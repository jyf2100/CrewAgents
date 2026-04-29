import { useState, useRef, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import type { AgentListItem } from "../lib/admin-api";
import { adminApi, getAuthHeaders, getAuthMode } from "../lib/admin-api";
import { useI18n } from "../hooks/useI18n";
import {
  formatBytes,
  formatMillicores,
  getApiError,
  getBarColor,
  statusDotColor,
  statusLabel,
  statusOrder,
} from "../lib/utils";
import { showToast } from "../lib/toast";
import { ConfirmDialog } from "./ConfirmDialog";

function copyToClipboard(text: string) {
  if (navigator.clipboard?.writeText) {
    return navigator.clipboard.writeText(text);
  }
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.style.cssText = "position:fixed;opacity:0";
  document.body.appendChild(ta);
  ta.select();
  document.execCommand("copy");
  document.body.removeChild(ta);
  return Promise.resolve();
}

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
  const isUser = getAuthMode() === "user";
  const [menuOpen, setMenuOpen] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ success: boolean; msg: string } | null>(null);
  const [revealedKey, setRevealedKey] = useState<string | null>(null);
  const [revealing, setRevealing] = useState(false);
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

  const isRunning = agent.status === "running";

  async function doAction(action: () => Promise<unknown>, label: string) {
    setActionLoading(true);
    try {
      await action();
      showToast(`${label} - OK`);
      onActionDone();
    } catch (err) {
      showToast(`${label} - ${getApiError(err, t.errorGeneric)}`, "error");
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
        headers: getAuthHeaders(),
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
        `${t.backup} - ${getApiError(err, t.errorGeneric)}`,
        "error"
      );
    }
  }

  async function handleDelete() {
    setConfirmDelete(false);
    await doAction(() => adminApi.deleteAgent(agent.id, true), t.delete);
  }

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

  async function handleCopy(text: string, label: string) {
    try {
      await copyToClipboard(text);
      showToast(`${label} - ${t.copied}`);
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

  return (
    <>
      <div
        className={`rounded-lg border border-border bg-surface p-4 flex flex-col gap-3 hover:border-border-cyan hover:shadow-[0_4px_20px_rgba(123,45,142,0.15)] transition-all duration-200 group hover:-translate-y-0.5 ${
          isRunning ? "border-l-[3px] border-l-accent-cyan" : ""
        }`}
      >
        {/* Header: status dot + name */}
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-2 min-w-0">
            <span
              className={`inline-block h-2.5 w-2.5 rounded-full flex-shrink-0 ${statusDotColor(agent.status)} ${
                isRunning ? "animate-status-pulse glow-cyan" : ""
              }`}
            />
            <span className="text-xs text-text-secondary">
              {statusLabel(agent.status, t)}
            </span>
            {agent.display_name ? (
              <>
                <span className="text-sm font-semibold font-[family-name:var(--font-body)] text-text-primary truncate">
                  {agent.display_name}
                </span>
                <span className="text-xs text-text-secondary truncate">
                  {agent.name}
                </span>
              </>
            ) : (
              <span className="text-sm font-semibold font-[family-name:var(--font-body)] text-text-primary truncate">
                {agent.name}
              </span>
            )}
          </div>
          {/* Kebab menu */}
          <details
            ref={menuRef}
            open={menuOpen}
            onToggle={(e) => setMenuOpen((e.target as HTMLDetailsElement).open)}
            className="relative"
          >
            <summary className="cursor-pointer text-text-secondary hover:text-text-primary select-none list-none p-1">
              <svg
                className="h-4 w-4"
                viewBox="0 0 16 16"
                fill="currentColor"
                aria-hidden="true"
              >
                <circle cx="4" cy="3" r="1.2" />
                <circle cx="4" cy="8" r="1.2" />
                <circle cx="4" cy="13" r="1.2" />
                <rect x="6" y="2.2" width="7" height="1.6" rx="0.8" />
                <rect x="6" y="7.2" width="7" height="1.6" rx="0.8" />
                <rect x="6" y="12.2" width="7" height="1.6" rx="0.8" />
              </svg>
            </summary>
            <div className="absolute right-0 top-8 z-20 w-36 rounded-md border border-border bg-surface-elevated shadow-lg py-1 text-sm">
              <button
                className="w-full text-left px-3 py-1.5 hover:bg-surface text-text-primary disabled:opacity-50"
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
                  className="w-full text-left px-3 py-1.5 hover:bg-surface text-text-primary disabled:opacity-50"
                  disabled={actionLoading}
                  onClick={() =>
                    doAction(() => adminApi.stopAgent(agent.id), t.stop)
                  }
                >
                  {t.stop}
                </button>
              ) : (
                <button
                  className="w-full text-left px-3 py-1.5 hover:bg-surface text-text-primary disabled:opacity-50"
                  disabled={actionLoading}
                  onClick={() =>
                    doAction(() => adminApi.startAgent(agent.id), t.start)
                  }
                >
                  {t.start}
                </button>
              )}
              <button
                className="w-full text-left px-3 py-1.5 hover:bg-surface text-text-primary"
                onClick={() => {
                  setMenuOpen(false);
                  navigate(`/agents/${agent.id}`);
                }}
              >
                {t.logs}
              </button>
              <button
                className="w-full text-left px-3 py-1.5 hover:bg-surface text-text-primary disabled:opacity-50"
                disabled={actionLoading}
                onClick={() => {
                  setMenuOpen(false);
                  handleBackup();
                }}
              >
                {t.backup}
              </button>
              <hr className="my-1 border-border" />
              {!isUser && (
                <button
                  className="w-full text-left px-3 py-1.5 hover:bg-surface text-accent-pink disabled:opacity-50"
                  disabled={actionLoading}
                  onClick={() => {
                    setMenuOpen(false);
                    setConfirmDelete(true);
                  }}
                >
                  {t.delete}
                </button>
              )}
            </div>
          </details>
        </div>

        {/* CPU bar */}
        <div>
          <div className="flex items-center justify-between text-xs text-text-secondary mb-1">
            <span>{t.cpuUsage}</span>
            <span className="font-[family-name:var(--font-mono)]">
              {agent.resources.cpu_cores !== null
                ? formatMillicores(agent.resources.cpu_cores)
                : "-"}
              {" / "}
              {agent.resources.cpu_limit_millicores !== null
                ? formatMillicores(agent.resources.cpu_limit_millicores / 1000)
                : "-"}
            </span>
          </div>
          <div className="h-1.5 rounded-full bg-bar-track overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${getBarColor(cpuPct)}`}
              style={{ width: `${cpuPct}%` }}
            />
          </div>
        </div>

        {/* Memory bar */}
        <div>
          <div className="flex items-center justify-between text-xs text-text-secondary mb-1">
            <span>{t.memoryUsage}</span>
            <span className="font-[family-name:var(--font-mono)]">
              {memUsage !== null ? formatBytes(memUsage) : "-"}
              {" / "}
              {memLimit !== null ? formatBytes(memLimit) : "-"}
            </span>
          </div>
          <div className="h-1.5 rounded-full bg-bar-track overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${memPct !== null ? getBarColor(memPct) : "bg-bar-track"}`}
              style={{ width: `${memPct ?? 0}%` }}
            />
          </div>
        </div>

        {/* API Access */}
        {(agent.api_server_url || agent.api_key_masked) && (
          <div className="rounded-md bg-background/50 border border-border-subtle p-2 space-y-1.5">
            <div className="flex items-center gap-1.5 text-xs">
              <span className="text-text-secondary shrink-0">{t.apiServerUrl}:</span>
              <span className="font-[family-name:var(--font-mono)] text-text-primary truncate flex-1 min-w-0" title={agent.api_server_url}>
                {agent.api_server_url || "-"}
              </span>
              {agent.api_server_url && (
                <button
                  onClick={() => handleCopy(agent.api_server_url, t.copyUrl)}
                  className="shrink-0 text-accent-cyan hover:text-accent-cyan/80"
                  title={t.copyUrl}
                >
                  <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
                    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
                  </svg>
                </button>
              )}
            </div>
            <div className="flex items-center gap-1.5 text-xs">
              <span className="text-text-secondary shrink-0">{t.apiKeyMasked}:</span>
              <span className="font-[family-name:var(--font-mono)] text-text-primary truncate">
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
                className="shrink-0 text-accent-cyan hover:text-accent-cyan/80"
                title={t.copyKey}
              >
                <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
                  <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
                </svg>
              </button>
              <div className="flex-1" />
              <button
                onClick={handleTestApi}
                disabled={testing || !isRunning}
                className="shrink-0 px-2 py-0.5 text-[10px] rounded border border-border hover:bg-surface text-text-secondary hover:text-text-primary disabled:opacity-50"
              >
                {testing ? "..." : t.testApiConnection}
              </button>
            </div>
            {testResult && (
              <div className={`text-[10px] ${testResult.success ? "text-success" : "text-accent-pink"}`}>
                {testResult.success ? t.testApiSuccess : t.testApiFailed}: {testResult.msg}
              </div>
            )}
          </div>
        )}

        {/* Footer: restart count, age, detail button */}
        <div className="flex items-center justify-between mt-1">
          <div className="flex items-center gap-3 text-xs text-text-secondary">
            {agent.restart_count > 0 && (
              <span className="inline-flex items-center rounded-full bg-accent-pink/20 text-accent-pink px-2 py-0.5 text-xs font-medium">
                {t.restartCount}: {agent.restart_count}
              </span>
            )}
            <span>{agent.age_human}</span>
          </div>
          <button
            onClick={() => navigate(`/agents/${agent.id}`)}
            className="text-xs text-accent-cyan hover:underline"
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
