import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import type {
  AgentDetail,
  EnvVarEntry,
  HealthResponse,
  K8sEvent,
} from "../lib/admin-api";
import { adminApi, AdminApiError } from "../lib/admin-api";
import { useI18n } from "../hooks/useI18n";
import { ConfirmDialog } from "../components/ConfirmDialog";
import {
  formatBytes,
  formatMillicores,
  getBarColor,
  statusDotColor,
  statusLabel,
} from "../lib/utils";
import { showToast } from "../lib/toast";

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
    return "text-red-400";
  if (upper.includes("WARN") || upper.includes("WARNING")) return "text-yellow-400";
  if (upper.includes("DEBUG") || upper.includes("TRACE")) return "text-zinc-500";
  return "text-zinc-200";
}

// ---------------------------------------------------------------------------
// Tab definitions
// ---------------------------------------------------------------------------

const TAB_IDS = ["overview", "config", "logs", "events", "health"] as const;
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
      showToast(
        `${label} - ${err instanceof AdminApiError ? err.detail : t.errorGeneric}`,
        "error"
      );
    } finally {
      setActionLoading(null);
      setConfirmDialog(null);
    }
  }

  // ----- Loading / Error states -----
  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <p className="text-sm text-muted-foreground">{t.loading}</p>
      </div>
    );
  }

  if (error && !agent) {
    return (
      <div className="flex flex-col items-center justify-center py-20 gap-3">
        <p className="text-sm text-destructive">{error}</p>
        <button
          onClick={loadAgent}
          className="h-9 px-4 text-sm border border-border hover:bg-accent rounded"
        >
          {t.retry}
        </button>
      </div>
    );
  }

  if (!agent) return null;

  // ----- Render -----
  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <button
            onClick={() => navigate("/admin")}
            className="h-9 px-3 text-sm border border-border hover:bg-accent rounded"
          >
            &larr; {t.back}
          </button>
          <div className="flex items-center gap-2">
            <span
              className={`inline-block h-2.5 w-2.5 rounded-full ${statusDotColor(agent.status)}`}
            />
            <h1 className="text-xl font-bold">{agent.name}</h1>
            <span className="text-xs text-muted-foreground">
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
            className="h-9 px-4 text-sm border border-border hover:bg-accent rounded disabled:opacity-50"
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
              className="h-9 px-4 text-sm border border-border hover:bg-accent rounded disabled:opacity-50"
            >
              {actionLoading === t.stop ? "..." : t.stop}
            </button>
          ) : (
            <button
              onClick={() =>
                doAction(() => adminApi.startAgent(agentId), t.start)
              }
              disabled={actionLoading !== null}
              className="h-9 px-4 text-sm border border-border hover:bg-accent rounded disabled:opacity-50"
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
            className="h-9 px-4 text-sm rounded bg-destructive text-white hover:bg-destructive/90 disabled:opacity-50"
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
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              activeTab === tab
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            {t[tab as keyof typeof t] ?? tab}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {activeTab === "overview" && (
        <OverviewTab agent={agent} />
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
              () => navigate("/admin")
            );
          }
        }}
        onCancel={() => setConfirmDialog(null)}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Overview Tab
// ---------------------------------------------------------------------------

function OverviewTab({ agent }: { agent: AgentDetail }) {
  const { t } = useI18n();

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

      {/* Resource usage */}
      <div className="rounded-lg border border-border bg-card p-4">
        <h3 className="text-sm font-medium mb-3">{t.resourceUsage}</h3>
        {/* CPU */}
        <div className="mb-3">
          <div className="flex items-center justify-between text-xs text-muted-foreground mb-1">
            <span>{t.cpuUsage}</span>
            <span>
              {agent.resources.cpu_cores !== null
                ? formatMillicores(agent.resources.cpu_cores)
                : "-"}
              {" / "}
              {cpuLimitMillicores !== null
                ? formatMillicores(cpuLimitMillicores / 1000)
                : "-"}
            </span>
          </div>
          <div className="h-2 rounded-full bg-muted overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${cpuPct !== null ? getBarColor(cpuPct) : "bg-muted"}`}
              style={{ width: `${cpuPct ?? 0}%` }}
            />
          </div>
        </div>
        {/* Memory */}
        <div>
          <div className="flex items-center justify-between text-xs text-muted-foreground mb-1">
            <span>{t.memoryUsage}</span>
            <span>
              {memUsage !== null ? formatBytes(memUsage) : "-"}
              {" / "}
              {memLimit !== null ? formatBytes(memLimit) : "-"}
            </span>
          </div>
          <div className="h-2 rounded-full bg-muted overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${memPct !== null ? getBarColor(memPct) : "bg-muted"}`}
              style={{ width: `${memPct ?? 0}%` }}
            />
          </div>
        </div>
      </div>

      {/* Pod info */}
      {agent.pods.length > 0 && (
        <div className="rounded-lg border border-border bg-card p-4">
          <h3 className="text-sm font-medium mb-3">{t.podInfo}</h3>
          {agent.pods.map((pod) => (
            <div key={pod.name} className="text-sm space-y-1 mb-3 last:mb-0">
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                <div>
                  <span className="text-xs text-muted-foreground">{t.podName}:</span>{" "}
                  <span className="font-mono text-xs">{pod.name}</span>
                </div>
                <div>
                  <span className="text-xs text-muted-foreground">{t.podPhase}:</span>{" "}
                  {pod.phase}
                </div>
                <div>
                  <span className="text-xs text-muted-foreground">{t.podIp}:</span>{" "}
                  {pod.pod_ip ?? "-"}
                </div>
                <div>
                  <span className="text-xs text-muted-foreground">{t.podNode}:</span>{" "}
                  {pod.node_name ?? "-"}
                </div>
              </div>
              {pod.containers.map((c) => (
                <div key={c.image} className="ml-4 text-xs text-muted-foreground">
                  {c.image} - {c.ready ? t.containerReady : t.containerNotReady}
                  {c.restart_count > 0 && ` (${t.restartCount}: ${c.restart_count})`}
                </div>
              ))}
            </div>
          ))}
        </div>
      )}

      {/* ConnectedPlatforms placeholder */}
      <div className="rounded-lg border border-border bg-card p-4">
        <h3 className="text-sm font-medium mb-1">{t.connectedPlatforms}</h3>
        <p className="text-xs text-muted-foreground">{t.dataFromHealth}</p>
      </div>

      {/* Metadata */}
      <div className="rounded-lg border border-border bg-card p-4">
        <h3 className="text-sm font-medium mb-2">{t.quickStats}</h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-sm">
          <div>
            <span className="text-xs text-muted-foreground">{t.agentId}:</span> {agent.id}
          </div>
          <div>
            <span className="text-xs text-muted-foreground">{t.agentNamespace}:</span>{" "}
            {agent.namespace}
          </div>
          <div>
            <span className="text-xs text-muted-foreground">{t.createdAt}:</span>{" "}
            {agent.created_at ?? "-"}
          </div>
          <div>
            <span className="text-xs text-muted-foreground">{t.restartCount}:</span>{" "}
            {agent.restart_count}
          </div>
        </div>
      </div>
    </div>
  );
}

function StatusCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border bg-card p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="text-sm font-medium mt-1">{value}</div>
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
      <div className="flex gap-1 mb-4">
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
              className={`px-3 py-1.5 text-sm rounded ${
                subTab === st
                  ? "bg-primary text-white"
                  : "border border-border hover:bg-accent"
              }`}
            >
              {label}
            </button>
          );
        })}
      </div>

      {subTab === "env" && <EnvFormEditor agentId={agentId} />}
      {subTab === "yaml" && <YamlEditor agentId={agentId} />}
      {subTab === "soul" && <SoulEditor agentId={agentId} />}
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
      showToast(
        err instanceof AdminApiError ? err.detail : t.errorSaveFailed,
        "error"
      );
    } finally {
      setApplying(false);
    }
  }

  if (loading) {
    return <p className="text-sm text-muted-foreground">{t.loading}</p>;
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
              className={`h-9 px-3 text-sm border border-border rounded flex-1 font-mono ${v.key !== "" ? "bg-muted" : ""}`}
              placeholder={t.envKey}
            />
            <input
              type={
                v.is_secret && !showValues[v.key] ? "password" : "text"
              }
              value={v.value}
              onChange={(e) => updateVar(i, "value", e.target.value)}
              className="h-9 px-3 text-sm border border-border rounded flex-[2] font-mono"
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
                className="h-9 px-2 text-xs border border-border hover:bg-accent rounded"
              >
                {showValues[v.key] ? t.hide : t.show}
              </button>
            )}
            <button
              onClick={() => removeVar(i)}
              className="h-9 px-2 text-xs border border-border hover:bg-accent rounded text-destructive"
            >
              {t.removeEnvVar}
            </button>
          </div>
        ))}
      </div>
      <div className="flex gap-2">
        <button
          onClick={addVar}
          className="h-9 px-4 text-sm border border-border hover:bg-accent rounded"
        >
          + {t.addEnvVar}
        </button>
        <button
          onClick={apply}
          disabled={applying}
          className="h-9 px-4 text-sm rounded bg-primary text-white hover:bg-primary/90 disabled:opacity-50"
        >
          {applying ? "..." : t.save}
        </button>
      </div>
    </div>
  );
}

// -- YAML Editor --

function YamlEditor({ agentId }: { agentId: number }) {
  const { t } = useI18n();
  const [content, setContent] = useState("");
  const [loading, setLoading] = useState(true);
  const [applying, setApplying] = useState(false);

  useEffect(() => {
    adminApi
      .getAgentConfig(agentId)
      .then((res) => setContent(res.content))
      .catch(() => showToast(t.errorLoadFailed, "error"))
      .finally(() => setLoading(false));
  }, [agentId, t]);

  async function apply() {
    setApplying(true);
    try {
      await adminApi.updateAgentConfig(agentId, content);
      showToast(t.applySuccess);
    } catch (err) {
      showToast(
        err instanceof AdminApiError ? err.detail : t.errorSaveFailed,
        "error"
      );
    } finally {
      setApplying(false);
    }
  }

  if (loading) {
    return <p className="text-sm text-muted-foreground">{t.loading}</p>;
  }

  return (
    <div>
      <textarea
        value={content}
        onChange={(e) => setContent(e.target.value)}
        className="w-full h-[500px] p-3 text-sm border border-border rounded font-mono bg-muted resize-y"
        spellCheck={false}
      />
      <div className="mt-3">
        <button
          onClick={apply}
          disabled={applying}
          className="h-9 px-4 text-sm rounded bg-primary text-white hover:bg-primary/90 disabled:opacity-50"
        >
          {applying ? "..." : t.save}
        </button>
      </div>
    </div>
  );
}

// -- SOUL.md Editor --

function SoulEditor({ agentId }: { agentId: number }) {
  const { t } = useI18n();
  const [content, setContent] = useState("");
  const [loading, setLoading] = useState(true);
  const [applying, setApplying] = useState(false);

  useEffect(() => {
    adminApi
      .getAgentSoul(agentId)
      .then((res) => setContent(res.content))
      .catch(() => showToast(t.errorLoadFailed, "error"))
      .finally(() => setLoading(false));
  }, [agentId, t]);

  async function apply() {
    setApplying(true);
    try {
      await adminApi.updateAgentSoul(agentId, content);
      showToast(t.soulSaved);
    } catch (err) {
      showToast(
        err instanceof AdminApiError ? err.detail : t.errorSaveFailed,
        "error"
      );
    } finally {
      setApplying(false);
    }
  }

  if (loading) {
    return <p className="text-sm text-muted-foreground">{t.loading}</p>;
  }

  return (
    <div>
      <textarea
        value={content}
        onChange={(e) => setContent(e.target.value)}
        className="w-full h-[500px] p-3 text-sm border border-border rounded font-mono bg-muted resize-y"
        spellCheck={false}
      />
      <div className="mt-3">
        <button
          onClick={apply}
          disabled={applying}
          className="h-9 px-4 text-sm rounded bg-primary text-white hover:bg-primary/90 disabled:opacity-50"
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
              ? "bg-green-500/10 text-green-600"
              : "bg-red-500/10 text-red-600"
          }`}
        >
          <span
            className={`inline-block h-1.5 w-1.5 rounded-full ${
              connected ? "bg-green-500" : "bg-red-500"
            }`}
          />
          {connected ? t.logsConnected : t.logsDisconnected}
        </span>

        {/* Pause/Resume */}
        <button
          onClick={() => setPaused(!paused)}
          className="h-8 px-3 text-xs border border-border hover:bg-accent rounded"
        >
          {paused ? t.resume : t.pause}
        </button>

        {/* Filter */}
        <input
          type="text"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder={t.filterLogs}
          className="h-8 px-3 text-xs border border-border rounded flex-1 max-w-xs"
        />

        {/* Clear */}
        <button
          onClick={clearLogs}
          className="h-8 px-3 text-xs border border-border hover:bg-accent rounded"
        >
          {t.logsClear}
        </button>

        {/* Reconnect */}
        {!connected && (
          <button
            onClick={reconnect}
            className="h-8 px-3 text-xs border border-border hover:bg-accent rounded"
          >
            {t.logsReconnect}
          </button>
        )}
      </div>

      {/* Log viewer */}
      <div
        ref={containerRef}
        className="bg-zinc-900 rounded-lg p-3 h-[500px] overflow-y-auto font-mono text-xs leading-5"
      >
        {filteredLines.length === 0 && (
          <p className="text-zinc-500">
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
    return <p className="text-sm text-muted-foreground">{t.loading}</p>;
  }

  if (error) {
    return (
      <p className="text-sm text-destructive">{error}</p>
    );
  }

  if (events.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">{t.noEvents}</p>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border text-left text-xs text-muted-foreground">
            <th className="py-2 px-3">{t.eventType}</th>
            <th className="py-2 px-3">{t.eventReason}</th>
            <th className="py-2 px-3">{t.eventMessage}</th>
            <th className="py-2 px-3">{t.eventCount}</th>
            <th className="py-2 px-3">{t.eventTime}</th>
          </tr>
        </thead>
        <tbody>
          {events.map((evt, i) => (
            <tr
              key={i}
              className={`border-b border-border/50 ${
                evt.type === "Warning" ? "bg-yellow-500/5" : ""
              }`}
            >
              <td className="py-2 px-3">
                <span
                  className={`inline-block text-xs px-2 py-0.5 rounded ${
                    evt.type === "Warning"
                      ? "bg-red-500/10 text-red-600"
                      : "bg-gray-500/10 text-gray-600"
                  }`}
                >
                  {evt.type}
                </span>
              </td>
              <td className="py-2 px-3 font-mono text-xs">{evt.reason}</td>
              <td className="py-2 px-3 text-xs max-w-md truncate">
                {evt.message}
              </td>
              <td className="py-2 px-3 text-xs">{evt.count}</td>
              <td className="py-2 px-3 text-xs text-muted-foreground">
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
    return <p className="text-sm text-muted-foreground">{t.loading}</p>;
  }

  if (error) {
    return (
      <div className="space-y-3">
        <p className="text-sm text-destructive">{error}</p>
        <button
          onClick={() => {
            setLoading(true);
            loadHealth();
          }}
          className="h-9 px-4 text-sm border border-border hover:bg-accent rounded"
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
      <div className="rounded-lg border border-border bg-card p-4 flex items-center gap-4">
        <span
          className={`inline-flex items-center gap-2 text-sm font-medium px-3 py-1 rounded ${
            isHealthy
              ? "bg-green-500/10 text-green-600"
              : "bg-red-500/10 text-red-600"
          }`}
        >
          <span
            className={`inline-block h-2.5 w-2.5 rounded-full ${
              isHealthy ? "bg-green-500" : "bg-red-500"
            }`}
          />
          {isHealthy ? t.healthOk : t.healthError}
        </span>
        {health.latency_ms !== null && (
          <span className="text-xs text-muted-foreground">
            {t.healthLatency}: {health.latency_ms}ms
          </span>
        )}
        {health.checked_at && (
          <span className="text-xs text-muted-foreground">
            {t.healthLastCheck}: {health.checked_at}
          </span>
        )}
        <div className="flex-1" />
        <button
          onClick={() => {
            setLoading(true);
            loadHealth();
          }}
          className="h-9 px-4 text-sm border border-border hover:bg-accent rounded"
        >
          {t.refresh}
        </button>
      </div>

      {/* Gateway raw response */}
      {health.gateway_raw && (
        <div className="rounded-lg border border-border bg-card p-4">
          <h3 className="text-sm font-medium mb-2">{t.healthGatewayRaw}</h3>
          <pre className="bg-muted p-3 rounded text-xs font-mono overflow-auto max-h-[400px]">
            {JSON.stringify(health.gateway_raw, null, 2)}
          </pre>
        </div>
      )}

      {/* Platform info */}
      {health.platform && (
        <div className="rounded-lg border border-border bg-card p-4">
          <span className="text-xs text-muted-foreground">{t.platform}:</span>{" "}
          <span className="text-sm">{health.platform}</span>
        </div>
      )}
    </div>
  );
}
