#!/usr/bin/env python3
"""
registry-init.py: 沙箱 Pod init container 脚本。

轮询 /shared/registry_done 标记文件等待主容器 Hermes Gateway 就绪，
然后将 Pod IP:port 注册到 Kubernetes Endpoints。

Usage: python3 registry-init.py
（环境变量：POD_NAME, POD_IP, SANDBOX_PORT）
"""
import os
import sys
import time

from kubernetes import client, config
from kubernetes.client.rest import ApiException

SANDBOX_PORT = os.getenv("SANDBOX_PORT", "8642")
POD_NAME = os.getenv("POD_NAME")
POD_IP = os.getenv("POD_IP")
NAMESPACE = "hermes-agent"


def wait_for_registration_marker(timeout: int = 120) -> bool:
    """等待主容器 postStart 写入的标记文件"""
    marker_path = "/shared/registry_done"
    start = time.time()
    while time.time() - start < timeout:
        try:
            with open(marker_path, "r") as f:
                content = f.read().strip()
                if content == "ready":
                    print("[registry-init] Sandbox ready, proceeding with registration")
                    return True
                elif content == "timeout":
                    print("[registry-init] Sandbox startup timeout, proceeding anyway")
                    return True
        except FileNotFoundError:
            pass
        time.sleep(2)
    print(f"[registry-init] Timeout waiting for marker file {marker_path}")
    return True


def extract_batch_name(pod_name: str) -> str:
    """从 Pod 名称提取 batch name (sandbox-{user_id})"""
    # Pod 名称格式: sandbox-{user_id}-{随机后缀}
    # 例如: sandbox-alice-5f4b9c7d6-r8s9m -> sandbox-alice
    parts = pod_name.split("-")
    if len(parts) >= 3 and parts[0] == "sandbox":
        return "-".join(parts[:2])
    return pod_name  # fallback


def register_endpoints() -> bool:
    """将 Pod IP:port 注册到 batch name 命名的 Endpoints"""
    core_v1 = client.CoreV1Api()
    batch_name = extract_batch_name(POD_NAME)
    endpoints_name = batch_name

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
        existing = core_v1.read_endpoints(name=endpoints_name, namespace=NAMESPACE)
        core_v1.patch_endpoints(name=endpoints_name, namespace=NAMESPACE, body=endpoints_body)
        print(f"[registry-init] Updated Endpoints/{endpoints_name} -> {POD_IP}:{SANDBOX_PORT}")
    except ApiException as e:
        if e.status == 404:
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
        try:
            config.load_kube_config()
        except config.ConfigException:
            print("[registry-init] ERROR: No kubernetes config available")
            sys.exit(1)

    wait_for_registration_marker()
    if register_endpoints():
        print("[registry-init] Registration complete")
    else:
        print("[registry-init] Registration failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
