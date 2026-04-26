import type { TaskStatus } from "../stores/swarmTasks";

export function statusBadgeClasses(status: TaskStatus): string {
  switch (status) {
    case "completed":
      return "bg-success/10 text-success border-success/20";
    case "failed":
      return "bg-accent-pink/10 text-accent-pink border-accent-pink/20";
    case "running":
      return "bg-accent-cyan/10 text-accent-cyan border-accent-cyan/20";
    case "pending":
      return "bg-warning/10 text-warning border-warning/20";
    default:
      return "bg-text-secondary/10 text-text-secondary border-text-secondary/20";
  }
}

export function statusDotColor(status: TaskStatus): string {
  switch (status) {
    case "completed":
      return "bg-success";
    case "failed":
      return "bg-accent-pink";
    case "running":
      return "bg-accent-cyan";
    case "pending":
      return "bg-warning";
    default:
      return "bg-text-secondary";
  }
}

export function statusDotPulse(status: TaskStatus): string {
  return status === "running" ? "animate-status-pulse" : "";
}

export function formatDuration(ms: number | null): string {
  if (ms === null) return "-";
  if (ms < 1000) return `${ms}ms`;
  const seconds = Math.floor(ms / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const remaining = seconds % 60;
  return `${minutes}m ${remaining}s`;
}

export function formatTimestamp(epoch: number, detailed = false): string {
  const date = new Date(epoch * 1000);
  if (detailed) {
    return date.toLocaleString([], {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  }
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export function truncateId(id: string, threshold = 12): string {
  if (id.length <= threshold) return id;
  return `${id.slice(0, 8)}...${id.slice(-4)}`;
}
