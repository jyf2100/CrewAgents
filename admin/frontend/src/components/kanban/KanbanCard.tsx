import { useState } from "react";
import { useI18n } from "../../hooks/useI18n";
import type { KanbanTask } from "./kanban-types";

const PRIORITY_COLORS: Record<number, string> = {
  1: "bg-success",
  2: "bg-accent-cyan",
  3: "bg-warning",
  4: "bg-accent-pink",
};

interface KanbanCardProps {
  task: KanbanTask;
  onClick: (task: KanbanTask) => void;
}

export function KanbanCard({ task, onClick }: KanbanCardProps) {
  const { t } = useI18n();
  const [dragging, setDragging] = useState(false);

  function handleDragStart(e: React.DragEvent) {
    e.dataTransfer.setData("text/plain", task.id);
    e.dataTransfer.effectAllowed = "move";
    setDragging(true);
  }

  function handleDragEnd() {
    setDragging(false);
  }

  const priorityColor =
    task.priority && PRIORITY_COLORS[task.priority]
      ? PRIORITY_COLORS[task.priority]
      : "bg-text-secondary";

  return (
    <div
      draggable
      onDragStart={handleDragStart}
      onDragEnd={handleDragEnd}
      onClick={() => onClick(task)}
      role="button"
      tabIndex={0}
      aria-label={`Task: ${task.title}`}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onClick(task);
        }
      }}
      className={`group cursor-pointer rounded-md bg-surface border border-border p-3 hover:border-accent-pink/40 hover:shadow-[0_2px_8px_rgba(0,0,0,0.15)] transition-all ${dragging ? "opacity-50" : ""}`}
    >
      <div className="flex items-start gap-2 mb-1.5">
        <span
          className={`mt-1.5 shrink-0 h-2 w-2 rounded-full ${priorityColor}`}
          title={`${t.kanbanPriority}: ${task.priority ?? "none"}`}
        />
        <span className="text-sm text-text-primary leading-snug line-clamp-2">
          {task.title}
        </span>
      </div>
      {task.labels && task.labels.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-2">
          {task.labels.map((label) => (
            <span
              key={label}
              className="text-[10px] px-1.5 py-0.5 rounded bg-accent-cyan/10 text-accent-cyan"
            >
              {label}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
