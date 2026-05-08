"""
Hermes Admin API - FastAPI application for managing Hermes Agent instances on Kubernetes.
"""
from __future__ import annotations

import asyncio
import hmac
import logging
import os
import re
import secrets as _secrets
import time
import redis as _redis
from typing import Optional

import httpx

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response as StarletteResponse
from pathlib import Path

from models import (
    ActionResponse, AgentApiKeyResponse, AgentDetailResponse, AgentListResponse,
    BackupRequest, BackupResponse, ClusterStatusResponse,
    ConfigWriteRequest, CreateAgentRequest, CreateAgentResponse,
    EnvReadResponse, EnvWriteRequest, EventListResponse,
    HealthResponse, MessageResponse, SoulWriteRequest, SoulMarkdown,
    ConfigYaml, TemplateResponse, TemplateTypeResponse,
    TestLLMRequest, TestLLMResponse, UpdateResourceLimitsRequest,
    UpdateAdminKeyRequest, UpdateTemplateRequest, SettingsResponse,
    DefaultResourceLimits, TestAgentApiResponse,
    WeixinStatusResponse, WeixinActionResponse,
    AgentMetadataUpdate,
    AgentMetadataResponse, AgentMetadataInternalResponse,
    SkillReportItem, SkillReportRequest, SkillReportResponse,
    ResourceSpec,
)
from k8s_client import K8sClient
from agent_manager import AgentManager
from config_manager import ConfigManager
from templates import TemplateGenerator, deployment_name
from weixin import stream_weixin_qr, start_qr_session, end_qr_session, read_weixin_status, unbind_weixin
from swarm_routes import router as swarm_router
from terminal import router as terminal_router
from file_browser import router as file_browser_router
from user_routes import router as user_router
from database import AsyncSessionLocal
from db_models import AgentMetadata as AgentMetadataORM
from db_models import AgentSkill as AgentSkillORM
from db_models import ReportIdRecord as ReportIdRecordORM
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

try:
    from auth import auth as user_auth, get_effective_agent_id, cleanup_expired_user_tokens
except ImportError:
    # auth.py may not exist yet (created by parallel agent)
    user_auth = None  # type: ignore[assignment]
    get_effective_agent_id = None  # type: ignore[assignment]
    cleanup_expired_user_tokens = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
API_PREFIX = ""
K8S_NAMESPACE = os.getenv("K8S_NAMESPACE", "hermes-agent")
ADMIN_KEY = os.getenv("ADMIN_KEY", "")
HERMES_DATA_ROOT = os.getenv("HERMES_DATA_ROOT", "/data/hermes")
ORCHESTRATOR_INTERNAL_URL = os.environ.get("ORCHESTRATOR_INTERNAL_URL", "http://hermes-orchestrator:8080")
ORCHESTRATOR_API_KEY = os.environ.get("ORCHESTRATOR_API_KEY", "")
if not ORCHESTRATOR_API_KEY:
    logger_orch = logging.getLogger("hermes-admin.orchestrator")
    logger_orch.warning("ORCHESTRATOR_API_KEY not set — orchestrator proxy will not authenticate")

INTERNAL_TOKEN = os.getenv("ADMIN_INTERNAL_TOKEN", "")

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("hermes-admin")

if not INTERNAL_TOKEN:
    logger.warning("ADMIN_INTERNAL_TOKEN not set — internal API will reject all requests")

# Shared httpx client for orchestrator proxy (connection pooling)
_orch_client: httpx.AsyncClient | None = None

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(title="Hermes Admin API", openapi_url=None, docs_url=None)

# Store admin key on app.state so all modules (including swarm_routes) read
# from the same source.  This ensures key rotation via update_admin_key is
# visible to every endpoint without restarting the process.
app.state.admin_key = ADMIN_KEY

# Include swarm router
app.include_router(swarm_router)
app.include_router(terminal_router)
app.include_router(file_browser_router)
app.include_router(user_router)


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
ADMIN_CORS_ORIGINS = os.environ.get("ADMIN_CORS_ORIGINS", "").split(",") if os.environ.get("ADMIN_CORS_ORIGINS") else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ADMIN_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-Admin-Key", "X-User-Token", "X-Email-Token", "X-Internal-Token"],
)


# ---------------------------------------------------------------------------
# SPA middleware -- serve index.html for browser navigation
# ---------------------------------------------------------------------------
STATIC_DIR = Path(__file__).parent / "static"


class _SpaFallbackMiddleware(BaseHTTPMiddleware):
    """Serve SPA index.html for browser navigation.

    The Ingress rewrite-target strips /admin prefix from ALL paths, so
    browser requests like /admin/agents/2 become /agents/2. The Accept
    header distinguishes browser navigation (text/html) from API calls
    (application/json or fetch/XHR). Browser requests always get the SPA;
    the SPA then makes authenticated API calls via fetch.
    """

    async def dispatch(self, request: Request, call_next):
        accept = request.headers.get("accept", "")
        path = request.url.path

        # Only intercept GET requests that want HTML (browser navigation)
        if request.method != "GET" or "text/html" not in accept:
            return await call_next(request)

        # Try static assets first
        if path.startswith("/assets/") or (path != "/" and "." in path.split("/")[-1]):
            file_path = (STATIC_DIR / path.lstrip("/")).resolve()
            if not str(file_path).startswith(str(STATIC_DIR.resolve())):
                return await call_next(request)
            if file_path.is_file():
                return FileResponse(file_path)

        # Serve SPA index.html for ALL browser navigation
        if STATIC_DIR.is_dir() and (STATIC_DIR / "index.html").is_file():
            return FileResponse(STATIC_DIR / "index.html")

        return await call_next(request)


app.add_middleware(_SpaFallbackMiddleware)


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
async def verify_admin_key(
    x_admin_key: str = Header(..., alias="X-Admin-Key"),
    request: Request = None,
):
    """Verify the request carries the correct admin key.

    .. deprecated::
        Admin-key auth will be migrated to auth.py.  New endpoints should
        use ``user_auth`` (from auth module) instead.
    """
    admin_key = getattr(request.app.state, "admin_key", "")
    if not admin_key:
        # No key configured -- allow all requests (dev mode).
        return True
    if not hmac.compare_digest(x_admin_key, admin_key):
        raise HTTPException(status_code=401, detail="Invalid admin key")
    return True


auth = user_auth if user_auth is not None else Depends(verify_admin_key)


def _aid(request: Request, agent_id: int) -> int:
    """Resolve effective agent_id (user-mode safe)."""
    return get_effective_agent_id(request, agent_id) if get_effective_agent_id is not None else agent_id


def _admin_only(request: Request) -> None:
    """Raise 403 if not admin mode."""
    if hasattr(request.state, 'agent_id') and request.state.agent_id is not None:
        raise HTTPException(status_code=403, detail="Admin access required")


async def _admin_only_dep(request: Request) -> None:
    """Dependency version — runs before body parsing."""
    _admin_only(request)


admin_only = Depends(_admin_only_dep)


def _verify_internal_token(request: Request) -> None:
    """Verify service-to-service auth via X-Internal-Token header."""
    token = request.headers.get("X-Internal-Token", "")
    if not INTERNAL_TOKEN or not hmac.compare_digest(token, INTERNAL_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid internal token")


internal_auth = Depends(_verify_internal_token)


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
config_mgr = ConfigManager(data_root=HERMES_DATA_ROOT)
manager = AgentManager(k8s=k8s, namespace=K8S_NAMESPACE, config_mgr=config_mgr)
tpl = TemplateGenerator(data_root=HERMES_DATA_ROOT)


# ---------------------------------------------------------------------------
# SSE token management (in-memory store for EventSource auth)
# ---------------------------------------------------------------------------
_sse_tokens: dict[str, tuple[int, float]] = {}
SSE_TOKEN_TTL = 300
SSE_MAX_DURATION = 300  # seconds -- hard cap on any single SSE log connection
_sse_semaphore = asyncio.Semaphore(20)


def _cleanup_expired_sse_tokens():
    """Periodic cleanup of expired SSE tokens."""
    now = time.time()
    expired = [k for k, (_, exp) in _sse_tokens.items() if now > exp]
    for k in expired:
        _sse_tokens.pop(k, None)


@app.on_event("startup")
async def _startup_cleanup():
    """Schedule periodic SSE token cleanup and init swarm Redis."""
    async def _sweep():
        while True:
            await asyncio.sleep(60)
            _cleanup_expired_sse_tokens()
            # Cleanup expired user tokens (auth module)
            if cleanup_expired_user_tokens is not None:
                cleanup_expired_user_tokens()
    asyncio.create_task(_sweep())

    # Swarm Redis init
    redis_url = os.environ.get("SWARM_REDIS_URL", "")
    if redis_url:
        try:
            r = _redis.from_url(redis_url, decode_responses=True, socket_connect_timeout=3)
            r.ping()
            app.state.swarm_redis = r
        except Exception:
            app.state.swarm_redis = None
    else:
        app.state.swarm_redis = None


@app.on_event("startup")
async def _warn_no_auth():
    if not app.state.admin_key:
        logger.warning("ADMIN_KEY not set — all API endpoints are unauthenticated!")

    # Initialize database (for email/password auth)
    try:
        from database import init_db
        await init_db()
    except Exception as e:
        logger.warning("Database init skipped: %s", e)


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
async def list_agents(request: Request):
    """List all Hermes agent deployments."""
    result = await manager.list_agents()
    # User mode: only show their own agent
    user_aid = getattr(request.state, 'agent_id', None)
    if user_aid is not None:
        result.agents = [a for a in result.agents if a.id == user_aid]
    return result


@app.post(f"{API_PREFIX}/agents", response_model=CreateAgentResponse,
          status_code=201, dependencies=[auth, admin_only], tags=["agents"])
async def create_agent(req: CreateAgentRequest):
    """Create a new Hermes agent with full provisioning."""
    return await manager.create_agent(req)


@app.get(f"{API_PREFIX}/agents/{{agent_id}}", response_model=AgentDetailResponse,
         dependencies=[auth], tags=["agents"])
async def get_agent_detail(request: Request, agent_id: int):
    """Get detailed information about a specific agent."""
    return await manager.get_agent_detail(_aid(request, agent_id))


@app.delete(f"{API_PREFIX}/agents/{{agent_id}}", response_model=MessageResponse,
            dependencies=[auth, admin_only], tags=["agents"])
async def delete_agent(agent_id: int, backup: bool = Query(True)):
    """Delete an agent deployment and optionally create a backup first."""
    return await manager.delete_agent(agent_id, backup=backup)


@app.post(f"{API_PREFIX}/agents/{{agent_id}}/restart", response_model=ActionResponse,
          dependencies=[auth], tags=["agents"])
async def restart_agent(request: Request, agent_id: int):
    """Restart an agent by rolling update annotation."""
    return await manager.restart_agent(_aid(request, agent_id))


@app.post(f"{API_PREFIX}/agents/{{agent_id}}/stop", response_model=ActionResponse,
          dependencies=[auth], tags=["agents"])
async def stop_agent(request: Request, agent_id: int):
    """Stop an agent by scaling to 0 replicas."""
    return await manager.scale_agent(_aid(request, agent_id), replicas=0, action="stop")


@app.post(f"{API_PREFIX}/agents/{{agent_id}}/start", response_model=ActionResponse,
          dependencies=[auth], tags=["agents"])
async def start_agent(request: Request, agent_id: int):
    """Start an agent by scaling to 1 replica."""
    return await manager.scale_agent(_aid(request, agent_id), replicas=1, action="start")


@app.get(f"{API_PREFIX}/agents/{{agent_id}}/resources", response_model=ResourceSpec,
         dependencies=[auth, admin_only], tags=["agents"])
async def get_agent_resources(agent_id: int, request: Request):
    """Get current CPU/memory resource limits for an agent's deployment."""
    _admin_only(request)
    return await manager.get_resources(agent_id)


@app.put(f"{API_PREFIX}/agents/{{agent_id}}/resources", response_model=ActionResponse,
         dependencies=[auth, admin_only], tags=["agents"])
async def update_agent_resources(agent_id: int, body: ResourceSpec, request: Request):
    """Update CPU/memory resource limits for an agent's deployment. Triggers rolling restart."""
    _admin_only(request)
    return await manager.update_resources(agent_id, body)


# ===================================================================
# Agent Metadata (tags / role)
# ===================================================================
@app.get(f"{API_PREFIX}/agents/metadata", response_model=list[AgentMetadataResponse], dependencies=[auth], tags=["agents-metadata"])
async def list_agent_metadata(request: Request):
    """Return metadata (tags/role/domain/skills) for all agents."""
    async with AsyncSessionLocal() as session:
        user_aid = getattr(request.state, 'agent_id', None)
        if user_aid is not None:
            # User mode: only return own metadata
            result = await session.execute(
                select(AgentMetadataORM).where(AgentMetadataORM.agent_number == user_aid)
            )
        else:
            result = await session.execute(select(AgentMetadataORM))
        rows = result.scalars().all()
        return [
            {
                "agent_number": r.agent_number,
                "tags": r.tags or [],
                "role": r.role or "generalist",
                "domain": _resolve_domain(r),
                "skills": r.skills or [],
                "display_name": r.display_name or "",
                "description": r.description or "",
                "updated_at": r.updated_at.timestamp() if r.updated_at else None,
            }
            for r in rows
        ]


@app.get(f"{API_PREFIX}/agents/{{agent_id}}/metadata", response_model=AgentMetadataResponse, dependencies=[auth], tags=["agents-metadata"])
async def get_agent_metadata(request: Request, agent_id: int):
    """Return metadata for a single agent."""
    aid = _aid(request, agent_id)
    async with AsyncSessionLocal() as session:
        row = await session.get(AgentMetadataORM, aid)
        if not row:
            raise HTTPException(404, "Agent metadata not found")
        return {
            "agent_number": row.agent_number,
            "tags": row.tags or [],
            "role": row.role or "generalist",
            "domain": _resolve_domain(row),
            "skills": row.skills or [],
            "display_name": row.display_name or "",
            "description": row.description or "",
            "updated_at": row.updated_at.timestamp() if row.updated_at else None,
        }


@app.put(f"{API_PREFIX}/agents/{{agent_id}}/metadata", dependencies=[auth, admin_only], tags=["agents-metadata"])
async def update_agent_metadata(agent_id: int, body: AgentMetadataUpdate):
    """Create or update agent metadata (tags, role, domain, display_name, description)."""
    # Verify agent exists in K8s
    dep = await k8s.get_deployment(deployment_name(agent_id))
    if dep is None:
        raise HTTPException(404, f"Agent {agent_id} not found")

    values = {"agent_number": agent_id}
    if body.tags is not None:
        values["tags"] = body.tags
    if body.role is not None:
        values["role"] = body.role
    if body.domain is not None:
        values["domain"] = body.domain
    if body.display_name is not None:
        values["display_name"] = body.display_name
    if body.description is not None:
        values["description"] = body.description

    async with AsyncSessionLocal() as session:
        stmt = pg_insert(AgentMetadataORM).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["agent_number"],
            set_={k: stmt.excluded[k] for k in values if k != "agent_number"},
        )
        await session.execute(stmt)
        await session.commit()
        row = await session.get(AgentMetadataORM, agent_id)
        return {
            "status": "updated",
            "updated_at": row.updated_at.timestamp() if row and row.updated_at else None,
        }


# ===================================================================
# Agent Config
# ===================================================================

@app.get(f"{API_PREFIX}/agents/{{agent_id}}/config", response_model=ConfigYaml,
         dependencies=[auth], tags=["agents-config"])
async def read_config(request: Request, agent_id: int):
    """Read the config.yaml for an agent."""
    return config_mgr.read_config(_aid(request, agent_id))


@app.put(f"{API_PREFIX}/agents/{{agent_id}}/config", response_model=MessageResponse,
         dependencies=[auth], tags=["agents-config"])
async def write_config(request: Request, agent_id: int, req: ConfigWriteRequest):
    """Write the config.yaml for an agent. Optionally restart after write."""
    aid = _aid(request, agent_id)
    config_mgr.write_config(aid, req.content)
    if req.restart:
        try:
            await manager.restart_agent(aid)
        except Exception:
            pass  # Config saved even if restart fails
    return MessageResponse(message="Config updated")


@app.get(f"{API_PREFIX}/agents/{{agent_id}}/env", response_model=EnvReadResponse,
         dependencies=[auth], tags=["agents-config"])
async def read_env(request: Request, agent_id: int):
    """Read the .env file for an agent (secrets masked)."""
    return config_mgr.read_env(_aid(request, agent_id))


@app.put(f"{API_PREFIX}/agents/{{agent_id}}/env", response_model=MessageResponse,
         dependencies=[auth], tags=["agents-config"])
async def write_env(request: Request, agent_id: int, req: EnvWriteRequest):
    """Write environment variables for an agent. Optionally restart after write."""
    aid = _aid(request, agent_id)
    config_mgr.write_env(aid, req.variables)
    if req.restart:
        try:
            await manager.restart_agent(aid)
        except Exception:
            pass
    return MessageResponse(message="Environment updated")


@app.get(f"{API_PREFIX}/agents/{{agent_id}}/soul", response_model=SoulMarkdown,
         dependencies=[auth], tags=["agents-config"])
async def read_soul(request: Request, agent_id: int):
    """Read the SOUL.md for an agent."""
    return config_mgr.read_soul(_aid(request, agent_id))


@app.put(f"{API_PREFIX}/agents/{{agent_id}}/soul", response_model=MessageResponse,
         dependencies=[auth], tags=["agents-config"])
async def write_soul(request: Request, agent_id: int, req: SoulWriteRequest):
    """Write the SOUL.md for an agent."""
    config_mgr.write_soul(_aid(request, agent_id), req.content)
    return MessageResponse(message="SOUL.md updated")


# ===================================================================
# Agent Monitoring
# ===================================================================

@app.get(f"{API_PREFIX}/agents/{{agent_id}}/health", response_model=HealthResponse,
         dependencies=[auth], tags=["agents-monitoring"])
async def agent_health(request: Request, agent_id: int):
    """Proxy a health check to the agent's gateway service."""
    return await manager.check_health(_aid(request, agent_id))


@app.post(f"{API_PREFIX}/agents/{{agent_id}}/test-api", response_model=TestAgentApiResponse,
          dependencies=[auth], tags=["agents-monitoring"])
async def test_agent_api(request: Request, agent_id: int):
    """Test the agent's external API endpoint via ingress URL."""
    return await manager.test_agent_api(_aid(request, agent_id))


@app.get(f"{API_PREFIX}/agents/{{agent_id}}/logs/token",
         dependencies=[auth], tags=["agents-monitoring"])
async def get_logs_token(request: Request, agent_id: int):
    """Issue a one-time SSE token for log streaming (EventSource cannot send headers)."""
    # Resolve effective agent_id (supports user-mode scoped access)
    effective_id = get_effective_agent_id(request, agent_id) if get_effective_agent_id is not None else agent_id
    token = _secrets.token_urlsafe(32)
    expires_at = time.time() + SSE_TOKEN_TTL
    _sse_tokens[token] = (effective_id, expires_at)
    return {"token": token, "expires_in": SSE_TOKEN_TTL}


@app.get(f"{API_PREFIX}/agents/{{agent_id}}/logs", tags=["agents-monitoring"])
async def stream_logs(request: Request, agent_id: int, token: Optional[str] = Query(None)):
    """SSE log stream for an agent. Accept ?token= as alternative auth for EventSource."""
    aid = _aid(request, agent_id)
    # Authenticate: either SSE token or admin key header
    if token:
        if not _verify_sse_token(aid, token):
            raise HTTPException(status_code=401, detail="Invalid or expired SSE token")
    else:
        # Fall back to header-based auth (will be checked by middleware pattern)
        raise HTTPException(status_code=401, detail="Missing SSE token")

    async with _sse_semaphore:
        return StreamingResponse(
            manager.stream_logs(aid, request=request, max_duration=SSE_MAX_DURATION),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )


@app.get(f"{API_PREFIX}/agents/{{agent_id}}/events", response_model=EventListResponse,
         dependencies=[auth], tags=["agents-monitoring"])
async def agent_events(request: Request, agent_id: int):
    """Get recent Kubernetes events for an agent."""
    return await manager.get_events(_aid(request, agent_id))


@app.post(f"{API_PREFIX}/agents/{{agent_id}}/api-key", response_model=AgentApiKeyResponse,
          dependencies=[auth], tags=["agents-monitoring"])
async def reveal_agent_api_key(agent_id: int, request: Request):
    """Reveal the full API key for an agent. Audit-logged."""
    aid = _aid(request, agent_id)
    logger.info("API key revealed for agent %d from %s", aid, request.client.host if request.client else "unknown")
    key = await manager.get_agent_api_key_full(aid)
    response = JSONResponse(content=AgentApiKeyResponse(agent_number=agent_id, api_key=key).model_dump())
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response


@app.get(f"{API_PREFIX}/agents/{{agent_id}}/resources",
         dependencies=[auth], tags=["agents-monitoring"])
async def agent_resources(request: Request, agent_id: int):
    """Get current resource usage (CPU/memory) for an agent."""
    return await manager.get_resource_usage(_aid(request, agent_id))


# ===================================================================
# Agent Operations
# ===================================================================

@app.post(f"{API_PREFIX}/agents/{{agent_id}}/backup", response_model=BackupResponse,
          dependencies=[auth], tags=["agents-ops"])
async def create_backup(request: Request, agent_id: int, req: BackupRequest = BackupRequest()):
    """Create a backup tarball for an agent."""
    return await manager.backup_agent(_aid(request, agent_id), req)


@app.get(f"{API_PREFIX}/backups/{{filename}}", dependencies=[auth, admin_only], tags=["agents-ops"])
async def download_backup(request: Request, filename: str):
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
# WeChat (Weixin) Integration
# ===================================================================

@app.get(f"{API_PREFIX}/agents/{{agent_id}}/weixin/qr",
         tags=["agents-weixin"])
async def weixin_qr_login(request: Request, agent_id: int, key: Optional[str] = Query(None, alias="key"), token: Optional[str] = Query(None, alias="token")):
    """Initiate WeChat QR login session. Returns SSE stream.

    Uses query-param auth because EventSource cannot set custom headers.
    Supports both admin key (?key=xxx) and user token (?token=xxx).
    """
    is_authorized = False
    if key:
        admin_key = getattr(request.app.state, "admin_key", "")
        if admin_key and hmac.compare_digest(key, admin_key):
            is_authorized = True
    if token and not is_authorized:
        from auth import verify_user_token
        result = verify_user_token(token)
        if result and result[0] == agent_id:
            is_authorized = True
    if not is_authorized:
        raise HTTPException(status_code=401, detail="Unauthorized")
    # Validate agent exists
    try:
        detail = await manager.get_agent_detail(agent_id)
    except HTTPException:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Check agent is running
    if detail.status.value != "running":
        raise HTTPException(status_code=400, detail="Agent must be running to register WeChat")

    agent_dir = os.path.join(HERMES_DATA_ROOT, f"agent{agent_id}")

    return StreamingResponse(
        stream_weixin_qr(agent_id, agent_dir, restart_callback=manager.restart_agent),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get(f"{API_PREFIX}/agents/{{agent_id}}/weixin/status",
         response_model=WeixinStatusResponse,
         dependencies=[auth], tags=["agents-weixin"])
async def weixin_status(request: Request, agent_id: int):
    """Get WeChat connection status for an agent."""
    aid = _aid(request, agent_id)
    agent_dir = os.path.join(HERMES_DATA_ROOT, f"agent{aid}")
    return read_weixin_status(agent_dir, aid)


@app.delete(f"{API_PREFIX}/agents/{{agent_id}}/weixin/bind",
            response_model=WeixinActionResponse,
            dependencies=[auth], tags=["agents-weixin"])
async def weixin_unbind(request: Request, agent_id: int):
    """Unbind WeChat from an agent."""
    aid = _aid(request, agent_id)
    agent_dir = os.path.join(HERMES_DATA_ROOT, f"agent{aid}")
    unbind_weixin(agent_dir, aid)

    # Restart agent to pick up the changes
    msg = "WeChat unbound and agent restarted"
    try:
        await manager.restart_agent(aid)
    except Exception:
        msg = "WeChat unbound but agent restart failed"

    return WeixinActionResponse(agent_number=aid, action="unbind", success=True, message=msg)


# ===================================================================
# Cluster
# ===================================================================

@app.get(f"{API_PREFIX}/cluster/status", response_model=ClusterStatusResponse,
         dependencies=[auth, admin_only], tags=["cluster"])
async def cluster_status():
    """Get cluster node status and agent counts."""
    return await manager.get_cluster_status()


@app.get(f"{API_PREFIX}/templates", response_model=TemplateResponse,
         dependencies=[auth, admin_only], tags=["templates"])
async def get_all_templates():
    """Get all template files."""
    return tpl.get_all()


@app.get(f"{API_PREFIX}/templates/{{template_type}}", response_model=TemplateTypeResponse,
         dependencies=[auth, admin_only], tags=["templates"])
async def get_template(template_type: str):
    """Get a single template by type (deployment, env, config, soul)."""
    try:
        content = tpl.get_template(template_type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return TemplateTypeResponse(type=template_type, content=content)


@app.put(f"{API_PREFIX}/templates/{{template_type}}", response_model=MessageResponse,
         dependencies=[auth, admin_only], tags=["templates"])
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
         dependencies=[auth, admin_only], tags=["settings"])
async def get_settings(request: Request):
    """Get current admin settings."""
    admin_key = request.app.state.admin_key
    masked_key = ""
    if admin_key:
        masked_key = admin_key[:3] + "****" + admin_key[-3:] if len(admin_key) > 8 else "****"
    return SettingsResponse(
        admin_key_masked=masked_key,
        default_resources=manager.get_default_resource_limits(),
    )


@app.put(f"{API_PREFIX}/settings", response_model=MessageResponse,
         dependencies=[auth, admin_only], tags=["settings"])
async def update_settings(req: UpdateResourceLimitsRequest):
    """Update default resource limits for new agents."""
    manager.set_default_resource_limits(req.default_resources)
    return MessageResponse(message="Default resource limits updated")


@app.put(f"{API_PREFIX}/settings/admin-key", response_model=MessageResponse,
         dependencies=[auth, admin_only], tags=["settings"])
async def update_admin_key(request: Request, req: UpdateAdminKeyRequest):
    """Change the admin API key. Persists to K8s Secret with file fallback."""
    global ADMIN_KEY
    ADMIN_KEY = req.new_key
    request.app.state.admin_key = req.new_key

    # Try K8s Secret first
    try:
        await k8s.replace_secret("hermes-admin-secret", {"admin_key": req.new_key})
    except Exception:
        try:
            await k8s.create_secret(name="hermes-admin-secret", data={"admin_key": req.new_key})
        except Exception:
            pass  # Fall through to file fallback

    # File fallback
    logger.warning(
        "Admin key persisted to plaintext file (%s/_admin/admin_key) — "
        "K8s Secret update failed; ensure this directory is excluded from backups",
        HERMES_DATA_ROOT,
    )
    admin_dir = os.path.join(HERMES_DATA_ROOT, "_admin")
    os.makedirs(admin_dir, exist_ok=True)
    key_path = os.path.join(admin_dir, "admin_key")
    tmp_path = key_path + ".tmp"
    with open(tmp_path, "w") as f:
        f.write(req.new_key)
    os.replace(tmp_path, key_path)
    os.chmod(key_path, 0o600)
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
# User Authentication (logout / me — login is in user_routes.py)
# ===================================================================

@app.post(f"{API_PREFIX}/user/logout", tags=["user"])
async def user_logout(request: Request, _=user_auth):
    """User logout -- revoke token."""
    if user_auth is None:
        raise HTTPException(status_code=501, detail="User auth module not loaded")

    from auth import revoke_user_token

    token = request.headers.get("X-User-Token", "")
    if token:
        revoke_user_token(token)
    return {"ok": True}


@app.get(f"{API_PREFIX}/user/me", tags=["user"])
async def user_me(request: Request, _=user_auth):
    """Get current user info."""
    if user_auth is None:
        raise HTTPException(status_code=501, detail="User auth module not loaded")

    agent_id = getattr(request.state, "agent_id", None)
    if agent_id is None:
        raise HTTPException(status_code=401, detail="Not authenticated as user")

    display_name = f"Agent #{agent_id}"
    try:
        deployment_name = f"hermes-gateway-{agent_id}" if agent_id > 0 else "hermes-gateway"
        deploy = await k8s.get_deployment(deployment_name)
        if deploy and deploy.metadata.annotations:
            display_name = deploy.metadata.annotations.get("hermes/display-name", display_name)
    except Exception:
        pass

    return {"agent_id": agent_id, "display_name": display_name, "mode": "user"}


# ===================================================================
# Orchestrator Proxy
# ===================================================================

@app.get("/orchestrator/capability")
async def orchestrator_capability():
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{ORCHESTRATOR_INTERNAL_URL}/health")
            return {"enabled": resp.status_code == 200}
    except Exception:
        return {"enabled": False}


@app.post("/orchestrator/tasks", dependencies=[auth, admin_only])
async def orchestrator_submit_task(request: Request):
    body = await request.json()
    # Validate body matches the expected schema
    from pydantic import ValidationError
    try:
        from hermes_orchestrator.models.api import TaskSubmitRequest
        validated = TaskSubmitRequest(**body)
        body = validated.model_dump()
    except (ImportError, ValidationError):
        pass  # If orchestrator package unavailable, forward as-is
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{ORCHESTRATOR_INTERNAL_URL}/api/v1/tasks",
            json=body,
            headers={"Authorization": f"Bearer {ORCHESTRATOR_API_KEY}"},
        )
        return StarletteResponse(content=resp.content, status_code=resp.status_code, media_type="application/json")


@app.get("/orchestrator/tasks", dependencies=[auth, admin_only])
async def orchestrator_list_tasks(request: Request):
    params = dict(request.query_params)
    if "limit" in params:
        params["limit"] = str(min(int(params.get("limit", 50)), 200))
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{ORCHESTRATOR_INTERNAL_URL}/api/v1/tasks",
            params=params,
            headers={"Authorization": f"Bearer {ORCHESTRATOR_API_KEY}"},
        )
        return StarletteResponse(content=resp.content, status_code=resp.status_code, media_type="application/json")


@app.get("/orchestrator/tasks/{task_id}", dependencies=[auth, admin_only])
async def orchestrator_get_task(task_id: str):
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{ORCHESTRATOR_INTERNAL_URL}/api/v1/tasks/{task_id}",
            headers={"Authorization": f"Bearer {ORCHESTRATOR_API_KEY}"},
        )
        return StarletteResponse(content=resp.content, status_code=resp.status_code, media_type="application/json")


@app.delete("/orchestrator/tasks/{task_id}", dependencies=[auth, admin_only])
async def orchestrator_cancel_task(task_id: str):
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.delete(
            f"{ORCHESTRATOR_INTERNAL_URL}/api/v1/tasks/{task_id}",
            headers={"Authorization": f"Bearer {ORCHESTRATOR_API_KEY}"},
        )
        return StarletteResponse(content=resp.content, status_code=resp.status_code, media_type="application/json")


@app.get("/orchestrator/agents", dependencies=[auth, admin_only])
async def orchestrator_list_agents():
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{ORCHESTRATOR_INTERNAL_URL}/api/v1/agents",
            headers={"Authorization": f"Bearer {ORCHESTRATOR_API_KEY}"},
        )
        return StarletteResponse(content=resp.content, status_code=resp.status_code, media_type="application/json")


@app.get("/orchestrator/agents/{agent_id}/health", dependencies=[auth, admin_only])
async def orchestrator_agent_health(agent_id: str):
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{ORCHESTRATOR_INTERNAL_URL}/api/v1/agents/{agent_id}/health",
            headers={"Authorization": f"Bearer {ORCHESTRATOR_API_KEY}"},
        )
        return StarletteResponse(content=resp.content, status_code=resp.status_code, media_type="application/json")


# ---------------------------------------------------------------------------
# Domain / Skills helpers
# ---------------------------------------------------------------------------

# Mapping from legacy role values to domain values (transition period)
_ROLE_TO_DOMAIN: dict[str, str] = {
    "generalist": "generalist",
    "coder": "code",
    "analyst": "data",
}


def _resolve_domain(row: AgentMetadataORM) -> str:
    """Resolve domain with fallback to role mapping during transition period."""
    domain = getattr(row, "domain", None)
    if domain:
        return domain
    role = getattr(row, "role", None) or "generalist"
    return _ROLE_TO_DOMAIN.get(role, "generalist")


# ===================================================================
# Internal API (service-to-service, used by Orchestrator)
# ===================================================================
@app.get("/internal/agents/metadata", response_model=list[AgentMetadataInternalResponse], dependencies=[internal_auth], tags=["internal"])
async def internal_all_metadata():
    """Return lightweight metadata for all agents (for Orchestrator discovery)."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(AgentMetadataORM))
        rows = result.scalars().all()
        return [
            {
                "agent_number": r.agent_number,
                "tags": r.tags or [],
                "role": r.role or "generalist",
                "domain": _resolve_domain(r),
                "skills": r.skills or [],
            }
            for r in rows
        ]


# ===================================================================
# Skill Reporting (Internal API — agent self-reporting)
# ===================================================================

@app.post(
    "/internal/agents/{agent_number}/skills/report",
    response_model=SkillReportResponse,
    dependencies=[internal_auth],
    tags=["internal"],
)
async def report_agent_skills(agent_number: int, body: SkillReportRequest):
    """Accept a full-replace skill report from an agent gateway.

    Idempotency: duplicate report_id returns "unchanged".
    Semantics: DELETE old skills + INSERT new skills in a single transaction,
    then aggregate tags into agent_metadata.skills JSONB.
    """
    async with AsyncSessionLocal() as session:
        # --- Idempotency check (atomic via INSERT ... ON CONFLICT DO NOTHING) ---
        if body.report_id:
            idemp_stmt = pg_insert(ReportIdRecordORM).values(
                report_id=body.report_id,
                agent_number=agent_number,
                skills_count=0,
                tags_aggregated=[],
            )
            idemp_stmt = idemp_stmt.on_conflict_do_nothing(index_elements=["report_id"])
            idemp_result = await session.execute(idemp_stmt)
            await session.commit()
            if idemp_result.rowcount == 0:
                # Already processed — return cached result
                existing = await session.get(ReportIdRecordORM, body.report_id)
                return SkillReportResponse(
                    status="unchanged",
                    skills_count=existing.skills_count if existing else 0,
                    tags_aggregated=existing.tags_aggregated if existing else [],
                )

        # --- Validate skill_dir paths ---
        for skill in body.skills:
            if skill.skill_dir and (".." in skill.skill_dir or skill.skill_dir.startswith("/")):
                raise HTTPException(400, f"Invalid skill_dir: {skill.skill_dir}")

        # --- Collect aggregated tags across all incoming skills ---
        all_tags: set[str] = set()
        for skill in body.skills:
            for tag in skill.tags:
                all_tags.add(tag.lower())

        tags_sorted = sorted(all_tags)

        # --- Full-replace: DELETE old + INSERT new (single transaction) ---
        await session.execute(
            delete(AgentSkillORM).where(AgentSkillORM.agent_number == agent_number)
        )

        for skill in body.skills:
            row = AgentSkillORM(
                agent_number=agent_number,
                skill_name=skill.name,
                description=skill.description,
                version=skill.version,
                tags=[t.lower() for t in skill.tags],
                skill_dir=skill.skill_dir,
                content_hash=skill.content_hash,
            )
            session.add(row)

        # --- Upsert agent_metadata.skills JSONB ---
        meta = await session.get(AgentMetadataORM, agent_number)
        if meta is None:
            meta = AgentMetadataORM(agent_number=agent_number, skills=tags_sorted)
            session.add(meta)
        else:
            meta.skills = tags_sorted

        # --- Record report_id for dedup (atomic upsert) ---
        if body.report_id:
            dedup_stmt = pg_insert(ReportIdRecordORM).values(
                report_id=body.report_id,
                agent_number=agent_number,
                skills_count=len(body.skills),
                tags_aggregated=tags_sorted,
            )
            dedup_stmt = dedup_stmt.on_conflict_do_update(
                index_elements=["report_id"],
                set_={
                    "skills_count": dedup_stmt.excluded.skills_count,
                    "tags_aggregated": dedup_stmt.excluded.tags_aggregated,
                },
            )
            await session.execute(dedup_stmt)

        await session.commit()

        return SkillReportResponse(
            status="accepted",
            skills_count=len(body.skills),
            tags_aggregated=tags_sorted,
        )


# ===================================================================
# Skill Queries (Frontend display)
# ===================================================================

@app.get(
    f"{API_PREFIX}/agents/{{agent_id}}/skills",
    response_model=list[SkillReportItem],
    dependencies=[auth],
    tags=["agents-metadata"],
)
async def get_agent_skills(agent_id: int):
    """Return the installed skills for a single agent (for frontend MetadataCard)."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(AgentSkillORM)
            .where(AgentSkillORM.agent_number == agent_id)
            .order_by(AgentSkillORM.skill_name)
        )
        rows = result.scalars().all()
        return [
            SkillReportItem(
                name=r.skill_name,
                description=r.description or "",
                version=r.version or "",
                tags=r.tags or [],
                skill_dir=r.skill_dir or "",
                content_hash=r.content_hash or "",
            )
            for r in rows
        ]


@app.get(
    f"{API_PREFIX}/orchestrator/skill-tags",
    dependencies=[auth, admin_only],
    tags=["orchestrator"],
)
async def orchestrator_skill_tags():
    """Lightweight aggregation of all skill tags across all agents.

    Returns de-duplicated tags and domain distribution for TaskSubmitPage
    tag autocompletion. Does not expose agent-level detail.
    """
    async with AsyncSessionLocal() as session:
        # Aggregate tags from all AgentSkill rows
        result = await session.execute(select(AgentSkillORM.tags))
        all_tags: set[str] = set()
        for (tags_json,) in result.all():
            for tag in (tags_json or []):
                all_tags.add(tag.lower())

        # Domain distribution from agent_metadata
        meta_result = await session.execute(
            select(AgentMetadataORM.domain, AgentMetadataORM.role)
        )
        domain_dist: dict[str, int] = {}
        for domain_val, role_val in meta_result.all():
            d = domain_val if domain_val else _ROLE_TO_DOMAIN.get(role_val or "generalist", "generalist")
            domain_dist[d] = domain_dist.get(d, 0) + 1

        return {"tags": sorted(all_tags), "domain_distribution": domain_dist}


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
        # Strip /admin prefix for asset lookups (assets are at /assets not /admin/assets)
        lookup_path = full_path[7:] if full_path.startswith("admin/") else full_path
        file_path = (STATIC_DIR / lookup_path).resolve()
        if not str(file_path).startswith(str(STATIC_DIR.resolve())):
            raise HTTPException(status_code=404)
        if file_path.is_file():
            return FileResponse(file_path)
    return FileResponse(STATIC_DIR / "index.html")
