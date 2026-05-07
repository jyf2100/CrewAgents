/**
 * Shared badge components for the Orchestrator UI.
 *
 * Typed props prevent accidental misspelling of status / role / circuit values.
 */

import type { OrchestratorAgent, OrchestratorTask } from "../lib/admin-api";

// ---------------------------------------------------------------------------
// Task status badge
// ---------------------------------------------------------------------------

type TaskStatus = OrchestratorTask["status"];

const TASK_STATUS_COLORS: Record<TaskStatus, string> = {
  done: "bg-green-500/20 text-green-400",
  failed: "bg-red-500/20 text-red-400",
  executing: "bg-blue-500/20 text-blue-400",
  streaming: "bg-blue-500/20 text-blue-400",
  queued: "bg-gray-500/20 text-gray-400",
  assigned: "bg-gray-500/20 text-gray-400",
  submitted: "bg-gray-500/20 text-gray-400",
};

export function TaskStatusBadge({ status }: { status: TaskStatus }) {
  return (
    <span
      className={`px-2 py-0.5 rounded text-xs font-medium ${
        TASK_STATUS_COLORS[status] ?? "bg-gray-500/20 text-gray-400"
      }`}
    >
      {status}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Agent status badge
// ---------------------------------------------------------------------------

type AgentStatus = OrchestratorAgent["status"];

const AGENT_STATUS_COLORS: Record<AgentStatus, string> = {
  online: "bg-green-500/20 text-green-400",
  degraded: "bg-yellow-500/20 text-yellow-400",
  offline: "bg-red-500/20 text-red-400",
};

export function AgentStatusBadge({ status }: { status: AgentStatus }) {
  return (
    <span
      className={`px-2 py-0.5 rounded text-xs font-medium ${
        AGENT_STATUS_COLORS[status] ?? "bg-gray-500/20 text-gray-400"
      }`}
    >
      {status}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Role badge
// ---------------------------------------------------------------------------

type AgentRole = OrchestratorAgent["role"];

const ROLE_COLORS: Record<string, string> = {
  coder: "bg-blue-500/15 text-blue-400 border-blue-500/30",
  analyst: "bg-purple-500/15 text-purple-400 border-purple-500/30",
  generalist: "bg-gray-500/15 text-gray-400 border-gray-500/30",
};

export function RoleBadge({ role }: { role: AgentRole }) {
  const displayRole = role ?? "generalist";
  const colorClass =
    ROLE_COLORS[displayRole] ?? "bg-gray-500/15 text-gray-400 border-gray-500/30";
  return (
    <span
      className={`px-2 py-0.5 rounded-full text-[10px] font-medium border ${colorClass}`}
    >
      {displayRole}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Circuit badge
// ---------------------------------------------------------------------------

type CircuitState = OrchestratorAgent["circuit_state"];

const CIRCUIT_COLORS: Record<CircuitState, string> = {
  closed: "bg-green-500",
  open: "bg-red-500",
  half_open: "bg-yellow-500",
};

export function CircuitBadge({ state }: { state: CircuitState }) {
  return (
    <span
      className={`inline-block w-2.5 h-2.5 rounded-full ${
        CIRCUIT_COLORS[state] ?? "bg-gray-500"
      }`}
      title={state}
    />
  );
}
