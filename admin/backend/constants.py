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
    "anthropic-compat": "",
    "custom":     "https://api.example.com/v1",
}

# Provider -> api_mode mapping for Anthropic-compatible providers.
# When set, config.yaml includes `model.api_mode` so the agent uses the
# correct wire protocol without relying on URL heuristic detection.
PROVIDER_API_MODE_MAP: dict[str, str] = {
    "anthropic": "anthropic_messages",
    "anthropic-compat": "anthropic_messages",
    "minimax": "anthropic_messages",
}

# Admin-only provider names that must be remapped to agent-recognized names
# in config.yaml.  The admin dropdown uses distinct labels for UX, but the
# agent only knows about a fixed set of providers.
#
# Dependency chain for each entry:
#   PROVIDER_API_MODE_MAP  → determines api_mode in config.yaml
#   PROVIDER_AGENT_MAP     → determines provider field in config.yaml
#   PROVIDER_KEY_MAP (templates.py) → determines env var name in .env
# All three must agree: the env var must be one the agent checks for the
# remapped provider name.  E.g. minimax → custom in config → OPENAI_API_KEY
# in .env, because the agent's _resolve_openrouter_runtime() checks
# OPENAI_API_KEY for provider=custom.
PROVIDER_AGENT_MAP: dict[str, str] = {
    "anthropic-compat": "custom",
    "minimax": "custom",
}


def strip_v1_suffix(url: str) -> str:
    """Strip a trailing ``/v1`` from *url*.

    The Anthropic SDK appends ``/v1/messages`` to ``base_url``.  If the URL
    already ends with ``/v1`` (common for OpenAI-compatible endpoints like
    MiniMax's ``/anthropic/v1``), calling this avoids a double
    ``/v1/v1/messages``.
    """
    url = url.rstrip("/")
    return url.removesuffix("/v1") if url.endswith("/v1") else url


def determine_api_mode(provider: str) -> str | None:
    """Determine api_mode for config.yaml generation.

    Returns the resolved api_mode string, or None when the default
    (chat_completions) should be left implicit.
    """
    return PROVIDER_API_MODE_MAP.get(provider)


def resolve_agent_provider(provider: str) -> str:
    """Map an admin provider name to the value written in config.yaml.

    Admin-only providers (e.g. 'anthropic-compat') are remapped to a name
    the agent recognises; standard providers pass through unchanged.
    """
    return PROVIDER_AGENT_MAP.get(provider, provider)


# Anthropic-compatible providers that require Bearer auth instead of x-api-key.
# Must stay in sync with anthropic_adapter._requires_bearer_auth().
BEARER_AUTH_URL_PREFIXES = (
    "https://api.minimax.io/anthropic",
    "https://api.minimaxi.com/anthropic",
)


def is_bearer_auth_endpoint(base_url: str) -> bool:
    """Return True for Anthropic-compatible providers that require Bearer auth.

    Mirrors ``anthropic_adapter._requires_bearer_auth`` so the admin test path
    uses the same auth strategy as the runtime.
    """
    normalized = base_url.rstrip("/").lower()
    return normalized.startswith(BEARER_AUTH_URL_PREFIXES)


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
