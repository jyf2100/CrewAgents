from __future__ import annotations

import redis

from .connection_config import ConnectionConfig, compute_pool_size


def create_redis_pool(
    url: str,
    cfg: ConnectionConfig,
    password: str | None = None,
) -> redis.Redis:
    """Create a Redis connection pool configured from a ConnectionConfig."""
    return redis.Redis.from_url(
        url,
        password=password,
        max_connections=compute_pool_size(cfg),
        socket_timeout=cfg.socket_timeout,
        socket_connect_timeout=cfg.socket_connect_timeout,
        retry_on_timeout=cfg.retry_on_timeout,
        health_check_interval=cfg.health_check_interval,
        decode_responses=True,
    )
