"""
Hermes Setup Wizard Server.
Serves landing page (port 3000) and setup wizard (port 8643).
"""
import json
import os
import re
import secrets
import tempfile
from pathlib import Path
from typing import Optional

HERMES_HOME = os.environ.get("HERMES_HOME", "/opt/data")
ENV_PATH = os.path.join(HERMES_HOME, ".env")
CONFIG_PATH = os.path.join(HERMES_HOME, "config.yaml")
SETUP_MARKER = os.path.join(HERMES_HOME, ".setup_complete")

# Whitelist of allowed env var names (security)
ALLOWED_ENV_KEYS = frozenset({
    "MINIMAX_CN_API_KEY", "MINIMAX_CN_BASE_URL",
    "OPENROUTER_API_KEY",
    "GOOGLE_API_KEY", "GEMINI_API_KEY",
    "OPENAI_API_KEY", "OPENAI_BASE_URL",
    "WEIXIN_TOKEN", "WEIXIN_ACCOUNT_ID", "WEIXIN_BASE_URL",
    "TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_USERS",
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
    "API_SERVER_KEY",
})

UNSAFE_CHARS_RE = re.compile(r"[\n\r\x00`$|;&><]")


def validate_env_value(value: str) -> str:
    """Sanitize env value: reject newlines, null bytes, shell metacharacters."""
    if UNSAFE_CHARS_RE.search(value):
        raise ValueError("Value contains unsafe characters")
    return value.strip()


def read_env() -> dict[str, str]:
    """Read .env file into dict. Ignores comments and blank lines."""
    result = {}
    if not os.path.exists(ENV_PATH):
        return result
    with open(ENV_PATH) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                result[k.strip()] = v.strip()
    return result


def atomic_write(path: str, content: str) -> None:
    """Write file atomically: write to temp, then os.replace()."""
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_env(updates: dict[str, str]) -> None:
    """Write specific env vars into .env, preserving existing content."""
    for k, v in updates.items():
        if k not in ALLOWED_ENV_KEYS:
            raise ValueError(f"Disallowed env key: {k}")
        validate_env_value(v)

    existing = read_env()
    existing.update(updates)

    lines = []
    for k, v in existing.items():
        lines.append(f"{k}={v}")
    content = "\n".join(lines) + "\n"
    atomic_write(ENV_PATH, content)


def read_config_yaml() -> dict:
    """Read minimal config from config.yaml (no pyyaml dependency — parse manually)."""
    result = {"model": "", "provider": ""}
    if not os.path.exists(CONFIG_PATH):
        return result
    in_model = False
    with open(CONFIG_PATH) as f:
        for line in f:
            stripped = line.rstrip()
            if stripped == "model:" or stripped.startswith("model:"):
                in_model = True
                continue
            if in_model and stripped and not stripped[0].isspace():
                in_model = False
                continue
            if in_model:
                s = stripped.strip()
                if s.startswith("default:"):
                    result["model"] = s.split(":", 1)[1].strip().strip('"').strip("'")
                elif s.startswith("provider:"):
                    result["provider"] = s.split(":", 1)[1].strip().strip('"').strip("'")
    return result


def write_config_yaml(model: str, provider: str) -> None:
    """Write minimal config.yaml. This is authoritative — setup owns the config."""
    content = f"""model:
  default: "{model}"
  provider: "{provider}"

terminal:
  backend: "local"
  cwd: "."
  timeout: 180

memory:
  memory_enabled: true
  user_profile_enabled: true
  memory_char_limit: 2200
  user_char_limit: 1375
"""
    atomic_write(CONFIG_PATH, content)


def is_setup_complete() -> bool:
    return os.path.exists(SETUP_MARKER)


def mark_setup_complete() -> None:
    Path(SETUP_MARKER).touch()


def reset_setup() -> None:
    if os.path.exists(SETUP_MARKER):
        os.unlink(SETUP_MARKER)


_cached_api_key: Optional[str] = None

def ensure_api_server_key() -> str:
    """Get or generate API_SERVER_KEY, cache in memory."""
    global _cached_api_key
    if _cached_api_key:
        return _cached_api_key
    env = read_env()
    key = env.get("API_SERVER_KEY", "")
    if not key:
        key = secrets.token_hex(24)
        write_env({"API_SERVER_KEY": key})
    _cached_api_key = key
    return key


# --- Provider definitions ---
PROVIDERS = {
    "minimax-cn": {
        "label": "MiniMax (中国)",
        "desc": "推荐中国用户使用",
        "env_key": "MINIMAX_CN_API_KEY",
        "base_url": "https://api.minimaxi.com/v1",
        "default_model": "MiniMax-M2.7",
        "models": ["MiniMax-M2.7", "MiniMax-Text-01"],
        "get_key_url": "https://www.minimax.io",
        "show_proxy": True,
        "config_provider": "minimax-cn",
    },
    "openrouter": {
        "label": "OpenRouter",
        "desc": "Access to 100+ models",
        "env_key": "OPENROUTER_API_KEY",
        "base_url": "https://openrouter.ai/api/v1",
        "default_model": "anthropic/claude-sonnet-4-6",
        "models": ["anthropic/claude-sonnet-4-6", "google/gemini-2.5-flash", "deepseek/deepseek-chat"],
        "get_key_url": "https://openrouter.ai/keys",
        "show_proxy": False,
        "config_provider": "openrouter",
    },
    "gemini": {
        "label": "Google AI Studio",
        "desc": "Gemini models via Google",
        "env_key": "GOOGLE_API_KEY",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "default_model": "google/gemini-2.5-flash",
        "models": ["google/gemini-2.5-flash", "google/gemini-2.5-pro"],
        "get_key_url": "https://aistudio.google.com/app/apikey",
        "show_proxy": False,
        "config_provider": "gemini",
    },
    "custom": {
        "label": "Custom",
        "desc": "Any OpenAI-compatible endpoint",
        "env_key": "OPENAI_API_KEY",
        "base_url": "",
        "default_model": "",
        "models": [],
        "get_key_url": "",
        "show_proxy": False,
        "config_provider": "custom",
    },
}


def get_setup_status() -> dict:
    """Return non-sensitive config status for the frontend + pre-population data."""
    config = read_config_yaml()
    env = read_env()
    wechat_connected = bool(env.get("WEIXIN_TOKEN") and env.get("WEIXIN_ACCOUNT_ID"))
    telegram_connected = bool(env.get("TELEGRAM_BOT_TOKEN"))

    # Detect which provider has a key set
    active_provider = ""
    for pid, p in PROVIDERS.items():
        if env.get(p["env_key"]):
            active_provider = pid
            break

    # Mask API keys for pre-population (show first/last 4 chars)
    masked_keys = {}
    for pid, p in PROVIDERS.items():
        key = env.get(p["env_key"], "")
        if key and len(key) > 8:
            masked_keys[pid] = key[:4] + "..." + key[-4:]
        elif key:
            masked_keys[pid] = "****"

    return {
        "setup_complete": is_setup_complete(),
        "model": config.get("model", ""),
        "provider": config.get("provider", ""),
        "active_provider": active_provider,
        "wechat_connected": wechat_connected,
        "telegram_connected": telegram_connected,
        "has_api_key": bool(active_provider),
        "masked_keys": masked_keys,
        "proxy": env.get("HTTP_PROXY", ""),
        "providers": {k: {"label": v["label"], "desc": v["desc"], "models": v["models"],
                          "get_key_url": v["get_key_url"], "show_proxy": v["show_proxy"]}
                      for k, v in PROVIDERS.items()},
    }


# --- aiohttp server ---
import asyncio

from aiohttp import web

LANDING_PORT = 3000
WIZARD_PORT = 8643


def landing_page_html(status: dict) -> str:
    wechat_status = '<span style="color:#2ecc71">Connected</span>' if status["wechat_connected"] else '<span style="color:#888">Not connected</span>'
    telegram_status = '<span style="color:#2ecc71">Connected</span>' if status["telegram_connected"] else '<span style="color:#888">Not connected</span>'
    model_display = f'{status["model"]} ({status["provider"]})' if status["model"] else '<span style="color:#888">Not configured</span>'
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Hermes Agent</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#0F172A;color:#e0e0e0;
  display:flex;justify-content:center;align-items:center;min-height:100vh}}
.card{{background:#1E293B;border-radius:16px;padding:48px;text-align:center;max-width:440px;width:90%}}
h1{{color:#FFB800;margin-bottom:4px;font-size:28px}}
.version{{color:#64748B;margin-bottom:32px;font-size:14px}}
.btn-grid{{display:flex;gap:16px;justify-content:center;margin-bottom:32px}}
.btn{{display:inline-flex;align-items:center;gap:8px;padding:16px 28px;border-radius:12px;
  font-size:16px;font-weight:600;text-decoration:none;min-height:48px;cursor:pointer;border:none}}
.btn-chat{{background:#FFB800;color:#0F172A}}
.btn-chat:hover{{background:#E5A700}}
.btn-setup{{background:#334155;color:#e0e0e0;border:1px solid #475569}}
.btn-setup:hover{{background:#3D4F63}}
.status{{text-align:left;margin-top:16px}}
.status-row{{display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid #334155;font-size:14px}}
.status-label{{color:#94A3B8}}
</style>
</head>
<body>
<div class="card">
  <h1>Hermes Agent</h1>
  <p class="version">v0.8.0</p>
  <div class="btn-grid">
    <a href="http://localhost:3001" class="btn btn-chat">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
      Chat
    </a>
    <a href="http://localhost:8643/setup" class="btn btn-setup">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
      Settings
    </a>
  </div>
  <div class="status">
    <div class="status-row"><span class="status-label">Model</span><span>{model_display}</span></div>
    <div class="status-row"><span class="status-label">WeChat</span><span>{wechat_status}</span></div>
    <div class="status-row"><span class="status-label">Telegram</span><span>{telegram_status}</span></div>
  </div>
</div>
<script>
if (!{"true" if status.get("setup_complete") else "false"}) window.location.href = "http://localhost:8643/setup";
</script>
</body></html>"""


async def handle_landing(request: web.Request) -> web.Response:
    status = get_setup_status()
    return web.Response(text=landing_page_html(status), content_type="text/html")


async def handle_status(request: web.Request) -> web.Response:
    return web.json_response(get_setup_status())


@web.middleware
async def cors_middleware(request: web.Request, handler):
    resp = await handler(request)
    origin = request.headers.get("Origin", "")
    if origin in ("http://localhost:3000", "http://localhost:3001"):
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
    if request.method == "OPTIONS":
        resp.set_status(204)
    return resp


def create_app() -> web.Application:
    app = web.Application(middlewares=[cors_middleware])
    app.router.add_get("/", handle_landing)
    app.router.add_get("/status", handle_status)
    return app
