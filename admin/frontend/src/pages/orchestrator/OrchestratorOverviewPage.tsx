import { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { adminApi, type OrchestratorAgent, type OrchestratorTask } from "../../lib/admin-api";
import { useI18n } from "../../hooks/useI18n";

export function OrchestratorOverviewPage() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [agents, setAgents] = useState<OrchestratorAgent[]>([]);
  const [tasks, setTasks] = useState<OrchestratorTask[]>([]);
  const [loading, setLoading] = useState(true);

  const loadData = useCallback(async () => {
    try {
      const [agentsData, tasksData] = await Promise.all([
        adminApi.orchestratorListAgents(),
        adminApi.orchestratorListTasks({ limit: 10 }),
      ]);
      setAgents(agentsData.agents);
      setTasks(tasksData);
    } catch {
      // silently fail
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
    const interval = setInterval(loadData, 10000);
    return () => clearInterval(interval);
  }, [loadData]);

  if (loading) return <div className="p-6 text-text-secondary">Loading...</div>;

  const onlineAgents = agents.filter(a => a.status === "online").length;
  const activeTasks = tasks.filter(t => ["queued", "assigned", "executing", "streaming"].includes(t.status)).length;
  const doneToday = tasks.filter(t => t.status === "done").length;

  return (
    <div className="p-6 space-y-6">
      <div className="grid grid-cols-4 gap-4">
        <StatCard label={t.orchestratorAgentFleet || "Agent Fleet"} value={agents.length} />
        <StatCard label={t.orchestratorStatusOnline || "Online"} value={onlineAgents} />
        <StatCard label="Active Tasks" value={activeTasks} />
        <StatCard label="Done" value={doneToday} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <section className="bg-surface/50 rounded-lg border border-border/50 p-4">
          <h2 className="text-lg font-semibold text-text-primary mb-4">{t.orchestratorAgentFleet || "Agent Fleet"}</h2>
          {agents.length === 0 ? (
            <p className="text-text-secondary text-sm">{t.orchestratorNoAgents || "No agents registered"}</p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-text-muted text-left border-b border-border/30">
                  <th className="pb-2">Agent</th>
                  <th className="pb-2">Status</th>
                  <th className="pb-2">Load</th>
                  <th className="pb-2">Circuit</th>
                </tr>
              </thead>
              <tbody>
                {agents.map(agent => (
                  <tr key={agent.agent_id} className="border-b border-border/10 hover:bg-surface/30">
                    <td className="py-2 font-mono text-xs">{agent.agent_id}</td>
                    <td className="py-2"><StatusBadge status={agent.status} /></td>
                    <td className="py-2">
                      <div className="flex items-center gap-2">
                        <div className="w-16 h-1.5 bg-border/30 rounded-full overflow-hidden">
                          <div className="h-full bg-accent-cyan rounded-full" style={{ width: `${(agent.current_load / agent.max_concurrent) * 100}%` }} />
                        </div>
                        <span className="text-text-muted text-xs">{agent.current_load}/{agent.max_concurrent}</span>
                      </div>
                    </td>
                    <td className="py-2"><CircuitBadge state={agent.circuit_state} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        <section className="bg-surface/50 rounded-lg border border-border/50 p-4">
          <h2 className="text-lg font-semibold text-text-primary mb-4">{t.orchestratorTaskList || "Tasks"}</h2>
          {tasks.length === 0 ? (
            <p className="text-text-secondary text-sm">{t.orchestratorNoTasks || "No tasks yet"}</p>
          ) : (
            <div className="space-y-2">
              {tasks.map(task => (
                <div key={task.task_id}
                  className="flex items-center justify-between p-2 rounded hover:bg-surface/30 cursor-pointer"
                  onClick={() => navigate(`/orchestrator/tasks/${task.task_id}`)}
                >
                  <div className="flex items-center gap-3">
                    <StatusBadge status={task.status} />
                    <span className="font-mono text-xs text-text-secondary">{task.task_id.slice(0, 8)}</span>
                  </div>
                  <span className="text-text-muted text-xs">{task.assigned_agent || "—"}</span>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="bg-surface/50 rounded-lg border border-border/50 p-4">
      <p className="text-text-muted text-xs">{label}</p>
      <p className="text-2xl font-bold text-text-primary">{value}</p>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    online: "bg-green-500/20 text-green-400",
    done: "bg-green-500/20 text-green-400",
    degraded: "bg-yellow-500/20 text-yellow-400",
    half_open: "bg-yellow-500/20 text-yellow-400",
    queued: "bg-gray-500/20 text-gray-400",
    assigned: "bg-gray-500/20 text-gray-400",
    offline: "bg-red-500/20 text-red-400",
    failed: "bg-red-500/20 text-red-400",
    executing: "bg-blue-500/20 text-blue-400",
    streaming: "bg-blue-500/20 text-blue-400",
  };
  return <span className={`px-2 py-0.5 rounded text-xs font-medium ${colors[status] || "bg-gray-500/20 text-gray-400"}`}>{status}</span>;
}

function CircuitBadge({ state }: { state: string }) {
  const colors: Record<string, string> = {
    closed: "bg-green-500",
    open: "bg-red-500",
    half_open: "bg-yellow-500",
  };
  return <span className={`inline-block w-2.5 h-2.5 rounded-full ${colors[state] || "bg-gray-500"}`} title={state} />;
}
