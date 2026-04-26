from __future__ import annotations

from dataclasses import dataclass

_VALID_ROLES = ("worker", "supervisor")


@dataclass(frozen=True)
class ConnectionConfig:
    """Configuration for Redis connection pool sizing and behavior."""

    role: str
    max_concurrent_tasks: int
    socket_timeout: float = 5.0
    socket_connect_timeout: float = 3.0
    retry_on_timeout: bool = True
    health_check_interval: int = 15

    def __post_init__(self):
        if self.role not in _VALID_ROLES:
            raise ValueError(
                f"Invalid role: {self.role!r}. Must be one of {_VALID_ROLES}"
            )


def compute_pool_size(cfg: ConnectionConfig) -> int:
    """Compute the Redis connection pool size based on role and task count."""
    base = 2
    per_task = 1
    pool = base + cfg.max_concurrent_tasks * per_task
    if cfg.role == "supervisor":
        pool += 4
    return pool
