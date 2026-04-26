# Hermes Agent + OpenSandbox 统一生命周期管理设计（v2）

**Date:** 2026-04-16
**Status:** Draft
**Based on:** OpenSandbox v1alpha1 CRD 实际字段

## 1. 概述

### 1.1 目标

通过 OpenSandbox 的 **Pool + BatchSandbox** 组合，实现 Hermes Agent 服务和用户沙箱的统一生命周期管理。

### 1.2 核心约束

- **不修改 hermes-agent 核心代码**（运维部署脚本除外）
- 已有的 `gateway/sandbox_router.py`、`scripts/registry-init.py` 等保留
- Hermes Agent Docker 镜像使用官方版本
- 一切配置通过环境变量、ConfigMap、Secret 传入
- **单台服务器**，使用本地存储

### 1.3 关键发现：OpenSandbox CRD 真实字段

| CRD | apiVersion | 关键能力 |
|-----|-----------|---------|
| Pool | `sandbox.opensandbox.io/v1alpha1` | 预热节点池：capacitySpec (poolMin/Max, bufferMin/Max) |
| BatchSandbox | `sandbox.opensandbox.io/v1alpha1` | 按需创建沙箱，**支持 expireTime（TTL）**，支持 poolRef 从 Pool 分配 |

**Pool + BatchSandbox 组合：**
- Pool 管理预热节点（快速分配）
- BatchSandbox 从 Pool 分配节点，设置 expireTime 实现 TTL
- 两者配合 = 预热 + 按需 + 自动过期

### 1.4 架构概览

```
┌──────────────────────────────────────────────────────────────┐
│                    K8s Cluster (单节点)                       │
│                                                              │
│  ┌───────────────────────────────────────────────────────┐   │
│  │   hermes-agent namespace                              │   │
│  │                                                       │   │
│  │  ┌─────────────────┐  ┌─────────────────────────┐    │   │
│  │  │ hermes-gateway   │  │ hermes-sandbox-pool     │    │   │
│  │  │ Deployment (1副本)│  │ Pool (预热沙箱节点)    │    │   │
│  │  │ + sandbox_router │  │ poolMin:2 poolMax:50    │    │   │
│  │  │ + dashboard      │  │ bufferMin:2 bufferMax:10│    │   │
│  │  └─────────────────┘  └─────────────────────────┘    │   │
│  │          │                         ▲                  │   │
│  │          │ BatchSandbox             │ poolRef          │   │
│  │          │ (per-user)               │                  │   │
│  │          ▼                         │                  │   │
│  │  ┌─────────────────────────────────┐                  │   │
│  │  │ sandbox-{user_id}              │                   │   │
│  │  │ BatchSandbox (replicas:1)      │                   │   │
│  │  │ poolRef: hermes-sandbox-pool   │                   │   │
│  │  │ expireTime: now+30m            │                   │   │
│  │  └─────────────────────────────────┘                  │   │
│  │                                                       │   │
│  │  ┌──────────────┐  ┌──────────────┐                  │   │
│  │  │ hermes-webui │  │ postgres     │                  │   │
│  │  │ Deployment   │  │ StatefulSet  │                  │   │
│  │  └──────────────┘  └──────────────┘                  │   │
│  └───────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌───────────────────────────────────────────────────────┐   │
│  │              OpenSandbox Controller                    │   │
│  └───────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌───────────────────────────────────────────────────────┐   │
│  │              Local PV (hostPath)                       │   │
│  │              /data/hermes/                             │   │
│  └───────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────┘
```

## 2. CRD 配置（基于真实字段）

### 2.1 用户沙箱 Pool（预热节点池）

```yaml
apiVersion: sandbox.opensandbox.io/v1alpha1
kind: Pool
metadata:
  name: hermes-sandbox-pool
  namespace: hermes-agent
spec:
  template:
    spec:
      runtimeClassName: gvisor          # gVisor 隔离（可选，需节点安装）
      containers:
        - name: hermes-sandbox
          image: nousresearch/hermes-agent:latest
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
          resources:
            requests:
              memory: "512Mi"
              cpu: "250m"
            limits:
              memory: "1Gi"
              cpu: "1000m"
  capacitySpec:
    poolMin: 2                          # 最少保持 2 个预热节点
    poolMax: 50                         # 最多 50 个
    bufferMin: 2                        # 最少 2 个空闲
    bufferMax: 10                       # 最多 10 个空闲预热
```

### 2.2 Hermes Gateway（标准 Deployment，非 Pool）

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: hermes-gateway
  namespace: hermes-agent
spec:
  replicas: 1                           # 单台服务器用 1 副本
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
          command: ["bash", "-c", "uv pip install --system --break-system-packages 'hermes-agent[web]' -i https://pypi.tuna.tsinghua.edu.cn/simple && hermes gateway & python3 -m hermes_cli.main dashboard --host 0.0.0.0 --port 9119 --insecure & wait"]
          ports:
            - containerPort: 8642       # API
            - containerPort: 9119       # Dashboard
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
          volumeMounts:
            - name: hermes-data
              mountPath: /opt/data
      volumes:
        - name: hermes-data
          persistentVolumeClaim:
            claimName: hermes-data-pvc
```

### 2.3 用户沙箱（BatchSandbox，由 sandbox_router 创建）

由 `gateway/sandbox_router.py` 自动创建，实际 YAML 等效于：

```yaml
apiVersion: sandbox.opensandbox.io/v1alpha1
kind: BatchSandbox
metadata:
  name: sandbox-{user_id}               # 每用户一个
  namespace: hermes-agent
  labels:
    user_id: "{user_id}"
spec:
  replicas: 1
  poolRef: hermes-sandbox-pool          # 从 Pool 分配预热节点
  expireTime: "2026-04-16T12:00:00Z"   # TTL: 创建时间 + 30min
```

**关键：`expireTime` 实现 TTL！** 不需要外部 TTL manager。

## 3. 数据流

```
用户请求 → Ingress → hermes-gateway:8642
                          │
                          ├── GET /v1/chat/completions (带 API Key)
                          │
                          ▼
                    sandbox_router.get_or_create_sandbox(user_id)
                          │
                          ├── 1. 查询 BatchSandbox (label: user_id=xxx)
                          ├── 2. 不存在 → 创建 BatchSandbox (poolRef + expireTime)
                          ├── 3. 等待 Pod Ready
                          ├── 4. 获取 Pod IP → http://pod-ip:8642
                          │
                          ▼
                    转发请求 → sandbox-{user_id}:8642
                                        │
                                        ▼
                                   用户专属 Hermes Agent
```

## 4. 存储设计（单台服务器）

### 4.1 Local PV

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

### 4.2 PVC

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

## 5. 网络架构

### 5.1 Ingress

```
Internet
    │
    ▼
┌─────────────────┐
│   Ingress       │
│  (hermes.local) │
└─────────────────┘
    │
    ├── /api/*       → hermes-gateway:8642   (OpenAI 兼容 API)
    ├── /dashboard/* → hermes-gateway:9119   (原生 Dashboard)
    └── /webui/*     → hermes-webui:8080     (Open WebUI)
```

### 5.2 NetworkPolicy

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: hermes-agent-netpol
  namespace: hermes-agent
spec:
  podSelector: {}
  policyTypes:
    - Ingress
    - Egress
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              name: hermes-agent     # 限制为同 namespace 内的流量
      ports:
        - port: 8642
        - port: 9119
  egress:
    - {}              # Hermes 需要访问外部 API，完全放行
```

## 6. 生命周期管理

### 6.1 Hermes 服务（标准 K8s 资源）

| 服务 | 类型 | 生命周期 | 管理 |
|------|------|---------|------|
| hermes-gateway | Deployment | 常驻 | kubectl scale / helm upgrade |
| hermes-webui | Deployment | 常驻 | kubectl scale |
| postgres | StatefulSet | 常驻 | 标准 K8s 管理 |

### 6.2 用户沙箱（OpenSandbox BatchSandbox）

| 阶段 | 触发 | 说明 |
|------|------|------|
| 创建 | sandbox_router.create_sandbox() | BatchSandbox + poolRef 从 Pool 分配 |
| 就绪 | BatchSandbox status.ready=1 | Pod Running + Readiness 通过 |
| 使用 | gateway 转发请求到 Pod IP | sandbox_router.get_sandbox_url() |
| 更新 | sandbox_router._update_endpoint_timestamp() | 更新 last_seen annotation |
| 过期 | BatchSandbox expireTime 到达 | OpenSandbox Controller 自动删除 |
| 回收 | Pool 回收节点到 buffer | 节点回到预热池 |

### 6.3 Pool 弹性

```
用户请求 ↑
    │
    ▼
Pool buffer 下降 → Controller 自动扩容 (到 bufferMax)
    │
用户请求 ↓
    │
    ▼
BatchSandbox expireTime 到达 → 节点归还 Pool
    │
    ▼
Pool buffer 上升 → Controller 自动缩容 (到 poolMin)
```

## 7. 隔离级别（通过 runtimeClassName）

### 7.1 容器级隔离（默认）

```yaml
spec:
  template:
    spec:
      runtimeClassName: gvisor    # 需要节点安装 gVisor (runsc)
```

### 7.2 VM 级隔离（高安全需求）

```yaml
spec:
  template:
    spec:
      runtimeClassName: kata-fc   # Firecracker microVM (需安装 Kata Containers)
```

**两种隔离通过创建不同的 Pool 实现，sandbox_router 根据用户标签选择 Pool。**

## 8. 文件结构

```
hermes-agent/                            # 现有仓库
├── docker/
│   └── entrypoint-merged.sh            # [已有] Gateway + Dashboard 合并入口
├── gateway/
│   └── sandbox_router.py               # [已有] BatchSandbox 沙箱路由
├── scripts/
│   ├── registry-init.py                # [已有] 沙箱 init 注册
│   ├── registry-agent.py               # [已有] 沙箱注册 Agent
│   └── ttl-manager.py                  # [已有] TTL 管理（可被 expireTime 替代）
├── kubernetes/                          # [已有] K8s 清单
│   ├── namespace.yaml
│   ├── gateway/
│   │   ├── deployment.yaml             # 更新：合并 Dashboard + 环境变量
│   │   ├── rbac.yaml
│   │   ├── pdb.yaml
│   │   ├── ingress.yaml
│   │   └── service.yaml
│   ├── sandbox/
│   │   ├── pool.yaml                   # 新建：基于真实 CRD 字段
│   │   └── sandbox-rbac.yaml
│   └── postgres/
│       ├── statefulset.yaml
│       ├── service.yaml
│       └── secret.yaml
└── helm/
    └── hermes-agent/                   # 新建：Helm Chart
        ├── Chart.yaml
        ├── values.yaml
        └── templates/
            ├── deployment-gateway.yaml
            ├── deployment-webui.yaml
            ├── pool-sandbox.yaml
            ├── statefulset-postgres.yaml
            ├── ingress.yaml
            ├── pvc.yaml
            ├── rbac.yaml
            ├── networkpolicy.yaml
            └── quota.yaml
```

## 9. 实施计划

### Phase 1: OpenSandbox 部署
1. 安装 OpenSandbox Controller (Helm)
2. 验证 CRD 注册成功

### Phase 2: Hermes 服务部署
3. 创建 namespace + RBAC + NetworkPolicy
4. 部署 PostgreSQL StatefulSet
5. 部署 Hermes Gateway Deployment (合并 Dashboard)
6. 部署 Open WebUI Deployment
7. 配置 Ingress

### Phase 3: 用户沙箱
8. 创建 hermes-sandbox-pool (Pool CRD)
9. 验证 sandbox_router 能创建 BatchSandbox
10. 验证 expireTime 自动回收
11. 验证端到端请求路由

### Phase 4: 运维完善
12. 打包 Helm Chart
13. 配置 Prometheus 监控
14. 编写运维文档

## 10. 与现有代码的关系

### 10.1 sandbox_router.py（需要修改 4 处）

> **Code Review 发现（2026-04-16）：**
> - [Critical] Pool 模式下 Pod 由 Pool 预创建，名称与 BatchSandbox 无关，不能用 label selector 按 BatchSandbox 名称查找
> - [Critical] OpenSandbox Controller 在 BatchSandbox 的 `sandbox.opensandbox.io/endpoints` 注解中写入 Pod IP（JSON 数组），可直接读取
> - [Critical] RBAC 需要添加 `patch` 权限
> - [Important] K8s client 初始化应合并到 `__init__` 中一次完成

#### 修改 0: 构造函数 — 合并 K8s client 初始化

```python
from datetime import datetime, timezone, timedelta
import json

class SandboxRouter:
    def __init__(self):
        # K8s 配置只初始化一次
        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()
        self._core_v1 = client.CoreV1Api()
        self._sandbox_v1 = client.CustomObjectsApi()
```

#### 修改 1: get_sandbox_url() — 直接读 endpoints 注解

**问题：**
- 当前代码用 `read_namespaced_pod(name=batch_name)` 直接查找 Pod，会 404
- Pool 模式下，Pod 由 Pool Controller 预创建，名称与 BatchSandbox 名称无关
- 不存在 `batchsandbox.opensandbox.io/name` 这样的 label

**正确方案：** OpenSandbox Controller 在 BatchSandbox 的 `sandbox.opensandbox.io/endpoints` 注解中写入 Pod IP（JSON 数组），直接读取即可，一次 API 调用搞定。

```python
ENDPOINTS_ANNOTATION = "sandbox.opensandbox.io/endpoints"

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
        return None  # Pod 尚未就绪或未分配
    except ApiException as e:
        if e.status == 404:
            return None
        raise
    except Exception:
        return None
```

#### 修改 2: create_sandbox() — 添加 expireTime

**新增：** 创建时设置 `expireTime`，默认 now + 30min。保留 409 幂等处理。

```python
def _get_expire_time(self, minutes: int) -> str:
    """计算 expireTime（ISO 8601 UTC）"""
    expire = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    return expire.strftime("%Y-%m-%dT%H:%M:%SZ")

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
            "labels": {"user_id": user_id}
        },
        "spec": {
            "poolRef": pool_name,
            "replicas": 1,
            "expireTime": self._get_expire_time(SANDBOX_TTL_MINUTES)
        }
    }

    try:
        self._sandbox_v1.create_namespaced_custom_object(
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
```

#### 修改 3: _update_endpoint_timestamp() — 每次请求续期 expireTime

**策略：永久 + 每次请求续期。** 用户持续使用时沙箱永不过期；停止使用 30 分钟后自动回收。

> **竞态说明：** Gateway 续期 `spec.expireTime` 与 Controller 删除过期对象存在理论竞态。
> 如果续期请求恰好在 Controller 执行删除的瞬间到达，对象可能被删除。
> `get_or_create_sandbox()` 已有回退逻辑：如果 URL 查找失败，会重新创建沙箱。

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
            # BatchSandbox 已被 Controller 删除，忽略（下次请求会重建）
            return
        print(f"[SandboxRouter] Failed to renew expireTime: {e}")
    except Exception:
        pass  # 静默失败，不阻塞路由
```

### 10.2 RBAC 修改（必须）

当前 RBAC 缺少 `patch` 权限，TTL 续期会 403 Forbidden。

```yaml
# kubernetes/gateway/rbac.yaml — 必须添加 patch
- apiGroups: ["sandbox.opensandbox.io"]
  resources: ["batchsandboxes", "batchsandboxes/status"]
  verbs: ["get", "list", "watch", "create", "delete", "patch"]  # 添加 patch
```

### 10.3 ttl-manager.py（可被 expireTime 替代）

BatchSandbox 的 `expireTime` 字段原生支持 TTL，可以替代独立的 `ttl-manager.py` 脚本。但保留 `ttl-manager.py` 作为备用方案。

### 10.3 entrypoint-merged.sh（已有，保留）

Gateway + Dashboard 合并入口，直接复用。

### 10.4 分支策略

所有 OpenSandbox 相关修改（包括 `sandbox_router.py`、K8s YAML、Helm Chart）在独立分支 `feature/opensandbox-lifecycle` 上进行，不与主代码分支（`local-v0.9.0` / `main`）纠缠。

---

## 附录 A: Pool CRD 字段速查

```yaml
apiVersion: sandbox.opensandbox.io/v1alpha1
kind: Pool
spec:
  template:                    # PodTemplateSpec (K8s 标准)
    spec:
      runtimeClassName: gvisor  # 隔离级别
      containers: [...]
  capacitySpec:                 # 必填
    poolMin: int32              # 池最小节点数
    poolMax: int32              # 池最大节点数
    bufferMin: int32            # 最小空闲预热数
    bufferMax: int32            # 最大空闲预热数
  scaleStrategy:                # 可选
    maxUnavailable: int-or-string  # 默认 25%
  updateStrategy:               # 可选
    maxUnavailable: int-or-string  # 默认 25%
```

## 附录 B: BatchSandbox CRD 字段速查

```yaml
apiVersion: sandbox.opensandbox.io/v1alpha1
kind: BatchSandbox
spec:
  replicas: int32              # 必填，默认 1
  poolRef: string              # 引用 Pool（与 template 互斥）
  template: PodTemplateSpec    # 直接模板（与 poolRef 互斥）
  expireTime: datetime         # 过期时间，到达后自动删除
  taskTemplate: TaskTemplateSpec  # 自动派发任务
  taskResourcePolicyWhenCompleted: Retain | Release
```
