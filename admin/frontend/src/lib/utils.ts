/**
 * Shared utility functions for the Hermes Admin Panel frontend.
 * Extracted from AgentCard, AgentDetailPage, and ClusterStatusBar.
 */

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null) return "-";
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)}K`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(0)}M`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(1)}Gi`;
}

export function formatMillicores(cores: number | null | undefined): string {
  if (cores == null) return "-";
  const mc = cores * 1000;
  if (mc >= 1000) return `${(mc / 1000).toFixed(1)}`;
  return `${Math.round(mc)}m`;
}

export function getBarColor(percent: number): string {
  if (percent >= 90) return "bg-accent-pink";
  if (percent >= 70) return "bg-warning";
  return "bg-accent-cyan";
}

export function statusDotColor(status: string): string {
  switch (status) {
    case "running":
      return "bg-success";
    case "stopped":
      return "bg-text-secondary";
    case "failed":
      return "bg-accent-pink";
    case "pending":
    case "updating":
    case "scaling":
    case "starting":
      return "bg-warning";
    default:
      return "bg-text-secondary";
  }
}

export function statusLabel(status: string, t: any): string {
  const map: Record<string, string> = {
    running: t.statusRunning,
    stopped: t.statusStopped,
    failed: t.statusFailed,
    starting: t.statusPending,
    pending: t.statusPending,
    updating: t.statusUpdating,
    scaling: t.statusScaling,
    unknown: t.statusUnknown,
  };
  return map[status] || t.statusUnknown;
}

export const STATUS_PRIORITY: Record<string, number> = {
  failed: 0,
  starting: 1,
  stopped: 2,
  running: 3,
  unknown: 4,
};

export function statusOrder(status: string): number {
  return STATUS_PRIORITY[status] ?? 5;
}
