import time

import pytest

from hermes_orchestrator.models.task import Task, TaskResult, RunResult, RoutingInfo


def test_task_defaults():
    t = Task(task_id="t1", prompt="hello", created_at=time.time())
    assert t.status == "submitted"
    assert t.instructions == ""
    assert t.model_id == "hermes-agent"
    assert t.assigned_agent is None
    assert t.run_id is None
    assert t.result is None
    assert t.retry_count == 0
    assert t.max_retries == 2
    assert t.timeout_seconds == 600.0


def test_task_to_dict_roundtrip():
    t = Task(task_id="t1", prompt="hello", created_at=1000.0, updated_at=1000.0)
    d = t.to_dict()
    t2 = Task.from_dict(d)
    assert t2.task_id == t.task_id
    assert t2.prompt == t.prompt
    assert t2.status == t.status


def test_task_result_fields():
    r = TaskResult(
        content="answer",
        usage={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        duration_seconds=1.5,
        run_id="run_abc",
    )
    assert r.content == "answer"
    assert r.usage["total_tokens"] == 15


def test_run_result_completed():
    rr = RunResult(
        run_id="run_abc",
        status="completed",
        output="result text",
        usage={"total_tokens": 100},
    )
    assert rr.status == "completed"
    assert rr.error is None


def test_run_result_failed():
    rr = RunResult(run_id="run_abc", status="failed", error="timeout")
    assert rr.status == "failed"
    assert rr.output == ""


# ===================================================================
# RoutingInfo
# ===================================================================


class TestRoutingInfo:
    """Tests for RoutingInfo dataclass and serialization."""

    def test_routing_info_defaults(self):
        """RoutingInfo basic fields are set correctly."""
        info = RoutingInfo(
            strategy="tag_match",
            chosen_agent_id="agent-1",
            scores={"agent-1": 0.75},
            matched_tags=["python"],
            fallback=False,
            reason="Best match",
        )
        assert info.strategy == "tag_match"
        assert info.chosen_agent_id == "agent-1"
        assert info.scores == {"agent-1": 0.75}
        assert info.matched_tags == ["python"]
        assert info.fallback is False
        assert info.reason == "Best match"
        assert info.shadow_smart_agent_id is None
        assert info.shadow_smart_score is None

    def test_routing_info_with_shadow_fields(self):
        """RoutingInfo shadow fields can be populated."""
        info = RoutingInfo(
            strategy="shadow",
            chosen_agent_id="agent-1",
            scores={"agent-1": 0.8},
            matched_tags=[],
            fallback=False,
            reason="Shadow test",
            shadow_smart_agent_id="agent-2",
            shadow_smart_score=0.9,
        )
        assert info.shadow_smart_agent_id == "agent-2"
        assert info.shadow_smart_score == 0.9


# ===================================================================
# Task roundtrip with RoutingInfo
# ===================================================================


def _make_task(**kwargs) -> Task:
    """Helper to create a Task with sensible defaults."""
    defaults = {
        "task_id": "t-rt",
        "prompt": "test prompt",
        "created_at": 1000.0,
    }
    defaults.update(kwargs)
    return Task(**defaults)


class TestTaskRoutingInfoSerialization:
    """Tests for Task serialization/deserialization with routing_info."""

    def test_task_roundtrip_with_routing_info(self):
        """Task.to_dict() and Task.from_dict() preserve routing_info."""
        info = RoutingInfo(
            strategy="tag_match",
            chosen_agent_id="agent-1",
            scores={"agent-1": 0.75, "agent-2": 0.5},
            matched_tags=["python", "code"],
            fallback=False,
            reason="Best tag match",
        )
        task = _make_task(routing_info=info)
        d = task.to_dict()

        # routing_info should be serialized as a nested dict
        assert isinstance(d["routing_info"], dict)
        assert d["routing_info"]["strategy"] == "tag_match"

        restored = Task.from_dict(d)
        assert restored.routing_info is not None
        assert restored.routing_info.strategy == "tag_match"
        assert restored.routing_info.chosen_agent_id == "agent-1"
        assert restored.routing_info.matched_tags == ["python", "code"]
        assert restored.routing_info.scores == {"agent-1": 0.75, "agent-2": 0.5}
        assert restored.routing_info.fallback is False
        assert restored.routing_info.reason == "Best tag match"

    def test_task_roundtrip_without_routing_info(self):
        """Task without routing_info survives serialization roundtrip."""
        task = _make_task()
        assert task.routing_info is None
        d = task.to_dict()
        restored = Task.from_dict(d)
        assert restored.routing_info is None

    def test_task_roundtrip_with_shadow_routing_info(self):
        """RoutingInfo with shadow fields survives roundtrip."""
        info = RoutingInfo(
            strategy="shadow",
            chosen_agent_id="agent-1",
            scores={"agent-1": 0.8},
            matched_tags=["python"],
            fallback=False,
            reason="Shadow run",
            shadow_smart_agent_id="agent-smart",
            shadow_smart_score=0.95,
        )
        task = _make_task(routing_info=info)
        d = task.to_dict()
        restored = Task.from_dict(d)
        assert restored.routing_info is not None
        assert restored.routing_info.shadow_smart_agent_id == "agent-smart"
        assert restored.routing_info.shadow_smart_score == 0.95

    def test_task_from_dict_malformed_routing_info(self):
        """Malformed routing_info (missing required fields) degrades to None."""
        data = _make_task().to_dict()
        data["routing_info"] = {"strategy": "tag_match"}  # missing required fields
        restored = Task.from_dict(data)
        assert restored.routing_info is None

    def test_task_from_dict_none_routing_info(self):
        """Explicit None routing_info is handled gracefully."""
        data = _make_task().to_dict()
        data["routing_info"] = None
        restored = Task.from_dict(data)
        assert restored.routing_info is None

    def test_task_from_dict_empty_dict_routing_info(self):
        """Empty dict as routing_info degrades to None."""
        data = _make_task().to_dict()
        data["routing_info"] = {}
        restored = Task.from_dict(data)
        assert restored.routing_info is None

    def test_task_roundtrip_preserves_other_fields_with_routing_info(self):
        """All Task fields survive roundtrip when routing_info is present."""
        info = RoutingInfo(
            strategy="least_load",
            chosen_agent_id="a1",
            scores={},
            matched_tags=[],
            fallback=True,
            reason="No tags matched",
        )
        task = _make_task(
            instructions="do something",
            model_id="custom-model",
            priority=5,
            required_tags=["python"],
            routing_info=info,
        )
        d = task.to_dict()
        restored = Task.from_dict(d)
        assert restored.instructions == "do something"
        assert restored.model_id == "custom-model"
        assert restored.priority == 5
        assert restored.required_tags == ["python"]
        assert restored.routing_info.strategy == "least_load"
