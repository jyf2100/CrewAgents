import pytest
from unittest.mock import MagicMock

from swarm.health import check_redis_health, RedisHealth


def test_check_redis_health_ok():
    mock_redis = MagicMock()
    mock_redis.ping.return_value = True
    mock_redis.info.return_value = {
        "redis_version": "7.2.0",
        "connected_clients": 5,
        "used_memory": 100_000_000,
        "maxmemory": 400_000_000,
        "uptime_in_seconds": 86400,
        "aof_enabled": 1,
    }
    health = check_redis_health(mock_redis)
    assert isinstance(health, RedisHealth)
    assert health.connected is True
    assert health.latency_ms >= 0
    assert health.memory_used_percent == pytest.approx(25.0)
    assert health.aof_enabled is True


def test_check_redis_health_unreachable():
    import redis as _redis

    mock_redis = MagicMock()
    mock_redis.ping.side_effect = _redis.ConnectionError("refused")
    health = check_redis_health(mock_redis)
    assert health.connected is False
