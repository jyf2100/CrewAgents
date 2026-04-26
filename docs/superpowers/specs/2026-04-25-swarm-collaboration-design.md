# Hermes 蜂群协作详细设计

> **版本**: v2.0 (含技术补充)
> **日期**: 2026-04-25
> **依赖**: Hermes Admin Panel PRD v1.0
> **状态**: Draft
> **合并**: 原始设计 v1.0 + 技术补充文档（解决 11 CRITICAL + 23 HIGH 评审问题）

---

## 1. 设计目标

将 Hermes 从「多实例独立运行」演进为「多 Agent 蜂群协作」，使 Agent 能够：
- 发现彼此的存在和能力
- 通过消息总线异步通信
- 共享知识和工具
- 接受统一调度执行复合任务

**设计原则**：
- 增量演进，不破坏现有独立 Agent 功能
- 复用现有架构（K8s Deployment、Admin API、delegate_tool）
- 消息总线解耦，Agent 可随时加入/离开
- 单 Agent 仍然是完整可用的独立实体
- Redis 故障时自动降级为独立模式

---

## 2. 系统架构

```
                              ┌──────────────────┐
                              │   Supervisor      │
                              │   (特殊 Agent)    │
                              │   - 任务路由      │
                              │   - 结果汇总      │
                              │   - 负载均衡      │
                              └────────┬─────────┘
                                       │
                          ┌────────────┼────────────┐
                          │            │            │
                    ┌─────┴─────┐ ┌────┴────┐ ┌─────┴─────┐
                    │ Agent #1  │ │Agent #2  │ │ Agent #N  │
                    │ code-     │ │data-     │ │trans-     │
                    │ review    │ │analysis  │ │lation     │
                    └─────┬─────┘ └────┬─────┘ └─────┬─────┘
                          │            │              │
              ┌───────────┴────────────┴──────────────┴───────────┐
              │              消息传输层 (Redis)                     │
              │  ┌─────────────────────────────────────────────┐  │
              │  │ Authoritative Layer (Streams)                │  │
              │  │  hermes:stream:agent.{id}.tasks             │  │
              │  │  hermes:stream:agent.{id}.results           │  │
              │  │  hermes:stream:swarm.dlq                    │  │
              │  ├─────────────────────────────────────────────┤  │
              │  │ Advisory Layer (Pub/Sub)                    │  │
              │  │  swarm.advisory.task/result/online/offline  │  │
              │  └─────────────────────────────────────────────┘  │
              └──────────────────────────────────────────────────┘
                          │            │              │
              ┌───────────┴────────────┴──────────────┴───────────┐
              │                  共享记忆层                        │
              │  ┌────────────────┐  ┌───────────────────────┐   │
              │  │ Agent Registry │  │ Shared Knowledge Base │   │
              │  │ (Redis Hash)   │  │ (Vector Store)        │   │
              │  └────────────────┘  └───────────────────────┘   │
              └──────────────────────────────────────────────────┘
```

**双层传输架构**：
- **Advisory Layer (Pub/Sub)**：实时唤醒通知，fire-and-forget，允许丢失
- **Authoritative Layer (Streams)**：持久化任务/结果投递，Consumer Group 确认机制，不允许丢失

---

## 3. 核心组件设计

### 3.1 Agent Registry（Agent 注册中心）

#### 3.1.1 数据模型

存储在 Redis Hash `hermes:registry` 中，每个 Agent 一个条目：

```python
@dataclass
class AgentProfile:
    agent_id: int
    display_name: str
    capabilities: list[str]        # ["code-review", "refactoring", "testing"]
    model: str                      # "anthropic/claude-sonnet-4-20250514"
    provider: str                   # "openrouter"
    status: str                     # "online" | "offline" | "busy"
    tools: list[str]                # ["terminal", "file", "web", "browser"]
    max_concurrent_tasks: int       # 并发任务上限
    current_tasks: int              # 当前执行中的任务数
    registered_at: float            # 注册时间戳
    last_heartbeat: float           # 最后心跳时间
    inbox_channel: str              # "agent.3.inbox"
    api_endpoint: str               # Ingress URL
```

#### 3.1.2 注册流程

```
Agent 启动
    ↓
1. 读取自身 config.yaml 获取 capabilities（新增字段）
    ↓
2. POST /swarm/register → Admin API
    ↓
3. Admin API 写入 Redis Hash + 发布 swarm.advisory.online 消息
    ↓
4. Agent 启动心跳线程（每 30 秒更新 last_heartbeat）
    ↓
5. Agent 启动 Stream Consumer（XREADGROUP 订阅自己的任务流）
```

#### 3.1.3 K8s 集成

Agent capabilities 通过 config.yaml 定义，创建时由 Admin Panel 注入：

```yaml
# config.yaml 新增字段
swarm:
  enabled: true
  capabilities:
    - code-review
    - refactoring
  max_concurrent_tasks: 3
  message_bus: "redis://hermes-redis:6379/0"
```

Admin Panel 将这些信息同步写入：
- K8s Deployment annotation `hermes/capabilities`
- Redis Registry

#### 3.1.4 心跳与离线检测

```python
# Redis key: hermes:heartbeat:{agent_id}
# TTL: 60 seconds
# Agent 每 30 秒 SETEX 刷新

# Supervisor 每 60 秒扫描
async def prune_offline_agents(redis: Redis):
    keys = await redis.keys("hermes:heartbeat:*")
    for key in keys:
        ttl = await redis.ttl(key)
        if ttl < 0:  # expired
            agent_id = int(key.split(":")[-1])
            await redis.hset("hermes:registry", agent_id,
                           {"status": "offline"})
```

---

### 3.2 消息传输层

#### 3.2.1 双层传输分离

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

**为什么不只用 Pub/Sub**：Pub/Sub 不持久化消息，离线 Agent 会丢失任务。Streams + Consumer Group 提供持久化、消息确认、超时回收和死信队列能力。

#### 3.2.2 Per-Agent Stream 生命周期

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

#### 3.2.3 消息格式

所有 Stream 消息使用扁平 string key-value 字段（Redis Streams 要求），嵌套结构 JSON 编码。每条消息包含 `msg_version` 用于向前兼容。

**Task 消息字段**：`msg_version`, `task_id`, `task_type`, `goal`, `capability`, `input_data`, `sender_id`, `priority` (0/1/2), `deadline_ts`, `max_tokens`, `trace_id`, `parent_msg_id`, `timestamp`

**Result 消息字段**：`msg_version`, `task_id`, `agent_id`, `status` (completed/failed/partial), `output`, `error`, `tokens_used`, `duration_ms`, `artifacts` (JSON), `timestamp`

#### 3.2.4 完整消息生命周期

```
[发送任务]
  1. Generate task_id (UUID)
  2. SETNX hermes:swarm:dedup:{task_id} {sender_id} EX 300
  3. Backpressure check: GET hermes:swarm:depth:{target_id}
  4. XADD hermes:stream:agent.{target}.tasks * {fields} MAXLEN ~10000
  5. PUBLISH swarm.advisory.task {notification}

[接收和处理]
  1. Advisory listener wakes on Pub/Sub
  2. XREADGROUP GROUP agent.{B}.worker consumer-1 BLOCK 5000
  3. Check dedup lock: GET hermes:swarm:dedup:{task_id}
  4. Execute task
  5a. Success → XADD result to sender's result stream, XACK task
  5b. Failure → XADD to DLQ stream, XACK task
  6. PUBLISH swarm.advisory.result {notification}

[超时回收 — Supervisor 每 30s]
  1. XPENDING per agent stream
  2. XCLAIM messages idle > 180s
  3. Check agent heartbeat: EXISTS hermes:heartbeat:{agent_id}
  4a. Agent alive → DLQ with "timeout while agent alive"
  4b. Agent dead → Re-dispatch to another capable agent
```

#### 3.2.5 背压机制

| 队列深度 | 动作 |
|---------|------|
| < 5 | 正常接受 |
| 5-9 | 接受 + 记录警告 |
| >= 10 | 拒绝（503 + 重试提示） |

Redis key: `hermes:swarm:depth:{agent_id}`, TTL 120s，每次 XREADGROUP/XACK 后更新。

#### 3.2.6 常量

| 常量 | 值 | 用途 |
|------|-----|------|
| `MSG_VERSION` | "1" | 消息格式版本 |
| `DEFAULT_STREAM_MAXLEN` | 10000 | 每条 Stream 近似裁剪上限 |
| `RECLAIM_TIMEOUT_MS` | 180000 | 3 分钟后 Supervisor 回收 |
| `DEPTH_WARN_THRESHOLD` | 5 | 背压警告阈值 |
| `DEPTH_REJECT_THRESHOLD` | 10 | 背压拒绝阈值 |
| `DLQ_STREAM` | `hermes:stream:swarm.dlq` | 死信队列 |

---

### 3.3 Exactly-Once 语义

#### 3.3.1 五层防御

```
Layer 1: SETNX 去重锁（发送端）
  Key: hermes:swarm:dedup:{task_id}, TTL: 300s
  防止同一 task_id 重复 XADD

Layer 2: 执行守卫（接收端）
  Key: hermes:swarm:exec:{task_id}, Value: {agent_id, started_at, status}, TTL: 600s
  防止同一 task 被重复执行

Layer 3: 幂等结果写入
  Result RPUSH to hermes:swarm:result:{task_id}（每任务一个 list，单消费者 BLPOP）

Layer 4: 任务取消
  Key: hermes:swarm:cancel:{task_id}, TTL: 300s
  执行前和执行中均检查

Layer 5: DLQ 兜底
  Stream: hermes:stream:swarm.dlq
  人工或自动审查后可重新投递或丢弃
```

#### 3.3.2 任务取消流程

```
Supervisor / Sender:
  1. SET hermes:swarm:cancel:{task_id} {reason} EX 300
  2. PUBLISH swarm.advisory.cancel {task_id, reason}

Target Agent:
  Before execution: if EXISTS cancel key → skip, return status:"cancelled"
  During execution: if EXISTS cancel key → interrupt, return partial result
  After execution: if EXISTS cancel key → discard result
```

#### 3.3.3 DLQ 处理规则

| 原因 | 动作 |
|------|------|
| 超时 + Agent 存活 | retry_count < 3: 重发同一 Agent; >= 3: 升级处理 |
| 超时 + Agent 离线 | 找另一个有能力的 Agent，重新投递 |
| 错误 | 记录日志、通知发送方，不重试 |
| 已取消 | 静默丢弃 |
| 队列溢出 | 等待 30s，重发到同一或不同 Agent |

#### 3.3.4 幂等性原则

1. **发送端幂等**：`publish_task()` 使用 SETNX；重复 XADD 被阻止
2. **接收端幂等**：执行前检查执行守卫；"running" 则跳过，"completed" 则重发缓存结果
3. **结果写入幂等**：每任务 list 配合 BLPOP 单消费者
4. **状态转换幂等**：Compare-and-set；completed→completed 是空操作
5. **工具副作用幂等**："写文件"覆盖相同内容；"创建 PR"先检查是否已存在

#### 3.3.5 常量

| 常量 | 值 | 用途 |
|------|-----|------|
| `DEDUP_TTL` | 300s | 发送端去重锁生命周期 |
| `EXEC_GUARD_TTL` | 600s | 执行守卫（2 倍任务超时） |
| `CANCEL_TTL` | 300s | 取消标记生命周期 |
| `RESULT_TTL` | 300s | 结果 list 生命周期 |
| `MAX_DLQ_RETRIES` | 3 | DLQ 重试上限 |

---

### 3.4 Supervisor Agent（调度者）

#### 3.4.1 角色定义

Supervisor 是一个特殊的 Hermes Agent 实例（agent_id=0），额外加载以下能力：
- **任务路由**：根据任务类型和 Agent 能力匹配最优执行者
- **负载均衡**：考虑 Agent 当前任务数和响应延迟
- **结果汇总**：多 Agent 协作时合并中间结果
- **故障恢复**：Agent 离线时重新分配任务

#### 3.4.2 路由算法

```python
class SwarmRouter:
    def __init__(self, registry: AgentRegistry):
        self.registry = registry

    def route(self, task: TaskPayload) -> int | None:
        """选择最佳 Agent 执行任务。"""
        # 1. 按能力过滤
        candidates = [
            a for a in self.registry.get_online_agents()
            if set(task.required_capabilities).issubset(set(a.capabilities))
        ]
        if not candidates:
            return None

        # 2. 排除满载的 Agent
        candidates = [
            a for a in candidates
            if a.current_tasks < a.max_concurrent_tasks
        ]
        if not candidates:
            return None

        # 3. 按 (当前负载 / 最大负载) 排序，选择最空闲的
        candidates.sort(key=lambda a: a.current_tasks / a.max_concurrent_tasks)
        return candidates[0].agent_id

    def route_batch(self, tasks: list[TaskPayload]) -> dict[int, list[TaskPayload]]:
        """批量路由，均衡分配。"""
        assignments: dict[int, list[TaskPayload]] = {}
        for task in tasks:
            best = self.route(task)
            if best is not None:
                assignments.setdefault(best, []).append(task)
        return assignments
```

#### 3.4.3 任务执行流程

```
用户 → Supervisor
         │
         ├─ 1. 解析用户意图，判断是否需要多 Agent 协作
         │
         ├─ 2. 单 Agent 任务：直接路由给最合适的 Agent
         │     └─ 等待结果 → 返回用户
         │
         └─ 3. 多 Agent 任务：拆分为子任务
               │
               ├─ 并行分发子任务到多个 Agent
               │   ├─ Agent A: 代码分析
               │   ├─ Agent B: 生成测试
               │   └─ Agent C: 文档翻译
               │
               ├─ 收集所有结果
               │
               └─ 汇总合并 → 返回用户
```

#### 3.4.4 Supervisor 的 SOUL.md

```markdown
# Supervisor Agent

You are the coordinator of a multi-agent swarm. Your responsibilities:

1. **Task Analysis**: Break down complex user requests into subtasks
2. **Agent Selection**: Choose the best agent based on capabilities
3. **Delegation**: Dispatch tasks via the swarm delegation tool
4. **Synthesis**: Combine results from multiple agents into coherent responses
5. **Fallback**: If no suitable agent is available, handle the task yourself

## Decision Rules
- If a task requires only one capability → delegate to a single specialist
- If a task requires multiple capabilities → split and parallelize
- If no agent with required capability is online → do it yourself + warn user
- If an agent fails to respond in 60s → reassign to another agent

## Available Tools
- swarm_delegate: Dispatch task to swarm agents
- swarm_status: Check agent availability and load
- swarm_broadcast: Send message to all agents
- (all standard hermes tools for self-execution fallback)
```

---

### 3.5 Sync/Async 桥接策略

#### 3.5.1 问题

Agent 循环 (`run_agent.py` `AIAgent.run_conversation()`) 完全同步。Swarm 委派可能阻塞 30-120 秒等待另一个 Agent 执行任务并返回结果。期间心跳线程饥饿，Agent 在 Gateway 看来离线，引发级联故障。

现有的 `delegate_tool.py` 已通过三线程架构解决此问题：ThreadPoolExecutor 用于子 Agent、daemon 心跳线程、调用方工具执行线程。

#### 3.5.2 三线程架构

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

#### 3.5.3 调用序列

```
1. LLM 调用 swarm_delegate(goal, capability)
2. registry.dispatch → swarm_delegate_handler (is_async=False)
3. Handler 生成心跳线程 + 内部工作线程
4. 工作线程运行独立事件循环：
   a. XADD to hermes:stream:agent.{target}.tasks
   b. PUBLISH advisory on swarm.advisory.task
   c. BLPOP on hermes:swarm:result:{task_id} with periodic cancel check
   d. 返回结果或超时错误
5. Handler 收集 future.result(timeout+10)
6. 心跳线程每 30s 调用 _touch_activity()
7. 结果流：worker → handler → registry.dispatch → agent loop
```

#### 3.5.4 关键设计决策

`swarm_delegate` 注册为 **`is_async=False`**。内部管理自己的 ThreadPoolExecutor，完全复制 `delegate_tool.py` 的已验证模式。`_run_async()` 桥接从不用于 swarm 委派。

| 场景 | 机制 | 原因 |
|------|------|------|
| 本地异步工具 (web, mcp) | `_run_async()` via `_get_tool_loop()` | 短 (<10s)，无心跳风险 |
| 进程内子 Agent 委派 | ThreadPoolExecutor (outer) + heartbeat thread | 长 (最长 120s) |
| Swarm 委派 | ThreadPoolExecutor (inner) + heartbeat thread | 长 (最长 120s)，Redis 阻塞 |
| Swarm 结果收集 | `_run_async()` 仅在 worker thread 内 | Worker 已隔离 |

#### 3.5.5 常量

| 常量 | 值 | 位置 |
|------|-----|------|
| `_SWARM_TIMEOUT` | 120 | `tools/swarm_tool.py` |
| `_HEARTBEAT_INTERVAL` | 30 | `tools/swarm_tool.py` |
| `_HEARTBEAT_TTL` | 60 | Redis key TTL |

#### 3.5.6 集成点

- **`model_tools.py`**：添加 `"tools.swarm_tool"` 到 `_modules` 列表
- **`tools/delegate_tool.py`**：Swarm 心跳与 delegate 心跳共存（都调用 `_touch_activity`）
- **`gateway/run.py`**：无需修改；swarm handler 的内部线程池安全嵌套在 gateway 的 executor 线程内
- **`tools/registry.py`**：无需修改；`is_async=False` 意味着 dispatch 直接调用 handler

---

### 3.6 连接管理

#### 3.6.1 Per-Agent 连接拓扑

```
Agent Process
├── Pool A: General (max_connections=4)
│   Registry reads/writes, heartbeat, shared memory, trace writes
├── Connection B: Pub/Sub Dedicated (1 connection)
│   Subscriptions to advisory channels (blocks the connection)
└── Connection C: Stream Consumer (1-2 connections)
    XREADGROUP, XACK, XPENDING (blocking reads)
```

#### 3.6.2 连接池大小公式

```
general_pool_max = base(2) + max_concurrent_tasks * per_task(1)

Supervisor: general_pool_max = base + (max_tasks * per_task) + 4
  Extra for: registry scanning, latency tracking, broadcast, result aggregation
```

**10-Agent 集群估算**：73 个总连接（远低于 Redis `maxclients=200`）。

| 组件 | 数量 | 每个连接数 | 总计 |
|------|------|-----------|------|
| Worker Agent | 8 | 6 (4 pool + 1 pubsub + 1 stream) | 48 |
| Supervisor | 1 | 17 (11 pool + 1 pubsub + 2 streams + 3 extra) | 17 |
| Admin Panel | 1 | 4 | 4 |
| Monitoring | 2 | 2 | 4 |

#### 3.6.3 超时配置

所有连接：`socket_timeout=5s`, `socket_connect_timeout=3s`, `retry_on_timeout=True`, `health_check_interval=15s`, TCP keepalive (idle=60s, interval=10s, count=3)。

---

### 3.7 Redis 部署架构

#### 3.7.1 Phase 1：单节点 + AOF + PVC（3-10 Agent）

**Redis 配置** (`kubernetes/swarm/redis-config.yaml`)：

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

**PersistentVolume** (`kubernetes/swarm/redis-pv.yaml`)：Local PV 5Gi with `Retain` 回收策略，通过 `nodeAffinity` 绑定到特定节点。

**Deployment** (`kubernetes/swarm/redis.yaml`)：单副本 `Recreate` 策略，密码来自 Secret，readiness/liveness probe 通过 `redis-cli ping`，sidecar `oliver006/redis_exporter` 用于 Prometheus 指标。资源限制：500m CPU / 512Mi 内存。

**NetworkPolicy**：仅允许 `hermes-agent` namespace 内的 ingress。

**容量估算**：~200MB/天；5Gi 支持约 25 天，配合应用层 TTL 清理。

#### 3.7.2 Phase 2：Redis Sentinel（10-20 Agent）

架构：1 Master (StatefulSet + PVC) + 3 Sentinel pods (Deployment)。

Sentinel 配置：
- `down-after-milliseconds`: 10000
- `failover-timeout`: 30000
- `parallel-syncs`: 1
- Quorum: 2

客户端连接（redis-py Sentinel 模式）：

```python
from redis.asyncio.sentinel import Sentinel
sentinel = Sentinel([(host, 26379)])
redis = sentinel.master_for('hermes-master', password=pwd)
```

**限制**：1 Master 无 Slave 时，Sentinel 无法自动提升。其价值在于检测故障 + 触发 K8s Pod 重启 + 客户端自动发现恢复的 Master。

#### 3.7.3 Phase 3：NATS JetStream 评估（20+ Agent）

迁移触发阈值：
- Agent 数量 > 20
- Stream 吞吐量 > 2000 msg/s
- 需要保证的 exactly-once 投递
- Redis 内存 > 2GB

迁移路径：双写过渡期（`redis-only` → `dual-write` → `nats-primary` → `nats-only`）。

---

### 3.8 Redis 监控与运维

#### 3.8.1 `/swarm/metrics` API 端点

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

#### 3.8.2 停滞消息扫描器

在 Supervisor 上每 60s 运行。对每条 stream：
1. XPENDING 查找未确认消息
2. 空闲 > 300s（可配置）的消息为"停滞"
3. 如果 `delivered_count < 3`：XCLAIM + 重新 XADD 为新消息（重试）
4. 如果 `delivered_count >= 3`：移入死信 stream (`{stream}.dead`)

#### 3.8.3 Redis 健康检查指标

| 指标 | 告警阈值 | 严重度 |
|------|---------|--------|
| `latency_ms` | > 10ms warn, > 50ms critical | WARN/CRIT |
| `memory_used_percent` | > 70% warn, > 85% critical | WARN/CRIT |
| `connected_clients` | > 150 warn, > 180 critical | WARN/CRIT |
| `aof_enabled` | false | CRITICAL |
| `aof_last_bgrewrite_status` | "err" | CRITICAL |
| `evicted_keys` | > 0 | WARN |
| `stream_length` | > 10000 | WARN |
| `stalled_messages` | > 5 warn, > 20 critical | WARN/CRIT |

---

### 3.9 熔断器与优雅降级

#### 3.9.1 熔断器模式

状态：CLOSED → OPEN（5 次连续失败后）→ HALF_OPEN（30s 恢复超时后）→ CLOSED（2 次连续成功后）。

```python
breaker = RedisCircuitBreaker(config=CircuitBreakerConfig(
    failure_threshold=5,
    success_threshold=2,
    recovery_timeout=30.0,
    timeout_per_call=3.0,
))
result = await breaker.call(redis.get, "some_key")  # Returns None if OPEN
```

仅连接相关错误（ConnectionError, TimeoutError 等）触发熔断器。非连接错误（WRONGTYPE 等）正常传播。

#### 3.9.2 优雅降级流程

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

#### 3.9.3 重连策略

指数退避：`initial_delay=1s`, `max_delay=60s`, `multiplier=2.0`, `jitter=±10%`。Jitter 防止所有 Agent 在 Redis 重启后同时重连。

#### 3.9.4 集成到 Agent 生命周期

`ResilientSwarmClient` 封装 `SwarmClient` 并管理模式转换。回调 `on_degrade` 和 `on_recover` 允许 Agent 循环做出反应（禁用/启用 swarm 工具、通知用户）。工具的 `check_fn` 读取客户端模式，因此工具会自动禁用而无需显式注销。

---

### 3.10 共享记忆层

#### 3.10.1 知识库架构

```
┌───────────────────────────────────────────────┐
│              Shared Knowledge Base              │
│                                                 │
│  ┌──────────────┐  ┌────────────────────────┐ │
│  │ Short-term   │  │ Long-term              │ │
│  │ (Redis)      │  │ (Vector Store)         │ │
│  │              │  │                        │ │
│  │ - 会话上下文  │  │ - 代码规范             │ │
│  │ - 任务状态   │  │ - 项目文档             │ │
│  │ - 中间结果   │  │ - 历史决策             │ │
│  │ - TTL: 1h    │  │ - 知识条目             │ │
│  └──────────────┘  └────────────────────────┘ │
│                                                 │
│  ┌──────────────────────────────────────────┐  │
│  │ API Layer                                 │  │
│  │ POST /swarm/knowledge                     │  │
│  │ GET  /swarm/knowledge?q={query}           │  │
│  │ POST /swarm/knowledge/{id}                │  │
│  └──────────────────────────────────────────┘  │
└───────────────────────────────────────────────┘
```

#### 3.10.2 短期记忆（Redis）

```python
# Key: hermes:context:{trace_id}
# Value: { messages, artifacts, status }
# TTL: 3600 (1 hour)

@dataclass
class SharedContext:
    trace_id: str
    task_id: str
    messages: list[dict]       # 对话历史
    artifacts: list[str]       # 产出物路径
    status: str
    created_at: float
    participants: list[int]    # 参与 Agent 列表
```

#### 3.10.3 长期记忆（Vector Store）

```python
@dataclass
class KnowledgeEntry:
    id: str
    source_agent: int
    content: str              # 原始内容
    embedding: list[float]    # 向量
    tags: list[str]           # ["python", "testing", "convention"]
    category: str             # "code_style" | "decision" | "doc"
    created_at: float
    access_count: int
```

#### 3.10.4 技术选型

| 选项 | 优点 | 缺点 | 推荐 |
|------|------|------|------|
| ChromaDB (嵌入式) | 轻量、Python 原生 | 单进程、不支持分布式 | 开发/小规模 |
| Qdrant | 高性能、支持 K8s 部署 | 需额外资源 | **生产推荐** |
| Redis + RedisVL | 复用 Redis、少一个组件 | 向量搜索能力较弱 | 最小部署 |

**推荐方案**：Phase 2 用 Redis + RedisVL，Phase 3 迁移到 Qdrant。

---

### 3.11 工具市场

#### 3.11.1 工具注册

每个 Agent 在注册时声明自己可提供的工具：

```python
@dataclass
class AgentProfile:
    # ... 原有字段 ...
    offered_tools: list[ToolOffering]  # 对外提供的工具

@dataclass
class ToolOffering:
    name: str               # "code_analysis"
    description: str        # "深度代码分析，支持 10+ 语言"
    input_schema: dict      # JSON Schema
    output_schema: dict     # JSON Schema
    estimated_latency_ms: int  # 预估延迟
    cost_tokens: int        # 预估 token 消耗
```

#### 3.11.2 跨 Agent 工具调用

```python
# 在 delegate_tool.py 中新增 swarm 委派模式

def delegate_to_swarm(
    goal: str,
    required_capability: str,
    input_data: str,
    timeout: int = 120,
) -> str:
    """将任务委派给蜂群中最合适的 Agent。"""

    # 1. 查询 Registry 找到有此能力的 Agent
    agent = registry.find_by_capability(required_capability)

    if agent is None:
        return f"No agent with capability '{required_capability}' is available."

    # 2. 通过消息总线发送任务
    msg = SwarmMessage(
        msg_id=str(uuid4()),
        msg_type="task",
        sender=my_agent_id,
        recipient=agent.agent_id,
        payload=TaskPayload(
            task_id=str(uuid4()),
            task_type=required_capability,
            description=goal,
            input_data=input_data,
        ),
    )

    # 3. 等待结果（通过 Stream）
    result = wait_for_result(msg.msg_id, timeout=timeout)

    return result.output
```

#### 3.11.3 Agent 侧工具服务化

每个 Agent 在注册后，除了监听 Stream Consumer，还需要启动一个轻量级的 HTTP 工具服务：

```python
# Agent 进程内启动的 FastAPI 子服务
# 端口：8643（Agent 主服务在 8642）

@app.post("/swarm/invoke/{tool_name}")
async def invoke_tool(tool_name: str, request: ToolRequest):
    """供其他 Agent 通过 HTTP 调用本 Agent 的工具。"""
    # 验证调用者身份（通过 Admin API token）
    # 执行工具
    # 返回结果
```

**为什么不只用消息总线**：HTTP 同步调用更简单，适合短延迟的工具调用；消息总线用于异步任务和广播。

---

### 3.12 分布式追踪

#### 3.12.1 Trace Context 传播

```python
import contextvars

# 当前追踪上下文
trace_context: contextvars.ContextVar[TraceContext | None] = \
    contextvars.ContextVar("trace_context", default=None)

@dataclass
class TraceContext:
    trace_id: str       # 全局唯一
    span_id: str        # 当前 span
    parent_span_id: str | None
    agent_id: int       # 发起 Agent
```

#### 3.12.2 追踪数据存储

```python
# Redis Sorted Set: hermes:traces:{trace_id}
# Score = timestamp, Value = span JSON
# TTL: 3600 (1 hour, 防止无限增长)

@dataclass
class TraceSpan:
    trace_id: str
    span_id: str
    parent_span_id: str | None
    agent_id: int
    operation: str       # "delegate" | "execute" | "tool_call"
    input_tokens: int
    output_tokens: int
    start_time: float
    end_time: float
    status: str          # "ok" | "error"
    error_message: str | None
```

#### 3.12.3 Admin Panel 可视化

在 `/swarm/tasks/{id}/trace` 页面展示：
- 时间线视图（每个 Agent 一个泳道）
- Span 详情（点击展开 token 用量、延迟等）
- 错误高亮和重试链

---

### 3.13 自适应扩缩容

#### 3.13.1 KEDA Scaler 配置

```yaml
# kubernetes/swarm/keda-scaler.yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: agent-scaler
  namespace: hermes-agent
spec:
  scaleTargetRef:
    name: hermes-gateway-1
  triggers:
    - type: redis
      metadata:
        address: hermes-redis:6379
        listName: hermes:tasks:agent.1
        listLength: "5"           # 队列深度 > 5 时扩容
  minReplicaCount: 0              # 空闲时缩到 0
  maxReplicaCount: 5              # 最多 5 副本
  cooldownPeriod: 120             # 2 分钟冷却
```

#### 3.13.2 基于 Agent 负载的动态路由

```python
class AdaptiveRouter(SwarmRouter):
    """根据 Agent 负载和响应时间动态调整路由。"""

    def __init__(self, registry: AgentRegistry, redis: Redis):
        super().__init__(registry)
        self.redis = redis

    def route(self, task: TaskPayload) -> int | None:
        candidates = self._filter_capable(task)
        if not candidates:
            return None

        # 加权随机选择：权重 = f(空闲容量, 历史响应速度)
        weights = []
        for agent in candidates:
            capacity = (agent.max_concurrent_tasks - agent.current_tasks)
            latency = self._get_avg_latency(agent.agent_id)
            weight = capacity * 1000 / max(latency, 100)
            weights.append(weight)

        return random.choices(candidates, weights=weights, k=1)[0].agent_id

    def _get_avg_latency(self, agent_id: int) -> float:
        """从 Redis 获取 Agent 平均响应延迟（ms）。"""
        val = self.redis.get(f"hermes:latency:{agent_id}")
        return float(val) if val else 5000.0
```

---

## 4. Admin Panel 扩展

### 4.1 新增页面

| 页面 | 路由 | 功能 |
|------|------|------|
| 蜂群概览 | `/swarm` | 所有 Agent 状态、能力标签、负载热力图 |
| 任务监控 | `/swarm/tasks` | 实时任务流、追踪链、结果查看 |
| 任务详情 | `/swarm/tasks/:id` | 任务元数据、追踪泳道时间线、Span 详情 |
| Crew 管理 | `/crews` | 创建/编辑/删除 Crew（Agent 组合） |
| 知识库 | `/swarm/knowledge` | 搜索、浏览、管理共享知识 |

### 4.2 新增 API 端点

```
# Swarm 管理
GET    /swarm/agents              # 获取所有注册 Agent 及能力
GET    /swarm/capability          # 检查 swarm 是否可用（feature flag）
POST   /swarm/tasks               # 提交任务到蜂群
GET    /swarm/tasks/{id}          # 查询任务状态
GET    /swarm/tasks/{id}/trace    # 获取任务追踪链
GET    /swarm/metrics             # 获取集群指标和 Redis 健康状态

# SSE 实时传输
POST   /swarm/events/token        # 获取一次性 SSE token
GET    /swarm/events/stream       # SSE 事件流

# Crew 管理
GET    /crews                     # 列出所有 Crew
POST   /crews                     # 创建 Crew
GET    /crews/{id}                # Crew 详情
PUT    /crews/{id}                # 更新 Crew
DELETE /crews/{id}                # 删除 Crew
POST   /crews/{id}/execute        # 执行 Crew 任务

# 知识库
GET    /swarm/knowledge           # 搜索知识
POST   /swarm/knowledge           # 添加知识
DELETE /swarm/knowledge/{id}      # 删除知识
```

### 4.3 Crew 数据模型

```python
class CrewConfig(BaseModel):
    name: str
    description: str
    agents: list[CrewAgent]       # Agent 角色分配
    workflow: WorkflowDef          # 工作流定义

class CrewAgent(BaseModel):
    agent_id: int
    role: str                     # "analyst" | "reviewer" | "writer"
    capabilities_required: list[str]

class WorkflowDef(BaseModel):
    type: str                     # "sequential" | "parallel" | "dag"
    steps: list[WorkflowStep]

class WorkflowStep(BaseModel):
    id: str
    agent_role: str
    task_template: str            # Jinja2 模板
    depends_on: list[str]         # 依赖的 step IDs
    input_from: dict[str, str]    # { "code": "step_1.output" }
```

---

## 5. 前端设计规格

### 5.1 交互规格

#### 5.1.1 Swarm Overview (`/swarm`)

**布局**：Stats 行（4 个 StatusCard）+ 双列第二行（热力图左，Agent 网格右）。

**交互**：
- 搜索：客户端按 display_name, capabilities, model 过滤（300ms debounce）
- 排序：按 status, load, name 切换升序/降序
- 热力图 hover：Tooltip 显示 Agent 名称、时间窗口、任务数、负载百分比
- 热力图/卡片点击：导航到现有 `/agents/:id` 详情页
- 能力标签点击：过滤网格到匹配能力的 Agent

**状态**：Loading（骨架微光）、Empty（插图 + CTA "Create Agent"）、Error（粉色横幅 + 重试）、Partial（热力图不可用提示）。

#### 5.1.2 Task Monitor (`/swarm/tasks`)

**任务列表**：全宽表格，带过滤栏（status/priority/agent 下拉 + 搜索）。服务端分页（每页 25 条）。列：ID（截断 UUID）、Description、Status（彩色徽章）、Priority、Agent、Duration、Time。

**任务详情** (`/swarm/tasks/:id`)：Header + 元数据 + 追踪泳道时间线 + Span 详情面板（可展开）+ 结果面板。

**追踪泳道**：每个参与 Agent 一个水平泳道。Span 渲染为彩色绝对定位块。颜色：ok = cyan, error = pink, running = 动画 cyan pulse。点击 Span 展开详情面板。

**实时更新**：新任务行以 `animate-stagger` 滑入 + 短暂 cyan 左边框高亮。状态变更转换徽章颜色。新 Span 动画进入泳道。全部来自 SSE 事件。

#### 5.1.3 Crew 管理 (`/crews`)

**Crew 列表**：卡片网格，显示名称、描述、Agent 数量、工作流类型徽章、Edit/Execute 按钮。

**Crew 创建/编辑**：双面板布局 — 左侧表单编辑器，右侧实时 DAG 预览。

表单步骤：
1. **基本信息**：Name（必填）、description
2. **Agent 分配**：重复角色卡片，含 Agent 下拉（来自注册表）、能力标签
3. **工作流步骤**：重复步骤卡片，含角色、任务模板、depends-on 多选、input-from 键值对
4. **审查**：只读摘要 + 全宽 DAG 预览

DAG 预览：SVG 拓扑图。节点为圆角矩形含 step ID + role。边为有向箭头。表单变更时实时更新。Hover 高亮连接边。点击节点滚动表单到对应卡片。保存前环检测。

**校验**：错误时内联红色文本。步骤指示器变粉色标记有错误的步骤。保存前环检测含内联错误消息。

#### 5.1.4 Knowledge Base (`/swarm/knowledge`)

**布局**：搜索 + 过滤栏（category 下拉、tags 多选）+ 条目列表（手风琴模式）+ 分页。

**搜索**：客户端 debounce（300ms）。查询长度 >= 3 时，同时触发服务端 `GET /swarm/knowledge?q={query}` 语义搜索。合并结果：语义搜索优先，子串匹配其次，去重。

**条目详情**：手风琴展开，完整内容在 monospace pre 块中。

**创建/编辑**：模态对话框，含 category 下拉、tags 输入、content textarea（最少 10 字符）。

### 5.2 状态管理（Zustand）

三个 store，无需 provider 样板代码，与现有 `useState` 页面共存：

| Store | 职责 | 更新来源 |
|-------|------|---------|
| `swarmRegistry` | Agent 列表、状态、能力、负载 | REST fetch + SSE 事件 |
| `swarmTasks` | 任务列表、过滤器、分页、追踪 Span | REST fetch + SSE 事件 |
| `swarmEvents` | SSE 连接生命周期、事件分发 | EventSource wrapper |

TypeScript 接口：

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
```

### 5.3 实时传输协议（SSE）

#### 5.3.1 SSE 端点

`GET /admin/api/swarm/events/stream?token={sse_token}`

事件类型：`agent_online`, `agent_offline`, `task_created`, `task_started`, `task_completed`, `task_failed`, `trace_span_added`, `heartbeat`（每 30s）。

每个事件格式：`event: {type}\ndata: {JSON}\nid: {sequential_id}`。`id` 字段启用浏览器的内置 `Last-Event-ID` 重连。

#### 5.3.2 一次性 SSE Token 认证

`EventSource` 不支持自定义 header，因此用查询参数传递 admin key 不安全。解决方案：

1. `POST /admin/api/swarm/events/token` → `{token: "sse_xxx", expires_in: 1800}`
2. Token：16 字节随机 hex，存储在 Redis 中，TTL 30 分钟
3. 客户端用 `?token={token}` 创建 EventSource
4. 过期前 60s，客户端获取新 token，关闭旧 EventSource，用 `Last-Event-ID` 打开新的

速率限制：每个 admin key 每分钟最多 10 次 token 请求。Admin key 变更时 token 失效。

#### 5.3.3 前端 EventSource 封装

`SwarmSSE` 类功能：
- 指数退避重连（1s → 30s 上限，最多 10 次尝试）
- 心跳检测：60s 内无事件则重连
- Token 到期前 60s 自动刷新 + `Last-Event-ID` 继续
- 干净停止：清除所有 timer，关闭 EventSource
- 直接 store 访问（`useSwarmEvents.getState().handleEvent()`）— 无 React hook 依赖

SSE 连接生命周期由 `useSwarmSSE` hook 管理，带引用计数。连接在 swarm 页面间导航时持久化，离开所有 swarm 页面时断开。

### 5.4 导航与路由扩展

#### 5.4.1 侧边栏分组

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

#### 5.4.2 Feature Flag：条件 Swarm UI

`GET /admin/api/swarm/capability` → `{enabled: true}`。仅当 Redis 可达且 swarm 模块加载时返回 true。如果 false/失败，整个 swarm 导航部分隐藏。

路由级守卫：`SwarmGuard` 组件包裹所有 swarm 路由，禁用时重定向到 Dashboard。

#### 5.4.3 路由配置

```
/swarm              → SwarmOverviewPage
/swarm/tasks        → TaskMonitorPage
/swarm/tasks/:id    → TaskDetailPage
/swarm/knowledge    → KnowledgeBasePage
/crews              → CrewListPage
/crews/new          → CrewEditPage
/crews/:id/edit     → CrewEditPage
```

所有嵌套在 `SwarmGuard` 下。Swarm 页面组织在 `src/pages/swarm/` 目录。

#### 5.4.4 SVG 图标

四个新 inline SVG 图标，遵循现有模式（`viewBox="0 0 24 24"`, `stroke="currentColor"`）：
- **IconSwarm**：五边形 5 个圆 + 连线（分布式拓扑）
- **IconTasks**：圆角方块 + 3 行 + 状态点（任务列表）
- **IconCrews**：两个重叠的人形轮廓（团队）
- **IconKnowledge**：书本 + 文字行 + 小灯泡（知识库）

### 5.5 视觉设计（Neon Cyberpunk 主题）

#### 5.5.1 Swarm 颜色映射

| 概念 | 颜色 | Token |
|------|------|-------|
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

#### 5.5.2 追踪泳道视觉

- **泳道**：48px 高，1px 分隔线，180px 左侧标签，右侧时间轴区域
- **泳道颜色**：循环使用 accent-pink (supervisor), accent-cyan, success, warning, accent-glow
- **Span**：32px 高圆角矩形，`position: absolute`，`left: {start%}`, `width: {duration%}`
- **Running span**：微光动画（2s linear infinite gradient sweep）
- **Error span**：`glow-pink` box-shadow，hover 展开显示错误消息
- **时间轴标尺**：根据 trace 时长每 5s/30s/5min 分刻度，`font-mono text-xs`

#### 5.5.3 热力图配色

复用现有 `getBarColor` 渐变作为单元格背景：
- 0-69%：`--color-heatmap-low`（cyan 20% 不透明度）
- 70-89%：`--color-heatmap-mid`（amber 40% 不透明度）
- 90-100%：`--color-heatmap-high`（pink 50% 不透明度）

单元格：20x20px，2px 间距。Hover 显示 tooltip：agent 名称、时间窗口、任务数、负载百分比。

#### 5.5.4 组件复用

直接复用：`StatusCard`, `ConfirmDialog`, `showToast`, `getBarColor`, `statusDotColor`, `StepIndicator`, `glass`/`animate-stagger`/`glow-pink-text` CSS 类、所有 `--color-*` 主题 token、`adminFetch`/`AdminApiError`。

需适配：Dashboard agent card → `SwarmAgentCard`（添加能力标签、负载条），Logs SSE 模式 → `SwarmSSE` 类。

#### 5.5.5 i18n 新增 Key

约 80 个新 key 分布在 `en.ts` 和 `zh.ts`，组织为：`navSwarm*`, `swarm*`, `task*`, `crew*`, `knowledge*`, `swarmConnected/Disconnected/Reconnecting`。

---

## 6. Hermes 核心代码变更

### 6.1 Agent 进程内新增模块

```
hermes_agent/
├── swarm/                        # 新增：蜂群模块
│   ├── __init__.py
│   ├── redis_connection.py       # Redis 连接工厂（Sentinel/standalone）
│   ├── connection_config.py      # 连接池大小配置
│   ├── client.py                 # SwarmClient 核心
│   ├── health.py                 # Redis 健康检查
│   ├── messaging.py              # Stream 操作（publish, read, ack, reclaim）
│   ├── exactly_once.py           # 去重、执行守卫、取消、DLQ
│   ├── stalled_scanner.py        # 停滞消息后台扫描器
│   ├── circuit_breaker.py        # 熔断器模式
│   ├── reconnect.py              # 指数退避重连
│   ├── resilient_client.py       # 弹性客户端 + 优雅降级
│   ├── registry.py               # Agent 注册 + 心跳
│   ├── router.py                 # 本地路由（Supervisor 用）
│   ├── knowledge.py              # 共享记忆读写
│   └── tools.py                  # swarm_delegate 等新工具
├── tools/
│   ├── delegate_tool.py          # 现有：扩展支持 swarm 模式
│   └── swarm_tool.py             # 新增：swarm_delegate 工具 handler
└── config.yaml                   # 扩展：swarm 配置段
```

### 6.2 config.yaml 扩展

```yaml
model:
  default: "anthropic/claude-sonnet-4-20250514"
  provider: "openrouter"
  base_url: "https://openrouter.ai/api/v1"

# 新增：蜂群配置
swarm:
  enabled: true
  capabilities:
    - "code-review"
    - "refactoring"
    - "testing"
  max_concurrent_tasks: 3
  message_bus: "redis://hermes-redis:6379/0"
  knowledge_base: "redis://hermes-redis:6379/1"
  heartbeat_interval: 30
  registry_enabled: true
```

### 6.3 新增工具注册

```python
# tools/swarm_tool.py

def check_swarm_requirements() -> bool:
    """检查蜂群功能是否可用。"""
    cfg = _load_config()
    return cfg.get("swarm", {}).get("enabled", False)

def register_swarm_tools(registry: ToolRegistry):
    """注册蜂群相关工具。"""
    registry.register(
        name="swarm_delegate",
        toolset="swarm",
        schema={
            "type": "function",
            "function": {
                "name": "swarm_delegate",
                "description": "将任务委派给蜂群中最合适的 Agent",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "goal": {"type": "string", "description": "任务描述"},
                        "capability": {"type": "string", "description": "所需能力"},
                        "input_data": {"type": "string", "description": "输入数据"},
                        "timeout": {"type": "integer", "default": 120},
                    },
                    "required": ["goal", "capability"],
                },
            },
        },
        handler=handle_swarm_delegate,
        check_fn=check_swarm_requirements,
        requires_env=False,
        is_async=False,  # 关键：使用内部 ThreadPoolExecutor
        description="Delegate task to swarm agents",
        emoji="🐝",
    )
```

### 6.4 Agent 启动流程扩展

```python
# run_agent.py 扩展

class AIAgent:
    def __init__(self, ...):
        # ... 现有初始化 ...
        self._swarm_client: ResilientSwarmClient | None = None

    def _init_swarm(self):
        """初始化蜂群客户端（如果配置了 swarm.enabled）。"""
        cfg = self._load_config()
        swarm_cfg = cfg.get("swarm", {})
        if not swarm_cfg.get("enabled"):
            return

        self._swarm_client = ResilientSwarmClient(
            inner=SwarmClient(
                agent_id=self.agent_id,
                redis_url=swarm_cfg["message_bus"],
                capabilities=swarm_cfg.get("capabilities", []),
                max_tasks=swarm_cfg.get("max_concurrent_tasks", 3),
            ),
            on_degrade=self._on_swarm_degrade,
            on_recover=self._on_swarm_recover,
        )
        self._swarm_client.start()  # 注册 + 启动心跳 + 订阅 stream
```

---

## 7. 数据流示例

### 7.1 用户发起代码审查

```
User (WeChat): "帮我审查 agent_manager.py 的代码质量"
    │
    ▼
Gateway → Supervisor Agent
    │
    ├─ 1. 分析意图：需要 code-review 能力
    ├─ 2. 查询 Registry：Agent #3 有 code-review capability
    ├─ 3. 读取 agent_manager.py 内容
    ├─ 4. 发送 Task 到 hermes:stream:agent.3.tasks
    │     └─ payload: { file: "agent_manager.py", content: "..." }
    │     └─ PUBLISH swarm.advisory.task {notification}
    │
    ▼
Agent #3 收到任务（Stream Consumer 唤醒）
    │
    ├─ 5. 执行代码审查（使用 terminal + file tools）
    ├─ 6. 生成审查报告
    ├─ 7. XADD result to hermes:stream:agent.0.results + XACK task
    │     └─ PUBLISH swarm.advisory.result {notification}
    │
    ▼
Supervisor 收到结果
    │
    ├─ 8. 格式化报告
    └─ 9. 通过 Gateway 发送给用户
```

### 7.2 多 Agent 协作：技术文档翻译

```
User: "把这份 API 文档翻译成英文"
    │
    ▼
Supervisor 分析：
    ├─ 子任务 1：提取文档结构 → Agent #2 (data-analysis)
    ├─ 子任务 2：翻译正文     → Agent #4 (translation)
    └─ 子任务 3：技术校对     → Agent #3 (code-review)
    │
    ├─ 并行发送 Task 1 + Task 2（不同 Agent Stream）
    │   ├─ Agent #2 提取结构 → Result
    │   └─ Agent #4 翻译正文 → Result
    │
    ├─ Task 3 依赖 1+2 结果，串行发送
    │   └─ Agent #3 技术校对 → Result
    │
    └─ Supervisor 合并三个 Result → 返回用户
```

---

## 8. 部署架构

### 8.1 K8s 资源清单

```
kubernetes/
├── swarm/
│   ├── redis-config.yaml        # Redis 配置 ConfigMap
│   ├── redis-secret.yaml        # Redis 密码 Secret
│   ├── redis-pv.yaml            # PV + PVC
│   ├── redis.yaml               # Deployment + Service + Exporter
│   ├── redis-networkpolicy.yaml # NetworkPolicy
│   ├── keda-scaler.yaml         # KEDA 自动扩缩容配置
│   ├── supervisor.yaml          # Supervisor Agent Deployment
│   └── rbac.yaml                # Swarm 相关 RBAC
├── gateway/
│   └── deployment.yaml          # 现有 gateway（扩展 swarm 环境变量）
└── admin/
    └── deployment.yaml          # Admin Panel（扩展 swarm 管理 API）
```

### 8.2 环境变量扩展

```bash
# 每个 Agent Deployment 新增的环境变量
SWARM_ENABLED=true
SWARM_REDIS_URL=redis://hermes-redis:6379/0
SWARM_CAPABILITIES=code-review,refactoring,testing
SWARM_MAX_CONCURRENT_TASKS=3
SWARM_KNOWLEDGE_URL=redis://hermes-redis:6379/1
```

### 8.3 资源规划

| 组件 | CPU Request | CPU Limit | Memory Request | Memory Limit |
|------|------------|-----------|----------------|--------------|
| Redis | 100m | 500m | 128Mi | 512Mi |
| Supervisor Agent | 500m | 2000m | 1Gi | 2Gi |
| Worker Agent (per) | 500m | 2000m | 1Gi | 2Gi |
| Admin Panel | 200m | 1000m | 256Mi | 512Mi |

### 8.4 Phase 1 部署步骤

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

---

## 9. 安全设计

### 9.1 Agent 间通信安全

- 消息总线通过 Redis ACL 限制 channel 访问
- Agent 间 HTTP 调用需携带 Swarm Token（由 Admin API 签发）
- Swarm Token 绑定 Agent ID，无法伪造身份
- SSE Token 一次性使用，30 分钟过期，速率限制

### 9.2 任务隔离

- 每个 Agent 有独立的 K8s ServiceAccount
- 工具执行在各自的 Sandbox 中隔离
- 共享知识库读写分离：所有 Agent 可读，只有知识 owner 可写

### 9.3 资源配额

```python
@dataclass
class SwarmQuota:
    max_tasks_per_agent: int = 3
    max_total_tasks: int = 20
    task_timeout_seconds: int = 300
    max_tokens_per_task: int = 50000
    max_trace_depth: int = 5  # 最大委派深度
```

---

## 10. 分阶段实施计划

### Phase 1: 基础设施 ✅ 已完成（2026-04-26）
- Redis 部署（单节点 + AOF + PVC）
- Agent Registry + 心跳
- 消息传输层（Streams + Pub/Sub 双层）
- Exactly-Once 语义（五层防御）
- 连接管理（Per-Agent 拓扑）
- Admin Panel Swarm 概览页 + Redis 健康卡片
- 基本的单 Agent 路由
- **提前实现**：Sync/Async 桥接（三线程架构 `tools/swarm_tool.py`）
- **提前实现**：熔断器 + 优雅降级（`circuit_breaker.py` + `resilient_client.py`）
- **提前实现**：SSE 一次性 Token 认证（`swarm_routes.py` + `swarm_models.py`）
- **提前实现**：Zustand stores（`swarmRegistry` + `swarmEvents`）
- **提前实现**：SSE EventSource 封装（`swarm-sse.ts`）

**交付物**：Agent 可注册到 Registry、发送任务到 Stream、Redis 故障自动降级。Admin Panel 显示 Agent 列表和 Redis 健康状态。

### Phase 2: 核心通信闭环（2 周）

> 目标：实现完整的"发送任务 → 消费执行 → 返回结果 → 实时展示"闭环。

**后端 — Agent 端 Stream Consumer：**
- Agent 进程内 daemon 线程（`swarm/consumer.py`），XREADGROUP 阻塞消费
- 收到任务后调用 `AIAgent` 单次 LLM 对话执行（不启动完整对话循环）
- 执行完成后 XADD 结果到发送方的 result stream + XACK 任务
- Consumer 生命周期：Agent 启动时创建 Consumer Group + 启动线程，退出时优雅停止

**后端 — SSE 实时事件桥接：**
- `swarm_routes.py` 的 SSE 端点订阅 Redis Pub/Sub advisory 频道
- 将 `swarm.advisory.task/result/online/offline` 事件实时转发给前端 SSE 客户端
- 替换现有的 30s heartbeat-only 事件循环为 Pub/Sub 驱动的事件推送

**前端 — 任务监控：**
- `swarmTasks` Zustand store（任务列表 + 过滤器 + 分页）
- `TaskMonitorPage`：全宽表格 + 过滤栏（status/priority/agent）+ SSE 实时更新
- `TaskDetailPage`：任务元数据 + 结果面板 + 参与者信息

**不包含**（移至 Phase 2b 或更后）：
- 任务追踪 Trace Span 存储和查询 API
- 追踪泳道可视化（TaskDetailPage 中的 trace timeline）
- 停滞消息扫描器（stalled_scanner.py）
- 跨 Agent HTTP 工具调用

**交付物**：Supervisor 发送任务 → Worker Agent 消费执行 → 结果返回 → Admin Panel 实时展示。多 Agent 可协作完成单步任务。

### Phase 2b: 可观测性（1-2 周）— 可选
- 任务追踪（TraceSpan 存储 + 查询 API）
- 追踪泳道可视化（TaskDetailPage 扩展）
- 停滞消息扫描器（stalled_scanner.py）
- Admin `/swarm/metrics` 扩展队列深度和停滞消息指标

**交付物**：完整任务可观测性，停滞任务自动回收

### Phase 3: 知识与编排（4 周）
- 共享记忆层（Redis → Qdrant）
- Crew 管理 UI（含 DAG 编辑器）
- 工作流定义（sequential/parallel/DAG）
- 知识库管理 UI

**交付物**：可视化编排 Agent 组合执行复杂工作流

### Phase 4: 弹性与优化（2 周）
- KEDA 自适应扩缩容
- 负载感知动态路由
- 故障恢复（Sentinel）
- 性能优化
- Redis 监控告警

**交付物**：生产级蜂群系统

---

## 11. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| Redis 单点故障 | 消息丢失、Registry 不可用 | AOF 持久化 + PVC；Phase 2 迁移 Sentinel |
| Agent 委派深度爆炸 | Token 预算耗尽 | MAX_DEPTH=2 硬限制 |
| 消息总线过载 | 延迟增加、任务丢失 | 背压机制（队列深度 10 拒绝）+ 停滞扫描 |
| 共享知识污染 | 所有 Agent 产生错误结果 | 知识审核机制 + 信心度评分 |
| 安全攻击面扩大 | Agent 间横向移动 | Swarm Token + RBAC + 网络策略 |
| Agent 循环阻塞 | Gateway 饥饿、级联故障 | 三线程架构 + 心跳 daemon + is_async=False |
| 连接池耗尽 | Redis 拒绝连接 | Per-Agent 拓扑 + 公式计算 + 监控告警 |
| Redis 网络分区 | 脑裂数据不一致 | Phase 2 Sentinel quorum + 客户端重连 |

---

## 12. 与现有系统的兼容性

### 12.1 向后兼容

- `swarm.enabled: false`（默认）时，Agent 行为完全不变
- 不使用 Redis 时，所有蜂群功能静默禁用
- 新工具（swarm_delegate）仅在 swarm 启用时注册
- Admin Panel 在无 Redis 时隐藏蜂群相关 UI
- Redis 连接失败时自动降级为独立模式（熔断器 + 重连）

### 12.2 渐进式升级路径

```
现有部署 (无蜂群)
    ↓ 安装 Redis (AOF + PVC)
    ↓ Admin Panel 升级（新增 Swarm API + SSE）
    ↓ 创建 Supervisor Agent
    ↓ 现有 Agent 添加 swarm 配置
    ↓ 重启 Agent → 自动注册到蜂群
```

每一步都是可选的，可以部分 Agent 加入蜂群，部分保持独立。

---

## 附录 A：新文件清单

```
kubernetes/swarm/
  redis-config.yaml            # Redis 配置 ConfigMap
  redis-secret.yaml            # Redis 密码 Secret
  redis-pv.yaml                # PV + PVC
  redis.yaml                   # Deployment + Service + Exporter
  redis-networkpolicy.yaml     # NetworkPolicy
  redis-master.yaml            # Phase 2 Master StatefulSet
  redis-sentinel.yaml          # Phase 2 Sentinel Deployment

hermes_agent/swarm/
  redis_connection.py          # Redis 连接工厂（Sentinel/standalone）
  connection_config.py         # 连接池大小配置
  client.py                    # SwarmClient 核心
  health.py                    # Redis 健康检查
  messaging.py                 # Stream 操作（publish, read, ack, reclaim）
  exactly_once.py              # 去重、执行守卫、取消、DLQ
  stalled_scanner.py           # 停滞消息后台扫描器
  circuit_breaker.py           # 熔断器模式
  reconnect.py                 # 指数退避重连
  resilient_client.py          # 弹性客户端 + 优雅降级

tools/
  swarm_tool.py                # swarm_delegate 工具 handler

admin/backend/
  swarm_models.py              # Swarm API Pydantic 模型
  swarm_routes.py              # Swarm API FastAPI 路由

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
  redis-alerts.yaml            # Prometheus 告警规则
```
