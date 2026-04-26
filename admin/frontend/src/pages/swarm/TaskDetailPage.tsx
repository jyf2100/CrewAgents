import { useState, useEffect, useCallback, useMemo } from "react";
import { useParams, useNavigate } from "react-router-dom";
import type { SwarmTask, TaskStatus } from "../../stores/swarmTasks";
import { useSwarmRegistry } from "../../stores/swarmRegistry";
import { adminFetch } from "../../lib/admin-api";
import { useI18n } from "../../hooks/useI18n";
import { LoadingSpinner } from "../../components/LoadingSpinner";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

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

function statusDotColor(status: TaskStatus): string {
  switch (status) {
    case "completed":
      return "bg-success";
    case "failed":
      return "bg-accent-pink";
    case "running":
      return "bg-accent-cyan";
    case "pending":
      return "bg-warning";
    default:
      return "bg-text-secondary";
  }
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
  return date.toLocaleString([], {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function truncateId(id: string): string {
  if (id.length <= 16) return id;
  return `${id.slice(0, 12)}...${id.slice(-4)}`;
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function TaskDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { t } = useI18n();
  const { agents, fetchAgents } = useSwarmRegistry();

  const [task, setTask] = useState<SwarmTask | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);

  const loadTask = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    setError(null);
    setNotFound(false);
    try {
      const result = await adminFetch<SwarmTask | null>(
        `/swarm/tasks/${id}`
      );
      if (result === null) {
        setNotFound(true);
      } else {
        setTask(result);
      }
    } catch (err) {
      setError(
        err instanceof Error ? err.message : t.errorLoadFailed
      );
    } finally {
      setLoading(false);
    }
  }, [id, t.errorLoadFailed]);

  useEffect(() => {
    loadTask();
  }, [loadTask]);

  useEffect(() => {
    fetchAgents();
  }, [fetchAgents]);

  // Agent name lookup
  const agentName = useMemo(() => {
    if (!task?.assigned_agent_id) return "-";
    const agent = agents.find(
      (a) => a.agent_id === task.assigned_agent_id
    );
    return agent ? agent.display_name : `#${task.assigned_agent_id}`;
  }, [task, agents]);

  // Loading
  if (loading) {
    return <LoadingSpinner />;
  }

  // Error
  if (error) {
    return (
      <div className="flex flex-col items-center justify-center py-24 gap-4">
        <div className="rounded-lg bg-surface border border-border-cyan/30 border-l-[3px] border-l-accent-pink p-6 max-w-md text-center">
          <p className="text-sm text-accent-pink font-[family-name:var(--font-mono)]">
            {error}
          </p>
        </div>
        <button
          onClick={loadTask}
          className="h-9 px-4 text-sm border border-accent-cyan text-accent-cyan rounded-lg hover:bg-accent-cyan/10 transition-colors"
        >
          {t.retry}
        </button>
      </div>
    );
  }

  // Not found
  if (notFound) {
    return (
      <div className="flex flex-col items-center justify-center py-24 gap-4">
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
            d="M9.75 9.75l4.5 4.5m0-4.5l-4.5 4.5M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
          />
        </svg>
        <p className="text-lg font-medium text-text-secondary">
          Task not found
        </p>
        <button
          onClick={() => navigate("/swarm/tasks")}
          className="h-9 px-4 text-sm border border-accent-cyan text-accent-cyan rounded-lg hover:bg-accent-cyan/10 transition-colors"
        >
          {t.back}
        </button>
      </div>
    );
  }

  if (!task) return null;

  const badgeClasses = statusBadgeClasses(task.status);
  const dotColor = statusDotColor(task.status);
  const pulseClass = task.status === "running" ? "animate-status-pulse" : "";

  return (
    <div>
      {/* Back button */}
      <button
        onClick={() => navigate("/swarm/tasks")}
        className="flex items-center gap-1.5 text-sm text-text-secondary hover:text-text-primary transition-colors mb-4"
        aria-label={t.taskMonitor}
      >
        <svg
          className="h-4 w-4"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
          aria-hidden="true"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M15.75 19.5L8.25 12l7.5-7.5"
          />
        </svg>
        {t.taskMonitor}
      </button>

      {/* Header: task ID + status badge */}
      <div className="flex items-center gap-3 mb-6">
        <h1 className="text-2xl font-semibold font-[family-name:var(--font-body)] text-text-primary">
          {t.taskId}: {truncateId(task.task_id)}
        </h1>
        <span
          className={`inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full border ${badgeClasses}`}
        >
          <span
            className={`inline-block h-2 w-2 rounded-full ${dotColor} ${pulseClass}`}
          />
          {task.status}
        </span>
      </div>

      {/* Metadata grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
        {/* Left card: Goal, Type, Agent */}
        <div className="rounded-lg border border-border bg-surface p-4 space-y-4 animate-stagger">
          {/* Goal */}
          <div>
            <p className="text-xs text-text-secondary mb-1">{t.taskGoal}</p>
            <p className="text-sm text-text-primary break-words">
              {task.goal || "-"}
            </p>
          </div>

          {/* Type */}
          <div>
            <p className="text-xs text-text-secondary mb-1">{t.taskType}</p>
            <p className="text-sm font-[family-name:var(--font-mono)] text-text-primary">
              {task.task_type || "-"}
            </p>
          </div>

          {/* Assigned Agent */}
          <div>
            <p className="text-xs text-text-secondary mb-1">{t.taskAgent}</p>
            <p className="text-sm font-[family-name:var(--font-mono)] text-text-primary">
              {agentName}
            </p>
          </div>
        </div>

        {/* Right card: Duration, Timestamp */}
        <div
          className="rounded-lg border border-border bg-surface p-4 space-y-4 animate-stagger"
          style={{ animationDelay: "80ms" }}
        >
          {/* Duration */}
          <div>
            <p className="text-xs text-text-secondary mb-1">
              {t.taskDuration}
            </p>
            <p className="text-sm font-[family-name:var(--font-mono)] text-text-primary">
              {formatDuration(task.duration_ms)}
            </p>
          </div>

          {/* Timestamp */}
          <div>
            <p className="text-xs text-text-secondary mb-1">{t.taskTime}</p>
            <p className="text-sm font-[family-name:var(--font-mono)] text-text-primary">
              {formatTimestamp(task.timestamp)}
            </p>
          </div>
        </div>
      </div>

      {/* Error panel */}
      {task.error && (
        <div className="rounded-lg border border-accent-pink/40 bg-accent-pink/5 p-4 animate-stagger"
          style={{ animationDelay: "160ms" }}
        >
          <p className="text-xs text-accent-pink mb-2 font-medium">Error</p>
          <pre className="text-sm text-accent-pink/90 font-[family-name:var(--font-mono)] whitespace-pre-wrap break-words">
            {task.error}
          </pre>
        </div>
      )}
    </div>
  );
}
