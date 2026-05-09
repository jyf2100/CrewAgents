"""Unit tests for RedisCircuitStore — Lua-script-based circuit breaker state machine.

Uses a real Redis connection (db=15, flushed between tests) following the
same pattern as test_redis_agent_registry.py.
"""

import os
import time
from unittest.mock import patch

import pytest
import redis as _redis

from hermes_orchestrator.stores.redis_circuit_store import RedisCircuitStore


def _build_redis():
    url = os.environ.get("REDIS_URL")
    if url:
        return _redis.Redis.from_url(url, db=15, decode_responses=True)
    host = os.environ.get("REDIS_HOST", "localhost")
    port = int(os.environ.get("REDIS_PORT", "6379"))
    password = os.environ.get("REDIS_PASSWORD")
    return _redis.Redis(host=host, port=port, password=password, db=15, decode_responses=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

AGENT_ID = "gw-test"


def _set_circuit_state(redis_client, agent_id, state, *, failure_count=0,
                       success_count=0, last_failure_ts=0):
    """Directly write circuit breaker fields into Redis for controlled setup."""
    key = f"hermes:orchestrator:circuits:{agent_id}"
    redis_client.hset(
        key,
        mapping={
            "state": state,
            "failure_count": failure_count,
            "success_count": success_count,
            "last_failure_ts": last_failure_ts,
        },
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def redis_client():
    r = _build_redis()
    r.flushdb()
    yield r
    r.flushdb()
    r.close()


@pytest.fixture
def store(redis_client):
    return RedisCircuitStore(
        redis_client,
        failure_threshold=3,
        success_threshold=2,
        recovery_timeout=1.0,
        circuit_ttl=3600,
    )


# ===================================================================
# State machine transitions
# ===================================================================


class TestClosedState:
    """Circuit in CLOSED state."""

    def test_stays_closed_below_threshold(self, store):
        """Failures below threshold keep circuit CLOSED."""
        state, fc = store.record_failure(AGENT_ID)
        assert state == "closed"
        assert fc == 1

        state, fc = store.record_failure(AGENT_ID)
        assert state == "closed"
        assert fc == 2

    def test_transitions_to_open_at_threshold(self, store):
        """Exactly failure_threshold failures trip circuit to OPEN."""
        for _ in range(2):
            store.record_failure(AGENT_ID)

        # Third failure reaches threshold=3
        state, fc = store.record_failure(AGENT_ID)
        assert state == "open"
        assert fc == 3

    def test_record_success_resets_counters(self, store, redis_client):
        """record_success on CLOSED circuit resets both counters to 0."""
        # Accumulate some failures first
        store.record_failure(AGENT_ID)
        store.record_failure(AGENT_ID)

        state, fc, sc = store.record_success(AGENT_ID)
        assert state == "closed"
        assert fc == 0
        assert sc == 0

        # Verify in Redis directly
        key = f"hermes:orchestrator:circuits:{AGENT_ID}"
        assert redis_client.hget(key, "failure_count") == "0"
        assert redis_client.hget(key, "success_count") == "0"


class TestOpenState:
    """Circuit in OPEN state."""

    def _open_circuit(self, store):
        """Helper: drive circuit into OPEN state via failures."""
        for _ in range(3):
            store.record_failure(AGENT_ID)

    def test_stays_open_before_recovery_timeout(self, store):
        """record_success before recovery_timeout keeps circuit OPEN."""
        self._open_circuit(store)

        # Immediately call record_success — timeout has not elapsed
        state, fc, sc = store.record_success(AGENT_ID)
        assert state == "open"
        assert sc == 0

    def test_transitions_to_half_open_after_recovery_timeout(self, store):
        """record_success after recovery_timeout moves OPEN -> HALF_OPEN."""
        self._open_circuit(store)

        # Manipulate last_failure_ts to simulate elapsed recovery_timeout
        past_ts = time.time() - store._recovery_timeout - 0.5
        key = f"hermes:orchestrator:circuits:{AGENT_ID}"
        store._redis.hset(key, "last_failure_ts", past_ts)

        state, fc, sc = store.record_success(AGENT_ID)
        assert state == "half_open"
        assert fc == 0
        assert sc == 1


class TestHalfOpenState:
    """Circuit in HALF_OPEN state."""

    def _set_half_open(self, redis_client, agent_id):
        """Helper: place circuit directly into HALF_OPEN."""
        _set_circuit_state(
            redis_client,
            agent_id,
            "half_open",
            failure_count=0,
            success_count=0,
        )

    def test_transitions_to_closed_after_success_threshold(self, store, redis_client):
        """success_threshold consecutive successes close the circuit."""
        self._set_half_open(redis_client, AGENT_ID)

        # First success
        state, fc, sc = store.record_success(AGENT_ID)
        assert state == "half_open"
        assert sc == 1

        # Second success reaches success_threshold=2
        state, fc, sc = store.record_success(AGENT_ID)
        assert state == "closed"
        assert fc == 0
        assert sc == 0

    def test_transitions_to_open_on_any_failure(self, store, redis_client):
        """Any failure in HALF_OPEN trips back to OPEN and resets success_count."""
        self._set_half_open(redis_client, AGENT_ID)

        # Accumulate one success first to prove success_count gets reset
        store.record_success(AGENT_ID)
        key = f"hermes:orchestrator:circuits:{AGENT_ID}"
        assert redis_client.hget(key, "success_count") == "1"

        # Now a single failure should re-open
        state, fc = store.record_failure(AGENT_ID)
        assert state == "open"
        assert fc == 1

        # success_count must have been reset to 0 (fix C7)
        assert redis_client.hget(key, "success_count") == "0"


class TestCheckState:
    """check_state is a pure read — must never trigger transitions."""

    def test_check_state_does_not_transition(self, store, redis_client):
        """Reading an OPEN circuit must NOT auto-transition to HALF_OPEN."""
        # Trip to OPEN
        for _ in range(3):
            store.record_failure(AGENT_ID)

        # Manipulate last_failure_ts so that recovery_timeout has elapsed
        past_ts = time.time() - store._recovery_timeout - 0.5
        key = f"hermes:orchestrator:circuits:{AGENT_ID}"
        redis_client.hset(key, "last_failure_ts", past_ts)

        # check_state should still report OPEN (no side effects)
        state, fc, sc, lfts = store.check_state(AGENT_ID)
        assert state == "open"
        assert fc == 3
        assert sc == 0

    def test_check_state_returns_defaults_for_missing_key(self, store):
        """check_state on a non-existent key returns safe defaults."""
        state, fc, sc, lfts = store.check_state("no-such-agent")
        assert state == "closed"
        assert fc == 0
        assert sc == 0
        assert lfts == 0.0


# ===================================================================
# Key management
# ===================================================================


class TestKeyManagement:
    def test_ttl_set_after_record_failure(self, store, redis_client):
        """record_failure must set EXPIRE on the key."""
        store.record_failure(AGENT_ID)
        key = f"hermes:orchestrator:circuits:{AGENT_ID}"
        ttl = redis_client.ttl(key)
        assert ttl > 0

    def test_ttl_set_after_record_success(self, store, redis_client):
        """record_success must set EXPIRE on the key."""
        store.record_success(AGENT_ID)
        key = f"hermes:orchestrator:circuits:{AGENT_ID}"
        ttl = redis_client.ttl(key)
        assert ttl > 0

    def test_delete_removes_key(self, store, redis_client):
        """delete removes the Redis key entirely."""
        store.record_failure(AGENT_ID)
        key = f"hermes:orchestrator:circuits:{AGENT_ID}"
        assert redis_client.exists(key) == 1

        store.delete(AGENT_ID)
        assert redis_client.exists(key) == 0

        # check_state should return safe defaults after deletion
        state, fc, sc, lfts = store.check_state(AGENT_ID)
        assert state == "closed"
        assert fc == 0


# ===================================================================
# Error handling (H13) — graceful degradation
# ===================================================================


class TestErrorHandling:
    def test_record_failure_degrades_gracefully(self, store):
        """record_failure returns ('closed', 0) on Redis ConnectionError."""
        with patch.object(store, "_record_failure_script", side_effect=_redis.ConnectionError("boom")):
            state, fc = store.record_failure(AGENT_ID)
        assert state == "closed"
        assert fc == 0

    def test_record_success_degrades_gracefully(self, store):
        """record_success returns ('closed', 0, 0) on Redis ConnectionError."""
        with patch.object(store, "_record_success_script", side_effect=_redis.ConnectionError("boom")):
            state, fc, sc = store.record_success(AGENT_ID)
        assert state == "closed"
        assert fc == 0
        assert sc == 0

    def test_check_state_degrades_gracefully(self, store):
        """check_state returns safe defaults on Redis ConnectionError."""
        with patch.object(store, "_check_state_script", side_effect=_redis.ConnectionError("boom")):
            state, fc, sc, lfts = store.check_state(AGENT_ID)
        assert state == "closed"
        assert fc == 0
        assert sc == 0
        assert lfts == 0.0
