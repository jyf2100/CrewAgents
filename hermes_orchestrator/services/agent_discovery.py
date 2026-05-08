from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import time
from typing import TYPE_CHECKING

import httpx

from hermes_orchestrator.models.agent import AgentProfile, AgentCapability
from hermes_orchestrator.services.agent_selector import ROLE_TO_DOMAIN

if TYPE_CHECKING:
    from kubernetes_asyncio import client as k8s_client_module
    from hermes_orchestrator.config import OrchestratorConfig

logger = logging.getLogger(__name__)

GATEWAY_LABEL = "app.kubernetes.io/component=gateway"
CAPABILITIES_ANNOTATION = "hermes-agent.io/capabilities"
ROLE_ANNOTATION = "hermes-agent.io/role"

SHARED_SECRET_NAME = "hermes-db-secret"

# Mapping from agent deployment name to the corresponding key in hermes-db-secret
_AGENT_KEY_MAP: dict[str, str] = {
    "hermes-gateway-1": "api_key",
    "hermes-gateway-2": "api_key_2",
    "hermes-gateway-3": "api_key_3",
}


class _CircuitBreaker:
    """Simple circuit breaker for Admin API calls."""

    def __init__(self, failure_threshold: int = 3, cooldown: float = 300):
        self._failures = 0
        self._threshold = failure_threshold
        self._cooldown = cooldown
        self._last_failure: float = 0

    @property
    def is_open(self) -> bool:
        if self._failures < self._threshold:
            return False
        return time.time() - self._last_failure < self._cooldown

    def success(self):
        self._failures = 0

    def failure(self):
        self._failures += 1
        self._last_failure = time.time()


class AgentDiscoveryService:
    def __init__(self, config: OrchestratorConfig):
        self._config = config
        self._api_key_cache: dict[str, str] = {}
        self._k8s_api: k8s_client_module.CoreV1Api | None = None
        self._k8s_client_module: k8s_client_module | None = None
        # Admin API integration (Phase 2)
        self._admin_url = os.getenv("ADMIN_INTERNAL_URL", "")
        self._admin_token = os.getenv("ADMIN_INTERNAL_TOKEN", "")
        self._admin_cb = _CircuitBreaker()
        self._metadata_cache: dict[int, dict] = {}
        self._metadata_cache_ts: float = 0

    async def _ensure_k8s_client(self) -> k8s_client_module:
        """Lazy-initialize and cache the kubernetes client module and API instance."""
        if self._k8s_api is not None:
            return self._k8s_client_module  # type: ignore[return-value]

        from kubernetes_asyncio import client, config as k8s_config

        try:
            k8s_config.load_incluster_config()
        except Exception as exc:
            logger.debug(
                "In-cluster config failed (%s), trying kube_config", exc
            )
            await k8s_config.load_kube_config()

        self._k8s_client_module = client
        self._k8s_api = client.CoreV1Api()
        return client

    async def close(self) -> None:
        """Close the cached K8s API client to release resources."""
        if self._k8s_api is not None:
            await self._k8s_api.api_client.close()
            self._k8s_api = None
            self._k8s_client_module = None

    def _extract_agent_name(self, pod) -> str:
        """Extract gateway deployment name from pod metadata.

        Uses ownerReferences (ReplicaSet owned by Deployment) when available.
        Falls back to pod name parsing for pods without ownerReferences.
        """
        # Prefer ownerReferences: ReplicaSet name matches the Deployment name
        # for standard Kubernetes Deployments (e.g. hermes-gateway-10-abc123
        # has ownerReference to a ReplicaSet hermes-gateway-10-xxxx).
        try:
            owners = pod.metadata.owner_references
            if owners:
                # Use the first owner (typically a ReplicaSet)
                owner_name = owners[0].name
                # ReplicaSet names are <deployment>-<random>; strip the suffix
                rs_parts = owner_name.rsplit("-", 1)
                if len(rs_parts) >= 2:
                    return rs_parts[0]
                return owner_name
        except (AttributeError, IndexError):
            pass

        # Fallback: parse pod name.  Pod names are <deployment>-<replicaset-hash>-<pod-hash>.
        # We cannot reliably strip from the right for multi-digit numbers, so we
        # strip the last two hyphen-delimited segments.
        pod_name = pod.metadata.name
        parts = pod_name.rsplit("-", 2)
        if len(parts) >= 3:
            return "-".join(parts[:-2])
        return pod_name

    async def _get_api_key(self, agent_name: str) -> str:
        """Read API key from the shared hermes-db-secret for the given agent.

        Uses the _AGENT_KEY_MAP to look up the correct key (api_key, api_key_2,
        api_key_3) based on the agent deployment name.
        """
        if agent_name in self._api_key_cache:
            return self._api_key_cache[agent_name]
        try:
            await self._ensure_k8s_client()
            api = self._k8s_api
            secret_key = _AGENT_KEY_MAP.get(agent_name, "api_key")
            secret = await api.read_namespaced_secret(
                SHARED_SECRET_NAME, self._config.k8s_namespace
            )
            key = base64.b64decode(secret.data.get(secret_key, "")).decode()
            self._api_key_cache[agent_name] = key
            return key
        except Exception as e:
            logger.warning("Failed to read API key for %s: %s", agent_name, e)
            return self._config.gateway_api_key

    def _parse_tags_from_annotation(self, annotations: dict | None) -> list[str]:
        if not annotations:
            return []
        raw = annotations.get(CAPABILITIES_ANNOTATION, "")
        if not raw:
            return []
        raw = raw.strip()
        if raw.startswith("["):
            try:
                tags = json.loads(raw)
                if isinstance(tags, list):
                    return [str(t).strip().lower() for t in tags if str(t).strip()]
            except json.JSONDecodeError:
                pass
        return [t.strip().lower() for t in raw.split(",") if t.strip()]

    def _parse_role_from_annotation(self, annotations: dict | None) -> str:
        if not annotations:
            return "generalist"
        return annotations.get(ROLE_ANNOTATION, "generalist").strip().lower() or "generalist"

    def _extract_agent_number(self, agent_name: str) -> int | None:
        """Extract the agent number from a deployment name like 'hermes-gateway-1'.

        Returns None if no trailing number is found.
        """
        match = re.search(r"(\d+)\s*$", agent_name)
        return int(match.group(1)) if match else None

    async def _fetch_agent_metadata(self) -> dict[int, dict]:
        """Fetch agent tags/role/domain/skills from Admin API.

        Returns {agent_number: {tags, role, domain, skills}}.
        """
        if self._metadata_cache and time.time() - self._metadata_cache_ts < 30:
            return self._metadata_cache
        if not self._admin_url or not self._admin_token or self._admin_cb.is_open:
            return {}
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                resp = await client.get(
                    f"{self._admin_url}/internal/agents/metadata",
                    headers={"X-Internal-Token": self._admin_token},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    result = {item["agent_number"]: item for item in data}
                    self._metadata_cache = result
                    self._metadata_cache_ts = time.time()
                    self._admin_cb.success()
                    return result
        except Exception:
            self._admin_cb.failure()
            logger.debug(
                "Admin metadata API unavailable (failures=%d)",
                self._admin_cb._failures,
            )
        return {}

    async def discover_pods(self) -> list[AgentProfile]:
        # Clear API key cache on each discovery cycle to pick up secret rotations
        self._api_key_cache.clear()

        await self._ensure_k8s_client()
        api = self._k8s_api
        pods = await api.list_namespaced_pod(
            namespace=self._config.k8s_namespace,
            label_selector=GATEWAY_LABEL,
        )
        admin_meta = await self._fetch_agent_metadata()
        profiles = []
        for pod in pods.items:
            if pod.status.phase != "Running" or not pod.status.pod_ip:
                continue
            agent_name = self._extract_agent_name(pod)
            api_key = await self._get_api_key(agent_name)
            profile = self._pod_to_profile(pod)
            profile.api_key = api_key
            # Check Admin DB first, fall back to K8s annotations
            agent_number = self._extract_agent_number(agent_name)
            meta = admin_meta.get(agent_number) if agent_number else None
            if meta:
                profile.tags = meta.get("tags", [])
                profile.role = meta.get("role", "generalist")
                # Read domain from Admin API (fallback to role mapping)
                admin_domain = meta.get("domain", "")
                if admin_domain:
                    profile.domain = admin_domain
                else:
                    profile.domain = ROLE_TO_DOMAIN.get(profile.role, "generalist")
                # Read skills from Admin API (aggregated from AgentSkill)
                profile.skills = meta.get("skills", [])
            else:
                annotations = pod.metadata.annotations or {}
                profile.tags = self._parse_tags_from_annotation(annotations)
                profile.role = self._parse_role_from_annotation(annotations)
                # Fallback: derive domain from role via K8s annotation
                profile.domain = ROLE_TO_DOMAIN.get(profile.role, "generalist")
                profile.skills = []
            profiles.append(profile)
        # Discover capabilities in parallel
        await self._discover_all_capabilities(profiles)
        return profiles

    async def _discover_all_capabilities(self, profiles: list[AgentProfile]) -> None:
        async def _safe_discover(profile: AgentProfile) -> None:
            try:
                capabilities = await self.discover_capabilities(
                    profile.gateway_url,
                    headers=profile.gateway_headers(),
                )
                if capabilities:
                    profile.models = list({c.model_id for c in capabilities})
                    all_tool_ids: list[str] = []
                    for c in capabilities:
                        all_tool_ids.extend(c.tool_ids)
                    profile.tool_ids = sorted(set(all_tool_ids))
                    merged_caps: dict = {}
                    for c in capabilities:
                        merged_caps.update(c.capabilities)
                    profile.capabilities = merged_caps
                    logger.info(
                        "Discovered capabilities for %s: models=%s, tools=%d, tags=%s",
                        profile.agent_id, profile.models, len(profile.tool_ids),
                        profile.tags,
                    )
            except Exception as e:
                logger.warning(
                    "Capability discovery failed for %s: %s",
                    profile.agent_id, e,
                )
        await asyncio.gather(*[_safe_discover(p) for p in profiles])

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
