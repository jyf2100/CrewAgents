import { useEffect, useState, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { adminApi, type OrchestratorTask } from "../../lib/admin-api";
import { useI18n } from "../../hooks/useI18n";

export function TaskDetailPage() {
  const { taskId } = useParams<{ taskId: string }>();
  const { t } = useI18n();
  const navigate = useNavigate();
  const [task, setTask] = useState<OrchestratorTask | null>(null);
  const [loading, setLoading] = useState(true);

  const loadTask = useCallback(async () => {
    if (!taskId) return;
    try {
      const data = await adminApi.orchestratorGetTask(taskId);
      setTask(data);
    } catch {
      setTask(null);
    } finally {
      setLoading(false);
    }
  }, [taskId]);

  useEffect(() => {
    loadTask();
    if (!task || ["done", "failed"].includes(task.status)) return;
    const interval = setInterval(loadTask, 5000);
    return () => clearInterval(interval);
  }, [loadTask, task?.status]);

  const handleCancel = async () => {
    if (!taskId) return;
    try {
      await adminApi.orchestratorCancelTask(taskId);
      loadTask();
    } catch {
      // silently fail
    }
  };

  if (loading) return <div className="p-6 text-text-secondary">Loading...</div>;
  if (!task) return <div className="p-6 text-red-400">Task not found</div>;

  const isActive = !["done", "failed"].includes(task.status);

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <button onClick={() => navigate("/admin/orchestrator")} className="text-text-muted hover:text-text-primary">&larr; Back</button>
          <h1 className="text-lg font-mono text-text-primary">{task.task_id.slice(0, 16)}...</h1>
          <StatusBadge status={task.status} />
        </div>
        {isActive && task.status !== "executing" && task.status !== "streaming" && (
          <button onClick={handleCancel} className="px-3 py-1.5 bg-red-500/20 text-red-400 rounded-md text-sm hover:bg-red-500/30">{t.orchestratorCancelTask || "Cancel Task"}</button>
        )}
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <InfoCard label={t.orchestratorTaskAgent || "Agent"} value={task.assigned_agent || "—"} />
        <InfoCard label="Run ID" value={task.run_id || "—"} monospace />
        <InfoCard label={t.orchestratorTaskRetries || "Retries"} value={String(task.retry_count)} />
        <InfoCard label={t.orchestratorTaskCreated || "Created"} value={new Date(task.created_at * 1000).toLocaleString()} />
      </div>

      {task.result && (
        <section className="bg-surface/50 rounded-lg border border-border/50 p-4">
          <h2 className="text-sm font-semibold text-text-primary mb-2">{t.orchestratorTaskResult || "Result"}</h2>
          <pre className="text-sm text-text-primary whitespace-pre-wrap bg-surface/80 rounded p-3 max-h-96 overflow-y-auto">{task.result.content}</pre>
          <div className="mt-3 flex gap-6 text-xs text-text-muted">
            <span>Tokens: {task.result.usage?.total_tokens ?? "—"}</span>
            <span>Duration: {task.result.duration_seconds?.toFixed(1)}s</span>
          </div>
        </section>
      )}

      {task.error && (
        <section className="bg-red-500/10 border border-red-500/30 rounded-lg p-4">
          <h2 className="text-sm font-semibold text-red-400 mb-1">{t.orchestratorTaskError || "Error"}</h2>
          <p className="text-sm text-red-300">{task.error}</p>
        </section>
      )}
    </div>
  );
}

function InfoCard({ label, value, monospace }: { label: string; value: string; monospace?: boolean }) {
  return (
    <div className="bg-surface/50 rounded-lg border border-border/50 p-3">
      <p className="text-text-muted text-xs">{label}</p>
      <p className={`text-sm text-text-primary ${monospace ? "font-mono" : ""}`}>{value}</p>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    done: "bg-green-500/20 text-green-400",
    failed: "bg-red-500/20 text-red-400",
    executing: "bg-blue-500/20 text-blue-400",
    streaming: "bg-blue-500/20 text-blue-400",
    queued: "bg-gray-500/20 text-gray-400",
    assigned: "bg-gray-500/20 text-gray-400",
  };
  return <span className={`px-2 py-0.5 rounded text-xs font-medium ${colors[status] || "bg-gray-500/20 text-gray-400"}`}>{status}</span>;
}
