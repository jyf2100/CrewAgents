import logging
import os
import hmac

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
import json
import time
import secrets
import asyncio

from swarm_models import (
    SwarmCapabilityResponse,
    SwarmAgentProfile,
    SwarmMetricsResponse,
    RedisHealthResponse,
    SSETokenResponse,
)
from swarm.health import check_redis_health

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Auth — same logic as main.py's verify_admin_key.
# Defined locally to avoid circular imports (main.py imports this module).
# ---------------------------------------------------------------------------
_ADMIN_KEY = os.getenv("ADMIN_KEY", "")


async def _verify_swarm_admin_key(
    x_admin_key: str = Header(..., alias="X-Admin-Key"),
) -> bool:
    """Verify the request carries the correct admin key."""
    if not _ADMIN_KEY:
        return True
    if not hmac.compare_digest(x_admin_key, _ADMIN_KEY):
        raise HTTPException(status_code=401, detail="Invalid admin key")
    return True


_auth = Depends(_verify_swarm_admin_key)

router = APIRouter(prefix="/swarm", tags=["swarm"])


def _get_redis(request: Request):
    return getattr(request.app.state, "swarm_redis", None)


async def _get_agents_data(request: Request) -> list[SwarmAgentProfile]:
    """Shared helper to fetch agent profiles from Redis."""
    redis = _get_redis(request)
    if redis is None:
        return []
    agents = []
    try:
        raw = redis.hgetall("hermes:registry")
    except Exception as e:
        logger.warning("swarm agent list fetch failed: %s", e)
        return []
    for agent_id_str, profile_json in raw.items():
        try:
            profile = json.loads(profile_json)
            agents.append(SwarmAgentProfile(
                agent_id=int(profile.get("agent_id", agent_id_str)),
                display_name=profile.get("display_name", f"Agent-{agent_id_str}"),
                capabilities=json.loads(profile.get("capabilities", "[]")),
                status=profile.get("status", "unknown"),
                current_tasks=int(profile.get("current_tasks", 0)),
                max_concurrent_tasks=int(profile.get("max_concurrent_tasks", 3)),
                last_heartbeat=float(profile.get("last_heartbeat", 0)),
                model=profile.get("model", ""),
            ))
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            logger.warning("swarm agent profile parse failed for %s: %s", agent_id_str, e)
            continue
    return agents


@router.get("/capability", response_model=SwarmCapabilityResponse, dependencies=[_auth])
async def get_capability(request: Request):
    redis = _get_redis(request)
    if redis is None:
        return SwarmCapabilityResponse(enabled=False)
    try:
        redis.ping()
        return SwarmCapabilityResponse(enabled=True)
    except Exception as e:
        logger.warning("swarm capability check failed: %s", e)
        return SwarmCapabilityResponse(enabled=False)


@router.get("/agents", response_model=list[SwarmAgentProfile], dependencies=[_auth])
async def get_swarm_agents(request: Request):
    return await _get_agents_data(request)


@router.get("/metrics", response_model=SwarmMetricsResponse, dependencies=[_auth])
async def get_swarm_metrics(request: Request):
    redis = _get_redis(request)
    if redis is None:
        return SwarmMetricsResponse(
            timestamp=time.time(), swarm_enabled=False, agents=[],
            agents_online=0, agents_offline=0, agents_busy=0,
            queues={}, redis_health=RedisHealthResponse(connected=False),
        )

    health = check_redis_health(redis)
    if not health.connected:
        return SwarmMetricsResponse(
            timestamp=time.time(), swarm_enabled=False, agents=[],
            agents_online=0, agents_offline=0, agents_busy=0,
            queues={}, redis_health=RedisHealthResponse(connected=False),
        )

    agents = await _get_agents_data(request)

    online = sum(1 for a in agents if a.status == "online")
    offline = sum(1 for a in agents if a.status == "offline")
    busy = sum(1 for a in agents if a.status == "busy")

    return SwarmMetricsResponse(
        timestamp=time.time(),
        swarm_enabled=True,
        agents=agents,
        agents_online=online,
        agents_offline=offline,
        agents_busy=busy,
        queues={"streams": [], "total_pending": 0},
        redis_health=RedisHealthResponse(
            connected=True,
            latency_ms=health.latency_ms,
            memory_used_percent=health.memory_used_percent,
            connected_clients=health.connected_clients,
            uptime_seconds=health.uptime_seconds,
            aof_enabled=health.aof_enabled,
            version=health.version,
        ),
    )


@router.post("/events/token", response_model=SSETokenResponse, dependencies=[_auth])
async def create_sse_token(request: Request):
    redis = _get_redis(request)
    token = f"sse_{secrets.token_hex(16)}"
    ttl = 1800
    if redis:
        try:
            redis.setex(f"hermes:sse:token:{token}", ttl, "valid")
        except Exception as e:
            logger.warning("swarm SSE token store failed: %s", e)
    return SSETokenResponse(token=token, expires_in=ttl)


@router.get("/events/stream")
async def sse_stream(request: Request, token: str = Query(...)):
    from fastapi.responses import StreamingResponse

    redis = _get_redis(request)
    if redis is None:
        async def error_gen():
            yield 'data: {"error": "redis unavailable"}\n\n'
        return StreamingResponse(error_gen(), media_type="text/event-stream")

    stored = redis.get(f"hermes:sse:token:{token}")
    if stored is None:
        async def invalid_gen():
            yield 'data: {"error": "invalid token"}\n\n'
        return StreamingResponse(invalid_gen(), media_type="text/event-stream")

    redis.delete(f"hermes:sse:token:{token}")

    async def event_generator():
        seq = 0
        try:
            while True:
                if await request.is_disconnected():
                    break
                seq += 1
                yield f"id: {seq}\nevent: heartbeat\ndata: {{}}\n\n"
                await asyncio.sleep(30)
        except asyncio.CancelledError:
            pass

    return StreamingResponse(event_generator(), media_type="text/event-stream")
