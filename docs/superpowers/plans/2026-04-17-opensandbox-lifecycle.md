# OpenSandbox Lifecycle Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 通过修改 `sandbox_router.py` 和更新 K8s 清单，实现基于 OpenSandbox Pool + BatchSandbox 的用户沙箱统一生命周期管理（TTL 续期 + 自动回收）。

**Architecture:** Gateway 的 `sandbox_router.py` 为每个用户创建 BatchSandbox（从 Pool 分配预热节点），利用 `sandbox.opensandbox.io/endpoints` 注解获取 Pod IP，通过 `spec.expireTime` 实现"永久 + 每次请求续期"策略。OpenSandbox Controller 原生处理过期回收。

**Tech Stack:** Python 3, Kubernetes Python Client, OpenSandbox v1alpha1 CRD (Pool + BatchSandbox), K8s YAML manifests

**Branch:** `feature/opensandbox-lifecycle`（从 `local-v0.9.0` 创建）

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `gateway/sandbox_router.py` | 修复 Pod IP 查找、添加 expireTime、续期逻辑 |
| Modify | `kubernetes/gateway/rbac.yaml` | 添加 `patch` 权限 |
| Modify | `kubernetes/gateway/deployment.yaml` | 添加沙箱环境变量、合并 Dashboard、改为单副本 |
| Modify | `kubernetes/sandbox/pool.yaml` | 简化为单服务器配置 |
| Create | `kubernetes/storage/pv.yaml` | Local PV |
| Create | `kubernetes/storage/pvc.yaml` | PVC |
| Create | `kubernetes/webui/deployment.yaml` | Open WebUI Deployment |
| Create | `kubernetes/webui/service.yaml` | WebUI Service |
| Modify | `tests/test_sandbox_router.py` | 更新测试覆盖新逻辑 |

---

### Task 1: 创建分支

**Files:** 无

- [ ] **Step 1: 从 local-v0.9.0 创建 feature 分支**

```bash
git checkout local-v0.9.0
git checkout -b feature/opensandbox-lifecycle
```

- [ ] **Step 2: 验证分支**

Run: `git branch --show-current`
Expected: `feature/opensandbox-lifecycle`

---

### Task 2: 重写 sandbox_router.py — 构造函数 + get_sandbox_url + 全部测试（一次原子提交）

> **Code Review 修复（C1）：** 将构造函数修改、get_sandbox_url 重写和所有相关测试放在同一个 Task 中，
> 确保每次 commit 都有通过的测试，不提交 broken tests。

**Files:**
- Modify: `gateway/sandbox_router.py` (构造函数 + get_sandbox_url)
- Modify: `tests/test_sandbox_router.py` (setup_method + 3 个 get_sandbox_url 测试)

- [ ] **Step 1: 修改 sandbox_router.py — 添加 import + 常量**

在 `gateway/sandbox_router.py` 顶部（第 11 行后）添加：

```python
import json
from datetime import datetime, timezone, timedelta
```

在 `K8S_NAMESPACE` 常量后（第 18 行后）添加：

```python
ENDPOINTS_ANNOTATION = "sandbox.opensandbox.io/endpoints"
```

- [ ] **Step 2: 修改 sandbox_router.py — 替换构造函数**

将 `SandboxRouter` 类的 `__init__` 和两个 `@property`（`core_v1`、`sandbox_v1`）全部替换为：

```python
class SandboxRouter:
    def __init__(self):
        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()
        self._core_v1 = client.CoreV1Api()
        self._sandbox_v1 = client.CustomObjectsApi()
```

- [ ] **Step 3: 修改 sandbox_router.py — 替换 get_sandbox_url**

将 `get_sandbox_url` 方法替换为：

```python
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
```

- [ ] **Step 4: 更新全部测试**

将 `tests/test_sandbox_router.py` 整体替换为：

```python
import pytest
from unittest.mock import MagicMock, patch
from gateway.sandbox_router import SandboxRouter


class TestSandboxRouter:
    def setup_method(self):
        with patch('gateway.sandbox_router.config'):
            self.router = SandboxRouter()
        self.mock_sandbox_v1 = MagicMock()
        self.mock_core_v1 = MagicMock()
        self.router._sandbox_v1 = self.mock_sandbox_v1
        self.router._core_v1 = self.mock_core_v1

    def test_get_sandbox_url_found(self):
        """BatchSandbox endpoints 注解中有 Pod IP 时返回正确 URL"""
        mock_bs = {
            "metadata": {
                "annotations": {
                    "sandbox.opensandbox.io/endpoints": '["10.244.1.45"]'
                }
            }
        }
        self.mock_sandbox_v1.get_namespaced_custom_object.return_value = mock_bs

        url = self.router.get_sandbox_url("user_123")
        assert url == "http://10.244.1.45:8642"
        self.mock_sandbox_v1.get_namespaced_custom_object.assert_called_once_with(
            group="sandbox.opensandbox.io",
            version="v1alpha1",
            namespace="hermes-agent",
            plural="batchsandboxes",
            name="sandbox-user_123"
        )

    def test_get_sandbox_url_not_found(self):
        """BatchSandbox 不存在时返回 None"""
        from kubernetes.client.rest import ApiException

        self.mock_sandbox_v1.get_namespaced_custom_object.side_effect = ApiException(status=404)

        url = self.router.get_sandbox_url("user_123")
        assert url is None

    def test_get_sandbox_url_pod_not_ready(self):
        """endpoints 注解为空时返回 None（Pod 尚未就绪）"""
        mock_bs = {
            "metadata": {
                "annotations": {}
            }
        }
        self.mock_sandbox_v1.get_namespaced_custom_object.return_value = mock_bs

        url = self.router.get_sandbox_url("user_123")
        assert url is None

    def test_wait_for_sandbox_timeout(self):
        """沙箱未就绪时超时返回 None"""
        with patch.object(self.router, 'get_sandbox_url', return_value=None):
            with patch('time.sleep'):
                result = self.router.wait_for_sandbox("user_123", timeout=3)
                assert result is None

    def test_create_sandbox_idempotent(self):
        """create_sandbox 对已存在的沙箱返回 True（幂等）"""
        from kubernetes.client.rest import ApiException

        self.mock_sandbox_v1.create_namespaced_custom_object.side_effect = ApiException(status=409)

        result = self.router.create_sandbox("alice")
        assert result is True

    def test_is_pool_full(self):
        """池满时 is_pool_full 返回 True"""
        mock_pool = {
            "status": {"allocated": 30},
            "spec": {"capacitySpec": {"poolMax": 30}}
        }

        self.mock_sandbox_v1.get_namespaced_custom_object.return_value = mock_pool

        result = self.router.is_pool_full()
        assert result is True

    def test_is_pool_not_full(self):
        """池未满时 is_pool_full 返回 False"""
        mock_pool = {
            "status": {"allocated": 10},
            "spec": {"capacitySpec": {"poolMax": 30}}
        }

        self.mock_sandbox_v1.get_namespaced_custom_object.return_value = mock_pool

        result = self.router.is_pool_full()
        assert result is False
```

- [ ] **Step 5: 运行测试验证**

Run: `cd /mnt/disk01/workspaces/worksummary/hermes-agent && python -m pytest tests/test_sandbox_router.py -v`
Expected: ALL PASS（7 个测试）

- [ ] **Step 6: Commit**

```bash
git add gateway/sandbox_router.py tests/test_sandbox_router.py
git commit -m "refactor: rewrite SandboxRouter constructor + endpoints annotation lookup"
```

---

### Task 4: 修改 sandbox_router.py — 添加 expireTime 和续期逻辑

**Files:**
- Modify: `gateway/sandbox_router.py:78-96,98-132`
- Modify: `tests/test_sandbox_router.py`

- [ ] **Step 1: 添加 _get_expire_time 辅助方法**

在 `get_sandbox_url` 方法后、`_update_endpoint_timestamp` 方法前添加：

```python
def _get_expire_time(self, minutes: int) -> str:
    """计算 expireTime（ISO 8601 UTC）"""
    expire = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    return expire.strftime("%Y-%m-%dT%H:%M:%SZ")
```

- [ ] **Step 2: 替换 _update_endpoint_timestamp 方法**

删除原方法，替换为：

```python
def _update_endpoint_timestamp(self, user_id: str):
    """续期 BatchSandbox expireTime（每次请求续期 30 分钟）"""
    batch_name = f"sandbox-{user_id}"
    new_expire = self._get_expire_time(SANDBOX_TTL_MINUTES)
    try:
        body = {"spec": {"expireTime": new_expire}}
        self._sandbox_v1.patch_namespaced_custom_object(
            group="sandbox.opensandbox.io",
            version="v1alpha1",
            namespace=K8S_NAMESPACE,
            plural="batchsandboxes",
            name=batch_name,
            body=body
        )
    except ApiException as e:
        if e.status == 404:
            return
        print(f"[SandboxRouter] Failed to renew expireTime: {e}")
    except Exception:
        pass
```

- [ ] **Step 3: 修改 create_sandbox 方法**

在 `create_sandbox` 方法的 body dict 中，`"spec"` 内添加 `"expireTime"` 字段。将原：

```python
            "spec": {
                "poolRef": pool_name,
                "replicas": 1
            }
```

改为：

```python
            "spec": {
                "poolRef": pool_name,
                "replicas": 1,
                "expireTime": self._get_expire_time(SANDBOX_TTL_MINUTES)
            }
```

- [ ] **Step 4: 添加测试 — test_create_sandbox_with_expire_time**

在 `tests/test_sandbox_router.py` 的 `TestSandboxRouter` 类中添加：

```python
def test_create_sandbox_with_expire_time(self):
    """create_sandbox 在 body 中设置 expireTime"""
    self.mock_sandbox_v1.create_namespaced_custom_object.return_value = {}

    result = self.router.create_sandbox("alice")
    assert result is True

    call_args = self.mock_sandbox_v1.create_namespaced_custom_object.call_args
    body = call_args[1]["body"]
    assert "expireTime" in body["spec"]
    assert body["spec"]["poolRef"] == "hermes-sandbox-pool"
    assert body["spec"]["replicas"] == 1
```

- [ ] **Step 5: 添加测试 — test_renew_expire_time**

```python
def test_renew_expire_time(self):
    """_update_endpoint_timestamp 通过 patch 续期 expireTime"""
    self.mock_sandbox_v1.patch_namespaced_custom_object.return_value = {}

    self.router._update_endpoint_timestamp("alice")

    call_args = self.mock_sandbox_v1.patch_namespaced_custom_object.call_args
    assert call_args[1]["name"] == "sandbox-alice"
    body = call_args[1]["body"]
    assert "expireTime" in body["spec"]
    self.mock_sandbox_v1.patch_namespaced_custom_object.assert_called_once()
```

- [ ] **Step 6: 添加测试 — test_renew_expire_time_404_handled**

```python
def test_renew_expire_time_404_handled(self):
    """续期时 BatchSandbox 已被删除（404）不抛异常"""
    from kubernetes.client.rest import ApiException

    self.mock_sandbox_v1.patch_namespaced_custom_object.side_effect = ApiException(status=404)

    # 不应抛异常
    self.router._update_endpoint_timestamp("alice")
```

- [ ] **Step 7: 运行全部测试**

Run: `cd /mnt/disk01/workspaces/worksummary/hermes-agent && python -m pytest tests/test_sandbox_router.py -v`
Expected: ALL PASS

- [ ] **Step 8: Commit**

```bash
git add gateway/sandbox_router.py tests/test_sandbox_router.py
git commit -m "feat: add expireTime to BatchSandbox creation and per-request TTL renewal"
```

---

### Task 5: 修改 RBAC — 添加 patch 权限

**Files:**
- Modify: `kubernetes/gateway/rbac.yaml:17-18`

- [ ] **Step 1: 在 batchsandboxes 规则中添加 patch**

将 `kubernetes/gateway/rbac.yaml` 第 17-18 行：

```yaml
  - apiGroups: ["sandbox.opensandbox.io"]
    resources: ["batchsandboxes", "batchsandboxes/status"]
    verbs: ["get", "list", "watch", "create", "delete"]
```

改为：

```yaml
  - apiGroups: ["sandbox.opensandbox.io"]
    resources: ["batchsandboxes", "batchsandboxes/status"]
    verbs: ["get", "list", "watch", "create", "delete", "patch"]
```

- [ ] **Step 2: 验证 YAML 语法**

Run: `python -c "import yaml; list(yaml.safe_load_all(open('kubernetes/gateway/rbac.yaml')))"`
Expected: 无报错，输出三个文档的列表

- [ ] **Step 3: Commit**

```bash
git add kubernetes/gateway/rbac.yaml
git commit -m "fix: add patch verb to RBAC for BatchSandbox TTL renewal"
```

---

### Task 6: 更新 Gateway Deployment — 单副本 + Dashboard + 沙箱环境变量

**Files:**
- Modify: `kubernetes/gateway/deployment.yaml`

- [ ] **Step 1: 更新 deployment.yaml**

将 `kubernetes/gateway/deployment.yaml` 整体替换为：

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: hermes-gateway
  namespace: hermes-agent
spec:
  replicas: 1
  selector:
    matchLabels:
      app: hermes-gateway
  template:
    metadata:
      labels:
        app: hermes-gateway
    spec:
      serviceAccountName: hermes-gateway
      containers:
        - name: gateway
          image: nousresearch/hermes-agent:latest
          imagePullPolicy: IfNotPresent
          command: ["bash", "-c", "uv pip install --system --break-system-packages 'hermes-agent[web]' -i https://pypi.tuna.tsinghua.edu.cn/simple && hermes gateway & python3 -m hermes_cli.main dashboard --host 0.0.0.0 --port 9119 --insecure & wait"]
          ports:
            - containerPort: 8642
            - containerPort: 9119
          env:
            - name: API_SERVER_ENABLED
              value: "true"
            - name: API_SERVER_HOST
              value: "0.0.0.0"
            - name: API_SERVER_PORT
              value: "8642"
            - name: GATEWAY_ALLOW_ALL_USERS
              value: "true"
            - name: K8S_NAMESPACE
              value: "hermes-agent"
            - name: SANDBOX_POOL_NAME
              value: "hermes-sandbox-pool"
            - name: SANDBOX_TTL_MINUTES
              value: "30"
            - name: DB_HOST
              value: "postgres.hermes-agent.svc.cluster.local"
            - name: DB_NAME
              value: "hermes"
            - name: DB_USER
              valueFrom:
                secretKeyRef:
                  name: hermes-db-secret
                  key: username
            - name: DB_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: hermes-db-secret
                  key: password
          resources:
            requests:
              cpu: 250m
              memory: 512Mi
            limits:
              cpu: 1000m
              memory: 1Gi
          readinessProbe:
            httpGet:
              path: /health
              port: 8642
            initialDelaySeconds: 10
            periodSeconds: 10
            timeoutSeconds: 3
          livenessProbe:
            httpGet:
              path: /health
              port: 8642
            initialDelaySeconds: 30
            periodSeconds: 20
            timeoutSeconds: 5
          volumeMounts:
            - name: hermes-data
              mountPath: /opt/data
      volumes:
        - name: hermes-data
          persistentVolumeClaim:
            claimName: hermes-data-pvc
---
apiVersion: v1
kind: Service
metadata:
  name: hermes-gateway
  namespace: hermes-agent
spec:
  type: ClusterIP
  ports:
    - name: api
      port: 8642
      targetPort: 8642
    - name: dashboard
      port: 9119
      targetPort: 9119
  selector:
    app: hermes-gateway
```

关键变更：
- `replicas: 1`（单服务器）
- 合并 Gateway + Dashboard（单 command 行启动两个进程）
- 添加 `K8S_NAMESPACE`、`SANDBOX_POOL_NAME`、`SANDBOX_TTL_MINUTES` 环境变量
- 使用 `latest` tag（与 docker-compose.yml 一致）
- 增加 memory limits 到 1Gi（承载 Gateway + Dashboard）
- 添加 PVC volume mount
- Service 暴露 9119 端口
- 移除 anti-affinity 和 topology spread（单节点不需要）

- [ ] **Step 2: 验证 YAML 语法**

Run: `python -c "import yaml; list(yaml.safe_load_all(open('kubernetes/gateway/deployment.yaml')))"`
Expected: 无报错

- [ ] **Step 3: Commit**

```bash
git add kubernetes/gateway/deployment.yaml
git commit -m "feat: update gateway deployment for single-server + merged dashboard"
```

---

### Task 7: 更新 Pool 配置 — 单服务器简化

**Files:**
- Modify: `kubernetes/sandbox/pool.yaml`

- [ ] **Step 1: 简化 Pool 配置**

将 `kubernetes/sandbox/pool.yaml` 整体替换为单服务器版本（保留 init container 和 sidecar 用于 registry 注册，但简化资源配置）：

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
      initContainers:
        - name: registry-init
          image: nousresearch/hermes-agent:latest
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
      containers:
        - name: sandbox
          image: nousresearch/hermes-agent:latest
          imagePullPolicy: IfNotPresent
          command: ["hermes", "gateway"]
          ports:
            - containerPort: 8642
          env:
            - name: API_SERVER_ENABLED
              value: "true"
            - name: API_SERVER_HOST
              value: "0.0.0.0"
            - name: API_SERVER_PORT
              value: "8642"
            - name: GATEWAY_ALLOW_ALL_USERS
              value: "true"
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
              cpu: 250m
              memory: 512Mi
            limits:
              cpu: 1000m
              memory: 1Gi
          volumeMounts:
            - name: sandbox-data
              mountPath: /opt/data
            - name: shared
              mountPath: /shared
        - name: registry-agent
          image: nousresearch/hermes-agent:latest
          imagePullPolicy: IfNotPresent
          command: ["python3", "/opt/hermes/scripts/registry-agent.py"]
          ports:
            - containerPort: 8080
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
    poolMin: 2
    poolMax: 50
    bufferMin: 2
    bufferMax: 10
```

关键变更：
- `image: latest`（与 docker-compose.yml 一致）
- 移除 `securityContext`（官方镜像以 hermes 用户运行，兼容更好）
- 保留 `POD_IP` 环境变量（registry-init 和 gateway 依赖）
- 保留 `preStop` lifecycle hook（处理 Pod 主动终止时的优雅注销，与 expireTime 回收互补）
- 保留 `GATEWAY_ALLOW_ALL_USERS`（新增，原 pool.yaml 缺失）
- `capacitySpec` 降低为 `poolMin:2, poolMax:50, bufferMin:2, bufferMax:10`（单服务器）

- [ ] **Step 2: 验证 YAML 语法**

Run: `python -c "import yaml; yaml.safe_load(open('kubernetes/sandbox/pool.yaml'))"`
Expected: 无报错

- [ ] **Step 3: Commit**

```bash
git add kubernetes/sandbox/pool.yaml
git commit -m "feat: simplify pool.yaml for single-server deployment"
```

---

### Task 8: 创建存储清单 — Local PV + PVC

**Files:**
- Create: `kubernetes/storage/pv.yaml`
- Create: `kubernetes/storage/pvc.yaml`

- [ ] **Step 1: 创建 storage 目录**

```bash
mkdir -p kubernetes/storage
```

- [ ] **Step 2: 创建 PV**

Write file `kubernetes/storage/pv.yaml`:

```yaml
apiVersion: v1
kind: PersistentVolume
metadata:
  name: hermes-data-pv
spec:
  capacity:
    storage: 50Gi
  accessModes:
    - ReadWriteOnce
  persistentVolumeReclaimPolicy: Retain
  storageClassName: local-storage
  local:
    path: /data/hermes
  nodeAffinity:
    required:
      nodeSelectorTerms:
        - matchExpressions:
            - key: kubernetes.io/hostname
              operator: In
              values:
                - hermes-node
```

- [ ] **Step 3: 创建 PVC**

Write file `kubernetes/storage/pvc.yaml`:

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: hermes-data-pvc
  namespace: hermes-agent
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 50Gi
  storageClassName: local-storage
```

- [ ] **Step 4: 验证 YAML**

Run: `python -c "import yaml; yaml.safe_load(open('kubernetes/storage/pv.yaml')); yaml.safe_load(open('kubernetes/storage/pvc.yaml'))"`
Expected: 无报错

- [ ] **Step 5: Commit**

```bash
git add kubernetes/storage/
git commit -m "feat: add local PV + PVC for single-server storage"
```

---

### Task 9: 创建 Open WebUI 清单

**Files:**
- Create: `kubernetes/webui/deployment.yaml`
- Create: `kubernetes/webui/service.yaml`

- [ ] **Step 1: 创建 webui 目录**

```bash
mkdir -p kubernetes/webui
```

- [ ] **Step 2: 创建 WebUI Deployment**

Write file `kubernetes/webui/deployment.yaml`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: hermes-webui
  namespace: hermes-agent
spec:
  replicas: 1
  selector:
    matchLabels:
      app: hermes-webui
  template:
    metadata:
      labels:
        app: hermes-webui
    spec:
      containers:
        - name: webui
          image: ghcr.io/open-webui/open-webui:main
          ports:
            - containerPort: 8080
          env:
            - name: OPENAI_API_BASE_URL
              value: "http://hermes-gateway:8642/v1"
            - name: OPENAI_API_KEY
              valueFrom:
                secretKeyRef:
                  name: hermes-db-secret
                  key: api_key
                  optional: true
            - name: WEBUI_AUTH
              value: "false"
          resources:
            requests:
              cpu: 100m
              memory: 256Mi
            limits:
              cpu: 500m
              memory: 512Mi
```

- [ ] **Step 3: 创建 WebUI Service**

Write file `kubernetes/webui/service.yaml`:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: hermes-webui
  namespace: hermes-agent
spec:
  type: ClusterIP
  ports:
    - port: 8080
      targetPort: 8080
  selector:
    app: hermes-webui
```

- [ ] **Step 4: 验证 YAML**

Run: `python -c "import yaml; yaml.safe_load(open('kubernetes/webui/deployment.yaml')); yaml.safe_load(open('kubernetes/webui/service.yaml'))"`
Expected: 无报错

- [ ] **Step 5: Commit**

```bash
git add kubernetes/webui/
git commit -m "feat: add Open WebUI K8s manifests"
```

---

### Task 10: 更新 Ingress — 三路由

**Files:**
- Modify: `kubernetes/gateway/ingress.yaml`

- [ ] **Step 1: 更新 Ingress 配置**

将 `kubernetes/gateway/ingress.yaml` 整体替换为三路由版本：

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: hermes-ingress
  namespace: hermes-agent
spec:
  rules:
    - host: hermes.local
      http:
        paths:
          - path: /api
            pathType: Prefix
            backend:
              service:
                name: hermes-gateway
                port:
                  number: 8642
          - path: /dashboard
            pathType: Prefix
            backend:
              service:
                name: hermes-gateway
                port:
                  number: 9119
          - path: /webui
            pathType: Prefix
            backend:
              service:
                name: hermes-webui
                port:
                  number: 8080
```

> **注意：** 不使用 `rewrite-target`，Gateway 和 WebUI 直接处理带前缀的路径。

- [ ] **Step 2: 验证 YAML**

Run: `python -c "import yaml; yaml.safe_load(open('kubernetes/gateway/ingress.yaml'))"`
Expected: 无报错

- [ ] **Step 3: Commit**

```bash
git add kubernetes/gateway/ingress.yaml
git commit -m "feat: update ingress with three-route configuration"
```

---

### Task 11: 更新 namespace.yaml — 添加 Gateway Dashboard 端口

**Files:**
- Modify: `kubernetes/namespace.yaml`

- [ ] **Step 1: 在 gateway-isolation NetworkPolicy 中添加 9119 端口**

在 `kubernetes/namespace.yaml` 的 `gateway-isolation` NetworkPolicy 中，将：

```yaml
  ingress:
    - from: []  # 允许任意来源（API Gateway 在集群外）
```

改为：

```yaml
  ingress:
    - from: []  # 允许任意来源（API Gateway 在集群外）
      ports:
        - protocol: TCP
          port: 8642
        - protocol: TCP
          port: 9119
```

- [ ] **Step 2: 验证 YAML**

Run: `python -c "import yaml; list(yaml.safe_load_all(open('kubernetes/namespace.yaml')))"`
Expected: 无报错

- [ ] **Step 3: Commit**

```bash
git add kubernetes/namespace.yaml
git commit -m "feat: add dashboard port to gateway NetworkPolicy"
```

---

### Task 12: 最终验证

**Files:** 无新文件

- [ ] **Step 1: 运行全部 sandbox_router 测试**

Run: `cd /mnt/disk01/workspaces/worksummary/hermes-agent && python -m pytest tests/test_sandbox_router.py -v`
Expected: ALL PASS（至少 9 个测试）

- [ ] **Step 2: 验证所有 YAML 语法**

Run: `find kubernetes/ -name '*.yaml' -exec python -c "import yaml,sys; list(yaml.safe_load_all(open(sys.argv[1])))" {} \; -print`
Expected: 所有文件无报错

- [ ] **Step 3: 检查 git log 确认所有提交**

Run: `git log --oneline local-v0.9.0..HEAD`
Expected: 9 个提交（Task 2-11）

- [ ] **Step 4: 最终 commit（如有未提交的变更）**

```bash
git status
# 如果有未提交的文件，提交它们
```

> **关于 ttl-manager.py：** `expireTime` 原生替代了 ttl-manager 的 TTL 扫描功能。
> ttl-manager.py 保留在代码库中不删除，但在 K8s 部署中不再部署为 CronJob。
> 如果同时运行，两者不会冲突——expireTime 由 OpenSandbox Controller 处理，
> ttl-manager 扫描的是 last_seen annotation，而新代码已改为 patch expireTime。
> 为避免混淆，建议在部署时不启动 ttl-manager。

---

## Self-Review

### Spec Coverage

| Spec Section | Task | Status |
|-------------|------|--------|
| 1.2 核心约束（不改核心代码） | All | 只改 sandbox_router.py 和 K8s YAML |
| 2.1 Pool CRD | Task 7 | pool.yaml 已更新 |
| 2.2 Gateway Deployment | Task 6 | deployment.yaml 已更新 |
| 2.3 BatchSandbox (sandbox_router) | Task 2, 3 | expireTime + endpoints annotation |
| 4.1-4.2 Local PV/PVC | Task 8 | pv.yaml + pvc.yaml |
| 5.1 Ingress 三路由 | Task 10 | ingress.yaml 已更新 |
| 5.2 NetworkPolicy | Task 11 | namespace.yaml 已更新 |
| 10.1 修改 0（构造函数） | Task 2 | __init__ 合并初始化 |
| 10.1 修改 1（endpoints 注解） | Task 2 | get_sandbox_url 重写 |
| 10.1 修改 2（expireTime） | Task 3 | create_sandbox + _get_expire_time |
| 10.1 修改 3（续期） | Task 3 | _update_endpoint_timestamp |
| 10.2 RBAC patch | Task 5 | rbac.yaml 已更新 |
| 10.3 ttl-manager | Task 12 | 不部署，保留代码 |

### Placeholder Scan

无 TBD、TODO、implement later。所有步骤包含完整代码。

### Type Consistency

- `_sandbox_v1` 和 `_core_v1` 在 Task 2 统一为实例变量，后续所有 Task 使用一致
- `ENDPOINTS_ANNOTATION` 常量在 Task 3 定义，Task 4 的 `_update_endpoint_timestamp` 不需要使用它
- `_get_expire_time` 在 Task 4 定义，被 `create_sandbox` 和 `_update_endpoint_timestamp` 统一调用
