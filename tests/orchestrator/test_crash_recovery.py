import time

import pytest
import redis as _redis

from hermes_orchestrator.models.task import Task
from hermes_orchestrator.stores.redis_agent_registry import RedisAgentRegistry
from hermes_orchestrator.stores.redis_task_store import RedisTaskStore


@pytest.fixture
def redis_client():
    r = _redis.Redis(host="localhost", port=6379, db=15, decode_responses=True)
    r.flushdb()
    yield r
    r.flushdb()
    r.close()


@pytest.mark.integration
def test_in_flight_tasks_requeued_on_startup(redis_client):
    store = RedisTaskStore(redis_client)
    registry = RedisAgentRegistry(redis_client)

    # Simulate tasks that were in-flight when orchestrator crashed
    for i, status in enumerate(["executing", "streaming", "assigned"]):
        t = Task(
            task_id=f"t-{status}",
            prompt="test",
            created_at=time.time(),
            status=status,
            assigned_agent="gw-1",
        )
        store.create(t)

    # Simulate a task that was done (should NOT be requeued)
    t_done = Task(
        task_id="t-done", prompt="done", created_at=time.time(), status="done"
    )
    store.create(t_done)

    # Run recovery
    from hermes_orchestrator.main import _recover_in_flight_tasks

    _recover_in_flight_tasks(store, registry)

    # In-flight tasks should be back to queued
    for status in ["executing", "streaming", "assigned"]:
        recovered = store.get(f"t-{status}")
        assert recovered is not None
        assert recovered.status == "queued"
        assert recovered.assigned_agent is None

    # Done task should remain done
    done = store.get("t-done")
    assert done.status == "done"
