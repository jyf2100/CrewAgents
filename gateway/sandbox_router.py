"""
gateway/sandbox_router.py: 沙箱发现 + 路由逻辑。

提供:
- SandboxRouter.get_sandbox_url(user_id) -> str
- SandboxRouter.create_sandbox_if_needed(user_id) -> None
- SandboxRouter.get_user_policy(user_id) -> str
"""
import os
import time
from typing import Optional

from kubernetes import client, config
from kubernetes.client.rest import ApiException

K8S_NAMESPACE = os.getenv("K8S_NAMESPACE", "hermes-agent")
SANDBOX_TTL_MINUTES = int(os.getenv("SANDBOX_TTL_MINUTES", "30"))


class SandboxRouter:
    def __init__(self):
        self._core_v1 = None
        self._sandbox_v1 = None

    @property
    def core_v1(self):
        if self._core_v1 is None:
            try:
                config.load_incluster_config()
            except config.ConfigException:
                config.load_kube_config()
            self._core_v1 = client.CoreV1Api()
        return self._core_v1

    @property
    def sandbox_v1(self):
        if self._sandbox_v1 is None:
            try:
                config.load_incluster_config()
            except config.ConfigException:
                config.load_kube_config()
            self._sandbox_v1 = client.CustomObjectsApi()
        return self._sandbox_v1

    def get_sandbox_url(self, user_id: str) -> Optional[str]:
        """查询 Endpoints 获取沙箱地址，若不存在返回 None"""
        try:
            ep = self.core_v1.read_endpoints(name=user_id, namespace=K8S_NAMESPACE)
            if ep.subsets and ep.subsets[0].addresses:
                ip = ep.subsets[0].addresses[0].ip
                port = ep.subsets[0].ports[0].port
                return f"http://{ip}:{port}"
        except ApiException as e:
            if e.status == 404:
                return None
            raise
        return None

    def create_sandbox(self, user_id: str) -> bool:
        """创建 BatchSandbox（常驻沙箱）"""
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
            self.sandbox_v1.create_namespaced_custom_object(
                group="sandbox.opensandbox.io",
                version="v1alpha1",
                namespace=K8S_NAMESPACE,
                plural="batchsandboxes",
                body=body
            )
            return True
        except ApiException as e:
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
            return url

        # 沙箱不存在，尝试创建
        if not self.create_sandbox(user_id):
            return None

        # 等待沙箱就绪
        return self.wait_for_sandbox(user_id)

    def check_pool_capacity(self) -> bool:
        """检查沙箱池是否满载。满载时返回 True."""
        pool_name = os.getenv("SANDBOX_POOL_NAME", "hermes-sandbox-pool")
        try:
            pool = self.sandbox_v1.get_namespaced_custom_object(
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