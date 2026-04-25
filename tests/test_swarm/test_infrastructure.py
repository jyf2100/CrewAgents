"""Infrastructure integration test — validates full connection setup with mocked Redis."""
import pytest
from unittest.mock import patch, MagicMock
from swarm.connection_config import ConnectionConfig
from swarm.redis_connection import create_redis_pool
from swarm.health import check_redis_health


def test_full_connection_health_flow():
    """Simulate: create pool → ping → check health."""
    cfg = ConnectionConfig(role="worker", max_concurrent_tasks=3)

    with patch("swarm.redis_connection.redis.Redis") as mock_cls:
        mock_redis = MagicMock()
        mock_cls.from_url.return_value = mock_redis
        mock_redis.ping.return_value = True
        mock_redis.info.return_value = {
            "redis_version": "7.2.0",
            "connected_clients": 5,
            "used_memory": 100_000_000,
            "maxmemory": 400_000_000,
            "uptime_in_seconds": 86400,
            "aof_enabled": 1,
        }

        pool = create_redis_pool("redis://hermes-redis:6379/0", cfg, password="test")
        health = check_redis_health(pool)

        assert health.connected is True
        assert health.memory_used_percent == pytest.approx(25.0)
