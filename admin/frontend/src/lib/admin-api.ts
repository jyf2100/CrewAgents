/**
 * Hermes Admin API Client
 *
 * TypeScript client for the Hermes Agent Admin API.
 * Supports two auth modes:
 *   - Admin mode: X-Admin-Key header (existing flow)
 *   - User mode: X-User-Token header (new flow)
 * On 401, clears stored credentials and redirects to login.
 */

// ---------------------------------------------------------------------------
// Error class
// ---------------------------------------------------------------------------

export class AdminApiError extends Error {
  constructor(
    public status: number,
    public detail: string
  ) {
    super(detail);
    this.name = "AdminApiError";
  }
}

// ---------------------------------------------------------------------------
// Auth mode helpers
// ---------------------------------------------------------------------------

export type AuthMode = "admin" | "user" | "email";

const ADMIN_BASE = "/admin/api";

export function setAdminKey(key: string): void {
  localStorage.setItem("admin_api_key", key);
}

export function getAdminKey(): string {
  return localStorage.getItem("admin_api_key") || "";
}

export function getAuthMode(): AuthMode {
  return (localStorage.getItem("admin_mode") as AuthMode) || "admin";
}

export function setAuthMode(mode: AuthMode): void {
  localStorage.setItem("admin_mode", mode);
}

export function getAuthHeaders(): Record<string, string> {
  const mode = getAuthMode();
  if (mode === "email") {
    const token = localStorage.getItem("admin_email_token") || "";
    return { "X-Email-Token": token };
  }
  if (mode === "user") {
    const token = localStorage.getItem("admin_user_token") || "";
    return { "X-User-Token": token };
  }
  const key = getAdminKey();
  return { "X-Admin-Key": key };
}

function clearAuth(): void {
  const mode = getAuthMode();
  if (mode === "email") {
    localStorage.removeItem("admin_email_token");
    localStorage.removeItem("admin_user_agent_id");
    localStorage.removeItem("admin_user_display_name");
  } else if (mode === "user") {
    localStorage.removeItem("admin_user_token");
    localStorage.removeItem("admin_user_agent_id");
    localStorage.removeItem("admin_user_display_name");
  } else {
    localStorage.removeItem("admin_api_key");
  }
  localStorage.removeItem("admin_mode");
  window.location.href = "/admin/";
}

// ---------------------------------------------------------------------------
// Core fetch helper
// ---------------------------------------------------------------------------

export async function adminFetch<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const url = `${ADMIN_BASE}${path}`;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...getAuthHeaders(),
    ...(options.headers as Record<string, string> | undefined),
  };

  const res = await fetch(url, { ...options, headers });

  if (res.status === 401) {
    clearAuth();
    throw new AdminApiError(401, "Unauthorized");
  }

  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") {
        detail = body.detail;
      } else if (Array.isArray(body.detail)) {
        // Pydantic validation errors: [{type, loc, msg, ...}]
        detail = body.detail
          .map((e: { msg?: string; loc?: string[] }) => {
            const field = e.loc ? e.loc.join(".") : "";
            return field ? `${field}: ${e.msg}` : e.msg;
          })
          .join("; ");
      } else if (body.message) {
        detail = body.message;
      }
    } catch {
      // ignore JSON parse errors
    }
    throw new AdminApiError(res.status, detail);
  }

  // Handle Blob responses (e.g. backup download)
  const contentType = res.headers.get("content-type") || "";
  if (
    contentType.includes("application/octet-stream") ||
    contentType.includes("application/gzip") ||
    contentType.includes("application/x-tar")
  ) {
    return (await res.blob()) as unknown as T;
  }

  // For 204 No Content
  if (res.status === 204) {
    return undefined as unknown as T;
  }

  return res.json();
}

// ---------------------------------------------------------------------------
// TypeScript interfaces
// ---------------------------------------------------------------------------

export interface AgentListItem {
  id: number;
  name: string;
  display_name?: string;
  status: string;
  url_path: string;
  api_server_url: string;
  api_key_masked: string;
  resources: {
    cpu_cores: number | null;
    cpu_request_millicores: number | null;
    cpu_limit_millicores: number | null;
    memory_bytes: number | null;
    memory_request_bytes: number | null;
    memory_limit_bytes: number | null;
  };
  restart_count: number;
  created_at: string | null;
  age_human: string;
  health_ok: boolean | null;
}

export interface ContainerStatus {
  ready: boolean;
  restart_count: number;
  state: string;
  reason: string | null;
  image: string;
}

export interface PodInfo {
  name: string;
  phase: string;
  pod_ip: string | null;
  node_name: string | null;
  started_at: string | null;
  containers: ContainerStatus[];
}

export interface AgentDetail {
  id: number;
  name: string;
  display_name?: string;
  status: string;
  url_path: string;
  api_server_url: string;
  api_key_masked: string;
  namespace: string;
  labels: Record<string, string>;
  created_at: string | null;
  pods: PodInfo[];
  resources: {
    cpu_cores: number | null;
    cpu_request_millicores: number | null;
    cpu_limit_millicores: number | null;
    memory_bytes: number | null;
    memory_request_bytes: number | null;
    memory_limit_bytes: number | null;
  };
  health_ok: boolean | null;
  health_last_check: string | null;
  ingress_path: string | null;
  restart_count: number;
  age_human: string;
}

export interface ResourceDataPoint {
  timestamp: string;
  cpu_cores: number;
  memory_bytes: number;
}

export interface EnvVarEntry {
  key: string;
  value: string;
  masked: boolean;
  is_secret: boolean;
}

export interface HealthResponse {
  status: string;
  platform: string;
  gateway_raw: Record<string, unknown> | null;
  latency_ms: number | null;
  checked_at: string;
}

export interface K8sEvent {
  type: string;
  reason: string;
  message: string;
  count: number;
  source: string | null;
  first_timestamp: string | null;
  last_timestamp: string | null;
  age_human: string;
}

export interface ClusterStatus {
  nodes: {
    name: string;
    cpu_capacity: string;
    memory_capacity: string;
    cpu_usage_percent: number | null;
    memory_usage_percent: number | null;
    disk_total_gb: number | null;
    disk_used_gb: number | null;
  }[];
  namespace: string;
  total_agents: number;
  running_agents: number;
}

export interface CreateAgentRequest {
  agent_number: number;
  display_name?: string;
  resources: {
    cpu_request: string;
    cpu_limit: string;
    memory_request: string;
    memory_limit: string;
  };
  llm: {
    provider: string;
    api_key: string;
    model: string;
    base_url?: string | null;
  };
  soul_md: string;
  extra_env: EnvVarEntry[];
  terminal_enabled: boolean;
  browser_enabled: boolean;
  streaming_enabled: boolean;
  memory_enabled: boolean;
  session_reset_enabled: boolean;
}

export interface DeployProgress {
  agent_number: number;
  name: string;
  created: boolean;
  steps: {
    step: number;
    label: string;
    status: string;
    message: string;
  }[];
}

export interface TestLlmRequest {
  provider: string;
  api_key: string;
  model: string;
  base_url?: string | null;
}

export interface TestLlmResponse {
  success: boolean;
  latency_ms: number;
  model_used: string;
  error: string | null;
  response_preview: string | null;
}

export interface Templates {
  deployment_yaml: string;
  env_template: string;
  config_yaml_template: string;
  soul_md_template: string;
}

export interface TemplateType {
  type: string;
  content: string;
}

export interface AdminSettings {
  admin_key_masked: string;
  default_resources: {
    cpu_request: string;
    cpu_limit: string;
    memory_request: string;
    memory_limit: string;
  };
  templates: string[];
}

export interface UpdateSettingsRequest {
  default_resources: {
    cpu_request: string;
    cpu_limit: string;
    memory_request: string;
    memory_limit: string;
  };
}

export interface UpdateConfigResponse {
  message: string;
  detail?: string;
}

export interface ActionResponse {
  agent_number: number;
  action: string;
  success: boolean;
  message: string;
}

export interface BackupResponse {
  agent_number: number;
  filename: string;
  size_bytes: number;
  download_url: string;
}

export interface LogsTokenResponse {
  token: string;
  expires_in: number;
}

export interface WeixinStatus {
  agent_number: number;
  connected: boolean;
  account_id: string;
  user_id: string;
  base_url: string;
  dm_policy: string;
  group_policy: string;
  bound_at: string | null;
}

export interface WeixinAction {
  agent_number: number;
  action: string;
  success: boolean;
  message: string;
}

export interface TestAgentApiResponse {
  agent_number: number;
  success: boolean;
  status_code: number | null;
  latency_ms: number | null;
  error: string | null;
  response_preview: string | null;
}

// ---------------------------------------------------------------------------
// Orchestrator types
// ---------------------------------------------------------------------------

export interface OrchestratorTask {
  task_id: string;
  status: "submitted" | "queued" | "assigned" | "executing" | "streaming" | "done" | "failed";
  assigned_agent: string | null;
  run_id: string | null;
  result: {
    content: string;
    usage: { input_tokens: number; output_tokens: number; total_tokens: number };
    duration_seconds: number;
    run_id: string;
  } | null;
  error: string | null;
  retry_count: number;
  created_at: number;
  updated_at: number;
}

export interface OrchestratorAgent {
  agent_id: string;
  gateway_url: string;
  status: "online" | "degraded" | "offline";
  models: string[];
  current_load: number;
  max_concurrent: number;
  circuit_state: "closed" | "open" | "half_open";
  last_health_check: number;
}

export interface TaskSubmitRequest {
  prompt: string;
  instructions?: string;
  model_id?: string;
  priority?: number;
  timeout_seconds?: number;
  max_retries?: number;
  callback_url?: string;
  metadata?: Record<string, string>;
}

// ---------------------------------------------------------------------------
// User Login response
// ---------------------------------------------------------------------------

export interface UserLoginResponse {
  token: string;
  agent_id: number;
  display_name: string;
  expires_in: number;
}

export interface UserMeResponse {
  agent_id: number;
  display_name: string;
}

export interface UserResponse {
  id: number;
  email: string;
  display_name: string;
  agent_id: number | null;
  is_active: boolean;
  created_at: string | null;
  provisioning_status: string;
  provisioning_error: string | null;
}

// ---------------------------------------------------------------------------
// API methods
// ---------------------------------------------------------------------------

export const adminApi = {
  // -- Auth --
  login(key: string): Promise<{ status: string }> {
    // Test the key by calling health endpoint with it
    return fetch(`${ADMIN_BASE}/health`, {
      headers: { "X-Admin-Key": key },
    }).then(async (res) => {
      if (!res.ok) throw new AdminApiError(res.status, "Invalid admin key");
      return res.json();
    });
  },

  async userLogin(apiKey: string): Promise<UserLoginResponse> {
    return fetch(`${ADMIN_BASE}/user/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ api_key: apiKey }),
    }).then(async (res) => {
      if (res.status === 401) {
        throw new AdminApiError(401, "Invalid API Key");
      }
      if (res.status === 429) {
        throw new AdminApiError(429, "Too many attempts, please try again later");
      }
      if (!res.ok) {
        let detail = `Request failed (${res.status})`;
        try {
          const body = await res.json();
          if (typeof body.detail === "string") detail = body.detail;
          else if (body.message) detail = body.message;
        } catch {
          // ignore JSON parse errors
        }
        throw new AdminApiError(res.status, detail);
      }
      return res.json();
    });
  },

  async userLogout(): Promise<void> {
    const mode = getAuthMode();
    if (mode === "email") {
      const token = localStorage.getItem("admin_email_token");
      if (token) {
        try {
          await fetch(`${ADMIN_BASE}/user/logout`, {
            method: "POST",
            headers: { "Content-Type": "application/json", "X-Email-Token": token },
          });
        } catch {
          // Ignore errors on logout — best effort
        }
      }
    } else if (mode === "user") {
      const token = localStorage.getItem("admin_user_token");
      if (token) {
        try {
          await fetch(`${ADMIN_BASE}/user/logout`, {
            method: "POST",
            headers: { "Content-Type": "application/json", "X-User-Token": token },
          });
        } catch {
          // Ignore errors on logout — best effort
        }
      }
    }
  },

  // -- Email Auth --
  async emailLogin(email: string, password: string): Promise<{
    token: string;
    user_id: number;
    email: string;
    agent_id: number | null;
    display_name: string;
  }> {
    return fetch(`${ADMIN_BASE}/user/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    }).then(async (res) => {
      if (res.status === 401) {
        throw new AdminApiError(401, "Invalid email or password");
      }
      if (res.status === 403) {
        const body = await res.json();
        throw new AdminApiError(403, body.detail || "Account not yet activated");
      }
      if (res.status === 429) {
        throw new AdminApiError(429, "Too many attempts, please try again later");
      }
      if (!res.ok) {
        let detail = `Request failed (${res.status})`;
        try {
          const body = await res.json();
          if (typeof body.detail === "string") detail = body.detail;
        } catch {
          // ignore
        }
        throw new AdminApiError(res.status, detail);
      }
      return res.json();
    });
  },

  async register(email: string, password: string, display_name?: string): Promise<{ message: string }> {
    return adminFetch("/user/register", {
      method: "POST",
      body: JSON.stringify({ email, password, display_name }),
    });
  },

  // -- User Management (admin) --
  listUsers(): Promise<{ users: UserResponse[] }> {
    return adminFetch("/user/list");
  },

  activateUser(userId: number, agentId: number): Promise<UserResponse> {
    return adminFetch(`/user/${userId}/activate`, {
      method: "POST",
      body: JSON.stringify({ agent_id: agentId }),
    });
  },

  deleteUser(userId: number): Promise<{ message: string }> {
    return adminFetch(`/user/${userId}`, { method: "DELETE" });
  },

  rebindAgent(userId: number, agentId: number): Promise<{ status: string; provisioning: string }> {
    return adminFetch(`/user/${userId}/rebind-agent`, {
      method: "POST",
      body: JSON.stringify({ agent_id: agentId }),
    });
  },

  retryProvision(userId: number): Promise<{ provisioning_status: string }> {
    return adminFetch(`/user/${userId}/retry-provision`, { method: "POST" });
  },

  getWebUILoginUrl(): Promise<{ url: string; email: string; password: string; provisioning_status: string }> {
    return adminFetch("/user/webui-url");
  },

  getUserMe(): Promise<UserMeResponse> {
    return adminFetch("/user/me");
  },

  getLogsToken(agentId: number): Promise<LogsTokenResponse> {
    return adminFetch(`/agents/${agentId}/logs/token`);
  },

  // -- Terminal --
  getTerminalToken(agentId: number): Promise<LogsTokenResponse> {
    return adminFetch(`/agents/${agentId}/terminal/token`);
  },

  getTerminalWsUrl(agentId: number, token: string): string {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${proto}//${window.location.host}/admin/api/agents/${agentId}/terminal/ws?token=${encodeURIComponent(token)}`;
  },

  // -- Agents --
  listAgents(): Promise<{ agents: AgentListItem[]; total: number }> {
    return adminFetch("/agents");
  },

  getAgent(agentId: number): Promise<AgentDetail> {
    return adminFetch(`/agents/${agentId}`);
  },

  createAgent(req: CreateAgentRequest): Promise<DeployProgress> {
    return adminFetch("/agents", {
      method: "POST",
      body: JSON.stringify(req),
    });
  },

  deleteAgent(agentId: number, backup = true): Promise<UpdateConfigResponse> {
    return adminFetch(`/agents/${agentId}?backup=${backup}`, {
      method: "DELETE",
    });
  },

  // -- Agent actions --
  restartAgent(agentId: number): Promise<ActionResponse> {
    return adminFetch(`/agents/${agentId}/restart`, { method: "POST" });
  },

  stopAgent(agentId: number): Promise<ActionResponse> {
    return adminFetch(`/agents/${agentId}/stop`, { method: "POST" });
  },

  startAgent(agentId: number): Promise<ActionResponse> {
    return adminFetch(`/agents/${agentId}/start`, { method: "POST" });
  },

  // -- Agent config --
  getAgentConfig(agentId: number): Promise<{ content: string }> {
    return adminFetch(`/agents/${agentId}/config`);
  },

  updateAgentConfig(
    agentId: number,
    content: string,
    restart = true
  ): Promise<UpdateConfigResponse> {
    return adminFetch(`/agents/${agentId}/config`, {
      method: "PUT",
      body: JSON.stringify({ content, restart }),
    });
  },

  getAgentEnv(agentId: number): Promise<{ agent_number: number; variables: EnvVarEntry[] }> {
    return adminFetch(`/agents/${agentId}/env`);
  },

  updateAgentEnv(
    agentId: number,
    variables: EnvVarEntry[],
    restart = true
  ): Promise<UpdateConfigResponse> {
    return adminFetch(`/agents/${agentId}/env`, {
      method: "PUT",
      body: JSON.stringify({ variables, restart }),
    });
  },

  getAgentSoul(agentId: number): Promise<{ content: string }> {
    return adminFetch(`/agents/${agentId}/soul`);
  },

  updateAgentSoul(agentId: number, content: string): Promise<UpdateConfigResponse> {
    return adminFetch(`/agents/${agentId}/soul`, {
      method: "PUT",
      body: JSON.stringify({ content }),
    });
  },

  // -- Agent monitoring --
  getAgentHealth(agentId: number): Promise<HealthResponse> {
    return adminFetch(`/agents/${agentId}/health`);
  },

  testAgentApi(agentId: number): Promise<TestAgentApiResponse> {
    return adminFetch(`/agents/${agentId}/test-api`, {
      method: "POST",
    });
  },

  getAgentEvents(agentId: number): Promise<{ agent_number: number; events: K8sEvent[] }> {
    return adminFetch(`/agents/${agentId}/events`);
  },

  getAgentResources(agentId: number): Promise<Record<string, unknown>> {
    return adminFetch(`/agents/${agentId}/resources`);
  },

  getAgentLogsUrl(agentId: number): Promise<LogsTokenResponse> {
    return adminFetch(`/agents/${agentId}/logs/token`);
  },

  // -- Agent operations --
  backupAgent(agentId: number): Promise<BackupResponse> {
    return adminFetch(`/agents/${agentId}/backup`, {
      method: "POST",
      body: JSON.stringify({ include_data: true, include_k8s_yaml: true }),
    });
  },

  // -- Cluster --
  getClusterStatus(): Promise<ClusterStatus> {
    return adminFetch("/cluster/status");
  },

  // -- Settings --
  getSettings(): Promise<AdminSettings> {
    return adminFetch("/settings");
  },

  updateSettings(
    req: UpdateSettingsRequest
  ): Promise<UpdateConfigResponse> {
    return adminFetch("/settings", {
      method: "PUT",
      body: JSON.stringify(req),
    });
  },

  changeAdminKey(newKey: string): Promise<UpdateConfigResponse> {
    return adminFetch("/settings/admin-key", {
      method: "PUT",
      body: JSON.stringify({ new_key: newKey }),
    });
  },

  // -- Templates --
  getTemplate(type: string): Promise<TemplateType> {
    return adminFetch(`/templates/${type}`);
  },

  updateTemplate(type: string, content: string): Promise<UpdateConfigResponse> {
    return adminFetch(`/templates/${type}`, {
      method: "PUT",
      body: JSON.stringify({ content }),
    });
  },

  // -- Utilities --
  testLlmConnection(req: TestLlmRequest): Promise<TestLlmResponse> {
    return adminFetch("/test-llm-connection", {
      method: "POST",
      body: JSON.stringify(req),
    });
  },

  // -- WeChat (Weixin) --
  getWeixinStatus(agentId: number): Promise<WeixinStatus> {
    return adminFetch(`/agents/${agentId}/weixin/status`);
  },

  startWeixinQR(agentId: number): string {
    // EventSource cannot set custom headers, so pass auth as query param
    const authHeaders = getAuthHeaders();
    const authKey = authHeaders["X-Admin-Key"] || authHeaders["X-User-Token"] || "";
    const authParam = authHeaders["X-User-Token"] ? "token" : "key";
    return `${ADMIN_BASE}/agents/${agentId}/weixin/qr?${authParam}=${encodeURIComponent(authKey)}`;
  },

  unbindWeixin(agentId: number): Promise<WeixinAction> {
    return adminFetch(`/agents/${agentId}/weixin/bind`, {
      method: "DELETE",
    });
  },

  // -- API Key Reveal --
  revealAgentApiKey(agentId: number): Promise<{ agent_number: number; api_key: string }> {
    return adminFetch(`/agents/${agentId}/api-key`, {
      method: "POST",
    });
  },

  // -- Orchestrator --
  orchestratorCapability(): Promise<{ enabled: boolean }> {
    return adminFetch("/orchestrator/capability");
  },

  orchestratorSubmitTask(req: TaskSubmitRequest): Promise<{ task_id: string; status: string; created_at: number }> {
    return adminFetch("/orchestrator/tasks", { method: "POST", body: JSON.stringify(req) });
  },

  orchestratorListTasks(params?: { status?: string; limit?: number; offset?: number }): Promise<OrchestratorTask[]> {
    const query = new URLSearchParams();
    if (params?.status) query.set("status", params.status);
    if (params?.limit) query.set("limit", String(params.limit));
    if (params?.offset) query.set("offset", String(params.offset));
    const qs = query.toString();
    return adminFetch(`/orchestrator/tasks${qs ? `?${qs}` : ""}`);
  },

  orchestratorGetTask(taskId: string): Promise<OrchestratorTask> {
    return adminFetch(`/orchestrator/tasks/${taskId}`);
  },

  orchestratorCancelTask(taskId: string): Promise<{ status: string }> {
    return adminFetch(`/orchestrator/tasks/${taskId}`, { method: "DELETE" });
  },

  orchestratorListAgents(): Promise<{ agents: OrchestratorAgent[] }> {
    return adminFetch("/orchestrator/agents");
  },

  orchestratorAgentHealth(agentId: string): Promise<OrchestratorAgent> {
    return adminFetch(`/orchestrator/agents/${agentId}/health`);
  },
};
