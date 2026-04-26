import json
from unittest.mock import MagicMock, patch

from swarm.client import SwarmClient


def test_register_writes_registry():
    mock_redis = MagicMock()
    mock_redis.hset.return_value = 1
    client = SwarmClient(
        agent_id=3,
        redis_client=mock_redis,
        capabilities=["code-review"],
        max_tasks=3,
    )
    client.register(display_name="Agent-3")
    mock_redis.hset.assert_called()
    call_args = mock_redis.hset.call_args
    assert call_args[0][0] == "hermes:registry"
    # Verify the profile data includes capabilities
    profile_json = call_args[0][2]
    profile = json.loads(profile_json)
    assert profile["capabilities"] == ["code-review"]
    assert profile["display_name"] == "Agent-3"


def test_register_publishes_online_advisory():
    mock_redis = MagicMock()
    mock_redis.hset.return_value = 1
    client = SwarmClient(
        agent_id=3,
        redis_client=mock_redis,
        capabilities=["code-review"],
        max_tasks=3,
    )
    client.register(display_name="Agent-3")
    mock_redis.publish.assert_called_once()
    channel = mock_redis.publish.call_args[0][0]
    assert channel == "swarm.advisory.online"


def test_heartbeat_sets_key():
    mock_redis = MagicMock()
    client = SwarmClient(
        agent_id=3,
        redis_client=mock_redis,
        capabilities=[],
        max_tasks=1,
    )
    client.heartbeat()
    mock_redis.set.assert_called_once()
    key = mock_redis.set.call_args[0][0]
    assert "heartbeat" in key
    assert "3" in key
    # Verify TTL is set
    assert mock_redis.set.call_args[1]["ex"] == 60


def test_submit_task():
    mock_redis = MagicMock()
    client = SwarmClient(
        agent_id=1,
        redis_client=mock_redis,
        capabilities=[],
        max_tasks=3,
    )
    with patch.object(client, "_messaging") as mock_msg:
        mock_msg.publish_task.return_value = "msg-001"
        task_id = client.submit_task(
            target_agent_id=5, task_type="review", goal="Review code"
        )
        assert task_id is not None
        mock_msg.publish_task.assert_called_once()
        call_kwargs = mock_msg.publish_task.call_args[1]
        assert call_kwargs["target_agent_id"] == 5
        assert call_kwargs["task_type"] == "review"
        assert call_kwargs["goal"] == "Review code"
        assert call_kwargs["sender_id"] == 1


def test_wait_for_result():
    mock_redis = MagicMock()
    mock_redis.blpop.return_value = (
        "key",
        json.dumps({"status": "completed", "output": "ok"}),
    )
    client = SwarmClient(
        agent_id=1,
        redis_client=mock_redis,
        capabilities=[],
        max_tasks=3,
    )
    result = client.wait_for_result("task-1", timeout=5)
    assert result is not None
    assert result["status"] == "completed"
    mock_redis.blpop.assert_called_once()
    key = mock_redis.blpop.call_args[0][0]
    assert "result:task-1" in key


def test_wait_for_result_timeout():
    mock_redis = MagicMock()
    mock_redis.blpop.return_value = None
    client = SwarmClient(
        agent_id=1,
        redis_client=mock_redis,
        capabilities=[],
        max_tasks=3,
    )
    result = client.wait_for_result("task-1", timeout=5)
    assert result is None
