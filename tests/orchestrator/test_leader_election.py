"""Tests for Redis-based leader election service."""

import asyncio
import os

import pytest
import redis as _redis

from hermes_orchestrator.services.leader_election import FENCING_KEY, LEADER_KEY, LeaderElection


def _build_redis():
    url = os.environ.get("REDIS_URL")
    if url:
        return _redis.Redis.from_url(url, db=15, decode_responses=True)
    host = os.environ.get("REDIS_HOST", "localhost")
    port = int(os.environ.get("REDIS_PORT", "6379"))
    password = os.environ.get("REDIS_PASSWORD")
    return _redis.Redis(host=host, port=port, password=password, db=15, decode_responses=True)


@pytest.fixture
def redis_client():
    r = _build_redis()
    r.flushdb()
    yield r
    r.flushdb()
    r.close()


@pytest.fixture
def election(redis_client):
    return LeaderElection(redis_client, identity="pod-1:1234", ttl=5, renew_interval=1.0)


@pytest.fixture
def election2(redis_client):
    return LeaderElection(redis_client, identity="pod-2:5678", ttl=5, renew_interval=1.0)


# ---------------------------------------------------------------------------
# Basic acquire / release
# ---------------------------------------------------------------------------


class TestAcquire:
    def test_try_acquire_succeeds_on_empty_key(self, election, redis_client):
        result = election.try_acquire()
        assert result is True
        assert election.is_leader is True
        assert redis_client.get(LEADER_KEY) == "pod-1:1234"

    def test_try_acquire_fails_when_another_holds_lock(self, election, election2):
        election.try_acquire()
        result = election2.try_acquire()
        assert result is False
        assert election2.is_leader is False

    def test_try_acquire_sets_fencing_token_via_incr(self, election, redis_client):
        assert election.fencing_token == 0
        election.try_acquire()
        assert election.fencing_token > 0
        assert isinstance(election.fencing_token, int)
        # The Redis INCR counter should match the fencing token
        assert int(redis_client.get(FENCING_KEY)) == election.fencing_token

    def test_try_acquire_fencing_token_monotonically_increasing(
        self, election, redis_client
    ):
        election.try_acquire()
        first_token = election.fencing_token

        # Simulate stepping down by deleting the key directly
        redis_client.delete(LEADER_KEY)
        election._is_leader = False

        election.try_acquire()
        second_token = election.fencing_token
        assert second_token > first_token


# ---------------------------------------------------------------------------
# Renewal
# ---------------------------------------------------------------------------


class TestRenew:
    def test_renew_succeeds_when_identity_matches(self, election, redis_client):
        election.try_acquire()
        # TTL should be reset by renew — just verify the return value
        result = election.renew()
        assert result is True
        assert election.is_leader is True

    def test_renew_fails_when_identity_does_not_match(self, election, redis_client):
        election.try_acquire()
        assert election.is_leader is True

        # Overwrite key with a different identity to simulate takeover
        redis_client.set(LEADER_KEY, "pod-other:9999", ex=10)

        result = election.renew()
        assert result is False
        assert election.is_leader is False


# ---------------------------------------------------------------------------
# Step down (async)
# ---------------------------------------------------------------------------


class TestStepDown:
    @pytest.mark.asyncio
    async def test_step_down_deletes_matching_identity(self, election, redis_client):
        election.try_acquire()
        assert redis_client.get(LEADER_KEY) == "pod-1:1234"

        await election.step_down()
        assert redis_client.get(LEADER_KEY) is None
        assert election.is_leader is False

    @pytest.mark.asyncio
    async def test_step_down_does_not_delete_others_lock(
        self, election, redis_client
    ):
        # Another instance holds the lock
        redis_client.set(LEADER_KEY, "pod-other:9999", ex=10)

        await election.step_down()
        assert election.is_leader is False
        # The other instance's lock should remain
        assert redis_client.get(LEADER_KEY) == "pod-other:9999"

    @pytest.mark.asyncio
    async def test_step_down_is_idempotent(self, election, redis_client):
        election.try_acquire()
        await election.step_down()
        assert election.is_leader is False

        # Second call should not raise
        await election.step_down()
        assert election.is_leader is False


# ---------------------------------------------------------------------------
# Async behaviour — renew loop and acquire loop
# ---------------------------------------------------------------------------


class TestAsyncLoops:
    @pytest.mark.asyncio
    async def test_start_renew_loop_keeps_leadership_alive(
        self, election, redis_client
    ):
        # Use a very short TTL and fast renew interval so the test completes quickly
        election._ttl = 2
        election._renew_interval = 0.5

        election.try_acquire()
        await election.start_renew_loop()

        # Sleep past the original TTL — without renewals the key would expire
        await asyncio.sleep(3)

        assert election.is_leader is True
        # Key should still exist in Redis with our identity
        assert redis_client.get(LEADER_KEY) == "pod-1:1234"

        await election.step_down()

    @pytest.mark.asyncio
    async def test_step_down_cancels_renew_loop(self, election, redis_client):
        election.try_acquire()
        await election.start_renew_loop()
        assert election._renew_task is not None

        await election.step_down()
        assert election.is_leader is False
        assert election._renew_task is None

    @pytest.mark.asyncio
    async def test_acquire_loop_eventually_acquires(self, redis_client):
        # The acquire loop uses interval = max(ttl/3, 5.0), so minimum 5s.
        # Use ttl=20 so interval=6.67s, set competing key with 2s TTL.
        election = LeaderElection(
            redis_client, identity="pod-1:1234", ttl=20, renew_interval=1.0
        )
        # Another identity holds the lock with a short TTL so it will expire
        redis_client.set(LEADER_KEY, "pod-other:9999", ex=2)

        acquired_flag = asyncio.Event()

        async def on_become_leader():
            acquired_flag.set()

        await election.start_acquire_loop(on_become_leader=on_become_leader)

        # Wait long enough for the loop interval + buffer
        await asyncio.sleep(8)

        assert election.is_leader is True
        assert acquired_flag.is_set()

        # Clean up
        await election.step_down()


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_is_leader_false_after_failed_renew(self, election, redis_client):
        election.try_acquire()
        assert election.is_leader is True

        # Another instance overwrites the key
        redis_client.set(LEADER_KEY, "pod-other:9999", ex=10)

        result = election.renew()
        assert result is False
        assert election.is_leader is False

    @pytest.mark.asyncio
    async def test_step_down_handles_redis_unavailable_gracefully(
        self, redis_client
    ):
        election = LeaderElection(
            redis_client, identity="pod-1:1234", ttl=5, renew_interval=1.0
        )
        election.try_acquire()

        # Close the Redis connection to simulate unavailability
        redis_client.close()

        # step_down should not raise
        await election.step_down()
        assert election.is_leader is False
