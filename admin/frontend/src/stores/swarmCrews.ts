import { create } from "zustand";
import { adminFetch } from "../lib/admin-api";

export interface CrewAgent {
  agent_id: number;
  required_capability: string;
}

export interface WorkflowStep {
  id: string;
  required_capability: string;
  task_template: string;
  depends_on: string[];
  input_from: Record<string, string>;
  timeout_seconds: number;
}

export interface WorkflowDef {
  type: "sequential" | "parallel" | "dag";
  steps: WorkflowStep[];
  timeout_seconds: number;
}

export interface Crew {
  crew_id: string;
  name: string;
  description: string;
  agents: CrewAgent[];
  workflow: WorkflowDef;
  created_at: number;
  updated_at: number;
  created_by: string;
}

interface ExecutionResult {
  exec_id: string;
  crew_id: string;
  status: string;
  step_results: Record<
    string,
    {
      step_id: string;
      status: string;
      output: string | null;
      error: string | null;
      agent_id: number | null;
      duration_ms: number;
    }
  >;
  error: string | null;
  started_at: number;
  finished_at: number | null;
  timeout_seconds: number;
}

interface SwarmCrewsState {
  crews: Crew[];
  loading: boolean;
  error: string | null;
  execution: ExecutionResult | null;
  executionCrewId: string | null;
  executionLoading: boolean;
  fetchCrews: () => Promise<void>;
  createCrew: (
    data: Omit<Crew, "crew_id" | "created_at" | "updated_at" | "created_by">
  ) => Promise<string | null>;
  updateCrew: (crewId: string, data: Partial<Crew>) => Promise<boolean>;
  deleteCrew: (crewId: string) => Promise<boolean>;
  executeCrew: (crewId: string) => Promise<string | null>;
  pollExecution: (crewId: string, execId: string) => Promise<void>;
}

export const useSwarmCrews = create<SwarmCrewsState>((set, get) => ({
  crews: [],
  loading: false,
  error: null,
  execution: null,
  executionCrewId: null,
  executionLoading: false,

  fetchCrews: async () => {
    set({ loading: true, error: null });
    try {
      const data = await adminFetch<{ results: Crew[]; total: number }>(
        "/swarm/crews"
      );
      set({ crews: data.results, loading: false });
    } catch {
      set({ error: "Failed to fetch crews", loading: false });
    }
  },

  createCrew: async (data) => {
    try {
      const crew = await adminFetch<Crew>("/swarm/crews", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
      await get().fetchCrews();
      return crew.crew_id;
    } catch {
      set({ error: "Failed to create crew" });
      return null;
    }
  },

  updateCrew: async (crewId, data) => {
    try {
      await adminFetch<Crew>(`/swarm/crews/${crewId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
      await get().fetchCrews();
      return true;
    } catch {
      set({ error: "Failed to update crew" });
      return false;
    }
  },

  deleteCrew: async (crewId) => {
    try {
      await adminFetch(`/swarm/crews/${crewId}`, { method: "DELETE" });
      await get().fetchCrews();
      return true;
    } catch {
      set({ error: "Failed to delete crew" });
      return false;
    }
  },

  executeCrew: async (crewId) => {
    set({ executionLoading: true, execution: null, executionCrewId: crewId });
    try {
      const result = await adminFetch<{ exec_id: string; status: string }>(
        `/swarm/crews/${crewId}/execute`,
        { method: "POST" }
      );
      set({ executionLoading: false });
      return result.exec_id;
    } catch {
      set({ error: "Failed to execute crew", executionLoading: false });
      return null;
    }
  },

  pollExecution: async (crewId, execId) => {
    try {
      const result = await adminFetch<ExecutionResult | null>(
        `/swarm/crews/${crewId}/executions/${execId}`
      );
      if (result) {
        set({ execution: result });
      }
    } catch {
      // Polling errors are non-critical
    }
  },
}));
