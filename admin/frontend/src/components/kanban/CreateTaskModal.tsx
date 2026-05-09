import { useState } from "react";
import { useKanbanBoard } from "../../stores/kanbanBoard";
import { showToast } from "../../lib/toast";
import { useI18n } from "../../hooks/useI18n";

interface CreateTaskModalProps {
  agentId: number;
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}

export function CreateTaskModal({
  agentId,
  open,
  onClose,
  onCreated,
}: CreateTaskModalProps) {
  const createTask = useKanbanBoard((s) => s.createTask);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [priority, setPriority] = useState(2);
  const [labelsInput, setLabelsInput] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { t } = useI18n();

  if (!open) return null;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim()) return;

    setSubmitting(true);
    setError(null);
    try {
      const labels = labelsInput.trim()
        ? labelsInput.split(",").map((l: string) => l.trim()).filter(Boolean)
        : undefined;
      await createTask(agentId, {
        title: title.trim(),
        body: body.trim() || undefined,
        priority,
        labels,
        assignee: "default",
      });
      showToast(t.kanbanTaskCreated);
      resetForm();
      onCreated();
      onClose();
    } catch (e: unknown) {
      setError(
        e instanceof Error ? e.message : t.kanbanCreateFailed
      );
    } finally {
      setSubmitting(false);
    }
  }

  function resetForm() {
    setTitle("");
    setBody("");
    setPriority(2);
    setLabelsInput("");
    setError(null);
  }

  function handleClose() {
    resetForm();
    onClose();
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      role="dialog"
      aria-modal="true"
      aria-labelledby="create-task-title"
      tabIndex={-1}
      onClick={handleClose}
      onKeyDown={(e) => {
        if (e.key === "Escape") handleClose();
      }}
    >
      <div
        className="bg-surface border border-border rounded-lg p-6 w-full max-w-md space-y-4"
        onClick={(e) => e.stopPropagation()}
      >
        <h3
          id="create-task-title"
          className="text-lg font-medium text-text-primary"
        >
          {t.kanbanCreateTask}
        </h3>

        <form onSubmit={handleSubmit} className="space-y-4">
          {/* Title */}
          <div>
            <label className="text-xs text-text-secondary block mb-1">
              {t.kanbanTitle} <span className="text-accent-pink">*</span>
            </label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              required
              autoFocus
              placeholder={t.kanbanTitlePlaceholder}
              className="w-full bg-background border border-border rounded-md px-3 py-2 text-sm text-text-primary placeholder:text-text-secondary focus:outline-none focus:border-accent-cyan"
            />
          </div>

          {/* Description */}
          <div>
            <label className="text-xs text-text-secondary block mb-1">
              {t.kanbanDescription}
            </label>
            <textarea
              value={body}
              onChange={(e) => setBody(e.target.value)}
              rows={3}
              placeholder={t.kanbanDescPlaceholder}
              className="w-full bg-background border border-border rounded-md px-3 py-2 text-sm text-text-primary resize-y placeholder:text-text-secondary focus:outline-none focus:border-accent-cyan"
            />
          </div>

          {/* Priority */}
          <div>
            <label className="text-xs text-text-secondary block mb-1">
              {t.kanbanPriority}
            </label>
            <select
              value={priority}
              onChange={(e) => setPriority(Number(e.target.value))}
              className="w-full bg-background border border-border rounded-md px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent-cyan"
            >
              <option value={1}>{t.kanbanPriorityLow}</option>
              <option value={2}>{t.kanbanPriorityNormal}</option>
              <option value={3}>{t.kanbanPriorityHigh}</option>
              <option value={4}>{t.kanbanPriorityCritical}</option>
            </select>
          </div>

          {/* Labels */}
          <div>
            <label className="text-xs text-text-secondary block mb-1">
              {t.kanbanLabels}
            </label>
            <input
              type="text"
              value={labelsInput}
              onChange={(e) => setLabelsInput(e.target.value)}
              placeholder={t.kanbanLabelsPlaceholder}
              className="w-full bg-background border border-border rounded-md px-3 py-2 text-sm text-text-primary placeholder:text-text-secondary focus:outline-none focus:border-accent-cyan"
            />
            <p className="text-[10px] text-text-secondary mt-1">
              {t.kanbanLabelsHint}
            </p>
          </div>

          {error && (
            <div className="p-2 rounded bg-accent-pink/10 text-accent-pink text-xs">
              {error}
            </div>
          )}

          {/* Actions */}
          <div className="flex gap-2 justify-end pt-1">
            <button
              type="button"
              onClick={handleClose}
              className="px-4 py-2 text-sm rounded-md text-text-secondary hover:text-text-primary border border-border-subtle transition-colors"
            >
              {t.kanbanCancel}
            </button>
            <button
              type="submit"
              disabled={submitting || !title.trim()}
              className="px-4 py-2 text-sm rounded-md bg-accent-pink text-white hover:bg-accent-pink/90 disabled:opacity-50"
            >
              {submitting ? t.kanbanCreating : t.kanbanCreateTask}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
