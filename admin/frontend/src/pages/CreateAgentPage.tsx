import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import type { AgentListItem, DeployProgress } from "../lib/admin-api";
import { adminApi, AdminApiError } from "../lib/admin-api";
import { useI18n } from "../hooks/useI18n";
import type { Translations } from "../i18n/zh";
import { showToast } from "../lib/toast";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface CreateForm {
  agentNumber: number;
  displayName: string;
  cpuLimit: string;
  memoryLimit: string;
  provider: string;
  model: string;
  apiKey: string;
  baseUrl: string;
  soul: string;
  envVars: Array<{ key: string; value: string }>;
}

interface ValidationErrors {
  [field: string]: string;
}

// ---------------------------------------------------------------------------
// Provider defaults
// ---------------------------------------------------------------------------

const PROVIDER_DEFAULTS: Record<
  string,
  { model: string; baseUrl: string }
> = {
  openrouter: {
    model: "anthropic/claude-sonnet-4-20250514",
    baseUrl: "https://openrouter.ai/api/v1",
  },
  anthropic: {
    model: "claude-sonnet-4-20250514",
    baseUrl: "https://api.anthropic.com/v1",
  },
  openai: {
    model: "gpt-4o",
    baseUrl: "https://api.openai.com/v1",
  },
  gemini: {
    model: "gemini-2.0-flash",
    baseUrl: "https://generativelanguage.googleapis.com/v1beta",
  },
  zhipuai: {
    model: "glm-4-plus",
    baseUrl: "https://open.bigmodel.cn/api/paas/v4",
  },
  minimax: {
    model: "MiniMax-M1",
    baseUrl: "https://api.minimaxi.com/anthropic/v1",
  },
  kimi: {
    model: "moonshot-v1-128k",
    baseUrl: "https://api.moonshot.cn/v1",
  },
  "anthropic-compat": {
    model: "",
    baseUrl: "",
  },
  custom: {
    model: "",
    baseUrl: "",
  },
};

const PROVIDER_OPTIONS = [
  { value: "openrouter", label: "OpenRouter" },
  { value: "anthropic", label: "Anthropic" },
  { value: "openai", label: "OpenAI" },
  { value: "gemini", label: "Gemini" },
  { value: "zhipuai", label: "ZhipuAI" },
  { value: "minimax", label: "MiniMax" },
  { value: "kimi", label: "Kimi" },
  { value: "anthropic-compat", label: "Anthropic 兼容" },
  { value: "custom", label: "OpenAI 兼容" },
];

// ---------------------------------------------------------------------------
// Step indicator
// ---------------------------------------------------------------------------

const STEP_LABELS = [
  "stepBasic",
  "stepLlm",
  "stepSoul",
  "stepReview",
] as const;

function StepIndicator({
  currentStep,
  t,
}: {
  currentStep: number;
  t: Translations;
}) {
  return (
    <div className="flex items-center gap-2 mb-8">
      {STEP_LABELS.map((key, idx) => {
        const stepNum = idx + 1;
        const isActive = idx === currentStep;
        const isCompleted = idx < currentStep;
        return (
          <div key={key} className="flex items-center gap-2">
            <div className="flex items-center gap-2">
              <span
                className={`inline-flex items-center justify-center h-8 w-8 rounded-full text-sm font-medium transition-colors ${
                  isActive
                    ? "bg-primary text-white"
                    : isCompleted
                      ? "bg-green-500 text-white"
                      : "bg-muted text-muted-foreground"
                }`}
              >
                {isCompleted ? (
                  <svg
                    className="h-4 w-4"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                    strokeWidth={2}
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      d="M5 13l4 4L19 7"
                    />
                  </svg>
                ) : (
                  stepNum
                )}
              </span>
              <span
                className={`text-sm ${isActive ? "font-medium text-foreground" : "text-muted-foreground"}`}
              >
                {t[key]}
              </span>
            </div>
            {idx < STEP_LABELS.length - 1 && (
              <div
                className={`h-px w-8 ${isCompleted ? "bg-green-500" : "bg-border"}`}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function CreateAgentPage() {
  const { t } = useI18n();
  const navigate = useNavigate();

  const [agents, setAgents] = useState<AgentListItem[]>([]);
  const [currentStep, setCurrentStep] = useState(0);
  const [validationErrors, setValidationErrors] = useState<ValidationErrors>(
    {}
  );
  const [deploying, setDeploying] = useState(false);
  const [deployResult, setDeployResult] = useState<DeployProgress | null>(null);
  const [deployError, setDeployError] = useState<string | null>(null);

  const [form, setForm] = useState<CreateForm>({
    agentNumber: 1,
    displayName: "",
    cpuLimit: "1000m",
    memoryLimit: "1Gi",
    provider: "openrouter",
    model: PROVIDER_DEFAULTS.openrouter.model,
    apiKey: "",
    baseUrl: PROVIDER_DEFAULTS.openrouter.baseUrl,
    soul: "",
    envVars: [],
  });

  // Load agents to determine next agent number
  useEffect(() => {
    adminApi.listAgents().then((res) => {
      setAgents(res.agents);
      const maxNum = res.agents.reduce(
        (max, a) => Math.max(max, a.id),
        0
      );
      setForm((prev) => ({ ...prev, agentNumber: maxNum + 1 }));
    });
  }, []);

  // Load SOUL.md template
  useEffect(() => {
    adminApi
      .getTemplate("soul")
      .then((res) =>
        setForm((prev) => ({ ...prev, soul: prev.soul || res.content }))
      )
      .catch(() => {
        // Use a default template if API fails
        setForm((prev) => ({
          ...prev,
          soul:
            prev.soul ||
            "# Agent Identity\n\nYou are a helpful AI assistant.\n\n# Behavior\n\nBe polite, accurate, and helpful.\n",
        }));
      });
  }, []);

  // ----- Form helpers -----
  function updateForm(partial: Partial<CreateForm>) {
    setForm((prev) => ({ ...prev, ...partial }));
  }

  // ----- Validation -----
  function validateStep(step: number): boolean {
    const errors: ValidationErrors = {};

    if (step === 0) {
      if (form.agentNumber < 1) {
        errors.agentNumber = t.validationPositiveNumber;
      }
      if (agents.some((a) => a.id === form.agentNumber)) {
        errors.agentNumber = t.validationAgentExists;
      }
      if (!/^\d+m?$/.test(form.cpuLimit)) {
        errors.cpuLimit = t.invalidCpuFormat;
      }
      if (!/^\d+(Ki|Mi|Gi)$/.test(form.memoryLimit)) {
        errors.memoryLimit = t.invalidMemoryFormat;
      }
    }

    if (step === 1) {
      if (!form.apiKey.trim()) {
        errors.apiKey = t.validationRequired;
      }
      if (!form.model.trim()) {
        errors.model = t.validationRequired;
      }
    }

    setValidationErrors(errors);
    return Object.keys(errors).length === 0;
  }

  function handleNext() {
    if (validateStep(currentStep)) {
      setCurrentStep((s) => Math.min(s + 1, 3));
    }
  }

  function handlePrev() {
    setCurrentStep((s) => Math.max(s - 1, 0));
  }

  // ----- Deploy -----
  async function handleDeploy() {
    setDeploying(true);
    setDeployError(null);
    setDeployResult(null);

    try {
      const result = await adminApi.createAgent({
        agent_number: form.agentNumber,
        display_name: form.displayName || undefined,
        resources: {
          cpu_request: form.cpuLimit,
          cpu_limit: form.cpuLimit,
          memory_request: form.memoryLimit,
          memory_limit: form.memoryLimit,
        },
        llm: {
          provider: form.provider,
          api_key: form.apiKey,
          model: form.model,
          base_url: form.baseUrl || null,
        },
        soul_md: form.soul,
        extra_env: form.envVars.map((v) => ({
          key: v.key,
          value: v.value,
          masked: false,
          is_secret: false,
        })),
        terminal_enabled: false,
        browser_enabled: false,
        streaming_enabled: true,
        memory_enabled: false,
        session_reset_enabled: false,
      });

      setDeployResult(result);
      showToast(t.deploySuccess);

      // Redirect after a short delay
      setTimeout(() => {
        navigate(`/agents/hermes-gateway-${form.agentNumber}`);
      }, 1500);
    } catch (err) {
      const msg =
        err instanceof AdminApiError
          ? err.detail
          : err instanceof Error
            ? err.message
            : t.deployFailed;
      setDeployError(msg);
      showToast(msg, "error");
    } finally {
      setDeploying(false);
    }
  }

  // ----- Provider change handler -----
  function handleProviderChange(provider: string) {
    const defaults = PROVIDER_DEFAULTS[provider] || PROVIDER_DEFAULTS.custom;
    setForm((prev) => ({
      ...prev,
      provider,
      model: defaults.model,
      baseUrl: defaults.baseUrl,
    }));
    setValidationErrors({});
  }

  // ----- Step content -----
  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between mb-4 shrink-0">
        <div>
          <h1 className="text-2xl font-bold">{t.createTitle}</h1>
          <p className="text-sm text-muted-foreground">
            {t.createSubtitle}
          </p>
        </div>
        <button
          onClick={() => navigate("/")}
          className="h-9 px-4 text-sm border border-border hover:bg-accent rounded"
        >
          {t.cancel}
        </button>
      </div>

      {/* Step indicator */}
      <div className="shrink-0 mb-4">
        <StepIndicator currentStep={currentStep} t={t} />
      </div>

      {/* Step content */}
      <div className="rounded-lg border border-border bg-card flex flex-col flex-1 min-h-0">
        <div className="p-6 overflow-y-auto flex-1 min-h-0">
        {currentStep === 0 && (
          <StepBasicInfo
            form={form}
            errors={validationErrors}
            onChange={updateForm}
            t={t}
          />
        )}
        {currentStep === 1 && (
          <StepLlmConfig
            form={form}
            errors={validationErrors}
            onProviderChange={handleProviderChange}
            onChange={updateForm}
            t={t}
          />
        )}
        {currentStep === 2 && (
          <StepAgentConfig
            form={form}
            onChange={updateForm}
            t={t}
          />
        )}
        {currentStep === 3 && (
          <StepConfirm
            form={form}
            deploying={deploying}
            deployResult={deployResult}
            deployError={deployError}
            onDeploy={handleDeploy}
            t={t}
          />
        )}

        </div>

        {/* Navigation buttons - always visible at bottom */}
        {!deploying && (
          <div className="flex justify-between items-center px-6 py-3 border-t border-border bg-card shrink-0">
            <button
              onClick={handlePrev}
              disabled={currentStep === 0}
              className="h-9 px-4 text-sm border border-border hover:bg-accent rounded disabled:opacity-50"
            >
              {t.back}
            </button>
            <div className="flex gap-3">
              {currentStep < 3 && (
                <button
                  onClick={handleNext}
                  className="h-9 px-6 text-sm rounded bg-primary text-white hover:bg-primary/90"
                >
                  {t.confirm}
                </button>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step 1: Basic Info
// ---------------------------------------------------------------------------

function StepBasicInfo({
  form,
  errors,
  onChange,
  t,
}: {
  form: CreateForm;
  errors: ValidationErrors;
  onChange: (partial: Partial<CreateForm>) => void;
  t: Translations;
}) {
  return (
    <div className="space-y-4 max-w-lg">
      {/* Agent Number */}
      <div>
        <label className="block text-sm font-medium mb-1">
          {t.agentNumber}
        </label>
        <input
          type="number"
          value={form.agentNumber}
          onChange={(e) =>
            onChange({ agentNumber: parseInt(e.target.value, 10) || 0 })
          }
          className="h-9 w-full px-3 text-sm border border-border rounded"
        />
        {errors.agentNumber && (
          <p className="text-xs text-destructive mt-1">{errors.agentNumber}</p>
        )}
      </div>

      {/* Display Name */}
      <div>
        <label className="block text-sm font-medium mb-1">
          {t.displayName}
        </label>
        <input
          type="text"
          value={form.displayName}
          onChange={(e) => onChange({ displayName: e.target.value })}
          placeholder={t.displayNamePlaceholder}
          className="h-9 w-full px-3 text-sm border border-border rounded"
        />
      </div>

      {/* CPU Limit */}
      <div>
        <label className="block text-sm font-medium mb-1">
          {t.cpuLimit}
        </label>
        <input
          type="text"
          value={form.cpuLimit}
          onChange={(e) => onChange({ cpuLimit: e.target.value })}
          placeholder="1000m"
          className="h-9 w-full px-3 text-sm border border-border rounded font-mono"
        />
        {errors.cpuLimit && (
          <p className="text-xs text-destructive mt-1">{errors.cpuLimit}</p>
        )}
      </div>

      {/* Memory Limit */}
      <div>
        <label className="block text-sm font-medium mb-1">
          {t.memoryLimit}
        </label>
        <input
          type="text"
          value={form.memoryLimit}
          onChange={(e) => onChange({ memoryLimit: e.target.value })}
          placeholder="1Gi"
          className="h-9 w-full px-3 text-sm border border-border rounded font-mono"
        />
        {errors.memoryLimit && (
          <p className="text-xs text-destructive mt-1">
            {errors.memoryLimit}
          </p>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step 2: LLM Config
// ---------------------------------------------------------------------------

function StepLlmConfig({
  form,
  errors,
  onProviderChange,
  onChange,
  t,
}: {
  form: CreateForm;
  errors: ValidationErrors;
  onProviderChange: (provider: string) => void;
  onChange: (partial: Partial<CreateForm>) => void;
  t: Translations;
}) {
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{
    success: boolean;
    message: string;
  } | null>(null);

  async function testConnection() {
    setTesting(true);
    setTestResult(null);
    try {
      const result = await adminApi.testLlmConnection({
        provider: form.provider,
        api_key: form.apiKey,
        model: form.model,
        base_url: form.baseUrl || null,
      });
      if (result.success) {
        setTestResult({
          success: true,
          message: `${t.llmTestSuccess} (${result.latency_ms}ms)`,
        });
      } else {
        setTestResult({
          success: false,
          message: `${t.llmTestFailed}: ${result.error || t.errorGeneric}`,
        });
      }
    } catch (err) {
      setTestResult({
        success: false,
        message: `${t.llmTestFailed}: ${err instanceof Error ? err.message : t.errorNetwork}`,
      });
    } finally {
      setTesting(false);
    }
  }

  return (
    <div className="space-y-4 max-w-lg">
      {/* Provider */}
      <div>
        <label className="block text-sm font-medium mb-1">
          {t.llmProvider}
        </label>
        <select
          value={form.provider}
          onChange={(e) => onProviderChange(e.target.value)}
          className="h-9 w-full px-3 text-sm border border-border rounded bg-background"
        >
          {PROVIDER_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </div>

      {/* Model */}
      <div>
        <label className="block text-sm font-medium mb-1">
          {t.llmModel}
        </label>
        <input
          type="text"
          value={form.model}
          onChange={(e) => onChange({ model: e.target.value })}
          className="h-9 w-full px-3 text-sm border border-border rounded font-mono"
        />
        {errors.model && (
          <p className="text-xs text-destructive mt-1">{errors.model}</p>
        )}
      </div>

      {/* API Key */}
      <div>
        <label className="block text-sm font-medium mb-1">
          {t.llmApiKey}
        </label>
        <input
          type="password"
          value={form.apiKey}
          onChange={(e) => onChange({ apiKey: e.target.value })}
          placeholder="sk-..."
          className="h-9 w-full px-3 text-sm border border-border rounded font-mono"
        />
        {errors.apiKey && (
          <p className="text-xs text-destructive mt-1">{errors.apiKey}</p>
        )}
      </div>

      {/* Base URL */}
      <div>
        <label className="block text-sm font-medium mb-1">
          {t.llmBaseUrl}
        </label>
        <input
          type="text"
          value={form.baseUrl}
          onChange={(e) => onChange({ baseUrl: e.target.value })}
          className="h-9 w-full px-3 text-sm border border-border rounded font-mono"
        />
      </div>

      {/* Test Connection */}
      <div className="flex items-center gap-3">
        <button
          onClick={testConnection}
          disabled={testing || !form.apiKey}
          className="h-9 px-4 text-sm border border-border hover:bg-accent rounded disabled:opacity-50"
        >
          {testing ? "..." : t.llmTestConnection}
        </button>
        {testResult && (
          <span
            className={`text-sm ${testResult.success ? "text-green-600" : "text-destructive"}`}
          >
            {testResult.message}
          </span>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step 3: Agent Config (SOUL.md + env vars)
// ---------------------------------------------------------------------------

function StepAgentConfig({
  form,
  onChange,
  t,
}: {
  form: CreateForm;
  onChange: (partial: Partial<CreateForm>) => void;
  t: Translations;
}) {
  function addEnvVar() {
    onChange({
      envVars: [...form.envVars, { key: "", value: "" }],
    });
  }

  function removeEnvVar(index: number) {
    onChange({
      envVars: form.envVars.filter((_, i) => i !== index),
    });
  }

  function updateEnvVar(
    index: number,
    field: "key" | "value",
    val: string
  ) {
    const updated = form.envVars.map((v, i) =>
      i === index ? { ...v, [field]: val } : v
    );
    onChange({ envVars: updated });
  }

  return (
    <div className="space-y-6">
      {/* SOUL.md */}
      <div>
        <label className="block text-sm font-medium mb-1">
          {t.soulContent}
        </label>
        <textarea
          value={form.soul}
          onChange={(e) => onChange({ soul: e.target.value })}
          className="w-full h-[400px] p-3 text-sm border border-border rounded font-mono bg-muted resize-y"
          spellCheck={false}
        />
      </div>

      {/* Extra env vars */}
      <div>
        <label className="block text-sm font-medium mb-2">
          {t.extraEnv}
        </label>
        <div className="space-y-2">
          {form.envVars.map((v, i) => (
            <div key={i} className="flex items-center gap-2">
              <input
                type="text"
                value={v.key}
                onChange={(e) => updateEnvVar(i, "key", e.target.value)}
                placeholder={t.envKey}
                className="h-9 px-3 text-sm border border-border rounded flex-1 font-mono"
              />
              <input
                type="text"
                value={v.value}
                onChange={(e) => updateEnvVar(i, "value", e.target.value)}
                placeholder={t.envValue}
                className="h-9 px-3 text-sm border border-border rounded flex-[2] font-mono"
              />
              <button
                onClick={() => removeEnvVar(i)}
                className="h-9 px-2 text-xs border border-border hover:bg-accent rounded text-destructive"
              >
                {t.removeEnvVar}
              </button>
            </div>
          ))}
        </div>
        <button
          onClick={addEnvVar}
          className="h-9 px-4 text-sm border border-border hover:bg-accent rounded mt-2"
        >
          + {t.addEnvVar}
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step 4: Confirm & Deploy
// ---------------------------------------------------------------------------

function StepConfirm({
  form,
  deploying,
  deployResult,
  deployError,
  onDeploy,
  t,
}: {
  form: CreateForm;
  deploying: boolean;
  deployResult: DeployProgress | null;
  deployError: string | null;
  onDeploy: () => void;
  t: Translations;
}) {
  const providerLabel =
    PROVIDER_OPTIONS.find((p) => p.value === form.provider)?.label ||
    form.provider;

  const stepLabels = [
    t.deployStepSecret,
    t.deployStepInitData,
    t.deployStepCreateDeployment,
    t.deployStepUpdateIngress,
    t.deployStepWaitReady,
  ];

  return (
    <div className="space-y-6">
      {/* Summary card */}
      <div className="rounded-lg border border-border bg-muted p-4">
        <h3 className="text-sm font-medium mb-3">
          {t.stepReview}
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-2 text-sm">
          <SummaryRow label={t.agentNumber} value={String(form.agentNumber)} />
          <SummaryRow label={t.displayName} value={form.displayName || "-"} />
          <SummaryRow label={t.cpuLimit} value={form.cpuLimit} />
          <SummaryRow label={t.memoryLimit} value={form.memoryLimit} />
          <SummaryRow label={t.llmProvider} value={providerLabel} />
          <SummaryRow label={t.llmModel} value={form.model} />
          <SummaryRow
            label={t.llmApiKey}
            value={form.apiKey ? "****" : "-"}
          />
          <SummaryRow label={t.llmBaseUrl} value={form.baseUrl || "-"} />
          {form.envVars.length > 0 && (
            <SummaryRow
              label={t.extraEnv}
              value={t.envVarCount.replace("{n}", String(form.envVars.length))}
            />
          )}
        </div>
      </div>

      {/* SOUL.md preview */}
      <div>
        <label className="block text-sm font-medium mb-1">
          {t.soulContent}
        </label>
        <pre className="bg-muted p-3 rounded text-xs font-mono max-h-[200px] overflow-auto">
          {form.soul.slice(0, 500)}
          {form.soul.length > 500 ? "\n..." : ""}
        </pre>
      </div>

      {/* Deploy progress */}
      {(deploying || deployResult || deployError) && (
        <div className="rounded-lg border border-border p-4">
          <h3 className="text-sm font-medium mb-3">
            {t.deploying}
          </h3>
          <div className="space-y-2">
            {stepLabels.map((label, idx) => {
              const stepInfo = deployResult?.steps?.[idx];
              const status = deploying
                ? stepInfo?.status || (idx === 0 ? "running" : "pending")
                : deployError
                  ? stepInfo?.status || (idx === 0 ? "failed" : "pending")
                  : deployResult
                    ? stepInfo?.status || "done"
                    : "pending";

              return (
                <DeployStepRow
                  key={idx}
                  label={label}
                  status={
                    status as "pending" | "running" | "done" | "failed"
                  }
                  message={stepInfo?.message}
                />
              );
            })}
          </div>
        </div>
      )}

      {/* Error */}
      {deployError && (
        <div className="rounded-md bg-destructive/10 border border-destructive/20 p-3">
          <p className="text-sm text-destructive">{deployError}</p>
        </div>
      )}

      {/* Deploy button */}
      {!deployResult && (
        <button
          onClick={onDeploy}
          disabled={deploying}
          className="h-10 px-8 text-sm rounded bg-primary text-white hover:bg-primary/90 disabled:opacity-50"
        >
          {deploying ? t.deploying : t.deploy}
        </button>
      )}

      {/* Success message */}
      {deployResult && (
        <div className="rounded-md bg-green-500/10 border border-green-500/20 p-3">
          <p className="text-sm text-green-600">{t.deploySuccess}</p>
        </div>
      )}
    </div>
  );
}

function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between py-1 border-b border-border/50">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-mono text-xs">{value}</span>
    </div>
  );
}

function DeployStepRow({
  label,
  status,
  message,
}: {
  label: string;
  status: "pending" | "running" | "done" | "failed";
  message?: string;
}) {
  const iconMap = {
    pending: <span className="inline-block h-4 w-4 rounded-full bg-gray-300" />,
    running: (
      <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />
    ),
    done: (
      <svg
        className="h-4 w-4 text-green-500"
        fill="none"
        viewBox="0 0 24 24"
        stroke="currentColor"
        strokeWidth={2}
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          d="M5 13l4 4L19 7"
        />
      </svg>
    ),
    failed: (
      <svg
        className="h-4 w-4 text-red-500"
        fill="none"
        viewBox="0 0 24 24"
        stroke="currentColor"
        strokeWidth={2}
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          d="M6 18L18 6M6 6l12 12"
        />
      </svg>
    ),
  };

  return (
    <div className="flex items-center gap-3 text-sm">
      {iconMap[status]}
      <span className={status === "pending" ? "text-muted-foreground" : ""}>
        {label}
      </span>
      {message && (
        <span className="text-xs text-muted-foreground ml-auto">
          {message}
        </span>
      )}
    </div>
  );
}
