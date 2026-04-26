import { create } from "zustand";
import { adminFetch } from "../lib/admin-api";

export type TaskStatus = "completed" | "failed" | "pending" | "running";

export interface SwarmTask {
  task_id: string;
  task_type: string;
  goal: string;
  status: TaskStatus;
  sender_id: number;
  assigned_agent_id: number | null;
  duration_ms: number | null;
  error: string;
  timestamp: number;
}

interface SwarmTasksState {
  tasks: SwarmTask[];
  loading: boolean;
  error: string | null;
  fetchTasks: () => Promise<void>;
  handleEvent: (type: string, data: unknown) => void;
}

export const useSwarmTasks = create<SwarmTasksState>((set) => ({
  tasks: [],
  loading: false,
  error: null,

  fetchTasks: async () => {
    set({ loading: true, error: null });
    try {
      const tasks = await adminFetch<SwarmTask[]>("/swarm/tasks");
      set({ tasks, loading: false });
    } catch (e: unknown) {
      set({ error: String(e), loading: false });
    }
  },

  handleEvent: (type, data) => {
    const d = data as Record<string, unknown>;
    if (
      type === "task_created" ||
      type === "task_started" ||
      type === "task_completed" ||
      type === "task_failed"
    ) {
      const taskId = d.task_id as string;
      set((state) => {
        const existing = state.tasks.findIndex((t) => t.task_id === taskId);
        if (existing >= 0) {
          const updated = [...state.tasks];
          updated[existing] = {
            ...updated[existing],
            status:
              (d.status as TaskStatus) ??
              (type.replace("task_", "") as TaskStatus),
            duration_ms:
              (d.duration_ms as number) ?? updated[existing].duration_ms,
            assigned_agent_id:
              (d.agent_id as number) ?? updated[existing].assigned_agent_id,
          };
          return { tasks: updated };
        }
        return {
          tasks: [
            {
              task_id: taskId,
              task_type: (d.task_type as string) ?? "",
              goal: "",
              status:
                type === "task_created"
                  ? "pending"
                  : ((d.status as TaskStatus) ?? "running"),
              sender_id: 0,
              assigned_agent_id: (d.agent_id as number) ?? null,
              duration_ms: null,
              error: "",
              timestamp: Date.now() / 1000,
            },
            ...state.tasks,
          ],
        };
      });
    }
  },
}));
