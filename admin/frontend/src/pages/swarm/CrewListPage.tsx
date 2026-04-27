import { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useSwarmCrews } from "../../stores/swarmCrews";
import { useSwarmRegistry } from "../../stores/swarmRegistry";
import { useI18n } from "../../hooks/useI18n";

const WORKFLOW_BADGES: Record<string, string> = {
  sequential: "bg-accent-cyan/20 text-accent-cyan",
  parallel: "bg-amber-500/20 text-amber-400",
  dag: "bg-accent-pink/20 text-accent-pink",
};

const MAX_POLL_COUNT = 200; // 200 * 3s = 10 minutes

export function CrewListPage() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const { crews, loading, error, fetchCrews, deleteCrew, executeCrew, pollExecution, execution, executionCrewId, executionLoading } =
    useSwarmCrews();
  const { agents, fetchAgents } = useSwarmRegistry();
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollCountRef = useRef(0);

  useEffect(() => {
    fetchCrews();
    fetchAgents();
  }, [fetchCrews, fetchAgents]);

  useEffect(() => {
    if (executionCrewId && execution?.status === "running") {
      if (pollCountRef.current >= MAX_POLL_COUNT) {
        // Timeout — stop polling
        return;
      }
      pollCountRef.current += 1;
      pollRef.current = setInterval(() => {
        if (executionCrewId && execution?.exec_id) {
          pollExecution(executionCrewId, execution.exec_id);
        }
      }, 3000);
      return () => { if (pollRef.current) clearInterval(pollRef.current); };
    }
    if (pollRef.current && execution?.status !== "running") {
      clearInterval(pollRef.current);
      pollRef.current = null;
      pollCountRef.current = 0;
    }
  }, [executionCrewId, execution?.status, execution?.exec_id, pollExecution]);

  const handleDelete = async (crewId: string, name: string) => {
    if (!confirm(`${t.crewDeleteConfirm}\n${name}`)) return;
    await deleteCrew(crewId);
  };

  const handleExecute = async (crewId: string) => {
    if (!confirm(t.crewExecuteConfirm)) return;
    pollCountRef.current = 0;
    const execId = await executeCrew(crewId);
    if (execId) {
      await pollExecution(crewId, execId);
    }
  };

  if (loading && crews.length === 0) return <div className="flex items-center justify-center py-20"><div className="w-6 h-6 border-2 border-accent-cyan border-t-transparent rounded-full animate-spin" /></div>;

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-semibold font-[family-name:var(--font-body)] text-text-primary">
          {t.crewTitle}
        </h1>
        <button
          onClick={() => navigate("/swarm/crews/new")}
          className="h-9 px-4 text-sm bg-accent-cyan text-bg rounded-lg hover:bg-accent-cyan/90 transition-colors font-medium"
        >
          {t.crewAdd}
        </button>
      </div>

      {error && (
        <div className="mb-4 px-4 py-2 rounded-lg bg-accent-pink/10 text-accent-pink text-sm">
          {t.crewLoadError}
        </div>
      )}

      {execution && (
        <div className="mb-4 px-4 py-3 rounded-lg bg-surface/80 border border-border-subtle">
          <div className="flex items-center gap-2 text-sm">
            <span className="text-text-secondary">{t.crewExecutionStatus}:</span>
            <span className={execution.status === "completed" ? "text-green-400" : execution.status === "failed" ? "text-accent-pink" : "text-accent-cyan"}>
              {execution.status === "completed" ? t.crewExecutionCompleted :
               execution.status === "failed" ? t.crewExecutionFailed :
               execution.status === "running" ? t.crewExecutionRunning : t.crewExecutionPending}
            </span>
            {pollCountRef.current >= MAX_POLL_COUNT && execution.status === "running" && (
              <span className="text-amber-400 text-xs ml-2">— timeout, check back later</span>
            )}
          </div>
          {execution.error && (
            <p className="mt-1 text-xs text-accent-pink">{execution.error}</p>
          )}
        </div>
      )}

      {crews.length === 0 && !loading ? (
        <div className="flex flex-col items-center justify-center py-20 text-text-secondary">
          <p className="text-lg mb-4">{t.crewNoCrews}</p>
          <button
            onClick={() => navigate("/swarm/crews/new")}
            className="px-6 py-2 bg-accent-cyan text-bg rounded-lg hover:bg-accent-cyan/90 transition-colors"
          >
            {t.crewAdd}
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {crews.map((crew, i) => (
            <div
              key={crew.crew_id}
              className="bg-surface/60 border border-border-subtle rounded-xl p-5 hover:border-accent-cyan/30 transition-colors"
              style={{ animationDelay: `${i * 50}ms` }}
            >
              <div className="flex items-start justify-between mb-3">
                <h3 className="font-semibold text-text-primary">{crew.name}</h3>
                <span className={`px-2 py-0.5 rounded text-xs font-medium ${WORKFLOW_BADGES[crew.workflow.type] || "bg-surface text-text-secondary"}`}>
                  {crew.workflow.type === "sequential" ? t.crewSequential :
                   crew.workflow.type === "parallel" ? t.crewParallel : t.crewDAG}
                </span>
              </div>
              {crew.description && (
                <p className="text-sm text-text-secondary mb-3 line-clamp-2">{crew.description}</p>
              )}
              <div className="flex items-center gap-2 text-xs text-text-secondary mb-4">
                <span>{crew.agents.length} agents</span>
                <span>·</span>
                <span>{crew.workflow.steps.length} steps</span>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => navigate(`/swarm/crews/${crew.crew_id}/edit`)}
                  className="px-3 py-1.5 text-xs bg-surface border border-border-subtle rounded-lg hover:border-accent-cyan/40 transition-colors"
                >
                  {t.crewEdit}
                </button>
                <button
                  onClick={() => handleExecute(crew.crew_id)}
                  disabled={executionLoading}
                  className="px-3 py-1.5 text-xs bg-accent-cyan/20 text-accent-cyan rounded-lg hover:bg-accent-cyan/30 transition-colors disabled:opacity-50"
                >
                  {executionLoading ? t.crewExecuting : t.crewExecute}
                </button>
                <button
                  onClick={() => handleDelete(crew.crew_id, crew.name)}
                  className="px-3 py-1.5 text-xs text-accent-pink hover:bg-accent-pink/10 rounded-lg transition-colors ml-auto"
                >
                  {t.crewDeleteLabel}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
