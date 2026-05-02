import os
import pytest

def test_config_loads_from_env():
    os.environ["ORCHESTRATOR_API_KEY"] = "test-key-123"
    os.environ["REDIS_URL"] = "redis://localhost:6379/0"
    os.environ["GATEWAY_API_KEY"] = "gw-key-456"
    from hermes_orchestrator.config import OrchestratorConfig
    cfg = OrchestratorConfig()
    assert cfg.api_key == "test-key-123"
    assert cfg.redis_url == "redis://localhost:6379/0"
    assert cfg.gateway_api_key == "gw-key-456"
    assert cfg.k8s_namespace == "hermes-agent"
    assert cfg.gateway_port == 8642
    assert cfg.agent_max_concurrent == 10
    assert cfg.task_max_wait == 600.0
    assert cfg.circuit_failure_threshold == 3
    assert cfg.circuit_recovery_timeout == 30.0
    for k in ["ORCHESTRATOR_API_KEY", "REDIS_URL", "GATEWAY_API_KEY"]:
        os.environ.pop(k, None)

def test_config_rejects_empty_api_key():
    os.environ.pop("ORCHESTRATOR_API_KEY", None)
    with pytest.raises(SystemExit):
        from hermes_orchestrator.config import OrchestratorConfig
        OrchestratorConfig()
