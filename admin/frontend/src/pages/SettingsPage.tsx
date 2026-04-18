import { useState, useEffect, useCallback } from "react";
import type {
  AdminSettings,
  ClusterStatus,
} from "../lib/admin-api";
import { adminApi, AdminApiError } from "../lib/admin-api";
import { useI18n } from "../hooks/useI18n";
import { ConfirmDialog } from "../components/ConfirmDialog";

// ---------------------------------------------------------------------------
// Toast helper
// ---------------------------------------------------------------------------

function toast(msg: string, variant: "default" | "error" = "default") {
  const el = document.createElement("div");
  el.className =
    "fixed bottom-4 right-4 z-50 rounded-md border px-4 py-2 text-sm shadow-lg transition-opacity " +
    (variant === "error"
      ? "border-red-300 bg-red-50 text-red-700"
      : "border-border bg-card");
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => {
    el.style.opacity = "0";
    setTimeout(() => el.remove(), 300);
  }, 3000);
}

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
  const [templateLoading, setTemplateLoading] = useState(false);
  const [templateSaving, setTemplateSaving] = useState(false);

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
        err instanceof Error ? err.message : t.errorLoadFailed
      );
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    loadSettings();
  }, [loadSettings]);

  // Load template when tab changes
  const loadTemplate = useCallback(
    async (type: string) => {
      if (templateContents[type] !== undefined) return;
      setTemplateLoading(true);
      try {
        const res = await adminApi.getTemplate(type);
        setTemplateContents((prev) => ({ ...prev, [type]: res.content }));
      } catch {
        toast(t.errorLoadFailed, "error");
      } finally {
        setTemplateLoading(false);
      }
    },
    [templateContents, t]
  );

  useEffect(() => {
    loadTemplate(templateTab);
  }, [templateTab, loadTemplate]);

  // ----- Handlers -----

  async function handleChangeKey() {
    if (newKey.length < 8) {
      toast("密钥至少需要8个字符", "error");
      return;
    }
    if (newKey !== confirmKey) {
      toast("两次输入的密钥不一致", "error");
      return;
    }
    setChangingKey(true);
    try {
      await adminApi.changeAdminKey(newKey);
      toast("Admin Key 已更改，请使用新密钥重新登录");
      setShowKeyDialog(false);
      setNewKey("");
      setConfirmKey("");
      // Redirect to login after a brief delay
      setTimeout(() => {
        localStorage.removeItem("admin_api_key");
        window.location.href = "/admin/login";
      }, 1500);
    } catch (err) {
      toast(
        err instanceof AdminApiError ? err.detail : t.errorSaveFailed,
        "error"
      );
    } finally {
      setChangingKey(false);
    }
  }

  async function handleSaveResources() {
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
      toast("默认资源配置已保存");
    } catch (err) {
      toast(
        err instanceof AdminApiError ? err.detail : t.errorSaveFailed,
        "error"
      );
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
      toast("模板已保存");
    } catch (err) {
      toast(
        err instanceof AdminApiError ? err.detail : t.errorSaveFailed,
        "error"
      );
    } finally {
      setTemplateSaving(false);
    }
  }

  // ----- Loading / Error -----
  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-primary border-t-transparent" />
      </div>
    );
  }

  if (error && !settings) {
    return (
      <div className="flex flex-col items-center justify-center py-20 gap-3">
        <p className="text-sm text-destructive">{error}</p>
        <button
          onClick={() => {
            setLoading(true);
            loadSettings();
          }}
          className="h-9 px-4 text-sm border border-border hover:bg-accent rounded"
        >
          {t.retry}
        </button>
      </div>
    );
  }

  return (
    <div>
      {/* Header */}
      <div className="mb-6">
        <h1 className="text-2xl font-bold">{t.settingsTitle}</h1>
        <p className="text-sm text-muted-foreground">
          {t.settingsSubtitle}
        </p>
      </div>

      <div className="space-y-6">
        {/* Section 1: Cluster Status */}
        {cluster && (
          <SettingsSection title={t.clusterStatus}>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-xs text-muted-foreground">
                    <th className="py-2 px-3">{t.clusterNodeName}</th>
                    <th className="py-2 px-3">{t.clusterCpuCapacity}</th>
                    <th className="py-2 px-3">{t.clusterMemoryCapacity}</th>
                    <th className="py-2 px-3">{t.clusterCpuUsage}</th>
                    <th className="py-2 px-3">{t.clusterMemoryUsage}</th>
                    <th className="py-2 px-3">{t.clusterDiskTotal}</th>
                    <th className="py-2 px-3">{t.clusterDiskUsed}</th>
                  </tr>
                </thead>
                <tbody>
                  {cluster.nodes.map((node) => (
                    <tr
                      key={node.name}
                      className="border-b border-border/50"
                    >
                      <td className="py-2 px-3 font-mono text-xs">
                        {node.name}
                      </td>
                      <td className="py-2 px-3">{node.cpu_capacity}</td>
                      <td className="py-2 px-3">{node.memory_capacity}</td>
                      <td className="py-2 px-3">
                        {node.cpu_usage_percent !== null
                          ? `${node.cpu_usage_percent.toFixed(1)}%`
                          : "-"}
                      </td>
                      <td className="py-2 px-3">
                        {node.memory_usage_percent !== null
                          ? `${node.memory_usage_percent.toFixed(1)}%`
                          : "-"}
                      </td>
                      <td className="py-2 px-3">
                        {node.disk_total_gb !== null
                          ? `${node.disk_total_gb.toFixed(1)} GB`
                          : "-"}
                      </td>
                      <td className="py-2 px-3">
                        {node.disk_used_gb !== null
                          ? `${node.disk_used_gb.toFixed(1)} GB`
                          : "-"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="mt-3 text-xs text-muted-foreground">
              Namespace: {cluster.namespace} | Agents:{" "}
              {cluster.running_agents}/{cluster.total_agents} running
            </div>
          </SettingsSection>
        )}

        {/* Section 2: Admin API Key */}
        {settings && (
          <SettingsSection title={t.adminKey}>
            <div className="space-y-3 max-w-lg">
              {/* Current key (masked) */}
              <div>
                <label className="block text-xs text-muted-foreground mb-1">
                  {t.adminKeyMasked}
                </label>
                <input
                  type="text"
                  value={settings.admin_key_masked}
                  readOnly
                  className="h-9 w-full px-3 text-sm border border-border rounded bg-muted font-mono"
                />
              </div>

              {/* New key inputs */}
              <div>
                <label className="block text-xs text-muted-foreground mb-1">
                  {t.adminKeyNew}
                </label>
                <input
                  type="password"
                  value={newKey}
                  onChange={(e) => setNewKey(e.target.value)}
                  placeholder={t.adminKeyNewPlaceholder}
                  className="h-9 w-full px-3 text-sm border border-border rounded font-mono"
                />
              </div>
              <div>
                <label className="block text-xs text-muted-foreground mb-1">
                  确认新密钥
                </label>
                <input
                  type="password"
                  value={confirmKey}
                  onChange={(e) => setConfirmKey(e.target.value)}
                  placeholder="再次输入新密钥"
                  className="h-9 w-full px-3 text-sm border border-border rounded font-mono"
                />
              </div>
              <button
                onClick={() => setShowKeyDialog(true)}
                disabled={!newKey || !confirmKey || newKey !== confirmKey}
                className="h-9 px-4 text-sm rounded bg-destructive text-white hover:bg-destructive/90 disabled:opacity-50"
              >
                {t.changeAdminKey}
              </button>
            </div>
          </SettingsSection>
        )}

        {/* Section 3: Default Resource Limits */}
        <SettingsSection title={t.defaultResources}>
          <div className="space-y-3 max-w-lg">
            <div>
              <label className="block text-xs text-muted-foreground mb-1">
                {t.cpuLimit}
              </label>
              <input
                type="text"
                value={cpuLimit}
                onChange={(e) => setCpuLimit(e.target.value)}
                className="h-9 w-full px-3 text-sm border border-border rounded font-mono"
                placeholder="1000m"
              />
            </div>
            <div>
              <label className="block text-xs text-muted-foreground mb-1">
                {t.memoryLimit}
              </label>
              <input
                type="text"
                value={memoryLimit}
                onChange={(e) => setMemoryLimit(e.target.value)}
                className="h-9 w-full px-3 text-sm border border-border rounded font-mono"
                placeholder="1Gi"
              />
            </div>
            <button
              onClick={handleSaveResources}
              disabled={savingResources}
              className="h-9 px-4 text-sm rounded bg-primary text-white hover:bg-primary/90 disabled:opacity-50"
            >
              {savingResources ? "..." : t.save}
            </button>
          </div>
        </SettingsSection>

        {/* Section 4: Template Editor */}
        <SettingsSection title={t.templateManagement}>
          {/* Sub-tabs */}
          <div className="flex gap-1 mb-4">
            {TEMPLATE_TABS.map((tab) => (
              <button
                key={tab.type}
                onClick={() => setTemplateTab(tab.type)}
                className={`px-3 py-1.5 text-sm rounded ${
                  templateTab === tab.type
                    ? "bg-primary text-white"
                    : "border border-border hover:bg-accent"
                }`}
              >
                {t[tab.labelKey]}
              </button>
            ))}
          </div>

          {/* Template content */}
          {templateLoading ? (
            <div className="flex items-center gap-2 py-4">
              <div className="h-4 w-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />
              <span className="text-sm text-muted-foreground">
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
                className="w-full h-[400px] p-3 text-sm border border-border rounded font-mono bg-muted resize-y"
                spellCheck={false}
              />
              <div className="mt-3">
                <button
                  onClick={handleSaveTemplate}
                  disabled={templateSaving}
                  className="h-9 px-4 text-sm rounded bg-primary text-white hover:bg-primary/90 disabled:opacity-50"
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
        message="更改 Admin Key 后需要使用新密钥重新验证。确定继续？"
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
// Settings section wrapper
// ---------------------------------------------------------------------------

function SettingsSection({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <h2 className="text-sm font-semibold mb-3">{title}</h2>
      {children}
    </div>
  );
}
