# Hermes 智能路由 Phase 3 设计文档 — 任务拆分 + 多 Agent 协作

> 文档版本: 1.0-draft
> 日期: 2026-05-05
> 分支: feature/smart-routing-phase3
> 状态: 设计

---

## 1. 概述

Phase 3 在 Manager Agent 路由基础上引入**任务拆分**能力。当用户提交的任务可以被分解为多个独立或有序的子任务时，Manager Agent 可以生成拆分计划，Orchestrator 负责按依赖关系编排子任务的执行，并将结果聚合返回给用户。

**核心原则**:
- 拆分决策由 Manager Agent 的 LLM 能力驱动，Orchestrator 只做调度执行
- 子任务是独立的一等公民任务，有完整的状态生命周期
- 支持并行执行无依赖的子任务，串行执行有依赖的子任务
- 结果聚合策略由 Manager 在拆分计划中指定

## 2. Task 数据模型扩展

### 2.1 Task 扩展字段

在 `hermes_orchestrator/models/task.py` 的 `Task` dataclass 中新增字段:

```python
@dataclass
class Task:
    task_id: str
    prompt: str
    created_at: float
    # ... 现有字段 ...

    # --- Phase 3: 任务拆分 ---
    parent_task_id: str | None = None          # 父任务 ID（子任务指向父任务）
    subtask_ids: list[str] = field(default_factory=list)  # 子任务 ID 列表
    task_type: str = "simple"                   # "simple" | "parent" | "subtask"
    decomposition_plan: dict | None = None      # 拆分计划（JSON，仅 parent 任务）
    aggregation_strategy: str = "concat"        # "concat" | "summarize" | "merge"
    subtask_index: int = 0                      # 子任务在父任务中的序号
    depends_on_subtasks: list[str] = field(default_factory=list)  # 依赖的子任务 ID
    result_aggregation: dict | None = None      # 聚合结果（仅 parent 任务）
```

### 2.2 新增状态

扩展现有状态机:

```
现有: submitted → queued → assigned → executing → streaming → done/failed

新增:
  submitted → queued → assigned → executing → streaming → done/failed
                                          ↑
  decomposing ────────────────────────────┘  (Manager 正在分析拆分)
  aggregating ────────────────────────────── (等待子任务完成后聚合)
```

| 状态 | 含义 | 适用任务类型 |
|------|------|-------------|
| `decomposing` | Manager 正在分析任务并生成拆分计划 | parent |
| `aggregating` | 所有子任务完成，等待结果聚合 | parent |
| `waiting_subtasks` | 等待子任务执行完成 | parent |

### 2.3 完整状态机

```
用户提交任务
    ↓
submitted → queued
    ↓
检测到需要拆分？
├─ 否 → assigned → executing → streaming → done/failed  (Phase 1/2)
└─ 是 → decomposing (Manager 分析)
         ↓
         生成拆分计划
         ↓
         waiting_subtasks (创建子任务并入队)
         ↓
         子任务执行中 (assigned → executing → streaming → done/failed)
         ↓
         全部子任务完成？
         ├─ 否 → 继续等待
         └─ 是 → aggregating
                  ↓
                  聚合结果
                  ↓
                  done/failed
```

### 2.4 分解计划 JSON 格式

`decomposition_plan` 字段存储 Manager 生成的拆分计划:

```json
{
  "plan_id": "plan-uuid",
  "reasoning": "该任务包含三个独立步骤：数据收集、分析处理、报告生成",
  "subtasks": [
    {
      "subtask_index": 0,
      "description": "从 Redis 读取所有 hermes-agent 任务状态数据",
      "suggested_agent_capability": "terminal",
      "depends_on": [],
      "estimated_complexity": "low"
    },
    {
      "subtask_index": 1,
      "description": "对收集的数据进行统计分析：计算平均执行时长、成功率、各 agent 负载分布",
      "suggested_agent_capability": "terminal",
      "depends_on": [0],
      "estimated_complexity": "medium"
    },
    {
      "subtask_index": 2,
      "description": "生成 CSV 报告文件，包含任务ID、状态、执行时长、分配的 agent",
      "suggested_agent_capability": "file_operations",
      "depends_on": [1],
      "estimated_complexity": "low"
    }
  ],
  "aggregation_strategy": "concat",
  "estimated_total_time_seconds": 120
}
```

## 3. Manager-Worker 编排流程

### 3.1 完整流程

```
[用户] POST /api/v1/tasks {prompt: "复杂任务..."}
    ↓
[Orchestrator] 创建 Task (task_type=simple, status=queued)
    ↓
[Orchestrator] _process_task() 取出任务
    ↓
[Orchestrator] 发送给 Manager Agent 路由请求
    ↓
[Manager Agent] 分析任务:
    option A: decision=route → 选择单个 agent (Phase 2)
    option B: decision=decompose → 生成拆分计划 (Phase 3)
    ↓
[Orchestrator] 收到 decompose 决策
    ↓
[Orchestrator] 更新任务:
    task_type = "parent"
    status = "decomposing"
    decomposition_plan = {...}
    ↓
[Orchestrator] 创建子任务:
    for each subtask in plan:
        child = Task(
            task_id = new_uuid(),
            prompt = subtask.description,
            parent_task_id = parent.task_id,
            task_type = "subtask",
            subtask_index = subtask.subtask_index,
            depends_on_subtasks = subtask.depends_on,
            status = "queued"
        )
        parent.subtask_ids.append(child.task_id)
    ↓
[Orchestrator] 更新父任务 status = "waiting_subtasks"
    ↓
[Orchestrator] 按依赖关系调度子任务:
    - 无依赖的子任务立即入队
    - 有依赖的子任务等待依赖完成后入队
    ↓
[Subtask Worker] 各子任务独立执行 (Phase 1/2 路由到具体 agent)
    ↓
[Orchestrator] 每个子任务完成时检查:
    - 通知依赖它的兄弟子任务可以开始
    - 检查是否所有子任务都完成
    ↓
[Orchestrator] 所有子任务完成:
    status = "aggregating"
    ↓
[Orchestrator] 结果聚合:
    - concat: 拼接所有子任务结果
    - summarize: 发送给 Manager 总结
    - merge: 按序号合并（默认）
    ↓
[Orchestrator] 父任务 status = "done"
    ↓
[用户] GET /api/v1/tasks/{parent_id} 返回完整结果
```

### 3.2 依赖管理

子任务之间的依赖关系通过 DAG（有向无环图）管理:

```python
class SubtaskScheduler:
    """管理子任务的依赖关系和执行顺序。"""

    def __init__(self, task_store: RedisTaskStore, agent_registry: RedisAgentRegistry):
        self._store = task_store
        self._registry = agent_registry
        self._pending: dict[str, set[str]] = {}  # subtask_id -> set of pending deps

    def register_subtasks(self, parent: Task, plan: dict, resolved_deps: dict[str, list[str]] | None = None) -> None:
        """注册子任务及其依赖关系。

        Args:
            parent: 父任务对象。
            plan: Manager 生成的拆分计划 JSON。
            resolved_deps: 已解析的 ID-based 依赖映射（subtask_id -> [dep_task_ids]）。
                           如果为 None，则从 plan 的整数索引推导（向后兼容）。

        Raises:
            CycleError: 如果依赖图包含循环，拒绝注册并标记父任务失败。
        """
        subtask_map = {s["subtask_index"]: s for s in plan["subtasks"]}
        id_by_index = {st.subtask_index: st.task_id for st in self._get_subtasks(parent)}

        for index, subtask_plan in subtask_map.items():
            subtask_id = id_by_index[index]
            if resolved_deps is not None and subtask_id in resolved_deps:
                dep_ids = set(resolved_deps[subtask_id])
            else:
                dep_indices = subtask_plan.get("depends_on", [])
                dep_ids = {id_by_index[i] for i in dep_indices}
            self._pending[subtask_id] = dep_ids

        # 循环检测：使用 Kahn's 算法验证 DAG
        self._validate_no_cycles(parent.task_id)

    def _validate_no_cycles(self, parent_task_id: str) -> None:
        """使用 Kahn's 算法检测依赖图中的循环。

        如果存在循环，说明 Manager 生成的拆分计划有误，
        此时将父任务标记为 failed 并抛出 CycleError。
        """
        in_degree: dict[str, int] = {sid: 0 for sid in self._pending}
        adjacency: dict[str, list[str]] = {sid: [] for sid in self._pending}

        for sid, deps in self._pending.items():
            in_degree[sid] = len(deps)
            for dep in deps:
                if dep in adjacency:
                    adjacency[dep].append(sid)

        queue = [sid for sid, deg in in_degree.items() if deg == 0]
        visited_count = 0

        while queue:
            node = queue.pop(0)
            visited_count += 1
            for neighbor in adjacency[node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if visited_count != len(self._pending):
            # 存在循环 —— 无法完成拓扑排序
            cycle_nodes = [sid for sid, deg in in_degree.items() if deg > 0]
            self._pending.clear()
            raise CycleError(
                f"Dependency cycle detected among subtasks: {cycle_nodes}. "
                f"Parent task {parent_task_id} will be marked as failed."
            )

    def get_ready_subtasks(self) -> list[str]:
        """返回所有依赖已满足的子任务 ID。"""
        ready = []
        for subtask_id, deps in list(self._pending.items()):
            if not deps:
                ready.append(subtask_id)
        return ready

    def notify_completion(self, completed_subtask_id: str) -> list[str]:
        """通知某个子任务完成，返回因此变得可执行的子任务列表。"""
        newly_ready = []
        for subtask_id, deps in list(self._pending.items()):
            deps.discard(completed_subtask_id)
            if not deps and subtask_id != completed_subtask_id:
                newly_ready.append(subtask_id)
        self._pending.pop(completed_subtask_id, None)
        return newly_ready

    def get_pending_ids(self) -> set[str]:
        """返回所有仍在等待依赖的子任务 ID（用于取消操作）。"""
        return set(self._pending.keys())

    def _get_subtasks(self, parent: Task) -> list[Task]:
        """从 store 获取所有子任务。"""
        result = []
        for sid in parent.subtask_ids:
            st = self._store.get(sid)
            if st:
                result.append(st)
        return result


class CycleError(Exception):
    """当子任务依赖图包含循环时抛出。"""
    pass
```

### 3.3 并行执行

子任务通过现有的 Redis Stream 并行分发:

```python
async def _execute_decomposition(parent_task_id: str, plan: dict):
    """执行拆分计划。

    这是唯一负责将 decomposition_plan 中的整数索引依赖转换为
    实际 task ID 依赖的地方。所有下游代码（SubtaskScheduler、
    _on_subtask_completed 等）只使用 task ID，不再触碰整数索引。
    """
    loop = asyncio.get_event_loop()
    parent = await loop.run_in_executor(None, task_store.get, parent_task_id)

    # ── 唯一的 index → task_id 转换点 ──
    # 第一步：创建子任务，建立 index → task_id 映射
    index_to_id: dict[int, str] = {}
    for st_plan in plan["subtasks"]:
        child = Task(
            task_id=str(uuid.uuid4()),
            prompt=st_plan["description"],
            created_at=time.time(),
            parent_task_id=parent_task_id,
            task_type="subtask",
            subtask_index=st_plan["subtask_index"],
            # 这里先不填 depends_on_subtasks，下一轮统一转换
            timeout_seconds=parent.timeout_seconds / len(plan["subtasks"]),
            max_retries=1,
        )
        task_store.create(child)
        parent.subtask_ids.append(child.task_id)
        index_to_id[st_plan["subtask_index"]] = child.task_id

    # 第二步：用 index_to_id 将所有依赖从整数索引转为 task ID
    resolved_deps: dict[str, list[str]] = {}
    for st_plan in plan["subtasks"]:
        child_id = index_to_id[st_plan["subtask_index"]]
        dep_ids = [index_to_id[i] for i in st_plan.get("depends_on", [])]
        resolved_deps[child_id] = dep_ids
        # 回写子任务的 depends_on_subtasks 字段
        child = task_store.get(child_id)
        if child:
            child.depends_on_subtasks = dep_ids
            task_store.update(child_id, depends_on_subtasks=dep_ids)

    task_store.update(
        parent_task_id,
        status="waiting_subtasks",
        subtask_ids=parent.subtask_ids,
        decomposition_plan=plan,
        aggregation_strategy=plan.get("aggregation_strategy", "concat"),
    )

    # 第三步：注册依赖（传入已解析的 ID-based 依赖）
    scheduler = SubtaskScheduler(task_store, agent_registry)
    scheduler.register_subtasks(parent, plan, resolved_deps=resolved_deps)

    # 持久化 scheduler 状态以支持重启恢复（见 H3 修复）
    await _persist_scheduler_state(parent_task_id, scheduler)

    # 入队无依赖的子任务
    for ready_id in scheduler.get_ready_subtasks():
        ready_task = task_store.get(ready_id)
        if ready_task:
            task_store.enqueue(ready_task)
```

### 3.4 调度器状态持久化（重启恢复）

`SubtaskScheduler` 实例不能仅存在于内存中的局部变量，否则 Orchestrator 重启后依赖追踪全部丢失。将 DAG 状态持久化到 Redis：

```python
# Redis key: hermes:scheduler:{parent_task_id}
# Value: JSON { "parent_task_id": str, "pending": { subtask_id: [dep_ids] } }

SCHEDULER_KEY_PREFIX = "hermes:scheduler:"

async def _persist_scheduler_state(parent_task_id: str, scheduler: SubtaskScheduler) -> None:
    """将 SubtaskScheduler 的 DAG 状态写入 Redis，用于重启恢复。"""
    loop = asyncio.get_event_loop()
    state = {
        "parent_task_id": parent_task_id,
        "pending": {sid: list(deps) for sid, deps in scheduler._pending.items()},
    }
    key = f"{SCHEDULER_KEY_PREFIX}{parent_task_id}"
    await loop.run_in_executor(
        None, partial(task_store._r.json().set, key, "$", json.dumps(state))
    )

async def _restore_scheduler(parent_task_id: str) -> SubtaskScheduler | None:
    """从 Redis 恢复 SubtaskScheduler 实例。如果无持久化状态则返回 None。"""
    loop = asyncio.get_event_loop()
    key = f"{SCHEDULER_KEY_PREFIX}{parent_task_id}"
    raw = await loop.run_in_executor(None, partial(task_store._r.json().get, key))
    if not raw:
        return None
    state = json.loads(raw)
    scheduler = SubtaskScheduler(task_store, agent_registry)
    for sid, dep_list in state["pending"].items():
        scheduler._pending[sid] = set(dep_list)
    return scheduler

async def _delete_scheduler_state(parent_task_id: str) -> None:
    """父任务完成后清理持久化的调度器状态。"""
    loop = asyncio.get_event_loop()
    key = f"{SCHEDULER_KEY_PREFIX}{parent_task_id}"
    await loop.run_in_executor(None, task_store._r.delete, key)
```

在现有的 `_recover_in_flight_tasks` 中增加调度器恢复逻辑：

```python
async def _recover_in_flight_tasks():
    """Orchestrator 启动时恢复未完成任务（含 Phase 3 调度器恢复）。"""
    # ... 现有恢复逻辑 ...

    # Phase 3: 恢复 waiting_subtasks 状态的父任务
    waiting_parents = task_store.list_by_status("waiting_subtasks")
    for parent in waiting_parents:
        scheduler = await _restore_scheduler(parent.task_id)
        if scheduler is None:
            # 调度器状态丢失（升级前创建的任务），从 decomposition_plan 重建
            scheduler = SubtaskScheduler(task_store, agent_registry)
            # 使用已持久化的 depends_on_subtasks 字段重建
            for sid in parent.subtask_ids:
                st = task_store.get(sid)
                if st and st.status in ("queued", "assigned", "executing"):
                    scheduler._pending[sid] = set(st.depends_on_subtasks)

        # 将已完成的子任务从 pending 中移除，并重新调度就绪的子任务
        for sid in parent.subtask_ids:
            st = task_store.get(sid)
            if st and st.status in ("done", "failed"):
                scheduler.notify_completion(sid)

        for ready_id in scheduler.get_ready_subtasks():
            ready_task = task_store.get(ready_id)
            if ready_task and ready_task.status == "queued":
                task_store.enqueue(ready_task)

        # 重新持久化恢复后的状态
        await _persist_scheduler_state(parent.task_id, scheduler)
```

### 3.5 结果聚合

当所有子任务完成后，Orchestrator 聚合结果:

```python
async def _aggregate_results(parent_task_id: str):
    """聚合子任务结果。"""
    loop = asyncio.get_event_loop()
    parent = await loop.run_in_executor(None, task_store.get, parent_task_id)

    # 收集子任务结果
    subtask_results = []
    for sid in sorted(parent.subtask_ids, key=lambda x: _get_subtask_index(task_store, x)):
        st = await loop.run_in_executor(None, task_store.get, sid)
        if st and st.result:
            subtask_results.append({
                "index": st.subtask_index,
                "content": st.result.content,
                "duration": st.result.duration_seconds,
                "agent": st.assigned_agent,
            })

    strategy = parent.aggregation_strategy

    if strategy == "concat":
        # 简单拼接
        aggregated = "\n\n---\n\n".join(
            f"### 子任务 {r['index']} (by {r['agent']})\n{r['content']}"
            for r in subtask_results
        )
    elif strategy == "summarize":
        # 发送给 Manager 总结
        aggregated = await _summarize_via_manager(parent, subtask_results)
    else:
        # merge: 按序号合并
        aggregated = "\n\n".join(r["content"] for r in subtask_results)

    # 计算总用时
    total_duration = sum(r["duration"] for r in subtask_results)
    total_usage = {"subtask_count": len(subtask_results)}

    await loop.run_in_executor(
        None,
        partial(
            task_store.update,
            parent_task_id,
            status="done",
            result=TaskResult(
                content=aggregated,
                usage=total_usage,
                duration_seconds=total_duration,
                run_id="",
            ),
        ),
    )
```

## 4. PG 混合存储设计

### 4.1 设计动机

Redis 适合热数据（任务队列、agent 状态、circuit breaker），但对于以下场景需要持久化存储:

- 路由决策审计
- 任务拆分计划持久化
- 历史任务查询
- agent 能力档案

### 4.2 表结构设计

```sql
-- Agent 静态 profile（Discovery 写入）
CREATE TABLE agents (
    agent_id       VARCHAR(128) PRIMARY KEY,
    gateway_url    VARCHAR(512) NOT NULL,
    role           VARCHAR(32) DEFAULT 'worker',
    status         VARCHAR(32) DEFAULT 'online',
    soul_summary   TEXT DEFAULT '',
    soul_hash      VARCHAR(64) DEFAULT '',
    capabilities   TEXT DEFAULT '',  -- JSON array
    max_concurrent INTEGER DEFAULT 10,
    registered_at  TIMESTAMPTZ DEFAULT NOW(),
    last_seen_at   TIMESTAMPTZ DEFAULT NOW(),
    metadata       JSONB DEFAULT '{}'
);

CREATE INDEX idx_agents_role ON agents(role);
CREATE INDEX idx_agents_status ON agents(status);

-- 路由决策审计（每次路由决策写一条）
CREATE TABLE task_routes (
    id              BIGSERIAL PRIMARY KEY,
    task_id         VARCHAR(128) NOT NULL,
    manager_id      VARCHAR(128) REFERENCES agents(agent_id) ON DELETE SET NULL,
    selected_id     VARCHAR(128) REFERENCES agents(agent_id) ON DELETE SET NULL,
    decision_type   VARCHAR(32) NOT NULL,  -- 'route' | 'decompose'
    confidence      FLOAT,
    reasoning       TEXT,
    fallback_used   BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_routes_task ON task_routes(task_id);
CREATE INDEX idx_routes_created ON task_routes(created_at);

-- 任务拆分计划
CREATE TABLE task_plans (
    plan_id         VARCHAR(128) PRIMARY KEY,
    parent_task_id  VARCHAR(128) NOT NULL,
    manager_id      VARCHAR(128),
    reasoning       TEXT,
    aggregation_strategy VARCHAR(32) DEFAULT 'concat',
    estimated_time  FLOAT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- 子任务
CREATE TABLE subtasks (
    subtask_id      VARCHAR(128) PRIMARY KEY,
    parent_task_id  VARCHAR(128) NOT NULL,
    plan_id         VARCHAR(128) REFERENCES task_plans(plan_id),
    subtask_index   INTEGER NOT NULL,
    description     TEXT NOT NULL,
    assigned_agent  VARCHAR(128),
    status          VARCHAR(32) DEFAULT 'queued',
    depends_on      INTEGER[] DEFAULT '{}',  -- 依赖的子任务 index 列表
    result_content  TEXT,
    duration_seconds FLOAT DEFAULT 0,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    completed_at    TIMESTAMPTZ
);

CREATE INDEX idx_subtasks_parent ON subtasks(parent_task_id);
CREATE INDEX idx_subtasks_status ON subtasks(status);
```

### 4.3 Redis vs PG 分工

| 数据类型 | 存储 | 理由 |
|---------|------|------|
| 任务队列（stream） | Redis | 高吞吐，消费者组 |
| 任务实时状态 | Redis | 低延迟读写，频繁更新 |
| Agent 注册表（热） | Redis | 毫秒级查询，Discovery 写入 |
| Agent Profile（冷） | PG | 持久化，支持复杂查询 |
| 路由决策日志 | PG | 审计查询，不需要低延迟 |
| 任务拆分计划 | PG | 结构化持久化，关联查询 |
| 子任务关系 | PG | DAG 查询，依赖分析 |
| 任务最终结果 | Redis (热) + PG (冷) | Redis 返回实时结果，PG 存历史 |

### 4.4 同步策略

```
Discovery Loop (30s)
    → 发现 Pod → Redis AgentProfile (实时)
    → 同时写入 PG agents 表 (upsert)

路由决策完成
    → Redis: 更新 task status + metadata
    → PG: INSERT task_routes (异步写入)

子任务完成
    → Redis: 更新 task status
    → PG: UPDATE subtasks (异步写入)

父任务完成
    → Redis: 更新 task result
    → PG: UPDATE subtasks + task_routes (异步批量写入)
```

### 4.5 PG 写入策略

使用 write-behind 模式，避免阻塞主路径:

```python
class AuditWriter:
    """异步写入审计日志到 PG，不阻塞主流程。"""

    def __init__(self, pg_pool):
        self._pool = pg_pool
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=10000)

    async def start(self):
        asyncio.create_task(self._drain_loop())

    async def record_route(self, route: dict):
        await self._queue.put(("route", route))

    async def record_plan(self, plan: dict):
        await self._queue.put(("plan", plan))

    async def _drain_loop(self):
        while True:
            batch = []
            try:
                item = await asyncio.wait_for(self._queue.get(), timeout=5.0)
                batch.append(item)
                # 批量获取更多
                while not self._queue.empty() and len(batch) < 50:
                    batch.append(self._queue.get_nowait())
            except asyncio.TimeoutError:
                pass

            if not batch:
                continue

            try:
                async with self._pool.acquire() as conn:
                    for item_type, data in batch:
                        if item_type == "route":
                            await conn.execute(
                                """INSERT INTO task_routes
                                   (task_id, manager_id, selected_id, decision_type,
                                    confidence, reasoning, fallback_used)
                                   VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                                data["task_id"], data.get("manager_id"),
                                data.get("selected_id"), data["decision_type"],
                                data.get("confidence"), data.get("reasoning"),
                                data.get("fallback_used", False),
                            )
            except Exception as e:
                logger.error("Audit write failed: %s", e)
```

## 5. _process_task() 完整改造

### 5.1 Phase 3 完整流程

```python
async def _process_task(task_id: str):
    loop = asyncio.get_event_loop()
    task = await loop.run_in_executor(None, task_store.get, task_id)
    if not task:
        return

    # 跳过子任务之外的 parent 任务（parent 不会被 worker 直接执行）
    if task.task_type == "parent":
        return

    agents = await loop.run_in_executor(None, agent_registry.list_agents)
    managers = [a for a in agents if a.role == "manager" and a.status in ("online", "degraded")]
    workers = [a for a in agents if a.role != "manager" and a.status in ("online", "degraded")]

    chosen = None

    # --- Phase 2/3: Manager routing ---
    if managers and workers and config.manager_routing_enabled:
        routing_result = await _route_via_manager(task, managers[0], workers)

        if routing_result and routing_result.get("decision") == "decompose":
            # Phase 3: 任务拆分
            await _execute_decomposition(task_id, routing_result["decomposition_plan"])
            return
        elif routing_result and routing_result.get("decision") == "route":
            # Phase 2: 直接路由
            chosen = next(
                (w for w in workers if w.agent_id == routing_result["selected_agent"]),
                None,
            )

    # --- Phase 1 fallback ---
    if chosen is None and config.manager_routing_fallback:
        chosen = selector.select(workers, task)

    if not chosen:
        await loop.run_in_executor(
            None, partial(task_store.update, task_id, status="failed",
                          error="No available agent")
        )
        return

    # --- 执行任务（与 Phase 1 相同）---
    await loop.run_in_executor(
        None, partial(task_store.update, task_id, status="assigned",
                      assigned_agent=chosen.agent_id)
    )
    await loop.run_in_executor(
        None, agent_registry.update_load, chosen.agent_id, chosen.current_load + 1
    )
    try:
        run_id = await executor.submit_run(
            chosen.gateway_url, task.prompt, task.instructions,
            headers=chosen.gateway_headers(),
        )
        await loop.run_in_executor(
            None, partial(task_store.update, task_id, status="executing", run_id=run_id)
        )
        await loop.run_in_executor(
            None, partial(task_store.update, task_id, status="streaming")
        )
        run_result = await executor.consume_run_events(
            chosen.gateway_url, run_id, task.timeout_seconds,
            headers=chosen.gateway_headers(),
        )
        if run_result.status == "completed":
            result = executor.extract_result(
                {"output": run_result.output, "usage": run_result.usage or {},
                 "run_id": run_id},
                task,
            )
            await loop.run_in_executor(
                None, partial(task_store.update, task_id, status="done", result=result)
            )
            if chosen.agent_id in circuits:
                circuits[chosen.agent_id].record_success()
        else:
            await loop.run_in_executor(
                None, partial(task_store.update, task_id, status="failed",
                              error=run_result.error or "Run failed")
            )
            circuits.setdefault(chosen.agent_id, CircuitBreaker(
                failure_threshold=config.circuit_failure_threshold,
                success_threshold=config.circuit_success_threshold,
                recovery_timeout=config.circuit_recovery_timeout,
            )).record_failure()
    except Exception as e:
        current = await loop.run_in_executor(None, task_store.get, task_id)
        if current and current.retry_count < current.max_retries:
            new_count = current.retry_count + 1
            await loop.run_in_executor(
                None, partial(task_store.update, task_id, status="queued",
                              assigned_agent=None, run_id=None, error=None,
                              retry_count=new_count)
            )
            requeued = await loop.run_in_executor(None, task_store.get, task_id)
            if requeued:
                await loop.run_in_executor(None, task_store.enqueue, requeued)
        else:
            await loop.run_in_executor(
                None, partial(task_store.update, task_id, status="failed", error=str(e))
            )
        circuits.setdefault(chosen.agent_id, CircuitBreaker(
            failure_threshold=config.circuit_failure_threshold,
            success_threshold=config.circuit_success_threshold,
            recovery_timeout=config.circuit_recovery_timeout,
        )).record_failure()
    finally:
        updated = await loop.run_in_executor(None, agent_registry.get, chosen.agent_id)
        if updated:
            await loop.run_in_executor(
                None, agent_registry.update_load,
                chosen.agent_id, max(0, updated.current_load - 1)
            )

        # --- Phase 3: 检查是否为子任务完成 ---
        task = await loop.run_in_executor(None, task_store.get, task_id)
        if task and task.parent_task_id and task.status == "done":
            await _on_subtask_completed(task)
```

### 5.2 子任务完成回调

```python
async def _on_subtask_completed(subtask: Task):
    """子任务完成后的处理：检查父任务状态。"""
    loop = asyncio.get_event_loop()
    parent = await loop.run_in_executor(None, task_store.get, subtask.parent_task_id)
    if not parent:
        return

    # 恢复或获取调度器
    scheduler = await _restore_scheduler(parent.task_id)
    if scheduler is None:
        return

    # 如果当前子任务失败，立即取消所有剩余的 pending/queued 子任务
    if subtask.status == "failed":
        await _cancel_pending_subtasks(parent, scheduler)
        # 标记父任务失败
        await loop.run_in_executor(
            None, partial(
                task_store.update, parent.task_id, status="failed",
                error=f"Subtask {subtask.subtask_index} failed: {subtask.error or 'unknown error'}. "
                      f"All remaining subtasks cancelled."
            )
        )
        await _delete_scheduler_state(parent.task_id)
        # 发送回调
        parent = await loop.run_in_executor(None, task_store.get, parent.task_id)
        if parent and parent.callback_url:
            asyncio.create_task(_send_callback(parent))
        return

    # 子任务成功完成：通知依赖此子任务的其他子任务可以开始
    ready_ids = scheduler.notify_completion(subtask.task_id)
    for ready_id in ready_ids:
        ready_task = await loop.run_in_executor(None, task_store.get, ready_id)
        if ready_task:
            await loop.run_in_executor(None, task_store.enqueue, ready_task)

    # 持久化更新后的调度器状态
    await _persist_scheduler_state(parent.task_id, scheduler)

    # 检查所有兄弟子任务状态
    all_done = True
    for sid in parent.subtask_ids:
        st = await loop.run_in_executor(None, task_store.get, sid)
        if not st or st.status not in ("done", "failed"):
            all_done = False
            break

    if not all_done:
        return

    # 所有子任务完成（且均为成功，因为失败已提前返回）
    await loop.run_in_executor(
        None, partial(task_store.update, parent.task_id, status="aggregating")
    )
    await _aggregate_results(parent.task_id)
    await _delete_scheduler_state(parent.task_id)

    # 发送回调
    parent = await loop.run_in_executor(None, task_store.get, parent.task_id)
    if parent and parent.callback_url:
        asyncio.create_task(_send_callback(parent))


async def _cancel_pending_subtasks(parent: Task, scheduler: SubtaskScheduler) -> None:
    """取消所有仍在 pending/queued 状态的子任务。

    当任意子任务失败时调用，避免兄弟子任务继续执行（浪费资源且结果无用）。
    已完成（done）的子任务不受影响。
    """
    loop = asyncio.get_event_loop()
    for sid in parent.subtask_ids:
        st = await loop.run_in_executor(None, task_store.get, sid)
        if st and st.status in ("queued", "assigned", "executing", "streaming"):
            await loop.run_in_executor(
                None,
                partial(
                    task_store.update, sid,
                    status="failed",
                    error="Cancelled: sibling subtask failed"
                )
            )
            scheduler.notify_completion(sid)
```

## 6. 前端交互设计

### 6.1 任务拆分确认流程

```
用户提交任务
    → 前端显示 "任务分析中..."
    → Manager 返回 decompose 决策
    → 前端展示拆分计划预览:
        ┌──────────────────────────────────────┐
        │ 任务将被拆分为 3 个子任务:             │
        │                                      │
        │ ① 数据收集 (预估: 30s)               │
        │   → hermes-coder                     │
        │                                      │
        │ ② 统计分析 (预估: 45s)               │
        │   → hermes-coder (依赖 ①)            │
        │                                      │
        │ ③ 生成报告 (预估: 25s)               │
        │   → hermes-coder (依赖 ②)            │
        │                                      │
        │ [确认执行]  [修改计划]  [整包执行]      │
        └──────────────────────────────────────┘
    → 用户点击 [确认执行]
    → 子任务开始执行
```

### 6.2 子任务时间线

```
任务 #abc123 "分析任务数据并生成报告"
├── 状态: 执行中 (2/3 子任务完成)
│
├── ① 数据收集 ✓ (12.3s) — hermes-coder
│   └── 结果: 读取了 1,234 条任务记录
│
├── ② 统计分析 ● 执行中 — hermes-coder
│   └── 已用时: 8s
│
└── ③ 生成报告 ○ 等待 ② 完成
    └── 分配: hermes-coder
```

### 6.3 API 扩展

```python
# 获取任务的子任务列表
@app.get("/api/v1/tasks/{task_id}/subtasks")
async def list_subtasks(task_id: str):
    task = task_store.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    subtasks = []
    for sid in task.subtask_ids:
        st = task_store.get(sid)
        if st:
            subtasks.append({
                "task_id": st.task_id,
                "subtask_index": st.subtask_index,
                "status": st.status,
                "assigned_agent": st.assigned_agent,
                "depends_on": st.depends_on_subtasks,
                "result": st.result.__dict__ if st.result else None,
                "duration_seconds": st.result.duration_seconds if st.result else None,
            })
    return {
        "parent_task_id": task_id,
        "decomposition_plan": task.decomposition_plan,
        "aggregation_strategy": task.aggregation_strategy,
        "subtasks": sorted(subtasks, key=lambda x: x["subtask_index"]),
    }


# 获取任务路由历史
@app.get("/api/v1/tasks/{task_id}/routing")
async def get_routing_history(task_id: str):
    # 从 PG 查询
    routes = await pg_audit.get_routes_for_task(task_id)
    return {"task_id": task_id, "routes": routes}


# 手动重路由
@app.post("/api/v1/tasks/{task_id}/reroute")
async def reroute_task(task_id: str, target_agent_id: str | None = None):
    task = task_store.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status not in ("queued", "assigned"):
        raise HTTPException(status_code=400, detail="Can only reroute queued/assigned tasks")
    # 清除当前分配，重新入队
    task_store.update(task_id, status="queued", assigned_agent=None, run_id=None)
    if target_agent_id:
        task.metadata["preferred_agent"] = target_agent_id
    requeued = task_store.get(task_id)
    if requeued:
        task_store.enqueue(requeued)
    return {"status": "rerouted", "task_id": task_id}


# 取消子任务
@app.post("/api/v1/tasks/{task_id}/subtasks/{subtask_id}/cancel")
async def cancel_subtask(task_id: str, subtask_id: str):
    subtask = task_store.get(subtask_id)
    if not subtask or subtask.parent_task_id != task_id:
        raise HTTPException(status_code=404, detail="Subtask not found")
    if subtask.status in ("done", "failed"):
        raise HTTPException(status_code=409, detail="Subtask already completed")
    task_store.update(subtask_id, status="failed", error="Cancelled by user")
    # 触发依赖检查
    await _on_subtask_completed(subtask)
    return {"status": "cancelled", "subtask_id": subtask_id}
```

## 7. 与 Swarm 模块的关系

### 7.1 现有 Swarm WorkflowEngine

`swarm/workflow.py` 提供了一个 DAG 工作流引擎:

| 能力 | Swarm WorkflowEngine | Orchestrator 编排 |
|------|---------------------|------------------|
| 任务分发 | Redis Streams (hermes:swarm:task:*) | Gateway API (POST /v1/runs) |
| 结果收集 | Redis BLPOP (hermes:swarm:result:*) | SSE stream (GET /v1/runs/{id}/events) |
| DAG 执行 | 内置拓扑排序 + 并行 | 通过 Manager 拆分 + Orchestrator 调度 |
| Agent 通信 | 点对点 Redis Streams | 通过 Orchestrator 中转 |
| 适用场景 | Agent 间协作（用户 Agent 内部） | 外部任务接入（API 级别） |

### 7.2 分工原则

```
┌─────────────────────────────────────────────┐
│              用户 / 外部系统                   │
│                  ↓ POST /tasks                │
├─────────────────────────────────────────────┤
│           Orchestrator (Phase 3)             │
│  - 接收外部任务                               │
│  - Manager Agent 路由/拆分                    │
│  - 子任务 DAG 编排                            │
│  - 结果聚合                                   │
│                  ↓ POST /v1/runs              │
├─────────────────────────────────────────────┤
│              Gateway (Agent)                 │
│  - 执行单个任务                               │
│  - 内部可使用 Swarm WorkflowEngine           │
│  - delegate_tool → 子 agent                  │
│                  ↓ Redis Streams              │
├─────────────────────────────────────────────┤
│            Swarm WorkflowEngine              │
│  - Agent 内部 DAG 工作流                      │
│  - 同一用户 session 内的多 agent 协作          │
│  - Redis Streams 点对点通信                   │
└─────────────────────────────────────────────┘
```

### 7.3 何时用 Orchestrator 编排 vs Swarm 编排

| 场景 | 使用 Orchestrator | 使用 Swarm |
|------|------------------|-----------|
| 外部 API 提交的任务 | 是 | 否 |
| Agent 内部的工具调用链 | 否 | 是 |
| 跨 Gateway 实例的协作 | 是 | 否（同进程内） |
| 同一 Gateway 内的子任务 | 否 | 是（更高效） |
| 用户触发的长流程任务 | 是 | 辅助 |
| Agent 主动发起的协作 | 否 | 是 |

### 7.4 集成方案

Orchestrator 的任务拆分结果可以触发 Swarm 级别的工作流:

```python
# 当 Manager 拆分任务时，可以考虑子任务是否适合用 Swarm 内部编排
# 例如：如果多个子任务都在同一个 Gateway 上执行，
# Orchestrator 可以将它们打包为一个 Swarm WorkflowDef 提交给该 Gateway
```

这是远期优化方向，Phase 3 先实现 Orchestrator 级别的独立编排。

## 8. 配置扩展

### 8.1 OrchestratorConfig Phase 3 新增

```python
class OrchestratorConfig:
    # ... Phase 2 字段 ...

    self.decomposition_enabled = os.environ.get(
        "DECOMPOSITION_ENABLED", "false"
    ).lower() in ("true", "1", "yes")
    self.max_subtasks_per_parent = int(
        os.environ.get("MAX_SUBTASKS_PER_PARENT", "10")
    )
    self.max_decomposition_depth = int(
        os.environ.get("MAX_DECOMPOSITION_DEPTH", "2")
    )
    self.subtask_timeout_ratio = float(
        os.environ.get("SUBTASK_TIMEOUT_RATIO", "0.5")
    )

    # PG 配置
    self.pg_url = os.environ.get("PG_URL", "")
    self.audit_enabled = bool(self.pg_url)
```

### 8.2 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DECOMPOSITION_ENABLED` | `false` | 是否启用任务拆分 |
| `MAX_SUBTASKS_PER_PARENT` | `10` | 单个父任务最大子任务数 |
| `MAX_DECOMPOSITION_DEPTH` | `2` | 最大拆分深度（不允许无限递归） |
| `SUBTASK_TIMEOUT_RATIO` | `0.5` | 子任务超时 = 父任务超时 * ratio / 子任务数 |
| `PG_URL` | `""` | PostgreSQL 连接字符串（空则禁用 PG） |

## 9. 测试计划

### 9.1 单元测试

| 测试 | 验证点 |
|------|--------|
| `test_task_decomposition_plan_parsing` | 正确解析拆分计划 JSON |
| `test_subtask_scheduler_register` | 正确注册依赖关系 |
| `test_subtask_scheduler_get_ready` | 返回无依赖的子任务 |
| `test_subtask_scheduler_notify` | 完成通知触发新就绪子任务 |
| `test_subtask_scheduler_dag_cycle_detection` | 检测循环依赖 |
| `test_aggregate_concat` | concat 策略正确拼接 |
| `test_aggregate_summarize` | summarize 策略调用 Manager |
| `test_max_subtasks_limit` | 超过限制时拒绝拆分 |
| `test_max_depth_limit` | 子任务不能继续拆分 |

### 9.2 集成测试

| 测试 | 验证点 |
|------|--------|
| `test_decompose_e2e` | 从 Manager 拆分到子任务完成到聚合全流程 |
| `test_parallel_subtasks` | 无依赖子任务并行执行 |
| `test_sequential_subtasks` | 有依赖子任务串行执行 |
| `test_subtask_failure_propagation` | 子任务失败传播到父任务 |
| `test_partial_subtask_cancel` | 取消部分子任务后继续执行 |
| `test_pg_audit_write` | 路由决策正确写入 PG |

### 9.3 负载测试

| 测试 | 验证点 |
|------|--------|
| `test_10_parallel_decompositions` | 10 个拆分任务并行执行 |
| `test_deep_dag_execution` | 5 层深度的 DAG 执行 |
| `test_many_small_subtasks` | 100 个子任务的拆分执行 |

## 10. 实施步骤

### Phase 3a: 基础拆分（MVP）

1. **扩展 Task 模型** — 新增 parent_task_id, subtask_ids, task_type 等字段
2. **扩展 RoutingService** — 支持 decompose 决策解析
3. **实现 SubtaskScheduler** — 依赖关系管理
4. **改造 _process_task()** — 增加 decompose 分支
5. **实现 _on_subtask_completed()** — 完成回调
6. **实现基础聚合 (concat)** — 简单拼接策略
7. **编写测试** — 单元测试 + 集成测试

### Phase 3b: PG 持久化

8. **创建 PG 表结构** — agents, task_routes, task_plans, subtasks
9. **实现 AuditWriter** — 异步写入审计日志
10. **Discovery 同步到 PG** — agent profile 双写
11. **历史任务迁移** — Redis → PG 冷数据迁移

### Phase 3c: 前端交互

12. **子任务列表 API** — GET /tasks/{id}/subtasks
13. **路由历史 API** — GET /tasks/{id}/routing
14. **手动干预 API** — reroute, cancel subtask
15. **前端时间线组件** — 子任务进度展示

### Phase 3d: 高级聚合

16. **Summarize 聚合** — Manager 总结子任务结果
17. **Merge 聚合** — 结构化结果合并
18. **拆分确认流程** — 前端预览 + 用户确认
```

---

以下是影响设计的关键文件摘要：

**Orchestrator 核心模块（将要修改）：**
- `/mnt/disk01/workspaces/worksummary/hermes-agent/hermes_orchestrator/main.py` -- 添加 Manager 路由分支，`_process_task()` 重构，子任务完成回调
- `/mnt/disk01/workspaces/worksummary/hermes-agent/hermes_orchestrator/models/agent.py` -- 添加 `role`、`soul_summary`、`soul_hash`、`capabilities_summary` 字段
- `/mnt/disk01/workspaces/worksummary/hermes-agent/hermes_orchestrator/models/task.py` -- 添加 `parent_task_id`、`subtask_ids`、`task_type`、`decomposition_plan` 字段
- `/mnt/disk01/workspaces/worksummary/hermes-agent/hermes_orchestrator/services/agent_discovery.py` -- 添加 SOUL.md 抓取，读取 K8s 注解以确定角色
- `/mnt/disk01/workspaces/worksummary/hermes-agent/hermes_orchestrator/config.py` -- 为 Manager 路由和分解配置添加环境变量
- `/mnt/disk01/workspaces/worksummary/hermes-agent/hermes_orchestrator/stores/redis_task_store.py` -- 扩展更新方法以处理新字段（见下方 H4 修复）

### H4: RedisTaskStore.update() 扩展签名

Phase 3 的 `_execute_decomposition`、`_on_subtask_completed` 等代码需要更新 Phase 3 新增的字段（`subtask_ids`、`decomposition_plan`、`aggregation_strategy`、`depends_on_subtasks`、`task_type`、`result_aggregation`），但现有 `update()` 只接受 `status`、`assigned_agent`、`run_id`、`result`、`error`、`retry_count`。

**方案：扩展 `update()` 签名为通用关键字参数模式**，避免每次新增字段都改方法签名：

```python
class RedisTaskStore:
    # 现有 update() 签名（保留向后兼容）
    def update(self, task_id: str, *,
               status: str | None = None,
               assigned_agent: str | None = None,
               run_id: str | None = None,
               result: TaskResult | None = None,
               error: str | None = None,
               retry_count: int | None = None,
               # --- Phase 3 新增字段 ---
               subtask_ids: list[str] | None = None,
               decomposition_plan: dict | None = None,
               aggregation_strategy: str | None = None,
               depends_on_subtasks: list[str] | None = None,
               task_type: str | None = None,
               result_aggregation: dict | None = None,
               ) -> Task | None:
        """更新任务字段。仅更新非 None 的参数。"""
        task = self.get(task_id)
        if not task:
            return None

        if status is not None:
            task.status = status
        if assigned_agent is not None:
            task.assigned_agent = assigned_agent
        if run_id is not None:
            task.run_id = run_id
        if result is not None:
            task.result = result
        if error is not None:
            task.error = error
        if retry_count is not None:
            task.retry_count = retry_count
        # Phase 3 字段
        if subtask_ids is not None:
            task.subtask_ids = subtask_ids
        if decomposition_plan is not None:
            task.decomposition_plan = decomposition_plan
        if aggregation_strategy is not None:
            task.aggregation_strategy = aggregation_strategy
        if depends_on_subtasks is not None:
            task.depends_on_subtasks = depends_on_subtasks
        if task_type is not None:
            task.task_type = task_type
        if result_aggregation is not None:
            task.result_aggregation = result_aggregation

        self._save(task)
        return task
```

这样所有 Phase 3 代码中的 `task_store.update(parent_task_id, subtask_ids=..., decomposition_plan=..., ...)` 调用都能正常工作，同时现有调用不受影响。

**新增文件（待创建）：**
- `hermes_orchestrator/services/routing_service.py` -- 提示词构建、JSON 解析、决策验证
- `hermes_orchestrator/services/subtask_scheduler.py` -- 用于子任务依赖跟踪的 DAG 管理器
- `hermes_orchestrator/stores/pg_audit.py` -- 异步 PostgreSQL 审计写入器

**Gateway（次要修改）：**
- `/mnt/disk01/workspaces/worksummary/hermes-agent/gateway/run.py` -- 添加 `GET /v1/identity` 端点

**现有参考（未修改）：**
- `/mnt/disk01/workspaces/worksummary/hermes-agent/hermes_orchestrator/services/agent_selector.py` -- 第一阶段回退仍按原样使用
- `/mnt/disk01/workspaces/worksummary/hermes-agent/hermes_orchestrator/services/task_executor.py` -- 与 Manager 和 worker 交互时原样使用
- `/mnt/disk01/workspaces/worksummary/hermes-agent/swarm/workflow.py` -- 独立层；Agent 内部工作流，而非 Orchestrator 编排
- `/mnt/disk01/workspaces/worksummary/hermes-agent/swarm/circuit_breaker.py` -- 在两个层级之间共享