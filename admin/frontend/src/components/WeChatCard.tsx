import { useState, useEffect, useCallback } from "react";
import type { WeixinStatus } from "../lib/admin-api";
import { adminApi } from "../lib/admin-api";
import { useI18n } from "../hooks/useI18n";
import { ConfirmDialog } from "./ConfirmDialog";
import { showToast } from "../lib/toast";
import { getApiError } from "../lib/utils";

interface WeChatCardProps {
  agentId: number;
  agentRunning: boolean;
  onRegister: () => void;
  onRefresh: () => void;
}

export function WeChatCard({ agentId, agentRunning, onRegister, onRefresh }: WeChatCardProps) {
  const { t } = useI18n();
  const [status, setStatus] = useState<WeixinStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [unbinding, setUnbinding] = useState(false);
  const [showUnbindDialog, setShowUnbindDialog] = useState(false);

  const loadStatus = useCallback(async () => {
    try {
      const res = await adminApi.getWeixinStatus(agentId);
      setStatus(res);
    } catch {
      // API unavailable — show "not connected" instead of skeleton
      setStatus({ agent_number: agentId, connected: false, account_id: "", user_id: "", base_url: "", dm_policy: "", group_policy: "", bound_at: null });
    } finally {
      setLoading(false);
    }
  }, [agentId]);

  useEffect(() => {
    loadStatus();
  }, [loadStatus]);

  async function handleUnbind() {
    setShowUnbindDialog(false);
    setUnbinding(true);
    try {
      await adminApi.unbindWeixin(agentId);
      showToast(t.weixinUnbound || "WeChat unbound");
      await loadStatus();
      onRefresh();
    } catch (err) {
      showToast(getApiError(err, t.errorGeneric), "error");
    } finally {
      setUnbinding(false);
    }
  }

  if (loading || !status) {
    return (
      <div className="rounded-lg border border-border bg-surface p-4">
        <h3 className="text-sm font-medium text-text-primary mb-2">
          {t.weixinConnection || "WeChat Connection"}
        </h3>
        <div className="h-4 w-24 bg-bar-track rounded animate-pulse" />
      </div>
    );
  }

  const connected = status.connected;

  return (
    <div className="rounded-lg border border-border bg-surface p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-medium text-text-primary">
          {t.weixinConnection || "WeChat Connection"}
        </h3>
        <span className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded ${
          connected
            ? "bg-success/10 text-success"
            : "bg-text-secondary/10 text-text-secondary"
        }`}>
          <span className={`inline-block h-1.5 w-1.5 rounded-full ${connected ? "bg-success" : "bg-text-secondary"}`} />
          {connected ? (t.statusRunning || "Connected") : (t.weixinNotConnected || "Not Connected")}
        </span>
      </div>

      {connected ? (
        <div className="space-y-2">
          <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
            <div>
              <span className="text-text-secondary">{t.weixinAccount || "Account"}:</span>{" "}
              <span className="font-[family-name:var(--font-mono)] text-text-primary">
                {status.account_id.length > 12
                  ? status.account_id.slice(0, 8) + "..." + status.account_id.slice(-4)
                  : status.account_id}
              </span>
            </div>
            <div>
              <span className="text-text-secondary">{t.weixinBoundAt || "Bound"}:</span>{" "}
              <span className="text-text-primary">
                {status.bound_at ? new Date(status.bound_at).toLocaleString() : "-"}
              </span>
            </div>
            <div>
              <span className="text-text-secondary">DM:</span>{" "}
              <span className="text-text-primary">{status.dm_policy}</span>
            </div>
            <div>
              <span className="text-text-secondary">{t.weixinGroups || "Groups"}:</span>{" "}
              <span className="text-text-primary">{status.group_policy}</span>
            </div>
          </div>
          <div className="flex gap-2 pt-1">
            <button
              onClick={onRegister}
              disabled={!agentRunning}
              className="h-8 px-3 text-xs border border-accent-cyan text-accent-cyan hover:bg-accent-cyan/10 rounded transition-colors disabled:opacity-50"
            >
              {t.weixinReregister || "Re-register"}
            </button>
            <button
              onClick={() => setShowUnbindDialog(true)}
              disabled={unbinding}
              className="h-8 px-3 text-xs border border-accent-pink text-accent-pink hover:bg-accent-pink/10 rounded transition-colors disabled:opacity-50"
            >
              {t.weixinUnbind || "Unbind"}
            </button>
          </div>
        </div>
      ) : (
        <div className="flex flex-col items-center gap-3 py-2">
          <p className="text-xs text-text-secondary">
            {t.weixinNotConnectedDesc || "Not connected to WeChat"}
          </p>
          <button
            onClick={onRegister}
            disabled={!agentRunning}
            className="h-9 px-4 text-sm rounded-lg bg-accent-cyan text-background hover:shadow-[0_0_15px_rgba(5,217,232,0.3)] transition-shadow disabled:opacity-50"
          >
            {t.weixinRegister || "Register WeChat"}
          </button>
        </div>
      )}

      <ConfirmDialog
        open={showUnbindDialog}
        title={t.weixinUnbind || "Unbind WeChat"}
        message={t.weixinUnbindConfirm || "Are you sure you want to unbind WeChat? The agent will restart."}
        confirmLabel={t.weixinUnbind || "Unbind"}
        cancelLabel={t.cancel}
        variant="destructive"
        loading={unbinding}
        onConfirm={handleUnbind}
        onCancel={() => setShowUnbindDialog(false)}
      />
    </div>
  );
}
