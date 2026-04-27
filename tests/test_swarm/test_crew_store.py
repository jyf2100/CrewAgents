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
