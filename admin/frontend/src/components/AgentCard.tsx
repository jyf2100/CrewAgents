import { useState, useRef, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import type { AgentListItem } from "../lib/admin-api";
import { adminApi, AdminApiError, getAdminKey } from "../lib/admin-api";
import { useI18n } from "../hooks/useI18n";
import {
  formatBytes,
  formatMillicores,
  getBarColor,
  statusDotColor,
  statusLabel,
  statusOrder,
} from "../lib/utils";
import { showToast } from "../lib/toast";
import { ConfirmDialog } from "./ConfirmDialog";

// Re-export statusOrder for DashboardPage
export { statusOrder };

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

  // Resource computation - simplified CPU
  const cpuCores = agent.resources.cpu_cores ?? 0;
  const cpuLimitCores =
    (agent.resources.cpu_limit_millicores ?? cpuCores * 1000) / 1000;
  const cpuPercent =
    cpuLimitCores > 0 ? Math.round((cpuCores / cpuLimitCores) * 100) : 0;

  const memLimit = agent.resources.memory_limit_bytes;
  const memUsage = agent.resources.memory_bytes;
  const memFraction =
    memLimit !== null && memLimit > 0 && memUsage !== null
      ? memUsage / memLimit
      : null;

  const cpuPct = Math.min(cpuPercent, 100);
  const memPct =
    memFraction !== null ? Math.min(Math.round(memFraction * 100), 100) : null;

  async function doAction(action: () => Promise<unknown>, label: string) {
    setActionLoading(true);
    try {
      await action();
      showToast(`${label} - OK`);
      onActionDone();
    } catch (err) {
      showToast(
        `${label} - ${err instanceof AdminApiError ? err.detail : t.errorGeneric}`,
        "error"
      );
    } finally {
      setActionLoading(false);
      setMenuOpen(false);
    }
  }

  async function handleBackup() {
    try {
      const resp = await adminApi.backupAgent(agent.id);
      // Download via fetch with header auth (avoids key in URL)
      const downloadRes = await fetch(resp.download_url, {
        headers: { "X-Admin-Key": getAdminKey() },
      });
      if (!downloadRes.ok) throw new Error("Download failed");
      const blob = await downloadRes.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = resp.filename || `${agent.name}-backup.tar.gz`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      showToast(
        `${t.backup} - ${err instanceof AdminApiError ? err.detail : t.errorGeneric}`,
        "error"
      );
    }
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
                  navigate(`/agents/${agent.id}`);
                }}
              >
                {t.logs}
              </button>
              <button
                className="w-full text-left px-3 py-1.5 hover:bg-accent disabled:opacity-50"
                disabled={actionLoading}
                onClick={() => {
                  setMenuOpen(false);
                  handleBackup();
                }}
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
              {agent.resources.cpu_cores !== null
                ? formatMillicores(agent.resources.cpu_cores)
                : "-"}
              {" / "}
              {agent.resources.cpu_limit_millicores !== null
                ? formatMillicores(agent.resources.cpu_limit_millicores / 1000)
                : "-"}
            </span>
          </div>
          <div className="h-1.5 rounded-full bg-muted overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${getBarColor(cpuPct)}`}
              style={{ width: `${cpuPct}%` }}
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
            onClick={() => navigate(`/agents/${agent.id}`)}
            className="text-xs text-primary hover:underline"
          >
            {t.view} &rarr;
          </button>
        </div>
      </div>

      {/* Delete confirm dialog */}
      <ConfirmDialog
        open={confirmDelete}
        title={t.delete}
        message={t.errorDeleteConfirm}
        confirmLabel={t.delete}
        cancelLabel={t.cancel}
        variant="destructive"
        loading={actionLoading}
        onConfirm={handleDelete}
        onCancel={() => setConfirmDelete(false)}
      />
    </>
  );
}
