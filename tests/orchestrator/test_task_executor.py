import json
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from hermes_orchestrator.models.task import Task, RunResult
from hermes_orchestrator.services.task_executor import TaskExecutor

@pytest.fixture
def executor():
    cfg = MagicMock()
    cfg.gateway_headers = {"Authorization": "Bearer test-key"}
    cfg.task_max_wait = 60.0
    return TaskExecutor(cfg)

def test_extract_result_completed(executor):
    event = {"event": "run.completed", "run_id": "run_1", "output": "Hello", "usage": {"total_tokens": 100}}
    task = Task(task_id="t1", prompt="hi", created_at=time.time())
    result = executor.extract_result(event, task)
    assert result.content == "Hello"
    assert result.usage["total_tokens"] == 100
    assert result.run_id == "run_1"
    assert result.duration_seconds > 0

def test_extract_result_empty_output(executor):
    event = {"event": "run.completed", "run_id": "run_2", "output": "", "usage": {}}
    task = Task(task_id="t2", prompt="hi", created_at=time.time())
    result = executor.extract_result(event, task)
    assert result.content == ""
