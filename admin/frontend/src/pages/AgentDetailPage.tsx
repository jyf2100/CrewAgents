import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import type {
  AgentDetail,
  AgentMetadata,
  EnvVarEntry,
  HealthResponse,
  K8sEvent,
  SkillEntry,
} from "../lib/admin-api";
import { adminApi, AdminApiError, getAuthMode } from "../lib/admin-api";
import { useI18n } from "../hooks/useI18n";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { DomainCardSelector } from "../components/DomainCardSelector";
import { SkillList } from "../components/SkillList";
import { TagCloud } from "../components/TagCloud";
import { TagInput } from "../components/TagInput";
import type { DomainValue } from "../components/domain-constants";
import {
  formatBytes,
  formatMillicores,
  getApiError,
  getBarColor,
  statusDotColor,
  statusLabel,
} from "../lib/utils";
import { showToast } from "../lib/toast";
import { WeChatCard } from "../components/WeChatCard";
import { WeChatQRModal } from "../components/WeChatQRModal";
import { TerminalTab } from "../components/TerminalTab";
import { KanbanTab } from "../components/kanban/KanbanTab";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function parseAgentId(raw: string): number {
  // "hermes-gateway-1" -> 1, "5" -> 5
  if (raw.startsWith("hermes-gateway-")) {
    const num = parseInt(raw.slice("hermes-gateway-".length), 10);
    if (!isNaN(num)) return num;
  }
  const n = parseInt(raw, 10);
  if (isNaN(n)) throw new Error(`Invalid agent id: ${raw}`);
  return n;
}

function logLineColor(line: string): string {
  const upper = line.toUpperCase();
  if (upper.includes("ERROR") || upper.includes("FATAL") || upper.includes("CRITICAL"))
    return "text-accent-pink border-l-2 border-l-accent-pink pl-2";
  if (upper.includes("WARN") || upper.includes("WARNING"))
    return "text-warning border-l-2 border-l-warning pl-2";
  if (upper.includes("DEBUG") || upper.includes("TRACE")) return "text-text-secondary";
  return "text-text-primary";
}

// ---------------------------------------------------------------------------
// Tab definitions
// ---------------------------------------------------------------------------

const TAB_IDS = ["overview", "config", "logs", "events", "health", "terminal", "kanban"] as const;
type TabId = (typeof TAB_IDS)[number];

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function AgentDetailPage() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const { id: idParam } = useParams<{ id: string }>();
  const [searchParams, setSearchParams] = useSearchParams();

  const agentId = parseAgentId(idParam ?? "");
  const activeTab = (searchParams.get("tab") as TabId) || "overview";
  const isUser = getAuthMode() !== "admin";

  function setTab(tab: TabId) {
    setSearchParams({ tab }, { replace: true });
  }

  // Agent detail
  const [agent, setAgent] = useState<AgentDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Action loading states
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  // Confirm dialogs
  const [confirmDialog, setConfirmDialog] = useState<{
    action: string;
    label: string;
    message: string;
  } | null>(null);

  // WeChat QR modal
  const [weixinQROpen, setWeixinQROpen] = useState(false);

  const loadAgent = useCallback(async () => {
    try {
      const detail = await adminApi.getAgent(agentId);
      setAgent(detail);
      setError(null);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to load"
      );
    } finally {
      setLoading(false);
    }
  }, [agentId]);

  useEffect(() => {
    loadAgent();
  }, [loadAgent]);

  // Auto-refresh agent detail every 10s
  useEffect(() => {
    const interval = setInterval(loadAgent, 10_000);
    return () => clearInterval(interval);
  }, [loadAgent]);

  async function doAction(action: () => Promise<unknown>, label: string) {
    setActionLoading(label);
    try {
      await action();
      showToast(`${label} - OK`);
      await loadAgent();
    } catch (err) {
      showToast(`${label} - ${getApiError(err, t.errorGeneric)}`, "error");
    } finally {
      setActionLoading(null);
      setConfirmDialog(null);
    }
  }

  // ----- Loading / Error states -----
  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <p className="text-sm text-text-secondary">{t.loading}</p>
      </div>
    );
  }

  if (error && !agent) {
    return (
      <div className="flex flex-col items-center justify-center py-20 gap-3">
        <p className="text-sm text-accent-pink">{error}</p>
        <button
          onClick={loadAgent}
          className="h-9 px-4 text-sm border border-accent-cyan text-accent-cyan hover:bg-accent-cyan/10 rounded"
        >
          {t.retry}
        </button>
      </div>
    );
  }

  if (!agent) return null;

  // ----- Render -----
  return (
    <div className="animate-page-enter">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <button
            onClick={() => navigate("/")}
            className="h-9 px-3 text-sm border border-accent-cyan text-accent-cyan hover:bg-accent-cyan/10 rounded"
          >
            &larr; {t.back}
          </button>
          <div className="flex items-center gap-2">
            <span
              className={`inline-block h-2.5 w-2.5 rounded-full ${statusDotColor(agent.status)} ${agent.status === "running" ? "animate-status-pulse" : ""}`}
            />
            {agent.display_name ? (
              <>
                <h1 className="text-xl font-[family-name:var(--font-body)] font-semibold text-text-primary">
                  {agent.display_name}
                </h1>
                <span className="text-text-secondary text-sm">
                  {agent.name}
                </span>
              </>
            ) : (
              <h1 className="text-xl font-[family-name:var(--font-body)] font-semibold text-text-primary">
                {agent.name}
              </h1>
            )}
            <span className="text-text-secondary text-xs">
              {statusLabel(agent.status, t)}
            </span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() =>
              doAction(() => adminApi.restartAgent(agentId), t.restart)
            }
            disabled={actionLoading !== null}
            className="h-9 px-4 text-sm border border-accent-cyan text-accent-cyan hover:bg-accent-cyan/10 rounded disabled:opacity-50"
          >
            {actionLoading === t.restart ? "..." : t.restart}
          </button>
          {agent.status === "running" ? (
            <button
              onClick={() =>
                setConfirmDialog({
                  action: "stop",
                  label: t.stop,
                  message: `${t.stop} ${agent.name}?`,
                })
              }
              disabled={actionLoading !== null}
              className="h-9 px-4 text-sm border border-warning text-warning hover:bg-warning/10 rounded disabled:opacity-50"
            >
              {actionLoading === t.stop ? "..." : t.stop}
            </button>
          ) : (
            <button
              onClick={() =>
                doAction(() => adminApi.startAgent(agentId), t.start)
              }
              disabled={actionLoading !== null}
              className="h-9 px-4 text-sm border border-accent-cyan text-accent-cyan hover:bg-accent-cyan/10 rounded disabled:opacity-50"
            >
              {actionLoading === t.start ? "..." : t.start}
            </button>
          )}
          <button
            onClick={() =>
              setConfirmDialog({
                action: "delete",
                label: t.delete,
                message: t.errorDeleteConfirm,
              })
            }
            disabled={actionLoading !== null}
            className="h-9 px-4 text-sm rounded bg-accent-pink text-white hover:bg-accent-pink/90 disabled:opacity-50"
            style={isUser ? { display: "none" } : undefined}
          >
            {actionLoading === t.delete ? "..." : t.delete}
          </button>
        </div>
      </div>

      {/* Tab bar */}
      <div className="flex border-b border-border mb-6">
        {TAB_IDS.map((tab) => (
          <button
            key={tab}
            onClick={() => setTab(tab)}
            className={`px-4 py-2 text-sm font-medium border-b-[3px] transition-colors ${
              activeTab === tab
                ? "border-b-accent-pink text-accent-pink"
                : "border-b-transparent text-text-secondary hover:text-text-primary"
            }`}
          >
            {t[tab as keyof typeof t] ?? tab}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {activeTab === "overview" && (
        <OverviewTab agent={agent} onRegisterWeChat={() => setWeixinQROpen(true)} onRefresh={loadAgent} isUser={isUser} />
      )}
      {activeTab === "config" && (
        <ConfigTab agentId={agentId} />
      )}
      {activeTab === "logs" && (
        <LogsTab agentId={agentId} />
      )}
      {activeTab === "events" && (
        <EventsTab agentId={agentId} />
      )}
      {activeTab === "health" && (
        <HealthTab agentId={agentId} />
      )}

      {activeTab === "terminal" && (
        <TerminalTab agentId={agentId} />
      )}

      {activeTab === "kanban" && (
        <KanbanTab agentId={agentId} />
      )}

      {/* WeChat QR Modal */}
      <WeChatQRModal
        agentId={agentId}
        open={weixinQROpen}
        onClose={() => setWeixinQROpen(false)}
        onSuccess={loadAgent}
      />

      {/* Confirm dialog */}
      <ConfirmDialog
        open={confirmDialog !== null}
        title={confirmDialog?.label ?? ""}
        message={confirmDialog?.message ?? ""}
        variant={confirmDialog?.action === "delete" ? "destructive" : "default"}
        confirmLabel={confirmDialog?.label ?? t.confirm}
        cancelLabel={t.cancel}
        loading={actionLoading !== null}
        onConfirm={() => {
          if (!confirmDialog) return;
          if (confirmDialog.action === "stop") {
            doAction(() => adminApi.stopAgent(agentId), t.stop);
          } else if (confirmDialog.action === "delete") {
            doAction(() => adminApi.deleteAgent(agentId, true), t.delete).then(
              () => navigate("/")
            );
          }
        }}
        onCancel={() => setConfirmDialog(null)}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Resource Edit Dialog
// ---------------------------------------------------------------------------

function ResourceEditDialog({ agentId, onClose, onSaved }: {
  agentId: number;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useI18n();
  const [cpuReq, setCpuReq] = useState("250m");
  const [cpuLimit, setCpuLimit] = useState("1000m");
  const [memReq, setMemReq] = useState("512Mi");
  const [memLimit, setMemLimit] = useState("1Gi");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    adminApi.getAgentResources(agentId).then(r => {
      setCpuReq(r.cpu_request);
      setCpuLimit(r.cpu_limit);
      setMemReq(r.memory_request);
      setMemLimit(r.memory_limit);
      setLoading(false);
    }).catch(() => {
      setLoading(false);
      setError(t.resourceLoadError);
    });
  }, [agentId]);

  async function handleSave() {
    setSaving(true);
    setError(null);
    try {
      await adminApi.updateAgentResources(agentId, {
        cpu_request: cpuReq, cpu_limit: cpuLimit,
        memory_request: memReq, memory_limit: memLimit,
      });
      onSaved();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(t.resourceError));
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"><div className="text-text-secondary">...</div></div>;

  const fields = [
    { label: t.resourceCpuRequest, value: cpuReq, set: setCpuReq, placeholder: "250m" },
    { label: t.resourceCpuLimit, value: cpuLimit, set: setCpuLimit, placeholder: "1000m" },
    { label: t.resourceMemRequest, value: memReq, set: setMemReq, placeholder: "512Mi" },
    { label: t.resourceMemLimit, value: memLimit, set: setMemLimit, placeholder: "1Gi" },
  ];

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      role="dialog"
      aria-modal="true"
      aria-labelledby="resource-edit-title"
      tabIndex={-1}
      onClick={onClose}
      onKeyDown={(e) => { if (e.key === "Escape") onClose(); }}
    >
      <div className="bg-surface border border-border rounded-lg p-6 w-96 space-y-4" onClick={(e) => e.stopPropagation()}>
        <h3 id="resource-edit-title" className="text-lg font-bold text-text-primary">{t.resourceEditTitle}</h3>
        <div className="space-y-3">
          {fields.map((f) => (
            <div key={f.label}>
              <label className="text-xs text-text-secondary block mb-1">{f.label}</label>
              <input
                value={f.value}
                onChange={(e) => f.set(e.target.value)}
                placeholder={f.placeholder}
                className="w-full bg-surface/50 border border-border-subtle rounded-md px-3 py-1.5 text-sm font-[family-name:var(--font-mono)] text-text-primary focus:outline-none focus:border-accent-cyan"
              />
            </div>
          ))}
        </div>
        {error && <div className="p-2 rounded bg-red-500/10 text-red-400 text-xs">{error}</div>}
        <p className="text-xs text-text-muted">{t.resourceRestartNote}</p>
        <div className="flex gap-2 justify-end">
          <button onClick={onClose} className="px-4 py-1.5 rounded-md text-sm text-text-secondary hover:text-text-primary border border-border-subtle transition-colors">
            {t.cancel || "Cancel"}
          </button>
          <button onClick={handleSave} disabled={saving} className="px-4 py-1.5 rounded-md text-sm bg-accent-cyan/20 text-accent-cyan border border-accent-cyan/30 hover:bg-accent-cyan/30 disabled:opacity-50 transition-colors">
            {saving ? t.resourceSaving : t.resourceSave}
          </button>
        </div>
      </div>
    </div>
  );
}

function ResourceViewDialog({ agentId, onClose }: {
  agentId: number;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const [spec, setSpec] = useState<{ cpu_request: string; cpu_limit: string; memory_request: string; memory_limit: string } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    setLoading(true);
    setError("");
    adminApi.getAgentResources(agentId).then(r => {
      setSpec({
        cpu_request: r.cpu_request,
        cpu_limit: r.cpu_limit,
        memory_request: r.memory_request,
        memory_limit: r.memory_limit,
      });
      setLoading(false);
    }).catch((e: unknown) => {
      setError(e instanceof Error ? e.message : String(e));
      setLoading(false);
    });
  }, [agentId]);

  if (loading) return <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"><div className="text-text-secondary">...</div></div>;

  const rows = spec ? [
    { label: t.resourceCpuRequest, value: spec.cpu_request },
    { label: t.resourceCpuLimit, value: spec.cpu_limit },
    { label: t.resourceMemRequest, value: spec.memory_request },
    { label: t.resourceMemLimit, value: spec.memory_limit },
  ] : [];

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      role="dialog"
      aria-modal="true"
      aria-labelledby="resource-view-title"
      tabIndex={-1}
      onClick={onClose}
      onKeyDown={(e) => { if (e.key === "Escape") onClose(); }}
    >
      <div className="bg-surface border border-border rounded-lg p-6 w-96 space-y-4" onClick={(e) => e.stopPropagation()}>
        <h3 id="resource-view-title" className="text-lg font-bold text-text-primary">{t.resourceViewTitle}</h3>
        {error && <p className="text-red-400 text-sm mb-3">{error}</p>}
        <div className="space-y-3">
          {rows.map((r) => (
            <div key={r.label} className="flex items-center justify-between">
              <span className="text-xs text-text-secondary">{r.label}</span>
              <span className="text-sm font-[family-name:var(--font-mono)] text-text-primary">{r.value}</span>
            </div>
          ))}
        </div>
        <div className="flex justify-end">
          <button onClick={onClose} className="px-4 py-1.5 rounded-md text-sm text-text-secondary hover:text-text-primary border border-border-subtle transition-colors">
            {t.close || "Close"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Overview Tab
// ---------------------------------------------------------------------------

function OverviewTab({ agent, onRegisterWeChat, onRefresh, isUser }: { agent: AgentDetail; onRegisterWeChat: () => void; onRefresh: () => void; isUser: boolean }) {
  const { t } = useI18n();
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ success: boolean; msg: string } | null>(null);
  const [revealedKey, setRevealedKey] = useState<string | null>(null);
  const [revealing, setRevealing] = useState(false);
  const [showResourceEdit, setShowResourceEdit] = useState(false);
  const [showResourceView, setShowResourceView] = useState(false);

  async function handleTestApi() {
    setTesting(true);
    setTestResult(null);
    try {
      const res = await adminApi.testAgentApi(agent.id);
      if (res.success) {
        setTestResult({ success: true, msg: t.testApiLatency.replace("{n}", String(res.latency_ms)) });
      } else {
        setTestResult({ success: false, msg: res.error || t.testApiFailed });
      }
    } catch (err) {
      setTestResult({ success: false, msg: getApiError(err, t.errorGeneric) });
    } finally {
      setTesting(false);
    }
  }

  function handleCopy(text: string, label: string) {
    try {
      if (navigator.clipboard?.writeText) {
        navigator.clipboard.writeText(text).then(
          () => showToast(`${label} - ${t.copied}`),
          () => showToast(t.errorGeneric, "error"),
        );
      } else {
        const ta = document.createElement("textarea");
        ta.value = text;
        ta.style.cssText = "position:fixed;opacity:0";
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        document.body.removeChild(ta);
        showToast(`${label} - ${t.copied}`);
      }
    } catch {
      showToast(t.errorGeneric, "error");
    }
  }

  async function handleRevealKey() {
    if (revealedKey) {
      setRevealedKey(null);
      return;
    }
    setRevealing(true);
    try {
      const res = await adminApi.revealAgentApiKey(agent.id);
      setRevealedKey(res.api_key);
    } catch (err) {
      showToast(`${t.revealKey} - ${getApiError(err, t.errorGeneric)}`, "error");
    } finally {
      setRevealing(false);
    }
  }

  const cpuLimitMillicores =
    agent.resources.cpu_limit_millicores ?? agent.resources.cpu_cores !== null
      ? Math.round((agent.resources.cpu_cores ?? 0) * 1000)
      : null;

  const cpuFraction =
    agent.resources.cpu_limit_millicores !== null &&
    agent.resources.cpu_limit_millicores > 0 &&
    agent.resources.cpu_cores !== null
      ? (agent.resources.cpu_cores * 1000) / agent.resources.cpu_limit_millicores
      : null;

  const memLimit = agent.resources.memory_limit_bytes;
  const memUsage = agent.resources.memory_bytes;
  const memFraction =
    memLimit !== null && memLimit > 0 && memUsage !== null
      ? memUsage / memLimit
      : null;

  const cpuPct =
    cpuFraction !== null ? Math.min(Math.round(cpuFraction * 100), 100) : null;
  const memPct =
    memFraction !== null ? Math.min(Math.round(memFraction * 100), 100) : null;

  const runningPods = agent.pods.filter((p) => p.phase === "Running").length;

  return (
    <div className="space-y-6">
      {/* Status cards row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatusCard label={t.podIp} value={agent.pods[0]?.pod_ip ?? "-"} />
        <StatusCard label={t.podNode} value={agent.pods[0]?.node_name ?? "-"} />
        <StatusCard label={t.agentAge} value={agent.age_human} />
        <StatusCard
          label={t.replicas}
          value={`${runningPods}/${agent.pods.length}`}
        />
      </div>

      {/* API Access */}
      {(agent.api_server_url || agent.api_key_masked) && (
        <div className="rounded-lg border border-border bg-surface p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-medium text-text-primary">{t.apiAccess}</h3>
            <button
              onClick={handleTestApi}
              disabled={testing || agent.status !== "running"}
              className="h-8 px-3 text-xs border border-accent-cyan text-accent-cyan hover:bg-accent-cyan/10 rounded disabled:opacity-50"
            >
              {testing ? "..." : t.testApiConnection}
            </button>
          </div>
          {testResult && (
            <div className={`mb-3 text-xs px-3 py-2 rounded ${
              testResult.success ? "bg-success/10 text-success" : "bg-accent-pink/10 text-accent-pink"
            }`}>
              {testResult.success ? t.testApiSuccess : t.testApiFailed}: {testResult.msg}
            </div>
          )}
          <div className="space-y-2">
            <div className="flex items-center gap-3 text-sm">
              <span className="text-text-secondary text-xs w-20 shrink-0">{t.apiServerUrl}:</span>
              <span className="font-[family-name:var(--font-mono)] text-xs text-text-primary flex-1 truncate" title={agent.api_server_url}>
                {agent.api_server_url || "-"}
              </span>
              {agent.api_server_url && (
                <button
                  onClick={() => handleCopy(agent.api_server_url, t.copyUrl)}
                  className="shrink-0 text-accent-cyan hover:text-accent-cyan/80 text-xs px-2 py-1 border border-border rounded"
                >
                  {t.copy}
                </button>
              )}
            </div>
            <div className="flex items-center gap-3 text-sm">
              <span className="text-text-secondary text-xs w-20 shrink-0">{t.apiKeyMasked}:</span>
              <span className="font-[family-name:var(--font-mono)] text-xs text-text-primary truncate">
                {revealedKey || agent.api_key_masked || "-"}
              </span>
              <button
                onClick={handleRevealKey}
                disabled={revealing}
                className="shrink-0 text-text-secondary hover:text-text-primary disabled:opacity-50"
                title={revealedKey ? t.hideKey : t.revealKey}
              >
                <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  {revealedKey ? (
                    <>
                      <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24" />
                      <line x1="1" y1="1" x2="23" y2="23" />
                    </>
                  ) : (
                    <>
                      <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                      <circle cx="12" cy="12" r="3" />
                    </>
                  )}
                </svg>
              </button>
              <button
                onClick={() => handleCopy(revealedKey || agent.api_key_masked || "", t.copyKey)}
                className="shrink-0 text-xs px-2 py-1 border border-border rounded text-text-secondary hover:text-text-primary hover:bg-surface"
              >
                {t.copy}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Resource usage */}
      <div className="rounded-lg border border-border bg-surface p-4">
        <h3 className="text-sm font-medium mb-3 text-text-primary flex items-center justify-between">
          <span>{t.resourceUsage}</span>
          {isUser ? (
            <button onClick={() => setShowResourceView(true)} className="text-xs text-accent-cyan hover:text-accent-cyan/80 transition-colors">
              {t.viewConfig}
            </button>
          ) : (
            <button onClick={() => setShowResourceEdit(true)} className="text-xs text-accent-cyan hover:text-accent-cyan/80 transition-colors">
              {t.resourceEdit}
            </button>
          )}
        </h3>
        {/* CPU */}
        <div className="mb-3">
          <div className="flex items-center justify-between text-xs text-text-secondary mb-1">
            <span>{t.cpuUsage}</span>
            <span className="font-[family-name:var(--font-mono)]">
              {agent.resources.cpu_cores !== null
                ? formatMillicores(agent.resources.cpu_cores)
                : "-"}
              {" / "}
              {cpuLimitMillicores !== null
                ? formatMillicores(cpuLimitMillicores / 1000)
                : "-"}
            </span>
          </div>
          <div className="h-2 rounded-full bg-bar-track overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${cpuPct !== null ? getBarColor(cpuPct) : "bg-bar-track"}`}
              style={{ width: `${cpuPct ?? 0}%` }}
            />
          </div>
        </div>
        {/* Memory */}
        <div>
          <div className="flex items-center justify-between text-xs text-text-secondary mb-1">
            <span>{t.memoryUsage}</span>
            <span className="font-[family-name:var(--font-mono)]">
              {memUsage !== null ? formatBytes(memUsage) : "-"}
              {" / "}
              {memLimit !== null ? formatBytes(memLimit) : "-"}
            </span>
          </div>
          <div className="h-2 rounded-full bg-bar-track overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${memPct !== null ? getBarColor(memPct) : "bg-bar-track"}`}
              style={{ width: `${memPct ?? 0}%` }}
            />
          </div>
        </div>
      </div>

      {/* WeChat Connection */}
      <WeChatCard
        agentId={agent.id}
        agentRunning={agent.status === "running"}
        onRegister={onRegisterWeChat}
        onRefresh={() => {}}
      />

      {/* Pod info */}
      {agent.pods.length > 0 && (
        <div className="rounded-lg border border-border bg-surface p-4">
          <h3 className="text-sm font-medium mb-3 text-text-primary">{t.podInfo}</h3>
          {agent.pods.map((pod) => (
            <div key={pod.name} className="text-sm space-y-1 mb-3 last:mb-0">
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                <div>
                  <span className="text-xs text-text-secondary">{t.podName}:</span>{" "}
                  <span className="font-[family-name:var(--font-mono)] text-xs">{pod.name}</span>
                </div>
                <div>
                  <span className="text-xs text-text-secondary">{t.podPhase}:</span>{" "}
                  {pod.phase}
                </div>
                <div>
                  <span className="text-xs text-text-secondary">{t.podIp}:</span>{" "}
                  {pod.pod_ip ?? "-"}
                </div>
                <div>
                  <span className="text-xs text-text-secondary">{t.podNode}:</span>{" "}
                  {pod.node_name ?? "-"}
                </div>
              </div>
              {pod.containers.map((c) => (
                <div key={c.image} className="ml-4 text-xs text-text-secondary">
                  {c.image} - {c.ready ? t.containerReady : t.containerNotReady}
                  {c.restart_count > 0 && ` (${t.restartCount}: ${c.restart_count})`}
                </div>
              ))}
            </div>
          ))}
        </div>
      )}

      {/* ConnectedPlatforms placeholder */}
      <div className="rounded-lg border border-border bg-surface p-4">
        <h3 className="text-sm font-medium mb-1 text-text-primary">{t.connectedPlatforms}</h3>
        <p className="text-xs text-text-secondary">{t.dataFromHealth}</p>
      </div>

      {/* Agent Tags & Role */}
      <MetadataCard agentId={agent.id} />

      {/* Metadata */}
      <div className="rounded-lg border border-border bg-surface p-4">
        <h3 className="text-sm font-medium mb-2 text-text-primary">{t.quickStats}</h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-sm">
          <div>
            <span className="text-xs text-text-secondary">{t.agentId}:</span> {agent.id}
          </div>
          <div>
            <span className="text-xs text-text-secondary">{t.agentNamespace}:</span>{" "}
            {agent.namespace}
          </div>
          <div>
            <span className="text-xs text-text-secondary">{t.createdAt}:</span>{" "}
            {agent.created_at ?? "-"}
          </div>
          <div>
            <span className="text-xs text-text-secondary">{t.restartCount}:</span>{" "}
            {agent.restart_count}
          </div>
        </div>
      </div>

      {showResourceEdit && (
        <ResourceEditDialog
          agentId={agent.id}
          onClose={() => setShowResourceEdit(false)}
          onSaved={() => { onRefresh(); }}
        />
      )}
      {showResourceView && (
        <ResourceViewDialog
          agentId={agent.id}
          onClose={() => setShowResourceView(false)}
        />
      )}
    </div>
  );
}

function StatusCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border border-t border-t-accent-cyan/30 bg-surface p-3">
      <div className="text-xs text-text-secondary">{label}</div>
      <div className="text-sm font-medium mt-1 text-text-primary font-[family-name:var(--font-mono)]">{value}</div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Agent Metadata Card (tags / role editor)
// ---------------------------------------------------------------------------

const TAG_PATTERN = /^[a-z0-9_-]+$/;
const MAX_TAGS = 20;

function MetadataCard({ agentId }: { agentId: number }) {
  const { t } = useI18n();
  const isUser = getAuthMode() !== "admin";

  const [meta, setMeta] = useState<AgentMetadata | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  // Edit state
  const [domain, setDomain] = useState<DomainValue>("generalist");
  const [tags, setTags] = useState<string[]>([]);

  // Skills state
  const [skills, setSkills] = useState<SkillEntry[]>([]);
  const [skillsLoading, setSkillsLoading] = useState(false);

  // Suggestions for TagInput (all known tags)
  const [tagSuggestions, setTagSuggestions] = useState<string[]>([]);

  useEffect(() => {
    adminApi
      .getAgentMetadata(agentId)
      .then((m) => {
        setMeta(m);
        setDomain((m.domain as DomainValue) || "generalist");
        setTags(m.tags || []);
      })
      .catch((err) => {
        // 404 is fine — metadata not created yet
        if (err instanceof AdminApiError && err.status === 404) {
          setMeta(null);
        } else {
          // Log unexpected errors but don't crash the card
          console.warn("Failed to load agent metadata:", err);
          setMeta(null);
        }
      })
      .finally(() => setLoading(false));
  }, [agentId]);

  // Load skills
  useEffect(() => {
    setSkillsLoading(true);
    adminApi
      .getAgentSkills(agentId)
      .then(setSkills)
      .catch(() => setSkills([]))
      .finally(() => setSkillsLoading(false));
  }, [agentId]);

  // Load skill tags for suggestions
  useEffect(() => {
    adminApi
      .getSkillTags()
      .then((res) => setTagSuggestions(res.tags))
      .catch(() => setTagSuggestions([]));
  }, []);

  async function save() {
    setSaving(true);
    try {
      await adminApi.updateAgentMetadata(agentId, {
        tags,
        domain,
        role: domain, // transitional: send both during migration
      });
      showToast(t.metadataSaved);
    } catch (err) {
      showToast(getApiError(err, t.errorGeneric), "error");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <div className="rounded-lg border border-border bg-surface p-4">
        <p className="text-sm text-text-secondary">{t.loading}</p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-border bg-surface p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-medium text-text-primary">{t.editMetadata}</h3>
        {!isUser && (
          <button
            onClick={save}
            disabled={saving}
            className="h-8 px-3 text-xs rounded bg-accent-pink text-white hover:bg-accent-pink/90 disabled:opacity-50"
          >
            {saving ? "..." : t.saveMetadata}
          </button>
        )}
      </div>

      {/* Domain selector */}
      <div className="mb-4">
        <label className="text-xs text-text-secondary block mb-1.5">{t.domainLabel}</label>
        <DomainCardSelector
          value={domain}
          onChange={(v) => setDomain(v)}
          disabled={isUser}
        />
      </div>

      {/* Installed Skills */}
      <div className="mb-4">
        <SkillList
          skills={skills}
          loading={skillsLoading}
          onRefresh={() => {
            setSkillsLoading(true);
            adminApi
              .getAgentSkills(agentId)
              .then(setSkills)
              .catch(() => setSkills([]))
              .finally(() => setSkillsLoading(false));
          }}
        />
      </div>

      {/* Skill-based Tags (read-only) */}
      {meta?.skills && meta.skills.length > 0 && (
        <div className="mb-4">
          <TagCloud
            tags={meta.skills}
            label={t.skillTags}
            hint={t.skillTagsRoutingHint}
          />
        </div>
      )}

      {/* Free Tags (editable) */}
      <div>
        <label className="text-xs text-text-secondary block mb-1">{t.freeTags}</label>
        <p className="text-[10px] text-text-muted mb-1.5">{t.freeTagsHint}</p>
        {isUser ? (
          <TagCloud tags={tags} />
        ) : (
          <TagInput
            value={tags}
            onChange={setTags}
            suggestions={tagSuggestions}
            placeholder={t.tagInputPlaceholder}
          />
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Config Tab
// ---------------------------------------------------------------------------

function ConfigTab({ agentId }: { agentId: number }) {
  const { t } = useI18n();
  const [subTab, setSubTab] = useState<"env" | "yaml" | "soul">("env");

  return (
    <div>
      {/* Sub-tabs */}
      <div className="flex gap-1 mb-4 border-b border-border">
        {(["env", "yaml", "soul"] as const).map((st) => {
          const label =
            st === "env"
              ? ".env"
              : st === "yaml"
                ? "config.yaml"
                : "SOUL.md";
          return (
            <button
              key={st}
              onClick={() => setSubTab(st)}
              className={`px-3 py-1.5 text-sm border-b-[3px] transition-colors ${
                subTab === st
                  ? "border-b-accent-pink text-accent-pink"
                  : "border-b-transparent text-text-secondary hover:text-text-primary"
              }`}
            >
              {label}
            </button>
          );
        })}
      </div>

      {subTab === "env" && <EnvFormEditor agentId={agentId} />}
      {subTab === "yaml" && (
        <TextConfigEditor
          agentId={agentId}
          loadFn={adminApi.getAgentConfig}
          saveFn={(_, content) => adminApi.updateAgentConfig(agentId, content)}
          successMsg={t.applySuccess}
          t={t}
        />
      )}
      {subTab === "soul" && (
        <TextConfigEditor
          agentId={agentId}
          loadFn={adminApi.getAgentSoul}
          saveFn={(_, content) => adminApi.updateAgentSoul(agentId, content)}
          successMsg={t.soulSaved}
          t={t}
        />
      )}
    </div>
  );
}

// -- Env Form Editor --

function EnvFormEditor({ agentId }: { agentId: number }) {
  const { t } = useI18n();
  const [vars, setVars] = useState<EnvVarEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [applying, setApplying] = useState(false);
  const [showValues, setShowValues] = useState<Record<string, boolean>>({});

  useEffect(() => {
    adminApi
      .getAgentEnv(agentId)
      .then((res) => setVars(res.variables))
      .catch(() => showToast(t.errorLoadFailed, "error"))
      .finally(() => setLoading(false));
  }, [agentId, t]);

  function updateVar(index: number, field: "key" | "value", val: string) {
    setVars((prev) => {
      const copy = [...prev];
      copy[index] = { ...copy[index], [field]: val };
      return copy;
    });
  }

  function removeVar(index: number) {
    setVars((prev) => prev.filter((_, i) => i !== index));
  }

  function addVar() {
    setVars((prev) => [
      ...prev,
      { key: "", value: "", masked: false, is_secret: false },
    ]);
  }

  async function apply() {
    setApplying(true);
    try {
      await adminApi.updateAgentEnv(agentId, vars);
      showToast(t.applySuccess);
    } catch (err) {
      showToast(getApiError(err, t.errorSaveFailed), "error");
    } finally {
      setApplying(false);
    }
  }

  if (loading) {
    return <p className="text-sm text-text-secondary">{t.loading}</p>;
  }

  return (
    <div>
      <div className="space-y-2 mb-4">
        {vars.map((v, i) => (
          <div key={i} className="flex items-center gap-2">
            <input
              type="text"
              value={v.key}
              readOnly={v.key !== ""}
              onChange={(e) => updateVar(i, "key", e.target.value)}
              className={`h-9 px-3 text-sm border border-border rounded-lg flex-1 font-[family-name:var(--font-mono)] bg-background text-text-primary placeholder:text-text-secondary focus:outline-none focus:border-accent-cyan focus:shadow-[0_0_0_2px_rgba(5,217,232,0.15)] ${v.key !== "" ? "opacity-60 cursor-not-allowed bg-surface" : ""}`}
              placeholder={t.envKey}
            />
            <input
              type={
                v.is_secret && !showValues[v.key] ? "password" : "text"
              }
              value={v.value}
              onChange={(e) => updateVar(i, "value", e.target.value)}
              className="h-9 px-3 text-sm border border-border rounded-lg flex-[2] font-[family-name:var(--font-mono)] bg-background text-text-primary placeholder:text-text-secondary focus:outline-none focus:border-accent-cyan focus:shadow-[0_0_0_2px_rgba(5,217,232,0.15)]"
              placeholder={t.envValue}
            />
            {v.is_secret && (
              <button
                onClick={() =>
                  setShowValues((prev) => ({
                    ...prev,
                    [v.key]: !prev[v.key],
                  }))
                }
                className="h-9 px-2 text-xs border border-accent-cyan text-accent-cyan hover:bg-accent-cyan/10 rounded"
              >
                {showValues[v.key] ? t.hide : t.show}
              </button>
            )}
            <button
              onClick={() => removeVar(i)}
              className="h-9 px-2 text-xs border border-accent-pink text-accent-pink hover:bg-accent-pink/10 rounded"
            >
              {t.removeEnvVar}
            </button>
          </div>
        ))}
      </div>
      <div className="flex gap-2">
        <button
          onClick={addVar}
          className="h-9 px-4 text-sm border border-accent-cyan text-accent-cyan hover:bg-accent-cyan/10 rounded"
        >
          + {t.addEnvVar}
        </button>
        <button
          onClick={apply}
          disabled={applying}
          className="h-9 px-4 text-sm rounded bg-accent-pink text-white hover:bg-accent-pink/90 disabled:opacity-50"
        >
          {applying ? "..." : t.save}
        </button>
      </div>
    </div>
  );
}

// -- Shared text config editor --

function TextConfigEditor({
  agentId,
  loadFn,
  saveFn,
  successMsg,
  t,
}: {
  agentId: number;
  loadFn: (id: number) => Promise<{ content: string }>;
  saveFn: (id: number, content: string) => Promise<unknown>;
  successMsg: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- Translations has no index signature
  t: any;}) {
  const [content, setContent] = useState("");
  const [loading, setLoading] = useState(true);
  const [applying, setApplying] = useState(false);

  useEffect(() => {
    loadFn(agentId)
      .then((res) => setContent(res.content))
      .catch(() => showToast(t.errorLoadFailed, "error"))
      .finally(() => setLoading(false));
  }, [agentId, loadFn, t]);

  async function apply() {
    setApplying(true);
    try {
      await saveFn(agentId, content);
      showToast(successMsg);
    } catch (err) {
      showToast(getApiError(err, t.errorSaveFailed), "error");
    } finally {
      setApplying(false);
    }
  }

  if (loading) {
    return <p className="text-sm text-text-secondary">{t.loading}</p>;
  }

  return (
    <div>
      <textarea
        value={content}
        onChange={(e) => setContent(e.target.value)}
        className="w-full h-[500px] p-3 text-sm border border-border rounded-lg font-[family-name:var(--font-mono)] bg-background text-text-primary resize-y focus:outline-none focus:border-accent-cyan focus:shadow-[0_0_0_2px_rgba(5,217,232,0.15)]"
        spellCheck={false}
      />
      <div className="mt-3">
        <button
          onClick={apply}
          disabled={applying}
          className="h-9 px-4 text-sm rounded bg-accent-pink text-white hover:bg-accent-pink/90 disabled:opacity-50"
        >
          {applying ? "..." : t.save}
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Logs Tab
// ---------------------------------------------------------------------------

function LogsTab({ agentId }: { agentId: number }) {
  const { t } = useI18n();
  const [lines, setLines] = useState<string[]>([]);
  const [connected, setConnected] = useState(false);
  const [paused, setPaused] = useState(false);
  const [filter, setFilter] = useState("");
  const containerRef = useRef<HTMLDivElement>(null);
  const esRef = useRef<EventSource | null>(null);
  const retriesRef = useRef(0);
  const pausedRef = useRef(false);
  const timeoutRef = useRef<ReturnType<typeof setTimeout>[]>([]);

  // Keep ref in sync
  useEffect(() => {
    pausedRef.current = paused;
  }, [paused]);

  const connect = useCallback(() => {
    let cancelled = false;

    async function start() {
      try {
        const tokenResp = await adminApi.getLogsToken(agentId);
        if (cancelled) return;

        const es = new EventSource(
          `/admin/api/agents/${agentId}/logs?token=${tokenResp.token}&tail=500&follow=true`
        );
        esRef.current = es;

        es.onopen = () => {
          setConnected(true);
          retriesRef.current = 0;
        };

        es.addEventListener("log", (e) => {
          if (pausedRef.current) return;
          const data = (e as MessageEvent).data;
          if (typeof data === "string") {
            setLines((prev) => {
              const next = [...prev, data];
              // Keep at most 2000 lines
              return next.length > 2000 ? next.slice(-1500) : next;
            });
          }
        });

        es.onerror = () => {
          setConnected(false);
          es.close();
          esRef.current = null;
          // Retry with exponential backoff, max 5
          if (retriesRef.current < 5 && !cancelled) {
            const delay = Math.min(1000 * Math.pow(2, retriesRef.current), 30000);
            retriesRef.current++;
            const tid = setTimeout(() => {
              if (!cancelled) connect();
            }, delay);
            timeoutRef.current.push(tid);
          }
        };
      } catch {
        if (!cancelled) {
          setConnected(false);
          if (retriesRef.current < 5) {
            const delay = Math.min(
              1000 * Math.pow(2, retriesRef.current),
              30000
            );
            retriesRef.current++;
            const tid = setTimeout(() => {
              if (!cancelled) connect();
            }, delay);
            timeoutRef.current.push(tid);
          }
        }
      }
    }

    start();
    return () => {
      cancelled = true;
      // Clear all pending reconnect timeouts
      timeoutRef.current.forEach(clearTimeout);
      timeoutRef.current = [];
      esRef.current?.close();
      esRef.current = null;
    };
  }, [agentId]);

  useEffect(() => {
    const cleanup = connect();
    return cleanup;
  }, [connect]);

  // Auto-scroll
  useEffect(() => {
    if (!paused && containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [lines, paused]);

  // Memoized filtered lines for performance
  const filteredLines = useMemo(() => {
    if (!filter) return lines;
    const lower = filter.toLowerCase();
    return lines.filter((l) => l.toLowerCase().includes(lower));
  }, [lines, filter]);

  function clearLogs() {
    setLines([]);
  }

  function reconnect() {
    retriesRef.current = 0;
    esRef.current?.close();
    esRef.current = null;
    timeoutRef.current.forEach(clearTimeout);
    timeoutRef.current = [];
    setLines([]);
    connect();
  }

  return (
    <div>
      {/* Toolbar */}
      <div className="flex items-center gap-2 mb-3">
        {/* Connection status */}
        <span
          className={`inline-flex items-center gap-1 text-xs px-2 py-1 rounded ${
            connected
              ? "bg-success/10 text-success"
              : "bg-accent-pink/10 text-accent-pink"
          }`}
        >
          <span
            className={`inline-block h-1.5 w-1.5 rounded-full ${
              connected ? "bg-success" : "bg-accent-pink"
            }`}
          />
          {connected ? t.logsConnected : t.logsDisconnected}
        </span>

        {/* Pause/Resume */}
        <button
          onClick={() => setPaused(!paused)}
          className="h-8 px-3 text-xs border border-border text-text-secondary hover:bg-surface hover:text-text-primary rounded"
        >
          {paused ? t.resume : t.pause}
        </button>

        {/* Filter */}
        <input
          type="text"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder={t.filterLogs}
          className="h-8 px-3 text-xs border border-border rounded flex-1 max-w-xs bg-background text-text-primary placeholder:text-text-secondary focus:outline-none focus:border-accent-cyan"
        />

        {/* Clear */}
        <button
          onClick={clearLogs}
          className="h-8 px-3 text-xs border border-border text-text-secondary hover:bg-surface hover:text-text-primary rounded"
        >
          {t.logsClear}
        </button>

        {/* Reconnect */}
        {!connected && (
          <button
            onClick={reconnect}
            className="h-8 px-3 text-xs border border-border text-text-secondary hover:bg-surface hover:text-text-primary rounded"
          >
            {t.logsReconnect}
          </button>
        )}
      </div>

      {/* Log viewer */}
      <div
        ref={containerRef}
        className="bg-terminal rounded-lg p-3 h-[500px] overflow-y-auto font-[family-name:var(--font-mono)] text-xs leading-5"
      >
        {filteredLines.length === 0 && (
          <p className="text-text-secondary">
            {connected ? t.logsConnecting : t.logsDisconnected}
          </p>
        )}
        {filteredLines.map((line, i) => (
          <div key={i} className={logLineColor(line)}>
            {line}
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Events Tab
// ---------------------------------------------------------------------------

function EventsTab({ agentId }: { agentId: number }) {
  const { t } = useI18n();
  const [events, setEvents] = useState<K8sEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadEvents = useCallback(async () => {
    try {
      const res = await adminApi.getAgentEvents(agentId);
      setEvents(res.events);
      setError(null);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to load"
      );
    } finally {
      setLoading(false);
    }
  }, [agentId]);

  useEffect(() => {
    loadEvents();
  }, [loadEvents]);

  // Auto-refresh every 10s
  useEffect(() => {
    const interval = setInterval(loadEvents, 10_000);
    return () => clearInterval(interval);
  }, [loadEvents]);

  if (loading) {
    return <p className="text-sm text-text-secondary">{t.loading}</p>;
  }

  if (error) {
    return (
      <p className="text-sm text-accent-pink">{error}</p>
    );
  }

  if (events.length === 0) {
    return (
      <p className="text-sm text-text-secondary">{t.noEvents}</p>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border bg-surface text-left text-xs text-text-secondary uppercase tracking-wider">
            <th className="py-2 px-3">{t.eventType}</th>
            <th className="py-2 px-3">{t.eventReason}</th>
            <th className="py-2 px-3">{t.eventMessage}</th>
            <th className="py-2 px-3">{t.eventCount}</th>
            <th className="py-2 px-3">{t.eventTime}</th>
          </tr>
        </thead>
        <tbody className="bg-background">
          {events.map((evt, i) => (
            <tr
              key={i}
              className={`border-b border-border-subtle hover:bg-surface/50 ${
                evt.type === "Warning" ? "bg-warning/5" : ""
              }`}
            >
              <td className="py-2 px-3">
                <span
                  className={`inline-block text-xs px-2 py-0.5 rounded ${
                    evt.type === "Warning"
                      ? "bg-accent-pink/10 text-accent-pink"
                      : "bg-accent-cyan/10 text-accent-cyan"
                  }`}
                >
                  {evt.type}
                </span>
              </td>
              <td className="py-2 px-3 font-[family-name:var(--font-mono)] text-xs">{evt.reason}</td>
              <td className="py-2 px-3 text-xs max-w-md truncate">
                {evt.message}
              </td>
              <td className="py-2 px-3 text-xs">{evt.count}</td>
              <td className="py-2 px-3 text-xs text-text-secondary">
                {evt.age_human}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Health Tab
// ---------------------------------------------------------------------------

function HealthTab({ agentId }: { agentId: number }) {
  const { t } = useI18n();
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadHealth = useCallback(async () => {
    try {
      const res = await adminApi.getAgentHealth(agentId);
      setHealth(res);
      setError(null);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to load"
      );
    } finally {
      setLoading(false);
    }
  }, [agentId]);

  useEffect(() => {
    loadHealth();
  }, [loadHealth]);

  if (loading) {
    return <p className="text-sm text-text-secondary">{t.loading}</p>;
  }

  if (error) {
    return (
      <div className="space-y-3">
        <p className="text-sm text-accent-pink">{error}</p>
        <button
          onClick={() => {
            setLoading(true);
            loadHealth();
          }}
          className="h-9 px-4 text-sm border border-accent-cyan text-accent-cyan hover:bg-accent-cyan/10 rounded"
        >
          {t.refresh}
        </button>
      </div>
    );
  }

  if (!health) return null;

  const isHealthy = health.status === "healthy" || health.status === "ok";

  return (
    <div className="space-y-4">
      {/* Overall status */}
      <div className="rounded-lg border border-border bg-surface p-4 flex items-center gap-4">
        <span
          className={`inline-flex items-center gap-2 text-sm font-medium px-3 py-1 rounded ${
            isHealthy
              ? "bg-success/10 text-success"
              : "bg-accent-pink/10 text-accent-pink"
          }`}
        >
          <span
            className={`inline-block h-2.5 w-2.5 rounded-full ${
              isHealthy ? "bg-success" : "bg-accent-pink"
            }`}
          />
          {isHealthy ? t.healthOk : t.healthError}
        </span>
        {health.latency_ms !== null && (
          <span className="text-text-secondary text-xs">
            {t.healthLatency}: {health.latency_ms}ms
          </span>
        )}
        {health.checked_at && (
          <span className="text-text-secondary text-xs">
            {t.healthLastCheck}: {health.checked_at}
          </span>
        )}
        <div className="flex-1" />
        <button
          onClick={() => {
            setLoading(true);
            loadHealth();
          }}
          className="h-9 px-4 text-sm border border-accent-cyan text-accent-cyan hover:bg-accent-cyan/10 rounded"
        >
          {t.refresh}
        </button>
      </div>

      {/* Gateway raw response */}
      {health.gateway_raw && (
        <div className="rounded-lg border border-border bg-surface p-4">
          <h3 className="text-sm font-medium mb-2 text-text-primary">{t.healthGatewayRaw}</h3>
          <pre className="bg-background p-3 rounded font-[family-name:var(--font-mono)] text-xs text-text-primary overflow-auto max-h-[400px]">
            {JSON.stringify(health.gateway_raw, null, 2)}
          </pre>
        </div>
      )}

      {/* Platform info */}
      {health.platform && (
        <div className="rounded-lg border border-border bg-surface p-4">
          <span className="text-xs text-text-secondary">{t.platform}:</span>{" "}
          <span className="text-sm text-text-primary">{health.platform}</span>
        </div>
      )}
    </div>
  );
}
