"""Tests for the Hermes Orchestrator REST API endpoints."""

import time

import pytest
from unittest.mock import MagicMock, patch

# Set env vars before importing the module that reads them at import time
import os

os.environ.setdefault("ORCHESTRATOR_API_KEY", "test-api-key")
os.environ.setdefault("GATEWAY_API_KEY", "gw-key")


@pytest.fixture
def client():
    """Create a TestClient with mocked Redis and module globals."""
    with patch("hermes_orchestrator.main._redis.Redis.from_url") as mock_from_url:
        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        mock_from_url.return_value = mock_redis

        # Reload the module so create_app() picks up the mocked Redis
        import importlib
        import hermes_orchestrator.main as main_mod

        importlib.reload(main_mod)

        # Patch module-level globals to mock instances (lifespan doesn't run in TestClient)
        mock_task_store = MagicMock()
        mock_agent_registry = MagicMock()
        main_mod.task_store = mock_task_store
        main_mod.agent_registry = mock_agent_registry
        main_mod.redis_client = mock_redis
        main_mod.circuits = {}

        from fastapi.testclient import TestClient

        tc = TestClient(main_mod.app, raise_server_exceptions=False)
        # Stash references on the test client for tests to use
        tc._main_mod = main_mod  # type: ignore[attr-defined]
        tc._task_store = mock_task_store  # type: ignore[attr-defined]
        tc._agent_registry = mock_agent_registry  # type: ignore[attr-defined]
        yield tc


AUTH_HEADERS = {"Authorization": "Bearer test-api-key"}


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

def test_health_no_auth(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("ok", "degraded")


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def test_submit_task_requires_auth(client):
    resp = client.post("/api/v1/tasks", json={"prompt": "hello"})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Task submission
# ---------------------------------------------------------------------------

def test_submit_task_validates_prompt(client):
    resp = client.post("/api/v1/tasks", json={}, headers=AUTH_HEADERS)
    assert resp.status_code == 422


def test_submit_task_returns_202(client):
    resp = client.post(
        "/api/v1/tasks",
        json={"prompt": "summarize this"},
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 202
    data = resp.json()
    assert "task_id" in data
    assert data["status"] == "queued"
    # Verify store was called
    client._task_store.create.assert_called_once()
    client._task_store.enqueue.assert_called_once()


# ---------------------------------------------------------------------------
# Task retrieval
# ---------------------------------------------------------------------------

def test_get_task_not_found(client):
    client._task_store.get.return_value = None
    resp = client.get("/api/v1/tasks/no-exist", headers=AUTH_HEADERS)
    assert resp.status_code == 404


def test_get_task_found(client):
    from hermes_orchestrator.models.task import Task

    task = Task(
        task_id="abc-123",
        prompt="hello",
        created_at=time.time(),
        status="done",
    )
    client._task_store.get.return_value = task
    resp = client.get("/api/v1/tasks/abc-123", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["task_id"] == "abc-123"
    assert data["status"] == "done"


# ---------------------------------------------------------------------------
# Task listing
# ---------------------------------------------------------------------------

def test_list_tasks_default(client):
    from hermes_orchestrator.models.task import Task

    client._task_store.list_by_status.return_value = [
        Task(task_id="t1", prompt="a", created_at=1000.0, status="queued"),
    ]
    resp = client.get("/api/v1/tasks", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1


def test_list_tasks_by_status(client):
    from hermes_orchestrator.models.task import Task

    client._task_store.list_by_status.return_value = [
        Task(task_id="t2", prompt="b", created_at=1000.0, status="done"),
    ]
    resp = client.get("/api/v1/tasks?status=done", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    # Verify the filter was applied
    client._task_store.list_by_status.assert_called_with(["done"])


# ---------------------------------------------------------------------------
# Task cancellation
# ---------------------------------------------------------------------------

def test_cancel_task_not_found(client):
    client._task_store.get.return_value = None
    resp = client.delete("/api/v1/tasks/nonexistent", headers=AUTH_HEADERS)
    assert resp.status_code == 404


def test_cancel_completed_task_conflict(client):
    from hermes_orchestrator.models.task import Task

    done_task = Task(
        task_id="t1", prompt="test", created_at=time.time(), status="done"
    )
    client._task_store.get.return_value = done_task
    resp = client.delete("/api/v1/tasks/t1", headers=AUTH_HEADERS)
    assert resp.status_code == 409


def test_cancel_executing_task_bad_request(client):
    from hermes_orchestrator.models.task import Task

    executing_task = Task(
        task_id="t3", prompt="test", created_at=time.time(), status="executing"
    )
    client._task_store.get.return_value = executing_task
    resp = client.delete("/api/v1/tasks/t3", headers=AUTH_HEADERS)
    assert resp.status_code == 400


def test_cancel_queued_task(client):
    from hermes_orchestrator.models.task import Task

    queued_task = Task(
        task_id="t2", prompt="test", created_at=time.time(), status="queued"
    )
    client._task_store.get.return_value = queued_task
    resp = client.delete("/api/v1/tasks/t2", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "cancelled"
    client._task_store.update.assert_called_once_with(
        "t2", status="failed", error="Cancelled by user"
    )


# ---------------------------------------------------------------------------
# Agent listing
# ---------------------------------------------------------------------------

def test_list_agents(client):
    client._agent_registry.list_agents.return_value = []
    resp = client.get("/api/v1/agents", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    assert "agents" in resp.json()


# ---------------------------------------------------------------------------
# Agent health
# ---------------------------------------------------------------------------

def test_agent_health_not_found(client):
    client._agent_registry.get.return_value = None
    resp = client.get("/api/v1/agents/no-agent/health", headers=AUTH_HEADERS)
    assert resp.status_code == 404


def test_agent_health_ok(client):
    from hermes_orchestrator.models.agent import AgentProfile

    agent = AgentProfile(
        agent_id="gw-1",
        gateway_url="http://10.0.0.1:8642",
        registered_at=time.time(),
        status="online",
        current_load=2,
        max_concurrent=10,
        last_health_check=time.time(),
    )
    client._agent_registry.get.return_value = agent
    # circuits is an empty dict, so circuit_state defaults to "closed"
    resp = client.get("/api/v1/agents/gw-1/health", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["agent_id"] == "gw-1"
    assert data["status"] == "online"
    assert data["circuit_state"] == "closed"
    assert data["current_load"] == 2
