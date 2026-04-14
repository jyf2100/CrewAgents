import time
import pytest
from unittest.mock import MagicMock, patch


class TestScanAndReclaim:
    """测试 scan_and_reclaim 函数"""

    def test_reclaims_sandbox_when_idle(self):
        """last_seen 超过 TTL 时删除沙箱"""
        cutoff = int(time.time()) - (30 * 60)  # 30分钟前

        mock_ep = MagicMock()
        mock_ep.metadata.annotations = {"last_seen": str(int(time.time()) - 3600)}  # 1小时前
        mock_ep.metadata.name = "sandbox-alice"

        mock_batch_sandbox = MagicMock()
        mock_batch_sandbox.metadata.name = "sandbox-alice"
        mock_batch_sandbox.metadata.labels = {"user_id": "alice"}

        mock_bs_list = {"items": [mock_batch_sandbox]}
        mock_ep_list = MagicMock()
        mock_ep_list.items = [mock_ep]

        mock_sandbox_v1 = MagicMock()
        mock_sandbox_v1.list_namespaced_custom_object.return_value = mock_bs_list

        mock_core_v1 = MagicMock()
        mock_core_v1.read_endpoints.return_value = mock_ep

        with patch("scripts.ttl_manager.client.CustomObjectsApi", return_value=mock_sandbox_v1):
            with patch("scripts.ttl_manager.client.CoreV1Api", return_value=mock_core_v1):
                with patch("scripts.ttl_manager.delete_batchsandbox") as mock_delete:
                    with patch("scripts.ttl_manager.deregister_endpoints") as mock_dereg:
                        import importlib
                        import scripts.ttl_manager
                        importlib.reload(scripts.ttl_manager)
                        scripts.ttl_manager.scan_and_reclaim()
                        mock_delete.assert_called_once_with("alice")
                        mock_dereg.assert_called_once_with("sandbox-alice")

    def test_skips_active_sandbox(self):
        """last_seen 在 TTL 内时跳过"""
        mock_ep = MagicMock()
        mock_ep.metadata.annotations = {"last_seen": str(int(time.time()) - 60)}  # 1分钟前
        mock_ep.metadata.name = "sandbox-alice"

        mock_batch_sandbox = MagicMock()
        mock_batch_sandbox.metadata.name = "sandbox-alice"
        mock_batch_sandbox.metadata.labels = {"user_id": "alice"}

        mock_bs_list = {"items": [mock_batch_sandbox]}

        mock_sandbox_v1 = MagicMock()
        mock_sandbox_v1.list_namespaced_custom_object.return_value = mock_bs_list

        mock_core_v1 = MagicMock()
        mock_core_v1.read_endpoints.return_value = mock_ep

        with patch("scripts.ttl_manager.client.CustomObjectsApi", return_value=mock_sandbox_v1):
            with patch("scripts.ttl_manager.client.CoreV1Api", return_value=mock_core_v1):
                with patch("scripts.ttl_manager.delete_batchsandbox") as mock_delete:
                    import importlib
                    import scripts.ttl_manager
                    importlib.reload(scripts.ttl_manager)
                    scripts.ttl_manager.scan_and_reclaim()
                    mock_delete.assert_not_called()
