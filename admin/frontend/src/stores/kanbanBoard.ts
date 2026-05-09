import { create } from "zustand";
import { adminFetch } from "../lib/admin-api";
import type { KanbanTask, KanbanComment } from "../components/kanban/kanban-types";

interface KanbanBoardState {
  tasks: KanbanTask[];
  loading: boolean;
  error: string | null;
  fetchBoard: (agentId: number) => Promise<void>;
  startPolling: (agentId: number) => void;
  stopPolling: () => void;
  createTask: (
    agentId: number,
    data: { title: string; body?: string; priority?: number; labels?: string[]; assignee?: string }
  ) => Promise<void>;
  updateTask: (
    agentId: number,
    taskId: string,
    data: Partial<KanbanTask>
  ) => Promise<void>;
  addComment: (
    agentId: number,
    taskId: string,
    commentBody: string
  ) => Promise<void>;
  moveTask: (
    agentId: number,
    taskId: string,
    newStatus: KanbanTask["status"]
  ) => Promise<void>;
}

let pollIntervalId: ReturnType<typeof setInterval> | null = null;
let _pollingAgentId: number | null = null;

function _handleVisibility() {
  if (document.hidden) {
    // stopPolling will be called, interval cleared
    if (pollIntervalId !== null) {
      clearInterval(pollIntervalId);
      pollIntervalId = null;
    }
  } else if (_pollingAgentId !== null) {
    // Resume: fetch immediately and restart interval
    const store = useKanbanBoard.getState();
    store.fetchBoard(_pollingAgentId);
    pollIntervalId = setInterval(() => store.fetchBoard(_pollingAgentId!), 15_000);
  }
}

export const useKanbanBoard = create<KanbanBoardState>((set, get) => ({
  tasks: [],
  loading: false,
  error: null,

  fetchBoard: async (agentId: number) => {
    set({ loading: true, error: null });
    try {
      const board = await adminFetch<{ columns?: { tasks?: KanbanTask[] }[] }>(
        `/agents/${agentId}/kanban/tasks`
      );
      const columns = board?.columns ?? [];
      const tasks = columns.flatMap((col) => col?.tasks ?? []);
      set({ tasks, loading: false });
    } catch (e: unknown) {
      set({ error: e instanceof Error ? e.message : String(e), loading: false });
    }
  },

  startPolling: (agentId: number) => {
    get().stopPolling();
    _pollingAgentId = agentId;
    get().fetchBoard(agentId);
    pollIntervalId = setInterval(() => get().fetchBoard(agentId), 15_000);
    document.removeEventListener('visibilitychange', _handleVisibility);
    document.addEventListener('visibilitychange', _handleVisibility);
  },

  stopPolling: () => {
    if (pollIntervalId !== null) {
      clearInterval(pollIntervalId);
      pollIntervalId = null;
    }
    _pollingAgentId = null;
    document.removeEventListener('visibilitychange', _handleVisibility);
  },

  createTask: async (agentId, data) => {
    await adminFetch<KanbanTask>(`/agents/${agentId}/kanban/tasks`, {
      method: "POST",
      body: JSON.stringify(data),
    });
    await get().fetchBoard(agentId);
    // Auto-dispatch after creating a task
    try {
      await adminFetch<{ spawned: unknown[] }>(`/agents/${agentId}/kanban/dispatch`, {
        method: "POST",
      });
    } catch (e) {
      console.warn("Auto-dispatch failed:", e);
    }
  },

  updateTask: async (agentId, taskId, data) => {
    await adminFetch<KanbanTask>(
      `/agents/${agentId}/kanban/tasks/${taskId}`,
      {
        method: "PATCH",
        body: JSON.stringify(data),
      }
    );
    await get().fetchBoard(agentId);
  },

  addComment: async (agentId, taskId, commentBody) => {
    await adminFetch<KanbanComment>(
      `/agents/${agentId}/kanban/tasks/${taskId}/comments`,
      {
        method: "POST",
        body: JSON.stringify({ body: commentBody }),
      }
    );
  },

  moveTask: async (agentId, taskId, newStatus) => {
    await adminFetch<KanbanTask>(
      `/agents/${agentId}/kanban/tasks/${taskId}`,
      {
        method: "PATCH",
        body: JSON.stringify({ status: newStatus }),
      }
    );
    await get().fetchBoard(agentId);
  },
}));
