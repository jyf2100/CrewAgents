# Orchestrator 直连 PostgreSQL 读取 Agent 元数据

## 背景

Orchestrator 当前通过 Admin 内部 HTTP API (`http://hermes-admin:48082/internal/agents/metadata`) 读取 agent 的 tags/role/domain/skills。存在两个问题：

1. **网络策略阻断** — K8s NetworkPolicy 未允许 orchestrator 到 admin:48082 的出站流量
2. **运行时依赖** — admin pod 重启期间元数据不可用（虽然断路器 + 30 秒缓存可兜底）

改为 orchestrator 直接从 PostgreSQL 读取 `agent_metadata` 表。

## 数据流

```
Admin Panel (写入)                    Orchestrator (读取)
  ├─ PUT /agents/{id}/metadata         ├─ discover_pods() 每 30 秒
  │   → agent_metadata.tags/role       │   → SELECT from agent_metadata
  ├─ GET /agents/{id}/skills           │   → K8s pod list
  │   → agent_skills → aggregate       │   → 合并 → AgentProfile
  │     → agent_metadata.skills        │
  └─ PostgreSQL (source of truth)  ←───┘
```

## 字段来源分类

### 从 DB 读取（用户可编辑、需持久化）

| 字段 | 表.列 | 类型 | 说明 |
|------|--------|------|------|
| tags | agent_metadata.tags | JSONB | 用户编辑的标签 |
| role | agent_metadata.role | VARCHAR(50) | generalist/coder/analyst |
| domain | agent_metadata.domain | VARCHAR(20) | 由 `_resolve_domain()` 计算 |
| skills | agent_metadata.skills | JSONB | admin 扫描聚合的技能标签 |

### 保持 K8s 读取（运行时瞬态数据）

| 字段 | 来源 | 说明 |
|------|------|------|
| agent_id | pod.metadata.name | pod 名称 |
| gateway_url | pod.status.pod_ip + port | 每次 pod 重启都变 |
| api_key | K8s Secret hermes-db-secret | 集群密钥 |
| models/tool_ids/capabilities | gateway `/v1/models` 实时探测 | 运行时状态 |
| status/current_load/circuit_state | Redis 运行时状态 | 高频变更 |

## SQL 查询

```sql
SELECT agent_number, tags, role, domain, skills
FROM agent_metadata;
```

表小（通常 <20 行），无需 WHERE 或 JOIN。`agent_metadata.skills` 已是聚合后的数组。

注：`tags`/`role`/`domain`/`skills` 列均有 `NOT NULL` + `server_default`，无需 COALESCE。
`display_name`/`description` 故意不查 — 这些是展示字段，orchestrator 路由不需要。

## 安全模型

### 只读 PostgreSQL 用户

```sql
CREATE ROLE hermes_orchestrator_ro WITH LOGIN PASSWORD '<generated>';
GRANT CONNECT ON DATABASE hermes_admin TO hermes_orchestrator_ro;
GRANT USAGE ON SCHEMA public TO hermes_orchestrator_ro;
GRANT SELECT ON TABLE agent_metadata TO hermes_orchestrator_ro;
-- 防止未来 admin 新建的表自动可见
ALTER DEFAULT PRIVILEGES IN SCHEMA public FOR ROLE hermes REVOKE SELECT ON TABLES FROM hermes_orchestrator_ro;
```

- 只授权 `agent_metadata` 的 SELECT，不授权 `agent_skills`、`users` 等表
- `GRANT USAGE ON SCHEMA public` 允许列出 schema 对象，但不等于 SELECT 权限
- orchestrator 不需要写权限
- 与 admin 的 `hermes` 用户隔离，缩小攻击面
- 凭据轮换：修补 Secret 后需重启 orchestrator pod

## 代码改动

### 1. 新模块: `hermes_orchestrator/db.py`

```python
"""Lightweight asyncpg pool for orchestrator metadata queries."""
from __future__ import annotations
import logging
from typing import Any
import asyncpg

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None

_ROLE_TO_DOMAIN: dict[str, str] = {
    "generalist": "generalist",
    "coder": "code",
    "analyst": "data",
}

def _resolve_domain(domain: str | None, role: str | None) -> str:
    if domain:
        return domain
    return _ROLE_TO_DOMAIN.get(role or "generalist", "generalist")

async def init_pool(dsn: str) -> asyncpg.Pool:
    global _pool
    _pool = await asyncpg.create_pool(dsn, min_size=1, max_size=3, command_timeout=5)
    logger.info("asyncpg pool created (max_size=3)")
    return _pool

async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None

async def fetch_agent_metadata() -> dict[int, dict[str, Any]]:
    if _pool is None:
        return {}
    try:
        async with _pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT agent_number, tags, role, domain, skills "
                "FROM agent_metadata"
            )
        result: dict[int, dict[str, Any]] = {}
        for row in rows:
            role = row["role"]
            domain = row["domain"]
            result[row["agent_number"]] = {
                "tags": list(row["tags"]),
                "role": role,
                "domain": _resolve_domain(domain, role),
                "skills": list(row["skills"]),
            }
        return result
    except Exception:
        logger.debug("PostgreSQL metadata query failed", exc_info=True)
        return {}
```

### 2. 修改: `hermes_orchestrator/services/agent_discovery.py`

- 删除 `import httpx` 和 `import os`
- 删除 `_CircuitBreaker` 类
- 删除 `__init__` 中的 `_admin_url`、`_admin_token`、`_admin_cb`
- 替换 `_fetch_agent_metadata()` 方法体，调用 `db.fetch_agent_metadata()`
- 保留 30 秒内存缓存逻辑

### 3. 修改: `hermes_orchestrator/main.py`

- 加 `from hermes_orchestrator import db`
- lifespan 中 `await db.init_pool(config.database_url)`（try/except 包裹）
- shutdown 时 `await db.close_pool()`

### 4. 修改: `hermes_orchestrator/config.py`

```python
self.database_url = os.environ.get("DATABASE_URL", "")
```

### 5. 依赖: `pyproject.toml`

orchestrator extras 加 `asyncpg>=0.29,<1`。

## K8s 部署改动

### Secret

扩展现有 `hermes-orchestrator-secret`，加 `DATABASE_URL` key：

```bash
kubectl patch secret hermes-orchestrator-secret \
  -p '{"stringData":{"DATABASE_URL":"postgresql://hermes_orchestrator_ro:<password>@postgres:5432/hermes_admin"}}' \
  -n hermes-agent
```

### Deployment

```yaml
- name: DATABASE_URL
  valueFrom:
    secretKeyRef:
      name: hermes-orchestrator-secret
      key: DATABASE_URL
      optional: true   # Secret 缺失时 pod 仍启动，走回退路径
```

### NetworkPolicy

```yaml
- to:
    - podSelector:
        matchLabels:
          app: postgres
  ports:
    - port: 5432
      protocol: TCP
```

## 回退策略

两层降级，DB 失败自动切换到 K8s annotation：

```
PostgreSQL 直连 (实时，用户编辑的最新数据)
  → 失败时
K8s Pod Annotation (始终可用，但可能是创建时的过期快照)
```

- `optional: true` 确保 Secret 缺失时 pod 正常启动
- DB 连接池初始化失败仅 warning，不阻塞启动
- `fetch_agent_metadata()` 返回空 dict 时，`discover_pods()` 走 K8s annotation 回退
- 不再依赖 Admin HTTP API — 消除网络策略和 admin 可用性依赖

## 回滚方案

1. 删除 Secret 中的 `DATABASE_URL` key
2. 重启 orchestrator pod
3. orchestrator 回退到 K8s annotation 路径
4. 无需回滚 DDL（只读用户存在无害）或 NetworkPolicy（额外出站规则无害）

## 部署顺序

1. PostgreSQL 创建只读用户（一次性 SQL）
2. K8s Secret 加 `DATABASE_URL` key
3. 应用 NetworkPolicy
4. 构建新 orchestrator 镜像并部署
5. 验证日志确认元数据从 DB 读取

## 不改动的内容

- Admin panel 代码 — 继续写入 `agent_metadata` 表
- `agent_metadata` 表结构 — 无 DDL 变更
- 前端代码 — 无变化
- `agent_skills` 表 — orchestrator 不直接读，通过 `agent_metadata.skills` 聚合列获取
