"""Kanban proxy routes -- forwards admin requests to agent Dashboard sidecars."""
import asyncio
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Path, Request
from starlette.responses import Response as StarletteResponse

from auth import auth, get_effective_agent_id
from templates import deployment_name

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agents/{agent_id}/kanban", tags=["kanban"])

NAMESPACE = "hermes-agent"
_CLIENT_TIMEOUT = httpx.Timeout(15.0, connect=5.0)
_dashboard_cache: dict[str, httpx.AsyncClient] = {}
_cache_lock = asyncio.Lock()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CLIENT_LIMITS = httpx.Limits(max_connections=10, max_keepalive_connections=5)
_MAX_BODY_SIZE = 1 << 20  # 1 MiB


def _dashboard_url(agent_id: int) -> str:
    svc = deployment_name(agent_id)
    return f"http://{svc}.{NAMESPACE}.svc.cluster.local:9119"


async def _get_client(base_url: str) -> httpx.AsyncClient:
    async with _cache_lock:
        if base_url not in _dashboard_cache:
            _dashboard_cache[base_url] = httpx.AsyncClient(
                base_url=base_url, timeout=_CLIENT_TIMEOUT, limits=_CLIENT_LIMITS,
            )
        return _dashboard_cache[base_url]


async def close_dashboard_clients():
    """Close all cached httpx clients. Call on app shutdown."""
    async with _cache_lock:
        for client in _dashboard_cache.values():
            await client.aclose()
        _dashboard_cache.clear()


async def _proxy(
    request: Request,
    agent_id: int,
    path: str,
) -> StarletteResponse:
    """Forward a request to the dashboard sidecar.

    Preserves method, query params, body, and content-type.
    Returns 502 JSON when the sidecar is unreachable.
    """
    base_url = _dashboard_url(agent_id)
    client = await _get_client(base_url)

    body = await request.body()
    if len(body) > _MAX_BODY_SIZE:
        raise HTTPException(status_code=413, detail="Request body too large")
    resp: httpx.Response | None = None
    try:
        resp = await client.request(
            method=request.method,
            url=path,
            params=dict(request.query_params),
            content=body or None,
            headers={
                k: v
                for k, v in request.headers.items()
                if k.lower() in ("content-type", "accept")
            },
        )
    except httpx.ConnectError as exc:
        logger.warning("Kanban dashboard unreachable for agent %s: %s", agent_id, exc)
        raise HTTPException(
            status_code=502,
            detail=f"Kanban dashboard unavailable for agent {agent_id}",
        )
    except httpx.TimeoutException as exc:
        logger.warning("Kanban dashboard timeout for agent %s: %s", agent_id, exc)
        raise HTTPException(
            status_code=504,
            detail=f"Kanban dashboard timed out for agent {agent_id}",
        )
    except httpx.HTTPError as exc:
        logger.error("Unexpected httpx error for agent %s: %s", agent_id, exc)
        raise HTTPException(
            status_code=502,
            detail=f"Kanban dashboard error for agent {agent_id}",
        )

    return StarletteResponse(
        content=resp.content,
        status_code=resp.status_code,
        media_type=resp.headers.get("content-type"),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/board", dependencies=[auth])
async def kanban_board(request: Request, agent_id: int) -> StarletteResponse:
    """Proxy: GET board state."""
    return await _proxy(request, get_effective_agent_id(request, agent_id), "/api/plugins/kanban/board")


@router.get("/tasks", dependencies=[auth])
async def kanban_list_tasks(request: Request, agent_id: int) -> StarletteResponse:
    """Proxy: GET all tasks (flattened from board columns)."""
    return await _proxy(request, get_effective_agent_id(request, agent_id), "/api/plugins/kanban/board")


@router.get("/tasks/{task_id}", dependencies=[auth])
async def kanban_get_task(request: Request, agent_id: int, task_id: str = Path(..., pattern=r"^[a-zA-Z0-9_-]{1,128}$")) -> StarletteResponse:
    """Proxy: GET single task."""
    return await _proxy(request, get_effective_agent_id(request, agent_id), f"/api/plugins/kanban/tasks/{task_id}")


@router.post("/tasks", dependencies=[auth])
async def kanban_create_task(request: Request, agent_id: int) -> StarletteResponse:
    """Proxy: POST create task."""
    return await _proxy(request, get_effective_agent_id(request, agent_id), "/api/plugins/kanban/tasks")


@router.patch("/tasks/{task_id}", dependencies=[auth])
async def kanban_update_task(request: Request, agent_id: int, task_id: str = Path(..., pattern=r"^[a-zA-Z0-9_-]{1,128}$")) -> StarletteResponse:
    """Proxy: PATCH update task."""
    return await _proxy(request, get_effective_agent_id(request, agent_id), f"/api/plugins/kanban/tasks/{task_id}")


@router.post("/tasks/{task_id}/comments", dependencies=[auth])
async def kanban_add_comment(request: Request, agent_id: int, task_id: str = Path(..., pattern=r"^[a-zA-Z0-9_-]{1,128}$")) -> StarletteResponse:
    """Proxy: POST add comment to task."""
    return await _proxy(request, get_effective_agent_id(request, agent_id), f"/api/plugins/kanban/tasks/{task_id}/comments")


@router.get("/stats", dependencies=[auth])
async def kanban_stats(request: Request, agent_id: int) -> StarletteResponse:
    """Proxy: GET kanban statistics."""
    return await _proxy(request, get_effective_agent_id(request, agent_id), "/api/plugins/kanban/stats")


@router.post("/dispatch", dependencies=[auth])
async def kanban_dispatch(request: Request, agent_id: int) -> StarletteResponse:
    """Proxy: POST dispatch task assignment."""
    return await _proxy(request, get_effective_agent_id(request, agent_id), "/api/plugins/kanban/dispatch")
