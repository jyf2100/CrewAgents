from __future__ import annotations

import json
import time
from typing import Any


class SwarmMessaging:
    """Redis Streams-based messaging layer for inter-agent communication."""

    MSG_VERSION = "1"
    DEFAULT_MAXLEN = 10000

    def __init__(self, redis_client: Any = None):
        self._redis = redis_client

    def publish_task(
        self,
        target_agent_id: int,
        task_id: str,
        task_type: str,
        goal: str,
        sender_id: int,
        capability: str = "",
        input_data: str = "",
        priority: int = 1,
        deadline_ts: float = 0.0,
        trace_id: str = "",
    ) -> str:
        """Publish a task to a target agent's stream and send an advisory notification."""
        stream = f"hermes:stream:agent.{target_agent_id}.tasks"
        fields = {
            "msg_version": self.MSG_VERSION,
            "task_id": task_id,
            "task_type": task_type,
            "goal": goal,
            "capability": capability,
            "input_data": input_data,
            "sender_id": str(sender_id),
            "priority": str(priority),
            "deadline_ts": str(deadline_ts),
            "trace_id": trace_id,
            "timestamp": str(time.time()),
        }
        msg_id = self._redis.xadd(
            stream, fields, maxlen=self.DEFAULT_MAXLEN, approximate=True
        )
        self._redis.publish(
            "swarm.advisory.task",
            json.dumps({"task_id": task_id, "target": target_agent_id}),
        )
        return msg_id

    def read_task(
        self,
        agent_id: int,
        consumer: str,
        block_ms: int = 5000,
        count: int = 1,
    ) -> list[dict]:
        """Read tasks from the agent's consumer group."""
        stream = f"hermes:stream:agent.{agent_id}.tasks"
        group = f"agent.{agent_id}.worker"
        result = self._redis.xreadgroup(
            group, consumer, {stream: ">"}, count=count, block=block_ms
        )
        messages: list[dict] = []
        if result:
            for _, msgs in result:
                for msg_id, fields in msgs:
                    fields["_msg_id"] = msg_id
                    messages.append(fields)
        return messages

    def ack_task(self, agent_id: int, group: str, msg_id: str) -> None:
        """Acknowledge a processed task message."""
        stream = f"hermes:stream:agent.{agent_id}.tasks"
        self._redis.xack(stream, group, msg_id)

    def reclaim_tasks(
        self, agent_id: int, min_idle_ms: int, consumer: str
    ) -> list[tuple]:
        """Claim pending messages that have been idle longer than min_idle_ms."""
        stream = f"hermes:stream:agent.{agent_id}.tasks"
        group = f"agent.{agent_id}.worker"
        pending = self._redis.xpending_range(
            stream, group, min=min_idle_ms, max="+", count=10
        )
        if not pending:
            return []
        ids = [p["message_id"] for p in pending]
        claimed = self._redis.xclaim(
            stream, group, consumer, min_idle_time=min_idle_ms, message_ids=ids
        )
        return [(mid, fields) for mid, fields in claimed]
