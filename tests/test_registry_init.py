import os
import pytest
from unittest.mock import MagicMock, patch, mock_open
import importlib.util


def load_module(name, path):
    """使用 importlib.util 从文件路径加载模块"""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestWaitForRegistrationMarker:
    """测试 wait_for_registration_marker 函数"""

    def test_marker_ready(self):
        """标记文件内容为 ready 时返回 True"""
        module = load_module("ri", "/mnt/disk01/workspaces/worksummary/hermes-agent/scripts/registry-init.py")
        with patch("builtins.open", mock_open(read_data="ready\n")):
            with patch("time.sleep"):
                result = module.wait_for_registration_marker(timeout=1)
                assert result is True

    def test_marker_timeout_content(self):
        """标记文件内容为 timeout 时返回 True"""
        module = load_module("ri", "/mnt/disk01/workspaces/worksummary/hermes-agent/scripts/registry-init.py")
        with patch("builtins.open", mock_open(read_data="timeout\n")):
            with patch("time.sleep"):
                result = module.wait_for_registration_marker(timeout=1)
                assert result is True

    def test_marker_file_not_found_keeps_waiting(self):
        """标记文件不存在时继续等待（最终超时返回 True）"""
        def fake_open(path, *args, **kwargs):
            raise FileNotFoundError()

        module = load_module("ri", "/mnt/disk01/workspaces/worksummary/hermes-agent/scripts/registry-init.py")
        with patch("builtins.open", side_effect=fake_open):
            with patch("time.sleep"):
                result = module.wait_for_registration_marker(timeout=1)
                assert result is True


class TestExtractBatchName:
    """测试 extract_batch_name 函数"""

    def test_extracts_batch_name_from_pod_name(self):
        """从 Pod 名称提取 batch name"""
        module = load_module("ri", "/mnt/disk01/workspaces/worksummary/hermes-agent/scripts/registry-init.py")
        # Pod 名称格式: sandbox-{user_id}-{随机后缀}
        assert module.extract_batch_name("sandbox-alice-5f4b9c7d6-r8s9m") == "sandbox-alice"
        assert module.extract_batch_name("sandbox-bob-abc123") == "sandbox-bob"

    def test_fallback_for_unexpected_pod_name(self):
        """无法解析时返回原始 Pod 名称"""
        module = load_module("ri", "/mnt/disk01/workspaces/worksummary/hermes-agent/scripts/registry-init.py")
        assert module.extract_batch_name("unexpected-name") == "unexpected-name"


class TestRegisterEndpoints:
    """测试 register_endpoints 函数"""

    def test_register_new_endpoints(self):
        """Endpoints 不存在时创建"""
        from kubernetes.client.rest import ApiException

        mock_core = MagicMock()
        mock_core.read_endpoints.side_effect = ApiException(status=404)
        mock_core.create_namespaced_endpoints.return_value = MagicMock()

        os.environ["POD_NAME"] = "sandbox-alice-5f4b9c7d6-r8s9m"
        os.environ["POD_IP"] = "10.0.0.1"
        os.environ["SANDBOX_PORT"] = "8642"

        module = load_module("ri_new_ep", "/mnt/disk01/workspaces/worksummary/hermes-agent/scripts/registry-init.py")

        with patch.object(module, 'client') as mock_client:
            mock_client.CoreV1Api.return_value = mock_core
            result = module.register_endpoints()
            assert result is True
            mock_core.create_namespaced_endpoints.assert_called_once()
            # 验证调用参数中的 namespace
            call_kwargs = mock_core.create_namespaced_endpoints.call_args[1]
            assert call_kwargs["namespace"] == "hermes-agent"

    def test_register_existing_endpoints(self):
        """Endpoints 已存在时更新"""
        mock_core = MagicMock()
        mock_core.read_endpoints.return_value = MagicMock()

        os.environ["POD_NAME"] = "sandbox-alice-5f4b9c7d6-r8s9m"
        os.environ["POD_IP"] = "10.0.0.1"
        os.environ["SANDBOX_PORT"] = "8642"

        module = load_module("ri_exist_ep", "/mnt/disk01/workspaces/worksummary/hermes-agent/scripts/registry-init.py")

        with patch.object(module, 'client') as mock_client:
            mock_client.CoreV1Api.return_value = mock_core
            result = module.register_endpoints()
            assert result is True
            mock_core.patch_endpoints.assert_called_once()
            # 验证 Endpoints 名称是 batch name (sandbox-alice)
            call_args = mock_core.patch_endpoints.call_args
            assert call_args[1]["name"] == "sandbox-alice"