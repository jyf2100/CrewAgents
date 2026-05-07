# Hermes Orchestrator 混合存储方案 (PostgreSQL + Redis)

> **状态**: 设计评审
> **日期**: 2026-05-05
> **范围**: 在现有纯 Redis 方案基础上引入 PostgreSQL，实现冷热分层存储

---

## 目录

1. [设计目标与原则](#1-设计目标与原则)
2. [数据分类：冷热分离](#2-数据分类冷热分离)
3. [PostgreSQL 表结构 (DDL)](#3-postgresql-表结构-ddl)
4. [Redis 保留数据](#4-redis-保留数据)
5. [数据同步策略](#5-数据同步策略)
6. [查询模式](#6-查询模式)
7. [迁移策略](#7-迁移策略)
8. [架构图](#8-架构图)

---

## 1. 设计目标与原则

### 目标

| 目标 | 说明 |
|------|------|
| 持久化审计 | 任务路由历史、执行结果不可丢失，支持事后回溯 |
| 复杂查询 | 能力标签筛选、统计分析、聚合报表等关系型查询 |
| 实时性能 | 热路径（任务分发、agent 选择、健康检查）保持毫秒级延迟 |
| 最小改动 | 渐进式迁移，不破坏现有 API 契约 |

### 原则

- **Redis 是热数据缓存 + 消息通道**：存活的 agent 状态、任务队列、实时负载
- **PostgreSQL 是持久化真相源 (SSOT)**：agent 静态 profile、任务完整历史、路由审计、能力标签
- **写时同步，读时优先 PG**：关键写操作同时写入两个存储；读取历史数据从 PG，读取实时状态从 Redis

---

## 2. 数据分类：冷热分离

```
┌─────────────────────────────────────────────────────────────┐
│                      Redis (热数据)                          │
│  ┌──────────────────────┐  ┌──────────────────────────────┐ │
│  │ Agent 实时状态        │  │ 任务队列 (Stream)             │ │
│  │ - status             │  │ - XADD/XREADGROUP/XACK       │ │
│  │ - current_load       │  │ - 待消费的任务 ID             │ │
│  │ - circuit_state      │  └──────────────────────────────┘ │
│  │ - last_health_check  │  ┌──────────────────────────────┐ │
│  └──────────────────────┘  │ 活跃任务详情 (HASH)           │ │
│                            │ - 非 terminal 状态的任务       │ │
│                            │ - status/submitted..streaming  │ │
│                            └──────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                  PostgreSQL (持久化数据)                      │
│  ┌──────────────────────┐  ┌──────────────────────────────┐ │
│  │ Agent 静态 Profile    │  │ 任务完整历史                  │ │
│  │ - gateway_url        │  │ - 所有 terminal 状态任务       │ │
│  │ - models             │  │ - result/error 字段           │ │
│  │ - capabilities       │  └──────────────────────────────┘ │
│  │ - tool_ids           │  ┌──────────────────────────────┐ │
│  │ - soul_summary       │  │ 路由审计                      │ │
│  │ - registered_at      │  │ - 选择理由、候选列表          │ │
│  └──────────────────────┘  └──────────────────────────────┘ │
│  ┌──────────────────────┐  ┌──────────────────────────────┐ │
│  │ 能力标签体系          │  │ 任务拆分计划                  │ │
│  │ - 标签定义           │  │ - 父子任务关系                │ │
│  │ - agent-标签关联     │  │ - DAG 依赖                   │ │
│  └──────────────────────┘  └──────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### 数据归属总表

| 数据 | Redis | PostgreSQL | 说明 |
|------|-------|------------|------|
| Agent 实时状态 (status, load, circuit) | **主** | 仅记录 last_seen | 毫秒级读写 |
| Agent 静态 profile (url, models, capabilities) | 缓存 | **主** | 查询能力标签时从 PG 读 |
| Agent soul_summary | 无 | **主** | 大文本，不适合 Redis |
| 任务队列 (Stream) | **主** | 无 | 消费完即弃 |
| 活跃任务 (non-terminal) | **主** | **同时写** | 活跃任务需要双重保障 |
| 已完成任务 | 无 (可删) | **主** | 历史查询从 PG |
| 任务路由历史 | 无 | **主** | 审计数据 |
| 任务拆分计划 | 无 | **主** | 复杂关系查询 |
| 能力标签定义 | 无 | **主** | 标签 CRUD |
| agent-标签关联 | 缓存 | **主** | agent 选择时可缓存到 Redis |

---

## 3. PostgreSQL 表结构 (DDL)

### 3.1 概览

```
┌──────────────┐       ┌───────────────────────┐
│   agents     │──1:N──│ agent_capabilities     │
│              │       └───────────────────────┘
│              │──1:N──│ agent_tags             │
│              │       └───────────┬───────────┘
└──────┬───────┘                   │
       │                       ┌───┴───────────┐
       │                       │ capability_tags│
       │                       └───────────────┘
       │
       │1:N
┌──────┴───────┐       ┌───────────────────────┐
│    tasks     │──1:N──│ task_routes            │
│              │       └───────────────────────┘
│              │
│              │──1:N──│ task_plans             │
│              │       └───────────┬───────────┘
│              │                   │
└──────────────┘               ┌───┴───────────┐
                               │ subtasks       │
                               └───────────────┘
```

### 3.2 完整 DDL

```sql
-- ============================================================
-- Schema: hermes_orchestrator
-- 使用 admin 现有的 PostgreSQL 实例，独立的 schema 做命名隔离
-- ============================================================

CREATE SCHEMA IF NOT EXISTS orchestrator;

-- ============================================================
-- 1. agents 表 — 静态 profile（不含运行时状态）
-- ============================================================
CREATE TABLE orchestrator.agents (
    agent_id        VARCHAR(128)  PRIMARY KEY,        -- K8s pod name 或用户自定义 ID
    display_name    VARCHAR(255)  NOT NULL DEFAULT '', -- 可读名称
    gateway_url     VARCHAR(512)  NOT NULL,            -- http://<pod_ip>:8642
    api_key_ref     VARCHAR(255)  DEFAULT NULL,        -- K8s Secret 引用（不存明文）
    models          JSONB         NOT NULL DEFAULT '[]', -- 可用模型 ID 列表
    capabilities    JSONB         NOT NULL DEFAULT '{}', -- 能力字典 (来自 /v1/models)
    tool_ids        JSONB         NOT NULL DEFAULT '[]', -- 工具 ID 列表
    supported_endpoints JSONB     NOT NULL DEFAULT '[]', -- 支持的端点列表
    max_concurrent  INTEGER       NOT NULL DEFAULT 10,  -- 最大并发
    soul_summary    TEXT          DEFAULT NULL,          -- SOUL.md 摘要（由 discovery 抓取）
    config_snapshot JSONB         DEFAULT NULL,          -- 最近一次发现的配置快照
    first_seen_at   TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    last_seen_at    TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    is_active       BOOLEAN       NOT NULL DEFAULT TRUE, -- 软删除标记

    -- 元信息
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_agents_last_seen ON orchestrator.agents (last_seen_at);
CREATE INDEX idx_agents_active    ON orchestrator.agents (is_active) WHERE is_active = TRUE;

COMMENT ON TABLE orchestrator.agents IS 'Agent 静态 profile，由 Discovery loop 发现并持久化';
COMMENT ON COLUMN orchestrator.agents.api_key_ref IS 'K8s Secret 引用，格式: secret_name/key，不存储明文密钥';
COMMENT ON COLUMN orchestrator.agents.soul_summary IS 'SOUL.md 的前 2000 字符摘要，便于路由时做文本匹配';

-- ============================================================
-- 2. capability_tags 表 — 能力标签定义
-- ============================================================
CREATE TABLE orchestrator.capability_tags (
    tag_id          SERIAL        PRIMARY KEY,
    tag_key         VARCHAR(100)  NOT NULL UNIQUE,     -- 标签键，如 "code-review"
    display_name    VARCHAR(255)  NOT NULL,             -- 显示名称
    description     TEXT          DEFAULT '',
    category        VARCHAR(50)   DEFAULT 'general',    -- 分类: general | tool | domain | model
    metadata        JSONB         DEFAULT '{}',          -- 扩展字段
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_cap_tags_key ON orchestrator.capability_tags (tag_key);
CREATE INDEX idx_cap_tags_category ON orchestrator.capability_tags (category);

COMMENT ON TABLE orchestrator.capability_tags IS '能力标签字典，支持 agent 按能力筛选';

-- ============================================================
-- 3. agent_tags 表 — agent 与能力标签的关联
-- ============================================================
CREATE TABLE orchestrator.agent_tags (
    agent_id        VARCHAR(128)  NOT NULL REFERENCES orchestrator.agents(agent_id) ON DELETE CASCADE,
    tag_id          INTEGER       NOT NULL REFERENCES orchestrator.capability_tags(tag_id) ON DELETE CASCADE,
    confidence      REAL          DEFAULT 1.0,           -- 匹配置信度 0.0-1.0
    source          VARCHAR(20)   NOT NULL DEFAULT 'auto', -- auto=discovery推断 | manual=人工标注
    updated_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),

    PRIMARY KEY (agent_id, tag_id)
);

CREATE INDEX idx_agent_tags_tag ON orchestrator.agent_tags (tag_id);

COMMENT ON TABLE orchestrator.agent_tags IS 'Agent 与能力标签的关联，支持自动推断和人工标注两种来源';

-- ============================================================
-- 4. agent_capabilities 表 — 按模型的细粒度能力记录
-- ============================================================
CREATE TABLE orchestrator.agent_capabilities (
    id              SERIAL        PRIMARY KEY,
    agent_id        VARCHAR(128)  NOT NULL REFERENCES orchestrator.agents(agent_id) ON DELETE CASCADE,
    model_id        VARCHAR(255)  NOT NULL,              -- 模型 ID
    capabilities    JSONB         NOT NULL DEFAULT '{}', -- 能力字典
    tool_ids        JSONB         NOT NULL DEFAULT '[]', -- 工具列表
    supported_endpoints JSONB     NOT NULL DEFAULT '[]',
    discovered_at   TIMESTAMPTZ   NOT NULL DEFAULT NOW(),

    UNIQUE (agent_id, model_id)
);

CREATE INDEX idx_agent_caps_agent ON orchestrator.agent_capabilities (agent_id);

COMMENT ON TABLE orchestrator.agent_capabilities IS '每次 discovery 抓取的 /v1/models 详细能力快照';

-- ============================================================
-- 5. tasks 表 — 任务完整生命周期
-- ============================================================
CREATE TABLE orchestrator.tasks (
    task_id         UUID          PRIMARY KEY,
    prompt          TEXT          NOT NULL,
    instructions    TEXT          NOT NULL DEFAULT '',
    model_id        VARCHAR(255)  NOT NULL DEFAULT 'hermes-agent',
    status          VARCHAR(20)   NOT NULL DEFAULT 'submitted',
        -- submitted | queued | assigned | executing | streaming | done | failed | cancelled

    -- 路由信息（冗余存储，便于直接查询）
    assigned_agent  VARCHAR(128)  DEFAULT NULL REFERENCES orchestrator.agents(agent_id),
    run_id          VARCHAR(255)  DEFAULT NULL,

    -- 结果
    result_content  TEXT          DEFAULT NULL,
    result_usage    JSONB         DEFAULT NULL,
    duration_seconds REAL         DEFAULT NULL,

    -- 错误信息
    error           TEXT          DEFAULT NULL,

    -- 重试控制
    retry_count     SMALLINT      NOT NULL DEFAULT 0,
    max_retries     SMALLINT      NOT NULL DEFAULT 2,

    -- 优先级与超时
    priority        SMALLINT      NOT NULL DEFAULT 1,
    timeout_seconds REAL          NOT NULL DEFAULT 600.0,

    -- 回调
    callback_url    VARCHAR(1024) DEFAULT NULL,

    -- 扩展元数据
    metadata        JSONB         NOT NULL DEFAULT '{}',

    -- 关联（可选，指向 workflow 或 parent task）
    parent_task_id  UUID          DEFAULT NULL REFERENCES orchestrator.tasks(task_id) ON DELETE SET NULL,
    workflow_id     VARCHAR(255)  DEFAULT NULL,

    -- 时间戳
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ   DEFAULT NULL
);

-- 高频查询索引
CREATE INDEX idx_tasks_status     ON orchestrator.tasks (status);
CREATE INDEX idx_tasks_agent      ON orchestrator.tasks (assigned_agent);
CREATE INDEX idx_tasks_created    ON orchestrator.tasks (created_at DESC);
CREATE INDEX idx_tasks_parent     ON orchestrator.tasks (parent_task_id) WHERE parent_task_id IS NOT NULL;
CREATE INDEX idx_tasks_workflow   ON orchestrator.tasks (workflow_id) WHERE workflow_id IS NOT NULL;

COMMENT ON TABLE orchestrator.tasks IS '任务完整生命周期记录，terminal 状态的任务长期保留';

-- ============================================================
-- 6. task_routes 表 — 路由历史 + 审计
-- ============================================================
CREATE TABLE orchestrator.task_routes (
    id              BIGSERIAL      PRIMARY KEY,
    task_id         UUID           NOT NULL REFERENCES orchestrator.tasks(task_id) ON DELETE CASCADE,
    agent_id        VARCHAR(128)   NOT NULL REFERENCES orchestrator.agents(agent_id),

    -- 路由决策
    route_order     SMALLINT       NOT NULL DEFAULT 1,   -- 第几次路由（重试=2,3...）
    route_reason    VARCHAR(50)    NOT NULL,
        -- initial_assignment | retry | failover | manual_override
    selection_score REAL           DEFAULT NULL,          -- 选择评分（如负载分数）
    is_selected     BOOLEAN        NOT NULL DEFAULT TRUE, -- 是否最终被选中

    -- 路由时的上下文快照
    agent_status_at_route  VARCHAR(20)  DEFAULT NULL,     -- 路由时 agent 状态
    agent_load_at_route    SMALLINT     DEFAULT NULL,     -- 路由时 agent 负载
    candidates_count       SMALLINT     DEFAULT NULL,     -- 候选 agent 数量
    candidates_snapshot    JSONB        DEFAULT NULL,     -- 候选列表 [{agent_id, load, score}]

    -- 结果
    outcome         VARCHAR(20)   DEFAULT NULL,
        -- completed | failed | timeout | cancelled
    error_message   TEXT          DEFAULT NULL,

    -- 时间戳
    routed_at       TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    resolved_at     TIMESTAMPTZ   DEFAULT NULL
);

CREATE INDEX idx_task_routes_task  ON orchestrator.task_routes (task_id);
CREATE INDEX idx_task_routes_agent ON orchestrator.task_routes (agent_id);
CREATE INDEX idx_task_routes_time  ON orchestrator.task_routes (routed_at DESC);

COMMENT ON TABLE orchestrator.task_routes IS '任务路由历史审计，记录每次路由决策的上下文和结果';

-- ============================================================
-- 7. task_plans 表 — 任务拆分计划
-- ============================================================
CREATE TABLE orchestrator.task_plans (
    plan_id         UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    parent_task_id  UUID          NOT NULL REFERENCES orchestrator.tasks(task_id) ON DELETE CASCADE,
    plan_type       VARCHAR(20)   NOT NULL,
        -- sequential | parallel | dag
    description     TEXT          DEFAULT NULL,
    status          VARCHAR(20)   NOT NULL DEFAULT 'pending',
        -- pending | running | completed | failed | partially_completed
    total_subtasks  SMALLINT      NOT NULL DEFAULT 0,
    completed_subtasks SMALLINT   NOT NULL DEFAULT 0,
    failed_subtasks SMALLINT      NOT NULL DEFAULT 0,

    -- DAG 依赖关系（整体描述）
    dependency_graph JSONB        DEFAULT NULL,
        -- 格式: {"subtask_id": ["depends_on_subtask_id", ...], ...}

    created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_task_plans_parent ON orchestrator.task_plans (parent_task_id);
CREATE INDEX idx_task_plans_status ON orchestrator.task_plans (status);

COMMENT ON TABLE orchestrator.task_plans IS '任务拆分计划，描述父任务如何分解为子任务';

-- ============================================================
-- 8. subtasks 表 — 子任务实例
-- ============================================================
CREATE TABLE orchestrator.subtasks (
    subtask_id      UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_id         UUID          NOT NULL REFERENCES orchestrator.task_plans(plan_id) ON DELETE CASCADE,
    task_id         UUID          NOT NULL REFERENCES orchestrator.tasks(task_id) ON DELETE CASCADE,
    step_label      VARCHAR(100)  NOT NULL,               -- 步骤标签，如 "research"、"summarize"
    step_order      SMALLINT      NOT NULL DEFAULT 0,     -- 执行顺序
    prompt_template TEXT          NOT NULL,                -- prompt 模板（支持变量插值）
    instructions    TEXT          DEFAULT '',
    model_id        VARCHAR(255)  DEFAULT 'hermes-agent',

    -- 依赖
    depends_on      JSONB         NOT NULL DEFAULT '[]',
        -- 依赖的 subtask_id 列表

    status          VARCHAR(20)   NOT NULL DEFAULT 'pending',
        -- pending | ready | running | completed | failed | skipped
    assigned_agent  VARCHAR(128)  DEFAULT NULL,
    result_content  TEXT          DEFAULT NULL,
    error           TEXT          DEFAULT NULL,

    created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    started_at      TIMESTAMPTZ   DEFAULT NULL,
    completed_at    TIMESTAMPTZ   DEFAULT NULL
);

CREATE INDEX idx_subtasks_plan   ON orchestrator.subtasks (plan_id);
CREATE INDEX idx_subtasks_task   ON orchestrator.subtasks (task_id);
CREATE INDEX idx_subtasks_status ON orchestrator.subtasks (status);

COMMENT ON TABLE orchestrator.subtasks IS '拆分计划中的子任务实例';

-- ============================================================
-- 触发器：自动维护 updated_at
-- ============================================================
CREATE OR REPLACE FUNCTION orchestrator.update_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_agents_updated
    BEFORE UPDATE ON orchestrator.agents
    FOR EACH ROW EXECUTE FUNCTION orchestrator.update_timestamp();

CREATE TRIGGER trg_tasks_updated
    BEFORE UPDATE ON orchestrator.tasks
    FOR EACH ROW EXECUTE FUNCTION orchestrator.update_timestamp();

CREATE TRIGGER trg_task_plans_updated
    BEFORE UPDATE ON orchestrator.task_plans
    FOR EACH ROW EXECUTE FUNCTION orchestrator.update_timestamp();

-- ============================================================
-- 触发器：terminal 状态时记录 completed_at
-- ============================================================
CREATE OR REPLACE FUNCTION orchestrator.set_completed_at()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.status IN ('done', 'failed', 'cancelled') AND OLD.status NOT IN ('done', 'failed', 'cancelled') THEN
        NEW.completed_at = NOW();
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_tasks_completed
    BEFORE UPDATE ON orchestrator.tasks
    FOR EACH ROW EXECUTE FUNCTION orchestrator.set_completed_at();

-- ============================================================
-- 视图：agent 统计摘要
-- ============================================================
CREATE OR REPLACE VIEW orchestrator.v_agent_stats AS
SELECT
    a.agent_id,
    a.display_name,
    a.is_active,
    COUNT(t.task_id) AS total_tasks,
    COUNT(t.task_id) FILTER (WHERE t.status = 'done') AS completed_tasks,
    COUNT(t.task_id) FILTER (WHERE t.status = 'failed') AS failed_tasks,
    ROUND(
        COUNT(t.task_id) FILTER (WHERE t.status = 'done')::REAL
        / NULLIF(COUNT(t.task_id), 0) * 100,
        1
    ) AS success_rate_pct,
    ROUND(AVG(t.duration_seconds) FILTER (WHERE t.status = 'done'), 2) AS avg_duration_seconds,
    MAX(t.created_at) AS last_task_at
FROM orchestrator.agents a
LEFT JOIN orchestrator.tasks t ON t.assigned_agent = a.agent_id
GROUP BY a.agent_id, a.display_name, a.is_active;

COMMENT ON VIEW orchestrator.v_agent_stats IS 'Agent 任务统计摘要视图';
```

---

## 4. Redis 保留数据

### 4.1 保留的 Key 清单

| Redis Key | 类型 | 用途 | TTL |
|-----------|------|------|-----|
| `hermes:orchestrator:agents` | HASH | Agent 实时状态 (status, load, circuit_state, last_health_check) | 无 |
| `hermes:orchestrator:tasks:stream` | STREAM | 任务队列（消费完即弃） | MAXLEN 10000 |
| `hermes:orchestrator:tasks:{task_id}` | HASH | 活跃任务详情（仅 non-terminal 状态） | 无（完成后删除） |

### 4.2 不再保留的数据

| 数据 | 原因 |
|------|------|
| 已完成任务详情 | 迁移到 PG 后从 Redis 删除，节省内存 |
| Agent 静态 profile (models, capabilities, tool_ids) | PG 为主，Redis 仅缓存实时状态字段 |
| 任务路由历史 | 完全由 PG 管理 |
| 任务拆分计划 | 完全由 PG 管理 |

### 4.3 Redis Agent Hash 结构调整

调整后 Redis 只存实时热数据（不再存静态 profile）：

```
hermes:orchestrator:agents (HASH)
  {agent_id} -> {
    "agent_id":        "hermes-gateway-1-abc123",
    "gateway_url":     "http://10.244.1.42:8642",  -- 保留（热路径需要）
    "status":          "online",                    -- 保留（选择器需要）
    "current_load":    3,                           -- 保留（选择器需要）
    "max_concurrent":  10,                          -- 保留（选择器需要）
    "circuit_state":   "closed",                    -- 保留（选择器需要）
    "last_health_check": 1746316795.0,              -- 保留（自适应轮询需要）
    "api_key":         "..."                        -- 保留（提交任务需要）
  }
```

移除的字段（从 PG 读取）：
- `models` -- 不再缓存到 Redis，选择器暂不按模型筛选
- `capabilities` -- 复杂查询走 PG
- `tool_ids` -- 同上
- `registered_at` -- PG 持久化

### 4.4 为什么要这样分

| 维度 | Redis | PostgreSQL |
|------|-------|------------|
| 访问延迟 | < 1ms | 5-10ms |
| 适合场景 | 实时负载、状态机、消息队列 | 审计、统计、复杂查询 |
| 数据量 | KB 级热数据 | GB 级历史数据 |
| 持久化 | AOF 但不保证零丢失 | ACID 事务保证 |
| 查询能力 | 仅 key-value / scan | SQL 全功能 |
| 关联查询 | 不支持 | JOIN / 子查询 |

---

## 5. 数据同步策略

### 5.1 同步架构总览

```
                 ┌─────────────────────────────────┐
                 │       Orchestrator Services       │
                 │                                   │
Discovery Loop ──┤── register_agent() ──────────────┤──► PG upsert agents
                 │                                   │    PG upsert agent_capabilities
                 │                                   │    Redis HSET agent status
                 │                                   │
Health Monitor ──┤── update_agent_health() ─────────┤──► Redis HSET status/circuit
                 │                                   │    PG UPDATE last_seen_at
                 │                                   │
Task Worker ─────┤── process_task() ────────────────┤──► Redis task queue (Stream)
                 │                                   │    PG INSERT tasks
                 │                                   │    PG INSERT task_routes (审计)
                 │                                   │
                 └─────────────────────────────────┘
```

### 5.2 Agent 同步：Discovery Loop

Discovery loop 发现 agent 后，同步流程如下：

```python
async def register_agent(self, profile: AgentProfile):
    """双写：PG (静态 profile) + Redis (实时状态)"""
    # 1. 写入 PG — 静态 profile
    async with pg_session() as session:
        stmt = pg_insert(Agent).values(
            agent_id=profile.agent_id,
            display_name=profile.agent_id,  # 初始用 ID，后续可改
            gateway_url=profile.gateway_url,
            models=profile.models,
            capabilities=profile.capabilities,
            tool_ids=profile.tool_ids,
            last_seen_at=func.now(),
            is_active=True,
        ).on_conflict_do_update(
            index_elements=['agent_id'],
            set_={
                'gateway_url': profile.gateway_url,
                'models': profile.models,
                'capabilities': profile.capabilities,
                'tool_ids': profile.tool_ids,
                'last_seen_at': func.now(),
                'is_active': True,
            }
        )
        await session.execute(stmt)
        await session.commit()

    # 2. 写入 PG — 按模型的细粒度能力
    if profile.capabilities:
        async with pg_session() as session:
            for model_id, caps in profile.capabilities.items():
                stmt = pg_insert(AgentCapability).values(
                    agent_id=profile.agent_id,
                    model_id=model_id,
                    capabilities=caps.get('capabilities', {}),
                    tool_ids=caps.get('tool_ids', []),
                ).on_conflict_do_update(
                    constraint='agent_capabilities_agent_id_model_id_key',
                    set_={
                        'capabilities': caps.get('capabilities', {}),
                        'tool_ids': caps.get('tool_ids', []),
                        'discovered_at': func.now(),
                    }
                )
                await session.execute(stmt)
            await session.commit()

    # 3. 推断能力标签（自动打标）
    await self._infer_capability_tags(profile)

    # 4. 写入 Redis — 实时状态
    self.redis_registry.register(profile)
```

### 5.3 Agent 同步：Health Monitor

Health monitor 检测 agent 状态变化后：

```python
async def _update_agent_health(self, agent_id: str, healthy: bool):
    """热数据 → Redis，冷数据 → PG"""
    # 1. Redis: 实时状态（毫秒级）
    if healthy:
        self.redis_registry.update_status(agent_id, "online")
    else:
        circuit = self.circuits[agent_id]
        if circuit.state == CircuitState.OPEN:
            self.redis_registry.update_status(agent_id, "degraded")

    # 2. PG: last_seen_at（批量更新，不阻塞热路径）
    # 使用异步写入，不影响健康检查的实时性
    await self.pg_session.execute(
        update(Agent)
        .where(Agent.agent_id == agent_id)
        .values(last_seen_at=func.now())
    )
```

### 5.4 Task 同步：任务生命周期

```python
async def _process_task(self, task_id: str):
    # === 阶段1: 任务创建 ===
    # API 层 submit_task() 时双写
    task = Task(...)
    self.redis_task_store.create(task)       # Redis: 活跃任务
    self.redis_task_store.enqueue(task)       # Redis: 入队列
    await self.pg_task_repo.create(task)      # PG: 持久化

    # === 阶段2: 路由选择 ===
    chosen = self.selector.select(agents, task)
    # 记录路由审计
    await self.pg_route_repo.create(TaskRoute(
        task_id=task.task_id,
        agent_id=chosen.agent_id,
        route_reason="initial_assignment",
        agent_load_at_route=chosen.current_load,
        candidates_count=len(candidates),
        candidates_snapshot=[...],
    ))
    # 更新 Redis 状态
    self.redis_task_store.update(task_id, status="assigned", assigned_agent=chosen.agent_id)
    # 更新 PG 状态
    await self.pg_task_repo.update(task_id, status="assigned", assigned_agent=chosen.agent_id)

    # === 阶段3: 执行完成 ===
    # 更新 PG 完整结果
    await self.pg_task_repo.update(task_id,
        status="done",
        result_content=result.content,
        result_usage=result.usage,
        duration_seconds=result.duration_seconds,
    )
    # 更新 Redis 状态
    self.redis_task_store.update(task_id, status="done", result=result)

    # === 阶段4: 清理 Redis ===
    # 任务进入 terminal 状态后，延迟删除 Redis 数据（保留短时间供查询）
    # 由后台 GC 任务清理，或立即删除以节省内存
    self.redis_task_store.delete(task_id)
```

### 5.5 不一致处理策略

| 场景 | 检测方法 | 处理策略 |
|------|---------|---------|
| Redis 有 agent 但 PG 没有 | Discovery loop 查 PG | 自动补录到 PG（以 Redis 为准） |
| PG 有 agent 但 Redis 没有 | Discovery loop 查 Redis | 正常（agent 可能已下线，Redis 是实时的） |
| 任务状态不一致 | 定期对账任务（每小时） | 以 PG 为真相源，修正 Redis |
| PG 写入失败但 Redis 成功 | 写入异常捕获 | 记录到补偿队列，异步重试 PG 写入 |
| Redis 宕机 | health check 失败 | 降级模式：任务路由仅用 PG（牺牲实时性） |

#### 对账任务伪代码

```python
async def reconciliation_job():
    """每小时运行，检查 PG 和 Redis 的数据一致性"""
    # 1. 检查活跃任务
    pg_active_tasks = await pg_repo.list_by_status(["assigned", "executing", "streaming"])
    for task in pg_active_tasks:
        redis_task = redis_store.get(task.task_id)
        if not redis_task:
            # Redis 已丢失（可能宕机恢复后），以 PG 为准补回 Redis
            redis_store.create(task)
            logger.warning("Reconciliation: restored task %s to Redis", task.task_id)
        elif redis_task.status != task.status:
            # 状态不一致，以 PG 为准
            redis_store.update(task.task_id, status=task.status)
            logger.warning("Reconciliation: fixed status for task %s (Redis=%s, PG=%s)",
                          task.task_id, redis_task.status, task.status)

    # 2. 清理 Redis 中的已完成任务（Redis 可能未及时删除）
    redis_all = redis_store.list_by_status(["done", "failed"])
    for task in redis_all:
        redis_store.delete(task.task_id)
        logger.info("Reconciliation: cleaned completed task %s from Redis", task.task_id)
```

---

## 6. 查询模式

### 6.1 按能力标签查找在线 Agent

```sql
-- 找到所有有 "code-review" 能力的 agent
-- 实时状态从 Redis 读，这里只返回 agent_id 列表
SELECT a.agent_id, a.display_name, a.gateway_url
FROM orchestrator.agents a
INNER JOIN orchestrator.agent_tags at ON a.agent_id = at.agent_id
INNER JOIN orchestrator.capability_tags ct ON at.tag_id = ct.tag_id
WHERE ct.tag_key = 'code-review'
  AND a.is_active = TRUE
  AND a.last_seen_at > NOW() - INTERVAL '5 minutes';
```

### 6.2 带标签自动推断的增强版

```sql
-- 找到有 code-review 相关工具的 agent（通过 tool_ids 推断）
-- 不依赖手动标签，直接查 agent_capabilities
SELECT DISTINCT a.agent_id, a.display_name, a.gateway_url
FROM orchestrator.agents a
INNER JOIN orchestrator.agent_capabilities ac ON a.agent_id = ac.agent_id
WHERE a.is_active = TRUE
  AND a.last_seen_at > NOW() - INTERVAL '5 minutes'
  AND (
    ac.tool_ids @> '["code-review"]'::jsonb
    OR ac.capabilities::text LIKE '%code-review%'
  );
```

### 6.3 查询某任务的路由历史

```sql
SELECT
    tr.route_order,
    tr.agent_id,
    a.display_name AS agent_name,
    tr.route_reason,
    tr.agent_status_at_route,
    tr.agent_load_at_route,
    tr.candidates_count,
    tr.outcome,
    tr.error_message,
    tr.routed_at,
    tr.resolved_at
FROM orchestrator.task_routes tr
LEFT JOIN orchestrator.agents a ON tr.agent_id = a.agent_id
WHERE tr.task_id = :task_id
ORDER BY tr.route_order;
```

### 6.4 统计各 Agent 任务成功率

```sql
-- 使用预定义视图
SELECT * FROM orchestrator.v_agent_stats
ORDER BY total_tasks DESC;

-- 或直接查询
SELECT
    a.agent_id,
    a.display_name,
    COUNT(*) AS total_tasks,
    COUNT(*) FILTER (WHERE t.status = 'done') AS success_count,
    COUNT(*) FILTER (WHERE t.status = 'failed') AS fail_count,
    ROUND(
        COUNT(*) FILTER (WHERE t.status = 'done')::REAL
        / NULLIF(COUNT(*), 0) * 100, 1
    ) AS success_rate_pct
FROM orchestrator.agents a
LEFT JOIN orchestrator.tasks t ON t.assigned_agent = a.agent_id
WHERE t.created_at > NOW() - INTERVAL '7 days'
GROUP BY a.agent_id, a.display_name
ORDER BY total_tasks DESC;
```

### 6.5 查询某 Agent 平均执行时间

```sql
SELECT
    assigned_agent,
    COUNT(*) AS task_count,
    ROUND(AVG(duration_seconds), 2) AS avg_duration_sec,
    ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY duration_seconds), 2) AS p50_sec,
    ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_seconds), 2) AS p95_sec,
    ROUND(MAX(duration_seconds), 2) AS max_duration_sec
FROM orchestrator.tasks
WHERE status = 'done'
  AND assigned_agent = :agent_id
  AND completed_at > NOW() - INTERVAL '7 days'
GROUP BY assigned_agent;
```

### 6.6 查询任务拆分计划及子任务状态

```sql
SELECT
    tp.plan_id,
    tp.plan_type,
    tp.status AS plan_status,
    tp.total_subtasks,
    tp.completed_subtasks,
    tp.failed_subtasks,
    json_agg(
        json_build_object(
            'subtask_id', st.subtask_id,
            'step_label', st.step_label,
            'status', st.status,
            'depends_on', st.depends_on,
            'assigned_agent', st.assigned_agent
        ) ORDER BY st.step_order
    ) AS subtasks
FROM orchestrator.task_plans tp
LEFT JOIN orchestrator.subtasks st ON tp.plan_id = st.plan_id
WHERE tp.parent_task_id = :task_id
GROUP BY tp.plan_id;
```

### 6.7 Token 使用量统计

```sql
SELECT
    date_trunc('day', created_at) AS day,
    COUNT(*) AS task_count,
    SUM((result_usage->>'input_tokens')::int) AS total_input_tokens,
    SUM((result_usage->>'output_tokens')::int) AS total_output_tokens,
    SUM((result_usage->>'total_tokens')::int) AS total_tokens,
    SUM(duration_seconds) AS total_duration_sec
FROM orchestrator.tasks
WHERE status = 'done'
  AND result_usage IS NOT NULL
  AND created_at > NOW() - INTERVAL '30 days'
GROUP BY date_trunc('day', created_at)
ORDER BY day DESC;
```

### 6.8 最近失败任务及路由链分析

```sql
-- 找出最近失败的电务及其路由链，用于诊断
SELECT
    t.task_id,
    t.prompt AS prompt_preview,
    t.error,
    t.created_at,
    t.updated_at,
    (
        SELECT json_agg(
            json_build_object(
                'route_order', tr.route_order,
                'agent_id', tr.agent_id,
                'route_reason', tr.route_reason,
                'outcome', tr.outcome
            ) ORDER BY tr.route_order
        )
        FROM orchestrator.task_routes tr
        WHERE tr.task_id = t.task_id
    ) AS route_chain
FROM orchestrator.tasks t
WHERE t.status = 'failed'
  AND t.created_at > NOW() - INTERVAL '1 hour'
ORDER BY t.created_at DESC
LIMIT 20;
```

---

## 7. 迁移策略

### 7.1 迁移阶段

```
Phase 0 (当前)          Phase 1 (双写)          Phase 2 (PG主读)         Phase 3 (Redis清理)
┌──────────────┐     ┌──────────────┐       ┌──────────────┐       ┌──────────────┐
│ Redis only   │ ──► │ Redis + PG   │ ──►   │ PG 主 + Redis│ ──►   │ Redis 仅热  │
│              │     │ 双写         │       │ 查询从 PG    │       │ 数据 + 队列 │
│ 全部数据在   │     │ PG 暂不读    │       │              │       │              │
│ Redis 中     │     │              │       │ 历史=PG      │       │ 历史=PG      │
│              │     │              │       │ 实时=Redis    │       │ 实时=Redis    │
└──────────────┘     └──────────────┘       └──────────────┘       └──────────────┘
  无改动              1-2 天                  3-5 天                  持续运行
```

### 7.2 Phase 1: 双写（零风险）

**目标**：让 PG 和 Redis 同时拥有完整数据，但不改变任何读取逻辑。

**改动清单**：

1. **创建 PG schema 和表**：执行上述 DDL
2. **添加 PG 连接层**：在 `hermes_orchestrator/` 下新增 `stores/pg_store.py`
3. **修改 Discovery Loop**：`register_agent()` 同时写 PG
4. **修改 Task Worker**：`_process_task()` 同时写 PG
5. **不修改任何读取逻辑**

```python
# stores/pg_store.py (新增)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

class PGAgentStore:
    """PostgreSQL-backed agent store for persistent data."""

    async def upsert(self, profile: AgentProfile) -> None:
        """INSERT ... ON CONFLICT DO UPDATE"""

    async def update_last_seen(self, agent_id: str) -> None:
        """UPDATE last_seen_at = NOW() WHERE agent_id = :id"""

class PGTaskStore:
    """PostgreSQL-backed task store for persistent history."""

    async def create(self, task: Task) -> None:
        """INSERT INTO orchestrator.tasks"""

    async def update(self, task_id: str, **fields) -> None:
        """UPDATE orchestrator.tasks SET ... WHERE task_id = :id"""

class PGRouteStore:
    """PostgreSQL-backed route audit store."""

    async def create(self, route: TaskRoute) -> None:
        """INSERT INTO orchestrator.task_routes"""
```

**验证**：PG 中数据持续增长，无报错。

### 7.3 Phase 2: PG 主读

**目标**：历史查询、统计、审计从 PG 读取；实时路径保持 Redis。

**改动清单**：

1. **修改 API 端点**：
   - `GET /api/v1/tasks` (列表) -- 从 PG 分页查询
   - `GET /api/v1/tasks/{task_id}` (详情) -- terminal 状态从 PG，活跃状态从 Redis
   - `GET /api/v1/agents` (列表) -- 合并 Redis 实时状态 + PG 静态 profile
2. **添加统计 API**：
   - `GET /api/v1/stats/agents` -- agent 统计
   - `GET /api/v1/stats/tasks` -- 任务统计
   - `GET /api/v1/tasks/{task_id}/routes` -- 路由历史
3. **Admin 前端对接**：展示统计仪表盘

**验证**：API 返回结果正确，PG 和 Redis 数据一致。

### 7.4 Phase 3: Redis 清理

**目标**：从 Redis 清除不再需要的数据，优化内存使用。

**改动清单**：

1. **活跃任务完成后删除 Redis 数据**：在 `_process_task()` 的 finally 块中
2. **调整 Redis agent hash 结构**：只保留实时状态字段
3. **启动对账任务**：每小时检查一致性

### 7.5 数据迁移脚本

```python
#!/usr/bin/env python3
"""
migrate_redis_to_pg.py — 从 Redis 迁移现有数据到 PostgreSQL

使用方法:
    REDIS_URL=redis://:password@hermes-redis:6379/0 \
    DATABASE_URL=postgresql+asyncpg://hermes:password@postgres:5432/hermes_admin \
    python migrate_redis_to_pg.py
"""
import asyncio
import json
import os
import sys

import redis as _redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker


AGENTS_KEY = "hermes:orchestrator:agents"
TASK_PREFIX = "hermes:orchestrator:tasks:"


async def migrate(redis_client, pg_engine):
    session_factory = async_sessionmaker(pg_engine, class_=AsyncSession)

    # 1. 迁移 agents
    all_agents = redis_client.hgetall(AGENTS_KEY)
    agent_count = 0
    async with session_factory() as session:
        for agent_id, raw in all_agents.items():
            if isinstance(agent_id, bytes):
                agent_id = agent_id.decode()
            if isinstance(raw, bytes):
                raw = raw.decode()
            data = json.loads(raw)

            await session.execute(text("""
                INSERT INTO orchestrator.agents (agent_id, display_name, gateway_url,
                    models, capabilities, tool_ids, max_concurrent,
                    first_seen_at, last_seen_at, is_active)
                VALUES (:aid, :name, :url, :models::jsonb, :caps::jsonb,
                    :tools::jsonb, :max_conc,
                to_timestamp(:reg_at), NOW(), true)
                ON CONFLICT (agent_id) DO UPDATE SET
                    gateway_url = EXCLUDED.gateway_url,
                    models = EXCLUDED.models,
                    capabilities = EXCLUDED.capabilities,
                    tool_ids = EXCLUDED.tool_ids,
                    last_seen_at = NOW()
            """), {
                'aid': agent_id,
                'name': agent_id,
                'url': data.get('gateway_url', ''),
                'models': json.dumps(data.get('models', [])),
                'caps': json.dumps(data.get('capabilities', {})),
                'tools': json.dumps(data.get('tool_ids', [])),
                'max_conc': data.get('max_concurrent', 10),
                'reg_at': data.get('registered_at', 0),
            })
            agent_count += 1
        await session.commit()
    print(f"Migrated {agent_count} agents")

    # 2. 迁移 tasks
    cursor = 0
    task_count = 0
    async with session_factory() as session:
        while True:
            cursor, keys = redis_client.scan(cursor, match=f"{TASK_PREFIX}*", count=100)
            for key in keys:
                if isinstance(key, bytes):
                    key = key.decode()
                if key.endswith(":stream"):
                    continue
                raw = redis_client.hget(key, "data")
                if not raw:
                    continue
                if isinstance(raw, bytes):
                    raw = raw.decode()
                data = json.loads(raw)
                task_id = data.get('task_id', '')
                if not task_id:
                    continue

                await session.execute(text("""
                    INSERT INTO orchestrator.tasks (
                        task_id, prompt, instructions, model_id, status,
                        assigned_agent, run_id, error,
                        retry_count, max_retries, priority, timeout_seconds,
                        callback_url, metadata,
                        created_at, updated_at
                    ) VALUES (
                        :tid::uuid, :prompt, :instr, :model, :status,
                        :agent, :run_id, :error,
                        :retries, :max_retries, :priority, :timeout,
                        :callback, :meta::jsonb,
                        to_timestamp(:created), to_timestamp(:updated)
                    )
                    ON CONFLICT (task_id) DO NOTHING
                """), {
                    'tid': task_id,
                    'prompt': data.get('prompt', ''),
                    'instr': data.get('instructions', ''),
                    'model': data.get('model_id', 'hermes-agent'),
                    'status': data.get('status', 'queued'),
                    'agent': data.get('assigned_agent'),
                    'run_id': data.get('run_id'),
                    'error': data.get('error'),
                    'retries': data.get('retry_count', 0),
                    'max_retries': data.get('max_retries', 2),
                    'priority': data.get('priority', 1),
                    'timeout': data.get('timeout_seconds', 600.0),
                    'callback': data.get('callback_url'),
                    'meta': json.dumps(data.get('metadata', {})),
                    'created': data.get('created_at', 0),
                    'updated': data.get('updated_at', 0),
                })

                # 迁移 result 字段
                result = data.get('result')
                if result and isinstance(result, dict):
                    await session.execute(text("""
                        UPDATE orchestrator.tasks SET
                            result_content = :content,
                            result_usage = :usage::jsonb,
                            duration_seconds = :duration
                        WHERE task_id = :tid::uuid
                    """), {
                        'tid': task_id,
                        'content': result.get('content', ''),
                        'usage': json.dumps(result.get('usage', {})),
                        'duration': result.get('duration_seconds'),
                    })

                task_count += 1
            if cursor == 0:
                break
        await session.commit()
    print(f"Migrated {task_count} tasks")

    await pg_engine.dispose()


def main():
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    db_url = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://hermes:hermes_pg_2024@postgres:5432/hermes_admin",
    )

    redis_client = _redis.Redis.from_url(redis_url, decode_responses=True)
    pg_engine = create_async_engine(db_url, echo=False)

    asyncio.run(migrate(redis_client, pg_engine))
    redis_client.close()
    print("Migration complete")


if __name__ == "__main__":
    main()
```

### 7.6 回滚方案

| 阶段 | 回滚方式 |
|------|---------|
| Phase 1 (双写) | 删除 PG 写入代码，重新部署。PG 数据保留但不再更新 |
| Phase 2 (PG主读) | 将 API 读取切回 Redis。PG 继续写但不再读 |
| Phase 3 (Redis清理) | 停止 Redis 清理逻辑，重新从 PG 回填 Redis |

**紧急回滚**：所有 PG 相关代码用 feature flag 控制：

```python
# config.py
PG_ENABLED = os.environ.get("ORCHESTRATOR_PG_ENABLED", "true").lower() == "true"

# 使用处
if config.PG_ENABLED:
    await pg_store.create(task)
```

设置 `ORCHESTRATOR_PG_ENABLED=false` 即可完全禁用 PG，回到纯 Redis 模式。

---

## 8. 架构图

### 8.1 整体数据流

```
                              ┌─────────────────┐
                              │   External API   │
                              │  Client / Admin  │
                              └────────┬────────┘
                                       │
                              ┌────────▼────────┐
                              │  Orchestrator    │
                              │  FastAPI App     │
                              │                  │
                    ┌─────────┤  Routes          ├─────────┐
                    │         │                  │         │
                    │         └──────────────────┘         │
                    │                                      │
          ┌─────────▼──────────┐              ┌───────────▼──────────┐
          │   Read Path         │              │   Write Path          │
          │                     │              │                       │
          │  实时状态 → Redis    │              │  双写 (Redis + PG)    │
          │  历史查询 → PG       │              │                       │
          │  统计分析 → PG       │              │  1. Redis (同步, 热路径)│
          │                     │              │  2. PG (异步, 持久化)  │
          └─────────┬──────────┘              └───┬───────────────┬───┘
                    │                              │               │
          ┌─────────▼──────────┐      ┌───────────▼───┐   ┌───────▼───────┐
          │   Redis             │      │   Redis       │   │   PostgreSQL   │
          │                     │      │               │   │               │
          │  agent:status/load  │      │  Task Queue   │   │  agents       │
          │  active tasks       │      │  (Stream)     │   │  tasks        │
          │                     │      │  Agent Status │   │  task_routes  │
          └─────────────────────┘      └───────────────┘   │  task_plans   │
                                                           │  subtasks     │
                                                           │  cap_tags     │
                                                           │  agent_tags   │
                                                           └───────────────┘
```

### 8.2 写入路径（任务提交流程）

```
POST /api/v1/tasks
       │
       ├─(1)─► Redis HSET task detail         ← 热路径，同步
       ├─(2)─► Redis XADD task to stream      ← 热路径，同步
       └─(3)─► PG INSERT task                 ← 持久化，异步或同步
              │
         Worker picks task from stream
              │
              ├─(4)─► AgentSelector.select()   ← 读 Redis agent 状态
              ├─(5)─► Redis HSET status=assigned
              ├─(6)─► PG UPDATE task (assigned)
              └─(7)─► PG INSERT task_route     ← 审计
                     │
                Execute on gateway
                     │
              ├─(8)─► Redis HSET status=done
              ├─(9)─► PG UPDATE task (done, result)
              └─(10)► Redis DEL task           ← 清理内存
```

### 8.3 读取路径

```
GET /api/v1/tasks (列表)
       │
       ├─ status=queued/assigned/executing/streaming → Redis (实时)
       └─ status=done/failed → PG (历史)
       └─ 无 status 过滤 → PG (分页)

GET /api/v1/tasks/{id} (详情)
       │
       ├─ Redis GET → 如果存在且 non-terminal → 返回
       └─ Redis GET → 不存在 → PG SELECT → 返回

GET /api/v1/agents (列表)
       │
       ├─ Redis HGETALL → 实时状态 (status, load, circuit)
       └─ PG SELECT → 静态 profile (models, capabilities, tags)
       └─ 合并两个数据源后返回

GET /api/v1/stats/* (统计)
       │
       └─ 全部走 PG (SQL 聚合)
```
