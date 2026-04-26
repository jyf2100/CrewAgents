import type { ClusterStatus } from "../lib/admin-api";
import { useI18n } from "../hooks/useI18n";
import { getBarColor } from "../lib/utils";

interface ClusterStatusBarProps {
  cluster: ClusterStatus;
}

export function ClusterStatusBar({ cluster }: ClusterStatusBarProps) {
  const { t } = useI18n();

  // Use the first node for display (single-node cluster typical for Hermes)
  const node = cluster.nodes[0];
  const nodeName = node?.name ?? "-";
  const cpuPct = node?.cpu_usage_percent ?? 0;
  const memPct = node?.memory_usage_percent ?? 0;
  const diskTotal = node?.disk_total_gb ?? 0;
  const diskUsed = node?.disk_used_gb ?? 0;
  const diskPct = diskTotal > 0 ? Math.round((diskUsed / diskTotal) * 100) : 0;

  return (
    <div className="rounded-lg border border-border bg-card p-4 mb-6">
      <div className="flex flex-wrap items-center gap-6">
        {/* Cluster name */}
        <div className="flex-shrink-0">
          <span className="text-xs text-muted-foreground">{t.clusterStatus}</span>
          <p className="text-sm font-semibold">{nodeName}</p>
        </div>

        {/* CPU bar */}
        <div className="flex-1 min-w-[140px]">
          <div className="flex items-center justify-between text-xs text-muted-foreground mb-1">
            <span>{t.clusterCpuUsage}</span>
            <span>{cpuPct}%</span>
          </div>
          <div className="h-2 rounded-full bg-muted overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${getBarColor(cpuPct)}`}
              style={{ width: `${cpuPct}%` }}
            />
          </div>
        </div>

        {/* Memory bar */}
        <div className="flex-1 min-w-[140px]">
          <div className="flex items-center justify-between text-xs text-muted-foreground mb-1">
            <span>{t.clusterMemoryUsage}</span>
            <span>{memPct}%</span>
          </div>
          <div className="h-2 rounded-full bg-muted overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${getBarColor(memPct)}`}
              style={{ width: `${memPct}%` }}
            />
          </div>
        </div>

        {/* Disk bar */}
        <div className="flex-1 min-w-[140px]">
          <div className="flex items-center justify-between text-xs text-muted-foreground mb-1">
            <span>{t.clusterDiskUsed}</span>
            <span>{diskPct}%</span>
          </div>
          <div className="h-2 rounded-full bg-muted overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${getBarColor(diskPct)}`}
              style={{ width: `${diskPct}%` }}
            />
          </div>
        </div>

        {/* Agent count */}
        <div className="flex-shrink-0 text-center">
          <span className="text-xs text-muted-foreground">{t.totalAgents}</span>
          <p className="text-sm font-semibold">
            <span className="text-green-500">{cluster.running_agents}</span>
            <span className="text-muted-foreground"> / </span>
            <span>{cluster.total_agents}</span>
          </p>
        </div>
      </div>
    </div>
  );
}
