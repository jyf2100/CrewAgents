from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import redis as _redis

logger = logging.getLogger(__name__)

LEADER_KEY = "hermes:orchestrator:leader"
FENCING_KEY = "hermes:orchestrator:leader:fencing"

_RENEW_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    redis.call('EXPIRE', KEYS[1], tonumber(ARGV[2]))
    return 1
end
return 0
"""

_STEP_DOWN_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""


class LeaderElection:
    """Redis-based leader election using SET NX EX."""

    def __init__(
        self,
        redis_client: _redis.Redis,
        identity: str,
        ttl: int = 30,
        renew_interval: float = 10.0,
    ):
        self._redis = redis_client
        self._identity = identity
        self._ttl = ttl
        self._renew_interval = renew_interval
        self._is_leader = False
        self._fencing_token = 0
        self._renew_task: asyncio.Task | None = None
        self._acquire_task: asyncio.Task | None = None
        self._on_become_leader = None

    @property
    def identity(self) -> str:
        return self._identity

    @property
    def is_leader(self) -> bool:
        return self._is_leader

    @property
    def fencing_token(self) -> int:
        return self._fencing_token

    def try_acquire(self) -> bool:
        """Attempt to acquire leadership atomically via SET NX EX."""
        acquired = self._redis.set(LEADER_KEY, self._identity, nx=True, ex=self._ttl)
        if acquired:
            self._is_leader = True
            self._fencing_token = self._redis.incr(FENCING_KEY)
            logger.info(
                "Acquired leadership (identity=%s, fencing_token=%d)",
                self._identity, self._fencing_token,
            )
        return bool(acquired)

    def renew(self) -> bool:
        """Renew leadership lease via Lua compare-and-set. Returns False if lost."""
        renewed = self._redis.eval(
            _RENEW_LUA, 1, LEADER_KEY, self._identity, str(self._ttl),
        )
        if not renewed:
            self._is_leader = False
            logger.warning("Leadership renewal failed — another instance took over")
        return bool(renewed)

    async def step_down(self) -> None:
        """Release leadership via Lua compare-and-delete."""
        try:
            self._redis.eval(_STEP_DOWN_LUA, 1, LEADER_KEY, self._identity)
        except Exception:
            logger.warning("Failed to step down from leadership: Redis unavailable")
        was_leader = self._is_leader
        self._is_leader = False
        if self._renew_task:
            self._renew_task.cancel()
            try:
                await self._renew_task
            except asyncio.CancelledError:
                pass
            self._renew_task = None
        if was_leader:
            logger.info("Stepped down from leadership (identity=%s)", self._identity)

    async def start_renew_loop(self) -> None:
        """Start the background renewal loop."""
        self._renew_task = asyncio.create_task(self._renew_loop())

    async def start_acquire_loop(self, on_become_leader=None) -> None:
        """Background loop for non-leaders to periodically attempt acquiring leadership."""
        self._on_become_leader = on_become_leader
        self._acquire_task = asyncio.create_task(self._acquire_loop())

    async def _renew_loop(self) -> None:
        """Periodically renew the leader lease. Stops on failure or cancellation."""
        try:
            while self._is_leader:
                if not self.renew():
                    return
                await asyncio.sleep(self._renew_interval)
        except asyncio.CancelledError:
            self._is_leader = False
            return

    async def _acquire_loop(self) -> None:
        """Periodically attempt to acquire leadership until successful."""
        interval = max(self._ttl / 3, 5.0)
        while not self._is_leader:
            await asyncio.sleep(interval)
            if self.try_acquire():
                if self._on_become_leader:
                    await self._on_become_leader()
                return
