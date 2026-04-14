import time
import pytest


def test_ttl_manager_loads():
    """验证 ttl-manager 模块可以加载"""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "ttl_manager",
        "/mnt/disk01/workspaces/worksummary/hermes-agent/scripts/ttl-manager.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert hasattr(module, 'scan_and_reclaim')
    assert hasattr(module, 'delete_batchsandbox')
    assert hasattr(module, 'deregister_endpoints')
    assert hasattr(module, 'main')
