from unittest.mock import MagicMock

from swarm.exactly_once import ExactlyOnceGuard


def test_dedup_allows_first():
    guard = ExactlyOnceGuard(dedup_ttl=300)
    mock_redis = MagicMock()
    mock_redis.set.return_value = True
    assert guard.acquire_dedup(mock_redis, "task-123", "agent-1") is True
    mock_redis.set.assert_called_once()
    call_kwargs = mock_redis.set.call_args
    assert call_kwargs[1]["nx"] is True
    assert call_kwargs[1]["ex"] == 300


def test_dedup_blocks_duplicate():
    guard = ExactlyOnceGuard(dedup_ttl=300)
    mock_redis = MagicMock()
    mock_redis.set.return_value = None
    assert guard.acquire_dedup(mock_redis, "task-123", "agent-1") is False


def test_execution_guard_allows_new():
    guard = ExactlyOnceGuard(exec_guard_ttl=600)
    mock_redis = MagicMock()
    mock_redis.set.return_value = True
    assert guard.begin_execution(mock_redis, "task-123", "agent-1") is True


def test_execution_guard_blocks_running():
    guard = ExactlyOnceGuard(exec_guard_ttl=600)
    mock_redis = MagicMock()
    mock_redis.set.return_value = None
    assert guard.begin_execution(mock_redis, "task-123", "agent-1") is False


def test_is_cancelled():
    guard = ExactlyOnceGuard(cancel_ttl=300)
    mock_redis = MagicMock()
    mock_redis.exists.return_value = 1
    assert guard.is_cancelled(mock_redis, "task-123") is True


def test_is_not_cancelled():
    guard = ExactlyOnceGuard(cancel_ttl=300)
    mock_redis = MagicMock()
    mock_redis.exists.return_value = 0
    assert guard.is_cancelled(mock_redis, "task-123") is False


def test_set_cancel():
    guard = ExactlyOnceGuard(cancel_ttl=300)
    mock_redis = MagicMock()
    guard.set_cancel(mock_redis, "task-123", "user requested")
    mock_redis.set.assert_called_once()
    call_args = mock_redis.set.call_args
    assert "cancel:task-123" in call_args[0][0]
    assert call_args[1]["ex"] == 300


def test_write_result():
    guard = ExactlyOnceGuard(result_ttl=300)
    mock_redis = MagicMock()
    guard.write_result(mock_redis, "task-123", '{"status": "done"}')
    mock_redis.rpush.assert_called_once()
    mock_redis.expire.assert_called_once()
    key = mock_redis.rpush.call_args[0][0]
    assert "result:task-123" in key


def test_send_to_dlq():
    guard = ExactlyOnceGuard()
    mock_redis = MagicMock()
    guard.send_to_dlq(mock_redis, "task-123", "agent-1", "timeout")
    mock_redis.xadd.assert_called_once()
    args = mock_redis.xadd.call_args
    assert args[0][0] == "hermes:stream:swarm.dlq"
    fields = args[0][1]
    assert fields["task_id"] == "task-123"
    assert fields["agent_id"] == "agent-1"
    assert fields["reason"] == "timeout"
