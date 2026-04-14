import pytest


def test_registry_agent_loads():
    """验证 registry-agent 模块可以加载"""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "registry_agent",
        "/mnt/disk01/workspaces/worksummary/hermes-agent/scripts/registry-agent.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert hasattr(module, 'DeregisterHandler')
    assert hasattr(module, 'main')
