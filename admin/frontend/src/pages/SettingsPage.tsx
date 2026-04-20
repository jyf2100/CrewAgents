import { useState, useEffect, useCallback, useRef } from "react";
import type {
  AdminSettings,
  ClusterStatus,
} from "../lib/admin-api";
import { adminApi } from "../lib/admin-api";
import { useI18n } from "../hooks/useI18n";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { LoadingSpinner } from "../components/LoadingSpinner";
import { getApiError } from "../lib/utils";
import { showToast } from "../lib/toast";

// ---------------------------------------------------------------------------
// Template tab definitions
// ---------------------------------------------------------------------------

const TEMPLATE_TABS = [
  { type: "deployment", labelKey: "templateDeployment" as const },
  { type: "env", labelKey: "templateEnv" as const },
  { type: "config", labelKey: "templateConfig" as const },
  { type: "soul", labelKey: "templateSoul" as const },
] as const;

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function SettingsPage() {
  const { t } = useI18n();

  const [settings, setSettings] = useState<AdminSettings | null>(null);
  const [cluster, setCluster] = useState<ClusterStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Admin key state
  const [newKey, setNewKey] = useState("");
  const [confirmKey, setConfirmKey] = useState("");
  const [changingKey, setChangingKey] = useState(false);
  const [showKeyDialog, setShowKeyDialog] = useState(false);

  // Resources state
  const [cpuLimit, setCpuLimit] = useState("");
  const [memoryLimit, setMemoryLimit] = useState("");
  const [savingResources, setSavingResources] = useState(false);

  // Template state
  const [templateTab, setTemplateTab] = useState<string>("deployment");
  const [templateContents, setTemplateContents] = useState<
    Record<string, string>
  >({});
  const templateContentsRef = useRef(templateContents);
  templateContentsRef.current = templateContents;
  const [templateLoading, setTemplateLoading] = useState(false);
  const [templateSaving, setTemplateSaving] = useState(false);

  // Section collapse state
  const [openSections, setOpenSections] = useState<Record<string, boolean>>({
    cluster: true,
    adminKey: true,
    resources: true,
    templates: true,
  });

  function toggleSection(key: string) {
    setOpenSections((prev) => ({ ...prev, [key]: !prev[key] }));
  }

  // Load settings
  const loadSettings = useCallback(async () => {
    try {
      const [settingsRes, clusterRes] = await Promise.all([
        adminApi.getSettings(),
        adminApi.getClusterStatus(),
      ]);
      setSettings(settingsRes);
      setCluster(clusterRes);
      setCpuLimit(settingsRes.default_resources.cpu_limit);
      setMemoryLimit(settingsRes.default_resources.memory_limit);
      setError(null);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to load"
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadSettings();
  }, [loadSettings]);

  // Load template when tab changes
  const loadTemplate = useCallback(
    async (type: string) => {
      if (templateContentsRef.current[type] !== undefined) return;
      setTemplateLoading(true);
      try {
        const res = await adminApi.getTemplate(type);
        setTemplateContents((prev) => ({ ...prev, [type]: res.content }));
      } catch {
        showToast(t.errorLoadFailed, "error");
      } finally {
        setTemplateLoading(false);
      }
    },
    [t]
  );

  useEffect(() => {
    loadTemplate(templateTab);
  }, [templateTab, loadTemplate]);

  // ----- Handlers -----

  async function handleChangeKey() {
    if (newKey.length < 8) {
      showToast(t.validationAdminKeyLength, "error");
      return;
    }
    if (newKey !== confirmKey) {
      showToast(t.keyMismatch, "error");
      return;
    }
    setChangingKey(true);
    try {
      await adminApi.changeAdminKey(newKey);
      showToast(t.adminKeyChanged);
      setShowKeyDialog(false);
      setNewKey("");
      setConfirmKey("");
      // Redirect to login after a brief delay
      setTimeout(() => {
        localStorage.removeItem("admin_api_key");
        window.location.href = "/admin/login";
      }, 1500);
    } catch (err) {
      showToast(getApiError(err, t.errorSaveFailed), "error");
    } finally {
      setChangingKey(false);
    }
  }

  async function handleSaveResources() {
    // Validate CPU format
    const cpuRegex = /^\d+(\.\d+)?m?$/;
    if (!cpuRegex.test(cpuLimit)) {
      showToast(t.invalidCpuFormat || "Invalid CPU format (e.g., 250m, 1, 1000m)", "error");
      return;
    }
    // Validate Memory format
    const memRegex = /^\d+(Ki|Mi|Gi|Ti)$/;
    if (!memRegex.test(memoryLimit)) {
      showToast(t.invalidMemoryFormat || "Invalid memory format (e.g., 512Mi, 1Gi)", "error");
      return;
    }

    setSavingResources(true);
    try {
      await adminApi.updateSettings({
        default_resources: {
          cpu_request: cpuLimit,
          cpu_limit: cpuLimit,
          memory_request: memoryLimit,
          memory_limit: memoryLimit,
        },
      });
      showToast(t.settingsSaved);
    } catch (err) {
      showToast(getApiError(err, t.errorSaveFailed), "error");
    } finally {
      setSavingResources(false);
    }
  }

  async function handleSaveTemplate() {
    setTemplateSaving(true);
    try {
      await adminApi.updateTemplate(
        templateTab,
        templateContents[templateTab] || ""
      );
      showToast(t.settingsSaved);
    } catch (err) {
      showToast(getApiError(err, t.errorSaveFailed), "error");
    } finally {
      setTemplateSaving(false);
    }
  }

  // ----- Loading / Error -----
  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <LoadingSpinner />
      </div>
    );
  }

  if (error && !settings) {
    return (
      <div className="flex flex-col items-center justify-center py-20 gap-3">
        <p className="text-sm text-accent-pink">{error}</p>
        <button
          onClick={() => {
            setLoading(true);
            loadSettings();
          }}
          className="h-9 px-4 text-sm border border-accent-cyan text-accent-cyan rounded-lg hover:bg-accent-cyan/10 transition-colors"
        >
          {t.retry}
        </button>
      </div>
    );
  }

  return (
    <div className="animate-page-enter">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-text-primary">
          {t.settingsTitle}
        </h1>
        <p className="text-sm text-text-secondary mt-1">
          {t.settingsSubtitle}
        </p>
      </div>

      <div className="space-y-4">
        {/* Section 1: Cluster Status */}
        {cluster && (
          <SettingsSection
            title={t.clusterStatus}
            open={openSections.cluster}
            onToggle={() => toggleSection("cluster")}
          >
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-surface text-text-secondary text-xs uppercase tracking-wider font-semibold">
                    <th className="py-2.5 px-3 text-left">{t.clusterNodeName}</th>
                    <th className="py-2.5 px-3 text-left">{t.clusterCpuCapacity}</th>
                    <th className="py-2.5 px-3 text-left">{t.clusterMemoryCapacity}</th>
                    <th className="py-2.5 px-3 text-left">{t.clusterCpuUsage}</th>
                    <th className="py-2.5 px-3 text-left">{t.clusterMemoryUsage}</th>
                    <th className="py-2.5 px-3 text-left">{t.clusterDiskTotal}</th>
                    <th className="py-2.5 px-3 text-left">{t.clusterDiskUsed}</th>
                  </tr>
                </thead>
                <tbody className="bg-background">
                  {cluster.nodes.map((node) => (
                    <tr
                      key={node.name}
                      className="border-b border-border-subtle hover:bg-surface/50 transition-colors"
                    >
                      <td className="py-2.5 px-3 font-[family-name:var(--font-mono)] text-xs text-accent-cyan">
                        {node.name}
                      </td>
                      <td className="py-2.5 px-3 font-[family-name:var(--font-mono)] text-text-primary">
                        {node.cpu_capacity}
                      </td>
                      <td className="py-2.5 px-3 font-[family-name:var(--font-mono)] text-text-primary">
                        {node.memory_capacity}
                      </td>
                      <td className="py-2.5 px-3 font-[family-name:var(--font-mono)] text-text-primary">
                        {node.cpu_usage_percent !== null
                          ? `${node.cpu_usage_percent.toFixed(1)}%`
                          : "-"}
                      </td>
                      <td className="py-2.5 px-3 font-[family-name:var(--font-mono)] text-text-primary">
                        {node.memory_usage_percent !== null
                          ? `${node.memory_usage_percent.toFixed(1)}%`
                          : "-"}
                      </td>
                      <td className="py-2.5 px-3 font-[family-name:var(--font-mono)] text-text-primary">
                        {node.disk_total_gb !== null
                          ? `${node.disk_total_gb.toFixed(1)} GB`
                          : "-"}
                      </td>
                      <td className="py-2.5 px-3 font-[family-name:var(--font-mono)] text-text-primary">
                        {node.disk_used_gb !== null
                          ? `${node.disk_used_gb.toFixed(1)} GB`
                          : "-"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="mt-3 text-xs text-text-secondary font-[family-name:var(--font-mono)]">
              {t.agentNamespace}: <span className="text-accent-cyan">{cluster.namespace}</span> | {t.runningAgents}:{" "}
              <span className="text-accent-cyan">{cluster.running_agents}</span>/{cluster.total_agents}
            </div>
          </SettingsSection>
        )}

        {/* Section 2: Admin API Key */}
        {settings && (
          <SettingsSection
            title={t.adminKey}
            open={openSections.adminKey}
            onToggle={() => toggleSection("adminKey")}
          >
            <div className="space-y-3 max-w-lg">
              {/* Current key (masked) */}
              <div>
                <label className="text-xs text-text-secondary mb-1 block">
                  {t.adminKeyMasked}
                </label>
                <input
                  type="text"
                  value={settings.admin_key_masked}
                  readOnly
                  className="h-9 w-full px-3 text-sm bg-background border border-border rounded-lg text-text-primary font-[family-name:var(--font-mono)] opacity-60 cursor-not-allowed"
                />
              </div>

              {/* New key inputs */}
              <div>
                <label className="text-xs text-text-secondary mb-1 block">
                  {t.adminKeyNew}
                </label>
                <input
                  type="password"
                  value={newKey}
                  onChange={(e) => setNewKey(e.target.value)}
                  placeholder={t.adminKeyNewPlaceholder}
                  className="h-9 w-full px-3 text-sm bg-background border border-border rounded-lg text-text-primary font-[family-name:var(--font-mono)] placeholder:text-text-secondary focus:outline-none focus:border-accent-cyan focus:shadow-[0_0_0_2px_rgba(5,217,232,0.15)]"
                />
              </div>
              <div>
                <label className="text-xs text-text-secondary mb-1 block">
                  {t.confirmNewKey}
                </label>
                <input
                  type="password"
                  value={confirmKey}
                  onChange={(e) => setConfirmKey(e.target.value)}
                  placeholder={t.confirmNewKeyPlaceholder}
                  className="h-9 w-full px-3 text-sm bg-background border border-border rounded-lg text-text-primary font-[family-name:var(--font-mono)] placeholder:text-text-secondary focus:outline-none focus:border-accent-cyan focus:shadow-[0_0_0_2px_rgba(5,217,232,0.15)]"
                />
              </div>
              <button
                onClick={() => setShowKeyDialog(true)}
                disabled={!newKey || !confirmKey || newKey !== confirmKey}
                className="h-9 px-4 text-sm rounded-lg bg-accent-pink text-white hover:shadow-[0_0_15px_rgba(255,42,109,0.2)] transition-shadow disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {t.changeAdminKey}
              </button>
            </div>
          </SettingsSection>
        )}

        {/* Section 3: Default Resource Limits */}
        <SettingsSection
          title={t.defaultResources}
          open={openSections.resources}
          onToggle={() => toggleSection("resources")}
        >
          <div className="space-y-3 max-w-lg">
            <div>
              <label className="text-xs text-text-secondary mb-1 block">
                {t.cpuLimit}
              </label>
              <input
                type="text"
                value={cpuLimit}
                onChange={(e) => setCpuLimit(e.target.value)}
                className="h-9 w-full px-3 text-sm bg-background border border-border rounded-lg text-text-primary font-[family-name:var(--font-mono)] placeholder:text-text-secondary focus:outline-none focus:border-accent-cyan focus:shadow-[0_0_0_2px_rgba(5,217,232,0.15)]"
                placeholder="1000m"
              />
            </div>
            <div>
              <label className="text-xs text-text-secondary mb-1 block">
                {t.memoryLimit}
              </label>
              <input
                type="text"
                value={memoryLimit}
                onChange={(e) => setMemoryLimit(e.target.value)}
                className="h-9 w-full px-3 text-sm bg-background border border-border rounded-lg text-text-primary font-[family-name:var(--font-mono)] placeholder:text-text-secondary focus:outline-none focus:border-accent-cyan focus:shadow-[0_0_0_2px_rgba(5,217,232,0.15)]"
                placeholder="1Gi"
              />
            </div>
            <button
              onClick={handleSaveResources}
              disabled={savingResources}
              className="h-9 px-4 text-sm rounded-lg bg-accent-pink text-white hover:shadow-[0_0_15px_rgba(255,42,109,0.2)] transition-shadow disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {savingResources ? "..." : t.save}
            </button>
          </div>
        </SettingsSection>

        {/* Section 4: Template Editor */}
        <SettingsSection
          title={t.templateManagement}
          open={openSections.templates}
          onToggle={() => toggleSection("templates")}
        >
          {/* Sub-tabs — underline style */}
          <div className="flex gap-1 border-b border-border-subtle mb-4 overflow-x-auto">
            {TEMPLATE_TABS.map((tab) => {
              const isActive = templateTab === tab.type;
              return (
                <button
                  key={tab.type}
                  onClick={() => setTemplateTab(tab.type)}
                  className={`
                    relative px-3 py-2 text-sm font-medium whitespace-nowrap transition-colors
                    ${isActive
                      ? "text-accent-pink"
                      : "text-text-secondary hover:text-text-primary"
                    }
                  `}
                >
                  {t[tab.labelKey]}
                  {isActive && (
                    <span className="absolute bottom-0 left-0 right-0 h-[3px] bg-accent-pink rounded-t" />
                  )}
                </button>
              );
            })}
          </div>

          {/* Template content */}
          {templateLoading ? (
            <div className="flex items-center gap-2 py-4">
              <LoadingSpinner size="sm" />
              <span className="text-sm text-text-secondary">
                {t.loading}
              </span>
            </div>
          ) : (
            <div>
              <textarea
                value={templateContents[templateTab] ?? ""}
                onChange={(e) =>
                  setTemplateContents((prev) => ({
                    ...prev,
                    [templateTab]: e.target.value,
                  }))
                }
                className="w-full h-[400px] p-4 text-sm bg-background border border-border rounded-lg font-[family-name:var(--font-mono)] text-text-primary resize-y focus:outline-none focus:border-accent-cyan"
                spellCheck={false}
              />
              <div className="mt-3">
                <button
                  onClick={handleSaveTemplate}
                  disabled={templateSaving}
                  className="h-9 px-4 text-sm rounded-lg bg-accent-pink text-white hover:shadow-[0_0_15px_rgba(255,42,109,0.2)] transition-shadow disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {templateSaving ? "..." : t.save}
                </button>
              </div>
            </div>
          )}
        </SettingsSection>
      </div>

      {/* Confirm dialog for admin key change */}
      <ConfirmDialog
        open={showKeyDialog}
        title={t.changeAdminKey}
        message={t.confirmKeyChange}
        confirmLabel={t.confirm}
        cancelLabel={t.cancel}
        variant="destructive"
        loading={changingKey}
        onConfirm={handleChangeKey}
        onCancel={() => setShowKeyDialog(false)}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Settings section wrapper — collapsible cyberpunk panels
// ---------------------------------------------------------------------------

function SettingsSection({
  title,
  open = true,
  onToggle,
  children,
}: {
  title: string;
  open?: boolean;
  onToggle?: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="bg-surface rounded-lg border border-border overflow-hidden">
      {/* Header bar */}
      <button
        type="button"
        onClick={onToggle}
        className="w-full bg-surface px-4 py-3 flex items-center justify-between cursor-pointer border-l-[3px] border-l-accent-cyan hover:bg-surface-elevated/30 transition-colors"
      >
        <h2 className="text-sm font-semibold text-text-primary text-left">
          {title}
        </h2>
        <svg
          className={`w-4 h-4 text-text-secondary transition-transform duration-200 ${
            open ? "rotate-180" : "rotate-0"
          }`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
          aria-hidden="true"
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {/* Content — collapsible */}
      <div
        className={`transition-all duration-200 ease-in-out ${
          open
            ? "max-h-[2000px] opacity-100"
            : "max-h-0 opacity-0 overflow-hidden"
        }`}
      >
        <div className="px-4 pb-4 pt-2">{children}</div>
      </div>
    </div>
  );
}
