import time
import pytest
import redis as _redis
from hermes_orchestrator.models.agent import AgentProfile
from hermes_orchestrator.stores.redis_agent_registry import RedisAgentRegistry


@pytest.fixture
def redis_client():
    r = _redis.Redis(host="localhost", port=6379, db=15, decode_responses=True)
    r.flushdb()
    yield r
    r.flushdb()
    r.close()


@pytest.fixture
def registry(redis_client):
    return RedisAgentRegistry(redis_client)


def test_register_and_get(registry):
    a = AgentProfile(agent_id="gw-1", gateway_url="http://10.0.0.1:8642", registered_at=time.time())
    registry.register(a)
    got = registry.get("gw-1")
    assert got is not None
    assert got.agent_id == "gw-1"
    assert got.status == "online"


def test_update_status(registry):
    a = AgentProfile(agent_id="gw-2", gateway_url="http://10.0.0.2:8642", registered_at=time.time())
    registry.register(a)
    registry.update_status("gw-2", "degraded")
    got = registry.get("gw-2")
    assert got.status == "degraded"


def test_update_load(registry):
    a = AgentProfile(agent_id="gw-3", gateway_url="http://10.0.0.3:8642", registered_at=time.time())
    registry.register(a)
    registry.update_load("gw-3", 5)
    got = registry.get("gw-3")
    assert got.current_load == 5


def test_deregister(registry):
    a = AgentProfile(agent_id="gw-4", gateway_url="http://10.0.0.4:8642", registered_at=time.time())
    registry.register(a)
    registry.deregister("gw-4")
    assert registry.get("gw-4") is None


def test_list_agents(registry):
    for i in range(3):
        a = AgentProfile(agent_id=f"gw-{i}", gateway_url=f"http://10.0.0.{i}:8642", registered_at=time.time())
        registry.register(a)
    agents = registry.list_agents()
    assert len(agents) == 3


def test_get_nonexistent(registry):
    assert registry.get("nope") is None
