import { useI18n } from "../hooks/useI18n";

export interface RedisHealth {
  connected: boolean;
  latency_ms: number;
  memory_used_percent: number;
  connected_clients: number;
  uptime_seconds: number;
  aof_enabled: boolean;
  version: string;
}

interface RedisHealthCardProps {
  health: RedisHealth;
}

export function RedisHealthCard({ health }: RedisHealthCardProps) {
  const { t } = useI18n();
  const statusColor = health.connected ? "text-green-500" : "text-red-400";

  return (
    <div className="rounded-lg border border-border bg-surface p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-medium text-text-primary">{t.redisLabel}</h3>
        <span
          className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded ${
            health.connected
              ? "bg-success/10 text-success"
              : "bg-red-500/10 text-red-400"
          }`}
        >
          <span
            className={`inline-block h-1.5 w-1.5 rounded-full ${
              health.connected ? "bg-success" : "bg-red-400"
            }`}
          />
          <span className={statusColor}>
            {health.connected ? t.swarmConnected : t.swarmDisconnected}
          </span>
        </span>
      </div>
      {health.connected && (
        <div className="space-y-1.5 text-xs">
          <div className="flex justify-between">
            <span className="text-text-secondary">{t.latency}</span>
            <span className="font-[family-name:var(--font-mono)] text-text-primary">
              {health.latency_ms.toFixed(1)} ms
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-text-secondary">{t.memory}</span>
            <span className="font-[family-name:var(--font-mono)] text-text-primary">
              {health.memory_used_percent.toFixed(1)}%
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-text-secondary">{t.clients}</span>
            <span className="font-[family-name:var(--font-mono)] text-text-primary">
              {health.connected_clients}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-text-secondary">{t.version}</span>
            <span className="font-[family-name:var(--font-mono)] text-text-primary">
              {health.version}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
