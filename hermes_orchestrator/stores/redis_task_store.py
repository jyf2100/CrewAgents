from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import redis as _redis

from hermes_orchestrator.models.task import Task, TaskResult

logger = logging.getLogger(__name__)

STREAM_KEY = "hermes:orchestrator:tasks:stream"
TASK_PREFIX = "hermes:orchestrator:tasks:"
CONSUMER_GROUP = "orchestrator.workers"

_UNSET = object()


class RedisTaskStore:
    def __init__(self, redis_client: _redis.Redis):
        self._redis = redis_client
        self._ensure_consumer_group()

    def _ensure_consumer_group(self):
        try:
            self._redis.xgroup_create(
                STREAM_KEY, CONSUMER_GROUP, id="0", mkstream=True
            )
        except Exception:
            pass

    def create(self, task: Task) -> None:
        data = task.to_dict()
        data["status"] = "queued"
        data["updated_at"] = time.time()
        self._redis.hset(
            f"{TASK_PREFIX}{task.task_id}",
            "data",
            json.dumps(data),
        )

    def get(self, task_id: str) -> Task | None:
        data = self._redis.hget(f"{TASK_PREFIX}{task_id}", "data")
        if not data:
            return None
        return Task.from_dict(json.loads(data))

    def update(
        self,
        task_id: str,
        status: str | None = _UNSET,
        assigned_agent: str | None = _UNSET,
        run_id: str | None = _UNSET,
        result: TaskResult | None = _UNSET,
        error: str | None = _UNSET,
        retry_count: int | None = _UNSET,
    ) -> None:
        task = self.get(task_id)
        if not task:
            logger.warning("Attempted to update nonexistent task %s", task_id)
            return
        if status is not _UNSET:
            task.status = status
        if assigned_agent is not _UNSET:
            task.assigned_agent = assigned_agent
        if run_id is not _UNSET:
            task.run_id = run_id
        if result is not _UNSET:
            task.result = result
        if error is not _UNSET:
            task.error = error
        if retry_count is not _UNSET:
            task.retry_count = retry_count
        task.updated_at = time.time()
        self._redis.hset(
            f"{TASK_PREFIX}{task.task_id}",
            "data",
            json.dumps(task.to_dict()),
        )

    def delete(self, task_id: str) -> None:
        self._redis.delete(f"{TASK_PREFIX}{task_id}")

    def enqueue(self, task: Task) -> None:
        fields = {
            "task_id": task.task_id,
            "priority": str(task.priority),
            "model_id": task.model_id,
            "created_at": str(task.created_at),
        }
        self._redis.xadd(STREAM_KEY, fields, maxlen=10000, approximate=True)

    def list_by_status(self, statuses: list[str], max_items: int = 1000) -> list[Task]:
        cursor = 0
        tasks = []
        while True:
            cursor, keys = self._redis.scan(
                cursor, match=f"{TASK_PREFIX}*", count=100
            )
            for key in keys:
                if isinstance(key, bytes):
                    key = key.decode()
                # Skip the stream key (not a task hash)
                if key.endswith(":stream"):
                    continue
                data = self._redis.hget(key, "data")
                if data:
                    t = Task.from_dict(json.loads(data))
                    if t.status in statuses:
                        tasks.append(t)
            if cursor == 0 or len(tasks) >= max_items:
                break
        return tasks
