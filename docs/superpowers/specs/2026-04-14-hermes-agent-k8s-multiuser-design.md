# Hermes Agent K8s 多用户沙箱部署设计

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
[Hermes Gateway Cluster] (Kubernetes Deployment, 2 replicas)
  - 认证：校验 API Key，识别用户身份 (user_id)
  - 路由：根据用户选择常驻沙箱 / 创建临时沙箱
  - 消息聚合：汇总沙箱响应返回给用户
    ↓
[OpenSandbox Pool] (常驻沙箱 per 用户)
  - 常驻沙箱：用户登录时分配，生命周期与用户会话绑定
  - 临时沙箱：复杂任务按需创建，任务完成后销毁
    ↓
[Hermes Agent inside Sandbox Pod] (容器内运行 bash/terminal)
```

### 2.2 核心组件

| 组件 | 类型 | 说明 |
|------|------|------|
| Hermes Gateway | K8s Deployment | 无状态，2+ replicas，API Key 认证，路由逻辑 |
| OpenSandbox Controller | K8s Deployment | Operator，管理 BatchSandbox/Pool CRD |
| Sandbox Pod (per user) | K8s Pod | 独立沙箱，Long-lived，包含 Hermes Agent |
| API Gateway / Nginx | 集群外 | 反向代理 + TLS termination |

### 2.3 数据流

1. 用户请求到达 API Gateway，做 TLS termination
2. 请求转发至 Hermes Gateway Cluster
3. Gateway 校验 API Key，提取 `user_id`
4. Gateway 查询该用户的沙箱状态：
   - 有常驻沙箱 → 路由到该沙箱
   - 无常驻沙箱 → 通过 OpenSandbox 创建新沙箱（常驻）
5. 沙箱内 Hermes Agent 处理请求
6. 响应通过 Gateway 聚合返回用户

## 3. 组件设计

### 3.1 Hermes Gateway (无状态化改造)

**现状**：当前 docker-compose 中 Hermes Gateway 直接运行在容器内，调用本地沙箱。

**改造目标**：Gateway 无状态化，不直接运行沙箱，通过 API 与沙箱通信。

**关键改动**：
- 新增沙箱发现服务：给定 `user_id`，找到对应沙箱的 API endpoint
- 新增沙箱生命周期通知：用户上线/下线时通知 OpenSandbox 创建/释放沙箱
-沙箱 API 适配层：Hermes Agent 暴露 HTTP API，Gateway 通过 HTTP 调用

**接口设计**：
```
沙箱注册表 (in-cluster service):
  - PUT /sandboxes/{user_id}     # 注册沙箱 endpoint
  - DELETE /sandboxes/{user_id}   # 注销沙箱
  - GET /sandboxes/{user_id}     # 获取沙箱 endpoint

沙箱 HTTP API (每个沙箱内):
  - POST /v1/chat/completions     # 发送对话请求
  - GET /health                  # 健康检查
```

### 3.2 OpenSandbox 集成

**使用 OpenSandbox 的资源池能力**：
- 使用 `Pool` CRD 预热沙箱镜像（bufferMin/bufferMax 控制预热数量）
- 使用 `BatchSandbox` CRD 创建常驻沙箱（replicas=1 per user）
- 沙箱模板使用 nousresearch/hermes-agent 镜像

**沙箱网络**：
- 每个沙箱 Pod 分配固定 ClusterIP
- Gateway 通过 `<user_id>.sandbox.svc.cluster.local` 访问

### 3.3 用户身份与沙箱绑定

**认证流程**：
```
API Key (用户提供)
  → Gateway 解析出 user_id
  → 查询沙箱注册表
  → 路由到对应沙箱 Pod
```

**沙箱注册表**：
- 使用 Kubernetes ConfigMap 或专门的 Sidecar Service 存储 user_id → sandbox_endpoint 映射
- 用户登录时创建映射，用户登出时删除
- TTL 机制：用户无活动 N 分钟后自动回收沙箱

### 3.4 混合沙箱模式

**常驻沙箱**：
- 用户首次请求时创建，绑定到 user_id
- 生命周期：用户会话期间，或 TTL 超时
- 用于处理日常对话，低延迟

**临时沙箱**：
- 复杂任务（代码执行、长时间操作）时按需创建
- BatchSandbox CR 创建，任务完成后自动销毁
- 高资源消耗场景使用

## 4. Kubernetes 资源设计

### 4.1 Namespace

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: hermes-agent
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
  template:
    spec:
      containers:
        - name: gateway
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
          readinessProbe:
            httpGet:
              path: /health
              port: 8642
          livenessProbe:
            httpGet:
              path: /health
              port: 8642
```

### 4.3 Hermes Gateway Service

```yaml
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
```

### 4.4 OpenSandbox Pool (预热池)

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
      containers:
        # 主容器：Hermes Agent
        - name: sandbox
          image: nousresearch/hermes-agent:latest
          command: ["hermes", "gateway"]
          ports:
            - containerPort: 8642
          env:
            - name: POD_IP
              valueFrom:
                fieldRef:
                  fieldPath: status.podIP
          lifecycle:
            preStop:
              exec:
                command: ["/bin/sh", "-c", "wget -q -O- --post-data='' http://localhost:8080/deregister 2>/dev/null || true"]
        # Sidecar：Registry Agent（处理注册/注销）
        - name: registry-agent
          image: nousresearch/hermes-agent:latest
          command: ["python3", "/opt/hermes/scripts/registry-agent.py"]
          ports:
            - containerPort: 8080
          env:
            - name: POD_NAME
              valueFrom:
                fieldRef:
                  fieldPath: metadata.name
            - name: SANDBOX_REGISTRY_URL
              value: "http://sandbox-registry:8080"
            - name: SANDBOX_PORT
              value: "8642"
  capacitySpec:
    bufferMin: 3
    bufferMax: 10
    poolMin: 3
    poolMax: 20
```

> **说明**：每个沙箱 Pod 包含两个容器：
> - **sandbox**（主）：Hermes Agent，监听 8642
> - **registry-agent**（Sidecar）：轻量 HTTP Server，监听 8080，Pod 启动时自动注册 endpoint，Pod 终止时（preStop）自动注销

### 4.5 Sandbox Registry Service + ConfigMap

Sandbox Registry 是一个轻量级 HTTP Sidecar Service，运行在每个沙箱 Pod 内，负责沙箱 endpoint 的注册/注销。Gateway 通过 K8s Service 统一访问 Registry。

```yaml
---
# Registry Sidecar Service（所有沙箱 Pod 内共享访问）
apiVersion: v1
kind: Service
metadata:
  name: sandbox-registry
  namespace: hermes-agent
spec:
  type: ClusterIP
  ports:
    - port: 8080
      targetPort: 8080
---
# 注册表数据（ConfigMap 存储 user_id → sandbox endpoint 映射）
apiVersion: v1
kind: ConfigMap
metadata:
  name: sandbox-registry
  namespace: hermes-agent
data:
  # 由沙箱 Pod 内的 registry-agent 自动写入
  # 格式示例：user_123 -> "http://10.244.1.45:8642"
```

> **关键机制**：每个沙箱 Pod 包含两个容器：
> 1. **sandbox**（主容器）：运行 Hermes Agent，监听 8642 端口
> 2. **registry-agent**（Sidecar）：轻量 HTTP Server，监听 8080 端口
>    - Pod 启动时：registry-agent 将 `<pod-ip>:8642` 注册到 ConfigMap，key 为 `user_id`
>    - Pod 终止时（preStop hook）：自动从 ConfigMap 注销
> - Gateway 通过 `sandbox-registry:8080` 查询/注册沙箱 endpoint

### 4.6 Ingress (Gateway 暴露)

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: hermes-gateway-ingress
  namespace: hermes-agent
spec:
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

## 5. 关键问题与解决方案

### 5.1 Gateway 如何发现沙箱？

**方案**：引入 Sandbox Registry Sidecar

- 每个沙箱 Pod 启动时，向 Registry Sidecar 注册自己的 endpoint
- Gateway 通过 K8s Service 访问 Registry
- Registry 使用 ConfigMap 存储 user_id → endpoint 映射

### 5.2 用户首次请求时沙箱未创建？

**流程**：
1. Gateway 查询 Registry，发现用户无沙箱
2. Gateway 调用 OpenSandbox API 创建常驻沙箱（BatchSandbox, replicas=1）
3. 等待沙箱 Ready（OpenSandbox 反馈）
4. 获取沙箱 endpoint
5. 注册到 Registry
6. 路由请求

### 5.3 沙箱内 Hermes Agent 如何暴露 API？

沙箱 Pod 内的 Hermes Agent 本身就是 Gateway 模式运行，监听 8642 端口。

沙箱 Pod 的 Service 暴露该端口，Gateway 通过 `<user_id>.sandbox-service.hermes-agent.svc.cluster.local:8642` 访问。

### 5.4 数据持久化

- 用户会话数据：Hermes 使用 SQLite 存储在 `$HERMES_HOME/sessions/`
- 持久化方案：每个沙箱 Pod 挂载 PVC (`hermes-sandbox-pvc-<user_id>`)
- 临时沙箱：任务完成后 PVC 删除

## 6. 实施步骤

### Phase 1: 基础部署（当前设计范围）

1. 部署 OpenSandbox Controller 到 K8s 集群
2. 创建 hermes-agent namespace
3. 构建/推送 hermes-agent Docker 镜像到 Registry
4. 部署 Hermes Gateway Deployment + Service
5. 配置 Ingress（对接已有 API 网关）
6. 创建 Sandbox Pool（预热）
7. 端到端验证：API Key 认证 → 请求路由 → 沙箱响应

### Phase 2: 沙箱生命周期管理

1. 实现 Sandbox Registry Sidecar
2. 实现用户上线/下线流程
3. 配置沙箱 TTL 回收机制
4. 常驻沙箱 vs 临时沙箱路由逻辑

### Phase 3: 增强与优化

1. HPA 自动扩缩容 Hermes Gateway
2. OpenSandbox Pool 自动扩缩
3. 计量与监控（Prometheus + Grafana）
4. 权限与 Quota 控制

## 7. 测试计划

### 7.1 单元测试

- API Key 解析正确性
- Registry 映射读写
- 沙箱 endpoint 路由

### 7.2 集成测试

- 用户 A 认证 → 分配沙箱 → 请求响应
- 用户 B 认证 → 分配独立沙箱 → 数据隔离验证
- 用户登出 → 沙箱回收 → 新用户复用

### 7.3 压力测试

- 50 并发用户同时在线
- 沙箱创建/销毁速率
- Gateway 吞吐量

## 8. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 沙箱冷启动延迟 | 用户体验差 | Pool 预热 + bufferMin 保持热备 |
| 沙箱 Pod OOM | 服务中断 | 设置合理 resource limits |
| Registry 单点 | 路由失败 | 使用 K8s Service 作为 Registry |
| 镜像拉取慢 | 扩容延迟 | 使用同集群 Registry 缓存 |

## 9. 配置参考

关键环境变量：

| 变量 | 值 | 说明 |
|------|-----|------|
| API_SERVER_ENABLED | true | 启用 API Server |
| API_SERVER_HOST | 0.0.0.0 | 监听地址 |
| API_SERVER_PORT | 8642 | 监听端口 |
| GATEWAY_ALLOW_ALL_USERS | true | 允许所有认证用户 |
| HERMES_HOME | /opt/data | 数据目录（需 PVC 挂载）|
