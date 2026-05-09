import os
import time

import pytest
import redis as _redis

from hermes_orchestrator.models.task import Task
from hermes_orchestrator.stores.redis_agent_registry import RedisAgentRegistry
from hermes_orchestrator.stores.redis_task_store import RedisTaskStore


def _build_redis():
    url = os.environ.get("REDIS_URL")
    if url:
        return _redis.Redis.from_url(url, db=15, decode_responses=True)
    host = os.environ.get("REDIS_HOST", "localhost")
    port = int(os.environ.get("REDIS_PORT", "6379"))
    password = os.environ.get("REDIS_PASSWORD")
    return _redis.Redis(host=host, port=port, password=password, db=15, decode_responses=True)


@pytest.fixture
def redis_client():
    r = _build_redis()
    r.flushdb()
    yield r
    r.flushdb()
    r.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_in_flight_tasks_requeued_on_startup(redis_client):
    store = RedisTaskStore(redis_client)
    registry = RedisAgentRegistry(redis_client)

    # Simulate tasks that were in-flight when orchestrator crashed.
    # store.create() forces status="queued", so we must update afterwards.
    for i, status in enumerate(["executing", "streaming", "assigned"]):
        t = Task(
            task_id=f"t-{status}",
            prompt="test",
            created_at=time.time(),
            status=status,
            assigned_agent="gw-1",
        )
        store.create(t)
        store.update(f"t-{status}", status=status, assigned_agent="gw-1")

    # Simulate a task that was done (should NOT be requeued)
    t_done = Task(
        task_id="t-done", prompt="done", created_at=time.time(), status="done"
    )
    store.create(t_done)
    store.update("t-done", status="done")

    # Run recovery — _recover_in_flight_tasks now requires leader_election and recovery_epoch
    from unittest.mock import MagicMock, patch

    leader_election = MagicMock()
    leader_election.is_leader = True
    recovery_epoch = "test-recovery-001"

    # Set required env var before importing main (create_app reads it at module level)
    os.environ.setdefault("ORCHESTRATOR_API_KEY", "test-key-for-recovery")

    import hermes_orchestrator.main as main_mod

    # _recover_in_flight_tasks references main.redis_client for idempotency check
    with patch.object(main_mod, "redis_client", redis_client):
        from hermes_orchestrator.main import _recover_in_flight_tasks
        await _recover_in_flight_tasks(
            store, registry,
            leader_election=leader_election, recovery_epoch=recovery_epoch,
        )

    # In-flight tasks should be back to queued
    for status in ["executing", "streaming", "assigned"]:
        recovered = store.get(f"t-{status}")
        assert recovered is not None
        assert recovered.status == "queued"
        assert recovered.assigned_agent is None

    # Done task should remain done
    done = store.get("t-done")
    assert done.status == "done"
