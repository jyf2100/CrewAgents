"""
gateway/sandbox_router.py: 沙箱发现 + 路由逻辑。

提供:
- SandboxRouter.get_sandbox_url(user_id) -> str  # 通过 BatchSandbox label selector 获取 pod IP
- SandboxRouter.is_pool_full() -> bool            # 检查池是否满载
- SandboxRouter.create_sandbox(user_id) -> bool   # 创建沙箱（幂等）
- SandboxRouter.wait_for_sandbox(user_id) -> str  # 等待沙箱就绪
"""
import os
import time
from typing import Optional

from kubernetes import client, config
from kubernetes.client.rest import ApiException
import json
from datetime import datetime, timezone, timedelta

K8S_NAMESPACE = os.getenv("K8S_NAMESPACE", "hermes-agent")
SANDBOX_TTL_MINUTES = int(os.getenv("SANDBOX_TTL_MINUTES", "30"))
ENDPOINTS_ANNOTATION = "sandbox.opensandbox.io/endpoints"


class SandboxRouter:
    def __init__(self):
        # K8s 配置只初始化一次
        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()
        self._core_v1 = client.CoreV1Api()
        self._sandbox_v1 = client.CustomObjectsApi()

    def get_sandbox_url(self, user_id: str) -> Optional[str]:
        """通过 BatchSandbox 的 endpoints 注解直接获取 Pod IP"""
        batch_name = f"sandbox-{user_id}"
        try:
            bs = self._sandbox_v1.get_namespaced_custom_object(
                group="sandbox.opensandbox.io",
                version="v1alpha1",
                namespace=K8S_NAMESPACE,
                plural="batchsandboxes",
                name=batch_name
            )
            annotations = bs.get("metadata", {}).get("annotations", {})
            ips_json = annotations.get(ENDPOINTS_ANNOTATION, "[]")
            ips = json.loads(ips_json)
            if ips and ips[0]:
                return f"http://{ips[0]}:8642"
            return None
        except ApiException as e:
            if e.status == 404:
                return None
            raise
        except Exception:
            return None

    def _update_endpoint_timestamp(self, user_id: str):
        """更新 Endpoints 的 last_seen timestamp annotation"""
        batch_name = f"sandbox-{user_id}"
        try:
            body = client.V1Endpoints(
                metadata=client.V1ObjectMeta(
                    name=batch_name,
                    namespace=K8S_NAMESPACE,
                    annotations={"last_seen": str(int(time.time()))}
                )
            )
            self._core_v1.patch_endpoints(
                name=batch_name,
                namespace=K8S_NAMESPACE,
                body=body
            )
        except Exception:
            pass

    def create_sandbox(self, user_id: str) -> bool:
        """创建 BatchSandbox（幂等：已存在时返回 True）"""
        pool_name = os.getenv("SANDBOX_POOL_NAME", "hermes-sandbox-pool")
        batch_name = f"sandbox-{user_id}"

        body = {
            "apiVersion": "sandbox.opensandbox.io/v1alpha1",
            "kind": "BatchSandbox",
            "metadata": {
                "name": batch_name,
                "namespace": K8S_NAMESPACE,
                "labels": {
                    "user_id": user_id
                }
            },
            "spec": {
                "poolRef": pool_name,
                "replicas": 1
            }
        }

        try:
            self._sandbox_v1.create_namespaced_custom_object(
                group="sandbox.opensandbox.io",
                version="v1alpha1",
                namespace=K8S_NAMESPACE,
                plural="batchsandboxes",
                body=body
            )
            return True
        except ApiException as e:
            if e.status == 409:
                return True
            print(f"[SandboxRouter] Failed to create BatchSandbox: {e}")
            return False

    def wait_for_sandbox(self, user_id: str, timeout: int = 60) -> Optional[str]:
        """等待沙箱就绪并返回 URL，超时返回 None"""
        start = time.time()
        while time.time() - start < timeout:
            url = self.get_sandbox_url(user_id)
            if url:
                return url
            time.sleep(2)
        return None

    def get_or_create_sandbox(self, user_id: str) -> Optional[str]:
        """获取或创建沙箱，返回沙箱 URL"""
        url = self.get_sandbox_url(user_id)
        if url:
            self._update_endpoint_timestamp(user_id)
            return url

        if not self.create_sandbox(user_id):
            return None

        return self.wait_for_sandbox(user_id)

    def is_pool_full(self) -> bool:
        """检查沙箱池是否已满。满返回 True，未满返回 False."""
        pool_name = os.getenv("SANDBOX_POOL_NAME", "hermes-sandbox-pool")
        try:
            pool = self._sandbox_v1.get_namespaced_custom_object(
                group="sandbox.opensandbox.io",
                version="v1alpha1",
                namespace=K8S_NAMESPACE,
                plural="pools",
                name=pool_name
            )
            status = pool.get("status", {})
            allocated = status.get("allocated", 0)
            pool_max = pool.get("spec", {}).get("capacitySpec", {}).get("poolMax", 30)
            return allocated >= pool_max
        except Exception as e:
            print(f"[SandboxRouter] Failed to check pool capacity: {e}")
            return False


# 全局单例
_sandbox_router: Optional[SandboxRouter] = None


def get_sandbox_router() -> SandboxRouter:
    global _sandbox_router
    if _sandbox_router is None:
        _sandbox_router = SandboxRouter()
    return _sandbox_router