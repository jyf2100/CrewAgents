#!/usr/bin/env python3
"""
ttl-manager.py: 常驻沙箱 TTL 回收。
"""
import os
import time

from kubernetes import client, config
from kubernetes.client.rest import ApiException

SANDBOX_TTL_MINUTES = int(os.getenv("SANDBOX_TTL_MINUTES", "30"))
K8S_NAMESPACE = os.getenv("K8S_NAMESPACE", "hermes-agent")
SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL_SECONDS", "300"))


def delete_batchsandbox(user_id: str) -> bool:
    custom_api = client.CustomObjectsApi()
    batch_name = f"sandbox-{user_id}"
    try:
        custom_api.delete_namespaced_custom_object(
            group="sandbox.opensandbox.io", version="v1alpha1",
            namespace=K8S_NAMESPACE, plural="batchsandboxes", name=batch_name
        )
        return True
    except ApiException as e:
        return e.status == 404


def deregister_endpoints(endpoints_name: str) -> bool:
    core_v1 = client.CoreV1Api()
    try:
        body = client.V1Endpoints(
            metadata=client.V1ObjectMeta(name=endpoints_name, namespace=K8S_NAMESPACE),
            subsets=[]
        )
        core_v1.patch_endpoints(name=endpoints_name, namespace=K8S_NAMESPACE, body=body)
        return True
    except ApiException as e:
        return e.status == 404


def scan_and_reclaim():
    sandbox_v1 = client.CustomObjectsApi()
    core_v1 = client.CoreV1Api()
    cutoff = int(time.time()) - (SANDBOX_TTL_MINUTES * 60)

    try:
        batch_sandboxes = sandbox_v1.list_namespaced_custom_object(
            group="sandbox.opensandbox.io", version="v1alpha1",
            namespace=K8S_NAMESPACE, plural="batchsandboxes"
        )
    except ApiException as e:
        print(f"[ttl-manager] Failed to list batchsandboxes: {e}")
        return

    for bs in batch_sandboxes.get("items", []):
        batch_name = bs["metadata"]["name"]
        user_id = bs["metadata"]["labels"].get("user_id")
        if not user_id:
            continue
        try:
            ep = core_v1.read_endpoints(name=batch_name, namespace=K8S_NAMESPACE)
            last_seen = int(ep.metadata.annotations.get("last_seen", "0"))
            if last_seen > 0 and last_seen < cutoff:
                print(f"[ttl-manager] Reclaiming {user_id}")
                delete_batchsandbox(user_id)
                deregister_endpoints(batch_name)
        except ApiException as e:
            if e.status != 404:
                print(f"[ttl-manager] Failed: {e}")


def main():
    try:
        config.load_incluster_config()
    except config.ConfigException:
        try:
            config.load_kube_config()
        except config.ConfigException:
            print("[ttl-manager] ERROR: No kubernetes config")
            return
    print(f"[ttl-manager] Starting (interval={SCAN_INTERVAL}s, TTL={SANDBOX_TTL_MINUTES}min)")
    while True:
        scan_and_reclaim()
        time.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    main()
