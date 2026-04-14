# Hermes Agent K8s 多用户沙箱部署设计 v2

> 基于三专家审核反馈修订：K8s专家 × 架构专家 × 产品专家

## 1. 背景与目标

将 Hermes Agent 部署到 Kubernetes 集群，通过 OpenSandbox 实现多用户沙箱管理，达到以下目标：

- **用户隔离**：每个用户拥有独立的沙箱容器，数据不共享
- **原生认证**：复用 Hermes Gateway 的 API Key 机制识别用户
- **混合沙箱模式**：常驻沙箱处理日常对话 + 临时沙箱处理复杂任务
- **小规模起步**：< 50 并发，架构验证优先
- **内网部署**：通过 API 网关对外暴露服务

## 2. 架构设计

### 2.1 整体架构

```
用户请求 (HTTPS)
    ↓
[API Gateway / Nginx] → TLS termination, 路由到 Hermes Gateway
    ↓
[Hermes Gateway Cluster] (Kubernetes Deployment, 2 replicas, HA)
  - 认证：校验 API Key，识别用户身份 (user_id)
  - 沙箱发现：通过 Endpoints 查询沙箱地址
  - 路由：根据用户选择常驻沙箱 / 创建临时沙箱
  - 消息聚合：汇总沙箱响应返回给用户
    ↓
[沙箱沙箱注册表 (Endpoints 资源)] ← 每用户一条 Endpoint 记录
    ↓
[沙箱 Pod (per user)] (OpenSandbox 管理)
  - 常驻沙箱：用户登录时分配，生命周期与用户会话绑定
  - 临时沙箱：复杂任务按需创建，任务完成后销毁
    ↓
[Hermes Agent inside Sandbox Pod]
```

### 2.2 核心组件

| 组件 | 类型 | 说明 |
|------|------|------|
| Hermes Gateway | K8s Deployment | 无状态，2+ replicas，API Key 认证，路由逻辑 |
| Sandbox Registry | K8s Endpoints | 存储 user_id → sandbox_endpoint 映射，无单点 |
| OpenSandbox Controller | K8s Deployment | Operator，管理 BatchSandbox/Pool CRD |
| Sandbox Pod (per user) | K8s Pod | 独立沙箱，Long-lived，包含 Hermes Agent |
| API Gateway / Nginx | 集群外 | 反向代理 + TLS termination |

### 2.3 数据流

1. 用户请求到达 API Gateway，做 TLS termination
2. 请求转发至 Hermes Gateway Cluster (Service: hermes-gateway)
3. Gateway 校验 API Key，从 Key-User 表提取 `user_id`
4. Gateway 查询 Endpoints 获取该用户的沙箱地址：
   - 有常驻沙箱 → 直接路由到沙箱 Pod
   - 无常驻沙箱 → 调用 OpenSandbox 创建新沙箱（常驻），沙箱就绪后注册到 Endpoints
5. 沙箱内 Hermes Agent 处理请求
6. 响应通过 Gateway 聚合返回用户

## 3. 组件设计

### 3.1 认证流程（API Key → user_id）

```
用户提供 API Key (HTTP Header: Authorization: Bearer <key>)
  → Gateway 查询 Key-User 映射表（PostgreSQL/MySQL）
  → 映射表返回 user_id + sandbox_policy
  → Gateway 根据 sandbox_policy 决定路由
```

**Key-User 映射表设计**：

| 字段 | 类型 | 说明 |
|------|------|------|
| api_key | VARCHAR(64) | 用户的 API Key（SHA256 哈希存储）|
| user_id | VARCHAR(64) | 用户唯一标识 |
| sandbox_policy | ENUM | `resident`, `temporary`, `hybrid` |
| created_at | TIMESTAMP | 创建时间 |
| revoked_at | TIMESTAMP | 撤销时间（NULL=有效）|

> **说明**：API Key 建议使用现有的 Hermes API Server Key 机制，映射表可复用现有数据库。

### 3.2 Hermes Gateway (无状态化改造)

**现状**：当前 docker-compose 中 Hermes Gateway 直接运行在容器内，调用本地沙箱。

**改造目标**：Gateway 无状态化，不直接运行沙箱，通过 HTTP 与沙箱通信。

**关键接口**：

**沙箱 HTTP API (每个沙箱内)**：
```
POST /v1/chat/completions     # 发送对话请求
GET  /health                  # 健康检查
GET  /status                  # 沙箱状态 (idle/busy)
```

**Endpoints 注册**（沙箱 Pod 就绪后自动写入）：
```
# 沙箱 Pod 通过 initContainer 将自己的 IP:8642 注册到同名 Endpoints
# 每用户一个 Endpoints 资源，名称 = user_id
kubectl get endpoints <user_id> -n hermes-agent
# ADDRESS   PORT   PROTOCOL
# 10.244.1.45   8642   TCP
```

### 3.3 OpenSandbox 集成

**使用 OpenSandbox 的资源池能力**：
- 使用 `Pool` CRD 预热沙箱镜像（bufferMin/bufferMax 控制预热数量）
- 使用 `BatchSandbox` CRD 创建常驻沙箱（replicas=1 per user）
- 沙箱模板使用 nousresearch/hermes-agent 镜像

> ⚠️ **重要**：OpenSandbox Pool CRD 的实际字段名需要对照 `OpenSandbox/kubernetes/config/crd/bases/sandbox.opensandbox.io_pools.yaml` 确认。本文档中的字段名为推测，需要在实施前验证。当前 Phase 1 计划先用 `kubectl apply --dry-run=server` 验证 CRD 合法性。

**沙箱网络**：
- 每个沙箱 Pod 分配固定 ClusterIP
- Gateway 通过 `<user_id>.hermes-agent.svc.cluster.local` 即 `Endpoints` 资源访问

### 3.4 用户身份与沙箱绑定

**认证流程**：
```
API Key (用户提供)
  → Gateway 解析出 user_id
  → 查询 Kubernetes Endpoints (名称=user_id)
  → 获取沙箱 Pod IP:Port
  → 路由请求
```

**沙箱注册机制**：
- 每用户一个同名的 Kubernetes Endpoints 资源
- 沙箱 Pod 启动时，initContainer 等待主容器就绪后，将 Pod IP 注册到 Endpoints
- Pod 终止时（PreStop），通过优雅关闭流程注销
- Endpoints 是 Kubernetes 原生资源，支持原子更新，无 ConfigMap 的竞态问题

### 3.5 混合沙箱模式

**常驻沙箱**：
- 用户首次请求时创建，绑定到 user_id（通过 Endpoints 名称）
- 生命周期：用户会话期间，或 TTL 超时（默认 30 分钟无活动）
- 用于处理日常对话，低延迟
- TTL 超时后：OpenSandbox 删除 BatchSandbox，PVC 数据保留（供审计）

**临时沙箱**：
- 复杂任务（代码执行、长时间操作）时按需创建
- 通过 OpenSandbox BatchSandbox 创建，任务完成后自动删除
- 高资源消耗场景使用
- 不挂载用户 PVC，数据不持久

**路由决策**（Section 3.1 中 sandbox_policy）：
- `resident`：所有请求路由到常驻沙箱
- `temporary`：所有请求创建临时沙箱（每次新建）
- `hybrid`：普通对话→常驻沙箱，计算密集任务→临时沙箱（由 Agent 自行判断）

## 4. Kubernetes 资源设计

### 4.1 Namespace

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: hermes-agent
  labels:
    name: hermes-agent
---
# NetworkPolicy：只允许同 namespace 内的 Pod 访问沙箱
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
```

### 4.2 Hermes Gateway Deployment

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
          image: nousresearch/hermes-agent:v0.8.0  # 固定版本，不用 latest
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
# PodDisruptionBudget
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

### 4.3 RBAC (Gateway ServiceAccount + Permissions)

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

### 4.4 OpenSandbox Pool (预热池)

> ⚠️ **待验证**：以下 `capacitySpec` 字段名为推测。需要先执行 `kubectl apply --dry-run=server -f pool.yaml` 验证 CRD 合法性。若失败，对照 `OpenSandbox/kubernetes/config/crd/bases/sandbox.opensandbox.io_pools.yaml` 修正字段名。

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
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        fsGroup: 1000
      containers:
        # 主容器：Hermes Agent（运行 Agent 模式，不运行 Gateway 模式）
        - name: sandbox
          image: nousresearch/hermes-agent:v0.8.0
          imagePullPolicy: IfNotPresent
          command: ["hermes", "agent"]  # 修复：运行 agent 模式，不是 gateway 模式
          ports:
            - containerPort: 8642
          securityContext:
            readOnlyRootFilesystem: false  # Hermes 需要写 /tmp 等
            allowPrivilegeEscalation: false
            capabilities:
              drop: ["ALL"]
          env:
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
                    # 使用 curl 而非 wget（更通用）
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
        # Sidecar：Registry Agent（沙箱注册）
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
            - name: SANDBOX_IP
              valueFrom:
                fieldRef:
                  fieldPath: status.podIP
          resources:
            requests:
              cpu: 50m
              memory: 64Mi
            limits:
              cpu: 100m
              memory: 128Mi
          lifecycle:
            startCondition: FirstStart  # Sidecar 先于主容器启动
      volumes:
        - name: sandbox-data
          emptyDir: {}
  capacitySpec:
    bufferMin: 5       # 预热 5 个沙箱（调高应对 burst）
    bufferMax: 15
    poolMin: 5
    poolMax: 30        # 修正：poolMax 应 >= 目标并发数的 60%
```

### 4.5 Ingress (Gateway 暴露)

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

> **说明**：TLS 由 Ingress termination。若 API Gateway/Nginx 在集群外做 TLS termination，此处 Ingress 可用 `nginx.io/ssl-passthrough: "true"` 或让外部网关直接访问 Service。

## 5. 沙箱注册机制（Endpoints 方案）

### 5.1 方案选择

| 方案 | 优点 | 缺点 |
|------|------|------|
| ConfigMap | 简单 | ❌ 竞态 + 1MB 上限 + 无原子更新 |
| Endpoints（采用）| Kubernetes 原生，原子更新，支持 watch，无单点 | 需要 RBAC 权限 |
| 独立 CRD | 可扩展 | 需要额外开发 |
| Redis/etcd | 高性能 | 引入新组件 |

**Endpoints 方案**：每用户一个 Endpoints 资源（名称 = user_id），沙箱 Pod 启动时写入 `subsets.addresses[0].ip = <pod-ip>`。

### 5.2 注册流程

```
1. BatchSandbox 创建 → OpenSandbox 调度 Pod
2. Pod 内主容器 (sandbox) 启动，等待 Hermes Agent 就绪
3. Sidecar (registry-agent) 检测到主容器健康
4. Sidecar 调用 K8s API: PATCH endpoints/<user_id> 
   body: {"subsets": [{"addresses": [{"ip": "<pod-ip>"}], "ports": [{"port": 8642}]}]}
5. Gateway 查询: kubectl get endpoints <user_id> → 获取 Pod IP
```

### 5.3 注销流程

```
1. Pod 收到 SIGTERM（优雅关闭）
2. PreStop hook: curl -X POST http://localhost:8080/deregister
3. registry-agent 收到请求
4. registry-agent 调用 K8s API: PATCH endpoints/<user_id>
   body: {"subsets": []}  # 清空地址列表
5. registry-agent 退出码 0
6. 主容器收到 SIGTERM，开始自身关闭
```

> **注意**：若沙箱 Pod 被强制删除（kubectl delete --grace-period=0 / OOM），PreStop 不执行。Gateway 端需要实现超时重试逻辑：Endpoint 关联的 Pod 消失后，Gateway 自动触发沙箱重建。

### 5.4 Gateway 端沙箱发现逻辑

```python
def get_sandbox_endpoint(user_id: str) -> str:
    """查询 Endpoints 获取沙箱地址，超时则触发重建"""
    try:
        ep = client.get_endpoints(name=user_id, namespace="hermes-agent")
        if ep.subsets and ep.subsets[0].addresses:
            pod_ip = ep.subsets[0].addresses[0].ip
            return f"http://{pod_ip}:8642"
    except NotFound:
        pass
    
    # 沙箱不存在，触发创建
    sandbox = create_batchsandbox(user_id)
    wait_for_endpoints(user_id, timeout=60)
    return get_sandbox_endpoint(user_id)
```

## 6. 关键问题解决方案

### 6.1 用户首次请求时沙箱未创建？

**流程**：
1. Gateway 查询 Endpoints `<user_id>`，NotFound → 创建 BatchSandbox
2. OpenSandbox 调度 Pod，Pod 启动后注册到 Endpoints
3. Gateway 轮询 Endpoints 直到有地址（最多 60s 超时）
4. 若超时，返回 503 Service Unavailable（用户可重试）
5. 若 3 次重试均失败，告警并标记用户沙箱创建失败

### 6.2 51st 用户超出容量？

**缓解策略**：
- `poolMax: 30`，Buffer 预热 5 个
- **超出时排队**：Gateway 检测到 pool 满载后，返回 `429 Too Many Requests`，客户端等待后重试
- **临时扩容**：Gateway 可调用 OpenSandbox 临时扩展 Pool（若 CRD 支持）
- **资源回收**：优先回收超过 TTL 的常驻沙箱（30 分钟无活动）

> **注**：`< 50 并发` 是架构验证目标。Phase 1 验证 20-30 用户规模，若需支持 50+ 用户，需 Phase 2 优化 Pool 参数 + HPA。

### 6.3 TTL 沙箱回收机制

**定时扫描**（Gateway 侧或独立 CronJob）：
```python
# 每 5 分钟扫描所有活跃 Endpoints
# 查询 Pod 最后活跃时间（kubectl get pods --watch）
# 若用户无活动 > TTL(30min)，删除 BatchSandbox
```

**实现方式**：在 Hermes Gateway Deployment 中增加一个 sidecar container，运行 TTL 管理逻辑。

### 6.4 数据持久化

- 用户会话数据：SQLite 存储在 `$HERMES_HOME/sessions/`
- 持久化方案：沙箱 Pod 挂载 PVC `hermes-sandbox-pvc-<user_id_hash>`（user_id 做 SHA256 hash 避免特殊字符问题）
- 临时沙箱不挂载 PVC，任务完成后数据丢失
- 沙箱删除后 PVC 保留（设置 Retain Policy），供审计或数据恢复

## 7. 实施步骤

### Phase 1: 基础部署（核心功能验证）

目标：20-30 用户同时在线，常驻沙箱 + 临时沙箱。

1. 部署 OpenSandbox Controller（Helm 安装）
   ```bash
   helm install opensandbox-controller \
     https://github.com/alibaba/OpenSandbox/releases/download/helm/opensandbox-controller/0.1.0/opensandbox-controller-0.1.0.tgz \
     --namespace hermes-agent --create-namespace
   ```
2. 创建 hermes-agent namespace + NetworkPolicy
3. 构建/推送 hermes-agent Docker 镜像到 Registry（固定 tag v0.8.0）
4. 部署 Hermes Gateway Deployment + Service + RBAC + PDB
5. 部署 Ingress（对接已有 API 网关）
6. 创建 Sandbox Pool（预热），**先用 `kubectl apply --dry-run=server` 验证 CRD**
7. 部署 Key-User 映射数据库（PostgreSQL）
8. **端到端验证**：
   - 用户 A 认证 → 分配沙箱 → 对话响应
   - 用户 B 认证 → 分配独立沙箱 → 数据隔离验证
   - 临时沙箱创建 → 任务完成 → 自动销毁

### Phase 2: 生命周期 + 隔离增强

1. 实现 Registry Agent (registry-agent.py)，支持 Endpoints 注册/注销
2. 实现 TTL 回收机制（Gateway sidecar 或独立 CronJob）
3. 实现沙箱超额排队（429 响应 + 客户端重试）
4. 完善常驻/临时沙箱路由策略
5. 添加 Prometheus metrics（沙箱数量、创建延迟、认证失败率）
6. HPA 自动扩缩容 Hermes Gateway（CPU 70% 阈值）

### Phase 3: 企业级能力

1. OpenSandbox Pool 自动扩缩（基于队列长度）
2. 计量与监控（Grafana Dashboard）
3. 多租户 Quota 控制（每个 user_id 最大沙箱数量）
4. 沙箱镜像定制（预装额外工具）
5. 沙箱快照与恢复（用户数据回滚）

## 8. 测试计划

### 8.1 单元测试

- API Key → user_id 映射查询
- Endpoints 读写（原子性验证）
- TTL 计算逻辑
- 沙箱路由策略

### 8.2 集成测试

- 用户 A 认证 → 分配沙箱 → 请求响应
- 用户 B 认证 → 分配独立沙箱 → 数据隔离验证
- 用户登出 → Endpoints 注销 → TTL 到期 → 沙箱删除
- 沙箱 Pod 被 OOM → Gateway 重建 → 用户无感知重试

### 8.3 压力测试

- 20 并发用户同时在线
- poolMax 边界测试（30 用户 + 5 新用户同时进入）
- 沙箱 Pod 突然终止（节点宕机）的恢复时间

## 9. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 沙箱冷启动延迟（>30s） | 用户体验差 | Pool 预热 + bufferMin=5 保持热备；超时 60s 后客户端重试 |
| 沙箱 Pod OOM | 服务中断 | 设置合理 resource limits (1Gi memory)；PDB 保护 |
| Endpoints 竞态（Pod 快速启停） | Registry 不一致 | 使用 K8s 原生 Endpoints（原子更新）；Gateway 端超时重建 |
| 镜像拉取慢 | 扩容延迟 | 使用同集群 Registry 缓存；镜像预拉取到 Node |
| 超出 poolMax（51st 用户） | 拒绝服务 | 返回 429 + 客户端重试；优先回收空闲沙箱 |
| OpenSandbox Controller 故障 | 无法创建沙箱 | Gateway 检测并告警；已有沙箱可继续服务 |
| API Key 数据库不可用 | 全部用户无法认证 | 使用 HA PostgreSQL；Gateway 本地缓存 Key-User 映射 |

## 10. 配置参考

关键环境变量：

| 变量 | 值 | 说明 |
|------|-----|------|
| API_SERVER_ENABLED | true | 启用 API Server |
| API_SERVER_HOST | 0.0.0.0 | 监听地址 |
| API_SERVER_PORT | 8642 | 监听端口 |
| GATEWAY_ALLOW_ALL_USERS | true | 允许所有认证用户 |
| HERMES_HOME | /opt/data | 数据目录（需 PVC 挂载）|
| DB_HOST | postgres.hermes-agent.svc.cluster.local | Key-User 映射库地址 |
| SANDBOX_TTL_MINUTES | 30 | 常驻沙箱无活动回收时间 |

### OpenSandbox CRD 字段验证命令

```bash
# 验证 Pool CRD 字段是否正确
kubectl apply --dry-run=server -f - <<EOF
apiVersion: sandbox.opensandbox.io/v1alpha1
kind: Pool
metadata:
  name: test-pool
  namespace: hermes-agent
spec:
  template:
    spec:
      containers:
        - name: test
          image: nginx:latest
  capacitySpec:
    bufferMin: 1
    bufferMax: 2
    poolMin: 1
    poolMax: 3
EOF
```

若返回 validation error，对照 `OpenSandbox/kubernetes/config/crd/bases/sandbox.opensandbox.io_pools.yaml` 修正字段名。

## 11. 修订说明（v1 → v2）

基于三专家审核反馈的关键修改：

| # | 问题 | 修复方式 |
|---|------|---------|
| 1 | ConfigMap 竞态 + 1MB 上限 | 改用 Kubernetes Endpoints（原子更新，原生 watch） |
| 2 | OpenSandbox CRD 字段名未验证 | 添加 `kubectl apply --dry-run=server` 验证步骤 + 待验证说明 |
| 3 | Gateway Deployment 缺少 template labels | 补全 `spec.template.metadata.labels` |
| 4 | preStop hook 使用 wget | 改用 curl + sleep 2 延迟 |
| 5 | sandbox 容器运行 gateway 模式 | 改为 `hermes agent` 模式 |
| 6 | Auth 认证流程未定义 | 新增 3.1 节定义 Key-User 映射表 |
| 7 | 51st 用户场景未处理 | 新增 6.2 节定义排队 + 回收策略 |
| 8 | TTL 机制未设计 | 新增 6.3 节 TTL 回收方案 |
| 9 | 无 resource limits | 所有容器添加 requests/limits |
| 10 | 无 SecurityContext | 所有 Pod/容器添加 runAsNonRoot 等 |
| 11 | 无 PodDisruptionBudget | 添加 hermes-gateway-pdb |
| 12 | 无 RBAC | 添加 Role + RoleBinding |
| 13 | 无 NetworkPolicy | 添加 sandbox-isolation NetworkPolicy |
| 14 | Ingress 缺 TLS | 添加 tls section |
| 15 | poolMax=20 不足 | 调整为 poolMax=30 |
| 16 | 镜像用 latest | 改为固定版本 v0.8.0 |
| 17 | DNS 命名不一致 | 统一为 Endpoints 方案，DNS 即 `<user_id>.hermes-agent.svc.cluster.local` |
