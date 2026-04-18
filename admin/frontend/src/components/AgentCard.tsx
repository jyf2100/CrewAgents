import { useState, useRef, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import type { AgentListItem } from "../lib/admin-api";
import { adminApi, AdminApiError } from "../lib/admin-api";
import { useI18n } from "../hooks/useI18n";
import type { Translations } from "../i18n/zh";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatBytes(bytes: number | null): string {
  if (bytes === null || bytes === 0) return "0";
  const units = ["", "K", "M", "Gi", "Ti"];
  let idx = 0;
  let val = bytes;
  while (val >= 1024 && idx < units.length - 1) {
    val /= 1024;
    idx++;
  }
  return idx === 0 ? `${val}` : `${val.toFixed(val < 10 ? 1 : 0)}${units[idx]}`;
}

function formatMillicores(cores: number | null): string {
  if (cores === null) return "-";
  const milli = Math.round(cores * 1000);
  return `${milli}m`;
}

function getBarColor(pct: number): string {
  if (pct >= 90) return "bg-red-500";
  if (pct >= 70) return "bg-yellow-500";
  return "bg-green-500";
}

const STATUS_PRIORITY: Record<string, number> = {
  failed: 0,
  starting: 1,
  stopped: 2,
  running: 3,
  unknown: 4,
};

function statusOrder(status: string): number {
  return STATUS_PRIORITY[status] ?? 5;
}

function statusDotColor(status: string): string {
  switch (status) {
    case "running":
      return "bg-green-500";
    case "failed":
      return "bg-red-500";
    case "starting":
      return "bg-yellow-500";
    case "stopped":
      return "bg-gray-400";
    default:
      return "bg-gray-300";
  }
}

function statusLabel(status: string, t: Translations): string {
  switch (status) {
    case "running":
      return t.statusRunning;
    case "failed":
      return t.statusFailed;
    case "starting":
      return t.statusPending;
    case "stopped":
      return t.statusStopped;
    default:
      return t.statusUnknown;
  }
}

export { statusOrder, formatBytes, formatMillicores };

// ---------------------------------------------------------------------------
// AgentCard component
// ---------------------------------------------------------------------------

interface AgentCardProps {
  agent: AgentListItem;
  onActionDone: () => void;
}

export function AgentCard({ agent, onActionDone }: AgentCardProps) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [menuOpen, setMenuOpen] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);
  const menuRef = useRef<HTMLDetailsElement>(null);

  // Close menu when clicking outside
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    }
    if (menuOpen) {
      document.addEventListener("click", handleClick);
      return () => document.removeEventListener("click", handleClick);
    }
  }, [menuOpen]);

  // Resource computation
  const cpuLimitMillicores =
    agent.resources.cpu_limit_millicores ?? agent.resources.cpu_cores !== null
      ? Math.round((agent.resources.cpu_cores ?? 0) * 1000)
      : null;
  const cpuUsageMillicores =
    cpuLimitMillicores !== null
      ? Math.round(
          cpuLimitMillicores *
            (agent.resources.cpu_cores !== null && cpuLimitMillicores > 0
              ? (agent.resources.cpu_cores * 1000) / cpuLimitMillicores
              : 0)
        )
      : null;

  // cpu_usage is fraction of limit: use cpu_cores / (cpu_limit_millicores/1000)
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

  async function doAction(action: () => Promise<unknown>, label: string) {
    setActionLoading(true);
    try {
      await action();
      toast(`${label} - OK`);
      onActionDone();
    } catch (err) {
      toast(
        `${label} - ${err instanceof AdminApiError ? err.detail : t.errorGeneric}`
      );
    } finally {
      setActionLoading(false);
      setMenuOpen(false);
    }
  }

  function toast(msg: string) {
    // Simple toast via a temporary element
    const el = document.createElement("div");
    el.className =
      "fixed bottom-4 right-4 z-50 rounded-md border border-border bg-card px-4 py-2 text-sm shadow-lg transition-opacity";
    el.textContent = msg;
    document.body.appendChild(el);
    setTimeout(() => {
      el.style.opacity = "0";
      setTimeout(() => el.remove(), 300);
    }, 2500);
  }

  async function handleDelete() {
    setConfirmDelete(false);
    await doAction(() => adminApi.deleteAgent(agent.id, true), t.delete);
  }

  return (
    <>
      <div className="rounded-lg border border-border bg-card p-4 flex flex-col gap-3 hover:shadow-md transition-shadow">
        {/* Header: status dot + name */}
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-2 min-w-0">
            <span
              className={`inline-block h-2.5 w-2.5 rounded-full flex-shrink-0 ${statusDotColor(agent.status)}`}
            />
            <span className="text-xs text-muted-foreground">
              {statusLabel(agent.status, t)}
            </span>
            <span className="text-sm font-medium truncate">{agent.name}</span>
          </div>
          {/* Kebab menu */}
          <details
            ref={menuRef}
            open={menuOpen}
            onToggle={(e) => setMenuOpen((e.target as HTMLDetailsElement).open)}
            className="relative"
          >
            <summary className="cursor-pointer text-muted-foreground hover:text-foreground text-sm select-none list-none px-1">
              ...
            </summary>
            <div className="absolute right-0 top-6 z-20 w-36 rounded-md border border-border bg-background shadow-lg py-1 text-sm">
              <button
                className="w-full text-left px-3 py-1.5 hover:bg-accent disabled:opacity-50"
                disabled={actionLoading}
                onClick={() =>
                  doAction(
                    () => adminApi.restartAgent(agent.id),
                    t.restart
                  )
                }
              >
                {t.restart}
              </button>
              {agent.status === "running" ? (
                <button
                  className="w-full text-left px-3 py-1.5 hover:bg-accent disabled:opacity-50"
                  disabled={actionLoading}
                  onClick={() =>
                    doAction(() => adminApi.stopAgent(agent.id), t.stop)
                  }
                >
                  {t.stop}
                </button>
              ) : (
                <button
                  className="w-full text-left px-3 py-1.5 hover:bg-accent disabled:opacity-50"
                  disabled={actionLoading}
                  onClick={() =>
                    doAction(() => adminApi.startAgent(agent.id), t.start)
                  }
                >
                  {t.start}
                </button>
              )}
              <button
                className="w-full text-left px-3 py-1.5 hover:bg-accent"
                onClick={() => {
                  setMenuOpen(false);
                  navigate(`/admin/agents/${agent.id}`);
                }}
              >
                {t.logs}
              </button>
              <button
                className="w-full text-left px-3 py-1.5 hover:bg-accent disabled:opacity-50"
                disabled={actionLoading}
                onClick={() =>
                  doAction(
                    () =>
                      adminApi.backupAgent(agent.id).then((blob) => {
                        const url = URL.createObjectURL(blob);
                        const a = document.createElement("a");
                        a.href = url;
                        a.download = `${agent.name}-backup.tar.gz`;
                        a.click();
                        URL.revokeObjectURL(url);
                      }),
                    t.backup
                  )
                }
              >
                {t.backup}
              </button>
              <hr className="my-1 border-border" />
              <button
                className="w-full text-left px-3 py-1.5 hover:bg-accent text-destructive disabled:opacity-50"
                disabled={actionLoading}
                onClick={() => {
                  setMenuOpen(false);
                  setConfirmDelete(true);
                }}
              >
                {t.delete}
              </button>
            </div>
          </details>
        </div>

        {/* CPU bar */}
        <div>
          <div className="flex items-center justify-between text-xs text-muted-foreground mb-1">
            <span>{t.cpuUsage}</span>
            <span>
              {cpuUsageMillicores !== null ? formatMillicores(cpuUsageMillicores / 1000) : "-"}
              {" / "}
              {cpuLimitMillicores !== null ? formatMillicores(cpuLimitMillicores / 1000) : "-"}
            </span>
          </div>
          <div className="h-1.5 rounded-full bg-muted overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${cpuPct !== null ? getBarColor(cpuPct) : "bg-muted"}`}
              style={{ width: `${cpuPct ?? 0}%` }}
            />
          </div>
        </div>

        {/* Memory bar */}
        <div>
          <div className="flex items-center justify-between text-xs text-muted-foreground mb-1">
            <span>{t.memoryUsage}</span>
            <span>
              {memUsage !== null ? formatBytes(memUsage) : "-"}
              {" / "}
              {memLimit !== null ? formatBytes(memLimit) : "-"}
            </span>
          </div>
          <div className="h-1.5 rounded-full bg-muted overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${memPct !== null ? getBarColor(memPct) : "bg-muted"}`}
              style={{ width: `${memPct ?? 0}%` }}
            />
          </div>
        </div>

        {/* Footer: restart count, age, detail button */}
        <div className="flex items-center justify-between mt-1">
          <div className="flex items-center gap-3 text-xs text-muted-foreground">
            {agent.restart_count > 0 && (
              <span className="inline-flex items-center rounded-full bg-red-100 text-red-700 px-2 py-0.5 text-xs font-medium">
                {t.restartCount}: {agent.restart_count}
              </span>
            )}
            <span>{agent.age_human}</span>
          </div>
          <button
            onClick={() => navigate(`/admin/agents/${agent.id}`)}
            className="text-xs text-primary hover:underline"
          >
            {t.view} &rarr;
          </button>
        </div>
      </div>

      {/* Delete confirm dialog */}
      {confirmDelete && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div
            className="absolute inset-0 bg-black/50"
            onClick={() => setConfirmDelete(false)}
          />
          <div className="relative bg-background border border-border rounded-lg shadow-lg max-w-md w-full mx-4 p-6">
            <h3 className="text-lg font-semibold mb-2">{t.delete}</h3>
            <p className="text-sm text-muted-foreground mb-6">
              {t.errorDeleteConfirm}
            </p>
            <div className="flex justify-end gap-3">
              <button
                onClick={() => setConfirmDelete(false)}
                className="h-9 px-4 text-sm border border-border hover:bg-accent rounded"
                disabled={actionLoading}
              >
                {t.cancel}
              </button>
              <button
                onClick={handleDelete}
                className="h-9 px-4 text-sm rounded bg-destructive text-white hover:bg-destructive/90"
                disabled={actionLoading}
              >
                {actionLoading ? "..." : t.delete}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
