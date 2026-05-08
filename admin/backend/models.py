from __future__ import annotations
import datetime
import re
from enum import Enum
from typing import Annotated, Any, Literal, Optional
from pydantic import BaseModel, Field, StringConstraints, field_validator

from constants import PROVIDER_URL_MAP

# K8s resource format constants
K8S_CPU_REGEX = re.compile(r"^\d+(\.\d+)?m?$")
K8S_MEMORY_REGEX = re.compile(r"^\d+(Ki|Mi|Gi|Ti)$")

# SSRF blocked hostnames
_SSRF_BLOCKED_HOSTNAMES = {"169.254.169.254", "localhost", "127.0.0.1"}


def _validate_k8s_cpu(value: str, field_name: str) -> str:
    if not K8S_CPU_REGEX.match(value):
        raise ValueError(
            f"{field_name}: invalid CPU format '{value}'. "
            "Expected format like '250m', '1', '1000m', or '0.5'"
        )
    return value


def _validate_k8s_memory(value: str, field_name: str) -> str:
    if not K8S_MEMORY_REGEX.match(value):
        raise ValueError(
            f"{field_name}: invalid memory format '{value}'. "
            "Expected format like '512Mi', '1Gi', '2Gi', or '100Ki'"
        )
    return value


def _check_ssrf(url: str) -> str:
    """Validate base_url against SSRF by blocking metadata/local hostnames."""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    if hostname in _SSRF_BLOCKED_HOSTNAMES:
        raise ValueError(
            f"base_url hostname '{hostname}' is not allowed (SSRF protection)"
        )
    return url


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
    zhipuai = "zhipuai"
    minimax = "minimax"
    kimi = "kimi"
    anthropic_compat = "anthropic-compat"
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
    key: str = Field(
        ...,
        min_length=1,
        max_length=256,
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*$",
    )
    value: str = Field("", max_length=65536)
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
    display_name: Optional[str] = None
    status: AgentStatus
    url_path: str = Field("", description="Ingress path, e.g. /agent4")
    api_server_url: str = Field("", description="Full external API URL, e.g. http://host/agent4")
    api_key_masked: str = Field("", description="Masked API key, e.g. abc***xyz")
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
    display_name: Optional[str] = None
    status: AgentStatus
    url_path: str
    api_server_url: str = ""
    api_key_masked: str = ""
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

    @field_validator("cpu_request", "cpu_limit", mode="before")
    @classmethod
    def _validate_cpu(cls, v: str) -> str:
        return _validate_k8s_cpu(v, "cpu_request/cpu_limit")

    @field_validator("memory_request", "memory_limit", mode="before")
    @classmethod
    def _validate_memory(cls, v: str) -> str:
        return _validate_k8s_memory(v, "memory_request/memory_limit")


class LLMConfig(BaseModel):
    provider: LLMProvider = LLMProvider.openrouter
    api_key: str = Field(..., min_length=1, max_length=4096)
    model: str = Field(
        "anthropic/claude-sonnet-4-20250514",
        max_length=256,
        pattern=r'^[a-zA-Z0-9\-_./:]+$',
    )
    base_url: Optional[str] = Field(None, max_length=2048)

    @field_validator("base_url", mode="before")
    @classmethod
    def _fill_default_url(cls, v, info):
        if v:
            if not v.startswith(("http://", "https://")):
                raise ValueError("base_url must start with http:// or https://")
            _check_ssrf(v)
            return v
        provider = info.data.get("provider")
        return PROVIDER_URL_MAP.get(provider)


class CreateAgentRequest(BaseModel):
    agent_number: int = Field(..., ge=1, le=1000)
    display_name: Optional[str] = Field(None, max_length=128)

    @field_validator("display_name", mode="before")
    @classmethod
    def _strip_display_name(cls, v):
        if isinstance(v, str):
            v = v.strip()
        return v if v else None
    resources: ResourceSpec = Field(default_factory=ResourceSpec)
    llm: LLMConfig
    soul_md: str = Field("You are a helpful, concise AI assistant.\n", max_length=1_000_000)
    extra_env: list[EnvVariable] = Field(default_factory=list, max_length=50)
    terminal_enabled: bool = True
    browser_enabled: bool = False
    streaming_enabled: bool = True
    memory_enabled: bool = True
    session_reset_enabled: bool = False
    swarm_enabled: bool = False
    swarm_capabilities: list[str] = []
    swarm_max_tasks: int = 3


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
    variables: list[EnvVariable] = Field(..., max_length=100)
    restart: bool = True


class ConfigWriteRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=5_000_000, description="Full YAML content for config.yaml")
    restart: bool = True


class SoulWriteRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=1_000_000, description="Full markdown content for SOUL.md")


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
    content: str = Field(..., min_length=1, max_length=5_000_000)


# Test LLM Connection
class TestLLMRequest(BaseModel):
    provider: LLMProvider
    api_key: str = Field(..., min_length=1, max_length=4096)
    model: str = Field(
        "anthropic/claude-sonnet-4-20250514",
        max_length=256,
        pattern=r'^[a-zA-Z0-9\-_./:]+$',
    )
    base_url: Optional[str] = Field(None, max_length=2048)

    @field_validator("base_url", mode="before")
    @classmethod
    def _validate_base_url(cls, v):
        if v is not None:
            if not v.startswith(("http://", "https://")):
                raise ValueError("base_url must start with http:// or https://")
            _check_ssrf(v)
        return v


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


class TestAgentApiResponse(BaseModel):
    agent_number: int
    success: bool
    status_code: Optional[int] = None
    latency_ms: Optional[float] = None
    error: Optional[str] = None
    response_preview: Optional[str] = None


# Settings
DefaultResourceLimits = ResourceSpec


class SettingsResponse(BaseModel):
    admin_key_masked: str
    default_resources: DefaultResourceLimits = Field(default_factory=DefaultResourceLimits)
    templates: list[str] = Field(default_factory=lambda: ["deployment", "env", "config", "soul"])


class UpdateResourceLimitsRequest(BaseModel):
    default_resources: DefaultResourceLimits


class UpdateAdminKeyRequest(BaseModel):
    new_key: str = Field(
        ...,
        min_length=8,
        max_length=256,
        pattern=r'^[A-Za-z0-9\-_./+=]+$',
        description="New admin API key (min 8 chars)",
    )


# WeChat (Weixin) integration
class WeixinStatusResponse(BaseModel):
    agent_number: int
    connected: bool
    account_id: str = ""
    user_id: str = ""
    base_url: str = ""
    dm_policy: str = "open"
    group_policy: str = "disabled"
    bound_at: Optional[str] = None


class WeixinActionResponse(BaseModel):
    agent_number: int
    action: str
    success: bool
    message: str = ""


# API Key Reveal
class AgentApiKeyResponse(BaseModel):
    agent_number: int
    api_key: str


# Generic
class MessageResponse(BaseModel):
    message: str
    detail: Optional[str] = None


# ---------------------------------------------------------------------------
# Email/Password User Auth
# ---------------------------------------------------------------------------
class EmailLoginRequest(BaseModel):
    email: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=1, max_length=256)


class UserRegisterRequest(BaseModel):
    email: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=6, max_length=256)
    display_name: str = Field("", max_length=100)


class UserResponse(BaseModel):
    id: int
    email: str
    display_name: str
    agent_id: Optional[int] = None
    is_active: bool
    created_at: Optional[str] = None
    provisioning_status: str = "not_started"
    provisioning_error: Optional[str] = None


class UserListResponse(BaseModel):
    users: list[UserResponse]


class ActivateUserRequest(BaseModel):
    agent_id: int = Field(..., ge=0)


class UpdateUserRequest(BaseModel):
    display_name: Optional[str] = Field(None, max_length=100)
    is_active: Optional[bool] = None


class WebUILoginResponse(BaseModel):
    url: str
    email: str = ""
    password: str = ""
    provisioning_status: str = "completed"


class RebindAgentRequest(BaseModel):
    agent_id: int = Field(..., ge=1)


# ── Agent Metadata ──

TagStr = Annotated[str, StringConstraints(max_length=50, pattern=r"^[^\s]")]

# Valid domain values (extensible)
DOMAINS = ["generalist", "code", "data", "ops", "creative"]
DOMAIN_PATTERN = "|".join(DOMAINS)


class AgentMetadataUpdate(BaseModel):
    tags: list[TagStr] = Field(default_factory=list, max_length=20)
    role: str = Field(default="generalist", pattern=rf"^(coder|analyst|{DOMAIN_PATTERN})$")
    domain: str = Field(default="generalist", pattern=rf"^({DOMAIN_PATTERN})$")
    display_name: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=500)


class AgentMetadataResponse(BaseModel):
    agent_number: int
    tags: list[str]
    role: str
    domain: str = "generalist"
    skills: list[str] = []
    display_name: str = ""
    description: str = ""
    cpu_request: str = "250m"
    cpu_limit: str = "1000m"
    memory_request: str = "512Mi"
    memory_limit: str = "1Gi"
    updated_at: float | None = None


class AgentMetadataInternalResponse(BaseModel):
    agent_number: int
    tags: list[str]
    role: str
    domain: str = "generalist"
    skills: list[str] = []


# ---------------------------------------------------------------------------
# File Browser
# ---------------------------------------------------------------------------
class FileEntryResponse(BaseModel):
    name: str
    type: Literal["d", "f", "l"]
    size: int


class FileListResponse(BaseModel):
    path: str
    entries: list[FileEntryResponse]


class FileReadResponse(BaseModel):
    path: str
    content: str | None = None
    size: int
    truncated: bool = False
    binary: bool | None = None
    message: str | None = None


class FileUploadResponse(BaseModel):
    path: str
    size: int


class FileDeleteResponse(BaseModel):
    path: str
    success: bool


# ── Skill Reporting ──

class SkillReportItem(BaseModel):
    name: str = Field(..., max_length=64)
    description: str = Field("", max_length=1024)
    version: str = Field("", max_length=32)
    tags: list[TagStr] = Field(default_factory=list, max_length=50)
    skill_dir: str = Field("", max_length=512)
    content_hash: str = Field("", max_length=64)


class SkillReportRequest(BaseModel):
    skills: list[SkillReportItem] = Field(default_factory=list, max_length=200)
    report_id: str = Field("", max_length=128)


class SkillReportResponse(BaseModel):
    status: str          # "accepted" | "unchanged"
    skills_count: int
    tags_aggregated: list[str]
