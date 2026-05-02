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
