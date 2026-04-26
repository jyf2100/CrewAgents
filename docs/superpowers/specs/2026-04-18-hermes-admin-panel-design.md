# Hermes Agent Admin Panel Design Spec

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a web-based admin panel for managing multiple Hermes Agent instances on a Kubernetes cluster — config generation, deployment, and monitoring.

**Architecture:** React SPA + FastAPI backend, both served through the existing Nginx Ingress at `/admin`. Backend wraps K8s API operations (Deployment/Service/Secret/Ingress CRUD) into simple REST endpoints.

**Tech Stack:** React 19 + Vite 7 + TypeScript + Tailwind CSS 4 + shadcn/ui + FastAPI + kubernetes-client/python

---

## 1. Architecture

```
Browser → Ingress (:40080) → ┌─ /admin/*     → React SPA (static)
                              └─ /admin/api/* → FastAPI Backend → K8s API
                                                  ↘ hostPath /data/hermes/agentN
```

### Components

| Component | Runtime | Port | Access |
|-----------|---------|------|--------|
| React SPA | Nginx / static serving | — | Ingress `/admin` |
| FastAPI Backend | K8s Deployment | 48082 | Ingress `/admin/api` |
| K8s API | Existing cluster | 6443 | ServiceAccount token |

### Naming Convention

All agent resources follow a consistent pattern:

| Resource | Pattern | Example |
|----------|---------|---------|
| K8s Deployment | `hermes-gateway-N` | `hermes-gateway-4` |
| K8s Service | `hermes-gateway-N` | `hermes-gateway-4` |
| K8s Secret | `hermes-gateway-N-secret` | `hermes-gateway-4-secret` |
| Ingress path | `/agentN` | `/agent4` |
| Data dir | `/data/hermes/agentN` | `/data/hermes/agent4` |
| Secret key | `api_key` (single key per secret) | `api_key` |

### Security

- Admin API protected by API key (stored in K8s Secret `hermes-admin-secret`)
- Backend ServiceAccount scoped to `hermes-agent` namespace with permissions for: Deployments, Services, Ingresses, Secrets, Pods, Events, ConfigMaps
- `.env` read returns masked values; write is key-level (never returns unmasked secrets)

---

## 2. Backend API

### Agent CRUD

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/admin/api/agents` | GET | List all agents with status, resources, health |
| `/admin/api/agents` | POST | Create agent (generate templates → write files → apply K8s resources) |
| `/admin/api/agents/:id` | GET | Agent detail (config, status, events) |
| `/admin/api/agents/:id` | DELETE | Delete agent (optional backup before deletion) |
| `/admin/api/agents/:id/restart` | POST | Rollout restart |
| `/admin/api/agents/:id/stop` | POST | Scale to 0 replicas |
| `/admin/api/agents/:id/start` | POST | Scale to 1 replica |

### Agent Config

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/admin/api/agents/:id/config` | GET | Read config.yaml (non-secret) |
| `/admin/api/agents/:id/config` | PUT | Write config.yaml + restart |
| `/admin/api/agents/:id/env` | GET | Read .env (values masked) |
| `/admin/api/agents/:id/env` | PUT | Write .env key-value pairs + restart |
| `/admin/api/agents/:id/soul` | GET/PUT | Read/write SOUL.md |

### Agent Monitoring

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/admin/api/agents/:id/health` | GET | Proxy to gateway `/health` endpoint |
| `/admin/api/agents/:id/logs` | GET | Streaming pod logs (SSE) |
| `/admin/api/agents/:id/events` | GET | K8s events for this agent's deployment |
| `/admin/api/agents/:id/resources` | GET | CPU/memory usage |

### Agent Operations

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/admin/api/agents/:id/backup` | POST | Download backup (K8s resources YAML + data tar) |

### Cluster

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/admin/api/cluster/status` | GET | Node info, total CPU/memory/disk usage |
| `/admin/api/templates` | GET | Default templates (deployment, .env, config.yaml, SOUL.md) |
| `/admin/api/test-llm-connection` | POST | Test LLM API key validity (send minimal completion request) |

### Auth

All requests require header `X-Admin-Key: <key>`. Key stored in `hermes-admin-secret`.

---

## 3. Frontend Pages (4 pages)

### Page 1: Dashboard (`/admin`)

Cluster overview + agent cards.

**Layout:**
```
┌─────────────────────────────────────────────┐
│ Hermes Agent Manager          [设置] ⚙      │
├─────────────────────────────────────────────┤
│ Cluster: roc-epyc | CPU 68% | Mem 4.2/8Gi  │
│ Disk: 149/234G (68%)                        │
├─────────────────────────────────────────────┤
│ ┌──────────────┐ ┌──────────────┐  [+新建]  │
│ │ Agent 1      │ │ Agent 2      │           │
│ │ ● 运行中      │ │ ● 运行中      │           │
│ │ CPU 12%      │ │ CPU 8%       │           │
│ │ Mem 800M     │ │ Mem 600M     │           │
│ │ Restarts: 0  │ │ Restarts: 2  │           │
│ │ 部署于 2h前   │ │ 部署于 5d前   │           │
│ │ [详情]  [...] │ │ [详情]  [...] │           │
│ └──────────────┘ └──────────────┘           │
└─────────────────────────────────────────────┘
```

**Agent card info:**
- Name + status indicator (green/red/yellow)
- CPU + Memory usage bars
- Restart count (red badge if > 0)
- Last deploy time (relative)
- [详情] button → navigate to Agent Detail
- [...] kebab menu → Restart / Stop / View Logs / Backup

**Behavior:**
- Sort by status: failed → warning → running
- Auto-refresh every 10s
- Cards use responsive grid: `grid-cols-1 sm:grid-cols-2 lg:grid-cols-3`

### Page 2: Agent Detail (`/admin/agents/:id`)

Everything about a single agent in tabs.

**Layout:**
```
┌───────────────────────────────────────────────┐
│ ← 返回   Agent: hermes-gateway-1   [重启][停止]│
├───────────────────────────────────────────────┤
│ [概览] [配置] [日志] [K8s Events] [健康]        │
├───────────────────────────────────────────────┤
│                                               │
│  (tab content)                                │
│                                               │
└───────────────────────────────────────────────┘
```

**Tab: 概览 (Overview)**
- Status card (running/stopped, pod IP, node, age)
- Resource usage sparkline (CPU + Memory over last hour)
- Connected platforms
- Active sessions count
- Quick stats (total messages, total tokens)

**Tab: 配置 (Config)**
- Sub-tabs: `.env` | `config.yaml` | `SOUL.md`
- `.env`: key-value form editor, secret fields masked, "add variable" button
- `config.yaml`: raw YAML code editor with syntax highlighting
- `SOUL.md`: markdown textarea with preview
- [Apply] button with diff preview and confirmation dialog

**Tab: 日志 (Logs)**
- Streaming log viewer (SSE from backend)
- Filter bar: log level, component, search text
- Auto-scroll to bottom, pause/resume button

**Tab: K8s Events**
- Table: Type (Warning/Normal), Reason, Message, Age
- Auto-refresh every 10s
- Warning rows highlighted yellow/red

**Tab: 健康 (Health)**
- Gateway `/health` response
- K8s readiness/liveness probe status
- Last health check timestamp

### Page 3: Create Agent (`/admin/create`)

4-step wizard.

**Step 1: 基本信息**
- Agent number (auto-increment, editable)
- Display name (optional)
- Resource limits: CPU (default 1000m), Memory (default 1Gi)

**Step 2: LLM 配置**
- Provider dropdown: OpenRouter / Anthropic / OpenAI / Gemini / ZhipuAI / Custom
- Model input (text, default based on provider)
- API Key input (password field)
- Base URL (auto-filled, editable for custom)
- [测试连接] button → calls `/admin/api/test-llm-connection` → shows success/failure + latency

**Step 3: 代理配置**
- SOUL.md textarea (pre-filled from template)
- Additional .env variables (dynamic key-value pairs, add/remove rows)

**Step 4: 确认部署**
- Summary card of all settings
- Collapsible "查看原始模板" section with tabs for each generated file
- [部署] button with progress indicator:
  1. Creating Secret... ✓
  2. Initializing data directory... ✓
  3. Creating Deployment... ✓
  4. Updating Ingress... ✓
  5. Waiting for ready... ✓
- On success: redirect to Agent Detail page

### Page 4: Settings (`/admin/settings`)

Admin panel configuration.

- Cluster connection status
- Admin API key (change)
- Default resource limits for new agents
- Default templates (editable deployment, .env, config.yaml, SOUL.md templates)

---

## 4. K8s Deployment

### Backend Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: hermes-admin
  namespace: hermes-agent
spec:
  replicas: 1
  selector:
    matchLabels:
      app: hermes-admin
  template:
    spec:
      serviceAccountName: hermes-admin
      containers:
        - name: admin
          image: hermes-admin:latest
          ports:
            - containerPort: 48082
          env:
            - name: K8S_NAMESPACE
              value: "hermes-agent"
            - name: ADMIN_KEY
              valueFrom:
                secretKeyRef:
                  name: hermes-admin-secret
                  key: admin_key
          volumeMounts:
            - name: hermes-data-root
              mountPath: /data/hermes
              readOnly: false  # Need write access for config edits and backup archives
      volumes:
        - name: hermes-data-root
          hostPath:
            path: /data/hermes
            type: Directory
```

### RBAC

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: hermes-admin
  namespace: hermes-agent
rules:
  - apiGroups: ["apps"]
    resources: ["deployments"]
    verbs: ["get", "list", "watch", "create", "delete", "update", "patch"]
  - apiGroups: [""]
    resources: ["services", "pods", "pods/log", "events", "secrets", "configmaps"]
    verbs: ["get", "list", "watch", "create", "delete", "update", "patch"]
  - apiGroups: ["networking.k8s.io"]
    resources: ["ingresses"]
    verbs: ["get", "list", "watch", "update", "patch"]
```

### Ingress Addition

Add to existing `hermes-ingress`:
```yaml
- path: /admin/api(/|$)(.*)
  pathType: Prefix
  backend:
    service:
      name: hermes-admin
      port:
        number: 48082
- path: /admin(/|$)(.*)
  pathType: Prefix
  backend:
    service:
      name: hermes-admin
      port:
        number: 48082
```

---

## 5. File Structure

```
admin/
├── backend/
│   ├── main.py              # FastAPI app, static file serving
│   ├── k8s_client.py         # K8s API wrapper (deployments, secrets, ingress)
│   ├── agent_manager.py      # Agent lifecycle logic (create/delete/restart)
│   ├── config_manager.py     # Read/write config files on hostPath
│   ├── templates.py          # Template generation (deployment, .env, config.yaml, SOUL.md)
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── App.tsx           # Router setup (/admin/*)
│   │   ├── pages/
│   │   │   ├── DashboardPage.tsx
│   │   │   ├── AgentDetailPage.tsx
│   │   │   ├── CreateAgentPage.tsx
│   │   │   └── SettingsPage.tsx
│   │   ├── components/
│   │   │   ├── AgentCard.tsx
│   │   │   ├── ClusterStatus.tsx
│   │   │   ├── ConfigEditor.tsx
│   │   │   ├── LogViewer.tsx
│   │   │   ├── EventsTable.tsx
│   │   │   └── CreateWizard.tsx
│   │   ├── lib/
│   │   │   └── admin-api.ts  # API client
│   │   └── i18n/
│   │       ├── zh.ts         # Chinese translations (admin namespace)
│   │       └── en.ts         # English translations (admin namespace)
│   ├── package.json
│   ├── vite.config.ts
│   └── tailwind.config.ts
├── kubernetes/
│   ├── deployment.yaml       # Admin backend deployment
│   ├── rbac.yaml             # ServiceAccount + Role + RoleBinding
│   ├── secret.yaml           # Admin API key secret
│   └── ingress-patch.yaml    # Ingress addition for /admin
└── templates/
    ├── deployment.yaml        # Default deployment template
    ├── .env.template          # Default .env template
    ├── config.yaml.template   # Default config.yaml template
    └── SOUL.md.template       # Default SOUL.md template
```

---

## 6. Localization

Chinese as primary language. K8s terms stay in English.

Key translations:
- Dashboard → 仪表盘
- Agent → 代理 (UI), hermes-gateway (K8s resource)
- Running → 运行中
- Stopped → 已停止
- Create → 新建
- Restart → 重启
- Deploy → 部署
- Backup → 备份
- Config → 配置
- Health → 健康
- Logs → 日志
- Pod, Deployment, Secret, Ingress, Namespace → keep English

---

## 7. Out of Scope (v1)

- WebSocket real-time updates (use polling/SSE only)
- Multi-cluster management
- RBAC user management
- Automated scheduling/scale policies
- GitOps integration
- Mobile-optimized layouts
- Restore from backup (manual kubectl apply)
