"""Background thread that consumes tasks from the agent's Redis Stream and executes them."""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Prune task metadata older than this many seconds.
_TASK_TTL_SECONDS = 300  # 5 minutes


class SwarmConsumer:
    """Consumes tasks from a Redis Stream for a single agent and executes them.

    Parameters
    ----------
    agent_id:
        Numeric identifier of the agent this consumer belongs to.
    redis_client:
        A ``redis-py`` client with ``decode_responses=True``.
    execute_fn:
        Callable ``(goal: str, input_data: str) -> str`` that performs the
        actual work and returns a result string.
    """

    def __init__(
        self,
        agent_id: int,
        redis_client: Any,
        execute_fn: Callable[[str, str], str],
    ) -> None:
        self._agent_id = agent_id
        self._redis = redis_client
        self._execute_fn = execute_fn

        self._stream = f"hermes:stream:agent.{agent_id}.tasks"
        self._group = f"agent.{agent_id}.worker"

        self._stop_event = threading.Event()
        self._consumer_name = f"consumer-{agent_id}"

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _ensure_group(self) -> None:
        """Create the consumer group (idempotent)."""
        try:
            self._redis.xgroup_create(self._stream, self._group, id="0", mkstream=True)
        except Exception as exc:
            # redis-py raises a ResponseError; check for BUSYGROUP substring.
            if "BUSYGROUP" not in str(exc):
                raise

    def run(self) -> None:
        """Main loop — polls for messages until :meth:`stop` is called."""
        self._ensure_group()
        while not self._stop_event.is_set():
            try:
                self._poll_once()
            except Exception as exc:
                logger.warning(
                    "Consumer poll error (agent %d), retrying in 2s: %s",
                    self._agent_id, exc,
                )
                self._stop_event.wait(2.0)

    def stop(self) -> None:
        """Signal the consumer to exit its run loop."""
        self._stop_event.set()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _poll_once(self) -> None:
        """Block briefly for one message, then handle it."""
        result = self._redis.xreadgroup(
            self._group,
            self._consumer_name,
            {self._stream: ">"},
            count=1,
            block=5000,
        )
        if not result:
            return

        for _stream_name, messages in result:
            for msg_id, fields in messages:
                self._handle_message(msg_id, fields)

    def _handle_message(self, msg_id: str, fields: dict) -> None:
        """Process a single stream message."""
        task_id = fields.get("task_id", "unknown")
        task_type = fields.get("task_type", "unknown")
        goal = fields.get("goal", "")
        input_data = fields.get("input_data", "")

        try:
            # ── Cancellation check ────────────────────────────────
            cancel_key = f"hermes:swarm:cancel:{task_id}"
            if self._redis.exists(cancel_key):
                logger.info("Task %s cancelled, skipping.", task_id)
                return

            # ── Advisory: task started ────────────────────────────
            self._redis.publish(
                "swarm.advisory.task",
                json.dumps(
                    {
                        "event": "task_started",
                        "task_id": task_id,
                        "agent_id": self._agent_id,
                        "task_type": task_type,
                    }
                ),
            )

            # ── Execute ───────────────────────────────────────────
            start = time.monotonic()
            error: str | None = None
            output: str = ""
            status = "completed"
            try:
                output = self._execute_fn(goal, input_data)
            except Exception as exc:
                status = "failed"
                error = str(exc)
                logger.exception("Task %s execution failed.", task_id)
            duration_ms = int((time.monotonic() - start) * 1000)

            # ── Write result ──────────────────────────────────────
            result_key = f"hermes:swarm:result:{task_id}"
            now_ms = time.time() * 1000
            now = now_ms / 1000
            result_payload = {
                "task_id": task_id,
                "agent_id": self._agent_id,
                "status": status,
                "output": output,
                "error": error or "",
                "duration_ms": duration_ms,
                "timestamp": now,
            }
            self._redis.rpush(result_key, json.dumps(result_payload))
            self._redis.expire(result_key, 300)

            # ── Advisory: task completed/failed ───────────────────
            self._redis.publish(
                "swarm.advisory.result",
                json.dumps(
                    {
                        "event": "task_completed" if status == "completed" else "task_failed",
                        "task_id": task_id,
                        "agent_id": self._agent_id,
                        "status": status,
                        "duration_ms": duration_ms,
                    }
                ),
            )

            # ── Store task metadata (sorted set, score=ms timestamp) ─
            tasks_key = "hermes:swarm:tasks"
            sender_id = fields.get("sender_id", "0")
            task_meta = {
                "task_id": task_id,
                "task_type": task_type,
                "goal": goal[:200],
                "status": status,
                "sender_id": int(sender_id) if sender_id.isdigit() else 0,
                "assigned_agent_id": self._agent_id,
                "duration_ms": duration_ms,
                "error": (error or "")[:500],
                "timestamp": now,
            }
            self._redis.zadd(tasks_key, {json.dumps(task_meta): now_ms})
            # Prune entries older than 5 minutes
            cutoff_ms = (now - _TASK_TTL_SECONDS) * 1000
            self._redis.zremrangebyscore(tasks_key, "-inf", cutoff_ms)

        except Exception:
            logger.exception("Error processing task %s, ACKing to avoid re-delivery.", task_id)
        finally:
            # Always ACK so the message is not re-delivered on errors
            try:
                self._redis.xack(self._stream, self._group, msg_id)
            except Exception:
                logger.exception("Failed to ACK message %s", msg_id)
