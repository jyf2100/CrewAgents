# Swarm Phase 2: Core Communication Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the full "send task → consume & execute → return result → real-time display" loop, enabling multi-agent collaboration on single-step tasks.

**Architecture:** Agent-side daemon thread (`swarm/consumer.py`) consumes tasks from Redis Streams via XREADGROUP, executes them with a single LLM call, writes results back to the sender's result stream, and publishes advisory events. The SSE endpoint bridges Redis Pub/Sub advisory channels to browser EventSource clients. Frontend TaskMonitorPage subscribes via SSE for real-time task status updates.

**Tech Stack:** Python 3.11, Redis Streams + Pub/Sub, FastAPI SSE, React 19, Zustand, TypeScript

**Spec:** `docs/superpowers/specs/2026-04-25-swarm-collaboration-design.md` (Section 3.2, 3.5, 5.1.2, 5.3)

**Branch:** Create `feature/swarm-phase2` from `main`

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `swarm/consumer.py` | Stream consumer daemon thread |
| Modify | `swarm/client.py` | Add `publish_result()` method |
| Modify | `swarm/resilient_client.py` | Add `start_consumer()` / `stop_consumer()` |
| Modify | `run_agent.py:1753-1801` | Wire consumer into `_init_swarm()` |
| Modify | `admin/backend/swarm_models.py` | Add `SwarmTaskResponse` model |
| Modify | `admin/backend/swarm_routes.py:156-186` | Replace SSE heartbeat loop with Pub/Sub bridge |
| Create | `admin/frontend/src/stores/swarmTasks.ts` | Zustand store for tasks |
| Modify | `admin/frontend/src/stores/swarmEvents.ts` | Wire swarmTasks events |
| Create | `admin/frontend/src/pages/swarm/TaskMonitorPage.tsx` | Task list with filters |
| Create | `admin/frontend/src/pages/swarm/TaskDetailPage.tsx` | Task detail view |
| Modify | `admin/frontend/src/App.tsx` | Add task routes |
| Modify | `admin/frontend/src/components/AdminLayout.tsx` | Add nav item |
| Modify | `admin/frontend/src/i18n/en.ts` | Add task-related keys |
| Modify | `admin/frontend/src/i18n/zh.ts` | Add task-related keys |
| Create | `tests/test_swarm/test_consumer.py` | Consumer unit tests |
| Create | `admin/frontend/e2e/task-monitor.spec.ts` | E2E tests for task pages |

---

### Task 1: Create `swarm/consumer.py` — Stream Consumer Thread

**Files:**
- Create: `swarm/consumer.py`
- Test: `tests/test_swarm/test_consumer.py`

This is the core of Phase 2: a daemon thread that consumes tasks from the agent's Redis Stream, executes them via a single LLM call, writes results back, and sends advisory notifications.

- [ ] **Step 1: Write failing tests for SwarmConsumer**

```python
# tests/test_swarm/test_consumer.py
from unittest.mock import MagicMock, patch, call
import threading

from swarm.consumer import SwarmConsumer


def test_consumer_reads_from_stream():
    """Consumer calls XREADGROUP on the correct stream."""
    redis_mock = MagicMock()
    redis_mock.xreadgroup.return_value = []  # no messages
    redis_mock.xpending_range.return_value = []

    consumer = SwarmConsumer(
        agent_id=3,
        redis_client=redis_mock,
        execute_fn=lambda goal, data: "done",
    )
    consumer._poll_once()  # single poll, no loop

    redis_mock.xreadgroup.assert_called_once()
    args = redis_mock.xreadgroup.call_args
    group_name = args[0][0]
    stream_dict = args[0][2]
    assert group_name == "agent.3.worker"
    assert "hermes:stream:agent.3.tasks" in stream_dict


def test_consumer_executes_and_acks():
    """Consumer executes the task function and acks the message."""
    redis_mock = MagicMock()
    task_fields = {
        "task_id": "t-001",
        "task_type": "code-review",
        "goal": "Review main.py",
        "sender_id": "1",
        "input_data": "",
        "capability": "code-review",
        "timestamp": "1234.5",
        "_msg_id": "1640000000-0",
    }
    redis_mock.xreadgroup.return_value = [
        ("hermes:stream:agent.3.tasks", [("1640000000-0", task_fields)])
    ]
    redis_mock.xpending_range.return_value = []

    execute_fn = MagicMock(return_value="review passed")

    consumer = SwarmConsumer(
        agent_id=3,
        redis_client=redis_mock,
        execute_fn=execute_fn,
    )
    consumer._poll_once()

    execute_fn.assert_called_once_with("Review main.py", "")
    redis_mock.xack.assert_called_once_with(
        "hermes:stream:agent.3.tasks",
        "agent.3.worker",
        "1640000000-0",
    )


def test_consumer_writes_result_to_sender_stream():
    """After execution, consumer writes result to the sender's result stream."""
    redis_mock = MagicMock()
    task_fields = {
        "task_id": "t-002",
        "task_type": "code-review",
        "goal": "Review app.py",
        "sender_id": "1",
        "input_data": "file contents",
        "capability": "code-review",
        "timestamp": "1234.5",
        "_msg_id": "1640000001-0",
    }
    redis_mock.xreadgroup.return_value = [
        ("hermes:stream:agent.3.tasks", [("1640000001-0", task_fields)])
    ]
    redis_mock.xpending_range.return_value = []

    consumer = SwarmConsumer(
        agent_id=3,
        redis_client=redis_mock,
        execute_fn=lambda goal, data: "LGTM",
    )
    consumer._poll_once()

    # Should XADD result to hermes:swarm:result:t-002 (for BLPOP)
    redis_mock.rpush.assert_called_once()
    rpush_args = redis_mock.rpush.call_args[0]
    assert rpush_args[0] == "hermes:swarm:result:t-002"

    # Should publish advisory
    redis_mock.publish.assert_called_once()
    pub_args = redis_mock.publish.call_args[0]
    assert pub_args[0] == "swarm.advisory.result"


def test_consumer_publishes_task_started_advisory():
    """Consumer publishes a task_started advisory when it begins execution."""
    redis_mock = MagicMock()
    task_fields = {
        "task_id": "t-003",
        "task_type": "code-review",
        "goal": "Review",
        "sender_id": "1",
        "input_data": "",
        "capability": "",
        "timestamp": "1234.5",
        "_msg_id": "1640000002-0",
    }
    redis_mock.xreadgroup.return_value = [
        ("hermes:stream:agent.3.tasks", [("1640000002-0", task_fields)])
    ]
    redis_mock.xpending_range.return_value = []

    consumer = SwarmConsumer(
        agent_id=3,
        redis_client=redis_mock,
        execute_fn=lambda g, d: "ok",
    )
    consumer._poll_once()

    # publish called twice: task_started + result
    assert redis_mock.publish.call_count == 2
    first_pub = redis_mock.publish.call_args_list[0]
    assert first_pub[0][0] == "swarm.advisory.task"


def test_consumer_skips_cancelled_task():
    """Consumer checks cancel flag and skips execution if cancelled."""
    redis_mock = MagicMock()
    redis_mock.exists.return_value = 1  # cancel flag set
    task_fields = {
        "task_id": "t-004",
        "task_type": "test",
        "goal": "Run tests",
        "sender_id": "1",
        "input_data": "",
        "capability": "",
        "timestamp": "1234.5",
        "_msg_id": "1640000003-0",
    }
    redis_mock.xreadgroup.return_value = [
        ("hermes:stream:agent.3.tasks", [("1640000003-0", task_fields)])
    ]
    redis_mock.xpending_range.return_value = []

    execute_fn = MagicMock(return_value="should not be called")

    consumer = SwarmConsumer(
        agent_id=3,
        redis_client=redis_mock,
        execute_fn=execute_fn,
    )
    consumer._poll_once()

    execute_fn.assert_not_called()
    redis_mock.xack.assert_called_once()


def test_consumer_graceful_stop():
    """Calling stop() breaks the polling loop."""
    redis_mock = MagicMock()
    redis_mock.xreadgroup.return_value = []
    redis_mock.xpending_range.return_value = []

    consumer = SwarmConsumer(
        agent_id=3,
        redis_client=redis_mock,
        execute_fn=lambda g, d: "ok",
    )
    thread = threading.Thread(target=consumer.run, daemon=True)
    thread.start()
    consumer.stop()
    thread.join(timeout=2)
    assert not thread.is_alive()


def test_consumer_handles_execution_error():
    """Consumer catches execution errors, sends error result, still acks."""
    redis_mock = MagicMock()
    task_fields = {
        "task_id": "t-005",
        "task_type": "test",
        "goal": "Boom",
        "sender_id": "1",
        "input_data": "",
        "capability": "",
        "timestamp": "1234.5",
        "_msg_id": "1640000004-0",
    }
    redis_mock.xreadgroup.return_value = [
        ("hermes:stream:agent.3.tasks", [("1640000004-0", task_fields)])
    ]
    redis_mock.xpending_range.return_value = []

    def boom(goal, data):
        raise RuntimeError("LLM failed")

    consumer = SwarmConsumer(
        agent_id=3,
        redis_client=redis_mock,
        execute_fn=boom,
    )
    consumer._poll_once()

    # Should still ack
    redis_mock.xack.assert_called_once()
    # Should write error result
    rpush_args = redis_mock.rpush.call_args[0][1]
    import json
    result = json.loads(rpush_args)
    assert result["status"] == "failed"
    assert "LLM failed" in result["error"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /mnt/disk01/workspaces/worksummary/hermes-agent && python -m pytest tests/test_swarm/test_consumer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'swarm.consumer'`

- [ ] **Step 3: Implement `swarm/consumer.py`**

```python
# swarm/consumer.py
"""Background thread that consumes tasks from the agent's Redis Stream."""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Callable

logger = logging.getLogger(__name__)

_CONSUMER_BLOCK_MS = 5000


class SwarmConsumer:
    """Reads tasks from the agent's Redis Stream consumer group, executes
    them via ``execute_fn``, writes results back, and publishes advisory events."""

    def __init__(
        self,
        agent_id: int,
        redis_client: Any,
        execute_fn: Callable[[str, str], str],
    ):
        self.agent_id = agent_id
        self._redis = redis_client
        self._execute_fn = execute_fn
        self._stop = threading.Event()
        self._stream = f"hermes:stream:agent.{agent_id}.tasks"
        self._group = f"agent.{agent_id}.worker"

    def run(self) -> None:
        """Main loop — blocks on XREADGROUP until stop() is called."""
        self._ensure_group()
        while not self._stop.is_set():
            self._poll_once()
        logger.info("swarm consumer stopped for agent %d", self.agent_id)

    def stop(self) -> None:
        self._stop.set()

    def _ensure_group(self) -> None:
        try:
            self._redis.xgroup_create(
                self._stream, self._group, id="0", mkstream=True
            )
        except Exception:
            pass  # BUSYGROUP = already exists

    def _poll_once(self) -> None:
        try:
            result = self._redis.xreadgroup(
                self._group,
                "consumer-1",
                {self._stream: ">"},
                count=1,
                block=_CONSUMER_BLOCK_MS,
            )
        except Exception as exc:
            logger.debug("swarm consumer read error: %s", exc)
            return

        if not result:
            return

        for _, messages in result:
            for msg_id, fields in messages:
                self._handle_message(msg_id, fields)

    def _handle_message(self, msg_id: str, fields: dict) -> None:
        task_id = fields.get("task_id", "")
        goal = fields.get("goal", "")
        input_data = fields.get("input_data", "")
        sender_id = fields.get("sender_id", "")

        # Check cancellation
        if self._redis.exists(f"hermes:swarm:cancel:{task_id}"):
            logger.info("swarm: task %s cancelled, skipping", task_id)
            self._redis.xack(self._stream, self._group, msg_id)
            return

        # Publish task_started advisory
        self._redis.publish(
            "swarm.advisory.task",
            json.dumps({
                "event": "task_started",
                "task_id": task_id,
                "agent_id": self.agent_id,
                "task_type": fields.get("task_type", ""),
            }),
        )

        # Execute
        status = "completed"
        output = ""
        error_msg = ""
        start = time.time()
        try:
            output = self._execute_fn(goal, input_data)
        except Exception as exc:
            status = "failed"
            error_msg = str(exc)
            logger.warning("swarm: task %s execution failed: %s", task_id, exc)
        duration_ms = int((time.time() - start) * 1000)

        # Write result via RPUSH (for BLPOP on sender side)
        result_payload = json.dumps({
            "task_id": task_id,
            "agent_id": self.agent_id,
            "status": status,
            "output": output,
            "error": error_msg,
            "duration_ms": duration_ms,
            "timestamp": time.time(),
        })
        result_key = f"hermes:swarm:result:{task_id}"
        self._redis.rpush(result_key, result_payload)
        self._redis.expire(result_key, 300)

        # Publish result advisory
        self._redis.publish(
            "swarm.advisory.result",
            json.dumps({
                "event": "task_completed" if status == "completed" else "task_failed",
                "task_id": task_id,
                "agent_id": self.agent_id,
                "status": status,
                "duration_ms": duration_ms,
            }),
        )

        # Ack
        self._redis.xack(self._stream, self._group, msg_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_swarm/test_consumer.py -v`
Expected: 7 PASSED

- [ ] **Step 5: Update `swarm/__init__.py`**

Add `SwarmConsumer` to the exports:

```python
# In swarm/__init__.py, add to imports:
from .consumer import SwarmConsumer

# Add to __all__:
    "SwarmConsumer",
```

- [ ] **Step 6: Commit**

```bash
git add swarm/consumer.py swarm/__init__.py tests/test_swarm/test_consumer.py
git commit -m "feat(swarm): add StreamConsumer daemon thread for task execution"
```

---

### Task 2: Wire Consumer into `run_agent.py` via `ResilientSwarmClient`

**Files:**
- Modify: `swarm/resilient_client.py`
- Modify: `run_agent.py:1753-1801`

- [ ] **Step 1: Add consumer lifecycle methods to `ResilientSwarmClient`**

In `swarm/resilient_client.py`, add `start_consumer()` and `stop_consumer()` methods. The `start_consumer` method creates a `SwarmConsumer` instance and starts it in a daemon thread. The `stop_consumer` method signals the consumer to stop.

Add these imports at the top:

```python
from .consumer import SwarmConsumer
```

Add to `ResilientSwarmClient.__init__`:

```python
        self._consumer: SwarmConsumer | None = None
        self._consumer_thread: threading.Thread | None = None
        self._execute_fn: Callable[[str, str], str] | None = None
```

Add these methods after `wait_for_result`:

```python
    def start_consumer(self, execute_fn: Callable[[str, str], str]) -> None:
        """Start the background task consumer thread."""
        with self._lock:
            if self._mode == SwarmMode.STANDALONE:
                return
        self._execute_fn = execute_fn
        self._consumer = SwarmConsumer(
            agent_id=self._inner.agent_id,
            redis_client=self._inner._redis,
            execute_fn=execute_fn,
        )
        self._consumer_thread = threading.Thread(
            target=self._consumer.run, daemon=True
        )
        self._consumer_thread.start()

    def stop_consumer(self) -> None:
        """Stop the background task consumer."""
        if self._consumer is not None:
            self._consumer.stop()
        self._consumer = None
        self._consumer_thread = None
```

- [ ] **Step 2: Wire consumer into `_init_swarm()` in `run_agent.py`**

In `run_agent.py`, after the `_init_swarm_client(self._swarm_client)` call (around line 1790), add:

```python
            # Start the swarm task consumer daemon thread
            def _swarm_execute(goal: str, input_data: str) -> str:
                """Execute a swarm task via a single LLM call."""
                try:
                    return self.run_single_turn(goal, context=input_data)
                except Exception as exc:
                    logger.warning("swarm task execution error: %s", exc)
                    raise

            self._swarm_client.start_consumer(_swarm_execute)
```

Note: `run_single_turn` may not exist yet. If it doesn't, the implementer should check for an existing single-turn method on `AIAgent`. If none exists, create a minimal one that sends a single user message to the LLM and returns the text response without entering the full tool loop.

- [ ] **Step 3: Run existing tests**

Run: `python -m pytest tests/test_swarm/test_resilient.py -v`
Expected: 5 PASSED (existing tests should still pass — consumer methods are additive)

- [ ] **Step 4: Commit**

```bash
git add swarm/resilient_client.py run_agent.py
git commit -m "feat(swarm): wire StreamConsumer into agent lifecycle"
```

---

### Task 3: SSE Pub/Sub Bridge — Replace Heartbeat-Only Loop

**Files:**
- Modify: `admin/backend/swarm_routes.py:156-186`
- Test: `admin/frontend/e2e/task-monitor.spec.ts` (partial — SSE events)

Replace the current SSE endpoint (which only sends 30s heartbeats) with a Pub/Sub bridge that subscribes to `swarm.advisory.*` channels and forwards events to SSE clients.

- [ ] **Step 1: Rewrite `sse_stream` endpoint**

Replace the `sse_stream` function in `swarm_routes.py` (lines 156-186) with:

```python
@router.get("/events/stream")
async def sse_stream(request: Request, token: str = Query(...)):
    from fastapi.responses import StreamingResponse

    redis = _get_redis(request)
    if redis is None:
        async def error_gen():
            yield 'data: {"error": "redis unavailable"}\n\n'
        return StreamingResponse(error_gen(), media_type="text/event-stream")

    stored = redis.get(f"hermes:sse:token:{token}")
    if stored is None:
        async def invalid_gen():
            yield 'data: {"error": "invalid token"}\n\n'
        return StreamingResponse(invalid_gen(), media_type="text/event-stream")

    redis.delete(f"hermes:sse:token:{token}")

    pubsub = redis.pubsub()
    pubsub.subscribe(
        "swarm.advisory.task",
        "swarm.advisory.result",
        "swarm.advisory.online",
        "swarm.advisory.offline",
    )

    async def event_generator():
        seq = 0
        try:
            while True:
                if await request.is_disconnected():
                    break
                # Non-blocking check for pub/sub messages
                message = pubsub.get_message(timeout=1.0)
                if message and message["type"] == "message":
                    seq += 1
                    channel = message["channel"]
                    if isinstance(channel, bytes):
                        channel = channel.decode()
                    data = message["data"]
                    if isinstance(data, bytes):
                        data = data.decode()
                    event_type = _advisory_channel_to_event(channel, data)
                    yield f"id: {seq}\nevent: {event_type}\ndata: {data}\n\n"
                else:
                    seq += 1
                    yield f"id: {seq}\nevent: heartbeat\ndata: {{}}\n\n"
                    await asyncio.sleep(5)
        except asyncio.CancelledError:
            pass
        finally:
            pubsub.unsubscribe()
            pubsub.close()

    return StreamingResponse(event_generator(), media_type="text/event-stream")


def _advisory_channel_to_event(channel: str, data: str) -> str:
    """Map Redis Pub/Sub channel + data to SSE event type."""
    try:
        parsed = json.loads(data)
        # Consumer and client publish structured events with an "event" key
        if "event" in parsed:
            return parsed["event"]
    except (json.JSONDecodeError, TypeError):
        pass
    # Fallback: derive from channel name
    mapping = {
        "swarm.advisory.task": "task_created",
        "swarm.advisory.result": "task_completed",
        "swarm.advisory.online": "agent_online",
        "swarm.advisory.offline": "agent_offline",
    }
    return mapping.get(channel, "message")
```

- [ ] **Step 2: Verify existing SSE E2E test still passes**

Run: `cd admin/frontend && npx playwright test swarm --reporter=list`
Expected: Swarm Overview tests PASS (SSE token flow unchanged)

- [ ] **Step 3: Commit**

```bash
git add admin/backend/swarm_routes.py
git commit -m "feat(swarm): bridge Redis Pub/Sub advisory events to SSE stream"
```

---

### Task 4: Backend Task Query API

**Files:**
- Modify: `admin/backend/swarm_models.py`
- Modify: `admin/backend/swarm_routes.py`

Add API endpoints for querying recent tasks. Since tasks are ephemeral (TTL 300s on result keys), we store minimal task metadata in a Redis Sorted Set for the last 5 minutes.

- [ ] **Step 1: Add `SwarmTaskResponse` model to `swarm_models.py`**

Append to `swarm_models.py`:

```python
class SwarmTaskResponse(BaseModel):
    task_id: str
    task_type: str
    goal: str
    status: str  # "completed" | "failed" | "pending" | "running"
    sender_id: int
    assigned_agent_id: int | None = None
    duration_ms: int | None = None
    error: str = ""
    timestamp: float
```

- [ ] **Step 2: Add `GET /swarm/tasks` and `GET /swarm/tasks/{task_id}` routes**

In `swarm_routes.py`, add after the `get_swarm_metrics` endpoint:

```python
@router.get("/tasks", response_model=list[SwarmTaskResponse], dependencies=[_auth])
async def get_swarm_tasks(request: Request):
    redis = _get_redis(request)
    if redis is None:
        return []
    now = time.time()
    cutoff = now - 300  # last 5 minutes
    raw = redis.zrangebyscore("hermes:swarm:tasks", cutoff, now)
    tasks = []
    for entry in raw:
        try:
            tasks.append(SwarmTaskResponse(**json.loads(entry)))
        except (json.JSONDecodeError, ValueError):
            continue
    return list(reversed(tasks))


@router.get("/tasks/{task_id}", response_model=SwarmTaskResponse | None, dependencies=[_auth])
async def get_swarm_task(request: Request, task_id: str):
    redis = _get_redis(request)
    if redis is None:
        return None
    # Try result key first
    raw = redis.get(f"hermes:swarm:result:{task_id}")
    if raw:
        try:
            result = json.loads(raw)
            return SwarmTaskResponse(
                task_id=task_id,
                task_type="",
                goal="",
                status=result.get("status", "unknown"),
                sender_id=0,
                assigned_agent_id=result.get("agent_id"),
                duration_ms=result.get("duration_ms"),
                error=result.get("error", ""),
                timestamp=result.get("timestamp", 0),
            )
        except (json.JSONDecodeError, ValueError):
            pass
    return None
```

- [ ] **Step 3: Update consumer to write task metadata to sorted set**

In `swarm/consumer.py`, inside `_handle_message`, after the RPUSH + EXPIRE block, add:

```python
        # Store task metadata for the admin API (5-min TTL)
        task_meta = json.dumps({
            "task_id": task_id,
            "task_type": fields.get("task_type", ""),
            "goal": goal[:200],  # truncate for storage
            "status": status,
            "sender_id": int(sender_id) if sender_id.isdigit() else 0,
            "assigned_agent_id": self.agent_id,
            "duration_ms": duration_ms,
            "error": error_msg[:500] if error_msg else "",
            "timestamp": time.time(),
        })
        self._redis.zadd("hermes:swarm:tasks", {task_meta: time.time()})
        # Prune entries older than 5 minutes
        self._redis.zremrangebyscore("hermes:swarm:tasks", 0, time.time() - 300)
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_swarm/ -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add admin/backend/swarm_models.py admin/backend/swarm_routes.py swarm/consumer.py
git commit -m "feat(swarm): add task query API with 5-min sorted set storage"
```

---

### Task 5: Frontend — `swarmTasks` Store + Wire Events

**Files:**
- Create: `admin/frontend/src/stores/swarmTasks.ts`
- Modify: `admin/frontend/src/stores/swarmEvents.ts`

- [ ] **Step 1: Create `swarmTasks.ts` Zustand store**

```typescript
// admin/frontend/src/stores/swarmTasks.ts
import { create } from "zustand";
import { adminFetch } from "../lib/admin-api";

export type TaskStatus = "completed" | "failed" | "pending" | "running";

export interface SwarmTask {
  task_id: string;
  task_type: string;
  goal: string;
  status: TaskStatus;
  sender_id: number;
  assigned_agent_id: number | null;
  duration_ms: number | null;
  error: string;
  timestamp: number;
}

interface SwarmTasksState {
  tasks: SwarmTask[];
  loading: boolean;
  error: string | null;
  fetchTasks: () => Promise<void>;
  handleEvent: (type: string, data: unknown) => void;
}

export const useSwarmTasks = create<SwarmTasksState>((set) => ({
  tasks: [],
  loading: false,
  error: null,

  fetchTasks: async () => {
    set({ loading: true, error: null });
    try {
      const tasks = await adminFetch<SwarmTask[]>("/swarm/tasks");
      set({ tasks, loading: false });
    } catch (e: unknown) {
      set({ error: String(e), loading: false });
    }
  },

  handleEvent: (type, data) => {
    const d = data as Record<string, unknown>;
    if (
      type === "task_created" ||
      type === "task_started" ||
      type === "task_completed" ||
      type === "task_failed"
    ) {
      const taskId = d.task_id as string;
      set((state) => {
        const existing = state.tasks.findIndex((t) => t.task_id === taskId);
        if (existing >= 0) {
          const updated = [...state.tasks];
          updated[existing] = {
            ...updated[existing],
            status: (d.status as TaskStatus) ?? type.replace("task_", "") as TaskStatus,
            duration_ms: (d.duration_ms as number) ?? updated[existing].duration_ms,
            assigned_agent_id: (d.agent_id as number) ?? updated[existing].assigned_agent_id,
          };
          return { tasks: updated };
        }
        return {
          tasks: [
            {
              task_id: taskId,
              task_type: (d.task_type as string) ?? "",
              goal: "",
              status: type === "task_created" ? "pending" : (d.status as TaskStatus) ?? "running",
              sender_id: 0,
              assigned_agent_id: (d.agent_id as number) ?? null,
              duration_ms: null,
              error: "",
              timestamp: Date.now() / 1000,
            },
            ...state.tasks,
          ],
        };
      });
    }
  },
}));
```

- [ ] **Step 2: Wire `swarmTasks.handleEvent` into `swarmEvents.ts`**

In `swarmEvents.ts`, add import:

```typescript
import { useSwarmTasks } from "./swarmTasks";
```

In the `onEvent` callback inside `connect`, add after the existing `useSwarmRegistry` call:

```typescript
        useSwarmTasks.getState().handleEvent(type, data);
```

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd admin/frontend && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add admin/frontend/src/stores/swarmTasks.ts admin/frontend/src/stores/swarmEvents.ts
git commit -m "feat(swarm): add swarmTasks Zustand store with SSE event handling"
```

---

### Task 6: Frontend — TaskMonitorPage

**Files:**
- Create: `admin/frontend/src/pages/swarm/TaskMonitorPage.tsx`
- Modify: `admin/frontend/src/i18n/en.ts`
- Modify: `admin/frontend/src/i18n/zh.ts`
- Modify: `admin/frontend/src/App.tsx`
- Modify: `admin/frontend/src/components/AdminLayout.tsx`

- [ ] **Step 1: Add i18n keys**

In `en.ts`, add after the existing swarm keys:

```typescript
  // Task Monitor
  navTasks: "Tasks",
  taskMonitor: "Task Monitor",
  taskId: "Task ID",
  taskGoal: "Goal",
  taskStatus: "Status",
  taskAgent: "Agent",
  taskDuration: "Duration",
  taskTime: "Time",
  taskType: "Type",
  taskNoTasks: "No recent tasks",
  taskFilterAll: "All",
  taskFilterCompleted: "Completed",
  taskFilterFailed: "Failed",
  taskFilterRunning: "Running",
  taskFilterPending: "Pending",
```

In `zh.ts`, add matching keys:

```typescript
  // Task Monitor
  navTasks: "任务",
  taskMonitor: "任务监控",
  taskId: "任务 ID",
  taskGoal: "目标",
  taskStatus: "状态",
  taskAgent: "Agent",
  taskDuration: "耗时",
  taskTime: "时间",
  taskType: "类型",
  taskNoTasks: "暂无任务",
  taskFilterAll: "全部",
  taskFilterCompleted: "已完成",
  taskFilterFailed: "已失败",
  taskFilterRunning: "执行中",
  taskFilterPending: "等待中",
```

- [ ] **Step 2: Create TaskMonitorPage**

```tsx
// admin/frontend/src/pages/swarm/TaskMonitorPage.tsx
import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import type { SwarmTask, TaskStatus } from "../../stores/swarmTasks";
import { useSwarmTasks } from "../../stores/swarmTasks";
import { useSwarmRegistry } from "../../stores/swarmRegistry";
import { useSwarmEvents } from "../../stores/swarmEvents";
import { useI18n } from "../../hooks/useI18n";
import { LoadingSpinner } from "../../components/LoadingSpinner";

const STATUS_BADGE: Record<string, string> = {
  completed: "bg-success/15 text-success border-success/30",
  failed: "bg-accent-pink/15 text-accent-pink border-accent-pink/30",
  running: "bg-accent-cyan/15 text-accent-cyan border-accent-cyan/30",
  pending: "bg-warning/15 text-warning border-warning/30",
};

function statusLabel(status: string, t: Record<string, string>): string {
  switch (status) {
    case "completed": return t.taskFilterCompleted;
    case "failed": return t.taskFilterFailed;
    case "running": return t.taskFilterRunning;
    case "pending": return t.taskFilterPending;
    default: return status;
  }
}

function agentName(agentId: number | null, agents: { agent_id: number; display_name: string }[]): string {
  if (agentId == null) return "—";
  const found = agents.find((a) => a.agent_id === agentId);
  return found ? found.display_name : `Agent-${agentId}`;
}

function formatDuration(ms: number | null): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function formatTime(ts: number): string {
  if (!ts) return "—";
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

const FILTERS: { value: TaskStatus | "all"; labelKey: string }[] = [
  { value: "all", labelKey: "taskFilterAll" },
  { value: "completed", labelKey: "taskFilterCompleted" },
  { value: "failed", labelKey: "taskFilterFailed" },
  { value: "running", labelKey: "taskFilterRunning" },
  { value: "pending", labelKey: "taskFilterPending" },
];

export function TaskMonitorPage() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const { tasks, loading, fetchTasks } = useSwarmTasks();
  const { agents, fetchAgents } = useSwarmRegistry();
  const { connect, disconnect } = useSwarmEvents();
  const [filter, setFilter] = useState<TaskStatus | "all">("all");

  const initData = useCallback(async () => {
    await Promise.all([fetchTasks(), fetchAgents()]);
    connect(window.location.origin);
  }, [fetchTasks, fetchAgents, connect]);

  useEffect(() => {
    initData();
    const interval = setInterval(fetchTasks, 15_000);
    return () => {
      clearInterval(interval);
      disconnect();
    };
  }, [initData, fetchTasks, disconnect]);

  const filtered = filter === "all" ? tasks : tasks.filter((t) => t.status === filter);

  if (loading && tasks.length === 0) {
    return <LoadingSpinner />;
  }

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold font-[family-name:var(--font-body)] text-text-primary">
          {t.taskMonitor}
        </h1>
        <p className="text-sm text-text-secondary">{t.swarmAgents}</p>
      </div>

      {/* Filter bar */}
      <div className="flex gap-2 mb-4">
        {FILTERS.map((f) => (
          <button
            key={f.value}
            onClick={() => setFilter(f.value)}
            className={`px-3 py-1.5 text-xs rounded-lg border transition-colors ${
              filter === f.value
                ? "border-accent-cyan text-accent-cyan bg-accent-cyan/10"
                : "border-border text-text-secondary hover:border-accent-cyan/30"
            }`}
          >
            {t[f.labelKey as keyof typeof t] ?? f.labelKey}
          </button>
        ))}
      </div>

      {/* Task table */}
      {filtered.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 gap-3">
          <svg
            className="h-10 w-10 text-text-secondary"
            fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1}
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
          </svg>
          <p className="text-sm text-text-secondary">{t.taskNoTasks}</p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs text-text-secondary">
                <th className="px-4 py-2 font-medium">{t.taskId}</th>
                <th className="px-4 py-2 font-medium">{t.taskGoal}</th>
                <th className="px-4 py-2 font-medium">{t.taskStatus}</th>
                <th className="px-4 py-2 font-medium">{t.taskAgent}</th>
                <th className="px-4 py-2 font-medium">{t.taskDuration}</th>
                <th className="px-4 py-2 font-medium">{t.taskTime}</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((task) => (
                <tr
                  key={task.task_id}
                  onClick={() => navigate(`/swarm/tasks/${task.task_id}`)}
                  className="border-b border-border/50 hover:bg-surface/50 cursor-pointer transition-colors"
                >
                  <td className="px-4 py-2.5 font-[family-name:var(--font-mono)] text-xs text-text-secondary">
                    {task.task_id.slice(0, 8)}…
                  </td>
                  <td className="px-4 py-2.5 text-text-primary max-w-[300px] truncate">
                    {task.goal}
                  </td>
                  <td className="px-4 py-2.5">
                    <span
                      className={`inline-block text-[10px] px-2 py-0.5 rounded-full border ${STATUS_BADGE[task.status] ?? "border-border text-text-secondary"}`}
                    >
                      {statusLabel(task.status, t)}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-text-primary">
                    {agentName(task.assigned_agent_id, agents)}
                  </td>
                  <td className="px-4 py-2.5 font-[family-name:var(--font-mono)] text-xs text-text-primary">
                    {formatDuration(task.duration_ms)}
                  </td>
                  <td className="px-4 py-2.5 text-xs text-text-secondary">
                    {formatTime(task.timestamp)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Add routes in `App.tsx`**

Add import:

```typescript
import { TaskMonitorPage } from "./pages/swarm/TaskMonitorPage";
```

Add route inside the `<SwarmGuard>` block, after the `/swarm` route:

```tsx
            <Route path="/swarm/tasks" element={<TaskMonitorPage />} />
```

- [ ] **Step 4: Add nav item in `AdminLayout.tsx`**

Find the existing Swarm nav item and add a Tasks item after it, indented under the Swarm section:

```tsx
          { label: t.navTasks, path: "/swarm/tasks" },
```

Place it adjacent to the existing Swarm Overview nav item, within the same SWARM section group.

- [ ] **Step 5: Verify TypeScript compiles**

Run: `cd admin/frontend && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 6: Commit**

```bash
git add admin/frontend/src/pages/swarm/TaskMonitorPage.tsx admin/frontend/src/App.tsx admin/frontend/src/components/AdminLayout.tsx admin/frontend/src/i18n/en.ts admin/frontend/src/i18n/zh.ts
git commit -m "feat(swarm): add TaskMonitorPage with filter bar and SSE updates"
```

---

### Task 7: Frontend — TaskDetailPage

**Files:**
- Create: `admin/frontend/src/pages/swarm/TaskDetailPage.tsx`
- Modify: `admin/frontend/src/App.tsx`

- [ ] **Step 1: Create TaskDetailPage**

```tsx
// admin/frontend/src/pages/swarm/TaskDetailPage.tsx
import { useState, useEffect, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import type { SwarmTask } from "../../stores/swarmTasks";
import { adminFetch } from "../../lib/admin-api";
import { useSwarmRegistry } from "../../stores/swarmRegistry";
import { useI18n } from "../../hooks/useI18n";
import { LoadingSpinner } from "../../components/LoadingSpinner";

const STATUS_BADGE: Record<string, string> = {
  completed: "bg-success/15 text-success border-success/30",
  failed: "bg-accent-pink/15 text-accent-pink border-accent-pink/30",
  running: "bg-accent-cyan/15 text-accent-cyan border-accent-cyan/30",
  pending: "bg-warning/15 text-warning border-warning/30",
};

export function TaskDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { t } = useI18n();
  const navigate = useNavigate();
  const { agents, fetchAgents } = useSwarmRegistry();
  const [task, setTask] = useState<SwarmTask | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchTask = useCallback(async () => {
    if (!id) return;
    try {
      const result = await adminFetch<SwarmTask | null>(`/swarm/tasks/${id}`);
      setTask(result);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : t.errorLoadFailed);
    } finally {
      setLoading(false);
    }
  }, [id, t.errorLoadFailed]);

  useEffect(() => {
    fetchTask();
    fetchAgents();
  }, [fetchTask, fetchAgents]);

  if (loading) return <LoadingSpinner />;

  if (error || !task) {
    return (
      <div className="py-16 text-center">
        <p className="text-accent-pink mb-4">{error ?? "Task not found"}</p>
        <button
          onClick={() => navigate("/swarm/tasks")}
          className="text-accent-cyan hover:underline text-sm"
        >
          &larr; {t.taskMonitor}
        </button>
      </div>
    );
  }

  const agentName = (agentId: number | null) => {
    if (agentId == null) return "—";
    const found = agents.find((a) => a.agent_id === agentId);
    return found ? found.display_name : `Agent-${agentId}`;
  };

  const formatTime = (ts: number) => {
    if (!ts) return "—";
    return new Date(ts * 1000).toLocaleString();
  };

  return (
    <div>
      {/* Header */}
      <div className="mb-6">
        <button
          onClick={() => navigate("/swarm/tasks")}
          className="text-xs text-text-secondary hover:text-accent-cyan mb-2 inline-block"
        >
          &larr; {t.taskMonitor}
        </button>
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-semibold font-[family-name:var(--font-body)] text-text-primary">
            {t.taskId}: {task.task_id.slice(0, 12)}…
          </h1>
          <span
            className={`text-[10px] px-2 py-0.5 rounded-full border ${STATUS_BADGE[task.status] ?? "border-border text-text-secondary"}`}
          >
            {task.status}
          </span>
        </div>
      </div>

      {/* Metadata */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
        <div className="rounded-lg border border-border bg-surface p-4 space-y-3">
          <div>
            <p className="text-xs text-text-secondary mb-0.5">{t.taskGoal}</p>
            <p className="text-sm text-text-primary">{task.goal || "—"}</p>
          </div>
          <div>
            <p className="text-xs text-text-secondary mb-0.5">{t.taskType}</p>
            <p className="text-sm font-[family-name:var(--font-mono)] text-text-primary">{task.task_type || "—"}</p>
          </div>
          <div>
            <p className="text-xs text-text-secondary mb-0.5">{t.taskAgent}</p>
            <p className="text-sm text-text-primary">{agentName(task.assigned_agent_id)}</p>
          </div>
        </div>
        <div className="rounded-lg border border-border bg-surface p-4 space-y-3">
          <div>
            <p className="text-xs text-text-secondary mb-0.5">{t.taskDuration}</p>
            <p className="text-sm font-[family-name:var(--font-mono)] text-text-primary">
              {task.duration_ms != null ? `${task.duration_ms}ms` : "—"}
            </p>
          </div>
          <div>
            <p className="text-xs text-text-secondary mb-0.5">{t.taskTime}</p>
            <p className="text-sm text-text-primary">{formatTime(task.timestamp)}</p>
          </div>
        </div>
      </div>

      {/* Error */}
      {task.error && (
        <div className="rounded-lg border border-accent-pink/30 bg-accent-pink/5 p-4 mb-6">
          <p className="text-xs text-accent-pink mb-1">Error</p>
          <pre className="text-sm text-text-primary whitespace-pre-wrap font-[family-name:var(--font-mono)]">
            {task.error}
          </pre>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Add route in `App.tsx`**

Add import:

```typescript
import { TaskDetailPage } from "./pages/swarm/TaskDetailPage";
```

Add route inside the `<SwarmGuard>` block:

```tsx
            <Route path="/swarm/tasks/:id" element={<TaskDetailPage />} />
```

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd admin/frontend && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add admin/frontend/src/pages/swarm/TaskDetailPage.tsx admin/frontend/src/App.tsx
git commit -m "feat(swarm): add TaskDetailPage with metadata and error display"
```

---

### Task 8: E2E Tests for Task Monitor

**Files:**
- Create: `admin/frontend/e2e/task-monitor.spec.ts`

- [ ] **Step 1: Write E2E tests**

```typescript
// admin/frontend/e2e/task-monitor.spec.ts
import { test, expect } from "@playwright/test";

test.describe("Task Monitor", () => {
  test.beforeEach(async ({ page }) => {
    await page.route("**/admin/api/login", async (route) => {
      await route.fulfill({ status: 200, body: JSON.stringify({ success: true }) });
    });
    await page.route("**/admin/api/swarm/capability", async (route) => {
      await route.fulfill({ status: 200, body: JSON.stringify({ enabled: true }) });
    });
    await page.route("**/admin/api/swarm/agents", async (route) => {
      await route.fulfill({
        status: 200,
        body: JSON.stringify([
          { agent_id: 1, display_name: "Supervisor", capabilities: ["supervision"], status: "online", current_tasks: 0, max_concurrent_tasks: 5, last_heartbeat: Date.now() / 1000, model: "claude-sonnet" },
          { agent_id: 3, display_name: "Reviewer", capabilities: ["code-review"], status: "busy", current_tasks: 2, max_concurrent_tasks: 3, last_heartbeat: Date.now() / 1000, model: "claude-sonnet" },
        ]),
      });
    });
    await page.route("**/admin/api/swarm/tasks", async (route) => {
      await route.fulfill({
        status: 200,
        body: JSON.stringify([
          { task_id: "a1b2c3d4-0001-4000-8000-000000000001", task_type: "code-review", goal: "Review agent_manager.py", status: "completed", sender_id: 1, assigned_agent_id: 3, duration_ms: 4500, error: "", timestamp: Date.now() / 1000 - 60 },
          { task_id: "a1b2c3d4-0002-4000-8000-000000000002", task_type: "code-review", goal: "Review models.py", status: "failed", sender_id: 1, assigned_agent_id: 3, duration_ms: 1200, error: "LLM timeout", timestamp: Date.now() / 1000 - 120 },
          { task_id: "a1b2c3d4-0003-4000-8000-000000000003", task_type: "testing", goal: "Write unit tests", status: "running", sender_id: 1, assigned_agent_id: 3, duration_ms: null, error: "", timestamp: Date.now() / 1000 - 10 },
        ]),
      });
    });
    await page.route("**/admin/api/swarm/events/token", async (route) => {
      await route.fulfill({ status: 200, body: JSON.stringify({ token: "sse_test_token_1234", expires_in: 1800 }) });
    });
    await page.route("**/admin/api/swarm/events/stream*", async (route) => {
      await route.fulfill({
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
        body: "id: 1\nevent: heartbeat\ndata: {}\n\n",
      });
    });
    // Default mocks for cluster/agents needed by AdminLayout
    await page.route("**/admin/api/agents", async (route) => {
      await route.fulfill({ status: 200, body: JSON.stringify({ agents: [], total: 0 }) });
    });
    await page.route("**/admin/api/cluster/status", async (route) => {
      await route.fulfill({ status: 200, body: JSON.stringify({ nodes: [], namespace: "hermes-agent", total_agents: 0, running_agents: 0 }) });
    });
  });

  test("shows task list with correct rows", async ({ page }) => {
    await page.goto("/admin/login");
    await page.evaluate(() => {
      localStorage.setItem("admin_api_key", "test-admin-key-1234");
    });

    await page.goto("/admin/swarm/tasks");
    await expect(page.getByText("Review agent_manager.py")).toBeVisible({ timeout: 10000 });
    await expect(page.getByText("Review models.py")).toBeVisible();
    await expect(page.getByText("Write unit tests")).toBeVisible();
  });

  test("filter buttons work", async ({ page }) => {
    await page.goto("/admin/login");
    await page.evaluate(() => {
      localStorage.setItem("admin_api_key", "test-admin-key-1234");
    });

    await page.goto("/admin/swarm/tasks");
    await expect(page.getByText("Review agent_manager.py")).toBeVisible({ timeout: 10000 });

    // Click "Failed" filter
    const failedFilter = page.getByRole("button", { name: /Failed|已失败/ });
    await failedFilter.click();

    // Only the failed task should be visible
    await expect(page.getByText("Review models.py")).toBeVisible();
    await expect(page.getByText("Review agent_manager.py")).not.toBeVisible();
  });

  test("navigates to task detail on row click", async ({ page }) => {
    await page.route("**/admin/api/swarm/tasks/a1b2c3d4-0001-4000-8000-000000000001", async (route) => {
      await route.fulfill({
        status: 200,
        body: JSON.stringify({
          task_id: "a1b2c3d4-0001-4000-8000-000000000001",
          task_type: "code-review",
          goal: "Review agent_manager.py",
          status: "completed",
          sender_id: 1,
          assigned_agent_id: 3,
          duration_ms: 4500,
          error: "",
          timestamp: Date.now() / 1000 - 60,
        }),
      });
    });

    await page.goto("/admin/login");
    await page.evaluate(() => {
      localStorage.setItem("admin_api_key", "test-admin-key-1234");
    });

    await page.goto("/admin/swarm/tasks");
    await expect(page.getByText("Review agent_manager.py")).toBeVisible({ timeout: 10000 });

    // Click the task row
    await page.getByText("Review agent_manager.py").click();
    await expect(page).toHaveURL(/\/admin\/swarm\/tasks\//, { timeout: 10000 });
    await expect(page.getByText("4500ms")).toBeVisible();
  });

  test("task detail shows error for failed tasks", async ({ page }) => {
    await page.route("**/admin/api/swarm/tasks/a1b2c3d4-0002-4000-8000-000000000002", async (route) => {
      await route.fulfill({
        status: 200,
        body: JSON.stringify({
          task_id: "a1b2c3d4-0002-4000-8000-000000000002",
          task_type: "code-review",
          goal: "Review models.py",
          status: "failed",
          sender_id: 1,
          assigned_agent_id: 3,
          duration_ms: 1200,
          error: "LLM timeout",
          timestamp: Date.now() / 1000 - 120,
        }),
      });
    });

    await page.goto("/admin/login");
    await page.evaluate(() => {
      localStorage.setItem("admin_api_key", "test-admin-key-1234");
    });

    await page.goto("/admin/swarm/tasks/a1b2c3d4-0002-4000-8000-000000000002");
    await expect(page.getByText("LLM timeout")).toBeVisible({ timeout: 10000 });
  });
});
```

- [ ] **Step 2: Run E2E tests**

Run: `cd admin/frontend && npx playwright test task-monitor --reporter=list`
Expected: 4 PASSED

- [ ] **Step 3: Commit**

```bash
git add admin/frontend/e2e/task-monitor.spec.ts
git commit -m "test(swarm): add E2E tests for TaskMonitorPage and TaskDetailPage"
```

---

### Task 9: Build and Integration Verification

**Files:** None (verification only)

- [ ] **Step 1: Run full backend test suite**

Run: `python -m pytest tests/test_swarm/ -v`
Expected: All PASS

- [ ] **Step 2: Run frontend build**

Run: `cd admin/frontend && npm run build`
Expected: Build succeeds

- [ ] **Step 3: Run all E2E tests**

Run: `cd admin/frontend && npx playwright test --reporter=list`
Expected: All PASS (swarm + task-monitor)

- [ ] **Step 4: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix(swarm): integration fixes from build verification"
```
