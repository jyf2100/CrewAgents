from __future__ import annotations

import json
import time
import uuid
from typing import Any

from .messaging import SwarmMessaging


class SwarmClient:
    """High-level client for interacting with the swarm as a registered agent."""

    def __init__(
        self,
        agent_id: int,
        redis_client: Any,
        capabilities: list[str],
        max_tasks: int = 3,
    ):
        self.agent_id = agent_id
        self._redis = redis_client
        self.capabilities = capabilities
        self.max_tasks = max_tasks
        self._messaging = SwarmMessaging(redis_client=redis_client)

    def register(self, display_name: str = "") -> None:
        """Register this agent in the swarm registry."""
        profile = {
            "agent_id": str(self.agent_id),
            "display_name": display_name or f"Agent-{self.agent_id}",
            "capabilities": self.capabilities,
            "status": "online",
            "max_concurrent_tasks": str(self.max_tasks),
            "current_tasks": "0",
            "registered_at": str(time.time()),
            "last_heartbeat": str(time.time()),
            "inbox_channel": f"agent.{self.agent_id}.inbox",
        }
        self._redis.hset(
            "hermes:registry", str(self.agent_id), json.dumps(profile)
        )
        self._redis.publish(
            "swarm.advisory.online",
            json.dumps({"agent_id": self.agent_id}),
        )

    def heartbeat(self) -> None:
        """Send a heartbeat signal to indicate this agent is alive."""
        self._redis.set(
            f"hermes:heartbeat:{self.agent_id}",
            str(time.time()),
            ex=60,
        )

    def submit_task(
        self,
        target_agent_id: int,
        task_type: str,
        goal: str,
        input_data: str = "",
        timeout: int = 120,
    ) -> str:
        """Submit a task to a target agent. Returns the generated task_id."""
        task_id = str(uuid.uuid4())
        self._messaging.publish_task(
            target_agent_id=target_agent_id,
            task_id=task_id,
            task_type=task_type,
            goal=goal,
            sender_id=self.agent_id,
            input_data=input_data,
        )
        return task_id

    def wait_for_result(self, task_id: str, timeout: int = 120) -> dict | None:
        """Block until a result is available for the given task, or timeout."""
        key = f"hermes:swarm:result:{task_id}"
        result = self._redis.blpop(key, timeout=timeout)
        if result:
            _, data = result
            return json.loads(data)
        return None
