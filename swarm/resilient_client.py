"""Resilient wrapper around SwarmClient that degrades to standalone on Redis failures."""
from __future__ import annotations

import enum
import logging
import threading
from typing import Any, Callable

import redis as _redis

from .client import SwarmClient
from .consumer import SwarmConsumer

logger = logging.getLogger(__name__)


class SwarmMode(enum.Enum):
    SWARM = "swarm"
    STANDALONE = "standalone"


class ResilientSwarmClient:
    """Wraps a SwarmClient and gracefully degrades to standalone mode when Redis is unreachable."""

    def __init__(
        self,
        inner: SwarmClient,
        on_degrade: Callable[[], None] | None = None,
        on_recover: Callable[[], None] | None = None,
    ):
        self._inner = inner
        self._mode = SwarmMode.SWARM
        self._lock = threading.Lock()
        self._on_degrade = on_degrade
        self._on_recover = on_recover
        self._consumer: SwarmConsumer | None = None
        self._consumer_thread: threading.Thread | None = None
        self._execute_fn: Callable[[str, str], str] | None = None

    @property
    def mode(self) -> SwarmMode:
        with self._lock:
            return self._mode

    def start(self) -> None:
        try:
            self._inner.register()
        except _redis.ConnectionError as exc:
            with self._lock:
                self._mode = SwarmMode.STANDALONE
            logger.warning("swarm: Redis unreachable, entering standalone mode: %s", exc)
            if self._on_degrade:
                self._on_degrade()

    def heartbeat(self) -> None:
        try:
            self._inner.heartbeat()
            with self._lock:
                if self._mode == SwarmMode.STANDALONE:
                    self._mode = SwarmMode.SWARM
                    logger.info("swarm: recovered from standalone mode")
                    if self._on_recover:
                        self._on_recover()
        except _redis.ConnectionError:
            with self._lock:
                if self._mode != SwarmMode.STANDALONE:
                    self._mode = SwarmMode.STANDALONE
                    logger.warning("swarm: heartbeat failed, degrading to standalone")
                    if self._on_degrade:
                        self._on_degrade()

    def submit_task(
        self,
        target_agent_id: int,
        task_type: str,
        goal: str,
        **kwargs: Any,
    ) -> str | None:
        with self._lock:
            if self._mode == SwarmMode.STANDALONE:
                return None
        try:
            return self._inner.submit_task(
                target_agent_id=target_agent_id,
                task_type=task_type,
                goal=goal,
                **kwargs,
            )
        except _redis.ConnectionError:
            with self._lock:
                self._mode = SwarmMode.STANDALONE
            if self._on_degrade:
                self._on_degrade()
            return None

    def wait_for_result(self, task_id: str, timeout: int = 120) -> dict | None:
        with self._lock:
            if self._mode == SwarmMode.STANDALONE:
                return None
        return self._inner.wait_for_result(task_id, timeout)

    def start_consumer(self, execute_fn: Callable[[str, str], str]) -> None:
        """Start the background task consumer thread."""
        with self._lock:
            if self._mode == SwarmMode.STANDALONE:
                return
        self._execute_fn = execute_fn
        self._consumer = SwarmConsumer(
            agent_id=self._inner.agent_id,
            redis_client=self._inner._redis,
            execute_fn=execute_fn,
        )
        self._consumer_thread = threading.Thread(
            target=self._consumer.run, daemon=True
        )
        self._consumer_thread.start()

    def stop_consumer(self) -> None:
        """Stop the background task consumer."""
        if self._consumer is not None:
            self._consumer.stop()
        self._consumer = None
        self._consumer_thread = None
