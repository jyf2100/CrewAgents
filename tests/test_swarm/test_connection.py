import pytest
from unittest.mock import patch, MagicMock

from swarm.connection_config import ConnectionConfig, compute_pool_size


def test_compute_pool_size_worker():
    cfg = ConnectionConfig(role="worker", max_concurrent_tasks=3)
    assert compute_pool_size(cfg) == 2 + 3  # base(2) + per_task(1)*3


def test_compute_pool_size_supervisor():
    cfg = ConnectionConfig(role="supervisor", max_concurrent_tasks=5)
    assert compute_pool_size(cfg) == 2 + 5 + 4  # base + tasks + supervisor_extra


def test_connection_config_defaults():
    cfg = ConnectionConfig(role="worker", max_concurrent_tasks=2)
    assert cfg.socket_timeout == 5.0
    assert cfg.socket_connect_timeout == 3.0
    assert cfg.retry_on_timeout is True
    assert cfg.health_check_interval == 15


def test_connection_config_rejects_invalid_role():
    with pytest.raises(ValueError):
        ConnectionConfig(role="invalid", max_concurrent_tasks=1)


# --- Task 3: Redis connection factory tests ---

from swarm.redis_connection import create_redis_pool


def test_create_redis_pool_standalone():
    cfg = ConnectionConfig(role="worker", max_concurrent_tasks=3)
    with patch("swarm.redis_connection.redis.Redis") as mock_redis_cls:
        mock_instance = MagicMock()
        mock_redis_cls.from_url.return_value = mock_instance
        pool = create_redis_pool("redis://localhost:6379/0", cfg)
        mock_redis_cls.from_url.assert_called_once()
        call_kwargs = mock_redis_cls.from_url.call_args[1]
        assert call_kwargs["max_connections"] == 5  # 2 + 3
        assert call_kwargs["socket_timeout"] == 5.0
        assert call_kwargs["decode_responses"] is True


def test_create_redis_pool_with_password():
    cfg = ConnectionConfig(role="worker", max_concurrent_tasks=2)
    with patch("swarm.redis_connection.redis.Redis") as mock_redis_cls:
        mock_redis_cls.from_url.return_value = MagicMock()
        create_redis_pool("redis://localhost:6379/0", cfg, password="s3cret")
        call_kwargs = mock_redis_cls.from_url.call_args[1]
        assert call_kwargs["password"] == "s3cret"
