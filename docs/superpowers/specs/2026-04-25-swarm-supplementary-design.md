# Swarm Collaboration — Technical Supplementary Design

> **Supplements**: `2026-04-25-swarm-collaboration-design.md`
> **Status**: Draft
> **Date**: 2026-04-25
> **Addresses**: 11 CRITICAL + 23 HIGH issues from five-expert review

This document provides detailed technical designs for the gaps identified in the original swarm collaboration design. Each chapter is self-contained and maps to specific review findings.

---

## Table of Contents

1. [Sync/Async Bridge Strategy](#1-syncasync-bridge-strategy)
2. [Message Transport Layer Redesign](#2-message-transport-layer-redesign)
3. [Exactly-Once Semantics](#3-exactly-once-semantics)
4. [Redis Deployment Architecture](#4-redis-deployment-architecture)
5. [Connection Management](#5-connection-management)
6. [Redis Monitoring and Operations](#6-redis-monitoring-and-operations)
7. [Circuit Breaker and Graceful Degradation](#7-circuit-breaker-and-graceful-degradation)
8. [Frontend Interaction Specifications](#8-frontend-interaction-specifications)
9. [State Management Architecture](#9-state-management-architecture)
10. [Real-Time Transport Protocol](#10-real-time-transport-protocol)
11. [Navigation and Routing Extension](#11-navigation-and-routing-extension)
12. [Visual Design Specification](#12-visual-design-specification)

---

## 1. Sync/Async Bridge Strategy

**Addresses**: C1 (Async/Sync Boundary), H2 (Thread Safety), H3 (Graceful Shutdown)

### 1.1 Problem Statement

The agent loop (`run_agent.py` `AIAgent.run_conversation()`) is entirely synchronous. The existing `_run_async()` in `model_tools.py` blocks the calling thread until the coroutine completes. For swarm delegation, a tool call may block for 30-120 seconds waiting for another agent to execute a task and return a result. During this time, the heartbeat thread starves, the agent appears offline to the gateway, and cascading failures occur.

The existing `delegate_tool.py` already solves this exact problem via a three-thread architecture: a ThreadPoolExecutor for the child agent, a daemon heartbeat thread, and the calling tool executor thread.

### 1.2 Three-Thread Architecture

```
Gateway Process
├── asyncio Event Loop (main)
│   └── run_in_executor → run_sync() in thread pool
│       └── Tool Executor Thread
│           ├── AIAgent.run_conversation() [synchronous]
│           │   └── handle_function_call("swarm_delegate", ...)
│           │       └── swarm_delegate_handler() [SYNC, is_async=False]
│           │           ├── Start heartbeat daemon thread
│           │           ├── Submit _swarm_delegate_worker to inner ThreadPoolExecutor
│           │           └── future.result(timeout=120) [BLOCKS]
│           │               └── Swarm Worker Thread (owns asyncio loop)
│           │                   ├── XADD task to target agent's stream
│           │                   ├── PUBLISH advisory notification
│           │                   └── BLPOP on result queue (blocking async wait)
│           └── Heartbeat Thread (daemon)
│               └── Every 30s: _touch_activity() + Redis SETEX heartbeat
```

### 1.3 Sequence: Swarm Delegate Call

```
1. LLM calls swarm_delegate(goal, capability)
2. registry.dispatch → swarm_delegate_handler (is_async=False)
3. Handler spawns heartbeat thread + inner worker thread
4. Worker thread runs own event loop:
   a. XADD to hermes:stream:agent.{target}.tasks
   b. PUBLISH advisory on swarm.advisory.task
   c. BLPOP on hermes:swarm:result:{task_id} with periodic cancel check
   d. Return result or timeout error
5. Handler collects future.result(timeout+10)
6. Heartbeat thread calls _touch_activity() every 30s
7. Result flows: worker → handler → registry.dispatch → agent loop
```

### 1.4 Key Design Decision

`swarm_delegate` is registered with **`is_async=False`**. It internally manages its own ThreadPoolExecutor, exactly replicating `delegate_tool.py`'s proven pattern. The `_run_async()` bridge is never invoked for swarm delegation.

| Scenario | Mechanism | Reason |
|----------|-----------|--------|
| Local async tools (web, mcp) | `_run_async()` via `_get_tool_loop()` | Short (<10s), no heartbeat risk |
| In-process subagent delegation | ThreadPoolExecutor (outer) + heartbeat thread | Long (up to 120s) |
| Swarm delegation | ThreadPoolExecutor (inner) + heartbeat thread | Long (up to 120s), Redis blocking |
| Swarm result collection | `_run_async()` inside worker thread only | Worker is already isolated |

### 1.5 Constants

| Constant | Value | Location |
|----------|-------|----------|
| `_SWARM_TIMEOUT` | 120 | `tools/swarm_tool.py` |
| `_HEARTBEAT_INTERVAL` | 30 | `tools/swarm_tool.py` |
| `_HEARTBEAT_TTL` | 60 | Redis key TTL |

### 1.6 Integration Points

- **`model_tools.py`**: Add `"tools.swarm_tool"` to `_modules` list
- **`tools/delegate_tool.py`**: Swarm heartbeat coexists with delegate heartbeat (both call `_touch_activity`)
- **`gateway/run.py`**: No changes needed; swarm handler's inner pool nests safely inside gateway's executor thread
- **`tools/registry.py`**: No changes; `is_async=False` means dispatch calls handler directly

---

## 2. Message Transport Layer Redesign

**Addresses**: C2 (Pub/Sub for point-to-point), H8 (No Consumer Groups), H9 (No Backpressure)

### 2.1 Transport Layer Separation

```
Advisory Layer (Pub/Sub)          Authoritative Layer (Streams)
─────────────────────────         ──────────────────────────────
Purpose: Real-time wake-up        Purpose: Durable task/result delivery
Semantics: fire-and-forget        Semantics: persistent, acknowledged
Loss: acceptable                  Loss: never (within retention)

Channels:                         Streams:
  swarm.advisory.task               hermes:stream:agent.{id}.tasks
  swarm.advisory.result             hermes:stream:agent.{id}.results
  swarm.advisory.online             hermes:stream:swarm.dlq
  swarm.advisory.offline
  swarm.advisory.cancel
```

### 2.2 Per-Agent Stream Lifecycle

```
Agent Startup:
  1. XGROUP CREATE hermes:stream:agent.{id}.tasks agent.{id}.worker 0 MKSTREAM
  2. Start consumer: XREADGROUP GROUP agent.{id}.worker consumer-1
     BLOCK 5000 COUNT 1 STREAMS hermes:stream:agent.{id}.tasks >

Agent Shutdown (graceful):
  1. XCLAIM all pending messages back
  2. XGROUP DESTROY hermes:stream:agent.{id}.tasks agent.{id}.worker

Agent Crash (no graceful shutdown):
  1. Supervisor detects heartbeat expiry
  2. Supervisor runs reclaim: XPENDING + XCLAIM for messages pending > N ms
  3. Reclaimed messages are re-dispatched or sent to DLQ
```

### 2.3 Complete Message Lifecycle

```
[Sending a Task]
  1. Generate task_id (UUID)
  2. SETNX hermes:swarm:dedup:{task_id} {sender_id} EX 300
  3. Backpressure check: GET hermes:swarm:depth:{target_id}
  4. XADD hermes:stream:agent.{target}.tasks * {fields} MAXLEN ~10000
  5. PUBLISH swarm.advisory.task {notification}

[Receiving and Processing]
  1. Advisory listener wakes on Pub/Sub
  2. XREADGROUP GROUP agent.{B}.worker consumer-1 BLOCK 5000
  3. Check dedup lock: GET hermes:swarm:dedup:{task_id}
  4. Execute task
  5a. Success → XADD result to sender's result stream, XACK task
  5b. Failure → XADD to DLQ stream, XACK task
  6. PUBLISH swarm.advisory.result {notification}

[Timeout Reclaim — every 30s on Supervisor]
  1. XPENDING per agent stream
  2. XCLAIM messages idle > 180s
  3. Check agent heartbeat: EXISTS hermes:heartbeat:{agent_id}
  4a. Agent alive → DLQ with "timeout while agent alive"
  4b. Agent dead → Re-dispatch to another capable agent
```

### 2.4 Backpressure

| Queue Depth | Action |
|-------------|--------|
| < 5 | Accept normally |
| 5-9 | Accept + log warning |
| >= 10 | REJECT with 503 + retry hint |

Redis key: `hermes:swarm:depth:{agent_id}`, TTL 120s, updated after every XREADGROUP/XACK cycle.

### 2.5 Message Format

All stream messages use flat string key-value fields (Redis Streams requirement). Nested structures are JSON-encoded. Every message includes `msg_version` for forward compatibility.

**Task message fields**: `msg_version`, `task_id`, `task_type`, `goal`, `capability`, `input_data`, `sender_id`, `priority` (0/1/2), `deadline_ts`, `max_tokens`, `trace_id`, `parent_msg_id`, `timestamp`

**Result message fields**: `msg_version`, `task_id`, `agent_id`, `status` (completed/failed/partial), `output`, `error`, `tokens_used`, `duration_ms`, `artifacts` (JSON), `timestamp`

### 2.6 Constants

| Constant | Value | Purpose |
|----------|-------|---------|
| `MSG_VERSION` | "1" | Schema version |
| `DEFAULT_STREAM_MAXLEN` | 10000 | Approximate trimming per stream |
| `RECLAIM_TIMEOUT_MS` | 180000 | 3 min before supervisor reclaims |
| `DEPTH_WARN_THRESHOLD` | 5 | Backpressure warning |
| `DEPTH_REJECT_THRESHOLD` | 10 | Backpressure rejection |
| `DLQ_STREAM` | `hermes:stream:swarm.dlq` | Dead letter queue |

---

## 3. Exactly-Once Semantics

**Addresses**: C3 (No deduplication), H5 (Task state machine)

### 3.1 Five-Layer Defense

```
Layer 1: SETNX Dedup Lock (sender side)
  Key: hermes:swarm:dedup:{task_id}, TTL: 300s
  Prevents duplicate XADD for the same task_id

Layer 2: Execution Guard (receiver side)
  Key: hermes:swarm:exec:{task_id}, Value: {agent_id, started_at, status}, TTL: 600s
  Prevents duplicate execution of the same task

Layer 3: Idempotent Result Writing
  Result RPUSH to hermes:swarm:result:{task_id} (per-task list, single consumer BLPOP)

Layer 4: Task Cancellation
  Key: hermes:swarm:cancel:{task_id}, TTL: 300s
  Checked before and during execution

Layer 5: DLQ Safety Net
  Stream: hermes:stream:swarm.dlq
  Human or automated review can re-dispatch or drop
```

### 3.2 Task Cancellation Flow

```
Supervisor / Sender:
  1. SET hermes:swarm:cancel:{task_id} {reason} EX 300
  2. PUBLISH swarm.advisory.cancel {task_id, reason}

Target Agent:
  Before execution: if EXISTS cancel key → skip, return status:"cancelled"
  During execution: if EXISTS cancel key → interrupt, return partial result
  After execution: if EXISTS cancel key → discard result
```

### 3.3 DLQ Processing Rules

| Reason | Action |
|--------|--------|
| timeout + agent alive | retry_count < 3: re-dispatch to same; >= 3: escalate |
| timeout + agent dead | Find another capable agent, re-dispatch |
| error | Log, notify sender, do NOT retry |
| cancelled | Discard silently |
| overflow | Wait 30s, retry to same or different agent |

### 3.4 Idempotency Principles

1. **Sender idempotency**: `publish_task()` uses SETNX; duplicate XADD is blocked
2. **Receiver idempotency**: Check execution guard before processing; skip if "running", resend cached result if "completed"
3. **Result write idempotency**: Per-task list with BLPOP single consumer
4. **State transition idempotency**: Compare-and-set; completed→completed is no-op
5. **Tool side-effect idempotency**: "write file" overwrites same content; "create PR" checks existence first

### 3.5 Constants

| Constant | Value | Purpose |
|----------|-------|---------|
| `DEDUP_TTL` | 300s | Send-side dedup lock lifetime |
| `EXEC_GUARD_TTL` | 600s | Execution guard (2x task timeout) |
| `CANCEL_TTL` | 300s | Cancel flag lifetime |
| `RESULT_TTL` | 300s | Result list lifetime |
| `MAX_DLQ_RETRIES` | 3 | DLQ retry cap before escalation |

---

## 4. Redis Deployment Architecture

**Addresses**: C4 (Redis SPOF), H7 (Trace data no TTL)

### 4.1 Phase 1: Single Node + AOF + PVC (3-10 agents)

**Redis Config** (`kubernetes/swarm/redis-config.yaml`):

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: hermes-redis-config
  namespace: hermes-agent
data:
  redis.conf: |
    bind 0.0.0.0
    port 6379
    protected-mode no
    timeout 300
    tcp-keepalive 60

    # Persistence: AOF every-second fsync
    appendonly yes
    appendfilename "appendonly.aof"
    appendfsync everysec
    auto-aof-rewrite-percentage 100
    auto-aof-rewrite-min-size 64mb

    # RDB: snapshot every 15 min
    save 900 1
    save 300 10
    save 60 10000
    rdbcompression yes
    dir /data

    # Memory
    maxmemory 384mb
    maxmemory-policy allkeys-lru

    # Limits
    maxclients 200
    slowlog-log-slower-than 10000
    slowlog-max-len 128
```

**PersistentVolume** (`kubernetes/swarm/redis-pv.yaml`): Local PV 5Gi with `Retain` reclaim policy, bound to specific node via `nodeAffinity`.

**Deployment** (`kubernetes/swarm/redis.yaml`): Single replica with `Recreate` strategy, password from Secret, readiness/liveness probes via `redis-cli ping`, sidecar `oliver006/redis_exporter` for Prometheus metrics. Resource limits: 500m CPU / 512Mi memory.

**NetworkPolicy**: Allow ingress only from within `hermes-agent` namespace.

**Capacity estimate**: ~200MB/day; 5Gi supports ~25 days with application-layer TTL cleanup.

### 4.2 Phase 2: Redis Sentinel (10-20 agents)

Architecture: 1 Master (StatefulSet + PVC) + 3 Sentinel pods (Deployment).

Sentinel configuration:
- `down-after-milliseconds`: 10000
- `failover-timeout`: 30000
- `parallel-syncs`: 1
- Quorum: 2

Client connection (redis-py Sentinel mode):

```python
from redis.asyncio.sentinel import Sentinel
sentinel = Sentinel([(host, 26379)])
redis = sentinel.master_for('hermes-master', password=pwd)
```

**Limitation**: With 1 Master and no Slave, Sentinel cannot auto-promote. Its value is detecting failure + triggering K8s Pod restart + client auto-discovery of recovered Master.

### 4.3 Phase 3: NATS JetStream Evaluation (20+ agents)

Migration trigger thresholds:
- Agent count > 20
- Stream throughput > 2000 msg/s
- Need for guaranteed exactly-once delivery
- Redis memory > 2GB

Migration path: Dual-write transition period (`redis-only` → `dual-write` → `nats-primary` → `nats-only`).

---

## 5. Connection Management

**Addresses**: H4 (Connection pool), M8 (Connection topology)

### 5.1 Per-Agent Connection Topology

```
Agent Process
├── Pool A: General (max_connections=4)
│   Registry reads/writes, heartbeat, shared memory, trace writes
├── Connection B: Pub/Sub Dedicated (1 connection)
│   Subscriptions to advisory channels (blocks the connection)
└── Connection C: Stream Consumer (1-2 connections)
    XREADGROUP, XACK, XPENDING (blocking reads)
```

### 5.2 Connection Pool Sizing Formula

```
general_pool_max = base(2) + max_concurrent_tasks * per_task(1)

Supervisor: general_pool_max = base + (max_tasks * per_task) + 4
  Extra for: registry scanning, latency tracking, broadcast, result aggregation
```

**10-agent cluster estimate**: 73 total connections (well within Redis `maxclients=200`).

| Component | Count | Connections Each | Total |
|-----------|-------|-----------------|-------|
| Worker Agent | 8 | 6 (4 pool + 1 pubsub + 1 stream) | 48 |
| Supervisor | 1 | 17 (11 pool + 1 pubsub + 2 streams + 3 extra) | 17 |
| Admin Panel | 1 | 4 | 4 |
| Monitoring | 2 | 2 | 4 |

### 5.3 Timeout Configuration

All connections: `socket_timeout=5s`, `socket_connect_timeout=3s`, `retry_on_timeout=True`, `health_check_interval=15s`, TCP keepalive (idle=60s, interval=10s, count=3).

---

## 6. Redis Monitoring and Operations

**Addresses**: H10 (No message bus monitoring)

### 6.1 `/swarm/metrics` API Endpoint

```
GET /admin/api/swarm/metrics
Response: {
  timestamp, swarm_enabled,
  agents: [SwarmAgentProfile],
  agents_online, agents_offline, agents_busy,
  queues: { streams: [{stream_name, length, pending_count}], total_pending },
  redis_health: { connected, latency_ms, memory_used_percent, connected_clients,
                  uptime_seconds, aof_enabled, persistence_status, version },
  stalled_messages: [{stream, message_id, pending_duration_seconds}],
  tasks_submitted_last_5m, tasks_completed_last_5m, tasks_failed_last_5m,
  avg_task_duration_ms
}
```

### 6.2 Stalled Message Scanner

Runs every 60s on Supervisor. For each stream:
1. XPENDING to find unacknowledged messages
2. Messages idle > 300s (configurable) are "stalled"
3. If `delivered_count < 3`: XCLAIM + re-XADD as new message (retry)
4. If `delivered_count >= 3`: Move to dead-letter stream (`{stream}.dead`)

### 6.3 Redis Health Check Metrics

| Metric | Alert Threshold | Severity |
|--------|----------------|----------|
| `latency_ms` | > 10ms warn, > 50ms critical | WARN/CRIT |
| `memory_used_percent` | > 70% warn, > 85% critical | WARN/CRIT |
| `connected_clients` | > 150 warn, > 180 critical | WARN/CRIT |
| `aof_enabled` | false | CRITICAL |
| `aof_last_bgrewrite_status` | "err" | CRITICAL |
| `evicted_keys` | > 0 | WARN |
| `stream_length` | > 10000 | WARN |
| `stalled_messages` | > 5 warn, > 20 critical | WARN/CRIT |

### 6.4 Admin Panel: Redis Health Card Component

Shows in the Swarm Overview page: memory usage bar, client connection bar, uptime, AOF status, hit rate, queue depths per stream, and stalled message warnings. Uses existing `getBarColor` gradient (cyan→amber→red) for progress bars.

---

## 7. Circuit Breaker and Graceful Degradation

**Addresses**: H5 (Redis failure no fallback)

### 7.1 Circuit Breaker Pattern

States: CLOSED → OPEN (after 5 consecutive failures) → HALF_OPEN (after 30s recovery timeout) → CLOSED (after 2 consecutive successes).

```python
breaker = RedisCircuitBreaker(config=CircuitBreakerConfig(
    failure_threshold=5,
    success_threshold=2,
    recovery_timeout=30.0,
    timeout_per_call=3.0,
))
result = await breaker.call(redis.get, "some_key")  # Returns None if OPEN
```

Only connection-related errors (ConnectionError, TimeoutError, etc.) trigger the breaker. Non-connection errors (WRONGTYPE, etc.) propagate normally.

### 7.2 Graceful Degradation Flow

```
Agent starts with swarm.enabled=true
├── Redis PING succeeds? → YES: Register, start heartbeat, subscribe
│                          → NO: Enter standalone mode
│                                ├── Log WARNING
│                                ├── Disable swarm tools
│                                ├── Continue normal operation (local tools)
│                                └── Start background reconnection
│                                    (exponential backoff: 1s, 2s, 4s, ... 60s)
│                                    ├── Redis recovered? → Re-register, resume swarm
│                                    └── Still down? → Continue backoff
└── Circuit breaker opens after 5 failures → Stops attempting for 30s
```

### 7.3 Reconnection Strategy

Exponential backoff: `initial_delay=1s`, `max_delay=60s`, `multiplier=2.0`, `jitter=±10%`. Jitter prevents all agents from reconnecting simultaneously after a Redis restart.

### 7.4 Integration into Agent Lifecycle

`ResilientSwarmClient` wraps `SwarmClient` and manages mode transitions. Callbacks `on_degrade` and `on_recover` allow the agent loop to react (disable/enable swarm tools, notify user). The tool's `check_fn` reads the client mode, so tools are automatically disabled without explicit unregistration.

---

## 8. Frontend Interaction Specifications

**Addresses**: H13 (Incomplete interaction design), H14 (No real-time transport), H15 (Crew builder unspecified)

### 8.1 Swarm Overview (`/swarm`)

**Layout**: Stats row (4 StatusCards) + two-column second row (heatmap left, agent grid right).

**Interactions**:
- Search: Client-side filter by display_name, capabilities, model (debounced 300ms)
- Sort: Toggle asc/desc by status, load, name
- Heatmap hover: Tooltip with agent name, time window, task count, load %
- Heatmap click / card click: Navigate to existing `/agents/:id` detail page
- Capability tag click: Filter grid to agents with matching capability

**States**: Loading (skeleton shimmer), Empty (illustration + CTA "Create Agent"), Error (pink banner + retry), Partial (heatmap unavailable message).

### 8.2 Task Monitor (`/swarm/tasks`)

**Task list**: Full-width table with filter bar (status/priority/agent dropdowns + search). Server-driven pagination (page size 25). Columns: ID (truncated UUID), Description, Status (colored badge), Priority, Agent, Duration, Time.

**Task detail** (`/swarm/tasks/:id`): Header + metadata + trace swimlane timeline + span detail panel (expandable) + result panel.

**Trace swimlane**: Each participating agent gets a horizontal lane. Spans rendered as colored absolute-positioned blocks on a time axis. Colors: ok = cyan, error = pink, running = animated cyan pulse. Click span → expand detail panel below.

**Real-time updates**: New task rows slide in with `animate-stagger` + brief cyan left-border highlight. Status changes transition badge color. New spans animate into the swimlane. All from SSE events.

### 8.3 Crew Management (`/crews`)

**Crew list**: Card grid showing name, description, agent count, workflow type badge, Edit/Execute buttons.

**Crew create/edit**: Two-panel layout — left form editor, right live DAG preview.

Form steps:
1. **Basic Info**: Name (required), description
2. **Agent Assignment**: Repeating role cards with agent dropdown (from registry), capability tags
3. **Workflow Steps**: Repeating step cards with role, task template, depends-on multi-select, input-from key-value pairs
4. **Review**: Read-only summary + full-width DAG preview

DAG preview: SVG-based topological graph. Nodes are rounded rectangles with step ID + role. Edges are directed arrows. Updates live as form changes. Hover highlights connected edges. Click node scrolls form to corresponding card. Cycle detection on save.

**Validation**: Inline red text on error. Step indicator turns pink for steps with errors. Cycle detection before save with inline error message.

### 8.4 Knowledge Base (`/swarm/knowledge`)

**Layout**: Search + filter bar (category dropdown, tags multi-select) + entry list (accordion pattern) + pagination.

**Search**: Client-side debounce (300ms). If query length >= 3, also trigger server-side `GET /swarm/knowledge?q={query}` for semantic search. Merge results: semantic first, substring matches second, deduplicated.

**Entry detail**: Accordion expansion with full content in monospace pre block.

**Create/edit**: Modal dialog with category dropdown, tags input, content textarea (min 10 chars).

---

## 9. State Management Architecture

**Addresses**: H16 (useState insufficient)

### 9.1 Store Architecture (Zustand)

Three stores, no provider boilerplate, coexist with existing `useState` pages:

| Store | Responsibility | Updated By |
|-------|---------------|------------|
| `swarmRegistry` | Agent list, status, capabilities, load | REST fetch + SSE events |
| `swarmTasks` | Task list, filters, pagination, trace spans | REST fetch + SSE events |
| `swarmEvents` | SSE connection lifecycle, event dispatch | EventSource wrapper |

### 9.2 TypeScript Interfaces

```typescript
interface SwarmAgent {
  agent_id: number;
  display_name: string;
  capabilities: string[];
  status: "online" | "offline" | "busy";
  current_tasks: number;
  max_concurrent_tasks: number;
  last_heartbeat: number;
}

type TaskStatus = "pending" | "assigned" | "running" | "completed" | "failed";

interface SwarmTask {
  task_id: string;
  description: string;
  status: TaskStatus;
  priority: 0 | 1 | 2;
  assigned_agent_id: number | null;
  duration_ms: number | null;
  tokens_used: number;
  created_at: number;
}

interface TraceSpan {
  span_id: string;
  agent_id: number;
  operation: string;
  start_time: number;
  end_time: number | null;
  status: "ok" | "error" | "running";
}

interface TaskFilters {
  status: TaskStatus | "all";
  priority: 0 | 1 | 2 | "all";
  agentId: number | "all";
  search: string;
}
```

### 9.3 SSE Connection Lifecycle

Managed by `useSwarmSSE` hook with reference counting. Connection persists across navigation between swarm pages, tears down when leaving all swarm pages.

```
SwarmSSE (vanilla class) → swarmEvents store.handleEvent()
  → dispatches to swarmRegistry / swarmTasks stores
  → React components re-render via zustand selectors
```

### 9.4 Compatibility

Existing pages import zero zustand stores. No provider wrapper needed. `AdminLayout` checks swarm capability once on mount for sidebar conditional rendering only.

---

## 10. Real-Time Transport Protocol

**Addresses**: H14 (No transport specified), SSE security concern

### 10.1 SSE Endpoint

`GET /admin/api/swarm/events/stream?token={sse_token}`

Event types: `agent_online`, `agent_offline`, `task_created`, `task_started`, `task_completed`, `task_failed`, `trace_span_added`, `heartbeat` (every 30s).

Each event: `event: {type}\ndata: {JSON}\nid: {sequential_id}`. The `id` field enables browser's built-in `Last-Event-ID` reconnection.

### 10.2 One-Time SSE Token Authentication

`EventSource` doesn't support custom headers, so passing admin key as query param is insecure. Solution:

1. `POST /admin/api/swarm/events/token` → `{token: "sse_xxx", expires_in: 1800}`
2. Token: 16-byte random hex, stored in Redis with 30min TTL
3. Client creates EventSource with `?token={token}`
4. 60s before expiry, client obtains new token, closes old EventSource, opens new one with `Last-Event-ID`

Rate limiting: Max 10 token requests per minute per admin key. Token invalidated on admin key change.

### 10.3 Frontend EventSource Wrapper

`SwarmSSE` class features:
- Exponential backoff reconnection (1s → 30s cap, max 10 attempts)
- Heartbeat detection: if no event within 60s, reconnect
- Token auto-refresh 60s before expiry with `Last-Event-ID` continuation
- Clean stop: clears all timers, closes EventSource
- Direct store access (`useSwarmEvents.getState().handleEvent()`) — no React hook dependency

---

## 11. Navigation and Routing Extension

### 11.1 Sidebar Grouping

```
── AGENT MANAGEMENT ──   (section label, uppercase, text-text-secondary)
 [icon] Dashboard
 [icon] Settings

── SWARM ────────────   (section label)
 [icon] Swarm Overview
 [icon] Task Monitor
 [icon] Crews
 [icon] Knowledge Base
```

### 11.2 Feature Flag: Conditional Swarm UI

`GET /admin/api/swarm/capability` → `{enabled: true}`. Returns true only when Redis is reachable and swarm module is loaded. If false/failed, entire swarm navigation section is hidden.

Route-level guard: `SwarmGuard` component wraps all swarm routes, redirects to dashboard if disabled.

### 11.3 Route Configuration

8 new routes (nearly tripling existing 4):

```
/swarm              → SwarmOverviewPage
/swarm/tasks        → TaskMonitorPage
/swarm/tasks/:id    → TaskDetailPage
/swarm/knowledge    → KnowledgeBasePage
/crews              → CrewListPage
/crews/new          → CrewEditPage
/crews/:id/edit     → CrewEditPage
```

All nested under `SwarmGuard` wrapper. Swarm pages organized in `src/pages/swarm/` directory.

### 11.4 SVG Icons

Four new inline SVG icons following existing pattern (`viewBox="0 0 24 24"`, `stroke="currentColor"`):
- **IconSwarm**: Pentagon of 5 circles connected by lines (distributed topology)
- **IconTasks**: Rounded square with 3 lines and status dots (task checklist)
- **IconCrews**: Two overlapping person silhouettes (team)
- **IconKnowledge**: Book with text lines and small lightbulb (knowledge repository)

---

## 12. Visual Design Specification

### 12.1 Swarm Color Mapping (Neon Cyberpunk Theme)

| Concept | Color | Token |
|---------|-------|-------|
| Agent online | Green | `--color-success` |
| Agent offline | Dim gray | `--color-text-secondary` |
| Agent busy | Cyan | `--color-accent-cyan` |
| Task pending | Amber | `--color-warning` |
| Task running | Cyan | `--color-accent-cyan` |
| Task completed | Green | `--color-success` |
| Task failed | Pink | `--color-accent-pink` |
| Span ok | Cyan | `bg-accent-cyan` |
| Span error | Pink | `bg-accent-pink` |
| Span running | Cyan + pulse | `bg-accent-cyan animate-status-pulse` |
| Capability tag | Cyan tint | `bg-accent-cyan/10 text-accent-cyan` |

### 12.2 Trace Swimlane Visual

- **Lane**: 48px tall, 1px separator, 180px left label, right timeline area
- **Lane colors**: Cycle through accent-pink (supervisor), accent-cyan, success, warning, accent-glow
- **Span**: 32px tall rounded rect, `position: absolute`, `left: {start%}`, `width: {duration%}`
- **Running span**: Shimmer animation (2s linear infinite gradient sweep)
- **Error span**: `glow-pink` box-shadow, expand on hover to show error message
- **Time axis ruler**: Graduated marks every 5s/30s/5min depending on trace duration, `font-mono text-xs`

### 12.3 Heatmap Color Scheme

Reuses existing `getBarColor` gradient as cell background:
- 0-69%: `--color-heatmap-low` (cyan 20% opacity)
- 70-89%: `--color-heatmap-mid` (amber 40% opacity)
- 90-100%: `--color-heatmap-high` (pink 50% opacity)

Cell: 20x20px, 2px gap. Tooltip on hover: agent name, time window, task count, load %.

### 12.4 Component Reuse

Directly reusable: `StatusCard`, `ConfirmDialog`, `showToast`, `getBarColor`, `statusDotColor`, `StepIndicator`, `glass`/`animate-stagger`/`glow-pink-text` CSS classes, all `--color-*` theme tokens, `adminFetch`/`AdminApiError`.

Requires adaptation: Dashboard agent card → `SwarmAgentCard` (add capability tags, load bar), Logs SSE pattern → `SwarmSSE` class.

### 12.5 i18n Key Additions

~80 new keys across both `en.ts` and `zh.ts`, organized into sections: `navSwarm*`, `swarm*`, `task*`, `crew*`, `knowledge*`, `swarmConnected/Disconnected/Reconnecting`.

---

## Appendix: New Files

```
kubernetes/swarm/
  redis-config.yaml            # Redis configuration ConfigMap
  redis-secret.yaml            # Redis password Secret
  redis-pv.yaml                # PV + PVC
  redis.yaml                   # Deployment + Service + Exporter
  redis-networkpolicy.yaml     # NetworkPolicy
  redis-master.yaml            # Phase 2 Master StatefulSet
  redis-sentinel.yaml          # Phase 2 Sentinel Deployment

hermes_agent/swarm/
  redis_connection.py          # Redis connection factory (Sentinel/standalone)
  connection_config.py         # Connection pool sizing
  client.py                    # SwarmClient core
  health.py                    # Redis health check
  messaging.py                 # Stream operations (publish, read, ack, reclaim)
  exactly_once.py              # Dedup, execution guard, cancellation, DLQ
  stalled_scanner.py           # Stalled message background scanner
  circuit_breaker.py           # Circuit breaker pattern
  reconnect.py                 # Exponential backoff reconnection
  resilient_client.py          # Resilient client with graceful degradation

tools/
  swarm_tool.py                # swarm_delegate tool handler

admin/backend/
  swarm_models.py              # Swarm API Pydantic models
  swarm_routes.py              # Swarm API FastAPI routes

admin/frontend/src/
  stores/
    swarmRegistry.ts           # Zustand store for agent registry
    swarmTasks.ts              # Zustand store for tasks + traces
    swarmEvents.ts             # Zustand store for SSE events
  lib/
    swarm-sse.ts               # EventSource wrapper with reconnection
  pages/swarm/
    SwarmOverviewPage.tsx
    TaskMonitorPage.tsx
    TaskDetailPage.tsx
    CrewListPage.tsx
    CrewEditPage.tsx
    KnowledgeBasePage.tsx
  components/
    SwarmGuard.tsx             # Feature flag route guard
    RedisHealthCard.tsx        # Redis health display

monitoring/
  redis-alerts.yaml            # Prometheus alerting rules
```

## Appendix: Deployment Order (Phase 1)

```bash
NS="hermes-agent"

# 1. Node storage directory
ssh hermes-node "sudo mkdir -p /data/hermes-redis && sudo chown 999:999 /data/hermes-redis"

# 2. Secret
kubectl create secret generic hermes-redis-secret \
  --namespace="$NS" \
  --from-literal=redis-password="$(openssl rand -hex 32)" \
  --dry-run=client -o yaml | kubectl apply -f -

# 3-6. ConfigMap, PV/PVC, Deployment, NetworkPolicy
kubectl apply -f kubernetes/swarm/redis-config.yaml
kubectl apply -f kubernetes/swarm/redis-pv.yaml
kubectl apply -f kubernetes/swarm/redis.yaml
kubectl apply -f kubernetes/swarm/redis-networkpolicy.yaml

# 7. Verify
kubectl rollout status deployment/hermes-redis -n "$NS" --timeout=60s
```
