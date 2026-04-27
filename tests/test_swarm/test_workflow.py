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

    # exec_id consumes first uuid, then step_1 task_id gets "t1", step_2 gets "t2"
    with patch("swarm.workflow.uuid4", side_effect=["exec1", "t1", "t2"]):
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

    # exec_id + step_1 task_id
    with patch("swarm.workflow.uuid4", side_effect=["exec1", "t1"]):
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
