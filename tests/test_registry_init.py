import os
import pytest
from unittest.mock import MagicMock, patch, mock_open


class TestWaitForRegistrationMarker:
    """测试 wait_for_registration_marker 函数"""

    def test_marker_ready(self):
        """标记文件内容为 ready 时返回 True"""
        with patch("builtins.open", mock_open(read_data="ready\n")):
            with patch("time.sleep"):
                import importlib
                import scripts.registry_init
                importlib.reload(scripts.registry_init)
                result = scripts.registry_init.wait_for_registration_marker(timeout=1)
                assert result is True

    def test_marker_timeout(self):
        """标记文件不存在时超时返回 True"""
        with patch("builtins.open", side_effect=FileNotFoundError()):
            with patch("time.sleep"):
                import importlib
                import scripts.registry_init
                importlib.reload(scripts.registry_init)
                result = scripts.registry_init.wait_for_registration_marker(timeout=1)
                assert result is True


class TestRegisterEndpoints:
    """测试 register_endpoints 函数"""

    def test_register_new_endpoints(self):
        """Endpoints 不存在时创建"""
        from kubernetes.client.rest import ApiException

        mock_core = MagicMock()
        mock_core.read_endpoints.side_effect = ApiException(status=404)
        mock_core.create_namespaced_endpoints.return_value = MagicMock()

        with patch("scripts.registry_init.client.CoreV1Api", return_value=mock_core):
            with patch.dict(os.environ, {"POD_NAME": "sandbox-alice", "POD_IP": "10.0.0.1", "SANDBOX_PORT": "8642"}):
                import importlib
                import scripts.registry_init
                importlib.reload(scripts.registry_init)
                result = scripts.registry_init.register_endpoints()
                assert result is True
                mock_core.create_namespaced_endpoints.assert_called_once()

    def test_register_existing_endpoints(self):
        """Endpoints 已存在时更新"""
        mock_core = MagicMock()
        mock_core.read_endpoints.return_value = MagicMock()

        with patch("scripts.registry_init.client.CoreV1Api", return_value=mock_core):
            with patch.dict(os.environ, {"POD_NAME": "sandbox-alice", "POD_IP": "10.0.0.1", "SANDBOX_PORT": "8642"}):
                import importlib
                import scripts.registry_init
                importlib.reload(scripts.registry_init)
                result = scripts.registry_init.register_endpoints()
                assert result is True
                mock_core.patch_endpoints.assert_called_once()
