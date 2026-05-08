from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from functools import partial

import redis as _redis
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware

from hermes_orchestrator import db
from hermes_orchestrator.config import OrchestratorConfig
from hermes_orchestrator.middleware.auth import create_auth_middleware
from hermes_orchestrator.models.api import (
    AgentHealthResponse,
    AgentListResponse,
    TaskSubmitRequest,
    TaskSubmitResponse,
    TaskStatusResponse,
)
from hermes_orchestrator.models.task import Task
from hermes_orchestrator.services.agent_discovery import AgentDiscoveryService
from hermes_orchestrator.services.agent_selector import AgentSelector
from hermes_orchestrator.services.health_monitor import HealthMonitor
from hermes_orchestrator.services.task_executor import TaskExecutor
from hermes_orchestrator.stores.redis_agent_registry import RedisAgentRegistry
from hermes_orchestrator.stores.redis_task_store import RedisTaskStore
from swarm.circuit_breaker import CircuitBreaker

logger = logging.getLogger(__name__)

config: OrchestratorConfig | None = None
redis_client: _redis.Redis | None = None
task_store: RedisTaskStore | None = None
agent_registry: RedisAgentRegistry | None = None
selector: AgentSelector | None = None
executor: TaskExecutor | None = None
discovery: AgentDiscoveryService | None = None
health_monitor: HealthMonitor | None = None
circuits: dict[str, CircuitBreaker] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    global config, redis_client, task_store, agent_registry, selector, executor
    global discovery, health_monitor, circuits

    config = app.state.config

    if config.database_url:
        await db.init_pool(config.database_url)
        config.database_url = ""
    else:
        logger.info("DATABASE_URL not set — metadata will use K8s annotation fallback")

    redis_client = _redis.Redis.from_url(config.redis_url, decode_responses=True)
    task_store = RedisTaskStore(redis_client)
    agent_registry = RedisAgentRegistry(redis_client)
    selector = AgentSelector()
    executor = TaskExecutor(config)
    discovery = AgentDiscoveryService(config)

    for a in agent_registry.list_agents():
        circuits[a.agent_id] = CircuitBreaker(
            failure_threshold=config.circuit_failure_threshold,
            success_threshold=config.circuit_success_threshold,
            recovery_timeout=config.circuit_recovery_timeout,
        )

    _recover_in_flight_tasks(task_store, agent_registry)

    health_monitor = HealthMonitor(config, agent_registry, circuits)
    health_task = asyncio.create_task(_run_health_monitor())
    worker_task = asyncio.create_task(_run_task_worker())
    discovery_task = asyncio.create_task(_run_discovery_loop())

    logger.info("Orchestrator started")
    yield

    health_monitor.stop()
    await db.close_pool()
    if discovery:
        await discovery.close()
    health_task.cancel()
    worker_task.cancel()
    discovery_task.cancel()
    redis_client.close()
    logger.info("Orchestrator shut down")


def create_app() -> FastAPI:
    cfg = OrchestratorConfig()
    logging.basicConfig(level=getattr(logging, cfg.log_level, logging.INFO))

    application = FastAPI(
        title="Hermes Orchestrator",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    # FIXED: correct tuple unpacking for middleware registration
    cls, kwargs = create_auth_middleware(cfg.api_key)
    application.add_middleware(cls, **kwargs)
    if cfg.cors_origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=cfg.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["Authorization", "Content-Type"],
        )
    application.state.config = cfg
    return application


app = create_app()


def _recover_in_flight_tasks(
    store: RedisTaskStore, registry: RedisAgentRegistry
) -> None:
    """Recover tasks that were in-flight when the orchestrator crashed."""
    in_flight = store.list_by_status(["assigned", "executing", "streaming"])
    for task in in_flight:
        store.update(task.task_id, status="queued", assigned_agent=None)
        logger.info(
            "Recovered task %s → queued (was %s)", task.task_id, task.status
        )


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    checks: dict = {"status": "ok"}
    if redis_client:
        try:
            redis_client.ping()
            checks["redis"] = "ok"
        except Exception:
            checks["redis"] = "error"
            checks["status"] = "degraded"
    return checks


# ---------------------------------------------------------------------------
# Task endpoints
# ---------------------------------------------------------------------------

@app.post("/api/v1/tasks", status_code=202)
async def submit_task(req: TaskSubmitRequest, response: Response):
    task = Task(
        task_id=str(uuid.uuid4()),
        prompt=req.prompt,
        instructions=req.instructions,
        model_id=req.model_id,
        priority=req.priority,
        timeout_seconds=req.timeout_seconds,
        max_retries=req.max_retries,
        callback_url=req.callback_url,
        metadata=req.metadata,
        required_tags=req.required_tags,
        domain=req.domain,
        preferred_tags=req.preferred_tags,
        created_at=time.time(),
    )
    task_store.create(task)
    task_store.enqueue(task)
    response.headers["Retry-After"] = "5"
    return TaskSubmitResponse(task_id=task.task_id, created_at=task.created_at)


@app.get("/api/v1/tasks/{task_id}")
async def get_task(task_id: str, response: Response):
    if not re.match(r'^[a-zA-Z0-9_-]+$', task_id):
        raise HTTPException(status_code=400, detail="Invalid task ID format")
    task = task_store.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    response.headers["Retry-After"] = "5"
    result_dict = None
    if task.result:
        result_dict = task.result.__dict__
    routing_info_dict = None
    if task.routing_info:
        routing_info_dict = task.routing_info.__dict__
    return TaskStatusResponse(
        task_id=task.task_id,
        status=task.status,
        assigned_agent=task.assigned_agent,
        run_id=task.run_id,
        result=result_dict,
        error=task.error,
        retry_count=task.retry_count,
        created_at=task.created_at,
        updated_at=task.updated_at,
        routing_info=routing_info_dict,
    )


@app.get("/api/v1/tasks")
async def list_tasks(status: str | None = None, limit: int = 50, offset: int = 0):
    if status:
        statuses = [status]
        tasks = task_store.list_by_status(statuses)
    else:
        tasks = task_store.list_by_status(
            ["queued", "assigned", "executing", "streaming", "done", "failed"]
        )
    return [
        TaskStatusResponse(
            task_id=t.task_id,
            status=t.status,
            assigned_agent=t.assigned_agent,
            run_id=t.run_id,
            created_at=t.created_at,
            updated_at=t.updated_at,
        )
        for t in tasks[offset : offset + limit]
    ]


@app.delete("/api/v1/tasks/{task_id}")
async def cancel_task(task_id: str):
    if not re.match(r'^[a-zA-Z0-9_-]+$', task_id):
        raise HTTPException(status_code=400, detail="Invalid task ID format")
    task = task_store.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status in ("done", "failed"):
        raise HTTPException(status_code=409, detail="Task already completed")
    if task.status not in ("queued", "assigned"):
        raise HTTPException(
            status_code=400,
            detail="Task is already executing and cannot be cancelled",
        )
    task_store.update(task_id, status="failed", error="Cancelled by user")
    return {"status": "cancelled", "task_id": task_id}


# ---------------------------------------------------------------------------
# Agent endpoints
# ---------------------------------------------------------------------------

@app.get("/api/v1/agents")
async def list_agents():
    agents = agent_registry.list_agents()
    return AgentListResponse(agents=[a.to_dict() for a in agents])


@app.get("/api/v1/agents/{agent_id}/health")
async def agent_health(agent_id: str):
    agent = agent_registry.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    circuit = circuits.get(agent_id)
    return AgentHealthResponse(
        agent_id=agent.agent_id,
        status=agent.status,
        circuit_state=circuit.state.name.lower() if circuit else "closed",
        current_load=agent.current_load,
        max_concurrent=agent.max_concurrent,
        last_health_check=agent.last_health_check,
    )


# ---------------------------------------------------------------------------
# Background workers
# ---------------------------------------------------------------------------

async def _run_task_worker():
    consumer = f"worker-{secrets.token_hex(4)}"
    loop = asyncio.get_event_loop()
    pending: set[asyncio.Task] = set()
    while True:
        try:
            result = await loop.run_in_executor(
                None,
                lambda: redis_client.xreadgroup(
                    "orchestrator.workers",
                    consumer,
                    {"hermes:orchestrator:tasks:stream": ">"},
                    count=1,
                    block=5000,
                ),
            )
            if not result:
                continue
            for _stream_name, messages in result:
                for msg_id, fields in messages:
                    task_id = fields["task_id"]
                    # ACK immediately to avoid crash-duplicate
                    await loop.run_in_executor(
                        None,
                        lambda mid=msg_id: redis_client.xack(
                            "hermes:orchestrator:tasks:stream",
                            "orchestrator.workers",
                            mid,
                        ),
                    )
                    # Dispatch concurrently
                    t = asyncio.create_task(_process_task_safe(task_id))
                    pending.add(t)
                    t.add_done_callback(pending.discard)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("Worker loop error: %s", e)
            await asyncio.sleep(5)


async def _process_task_safe(task_id: str):
    try:
        await _process_task(task_id)
    except Exception as e:
        logger.error("Task %s processing failed: %s", task_id, e)
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            partial(
                task_store.update,
                task_id,
                status="failed",
                error=str(e),
            ),
        )


async def _process_task(task_id: str):
    loop = asyncio.get_event_loop()
    task = await loop.run_in_executor(None, task_store.get, task_id)
    if not task:
        return
    agents = await loop.run_in_executor(None, agent_registry.list_agents)
    chosen, routing_info = selector.select(agents, task)
    if routing_info:
        await loop.run_in_executor(
            None,
            partial(task_store.update, task_id, routing_info=routing_info),
        )
    if not chosen:
        # Check if the routing info indicates we should requeue instead of failing
        should_requeue = routing_info and routing_info.requeue
        if should_requeue:
            current = await loop.run_in_executor(None, task_store.get, task_id)
            if current and current.retry_count < current.max_retries:
                new_count = current.retry_count + 1
                await loop.run_in_executor(
                    None,
                    partial(
                        task_store.update,
                        task_id,
                        status="queued",
                        assigned_agent=None,
                        retry_count=new_count,
                        error=None,
                    ),
                )
                requeued_task = await loop.run_in_executor(None, task_store.get, task_id)
                if requeued_task:
                    await loop.run_in_executor(None, task_store.enqueue, requeued_task)
                logger.info(
                    "Task %s re-queued (attempt %d/%d, required_tags unsatisfied)",
                    task_id, new_count, current.max_retries,
                )
                return
        await loop.run_in_executor(
            None,
            partial(
                task_store.update, task_id, status="failed", error="No available agent"
            ),
        )
        return
    await loop.run_in_executor(
        None,
        partial(task_store.update, task_id, status="assigned", assigned_agent=chosen.agent_id),
    )
    # Use atomic increment to prevent race condition on load counter
    load_increased = await loop.run_in_executor(
        None, agent_registry.atomic_increment_load, chosen.agent_id, chosen.max_concurrent
    )
    if not load_increased:
        logger.warning(
            "Task %s: agent %s was at capacity after atomic check, re-queuing",
            task_id, chosen.agent_id,
        )
        await loop.run_in_executor(
            None,
            partial(task_store.update, task_id, status="queued", assigned_agent=None),
        )
        requeued_task = await loop.run_in_executor(None, task_store.get, task_id)
        if requeued_task:
            await loop.run_in_executor(None, task_store.enqueue, requeued_task)
        return
    try:
        run_id = await executor.submit_run(
            chosen.gateway_url, task.prompt, task.instructions,
            headers=chosen.gateway_headers(),
        )
        await loop.run_in_executor(
            None, partial(task_store.update, task_id, status="executing", run_id=run_id)
        )
        await loop.run_in_executor(
            None, partial(task_store.update, task_id, status="streaming")
        )
        run_result = await executor.consume_run_events(
            chosen.gateway_url, run_id, task.timeout_seconds,
            headers=chosen.gateway_headers(),
        )
        if run_result.status == "completed":
            result = executor.extract_result(
                {
                    "output": run_result.output,
                    "usage": run_result.usage or {},
                    "run_id": run_id,
                },
                task,
            )
            await loop.run_in_executor(
                None, partial(task_store.update, task_id, status="done", result=result)
            )
            # Record success so circuit breaker can recover
            if chosen.agent_id in circuits:
                circuits[chosen.agent_id].record_success()
        else:
            await loop.run_in_executor(
                None,
                partial(
                    task_store.update,
                    task_id,
                    status="failed",
                    error=run_result.error or "Run failed",
                ),
            )
            circuits.setdefault(
                chosen.agent_id,
                CircuitBreaker(
                    failure_threshold=config.circuit_failure_threshold,
                    success_threshold=config.circuit_success_threshold,
                    recovery_timeout=config.circuit_recovery_timeout,
                ),
            ).record_failure()
    except Exception as e:
        current = await loop.run_in_executor(None, task_store.get, task_id)
        if current and current.retry_count < current.max_retries:
            new_count = current.retry_count + 1
            await loop.run_in_executor(
                None,
                partial(
                    task_store.update,
                    task_id,
                    status="queued",
                    assigned_agent=None,
                    run_id=None,
                    error=None,
                    retry_count=new_count,
                ),
            )
            requeued_task = await loop.run_in_executor(None, task_store.get, task_id)
            if requeued_task:
                await loop.run_in_executor(None, task_store.enqueue, requeued_task)
            logger.warning(
                "Task %s failed (attempt %d/%d), re-queued",
                task_id,
                new_count,
                current.max_retries,
            )
        else:
            await loop.run_in_executor(
                None, partial(task_store.update, task_id, status="failed", error=str(e))
            )
        circuits.setdefault(
            chosen.agent_id,
            CircuitBreaker(
                failure_threshold=config.circuit_failure_threshold,
                success_threshold=config.circuit_success_threshold,
                recovery_timeout=config.circuit_recovery_timeout,
            ),
        ).record_failure()
    finally:
        updated = await loop.run_in_executor(None, agent_registry.get, chosen.agent_id)
        if updated:
            await loop.run_in_executor(
                None,
                agent_registry.update_load,
                chosen.agent_id,
                max(0, updated.current_load - 1),
            )

    task = await loop.run_in_executor(None, task_store.get, task_id)
    if task and task.callback_url:
        asyncio.create_task(_send_callback(task))


async def _send_callback(task: Task):
    if not task.callback_url or not task.callback_url.startswith("https://"):
        return
    import aiohttp
    import hmac as _hmac
    import hashlib

    body = json.dumps(
        {
            "task_id": task.task_id,
            "status": task.status,
            "result": task.result.__dict__ if task.result else None,
        }
    )
    sig = _hmac.new(config.api_key.encode(), body.encode(), hashlib.sha256).hexdigest()
    headers = {
        "Content-Type": "application/json",
        "X-Hermes-Signature": f"sha256={sig}",
    }
    for attempt in range(3):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    task.callback_url,
                    data=body,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status < 500:
                        return
        except Exception as e:
            logger.warning("Callback attempt %d failed: %s", attempt + 1, e)
        await asyncio.sleep(2**attempt)


async def _run_discovery_loop():
    loop = asyncio.get_event_loop()
    while True:
        try:
            profiles = await discovery.discover_pods()
            existing_agents = await loop.run_in_executor(None, agent_registry.list_agents)
            existing = {a.agent_id for a in existing_agents}
            discovered = {p.agent_id for p in profiles}
            for p in profiles:
                is_new = p.agent_id not in existing
                await loop.run_in_executor(None, agent_registry.register, p)
                if is_new:
                    circuits[p.agent_id] = CircuitBreaker(
                        failure_threshold=config.circuit_failure_threshold,
                        success_threshold=config.circuit_success_threshold,
                        recovery_timeout=config.circuit_recovery_timeout,
                    )
            for gone in existing - discovered:
                await loop.run_in_executor(None, agent_registry.deregister, gone)
                circuits.pop(gone, None)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("Discovery loop error: %s", e)
        await asyncio.sleep(30)


async def _run_health_monitor():
    if health_monitor:
        await health_monitor.start()
