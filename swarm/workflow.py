"""Workflow execution engine — sequential, parallel, DAG modes."""
from __future__ import annotations

import json
import logging
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any

from swarm.crew_store import WorkflowDef, WorkflowStep

logger = logging.getLogger(__name__)

# Sentinel sender_id for Admin orchestrator (not a registered agent).
_ADMIN_SENDER_ID = 0

# Use uuid.uuid4 but allow patching via module-level reference
uuid4 = uuid.uuid4

# Dunder-key pattern — reject SSTI-style __xxx__ lookups in format strings.
_DUNDER_RE = re.compile(r"__\w+__")


# ---------------------------------------------------------------------------
# _SafeFormat — safe variable replacement without Jinja2
# ---------------------------------------------------------------------------

class _Namespace:
    """Lightweight namespace that supports attribute access for .output patterns."""
    __slots__ = ("output",)

    def __init__(self, output: str) -> None:
        self.output = output

    def __str__(self) -> str:
        return self.output


class _SafeFormat:
    """Format strings using str.format_map with safe missing-key handling.

    Known keys (step IDs from the workflow) are resolved normally.
    Unknown brace expressions are preserved verbatim (no KeyError).
    Step output containing ``{`` / ``}`` is pre-escaped to ``{{`` / ``}}``.
    Dunder patterns (``__xxx__``) are rejected to prevent SSTI.
    """

    def format(self, template: str, **kwargs: Any) -> str:
        # Build namespace objects from step results so {step_1.output} works
        safe_kwargs: dict[str, _Namespace] = {}
        for k, v in kwargs.items():
            text = getattr(v, "output", str(v))
            # Escape braces in output to avoid double-interpretation
            safe_text = text.replace("{", "{{").replace("}", "}}")
            safe_kwargs[k] = _Namespace(safe_text)

        class _SafeDict(dict):
            def __missing__(self, key: str) -> str:
                if _DUNDER_RE.search(key):
                    return f"{{INVALID:{key}}}"
                return f"{{{key}}}"

        return template.format_map(_SafeDict(safe_kwargs))


# ---------------------------------------------------------------------------
# Topological sort (Kahn's algorithm)
# ---------------------------------------------------------------------------

def _topological_sort(steps: list[dict]) -> list[list[str]]:
    """Return layers of step IDs for concurrent DAG execution.

    Each inner list contains step IDs that can run in parallel.
    Raises ``ValueError`` if a cycle is detected.
    """
    if not steps:
        return []

    in_degree: dict[str, int] = {s["id"]: 0 for s in steps}
    adjacency: dict[str, list[str]] = {s["id"]: [] for s in steps}
    for s in steps:
        for dep in s.get("depends_on", []):
            if dep in adjacency:
                adjacency[dep].append(s["id"])
                in_degree[s["id"]] += 1

    queue = [sid for sid, deg in in_degree.items() if deg == 0]
    layers: list[list[str]] = []
    visited = 0

    while queue:
        layers.append(list(queue))
        next_queue: list[str] = []
        for sid in queue:
            for neighbor in adjacency[sid]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    next_queue.append(neighbor)
            visited += 1
        queue = next_queue

    if visited != len(steps):
        raise ValueError("Circular dependency detected in workflow DAG")

    return layers


# ---------------------------------------------------------------------------
# Execution data models
# ---------------------------------------------------------------------------

@dataclass
class StepResult:
    step_id: str
    status: str  # "completed" | "failed"
    output: str | None = None
    error: str | None = None
    agent_id: int | None = None
    duration_ms: int = 0


@dataclass
class CrewExecution:
    exec_id: str
    crew_id: str = ""
    status: str = "pending"  # "pending" | "running" | "completed" | "failed"
    step_results: dict[str, StepResult] = field(default_factory=dict)
    error: str | None = None
    started_at: float = 0.0
    finished_at: float | None = None
    timeout_seconds: int = 300
    _deadline: float = 0.0  # monotonic deadline for timeout check


# ---------------------------------------------------------------------------
# WorkflowEngine
# ---------------------------------------------------------------------------

class WorkflowEngine:
    """Executes workflow steps by routing tasks through Redis Streams."""

    def __init__(self, redis_client: Any, router: Any, messaging: Any) -> None:
        self._redis = redis_client
        self._router = router
        self._messaging = messaging
        self._formatter = _SafeFormat()
        self._result_lock = threading.Lock()

    def execute(self, workflow: WorkflowDef, crew_id: str = "",
                workflow_timeout: int | None = None) -> CrewExecution:
        timeout = workflow_timeout or workflow.timeout_seconds
        execution = CrewExecution(
            exec_id=str(uuid4()),
            crew_id=crew_id,
            status="running",
            started_at=time.time(),
            timeout_seconds=timeout,
            _deadline=time.monotonic() + timeout,
        )

        if workflow.type == "sequential":
            self._run_sequential(workflow, execution)
        elif workflow.type == "parallel":
            self._run_parallel(workflow, execution)
        elif workflow.type == "dag":
            self._run_dag(workflow, execution)

        if execution.status == "running":
            execution.status = "completed"
        execution.finished_at = time.time()
        return execution

    def _check_timeout(self, execution: CrewExecution) -> bool:
        return time.monotonic() > execution._deadline

    def _execute_step(
        self, step: WorkflowStep, results: dict[str, StepResult],
    ) -> StepResult:
        agent_id = self._router.find_agent(step.required_capability)
        if agent_id is None:
            return StepResult(
                step_id=step.id, status="failed",
                error=f"No agent available for capability: {step.required_capability}",
            )

        # Build goal from template
        goal = self._formatter.format(step.task_template, **results)

        task_id = str(uuid4())
        deadline = time.monotonic() + step.timeout_seconds

        try:
            self._messaging.publish_task(
                target_agent_id=agent_id,
                task_id=task_id,
                task_type=step.required_capability,
                goal=goal,
                sender_id=_ADMIN_SENDER_ID,
            )
        except Exception as e:
            return StepResult(step_id=step.id, status="failed",
                              error=f"Publish failed: {e}")

        remaining = max(int(deadline - time.monotonic()), 1)
        raw = self._redis.blpop(f"hermes:swarm:result:{task_id}", timeout=remaining)
        if raw is None:
            return StepResult(step_id=step.id, status="failed",
                              error="Step timed out waiting for result")

        try:
            result_data = json.loads(raw[1])
        except (json.JSONDecodeError, IndexError, TypeError) as e:
            return StepResult(step_id=step.id, status="failed",
                              error=f"Invalid result: {e}")

        status = result_data.get("status", "failed")
        return StepResult(
            step_id=step.id,
            status=status,
            output=result_data.get("output") if status == "completed" else None,
            error=result_data.get("error") if status == "failed" else None,
            agent_id=agent_id,
            duration_ms=result_data.get("duration_ms", 0),
        )

    def _run_sequential(self, workflow: WorkflowDef, execution: CrewExecution) -> None:
        for step in workflow.steps:
            if self._check_timeout(execution):
                execution.status = "failed"
                execution.error = "Workflow timeout exceeded"
                return
            result = self._execute_step(step, execution.step_results)
            execution.step_results[step.id] = result
            if result.status == "failed":
                execution.status = "failed"
                execution.error = f"Step {step.id} failed: {result.error}"
                self._cancel_remaining(workflow, step.id, execution)
                return

    def _run_parallel(self, workflow: WorkflowDef, execution: CrewExecution) -> None:
        with ThreadPoolExecutor(max_workers=min(len(workflow.steps), 8)) as pool:
            futures = {
                pool.submit(self._execute_step, step, execution.step_results): step
                for step in workflow.steps
            }
            for future in as_completed(futures):
                step = futures[future]
                try:
                    result = future.result()
                except Exception as e:
                    result = StepResult(step_id=step.id, status="failed", error=str(e))
                with self._result_lock:
                    execution.step_results[step.id] = result
                    if result.status == "failed" and execution.status == "running":
                        execution.status = "failed"
                        execution.error = f"Step {step.id} failed: {result.error}"

    def _run_dag(self, workflow: WorkflowDef, execution: CrewExecution) -> None:
        step_map = {s.id: s for s in workflow.steps}
        raw_steps = [{"id": s.id, "depends_on": s.depends_on} for s in workflow.steps]
        try:
            layers = _topological_sort(raw_steps)
        except ValueError as e:
            execution.status = "failed"
            execution.error = str(e)
            return

        for layer in layers:
            if self._check_timeout(execution):
                execution.status = "failed"
                execution.error = "Workflow timeout exceeded"
                return
            if execution.status == "failed":
                break

            with ThreadPoolExecutor(max_workers=min(len(layer), 8)) as pool:
                futures = {
                    pool.submit(self._execute_step, step_map[sid], execution.step_results): sid
                    for sid in layer
                }
                for future in as_completed(futures):
                    sid = futures[future]
                    try:
                        result = future.result()
                    except Exception as e:
                        result = StepResult(step_id=sid, status="failed", error=str(e))
                    with self._result_lock:
                        execution.step_results[sid] = result
                        if result.status == "failed" and execution.status == "running":
                            execution.status = "failed"
                            execution.error = f"Step {sid} failed: {result.error}"

    def _cancel_remaining(self, workflow: WorkflowDef, failed_id: str,
                           execution: CrewExecution) -> None:
        """Best-effort cancel pending tasks for steps after the failed one."""
        found = False
        for step in workflow.steps:
            if step.id == failed_id:
                found = True
                continue
            if found:
                logger.info("Marking step %s for cancellation after %s failed",
                            step.id, failed_id)
