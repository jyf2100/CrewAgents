"""End-to-end swarm flow test with mocked Redis."""
import json
from unittest.mock import MagicMock

from swarm import (
    CircuitBreaker,
    ConnectionConfig,
    ResilientSwarmClient,
    SwarmClient,
    SwarmMode,
)


def test_full_delegation_flow():
    """Agent A registers, submits task to Agent B, B reads + executes, A gets result."""
    mock_redis = MagicMock()
    mock_redis.ping.return_value = True
    mock_redis.info.return_value = {
        "redis_version": "7.2",
        "used_memory": 100,
        "maxmemory": 400,
        "uptime_in_seconds": 100,
        "aof_enabled": 1,
        "connected_clients": 1,
    }
    mock_redis.hset.return_value = 1
    mock_redis.set.return_value = True
    mock_redis.xadd.return_value = "1000-0"
    mock_redis.publish.return_value = 1
    mock_redis.rpush.return_value = 1
    mock_redis.blpop.return_value = (
        "hermes:swarm:result:t-001",
        json.dumps({"status": "completed", "output": "LGTM"}),
    )

    # Agent A (sender)
    client_a = SwarmClient(
        agent_id=1,
        redis_client=mock_redis,
        capabilities=["supervision"],
        max_tasks=5,
    )
    client_a.register(display_name="Supervisor")

    # Submit task
    task_id = client_a.submit_task(
        target_agent_id=2, task_type="code-review", goal="Review main.py"
    )
    assert task_id is not None

    # Agent A waits for result
    result = client_a.wait_for_result(task_id, timeout=5)
    assert result is not None
    assert result["status"] == "completed"


def test_degradation_under_failure():
    """When Redis goes down, client degrades gracefully."""
    import redis as _redis

    mock_redis = MagicMock()
    mock_redis.hset.side_effect = _redis.ConnectionError("Connection refused")

    inner = SwarmClient(
        agent_id=5, redis_client=mock_redis, capabilities=["test"], max_tasks=1
    )
    degraded = MagicMock()
    rclient = ResilientSwarmClient(inner=inner, on_degrade=degraded)
    rclient.start()

    assert rclient.mode == SwarmMode.STANDALONE
    degraded.assert_called_once()

    # Submit returns None in standalone
    assert (
        rclient.submit_task(target_agent_id=1, task_type="test", goal="x") is None
    )
