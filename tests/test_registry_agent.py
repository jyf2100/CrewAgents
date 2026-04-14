import pytest
from unittest.mock import MagicMock, patch
from http.server import HTTPServer
import importlib.util
import os


def load_module(name, path):
    """使用 importlib.util 从文件路径加载模块"""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestExtractBatchName:
    """测试 _extract_batch_name 函数"""

    def test_extracts_batch_name_from_pod_name(self):
        """从 Pod 名称提取 batch name"""
        module = load_module("ra", "/mnt/disk01/workspaces/worksummary/hermes-agent/scripts/registry-agent.py")
        # Pod 名称格式: sandbox-{user_id}-{随机后缀}
        assert module._extract_batch_name("sandbox-alice-5f4b9c7d6-r8s9m") == "sandbox-alice"
        assert module._extract_batch_name("sandbox-bob-abc123") == "sandbox-bob"

    def test_fallback_for_unexpected_pod_name(self):
        """无法解析时返回原始 Pod 名称"""
        module = load_module("ra", "/mnt/disk01/workspaces/worksummary/hermes-agent/scripts/registry-agent.py")
        assert module._extract_batch_name("unexpected-name") == "unexpected-name"


class TestDeregisterHandler:
    """测试 DeregisterHandler 的 /deregister 端点"""

    def test_deregister_endpoint_exists(self):
        """POST /deregister 端点存在"""
        module = load_module("ra", "/mnt/disk01/workspaces/worksummary/hermes-agent/scripts/registry-agent.py")
        assert hasattr(module.DeregisterHandler, 'do_POST')

    def test_health_endpoint_exists(self):
        """GET /health 端点存在"""
        module = load_module("ra", "/mnt/disk01/workspaces/worksummary/hermes-agent/scripts/registry-agent.py")
        assert hasattr(module.DeregisterHandler, 'do_GET')


class TestDeregisterFunction:
    """测试 _deregister 函数（独立函数形式）"""

    def test_deregister_calls_patch_with_batch_name(self):
        """_deregister 使用 batch name 调用 patch_endpoints"""
        from kubernetes.client.rest import ApiException

        # Set env BEFORE loading module
        os.environ["POD_NAME"] = "sandbox-alice-5f4b9c7d6-r8s9m"
        os.environ["SANDBOX_PORT"] = "8642"

        mock_core = MagicMock()

        module = load_module("ra", "/mnt/disk01/workspaces/worksummary/hermes-agent/scripts/registry-agent.py")

        with patch.object(module, 'client') as mock_client:
            mock_client.CoreV1Api.return_value = mock_core
            module._deregister()
            mock_core.patch_endpoints.assert_called_once()
            call_args = mock_core.patch_endpoints.call_args
            assert call_args[1]["name"] == "sandbox-alice"

    def test_deregister_handles_404(self):
        """_deregister 处理 Endpoints 不存在的情况（不算错误）"""
        from kubernetes.client.rest import ApiException

        os.environ["POD_NAME"] = "sandbox-alice-5f4b9c7d6-r8s9m"
        os.environ["SANDBOX_PORT"] = "8642"

        mock_core = MagicMock()
        mock_core.patch_endpoints.side_effect = ApiException(status=404)

        module = load_module("ra2", "/mnt/disk01/workspaces/worksummary/hermes-agent/scripts/registry-agent.py")

        with patch.object(module, 'client') as mock_client:
            mock_client.CoreV1Api.return_value = mock_core
            # Should not raise, just returns (exits with 1 on non-404)
            try:
                module._deregister()
            except SystemExit:
                pytest.fail("_deregister should not exit on 404")

    def test_deregister_exits_on_other_api_error(self):
        """_deregister 在非 404 API 错误时退出"""
        from kubernetes.client.rest import ApiException

        os.environ["POD_NAME"] = "sandbox-alice-5f4b9c7d6-r8s9m"
        os.environ["SANDBOX_PORT"] = "8642"

        mock_core = MagicMock()
        mock_core.patch_endpoints.side_effect = ApiException(status=500)

        module = load_module("ra3", "/mnt/disk01/workspaces/worksummary/hermes-agent/scripts/registry-agent.py")

        with patch.object(module, 'client') as mock_client:
            mock_client.CoreV1Api.return_value = mock_core
            with pytest.raises(SystemExit):
                module._deregister()