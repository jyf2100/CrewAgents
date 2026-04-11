# Hermes Docker Setup Wizard Design

**Date:** 2026-04-11
**Status:** Approved (post-review revision)
**Scope:** Docker deployment onboarding experience

## Problem

Current Docker setup requires 7-8 manual steps, 15-45 minutes for a new user. No guided onboarding, no unified entry point, configuration split across `.env` and `config.yaml`, proxy settings hardcoded.

**Target user:** Regular users (not just developers). Web chat and WeChat equally important.

## Solution

Add a web-based setup wizard at `localhost:8643/setup` that guides users through: model selection, API key, messaging platform connection. Landing page at `localhost:3000` (moved from Open WebUI) provides entry to both chat and settings.

## Architecture

### Components

```
localhost:3000  →  Landing page (setup container) → links to chat + settings
localhost:3001  →  Open WebUI (chat interface)
localhost:8642  →  Hermes gateway API (internal, not user-facing)
localhost:8643  →  Setup wizard server
```

### Files Changed

| File | Action |
|------|--------|
| `docker-compose.yml` | Remove wechat-setup, add setup service (ports 3000+8643), move webui to 3001, proxy from .env |
| `docker/setup_server.py` | **New** — aiohttp wizard server + landing page, replacing `wechat_setup.py` |
| `docker/wechat_setup.py` | **Delete** — merged into `setup_server.py` |
| `docker/config.yaml` | Unchanged |

### Landing Page (port 3000)

A simple static page served by `setup_server.py`:

```
┌─────────────────────────────────────┐
│          ⚕ Hermes Agent            │
│                                     │
│   ┌─────────┐    ┌──────────┐      │
│   │ 💬 Chat  │    │ ⚙ Setup  │      │
│   └─────────┘    └──────────┘      │
│                                     │
│   Model: MiniMax-M2.7 ✅            │
│   WeChat: Connected ✅              │
│   Status: Running                   │
└─────────────────────────────────────┘
```

- "Chat" → `http://localhost:3001`
- "Setup" → `http://localhost:8643/setup`
- Shows current status (from `/setup/status`)
- If `.setup_complete` doesn't exist, auto-redirects to setup wizard

### Setup Server Endpoints

```
GET  /                          → Landing page (port 3000)
GET  /setup                     → Wizard HTML (3 steps with back navigation)
GET  /setup/status              → JSON: non-sensitive config metadata only
POST /setup/model               → Save model config → write config.yaml + .env
POST /setup/test-conn           → Test API key validity
GET  /setup/platforms/wechat/qr → Fetch WeChat QR code from iLink
GET  /setup/platforms/wechat/poll → Poll WeChat scan status
POST /setup/platforms/telegram  → Save Telegram bot token to .env
POST /setup/complete            → Write .setup_complete marker
DELETE /setup/reset             → Clear .setup_complete, return to wizard mode
```

### Data Flow

Config keys are split by reload mechanism:

**config.yaml (read per agent turn, hot-reloadable):**
- model.default, model.provider

**.env (baked into process env, requires container restart):**
- API keys, platform tokens, proxy settings

```
User fills wizard form
  → setup_server.py validates & sanitizes input
  → setup_server.py writes to:
    /opt/data/.env            (API keys, platform tokens)
    /opt/data/config.yaml     (model name, provider)
    /opt/data/.setup_complete (completion marker)
  → docker restart hermes-agent (via Docker socket)
  → UI polls /setup/status until gateway responds
```

## Wizard UI

### Navigation

- Every step has `[← Back]` and `[Next →]`
- Server tracks wizard state in `/opt/data/.wizard_state`
- On page load, client reads current state via `/setup/status` and resumes at correct step
- Previously entered values are pre-populated from existing config

### Step 1/3: AI Model

- Provider dropdown with descriptions:
  - MiniMax (CN) — Recommended for China users
  - OpenRouter — Access to 100+ models
  - Gemini — Google AI Studio
  - Custom — Any OpenAI-compatible endpoint (shows base_url + key fields)
- API Key input with "Get Key" link (per-provider, opens in new tab)
- Model dropdown (auto-populated per provider)
- Proxy field (optional): `http://host.docker.internal:7890` — shown for China providers by default
- [Test Connection] button — calls chat/completions once
- [← Back] [Next →]

### Step 2/3: Messaging Platforms (optional)

- Card selection: WeChat | Telegram | Skip (Discord deferred — no endpoint yet)
- WeChat: inline QR code, auto-poll, auto-refresh on expiry
- Telegram: token input field with "Get Token" link to @BotFather
- Skip advances to step 3
- [← Back] [Next →]

### Step 3/3: Complete

- Summary: model, connected platforms, API endpoint
- "Restarting gateway..." loading state while polling gateway readiness
- [Start Chat →] button → redirects to `http://localhost:3001`
- Note: "Bookmark this page to change settings: localhost:8643/setup"

### Visual Style

- Dark theme matching Open WebUI
- Hermes brand colors: gold #FFB800, dark blue #0F172A
- Responsive: max-width 480px, min-height 48px touch targets
- Status colors: blue=waiting, green=success, red=error, orange=timeout
- WCAG 2.1 AA contrast ratios for all text
- `prefers-reduced-motion` media query disables animations

### Accessibility

- `<html lang="zh-CN">` for Chinese-targeted deployment
- ARIA labels on all form fields, step indicators, QR image, status messages
- Visible focus indicators for keyboard navigation (Tab/Enter/Escape)
- `<label>` elements on all inputs (no placeholder-only)
- Inline SVG icons instead of emoji for consistent cross-platform rendering
- Screen reader announcements for QR scan status changes

## Error Handling

| Scenario | User Feedback | Action |
|----------|--------------|--------|
| Invalid API key | "API Key invalid, check and retry" | Red alert, preserve input |
| Rate limit / quota | "API quota exceeded, check your plan" | Show provider dashboard link |
| Model not available | "Model X not available with this key" | Suggest alternative models |
| Network/proxy error | "Cannot reach server, check network or proxy settings" | Check proxy field |
| QR expired | Auto-refresh QR, "QR refreshed, please scan again" | No user action needed |
| QR timeout (2min) | "Scan timeout, tap retry" | Retry button |
| Gateway restart fail | "Restart failed, run `docker compose restart hermes-agent`" | Show command |
| .env write fail | "Config save failed, check file permissions" | Show specific error |
| Partial write (config.yaml ok, .env fail) | "Partial save — retry to complete" | Atomic: write .env first, then config.yaml |
| Setup complete but config invalid | Warning on landing page + "Reconfigure" link | DELETE /setup/reset + re-run wizard |

## Security

### Authentication

- GET `/` (landing page) — no auth
- GET `/setup` (wizard HTML) — no auth (first-run convenience)
- GET `/setup/status` — no auth, but **strips all secret values** (returns only: provider name, model name, platform connected yes/no, setup_complete bool)
- All POST/DELETE endpoints — require `Authorization: Bearer <API_SERVER_KEY>`
- API_SERVER_KEY generated at first run (`secrets.token_hex(24)`) and stored in `.env`

### Input Validation

- Whitelist allowed env var names (only known Hermes config keys)
- Reject values containing newlines, null bytes, or shell metacharacters
- Validate model names against provider's model list (when available)

### CORS

- Setup server allows requests from `http://localhost:3000` and `http://localhost:3001` only
- No wildcard `Access-Control-Allow-Origin`
- CSRF: Bearer token in header (not cookie-based) + same-origin for wizard JS

### Container Security

- Setup server binds to `127.0.0.1` inside container (port mapping controls external access)
- Docker socket mounted for restart capability (setup container runs same trusted image as hermes)
- All file writes use atomic pattern: write to temp file, then `os.replace()`
- No `os.system()` or `shell=True` — all subprocess calls use `subprocess.run()` with arg lists

## Configuration Reload

1. Primary: `docker restart hermes-agent` via Docker socket
2. No SIGHUP (gateway doesn't support it)
3. UI shows "Restarting gateway..." spinner, polls `/setup/status` until gateway responds (timeout: 30s)
4. If restart times out: show manual command `docker compose restart hermes-agent`

## docker-compose.yml Changes

```yaml
services:
  hermes:
    # unchanged, port 8642

  webui:
    image: ghcr.io/open-webui/open-webui:main
    ports:
      - "3001:8080"              # moved from 3000 to 3001
    environment:
      - OPENAI_API_BASE_URL=http://hermes:8642/v1
      - OPENAI_API_KEY=${API_SERVER_KEY}
      - WEBUI_AUTH=false
    # ... rest unchanged

  setup:
    image: nousresearch/hermes-agent:latest
    entrypoint: ["python3", "/opt/hermes/docker/setup_server.py"]
    ports:
      - "3000:3000"              # landing page
      - "8643:8643"              # wizard
    volumes:
      - hermes-data:/opt/data
      - ./.env:/opt/data/.env
      - ./docker/setup_server.py:/opt/hermes/docker/setup_server.py
      - ./docker/config.yaml:/opt/data/config.yaml
      - /var/run/docker.sock:/var/run/docker.sock  # for container restart
    environment:
      - HERMES_HOME=/opt/data
      - HTTP_PROXY=${HTTP_PROXY:-}
      - HTTPS_PROXY=${HTTPS_PROXY:-}
      - NO_PROXY=${NO_PROXY:-localhost,127.0.0.1}
    extra_hosts:
      - "host.docker.internal:host-gateway"
    restart: unless-stopped
```

Key changes:
- Landing page on port 3000 (replaces Open WebUI at that port)
- Open WebUI moved to 3001
- Proxy/API key values from `.env` (no hardcoding)
- Docker socket mounted for container restart
- No wechat-setup container (merged into setup)

## First-Run User Journey (revised)

```
docker compose up
  │
  ▼
Terminal prints:
  ═════════════════════════════════════
    ⚕ Hermes Agent 已启动！
    打开浏览器: http://localhost:3000
  ═════════════════════════════════════
  │
  ▼
User opens localhost:3000 → landing page detects no .setup_complete
  │
  ▼
Auto-redirect to localhost:8643/setup (wizard)
  │
  ▼
Step 1: Select provider, enter API key, test connection
  │  [← Back] [Next →]
  ▼
Step 2: Connect WeChat (QR scan) or Telegram, or skip
  │  [← Back] [Next →]
  ▼
Step 3: "Restarting gateway..." → "Ready!" → [Start Chat →]
  │
  ▼
Redirect to localhost:3001 (Open WebUI) — chat begins
```

Subsequent visits to localhost:3000 show landing page with Chat + Settings links.
