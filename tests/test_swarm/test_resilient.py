from unittest.mock import MagicMock

import redis as _redis

from swarm.resilient_client import ResilientSwarmClient, SwarmMode
from swarm.client import SwarmClient


def test_starts_in_swarm_mode():
    inner = MagicMock(spec=SwarmClient)
    rclient = ResilientSwarmClient(inner=inner)
    assert rclient.mode == SwarmMode.SWARM


def test_degrades_on_connection_error():
    inner = MagicMock(spec=SwarmClient)
    inner.register.side_effect = _redis.ConnectionError("refused")
    degrade_cb = MagicMock()
    rclient = ResilientSwarmClient(inner=inner, on_degrade=degrade_cb)
    rclient.start()
    assert rclient.mode == SwarmMode.STANDALONE
    degrade_cb.assert_called_once()


def test_submit_returns_none_in_standalone():
    inner = MagicMock(spec=SwarmClient)
    rclient = ResilientSwarmClient(inner=inner)
    rclient._mode = SwarmMode.STANDALONE
    result = rclient.submit_task(target_agent_id=5, task_type="review", goal="test")
    assert result is None


def test_heartbeat_noop_in_standalone():
    inner = MagicMock(spec=SwarmClient)
    rclient = ResilientSwarmClient(inner=inner)
    rclient._mode = SwarmMode.STANDALONE
    rclient.heartbeat()
    inner.heartbeat.assert_not_called()
