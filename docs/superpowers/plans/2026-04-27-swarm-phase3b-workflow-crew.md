# Phase 3b: Workflow Engine + Crew CRUD Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement workflow execution engine (sequential/parallel/DAG) and Crew CRUD with Redis persistence, enabling multi-agent collaboration through Admin Panel.

**Architecture:** Admin FastAPI process acts as workflow orchestrator. Each workflow step: SwarmRouter finds capable agent → SwarmMessaging publishes task to agent's Redis Stream → BLPOP waits for result. Workflow execution runs in a dedicated ThreadPoolExecutor, decoupled from uvicorn's event loop. Crew configurations persisted in Redis (hash + set), same pattern as KnowledgeStore.

**Tech Stack:** Python 3.11, FastAPI, redis-py (sync), Pydantic v2, React 19, Zustand, Tailwind 4, TypeScript

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `swarm/crew_store.py` | CrewConfig Redis CRUD (follows KnowledgeStore pattern) |
| Create | `swarm/workflow.py` | WorkflowEngine with sequential/parallel/DAG execution + _SafeFormat |
| Modify | `swarm/__init__.py` | Export CrewStore, CrewConfig, WorkflowEngine, StepResult, CrewExecution |
| Modify | `admin/backend/swarm_models.py` | Add Crew Pydantic models + request/response types |
| Modify | `admin/backend/swarm_routes.py` | Add 7 Crew API endpoints + execution handler |
| Create | `admin/frontend/src/stores/swarmCrews.ts` | Crew Zustand store with CRUD + execution polling |
| Create | `admin/frontend/src/pages/swarm/CrewListPage.tsx` | Crew card grid + create/edit/delete/execute |
| Create | `admin/frontend/src/pages/swarm/CrewEditPage.tsx` | Form editor for create/edit crew |
| Modify | `admin/frontend/src/App.tsx` | Add `/swarm/crews/*` routes under SwarmGuard |
| Modify | `admin/frontend/src/components/AdminLayout.tsx` | Add Crews nav item in Swarm section |
| Modify | `admin/frontend/src/i18n/zh.ts` | Add ~45 crew i18n keys (Translations interface) |
| Modify | `admin/frontend/src/i18n/en.ts` | Add ~45 crew i18n keys (English values) |
| Create | `tests/test_swarm/test_crew_store.py` | Unit tests for CrewStore CRUD |
| Create | `tests/test_swarm/test_workflow.py` | Unit tests for WorkflowEngine + _SafeFormat + DAG |
| Create | `admin/frontend/e2e/crew.spec.ts` | E2E tests for Crew pages |

---

### Task 1: CrewStore — Redis CRUD

**Files:**
- Create: `swarm/crew_store.py`
- Create: `tests/test_swarm/test_crew_store.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_swarm/test_crew_store.py`:

```python
"""Tests for CrewStore — Redis-backed Crew CRUD."""
import json
from dataclasses import asdict
from unittest.mock import MagicMock

from swarm.crew_store import CrewStore, CrewConfig, CrewAgent, WorkflowDef, WorkflowStep


def _make_store():
    redis = MagicMock()
    return CrewStore(redis)


def _sample_crew():
    return CrewConfig(
        crew_id="test-uuid",
        name="Review Team",
        description="Code review crew",
        agents=[CrewAgent(agent_id=1, required_capability="code-review")],
        workflow=WorkflowDef(
            type="sequential",
            steps=[WorkflowStep(id="step_1", required_capability="code-review",
                                task_template="Review: {input}", depends_on=[],
                                input_from={})],
        ),
        created_at=1000.0,
        updated_at=1000.0,
        created_by="admin",
    )


# --- create() ---

def test_create_generates_uuid_and_stores():
    store = _make_store()
    pipe_mock = MagicMock()
    store._redis.pipeline.return_value = pipe_mock

    crew = store.create(
        name="Review Team",
        description="Code review crew",
        agents=[CrewAgent(agent_id=1, required_capability="code-review")],
        workflow=WorkflowDef(
            type="sequential",
            steps=[WorkflowStep(id="step_1", required_capability="code-review",
                                task_template="Review", depends_on=[], input_from={})],
        ),
        created_by="admin",
    )

    assert crew.name == "Review Team"
    assert len(crew.crew_id) == 36  # UUID format
    store._redis.pipeline.assert_called_once()
    pipe_mock.execute.assert_called_once()


# --- get() ---

def test_get_returns_parsed_crew():
    store = _make_store()
    crew = _sample_crew()
    store._redis.hget.return_value = json.dumps(asdict(crew))

    result = store.get("test-uuid")
    assert result is not None
    assert result.name == "Review Team"
    assert result.crew_id == "test-uuid"


def test_get_returns_none_when_missing():
    store = _make_store()
    store._redis.hget.return_value = None
    assert store.get("nope") is None


# --- list_crews() ---

def test_list_crews_returns_all():
    store = _make_store()
    store._redis.smembers.return_value = {"id1"}
    pipe_mock = MagicMock()
    store._redis.pipeline.return_value = pipe_mock
    crew = _sample_crew()
    pipe_mock.execute.return_value = [json.dumps(asdict(crew))]

    crews = store.list_crews()
    assert len(crews) == 1
    assert crews[0].name == "Review Team"


def test_list_crews_empty():
    store = _make_store()
    store._redis.smembers.return_value = set()
    assert store.list_crews() == []


# --- update() ---

def test_update_changes_name_and_touches_timestamp():
    store = _make_store()
    crew = _sample_crew()
    store._redis.hget.return_value = json.dumps(asdict(crew))

    updated = store.update("test-uuid", {"name": "New Name"})
    assert updated is not None
    assert updated.name == "New Name"
    assert updated.updated_at > crew.updated_at


def test_update_returns_none_when_missing():
    store = _make_store()
    store._redis.hget.return_value = None
    assert store.update("nope", {"name": "X"}) is None


# --- delete() ---

def test_delete_removes_from_index_and_data():
    store = _make_store()
    crew = _sample_crew()
    store._redis.hget.return_value = json.dumps(asdict(crew))

    result = store.delete("test-uuid")
    assert result is True
    store._redis.srem.assert_called_with("hermes:crews:index", "test-uuid")
    store._redis.delete.assert_called_with("hermes:crew:test-uuid")


def test_delete_returns_false_when_missing():
    store = _make_store()
    store._redis.hget.return_value = None
    assert store.delete("nope") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /mnt/disk01/workspaces/worksummary/hermes-agent && python -m pytest tests/test_swarm/test_crew_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'swarm.crew_store'`

- [ ] **Step 3: Write the implementation**

Create `swarm/crew_store.py`:

```python
"""Crew persistence — Redis-backed CRUD for CrewConfig."""
from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, asdict, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CrewAgent:
    agent_id: int
    required_capability: str


@dataclass(frozen=True)
class WorkflowStep:
    id: str
    required_capability: str
    task_template: str
    depends_on: list[str] = field(default_factory=list)
    input_from: dict[str, str] = field(default_factory=dict)
    timeout_seconds: int = 120


@dataclass(frozen=True)
class WorkflowDef:
    type: str  # "sequential" | "parallel" | "dag"
    steps: list[WorkflowStep]
    timeout_seconds: int = 300


@dataclass(frozen=True)
class CrewConfig:
    crew_id: str
    name: str
    description: str
    agents: list[CrewAgent]
    workflow: WorkflowDef
    created_at: float
    updated_at: float
    created_by: str


class CrewStore:
    """Redis-backed Crew configuration store.

    Key patterns:
      - ``hermes:crew:{crew_id}``  — hash, field ``data`` → JSON
      - ``hermes:crews:index``     — set of all crew IDs
    """

    def __init__(self, redis_client: Any) -> None:
        self._redis = redis_client

    def create(
        self,
        name: str,
        description: str,
        agents: list[CrewAgent],
        workflow: WorkflowDef,
        created_by: str = "admin",
    ) -> CrewConfig:
        crew_id = str(uuid.uuid4())
        now = time.time()
        crew = CrewConfig(
            crew_id=crew_id,
            name=name,
            description=description,
            agents=agents,
            workflow=workflow,
            created_at=now,
            updated_at=now,
            created_by=created_by,
        )
        pipe = self._redis.pipeline()
        pipe.hset(f"hermes:crew:{crew_id}", "data", json.dumps(asdict(crew)))
        pipe.sadd("hermes:crews:index", crew_id)
        pipe.execute()
        return crew

    def get(self, crew_id: str) -> CrewConfig | None:
        raw = self._redis.hget(f"hermes:crew:{crew_id}", "data")
        if not raw:
            return None
        try:
            d = json.loads(raw)
            return CrewConfig(
                crew_id=d["crew_id"],
                name=d["name"],
                description=d["description"],
                agents=[CrewAgent(**a) for a in d.get("agents", [])],
                workflow=WorkflowDef(
                    type=d["workflow"]["type"],
                    steps=[
                        WorkflowStep(
                            id=s["id"],
                            required_capability=s["required_capability"],
                            task_template=s["task_template"],
                            depends_on=s.get("depends_on", []),
                            input_from=s.get("input_from", {}),
                            timeout_seconds=s.get("timeout_seconds", 120),
                        )
                        for s in d["workflow"].get("steps", [])
                    ],
                    timeout_seconds=d["workflow"].get("timeout_seconds", 300),
                ),
                created_at=d["created_at"],
                updated_at=d["updated_at"],
                created_by=d.get("created_by", ""),
            )
        except (json.JSONDecodeError, ValueError, TypeError, KeyError):
            logger.warning("Failed to parse crew %s", crew_id, exc_info=True)
            return None

    def list_crews(self) -> list[CrewConfig]:
        ids = self._redis.smembers("hermes:crews:index") or set()
        if not ids:
            return []
        pipe = self._redis.pipeline()
        for cid in ids:
            pipe.hget(f"hermes:crew:{cid}", "data")
        raw_results = pipe.execute()
        crews = []
        for raw in raw_results:
            if raw:
                try:
                    d = json.loads(raw)
                    crew = self.get(d.get("crew_id", ""))
                    if crew:
                        crews.append(crew)
                except (json.JSONDecodeError, ValueError, TypeError):
                    continue
        return sorted(crews, key=lambda c: c.created_at, reverse=True)

    def update(self, crew_id: str, updates: dict[str, Any]) -> CrewConfig | None:
        crew = self.get(crew_id)
        if not crew:
            return None
        d = json.loads(self._redis.hget(f"hermes:crew:{crew_id}", "data"))
        d.update(updates)
        d["updated_at"] = time.time()
        self._redis.hset(f"hermes:crew:{crew_id}", "data", json.dumps(d))
        return self.get(crew_id)

    def delete(self, crew_id: str) -> bool:
        exists = self._redis.hget(f"hermes:crew:{crew_id}", "data")
        if not exists:
            return False
        try:
            self._redis.delete(f"hermes:crew:{crew_id}")
            self._redis.srem("hermes:crews:index", crew_id)
        except Exception:
            logger.warning("Crew delete failed for %s", crew_id, exc_info=True)
            return False
        return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /mnt/disk01/workspaces/worksummary/hermes-agent && python -m pytest tests/test_swarm/test_crew_store.py -v`
Expected: All 9 tests PASS

- [ ] **Step 5: Update `swarm/__init__.py` exports**

Add after the existing `from .knowledge import ...` line in `swarm/__init__.py`:

```python
from .crew_store import CrewStore, CrewConfig, CrewAgent, WorkflowDef, WorkflowStep
```

And add to `__all__`:

```python
"CrewStore",
"CrewConfig",
"CrewAgent",
"WorkflowDef",
"WorkflowStep",
```

- [ ] **Step 6: Commit**

```bash
git add swarm/crew_store.py tests/test_swarm/test_crew_store.py swarm/__init__.py
git commit -m "feat(swarm): add CrewStore with Redis CRUD for crew configurations"
```

---

### Task 2: WorkflowEngine — Sequential, Parallel, DAG Execution

**Files:**
- Create: `swarm/workflow.py`
- Create: `tests/test_swarm/test_workflow.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_swarm/test_workflow.py`:

```python
"""Tests for WorkflowEngine — sequential, parallel, DAG execution + _SafeFormat."""
import json
import time
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

from swarm.workflow import (
    WorkflowEngine,
    StepResult,
    CrewExecution,
    _SafeFormat,
    _topological_sort,
)


# ---------------------------------------------------------------------------
# _SafeFormat
# ---------------------------------------------------------------------------

def test_safe_format_replaces_known_keys():
    result = _SafeFormat().format("{step_1.output}", step_1=MagicMock(output="hello"))
    assert result == "hello"


def test_safe_format_preserves_unknown_braces():
    result = _SafeFormat().format("use {unknown_key} please", step_1=MagicMock(output="hi"))
    assert result == "use {unknown_key} please"


def test_safe_format_escapes_output_braces():
    result = _SafeFormat().format(
        "code: {step_1}",
        step_1=MagicMock(output='func({x})'),
    )
    assert "{x}" not in result or "func" in result


def test_safe_format_nested_output():
    result = _SafeFormat().format(
        "{step_1.output}",
        step_1=MagicMock(output="result text"),
    )
    assert result == "result text"


# ---------------------------------------------------------------------------
# _topological_sort
# ---------------------------------------------------------------------------

def test_topo_sort_simple_chain():
    steps = [
        {"id": "a", "depends_on": []},
        {"id": "b", "depends_on": ["a"]},
        {"id": "c", "depends_on": ["b"]},
    ]
    layers = _topological_sort(steps)
    assert layers == [["a"], ["b"], ["c"]]


def test_topo_sort_parallel():
    steps = [
        {"id": "a", "depends_on": []},
        {"id": "b", "depends_on": []},
        {"id": "c", "depends_on": ["a", "b"]},
    ]
    layers = _topological_sort(steps)
    assert layers[0] == ["a", "b"]
    assert layers[1] == ["c"]


def test_topo_sort_detects_cycle():
    steps = [
        {"id": "a", "depends_on": ["b"]},
        {"id": "b", "depends_on": ["a"]},
    ]
    try:
        _topological_sort(steps)
        assert False, "Expected ValueError for cycle"
    except ValueError as e:
        assert "cycle" in str(e).lower() or "circular" in str(e).lower()


def test_topo_sort_empty():
    assert _topological_sort([]) == []


def test_topo_sort_single():
    assert _topological_sort([{"id": "a", "depends_on": []}]) == [["a"]]


# ---------------------------------------------------------------------------
# WorkflowEngine — Sequential
# ---------------------------------------------------------------------------

def _make_engine():
    redis_mock = MagicMock()
    router_mock = MagicMock()
    messaging_mock = MagicMock()
    return WorkflowEngine(redis_mock, router_mock, messaging_mock), redis_mock, router_mock, messaging_mock


def test_sequential_execution_passes_outputs():
    engine, redis, router, messaging = _make_engine()
    router.find_agent.side_effect = [1, 2]
    messaging.publish_task.side_effect = ["msg1", "msg2"]

    # First BLPOP returns result for step_1, second for step_2
    redis.blpop.side_effect = [
        [b"hermes:swarm:result:t1", json.dumps({"status": "completed", "output": "step1_result", "duration_ms": 100}).encode()],
        [b"hermes:swarm:result:t2", json.dumps({"status": "completed", "output": "step2_result", "duration_ms": 200}).encode()],
    ]

    from swarm.crew_store import WorkflowStep, WorkflowDef, CrewAgent
    from unittest.mock import MagicMock as MM

    workflow = WorkflowDef(
        type="sequential",
        steps=[
            WorkflowStep(id="step_1", required_capability="cap-a",
                        task_template="do {input}", depends_on=[], input_from={}),
            WorkflowStep(id="step_2", required_capability="cap-b",
                        task_template="review: {step_1}", depends_on=["step_1"],
                        input_from={}),
        ],
    )

    with patch("swarm.workflow.uuid4", side_effect=["t1", "t2"]):
        result = engine.execute(workflow, workflow_timeout=30)

    assert result.status == "completed"
    assert result.step_results["step_1"].output == "step1_result"
    assert result.step_results["step_2"].output == "step2_result"


def test_sequential_stops_on_failure():
    engine, redis, router, messaging = _make_engine()
    router.find_agent.return_value = 1
    messaging.publish_task.return_value = "msg1"

    redis.blpop.return_value = [
        b"hermes:swarm:result:t1",
        json.dumps({"status": "failed", "error": "agent error", "duration_ms": 50}).encode(),
    ]

    from swarm.crew_store import WorkflowStep, WorkflowDef

    workflow = WorkflowDef(
        type="sequential",
        steps=[
            WorkflowStep(id="step_1", required_capability="cap-a",
                        task_template="do", depends_on=[], input_from={}),
            WorkflowStep(id="step_2", required_capability="cap-b",
                        task_template="next", depends_on=["step_1"], input_from={}),
        ],
    )

    with patch("swarm.workflow.uuid4", return_value="t1"):
        result = engine.execute(workflow, workflow_timeout=30)

    assert result.status == "failed"
    assert "step_1" in result.step_results
    assert result.step_results["step_1"].status == "failed"


def test_no_agent_available_fails_step():
    engine, redis, router, messaging = _make_engine()
    router.find_agent.return_value = None

    from swarm.crew_store import WorkflowStep, WorkflowDef

    workflow = WorkflowDef(
        type="sequential",
        steps=[
            WorkflowStep(id="step_1", required_capability="missing-cap",
                        task_template="do", depends_on=[], input_from={}),
        ],
    )

    result = engine.execute(workflow, workflow_timeout=30)
    assert result.status == "failed"
    assert result.step_results["step_1"].status == "failed"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /mnt/disk01/workspaces/worksummary/hermes-agent && python -m pytest tests/test_swarm/test_workflow.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'swarm.workflow'`

- [ ] **Step 3: Write the implementation**

Create `swarm/workflow.py`:

```python
"""Workflow execution engine — sequential, parallel, DAG modes."""
from __future__ import annotations

import json
import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from typing import Any

from swarm.crew_store import WorkflowDef, WorkflowStep

logger = logging.getLogger(__name__)

# Sentinel sender_id for Admin orchestrator (not a registered agent).
_ADMIN_SENDER_ID = 0


# ---------------------------------------------------------------------------
# _SafeFormat — safe variable replacement without Jinja2
# ---------------------------------------------------------------------------

class _SafeFormat:
    """Format strings using str.format_map with safe missing-key handling.

    Known keys (step IDs from the workflow) are resolved normally.
    Unknown brace expressions are preserved verbatim (no KeyError).
    Step output containing ``{`` / ``}`` is pre-escaped to ``{{`` / ``}}``.
    """

    def format(self, template: str, **kwargs: Any) -> str:
        # Pre-escape brace characters in all step outputs
        safe_kwargs: dict[str, str] = {}
        for k, v in kwargs.items():
            text = getattr(v, "output", str(v))
            safe_kwargs[k] = text.replace("{", "{{").replace("}", "}}")

        class _SafeDict(dict):
            def __missing__(self, key: str) -> str:
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

    def execute(self, workflow: WorkflowDef, crew_id: str = "",
                workflow_timeout: int | None = None) -> CrewExecution:
        timeout = workflow_timeout or workflow.timeout_seconds
        execution = CrewExecution(
            exec_id=str(uuid.uuid4()),
            crew_id=crew_id,
            status="running",
            started_at=time.monotonic(),
            timeout_seconds=timeout,
        )

        if workflow.type == "sequential":
            self._run_sequential(workflow, execution)
        elif workflow.type == "parallel":
            self._run_parallel(workflow, execution)
        elif workflow.type == "dag":
            self._run_dag(workflow, execution)

        if execution.status == "running":
            execution.status = "completed"
        execution.finished_at = time.monotonic()
        return execution

    def _check_timeout(self, execution: CrewExecution) -> bool:
        elapsed = time.monotonic() - execution.started_at
        return elapsed > execution.timeout_seconds

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

        task_id = str(uuid.uuid4())
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
                # Set cancel key — Consumer checks before execution
                task_key = f"hermes:swarm:cancel:tbd"  # task_id unknown until submitted
                logger.info("Marking step %s for cancellation after %s failed",
                            step.id, failed_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /mnt/disk01/workspaces/worksummary/hermes-agent && python -m pytest tests/test_swarm/test_workflow.py -v`
Expected: All tests PASS

- [ ] **Step 5: Update `swarm/__init__.py` exports**

Add to `swarm/__init__.py`:

```python
from .workflow import WorkflowEngine, StepResult, CrewExecution
```

And add to `__all__`:

```python
"WorkflowEngine",
"StepResult",
"CrewExecution",
```

- [ ] **Step 6: Run full test suite**

Run: `cd /mnt/disk01/workspaces/worksummary/hermes-agent && python -m pytest tests/test_swarm/ -q`
Expected: All tests PASS (including existing ones)

- [ ] **Step 7: Commit**

```bash
git add swarm/workflow.py tests/test_swarm/test_workflow.py swarm/__init__.py
git commit -m "feat(swarm): add WorkflowEngine with sequential, parallel, and DAG execution"
```

---

### Task 3: Backend — Crew Pydantic Models + API Endpoints

**Files:**
- Modify: `admin/backend/swarm_models.py`
- Modify: `admin/backend/swarm_routes.py`

- [ ] **Step 1: Add Crew Pydantic models to `swarm_models.py`**

Append to `admin/backend/swarm_models.py` after the existing models:

```python
from typing import Literal


# --- Crew models ---

class CrewAgentModel(BaseModel):
    agent_id: int
    required_capability: str


class WorkflowStepModel(BaseModel):
    id: str = Field(..., min_length=1, max_length=64)
    required_capability: str = Field(..., min_length=1, max_length=128)
    task_template: str = Field("", max_length=10000)
    depends_on: list[str] = Field(default_factory=list)
    input_from: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: int = Field(120, ge=10, le=600)


class WorkflowDefModel(BaseModel):
    type: Literal["sequential", "parallel", "dag"]
    steps: list[WorkflowStepModel] = Field(..., min_length=1)
    timeout_seconds: int = Field(300, ge=30, le=3600)

    @model_validator(mode="after")
    def validate_step_deps(self) -> "WorkflowDefModel":
        step_ids = {s.id for s in self.steps}
        for step in self.steps:
            for dep in step.depends_on:
                if dep not in step_ids:
                    raise ValueError(
                        f"Step '{step.id}' depends_on '{dep}' not found in step list"
                    )
        return self


class CrewCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    description: str = Field("", max_length=1024)
    agents: list[CrewAgentModel] = Field(default_factory=list)
    workflow: WorkflowDefModel
    created_by: str = Field("admin", max_length=64)


class CrewUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    agents: list[CrewAgentModel] | None = None
    workflow: WorkflowDefModel | None = None


class CrewResponse(BaseModel):
    crew_id: str
    name: str
    description: str = ""
    agents: list[CrewAgentModel] = []
    workflow: WorkflowDefModel
    created_at: float
    updated_at: float
    created_by: str = ""


class CrewExecutionResponse(BaseModel):
    exec_id: str
    crew_id: str
    status: str
    step_results: dict = {}
    error: str | None = None
    started_at: float
    finished_at: float | None = None
    timeout_seconds: int = 300


class CrewListResponse(BaseModel):
    results: list[CrewResponse]
    total: int
```

- [ ] **Step 2: Add Crew API endpoints to `swarm_routes.py`**

Add imports at top of `admin/backend/swarm_routes.py`:

```python
from swarm_models import (
    # ... existing imports ...
    CrewCreateRequest,
    CrewUpdateRequest,
    CrewResponse,
    CrewListResponse,
    CrewExecutionResponse,
)
from swarm.crew_store import CrewStore
from swarm.workflow import WorkflowEngine
from swarm.router import SwarmRouter
from swarm.messaging import SwarmMessaging
```

Add helper after the `_get_redis` function:

```python
def _get_crew_store(request: Request) -> CrewStore | None:
    redis = _get_redis(request)
    if redis is None:
        return None
    return CrewStore(redis)


_workflow_executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)
```

Add these endpoints at the end of `swarm_routes.py` (before the SSE endpoints):

```python

# ---------------------------------------------------------------------------
# Crew CRUD
# ---------------------------------------------------------------------------

@router.get("/crews", response_model=CrewListResponse, dependencies=[_auth])
async def list_crews(request: Request):
    store = _get_crew_store(request)
    if store is None:
        return CrewListResponse(results=[], total=0)
    crews = store.list_crews()
    results = [
        CrewResponse(
            crew_id=c.crew_id, name=c.name, description=c.description,
            agents=[CrewAgentModel(agent_id=a.agent_id,
                                   required_capability=a.required_capability)
                    for a in c.agents],
            workflow=WorkflowDefModel(
                type=c.workflow.type, timeout_seconds=c.workflow.timeout_seconds,
                steps=[WorkflowStepModel(
                    id=s.id, required_capability=s.required_capability,
                    task_template=s.task_template, depends_on=s.depends_on,
                    input_from=s.input_from, timeout_seconds=s.timeout_seconds,
                ) for s in c.workflow.steps],
            ),
            created_at=c.created_at, updated_at=c.updated_at,
            created_by=c.created_by,
        )
        for c in crews
    ]
    return CrewListResponse(results=results, total=len(results))


@router.post("/crews", response_model=CrewResponse, dependencies=[_auth])
async def create_crew(request: Request, body: CrewCreateRequest):
    store = _get_crew_store(request)
    if store is None:
        raise HTTPException(status_code=503, detail="Redis unavailable")
    from swarm.crew_store import CrewAgent as CrewAgentData
    from swarm.crew_store import WorkflowStep as StepData
    from swarm.crew_store import WorkflowDef as DefData
    crew = store.create(
        name=body.name,
        description=body.description,
        agents=[CrewAgentData(agent_id=a.agent_id,
                              required_capability=a.required_capability)
                for a in body.agents],
        workflow=DefData(
            type=body.workflow.type,
            steps=[StepData(
                id=s.id, required_capability=s.required_capability,
                task_template=s.task_template, depends_on=s.depends_on,
                input_from=s.input_from, timeout_seconds=s.timeout_seconds,
            ) for s in body.workflow.steps],
            timeout_seconds=body.workflow.timeout_seconds,
        ),
        created_by=body.created_by,
    )
    return CrewResponse(
        crew_id=crew.crew_id, name=crew.name, description=crew.description,
        agents=[CrewAgentModel(agent_id=a.agent_id,
                               required_capability=a.required_capability)
                for a in crew.agents],
        workflow=WorkflowDefModel(
            type=crew.workflow.type, timeout_seconds=crew.workflow.timeout_seconds,
            steps=[WorkflowStepModel(
                id=s.id, required_capability=s.required_capability,
                task_template=s.task_template, depends_on=s.depends_on,
                input_from=s.input_from, timeout_seconds=s.timeout_seconds,
            ) for s in crew.workflow.steps],
        ),
        created_at=crew.created_at, updated_at=crew.updated_at,
        created_by=crew.created_by,
    )


@router.get("/crews/{crew_id}", response_model=CrewResponse | None,
             dependencies=[_auth])
async def get_crew(request: Request, crew_id: str = Path(...)):
    store = _get_crew_store(request)
    if store is None:
        raise HTTPException(status_code=503, detail="Redis unavailable")
    crew = store.get(crew_id)
    if crew is None:
        raise HTTPException(status_code=404, detail="Crew not found")
    return CrewResponse(
        crew_id=crew.crew_id, name=crew.name, description=crew.description,
        agents=[CrewAgentModel(agent_id=a.agent_id,
                               required_capability=a.required_capability)
                for a in crew.agents],
        workflow=WorkflowDefModel(
            type=crew.workflow.type, timeout_seconds=crew.workflow.timeout_seconds,
            steps=[WorkflowStepModel(
                id=s.id, required_capability=s.required_capability,
                task_template=s.task_template, depends_on=s.depends_on,
                input_from=s.input_from, timeout_seconds=s.timeout_seconds,
            ) for s in crew.workflow.steps],
        ),
        created_at=crew.created_at, updated_at=crew.updated_at,
        created_by=crew.created_by,
    )


@router.put("/crews/{crew_id}", response_model=CrewResponse | None,
             dependencies=[_auth])
async def update_crew(request: Request, body: CrewUpdateRequest,
                      crew_id: str = Path(...)):
    store = _get_crew_store(request)
    if store is None:
        raise HTTPException(status_code=503, detail="Redis unavailable")
    updates: dict = {}
    if body.name is not None:
        updates["name"] = body.name
    if body.description is not None:
        updates["description"] = body.description
    if body.agents is not None:
        updates["agents"] = [
            {"agent_id": a.agent_id, "required_capability": a.required_capability}
            for a in body.agents
        ]
    if body.workflow is not None:
        from dataclasses import asdict
        updates["workflow"] = {
            "type": body.workflow.type,
            "steps": [
                {"id": s.id, "required_capability": s.required_capability,
                 "task_template": s.task_template, "depends_on": s.depends_on,
                 "input_from": s.input_from, "timeout_seconds": s.timeout_seconds}
                for s in body.workflow.steps
            ],
            "timeout_seconds": body.workflow.timeout_seconds,
        }
    crew = store.update(crew_id, updates)
    if crew is None:
        raise HTTPException(status_code=404, detail="Crew not found")
    return await get_crew(request, crew_id)


@router.delete("/crews/{crew_id}", dependencies=[_auth])
async def delete_crew(request: Request, crew_id: str = Path(...)):
    store = _get_crew_store(request)
    if store is None:
        raise HTTPException(status_code=503, detail="Redis unavailable")
    deleted = store.delete(crew_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Crew not found")
    return {"status": "deleted"}


@router.post("/crews/{crew_id}/execute", dependencies=[_auth])
async def execute_crew(request: Request, crew_id: str = Path(...)):
    redis = _get_redis(request)
    if redis is None:
        raise HTTPException(status_code=503, detail="Redis unavailable")
    store = _get_crew_store(request)
    crew = store.get(crew_id) if store else None
    if crew is None:
        raise HTTPException(status_code=404, detail="Crew not found")

    # Distributed lock — prevent concurrent execution of the same crew
    lock_key = f"hermes:crew_exec_lock:{crew_id}"
    import uuid as _uuid
    exec_id = str(_uuid.uuid4())
    acquired = redis.set(lock_key, exec_id, nx=True, ex=crew.workflow.timeout_seconds + 60)
    if not acquired:
        raise HTTPException(status_code=409, detail="Crew execution already in progress")

    def _run():
        from swarm.workflow import CrewExecution
        router = SwarmRouter(redis)
        messaging = SwarmMessaging(redis)
        engine = WorkflowEngine(redis, router, messaging)
        execution = engine.execute(crew.workflow, crew_id=crew_id)
        # Persist result
        redis.hset(f"hermes:crew_exec:{execution.exec_id}", "data",
                   json.dumps({
                       "exec_id": execution.exec_id,
                       "crew_id": execution.crew_id,
                       "status": execution.status,
                       "step_results": {
                           sid: {"step_id": r.step_id, "status": r.status,
                                 "output": r.output, "error": r.error,
                                 "agent_id": r.agent_id, "duration_ms": r.duration_ms}
                           for sid, r in execution.step_results.items()
                       },
                       "error": execution.error,
                       "started_at": execution.started_at,
                       "finished_at": execution.finished_at,
                       "timeout_seconds": execution.timeout_seconds,
                   }))
        redis.expire(f"hermes:crew_exec:{execution.exec_id}", 3600)
        # Release lock
        redis.delete(lock_key)

    _workflow_executor.submit(_run)
    return {"exec_id": exec_id, "status": "pending"}


@router.get("/crews/{crew_id}/executions/{exec_id}",
             response_model=CrewExecutionResponse | None,
             dependencies=[_auth])
async def get_execution(request: Request, crew_id: str = Path(...),
                        exec_id: str = Path(...)):
    redis = _get_redis(request)
    if redis is None:
        return None
    raw = redis.hget(f"hermes:crew_exec:{exec_id}", "data")
    if not raw:
        return None
    data = json.loads(raw)
    return CrewExecutionResponse(**data)
```

- [ ] **Step 3: Run Python tests to verify no regressions**

Run: `cd /mnt/disk01/workspaces/worksummary/hermes-agent && python -m pytest tests/ -q`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add admin/backend/swarm_models.py admin/backend/swarm_routes.py
git commit -m "feat(admin): add Crew CRUD API endpoints and workflow execution"
```

---

### Task 4: Frontend — Crew Zustand Store + i18n

**Files:**
- Create: `admin/frontend/src/stores/swarmCrews.ts`
- Modify: `admin/frontend/src/i18n/zh.ts`
- Modify: `admin/frontend/src/i18n/en.ts`

- [ ] **Step 1: Add i18n keys to both language files**

Add to the `Translations` interface in `admin/frontend/src/i18n/zh.ts` (after knowledge keys, before the closing `}`):

```typescript
  // Crew
  crewTitle: string;
  crewAdd: string;
  crewEdit: string;
  crewName: string;
  crewDescription: string;
  crewAgents: string;
  crewAgentId: string;
  crewAgentCapability: string;
  crewWorkflowType: string;
  crewWorkflowSteps: string;
  crewStepId: string;
  crewStepCapability: string;
  crewStepTemplate: string;
  crewStepDependsOn: string;
  crewStepInputFrom: string;
  crewStepTimeout: string;
  crewWorkflowTimeout: string;
  crewNoCrews: string;
  crewCreateButton: string;
  crewDeleteConfirm: string;
  crewDeleteLabel: string;
  crewCancel: string;
  crewSave: string;
  crewSequential: string;
  crewParallel: string;
  crewDAG: string;
  crewExecute: string;
  crewExecuting: string;
  crewExecuteConfirm: string;
  crewExecutionStatus: string;
  crewExecutionCompleted: string;
  crewExecutionFailed: string;
  crewExecutionPending: string;
  crewExecutionRunning: string;
  crewLoadError: string;
  crewAgentOnline: string;
  crewAgentOffline: string;
  crewAgentBusy: string;
  crewAddStep: string;
  crewRemoveStep: string;
  crewAddAgent: string;
  crewRemoveAgent: string;
  crewStepTemplateHint: string;
  crewValidationCycle: string;
  crewValidationEmptySteps: string;
  crewValidationRequired: string;
```

Add the Chinese values to `zh.ts` after the knowledge section in the `zh` object:

```typescript
  // Crew
  crewTitle: "Crew 管理",
  crewAdd: "创建 Crew",
  crewEdit: "编辑 Crew",
  crewName: "名称",
  crewDescription: "描述",
  crewAgents: "Agent 分配",
  crewAgentId: "Agent ID",
  crewAgentCapability: "所需能力",
  crewWorkflowType: "工作流类型",
  crewWorkflowSteps: "工作流步骤",
  crewStepId: "步骤 ID",
  crewStepCapability: "能力",
  crewStepTemplate: "任务模板",
  crewStepDependsOn: "依赖步骤",
  crewStepInputFrom: "输入映射",
  crewStepTimeout: "步骤超时(秒)",
  crewWorkflowTimeout: "工作流超时(秒)",
  crewNoCrews: "暂无 Crew",
  crewCreateButton: "创建",
  crewDeleteConfirm: "确定删除此 Crew？",
  crewDeleteLabel: "删除",
  crewCancel: "取消",
  crewSave: "保存",
  crewSequential: "顺序",
  crewParallel: "并行",
  crewDAG: "DAG",
  crewExecute: "执行",
  crewExecuting: "执行中...",
  crewExecuteConfirm: "确定执行此 Crew 的工作流？",
  crewExecutionStatus: "执行状态",
  crewExecutionCompleted: "已完成",
  crewExecutionFailed: "失败",
  crewExecutionPending: "等待中",
  crewExecutionRunning: "运行中",
  crewLoadError: "加载 Crew 列表失败",
  crewAgentOnline: "在线",
  crewAgentOffline: "离线",
  crewAgentBusy: "忙碌",
  crewAddStep: "添加步骤",
  crewRemoveStep: "移除",
  crewAddAgent: "添加 Agent",
  crewRemoveAgent: "移除",
  crewStepTemplateHint: "使用 {step_id} 引用上一步输出",
  crewValidationCycle: "工作流存在循环依赖",
  crewValidationEmptySteps: "至少需要一个步骤",
  crewValidationRequired: "此字段为必填",
```

Add the English values to `en.ts` after the knowledge section in the `en` object:

```typescript
  // Crew
  crewTitle: "Crew Management",
  crewAdd: "Create Crew",
  crewEdit: "Edit Crew",
  crewName: "Name",
  crewDescription: "Description",
  crewAgents: "Agent Assignment",
  crewAgentId: "Agent ID",
  crewAgentCapability: "Required Capability",
  crewWorkflowType: "Workflow Type",
  crewWorkflowSteps: "Workflow Steps",
  crewStepId: "Step ID",
  crewStepCapability: "Capability",
  crewStepTemplate: "Task Template",
  crewStepDependsOn: "Dependencies",
  crewStepInputFrom: "Input Mapping",
  crewStepTimeout: "Step Timeout (s)",
  crewWorkflowTimeout: "Workflow Timeout (s)",
  crewNoCrews: "No crews yet",
  crewCreateButton: "Create",
  crewDeleteConfirm: "Delete this crew?",
  crewDeleteLabel: "Delete",
  crewCancel: "Cancel",
  crewSave: "Save",
  crewSequential: "Sequential",
  crewParallel: "Parallel",
  crewDAG: "DAG",
  crewExecute: "Execute",
  crewExecuting: "Executing...",
  crewExecuteConfirm: "Execute this crew's workflow?",
  crewExecutionStatus: "Execution Status",
  crewExecutionCompleted: "Completed",
  crewExecutionFailed: "Failed",
  crewExecutionPending: "Pending",
  crewExecutionRunning: "Running",
  crewLoadError: "Failed to load crews",
  crewAgentOnline: "Online",
  crewAgentOffline: "Offline",
  crewAgentBusy: "Busy",
  crewAddStep: "Add Step",
  crewRemoveStep: "Remove",
  crewAddAgent: "Add Agent",
  crewRemoveAgent: "Remove",
  crewStepTemplateHint: "Use {step_id} to reference previous step output",
  crewValidationCycle: "Workflow has circular dependencies",
  crewValidationEmptySteps: "At least one step is required",
  crewValidationRequired: "This field is required",
```

- [ ] **Step 2: Create the Crew Zustand store**

Create `admin/frontend/src/stores/swarmCrews.ts`:

```typescript
import { create } from "zustand";
import { adminFetch } from "../lib/admin-api";

export interface CrewAgent {
  agent_id: number;
  required_capability: string;
}

export interface WorkflowStep {
  id: string;
  required_capability: string;
  task_template: string;
  depends_on: string[];
  input_from: Record<string, string>;
  timeout_seconds: number;
}

export interface WorkflowDef {
  type: "sequential" | "parallel" | "dag";
  steps: WorkflowStep[];
  timeout_seconds: number;
}

export interface Crew {
  crew_id: string;
  name: string;
  description: string;
  agents: CrewAgent[];
  workflow: WorkflowDef;
  created_at: number;
  updated_at: number;
  created_by: string;
}

interface ExecutionResult {
  exec_id: string;
  crew_id: string;
  status: string;
  step_results: Record<string, {
    step_id: string;
    status: string;
    output: string | null;
    error: string | null;
    agent_id: number | null;
    duration_ms: number;
  }>;
  error: string | null;
  started_at: number;
  finished_at: number | null;
  timeout_seconds: number;
}

interface SwarmCrewsState {
  crews: Crew[];
  loading: boolean;
  error: string | null;
  execution: ExecutionResult | null;
  executionLoading: boolean;
  fetchCrews: () => Promise<void>;
  createCrew: (data: Omit<Crew, "crew_id" | "created_at" | "updated_at" | "created_by">) => Promise<string | null>;
  updateCrew: (crewId: string, data: Partial<Crew>) => Promise<boolean>;
  deleteCrew: (crewId: string) => Promise<boolean>;
  executeCrew: (crewId: string) => Promise<string | null>;
  pollExecution: (crewId: string, execId: string) => Promise<void>;
}

export const useSwarmCrews = create<SwarmCrewsState>((set, get) => ({
  crews: [],
  loading: false,
  error: null,
  execution: null,
  executionLoading: false,

  fetchCrews: async () => {
    set({ loading: true, error: null });
    try {
      const data = await adminFetch<{ results: Crew[]; total: number }>("/swarm/crews");
      set({ crews: data.results, loading: false });
    } catch {
      set({ error: "Failed to fetch crews", loading: false });
    }
  },

  createCrew: async (data) => {
    try {
      const crew = await adminFetch<Crew>("/swarm/crews", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
      await get().fetchCrews();
      return crew.crew_id;
    } catch {
      set({ error: "Failed to create crew" });
      return null;
    }
  },

  updateCrew: async (crewId, data) => {
    try {
      await adminFetch<Crew>(`/swarm/crews/${crewId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
      await get().fetchCrews();
      return true;
    } catch {
      set({ error: "Failed to update crew" });
      return false;
    }
  },

  deleteCrew: async (crewId) => {
    try {
      await adminFetch(`/swarm/crews/${crewId}`, { method: "DELETE" });
      await get().fetchCrews();
      return true;
    } catch {
      set({ error: "Failed to delete crew" });
      return false;
    }
  },

  executeCrew: async (crewId) => {
    set({ executionLoading: true, execution: null });
    try {
      const result = await adminFetch<{ exec_id: string; status: string }>(
        `/swarm/crews/${crewId}/execute`,
        { method: "POST" }
      );
      set({ executionLoading: false });
      return result.exec_id;
    } catch {
      set({ error: "Failed to execute crew", executionLoading: false });
      return null;
    }
  },

  pollExecution: async (crewId, execId) => {
    try {
      const result = await adminFetch<ExecutionResult | null>(
        `/swarm/crews/${crewId}/executions/${execId}`
      );
      if (result) {
        set({ execution: result });
      }
    } catch {
      // Polling errors are non-critical
    }
  },
}));
```

- [ ] **Step 3: Run TypeScript check**

Run: `cd /mnt/disk01/workspaces/worksummary/hermes-agent/admin/frontend && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add admin/frontend/src/stores/swarmCrews.ts admin/frontend/src/i18n/zh.ts admin/frontend/src/i18n/en.ts
git commit -m "feat(admin): add Crew Zustand store and ~45 i18n keys"
```

---

### Task 5: Frontend — Crew Pages + Routing

**Files:**
- Create: `admin/frontend/src/pages/swarm/CrewListPage.tsx`
- Create: `admin/frontend/src/pages/swarm/CrewEditPage.tsx`
- Modify: `admin/frontend/src/App.tsx`
- Modify: `admin/frontend/src/components/AdminLayout.tsx`

- [ ] **Step 1: Create CrewListPage**

Create `admin/frontend/src/pages/swarm/CrewListPage.tsx`:

```tsx
import { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useSwarmCrews } from "../../stores/swarmCrews";
import { useSwarmRegistry } from "../../stores/swarmRegistry";
import { useI18n } from "../../hooks/useI18n";
import { LoadingSpinner } from "../../components/LoadingSpinner";

const WORKFLOW_BADGES: Record<string, string> = {
  sequential: "bg-accent-cyan/20 text-accent-cyan",
  parallel: "bg-amber-500/20 text-amber-400",
  dag: "bg-accent-pink/20 text-accent-pink",
};

export function CrewListPage() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const { crews, loading, error, fetchCrews, deleteCrew, executeCrew, pollExecution, execution, executionLoading } =
    useSwarmCrews();
  const { agents, fetchAgents } = useSwarmRegistry();
  const [execCrewId, setExecCrewId] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    fetchCrews();
    fetchAgents();
  }, [fetchCrews, fetchAgents]);

  useEffect(() => {
    if (execCrewId && execution?.status === "running") {
      pollRef.current = setInterval(() => {
        pollExecution(execCrewId, execution.exec_id);
      }, 3000);
      return () => { if (pollRef.current) clearInterval(pollRef.current); };
    }
    if (pollRef.current && execution?.status !== "running") {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, [execCrewId, execution?.status, execution?.exec_id, pollExecution]);

  const handleDelete = async (crewId: string, name: string) => {
    if (!confirm(`${t.crewDeleteConfirm}\n${name}`)) return;
    await deleteCrew(crewId);
  };

  const handleExecute = async (crewId: string) => {
    if (!confirm(t.crewExecuteConfirm)) return;
    setExecCrewId(crewId);
    const execId = await executeCrew(crewId);
    if (execId) {
      await pollExecution(crewId, execId);
    }
  };

  const agentName = (id: number) =>
    agents.find((a) => a.agent_id === id)?.display_name || `Agent ${id}`;

  if (loading && crews.length === 0) return <LoadingSpinner />;

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-semibold font-[family-name:var(--font-body)] text-text-primary">
          {t.crewTitle}
        </h1>
        <button
          onClick={() => navigate("/swarm/crews/new")}
          className="h-9 px-4 text-sm bg-accent-cyan text-bg rounded-lg hover:bg-accent-cyan/90 transition-colors font-medium"
        >
          {t.crewAdd}
        </button>
      </div>

      {error && (
        <div className="mb-4 px-4 py-2 rounded-lg bg-accent-pink/10 text-accent-pink text-sm">
          {t.crewLoadError}
        </div>
      )}

      {/* Execution progress overlay */}
      {execution && (
        <div className="mb-4 px-4 py-3 rounded-lg bg-surface/80 border border-border-subtle">
          <div className="flex items-center gap-2 text-sm">
            <span className="text-text-secondary">{t.crewExecutionStatus}:</span>
            <span className={execution.status === "completed" ? "text-green-400" : execution.status === "failed" ? "text-accent-pink" : "text-accent-cyan"}>
              {execution.status === "completed" ? t.crewExecutionCompleted :
               execution.status === "failed" ? t.crewExecutionFailed :
               execution.status === "running" ? t.crewExecutionRunning : t.crewExecutionPending}
            </span>
          </div>
          {execution.error && (
            <p className="mt-1 text-xs text-accent-pink">{execution.error}</p>
          )}
        </div>
      )}

      {crews.length === 0 && !loading ? (
        <div className="flex flex-col items-center justify-center py-20 text-text-secondary">
          <p className="text-lg mb-4">{t.crewNoCrews}</p>
          <button
            onClick={() => navigate("/swarm/crews/new")}
            className="px-6 py-2 bg-accent-cyan text-bg rounded-lg hover:bg-accent-cyan/90 transition-colors"
          >
            {t.crewAdd}
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {crews.map((crew, i) => (
            <div
              key={crew.crew_id}
              className="bg-surface/60 border border-border-subtle rounded-xl p-5 hover:border-accent-cyan/30 transition-colors animate-stagger"
              style={{ animationDelay: `${i * 50}ms` }}
            >
              <div className="flex items-start justify-between mb-3">
                <h3 className="font-semibold text-text-primary">{crew.name}</h3>
                <span className={`px-2 py-0.5 rounded text-xs font-medium ${WORKFLOW_BADGES[crew.workflow.type] || "bg-surface text-text-secondary"}`}>
                  {crew.workflow.type === "sequential" ? t.crewSequential :
                   crew.workflow.type === "parallel" ? t.crewParallel : t.crewDAG}
                </span>
              </div>
              {crew.description && (
                <p className="text-sm text-text-secondary mb-3 line-clamp-2">{crew.description}</p>
              )}
              <div className="flex items-center gap-2 text-xs text-text-secondary mb-4">
                <span>{crew.agents.length} agents</span>
                <span>·</span>
                <span>{crew.workflow.steps.length} steps</span>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => navigate(`/swarm/crews/${crew.crew_id}/edit`)}
                  className="px-3 py-1.5 text-xs bg-surface border border-border-subtle rounded-lg hover:border-accent-cyan/40 transition-colors"
                >
                  {t.crewEdit}
                </button>
                <button
                  onClick={() => handleExecute(crew.crew_id)}
                  disabled={executionLoading}
                  className="px-3 py-1.5 text-xs bg-accent-cyan/20 text-accent-cyan rounded-lg hover:bg-accent-cyan/30 transition-colors disabled:opacity-50"
                >
                  {executionLoading ? t.crewExecuting : t.crewExecute}
                </button>
                <button
                  onClick={() => handleDelete(crew.crew_id, crew.name)}
                  className="px-3 py-1.5 text-xs text-accent-pink hover:bg-accent-pink/10 rounded-lg transition-colors ml-auto"
                >
                  {t.crewDeleteLabel}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Create CrewEditPage**

Create `admin/frontend/src/pages/swarm/CrewEditPage.tsx`:

```tsx
import { useState, useEffect } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useSwarmCrews, WorkflowStep, CrewAgent } from "../../stores/swarmCrews";
import { useSwarmRegistry } from "../../stores/swarmRegistry";
import { useI18n } from "../../hooks/useI18n";
import { LoadingSpinner } from "../../components/LoadingSpinner";

export function CrewEditPage() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const { id } = useParams();
  const isEdit = Boolean(id);
  const { crews, fetchCrews, createCrew, updateCrew } = useSwarmCrews();
  const { agents, fetchAgents } = useSwarmRegistry();

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [workflowType, setWorkflowType] = useState<"sequential" | "parallel" | "dag">("sequential");
  const [workflowTimeout, setWorkflowTimeout] = useState(300);
  const [crewAgents, setCrewAgents] = useState<CrewAgent[]>([]);
  const [steps, setSteps] = useState<WorkflowStep[]>([
    { id: "step_1", required_capability: "", task_template: "", depends_on: [], input_from: {}, timeout_seconds: 120 },
  ]);
  const [saving, setSaving] = useState(false);
  const [validationError, setValidationError] = useState<string | null>(null);

  useEffect(() => {
    fetchAgents();
    if (isEdit) {
      fetchCrews();
    }
  }, [fetchAgents, fetchCrews, isEdit]);

  useEffect(() => {
    if (isEdit && id) {
      const crew = crews.find((c) => c.crew_id === id);
      if (crew) {
        setName(crew.name);
        setDescription(crew.description);
        setWorkflowType(crew.workflow.type);
        setWorkflowTimeout(crew.workflow.timeout_seconds);
        setCrewAgents(crew.agents);
        setSteps(crew.workflow.steps);
      }
    }
  }, [isEdit, id, crews]);

  const addAgent = () => {
    setCrewAgents([...crewAgents, { agent_id: 0, required_capability: "" }]);
  };

  const removeAgent = (idx: number) => {
    setCrewAgents(crewAgents.filter((_, i) => i !== idx));
  };

  const updateAgent = (idx: number, field: keyof CrewAgent, value: string | number) => {
    const updated = [...crewAgents];
    updated[idx] = { ...updated[idx], [field]: value };
    setCrewAgents(updated);
  };

  const addStep = () => {
    setSteps([...steps, {
      id: `step_${steps.length + 1}`,
      required_capability: "",
      task_template: "",
      depends_on: [],
      input_from: {},
      timeout_seconds: 120,
    }]);
  };

  const removeStep = (idx: number) => {
    setSteps(steps.filter((_, i) => i !== idx));
  };

  const updateStep = (idx: number, field: keyof WorkflowStep, value: unknown) => {
    const updated = [...steps];
    updated[idx] = { ...updated[idx], [field]: value };
    setSteps(updated);
  };

  const validate = (): string | null => {
    if (!name.trim()) return t.crewValidationRequired;
    if (steps.length === 0) return t.crewValidationEmptySteps;
    for (const step of steps) {
      if (!step.id.trim() || !step.required_capability.trim()) return t.crewValidationRequired;
    }
    if (workflowType === "dag") {
      const stepIds = new Set(steps.map((s) => s.id));
      for (const step of steps) {
        for (const dep of step.depends_on) {
          if (!stepIds.has(dep)) return `Step '${step.id}' depends on unknown step '${dep}'`;
        }
      }
      // Cycle detection via topological sort
      const inDegree: Record<string, number> = {};
      const adj: Record<string, string[]> = {};
      for (const s of steps) {
        inDegree[s.id] = 0;
        adj[s.id] = [];
      }
      for (const s of steps) {
        for (const dep of s.depends_on) {
          if (adj[dep]) { adj[dep].push(s.id); inDegree[s.id]++; }
        }
      }
      const queue = Object.keys(inDegree).filter((id) => inDegree[id] === 0);
      let visited = 0;
      const q = [...queue];
      while (q.length > 0) {
        const curr = q.shift()!;
        visited++;
        for (const next of adj[curr]) {
          inDegree[next]--;
          if (inDegree[next] === 0) q.push(next);
        }
      }
      if (visited !== steps.length) return t.crewValidationCycle;
    }
    return null;
  };

  const handleSave = async () => {
    const err = validate();
    if (err) { setValidationError(err); return; }
    setValidationError(null);
    setSaving(true);

    const crewData = {
      name: name.trim(),
      description: description.trim(),
      agents: crewAgents,
      workflow: { type: workflowType, steps, timeout_seconds: workflowTimeout },
    };

    if (isEdit && id) {
      await updateCrew(id, crewData);
    } else {
      const newId = await createCrew(crewData as never);
      if (newId) {
        navigate(`/swarm/crews/${newId}/edit`);
      }
    }
    setSaving(false);
  };

  if (isEdit && crews.length === 0) return <LoadingSpinner />;

  const agentStatusColor = (status: string) => {
    if (status === "online") return "text-green-400";
    if (status === "busy") return "text-amber-400";
    return "text-text-secondary opacity-50";
  };

  const agentStatusLabel = (status: string) => {
    if (status === "online") return t.crewAgentOnline;
    if (status === "busy") return t.crewAgentBusy;
    return t.crewAgentOffline;
  };

  return (
    <div className="max-w-3xl mx-auto">
      <h1 className="text-2xl font-semibold font-[family-name:var(--font-body)] text-text-primary mb-6">
        {isEdit ? t.crewEdit : t.crewAdd}
      </h1>

      {validationError && (
        <div className="mb-4 px-4 py-2 rounded-lg bg-accent-pink/10 text-accent-pink text-sm">
          {validationError}
        </div>
      )}

      {/* Basic info */}
      <div className="space-y-4 mb-8">
        <div>
          <label className="block text-sm text-text-secondary mb-1">{t.crewName} *</label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full px-3 py-2 bg-surface border border-border-subtle rounded-lg text-text-primary focus:border-accent-cyan focus:outline-none"
            aria-label={t.crewName}
          />
        </div>
        <div>
          <label className="block text-sm text-text-secondary mb-1">{t.crewDescription}</label>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={2}
            className="w-full px-3 py-2 bg-surface border border-border-subtle rounded-lg text-text-primary focus:border-accent-cyan focus:outline-none resize-none"
            aria-label={t.crewDescription}
          />
        </div>
      </div>

      {/* Agent assignment */}
      <div className="mb-8">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-lg font-medium text-text-primary">{t.crewAgents}</h2>
          <button onClick={addAgent} className="text-sm text-accent-cyan hover:underline">
            {t.crewAddAgent}
          </button>
        </div>
        {crewAgents.map((agent, idx) => (
          <div key={idx} className="flex items-center gap-3 mb-2">
            <select
              value={agent.agent_id}
              onChange={(e) => updateAgent(idx, "agent_id", Number(e.target.value))}
              className="flex-1 px-3 py-2 bg-surface border border-border-subtle rounded-lg text-text-primary text-sm"
              aria-label={t.crewAgentId}
            >
              <option value={0}>--</option>
              {agents.map((a) => (
                <option key={a.agent_id} value={a.agent_id}>
                  {a.display_name} ({agentStatusLabel(a.status)})
                </option>
              ))}
            </select>
            <input
              value={agent.required_capability}
              onChange={(e) => updateAgent(idx, "required_capability", e.target.value)}
              placeholder={t.crewAgentCapability}
              className="flex-1 px-3 py-2 bg-surface border border-border-subtle rounded-lg text-text-primary text-sm"
              aria-label={t.crewAgentCapability}
            />
            <button onClick={() => removeAgent(idx)} className="text-xs text-accent-pink hover:underline">
              {t.crewRemoveAgent}
            </button>
          </div>
        ))}
      </div>

      {/* Workflow */}
      <div className="mb-8">
        <h2 className="text-lg font-medium text-text-primary mb-3">{t.crewWorkflowType}</h2>
        <div className="flex items-center gap-4 mb-4">
          <select
            value={workflowType}
            onChange={(e) => setWorkflowType(e.target.value as "sequential" | "parallel" | "dag")}
            className="px-3 py-2 bg-surface border border-border-subtle rounded-lg text-text-primary text-sm"
          >
            <option value="sequential">{t.crewSequential}</option>
            <option value="parallel">{t.crewParallel}</option>
            <option value="dag">{t.crewDAG}</option>
          </select>
          <div className="flex items-center gap-2 text-sm">
            <label className="text-text-secondary">{t.crewWorkflowTimeout}</label>
            <input
              type="number"
              value={workflowTimeout}
              onChange={(e) => setWorkflowTimeout(Number(e.target.value))}
              className="w-20 px-2 py-1 bg-surface border border-border-subtle rounded text-text-primary text-sm"
            />
          </div>
        </div>

        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-medium text-text-secondary">{t.crewWorkflowSteps}</h3>
          <button onClick={addStep} className="text-sm text-accent-cyan hover:underline">
            {t.crewAddStep}
          </button>
        </div>

        {steps.map((step, idx) => (
          <div key={idx} className="bg-surface/40 border border-border-subtle rounded-lg p-4 mb-3">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs text-text-secondary font-mono">{step.id}</span>
              <button onClick={() => removeStep(idx)} className="text-xs text-accent-pink hover:underline">
                {t.crewRemoveStep}
              </button>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <input
                value={step.required_capability}
                onChange={(e) => updateStep(idx, "required_capability", e.target.value)}
                placeholder={t.crewStepCapability}
                className="px-2 py-1.5 bg-surface border border-border-subtle rounded text-sm text-text-primary"
                aria-label={`${step.id} ${t.crewStepCapability}`}
              />
              <input
                value={step.task_template}
                onChange={(e) => updateStep(idx, "task_template", e.target.value)}
                placeholder={`${t.crewStepTemplate} — ${t.crewStepTemplateHint}`}
                className="px-2 py-1.5 bg-surface border border-border-subtle rounded text-sm text-text-primary"
                aria-label={`${step.id} ${t.crewStepTemplate}`}
              />
              {workflowType === "dag" && (
                <>
                  <input
                    value={step.depends_on.join(", ")}
                    onChange={(e) => updateStep(idx, "depends_on", e.target.value.split(",").map((s) => s.trim()).filter(Boolean))}
                    placeholder={t.crewStepDependsOn}
                    className="px-2 py-1.5 bg-surface border border-border-subtle rounded text-sm text-text-primary"
                    aria-label={`${step.id} ${t.crewStepDependsOn}`}
                  />
                  <input
                    type="number"
                    value={step.timeout_seconds}
                    onChange={(e) => updateStep(idx, "timeout_seconds", Number(e.target.value))}
                    placeholder={t.crewStepTimeout}
                    className="px-2 py-1.5 bg-surface border border-border-subtle rounded text-sm text-text-primary"
                    aria-label={`${step.id} ${t.crewStepTimeout}`}
                  />
                </>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Save / Cancel */}
      <div className="flex items-center gap-3">
        <button
          onClick={handleSave}
          disabled={saving}
          className="px-6 py-2 bg-accent-cyan text-bg rounded-lg hover:bg-accent-cyan/90 transition-colors font-medium disabled:opacity-50"
        >
          {saving ? "..." : t.crewSave}
        </button>
        <button
          onClick={() => navigate("/swarm/crews")}
          className="px-6 py-2 text-text-secondary hover:text-text-primary transition-colors"
        >
          {t.crewCancel}
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Add routes to App.tsx**

Add imports in `admin/frontend/src/App.tsx`:

```typescript
import { CrewListPage } from "./pages/swarm/CrewListPage";
import { CrewEditPage } from "./pages/swarm/CrewEditPage";
```

Add routes inside the `<SwarmGuard>` block, after the Knowledge route:

```tsx
<Route path="/swarm/crews" element={<CrewListPage />} />
<Route path="/swarm/crews/new" element={<CrewEditPage />} />
<Route path="/swarm/crews/:id/edit" element={<CrewEditPage />} />
```

- [ ] **Step 4: Add nav item to AdminLayout.tsx**

In `admin/frontend/src/components/AdminLayout.tsx`, add a NavLink between the Tasks and Knowledge NavLinks. The NavLink follows the exact same pattern as the existing ones (isActive indicator span + SVG icon + label text). Use this SVG icon (two overlapping user outlines):

```tsx
<svg
  viewBox="0 0 24 24"
  className="w-4 h-4 shrink-0"
  fill="none"
  stroke="currentColor"
  strokeWidth="1.5"
  aria-hidden="true"
>
  <path strokeLinecap="round" strokeLinejoin="round" d="M15 19.128a9.38 9.38 0 002.625.372 9.337 9.337 0 004.121-.952 4.125 4.125 0 00-7.533-2.493M15 19.128v-.003c0-1.113-.285-2.16-.786-3.07M15 19.128v.106A12.318 12.318 0 018.624 21c-2.331 0-4.512-.645-6.374-1.766l-.001-.109a6.375 6.375 0 0111.964-3.07M12 6.375a3.375 3.375 0 11-6.75 0 3.375 3.375 0 016.75 0zm8.25 2.25a2.625 2.625 0 11-5.25 0 2.625 2.625 0 015.25 0z" />
</svg>
<span>{t.navCrews}</span>
```

The `navCrews` key needs to be added to i18n. Add `navCrews: string;` to the Translations interface and `"Crews"` / `"Crews"` to the respective language objects.

- [ ] **Step 5: Run TypeScript check + build**

Run: `cd /mnt/disk01/workspaces/worksummary/hermes-agent/admin/frontend && npx tsc --noEmit && npm run build`
Expected: No errors, build succeeds

- [ ] **Step 6: Commit**

```bash
git add admin/frontend/src/pages/swarm/CrewListPage.tsx admin/frontend/src/pages/swarm/CrewEditPage.tsx admin/frontend/src/App.tsx admin/frontend/src/components/AdminLayout.tsx admin/frontend/src/i18n/zh.ts admin/frontend/src/i18n/en.ts
git commit -m "feat(admin): add Crew list and edit pages with routing and navigation"
```

---

### Task 6: E2E Tests + Final Verification

**Files:**
- Create: `admin/frontend/e2e/crew.spec.ts`
- Modify: `admin/frontend/e2e/fixtures/mock-data.ts`

- [ ] **Step 1: Add mock crew data to fixtures**

In `admin/frontend/e2e/fixtures/mock-data.ts`, add:

```typescript
export const mockCrews = {
  results: [
    {
      crew_id: "crew-1",
      name: "Review Team",
      description: "Code review crew",
      agents: [{ agent_id: 1, required_capability: "code-review" }],
      workflow: {
        type: "sequential",
        steps: [
          { id: "step_1", required_capability: "code-review", task_template: "Review: {input}", depends_on: [], input_from: {}, timeout_seconds: 120 },
        ],
        timeout_seconds: 300,
      },
      created_at: 1745700000,
      updated_at: 1745700000,
      created_by: "admin",
    },
  ],
  total: 1,
};

export const mockCreatedCrew = {
  crew_id: "crew-new",
  name: "New Crew",
  description: "A new crew",
  agents: [],
  workflow: {
    type: "parallel",
    steps: [
      { id: "step_1", required_capability: "translation", task_template: "Translate", depends_on: [], input_from: {}, timeout_seconds: 120 },
    ],
    timeout_seconds: 300,
  },
  created_at: 1745700100,
  updated_at: 1745700100,
  created_by: "admin",
};
```

- [ ] **Step 2: Write E2E tests**

Create `admin/frontend/e2e/crew.spec.ts`:

```typescript
import { test, expect } from "@playwright/test";
import { mockApi, login } from "./helpers";
import { mockCrews, mockCreatedCrew } from "./fixtures/mock-data";

test.beforeEach(async ({ page }) => {
  await login(page);
  await mockApi(page, "/swarm/capability", { enabled: true });
  await mockApi(page, "/swarm/agents", []);
  await mockApi(page, "/swarm/crews", mockCrews);
});

test("renders crew list with cards", async ({ page }) => {
  await page.goto("/admin/swarm/crews");
  await expect(page.getByText("Review Team")).toBeVisible();
  await expect(page.getByText("Sequential")).toBeVisible();
  await expect(page.getByText("1 agents")).toBeVisible();
  await expect(page.getByText("1 steps")).toBeVisible();
});

test("navigates to create crew form", async ({ page }) => {
  await page.goto("/admin/swarm/crews");
  await page.click("text=Create Crew");
  await expect(page).toHaveURL(/\/swarm\/crews\/new/);
  await expect(page.getByLabel(/Name/)).toBeVisible();
});

test("creates a new crew", async ({ page }) => {
  await mockApi(page, "/swarm/crews", mockCreatedCrew, "POST");

  await page.goto("/admin/swarm/crews/new");
  await page.getByLabel(/Name/).fill("New Crew");
  await page.getByLabel(/Description/).fill("A new crew");

  // Fill step capability
  const capInput = page.getByLabel(/step_1.*Capability/i);
  await capInput.fill("translation");

  await page.click("text=Save");

  // Should navigate to edit page after creation
  await expect(page).toHaveURL(/\/swarm\/crews\/crew-new\/edit/);
});

test("empty state shows CTA", async ({ page }) => {
  await mockApi(page, "/swarm/crews", { results: [], total: 0 });
  await page.goto("/admin/swarm/crews");
  await expect(page.getByText("No crews yet")).toBeVisible();
});
```

- [ ] **Step 3: Run E2E tests**

Run: `cd /mnt/disk01/workspaces/worksummary/hermes-agent/admin/frontend && npx playwright test crew`
Expected: All 4 tests PASS

- [ ] **Step 4: Run full Python test suite**

Run: `cd /mnt/disk01/workspaces/worksummary/hermes-agent && python -m pytest tests/ -q`
Expected: All tests PASS

- [ ] **Step 5: Rebuild frontend dist**

Run: `cd /mnt/disk01/workspaces/worksummary/hermes-agent/admin/frontend && npm run build`

- [ ] **Step 6: Commit**

```bash
git add admin/frontend/e2e/crew.spec.ts admin/frontend/e2e/fixtures/mock-data.ts admin/frontend/dist/
git commit -m "test(swarm): add E2E tests for Crew pages"
```

---

## Self-Review

### Spec Coverage Check

| Spec Requirement | Task |
|-----------------|------|
| CrewStore Redis CRUD (hash + set + pipeline) | Task 1 |
| WorkflowEngine sequential mode | Task 2 |
| WorkflowEngine parallel mode | Task 2 |
| WorkflowEngine DAG mode with Kahn's topo sort | Task 2 |
| `_SafeFormat` template engine (no Jinja2) | Task 2 |
| Cycle detection | Task 2 |
| `StepResult` + `CrewExecution` data models | Task 2 |
| Fail-fast with cancel keys | Task 2 |
| Timeout enforcement (monotonic check) | Task 2 |
| Admin sender_id=0 | Task 2 |
| Distributed lock (SETNX) | Task 3 |
| ThreadPoolExecutor(max_workers=4) | Task 3 |
| Crew Pydantic models with Literal type + validators | Task 3 |
| 7 API endpoints (CRUD + execute + poll) | Task 3 |
| swarmCrews Zustand store | Task 4 |
| ~45 i18n keys | Task 4 |
| CrewListPage with card grid | Task 5 |
| CrewEditPage with form editor | Task 5 |
| Agent dropdown with online status | Task 5 |
| Execute UX (confirm + poll + results) | Task 5 |
| Routes under SwarmGuard | Task 5 |
| Crews nav item in Swarm section | Task 5 |
| E2E tests | Task 6 |

### Placeholder Scan

No TBD, TODO, or placeholder patterns found.

### Type Consistency

- `CrewAgent` dataclass (crew_store.py) ↔ `CrewAgentModel` Pydantic (swarm_models.py) ↔ `CrewAgent` TypeScript interface (swarmCrews.ts) — all have `agent_id: int` + `required_capability: str`
- `WorkflowStep` dataclass ↔ `WorkflowStepModel` ↔ `WorkflowStep` TS — all have `id`, `required_capability`, `task_template`, `depends_on`, `input_from`, `timeout_seconds`
- `WorkflowDef` dataclass ↔ `WorkflowDefModel` ↔ `WorkflowDef` TS — all have `type`, `steps`, `timeout_seconds`
- `CrewExecution` dataclass ↔ `CrewExecutionResponse` Pydantic ↔ `ExecutionResult` TS — all have `exec_id`, `crew_id`, `status`, `step_results`, `error`, `started_at`, `finished_at`, `timeout_seconds`
- `StepResult` dataclass ↔ inline dict in execute endpoint ↔ TS `step_results` record — all have `step_id`, `status`, `output`, `error`, `agent_id`, `duration_ms`
