import { useState, useRef } from "react";
import { useI18n } from "../../hooks/useI18n";
import type { KanbanTask, KanbanStatus } from "./kanban-types";
import { KanbanCard } from "./KanbanCard";

interface KanbanColumnProps {
  title: string;
  status: KanbanStatus;
  tasks: KanbanTask[];
  onDrop: (taskId: string, newStatus: KanbanStatus) => void;
  onCardClick: (task: KanbanTask) => void;
}

export function KanbanColumn({
  title,
  status,
  tasks,
  onDrop,
  onCardClick,
}: KanbanColumnProps) {
  const { t } = useI18n();
  const [dragOver, setDragOver] = useState(false);
  const counterRef = useRef(0);

  function handleDragEnter(e: React.DragEvent) {
    e.preventDefault();
    counterRef.current += 1;
    setDragOver(true);
  }

  function handleDragLeave() {
    counterRef.current -= 1;
    if (counterRef.current === 0) {
      setDragOver(false);
    }
  }

  function handleDragOver(e: React.DragEvent) {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    counterRef.current = 0;
    setDragOver(false);
    const taskId = e.dataTransfer.getData("text/plain");
    if (taskId) {
      onDrop(taskId, status);
    }
  }

  return (
    <div
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
      className={`flex flex-col min-w-[240px] rounded-lg bg-surface-secondary border transition-colors ${
        dragOver
          ? "border-accent-pink/60 shadow-[0_0_8px_rgba(236,72,153,0.15)]"
          : "border-border"
      }`}
    >
      <div className="flex items-center justify-between px-3 py-2.5 border-b border-border">
        <h3 className="text-xs font-medium uppercase tracking-wider text-text-secondary">
          {title}
        </h3>
        <span className="text-[10px] font-[family-name:var(--font-mono)] px-1.5 py-0.5 rounded bg-surface-tertiary text-text-secondary">
          {tasks.length}
        </span>
      </div>
      <div className="flex-1 p-2 space-y-2 overflow-y-auto max-h-[calc(100vh-280px)]">
        {tasks.length === 0 && (
          <p className="text-[10px] text-text-secondary text-center py-4">
            {t.kanbanDropTasks}
          </p>
        )}
        {tasks.map((task) => (
          <KanbanCard key={task.id} task={task} onClick={onCardClick} />
        ))}
      </div>
    </div>
  );
}
