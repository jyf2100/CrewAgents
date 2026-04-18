# Hermes Admin Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a web-based admin panel (React SPA + FastAPI backend) for managing multiple Hermes Agent instances on a K8s cluster — CRUD, config generation, deployment, monitoring.

**Architecture:** React SPA served by FastAPI backend at `/admin` path through existing Nginx Ingress. Backend wraps K8s API operations into REST endpoints. All agent config files live on hostPath `/data/hermes/agentN/`.

**Tech Stack:** Python 3.11 + FastAPI + kubernetes-client/python + React 19 + Vite 7 + TypeScript + Tailwind CSS 4 + react-router-dom

**Specs:** See `docs/superpowers/specs/2026-04-18-hermes-admin-panel-design.md` and companion detail docs (`admin-backend-detail.md`, `admin-frontend-detail.md`, `admin-k8s-detail.md`).

---

## File Structure

All new files under `admin/`:

```
admin/
├── backend/
│   ├── main.py              # FastAPI app, static file serving, routes
│   ├── models.py             # Pydantic models (all request/response types)
│   ├── k8s_client.py         # Async K8s API wrapper
│   ├── agent_manager.py      # Agent lifecycle (create/delete/restart/scale/backup)
│   ├── config_manager.py     # Read/write config files on hostPath
│   ├── templates.py          # Template generation (deployment, .env, config.yaml, SOUL.md)
│   ├── Dockerfile             # Multi-stage build (frontend → Python runtime)
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── App.tsx           # BrowserRouter + routes
│   │   ├── main.tsx          # Entry point
│   │   ├── pages/
│   │   │   ├── DashboardPage.tsx
│   │   │   ├── AgentDetailPage.tsx
│   │   │   ├── CreateAgentPage.tsx
│   │   │   ├── SettingsPage.tsx
│   │   │   └── LoginPage.tsx
│   │   ├── components/
│   │   │   ├── AdminLayout.tsx
│   │   │   ├── AgentCard.tsx
│   │   │   ├── ClusterStatusBar.tsx
│   │   │   ├── ConfirmDialog.tsx
│   │   │   ├── LoadingSpinner.tsx
│   │   │   └── ErrorDisplay.tsx
│   │   ├── lib/
│   │   │   └── admin-api.ts  # API client + types
│   │   └── i18n/
│   │       ├── zh.ts
│   │       └── en.ts
│   ├── index.html
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   └── tailwind.config.ts
├── kubernetes/
│   ├── deployment.yaml
│   ├── service.yaml
│   ├── rbac.yaml
│   ├── secret.yaml
│   ├── deploy.sh
│   ├── upgrade.sh
│   └── uninstall.sh
└── templates/
    ├── deployment.yaml
    ├── .env.template
    ├── config.yaml.template
    └── SOUL.md.template
```

---

## Phase 1: Backend Foundation

### Task 1: Backend project scaffold

**Files:**
- Create: `admin/backend/requirements.txt`
- Create: `admin/backend/main.py` (skeleton)

- [ ] **Step 1: Create requirements.txt**

```
fastapi==0.115.12
uvicorn[standard]==0.34.2
kubernetes==32.0.1
python-multipart==0.0.20
pyyaml==6.0.2
aiofiles==24.1.0
httpx==0.28.1
```

- [ ] **Step 2: Create main.py skeleton with app setup, CORS, global exception handler, auth dependency**

```python
import logging
import os
import traceback

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

logger = logging.getLogger("hermes-admin")

API_PREFIX = "/admin/api"
K8S_NAMESPACE = os.getenv("K8S_NAMESPACE", "hermes-agent")
ADMIN_KEY = os.getenv("ADMIN_KEY", "")

app = FastAPI(title="Hermes Admin API", openapi_url=None, docs_url=None)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled exception on %s %s: %s\n%s",
                 request.method, request.url.path, exc, traceback.format_exc())
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


async def verify_admin_key(x_admin_key: str = Header(..., alias="X-Admin-Key")):
    if ADMIN_KEY and x_admin_key != ADMIN_KEY:
        raise HTTPException(status_code=401, detail="Invalid admin key")
    return x_admin_key


auth = Depends(verify_admin_key)


@app.get(f"{API_PREFIX}/health")
async def health():
    return {"status": "ok"}
```

- [ ] **Step 3: Verify the backend starts**

```bash
cd admin/backend && pip install -r requirements.txt && python -c "from main import app; print('OK')"
```

- [ ] **Step 4: Commit**

```bash
git add admin/backend/requirements.txt admin/backend/main.py
git commit -m "feat(admin): scaffold backend project with FastAPI app skeleton"
```

---

### Task 2: Pydantic models

**Files:**
- Create: `admin/backend/models.py`

- [ ] **Step 1: Create models.py with all request/response Pydantic models**

Copy the complete models from spec section `admin-backend-detail.md` Section 1 (lines 13–399). Includes: enums (AgentStatus, LLMProvider, EventType), nested models (ResourceUsage, ContainerStatus, PodInfo, EnvVariable), request/response models for all 28 endpoints.

Key models: `AgentSummary`, `AgentListResponse`, `AgentDetailResponse`, `CreateAgentRequest`, `EnvReadResponse`, `EnvWriteRequest`, `ConfigWriteRequest`, `SoulWriteRequest`, `HealthResponse`, `K8sEvent`, `EventListResponse`, `BackupRequest`, `BackupResponse`, `ClusterStatusResponse`, `TemplateResponse`, `TestLLMRequest`, `TestLLMResponse`, `ActionResponse`, `SettingsResponse`, `MessageResponse`.

- [ ] **Step 2: Verify models import cleanly**

```bash
cd admin/backend && python -c "from models import *; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add admin/backend/models.py
git commit -m "feat(admin): add all Pydantic request/response models"
```

---

### Task 3: K8s client wrapper

**Files:**
- Create: `admin/backend/k8s_client.py`

- [ ] **Step 1: Create k8s_client.py with async K8s API wrapper**

Implements `K8sClient` class from spec section 11. Key methods:
- `_k8s_call(fn, *args, **kwargs)` — runs sync K8s calls in thread pool with 30s timeout
- `get_deployment`, `create_deployment`, `delete_deployment`, `patch_deployment`
- `get_service`, `create_service`, `delete_service`
- `get_secret`, `create_secret`, `delete_secret`
- `get_pods_for_deployment`, `get_first_pod_name`
- `get_events` (filtered for deployment's pods)
- `add_ingress_path` (read-modify-write with asyncio.Lock + resource_version)
- `remove_ingress_path` (filter out matching path)
- `wait_deployment_ready` (poll until availableReplicas >= replicas)
- `get_pod_metrics` (metrics.k8s.io custom object, graceful fallback)

The ingress lock (`_ingress_lock = asyncio.Lock()`) serializes concurrent mutations.

- [ ] **Step 2: Verify K8sClient imports (will not connect outside cluster)**

```bash
cd admin/backend && python -c "from k8s_client import K8sClient; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add admin/backend/k8s_client.py
git commit -m "feat(admin): add async K8s API client wrapper"
```

---

### Task 4: Config manager

**Files:**
- Create: `admin/backend/config_manager.py`

- [ ] **Step 1: Create config_manager.py**

Implements `ConfigManager` from spec section 6. Methods:
- `read_env(agent_id)` — parse .env, mask values matching SECRET_PATTERNS regex
- `write_env(agent_id, updates)` — key-level merge, reject BLOCKED_ENV_KEYS, atomic write via .tmp + os.replace
- `read_config(agent_id)` — read config.yaml
- `write_config(agent_id, content)` — YAML validation via yaml.safe_load, atomic write
- `read_soul(agent_id)` — read SOUL.md
- `write_soul(agent_id, content)` — write SOUL.md, atomic

Secret masking regex: `r"(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|AUTH)"`
Blocked env keys: `PATH, HOME, USER, SHELL, LD_PRELOAD, LD_LIBRARY_PATH, PYTHONPATH, PYTHONHOME, HOSTNAME, TERM, LANG, LC_ALL, PWD, OLDPWD, MAIL, LOGNAME, SSH_AUTH_SOCK, DISPLAY, XDG_RUNTIME_DIR, container, KUBERNETES_SERVICE_HOST, KUBERNETES_SERVICE_PORT`

- [ ] **Step 2: Verify config_manager imports**

```bash
cd admin/backend && python -c "from config_manager import ConfigManager; cm = ConfigManager('/tmp/test-data'); print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add admin/backend/config_manager.py
git commit -m "feat(admin): add config manager for hostPath file read/write"
```

---

### Task 5: Template generator

**Files:**
- Create: `admin/backend/templates.py`
- Create: `admin/templates/deployment.yaml`
- Create: `admin/templates/.env.template`
- Create: `admin/templates/config.yaml.template`
- Create: `admin/templates/SOUL.md.template`

- [ ] **Step 1: Create template files in admin/templates/**

Copy from `.claude/skills/hermes-agent-lifecycle/references/`:
- `.env.template` → `admin/templates/.env.template`
- `config.yaml.template` → `admin/templates/config.yaml.template`
- `SOUL.md.template` → `admin/templates/SOUL.md.template`
- `deployment-template.yaml` → `admin/templates/deployment.yaml`

- [ ] **Step 2: Create templates.py with TemplateGenerator class**

Methods:
- `render_env(llm_config, extra_env)` — generate .env content from LLM config
- `render_config_yaml(default_model, provider, base_url, ...)` — generate config.yaml
- `render_deployment(agent_number, secret_name, resources)` — generate Deployment dict
- `render_service(agent_number)` — generate Service dict
- `get_all()` — return all templates as TemplateResponse
- `get_template(type)` — return single template by type
- `set_template(type, content)` — update and persist a template

- [ ] **Step 3: Verify templates.py imports and generates output**

```bash
cd admin/backend && python -c "
from templates import TemplateGenerator
t = TemplateGenerator()
print(t.render_service(1))
print('OK')
"
```

- [ ] **Step 4: Commit**

```bash
git add admin/backend/templates.py admin/templates/
git commit -m "feat(admin): add template generator for agent resource creation"
```

---

### Task 6: Agent manager

**Files:**
- Create: `admin/backend/agent_manager.py`

- [ ] **Step 1: Create agent_manager.py with all lifecycle methods**

Implements `AgentManager` from spec sections 4, 5, 7, 8, 9, 10:
- `list_agents()` — list deployments, fetch pod status + metrics, build AgentSummary list
- `get_agent_detail(agent_id)` — full agent detail with pods, resources, ingress path
- `create_agent(req)` — 5-step creation with rollback on failure
- `delete_agent(agent_id, backup)` — optional backup then delete all K8s resources + data dir
- `restart_agent(agent_id)` — patch deployment annotation with timestamp
- `scale_agent(agent_id, replicas, action)` — scale to 0 (stop) or 1 (start)
- `check_health(agent_id)` — proxy to gateway /health via K8s Service DNS
- `stream_logs(agent_id, tail, follow, request)` — SSE generator from K8s pod log stream
- `get_events(agent_id)` — K8s events for agent's deployment
- `get_resource_usage(agent_id)` — CPU/memory from metrics.k8s.io
- `backup_agent(agent_id, req)` — tar.gz with K8s YAML + masked data dir
- `test_llm(req)` — send minimal chat completion request to validate API key
- `get_cluster_status()` — node info, disk usage, agent counts
- `get_default_resource_limits()` / `set_default_resource_limits()`

Creation flow: validate → create Secret → init data dir → create Deployment+Service → patch Ingress → wait for ready. Each step has rollback on failure.

Backup: K8s resources exported as YAML, .env secrets masked with `****`, data dir tarred.

- [ ] **Step 2: Verify agent_manager imports**

```bash
cd admin/backend && python -c "from agent_manager import AgentManager; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add admin/backend/agent_manager.py
git commit -m "feat(admin): add agent lifecycle manager (create/delete/restart/backup)"
```

---

## Phase 2: Backend API Routes

### Task 7: Wire all API routes into main.py

**Files:**
- Modify: `admin/backend/main.py`

- [ ] **Step 1: Add imports and singleton helpers**

```python
from models import (
    ActionResponse, AgentDetailResponse, AgentListResponse,
    BackupRequest, BackupResponse, ClusterStatusResponse,
    ConfigWriteRequest, CreateAgentRequest, CreateAgentResponse,
    EnvReadResponse, EnvWriteRequest, EventListResponse,
    HealthResponse, MessageResponse, SoulWriteRequest, SoulMarkdown,
    ConfigYaml, TemplateResponse, TemplateTypeResponse,
    TestLLMRequest, TestLLMResponse, UpdateResourceLimitsRequest,
    UpdateAdminKeyRequest, UpdateTemplateRequest, SettingsResponse,
)
from k8s_client import K8sClient
from agent_manager import AgentManager
from config_manager import ConfigManager
from templates import TemplateGenerator

k8s = K8sClient(namespace=K8S_NAMESPACE)
manager = AgentManager(k8s=k8s, namespace=K8S_NAMESPACE)
config_mgr = ConfigManager(data_root=os.getenv("HERMES_DATA_ROOT", "/data/hermes"))
tpl = TemplateGenerator()
```

- [ ] **Step 2: Add all route definitions**

Add all 28 endpoints from spec section 3 (backend-detail.md sections 3.1–3.6):
- Agent CRUD: GET/POST /agents, GET/DELETE /agents/{id}, POST restart/stop/start
- Agent Config: GET/PUT config, GET/PUT env, GET/PUT soul
- Agent Monitoring: GET health, GET logs (SSE), GET logs/token, GET events, GET resources
- Agent Operations: POST backup, GET backups/{filename}
- Cluster: GET cluster/status, GET templates, GET/PUT templates/{type}
- LLM Test: POST test-llm-connection
- Settings: GET/PUT settings, PUT settings/admin-key

SSE log endpoint includes token-based auth fallback for EventSource.

- [ ] **Step 3: Add static file serving for SPA**

```python
from pathlib import Path
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

STATIC_DIR = Path(__file__).parent / "static"

# Mount assets
app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

@app.get("/{full_path:path}")
async def spa_fallback(full_path: str):
    if "." in full_path.split("/")[-1]:
        file_path = STATIC_DIR / full_path
        if file_path.is_file():
            return FileResponse(file_path)
    return FileResponse(STATIC_DIR / "index.html")
```

- [ ] **Step 4: Verify all routes register correctly**

```bash
cd admin/backend && python -c "from main import app; routes = [r.path for r in app.routes]; print(f'{len(routes)} routes'); print('\n'.join(sorted(routes)))"
```

- [ ] **Step 5: Commit**

```bash
git add admin/backend/main.py
git commit -m "feat(admin): wire all 28 API endpoints and SPA static serving"
```

---

## Phase 3: Frontend Foundation

### Task 8: Frontend project scaffold

**Files:**
- Create: `admin/frontend/package.json`
- Create: `admin/frontend/tsconfig.json`
- Create: `admin/frontend/vite.config.ts`
- Create: `admin/frontend/tailwind.config.ts`
- Create: `admin/frontend/index.html`
- Create: `admin/frontend/src/main.tsx`

- [ ] **Step 1: Create package.json**

```json
{
  "name": "hermes-admin",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^19.0.0",
    "react-dom": "^19.0.0",
    "react-router-dom": "^7.5.0"
  },
  "devDependencies": {
    "@tailwindcss/vite": "^4.0.0",
    "@types/react": "^19.0.0",
    "@types/react-dom": "^19.0.0",
    "@vitejs/plugin-react": "^4.3.0",
    "tailwindcss": "^4.0.0",
    "typescript": "^5.7.0",
    "vite": "^7.0.0"
  }
}
```

- [ ] **Step 2: Create vite.config.ts with /admin base path and dev proxy**

```typescript
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  base: '/admin/',
  plugins: [react(), tailwindcss()],
  build: { outDir: 'dist', sourcemap: false },
  server: {
    proxy: {
      '/admin/api': {
        target: 'http://localhost:48082',
        rewrite: (path) => path.replace(/^\/admin/, ''),
        changeOrigin: true,
      },
    },
  },
});
```

- [ ] **Step 3: Create tsconfig.json**

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "isolatedModules": true,
    "moduleDetection": "force",
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": false,
    "noUnusedParameters": false,
    "noFallthroughCasesInSwitch": true,
    "forceConsistentCasingInFileNames": true
  },
  "include": ["src"]
}
```

- [ ] **Step 4: Create index.html**

```html
<!DOCTYPE html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Hermes Admin</title>
    <base href="/admin/" />
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/admin/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 5: Create main.tsx with CSS import and root render**

```tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>
);
```

- [ ] **Step 6: Create src/index.css with Tailwind import**

```css
@import "tailwindcss";
```

- [ ] **Step 7: Install dependencies and verify build**

```bash
cd admin/frontend && npm install --registry https://registry.npmmirror.com && npm run build
```

- [ ] **Step 8: Commit**

```bash
git add admin/frontend/
git commit -m "feat(admin): scaffold frontend project with Vite + React + Tailwind"
```

---

### Task 9: API client + types

**Files:**
- Create: `admin/frontend/src/lib/admin-api.ts`

- [ ] **Step 1: Create admin-api.ts with full API client**

Copy the complete TypeScript API client from spec section 7 (`admin-frontend-detail.md` lines 987–1378). Includes:
- Type definitions: AgentListItem, AgentDetail, ClusterStatus, K8sEvent, CreateAgentRequest, HealthResponse, Templates, AdminSettings, etc.
- `AdminApiError` class with status code
- `adminFetch<T>()` helper with X-Admin-Key header and 401 redirect
- `adminApi` object with all methods: login, listAgents, getAgent, createAgent, deleteAgent, restartAgent, stopAgent, startAgent, getAgentConfig, updateAgentConfig, getAgentEnv, updateAgentEnv, getAgentSoul, updateAgentSoul, getAgentHealth, getAgentEvents, getAgentResources, getAgentLogsUrl, backupAgent, getClusterStatus, getSettings, updateSettings, changeAdminKey, getTemplate, updateTemplate, testLlmConnection

- [ ] **Step 2: Commit**

```bash
git add admin/frontend/src/lib/admin-api.ts
git commit -m "feat(admin): add TypeScript API client with all endpoint methods"
```

---

### Task 10: i18n translations

**Files:**
- Create: `admin/frontend/src/i18n/zh.ts`
- Create: `admin/frontend/src/i18n/en.ts`
- Create: `admin/frontend/src/hooks/useI18n.ts`

- [ ] **Step 1: Create useI18n hook**

Simple i18n hook: reads language from localStorage key `admin_lang`, defaults to `zh`. Returns `{ t, lang, setLang }` where `t` is the translation object.

```typescript
import { useState, useCallback } from "react";
import { zh } from "../i18n/zh";
import { en } from "../i18n/en";

const translations = { zh, en } as const;
type Lang = keyof typeof translations;

export function useI18n() {
  const [lang, setLangState] = useState<Lang>(
    (localStorage.getItem("admin_lang") as Lang) || "zh"
  );
  const setLang = useCallback((l: Lang) => {
    localStorage.setItem("admin_lang", l);
    setLangState(l);
  }, []);
  return { t: translations[lang], lang, setLang };
}
```

- [ ] **Step 2: Create zh.ts with ~130 admin translation keys**

Copy from spec section 8.2 (`admin-frontend-detail.md` lines 1582–1768). All Chinese translations for the admin namespace.

- [ ] **Step 3: Create en.ts with ~130 admin translation keys**

Copy from spec section 8.3 (`admin-frontend-detail.md` lines 1773–1959). All English translations for the admin namespace.

- [ ] **Step 4: Commit**

```bash
git add admin/frontend/src/i18n/ admin/frontend/src/hooks/
git commit -m "feat(admin): add i18n translations (zh + en) and useI18n hook"
```

---

### Task 11: Shared components

**Files:**
- Create: `admin/frontend/src/components/LoadingSpinner.tsx`
- Create: `admin/frontend/src/components/ErrorDisplay.tsx`
- Create: `admin/frontend/src/components/ConfirmDialog.tsx`
- Create: `admin/frontend/src/components/AdminLayout.tsx`

- [ ] **Step 1: Create LoadingSpinner** — centered spinning border circle.

- [ ] **Step 2: Create ErrorDisplay** — red bordered box with error message + optional retry button.

- [ ] **Step 3: Create ConfirmDialog** — fixed overlay with title, message, cancel/confirm buttons. Props: `open, title, message, confirmLabel, variant ("destructive"|"default"), onConfirm, onCancel`.

- [ ] **Step 4: Create AdminLayout** — checks localStorage for admin_api_key, renders header (title + language switcher + nav links) and routes, redirects to login if no key.

- [ ] **Step 5: Commit**

```bash
git add admin/frontend/src/components/
git commit -m "feat(admin): add shared components (spinner, error, dialog, layout)"
```

---

## Phase 4: Frontend Pages

### Task 12: App.tsx with routing + LoginPage

**Files:**
- Create: `admin/frontend/src/App.tsx`
- Create: `admin/frontend/src/pages/LoginPage.tsx`

- [ ] **Step 1: Create App.tsx with BrowserRouter (basename="/admin") and all routes**

Routes: `/` → DashboardPage, `/agents/:id` → AgentDetailPage, `/create` → CreateAgentPage, `/settings` → SettingsPage, `/login` → LoginPage.

- [ ] **Step 2: Create LoginPage** — centered form with password input, submits via `adminApi.login(key)`, stores key in localStorage.

- [ ] **Step 3: Verify app builds**

```bash
cd admin/frontend && npm run build
```

- [ ] **Step 4: Commit**

```bash
git add admin/frontend/src/App.tsx admin/frontend/src/pages/LoginPage.tsx
git commit -m "feat(admin): add App routing and login page"
```

---

### Task 13: DashboardPage

**Files:**
- Create: `admin/frontend/src/pages/DashboardPage.tsx`
- Create: `admin/frontend/src/components/ClusterStatusBar.tsx`
- Create: `admin/frontend/src/components/AgentCard.tsx`

- [ ] **Step 1: Create ClusterStatusBar** — horizontal strip showing cluster name, CPU/Mem/Disk bars (color-coded), agent count.

- [ ] **Step 2: Create AgentCard** — card showing agent name, status dot, CPU/Mem resource bars, restart badge, age, detail button, kebab menu with actions (restart/stop/start/delete/backup/view-logs).

- [ ] **Step 3: Create DashboardPage** — loads agents + cluster status, renders ClusterStatusBar + AgentCard grid (responsive 1/2/3 columns), auto-refresh every 10s, sorted by status priority (failed > starting > stopped > running).

- [ ] **Step 4: Verify build**

```bash
cd admin/frontend && npm run build
```

- [ ] **Step 5: Commit**

```bash
git add admin/frontend/src/pages/DashboardPage.tsx admin/frontend/src/components/ClusterStatusBar.tsx admin/frontend/src/components/AgentCard.tsx
git commit -m "feat(admin): add dashboard page with cluster status bar and agent cards"
```

---

### Task 14: AgentDetailPage

**Files:**
- Create: `admin/frontend/src/pages/AgentDetailPage.tsx`

- [ ] **Step 1: Create AgentDetailPage with 5 tabs**

Uses `useSearchParams` for tab deep-linking (`?tab=overview|config|logs|events|health`).

**OverviewTab**: StatusCard (pod IP, node, age), ResourceUsage (CPU/Mem bars), ConnectedPlatforms, QuickStats.

**ConfigTab**: Sub-tabs for .env (form editor with masked values), config.yaml (monospace textarea), SOUL.md (textarea + preview). Apply button with diff preview.

**LogsTab**: SSE streaming via EventSource with short-lived token auth. Filter bar (level, search), auto-scroll, pause/resume.

**EventsTab**: Table with Type (Warning/Normal badge), Reason, Message, Count, Age. Auto-refresh 10s.

**HealthTab**: Overall status, readiness/liveness probe status, gateway /health response JSON, last check time.

All actions (restart/stop/start/delete) in header with confirm dialogs.

- [ ] **Step 2: Verify build**

```bash
cd admin/frontend && npm run build
```

- [ ] **Step 3: Commit**

```bash
git add admin/frontend/src/pages/AgentDetailPage.tsx
git commit -m "feat(admin): add agent detail page with overview/config/logs/events/health tabs"
```

---

### Task 15: CreateAgentPage

**Files:**
- Create: `admin/frontend/src/pages/CreateAgentPage.tsx`

- [ ] **Step 1: Create CreateAgentPage with 4-step wizard**

**Step 1 (Basic Info)**: Agent number (auto-increment), display name, CPU/memory limits.

**Step 2 (LLM Config)**: Provider dropdown (OpenRouter/Anthropic/OpenAI/Gemini/ZhipuAI/Custom), model, API key (password field), base URL (auto-filled). "Test Connection" button.

**Step 3 (Agent Config)**: SOUL.md textarea (pre-filled from template), extra env vars (dynamic key-value rows).

**Step 4 (Confirm & Deploy)**: Summary card, collapsible raw template preview, Deploy button with progress stepper (Creating Secret → Init Data → Create Deployment → Update Ingress → Wait Ready).

On deploy success, redirects to Agent Detail page.

- [ ] **Step 2: Verify build**

```bash
cd admin/frontend && npm run build
```

- [ ] **Step 3: Commit**

```bash
git add admin/frontend/src/pages/CreateAgentPage.tsx
git commit -m "feat(admin): add 4-step create agent wizard"
```

---

### Task 16: SettingsPage

**Files:**
- Create: `admin/frontend/src/pages/SettingsPage.tsx`

- [ ] **Step 1: Create SettingsPage**

Sections:
- Cluster status (read-only)
- Admin API key change (current masked, new + confirm, warning dialog)
- Default resource limits (CPU/memory inputs)
- Template editor (4 sub-tabs: deployment, .env, config.yaml, SOUL.md, each as monospace textarea)

Save button for each section. Toast on success/failure.

- [ ] **Step 2: Verify build**

```bash
cd admin/frontend && npm run build
```

- [ ] **Step 3: Commit**

```bash
git add admin/frontend/src/pages/SettingsPage.tsx
git commit -m "feat(admin): add settings page with key change, resource defaults, templates"
```

---

## Phase 5: K8s Infrastructure

### Task 17: K8s manifests

**Files:**
- Create: `admin/kubernetes/deployment.yaml`
- Create: `admin/kubernetes/service.yaml`
- Create: `admin/kubernetes/rbac.yaml`
- Create: `admin/kubernetes/secret.yaml`

- [ ] **Step 1: Create deployment.yaml** — Admin backend Deployment with ServiceAccount, secret env, hostPath volume, probes, resource limits.

- [ ] **Step 2: Create service.yaml** — ClusterIP Service on port 48082.

- [ ] **Step 3: Create rbac.yaml** — ServiceAccount + Role (scoped to hermes-agent namespace) + RoleBinding. Role grants CRUD on deployments, services, secrets, pods, pods/log, events, configmaps; read/update on ingresses.

- [ ] **Step 4: Create secret.yaml** — Opaque secret with placeholder admin_key.

- [ ] **Step 5: Commit**

```bash
git add admin/kubernetes/
git commit -m "feat(admin): add K8s manifests (deployment, service, RBAC, secret)"
```

---

### Task 18: Dockerfile

**Files:**
- Create: `admin/backend/Dockerfile`

- [ ] **Step 1: Create multi-stage Dockerfile**

Stage 1 (frontend-builder): `node:20-alpine` from Aliyun mirror, install deps with npmmirror, build React SPA with `VITE_BASE_PATH=/admin/`.

Stage 2 (runtime): `python:3.11-slim` from Aliyun mirror, install system deps, pip install with Tsinghua mirror, copy backend source + built frontend static files, non-root user, uvicorn CMD.

- [ ] **Step 2: Verify Dockerfile syntax**

```bash
cd admin && docker build --check -f backend/Dockerfile . 2>/dev/null || echo "Docker build check skipped (no docker daemon)"
```

- [ ] **Step 3: Commit**

```bash
git add admin/backend/Dockerfile
git commit -m "feat(admin): add multi-stage Dockerfile with Aliyun mirrors"
```

---

### Task 19: Deploy scripts

**Files:**
- Create: `admin/kubernetes/deploy.sh`
- Create: `admin/kubernetes/upgrade.sh`
- Create: `admin/kubernetes/uninstall.sh`

- [ ] **Step 1: Create deploy.sh** — 6-step first-deploy script: create secret (with generated key), apply RBAC, apply deployment, apply service, patch ingress (strategic merge for /admin paths), wait for rollout.

- [ ] **Step 2: Create upgrade.sh** — 3-step: build image, push, rollout restart.

- [ ] **Step 3: Create uninstall.sh** — remove /admin ingress paths, delete service/deployment/rbac/secret. Preserves agent deployments.

- [ ] **Step 4: Make scripts executable**

```bash
chmod +x admin/kubernetes/deploy.sh admin/kubernetes/upgrade.sh admin/kubernetes/uninstall.sh
```

- [ ] **Step 5: Commit**

```bash
git add admin/kubernetes/deploy.sh admin/kubernetes/upgrade.sh admin/kubernetes/uninstall.sh
git commit -m "feat(admin): add deploy/upgrade/uninstall scripts"
```

---

## Phase 6: Integration & Verification

### Task 20: End-to-end build and smoke test

**Files:**
- None (verification only)

- [ ] **Step 1: Build frontend and verify output**

```bash
cd admin/frontend && npm run build && ls -la dist/
```

- [ ] **Step 2: Build Docker image (or verify Dockerfile is correct)**

If containerd/nerdctl available:
```bash
cd admin && nerdctl build -t hermes-admin:latest -f backend/Dockerfile .
```
Otherwise verify the Dockerfile references all correct paths.

- [ ] **Step 3: Verify backend starts with static files**

```bash
# Copy frontend dist to backend/static for local testing
mkdir -p admin/backend/static && cp -r admin/frontend/dist/* admin/backend/static/
cd admin/backend && ADMIN_KEY=test123 python -c "
from main import app
print(f'Routes: {len(app.routes)}')
for r in app.routes:
    if hasattr(r, 'path'): print(f'  {r.path}')
"
```

Expected: 30+ routes registered including `/admin/api/agents`, `/admin/api/health`, and SPA fallback.

- [ ] **Step 4: Commit any fixups**

```bash
git add -A admin/ && git commit -m "fix(admin): integration fixes from end-to-end build test"
```

---

## Self-Review Checklist

- [ ] **Spec coverage**: Each of the 28 API endpoints has a route in main.py
- [ ] **Placeholder scan**: No "TBD", "TODO", "implement later" in any file
- [ ] **Type consistency**: Frontend TypeScript types match backend Pydantic model field names
- [ ] **Ingress paths**: `/admin/api` path comes before `/admin` in ingress patch
- [ ] **Auth**: All endpoints require X-Admin-Key header; SSE uses token fallback
- [ ] **Secret masking**: .env read returns `****` for secret keys; backup masks secrets
- [ ] **Atomic writes**: All config writes go through .tmp + os.replace()
- [ ] **i18n**: All UI strings come from translation keys, no hardcoded Chinese/English
