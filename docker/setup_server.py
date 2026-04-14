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
    """Write file safely. Uses os.replace() for atomicity; falls back to
    direct write for bind-mounted files where rename across mounts fails."""
    parent = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=parent)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
        try:
            os.replace(tmp, path)
        except OSError:
            # Bind-mounted files can't be replaced via rename — write directly
            os.unlink(tmp)
            with open(path, "w") as f:
                f.write(content)
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
    """Get or generate API_SERVER_KEY. Called once at startup; returns cached value thereafter."""
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


def get_api_key() -> str:
    """Return the cached API key. Raises if not initialized."""
    if not _cached_api_key:
        raise RuntimeError("API key not initialized — call ensure_api_server_key() first")
    return _cached_api_key


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

import aiohttp
from aiohttp import web

LANDING_PORT = 3080
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
if ('serviceWorker' in navigator) navigator.serviceWorker.getRegistrations().then(rs => rs.forEach(r => r.unregister()));
if (!{"true" if status.get("setup_complete") else "false"}) window.location.href = "http://localhost:8643/setup";
</script>
</body></html>"""


async def handle_landing(request: web.Request) -> web.Response:
    status = get_setup_status()
    resp = web.Response(text=landing_page_html(status), content_type="text/html")
    # Force clear all browser data (cache, service workers, storage) from previous
    # Open WebUI installation that was on this port. This is a one-time fix.
    resp.headers["Clear-Site-Data"] = '"cache", "storage", "executionContexts"'
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    return resp


async def handle_status(request: web.Request) -> web.Response:
    """Public status — strips sensitive data. Full status requires auth."""
    status = get_setup_status()
    # Remove sensitive fields for unauthenticated access
    status.pop("masked_keys", None)
    status.pop("proxy", None)
    return web.json_response(status)


async def handle_status_authed(request: web.Request) -> web.Response:
    """Authenticated status — includes masked keys and proxy for pre-population."""
    if not _check_auth(request):
        return web.json_response({"error": "Unauthorized"}, status=401)
    return web.json_response(get_setup_status())


@web.middleware
async def cors_middleware(request: web.Request, handler):
    # Handle OPTIONS preflight before dispatching to handler
    if request.method == "OPTIONS":
        resp = web.Response(status=204)
    else:
        resp = await handler(request)
    origin = request.headers.get("Origin", "")
    if origin in ("http://localhost:3000", "http://localhost:3001"):
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
    return resp


async def handle_manifest(request: web.Request) -> web.Response:
    """Return minimal PWA manifest to avoid 404 in browser console."""
    return web.json_response({
        "name": "Hermes Agent",
        "short_name": "Hermes",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#0F172A",
        "theme_color": "#FFB800",
    })


# Self-unregistering service worker that replaces any old SW (e.g. Open WebUI)
# left over from a previous installation on this port.
# The browser checks for SW script updates from the network, so it will fetch
# this script and replace the old SW. This script clears caches and unregisters.
_SELF_DESTRUCT_SW_JS = r"""
// Hermes replacement SW: clear all cached data and self-unregister.
// This removes service workers left by previous installations (e.g. Open WebUI).
self.addEventListener('install', function(event) {
  event.waitUntil(
    caches.keys().then(function(names) {
      return Promise.all(names.map(function(n) { return caches.delete(n); }));
    }).then(function() { return self.skipWaiting(); })
  );
});
self.addEventListener('activate', function(event) {
  event.waitUntil(
    self.registration.unregister().then(function() {
      return self.clients.matchAll();
    }).then(function(clients) {
      clients.forEach(function(c) { c.navigate(c.url); });
      return self.clients.claim();
    })
  );
});
// Pass-through: never intercept requests
self.addEventListener('fetch', function(event) {
  event.respondWith(fetch(event.request));
});
"""


async def handle_sw_js(request: web.Request) -> web.Response:
    """Serve a self-unregistering SW to replace any leftover SW from a prior app."""
    resp = web.Response(
        text=_SELF_DESTRUCT_SW_JS,
        content_type="application/javascript",
    )
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    resp.headers["Clear-Site-Data"] = '"cache", "storage", "executionContexts"'
    return resp


async def handle_catch_all(request: web.Request) -> web.Response:
    """Catch-all for old Open WebUI paths.

    When a browser has a registered SW from a previous app (e.g. Open WebUI)
    on this port, it periodically fetches the SW script URL to check for updates.
    Since the old app is gone, those fetches 404 and the stale SW keeps serving
    cached content.

    Strategy:
    - .js paths → return self-destruct SW (browser treats this as an updated SW
      and replaces the old registration, which then clears caches and unregisters)
    - All other paths → return the landing page HTML (so direct URL access works)
    """
    path = request.path
    if path.endswith(".js"):
        # Serve self-destruct SW to replace any old SW registration
        resp = web.Response(
            text=_SELF_DESTRUCT_SW_JS,
            content_type="application/javascript",
        )
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        resp.headers["Clear-Site-Data"] = '"cache", "storage", "executionContexts"'
        return resp
    else:
        # Return landing page for all other unknown paths (CSS, images, etc.)
        return await handle_landing(request)


def create_app() -> web.Application:
    app = web.Application(middlewares=[cors_middleware])
    app.router.add_get("/", handle_landing)
    app.router.add_get("/status", handle_status)
    app.router.add_get("/manifest.json", handle_manifest)
    app.router.add_get("/sw.js", handle_sw_js)
    # Catch-all MUST be last — returns self-destruct SW for any old SW script URL
    app.router.add_get("/{path:.*}", handle_catch_all)
    return app


WIZARD_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Hermes Setup Wizard</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
*:focus-visible{outline:2px solid #FFB800;outline-offset:2px}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#0F172A;color:#e0e0e0;
  display:flex;justify-content:center;align-items:flex-start;min-height:100vh;padding:32px 16px}
.card{background:#1E293B;border-radius:16px;padding:32px;max-width:480px;width:100%}
h1{color:#FFB800;font-size:24px;margin-bottom:4px;text-align:center}
.step-indicator{color:#64748B;font-size:14px;text-align:center;margin-bottom:24px}
.step{display:none}
.step.active{display:block}
label{display:block;color:#94A3B8;font-size:13px;margin-bottom:4px;margin-top:16px}
label:first-child{margin-top:0}
input,select{width:100%;padding:12px 16px;border-radius:12px;border:1px solid #334155;
  background:#0F172A;color:#e0e0e0;font-size:15px;min-height:48px;appearance:none;-webkit-appearance:none}
select{background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%2394A3B8' stroke-width='2'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E");
  background-repeat:no-repeat;background-position:right 16px center;padding-right:40px}
input::placeholder{color:#475569}
.btn-row{display:flex;gap:12px;margin-top:24px}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;padding:14px 24px;
  border-radius:12px;font-size:15px;font-weight:600;cursor:pointer;border:none;min-height:48px;
  transition:background .15s}
.btn-primary{background:#FFB800;color:#0F172A;flex:1}
.btn-primary:hover{background:#E5A700}
.btn-secondary{background:#334155;color:#e0e0e0;border:1px solid #475569}
.btn-secondary:hover{background:#3D4F63}
.btn:disabled{opacity:.5;cursor:not-allowed}
.get-key-link{display:inline-block;margin-top:6px;color:#FFB800;font-size:13px;text-decoration:none}
.get-key-link:hover{text-decoration:underline}
.status-box{padding:12px 16px;border-radius:10px;font-size:14px;margin-top:12px;display:none;align-items:center;gap:8px}
.status-box svg{flex-shrink:0}
.status-waiting{display:flex;background:#0F3460;color:#60A5FA}
.status-success{display:flex;background:#1e4d2b;color:#4ADE80}
.status-error{display:flex;background:#4a1c1c;color:#F87171}
.status-timeout{display:flex;background:#4a3c1c;color:#FBBF24}
.platform-cards{display:flex;flex-direction:column;gap:12px;margin-top:16px}
.platform-card{background:#0F172A;border:2px solid #334155;border-radius:12px;padding:20px;
  cursor:pointer;transition:border-color .15s,background .15s}
.platform-card:hover{border-color:#475569;background:#131D33}
.platform-card.selected{border-color:#FFB800;background:#1a2332}
.platform-card h3{font-size:16px;margin-bottom:4px}
.platform-card p{font-size:13px;color:#94A3B8}
.platform-detail{display:none;margin-top:16px}
.platform-detail.active{display:block}
.platform-note{color:#64748B;font-size:12px;margin-top:8px}
.qr-area{margin-top:16px;display:flex;flex-direction:column;align-items:center}
.qr-card{background:#fff;border-radius:12px;padding:20px;box-shadow:0 4px 24px rgba(0,0,0,.3);display:inline-block}
.qr-card svg{display:block;width:280px;height:280px}
.qr-instruction{color:#FFB800;font-size:15px;font-weight:600;margin-bottom:12px;text-align:center}
.qr-status{margin-top:12px;font-size:14px;display:flex;align-items:center;justify-content:center;gap:6px}
.summary{margin-top:16px}
.summary-row{display:flex;justify-content:space-between;padding:10px 0;border-bottom:1px solid #334155;font-size:14px}
.summary-label{color:#94A3B8}
.spinner{display:inline-block;width:20px;height:20px;border:3px solid #334155;
  border-top-color:#FFB800;border-radius:50%;animation:spin .8s linear infinite;margin-right:8px;vertical-align:middle}
@keyframes spin{to{transform:rotate(360deg)}}
@media(prefers-reduced-motion:reduce){.spinner{animation:none}}
.complete-actions{margin-top:24px;text-align:center}
.restart-status{font-size:14px;color:#94A3B8;margin-top:12px}
.proxy-row{display:none}
.proxy-row.visible{display:block}
.custom-url-row{display:none}
.custom-url-row.visible{display:block}
</style>
</head>
<body>
<div class="card">
  <h1>Hermes Setup Wizard</h1>
  <p class="step-indicator" id="stepIndicator">Step 1 of 3</p>

  <!-- Step 1: AI Model -->
  <div class="step active" id="step1" role="region" aria-label="AI Model Configuration">
    <label for="provider">AI Provider</label>
    <select id="provider">
      <option value="minimax-cn">MiniMax (中国) — 推荐中国用户使用</option>
      <option value="openrouter">OpenRouter — Access to 100+ models</option>
      <option value="gemini">Google AI Studio — Gemini models via Google</option>
      <option value="custom">Custom — Any OpenAI-compatible endpoint</option>
    </select>

    <label for="apiKey">API Key</label>
    <input type="password" id="apiKey" placeholder="Enter your API key" autocomplete="off">
    <a id="get-key-link" class="get-key-link" href="#" target="_blank" rel="noopener">Get Key →</a>

    <div class="custom-url-row" id="customUrlRow">
      <label for="baseUrl">Base URL</label>
      <input type="url" id="baseUrl" placeholder="https://api.example.com/v1">
    </div>

    <label for="model">Model</label>
    <select id="model">
      <option value="">Select a model</option>
    </select>
    <div class="custom-url-row visible" id="customModelRow" style="display:none">
      <label for="customModel">Custom Model Name</label>
      <input type="text" id="customModel" placeholder="e.g. gpt-4o">
    </div>

    <div class="proxy-row" id="proxyRow">
      <label for="proxy">HTTP Proxy</label>
      <input type="text" id="proxy" placeholder="http://127.0.0.1:7890">
    </div>

    <div class="status-box" id="testResult" role="status" aria-live="polite"></div>

    <div class="btn-row">
      <button class="btn btn-secondary" onclick="goStep(0)" disabled aria-label="Go back">← Back</button>
      <button class="btn btn-primary" id="testBtn" onclick="testConnection()" aria-label="Test Connection">
        Test Connection
      </button>
      <button class="btn btn-primary" id="next1" onclick="goStep(2)" disabled aria-label="Next step">Next →</button>
    </div>
  </div>

  <!-- Step 2: Messaging Platforms -->
  <div class="step" id="step2" role="region" aria-label="Messaging Platform Setup">
    <div class="platform-cards">
      <div class="platform-card" id="wechatCard" onclick="selectPlatform('wechat')" tabindex="0" role="button" aria-label="Connect WeChat">
        <h3>WeChat</h3>
        <p>Scan QR code to connect your WeChat account</p>
      </div>
      <div class="platform-card" id="telegramCard" onclick="selectPlatform('telegram')" tabindex="0" role="button" aria-label="Connect Telegram">
        <h3>Telegram</h3>
        <p>Connect via BotFather token</p>
      </div>
      <div class="platform-card" id="skipCard" onclick="selectPlatform('skip')" tabindex="0" role="button" aria-label="Skip messaging setup">
        <h3>Skip</h3>
        <p>Configure messaging later</p>
      </div>
    </div>

    <!-- WeChat detail -->
    <div class="platform-detail" id="wechatDetail" role="region" aria-label="WeChat QR Code">
      <div class="qr-area" id="qrArea">
        <div class="qr-instruction" id="qrInstruction">微信扫码连接</div>
        <div class="qr-card" id="qrCard" style="display:none"></div>
        <div class="qr-status" id="qrStatus" role="status" aria-live="polite">Click to start</div>
      </div>
      <p class="platform-note" style="text-align:center;margin-top:8px">WeChat 扫码需从另一台设备（手机）操作</p>
    </div>

    <!-- Telegram detail -->
    <div class="platform-detail" id="telegramDetail" role="region" aria-label="Telegram Configuration">
      <label for="telegramToken">Bot Token</label>
      <input type="text" id="telegramToken" placeholder="123456:ABC-DEF..." autocomplete="off">
      <a class="get-key-link" href="https://t.me/BotFather" target="_blank" rel="noopener">Get Token →</a>
      <button class="btn btn-primary" style="margin-top:12px;width:100%" onclick="saveTelegram()" aria-label="Save Telegram token">
        Save Telegram Token
      </button>
      <div class="status-box" id="telegramResult" role="status" aria-live="polite"></div>
    </div>

    <div class="btn-row">
      <button class="btn btn-secondary" onclick="goStep(1)" aria-label="Go back">← Back</button>
      <button class="btn btn-primary" onclick="goStep(3)" aria-label="Next step">Next →</button>
    </div>
  </div>

  <!-- Step 3: Complete -->
  <div class="step" id="step3" role="region" aria-label="Setup Complete">
    <h2 style="color:#FFB800;font-size:20px;margin-bottom:16px;text-align:center">Setup Complete</h2>
    <div class="summary" id="summary" role="region" aria-label="Configuration summary">
    </div>

    <div class="complete-actions">
      <button class="btn btn-primary" id="restartBtn" onclick="restartGateway()" style="width:100%" aria-label="Restart gateway">
        Restarting gateway...
      </button>
      <p class="restart-status" id="restartStatus" role="status" aria-live="polite">
        <span class="spinner"></span>Restarting gateway...
      </p>
      <a id="startChatBtn" class="btn btn-primary" href="http://localhost:3001" style="width:100%;display:none;text-decoration:none;margin-top:12px" aria-label="Start chatting">
        Start Chat →
      </a>
    </div>
    <p class="platform-note" style="margin-top:16px;text-align:center">Bookmark this page to change settings: localhost:8643/setup</p>
  </div>
</div>

<script>
// qrcode-generator v1.4.4 by Kazuhiko Arase (MIT License)
// https://github.com/kazuhikoarase/qrcode-generator
// Generates scannable QR codes with SVG output for crisp rendering.
var qrcode=function(){var t=function(t,r){var e=t,n=g[r],o=null,i=0,a=null,u=[],f={},c=function(t,r){o=function(t){for(var r=new Array(t),e=0;e<t;e+=1){r[e]=new Array(t);for(var n=0;n<t;n+=1)r[e][n]=null}return r}(i=4*e+17),l(0,0),l(i-7,0),l(0,i-7),s(),h(),d(t,r),e>=7&&v(t),null==a&&(a=p(e,n,u)),w(a,r)},l=function(t,r){for(var e=-1;e<=7;e+=1)if(!(t+e<=-1||i<=t+e))for(var n=-1;n<=7;n+=1)r+n<=-1||i<=r+n||(o[t+e][r+n]=0<=e&&e<=6&&(0==n||6==n)||0<=n&&n<=6&&(0==e||6==e)||2<=e&&e<=4&&2<=n&&n<=4)},h=function(){for(var t=8;t<i-8;t+=1)null==o[t][6]&&(o[t][6]=t%2==0);for(var r=8;r<i-8;r+=1)null==o[6][r]&&(o[6][r]=r%2==0)},s=function(){for(var t=B.getPatternPosition(e),r=0;r<t.length;r+=1)for(var n=0;n<t.length;n+=1){var i=t[r],a=t[n];if(null==o[i][a])for(var u=-2;u<=2;u+=1)for(var f=-2;f<=2;f+=1)o[i+u][a+f]=-2==u||2==u||-2==f||2==f||0==u&&0==f}},v=function(t){for(var r=B.getBCHTypeNumber(e),n=0;n<18;n+=1){var a=!t&&1==(r>>n&1);o[Math.floor(n/3)][n%3+i-8-3]=a}for(n=0;n<18;n+=1){a=!t&&1==(r>>n&1);o[n%3+i-8-3][Math.floor(n/3)]=a}},d=function(t,r){for(var e=n<<3|r,a=B.getBCHTypeInfo(e),u=0;u<15;u+=1){var f=!t&&1==(a>>u&1);u<6?o[u][8]=f:u<8?o[u+1][8]=f:o[i-15+u][8]=f}for(u=0;u<15;u+=1){f=!t&&1==(a>>u&1);u<8?o[8][i-u-1]=f:u<9?o[8][15-u-1+1]=f:o[8][15-u-1]=f}o[i-8][8]=!t},w=function(t,r){for(var e=-1,n=i-1,a=7,u=0,f=B.getMaskFunction(r),c=i-1;c>0;c-=2)for(6==c&&(c-=1);;){for(var g=0;g<2;g+=1)if(null==o[n][c-g]){var l=!1;u<t.length&&(l=1==(t[u]>>>a&1)),f(n,c-g)&&(l=!l),o[n][c-g]=l,-1==(a-=1)&&(u+=1,a=7)}if((n+=e)<0||i<=n){n-=e,e=-e;break}}},p=function(t,r,e){for(var n=A.getRSBlocks(t,r),o=b(),i=0;i<e.length;i+=1){var a=e[i];o.put(a.getMode(),4),o.put(a.getLength(),B.getLengthInBits(a.getMode(),t)),a.write(o)}var u=0;for(i=0;i<n.length;i+=1)u+=n[i].dataCount;if(o.getLengthInBits()>8*u)throw"code length overflow. ("+o.getLengthInBits()+">"+8*u+")";for(o.getLengthInBits()+4<=8*u&&o.put(0,4);o.getLengthInBits()%8!=0;)o.putBit(!1);for(;!(o.getLengthInBits()>=8*u||(o.put(236,8),o.getLengthInBits()>=8*u));)o.put(17,8);return function(t,r){for(var e=0,n=0,o=0,i=new Array(r.length),a=new Array(r.length),u=0;u<r.length;u+=1){var f=r[u].dataCount,c=r[u].totalCount-f;n=Math.max(n,f),o=Math.max(o,c),i[u]=new Array(f);for(var g=0;g<i[u].length;g+=1)i[u][g]=255&t.getBuffer()[g+e];e+=f;var l=B.getErrorCorrectPolynomial(c),h=k(i[u],l.getLength()-1).mod(l);for(a[u]=new Array(l.getLength()-1),g=0;g<a[u].length;g+=1){var s=g+h.getLength()-a[u].length;a[u][g]=s>=0?h.getAt(s):0}}var v=0;for(g=0;g<r.length;g+=1)v+=r[g].totalCount;var d=new Array(v),w=0;for(g=0;g<n;g+=1)for(u=0;u<r.length;u+=1)g<i[u].length&&(d[w]=i[u][g],w+=1);for(g=0;g<o;g+=1)for(u=0;u<r.length;u+=1)g<a[u].length&&(d[w]=a[u][g],w+=1);return d}(o,n)};f.addData=function(t,r){var e=null;switch(r=r||"Byte"){case"Numeric":e=M(t);break;case"Alphanumeric":e=x(t);break;case"Byte":e=m(t);break;case"Kanji":e=L(t);break;default:throw"mode:"+r}u.push(e),a=null},f.isDark=function(t,r){if(t<0||i<=t||r<0||i<=r)throw t+","+r;return o[t][r]},f.getModuleCount=function(){return i},f.make=function(){if(e<1){for(var t=1;t<40;t++){for(var r=A.getRSBlocks(t,n),o=b(),i=0;i<u.length;i+=1){var a=u[i];o.put(a.getMode(),4),o.put(a.getLength(),B.getLengthInBits(a.getMode(),t)),a.write(o)}var g=0;for(i=0;i<r.length;i++)g+=r[i].dataCount;if(o.getLengthInBits()<=8*g)break}e=t}c(!1,function(){for(var t=0,r=0,e=0;e<8;e+=1){c(!0,e);var n=B.getLostPoint(f);(0==e||t>n)&&(t=n,r=e)}return r}())},f.createSvgTag=function(t,r,e,n){var o={};"object"==typeof arguments[0]&&(t=(o=arguments[0]).cellSize,r=o.margin,e=o.alt,n=o.title),t=t||2,r=void 0===r?4*t:r,(e="string"==typeof e?{text:e}:e||{}).text=e.text||null,e.id=e.text?e.id||"qrcode-description":null,(n="string"==typeof n?{text:n}:n||{}).text=n.text||null,n.id=n.text?n.id||"qrcode-title":null;var i,a,u,c,g=f.getModuleCount()*t+2*r,l="";for(c="l"+t+",0 0,"+t+" -"+t+",0 0,-"+t+"z ",l+='<svg version="1.1" xmlns="http://www.w3.org/2000/svg"',l+=o.scalable?"":' width="'+g+'px" height="'+g+'px"',l+=' viewBox="0 0 '+g+" "+g+'" ',l+=' preserveAspectRatio="xMinYMin meet"',l+=n.text||e.text?' role="img" aria-labelledby="'+y([n.id,e.id].join(" ").trim())+'"':"",l+=">",l+=n.text?'<title id="'+y(n.id)+'">'+y(n.text)+"</title>":"",l+=e.text?'<description id="'+y(e.id)+'">'+y(e.text)+"</description>":"",l+='<rect width="100%" height="100%" fill="white" cx="0" cy="0"/>',l+='<path d="',a=0;a<f.getModuleCount();a+=1)for(u=a*t+r,i=0;i<f.getModuleCount();i+=1)f.isDark(a,i)&&(l+="M"+(i*t+r)+","+u+c);return l+='" stroke="transparent" fill="black"/>',l+="</svg>"};var y=function(t){for(var r="",e=0;e<t.length;e+=1){var n=t.charAt(e);switch(n){case"<":r+="&lt;";break;case">":r+="&gt;";break;case"&":r+="&amp;";break;case'"':r+="&quot;";break;default:r+=n}}return r};return f};t.stringToBytes=(t.stringToBytesFuncs={default:function(t){for(var r=[],e=0;e<t.length;e+=1){var n=t.charCodeAt(e);r.push(255&n)}return r}}).default,t.createStringToBytes=function(t,r){var e=function(){for(var e=S(t),n=function(){var t=e.read();if(-1==t)throw"eof";return t},o=0,i={};;){var a=e.read();if(-1==a)break;var u=n(),f=n()<<8|n();i[String.fromCharCode(a<<8|u)]=f,o+=1}if(o!=r)throw o+" != "+r;return i}(),n="?".charCodeAt(0);return function(t){for(var r=[],o=0;o<t.length;o+=1){var i=t.charCodeAt(o);if(i<128)r.push(i);else{var a=e[t.charAt(o)];"number"==typeof a?(255&a)==a?r.push(a):(r.push(a>>>8),r.push(255&a)):r.push(n)}}return r}};var r,e,n,o,i,a=1,u=2,f=4,c=8,g={L:1,M:0,Q:3,H:2},l=0,h=1,s=2,v=3,d=4,w=5,p=6,y=7,B=(r=[[],[6,18],[6,22],[6,26],[6,30],[6,34],[6,22,38],[6,24,42],[6,26,46],[6,28,50],[6,30,54],[6,32,58],[6,34,62],[6,26,46,66],[6,26,48,70],[6,26,50,74],[6,30,54,78],[6,30,56,82],[6,30,58,86],[6,34,62,90],[6,28,50,72,94],[6,26,50,74,98],[6,30,54,78,102],[6,28,54,80,106],[6,32,58,84,110],[6,30,58,86,114],[6,34,62,90,118],[6,26,50,74,98,122],[6,30,54,78,102,126],[6,26,52,78,104,130],[6,30,56,82,108,134],[6,34,60,86,112,138],[6,30,58,86,114,142],[6,34,62,90,118,146],[6,30,54,78,102,126,150],[6,24,50,76,102,128,154],[6,28,54,80,106,132,158],[6,32,58,84,110,136,162],[6,26,54,82,110,138,166],[6,30,58,86,114,142,170]],e=1335,n=7973,i=function(t){for(var r=0;0!=t;)r+=1,t>>>=1;return r},(o={}).getBCHTypeInfo=function(t){for(var r=t<<10;i(r)-i(e)>=0;)r^=e<<i(r)-i(e);return 21522^(t<<10|r)},o.getBCHTypeNumber=function(t){for(var r=t<<12;i(r)-i(n)>=0;)r^=n<<i(r)-i(n);return t<<12|r},o.getPatternPosition=function(t){return r[t-1]},o.getMaskFunction=function(t){switch(t){case l:return function(t,r){return(t+r)%2==0};case h:return function(t,r){return t%2==0};case s:return function(t,r){return r%3==0};case v:return function(t,r){return(t+r)%3==0};case d:return function(t,r){return(Math.floor(t/2)+Math.floor(r/3))%2==0};case w:return function(t,r){return t*r%2+t*r%3==0};case p:return function(t,r){return(t*r%2+t*r%3)%2==0};case y:return function(t,r){return(t*r%3+(t+r)%2)%2==0};default:throw"bad maskPattern:"+t}},o.getErrorCorrectPolynomial=function(t){for(var r=k([1],0),e=0;e<t;e+=1)r=r.multiply(k([1,C.gexp(e)],0));return r},o.getLengthInBits=function(t,r){if(1<=r&&r<10)switch(t){case a:return 10;case u:return 9;case f:case c:return 8;default:throw"mode:"+t}else if(r<27)switch(t){case a:return 12;case u:return 11;case f:return 16;case c:return 10;default:throw"mode:"+t}else{if(!(r<41))throw"type:"+r;switch(t){case a:return 14;case u:return 13;case f:return 16;case c:return 12;default:throw"mode:"+t}}},o.getLostPoint=function(t){for(var r=t.getModuleCount(),e=0,n=0;n<r;n+=1)for(var o=0;o<r;o+=1){for(var i=0,a=t.isDark(n,o),u=-1;u<=1;u+=1)if(!(n+u<0||r<=n+u))for(var f=-1;f<=1;f+=1)o+f<0||r<=o+f||0==u&&0==f||a==t.isDark(n+u,o+f)&&(i+=1);i>5&&(e+=3+i-5)}for(n=0;n<r-1;n+=1)for(o=0;o<r-1;o+=1){var c=0;t.isDark(n,o)&&(c+=1),t.isDark(n+1,o)&&(c+=1),t.isDark(n,o+1)&&(c+=1),t.isDark(n+1,o+1)&&(c+=1),0!=c&&4!=c||(e+=3)}for(n=0;n<r;n+=1)for(o=0;o<r-6;o+=1)t.isDark(n,o)&&!t.isDark(n,o+1)&&t.isDark(n,o+2)&&t.isDark(n,o+3)&&t.isDark(n,o+4)&&!t.isDark(n,o+5)&&t.isDark(n,o+6)&&(e+=40);for(o=0;o<r;o+=1)for(n=0;n<r-6;n+=1)t.isDark(n,o)&&!t.isDark(n+1,o)&&t.isDark(n+2,o)&&t.isDark(n+3,o)&&t.isDark(n+4,o)&&!t.isDark(n+5,o)&&t.isDark(n+6,o)&&(e+=40);var g=0;for(o=0;o<r;o+=1)for(n=0;n<r;n+=1)t.isDark(n,o)&&(g+=1);return e+=Math.abs(100*g/r/r-50)/5*10},o),C=function(){for(var t=new Array(256),r=new Array(256),e=0;e<8;e+=1)t[e]=1<<e;for(e=8;e<256;e+=1)t[e]=t[e-4]^t[e-5]^t[e-6]^t[e-8];for(e=0;e<255;e+=1)r[t[e]]=e;var n={glog:function(t){if(t<1)throw"glog("+t+")";return r[t]},gexp:function(r){for(;r<0;)r+=255;for(;r>=256;)r-=255;return t[r]}};return n}();function k(t,r){if(void 0===t.length)throw t.length+"/"+r;var e=function(){for(var e=0;e<t.length&&0==t[e];)e+=1;for(var n=new Array(t.length-e+r),o=0;o<t.length-e;o+=1)n[o]=t[o+e];return n}(),n={getAt:function(t){return e[t]},getLength:function(){return e.length},multiply:function(t){for(var r=new Array(n.getLength()+t.getLength()-1),e=0;e<n.getLength();e+=1)for(var o=0;o<t.getLength();o+=1)r[e+o]^=C.gexp(C.glog(n.getAt(e))+C.glog(t.getAt(o)));return k(r,0)},mod:function(t){if(n.getLength()-t.getLength()<0)return n;for(var r=C.glog(n.getAt(0))-C.glog(t.getAt(0)),e=new Array(n.getLength()),o=0;o<n.getLength();o+=1)e[o]=n.getAt(o);for(o=0;o<t.getLength();o+=1)e[o]^=C.gexp(C.glog(t.getAt(o))+r);return k(e,0).mod(t)}};return n}var A=function(){var t=[[1,26,19],[1,26,16],[1,26,13],[1,26,9],[1,44,34],[1,44,28],[1,44,22],[1,44,16],[1,70,55],[1,70,44],[2,35,17],[2,35,13],[1,100,80],[2,50,32],[2,50,24],[4,25,9],[1,134,108],[2,67,43],[2,33,15,2,34,16],[2,33,11,2,34,12],[2,86,68],[4,43,27],[4,43,19],[4,43,15],[2,98,78],[4,49,31],[2,32,14,4,33,15],[4,39,13,1,40,14],[2,121,97],[2,60,38,2,61,39],[4,40,18,2,41,19],[4,40,14,2,41,15],[2,146,116],[3,58,36,2,59,37],[4,36,16,4,37,17],[4,36,12,4,37,13],[2,86,68,2,87,69],[4,69,43,1,70,44],[6,43,19,2,44,20],[6,43,15,2,44,16],[4,101,81],[1,80,50,4,81,51],[4,50,22,4,51,23],[3,36,12,8,37,13],[2,116,92,2,117,93],[6,58,36,2,59,37],[4,46,20,6,47,21],[7,42,14,4,43,15],[4,133,107],[8,59,37,1,60,38],[8,44,20,4,45,21],[12,33,11,4,34,12],[3,145,115,1,146,116],[4,64,40,5,65,41],[11,36,16,5,37,17],[11,36,12,5,37,13],[5,109,87,1,110,88],[5,65,41,5,66,42],[5,54,24,7,55,25],[11,36,12,7,37,13],[5,122,98,1,123,99],[7,73,45,3,74,46],[15,43,19,2,44,20],[3,45,15,13,46,16],[1,135,107,5,136,108],[10,74,46,1,75,47],[1,50,22,15,51,23],[2,42,14,17,43,15],[5,150,120,1,151,121],[9,69,43,4,70,44],[17,50,22,1,51,23],[2,42,14,19,43,15],[3,141,113,4,142,114],[3,70,44,11,71,45],[17,47,21,4,48,22],[9,39,13,16,40,14],[3,135,107,5,136,108],[3,67,41,13,68,42],[15,54,24,5,55,25],[15,43,15,10,44,16],[4,144,116,4,145,117],[17,68,42],[17,50,22,6,51,23],[19,46,16,6,47,17],[2,139,111,7,140,112],[17,74,46],[7,54,24,16,55,25],[34,37,13],[4,151,121,5,152,122],[4,75,47,14,76,48],[11,54,24,14,55,25],[16,45,15,14,46,16],[6,147,117,4,148,118],[6,73,45,14,74,46],[11,54,24,16,55,25],[30,46,16,2,47,17],[8,132,106,4,133,107],[8,75,47,13,76,48],[7,54,24,22,55,25],[22,45,15,13,46,16],[10,142,114,2,143,115],[19,74,46,4,75,47],[28,50,22,6,51,23],[33,46,16,4,47,17],[8,152,122,4,153,123],[22,73,45,3,74,46],[8,53,23,26,54,24],[12,45,15,28,46,16],[3,147,117,10,148,118],[3,73,45,23,74,46],[4,54,24,31,55,25],[11,45,15,31,46,16],[7,146,116,7,147,117],[21,73,45,7,74,46],[1,53,23,37,54,24],[19,45,15,26,46,16],[5,145,115,10,146,116],[19,75,47,10,76,48],[15,54,24,25,55,25],[23,45,15,25,46,16],[13,145,115,3,146,116],[2,74,46,29,75,47],[42,54,24,1,55,25],[23,45,15,28,46,16],[17,145,115],[10,74,46,23,75,47],[10,54,24,35,55,25],[19,45,15,35,46,16],[17,145,115,1,146,116],[14,74,46,21,75,47],[29,54,24,19,55,25],[11,45,15,46,46,16],[13,145,115,6,146,116],[14,74,46,23,75,47],[44,54,24,7,55,25],[59,46,16,1,47,17],[12,151,121,7,152,122],[12,75,47,26,76,48],[39,54,24,14,55,25],[22,45,15,41,46,16],[6,151,121,14,152,122],[6,75,47,34,76,48],[46,54,24,10,55,25],[2,45,15,64,46,16],[17,152,122,4,153,123],[29,74,46,14,75,47],[49,54,24,10,55,25],[24,45,15,46,46,16],[4,152,122,18,153,123],[13,74,46,32,75,47],[48,54,24,14,55,25],[42,45,15,32,46,16],[20,147,117,4,148,118],[40,75,47,7,76,48],[43,54,24,22,55,25],[10,45,15,67,46,16],[19,148,118,6,149,119],[18,75,47,31,76,48],[34,54,24,34,55,25],[20,45,15,61,46,16]],r=function(t,r){var e={};return e.totalCount=t,e.dataCount=r,e},e={};return e.getRSBlocks=function(e,n){var o=function(r,e){switch(e){case g.L:return t[4*(r-1)+0];case g.M:return t[4*(r-1)+1];case g.Q:return t[4*(r-1)+2];case g.H:return t[4*(r-1)+3];default:return}}(e,n);if(void 0===o)throw"bad rs block @ typeNumber:"+e+"/errorCorrectionLevel:"+n;for(var i=o.length/3,a=[],u=0;u<i;u+=1)for(var f=o[3*u+0],c=o[3*u+1],l=o[3*u+2],h=0;h<f;h+=1)a.push(r(c,l));return a},e}(),b=function(){var t=[],r=0,e={getBuffer:function(){return t},getAt:function(r){var e=Math.floor(r/8);return 1==(t[e]>>>7-r%8&1)},put:function(t,r){for(var n=0;n<r;n+=1)e.putBit(1==(t>>>r-n-1&1))},getLengthInBits:function(){return r},putBit:function(e){var n=Math.floor(r/8);t.length<=n&&t.push(0),e&&(t[n]|=128>>>r%8),r+=1}};return e},M=function(t){var r=a,e=t,n={getMode:function(){return r},getLength:function(t){return e.length},write:function(t){for(var r=e,n=0;n+2<r.length;)t.put(o(r.substring(n,n+3)),10),n+=3;n<r.length&&(r.length-n==1?t.put(o(r.substring(n,n+1)),4):r.length-n==2&&t.put(o(r.substring(n,n+2)),7))}},o=function(t){for(var r=0,e=0;e<t.length;e+=1)r=10*r+i(t.charAt(e));return r},i=function(t){if("0"<=t&&t<="9")return t.charCodeAt(0)-"0".charCodeAt(0);throw"illegal char :"+t};return n},x=function(t){var r=u,e=t,n={getMode:function(){return r},getLength:function(t){return e.length},write:function(t){for(var r=e,n=0;n+1<r.length;)t.put(45*o(r.charAt(n))+o(r.charAt(n+1)),11),n+=2;n<r.length&&t.put(o(r.charAt(n)),6)}},o=function(t){if("0"<=t&&t<="9")return t.charCodeAt(0)-"0".charCodeAt(0);if("A"<=t&&t<="Z")return t.charCodeAt(0)-"A".charCodeAt(0)+10;switch(t){case" ":return 36;case"$":return 37;case"%":return 38;case"*":return 39;case"+":return 40;case"-":return 41;case".":return 42;case"/":return 43;case":":return 44;default:throw"illegal char :"+t}};return n},m=function(r){var e=f,n=t.stringToBytes(r),o={getMode:function(){return e},getLength:function(t){return n.length},write:function(t){for(var r=0;r<n.length;r+=1)t.put(n[r],8)}};return o},L=function(r){var e=c,n=t.stringToBytesFuncs.SJIS;if(!n)throw"sjis not supported.";!function(){var t=n("\u53cb");if(2!=t.length||38726!=(t[0]<<8|t[1]))throw"sjis not supported."}();var o=n(r),i={getMode:function(){return e},getLength:function(t){return~~(o.length/2)},write:function(t){for(var r=o,e=0;e+1<r.length;){var n=(255&r[e])<<8|255&r[e+1];if(33088<=n&&n<=40956)n-=33088;else{if(!(57408<=n&&n<=60351))throw"illegal char at "+(e+1)+"/"+n;n-=49472}n=192*(n>>>8&255)+(255&n),t.put(n,13),e+=2}if(e<r.length)throw"illegal char at "+(e+1)}};return i},D=function(){var t=[],r={writeByte:function(r){t.push(255&r)},writeShort:function(t){r.writeByte(t),r.writeByte(t>>>8)},writeBytes:function(t,e,n){e=e||0,n=n||t.length;for(var o=0;o<n;o+=1)r.writeByte(t[o+e])},writeString:function(t){for(var e=0;e<t.length;e+=1)r.writeByte(t.charCodeAt(e))},toByteArray:function(){return t},toString:function(){var r="";r+="[";for(var e=0;e<t.length;e+=1)e>0&&(r+=","),r+=t[e];return r+="]"}};return r},S=function(t){var r=t,e=0,n=0,o=0,i={read:function(){for(;o<8;){if(e>=r.length){if(0==o)return-1;throw"unexpected end of file./"+o}var t=r.charAt(e);if(e+=1,"="==t)return o=0,-1;t.match(/^\s$/)||(n=n<<6|a(t.charCodeAt(0)),o+=6)}var i=n>>>o-8&255;return o-=8,i}},a=function(t){if(65<=t&&t<=90)return t-65;if(97<=t&&t<=122)return t-97+26;if(48<=t&&t<=57)return t-48+52;if(43==t)return 62;if(47==t)return 63;throw"c:"+t};return i},I=function(t,r,e){for(var n=function(t,r){var e=t,n=r,o=new Array(t*r),i={setPixel:function(t,r,n){o[r*e+t]=n},write:function(t){t.writeString("GIF87a"),t.writeShort(e),t.writeShort(n),t.writeByte(128),t.writeByte(0),t.writeByte(0),t.writeByte(0),t.writeByte(0),t.writeByte(0),t.writeByte(255),t.writeByte(255),t.writeByte(255),t.writeString(","),t.writeShort(0),t.writeShort(0),t.writeShort(e),t.writeShort(n),t.writeByte(0);var r=a(2);t.writeByte(2);for(var o=0;r.length-o>255;)t.writeByte(255),t.writeBytes(r,o,255),o+=255;t.writeByte(r.length-o),t.writeBytes(r,o,r.length-o),t.writeByte(0),t.writeString(";")}},a=function(t){for(var r=1<<t,e=1+(1<<t),n=t+1,i=u(),a=0;a<r;a+=1)i.add(String.fromCharCode(a));i.add(String.fromCharCode(r)),i.add(String.fromCharCode(e));var f,c,g,l=D(),h=(f=l,c=0,g=0,{write:function(t,r){if(t>>>r!=0)throw"length over";for(;c+r>=8;)f.writeByte(255&(t<<c|g)),r-=8-c,t>>>=8-c,g=0,c=0;g|=t<<c,c+=r},flush:function(){c>0&&f.writeByte(g)}});h.write(r,n);var s=0,v=String.fromCharCode(o[s]);for(s+=1;s<o.length;){var d=String.fromCharCode(o[s]);s+=1,i.contains(v+d)?v+=d:(h.write(i.indexOf(v),n),i.size()<4095&&(i.size()==1<<n&&(n+=1),i.add(v+d)),v=d)}return h.write(i.indexOf(v),n),h.write(e,n),h.flush(),l.toByteArray()},u=function(){var t={},r=0,e={add:function(n){if(e.contains(n))throw"dup key:"+n;t[n]=r,r+=1},size:function(){return r},indexOf:function(r){return t[r]},contains:function(r){return void 0!==t[r]}};return e};return i}(t,r),o=0;o<r;o+=1)for(var i=0;i<t;i+=1)n.setPixel(i,o,e(i,o));var a=D();n.write(a);for(var u=function(){var t=0,r=0,e=0,n="",o={},i=function(t){n+=String.fromCharCode(a(63&t))},a=function(t){if(t<0);else{if(t<26)return 65+t;if(t<52)return t-26+97;if(t<62)return t-52+48;if(62==t)return 43;if(63==t)return 47}throw"n:"+t};return o.writeByte=function(n){for(t=t<<8|255&n,r+=8,e+=1;r>=6;)i(t>>>r-6),r-=6},o.flush=function(){if(r>0&&(i(t<<6-r),t=0,r=0),e%3!=0)for(var o=3-e%3,a=0;a<o;a+=1)n+="="},o.toString=function(){return n},o}(),f=a.toByteArray(),c=0;c<f.length;c+=1)u.writeByte(f[c]);return u.flush(),"data:image/gif;base64,"+u};return t}();qrcode.stringToBytesFuncs["UTF-8"]=function(t){return function(t){for(var r=[],e=0;e<t.length;e++){var n=t.charCodeAt(e);n<128?r.push(n):n<2048?r.push(192|n>>6,128|63&n):n<55296||n>=57344?r.push(224|n>>12,128|n>>6&63,128|63&n):(e++,n=65536+((1023&n)<<10|1023&t.charCodeAt(e)),r.push(240|n>>18,128|n>>12&63,128|n>>6&63,128|63&n))}return r}(t)},function(t){"function"==typeof define&&define.amd?define([],t):"object"==typeof exports&&(module.exports=t())}((function(){return qrcode}));
// Helper: generate QR as inline SVG string for the given text
function generateQRSvg(text) {
  var qr = qrcode(0, 'M');
  qr.addData(text);
  qr.make();
  return qr.createSvgTag({cellSize: 8, margin: 4, scalable: true});
}
</script>

<script>
const API_KEY = "__API_KEY__";
let currentStep = 1;
let setupStatus = {};
let selectedPlatform = "";
let wechatPollTimer = null;

function authHeaders() {
  return { "Content-Type": "application/json", "Authorization": "Bearer " + API_KEY };
}

async function fetchStatus() {
  const resp = await fetch("/setup/status", { headers: authHeaders() });
  setupStatus = await resp.json();
  return setupStatus;
}

function showStep(n) {
  document.querySelectorAll(".step").forEach((el, i) => {
    el.classList.toggle("active", i + 1 === n);
  });
  document.getElementById("stepIndicator").textContent = "Step " + n + " of 3";
  currentStep = n;
}

async function saveModelConfig() {
  const provider = document.getElementById("provider").value;
  const apiKey = document.getElementById("apiKey").value;
  const model = document.getElementById("model").value || document.getElementById("customModel").value;
  const baseUrl = document.getElementById("baseUrl").value;
  const proxy = document.getElementById("proxy").value;
  const body = { provider, model };
  if (apiKey) body.api_key = apiKey;
  if (baseUrl) body.base_url = baseUrl;
  if (proxy) body.proxy = proxy;
  try {
    await fetch("/setup/model", { method: "POST", headers: authHeaders(), body: JSON.stringify(body) });
  } catch (e) { /* non-fatal */ }
}

function goStep(n) {
  if (n === 2) { saveModelConfig(); }
  if (n === 3) buildSummary();
  showStep(n);
  if (n === 3) restartGateway();
}

// --- Step 1: Provider logic ---
function updateProviderUI() {
  const provider = document.getElementById("provider").value;
  const p = setupStatus.providers ? setupStatus.providers[provider] : null;
  const keyLink = document.getElementById("get-key-link");
  const proxyRow = document.getElementById("proxyRow");
  const customUrlRow = document.getElementById("customUrlRow");
  const modelSelect = document.getElementById("model");
  const customModelRow = document.getElementById("customModelRow");

  if (p && p.get_key_url) {
    keyLink.href = p.get_key_url;
    keyLink.style.display = "inline-block";
  } else {
    keyLink.style.display = "none";
  }

  if (p && p.show_proxy) {
    proxyRow.classList.add("visible");
  } else {
    proxyRow.classList.remove("visible");
  }

  if (provider === "custom") {
    customUrlRow.classList.add("visible");
    modelSelect.style.display = "none";
    customModelRow.style.display = "block";
  } else {
    customUrlRow.classList.remove("visible");
    modelSelect.style.display = "block";
    customModelRow.style.display = "none";
    modelSelect.innerHTML = "";
    if (p && p.models) {
      p.models.forEach((m, i) => {
        const opt = document.createElement("option");
        opt.value = m;
        opt.textContent = m;
        modelSelect.appendChild(opt);
      });
      if (p.models.length === 0) {
        const opt = document.createElement("option");
        opt.value = "";
        opt.textContent = "No models listed";
        modelSelect.appendChild(opt);
      }
    }
  }
}

async function testConnection() {
  const provider = document.getElementById("provider").value;
  const apiKey = document.getElementById("apiKey").value;
  const model = document.getElementById("model").value || document.getElementById("customModel").value;
  const baseUrl = document.getElementById("baseUrl").value;
  const proxy = document.getElementById("proxy").value;
  const resultBox = document.getElementById("testResult");
  const testBtn = document.getElementById("testBtn");

  resultBox.className = "status-box status-waiting";
  resultBox.innerHTML = '<span class="spinner"></span>Testing connection...';
  testBtn.disabled = true;

  try {
    const body = { provider, api_key: apiKey, model };
    if (baseUrl) body.base_url = baseUrl;
    if (proxy) body.proxy = proxy;

    const resp = await fetch("/setup/test-conn", {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify(body),
    });
    const data = await resp.json();

    if (data.ok) {
      resultBox.className = "status-box status-success";
      resultBox.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#4ADE80" stroke-width="2"><path d="M20 6L9 17l-5-5"/></svg>Connection successful';
      document.getElementById("next1").disabled = false;
    } else {
      resultBox.className = "status-box status-error";
      resultBox.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#F87171" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M15 9l-6 6M9 9l6 6"/></svg>' + (data.error || "Connection failed");
      document.getElementById("next1").disabled = true;
    }
  } catch (e) {
    resultBox.className = "status-box status-error";
    resultBox.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#F87171" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M15 9l-6 6M9 9l6 6"/></svg>Network error: ' + e.message;
    document.getElementById("next1").disabled = true;
  }
  testBtn.disabled = false;
}

// --- Step 2: Platform logic ---
function selectPlatform(platform) {
  selectedPlatform = platform;
  document.querySelectorAll(".platform-card").forEach(c => c.classList.remove("selected"));
  document.getElementById(platform === "wechat" ? "wechatCard" : platform === "telegram" ? "telegramCard" : "skipCard").classList.add("selected");
  document.querySelectorAll(".platform-detail").forEach(d => d.classList.remove("active"));
  if (platform === "wechat") {
    document.getElementById("wechatDetail").classList.add("active");
    startWechatQR();
  } else if (platform === "telegram") {
    document.getElementById("telegramDetail").classList.add("active");
  }
}

async function startWechatQR() {
  var qrCard = document.getElementById("qrCard");
  var qrStatus = document.getElementById("qrStatus");
  var qrInstruction = document.getElementById("qrInstruction");
  qrCard.style.display = "none";
  qrCard.innerHTML = "";
  qrInstruction.style.display = "none";
  qrStatus.innerHTML = '<span class="spinner"></span>Loading QR code...';

  try {
    const resp = await fetch("/setup/platforms/wechat/qr", { headers: authHeaders() });
    const data = await resp.json();
    if (data.qr_value) {
      var qrContent = data.qr_url || data.qr_value;
      lastQrUrl = qrContent;
      // Render QR as SVG via battle-tested qrcode-generator library
      var svgHtml = generateQRSvg(qrContent);
      qrCard.innerHTML = svgHtml;
      qrCard.style.display = "inline-block";
      qrInstruction.style.display = "block";
      qrStatus.innerHTML = '<span class="spinner"></span>Waiting for scan...';
      pollWechat();
    } else {
      qrStatus.textContent = data.error || data.detail || "Failed to get QR code";
    }
  } catch (e) {
    qrStatus.textContent = "Error: " + e.message;
  }
}

let lastQrUrl = "";
function pollWechat() {
  if (wechatPollTimer) clearInterval(wechatPollTimer);
  const qrStatus = document.getElementById("qrStatus");
  wechatPollTimer = setInterval(async () => {
    try {
      const resp = await fetch("/setup/platforms/wechat/poll", { headers: authHeaders() });
      const data = await resp.json();
      if (data.status === "scanned") {
        qrStatus.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#60A5FA" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>Scanned — confirming...';
      } else if (data.status === "success") {
        clearInterval(wechatPollTimer);
        qrStatus.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#4ADE80" stroke-width="2"><path d="M20 6L9 17l-5-5"/></svg>WeChat connected!';
      } else if (data.status === "expired") {
        clearInterval(wechatPollTimer);
        qrStatus.innerHTML = 'QR expired. <a href="#" onclick="startWechatQR();return false;" style="color:#FFB800">Refresh</a>';
      }
      // Re-render QR if backend auto-refreshed it
      if (data.qr_url && data.qr_url !== lastQrUrl) {
        lastQrUrl = data.qr_url;
        var qrCard = document.getElementById("qrCard");
        if (qrCard) {
          var svgHtml = generateQRSvg(data.qr_url);
          qrCard.innerHTML = svgHtml;
        }
      }
    } catch (e) {
      // ignore poll errors
    }
  }, 2000);
}

async function saveTelegram() {
  const token = document.getElementById("telegramToken").value;
  const resultBox = document.getElementById("telegramResult");
  resultBox.className = "status-box status-waiting";
  resultBox.innerHTML = '<span class="spinner"></span>Saving...';

  try {
    const resp = await fetch("/setup/platforms/telegram", {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify({ token }),
    });
    const data = await resp.json();
    if (data.ok) {
      resultBox.className = "status-box status-success";
      resultBox.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#4ADE80" stroke-width="2"><path d="M20 6L9 17l-5-5"/></svg>Telegram connected!';
    } else {
      resultBox.className = "status-box status-error";
      resultBox.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#F87171" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M15 9l-6 6M9 9l6 6"/></svg>' + (data.error || "Failed");
    }
  } catch (e) {
    resultBox.className = "status-box status-error";
    resultBox.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#F87171" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M15 9l-6 6M9 9l6 6"/></svg>Error: ' + e.message;
  }
}

// --- Step 3: Summary & Restart ---
function buildSummary() {
  const provider = document.getElementById("provider");
  const providerText = provider.options[provider.selectedIndex].text;
  const model = document.getElementById("model").value || document.getElementById("customModel").value || setupStatus.model || "-";
  const wechatConnected = setupStatus.wechat_connected;
  const telegramConnected = setupStatus.telegram_connected;

  document.getElementById("summary").innerHTML =
    '<div class="summary-row"><span class="summary-label">Provider</span><span>' + providerText + '</span></div>' +
    '<div class="summary-row"><span class="summary-label">Model</span><span>' + model + '</span></div>' +
    '<div class="summary-row"><span class="summary-label">WeChat</span><span style="color:' + (wechatConnected ? '#4ADE80' : '#94A3B8') + '">' + (wechatConnected ? 'Connected' : 'Not connected') + '</span></div>' +
    '<div class="summary-row"><span class="summary-label">Telegram</span><span style="color:' + (telegramConnected ? '#4ADE80' : '#94A3B8') + '">' + (telegramConnected ? 'Connected' : 'Not connected') + '</span></div>';
}

async function restartGateway() {
  const restartBtn = document.getElementById("restartBtn");
  const restartStatus = document.getElementById("restartStatus");
  const startChatBtn = document.getElementById("startChatBtn");
  restartBtn.disabled = true;
  restartStatus.innerHTML = '<span class="spinner"></span>Restarting gateway...';
  startChatBtn.style.display = "none";

  try {
    await fetch("/setup/restart", { method: "POST", headers: authHeaders() });
  } catch (e) {
    // gateway may restart too fast to respond
  }

  let attempts = 0;
  const maxAttempts = 15;
  const poll = setInterval(async () => {
    attempts++;
    if (attempts >= maxAttempts) {
      clearInterval(poll);
      restartStatus.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#FBBF24" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 8v4M12 16h.01"/></svg>Timeout — try refreshing manually';
      startChatBtn.style.display = "inline-flex";
      return;
    }
    try {
      const resp = await fetch("/setup/status", { headers: authHeaders() });
      const data = await resp.json();
      if (data.has_api_key) {
        clearInterval(poll);
        restartStatus.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#4ADE80" stroke-width="2"><path d="M20 6L9 17l-5-5"/></svg>Gateway is ready!';
        startChatBtn.style.display = "inline-flex";
        restartBtn.style.display = "none";
      }
    } catch (e) {
      // gateway still restarting
    }
  }, 2000);
}

// --- Init ---
window.addEventListener("DOMContentLoaded", async () => {
  await fetchStatus();

  const provider = document.getElementById("provider");
  if (setupStatus.active_provider) {
    provider.value = setupStatus.active_provider;
  }
  updateProviderUI();

  if (setupStatus.masked_keys) {
    const activeKey = setupStatus.masked_keys[provider.value];
    if (activeKey) document.getElementById("apiKey").placeholder = activeKey;
  }

  if (setupStatus.model) {
    const modelSelect = document.getElementById("model");
    for (let i = 0; i < modelSelect.options.length; i++) {
      if (modelSelect.options[i].value === setupStatus.model) {
        modelSelect.selectedIndex = i;
        break;
      }
    }
  }

  if (setupStatus.proxy) {
    document.getElementById("proxy").value = setupStatus.proxy;
  }

  provider.addEventListener("change", updateProviderUI);
});
</script>
</body>
</html>"""


async def handle_wizard(request: web.Request) -> web.Response:
    """Full 3-step setup wizard SPA."""
    key = get_api_key()
    html = WIZARD_HTML.replace("__API_KEY__", key)
    return web.Response(text=html, content_type="text/html")


def _check_auth(request: web.Request) -> bool:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:] == get_api_key()
    return False


async def handle_save_model(request: web.Request) -> web.Response:
    if not _check_auth(request):
        return web.json_response({"error": "Unauthorized"}, status=401)
    data = await request.json()
    provider = data.get("provider", "")
    api_key = data.get("api_key", "")
    model = data.get("model", "")
    proxy = data.get("proxy", "")

    if provider not in PROVIDERS:
        return web.json_response({"error": f"Unknown provider: {provider}"}, status=400)

    p = PROVIDERS[provider]
    # Only update API key if the user provided a new one.
    # On re-visits the field is empty (placeholder shows masked key).
    env_updates = {}
    if api_key:
        env_updates[p["env_key"]] = api_key
    if provider == "custom" and data.get("base_url"):
        env_updates["OPENAI_BASE_URL"] = data["base_url"]
    if proxy:
        env_updates["HTTP_PROXY"] = proxy
        env_updates["HTTPS_PROXY"] = proxy

    try:
        if env_updates:
            write_env(env_updates)
        write_config_yaml(model, provider)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

    return web.json_response({"ok": True})


async def handle_test_conn(request: web.Request) -> web.Response:
    if not _check_auth(request):
        return web.json_response({"error": "Unauthorized"}, status=401)
    data = await request.json()
    provider = data.get("provider", "")
    api_key = data.get("api_key", "")
    model = data.get("model", "")
    proxy = data.get("proxy", "")

    if provider not in PROVIDERS:
        return web.json_response({"error": "Unknown provider"}, status=400)
    p = PROVIDERS[provider]
    base_url = data.get("base_url") or p["base_url"]
    if not base_url:
        return web.json_response({"ok": False, "detail": "Base URL required for custom provider"})

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{base_url}/chat/completions",
                json={"model": model, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 5},
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                proxy=proxy or None,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status == 200:
                    return web.json_response({"ok": True})
                body = await resp.text()
                return web.json_response({"ok": False, "status": resp.status, "detail": body[:200]})
    except Exception as e:
        return web.json_response({"ok": False, "detail": str(e)})


async def handle_complete(request: web.Request) -> web.Response:
    if not _check_auth(request):
        return web.json_response({"error": "Unauthorized"}, status=401)
    mark_setup_complete()
    return web.json_response({"ok": True})


async def handle_reset(request: web.Request) -> web.Response:
    if not _check_auth(request):
        return web.json_response({"error": "Unauthorized"}, status=401)
    reset_setup()
    return web.json_response({"ok": True})


# --- WeChat QR state (per-process, single user) ---
_wechat_state = {"status": "idle", "qr_url": "", "qr_value": "", "credentials": None}

ILINK_BASE_URL = "https://ilinkai.weixin.qq.com"
ILINK_HEADERS = {
    "AuthorizationType": "ilink_bot_token",
    "iLink-App-Id": "bot",
    "iLink-App-ClientVersion": str((2 << 16) | (2 << 8) | 0),
}


async def handle_wechat_qr(request: web.Request) -> web.Response:
    """Fetch a fresh QR code from iLink. Starts a background polling task."""
    if not _check_auth(request):
        return web.json_response({"error": "Unauthorized"}, status=401)
    _wechat_state["status"] = "fetching"
    _wechat_state["qr_url"] = ""
    _wechat_state["credentials"] = None

    try:
        async with aiohttp.ClientSession(base_url=ILINK_BASE_URL, headers=ILINK_HEADERS) as session:
            async with session.get("ilink/bot/get_bot_qrcode?bot_type=3") as resp:
                data = json.loads(await resp.text())

        qr_value = str(data.get("qrcode", ""))
        qr_img_url = str(data.get("qrcode_img_content", ""))

        if not qr_value and not qr_img_url:
            _wechat_state["status"] = "error"
            return web.json_response({"status": "error", "detail": "No QR code returned"})

        _wechat_state["qr_value"] = qr_value
        _wechat_state["qr_url"] = qr_img_url or qr_value
        _wechat_state["status"] = "waiting"

        asyncio.ensure_future(_poll_wechat_scan())

        return web.json_response({
            "status": "waiting",
            "qr_url": _wechat_state["qr_url"],
            "qr_value": qr_value,
        })
    except Exception as e:
        _wechat_state["status"] = "error"
        return web.json_response({"status": "error", "detail": "Failed to fetch QR code from WeChat"})


async def _poll_wechat_scan() -> None:
    """Background task: poll iLink for QR scan status.

    Status values aligned with gateway/platforms/weixin.py qr_login():
    - "wait" — still waiting for scan
    - "scaned" — user scanned, waiting for phone confirmation
    - "scaned_but_redirect" — redirect to a different iLink host
    - "expired" — QR code expired, auto-refresh (up to 3 times)
    - "confirmed" — login confirmed, credentials available
    """
    qr_value = _wechat_state.get("qr_value", "")
    if not qr_value:
        return

    current_base_url = ILINK_BASE_URL
    refresh_count = 0

    async with aiohttp.ClientSession(headers=ILINK_HEADERS) as session:
        for _ in range(60):  # 2 min
            await asyncio.sleep(2)
            try:
                url = f"{current_base_url}/ilink/bot/get_qrcode_status?qrcode={qr_value}"
                async with session.get(url) as resp:
                    status_data = json.loads(await resp.text())
            except Exception:
                continue

            status = str(status_data.get("status", ""))

            if status in ("wait", ""):
                pass  # still waiting
            elif status == "scaned":
                _wechat_state["status"] = "scanned"
            elif status == "scaned_but_redirect":
                redirect_host = str(status_data.get("redirect_host", ""))
                if redirect_host:
                    current_base_url = f"https://{redirect_host}"
            elif status == "expired":
                refresh_count += 1
                if refresh_count > 3:
                    _wechat_state["status"] = "expired"
                    return
                # Auto-refresh QR
                try:
                    async with aiohttp.ClientSession(
                        base_url=ILINK_BASE_URL, headers=ILINK_HEADERS
                    ) as refresh_session:
                        async with refresh_session.get(
                            "ilink/bot/get_bot_qrcode?bot_type=3"
                        ) as refresh_resp:
                            refresh_data = json.loads(await refresh_resp.text())
                    new_qr = str(refresh_data.get("qrcode", ""))
                    new_img = str(refresh_data.get("qrcode_img_content", ""))
                    if new_qr:
                        qr_value = new_qr
                        _wechat_state["qr_value"] = new_qr
                        _wechat_state["qr_url"] = new_img or new_qr
                except Exception:
                    pass
            elif status == "confirmed":
                account_id = str(status_data.get("ilink_bot_id", ""))
                token = str(status_data.get("bot_token", ""))
                base_url = str(status_data.get("baseurl", "") or ILINK_BASE_URL)
                if account_id and token:
                    _wechat_state["status"] = "success"
                    _wechat_state["credentials"] = {
                        "WEIXIN_TOKEN": token,
                        "WEIXIN_ACCOUNT_ID": account_id,
                        "WEIXIN_BASE_URL": base_url,
                    }
                    write_env(_wechat_state["credentials"])
                    return

    _wechat_state["status"] = "timeout"


async def handle_wechat_poll(request: web.Request) -> web.Response:
    if not _check_auth(request):
        return web.json_response({"error": "Unauthorized"}, status=401)
    return web.json_response({
        "status": _wechat_state["status"],
        "qr_url": _wechat_state["qr_url"],
        "qr_value": _wechat_state.get("qr_value", ""),
    })


async def handle_save_telegram(request: web.Request) -> web.Response:
    if not _check_auth(request):
        return web.json_response({"error": "Unauthorized"}, status=401)
    data = await request.json()
    token = data.get("token", "")
    if not token:
        return web.json_response({"error": "Token required"}, status=400)
    try:
        write_env({"TELEGRAM_BOT_TOKEN": token})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)
    return web.json_response({"ok": True})


def clean_stale_env_keys() -> None:
    """Write empty values for ALLOWED_ENV_KEYS not currently in .env.

    The gateway calls ``load_dotenv(override=True)`` at startup which only
    SETS keys found in .env — it does NOT remove keys absent from the file.
    If the container was created with stale test credentials (e.g. from a
    previous ``env_file``), those persist across ``docker restart`` because
    the initial container environment is immutable.

    By writing ``KEY=`` (empty value) for every allowed key that isn't
    explicitly configured, ``load_dotenv`` will override the stale value
    with an empty string, and the gateway's ``if api_key:`` / ``if token:``
    checks will correctly skip unconfigured providers.
    """
    existing = read_env()
    updates = {key: "" for key in ALLOWED_ENV_KEYS if key not in existing}
    if updates:
        write_env(updates)


async def handle_restart_gateway(request: web.Request) -> web.Response:
    """Restart the hermes-agent container via Docker Engine API over Unix socket.

    Before restarting, cleans stale env keys so the gateway re-reads a
    fresh .env file via ``load_dotenv(override=True)``.
    """
    if not _check_auth(request):
        return web.json_response({"error": "Unauthorized"}, status=401)

    # Clean stale env vars so load_dotenv clears them on restart
    try:
        clean_stale_env_keys()
    except Exception:
        pass  # non-fatal — best-effort cleanup

    try:
        connector = aiohttp.connector.UnixConnector("/var/run/docker.sock")
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.post(
                "http://localhost/containers/hermes-agent/restart?t=10"
            ) as resp:
                if resp.status in (200, 204, 304):
                    return web.json_response({"ok": True, "detail": "Restarting hermes-agent"})
                body = await resp.text()
                return web.json_response({"ok": False, "detail": f"Docker API {resp.status}: {body[:200]}"})
    except Exception as e:
        return web.json_response({"ok": False, "detail": str(e)})


async def run_servers():
    """Run landing page (3000) and wizard (8643) concurrently."""
    # Ensure .env exists (Docker bind-mount creates a directory if file is missing)
    if not os.path.exists(ENV_PATH):
        Path(ENV_PATH).touch()
    ensure_api_server_key()

    # Landing app (port 3000)
    landing_app = create_app()

    # Wizard app (port 8643)
    wizard_app = web.Application(middlewares=[cors_middleware])
    wizard_app.router.add_get("/setup", handle_wizard)
    wizard_app.router.add_get("/setup/status", handle_status_authed)
    wizard_app.router.add_post("/setup/model", handle_save_model)
    wizard_app.router.add_post("/setup/test-conn", handle_test_conn)
    wizard_app.router.add_post("/setup/complete", handle_complete)
    wizard_app.router.add_delete("/setup/reset", handle_reset)
    wizard_app.router.add_get("/setup/platforms/wechat/qr", handle_wechat_qr)
    wizard_app.router.add_get("/setup/platforms/wechat/poll", handle_wechat_poll)
    wizard_app.router.add_post("/setup/platforms/telegram", handle_save_telegram)
    wizard_app.router.add_post("/setup/restart", handle_restart_gateway)

    runner1 = web.AppRunner(landing_app)
    runner2 = web.AppRunner(wizard_app)
    await runner1.setup()
    await runner2.setup()

    bind_host = os.environ.get("SETUP_BIND_HOST", "0.0.0.0")
    site1 = web.TCPSite(runner1, bind_host, LANDING_PORT)
    site2 = web.TCPSite(runner2, bind_host, WIZARD_PORT)
    await site1.start()
    await site2.start()

    # Clean stale env keys on startup so the next gateway restart
    # (whether triggered by the wizard or manually) picks up a clean .env.
    try:
        clean_stale_env_keys()
    except Exception:
        pass

    print("=" * 50)
    print("  Hermes Agent 已启动！")
    print(f"  打开浏览器: http://localhost:{LANDING_PORT}")
    print("=" * 50)

    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(run_servers())
