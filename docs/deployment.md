# Hermes Agent 部署规范

## 架构概览

```
用户 (Telegram/Discord/Slack/WhatsApp/CLI/WebUI/...)
  → Ingress (Nginx, hostNetwork :40080)
    → Gateway (gateway/run.py) — 异步平台适配器，监听 8642
      → AIAgent (run_agent.py) — 同步 Agent 循环，LLM API 调用
        → Tool Registry (tools/registry.py) — 自注册工具系统

Admin Panel (admin/) — FastAPI + React，管理 K8s Agent 实例
  → 监听 48082，通过 K8s API 管理 Deployment
  → 用户注册/登录/激活，WebUI 自动 Provisioning

Orchestrator — 任务调度 + Agent 路由
  → 监听 8080，Redis 队列

Open WebUI — Web 聊天界面，监听 48080
  → per-user Direct Connection 注入 agent base_url + api_key
  → 通过 Admin iframe 免密跳转

PostgreSQL — Admin 用户数据 + Agent 元数据
Redis — Orchestrator 任务队列 + Swarm 协作
```

---

## 集群拓扑

### 开发集群 (184)

| 角色 | IP | 说明 |
|------|-----|------|
| K8s Master/Worker | 172.32.153.184 | kubectl 本地访问 |
| Ingress LB | 172.32.153.184 | Nginx Ingress hostNetwork |

### 测试集群 (183)

| 角色 | IP | 说明 |
|------|-----|------|
| K8s Master/Worker | 172.32.153.183 | SSH root@172.32.153.183 |
| ctr 路径 | /opt/containerd/bin/ctr | 镜像导入 |
| Ingress LB | 172.32.153.183 | Nginx Ingress hostNetwork |

---

## 端口映射

### 集群内部端口

| 端口 | 服务 | 协议 |
|------|------|------|
| 8642 | Gateway API | HTTP |
| 48082 | Admin Panel | HTTP |
| 48080 | Open WebUI | HTTP |
| 8080 | Orchestrator API | HTTP |
| 6379 | Redis | TCP |
| 9121 | Redis Exporter (metrics) | HTTP |
| 5432 | PostgreSQL | TCP |

### 外部端口映射

| 外部端口 | 集群端口 | 服务 | 路径 |
|----------|----------|------|------|
| 40080 | 80 (Ingress) | Admin/Gateway/WebUI | 见 Ingress 规则 |
| 48080 | 8080 (NodePort) | Open WebUI 直接访问 | `/` |

### Ingress 路由规则

| 路径 (regex) | 后端 Service:Port | rewrite-target |
|-------------|-------------------|----------------|
| `/admin/api(/\|$)(.*)` | hermes-admin:48082 | `/$2` |
| `/admin/assets/` | hermes-admin:48082 | (none) |
| `/admin(/\|$)(.*)` | hermes-admin:48082 | `/$2` |
| `/agentN(/\|$)(.*)` | hermes-gateway-N:8642 | `/$2` |
| `/` | hermes-webui:8080 | (none, Prefix) |

**注：** Ingress `rewrite-target: /$2` 会剥离路径前缀。例如 `/admin/api/agents` → 后端收到 `/agents`。因此后端路由不要加 `/admin/api` 前缀。

---

## 镜像清单

| 镜像名 | 构建目录 | Dockerfile | 说明 |
|--------|---------|------------|------|
| `nousresearch/hermes-agent:latest` | 仓库根目录 | `Dockerfile` | Gateway |
| `hermes-admin:latest` | `admin/` | `backend/Dockerfile` | Admin Panel |
| `hermes-orchestrator:latest` | `hermes_orchestrator/` | `Dockerfile` | Orchestrator |
| `redis:7-alpine` | (公共镜像) | - | Redis |
| `oliver006/redis_exporter:latest` | (公共镜像) | - | Redis 监控 |
| `open-webui:nl-v0.9.2-nh` | (预构建镜像) | - | Open WebUI |

### 构建命令

```bash
# Gateway
docker build -t nousresearch/hermes-agent:latest .

# Admin (从 admin/ 目录)
cd admin && docker build -f backend/Dockerfile -t hermes-admin:latest .

# Orchestrator (从仓库根目录)
docker build -f hermes_orchestrator/Dockerfile -t hermes-orchestrator:latest .
```

### 导入镜像到 containerd

```bash
# 184 (开发集群，本地 kubectl)
docker save <image>:latest | sudo ctr -n k8s.io images import -

# 183 (测试集群，SSH 远程)
docker save <image>:latest | ssh root@172.32.153.183 '/opt/containerd/bin/ctr -n k8s.io images import -'
```

**注：** 所有 Deployment 使用 `imagePullPolicy: Never`，必须先导入镜像再 rollout。

---

## Secret 管理

### 必需 Secrets

| Secret 名 | Key(s) | 用途 |
|-----------|--------|------|
| `hermes-admin-secret` | `admin_key` | Admin 面板认证密钥 (32字节 hex) |
| `hermes-admin-internal-secret` | `admin_internal_token` | Admin 内部 API token (Orchestrator/Agent 回调用) |
| `hermes-orchestrator-secret` | `ORCHESTRATOR_API_KEY` | Orchestrator API 认证 |
| `hermes-redis-secret` | `redis-password`, `redis-url` | Redis 密码和连接 URL |
| `hermes-database-secret` | `database-url` | PostgreSQL 连接字符串 (Admin 用) |
| `hermes-db-secret` | `api_key`, `api_key_2`, `api_key_3`, `password`, `username` | PostgreSQL 凭据 + Gateway 默认 API Key |
| `hermes-gateway-N-secret` | `api_key` | 每个 Gateway 的 API Key (创建 Agent 时自动生成) |
| `postgres-secret` | `database-url`, `password` | PostgreSQL StatefulSet 密码 |

### 创建 Secrets

```bash
NS=hermes-agent

# Admin Key
kubectl create secret generic hermes-admin-secret \
  --from-literal=admin_key=$(openssl rand -hex 16) -n $NS

# Admin Internal Token
kubectl create secret generic hermes-admin-internal-secret \
  --from-literal=admin_internal_token=$(openssl rand -hex 32) -n $NS

# Orchestrator API Key
kubectl create secret generic hermes-orchestrator-secret \
  --from-literal=ORCHESTRATOR_API_KEY=$(openssl rand -hex 32) -n $NS

# Redis
REDIS_PASS=$(openssl rand -hex 16)
kubectl create secret generic hermes-redis-secret \
  --from-literal=redis-password=$REDIS_PASS \
  --from-literal=redis-url="redis://:${REDIS_PASS}@hermes-redis:6379/0" -n $NS

# PostgreSQL
PG_PASS=$(openssl rand -hex 16)
kubectl create secret generic postgres-secret \
  --from-literal=password=$PG_PASS \
  --from-literal=database-url="postgresql+asyncpg://postgres:${PG_PASS}@postgres:5432/hermes_admin" -n $NS

kubectl create secret generic hermes-database-secret \
  --from-literal=password=$PG_PASS \
  --from-literal=username=postgres \
  --from-literal=database-url="postgresql+asyncpg://postgres:${PG_PASS}@postgres:5432/hermes_admin" \
  --from-literal=api_key=$(openssl rand -hex 16) \
  --from-literal=api_key_2=$(openssl rand -hex 16) \
  --from-literal=api_key_3=$(openssl rand -hex 16) -n $NS
```

---

## ConfigMaps

| ConfigMap 名 | Key | 用途 | 挂载到 |
|-------------|-----|------|--------|
| `hermes-redis-config` | `redis.conf` | Redis 持久化 + RDB/AOF 配置 | hermes-redis |
| `webui-bridge-page` | `token-login.html` | WebUI 免密跳转桥接页 | hermes-webui: `/app/build/token-login.html` |
| `hermes-swarm-module` | 多个 `.py` | Swarm Python 模块注入 | hermes-gateway-N |
| `postgres-init-script` | `init.sql` | PostgreSQL 初始化 SQL | postgres |
| `admin-startup` | `startup.sh` | Admin 启动脚本 (DB migration 等) | hermes-admin |

**重要：** `webui-bridge-page` ConfigMap 必须挂载到 WebUI Deployment，否则用户无法通过 iframe 免密跳转到 WebUI。挂载路径为 `/app/build/token-login.html`（subPath 方式）。

---

## 环境变量规范

### hermes-admin

| 变量 | 来源 | 说明 | 示例 |
|------|------|------|------|
| `ADMIN_KEY` | secret `hermes-admin-secret/admin_key` | 认证密钥 | |
| `ADMIN_INTERNAL_TOKEN` | secret `hermes-admin-internal-secret/admin_internal_token` | 内部 API token | |
| `K8S_NAMESPACE` | value | K8s 命名空间 | `hermes-agent` |
| `HERMES_DATA_ROOT` | value | Agent 数据根目录 | `/data/hermes` |
| `PYTHONUNBUFFERED` | value | Python 日志不缓冲 | `1` |
| `EXTERNAL_URL_PREFIX` | value | Admin 外部 URL | `http://172.32.153.184:40080` |
| `EXTERNAL_WEBUI_URL` | value | WebUI 外部 URL | `http://172.32.153.184:48080` |
| `EXTERNAL_API_BASE` | value | Gateway 外部 API 基地址 (用于 Direct Connection) | `http://172.32.153.184:40080` |
| `WEBUI_INTERNAL_URL` | value | WebUI 集群内部 URL | `http://hermes-webui:8080` |
| `ORCHESTRATOR_INTERNAL_URL` | value | Orchestrator 内部 URL | `http://hermes-orchestrator:8080` |
| `ORCHESTRATOR_API_KEY` | secret (推荐) | Orchestrator 调用密钥 | |
| `DATABASE_URL` | secret `postgres-secret/database-url` | PostgreSQL 连接串 | |
| `REDIS_PASSWORD` | secret `hermes-redis-secret/redis-password` | Redis 密码 (供 SWARM_REDIS_URL 引用) | |
| `SWARM_REDIS_URL` | value (含 `$(REDIS_PASSWORD)` 引用) | Redis 连接串 | `redis://:$(REDIS_PASSWORD)@hermes-redis:6379/0` |
| `ADMIN_CORS_ORIGINS` | value | CORS 允许来源 | `http://172.32.153.184:40080` |

**外部 URL 按集群不同（必须配置，不可省略）：**
- 184: `EXTERNAL_URL_PREFIX`=`http://172.32.153.184:40080` / `EXTERNAL_WEBUI_URL`=`http://172.32.153.184:48080` / `EXTERNAL_API_BASE`=`http://172.32.153.184:40080`
- 183: `EXTERNAL_URL_PREFIX`=`http://172.32.153.183:32570` / `EXTERNAL_WEBUI_URL`=`http://172.32.153.183:48080` / `EXTERNAL_API_BASE`=`http://172.32.153.183:32570`

**警告：** `EXTERNAL_API_BASE` 无默认值。如果未设置，WebUI Direct Connection 配置会失败。部署新集群时必须显式设置此变量。

### hermes-gateway-N

| 变量 | 来源 | 说明 |
|------|------|------|
| `API_SERVER_ENABLED` | value: `true` | 启用 HTTP API |
| `API_SERVER_HOST` | value: `0.0.0.0` | 监听地址 |
| `API_SERVER_PORT` | value: `8642` | 监听端口 |
| `API_SERVER_KEY` | secret `hermes-gateway-N-secret/api_key` | API 认证密钥 |
| `API_SERVER_CORS_ORIGINS` | value: `*` | CORS |
| `GATEWAY_ALLOW_ALL_USERS` | value: `true` | 允许所有用户 |
| `K8S_NAMESPACE` | value: `hermes-agent` | 命名空间 |
| `K8S_DEPLOYMENT` | value: `hermes-gateway-N` | 自身 Deployment 名 |
| `SWARM_REDIS_URL` | value (含 `$(REDIS_PASSWORD)` 引用) | Redis 连接串 | `redis://:$(REDIS_PASSWORD)@hermes-redis:6379/0` |
| `REDIS_PASSWORD` | secret `hermes-redis-secret/redis-password` | Redis 密码 (供 SWARM_REDIS_URL 引用) | |
| `SANDBOX_POOL_NAME` | value: `hermes-sandbox-pool` | Sandbox 资源池 |
| `SANDBOX_TTL_MINUTES` | value: `30` | Sandbox TTL |
| `SKILL_REPORT_INTERVAL` | value: `300` | 技能上报间隔(秒) |
| `SKILL_REPORT_ADMIN_URL` | value: `http://hermes-admin:48082` | Admin 内部 URL |

### hermes-orchestrator

| 变量 | 来源 | 说明 |
|------|------|------|
| `ORCHESTRATOR_API_KEY` | secret | API 认证密钥 |
| `REDIS_URL` | secret `hermes-redis-secret/redis-url` | Redis 连接 |
| `GATEWAY_API_KEY` | secret `hermes-db-secret/api_key` | 默认 Gateway API Key |
| `K8S_NAMESPACE` | value: `hermes-agent` | 命名空间 |
| `LOG_LEVEL` | value: `INFO` | 日志级别 |
| `ADMIN_INTERNAL_URL` | value: `http://hermes-admin:48082` | Admin 内部 URL |
| `ADMIN_INTERNAL_TOKEN` | secret `hermes-admin-internal-secret/admin_internal_token` | Admin 内部 token |

### hermes-webui

| 变量 | 值 | 说明 |
|------|-----|------|
| `WEBUI_AUTH` | `true` | 启用认证 |
| `PORT` | `48080` | 监听端口 |
| `ENABLE_DIRECT_CONNECTIONS` | `true` | 启用 per-user LLM 配置 |
| `ENABLE_ONBOARDING` | `false` | 禁用新手引导 |
| `WEBUI_SECRET_KEY` | (随机 hex) | JWT 签名密钥 |
| `RAG_EMBEDDING_MODEL` | (空) | 嵌入模型名称 |
| `RAG_RERANKING_MODEL` | (空) | 重排序模型名称 |

**警告：** 不要设置全局 `OPENAI_API_BASE_URL` 或 `OPENAI_API_KEY`。WebUI 使用 per-user Direct Connection，全局配置会导致所有用户共用同一个 agent。

---

## 资源配额

| 组件 | CPU request | CPU limit | Memory request | Memory limit |
|------|-------------|-----------|----------------|--------------|
| hermes-admin | 100m | 500m | 128Mi | 512Mi |
| hermes-gateway-N | 1000m | 1000m (Guaranteed) | 1Gi | 1Gi |
| hermes-orchestrator | 100m | 500m | 128Mi | 256Mi |
| hermes-redis | 100m | 500m | 128Mi | 512Mi |
| redis-exporter | 50m | 100m | 50Mi | 100Mi |
| hermes-webui | 100m | 1000m | 512Mi | 2Gi |
| postgres | - | - | - | 1Gi PVC |

---

## 存储需求

| PVC | 容量 | StorageClass | 挂载点 | 用途 |
|-----|------|-------------|--------|------|
| `hermes-data-pvc` | 50Gi | local-storage | `/data/hermes` | Agent 数据 |
| `hermes-redis-pvc` | 5Gi | local-storage | `/data` | Redis AOF/RDB |
| `pgdata-postgres-0` | 1Gi | local-storage | `/var/lib/postgresql/data` | PostgreSQL 数据 |

**节点目录要求：**
```bash
sudo mkdir -p /data/hermes
sudo chown -R 10000:10000 /data/hermes
```

---

## NetworkPolicies

| Policy | Pod Selector | Ingress 规则 | Egress 规则 |
|--------|-------------|-------------|------------|
| `gateway-isolation` | `app=hermes-gateway` | 允许 all | 允许 all |
| `hermes-orchestrator` | `app=hermes-orchestrator` | 允许 all | 允许 gateway, redis, admin |
| `hermes-redis-netpol` | `app=hermes-redis` | 允许 namespace 内 | 允许 all |
| `sandbox-isolation` | `app=sandbox` | 允许 gateway | 允许 all |

---

## 部署步骤 (新集群)

### 1. 创建命名空间 + 存储

```bash
kubectl apply -f kubernetes/namespace.yaml
kubectl apply -f kubernetes/storage/
```

### 2. 创建 Secrets

按上方 "创建 Secrets" 章节执行。

### 3. 部署 PostgreSQL

```bash
kubectl apply -f kubernetes/postgres/
# 等待 ready
kubectl wait --for=condition=ready pod -l app=postgres -n hermes-agent --timeout=120s
```

### 4. 部署 Redis

```bash
kubectl apply -f kubernetes/redis/  # 或从 ConfigMap 创建
# ConfigMap 内容见 kubernetes/ 目录
```

### 5. 部署 Gateway

```bash
# 根据需要部署 N 个 Gateway 实例
kubectl apply -f kubernetes/gateway/deployment.yaml
kubectl apply -f kubernetes/gateway/service.yaml
kubectl apply -f kubernetes/gateway/rbac.yaml
```

### 6. 部署 WebUI

```bash
kubectl apply -f kubernetes/webui/
# 确保 Service targetPort=48080 匹配容器 PORT
```

### 7. 部署 Orchestrator

```bash
kubectl apply -f kubernetes/orchestrator/
```

### 8. 部署 Admin

```bash
cd admin/kubernetes
./deploy.sh
# 或者手动：
kubectl apply -f rbac.yaml
kubectl apply -f deployment.yaml
kubectl apply -f service.yaml
```

### 9. 配置 Ingress

```bash
kubectl apply -f kubernetes/ingress-nginx/  # Ingress Controller
# Admin + Gateway Ingress 路径已在 deploy.sh 或 manifest 中配置
```

### 10. 集群特定配置

```bash
# 按集群设置外部 URL（无需重建镜像）
kubectl set env deployment/hermes-admin -n hermes-agent \
  EXTERNAL_URL_PREFIX=http://<NODE_IP>:<INGRESS_PORT> \
  EXTERNAL_WEBUI_URL=http://<NODE_IP>:48080 \
  ADMIN_CORS_ORIGINS=http://<NODE_IP>:<INGRESS_PORT>
```

---

## 用户注册/激活/WebUI 流程

```
1. 用户注册 POST /user/register {email, password, name}
   → Admin DB 创建用户 (is_active=false)
   → 同步注册到 WebUI 公开 signup API (非阻塞)

2. 管理员激活 POST /user/{id}/activate {agent_id}
   → 设置 is_active=true, agent_id=N
   → 异步 Provisioning:
     a. 用用户密码登录 WebUI 获取 JWT
     b. 从 K8s Secret 获取 agent API Key
     c. 配置 WebUI Direct Connection (per-user base_url + api_key)
   → 更新 provisioning_status: completed | failed

3. 用户对话 GET /user/webui-url (X-Email-Token)
   → 返回 {url, email, password, provisioning_status}
   → 前端用 iframe 加载 WebUI token-login.html 免密跳转
```

---

## 升级流程

### 镜像更新 (代码变更)

```bash
# 1. 构建
docker build -f <dockerfile> -t <image>:latest <context>

# 2. 导入
docker save <image>:latest | sudo ctr -n k8s.io images import -
# 测试集群:
docker save <image>:latest | ssh root@172.32.153.183 '/opt/containerd/bin/ctr -n k8s.io images import -'

# 3. 重启
kubectl rollout restart deployment/<name> -n hermes-agent
```

### 配置更新 (无代码变更)

```bash
# 修改环境变量 (不需要重建镜像)
kubectl set env deployment/hermes-admin -n hermes-agent KEY=VALUE

# 修改 ConfigMap
kubectl create configmap <name> --from-file=<path> -n hermes-agent --dry-run=client -o yaml | kubectl apply -f -
kubectl rollout restart deployment/<name> -n hermes-agent

# 修改 Secret
kubectl edit secret <name> -n hermes-agent
kubectl rollout restart deployment/<name> -n hermes-agent
```

### Gateway 扩容

通过 Admin 面板创建新 Agent 会自动创建：
1. Deployment `hermes-gateway-N`
2. Service `hermes-gateway-N`
3. Secret `hermes-gateway-N-secret`
4. Ingress path `/agentN`
5. PVC mount (hostPath)

---

## 健康检查

| 组件 | Liveness | Readiness | 端点 |
|------|----------|-----------|------|
| hermes-admin | HTTP :48082 /health | HTTP :48082 /health | `GET /health` |
| hermes-gateway-N | HTTP :8642 /health | HTTP :8642 /health | `GET /health` |
| hermes-orchestrator | HTTP :8080 /health | HTTP :8080 /health | `GET /health` |
| hermes-redis | TCP :6379 | TCP :6379 | (TCP check) |
| hermes-webui | HTTP :48080 /health | HTTP :48080 /health | `GET /health` |

---

## 常见问题

### Ingress rewrite 规则

后端路由 **不要** 加 `/admin/api` 前缀。Ingress `rewrite-target: /$2` 会剥离路径前缀：
- `/admin/api/agents` → 后端收到 `/agents`
- `/agent1/v1/chat/completions` → 后端收到 `/v1/chat/completions`

### Service targetPort 必须匹配容器 PORT

WebUI 容器 `PORT=48080`，Service `targetPort` 必须是 `48080` 而非 `8080`。Service `port` 可以是 `8080`。

### email token 认证

用户登录后获得的 token 需通过 `X-Email-Token` header 传递（非 `Authorization: Bearer`）。Admin key 通过 `X-Admin-Key` header 传递。

### 环境变量修改不需要重建镜像

`WEBUI_INTERNAL_URL`、`EXTERNAL_WEBUI_URL` 等配置变更只需 `kubectl set env` + 自动 rollout，不需要重新构建 Docker 镜像。

### 国内镜像构建

```bash
# pip 国内源 (已在 Dockerfile 中配置)
pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

# npm 国内源
npm config set registry https://registry.npmmirror.com

# GitHub 代理
export http_proxy=http://172.32.147.190:7890
```

---

## 集群配置速查

| 配置项 | 184 (开发) | 183 (测试) |
|--------|-----------|-----------|
| 访问方式 | 本地 kubectl | SSH root@172.32.153.183 |
| ctr 路径 | `/usr/bin/ctr` | `/opt/containerd/bin/ctr` |
| Ingress 端口 | 40080 | 32570 |
| WebUI 端口 | 48080 (NodePort 30480) | 48080 (NodePort) |
| Gateway 数量 | 3 | 13 |
| Admin external URL | `http://172.32.153.184:40080` | `http://172.32.153.183:32570` |
| WebUI external URL | `http://172.32.153.184:48080` | `http://172.32.153.183:48080` |
| Orchestrator | 有 | 有 |
| PostgreSQL | StatefulSet + PVC | StatefulSet + PVC |
| Admin DATABASE_URL | secret `postgres-secret/database-url` | secret `postgres-secret/database-url` |
| Admin REDIS_PASSWORD | secret `hermes-redis-secret/redis-password` | secret `hermes-redis-secret/redis-password` |
| Gateway REDIS_PASSWORD | secret `hermes-redis-secret/redis-password` | secret `hermes-redis-secret/redis-password` |
| Gateway SKILL_REPORT | interval=300, admin=hermes-admin:48082 | interval=300, admin=hermes-admin:48082 |
| WebUI Direct Connection | enabled (no global API URL) | enabled (no global API URL) |
| WebUI SECRET_KEY | (auto-generated) | (auto-generated) |
| Admin volume name | `hermes-data-root` | `hermes-data-root` |
