"""Web terminal — interactive shell into agent pods via WebSocket + K8s exec."""
from __future__ import annotations

import asyncio
import json
import logging
import secrets as _secrets
import struct
import threading
import time
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, WebSocket, WebSocketDisconnect

logger = logging.getLogger("hermes-admin.terminal")

router = APIRouter()

# ---------------------------------------------------------------------------
# Terminal token management
# ---------------------------------------------------------------------------
_terminal_tokens: dict[str, tuple[int, float]] = {}
TERMINAL_TOKEN_TTL = 60
TERMINAL_SESSION_TIMEOUT = 600
_terminal_semaphore = asyncio.Semaphore(5)


def _cleanup_expired_tokens():
    now = time.time()
    expired = [k for k, (_, exp) in _terminal_tokens.items() if now > exp]
    for k in expired:
        _terminal_tokens.pop(k, None)


@router.on_event("startup")
async def _start_token_sweep():
    async def _sweep():
        while True:
            await asyncio.sleep(60)
            _cleanup_expired_tokens()
    asyncio.create_task(_sweep())


def _verify_terminal_token(agent_id: int, token: str) -> bool:
    entry = _terminal_tokens.pop(token, None)
    if entry is None:
        return False
    aid, expires_at = entry
    if aid != agent_id or time.time() > expires_at:
        return False
    return True


# ---------------------------------------------------------------------------
# Auth — dual-mode (admin key + user token)
# ---------------------------------------------------------------------------
try:
    from auth import auth as _auth
    auth = _auth
except ImportError:
    async def _verify_admin_key(
        x_admin_key: str = Header(..., alias="X-Admin-Key"),
        request: Request = None,
    ):
        import hmac
        admin_key = getattr(request.app.state, "admin_key", "")
        if not admin_key:
            return True
        if not hmac.compare_digest(x_admin_key, admin_key):
            raise HTTPException(status_code=401, detail="Invalid admin key")
        return True
    auth = Depends(_verify_admin_key)


# ---------------------------------------------------------------------------
# Token endpoint
# ---------------------------------------------------------------------------
@router.get("/agents/{agent_id}/terminal/token", dependencies=[auth])
async def get_terminal_token(agent_id: int, request: Request):
    """Mint a one-time token for WebSocket terminal auth."""
    # Resolve effective agent_id (user-mode safe)
    override = getattr(request.state, 'agent_id', None)
    effective_id = override if override is not None else agent_id
    _cleanup_expired_tokens()
    token = _secrets.token_urlsafe(32)
    expires_at = time.time() + TERMINAL_TOKEN_TTL
    _terminal_tokens[token] = (effective_id, expires_at)
    return {"token": token, "expires_in": TERMINAL_TOKEN_TTL}


# ---------------------------------------------------------------------------
# K8s exec channel constants
# ---------------------------------------------------------------------------
STDIN_CHANNEL = 0
STDOUT_CHANNEL = 1
STDERR_CHANNEL = 2
ERROR_CHANNEL = 3
RESIZE_CHANNEL = 4


def _encode_resize(rows: int, cols: int) -> bytes:
    return struct.pack(">HH", rows, cols)


# ---------------------------------------------------------------------------
# WebSocket terminal endpoint
# ---------------------------------------------------------------------------
@router.websocket("/agents/{agent_id}/terminal/ws")
async def terminal_ws(websocket: WebSocket, agent_id: int, token: str = Query(...)):
    """Interactive terminal session into agent pod."""
    await websocket.accept()

    if not _verify_terminal_token(agent_id, token):
        await websocket.send_json({"type": "error", "message": "Invalid or expired token"})
        await websocket.close(code=4001, reason="Auth failed")
        return

    # Atomic semaphore acquisition with timeout
    try:
        await asyncio.wait_for(_terminal_semaphore.acquire(), timeout=5.0)
    except asyncio.TimeoutError:
        await websocket.send_json({"type": "error", "message": "Too many terminal sessions"})
        await websocket.close(code=4003, reason="Too many sessions")
        return

    try:
        await _run_terminal_session(websocket, agent_id)
    finally:
        _terminal_semaphore.release()


async def _run_terminal_session(websocket: WebSocket, agent_id: int):
    """Bridge WebSocket <-> K8s exec stream."""
    from main import k8s

    deployment_name = f"hermes-gateway-{agent_id}"

    # Find running pod (only Running phase, not Pending)
    pods = await k8s.get_pods_for_deployment(deployment_name)
    pod_name = None
    for pod in pods:
        if pod.status.phase == "Running":
            pod_name = pod.metadata.name
            break

    if not pod_name:
        await websocket.send_json({"type": "error", "message": "Agent is not running"})
        await websocket.close(code=4004, reason="No running pod")
        return

    # Create K8s exec stream
    try:
        k8s_ws = await k8s.exec_pod(pod_name)
    except Exception as e:
        logger.error("Failed to exec into pod %s: %s", pod_name, e)
        await websocket.send_json({"type": "error", "message": "Failed to open terminal session"})
        await websocket.close(code=4005, reason="Exec failed")
        return

    queue: asyncio.Queue[bytes | None] = asyncio.Queue()
    cancel = threading.Event()

    def _reader():
        """Read from K8s exec stream in a background thread."""
        try:
            while not cancel.is_set():
                try:
                    if k8s_ws.peek_channel(STDOUT_CHANNEL, timeout=0.1):
                        data = k8s_ws.read_channel(STDOUT_CHANNEL, timeout=0.1)
                        if data:
                            loop.call_soon_threadsafe(queue.put_nowait,
                                                      data if isinstance(data, bytes) else data.encode("utf-8", errors="replace"))
                    if k8s_ws.peek_channel(STDERR_CHANNEL, timeout=0.1):
                        data = k8s_ws.read_channel(STDERR_CHANNEL, timeout=0.1)
                        if data:
                            loop.call_soon_threadsafe(queue.put_nowait,
                                                      data if isinstance(data, bytes) else data.encode("utf-8", errors="replace"))
                    if k8s_ws.peek_channel(ERROR_CHANNEL, timeout=0.1):
                        data = k8s_ws.read_channel(ERROR_CHANNEL, timeout=0.1)
                        if data:
                            err_msg = data if isinstance(data, bytes) else data.encode("utf-8", errors="replace")
                            loop.call_soon_threadsafe(queue.put_nowait, b'\x1b[31m' + err_msg + b'\x1b[0m')
                except Exception:
                    break
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    loop = asyncio.get_event_loop()
    reader_thread = threading.Thread(target=_reader, daemon=True)
    reader_thread.start()

    try:
        async def _send_to_browser():
            while True:
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                if data is None:
                    return
                try:
                    await websocket.send_bytes(data)
                except Exception:
                    return

        async def _recv_from_browser():
            while True:
                try:
                    msg = await websocket.receive()
                except WebSocketDisconnect:
                    return
                if "bytes" in msg and msg["bytes"]:
                    k8s_ws.write_channel(STDIN_CHANNEL, msg["bytes"])
                elif "text" in msg and msg["text"]:
                    text = msg["text"]
                    if text.startswith("{"):
                        try:
                            obj = json.loads(text)
                            if obj.get("type") == "resize":
                                rows = max(1, min(int(obj.get("rows", 24)), 500))
                                cols = max(1, min(int(obj.get("cols", 80)), 1000))
                                k8s_ws.write_channel(RESIZE_CHANNEL, _encode_resize(rows, cols))
                                continue
                        except (json.JSONDecodeError, ValueError):
                            pass
                    k8s_ws.write_channel(STDIN_CHANNEL, text.encode("utf-8"))
                elif msg.get("type") == "websocket.disconnect":
                    return

        send_task = asyncio.create_task(_send_to_browser())
        recv_task = asyncio.create_task(_recv_from_browser())

        done, pending = await asyncio.wait(
            [send_task, recv_task],
            timeout=TERMINAL_SESSION_TIMEOUT,
            return_when=asyncio.FIRST_COMPLETED,
        )
        for t in pending:
            t.cancel()
    except Exception as e:
        logger.error("Terminal session error for agent %d: %s", agent_id, e)
    finally:
        cancel.set()
        try:
            k8s_ws.close()
        except Exception:
            pass
        try:
            await websocket.close(code=1000, reason="Session ended")
        except Exception:
            pass
        logger.info("Terminal session ended for agent %d (pod %s)", agent_id, pod_name)
