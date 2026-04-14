import time
import pytest
from unittest.mock import MagicMock, patch
import importlib.util


def load_module(name, path):
    """使用 importlib.util 从文件路径加载模块"""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestScanAndReclaim:
    """测试 scan_and_reclaim 函数"""

    def test_reclaims_sandbox_when_idle(self):
        """last_seen 超过 TTL 时删除沙箱"""
        mock_ep = MagicMock()
        mock_ep.metadata.annotations = {"last_seen": str(int(time.time()) - 3600)}  # 1小时前
        mock_ep.metadata.name = "sandbox-alice"

        mock_bs_list = {"items": [{
            "metadata": {
                "name": "sandbox-alice",
                "labels": {"user_id": "alice"}
            }
        }]}

        mock_sandbox_v1 = MagicMock()
        mock_sandbox_v1.list_namespaced_custom_object.return_value = mock_bs_list

        mock_core_v1 = MagicMock()
        mock_core_v1.read_endpoints.return_value = mock_ep

        module = load_module("ttl_manager", "/mnt/disk01/workspaces/worksummary/hermes-agent/scripts/ttl-manager.py")

        with patch.object(module, 'client') as mock_client:
            mock_client.CustomObjectsApi.return_value = mock_sandbox_v1
            mock_client.CoreV1Api.return_value = mock_core_v1
            with patch.object(module, 'delete_batchsandbox') as mock_delete:
                with patch.object(module, 'deregister_endpoints') as mock_dereg:
                    module.scan_and_reclaim()
                    mock_delete.assert_called_once_with("alice")
                    mock_dereg.assert_called_once_with("sandbox-alice")

    def test_skips_active_sandbox(self):
        """last_seen 在 TTL 内时跳过"""
        mock_ep = MagicMock()
        mock_ep.metadata.annotations = {"last_seen": str(int(time.time()) - 60)}  # 1分钟前
        mock_ep.metadata.name = "sandbox-alice"

        mock_bs_list = {"items": [{
            "metadata": {
                "name": "sandbox-alice",
                "labels": {"user_id": "alice"}
            }
        }]}

        mock_sandbox_v1 = MagicMock()
        mock_sandbox_v1.list_namespaced_custom_object.return_value = mock_bs_list

        mock_core_v1 = MagicMock()
        mock_core_v1.read_endpoints.return_value = mock_ep

        module = load_module("ttl_manager", "/mnt/disk01/workspaces/worksummary/hermes-agent/scripts/ttl-manager.py")

        with patch.object(module, 'client') as mock_client:
            mock_client.CustomObjectsApi.return_value = mock_sandbox_v1
            mock_client.CoreV1Api.return_value = mock_core_v1
            with patch.object(module, 'delete_batchsandbox') as mock_delete:
                module.scan_and_reclaim()
                mock_delete.assert_not_called()

    def test_skips_sandbox_without_user_id_label(self):
        """没有 user_id label 的 BatchSandbox 被跳过"""
        mock_bs_list = {"items": [{
            "metadata": {
                "name": "sandbox-alice",
                "labels": {}  # no user_id
            }
        }]}

        mock_sandbox_v1 = MagicMock()
        mock_sandbox_v1.list_namespaced_custom_object.return_value = mock_bs_list

        mock_core_v1 = MagicMock()

        module = load_module("ttl_manager", "/mnt/disk01/workspaces/worksummary/hermes-agent/scripts/ttl-manager.py")

        with patch.object(module, 'client') as mock_client:
            mock_client.CustomObjectsApi.return_value = mock_sandbox_v1
            mock_client.CoreV1Api.return_value = mock_core_v1
            with patch.object(module, 'delete_batchsandbox') as mock_delete:
                module.scan_and_reclaim()
                mock_delete.assert_not_called()
                mock_core_v1.read_endpoints.assert_not_called()