from __future__ import annotations
import logging
import time
from typing import TYPE_CHECKING

from hermes_orchestrator.models.agent import AgentProfile, AgentCapability

if TYPE_CHECKING:
    from hermes_orchestrator.config import OrchestratorConfig

logger = logging.getLogger(__name__)

GATEWAY_LABEL = "app.kubernetes.io/component=gateway"


class AgentDiscoveryService:
    def __init__(self, config: OrchestratorConfig):
        self._config = config

    async def discover_pods(self) -> list[AgentProfile]:
        from kubernetes_asyncio import client, config as k8s_config
        try:
            k8s_config.load_incluster_config()
        except Exception:
            await k8s_config.load_kube_config()
        api = client.CoreV1Api()
        pods = await api.list_namespaced_pod(
            namespace=self._config.k8s_namespace,
            label_selector=GATEWAY_LABEL,
        )
        profiles = []
        for pod in pods.items:
            if pod.status.phase != "Running" or not pod.status.pod_ip:
                continue
            profiles.append(self._pod_to_profile(pod))
        await api.api_client.close()
        return profiles

    async def discover_capabilities(self, gateway_url: str) -> list[AgentCapability]:
        import aiohttp

        capabilities = []
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{gateway_url}/v1/models",
                    headers=self._config.gateway_headers,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status != 200:
                        logger.warning(
                            "Failed to query %s/v1/models: %s",
                            gateway_url,
                            resp.status,
                        )
                        return []
                    data = await resp.json()
                    for entry in data.get("data", []):
                        info = entry.get("info", {}) or {}
                        meta = info.get("meta", {}) or {}
                        capabilities.append(
                            AgentCapability(
                                gateway_url=gateway_url,
                                model_id=entry.get("id", ""),
                                capabilities=meta.get("capabilities", {}),
                                tool_ids=meta.get("toolIds", []),
                                supported_endpoints=entry.get(
                                    "supported_endpoints", []
                                ),
                            )
                        )
        except Exception as e:
            logger.warning(
                "Capability discovery failed for %s: %s", gateway_url, e
            )
        return capabilities

    def _build_pod_url(self, pod) -> str:
        return f"http://{pod.status.pod_ip}:{self._config.gateway_port}"

    def _pod_to_profile(self, pod) -> AgentProfile:
        return AgentProfile(
            agent_id=pod.metadata.name,
            gateway_url=self._build_pod_url(pod),
            registered_at=time.time(),
            max_concurrent=self._config.agent_max_concurrent,
            status="online",
        )
