from __future__ import annotations
import logging
from hermes_orchestrator.models.agent import AgentProfile
from hermes_orchestrator.models.task import Task

logger = logging.getLogger(__name__)

class AgentSelector:
    def select(self, agents: list[AgentProfile], task: Task) -> AgentProfile | None:
        candidates = [
            a for a in agents
            if a.status in ("online", "degraded")
            and a.current_load < a.max_concurrent
            and a.circuit_state != "open"
        ]
        if not candidates:
            logger.warning("No available agent for task %s (checked %d agents)", task.task_id, len(agents))
            return None
        candidates.sort(key=lambda a: (a.current_load, a.last_health_check))
        return candidates[0]
