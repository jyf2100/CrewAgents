# 用户管理入口设计文档

> 日期: 2026-04-29
> 状态: 已审核，待实现
> 审核: 安全 + 架构双审核通过（v2 含审核修订）

## 背景

当前 Admin Panel 是单密钥全权限模式：一个 `ADMIN_KEY` 管理所有 agent。用户（agent 的实际使用者）无法自行查看配置、日志或管理自己的 agent，每次都需要找管理员操作。

本设计在现有 Admin Panel 上增加用户登录入口，用户用自己 agent 的 `API_SERVER_KEY` 登录后可自主管理自己的 agent。

## 需求

- 用户用 agent 的 `API_SERVER_KEY` 登录 Admin Panel
- 登录后只能看到和管理自己的那一个 agent
- 复用现有 Admin Panel 前端和组件
- 功能范围：配置编辑、日志查看、终端、健康检查、重启/停止/启动（和管理员一样的操作，但只针对自己的 agent）
- 登录页默认用户模式，可切换到管理员模式

## 认证与会话管理

### 会话机制：内存 Token Store（非 JWT）

> **审核修订**：原设计使用 JWT，审核后改为内存 token store，理由：
> - 与代码库现有模式一致（SSE token、terminal token 都是内存 dict + TTL）
> - 单实例部署无需 stateless token
> - 天然支持吊销（删 dict entry 即可）
> - 无需新增 PyJWT 依赖
> - Pod 重启自动清除所有 session（可接受）

```python
_user_tokens: dict[str, tuple[int, str, float]] = {}
# token -> (agent_id, api_key_hash, expires_at)
USER_TOKEN_TTL = 7200  # 2 小时
```

### 登录流程

```
用户输入 API_SERVER_KEY
  → POST /user/login
  → 查内存缓存 key_hash → agent_id 映射（无则从 K8s Secret 刷新）
  → hmac.compare_digest 匹配 api_key 字段
  → 匹配成功 → 签发随机 token（secrets.token_urlsafe(32)）
  → 存入 _user_tokens: {token: (agent_id, api_key_sha256_prefix, expires_at)}
  → 返回 {token, agent_id, display_name}
```

### 登录 Rate Limiting

> **审核要求（CRITICAL-1）**：必须防止暴力猜 API key。

- 每 IP 限制：5 次/分钟，20 次/小时
- 实现方式：内存固定窗口计数器（`dict[ip, (count, window_start)]`）
- 超限返回 429 + 递增 backoff 提示
- 记录所有登录尝试日志（时间、IP、成功/失败、匹配的 agent_id）

### API Key 缓存

> **审核修订**：避免每次登录都调 K8s API。

```python
_key_cache: dict[str, int] = {}        # sha256(api_key) -> agent_id (完整 hash)
_key_cache_at: float = 0
KEY_CACHE_TTL = 60  # 60 秒刷新

async def _refresh_key_cache(self):
    """从 K8s Secret 刷新 api_key → agent_id 映射"""
    if time.time() - _key_cache_at < KEY_CACHE_TTL:
        return
    secrets = await self.list_agent_secrets()  # label selector: app=hermes-gateway
    _key_cache.clear()
    for secret in secrets:
        api_key = decode_secret_field(secret, "api_key")
        agent_id = extract_agent_id(secret.metadata.name)
        _key_cache[sha256(api_key.encode()).hexdigest()] = agent_id
    _key_cache_at = time.time()
```

### 双模式认证

| 模式 | Header | 权限 |
|------|--------|------|
| 管理员 | `X-Admin-Key` | 所有 agent，全部功能 |
| 用户 | `X-User-Token` | 只有 token 绑定的 agent_id，无创建/删除/Settings |

> **审核修订**：用自定义 header `X-User-Token` 而非 `Authorization: Bearer`，避免和 API server 的 Bearer token 混淆。

后端通过 `get_current_user` dependency 自动识别两种认证方式：
- 请求带 `X-Admin-Key` → 管理员模式，不限制 agent_id
- 请求带 `X-User-Token` → 用户模式，查 `_user_tokens` 取 `agent_id`
- 现有 agent 操作端点检查 `request.state.agent_id`，如果存在则强制只允许访问该 agent

### 集中 Auth 模块

> **审核要求**：当前 auth 逻辑在三个文件中重复（main.py、terminal.py、swarm_routes.py），必须先抽取再扩展。

新建 `admin/backend/auth.py`：
```python
# 统一的双模式 auth dependency
async def get_current_user(
    x_admin_key: str = Header(default="", alias="X-Admin-Key"),
    x_user_token: str = Header(default="", alias="X-User-Token"),
    request: Request = None,
) -> AuthContext:
    """返回 AuthContext(is_admin=True/False, agent_id=None|int)"""
```

三个 router 统一 import `from auth import auth` 替代各自的 `_verify_admin_key`。

### Token 吊销

- 用户登出：`POST /user/logout` → 从 `_user_tokens` 删除
- 管理员强制吊销：`DELETE /user/sessions/{agent_id}` → 清除该 agent 的所有 token
- 定时清理：复用 startup event 的 sweep task，每分钟清除过期 token

### Agent 重建保护

> **审核要求（HIGH-4）**：防止 agent 删重建后旧 token 仍有效。

token 存储中包含 `api_key_hash`（完整 SHA-256）。每次请求验证时，从 `_key_cache` 读取当前 api_key hash 并比对（60s TTL 缓存，不做实时 K8s 调用）。如果 agent 被删重建（新 api_key），最多 60s 后旧 token 自动失效。旧 agent_id 对应的 pod 已不存在，即使 60s 内旧 token 通过了 hash 校验，实际操作也会因 pod 不存在而失败。

## 后端 API 变更

### 新增端点

| Method | Path | 描述 | 认证 | Rate Limit |
|--------|------|------|------|------------|
| POST | `/user/login` | 用户登录 | 无 | 5/min/IP |
| POST | `/user/logout` | 用户登出 | User Token | 无 |
| GET | `/user/me` | 当前用户信息 | User Token | 无 |

### 修改的端点

所有现有 agent 操作端点（`/agents/{agent_id}/...`）的 auth dependency 改为 `from auth import auth`：
- 管理员：路径中 `{agent_id}` 可以是任意值
- 用户：忽略路径中 `{agent_id}`，强制使用 token 绑定的 `agent_id`

**特别注意**：Terminal token 端点和 SSE log token 端点也必须强制使用 token 绑定的 agent_id，忽略 URL 参数中的 agent_id。具体实现模式：

```python
# auth.py 中的通用 agent_id 覆盖逻辑
def get_effective_agent_id(request: Request, url_agent_id: int) -> int:
    """用户模式强制使用 session agent_id，管理员模式使用 URL 参数"""
    override = getattr(request.state, "agent_id", None)
    return override if override is not None else url_agent_id

# terminal.py 和 main.py 的 token 端点中使用
@router.get("/agents/{agent_id}/terminal/token")
async def get_terminal_token(request: Request, agent_id: int, _=Depends(auth)):
    effective_id = get_effective_agent_id(request, agent_id)
    # 用 effective_id 生成 token，不用 url 的 agent_id
    ...
```

同样适用于 SSE log token 端点（`main.py` 的 `get_logs_token`）和所有 WebSocket 端点。

### 新增方法

`k8s_client.py`:
```python
async def list_agent_secrets(self) -> list:
    """列出所有 hermes-gateway*-secret（用 label selector）"""

async def find_agent_by_api_key(self, api_key: str) -> int | None:
    """查缓存/遍历 secret，匹配 api_key，返回 agent_id"""
```

### SPA Middleware 更新

`main.py` 的 `_SpaFallbackMiddleware.API_ONLY_PREFIXES` 添加 `/user`，确保 API 请求不被 SPA fallback 拦截。

## 登录页设计

默认用户模式，Tab 切换到管理员模式。

```
┌─────────────────────────────────────┐
│         Hermes Agent Manager        │
│                                     │
│     [ 用户登录 ]  [ 管理员登录 ]      │
│  ─────────────────────────────────  │
│                                     │
│  API Key                            │
│  [________________________] 👁       │
│                                     │
│           [ 登 录 ]                  │
│                                     │
│  ─────────────────────────────────  │
│  使用你 agent 的 API Key 登录         │
│  管理你自己的 Agent                   │
└─────────────────────────────────────┘
```

切换到管理员 tab 时：
- 输入框 label 变成「Admin Key」
- 底部提示消失
- 其余不变，共用同一个输入框和登录按钮

## 前端路由与页面

### 路由

> **审核修订**：去掉独立 `/user/` 路由。用户登录后直接跳到 `/agents/{agent_id}`，用 localStorage mode flag 控制显示。

| 路径 | 描述 | 模式 |
|------|------|------|
| `/admin/` | 管理面板主页 | 管理员 |
| `/admin/agents/:id` | Agent 详情 | 管理员/用户共用 |

用户登录后跳转到 `/admin/agents/{token_agent_id}`，`AgentDetailPage` 从 localStorage 读取 mode：
- `mode === "user"` → 隐藏创建/删除按钮，固定 agent_id 不可切换
- `mode === "admin"` → 正常行为

### 功能权限对比

| 功能 | 管理员 | 用户 |
|------|--------|------|
| Agent 列表页 | 所有 agent | 跳过，直接进详情 |
| Agent 详情页 | 可切换任意 agent | 只看自己的，不可切换 |
| Config/Env/Soul 编辑 | 可编辑 | 可编辑 |
| Logs/Terminal/Health | 可用 | 可用 |
| Restart/Stop/Start | 可用 | 可用 |
| 创建 Agent | 可用 | 不可见 |
| 删除 Agent | 可用 | 不可见 |
| Settings/Templates | 可用 | 不可见 |
| Cluster Status | 可用 | 不可见 |
| Swarm | 可用 | 不可见 |

### 前端状态

`localStorage` 存储:
```typescript
{
  admin_api_key?: string,  // 管理员 key（现有）
  user_token?: string,     // 用户 token
  user_agent_id?: number,  // 用户 agent id
  mode: "admin" | "user",  // 当前模式
}
```

`adminFetch` 根据模式自动带不同 header:
- 管理员: `X-Admin-Key: <key>`
- 用户: `X-User-Token: <token>`

### Header 导航

- 管理员: 现有侧边栏 + Dashboard/Settings/Swarm 全部导航
- 用户: 只显示 agent display name + 登出按钮，隐藏侧边栏

## 要修改的文件

### 后端

| 文件 | 变更 |
|------|------|
| `admin/backend/auth.py` | **新建**：集中双模式 auth dependency + rate limiting + token store |
| `admin/backend/main.py` | 导入 `auth.py` 替代内联 auth；新增 `/user/login`、`/user/logout`、`/user/me`；SPA middleware 添加 `/user` |
| `admin/backend/k8s_client.py` | 新增 `list_agent_secrets`、`find_agent_by_api_key` 方法 |
| `admin/backend/terminal.py` | 导入 `auth.py` 替代内联 `_verify_admin_key` |
| `admin/backend/swarm_routes.py` | 导入 `auth.py` 替代内联 `_verify_swarm_admin_key` |

### 前端

| 文件 | 变更 |
|------|------|
| `src/pages/LoginPage.tsx` | Tab 切换：用户/管理员；用户登录调用 `/user/login` |
| `src/lib/admin-api.ts` | 新增 `userLogin`、`userLogout`、`getUserMe`；`adminFetch` 双模式 header |
| `src/App.tsx` | 用户登录后重定向到 `/agents/{id}` |
| `src/pages/AgentDetailPage.tsx` | 读取 mode，隐藏管理员专属按钮（创建/删除），固定 agent_id |
| `src/components/Header.tsx` | 用户模式简化导航，隐藏侧边栏 |
| `src/i18n/en.ts` + `zh.ts` | 翻译 key |

### 依赖

无新增依赖。使用 Python 标准库 `secrets`、`hashlib`、`hmac`（和现有 token store 模式一致）。

## 登出

- 前端调用 `POST /user/logout` → 后端从 `_user_tokens` 删除
- 前端清除 localStorage 中 `user_token`、`user_agent_id`、`mode`
- 跳转回登录页

## 安全考虑

- API key 匹配使用 `hmac.compare_digest`（timing-safe）
- Token 是随机 32 字节（`secrets.token_urlsafe(32)`），服务端持有
- 用户模式后端强制限制 agent_id，无法通过修改路径访问其他 agent
- 登录端点强制 rate limiting（5/min/IP）
- Agent 重建后旧 token 自动失效（api_key hash 不匹配）
- CORS 收紧：生产环境 SPA 和 API 同源（都从 FastAPI 48082 端口提供），可移除 CORS 中间件或设为空列表；开发环境保留 `["http://localhost:5173"]` 供 Vite proxy 使用
- 登录日志记录所有尝试（时间、IP、成功/失败）

## 审核变更记录

| 原设计 | 审核修订 | 理由 |
|--------|----------|------|
| JWT (PyJWT) | 内存 token store | 与代码库模式一致；支持吊销；无新依赖 |
| `Authorization: Bearer` | `X-User-Token` header | 避免和 agent API server 的 Bearer 混淆 |
| 24h 过期 | 2h 过期 | 减少被盗 token 的攻击窗口 |
| 无 rate limiting | 5/min/IP 强制限制 | 防止暴力猜 API key（CRITICAL） |
| 无吊销 | 内存删除即吊销 | 支持主动登出和管理员强制清除 |
| 独立 `/user/` 路由 | 复用 `/agents/:id` | 零新增路由，简化实现 |
| 三个文件各自 auth | 集中 `auth.py` | 消除重复，防止 drift |
| 无 agent 重建保护 | api_key hash 校验 | 防止旧 token 绑定到新 agent |
| CORS 全开 | 生产环境移除/收紧，dev 保留 localhost | SPA 和 API 同源无需 CORS |
| Rate limiter "滑动窗口" | 改为"固定窗口" | 数据结构是固定窗口，避免误导 |
| Key cache 用 truncated hash | 改为完整 SHA-256 | 避免 prefix 碰撞风险 |
| Terminal/SSE agent_id 覆盖 | 给出 `get_effective_agent_id` 代码模式 | 二次审核发现描述不够具体，开发者容易遗漏 |
