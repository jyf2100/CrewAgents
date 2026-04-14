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
        """通过 BatchSandbox label selector 查找 pod IP"""
        try:
            # 1. 查找用户的 BatchSandbox
            batch_sandboxes = self.sandbox_v1.list_namespaced_custom_object(
                group="sandbox.opensandbox.io",
                version="v1alpha1",
                namespace=K8S_NAMESPACE,
                plural="batchsandboxes",
                label_selector=f"user_id={user_id}"
            )
            items = batch_sandboxes.get("items", [])
            if not items:
                return None
            batch_name = items[0]["metadata"]["name"]

            # 2. 获取 Pod IP
            pod = self.core_v1.read_namespaced_pod(
                name=batch_name,
                namespace=K8S_NAMESPACE
            )
            pod_ip = pod.status.pod_ip
            if not pod_ip:
                return None
            return f"http://{pod_ip}:8642"
        except ApiException as e:
            if e.status == 404:
                return None
            raise
        except Exception:
            return None

    def _update_endpoint_timestamp(self, user_id: str):
        """更新 Endpoints 的 last_seen timestamp annotation"""
        try:
            body = client.V1Endpoints(
                metadata=client.V1ObjectMeta(
                    name=user_id,
                    namespace=K8S_NAMESPACE,
                    annotations={"last_seen": str(int(time.time()))}
                )
            )
            self.core_v1.patch_endpoints(
                name=user_id,
                namespace=K8S_NAMESPACE,
                body=body
            )
        except Exception:
            pass  # 静默失败，不阻塞路由

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
            self.sandbox_v1.create_namespaced_custom_object(
                group="sandbox.opensandbox.io",
                version="v1alpha1",
                namespace=K8S_NAMESPACE,
                plural="batchsandboxes",
                body=body
            )
            return True
        except ApiException as e:
            if e.status == 409:  # Already exists - idempotent
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
            # 更新 last_seen annotation
            self._update_endpoint_timestamp(user_id)
            return url

        if not self.create_sandbox(user_id):
            return None

        return self.wait_for_sandbox(user_id)

    def is_pool_full(self) -> bool:
        """检查沙箱池是否已满。满返回 True，未满返回 False."""
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