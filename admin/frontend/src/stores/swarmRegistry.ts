import { create } from "zustand";
import { adminFetch } from "../lib/admin-api";

export interface SwarmAgent {
  agent_id: number;
  display_name: string;
  capabilities: string[];
  status: "online" | "offline" | "busy";
  current_tasks: number;
  max_concurrent_tasks: number;
  last_heartbeat: number;
  model: string;
}

interface SwarmRegistryState {
  agents: SwarmAgent[];
  loading: boolean;
  error: string | null;
  fetchAgents: () => Promise<void>;
  handleEvent: (type: string, data: unknown) => void;
}

export const useSwarmRegistry = create<SwarmRegistryState>((set) => ({
  agents: [],
  loading: false,
  error: null,

  fetchAgents: async () => {
    set({ loading: true, error: null });
    try {
      // adminFetch<T> returns parsed JSON directly (not a Response)
      const agents = await adminFetch<SwarmAgent[]>("/swarm/agents");
      set({ agents, loading: false });
    } catch (e: unknown) {
      set({ error: String(e), loading: false });
    }
  },

  handleEvent: (type, data) => {
    const d = data as Record<string, unknown>;
    if (type === "agent_online" || type === "agent_offline") {
      set((state) => {
        const agentId = d.agent_id as number;
        const status = type === "agent_online" ? "online" : "offline";
        return {
          agents: state.agents.map((a) =>
            a.agent_id === agentId ? { ...a, status: status as SwarmAgent["status"] } : a,
          ),
        };
      });
    }
  },
}));
