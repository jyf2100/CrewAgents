from pydantic import BaseModel


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
