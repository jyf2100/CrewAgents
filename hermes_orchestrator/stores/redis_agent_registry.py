from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import redis as _redis

from hermes_orchestrator.models.agent import AgentProfile

logger = logging.getLogger(__name__)

AGENTS_KEY = "hermes:orchestrator:agents"

_ALLOWED_FIELDS = {"status", "circuit_state", "current_load"}
_EXPECTED_TYPES: dict[str, type] = {
    "status": str,
    "circuit_state": str,
    "current_load": int,
}


class RedisAgentRegistry:
    def __init__(self, redis_client: _redis.Redis):
        self._redis = redis_client

    def register(self, agent: AgentProfile) -> None:
        self._redis.hset(AGENTS_KEY, agent.agent_id, json.dumps(agent.to_dict()))
        logger.info("Registered agent %s at %s", agent.agent_id, agent.gateway_url)

    def get(self, agent_id: str) -> AgentProfile | None:
        data = self._redis.hget(AGENTS_KEY, agent_id)
        if not data:
            return None
        return AgentProfile.from_dict(json.loads(data))

    # -- Lua scripts for atomic operations ----------------------------------

    # Atomic load increment with capacity check.
    # Returns the new load (> 0) on success, or 0 if at capacity / not found.
    _ATOMIC_INCR_LUA = """
    local key = KEYS[1]
    local field = ARGV[1]
    local max_load = tonumber(ARGV[2])
    local data = redis.call('HGET', key, field)
    if not data then return 0 end
    local ok, agent = pcall(cjson.decode, data)
    if not ok then return 0 end
    local current = tonumber(agent['current_load']) or 0
    local max_c = tonumber(agent['max_concurrent']) or max_load
    if current >= max_c then return 0 end
    local new_load = math.floor(current + 1)
    agent['current_load'] = new_load
    redis.call('HSET', key, field, cjson.encode(agent))
    return new_load
    """

    # Atomic load decrement.
    # Returns the new load (>= 0), or -1 if the agent does not exist.
    _ATOMIC_DECR_LUA = """
    local key = KEYS[1]
    local field = ARGV[1]
    local data = redis.call('HGET', key, field)
    if not data then return -1 end
    local ok, agent = pcall(cjson.decode, data)
    if not ok then return redis.error_reply('ERR corrupt JSON') end
    local current = tonumber(agent['current_load']) or 0
    if current <= 0 then return 0 end
    local new_load = math.floor(current - 1)
    agent['current_load'] = new_load
    redis.call('HSET', key, field, cjson.encode(agent))
    return new_load
    """

    # Atomic set on a whitelisted field inside the agent JSON hash value.
    # KEYS[1]  = hash key (AGENTS_KEY)
    # ARGV[1]  = agent_id (hash field)
    # ARGV[2]  = field name (must be in whitelist)
    # ARGV[3]  = JSON-encoded new value
    # Returns 1 on success, 0 if agent not found.
    _ATOMIC_SET_FIELD_LUA = """
    local allowed = { status = true, circuit_state = true, current_load = true }
    if not allowed[ARGV[2]] then
        return redis.error_reply('ERR field not whitelisted: ' .. ARGV[2])
    end
    local ok_val, value = pcall(cjson.decode, ARGV[3])
    if not ok_val then return redis.error_reply('ERR invalid JSON in ARGV[3]') end
    -- Coerce numeric fields to integers to avoid float pollution
    if ARGV[2] == 'current_load' then
        value = math.floor(tonumber(value) or 0)
    end
    local data = redis.call('HGET', KEYS[1], ARGV[1])
    if not data then return 0 end
    local ok_agent, agent = pcall(cjson.decode, data)
    if not ok_agent then return redis.error_reply('ERR corrupt JSON') end
    agent[ARGV[2]] = value
    redis.call('HSET', KEYS[1], ARGV[1], cjson.encode(agent))
    return 1
    """

    # -- Public API ---------------------------------------------------------

    def update_status(self, agent_id: str, status: str) -> None:
        """Atomically update agent status via Lua script."""
        self._atomic_set_field(agent_id, "status", status)

    def update_circuit_state(self, agent_id: str, state: str) -> None:
        """Atomically update circuit-breaker state via Lua script."""
        self._atomic_set_field(agent_id, "circuit_state", state)

    def update_load(self, agent_id: str, load: int) -> None:
        """Atomically set agent current_load via Lua script."""
        self._atomic_set_field(agent_id, "current_load", load)

    def atomic_increment_load(self, agent_id: str, max_load: int) -> bool:
        """Atomically increment agent load if not at capacity.

        Uses a Redis Lua script to avoid read-modify-write race conditions.
        Returns True if the increment succeeded, False if the agent is at
        capacity or does not exist.
        """
        try:
            result = self._redis.eval(
                self._ATOMIC_INCR_LUA,
                1,
                AGENTS_KEY,
                agent_id,
                str(max_load),
            )
            return int(result) > 0
        except Exception as exc:
            logger.warning(
                "atomic_increment_load failed for %s, falling back to non-atomic: %s",
                agent_id,
                exc,
            )
            # Fallback: non-atomic read-modify-write
            agent = self.get(agent_id)
            if not agent:
                return False
            if agent.current_load >= agent.max_concurrent:
                return False
            agent.current_load += 1
            self._redis.hset(AGENTS_KEY, agent_id, json.dumps(agent.to_dict()))
            return True

    def atomic_decrement_load(self, agent_id: str) -> int:
        """Atomically decrement agent load.

        Returns the new load value (>= 0) on success, or -1 if the agent
        does not exist.  Falls back to a non-atomic path on Lua errors.
        """
        try:
            result = self._redis.eval(
                self._ATOMIC_DECR_LUA,
                1,
                AGENTS_KEY,
                agent_id,
            )
            return int(result)
        except Exception as exc:
            logger.warning(
                "atomic_decrement_load failed for %s, falling back to non-atomic: %s",
                agent_id,
                exc,
            )
            agent = self.get(agent_id)
            if not agent:
                return -1
            if agent.current_load <= 0:
                return 0
            agent.current_load -= 1
            self._redis.hset(AGENTS_KEY, agent_id, json.dumps(agent.to_dict()))
            return agent.current_load

    def deregister(self, agent_id: str) -> None:
        self._redis.hdel(AGENTS_KEY, agent_id)
        logger.info("Deregistered agent %s", agent_id)

    def list_agents(self) -> list[AgentProfile]:
        all_data = self._redis.hgetall(AGENTS_KEY)
        agents = []
        for raw in all_data.values():
            agents.append(AgentProfile.from_dict(json.loads(raw)))
        return agents

    # -- Internal helpers ---------------------------------------------------

    def _atomic_set_field(
        self, agent_id: str, field: str, value: object
    ) -> None:
        """Run the _ATOMIC_SET_FIELD_LUA script with a non-atomic fallback."""
        if field not in _ALLOWED_FIELDS:
            raise ValueError(f"field not whitelisted: {field}")
        expected = _EXPECTED_TYPES.get(field)
        if expected is not None and not isinstance(value, expected):
            logger.warning(
                "Type mismatch for %s: expected %s, got %s",
                field, expected.__name__, type(value).__name__,
            )
        try:
            self._redis.eval(
                self._ATOMIC_SET_FIELD_LUA,
                1,
                AGENTS_KEY,
                agent_id,
                field,
                json.dumps(value),
            )
        except Exception as exc:
            logger.warning(
                "_atomic_set_field(%s, %s) failed, falling back to non-atomic: %s",
                agent_id,
                field,
                exc,
            )
            # Fallback: non-atomic read-modify-write
            agent = self.get(agent_id)
            if not agent:
                return
            setattr(agent, field, value)
            self._redis.hset(AGENTS_KEY, agent_id, json.dumps(agent.to_dict()))
