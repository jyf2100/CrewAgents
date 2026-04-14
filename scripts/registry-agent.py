#!/usr/bin/env python3
"""
registry-agent.py: 沙箱 Pod sidecar HTTP server。

监听 8080 端口，提供以下端点：
- GET /health          → 返回 200
- POST /deregister     → 从 Endpoints 注销当前 Pod

Usage: python3 registry-agent.py
（环境变量：POD_NAME, SANDBOX_PORT）
"""
import os
import sys
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from kubernetes import client, config
from kubernetes.client.rest import ApiException

SANDBOX_PORT = os.getenv("SANDBOX_PORT", "8642")
POD_NAME = os.getenv("POD_NAME")
NAMESPACE = "hermes-agent"


class DeregisterHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        print(f"[registry-agent] {args[0]}")

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"OK")
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/deregister":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Deregistering")
            # 异步执行注销，避免阻塞 HTTP 响应
            threading.Thread(target=_deregister, daemon=True).start()
        else:
            self.send_response(404)
            self.end_headers()

def _extract_batch_name(pod_name: str) -> str:
    """从 Pod 名称提取 batch name (sandbox-{user_id})"""
    parts = pod_name.split("-")
    if len(parts) >= 3 and parts[0] == "sandbox":
        return "-".join(parts[:2])
    return pod_name  # fallback


def _deregister():
    """从 Endpoints 注销当前 Pod"""
    core_v1 = client.CoreV1Api()
    batch_name = _extract_batch_name(POD_NAME)

    try:
        body = client.V1Endpoints(
            metadata=client.V1ObjectMeta(name=batch_name, namespace=NAMESPACE),
            subsets=[]
        )
        core_v1.patch_endpoints(name=batch_name, namespace=NAMESPACE, body=body)
        print(f"[registry-agent] Deregistered Endpoints/{batch_name}")
    except ApiException as e:
        if e.status == 404:
            print(f"[registry-agent] Endpoints/{batch_name} not found, skipping")
        else:
            print(f"[registry-agent] Failed to deregister: {e}")
            sys.exit(1)


def main():
    if not POD_NAME:
        print("[registry-agent] ERROR: POD_NAME not set")
        sys.exit(1)

    try:
        config.load_incluster_config()
    except config.ConfigException:
        try:
            config.load_kube_config()
        except config.ConfigException:
            print("[registry-agent] ERROR: No kubernetes config")
            sys.exit(1)

    server = HTTPServer(("0.0.0.0", 8080), DeregisterHandler)
    print(f"[registry-agent] Listening on 0.0.0.0:8080")
    server.serve_forever()


if __name__ == "__main__":
    main()