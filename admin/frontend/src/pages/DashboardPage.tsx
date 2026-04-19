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
          <h1 className="text-2xl font-bold">{t.dashboard}</h1>
          <p className="text-sm text-muted-foreground">{t.dashboardSubtitle}</p>
        </div>
        <button
          onClick={() => navigate("/create")}
          className="h-9 px-4 text-sm rounded bg-primary text-white hover:bg-primary/90"
        >
          + {t.createAgent}
        </button>
      </div>

      {/* Cluster status bar */}
      {cluster && <ClusterStatusBar cluster={cluster} />}

      {/* Error banner (non-fatal, data may be stale) */}
      {error && (
        <div className="rounded-md bg-destructive/10 border border-destructive/20 p-3 mb-4">
          <p className="text-sm text-destructive">{error}</p>
        </div>
      )}

      {/* Agent grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {/* "+ New Agent" card */}
        <button
          onClick={() => navigate("/create")}
          className="rounded-lg border-2 border-dashed border-border hover:border-primary/50 bg-card/50 p-4 flex flex-col items-center justify-center gap-2 min-h-[180px] transition-colors"
        >
          <span className="text-3xl text-muted-foreground">+</span>
          <span className="text-sm text-muted-foreground">{t.createAgent}</span>
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
          <p className="text-lg font-medium">{t.noAgents}</p>
          <p className="text-sm text-muted-foreground">{t.noAgentsDesc}</p>
        </div>
      )}
    </div>
  );
}
