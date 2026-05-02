import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { adminApi } from "../../lib/admin-api";
import { useI18n } from "../../hooks/useI18n";

export function TaskSubmitPage() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [prompt, setPrompt] = useState("");
  const [instructions, setInstructions] = useState("");
  const [priority, setPriority] = useState(1);
  const [timeout, setTimeout_] = useState(600);
  const [maxRetries, setMaxRetries] = useState(2);
  const [callbackUrl, setCallbackUrl] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!prompt.trim()) return;
    setSubmitting(true);
    setError("");
    try {
      const result = await adminApi.orchestratorSubmitTask({
        prompt: prompt.trim(),
        instructions: instructions.trim() || undefined,
        priority,
        timeout_seconds: timeout,
        max_retries: maxRetries,
        callback_url: callbackUrl.trim() || undefined,
      });
      navigate(`/orchestrator/tasks/${result.task_id}`);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : (t.orchestratorSubmitError || "Failed to submit task"));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="p-6 max-w-2xl">
      <h1 className="text-xl font-bold text-text-primary mb-6">{t.orchestratorSubmitTask || "Submit Task"}</h1>
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="block text-sm text-text-secondary mb-1">{t.orchestratorPromptLabel || "Prompt"} *</label>
          <textarea value={prompt} onChange={e => setPrompt(e.target.value)} rows={6}
            className="w-full bg-surface/80 border border-border/50 rounded-md p-3 text-text-primary text-sm focus:outline-none focus:border-accent-cyan/50"
            placeholder="Enter task prompt..." required />
        </div>
        <div>
          <label className="block text-sm text-text-secondary mb-1">{t.orchestratorInstructionsLabel || "System Instructions"}</label>
          <textarea value={instructions} onChange={e => setInstructions(e.target.value)} rows={3}
            className="w-full bg-surface/80 border border-border/50 rounded-md p-3 text-text-primary text-sm focus:outline-none focus:border-accent-cyan/50"
            placeholder="Optional system instructions..." />
        </div>
        <div className="grid grid-cols-3 gap-4">
          <div>
            <label className="block text-sm text-text-secondary mb-1">{t.orchestratorPriorityLabel || "Priority"}</label>
            <input type="number" min={1} max={10} value={priority} onChange={e => setPriority(Number(e.target.value))}
              className="w-full bg-surface/80 border border-border/50 rounded-md p-2 text-text-primary text-sm" />
          </div>
          <div>
            <label className="block text-sm text-text-secondary mb-1">{t.orchestratorTimeoutLabel || "Timeout (seconds)"}</label>
            <input type="number" min={10} max={3600} value={timeout} onChange={e => setTimeout_(Number(e.target.value))}
              className="w-full bg-surface/80 border border-border/50 rounded-md p-2 text-text-primary text-sm" />
          </div>
          <div>
            <label className="block text-sm text-text-secondary mb-1">{t.orchestratorTaskRetries || "Retries"}</label>
            <input type="number" min={0} max={5} value={maxRetries} onChange={e => setMaxRetries(Number(e.target.value))}
              className="w-full bg-surface/80 border border-border/50 rounded-md p-2 text-text-primary text-sm" />
          </div>
        </div>
        <div>
          <label className="block text-sm text-text-secondary mb-1">{t.orchestratorCallbackLabel || "Callback URL (HTTPS)"}</label>
          <input type="url" value={callbackUrl} onChange={e => setCallbackUrl(e.target.value)}
            className="w-full bg-surface/80 border border-border/50 rounded-md p-2 text-text-primary text-sm"
            placeholder="https://example.com/webhook" />
        </div>
        {error && <p className="text-red-400 text-sm">{error}</p>}
        <button type="submit" disabled={submitting || !prompt.trim()}
          className="px-6 py-2 bg-accent-cyan/80 text-white rounded-md hover:bg-accent-cyan disabled:opacity-50 disabled:cursor-not-allowed text-sm font-medium">
          {submitting ? (t.orchestratorSubmitting || "Submitting...") : (t.orchestratorSubmitTask || "Submit Task")}
        </button>
      </form>
    </div>
  );
}
