import { useEffect, useState, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { adminApi, type OrchestratorTask, type RoutingInfo } from "../../lib/admin-api";
import { useI18n } from "../../hooks/useI18n";
import { TaskStatusBadge } from "../../components/OrchestratorBadges";

export function TaskDetailPage() {
  const { taskId } = useParams<{ taskId: string }>();
  const { t } = useI18n();
  const navigate = useNavigate();
  const [task, setTask] = useState<OrchestratorTask | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const loadTask = useCallback(async () => {
    if (!taskId) return;
    try {
      const data = await adminApi.orchestratorGetTask(taskId);
      setTask(data);
      setError("");
    } catch {
      setTask(null);
      setError(t.errorLoadFailed || "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [taskId, t]);

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
      setError(t.orchestratorCancelFailed || "Failed to cancel task");
    }
  };

  if (loading) return <div className="p-6 text-text-secondary">{t.loading}</div>;

  if (error && !task) {
    return <div className="p-6 text-red-400">{t.taskNotFound}</div>;
  }

  if (!task) return null;

  const isActive = !["done", "failed"].includes(task.status);

  return (
    <div className="p-6 space-y-6">
      {error && (
        <div className="px-3 py-2 bg-red-500/10 border border-red-500/30 rounded text-red-400 text-sm">
          {error}
        </div>
      )}

      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <button onClick={() => navigate("/orchestrator")} className="text-text-muted hover:text-text-primary">
            &larr; {t.back}
          </button>
          <h1 className="text-lg font-mono text-text-primary">{task.task_id.slice(0, 16)}...</h1>
          <TaskStatusBadge status={task.status} />
        </div>
        {isActive && task.status !== "executing" && task.status !== "streaming" && (
          <button onClick={handleCancel} className="px-3 py-1.5 bg-red-500/20 text-red-400 rounded-md text-sm hover:bg-red-500/30">
            {t.orchestratorCancelTask}
          </button>
        )}
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <InfoCard label={t.orchestratorTaskAgent} value={task.assigned_agent || "—"} />
        <InfoCard label={t.runId} value={task.run_id || "—"} monospace />
        <InfoCard label={t.orchestratorTaskRetries} value={String(task.retry_count)} />
        <InfoCard label={t.orchestratorTaskCreated} value={new Date(task.created_at * 1000).toLocaleString()} />
      </div>

      {task.routing_info && (
        <RoutingInfoCard routing={task.routing_info} />
      )}

      {task.result && (
        <section className="bg-surface/50 rounded-lg border border-border/50 p-4">
          <h2 className="text-sm font-semibold text-text-primary mb-2">{t.orchestratorTaskResult}</h2>
          <pre className="text-sm text-text-primary whitespace-pre-wrap bg-surface/80 rounded p-3 max-h-96 overflow-y-auto">{task.result.content}</pre>
          <div className="mt-3 flex gap-6 text-xs text-text-muted">
            <span>{t.tokens}: {task.result.usage?.total_tokens ?? "—"}</span>
            <span>{t.duration}: {task.result.duration_seconds?.toFixed(1)}s</span>
          </div>
        </section>
      )}

      {task.error && (
        <section className="bg-red-500/10 border border-red-500/30 rounded-lg p-4">
          <h2 className="text-sm font-semibold text-red-400 mb-1">{t.orchestratorTaskError}</h2>
          <p className="text-sm text-red-300">{task.error}</p>
        </section>
      )}
    </div>
  );
}

function RoutingInfoCard({ routing }: { routing: RoutingInfo }) {
  const { t } = useI18n();
  const hasScores = routing.scores && Object.keys(routing.scores).length > 0;
  const maxScore = hasScores ? Math.max(...Object.values(routing.scores)) : 0;

  return (
    <section className={`rounded-lg border p-4 ${routing.fallback ? "bg-yellow-500/5 border-yellow-500/30" : "bg-surface/50 border-border/50"}`}>
      <div className="flex items-center gap-2 mb-3">
        <h2 className="text-sm font-semibold text-text-primary">{t.routingInfo}</h2>
        {routing.fallback && (
          <span className="px-2 py-0.5 rounded text-xs font-medium bg-yellow-500/20 text-yellow-400">
            {t.fallback}
          </span>
        )}
      </div>

      <div className="space-y-3">
        {/* Strategy */}
        <div className="flex items-start gap-3">
          <span className="text-xs text-text-muted w-24 shrink-0 pt-0.5">{t.routingStrategy}</span>
          <span className="text-sm text-text-primary font-mono">{routing.strategy}</span>
        </div>

        {/* Matched Tags */}
        {routing.matched_tags.length > 0 && (
          <div className="flex items-start gap-3">
            <span className="text-xs text-text-muted w-24 shrink-0 pt-0.5">{t.matchedTags}</span>
            <div className="flex flex-wrap gap-1">
              {routing.matched_tags.map(tag => (
                <span key={tag} className="px-2 py-0.5 rounded-full text-xs bg-accent-cyan/15 text-accent-cyan border border-accent-cyan/30">
                  {tag}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Reason */}
        {routing.reason && (
          <div className="flex items-start gap-3">
            <span className="text-xs text-text-muted w-24 shrink-0 pt-0.5">{t.routingReason}</span>
            <span className="text-xs text-text-secondary">{routing.reason}</span>
          </div>
        )}

        {/* Candidate Scores */}
        {hasScores && (
          <div className="flex items-start gap-3">
            <span className="text-xs text-text-muted w-24 shrink-0 pt-0.5">{t.candidateScores}</span>
            <div className="flex-1 space-y-1.5">
              {Object.entries(routing.scores)
                .sort(([, a], [, b]) => b - a)
                .map(([agentId, score]) => (
                  <div key={agentId} className="flex items-center gap-2">
                    <span className="text-xs font-mono text-text-secondary w-32 truncate" title={agentId}>
                      {agentId.length > 20 ? `${agentId.slice(0, 20)}...` : agentId}
                    </span>
                    <div className="flex-1 h-1.5 bg-border/20 rounded-full overflow-hidden">
                      <div
                        className={`h-full rounded-full ${
                          agentId === routing.chosen_agent_id
                            ? "bg-accent-cyan"
                            : "bg-text-muted/40"
                        }`}
                        style={{ width: maxScore > 0 ? `${(score / maxScore) * 100}%` : "0%" }}
                      />
                    </div>
                    <span className="text-xs text-text-muted w-10 text-right">{score.toFixed(2)}</span>
                  </div>
                ))}
            </div>
          </div>
        )}

        {/* Shadow Info */}
        {(routing.shadow_smart_agent_id || routing.shadow_smart_score != null) && (
          <div className="flex items-start gap-3 pt-2 border-t border-border/20">
            <span className="text-xs text-text-muted w-24 shrink-0 pt-0.5">{t.routingShadowInfo}</span>
            <div className="text-xs text-text-secondary">
              {routing.shadow_smart_agent_id && (
                <span className="mr-4">{t.agent}: <span className="font-mono">{routing.shadow_smart_agent_id}</span></span>
              )}
              {routing.shadow_smart_score != null && (
                <span>{t.score}: {routing.shadow_smart_score.toFixed(3)}</span>
              )}
            </div>
          </div>
        )}

        {/* No match */}
        {!routing.chosen_agent_id && (
          <div className="flex items-start gap-3">
            <span className="text-xs text-yellow-400">{t.routingNoMatch}</span>
          </div>
        )}
      </div>
    </section>
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
