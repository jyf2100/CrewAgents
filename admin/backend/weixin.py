"""
WeChat (Weixin) QR login orchestration for the Hermes Admin panel.

Provides SSE-based QR login flow that the admin frontend can consume
via EventSource.  Credentials are persisted to the agent's .env file
and a per-account JSON file under the agent data directory.

Design notes:
- Uses httpx for async HTTP (already in requirements).
- SSE events: qr_ready, status_update, qr_refresh, done, timeout, error.
- Concurrent sessions are guarded by ``_weixin_qr_sessions`` so that at
  most one QR login runs per agent at a time.
- All file writes use the atomic .tmp + os.replace pattern.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, AsyncGenerator, Optional

import httpx

logger = logging.getLogger("hermes-admin.weixin")

# ---------------------------------------------------------------------------
# iLink API constants (mirrored from gateway/platforms/weixin.py)
# ---------------------------------------------------------------------------
ILINK_BASE_URL = "https://ilinkai.weixin.qq.com"
EP_GET_BOT_QR = "ilink/bot/get_bot_qrcode"
EP_GET_QR_STATUS = "ilink/bot/get_qrcode_status"

ILINK_APP_ID = "bot"
ILINK_APP_CLIENT_VERSION = (2 << 16) | (2 << 8) | 0

QR_TIMEOUT_SECONDS = 480  # 8 minutes
MAX_QR_REFRESHES = 3
POLL_INTERVAL_SECONDS = 1

# ---------------------------------------------------------------------------
# SSE helper
# ---------------------------------------------------------------------------


def _sse(event: str, data: Any) -> str:
    """Format a single SSE frame."""
    payload = json.dumps(data, ensure_ascii=False) if not isinstance(data, str) else data
    return f"event: {event}\ndata: {payload}\n\n"


def _generate_qr_data_url(qrcode_value: str, qrcode_img_url: str = "") -> str:
    """Generate a high-res base64 PNG data URL from the iLink QR data.

    Encodes the liteapp URL (from qrcode_img_content) into a QR image.
    Falls back to encoding the raw qrcode value if the URL is unavailable.

    IMPORTANT: This is a CPU-bound function. Call via run_in_executor()
    to avoid blocking the asyncio event loop.
    """
    import io
    import base64
    import qrcode as qrcode_lib
    qr = qrcode_lib.QRCode(version=1, box_size=10, border=2,
                            error_correction=qrcode_lib.constants.ERROR_CORRECT_M)
    content = qrcode_img_url if qrcode_img_url else qrcode_value
    qr.add_data(content)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    return f"data:image/png;base64,{b64}"


# ---------------------------------------------------------------------------
# Concurrent session guard (agent_id -> timestamp)
# ---------------------------------------------------------------------------
_weixin_qr_sessions: dict[int, float] = {}
_SESSION_TTL_SECONDS = 600  # 10 min — covers QR_TIMEOUT_SECONDS + buffer


def _cleanup_stale_sessions() -> None:
    """Evict sessions older than TTL."""
    now = time.time()
    stale = [aid for aid, ts in _weixin_qr_sessions.items() if now - ts > _SESSION_TTL_SECONDS]
    for aid in stale:
        _weixin_qr_sessions.pop(aid, None)


def start_qr_session(agent_id: int) -> str:
    """Register a new QR login session.  Raises if one is already active."""
    _cleanup_stale_sessions()
    if agent_id in _weixin_qr_sessions:
        raise RuntimeError(f"QR login already in progress for agent {agent_id}")
    _weixin_qr_sessions[agent_id] = time.time()
    return f"wx-qr-{agent_id}-{int(time.time())}"


def end_qr_session(agent_id: int) -> None:
    """Remove the session guard for *agent_id*."""
    _weixin_qr_sessions.pop(agent_id, None)


# ---------------------------------------------------------------------------
# iLink HTTP helpers
# ---------------------------------------------------------------------------

_ILINK_HEADERS = {
    "iLink-App-Id": ILINK_APP_ID,
    "iLink-App-ClientVersion": str(ILINK_APP_CLIENT_VERSION),
}


async def _ilink_get(client: httpx.AsyncClient, url: str, timeout: float = 15.0) -> dict[str, Any]:
    """GET request to iLink API with standard headers."""
    resp = await client.get(url, headers=_ILINK_HEADERS, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Credential persistence
# ---------------------------------------------------------------------------


def _update_env_file(env_path: str, updates: dict[str, str]) -> None:
    """Atomically update selected variables in a .env file.

    Only the keys present in *updates* are touched; all other lines are
    preserved verbatim.  Keys with a value of ``""`` are removed.
    """
    lines: list[str] = []
    if os.path.isfile(env_path):
        with open(env_path) as fh:
            lines = fh.readlines()

    remove_keys = {k for k, v in updates.items() if v == ""}
    update_map = {k: v for k, v in updates.items() if v != ""}
    updated_keys: set[str] = set()
    new_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            new_lines.append(line)
            continue
        if "=" in stripped:
            key, _, _ = stripped.partition("=")
            key = key.strip()
            if key in remove_keys:
                continue  # drop the line
            if key in update_map:
                new_lines.append(f"{key}={update_map[key]}\n")
                updated_keys.add(key)
                continue
        new_lines.append(line)

    for key, value in update_map.items():
        if key not in updated_keys:
            new_lines.append(f"{key}={value}\n")

    tmp_path = env_path + ".tmp"
    os.makedirs(os.path.dirname(env_path), exist_ok=True)
    with open(tmp_path, "w") as fh:
        fh.writelines(new_lines)
    os.replace(tmp_path, env_path)


def _save_credentials(
    agent_dir: str,
    *,
    account_id: str,
    token: str,
    base_url: str,
    user_id: str,
) -> None:
    """Persist Weixin credentials to .env and an account JSON file."""
    # 1) Update .env
    env_path = os.path.join(agent_dir, ".env")
    _update_env_file(env_path, {
        "WEIXIN_ACCOUNT_ID": account_id,
        "WEIXIN_TOKEN": token,
        "WEIXIN_BASE_URL": base_url,
    })

    # 2) Save account JSON
    accounts_dir = os.path.join(agent_dir, "weixin", "accounts")
    os.makedirs(accounts_dir, exist_ok=True)
    # Ensure the agent process (runs as 'hermes' user) can write here
    os.chmod(accounts_dir, 0o777)
    account_file = os.path.join(accounts_dir, f"{account_id}.json")
    payload = {
        "account_id": account_id,
        "token": token,
        "base_url": base_url,
        "user_id": user_id,
        "bound_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    tmp_path = account_file + ".tmp"
    with open(tmp_path, "w") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    os.replace(tmp_path, account_file)
    try:
        os.chmod(account_file, 0o666)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# QR login SSE stream
# ---------------------------------------------------------------------------


async def stream_weixin_qr(agent_id: int, agent_dir: str, restart_callback=None) -> AsyncGenerator[str, None]:
    """Async generator yielding SSE events for a Weixin QR login flow.

    Yields events: qr_ready, status_update, qr_refresh, done, timeout, error.
    Always cleans up the session guard in a ``finally`` block.

    Args:
        restart_callback: Optional async callable(agent_id) to restart the agent
            after successful binding. If None, creates a temporary K8sClient.
    """
    session_id: Optional[str] = None
    try:
        session_id = start_qr_session(agent_id)
    except RuntimeError as exc:
        yield _sse("error", {"message": str(exc)})
        return

    try:
        async with httpx.AsyncClient() as client:
            # -- fetch initial QR code --
            try:
                qr_resp = await _ilink_get(
                    client,
                    f"{ILINK_BASE_URL}/{EP_GET_BOT_QR}?bot_type=3",
                    timeout=15.0,
                )
            except Exception as exc:
                logger.error("weixin: failed to fetch QR code for agent %d: %s", agent_id, exc)
                yield _sse("error", {"message": f"Failed to fetch QR code: {exc}"})
                return

            qrcode_value = str(qr_resp.get("qrcode") or "")
            qrcode_img_url = str(qr_resp.get("qrcode_img_content") or "")
            logger.info("weixin: QR response for agent %d: keys=%s, qrcode=%s..., img_url=%s",
                        agent_id, list(qr_resp.keys()),
                        qrcode_value[:20] if qrcode_value else "EMPTY",
                        qrcode_img_url[:60] if qrcode_img_url else "EMPTY")
            if not qrcode_value:
                yield _sse("error", {"message": "QR response missing qrcode value"})
                return

            # Generate QR code image encoding the liteapp URL (offload CPU work)
            loop = asyncio.get_event_loop()
            qrcode_data_url = await loop.run_in_executor(
                None, _generate_qr_data_url, qrcode_value, qrcode_img_url
            )

            yield _sse("qr_ready", {
                "qrcode_url": qrcode_data_url,
                "session_id": session_id,
            })

            deadline = time.time() + QR_TIMEOUT_SECONDS
            current_base_url = ILINK_BASE_URL
            refresh_count = 0

            while time.time() < deadline:
                # -- poll status --
                try:
                    status_resp = await _ilink_get(
                        client,
                        f"{current_base_url}/{EP_GET_QR_STATUS}?qrcode={qrcode_value}",
                        timeout=15.0,
                    )
                except httpx.TimeoutException:
                    yield _sse("status_update", {"status": "wait", "detail": "poll_timeout"})
                    await asyncio.sleep(POLL_INTERVAL_SECONDS)
                    continue
                except Exception as exc:
                    logger.warning("weixin: QR poll error for agent %d: %s", agent_id, exc)
                    yield _sse("status_update", {"status": "wait", "detail": f"poll_error: {exc}"})
                    await asyncio.sleep(POLL_INTERVAL_SECONDS)
                    continue

                status = str(status_resp.get("status") or "wait")

                if status == "wait":
                    yield _sse("status_update", {"status": "wait"})

                elif status == "scaned":
                    yield _sse("status_update", {"status": "scaned", "message": "QR code scanned, waiting for confirmation"})

                elif status == "scaned_but_redirect":
                    redirect_host = str(status_resp.get("redirect_host") or "")
                    if redirect_host:
                        current_base_url = f"https://{redirect_host}"
                    yield _sse("status_update", {"status": "scaned_but_redirect", "redirect_host": redirect_host})

                elif status == "expired":
                    refresh_count += 1
                    if refresh_count > MAX_QR_REFRESHES:
                        yield _sse("timeout", {"message": "QR code expired too many times"})
                        return
                    # Fetch a fresh QR code
                    try:
                        qr_resp = await _ilink_get(
                            client,
                            f"{ILINK_BASE_URL}/{EP_GET_BOT_QR}?bot_type=3",
                            timeout=15.0,
                        )
                        new_value = str(qr_resp.get("qrcode") or "")
                        new_img_url = str(qr_resp.get("qrcode_img_content") or "")
                        if not new_value:
                            yield _sse("error", {"message": "QR refresh returned empty qrcode"})
                            return
                        qrcode_value = new_value
                        new_data_url = await loop.run_in_executor(
                            None, _generate_qr_data_url, new_value, new_img_url
                        )
                        yield _sse("qr_refresh", {
                            "qrcode_url": new_data_url,
                            "refresh_count": refresh_count,
                            "max_refreshes": MAX_QR_REFRESHES,
                        })
                    except Exception as exc:
                        logger.error("weixin: QR refresh failed for agent %d: %s", agent_id, exc)
                        yield _sse("error", {"message": f"QR refresh failed: {exc}"})
                        return

                elif status == "confirmed":
                    account_id = str(status_resp.get("ilink_bot_id") or "")
                    token = str(status_resp.get("bot_token") or "")
                    base_url = str(status_resp.get("baseurl") or ILINK_BASE_URL)
                    user_id = str(status_resp.get("ilink_user_id") or "")

                    if not account_id or not token:
                        yield _sse("error", {"message": "Login confirmed but credential payload was incomplete"})
                        return

                    try:
                        _save_credentials(
                            agent_dir,
                            account_id=account_id,
                            token=token,
                            base_url=base_url,
                            user_id=user_id,
                        )
                    except Exception as exc:
                        logger.error("weixin: credential save failed for agent %d: %s", agent_id, exc)
                        yield _sse("error", {"message": f"Failed to save credentials: {exc}"})
                        return

                    yield _sse("done", {
                        "account_id": account_id,
                        "user_id": user_id,
                        "base_url": base_url,
                    })

                    # Restart agent so it picks up the new WEIXIN_* env vars
                    try:
                        if restart_callback:
                            await restart_callback(agent_id)
                        else:
                            from agent_manager import AgentManager
                            from k8s_client import K8sClient
                            ns = os.getenv("K8S_NAMESPACE", "hermes-agent")
                            _k8s = K8sClient(namespace=ns)
                            _mgr = AgentManager(k8s=_k8s, namespace=ns, config_mgr=None)
                            await _mgr.restart_agent(agent_id)
                        logger.info("weixin: triggered agent %d restart after WeChat binding", agent_id)
                    except Exception as exc:
                        logger.warning("weixin: failed to restart agent %d after binding: %s", agent_id, exc)
                    return

                await asyncio.sleep(POLL_INTERVAL_SECONDS)

            # Deadline reached
            yield _sse("timeout", {"message": f"QR login timed out after {QR_TIMEOUT_SECONDS}s"})

    except Exception as exc:
        logger.exception("weixin: unexpected error in QR stream for agent %d", agent_id)
        yield _sse("error", {"message": f"Unexpected error: {exc}"})
    finally:
        end_qr_session(agent_id)


# ---------------------------------------------------------------------------
# Status reader
# ---------------------------------------------------------------------------


def read_weixin_status(agent_dir: str, agent_id: int) -> dict[str, Any]:
    """Read current Weixin binding status for an agent.

    Returns a dict matching the frontend ``WeixinStatus`` interface:
      - connected (bool)
      - account_id, user_id, base_url
      - bound_at (from account JSON, if present)
      - dm_policy, group_policy (from config.yaml, if present)
    """
    result: dict[str, Any] = {
        "agent_number": agent_id,
        "connected": False,
        "account_id": "",
        "user_id": "",
        "base_url": "",
        "dm_policy": "open",
        "group_policy": "disabled",
        "bound_at": None,
    }

    # Read .env for WEIXIN_ variables
    env_path = os.path.join(agent_dir, ".env")
    if os.path.isfile(env_path):
        env_vars: dict[str, str] = {}
        with open(env_path) as fh:
            for line in fh:
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if "=" not in stripped:
                    continue
                key, _, value = stripped.partition("=")
                env_vars[key.strip()] = value.strip().strip("\"'")

        account_id = env_vars.get("WEIXIN_ACCOUNT_ID", "")
        token = env_vars.get("WEIXIN_TOKEN", "")
        base_url = env_vars.get("WEIXIN_BASE_URL", "")

        if account_id:
            result["connected"] = True
            result["account_id"] = account_id
            result["base_url"] = base_url or ""

    # Read account JSON for bound_at and user_id
    if result["account_id"]:
        account_file = os.path.join(agent_dir, "weixin", "accounts", f"{result['account_id']}.json")
        if os.path.isfile(account_file):
            try:
                with open(account_file) as fh:
                    data = json.load(fh)
                result["bound_at"] = data.get("bound_at")
                result["user_id"] = data.get("user_id")
            except Exception:
                pass

    # Read config.yaml for dm_policy / group_policy
    config_path = os.path.join(agent_dir, "config.yaml")
    if os.path.isfile(config_path):
        try:
            import yaml
            with open(config_path) as fh:
                cfg = yaml.safe_load(fh) or {}
            weixin_cfg = (cfg.get("platforms") or {}).get("weixin") or {}
            if isinstance(weixin_cfg, dict):
                result["dm_policy"] = weixin_cfg.get("dm_policy") or "open"
                result["group_policy"] = weixin_cfg.get("group_policy") or "disabled"
        except Exception:
            pass

    return result


# ---------------------------------------------------------------------------
# Unbind
# ---------------------------------------------------------------------------


def unbind_weixin(agent_dir: str, agent_id: int) -> dict[str, Any]:
    """Remove Weixin binding for an agent.

    - Removes WEIXIN_* vars from .env
    - Sets weixin.enabled=false in config.yaml (if the section exists)
    - Deletes the weixin/accounts directory
    """
    # 1) Remove WEIXIN_ vars from .env
    env_path = os.path.join(agent_dir, ".env")
    if os.path.isfile(env_path):
        _update_env_file(env_path, {
            "WEIXIN_ACCOUNT_ID": "",
            "WEIXIN_TOKEN": "",
            "WEIXIN_BASE_URL": "",
        })

    # 2) Set weixin.enabled=false in config.yaml
    config_path = os.path.join(agent_dir, "config.yaml")
    if os.path.isfile(config_path):
        try:
            import yaml
            with open(config_path) as fh:
                cfg = yaml.safe_load(fh) or {}
            platforms = cfg.setdefault("platforms", {})
            weixin_cfg = platforms.setdefault("weixin", {})
            if isinstance(weixin_cfg, dict):
                weixin_cfg["enabled"] = False
            tmp_path = config_path + ".tmp"
            with open(tmp_path, "w") as fh:
                yaml.dump(cfg, fh, default_flow_style=False, allow_unicode=True)
            os.replace(tmp_path, config_path)
        except Exception as exc:
            logger.warning("weixin: failed to update config.yaml for agent %d: %s", agent_id, exc)

    # 3) Delete accounts directory
    accounts_dir = os.path.join(agent_dir, "weixin", "accounts")
    if os.path.isdir(accounts_dir):
        import shutil
        try:
            shutil.rmtree(accounts_dir)
        except Exception as exc:
            logger.warning("weixin: failed to remove accounts dir for agent %d: %s", agent_id, exc)

    return {"agent_id": agent_id, "unbound": True}
