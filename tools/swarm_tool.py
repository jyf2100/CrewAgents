"""
swarm_delegate tool — delegates a task to the best-suited swarm agent.

Uses the three-thread architecture from delegate_tool.py:
  - Tool executor thread (sync, blocks on result)
  - Inner worker thread (runs Redis operations)
  - Heartbeat daemon thread (keeps agent alive)
"""
from __future__ import annotations

import json
import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

import redis as _redis

logger = logging.getLogger(__name__)

_SWARM_TIMEOUT = 120
_HEARTBEAT_INTERVAL = 30
_HEARTBEAT_TTL = 60

# Module-level reference set by _init_swarm_client during agent startup.
# Protected by _swarm_client_lock for thread safety.
_swarm_client: Any = None
_swarm_client_lock = threading.Lock()


def _init_swarm_client(client: Any) -> None:
    global _swarm_client
    with _swarm_client_lock:
        _swarm_client = client


def check_swarm_requirements() -> bool:
    with _swarm_client_lock:
        client = _swarm_client
    if client is None:
        return False
    from swarm.resilient_client import SwarmMode
    return client.mode == SwarmMode.SWARM


def _heartbeat_loop(stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        with _swarm_client_lock:
            client = _swarm_client
        if client is not None:
            try:
                client.heartbeat()
            except Exception as exc:
                logger.debug("swarm heartbeat error: %s", exc)
        stop_event.wait(_HEARTBEAT_INTERVAL)


def _swarm_delegate_worker(
    goal: str, capability: str, input_data: str, target_agent_id: int | None,
    timeout: int = _SWARM_TIMEOUT,
) -> str:
    """Runs in inner worker thread. Returns JSON result string."""
    if target_agent_id is None or target_agent_id == 0:
        return json.dumps({"status": "error", "error": "auto-routing not yet implemented; specify target_agent_id"})

    with _swarm_client_lock:
        client = _swarm_client
    if client is None:
        return json.dumps({"status": "error", "error": "swarm not initialized"})

    task_id = client.submit_task(
        target_agent_id=target_agent_id,
        task_type=capability,
        goal=goal,
        input_data=input_data,
    )
    if task_id is None:
        return json.dumps(
            {"status": "error", "error": "swarm unavailable (standalone mode)"}
        )

    result = client.wait_for_result(task_id, timeout=timeout)
    if result is None:
        return json.dumps(
            {
                "status": "error",
                "error": f"task {task_id} timed out after {timeout}s",
            }
        )

    return json.dumps({"status": "ok", "task_id": task_id, "result": result})


def handle_swarm_delegate(
    goal: str,
    capability: str,
    input_data: str = "",
    target_agent_id: int | None = None,
    timeout: int = _SWARM_TIMEOUT,
) -> str:
    """Tool handler registered in the tool registry."""
    stop_heartbeat = threading.Event()
    heartbeat_thread = threading.Thread(
        target=_heartbeat_loop, args=(stop_heartbeat,), daemon=True
    )
    heartbeat_thread.start()

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future: Future[str] = executor.submit(
                _swarm_delegate_worker, goal, capability, input_data, target_agent_id, timeout
            )
            return future.result(timeout=timeout + 10)
    except (
        _redis.ConnectionError,
        _redis.TimeoutError,
        TimeoutError,
        RuntimeError,
    ) as exc:
        return json.dumps({"status": "error", "error": str(exc)})
    finally:
        stop_heartbeat.set()


SCHEMA = {
    "type": "function",
    "function": {
        "name": "swarm_delegate",
        "description": "Delegate task to the best-suited swarm agent. Requires swarm mode enabled and Redis reachable.",
        "parameters": {
            "type": "object",
            "properties": {
                "goal": {
                    "type": "string",
                    "description": "Task description",
                },
                "capability": {
                    "type": "string",
                    "description": "Required capability, e.g. code-review, data-analysis, translation",
                },
                "input_data": {
                    "type": "string",
                    "description": "Input data (optional)",
                    "default": "",
                },
                "target_agent_id": {
                    "type": "integer",
                    "description": "Target Agent ID (optional, auto-route if not specified)",
                    "default": None,
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds",
                    "default": 120,
                },
            },
            "required": ["goal", "capability"],
        },
    },
}
