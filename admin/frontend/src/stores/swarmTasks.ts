import { create } from "zustand";
import { adminFetch } from "../lib/admin-api";

export type TaskStatus = "completed" | "failed" | "pending" | "running";

const VALID_STATUSES = new Set<string>(["completed", "failed", "pending", "running"]);

function extractEventFields(data: unknown) {
  if (typeof data !== "object" || data === null) {
    return null;
  }
  const d = data as Record<string, unknown>;
  return {
    task_id: typeof d.task_id === "string" ? d.task_id : "",
    status:
      typeof d.status === "string" && VALID_STATUSES.has(d.status)
        ? (d.status as TaskStatus)
        : undefined,
    task_type: typeof d.task_type === "string" ? d.task_type : "",
    duration_ms: typeof d.duration_ms === "number" ? d.duration_ms : undefined,
    agent_id: typeof d.agent_id === "number" ? d.agent_id : undefined,
  };
}

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
    if (
      type !== "task_created" &&
      type !== "task_started" &&
      type !== "task_completed" &&
      type !== "task_failed"
    ) {
      return;
    }

    const fields = extractEventFields(data);
    if (!fields || !fields.task_id) return;

    const taskId = fields.task_id;
    set((state) => {
      const existing = state.tasks.findIndex((t) => t.task_id === taskId);
      if (existing >= 0) {
        const updated = [...state.tasks];
        updated[existing] = {
          ...updated[existing],
          status:
            fields.status ??
            (type.replace("task_", "") as TaskStatus),
          duration_ms:
            fields.duration_ms ?? updated[existing].duration_ms,
          assigned_agent_id:
            fields.agent_id ?? updated[existing].assigned_agent_id,
        };
        return { tasks: updated };
      }
      return {
        tasks: [
          {
            task_id: taskId,
            task_type: fields.task_type,
            goal: "",
            status:
              type === "task_created"
                ? "pending"
                : (fields.status ?? "running"),
            sender_id: 0,
            assigned_agent_id: fields.agent_id ?? null,
            duration_ms: null,
            error: "",
            timestamp: Date.now() / 1000,
          },
          ...state.tasks,
        ],
      };
    });
  },
}));
