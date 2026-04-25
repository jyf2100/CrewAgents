import { useState, useEffect, useCallback } from "react";
import type { SwarmAgent } from "../../stores/swarmRegistry";
import type { RedisHealth } from "../../components/RedisHealthCard";
import { adminFetch } from "../../lib/admin-api";
import { useI18n } from "../../hooks/useI18n";
import { RedisHealthCard } from "../../components/RedisHealthCard";
import { LoadingSpinner } from "../../components/LoadingSpinner";
import { ErrorDisplay } from "../../components/ErrorDisplay";

// ---------------------------------------------------------------------------
// API response types
// ---------------------------------------------------------------------------

interface SwarmMetricsResponse {
  timestamp: number;
  swarm_enabled: boolean;
  agents: SwarmAgent[];
  agents_online: number;
  agents_offline: number;
  agents_busy: number;
  queues: {
    streams: { name: string; pending: number }[];
    total_pending: number;
  };
  redis_health: RedisHealth;
  tasks_submitted_last_5m: number;
  tasks_completed_last_5m: number;
  tasks_failed_last_5m: number;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function swarmStatusDotColor(status: string): string {
  switch (status) {
    case "online":
      return "bg-success";
    case "busy":
      return "bg-warning";
    case "offline":
      return "bg-text-secondary";
    default:
      return "bg-text-secondary";
  }
}

function swarmStatusLabel(status: string, t: Record<string, string>): string {
  switch (status) {
    case "online":
      return t.statusRunning;
    case "busy":
      return t.statusUpdating;
    case "offline":
      return t.statusStopped;
    default:
      return t.statusUnknown;
  }
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function SwarmOverviewPage() {
  const { t } = useI18n();

  const [agents, setAgents] = useState<SwarmAgent[]>([]);
  const [metrics, setMetrics] = useState<SwarmMetricsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    try {
      const [agentsRes, metricsRes] = await Promise.all([
        adminFetch<SwarmAgent[]>("/swarm/agents"),
        adminFetch<SwarmMetricsResponse>("/swarm/metrics"),
      ]);
      setAgents(agentsRes);
      setMetrics(metricsRes);
      setError(null);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : t.errorLoadFailed
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
    const interval = setInterval(loadData, 10_000);
    return () => clearInterval(interval);
  }, [loadData]);

  if (loading) {
    return <LoadingSpinner />;
  }

  if (error && agents.length === 0 && metrics === null) {
    return <ErrorDisplay error={error} onRetry={loadData} />;
  }

  const onlineCount = metrics?.agents_online ?? agents.filter((a) => a.status === "online").length;
  const busyCount = metrics?.agents_busy ?? agents.filter((a) => a.status === "busy").length;
  const offlineCount = metrics?.agents_offline ?? agents.filter((a) => a.status === "offline").length;
  const totalCount = agents.length;

  const stats = [
    {
      label: t.statusRunning,
      count: onlineCount,
      borderColor: "border-l-success",
      textColor: "text-success",
    },
    {
      label: t.statusUpdating,
      count: busyCount,
      borderColor: "border-l-warning",
      textColor: "text-warning",
    },
    {
      label: t.statusStopped,
      count: offlineCount,
      borderColor: "border-l-text-secondary",
      textColor: "text-text-secondary",
    },
    {
      label: t.totalAgents,
      count: totalCount,
      borderColor: "border-l-accent-cyan",
      textColor: "text-accent-cyan",
    },
  ];

  return (
    <div>
      {/* Page header */}
      <div className="mb-6">
        <h1 className="text-2xl font-semibold font-[family-name:var(--font-body)] text-text-primary">
          {t.swarmOverview}
        </h1>
        <p className="text-sm text-text-secondary">{t.swarmAgents}</p>
      </div>

      {/* Error banner (non-fatal) */}
      {error && (
        <div className="bg-surface border-l-[3px] border-l-accent-pink p-3 rounded-lg mb-4">
          <p className="text-sm text-accent-pink">{error}</p>
        </div>
      )}

      {/* Stats row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        {stats.map((stat, i) => (
          <div
            key={stat.label}
            className="animate-stagger bg-surface rounded-lg px-4 py-3 border-l-[3px]"
            style={{ animationDelay: `${i * 80}ms` }}
          >
            <p className="text-xs text-text-secondary mb-0.5">{stat.label}</p>
            <p
              className={`text-2xl font-semibold font-[family-name:var(--font-body)] ${stat.textColor}`}
            >
              {stat.count}
            </p>
          </div>
        ))}
      </div>

      {/* Main content: agent grid + sidebar */}
      <div className="flex flex-col lg:flex-row gap-6">
        {/* Agent grid */}
        <div className="flex-1 min-w-0">
          {agents.length === 0 ? (
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
              <p className="text-lg font-medium text-text-secondary">
                {t.swarmNoAgents}
              </p>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {agents.map((agent, i) => (
                <SwarmAgentCard
                  key={agent.agent_id}
                  agent={agent}
                  t={t}
                  delay={i * 60}
                />
              ))}
            </div>
          )}
        </div>

        {/* Sidebar: Redis health */}
        <div className="w-full lg:w-72 shrink-0 space-y-4">
          {metrics?.redis_health && (
            <div className="animate-stagger" style={{ animationDelay: `${agents.length * 60}ms` }}>
              <h3 className="text-sm font-medium text-text-primary mb-2">
                {t.swarmHealth}
              </h3>
              <RedisHealthCard health={metrics.redis_health} />
            </div>
          )}

          {/* Task throughput */}
          {metrics && (
            <div className="animate-stagger rounded-lg border border-border bg-surface p-4" style={{ animationDelay: `${agents.length * 60 + 80}ms` }}>
              <h3 className="text-sm font-medium text-text-primary mb-3">
                {t.last5min}
              </h3>
              <div className="space-y-1.5 text-xs">
                <div className="flex justify-between">
                  <span className="text-text-secondary">{t.submitted}</span>
                  <span className="font-[family-name:var(--font-mono)] text-text-primary">
                    {metrics.tasks_submitted_last_5m}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-text-secondary">{t.completed}</span>
                  <span className="font-[family-name:var(--font-mono)] text-success">
                    {metrics.tasks_completed_last_5m}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-text-secondary">{t.failed}</span>
                  <span className="font-[family-name:var(--font-mono)] text-accent-pink">
                    {metrics.tasks_failed_last_5m}
                  </span>
                </div>
                {metrics.queues.total_pending > 0 && (
                  <div className="flex justify-between">
                    <span className="text-text-secondary">{t.queued}</span>
                    <span className="font-[family-name:var(--font-mono)] text-warning">
                      {metrics.queues.total_pending}
                    </span>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// SwarmAgentCard
// ---------------------------------------------------------------------------

function SwarmAgentCard({
  agent,
  t,
  delay,
}: {
  agent: SwarmAgent;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  t: any;
  delay: number;
}) {
  const loadPercent =
    agent.max_concurrent_tasks > 0
      ? Math.round((agent.current_tasks / agent.max_concurrent_tasks) * 100)
      : 0;

  const loadBarColor =
    loadPercent >= 90
      ? "bg-accent-pink"
      : loadPercent >= 70
        ? "bg-warning"
        : "bg-accent-cyan";

  return (
    <div
      className="animate-stagger rounded-lg border border-border bg-surface p-4 hover:border-accent-cyan/30 transition-colors"
      style={{ animationDelay: `${delay}ms` }}
    >
      {/* Header: name + status */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span
            className={`inline-block h-2.5 w-2.5 rounded-full ${swarmStatusDotColor(agent.status)} ${
              agent.status === "online" ? "animate-status-pulse" : ""
            }`}
          />
          <h4 className="text-sm font-medium text-text-primary">
            {agent.display_name}
          </h4>
        </div>
        <span className="text-xs text-text-secondary">
          {swarmStatusLabel(agent.status, t)}
        </span>
      </div>

      {/* Capabilities tags */}
      {agent.capabilities.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-3">
          {agent.capabilities.map((cap) => (
            <span
              key={cap}
              className="inline-block text-[10px] px-2 py-0.5 rounded-full bg-accent-cyan/10 text-accent-cyan border border-accent-cyan/20"
            >
              {cap}
            </span>
          ))}
        </div>
      )}

      {/* Load bar */}
      <div className="mb-1">
        <div className="flex items-center justify-between text-xs text-text-secondary mb-1">
          <span>
            {t.load}: {agent.current_tasks}/{agent.max_concurrent_tasks}
          </span>
          <span className="font-[family-name:var(--font-mono)]">
            {loadPercent}%
          </span>
        </div>
        <div className="h-1.5 rounded-full bg-bar-track overflow-hidden">
          <div
            className={`h-full rounded-full transition-all ${loadBarColor}`}
            style={{ width: `${loadPercent}%` }}
          />
        </div>
      </div>

      {/* Model info */}
      <div className="mt-2 text-xs text-text-secondary">
        {t.model}: <span className="font-[family-name:var(--font-mono)] text-text-primary">{agent.model}</span>
      </div>
    </div>
  );
}
