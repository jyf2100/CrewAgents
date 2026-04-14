import pytest
from unittest.mock import MagicMock, patch
from gateway.sandbox_router import SandboxRouter


class TestSandboxRouter:
    def setup_method(self):
        self.router = SandboxRouter()

    def test_get_sandbox_url_found(self):
        """Endpoints 存在时返回正确 URL"""
        mock_ep = MagicMock()
        mock_ep.subsets = [MagicMock()]
        mock_ep.subsets[0].addresses = [MagicMock()]
        mock_ep.subsets[0].addresses[0].ip = "10.244.1.45"
        mock_ep.subsets[0].ports = [MagicMock()]
        mock_ep.subsets[0].ports[0].port = 8642

        mock_core = MagicMock()
        mock_core.read_endpoints.return_value = mock_ep
        self.router._core_v1 = mock_core

        url = self.router.get_sandbox_url("user_123")
        assert url == "http://10.244.1.45:8642"

    def test_get_sandbox_url_not_found(self):
        """Endpoints 不存在时返回 None"""
        from kubernetes.client.rest import ApiException

        mock_core = MagicMock()
        mock_core.read_endpoints.side_effect = ApiException(status=404)
        self.router._core_v1 = mock_core

        url = self.router.get_sandbox_url("user_123")
        assert url is None

    def test_wait_for_sandbox_timeout(self):
        """沙箱未就绪时超时返回 None"""
        with patch.object(self.router, 'get_sandbox_url', return_value=None):
            with patch('time.sleep'):
                result = self.router.wait_for_sandbox("user_123", timeout=3)
                assert result is None