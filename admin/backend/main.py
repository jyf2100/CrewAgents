"""
Hermes Admin API - FastAPI application for managing Hermes Agent instances on Kubernetes.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import secrets as _secrets
import time
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from models import (
    ActionResponse, AgentDetailResponse, AgentListResponse,
    BackupRequest, BackupResponse, ClusterStatusResponse,
    ConfigWriteRequest, CreateAgentRequest, CreateAgentResponse,
    EnvReadResponse, EnvWriteRequest, EventListResponse,
    HealthResponse, MessageResponse, SoulWriteRequest, SoulMarkdown,
    ConfigYaml, TemplateResponse, TemplateTypeResponse,
    TestLLMRequest, TestLLMResponse, UpdateResourceLimitsRequest,
    UpdateAdminKeyRequest, UpdateTemplateRequest, SettingsResponse,
    DefaultResourceLimits,
)
from k8s_client import K8sClient
from agent_manager import AgentManager
from config_manager import ConfigManager
from templates import TemplateGenerator

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
API_PREFIX = "/admin/api"
K8S_NAMESPACE = os.getenv("K8S_NAMESPACE", "hermes-agent")
ADMIN_KEY = os.getenv("ADMIN_KEY", "")
HERMES_DATA_ROOT = os.getenv("HERMES_DATA_ROOT", "/data/hermes")

logger = logging.getLogger("hermes-admin")

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(title="Hermes Admin API", openapi_url=None, docs_url=None)


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Global exception handler
# ---------------------------------------------------------------------------
@app.exception_handler(Exception)
async def _global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------
async def verify_admin_key(x_admin_key: str = Header(..., alias="X-Admin-Key")):
    """Verify the request carries the correct admin key."""
    if not ADMIN_KEY:
        # No key configured -- allow all requests (dev mode).
        return True
    if x_admin_key != ADMIN_KEY:
        raise HTTPException(status_code=401, detail="Invalid admin key")
    return True


auth = Depends(verify_admin_key)


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------
@app.get(f"{API_PREFIX}/health", tags=["health"])
async def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Singleton helpers
# ---------------------------------------------------------------------------
k8s = K8sClient(namespace=K8S_NAMESPACE)
manager = AgentManager(k8s=k8s, namespace=K8S_NAMESPACE, config_mgr=ConfigManager(data_root=HERMES_DATA_ROOT))
config_mgr = ConfigManager(data_root=HERMES_DATA_ROOT)
tpl = TemplateGenerator()


# ---------------------------------------------------------------------------
# SSE token management (in-memory store for EventSource auth)
# ---------------------------------------------------------------------------
_sse_tokens: dict[str, tuple[int, float]] = {}
SSE_TOKEN_TTL = 300
_sse_semaphore = asyncio.Semaphore(20)


def _verify_sse_token(agent_id: int, token: str) -> bool:
    entry = _sse_tokens.pop(token, None)
    if entry is None:
        return False
    aid, expires_at = entry
    if aid != agent_id or time.time() > expires_at:
        return False
    return True


# ===================================================================
# Agent CRUD
# ===================================================================

@app.get(f"{API_PREFIX}/agents", response_model=AgentListResponse,
         dependencies=[auth], tags=["agents"])
async def list_agents():
    """List all Hermes agent deployments."""
    return await manager.list_agents()


@app.post(f"{API_PREFIX}/agents", response_model=CreateAgentResponse,
          status_code=201, dependencies=[auth], tags=["agents"])
async def create_agent(req: CreateAgentRequest):
    """Create a new Hermes agent with full provisioning."""
    return await manager.create_agent(req)


@app.get(f"{API_PREFIX}/agents/{{agent_id}}", response_model=AgentDetailResponse,
         dependencies=[auth], tags=["agents"])
async def get_agent_detail(agent_id: int):
    """Get detailed information about a specific agent."""
    return await manager.get_agent_detail(agent_id)


@app.delete(f"{API_PREFIX}/agents/{{agent_id}}", response_model=MessageResponse,
            dependencies=[auth], tags=["agents"])
async def delete_agent(agent_id: int, backup: bool = Query(True)):
    """Delete an agent deployment and optionally create a backup first."""
    return await manager.delete_agent(agent_id, backup=backup)


@app.post(f"{API_PREFIX}/agents/{{agent_id}}/restart", response_model=ActionResponse,
          dependencies=[auth], tags=["agents"])
async def restart_agent(agent_id: int):
    """Restart an agent by rolling update annotation."""
    return await manager.restart_agent(agent_id)


@app.post(f"{API_PREFIX}/agents/{{agent_id}}/stop", response_model=ActionResponse,
          dependencies=[auth], tags=["agents"])
async def stop_agent(agent_id: int):
    """Stop an agent by scaling to 0 replicas."""
    return await manager.scale_agent(agent_id, replicas=0, action="stop")


@app.post(f"{API_PREFIX}/agents/{{agent_id}}/start", response_model=ActionResponse,
          dependencies=[auth], tags=["agents"])
async def start_agent(agent_id: int):
    """Start an agent by scaling to 1 replica."""
    return await manager.scale_agent(agent_id, replicas=1, action="start")


# ===================================================================
# Agent Config
# ===================================================================

@app.get(f"{API_PREFIX}/agents/{{agent_id}}/config", response_model=ConfigYaml,
         dependencies=[auth], tags=["agents-config"])
async def read_config(agent_id: int):
    """Read the config.yaml for an agent."""
    return config_mgr.read_config(agent_id)


@app.put(f"{API_PREFIX}/agents/{{agent_id}}/config", response_model=MessageResponse,
         dependencies=[auth], tags=["agents-config"])
async def write_config(agent_id: int, req: ConfigWriteRequest):
    """Write the config.yaml for an agent. Optionally restart after write."""
    await config_mgr.write_config(agent_id, req.content)
    if req.restart:
        try:
            await manager.restart_agent(agent_id)
        except Exception:
            pass  # Config saved even if restart fails
    return MessageResponse(message="Config updated")


@app.get(f"{API_PREFIX}/agents/{{agent_id}}/env", response_model=EnvReadResponse,
         dependencies=[auth], tags=["agents-config"])
async def read_env(agent_id: int):
    """Read the .env file for an agent (secrets masked)."""
    return config_mgr.read_env(agent_id)


@app.put(f"{API_PREFIX}/agents/{{agent_id}}/env", response_model=MessageResponse,
         dependencies=[auth], tags=["agents-config"])
async def write_env(agent_id: int, req: EnvWriteRequest):
    """Write environment variables for an agent. Optionally restart after write."""
    config_mgr.write_env(agent_id, req.variables)
    if req.restart:
        try:
            await manager.restart_agent(agent_id)
        except Exception:
            pass
    return MessageResponse(message="Environment updated")


@app.get(f"{API_PREFIX}/agents/{{agent_id}}/soul", response_model=SoulMarkdown,
         dependencies=[auth], tags=["agents-config"])
async def read_soul(agent_id: int):
    """Read the SOUL.md for an agent."""
    return config_mgr.read_soul(agent_id)


@app.put(f"{API_PREFIX}/agents/{{agent_id}}/soul", response_model=MessageResponse,
         dependencies=[auth], tags=["agents-config"])
async def write_soul(agent_id: int, req: SoulWriteRequest):
    """Write the SOUL.md for an agent."""
    await config_mgr.write_soul(agent_id, req.content)
    return MessageResponse(message="SOUL.md updated")


# ===================================================================
# Agent Monitoring
# ===================================================================

@app.get(f"{API_PREFIX}/agents/{{agent_id}}/health", response_model=HealthResponse,
         dependencies=[auth], tags=["agents-monitoring"])
async def agent_health(agent_id: int):
    """Proxy a health check to the agent's gateway service."""
    return await manager.check_health(agent_id)


@app.get(f"{API_PREFIX}/agents/{{agent_id}}/logs/token",
         dependencies=[auth], tags=["agents-monitoring"])
async def get_logs_token(agent_id: int):
    """Issue a one-time SSE token for log streaming (EventSource cannot send headers)."""
    token = _secrets.token_urlsafe(32)
    expires_at = time.time() + SSE_TOKEN_TTL
    _sse_tokens[token] = (agent_id, expires_at)
    return {"token": token, "expires_in": SSE_TOKEN_TTL}


@app.get(f"{API_PREFIX}/agents/{{agent_id}}/logs", tags=["agents-monitoring"])
async def stream_logs(agent_id: int, token: Optional[str] = Query(None)):
    """SSE log stream for an agent. Accept ?token= as alternative auth for EventSource."""
    # Authenticate: either SSE token or admin key header
    if token:
        if not _verify_sse_token(agent_id, token):
            raise HTTPException(status_code=401, detail="Invalid or expired SSE token")
    else:
        # Fall back to header-based auth (will be checked by middleware pattern)
        raise HTTPException(status_code=401, detail="Missing SSE token")

    if _sse_semaphore.locked():
        raise HTTPException(status_code=429, detail="Too many concurrent log streams")

    async with _sse_semaphore:
        return StreamingResponse(
            manager.stream_logs(agent_id, request=None),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )


@app.get(f"{API_PREFIX}/agents/{{agent_id}}/events", response_model=EventListResponse,
         dependencies=[auth], tags=["agents-monitoring"])
async def agent_events(agent_id: int):
    """Get recent Kubernetes events for an agent."""
    return await manager.get_events(agent_id)


@app.get(f"{API_PREFIX}/agents/{{agent_id}}/resources",
         dependencies=[auth], tags=["agents-monitoring"])
async def agent_resources(agent_id: int):
    """Get current resource usage (CPU/memory) for an agent."""
    return await manager.get_resource_usage(agent_id)


# ===================================================================
# Agent Operations
# ===================================================================

@app.post(f"{API_PREFIX}/agents/{{agent_id}}/backup", response_model=BackupResponse,
          dependencies=[auth], tags=["agents-ops"])
async def create_backup(agent_id: int, req: BackupRequest = BackupRequest()):
    """Create a backup tarball for an agent."""
    return await manager.backup_agent(agent_id, req)


@app.get(f"{API_PREFIX}/backups/{{filename}}", dependencies=[auth], tags=["agents-ops"])
async def download_backup(filename: str):
    """Download a previously created backup tarball."""
    if not re.match(r"^agent\d+-\d{8}-\d{6}\.tar\.gz$", filename):
        raise HTTPException(status_code=400, detail="Invalid backup filename")
    backup_path = os.path.join(HERMES_DATA_ROOT, "_backups", filename)
    if not os.path.isfile(backup_path):
        raise HTTPException(status_code=404, detail="Backup file not found")
    return FileResponse(
        backup_path,
        media_type="application/gzip",
        filename=filename,
    )


# ===================================================================
# Cluster
# ===================================================================

@app.get(f"{API_PREFIX}/cluster/status", response_model=ClusterStatusResponse,
         dependencies=[auth], tags=["cluster"])
async def cluster_status():
    """Get cluster node status and agent counts."""
    return await manager.get_cluster_status()


@app.get(f"{API_PREFIX}/templates", response_model=TemplateResponse,
         dependencies=[auth], tags=["templates"])
async def get_all_templates():
    """Get all template files."""
    return tpl.get_all()


@app.get(f"{API_PREFIX}/templates/{{template_type}}", response_model=TemplateTypeResponse,
         dependencies=[auth], tags=["templates"])
async def get_template(template_type: str):
    """Get a single template by type (deployment, env, config, soul)."""
    try:
        content = tpl.get_template(template_type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return TemplateTypeResponse(type=template_type, content=content)


@app.put(f"{API_PREFIX}/templates/{{template_type}}", response_model=MessageResponse,
         dependencies=[auth], tags=["templates"])
async def update_template(template_type: str, req: UpdateTemplateRequest):
    """Update a template file."""
    try:
        tpl.set_template(template_type, req.content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return MessageResponse(message=f"Template '{template_type}' updated")


# ===================================================================
# Settings
# ===================================================================

@app.get(f"{API_PREFIX}/settings", response_model=SettingsResponse,
         dependencies=[auth], tags=["settings"])
async def get_settings():
    """Get current admin settings."""
    masked_key = ""
    if ADMIN_KEY:
        masked_key = ADMIN_KEY[:3] + "****" + ADMIN_KEY[-3:] if len(ADMIN_KEY) > 8 else "****"
    return SettingsResponse(
        admin_key_masked=masked_key,
        default_resources=manager.get_default_resource_limits(),
    )


@app.put(f"{API_PREFIX}/settings", response_model=MessageResponse,
         dependencies=[auth], tags=["settings"])
async def update_settings(req: UpdateResourceLimitsRequest):
    """Update default resource limits for new agents."""
    manager.set_default_resource_limits(req.default_resources)
    return MessageResponse(message="Default resource limits updated")


@app.put(f"{API_PREFIX}/settings/admin-key", response_model=MessageResponse,
         dependencies=[auth], tags=["settings"])
async def update_admin_key(req: UpdateAdminKeyRequest):
    """Change the admin API key. Persists to /data/hermes/_admin/admin_key."""
    global ADMIN_KEY
    ADMIN_KEY = req.new_key
    # Persist to disk so it survives restarts
    admin_dir = os.path.join(HERMES_DATA_ROOT, "_admin")
    os.makedirs(admin_dir, exist_ok=True)
    key_path = os.path.join(admin_dir, "admin_key")
    tmp_path = key_path + ".tmp"
    with open(tmp_path, "w") as f:
        f.write(req.new_key)
    os.replace(tmp_path, key_path)
    return MessageResponse(message="Admin key updated")


# ===================================================================
# LLM Connection Test
# ===================================================================

@app.post(f"{API_PREFIX}/test-llm-connection", response_model=TestLLMResponse,
          dependencies=[auth], tags=["utils"])
async def test_llm_connection(req: TestLLMRequest):
    """Test an LLM API key by making a minimal chat completion request."""
    return await manager.test_llm(req)


# ===================================================================
# Static file serving (SPA catch-all -- MUST be last)
# ===================================================================
STATIC_DIR = Path(__file__).parent / "static"

# Mount /assets explicitly so Vite chunked assets are served correctly
if (STATIC_DIR / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=str(STATIC_DIR / "assets")), name="assets")


@app.get("/{full_path:path}", tags=["spa"])
async def spa_fallback(full_path: str):
    """Serve the SPA: return static files for asset-like paths, index.html otherwise."""
    if "." in full_path.split("/")[-1]:
        file_path = STATIC_DIR / full_path
        if file_path.is_file():
            return FileResponse(file_path)
    return FileResponse(STATIC_DIR / "index.html")
