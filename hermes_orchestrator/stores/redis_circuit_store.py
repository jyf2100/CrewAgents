from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import redis as _redis

logger = logging.getLogger(__name__)


class RedisCircuitStore:
    """Redis-backed circuit breaker state store.

    All state transitions execute atomically via Lua scripts.
    Threshold parameters are passed per-call (not stored in Redis)
    so that config changes take effect immediately.
    """

    def __init__(
        self,
        redis_client: _redis.Redis,
        key_prefix: str = "hermes:orchestrator:circuits:",
        failure_threshold: int = 3,
        success_threshold: int = 2,
        recovery_timeout: float = 30.0,
        circuit_ttl: int = 3600,
    ):
        self._redis = redis_client
        self._key_prefix = key_prefix
        self._failure_threshold = failure_threshold
        self._success_threshold = success_threshold
        self._recovery_timeout = recovery_timeout
        self._circuit_ttl = circuit_ttl

        # Register Lua scripts for efficient server-side execution
        self._record_failure_script = redis_client.register_script(self._RECORD_FAILURE_LUA)
        self._record_success_script = redis_client.register_script(self._RECORD_SUCCESS_LUA)
        self._check_state_script = redis_client.register_script(self._CHECK_STATE_LUA)

    def _key(self, agent_id: str) -> str:
        return f"{self._key_prefix}{agent_id}"

    # ---- Lua scripts ----

    _RECORD_FAILURE_LUA = """
local key = KEYS[1]
local failure_threshold = tonumber(ARGV[1])
local now = tonumber(ARGV[2])
local circuit_ttl = tonumber(ARGV[3])

local state = redis.call('HGET', key, 'state') or 'closed'
local raw_fc = redis.call('HGET', key, 'failure_count')
local failure_count = tonumber(raw_fc) or 0

failure_count = failure_count + 1
redis.call('HSET', key, 'failure_count', failure_count)
redis.call('HSET', key, 'last_failure_ts', now)

if state == 'closed' then
    if failure_count >= failure_threshold then
        redis.call('HSET', key, 'state', 'open')
        state = 'open'
    end
elseif state == 'half_open' then
    redis.call('HSET', key, 'success_count', 0)
    redis.call('HSET', key, 'state', 'open')
    state = 'open'
end

redis.call('EXPIRE', key, circuit_ttl)
return {state, failure_count}
"""

    _RECORD_SUCCESS_LUA = """
local key = KEYS[1]
local success_threshold = tonumber(ARGV[1])
local now = tonumber(ARGV[2])
local recovery_timeout = tonumber(ARGV[3])
local circuit_ttl = tonumber(ARGV[4])

local exists = redis.call('EXISTS', key)

if exists == 0 then
    redis.call('HSET', key, 'state', 'closed')
    redis.call('HSET', key, 'failure_count', 0)
    redis.call('HSET', key, 'success_count', 0)
    redis.call('HSET', key, 'last_failure_ts', 0)
    redis.call('EXPIRE', key, circuit_ttl)
    return {'closed', 0, 0}
end

local state = redis.call('HGET', key, 'state') or 'closed'

if state == 'closed' then
    redis.call('HSET', key, 'failure_count', 0)
    redis.call('HSET', key, 'success_count', 0)
    redis.call('EXPIRE', key, circuit_ttl)
    return {'closed', 0, 0}
elseif state == 'open' then
    local last_fts = tonumber(redis.call('HGET', key, 'last_failure_ts')) or 0
    if now - last_fts >= recovery_timeout then
        redis.call('HSET', key, 'state', 'half_open')
        redis.call('HSET', key, 'success_count', 1)
        redis.call('EXPIRE', key, circuit_ttl)
        return {'half_open', 0, 1}
    else
        redis.call('EXPIRE', key, circuit_ttl)
        local fc = tonumber(redis.call('HGET', key, 'failure_count')) or 0
        return {'open', fc, 0}
    end
elseif state == 'half_open' then
    local raw_sc = redis.call('HGET', key, 'success_count')
    local success_count = tonumber(raw_sc) or 0
    success_count = success_count + 1
    redis.call('HSET', key, 'success_count', success_count)
    if success_count >= success_threshold then
        redis.call('HSET', key, 'state', 'closed')
        redis.call('HSET', key, 'failure_count', 0)
        redis.call('HSET', key, 'success_count', 0)
        redis.call('EXPIRE', key, circuit_ttl)
        return {'closed', 0, 0}
    else
        redis.call('EXPIRE', key, circuit_ttl)
        local fc = tonumber(redis.call('HGET', key, 'failure_count')) or 0
        return {'half_open', fc, success_count}
    end
end

redis.call('EXPIRE', key, circuit_ttl)
return {'closed', 0, 0}
"""

    _CHECK_STATE_LUA = """
local key = KEYS[1]
local exists = redis.call('EXISTS', key)
if exists == 0 then
    return {'closed', 0, 0, 0}
end
local state = redis.call('HGET', key, 'state') or 'closed'
local failure_count = tonumber(redis.call('HGET', key, 'failure_count')) or 0
local success_count = tonumber(redis.call('HGET', key, 'success_count')) or 0
local last_failure_ts = tonumber(redis.call('HGET', key, 'last_failure_ts')) or 0
return {state, failure_count, success_count, last_failure_ts}
"""

    # ---- Public API ----

    def record_failure(self, agent_id: str) -> tuple[str, int]:
        """Record a failed call. Returns (state, failure_count)."""
        try:
            now = time.time()
            result = self._record_failure_script(
                keys=[self._key(agent_id)],
                args=[str(self._failure_threshold), str(now), str(self._circuit_ttl)],
            )
            state, count = result[0], int(result[1])
            logger.debug("Circuit %s: record_failure -> state=%s count=%d", agent_id, state, count)
            return state, count
        except Exception:
            logger.warning("Circuit %s: record_failure Redis error, returning safe default", agent_id, exc_info=True)
            return ("closed", 0)

    def record_success(self, agent_id: str) -> tuple[str, int, int]:
        """Record a successful call. Returns (state, failure_count, success_count)."""
        try:
            now = time.time()
            result = self._record_success_script(
                keys=[self._key(agent_id)],
                args=[str(self._success_threshold), str(now), str(self._recovery_timeout), str(self._circuit_ttl)],
            )
            state, fc, sc = result[0], int(result[1]), int(result[2])
            logger.debug("Circuit %s: record_success -> state=%s fc=%d sc=%d", agent_id, state, fc, sc)
            return state, fc, sc
        except Exception:
            logger.warning("Circuit %s: record_success Redis error, returning safe default", agent_id, exc_info=True)
            return ("closed", 0, 0)

    def check_state(self, agent_id: str) -> tuple[str, int, int, float]:
        """Pure read: returns (state, failure_count, success_count, last_failure_ts)."""
        try:
            result = self._check_state_script(
                keys=[self._key(agent_id)],
                args=[],
            )
            return result[0], int(result[1]), int(result[2]), float(result[3])
        except Exception:
            logger.warning("Circuit %s: check_state Redis error, returning safe default", agent_id, exc_info=True)
            return ("closed", 0, 0, 0.0)

    def delete(self, agent_id: str) -> None:
        """Delete circuit state (called on agent deregistration)."""
        self._redis.delete(self._key(agent_id))
        logger.info("Deleted circuit state for agent %s", agent_id)
