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
    models: list[str] = field(default_factory=list)
    capabilities: dict = field(default_factory=dict)
    tool_ids: list[str] = field(default_factory=list)
    status: str = "online"  # online | degraded | offline
    current_load: int = 0
    max_concurrent: int = 10
    last_health_check: float = 0.0
    circuit_state: str = "closed"  # closed | open | half_open

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> AgentProfile:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
