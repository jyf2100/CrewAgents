# Hermes Admin Panel — 产品需求文档 (PRD)

> **版本**: v1.0
> **日期**: 2026-04-25
> **分支**: feature/opensandbox-lifecycle
> **PR**: jyf2100/CrewAgents#1
> **状态**: Review 完成，待修复后合并

---

## 1. 产品概述

### 1.1 产品定位

Hermes Admin Panel 是 Hermes Agent 的管理控制台，提供对 Kubernetes 集群中 AI Agent 实例的全生命周期管理能力。面向运维人员和 Agent 管理者，通过 Web UI 完成 Agent 的创建、配置、监控、维护和销毁。

### 1.2 核心价值

- **零kubectl操作**：所有 Agent 管理通过 Web UI 完成，无需直接操作 K8s
- **全生命周期管理**：从创建到销毁的完整闭环，包括配置编辑、日志查看、健康检查
- **多实例并行**：支持同时运行多个独立 Agent 实例，各自拥有独立的配置、环境变量和人格
- **微信集成**：Agent 可绑定微信账号，通过扫码完成登录
- **数据持久化**：配置和模板修改在 Pod 重启后保留

### 1.3 系统边界

| 范围内 | 范围外 |
|--------|--------|
| Agent CRUD 操作 | Agent 内部 AI 逻辑 |
| 配置文件管理（.env/config.yaml/SOUL.md） | LLM 模型训练 |
| K8s 资源监控 | 集群基础设施管理 |
| 日志流式查看 | 用户认证系统（使用简单 Admin Key） |
| 微信账号绑定 | 多租户隔离 |
| 备份与恢复 | Agent 间协作/通信 |
| 模板管理 | 计费系统 |

---

## 2. 用户画像

### 2.1 主要用户：Agent 运维管理员

- **角色**：管理一个或多个 Hermes Agent 实例
- **典型场景**：
  - 快速部署新的 Agent 实例（选择 LLM provider、配置 API key）
  - 修改运行中 Agent 的配置并重启
  - 监控 Agent 健康状态和资源使用
  - 绑定微信账号使 Agent 能在微信上对话
  - 排查问题：查看日志、K8s 事件、健康检查
- **技术水平**：熟悉 AI/LLM 概念，不一定熟悉 Kubernetes

### 2.2 次要用户：平台管理员

- **角色**：维护 Admin Panel 本身和底层 K8s 集群
- **典型场景**：
  - 修改 Admin Key
  - 调整默认资源限制
  - 管理模板文件
  - 查看集群节点状态
- **技术水平**：熟悉 Kubernetes 和 DevOps

---

## 3. 功能需求

### 3.1 认证与安全

#### FR-AUTH-01: Admin Key 认证
- 所有 API 端点（除 `/health`）通过 `X-Admin-Key` Header 认证
- Admin Key 为空时为开发模式（允许所有请求，启动时打印警告）
- 使用 `hmac.compare_digest` 进行时序安全比较
- **待修复**：需添加速率限制防止暴力破解

#### FR-AUTH-02: SSE Token 机制
- EventSource 无法设置自定义 Header，使用一次性 Token 替代
- `/agents/{id}/logs/token` 发放 5 分钟有效期的 Token
- `/agents/{id}/logs` 通过 `?token=` 参数认证
- Token 单次使用（pop），过期自动清理
- **待修复**：需添加 Token 数量上限防止内存耗尽

#### FR-AUTH-03: Admin Key 轮换
- `PUT /settings/admin-key` 修改 Admin Key
- 优先写入 K8s Secret，fallback 到文件
- 文件权限 `0o600`，原子写入
- **待修复**：文件存储为明文，应考虑加密或仅依赖 K8s Secret

### 3.2 Agent 管理

#### FR-AGENT-01: Agent 列表
- `GET /agents` 返回所有 Agent 摘要信息
- 每个摘要包含：编号、名称、显示名称、状态、副本数、创建时间、资源使用
- 状态类型：running、stopped、pending、error、unknown
- Dashboard 以卡片网格展示

#### FR-AGENT-02: 创建 Agent
- `POST /agents` 创建新 Agent，4 步向导：
  1. 基本信息（显示名称、LLM provider 选择）
  2. API 密钥配置 + LLM 连接测试
  3. 模型选择与高级配置（终端/浏览器/流式/记忆/会话重置）
  4. 资源限制配置 + 部署确认
- 支持的 LLM Provider：OpenRouter、Anthropic、OpenAI、Gemini、智谱AI、MiniMax、Kimi、Anthropic 兼容、自定义
- 创建过程自动：K8s Secret → Deployment → Service → Ingress → 配置文件
- 支持 Anthropic 兼容模式（`api_mode: anthropic_messages`）
- 显示名称存储在 K8s Deployment annotation `hermes/display-name`
- 创建成功返回 Agent 编号和 API Key

#### FR-AGENT-03: Agent 详情
- `GET /agents/{id}` 返回完整 Agent 信息
- 包含：K8s 资源状态、配置摘要、健康状态、资源使用、Ingress URL
- 5 个 Tab 页：
  - **概览**：基本信息、资源仪表盘、API Key（可显示/隐藏）、测试连接、微信状态
  - **配置**：环境变量编辑器 + config.yaml 原始编辑器
  - **日志**：SSE 实时日志流，支持过滤（All/Error/Warning）
  - **事件**：K8s 事件列表
  - **健康**：Agent 健康检查结果

#### FR-AGENT-04: Agent 操作
- `POST /agents/{id}/restart`：滚动更新重启
- `POST /agents/{id}/stop`：缩容到 0 副本
- `POST /agents/{id}/start`：扩容到 1 副本
- `DELETE /agents/{id}`：删除 Agent（可选自动备份）
- 操作通过 K8s annotation 触发滚动更新

#### FR-AGENT-05: API Key 管理
- `POST /agents/{id}/api-key`：显示完整 API Key
- 响应设置 `Cache-Control: no-store` 防止缓存
- 审计日志记录每次 reveal 操作
- 前端 show/hide 切换按钮
- **待修复**：reveal 后 Key 应设置自动隐藏超时（如 30 秒）

### 3.3 配置管理

#### FR-CONFIG-01: 环境变量
- `GET /agents/{id}/env`：读取 .env 文件（secrets 已脱敏为 `***`）
- `PUT /agents/{id}/env`：写入环境变量列表，可选自动重启
- 支持额外自定义环境变量

#### FR-CONFIG-02: Config YAML
- `GET /agents/{id}/config`：读取 config.yaml
- `PUT /agents/{id}/config`：写入 config.yaml，可选自动重启
- 包含：模型配置、终端/浏览器/流式/记忆开关、api_mode

#### FR-CONFIG-03: SOUL.md
- `GET /agents/{id}/soul`：读取 SOUL.md 人格文件
- `PUT /agents/{id}/soul`：写入 SOUL.md

### 3.4 监控与可观测性

#### FR-MONITOR-01: 资源监控
- `GET /agents/{id}/resources`：CPU/内存使用量
- 数据来源：K8s metrics-server
- Dashboard 卡片和详情页均有展示

#### FR-MONITOR-02: 日志流
- `GET /agents/{id}/logs`：SSE 实时日志流
- 最长连接 300 秒，最大并发 20 个
- 前端支持 All/Error/Warning 过滤和自动重连
- **待修复**：重连逻辑存在竞态条件

#### FR-MONITOR-03: K8s 事件
- `GET /agents/{id}/events`：最近 K8s 事件列表

#### FR-MONITOR-04: 健康检查
- `GET /agents/{id}/health`：代理到 Agent 的 /health 端点

#### FR-MONITOR-05: API 连接测试
- `POST /agents/{id}/test-api`：通过 Ingress URL 调用 OpenAI 兼容的 chat completions 接口测试连通性

### 3.5 微信集成

#### FR-WEIXIN-01: QR 码登录
- `GET /agents/{id}/weixin/qr`：启动微信扫码登录 SSE 流
- 流程：生成 QR → 用户扫码 → 确认登录 → 获取凭证 → 写入 .env → 重启 Agent
- 前端通过 EventSource 接收状态更新并展示 QR 码
- **待修复**：当前使用 raw admin key 作为 query param 认证，应改用 SSE token 模式

#### FR-WEIXIN-02: 连接状态
- `GET /agents/{id}/weixin/status`：读取微信连接状态
- 状态：未绑定 / 已连接（显示昵称、DM ID、群组）

#### FR-WEIXIN-03: 解绑
- `DELETE /agents/{id}/weixin/bind`：清除微信凭证并重启 Agent
- **待修复**：凭证文件权限 0o777/0o666 过于宽松

### 3.6 备份与恢复

#### FR-BACKUP-01: 创建备份
- `POST /agents/{id}/backup`：创建 Agent 数据目录的 tar.gz 备份
- 包含：.env、config.yaml、SOUL.md、会话数据
- 可选包含 K8s 资源清单
- **待修复**：需添加 tarfile 成员过滤防止路径穿越

#### FR-BACKUP-02: 下载备份
- `GET /backups/{filename}`：下载备份文件
- 文件名格式校验：`agentN-YYYYMMDD-HHMMSS.tar.gz`

### 3.7 集群管理

#### FR-CLUSTER-01: 集群状态
- `GET /cluster/status`：返回节点列表、Agent 分布、磁盘使用

#### FR-CLUSTER-02: 资源限制
- `GET /settings`：获取当前默认资源限制（CPU/内存 request 和 limit）
- `PUT /settings`：更新默认资源限制
- 数据持久化到 `/data/hermes/_admin/default_resources.json`

### 3.8 模板管理

#### FR-TEMPLATE-01: 模板查看
- `GET /templates`：查看所有模板（deployment.yaml、.env、config.yaml、SOUL.md）
- `GET /templates/{type}`：查看单个模板

#### FR-TEMPLATE-02: 模板编辑
- `PUT /templates/{type}`：修改模板内容
- 持久化到 `/data/hermes/_admin/templates/`，不影响镜像默认文件
- 双层读取：优先持久化版本，fallback 到镜像默认

### 3.9 LLM 连接测试

#### FR-LLM-01: 测试 API Key
- `POST /test-llm-connection`：使用提供的 API Key 和 Provider 发起最小化 chat completion 请求
- 返回：连接状态、响应时间、错误信息
- **待修复**：需添加速率限制防止被滥用为代理

---

## 4. API 接口清单

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| GET | `/health` | 无 | 健康检查 |
| GET | `/agents` | Header | Agent 列表 |
| POST | `/agents` | Header | 创建 Agent |
| GET | `/agents/{id}` | Header | Agent 详情 |
| DELETE | `/agents/{id}` | Header | 删除 Agent |
| POST | `/agents/{id}/restart` | Header | 重启 |
| POST | `/agents/{id}/stop` | Header | 停止 |
| POST | `/agents/{id}/start` | Header | 启动 |
| GET | `/agents/{id}/config` | Header | 读取 config.yaml |
| PUT | `/agents/{id}/config` | Header | 写入 config.yaml |
| GET | `/agents/{id}/env` | Header | 读取环境变量 |
| PUT | `/agents/{id}/env` | Header | 写入环境变量 |
| GET | `/agents/{id}/soul` | Header | 读取 SOUL.md |
| PUT | `/agents/{id}/soul` | Header | 写入 SOUL.md |
| GET | `/agents/{id}/health` | Header | Agent 健康检查 |
| POST | `/agents/{id}/test-api` | Header | API 连接测试 |
| GET | `/agents/{id}/logs/token` | Header | 获取 SSE Token |
| GET | `/agents/{id}/logs` | Token | SSE 日志流 |
| GET | `/agents/{id}/events` | Header | K8s 事件 |
| POST | `/agents/{id}/api-key` | Header | 显示完整 API Key |
| GET | `/agents/{id}/resources` | Header | 资源使用 |
| POST | `/agents/{id}/backup` | Header | 创建备份 |
| GET | `/agents/{id}/weixin/qr` | Query | 微信 QR 登录 |
| GET | `/agents/{id}/weixin/status` | Header | 微信状态 |
| DELETE | `/agents/{id}/weixin/bind` | Header | 微信解绑 |
| POST | `/agents/{id}/backup` | Header | 创建备份 |
| GET | `/backups/{filename}` | Header | 下载备份 |
| GET | `/cluster/status` | Header | 集群状态 |
| GET | `/templates` | Header | 所有模板 |
| GET | `/templates/{type}` | Header | 单个模板 |
| PUT | `/templates/{type}` | Header | 更新模板 |
| GET | `/settings` | Header | 获取设置 |
| PUT | `/settings` | Header | 更新资源限制 |
| PUT | `/settings/admin-key` | Header | 更新 Admin Key |
| POST | `/test-llm-connection` | Header | LLM 连接测试 |

---

## 5. 前端页面

### 5.1 登录页 (`/login`)
- Admin Key 输入框
- 登录验证后 Key 存入 localStorage
- Key 缓存在 sessionStorage 或内存中（安全改进）

### 5.2 仪表盘 (`/`)
- 集群状态栏：节点数、运行/停止 Agent 数、总 Agent 数、磁盘用量
- Agent 卡片网格：
  - 显示名称（主）+ K8s 名称（副）
  - 状态指示灯 + 资源使用柱状图
  - 快捷操作：重启/停止/启动/测试连接
  - API Key 显示/隐藏切换
  - 剪贴板复制（HTTP fallback）
- 空状态提示
- 10 秒自动刷新

### 5.3 Agent 详情页 (`/agents/:id`)
- 头部：显示名称、状态、操作按钮
- Tab 导航：概览/配置/日志/事件/健康
- 概览 Tab：
  - 基本信息卡片（Provider、Model、创建时间、URL）
  - 资源仪表盘（CPU/内存 request vs usage）
  - API Key 管理（reveal/hide/copy）
  - 微信状态卡片（绑定/解绑/扫码）
  - 连接测试按钮
- 配置 Tab：
  - 环境变量表单编辑器（key-value 对，支持新增/删除）
  - config.yaml 原始编辑器（textarea）
  - 保存时可选择自动重启
- 日志 Tab：
  - SSE 实时日志流
  - 过滤器：All/Error/Warning
  - 自动重连（指数退避）
  - 最大 1500 行缓冲
- 事件 Tab：K8s 事件时间线
- 健康 Tab：Agent 健康检查结果

### 5.4 创建 Agent 向导 (`/agents/new`)
- Step 1：基本信息（显示名称、LLM Provider 选择）
- Step 2：API 密钥 + 连接测试
- Step 3：模型选择 + 高级配置开关
- Step 4：资源限制 + 部署
- 部署过程显示 10 步进度条
- 创建成功显示 Agent 编号和 API Key

### 5.5 设置页 (`/settings`)
- 集群状态表格（节点名、状态、Agent 数、角色、K8s 版本）
- Admin Key 管理（显示脱敏 Key、更新）
- 默认资源限制编辑器（CPU/内存 request 和 limit）
- 模板编辑器（4 个子 Tab：deployment/env/config/soul）

### 5.6 设计规范
- **主题**：霓虹赛博朋克风格
- **色调**：深色背景 + 青色/品红色/绿色高亮
- **字体**：等宽字体为主
- **响应式**：支持桌面和平板
- **国际化**：中文/英文双语

---

## 6. 技术架构

### 6.1 后端
- **框架**：FastAPI (Python 3.12)
- **K8s 客户端**：kubernetes Python client
- **数据存储**：
  - Agent 数据：`/data/hermes/agentN/` (hostPath volume)
  - 管理数据：`/data/hermes/_admin/` (持久化配置、模板)
  - K8s 资源：Deployment、Service、Ingress、Secret、RBAC
- **认证**：HMAC-safe Admin Key 比对
- **SSE**：日志流、微信 QR 流

### 6.2 前端
- **框架**：React 19 + React Router v7
- **构建**：Vite 7
- **样式**：Tailwind CSS 4
- **状态**：React useState/useEffect（无全局状态管理库）
- **HTTP**：Fetch API + 自封装 AdminApiClient

### 6.3 部署
- **Docker**：多阶段构建（Node.js 构建前端 + Python 运行时）
- **K8s**：Deployment + Service + Ingress + RBAC
- **存储**：hostPath volume (单节点) + 本地 PV
- **镜像**：`hermes-admin:latest`，`imagePullPolicy: Never`

---

## 7. 非功能性需求

### 7.1 性能
- Agent 列表加载 < 3 秒（100 个 Agent 以内）
- SSE 日志延迟 < 500ms
- 配置写入到 Agent 重启完成 < 60 秒
- **已知问题**：N+1 K8s API 调用导致大规模时延迟高

### 7.2 可靠性
- 配置写入使用原子替换（`os.replace`），避免部分写入
- SSE 连接最大 300 秒自动断开
- SSE Token 过期自动清理
- 备份删除前自动备份

### 7.3 安全（含审查发现）
- [x] HMAC-safe Admin Key 比较
- [x] SSE Token 单次使用
- [x] API Key 响应 Cache-Control: no-store
- [x] 启动时 ADMIN_KEY 为空警告
- [ ] **待修复**：速率限制（防暴力破解）
- [ ] **待修复**：CORS 限制到部署 origin
- [ ] **待修复**：微信 QR 改用 SSE token 认证
- [ ] **待修复**：文件权限收紧
- [ ] **待修复**：tarfile 成员过滤
- [ ] **待修复**：K8s 异常消息脱敏
- [ ] **待修复**：审计日志覆盖所有破坏性操作
- [ ] **待修复**：安全响应头

### 7.4 可维护性
- 前后端代码分离
- API 接口 OpenAPI 自动生成（已禁用，可按需开启）
- 双语 i18n
- E2E 测试基础设施（Playwright + Mock API）

---

## 8. 数据模型

### 8.1 K8s 资源映射

```
Agent N ↔ K8s Deployment: hermes-gateway[-N]
        ↔ K8s Service:    hermes-gateway[-N]
        ↔ K8s Secret:     hermes-agent[-N]-secret (API Key)
        ↔ K8s Ingress:    /agentN → hermes-gateway[-N]:8642
        ↔ hostPath:       /data/hermes/agentN/
```

### 8.2 Agent 目录结构

```
/data/hermes/
├── _admin/                    # Admin Panel 持久化数据
│   ├── admin_key              # Admin Key fallback 存储
│   ├── default_resources.json # 默认资源限制
│   └── templates/             # 自定义模板覆盖
│       ├── deployment.yaml
│       ├── .env.template
│       ├── config.yaml.template
│       └── SOUL.md.template
├── _backups/                  # 备份文件
├── agent1/                    # Agent 1 数据
│   ├── .env                   # 环境变量（含 API Key）
│   ├── config.yaml            # Agent 配置
│   ├── SOUL.md                # Agent 人格
│   └── weixin/                # 微信凭证
│       └── accounts/          # 微信账号数据
├── agent2/                    # Agent 2 数据
└── ...
```

---

## 9. 审查问题追踪

### 9.1 CRITICAL（合并前必须修复）

| ID | 问题 | 修复方案 |
|----|------|----------|
| C1 | 无速率限制 | 引入 slowapi，敏感端点（admin-key、test-llm）限制频率 |
| C2 | Admin key 暴露在 URL | 微信 QR 改用 SSE token 模式（复用 logs/token 机制） |
| C3 | 凭证文件权限过宽 | 改为 0o750 (dir) / 0o640 (file) |
| C4 | CORS 全开放 | 限制到 ADMIN_ORIGIN 环境变量 |
| C5 | tarfile 路径穿越 | 添加成员名过滤函数 |

### 9.2 HIGH（合并后尽快修复）

| ID | 问题 | 修复方案 |
|----|------|----------|
| H1 | SSE token 无上限 | 添加 MAX_SSE_TOKENS=1000 上限 |
| H2 | Restart 失败静默 | 返回明确消息 "Config updated but restart failed" |
| H3 | N+1 API 调用 | 批量获取 namespace 级 metrics |
| H4 | K8s 异常泄露 | 脱敏后返回通用错误消息 |
| H5 | 微信 SSRF | redirect_host 白名单校验 |
| H6 | 前端 JSON.parse 崩溃 | WeChatQRModal 加 try/catch |
| H7 | 前端 any 类型 | 添加 Translations index signature |
| H8 | 日志重连竞态 | 重构 connect/cleanup 为 useRef 管理 |
| H9 | 异步锁事件循环 | 延迟创建 asyncio.Lock |
| H10 | agent_id 未校验 | ConfigManager 添加范围检查 |

### 9.3 MEDIUM（后续迭代）

- 审计日志覆盖所有破坏性操作
- 提取共享 hooks（useRevealKey、useTestApi、copyToClipboard）
- Modal 焦点陷阱和 ARIA 属性
- 弃用 API 迁移到 lifespan
- 安全响应头中间件
- 动态列表 key 优化

---

## 10. 后续路线图

### Phase 1: 安全加固（当前 PR 合并前）
- 修复全部 CRITICAL 和关键 HIGH 问题
- 添加速率限制
- 收紧 CORS 和文件权限

### Phase 2: 多 Agent 协作（蜂群演进）
- Supervisor Agent 调度层
- Agent Registry（能力标签注册与发现）
- 消息总线（Redis Pub/Sub / NATS）
- 共享记忆层
- 工具市场（跨 Agent 工具共享）

### Phase 3: 企业级特性
- 多租户隔离
- RBAC 角色权限（Admin/Operator/Viewer）
- 审计日志持久化
- 告警规则和通知
- Agent 编排画布（可视化工作流）
