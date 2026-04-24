# Admin WeChat (Weixin) Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add WeChat QR login, status monitoring, and unbind capabilities to the Hermes Admin Panel via SSE-based QR flow.

**Architecture:** Admin backend calls iLink Bot API directly to perform QR login, streams status via SSE to the browser. Credentials are written to the agent's `.env` and `config.yaml`, then the Pod is restarted.

**Tech Stack:** FastAPI + httpx (backend), React + EventSource (frontend), iLink Bot API (WeChat QR)

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `admin/backend/weixin.py` | QR login orchestration, iLink API calls, credential persistence |
| Modify | `admin/backend/config_manager.py` | Add `read_env_raw()`, `remove_env_keys()` |
| Modify | `admin/backend/models.py` | Add `WeixinStatusResponse`, `WeixinActionResponse` |
| Modify | `admin/backend/main.py` | Add 3 new API endpoints |
| Create | `admin/frontend/src/components/WeChatQRModal.tsx` | Full-screen QR modal with SSE state machine |
| Create | `admin/frontend/src/components/WeChatCard.tsx` | Status card for overview tab |
| Modify | `admin/frontend/src/lib/admin-api.ts` | Add 3 API client methods + interfaces |
| Modify | `admin/frontend/src/pages/AgentDetailPage.tsx` | Integrate WeChatCard into Overview tab |

---

### Task 1: Backend — `weixin.py` QR Login Orchestration Module

**Files:**
- Create: `admin/backend/weixin.py`

- [ ] **Step 1: Create `weixin.py` with QR login SSE generator**

```python
"""WeChat (Weixin) QR login orchestration for the Hermes Admin backend.

Calls iLink Bot API to perform QR code login, streaming status updates
via SSE to the browser. On success, writes credentials to the agent's
.env and config.yaml, then triggers a Pod restart.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import AsyncGenerator

import httpx

logger = logging.getLogger("hermes-admin.weixin")

ILINK_BASE_URL = "https://ilinkai.weixin.qq.com"
EP_GET_BOT_QR = "ilink/bot/get_bot_qrcode"
EP_GET_QR_STATUS = "ilink/bot/get_qrcode_status"

QR_POLL_INTERVAL = 1.0       # seconds between status polls
QR_TIMEOUT_SECONDS = 480     # 8 minutes
QR_MAX_REFRESHES = 3         # max QR refreshes on expiry

# In-memory concurrent guard: agent_id -> session_id
_weixin_qr_sessions: dict[int, str] = {}


def _sse(event: str, data: dict) -> str:
    """Format a single SSE message."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def start_qr_session(agent_id: int) -> str | None:
    """Try to start a QR session for an agent. Returns session_id or None if already active."""
    import secrets as _secrets
    if agent_id in _weixin_qr_sessions:
        return None
    session_id = _secrets.token_urlsafe(16)
    _weixin_qr_sessions[agent_id] = session_id
    return session_id


def end_qr_session(agent_id: int) -> None:
    """Clear the QR session for an agent."""
    _weixin_qr_sessions.pop(agent_id, None)


async def stream_weixin_qr(
    agent_id: int,
    agent_dir: str,
) -> AsyncGenerator[str, None]:
    """SSE generator that orchestrates the full QR login flow.

    Yields SSE events: qr_ready, status_update, qr_refresh, done, error, timeout.
    """
    try:
        async with httpx.AsyncClient(timeout=15.0, verify=True) as client:
            # Step 1: Get QR code
            try:
                resp = await client.get(
                    f"{ILINK_BASE_URL}/{EP_GET_BOT_QR}",
                    params={"bot_type": "3"},
                )
                resp.raise_for_status()
                qr_resp = resp.json()
            except Exception as exc:
                logger.error("weixin: failed to fetch QR code: %s", exc)
                yield _sse("error", {"message": f"Failed to fetch QR code: {exc}"})
                return

            qrcode_value = str(qr_resp.get("qrcode") or "")
            qrcode_url = str(qr_resp.get("qrcode_img_content") or "")
            if not qrcode_value:
                yield _sse("error", {"message": "QR response missing qrcode value"})
                return

            yield _sse("qr_ready", {
                "qrcode_url": qrcode_url,
                "session_id": _weixin_qr_sessions.get(agent_id, ""),
            })

            # Step 2: Poll for status
            deadline = time.time() + QR_TIMEOUT_SECONDS
            current_base_url = ILINK_BASE_URL
            refresh_count = 0

            while time.time() < deadline:
                try:
                    status_resp = await client.get(
                        f"{current_base_url}/{EP_GET_QR_STATUS}",
                        params={"qrcode": qrcode_value},
                        timeout=10.0,
                    )
                    status_resp.raise_for_status()
                    data = status_resp.json()
                except (httpx.TimeoutException, asyncio.TimeoutError):
                    await asyncio.sleep(QR_POLL_INTERVAL)
                    continue
                except Exception as exc:
                    logger.warning("weixin: QR poll error: %s", exc)
                    await asyncio.sleep(QR_POLL_INTERVAL)
                    continue

                # Check for iLink error codes
                errcode = data.get("errcode")
                if errcode and errcode != 0:
                    errmsg = data.get("errmsg", "unknown error")
                    if errcode == -14:
                        yield _sse("error", {"message": "iLink session expired, please retry"})
                    else:
                        yield _sse("error", {"message": f"iLink error {errcode}: {errmsg}"})
                    return

                status = str(data.get("status") or "wait")

                if status == "wait":
                    yield _sse("status_update", {"status": "wait", "message": "Waiting for scan..."})

                elif status == "scaned":
                    yield _sse("status_update", {"status": "scaned", "message": "Scanned! Confirm on phone..."})

                elif status == "scaned_but_redirect":
                    redirect_host = str(data.get("redirect_host") or "")
                    if redirect_host:
                        current_base_url = f"https://{redirect_host}"

                elif status == "expired":
                    refresh_count += 1
                    if refresh_count > QR_MAX_REFRESHES:
                        yield _sse("error", {"message": "QR expired too many times, please retry"})
                        return
                    # Refresh QR code
                    try:
                        resp = await client.get(
                            f"{ILINK_BASE_URL}/{EP_GET_BOT_QR}",
                            params={"bot_type": "3"},
                            timeout=10.0,
                        )
                        resp.raise_for_status()
                        qr_resp = resp.json()
                        qrcode_value = str(qr_resp.get("qrcode") or "")
                        qrcode_url = str(qr_resp.get("qrcode_img_content") or "")
                        if not qrcode_value:
                            yield _sse("error", {"message": "QR refresh failed: missing qrcode"})
                            return
                        yield _sse("qr_refresh", {"qrcode_url": qrcode_url})
                    except Exception as exc:
                        yield _sse("error", {"message": f"QR refresh failed: {exc}"})
                        return

                elif status == "confirmed":
                    account_id = str(data.get("ilink_bot_id") or "")
                    token = str(data.get("bot_token") or "")
                    base_url = str(data.get("baseurl") or ILINK_BASE_URL)
                    user_id = str(data.get("ilink_user_id") or "")
                    if not account_id or not token:
                        yield _sse("error", {"message": "QR confirmed but credentials incomplete"})
                        return

                    # Save credentials
                    _save_credentials(
                        agent_dir, agent_id,
                        account_id=account_id,
                        token=token,
                        base_url=base_url,
                        user_id=user_id,
                    )

                    yield _sse("done", {
                        "account_id": account_id,
                        "user_id": user_id,
                        "base_url": base_url,
                    })
                    return

                await asyncio.sleep(QR_POLL_INTERVAL)

            # Timeout
            yield _sse("timeout", {"message": "QR session timed out (8 min)"})

    except Exception as exc:
        logger.exception("weixin: unexpected error in QR stream")
        yield _sse("error", {"message": f"Unexpected error: {exc}"})
    finally:
        end_qr_session(agent_id)


def _save_credentials(
    agent_dir: str,
    agent_id: int,
    *,
    account_id: str,
    token: str,
    base_url: str,
    user_id: str,
) -> None:
    """Save WeChat credentials to .env and account JSON file."""
    import datetime

    # Write to .env (append/update)
    env_path = os.path.join(agent_dir, ".env")
    env_updates = {
        "WEIXIN_ACCOUNT_ID": account_id,
        "WEIXIN_TOKEN": token,
        "WEIXIN_BASE_URL": base_url,
    }
    _update_env_file(env_path, env_updates)

    # Save account JSON
    accounts_dir = os.path.join(agent_dir, "weixin", "accounts")
    os.makedirs(accounts_dir, exist_ok=True)
    account_path = os.path.join(accounts_dir, f"{account_id}.json")
    account_data = {
        "token": token,
        "base_url": base_url,
        "user_id": user_id,
        "saved_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    tmp_path = account_path + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(account_data, f, indent=2)
    os.replace(tmp_path, account_path)


def _update_env_file(env_path: str, updates: dict[str, str]) -> None:
    """Update or append key=value pairs in an .env file."""
    os.makedirs(os.path.dirname(env_path), exist_ok=True)
    lines: list[str] = []
    if os.path.isfile(env_path):
        with open(env_path) as f:
            lines = f.readlines()

    updated_keys: set[str] = set()
    new_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            new_lines.append(line)
            continue
        if "=" in stripped:
            key, _, _ = stripped.partition("=")
            key = key.strip()
            if key in updates:
                new_lines.append(f"{key}={updates[key]}\n")
                updated_keys.add(key)
                continue
        new_lines.append(line)

    for key, value in updates.items():
        if key not in updated_keys:
            new_lines.append(f"{key}={value}\n")

    tmp_path = env_path + ".tmp"
    with open(tmp_path, "w") as f:
        f.writelines(new_lines)
    os.replace(tmp_path, env_path)


def read_weixin_status(agent_dir: str, agent_id: int) -> dict:
    """Read WeChat connection status from .env and account JSON."""
    env_path = os.path.join(agent_dir, ".env")
    env_vars: dict[str, str] = {}
    if os.path.isfile(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                env_vars[key.strip()] = value.strip().strip("\"'")

    account_id = env_vars.get("WEIXIN_ACCOUNT_ID", "")
    token = env_vars.get("WEIXIN_TOKEN", "")
    base_url = env_vars.get("WEIXIN_BASE_URL", ILINK_BASE_URL)
    connected = bool(account_id and token)

    # Read account JSON for bound_at
    bound_at = None
    if account_id:
        account_path = os.path.join(agent_dir, "weixin", "accounts", f"{account_id}.json")
        if os.path.isfile(account_path):
            try:
                with open(account_path) as f:
                    account_data = json.load(f)
                bound_at = account_data.get("saved_at")
            except Exception:
                pass

    # Read config.yaml for platform settings
    dm_policy = "open"
    group_policy = "disabled"
    config_path = os.path.join(agent_dir, "config.yaml")
    if os.path.isfile(config_path):
        try:
            import yaml
            with open(config_path) as f:
                cfg = yaml.safe_load(f) or {}
            weixin_cfg = (cfg.get("platforms") or {}).get("weixin") or {}
            extra = weixin_cfg.get("extra") or {}
            dm_policy = extra.get("dm_policy", dm_policy)
            group_policy = extra.get("group_policy", group_policy)
        except Exception:
            pass

    return {
        "agent_number": agent_id,
        "connected": connected,
        "account_id": account_id,
        "user_id": "",  # Not stored in env
        "base_url": base_url,
        "dm_policy": dm_policy,
        "group_policy": group_policy,
        "bound_at": bound_at,
    }


def unbind_weixin(agent_dir: str, agent_id: int) -> dict:
    """Remove WeChat credentials and disable the platform."""
    # Remove WEIXIN_* keys from .env
    env_path = os.path.join(agent_dir, ".env")
    if os.path.isfile(env_path):
        with open(env_path) as f:
            lines = f.readlines()
        new_lines = [
            line for line in lines
            if not (line.strip() and "=" in line.strip()
                    and line.strip().partition("=")[0].strip().startswith("WEIXIN_"))
        ]
        tmp_path = env_path + ".tmp"
        with open(tmp_path, "w") as f:
            f.writelines(new_lines)
        os.replace(tmp_path, env_path)

    # Disable in config.yaml
    config_path = os.path.join(agent_dir, "config.yaml")
    if os.path.isfile(config_path):
        try:
            import yaml
            with open(config_path) as f:
                cfg = yaml.safe_load(f) or {}
            platforms = cfg.setdefault("platforms", {})
            weixin = platforms.setdefault("weixin", {})
            weixin["enabled"] = False
            # Remove account_id from extra if present
            extra = weixin.setdefault("extra", {})
            extra.pop("account_id", None)
            tmp_path = config_path + ".tmp"
            with open(tmp_path, "w") as f:
                yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)
            os.replace(tmp_path, config_path)
        except Exception as exc:
            logger.warning("weixin: failed to update config.yaml: %s", exc)

    # Delete account files
    import shutil
    accounts_dir = os.path.join(agent_dir, "weixin", "accounts")
    if os.path.isdir(accounts_dir):
        shutil.rmtree(accounts_dir, ignore_errors=True)

    return {
        "agent_number": agent_id,
        "action": "unbind_weixin",
        "success": True,
        "message": "WeChat unbound and agent needs restart",
    }
```

- [ ] **Step 2: Verify imports and syntax**

Run: `cd /mnt/disk01/workspaces/worksummary/hermes-agent/admin/backend && python -c "import weixin; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add admin/backend/weixin.py
git commit -m "feat(admin): add weixin.py QR login orchestration module"
```

---

### Task 2: Backend — Add `read_env_raw()` and `remove_env_keys()` to ConfigManager

**Files:**
- Modify: `admin/backend/config_manager.py`

- [ ] **Step 1: Add `read_env_raw()` method**

Add this method to the `ConfigManager` class after the existing `read_env` method:

```python
    def read_env_raw(self, agent_id: int) -> dict[str, str]:
        """Read .env file without masking secrets. Returns {key: value} dict."""
        env_path = os.path.join(self._agent_dir(agent_id), ".env")
        if not os.path.isfile(env_path):
            return {}
        result: dict[str, str] = {}
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                result[key.strip()] = value.strip().strip("\"'")
        return result
```

- [ ] **Step 2: Add `remove_env_keys()` method**

Add this method after `read_env_raw`:

```python
    def remove_env_keys(self, agent_id: int, key_prefix: str) -> None:
        """Remove all env vars whose key starts with key_prefix."""
        env_path = os.path.join(self._agent_dir(agent_id), ".env")
        if not os.path.isfile(env_path):
            return
        with open(env_path) as f:
            lines = f.readlines()
        new_lines = [
            line for line in lines
            if not (line.strip() and "=" in line.strip()
                    and line.strip().partition("=")[0].strip().startswith(key_prefix))
        ]
        tmp_path = env_path + ".tmp"
        with open(tmp_path, "w") as f:
            f.writelines(new_lines)
        os.replace(tmp_path, env_path)
```

- [ ] **Step 3: Verify syntax**

Run: `cd /mnt/disk01/workspaces/worksummary/hermes-agent/admin/backend && python -c "from config_manager import ConfigManager; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add admin/backend/config_manager.py
git commit -m "feat(admin): add read_env_raw and remove_env_keys to ConfigManager"
```

---

### Task 3: Backend — Add Pydantic Models

**Files:**
- Modify: `admin/backend/models.py`

- [ ] **Step 1: Add `WeixinStatusResponse` and `WeixinActionResponse` models**

Add these at the end of `models.py`, before the `MessageResponse` class (or after it, but before the file ends):

```python
# WeChat (Weixin) integration
class WeixinStatusResponse(BaseModel):
    agent_number: int
    connected: bool
    account_id: str = ""
    user_id: str = ""
    base_url: str = ""
    dm_policy: str = "open"
    group_policy: str = "disabled"
    bound_at: Optional[str] = None


class WeixinActionResponse(BaseModel):
    agent_number: int
    action: str
    success: bool
    message: str = ""
```

- [ ] **Step 2: Verify syntax**

Run: `cd /mnt/disk01/workspaces/worksummary/hermes-agent/admin/backend && python -c "from models import WeixinStatusResponse, WeixinActionResponse; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add admin/backend/models.py
git commit -m "feat(admin): add WeixinStatusResponse and WeixinActionResponse models"
```

---

### Task 4: Backend — Add 3 API Endpoints to `main.py`

**Files:**
- Modify: `admin/backend/main.py`

- [ ] **Step 1: Add imports**

At the top of `main.py`, add `WeixinStatusResponse, WeixinActionResponse` to the import from `models`:

```python
from models import (
    ActionResponse, AgentDetailResponse, AgentListResponse,
    BackupRequest, BackupResponse, ClusterStatusResponse,
    ConfigWriteRequest, CreateAgentRequest, CreateAgentResponse,
    EnvReadResponse, EnvWriteRequest, EventListResponse,
    HealthResponse, MessageResponse, SoulWriteRequest, SoulMarkdown,
    ConfigYaml, TemplateResponse, TemplateTypeResponse,
    TestLLMRequest, TestLLMResponse, UpdateResourceLimitsRequest,
    UpdateAdminKeyRequest, UpdateTemplateRequest, SettingsResponse,
    DefaultResourceLimits,
    WeixinStatusResponse, WeixinActionResponse,
)
```

Also add the weixin module import:

```python
from weixin import stream_weixin_qr, start_qr_session, end_qr_session, read_weixin_status, unbind_weixin
```

- [ ] **Step 2: Add 3 route handlers**

Add these routes after the "Agent Operations" section and before the "Cluster" section in `main.py`:

```python
# ===================================================================
# WeChat (Weixin) Integration
# ===================================================================

@app.post(f"{API_PREFIX}/agents/{{agent_id}}/weixin/qr",
          dependencies=[auth], tags=["agents-weixin"])
async def weixin_qr_login(agent_id: int):
    """Initiate WeChat QR login session. Returns SSE stream."""
    # Validate agent exists
    try:
        await manager.get_agent_detail(agent_id)
    except HTTPException:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Check agent is running
    detail = await manager.get_agent_detail(agent_id)
    if detail.status.value != "running":
        raise HTTPException(status_code=400, detail="Agent must be running to register WeChat")

    # Concurrent guard
    session_id = start_qr_session(agent_id)
    if session_id is None:
        raise HTTPException(status_code=409, detail="QR login already in progress")

    agent_dir = os.path.join(HERMES_DATA_ROOT, f"agent{agent_id}")

    return StreamingResponse(
        stream_weixin_qr(agent_id, agent_dir),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get(f"{API_PREFIX}/agents/{{agent_id}}/weixin/status",
         response_model=WeixinStatusResponse,
         dependencies=[auth], tags=["agents-weixin"])
async def weixin_status(agent_id: int):
    """Get WeChat connection status for an agent."""
    agent_dir = os.path.join(HERMES_DATA_ROOT, f"agent{agent_id}")
    return read_weixin_status(agent_dir, agent_id)


@app.delete(f"{API_PREFIX}/agents/{{agent_id}}/weixin/bind",
            response_model=WeixinActionResponse,
            dependencies=[auth], tags=["agents-weixin"])
async def weixin_unbind(agent_id: int):
    """Unbind WeChat from an agent."""
    # Validate agent exists
    try:
        await manager.get_agent_detail(agent_id)
    except HTTPException:
        raise HTTPException(status_code=404, detail="Agent not found")

    agent_dir = os.path.join(HERMES_DATA_ROOT, f"agent{agent_id}")
    result = unbind_weixin(agent_dir, agent_id)

    # Restart agent to pick up the changes
    try:
        await manager.restart_agent(agent_id)
        result["message"] = "WeChat unbound and agent restarted"
    except Exception:
        result["message"] = "WeChat unbound but agent restart failed"

    return result
```

- [ ] **Step 3: Verify syntax**

Run: `cd /mnt/disk01/workspaces/worksummary/hermes-agent/admin/backend && python -c "from main import app; print('OK')"`
Expected: `OK` (may show startup warnings but no import errors)

- [ ] **Step 4: Commit**

```bash
git add admin/backend/main.py
git commit -m "feat(admin): add WeChat QR login, status, and unbind API endpoints"
```

---

### Task 5: Frontend — Add TypeScript Interfaces and API Methods

**Files:**
- Modify: `admin/frontend/src/lib/admin-api.ts`

- [ ] **Step 1: Add TypeScript interfaces**

After the existing `LogsTokenResponse` interface (around line 321), add:

```typescript
export interface WeixinStatus {
  agent_number: number;
  connected: boolean;
  account_id: string;
  user_id: string;
  base_url: string;
  dm_policy: string;
  group_policy: string;
  bound_at: string | null;
}

export interface WeixinAction {
  agent_number: number;
  action: string;
  success: boolean;
  message: string;
}
```

- [ ] **Step 2: Add API methods**

In the `adminApi` object, add these methods after the `testLlmConnection` method:

```typescript
  // -- WeChat (Weixin) --
  getWeixinStatus(agentId: number): Promise<WeixinStatus> {
    return adminFetch(`/agents/${agentId}/weixin/status`);
  },

  startWeixinQR(agentId: number): string {
    // Returns EventSource URL for SSE — caller creates EventSource
    return `${ADMIN_BASE}/agents/${agentId}/weixin/qr`;
  },

  unbindWeixin(agentId: number): Promise<WeixinAction> {
    return adminFetch(`/agents/${agentId}/weixin/bind`, {
      method: "DELETE",
    });
  },
```

- [ ] **Step 3: Verify build**

Run: `cd /mnt/disk01/workspaces/worksummary/hermes-agent/admin/frontend && npx tsc --noEmit 2>&1 | head -20`
Expected: No errors related to the new interfaces/methods

- [ ] **Step 4: Commit**

```bash
git add admin/frontend/src/lib/admin-api.ts
git commit -m "feat(admin): add WeChat API client methods and TypeScript interfaces"
```

---

### Task 6: Frontend — `WeChatQRModal.tsx`

**Files:**
- Create: `admin/frontend/src/components/WeChatQRModal.tsx`

- [ ] **Step 1: Create the QR modal component**

```tsx
import { useState, useEffect, useRef, useCallback } from "react";
import { adminApi } from "../lib/admin-api";
import { useI18n } from "../hooks/useI18n";
import { showToast } from "../lib/toast";

type QRStatus =
  | "idle"
  | "loading"
  | "waiting"
  | "scanned"
  | "done"
  | "error"
  | "timeout";

interface WeChatQRModalProps {
  agentId: number;
  open: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

export function WeChatQRModal({ agentId, open, onClose, onSuccess }: WeChatQRModalProps) {
  const { t } = useI18n();
  const [status, setStatus] = useState<QRStatus>("idle");
  const [qrUrl, setQrUrl] = useState("");
  const [message, setMessage] = useState("");
  const [elapsed, setElapsed] = useState(0);
  const esRef = useRef<EventSource | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const cleanup = useCallback(() => {
    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
    }
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const startQR = useCallback(() => {
    cleanup();
    setStatus("loading");
    setQrUrl("");
    setMessage("");
    setElapsed(0);

    const url = adminApi.startWeixinQR(agentId);
    const es = new EventSource(url);
    esRef.current = es;

    // Start countdown timer (8 min = 480s)
    timerRef.current = setInterval(() => {
      setElapsed((prev) => {
        if (prev >= 480) {
          cleanup();
          setStatus("timeout");
          setMessage("QR session timed out");
          return prev;
        }
        return prev + 1;
      });
    }, 1000);

    es.addEventListener("qr_ready", (e) => {
      const data = JSON.parse((e as MessageEvent).data);
      setQrUrl(data.qrcode_url);
      setStatus("waiting");
      setMessage("Waiting for scan...");
    });

    es.addEventListener("status_update", (e) => {
      const data = JSON.parse((e as MessageEvent).data);
      if (data.status === "wait") {
        setStatus("waiting");
        setMessage("Waiting for scan...");
      } else if (data.status === "scaned") {
        setStatus("scanned");
        setMessage("Scanned! Confirm on phone...");
      }
    });

    es.addEventListener("qr_refresh", (e) => {
      const data = JSON.parse((e as MessageEvent).data);
      setQrUrl(data.qrcode_url);
      setElapsed(0);
      setStatus("waiting");
      setMessage("QR refreshed, waiting for scan...");
    });

    es.addEventListener("done", () => {
      cleanup();
      setStatus("done");
      setMessage("WeChat connected!");
      showToast(t.weixinConnected || "WeChat connected!");
      setTimeout(() => {
        onSuccess();
        onClose();
      }, 2000);
    });

    es.addEventListener("error", (e) => {
      const data = JSON.parse((e as MessageEvent).data);
      cleanup();
      setStatus("error");
      setMessage(data.message || "Unknown error");
    });

    es.addEventListener("timeout", (e) => {
      const data = JSON.parse((e as MessageEvent).data);
      cleanup();
      setStatus("timeout");
      setMessage(data.message || "Timed out");
    });

    es.onerror = () => {
      // Only set error if we haven't already handled it
      if (esRef.current === es) {
        cleanup();
        if (status === "loading" || status === "waiting") {
          setStatus("error");
          setMessage("Connection lost");
        }
      }
    };
  }, [agentId, cleanup, onClose, onSuccess, status, t]);

  useEffect(() => {
    if (open) {
      startQR();
    } else {
      cleanup();
      setStatus("idle");
    }
    return cleanup;
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!open) return null;

  const remaining = Math.max(0, 480 - elapsed);
  const minutes = Math.floor(remaining / 60);
  const seconds = remaining % 60;
  const progressPct = (remaining / 480) * 100;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" onClick={onClose}>
      {/* Glass backdrop */}
      <div className="absolute inset-0 bg-background/70 backdrop-blur-md" />

      {/* Modal */}
      <div
        className="relative z-10 w-full max-w-md mx-4 rounded-lg border border-border bg-surface p-6 animate-modal-enter"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-lg font-semibold text-text-primary mb-4">
          {t.weixinQRTitle || "Scan QR with WeChat"}
        </h2>

        {/* QR Code area */}
        <div className="flex flex-col items-center gap-4">
          {status === "loading" && (
            <div className="h-48 w-48 flex items-center justify-center rounded-lg bg-background border border-border">
              <div className="h-6 w-6 border-2 border-accent-cyan border-t-transparent rounded-full animate-spin-slow" />
            </div>
          )}

          {(status === "waiting" || status === "scanned") && qrUrl && (
            <div className="rounded-lg bg-white p-2 border border-border">
              <img
                src={qrUrl}
                alt="WeChat QR Code"
                className="h-48 w-48"
              />
            </div>
          )}

          {(status === "waiting" || status === "scanned") && !qrUrl && (
            <div className="h-48 w-48 flex items-center justify-center rounded-lg bg-background border border-border">
              <span className="text-text-secondary text-sm">Loading QR...</span>
            </div>
          )}

          {status === "done" && (
            <div className="h-48 w-48 flex items-center justify-center rounded-lg bg-success/10 border border-success/30">
              <svg className="h-16 w-16 text-success" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
              </svg>
            </div>
          )}

          {(status === "error" || status === "timeout") && (
            <div className="h-48 w-48 flex items-center justify-center rounded-lg bg-accent-pink/10 border border-accent-pink/30">
              <svg className="h-16 w-16 text-accent-pink" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </div>
          )}

          {/* Status message */}
          <p className={`text-sm text-center ${
            status === "scanned" ? "text-accent-cyan" :
            status === "done" ? "text-success" :
            status === "error" || status === "timeout" ? "text-accent-pink" :
            "text-text-secondary"
          }`}>
            {message}
          </p>

          {/* Progress bar (only during active QR) */}
          {(status === "waiting" || status === "scanned") && (
            <div className="w-full">
              <div className="h-1.5 rounded-full bg-bar-track overflow-hidden">
                <div
                  className="h-full rounded-full bg-accent-cyan transition-all duration-1000"
                  style={{ width: `${progressPct}%` }}
                />
              </div>
              <div className="flex justify-between mt-1 text-xs text-text-secondary">
                <span>{status === "scanned" ? (t.weixinScanned || "Scanned") : (t.weixinWaiting || "Waiting...")}</span>
                <span className="font-[family-name:var(--font-mono)]">
                  {String(minutes).padStart(2, "0")}:{String(seconds).padStart(2, "0")}
                </span>
              </div>
            </div>
          )}
        </div>

        {/* Action buttons */}
        <div className="flex justify-center gap-3 mt-6">
          {(status === "error" || status === "timeout") && (
            <button
              onClick={startQR}
              className="h-9 px-4 text-sm rounded-lg bg-accent-cyan text-background hover:shadow-[0_0_15px_rgba(5,217,232,0.3)] transition-shadow"
            >
              {t.retry}
            </button>
          )}
          <button
            onClick={onClose}
            className="h-9 px-4 text-sm border border-border text-text-secondary hover:text-text-primary rounded-lg transition-colors"
          >
            {status === "done" ? (t.close || "Close") : t.cancel}
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify build**

Run: `cd /mnt/disk01/workspaces/worksummary/hermes-agent/admin/frontend && npx tsc --noEmit 2>&1 | head -20`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add admin/frontend/src/components/WeChatQRModal.tsx
git commit -m "feat(admin): add WeChatQRModal component with SSE state machine"
```

---

### Task 7: Frontend — `WeChatCard.tsx` Status Card

**Files:**
- Create: `admin/frontend/src/components/WeChatCard.tsx`

- [ ] **Step 1: Create the status card component**

```tsx
import { useState, useEffect, useCallback } from "react";
import type { WeixinStatus } from "../lib/admin-api";
import { adminApi } from "../lib/admin-api";
import { useI18n } from "../hooks/useI18n";
import { ConfirmDialog } from "./ConfirmDialog";
import { showToast } from "../lib/toast";
import { getApiError } from "../lib/utils";

interface WeChatCardProps {
  agentId: number;
  agentRunning: boolean;
  onRegister: () => void;
  onRefresh: () => void;
}

export function WeChatCard({ agentId, agentRunning, onRegister, onRefresh }: WeChatCardProps) {
  const { t } = useI18n();
  const [status, setStatus] = useState<WeixinStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [unbinding, setUnbinding] = useState(false);
  const [showUnbindDialog, setShowUnbindDialog] = useState(false);

  const loadStatus = useCallback(async () => {
    try {
      const res = await adminApi.getWeixinStatus(agentId);
      setStatus(res);
    } catch {
      // Silently fail — WeChat status is non-critical
    } finally {
      setLoading(false);
    }
  }, [agentId]);

  useEffect(() => {
    loadStatus();
  }, [loadStatus]);

  async function handleUnbind() {
    setShowUnbindDialog(false);
    setUnbinding(true);
    try {
      await adminApi.unbindWeixin(agentId);
      showToast(t.weixinUnbound || "WeChat unbound");
      await loadStatus();
      onRefresh();
    } catch (err) {
      showToast(getApiError(err, t.errorGeneric), "error");
    } finally {
      setUnbinding(false);
    }
  }

  if (loading || !status) {
    return (
      <div className="rounded-lg border border-border bg-surface p-4">
        <h3 className="text-sm font-medium text-text-primary mb-2">
          {t.weixinConnection || "WeChat Connection"}
        </h3>
        <div className="h-4 w-24 bg-bar-track rounded animate-pulse" />
      </div>
    );
  }

  const connected = status.connected;

  return (
    <div className="rounded-lg border border-border bg-surface p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-medium text-text-primary">
          {t.weixinConnection || "WeChat Connection"}
        </h3>
        <span className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded ${
          connected
            ? "bg-success/10 text-success"
            : "bg-text-secondary/10 text-text-secondary"
        }`}>
          <span className={`inline-block h-1.5 w-1.5 rounded-full ${connected ? "bg-success" : "bg-text-secondary"}`} />
          {connected ? (t.statusRunning || "Connected") : (t.weixinNotConnected || "Not Connected")}
        </span>
      </div>

      {connected ? (
        <div className="space-y-2">
          <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
            <div>
              <span className="text-text-secondary">{t.weixinAccount || "Account"}:</span>{" "}
              <span className="font-[family-name:var(--font-mono)] text-text-primary">
                {status.account_id.length > 12
                  ? status.account_id.slice(0, 8) + "..." + status.account_id.slice(-4)
                  : status.account_id}
              </span>
            </div>
            <div>
              <span className="text-text-secondary">{t.weixinBoundAt || "Bound"}:</span>{" "}
              <span className="text-text-primary">
                {status.bound_at ? new Date(status.bound_at).toLocaleString() : "-"}
              </span>
            </div>
            <div>
              <span className="text-text-secondary">DM:</span>{" "}
              <span className="text-text-primary">{status.dm_policy}</span>
            </div>
            <div>
              <span className="text-text-secondary">{t.weixinGroups || "Groups"}:</span>{" "}
              <span className="text-text-primary">{status.group_policy}</span>
            </div>
          </div>
          <div className="flex gap-2 pt-1">
            <button
              onClick={onRegister}
              disabled={!agentRunning}
              className="h-8 px-3 text-xs border border-accent-cyan text-accent-cyan hover:bg-accent-cyan/10 rounded transition-colors disabled:opacity-50"
            >
              {t.weixinReregister || "Re-register"}
            </button>
            <button
              onClick={() => setShowUnbindDialog(true)}
              disabled={unbinding}
              className="h-8 px-3 text-xs border border-accent-pink text-accent-pink hover:bg-accent-pink/10 rounded transition-colors disabled:opacity-50"
            >
              {t.weixinUnbind || "Unbind"}
            </button>
          </div>
        </div>
      ) : (
        <div className="flex flex-col items-center gap-3 py-2">
          <p className="text-xs text-text-secondary">
            {t.weixinNotConnectedDesc || "Not connected to WeChat"}
          </p>
          <button
            onClick={onRegister}
            disabled={!agentRunning}
            className="h-9 px-4 text-sm rounded-lg bg-accent-cyan text-background hover:shadow-[0_0_15px_rgba(5,217,232,0.3)] transition-shadow disabled:opacity-50"
          >
            {t.weixinRegister || "Register WeChat"}
          </button>
        </div>
      )}

      <ConfirmDialog
        open={showUnbindDialog}
        title={t.weixinUnbind || "Unbind WeChat"}
        message={t.weixinUnbindConfirm || "Are you sure you want to unbind WeChat? The agent will restart."}
        confirmLabel={t.weixinUnbind || "Unbind"}
        cancelLabel={t.cancel}
        variant="destructive"
        loading={unbinding}
        onConfirm={handleUnbind}
        onCancel={() => setShowUnbindDialog(false)}
      />
    </div>
  );
}
```

- [ ] **Step 2: Verify build**

Run: `cd /mnt/disk01/workspaces/worksummary/hermes-agent/admin/frontend && npx tsc --noEmit 2>&1 | head -20`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add admin/frontend/src/components/WeChatCard.tsx
git commit -m "feat(admin): add WeChatCard status card component"
```

---

### Task 8: Frontend — Integrate into AgentDetailPage

**Files:**
- Modify: `admin/frontend/src/pages/AgentDetailPage.tsx`

- [ ] **Step 1: Add imports**

At the top of `AgentDetailPage.tsx`, add these imports:

```typescript
import { WeChatCard } from "../components/WeChatCard";
import { WeChatQRModal } from "../components/WeChatQRModal";
```

- [ ] **Step 2: Add QR modal state to main component**

Inside `AgentDetailPage`, after the `confirmDialog` state declaration (around line 85), add:

```typescript
  const [weixinQROpen, setWeixinQROpen] = useState(false);
```

- [ ] **Step 3: Add WeChatQRModal to the render**

Inside the main `return` of `AgentDetailPage`, just before the closing `</div>` (before the `<ConfirmDialog>`), add:

```tsx
      {/* WeChat QR Modal */}
      <WeChatQRModal
        agentId={agentId}
        open={weixinQROpen}
        onClose={() => setWeixinQROpen(false)}
        onSuccess={loadAgent}
      />
```

- [ ] **Step 4: Add WeChatCard to OverviewTab**

In the `OverviewTab` function component, add the `WeChatCard` between the "Resource usage" section and the "Pod info" section. Also add the `onRegister` and `agentId` props. The `OverviewTab` signature needs updating:

Change the OverviewTab component signature from:
```typescript
function OverviewTab({ agent }: { agent: AgentDetail }) {
```
to:
```typescript
function OverviewTab({ agent, onRegisterWeChat }: { agent: AgentDetail; onRegisterWeChat: () => void }) {
```

And add the WeChatCard after the Resource usage `</div>` and before the Pod info `{agent.pods.length > 0 && (`:

```tsx
      {/* WeChat Connection */}
      <WeChatCard
        agentId={agent.id}
        agentRunning={agent.status === "running"}
        onRegister={onRegisterWeChat}
        onRefresh={() => {}} // Will reload via parent
      />
```

- [ ] **Step 5: Update OverviewTab call site**

Change the call in the main render from:
```tsx
<OverviewTab agent={agent} />
```
to:
```tsx
<OverviewTab agent={agent} onRegisterWeChat={() => setWeixinQROpen(true)} />
```

- [ ] **Step 6: Verify build**

Run: `cd /mnt/disk01/workspaces/worksummary/hermes-agent/admin/frontend && npx vite build 2>&1 | tail -5`
Expected: Build succeeds

- [ ] **Step 7: Commit**

```bash
git add admin/frontend/src/pages/AgentDetailPage.tsx
git commit -m "feat(admin): integrate WeChatCard and WeChatQRModal into AgentDetailPage"
```

---

### Task 9: Build, Verify, and Final Commit

**Files:**
- All modified/created files

- [ ] **Step 1: Run frontend build**

Run: `cd /mnt/disk01/workspaces/worksummary/hermes-agent/admin/frontend && npx vite build`
Expected: Build succeeds with JS < 350kB, CSS < 50kB

- [ ] **Step 2: Run backend syntax check**

Run: `cd /mnt/disk01/workspaces/worksummary/hermes-agent/admin/backend && python -c "from main import app; from weixin import stream_weixin_qr; print('Backend OK')"`
Expected: `Backend OK`

- [ ] **Step 3: Copy frontend build to backend static**

Run: `cp -r /mnt/disk01/workspaces/worksummary/hermes-agent/admin/frontend/dist/* /mnt/disk01/workspaces/worksummary/hermes-agent/admin/backend/static/`

- [ ] **Step 4: Final commit if any unstaged changes**

```bash
git add admin/backend/static/
git commit -m "chore(admin): update frontend build with WeChat integration"
```

---

## Self-Review Checklist

- [ ] Spec coverage: All 3 API endpoints implemented (Task 4), QR modal with SSE (Task 6), status card (Task 7), integration (Task 8)
- [ ] No placeholders: Every step has complete code
- [ ] Type consistency: `WeixinStatus` interface matches `WeixinStatusResponse` model fields
- [ ] SSE flow: qr_ready → status_update → qr_refresh → done/error/timeout — all handled
- [ ] Concurrent guard: `_weixin_qr_sessions` dict in weixin.py prevents duplicate sessions
- [ ] Security: TOKEN always masked, admin key required, HTTPS for iLink
