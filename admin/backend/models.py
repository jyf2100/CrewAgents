from __future__ import annotations
import datetime
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field, field_validator


# Enums
class AgentStatus(str, Enum):
    running = "running"
    stopped = "stopped"
    pending = "pending"
    updating = "updating"
    scaling = "scaling"
    failed = "failed"
    unknown = "unknown"


class LLMProvider(str, Enum):
    openrouter = "openrouter"
    anthropic = "anthropic"
    openai = "openai"
    gemini = "gemini"
    zai = "zai"
    custom = "custom"


class EventType(str, Enum):
    normal = "Normal"
    warning = "Warning"


# Shared/Nested models
class ResourceUsage(BaseModel):
    cpu_cores: Optional[float] = Field(None, description="CPU usage in cores")
    cpu_request_millicores: Optional[int] = None
    cpu_limit_millicores: Optional[int] = None
    memory_bytes: Optional[int] = Field(None, description="Memory usage in bytes")
    memory_request_bytes: Optional[int] = None
    memory_limit_bytes: Optional[int] = None


class ContainerStatus(BaseModel):
    ready: bool = False
    restart_count: int = 0
    state: str = "waiting"
    reason: Optional[str] = None
    image: str = ""


class PodInfo(BaseModel):
    name: str
    phase: str
    pod_ip: Optional[str] = None
    node_name: Optional[str] = None
    started_at: Optional[datetime.datetime] = None
    containers: list[ContainerStatus] = []


class EnvVariable(BaseModel):
    key: str
    value: str = ""
    masked: bool = False
    is_secret: bool = False


class ConfigYaml(BaseModel):
    content: str


class SoulMarkdown(BaseModel):
    content: str


# Agent List/Summary
class AgentSummary(BaseModel):
    id: int = Field(..., description="Agent number N")
    name: str = Field(..., description="Deployment name, e.g. hermes-gateway-4")
    status: AgentStatus
    url_path: str = Field("", description="Ingress path, e.g. /agent4")
    resources: ResourceUsage = Field(default_factory=ResourceUsage)
    restart_count: int = 0
    created_at: Optional[datetime.datetime] = None
    age_human: str = ""
    health_ok: Optional[bool] = None


class AgentListResponse(BaseModel):
    agents: list[AgentSummary]
    total: int


# Agent Detail
class AgentDetailResponse(BaseModel):
    id: int
    name: str
    status: AgentStatus
    url_path: str
    namespace: str = "hermes-agent"
    labels: dict[str, str] = {}
    created_at: Optional[datetime.datetime] = None
    pods: list[PodInfo] = []
    resources: ResourceUsage = Field(default_factory=ResourceUsage)
    health_ok: Optional[bool] = None
    health_last_check: Optional[datetime.datetime] = None
    ingress_path: Optional[str] = None
    restart_count: int = 0
    age_human: str = ""


# Create Agent
class ResourceSpec(BaseModel):
    cpu_request: str = "250m"
    cpu_limit: str = "1000m"
    memory_request: str = "512Mi"
    memory_limit: str = "1Gi"


class LLMConfig(BaseModel):
    provider: LLMProvider = LLMProvider.openrouter
    api_key: str = Field(..., min_length=1)
    model: str = "anthropic/claude-sonnet-4-20250514"
    base_url: Optional[str] = None

    @field_validator("base_url", mode="before")
    @classmethod
    def _fill_default_url(cls, v, info):
        if v:
            return v
        provider = info.data.get("provider")
        defaults = {
            "openrouter": "https://openrouter.ai/api/v1",
            "anthropic":  "https://api.anthropic.com/v1",
            "openai":     "https://api.openai.com/v1",
            "gemini":     "https://generativelanguage.googleapis.com/v1beta",
            "zai":        "https://open.bigmodel.cn/api/paas/v4",
        }
        return defaults.get(provider)


class CreateAgentRequest(BaseModel):
    agent_number: int = Field(..., ge=1)
    display_name: Optional[str] = None
    resources: ResourceSpec = Field(default_factory=ResourceSpec)
    llm: LLMConfig
    soul_md: str = "You are a helpful, concise AI assistant.\n"
    extra_env: list[EnvVariable] = Field(default_factory=list)
    terminal_enabled: bool = True
    browser_enabled: bool = False
    streaming_enabled: bool = True
    memory_enabled: bool = True
    session_reset_enabled: bool = False


class CreateStepStatus(BaseModel):
    step: int
    label: str
    status: str  # pending | running | done | failed
    message: str = ""


class CreateAgentResponse(BaseModel):
    agent_number: int
    name: str
    created: bool
    steps: list[CreateStepStatus] = []


# Config Read/Write
class EnvReadResponse(BaseModel):
    agent_number: int
    variables: list[EnvVariable]


class EnvWriteRequest(BaseModel):
    variables: list[EnvVariable]
    restart: bool = True


class ConfigWriteRequest(BaseModel):
    content: str = Field(..., description="Full YAML content for config.yaml")
    restart: bool = True


class SoulWriteRequest(BaseModel):
    content: str = Field(..., description="Full markdown content for SOUL.md")


# Health
class HealthResponse(BaseModel):
    status: str  # "ok" | "error"
    platform: str = "hermes-agent"
    gateway_raw: Optional[dict[str, Any]] = None
    latency_ms: Optional[float] = None
    checked_at: datetime.datetime = Field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc)
    )


# K8s Events
class K8sEvent(BaseModel):
    type: EventType
    reason: str
    message: str
    count: int = 1
    source: Optional[str] = None
    first_timestamp: Optional[datetime.datetime] = None
    last_timestamp: Optional[datetime.datetime] = None
    age_human: str = ""


class EventListResponse(BaseModel):
    agent_number: int
    events: list[K8sEvent]


# Backup
class BackupRequest(BaseModel):
    include_data: bool = True
    include_k8s_yaml: bool = True


class BackupResponse(BaseModel):
    agent_number: int
    filename: str
    size_bytes: int
    download_url: str


# Cluster Status
class NodeInfo(BaseModel):
    name: str
    cpu_capacity: str
    memory_capacity: str
    cpu_usage_percent: Optional[float] = None
    memory_usage_percent: Optional[float] = None
    disk_total_gb: Optional[float] = None
    disk_used_gb: Optional[float] = None


class ClusterStatusResponse(BaseModel):
    nodes: list[NodeInfo]
    namespace: str = "hermes-agent"
    total_agents: int = 0
    running_agents: int = 0


# Templates
class TemplateResponse(BaseModel):
    deployment_yaml: str
    env_template: str
    config_yaml_template: str
    soul_md_template: str


class TemplateTypeResponse(BaseModel):
    type: str
    content: str


class UpdateTemplateRequest(BaseModel):
    content: str = Field(..., min_length=1)


# Test LLM Connection
class TestLLMRequest(BaseModel):
    provider: LLMProvider
    api_key: str
    model: str = "anthropic/claude-sonnet-4-20250514"
    base_url: Optional[str] = None


class TestLLMResponse(BaseModel):
    success: bool
    latency_ms: float
    model_used: str
    error: Optional[str] = None
    response_preview: Optional[str] = None


# Actions
class ActionResponse(BaseModel):
    agent_number: int
    action: str  # "restart" | "start" | "stop"
    success: bool
    message: str = ""


# Settings
class DefaultResourceLimits(BaseModel):
    cpu_request: str = "250m"
    cpu_limit: str = "1000m"
    memory_request: str = "512Mi"
    memory_limit: str = "1Gi"


class SettingsResponse(BaseModel):
    admin_key_masked: str
    default_resources: DefaultResourceLimits = Field(default_factory=DefaultResourceLimits)
    templates: list[str] = Field(default_factory=lambda: ["deployment", "env", "config", "soul"])


class UpdateResourceLimitsRequest(BaseModel):
    default_resources: DefaultResourceLimits


class UpdateAdminKeyRequest(BaseModel):
    new_key: str = Field(..., min_length=8, description="New admin API key (min 8 chars)")


# Generic
class MessageResponse(BaseModel):
    message: str
    detail: Optional[str] = None
