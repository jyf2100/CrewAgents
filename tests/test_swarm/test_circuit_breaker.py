import time
import pytest
from unittest.mock import MagicMock
import redis as _redis
from swarm.circuit_breaker import CircuitBreaker, CircuitState


def test_starts_closed():
    cb = CircuitBreaker(failure_threshold=3, recovery_timeout=1.0)
    assert cb.state == CircuitState.CLOSED


def test_opens_after_threshold():
    cb = CircuitBreaker(failure_threshold=3, recovery_timeout=1.0)
    for _ in range(3):
        cb.record_failure()
    assert cb.state == CircuitState.OPEN


def test_half_open_after_timeout():
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.1)
    cb.record_failure()
    cb.record_failure()
    assert cb.state == CircuitState.OPEN
    time.sleep(0.15)
    # Accessing .state should auto-transition to HALF_OPEN
    assert cb.state == CircuitState.HALF_OPEN


def test_closes_after_success_threshold():
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.1, success_threshold=2)
    cb.record_failure()
    cb.record_failure()
    time.sleep(0.15)
    # Call transitions to HALF_OPEN, then successes close it
    cb.call(lambda: "ok")  # HALF_OPEN + success
    cb.record_success()  # second success
    assert cb.state == CircuitState.CLOSED


def test_call_returns_none_when_open():
    cb = CircuitBreaker(failure_threshold=1, recovery_timeout=10.0)
    cb.record_failure()
    assert cb.state == CircuitState.OPEN
    result = cb.call(lambda: "should not run")
    assert result is None


def test_connection_errors_trigger_failure():
    cb = CircuitBreaker(failure_threshold=1, recovery_timeout=1.0)
    fn = MagicMock(side_effect=_redis.ConnectionError("refused"))
    result = cb.call(fn)
    assert result is None
    assert cb.state == CircuitState.OPEN


def test_non_connection_errors_propagate():
    cb = CircuitBreaker(failure_threshold=3, recovery_timeout=1.0)
    with pytest.raises(ValueError):
        cb.call(lambda: (_ for _ in ()).throw(ValueError("bad")))
