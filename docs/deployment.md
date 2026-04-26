# Hermes Agent 部署指南

## 架构概览

```
用户 (Telegram/Discord/Slack/WhatsApp/CLI/...)
  → Gateway (gateway/run.py) — 异步平台适配器，监听 8642
    → AIAgent (run_agent.py) — 同步 Agent 循环，LLM API 调用
      → Tool Registry (tools/registry.py) — 自注册工具系统

Admin Panel (admin/) — FastAPI + React，管理 K8s Agent 实例
  → 监听 48082，通过 K8s API 管理 Deployment

Open WebUI — 可选的 Web 聊天界面，监听 48080
  → 通过 OpenAI 兼容 API 连接 Gateway
```

## 前置条件

| 组件 | 版本要求 | 用途 |
|------|---------|------|
| Docker | 20.10+ | 构建和运行容器镜像 |
| Python | 3.11+ | 本地开发 |
| kubectl | 1.28+ | K8s 部署（生产环境） |
| K8s 集群 | 1.28+ | 生产环境 |
| uv | latest | Python 包管理（本地开发） |

---

## 方式一：Docker Compose（开发/单机）

### 1. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`，填入：

```env
# 必填：LLM 提供商配置
OPENAI_API_KEY=sk-xxx
# 或其他提供商：
# ANTHROPIC_API_KEY=sk-ant-xxx
# OPENROUTER_API_KEY=sk-or-xxx

# 可选：代理
# HTTP_PROXY=http://proxy:port
# HTTPS_PROXY=http://proxy:port
```

### 2. 启动服务

```bash
docker-compose up -d
```

这会启动三个服务：

| 服务 | 端口 | 说明 |
|------|------|------|
| `hermes` | 8642 | Agent Gateway（API + 消息适配） |
| `webui` | 3001 | Open WebUI 聊天界面 |
| `setup` | 3080/8643 | 初始配置向导（可移除） |

### 3. 验证

```bash
# 检查 Gateway
curl http://localhost:8642/health

# 检查 WebUI
curl http://localhost:3001
```

---

## 方式二：Kubernetes（生产/多实例）

### 1. 构建镜像

#### Gateway 镜像

```bash
# 从仓库根目录构建
docker build -t nousresearch/hermes-agent:latest .

# 如果需要推送到私有仓库
docker tag nousresearch/hermes-agent:latest registry.cn-hangzhou.aliyuncs.com/hermes-ops/hermes-agent:latest
docker push registry.cn-hangzhou.aliyuncs.com/hermes-ops/hermes-agent:latest
```

**镜像包含：**
- Python 3.11 venv + 全部依赖（`.[all]`）
- Node.js + npm（whatsapp-bridge）
- Playwright Chromium（浏览器工具）
- ASCII 艺术工具：cowsay, boxes, toilet, jp2a, pyfiglet
- 图像处理：Pillow, scipy
- 运行用户：`hermes`（UID 10000），通过 gosu 降权

#### Admin 面板镜像

```bash
cd admin
docker build -f backend/Dockerfile -t hermes-admin:latest .

# 推送到私有仓库
docker tag hermes-admin:latest registry.cn-hangzhou.aliyuncs.com/hermes-ops/hermes-admin:latest
docker push registry.cn-hangzhou.aliyuncs.com/hermes-ops/hermes-admin:latest
```

### 2. 导入镜像到 containerd（如果使用 imagePullPolicy: Never）

```bash
docker save nousresearch/hermes-agent:latest | sudo ctr -n k8s.io images import -
docker save hermes-admin:latest | sudo ctr -n k8s.io images import -
```

### 3. 创建命名空间和 Secret

```bash
# 创建命名空间
kubectl apply -f kubernetes/namespace.yaml

# 配置数据库密钥（修改密码！）
kubectl apply -f kubernetes/postgres/secret.yaml
# 编辑 secret 中的 password 字段：
kubectl edit secret hermes-db-secret -n hermes-agent

# 配置 Gateway API Key
kubectl create secret generic hermes-db-secret \
  --from-literal=api_key=$(openssl rand -hex 32) \
  --from-literal=api_key_2=$(openssl rand -hex 32) \
  --from-literal=api_key_3=$(openssl rand -hex 32) \
  -n hermes-agent --dry-run=client -o yaml | kubectl apply -f -
```

### 4. 部署基础设施

```bash
# 本地存储（需要节点路径 /data/hermes 存在）
kubectl apply -f kubernetes/storage/

# PostgreSQL
kubectl apply -f kubernetes/postgres/

# Ingress Controller（如果集群没有）
kubectl apply -f kubernetes/ingress-nginx/
```

### 5. 部署 Gateway

```bash
# 确保节点上有数据目录
sudo mkdir -p /data/hermes/agent1 /data/hermes/agent2 /data/hermes/agent3
sudo chown -R 10000:10000 /data/hermes

# 部署 3 个 Gateway 实例
kubectl apply -f kubernetes/gateway/deployment.yaml
kubectl apply -f kubernetes/gateway/service.yaml
kubectl apply -f kubernetes/gateway/rbac.yaml
kubectl apply -f kubernetes/gateway/pdb.yaml
kubectl apply -f kubernetes/gateway/ingress.yaml

kubectl apply -f kubernetes/gateway2/deployment.yaml
kubectl apply -f kubernetes/gateway3/deployment.yaml
```

### 6. 部署 Sandbox Pool（可选）

```bash
# 需要 OpenSandbox CRD 已安装
kubectl apply -f kubernetes/sandbox/
```

### 7. 部署 WebUI（可选）

```bash
kubectl apply -f kubernetes/webui/
```

### 8. 部署 Admin 面板

```bash
cd admin/kubernetes
./deploy.sh
```

`deploy.sh` 会自动：
1. 生成 32 字节 hex admin key
2. 创建 Secret
3. 应用 RBAC
4. 应用 Deployment 和 Service
5. Patch Ingress 添加 `/admin` 路径
6. 等待 rollout 完成

**重要：保存输出的 Admin Key！**

### 9. 验证部署

```bash
# 检查所有 Pod 状态
kubectl get pods -n hermes-agent

# 检查 Gateway
kubectl logs -f deployment/hermes-gateway -n hermes-agent

# 检查 Admin
kubectl logs -f deployment/hermes-admin -n hermes-agent

# 测试 Gateway API
curl http://<节点IP>:40080/agent1/health

# 测试 Admin API
curl -H "X-Admin-Key: <your-admin-key>" http://<节点IP>:40080/admin/api/agents
```

---

## 端口映射

| 端口 | 服务 | 访问方式 |
|------|------|---------|
| 8642 | Gateway API | ClusterIP / Ingress |
| 48082 | Admin Panel | ClusterIP / Ingress `/admin` |
| 48080 | Open WebUI | hostNetwork |
| 40080 | Ingress HTTP | hostNetwork |
| 40443 | Ingress HTTPS | hostNetwork |
| 5432 | PostgreSQL | ClusterIP only |

### Ingress 路径映射

| 路径 | 后端服务 |
|------|---------|
| `/agent1(/|$)(.*)` | hermes-gateway:8642 |
| `/agent2(/|$)(.*)` | hermes-gateway-2:8642 |
| `/agent3(/|$)(.*)` | hermes-gateway-3:8642 |
| `/admin(/|$)(.*)` | hermes-admin:48082 |

---

## 配置说明

### LLM Provider 映射

创建 Agent 时选择 Provider，系统自动映射 API 模式和环境变量：

| Provider | API 模式 | 环境变量 | 默认 URL |
|----------|---------|---------|---------|
| `openrouter` | chat_completions | `OPENROUTER_API_KEY` | `https://openrouter.ai/api/v1` |
| `openai` | chat_completions | `OPENAI_API_KEY` | `https://api.openai.com/v1` |
| `anthropic` | anthropic_messages | `ANTHROPIC_API_KEY` | `https://api.anthropic.com/v1` |
| `gemini` | chat_completions | `GEMINI_API_KEY` | `https://generativelanguage.googleapis.com/v1beta` |
| `zhipuai` | chat_completions | `GLM_API_KEY` | `https://open.bigmodel.cn/api/paas/v4` |
| `minimax` | anthropic_messages | `OPENAI_API_KEY` | `https://api.minimaxi.com/anthropic/v1` |
| `kimi` | chat_completions | `MOONSHOT_API_KEY` | `https://api.moonshot.cn/v1` |
| `anthropic-compat` | anthropic_messages | `OPENAI_API_KEY` | 需手动填写 |
| `custom` | chat_completions | `OPENAI_API_KEY` | 需手动填写 |

**注意：** `minimax` 和 `anthropic-compat` 使用 Anthropic Messages 协议，但通过 `OPENAI_API_KEY` 环境变量传递密钥。Agent 内部 provider 会被解析为 `custom`。

### Gateway 环境变量

| 变量 | 说明 | 默认值 |
|------|------|-------|
| `API_SERVER_ENABLED` | 启用 HTTP API | `false` |
| `API_SERVER_HOST` | 监听地址 | `127.0.0.1` |
| `API_SERVER_PORT` | 监听端口 | `8642` |
| `API_SERVER_KEY` | API 认证密钥 | 空（无认证） |
| `GATEWAY_ALLOW_ALL_USERS` | 允许所有用户 | `false` |
| `K8S_NAMESPACE` | K8s 命名空间 | `hermes-agent` |
| `HERMES_HOME` | 数据目录 | `/opt/data` |

### Admin 环境变量

| 变量 | 说明 | 默认值 |
|------|------|-------|
| `ADMIN_KEY` | 认证密钥（空=无认证） | 空 |
| `K8S_NAMESPACE` | K8s 命名空间 | `hermes-agent` |
| `HERMES_DATA_ROOT` | Agent 数据根目录 | `/data/hermes` |

---

## 升级

### Gateway 升级

```bash
# 构建新镜像
docker build -t nousresearch/hermes-agent:latest .
docker save nousresearch/hermes-agent:latest | sudo ctr -n k8s.io images import -

# 滚动更新
kubectl rollout restart deployment/hermes-gateway -n hermes-agent
kubectl rollout restart deployment/hermes-gateway-2 -n hermes-agent
kubectl rollout restart deployment/hermes-gateway-3 -n hermes-agent
```

### Admin 升级

```bash
cd admin

# 方式一：本地构建
docker build -f backend/Dockerfile -t hermes-admin:latest .
docker save hermes-admin:latest | sudo ctr -n k8s.io images import -
kubectl rollout restart deployment/hermes-admin -n hermes-agent

# 方式二：推送到仓库（推荐）
TAG=v1.2.3 ./kubernetes/upgrade.sh
```

---

## 常见问题

### Docker 构建失败

**npm install 报 git SSH 错误：**
```
fatal: Could not read from remote repository
```
原因：whatsapp-bridge 依赖 `whiskeysockets/libsignal-node` 使用 SSH URL。
Dockerfile 中已自动将 SSH URL 替换为 HTTPS，确保构建时不跳过该步骤。

**Playwright 下载超时：**
```bash
# 设置代理
HTTPS_PROXY=http://proxy:port docker build .
```

**构建后 Pod 崩溃 "hermes: no such user"：**
确保 Dockerfile 中有 `useradd` 和 `COPY --from=gosu_source` 步骤。

### K8s 部署问题

**Pod CrashLoopBackOff ".venv/bin/activate not found"：**
Dockerfile 必须使用 `uv venv`（不带 `--system`），因为 entrypoint 依赖 `.venv/bin/activate`。

**Admin RBAC 权限不足：**
Admin 需要两个 Role：
- Role `hermes-admin`：deployments/services/secrets/configmaps/ingresses 的 CRUD
- ClusterRole `hermes-admin`：nodes/pods 的 get/list + metrics.k8s.io 权限

**Ingress 404：**
检查 ingress controller 是否运行：`kubectl get pods -n ingress-nginx` 或查看 `kubernetes/ingress-nginx/daemonset.yaml`。

**Gateway 无法连接 PostgreSQL：**
确保 `hermes-db-secret` 存在且密码正确。PostgreSQL 使用 StatefulSet，数据持久化在 hostPath `/data/hermes-postgres`。

### Provider 配置问题

**Agent 使用错误的 API 格式：**
检查 `PROVIDER_API_MODE_MAP` → `PROVIDER_AGENT_MAP` → `PROVIDER_KEY_MAP` 三个映射链是否一致。

**Anthropic SDK 重复 `/v1`：**
Anthropic SDK 会自动追加 `/v1/messages`。如果 base_url 以 `/v1` 结尾会被自动去除。Admin 的 `strip_v1_suffix()` 处理了这个情况。
