import { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { adminApi, type OrchestratorAgent, type OrchestratorTask } from "../../lib/admin-api";
import { useI18n } from "../../hooks/useI18n";
import { AgentStatusBadge, TaskStatusBadge, CircuitBadge } from "../../components/OrchestratorBadges";
import { DOMAINS, getDomainLabel, getDomainColorSet } from "../../components/domain-constants";
import type { DomainValue } from "../../components/domain-constants";

export function OrchestratorOverviewPage() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [agents, setAgents] = useState<OrchestratorAgent[]>([]);
  const [tasks, setTasks] = useState<OrchestratorTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const loadData = useCallback(async () => {
    try {
      const [agentsData, tasksData] = await Promise.all([
        adminApi.orchestratorListAgents(),
        adminApi.orchestratorListTasks({ limit: 10 }),
      ]);
      setAgents(agentsData.agents);
      setTasks(tasksData);
      setError("");
    } catch {
      setError(t.orchestratorLoadFailed || "Failed to load data");
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    loadData();
    const interval = setInterval(loadData, 10000);
    return () => clearInterval(interval);
  }, [loadData]);

  if (loading) return <div className="p-6 text-text-secondary">{t.loading}</div>;

  const onlineAgents = agents.filter(a => a.status === "online").length;
  const activeTasks = tasks.filter(t => ["queued", "assigned", "executing", "streaming"].includes(t.status)).length;
  const doneCount = tasks.filter(t => t.status === "done").length;

  return (
    <div className="p-6 space-y-6">
      {error && (
        <div className="px-3 py-2 bg-red-500/10 border border-red-500/30 rounded text-red-400 text-sm">
          {error}
        </div>
      )}

      <div className="grid grid-cols-4 gap-4">
        <StatCard label={t.orchestratorAgentFleet} value={agents.length} />
        <StatCard label={t.orchestratorStatusOnline} value={onlineAgents} />
        <StatCard label={t.orchestratorActiveTasks} value={activeTasks} />
        <StatCard label={t.orchestratorDoneCount} value={doneCount} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <section className="bg-surface/50 rounded-lg border border-border/50 p-4">
          <h2 className="text-lg font-semibold text-text-primary mb-4">{t.orchestratorAgentFleet}</h2>
          {agents.length === 0 ? (
            <p className="text-text-secondary text-sm">{t.orchestratorNoAgents}</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-text-muted text-left border-b border-border/30">
                    <th className="pb-2 pr-3">{t.agent}</th>
                    <th className="pb-2 pr-3">{t.orchestratorTaskStatus}</th>
                    <th className="pb-2 pr-3">{t.orchestratorAgentDomain || "Domain"}</th>
                    <th className="pb-2 pr-3">{t.orchestratorLoad}</th>
                    <th className="pb-2 pr-3">{t.orchestratorCircuit}</th>
                    <th className="pb-2">{t.orchestratorAgentTags}</th>
                  </tr>
                </thead>
                <tbody>
                  {agents.map(agent => (
                    <tr key={agent.agent_id} className="border-b border-border/10 hover:bg-surface/30">
                      <td className="py-2 pr-3 font-mono text-xs">{agent.agent_id}</td>
                      <td className="py-2 pr-3"><AgentStatusBadge status={agent.status} /></td>
                      <td className="py-2 pr-3"><DomainSkillsCell domain={agent.domain} role={agent.role} skills={agent.skills} /></td>
                      <td className="py-2 pr-3">
                        <div className="flex items-center gap-2">
                          <div className="w-16 h-1.5 bg-border/30 rounded-full overflow-hidden">
                            <div
                              className="h-full bg-accent-cyan rounded-full"
                              style={{ width: `${agent.max_concurrent > 0 ? (agent.current_load / agent.max_concurrent) * 100 : 0}%` }}
                            />
                          </div>
                          <span className="text-text-muted text-xs">{agent.current_load}/{agent.max_concurrent}</span>
                        </div>
                      </td>
                      <td className="py-2 pr-3"><CircuitBadge state={agent.circuit_state} /></td>
                      <td className="py-2">
                        <div className="flex flex-wrap gap-1 max-w-[200px]">
                          {agent.tags && agent.tags.length > 0 ? (
                            agent.tags.slice(0, 4).map(tag => (
                              <span key={tag} className="px-1.5 py-0.5 rounded text-[10px] bg-surface/80 text-text-muted border border-border/20">
                                {tag}
                              </span>
                            ))
                          ) : (
                            <span className="text-text-muted text-xs">-</span>
                          )}
                          {agent.tags && agent.tags.length > 4 && (
                            <span className="text-text-muted text-[10px]">+{agent.tags.length - 4}</span>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <section className="bg-surface/50 rounded-lg border border-border/50 p-4">
          <h2 className="text-lg font-semibold text-text-primary mb-4">{t.orchestratorTaskList}</h2>
          {tasks.length === 0 ? (
            <p className="text-text-secondary text-sm">{t.orchestratorNoTasks}</p>
          ) : (
            <div className="space-y-2">
              {tasks.map(task => (
                <div key={task.task_id}
                  className="flex items-center justify-between p-2 rounded hover:bg-surface/30 cursor-pointer"
                  onClick={() => navigate(`/orchestrator/tasks/${task.task_id}`)}
                >
                  <div className="flex items-center gap-3">
                    <TaskStatusBadge status={task.status} />
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

function DomainSkillsCell({ domain, role, skills }: { domain?: string; role?: string; skills?: string[] }) {
  const { t } = useI18n();

  // Use domain if available, fall back to role during migration
  const effectiveDomain = (domain || role || "generalist") as DomainValue;
  const colors = getDomainColorSet(effectiveDomain);
  const label = getDomainLabel(t, DOMAINS.find((d) => d.value === effectiveDomain)?.labelKey || "domainGeneralist");

  return (
    <div className="flex items-center gap-1.5">
      <span
        className={`px-2 py-0.5 rounded-full text-[10px] font-medium border ${colors ? `${colors.bg} ${colors.text} ${colors.border}` : "bg-gray-500/15 text-gray-400 border-gray-500/30"}`}
      >
        {label}
      </span>
      {skills && skills.length > 0 && (
        <span className="px-1.5 py-0.5 rounded text-[10px] bg-surface/80 text-text-muted border border-border/20">
          {(t.orchestratorSkillCount || "{n} skill(s)").replace("{n}", String(skills.length))}
        </span>
      )}
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
