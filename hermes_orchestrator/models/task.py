from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)


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
    strategy: str  # "tag_match" | "least_load" | "required_tags" | "shadow" | domain routing strategies
    chosen_agent_id: str | None
    scores: dict[str, float]  # agent_id -> match score
    matched_tags: list[str]
    fallback: bool
    reason: str
    shadow_smart_agent_id: str | None = None
    shadow_smart_score: float | None = None
    requeue: bool = False  # When True, task should be re-queued instead of marked failed


@dataclass
class Task:
    task_id: str
    prompt: str
    created_at: float
    instructions: str = ""
    model_id: str = "hermes-agent"
    status: str = "submitted"  # submitted|queued|assigned|executing|streaming|done|failed
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
    required_tags: list[str] = field(default_factory=list)
    domain: str = "generalist"
    preferred_tags: list[str] = field(default_factory=list)  # Soft-constraint tags merged into Jaccard scoring
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
        ri_data = data.get("routing_info")
        if ri_data is not None:
            try:
                routing_info = RoutingInfo(**ri_data)
            except (TypeError, ValueError) as exc:
                logger.warning(
                    "Failed to deserialize routing_info for task %s: %s",
                    data.get("task_id", "?"), exc,
                )
                routing_info = None
        data["routing_info"] = routing_info
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
