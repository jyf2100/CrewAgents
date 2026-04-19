"""Shared constants and utilities for the Hermes Admin backend."""
from __future__ import annotations

import datetime
import re

# Pattern to detect secret environment variable names
SECRET_PATTERNS = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|AUTH)", re.IGNORECASE)

# Environment variable keys that must never be set by users
BLOCKED_ENV_KEYS = {
    "PATH", "HOME", "USER", "SHELL", "LD_PRELOAD", "LD_LIBRARY_PATH",
    "PYTHONPATH", "PYTHONHOME", "HOSTNAME", "TERM", "LANG", "LC_ALL",
    "PWD", "OLDPWD", "MAIL", "LOGNAME", "SSH_AUTH_SOCK", "DISPLAY",
    "XDG_RUNTIME_DIR", "container", "KUBERNETES_SERVICE_HOST",
    "KUBERNETES_SERVICE_PORT",
}

# Provider -> default API base URL mapping
PROVIDER_URL_MAP = {
    "openrouter": "https://openrouter.ai/api/v1",
    "anthropic":  "https://api.anthropic.com/v1",
    "openai":     "https://api.openai.com/v1",
    "gemini":     "https://generativelanguage.googleapis.com/v1beta",
    "zhipuai":    "https://open.bigmodel.cn/api/paas/v4",
    "minimax":    "https://api.minimaxi.com/anthropic/v1",
    "kimi":       "https://api.moonshot.cn/v1",
    "custom":     "https://api.example.com/v1",
}


def format_age(created: datetime.datetime | None) -> str:
    """Format a creation timestamp as a human-readable age string (e.g. '3d', '2h', '15m')."""
    if not created:
        return ""
    if created.tzinfo is None:
        created = created.replace(tzinfo=datetime.timezone.utc)
    delta = datetime.datetime.now(datetime.timezone.utc) - created
    if delta.days > 0:
        return f"{delta.days}d"
    if delta.seconds >= 3600:
        return f"{delta.seconds // 3600}h"
    return f"{delta.seconds // 60}m"
