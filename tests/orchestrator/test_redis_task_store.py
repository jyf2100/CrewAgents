import json
import time

import pytest
import redis as _redis

from hermes_orchestrator.models.task import Task
from hermes_orchestrator.stores.redis_task_store import RedisTaskStore


@pytest.fixture
def redis_client():
    r = _redis.Redis(host="localhost", port=6379, db=15, decode_responses=True)
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
