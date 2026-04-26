import pytest
from unittest.mock import MagicMock, patch
from gateway.sandbox_router import SandboxRouter


class TestSandboxRouter:
    def setup_method(self):
        with patch('gateway.sandbox_router.config'):
            self.router = SandboxRouter()
        self.mock_sandbox_v1 = MagicMock()
        self.router._sandbox_v1 = self.mock_sandbox_v1

    def test_get_sandbox_url_found(self):
        """BatchSandbox endpoints 注解中有 Pod IP 时返回正确 URL"""
        mock_bs = {
            "metadata": {
                "annotations": {
                    "sandbox.opensandbox.io/endpoints": '["10.244.1.45"]'
                }
            }
        }
        self.mock_sandbox_v1.get_namespaced_custom_object.return_value = mock_bs

        url = self.router.get_sandbox_url("user_123")
        assert url == "http://10.244.1.45:8642"
        self.mock_sandbox_v1.get_namespaced_custom_object.assert_called_once_with(
            group="sandbox.opensandbox.io",
            version="v1alpha1",
            namespace="hermes-agent",
            plural="batchsandboxes",
            name="sandbox-user_123"
        )

    def test_get_sandbox_url_not_found(self):
        """BatchSandbox 不存在时返回 None"""
        from kubernetes.client.rest import ApiException

        self.mock_sandbox_v1.get_namespaced_custom_object.side_effect = ApiException(status=404)

        url = self.router.get_sandbox_url("user_123")
        assert url is None

    def test_get_sandbox_url_pod_not_ready(self):
        """endpoints 注解为空时返回 None（Pod 尚未就绪）"""
        mock_bs = {
            "metadata": {
                "annotations": {}
            }
        }
        self.mock_sandbox_v1.get_namespaced_custom_object.return_value = mock_bs

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

        self.mock_sandbox_v1.create_namespaced_custom_object.side_effect = ApiException(status=409)

        result = self.router.create_sandbox("alice")
        assert result is True

    def test_is_pool_full(self):
        """池满时 is_pool_full 返回 True"""
        mock_pool = {
            "status": {"allocated": 30},
            "spec": {"capacitySpec": {"poolMax": 30}}
        }

        self.mock_sandbox_v1.get_namespaced_custom_object.return_value = mock_pool

        result = self.router.is_pool_full()
        assert result is True

    def test_is_pool_not_full(self):
        """池未满时 is_pool_full 返回 False"""
        mock_pool = {
            "status": {"allocated": 10},
            "spec": {"capacitySpec": {"poolMax": 30}}
        }

        self.mock_sandbox_v1.get_namespaced_custom_object.return_value = mock_pool

        result = self.router.is_pool_full()
        assert result is False

    def test_create_sandbox_with_expire_time(self):
        """create_sandbox 在 body 中设置 expireTime"""
        self.mock_sandbox_v1.create_namespaced_custom_object.return_value = {}

        result = self.router.create_sandbox("alice")
        assert result is True

        call_args = self.mock_sandbox_v1.create_namespaced_custom_object.call_args
        body = call_args[1]["body"]
        assert "expireTime" in body["spec"]
        assert body["spec"]["poolRef"] == "hermes-sandbox-pool"
        assert body["spec"]["replicas"] == 1

    def test_renew_expire_time(self):
        """_update_endpoint_timestamp 通过 patch 续期 expireTime"""
        self.mock_sandbox_v1.patch_namespaced_custom_object.return_value = {}

        self.router._update_endpoint_timestamp("alice")

        call_args = self.mock_sandbox_v1.patch_namespaced_custom_object.call_args
        assert call_args[1]["name"] == "sandbox-alice"
        body = call_args[1]["body"]
        assert "expireTime" in body["spec"]
        self.mock_sandbox_v1.patch_namespaced_custom_object.assert_called_once()

    def test_renew_expire_time_404_handled(self):
        """续期时 BatchSandbox 已被删除（404）不抛异常"""
        from kubernetes.client.rest import ApiException

        self.mock_sandbox_v1.patch_namespaced_custom_object.side_effect = ApiException(status=404)

        # 不应抛异常
        self.router._update_endpoint_timestamp("alice")

    def test_get_or_create_sandbox_renews_ttl_after_create(self):
        """get_or_create_sandbox 在创建后也会续期 TTL"""
        with patch.object(self.router, 'get_sandbox_url', side_effect=[None, "http://10.0.0.1:8642"]):
            with patch.object(self.router, 'create_sandbox', return_value=True):
                with patch.object(self.router, '_update_endpoint_timestamp') as mock_renew:
                    result = self.router.get_or_create_sandbox("user_123")
                    assert result == "http://10.0.0.1:8642"
                    mock_renew.assert_called_once_with("user_123")

    def test_is_pool_full_fails_closed(self):
        """is_pool_full 在 API 异常时返回 True（fail-closed）"""
        self.mock_sandbox_v1.get_namespaced_custom_object.side_effect = Exception("api unreachable")
        result = self.router.is_pool_full()
        assert result is True
