"""Centralized auth module for Hermes Admin Panel — dual-mode authentication."""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import re
import secrets as _secrets
import time
from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, Header, HTTPException, Request

logger = logging.getLogger("hermes-admin.auth")

# ---------------------------------------------------------------------------
# AuthContext — returned by get_current_user dependency
# ---------------------------------------------------------------------------
@dataclass
class AuthContext:
    is_admin: bool
    agent_id: Optional[int] = None  # None for admin mode, set for user mode


# ---------------------------------------------------------------------------
# User token store (in-memory, same pattern as SSE/terminal tokens)
# ---------------------------------------------------------------------------
_user_tokens: dict[str, tuple[int, str, float]] = {}
# token -> (agent_id, api_key_sha256, expires_at)
USER_TOKEN_TTL = 7200  # 2 hours


def cleanup_expired_user_tokens() -> None:
    now = time.time()
    expired = [k for k, (_, _, exp) in _user_tokens.items() if now > exp]
    for k in expired:
        _user_tokens.pop(k, None)


def mint_user_token(agent_id: int, api_key: str) -> str:
    cleanup_expired_user_tokens()
    token = _secrets.token_urlsafe(32)
    api_key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    expires_at = time.time() + USER_TOKEN_TTL
    _user_tokens[token] = (agent_id, api_key_hash, expires_at)
    return token


def verify_user_token(token: str) -> Optional[tuple[int, str]]:
    """Returns (agent_id, api_key_hash) or None if invalid/expired."""
    entry = _user_tokens.get(token)
    if entry is None:
        return None
    agent_id, api_key_hash, expires_at = entry
    if time.time() > expires_at:
        _user_tokens.pop(token, None)
        return None
    return (agent_id, api_key_hash)


def revoke_user_token(token: str) -> bool:
    return _user_tokens.pop(token, None) is not None


def revoke_all_tokens_for_agent(agent_id: int) -> int:
    to_remove = [k for k, (aid, _, _) in _user_tokens.items() if aid == agent_id]
    for k in to_remove:
        _user_tokens.pop(k, None)
    return len(to_remove)


# ---------------------------------------------------------------------------
# Rate limiter for login endpoint (fixed window per IP)
# ---------------------------------------------------------------------------
_login_attempts: dict[str, tuple[int, float]] = {}  # ip -> (count, window_start)
LOGIN_RATE_LIMIT = 5  # attempts per minute per IP
LOGIN_RATE_WINDOW = 60  # seconds


def check_login_rate(ip: str) -> bool:
    """Returns True if rate limit exceeded."""
    now = time.time()
    count, window_start = _login_attempts.get(ip, (0, now))
    if now - window_start > LOGIN_RATE_WINDOW:
        _login_attempts[ip] = (1, now)
        return False
    if count >= LOGIN_RATE_LIMIT:
        return True
    _login_attempts[ip] = (count + 1, window_start)
    return False


# ---------------------------------------------------------------------------
# API key cache (sha256 -> agent_id)
# ---------------------------------------------------------------------------
_key_cache: dict[str, int] = {}
_key_cache_at: float = 0
KEY_CACHE_TTL = 60


async def refresh_key_cache() -> None:
    """Refresh api_key -> agent_id mapping from K8s Secrets."""
    global _key_cache, _key_cache_at
    if time.time() - _key_cache_at < KEY_CACHE_TTL and _key_cache:
        return

    from main import k8s
    secrets_list = await k8s.list_agent_secrets()
    new_cache: dict[str, int] = {}
    for secret in secrets_list:
        agent_id = _extract_agent_id(secret.metadata.name)
        if agent_id is None:
            continue
        api_key: str | None = None
        if secret.data and "api_key" in secret.data:
            api_key = base64.b64decode(secret.data["api_key"]).decode("utf-8")
        if api_key:
            key_hash = hashlib.sha256(api_key.encode()).hexdigest()
            new_cache[key_hash] = agent_id
    _key_cache = new_cache
    _key_cache_at = time.time()


def _extract_agent_id(secret_name: str) -> Optional[int]:
    """Extract agent_id from secret name like 'hermes-gateway-3-secret'."""
    m = re.match(r"^hermes-gateway-(\d+)-secret$", secret_name)
    if m:
        return int(m.group(1))
    if secret_name == "hermes-gateway-secret":
        return 0
    return None


async def find_agent_by_api_key(api_key: str) -> Optional[int]:
    """Find agent_id by matching api_key against K8s secrets."""
    await refresh_key_cache()
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    return _key_cache.get(key_hash)


def get_current_api_key_hash(agent_id: int) -> Optional[str]:
    """Get the cached api_key hash for an agent (for rebuild protection)."""
    for khash, aid in _key_cache.items():
        if aid == agent_id:
            return khash
    return None


# ---------------------------------------------------------------------------
# Dual-mode auth dependency
# ---------------------------------------------------------------------------
async def get_current_user(
    x_admin_key: str = Header(default="", alias="X-Admin-Key"),
    x_user_token: str = Header(default="", alias="X-User-Token"),
    request: Request = None,
) -> AuthContext:
    """Dual-mode auth: admin via X-Admin-Key, user via X-User-Token."""
    # Try user token first
    if x_user_token:
        result = verify_user_token(x_user_token)
        if result is None:
            raise HTTPException(status_code=401, detail="Invalid or expired user token")
        agent_id, stored_key_hash = result
        # Rebuild protection: verify api_key hash still matches
        current_hash = get_current_api_key_hash(agent_id)
        if current_hash is not None and current_hash != stored_key_hash:
            revoke_user_token(x_user_token)
            raise HTTPException(status_code=401, detail="Agent credentials changed, please re-login")
        request.state.agent_id = agent_id
        return AuthContext(is_admin=False, agent_id=agent_id)

    # Try admin key
    admin_key = getattr(request.app.state, "admin_key", "")
    if not admin_key:
        return AuthContext(is_admin=True)
    if x_admin_key and hmac.compare_digest(x_admin_key, admin_key):
        return AuthContext(is_admin=True)

    raise HTTPException(status_code=401, detail="Authentication required")


def get_effective_agent_id(request: Request, url_agent_id: int) -> int:
    """User mode forces session agent_id; admin mode uses URL param."""
    override = getattr(request.state, "agent_id", None)
    return override if override is not None else url_agent_id


# Convenience dependency
auth = Depends(get_current_user)
