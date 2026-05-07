# Hermes 智能路由 Phase 1 设计文档

> 文档版本：1.0  
> 日期：2026-05-05  
> 分支：feature/smart-routing-phase1  
> 作者：Architecture Review

---

## 目录

1. [目标与非目标](#1-目标与非目标)
2. [数据模型变更](#2-数据模型变更)
3. [AgentSelector 改造](#3-agentselector-改造)
4. [Discovery Loop 改造](#4-discovery-loop-改造)
5. [API 变更](#5-api-变更)
6. [前端变更](#6-前端变更)
7. [K8s 部署变更](#7-k8s-部署变更)
8. [灰度上线方案](#8-灰度上线方案)
9. [测试计划](#9-测试计划)
10. [风险与缓解](#10-风险与缓解)

---

## 1. 目标与非目标

### 1.1 Phase 1 目标

- 让 Orchestrator 能根据 task prompt 的语义关键词匹配到最合适的 agent
- Agent 的能力标签来自 K8s deployment annotation，运维可随时修改
- 当匹配分数不足时，自动回退到现有的最少负载策略，保证零退化
- 提交 task 时允许指定 `required_tags` 强制约束目标 agent 必须具备的标签
- 路由决策过程可观测：每次 task 的路由信息（评分、决策原因）持久化并可通过 API 查询
- 支持影子模式运行，新旧路由结果对比验证后再灰度切流

### 1.2 Phase 1 非目标

- 不使用 LLM 做语义匹配（Phase 2 考虑 embedding 向量检索）
- 不做跨 agent 的任务拆分/编排
- 不做历史任务的学习反馈（命中率统计在 Phase 2）
- 不修改 gateway 本身的任何代码
- 不新增 Redis 数据结构（复用现有 hash）

---

## 2. 数据模型变更

### 2.1 AgentProfile 新增字段

`hermes_orchestrator/models/agent.py`

```python
from __future__ import annotations

from dataclasses import dataclass, field, asdict


@dataclass
class AgentCapability:
    gateway_url: str
    model_id: str
    capabilities: dict = field(default_factory=dict)
    tool_ids: list[str] = field(default_factory=list)
    supported_endpoints: list[str] = field(default_factory=list)


@dataclass
class AgentProfile:
    agent_id: str
    gateway_url: str
    registered_at: float
    api_key: str = ""
    models: list[str] = field(default_factory=list)
    capabilities: dict = field(default_factory=dict)
    tool_ids: list[str] = field(default_factory=list)
    status: str = "online"  # online | degraded | offline
    current_load: int = 0
    max_concurrent: int = 10
    last_health_check: float = 0.0
    circuit_state: str = "closed"  # closed | open | half_open
    # --- Phase 1 新增 ---
    tags: list[str] = field(default_factory=list)
    # role 语义更宽：generalist, coder, analyst, creative 等
    role: str = "generalist"

    def gateway_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> AgentProfile:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
```

变更说明：
- `tags: list[str]` -- 从 K8s annotation `hermes-agent.io/capabilities` 解析得到。例如 `["code", "python", "debugging"]`。不区分大小写存储（统一 lower）。
- `role: str` -- 从 K8s annotation `hermes-agent.io/role` 读取，默认 `"generalist"`。
- 新增字段均有 `default_factory` 或默认值，Redis 中已有序列化数据反序列化时不会报错。

向后兼容性：`from_dict` 使用 `__dataclass_fields__` 过滤，旧数据没有 `tags`/`role` 字段时会使用默认值。`RedisAgentRegistry.register` 序列化 `to_dict()` 时自然包含新字段。无需 Redis 迁移。

### 2.2 Task 新增字段

`hermes_orchestrator/models/task.py`

```python
from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict


@dataclass
class TaskResult:
    content: str
    usage: dict
    duration_seconds: float
    run_id: str


@dataclass
class RunResult:
    run_id: str
    status: str  # "completed" | "failed"
    output: str = ""
    usage: dict | None = None
    error: str | None = None


@dataclass
class RoutingInfo:
    """一次路由决策的完整记录。"""
    strategy: str          # "tag_match" | "least_load" | "required_tags" | "shadow"
    chosen_agent_id: str | None
    scores: dict[str, float]  # agent_id → 匹配分
    matched_tags: list[str]   # 命中的标签
    fallback: bool             # 是否回退到 least_load
    reason: str                # 人类可读的决策原因
    # 影子模式专用字段：记录智能路由的决策（chosen_agent_id 反映 least_load 选择）
    shadow_smart_agent_id: str | None = None
    shadow_smart_score: float | None = None


@dataclass
class Task:
    task_id: str
    prompt: str
    created_at: float
    instructions: str = ""
    model_id: str = "hermes-agent"
    status: str = "submitted"
    assigned_agent: str | None = None
    run_id: str | None = None
    result: TaskResult | None = None
    error: str | None = None
    retry_count: int = 0
    max_retries: int = 2
    priority: int = 1
    timeout_seconds: float = 600.0
    updated_at: float = 0.0
    metadata: dict = field(default_factory=dict)
    callback_url: str | None = None
    # --- Phase 1 新增 ---
    required_tags: list[str] = field(default_factory=list)
    routing_info: RoutingInfo | None = None

    def __post_init__(self):
        if self.updated_at == 0.0:
            self.updated_at = self.created_at

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Task:
        result = None
        if data.get("result"):
            result = TaskResult(**data["result"])
        data["result"] = result
        routing_info = None
        if data.get("routing_info"):
            routing_info = RoutingInfo(**data["routing_info"])
        data["routing_info"] = routing_info
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
```

变更说明：
- `required_tags: list[str]` -- 调用方指定的硬性约束，agent 必须具备这些标签才能被选中。默认空列表表示无约束。
- `routing_info: RoutingInfo | None` -- 记录本次路由的完整决策过程，用于可观测性和后续分析。
- `RoutingInfo` 是新增 dataclass，包含策略名、候选打分、命中标签、是否回退等信息。

向后兼容性：同 AgentProfile，`from_dict` 过滤未知字段，默认值保证旧数据兼容。

### 2.3 TaskSubmitRequest 新增字段

`hermes_orchestrator/models/api.py`

```python
class TaskSubmitRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=50000)
    instructions: str = Field("", max_length=10000)
    model_id: str = "hermes-agent"
    priority: int = Field(1, ge=1, le=10)
    timeout_seconds: float = Field(600.0, ge=10.0, le=3600.0)
    max_retries: int = Field(2, ge=0, le=5)
    callback_url: str | None = None
    metadata: dict = Field(default_factory=dict)
    # --- Phase 1 新增 ---
    required_tags: list[str] = Field(
        default_factory=list,
        description="Agent 必须具备的能力标签（AND 关系）。空列表表示无约束。",
    )
```

### 2.4 TaskStatusResponse 新增字段

```python
class TaskStatusResponse(BaseModel):
    task_id: str
    status: str
    assigned_agent: str | None = None
    run_id: str | None = None
    result: dict | None = None
    error: str | None = None
    retry_count: int = 0
    created_at: float
    updated_at: float
    # --- Phase 1 新增 ---
    routing_info: dict | None = None
```

---

## 3. AgentSelector 改造

### 3.1 设计思路

路由分为三级优先级：

1. **required_tags 强制约束**：如果 task 指定了 `required_tags`，只考虑 tags 是 required_tags 超集的 agent。如果没有 agent 满足，直接返回 None（不做回退，因为这是调用方的硬性要求）。
2. **tag_match 评分匹配**：从 task prompt + instructions 中提取关键词，与每个 agent 的 tags 做交集，计算匹配分数。取分数最高的 agent。如果最高分低于阈值（`TAG_MATCH_MIN_SCORE = 0.15`），回退到 least_load。
3. **least_load 回退**：保持现有逻辑不变。

### 3.2 完整代码

`hermes_orchestrator/services/agent_selector.py`

```python
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from hermes_orchestrator.models.agent import AgentProfile
from hermes_orchestrator.models.task import Task, RoutingInfo

logger = logging.getLogger(__name__)

# 匹配分数低于此值时回退到 least_load
TAG_MATCH_MIN_SCORE = 0.15

# 关键词提取的停用词
_STOP_WORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "can", "shall", "to", "of", "in", "for",
    "on", "with", "at", "by", "from", "as", "into", "through", "during",
    "before", "after", "above", "below", "between", "out", "off", "over",
    "under", "again", "further", "then", "once", "here", "there", "when",
    "where", "why", "how", "all", "both", "each", "few", "more", "most",
    "other", "some", "such", "no", "nor", "not", "only", "own", "same",
    "so", "than", "too", "very", "just", "because", "but", "and", "or",
    "if", "while", "about", "up", "it", "its", "i", "me", "my", "we",
    "our", "you", "your", "he", "him", "his", "she", "her", "they",
    "them", "their", "this", "that", "these", "those", "what", "which",
    "who", "whom", "please", "help", "need", "want", "make", "like",
    "get", "got", "go", "going", "come", "take", "give", "tell",
    "say", "said", "know", "think", "see", "look", "find", "use",
    "try", "ask", "put", "keep", "let", "begin", "seem", "show",
    "hear", "play", "run", "move", "live", "believe", "happen",
    "also", "back", "still", "even", "much", "well", "really",
    # 中文停用词
    "的", "了", "在", "是", "我", "有", "和", "就", "不", "人",
    "都", "一", "一个", "上", "也", "很", "到", "说", "要", "去",
    "你", "会", "着", "没有", "看", "好", "自己", "这", "他", "她",
    "它", "们", "那", "些", "什么", "怎么", "可以", "能", "把",
    "被", "让", "给", "对", "与", "从", "以", "为", "之", "中",
})

# 从 prompt 中提取 tag 的扩展映射：用户常见词汇 → 标准化 tag
_TAG_ALIASES: dict[str, list[str]] = {
    "python": ["python", "code"],
    "javascript": ["javascript", "code"],
    "js": ["javascript", "code"],
    "typescript": ["typescript", "code"],
    "ts": ["typescript", "code"],
    "java": ["java", "code"],
    "go": ["golang", "code"],
    "golang": ["golang", "code"],
    "rust": ["rust", "code"],
    "code": ["code"],
    "coding": ["code"],
    "program": ["code"],
    "programming": ["code"],
    "debug": ["debugging"],
    "debugging": ["debugging"],
    "fix": ["debugging"],
    "bug": ["debugging"],
    "error": ["debugging"],
    "analyze": ["analysis"],
    "analysis": ["analysis"],
    "data": ["analysis"],
    "chart": ["analysis"],
    "graph": ["analysis"],
    "write": ["creative"],
    "article": ["creative"],
    "blog": ["creative"],
    "story": ["creative"],
    "creative": ["creative"],
    "translate": ["translation"],
    "translation": ["translation"],
    "explain": ["explanation"],
    "explaination": ["explanation"],
    "documentation": ["documentation"],
    "docs": ["documentation"],
    "search": ["search"],
    "research": ["research"],
    "deploy": ["devops"],
    "deployment": ["devops"],
    "docker": ["devops", "code"],
    "kubernetes": ["devops"],
    "k8s": ["devops"],
    "devops": ["devops"],
    "test": ["testing"],
    "testing": ["testing"],
    "review": ["code-review"],
    "refactor": ["code-review", "code"],
    "database": ["database"],
    "sql": ["database"],
    "query": ["database"],
    "api": ["api"],
    "rest": ["api"],
    "grpc": ["api"],
}


def _extract_keywords(text: str) -> set[str]:
    """从文本中提取标准化关键词集合。"""
    # 统一小写
    text_lower = text.lower()
    # 提取英文单词（2+ 字符）和 CJK 字符段
    words: set[str] = set()
    # 英文单词
    for w in re.findall(r"[a-z]{2,}", text_lower):
        if w not in _STOP_WORDS and len(w) > 1:
            words.add(w)
    # CJK 字符段（连续中日韩字符）
    for m in re.findall(r"[\u4e00-\u9fff\u3400-\u4dbf]+", text_lower):
        if len(m) >= 2 and m not in _STOP_WORDS:
            words.add(m)

    # 通过别名映射展开为标准 tag
    expanded: set[str] = set()
    for w in words:
        if w in _TAG_ALIASES:
            expanded.update(_TAG_ALIASES[w])
        else:
            expanded.add(w)
    return expanded


def _compute_tag_score(
    task_tags: set[str],
    agent_tags: list[str],
) -> tuple[float, list[str]]:
    """计算 task 关键词与 agent tags 的匹配分。返回 (score, matched_tags)。

    使用 Jaccard 相似度：|intersection| / |union|。
    相比简单的覆盖率，Jaccard 会惩罚 agent 堆砌大量无关 tag 的行为（union 变大，
    分数下降），同时不会因为 agent tag 丰富而惩罚它。
    """
    if not task_tags or not agent_tags:
        return 0.0, []
    agent_tag_set = {t.lower() for t in agent_tags}
    matched = task_tags & agent_tag_set
    if not matched:
        return 0.0, []
    union = task_tags | agent_tag_set
    score = len(matched) / len(union)
    return score, sorted(matched)


@dataclass
class _SelectionResult:
    agent: AgentProfile | None
    routing_info: RoutingInfo


class AgentSelector:
    def select(self, agents: list[AgentProfile], task: Task) -> tuple[AgentProfile | None, RoutingInfo | None]:
        """选择最合适的 agent 执行 task。

        返回 (agent, routing_info)。agent 为 None 表示无可用 agent。
        routing_info 始终生成，用于可观测性。
        """
        # 过滤不可用的 agent
        available = [
            a for a in agents
            if a.status in ("online", "degraded")
            and a.current_load < a.max_concurrent
            and a.circuit_state != "open"
        ]
        if not available:
            logger.warning(
                "No available agent for task %s (checked %d agents)",
                task.task_id, len(agents),
            )
            return None, None

        # Level 1: required_tags 硬约束
        if task.required_tags:
            required_set = {t.lower() for t in task.required_tags}
            candidates = []
            for a in available:
                agent_tag_set = {t.lower() for t in a.tags}
                if required_set.issubset(agent_tag_set):
                    candidates.append(a)
            if not candidates:
                logger.warning(
                    "Task %s required_tags %s not satisfied by any agent",
                    task.task_id, task.required_tags,
                )
                routing_info = RoutingInfo(
                    strategy="required_tags",
                    chosen_agent_id=None,
                    scores={},
                    matched_tags=[],
                    fallback=False,
                    reason=f"No agent satisfies required_tags: {task.required_tags}",
                )
                return None, routing_info
            # 在满足约束的候选中按 least_load 排序
            candidates.sort(key=lambda a: (a.current_load, a.last_health_check))
            chosen = candidates[0]
            routing_info = RoutingInfo(
                strategy="required_tags",
                chosen_agent_id=chosen.agent_id,
                scores={c.agent_id: 1.0 for c in candidates},
                matched_tags=sorted(required_set),
                fallback=False,
                reason=f"Required tags matched, selected least-loaded: {chosen.agent_id}",
            )
            return chosen, routing_info

        # Level 2: tag_match 评分
        source_text = f"{task.prompt} {task.instructions}"
        task_keywords = _extract_keywords(source_text)
        scores: dict[str, float] = {}
        matched_tags_map: dict[str, list[str]] = {}

        for a in available:
            score, matched = _compute_tag_score(task_keywords, a.tags)
            scores[a.agent_id] = score
            matched_tags_map[a.agent_id] = matched

        best_agent_id = max(scores, key=scores.get)  # type: ignore[arg-type]
        best_score = scores[best_agent_id]

        if best_score >= TAG_MATCH_MIN_SCORE:
            chosen = next(a for a in available if a.agent_id == best_agent_id)
            routing_info = RoutingInfo(
                strategy="tag_match",
                chosen_agent_id=chosen.agent_id,
                scores=scores,
                matched_tags=matched_tags_map[best_agent_id],
                fallback=False,
                reason=(
                    f"Tag match score {best_score:.3f} >= threshold {TAG_MATCH_MIN_SCORE}, "
                    f"matched: {matched_tags_map[best_agent_id]}"
                ),
            )
            return chosen, routing_info

        # Level 3: 回退到 least_load
        available.sort(key=lambda a: (a.current_load, a.last_health_check))
        chosen = available[0]
        routing_info = RoutingInfo(
            strategy="least_load",
            chosen_agent_id=chosen.agent_id,
            scores=scores,
            matched_tags=[],
            fallback=True,
            reason=(
                f"Tag match score {best_score:.3f} < threshold {TAG_MATCH_MIN_SCORE}, "
                f"fell back to least_load"
            ),
        )
        return chosen, routing_info
```

### 3.3 关键算法说明

**关键词提取**：
1. 文本转小写
2. 正则提取英文单词（2+ 字符）和 CJK 连续字符段
3. 过滤停用词（英+中）
4. 通过 `_TAG_ALIASES` 映射为标准化 tag（如 `python` -> `["python", "code"]`，`fix` -> `["debugging"]`）

**评分函数**：
- 使用 Jaccard 相似度：`score = |intersection| / |union|`
- 分母取 union（task_keywords 与 agent_tags 的并集），惩罚 agent 堆砌大量不相关 tag 的行为（union 膨胀导致分数下降），同时不会因为 agent tag 丰富而惩罚它
- 阈值 `TAG_MATCH_MIN_SCORE = 0.15`，即至少需要约 15% 的关键词命中才认为是有效匹配

**回退逻辑**：
- 最高分 < 0.15 时回退到 least_load（现有行为）
- required_tags 不满足时直接失败（不回退），因为这是调用方的明确要求
- least_load 排序保持现有逻辑：先按 `current_load` 升序，再按 `last_health_check` 升序

### 3.4 select() 签名变更的影响

`select()` 返回值从 `AgentProfile | None` 变为 `tuple[AgentProfile | None, RoutingInfo | None]`。所有调用点需更新。

唯一调用点在 `main.py` 的 `_process_task()` 函数，变更见第 5 节。

> **测试更新提醒**：所有已有的 `test_agent_selector.py` 测试用例（如存在）必须从
> `result = selector.select(...)` + `assert result is not None`
> 更新为
> `chosen, info = selector.select(...)` + `assert chosen is not None`。
> 返回类型不再是裸 `AgentProfile`。

---

## 4. Discovery Loop 改造

### 4.1 设计思路

现有的 `_pod_to_profile()` 方法只从 pod metadata 读取基本信息。Phase 1 需要：

1. 从 pod 所属 deployment 的 annotation 中读取 `hermes-agent.io/capabilities` 和 `hermes-agent.io/role`
2. 调用已有的 `discover_capabilities()` 获取 models/tool_ids 信息（现有代码已实现但从未调用）
3. 将 tags、role、models、tool_ids 合并到 AgentProfile 中

**为什么不直接从 pod annotation 读取**：pod 是 deployment 管理的，annotation 在 deployment 级别设置而非 pod 级别。pod 会继承 deployment 的 `spec.template.metadata.annotations`，但这些不是 pod 自身的 annotation。所以需要通过 deployment API 读取。

但实际上，更可靠的方式是在 pod 的 template metadata 上也设置 annotation（K8s 支持在 pod template 上设置 annotation，会传递到 pod 上）。如果运维在 `spec.template.metadata.annotations` 上设置，则可以从 pod 直接读取。

**最终选择**：从 pod annotation 读取，运维需要将 annotation 设置在 pod template 级别。

### 4.2 代码改动

`hermes_orchestrator/services/agent_discovery.py`

```python
from __future__ import annotations
import logging
import time
from typing import TYPE_CHECKING

from hermes_orchestrator.models.agent import AgentProfile, AgentCapability

if TYPE_CHECKING:
    from hermes_orchestrator.config import OrchestratorConfig

logger = logging.getLogger(__name__)

GATEWAY_LABEL = "app.kubernetes.io/component=gateway"
CAPABILITIES_ANNOTATION = "hermes-agent.io/capabilities"
ROLE_ANNOTATION = "hermes-agent.io/role"


class AgentDiscoveryService:
    def __init__(self, config: OrchestratorConfig):
        self._config = config
        self._api_key_cache: dict[str, str] = {}

    async def _load_k8s_client(self):
        from kubernetes_asyncio import client, config as k8s_config
        try:
            k8s_config.load_incluster_config()
        except Exception:
            await k8s_config.load_kube_config()
        return client

    def _extract_agent_name(self, pod) -> str:
        """Extract gateway deployment name from pod."""
        pod_name = pod.metadata.name
        parts = pod_name.rsplit("-", 2)
        if len(parts) >= 3:
            return "-".join(parts[:-2])
        return pod_name

    async def _get_api_key(self, agent_name: str) -> str:
        """Read API key from K8s secret for the given agent."""
        if agent_name in self._api_key_cache:
            return self._api_key_cache[agent_name]
        try:
            client = await self._load_k8s_client()
            api = client.CoreV1Api()
            secret_name = f"{agent_name}-secret"
            secret = await api.read_namespaced_secret(
                secret_name, self._config.k8s_namespace
            )
            import base64
            key = base64.b64decode(secret.data.get("api_key", "")).decode()
            await api.api_client.close()
            self._api_key_cache[agent_name] = key
            return key
        except Exception as e:
            logger.warning("Failed to read API key for %s: %s", agent_name, e)
            return self._config.gateway_api_key

    def _parse_tags_from_annotation(self, annotations: dict | None) -> list[str]:
        """从 pod annotation 解析 tag 列表。

        支持两种格式:
          - 逗号分隔: "code,python,debugging"
          - JSON 数组: '["code","python","debugging"]'
        """
        if not annotations:
            return []
        raw = annotations.get(CAPABILITIES_ANNOTATION, "")
        if not raw:
            return []
        raw = raw.strip()
        # 尝试 JSON 解析
        if raw.startswith("["):
            import json
            try:
                tags = json.loads(raw)
                if isinstance(tags, list):
                    return [str(t).strip().lower() for t in tags if str(t).strip()]
            except json.JSONDecodeError:
                pass
        # 逗号分隔回退
        return [t.strip().lower() for t in raw.split(",") if t.strip()]

    def _parse_role_from_annotation(self, annotations: dict | None) -> str:
        """从 pod annotation 解析 role。"""
        if not annotations:
            return "generalist"
        return annotations.get(ROLE_ANNOTATION, "generalist").strip().lower() or "generalist"

    async def discover_pods(self) -> list[AgentProfile]:
        client = await self._load_k8s_client()
        api = client.CoreV1Api()
        pods = await api.list_namespaced_pod(
            namespace=self._config.k8s_namespace,
            label_selector=GATEWAY_LABEL,
        )
        profiles = []
        for pod in pods.items:
            if pod.status.phase != "Running" or not pod.status.pod_ip:
                continue
            agent_name = self._extract_agent_name(pod)
            api_key = await self._get_api_key(agent_name)
            profile = self._pod_to_profile(pod)
            profile.api_key = api_key
            # Phase 1: 从 annotation 读取 tags 和 role
            annotations = pod.metadata.annotations or {}
            profile.tags = self._parse_tags_from_annotation(annotations)
            profile.role = self._parse_role_from_annotation(annotations)
            profiles.append(profile)
        await api.api_client.close()

        # Phase 1: 调用 discover_capabilities() 获取 models/tool_ids
        for profile in profiles:
            try:
                capabilities = await self.discover_capabilities(
                    profile.gateway_url,
                    headers=profile.gateway_headers(),
                )
                if capabilities:
                    profile.models = list({
                        c.model_id for c in capabilities
                    })
                    all_tool_ids: list[str] = []
                    for c in capabilities:
                        all_tool_ids.extend(c.tool_ids)
                    profile.tool_ids = sorted(set(all_tool_ids))
                    # 合并 capabilities dict
                    merged_caps: dict = {}
                    for c in capabilities:
                        merged_caps.update(c.capabilities)
                    profile.capabilities = merged_caps
                    logger.info(
                        "Discovered capabilities for %s: models=%s, tools=%d, tags=%s",
                        profile.agent_id, profile.models, len(profile.tool_ids),
                        profile.tags,
                    )
            except Exception as e:
                logger.warning(
                    "Capability discovery failed for %s: %s",
                    profile.agent_id, e,
                )

        return profiles

    async def discover_capabilities(
        self, gateway_url: str, headers: dict | None = None
    ) -> list[AgentCapability]:
        import aiohttp

        capabilities = []
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{gateway_url}/v1/models",
                    headers=headers or self._config.gateway_headers,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status != 200:
                        logger.warning(
                            "Failed to query %s/v1/models: %s",
                            gateway_url, resp.status,
                        )
                        return []
                    data = await resp.json()
                    for entry in data.get("data", []):
                        info = entry.get("info", {}) or {}
                        meta = info.get("meta", {}) or {}
                        capabilities.append(
                            AgentCapability(
                                gateway_url=gateway_url,
                                model_id=entry.get("id", ""),
                                capabilities=meta.get("capabilities", {}),
                                tool_ids=meta.get("toolIds", []),
                                supported_endpoints=entry.get(
                                    "supported_endpoints", []
                                ),
                            )
                        )
        except Exception as e:
            logger.warning(
                "Capability discovery failed for %s: %s", gateway_url, e
            )
        return capabilities

    def _build_pod_url(self, pod) -> str:
        return f"http://{pod.status.pod_ip}:{self._config.gateway_port}"

    def _pod_to_profile(self, pod) -> AgentProfile:
        return AgentProfile(
            agent_id=pod.metadata.name,
            gateway_url=self._build_pod_url(pod),
            registered_at=time.time(),
            max_concurrent=self._config.agent_max_concurrent,
            status="online",
        )
```

### 4.3 改动要点

1. `_parse_tags_from_annotation()` -- 支持 JSON 数组和逗号分隔两种格式，统一输出 `list[str]`（全小写）
2. `_parse_role_from_annotation()` -- 读取 `hermes-agent.io/role`，默认 `"generalist"`
3. `discover_pods()` -- 在遍历 pod 时读取 annotations 填充 `tags`/`role`；在返回前对每个 profile 调用 `discover_capabilities()` 获取 `models`/`tool_ids`/`capabilities`
4. capability 发现失败不影响 agent 注册（只 warn）

### 4.4 性能考量

`discover_capabilities()` 对每个 agent 发起一次 HTTP GET `/v1/models`，超时 10 秒。当前实现为串行循环，3 个 agent 最多 30 秒。**Phase 1 即应使用 `asyncio.gather` 并发**，避免 N+1 串行延迟：

```python
# 替换 4.2 中 discover_pods() 末尾的串行 for 循环：
async def _discover_all_capabilities(
    self, profiles: list[AgentProfile]
) -> None:
    """并发对所有 agent 调用 discover_capabilities()。"""
    async def _safe_discover(profile: AgentProfile) -> None:
        try:
            capabilities = await self.discover_capabilities(
                profile.gateway_url,
                headers=profile.gateway_headers(),
            )
            if capabilities:
                profile.models = list({c.model_id for c in capabilities})
                all_tool_ids: list[str] = []
                for c in capabilities:
                    all_tool_ids.extend(c.tool_ids)
                profile.tool_ids = sorted(set(all_tool_ids))
                merged_caps: dict = {}
                for c in capabilities:
                    merged_caps.update(c.capabilities)
                profile.capabilities = merged_caps
                logger.info(
                    "Discovered capabilities for %s: models=%s, tools=%d, tags=%s",
                    profile.agent_id, profile.models, len(profile.tool_ids),
                    profile.tags,
                )
        except Exception as e:
            logger.warning(
                "Capability discovery failed for %s: %s",
                profile.agent_id, e,
            )

    await asyncio.gather(*[_safe_discover(p) for p in profiles])
```

在 `discover_pods()` 中将串行 for 循环替换为 `await self._discover_all_capabilities(profiles)`。
`asyncio.gather` 保证所有 HTTP 请求并发发出，总耗时约等于单次超时（10 秒）而非 N × 10 秒。

---

## 5. API 变更

### 5.1 main.py 调用点改动

`_process_task()` 中调用 `selector.select()` 的部分需要适配新的返回值。

```python
# main.py _process_task() 改动（仅展示变更部分）

async def _process_task(task_id: str):
    loop = asyncio.get_event_loop()
    task = await loop.run_in_executor(None, task_store.get, task_id)
    if not task:
        return
    agents = await loop.run_in_executor(None, agent_registry.list_agents)
    chosen, routing_info = selector.select(agents, task)  # <-- 变更
    # 持久化 routing_info
    if routing_info:
        await loop.run_in_executor(
            None,
            partial(task_store.update, task_id, routing_info=routing_info),
        )
    if not chosen:
        await loop.run_in_executor(
            None,
            partial(
                task_store.update, task_id, status="failed",
                error="No available agent",
            ),
        )
        return
    await loop.run_in_executor(
        None,
        partial(
            task_store.update, task_id,
            status="assigned",
            assigned_agent=chosen.agent_id,
        ),
    )
    # ... 后续执行逻辑不变 ...
```

### 5.2 submit_task 端点改动

`main.py` 的 `submit_task()` 需要将 `required_tags` 传递给 Task。

```python
@app.post("/api/v1/tasks", status_code=202)
async def submit_task(req: TaskSubmitRequest, response: Response):
    task = Task(
        task_id=str(uuid.uuid4()),
        prompt=req.prompt,
        instructions=req.instructions,
        model_id=req.model_id,
        priority=req.priority,
        timeout_seconds=req.timeout_seconds,
        max_retries=req.max_retries,
        callback_url=req.callback_url,
        metadata=req.metadata,
        required_tags=req.required_tags,  # <-- 新增
        created_at=time.time(),
    )
    task_store.create(task)
    task_store.enqueue(task)
    response.headers["Retry-After"] = "5"
    return TaskSubmitResponse(task_id=task.task_id, created_at=task.created_at)
```

### 5.3 get_task 端点改动

返回 `routing_info`。

```python
@app.get("/api/v1/tasks/{task_id}")
async def get_task(task_id: str, response: Response):
    if not re.match(r'^[a-zA-Z0-9_-]+$', task_id):
        raise HTTPException(status_code=400, detail="Invalid task ID format")
    task = task_store.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    response.headers["Retry-After"] = "5"
    result_dict = None
    if task.result:
        result_dict = task.result.__dict__
    routing_info_dict = None
    if task.routing_info:
        routing_info_dict = task.routing_info.__dict__
    return TaskStatusResponse(
        task_id=task.task_id,
        status=task.status,
        assigned_agent=task.assigned_agent,
        run_id=task.run_id,
        result=result_dict,
        error=task.error,
        retry_count=task.retry_count,
        created_at=task.created_at,
        updated_at=task.updated_at,
        routing_info=routing_info_dict,  # <-- 新增
    )
```

### 5.4 RedisTaskStore.update 扩展

`redis_task_store.py` 的 `update()` 方法需要支持 `routing_info` 参数。

```python
def update(
    self,
    task_id: str,
    status: str | None = _UNSET,
    assigned_agent: str | None = _UNSET,
    run_id: str | None = _UNSET,
    result: TaskResult | None = _UNSET,
    error: str | None = _UNSET,
    retry_count: int | None = _UNSET,
    routing_info: RoutingInfo | None = _UNSET,  # <-- 新增
) -> None:
    task = self.get(task_id)
    if not task:
        logger.warning("Attempted to update nonexistent task %s", task_id)
        return
    if status is not _UNSET:
        task.status = status
    if assigned_agent is not _UNSET:
        task.assigned_agent = assigned_agent
    if run_id is not _UNSET:
        task.run_id = run_id
    if result is not _UNSET:
        task.result = result
    if error is not _UNSET:
        task.error = error
    if retry_count is not _UNSET:
        task.retry_count = retry_count
    if routing_info is not _UNSET:          # <-- 新增
        task.routing_info = routing_info
    task.updated_at = time.time()
    self._redis.hset(
        f"{TASK_PREFIX}{task.task_id}",
        "data",
        json.dumps(task.to_dict()),
    )
```

需要在文件顶部 import 中加入 `RoutingInfo`：

```python
from hermes_orchestrator.models.task import Task, TaskResult, RoutingInfo
```

### 5.5 路由信息返回格式示例

```json
{
  "task_id": "abc-123",
  "status": "assigned",
  "assigned_agent": "hermes-gateway-1",
  "routing_info": {
    "strategy": "tag_match",
    "chosen_agent_id": "hermes-gateway-1",
    "scores": {
      "hermes-gateway-1": 0.42,
      "hermes-gateway-2": 0.14,
      "hermes-gateway-3": 0.0
    },
    "matched_tags": ["python", "code", "debugging"],
    "fallback": false,
    "reason": "Tag match score 0.420 >= threshold 0.15, matched: ['code', 'debugging', 'python']",
    "shadow_smart_agent_id": null,
    "shadow_smart_score": null
  }
}
```

---

## 6. 前端变更

### 6.1 TaskSubmitPage 添加 tag 选择

在任务提交表单中新增 `required_tags` 多选组件。

```tsx
// admin/frontend/src/pages/TaskSubmitPage.tsx (示意)

const AVAILABLE_TAGS = [
  "code", "python", "javascript", "typescript", "golang", "rust", "java",
  "debugging", "analysis", "creative", "translation", "documentation",
  "search", "research", "devops", "testing", "code-review", "database",
  "api", "system-design",
];

function TaskSubmitPage() {
  const [requiredTags, setRequiredTags] = useState<string[]>([]);

  // ... existing form state ...

  const handleSubmit = async () => {
    const body = {
      prompt,
      instructions,
      model_id: selectedModel,
      priority,
      required_tags: requiredTags,  // <-- 新增
    };
    // ... submit logic ...
  };

  return (
    <form onSubmit={handleSubmit}>
      {/* ... existing fields ... */}

      {/* 新增: Required Tags 多选 */}
      <div className="field">
        <label>Required Tags (optional)</label>
        <TagSelector
          options={AVAILABLE_TAGS}
          selected={requiredTags}
          onChange={setRequiredTags}
          placeholder="Select capabilities the agent must have"
        />
        <p className="help-text">
          Only agents with ALL selected tags will be considered.
          Leave empty for automatic routing.
        </p>
      </div>

      <button type="submit">Submit Task</button>
    </form>
  );
}
```

### 6.2 TaskDetailPage 显示路由信息

在任务详情页新增 Routing Info 卡片。

```tsx
// admin/frontend/src/pages/TaskDetailPage.tsx (示意)

function RoutingInfoCard({ routingInfo }: { routingInfo: RoutingInfo | null }) {
  if (!routingInfo) return null;

  const strategyLabel: Record<string, string> = {
    tag_match: "Tag Match",
    least_load: "Least Load (Fallback)",
    required_tags: "Required Tags",
  };

  return (
    <div className="routing-info-card">
      <h3>Routing Decision</h3>
      <div className="info-grid">
        <div className="info-item">
          <span className="label">Strategy</span>
          <span className={`badge badge-${routingInfo.strategy}`}>
            {strategyLabel[routingInfo.strategy] || routingInfo.strategy}
          </span>
        </div>
        <div className="info-item">
          <span className="label">Fallback</span>
          <span>{routingInfo.fallback ? "Yes" : "No"}</span>
        </div>
        {routingInfo.matched_tags.length > 0 && (
          <div className="info-item">
            <span className="label">Matched Tags</span>
            <div className="tag-list">
              {routingInfo.matched_tags.map(tag => (
                <span key={tag} className="tag">{tag}</span>
              ))}
            </div>
          </div>
        )}
        <div className="info-item full-width">
          <span className="label">Reason</span>
          <p className="reason-text">{routingInfo.reason}</p>
        </div>
        {routingInfo.shadow_smart_agent_id && (
          <div className="info-item full-width shadow-audit">
            <span className="label">Shadow Mode Audit</span>
            <p>
              Smart routing would have chosen <strong>{routingInfo.shadow_smart_agent_id}</strong>
              {routingInfo.shadow_smart_score != null && (
                <> (score: {routingInfo.shadow_smart_score.toFixed(3)})</>
              )}
            </p>
          </div>
        )}
        {Object.keys(routingInfo.scores).length > 0 && (
          <div className="info-item full-width">
            <span className="label">Agent Scores</span>
            <div className="scores-bar-chart">
              {Object.entries(routingInfo.scores)
                .sort(([, a], [, b]) => b - a)
                .map(([agentId, score]) => (
                  <div key={agentId} className="score-row">
                    <span className="agent-name">{agentId}</span>
                    <div className="score-bar">
                      <div
                        className="score-fill"
                        style={{ width: `${Math.min(score * 100, 100)}%` }}
                      />
                    </div>
                    <span className="score-value">{score.toFixed(3)}</span>
                  </div>
                ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
```

### 6.3 AgentListPage 显示 tags

在 agent 列表中展示每个 agent 的 tags 和 role。

```tsx
// 在 agent 卡片/表格行中新增
<div className="agent-tags">
  <span className="role-badge">{agent.role}</span>
  {agent.tags.map(tag => (
    <span key={tag} className="tag">{tag}</span>
  ))}
</div>
```

---

## 7. K8s 部署变更

### 7.1 Gateway Deployment Annotation 示例

需要在 gateway deployment 的 pod template 中添加 annotations。

```yaml
# kubernetes/gateway-1-deployment.yaml (示意)

apiVersion: apps/v1
kind: Deployment
metadata:
  name: hermes-gateway-1
  namespace: hermes-agent
spec:
  selector:
    matchLabels:
      app.kubernetes.io/component: gateway
      app.kubernetes.io/instance: gateway-1
  template:
    metadata:
      labels:
        app.kubernetes.io/component: gateway
        app.kubernetes.io/instance: gateway-1
      annotations:
        # Phase 1 新增
        hermes-agent.io/capabilities: "code,python,debugging,testing"
        hermes-agent.io/role: "coder"
    spec:
      containers:
        - name: gateway
          # ... existing container spec ...
```

### 7.2 三个 Gateway 的推荐标签配置

```yaml
# gateway-1: 编程专家
hermes-agent.io/capabilities: "code,python,debugging,testing,code-review"
hermes-agent.io/role: "coder"

# gateway-2: 分析与研究
hermes-agent.io/capabilities: "analysis,research,documentation,search"
hermes-agent.io/role: "analyst"

# gateway-3: 通用助手
hermes-agent.io/capabilities: "creative,translation,api,system-design,general"
hermes-agent.io/role: "generalist"
```

### 7.3 热更新支持

修改 deployment annotation 后，K8s 会触发滚动更新，新的 pod 启动后 Discovery Loop 在下一个 30 秒周期内自动感知变更。无需重启 Orchestrator。

如果需要更快生效，也可以手动调用（Phase 2 可考虑）：
```bash
# 触发立即重新发现
curl -X POST http://orchestrator:8642/api/v1/agents/discover
```

Phase 1 不做主动触发端点，30 秒轮询足够。

---

## 8. 灰度上线方案

### 8.1 阶段划分

| 阶段 | 持续时间 | 路由行为 | 验证方式 |
|------|---------|---------|---------|
| 影子模式 | 3-5 天 | 新旧路由并行，仅记录不生效 | 对比日志，确认新路由不会选出离谱的 agent |
| 10% 灰度 | 3-5 天 | 10% 的 task 使用新路由 | 监控 task 成功率、耗时对比 |
| 50% 灰度 | 2-3 天 | 50% 的 task 使用新路由 | 同上 |
| 全量 | - | 所有 task 使用新路由 | - |

### 8.2 影子模式实现

在 `AgentSelector` 中增加影子模式开关。影子模式下，新路由算法执行并记录 `routing_info`，但实际选择仍使用 least_load。

```python
# config.py 新增
class OrchestratorConfig:
    # ... existing fields ...

    def __init__(self):
        # ... existing init ...
        self.routing_mode = os.environ.get("ROUTING_MODE", "shadow")
        # "shadow" | "canary" | "full"
        self.routing_canary_percent = int(
            os.environ.get("ROUTING_CANARY_PERCENT", "10")
        )
```

```python
# agent_selector.py select() 方法增加灰度逻辑

import random

class AgentSelector:
    def __init__(self, routing_mode: str = "full", canary_percent: int = 10):
        self._routing_mode = routing_mode
        self._canary_percent = canary_percent

    def select(
        self, agents: list[AgentProfile], task: Task
    ) -> tuple[AgentProfile | None, RoutingInfo | None]:
        # required_tags 是硬约束，不走灰度分支——直接由 _smart_select 处理
        if task.required_tags:
            return self._smart_select(agents, task)

        # 始终执行智能路由（生成 routing_info）
        smart_agent, routing_info = self._smart_select(agents, task)

        if self._routing_mode == "shadow":
            # 影子模式：记录智能路由结果，但使用 least_load
            actual_agent = self._least_load_select(agents)
            if routing_info:
                smart_score = routing_info.scores.get(
                    smart_agent.agent_id, 0.0
                ) if smart_agent else None
                routing_info.shadow_smart_agent_id = (
                    smart_agent.agent_id if smart_agent else None
                )
                routing_info.shadow_smart_score = smart_score
                # chosen_agent_id 反映实际（least_load）选择，不覆盖
                routing_info.chosen_agent_id = (
                    actual_agent.agent_id if actual_agent else None
                )
                routing_info.fallback = True
                routing_info.reason = (
                    f"[SHADOW] Smart would choose {smart_agent.agent_id if smart_agent else 'None'} "
                    f"(score={smart_score:.3f}), "
                    f"actual using least_load: {actual_agent.agent_id if actual_agent else 'None'}"
                )
                routing_info.strategy = "shadow"
            return actual_agent, routing_info

        if self._routing_mode == "canary":
            # 灰度模式：按百分比分流
            roll = random.random() * 100
            if roll < self._canary_percent:
                if routing_info:
                    routing_info.reason = (
                        f"[CANARY {self._canary_percent}%] "
                        f"Using smart routing: {routing_info.reason}"
                    )
                return smart_agent, routing_info
            else:
                actual_agent = self._least_load_select(agents)
                if routing_info:
                    routing_info.chosen_agent_id = (
                        actual_agent.agent_id if actual_agent else None
                    )
                    routing_info.strategy = "least_load"
                    routing_info.fallback = True
                    routing_info.reason = (
                        f"[CANARY] Fell back to least_load (roll={roll:.1f}%)"
                    )
                return actual_agent, routing_info

        # full 模式：直接使用智能路由
        return smart_agent, routing_info

    def _least_load_select(
        self, agents: list[AgentProfile]
    ) -> AgentProfile | None:
        """原有的最少负载选择逻辑。"""
        candidates = [
            a for a in agents
            if a.status in ("online", "degraded")
            and a.current_load < a.max_concurrent
            and a.circuit_state != "open"
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda a: (a.current_load, a.last_health_check))
        return candidates[0]

    def _smart_select(
        self, agents: list[AgentProfile], task: Task
    ) -> tuple[AgentProfile | None, RoutingInfo | None]:
        """完整的智能路由逻辑（不含灰度包装）。

        即第 3.2 节中 select() 的主体逻辑。灰度模式调用此方法
        获取智能路由决策，再根据 shadow/canary 策略决定是否采纳。
        required_tags 约束在此方法内处理，**完全绕过** shadow/canary
        包装——如果 task 带有 required_tags，select() 直接返回
        _smart_select 的结果，不走灰度分支。
        """
        # 过滤不可用的 agent
        available = [
            a for a in agents
            if a.status in ("online", "degraded")
            and a.current_load < a.max_concurrent
            and a.circuit_state != "open"
        ]
        if not available:
            logger.warning(
                "No available agent for task %s (checked %d agents)",
                task.task_id, len(agents),
            )
            return None, None

        # Level 1: required_tags 硬约束
        if task.required_tags:
            required_set = {t.lower() for t in task.required_tags}
            candidates = [
                a for a in available
                if required_set.issubset({t.lower() for t in a.tags})
            ]
            if not candidates:
                logger.warning(
                    "Task %s required_tags %s not satisfied by any agent",
                    task.task_id, task.required_tags,
                )
                routing_info = RoutingInfo(
                    strategy="required_tags",
                    chosen_agent_id=None,
                    scores={},
                    matched_tags=[],
                    fallback=False,
                    reason=f"No agent satisfies required_tags: {task.required_tags}",
                )
                return None, routing_info
            candidates.sort(key=lambda a: (a.current_load, a.last_health_check))
            chosen = candidates[0]
            routing_info = RoutingInfo(
                strategy="required_tags",
                chosen_agent_id=chosen.agent_id,
                scores={c.agent_id: 1.0 for c in candidates},
                matched_tags=sorted(required_set),
                fallback=False,
                reason=f"Required tags matched, selected least-loaded: {chosen.agent_id}",
            )
            return chosen, routing_info

        # Level 2: tag_match 评分
        source_text = f"{task.prompt} {task.instructions}"
        task_keywords = _extract_keywords(source_text)
        scores: dict[str, float] = {}
        matched_tags_map: dict[str, list[str]] = {}

        for a in available:
            score, matched = _compute_tag_score(task_keywords, a.tags)
            scores[a.agent_id] = score
            matched_tags_map[a.agent_id] = matched

        best_agent_id = max(scores, key=scores.get)  # type: ignore[arg-type]
        best_score = scores[best_agent_id]

        if best_score >= TAG_MATCH_MIN_SCORE:
            chosen = next(a for a in available if a.agent_id == best_agent_id)
            routing_info = RoutingInfo(
                strategy="tag_match",
                chosen_agent_id=chosen.agent_id,
                scores=scores,
                matched_tags=matched_tags_map[best_agent_id],
                fallback=False,
                reason=(
                    f"Tag match score {best_score:.3f} >= threshold {TAG_MATCH_MIN_SCORE}, "
                    f"matched: {matched_tags_map[best_agent_id]}"
                ),
            )
            return chosen, routing_info

        # Level 3: 回退到 least_load
        available.sort(key=lambda a: (a.current_load, a.last_health_check))
        chosen = available[0]
        routing_info = RoutingInfo(
            strategy="least_load",
            chosen_agent_id=chosen.agent_id,
            scores=scores,
            matched_tags=[],
            fallback=True,
            reason=(
                f"Tag match score {best_score:.3f} < threshold {TAG_MATCH_MIN_SCORE}, "
                f"fell back to least_load"
            ),
        )
        return chosen, routing_info
```

### 8.3 main.py 适配

```python
# lifespan() 中初始化 selector 时传入配置
selector = AgentSelector(
    routing_mode=config.routing_mode,
    canary_percent=config.routing_canary_percent,
)
```

### 8.4 影子模式验证脚本

```bash
# 对比影子模式日志中的 routing_info
# 在 k8s 环境中执行：
kubectl logs -n hermes-agent deployment/hermes-orchestrator | grep "\[SHADOW\]" | tail -100

# 统计智能路由与 least_load 的一致率（从 routing_info 的 JSON 字段读取）
# routing_info.shadow_smart_agent_id 为智能路由选择的 agent
# routing_info.chosen_agent_id 为 least_load 实际选择的 agent
grep "\[SHADOW\]" orchestrator.log | \
  python3 -c "
import sys, json, re
total = 0
same = 0
for line in sys.stdin:
    # 尝试从日志行中提取 routing_info JSON
    m = re.search(r'routing_info[\":\s]+(\{.*\})', line)
    if not m:
        # 回退：从 reason 文本中提取
        m2 = re.search(r'Smart would choose (\S+).*actual using least_load: (\S+)', line)
        if m2:
            total += 1
            if m2.group(1).rstrip(',').rstrip(')') == m2.group(2):
                same += 1
        continue
    try:
        info = json.loads(m.group(1))
        smart = info.get('shadow_smart_agent_id')
        actual = info.get('chosen_agent_id')
        if smart and actual:
            total += 1
            if smart == actual:
                same += 1
    except json.JSONDecodeError:
        pass
if total:
    print(f'Consistency: {same}/{total} = {same/total*100:.1f}%')
else:
    print('No shadow routing entries found')
"
```

### 8.5 灰度切换操作

```bash
# 影子模式（默认）
kubectl set env deployment/hermes-orchestrator ROUTING_MODE=shadow -n hermes-agent

# 10% 灰度
kubectl set env deployment/hermes-orchestrator ROUTING_MODE=canary ROUTING_CANARY_PERCENT=10 -n hermes-agent

# 50% 灰度
kubectl set env deployment/hermes-orchestrator ROUTING_CANARY_PERCENT=50 -n hermes-agent

# 全量
kubectl set env deployment/hermes-orchestrator ROUTING_MODE=full -n hermes-agent
```

---

## 9. 测试计划

### 9.1 单元测试

文件位置：`tests/orchestrator/test_agent_selector.py`

```python
"""AgentSelector 智能路由单元测试。"""
import time
import pytest

from hermes_orchestrator.models.agent import AgentProfile
from hermes_orchestrator.models.task import Task
from hermes_orchestrator.services.agent_selector import (
    AgentSelector,
    _extract_keywords,
    _compute_tag_score,
    TAG_MATCH_MIN_SCORE,
)


def _make_agent(
    agent_id: str = "gw-1",
    tags: list[str] | None = None,
    role: str = "generalist",
    current_load: int = 0,
    status: str = "online",
    circuit_state: str = "closed",
) -> AgentProfile:
    return AgentProfile(
        agent_id=agent_id,
        gateway_url=f"http://10.0.0.{agent_id.split('-')[-1]}:8642",
        registered_at=time.time(),
        tags=tags or [],
        role=role,
        current_load=current_load,
        status=status,
        circuit_state=circuit_state,
    )


def _make_task(
    task_id: str = "t1",
    prompt: str = "hello",
    required_tags: list[str] | None = None,
    instructions: str = "",
) -> Task:
    return Task(
        task_id=task_id,
        prompt=prompt,
        created_at=time.time(),
        required_tags=required_tags or [],
        instructions=instructions,
    )


# --- 关键词提取测试 ---

class TestExtractKeywords:
    def test_english_code_task(self):
        kw = _extract_keywords("Write a Python function to sort a list")
        assert "python" in kw
        assert "code" in kw  # 通过 _TAG_ALIASES: python -> [python, code]

    def test_debugging_task(self):
        kw = _extract_keywords("Fix the bug in my JavaScript code")
        assert "debugging" in kw  # fix -> debugging, bug -> debugging
        assert "javascript" in kw
        assert "code" in kw

    def test_chinese_task(self):
        kw = _extract_keywords("帮我写一段 Python 代码")
        assert "python" in kw
        assert "code" in kw

    def test_mixed_language(self):
        kw = _extract_keywords("Debug this TypeScript API endpoint / 调试这个接口")
        assert "debugging" in kw
        assert "typescript" in kw
        assert "api" in kw

    def test_stop_words_filtered(self):
        kw = _extract_keywords("I want to make a program that can do things")
        assert "want" not in kw
        assert "make" not in kw
        # "program" 通过别名映射到 ["code"]
        assert "code" in kw

    def test_empty_text(self):
        assert _extract_keywords("") == set()

    def test_no_meaningful_words(self):
        kw = _extract_keywords("the a an is are")
        assert kw == set()


# --- 评分函数测试 ---

class TestComputeTagScore:
    def test_perfect_match(self):
        score, matched = _compute_tag_score(
            {"python", "code"}, ["python", "code", "debugging"]
        )
        assert score > 0
        assert "python" in matched
        assert "code" in matched

    def test_no_match(self):
        score, matched = _compute_tag_score(
            {"creative", "writing"}, ["python", "code", "debugging"]
        )
        assert score == 0.0
        assert matched == []

    def test_partial_match(self):
        score, matched = _compute_tag_score(
            {"python", "creative"}, ["python", "code"]
        )
        assert score > 0
        assert "python" in matched
        assert "creative" not in matched

    def test_empty_task_tags(self):
        score, matched = _compute_tag_score(set(), ["python"])
        assert score == 0.0

    def test_empty_agent_tags(self):
        score, matched = _compute_tag_score({"python"}, [])
        assert score == 0.0

    def test_case_insensitive(self):
        score, matched = _compute_tag_score(
            {"Python"}, ["python", "code"]
        )
        # _extract_keywords 已经 lower，但直接调用时也应兼容
        assert score > 0


# --- AgentSelector.select 测试 ---

class TestAgentSelector:
    def test_least_load_fallback_when_no_tag_match(self):
        """没有任何 tag 匹配时回退到 least_load。"""
        selector = AgentSelector(routing_mode="full")
        agents = [
            _make_agent("gw-1", tags=["creative"], current_load=3),
            _make_agent("gw-2", tags=["analysis"], current_load=1),
            _make_agent("gw-3", tags=["translation"], current_load=0),
        ]
        task = _make_task(prompt="Random question about weather")
        chosen, info = selector.select(agents, task)
        assert chosen is not None
        assert chosen.agent_id == "gw-3"  # least load
        assert info is not None
        assert info.fallback is True
        assert info.strategy == "least_load"

    def test_tag_match_selects_best(self):
        """tag 匹配时选择分数最高的 agent。"""
        selector = AgentSelector(routing_mode="full")
        agents = [
            _make_agent("gw-1", tags=["code", "python", "debugging"]),
            _make_agent("gw-2", tags=["analysis", "research"]),
            _make_agent("gw-3", tags=["creative", "translation"]),
        ]
        task = _make_task(prompt="Write a Python function to parse CSV files")
        chosen, info = selector.select(agents, task)
        assert chosen is not None
        assert chosen.agent_id == "gw-1"
        assert info is not None
        assert info.strategy == "tag_match"
        assert info.fallback is False
        assert "python" in info.matched_tags

    def test_required_tags_enforced(self):
        """required_tags 硬约束只选满足条件的 agent。"""
        selector = AgentSelector(routing_mode="full")
        agents = [
            _make_agent("gw-1", tags=["code", "python"]),
            _make_agent("gw-2", tags=["analysis"]),
        ]
        task = _make_task(
            prompt="Any prompt",
            required_tags=["python"],
        )
        chosen, info = selector.select(agents, task)
        assert chosen is not None
        assert chosen.agent_id == "gw-1"
        assert info is not None
        assert info.strategy == "required_tags"

    def test_required_tags_no_match_returns_none(self):
        """required_tags 无 agent 满足时返回 None。"""
        selector = AgentSelector(routing_mode="full")
        agents = [
            _make_agent("gw-1", tags=["code"]),
            _make_agent("gw-2", tags=["analysis"]),
        ]
        task = _make_task(
            prompt="Any prompt",
            required_tags=["rust", "debugging"],
        )
        chosen, info = selector.select(agents, task)
        assert chosen is None
        assert info is not None
        assert info.strategy == "required_tags"

    def test_excludes_offline_agents(self):
        """排除 offline/degraded/open circuit 的 agent。"""
        selector = AgentSelector(routing_mode="full")
        agents = [
            _make_agent("gw-1", tags=["code"], status="offline"),
            _make_agent("gw-2", tags=["code"], circuit_state="open"),
            _make_agent("gw-3", tags=["code"], current_load=999, max_concurrent=10),
        ]
        task = _make_task(prompt="Write code")
        chosen, info = selector.select(agents, task)
        assert chosen is None

    def test_no_available_agents(self):
        """无可用 agent 时返回 None。"""
        selector = AgentSelector(routing_mode="full")
        task = _make_task(prompt="test")
        chosen, info = selector.select([], task)
        assert chosen is None
        assert info is None

    def test_required_tags_among_candidates_least_load(self):
        """多个 agent 满足 required_tags 时选 least load。"""
        selector = AgentSelector(routing_mode="full")
        agents = [
            _make_agent("gw-1", tags=["code", "python"], current_load=5),
            _make_agent("gw-2", tags=["code", "python"], current_load=2),
            _make_agent("gw-3", tags=["analysis"], current_load=0),
        ]
        task = _make_task(prompt="test", required_tags=["python"])
        chosen, info = selector.select(agents, task)
        assert chosen is not None
        assert chosen.agent_id == "gw-2"
        assert info is not None
        assert info.strategy == "required_tags"


# --- 灰度模式测试 ---

class TestAgentSelectorShadowMode:
    def test_shadow_mode_uses_least_load(self):
        """影子模式下实际使用 least_load，但记录智能路由结果。"""
        selector = AgentSelector(routing_mode="shadow")
        agents = [
            _make_agent("gw-1", tags=["code", "python"], current_load=5),
            _make_agent("gw-2", tags=["creative"], current_load=0),
        ]
        task = _make_task(prompt="Write a Python script")
        chosen, info = selector.select(agents, task)
        assert chosen is not None
        assert info is not None
        assert info.strategy == "shadow"
        # gw-2 负载最低，影子模式应选它
        assert chosen.agent_id == "gw-2"
        # 智能路由会选择 gw-1（tag 匹配 code+python），审计字段应记录
        assert info.shadow_smart_agent_id == "gw-1"
        assert info.shadow_smart_score is not None
        assert info.shadow_smart_score > 0


class TestAgentSelectorCanaryMode:
    def test_canary_mode_respects_percentage(self):
        """灰度模式按百分比分配。"""
        # 使用 canary_percent=100 测试全量智能路由
        selector = AgentSelector(routing_mode="canary", canary_percent=100)
        agents = [
            _make_agent("gw-1", tags=["code", "python"]),
            _make_agent("gw-2", tags=["creative"]),
        ]
        task = _make_task(prompt="Write a Python script")
        chosen, info = selector.select(agents, task)
        assert chosen is not None
        assert info is not None
        assert "CANARY" in info.reason
        assert chosen.agent_id == "gw-1"

    def test_canary_mode_zero_percent_uses_least_load(self):
        """canary_percent=0 时全部走 least_load。"""
        selector = AgentSelector(routing_mode="canary", canary_percent=0)
        agents = [
            _make_agent("gw-1", tags=["code", "python"], current_load=5),
            _make_agent("gw-2", tags=["creative"], current_load=0),
        ]
        task = _make_task(prompt="Write a Python script")
        chosen, info = selector.select(agents, task)
        assert chosen is not None
        assert info is not None
        assert info.strategy == "least_load"
```

### 9.2 关键词提取与 Discovery 集成测试

文件位置：`tests/orchestrator/test_discovery_annotations.py`

```python
"""Annotation 解析与 Discovery 集成测试。"""
import pytest

from hermes_orchestrator.services.agent_discovery import AgentDiscoveryService


class TestParseTagsFromAnnotation:
    """测试 _parse_tags_from_annotation 方法。"""

    @pytest.fixture
    def discovery(self):
        from hermes_orchestrator.config import OrchestratorConfig
        # OrchestratorConfig.__init__ 会读环境变量 ORCHESTRATOR_API_KEY
        # 测试环境中可能没有，所以 mock
        import os
        os.environ.setdefault("ORCHESTRATOR_API_KEY", "test-key-for-discovery-test")
        config = OrchestratorConfig()
        return AgentDiscoveryService(config)

    def test_comma_separated(self, discovery):
        result = discovery._parse_tags_from_annotation({
            "hermes-agent.io/capabilities": "code,python,debugging"
        })
        assert result == ["code", "python", "debugging"]

    def test_json_array(self, discovery):
        result = discovery._parse_tags_from_annotation({
            'hermes-agent.io/capabilities': '["code","python","debugging"]'
        })
        assert result == ["code", "python", "debugging"]

    def test_empty_annotation(self, discovery):
        assert discovery._parse_tags_from_annotation({}) == []
        assert discovery._parse_tags_from_annotation(None) == []

    def test_whitespace_handling(self, discovery):
        result = discovery._parse_tags_from_annotation({
            "hermes-agent.io/capabilities": " code , python , debugging "
        })
        assert result == ["code", "python", "debugging"]

    def test_uppercase_normalized(self, discovery):
        result = discovery._parse_tags_from_annotation({
            "hermes-agent.io/capabilities": "Code,Python,DEBUGGING"
        })
        assert result == ["code", "python", "debugging"]


class TestParseRoleFromAnnotation:
    @pytest.fixture
    def discovery(self):
        import os
        os.environ.setdefault("ORCHESTRATOR_API_KEY", "test-key-for-role-test")
        from hermes_orchestrator.config import OrchestratorConfig
        config = OrchestratorConfig()
        return AgentDiscoveryService(config)

    def test_explicit_role(self, discovery):
        result = discovery._parse_role_from_annotation({
            "hermes-agent.io/role": "coder"
        })
        assert result == "coder"

    def test_default_role(self, discovery):
        assert discovery._parse_role_from_annotation({}) == "generalist"
        assert discovery._parse_role_from_annotation(None) == "generalist"

    def test_role_case_normalized(self, discovery):
        result = discovery._parse_role_from_annotation({
            "hermes-agent.io/role": "CODER"
        })
        assert result == "coder"
```

### 9.3 集成测试场景

| 场景 | 描述 | 预期结果 |
|------|------|---------|
| 纯 least_load | 所有 agent tags 为空，提交无 required_tags 的 task | 走 least_load 回退 |
| tag 精确命中 | 3 个 agent 分别有不同 tags，提交含明确关键词的 task | 选到 tag 最匹配的 agent |
| required_tags 过滤 | 2 个 agent，1 个有 python tag，required_tags=["python"] | 只选有 python 的 agent |
| required_tags 失败 | 无 agent 有 required_tags | task 标记 failed，routing_info 记录原因 |
| 影子模式 | 设置 ROUTING_MODE=shadow | 实际走 least_load，routing_info.strategy="shadow"，shadow_smart_agent_id/shadow_smart_score 记录智能路由决策 |
| 灰度切换 | ROUTING_MODE=canary, PERCENT=50 | 约 50% task 走智能路由 |
| annotation 更新 | 修改 deployment annotation | 30 秒后 discovery loop 感知，agent tags 更新 |
| 并发任务 | 同时提交 10 个相同 task | 每个都正确路由，routing_info 独立 |
| agent 离线 | tag 最匹配的 agent offline | 回退到次优 agent 或 least_load |

### 9.4 E2E 测试流程

```bash
# 1. 确保 Redis 可用
# 2. 启动 Orchestrator（ROUTING_MODE=full）
# 3. 提交带 required_tags 的 task
curl -X POST http://localhost:8642/api/v1/tasks \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Write a Python function to calculate fibonacci",
    "required_tags": ["python"]
  }'

# 4. 查询 task 状态，验证 routing_info
curl http://localhost:8642/api/v1/tasks/{task_id} \
  -H "Authorization: Bearer $API_KEY"
# 验证 response.routing_info.strategy == "required_tags"
# 验证 response.routing_info.matched_tags 包含 "python"
```

---

## 10. 风险与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| 关键词提取不准导致错误路由 | 中 | 中 | 影子模式先验证，回退阈值保守（0.15），低分自动回退 least_load |
| `_TAG_ALIASES` 维护成本 | 低 | 低 | 初期手动维护，Phase 2 考虑从 agent 历史任务自动学习 |
| `discover_capabilities()` 延迟增加 discovery 周期 | 低 | 低 | 3 个 agent 串行约 3 秒，30 秒周期内可接受；超时不影响注册 |
| `required_tags` 拼写错误 | 中 | 低 | 前端提供预定义 tag 列表，减少自由输入 |
| 灰度切换时 random 不均匀 | 低 | 低 | 使用 task_id hash 做分桶（而非 random），保证相同 task_id 总是走同一路径 |
| Redis 中旧 Task 数据无新字段 | 低 | 无 | from_dict 使用 `__dataclass_fields__` 过滤，新字段取默认值 |

---

## 附录 A：变更文件清单

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `hermes_orchestrator/models/agent.py` | 修改 | AgentProfile 新增 tags, role 字段 |
| `hermes_orchestrator/models/task.py` | 修改 | 新增 RoutingInfo dataclass；Task 新增 required_tags, routing_info |
| `hermes_orchestrator/models/api.py` | 修改 | TaskSubmitRequest 新增 required_tags；TaskStatusResponse 新增 routing_info |
| `hermes_orchestrator/services/agent_selector.py` | 重写 | 完整的智能路由逻辑 + 灰度模式 |
| `hermes_orchestrator/services/agent_discovery.py` | 修改 | 从 annotation 读取 tags/role，调用 discover_capabilities |
| `hermes_orchestrator/stores/redis_task_store.py` | 修改 | update() 新增 routing_info 参数 |
| `hermes_orchestrator/config.py` | 修改 | 新增 routing_mode, routing_canary_percent 配置 |
| `hermes_orchestrator/main.py` | 修改 | select() 调用适配，routing_info 持久化 |
| `tests/orchestrator/test_agent_selector.py` | 新增 | Selector 单元测试 |
| `tests/orchestrator/test_discovery_annotations.py` | 新增 | Annotation 解析测试 |
| K8s deployment YAML (x3) | 修改 | 添加 annotations |

## 附录 B：配置环境变量

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `ROUTING_MODE` | `shadow` | 路由模式：shadow / canary / full |
| `ROUTING_CANARY_PERCENT` | `10` | 灰度百分比（仅 canary 模式生效） |

## 附录 C：Phase 2 展望

- **Embedding 向量匹配**：用 sentence-transformer 将 prompt 编码为向量，与 agent 历史任务的 embedding 做余弦相似度匹配
- **历史命中率反馈**：记录每次路由的 task 是否成功，动态调整 agent 的 tag 权重
- **主动发现端点**：`POST /api/v1/agents/discover` 立即触发重新发现
- **Agent 标签自动学习**：根据 agent 历史执行的 task 类型自动推断 tags
- **多 Agent 协作**：复杂任务拆分给多个 agent 并行执行