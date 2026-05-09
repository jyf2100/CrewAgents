from __future__ import annotations
import asyncio
import logging
from typing import TYPE_CHECKING

import aiohttp

if TYPE_CHECKING:
    from hermes_orchestrator.config import OrchestratorConfig
    from hermes_orchestrator.stores.redis_agent_registry import RedisAgentRegistry
    from hermes_orchestrator.stores.redis_circuit_store import RedisCircuitStore

logger = logging.getLogger(__name__)


class AdaptiveHealthChecker:
    BASE_INTERVAL = 5.0
    MAX_INTERVAL = 30.0
    MIN_INTERVAL = 2.0
    BACKOFF_FACTOR = 1.5

    def __init__(self):
        self._intervals: dict[str, float] = {}

    def next_interval(self, agent_id: str, last_check_ok: bool) -> float:
        if agent_id not in self._intervals:
            self._intervals[agent_id] = self.BASE_INTERVAL
            return self.BASE_INTERVAL
        current = self._intervals[agent_id]
        if last_check_ok:
            next_val = min(current * 1.1, self.MAX_INTERVAL)
        else:
            next_val = max(current / self.BACKOFF_FACTOR, self.MIN_INTERVAL)
        self._intervals[agent_id] = next_val
        return next_val

    def min_current_interval(self) -> float:
        if not self._intervals:
            return self.BASE_INTERVAL
        return min(self._intervals.values())


class HealthMonitor:
    def __init__(
        self,
        config: OrchestratorConfig,
        registry: RedisAgentRegistry,
        circuit_store: RedisCircuitStore,
    ):
        self._config = config
        self._registry = registry
        self._circuit_store = circuit_store
        self._adaptive = AdaptiveHealthChecker()
        self._running = False

    async def start(self):
        self._running = True
        loop = asyncio.get_event_loop()
        while self._running:
            agents = await loop.run_in_executor(None, self._registry.list_agents)
            for agent in agents:
                if agent.status == "offline":
                    continue
                try:
                    healthy = await self._check_health(agent.gateway_url)
                except Exception:
                    healthy = False
                self._adaptive.next_interval(agent.agent_id, healthy)
                if healthy:
                    state, _, _ = await loop.run_in_executor(
                        None, self._circuit_store.record_success, agent.agent_id
                    )
                    await loop.run_in_executor(
                        None, self._registry.update_status, agent.agent_id, "online"
                    )
                else:
                    state, _ = await loop.run_in_executor(
                        None, self._circuit_store.record_failure, agent.agent_id
                    )
                    await asyncio.get_event_loop().run_in_executor(
                        None, self._registry.update_status, agent.agent_id, "degraded"
                    )
                    if state == "open":
                        logger.warning("Agent %s circuit OPEN — marking degraded", agent.agent_id)
            await asyncio.sleep(self._adaptive.min_current_interval())

    def stop(self):
        self._running = False

    async def _check_health(self, gateway_url: str) -> bool:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{gateway_url}/health",
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    return resp.status == 200
        except Exception:
            logger.debug("Health check failed for %s", gateway_url, exc_info=True)
            return False
