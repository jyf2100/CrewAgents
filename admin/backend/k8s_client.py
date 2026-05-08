import asyncio
import logging
import time
from typing import Optional

import kubernetes.client
import kubernetes.config
from kubernetes.client import (
    V1Deployment, V1Service, V1Secret, V1Pod,
    V1ObjectMeta, AppsV1Api, CoreV1Api, NetworkingV1Api,
)

logger = logging.getLogger("hermes-admin.k8s")

K8S_API_TIMEOUT = 30


class K8sClient:
    def __init__(self, namespace: str = "hermes-agent"):
        self.namespace = namespace
        try:
            kubernetes.config.load_incluster_config()
        except kubernetes.config.ConfigException:
            kubernetes.config.load_kube_config()
        self.apps_api = AppsV1Api()
        self.core_api = CoreV1Api()
        self.networking_api = NetworkingV1Api()
        # Separate ApiClient for stream/exec operations to avoid the global
        # ApiClient.request being patched by k8s_stream() during concurrent
        # regular API calls (race condition causes WebSocket handshake errors).
        self._stream_api = CoreV1Api(api_client=kubernetes.client.ApiClient())
        self._ingress_lock = asyncio.Lock()

    @staticmethod
    async def _k8s_call(fn, *args, **kwargs):
        return await asyncio.wait_for(
            asyncio.to_thread(fn, *args, **kwargs),
            timeout=K8S_API_TIMEOUT,
        )

    # Deployments
    async def get_deployment(self, name: str) -> Optional[V1Deployment]:
        try:
            return await self._k8s_call(
                self.apps_api.read_namespaced_deployment,
                name=name, namespace=self.namespace,
            )
        except kubernetes.client.ApiException as e:
            if e.status == 404:
                return None
            raise

    async def create_deployment(self, body: dict) -> V1Deployment:
        return await self._k8s_call(
            self.apps_api.create_namespaced_deployment,
            namespace=self.namespace, body=body,
        )

    async def delete_deployment(self, name: str) -> None:
        await self._k8s_call(
            self.apps_api.delete_namespaced_deployment,
            name=name, namespace=self.namespace,
            grace_period_seconds=0, propagation_policy="Foreground",
        )

    async def patch_deployment(self, name: str, body: dict) -> V1Deployment:
        return await self._k8s_call(
            self.apps_api.patch_namespaced_deployment,
            name=name, namespace=self.namespace, body=body,
        )

    # Services
    async def get_service(self, name: str) -> Optional[V1Service]:
        try:
            return await self._k8s_call(
                self.core_api.read_namespaced_service,
                name=name, namespace=self.namespace,
            )
        except kubernetes.client.ApiException as e:
            if e.status == 404:
                return None
            raise

    async def create_service(self, body: dict) -> V1Service:
        return await self._k8s_call(
            self.core_api.create_namespaced_service,
            namespace=self.namespace, body=body,
        )

    async def delete_service(self, name: str) -> None:
        await self._k8s_call(
            self.core_api.delete_namespaced_service,
            name=name, namespace=self.namespace,
        )

    # Secrets
    async def get_secret(self, name: str) -> Optional[V1Secret]:
        try:
            return await self._k8s_call(
                self.core_api.read_namespaced_secret,
                name=name, namespace=self.namespace,
            )
        except kubernetes.client.ApiException as e:
            if e.status == 404:
                return None
            raise

    async def create_secret(self, name: str, data: dict[str, str]) -> V1Secret:
        body = V1Secret(
            api_version="v1", kind="Secret",
            metadata=V1ObjectMeta(name=name, namespace=self.namespace),
            string_data=data, type="Opaque",
        )
        return await self._k8s_call(
            self.core_api.create_namespaced_secret,
            namespace=self.namespace, body=body,
        )

    async def delete_secret(self, name: str) -> None:
        await self._k8s_call(
            self.core_api.delete_namespaced_secret,
            name=name, namespace=self.namespace,
        )

    async def replace_secret(self, name: str, data: dict[str, str]) -> V1Secret:
        """Replace an existing secret's data."""
        body = V1Secret(
            api_version="v1", kind="Secret",
            metadata=V1ObjectMeta(name=name, namespace=self.namespace),
            string_data=data, type="Opaque",
        )
        return await self._k8s_call(
            self.core_api.replace_namespaced_secret,
            name=name, namespace=self.namespace, body=body,
        )

    async def list_agent_secrets(self) -> list:
        """List all hermes-gateway secret objects."""
        all_secrets = await self._k8s_call(
            self.core_api.list_namespaced_secret,
            namespace=self.namespace,
        )
        return [s for s in all_secrets.items
                if s.metadata.name.startswith("hermes-gateway") and s.metadata.name.endswith("-secret")]

    # Pods
    async def get_pods_for_deployment(self, deployment_name: str) -> list[V1Pod]:
        dep = await self.get_deployment(deployment_name)
        if not dep:
            return []
        labels = dep.spec.selector.match_labels
        label_selector = ",".join(f"{k}={v}" for k, v in labels.items())
        result = await self._k8s_call(
            self.core_api.list_namespaced_pod,
            namespace=self.namespace, label_selector=label_selector,
        )
        return result.items

    async def get_first_pod_name(self, deployment_name: str) -> Optional[str]:
        pods = await self.get_pods_for_deployment(deployment_name)
        for pod in pods:
            if pod.status.phase in ("Running", "Pending"):
                return pod.metadata.name
        return None

    # Events
    async def get_events(self, deployment_name: str) -> list:
        pods = await self.get_pods_for_deployment(deployment_name)
        pod_names = {p.metadata.name for p in pods}
        result = await self._k8s_call(
            self.core_api.list_namespaced_event,
            namespace=self.namespace, limit=200,
        )
        related = [
            e for e in result.items
            if (e.involved_object.name in pod_names
                or e.involved_object.name == deployment_name)
        ]
        related.sort(key=lambda e: e.last_timestamp or e.event_time or "", reverse=True)
        return related

    # Ingress

    async def get_ingress(self, name: str):
        """Read an ingress resource by name."""
        try:
            return await self._k8s_call(
                self.networking_api.read_namespaced_ingress,
                name=name, namespace=self.namespace,
            )
        except kubernetes.client.ApiException as e:
            if e.status == 404:
                return None
            raise

    # Ingress mutations (with lock for concurrent mutations)

    async def add_ingress_path(self, path: str, service_name: str, service_port: int) -> None:
        async with self._ingress_lock:
            ingress_name = "hermes-ingress"
            ingress = await self._k8s_call(
                self.networking_api.read_namespaced_ingress,
                name=ingress_name, namespace=self.namespace,
            )
            new_path_rule = {
                "path": f"{path}(/|$)(.*)",
                "pathType": "Prefix",
                "backend": {
                    "service": {
                        "name": service_name,
                        "port": {"number": service_port},
                    }
                },
            }
            if not ingress.spec.rules:
                raise RuntimeError("Ingress has no rules configured")
            paths = ingress.spec.rules[0].http.paths
            for p in paths:
                if p.path and p.path.startswith(path):
                    raise ValueError(f"Path {path} already exists in ingress")
            paths.append(new_path_rule)
            await self._k8s_call(
                self.networking_api.replace_namespaced_ingress,
                name=ingress_name, namespace=self.namespace, body=ingress,
            )

    async def remove_ingress_path(self, path_prefix: str) -> None:
        async with self._ingress_lock:
            ingress_name = "hermes-ingress"
            ingress = await self._k8s_call(
                self.networking_api.read_namespaced_ingress,
                name=ingress_name, namespace=self.namespace,
            )
            if not ingress.spec.rules:
                return
            paths = ingress.spec.rules[0].http.paths
            original_len = len(paths)
            ingress.spec.rules[0].http.paths = [
                p for p in paths
                if not (p.path and p.path.startswith(path_prefix))
            ]
            if len(ingress.spec.rules[0].http.paths) < original_len:
                await self._k8s_call(
                    self.networking_api.replace_namespaced_ingress,
                    name=ingress_name, namespace=self.namespace, body=ingress,
                )

    # Wait for deployment ready
    async def wait_deployment_ready(self, name: str, timeout_seconds: int = 300,
                                     poll_interval_seconds: int = 5) -> bool:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            dep = await self._k8s_call(
                self.apps_api.read_namespaced_deployment,
                name=name, namespace=self.namespace,
            )
            if (dep.status.available_replicas or 0) >= (dep.spec.replicas or 1):
                return True
            await asyncio.sleep(poll_interval_seconds)
        return False

    # List resources (public wrappers)
    async def list_deployments(self) -> list:
        """List all deployments in the namespace."""
        result = await self._k8s_call(
            self.apps_api.list_namespaced_deployment,
            namespace=self.namespace,
        )
        return result.items

    async def list_nodes(self) -> list:
        """List all cluster nodes."""
        result = await self._k8s_call(self.core_api.list_node)
        return result.items

    # Metrics (optional, graceful fallback)
    async def get_pod_metrics(self, pod_name: str) -> Optional[dict]:
        try:
            from kubernetes.client import CustomObjectsApi
            co = CustomObjectsApi(api_client=self.apps_api.api_client)
            return await self._k8s_call(
                co.get_namespaced_custom_object,
                group="metrics.k8s.io", version="v1beta1",
                namespace=self.namespace, plural="pods", name=pod_name,
            )
        except Exception:
            return None

    async def get_node_metrics(self) -> list[dict]:
        """Get node-level metrics from metrics-server."""
        try:
            from kubernetes.client import CustomObjectsApi
            co = CustomObjectsApi(api_client=self.apps_api.api_client)
            result = await self._k8s_call(
                co.list_cluster_custom_object,
                group="metrics.k8s.io", version="v1beta1",
                plural="nodes",
            )
            return result.get("items", [])
        except Exception:
            return []

    # Exec into pod
    async def run_command(self, pod_name: str, command: list[str]) -> tuple[str, str]:
        """Run a one-shot command in a pod and return (stdout, stderr)."""
        from kubernetes.stream import stream as k8s_stream
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(
                    k8s_stream,
                    self._stream_api.connect_get_namespaced_pod_exec,
                    name=pod_name,
                    namespace=self.namespace,
                    command=command,
                    stdin=False,
                    stdout=True,
                    stderr=True,
                    tty=False,
                    _preload_content=True,
                ),
                timeout=15,
            )
            return result, ""
        except Exception as e:
            return "", str(e)

    async def exec_pod(self, pod_name: str, command: list[str] | None = None):
        """Create an interactive exec stream into a pod. Returns a kubernetes WSClient."""
        from kubernetes.stream import stream as k8s_stream
        if command is None:
            command = ["/bin/sh", "-c", "if command -v bash >/dev/null 2>&1; then exec bash; else exec sh; fi"]
        return await asyncio.wait_for(
            asyncio.to_thread(
                k8s_stream,
                self._stream_api.connect_get_namespaced_pod_exec,
                name=pod_name,
                namespace=self.namespace,
                command=command,
                stdin=True,
                stdout=True,
                stderr=True,
                tty=True,
                _preload_content=False,
            ),
            timeout=K8S_API_TIMEOUT,
        )

    async def get_file_size(self, pod_name: str, path: str) -> int:
        """Get file size in pod without reading content. Returns -1 on error."""
        from kubernetes.stream import stream as k8s_stream
        import shlex
        safe = shlex.quote(path)
        cmd = ["sh", "-c", f"stat -c%s {safe} 2>/dev/null || echo -1"]
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(
                    k8s_stream,
                    self._stream_api.connect_get_namespaced_pod_exec,
                    name=pod_name,
                    namespace=self.namespace,
                    command=cmd,
                    stdin=False,
                    stdout=True,
                    stderr=False,
                    tty=False,
                    _preload_content=True,
                ),
                timeout=10,
            )
            size = int(result.strip())
            return max(size, -1)
        except Exception:
            return -1

    async def read_file_from_pod(self, pod_name: str, path: str) -> tuple[bytes, str]:
        """Read a file from a pod via exec. Returns (content_bytes, error_msg).
        Uses base64 encoding to safely handle binary files.
        Resolves symlinks inside the pod via realpath to prevent blocked-prefix bypass."""
        from kubernetes.stream import stream as k8s_stream
        import base64
        import shlex
        safe = shlex.quote(path)
        cmd = ["sh", "-c", f"""realpath=$(/usr/bin/realpath {safe} 2>/dev/null || echo {safe})
allowed=0
for p in /home /tmp /var/log /opt/hermes /opt/data; do
  case "$realpath" in
    $p|$p/*) allowed=1; break ;;
  esac
done
if [ "$allowed" = "0" ]; then
  echo '__BLOCKED__'
elif [ -f "$realpath" ] && [ -r "$realpath" ]; then
  base64 "$realpath"
else
  echo '__NOT_FOUND__'
fi"""]
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(
                    k8s_stream,
                    self._stream_api.connect_get_namespaced_pod_exec,
                    name=pod_name,
                    namespace=self.namespace,
                    command=cmd,
                    stdin=False,
                    stdout=True,
                    stderr=False,  # Discard stderr to prevent contamination
                    tty=False,
                    _preload_content=True,
                ),
                timeout=30,
            )
            if "__BLOCKED__" in result:
                return b"", "Access to this path is not allowed"
            if "__NOT_FOUND__" in result:
                return b"", "File not found or not readable"
            return base64.b64decode(result.strip()), ""
        except asyncio.TimeoutError:
            return b"", "Timeout reading file"
        except Exception as e:
            return b"", str(e)

    async def list_dir(self, pod_name: str, path: str) -> list[dict]:
        """List directory contents in a pod. Returns [{name, type, size}].
        type is 'd' (directory), 'f' (file), 'l' (symlink).
        Resolves symlinks inside the pod via realpath to prevent blocked-prefix bypass.
        """
        from kubernetes.stream import stream as k8s_stream
        import shlex
        safe = shlex.quote(path)
        cmd = [
            "sh", "-c",
            f"""realpath=$(/usr/bin/realpath {safe} 2>/dev/null || echo {safe})
allowed=0
for p in /home /tmp /var/log /opt/hermes /opt/data; do
  case "$realpath" in
    $p|$p/*) allowed=1; break ;;
  esac
done
if [ "$allowed" = "0" ]; then echo '__BLOCKED__'; exit 0; fi
if [ ! -d "$realpath" ]; then echo '__NOT_DIR__'; exit 0; fi
cd "$realpath"
for f in * .*; do
  [ "$f" = "." ] && continue
  [ "$f" = ".." ] && continue
  [ -e "$f" ] || [ -L "$f" ] || continue
  if [ -L "$f" ]; then
    printf 'l\t%s\t0\n' "$f"
  elif [ -d "$f" ]; then
    printf 'd\t%s\t0\n' "$f"
  else
    size=$(stat -c%s "$f" 2>/dev/null || echo 0)
    printf 'f\t%s\t%s\n' "$f" "$size"
  fi
done""",
        ]
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(
                    k8s_stream,
                    self._stream_api.connect_get_namespaced_pod_exec,
                    name=pod_name,
                    namespace=self.namespace,
                    command=cmd,
                    stdin=False,
                    stdout=True,
                    stderr=False,  # Discard stderr to prevent contamination
                    tty=False,
                    _preload_content=True,
                ),
                timeout=15,
            )
            if "__BLOCKED__" in result:
                logger.warning("list_dir blocked for pod %s path %s (resolved to blocked prefix)", pod_name, path)
                return []
            if "__NOT_DIR__" in result:
                return []
            entries = []
            for line in result.strip().splitlines():
                line = line.strip()
                if not line or "\t" not in line:
                    continue
                parts = line.split("\t", 2)
                if len(parts) != 3:
                    continue
                entry_type, name, size_str = parts
                if not name:
                    continue
                try:
                    size = int(size_str)
                except ValueError:
                    size = 0
                entries.append({"name": name, "type": entry_type, "size": size})
            entries.sort(key=lambda e: (0 if e["type"] == "d" else 1, e["name"].lower()))
            return entries
        except asyncio.TimeoutError:
            return []
        except Exception as e:
            logger.warning("list_dir failed for pod %s path %s: %s", pod_name, path, e)
            return []

    async def write_file_to_pod(self, pod_name: str, path: str, content: bytes) -> None:
        """Write file content to a pod via exec + base64 decode. Creates parent dirs."""
        from kubernetes.stream import stream as k8s_stream
        import base64
        import shlex
        safe = shlex.quote(path)
        b64 = base64.b64encode(content).decode("ascii")
        cmd = ["sh", "-c", f"mkdir -p $(dirname {safe}) && printf '%s' '{b64}' | base64 -d > {safe}"]
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(
                    k8s_stream,
                    self._stream_api.connect_get_namespaced_pod_exec,
                    name=pod_name,
                    namespace=self.namespace,
                    command=cmd,
                    stdin=False,
                    stdout=True,
                    stderr=True,
                    tty=False,
                    _preload_content=True,
                ),
                timeout=30,
            )
            if isinstance(result, str) and result.strip():
                logger.warning("write_file_to_pod stderr for %s: %s", path, result.strip()[:200])
        except asyncio.TimeoutError:
            raise RuntimeError(f"Timeout writing file to pod {pod_name}")
        except Exception as e:
            raise RuntimeError(f"Failed to write file to pod {pod_name}: {e}")

    async def delete_file_from_pod(self, pod_name: str, path: str) -> None:
        """Delete a file in a pod via exec."""
        from kubernetes.stream import stream as k8s_stream
        import shlex
        safe = shlex.quote(path)
        cmd = ["sh", "-c", f"rm -f {safe}"]
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(
                    k8s_stream,
                    self._stream_api.connect_get_namespaced_pod_exec,
                    name=pod_name,
                    namespace=self.namespace,
                    command=cmd,
                    stdin=False,
                    stdout=True,
                    stderr=True,
                    tty=False,
                    _preload_content=True,
                ),
                timeout=10,
            )
            if isinstance(result, str) and result.strip():
                logger.warning("delete_file_from_pod stderr for %s: %s", path, result.strip()[:200])
        except asyncio.TimeoutError:
            raise RuntimeError(f"Timeout deleting file in pod {pod_name}")
        except Exception as e:
            raise RuntimeError(f"Failed to delete file in pod {pod_name}: {e}")
