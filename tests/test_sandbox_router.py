import pytest
from unittest.mock import MagicMock, patch
from gateway.sandbox_router import SandboxRouter


class TestSandboxRouter:
    def setup_method(self):
        self.router = SandboxRouter()

    def test_get_sandbox_url_found(self):
        """BatchSandbox 存在时通过 Pod IP 返回正确 URL"""
        mock_batch = MagicMock()
        mock_batch.metadata.name = "sandbox-user_123"

        mock_bs_list = {"items": [mock_batch]}

        mock_pod = MagicMock()
        mock_pod.status.pod_ip = "10.244.1.45"

        mock_sandbox_v1 = MagicMock()
        mock_sandbox_v1.list_namespaced_custom_object.return_value = mock_bs_list
        self.router._sandbox_v1 = mock_sandbox_v1

        mock_core_v1 = MagicMock()
        mock_core_v1.read_namespaced_pod.return_value = mock_pod
        self.router._core_v1 = mock_core_v1

        url = self.router.get_sandbox_url("user_123")
        assert url == "http://10.244.1.45:8642"
        mock_sandbox_v1.list_namespaced_custom_object.assert_called_once()
        mock_core_v1.read_namespaced_pod.assert_called_once()

    def test_get_sandbox_url_not_found(self):
        """BatchSandbox 不存在时返回 None"""
        from kubernetes.client.rest import ApiException

        mock_sandbox_v1 = MagicMock()
        mock_sandbox_v1.list_namespaced_custom_object.return_value = {"items": []}
        self.router._sandbox_v1 = mock_sandbox_v1

        url = self.router.get_sandbox_url("user_123")
        assert url is None

    def test_get_sandbox_url_pod_not_ready(self):
        """Pod IP 未分配时返回 None"""
        mock_batch = MagicMock()
        mock_batch.metadata.name = "sandbox-user_123"

        mock_pod = MagicMock()
        mock_pod.status.pod_ip = None

        mock_bs_list = {"items": [mock_batch]}

        mock_sandbox_v1 = MagicMock()
        mock_sandbox_v1.list_namespaced_custom_object.return_value = mock_bs_list
        self.router._sandbox_v1 = mock_sandbox_v1

        mock_core_v1 = MagicMock()
        mock_core_v1.read_namespaced_pod.return_value = mock_pod
        self.router._core_v1 = mock_core_v1

        url = self.router.get_sandbox_url("user_123")
        assert url is None

    def test_wait_for_sandbox_timeout(self):
        """沙箱未就绪时超时返回 None"""
        with patch.object(self.router, 'get_sandbox_url', return_value=None):
            with patch('time.sleep'):
                result = self.router.wait_for_sandbox("user_123", timeout=3)
                assert result is None

    def test_create_sandbox_idempotent(self):
        """create_sandbox 对已存在的沙箱返回 True（幂等）"""
        from kubernetes.client.rest import ApiException

        mock_sandbox_v1 = MagicMock()
        mock_sandbox_v1.create_namespaced_custom_object.side_effect = ApiException(status=409)
        self.router._sandbox_v1 = mock_sandbox_v1

        result = self.router.create_sandbox("alice")
        assert result is True

    def test_is_pool_full(self):
        """池满时 is_pool_full 返回 True"""
        mock_pool = {
            "status": {"allocated": 30},
            "spec": {"capacitySpec": {"poolMax": 30}}
        }

        mock_sandbox_v1 = MagicMock()
        mock_sandbox_v1.get_namespaced_custom_object.return_value = mock_pool
        self.router._sandbox_v1 = mock_sandbox_v1

        result = self.router.is_pool_full()
        assert result is True

    def test_is_pool_not_full(self):
        """池未满时 is_pool_full 返回 False"""
        mock_pool = {
            "status": {"allocated": 10},
            "spec": {"capacitySpec": {"poolMax": 30}}
        }

        mock_sandbox_v1 = MagicMock()
        mock_sandbox_v1.get_namespaced_custom_object.return_value = mock_pool
        self.router._sandbox_v1 = mock_sandbox_v1

        result = self.router.is_pool_full()
        assert result is False
