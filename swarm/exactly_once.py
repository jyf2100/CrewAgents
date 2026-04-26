from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ExactlyOnceGuard:
    """Ensures each task is processed exactly once using Redis-based guards."""

    dedup_ttl: int = 300
    exec_guard_ttl: int = 600
    cancel_ttl: int = 300
    result_ttl: int = 300

    def acquire_dedup(self, redis_client: Any, task_id: str, sender_id: str) -> bool:
        """Acquire a dedup lock. Returns True if this is the first claim, False if duplicate."""
        key = f"hermes:swarm:dedup:{task_id}"
        result = redis_client.set(key, sender_id, nx=True, ex=self.dedup_ttl)
        return result is not None and result is not False

    def begin_execution(self, redis_client: Any, task_id: str, agent_id: str) -> bool:
        """Mark task as executing. Returns True if no one else is running it."""
        key = f"hermes:swarm:exec:{task_id}"
        value = json.dumps(
            {"agent_id": agent_id, "started_at": time.time(), "status": "running"}
        )
        result = redis_client.set(key, value, nx=True, ex=self.exec_guard_ttl)
        return result is not None and result is not False

    def is_cancelled(self, redis_client: Any, task_id: str) -> bool:
        """Check whether a cancellation flag exists for the task."""
        return bool(redis_client.exists(f"hermes:swarm:cancel:{task_id}"))

    def set_cancel(self, redis_client: Any, task_id: str, reason: str) -> None:
        """Set a cancellation flag for the task."""
        redis_client.set(
            f"hermes:swarm:cancel:{task_id}", reason, ex=self.cancel_ttl
        )

    def write_result(self, redis_client: Any, task_id: str, result_json: str) -> None:
        """Write a result entry and set TTL on the list."""
        key = f"hermes:swarm:result:{task_id}"
        redis_client.rpush(key, result_json)
        redis_client.expire(key, self.result_ttl)

    def send_to_dlq(
        self, redis_client: Any, task_id: str, agent_id: str, reason: str
    ) -> None:
        """Send task metadata to the dead-letter queue stream."""
        redis_client.xadd(
            "hermes:stream:swarm.dlq",
            {
                "task_id": task_id,
                "agent_id": str(agent_id),
                "reason": reason,
                "timestamp": str(time.time()),
            },
            maxlen=10000,
            approximate=True,
        )
