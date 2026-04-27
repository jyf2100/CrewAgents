from typing import Literal

from pydantic import BaseModel, Field, model_validator


class SwarmCapabilityResponse(BaseModel):
    enabled: bool


class SwarmAgentProfile(BaseModel):
    agent_id: int
    display_name: str
    capabilities: list[str]
    status: str  # "online" | "offline" | "busy"
    current_tasks: int
    max_concurrent_tasks: int
    last_heartbeat: float
    model: str = ""


class RedisHealthResponse(BaseModel):
    connected: bool
    latency_ms: float = -1.0
    memory_used_percent: float = 0.0
    connected_clients: int = 0
    uptime_seconds: int = 0
    aof_enabled: bool = False
    version: str = ""


class StreamInfo(BaseModel):
    stream_name: str
    length: int
    pending_count: int


class SwarmMetricsResponse(BaseModel):
    timestamp: float
    swarm_enabled: bool
    agents: list[SwarmAgentProfile]
    agents_online: int
    agents_offline: int
    agents_busy: int
    queues: dict
    redis_health: RedisHealthResponse
    tasks_submitted_last_5m: int = 0
    tasks_completed_last_5m: int = 0
    tasks_failed_last_5m: int = 0


class SSETokenResponse(BaseModel):
    token: str
    expires_in: int

# --- Crew models ---


class CrewAgentModel(BaseModel):
    agent_id: int
    required_capability: str


class WorkflowStepModel(BaseModel):
    id: str = Field(..., min_length=1, max_length=64)
    required_capability: str = Field(..., min_length=1, max_length=128)
    task_template: str = Field("", max_length=10000)
    depends_on: list[str] = Field(default_factory=list)
    input_from: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: int = Field(120, ge=10, le=600)


class WorkflowDefModel(BaseModel):
    type: Literal["sequential", "parallel", "dag"]
    steps: list[WorkflowStepModel] = Field(..., min_length=1)
    timeout_seconds: int = Field(300, ge=30, le=3600)

    @model_validator(mode="after")
    def validate_step_deps(self) -> "WorkflowDefModel":
        step_ids = {s.id for s in self.steps}
        step_ids_list = [s.id for s in self.steps]
        if len(step_ids_list) != len(set(step_ids_list)):
            dupes = {sid for sid in step_ids_list if step_ids_list.count(sid) > 1}
            raise ValueError(f"Duplicate step IDs: {dupes}")
        for step in self.steps:
            for dep in step.depends_on:
                if dep not in step_ids:
                    raise ValueError(
                        f"Step '{step.id}' depends_on '{dep}' not found in step list"
                    )
        return self


class CrewCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    description: str = Field("", max_length=1024)
    agents: list[CrewAgentModel] = Field(default_factory=list)
    workflow: WorkflowDefModel
    created_by: str = Field("admin", max_length=64)


class CrewUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    agents: list[CrewAgentModel] | None = None
    workflow: WorkflowDefModel | None = None


class CrewResponse(BaseModel):
    crew_id: str
    name: str
    description: str = ""
    agents: list[CrewAgentModel] = []
    workflow: WorkflowDefModel
    created_at: float
    updated_at: float
    created_by: str = ""


class CrewExecutionResponse(BaseModel):
    exec_id: str
    crew_id: str
    status: str
    step_results: dict = {}
    error: str | None = None
    started_at: float
    finished_at: float | None = None
    timeout_seconds: int = 300


class CrewListResponse(BaseModel):
    results: list[CrewResponse]
    total: int
