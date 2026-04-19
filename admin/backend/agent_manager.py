import asyncio
import datetime
import io
import json
import os
import re
import secrets
import shutil
import tarfile
import time
import logging
from typing import Any, AsyncGenerator, Optional

import httpx
import yaml
from fastapi import HTTPException, Request

from models import (
    ActionResponse, AgentDetailResponse, AgentListResponse, AgentStatus, AgentSummary,
    BackupRequest, BackupResponse, ClusterStatusResponse, ContainerStatus, CreateAgentRequest,
    CreateAgentResponse, CreateStepStatus, EnvVariable, EventListResponse,
    HealthResponse, K8sEvent, MessageResponse, NodeInfo, PodInfo, ResourceUsage,
    TestLLMRequest, TestLLMResponse, DefaultResourceLimits, EventType,
)
from k8s_client import K8sClient
from config_manager import ConfigManager
from constants import SECRET_PATTERNS, PROVIDER_URL_MAP, format_age
from templates import deployment_name

logger = logging.getLogger(__name__)


class AgentManager:
    def __init__(self, k8s: K8sClient, namespace: str = "hermes-agent",
                 config_mgr: ConfigManager | None = None):
        self.k8s = k8s
        self.namespace = namespace
        self.config_mgr = config_mgr or ConfigManager()
        from templates import TemplateGenerator
        self.tpl = TemplateGenerator()
        self._default_resources = DefaultResourceLimits()

    @staticmethod
    def _resolve_status(replicas: int, available: int, conditions=None) -> AgentStatus:
        """Determine agent status from deployment state."""
        if replicas == 0:
            return AgentStatus.stopped
        if available >= replicas:
            return AgentStatus.running
        if conditions:
            for c in conditions:
                if c.type == "Progressing" and c.status == "False":
                    return AgentStatus.failed
                if c.type == "Available" and c.status == "False":
                    return AgentStatus.failed
        return AgentStatus.pending

    # --- List Agents ---
    async def list_agents(self) -> AgentListResponse:
        deps = await self.k8s.list_deployments()
        agents = []
        for dep in deps:
            name = dep.metadata.name
            if not name.startswith("hermes-gateway"):
                continue
            # Extract agent number from name
            m = re.fullmatch(r"hermes-gateway(?:-(\d+))?", name)
            if not m:
                continue
            agent_num = int(m.group(1) or 0)

            replicas = dep.spec.replicas or 0
            available = dep.status.available_replicas or 0

            status = self._resolve_status(replicas, available, dep.status.conditions)

            # Age
            created = dep.metadata.creation_timestamp
            age_human = format_age(created)

            agents.append(AgentSummary(
                id=agent_num,
                name=name,
                status=status,
                url_path=f"/agent{agent_num}" if agent_num > 0 else "",
                resources=ResourceUsage(),
                restart_count=0,
                created_at=created,
                age_human=age_human,
            ))
        return AgentListResponse(agents=agents, total=len(agents))

    # --- Get Agent Detail ---
    async def get_agent_detail(self, agent_id: int) -> AgentDetailResponse:
        name = deployment_name(agent_id)
        dep = await self.k8s.get_deployment(name)
        if dep is None:
            raise HTTPException(404, f"Agent {name} not found")

        replicas = dep.spec.replicas or 0
        available = dep.status.available_replicas or 0

        status = self._resolve_status(replicas, available)

        pods_info = []
        pods = await self.k8s.get_pods_for_deployment(name)
        restart_count = 0
        for pod in pods:
            containers = []
            for cs in (pod.status.container_statuses or []):
                restart_count += cs.restart_count
                state = "waiting"
                if cs.state:
                    if cs.state.running:
                        state = "running"
                    elif cs.state.terminated:
                        state = "terminated"
                    elif cs.state.waiting:
                        state = "waiting"
                containers.append(ContainerStatus(
                    ready=cs.ready,
                    restart_count=cs.restart_count,
                    state=state,
                    reason=(cs.state.waiting.reason if cs.state.waiting else None) or
                           (cs.state.terminated.reason if cs.state.terminated else None),
                    image=cs.image,
                ))
            pods_info.append(PodInfo(
                name=pod.metadata.name,
                phase=pod.status.phase,
                pod_ip=pod.status.pod_ip,
                node_name=pod.spec.node_name,
                started_at=pod.status.start_time,
                containers=containers,
            ))

        created = dep.metadata.creation_timestamp
        age_human = format_age(created)

        return AgentDetailResponse(
            id=agent_id,
            name=name,
            status=status,
            url_path=f"/agent{agent_id}",
            namespace=self.namespace,
            labels=dep.metadata.labels or {},
            created_at=created,
            pods=pods_info,
            resources=ResourceUsage(),
            restart_count=restart_count,
            age_human=age_human,
            ingress_path=f"/agent{agent_id}",
        )

    # --- Create Agent ---
    async def create_agent(self, req: CreateAgentRequest) -> CreateAgentResponse:
        steps: list[CreateStepStatus] = []
        agent_num = req.agent_number
        name = deployment_name(agent_num)
        secret_name = f"{name}-secret"
        data_dir = f"/data/hermes/agent{agent_num}"

        # Pre-flight: check existing
        existing = await self.k8s.get_deployment(name)
        if existing is not None:
            raise HTTPException(409, f"Deployment {name} already exists")

        api_key = secrets.token_urlsafe(32)

        # Step 1: Create Secret
        step = CreateStepStatus(step=1, label="Creating Secret", status="running")
        steps.append(step)
        try:
            await self.k8s.create_secret(name=secret_name, data={"api_key": api_key})
            step.status = "done"
        except Exception as e:
            step.status = "failed"
            step.message = str(e)
            return CreateAgentResponse(agent_number=agent_num, name=name, created=False, steps=steps)

        # Step 2: Init data directory
        step = CreateStepStatus(step=2, label="Initializing data directory", status="running")
        steps.append(step)
        try:
            os.makedirs(data_dir, exist_ok=True)
            env_content = self.tpl.render_env(req.llm, req.extra_env)
            with open(f"{data_dir}/.env", "w") as f:
                f.write(env_content)
            config_content = self.tpl.render_config_yaml(
                default_model=req.llm.model,
                provider=req.llm.provider,
                base_url=req.llm.base_url,
                terminal_enabled=req.terminal_enabled,
                browser_enabled=req.browser_enabled,
                streaming_enabled=req.streaming_enabled,
                memory_enabled=req.memory_enabled,
                session_reset_enabled=req.session_reset_enabled,
            )
            with open(f"{data_dir}/config.yaml", "w") as f:
                f.write(config_content)
            with open(f"{data_dir}/SOUL.md", "w") as f:
                f.write(req.soul_md)
            step.status = "done"
        except Exception as e:
            step.status = "failed"
            step.message = str(e)
            await self.k8s.delete_secret(secret_name)
            return CreateAgentResponse(agent_number=agent_num, name=name, created=False, steps=steps)

        # Step 3: Create Deployment
        step = CreateStepStatus(step=3, label="Creating Deployment", status="running")
        steps.append(step)
        try:
            deployment_body = self.tpl.render_deployment(
                agent_number=agent_num, secret_name=secret_name, resources=req.resources,
                namespace=self.namespace,
            )
            await self.k8s.create_deployment(deployment_body)
            step.status = "done"
        except Exception as e:
            step.status = "failed"
            step.message = str(e)
            shutil.rmtree(data_dir, ignore_errors=True)
            await self.k8s.delete_secret(secret_name)
            return CreateAgentResponse(agent_number=agent_num, name=name, created=False, steps=steps)

        # Step 3b: Create Service
        step_svc = CreateStepStatus(step=4, label="Creating Service", status="running")
        steps.append(step_svc)
        try:
            service_body = self.tpl.render_service(agent_number=agent_num, namespace=self.namespace)
            await self.k8s.create_service(service_body)
            step_svc.status = "done"
        except Exception as e:
            step_svc.status = "failed"
            step_svc.message = str(e)
            await self.k8s.delete_deployment(name)
            shutil.rmtree(data_dir, ignore_errors=True)
            await self.k8s.delete_secret(secret_name)
            return CreateAgentResponse(agent_number=agent_num, name=name, created=False, steps=steps)

        # Step 4: Update Ingress
        step = CreateStepStatus(step=5, label="Updating Ingress", status="running")
        steps.append(step)
        try:
            # Remove stale ingress path first (in case of previous failed deployment)
            try:
                await self.k8s.remove_ingress_path(f"/agent{agent_num}")
            except Exception as e:
                logger.debug("Stale ingress cleanup: %s", e)
            await self.k8s.add_ingress_path(
                path=f"/agent{agent_num}", service_name=name, service_port=8642,
            )
            step.status = "done"
        except Exception as e:
            step.status = "failed"
            step.message = str(e)
            await self.k8s.delete_deployment(name)
            await self.k8s.delete_service(name)
            shutil.rmtree(data_dir, ignore_errors=True)
            await self.k8s.delete_secret(secret_name)
            return CreateAgentResponse(agent_number=agent_num, name=name, created=False, steps=steps)

        # Step 5: Wait for ready (quick check, max 30s to avoid nginx 504)
        step = CreateStepStatus(step=6, label="Waiting for ready", status="running")
        steps.append(step)
        try:
            ready = await self.k8s.wait_deployment_ready(name, timeout_seconds=30, poll_interval_seconds=5)
            step.status = "done" if ready else "running"
            if not ready:
                step.message = "Deployment is still starting, check dashboard for status"
        except Exception as e:
            step.status = "running"
            step.message = f"Status check skipped: {e}"

        created = True  # Resources created successfully
        return CreateAgentResponse(agent_number=agent_num, name=name, created=created, steps=steps)

    # --- Delete Agent ---
    async def delete_agent(self, agent_id: int, backup: bool = True) -> MessageResponse:
        name = deployment_name(agent_id)
        secret_name = f"{name}-secret"
        dep = await self.k8s.get_deployment(name)
        if dep is None:
            raise HTTPException(404, f"Agent {name} not found")
        if backup:
            try:
                await self._create_backup(agent_id)
            except Exception as e:
                logger.warning("Backup failed for agent %s, proceeding with delete: %s", agent_id, e)
        # Remove ingress path FIRST to avoid leftovers on partial failure
        try:
            await self.k8s.remove_ingress_path(f"/agent{agent_id}")
        except Exception as e:
            logger.warning("Failed to remove ingress path for agent %s: %s", agent_id, e)
        try:
            await self.k8s.delete_deployment(name)
        except Exception as e:
            logger.warning("Failed to delete deployment %s: %s", name, e)
        try:
            await self.k8s.delete_service(name)
        except Exception as e:
            logger.warning("Failed to delete service %s: %s", name, e)
        try:
            await self.k8s.delete_secret(secret_name)
        except Exception as e:
            logger.warning("Failed to delete secret %s: %s", secret_name, e)
        data_dir = f"/data/hermes/agent{agent_id}"
        shutil.rmtree(data_dir, ignore_errors=True)
        return MessageResponse(message=f"Agent {name} deleted")

    # --- Restart Agent ---
    async def restart_agent(self, agent_id: int) -> ActionResponse:
        name = deployment_name(agent_id)
        dep = await self.k8s.get_deployment(name)
        if dep is None:
            raise HTTPException(404, f"Agent {name} not found")
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        patch = {
            "spec": {
                "template": {
                    "metadata": {
                        "annotations": {"kubectl.kubernetes.io/restartedAt": now}
                    }
                }
            }
        }
        await self.k8s.patch_deployment(name, patch)
        return ActionResponse(agent_number=agent_id, action="restart", success=True, message="Restart triggered")

    # --- Scale Agent ---
    async def scale_agent(self, agent_id: int, replicas: int, action: str) -> ActionResponse:
        name = deployment_name(agent_id)
        dep = await self.k8s.get_deployment(name)
        if dep is None:
            raise HTTPException(404, f"Agent {name} not found")
        patch = {"spec": {"replicas": replicas}}
        await self.k8s.patch_deployment(name, patch)
        return ActionResponse(agent_number=agent_id, action=action, success=True, message=f"Scaled to {replicas}")

    # --- Health Check ---
    async def check_health(self, agent_id: int) -> HealthResponse:
        service_name = deployment_name(agent_id)
        url = f"http://{service_name}.{self.namespace}.svc.cluster.local:8642/health"
        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url)
                latency_ms = (time.monotonic() - start) * 1000
                raw = resp.json()
                if resp.status_code == 200 and raw.get("status") == "ok":
                    return HealthResponse(status="ok", gateway_raw=raw,
                                         latency_ms=round(latency_ms, 1),
                                         checked_at=datetime.datetime.now(datetime.timezone.utc))
                return HealthResponse(status="error", gateway_raw=raw,
                                     latency_ms=round(latency_ms, 1),
                                     checked_at=datetime.datetime.now(datetime.timezone.utc))
        except Exception as e:
            return HealthResponse(status="error",
                                 checked_at=datetime.datetime.now(datetime.timezone.utc),
                                 gateway_raw={"error": str(e)})

    # --- Stream Logs ---
    async def stream_logs(self, agent_id: int, tail: int = 500,
                          follow: bool = True, request: Request | None = None,
                          max_duration: float = 300.0) -> AsyncGenerator[str, None]:
        """Stream pod logs over SSE.

        The K8s ``read_namespaced_pod_log`` with ``follow=True`` returns a
        *synchronous* iterator that blocks the calling thread on network I/O.
        The old implementation iterated it inside an ``async`` function which
        **blocked the uvicorn event-loop** and starved every other request
        (health checks, API calls, etc.), leading to 503s and Pod restarts.

        Fix: run the blocking iteration inside ``loop.run_in_executor`` so it
        lives on a real OS thread, and bridge lines to the async generator
        through a ``queue.SimpleQueue`` (thread-safe, no asyncio dependency).

        ``max_duration`` caps the total connection time (seconds) so that a
        long-running follow stream cannot hold resources forever.
        """
        import queue as _queue_mod

        name = deployment_name(agent_id)
        pod_name = await self.k8s.get_first_pod_name(name)
        if not pod_name:
            yield f"event: error\ndata: {json.dumps({'message': 'No running pod found'})}\n\n"
            return

        _line_q: _queue_mod.SimpleQueue[str | None] = _queue_mod.SimpleQueue()

        def _read_stream_sync():
            """Run in a worker thread -- read lines and push to a thread-safe queue."""
            try:
                log_stream = self.k8s.core_api.read_namespaced_pod_log(
                    name=pod_name, namespace=self.namespace,
                    tail_lines=tail, follow=follow, _preload_content=False,
                )
                for line in log_stream:
                    decoded = line.decode("utf-8", errors="replace").rstrip("\n")
                    _line_q.put(decoded)
            except Exception:
                pass  # Swallowed -- the generator will notice the sentinel
            finally:
                _line_q.put(None)  # sentinel signals end-of-stream

        loop = asyncio.get_running_loop()
        # Submit the blocking work to the default thread-pool executor.
        stream_future = loop.run_in_executor(None, _read_stream_sync)

        start_time = time.monotonic()
        try:
            while True:
                # --- Enforce max duration ---
                remaining = max_duration - (time.monotonic() - start_time)
                if remaining <= 0:
                    yield (f"event: info\ndata: "
                           f"{json.dumps({'message': 'Max connection duration reached, closing stream.'})}\n\n")
                    break

                # --- Check client disconnect ---
                if request and await request.is_disconnected():
                    break

                # --- Drain lines from the thread-safe queue ---
                wait_secs = min(15.0, remaining)
                try:
                    line = await asyncio.wait_for(
                        loop.run_in_executor(None, _line_q.get, True, wait_secs),
                        timeout=wait_secs + 1.0,
                    )
                except (asyncio.TimeoutError, Exception):
                    # Timeout / empty queue -- send keep-alive ping
                    yield ": ping\n\n"
                    continue

                if line is None:
                    break

                payload = json.dumps({
                    "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "message": line, "pod": pod_name,
                })
                yield f"event: log\ndata: {payload}\n\n"
        except Exception as e:
            yield f"event: error\ndata: {json.dumps({'message': f'Log stream error: {e}'})}\n\n"
        finally:
            yield "event: done\ndata: {}\n\n"
            # Best-effort cancellation of the background thread work.
            if not stream_future.done():
                stream_future.cancel()

    # --- Events ---
    async def get_events(self, agent_id: int) -> EventListResponse:
        name = deployment_name(agent_id)
        raw_events = await self.k8s.get_events(name)
        events = []
        for e in raw_events:
            ts = e.last_timestamp or e.event_time
            age_human = ""
            if ts:
                if isinstance(ts, datetime.datetime):
                    age_human = format_age(ts)
                else:
                    age_human = ""
            events.append(K8sEvent(
                type=EventType(e.type) if e.type in ("Normal", "Warning") else EventType.normal,
                reason=e.reason or "",
                message=e.message or "",
                count=e.count or 1,
                source=e.source.component if e.source else None,
                first_timestamp=e.first_timestamp,
                last_timestamp=e.last_timestamp,
                age_human=age_human,
            ))
        return EventListResponse(agent_number=agent_id, events=events)

    # --- Resource Usage ---
    async def get_resource_usage(self, agent_id: int) -> ResourceUsage:
        name = deployment_name(agent_id)
        pods = await self.k8s.get_pods_for_deployment(name)
        resources = ResourceUsage()
        for pod in pods:
            if pod.status.phase == "Running":
                metrics = await self.k8s.get_pod_metrics(pod.metadata.name)
                if metrics and "containers" in metrics:
                    for c in metrics["containers"]:
                        usage = c.get("usage", {})
                        cpu = usage.get("cpu", "0")
                        mem = usage.get("memory", "0")
                        if cpu.endswith("n"):
                            resources.cpu_cores = (resources.cpu_cores or 0) + int(cpu[:-1]) / 1e9
                        elif cpu.endswith("m"):
                            resources.cpu_cores = (resources.cpu_cores or 0) + int(cpu[:-1]) / 1000
                        if mem.endswith("Ki"):
                            resources.memory_bytes = (resources.memory_bytes or 0) + int(mem[:-2]) * 1024
        return resources

    # --- Backup ---
    async def _create_backup(self, agent_id: int) -> str:
        name = deployment_name(agent_id)
        secret_name = f"{name}-secret"
        timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
        filename = f"agent{agent_id}-{timestamp}.tar.gz"
        backup_dir = "/data/hermes/_backups"
        os.makedirs(backup_dir, exist_ok=True)
        backup_path = os.path.join(backup_dir, filename)
        with tarfile.open(backup_path, "w:gz") as tar:
            # K8s resources
            try:
                dep = await self.k8s.get_deployment(name)
                if dep:
                    yaml_bytes = yaml.dump(dep.to_dict(), default_flow_style=False).encode()
                    info = tarfile.TarInfo(name="k8s-resources/deployment.yaml")
                    info.size = len(yaml_bytes)
                    tar.addfile(info, io.BytesIO(yaml_bytes))
            except Exception:
                pass
            try:
                svc = await self.k8s.get_service(name)
                if svc:
                    yaml_bytes = yaml.dump(svc.to_dict(), default_flow_style=False).encode()
                    info = tarfile.TarInfo(name="k8s-resources/service.yaml")
                    info.size = len(yaml_bytes)
                    tar.addfile(info, io.BytesIO(yaml_bytes))
            except Exception:
                pass
            # Data dir with masked secrets
            data_dir = f"/data/hermes/agent{agent_id}"
            if os.path.isdir(data_dir):
                env_path = os.path.join(data_dir, ".env")
                if os.path.isfile(env_path):
                    with open(env_path) as ef:
                        env_lines = ef.readlines()
                    masked_lines = []
                    for line in env_lines:
                        stripped = line.strip()
                        if stripped and "=" in stripped and not stripped.startswith("#"):
                            key, _, _ = stripped.partition("=")
                            if SECRET_PATTERNS.search(key.strip()):
                                masked_lines.append(f"{key.strip()}=****\n")
                                continue
                        masked_lines.append(line)
                    masked_bytes = "".join(masked_lines).encode("utf-8")
                    info = tarfile.TarInfo(name="data/.env")
                    info.size = len(masked_bytes)
                    tar.addfile(info, io.BytesIO(masked_bytes))
                    for item in os.listdir(data_dir):
                        if item == ".env":
                            continue
                        item_path = os.path.join(data_dir, item)
                        if os.path.isfile(item_path):
                            tar.add(item_path, arcname=f"data/{item}")
                else:
                    tar.add(data_dir, arcname="data", recursive=True)
        return backup_path

    async def backup_agent(self, agent_id: int, req: BackupRequest) -> BackupResponse:
        timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
        filename = f"agent{agent_id}-{timestamp}.tar.gz"
        backup_path = await self._create_backup(agent_id)
        # Rename to expected filename
        expected_path = os.path.join(os.path.dirname(backup_path), filename)
        if backup_path != expected_path:
            os.replace(backup_path, expected_path)
        size_bytes = os.path.getsize(expected_path)
        return BackupResponse(
            agent_number=agent_id, filename=filename,
            size_bytes=size_bytes, download_url=f"/admin/api/backups/{filename}",
        )

    # --- Test LLM Connection ---
    async def test_llm(self, req: TestLLMRequest) -> TestLLMResponse:
        base_url = req.base_url or PROVIDER_URL_MAP.get(req.provider, PROVIDER_URL_MAP["openrouter"])
        url = f"{base_url.rstrip('/')}/chat/completions"
        payload = {"model": req.model, "messages": [{"role": "user", "content": "Hi"}], "max_tokens": 5, "temperature": 0}
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {req.api_key}"}
        if req.provider == "anthropic" and "anthropic.com" in base_url:
            url = f"{base_url.rstrip('/')}/messages"
            payload = {"model": req.model, "messages": [{"role": "user", "content": "Hi"}], "max_tokens": 5}
            headers = {"Content-Type": "application/json", "x-api-key": req.api_key, "anthropic-version": "2023-06-01"}
        elif req.provider == "minimax" and "minimaxi.com" in base_url:
            url = f"{base_url.rstrip('/')}/messages"
            payload = {"model": req.model, "messages": [{"role": "user", "content": "Hi"}], "max_tokens": 5}
            headers = {"Content-Type": "application/json", "Authorization": f"Bearer {req.api_key}", "anthropic-version": "2023-06-01"}
        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(url, json=payload, headers=headers)
                latency_ms = round((time.monotonic() - start) * 1000, 1)
                body = resp.text
                if resp.status_code == 200:
                    preview = None
                    try:
                        data = json.loads(body)
                        preview = data.get("choices", [{}])[0].get("message", {}).get("content", "")[:200]
                        if not preview:
                            preview = data.get("content", [{}])[0].get("text", "")[:200]
                    except Exception:
                        pass
                    return TestLLMResponse(success=True, latency_ms=latency_ms, model_used=req.model, response_preview=preview)
                error_msg = f"HTTP {resp.status_code}"
                try:
                    err_data = json.loads(body)
                    error_msg += ": " + (err_data.get("error", {}).get("message", "") or err_data.get("message", "") or body[:200])
                except Exception:
                    error_msg += ": " + body[:200]
                # Sanitize error to avoid leaking API keys
                safe_error = re.sub(r'Bearer\s+\S+', 'Bearer ***', error_msg)
                return TestLLMResponse(success=False, latency_ms=latency_ms, model_used=req.model, error=safe_error)
        except Exception as e:
            safe_error = re.sub(r'Bearer\s+\S+', 'Bearer ***', str(e))
            return TestLLMResponse(success=False, latency_ms=round((time.monotonic() - start) * 1000, 1), model_used=req.model, error=safe_error)

    # --- Cluster Status ---
    async def get_cluster_status(self) -> ClusterStatusResponse:
        results = await asyncio.gather(
            self.k8s.list_nodes(),
            self.k8s.list_deployments(),
            return_exceptions=True,
        )
        nodes = results[0] if not isinstance(results[0], Exception) else []
        try:
            node_infos = []
            for node in nodes:
                cpu_cap = node.status.capacity.get("cpu", "?")
                mem_cap = node.status.capacity.get("memory", "?")
                disk_total_gb = None
                disk_used_gb = None
                try:
                    stat = os.statvfs("/data/hermes")
                    disk_total_gb = round(stat.f_blocks * stat.f_frsize / 1e9, 1)
                    disk_used_gb = round((stat.f_blocks - stat.f_bfree) * stat.f_frsize / 1e9, 1)
                except Exception:
                    pass
                node_infos.append(NodeInfo(
                    name=node.metadata.name, cpu_capacity=cpu_cap, memory_capacity=mem_cap,
                    disk_total_gb=disk_total_gb, disk_used_gb=disk_used_gb,
                ))
        except Exception:
            node_infos = []
        deps = results[1] if not isinstance(results[1], Exception) else []
        # Count agents
        try:
            deps = deps if deps else []
            total = sum(1 for d in deps if d.metadata.name.startswith("hermes-gateway"))
            running = sum(1 for d in deps if d.metadata.name.startswith("hermes-gateway") and (d.status.available_replicas or 0) > 0)
        except Exception:
            total = running = 0
        return ClusterStatusResponse(nodes=node_infos, namespace=self.namespace, total_agents=total, running_agents=running)

    def get_default_resource_limits(self) -> DefaultResourceLimits:
        return self._default_resources

    def set_default_resource_limits(self, limits: DefaultResourceLimits) -> None:
        self._default_resources = limits
