import json
import os
import time

import pytest
import redis as _redis

from hermes_orchestrator.models.task import Task, RoutingInfo, TaskResult
from hermes_orchestrator.stores.redis_task_store import RedisTaskStore


def _build_redis_kwargs():
    url = os.environ.get("REDIS_URL")
    if url:
        return {"url": url, "db": 15, "decode_responses": True}
    host = os.environ.get("REDIS_HOST", "localhost")
    port = int(os.environ.get("REDIS_PORT", "6379"))
    password = os.environ.get("REDIS_PASSWORD")
    return {"host": host, "port": port, "db": 15, "password": password, "decode_responses": True}


@pytest.fixture
def redis_client():
    kwargs = _build_redis_kwargs()
    r = _redis.Redis(**kwargs)
    r.flushdb()
    yield r
    r.flushdb()
    r.close()


@pytest.fixture
def store(redis_client):
    return RedisTaskStore(redis_client)


STREAM = "hermes:orchestrator:tasks:stream"


def test_create_and_get(store, redis_client):
    t = Task(task_id="t1", prompt="hello", created_at=time.time())
    store.create(t)
    # create() does NOT mutate the original task
    assert t.status == "submitted"
    got = store.get("t1")
    assert got is not None
    assert got.task_id == "t1"
    assert got.prompt == "hello"
    assert got.status == "queued"


def test_enqueue_adds_to_stream(store, redis_client):
    t = Task(
        task_id="t2", prompt="world", created_at=time.time(), status="submitted"
    )
    store.create(t)
    store.enqueue(t)
    msgs = redis_client.xrange(STREAM)
    assert len(msgs) >= 1
    found = False
    for msg_id, fields in msgs:
        if fields.get("task_id") == "t2":
            found = True
    assert found


def test_update_status(store):
    t = Task(task_id="t3", prompt="test", created_at=time.time())
    store.create(t)
    store.update("t3", status="executing", assigned_agent="gw-1")
    got = store.get("t3")
    assert got.status == "executing"
    assert got.assigned_agent == "gw-1"


def test_update_with_result(store):
    from hermes_orchestrator.models.task import TaskResult

    t = Task(task_id="t4", prompt="test", created_at=time.time())
    store.create(t)
    result = TaskResult(
        content="answer",
        usage={"total_tokens": 50},
        duration_seconds=1.0,
        run_id="run_1",
    )
    store.update("t4", status="done", result=result)
    got = store.get("t4")
    assert got.status == "done"
    assert got.result.content == "answer"


def test_list_by_status(store):
    for i in range(5):
        t = Task(task_id=f"t{i}", prompt=f"p{i}", created_at=time.time())
        store.create(t)
    store.update("t0", status="done")
    store.update("t1", status="failed")
    done = store.list_by_status(["done"])
    assert len(done) == 1
    assert done[0].task_id == "t0"
    failed_and_done = store.list_by_status(["done", "failed"])
    assert len(failed_and_done) == 2


def test_get_nonexistent(store):
    assert store.get("nope") is None


def test_delete(store, redis_client):
    t = Task(task_id="t_del", prompt="bye", created_at=time.time())
    store.create(t)
    store.delete("t_del")
    assert store.get("t_del") is None


# ===================================================================
# routing_info persistence
# ===================================================================


def test_update_with_routing_info(store):
    """RoutingInfo can be stored and retrieved via update()."""
    t = Task(task_id="t-routing", prompt="test", created_at=time.time())
    store.create(t)

    info = RoutingInfo(
        strategy="tag_match",
        chosen_agent_id="agent-1",
        scores={"agent-1": 0.75, "agent-2": 0.5},
        matched_tags=["python", "code"],
        fallback=False,
        reason="Best tag match",
    )
    store.update("t-routing", routing_info=info)

    got = store.get("t-routing")
    assert got.routing_info is not None
    assert got.routing_info.strategy == "tag_match"
    assert got.routing_info.chosen_agent_id == "agent-1"
    assert got.routing_info.matched_tags == ["python", "code"]
    assert got.routing_info.scores == {"agent-1": 0.75, "agent-2": 0.5}
    assert got.routing_info.fallback is False
    assert got.routing_info.reason == "Best tag match"


def test_create_task_with_routing_info(store):
    """Task created with routing_info survives store roundtrip."""
    info = RoutingInfo(
        strategy="least_load",
        chosen_agent_id="a1",
        scores={"a1": 0.0, "a2": 0.0},
        matched_tags=[],
        fallback=True,
        reason="No tags matched",
    )
    t = Task(
        task_id="t-pre-routing",
        prompt="test",
        created_at=time.time(),
        routing_info=info,
    )
    store.create(t)
    got = store.get("t-pre-routing")
    assert got.routing_info is not None
    assert got.routing_info.strategy == "least_load"
    assert got.routing_info.fallback is True


def test_update_routing_info_preserves_other_fields(store):
    """Updating routing_info does not clobber status or assigned_agent."""
    t = Task(task_id="t-preserve", prompt="test", created_at=time.time())
    store.create(t)
    store.update("t-preserve", status="executing", assigned_agent="gw-1")

    info = RoutingInfo(
        strategy="tag_match",
        chosen_agent_id="gw-1",
        scores={"gw-1": 0.8},
        matched_tags=["python"],
        fallback=False,
        reason="Tag match",
    )
    store.update("t-preserve", routing_info=info)

    got = store.get("t-preserve")
    assert got.status == "executing"
    assert got.assigned_agent == "gw-1"
    assert got.routing_info is not None
    assert got.routing_info.strategy == "tag_match"


def test_update_routing_info_with_result_together(store):
    """Routing info and result can both be updated in one call."""
    t = Task(task_id="t-both", prompt="test", created_at=time.time())
    store.create(t)

    info = RoutingInfo(
        strategy="tag_match",
        chosen_agent_id="a1",
        scores={"a1": 0.9},
        matched_tags=["code"],
        fallback=False,
        reason="Matched",
    )
    result = TaskResult(
        content="answer",
        usage={"total_tokens": 50},
        duration_seconds=1.0,
        run_id="run_1",
    )
    store.update("t-both", status="done", result=result, routing_info=info)

    got = store.get("t-both")
    assert got.status == "done"
    assert got.result.content == "answer"
    assert got.routing_info.strategy == "tag_match"
    assert got.routing_info.matched_tags == ["code"]
