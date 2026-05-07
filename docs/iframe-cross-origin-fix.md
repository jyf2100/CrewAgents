# iframe 内嵌 WebUI 模型加载失败 — 修复方案

> 记录日期：2026-05-07
> 环境：184 开发集群，hermes-admin + hermes-webui，Nginx Ingress
> 审核日期：2026-05-07（安全+架构+前端三方审核）

## 问题

Admin 页面通过 iframe 内嵌 WebUI，但 `localStorage.token` 为 `undefined`，导致所有 API 调用失败，模型无法加载。

## 根因

**跨源（Cross-Origin）**：Admin 和 WebUI 走了不同端口。

| 服务 | 实际访问地址 | 端口 |
|------|-------------|------|
| Admin | `http://172.32.153.184:40080/admin/` | 40080 (ingress) |
| WebUI iframe | `http://172.32.153.184:48080/?token=xxx` | 48080 (pod 直连) |

协议 + 域名 + 端口 不一致 → 浏览器隔离 localStorage → token 写不进去。

## 修复方案

### 步骤 1：Admin 后端环境变量

Admin 的 `webui_provision.py` 有个未设置的环境变量：

```python
# webui_provision.py:17
EXTERNAL_WEBUI_URL = os.getenv("EXTERNAL_WEBUI_URL", "http://localhost:48080")
```

设置它指向 ingress：

```bash
kubectl set env deploy/hermes-admin -n hermes-agent \
  EXTERNAL_WEBUI_URL=http://172.32.153.184:40080
```

同时更新 deployment.yaml 确保持久化：

```yaml
# admin/kubernetes/deployment.yaml
- name: EXTERNAL_WEBUI_URL
  value: "http://172.32.153.184:40080"  # 改为 ingress 端口
```

这样 `/user/webui-url` API 返回的 signin URL 就走 ingress 40080。

### 步骤 2：Admin 前端两处硬编码端口

审计发现 **两处** 硬编码 `:48080`（原文档只记录了一处）：

#### 2a. AdminLayout.tsx 侧边栏链接（文档遗漏）

```typescript
// admin/frontend/src/components/AdminLayout.tsx:231
// 当前：
href={`http://${window.location.hostname}:48080`}

// 改为：
href={window.location.origin}
```

这是非邮箱认证用户点击"打开 WebUI"的链接，仍然直连 :48080。

#### 2b. ChatPage.tsx iframe src（无硬编码问题）

```typescript
// admin/frontend/src/pages/ChatPage.tsx:23-25
const baseUrl = res.url.replace("/api/v1/auths/signin", "");
const hash = `#email=${encodeURIComponent(res.email)}&password=${encodeURIComponent(res.password)}`;
setIframeSrc(`${baseUrl}/token-login.html${hash}`);
```

此处 URL 来自后端 API `/user/webui-url`，由 `EXTERNAL_WEBUI_URL` 环境变量控制，**无硬编码端口问题**。步骤 1 修好环境变量即可。

### 步骤 3：验证 Ingress 路由配置

Admin 和 WebUI 共享 :40080 端口，需要确认 Ingress 路径优先级：

| 路径 | 后端服务 | 优先级 |
|------|---------|--------|
| `/admin(/\|$)(.*)` | hermes-admin | 高（更长前缀） |
| `/` | hermes-webui | 低（兜底） |

NGINX Ingress 按路径长度优先匹配，`/admin/*` 优先于 `/`，所以不会冲突。但需要确认两个 Ingress 资源都已 apply。

### 步骤 4：验证 WebUI iframe 嵌入许可

检查 WebUI 是否发送阻止 iframe 嵌入的头：

```bash
curl -sI http://172.32.153.184:48080/ | grep -i 'x-frame-options\|content-security-policy'
```

如果返回 `X-Frame-Options: DENY` 或 `frame-ancestors 'none'`，需要移除或改为：

```
Content-Security-Policy: frame-ancestors 'self'
X-Frame-Options: SAMEORIGIN
```

## 完整 Token-Login 数据流

```
1. 用户点击"开始对话"
   → ChatPage.tsx 调用 adminFetch("/user/webui-url")

2. 后端 user_routes.py /user/webui-url
   → 读取 EXTERNAL_WEBUI_URL + user.webui_password
   → 返回 {url: "http://172.32.153.184:40080/api/v1/auths/signin", email, password}

3. ChatPage.tsx 构建 iframe src
   → baseUrl = url 去掉 "/api/v1/auths/signin" → "http://172.32.153.184:40080"
   → iframeSrc = baseUrl + "/token-login.html#email=xxx&password=xxx"

4. WebUI token-login.html 页面
   → 从 URL hash 读取 email + password
   → 调用 WebUI /api/v1/auths/signin 获取 JWT
   → 写入 localStorage.token
   → 重定向到 /

5. 同源（修复后）：Admin(:40080) 和 WebUI(:40080) 共享 localStorage
```

**依赖**：WebUI 必须支持 `/token-login.html` 路由。升级或替换 WebUI 时此约定会断裂，需要回归测试。

## 验证清单

改完后按以下顺序验证：

1. `kubectl get deploy hermes-admin -n hermes-agent -o yaml | grep EXTERNAL_WEBUI_URL`
   → 确认值为 `http://172.32.153.184:40080`
2. Admin 页面侧边栏"打开 WebUI"链接 → 浏览器状态栏 URL 端口应为 **40080**，不是 48080
3. Admin 页面中"开始对话"iframe → 检查 iframe src URL 端口应为 **40080**
4. iframe 场景下打开 DevTools Console → `localStorage.token` → 应返回 JWT 字符串，不是 `undefined`
5. hover 模型选择器 → 应看到 `hermes-agent` 模型
6. 确认 WebUI Ingress 存在：`kubectl get ingress -n hermes-agent`

## 安全审核记录

### CRITICAL：密码在 URL hash 中明文传输

**位置**：`ChatPage.tsx:24`

```typescript
const hash = `#email=${encodeURIComponent(res.email)}&password=${encodeURIComponent(res.password)}`;
setIframeSrc(`${baseUrl}/token-login.html${hash}`);
```

hash 不发送到服务器，但可被父页面 JS 读取，且持久化在浏览器历史中。修复后同源，admin 页面的 JS 可直接访问 iframe 的 `contentDocument` 和 `localStorage.token`。

**建议**（长期）：改为后端代理登录 + 一次性 token（OTT）模式：
1. Admin 后端调 WebUI signin API 获取 JWT
2. 生成短生命周期一次性 token，存内存
3. iframe 加载 `/?ott=xxx`，WebUI 用 OTT 换 JWT
4. OTT 用后即焚

### HIGH：全链路 HTTP 明文

`EXTERNAL_WEBUI_URL` 为 `http://`，token/密码在网络明文传输。内网环境风险可控，但违反纵深防御。

**建议**：Ingress 层加 HTTPS（自签证书即可）。

### HIGH：API 返回明文密码

`/user/webui-url` 端点在响应体中返回 `user.webui_password`。上述 OTT 方案可彻底消除。

### MEDIUM：同源扩大攻击面

修复前，浏览器 SOP 阻止 admin 页面 JS 读取 WebUI iframe 内容。修复后同源，admin XSS 可直接读写 WebUI 状态。

**缓解**：加 CSP `frame-ancestors 'self'` 限制哪些页面可以嵌入 WebUI。

### LOW：缺少点击劫持防护

WebUI 当前未设置 CSP 或 X-Frame-Options，任何网站都可嵌入。建议在 WebUI 响应头中加 `frame-ancestors` 限制。

## 影响范围

| 改动 | 影响服务 | 需要重启 | 需要重建镜像 |
|------|---------|---------|------------|
| 步骤 1：环境变量 | hermes-admin | 是（自动 rollout） | 否 |
| 步骤 2a：AdminLayout.tsx | hermes-admin | 是（自动 rollout） | 是 |
| 步骤 2b：ChatPage.tsx | 无需改动 | — | — |
| 步骤 3：Ingress 配置 | nginx-ingress | 否 | 否 |
| 步骤 4：WebUI 响应头 | hermes-webui | 是 | 可能 |

## 当前端口映射

| 端口 | 服务 | 访问方式 |
|------|------|---------|
| 40080 | Nginx Ingress (hostNetwork) | ingress 代理，**推荐统一用此端口** |
| 48080 | hermes-webui (hostNetwork) | pod 直连，修复后应废弃 |
| 30480 | hermes-webui (NodePort) | Service NodePort |
| 48082 | hermes-admin (ClusterIP) | 仅集群内访问 |

## 附带收益

同源修复后，WebUI 前端的 Direct Connection 模型发现（`getOpenAIModelsDirect` 从浏览器直连 gateway）也不再有 CORS 问题，因为所有请求都从 `:40080` 发出。
