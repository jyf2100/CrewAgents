import pytest
from unittest.mock import MagicMock, patch


class TestDeregisterHandler:
    """测试 DeregisterHandler 的 /health 和 /deregister 端点"""

    def test_health_endpoint(self):
        """GET /health 返回 200"""
        from scripts.registry_agent import DeregisterHandler

        handler = DeregisterHandler(MagicMock(), ("localhost", 8080))

        handler.path = "/health"
        with patch.object(handler, "send_response") as mock_send:
            with patch.object(handler, "send_header"):
                with patch.object(handler, "end_headers"):
                    with patch.object(handler, "wfile") as mock_wfile:
                        mock_wfile.write = MagicMock()
                        handler.do_GET()
                        mock_send.assert_called_with(200)

    def test_deregister_endpoint(self):
        """POST /deregister 返回 200"""
        from scripts.registry_agent import DeregisterHandler

        handler = DeregisterHandler(MagicMock(), ("localhost", 8080))
        handler.path = "/deregister"

        with patch.object(handler, "send_response") as mock_send:
            with patch.object(handler, "send_header"):
                with patch.object(handler, "end_headers"):
                    with patch.object(handler, "wfile") as mock_wfile:
                        mock_wfile.write = MagicMock()
                        with patch.object(handler, "_deregister") as mock_dereg:
                            handler.do_POST()
                            mock_send.assert_called_with(200)
                            mock_dereg.assert_called_once()

    def test_unknown_endpoint_returns_404(self):
        """未知路径返回 404"""
        from scripts.registry_agent import DeregisterHandler

        handler = DeregisterHandler(MagicMock(), ("localhost", 8080))
        handler.path = "/unknown"

        with patch.object(handler, "send_response") as mock_send:
            with patch.object(handler, "end_headers"):
                handler.do_GET()
                mock_send.assert_called_with(404)
