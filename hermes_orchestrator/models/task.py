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
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
