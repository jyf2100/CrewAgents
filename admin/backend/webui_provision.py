"""WebUI auto-provisioning — admin-created users, Direct Connection config."""
from __future__ import annotations

import base64
import logging
import os
import secrets as _secrets
import time

import httpx

logger = logging.getLogger("hermes-admin.webui_provision")

WEBUI_INTERNAL_URL = os.getenv("WEBUI_INTERNAL_URL", "http://hermes-webui:8080")
WEBUI_ADMIN_EMAIL = os.getenv("WEBUI_ADMIN_EMAIL", "rocju315@gmail.com")
WEBUI_ADMIN_PASSWORD = os.getenv("WEBUI_ADMIN_PASSWORD", "")
EXTERNAL_WEBUI_URL = os.getenv("EXTERNAL_WEBUI_URL", "http://localhost:48080")
EXTERNAL_API_BASE = os.getenv("EXTERNAL_API_BASE", "")
JWT_REFRESH_BUFFER = 3600

_admin_jwt: str | None = None
_admin_jwt_expires: float = 0


async def _webui_request(method: str, path: str, **kwargs) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        url = f"{WEBUI_INTERNAL_URL}{path}"
        resp = await getattr(client, method)(url, **kwargs)
        if resp.status_code >= 400:
            raise Exception(f"WebUI API error {resp.status_code}: {resp.text[:200]}")
        return resp.json()


async def _get_admin_jwt() -> str:
    global _admin_jwt, _admin_jwt_expires
    if _admin_jwt and _admin_jwt_expires > time.time() + JWT_REFRESH_BUFFER:
        return _admin_jwt

    if not WEBUI_ADMIN_PASSWORD:
        raise Exception("WEBUI_ADMIN_PASSWORD not configured")

    result = await _webui_request("post", "/api/v1/auths/signin", json={
        "email": WEBUI_ADMIN_EMAIL,
        "password": WEBUI_ADMIN_PASSWORD,
    })
    _admin_jwt = result["token"]
    _admin_jwt_expires = time.time() + 28 * 24 * 3600
    return _admin_jwt


async def _admin_create_user(email: str, password: str, name: str) -> str:
    admin_jwt = await _get_admin_jwt()
    try:
        result = await _webui_request("post", "/api/v1/auths/add",
            headers={"Authorization": f"Bearer {admin_jwt}"},
            json={
                "email": email,
                "password": password,
                "name": name,
                "role": "user",
            },
        )
        return result.get("id", "")
    except Exception as e:
        if "409" in str(e) or "already" in str(e).lower():
            logger.info("WebUI user %s already exists, resetting password", email)
            await _reset_existing_user(email, password, name, admin_jwt)
            return ""
        raise


async def _reset_existing_user(email: str, password: str, name: str, admin_jwt: str) -> None:
    """Reset an existing WebUI user: delete + recreate to avoid user/auth ID mismatch."""
    users = await _webui_request("get", "/api/v1/users/",
        headers={"Authorization": f"Bearer {admin_jwt}"})
    user_list = users if isinstance(users, list) else users.get("users", [])

    uid = None
    for u in user_list:
        if u.get("email") == email:
            uid = u.get("id")
            break

    if uid:
        try:
            await _webui_request("delete", f"/api/v1/users/{uid}",
                headers={"Authorization": f"Bearer {admin_jwt}"})
            logger.info("Deleted existing WebUI user %s (id=%s) for clean recreation", email, uid)
        except Exception as del_err:
            logger.warning("Failed to delete WebUI user %s: %s, attempting recreate anyway", email, del_err)

    await _webui_request("post", "/api/v1/auths/add",
        headers={"Authorization": f"Bearer {admin_jwt}"},
        json={
            "email": email,
            "password": password,
            "name": name,
            "role": "user",
        })
    logger.info("Recreated WebUI user %s with matching IDs", email)


async def signin(email: str, password: str) -> tuple[str, float]:
    result = await _webui_request("post", "/api/v1/auths/signin", json={
        "email": email, "password": password,
    })
    jwt_token = result["token"]
    expires_at = time.time() + 28 * 24 * 3600
    return jwt_token, expires_at


async def signup_webui_user(email: str, password: str, name: str) -> str:
    """公开 signup 接口注册 WebUI 用户，无需管理员密码。"""
    try:
        result = await _webui_request("post", "/api/v1/auths/signup", json={
            "email": email, "password": password, "name": name,
        })
        return result.get("id", "")
    except Exception as e:
        if "409" in str(e) or "already" in str(e).lower():
            logger.info("WebUI user %s already exists, skipping signup", email)
            return ""
        raise


async def get_or_refresh_jwt(user) -> str:
    if (user.webui_jwt and user.webui_jwt_expires_at
            and user.webui_jwt_expires_at > time.time() + JWT_REFRESH_BUFFER):
        return user.webui_jwt

    if not user.webui_password:
        raise Exception(f"No WebUI password for {user.email}, re-provision required")

    jwt_token, expires_at = await signin(user.email, user.webui_password)
    user.webui_jwt = jwt_token
    user.webui_jwt_expires_at = expires_at
    return jwt_token


async def configure_direct_connection(jwt_token: str, api_url: str, api_key: str) -> None:
    # model_ids=[] forces WebUI frontend to call getOpenAIModelsDirect()
    # for live model discovery instead of using a static list.
    configs = {"0": {
        "enable": True,
        "tags": [],
        "prefix_id": "hermes",
        "model_ids": [],
        "connection_type": "external",
        "auth_type": "bearer",
    }}

    await _webui_request("post", "/api/v1/users/user/settings/update",
        headers={"Authorization": f"Bearer {jwt_token}"},
        json={
            "directConnections": {
                "OPENAI_API_BASE_URLS": [api_url],
                "OPENAI_API_KEYS": [api_key],
                "OPENAI_API_CONFIGS": configs,
            },
        },
    )


async def get_agent_api_key(agent_id: int) -> str:
    from main import k8s
    secret = await k8s.get_secret(f"hermes-gateway-{agent_id}-secret")
    if not secret or not secret.data:
        raise Exception(f"Secret hermes-gateway-{agent_id}-secret not found")
    raw = secret.data.get("api_key", "")
    return base64.b64decode(raw).decode("utf-8")


async def delete_webui_user(email: str) -> None:
    """Delete a WebUI user by email (both user and auth records). Best-effort."""
    try:
        admin_jwt = await _get_admin_jwt()
    except Exception:
        logger.warning("Cannot get WebUI admin JWT, skipping WebUI cleanup for %s", email)
        return

    users = await _webui_request("get", "/api/v1/users/",
        headers={"Authorization": f"Bearer {admin_jwt}"})
    user_list = users if isinstance(users, list) else users.get("users", [])

    uid = None
    for u in user_list:
        if u.get("email") == email:
            uid = u.get("id")
            break

    if uid:
        try:
            await _webui_request("delete", f"/api/v1/users/{uid}",
                headers={"Authorization": f"Bearer {admin_jwt}"})
            logger.info("Deleted WebUI user %s (id=%s)", email, uid)
        except Exception as e:
            logger.warning("Failed to delete WebUI user %s: %s", email, e)


async def provision_user(user, agent_id: int) -> None:
    if not EXTERNAL_API_BASE:
        raise Exception("EXTERNAL_API_BASE env var is required but not set")

    password = user.webui_password

    if not password:
        user.provisioning_status = "failed"
        user.provisioning_error = "No WebUI password stored for user"
        user.provisioning_updated_at = time.time()
        return

    # 登录获取 JWT（注册时已创建 WebUI 账号）
    try:
        jwt_token, expires_at = await signin(user.email, password)
    except Exception:
        # 密码不匹配（旧用户残留），用 admin API 强制重置
        logger.warning("Signin failed for %s, resetting via admin API", user.email)
        await _admin_create_user(user.email, password, user.display_name or user.email)
        jwt_token, expires_at = await signin(user.email, password)

    api_url = f"{EXTERNAL_API_BASE}/agent{agent_id}/v1"
    api_key = await get_agent_api_key(agent_id)

    await configure_direct_connection(jwt_token, api_url, api_key)

    user.webui_jwt = jwt_token
    user.webui_jwt_expires_at = expires_at
    user.provisioning_status = "completed"
    user.provisioning_error = None
    user.provisioning_updated_at = time.time()
