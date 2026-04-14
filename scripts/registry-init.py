#!/usr/bin/env python3
"""
registry-init.py: 沙箱 Pod init container 脚本。

在主容器启动前等待 Hermes Gateway API server 就绪，
然后将 Pod IP:port 注册到 Kubernetes Endpoints（名称 = user_id）。

Usage: python3 registry-init.py
（环境变量：POD_NAME, POD_IP, SANDBOX_PORT）
"""
import os
import sys
import time
import urllib.request
import urllib.error

from kubernetes import client, config
from kubernetes.client.rest import ApiException

SANDBOX_PORT = os.getenv("SANDBOX_PORT", "8642")
POD_NAME = os.getenv("POD_NAME")
POD_IP = os.getenv("POD_IP")
NAMESPACE = "hermes-agent"


def wait_for_gateway(timeout: int = 60) -> bool:
    """等待 Hermes Gateway API server 就绪（/health 返回 200）"""
    url = f"http://localhost:{SANDBOX_PORT}/health"
    start = time.time()
    while time.time() - start < timeout:
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    print(f"[registry-init] Gateway ready at {url}")
                    return True
        except (urllib.error.URLError, urllib.error.HTTPError):
            pass
        time.sleep(2)
    print(f"[registry-init] Timeout waiting for gateway at {url}")
    return False


def register_endpoints() -> bool:
    """将 Pod IP:port 注册到同名 Endpoints"""
    core_v1 = client.CoreV1Api()

    # Endpoints 名称从 POD_NAME 推断（格式：sandbox-<user_id>）
    endpoints_name = POD_NAME

    endpoints_body = client.V1Endpoints(
        metadata=client.V1ObjectMeta(name=endpoints_name, namespace=NAMESPACE),
        subsets=[
            client.V1EndpointSubset(
                addresses=[client.V1EndpointAddress(ip=POD_IP)],
                ports=[client.V1EndpointPort(port=int(SANDBOX_PORT), protocol="TCP")]
            )
        ]
    )

    try:
        # 尝试创建 Endpoints（若已存在则更新）
        existing = core_v1.read_endpoints(name=endpoints_name, namespace=NAMESPACE)
        # 存在则更新
        core_v1.patch_endpoints(name=endpoints_name, namespace=NAMESPACE, body=endpoints_body)
        print(f"[registry-init] Updated Endpoints/{endpoints_name} -> {POD_IP}:{SANDBOX_PORT}")
    except ApiException as e:
        if e.status == 404:
            # 不存在则创建
            core_v1.create_namespaced_endpoints(namespace=NAMESPACE, body=endpoints_body)
            print(f"[registry-init] Created Endpoints/{endpoints_name} -> {POD_IP}:{SANDBOX_PORT}")
        else:
            print(f"[registry-init] Failed to create Endpoints: {e}")
            return False
    return True


def main():
    if not POD_NAME or not POD_IP:
        print("[registry-init] ERROR: POD_NAME or POD_IP not set")
        sys.exit(1)

    try:
        config.load_incluster_config()
    except config.ConfigException:
        print("[registry-init] WARNING: Could not load in-cluster config, using kubeconfig")
        try:
            config.load_kube_config()
        except config.ConfigException:
            print("[registry-init] ERROR: No kubernetes config available")
            sys.exit(1)

    if not wait_for_gateway():
        print("[registry-init] Gateway not ready, skipping registration")
        sys.exit(0)  # 不阻止 Pod 启动，只是跳过注册

    if register_endpoints():
        print("[registry-init] Registration complete")
    else:
        print("[registry-init] Registration failed")
        sys.exit(1)


if __name__ == "__main__":
    main()