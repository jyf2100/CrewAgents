# Hermes 智能路由 Phase 2 设计文档 — Manager Agent 路由

> 文档版本: 1.0-draft
> 日期: 2026-05-05
> 分支: feature/smart-routing-phase2
> 状态: 设计

---

## 1. 概述

Phase 2 在 Phase 1（基于负载的最小连接数选择）基础上引入 **Manager Agent** 概念。Manager Agent 是一个具有全局视野的 agent 实例，能够理解用户任务的语义，读取所有可用 agent 的 SOUL.md 摘要，做出智能的路由决策。

**核心原则**: Orchestrator 本身不调用 LLM，保持纯调度器定位。路由决策由 Manager Agent 自身完成，Orchestrator 只负责解析结构化结果并执行分配。

## 2. 架构概览

### 2.1 当前架构 (Phase 1)

```
用户 → POST /api/v1/tasks (prompt)
     → Redis Stream 队列
     → _process_task() 从队列取任务
     → AgentSelector.select() — 最小负载选择
     → TaskExecutor.submit_run() → Gateway POST /v1/runs
     → TaskExecutor.consume_run_events() → Gateway GET /v1/runs/{id}/events (SSE)
     → 结果写回 Redis
```

### 2.2 Phase 2 架构

```
用户 → POST /api/v1/tasks (prompt)
     → Redis Stream 队列
     → _process_task() 从队列取任务
     → 检测是否有 manager agent
     ├─ 无 manager → 回退到 Phase 1 最小负载选择
     └─ 有 manager → 构建 routing request
         → TaskExecutor.submit_run(manager_gateway, routing_prompt)
         → Manager 返回结构化 JSON 路由决策
         → Orchestrator 解析 JSON
         → TaskExecutor.submit_run(chosen_agent_gateway, original_prompt)
         → 消费结果，写回 Redis
```

### 2.3 关键约束

- **Orchestrator 不调 LLM**: 路由决策完全通过 Gateway API 委托给 Manager Agent
- **Manager 是普通 Agent**: Manager 本身就是一个 Hermes gateway 实例，有自己的 SOUL.md
- **回退安全**: Manager 不可用时自动降级到 Phase 1 负载均衡
- **幂等性**: 同一个路由请求多次发送应产生相同决策

## 3. Manager Agent 识别

### 3.1 K8s Annotation 标记

通过 K8s deployment annotation 标记 manager role:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: hermes-manager
  annotations:
    hermes.agent.role: "manager"
    hermes.agent.max_routing_tokens: "2000"
spec:
  template:
    metadata:
      labels:
        app.kubernetes.io/component: gateway
    spec:
      containers:
        - name: gateway
          volumeMounts:
            - name: data
              mountPath: /opt/data
      volumes:
        - name: data
          persistentVolumeClaim:
            claimName: manager-data
```

### 3.2 AgentProfile 扩展

在 `hermes_orchestrator/models/agent.py` 的 `AgentProfile` 中新增字段:

```python
@dataclass
class AgentProfile:
    # ... 现有字段 ...
    role: str = "worker"             # "worker" | "manager"
    soul_summary: str = ""           # SOUL.md 摘要（Discovery 缓存）
    soul_hash: str = ""              # SOUL.md 内容 hash（变更检测）
    capabilities_summary: str = ""   # 工具能力摘要（如 "terminal, web_search, file_operations"）
    max_routing_tokens: int = 2000   # Manager 路由决策最大 token
```

### 3.3 Discovery 识别逻辑

> **迁移说明**: 现有 Redis 中的 AgentProfile 条目没有 `role` 字段。由于 `role` 默认值为 `"worker"`，无需数据迁移——Discovery Loop 重新注册时会自动写入新字段，旧条目在下次注册时更新即可。

在 `AgentDiscoveryService._pod_to_profile()` 中读取 annotation:

```python
def _pod_to_profile(self, pod) -> AgentProfile:
    annotations = pod.metadata.annotations or {}
    role = annotations.get("hermes.agent.role", "worker")
    max_routing_tokens = int(annotations.get("hermes.agent.max_routing_tokens", "2000"))
    return AgentProfile(
        agent_id=pod.metadata.name,
        gateway_url=self._build_pod_url(pod),
        registered_at=time.time(),
        max_concurrent=self._config.agent_max_concurrent,
        status="online",
        role=role,
        max_routing_tokens=max_routing_tokens,
    )
```

## 4. SOUL.md 读取机制

### 4.1 Gateway 新端点: GET /v1/identity

> **依赖说明**: `_refresh_soul_summary()` 使用 `aiohttp` 发起 HTTP 请求。`aiohttp` 已是 Orchestrator 现有依赖（Gateway 通信、健康检查等均使用），无需新增安装。

在 Gateway 端（`gateway/run.py`）新增端点，返回 agent 自描述信息:

```python
@app_api_route("/v1/identity", methods=["GET"])
async def get_identity():
    """返回 agent 身份描述（SOUL.md 内容 + 能力摘要）。"""
    soul_content = ""
    soul_path = Path("/opt/data/SOUL.md")
    if soul_path.exists():
        try:
            soul_content = soul_path.read_text(encoding="utf-8")
        except Exception:
            pass

    # 获取工具能力列表
    from tools.registry import registry
    available_tools = registry.list_available_tools()
    capabilities = sorted(set(t.split(".")[0] for t in available_tools))

    return {
        "soul": soul_content,
        "capabilities": capabilities,
        "model": os.getenv("HERMES_DEFAULT_MODEL", ""),
    }
```

**设计要点**:
- 返回完整 SOUL.md 内容，由调用方（Discovery）负责摘要
- 包含工具能力列表，供路由决策参考
- 无需认证（仅集群内访问，通过 NetworkPolicy 保护）

### 4.2 Discovery Loop 缓存

在 `_run_discovery_loop()` 中增加 SOUL.md 拉取:

```python
async def _run_discovery_loop():
    loop = asyncio.get_event_loop()
    while True:
        try:
            profiles = await discovery.discover_pods()
            for p in profiles:
                # 拉取 SOUL.md（仅当 hash 变化时）
                if p.role == "worker":
                    await _refresh_soul_summary(p)
                # ... 现有注册逻辑 ...
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("Discovery loop error: %s", e)
        await asyncio.sleep(30)


async def _refresh_soul_summary(profile: AgentProfile):
    """拉取 agent 的 SOUL.md 并缓存摘要。"""
    try:
        import hashlib
        import aiohttp

        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{profile.gateway_url}/v1/identity",
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    return
                data = await resp.json()

        soul = data.get("soul", "")
        capabilities = data.get("capabilities", [])
        new_hash = hashlib.sha256(soul.encode()).hexdigest()[:16]

        # 仅当内容变化时更新
        if new_hash != profile.soul_hash:
            summary = _truncate_soul(soul, max_chars=500)
            profile.soul_summary = summary
            profile.soul_hash = new_hash
            profile.capabilities_summary = ", ".join(capabilities)
    except Exception as e:
        logger.debug("SOUL.md refresh failed for %s: %s", profile.agent_id, e)


def _truncate_soul(soul: str, max_chars: int = 500) -> str:
    """截取 SOUL.md 前 N 字符作为摘要。"""
    if len(soul) <= max_chars:
        return soul
    # 优先取第一段
    lines = soul.split("\n")
    result = []
    total = 0
    for line in lines:
        if total + len(line) + 1 > max_chars:
            break
        result.append(line)
        total += len(line) + 1
    return "\n".join(result) + "\n..."
```

### 4.3 变更检测策略

| 维度 | 策略 |
|------|------|
| 检测频率 | 每 30 秒（跟随 Discovery Loop） |
| 变更判定 | SHA256 前 16 位 hash 对比 |
| 更新触发 | hash 不同时更新 soul_summary |
| 存储 | Redis AgentProfile JSON（内存） |
| 最大摘要长度 | 500 字符（约 200-300 token） |

## 5. Manager Agent Prompt 设计

### 5.1 System Prompt 模板

Manager Agent 的 SOUL.md 中应包含以下路由指令:

```markdown
---
name: hermes-manager
description: 智能路由管理器 — 根据任务语义和 agent 能力做出最优路由决策
---

# Hermes Router

你是一个智能路由管理器。你的职责是根据用户任务的语义，从可用的 agent 列表中选择最合适的 agent 来处理任务。

## 决策原则

1. **能力匹配**: 选择具备完成任务所需工具和技能的 agent
2. **负载均衡**: 在能力匹配的前提下，优先选择负载较低的 agent
3. **专业匹配**: 如果有 agent 的 SOUL.md 表明它擅长该类任务，优先选择
4. **兜底选择**: 如果没有明确最佳选择，选择负载最低的通用 agent

## 输出格式

你必须输出一个 JSON 对象，不要输出其他内容。

## 选择策略

- 简单查询/闲聊 → 选择负载最低的 agent
- 代码开发任务 → 选择有 terminal + file 工具的 agent
- Web 研究 → 选择有 web_search 工具的 agent
- 数据分析 → 选择有 terminal + execute_code 的 agent
- 多步骤复杂任务 → 建议拆分（但仅在有明确子任务边界时）
```

### 5.2 输入格式 (User Message)

Orchestrator 发送给 Manager 的 prompt 格式:

```
## 路由请求

### 用户任务
{task.prompt}

### 可用 Agent 列表

{agent_1.agent_id}:
- 状态: {status}
- 当前负载: {current_load}/{max_concurrent}
- 能力: {capabilities_summary}
- 简介: {soul_summary}

{agent_2.agent_id}:
...

请选择最合适的 agent 来处理此任务。输出 JSON:
```

### 5.3 输出格式 (JSON Schema)

Manager 返回的结构化 JSON:

```json
{
  "decision": "route",
  "selected_agent": "hermes-gateway-1",
  "confidence": 0.9,
  "reasoning": "该任务需要代码开发，gateway-1 具备 terminal 和 file 工具，且负载最低",
  "suggested_decomposition": null
}
```

**JSON Schema 定义**:

```python
ROUTING_DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {
            "type": "string",
            "enum": ["route", "decompose", "reject"]
        },
        "selected_agent": {
            "type": "string",
            "description": "被选中的 agent_id（decision=route 时必填）"
        },
        "confidence": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
            "description": "决策置信度"
        },
        "reasoning": {
            "type": "string",
            "description": "选择理由（用于审计和前端展示）"
        },
        "suggested_decomposition": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "subtask_description": {"type": "string"},
                    "suggested_agent": {"type": "string"},
                    "depends_on": {
                        "type": "array",
                        "items": {"type": "integer"}
                    }
                },
                "required": ["subtask_description"]
            },
            "description": "任务拆分建议（decision=decompose 时使用，Phase 3 实现）"
        }
    },
    "required": ["decision", "confidence", "reasoning"]
}
```

### 5.4 完整 Prompt 示例

**输入**（Orchestrator → Manager）:

```
## 路由请求

### 用户任务
帮我写一个 Python 脚本，从 Redis 中读取所有 hermes-agent 的任务状态，生成一个 CSV 报告，包含任务ID、状态、执行时长、分配的 agent。

### 可用 Agent 列表

hermes-coder:
- 状态: online
- 当前负载: 2/10
- 能力: terminal, file_operations, web_search
- 简介: 专注于代码开发和文件操作。擅长 Python、Shell 脚本。
  有 Redis 客户端工具，可以直接查询 Redis。

hermes-researcher:
- 状态: online
- 当前负载: 0/10
- 能力: web_search, web_extract, terminal
- 简介: 专注于信息搜索和研究。擅长总结和分析。

hermes-general-1:
- 状态: online
- 当前负载: 5/10
- 能力: terminal, file_operations, web_search
- 简介: 通用 AI 助手。

请选择最合适的 agent 来处理此任务。输出 JSON:
```

**输出**（Manager 返回）:

```json
{
  "decision": "route",
  "selected_agent": "hermes-coder",
  "confidence": 0.92,
  "reasoning": "任务需要：1) Redis 客户端查询能力；2) CSV 文件生成；3) Python 脚本编写。hermes-coder 具备全部能力且简介明确提到 Redis 工具，负载适中。hermes-researcher 虽负载更低但无 Redis/file 能力。",
  "suggested_decomposition": null
}
```

## 6. Orchestrator 改造

### 6.1 新增路由服务

创建 `hermes_orchestrator/services/routing_service.py`:

```python
"""Manager-based routing service — builds prompts, parses decisions."""
from __future__ import annotations

import json
import logging
import re

from hermes_orchestrator.models.agent import AgentProfile
from hermes_orchestrator.models.task import Task

logger = logging.getLogger(__name__)

_ROUTING_PROMPT_TEMPLATE = """\
## 路由请求

### 用户任务
{task_prompt}

### 可用 Agent 列表

{agent_list}

请选择最合适的 agent 来处理此任务。输出 JSON:"""

_AGENT_ENTRY_TEMPLATE = """\
{agent_id}:
- 状态: {status}
- 当前负载: {current_load}/{max_concurrent}
- 能力: {capabilities}
- 简介: {soul_summary}"""


class RoutingService:
    """构建路由请求 prompt 并解析 Manager 返回的 JSON 决策。

    纯状态less工具类，不持有 executor 或任何外部依赖。
    """

    def build_routing_prompt(self, task: Task, agents: list[AgentProfile]) -> str:
        """构建发送给 Manager 的路由请求 prompt。

        注意: task.prompt 在传入路由 prompt 前截断到 1000 字符。
        这是安全防护措施——最坏情况下 Manager 仅产生次优路由决策，
        不涉及数据泄露或权限提升（prompt 注入风险仅影响任务分配质量）。
        """
        agent_entries = []
        for a in agents:
            if a.role == "manager":
                continue  # 不把自己列入候选
            agent_entries.append(
                _AGENT_ENTRY_TEMPLATE.format(
                    agent_id=a.agent_id,
                    status=a.status,
                    current_load=a.current_load,
                    max_concurrent=a.max_concurrent,
                    capabilities=a.capabilities_summary or "N/A",
                    soul_summary=a.soul_summary or "无简介",
                )
            )
        return _ROUTING_PROMPT_TEMPLATE.format(
            task_prompt=task.prompt[:1000],
            agent_list="\n\n".join(agent_entries),
        )

    def parse_routing_response(self, raw_output: str) -> dict | None:
        """从 Manager 返回的原始文本中提取 JSON 路由决策。

        支持以下格式:
        - 纯 JSON: {"decision": "route", ...}
        - Markdown 代码块: ```json\\n{...}\\n```
        - 前后带文本的 JSON: 一些文字 {"decision": ...} 一些文字
        """
        # 尝试提取 markdown 代码块中的 JSON
        md_match = re.search(r"```(?:json)?\s*\n?(.*?)```", raw_output, re.DOTALL)
        if md_match:
            candidate = md_match.group(1).strip()
        else:
            candidate = raw_output.strip()

        # 尝试提取最外层 { } 之间的 JSON
        brace_match = re.search(r"\{.*\}", candidate, re.DOTALL)
        if brace_match:
            candidate = brace_match.group(0)

        try:
            result = json.loads(candidate)
            if isinstance(result, dict) and "decision" in result:
                return result
        except json.JSONDecodeError:
            pass

        logger.warning("Failed to parse routing response as JSON: %.200s", raw_output)
        return None

    def validate_decision(
        self, decision: dict, agents: list[AgentProfile]
    ) -> str | None:
        """验证路由决策的合法性。返回选中的 agent_id 或 None。"""
        action = decision.get("decision")

        if action == "reject":
            logger.info("Manager rejected task: %s", decision.get("reasoning", ""))
            return None

        if action != "route":
            logger.warning("Unexpected decision type: %s", action)
            return None

        selected = decision.get("selected_agent")
        if not selected:
            logger.warning("Route decision missing selected_agent")
            return None

        # 验证选中的 agent 存在且可用
        agent_ids = {a.agent_id for a in agents if a.status in ("online", "degraded")}
        if selected not in agent_ids:
            logger.warning(
                "Manager selected unavailable agent: %s (available: %s)",
                selected,
                ", ".join(sorted(agent_ids)),
            )
            return None

        return selected
```

### 6.2 main.py _process_task() 改造

修改 `hermes_orchestrator/main.py` 中的 `_process_task()`:

```python
async def _process_task(task_id: str):
    loop = asyncio.get_event_loop()
    task = await loop.run_in_executor(None, task_store.get, task_id)
    if not task:
        return

    agents = await loop.run_in_executor(None, agent_registry.list_agents)

    # --- Phase 2: Manager-based routing ---
    managers = [a for a in agents if a.role == "manager" and a.status in ("online", "degraded")]
    workers = [a for a in agents if a.role != "manager" and a.status in ("online", "degraded")]

    if managers and workers and routing_service:
        chosen = await _route_via_manager(task, managers[0], workers)
    else:
        # Phase 1 fallback: 委托给 AgentSelector（最小负载选择）
        chosen = selector.select(workers, task)

    if not chosen:
        await loop.run_in_executor(
            None,
            partial(
                task_store.update, task_id, status="failed", error="No available agent"
            ),
        )
        return

    # --- 以下与 Phase 1 相同: 提交任务到选中 agent ---
    await loop.run_in_executor(
        None,
        partial(task_store.update, task_id, status="assigned", assigned_agent=chosen.agent_id),
    )
    await loop.run_in_executor(
        None, agent_registry.update_load, chosen.agent_id, chosen.current_load + 1
    )
    try:
        # ... 现有的 submit_run + consume_run_events 逻辑 ...
        pass
    finally:
        updated = await loop.run_in_executor(None, agent_registry.get, chosen.agent_id)
        if updated:
            await loop.run_in_executor(
                None,
                agent_registry.update_load,
                chosen.agent_id,
                max(0, updated.current_load - 1),
            )


async def _route_via_manager(
    task: Task,
    manager: AgentProfile,
    workers: list[AgentProfile],
) -> AgentProfile | None:
    """通过 Manager Agent 做路由决策。"""
    loop = asyncio.get_event_loop()
    prompt = routing_service.build_routing_prompt(task, workers)

    try:
        # 设置较短的超时（路由决策不需要太长时间）
        run_id = await executor.submit_run(
            manager.gateway_url,
            prompt,
            instructions="请分析任务并选择最合适的 agent。只输出 JSON，不要输出其他内容。",
            headers=manager.gateway_headers(),
        )
        run_result = await executor.consume_run_events(
            manager.gateway_url,
            run_id,
            max_wait=config.manager_routing_timeout,  # 默认 15 秒
            headers=manager.gateway_headers(),
        )

        if run_result.status != "completed":
            logger.warning("Manager routing run failed: %s", run_result.error)
            return None

        decision = routing_service.parse_routing_response(run_result.output)
        if not decision:
            logger.warning("Manager returned unparseable response")
            return None

        selected_id = routing_service.validate_decision(decision, workers)
        if not selected_id:
            return None

        # 记录路由决策到任务 metadata 并持久化到 Redis
        task.metadata["routing_decision"] = {
            "manager": manager.agent_id,
            "selected": selected_id,
            "confidence": decision.get("confidence"),
            "reasoning": decision.get("reasoning", ""),
        }
        await loop.run_in_executor(
            None,
            partial(task_store.update, task_id, metadata=task.metadata),
        )

        # 返回选中的 AgentProfile
        return next((w for w in workers if w.agent_id == selected_id), None)

    except Exception as e:
        logger.warning("Manager routing failed, falling back to load-based: %s", e)
        return None
```

### 6.3 Lifespan 初始化

在 `lifespan()` 中初始化 RoutingService:

```python
routing_service = RoutingService()
```

添加全局变量声明:

```python
routing_service: RoutingService | None = None
```

## 7. 配置扩展

### 7.1 OrchestratorConfig 新增

```python
class OrchestratorConfig:
    # ... 现有字段 ...
    self.manager_routing_enabled = os.environ.get(
        "MANAGER_ROUTING_ENABLED", "true"
    ).lower() in ("true", "1", "yes")
    self.manager_routing_timeout = float(
        os.environ.get("MANAGER_ROUTING_TIMEOUT", "15.0")
    )
    self.manager_routing_fallback = os.environ.get(
        "MANAGER_ROUTING_FALLBACK", "true"
    ).lower() in ("true", "1", "yes")
```

### 7.2 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MANAGER_ROUTING_ENABLED` | `true` | 是否启用 Manager 路由 |
| `MANAGER_ROUTING_TIMEOUT` | `15.0` | Manager 路由决策超时（秒） |
| `MANAGER_ROUTING_FALLBACK` | `true` | Manager 不可用时是否回退到负载均衡 |

## 8. 错误处理

### 8.1 回退策略

| 场景 | 处理方式 |
|------|---------|
| 无 manager agent 注册 | 直接使用 Phase 1 负载均衡 |
| manager circuit breaker OPEN | 跳过 manager，使用负载均衡 |
| manager 路由请求超时 | 15 秒超时后降级到负载均衡 |
| manager 返回非 JSON | 记录 warning，降级到负载均衡 |
| manager 选择了不存在的 agent | 记录 warning，降级到负载均衡 |
| manager 返回 decision=reject | 任务标记为 failed，附带 rejection 理由 |
| 所有 worker 都不可用 | 任务标记为 failed（无论是否有 manager） |

### 8.2 降级流程

```python
async def _process_task(task_id: str):
    # ...
    try:
        if managers and workers and config.manager_routing_enabled:
            chosen = await _route_via_manager(task, managers[0], workers)
        else:
            chosen = None
    except Exception as e:
        logger.warning("Manager routing exception: %s", e)
        chosen = None

    # Fallback to Phase 1
    if chosen is None and config.manager_routing_fallback:
        chosen = selector.select(workers, task)

    if not chosen:
        # 失败处理
        pass
```

### 8.3 审计日志

路由决策记录到任务 metadata 中，用于事后审计:

```python
task.metadata["routing_decision"] = {
    "method": "manager" | "load_balanced",
    "manager": manager_id,           # 仅 manager 路由时
    "selected": chosen_agent_id,
    "confidence": float,             # 仅 manager 路由时
    "reasoning": str,                # 仅 manager 路由时
    "fallback": bool,                # 是否从 manager 降级到负载均衡
    "timestamp": float,
}
```

## 9. 测试计划

### 9.1 单元测试

| 测试 | 验证点 |
|------|--------|
| `test_build_routing_prompt` | prompt 包含所有 agent 信息和任务描述 |
| `test_parse_routing_response_pure_json` | 正确解析纯 JSON 响应 |
| `test_parse_routing_response_markdown_code_block` | 正确解析 ```json 包裹的响应 |
| `test_parse_routing_response_with_surrounding_text` | 正确提取嵌入文本中的 JSON |
| `test_parse_routing_response_invalid` | 无效输入返回 None |
| `test_validate_decision_valid` | 合法决策返回 agent_id |
| `test_validate_decision_unknown_agent` | 选中不存在的 agent 返回 None |
| `test_validate_decision_reject` | reject 决策返回 None |
| `test_agent_profile_role_field` | role 字段序列化/反序列化正确 |

### 9.2 集成测试

| 测试 | 验证点 |
|------|--------|
| `test_manager_routing_e2e` | Manager 返回有效 JSON，任务路由到正确 agent |
| `test_manager_fallback_on_timeout` | Manager 超时后降级到负载均衡 |
| `test_manager_fallback_on_invalid_json` | Manager 返回无效 JSON 后降级 |
| `test_manager_fallback_on_unavailable` | Manager 不在线时降级 |
| `test_soul_summary_refresh` | Discovery loop 正确拉取和缓存 SOUL.md |

### 9.3 测试工具

使用 mock Gateway（返回预定义 JSON）来测试路由逻辑:

```python
import pytest
from unittest.mock import AsyncMock, patch
from hermes_orchestrator.services.routing_service import RoutingService

@pytest.fixture
def routing_service():
    return RoutingService()

def test_parse_routing_response_pure_json(routing_service):
    raw = '{"decision": "route", "selected_agent": "gw-1", "confidence": 0.9, "reasoning": "test"}'
    result = routing_service.parse_routing_response(raw)
    assert result["decision"] == "route"
    assert result["selected_agent"] == "gw-1"
```

## 10. 实施步骤

1. **扩展 AgentProfile** — 新增 role, soul_summary, soul_hash, capabilities_summary 字段
2. **实现 RoutingService** — prompt 构建 + JSON 解析 + 决策验证
3. **改造 _process_task()** — 增加 manager 路由分支和降级逻辑
4. **Gateway 新增 /v1/identity** — 返回 SOUL.md + 能力列表
5. **Discovery Loop 扩展** — 拉取 SOUL.md 摘要和 hash
6. **配置扩展** — 新增 manager routing 相关环境变量
7. **编写测试** — 单元测试 + 集成测试
8. **部署 Manager Agent** — 创建带有 role=manager annotation 的 K8s deployment
```

---

**File: `/mnt/disk01/workspaces/worksummary/hermes-agent/docs/plans/smart-routing-phase3.md`**

```markdown
# 智能路由 Phase 3: