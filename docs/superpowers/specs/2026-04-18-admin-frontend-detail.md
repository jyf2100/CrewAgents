# Hermes Admin Panel -- Frontend Component Architecture

> Detailed design for all React components, state management, API client, i18n, and error handling.
> Follows existing patterns from `web/src/` (Tailwind + shadcn/ui primitives, `useI18n`, `useToast`, `fetchJSON`).

### Dependencies

In addition to the existing `web/` dependencies, the admin panel requires:
- `react-router-dom` -- client-side routing with `BrowserRouter`, `Routes`, `Route`, `useNavigate`, `useParams`, `useSearchParams`

### App Setup

The admin entry point wraps the app in `BrowserRouter` with `basename="/admin"` so all route paths are relative to `/admin`:

```tsx
// admin/frontend/src/App.tsx
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { setAdminKey } from "./lib/admin-api";

function AdminApp() {
  // On mount, restore admin key from localStorage
  useEffect(() => {
    const storedKey = localStorage.getItem("admin_api_key");
    if (storedKey) setAdminKey(storedKey);
  }, []);

  return (
    <BrowserRouter basename="/admin">
      <AdminLayout />
    </BrowserRouter>
  );
}

function AdminLayout() {
  const key = localStorage.getItem("admin_api_key");
  if (!key) return <Routes><Route path="*" element={<LoginPage />} /></Routes>;

  return (
    <>
      <AdminHeader />
      <Routes>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/agents/:id" element={<AgentDetailPage />} />
        <Route path="/create" element={<CreateAgentPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </>
  );
}
```

All pages except LoginPage check for `admin_api_key` in localStorage on mount. If missing, they redirect to `/admin/login`.

---

## 1. Component Tree

```
AdminApp
├── BrowserRouter              (basename="/admin")
├── AdminHeader
│   ├── LanguageSwitcher        (reused from main app)
│   └── AdminNav                (navigation tabs)
├── <Routes>
│   ├── LoginPage               (/admin/login)
│   │   └── PasswordInput       (admin API key)
│   │
│   ├── DashboardPage           (/admin)
│   │   ├── ClusterStatusBar
│   │   │   ├── CpuMemBar
│   │   │   └── DiskBar
│   │   ├── AgentCard[]         (grid)
│   │   │   ├── StatusIndicator
│   │   │   ├── ResourceBar (CPU)
│   │   │   ├── ResourceBar (Memory)
│   │   │   ├── RestartBadge
│   │   │   ├── DetailButton
│   │   │   └── AgentKebabMenu
│   │   │       ├── MenuItem "Restart"
│   │   │       ├── MenuItem "Stop" / "Start"
│   │   │       ├── MenuItem "View Logs"
│   │   │       ├── MenuItem "Delete"
│   │   │       └── MenuItem "Backup"
│   │   └── CreateAgentButton
│   │
│   ├── AgentDetailPage         (/admin/agents/:id)
│   │   ├── AgentHeader
│   │   │   ├── BackButton
│   │   │   ├── AgentStatusBadge
│   │   │   ├── RestartButton
│   │   │   ├── StopStartButton
│   │   │   └── DeleteButton
│   │   └── AgentTabs
│   │       ├── OverviewTab
│   │       │   ├── StatusCard
│   │       │   ├── ResourceSparkline
│   │       │   ├── ConnectedPlatformsList
│   │       │   └── QuickStats
│   │       ├── ConfigTab
│   │       │   ├── ConfigSubTabs
│   │       │   ├── EnvFormEditor
│   │       │   │   ├── EnvRow[]
│   │       │   │   └── AddEnvRowButton
│   │       │   ├── YamlCodeEditor
│   │       │   ├── SoulMarkdownEditor
│   │       │   │   ├── MarkdownTextarea
│   │       │   │   └── MarkdownPreview
│   │       │   ├── ApplyConfigButton
│   │       │   └── DiffPreviewDialog
│   │       ├── LogsTab
│   │       │   ├── LogFilterBar
│   │       │   ├── StreamingLogViewer
│   │       │   └── LogControlBar (pause/resume, clear)
│   │       ├── EventsTab
│   │       │   └── EventsTable
│   │       │       └── EventRow[]
│   │       └── HealthTab
│   │           ├── HealthStatusCard
│   │           ├── ProbeStatus (readiness/liveness)
│   │           └── LastCheckTimestamp
│   │
│   ├── CreateAgentPage         (/admin/create)
│   │   └── CreateWizard
│   │       ├── Step1BasicInfo
│   │       │   ├── AgentNumberInput
│   │       │   ├── DisplayNameInput
│   │       │   └── ResourceLimitFields
│   │       ├── Step2LlmConfig
│   │       │   ├── ProviderSelect
│   │       │   ├── ModelInput
│   │       │   ├── ApiKeyInput
│   │       │   ├── BaseUrlInput
│   │       │   └── TestConnectionButton
│   │       ├── Step3AgentConfig
│   │       │   ├── SoulTextarea
│   │       │   └── EnvVariablesEditor
│   │       │       ├── EnvVarRow[]
│   │       │       └── AddEnvVarButton
│   │       └── Step4Confirm
│   │           ├── SummaryCard
│   │           ├── RawTemplatePreview (collapsible)
│   │           ├── DeployButton
│   │           └── DeployProgressStepper
│   │
│   └── SettingsPage            (/admin/settings)
│       ├── ClusterStatusCard
│       ├── AdminKeyForm
│       ├── DefaultResourceForm
│       └── TemplateEditors
│           ├── TemplateTab "deployment"
│           ├── TemplateTab ".env"
│           ├── TemplateTab "config.yaml"
│           └── TemplateTab "SOUL.md"
│
└── Toast                       (reused from main app)
```

---

## 2. State Management

Each page manages its own state with `useState` / `useEffect` -- no global store. The pattern follows the existing `StatusPage.tsx` approach: local state + polling interval.

### 2.1 State Per Page

#### DashboardPage

```typescript
// DashboardPage.tsx
const [agents, setAgents] = useState<AgentListItem[]>([]);
const [cluster, setCluster] = useState<ClusterStatus | null>(null);
const [loading, setLoading] = useState(true);
const [error, setError] = useState<string | null>(null);

// Auto-refresh every 10s
useEffect(() => {
  const load = async () => {
    try {
      const [agentList, clusterStatus] = await Promise.all([
        adminApi.listAgents(),
        adminApi.getClusterStatus(),
      ]);
      setAgents(agentList);
      setCluster(clusterStatus);
      setError(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  };
  load();
  const interval = setInterval(load, 10_000);
  return () => clearInterval(interval);
}, []);
```

#### AgentDetailPage

```typescript
// AgentDetailPage.tsx
const { id } = useParams<{ id: string }>();
const navigate = useNavigate();
const [searchParams, setSearchParams] = useSearchParams();
const [agent, setAgent] = useState<AgentDetail | null>(null);
const activeTab = (searchParams.get("tab") as "overview" | "config" | "logs" | "events" | "health") ?? "overview";
const setActiveTab = (tab: string) => setSearchParams({ tab });
const [loading, setLoading] = useState(true);
const { toast, showToast } = useToast();

// Load agent detail
useEffect(() => {
  adminApi.getAgent(id).then(setAgent).catch(() => showToast("...", "error"));
}, [id]);

// Action handlers
const handleRestart = async () => { ... };
const handleStop = async () => { ... };
const handleStart = async () => { ... };
```

#### CreateAgentPage

```typescript
// CreateAgentPage.tsx
const [step, setStep] = useState(1);
const [formData, setFormData] = useState<CreateAgentForm>({
  agentNumber: 1,
  displayName: "",
  cpuLimit: "1000m",
  memoryLimit: "1Gi",
  provider: "openrouter",
  model: "anthropic/claude-sonnet-4-20250514",
  apiKey: "",
  baseUrl: "https://openrouter.ai/api/v1",
  soul: "",
  envVars: [{ key: "", value: "" }],
});
const [deploying, setDeploying] = useState(false);
const [deploySteps, setDeploySteps] = useState<DeployStep[]>([]);
const [templates, setTemplates] = useState<Templates | null>(null);
const navigate = useNavigate();
const { toast, showToast } = useToast();
```

#### SettingsPage

```typescript
// SettingsPage.tsx
const [settings, setSettings] = useState<AdminSettings>({
  admin_key_masked: "",
  default_cpu_limit: "1000m",
  default_memory_limit: "1Gi",
});
const [clusterStatus, setClusterStatus] = useState<ClusterStatus | null>(null);
const [templates, setTemplates] = useState<Templates | null>(null);
const [saving, setSaving] = useState(false);
const { toast, showToast } = useToast();
```

### 2.2 API Call Organization

All API calls are centralized in `adminApi` (section 7). Each page calls `adminApi.*` directly in `useEffect` or event handlers -- no middleware, no React Query. This matches the existing `api.ts` pattern.

---

## 3. Dashboard Page -- Detailed Component Layout

### 3.1 Types

```typescript
interface AgentListItem {
  id: string;                    // e.g. "hermes-gateway-1"
  agent_number: number;          // e.g. 1
  display_name: string | null;
  status: "running" | "stopped" | "starting" | "failed" | "unknown";
  replicas: number;
  ready_replicas: number;
  restart_count: number;
  cpu_usage: number;             // e.g. 0.12 (fraction of limit, display as "12%")
  memory_usage: number;          // e.g. 838860800 (bytes, display as "800M")
  cpu_limit: number;             // e.g. 1 (cores, display as "1000m")
  memory_limit: number;          // e.g. 1073741824 (bytes, display as "1Gi")
  created_at: string;            // ISO timestamp
  ingress_path: string;          // e.g. "/agent1"
  pod_ip: string | null;
  node_name: string | null;
}

// Display formatting helpers (frontend only):
// cpuUsagePercent(agent.cpu_usage) => `${(agent.cpu_usage * 100).toFixed(0)}%`
// memoryHuman(agent.memory_usage) => human-readable bytes (e.g. "800M")
// cpuLimitHuman(agent.cpu_limit) => `${agent.cpu_limit * 1000}m`
// memoryLimitHuman(agent.memory_limit) => human-readable bytes (e.g. "1Gi")

interface ClusterStatus {
  node_name: string;             // e.g. "roc-epyc"
  cpu_usage_percent: number;     // e.g. 68
  cpu_total: string;             // e.g. "8"
  memory_used: string;           // e.g. "4.2Gi"
  memory_total: string;          // e.g. "8Gi"
  memory_usage_percent: number;
  disk_used: string;             // e.g. "149G"
  disk_total: string;           // e.g. "234G"
  disk_usage_percent: number;
  agent_count: number;
  running_count: number;
}
```

### 3.2 ClusterStatusBar

```typescript
// ClusterStatusBar.tsx
interface ClusterStatusBarProps {
  cluster: ClusterStatus;
}
```

Layout (horizontal strip):
```
┌──────────────────────────────────────────────────────────────┐
│ Cluster: roc-epyc  │  CPU ██████░░░░ 68%  │  Mem 4.2/8Gi (53%)  │  Disk 149/234G (64%)  │  Agents: 4 运行中 / 6 总计  │
└──────────────────────────────────────────────────────────────┘
```

- `CpuMemBar`: `width` set to `${cluster.cpu_usage_percent}%`, color-coded: green < 70%, yellow < 90%, red >= 90%.
- `DiskBar`: same pattern.

### 3.3 AgentCard

```typescript
// AgentCard.tsx
interface AgentCardProps {
  agent: AgentListItem;
  onDetail: (id: string) => void;
  onRestart: (id: string) => void;
  onStopStart: (id: string, action: "stop" | "start") => void;
  onViewLogs: (id: string) => void;
  onBackup: (id: string) => void;
}
```

Card internal layout:
```
┌──────────────────────────┐
│ ● 运行中  hermes-gateway-1│
│                          │
│ CPU  ██████░░░░ 120m/1   │
│ Mem  ███░░░░░░░ 400M/1Gi │
│                          │
│ Restarts: 0  │  2h 前    │
│                          │
│ [详情]         [...]  ▼   │
└──────────────────────────┘
```

- `StatusIndicator`: colored dot (green/red/yellow/gray) + status text from i18n.
- `ResourceBar`: thin progress bar with `bg-primary/20` track and colored fill. Label shows usage/limit.
- `RestartBadge`: if `restart_count > 0`, show red `Badge` variant `"destructive"` with count.
- Time display uses `timeAgo(agent.created_at)`.
- "详情" is a `Button variant="outline" size="sm"`.
- `[...]` is a kebab menu using native HTML `<details>/<summary>` + positioned dropdown (no radix dependency needed; matches project's minimal-dependency style). Items call `props.onRestart`, `props.onStopStart`, etc.

### 3.4 Kebab Menu Actions

```typescript
// AgentKebabMenu.tsx -- inline in AgentCard
interface AgentKebabMenuProps {
  agent: AgentListItem;
  onRestart: () => void;
  onStopStart: () => void;
  onViewLogs: () => void;
  onBackup: () => void;
  onDelete: () => void;
}
```

Items (conditionally shown):
| Menu Item | Shown When | Action |
|-----------|-----------|--------|
| 重启 (Restart) | Always | `adminApi.restartAgent(agent.id)` |
| 停止 (Stop) | `status === "running"` | `adminApi.stopAgent(agent.id)` |
| 启动 (Start) | `status === "stopped"` | `adminApi.startAgent(agent.id)` |
| 查看日志 (View Logs) | Always | `navigate(\`/admin/agents/${agent.id}\`)` with tab=logs |
| 删除 (Delete) | Always | Show `ConfirmDialog` then `adminApi.deleteAgent(agent.id)` |
| 备份 (Backup) | Always | `adminApi.backupAgent(agent.id)` -> download blob |

Delete action flow:
1. User clicks "删除" in the kebab menu.
2. A `ConfirmDialog` appears with `variant="destructive"`, message: `t.admin.confirmDelete`.
3. Optionally offer "删除前备份" checkbox which calls `adminApi.backupAgent()` first.
4. On confirm, call `adminApi.deleteAgent(agent.id)`.
5. On success, show toast and navigate back to dashboard.

Each action shows a loading spinner on the menu item while the API call is in flight, then shows toast on success/failure.

### 3.5 Grid Layout

```tsx
<div className="grid gap-4 grid-cols-1 sm:grid-cols-2 lg:grid-cols-3">
  {agents.map((agent) => (
    <AgentCard key={agent.id} agent={agent} ... />
  ))}
  {/* "Create" card -- dashed border, centered "+" icon */}
  <CreateAgentButton onClick={() => navigate("/admin/create")} />
</div>
```

Agents sorted by status priority: `failed` > `starting` > `stopped` > `running` > `unknown`.

---

## 4. Agent Detail Page

### 4.1 AgentHeader

```typescript
interface AgentHeaderProps {
  agent: AgentDetail;
  onBack: () => void;
  onRestart: () => void;
  onStopStart: () => void;
  onDelete: () => void;
  restarting: boolean;
  togglingState: boolean;
}
```

Layout:
```
┌─────────────────────────────────────────────────────────────┐
│ ← 返回   hermes-gateway-1   ● 运行中   [重启] [停止] [删除] │
└─────────────────────────────────────────────────────────────┘
```

- Delete button: `Button variant="destructive" size="sm"`. Shows `ConfirmDialog` on click. On confirm, calls `adminApi.deleteAgent(agent.id)` and navigates to `/admin` on success.

- Back button: `navigate("/admin")`.
- Status badge: same `StatusIndicator` from dashboard.
- Action buttons disabled while their async operation is in flight.

### 4.2 Tabs Structure

Tab navigation uses `Button variant="ghost"` buttons in a horizontal row with underline indicator (matching `App.tsx` nav pattern). No radix Tabs component -- keep it lightweight.

```tsx
const TABS = [
  { id: "overview", labelKey: "overview" },
  { id: "config", labelKey: "config" },
  { id: "logs", labelKey: "logs" },
  { id: "events", labelKey: "events" },
  { id: "health", labelKey: "health" },
] as const;
```

Tab state is stored in the URL search param to allow deep-linking. Uses `useSearchParams()` from `react-router-dom`:

```tsx
const [searchParams, setSearchParams] = useSearchParams();
const activeTab = (searchParams.get("tab") as typeof TABS[number]["id"]) ?? "overview";

// When a tab is clicked:
const handleTabChange = (tabId: string) => {
  setSearchParams({ tab: tabId }, { replace: true });
};
```

This means URLs like `/admin/agents/hermes-gateway-1?tab=logs` link directly to the logs tab. The "View Logs" kebab menu item navigates with `?tab=logs`.

### 4.3 OverviewTab

```typescript
interface OverviewTabProps {
  agent: AgentDetail;
}
```

Layout (2-column grid on `sm+`):
```
┌─────────────────┐  ┌──────────────────────┐
│ Status Card      │  │ Resource Usage        │
│ Pod: 10.244.0.5  │  │ CPU sparkline graph   │
│ Node: roc-epyc   │  │ Mem sparkline graph   │
│ Age: 2h          │  │                      │
│ Replicas: 1/1    │  │                      │
└─────────────────┘  └──────────────────────┘
┌─────────────────┐  ┌──────────────────────┐
│ Platforms        │  │ Quick Stats           │
│ ● discord ─── ✓  │  │ Sessions: 12          │
│ ● telegram ── ✓  │  │ Messages: 1,240       │
│                  │  │ Tokens: 89,500        │
└─────────────────┘  └──────────────────────┘
```

`ResourceSparkline` -- renders a simple SVG polyline from `agent.resource_history` (last 60 data points). No chart library dependency; the existing project uses no charting libs.

### 4.4 ConfigTab

```typescript
interface ConfigTabProps {
  agentId: string;
}

// Internal state
const [subTab, setSubTab] = useState<"env" | "config" | "soul">("env");
const [envVars, setEnvVars] = useState<EnvVarPair[]>([]);
const [yamlText, setYamlText] = useState("");
const [soulText, setSoulText] = useState("");
const [soulPreview, setSoulPreview] = useState(false);
const [saving, setSaving] = useState(false);
const [showDiff, setShowDiff] = useState(false);
```

#### EnvFormEditor

```typescript
interface EnvVarPair {
  key: string;
  value: string;      // masked value from API, e.g. "****abcd"
  is_secret: boolean;
  is_new: boolean;    // for newly added rows
  deleted: boolean;   // soft-delete for existing rows
}

interface EnvFormEditorProps {
  vars: EnvVarPair[];
  onChange: (vars: EnvVarPair[]) => void;
  readOnly: boolean;
}
```

Each row:
```
┌──────────────────────────────────────────────────┐
│ API_KEY    [••••••••abcd]  [显示] [删除]           │
│ CUSTOM_VAR [enter value... ]          [删除]       │
│                                  [+ 添加变量]      │
└──────────────────────────────────────────────────┘
```

- "显示" button: calls `adminApi.revealEnvVar(agentId, key)` to fetch actual value.
- Secret fields show `type="password"` input by default.
- "添加变量" appends `{ key: "", value: "", is_secret: false, is_new: true }`.
- "删除" marks existing vars as `deleted: true` (grayed out) or removes new rows entirely.

#### YamlCodeEditor

```tsx
<textarea
  className="flex min-h-[500px] w-full bg-transparent px-4 py-3 text-sm font-mono
             leading-relaxed border-t border-border focus-visible:outline-none"
  value={yamlText}
  onChange={(e) => setYamlText(e.target.value)}
  spellCheck={false}
/>
```

Plain `<textarea>` with `font-mono` -- matches existing `ConfigPage.tsx` YAML mode. No CodeMirror/Monaco dependency.

#### SoulMarkdownEditor

```typescript
interface SoulMarkdownEditorProps {
  value: string;
  onChange: (value: string) => void;
}
```

Split view: left is `<textarea>`, right is rendered preview. Preview renders the markdown as plain text in a `<pre>` block with basic formatting (headings rendered larger, code blocks monospaced) -- no markdown library needed for v1.

#### Apply Flow

1. User clicks "Apply" button.
2. Show diff: old value vs new value in a modal dialog (custom `<dialog>` or overlay `div`).
3. On confirm, call the appropriate API:
   - env changes: `adminApi.updateAgentEnv(agentId, changedVars)`
   - yaml changes: `adminApi.updateAgentConfig(agentId, yamlText)`
   - soul changes: `adminApi.updateAgentSoul(agentId, soulText)`
4. Show toast on success/failure.
5. Backend auto-restarts the agent after config change.

### 4.5 LogsTab

```typescript
interface LogsTabProps {
  agentId: string;
}
```

Uses SSE via `EventSource`. Because `EventSource` does not support custom headers, authentication is handled via a short-lived token obtained from a REST endpoint:

```typescript
const [lines, setLines] = useState<string[]>([]);
const [paused, setPaused] = useState(false);
const [filterLevel, setFilterLevel] = useState<string>("ALL");
const [searchText, setSearchText] = useState("");
const scrollRef = useRef<HTMLDivElement>(null);
const eventSourceRef = useRef<EventSource | null>(null);
const navigate = useNavigate();

useEffect(() => {
  if (paused) return;

  let retries = 0;

  async function connect() {
    // Step 1: Get a short-lived SSE token via authenticated REST call
    let token: string;
    try {
      const res = await adminFetch<{ token: string }>(`/agents/${encodeURIComponent(agentId)}/logs/token`, {
        method: "POST",
      });
      token = res.token;
    } catch (e) {
      if (e instanceof AdminApiError && e.status === 401) {
        // Auth failed -- redirect to login
        localStorage.removeItem("admin_api_key");
        navigate("/admin/login");
        return;
      }
      // Retry on other errors
      retries++;
      if (retries < 5) setTimeout(connect, 2000 * retries);
      return;
    }

    // Step 2: Open EventSource with token as query param
    const url = `${ADMIN_BASE}/agents/${encodeURIComponent(agentId)}/logs?token=${encodeURIComponent(token)}`;
    const es = new EventSource(url);

    es.onmessage = (e) => {
      setLines((prev) => [...prev.slice(-499), e.data]);  // keep last 500
      // auto-scroll
      requestAnimationFrame(() => {
        scrollRef.current?.scrollTo(0, scrollRef.current.scrollHeight);
      });
    };

    es.onerror = () => {
      es.close();
      // If the error is likely a 401 (token expired), try to reconnect
      retries++;
      if (retries < 5) {
        setTimeout(connect, 2000 * retries);  // backoff and get a new token
      }
    };

    eventSourceRef.current = es;
  }

  connect();
  return () => eventSourceRef.current?.close();
}, [agentId, paused]);
```

Log viewer layout:
```
┌─────────────────────────────────────────────────┐
│ [级别: ALL ▾] [搜索: ______] [暂停/继续] [清除] │
├─────────────────────────────────────────────────┤
│ 2026-04-18 10:23:01 INFO  gateway: connected...  │
│ 2026-04-18 10:23:02 DEBUG agent: processing...   │
│ 2026-04-18 10:23:03 ERROR tools: timeout...      │
│ ...                                              │
└─────────────────────────────────────────────────┘
```

Log line classification (same pattern as `LogsPage.tsx`): `classifyLine()` returns `"error" | "warning" | "info" | "debug"` and maps to color classes.

### 4.6 EventsTab

```typescript
interface K8sEvent {
  type: "Normal" | "Warning";
  reason: string;
  message: string;
  count: number;
  first_timestamp: string;
  last_timestamp: string;
  source: string;
}

interface EventsTabProps {
  agentId: string;
}
```

Table columns:
| Column | Width | Styling |
|--------|-------|---------|
| Type | 80px | `Badge variant="destructive"` for Warning, `variant="outline"` for Normal |
| Reason | 150px | monospace |
| Message | flex | text-sm, word-break |
| Count | 60px | tabular-nums |
| Age | 80px | `timeAgo(last_timestamp)` |

Auto-refresh every 10s. Warning rows: `bg-warning/5`.

### 4.7 HealthTab

```typescript
interface HealthResponse {
  status: "healthy" | "degraded" | "unhealthy";
  gateway_health: Record<string, unknown> | null;  // proxied /health response
  readiness: "passing" | "failing" | "unknown";
  liveness: "passing" | "failing" | "unknown";
  last_check: string;  // ISO timestamp
  details: string | null;
}
```

Layout:
```
┌─────────────────────────────────────┐
│ Overall: ● Healthy                  │
│                                     │
│ Readiness Probe: ● Passing          │
│ Liveness Probe:   ● Passing         │
│                                     │
│ Gateway /health Response:           │
│ { "status": "ok", ... }             │
│                                     │
│ Last Check: 2026-04-18 10:30:00     │
│ [刷新]                               │
└─────────────────────────────────────┘
```

---

## 5. Create Agent Wizard

### 5.1 Form State

```typescript
interface CreateAgentForm {
  // Step 1
  agentNumber: number;
  displayName: string;
  cpuLimit: string;
  memoryLimit: string;

  // Step 2
  provider: LlmProvider;
  model: string;
  apiKey: string;
  baseUrl: string;

  // Step 3
  soul: string;
  envVars: Array<{ key: string; value: string }>;
}

type LlmProvider = "openrouter" | "anthropic" | "openai" | "gemini" | "zhipuai" | "custom";

interface DeployStep {
  label: string;
  status: "pending" | "running" | "done" | "error";
  detail?: string;
}

const PROVIDER_DEFAULTS: Record<LlmProvider, { model: string; baseUrl: string }> = {
  openrouter: { model: "anthropic/claude-sonnet-4-20250514", baseUrl: "https://openrouter.ai/api/v1" },
  anthropic:  { model: "claude-sonnet-4-20250514", baseUrl: "https://api.anthropic.com/v1" },
  openai:     { model: "gpt-4o", baseUrl: "https://api.openai.com/v1" },
  gemini:     { model: "gemini-2.0-flash", baseUrl: "https://generativelanguage.googleapis.com/v1beta" },
  zhipuai:    { model: "glm-4-plus", baseUrl: "https://open.bigmodel.cn/api/paas/v4" },
  custom:     { model: "", baseUrl: "" },
};
```

### 5.2 Step 1: Basic Info

```typescript
interface Step1BasicInfoProps {
  form: CreateAgentForm;
  onChange: (update: Partial<CreateAgentForm>) => void;
}
```

Fields:
| Field | Component | Default | Validation |
|-------|-----------|---------|------------|
| Agent Number | `<Input type="number" min={1} />` | auto-increment from `agents.length + 1` | Required, integer >= 1, must not conflict with existing agent numbers |
| Display Name | `<Input type="text" />` | `""` | Optional, max 64 chars |
| CPU Limit | `<Input type="text" />` | `"1000m"` | Required, matches regex `^\d+m?$` |
| Memory Limit | `<Input type="text" />` | `"1Gi"` | Required, matches regex `^\d+(Ki|Mi|Gi)$` |

Validation runs on "Next" click. Errors shown as red text below the field.

### 5.3 Step 2: LLM Config

```typescript
interface Step2LlmConfigProps {
  form: CreateAgentForm;
  onChange: (update: Partial<CreateAgentForm>) => void;
}
```

Fields:
| Field | Component | Default | Validation |
|-------|-----------|---------|------------|
| Provider | `<select>` with `Button` group (like `FilterBar` in LogsPage) | `"openrouter"` | Required |
| Model | `<Input type="text" />` | auto-filled from provider | Required, non-empty |
| API Key | `<Input type="password" />` | `""` | Required, non-empty |
| Base URL | `<Input type="text" />` | auto-filled from provider, editable | Required for custom, auto for others |

"测试连接" button:
```typescript
const [testResult, setTestResult] = useState<"idle" | "testing" | "success" | "failure">("idle");
const [testLatency, setTestLatency] = useState<number | null>(null);

const handleTestConnection = async () => {
  setTestResult("testing");
  const start = Date.now();
  try {
    await adminApi.testLlmConnection({
      provider: form.provider,
      model: form.model,
      api_key: form.apiKey,
      base_url: form.baseUrl,
    });
    setTestLatency(Date.now() - start);
    setTestResult("success");
  } catch (e) {
    setTestResult("failure");
  }
};
```

Shows result inline: green "连接成功 (234ms)" or red "连接失败: <error message>".

### 5.4 Step 3: Agent Config

```typescript
interface Step3AgentConfigProps {
  form: CreateAgentForm;
  onChange: (update: Partial<CreateAgentForm>) => void;
  template: string;  // default SOUL.md template from API
}
```

- SOUL.md textarea: pre-filled from template loaded via `adminApi.getTemplates()`.
- Env variables: same `EnvVarRow` pattern as config tab, but all rows are new (no masked values).

Validation: SOUL.md is optional. Env var keys must be unique and match `[A-Z_][A-Z0-9_]*`.

### 5.5 Step 4: Confirm & Deploy

```typescript
interface Step4ConfirmProps {
  form: CreateAgentForm;
  templates: GeneratedTemplates;  // rendered templates for preview
  onDeploy: () => void;
  deploying: boolean;
  deploySteps: DeployStep[];
}
```

Summary card shows all entered values in a read-only `Card`:

```
┌────────────────────────────────────────┐
│ Agent: hermes-gateway-4                │
│ Display Name: My Agent                 │
│ CPU: 1000m  Memory: 1Gi                │
│ Provider: OpenRouter                   │
│ Model: claude-sonnet-4-20250514        │
│ Base URL: https://openrouter.ai/api/v1 │
│ API Key: ****abcd                      │
│ SOUL.md: (158 chars)                   │
│ Extra env vars: 2                      │
└────────────────────────────────────────┘
```

Collapsible "查看原始模板" section with sub-tabs showing the 4 generated files: deployment.yaml, .env, config.yaml, SOUL.md.

Deploy button triggers:

```typescript
const handleDeploy = async () => {
  setDeploying(true);
  const steps: DeployStep[] = [
    { label: t.admin.creatingSecret, status: "pending" },
    { label: t.admin.initializingData, status: "pending" },
    { label: t.admin.creatingDeployment, status: "pending" },
    { label: t.admin.updatingIngress, status: "pending" },
    { label: t.admin.waitingForReady, status: "pending" },
  ];
  setDeploySteps(steps);

  try {
    const result = await adminApi.createAgent({
      agent_number: form.agentNumber,
      display_name: form.displayName || null,
      cpu_limit: form.cpuLimit,
      memory_limit: form.memoryLimit,
      provider: form.provider,
      model: form.model,
      api_key: form.apiKey,
      base_url: form.baseUrl,
      soul: form.soul,
      env_vars: Object.fromEntries(form.envVars.filter(v => v.key).map(v => [v.key, v.value])),
    });

    // Poll for deployment readiness
    // ... (or backend does it synchronously and returns when ready)

    // All steps done
    setDeploySteps(steps.map(s => ({ ...s, status: "done" })));
    setTimeout(() => navigate(`/admin/agents/hermes-gateway-${form.agentNumber}`), 500);
  } catch (e) {
    // Mark current step as error
    showToast(`${t.admin.deployFailed}: ${e}`, "error");
  } finally {
    setDeploying(false);
  }
};
```

Deploy progress stepper shows each step with an icon:
- `pending`: gray circle
- `running`: spinning loader
- `done`: green checkmark
- `error`: red X

---

## 6. Settings Page

### 6.1 Types

```typescript
interface AdminSettings {
  admin_key_masked: string;      // current key (masked, e.g. "****abcd")
  default_cpu_limit: string;
  default_memory_limit: string;
}

interface Templates {
  deployment: string;            // YAML template
  env: string;                   // .env template
  config: string;                // config.yaml template
  soul: string;                  // SOUL.md template
}
```

### 6.2 Form Fields

| Section | Field | Component | Save Action |
|---------|-------|-----------|-------------|
| Cluster Status | Read-only display | `ClusterStatusCard` | N/A |
| Admin API Key | Current key (masked) | `<Input disabled />` | Displays `settings.admin_key_masked` |
| Admin API Key | New key | `<Input type="password" />` | `adminApi.changeAdminKey(newKey)` |
| Admin API Key | Confirm new key | `<Input type="password" />` | Client-side match validation |
| Default Resources | CPU limit | `<Input />` | `adminApi.updateSettings({ default_cpu_limit, default_memory_limit })` |
| Default Resources | Memory limit | `<Input />` | `adminApi.updateSettings({ default_cpu_limit, default_memory_limit })` |
| Templates | Deployment template | `<textarea font-mono />` | `adminApi.updateTemplate("deployment", text)` |
| Templates | .env template | `<textarea font-mono />` | `adminApi.updateTemplate("env", text)` |
| Templates | config.yaml template | `<textarea font-mono />` | `adminApi.updateTemplate("config", text)` |
| Templates | SOUL.md template | `<textarea />` | `adminApi.updateTemplate("soul", text)` |

### 6.3 Save Flow

1. All fields are editable at once (single-page form, not wizard).
2. "Save" button in header (same pattern as `ConfigPage.tsx`).
3. On save:
   - Validate required fields client-side.
   - Call API endpoints for changed fields only.
   - Show single toast "设置已保存" on success.
   - Show per-field error toasts on failure.
4. Admin key change requires confirmation dialog (custom overlay):
   - "更改 Admin Key 将要求使用新密钥重新登录。确定？"
   - On confirm, call API, then update the stored key in memory.

---

## 7. API Client

### 7.1 Full TypeScript API Client

File: `admin/frontend/src/lib/admin-api.ts`

```typescript
// ── Base Setup ──────────────────────────────────────────────────────────

const ADMIN_BASE = "/admin/api";

let _adminKey: string | null = null;

export function setAdminKey(key: string) {
  _adminKey = key;
}

export function getAdminKey(): string | null {
  return _adminKey;
}

async function adminFetch<T>(url: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    ...(init?.headers as Record<string, string> ?? {}),
  };
  if (_adminKey) {
    headers["X-Admin-Key"] = _adminKey;
  }
  const res = await fetch(`${ADMIN_BASE}${url}`, {
    ...init,
    headers,
  });
  if (!res.ok) {
    if (res.status === 401) {
      // Clear stored key and redirect to login
      localStorage.removeItem("admin_api_key");
      _adminKey = null;
      window.location.href = "/admin/login";
    }
    const text = await res.text().catch(() => res.statusText);
    const error = new AdminApiError(res.status, text);
    throw error;
  }
  // For backup endpoint, return blob instead of JSON
  if (init?.headers && (init.headers as Record<string, string>)["Accept"] === "application/octet-stream") {
    return res.blob() as unknown as T;
  }
  return res.json();
}

class AdminApiError extends Error {
  status: number;
  constructor(status: number, body: string) {
    super(`${status}: ${body}`);
    this.status = status;
    this.name = "AdminApiError";
  }
}

// ── Type Definitions ────────────────────────────────────────────────────

// -- Agent Types --

export interface AgentListItem {
  id: string;
  agent_number: number;
  display_name: string | null;
  status: "running" | "stopped" | "starting" | "failed" | "unknown";
  replicas: number;
  ready_replicas: number;
  restart_count: number;
  cpu_usage: number;           // fraction of limit (e.g. 0.12), format as "12%" in UI
  memory_usage: number;        // bytes (e.g. 838860800), format as "800M" in UI
  cpu_limit: number;           // cores (e.g. 1), format as "1000m" in UI
  memory_limit: number;        // bytes (e.g. 1073741824), format as "1Gi" in UI
  created_at: string;
  ingress_path: string;
  pod_ip: string | null;
  node_name: string | null;
}

export interface AgentDetail {
  id: string;
  agent_number: number;
  display_name: string | null;
  status: "running" | "stopped" | "starting" | "failed" | "unknown";
  replicas: number;
  ready_replicas: number;
  restart_count: number;
  created_at: string;
  ingress_path: string;
  pod_ip: string | null;
  node_name: string | null;
  labels: Record<string, string>;
  // Resources
  resources: AgentResources;
  resource_history: ResourceDataPoint[];
  // Config
  config_yaml: string;
  env_vars: EnvVarEntry[];
  soul_md: string;
  // Health
  health: HealthResponse;
}

export interface AgentResources {
  cpu_usage: number;           // fraction of limit (e.g. 0.12), consistent with AgentListItem
  cpu_limit: number;           // cores (e.g. 1), format as "1000m" in UI
  memory_usage: number;        // bytes (e.g. 838860800), consistent with AgentListItem
  memory_limit: number;        // bytes (e.g. 1073741824), format as "1Gi" in UI
}

export interface ResourceDataPoint {
  timestamp: string;
  cpu_usage: number;           // fraction at that point in time
  memory_usage: number;        // bytes at that point in time
}

export interface EnvVarEntry {
  key: string;
  value: string;                 // masked, e.g. "****abcd"
  is_secret: boolean;
}

export interface HealthResponse {
  status: "healthy" | "degraded" | "unhealthy";
  gateway_health: Record<string, unknown> | null;
  readiness: "passing" | "failing" | "unknown";
  liveness: "passing" | "failing" | "unknown";
  last_check: string;
  details: string | null;
}

// -- Cluster Types --

export interface ClusterStatus {
  node_name: string;
  cpu_usage_percent: number;
  cpu_total: string;
  memory_used: string;
  memory_total: string;
  memory_usage_percent: number;
  disk_used: string;
  disk_total: string;
  disk_usage_percent: number;
  agent_count: number;
  running_count: number;
}

// -- K8s Event Types --

export interface K8sEvent {
  type: "Normal" | "Warning";
  reason: string;
  message: string;
  count: number;
  first_timestamp: string;
  last_timestamp: string;
  source: string;
}

// -- Create Agent Types --

export type LlmProvider = "openrouter" | "anthropic" | "openai" | "gemini" | "zhipuai" | "custom";

export interface CreateAgentRequest {
  agent_number: number;
  display_name: string | null;
  cpu_limit: string;
  memory_limit: string;
  provider: LlmProvider;
  model: string;
  api_key: string;
  base_url: string;
  soul: string;
  env_vars: Record<string, string>;
}

export interface CreateAgentResponse {
  id: string;
  agent_number: number;
  status: string;
  message: string;
}

// -- LLM Test Types --

export interface TestLlmRequest {
  provider: LlmProvider;
  model: string;
  api_key: string;
  base_url: string;
}

export interface TestLlmResponse {
  success: boolean;
  latency_ms: number;
  error: string | null;
  model_info: string | null;
}

// -- Template Types --

export interface Templates {
  deployment: string;
  env: string;
  config: string;
  soul: string;
}

// -- Settings Types --

export interface AdminSettings {
  admin_key_masked: string;
  default_cpu_limit: string;
  default_memory_limit: string;
}

export interface UpdateSettingsRequest {
  admin_key?: string;
  default_cpu_limit?: string;
  default_memory_limit?: string;
}

// -- Config Update Types --

export interface UpdateEnvRequest {
  vars: Array<{ key: string; value: string; deleted?: boolean }>;
}

export interface UpdateConfigResponse {
  ok: boolean;
  restarted: boolean;
  message: string;
}

// -- Deploy Step Types --

export interface DeployProgress {
  steps: Array<{
    label: string;
    status: "pending" | "running" | "done" | "error";
    detail?: string;
  }>;
}

// ── API Methods ─────────────────────────────────────────────────────────

export const adminApi = {

  // -- Auth --
  login: (key: string) => {
    setAdminKey(key);
    return adminFetch<{ ok: boolean }>("/agents");
  },

  /** Get a short-lived token for SSE log streaming (EventSource cannot send headers) */
  getLogsToken: (agentId: string) =>
    adminFetch<{ token: string }>(`/agents/${encodeURIComponent(agentId)}/logs/token`, {
      method: "POST",
    }),

  // -- Agent CRUD --
  listAgents: () =>
    adminFetch<AgentListItem[]>("/agents"),

  getAgent: (id: string) =>
    adminFetch<AgentDetail>(`/agents/${encodeURIComponent(id)}`),

  createAgent: (req: CreateAgentRequest) =>
    adminFetch<CreateAgentResponse>("/agents", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    }),

  deleteAgent: (id: string, backup = false) =>
    adminFetch<{ ok: boolean }>(`/agents/${encodeURIComponent(id)}?backup=${backup}`, {
      method: "DELETE",
    }),

  restartAgent: (id: string) =>
    adminFetch<{ ok: boolean }>(`/agents/${encodeURIComponent(id)}/restart`, {
      method: "POST",
    }),

  stopAgent: (id: string) =>
    adminFetch<{ ok: boolean }>(`/agents/${encodeURIComponent(id)}/stop`, {
      method: "POST",
    }),

  startAgent: (id: string) =>
    adminFetch<{ ok: boolean }>(`/agents/${encodeURIComponent(id)}/start`, {
      method: "POST",
    }),

  // -- Agent Config --
  getAgentConfig: (id: string) =>
    adminFetch<{ yaml: string }>(`/agents/${encodeURIComponent(id)}/config`),

  updateAgentConfig: (id: string, yaml: string) =>
    adminFetch<UpdateConfigResponse>(`/agents/${encodeURIComponent(id)}/config`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ yaml }),
    }),

  getAgentEnv: (id: string) =>
    adminFetch<EnvVarEntry[]>(`/agents/${encodeURIComponent(id)}/env`),

  updateAgentEnv: (id: string, vars: Array<{ key: string; value: string; deleted?: boolean }>) =>
    adminFetch<UpdateConfigResponse>(`/agents/${encodeURIComponent(id)}/env`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ vars }),
    }),

  revealEnvVar: (id: string, key: string) =>
    adminFetch<{ key: string; value: string }>(`/agents/${encodeURIComponent(id)}/env/reveal`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key }),
    }),

  getAgentSoul: (id: string) =>
    adminFetch<{ content: string }>(`/agents/${encodeURIComponent(id)}/soul`),

  updateAgentSoul: (id: string, content: string) =>
    adminFetch<UpdateConfigResponse>(`/agents/${encodeURIComponent(id)}/soul`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    }),

  // -- Agent Monitoring --
  getAgentHealth: (id: string) =>
    adminFetch<HealthResponse>(`/agents/${encodeURIComponent(id)}/health`),

  getAgentEvents: (id: string) =>
    adminFetch<K8sEvent[]>(`/agents/${encodeURIComponent(id)}/events`),

  getAgentResources: (id: string) =>
    adminFetch<{ current: AgentResources; history: ResourceDataPoint[] }>(`/agents/${encodeURIComponent(id)}/resources`),

  /** Returns EventSource URL for SSE streaming with short-lived token.
   *  Caller should first call getLogsToken(id) to obtain a token, then construct:
   *  `new EventSource(getAgentLogsUrl(id, token))` */
  getAgentLogsUrl: (id: string, token: string) =>
    `${ADMIN_BASE}/agents/${encodeURIComponent(id)}/logs?token=${encodeURIComponent(token)}`,

  // -- Agent Operations --
  backupAgent: (id: string) =>
    adminFetch<Blob>(`/agents/${encodeURIComponent(id)}/backup`, {
      method: "POST",
      headers: { Accept: "application/octet-stream" },
    }) as unknown as Promise<Blob>,

  // -- Cluster --
  getClusterStatus: () =>
    adminFetch<ClusterStatus>("/cluster/status"),

  // -- Settings --
  getSettings: () =>
    adminFetch<AdminSettings>("/settings"),

  updateSettings: (req: UpdateSettingsRequest) =>
    adminFetch<{ ok: boolean }>("/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    }),

  changeAdminKey: (newKey: string) =>
    adminFetch<{ ok: boolean }>("/settings/admin-key", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ admin_key: newKey }),
    }),

  // -- Templates --
  getTemplate: (type: string) =>
    adminFetch<{ content: string }>(`/templates/${encodeURIComponent(type)}`),

  updateTemplate: (type: string, content: string) =>
    adminFetch<{ ok: boolean }>(`/templates/${encodeURIComponent(type)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    }),

  // -- LLM Test --
  testLlmConnection: (req: TestLlmRequest) =>
    adminFetch<TestLlmResponse>("/test-llm-connection", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    }),
};
```

---

## 8. i18n -- Admin Namespace Translations

These are appended to the existing `Translations` type as an `admin` namespace and merged into `zh.ts` / `en.ts`.

### 8.1 Type Addition (types.ts)

```typescript
// Append to the Translations interface:

admin: {
  // Shell
  title: string;
  navDashboard: string;
  navSettings: string;

  // Dashboard
  cluster: string;
  agents: string;
  runningCount: string;
  totalCount: string;
  agentCount: string;
  cpuUsage: string;
  memUsage: string;
  diskUsage: string;
  restarts: string;
  ago: string;
  detail: string;
  newAgent: string;

  // Status
  statusRunning: string;
  statusStopped: string;
  statusStarting: string;
  statusFailed: string;
  statusUnknown: string;

  // Actions
  restart: string;
  restarting: string;
  stop: string;
  stopping: string;
  start: string;
  starting: string;
  delete: string;
  backup: string;
  backingUp: string;
  viewLogs: string;
  confirmRestart: string;
  confirmStop: string;
  confirmDelete: string;
  confirmDeleteBackup: string;
  actionSuccess: string;
  actionFailed: string;
  backupDownloaded: string;

  // Agent Detail
  backToDashboard: string;
  overview: string;
  config: string;
  logs: string;
  events: string;
  health: string;

  // Overview Tab
  podInfo: string;
  nodeName: string;
  age: string;
  replicas: string;
  resourceUsage: string;
  connectedPlatforms: string;
  quickStats: string;
  sessions: string;
  messages: string;
  tokens: string;

  // Config Tab
  envVars: string;
  configYaml: string;
  soulMd: string;
  apply: string;
  applying: string;
  applySuccess: string;
  applyFailed: string;
  showDiff: string;
  addVariable: string;
  showValue: string;
  hideValue: string;
  keyPlaceholder: string;
  valuePlaceholder: string;
  deleteVar: string;
  configChanged: string;

  // Logs Tab
  pause: string;
  resume: string;
  clear: string;
  searchLogs: string;
  noLogs: string;
  connected: string;
  disconnected: string;

  // Events Tab
  eventType: string;
  reason: string;
  message: string;
  count: string;
  age: string;
  noEvents: string;
  normal: string;
  warning: string;

  // Health Tab
  overallStatus: string;
  readiness: string;
  liveness: string;
  passing: string;
  failing: string;
  unknown: string;
  gatewayResponse: string;
  lastCheck: string;
  healthy: string;
  degraded: string;
  unhealthy: string;

  // Create Wizard
  step1Title: string;
  step2Title: string;
  step3Title: string;
  step4Title: string;
  agentNumber: string;
  agentNumberHint: string;
  displayName: string;
  displayNameOptional: string;
  cpuLimit: string;
  memoryLimit: string;
  provider: string;
  model: string;
  apiKey: string;
  baseUrl: string;
  testConnection: string;
  testing: string;
  testSuccess: string;
  testFailed: string;
  connectionLatency: string;
  soulContent: string;
  envVariables: string;
  review: string;
  viewRawTemplates: string;
  deploy: string;
  deploying: string;
  deploySuccess: string;
  deployFailed: string;
  creatingSecret: string;
  initializingData: string;
  creatingDeployment: string;
  updatingIngress: string;
  waitingForReady: string;
  next: string;
  previous: string;

  // Validation
  validationRequired: string;
  validationInvalidNumber: string;
  validationAgentExists: string;
  validationInvalidCpu: string;
  validationInvalidMemory: string;
  validationInvalidEnvKey: string;

  // Settings
  settingsTitle: string;
  adminKey: string;
  currentKey: string;
  newKey: string;
  confirmKey: string;
  keyMismatch: string;
  changeKeyWarning: string;
  defaultResources: string;
  templateEditor: string;
  templateDeployment: string;
  templateEnv: string;
  templateConfig: string;
  templateSoul: string;
  settingsSaved: string;

  // Login
  loginTitle: string;
  loginKeyPlaceholder: string;
  loginButton: string;
  loginFailed: string;

  // Errors
  loadFailed: string;
  notFound: string;
  networkError: string;
};
```

### 8.2 Chinese Translations (zh)

```typescript
admin: {
  // Shell
  title: "Hermes Agent 管理面板",
  navDashboard: "仪表盘",
  navSettings: "设置",

  // Dashboard
  cluster: "集群",
  agents: "代理",
  runningCount: "{count} 运行中",
  totalCount: "{count} 总计",
  agentCount: "{count} 个代理",
  cpuUsage: "CPU 使用率",
  memUsage: "内存使用率",
  diskUsage: "磁盘使用率",
  restarts: "重启次数",
  ago: "{time}前",
  detail: "详情",
  newAgent: "+ 新建代理",

  // Status
  statusRunning: "运行中",
  statusStopped: "已停止",
  statusStarting: "启动中",
  statusFailed: "失败",
  statusUnknown: "未知",

  // Actions
  restart: "重启",
  restarting: "重启中...",
  stop: "停止",
  stopping: "停止中...",
  start: "启动",
  starting: "启动中...",
  delete: "删除",
  backup: "备份",
  backingUp: "备份中...",
  viewLogs: "查看日志",
  confirmRestart: "确定要重启此代理吗？",
  confirmStop: "确定要停止此代理吗？",
  confirmDelete: "确定要删除此代理吗？此操作不可撤销。",
  confirmDeleteBackup: "删除前创建备份？",
  actionSuccess: "操作成功",
  actionFailed: "操作失败",
  backupDownloaded: "备份已下载",

  // Agent Detail
  backToDashboard: "返回仪表盘",
  overview: "概览",
  config: "配置",
  logs: "日志",
  events: "K8s Events",
  health: "健康",

  // Overview Tab
  podInfo: "Pod 信息",
  nodeName: "节点",
  age: "运行时长",
  replicas: "副本",
  resourceUsage: "资源使用",
  connectedPlatforms: "已连接平台",
  quickStats: "快速统计",
  sessions: "会话数",
  messages: "消息数",
  tokens: "Token 数",

  // Config Tab
  envVars: "环境变量",
  configYaml: "config.yaml",
  soulMd: "SOUL.md",
  apply: "应用",
  applying: "应用中...",
  applySuccess: "配置已应用，代理将重启",
  applyFailed: "配置应用失败",
  showDiff: "查看变更",
  addVariable: "+ 添加变量",
  showValue: "显示",
  hideValue: "隐藏",
  keyPlaceholder: "变量名",
  valuePlaceholder: "变量值",
  deleteVar: "删除",
  configChanged: "配置已修改，点击「应用」以保存",

  // Logs Tab
  pause: "暂停",
  resume: "继续",
  clear: "清除",
  searchLogs: "搜索日志...",
  noLogs: "暂无日志",
  connected: "已连接",
  disconnected: "已断开",

  // Events Tab
  eventType: "类型",
  reason: "原因",
  message: "消息",
  count: "次数",
  age: "时间",
  noEvents: "暂无事件",
  normal: "Normal",
  warning: "Warning",

  // Health Tab
  overallStatus: "整体状态",
  readiness: "Readiness 探针",
  liveness: "Liveness 探针",
  passing: "通过",
  failing: "失败",
  unknown: "未知",
  gatewayResponse: "Gateway /health 响应",
  lastCheck: "上次检查",
  healthy: "健康",
  degraded: "降级",
  unhealthy: "不健康",

  // Create Wizard
  step1Title: "基本信息",
  step2Title: "LLM 配置",
  step3Title: "代理配置",
  step4Title: "确认部署",
  agentNumber: "代理编号",
  agentNumberHint: "将创建 hermes-gateway-{N}",
  displayName: "显示名称",
  displayNameOptional: "可选",
  cpuLimit: "CPU 限制",
  memoryLimit: "内存限制",
  provider: "提供商",
  model: "模型",
  apiKey: "API Key",
  baseUrl: "Base URL",
  testConnection: "测试连接",
  testing: "测试中...",
  testSuccess: "连接成功",
  testFailed: "连接失败",
  connectionLatency: "延迟 {ms}ms",
  soulContent: "SOUL.md 内容",
  envVariables: "额外环境变量",
  review: "确认信息",
  viewRawTemplates: "查看原始模板",
  deploy: "部署",
  deploying: "部署中...",
  deploySuccess: "部署成功",
  deployFailed: "部署失败",
  creatingSecret: "创建 Secret...",
  initializingData: "初始化数据目录...",
  creatingDeployment: "创建 Deployment...",
  updatingIngress: "更新 Ingress...",
  waitingForReady: "等待就绪...",
  next: "下一步",
  previous: "上一步",

  // Validation
  validationRequired: "此字段为必填",
  validationInvalidNumber: "请输入有效的数字",
  validationAgentExists: "代理编号已存在",
  validationInvalidCpu: "CPU 格式无效（如 1000m）",
  validationInvalidMemory: "内存格式无效（如 1Gi）",
  validationInvalidEnvKey: "变量名格式无效（大写字母、数字、下划线）",

  // Settings
  settingsTitle: "设置",
  adminKey: "Admin API Key",
  currentKey: "当前密钥",
  newKey: "新密钥",
  confirmKey: "确认密钥",
  keyMismatch: "两次输入的密钥不一致",
  changeKeyWarning: "更改 Admin Key 后需要使用新密钥重新验证。确定继续？",
  defaultResources: "默认资源限制",
  templateEditor: "模板编辑器",
  templateDeployment: "Deployment 模板",
  templateEnv: ".env 模板",
  templateConfig: "config.yaml 模板",
  templateSoul: "SOUL.md 模板",
  settingsSaved: "设置已保存",

  // Login
  loginTitle: "管理员登录",
  loginKeyPlaceholder: "输入 Admin API Key",
  loginButton: "登录",
  loginFailed: "密钥无效",

  // Errors
  loadFailed: "加载失败",
  notFound: "未找到资源",
  networkError: "网络错误，请检查连接",
},
```

### 8.3 English Translations (en)

```typescript
admin: {
  // Shell
  title: "Hermes Agent Admin",
  navDashboard: "Dashboard",
  navSettings: "Settings",

  // Dashboard
  cluster: "Cluster",
  agents: "Agents",
  runningCount: "{count} running",
  totalCount: "{count} total",
  agentCount: "{count} agents",
  cpuUsage: "CPU Usage",
  memUsage: "Memory Usage",
  diskUsage: "Disk Usage",
  restarts: "Restarts",
  ago: "{time} ago",
  detail: "Detail",
  newAgent: "+ New Agent",

  // Status
  statusRunning: "Running",
  statusStopped: "Stopped",
  statusStarting: "Starting",
  statusFailed: "Failed",
  statusUnknown: "Unknown",

  // Actions
  restart: "Restart",
  restarting: "Restarting...",
  stop: "Stop",
  stopping: "Stopping...",
  start: "Start",
  starting: "Starting...",
  delete: "Delete",
  backup: "Backup",
  backingUp: "Backing up...",
  viewLogs: "View Logs",
  confirmRestart: "Are you sure you want to restart this agent?",
  confirmStop: "Are you sure you want to stop this agent?",
  confirmDelete: "Are you sure you want to delete this agent? This cannot be undone.",
  confirmDeleteBackup: "Create backup before deleting?",
  actionSuccess: "Action completed",
  actionFailed: "Action failed",
  backupDownloaded: "Backup downloaded",

  // Agent Detail
  backToDashboard: "Back to Dashboard",
  overview: "Overview",
  config: "Config",
  logs: "Logs",
  events: "K8s Events",
  health: "Health",

  // Overview Tab
  podInfo: "Pod Info",
  nodeName: "Node",
  age: "Age",
  replicas: "Replicas",
  resourceUsage: "Resource Usage",
  connectedPlatforms: "Connected Platforms",
  quickStats: "Quick Stats",
  sessions: "Sessions",
  messages: "Messages",
  tokens: "Tokens",

  // Config Tab
  envVars: "Environment Variables",
  configYaml: "config.yaml",
  soulMd: "SOUL.md",
  apply: "Apply",
  applying: "Applying...",
  applySuccess: "Config applied, agent will restart",
  applyFailed: "Failed to apply config",
  showDiff: "Show Changes",
  addVariable: "+ Add Variable",
  showValue: "Show",
  hideValue: "Hide",
  keyPlaceholder: "KEY",
  valuePlaceholder: "value",
  deleteVar: "Delete",
  configChanged: "Config modified. Click Apply to save.",

  // Logs Tab
  pause: "Pause",
  resume: "Resume",
  clear: "Clear",
  searchLogs: "Search logs...",
  noLogs: "No logs yet",
  connected: "Connected",
  disconnected: "Disconnected",

  // Events Tab
  eventType: "Type",
  reason: "Reason",
  message: "Message",
  count: "Count",
  age: "Age",
  noEvents: "No events",
  normal: "Normal",
  warning: "Warning",

  // Health Tab
  overallStatus: "Overall Status",
  readiness: "Readiness Probe",
  liveness: "Liveness Probe",
  passing: "Passing",
  failing: "Failing",
  unknown: "Unknown",
  gatewayResponse: "Gateway /health Response",
  lastCheck: "Last Check",
  healthy: "Healthy",
  degraded: "Degraded",
  unhealthy: "Unhealthy",

  // Create Wizard
  step1Title: "Basic Info",
  step2Title: "LLM Config",
  step3Title: "Agent Config",
  step4Title: "Confirm & Deploy",
  agentNumber: "Agent Number",
  agentNumberHint: "Will create hermes-gateway-{N}",
  displayName: "Display Name",
  displayNameOptional: "optional",
  cpuLimit: "CPU Limit",
  memoryLimit: "Memory Limit",
  provider: "Provider",
  model: "Model",
  apiKey: "API Key",
  baseUrl: "Base URL",
  testConnection: "Test Connection",
  testing: "Testing...",
  testSuccess: "Connection successful",
  testFailed: "Connection failed",
  connectionLatency: "Latency {ms}ms",
  soulContent: "SOUL.md Content",
  envVariables: "Extra Environment Variables",
  review: "Review",
  viewRawTemplates: "View Raw Templates",
  deploy: "Deploy",
  deploying: "Deploying...",
  deploySuccess: "Deployed successfully",
  deployFailed: "Deployment failed",
  creatingSecret: "Creating Secret...",
  initializingData: "Initializing data directory...",
  creatingDeployment: "Creating Deployment...",
  updatingIngress: "Updating Ingress...",
  waitingForReady: "Waiting for ready...",
  next: "Next",
  previous: "Previous",

  // Validation
  validationRequired: "This field is required",
  validationInvalidNumber: "Please enter a valid number",
  validationAgentExists: "Agent number already exists",
  validationInvalidCpu: "Invalid CPU format (e.g. 1000m)",
  validationInvalidMemory: "Invalid memory format (e.g. 1Gi)",
  validationInvalidEnvKey: "Invalid key format (uppercase letters, digits, underscores)",

  // Settings
  settingsTitle: "Settings",
  adminKey: "Admin API Key",
  currentKey: "Current Key",
  newKey: "New Key",
  confirmKey: "Confirm Key",
  keyMismatch: "Keys do not match",
  changeKeyWarning: "Changing the Admin Key requires re-authentication. Continue?",
  defaultResources: "Default Resource Limits",
  templateEditor: "Template Editor",
  templateDeployment: "Deployment Template",
  templateEnv: ".env Template",
  templateConfig: "config.yaml Template",
  templateSoul: "SOUL.md Template",
  settingsSaved: "Settings saved",

  // Login
  loginTitle: "Admin Login",
  loginKeyPlaceholder: "Enter Admin API Key",
  loginButton: "Login",
  loginFailed: "Invalid key",

  // Errors
  loadFailed: "Failed to load",
  notFound: "Resource not found",
  networkError: "Network error, check connection",
},
```

---

## 9. Error Handling

### 9.1 Error States

Every page follows the same pattern (matching `StatusPage.tsx` and `LogsPage.tsx`):

```typescript
// Standard page state pattern
const [data, setData] = useState<T | null>(null);
const [loading, setLoading] = useState(true);
const [error, setError] = useState<string | null>(null);

// Three render branches:
if (loading) return <LoadingSpinner />;
if (error) return <ErrorDisplay error={error} onRetry={load} />;
if (!data) return null;
return <ActualContent />;
```

#### LoadingSpinner

```tsx
function LoadingSpinner() {
  return (
    <div className="flex items-center justify-center py-24">
      <div className="h-6 w-6 animate-spin rounded-full border-2 border-primary border-t-transparent" />
    </div>
  );
}
```

Reused from `StatusPage.tsx` exactly.

#### ErrorDisplay

```tsx
interface ErrorDisplayProps {
  error: string;
  onRetry?: () => void;
}

function ErrorDisplay({ error, onRetry }: ErrorDisplayProps) {
  const { t } = useI18n();
  return (
    <div className="flex flex-col items-center justify-center py-24 gap-4">
      <div className="rounded-md bg-destructive/10 border border-destructive/20 p-6 max-w-md text-center">
        <p className="text-sm text-destructive">{error}</p>
      </div>
      {onRetry && (
        <Button variant="outline" size="sm" onClick={onRetry}>
          <RefreshCw className="h-3 w-3 mr-1" />
          {t.common.retry}
        </Button>
      )}
    </div>
  );
}
```

#### EmptyState

```tsx
interface EmptyStateProps {
  message: string;
  icon?: React.ReactNode;
  action?: React.ReactNode;
}

function EmptyState({ message, icon, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-16 gap-3">
      {icon && <div className="text-muted-foreground">{icon}</div>}
      <p className="text-sm text-muted-foreground">{message}</p>
      {action}
    </div>
  );
}
```

### 9.2 Toast Notifications

Uses the existing `useToast` hook + `Toast` component from the main app:

```typescript
// Pattern for all action handlers:
const handleAction = async () => {
  setActionLoading(true);
  try {
    await adminApi.someAction(id);
    showToast(t.admin.actionSuccess, "success");
    await refreshData();
  } catch (e) {
    const message = e instanceof AdminApiError
      ? e.message
      : t.admin.actionFailed;
    showToast(message, "error");
  } finally {
    setActionLoading(false);
  }
};
```

Toast usage summary:

| Event | Type | Message |
|-------|------|---------|
| Config applied | success | `t.admin.applySuccess` |
| Config apply failed | error | `${t.admin.applyFailed}: ${err}` |
| Agent restarted | success | `t.admin.actionSuccess` |
| Restart failed | error | `${t.admin.actionFailed}: ${err}` |
| Agent stopped | success | `t.admin.actionSuccess` |
| Agent started | success | `t.admin.actionSuccess` |
| Backup downloaded | success | `t.admin.backupDownloaded` |
| Backup failed | error | `${t.admin.actionFailed}: ${err}` |
| Settings saved | success | `t.admin.settingsSaved` |
| Settings save failed | error | error details |
| LLM test passed | success | `${t.admin.testSuccess} (${latency}ms)` |
| LLM test failed | error | `${t.admin.testFailed}: ${err}` |
| Deploy success | success | `t.admin.deploySuccess` |
| Deploy failed | error | `${t.admin.deployFailed}: ${err}` |

### 9.3 Confirmation Dialogs

Destructive actions (restart, stop, delete) require confirmation. Uses a custom overlay:

```tsx
function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel,
  variant,   // "destructive" | "default"
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  message: string;
  confirmLabel: string;
  variant: "destructive" | "default";
  onConfirm: () => void;
  onCancel: () => void;
}) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 backdrop-blur-sm">
      <div className="bg-background border border-border p-6 max-w-sm w-full mx-4">
        <h3 className="text-sm font-medium mb-2">{title}</h3>
        <p className="text-sm text-muted-foreground mb-4">{message}</p>
        <div className="flex justify-end gap-2">
          <Button variant="outline" size="sm" onClick={onCancel}>
            {t.common.cancel}
          </Button>
          <Button
            variant={variant === "destructive" ? "destructive" : "default"}
            size="sm"
            onClick={onConfirm}
          >
            {confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  );
}
```

### 9.4 API Error Classification

```typescript
class AdminApiError extends Error {
  status: number;
  constructor(status: number, body: string) {
    super(`${status}: ${body}`);
    this.status = status;
    this.name = "AdminApiError";
  }
}

// Helper to get user-friendly error message
function getErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof AdminApiError) {
    switch (error.status) {
      case 401: return t.admin.loginFailed;
      case 404: return t.admin.notFound;
      case 500: return error.message;
      default: return error.message;
    }
  }
  if (error instanceof TypeError) {
    return t.admin.networkError;
  }
  return fallback;
}
```

### 9.5 Loading States Summary

| Component | Loading Indicator | Pattern |
|-----------|-------------------|---------|
| Full page | Centered spinner (`LoadingSpinner`) | Show until first data fetch completes |
| Agent cards | Spinner replaces card grid | `if (loading) return <LoadingSpinner />` |
| Action button | Button text changes + disabled | `disabled={loading}` + text "重启中..." |
| Logs stream | Spinner in log area before SSE connects | Replaced by streaming lines |
| Config save | Save button disabled + spinner icon | `<Save className="...animate-spin" />` |
| Deploy progress | Stepper with per-step spinners | Step-by-step progress indicator |
| Templates tab | Spinner in tab content | Same as full page pattern |

### 9.6 SSE Error Recovery (Logs Tab)

```typescript
useEffect(() => {
  if (paused) return;

  let retries = 0;
  const MAX_RETRIES = 5;
  const navigate = useNavigate();

  async function connect() {
    // Obtain short-lived SSE token
    let token: string;
    try {
      const res = await adminFetch<{ token: string }>(`/agents/${encodeURIComponent(agentId)}/logs/token`, {
        method: "POST",
      });
      token = res.token;
      retries = 0;
      setStreamStatus("connected");
    } catch (e) {
      if (e instanceof AdminApiError && e.status === 401) {
        localStorage.removeItem("admin_api_key");
        navigate("/admin/login");
        return;
      }
      setStreamStatus("disconnected");
      if (retries < MAX_RETRIES) {
        retries++;
        setTimeout(connect, 2000 * retries);  // exponential backoff
      }
      return;
    }

    const url = `${ADMIN_BASE}/agents/${encodeURIComponent(agentId)}/logs?token=${encodeURIComponent(token)}`;
    const es = new EventSource(url);

    es.onopen = () => {
      retries = 0;
      setStreamStatus("connected");
    };

    es.onmessage = (e) => {
      setLines((prev) => [...prev.slice(-499), e.data]);
      requestAnimationFrame(() => {
        scrollRef.current?.scrollTo(0, scrollRef.current.scrollHeight);
      });
    };

    es.onerror = () => {
      es.close();
      setStreamStatus("disconnected");
      if (retries < MAX_RETRIES) {
        retries++;
        setTimeout(connect, 2000 * retries);  // exponential backoff (gets new token)
      }
    };

    eventSourceRef.current = es;
  }

  connect();
  return () => eventSourceRef.current?.close();
}, [agentId, paused]);
```

Stream status shown as a small badge next to the filter bar: green "已连接" or red "已断开".

---

## 10. Login Page

### 10.1 LoginPage Component

```typescript
// LoginPage.tsx
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { adminApi, setAdminKey } from "./lib/admin-api";
import { useI18n } from "../hooks/useI18n";
import { useToast } from "../hooks/useToast";

function LoginPage() {
  const [key, setKey] = useState("");
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const { t } = useI18n();
  const { showToast } = useToast();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      setAdminKey(key);
      await adminApi.login(key);
      localStorage.setItem("admin_api_key", key);
      navigate("/admin");
    } catch (err) {
      localStorage.removeItem("admin_api_key");
      setAdminKey("");
      showToast(t.admin.loginFailed, "error");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex items-center justify-center min-h-screen">
      <form onSubmit={handleSubmit} className="w-full max-w-sm mx-4 space-y-4">
        <h1 className="text-lg font-medium text-center">{t.admin.loginTitle}</h1>
        <input
          type="password"
          value={key}
          onChange={(e) => setKey(e.target.value)}
          placeholder={t.admin.loginKeyPlaceholder}
          className="flex h-9 w-full border border-border bg-transparent px-3 py-1 text-sm"
          autoFocus
          disabled={loading}
        />
        <button
          type="submit"
          disabled={loading || !key}
          className="w-full h-9 bg-primary text-primary-foreground text-sm font-medium"
        >
          {loading ? "..." : t.admin.loginButton}
        </button>
      </form>
    </div>
  );
}
```

### 10.2 Auth Guard Pattern

All protected pages check for `admin_api_key` in localStorage on mount. If missing, redirect to login:

```typescript
// Used in every protected page (DashboardPage, AgentDetailPage, CreateAgentPage, SettingsPage)
const navigate = useNavigate();

useEffect(() => {
  const storedKey = localStorage.getItem("admin_api_key");
  if (!storedKey) {
    navigate("/admin/login", { replace: true });
  }
}, [navigate]);
```

On any 401 API response, the key is cleared and the user is redirected to login:

```typescript
// In adminFetch error handling:
if (res.status === 401) {
  localStorage.removeItem("admin_api_key");
  // Window-level redirect as fallback (in case React context is lost)
  window.location.href = "/admin/login";
}
```

---

## 11. i18n Interpolation Note

The existing `useI18n` system does not support native string interpolation (e.g. `{count}` placeholders). Use the following pattern for dynamic values:

```typescript
// Instead of expecting t.admin.runningCount to auto-replace {count}:
const text = t.admin.runningCount.replace("{count}", String(count));
const timeAgoText = t.admin.ago.replace("{time}", timeAgo(timestamp));
const latencyText = t.admin.connectionLatency.replace("{ms}", String(latencyMs));
```

This applies to all i18n keys that contain `{...}` placeholders:
- `runningCount`: `"{count} 运行中"` / `"{count} running"`
- `totalCount`: `"{count} 总计"` / `"{count} total"`
- `agentCount`: `"{count} 个代理"` / `"{count} agents"`
- `ago`: `"{time}前"` / `"{time} ago"`
- `connectionLatency`: `"延迟 {ms}ms"` / `"Latency {ms}ms"`
