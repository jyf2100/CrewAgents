import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from hermes_orchestrator.services.agent_discovery import AgentDiscoveryService


@pytest.fixture
def discovery():
    cfg = MagicMock()
    cfg.k8s_namespace = "hermes-agent"
    cfg.gateway_port = 8642
    cfg.agent_max_concurrent = 10
    cfg.gateway_headers = {"Authorization": "Bearer test"}
    return AgentDiscoveryService(cfg)


def test_build_pod_url():
    svc = AgentDiscoveryService.__new__(AgentDiscoveryService)
    svc._config = MagicMock()
    svc._config.gateway_port = 8642
    pod = MagicMock()
    pod.status.pod_ip = "10.244.1.42"
    url = svc._build_pod_url(pod)
    assert url == "http://10.244.1.42:8642"


def test_pod_to_profile():
    svc = AgentDiscoveryService.__new__(AgentDiscoveryService)
    svc._config = MagicMock()
    svc._config.gateway_port = 8642
    svc._config.agent_max_concurrent = 10
    from datetime import datetime, timezone

    pod = MagicMock()
    pod.metadata.name = "hermes-gateway-1-abc"
    pod.status.pod_ip = "10.244.1.42"
    pod.status.phase = "Running"
    pod.metadata.creation_timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    profile = svc._pod_to_profile(pod)
    assert profile.agent_id == "hermes-gateway-1-abc"
    assert profile.gateway_url == "http://10.244.1.42:8642"
    assert profile.max_concurrent == 10
    assert profile.status == "online"
