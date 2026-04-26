/**
 * Hermes Admin API Client
 *
 * TypeScript client for the Hermes Agent Admin API.
 * All requests include X-Admin-Key header for authentication.
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
// Key management
// ---------------------------------------------------------------------------

const ADMIN_BASE = "/admin/api";

export function setAdminKey(key: string): void {
  localStorage.setItem("admin_api_key", key);
}

export function getAdminKey(): string {
  return localStorage.getItem("admin_api_key") || "";
}

function clearAuth(): void {
  localStorage.removeItem("admin_api_key");
  window.location.href = "/admin/login";
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
    "X-Admin-Key": getAdminKey(),
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

  getLogsToken(agentId: number): Promise<LogsTokenResponse> {
    return adminFetch(`/agents/${agentId}/logs/token`);
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
    // EventSource cannot set custom headers, so pass admin key as query param
    const key = getAdminKey();
    return `${ADMIN_BASE}/agents/${agentId}/weixin/qr?key=${encodeURIComponent(key)}`;
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
};
