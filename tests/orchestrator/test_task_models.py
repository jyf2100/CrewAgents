import time

from hermes_orchestrator.models.task import Task, TaskResult, RunResult


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
