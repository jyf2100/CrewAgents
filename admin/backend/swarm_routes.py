import logging
import hmac

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
import json
import time
import secrets
import asyncio
import concurrent.futures

from swarm_models import (
    SwarmCapabilityResponse,
    SwarmAgentProfile,
    SwarmMetricsResponse,
    RedisHealthResponse,
    SwarmTaskResponse,
    SSETokenResponse,
)
from swarm.health import check_redis_health

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Auth — reads the active admin key from app.state so that key rotation in
# main.py (update_admin_key) is immediately effective here too.
# ---------------------------------------------------------------------------


async def _verify_swarm_admin_key(
    x_admin_key: str = Header(..., alias="X-Admin-Key"),
    request: Request = None,
) -> bool:
    """Verify the request carries the correct admin key."""
    admin_key = getattr(request.app.state, "admin_key", "")
    if not admin_key:
        return True
    if not hmac.compare_digest(x_admin_key, admin_key):
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
                capabilities=profile.get("capabilities", [])
                if isinstance(profile.get("capabilities"), str)
                else profile.get("capabilities", []),
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


@router.get("/tasks", response_model=list[SwarmTaskResponse], dependencies=[_auth])
async def get_swarm_tasks(request: Request):
    redis = _get_redis(request)
    if redis is None:
        return []
    now_ms = time.time() * 1000
    cutoff_ms = now_ms - 300_000  # last 5 minutes
    raw = redis.zrangebyscore("hermes:swarm:tasks", cutoff_ms, now_ms)
    tasks = []
    for entry in raw:
        try:
            tasks.append(SwarmTaskResponse(**json.loads(entry)))
        except (json.JSONDecodeError, ValueError):
            continue
    return list(reversed(tasks))


@router.get("/tasks/{task_id}", response_model=SwarmTaskResponse | None, dependencies=[_auth])
async def get_swarm_task(request: Request, task_id: str):
    redis = _get_redis(request)
    if redis is None:
        return None
    # Scan sorted set for matching task_id
    now_ms = time.time() * 1000
    raw = redis.zrangebyscore("hermes:swarm:tasks", now_ms - 300_000, now_ms)
    for entry in raw:
        try:
            data = json.loads(entry)
            if data.get("task_id") == task_id:
                return SwarmTaskResponse(**data)
        except (json.JSONDecodeError, ValueError):
            continue
    return None


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


def _advisory_channel_to_event(channel: str, data: str) -> str:
    """Map Redis Pub/Sub channel + data to SSE event type."""
    try:
        parsed = json.loads(data)
        if "event" in parsed:
            return parsed["event"]
    except (json.JSONDecodeError, TypeError):
        pass
    mapping = {
        "swarm.advisory.task": "task_created",
        "swarm.advisory.result": "task_completed",
        "swarm.advisory.online": "agent_online",
        "swarm.advisory.offline": "agent_offline",
    }
    return mapping.get(channel, "message")


@router.get("/events/stream")
async def sse_stream(request: Request, token: str = Query(...)):
    from fastapi.responses import StreamingResponse

    redis = _get_redis(request)
    if redis is None:
        async def error_gen():
            yield 'data: {"error": "redis unavailable"}\n\n'
        return StreamingResponse(error_gen(), media_type="text/event-stream")

    # Atomic get-and-delete to prevent token replay
    lua_getdel = redis.register_script(
        'local v = redis.call("GET", KEYS[1]); redis.call("DEL", KEYS[1]); return v'
    )
    stored = lua_getdel(keys=[f"hermes:sse:token:{token}"])
    if stored is None:
        async def invalid_gen():
            yield 'data: {"error": "invalid token"}\n\n'
        return StreamingResponse(invalid_gen(), media_type="text/event-stream")

    async def event_generator():
        advisory_channels = (
            "swarm.advisory.task",
            "swarm.advisory.result",
            "swarm.advisory.online",
            "swarm.advisory.offline",
        )
        pubsub = redis.pubsub()
        seq = 0
        idle_ticks = 0
        loop = asyncio.get_running_loop()
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        try:
            pubsub.subscribe(*advisory_channels)
            while True:
                if await request.is_disconnected():
                    break
                msg = await loop.run_in_executor(executor, pubsub.get_message, 1.0)
                if msg and msg.get("type") == "message":
                    channel = msg.get("channel", "")
                    if isinstance(channel, bytes):
                        channel = channel.decode("utf-8", errors="replace")
                    data = msg.get("data", "")
                    if isinstance(data, bytes):
                        data = data.decode("utf-8", errors="replace")
                    event_type = _advisory_channel_to_event(channel, data)
                    seq += 1
                    yield f"id: {seq}\nevent: {event_type}\ndata: {data}\n\n"
                    idle_ticks = 0
                else:
                    idle_ticks += 1
                    if idle_ticks >= 5:
                        seq += 1
                        yield f"id: {seq}\nevent: heartbeat\ndata: {{}}\n\n"
                        idle_ticks = 0
        except asyncio.CancelledError:
            pass
        finally:
            try:
                pubsub.unsubscribe()
                pubsub.close()
            except Exception:
                pass
            executor.shutdown(wait=False)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
