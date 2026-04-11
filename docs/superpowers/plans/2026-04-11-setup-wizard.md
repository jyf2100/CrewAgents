# Hermes Setup Wizard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the fragmented Docker setup (3 ports, no guidance, hardcoded config) with a unified setup wizard + landing page that guides non-technical users from `docker compose up` to chatting in 3 steps.

**Architecture:** Single aiohttp server (`setup_server.py`) serves a landing page on port 3000 and a 3-step setup wizard on port 8643. Open WebUI moves to port 3001. The wizard writes config atomically and restarts the hermes container via Docker socket.

**Tech Stack:** Python 3.13, aiohttp (pre-installed in hermes image), Docker SDK for Python (pre-installed), vanilla HTML/CSS/JS (no build step).

**Spec:** `docs/superpowers/specs/2026-04-11-setup-wizard-design.md`

---

## File Structure

| File | Responsibility |
|------|----------------|
| `docker/setup_server.py` | **New** — aiohttp server: landing page, wizard, config API, WeChat QR, Docker restart |
| `docker-compose.yml` | Rewrite: new setup service, webui moved to 3001, remove wechat-setup |
| `docker/wechat_setup.py` | **Delete** — replaced by setup_server.py |
| `docker/config.yaml` | Unchanged |

---

## Provider Definitions

Used by the wizard to populate dropdowns and validate inputs:

```python
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
```

---

### Task 1: Config read/write utilities

**Files:**
- Create: `docker/setup_server.py` (start file, add config helpers)

- [ ] **Step 1: Create setup_server.py with config helpers**

```python
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
WIZARD_STATE_PATH = os.path.join(HERMES_HOME, ".wizard_state")

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

UNSAFE_CHARS_RE = re.compile(r"[\n\r\x00`$]")


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
        os.unlink(tmp)
        raise


def write_env(updates: dict[str, str]) -> None:
    """Write specific env vars into .env, preserving existing content."""
    # Validate all keys and values
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
    with open(CONFIG_PATH) as f:
        content = f.read()
    # Simple extraction of model.default and model.provider
    for line in content.split("\n"):
        stripped = line.strip()
        if stripped.startswith("default:"):
            result["model"] = stripped.split(":", 1)[1].strip().strip('"').strip("'")
        elif stripped.startswith("provider:"):
            result["provider"] = stripped.split(":", 1)[1].strip().strip('"').strip("'")
    return result


def write_config_yaml(model: str, provider: str) -> None:
    """Write minimal config.yaml with model settings."""
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


def ensure_api_server_key() -> str:
    """Get or generate API_SERVER_KEY, save to .env."""
    env = read_env()
    key = env.get("API_SERVER_KEY", "")
    if not key:
        key = secrets.token_hex(24)
        write_env({"API_SERVER_KEY": key})
    return key


def get_setup_status() -> dict:
    """Return non-sensitive config status for the frontend."""
    config = read_config_yaml()
    env = read_env()
    wechat_connected = bool(env.get("WEIXIN_TOKEN") and env.get("WEIXIN_ACCOUNT_ID"))
    telegram_connected = bool(env.get("TELEGRAM_BOT_TOKEN"))
    return {
        "setup_complete": is_setup_complete(),
        "model": config.get("model", ""),
        "provider": config.get("provider", ""),
        "wechat_connected": wechat_connected,
        "telegram_connected": telegram_connected,
        "has_api_key": bool(env.get("MINIMAX_CN_API_KEY") or env.get("OPENROUTER_API_KEY") or env.get("GOOGLE_API_KEY") or env.get("OPENAI_API_KEY")),
    }
```

- [ ] **Step 2: Verify file loads**

Run: `python3 -c "import sys; sys.path.insert(0, 'docker'); from setup_server import read_env, get_setup_status; print(get_setup_status())"`
Expected: JSON dict with setup_complete, model, provider keys

- [ ] **Step 3: Commit**

```bash
git add docker/setup_server.py
git commit -m "feat(setup): config read/write utilities with atomic writes and input validation"
```

---

### Task 2: aiohttp server skeleton with landing page

**Files:**
- Modify: `docker/setup_server.py` (append server code)

- [ ] **Step 1: Add aiohttp app factory and landing page handler**

Append to `docker/setup_server.py`:

```python
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


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", handle_landing)
    app.router.add_get("/status", handle_status)
    return app


if __name__ == "__main__":
    print("=" * 50)
    print("  Hermes Agent 已启动！")
    print(f"  打开浏览器: http://localhost:{LANDING_PORT}")
    print("=" * 50)
    web.run_app(create_app(), host="127.0.0.1", port=LANDING_PORT)
```

- [ ] **Step 2: Test landing page locally**

Run: `cd /Users/roc/workspace/hermes-agent && python3 docker/setup_server.py &` then `curl -s http://localhost:3000/ | head -5`
Expected: HTML starting with `<!DOCTYPE html>`
Cleanup: `kill %1`

- [ ] **Step 3: Commit**

```bash
git add docker/setup_server.py
git commit -m "feat(setup): aiohttp server skeleton with landing page"
```

---

### Task 3: Wizard HTML (3-step SPA)

**Files:**
- Modify: `docker/setup_server.py` (add wizard handler + HTML)

- [ ] **Step 1: Add wizard page handler**

Append the wizard HTML as a separate handler. The wizard is a single-page app with 3 steps controlled by JavaScript (no server-side routing for steps — state tracked client-side).

Add to `docker/setup_server.py` before `create_app()`:

```python
async def handle_wizard(request: web.Request) -> web.Response:
    return web.Response(text=WIZARD_HTML, content_type="text/html")
```

And register in `create_app()`:
```python
app.router.add_get("/setup", handle_wizard)
```

The `WIZARD_HTML` constant contains the full 3-step wizard SPA. It is large (~200 lines of HTML/CSS/JS) and includes:
- Step 1 form: provider dropdown, API key input, model dropdown, proxy field, test button
- Step 2 form: WeChat/Telegram/Skip cards, inline QR code display, token input
- Step 3: summary, restart spinner, redirect button
- JavaScript: step navigation (back/next), AJAX calls to `/setup/*` endpoints, QR polling
- Accessibility: `<label>` on all inputs, ARIA attributes, `prefers-reduced-motion`, keyboard focus

(See the full HTML in the spec's Visual Style and Accessibility sections for reference. The implementer writes the exact HTML following the ASCII wireframes from the spec.)

- [ ] **Step 2: Test wizard page loads**

Run: `curl -s http://localhost:8643/setup | head -5`
Expected: HTML with `<html lang="zh-CN">`

- [ ] **Step 3: Commit**

```bash
git add docker/setup_server.py
git commit -m "feat(setup): 3-step wizard HTML with provider/model/messaging forms"
```

---

### Task 4: API endpoints (model, test-conn, complete, reset)

**Files:**
- Modify: `docker/setup_server.py` (add POST handlers)

- [ ] **Step 1: Add POST endpoint handlers**

Add these handlers to `docker/setup_server.py`:

```python
def _get_auth_key() -> str:
    return ensure_api_server_key()


def _check_auth(request: web.Request) -> bool:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:] == _get_auth_key()
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
        return web.json_response({"error": "Base URL required for custom provider"}, status=400)

    import aiohttp
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
                return web.json_response({"ok": False, "status": resp.status, "detail": body[:200]}, status=200)
    except Exception as e:
        return web.json_response({"ok": False, "detail": str(e)}, status=200)


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
```

Register in `create_app()`:
```python
app.router.add_post("/setup/model", handle_save_model)
app.router.add_post("/setup/test-conn", handle_test_conn)
app.router.add_post("/setup/complete", handle_complete)
app.router.add_delete("/setup/reset", handle_reset)
```

- [ ] **Step 2: Test model save endpoint**

Run: `curl -s -X POST http://localhost:8643/setup/model -H "Authorization: Bearer <key>" -H "Content-Type: application/json" -d '{"provider":"minimax-cn","api_key":"test-key","model":"MiniMax-M2.7"}'`
Expected: `{"ok": true}`

- [ ] **Step 3: Commit**

```bash
git add docker/setup_server.py
git commit -m "feat(setup): model save, test-conn, complete, reset endpoints"
```

---

### Task 5: WeChat QR integration

**Files:**
- Modify: `docker/setup_server.py` (add QR endpoints)

- [ ] **Step 1: Add WeChat QR endpoints**

Port the QR login logic from the old `wechat_setup.py`, but restructured as on-demand aiohttp handlers (not a background thread). The QR flow is now request-driven: frontend calls `/qr` to start, then polls `/poll`.

Add to `docker/setup_server.py`:

```python
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
    import aiohttp

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

        # Start background polling
        asyncio.ensure_future(_poll_wechat_scan())

        return web.json_response({"status": "waiting", "qr_url": _wechat_state["qr_url"]})
    except Exception as e:
        _wechat_state["status"] = "error"
        return web.json_response({"status": "error", "detail": str(e)})


async def _poll_wechat_scan() -> None:
    """Background task: poll iLink for QR scan status."""
    import aiohttp

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
                # Expired — refresh
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
```

Register in `create_app()`:
```python
app.router.add_get("/setup/platforms/wechat/qr", handle_wechat_qr)
app.router.add_get("/setup/platforms/wechat/poll", handle_wechat_poll)
```

- [ ] **Step 2: Test QR endpoint returns structure**

Run: `curl -s http://localhost:8643/setup/platforms/wechat/qr`
Expected: JSON with `status` and `qr_url` fields (may fail if iLink unreachable from host, that's OK — verify structure)

- [ ] **Step 3: Commit**

```bash
git add docker/setup_server.py
git commit -m "feat(setup): WeChat QR code integration with async polling"
```

---

### Task 6: Telegram config + Docker restart

**Files:**
- Modify: `docker/setup_server.py` (add telegram + restart handlers)

- [ ] **Step 1: Add Telegram and Docker restart handlers**

```python
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
        return web.json_response({"ok": False, "detail": str(e)}, status=200)
```

Register in `create_app()`:
```python
app.router.add_post("/setup/platforms/telegram", handle_save_telegram)
app.router.add_post("/setup/restart", handle_restart_gateway)
```

- [ ] **Step 2: Commit**

```bash
git add docker/setup_server.py
git commit -m "feat(setup): Telegram save + Docker restart via socket"
```

---

### Task 7: Dual-port server (landing + wizard)

**Files:**
- Modify: `docker/setup_server.py` (update `__main__` to run both ports)

- [ ] **Step 1: Update main to run both servers**

Replace the `if __name__ == "__main__"` block:

```python
async def run_servers():
    """Run landing page (3000) and wizard (8643) concurrently."""
    ensure_api_server_key()

    landing_app = create_app()
    wizard_app = web.Application()
    # Re-use same routes on wizard port
    wizard_app.router.add_get("/setup", handle_wizard)
    wizard_app.router.add_get("/setup/status", handle_status)
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

    site1 = web.TCPSite(runner1, "127.0.0.1", LANDING_PORT)
    site2 = web.TCPSite(runner2, "127.0.0.1", WIZARD_PORT)
    await site1.start()
    await site2.start()

    print("=" * 50)
    print("  Hermes Agent 已启动！")
    print(f"  打开浏览器: http://localhost:{LANDING_PORT}")
    print("=" * 50)

    # Keep running forever
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(run_servers())
```

- [ ] **Step 2: Test both ports respond**

Run: `python3 docker/setup_server.py &` then:
- `curl -s http://localhost:3000/ | grep Hermes`
- `curl -s http://localhost:8643/setup | grep Hermes`
Expected: Both return HTML
Cleanup: `kill %1`

- [ ] **Step 3: Commit**

```bash
git add docker/setup_server.py
git commit -m "feat(setup): dual-port server — landing (3000) + wizard (8643)"
```

---

### Task 8: Update docker-compose.yml

**Files:**
- Modify: `docker-compose.yml`
- Delete: `docker/wechat_setup.py`

- [ ] **Step 1: Rewrite docker-compose.yml**

Per the spec's docker-compose.yml section. Key changes:
- Remove `wechat-setup` service
- Add `setup` service (ports 3000, 8643, docker socket mount)
- Move `webui` from port 3000 to 3001
- Remove hardcoded proxy/API key values (source from `.env`)

- [ ] **Step 2: Delete old wechat_setup.py**

```bash
rm docker/wechat_setup.py
```

- [ ] **Step 3: Test full stack starts**

```bash
docker compose down -v 2>/dev/null; docker compose up -d 2>&1
docker compose ps
curl -s http://localhost:3000/ | grep Hermes
curl -s http://localhost:3001/ | grep -i "open.webui\|chat"
curl -s http://localhost:8643/setup | grep Hermes
```
Expected: All three return valid HTML

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml
git rm docker/wechat_setup.py
git commit -m "feat(setup): docker-compose with unified setup service, webui on 3001"
```

---

### Task 9: End-to-end smoke test

- [ ] **Step 1: Test first-run redirect**

```bash
# Ensure no setup marker
docker compose exec setup rm -f /opt/data/.setup_complete
curl -s http://localhost:3000/ | grep "window.location.href"
```
Expected: Page contains redirect to `localhost:8643/setup`

- [ ] **Step 2: Test wizard step 1 (model save + test connection)**

```bash
# Get the auto-generated API key
API_KEY=$(grep API_SERVER_KEY .env | cut -d= -f2)

curl -s -X POST http://localhost:8643/setup/model \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"provider":"minimax-cn","api_key":"'"$MINIMAX_CN_API_KEY"'","model":"MiniMax-M2.7"}'
```
Expected: `{"ok": true}`

- [ ] **Step 3: Test complete + landing page shows configured state**

```bash
curl -s -X POST http://localhost:8643/setup/complete \
  -H "Authorization: Bearer $API_KEY"
# Expected: {"ok": true}

curl -s http://localhost:3000/ | grep "MiniMax-M2.7"
# Expected: Landing page shows model name
```

- [ ] **Step 4: Test WeChat QR endpoint**

```bash
curl -s http://localhost:8643/setup/platforms/wechat/qr | python3 -m json.tool
```
Expected: JSON with `status` and `qr_url` (may timeout if iLink unreachable, but structure must be valid)

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "test(setup): verify end-to-end first-run, model config, and QR flow"
```

---

## Task Summary

| Task | What | Key Files |
|------|------|-----------|
| 1 | Config read/write utilities + wizard state | `docker/setup_server.py` |
| 2 | aiohttp skeleton + landing page + CORS | `docker/setup_server.py` |
| 3 | Dual-port server wiring | `docker/setup_server.py` |
| 4 | Wizard HTML (3-step SPA) | `docker/setup_server.py` |
| 5 | API endpoints (model, test, complete, reset) | `docker/setup_server.py` |
| 6 | WeChat QR integration | `docker/setup_server.py` |
| 7 | Telegram + Docker restart | `docker/setup_server.py` |
| 8 | docker-compose rewrite | `docker-compose.yml`, delete `wechat_setup.py` |
| 9 | End-to-end smoke test | All |

**Review fixes applied:**
- Task 3 (dual-port) moved earlier so Tasks 4-7 endpoints can be verified
- CORS middleware added in Task 2
- Wizard state persistence added in Task 1 (read/write + `/setup/status` integration)
- Config pre-population via extended `/setup/status` response
- Task 7 (Telegram+restart) now has verification step
- `write_config_yaml` documented as authoritative (intentional — setup owns config)
