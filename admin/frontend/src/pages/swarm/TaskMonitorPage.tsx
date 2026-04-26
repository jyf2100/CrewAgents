import { useState, useEffect, useCallback, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import type { SwarmTask, TaskStatus } from "../../stores/swarmTasks";
import { useSwarmTasks } from "../../stores/swarmTasks";
import { useSwarmRegistry } from "../../stores/swarmRegistry";
import { useSwarmEvents } from "../../stores/swarmEvents";
import { useI18n } from "../../hooks/useI18n";
import { LoadingSpinner } from "../../components/LoadingSpinner";
import { ErrorDisplay } from "../../components/ErrorDisplay";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

type FilterKey = "all" | TaskStatus;

const FILTERS: FilterKey[] = ["all", "completed", "failed", "running", "pending"];

function statusBadgeClasses(status: TaskStatus): string {
  switch (status) {
    case "completed":
      return "bg-success/10 text-success border-success/20";
    case "failed":
      return "bg-accent-pink/10 text-accent-pink border-accent-pink/20";
    case "running":
      return "bg-accent-cyan/10 text-accent-cyan border-accent-cyan/20";
    case "pending":
      return "bg-warning/10 text-warning border-warning/20";
    default:
      return "bg-text-secondary/10 text-text-secondary border-text-secondary/20";
  }
}

function statusDotPulse(status: TaskStatus): string {
  return status === "running" ? "animate-status-pulse" : "";
}

function formatDuration(ms: number | null): string {
  if (ms === null) return "-";
  if (ms < 1000) return `${ms}ms`;
  const seconds = Math.floor(ms / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const remaining = seconds % 60;
  return `${minutes}m ${remaining}s`;
}

function formatTimestamp(epoch: number): string {
  const date = new Date(epoch * 1000);
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function truncateId(id: string): string {
  if (id.length <= 12) return id;
  return `${id.slice(0, 8)}...`;
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function TaskMonitorPage() {
  const { t } = useI18n();
  const navigate = useNavigate();

  const [activeFilter, setActiveFilter] = useState<FilterKey>("all");

  const { tasks, loading, error, fetchTasks } = useSwarmTasks();
  const { agents, fetchAgents } = useSwarmRegistry();
  const { connect, connected } = useSwarmEvents();

  // Build agent lookup map
  const agentMap = useMemo(() => {
    const map = new Map<number, string>();
    for (const agent of agents) {
      map.set(agent.agent_id, agent.display_name);
    }
    return map;
  }, [agents]);

  // Initial data load
  const loadInitial = useCallback(async () => {
    await Promise.all([fetchTasks(), fetchAgents()]);
  }, [fetchTasks, fetchAgents]);

  useEffect(() => {
    loadInitial();
  }, [loadInitial]);

  // SSE connection
  useEffect(() => {
    connect("/admin/api");
  }, [connect]);

  // 15s polling
  useEffect(() => {
    const interval = setInterval(fetchTasks, 15_000);
    return () => clearInterval(interval);
  }, [fetchTasks]);

  // Filter tasks
  const filteredTasks = useMemo(() => {
    if (activeFilter === "all") return tasks;
    return tasks.filter((task) => task.status === activeFilter);
  }, [tasks, activeFilter]);

  // Filter label helper
  function filterLabel(key: FilterKey): string {
    switch (key) {
      case "all":
        return t.taskFilterAll;
      case "completed":
        return t.taskFilterCompleted;
      case "failed":
        return t.taskFilterFailed;
      case "running":
        return t.taskFilterRunning;
      case "pending":
        return t.taskFilterPending;
    }
  }

  // Loading
  if (loading && tasks.length === 0) {
    return <LoadingSpinner />;
  }

  // Error (fatal)
  if (error && tasks.length === 0) {
    return <ErrorDisplay error={error} onRetry={loadInitial} />;
  }

  return (
    <div>
      {/* Page header */}
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold font-[family-name:var(--font-body)] text-text-primary">
            {t.taskMonitor}
          </h1>
          <p className="text-sm text-text-secondary mt-0.5">
            {connected ? t.swarmConnected : t.swarmDisconnected}
          </p>
        </div>
      </div>

      {/* Error banner (non-fatal) */}
      {error && (
        <div className="bg-surface border-l-[3px] border-l-accent-pink p-3 rounded-lg mb-4">
          <p className="text-sm text-accent-pink">{error}</p>
        </div>
      )}

      {/* Filter bar */}
      <div className="flex flex-wrap gap-2 mb-6" role="tablist" aria-label="Task status filters">
        {FILTERS.map((key) => {
          const isActive = activeFilter === key;
          return (
            <button
              key={key}
              role="tab"
              aria-selected={isActive}
              onClick={() => setActiveFilter(key)}
              className={[
                "px-3 py-1.5 text-xs rounded-md border transition-colors duration-150",
                "font-[family-name:var(--font-mono)]",
                isActive
                  ? "border-accent-cyan bg-accent-cyan/10 text-accent-cyan"
                  : "border-border text-text-secondary hover:text-text-primary hover:border-text-secondary/30",
              ].join(" ")}
            >
              {filterLabel(key)}
            </button>
          );
        })}
      </div>

      {/* Content */}
      {filteredTasks.length === 0 ? (
        /* Empty state */
        <div className="flex flex-col items-center justify-center py-16 gap-3 animate-stagger">
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
              d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"
            />
          </svg>
          <p className="text-lg font-medium text-text-secondary">
            {t.taskNoTasks}
          </p>
        </div>
      ) : (
        /* Task table */
        <div className="bg-surface rounded-lg border border-border overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-text-secondary text-xs uppercase tracking-wider">
                  <th className="text-left px-4 py-3 font-medium">{t.taskId}</th>
                  <th className="text-left px-4 py-3 font-medium">{t.taskGoal}</th>
                  <th className="text-left px-4 py-3 font-medium">{t.taskStatus}</th>
                  <th className="text-left px-4 py-3 font-medium">{t.taskAgent}</th>
                  <th className="text-left px-4 py-3 font-medium">{t.taskDuration}</th>
                  <th className="text-left px-4 py-3 font-medium">{t.taskTime}</th>
                </tr>
              </thead>
              <tbody>
                {filteredTasks.map((task, i) => (
                  <TaskRow
                    key={task.task_id}
                    task={task}
                    agentName={
                      task.assigned_agent_id !== null
                        ? agentMap.get(task.assigned_agent_id) ?? `#${task.assigned_agent_id}`
                        : "-"
                    }
                    delay={i * 40}
                    onClick={() => navigate(`/swarm/tasks/${task.task_id}`)}
                    t={t}
                  />
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// TaskRow
// ---------------------------------------------------------------------------

interface TaskRowProps {
  task: SwarmTask;
  agentName: string;
  delay: number;
  onClick: () => void;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  t: any;
}

function TaskRow({ task, agentName, delay, onClick, t }: TaskRowProps) {
  const badgeClasses = statusBadgeClasses(task.status);
  const pulseClass = statusDotPulse(task.status);

  return (
    <tr
      className="animate-stagger border-b border-border/50 last:border-b-0 hover:bg-surface/80 cursor-pointer transition-colors"
      style={{ animationDelay: `${delay}ms` }}
      onClick={onClick}
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onClick();
        }
      }}
      role="link"
      aria-label={`${t.taskId} ${truncateId(task.task_id)}`}
    >
      {/* Task ID */}
      <td className="px-4 py-3">
        <span className="font-[family-name:var(--font-mono)] text-xs text-text-secondary">
          {truncateId(task.task_id)}
        </span>
      </td>

      {/* Goal */}
      <td className="px-4 py-3">
        <span className="text-text-primary line-clamp-1 max-w-[200px] lg:max-w-[320px]">
          {task.goal || "-"}
        </span>
      </td>

      {/* Status */}
      <td className="px-4 py-3">
        <span
          className={`inline-flex items-center gap-1.5 text-xs px-2 py-0.5 rounded-full border ${badgeClasses}`}
        >
          <span
            className={`inline-block h-1.5 w-1.5 rounded-full ${badgeClasses.split(" ")[0]} ${pulseClass}`}
          />
          {task.status}
        </span>
      </td>

      {/* Agent */}
      <td className="px-4 py-3">
        <span className="font-[family-name:var(--font-mono)] text-xs">
          {agentName}
        </span>
      </td>

      {/* Duration */}
      <td className="px-4 py-3">
        <span className="font-[family-name:var(--font-mono)] text-xs text-text-secondary">
          {formatDuration(task.duration_ms)}
        </span>
      </td>

      {/* Time */}
      <td className="px-4 py-3">
        <span className="font-[family-name:var(--font-mono)] text-xs text-text-secondary">
          {formatTimestamp(task.timestamp)}
        </span>
      </td>
    </tr>
  );
}
