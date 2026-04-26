# Admin Panel WeChat (Weixin) Integration Design

> **Date:** 2026-04-20
> **Status:** Approved
> **Branch:** feature/opensandbox-lifecycle

## Goal

Add WeChat registration, status monitoring, and unbind capabilities to the Hermes Admin Panel. Users can initiate QR code login from the admin UI, monitor WeChat connection status at a glance, and manage WeChat bindings without touching the terminal.

## Architecture

Admin backend calls iLink Bot API directly to perform QR login. Credentials obtained from QR login are written to the target agent's `.env` and `config.yaml`, followed by a Pod restart.

```
Browser                    Admin Backend (FastAPI)           iLink API
  │                              │                              │
  │  POST /agents/{id}/weixin/qr │                              │
  │  (SSE stream)                │  GET get_bot_qrcode          │
  │                              │ ───────────────────────────> │
  │  <── SSE: qr_ready ────────│ <── qrcode + img_url ────────│
  │  <── SSE: status=wait ─────│                              │
  │                              │  GET get_qrcode_status       │
  │  (user scans QR)             │ ───────────────────────────> │
  │  <── SSE: status=scaned ────│ <── scaned ──────────────────│
  │  <── SSE: status=confirmed──│ <── account_id, token ───────│
  │                              │                              │
  │                              │  write .env + config.yaml    │
  │                              │  restart Pod                 │
  │  <── SSE: done ────────────│                              │
```

## API Endpoints

### 1. POST /agents/{agent_id}/weixin/qr

Initiate QR login session. Returns SSE stream with real-time status updates.

**Auth:** Required (`X-Admin-Key`)

**Response:** `text/event-stream`

SSE event types:

| Event | Data | Description |
|-------|------|-------------|
| `qr_ready` | `{qrcode_url, session_id}` | QR code image URL ready for display |
| `status_update` | `{status, message}` | Status change: wait, scaned, expired |
| `qr_refresh` | `{qrcode_url}` | New QR code after expiry (auto-refresh, max 3 times) |
| `done` | `{account_id, user_id, base_url}` | Login confirmed, credentials saved, Pod restarting |
| `error` | `{message}` | Unrecoverable error |
| `timeout` | `{message}` | Session timed out (8 min) |

**Backend flow:**

1. Validate agent exists and is running
2. Check no active QR session for this agent (concurrent guard)
3. Call iLink `GET ilink/bot/get_bot_qrcode?bot_type=3`
4. Push `qr_ready` SSE event with `qrcode_img_content` URL
5. Start polling `GET ilink/bot/get_qrcode_status?qrcode={value}` every 1s
6. Map iLink statuses to SSE events:
   - `wait` → `status_update` (show spinner in UI)
   - `scaned` → `status_update` (show "confirm on phone")
   - `scaned_but_redirect` → update `base_url`, continue polling
   - `expired` → refresh QR (max 3), push `qr_refresh`
   - `confirmed` → extract credentials, save, push `done`
7. On `done`: write `.env` vars, update `config.yaml`, restart Pod

**Error cases:**

| Condition | Response |
|-----------|----------|
| Agent not found | 404 |
| Agent not running | 400 "Agent must be running to register WeChat" |
| Active QR session exists | 409 "QR login already in progress" |
| iLink API unreachable | SSE `error` event |
| QR expired 3 times | SSE `error` event "QR expired too many times" |
| Timeout (8 min) | SSE `timeout` event |

**Concurrent guard:** In-memory dict `_weixin_qr_sessions: dict[int, str]` mapping agent_id to session_id. Cleared on session completion/error/timeout.

### 2. GET /agents/{agent_id}/weixin/status

Read WeChat connection status for an agent.

**Auth:** Required

**Response:**

```json
{
  "agent_number": 3,
  "connected": true,
  "account_id": "abc123",
  "user_id": "u456",
  "base_url": "https://ilinkai.weixin.qq.com",
  "dm_policy": "open",
  "group_policy": "disabled",
  "bound_at": "2026-04-18T10:30:00Z"
}
```

**Backend logic:**

1. Read `.env` for the agent
2. Check `WEIXIN_ACCOUNT_ID` and `WEIXIN_TOKEN` presence
3. Read `config.yaml` for `platforms.weixin` settings
4. Return status (both must be present for `connected: true`)
5. `bound_at` comes from the account JSON file at `/data/hermes/agent{N}/weixin/accounts/{account_id}.json` if available

### 3. DELETE /agents/{agent_id}/weixin/bind

Unbind WeChat from an agent. Clears credentials and restarts Pod.

**Auth:** Required

**Response:**

```json
{
  "agent_number": 3,
  "action": "unbind_weixin",
  "success": true,
  "message": "WeChat unbound and agent restarted"
}
```

**Backend flow:**

1. Validate agent exists
2. Remove from `.env`: `WEIXIN_ACCOUNT_ID`, `WEIXIN_TOKEN`, `WEIXIN_BASE_URL`, `WEIXIN_CDN_BASE_URL`
3. In `config.yaml`: set `platforms.weixin.enabled: false`
4. Delete account file at `/data/hermes/agent{N}/weixin/accounts/` if exists
5. Restart Pod

## Frontend Design

### Overview Tab — WeChat Status Card

A new card in the AgentDetailPage Overview tab, positioned between Resource Usage and Pod List.

**States:**

| Status | Card Content |
|--------|-------------|
| **Not bound** | Gray icon, "WeChat not connected", cyan "Register" button |
| **Connected** | Green icon, account_id (truncated), bind time, "Re-register" + "Unbind" buttons |
| **Expired** | Yellow warning icon, "Session expired", "Re-register" button |
| **QR in progress** | Pulsing cyan icon, "QR scanning...", no action buttons |

**Card layout (connected state):**

```
┌──────────────────────────────────────────┐
│  WeChat Connection                    🟢  │
│  ──────────────────────────────────────  │
│  Account:  abc1...xyz                    │
│  Bound:    2026-04-18 10:30              │
│  DM:       open    Groups:  disabled     │
│                                          │
│  [Re-register]           [Unbind]        │
└──────────────────────────────────────────┘
```

**Card layout (not bound):**

```
┌──────────────────────────────────────────┐
│  WeChat Connection                       │
│  ──────────────────────────────────────  │
│  Not connected to WeChat                 │
│                                          │
│  [  Register WeChat  ]  ← cyan button    │
└──────────────────────────────────────────┘
```

### QR Code Modal

Full-screen overlay triggered by "Register" or "Re-register" button. Uses existing glass effect from cyberpunk design system.

**Structure:**

```
┌──────────────────────────────────────────────────────┐
│  ┌────────────────────────────────────────────────┐  │
│  │                                                │  │
│  │     Scan QR with WeChat                        │  │
│  │                                                │  │
│  │     ┌──────────────────┐                       │  │
│  │     │                  │                       │  │
│  │     │   [QR Code IMG]  │   ← from qrcode_url  │  │
│  │     │                  │                       │  │
│  │     └──────────────────┘                       │  │
│  │                                                │  │
│  │     Status: Waiting for scan...                │  │
│  │     ────────────────────── ████░░░░░░  02:30   │  │
│  │     (progress bar + countdown)                 │  │
│  │                                                │  │
│  │              [Cancel]                          │  │
│  └────────────────────────────────────────────────┘  │
│  (glass backdrop, click outside to cancel)           │
└──────────────────────────────────────────────────────┘
```

**SSE-driven state machine:**

```
qr_ready → show QR image + "Waiting for scan..." + countdown
status_update(wait) → keep showing, no change
status_update(scaned) → "Scanned! Confirm on phone..." (cyan text)
qr_refresh → replace QR image, reset countdown
done → "Connected!" (green text) → auto-close modal after 2s → refresh overview
error → show error message + "Retry" button
timeout → "Timed out" + "Retry" button
```

**Countdown:** 8 minutes (480s) from QR display. Progress bar shrinks. On 0, shows "Timed out".

**Cancel:** Closes EventSource connection, shows `ConfirmDialog` "Cancel QR login?".

### Config Tab — .env Sub-tab Enhancement

WeChat-related env vars get a visual group header and colored badge:

```
┌─ WeChat (Weixin) ─────────────── 🟢 Connected ─┐
│  WEIXIN_ACCOUNT_ID    abc1...xyz                 │
│  WEIXIN_TOKEN         ********                   │  ← always masked
│  WEIXIN_DM_POLICY     open                       │
│  WEIXIN_GROUP_POLICY  disabled                   │
│  WEIXIN_ALLOWED_USERS (empty)                    │
│  WEIXIN_HOME_CHANNEL (empty)                     │
└──────────────────────────────────────────────────┘
```

### Dashboard Page — Agent Card Indicator

Small WeChat icon in the AgentCard status row:

- Green WeChat icon: connected
- No icon: not connected

Not shown for agents without WeChat config (no false negatives).

## Data Persistence

### .env Writes

On successful QR login, write:

```bash
WEIXIN_ACCOUNT_ID={account_id}
WEIXIN_TOKEN={token}
WEIXIN_BASE_URL={base_url}
```

Also save account metadata file (reuse existing `save_weixin_account` pattern):

```
/data/hermes/agent{N}/weixin/accounts/{account_id}.json
{
  "token": "...",
  "base_url": "...",
  "user_id": "...",
  "saved_at": "2026-04-20T10:30:00Z"
}
```

### config.yaml Update

Enable WeChat platform:

```yaml
platforms:
  weixin:
    enabled: true
    extra:
      account_id: "{account_id}"
```

### Unbind Cleanup

Remove from `.env`: all `WEIXIN_*` keys
Update `config.yaml`: `platforms.weixin.enabled: false`
Delete: `/data/hermes/agent{N}/weixin/accounts/` directory

## New Files

| File | Purpose |
|------|---------|
| `admin/backend/weixin.py` | QR login orchestration, iLink API calls, credential management |
| `admin/frontend/src/components/WeChatCard.tsx` | Status card for overview tab |
| `admin/frontend/src/components/WeChatQRModal.tsx` | Full-screen QR modal with SSE |

## Modified Files

| File | Changes |
|------|---------|
| `admin/backend/main.py` | Add 3 new routes under `agents-weixin` tag |
| `admin/backend/models.py` | Add `WeixinStatusResponse`, `WeixinActionResponse` |
| `admin/backend/config_manager.py` | Add `read_env_raw()` (unmasked) for status check, `remove_env_keys()` for unbind |
| `admin/frontend/src/pages/AgentDetailPage.tsx` | Add WeChatCard to overview, env group highlighting in config |
| `admin/frontend/src/lib/admin-api.ts` | Add `startWeixinQR()`, `getWeixinStatus()`, `unbindWeixin()` |

## Security Considerations

- WEIXIN_TOKEN is always masked in API responses (like other secrets)
- QR session is agent-scoped (one session per agent at a time)
- SSE token system not needed — QR endpoint itself is auth-protected
- Unbind requires admin key + ConfirmDialog
- iLink API calls use HTTPS only

## Error Handling

| Scenario | Backend | Frontend |
|----------|---------|----------|
| iLink down | SSE `error` event | Red error in modal, "Retry" button |
| QR expired 3x | SSE `error` | "QR expired, retry?" |
| Pod restart fails | Log warning, still return `done` | Show success + warning toast |
| Agent stopped during QR | Close SSE | "Agent stopped" error |
| iLink session expired (errcode -14) | SSE `error` | "Session expired, retry" |

## Implementation Order

1. Backend: `weixin.py` — QR login orchestration module
2. Backend: `config_manager.py` — `read_env_raw()`, `remove_env_keys()`
3. Backend: `main.py` — 3 new API endpoints
4. Frontend: `WeChatQRModal.tsx` — QR modal with SSE
5. Frontend: `WeChatCard.tsx` — Status card
6. Frontend: `AgentDetailPage.tsx` — Integrate card + modal
7. Frontend: `admin-api.ts` — API client functions
8. Test & deploy
