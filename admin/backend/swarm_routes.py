import logging
import hmac

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Request
import json
import time
import secrets
import asyncio
import concurrent.futures
import atexit

from swarm_models import (
    SwarmCapabilityResponse,
    SwarmAgentProfile,
    SwarmMetricsResponse,
    RedisHealthResponse,
    SSETokenResponse,
    CrewCreateRequest,
    CrewUpdateRequest,
    CrewResponse,
    CrewListResponse,
    CrewExecutionResponse,
    CrewAgentModel,
    WorkflowStepModel,
    WorkflowDefModel,
)
from swarm.health import check_redis_health
from swarm.crew_store import CrewStore
from swarm.workflow import WorkflowEngine
from swarm.router import SwarmRouter
from swarm.messaging import SwarmMessaging

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


def _get_crew_store(request: Request) -> CrewStore | None:
    redis = _get_redis(request)
    if redis is None:
        return None
    return CrewStore(redis)


_workflow_executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)


atexit.register(lambda: _workflow_executor.shutdown(wait=False))


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


# ---------------------------------------------------------------------------
# Crew CRUD
# ---------------------------------------------------------------------------


def _crew_to_response(c) -> CrewResponse:
    """Map internal CrewConfig dataclass to API response model."""
    return CrewResponse(
        crew_id=c.crew_id, name=c.name, description=c.description,
        agents=[CrewAgentModel(agent_id=a.agent_id,
                               required_capability=a.required_capability)
                for a in c.agents],
        workflow=WorkflowDefModel(
            type=c.workflow.type, timeout_seconds=c.workflow.timeout_seconds,
            steps=[WorkflowStepModel(
                id=s.id, required_capability=s.required_capability,
                task_template=s.task_template, depends_on=s.depends_on,
                input_from=s.input_from, timeout_seconds=s.timeout_seconds,
            ) for s in c.workflow.steps],
        ),
        created_at=c.created_at, updated_at=c.updated_at,
        created_by=c.created_by,
    )


@router.get("/crews", response_model=CrewListResponse, dependencies=[_auth])
async def list_crews(request: Request):
    store = _get_crew_store(request)
    if store is None:
        return CrewListResponse(results=[], total=0)
    crews = store.list_crews()
    results = [_crew_to_response(c) for c in crews]
    return CrewListResponse(results=results, total=len(results))


@router.post("/crews", response_model=CrewResponse, dependencies=[_auth])
async def create_crew(request: Request, body: CrewCreateRequest):
    store = _get_crew_store(request)
    if store is None:
        raise HTTPException(status_code=503, detail="Redis unavailable")
    from swarm.crew_store import CrewAgent as CrewAgentData
    from swarm.crew_store import WorkflowStep as StepData
    from swarm.crew_store import WorkflowDef as DefData
    crew = store.create(
        name=body.name,
        description=body.description,
        agents=[CrewAgentData(agent_id=a.agent_id,
                              required_capability=a.required_capability)
                for a in body.agents],
        workflow=DefData(
            type=body.workflow.type,
            steps=[StepData(
                id=s.id, required_capability=s.required_capability,
                task_template=s.task_template, depends_on=s.depends_on,
                input_from=s.input_from, timeout_seconds=s.timeout_seconds,
            ) for s in body.workflow.steps],
            timeout_seconds=body.workflow.timeout_seconds,
        ),
        created_by=body.created_by,
    )
    return _crew_to_response(crew)


@router.get("/crews/{crew_id}", response_model=CrewResponse | None,
             dependencies=[_auth])
async def get_crew(request: Request, crew_id: str = Path(..., pattern=r"^[a-zA-Z0-9_-]{1,64}$")):
    store = _get_crew_store(request)
    if store is None:
        raise HTTPException(status_code=503, detail="Redis unavailable")
    crew = store.get(crew_id)
    if crew is None:
        raise HTTPException(status_code=404, detail="Crew not found")
    return _crew_to_response(crew)


@router.put("/crews/{crew_id}", response_model=CrewResponse | None,
             dependencies=[_auth])
async def update_crew(request: Request, body: CrewUpdateRequest,
                      crew_id: str = Path(..., pattern=r"^[a-zA-Z0-9_-]{1,64}$")):
    store = _get_crew_store(request)
    if store is None:
        raise HTTPException(status_code=503, detail="Redis unavailable")
    updates: dict = {}
    if body.name is not None:
        updates["name"] = body.name
    if body.description is not None:
        updates["description"] = body.description
    if body.agents is not None:
        updates["agents"] = [
            {"agent_id": a.agent_id, "required_capability": a.required_capability}
            for a in body.agents
        ]
    if body.workflow is not None:
        updates["workflow"] = {
            "type": body.workflow.type,
            "steps": [
                {"id": s.id, "required_capability": s.required_capability,
                 "task_template": s.task_template, "depends_on": s.depends_on,
                 "input_from": s.input_from, "timeout_seconds": s.timeout_seconds}
                for s in body.workflow.steps
            ],
            "timeout_seconds": body.workflow.timeout_seconds,
        }
    crew = store.update(crew_id, updates)
    if crew is None:
        raise HTTPException(status_code=404, detail="Crew not found")
    return _crew_to_response(crew)


@router.delete("/crews/{crew_id}", dependencies=[_auth])
async def delete_crew(request: Request, crew_id: str = Path(..., pattern=r"^[a-zA-Z0-9_-]{1,64}$")):
    store = _get_crew_store(request)
    if store is None:
        raise HTTPException(status_code=503, detail="Redis unavailable")
    deleted = store.delete(crew_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Crew not found")
    return {"status": "deleted"}


@router.post("/crews/{crew_id}/execute", dependencies=[_auth])
async def execute_crew(request: Request, crew_id: str = Path(..., pattern=r"^[a-zA-Z0-9_-]{1,64}$")):
    redis = _get_redis(request)
    if redis is None:
        raise HTTPException(status_code=503, detail="Redis unavailable")
    store = _get_crew_store(request)
    crew = store.get(crew_id) if store else None
    if crew is None:
        raise HTTPException(status_code=404, detail="Crew not found")

    # Distributed lock — prevent concurrent execution of the same crew
    lock_key = f"hermes:crew_exec_lock:{crew_id}"
    import uuid as _uuid
    exec_id = str(_uuid.uuid4())
    acquired = redis.set(lock_key, exec_id, nx=True, ex=crew.workflow.timeout_seconds + 60)
    if not acquired:
        raise HTTPException(status_code=409, detail="Crew execution already in progress")

    def _run():
        try:
            router = SwarmRouter(redis)
            messaging = SwarmMessaging(redis)
            engine = WorkflowEngine(redis, router, messaging)
            execution = engine.execute(crew.workflow, crew_id=crew_id)
            # Persist result
            redis.hset(f"hermes:crew_exec:{execution.exec_id}", "data",
                       json.dumps({
                           "exec_id": execution.exec_id,
                           "crew_id": execution.crew_id,
                           "status": execution.status,
                           "step_results": {
                               sid: {"step_id": r.step_id, "status": r.status,
                                     "output": r.output, "error": r.error,
                                     "agent_id": r.agent_id, "duration_ms": r.duration_ms}
                               for sid, r in execution.step_results.items()
                           },
                           "error": execution.error,
                           "started_at": execution.started_at,
                           "finished_at": execution.finished_at,
                           "timeout_seconds": execution.timeout_seconds,
                       }))
            redis.expire(f"hermes:crew_exec:{execution.exec_id}", 3600)
        except Exception as exc:
            logger.exception("Crew execution failed for %s: %s", crew_id, exc)
            # Persist failure so polling endpoint can report it
            try:
                redis.hset(f"hermes:crew_exec:{exec_id}", "data",
                           json.dumps({
                               "exec_id": exec_id, "crew_id": crew_id,
                               "status": "failed", "step_results": {},
                               "error": f"Internal error: {exc}",
                               "started_at": time.monotonic(), "finished_at": time.monotonic(),
                               "timeout_seconds": crew.workflow.timeout_seconds,
                           }))
                redis.expire(f"hermes:crew_exec:{exec_id}", 3600)
            except Exception:
                logger.exception("Failed to persist crew execution error")
        finally:
            # Always release the lock
            try:
                redis.delete(lock_key)
            except Exception:
                logger.exception("Failed to release crew lock %s", lock_key)

    # H4: Reject if thread pool queue is overloaded
    if _workflow_executor._work_queue.qsize() >= 8:  # type: ignore[attr-defined]
        redis.delete(lock_key)
        raise HTTPException(status_code=429, detail="Maximum concurrent workflows reached. Try again later.")

    # C2: Write initial running state so polling endpoint can return it immediately
    redis.hset(f"hermes:crew_exec:{exec_id}", "data",
               json.dumps({
                   "exec_id": exec_id, "crew_id": crew_id,
                   "status": "pending", "step_results": {},
                   "error": None,
                   "started_at": time.time(), "finished_at": None,
                   "timeout_seconds": crew.workflow.timeout_seconds,
               }))
    redis.expire(f"hermes:crew_exec:{exec_id}", crew.workflow.timeout_seconds + 120)

    _workflow_executor.submit(_run)
    return {"exec_id": exec_id, "status": "pending"}


@router.get("/crews/{crew_id}/executions/{exec_id}",
             response_model=CrewExecutionResponse | None,
             dependencies=[_auth])
async def get_execution(request: Request, crew_id: str = Path(..., pattern=r"^[a-zA-Z0-9_-]{1,64}$"),
                        exec_id: str = Path(..., pattern=r"^[a-zA-Z0-9_-]{1,64}$")):
    redis = _get_redis(request)
    if redis is None:
        return None
    raw = redis.hget(f"hermes:crew_exec:{exec_id}", "data")
    if not raw:
        return None
    data = json.loads(raw)
    if data.get("crew_id") != crew_id:
        raise HTTPException(status_code=404, detail="Execution not found")
    return CrewExecutionResponse(**data)


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
