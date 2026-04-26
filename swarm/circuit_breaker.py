from __future__ import annotations

import enum
import threading
import time
import logging
from typing import Any, Callable

import redis as _redis

logger = logging.getLogger(__name__)

_CONNECTION_ERRORS = (
    _redis.ConnectionError,
    _redis.TimeoutError,
    OSError,
)


class CircuitState(enum.Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    def __init__(
        self,
        failure_threshold: int = 5,
        success_threshold: int = 2,
        recovery_timeout: float = 30.0,
        timeout_per_call: float = 3.0,
    ):
        self._failure_threshold = failure_threshold
        self._success_threshold = success_threshold
        self._recovery_timeout = recovery_timeout
        self._timeout_per_call = timeout_per_call
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: float = 0.0
        self._lock = threading.Lock()

    def _maybe_transition_to_half_open(self) -> None:
        """Must be called with self._lock held."""
        if self._state == CircuitState.OPEN:
            if time.monotonic() - self._last_failure_time >= self._recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                self._success_count = 0

    @property
    def state(self) -> CircuitState:
        with self._lock:
            self._maybe_transition_to_half_open()
            return self._state

    def record_success(self) -> None:
        with self._lock:
            self._success_count += 1
            if self._state == CircuitState.HALF_OPEN and self._success_count >= self._success_threshold:
                self._state = CircuitState.CLOSED
                self._failure_count = 0
                logger.info("circuit breaker: CLOSED (recovered)")

    def record_failure(self) -> None:
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()
            if self._failure_count >= self._failure_threshold:
                self._state = CircuitState.OPEN
                logger.warning("circuit breaker: OPEN (%d failures)", self._failure_count)

    def call(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        # Check state under lock
        with self._lock:
            self._maybe_transition_to_half_open()
            current = self._state
            if current == CircuitState.OPEN:
                return None

        # Call fn OUTSIDE the lock (it may block)
        try:
            result = fn(*args, **kwargs)
            self.record_success()
            return result
        except _CONNECTION_ERRORS as exc:
            self.record_failure()
            logger.debug("circuit breaker: connection error: %s", exc)
            return None
