import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import type { AgentListItem, ClusterStatus } from "../lib/admin-api";
import { adminApi } from "../lib/admin-api";
import { useI18n } from "../hooks/useI18n";
import { ClusterStatusBar } from "../components/ClusterStatusBar";
import { AgentCard, statusOrder } from "../components/AgentCard";
import { LoadingSpinner } from "../components/LoadingSpinner";
import { ErrorDisplay } from "../components/ErrorDisplay";

export function DashboardPage() {
  const { t } = useI18n();
  const navigate = useNavigate();

  const [agents, setAgents] = useState<AgentListItem[]>([]);
  const [cluster, setCluster] = useState<ClusterStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    try {
      const [agentsRes, clusterRes] = await Promise.all([
        adminApi.listAgents(),
        adminApi.getClusterStatus(),
      ]);
      // Sort agents by status priority: failed > starting > stopped > running > unknown
      const sorted = [...agentsRes.agents].sort(
        (a, b) => statusOrder(a.status) - statusOrder(b.status)
      );
      setAgents(sorted);
      setCluster(clusterRes);
      setError(null);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : t.errorLoadFailed
      );
    } finally {
      setLoading(false);
    }
  }, [t]);

  // Initial load + auto-refresh every 10 seconds
  useEffect(() => {
    loadData();
    const interval = setInterval(loadData, 10_000);
    return () => clearInterval(interval);
  }, [loadData]);

  // Derive stats from agents array
  const runningCount = agents.filter((a) => a.status === "running").length;
  const stoppedCount = agents.filter(
    (a) => a.status === "stopped" || a.status === "unknown"
  ).length;
  const failedCount = agents.filter((a) => a.status === "failed").length;

  const stats = [
    {
      label: t.statusRunning,
      count: runningCount,
      borderColor: "border-l-accent-cyan",
      textColor: "text-accent-cyan",
    },
    {
      label: t.statusStopped,
      count: stoppedCount,
      borderColor: "border-l-text-secondary",
      textColor: "text-text-secondary",
    },
    {
      label: t.statusFailed,
      count: failedCount,
      borderColor: "border-l-accent-pink",
      textColor: "text-accent-pink",
    },
  ];

  if (loading) {
    return <LoadingSpinner />;
  }

  if (error && agents.length === 0 && cluster === null) {
    return <ErrorDisplay error={error} onRetry={loadData} />;
  }

  return (
    <div>
      {/* Page header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold font-[family-name:var(--font-body)] text-text-primary">
            {t.dashboard}
          </h1>
          <p className="text-sm text-text-secondary">{t.dashboardSubtitle}</p>
        </div>
        <button
          onClick={() => navigate("/create")}
          className="h-9 px-4 text-sm rounded-lg bg-accent-pink text-text-primary hover:shadow-[0_0_20px_rgba(255,42,109,0.3)] transition-all"
        >
          + {t.createAgent}
        </button>
      </div>

      {/* Stats row */}
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

      {/* Cluster status bar */}
      {cluster && <ClusterStatusBar cluster={cluster} />}

      {/* Error banner (non-fatal, data may be stale) */}
      {error && (
        <div className="bg-surface border-l-[3px] border-l-accent-pink p-3 rounded-lg mb-4">
          <p className="text-sm text-accent-pink">{error}</p>
        </div>
      )}

      {/* Agent grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
        {/* "+ New Agent" card */}
        <button
          onClick={() => navigate("/create")}
          className="rounded-lg border-2 border-dashed border-border hover:border-accent-cyan/50 bg-surface/30 p-4 flex flex-col items-center justify-center gap-2 min-h-[180px] transition-all hover:shadow-[0_0_20px_rgba(5,217,232,0.1)]"
        >
          <span className="text-3xl text-accent-cyan">+</span>
          <span className="text-sm text-text-secondary">{t.createAgent}</span>
        </button>

        {/* Agent cards */}
        {agents.map((agent) => (
          <AgentCard
            key={agent.id}
            agent={agent}
            onActionDone={loadData}
          />
        ))}
      </div>

      {/* Empty state */}
      {agents.length === 0 && !loading && (
        <div className="flex flex-col items-center justify-center py-16 gap-3">
          <svg
            className="h-12 w-12 text-text-secondary mb-2"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={1}
            aria-hidden="true"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4"
            />
          </svg>
          <p className="text-lg font-medium text-text-secondary">{t.noAgents}</p>
          <p className="text-sm text-text-secondary">{t.noAgentsDesc}</p>
          <button
            onClick={() => navigate("/create")}
            className="mt-2 text-sm text-accent-cyan hover:underline"
          >
            {t.createAgent}
          </button>
        </div>
      )}
    </div>
  );
}
