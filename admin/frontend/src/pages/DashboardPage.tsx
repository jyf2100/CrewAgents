import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import type { AgentListItem, ClusterStatus, UserResponse } from "../lib/admin-api";
import { adminApi, getAuthMode } from "../lib/admin-api";
import { useI18n } from "../hooks/useI18n";
import { ClusterStatusBar } from "../components/ClusterStatusBar";
import { AgentCard } from "../components/AgentCard";
import { LoadingSpinner } from "../components/LoadingSpinner";
import { statusOrder } from "../lib/utils";
import { ErrorDisplay } from "../components/ErrorDisplay";

function ProvisioningBadge({ status, error, t }: {
  status: string;
  error: string | null;
  t: Record<string, string>;
}) {
  const styles: Record<string, string> = {
    completed: "bg-green-500/15 text-green-400",
    pending: "bg-yellow-500/15 text-yellow-400",
    failed: "bg-red-500/15 text-red-400",
    not_started: "bg-gray-500/15 text-gray-400",
  };
  const labels: Record<string, string> = {
    completed: t.provisionCompleted,
    pending: t.provisionPending,
    failed: t.provisionFailed,
    not_started: t.provisionNotStarted,
  };

  return (
    <div className="flex items-center gap-1.5">
      <span className={`inline-block px-2 py-0.5 rounded text-xs ${styles[status] || styles.not_started}`}>
        {labels[status] || status}
      </span>
      {status === "pending" && (
        <span className="inline-block w-3 h-3 border-2 border-yellow-400 border-t-transparent rounded-full animate-spin" />
      )}
      {status === "failed" && error && (
        <span className="text-xs text-red-400/70 truncate max-w-[120px]" title={error}>!</span>
      )}
    </div>
  );
}

export function DashboardPage() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const isUser = getAuthMode() === "user" || getAuthMode() === "email";

  const [agents, setAgents] = useState<AgentListItem[]>([]);
  const [cluster, setCluster] = useState<ClusterStatus | null>(null);
  const [users, setUsers] = useState<UserResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activateTarget, setActivateTarget] = useState<number | null>(null);
  const [activateAgentId, setActivateAgentId] = useState("");
  const [webuiLoading, setWebuiLoading] = useState<number | null>(null);

  const loadData = useCallback(async () => {
    try {
      const agentsRes = await adminApi.listAgents();
      const sorted = [...agentsRes.agents].sort(
        (a, b) => statusOrder(a.status) - statusOrder(b.status)
      );
      setAgents(sorted);
      setError(null);
      if (!isUser) {
        try {
          const clusterRes = await adminApi.getClusterStatus();
          setCluster(clusterRes);
        } catch { /* non-critical */ }
        try {
          const usersRes = await adminApi.listUsers();
          setUsers(usersRes.users);
        } catch { /* non-critical */ }
      }
    } catch (err) {
      setError(
        err instanceof Error ? err.message : t.errorLoadFailed
      );
    } finally {
      setLoading(false);
    }
  }, [t, isUser]);

  useEffect(() => {
    loadData();
    const interval = setInterval(loadData, 10_000);
    return () => clearInterval(interval);
  }, [loadData]);

  const runningCount = agents.filter((a) => a.status === "running").length;
  const stoppedCount = agents.filter(
    (a) => a.status === "stopped" || a.status === "unknown"
  ).length;
  const failedCount = agents.filter((a) => a.status === "failed").length;

  const stats = [
    { label: t.statusRunning, count: runningCount, borderColor: "border-l-accent-cyan", textColor: "text-accent-cyan" },
    { label: t.statusStopped, count: stoppedCount, borderColor: "border-l-text-secondary", textColor: "text-text-secondary" },
    { label: t.statusFailed, count: failedCount, borderColor: "border-l-accent-pink", textColor: "text-accent-pink" },
  ];

  async function handleOpenWebUI(user: UserResponse) {
    setWebuiLoading(user.id);
    try {
      const res = await adminApi.getWebUILoginUrl();
      window.open(res.url, "_blank");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to get WebUI URL");
    } finally {
      setWebuiLoading(null);
    }
  }

  if (loading) {
    return <LoadingSpinner />;
  }

  if (error && agents.length === 0 && cluster === null) {
    return <ErrorDisplay error={error} onRetry={loadData} />;
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold font-[family-name:var(--font-body)] text-text-primary">
            {t.dashboard}
          </h1>
          <p className="text-sm text-text-secondary">{t.dashboardSubtitle}</p>
        </div>
        {!isUser && (
          <button
            onClick={() => navigate("/create")}
            className="h-9 px-4 text-sm rounded-lg bg-accent-pink text-text-primary hover:shadow-[0_0_20px_rgba(255,42,109,0.3)] transition-all"
          >
            + {t.createAgent}
          </button>
        )}
      </div>

      {agents.length > 0 && (
        <div className="grid grid-cols-3 gap-4 mb-6">
          {stats.map((stat, i) => (
            <div
              key={stat.label}
              className={`animate-stagger bg-surface rounded-lg px-4 py-3 border-l-[3px] ${stat.borderColor}`}
              style={{ animationDelay: `${i * 80}ms` }}
            >
              <p className="text-xs text-text-secondary mb-0.5">{stat.label}</p>
              <p className={`text-2xl font-semibold font-[family-name:var(--font-body)] ${stat.textColor}`}>
                {stat.count}
              </p>
            </div>
          ))}
        </div>
      )}

      {cluster && <ClusterStatusBar cluster={cluster} />}

      {error && (
        <div className="bg-surface border-l-[3px] border-l-accent-pink p-3 rounded-lg mb-4">
          <p className="text-sm text-accent-pink">{error}</p>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
        {!isUser && (
          <button
            onClick={() => navigate("/create")}
            className="rounded-lg border-2 border-dashed border-border hover:border-accent-cyan/50 bg-surface/30 p-4 flex flex-col items-center justify-center gap-2 min-h-[180px] transition-all hover:shadow-[0_0_0_20px_rgba(5,217,232,0.1)]"
          >
            <span className="text-3xl text-accent-cyan">+</span>
            <span className="text-sm text-text-secondary">{t.createAgent}</span>
          </button>
        )}

        {agents.map((agent) => (
          <AgentCard key={agent.id} agent={agent} onActionDone={loadData} />
        ))}
      </div>

      {/* User Management — admin only */}
      {!isUser && (
        <div className="mt-8">
          <h2 className="text-lg font-semibold text-text-primary mb-3">{t.userManagement}</h2>
          {users.length === 0 ? (
            <p className="text-sm text-text-secondary">{t.noUsers}</p>
          ) : (
            <div className="bg-surface rounded-lg border border-border overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-text-secondary text-xs">
                    <th className="px-4 py-2 text-left">Email</th>
                    <th className="px-4 py-2 text-left">{t.displayName}</th>
                    <th className="px-4 py-2 text-left">Agent</th>
                    <th className="px-4 py-2 text-left">{t.agentStatus}</th>
                    <th className="px-4 py-2 text-left">{t.provisionStatus}</th>
                    <th className="px-4 py-2 text-right">{t.agentActions}</th>
                  </tr>
                </thead>
                <tbody>
                  {users.map((user) => (
                    <tr key={user.id} className="border-b border-border/50 hover:bg-surface/50">
                      <td className="px-4 py-2.5 text-text-primary">{user.email}</td>
                      <td className="px-4 py-2.5 text-text-secondary">{user.display_name || "-"}</td>
                      <td className="px-4 py-2.5 text-text-secondary">
                        {user.agent_id != null ? `#${user.agent_id}` : "-"}
                      </td>
                      <td className="px-4 py-2.5">
                        <span className={`inline-block px-2 py-0.5 rounded text-xs ${
                          user.is_active
                            ? "bg-green-500/15 text-green-400"
                            : "bg-yellow-500/15 text-yellow-400"
                        }`}>
                          {user.is_active ? t.userActive : t.userInactive}
                        </span>
                      </td>
                      <td className="px-4 py-2.5">
                        <ProvisioningBadge
                          status={user.provisioning_status || "not_started"}
                          error={user.provisioning_error}
                          t={t as unknown as Record<string, string>}
                        />
                      </td>
                      <td className="px-4 py-2.5 text-right">
                        {activateTarget === user.id ? (
                          <div className="flex items-center gap-1.5 justify-end">
                            <input
                              type="number"
                              value={activateAgentId}
                              onChange={(e) => setActivateAgentId(e.target.value)}
                              placeholder="Agent #"
                              className="w-20 h-7 px-2 text-xs rounded border border-border-subtle bg-background text-text-primary"
                            />
                            <button
                              onClick={async () => {
                                try {
                                  await adminApi.activateUser(user.id, parseInt(activateAgentId));
                                  setActivateTarget(null);
                                  setActivateAgentId("");
                                  loadData();
                                } catch (err) {
                                  setError(err instanceof Error ? err.message : "Failed");
                                }
                              }}
                              className="px-2 py-1 text-xs rounded bg-accent-cyan/20 text-accent-cyan hover:bg-accent-cyan/30"
                            >
                              {t.confirm}
                            </button>
                            <button
                              onClick={() => { setActivateTarget(null); setActivateAgentId(""); }}
                              className="px-2 py-1 text-xs rounded bg-surface text-text-secondary hover:text-text-primary"
                            >
                              {t.cancel}
                            </button>
                          </div>
                        ) : (
                          <div className="flex items-center gap-2 justify-end">
                            {!user.is_active && (
                              <button
                                onClick={() => { setActivateTarget(user.id); setActivateAgentId(""); }}
                                className="px-2 py-1 text-xs rounded bg-accent-cyan/20 text-accent-cyan hover:bg-accent-cyan/30"
                              >
                                {t.activateUser}
                              </button>
                            )}
                            {user.provisioning_status === "completed" && (
                              <button
                                onClick={() => handleOpenWebUI(user)}
                                disabled={webuiLoading === user.id}
                                className="px-2 py-1 text-xs rounded bg-green-500/20 text-green-400 hover:bg-green-500/30 disabled:opacity-50"
                              >
                                {webuiLoading === user.id ? "..." : t.startChat}
                              </button>
                            )}
                            {user.provisioning_status === "failed" && (
                              <button
                                onClick={async () => {
                                  try {
                                    await adminApi.retryProvision(user.id);
                                    loadData();
                                  } catch (err) {
                                    setError(err instanceof Error ? err.message : "Retry failed");
                                  }
                                }}
                                className="px-2 py-1 text-xs rounded bg-yellow-500/20 text-yellow-400 hover:bg-yellow-500/30"
                              >
                                {t.retry}
                              </button>
                            )}
                            <button
                              onClick={async () => {
                                if (!window.confirm(t.userDeleteConfirm)) return;
                                try {
                                  await adminApi.deleteUser(user.id);
                                  loadData();
                                } catch (err) {
                                  setError(err instanceof Error ? err.message : "Failed");
                                }
                              }}
                              className="px-2 py-1 text-xs rounded bg-accent-pink/20 text-accent-pink hover:bg-accent-pink/30"
                            >
                              {t.deleteUser}
                            </button>
                          </div>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {agents.length === 0 && !loading && (
        <div className="flex flex-col items-center justify-center py-16 gap-3">
          <svg className="h-12 w-12 text-text-secondary mb-2" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1} aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4" />
          </svg>
          <p className="text-lg font-medium text-text-secondary">{t.noAgents}</p>
          <p className="text-sm text-text-secondary">{t.noAgentsDesc}</p>
          {!isUser && (
            <button onClick={() => navigate("/create")} className="mt-2 text-sm text-accent-cyan hover:underline">
              {t.createAgent}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
