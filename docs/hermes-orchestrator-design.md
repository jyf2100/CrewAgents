# Hermes Orchestrator -- Revised Architecture Design

> **Status**: Implementation-ready (post 2nd expert review)
> **Last updated**: 2026-05-02
> **Supersedes**: Original + 1st revision (pre-review, post-review-v1)

---

## Table of Contents

1. [Overview](#1-overview)
2. [Critical Corrections (Round 2)](#2-critical-corrections-round-2)
3. [Integration Pattern](#3-integration-pattern)
4. [Agent Discovery](#4-agent-discovery)
5. [Health Monitoring](#5-health-monitoring)
6. [Task Lifecycle](#6-task-lifecycle)
7. [API Surface](#7-api-surface)
8. [Redis Schema](#8-redis-schema)
9. [Workflow Engine](#9-workflow-engine)
10. [Security](#10-security)
11. [Deployment](#11-deployment)
12. [Implementation Phases](#12-implementation-phases)
13. [Key Files Reference](#13-key-files-reference)

---

## 1. Overview

### What Hermes Orchestrator Does

Hermes Orchestrator is a control plane that dispatches tasks to multiple Hermes Agent gateway instances running in Kubernetes. It provides:

- **Task routing**: Accept external requests, select the best available agent, execute asynchronously.
- **Agent lifecycle**: Track which agents are alive, what capabilities they have, and whether they are overloaded.
- **Workflow composition** (Phase 2/3): Chain multi-step tasks -- sequential, parallel, and DAG patterns.
- **Result extraction**: Read structured results from the gateway's chat database after execution completes.

### Constraints

The orchestrator treats each gateway as a **black box**. It does not:

- Call the LLM provider directly (that is the gateway's job).
- Inject system prompts or manage conversation history.
- Parse streaming SSE output in real-time (it reads final results from the chat DB).

The orchestrator communicates with gateways through their existing APIs:

1. **Gateway HTTP API** (`:8642`): Health checks, model discovery, task execution.
2. **`/v1/runs` endpoint**: Asynchronous task submission (returns 202 immediately), with SSE event stream for real-time progress.
3. **`/v1/responses` endpoint**: Synchronous task execution with structured output and SQLite persistence.

### Relationship with hermes-admin

| Concern | hermes-admin | hermes-orchestrator |
|---------|-------------|-------------------|
| Gateway lifecycle (create/delete/restart) | Owns | Read-only |
| Resource monitoring (CPU/memory) | Owns | Reads |
| Task routing & execution | No role | Owns |
| Agent health for task dispatch | Basic health | Task-failure-aware + circuit breaker |
| Workflow composition | No role | Owns |

Admin manages the fleet; Orchestrator routes work through it.

### Architecture Diagram

```
External Client / Scheduler
        |
        v
  +--------------------------+
  |   Hermes Orchestrator    |  (FastAPI, async, single process)
  |  - REST API              |
  |  - Task Queue (Stream)   |
  |  - Agent Registry        |
  |  - Health Monitor        |
  |  - Workflow Engine       |
  |  - Result Extraction     |  (internal module in MVP)
  +--------------------------+
    |          |          |
    | Redis    | K8s API  | HTTP
    |          |          |
    v          v          v
  Redis     K8s API    Gateway Pods (1..N)
  (state)   (discovery)    |
                           v
                    /v1/runs (async 202 + SSE events)
                    /v1/responses (sync 200 + structured output)
                    /v1/models (capability discovery)
                    /health (liveness)
```

**Result extraction** is an internal module in the orchestrator (MVP), not a separate service.
It reads structured `output` + `usage` from `/v1/runs` completed events. Phase 2 may extract
it into a standalone service if LLM-based extraction is needed.

---

## 2. Critical Corrections (Round 2)

Four expert reviewers (architect, security, backend/ops, product/integration) identified
fundamental errors in the previous revision. The table below summarizes every correction.

### Round 1 Corrections (Original → 1st Revision)

| # | Original (Wrong) | 1st Revision (Correct) |
|---|---|---|
| 1 | `POST /chat/completions` with `stream:false` | Automation/async task pattern with streaming |
| 2 | Parse LLM natural-language output | Read structured results from chat DB |
| 3 | Simple request/response over HTTP | Async task with poll for completion |
| 4 | Fixed 10s health polling | Task failure as immediate signal + adaptive polling |
| 5-10 | Various security fixes | CORS, Redis auth, TLS, secrets, NetworkPolicy |

### Round 2 Corrections (1st Revision → This Document)

| # | 1st Revision (Wrong) | This Document (Correct) | Why | Source |
|---|---|---|---|---|
| 1 | `POST /api/chat/completions` fire-and-forget + poll `/api/chats/{chat_id}` | **`POST /v1/runs`** (returns 202 + run_id) + **`GET /v1/runs/{run_id}/events`** (SSE) | `/api/chats/{chat_id}` does not exist on gateway. `/v1/runs` is a real async API — 202 immediate return, agent runs in background thread, no connection needed. | Architect, Backend, Product |
| 2 | `GET /api/models` for discovery | **`GET /v1/models`** | Gateway registers routes under `/v1/`, not `/api/`. | Backend, Product |
| 3 | Parse chat DB SQLite directly | **Read structured `output` from `/v1/runs` completed event** or **`/v1/responses` response object** | Gateway's `/v1/runs` emits `run.completed` with `output` + `usage`. `/v1/responses` stores structured `output` array in SQLite. No need to read raw DB. | Backend, Product |
| 4 | Result Extraction Agent as separate K8s deployment | **Internal module** in orchestrator (MVP), separate service only if needed (Phase 2) | `direct` strategy covers 90% cases. Over-engineered for MVP. | Architect, Product |
| 5 | Redis Sorted Set for task queue | **Redis Stream** (`XADD`/`XREADGROUP`/`XACK`) | Sorted Set has no consumer acknowledgment — crash loses tasks. Stream provides exactly-once delivery with XACK. | Backend |
| 6 | Redis without persistence, no AOF | **AOF persistence** (`appendonly yes`) + PVC | Redis restart loses all in-flight tasks and circuit breaker state, making crash recovery useless. | Architect, Backend |
| 7 | Auth middleware with string comparison | **`hmac.compare_digest()`** for constant-time comparison + startup validation rejecting empty key | String comparison is vulnerable to timing attacks. Empty default key = no auth. | Security |
| 8 | NetworkPolicy egress `cidr: 0.0.0.0/0:443` | **K8s API server endpoint selector** or specific CIDR | `0.0.0.0/0` allows egress to any HTTPS endpoint, not just K8s API. | Security |
| 9 | `/v1/responses` and `/v1/runs` endpoints ignored | **Documented and used** as primary integration surface | Gateway already has async task + structured output. Reimplementing was unnecessary. | Backend, Product |
| 10 | No relationship defined with hermes-admin | **Clear separation**: Admin = fleet lifecycle, Orchestrator = task routing | Overlapping health monitoring and agent management causes conflicts. | Product |

---

## 3. Integration Pattern

### Gateway's Existing `/v1/runs` API

The gateway already implements a fully async task execution API at `POST /v1/runs`. This is not
a new feature — it is production code in `gateway/platforms/api_server.py`.

**How it works:**

1. `POST /v1/runs` with `{"input": "..."}` → immediate `202 {"run_id": "run_xxx", "status": "started"}`
2. Agent executes in a background thread (`asyncio.create_task` + `run_in_executor`), independent of the HTTP connection
3. `GET /v1/runs/{run_id}/events` → SSE stream with structured events:
   - `message.delta` — text streaming
   - `tool.started` / `tool.completed` — tool execution progress
   - `reasoning.available` — thinking/reasoning text output
   - `run.completed` — final output + usage (terminal)
   - `run.failed` — error (terminal)
4. Orphan cleanup after 5 minutes if events not consumed

The orchestrator does **not** need to build fire-and-forget, create synthetic sessions,
or poll a chat DB. It submits via `/v1/runs` and consumes the SSE event stream.

### Step-by-Step: Submitting a Task to a Gateway

#### Step 1: Select a Gateway

Use the agent selector (Section 6) to pick the best available gateway pod.

#### Step 2: Submit via `/v1/runs`

```python
async def _submit_run(
    self, gateway_url: str, prompt: str, instructions: str = ""
) -> str:
    """Submit an async run to a gateway. Returns run_id."""
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{gateway_url}/v1/runs",
            json={
                "input": prompt,
                "instructions": instructions,
            },
            headers=self._gateway_headers,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            if resp.status == 429:
                raise GatewayOverloadedError("Gateway concurrent run limit reached")
            if resp.status != 202:
                body = await resp.text()
                raise TaskSubmissionError(f"Gateway returned {resp.status}: {body}")
            data = await resp.json()
            return data["run_id"]
```

#### Step 3: Consume SSE Events

Subscribe to the run's event stream and wait for `run.completed` or `run.failed`:

```python
async def _consume_run_events(
    self,
    gateway_url: str,
    run_id: str,
    max_wait: float = 600.0,
) -> RunResult:
    """Consume SSE events until run completes or fails."""
    deadline = time.monotonic() + max_wait
    output = ""
    usage = {}

    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{gateway_url}/v1/runs/{run_id}/events",
            headers=self._gateway_headers,
            timeout=aiohttp.ClientTimeout(total=max_wait),
        ) as resp:
            if resp.status != 200:
                raise RunNotFoundError(f"Run {run_id} not found on gateway")

            async for line in resp.content:
                if time.monotonic() > deadline:
                    raise TaskTimeoutError(f"Run {run_id} timed out")

                if not line.startswith(b"data: "):
                    continue
                event = json.loads(line[6:])

                if event["event"] == "message.delta":
                    output += event.get("delta", "")
                elif event["event"] == "reasoning.available":
                    logger.debug("Run %s: reasoning available (%d chars)", run_id, len(event.get("text", "")))
                elif event["event"] == "tool.started":
                    logger.info("Run %s: tool %s started", run_id, event.get("tool"))
                elif event["event"] == "tool.completed":
                    logger.info("Run %s: tool %s completed", run_id, event.get("tool"))
                elif event["event"] == "run.completed":
                    return RunResult(
                        run_id=run_id,
                        status="completed",
                        output=event.get("output", output),
                        usage=event.get("usage", {}),
                    )
                elif event["event"] == "run.failed":
                    return RunResult(
                        run_id=run_id,
                        status="failed",
                        error=event.get("error", "Unknown error"),
                    )

    raise TaskTimeoutError(f"Run {run_id} stream ended without completion")
```

#### Step 4: Extract Structured Results

The `run.completed` event contains structured data:

```json
{
  "event": "run.completed",
  "run_id": "run_abc123",
  "output": "The Q1 report shows revenue of $4.2M...",
  "usage": {
    "input_tokens": 1250,
    "output_tokens": 380,
    "total_tokens": 1630
  }
}
```

For tasks that need richer structured output (function calls, citations), use `/v1/responses`
instead (synchronous, stores in SQLite):

```python
async def _submit_response(
    self, gateway_url: str, prompt: str, instructions: str = ""
) -> dict:
    """Submit a synchronous response request. Blocks until complete."""
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{gateway_url}/v1/responses",
            json={"input": prompt, "instructions": instructions, "store": True},
            headers=self._gateway_headers,
            timeout=aiohttp.ClientTimeout(total=600),
        ) as resp:
            resp.raise_for_status()
            return await resp.json()
    # Response contains: id, status, output (typed array), usage
```

### When to Use `/v1/runs` vs `/v1/responses`

| Scenario | Endpoint | Reason |
|----------|----------|--------|
| Long-running tasks (tool loops, code execution) | `/v1/runs` | Async, doesn't hold HTTP connection |
| Quick queries, structured output needed | `/v1/responses` | Returns typed `output` array |
| Workflow step with output chaining | `/v1/responses` | Stored in SQLite, retrievable by `response_id` |
| Background batch processing | `/v1/runs` | Higher throughput, no blocking |

The orchestrator uses `/v1/runs` as the default and `/v1/responses` for workflow steps
that need persistent structured output.

---

## 4. Agent Discovery

Agent discovery uses two complementary mechanisms: Kubernetes API for pod-level discovery
and gateway HTTP API for capability discovery.

### 4.1 Pod Discovery via K8s API

The orchestrator uses the Kubernetes API to discover gateway pods. Both `list` and `watch`
are supported — `watch` is preferred for near-real-time discovery:

```python
from kubernetes_asyncio import client, config

async def discover_gateway_pods(namespace: str = "hermes-agent") -> list[GatewayPod]:
    """Discover all gateway pods via K8s API (snapshot for initial load)."""
    api = client.CoreV1Api()
    pods = await api.list_namespaced_pod(
        namespace=namespace,
        label_selector="app.kubernetes.io/component=gateway",
    )
    result = []
    for pod in pods.items:
        if pod.status.phase != "Running":
            continue
        if not pod.status.pod_ip:
            continue
        port = 8642
        result.append(GatewayPod(
            name=pod.metadata.name,
            ip=pod.status.pod_ip,
            port=port,
            namespace=namespace,
            url=f"http://{pod.status.pod_ip}:{port}",
            created_at=pod.metadata.creation_timestamp.timestamp(),
        ))
    return result

async def watch_gateway_pods(namespace: str = "hermes-agent") -> None:
    """Watch for pod changes (add/update/delete) in real-time."""
    from kubernetes_asyncio import watch as k8s_watch
    api = client.CoreV1Api()
    w = k8s_watch.Watch()
    async for event in w.stream(
        api.list_namespaced_pod,
        namespace=namespace,
        label_selector="app.kubernetes.io/component=gateway",
        timeout_seconds=300,
    ):
        obj = event["object"]
        if event["type"] == "ADDED" and obj.status.phase == "Running":
            await self._register_pod(obj)
        elif event["type"] == "DELETED":
            await self._deregister_pod(obj.metadata.name)
        elif event["type"] == "MODIFIED":
            await self._update_pod(obj)
```

**Note:** The current gateway deployments (`hermes-gateway-1` through `hermes-gateway-13`)
do not have a unified `app.kubernetes.io/component=gateway` label — they only have `app: hermes-gateway`.
**Prerequisite:** Before implementing discovery, add the label to all gateway deployments:

```bash
# One-time: patch label on all existing gateway deployments
for i in $(seq 1 13); do
  kubectl patch deployment hermes-gateway-$i -n hermes-agent --type=json \
    -p '[{"op":"add","path":"/spec/template/metadata/labels/app.kubernetes.io~1component","value":"gateway"}]'
done
```

Also update `kubernetes/gateway/deployment.yaml` template to include the label in the pod template
so future deployments get it automatically.

### 4.2 Capability Discovery via `/v1/models`

Each gateway exposes model information at `GET /v1/models`. The orchestrator queries this
on startup and periodically (decoupled from pod discovery):

```python
async def discover_capabilities(gateway_url: str) -> list[AgentCapability]:
    """Query a gateway's /v1/models to discover available capabilities."""
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{gateway_url}/v1/models",
            headers=self._gateway_headers,
        ) as resp:
            models_data = await resp.json()

    capabilities = []
    for model_entry in models_data.get("data", []):
        model_id = model_entry.get("id", "")
        info = model_entry.get("info", {}) or {}
        meta = info.get("meta", {}) or {}

        cap = AgentCapability(
            gateway_url=gateway_url,
            model_id=model_id,
            capabilities=meta.get("capabilities", {}),
            tool_ids=meta.get("toolIds", []),
            supported_endpoints=model_entry.get("supported_endpoints", []),
        )
        capabilities.append(cap)
    return capabilities
```

**Important:** The current gateway configuration typically exposes a single model
`hermes-agent`. The `supported_endpoints` field indicates which API formats are available
(e.g., `["/chat/completions", "/responses"]`). The orchestrator should verify that
`/v1/runs` is available (it is always registered regardless of model config).

### 4.3 Agent Registry

Discovered agents are stored in Redis:

```python
@dataclass
class AgentProfile:
    agent_id: str          # Unique ID (pod name)
    gateway_url: str       # http://<pod_ip>:8642
    models: list[str]      # Available model IDs
    capabilities: dict     # Capabilities per model
    tool_ids: list[str]    # Attached tool IDs
    status: str            # "online" | "degraded" | "offline"
    current_load: int      # Number of in-flight tasks
    max_concurrent: int    # Max concurrent tasks (default: 10, matches gateway _MAX_CONCURRENT_RUNS)
    last_health_check: float  # Timestamp
    circuit_state: str     # "closed" | "open" | "half_open"
    registered_at: float
```

---

## 5. Health Monitoring

### 5.1 Health Signals

The orchestrator uses three health signals in priority order:

| Signal | Latency | Reliability | Action |
|--------|---------|-------------|--------|
| Task failure | Immediate | High | Record failure, evaluate circuit breaker |
| Health endpoint (`GET /health`) | Low | Medium | Confirm pod is alive and responsive |
| K8s pod status | Medium | High | Detect crashes, evictions, scheduling failures |

### 5.2 Adaptive Polling

Instead of fixed 10-second intervals, the orchestrator uses adaptive polling:

```python
class AdaptiveHealthChecker:
    """Poll health endpoints with adaptive intervals."""

    BASE_INTERVAL = 5.0      # seconds
    MAX_INTERVAL = 30.0      # seconds
    MIN_INTERVAL = 2.0       # seconds
    BACKOFF_FACTOR = 1.5     # multiply on failure

    def __init__(self):
        self._intervals: dict[str, float] = {}  # per-agent

    def next_interval(self, agent_id: str, last_check_ok: bool) -> float:
        current = self._intervals.get(agent_id, self.BASE_INTERVAL)
        if last_check_ok:
            # Gradually increase interval when healthy
            next_val = min(current * 1.1, self.MAX_INTERVAL)
        else:
            # Decrease interval when unhealthy
            next_val = max(current / self.BACKOFF_FACTOR, self.MIN_INTERVAL)
        self._intervals[agent_id] = next_val
        return next_val
```

### 5.3 Task Failure as Immediate Health Signal

When a task fails (timeout, gateway error, malformed response), the orchestrator records this immediately:

```python
async def _handle_task_failure(self, agent_id: str, task_id: str, error: str) -> None:
    """Handle task failure as an immediate health signal."""
    # Record failure in agent health tracker
    self._health.record_failure(agent_id)

    # Update circuit breaker
    circuit = self._circuits[agent_id]
    circuit.record_failure()

    # If circuit is open, mark agent as degraded
    if circuit.state == CircuitState.OPEN:
        await self._registry.update_status(agent_id, "degraded")
        logger.warning(
            "Agent %s circuit OPEN after failures. Marking degraded.",
            agent_id,
        )

    # Mark the task as failed
    await self._task_store.update(task_id, status="failed", error=error)

    # Re-queue the task if it hasn't exceeded max retries
    task = await self._task_store.get(task_id)
    if task and task.retry_count < task.max_retries:
        await self._requeue_task(task)
```

### 5.4 Circuit Breaker

Reuse the existing `swarm/circuit_breaker.py` implementation with tuned parameters:

```python
CircuitBreaker(
    failure_threshold=3,     # Open after 3 consecutive failures
    success_threshold=2,     # Close after 2 consecutive successes
    recovery_timeout=30.0,   # Wait 30s before half-open probe
)
```

**Note:** The circuit breaker is for HTTP call outcomes (task submission failures,
health check failures), NOT for Redis connections. Redis connection health is checked
separately in the orchestrator's `/health` endpoint.
```

### 5.5 Health Check Background Task

```python
async def health_check_loop(self) -> None:
    """Background task that periodically checks agent health."""
    while True:
        agents = await self._registry.list_agents()
        for agent in agents:
            if agent.status == "offline":
                continue

            try:
                healthy = await self._check_agent_health(agent)
                interval = self._adaptive.next_interval(agent.agent_id, healthy)
            except Exception:
                healthy = False
                interval = self._adaptive.MIN_INTERVAL

            if not healthy:
                self._circuits[agent.agent_id].record_failure()
            else:
                self._circuits[agent.agent_id].record_success()
                await self._registry.update_health(agent.agent_id, healthy)

        await asyncio.sleep(self._adaptive.min_current_interval())

async def _check_agent_health(self, agent: AgentProfile) -> bool:
    """Check if a gateway agent is healthy via /health endpoint."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{agent.gateway_url}/health",
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                return resp.status == 200
    except Exception:
        return False
```

---

## 6. Task Lifecycle

### State Machine

```
                    +-----------+
                    | submitted  |
                    +-----+-----+
                          |
                    +-----v-----+
             +----->|  queued   |
             |      +-----+-----+     Redis Stream consumer
             |            |            picks up task
             |      +-----v-----+
             |      |  assigned  |    agent selected
             |      +-----+-----+
             |            |
             |      +-----v-----+
             |      | executing  |    POST /v1/runs → 202
             |      +-----+-----+
             |            |
             |      +-----v-----+
             |      | streaming  |    GET /v1/runs/{id}/events SSE
             |      +-----+-----+
             |            |
             |    +-------+--------+
             |    |                |
             | +--v--+        +---v---+
             | | done |        | failed |
             | +-----+        +-------+
             |                    |
             |            +-------v-------+
             +------------+ retry (if < 3)|
                          +---------------+
```

### Task States

| State | Description | Transitions |
|-------|-------------|-------------|
| `submitted` | Task received by orchestrator API | -> `queued` |
| `queued` | Waiting in Redis Stream for consumer | -> `assigned` |
| `assigned` | Agent selected, preparing request | -> `executing` |
| `executing` | `POST /v1/runs` sent, got 202 | -> `streaming` |
| `streaming` | Consuming SSE events from gateway | -> `done`, `failed` |
| `done` | Completed successfully (got `run.completed`) | terminal |
| `failed` | Failed (got `run.failed` or timeout) | -> `queued` (retry) |

### Task Data Model

```python
@dataclass
class Task:
    task_id: str
    prompt: str
    instructions: str = ""    # System prompt for the agent
    model_id: str = "hermes-agent"  # Default model on gateway
    status: str              # submitted|queued|assigned|executing|streaming|done|failed
    assigned_agent: str | None
    run_id: str | None       # Gateway run_id from POST /v1/runs
    result: TaskResult | None
    error: str | None
    retry_count: int = 0
    max_retries: int = 2
    priority: int = 1
    created_at: float
    updated_at: float
    timeout_seconds: float = 600.0
    metadata: dict = field(default_factory=dict)

@dataclass
class TaskResult:
    content: str             # Final text response
    usage: dict              # {input_tokens, output_tokens, total_tokens}
    duration_seconds: float
    run_id: str              # Gateway run_id
```

### Agent Selection (Load-Aware with Circuit Breaker)

```python
class AgentSelector:
    """Select the best agent for a task."""

    def select(self, agents: list[AgentProfile], task: Task) -> AgentProfile | None:
        """Select agent with lowest load that isn't circuit-broken."""
        candidates = [
            a for a in agents
            if a.status in ("online", "degraded")
            and a.current_load < a.max_concurrent
            and self._circuits[a.agent_id].state != CircuitState.OPEN
        ]
        if not candidates:
            return None

        # Prefer agents with lowest current load
        candidates.sort(key=lambda a: (a.current_load, a.last_health_check))
        return candidates[0]
```

**Note:** Model filtering is removed because each gateway exposes a single `hermes-agent`
model. If multi-model gateways are introduced later, add `and task.model_id in a.models`.

### 6.5 Result Extraction (Internal Module)

Result extraction is an **internal module** in the orchestrator, not a separate service.
It processes the structured data already returned by `/v1/runs` completed events.

#### Extraction Strategies

| Strategy | When to Use | Method |
|----------|------------|--------|
| `direct` | Default. `run.completed` event has `output` + `usage` | Pass through, no processing |
| `parse` | Response contains JSON blocks or numbered lists | Regex + JSON extraction |
| `llm` | Needs interpretation of free-form text into schema | Call lightweight model (Phase 2) |

#### MVP: Direct Strategy Only

```python
def extract_result(self, event: dict, task: Task) -> TaskResult:
    """Extract result from a run.completed event (direct strategy)."""
    return TaskResult(
        content=event.get("output", ""),
        usage=event.get("usage", {}),
        duration_seconds=time.time() - task.created_at,
        run_id=event.get("run_id", ""),
    )
```

Phase 2 adds `parse` and `llm` strategies. If LLM extraction is frequently needed,
the module can be extracted into a standalone service at that point.

---

## 7. API Surface

### Orchestrator REST API

All endpoints require authentication via `Authorization: Bearer <orchestrator-api-key>`.
Responses include a `Retry-After` header for polling guidance.

#### `POST /api/v1/tasks` -- Submit a Task

**Request:**

```json
{
  "prompt": "Summarize the Q1 financial report and extract key metrics.",
  "instructions": "You are a financial analyst.",
  "model_id": "hermes-agent",
  "priority": 1,
  "timeout_seconds": 600,
  "max_retries": 2,
  "callback_url": "https://example.com/webhook/task-complete",
  "metadata": {
    "source": "cron-scheduler",
    "workflow_step": "step_1"
  }
}
```

**Response (202 Accepted):**

```json
{
  "task_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "queued",
  "created_at": 1746316800.0,
  "eta_seconds": 30
}
```

Headers: `Retry-After: 5` (suggest polling interval in seconds).

If `callback_url` is provided, the orchestrator sends a POST to that URL when the task
completes (webhook pattern, avoiding polling).

**Webhook security requirements:**

1. **HTTPS required**: `callback_url` must use `https://`. HTTP callbacks are rejected.
2. **HMAC signature**: Each callback includes `X-Hermes-Signature: sha256=<hmac_hex>` header,
   computed with `hmac.new(ORCHESTRATOR_API_KEY, body, sha256)`. The receiver should verify.
3. **Timeout + retry**: 10-second timeout per attempt. Up to 3 retries with exponential backoff
   (1s, 2s, 4s) on connection errors or 5xx responses. 4xx responses are not retried.
4. **Idempotency**: The receiver must handle duplicate callbacks gracefully (use `task_id` as
   idempotency key). The orchestrator may retry on network uncertainty.

```python
async def _send_callback(self, callback_url: str, task: Task) -> None:
    """Send webhook callback with HMAC signature."""
    if not callback_url.startswith("https://"):
        logger.warning("Callback URL must use HTTPS: %s", callback_url)
        return

    body = json.dumps({"task_id": task.task_id, "status": task.status,
                        "result": asdict(task.result) if task.result else None})
    signature = hmac.new(
        ORCHESTRATOR_API_KEY.encode(), body.encode(), "sha256"
    ).hexdigest()

    headers = {
        "Content-Type": "application/json",
        "X-Hermes-Signature": f"sha256={signature}",
    }

    for attempt in range(3):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    callback_url, data=body, headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status < 500:
                        return  # Success or client error (don't retry 4xx)
        except Exception as e:
            logger.warning("Callback attempt %d failed: %s", attempt + 1, e)
        await asyncio.sleep(2 ** attempt)
    logger.error("All 3 callback attempts failed for task %s", task.task_id)
```

#### `GET /api/v1/tasks/{task_id}` -- Get Task Status

**Response (200 OK):**

```json
{
  "task_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "done",
  "assigned_agent": "hermes-gateway-7d8f9c-x2k4",
  "run_id": "run_abc123",
  "result": {
    "content": "The Q1 report shows revenue of $4.2M, up 12% YoY...",
    "usage": {
      "input_tokens": 1250,
      "output_tokens": 380,
      "total_tokens": 1630
    },
    "duration_seconds": 14.3,
    "run_id": "run_abc123"
  },
  "retry_count": 0,
  "created_at": 1746316800.0,
  "updated_at": 1746316814.3
}
```

Headers: `Retry-After: 5`.

#### `GET /api/v1/tasks?status=queued&limit=50` -- List Tasks

Query parameters: `status`, `limit`, `offset`.

#### `DELETE /api/v1/tasks/{task_id}` -- Cancel a Task

Only tasks in `queued` or `assigned` state can be cancelled.
Tasks already `executing` or `streaming` are allowed to complete.

#### `GET /api/v1/agents` -- List Registered Agents

**Response (200 OK):**

```json
{
  "agents": [
    {
      "agent_id": "hermes-gateway-7d8f9c-x2k4",
      "gateway_url": "http://10.244.1.42:8642",
      "status": "online",
      "models": ["hermes-agent"],
      "current_load": 1,
      "max_concurrent": 3,
      "circuit_state": "closed",
      "last_health_check": 1746316795.0
    }
  ]
}
```

#### `GET /api/v1/agents/{agent_id}/health` -- Agent Health Detail

#### `POST /api/v1/workflows` -- Submit a Workflow (Phase 2/3)

**Request:**

```json
{
  "name": "Research and Summarize",
  "type": "sequential",
  "steps": [
    {
      "id": "research",
      "model_id": "claude-sonnet-4-20250514",
      "prompt": "Research the latest trends in {topic}",
      "timeout_seconds": 300
    },
    {
      "id": "summarize",
      "model_id": "claude-sonnet-4-20250514",
      "prompt": "Summarize these findings into a 500-word report:\n\n{research.output}",
      "depends_on": ["research"],
      "timeout_seconds": 120
    }
  ],
  "timeout_seconds": 600
}
```

**Response (202 Accepted):**

```json
{
  "workflow_id": "wf_abc123",
  "status": "running",
  "created_at": 1746316800.0
}
```

#### `GET /api/v1/workflows/{workflow_id}` -- Get Workflow Status

**Response (200 OK):**

```json
{
  "workflow_id": "wf_abc123",
  "status": "completed",
  "steps": {
    "research": {
      "status": "done",
      "task_id": "task_research_123",
      "result": {
        "content": "Key trends include...",
        "duration_seconds": 45.2
      }
    },
    "summarize": {
      "status": "done",
      "task_id": "task_summarize_456",
      "result": {
        "content": "# Research Summary\n\n...",
        "duration_seconds": 12.1
      }
    }
  },
  "total_duration_seconds": 57.3
}
```

---

## 8. Redis Schema

### Key Patterns

```
# Task Queue (Redis Stream — consumer group pattern)
hermes:orchestrator:tasks:stream                    # STREAM: task submissions
                                                    # Fields: task_id, priority, prompt, model_id, metadata_json
                                                    # Consumer group: orchestrator.workers

# Task Details
hermes:orchestrator:tasks:{task_id}                 # HASH: field=data, value=JSON(Task)

# Task Results
hermes:orchestrator:results:{task_id}               # STRING (JSON): TaskResult (TTL: 7 days)

# Agent Registry
hermes:orchestrator:agents                          # HASH: field=agent_id, value=JSON(AgentProfile)

# Agent Health
hermes:orchestrator:health:{agent_id}               # STRING: timestamp of last successful check (TTL: 60s)
hermes:orchestrator:circuit:{agent_id}              # HASH: state, failure_count, last_failure_time

# Workflow State (Phase 2/3)
hermes:orchestrator:workflows:{workflow_id}          # HASH: field=data, value=JSON(WorkflowExecution)
hermes:orchestrator:workflows:index                  # SET: workflow IDs

# Pub/Sub
hermes:orchestrator:events                          # CHANNEL: task events (submitted, completed, failed)
```

### Why Redis Stream Instead of Sorted Set

The previous design used `ZADD`/`BZPOPMIN` (Sorted Set) for the task queue. This is
**unreliable** — if the orchestrator pops a task and crashes before processing, that task
is permanently lost.

Redis Stream (`XADD`/`XREADGROUP`/`XACK`) provides:

| Feature | Sorted Set | Stream |
|---------|-----------|--------|
| Consumer acknowledgment | No | Yes (XACK) |
| Crash recovery | Lost messages | Pending entries reclaimable via XPENDING/XCLAIM |
| Consumer groups | Manual | Built-in |
| Blocking read | BZPOPMIN | XREADGROUP with BLOCK |
| Message ordering | By score | By insertion time (MILLIisecond precision) |

This pattern is adapted from the existing `swarm/messaging.py` module, which uses a
**hybrid** of Redis Streams (task delivery via xadd/xreadgroup), Pub/Sub (advisory notifications),
and plain list keys + blpop (result collection). The orchestrator uses Streams only for task
queuing — result collection happens via SSE event consumption, not Redis blpop.

### Task Producer/Consumer Pattern

```python
# Producer: submit task to stream
async def enqueue_task(self, task: Task) -> None:
    fields = {
        "task_id": task.task_id,
        "priority": str(task.priority),
        "prompt": task.prompt,
        "model_id": task.model_id,
        "metadata": json.dumps(task.metadata),
        "created_at": str(task.created_at),
    }
    await self._redis.xadd(
        "hermes:orchestrator:tasks:stream",
        fields,
        maxlen=10000,
        approximate=True,
    )
    # Also store full task details
    await self._redis.hset(
        f"hermes:orchestrator:tasks:{task.task_id}",
        "data", json.dumps(asdict(task)),
    )

# Consumer: read and process tasks
async def consume_tasks(self, consumer_name: str = "worker-1") -> None:
    # Ensure consumer group exists
    try:
        await self._redis.xgroup_create(
            "hermes:orchestrator:tasks:stream",
            "orchestrator.workers",
            id="0",
        )
    except Exception:
        pass  # Group already exists

    while True:
        result = await self._redis.xreadgroup(
            "orchestrator.workers",
            consumer_name,
            {"hermes:orchestrator:tasks:stream": ">"},
            count=1,
            block=5000,
        )
        if not result:
            continue

        for stream_name, messages in result:
            for msg_id, fields in messages:
                task_id = fields["task_id"]
                try:
                    await self._process_task(task_id)
                except Exception as e:
                    logger.error("Task %s processing failed: %s", task_id, e)
                    # Ensure task is marked failed before acking, so it's not silently lost
                    try:
                        await self._task_store.update(task_id, status="failed", error=str(e))
                    except Exception:
                        logger.error("Failed to mark task %s as failed", task_id)
                # Acknowledge after task is definitively resolved (done or failed)
                await self._redis.xack(
                    "hermes:orchestrator:tasks:stream",
                    "orchestrator.workers",
                    msg_id,
                )
```

### TTL Strategy

| Key | TTL | Reason |
|-----|-----|--------|
| `health:{agent_id}` | 60s | Must be refreshed by health check loop |
| `results:{task_id}` | 604800s (7 days) | Results available for a week, then auto-cleaned |
| `tasks:{task_id}` | No TTL | Tasks persist until explicitly deleted or GC |
| `circuit:{agent_id}` | No TTL | Circuit state must survive restarts |
| `tasks:stream` | MAXLEN 10000 | Stream trimmed to prevent unbounded growth |

### Crash Recovery

On orchestrator restart:

1. **Claim pending stream messages**: Use `XPENDING` + `XCLAIM` to reclaim tasks that
   were read but not acknowledged before the crash.
2. **Check in-flight tasks**: Load tasks with status `executing` or `streaming`.
3. **Verify gateway pod age**: If the assigned gateway's pod `creationTimestamp` is newer
   than the task's `created_at`, the gateway was rebuilt and the task is lost — mark failed.
4. **Re-queue all in-flight tasks**: SSE streams cannot be reconnected after orchestrator crash
   (the gateway does not buffer events). All in-flight tasks must be re-queued:
   - If gateway is alive AND same pod: re-queue without incrementing retry_count
     (orchestrator crash, not task failure).
   - If gateway is alive but different pod: re-queue without incrementing retry_count
     (gateway was rebuilt, but may have completed the task — result will be lost).
   - If gateway is offline: re-queue with retry_count +1 (agent unavailable).

```python
async def recover_in_flight_tasks(self) -> None:
    """Recover tasks that were in-flight when the orchestrator crashed."""
    # 1. Reclaim pending stream messages
    pending = await self._redis.xpending_range(
        "hermes:orchestrator:tasks:stream",
        "orchestrator.workers",
        min=0, max="+", count=100,
    )
    if pending:
        ids = [p["message_id"] for p in pending]
        await self._redis.xclaim(
            "hermes:orchestrator:tasks:stream",
            "orchestrator.workers",
            "recovery-worker",
            min_idle_time=30000,  # 30s idle = crashed consumer
            message_ids=ids,
        )
        # Re-process claimed messages
        for msg_id in ids:
            msg = await self._redis.xrange(
                "hermes:orchestrator:tasks:stream", min=msg_id, max=msg_id
            )
            if msg:
                task_id = msg[0][1].get("task_id")
                await self._requeue_task_by_id(task_id)

    # 2. Check in-flight tasks
    tasks = await self._task_store.list_by_status(
        ["assigned", "executing", "streaming"]
    )
    for task in tasks:
        agent = await self._registry.get(task.assigned_agent)
        if not agent or agent.status == "offline":
            task.assigned_agent = None
            task.status = "queued"
            task.retry_count += 1  # Agent gone, count as attempt
            await self._task_store.update(task)
            continue

        # Check if gateway pod was rebuilt
        pod_age_ok = await self._check_pod_age(task)
        if not pod_age_ok:
            task.status = "failed"
            task.error = "Gateway pod rebuilt during orchestrator downtime"
            await self._task_store.update(task)
            continue

        # Gateway alive, same pod — re-queue without counting retry
        # SSE stream cannot be reconnected after orchestrator crash
        task.assigned_agent = None
        task.status = "queued"
        # Do NOT increment retry_count — orchestrator crash, not task failure
        await self._task_store.update(task)
```

---

## 9. Workflow Engine

### Phase 2: Sequential and Parallel

The workflow engine extends the existing `swarm/workflow.py` patterns but targets
the `/v1/runs` and `/v1/responses` APIs instead of Redis Streams.

For workflow steps that chain outputs, use `/v1/responses` (synchronous, SQLite-persisted)
instead of `/v1/runs` — this provides a retrievable `response_id` for each step.

```python
class OrchestratorWorkflowEngine:
    """Executes multi-step workflows by dispatching tasks through the orchestrator."""

    async def execute_sequential(
        self, workflow: WorkflowDef, execution: WorkflowExecution
    ) -> None:
        for step in workflow.steps:
            if self._check_timeout(execution):
                execution.status = "failed"
                execution.error = "Workflow timeout exceeded"
                return

            # Resolve template variables from previous step results
            prompt = self._formatter.format(
                step.prompt_template,
                **execution.step_results,
            )

            # Submit task via /v1/responses (sync, for structured output)
            result = await self._submit_and_wait(
                prompt=prompt,
                instructions=step.instructions,
                timeout_seconds=step.timeout_seconds,
            )

            execution.step_results[step.id] = StepResult(
                step_id=step.id,
                status="completed" if result else "failed",
                output=result.content if result else None,
                error=result.error if not result else None,
            )

            if not result or result.status == "failed":
                execution.status = "failed"
                execution.error = f"Step {step.id} failed: {result.error}"
                return
```

### Phase 3: DAG with Structured Result Passing

DAG execution uses the existing topological sort from `swarm/workflow.py`:

```python
async def execute_dag(
    self, workflow: WorkflowDef, execution: WorkflowExecution
) -> None:
    layers = _topological_sort(workflow.steps)
    for layer in layers:
        if self._check_timeout(execution):
            execution.status = "failed"
            return

        # Run all steps in this layer concurrently
        tasks = []
        for step_id in layer:
            step = step_map[step_id]
            prompt = self._formatter.format(step.prompt_template, **execution.step_results)
            tasks.append(self.submit_task(prompt, step.model_id))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        for step_id, result in zip(layer, results):
            if isinstance(result, Exception):
                execution.step_results[step_id] = StepResult(
                    step_id=step_id, status="failed", error=str(result)
                )
            else:
                execution.step_results[step_id] = result
```

### Safe Template Formatting

Reuse the `_SafeFormat` class from `swarm/workflow.py` which:
- Supports `{step_id.output}` variable syntax.
- Escapes braces in output to prevent double-interpretation.
- Rejects `__xxx__` dunder patterns to prevent SSTI.

---

## 10. Security

### 10.1 Authentication

The orchestrator requires API key authentication on all endpoints:

```python
import hmac
import os

# Startup validation — refuse to start without a key
ORCHESTRATOR_API_KEY = os.environ.get("ORCHESTRATOR_API_KEY", "")
if not ORCHESTRATOR_API_KEY:
    raise SystemExit("FATAL: ORCHESTRATOR_API_KEY environment variable is required")

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    if request.url.path in ("/health", "/metrics"):
        return await call_next(request)

    auth = request.headers.get("Authorization", "")
    expected = f"Bearer {ORCHESTRATOR_API_KEY}"
    if not hmac.compare_digest(auth, expected):
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    return await call_next(request)
```

### 10.2 Redis Security

```yaml
# Redis configuration (mounted via ConfigMap as /etc/redis/redis.conf)
requirepass ${REDIS_PASSWORD}
protected-mode yes
bind 0.0.0.0
port 6379
appendonly yes
appendfsync everysec
# Disable dangerous commands (must be in config file, not CLI args)
rename-command FLUSHDB ""
rename-command FLUSHALL ""
rename-command DEBUG ""
```

**Note:** `rename-command` can only be set via configuration file, not command-line arguments.
Create a ConfigMap with the above content and mount it into the Redis container:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: redis-config
  namespace: hermes-agent
data:
  redis.conf: |
    requirepass ${REDIS_PASSWORD}
    protected-mode yes
    bind 0.0.0.0
    port 6379
    appendonly yes
    appendfsync everysec
    rename-command FLUSHDB ""
    rename-command FLUSHALL ""
    rename-command DEBUG ""
```

Connection string: `redis://:${REDIS_PASSWORD}@hermes-redis:6379/0`

**Note:** Updating Redis to require a password requires updating all existing gateway
deployments' `SWARM_REDIS_URL` to include the password:
`redis://:${REDIS_PASSWORD}@hermes-redis:6379/0`.

### 10.3 Network Policies

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: orchestrator-egress
  namespace: hermes-agent
spec:
  podSelector:
    matchLabels:
      app: hermes-orchestrator
  policyTypes:
    - Egress
  egress:
    # Allow DNS resolution (UDP and TCP)
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: kube-system
      ports:
        - protocol: UDP
          port: 53
        - protocol: TCP
          port: 53
    # Allow Redis within namespace
    - to:
        - podSelector:
            matchLabels:
              app: hermes-redis
      ports:
        - protocol: TCP
          port: 6379
    # Allow gateway pods within namespace
    - to:
        - podSelector:
            matchLabels:
              app.kubernetes.io/component: gateway
      ports:
        - protocol: TCP
          port: 8642
    # Allow K8s API server (specific CIDR, not 0.0.0.0/0)
    # IMPORTANT: Replace with your cluster's actual API server CIDR.
    # Use `kubectl get endpoints kubernetes -o wide` to find the API server IPs.
    - to:
        - ipBlock:
            cidr: 172.32.0.0/16    # Replace with actual cluster CIDR
      ports:
        - protocol: TCP
          port: 6443
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: orchestrator-ingress
  namespace: hermes-agent
spec:
  podSelector:
    matchLabels:
      app: hermes-orchestrator
  policyTypes:
    - Ingress
  ingress:
    # Only allow from ingress controller
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: ingress-nginx
      ports:
        - protocol: TCP
          port: 8080
    # Allow health checks from K8s
    - from:
        - ipBlock:
            cidr: 10.0.0.0/8
      ports:
        - protocol: TCP
          port: 8080
```

### 10.4 TLS

TLS terminates at the ingress controller. Internal cluster traffic is plaintext (mesh networking can be added later with Cilium or Istio):

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: hermes-orchestrator
  namespace: hermes-agent
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
spec:
  ingressClassName: nginx
  tls:
    - hosts:
        - orchestrator.example.com
      secretName: orchestrator-tls
  rules:
    - host: orchestrator.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: hermes-orchestrator
                port:
                  number: 8080
```

### 10.5 CORS Configuration

```python
import os

# Read from environment variable, comma-separated
_cors_origins = os.environ.get("CORS_ALLOWED_ORIGINS", "").split(",")
_cors_origins = [o.strip() for o in _cors_origins if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)
```

### 10.6 Prompt Injection Protection

Prompt injection is an inherent risk when accepting user-provided prompts. The orchestrator
uses a **layered defense** rather than relying solely on pattern matching:

**Layer 1: Input sanitization** (always applied)
```python
def sanitize_prompt(prompt: str) -> str:
    """Strip control characters and normalize whitespace."""
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", prompt)
    return cleaned.strip()
```

**Layer 2: Template sandboxing** (for workflow templates)
- The `_SafeFormat` class rejects `__xxx__` dunder patterns and escapes braces.

**Layer 3: Gateway-side isolation** (architectural)
- The orchestrator does NOT handle LLM interaction directly. The gateway manages the
  agent's system prompt and tool permissions. Even if a malicious prompt reaches the
  gateway, the agent's tool scope limits the blast radius.

**Layer 4: Output monitoring** (observability)
- Log task prompts at INFO level for audit review.
- Rate-limit per-client task submissions to prevent automated abuse.

### 10.7 Secrets Management

- **No `.env` files committed to git.** All secrets come from Kubernetes Secrets.
- **Gateway API keys**: Stored in `hermes-db-secret` Kubernetes Secret.
- **Redis password**: Stored in `hermes-redis-secret` Kubernetes Secret (separate from orchestrator key).
- **Orchestrator API key**: Stored in `hermes-orchestrator-secret` Kubernetes Secret.
- **LLM provider keys**: Stored per-gateway in `hermes-db-secret`.

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: hermes-orchestrator-secret
  namespace: hermes-agent
type: Opaque
stringData:
  ORCHESTRATOR_API_KEY: "<generated-32-byte-hex>"
---
apiVersion: v1
kind: Secret
metadata:
  name: hermes-redis-secret
  namespace: hermes-agent
type: Opaque
stringData:
  REDIS_PASSWORD: "<generated-32-byte-hex>"
```

Separate secrets for independent rotation.

---

## 11. Deployment

### K8s Manifest: Orchestrator Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: hermes-orchestrator
  namespace: hermes-agent
  labels:
    app: hermes-orchestrator
    app.kubernetes.io/component: orchestrator
spec:
  replicas: 1  # Single replica -- state in Redis, tasks recover on restart
               # Multi-replica path: Redis Stream consumer groups support multiple consumers natively.
               # Scale to 2+ replicas by increasing this count; each replica joins the same consumer
               # group and claims tasks independently. No leader election needed.
  selector:
    matchLabels:
      app: hermes-orchestrator
  template:
    metadata:
      labels:
        app: hermes-orchestrator
        app.kubernetes.io/component: orchestrator
    spec:
      serviceAccountName: hermes-orchestrator
      containers:
        - name: orchestrator
          image: hermes-orchestrator:latest
          imagePullPolicy: IfNotPresent
          ports:
            - containerPort: 8080
          env:
            - name: ORCHESTRATOR_API_KEY
              valueFrom:
                secretKeyRef:
                  name: hermes-orchestrator-secret
                  key: ORCHESTRATOR_API_KEY
            - name: REDIS_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: hermes-redis-secret
                  key: REDIS_PASSWORD
            - name: REDIS_URL
              value: "redis://:$(REDIS_PASSWORD)@hermes-redis:6379/0"
            - name: K8S_NAMESPACE
              value: "hermes-agent"
            - name: GATEWAY_API_KEY
              valueFrom:
                secretKeyRef:
                  name: hermes-db-secret
                  key: api_key
            - name: LOG_LEVEL
              value: "INFO"
          resources:
            requests:
              cpu: 100m
              memory: 512Mi
            limits:
              cpu: 1000m
              memory: 1024Mi
          readinessProbe:
            httpGet:
              path: /health
              port: 8080
            initialDelaySeconds: 5
            periodSeconds: 10
            timeoutSeconds: 5
            failureThreshold: 3
          livenessProbe:
            httpGet:
              path: /health
              port: 8080
            initialDelaySeconds: 15
            periodSeconds: 30
            timeoutSeconds: 10
            failureThreshold: 5
```

**Changes from previous revision:**
- Redis password from separate `hermes-redis-secret` (not shared with orchestrator key)
- Memory limits increased to 1024Mi (each SSE connection holds an aiohttp session)
- Probe timeouts increased (health endpoint now checks Redis connectivity)
- `/health` endpoint checks Redis connectivity:

```python
@app.get("/health")
async def health():
    checks = {"status": "ok"}
    try:
        await redis.ping()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {e}"
        checks["status"] = "degraded"
    return checks
```
---
apiVersion: v1
kind: Service
metadata:
  name: hermes-orchestrator
  namespace: hermes-agent
spec:
  type: ClusterIP
  ports:
    - name: api
      port: 8080
      targetPort: 8080
  selector:
    app: hermes-orchestrator
```

### RBAC for Orchestrator

The orchestrator needs K8s API access to discover gateway pods:

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: hermes-orchestrator
  namespace: hermes-agent
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: hermes-orchestrator
  namespace: hermes-agent
rules:
  # Read pod information for gateway discovery
  - apiGroups: [""]
    resources: ["pods"]
    verbs: ["get", "list", "watch"]
  # Read services for gateway endpoint discovery
  - apiGroups: [""]
    resources: ["services"]
    verbs: ["get", "list"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: hermes-orchestrator
  namespace: hermes-agent
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: hermes-orchestrator
subjects:
  - kind: ServiceAccount
    name: hermes-orchestrator
    namespace: hermes-agent
```

### Redis Deployment with Authentication and Persistence

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: hermes-redis
  namespace: hermes-agent
spec:
  replicas: 1
  selector:
    matchLabels:
      app: hermes-redis
  template:
    metadata:
      labels:
        app: hermes-redis
    spec:
      containers:
        - name: redis
          image: redis:7-alpine
          args: ["redis-server", "/etc/redis/redis.conf"]
          env:
            - name: REDIS_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: hermes-redis-secret
                  key: REDIS_PASSWORD
            - name: REDISCLI_AUTH
              valueFrom:
                secretKeyRef:
                  name: hermes-redis-secret
                  key: REDIS_PASSWORD
          ports:
            - containerPort: 6379
          volumeMounts:
            - name: redis-data
              mountPath: /data
            - name: redis-config
              mountPath: /etc/redis
          resources:
            requests:
              cpu: 50m
              memory: 256Mi
            limits:
              cpu: 500m
              memory: 512Mi
          readinessProbe:
            exec:
              command: ["sh", "-c", "redis-cli -a \"$REDISCLI_AUTH\" ping | grep -q PONG"]
            initialDelaySeconds: 5
            periodSeconds: 10
      volumes:
        - name: redis-data
          persistentVolumeClaim:
            claimName: hermes-redis-pvc
        - name: redis-config
          configMap:
            name: redis-config
---
apiVersion: v1
kind: Service
metadata:
  name: hermes-redis
  namespace: hermes-agent
spec:
  type: ClusterIP
  ports:
    - port: 6379
      targetPort: 6379
  selector:
    app: hermes-redis
```

**Changes from previous revision:**
- AOF persistence (`appendonly yes`) — Redis restart no longer loses state
- PVC mount for data durability across pod restarts
- `REDISCLI_AUTH` env var for probe (avoids password in process list)
- Increased memory to 384mb/512mb (circuit breaker + task queue data must not be evicted)
- Password from separate `hermes-redis-secret`

**Important:** When adding authentication to Redis, all existing gateway deployments must
update their `SWARM_REDIS_URL` from `redis://hermes-redis:6379/0` to
`redis://:${REDIS_PASSWORD}@hermes-redis:6379/0`.

---

## 12. Implementation Phases

### MVP: Task Router via `/v1/runs` (1-2 weeks)

**Goal**: Accept task submissions, select a gateway, submit via `/v1/runs`, return results.

Simplified from previous revision because gateway already provides the async execution layer.

| Component | Description | Effort |
|-----------|-------------|--------|
| Orchestrator API server | FastAPI app with auth middleware + /health (with Redis check) | 1 day |
| Task data model + Redis Stream store | Task CRUD with Redis Stream persistence | 1 day |
| Agent discovery (K8s) | Pod discovery via list + `/v1/models` query | 1 day |
| Agent selector | Load-aware selection + circuit breaker | 1 day |
| Task executor | `POST /v1/runs` → consume SSE events → extract result | 2 days |
| Health monitor | Adaptive polling + task-failure-as-signal | 1 day |
| Crash recovery | Stream consumer reclaim + in-flight task recovery | 1 day |
| K8s manifests | Deployment, RBAC, NetworkPolicy, Secrets | 1 day |
| Testing | Unit + integration tests | 2 days |

**MVP delivers**:
- `POST /api/v1/tasks` → agent selection → `POST /v1/runs` → SSE consume → result
- `GET /api/v1/tasks/{id}` with structured result
- `GET /api/v1/agents` with health and circuit state
- Automatic agent discovery and health tracking
- Circuit breaker prevents dispatch to failing agents
- Tasks survive orchestrator restarts (Redis Stream XACK)
- Webhook callback for task completion (avoids polling)

### Phase 2: Workflows + Structured Extraction (2 weeks)

| Component | Description |
|-----------|-------------|
| Sequential workflows | Chain steps via `/v1/responses`, output feeds next step |
| Parallel workflows | Run independent steps concurrently via `/v1/runs` |
| Workflow API | `POST /api/v1/workflows`, `GET /api/v1/workflows/{id}` |
| Parse extraction strategy | Regex + JSON extraction from free-form responses |
| Safe template formatting | Reuse `_SafeFormat` from `swarm/workflow.py` |
| K8s watch for agent discovery | Replace list polling with watch for near-real-time |

### Phase 3: DAG Engine + Observability + Advanced Extraction (2 weeks)

| Component | Description |
|-----------|-------------|
| DAG execution | Topological sort layers, concurrent within layer |
| LLM extraction strategy | Lightweight model for structured extraction from free-form text |
| Prometheus metrics | Task throughput, latency, agent utilization, circuit breaker state |
| Structured logging | JSON logging with task_id as correlation ID |
| Rate limiting | Per-client rate limits on task submission |
| Result Extraction as separate service | If LLM extraction is frequently needed |

---

## 13. Key Files Reference

### Gateway Files (Primary Integration Surface)

| File | Purpose | Key Endpoints |
|------|---------|---------------|
| `gateway/platforms/api_server.py` | API server with all endpoints | `POST /v1/runs`, `GET /v1/runs/{id}/events`, `POST /v1/responses`, `GET /v1/responses/{id}`, `GET /v1/models`, `GET /health` |
| `run_agent.py` | AIAgent class | `run_conversation()` — the core execution engine shared by all endpoints |
| `gateway/run.py` | Gateway runner | `_resolve_runtime_agent_kwargs`, `_resolve_gateway_model` |

### Existing Swarm Module (Pattern Reference)

| File | Purpose | What to Reuse |
|------|---------|---------------|
| `swarm/workflow.py` | Workflow engine | `_SafeFormat`, `_topological_sort`, `StepResult` patterns |
| `swarm/circuit_breaker.py` | Circuit breaker | Reuse directly with tuned parameters |
| `swarm/messaging.py` | Redis Streams messaging | Pattern for XADD/XREADGROUP/XACK consumer groups |
| `swarm/client.py` | Swarm client | Pattern for agent registration |
| `swarm/crew_store.py` | Workflow definitions | Data model patterns |

### Admin System (Coexistence)

| File | Purpose | Relationship |
|------|---------|-------------|
| `admin/backend/main.py` | Admin API server | Admin manages gateway lifecycle; orchestrator is read-only consumer |
| `admin/backend/swarm_routes.py` | Swarm dashboard | May share agent health data via Redis |

### New Files to Create

```
hermes-orchestrator/
  __init__.py
  main.py                  # FastAPI app, startup, shutdown
  config.py                # Environment-based configuration
  models/
    task.py                # Task, TaskResult, RunResult data models
    agent.py               # AgentProfile, AgentCapability
    workflow.py             # WorkflowDef, WorkflowExecution (adapted from swarm)
  stores/
    redis_task_store.py     # Redis Stream-backed task persistence
    redis_agent_registry.py # Redis-backed agent registry
  services/
    agent_discovery.py      # K8s pod + /v1/models capability discovery
    health_monitor.py       # Adaptive health checking
    task_executor.py        # POST /v1/runs + SSE consume + result extraction
    workflow_engine.py      # Sequential/parallel/DAG execution
    agent_selector.py       # Agent selection with circuit breaker
  middleware/
    auth.py                 # API key authentication (hmac.compare_digest)
    cors.py                 # CORS configuration from env var
  k8s/
    deployment.yaml
    service.yaml
    rbac.yaml
    networkpolicy.yaml
    ingress.yaml
    redis.yaml
    secrets.yaml
```

---

## Appendix A: Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ORCHESTRATOR_API_KEY` | Yes | - | API key for authenticating requests (startup fails if empty) |
| `REDIS_URL` | Yes | - | Redis connection string with password |
| `REDIS_PASSWORD` | Yes | - | Redis password (used to construct REDIS_URL) |
| `K8S_NAMESPACE` | No | `hermes-agent` | Kubernetes namespace for pod discovery |
| `GATEWAY_API_KEY` | Yes | - | API key for authenticating to gateway pods |
| `GATEWAY_PORT` | No | `8642` | Gateway HTTP port |
| `GATEWAY_MAX_CONCURRENT_RUNS` | No | `10` | Max concurrent runs per gateway. Note: gateway currently hardcodes `_MAX_CONCURRENT_RUNS=10` in `api_server.py:1509`. The orchestrator uses this value for load-aware agent selection; it does not change gateway behavior. If gateway makes this configurable in the future, update both to match. |
| `TASK_MAX_WAIT` | No | `600.0` | Max seconds to wait for task completion |
| `HEALTH_BASE_INTERVAL` | No | `5.0` | Base interval for health checks |
| `AGENT_MAX_CONCURRENT` | No | `10` | Default max concurrent tasks per agent (matches gateway limit) |
| `CIRCUIT_FAILURE_THRESHOLD` | No | `3` | Failures before circuit opens |
| `CIRCUIT_RECOVERY_TIMEOUT` | No | `30.0` | Seconds before circuit half-open |
| `LOG_LEVEL` | No | `INFO` | Logging level |
| `CORS_ALLOWED_ORIGINS` | No | `""` | Comma-separated allowed CORS origins |

## Appendix B: Error Codes

| Code | HTTP Status | Meaning |
|------|-------------|---------|
| `NO_AGENT_AVAILABLE` | 503 | No agent matches the requested capability |
| `ALL_AGENTS_CIRCUIT_OPEN` | 503 | All candidate agents have open circuit breakers |
| `GATEWAY_OVERLOADED` | 503 | Gateway returned 429 (concurrent run limit) |
| `TASK_TIMEOUT` | 408 | Task exceeded timeout waiting for completion |
| `TASK_NOT_FOUND` | 404 | Task ID does not exist |
| `AGENT_NOT_FOUND` | 404 | Agent ID does not exist |
| `TASK_ALREADY_COMPLETED` | 409 | Cannot cancel a completed task |
| `GATEWAY_ERROR` | 502 | Gateway returned an error during task execution |
| `INVALID_PROMPT` | 400 | Prompt validation failed |
| `RATE_LIMITED` | 429 | Client exceeded task submission rate limit |
