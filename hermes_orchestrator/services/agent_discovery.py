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
        self._api_key_cache: dict[str, str] = {}

    async def _load_k8s_client(self):
        from kubernetes_asyncio import client, config as k8s_config
        try:
            k8s_config.load_incluster_config()
        except Exception:
            await k8s_config.load_kube_config()
        return client

    def _extract_agent_name(self, pod) -> str:
        """Extract gateway deployment name from pod (e.g. 'hermes-gateway-1' from 'hermes-gateway-1-abc123')."""
        pod_name = pod.metadata.name
        parts = pod_name.rsplit("-", 2)
        if len(parts) >= 3:
            return "-".join(parts[:-2])
        return pod_name

    async def _get_api_key(self, agent_name: str) -> str:
        """Read API key from K8s secret for the given agent."""
        if agent_name in self._api_key_cache:
            return self._api_key_cache[agent_name]
        try:
            client = await self._load_k8s_client()
            api = client.CoreV1Api()
            secret_name = f"{agent_name}-secret"
            secret = await api.read_namespaced_secret(secret_name, self._config.k8s_namespace)
            import base64
            key = base64.b64decode(secret.data.get("api_key", "")).decode()
            await api.api_client.close()
            self._api_key_cache[agent_name] = key
            return key
        except Exception as e:
            logger.warning("Failed to read API key for %s: %s", agent_name, e)
            return self._config.gateway_api_key

    async def discover_pods(self) -> list[AgentProfile]:
        client = await self._load_k8s_client()
        api = client.CoreV1Api()
        pods = await api.list_namespaced_pod(
            namespace=self._config.k8s_namespace,
            label_selector=GATEWAY_LABEL,
        )
        profiles = []
        for pod in pods.items:
            if pod.status.phase != "Running" or not pod.status.pod_ip:
                continue
            agent_name = self._extract_agent_name(pod)
            api_key = await self._get_api_key(agent_name)
            profile = self._pod_to_profile(pod)
            profile.api_key = api_key
            profiles.append(profile)
        await api.api_client.close()
        return profiles

    async def discover_capabilities(self, gateway_url: str, headers: dict | None = None) -> list[AgentCapability]:
        import aiohttp

        capabilities = []
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{gateway_url}/v1/models",
                    headers=headers or self._config.gateway_headers,
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
