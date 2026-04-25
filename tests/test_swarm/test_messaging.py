import json
from unittest.mock import MagicMock

from swarm.messaging import SwarmMessaging


def test_publish_task():
    msg = SwarmMessaging(redis_client=MagicMock())
    msg._redis.xadd.return_value = "1234567890-0"
    msg._redis.publish.return_value = 1

    msg.publish_task(
        target_agent_id=3,
        task_id="t-001",
        task_type="code-review",
        goal="Review agent_manager.py",
        sender_id=1,
    )

    msg._redis.xadd.assert_called_once()
    stream_name = msg._redis.xadd.call_args[0][0]
    assert stream_name == "hermes:stream:agent.3.tasks"

    msg._redis.publish.assert_called_once()
    channel = msg._redis.publish.call_args[0][0]
    assert channel == "swarm.advisory.task"


def test_publish_task_fields():
    msg = SwarmMessaging(redis_client=MagicMock())
    msg._redis.xadd.return_value = "1234567890-0"
    msg._redis.publish.return_value = 1

    msg.publish_task(
        target_agent_id=3,
        task_id="t-001",
        task_type="code-review",
        goal="Review code",
        sender_id=1,
    )

    fields = msg._redis.xadd.call_args[0][1]
    assert fields["task_id"] == "t-001"
    assert fields["task_type"] == "code-review"
    assert fields["goal"] == "Review code"
    assert fields["sender_id"] == "1"


def test_read_task():
    mock_redis = MagicMock()
    mock_redis.xreadgroup.return_value = [
        (
            "hermes:stream:agent.3.tasks",
            [("12345-0", {"task_id": "t-001", "goal": "test"})],
        )
    ]
    msg = SwarmMessaging(redis_client=mock_redis)
    messages = msg.read_task(agent_id=3, consumer="c-1", block_ms=1000)
    assert len(messages) == 1
    assert messages[0]["task_id"] == "t-001"
    assert messages[0]["_msg_id"] == "12345-0"


def test_read_task_empty():
    mock_redis = MagicMock()
    mock_redis.xreadgroup.return_value = []
    msg = SwarmMessaging(redis_client=mock_redis)
    messages = msg.read_task(agent_id=3, consumer="c-1", block_ms=1000)
    assert len(messages) == 0


def test_ack_task():
    mock_redis = MagicMock()
    msg = SwarmMessaging(redis_client=mock_redis)
    msg.ack_task(agent_id=3, group="agent.3.worker", msg_id="12345-0")
    mock_redis.xack.assert_called_once_with(
        "hermes:stream:agent.3.tasks", "agent.3.worker", "12345-0"
    )


def test_reclaim_task():
    mock_redis = MagicMock()
    mock_redis.xpending_range.return_value = [
        {"message_id": "123-0", "idle": 200000}
    ]
    mock_redis.xclaim.return_value = [("123-0", {"task_id": "t-old"})]
    msg = SwarmMessaging(redis_client=mock_redis)
    reclaimed = msg.reclaim_tasks(agent_id=3, min_idle_ms=180000, consumer="supervisor-1")
    assert len(reclaimed) == 1
    assert reclaimed[0][0] == "123-0"


def test_reclaim_task_none_pending():
    mock_redis = MagicMock()
    mock_redis.xpending_range.return_value = []
    msg = SwarmMessaging(redis_client=mock_redis)
    reclaimed = msg.reclaim_tasks(agent_id=3, min_idle_ms=180000, consumer="supervisor-1")
    assert reclaimed == []
