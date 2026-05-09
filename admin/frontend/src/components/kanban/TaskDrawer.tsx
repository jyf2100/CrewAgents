import { useState, useEffect } from "react";
import { useI18n } from "../../hooks/useI18n";
import type { KanbanTask, KanbanTaskDetail, KanbanComment, KanbanStatus } from "./kanban-types";
import { adminFetch } from "../../lib/admin-api";
import { showToast } from "../../lib/toast";

interface TaskDrawerProps {
  task: KanbanTask | null;
  agentId: number;
  onClose: () => void;
  onUpdate: () => void;
}

const STATUS_KEYS: { value: KanbanStatus; labelKey: keyof import("../../i18n/zh").Translations }[] = [
  { value: "triage", labelKey: "kanbanTriage" },
  { value: "todo", labelKey: "kanbanTodo" },
  { value: "ready", labelKey: "kanbanReady" },
  { value: "running", labelKey: "kanbanRunning" },
  { value: "done", labelKey: "kanbanDone" },
  { value: "blocked", labelKey: "kanbanBlocked" },
  { value: "archived", labelKey: "kanbanBlocked" },
];

function formatTimestamp(ts: number | null | undefined): string {
  if (!ts) return "";
  return new Date(ts * 1000).toLocaleString();
}

export function TaskDrawer({ task, agentId, onClose, onUpdate }: TaskDrawerProps) {
  const { t } = useI18n();
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [status, setStatus] = useState<KanbanStatus>("triage");
  const [priority, setPriority] = useState(2);
  const [assignee, setAssignee] = useState("");
  const [comments, setComments] = useState<KanbanComment[]>([]);
  const [commentInput, setCommentInput] = useState("");
  const [saving, setSaving] = useState(false);
  const [commentsLoading, setCommentsLoading] = useState(false);

  useEffect(() => {
    if (!task) return;
    setTitle(task.title);
    setBody(task.body ?? "");
    setStatus(task.status);
    setPriority(task.priority ?? 2);
    setAssignee(task.assignee ?? "default");

    let cancelled = false;
    setCommentsLoading(true);
    adminFetch<{ task: KanbanTaskDetail }>(
      `/agents/${agentId}/kanban/tasks/${task.id}`
    )
      .then((data) => {
        if (!cancelled) {
          setComments(Array.isArray(data.task.comments) ? data.task.comments : []);
        }
      })
      .catch(() => { if (!cancelled) setComments([]); })
      .finally(() => { if (!cancelled) setCommentsLoading(false); });
    return () => { cancelled = true; };
  }, [task, agentId]);

  const isOpen = task !== null;

  async function handleSave() {
    if (!task) return;
    setSaving(true);
    try {
      await adminFetch<KanbanTask>(
        `/agents/${agentId}/kanban/tasks/${task.id}`,
        {
          method: "PATCH",
          body: JSON.stringify({ title, body, status, priority, assignee: assignee.trim() || undefined }),
        }
      );
      showToast(t.kanbanTaskUpdated);
      onUpdate();
    } catch (e: unknown) {
      showToast(
        e instanceof Error ? e.message : t.kanbanUpdateFailed,
        "error"
      );
    } finally {
      setSaving(false);
    }
  }

  async function handleAddComment() {
    if (!task || !commentInput.trim()) return;
    setSaving(true);
    try {
      await adminFetch<KanbanComment>(
        `/agents/${agentId}/kanban/tasks/${task.id}/comments`,
        {
          method: "POST",
          body: JSON.stringify({ body: commentInput.trim() }),
        }
      );
      setCommentInput("");
      const data = await adminFetch<{ task: KanbanTaskDetail }>(
        `/agents/${agentId}/kanban/tasks/${task.id}`
      );
      setComments(Array.isArray(data.task.comments) ? data.task.comments : []);
    } catch (e: unknown) {
      showToast(
        e instanceof Error ? e.message : t.kanbanCommentFailed,
        "error"
      );
    } finally {
      setSaving(false);
    }
  }

  async function handleUnblock() {
    if (!task) return;
    setSaving(true);
    try {
      await adminFetch<KanbanTask>(
        `/agents/${agentId}/kanban/tasks/${task.id}`,
        {
          method: "PATCH",
          body: JSON.stringify({ status: "ready" }),
        }
      );
      showToast(t.kanbanTaskUnblocked);
      onUpdate();
      onClose();
    } catch (e: unknown) {
      showToast(
        e instanceof Error ? e.message : t.kanbanUnblockFailed,
        "error"
      );
    } finally {
      setSaving(false);
    }
  }

  function handleQuickStatus(newStatus: KanbanStatus) {
    setStatus(newStatus);
  }

  const taskDetail = task as KanbanTaskDetail | null;
  const latestSummary = taskDetail?.latest_summary ?? null;
  const taskResult = taskDetail?.result ?? null;
  const lastFailureError = taskDetail?.last_failure_error ?? null;

  return (
    <>
      {isOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/40"
          onClick={onClose}
          aria-hidden="true"
        />
      )}

      <div
        role="dialog"
        aria-modal="true"
        aria-label={task ? `${t.kanbanTaskDetail}: ${task.title}` : t.kanbanTaskDetail}
        className={`fixed top-0 right-0 z-50 h-full w-full max-w-md bg-surface border-l border-border shadow-xl transition-transform duration-300 ease-out ${
          isOpen ? "translate-x-0" : "translate-x-full"
        }`}
      >
        <div className="flex flex-col h-full">
          <div className="flex items-center justify-between px-4 py-3 border-b border-border">
            <h2 className="text-sm font-medium text-text-primary truncate">
              {t.kanbanTaskDetail}
            </h2>
            <button
              onClick={onClose}
              className="text-text-secondary hover:text-text-primary transition-colors"
              aria-label="Close drawer"
            >
              <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          {task ? (
            <div className="flex-1 overflow-y-auto p-4 space-y-5">
              <div>
                <label className="text-xs text-text-secondary block mb-1">{t.kanbanTitle}</label>
                <input
                  type="text"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  className="w-full bg-background border border-border rounded-md px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent-cyan"
                />
              </div>

              <div>
                <label className="text-xs text-text-secondary block mb-1">{t.kanbanDescription}</label>
                <textarea
                  value={body}
                  onChange={(e) => setBody(e.target.value)}
                  rows={4}
                  className="w-full bg-background border border-border rounded-md px-3 py-2 text-sm text-text-primary resize-y focus:outline-none focus:border-accent-cyan"
                />
              </div>

              <div>
                <label className="text-xs text-text-secondary block mb-1.5">{t.kanbanStatus}</label>
                <div className="flex flex-wrap gap-1.5">
                  {STATUS_KEYS.map((opt) => (
                    <button
                      key={opt.value}
                      onClick={() => handleQuickStatus(opt.value)}
                      className={`px-2.5 py-1 text-xs rounded-md border transition-colors ${
                        status === opt.value
                          ? "bg-accent-pink/15 border-accent-pink/40 text-accent-pink"
                          : "border-border text-text-secondary hover:border-accent-cyan/40 hover:text-text-primary"
                      }`}
                    >
                      {t[opt.labelKey]}
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <label className="text-xs text-text-secondary block mb-1">{t.kanbanPriority}</label>
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

              <div>
                <label className="text-xs text-text-secondary block mb-1">{t.kanbanAssignee}</label>
                <input
                  type="text"
                  value={assignee}
                  onChange={(e) => setAssignee(e.target.value)}
                  placeholder="default"
                  className="w-full bg-background border border-border rounded-md px-3 py-2 text-sm text-text-primary placeholder:text-text-secondary focus:outline-none focus:border-accent-cyan"
                />
                <p className="text-[10px] text-text-secondary mt-1">
                  {t.kanbanAssigneeHint}
                </p>
              </div>

              <div className="text-xs text-text-secondary space-y-1 border-t border-border pt-3">
                <p>{t.kanbanId}: {task.id}</p>
                <p>{t.kanbanCreated}: {formatTimestamp(task.created_at)}</p>
                {task.assignee && <p>{t.kanbanAssignee}: {task.assignee}</p>}
                {task.completed_at && <p>{t.kanbanCompleted}: {formatTimestamp(task.completed_at)}</p>}
                {task.block_reason && (
                  <p className="text-accent-pink">{t.kanbanBlockedReason}: {task.block_reason}</p>
                )}
              </div>

              {(latestSummary || taskResult || lastFailureError) && (
                <div className="border-t border-border pt-3">
                  <h3 className="text-xs font-medium text-text-secondary mb-2">{t.kanbanResult}</h3>
                  {latestSummary && (
                    <p className="text-xs text-text-primary bg-surface-secondary rounded-md p-2 mb-2">
                      {latestSummary}
                    </p>
                  )}
                  {taskResult && (
                    <p className="text-xs text-text-primary bg-surface-secondary rounded-md p-2 mb-2">
                      {taskResult}
                    </p>
                  )}
                  {lastFailureError && (
                    <p className="text-xs text-accent-pink bg-accent-pink/10 rounded-md p-2">
                      {lastFailureError}
                    </p>
                  )}
                </div>
              )}

              <div className="border-t border-border pt-3">
                <h3 className="text-xs font-medium text-text-secondary mb-2">
                  {t.kanbanComments} ({comments.length})
                </h3>
                {commentsLoading ? (
                  <p className="text-xs text-text-secondary">{t.loading}</p>
                ) : comments.length === 0 ? (
                  <p className="text-xs text-text-secondary">{t.kanbanNoComments}</p>
                ) : (
                  <div className="space-y-2 mb-3">
                    {comments.map((c) => (
                      <div key={c.id} className="bg-surface-secondary rounded-md p-2.5">
                        <div className="flex items-center justify-between mb-1">
                          <span className="text-xs font-medium text-accent-cyan">{c.author}</span>
                          <span className="text-[10px] text-text-secondary">{formatTimestamp(c.created_at)}</span>
                        </div>
                        <p className="text-xs text-text-primary leading-relaxed">{c.body}</p>
                      </div>
                    ))}
                  </div>
                )}

                <div className="flex gap-2">
                  <input
                    type="text"
                    value={commentInput}
                    onChange={(e) => setCommentInput(e.target.value)}
                    placeholder={t.kanbanAddComment}
                    className="flex-1 bg-background border border-border rounded-md px-3 py-1.5 text-xs text-text-primary placeholder:text-text-secondary focus:outline-none focus:border-accent-cyan"
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && !e.shiftKey) {
                        e.preventDefault();
                        handleAddComment();
                      }
                    }}
                  />
                  <button
                    onClick={handleAddComment}
                    disabled={saving || !commentInput.trim()}
                    className="px-3 py-1.5 text-xs rounded-md bg-accent-pink text-white hover:bg-accent-pink/90 disabled:opacity-50"
                  >
                    {t.kanbanCommentSend}
                  </button>
                </div>
              </div>
            </div>
          ) : (
            <div className="flex-1" />
          )}

          <div className="border-t border-border px-4 py-3 flex justify-end gap-2">
            {status === "blocked" && (
              <button
                onClick={handleUnblock}
                disabled={saving}
                className="px-4 py-2 text-sm rounded-md bg-accent-cyan text-white hover:bg-accent-cyan/90 disabled:opacity-50"
              >
                {saving ? t.kanbanUnblocking : t.kanbanUnblockRetry}
              </button>
            )}
            <button
              onClick={onClose}
              className="px-4 py-2 text-sm rounded-md text-text-secondary hover:text-text-primary border border-border-subtle transition-colors"
            >
              {t.kanbanCancel}
            </button>
            <button
              onClick={handleSave}
              disabled={saving}
              className="px-4 py-2 text-sm rounded-md bg-accent-pink text-white hover:bg-accent-pink/90 disabled:opacity-50"
            >
              {saving ? t.kanbanSaving : t.kanbanSave}
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
