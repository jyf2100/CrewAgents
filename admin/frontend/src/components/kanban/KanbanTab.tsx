import { useState, useEffect, useCallback } from "react";
import { useKanbanBoard } from "../../stores/kanbanBoard";
import { adminFetch } from "../../lib/admin-api";
import { showToast } from "../../lib/toast";
import { useI18n } from "../../hooks/useI18n";
import type { KanbanTask, KanbanStatus } from "./kanban-types";
import { KanbanColumn } from "./KanbanColumn";
import { TaskDrawer } from "./TaskDrawer";
import { CreateTaskModal } from "./CreateTaskModal";

interface KanbanTabProps {
  agentId: number;
}

interface ColumnDef {
  status: KanbanStatus;
  titleKey: keyof import("../../i18n/zh").Translations;
}

const COLUMNS: ColumnDef[] = [
  { status: "triage", titleKey: "kanbanTriage" },
  { status: "todo", titleKey: "kanbanTodo" },
  { status: "ready", titleKey: "kanbanReady" },
  { status: "running", titleKey: "kanbanRunning" },
  { status: "done", titleKey: "kanbanDone" },
  { status: "blocked", titleKey: "kanbanBlocked" },
];

export function KanbanTab({ agentId }: KanbanTabProps) {
  const tasks = useKanbanBoard((s) => s.tasks);
  const loading = useKanbanBoard((s) => s.loading);
  const error = useKanbanBoard((s) => s.error);
  const startPolling = useKanbanBoard((s) => s.startPolling);
  const stopPolling = useKanbanBoard((s) => s.stopPolling);
  const moveTask = useKanbanBoard((s) => s.moveTask);
  const fetchBoard = useKanbanBoard((s) => s.fetchBoard);
  const { t } = useI18n();

  const [selectedTask, setSelectedTask] = useState<KanbanTask | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [dispatching, setDispatching] = useState(false);

  useEffect(() => {
    startPolling(agentId);
    return () => stopPolling();
  }, [agentId, startPolling, stopPolling]);

  const handleDrop = useCallback(
    async (taskId: string, newStatus: KanbanStatus) => {
      try {
        await moveTask(agentId, taskId, newStatus);
      } catch (e: unknown) {
        showToast(
          e instanceof Error ? e.message : t.kanbanMoveFailed,
          "error"
        );
      }
    },
    [agentId, moveTask, t]
  );

  async function handleDispatch() {
    setDispatching(true);
    try {
      const result = await adminFetch<{
        spawned: unknown[];
        crashed: string[];
        skipped_unassigned: string[];
        auto_blocked: string[];
      }>(`/agents/${agentId}/kanban/dispatch`, { method: "POST" });
      const parts = [];
      if (result.spawned.length > 0) parts.push(`${t.kanbanSpawned}: ${result.spawned.length}`);
      if (result.crashed.length > 0) parts.push(`${t.kanbanCrashed}: ${result.crashed.length}`);
      if (result.skipped_unassigned.length > 0) parts.push(`${t.kanbanUnassigned}: ${result.skipped_unassigned.length}`);
      if (result.auto_blocked.length > 0) parts.push(`${t.kanbanAutoBlocked}: ${result.auto_blocked.length}`);
      showToast(parts.length > 0 ? parts.join(", ") : t.kanbanNoTasksToDispatch);
      fetchBoard(agentId);
    } catch (e: unknown) {
      showToast(
        e instanceof Error ? e.message : t.kanbanMoveFailed,
        "error"
      );
    } finally {
      setDispatching(false);
    }
  }

  if (loading && tasks.length === 0) {
    return (
      <div className="flex items-center justify-center py-16">
        <p className="text-sm text-text-secondary">{t.kanbanLoadingBoard}</p>
      </div>
    );
  }

  if (error && tasks.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 gap-3">
        <p className="text-sm text-accent-pink">{error}</p>
        <button
          onClick={() => fetchBoard(agentId)}
          className="h-9 px-4 text-sm border border-accent-cyan text-accent-cyan hover:bg-accent-cyan/10 rounded"
        >
          {t.retry}
        </button>
      </div>
    );
  }

  function tasksByStatus(status: KanbanStatus): KanbanTask[] {
    return tasks.filter((t) => t.status === status);
  }

  return (
    <div>
      {/* Toolbar */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <h2 className="text-sm font-medium text-text-primary">{t.kanbanBoard}</h2>
          <span className="text-[10px] text-text-secondary font-[family-name:var(--font-mono)]">
            {tasks.length} {t.kanbanTasks}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleDispatch}
            disabled={dispatching}
            className="h-8 px-3 text-xs border border-accent-cyan text-accent-cyan hover:bg-accent-cyan/10 rounded disabled:opacity-50"
          >
            {dispatching ? t.kanbanDispatching : t.kanbanDispatch}
          </button>
          <button
            onClick={() => setCreateOpen(true)}
            className="h-8 px-3 text-xs rounded bg-accent-pink text-white hover:bg-accent-pink/90"
          >
            {t.kanbanNewTask}
          </button>
        </div>
      </div>

      {/* Board */}
      <div className="flex gap-3 overflow-x-auto pb-4">
        {COLUMNS.map((col) => (
          <KanbanColumn
            key={col.status}
            title={t[col.titleKey]}
            status={col.status}
            tasks={tasksByStatus(col.status)}
            onDrop={handleDrop}
            onCardClick={setSelectedTask}
          />
        ))}
      </div>

      {/* Empty state */}
      {tasks.length === 0 && (
        <div className="text-center py-12 border border-dashed border-border rounded-lg">
          <p className="text-sm text-text-secondary mb-3">
            {t.kanbanNoTasksYet}
          </p>
          <button
            onClick={() => setCreateOpen(true)}
            className="h-9 px-4 text-sm border border-accent-cyan text-accent-cyan hover:bg-accent-cyan/10 rounded"
          >
            {t.kanbanCreateFirst}
          </button>
        </div>
      )}

      {/* Task detail drawer */}
      <TaskDrawer
        task={selectedTask}
        agentId={agentId}
        onClose={() => setSelectedTask(null)}
        onUpdate={() => fetchBoard(agentId)}
      />

      {/* Create task modal */}
      <CreateTaskModal
        agentId={agentId}
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={() => fetchBoard(agentId)}
      />
    </div>
  );
}
