from __future__ import annotations

import time
from dataclasses import dataclass

import redis as _redis


@dataclass(frozen=True)
class RedisHealth:
    """Snapshot of Redis server health."""

    connected: bool
    latency_ms: float = -1.0
    memory_used_percent: float = 0.0
    connected_clients: int = 0
    uptime_seconds: int = 0
    aof_enabled: bool = False
    version: str = ""
    error: str = ""


def check_redis_health(r: _redis.Redis) -> RedisHealth:
    """Ping Redis and collect server info. Returns a RedisHealth snapshot."""
    try:
        start = time.monotonic()
        r.ping()
        latency = (time.monotonic() - start) * 1000

        info = r.info()
        maxmem = info.get("maxmemory", 0) or 1
        used = info.get("used_memory", 0)

        return RedisHealth(
            connected=True,
            latency_ms=round(latency, 2),
            memory_used_percent=round(used / maxmem * 100, 1),
            connected_clients=info.get("connected_clients", 0),
            uptime_seconds=info.get("uptime_in_seconds", 0),
            aof_enabled=bool(info.get("aof_enabled", 0)),
            version=info.get("redis_version", "unknown"),
        )
    except (_redis.ConnectionError, _redis.TimeoutError) as exc:
        return RedisHealth(connected=False, error=str(exc))
