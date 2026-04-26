"""Hermes Swarm Collaboration module."""

from .connection_config import ConnectionConfig, compute_pool_size
from .redis_connection import create_redis_pool
from .health import RedisHealth, check_redis_health
from .circuit_breaker import CircuitBreaker, CircuitState
from .reconnect import ReconnectPolicy, compute_backoff
from .exactly_once import ExactlyOnceGuard
from .messaging import SwarmMessaging
from .client import SwarmClient
from .resilient_client import ResilientSwarmClient, SwarmMode

__all__ = [
    "ConnectionConfig",
    "compute_pool_size",
    "create_redis_pool",
    "RedisHealth",
    "check_redis_health",
    "CircuitBreaker",
    "CircuitState",
    "ReconnectPolicy",
    "compute_backoff",
    "ExactlyOnceGuard",
    "SwarmMessaging",
    "SwarmClient",
    "ResilientSwarmClient",
    "SwarmMode",
]
