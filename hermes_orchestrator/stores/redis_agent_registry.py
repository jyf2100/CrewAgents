from __future__ import annotations
import json
import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import redis as _redis

from hermes_orchestrator.models.agent import AgentProfile

logger = logging.getLogger(__name__)

AGENTS_KEY = "hermes:orchestrator:agents"


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

    def update_status(self, agent_id: str, status: str) -> None:
        agent = self.get(agent_id)
        if agent:
            agent.status = status
            self._redis.hset(AGENTS_KEY, agent_id, json.dumps(agent.to_dict()))

    # Lua script for atomic load increment with capacity check.
    # Returns the new load (> 0) on success, or 0 if the agent is at capacity.
    _ATOMIC_INCR_LUA = """
    local key = KEYS[1]
    local field = ARGV[1]
    local max_load = tonumber(ARGV[2])
    local data = redis.call('HGET', key, field)
    if not data then
        return 0
    end
    local agent = cjson.decode(data)
    local current = tonumber(agent['current_load']) or 0
    local max_c = tonumber(agent['max_concurrent']) or max_load
    if current >= max_c then
        return 0
    end
    agent['current_load'] = current + 1
    redis.call('HSET', key, field, cjson.encode(agent))
    return current + 1
    """

    def atomic_increment_load(self, agent_id: str, max_load: int) -> bool:
        """Atomically increment agent load if not at capacity.

        Uses a Redis Lua script to avoid read-modify-write race conditions.
        Returns True if the increment succeeded, False if the agent is at
        capacity or does not exist.
        """
        try:
            result = self._redis.eval(
                self._ATOMIC_INCR_LUA, 1,
                AGENTS_KEY, agent_id, str(max_load),
            )
            return int(result) > 0
        except Exception:
            logger.warning(
                "atomic_increment_load failed for %s, falling back to non-atomic",
                agent_id,
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

    def update_load(self, agent_id: str, load: int) -> None:
        agent = self.get(agent_id)
        if agent:
            agent.current_load = load
            self._redis.hset(AGENTS_KEY, agent_id, json.dumps(agent.to_dict()))

    def update_circuit_state(self, agent_id: str, state: str) -> None:
        agent = self.get(agent_id)
        if agent:
            agent.circuit_state = state
            self._redis.hset(AGENTS_KEY, agent_id, json.dumps(agent.to_dict()))

    def deregister(self, agent_id: str) -> None:
        self._redis.hdel(AGENTS_KEY, agent_id)
        logger.info("Deregistered agent %s", agent_id)

    def list_agents(self) -> list[AgentProfile]:
        all_data = self._redis.hgetall(AGENTS_KEY)
        agents = []
        for raw in all_data.values():
            agents.append(AgentProfile.from_dict(json.loads(raw)))
        return agents
