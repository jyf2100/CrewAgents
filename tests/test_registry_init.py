import os
import sys
import pytest
import importlib.util
from unittest.mock import MagicMock, patch, mock_open

# 验证 registry-init 模块可以正确加载
def test_registry_init_loads():
    """验证 registry-init 模块可以加载"""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "registry_init",
        "/mnt/disk01/workspaces/worksummary/hermes-agent/scripts/registry-init.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert hasattr(module, 'wait_for_registration_marker')
    assert hasattr(module, 'register_endpoints')
    assert hasattr(module, 'main')


def test_wait_for_registration_marker_ready():
    """标记文件为 ready 时返回 True"""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "ri",
        "/mnt/disk01/workspaces/worksummary/hermes-agent/scripts/registry-init.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    with patch("builtins.open", mock_open(read_data="ready\n")):
        with patch("time.sleep"):
            result = module.wait_for_registration_marker(timeout=1)
            assert result is True


def test_wait_for_registration_marker_timeout():
    """标记文件不存在时超时返回 True"""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "ri2",
        "/mnt/disk01/workspaces/worksummary/hermes-agent/scripts/registry-init.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    with patch("builtins.open", side_effect=FileNotFoundError()):
        with patch("time.sleep"):
            result = module.wait_for_registration_marker(timeout=1)
            assert result is True


def test_wait_for_registration_marker_timeout_content():
    """标记文件为 timeout 时返回 True"""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "ri3",
        "/mnt/disk01/workspaces/worksummary/hermes-agent/scripts/registry-init.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    with patch("builtins.open", mock_open(read_data="timeout\n")):
        with patch("time.sleep"):
            result = module.wait_for_registration_marker(timeout=1)
            assert result is True
