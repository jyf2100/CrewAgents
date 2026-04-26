# Hermes Agent K8s 多用户沙箱部署 - Critical 问题修复实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 K8s 多用户沙箱部署中的 Critical 和 Important 问题，包括 Endpoints 命名不匹配、init container 等待逻辑错误、PostgreSQL 存储、Secret 硬编码密码等。

**Architecture:** Gateway 改为通过 BatchSandbox CRD label selector 获取 Pod IP；init container 改为轮询共享卷标记文件；TTL manager 改为基于 Endpoints annotation 判断闲置。

**Tech Stack:** Kubernetes, Python, OpenSandbox CRD, PostgreSQL

---

## 文件结构

```
hermes-agent/
├── gateway/
│   └── sandbox_router.py              # [修改] label selector 获取 pod IP；annotation 更新时间戳；重命名方法
├── kubernetes/
│   └── sandbox/
│       └── pool.yaml                  # [修改] 添加 shared volume；postStart hook
├── scripts/
│   ├── registry-init.py               # [修改] 轮询标记文件而非等待端口
│   └── ttl-manager.py                 # [修改] 基于 BatchSandbox + annotation 判断闲置
├── kubernetes/postgres/
│   ├── secret.yaml                    # [修改] 密码改 placeholder
│   └── statefulset.yaml              # [修改] 完善注释
└── tests/
    ├── test_registry_init.py          # [新建] registry-init 单元测试
    ├── test_registry_agent.py         # [新建] registry-agent 单元测试
    └── test_ttl_manager.py            # [新建] ttl-manager 单元测试
```

---

## Task 1: 修改 Gateway sandbox_router.py（Endpoints 发现 + annotation）

**Files:**
- Modify: `gateway/sandbox_router.py`

- [ ] **Step 1: 读取当前 sandbox_router.py**

```bash
cat /mnt/disk01/workspaces/worksummary/hermes-agent/gateway/sandbox_router.py
```

- [ ] **Step 2: 写入修复后的 sandbox_router.py**

替换整个文件内容：

```python
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
```

- [ ] **Step 3: 验证语法**

```bash
python3 -m py_compile /mnt/disk01/workspaces/worksummary/hermes-agent/gateway/sandbox_router.py
```
Expected: (no output = success)

- [ ] **Step 4: 提交**

```bash
git add gateway/sandbox_router.py && git commit -m "fix(gateway): use BatchSandbox label selector for pod discovery; add last_seen annotation; rename to is_pool_full"
```

---

## Task 2: 修改 pool.yaml（shared volume + postStart hook）

**Files:**
- Modify: `kubernetes/sandbox/pool.yaml`

- [ ] **Step 1: 读取当前 pool.yaml**

```bash
cat /mnt/disk01/workspaces/worksummary/hermes-agent/kubernetes/sandbox/pool.yaml
```

- [ ] **Step 2: 写入修复后的 pool.yaml**

替换整个文件内容：

```yaml
apiVersion: sandbox.opensandbox.io/v1alpha1
kind: Pool
metadata:
  name: hermes-sandbox-pool
  namespace: hermes-agent
spec:
  template:
    metadata:
      labels:
        app: sandbox
    spec:
      serviceAccountName: sandbox
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        fsGroup: 1000
      initContainers:
        # init container: 轮询 /shared/registry_done 文件等待主容器就绪
        - name: registry-init
          image: nousresearch/hermes-agent:v0.8.0
          imagePullPolicy: IfNotPresent
          command: ["python3", "/opt/hermes/scripts/registry-init.py"]
          env:
            - name: POD_NAME
              valueFrom:
                fieldRef:
                  fieldPath: metadata.name
            - name: POD_IP
              valueFrom:
                fieldRef:
                  fieldPath: status.podIP
            - name: SANDBOX_PORT
              value: "8642"
          volumeMounts:
            - name: sandbox-data
              mountPath: /opt/data
            - name: shared
              mountPath: /shared
          resources:
            requests:
              cpu: 50m
              memory: 64Mi
            limits:
              cpu: 100m
              memory: 128Mi
      containers:
        # 主容器：Hermes Agent（Gateway 模式）
        - name: sandbox
          image: nousresearch/hermes-agent:v0.8.0
          imagePullPolicy: IfNotPresent
          command: ["hermes", "gateway"]
          ports:
            - containerPort: 8642
          securityContext:
            readOnlyRootFilesystem: false
            allowPrivilegeEscalation: false
            capabilities:
              drop: ["ALL"]
          env:
            - name: API_SERVER_ENABLED
              value: "true"
            - name: API_SERVER_HOST
              value: "0.0.0.0"
            - name: API_SERVER_PORT
              value: "8642"
            - name: POD_IP
              valueFrom:
                fieldRef:
                  fieldPath: status.podIP
            - name: HERMES_HOME
              value: "/opt/data"
          lifecycle:
            postStart:
              exec:
                command:
                  - /bin/sh
                  - -c
                  - |
                    # 等待 Hermes Gateway 就绪后写入标记文件
                    for i in $(seq 1 30); do
                      if curl -sf http://localhost:8642/health > /dev/null 2>&1; then
                        echo "ready" > /shared/registry_done
                        exit 0
                      fi
                      sleep 2
                    done
                    echo "timeout" > /shared/registry_done
            preStop:
              exec:
                command:
                  - /bin/sh
                  - -c
                  - |
                    curl -sf -X POST http://localhost:8080/deregister || true
                    sleep 2
          resources:
            requests:
              cpu: 500m
              memory: 512Mi
            limits:
              cpu: 1000m
              memory: 1Gi
          volumeMounts:
            - name: sandbox-data
              mountPath: /opt/data
            - name: shared
              mountPath: /shared
        # Sidecar：Registry Agent（处理注销请求）
        - name: registry-agent
          image: nousresearch/hermes-agent:v0.8.0
          imagePullPolicy: IfNotPresent
          command: ["python3", "/opt/hermes/scripts/registry-agent.py"]
          ports:
            - containerPort: 8080
          securityContext:
            readOnlyRootFilesystem: true
            allowPrivilegeEscalation: false
            capabilities:
              drop: ["ALL"]
          env:
            - name: POD_NAME
              valueFrom:
                fieldRef:
                  fieldPath: metadata.name
            - name: SANDBOX_PORT
              value: "8642"
          resources:
            requests:
              cpu: 50m
              memory: 64Mi
            limits:
              cpu: 100m
              memory: 128Mi
      volumes:
        - name: sandbox-data
          emptyDir: {}
        - name: shared
          emptyDir: {}
  capacitySpec:
    bufferMin: 5
    bufferMax: 15
    poolMin: 5
    poolMax: 30
```

- [ ] **Step 3: 验证 YAML 语法**

```bash
kubectl apply --dry-run=client -f /mnt/disk01/workspaces/worksummary/hermes-agent/kubernetes/sandbox/pool.yaml 2>&1 || true
```

- [ ] **Step 4: 提交**

```bash
git add kubernetes/sandbox/pool.yaml && git commit -m "fix(k8s): add shared volume and postStart hook for init container coordination"
```

---

## Task 3: 修改 registry-init.py（轮询标记文件）

**Files:**
- Modify: `scripts/registry-init.py`

- [ ] **Step 1: 写入修复后的 registry-init.py**

```python
#!/usr/bin/env python3
"""
registry-init.py: 沙箱 Pod init container 脚本。

轮询 /shared/registry_done 标记文件等待主容器 Hermes Gateway 就绪，
然后将 Pod IP:port 注册到 Kubernetes Endpoints（名称 = user_id）。

Usage: python3 registry-init.py
（环境变量：POD_NAME, POD_IP, SANDBOX_PORT）
"""
import os
import sys
import time

from kubernetes import client, config
from kubernetes.client.rest import ApiException

SANDBOX_PORT = os.getenv("SANDBOX_PORT", "8642")
POD_NAME = os.getenv("POD_NAME")
POD_IP = os.getenv("POD_IP")
NAMESPACE = "hermes-agent"


def wait_for_registration_marker(timeout: int = 120) -> bool:
    """等待主容器 postStart 写入的标记文件"""
    marker_path = "/shared/registry_done"
    start = time.time()
    while time.time() - start < timeout:
        try:
            with open(marker_path, "r") as f:
                content = f.read().strip()
                if content == "ready":
                    print("[registry-init] Sandbox ready, proceeding with registration")
                    return True
                elif content == "timeout":
                    print("[registry-init] Sandbox startup timeout, proceeding anyway")
                    return True
        except FileNotFoundError:
            pass
        time.sleep(2)
    print(f"[registry-init] Timeout waiting for marker file {marker_path}")
    return True  # 超时也继续，不阻止 Pod 启动


def register_endpoints() -> bool:
    """将 Pod IP:port 注册到同名 Endpoints"""
    core_v1 = client.CoreV1Api()
    endpoints_name = POD_NAME

    endpoints_body = client.V1Endpoints(
        metadata=client.V1ObjectMeta(name=endpoints_name, namespace=NAMESPACE),
        subsets=[
            client.V1EndpointSubset(
                addresses=[client.V1EndpointAddress(ip=POD_IP)],
                ports=[client.V1EndpointPort(port=int(SANDBOX_PORT), protocol="TCP")]
            )
        ]
    )

    try:
        existing = core_v1.read_endpoints(name=endpoints_name, namespace=NAMESPACE)
        core_v1.patch_endpoints(name=endpoints_name, namespace=NAMESPACE, body=endpoints_body)
        print(f"[registry-init] Updated Endpoints/{endpoints_name} -> {POD_IP}:{SANDBOX_PORT}")
    except ApiException as e:
        if e.status == 404:
            core_v1.create_namespaced_endpoints(namespace=NAMESPACE, body=endpoints_body)
            print(f"[registry-init] Created Endpoints/{endpoints_name} -> {POD_IP}:{SANDBOX_PORT}")
        else:
            print(f"[registry-init] Failed to create Endpoints: {e}")
            return False
    return True


def main():
    if not POD_NAME or not POD_IP:
        print("[registry-init] ERROR: POD_NAME or POD_IP not set")
        sys.exit(1)

    try:
        config.load_incluster_config()
    except config.ConfigException:
        print("[registry-init] WARNING: Could not load in-cluster config, using kubeconfig")
        try:
            config.load_kube_config()
        except config.ConfigException:
            print("[registry-init] ERROR: No kubernetes config available")
            sys.exit(1)

    if not wait_for_registration_marker():
        print("[registry-init] Marker wait failed, skipping registration")
        sys.exit(0)

    if register_endpoints():
        print("[registry-init] Registration complete")
    else:
        print("[registry-init] Registration failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 验证语法**

```bash
python3 -m py_compile /mnt/disk01/workspaces/worksummary/hermes-agent/scripts/registry-init.py
```
Expected: (no output = success)

- [ ] **Step 3: 提交**

```bash
git add scripts/registry-init.py && git commit -m "fix(scripts): poll marker file instead of waiting for port in registry-init"
```

---

## Task 4: 修改 ttl-manager.py（基于 BatchSandbox + annotation 判断闲置）

**Files:**
- Modify: `scripts/ttl-manager.py`

- [ ] **Step 1: 写入修复后的 ttl-manager.py**

```python
#!/usr/bin/env python3
"""
ttl-manager.py: 常驻沙箱 TTL 回收。

每 5 分钟扫描所有 BatchSandbox，
根据 Endpoints annotation 的 last_seen 判断闲置超时的沙箱并删除。
"""
import os
import time
from typing import Optional

from kubernetes import client, config
from kubernetes.client.rest import ApiException

SANDBOX_TTL_MINUTES = int(os.getenv("SANDBOX_TTL_MINUTES", "30"))
K8S_NAMESPACE = os.getenv("K8S_NAMESPACE", "hermes-agent")
SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL_SECONDS", "300"))


def delete_batchsandbox(user_id: str) -> bool:
    """删除用户的 BatchSandbox"""
    custom_api = client.CustomObjectsApi()
    batch_name = f"sandbox-{user_id}"
    try:
        custom_api.delete_namespaced_custom_object(
            group="sandbox.opensandbox.io",
            version="v1alpha1",
            namespace=K8S_NAMESPACE,
            plural="batchsandboxes",
            name=batch_name
        )
        return True
    except ApiException as e:
        if e.status == 404:
            return True
        return False


def deregister_endpoints(endpoints_name: str) -> bool:
    """从 Endpoints 注销沙箱"""
    core_v1 = client.CoreV1Api()
    try:
        body = client.V1Endpoints(
            metadata=client.V1ObjectMeta(name=endpoints_name, namespace=K8S_NAMESPACE),
            subsets=[]
        )
        core_v1.patch_endpoints(name=endpoints_name, namespace=K8S_NAMESPACE, body=body)
        return True
    except ApiException as e:
        if e.status == 404:
            return True
        return False


def scan_and_reclaim():
    """扫描并回收超时的沙箱"""
    sandbox_v1 = client.CustomObjectsApi()
    core_v1 = client.CoreV1Api()
    cutoff = int(time.time()) - (SANDBOX_TTL_MINUTES * 60)

    try:
        batch_sandboxes = sandbox_v1.list_namespaced_custom_object(
            group="sandbox.opensandbox.io",
            version="v1alpha1",
            namespace=K8S_NAMESPACE,
            plural="batchsandboxes"
        )
    except ApiException as e:
        print(f"[ttl-manager] Failed to list batchsandboxes: {e}")
        return

    for bs in batch_sandboxes.get("items", []):
        batch_name = bs["metadata"]["name"]
        user_id = bs["metadata"]["labels"].get("user_id")

        if not user_id:
            continue

        # Endpoints 名称就是 batch_name（OpenSandbox Pod 名 = BatchSandbox 名）
        try:
            ep = core_v1.read_endpoints(name=batch_name, namespace=K8S_NAMESPACE)
            last_seen_str = ep.metadata.annotations.get("last_seen", "0")
            last_seen = int(last_seen_str)

            if last_seen > 0 and last_seen < cutoff:
                print(f"[ttl-manager] Reclaiming sandbox for {user_id} (last_seen={last_seen}, cutoff={cutoff})")
                delete_batchsandbox(user_id)
                deregister_endpoints(batch_name)
        except ApiException as e:
            if e.status == 404:
                # Endpoints 不存在，跳过
                pass
            else:
                print(f"[ttl-manager] Failed to check endpoint {batch_name}: {e}")


def main():
    try:
        config.load_incluster_config()
    except config.ConfigException:
        try:
            config.load_kube_config()
        except config.ConfigException:
            print("[ttl-manager] ERROR: No kubernetes config")
            return

    print(f"[ttl-manager] Starting TTL manager (interval={SCAN_INTERVAL}s, TTL={SANDBOX_TTL_MINUTES}min)")
    while True:
        scan_and_reclaim()
        time.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 验证语法**

```bash
python3 -m py_compile /mnt/disk01/workspaces/worksummary/hermes-agent/scripts/ttl-manager.py
```
Expected: (no output = success)

- [ ] **Step 3: 提交**

```bash
git add scripts/ttl-manager.py && git commit -m "fix(scripts): use BatchSandbox to get user_id mapping; scan by last_seen annotation"
```

---

## Task 5: 修改 PostgreSQL Secret（placeholder）

**Files:**
- Modify: `kubernetes/postgres/secret.yaml`

- [ ] **Step 1: 写入修复后的 secret.yaml**

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: hermes-db-secret
  namespace: hermes-agent
type: Opaque
stringData:
  username: hermes
  # 部署前必须替换。生成方法：openssl rand -base64 24 | tr -d '\n'
  password: CHANGE_ME
```

- [ ] **Step 2: 验证 YAML 语法**

```bash
kubectl apply --dry-run=client -f /mnt/disk01/workspaces/worksummary/hermes-agent/kubernetes/postgres/secret.yaml
```

- [ ] **Step 3: 提交**

```bash
git add kubernetes/postgres/secret.yaml && git commit -m "fix(k8s): replace hardcoded password with CHANGE_ME placeholder"
```

---

## Task 6: 修复 postgres StatefulSet 注释

**Files:**
- Modify: `kubernetes/postgres/statefulset.yaml`

- [ ] **Step 1: 读取当前 statefulset.yaml**

```bash
cat /mnt/disk01/workspaces/worksummary/hermes-agent/kubernetes/postgres/statefulset.yaml
```

- [ ] **Step 2: 添加生产存储说明注释**

在 volumeClaimTemplates 部分添加清晰的说明注释：

```yaml
  # PRODUCTION: 取消下面的注释并删除 emptyDir volume，使用 PVC 持久化存储
  # volumeClaimTemplates:
  #   - metadata:
  #       name: postgres-data
  #     spec:
  #       accessModes: ["ReadWriteOnce"]
  #       resources:
  #         requests:
  #           storage: 1Gi
  #       # 需要集群管理员创建 StorageClass 并在此处指定:
  #       # storageClassName: standard
```

- [ ] **Step 3: 提交**

```bash
git add kubernetes/postgres/statefulset.yaml && git commit -m "docs(k8s): clarify how to enable PVC for postgres production"
```

---

## Task 7: 编写 registry-init 单元测试

**Files:**
- Create: `tests/test_registry_init.py`

- [ ] **Step 1: 写入单元测试**

```python
import os
import pytest
from unittest.mock import MagicMock, patch, mock_open
from pathlib import Path


class TestWaitForRegistrationMarker:
    """测试 wait_for_registration_marker 函数"""

    def test_marker_ready(self):
        """标记文件内容为 ready 时返回 True"""
        with patch("builtins.open", mock_open(read_data="ready\n")):
            with patch("time.sleep"):
                from scripts.registry_init import wait_for_registration_marker
                # 重新导入以获取最新函数
                import importlib
                import scripts.registry_init
                importlib.reload(scripts.registry_init)
                result = scripts.registry_init.wait_for_registration_marker(timeout=1)
                assert result is True

    def test_marker_timeout(self):
        """标记文件不存在时超时返回 True"""
        with patch("builtins.open", side_effect=FileNotFoundError()):
            with patch("time.sleep"):
                import importlib
                import scripts.registry_init
                importlib.reload(scripts.registry_init)
                result = scripts.registry_init.wait_for_registration_marker(timeout=1)
                assert result is True  # 超时也返回 True，不阻止 Pod 启动


class TestRegisterEndpoints:
    """测试 register_endpoints 函数"""

    def test_register_new_endpoints(self):
        """Endpoints 不存在时创建"""
        from kubernetes.client.rest import ApiException

        mock_core = MagicMock()
        mock_core.read_endpoints.side_effect = ApiException(status=404)
        mock_core.create_namespaced_endpoints.return_value = MagicMock()

        with patch("scripts.registry_init.client.CoreV1Api", return_value=mock_core):
            with patch.dict(os.environ, {"POD_NAME": "sandbox-alice", "POD_IP": "10.0.0.1", "SANDBOX_PORT": "8642"}):
                import importlib
                import scripts.registry_init
                importlib.reload(scripts.registry_init)
                result = scripts.registry_init.register_endpoints()
                assert result is True
                mock_core.create_namespaced_endpoints.assert_called_once()

    def test_register_existing_endpoints(self):
        """Endpoints 已存在时更新"""
        mock_core = MagicMock()
        mock_core.read_endpoints.return_value = MagicMock()  # 不抛 404

        with patch("scripts.registry_init.client.CoreV1Api", return_value=mock_core):
            with patch.dict(os.environ, {"POD_NAME": "sandbox-alice", "POD_IP": "10.0.0.1", "SANDBOX_PORT": "8642"}):
                import importlib
                import scripts.registry_init
                importlib.reload(scripts.registry_init)
                result = scripts.registry_init.register_endpoints()
                assert result is True
                mock_core.patch_endpoints.assert_called_once()
```

- [ ] **Step 2: 验证语法**

```bash
python3 -m py_compile /mnt/disk01/workspaces/worksummary/hermes-agent/tests/test_registry_init.py
```

- [ ] **Step 3: 运行测试**

```bash
cd /mnt/disk01/workspaces/worksummary/hermes-agent && python3 -m pytest tests/test_registry_init.py -v --override-ini="addopts=" 2>&1
```

- [ ] **Step 4: 提交**

```bash
git add tests/test_registry_init.py && git commit -m "test: add unit tests for registry-init"
```

---

## Task 8: 编写 registry-agent 单元测试

**Files:**
- Create: `tests/test_registry_agent.py`

- [ ] **Step 1: 写入单元测试**

```python
import pytest
from unittest.mock import MagicMock, patch
from http.client import HTTPConnection


class TestDeregisterHandler:
    """测试 DeregisterHandler 的 /health 和 /deregister 端点"""

    def test_health_endpoint(self):
        """GET /health 返回 200"""
        from scripts.registry_agent import DeregisterHandler

        handler = DeregisterHandler(MagicMock(), ("localhost", 8080))

        # 模拟 GET /health
        handler.path = "/health"
        with patch.object(handler, "send_response") as mock_send:
            with patch.object(handler, "send_header"):
                with patch.object(handler, "end_headers"):
                    with patch.object(handler, "wfile") as mock_wfile:
                        mock_wfile.write = MagicMock()
                        handler.do_GET()
                        mock_send.assert_called_with(200)

    def test_deregister_endpoint(self):
        """POST /deregister 返回 200"""
        from scripts.registry_agent import DeregisterHandler

        handler = DeregisterHandler(MagicMock(), ("localhost", 8080))
        handler.path = "/deregister"

        with patch.object(handler, "send_response") as mock_send:
            with patch.object(handler, "send_header"):
                with patch.object(handler, "end_headers"):
                    with patch.object(handler, "wfile") as mock_wfile:
                        mock_wfile.write = MagicMock()
                        with patch.object(handler, "_deregister") as mock_dereg:
                            handler.do_POST()
                            mock_send.assert_called_with(200)
                            mock_dereg.assert_called_once()

    def test_unknown_endpoint_returns_404(self):
        """未知路径返回 404"""
        from scripts.registry_agent import DeregisterHandler

        handler = DeregisterHandler(MagicMock(), ("localhost", 8080))
        handler.path = "/unknown"

        with patch.object(handler, "send_response") as mock_send:
            with patch.object(handler, "end_headers"):
                handler.do_GET()
                mock_send.assert_called_with(404)
```

- [ ] **Step 2: 验证语法**

```bash
python3 -m py_compile /mnt/disk01/workspaces/worksummary/hermes-agent/tests/test_registry_agent.py
```

- [ ] **Step 3: 运行测试**

```bash
cd /mnt/disk01/workspaces/worksummary/hermes-agent && python3 -m pytest tests/test_registry_agent.py -v --override-ini="addopts=" 2>&1
```

- [ ] **Step 4: 提交**

```bash
git add tests/test_registry_agent.py && git commit -m "test: add unit tests for registry-agent"
```

---

## Task 9: 编写 ttl-manager 单元测试

**Files:**
- Create: `tests/test_ttl_manager.py`

- [ ] **Step 1: 写入单元测试**

```python
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime


class TestScanAndReclaim:
    """测试 scan_and_reclaim 函数"""

    def test_reclaims_sandbox_when_idle(self):
        """last_seen 超过 TTL 时删除沙箱"""
        import time
        cutoff = int(time.time()) - (30 * 60)  # 30分钟前

        mock_ep = MagicMock()
        mock_ep.metadata.annotations = {"last_seen": str(int(time.time()) - 3600)}  # 1小时前
        mock_ep.metadata.name = "sandbox-alice"

        mock_batch_sandbox = MagicMock()
        mock_batch_sandbox.metadata.name = "sandbox-alice"
        mock_batch_sandbox.metadata.labels = {"user_id": "alice"}

        mock_bs_list = {"items": [mock_batch_sandbox]}
        mock_ep_list = MagicMock()
        mock_ep_list.items = [mock_ep]

        mock_sandbox_v1 = MagicMock()
        mock_sandbox_v1.list_namespaced_custom_object.return_value = mock_bs_list

        mock_core_v1 = MagicMock()
        mock_core_v1.read_endpoints.return_value = mock_ep

        with patch("scripts.ttl_manager.client.CustomObjectsApi", return_value=mock_sandbox_v1):
            with patch("scripts.ttl_manager.client.CoreV1Api", return_value=mock_core_v1):
                with patch("scripts.ttl_manager.delete_batchsandbox") as mock_delete:
                    with patch("scripts.ttl_manager.deregister_endpoints") as mock_dereg:
                        import importlib
                        import scripts.ttl_manager
                        importlib.reload(scripts.ttl_manager)
                        scripts.ttl_manager.scan_and_reclaim()
                        mock_delete.assert_called_once_with("alice")
                        mock_dereg.assert_called_once_with("sandbox-alice")

    def test_skips_active_sandbox(self):
        """last_seen 在 TTL 内时跳过"""
        import time

        mock_ep = MagicMock()
        mock_ep.metadata.annotations = {"last_seen": str(int(time.time()) - 60)}  # 1分钟前
        mock_ep.metadata.name = "sandbox-alice"

        mock_batch_sandbox = MagicMock()
        mock_batch_sandbox.metadata.name = "sandbox-alice"
        mock_batch_sandbox.metadata.labels = {"user_id": "alice"}

        mock_bs_list = {"items": [mock_batch_sandbox]}

        mock_sandbox_v1 = MagicMock()
        mock_sandbox_v1.list_namespaced_custom_object.return_value = mock_bs_list

        mock_core_v1 = MagicMock()
        mock_core_v1.read_endpoints.return_value = mock_ep

        with patch("scripts.ttl_manager.client.CustomObjectsApi", return_value=mock_sandbox_v1):
            with patch("scripts.ttl_manager.client.CoreV1Api", return_value=mock_core_v1):
                with patch("scripts.ttl_manager.delete_batchsandbox") as mock_delete:
                    import importlib
                    import scripts.ttl_manager
                    importlib.reload(scripts.ttl_manager)
                    scripts.ttl_manager.scan_and_reclaim()
                    mock_delete.assert_not_called()
```

- [ ] **Step 2: 验证语法**

```bash
python3 -m py_compile /mnt/disk01/workspaces/worksummary/hermes-agent/tests/test_ttl_manager.py
```

- [ ] **Step 3: 运行测试**

```bash
cd /mnt/disk01/workspaces/worksummary/hermes-agent && python3 -m pytest tests/test_ttl_manager.py -v --override-ini="addopts=" 2>&1
```

- [ ] **Step 4: 提交**

```bash
git add tests/test_ttl_manager.py && git commit -m "test: add unit tests for ttl-manager"
```

---

## 自审检查清单

### Spec Coverage

| 设计章节 | 对应 Task | 是否覆盖 |
|---------|---------|---------|
| 2.1 Endpoints 命名不匹配 | Task 1 (sandbox_router.py) | ✅ |
| 2.2 Init container 等待逻辑错误 | Task 2 (pool.yaml) + Task 3 (registry-init.py) | ✅ |
| 2.3 PostgreSQL 存储 | Task 6 (statefulset.yaml) | ✅ |
| 3.1 Secret 密码 Placeholder | Task 5 (secret.yaml) | ✅ |
| 3.2 TTL Manager 架构调整 | Task 4 (ttl-manager.py) | ✅ |
| 3.3 幂等性修复 | Task 1 (sandbox_router.py) | ✅ |
| 3.4 命名澄清 (is_pool_full) | Task 1 (sandbox_router.py) | ✅ |
| 3.5 单元测试 | Task 7, 8, 9 | ✅ |

### Placeholder 扫描

- `TBD` / `TODO` / `FIXME` → **无**
- `CHANGE_ME` → Task 5 中作为 password 值，有注释说明
- `startCondition` → **无**

### 类型一致性

- `registry-init.py`: `wait_for_registration_marker()` 函数存在 ✅
- `sandbox_router.py`: `is_pool_full()` 方法存在 ✅
- `ttl-manager.py`: `scan_and_reclaim()` 函数使用 `batchsandboxes` + `annotations["last_seen"]` ✅

---

## 执行方式选择

**Plan complete and saved to `docs/superpowers/plans/2026-04-14-hermes-agent-k8s-multiuser-hotfix.md`**

**两个执行选项：**

**1. Subagent-Driven（推荐）** - 每个 task 派发独立 subagent，task 间有检查点，快迭代

**2. Inline Execution** - 在本 session 内顺序执行，带检查点批量执行

请选择执行方式？