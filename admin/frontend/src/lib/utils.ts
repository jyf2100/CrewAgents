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
  if (percent >= 90) return "bg-red-500";
  if (percent >= 70) return "bg-yellow-500";
  return "bg-green-500";
}

export function statusDotColor(status: string): string {
  switch (status) {
    case "running":
      return "bg-green-500";
    case "stopped":
      return "bg-gray-400";
    case "failed":
      return "bg-red-500";
    case "pending":
    case "updating":
    case "scaling":
    case "starting":
      return "bg-yellow-500";
    default:
      return "bg-gray-400";
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
