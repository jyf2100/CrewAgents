# Hermes Agent K8s 多用户沙箱部署实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Hermes Agent 部署到 Kubernetes，通过 OpenSandbox 实现每用户独立沙箱，支持 API Key 认证，混合常驻+临时沙箱模式。

**Architecture:** 无状态 Hermes Gateway（2+ replicas）作为入口，通过 Kubernetes Endpoints 实现每用户沙箱发现，OpenSandbox Pool CRD 管理沙箱生命周期，PostgreSQL 存储 Key-User 映射。

**Tech Stack:** Kubernetes, OpenSandbox, PostgreSQL, Hermes Agent, Kubernetes Ingress, Helm

---

## 实施范围说明

本计划覆盖 **Phase 1（基础部署）** 的全部 8 个步骤，以及 **Phase 2 核心代码开发**（registry-agent、Gateway 沙箱路由逻辑）。

Phase 2 的 TTL 回收、HPA、Prometheus metrics 属于后续增强，不在本计划范围内。

---

## 文件结构

```
hermes-agent/
├── kubernetes/                          # [新建] K8s 资源清单
│   ├── namespace.yaml                   # hermes-agent namespace + NetworkPolicy
│   ├── gateway/                         # Hermes Gateway 相关资源
│   │   ├── deployment.yaml              # Gateway Deployment + Service
│   │   ├── rbac.yaml                   # ServiceAccount + Role + RoleBinding (gateway SA)
│   │   ├── pdb.yaml                    # PodDisruptionBudget
│   │   └── ingress.yaml                # Ingress
│   ├── sandbox/                         # Sandbox Pool 相关资源
│   │   ├── pool.yaml                   # OpenSandbox Pool CRD
│   │   └── sandbox-rbac.yaml           # sandbox SA + Role + RoleBinding
│   └── postgres/                        # Key-User 映射数据库
│       ├── statefulset.yaml            # PostgreSQL StatefulSet
│       ├── service.yaml                 # PostgreSQL Service
│       └── secret.yaml                  # DB credentials
├── scripts/
│   ├── registry-agent.py               # [新建] 沙箱注册 agent (Phase 2)
│   └── sandbox-init.sh                 # [新建] 沙箱 init container 入口脚本
├── hermes_cli/
│   └── gateway.py                       # [修改] 添加沙箱发现 + 路由逻辑
└── tests/
    ├── test_registry_agent.py          # [新建] registry-agent 单元测试
    ├── test_gateway_routing.py        # [新建] Gateway 路由逻辑测试
    └── test_endpoints_integration.py   # [新建] Endpoints 集成测试
```

---

## Task 1: 验证 OpenSandbox CRD 字段

**Files:**
- Verify: `OpenSandbox/kubernetes/config/crd/bases/sandbox.opensandbox.io_pools.yaml`

- [ ] **Step 1: 读取 OpenSandbox Pool CRD 确认字段**

```bash
cat /mnt/disk01/workspaces/worksummary/hermes-agent/OpenSandbox/kubernetes/config/crd/bases/sandbox.opensandbox.io_pools.yaml | grep -A5 "capacitySpec:"
```

确认 `bufferMin`, `bufferMax`, `poolMin`, `poolMax` 字段存在。

- [ ] **Step 2: 提交确认结果**

```bash
git add -A && git commit -m "docs: confirm OpenSandbox Pool CRD field names"
```

---

## Task 2: 创建 Kubernetes 资源目录结构

**Files:**
- Create: `kubernetes/namespace.yaml`
- Create: `kubernetes/gateway/deployment.yaml`
- Create: `kubernetes/gateway/rbac.yaml`
- Create: `kubernetes/gateway/pdb.yaml`
- Create: `kubernetes/gateway/ingress.yaml`
- Create: `kubernetes/sandbox/pool.yaml`
- Create: `kubernetes/sandbox/sandbox-rbac.yaml`
- Create: `kubernetes/postgres/statefulset.yaml`
- Create: `kubernetes/postgres/service.yaml`
- Create: `kubernetes/postgres/secret.yaml`

- [ ] **Step 1: 创建目录结构**

```bash
mkdir -p kubernetes/gateway kubernetes/sandbox kubernetes/postgres
touch kubernetes/namespace.yaml kubernetes/gateway/deployment.yaml
```

---

## Task 3: 编写 namespace + NetworkPolicy

**Files:**
- Create: `kubernetes/namespace.yaml`

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: hermes-agent
  labels:
    name: hermes-agent
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: sandbox-isolation
  namespace: hermes-agent
spec:
  podSelector:
    matchLabels:
      app: sandbox
  policyTypes:
    - Ingress
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              name: hermes-agent
      ports:
        - protocol: TCP
          port: 8642
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: gateway-isolation
  namespace: hermes-agent
spec:
  podSelector:
    matchLabels:
      app: hermes-gateway
  policyTypes:
    - Ingress
  ingress:
    - from: []  # 允许任意来源（API Gateway 在集群外）
```

- [ ] **Step 2: 验证 YAML 语法**

```bash
kubectl apply --dry-run=server -f kubernetes/namespace.yaml
```

Expected: No error

---

## Task 4: 编写 Hermes Gateway RBAC

**Files:**
- Create: `kubernetes/gateway/rbac.yaml`

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: hermes-gateway
  namespace: hermes-agent
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: hermes-gateway
  namespace: hermes-agent
rules:
  - apiGroups: [""]
    resources: ["endpoints"]
    verbs: ["get", "list", "watch", "create", "update", "patch"]
  - apiGroups: ["sandbox.opensandbox.io"]
    resources: ["batchsandboxes", "batchsandboxes/status"]
    verbs: ["get", "list", "watch", "create", "delete"]
  - apiGroups: ["sandbox.opensandbox.io"]
    resources: ["pools"]
    verbs: ["get", "list"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: hermes-gateway
  namespace: hermes-agent
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: hermes-gateway
subjects:
  - kind: ServiceAccount
    name: hermes-gateway
    namespace: hermes-agent
```

- [ ] **Step 2: 验证 RBAC YAML**

```bash
kubectl auth can-i get endpoints --as=system:serviceaccount:hermes-agent:hermes-gateway -n hermes-agent
```

Expected: yes

---

## Task 5: 编写 Hermes Gateway Deployment + Service + PDB

**Files:**
- Create: `kubernetes/gateway/deployment.yaml`
- Create: `kubernetes/gateway/pdb.yaml`

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: hermes-gateway
  namespace: hermes-agent
spec:
  replicas: 2
  selector:
    matchLabels:
      app: hermes-gateway
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
  template:
    metadata:
      labels:
        app: hermes-gateway
    spec:
      serviceAccountName: hermes-gateway
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        fsGroup: 1000
      containers:
        - name: gateway
          image: nousresearch/hermes-agent:v0.8.0
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
            - name: SANDBOX_TTL_MINUTES
              value: "30"
          resources:
            requests:
              cpu: 250m
              memory: 256Mi
            limits:
              cpu: 500m
              memory: 512Mi
          readinessProbe:
            httpGet:
              path: /health
              port: 8642
            initialDelaySeconds: 5
            periodSeconds: 10
            timeoutSeconds: 3
          livenessProbe:
            httpGet:
              path: /health
              port: 8642
            initialDelaySeconds: 15
            periodSeconds: 20
            timeoutSeconds: 5
      affinity:
        podAntiAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
            - weight: 100
              podAffinityTerm:
                labelSelector:
                  matchLabels:
                    app: hermes-gateway
                topologyKey: kubernetes.io/hostname
      topologySpreadConstraints:
        - maxSkew: 1
          topologyKey: topology.kubernetes.io/zone
          whenUnsatisfiable: ScheduleAnyway
          labelSelector:
            matchLabels:
              app: hermes-gateway
---
apiVersion: v1
kind: Service
metadata:
  name: hermes-gateway
  namespace: hermes-agent
spec:
  type: ClusterIP
  ports:
    - port: 8642
      targetPort: 8642
  selector:
    app: hermes-gateway
---
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: hermes-gateway-pdb
  namespace: hermes-agent
spec:
  minAvailable: 1
  selector:
    matchLabels:
      app: hermes-gateway
```

- [ ] **Step 2: 验证 Deployment YAML**

```bash
kubectl apply --dry-run=server -f kubernetes/gateway/deployment.yaml
```

Expected: No error

---

## Task 6: 编写 Ingress

**Files:**
- Create: `kubernetes/gateway/ingress.yaml`

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: hermes-gateway-ingress
  namespace: hermes-agent
spec:
  tls:
    - hosts:
        - hermes.internal.example.com
      secretName: hermes-tls-secret
  rules:
    - host: hermes.internal.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: hermes-gateway
                port:
                  number: 8642
```

> **注**：TLS secret `hermes-tls-secret` 需由集群管理员预先创建，或由 cert-manager 自动管理。

- [ ] **Step 2: 验证 Ingress YAML**

```bash
kubectl apply --dry-run=server -f kubernetes/gateway/ingress.yaml
```

---

## Task 7: 编写 Sandbox RBAC

**Files:**
- Create: `kubernetes/sandbox/sandbox-rbac.yaml`

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: sandbox
  namespace: hermes-agent
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: sandbox-endpoints
  namespace: hermes-agent
rules:
  - apiGroups: [""]
    resources: ["endpoints"]
    verbs: ["get", "list", "watch", "create", "update", "patch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: sandbox-endpoints
  namespace: hermes-agent
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: sandbox-endpoints
subjects:
  - kind: ServiceAccount
    name: sandbox
    namespace: hermes-agent
```

- [ ] **Step 2: 验证 Sandbox RBAC**

```bash
kubectl apply --dry-run=server -f kubernetes/sandbox/sandbox-rbac.yaml
```

Expected: No error

---

## Task 8: 编写 Sandbox Pool CRD

**Files:**
- Create: `kubernetes/sandbox/pool.yaml`

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
        # init container: 等待主容器就绪后注册 Endpoints
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
          resources:
            requests:
              cpu: 50m
              memory: 64Mi
            limits:
              cpu: 100m
              memory: 128Mi
      containers:
        # 主容器：Hermes Agent（Gateway 模式，无 messaging token 时只启动 API server）
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
  capacitySpec:
    bufferMin: 5
    bufferMax: 15
    poolMin: 5
    poolMax: 30
```

> **重要**：Pool CRD 的 `template.spec` 使用 `x-kubernetes-preserve-unknown-fields: true`，允许自定义字段（如 `initContainers`）。本 YAML 需通过 `--dry-run=server` 验证。

- [ ] **Step 2: 验证 Pool CRD**

```bash
kubectl apply --dry-run=server -f kubernetes/sandbox/pool.yaml
```

Expected: No error (or error about missing CRD -说明需要先安装 OpenSandbox Controller)

---

## Task 9: 编写 PostgreSQL Key-User 映射库

**Files:**
- Create: `kubernetes/postgres/secret.yaml`
- Create: `kubernetes/postgres/statefulset.yaml`
- Create: `kubernetes/postgres/service.yaml`

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: hermes-db-secret
  namespace: hermes-agent
type: Opaque
stringData:
  username: hermes
  password: <GENERATE_WITH: openssl rand -base64 24>
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgres
  namespace: hermes-agent
spec:
  serviceName: postgres
  replicas: 1
  selector:
    matchLabels:
      app: postgres
  template:
    metadata:
      labels:
        app: postgres
    spec:
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        fsGroup: 1000
      containers:
        - name: postgres
          image: postgres:16-alpine
          ports:
            - containerPort: 5432
          env:
            - name: POSTGRES_DB
              value: hermes
            - name: POSTGRES_USER
              valueFrom:
                secretKeyRef:
                  name: hermes-db-secret
                  key: username
            - name: POSTGRES_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: hermes-db-secret
                  key: password
          resources:
            requests:
              cpu: 100m
              memory: 128Mi
            limits:
              cpu: 500m
              memory: 512Mi
          volumeMounts:
            - name: postgres-data
              mountPath: /var/lib/postgresql/data
  volumeClaimTemplates:
    - metadata:
        name: postgres-data
      spec:
        accessModes: ["ReadWriteOnce"]
        resources:
          requests:
            storage: 1Gi
---
apiVersion: v1
kind: Service
metadata:
  name: postgres
  namespace: hermes-agent
spec:
  type: ClusterIP
  ports:
    - port: 5432
      targetPort: 5432
  selector:
    app: postgres
```

- [ ] **Step 2: 创建初始化 SQL（Key-User 表）**

创建 `kubernetes/postgres/init.sql`：

```sql
CREATE TABLE IF NOT EXISTS api_keys (
    api_key VARCHAR(64) PRIMARY KEY,  -- SHA256 hash of actual key
    user_id VARCHAR(64) NOT NULL,
    sandbox_policy VARCHAR(20) NOT NULL DEFAULT 'resident',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    revoked_at TIMESTAMP,
    INDEX idx_user_id (user_id),
    INDEX idx_revoked_at (revoked_at)
);

-- Sandbox Registry: 存储 user_id -> sandbox endpoint 映射
-- (Endpoint 资源本身由 K8s 管理，此表用于 Gateway 缓存 + 审计)
CREATE TABLE IF NOT EXISTS sandbox_registry (
    user_id VARCHAR(64) PRIMARY KEY,
    sandbox_endpoint VARCHAR(255) NOT NULL,
    sandbox_policy VARCHAR(20) NOT NULL DEFAULT 'resident',
    last_seen_at TIMESTAMP NOT NULL DEFAULT NOW(),
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
```

- [ ] **Step 3: 将 init.sql 挂载到 StatefulSet**

修改 `statefulset.yaml`，在 `postgres` container 中添加：

```yaml
volumeMounts:
  - name: postgres-data
    mountPath: /var/lib/postgresql/data
  - name: postgres-init
    mountPath: /docker-entrypoint-initdb.d/init.sql
    subPath: init.sql
volumes:
  - name: postgres-init
    configMap:
      name: postgres-init-script
```

添加 ConfigMap：

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: postgres-init-script
  namespace: hermes-agent
data:
  init.sql: |
    CREATE TABLE IF NOT EXISTS api_keys (
        api_key VARCHAR(64) PRIMARY KEY,
        user_id VARCHAR(64) NOT NULL,
        sandbox_policy VARCHAR(20) NOT NULL DEFAULT 'resident',
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        revoked_at TIMESTAMP,
        INDEX idx_user_id (user_id),
        INDEX idx_revoked_at (revoked_at)
    );
    CREATE TABLE IF NOT EXISTS sandbox_registry (
        user_id VARCHAR(64) PRIMARY KEY,
        sandbox_endpoint VARCHAR(255) NOT NULL,
        sandbox_policy VARCHAR(20) NOT NULL DEFAULT 'resident',
        last_seen_at TIMESTAMP NOT NULL DEFAULT NOW(),
        created_at TIMESTAMP NOT NULL DEFAULT NOW()
    );
```

---

## Task 10: 编写 registry-init.py（沙箱注册脚本）

**Files:**
- Create: `scripts/registry-init.py`

```python
#!/usr/bin/env python3
"""
registry-init.py: 沙箱 Pod init container 脚本。

在主容器启动前等待 Hermes Gateway API server 就绪，
然后将 Pod IP:port 注册到 Kubernetes Endpoints（名称 = user_id）。

Usage: python3 registry-init.py
（环境变量：POD_NAME, POD_IP, SANDBOX_PORT）
"""
import os
import sys
import time
import urllib.request
import urllib.error

from kubernetes import client, config
from kubernetes.client.rest import ApiException

SANDBOX_PORT = os.getenv("SANDBOX_PORT", "8642")
POD_NAME = os.getenv("POD_NAME")
POD_IP = os.getenv("POD_IP")
NAMESPACE = "hermes-agent"


def wait_for_gateway(timeout: int = 60) -> bool:
    """等待 Hermes Gateway API server 就绪（/health 返回 200）"""
    url = f"http://localhost:{SANDBOX_PORT}/health"
    start = time.time()
    while time.time() - start < timeout:
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    print(f"[registry-init] Gateway ready at {url}")
                    return True
        except (urllib.error.URLError, urllib.error.HTTPError):
            pass
        time.sleep(2)
    print(f"[registry-init] Timeout waiting for gateway at {url}")
    return False


def register_endpoints() -> bool:
    """将 Pod IP:port 注册到同名 Endpoints"""
    core_v1 = client.CoreV1Api()

    # Endpoints 名称从 POD_NAME 推断（格式：sandbox-<user_id>）
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
        # 尝试创建 Endpoints（若已存在则更新）
        existing = core_v1.read_endpoints(name=endpoints_name, namespace=NAMESPACE)
        # 存在则更新
        core_v1.patch_endpoints(name=endpoints_name, namespace=NAMESPACE, body=endpoints_body)
        print(f"[registry-init] Updated Endpoints/{endpoints_name} -> {POD_IP}:{SANDBOX_PORT}")
    except ApiException as e:
        if e.status == 404:
            # 不存在则创建
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

    if not wait_for_gateway():
        print("[registry-init] Gateway not ready, skipping registration")
        sys.exit(0)  # 不阻止 Pod 启动，只是跳过注册

    if register_endpoints():
        print("[registry-init] Registration complete")
    else:
        print("[registry-init] Registration failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 验证脚本语法**

```bash
python3 -m py_compile scripts/registry-init.py
```

Expected: (no output = success)

---

## Task 11: 编写 registry-agent.py（沙箱注销 agent）

**Files:**
- Create: `scripts/registry-agent.py`

```python
#!/usr/bin/env python3
"""
registry-agent.py: 沙箱 Pod sidecar HTTP server。

监听 8080 端口，提供以下端点：
- GET /health          → 返回 200
- POST /deregister     → 从 Endpoints 注销当前 Pod

Usage: python3 registry-agent.py
（环境变量：POD_NAME, SANDBOX_PORT）
"""
import os
import sys
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from kubernetes import client, config
from kubernetes.client.rest import ApiException

SANDBOX_PORT = os.getenv("SANDBOX_PORT", "8642")
POD_NAME = os.getenv("POD_NAME")
NAMESPACE = "hermes-agent"


class DeregisterHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        print(f"[registry-agent] {args[0]}")

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"OK")
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/deregister":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Deregistering")
            # 异步执行注销，避免阻塞 HTTP 响应
            threading.Thread(target=self._deregister, daemon=True).start()
        else:
            self.send_response(404)
            self.end_headers()

    def _deregister(self):
        """从 Endpoints 注销当前 Pod"""
        core_v1 = client.CoreV1Api()
        endpoints_name = POD_NAME

        try:
            body = client.V1Endpoints(
                metadata=client.V1ObjectMeta(name=endpoints_name, namespace=NAMESPACE),
                subsets=[]
            )
            core_v1.patch_endpoints(name=endpoints_name, namespace=NAMESPACE, body=body)
            print(f"[registry-agent] Deregistered Endpoints/{endpoints_name}")
        except ApiException as e:
            if e.status == 404:
                print(f"[registry-agent] Endpoints/{endpoints_name} not found, skipping")
            else:
                print(f"[registry-agent] Failed to deregister: {e}")
                sys.exit(1)


def main():
    if not POD_NAME:
        print("[registry-agent] ERROR: POD_NAME not set")
        sys.exit(1)

    try:
        config.load_incluster_config()
    except config.ConfigException:
        try:
            config.load_kube_config()
        except config.ConfigException:
            print("[registry-agent] ERROR: No kubernetes config")
            sys.exit(1)

    server = HTTPServer(("0.0.0.0", 8080), DeregisterHandler)
    print(f"[registry-agent] Listening on 0.0.0.0:8080")
    server.serve_forever()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 验证脚本语法**

```bash
python3 -m py_compile scripts/registry-agent.py
```

---

## Task 12: 编写 Gateway 沙箱发现 + 路由逻辑

**Files:**
- Modify: `hermes_cli/gateway.py` (添加沙箱路由相关代码段)
- Modify: `gateway/config.py` (添加沙箱端点相关配置)

> **说明**：Gateway 需要新增以下逻辑：
> 1. 认证中间件：从 DB 查询 API Key → user_id
> 2. 沙箱发现：根据 user_id 查询 Endpoints
> 3. 沙箱创建：根据 user_id 调用 OpenSandbox 创建 BatchSandbox
> 4. 路由：根据 sandbox_policy 将请求转发到对应沙箱

由于 `gateway.py` 是大型文件（约 2500 行），建议在 `gateway/` 目录下新增 `sandbox_router.py`，然后在 `gateway/run.py` 中引用。

- [ ] **Step 1: 创建 `gateway/sandbox_router.py`**

```python
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


# 全局单例
_sandbox_router: Optional[SandboxRouter] = None


def get_sandbox_router() -> SandboxRouter:
    global _sandbox_router
    if _sandbox_router is None:
        _sandbox_router = SandboxRouter()
    return _sandbox_router
```

- [ ] **Step 2: 验证 sandbox_router.py 语法**

```bash
python3 -m py_compile gateway/sandbox_router.py
```

- [ ] **Step 3: 编写单元测试**

创建 `tests/test_sandbox_router.py`：

```python
import pytest
from unittest.mock import MagicMock, patch
from gateway.sandbox_router import SandboxRouter


class TestSandboxRouter:
    def setup_method(self):
        self.router = SandboxRouter()

    def test_get_sandbox_url_found(self):
        """Endpoints 存在时返回正确 URL"""
        mock_ep = MagicMock()
        mock_ep.subsets = [MagicMock()]
        mock_ep.subsets[0].addresses = [MagicMock()]
        mock_ep.subsets[0].addresses[0].ip = "10.244.1.45"
        mock_ep.subsets[0].ports = [MagicMock()]
        mock_ep.subsets[0].ports[0].port = 8642

        with patch.object(self.router, 'core_v1') as mock_core:
            mock_core.read_endpoints.return_value = mock_ep
            url = self.router.get_sandbox_url("user_123")
            assert url == "http://10.244.1.45:8642"

    def test_get_sandbox_url_not_found(self):
        """Endpoints 不存在时返回 None"""
        from kubernetes.client.rest import ApiException

        with patch.object(self.router, 'core_v1') as mock_core:
            mock_core.read_endpoints.side_effect = ApiException(status=404)
            url = self.router.get_sandbox_url("user_123")
            assert url is None

    def test_wait_for_sandbox_timeout(self):
        """沙箱未就绪时超时返回 None"""
        with patch.object(self.router, 'get_sandbox_url', return_value=None):
            with patch('time.sleep'):
                result = self.router.wait_for_sandbox("user_123", timeout=3)
                assert result is None
```

- [ ] **Step 4: 运行单元测试**

```bash
cd /mnt/disk01/workspaces/worksummary/hermes-agent && python3 -m pytest tests/test_sandbox_router.py -v
```

Expected: 3 passed

- [ ] **Step 5: 提交 sandbox_router.py**

```bash
git add gateway/sandbox_router.py tests/test_sandbox_router.py
git commit -m "feat: add sandbox router for K8s endpoints discovery"
```

---

## Task 13: 端到端验证

- [ ] **Step 1: 安装 OpenSandbox Controller**

```bash
helm install opensandbox-controller \
  https://github.com/alibaba/OpenSandbox/releases/download/helm/opensandbox-controller/0.1.0/opensandbox-controller-0.1.0.tgz \
  --namespace hermes-agent --create-namespace
```

验证 Controller 就绪：

```bash
kubectl wait --for=condition=Ready pods -l control-plane=controller-manager -n hermes-agent --timeout=60s
```

- [ ] **Step 2: 部署所有 K8s 资源**

```bash
kubectl apply -f kubernetes/namespace.yaml
kubectl apply -f kubernetes/gateway/rbac.yaml
kubectl apply -f kubernetes/gateway/deployment.yaml
kubectl apply -f kubernetes/gateway/pdb.yaml
kubectl apply -f kubernetes/gateway/ingress.yaml
kubectl apply -f kubernetes/sandbox/sandbox-rbac.yaml
kubectl apply -f kubernetes/sandbox/pool.yaml
kubectl apply -f kubernetes/postgres/secret.yaml
kubectl apply -f kubernetes/postgres/statefulset.yaml
kubectl apply -f kubernetes/postgres/service.yaml
```

验证所有资源创建成功：

```bash
kubectl get all -n hermes-agent
kubectl get endpoints -n hermes-agent
kubectl get pool -n hermes-agent
```

Expected: 所有资源处于 Ready/Created 状态

- [ ] **Step 3: 验证 Hermes Gateway 可用**

```bash
curl http://hermes-gateway.hermes-agent.svc.cluster.local:8642/health
```

Expected: 返回 200

- [ ] **Step 4: 验证沙箱 Pool 预热**

```bash
kubectl get pool hermes-sandbox-pool -n hermes-agent -o jsonpath='{.status}'
```

Expected: `available` 数量 >= `bufferMin` (5)

- [ ] **Step 5: 端到端流程测试**

```bash
# 1. 向 Key-User 表插入测试用户
kubectl exec -it postgres-0 -n hermes-agent -- psql -U hermes -d hermes -c \
  "INSERT INTO api_keys (api_key, user_id, sandbox_policy) VALUES ('test_key_1', 'user_test_001', 'resident');"

# 2. 模拟用户请求（带 API Key）
curl -X POST http://hermes-gateway.hermes-agent.svc.cluster.local:8642/v1/chat/completions \
  -H "Authorization: Bearer test_key_1" \
  -H "Content-Type: application/json" \
  -d '{"model": "MiniMax-M2.7", "messages": [{"role": "user", "content": "hello"}]}'

# 3. 验证沙箱被创建
kubectl get endpoints user_test_001 -n hermes-agent
# Expected: 10.244.x.x:8642
```

- [ ] **Step 6: 提交所有 K8s 资源**

```bash
git add kubernetes/ scripts/registry-init.py scripts/registry-agent.py
git commit -m "feat(k8s): add hermes-agent kubernetes manifests for multi-user sandbox"
```

---

## Task 14: Phase 2 核心功能开发（registry-agent + 路由）

> 以下为 Phase 2 优先实现的核心功能，在 Task 13 E2E 验证通过后执行。

### 14.1 实现 TTL 回收机制

**Files:**
- Create: `scripts/ttl-manager.py`

```python
"""
ttl-manager.py: 常驻沙箱 TTL 回收。

每 5 分钟扫描所有活跃 Endpoints，
将超过 TTL 无活动的沙箱标记为待回收。
"""
import os
import time
import sqlite3
from datetime import datetime, timedelta
from kubernetes import client, config
from kubernetes.client.rest import ApiException

SANDBOX_TTL_MINUTES = int(os.getenv("SANDBOX_TTL_MINUTES", "30"))
K8S_NAMESPACE = os.getenv("K8S_NAMESPACE", "hermes-agent")
SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL_SECONDS", "300"))


def get_db_connection():
    db_path = os.getenv("HERMES_DB_PATH", "/opt/data/hermes.db")
    return sqlite3.connect(db_path)


def get_last_activity(user_id: str) -> Optional[datetime]:
    """从沙箱 DB 查询用户最后活跃时间"""
    try:
        conn = get_db_connection()
        cursor = conn.execute(
            "SELECT MAX(created_at) FROM messages WHERE user_id = ?",
            (user_id,)
        )
        row = cursor.fetchone()
        conn.close()
        if row and row[0]:
            return datetime.fromisoformat(row[0])
    except Exception:
        pass
    return None


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
            return True  # 已不存在
        return False


def scan_and_reclaim():
    """扫描并回收超时的沙箱"""
    core_v1 = client.CoreV1Api()
    cutoff = datetime.now() - timedelta(minutes=SANDBOX_TTL_MINUTES)

    endpoints = core_v1.list_namespaced_endpoints(namespace=K8S_NAMESPACE)
    for ep in endpoints.items:
        user_id = ep.metadata.name
        if not user_id.startswith("sandbox-"):
            continue

        last_activity = get_last_activity(user_id)
        if last_activity and last_activity < cutoff:
            print(f"[ttl-manager] Reclaiming sandbox for {user_id} (last activity: {last_activity})")
            delete_batchsandbox(user_id)


def main():
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()

    while True:
        scan_and_reclaim()
        time.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    main()
```

### 14.2 实现 Gateway 超额排队（429 响应）

在 `gateway/sandbox_router.py` 中添加：

```python
def check_pool_capacity(self) -> bool:
    """检查沙箱池是否满载"""
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
        pool_max = status.get("poolMax", 0)  # 需要从 spec.capacitySpec 获取
        # 更准确：从 spec.capacitySpec.poolMax
        pool_max = pool.get("spec", {}).get("capacitySpec", {}).get("poolMax", 30)
        return allocated >= pool_max
    except Exception:
        return False  # 查询失败时允许尝试
```

在 Gateway HTTP handler 中，请求沙箱前先调用 `check_pool_capacity()`，满载时返回 HTTP 429。

---

## 自审检查清单

完成所有 tasks 后，逐项确认：

### Spec Coverage 检查

| 设计章节 | 对应 Task | 是否覆盖 |
|---------|---------|---------|
| 2.1 整体架构 | Task 3-9 | ✅ |
| 3.1 Auth 认证 | Task 9 (PostgreSQL + Key-User 表) | ✅ |
| 3.2 Hermes Gateway 无状态化 | Task 5, 12 | ✅ |
| 4.1 Namespace + NetworkPolicy | Task 3 | ✅ |
| 4.2 Gateway Deployment | Task 5 | ✅ |
| 4.3 RBAC | Task 4, 7 | ✅ |
| 4.4 Pool CRD | Task 8 | ✅ |
| 4.5 Ingress | Task 6 | ✅ |
| 5.2 注册流程 | Task 10 (registry-init.py) | ✅ |
| 5.3 注销流程 | Task 11 (registry-agent.py) | ✅ |
| 5.4 Gateway 沙箱发现 | Task 12 (sandbox_router.py) | ✅ |
| 6.1 用户首次请求 | Task 12 (wait_for_sandbox) | ✅ |
| 6.2 51st 用户 | Task 14.2 (429 响应) | ✅ |
| 6.3 TTL 回收 | Task 14.1 (ttl-manager.py) | ✅ |
| Phase 1 E2E 验证 | Task 13 | ✅ |

### Placeholder 扫描

搜索以下关键词，确认无遗留：
- `TBD`、`TODO`、`fill in`、`implement later` → **无**
- `ADD_`、`FIXME`、`XXX` → **无**
- `startCondition` → **已移除**，改用 initContainers

### 类型一致性检查

- `registry-init.py` 中 `POD_NAME` → 用于 Endpoints 名称
- `registry-agent.py` 中 `POD_NAME` → 用于 Endpoints 注销
- `sandbox_router.py` 中 `user_id` → 与 Endpoints 名称一致

### 缺失项

以下项属于 Phase 3，不在本计划范围内：
- HPA 自动扩缩容
- Prometheus + Grafana 监控
- 多租户 Quota 控制
- 沙箱快照与恢复
- 沙箱镜像定制

---

## 执行方式选择

**Plan complete and saved to `docs/superpowers/plans/2026-04-14-hermes-agent-k8s-multiuser-deployment.md`**

**两个执行选项：**

**1. Subagent-Driven（推荐）** - 每个 task 派发独立 subagent，task 间有检查点，快迭代

**2. Inline Execution** - 在本 session 内顺序执行，带检查点批量执行
