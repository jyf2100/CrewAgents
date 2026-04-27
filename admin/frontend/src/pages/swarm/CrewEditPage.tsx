import { useState, useEffect, useRef } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useSwarmCrews, WorkflowStep, CrewAgent, Crew } from "../../stores/swarmCrews";
import { useSwarmRegistry } from "../../stores/swarmRegistry";
import { useI18n } from "../../hooks/useI18n";

interface AgentEntry {
  key: string;
  data: CrewAgent;
}

export function CrewEditPage() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const { id } = useParams();
  const isEdit = Boolean(id);
  const { crews, fetchCrews, createCrew, updateCrew, error: storeError } = useSwarmCrews();
  const { agents, fetchAgents } = useSwarmRegistry();

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [workflowType, setWorkflowType] = useState<"sequential" | "parallel" | "dag">("sequential");
  const [workflowTimeout, setWorkflowTimeout] = useState(300);
  const [agentEntries, setAgentEntries] = useState<AgentEntry[]>([]);
  const agentKeyRef = useRef(0);
  const [steps, setSteps] = useState<WorkflowStep[]>([
    { id: "step_1", required_capability: "", task_template: "", depends_on: [], input_from: {}, timeout_seconds: 120 },
  ]);
  const stepIdRef = useRef(1);
  const [saving, setSaving] = useState(false);
  const [notFound, setNotFound] = useState(false);
  const [validationError, setValidationError] = useState<string | null>(null);

  useEffect(() => {
    fetchAgents();
    if (isEdit) {
      fetchCrews();
    }
  }, [fetchAgents, fetchCrews, isEdit]);

  useEffect(() => {
    if (isEdit && id && crews.length > 0) {
      const crew = crews.find((c) => c.crew_id === id);
      if (crew) {
        setName(crew.name);
        setDescription(crew.description);
        setWorkflowType(crew.workflow.type);
        setWorkflowTimeout(crew.workflow.timeout_seconds);
        setAgentEntries(crew.agents.map((a, i) => ({ key: `agent_loaded_${i}`, data: a })));
        setSteps(crew.workflow.steps);
        // Initialize stepIdRef from existing steps to avoid ID collisions
        const maxNum = crew.workflow.steps.reduce((max, s) => {
          const match = s.id.match(/step_(\d+)/);
          return match ? Math.max(max, parseInt(match[1])) : max;
        }, 0);
        stepIdRef.current = maxNum;
      } else {
        setNotFound(true);
      }
    }
  }, [isEdit, id, crews]);

  const addAgent = () => {
    const key = `agent_${agentKeyRef.current++}`;
    setAgentEntries([...agentEntries, { key, data: { agent_id: 0, required_capability: "" } }]);
  };

  const removeAgent = (idx: number) => {
    setAgentEntries(agentEntries.filter((_, i) => i !== idx));
  };

  const updateAgent = (idx: number, field: keyof CrewAgent, value: string | number) => {
    const updated = [...agentEntries];
    updated[idx] = { ...updated[idx], data: { ...updated[idx].data, [field]: value } };
    setAgentEntries(updated);
  };

  const addStep = () => {
    stepIdRef.current += 1;
    setSteps([...steps, {
      id: `step_${stepIdRef.current}`,
      required_capability: "",
      task_template: "",
      depends_on: [],
      input_from: {},
      timeout_seconds: 120,
    }]);
  };

  const removeStep = (idx: number) => {
    setSteps(steps.filter((_, i) => i !== idx));
  };

  const updateStep = <K extends keyof WorkflowStep>(idx: number, field: K, value: WorkflowStep[K]) => {
    const updated = [...steps];
    updated[idx] = { ...updated[idx], [field]: value };
    setSteps(updated);
  };

  const validate = (): string | null => {
    if (!name.trim()) return t.crewValidationRequired;
    if (steps.length === 0) return t.crewValidationEmptySteps;
    for (const step of steps) {
      if (!step.id.trim() || !step.required_capability.trim()) return t.crewValidationRequired;
    }
    if (workflowType === "dag") {
      const stepIds = new Set(steps.map((s) => s.id));
      for (const step of steps) {
        for (const dep of step.depends_on) {
          if (!stepIds.has(dep)) return `Step '${step.id}' depends on unknown step '${dep}'`;
        }
      }
      const inDegree: Record<string, number> = {};
      const adj: Record<string, string[]> = {};
      for (const s of steps) {
        inDegree[s.id] = 0;
        adj[s.id] = [];
      }
      for (const s of steps) {
        for (const dep of s.depends_on) {
          if (adj[dep]) { adj[dep].push(s.id); inDegree[s.id]++; }
        }
      }
      const queue = Object.keys(inDegree).filter((id) => inDegree[id] === 0);
      let visited = 0;
      const q = [...queue];
      while (q.length > 0) {
        const curr = q.shift()!;
        visited++;
        for (const next of adj[curr]) {
          inDegree[next]--;
          if (inDegree[next] === 0) q.push(next);
        }
      }
      if (visited !== steps.length) return t.crewValidationCycle;
    }
    return null;
  };

  const handleSave = async () => {
    const crewAgents = agentEntries.map((e) => e.data);
    const err = validate();
    if (err) { setValidationError(err); return; }
    setValidationError(null);
    setSaving(true);

    const crewData = {
      name: name.trim(),
      description: description.trim(),
      agents: crewAgents,
      workflow: { type: workflowType, steps, timeout_seconds: workflowTimeout },
    };

    if (isEdit && id) {
      await updateCrew(id, crewData);
    } else {
      const newId = await createCrew(crewData as Omit<Crew, "crew_id" | "created_at" | "updated_at" | "created_by">);
      if (newId) {
        navigate(`/swarm/crews/${newId}/edit`);
      }
    }
    setSaving(false);
  };

  if (isEdit && crews.length === 0) return <div className="flex items-center justify-center py-20"><div className="w-6 h-6 border-2 border-accent-cyan border-t-transparent rounded-full animate-spin" /></div>;

  const agentStatusLabel = (status: string) => {
    if (status === "online") return t.crewAgentOnline;
    if (status === "busy") return t.crewAgentBusy;
    return t.crewAgentOffline;
  };

  return (
    <div className="max-w-3xl mx-auto">
      <h1 className="text-2xl font-semibold font-[family-name:var(--font-body)] text-text-primary mb-6">
        {isEdit ? t.crewEdit : t.crewAdd}
      </h1>

      {notFound && (
        <div className="mb-4 px-4 py-2 rounded-lg bg-accent-pink/10 text-accent-pink text-sm">
          Crew not found
        </div>
      )}
      {validationError && (
        <div className="mb-4 px-4 py-2 rounded-lg bg-accent-pink/10 text-accent-pink text-sm">
          {validationError}
        </div>
      )}

      <div className="space-y-4 mb-8">
        <div>
          <label className="block text-sm text-text-secondary mb-1">{t.crewName} *</label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full px-3 py-2 bg-surface border border-border-subtle rounded-lg text-text-primary focus:border-accent-cyan focus:outline-none"
            aria-label={t.crewName}
          />
        </div>
        <div>
          <label className="block text-sm text-text-secondary mb-1">{t.crewDescription}</label>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={2}
            className="w-full px-3 py-2 bg-surface border border-border-subtle rounded-lg text-text-primary focus:border-accent-cyan focus:outline-none resize-none"
            aria-label={t.crewDescription}
          />
        </div>
      </div>

      <div className="mb-8">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-lg font-medium text-text-primary">{t.crewAgents}</h2>
          <button onClick={addAgent} className="text-sm text-accent-cyan hover:underline">
            {t.crewAddAgent}
          </button>
        </div>
        {agentEntries.map((entry, idx) => (
          <div key={entry.key} className="flex items-center gap-3 mb-2">
            <select
              value={entry.data.agent_id}
              onChange={(e) => updateAgent(idx, "agent_id", Number(e.target.value))}
              className="flex-1 px-3 py-2 bg-surface border border-border-subtle rounded-lg text-text-primary text-sm"
              aria-label={t.crewAgentId}
            >
              <option value={0}>--</option>
              {agents.map((a) => (
                <option key={a.agent_id} value={a.agent_id}>
                  {a.display_name} ({agentStatusLabel(a.status)})
                </option>
              ))}
            </select>
            <input
              value={entry.data.required_capability}
              onChange={(e) => updateAgent(idx, "required_capability", e.target.value)}
              placeholder={t.crewAgentCapability}
              className="flex-1 px-3 py-2 bg-surface border border-border-subtle rounded-lg text-text-primary text-sm"
              aria-label={t.crewAgentCapability}
            />
            <button onClick={() => removeAgent(idx)} className="text-xs text-accent-pink hover:underline">
              {t.crewRemoveAgent}
            </button>
          </div>
        ))}
      </div>

      <div className="mb-8">
        <h2 className="text-lg font-medium text-text-primary mb-3">{t.crewWorkflowType}</h2>
        <div className="flex items-center gap-4 mb-4">
          <select
            value={workflowType}
            onChange={(e) => setWorkflowType(e.target.value as "sequential" | "parallel" | "dag")}
            className="px-3 py-2 bg-surface border border-border-subtle rounded-lg text-text-primary text-sm"
          >
            <option value="sequential">{t.crewSequential}</option>
            <option value="parallel">{t.crewParallel}</option>
            <option value="dag">{t.crewDAG}</option>
          </select>
          <div className="flex items-center gap-2 text-sm">
            <label className="text-text-secondary">{t.crewWorkflowTimeout}</label>
            <input
              type="number"
              value={workflowTimeout}
              onChange={(e) => setWorkflowTimeout(Number(e.target.value))}
              className="w-20 px-2 py-1 bg-surface border border-border-subtle rounded text-text-primary text-sm"
            />
          </div>
        </div>

        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-medium text-text-secondary">{t.crewWorkflowSteps}</h3>
          <button onClick={addStep} className="text-sm text-accent-cyan hover:underline">
            {t.crewAddStep}
          </button>
        </div>

        {steps.map((step, idx) => (
          <div key={step.id} className="bg-surface/40 border border-border-subtle rounded-lg p-4 mb-3">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs text-text-secondary font-mono">{step.id}</span>
              <button onClick={() => removeStep(idx)} className="text-xs text-accent-pink hover:underline">
                {t.crewRemoveStep}
              </button>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <input
                value={step.required_capability}
                onChange={(e) => updateStep(idx, "required_capability", e.target.value)}
                placeholder={t.crewStepCapability}
                className="px-2 py-1.5 bg-surface border border-border-subtle rounded text-sm text-text-primary"
                aria-label={`${step.id} ${t.crewStepCapability}`}
              />
              <input
                value={step.task_template}
                onChange={(e) => updateStep(idx, "task_template", e.target.value)}
                placeholder={`${t.crewStepTemplate} — ${t.crewStepTemplateHint}`}
                className="px-2 py-1.5 bg-surface border border-border-subtle rounded text-sm text-text-primary"
                aria-label={`${step.id} ${t.crewStepTemplate}`}
              />
              {workflowType === "dag" && (
                <>
                  <input
                    value={step.depends_on.join(", ")}
                    onChange={(e) => updateStep(idx, "depends_on", e.target.value.split(",").map((s) => s.trim()).filter(Boolean))}
                    placeholder={t.crewStepDependsOn}
                    className="px-2 py-1.5 bg-surface border border-border-subtle rounded text-sm text-text-primary"
                    aria-label={`${step.id} ${t.crewStepDependsOn}`}
                  />
                  <input
                    type="number"
                    value={step.timeout_seconds}
                    onChange={(e) => updateStep(idx, "timeout_seconds", Number(e.target.value))}
                    placeholder={t.crewStepTimeout}
                    className="px-2 py-1.5 bg-surface border border-border-subtle rounded text-sm text-text-primary"
                    aria-label={`${step.id} ${t.crewStepTimeout}`}
                  />
                </>
              )}
            </div>
          </div>
        ))}
      </div>

      <div className="flex items-center gap-3">
        <button
          onClick={handleSave}
          disabled={saving}
          className="px-6 py-2 bg-accent-cyan text-bg rounded-lg hover:bg-accent-cyan/90 transition-colors font-medium disabled:opacity-50"
        >
          {saving ? "..." : t.crewSave}
        </button>
        <button
          onClick={() => navigate("/swarm/crews")}
          className="px-6 py-2 text-text-secondary hover:text-text-primary transition-colors"
        >
          {t.crewCancel}
        </button>
      </div>

      {storeError && (
        <div className="text-red-400 text-sm mt-2">{storeError}</div>
      )}
    </div>
  );
}
