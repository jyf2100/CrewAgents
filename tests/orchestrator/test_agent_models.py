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


# ===================================================================
# gateway_headers
# ===================================================================


class TestGatewayHeaders:
    """Tests for AgentProfile.gateway_headers() method."""

    def test_gateway_headers_with_api_key(self):
        """When api_key is set, headers include Authorization Bearer."""
        agent = AgentProfile(
            agent_id="a1",
            gateway_url="http://test:8642",
            registered_at=0,
            api_key="sk-123",
        )
        headers = agent.gateway_headers()
        assert headers["Authorization"] == "Bearer sk-123"
        assert headers["Content-Type"] == "application/json"

    def test_gateway_headers_without_api_key(self):
        """When api_key is empty, headers do NOT include Authorization."""
        agent = AgentProfile(
            agent_id="a1",
            gateway_url="http://test:8642",
            registered_at=0,
        )
        headers = agent.gateway_headers()
        assert "Authorization" not in headers
        assert headers["Content-Type"] == "application/json"

    def test_gateway_headers_with_empty_api_key(self):
        """Empty string api_key should not add Authorization header."""
        agent = AgentProfile(
            agent_id="a1",
            gateway_url="http://test:8642",
            registered_at=0,
            api_key="",
        )
        headers = agent.gateway_headers()
        assert "Authorization" not in headers

    def test_gateway_headers_always_has_content_type(self):
        """Content-Type is always present regardless of api_key."""
        agent = AgentProfile(
            agent_id="a1",
            gateway_url="http://test:8642",
            registered_at=0,
        )
        headers = agent.gateway_headers()
        assert "Content-Type" in headers
        assert headers["Content-Type"] == "application/json"
