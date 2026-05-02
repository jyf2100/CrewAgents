from hermes_orchestrator.models.agent import AgentProfile, AgentCapability


def test_agent_profile_defaults():
    a = AgentProfile(
        agent_id="gw-1", gateway_url="http://10.0.0.1:8642", registered_at=1000.0
    )
    assert a.status == "online"
    assert a.models == []
    assert a.current_load == 0
    assert a.max_concurrent == 10
    assert a.circuit_state == "closed"


def test_agent_profile_to_dict_roundtrip():
    a = AgentProfile(
        agent_id="gw-1", gateway_url="http://10.0.0.1:8642", registered_at=1000.0
    )
    d = a.to_dict()
    a2 = AgentProfile.from_dict(d)
    assert a2.agent_id == a.agent_id
    assert a2.gateway_url == a.gateway_url


def test_agent_capability():
    c = AgentCapability(
        gateway_url="http://10.0.0.1:8642", model_id="hermes-agent"
    )
    assert c.capabilities == {}
    assert c.tool_ids == []
