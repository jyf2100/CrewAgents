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


def _parse_workflow_step(s: dict[str, Any]) -> WorkflowStep:
    return WorkflowStep(
        id=s["id"],
        required_capability=s["required_capability"],
        task_template=s["task_template"],
        depends_on=s.get("depends_on", []),
        input_from=s.get("input_from", {}),
        timeout_seconds=s.get("timeout_seconds", 120),
    )


def _parse_workflow(d: dict[str, Any]) -> WorkflowDef:
    return WorkflowDef(
        type=d["type"],
        steps=[_parse_workflow_step(s) for s in d.get("steps", [])],
        timeout_seconds=d.get("timeout_seconds", 300),
    )


def _parse_crew(d: dict[str, Any]) -> CrewConfig:
    return CrewConfig(
        crew_id=d["crew_id"],
        name=d["name"],
        description=d["description"],
        agents=[CrewAgent(**a) for a in d.get("agents", [])],
        workflow=_parse_workflow(d["workflow"]),
        created_at=d["created_at"],
        updated_at=d["updated_at"],
        created_by=d.get("created_by", ""),
    )


def _parse_raw(raw: str, crew_id: str = "") -> CrewConfig | None:
    try:
        return _parse_crew(json.loads(raw))
    except (json.JSONDecodeError, ValueError, TypeError, KeyError):
        logger.warning("Failed to parse crew %s", crew_id, exc_info=True)
        return None


class CrewStore:
    """Redis-backed Crew configuration store.

    Key patterns:
      - ``hermes:crew:{crew_id}``  — hash, field ``data`` -> JSON
      - ``hermes:crews:index``     — set of all crew IDs
    """

    _ALLOWED_UPDATE_FIELDS = {"name", "description", "agents", "workflow"}

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
        pipe = self._redis.pipeline(transaction=True)
        pipe.hset(f"hermes:crew:{crew_id}", "data", json.dumps(asdict(crew)))
        pipe.sadd("hermes:crews:index", crew_id)
        pipe.execute()
        return crew

    def get(self, crew_id: str) -> CrewConfig | None:
        raw = self._redis.hget(f"hermes:crew:{crew_id}", "data")
        if not raw:
            return None
        return _parse_raw(raw, crew_id)

    def list_crews(self) -> list[CrewConfig]:
        ids = self._redis.smembers("hermes:crews:index") or set()
        if not ids:
            return []
        pipe = self._redis.pipeline()
        for cid in ids:
            pipe.hget(f"hermes:crew:{cid}", "data")
        raw_results = pipe.execute()
        crews: list[CrewConfig] = []
        for raw in raw_results:
            if raw:
                crew = _parse_raw(raw)
                if crew:
                    crews.append(crew)
        return sorted(crews, key=lambda c: c.created_at, reverse=True)

    def update(self, crew_id: str, updates: dict[str, Any]) -> CrewConfig | None:
        raw = self._redis.hget(f"hermes:crew:{crew_id}", "data")
        if not raw:
            return None
        d = json.loads(raw)
        filtered = {k: v for k, v in updates.items() if k in self._ALLOWED_UPDATE_FIELDS}
        d.update(filtered)
        d["updated_at"] = time.time()
        self._redis.hset(f"hermes:crew:{crew_id}", "data", json.dumps(d))
        return _parse_raw(json.dumps(d), crew_id)

    def delete(self, crew_id: str) -> bool:
        exists = self._redis.hget(f"hermes:crew:{crew_id}", "data")
        if not exists:
            return False
        try:
            pipe = self._redis.pipeline(transaction=True)
            pipe.delete(f"hermes:crew:{crew_id}")
            pipe.srem("hermes:crews:index", crew_id)
            pipe.execute()
        except Exception:
            logger.warning("Crew delete failed for %s", crew_id, exc_info=True)
            return False
        return True
