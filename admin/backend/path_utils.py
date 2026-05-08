"""Shared path validation utilities for file browser and terminal."""
from __future__ import annotations

import os
import time
from urllib.parse import unquote

from fastapi import HTTPException

ALLOWED_PREFIXES = ("/home", "/tmp", "/var/log", "/opt/hermes", "/opt/data")


def validate_path(path: str) -> str:
    """Sanitize and validate a filesystem path for pod access.

    Uses allowlist: only paths under ALLOWED_PREFIXES are accessible.
    Symlinks are resolved server-side via realpath in k8s exec commands.
    """
    path = unquote(path).strip()
    if not path.startswith("/"):
        path = "/" + path
    normalized = os.path.normpath(path)
    # Allowlist check
    allowed = any(normalized == prefix or normalized.startswith(prefix + "/") for prefix in ALLOWED_PREFIXES)
    if not allowed:
        raise HTTPException(status_code=403, detail="Access denied: path outside allowed directories")
    return normalized


def sanitize_filename(path: str) -> str:
    """Extract and sanitize a filename for Content-Disposition headers."""
    filename = os.path.basename(path) or "file"
    return filename.replace('"', "'").replace("\r", "").replace("\n", "")


UPLOAD_ALLOWED_PREFIX = "/opt/data/skills"
MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10MB


def validate_upload_path(path: str) -> str:
    """Validate that a path is writable (only /opt/data/skills). Returns normalized path."""
    path = unquote(path).strip()
    if not path.startswith("/"):
        path = "/" + path
    normalized = os.path.normpath(path)
    if normalized != UPLOAD_ALLOWED_PREFIX and not normalized.startswith(UPLOAD_ALLOWED_PREFIX + "/"):
        raise HTTPException(status_code=403, detail="Upload only allowed under /opt/data/skills")
    basename = os.path.basename(normalized)
    if basename and not all(c.isalnum() or c in "._-+" for c in basename):
        raise HTTPException(status_code=400, detail="Invalid filename: use only alphanumeric, dot, underscore, hyphen, plus")
    return normalized


# ---------------------------------------------------------------------------
# Rate limiter for file browser endpoints (in-memory, per agent_id)
# ---------------------------------------------------------------------------
_rate_limit_store: dict[int, list[float]] = {}
FILE_BROWSER_RATE_LIMIT = 60  # requests per minute per agent_id


def check_file_rate_limit(agent_id: int) -> None:
    """Raise 429 if agent_id exceeded FILE_BROWSER_RATE_LIMIT in the last 60s."""
    now = time.time()
    window = 60  # 1 minute
    requests = _rate_limit_store.get(agent_id, [])
    # Remove old entries
    requests = [t for t in requests if now - t < window]
    if len(requests) >= FILE_BROWSER_RATE_LIMIT:
        raise HTTPException(status_code=429, detail="Too many requests. Please wait a moment.")
    requests.append(now)
    _rate_limit_store[agent_id] = requests
