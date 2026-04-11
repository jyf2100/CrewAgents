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
    if origin in ("http://localhost:3080", "http://localhost:3001"):
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


def create_app() -> web.Application:
    app = web.Application(middlewares=[cors_middleware])
    app.router.add_get("/", handle_landing)
    app.router.add_get("/status", handle_status)
    app.router.add_get("/manifest.json", handle_manifest)
    app.router.add_get("/sw.js", handle_sw_js)
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
.qr-area{margin-top:16px;text-align:center}
.qr-area img{max-width:200px;border-radius:8px;border:1px solid #334155}
.qr-status{margin-top:8px;font-size:14px}
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
      <p class="platform-note">WeChat 扫码需从另一台设备（手机）操作</p>
      <div class="qr-area" id="qrArea">
        <div class="qr-status" id="qrStatus" role="status" aria-live="polite">Click to start</div>
      </div>
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

function goStep(n) {
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
  const qrArea = document.getElementById("qrArea");
  const qrStatus = document.getElementById("qrStatus");
  qrStatus.innerHTML = '<span class="spinner"></span>Loading QR code...';

  try {
    const resp = await fetch("/setup/platforms/wechat/qr", { headers: authHeaders() });
    const data = await resp.json();
    if (data.qr_url) {
      // Use DOM API to prevent XSS from untrusted QR URL
      var img = document.createElement("img");
      img.src = data.qr_url;
      img.alt = "WeChat QR Code";
      img.style.maxWidth = "200px";
      img.style.borderRadius = "8px";
      img.style.border = "1px solid #334155";
      qrArea.innerHTML = "";
      qrArea.appendChild(img);
      var statusDiv = document.createElement("div");
      statusDiv.className = "qr-status";
      statusDiv.id = "qrStatus";
      statusDiv.setAttribute("role", "status");
      statusDiv.setAttribute("aria-live", "polite");
      statusDiv.innerHTML = '<span class="spinner"></span>Waiting for scan...';
      qrArea.appendChild(statusDiv);
      pollWechat();
    } else {
      qrStatus.textContent = data.error || "Failed to get QR code";
    }
  } catch (e) {
    qrStatus.textContent = "Error: " + e.message;
  }
}

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
    env_updates = {p["env_key"]: api_key}
    if provider == "custom" and data.get("base_url"):
        env_updates["OPENAI_BASE_URL"] = data["base_url"]
    if proxy:
        env_updates["HTTP_PROXY"] = proxy
        env_updates["HTTPS_PROXY"] = proxy

    try:
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
    _wechat_state["status"] = "fetching"
    _wechat_state["qr_url"] = ""
    _wechat_state["credentials"] = None

    try:
        async with aiohttp.ClientSession(base_url=ILINK_BASE_URL, headers=ILINK_HEADERS) as session:
            async with session.get("ilink/bot/get_bot_qrcode") as resp:
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

        return web.json_response({"status": "waiting", "qr_url": _wechat_state["qr_url"]})
    except Exception as e:
        _wechat_state["status"] = "error"
        return web.json_response({"status": "error", "detail": str(e)})


async def _poll_wechat_scan() -> None:
    """Background task: poll iLink for QR scan status."""
    qr_value = _wechat_state.get("qr_value", "")
    if not qr_value:
        return

    async with aiohttp.ClientSession(base_url=ILINK_BASE_URL, headers=ILINK_HEADERS) as session:
        for _ in range(60):  # 2 min
            await asyncio.sleep(2)
            try:
                async with session.get(f"ilink/bot/get_qrcode_status?qrcode={qr_value}") as resp:
                    status_data = json.loads(await resp.text())
            except Exception:
                continue

            status = str(status_data.get("status", ""))

            if status == "2":
                _wechat_state["status"] = "scanned"
            elif status in ("0", "success"):
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
            elif status == "3":
                new_qr = str(status_data.get("qrcode", ""))
                new_img = str(status_data.get("qrcode_img_content", ""))
                if new_qr:
                    qr_value = new_qr
                    _wechat_state["qr_value"] = new_qr
                    _wechat_state["qr_url"] = new_img or new_qr

    _wechat_state["status"] = "timeout"


async def handle_wechat_poll(request: web.Request) -> web.Response:
    return web.json_response({
        "status": _wechat_state["status"],
        "qr_url": _wechat_state["qr_url"],
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


async def handle_restart_gateway(request: web.Request) -> web.Response:
    """Restart the hermes-agent container via Docker socket."""
    if not _check_auth(request):
        return web.json_response({"error": "Unauthorized"}, status=401)
    try:
        import docker
        client = docker.from_env()
        client.containers.get("hermes-agent").restart(timeout=10)
        return web.json_response({"ok": True, "detail": "Restarting hermes-agent"})
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

    print("=" * 50)
    print("  Hermes Agent 已启动！")
    print(f"  打开浏览器: http://localhost:{LANDING_PORT}")
    print("=" * 50)

    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(run_servers())
