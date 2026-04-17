"""
gateway/sandbox_router.py: 沙箱发现 + 路由逻辑。

提供:
- SandboxRouter.get_sandbox_url(user_id) -> str  # 通过 BatchSandbox endpoints 注解获取 Pod IP
- SandboxRouter.is_pool_full() -> bool            # 检查池是否满载
- SandboxRouter.create_sandbox(user_id) -> bool   # 创建沙箱（幂等）
- SandboxRouter.wait_for_sandbox(user_id) -> str  # 等待沙箱就绪
"""
import os
import time
import logging
from typing import Optional

from kubernetes import client, config
from kubernetes.client.rest import ApiException
import json
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

K8S_NAMESPACE = os.getenv("K8S_NAMESPACE", "hermes-agent")
SANDBOX_TTL_MINUTES = int(os.getenv("SANDBOX_TTL_MINUTES", "30"))
ENDPOINTS_ANNOTATION = "sandbox.opensandbox.io/endpoints"


class SandboxRouter:
    _CRD_GROUP = "sandbox.opensandbox.io"
    _CRD_VERSION = "v1alpha1"
    _CRD_PLURAL = "batchsandboxes"

    def __init__(self):
        # K8s 配置只初始化一次
        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()
        self._sandbox_v1 = client.CustomObjectsApi()

    @staticmethod
    def _batch_name(user_id: str) -> str:
        return f"sandbox-{user_id}"

    def get_sandbox_url(self, user_id: str) -> Optional[str]:
        """通过 BatchSandbox 的 endpoints 注解直接获取 Pod IP"""
        batch_name = self._batch_name(user_id)
        try:
            bs = self._sandbox_v1.get_namespaced_custom_object(
                group=self._CRD_GROUP,
                version=self._CRD_VERSION,
                namespace=K8S_NAMESPACE,
                plural=self._CRD_PLURAL,
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
        except json.JSONDecodeError as e:
            logger.error("[SandboxRouter] Malformed endpoints annotation for %s: %s", batch_name, e)
            return None
        except Exception as e:
            logger.error("[SandboxRouter] Unexpected error getting sandbox URL for %s: %s", user_id, e)
            return None

    def _get_expire_time(self, minutes: int) -> str:
        """计算 expireTime（ISO 8601 UTC）"""
        expire = datetime.now(timezone.utc) + timedelta(minutes=minutes)
        return expire.strftime("%Y-%m-%dT%H:%M:%SZ")

    def _update_endpoint_timestamp(self, user_id: str):
        """续期 BatchSandbox expireTime，时长由 SANDBOX_TTL_MINUTES 环境变量控制"""
        batch_name = self._batch_name(user_id)
        new_expire = self._get_expire_time(SANDBOX_TTL_MINUTES)
        try:
            body = {"spec": {"expireTime": new_expire}}
            self._sandbox_v1.patch_namespaced_custom_object(
                group=self._CRD_GROUP,
                version=self._CRD_VERSION,
                namespace=K8S_NAMESPACE,
                plural=self._CRD_PLURAL,
                name=batch_name,
                body=body
            )
        except ApiException as e:
            if e.status == 404:
                return
            logger.error("[SandboxRouter] Failed to renew expireTime for %s: %s", batch_name, e)
        except Exception as e:
            logger.error("[SandboxRouter] Unexpected error renewing TTL for %s: %s", batch_name, e)

    def create_sandbox(self, user_id: str) -> bool:
        """创建 BatchSandbox（幂等：已存在时返回 True）"""
        pool_name = os.getenv("SANDBOX_POOL_NAME", "hermes-sandbox-pool")
        batch_name = self._batch_name(user_id)

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
                "replicas": 1,
                "expireTime": self._get_expire_time(SANDBOX_TTL_MINUTES)
            }
        }

        try:
            self._sandbox_v1.create_namespaced_custom_object(
                group=self._CRD_GROUP,
                version=self._CRD_VERSION,
                namespace=K8S_NAMESPACE,
                plural=self._CRD_PLURAL,
                body=body
            )
            return True
        except ApiException as e:
            if e.status == 409:
                return True
            logger.error("[SandboxRouter] Failed to create BatchSandbox %s: status=%s", batch_name, e.status)
            return False

    def wait_for_sandbox(self, user_id: str, timeout: int = 60) -> Optional[str]:
        """等待沙箱就绪并返回 URL，超时返回 None"""
        start = time.time()
        while time.time() - start < timeout:
            url = self.get_sandbox_url(user_id)
            if url:
                return url
            time.sleep(2)
        logger.warning("[SandboxRouter] Timed out waiting for sandbox %s after %ds", self._batch_name(user_id), timeout)
        return None

    def get_or_create_sandbox(self, user_id: str) -> Optional[str]:
        """获取或创建沙箱，返回沙箱 URL"""
        url = self.get_sandbox_url(user_id)
        if url:
            self._update_endpoint_timestamp(user_id)
            return url

        if not self.create_sandbox(user_id):
            return None

        url = self.wait_for_sandbox(user_id)
        if url:
            self._update_endpoint_timestamp(user_id)
        return url

    def is_pool_full(self) -> bool:
        """检查沙箱池是否已满。满载或 API 异常时返回 True（fail-closed），未满返回 False。"""
        pool_name = os.getenv("SANDBOX_POOL_NAME", "hermes-sandbox-pool")
        try:
            pool = self._sandbox_v1.get_namespaced_custom_object(
                group=self._CRD_GROUP,
                version=self._CRD_VERSION,
                namespace=K8S_NAMESPACE,
                plural="pools",
                name=pool_name
            )
            status = pool.get("status", {})
            allocated = status.get("allocated", 0)
            pool_max = pool.get("spec", {}).get("capacitySpec", {}).get("poolMax", 30)
            return allocated >= pool_max
        except Exception as e:
            logger.error("[SandboxRouter] Failed to check pool capacity: %s", e)
            return True


# 全局单例
_sandbox_router: Optional[SandboxRouter] = None


def get_sandbox_router() -> SandboxRouter:
    global _sandbox_router
    if _sandbox_router is None:
        _sandbox_router = SandboxRouter()
    return _sandbox_router
