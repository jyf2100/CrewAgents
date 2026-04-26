"""Tests for SwarmConsumer — background thread that consumes tasks from Redis Stream."""

import json
import time
import threading
from unittest.mock import MagicMock, call, patch

import pytest

from swarm.consumer import SwarmConsumer


def _make_consumer(**overrides):
    """Build a SwarmConsumer with mock redis and execute_fn."""
    defaults = {
        "agent_id": 7,
        "redis_client": MagicMock(),
        "execute_fn": MagicMock(return_value="done"),
    }
    defaults.update(overrides)
    return SwarmConsumer(**defaults)


def _make_xreadgroup_result(msg_id="12345-0", fields=None):
    """Build a fake XREADGROUP return value for one message."""
    if fields is None:
        fields = {
            "task_id": "t-001",
            "task_type": "code-review",
            "goal": "Review code",
            "input_data": "some input",
        }
    stream = "hermes:stream:agent.7.tasks"
    return [(stream, [(msg_id, fields)])]


# ── Test 1: reads from correct stream/group ──────────────────────────────


def test_consumer_reads_from_stream():
    """XREADGROUP is called with the correct stream and consumer group."""
    consumer = _make_consumer()
    consumer._redis.xreadgroup.return_value = []

    consumer._poll_once()

    consumer._redis.xreadgroup.assert_called_once()
    args = consumer._redis.xreadgroup.call_args
    group = args[0][0]
    consumer_name = args[0][1]
    stream_dict = args[0][2]

    assert group == "agent.7.worker"
    assert stream_dict == {"hermes:stream:agent.7.tasks": ">"}
    assert args[1]["count"] == 1
    assert args[1]["block"] == 5000


# ── Test 2: executes and acks ────────────────────────────────────────────


def test_consumer_executes_and_acks():
    """execute_fn is called with goal/input_data and XACK is called after."""
    consumer = _make_consumer()
    consumer._redis.exists.return_value = 0  # not cancelled
    consumer._redis.xreadgroup.return_value = _make_xreadgroup_result()

    consumer._poll_once()

    consumer._execute_fn.assert_called_once_with("Review code", "some input")
    consumer._redis.xack.assert_called_once_with(
        "hermes:stream:agent.7.tasks", "agent.7.worker", "12345-0"
    )


# ── Test 3: writes result to sender result key ───────────────────────────


def test_consumer_writes_result_to_sender_stream():
    """RPUSH writes JSON result to hermes:swarm:result:{task_id}."""
    consumer = _make_consumer()
    consumer._redis.exists.return_value = 0
    consumer._redis.xreadgroup.return_value = _make_xreadgroup_result()

    consumer._poll_once()

    rpush_calls = consumer._redis.rpush.call_args_list
    assert len(rpush_calls) == 1

    result_key = rpush_calls[0][0][0]
    assert result_key == "hermes:swarm:result:t-001"

    payload = json.loads(rpush_calls[0][0][1])
    assert payload["task_id"] == "t-001"
    assert payload["agent_id"] == 7
    assert payload["status"] == "completed"
    assert payload["output"] == "done"
    assert "duration_ms" in payload
    assert "timestamp" in payload

    # EXPIRE called on the result key
    consumer._redis.expire.assert_any_call("hermes:swarm:result:t-001", 300)


# ── Test 4: publishes task_started advisory ──────────────────────────────


def test_consumer_publishes_task_started_advisory():
    """First PUBLISH is swarm.advisory.task with event task_started."""
    consumer = _make_consumer()
    consumer._redis.exists.return_value = 0
    consumer._redis.xreadgroup.return_value = _make_xreadgroup_result()

    consumer._poll_once()

    publish_calls = consumer._redis.publish.call_args_list
    # First publish should be task_started
    first_publish = publish_calls[0]
    channel = first_publish[0][0]
    body = json.loads(first_publish[0][1])

    assert channel == "swarm.advisory.task"
    assert body["event"] == "task_started"
    assert body["task_id"] == "t-001"
    assert body["agent_id"] == 7
    assert body["task_type"] == "code-review"


# ── Test 5: skips cancelled task ─────────────────────────────────────────


def test_consumer_skips_cancelled_task():
    """If cancel key exists, execute_fn is NOT called but message is still ACK'd."""
    consumer = _make_consumer()
    consumer._redis.exists.return_value = 1  # cancelled
    consumer._redis.xreadgroup.return_value = _make_xreadgroup_result()

    consumer._poll_once()

    consumer._execute_fn.assert_not_called()
    # Still acked
    consumer._redis.xack.assert_called_once_with(
        "hermes:stream:agent.7.tasks", "agent.7.worker", "12345-0"
    )


# ── Test 6: graceful stop ───────────────────────────────────────────────


def test_consumer_graceful_stop():
    """stop() sets the event and run() exits cleanly."""
    consumer = _make_consumer()
    # Make poll block briefly so the loop can check the stop event
    consumer._redis.xreadgroup.return_value = []

    thread = threading.Thread(target=consumer.run, daemon=True)
    thread.start()

    # Give the thread a moment to enter the loop
    time.sleep(0.1)
    consumer.stop()
    thread.join(timeout=5)

    assert not thread.is_alive()


# ── Test 7: handles execution error ──────────────────────────────────────


def test_consumer_handles_execution_error():
    """If execute_fn raises, error result is written and message is ACK'd."""
    consumer = _make_consumer()
    consumer._redis.exists.return_value = 0
    consumer._redis.xreadgroup.return_value = _make_xreadgroup_result()
    consumer._execute_fn.side_effect = RuntimeError("boom")

    consumer._poll_once()

    # Should NOT raise — error is caught internally
    # Result written with status "failed"
    rpush_calls = consumer._redis.rpush.call_args_list
    assert len(rpush_calls) == 1

    payload = json.loads(rpush_calls[0][0][1])
    assert payload["status"] == "failed"
    assert payload["error"] == "boom"
    assert payload["task_id"] == "t-001"

    # publish advisory with task_failed
    publish_calls = consumer._redis.publish.call_args_list
    result_advisory = None
    for c in publish_calls:
        body = json.loads(c[0][1])
        if body.get("event") in ("task_completed", "task_failed"):
            result_advisory = body
            break
    assert result_advisory is not None
    assert result_advisory["event"] == "task_failed"

    # Still acked
    consumer._redis.xack.assert_called_once_with(
        "hermes:stream:agent.7.tasks", "agent.7.worker", "12345-0"
    )
