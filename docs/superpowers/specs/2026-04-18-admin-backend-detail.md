# Hermes Admin Panel -- FastAPI Backend Detailed Design

> Companion to `2026-04-18-hermes-admin-panel-design.md`. This document provides
> implementation-level detail for the FastAPI backend: Pydantic models, route signatures,
> and step-by-step flows for every operation.

---

## 1. Pydantic Models

All models live in `admin/backend/models.py`.

```python
from __future__ import annotations

import datetime
from enum import Enum
from typing import Any, Optional

# Use datetime.now(timezone.utc) instead of the deprecated
# datetime.datetime.utcnow() throughout the codebase.

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class AgentStatus(str, Enum):
    running = "running"
    stopped = "stopped"
    pending = "pending"
    updating = "updating"      # deployment rollout in progress
    scaling = "scaling"        # replica count being changed
    failed = "failed"
    unknown = "unknown"


class LLMProvider(str, Enum):
    openrouter = "openrouter"
    anthropic = "anthropic"
    openai = "openai"
    gemini = "gemini"
    zai = "zai"          # ZhipuAI
    custom = "custom"


class EventType(str, Enum):
    normal = "Normal"
    warning = "Warning"


# ---------------------------------------------------------------------------
# Shared / Nested
# ---------------------------------------------------------------------------

class ResourceUsage(BaseModel):
    cpu_cores: Optional[float] = Field(None, description="CPU usage in cores (e.g. 0.25)")
    cpu_request_millicores: Optional[int] = None
    cpu_limit_millicores: Optional[int] = None
    memory_bytes: Optional[int] = Field(None, description="Memory usage in bytes")
    memory_request_bytes: Optional[int] = None
    memory_limit_bytes: Optional[int] = None


class ContainerStatus(BaseModel):
    ready: bool = False
    restart_count: int = 0
    state: str = "waiting"  # running | waiting | terminated
    reason: Optional[str] = None        # e.g. CrashLoopBackOff
    image: str = ""


class PodInfo(BaseModel):
    name: str
    phase: str  # Pending | Running | Succeeded | Failed
    pod_ip: Optional[str] = None
    node_name: Optional[str] = None
    started_at: Optional[datetime.datetime] = None
    containers: list[ContainerStatus] = []


class EnvVariable(BaseModel):
    """One .env key-value pair (value may be masked)."""
    key: str
    value: str = ""
    masked: bool = False
    is_secret: bool = False  # heuristic: contains KEY, TOKEN, SECRET, PASSWORD


class ConfigYaml(BaseModel):
    """Raw YAML content of config.yaml."""
    content: str


class SoulMarkdown(BaseModel):
    """Raw markdown content of SOUL.md."""
    content: str


# ---------------------------------------------------------------------------
# Agent List / Summary
# ---------------------------------------------------------------------------

class AgentSummary(BaseModel):
    id: int = Field(..., description="Agent number N, derived from deployment name")
    name: str = Field(..., description="Deployment name, e.g. hermes-gateway-4")
    status: AgentStatus
    url_path: str = Field("", description="Ingress path, e.g. /agent4")
    resources: ResourceUsage = Field(default_factory=ResourceUsage)
    restart_count: int = 0
    created_at: Optional[datetime.datetime] = None
    age_human: str = ""  # e.g. "2h", "5d"

    # Populated by polling gateway /health
    health_ok: Optional[bool] = None


class AgentListResponse(BaseModel):
    agents: list[AgentSummary]
    total: int


# ---------------------------------------------------------------------------
# Agent Detail
# ---------------------------------------------------------------------------

class AgentDetailResponse(BaseModel):
    id: int
    name: str
    status: AgentStatus
    url_path: str

    # K8s metadata
    namespace: str = "hermes-agent"
    labels: dict[str, str] = {}
    created_at: Optional[datetime.datetime] = None

    # Pod info
    pods: list[PodInfo] = []

    # Resources (current)
    resources: ResourceUsage = Field(default_factory=ResourceUsage)

    # Health
    health_ok: Optional[bool] = None
    health_last_check: Optional[datetime.datetime] = None

    # Ingress
    ingress_path: Optional[str] = None

    # Operational metadata
    restart_count: int = 0
    age_human: str = ""  # e.g. "2h", "5d"


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

class ResourceSpec(BaseModel):
    cpu_request: str = "250m"
    cpu_limit: str = "1000m"
    memory_request: str = "512Mi"
    memory_limit: str = "1Gi"


class LLMConfig(BaseModel):
    provider: LLMProvider = LLMProvider.openrouter
    api_key: str = Field(..., min_length=1)
    model: str = "anthropic/claude-sonnet-4-20250514"
    base_url: Optional[str] = None  # auto-filled from provider, editable for custom

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
    agent_number: int = Field(..., ge=1, description="Agent number N")
    display_name: Optional[str] = None
    resources: ResourceSpec = Field(default_factory=ResourceSpec)
    llm: LLMConfig
    soul_md: str = "You are a helpful, concise AI assistant.\n"
    extra_env: list[EnvVariable] = Field(default_factory=list)
    # config.yaml overrides (merged onto template)
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


# ---------------------------------------------------------------------------
# Config Read / Write
# ---------------------------------------------------------------------------

class EnvReadResponse(BaseModel):
    agent_number: int
    variables: list[EnvVariable]


class EnvWriteRequest(BaseModel):
    variables: list[EnvVariable]
    restart: bool = True  # auto-restart after write


class ConfigWriteRequest(BaseModel):
    content: str = Field(..., description="Full YAML content for config.yaml")
    restart: bool = True


class SoulWriteRequest(BaseModel):
    content: str = Field(..., description="Full markdown content for SOUL.md")


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    status: str  # "ok" | "error"
    platform: str = "hermes-agent"
    gateway_raw: Optional[dict[str, Any]] = None  # raw /health JSON from gateway
    latency_ms: Optional[float] = None
    checked_at: datetime.datetime = Field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc)
    )


# ---------------------------------------------------------------------------
# K8s Events
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------

class BackupRequest(BaseModel):
    include_data: bool = True       # tar the data directory
    include_k8s_yaml: bool = True   # export K8s resources


class BackupResponse(BaseModel):
    agent_number: int
    filename: str
    size_bytes: int
    download_url: str  # same-origin URL to fetch the tar.gz


# ---------------------------------------------------------------------------
# Cluster Status
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

class TemplateResponse(BaseModel):
    deployment_yaml: str
    env_template: str
    config_yaml_template: str
    soul_md_template: str


# ---------------------------------------------------------------------------
# Test LLM Connection
# ---------------------------------------------------------------------------

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
    response_preview: Optional[str] = None  # first 200 chars of completion


# ---------------------------------------------------------------------------
# Restart / Scale
# ---------------------------------------------------------------------------

class ActionResponse(BaseModel):
    agent_number: int
    action: str  # "restart" | "start" | "stop"
    success: bool
    message: str = ""


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

class DefaultResourceLimits(BaseModel):
    cpu_request: str = "250m"
    cpu_limit: str = "1000m"
    memory_request: str = "512Mi"
    memory_limit: str = "1Gi"


class SettingsResponse(BaseModel):
    admin_key_masked: str  # e.g. "****" (never reveal)
    default_resources: DefaultResourceLimits = Field(default_factory=DefaultResourceLimits)
    templates: list[str] = Field(
        default_factory=lambda: ["deployment", "env", "config", "soul"],
        description="List of available template types",
    )


class UpdateResourceLimitsRequest(BaseModel):
    default_resources: DefaultResourceLimits


class UpdateAdminKeyRequest(BaseModel):
    new_key: str = Field(..., min_length=8, description="New admin API key (min 8 chars)")


class TemplateTypeResponse(BaseModel):
    type: str  # deployment | env | config | soul
    content: str


class UpdateTemplateRequest(BaseModel):
    content: str = Field(..., min_length=1)


# ---------------------------------------------------------------------------
# Generic Message
# ---------------------------------------------------------------------------

class MessageResponse(BaseModel):
    message: str
    detail: Optional[str] = None
```

---

## 2. FastAPI Application Skeleton

`admin/backend/main.py`:

```python
import logging
import os
import traceback

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from models import (
    ActionResponse, AgentDetailResponse, AgentListResponse,
    BackupRequest, BackupResponse, ClusterStatusResponse,
    ConfigWriteRequest, CreateAgentRequest, CreateAgentResponse,
    EnvReadResponse, EnvWriteRequest, EventListResponse,
    HealthResponse, MessageResponse, SoulWriteRequest, SoulMarkdown,
    ConfigYaml, TemplateResponse, TestLLMRequest, TestLLMResponse,
)
from k8s_client import K8sClient
from agent_manager import AgentManager
from config_manager import ConfigManager
from templates import TemplateGenerator

logger = logging.getLogger("hermes-admin")

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

API_PREFIX = "/admin/api"
K8S_NAMESPACE = os.getenv("K8S_NAMESPACE", "hermes-agent")
ADMIN_KEY = os.getenv("ADMIN_KEY", "")

# openapi_url=None disables the /openapi.json endpoint so it is not
# exposed unauthenticated. The docs_url is also removed to prevent
# unauthenticated access to Swagger UI.
app = FastAPI(title="Hermes Admin API", openapi_url=None, docs_url=None)


# ---------------------------------------------------------------------------
# Global exception handler
# ---------------------------------------------------------------------------

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled exception on %s %s: %s\n%s",
                 request.method, request.url.path, exc, traceback.format_exc())
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Singleton helpers — instantiated once at import time
k8s = K8sClient(namespace=K8S_NAMESPACE)
manager = AgentManager(k8s=k8s, namespace=K8S_NAMESPACE)
config_mgr = ConfigManager(data_root="/data/hermes")
tpl = TemplateGenerator()


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------

async def verify_admin_key(x_admin_key: str = Header(..., alias="X-Admin-Key")):
    if ADMIN_KEY and x_admin_key != ADMIN_KEY:
        raise HTTPException(status_code=401, detail="Invalid admin key")
    return x_admin_key


# Convenience: all routes depend on auth
auth = Depends(verify_admin_key)
```

---

## 3. Complete Route Definitions

### 3.1 Agent CRUD

```python
# ------------------------------------------------------------------
# GET /admin/api/agents
# ------------------------------------------------------------------
@app.get(
    f"{API_PREFIX}/agents",
    response_model=AgentListResponse,
    dependencies=[auth],
    summary="List all agents with status and resource usage",
)
async def list_agents():
    """
    1. List all Deployments with label selector ``app starting with hermes-gateway``.
    2. For each deployment, fetch pod status + resource metrics in parallel.
    3. Build AgentSummary for each.
    """
    return await manager.list_agents()


# ------------------------------------------------------------------
# POST /admin/api/agents
# ------------------------------------------------------------------
@app.post(
    f"{API_PREFIX}/agents",
    response_model=CreateAgentResponse,
    dependencies=[auth],
    summary="Create a new agent",
    status_code=201,
)
async def create_agent(req: CreateAgentRequest):
    """
    Full creation flow -- see Section 4 for details.
    """
    return await manager.create_agent(req)


# ------------------------------------------------------------------
# GET /admin/api/agents/{agent_id}
# ------------------------------------------------------------------
@app.get(
    f"{API_PREFIX}/agents/{{agent_id}}",
    response_model=AgentDetailResponse,
    dependencies=[auth],
    summary="Get agent detail",
)
async def get_agent(agent_id: int):
    """
    1. Fetch Deployment ``hermes-gateway-{agent_id}``.
    2. Fetch pods for the deployment.
    3. Fetch resource metrics from metrics.k8s.io (if available).
    4. Build AgentDetailResponse.
    """
    return await manager.get_agent_detail(agent_id)


# ------------------------------------------------------------------
# DELETE /admin/api/agents/{agent_id}
# ------------------------------------------------------------------
@app.delete(
    f"{API_PREFIX}/agents/{{agent_id}}",
    response_model=MessageResponse,
    dependencies=[auth],
    summary="Delete an agent",
)
async def delete_agent(
    agent_id: int,
    backup: bool = Query(True, description="Create backup before deletion"),
):
    """
    Full deletion flow -- see Section 5 for details.
    """
    return await manager.delete_agent(agent_id, backup=backup)


# ------------------------------------------------------------------
# POST /admin/api/agents/{agent_id}/restart
# ------------------------------------------------------------------
@app.post(
    f"{API_PREFIX}/agents/{{agent_id}}/restart",
    response_model=ActionResponse,
    dependencies=[auth],
)
async def restart_agent(agent_id: int):
    """
    Trigger a rolling restart by patching the deployment's
    ``spec.template.metadata.annotations`` with a timestamp annotation
    ``kubectl.kubernetes.io/restartedAt``.
    """
    return await manager.restart_agent(agent_id)


# ------------------------------------------------------------------
# POST /admin/api/agents/{agent_id}/stop
# ------------------------------------------------------------------
@app.post(
    f"{API_PREFIX}/agents/{{agent_id}}/stop",
    response_model=ActionResponse,
    dependencies=[auth],
)
async def stop_agent(agent_id: int):
    """
    Scale deployment replicas to 0.
    """
    return await manager.scale_agent(agent_id, replicas=0, action="stop")


# ------------------------------------------------------------------
# POST /admin/api/agents/{agent_id}/start
# ------------------------------------------------------------------
@app.post(
    f"{API_PREFIX}/agents/{{agent_id}}/start",
    response_model=ActionResponse,
    dependencies=[auth],
)
async def start_agent(agent_id: int):
    """
    Scale deployment replicas to 1.
    """
    return await manager.scale_agent(agent_id, replicas=1, action="start")
```

### 3.2 Agent Config

```python
# ------------------------------------------------------------------
# GET /admin/api/agents/{agent_id}/config
# ------------------------------------------------------------------
@app.get(
    f"{API_PREFIX}/agents/{{agent_id}}/config",
    response_model=ConfigYaml,
    dependencies=[auth],
)
async def read_config(agent_id: int):
    """
    Read /data/hermes/agent{agent_id}/config.yaml from hostPath volume.
    """
    return config_mgr.read_config(agent_id)


# ------------------------------------------------------------------
# PUT /admin/api/agents/{agent_id}/config
# ------------------------------------------------------------------
@app.put(
    f"{API_PREFIX}/agents/{{agent_id}}/config",
    response_model=MessageResponse,
    dependencies=[auth],
)
async def write_config(agent_id: int, body: ConfigWriteRequest):
    """
    Validate YAML, write config.yaml, optionally restart.
    See Section 6 for details.
    """
    await config_mgr.write_config(agent_id, body.content)
    if body.restart:
        await manager.restart_agent(agent_id)
    return MessageResponse(message="Config updated")


# ------------------------------------------------------------------
# GET /admin/api/agents/{agent_id}/env
# ------------------------------------------------------------------
@app.get(
    f"{API_PREFIX}/agents/{{agent_id}}/env",
    response_model=EnvReadResponse,
    dependencies=[auth],
)
async def read_env(agent_id: int):
    """
    Read /data/hermes/agent{agent_id}/.env. Mask values that look like secrets.
    See Section 6 for masking logic.
    """
    return config_mgr.read_env(agent_id)


# ------------------------------------------------------------------
# PUT /admin/api/agents/{agent_id}/env
# ------------------------------------------------------------------
@app.put(
    f"{API_PREFIX}/agents/{{agent_id}}/env",
    response_model=MessageResponse,
    dependencies=[auth],
)
async def write_env(agent_id: int, body: EnvWriteRequest):
    """
    Merge key-value pairs into existing .env, optionally restart.
    Only writes keys that are present in the request body.
    See Section 6 for merge logic.
    """
    await config_mgr.write_env(agent_id, body.variables)
    if body.restart:
        await manager.restart_agent(agent_id)
    return MessageResponse(message="Env updated")


# ------------------------------------------------------------------
# GET /admin/api/agents/{agent_id}/soul
# ------------------------------------------------------------------
@app.get(
    f"{API_PREFIX}/agents/{{agent_id}}/soul",
    response_model=SoulMarkdown,
    dependencies=[auth],
)
async def read_soul(agent_id: int):
    """
    Read /data/hermes/agent{agent_id}/SOUL.md.
    """
    return config_mgr.read_soul(agent_id)


# ------------------------------------------------------------------
# PUT /admin/api/agents/{agent_id}/soul
# ------------------------------------------------------------------
@app.put(
    f"{API_PREFIX}/agents/{{agent_id}}/soul",
    response_model=MessageResponse,
    dependencies=[auth],
)
async def write_soul(agent_id: int, body: SoulWriteRequest):
    """
    Write /data/hermes/agent{agent_id}/SOUL.md.
    No restart needed -- SOUL.md is loaded fresh each message by the agent.
    """
    await config_mgr.write_soul(agent_id, body.content)
    return MessageResponse(message="SOUL.md updated (takes effect on next message)")
```

### 3.3 Agent Monitoring

```python
# ------------------------------------------------------------------
# GET /admin/api/agents/{agent_id}/health
# ------------------------------------------------------------------
@app.get(
    f"{API_PREFIX}/agents/{{agent_id}}/health",
    response_model=HealthResponse,
    dependencies=[auth],
)
async def agent_health(agent_id: int):
    """
    Proxy health check -- see Section 7.
    """
    return await manager.check_health(agent_id)


# ------------------------------------------------------------------
# GET /admin/api/agents/{agent_id}/logs
# ------------------------------------------------------------------
@app.get(
    f"{API_PREFIX}/agents/{{agent_id}}/logs",
    dependencies=[auth],
)
async def agent_logs(
    agent_id: int,
    tail: int = Query(500, ge=1, le=5000),
    follow: bool = Query(True),
):
    """
    Streaming pod logs via SSE -- see Section 8.
    """
    return StreamingResponse(
        manager.stream_logs(agent_id, tail=tail, follow=follow),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ------------------------------------------------------------------
# GET /admin/api/agents/{agent_id}/events
# ------------------------------------------------------------------
@app.get(
    f"{API_PREFIX}/agents/{{agent_id}}/events",
    response_model=EventListResponse,
    dependencies=[auth],
)
async def agent_events(agent_id: int):
    """
    Fetch K8s Events for the agent's deployment.
    """
    return await manager.get_events(agent_id)


# ------------------------------------------------------------------
# GET /admin/api/agents/{agent_id}/resources
# ------------------------------------------------------------------
@app.get(
    f"{API_PREFIX}/agents/{{agent_id}}/resources",
    response_model=ResourceUsage,   # reuses the model from Section 1
    dependencies=[auth],
)
async def agent_resources(agent_id: int):
    """
    CPU/memory usage from metrics.k8s.io PodMetrics.
    """
    return await manager.get_resource_usage(agent_id)
```

### 3.4 Agent Operations

```python
# ------------------------------------------------------------------
# POST /admin/api/agents/{agent_id}/backup
# ------------------------------------------------------------------
@app.post(
    f"{API_PREFIX}/agents/{{agent_id}}/backup",
    response_model=BackupResponse,
    dependencies=[auth],
)
async def backup_agent(agent_id: int, body: BackupRequest = BackupRequest()):
    """
    Create backup -- see Section 9.
    """
    return await manager.backup_agent(agent_id, body)


# ------------------------------------------------------------------
# GET /admin/api/backups/{filename}  (download endpoint)
# ------------------------------------------------------------------
@app.get(
    f"{API_PREFIX}/backups/{{filename}}",
    dependencies=[auth],
)
async def download_backup(filename: str):
    """
    Serve a previously-created backup file from /data/hermes/_backups/.
    """
    path = f"/data/hermes/_backups/{filename}"
    if not os.path.isfile(path):
        raise HTTPException(404, "Backup not found")
    return FileResponse(path, media_type="application/gzip", filename=filename)
```

### 3.5 Cluster & Templates

```python
# ------------------------------------------------------------------
# GET /admin/api/cluster/status
# ------------------------------------------------------------------
@app.get(
    f"{API_PREFIX}/cluster/status",
    response_model=ClusterStatusResponse,
    dependencies=[auth],
)
async def cluster_status():
    """
    Node info from K8s API + disk usage from hostPath node.
    """
    return await manager.get_cluster_status()


# ------------------------------------------------------------------
# GET /admin/api/templates
# ------------------------------------------------------------------
@app.get(
    f"{API_PREFIX}/templates",
    response_model=TemplateResponse,
    dependencies=[auth],
)
async def get_templates():
    """
    Return default template contents (read from bundled template files).
    """
    return tpl.get_all()


# ------------------------------------------------------------------
# POST /admin/api/test-llm-connection
# ------------------------------------------------------------------
@app.post(
    f"{API_PREFIX}/test-llm-connection",
    response_model=TestLLMResponse,
    dependencies=[auth],
)
async def test_llm_connection(body: TestLLMRequest):
    """
    Send a minimal completion request to the LLM provider.
    See Section 10.
    """
    return await manager.test_llm(body)
```

### 3.6 Settings & Template Management

```python
# ------------------------------------------------------------------
# GET /admin/api/settings
# ------------------------------------------------------------------
@app.get(
    f"{API_PREFIX}/settings",
    response_model=SettingsResponse,
    dependencies=[auth],
    summary="Get current settings",
)
async def get_settings():
    """
    Return admin key (masked), default resource limits, and template list.
    """
    return SettingsResponse(
        admin_key_masked="****",
        default_resources=manager.get_default_resource_limits(),
        templates=["deployment", "env", "config", "soul"],
    )


# ------------------------------------------------------------------
# PUT /admin/api/settings
# ------------------------------------------------------------------
@app.put(
    f"{API_PREFIX}/settings",
    response_model=MessageResponse,
    dependencies=[auth],
    summary="Update default resource limits",
)
async def update_settings(body: UpdateResourceLimitsRequest):
    """
    Persist updated default resource limits.  These are applied to
    newly created agents but do not affect existing ones.
    """
    manager.set_default_resource_limits(body.default_resources)
    return MessageResponse(message="Default resource limits updated")


# ------------------------------------------------------------------
# PUT /admin/api/settings/admin-key
# ------------------------------------------------------------------
@app.put(
    f"{API_PREFIX}/settings/admin-key",
    response_model=MessageResponse,
    dependencies=[auth],
    summary="Change admin API key",
)
async def update_admin_key(body: UpdateAdminKeyRequest):
    """
    Update the admin API key used for authentication.
    The new key takes effect immediately for subsequent requests.
    Persisted to a config file so it survives restarts.
    """
    global ADMIN_KEY
    ADMIN_KEY = body.new_key
    # Persist to disk
    config_path = "/data/hermes/_admin/admin_key"
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    with open(config_path, "w") as f:
        f.write(body.new_key)
    os.chmod(config_path, 0o600)
    return MessageResponse(message="Admin key updated")


# ------------------------------------------------------------------
# GET /admin/api/templates/{template_type}
# ------------------------------------------------------------------
@app.get(
    f"{API_PREFIX}/templates/{{template_type}}",
    response_model=TemplateTypeResponse,
    dependencies=[auth],
    summary="Get a specific template",
)
async def get_template(template_type: str):
    """
    Return the content of a single template.
    template_type must be one of: deployment, env, config, soul.
    """
    allowed = {"deployment", "env", "config", "soul"}
    if template_type not in allowed:
        raise HTTPException(400, f"Invalid template type. Allowed: {', '.join(sorted(allowed))}")
    content = tpl.get_template(template_type)
    return TemplateTypeResponse(type=template_type, content=content)


# ------------------------------------------------------------------
# PUT /admin/api/templates/{template_type}
# ------------------------------------------------------------------
@app.put(
    f"{API_PREFIX}/templates/{{template_type}}",
    response_model=MessageResponse,
    dependencies=[auth],
    summary="Update a specific template",
)
async def update_template(template_type: str, body: UpdateTemplateRequest):
    """
    Persist an updated template.  Changes apply to newly created agents.
    """
    allowed = {"deployment", "env", "config", "soul"}
    if template_type not in allowed:
        raise HTTPException(400, f"Invalid template type. Allowed: {', '.join(sorted(allowed))}")
    tpl.set_template(template_type, body.content)
    return MessageResponse(message=f"Template '{template_type}' updated")
```

---

## 4. Agent Creation Flow (Detailed)

`agent_manager.py` -- `create_agent` method.

### Step-by-step

```
Input: CreateAgentRequest
Output: CreateAgentResponse (with step statuses)
```

### Step 1: Validate & Generate API Key Secret

```python
async def create_agent(self, req: CreateAgentRequest) -> CreateAgentResponse:
    steps: list[CreateStepStatus] = []
    agent_num = req.agent_number
    name = f"hermes-gateway-{agent_num}"
    secret_name = f"{name}-secret"

    # --- Pre-flight checks ---
    # 1a. Ensure no existing deployment with this name
    existing = await self.k8s.get_deployment(name)
    if existing is not None:
        raise HTTPException(409, f"Deployment {name} already exists")

    # 1b. Generate a random API key
    api_key = secrets.token_urlsafe(32)

    # --- Step 1: Create K8s Secret ---
    step = CreateStepStatus(step=1, label="Creating Secret", status="running")
    steps.append(step)
    try:
        await self.k8s.create_secret(
            name=secret_name,
            data={"api_key": api_key},
        )
        step.status = "done"
    except Exception as e:
        step.status = "failed"
        step.message = str(e)
        return CreateAgentResponse(agent_number=agent_num, name=name,
                                   created=False, steps=steps)
```

**K8s API call:**
```python
# k8s_client.py
async def create_secret(self, name: str, data: dict[str, str]) -> V1Secret:
    """Create a K8s Secret with stringData (auto-base64 encoded by API)."""
    secret = V1Secret(
        api_version="v1",
        kind="Secret",
        metadata=V1ObjectMeta(name=name, namespace=self.namespace),
        string_data=data,     # plain text, K8s base64-encodes it
        type="Opaque",
    )
    return self.core_api.create_namespaced_secret(
        namespace=self.namespace,
        body=secret,
    )
```

### Step 2: Initialize Data Directory

```python
    # --- Step 2: Initialize data directory ---
    step = CreateStepStatus(step=2, label="Initializing data directory", status="running")
    steps.append(step)
    try:
        data_dir = f"/data/hermes/agent{agent_num}"
        os.makedirs(data_dir, exist_ok=True)

        # Write .env
        env_content = tpl.render_env(req.llm, req.extra_env)
        with open(f"{data_dir}/.env", "w") as f:
            f.write(env_content)

        # Write config.yaml
        config_content = tpl.render_config_yaml(
            default_model=req.llm.model,
            provider=req.llm.provider,
            base_url=req.llm.base_url,
            terminal_enabled=req.terminal_enabled,
            browser_enabled=req.browser_enabled,
            streaming_enabled=req.streaming_enabled,
            memory_enabled=req.memory_enabled,
            session_reset_enabled=req.session_reset_enabled,
        )
        with open(f"{data_dir}/config.yaml", "w") as f:
            f.write(config_content)

        # Write SOUL.md
        with open(f"{data_dir}/SOUL.md", "w") as f:
            f.write(req.soul_md)

        step.status = "done"
    except Exception as e:
        step.status = "failed"
        step.message = str(e)
        # Rollback: delete secret
        await self.k8s.delete_secret(secret_name)
        return CreateAgentResponse(agent_number=agent_num, name=name,
                                   created=False, steps=steps)
```

### Step 3: Create Deployment + Service

```python
    # --- Step 3: Create Deployment ---
    step = CreateStepStatus(step=3, label="Creating Deployment", status="running")
    steps.append(step)
    try:
        deployment_body = tpl.render_deployment(
            agent_number=agent_num,
            secret_name=secret_name,
            resources=req.resources,
        )
        await self.k8s.create_deployment(deployment_body)
        step.status = "done"
    except Exception as e:
        step.status = "failed"
        step.message = str(e)
        # Rollback: delete data dir + secret
        shutil.rmtree(data_dir, ignore_errors=True)
        await self.k8s.delete_secret(secret_name)
        return CreateAgentResponse(agent_number=agent_num, name=name,
                                   created=False, steps=steps)

    # --- Step 3b: Create Service ---
    step_svc = CreateStepStatus(step=3, label="Creating Service", status="running")
    steps.append(step_svc)
    try:
        service_body = tpl.render_service(agent_number=agent_num)
        await self.k8s.create_service(service_body)
        step_svc.status = "done"
    except Exception as e:
        step_svc.status = "failed"
        step_svc.message = str(e)
        # Rollback deployment + data dir + secret
        await self.k8s.delete_deployment(name)
        shutil.rmtree(data_dir, ignore_errors=True)
        await self.k8s.delete_secret(secret_name)
        return CreateAgentResponse(agent_number=agent_num, name=name,
                                   created=False, steps=steps)
```

**Template rendering** (deployment YAML generated from the reference template):

```python
# templates.py
def render_deployment(self, agent_number: int, secret_name: str,
                      resources: ResourceSpec) -> dict:
    """Return a dict suitable for kubernetes-client create_namespaced_deployment."""
    name = f"hermes-gateway-{agent_number}"
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": name, "namespace": self.namespace},
        "spec": {
            "replicas": 1,
            "selector": {"matchLabels": {"app": name}},
            "template": {
                "metadata": {"labels": {"app": name}},
                "spec": {
                    "serviceAccountName": "hermes-gateway",
                    "containers": [{
                        "name": "gateway",
                        "image": "nousresearch/hermes-agent:latest",
                        "imagePullPolicy": "IfNotPresent",
                        "args": ["gateway"],
                        "ports": [{"containerPort": 8642}],
                        "env": [
                            {"name": "API_SERVER_ENABLED",  "value": "true"},
                            {"name": "API_SERVER_HOST",     "value": "0.0.0.0"},
                            {"name": "API_SERVER_PORT",     "value": "8642"},
                            {
                                "name": "API_SERVER_KEY",
                                "valueFrom": {
                                    "secretKeyRef": {
                                        "name": secret_name,
                                        "key": "api_key",
                                    }
                                },
                            },
                            {"name": "GATEWAY_ALLOW_ALL_USERS", "value": "true"},
                            {"name": "K8S_NAMESPACE",           "value": self.namespace},
                            {"name": "SANDBOX_POOL_NAME",       "value": "hermes-sandbox-pool"},
                            {"name": "SANDBOX_TTL_MINUTES",     "value": "30"},
                        ],
                        "resources": {
                            "requests": {
                                "cpu":    resources.cpu_request,
                                "memory": resources.memory_request,
                            },
                            "limits": {
                                "cpu":    resources.cpu_limit,
                                "memory": resources.memory_limit,
                            },
                        },
                        "readinessProbe": {
                            "httpGet": {"path": "/health", "port": 8642},
                            "initialDelaySeconds": 60,
                            "periodSeconds": 10,
                            "timeoutSeconds": 5,
                            "failureThreshold": 6,
                        },
                        "livenessProbe": {
                            "httpGet": {"path": "/health", "port": 8642},
                            "initialDelaySeconds": 120,
                            "periodSeconds": 30,
                            "timeoutSeconds": 10,
                            "failureThreshold": 5,
                        },
                        "volumeMounts": [{
                            "name": "hermes-data",
                            "mountPath": "/opt/data",
                        }],
                    }],
                    "volumes": [{
                        "name": "hermes-data",
                        "hostPath": {
                            "path": f"/data/hermes/agent{agent_number}",
                            "type": "DirectoryOrCreate",
                        },
                    }],
                },
            },
        },
    }


def render_service(self, agent_number: int) -> dict:
    name = f"hermes-gateway-{agent_number}"
    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": name, "namespace": self.namespace},
        "spec": {
            "type": "ClusterIP",
            "ports": [{"name": "api", "port": 8642, "targetPort": 8642}],
            "selector": {"app": name},
        },
    }
```

### Step 4: Update Ingress

```python
    # --- Step 4: Update Ingress ---
    step = CreateStepStatus(step=4, label="Updating Ingress", status="running")
    steps.append(step)
    try:
        await self.k8s.add_ingress_path(
            path=f"/agent{agent_num}",
            service_name=name,
            service_port=8642,
        )
        step.status = "done"
    except Exception as e:
        step.status = "failed"
        step.message = str(e)
        # Rollback everything including data dir
        await self.k8s.delete_deployment(name)
        await self.k8s.delete_service(name)
        shutil.rmtree(data_dir, ignore_errors=True)
        await self.k8s.delete_secret(secret_name)
        return CreateAgentResponse(agent_number=agent_num, name=name,
                                   created=False, steps=steps)
```

**Ingress patch implementation:**

```python
# k8s_client.py
# Mutex to serialize ingress mutations and prevent lost updates from
# concurrent read-modify-write cycles.
_ingress_lock = asyncio.Lock()

async def add_ingress_path(self, path: str, service_name: str,
                           service_port: int) -> None:
    """
    Patch the existing hermes-ingress to add a new path rule.
    Uses JSON Patch via the K8s API (strategic merge patch on Ingress
    is not ideal for paths, so we read-modify-write).

    Protected by an asyncio.Lock to prevent concurrent mutations, and
    uses resource_version for optimistic concurrency control.
    """
    async with _ingress_lock:
        ingress_name = "hermes-ingress"
        ingress = await asyncio.to_thread(
            self.networking_api.read_namespaced_ingress,
            name=ingress_name, namespace=self.namespace,
        )

        new_path_rule = {
            "path": f"{path}(/|$)(.*)",
            "pathType": "Prefix",
            "backend": {
                "service": {
                    "name": service_name,
                    "port": {"number": service_port},
                }
            },
        }

        # Append to the first (and typically only) HTTP rule
        if not ingress.spec.rules:
            raise RuntimeError("Ingress has no rules configured")

        paths = ingress.spec.rules[0].http.paths
        # Check for duplicate
        for p in paths:
            if p.path and p.path.startswith(path):
                raise ValueError(f"Path {path} already exists in ingress")

        paths.append(new_path_rule)

        # Write back with resource_version for optimistic concurrency
        await asyncio.to_thread(
            self.networking_api.replace_namespaced_ingress,
            name=ingress_name,
            namespace=self.namespace,
            body=ingress,
        )
```

### Step 5: Wait for Ready

```python
    # --- Step 5: Wait for ready ---
    step = CreateStepStatus(step=5, label="Waiting for ready", status="running")
    steps.append(step)
    try:
        ready = await self.k8s.wait_deployment_ready(
            name, timeout_seconds=300, poll_interval_seconds=5,
        )
        if ready:
            step.status = "done"
        else:
            step.status = "failed"
            step.message = "Deployment did not become ready within 300s"
    except Exception as e:
        step.status = "failed"
        step.message = str(e)

    created = step.status == "done"
    return CreateAgentResponse(
        agent_number=agent_num,
        name=name,
        created=created,
        steps=steps,
    )
```

**Wait implementation:**

```python
# k8s_client.py
async def wait_deployment_ready(self, name: str, timeout_seconds: int = 300,
                                 poll_interval_seconds: int = 5) -> bool:
    """
    Poll the deployment until availableReplicas == replicas or timeout.
    Runs in a thread pool to avoid blocking the async event loop.
    """
    import asyncio
    deadline = asyncio.get_event_loop().time() + timeout_seconds

    while asyncio.get_event_loop().time() < deadline:
        dep = await asyncio.to_thread(
            self.apps_api.read_namespaced_deployment,
            name=name, namespace=self.namespace,
        )
        if (dep.status.available_replicas or 0) >= (dep.spec.replicas or 1):
            return True
        await asyncio.sleep(poll_interval_seconds)

    return False
```

### Full Creation Sequence Diagram

```
Client              FastAPI                K8s API                hostPath
  |                    |                      |                      |
  | POST /agents       |                      |                      |
  |------------------->|                      |                      |
  |                    |-- check existing --->|                      |
  |                    |<-- not found --------|                      |
  |                    |-- create Secret ---> |                      |
  |                    |<-- created ----------|                      |
  |                    |-- write .env ------------------------------>|
  |                    |-- write config.yaml ----------------------->|
  |                    |-- write SOUL.md --------------------------->|
  |                    |-- create Deployment->|                      |
  |                    |<-- created ----------|                      |
  |                    |-- create Service --->|                      |
  |                    |<-- created ----------|                      |
  |                    |-- read Ingress ----->|                      |
  |                    |<-- current Ingress --|                      |
  |                    |-- replace Ingress -->|  (with new path)     |
  |                    |<-- updated ----------|                      |
  |                    |-- poll deployment -->|  (every 5s)          |
  |                    |<-- not ready --------|                      |
  |                    |-- poll deployment -->|                      |
  |                    |<-- available=1 ------|                      |
  |<-- 201 {steps} ----|                      |                      |
```

---

## 5. Agent Deletion Flow (Detailed)

```python
async def delete_agent(self, agent_id: int, backup: bool = True) -> MessageResponse:
    name = f"hermes-gateway-{agent_id}"
    secret_name = f"{name}-secret"

    # 1. Verify deployment exists
    dep = await self.k8s.get_deployment(name)
    if dep is None:
        raise HTTPException(404, f"Agent {name} not found")

    # 2. Optional backup
    if backup:
        try:
            await self._create_backup(agent_id)
        except Exception as e:
            # Abort deletion if backup was requested but failed
            raise HTTPException(
                500,
                f"Backup failed, aborting deletion to preserve data: {e}",
            )

    # 3. Delete Deployment (blocks until pods terminate)
    try:
        await self.k8s.delete_deployment(name)
    except kubernetes.client.ApiException as e:
        if e.status != 404:
            raise

    # 4. Delete Service
    try:
        await self.k8s.delete_service(name)
    except kubernetes.client.ApiException as e:
        if e.status != 404:
            raise

    # 5. Delete Secret
    try:
        await self.k8s.delete_secret(secret_name)
    except kubernetes.client.ApiException as e:
        if e.status != 404:
            raise

    # 6. Remove Ingress path
    try:
        await self.k8s.remove_ingress_path(f"/agent{agent_id}")
    except Exception:
        pass  # best-effort

    # 7. Remove data directory (only if backup was created or user confirmed)
    data_dir = f"/data/hermes/agent{agent_id}"
    if not backup:
        # Without backup, keep data dir for safety
        pass
    else:
        shutil.rmtree(data_dir, ignore_errors=True)

    return MessageResponse(message=f"Agent {name} deleted")
```

**Ingress path removal:**

```python
# k8s_client.py
async def remove_ingress_path(self, path_prefix: str) -> None:
    """Remove a path rule matching path_prefix from hermes-ingress."""
    async with _ingress_lock:
        ingress_name = "hermes-ingress"
        ingress = await asyncio.to_thread(
            self.networking_api.read_namespaced_ingress,
            name=ingress_name, namespace=self.namespace,
        )

        if not ingress.spec.rules:
            return

        paths = ingress.spec.rules[0].http.paths
        original_len = len(paths)
        ingress.spec.rules[0].http.paths = [
            p for p in paths
            if not (p.path and p.path.startswith(path_prefix))
        ]

        if len(ingress.spec.rules[0].http.paths) < original_len:
            await asyncio.to_thread(
                self.networking_api.replace_namespaced_ingress,
                name=ingress_name, namespace=self.namespace, body=ingress,
            )
```

### Deletion Sequence Diagram

```
Client              FastAPI                K8s API                hostPath
  |                    |                      |                      |
  | DELETE /agents/4   |                      |                      |
  |  ?backup=true      |                      |                      |
  |------------------->|                      |                      |
  |                    |-- tar data dir ---------------------------->| backup
  |                    |-- export K8s YAML ->|                      |
  |                    |-- delete Deployment->|                      |
  |                    |<-- deleted ----------|                      |
  |                    |-- delete Service --->|                      |
  |                    |<-- deleted ----------|                      |
  |                    |-- delete Secret ---->|                      |
  |                    |<-- deleted ----------|                      |
  |                    |-- read Ingress ----->|                      |
  |                    |-- replace Ingress -->|  (path removed)      |
  |                    |<-- updated ----------|                      |
  |                    |-- rm -rf data dir ------------------------->|
  |<-- 200 {message} --|                      |                      |
```

---

## 6. Config Read/Write Flow

`config_manager.py` operates on files under the mounted hostPath volume
`/data/hermes/agent{N}/`.

### Directory Layout

```
/data/hermes/
├── agent1/
│   ├── .env
│   ├── config.yaml
│   └── SOUL.md
├── agent2/
│   ├── .env
│   ├── config.yaml
│   └── SOUL.md
└── _backups/          # created by backup flow
```

### Reading .env (with masking)

```python
import re

SECRET_PATTERNS = re.compile(
    r"(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|AUTH)", re.IGNORECASE
)

# Dangerous env var names that must never be set via the admin API.
BLOCKED_ENV_KEYS = {
    "PATH", "HOME", "USER", "SHELL", "LD_PRELOAD", "LD_LIBRARY_PATH",
    "PYTHONPATH", "PYTHONHOME", "HOSTNAME", "TERM", "LANG", "LC_ALL",
    "PWD", "OLDPWD", "MAIL", "LOGNAME", "SSH_AUTH_SOCK", "DISPLAY",
    "XDG_RUNTIME_DIR", "container", "KUBERNETES_SERVICE_HOST",
    "KUBERNETES_SERVICE_PORT",
}

class ConfigManager:
    def __init__(self, data_root: str = "/data/hermes"):
        self.data_root = data_root

    def _agent_dir(self, agent_id: int) -> str:
        return os.path.join(self.data_root, f"agent{agent_id}")

    def read_env(self, agent_id: int) -> EnvReadResponse:
        """Read .env and return masked values for secret-looking keys."""
        env_path = os.path.join(self._agent_dir(agent_id), ".env")
        if not os.path.isfile(env_path):
            return EnvReadResponse(agent_number=agent_id, variables=[])

        variables = []
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip("\"'")

                is_secret = bool(SECRET_PATTERNS.search(key))
                if is_secret:
                    # Mask: never reveal any characters of secret values
                    masked_val = "****"
                    variables.append(EnvVariable(
                        key=key, value=masked_val, masked=True, is_secret=True,
                    ))
                else:
                    variables.append(EnvVariable(
                        key=key, value=value, masked=False, is_secret=False,
                    ))

        return EnvReadResponse(agent_number=agent_id, variables=variables)
```

### Writing .env (key-level merge)

```python
    def write_env(self, agent_id: int, updates: list[EnvVariable]) -> None:
        """
        Merge key-value pairs into existing .env.
        - Keys present in .env are updated.
        - New keys are appended.
        - Keys not in updates are left unchanged.
        - Blocked key names (PATH, LD_PRELOAD, etc.) are rejected.
        """
        # Reject dangerous env var names
        blocked = [v.key for v in updates if v.key in BLOCKED_ENV_KEYS]
        if blocked:
            raise HTTPException(
                400, f"Cannot set blocked environment variable(s): {', '.join(blocked)}"
            )
        env_path = os.path.join(self._agent_dir(agent_id), ".env")
        os.makedirs(os.path.dirname(env_path), exist_ok=True)

        # Read existing lines, preserving comments and order
        lines: list[str] = []
        if os.path.isfile(env_path):
            with open(env_path) as f:
                lines = f.readlines()

        # Build update map
        update_map = {v.key: v.value for v in updates}
        updated_keys: set[str] = set()
        new_lines: list[str] = []

        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                new_lines.append(line)
                continue
            if "=" in stripped:
                key, _, _ = stripped.partition("=")
                key = key.strip()
                if key in update_map:
                    new_lines.append(f"{key}={update_map[key]}\n")
                    updated_keys.add(key)
                    continue
            new_lines.append(line)

        # Append new keys not found in existing file
        for key, value in update_map.items():
            if key not in updated_keys:
                new_lines.append(f"{key}={value}\n")

        # Atomic write: write to temp file, then rename
        tmp_path = env_path + ".tmp"
        with open(tmp_path, "w") as f:
            f.writelines(new_lines)
        os.replace(tmp_path, env_path)
```

### Reading config.yaml

```python
    def read_config(self, agent_id: int) -> ConfigYaml:
        path = os.path.join(self._agent_dir(agent_id), "config.yaml")
        if not os.path.isfile(path):
            return ConfigYaml(content="# No config.yaml found")
        with open(path) as f:
            return ConfigYaml(content=f.read())
```

### Writing config.yaml (with validation)

```python
    async def write_config(self, agent_id: int, content: str) -> None:
        """Write config.yaml after YAML validation."""
        import yaml
        try:
            yaml.safe_load(content)  # validate it parses
        except yaml.YAMLError as e:
            raise HTTPException(400, f"Invalid YAML: {e}")

        path = os.path.join(self._agent_dir(agent_id), "config.yaml")
        os.makedirs(os.path.dirname(path), exist_ok=True)

        tmp_path = path + ".tmp"
        with open(tmp_path, "w") as f:
            f.write(content)
        os.replace(tmp_path, path)
```

### SOUL.md read/write

```python
    def read_soul(self, agent_id: int) -> SoulMarkdown:
        path = os.path.join(self._agent_dir(agent_id), "SOUL.md")
        if not os.path.isfile(path):
            return SoulMarkdown(content="")
        with open(path) as f:
            return SoulMarkdown(content=f.read())

    async def write_soul(self, agent_id: int, content: str) -> None:
        path = os.path.join(self._agent_dir(agent_id), "SOUL.md")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp_path = path + ".tmp"
        with open(tmp_path, "w") as f:
            f.write(content)
        os.replace(tmp_path, path)
```

### Write Safety Rules

1. **Atomic writes** -- all writes go to a `.tmp` file first, then `os.replace()` (atomic rename on Linux).
2. **YAML validation** -- config.yaml is parsed before writing; invalid YAML returns 400.
3. **Directory auto-creation** -- `os.makedirs(..., exist_ok=True)` for any missing parent.
4. **No secret exposure** -- .env read always masks values matching `KEY|TOKEN|SECRET|PASSWORD`.
5. **Key-level .env merge** -- only keys in the request body are changed; other keys and comments are preserved.

---

## 7. Health Check Implementation

The admin backend proxies to the agent gateway's `/health` endpoint via the K8s
Service internal DNS.

```python
import aiohttp
import time

async def check_health(self, agent_id: int) -> HealthResponse:
    """
    Proxy a health check to the agent's gateway.

    Uses K8s internal DNS: hermes-gateway-{N}.hermes-agent.svc.cluster.local:8642
    """
    service_name = f"hermes-gateway-{agent_id}"
    url = f"http://{service_name}.{self.namespace}.svc.cluster.local:8642/health"

    start = time.monotonic()
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            async with session.get(url) as resp:
                latency_ms = (time.monotonic() - start) * 1000
                raw = await resp.json()

                if resp.status == 200 and raw.get("status") == "ok":
                    return HealthResponse(
                        status="ok",
                        platform=raw.get("platform", "hermes-agent"),
                        gateway_raw=raw,
                        latency_ms=round(latency_ms, 1),
                        checked_at=datetime.datetime.now(datetime.timezone.utc),
                    )
                else:
                    return HealthResponse(
                        status="error",
                        gateway_raw=raw,
                        latency_ms=round(latency_ms, 1),
                        checked_at=datetime.datetime.now(datetime.timezone.utc),
                    )
    except Exception as e:
        return HealthResponse(
            status="error",
            checked_at=datetime.datetime.now(datetime.timezone.utc),
            gateway_raw={"error": str(e)},
        )
```

**Why not use the Ingress path?** The admin backend runs inside the same K8s
cluster and can reach the agent Service directly via cluster-internal DNS. This
avoids going through the Ingress controller and avoids any path-rewrite issues.

**Fallback for stopped agents:** If the deployment has 0 replicas, the Service
has no endpoints and the HTTP request will fail. The health endpoint returns
`status="error"` with the connection error message. The frontend checks
`agent.status == "stopped"` first and displays a "stopped" indicator without
even calling the health endpoint.

---

## 8. Streaming Logs via SSE

### SSE Auth Token Endpoint

EventSource cannot send custom headers, so we issue a short-lived token
that the SSE endpoint accepts as a query parameter.

```python
import secrets as _secrets

# In-memory store of short-lived SSE tokens: {token: (agent_id, expires_at)}
_sse_tokens: dict[str, tuple[int, float]] = {}
SSE_TOKEN_TTL = 300  # 5 minutes

@app.get(
    f"{API_PREFIX}/agents/{{agent_id}}/logs/token",
    dependencies=[auth],
    summary="Get a short-lived token for SSE log streaming",
)
async def get_log_token(agent_id: int):
    """
    Return a single-use, 5-minute token that the SSE endpoint accepts
    via ?token=xxx.  This is needed because EventSource cannot send
    custom headers (e.g. X-Admin-Key).
    """
    token = _secrets.token_urlsafe(24)
    expires_at = time.time() + SSE_TOKEN_TTL
    _sse_tokens[token] = (agent_id, expires_at)
    return {"token": token, "expires_in": SSE_TOKEN_TTL}


def _verify_sse_token(agent_id: int, token: str) -> bool:
    """Validate an SSE token. Returns True if valid, then removes it."""
    entry = _sse_tokens.pop(token, None)
    if entry is None:
        return False
    aid, expires_at = entry
    if aid != agent_id or time.time() > expires_at:
        return False
    return True
```

### Endpoint

```python
# Limit concurrent SSE connections to prevent resource exhaustion.
_sse_semaphore = asyncio.Semaphore(20)

@app.get(f"{API_PREFIX}/agents/{{agent_id}}/logs")
async def agent_logs(
    request: Request,
    agent_id: int,
    tail: int = 500,
    follow: bool = True,
    token: Optional[str] = Query(None, description="SSE auth token (alternative to header)"),
):
    # SSE auth: accept either header-based auth OR ?token=xxx
    if token:
        if not _verify_sse_token(agent_id, token):
            raise HTTPException(401, "Invalid or expired SSE token")
    else:
        # Fall back to header-based auth (not usable by EventSource,
        # but works for direct fetch/XHR clients)
        await verify_admin_key(request.headers.get("x-admin-key", ""))

    if _sse_semaphore.locked():
        raise HTTPException(429, "Too many concurrent log streams")

    return StreamingResponse(
        manager.stream_logs(agent_id, tail=tail, follow=follow, request=request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # prevent Nginx buffering
        },
    )
```

### Stream Generator

```python
import asyncio
import json
import time

async def stream_logs(self, agent_id: int, tail: int = 500,
                      follow: bool = True,
                      request: Request = None) -> AsyncGenerator[str, None]:
    """
    Async generator yielding SSE events from the K8s pod log stream.

    SSE event format:
        event: log
        data: {"timestamp": "...", "message": "...", "pod": "hermes-gateway-4-abc"}

    SSE keep-alive (every 15s):
        : ping
    """
    name = f"hermes-gateway-{agent_id}"
    pod_name = await self.k8s.get_first_pod_name(name)

    if not pod_name:
        yield f"event: error\ndata: {json.dumps({'message': 'No running pod found'})}\n\n"
        return

    async with _sse_semaphore:
        try:
            # The K8s Python client supports streaming logs via the follow parameter
            log_stream = await asyncio.to_thread(
                self.k8s.core_api.read_namespaced_pod_log,
                name=pod_name,
                namespace=self.namespace,
                tail_lines=tail,
                follow=follow,
                _preload_content=False,  # return a stream object
            )

            last_ping = time.monotonic()
            # Use a separate thread to read lines so we can use
            # asyncio.wait_for for keep-alive pings.
            line_queue: asyncio.Queue[str | None] = asyncio.Queue()

            async def _enqueue_lines():
                """Read lines from the K8s stream into an async queue."""
                try:
                    for line in log_stream:
                        decoded = line.decode("utf-8", errors="replace").rstrip("\n")
                        await line_queue.put(decoded)
                finally:
                    await line_queue.put(None)  # sentinel: stream ended

            import asyncio as _aio
            _aio.create_task(_enqueue_lines())

            while True:
                # Check for client disconnect
                if request and await request.is_disconnected():
                    break

                try:
                    # Wait for next line with 15s timeout for keep-alive ping
                    line = await asyncio.wait_for(line_queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    # No log line arrived in 15s -- send keep-alive ping
                    yield ": ping\n\n"
                    last_ping = time.monotonic()
                    continue

                if line is None:
                    # Stream ended
                    break

                payload = json.dumps({
                    "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "message": line,
                    "pod": pod_name,
                })
                yield f"event: log\ndata: {payload}\n\n"
                last_ping = time.monotonic()

        except Exception as e:
            error_payload = json.dumps({"message": f"Log stream error: {e}"})
            yield f"event: error\ndata: {error_payload}\n\n"
        finally:
            yield "event: done\ndata: {}\n\n"
```

### Frontend Consumption (for reference)

```typescript
// admin/frontend/src/lib/admin-api.ts
export async function streamAgentLogs(
  agentId: number,
  onLog: (msg: { timestamp: string; message: string; pod: string }) => void,
  onError: (err: string) => void,
  onDone: () => void,
): Promise<EventSource> {
  // 1. Obtain a short-lived SSE token (requires X-Admin-Key header)
  const tokenResp = await fetch(`/admin/api/agents/${agentId}/logs/token`, {
    headers: { "X-Admin-Key": getAdminKey() },
  });
  const { token } = await tokenResp.json();

  // 2. Open EventSource with the token as query parameter
  const es = new EventSource(
    `/admin/api/agents/${agentId}/logs?tail=500&follow=true&token=${token}`
  );
  es.addEventListener("log", (e) => onLog(JSON.parse(e.data)));
  es.addEventListener("error", (e) => {
    if (e.data) onError(JSON.parse(e.data).message);
    // EventSource auto-reconnects; caller may close if done
  });
  es.addEventListener("done", () => { es.close(); onDone(); });
  return es;
}
```

### Why SSE (not WebSocket)

1. Simpler -- unidirectional (server-to-client) fits log streaming perfectly.
2. Native browser `EventSource` API; no library needed.
3. Works through Nginx Ingress without special WebSocket annotation.
4. `X-Accel-Buffering: no` header ensures Nginx does not buffer SSE chunks.

---

## 9. Backup Implementation

### Backup Flow

```python
import io
import tarfile
import tempfile
import yaml as pyyaml

async def backup_agent(self, agent_id: int,
                       req: BackupRequest) -> BackupResponse:
    name = f"hermes-gateway-{agent_id}"
    secret_name = f"{name}-secret"
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
    filename = f"agent{agent_id}-{timestamp}.tar.gz"
    backup_dir = "/data/hermes/_backups"
    os.makedirs(backup_dir, exist_ok=True)
    backup_path = os.path.join(backup_dir, filename)

    with tarfile.open(backup_path, "w:gz") as tar:
        # --- K8s resource YAML export ---
        if req.include_k8s_yaml:
            k8s_dir = "k8s-resources"
            resources_to_export: dict[str, Any] = {}

            # Deployment
            try:
                dep = await self.k8s.get_deployment(name)
                resources_to_export["deployment.yaml"] = dep.to_dict()
            except Exception:
                pass

            # Service
            try:
                svc = await self.k8s.get_service(name)
                resources_to_export["service.yaml"] = svc.to_dict()
            except Exception:
                pass

            # Secret (masked values)
            try:
                sec = await self.k8s.get_secret(secret_name)
                # Replace actual values with "***masked***"
                safe = sec.to_dict()
                if "data" in safe:
                    safe["data"] = {k: "***masked***" for k in (safe["data"] or {})}
                resources_to_export["secret.yaml"] = safe
            except Exception:
                pass

            # Write each resource as a YAML file inside the tar
            for res_name, res_data in resources_to_export.items():
                yaml_bytes = pyyaml.dump(res_data, default_flow_style=False).encode()
                info = tarfile.TarInfo(name=f"{k8s_dir}/{res_name}")
                info.size = len(yaml_bytes)
                tar.addfile(info, io.BytesIO(yaml_bytes))

        # --- Data directory tar (with .env secret masking) ---
        if req.include_data:
            data_dir = f"/data/hermes/agent{agent_id}"
            if os.path.isdir(data_dir):
                # Mask secrets in .env before adding to tar.
                # Uses the same SECRET_PATTERNS regex from config_manager.py.
                env_path = os.path.join(data_dir, ".env")
                if os.path.isfile(env_path):
                    with open(env_path) as ef:
                        env_lines = ef.readlines()
                    masked_lines: list[str] = []
                    for line in env_lines:
                        stripped = line.strip()
                        if stripped and "=" in stripped and not stripped.startswith("#"):
                            key, _, value = stripped.partition("=")
                            key = key.strip()
                            if SECRET_PATTERNS.search(key):
                                masked_lines.append(f"{key}=****\n")
                                continue
                        masked_lines.append(line)
                    masked_env_bytes = "".join(masked_lines).encode("utf-8")
                    env_info = tarfile.TarInfo(name="data/.env")
                    env_info.size = len(masked_env_bytes)
                    tar.addfile(env_info, io.BytesIO(masked_env_bytes))
                    # Add remaining files (excluding .env which was handled above)
                    for item in os.listdir(data_dir):
                        item_path = os.path.join(data_dir, item)
                        if item == ".env":
                            continue  # already added with masking
                        if os.path.isfile(item_path):
                            tar.add(item_path, arcname=f"data/{item}")
                else:
                    tar.add(data_dir, arcname="data", recursive=True)

    size_bytes = os.path.getsize(backup_path)

    return BackupResponse(
        agent_number=agent_id,
        filename=filename,
        size_bytes=size_bytes,
        download_url=f"/admin/api/backups/{filename}",
    )
```

### Backup File Structure

```
agent4-20260418-143000.tar.gz
├── k8s-resources/
│   ├── deployment.yaml    # full Deployment manifest
│   ├── service.yaml       # full Service manifest
│   └── secret.yaml        # Secret with masked values
└── data/
    ├── .env
    ├── config.yaml
    └── SOUL.md
```

### Download Endpoint

```python
@app.get(f"{API_PREFIX}/backups/{{filename}}")
async def download_backup(filename: str):
    """Serve a backup file. Filename is validated to prevent path traversal."""
    # Security: only allow filenames matching our pattern
    if not re.match(r"^agent\d+-\d{8}-\d{6}\.tar\.gz$", filename):
        raise HTTPException(400, "Invalid backup filename")

    path = os.path.join("/data/hermes/_backups", filename)
    if not os.path.isfile(path):
        raise HTTPException(404, "Backup not found")

    return FileResponse(
        path,
        media_type="application/gzip",
        filename=filename,
    )
```

---

## 10. Test LLM Connection

Sends a minimal chat completion request to validate the API key.

```python
async def test_llm(self, req: TestLLMRequest) -> TestLLMResponse:
    """
    Send a minimal OpenAI-compatible /v1/chat/completions request.
    All supported providers (OpenRouter, Anthropic proxy, OpenAI, ZhipuAI)
    accept the OpenAI chat completions format.
    """
    base_url = req.base_url or self._default_url(req.provider)
    url = f"{base_url.rstrip('/')}/chat/completions"

    payload = {
        "model": req.model,
        "messages": [{"role": "user", "content": "Hi"}],
        "max_tokens": 5,        # minimal response
        "temperature": 0,
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {req.api_key}",
    }

    # Provider-specific headers
    if req.provider == "anthropic":
        # If using Anthropic's native API (not OpenRouter), adjust the URL
        if "anthropic.com" in base_url:
            url = f"{base_url.rstrip('/')}/messages"
            payload = {
                "model": req.model,
                "messages": [{"role": "user", "content": "Hi"}],
                "max_tokens": 5,
            }
            headers = {
                "Content-Type": "application/json",
                "x-api-key": req.api_key,
                "anthropic-version": "2023-06-01",
            }
    elif req.provider == "zai":
        headers["Authorization"] = f"Bearer {req.api_key}"

    start = time.monotonic()
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30),
        ) as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                latency_ms = round((time.monotonic() - start) * 1000, 1)
                body = await resp.text()

                if resp.status == 200:
                    # Try to extract a preview from the response
                    preview = None
                    try:
                        data = json.loads(body)
                        # OpenAI-compatible format
                        preview = data.get("choices", [{}])[0] \
                                  .get("message", {}).get("content", "")[:200]
                        # Anthropic native format
                        if not preview:
                            preview = data.get("content", [{}])[0] \
                                      .get("text", "")[:200]
                    except Exception:
                        pass

                    return TestLLMResponse(
                        success=True,
                        latency_ms=latency_ms,
                        model_used=req.model,
                        response_preview=preview,
                    )
                else:
                    # Parse error message from provider response
                    error_msg = f"HTTP {resp.status}"
                    try:
                        err_data = json.loads(body)
                        error_msg += ": " + (
                            err_data.get("error", {}).get("message", "")
                            or err_data.get("message", "")
                            or body[:200]
                        )
                    except Exception:
                        error_msg += ": " + body[:200]

                    return TestLLMResponse(
                        success=False,
                        latency_ms=latency_ms,
                        model_used=req.model,
                        error=error_msg,
                    )
    except Exception as e:
        latency_ms = round((time.monotonic() - start) * 1000, 1)
        return TestLLMResponse(
            success=False,
            latency_ms=latency_ms,
            model_used=req.model,
            error=str(e),
        )

    @staticmethod
    def _default_url(provider: LLMProvider) -> str:
        return {
            "openrouter": "https://openrouter.ai/api/v1",
            "anthropic":  "https://api.anthropic.com/v1",
            "openai":     "https://api.openai.com/v1",
            "gemini":     "https://generativelanguage.googleapis.com/v1beta",
            "zai":        "https://open.bigmodel.cn/api/paas/v4",
            "custom":     "https://api.example.com/v1",
        }.get(provider, "https://openrouter.ai/api/v1")
```

---

## 11. K8s Client Wrapper

`k8s_client.py` provides a typed async wrapper around the synchronous
`kubernetes-client/python` library. All K8s API calls are offloaded to a
thread pool via `asyncio.to_thread` to avoid blocking the FastAPI event loop.
Every call is wrapped with `asyncio.wait_for(..., timeout=30)` to prevent
indefinite hangs when the K8s API is unresponsive.

```python
import asyncio
from typing import Optional

import kubernetes.client
import kubernetes.config
from kubernetes.client import (
    V1Deployment, V1Service, V1Secret, V1Pod,
    V1ObjectMeta, AppsV1Api, CoreV1Api, NetworkingV1Api,
)

K8S_API_TIMEOUT = 30  # seconds


class K8sClient:
    def __init__(self, namespace: str = "hermes-agent"):
        self.namespace = namespace

        # Load in-cluster config when running inside K8s,
        # fall back to kubeconfig for local dev.
        try:
            kubernetes.config.load_incluster_config()
        except kubernetes.config.ConfigException:
            kubernetes.config.load_kube_config()

        self.apps_api = AppsV1Api()
        self.core_api = CoreV1Api()
        self.networking_api = NetworkingV1Api()

    @staticmethod
    async def _k8s_call(fn, *args, **kwargs):
        """Run a synchronous K8s API call in a thread with a 30s timeout."""
        return await asyncio.wait_for(
            asyncio.to_thread(fn, *args, **kwargs),
            timeout=K8S_API_TIMEOUT,
        )

    # ------------------------------------------------------------------
    # Deployments
    # ------------------------------------------------------------------

    async def get_deployment(self, name: str) -> Optional[V1Deployment]:
        try:
            return await self._k8s_call(
                self.apps_api.read_namespaced_deployment,
                name=name, namespace=self.namespace,
            )
        except kubernetes.client.ApiException as e:
            if e.status == 404:
                return None
            raise

    async def create_deployment(self, body: dict) -> V1Deployment:
        return await self._k8s_call(
            self.apps_api.create_namespaced_deployment,
            namespace=self.namespace,
            body=body,
        )

    async def delete_deployment(self, name: str) -> None:
        await self._k8s_call(
            self.apps_api.delete_namespaced_deployment,
            name=name, namespace=self.namespace,
            grace_period_seconds=0,
            propagation_policy="Foreground",
        )

    async def patch_deployment(self, name: str, body: dict) -> V1Deployment:
        return await self._k8s_call(
            self.apps_api.patch_namespaced_deployment,
            name=name, namespace=self.namespace, body=body,
        )

    # ------------------------------------------------------------------
    # Services
    # ------------------------------------------------------------------

    async def get_service(self, name: str) -> Optional[V1Service]:
        try:
            return await self._k8s_call(
                self.core_api.read_namespaced_service,
                name=name, namespace=self.namespace,
            )
        except kubernetes.client.ApiException as e:
            if e.status == 404:
                return None
            raise

    async def create_service(self, body: dict) -> V1Service:
        return await self._k8s_call(
            self.core_api.create_namespaced_service,
            namespace=self.namespace,
            body=body,
        )

    async def delete_service(self, name: str) -> None:
        await self._k8s_call(
            self.core_api.delete_namespaced_service,
            name=name, namespace=self.namespace,
        )

    # ------------------------------------------------------------------
    # Secrets
    # ------------------------------------------------------------------

    async def get_secret(self, name: str) -> Optional[V1Secret]:
        try:
            return await self._k8s_call(
                self.core_api.read_namespaced_secret,
                name=name, namespace=self.namespace,
            )
        except kubernetes.client.ApiException as e:
            if e.status == 404:
                return None
            raise

    async def create_secret(self, name: str, data: dict[str, str]) -> V1Secret:
        body = V1Secret(
            api_version="v1",
            kind="Secret",
            metadata=V1ObjectMeta(name=name, namespace=self.namespace),
            string_data=data,
            type="Opaque",
        )
        return await self._k8s_call(
            self.core_api.create_namespaced_secret,
            namespace=self.namespace, body=body,
        )

    async def delete_secret(self, name: str) -> None:
        await self._k8s_call(
            self.core_api.delete_namespaced_secret,
            name=name, namespace=self.namespace,
        )

    # ------------------------------------------------------------------
    # Pods
    # ------------------------------------------------------------------

    async def get_pods_for_deployment(self, deployment_name: str) -> list[V1Pod]:
        """Get all pods matching the deployment's label selector."""
        dep = await self.get_deployment(deployment_name)
        if not dep:
            return []
        labels = dep.spec.selector.match_labels
        label_selector = ",".join(f"{k}={v}" for k, v in labels.items())
        result = await self._k8s_call(
            self.core_api.list_namespaced_pod,
            namespace=self.namespace,
            label_selector=label_selector,
        )
        return result.items

    async def get_first_pod_name(self, deployment_name: str) -> Optional[str]:
        pods = await self.get_pods_for_deployment(deployment_name)
        for pod in pods:
            if pod.status.phase in ("Running", "Pending"):
                return pod.metadata.name
        return None

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    async def get_events(self, deployment_name: str) -> list:
        """Get K8s events related to this deployment's pods."""
        pods = await self.get_pods_for_deployment(deployment_name)
        pod_names = {p.metadata.name for p in pods}

        field_selector = ",".join(
            [f"involvedObject.name={n}" for n in pod_names]
            + [f"involvedObject.name={deployment_name}"]
        )
        # K8s API does not support OR in field_selector, so we fetch
        # all recent events in the namespace and filter.
        result = await self._k8s_call(
            self.core_api.list_namespaced_event,
            namespace=self.namespace,
            limit=200,
        )

        related = [
            e for e in result.items
            if (e.involved_object.name in pod_names
                or e.involved_object.name == deployment_name)
        ]
        # Sort by last_timestamp descending
        related.sort(key=lambda e: e.last_timestamp or e.event_time or "", reverse=True)
        return related

    # ------------------------------------------------------------------
    # Ingress
    # ------------------------------------------------------------------

    async def add_ingress_path(self, path: str, service_name: str,
                               service_port: int) -> None:
        # See Section 4, Step 4 for full implementation
        ...

    async def remove_ingress_path(self, path_prefix: str) -> None:
        # See Section 5 for full implementation
        ...

    # ------------------------------------------------------------------
    # Metrics (optional, requires metrics-server)
    # ------------------------------------------------------------------

    async def get_pod_metrics(self, pod_name: str) -> Optional[dict]:
        """
        Requires metrics.k8s.io API (metrics-server).
        Falls back gracefully if not available.
        """
        try:
            from kubernetes.client import CustomObjectsApi
            co = CustomObjectsApi()
            return await self._k8s_call(
                co.get_namespaced_custom_object,
                group="metrics.k8s.io",
                version="v1beta1",
                namespace=self.namespace,
                plural="pods",
                name=pod_name,
            )
        except Exception:
            return None
```

---

## 12. Complete Endpoint Summary

| # | Method | Path | Request Body | Response | Description |
|---|--------|------|-------------|----------|-------------|
| 1 | GET | `/admin/api/agents` | -- | `AgentListResponse` | List all agents |
| 2 | POST | `/admin/api/agents` | `CreateAgentRequest` | `CreateAgentResponse` | Create agent (201) |
| 3 | GET | `/admin/api/agents/{id}` | -- | `AgentDetailResponse` | Agent detail |
| 4 | DELETE | `/admin/api/agents/{id}` | -- | `MessageResponse` | Delete agent (query: `?backup=true`) |
| 5 | POST | `/admin/api/agents/{id}/restart` | -- | `ActionResponse` | Rolling restart |
| 6 | POST | `/admin/api/agents/{id}/stop` | -- | `ActionResponse` | Scale to 0 |
| 7 | POST | `/admin/api/agents/{id}/start` | -- | `ActionResponse` | Scale to 1 |
| 8 | GET | `/admin/api/agents/{id}/config` | -- | `ConfigYaml` | Read config.yaml |
| 9 | PUT | `/admin/api/agents/{id}/config` | `ConfigWriteRequest` | `MessageResponse` | Write config.yaml |
| 10 | GET | `/admin/api/agents/{id}/env` | -- | `EnvReadResponse` | Read .env (masked) |
| 11 | PUT | `/admin/api/agents/{id}/env` | `EnvWriteRequest` | `MessageResponse` | Write .env |
| 12 | GET | `/admin/api/agents/{id}/soul` | -- | `SoulMarkdown` | Read SOUL.md |
| 13 | PUT | `/admin/api/agents/{id}/soul` | `SoulWriteRequest` | `MessageResponse` | Write SOUL.md |
| 14 | GET | `/admin/api/agents/{id}/health` | -- | `HealthResponse` | Proxy health check |
| 15 | GET | `/admin/api/agents/{id}/logs` | -- | `text/event-stream` | SSE log stream |
| 16 | GET | `/admin/api/agents/{id}/logs/token` | -- | `{token, expires_in}` | Get SSE auth token |
| 17 | GET | `/admin/api/agents/{id}/events` | -- | `EventListResponse` | K8s events |
| 18 | GET | `/admin/api/agents/{id}/resources` | -- | `ResourceUsage` | CPU/memory metrics |
| 19 | POST | `/admin/api/agents/{id}/backup` | `BackupRequest` | `BackupResponse` | Create backup |
| 20 | GET | `/admin/api/backups/{filename}` | -- | `application/gzip` | Download backup |
| 21 | GET | `/admin/api/cluster/status` | -- | `ClusterStatusResponse` | Cluster overview |
| 22 | GET | `/admin/api/templates` | -- | `TemplateResponse` | All default templates |
| 23 | GET | `/admin/api/templates/{type}` | -- | `TemplateTypeResponse` | Single template |
| 24 | PUT | `/admin/api/templates/{type}` | `UpdateTemplateRequest` | `MessageResponse` | Update template |
| 25 | POST | `/admin/api/test-llm-connection` | `TestLLMRequest` | `TestLLMResponse` | Test LLM key |
| 26 | GET | `/admin/api/settings` | -- | `SettingsResponse` | Get settings |
| 27 | PUT | `/admin/api/settings` | `UpdateResourceLimitsRequest` | `MessageResponse` | Update resource limits |
| 28 | PUT | `/admin/api/settings/admin-key` | `UpdateAdminKeyRequest` | `MessageResponse` | Change admin key |

All endpoints require `X-Admin-Key` header, except the SSE log stream
which accepts `?token=xxx` as an alternative auth mechanism for
EventSource compatibility.

---

## 13. Error Handling Convention

All errors follow a consistent JSON format:

```python
# On HTTPException:
{"detail": "Human-readable error message"}
```

| Scenario | HTTP Status | Detail |
|----------|-------------|--------|
| Missing/invalid `X-Admin-Key` | 401 | "Invalid admin key" |
| Invalid/expired SSE token | 401 | "Invalid or expired SSE token" |
| Agent not found | 404 | "Agent hermes-gateway-4 not found" |
| Agent already exists | 409 | "Deployment hermes-gateway-4 already exists" |
| Invalid YAML in config write | 400 | "Invalid YAML: <parser error>" |
| Invalid backup filename | 400 | "Invalid backup filename" |
| Blocked env var name | 400 | "Cannot set blocked environment variable(s): PATH, ..." |
| Invalid template type | 400 | "Invalid template type. Allowed: ..." |
| Too many SSE connections | 429 | "Too many concurrent log streams" |
| Backup failed before deletion | 500 | "Backup failed, aborting deletion to preserve data: ..." |
| Backup file not found | 404 | "Backup not found" |
| K8s API unavailable | 502 | "Kubernetes API error: <message>" |
| K8s API timeout | 504 | "Kubernetes API call timed out (30s)" |
| Gateway health timeout | 504 | "Gateway health check timeout" |
| Unhandled exception | 500 | "Internal server error" |

---

## 14. Requirements

```
# admin/backend/requirements.txt
fastapi>=0.115.0
uvicorn[standard]>=0.32.0
kubernetes>=31.0.0
pydantic>=2.10.0
aiohttp>=3.11.0
PyYAML>=6.0
python-multipart>=0.0.18
```
