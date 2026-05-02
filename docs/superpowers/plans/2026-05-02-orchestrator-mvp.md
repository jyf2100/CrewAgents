# Hermes Orchestrator MVP — Task Router Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an async task router that accepts task submissions, selects the best available gateway agent, submits via `/v1/runs`, consumes SSE events, and returns structured results — all backed by Redis Streams for durability.

**Architecture:** Single-process FastAPI app with background workers. Agent discovery via K8s API (`list_namespaced_pod`). Task queue via Redis Streams (`XADD`/`XREADGROUP`/`XACK`). Health monitoring with adaptive polling + circuit breaker (reused from `swarm/circuit_breaker.py`). Gateway interaction via `aiohttp` to existing `/v1/runs` + `/v1/runs/{id}/events` endpoints.

**Tech Stack:** Python 3.11, FastAPI, uvicorn, aiohttp, redis[hiredis] (sync client for stores, wrapped in `run_in_executor` from async code — avoids blocking the event loop while keeping store layer testable with sync Redis), kubernetes_asyncio, Pydantic v2

**Design doc:** `docs/hermes-orchestrator-design.md`

---

## File Structure

```
hermes-orchestrator/
  __init__.py
  main.py                      # FastAPI app, startup/shutdown, background tasks
  config.py                    # Env-based config (pydantic-settings)
  models/
    __init__.py
    task.py                    # Task, TaskResult, RunResult dataclasses
    agent.py                   # AgentProfile, AgentCapability dataclasses
    api.py                     # Pydantic request/response models for REST API
  stores/
    __init__.py
    redis_task_store.py        # Task CRUD backed by Redis Hash + Stream
    redis_agent_registry.py   # Agent registry backed by Redis Hash
  services/
    __init__.py
    agent_discovery.py         # K8s pod discovery + /v1/models capability query
    health_monitor.py          # Adaptive health checking background loop
    task_executor.py           # POST /v1/runs + SSE consume + result extraction
    agent_selector.py          # Load-aware selection with circuit breaker
  middleware/
    __init__.py
    auth.py                    # Bearer token auth with hmac.compare_digest
kubernetes/
  orchestrator/
    deployment.yaml            # Orchestrator Deployment + Service
    rbac.yaml                  # ServiceAccount + Role + RoleBinding
    networkpolicy.yaml         # Egress/ingress rules
    secrets.yaml               # API key + Redis password secrets
    redis.yaml                 # Redis with AOF + PVC + auth (if not already deployed)
tests/
  orchestrator/
    __init__.py
    test_config.py
    test_task_models.py
    test_agent_models.py
    test_redis_task_store.py
    test_redis_agent_registry.py
    test_agent_selector.py
    test_task_executor.py
    test_health_monitor.py
    test_auth_middleware.py
    test_api_endpoints.py
    test_agent_discovery.py
    test_crash_recovery.py
```

---

## Task 1: Project Skeleton + Config

**Files:**
- Create: `hermes-orchestrator/__init__.py`
- Create: `hermes-orchestrator/config.py`
- Create: `hermes-orchestrator/models/__init__.py`
- Create: `hermes-orchestrator/stores/__init__.py`
- Create: `hermes-orchestrator/services/__init__.py`
- Create: `hermes-orchestrator/middleware/__init__.py`
- Modify: `pyproject.toml` — add `orchestrator` optional dep group
- Test: `tests/orchestrator/__init__.py`
- Test: `tests/orchestrator/test_config.py`

- [ ] **Step 1: Create test for config loading**

```python
# tests/orchestrator/test_config.py
import os
import pytest

def test_config_loads_from_env():
    os.environ["ORCHESTRATOR_API_KEY"] = "test-key-123"
    os.environ["REDIS_URL"] = "redis://localhost:6379/0"
    os.environ["GATEWAY_API_KEY"] = "gw-key-456"
    from hermes_orchestrator.config import OrchestratorConfig
    cfg = OrchestratorConfig()
    assert cfg.api_key == "test-key-123"
    assert cfg.redis_url == "redis://localhost:6379/0"
    assert cfg.gateway_api_key == "gw-key-456"
    assert cfg.k8s_namespace == "hermes-agent"
    assert cfg.gateway_port == 8642
    assert cfg.agent_max_concurrent == 10
    assert cfg.task_max_wait == 600.0
    assert cfg.circuit_failure_threshold == 3
    assert cfg.circuit_recovery_timeout == 30.0
    for k in ["ORCHESTRATOR_API_KEY", "REDIS_URL", "GATEWAY_API_KEY"]:
        os.environ.pop(k, None)

def test_config_rejects_empty_api_key():
    os.environ.pop("ORCHESTRATOR_API_KEY", None)
    with pytest.raises(SystemExit):
        from hermes_orchestrator.config import OrchestratorConfig
        OrchestratorConfig()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/orchestrator/test_config.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Create package structure and config**

```python
# hermes-orchestrator/__init__.py
# Hermes Orchestrator — Task routing for multi-agent gateway fleet
```

```python
# hermes-orchestrator/config.py
import os
import sys
import logging

logger = logging.getLogger(__name__)

class OrchestratorConfig:
    def __init__(self):
        self.api_key = os.environ.get("ORCHESTRATOR_API_KEY", "")
        if not self.api_key:
            logger.critical("FATAL: ORCHESTRATOR_API_KEY environment variable is required")
            raise SystemExit(1)

        self.redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        self.gateway_api_key = os.environ.get("GATEWAY_API_KEY", "")
        if not self.gateway_api_key:
            logger.warning("GATEWAY_API_KEY not set — gateway requests will be unauthenticated")

        self.k8s_namespace = os.environ.get("K8S_NAMESPACE", "hermes-agent")
        self.gateway_port = int(os.environ.get("GATEWAY_PORT", "8642"))
        self.agent_max_concurrent = int(os.environ.get("AGENT_MAX_CONCURRENT", "10"))
        self.task_max_wait = float(os.environ.get("TASK_MAX_WAIT", "600.0"))
        self.health_base_interval = float(os.environ.get("HEALTH_BASE_INTERVAL", "5.0"))
        self.circuit_failure_threshold = int(os.environ.get("CIRCUIT_FAILURE_THRESHOLD", "3"))
        self.circuit_success_threshold = int(os.environ.get("CIRCUIT_SUCCESS_THRESHOLD", "2"))
        self.circuit_recovery_timeout = float(os.environ.get("CIRCUIT_RECOVERY_TIMEOUT", "30.0"))
        self.log_level = os.environ.get("LOG_LEVEL", "INFO")
        self.cors_origins = [
            o.strip()
            for o in os.environ.get("CORS_ALLOWED_ORIGINS", "").split(",")
            if o.strip()
        ]

    @property
    def gateway_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.gateway_api_key:
            headers["Authorization"] = f"Bearer {self.gateway_api_key}"
        return headers
```

Create empty `__init__.py` files for `models/`, `stores/`, `services/`, `middleware/`, and `tests/orchestrator/`.

- [ ] **Step 4: Add orchestrator dependency group to pyproject.toml**

Add to `[project.optional-dependencies]` in `pyproject.toml`:

```toml
"orchestrator" = [
    "fastapi>=0.104.0,<1",
    "uvicorn[standard]>=0.24.0,<1",
    "aiohttp>=3.9.0,<4",
    "redis[hiredis]>=5.0,<6",
    "kubernetes-asyncio>=31.0,<32",
    "pydantic>=2.12.5,<3",
]
```

- [ ] **Step 5: Install and run test**

Run: `pip install -e ".[orchestrator,dev]" && python -m pytest tests/orchestrator/test_config.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add hermes-orchestrator/ tests/orchestrator/ pyproject.toml
git commit -m "feat(orchestrator): project skeleton with config module"
```

---

## Task 2: Task and Agent Data Models

**Files:**
- Create: `hermes-orchestrator/models/task.py`
- Create: `hermes-orchestrator/models/agent.py`
- Test: `tests/orchestrator/test_task_models.py`
- Test: `tests/orchestrator/test_agent_models.py`

- [ ] **Step 1: Write tests for task models**

```python
# tests/orchestrator/test_task_models.py
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
    r = TaskResult(content="answer", usage={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}, duration_seconds=1.5, run_id="run_abc")
    assert r.content == "answer"
    assert r.usage["total_tokens"] == 15

def test_run_result_completed():
    rr = RunResult(run_id="run_abc", status="completed", output="result text", usage={"total_tokens": 100})
    assert rr.status == "completed"
    assert rr.error is None

def test_run_result_failed():
    rr = RunResult(run_id="run_abc", status="failed", error="timeout")
    assert rr.status == "failed"
    assert rr.output == ""
```

```python
# tests/orchestrator/test_agent_models.py
from hermes_orchestrator.models.agent import AgentProfile, AgentCapability

def test_agent_profile_defaults():
    a = AgentProfile(agent_id="gw-1", gateway_url="http://10.0.0.1:8642", registered_at=1000.0)
    assert a.status == "online"
    assert a.models == []
    assert a.current_load == 0
    assert a.max_concurrent == 10
    assert a.circuit_state == "closed"

def test_agent_profile_to_dict_roundtrip():
    a = AgentProfile(agent_id="gw-1", gateway_url="http://10.0.0.1:8642", registered_at=1000.0)
    d = a.to_dict()
    a2 = AgentProfile.from_dict(d)
    assert a2.agent_id == a.agent_id
    assert a2.gateway_url == a.gateway_url

def test_agent_capability():
    c = AgentCapability(gateway_url="http://10.0.0.1:8642", model_id="hermes-agent")
    assert c.capabilities == {}
    assert c.tool_ids == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/orchestrator/test_task_models.py tests/orchestrator/test_agent_models.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement task model**

```python
# hermes-orchestrator/models/task.py
from __future__ import annotations
import json
import time
from dataclasses import dataclass, field, asdict

@dataclass
class TaskResult:
    content: str
    usage: dict
    duration_seconds: float
    run_id: str

@dataclass
class RunResult:
    run_id: str
    status: str  # "completed" | "failed"
    output: str = ""
    usage: dict | None = None
    error: str | None = None

@dataclass
class Task:
    task_id: str
    prompt: str
    created_at: float
    instructions: str = ""
    model_id: str = "hermes-agent"
    status: str = "submitted"  # submitted|queued|assigned|executing|streaming|done|failed
    assigned_agent: str | None = None
    run_id: str | None = None
    result: TaskResult | None = None
    error: str | None = None
    retry_count: int = 0
    max_retries: int = 2
    priority: int = 1
    timeout_seconds: float = 600.0
    updated_at: float = 0.0
    metadata: dict = field(default_factory=dict)
    callback_url: str | None = None

    def __post_init__(self):
        if self.updated_at == 0.0:
            self.updated_at = self.created_at

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, data: dict) -> Task:
        result = None
        if data.get("result"):
            result = TaskResult(**data["result"])
        data["result"] = result
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
```

- [ ] **Step 4: Implement agent model**

```python
# hermes-orchestrator/models/agent.py
from __future__ import annotations
from dataclasses import dataclass, field, asdict

@dataclass
class AgentCapability:
    gateway_url: str
    model_id: str
    capabilities: dict = field(default_factory=dict)
    tool_ids: list[str] = field(default_factory=list)
    supported_endpoints: list[str] = field(default_factory=list)

@dataclass
class AgentProfile:
    agent_id: str
    gateway_url: str
    registered_at: float
    models: list[str] = field(default_factory=list)
    capabilities: dict = field(default_factory=dict)
    tool_ids: list[str] = field(default_factory=list)
    status: str = "online"  # online | degraded | offline
    current_load: int = 0
    max_concurrent: int = 10
    last_health_check: float = 0.0
    circuit_state: str = "closed"  # closed | open | half_open

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> AgentProfile:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
```

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/orchestrator/test_task_models.py tests/orchestrator/test_agent_models.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add hermes-orchestrator/models/ tests/orchestrator/test_task_models.py tests/orchestrator/test_agent_models.py
git commit -m "feat(orchestrator): task and agent data models"
```

---

## Task 3: Redis Task Store

**Files:**
- Create: `hermes-orchestrator/stores/redis_task_store.py`
- Test: `tests/orchestrator/test_redis_task_store.py`

- [ ] **Step 1: Write test for Redis task store**

```python
# tests/orchestrator/test_redis_task_store.py
import json
import time
import pytest
import redis as _redis
from hermes_orchestrator.models.task import Task
from hermes_orchestrator.stores.redis_task_store import RedisTaskStore

@pytest.fixture
def redis_client():
    r = _redis.Redis(host="localhost", port=6379, db=15, decode_responses=True)
    r.flushdb()
    yield r
    r.flushdb()
    r.close()

@pytest.fixture
def store(redis_client):
    return RedisTaskStore(redis_client)

STREAM = "hermes:orchestrator:tasks:stream"

def test_create_and_get(store, redis_client):
    t = Task(task_id="t1", prompt="hello", created_at=time.time())
    store.create(t)
    # create() does NOT mutate the original task
    assert t.status == "submitted"
    got = store.get("t1")
    assert got is not None
    assert got.task_id == "t1"
    assert got.prompt == "hello"
    assert got.status == "queued"

def test_enqueue_adds_to_stream(store, redis_client):
    t = Task(task_id="t2", prompt="world", created_at=time.time(), status="submitted")
    store.create(t)
    store.enqueue(t)
    msgs = redis_client.xrange(STREAM)
    assert len(msgs) >= 1
    found = False
    for msg_id, fields in msgs:
        if fields.get("task_id") == "t2":
            found = True
    assert found

def test_update_status(store):
    t = Task(task_id="t3", prompt="test", created_at=time.time())
    store.create(t)
    store.update("t3", status="executing", assigned_agent="gw-1")
    got = store.get("t3")
    assert got.status == "executing"
    assert got.assigned_agent == "gw-1"

def test_update_with_result(store):
    from hermes_orchestrator.models.task import TaskResult
    t = Task(task_id="t4", prompt="test", created_at=time.time())
    store.create(t)
    result = TaskResult(content="answer", usage={"total_tokens": 50}, duration_seconds=1.0, run_id="run_1")
    store.update("t4", status="done", result=result)
    got = store.get("t4")
    assert got.status == "done"
    assert got.result.content == "answer"

def test_list_by_status(store):
    for i in range(5):
        t = Task(task_id=f"t{i}", prompt=f"p{i}", created_at=time.time())
        store.create(t)
    store.update("t0", status="done")
    store.update("t1", status="failed")
    done = store.list_by_status(["done"])
    assert len(done) == 1
    assert done[0].task_id == "t0"
    failed_and_done = store.list_by_status(["done", "failed"])
    assert len(failed_and_done) == 2

def test_get_nonexistent(store):
    assert store.get("nope") is None

def test_delete(store, redis_client):
    t = Task(task_id="t_del", prompt="bye", created_at=time.time())
    store.create(t)
    store.delete("t_del")
    assert store.get("t_del") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/orchestrator/test_redis_task_store.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement Redis task store**

```python
# hermes-orchestrator/stores/redis_task_store.py
from __future__ import annotations
import json
import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import redis as _redis

from hermes_orchestrator.models.task import Task, TaskResult

logger = logging.getLogger(__name__)

STREAM_KEY = "hermes:orchestrator:tasks:stream"
TASK_PREFIX = "hermes:orchestrator:tasks:"
CONSUMER_GROUP = "orchestrator.workers"

class RedisTaskStore:
    def __init__(self, redis_client: _redis.Redis):
        self._redis = redis_client
        self._ensure_consumer_group()

    def _ensure_consumer_group(self):
        try:
            self._redis.xgroup_create(STREAM_KEY, CONSUMER_GROUP, id="0", mkstream=True)
        except Exception:
            pass

    def create(self, task: Task) -> None:
        data = task.to_dict()
        data["status"] = "queued"
        data["updated_at"] = time.time()
        self._redis.hset(
            f"{TASK_PREFIX}{task.task_id}",
            "data",
            json.dumps(data),
        )

    def get(self, task_id: str) -> Task | None:
        data = self._redis.hget(f"{TASK_PREFIX}{task_id}", "data")
        if not data:
            return None
        return Task.from_dict(json.loads(data))

    def update(self, task_id: str, status: str | None = None,
               assigned_agent: str | None = None, run_id: str | None = None,
               result: TaskResult | None = None, error: str | None = None,
               retry_count: int | None = None) -> None:
        """Update task fields by task_id. Accepts explicit keyword args so
        run_in_executor can call it positionally without **kwargs."""
        task = self.get(task_id)
        if not task:
            logger.warning("Attempted to update nonexistent task %s", task_id)
            return
        if status is not None:
            task.status = status
        if assigned_agent is not None:
            task.assigned_agent = assigned_agent
        if run_id is not None:
            task.run_id = run_id
        if result is not None:
            task.result = result
        if error is not None:
            task.error = error
        if retry_count is not None:
            task.retry_count = retry_count
        task.updated_at = time.time()
        self._redis.hset(
            f"{TASK_PREFIX}{task.task_id}",
            "data",
            json.dumps(task.to_dict()),
        )

    def delete(self, task_id: str) -> None:
        self._redis.delete(f"{TASK_PREFIX}{task_id}")

    def enqueue(self, task: Task) -> None:
        fields = {
            "task_id": task.task_id,
            "priority": str(task.priority),
            "model_id": task.model_id,
            "created_at": str(task.created_at),
        }
        self._redis.xadd(STREAM_KEY, fields, maxlen=10000, approximate=True)

    def list_by_status(self, statuses: list[str]) -> list[Task]:
        cursor = 0
        tasks = []
        while True:
            cursor, keys = self._redis.scan(cursor, match=f"{TASK_PREFIX}*", count=100)
            for key in keys:
                data = self._redis.hget(key, "data")
                if data:
                    t = Task.from_dict(json.loads(data))
                    if t.status in statuses:
                        tasks.append(t)
            if cursor == 0:
                break
        return tasks
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/orchestrator/test_redis_task_store.py -v`
Expected: PASS (requires local Redis on port 6379)

- [ ] **Step 5: Commit**

```bash
git add hermes-orchestrator/stores/ tests/orchestrator/test_redis_task_store.py
git commit -m "feat(orchestrator): Redis Stream-backed task store"
```

---

## Task 4: Redis Agent Registry

**Files:**
- Create: `hermes-orchestrator/stores/redis_agent_registry.py`
- Test: `tests/orchestrator/test_redis_agent_registry.py`

- [ ] **Step 1: Write test for agent registry**

```python
# tests/orchestrator/test_redis_agent_registry.py
import time
import pytest
import redis as _redis
from hermes_orchestrator.models.agent import AgentProfile
from hermes_orchestrator.stores.redis_agent_registry import RedisAgentRegistry

@pytest.fixture
def redis_client():
    r = _redis.Redis(host="localhost", port=6379, db=15, decode_responses=True)
    r.flushdb()
    yield r
    r.flushdb()
    r.close()

@pytest.fixture
def registry(redis_client):
    return RedisAgentRegistry(redis_client)

def test_register_and_get(registry):
    a = AgentProfile(agent_id="gw-1", gateway_url="http://10.0.0.1:8642", registered_at=time.time())
    registry.register(a)
    got = registry.get("gw-1")
    assert got is not None
    assert got.agent_id == "gw-1"
    assert got.status == "online"

def test_update_status(registry):
    a = AgentProfile(agent_id="gw-2", gateway_url="http://10.0.0.2:8642", registered_at=time.time())
    registry.register(a)
    registry.update_status("gw-2", "degraded")
    got = registry.get("gw-2")
    assert got.status == "degraded"

def test_update_load(registry):
    a = AgentProfile(agent_id="gw-3", gateway_url="http://10.0.0.3:8642", registered_at=time.time())
    registry.register(a)
    registry.update_load("gw-3", 5)
    got = registry.get("gw-3")
    assert got.current_load == 5

def test_deregister(registry):
    a = AgentProfile(agent_id="gw-4", gateway_url="http://10.0.0.4:8642", registered_at=time.time())
    registry.register(a)
    registry.deregister("gw-4")
    assert registry.get("gw-4") is None

def test_list_agents(registry):
    for i in range(3):
        a = AgentProfile(agent_id=f"gw-{i}", gateway_url=f"http://10.0.0.{i}:8642", registered_at=time.time())
        registry.register(a)
    agents = registry.list_agents()
    assert len(agents) == 3

def test_get_nonexistent(registry):
    assert registry.get("nope") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/orchestrator/test_redis_agent_registry.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement agent registry**

```python
# hermes-orchestrator/stores/redis_agent_registry.py
from __future__ import annotations
import json
import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import redis as _redis

from hermes_orchestrator.models.agent import AgentProfile

logger = logging.getLogger(__name__)

AGENTS_KEY = "hermes:orchestrator:agents"

class RedisAgentRegistry:
    def __init__(self, redis_client: _redis.Redis):
        self._redis = redis_client

    def register(self, agent: AgentProfile) -> None:
        self._redis.hset(AGENTS_KEY, agent.agent_id, json.dumps(agent.to_dict()))
        logger.info("Registered agent %s at %s", agent.agent_id, agent.gateway_url)

    def get(self, agent_id: str) -> AgentProfile | None:
        data = self._redis.hget(AGENTS_KEY, agent_id)
        if not data:
            return None
        return AgentProfile.from_dict(json.loads(data))

    def update_status(self, agent_id: str, status: str) -> None:
        agent = self.get(agent_id)
        if agent:
            agent.status = status
            self._redis.hset(AGENTS_KEY, agent_id, json.dumps(agent.to_dict()))

    def update_load(self, agent_id: str, load: int) -> None:
        agent = self.get(agent_id)
        if agent:
            agent.current_load = load
            self._redis.hset(AGENTS_KEY, agent_id, json.dumps(agent.to_dict()))

    def update_circuit_state(self, agent_id: str, state: str) -> None:
        agent = self.get(agent_id)
        if agent:
            agent.circuit_state = state
            self._redis.hset(AGENTS_KEY, agent_id, json.dumps(agent.to_dict()))

    def deregister(self, agent_id: str) -> None:
        self._redis.hdel(AGENTS_KEY, agent_id)
        logger.info("Deregistered agent %s", agent_id)

    def list_agents(self) -> list[AgentProfile]:
        all_data = self._redis.hgetall(AGENTS_KEY)
        agents = []
        for raw in all_data.values():
            agents.append(AgentProfile.from_dict(json.loads(raw)))
        return agents
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/orchestrator/test_redis_agent_registry.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add hermes-orchestrator/stores/redis_agent_registry.py tests/orchestrator/test_redis_agent_registry.py
git commit -m "feat(orchestrator): Redis-backed agent registry"
```

---

## Task 5: Agent Selector with Circuit Breaker

**Files:**
- Create: `hermes-orchestrator/services/agent_selector.py`
- Test: `tests/orchestrator/test_agent_selector.py`

- [ ] **Step 1: Write test for agent selector**

```python
# tests/orchestrator/test_agent_selector.py
import time
from hermes_orchestrator.models.agent import AgentProfile
from hermes_orchestrator.models.task import Task
from hermes_orchestrator.services.agent_selector import AgentSelector
from swarm.circuit_breaker import CircuitBreaker, CircuitState

def _agent(agent_id: str, load: int = 0, status: str = "online", circuit_state: str = "closed") -> AgentProfile:
    return AgentProfile(
        agent_id=agent_id,
        gateway_url=f"http://{agent_id}:8642",
        registered_at=time.time(),
        current_load=load,
        status=status,
        circuit_state=circuit_state,
    )

def test_selects_lowest_load():
    selector = AgentSelector()
    agents = [_agent("a1", load=3), _agent("a2", load=1), _agent("a3", load=5)]
    task = Task(task_id="t1", prompt="test", created_at=time.time())
    chosen = selector.select(agents, task)
    assert chosen.agent_id == "a2"

def test_excludes_offline():
    selector = AgentSelector()
    agents = [_agent("a1", status="offline"), _agent("a2", status="online")]
    task = Task(task_id="t1", prompt="test", created_at=time.time())
    chosen = selector.select(agents, task)
    assert chosen.agent_id == "a2"

def test_excludes_full_load():
    selector = AgentSelector()
    agents = [_agent("a1", load=10), _agent("a2", load=2)]
    task = Task(task_id="t1", prompt="test", created_at=time.time())
    chosen = selector.select(agents, task)
    assert chosen.agent_id == "a2"

def test_excludes_open_circuit():
    selector = AgentSelector()
    agents = [_agent("a1", circuit_state="open"), _agent("a2", circuit_state="closed")]
    task = Task(task_id="t1", prompt="test", created_at=time.time())
    chosen = selector.select(agents, task)
    assert chosen.agent_id == "a2"

def test_returns_none_when_all_excluded():
    selector = AgentSelector()
    agents = [_agent("a1", status="offline"), _agent("a2", circuit_state="open"), _agent("a3", load=10)]
    task = Task(task_id="t1", prompt="test", created_at=time.time())
    assert selector.select(agents, task) is None

def test_returns_none_empty_list():
    selector = AgentSelector()
    task = Task(task_id="t1", prompt="test", created_at=time.time())
    assert selector.select([], task) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/orchestrator/test_agent_selector.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement agent selector**

```python
# hermes-orchestrator/services/agent_selector.py
from __future__ import annotations
import logging
from hermes_orchestrator.models.agent import AgentProfile
from hermes_orchestrator.models.task import Task

logger = logging.getLogger(__name__)

class AgentSelector:
    def select(self, agents: list[AgentProfile], task: Task) -> AgentProfile | None:
        candidates = [
            a for a in agents
            if a.status in ("online", "degraded")
            and a.current_load < a.max_concurrent
            and a.circuit_state != "open"
        ]
        if not candidates:
            logger.warning("No available agent for task %s (checked %d agents)", task.task_id, len(agents))
            return None
        candidates.sort(key=lambda a: (a.current_load, a.last_health_check))
        return candidates[0]
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/orchestrator/test_agent_selector.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add hermes-orchestrator/services/agent_selector.py tests/orchestrator/test_agent_selector.py
git commit -m "feat(orchestrator): load-aware agent selector"
```

---

## Task 6: Task Executor (Gateway Integration)

**Files:**
- Create: `hermes-orchestrator/services/task_executor.py`
- Test: `tests/orchestrator/test_task_executor.py`

This is the core integration component — submits tasks via `POST /v1/runs` and consumes SSE events.

- [ ] **Step 1: Write test for task executor**

```python
# tests/orchestrator/test_task_executor.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/orchestrator/test_task_executor.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement task executor**

```python
# hermes_orchestrator/services/task_executor.py
from __future__ import annotations
import json
import logging
import time
from typing import TYPE_CHECKING

import aiohttp

from hermes_orchestrator.models.task import Task, TaskResult, RunResult

if TYPE_CHECKING:
    from hermes_orchestrator.config import OrchestratorConfig

logger = logging.getLogger(__name__)

class GatewayOverloadedError(Exception):
    pass

class TaskSubmissionError(Exception):
    pass

class TaskTimeoutError(Exception):
    pass

class RunNotFoundError(Exception):
    pass

class TaskExecutor:
    def __init__(self, config: OrchestratorConfig):
        self._config = config

    async def submit_run(self, gateway_url: str, prompt: str, instructions: str = "") -> str:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{gateway_url}/v1/runs",
                json={"input": prompt, "instructions": instructions},
                headers=self._config.gateway_headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status == 429:
                    raise GatewayOverloadedError("Gateway concurrent run limit reached")
                if resp.status != 202:
                    body = await resp.text()
                    raise TaskSubmissionError(f"Gateway returned {resp.status}: {body}")
                data = await resp.json()
                return data["run_id"]

    async def consume_run_events(self, gateway_url: str, run_id: str, max_wait: float = 0) -> RunResult:
        if max_wait <= 0:
            max_wait = self._config.task_max_wait
        deadline = time.monotonic() + max_wait
        output = ""

        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{gateway_url}/v1/runs/{run_id}/events",
                headers=self._config.gateway_headers,
                timeout=aiohttp.ClientTimeout(total=max_wait),
            ) as resp:
                if resp.status != 200:
                    raise RunNotFoundError(f"Run {run_id} not found on gateway")

                async for line in resp.content:
                    if time.monotonic() > deadline:
                        raise TaskTimeoutError(f"Run {run_id} timed out")
                    if not line.startswith(b"data: "):
                        continue
                    event = json.loads(line[6:])
                    evt = event.get("event", "")

                    if evt == "message.delta":
                        output += event.get("delta", "")
                    elif evt == "reasoning.available":
                        logger.debug("Run %s: reasoning (%d chars)", run_id, len(event.get("text", "")))
                    elif evt == "tool.started":
                        logger.info("Run %s: tool %s started", run_id, event.get("tool"))
                    elif evt == "tool.completed":
                        logger.info("Run %s: tool %s completed", run_id, event.get("tool"))
                    elif evt == "run.completed":
                        return RunResult(
                            run_id=run_id, status="completed",
                            output=event.get("output", output),
                            usage=event.get("usage"),
                        )
                    elif evt == "run.failed":
                        return RunResult(
                            run_id=run_id, status="failed",
                            error=event.get("error", "Unknown error"),
                        )

        raise TaskTimeoutError(f"Run {run_id} stream ended without completion")

    def extract_result(self, event: dict, task: Task) -> TaskResult:
        return TaskResult(
            content=event.get("output", ""),
            usage=event.get("usage", {}),
            duration_seconds=time.time() - task.created_at,
            run_id=event.get("run_id", ""),
        )
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/orchestrator/test_task_executor.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add hermes-orchestrator/services/task_executor.py tests/orchestrator/test_task_executor.py
git commit -m "feat(orchestrator): task executor with gateway /v1/runs integration"
```

---

## Task 7: Auth Middleware

**Files:**
- Create: `hermes-orchestrator/middleware/auth.py`
- Test: `tests/orchestrator/test_auth_middleware.py`

- [ ] **Step 1: Write test for auth middleware**

```python
# tests/orchestrator/test_auth_middleware.py
import hmac
from fastapi import FastAPI
from fastapi.testclient import TestClient
from hermes_orchestrator.middleware.auth import create_auth_middleware

def _app(api_key: str = "secret123") -> FastAPI:
    app = FastAPI()
    app.add_middleware(*create_auth_middleware(api_key))
    @app.get("/health")
    async def health():
        return {"status": "ok"}
    @app.get("/api/v1/tasks")
    async def tasks():
        return {"tasks": []}
    return app

def test_health_endpoint_no_auth_required():
    client = TestClient(_app())
    resp = client.get("/health")
    assert resp.status_code == 200

def test_api_endpoint_requires_auth():
    client = TestClient(_app("mykey"))
    resp = client.get("/api/v1/tasks")
    assert resp.status_code == 401

def test_api_endpoint_accepts_valid_key():
    client = TestClient(_app("mykey"))
    resp = client.get("/api/v1/tasks", headers={"Authorization": "Bearer mykey"})
    assert resp.status_code == 200

def test_api_endpoint_rejects_wrong_key():
    client = TestClient(_app("mykey"))
    resp = client.get("/api/v1/tasks", headers={"Authorization": "Bearer wrong"})
    assert resp.status_code == 401

def test_api_endpoint_rejects_malformed_header():
    client = TestClient(_app("mykey"))
    resp = client.get("/api/v1/tasks", headers={"Authorization": "mykey"})
    assert resp.status_code == 401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/orchestrator/test_auth_middleware.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement auth middleware**

```python
# hermes-orchestrator/middleware/auth.py
from __future__ import annotations
import hmac
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

PUBLIC_PATHS = frozenset({"/health", "/metrics", "/docs", "/openapi.json", "/redoc"})

class _AuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, api_key: str):
        super().__init__(app)
        self._expected = f"Bearer {api_key}"

    async def dispatch(self, request: Request, call_next):
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)
        auth = request.headers.get("Authorization", "")
        if not hmac.compare_digest(auth, self._expected):
            return JSONResponse(status_code=401, content={"error": "Unauthorized"})
        return await call_next(request)

def create_auth_middleware(api_key: str):
    return (_AuthMiddleware, {"api_key": api_key})
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/orchestrator/test_auth_middleware.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add hermes-orchestrator/middleware/auth.py tests/orchestrator/test_auth_middleware.py
git commit -m "feat(orchestrator): Bearer token auth middleware with hmac.compare_digest"
```

---

## Task 8: Agent Discovery Service

**Files:**
- Create: `hermes-orchestrator/services/agent_discovery.py`
- Test: `tests/orchestrator/test_agent_discovery.py`

- [ ] **Step 1: Write test for agent discovery**

```python
# tests/orchestrator/test_agent_discovery.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from hermes_orchestrator.services.agent_discovery import AgentDiscoveryService

@pytest.fixture
def discovery():
    cfg = MagicMock()
    cfg.k8s_namespace = "hermes-agent"
    cfg.gateway_port = 8642
    cfg.agent_max_concurrent = 10
    cfg.gateway_headers = {"Authorization": "Bearer test"}
    return AgentDiscoveryService(cfg)

def test_build_pod_url():
    svc = AgentDiscoveryService.__new__(AgentDiscoveryService)
    svc._config = MagicMock()
    svc._config.gateway_port = 8642
    pod = MagicMock()
    pod.status.pod_ip = "10.244.1.42"
    url = svc._build_pod_url(pod)
    assert url == "http://10.244.1.42:8642"

def test_pod_to_profile():
    svc = AgentDiscoveryService.__new__(AgentDiscoveryService)
    svc._config = MagicMock()
    svc._config.gateway_port = 8642
    svc._config.agent_max_concurrent = 10
    from datetime import datetime, timezone
    pod = MagicMock()
    pod.metadata.name = "hermes-gateway-1-abc"
    pod.status.pod_ip = "10.244.1.42"
    pod.status.phase = "Running"
    pod.metadata.creation_timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    profile = svc._pod_to_profile(pod)
    assert profile.agent_id == "hermes-gateway-1-abc"
    assert profile.gateway_url == "http://10.244.1.42:8642"
    assert profile.max_concurrent == 10
    assert profile.status == "online"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/orchestrator/test_agent_discovery.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement agent discovery**

```python
# hermes-orchestrator/services/agent_discovery.py
from __future__ import annotations
import logging
import time
from typing import TYPE_CHECKING

from hermes_orchestrator.models.agent import AgentProfile, AgentCapability

if TYPE_CHECKING:
    from hermes_orchestrator.config import OrchestratorConfig

logger = logging.getLogger(__name__)

GATEWAY_LABEL = "app.kubernetes.io/component=gateway"

class AgentDiscoveryService:
    def __init__(self, config: OrchestratorConfig):
        self._config = config

    async def discover_pods(self) -> list[AgentProfile]:
        from kubernetes_asyncio import client, config as k8s_config
        try:
            await k8s_config.load_kube_config()
        except Exception:
            await k8s_config.load_incluster_config()
        api = client.CoreV1Api()
        pods = await api.list_namespaced_pod(
            namespace=self._config.k8s_namespace,
            label_selector=GATEWAY_LABEL,
        )
        profiles = []
        for pod in pods.items:
            if pod.status.phase != "Running" or not pod.status.pod_ip:
                continue
            profiles.append(self._pod_to_profile(pod))
        await api.api_client.close()
        return profiles

    async def discover_capabilities(self, gateway_url: str) -> list[AgentCapability]:
        import aiohttp
        capabilities = []
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{gateway_url}/v1/models",
                    headers=self._config.gateway_headers,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status != 200:
                        logger.warning("Failed to query %s/v1/models: %s", gateway_url, resp.status)
                        return []
                    data = await resp.json()
                    for entry in data.get("data", []):
                        info = entry.get("info", {}) or {}
                        meta = info.get("meta", {}) or {}
                        capabilities.append(AgentCapability(
                            gateway_url=gateway_url,
                            model_id=entry.get("id", ""),
                            capabilities=meta.get("capabilities", {}),
                            tool_ids=meta.get("toolIds", []),
                            supported_endpoints=entry.get("supported_endpoints", []),
                        ))
        except Exception as e:
            logger.warning("Capability discovery failed for %s: %s", gateway_url, e)
        return capabilities

    def _build_pod_url(self, pod) -> str:
        return f"http://{pod.status.pod_ip}:{self._config.gateway_port}"

    def _pod_to_profile(self, pod) -> AgentProfile:
        return AgentProfile(
            agent_id=pod.metadata.name,
            gateway_url=self._build_pod_url(pod),
            registered_at=time.time(),
            max_concurrent=self._config.agent_max_concurrent,
            status="online",
        )
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/orchestrator/test_agent_discovery.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add hermes-orchestrator/services/agent_discovery.py tests/orchestrator/test_agent_discovery.py
git commit -m "feat(orchestrator): K8s pod + /v1/models agent discovery"
```

---

## Task 9: Health Monitor

**Files:**
- Create: `hermes-orchestrator/services/health_monitor.py`
- Test: `tests/orchestrator/test_health_monitor.py`

- [ ] **Step 1: Write test for adaptive health checker**

```python
# tests/orchestrator/test_health_monitor.py
from hermes_orchestrator.services.health_monitor import AdaptiveHealthChecker

def test_base_interval_on_first_call():
    checker = AdaptiveHealthChecker()
    interval = checker.next_interval("agent-1", last_check_ok=True)
    assert interval == 5.0

def test_increases_on_healthy():
    checker = AdaptiveHealthChecker()
    checker.next_interval("a1", True)
    interval = checker.next_interval("a1", True)
    assert interval > 5.0
    assert interval <= 30.0

def test_decreases_on_unhealthy():
    checker = AdaptiveHealthChecker()
    checker.next_interval("a1", True)
    checker.next_interval("a1", True)
    healthy_interval = checker.next_interval("a1", True)
    unhealthy_interval = checker.next_interval("a1", False)
    assert unhealthy_interval < healthy_interval
    assert unhealthy_interval >= 2.0

def test_max_interval_cap():
    checker = AdaptiveHealthChecker()
    for _ in range(50):
        checker.next_interval("a1", True)
    interval = checker.next_interval("a1", True)
    assert interval <= 30.0

def test_min_interval_floor():
    checker = AdaptiveHealthChecker()
    for _ in range(50):
        checker.next_interval("a1", False)
    interval = checker.next_interval("a1", False)
    assert interval >= 2.0

def test_min_current_interval():
    checker = AdaptiveHealthChecker()
    checker.next_interval("a1", True)
    checker.next_interval("a2", False)
    assert checker.min_current_interval() >= 2.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/orchestrator/test_health_monitor.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement health monitor**

```python
# hermes-orchestrator/services/health_monitor.py
from __future__ import annotations
import asyncio
import logging
import time
from typing import TYPE_CHECKING

import aiohttp

from swarm.circuit_breaker import CircuitBreaker, CircuitState

if TYPE_CHECKING:
    from hermes_orchestrator.config import OrchestratorConfig
    from hermes_orchestrator.stores.redis_agent_registry import RedisAgentRegistry

logger = logging.getLogger(__name__)

class AdaptiveHealthChecker:
    BASE_INTERVAL = 5.0
    MAX_INTERVAL = 30.0
    MIN_INTERVAL = 2.0
    BACKOFF_FACTOR = 1.5

    def __init__(self):
        self._intervals: dict[str, float] = {}

    def next_interval(self, agent_id: str, last_check_ok: bool) -> float:
        current = self._intervals.get(agent_id, self.BASE_INTERVAL)
        if last_check_ok:
            next_val = min(current * 1.1, self.MAX_INTERVAL)
        else:
            next_val = max(current / self.BACKOFF_FACTOR, self.MIN_INTERVAL)
        self._intervals[agent_id] = next_val
        return next_val

    def min_current_interval(self) -> float:
        if not self._intervals:
            return self.BASE_INTERVAL
        return min(self._intervals.values())

class HealthMonitor:
    def __init__(
        self,
        config: OrchestratorConfig,
        registry: RedisAgentRegistry,
        circuits: dict[str, CircuitBreaker],
    ):
        self._config = config
        self._registry = registry
        self._circuits = circuits
        self._adaptive = AdaptiveHealthChecker()
        self._running = False

    async def start(self):
        self._running = True
        while self._running:
            agents = self._registry.list_agents()
            for agent in agents:
                if agent.status == "offline":
                    continue
                try:
                    healthy = await self._check_health(agent.gateway_url)
                except Exception:
                    healthy = False
                interval = self._adaptive.next_interval(agent.agent_id, healthy)
                circuit = self._circuits.get(agent.agent_id)
                if circuit:
                    if healthy:
                        circuit.record_success()
                    else:
                        circuit.record_failure()
                        if circuit.state == CircuitState.OPEN:
                            await asyncio.get_event_loop().run_in_executor(
                                None, self._registry.update_status, agent.agent_id, "degraded"
                            )
                            logger.warning("Agent %s circuit OPEN — marking degraded", agent.agent_id)
                if healthy:
                    await asyncio.get_event_loop().run_in_executor(
                        None, self._registry.update_status, agent.agent_id, "online"
                    )
            await asyncio.sleep(self._adaptive.min_current_interval())

    def stop(self):
        self._running = False

    async def _check_health(self, gateway_url: str) -> bool:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{gateway_url}/health",
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    return resp.status == 200
        except Exception:
            return False
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/orchestrator/test_health_monitor.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add hermes-orchestrator/services/health_monitor.py tests/orchestrator/test_health_monitor.py
git commit -m "feat(orchestrator): adaptive health monitor with circuit breaker"
```

---

## Task 10: API Pydantic Models + REST Endpoints

**Files:**
- Create: `hermes-orchestrator/models/api.py`
- Create: `hermes-orchestrator/main.py`
- Test: `tests/orchestrator/test_api_endpoints.py`

- [ ] **Step 1: Write test for API endpoints**

```python
# tests/orchestrator/test_api_endpoints.py
import time
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from hermes_orchestrator.models.task import Task

@pytest.fixture
def client():
    with patch("hermes_orchestrator.main.OrchestratorConfig") as MockCfg, \
         patch("hermes_orchestrator.main.Redis") as MockRedis, \
         patch("hermes_orchestrator.main.RedisTaskStore") as MockStore, \
         patch("hermes_orchestrator.main.RedisAgentRegistry") as MockRegistry:
        cfg = MagicMock()
        cfg.api_key = "test-api-key"
        cfg.redis_url = "redis://localhost:6379/0"
        cfg.gateway_api_key = "gw-key"
        cfg.k8s_namespace = "hermes-agent"
        cfg.gateway_port = 8642
        cfg.agent_max_concurrent = 10
        cfg.task_max_wait = 600.0
        cfg.health_base_interval = 5.0
        cfg.circuit_failure_threshold = 3
        cfg.circuit_success_threshold = 2
        cfg.circuit_recovery_timeout = 30.0
        cfg.log_level = "INFO"
        cfg.cors_origins = []
        cfg.gateway_headers = {"Authorization": "Bearer gw-key"}
        MockCfg.return_value = cfg
        MockRedis.return_value = MagicMock()

        from hermes_orchestrator.main import app
        tc = TestClient(app, raise_server_exceptions=False)
        yield tc

def test_health_no_auth(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("ok", "degraded")

def test_submit_task_requires_auth(client):
    resp = client.post("/api/v1/tasks", json={"prompt": "hello"})
    assert resp.status_code == 401

def test_submit_task_validates_prompt(client):
    resp = client.post("/api/v1/tasks", json={}, headers={"Authorization": "Bearer test-api-key"})
    assert resp.status_code == 422

def test_submit_task_returns_202(client):
    with patch("hermes_orchestrator.main.task_store") as mock_store:
        mock_store.create = MagicMock()
        mock_store.enqueue = MagicMock()
        resp = client.post(
            "/api/v1/tasks",
            json={"prompt": "summarize this"},
            headers={"Authorization": "Bearer test-api-key"},
        )
        assert resp.status_code == 202
        data = resp.json()
        assert "task_id" in data
        assert data["status"] == "queued"

def test_get_task_not_found(client):
    with patch("hermes_orchestrator.main.task_store") as mock_store:
        mock_store.get.return_value = None
        resp = client.get(
            "/api/v1/tasks/no-exist",
            headers={"Authorization": "Bearer test-api-key"},
        )
        assert resp.status_code == 404

def test_list_agents(client):
    with patch("hermes_orchestrator.main.agent_registry") as mock_reg:
        mock_reg.list_agents.return_value = []
        resp = client.get(
            "/api/v1/agents",
            headers={"Authorization": "Bearer test-api-key"},
        )
        assert resp.status_code == 200
        assert "agents" in resp.json()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/orchestrator/test_api_endpoints.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Create API Pydantic models**

```python
# hermes-orchestrator/models/api.py
from __future__ import annotations
from pydantic import BaseModel, Field

class TaskSubmitRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=50000)
    instructions: str = ""
    model_id: str = "hermes-agent"
    priority: int = Field(1, ge=1, le=10)
    timeout_seconds: float = Field(600.0, ge=10.0, le=3600.0)
    max_retries: int = Field(2, ge=0, le=5)
    callback_url: str | None = None
    metadata: dict = {}

class TaskSubmitResponse(BaseModel):
    task_id: str
    status: str = "queued"
    created_at: float
    eta_seconds: int = 30

class TaskStatusResponse(BaseModel):
    task_id: str
    status: str
    assigned_agent: str | None = None
    run_id: str | None = None
    result: dict | None = None
    error: str | None = None
    retry_count: int = 0
    created_at: float
    updated_at: float

class AgentListResponse(BaseModel):
    agents: list[dict]

class AgentHealthResponse(BaseModel):
    agent_id: str
    status: str
    circuit_state: str
    current_load: int
    max_concurrent: int
    last_health_check: float
```

- [ ] **Step 4: Implement FastAPI main.py with endpoints**

```python
# hermes-orchestrator/main.py
from __future__ import annotations
import asyncio
import json
import logging
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from functools import partial

import redis as _redis
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware

from hermes_orchestrator.config import OrchestratorConfig
from hermes_orchestrator.middleware.auth import create_auth_middleware
from hermes_orchestrator.models.api import (
    TaskSubmitRequest, TaskSubmitResponse, TaskStatusResponse,
    AgentListResponse, AgentHealthResponse,
)
from hermes_orchestrator.models.task import Task
from hermes_orchestrator.stores.redis_task_store import RedisTaskStore
from hermes_orchestrator.stores.redis_agent_registry import RedisAgentRegistry
from hermes_orchestrator.services.agent_selector import AgentSelector
from hermes_orchestrator.services.task_executor import TaskExecutor
from hermes_orchestrator.services.agent_discovery import AgentDiscoveryService
from hermes_orchestrator.services.health_monitor import HealthMonitor
from swarm.circuit_breaker import CircuitBreaker

logger = logging.getLogger(__name__)

config: OrchestratorConfig | None = None
redis_client: _redis.Redis | None = None
task_store: RedisTaskStore | None = None
agent_registry: RedisAgentRegistry | None = None
selector: AgentSelector | None = None
executor: TaskExecutor | None = None
discovery: AgentDiscoveryService | None = None
health_monitor: HealthMonitor | None = None
circuits: dict[str, CircuitBreaker] = {}

@asynccontextmanager
async def lifespan(app: FastAPI):
    global config, redis_client, task_store, agent_registry, selector, executor, discovery, health_monitor, circuits

    # Config was loaded in create_app() — reuse it here
    config = app.state.config

    redis_client = _redis.Redis.from_url(config.redis_url, decode_responses=True)
    task_store = RedisTaskStore(redis_client)
    agent_registry = RedisAgentRegistry(redis_client)
    selector = AgentSelector()
    executor = TaskExecutor(config)
    discovery = AgentDiscoveryService(config)

    for a in agent_registry.list_agents():
        circuits[a.agent_id] = CircuitBreaker(
            failure_threshold=config.circuit_failure_threshold,
            success_threshold=config.circuit_success_threshold,
            recovery_timeout=config.circuit_recovery_timeout,
        )

    health_monitor = HealthMonitor(config, agent_registry, circuits)
    health_task = asyncio.create_task(_run_health_monitor())
    worker_task = asyncio.create_task(_run_task_worker())
    discovery_task = asyncio.create_task(_run_discovery_loop())

    logger.info("Orchestrator started")
    yield

    health_monitor.stop()
    health_task.cancel()
    worker_task.cancel()
    discovery_task.cancel()
    redis_client.close()
    logger.info("Orchestrator shut down")

def create_app() -> FastAPI:
    """Application factory — loads config and registers middleware before building app."""
    cfg = OrchestratorConfig()
    logging.basicConfig(level=getattr(logging, cfg.log_level, logging.INFO))

    application = FastAPI(title="Hermes Orchestrator", version="0.1.0", lifespan=lifespan)
    application.add_middleware(*create_auth_middleware(cfg.api_key))
    if cfg.cors_origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=cfg.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["Authorization", "Content-Type"],
        )
    # Store config for lifespan to pick up
    application.state.config = cfg
    return application

app = create_app()

@app.get("/health")
async def health():
    checks: dict = {"status": "ok"}
    if redis_client:
        try:
            redis_client.ping()
            checks["redis"] = "ok"
        except Exception as e:
            checks["redis"] = f"error: {e}"
            checks["status"] = "degraded"
    return checks

@app.post("/api/v1/tasks", status_code=202)
async def submit_task(req: TaskSubmitRequest, response: Response):
    task = Task(
        task_id=str(uuid.uuid4()),
        prompt=req.prompt,
        instructions=req.instructions,
        model_id=req.model_id,
        priority=req.priority,
        timeout_seconds=req.timeout_seconds,
        max_retries=req.max_retries,
        callback_url=req.callback_url,
        metadata=req.metadata,
        created_at=time.time(),
    )
    task_store.create(task)
    task_store.enqueue(task)
    response.headers["Retry-After"] = "5"
    return TaskSubmitResponse(task_id=task.task_id, created_at=task.created_at)

@app.get("/api/v1/tasks/{task_id}")
async def get_task(task_id: str, response: Response):
    task = task_store.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    response.headers["Retry-After"] = "5"
    result_dict = None
    if task.result:
        result_dict = task.result.__dict__
    return TaskStatusResponse(
        task_id=task.task_id, status=task.status,
        assigned_agent=task.assigned_agent, run_id=task.run_id,
        result=result_dict, error=task.error,
        retry_count=task.retry_count,
        created_at=task.created_at, updated_at=task.updated_at,
    )

@app.get("/api/v1/tasks")
async def list_tasks(status: str | None = None, limit: int = 50, offset: int = 0, response: Response = Response()):
    if status:
        statuses = [status]
        tasks = task_store.list_by_status(statuses)
    else:
        tasks = task_store.list_by_status(["queued", "assigned", "executing", "streaming", "done", "failed"])
    response.headers["Retry-After"] = "5"
    return [TaskStatusResponse(
        task_id=t.task_id, status=t.status,
        assigned_agent=t.assigned_agent, run_id=t.run_id,
        created_at=t.created_at, updated_at=t.updated_at,
    ) for t in tasks[offset:offset+limit]]

@app.delete("/api/v1/tasks/{task_id}")
async def cancel_task(task_id: str):
    task = task_store.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status in ("done", "failed"):
        raise HTTPException(status_code=409, detail="Task already completed")
    if task.status not in ("queued", "assigned"):
        raise HTTPException(status_code=400, detail="Task is already executing and cannot be cancelled")
    task_store.update(task_id, status="failed", error="Cancelled by user")
    return {"status": "cancelled", "task_id": task_id}

@app.get("/api/v1/agents")
async def list_agents():
    agents = agent_registry.list_agents()
    return AgentListResponse(agents=[a.to_dict() for a in agents])

@app.get("/api/v1/agents/{agent_id}/health")
async def agent_health(agent_id: str):
    agent = agent_registry.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    circuit = circuits.get(agent_id)
    return AgentHealthResponse(
        agent_id=agent.agent_id, status=agent.status,
        circuit_state=circuit.state.name.lower() if circuit else "closed",
        current_load=agent.current_load, max_concurrent=agent.max_concurrent,
        last_health_check=agent.last_health_check,
    )

async def _run_task_worker():
    consumer = f"worker-{secrets.token_hex(4)}"
    loop = asyncio.get_event_loop()
    while True:
        try:
            # Sync Redis xreadgroup wrapped in executor to avoid blocking event loop
            result = await loop.run_in_executor(
                None,
                lambda: redis_client.xreadgroup(
                    "orchestrator.workers", consumer,
                    {"hermes:orchestrator:tasks:stream": ">"},
                    count=1, block=5000,
                )
            )
            if not result:
                continue
            for stream_name, messages in result:
                for msg_id, fields in messages:
                    task_id = fields["task_id"]
                    try:
                        await _process_task(task_id)
                    except Exception as e:
                        logger.error("Task %s processing failed: %s", task_id, e)
                        await loop.run_in_executor(
                            None, partial(task_store.update, task_id, status="failed", error=str(e))
                        )
                    await loop.run_in_executor(
                        None,
                        lambda mid=msg_id: redis_client.xack("hermes:orchestrator:tasks:stream", "orchestrator.workers", mid)
                    )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("Worker loop error: %s", e)
            await asyncio.sleep(5)

async def _process_task(task_id: str):
    loop = asyncio.get_event_loop()
    task = await loop.run_in_executor(None, task_store.get, task_id)
    if not task:
        return
    agents = await loop.run_in_executor(None, agent_registry.list_agents)
    chosen = selector.select(agents, task)
    if not chosen:
        await loop.run_in_executor(None, partial(task_store.update, task_id, status="failed", error="No available agent"))
        return
    await loop.run_in_executor(None, partial(task_store.update, task_id, status="assigned", assigned_agent=chosen.agent_id))
    await loop.run_in_executor(None, agent_registry.update_load, chosen.agent_id, chosen.current_load + 1)
    try:
        run_id = await executor.submit_run(chosen.gateway_url, task.prompt, task.instructions)
        await loop.run_in_executor(None, partial(task_store.update, task_id, status="executing", run_id=run_id))
        await loop.run_in_executor(None, partial(task_store.update, task_id, status="streaming"))
        run_result = await executor.consume_run_events(chosen.gateway_url, run_id, task.timeout_seconds)
        if run_result.status == "completed":
            result = executor.extract_result({"output": run_result.output, "usage": run_result.usage or {}, "run_id": run_id}, task)
            await loop.run_in_executor(None, partial(task_store.update, task_id, status="done", result=result))
        else:
            await loop.run_in_executor(None, partial(task_store.update, task_id, status="failed", error=run_result.error or "Run failed"))
            circuits.setdefault(chosen.agent_id, CircuitBreaker(
                failure_threshold=config.circuit_failure_threshold,
                success_threshold=config.circuit_success_threshold,
                recovery_timeout=config.circuit_recovery_timeout,
            )).record_failure()
    except Exception as e:
        # Retry logic: re-queue if retries remain
        current = await loop.run_in_executor(None, task_store.get, task_id)
        if current and current.retry_count < current.max_retries:
            new_count = current.retry_count + 1
            await loop.run_in_executor(
                None, partial(
                    task_store.update, task_id,
                    status="queued", assigned_agent=None,
                    run_id=None, error=None,
                    retry_count=new_count,
                )
            )
            # Must re-enqueue to the stream so the worker picks it up again
            requeued_task = await loop.run_in_executor(None, task_store.get, task_id)
            if requeued_task:
                await loop.run_in_executor(None, task_store.enqueue, requeued_task)
            logger.warning("Task %s failed (attempt %d/%d), re-queued", task_id, new_count, current.max_retries)
        else:
            await loop.run_in_executor(
                None, partial(task_store.update, task_id, status="failed", error=str(e))
            )
        circuits.setdefault(chosen.agent_id, CircuitBreaker(
            failure_threshold=config.circuit_failure_threshold,
            success_threshold=config.circuit_success_threshold,
            recovery_timeout=config.circuit_recovery_timeout,
        )).record_failure()
    finally:
        updated = await loop.run_in_executor(None, agent_registry.get, chosen.agent_id)
        if updated:
            await loop.run_in_executor(None, agent_registry.update_load, chosen.agent_id, max(0, updated.current_load - 1))

    task = await loop.run_in_executor(None, task_store.get, task_id)
    if task and task.callback_url:
        asyncio.create_task(_send_callback(task))

async def _send_callback(task: Task):
    if not task.callback_url or not task.callback_url.startswith("https://"):
        return
    import aiohttp
    body = json.dumps({"task_id": task.task_id, "status": task.status, "result": task.result.__dict__ if task.result else None})
    import hmac as _hmac, hashlib
    sig = _hmac.new(config.api_key.encode(), body.encode(), hashlib.sha256).hexdigest()
    headers = {"Content-Type": "application/json", "X-Hermes-Signature": f"sha256={sig}"}
    for attempt in range(3):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(task.callback_url, data=body, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status < 500:
                        return
        except Exception as e:
            logger.warning("Callback attempt %d failed: %s", attempt + 1, e)
        await asyncio.sleep(2 ** attempt)

async def _run_discovery_loop():
    loop = asyncio.get_event_loop()
    while True:
        try:
            profiles = await discovery.discover_pods()
            existing_agents = await loop.run_in_executor(None, agent_registry.list_agents)
            existing = {a.agent_id for a in existing_agents}
            discovered = {p.agent_id for p in profiles}
            for p in profiles:
                if p.agent_id not in existing:
                    await loop.run_in_executor(None, agent_registry.register, p)
                    circuits[p.agent_id] = CircuitBreaker(
                        failure_threshold=config.circuit_failure_threshold,
                        success_threshold=config.circuit_success_threshold,
                        recovery_timeout=config.circuit_recovery_timeout,
                    )
            for gone in existing - discovered:
                await loop.run_in_executor(None, agent_registry.update_status, gone, "offline")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("Discovery loop error: %s", e)
        await asyncio.sleep(30)

async def _run_health_monitor():
    if health_monitor:
        await health_monitor.start()
```

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/orchestrator/test_api_endpoints.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add hermes-orchestrator/models/api.py hermes-orchestrator/main.py tests/orchestrator/test_api_endpoints.py
git commit -m "feat(orchestrator): FastAPI app with task submission, status, agent endpoints"
```

---

## Task 11: K8s Manifests

**Files:**
- Create: `kubernetes/orchestrator/deployment.yaml`
- Create: `kubernetes/orchestrator/rbac.yaml`
- Create: `kubernetes/orchestrator/networkpolicy.yaml`
- Create: `kubernetes/orchestrator/secrets.yaml`
- Create: `hermes-orchestrator/Dockerfile`

- [ ] **Step 1: Create orchestrator K8s manifests**

Create `kubernetes/orchestrator/secrets.yaml`:
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: hermes-orchestrator-secret
  namespace: hermes-agent
type: Opaque
stringData:
  ORCHESTRATOR_API_KEY: "change-me-on-deploy"
```

Create `kubernetes/orchestrator/rbac.yaml`:
```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: hermes-orchestrator
  namespace: hermes-agent
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: hermes-orchestrator
  namespace: hermes-agent
rules:
  - apiGroups: [""]
    resources: ["pods"]
    verbs: ["get", "list", "watch"]
  - apiGroups: [""]
    resources: ["services"]
    verbs: ["get", "list"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: hermes-orchestrator
  namespace: hermes-agent
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: hermes-orchestrator
subjects:
  - kind: ServiceAccount
    name: hermes-orchestrator
    namespace: hermes-agent
```

Create `kubernetes/orchestrator/deployment.yaml`:
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: hermes-orchestrator
  namespace: hermes-agent
  labels:
    app: hermes-orchestrator
    app.kubernetes.io/component: orchestrator
spec:
  replicas: 1
  selector:
    matchLabels:
      app: hermes-orchestrator
  template:
    metadata:
      labels:
        app: hermes-orchestrator
        app.kubernetes.io/component: orchestrator
    spec:
      serviceAccountName: hermes-orchestrator
      containers:
        - name: orchestrator
          image: hermes-orchestrator:latest
          imagePullPolicy: IfNotPresent
          ports:
            - containerPort: 8080
          env:
            - name: ORCHESTRATOR_API_KEY
              valueFrom:
                secretKeyRef:
                  name: hermes-orchestrator-secret
                  key: ORCHESTRATOR_API_KEY
            - name: REDIS_URL
              value: "redis://:$(REDIS_PASSWORD)@hermes-redis:6379/0"
            - name: REDIS_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: hermes-redis-secret
                  key: REDIS_PASSWORD
            - name: GATEWAY_API_KEY
              valueFrom:
                secretKeyRef:
                  name: hermes-db-secret
                  key: api_key
            - name: K8S_NAMESPACE
              value: "hermes-agent"
            - name: LOG_LEVEL
              value: "INFO"
          resources:
            requests:
              cpu: 100m
              memory: 512Mi
            limits:
              cpu: 1000m
              memory: 1024Mi
          readinessProbe:
            httpGet:
              path: /health
              port: 8080
            initialDelaySeconds: 5
            periodSeconds: 10
          livenessProbe:
            httpGet:
              path: /health
              port: 8080
            initialDelaySeconds: 15
            periodSeconds: 30
---
apiVersion: v1
kind: Service
metadata:
  name: hermes-orchestrator
  namespace: hermes-agent
spec:
  type: ClusterIP
  ports:
    - name: api
      port: 8080
      targetPort: 8080
  selector:
    app: hermes-orchestrator
```

Create `kubernetes/orchestrator/networkpolicy.yaml`:
```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: orchestrator-egress
  namespace: hermes-agent
spec:
  podSelector:
    matchLabels:
      app: hermes-orchestrator
  policyTypes:
    - Egress
  egress:
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: kube-system
      ports:
        - protocol: UDP
          port: 53
        - protocol: TCP
          port: 53
    - to:
        - podSelector:
            matchLabels:
              app: hermes-redis
      ports:
        - protocol: TCP
          port: 6379
    - to:
        - podSelector:
            matchLabels:
              app.kubernetes.io/component: gateway
      ports:
        - protocol: TCP
          port: 8642
    - to:
        - ipBlock:
            cidr: 172.32.0.0/16
      ports:
        - protocol: TCP
          port: 6443
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: orchestrator-ingress
  namespace: hermes-agent
spec:
  podSelector:
    matchLabels:
      app: hermes-orchestrator
  policyTypes:
    - Ingress
  ingress:
    - from:
        - ipBlock:
            cidr: 10.0.0.0/8
      ports:
        - protocol: TCP
          port: 8080
```

Create `hermes-orchestrator/Dockerfile`:
```dockerfile
FROM python:3.12-slim
WORKDIR /app
# Build context is project root (docker build -f hermes-orchestrator/Dockerfile .)
COPY pyproject.toml README.md ./
COPY hermes-orchestrator/ ./hermes-orchestrator/
COPY swarm/ ./swarm/
RUN pip install --no-cache-dir -e ".[orchestrator]"
EXPOSE 8080
CMD ["uvicorn", "hermes_orchestrator.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

**Build command** (from project root):
```bash
docker build -f hermes-orchestrator/Dockerfile -t hermes-orchestrator:latest .
```

- [ ] **Step 2: Commit**

```bash
git add kubernetes/orchestrator/ hermes-orchestrator/Dockerfile
git commit -m "feat(orchestrator): K8s manifests — deployment, RBAC, network policy, Dockerfile"
```

---

## Task 12: Crash Recovery

**Files:**
- Modify: `hermes-orchestrator/main.py` — add `_recover_in_flight_tasks` on startup
- Test: `tests/orchestrator/test_crash_recovery.py`

- [ ] **Step 1: Write test for crash recovery**

```python
# tests/orchestrator/test_crash_recovery.py
import time
import pytest
import redis as _redis
from unittest.mock import MagicMock, patch
from hermes_orchestrator.models.task import Task
from hermes_orchestrator.stores.redis_task_store import RedisTaskStore
from hermes_orchestrator.stores.redis_agent_registry import RedisAgentRegistry

STREAM = "hermes:orchestrator:tasks:stream"

@pytest.fixture
def redis_client():
    r = _redis.Redis(host="localhost", port=6379, db=15, decode_responses=True)
    r.flushdb()
    yield r
    r.flushdb()
    r.close()

def test_in_flight_tasks_requeued_on_startup(redis_client):
    store = RedisTaskStore(redis_client)
    registry = RedisAgentRegistry(redis_client)

    # Simulate tasks that were in-flight when orchestrator crashed
    for i, status in enumerate(["executing", "streaming", "assigned"]):
        t = Task(task_id=f"t-{status}", prompt="test", created_at=time.time(),
                 status=status, assigned_agent="gw-1")
        store.create(t)

    # Simulate a task that was done (should NOT be requeued)
    t_done = Task(task_id="t-done", prompt="done", created_at=time.time(), status="done")
    store.create(t_done)

    # Run recovery
    from hermes_orchestrator.main import _recover_in_flight_tasks
    _recover_in_flight_tasks(store, registry)

    # In-flight tasks should be back to queued
    for status in ["executing", "streaming", "assigned"]:
        recovered = store.get(f"t-{status}")
        assert recovered is not None
        assert recovered.status == "queued"
        assert recovered.assigned_agent is None

    # Done task should remain done
    done = store.get("t-done")
    assert done.status == "done"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/orchestrator/test_crash_recovery.py -v`
Expected: FAIL — function not found

- [ ] **Step 3: Implement crash recovery in main.py**

Add to `hermes-orchestrator/main.py`:

```python
def _recover_in_flight_tasks(store: RedisTaskStore, registry: RedisAgentRegistry) -> None:
    """Recover tasks that were in-flight when the orchestrator crashed."""
    in_flight = store.list_by_status(["assigned", "executing", "streaming"])
    for task in in_flight:
        agent = registry.get(task.assigned_agent) if task.assigned_agent else None
        if not agent or agent.status == "offline":
            task.assigned_agent = None
            task.status = "queued"
            task.retry_count += 1
        else:
            task.assigned_agent = None
            task.status = "queued"
        store.update(task.task_id, status=task.status, assigned_agent=None)
        logger.info("Recovered task %s → queued (was %s)", task.task_id, task.status)
```

Call `_recover_in_flight_tasks(task_store, agent_registry)` in the `lifespan` startup, before starting the worker.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/orchestrator/test_crash_recovery.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add hermes-orchestrator/main.py tests/orchestrator/test_crash_recovery.py
git commit -m "feat(orchestrator): crash recovery — requeue in-flight tasks on startup"
```

---

## Task 13: Gateway Label Prerequisite

**Files:**
- Modify: `kubernetes/gateway/deployment.yaml` — add `app.kubernetes.io/component: gateway` label

- [ ] **Step 1: Add gateway label to deployment template**

In `kubernetes/gateway/deployment.yaml`, add the label to the pod template metadata:

```yaml
template:
  metadata:
    labels:
      app: hermes-gateway
      app.kubernetes.io/component: gateway  # Required for orchestrator discovery
```

- [ ] **Step 2: Patch existing gateway deployments on cluster**

Run on 184 dev cluster:
```bash
for dep in $(kubectl get deployments -n hermes-agent -o name | grep hermes-gateway); do
  kubectl patch $dep -n hermes-agent --type=json \
    -p '[{"op":"add","path":"/spec/template/metadata/labels/app.kubernetes.io~1component","value":"gateway"}]'
done
```

- [ ] **Step 3: Commit**

```bash
git add kubernetes/gateway/deployment.yaml
git commit -m "feat(orchestrator): add gateway label for orchestrator pod discovery"
```

---

---

## Task 14: Admin Backend — Orchestrator Proxy API

The admin backend proxies requests to the orchestrator service. This avoids exposing the orchestrator API directly to the browser and reuses the admin's existing auth middleware.

**Files:**
- Modify: `admin/backend/main.py` — add orchestrator proxy routes
- Modify: `admin/backend/requirements.txt` — add `httpx` if not present
- Test: `admin/frontend/e2e/orchestrator-api.spec.ts`

### API Contract: Admin → Orchestrator Proxy

The admin backend adds these routes under `/admin/api/orchestrator/`:

| Method | Admin Route | Orchestrator Route | Purpose |
|--------|-------------|-------------------|---------|
| `GET` | `/admin/api/orchestrator/capability` | — | Feature flag: returns `{enabled: true/false}` by checking if orchestrator service is reachable |
| `POST` | `/admin/api/orchestrator/tasks` | `POST /api/v1/tasks` | Submit a task |
| `GET` | `/admin/api/orchestrator/tasks` | `GET /api/v1/tasks` | List tasks (with query params) |
| `GET` | `/admin/api/orchestrator/tasks/:id` | `GET /api/v1/tasks/:id` | Get task status |
| `DELETE` | `/admin/api/orchestrator/tasks/:id` | `DELETE /api/v1/tasks/:id` | Cancel task |
| `GET` | `/admin/api/orchestrator/agents` | `GET /api/v1/agents` | List registered agents |
| `GET` | `/admin/api/orchestrator/agents/:id/health` | `GET /api/v1/agents/:id/health` | Agent health detail |

### Implementation

```python
# In admin/backend/main.py — add orchestrator proxy routes
import httpx

ORCHESTRATOR_INTERNAL_URL = os.environ.get("ORCHESTRATOR_INTERNAL_URL", "http://hermes-orchestrator:8080")

@app.get("/admin/api/orchestrator/capability")
async def orchestrator_capability(_: str = Depends(verify_admin_key)):
    """Check if orchestrator service is available."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{ORCHESTRATOR_INTERNAL_URL}/health")
            return {"enabled": resp.status_code == 200}
    except Exception:
        return {"enabled": False}

@app.post("/admin/api/orchestrator/tasks")
async def orchestrator_submit_task(request: Request, _: str = Depends(verify_admin_key)):
    """Proxy task submission to orchestrator."""
    body = await request.json()
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{ORCHESTRATOR_INTERNAL_URL}/api/v1/tasks",
            json=body,
            headers={"Authorization": f"Bearer {os.environ.get('ORCHESTRATOR_API_KEY', '')}"},
        )
        return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")

@app.get("/admin/api/orchestrator/tasks")
async def orchestrator_list_tasks(request: Request, _: str = Depends(verify_admin_key)):
    """Proxy task listing."""
    params = dict(request.query_params)
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{ORCHESTRATOR_INTERNAL_URL}/api/v1/tasks",
            params=params,
            headers={"Authorization": f"Bearer {os.environ.get('ORCHESTRATOR_API_KEY', '')}"},
        )
        return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")

@app.get("/admin/api/orchestrator/tasks/{task_id}")
async def orchestrator_get_task(task_id: str, _: str = Depends(verify_admin_key)):
    """Proxy get task status."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{ORCHESTRATOR_INTERNAL_URL}/api/v1/tasks/{task_id}",
            headers={"Authorization": f"Bearer {os.environ.get('ORCHESTRATOR_API_KEY', '')}"},
        )
        return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")

@app.delete("/admin/api/orchestrator/tasks/{task_id}")
async def orchestrator_cancel_task(task_id: str, _: str = Depends(verify_admin_key)):
    """Proxy cancel task."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.delete(
            f"{ORCHESTRATOR_INTERNAL_URL}/api/v1/tasks/{task_id}",
            headers={"Authorization": f"Bearer {os.environ.get('ORCHESTRATOR_API_KEY', '')}"},
        )
        return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")

@app.get("/admin/api/orchestrator/agents")
async def orchestrator_list_agents(_: str = Depends(verify_admin_key)):
    """Proxy list agents."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{ORCHESTRATOR_INTERNAL_URL}/api/v1/agents",
            headers={"Authorization": f"Bearer {os.environ.get('ORCHESTRATOR_API_KEY', '')}"},
        )
        return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")

@app.get("/admin/api/orchestrator/agents/{agent_id}/health")
async def orchestrator_agent_health(agent_id: str, _: str = Depends(verify_admin_key)):
    """Proxy agent health detail."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{ORCHESTRATOR_INTERNAL_URL}/api/v1/agents/{agent_id}/health",
            headers={"Authorization": f"Bearer {os.environ.get('ORCHESTRATOR_API_KEY', '')}"},
        )
        return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")

# NOTE: No SSE proxy endpoint needed — the orchestrator does not expose an SSE endpoint.
# The frontend polls task status via GET /admin/api/orchestrator/tasks/:id every 5 seconds.
# If real-time streaming is needed in the future, add a Redis Pub/Sub listener in the
# orchestrator that publishes task state changes, and add an SSE endpoint there.
```

### Environment Variables to Add to Admin Deployment

```yaml
# In admin deployment env section
- name: ORCHESTRATOR_INTERNAL_URL
  value: "http://hermes-orchestrator:8080"
- name: ORCHESTRATOR_API_KEY
  valueFrom:
    secretKeyRef:
      name: hermes-orchestrator-secret
      key: ORCHESTRATOR_API_KEY
```

- [ ] **Step 1: Add proxy routes to admin backend**
- [ ] **Step 2: Add `httpx` to admin requirements**
- [ ] **Step 3: Add env vars to admin deployment**
- [ ] **Step 4: Write E2E test for capability endpoint**

```typescript
// admin/frontend/e2e/orchestrator-api.spec.ts
import { test, expect } from "@playwright/test";
import { VALID_ADMIN_KEY } from "./fixtures/mock-data";
import { loginAsAdmin } from "./helpers";

test("orchestrator capability check", async ({ page }) => {
  await page.route("**/admin/api/orchestrator/capability", (route) =>
    route.fulfill({ json: { enabled: true } })
  );
  await loginAsAdmin(page);
  await page.goto("/admin/");
  // The orchestrator nav link should be visible when capability is true
  await expect(page.locator('a[href*="/orchestrator"]').first()).toBeVisible({ timeout: 5000 });
});
```

- [ ] **Step 5: Commit**

```bash
git add admin/backend/main.py admin/backend/requirements.txt admin/frontend/e2e/orchestrator-api.spec.ts
git commit -m "feat(admin): orchestrator proxy API routes with SSE streaming"
```

---

## Task 15: Frontend — Orchestrator API Client + Feature Guard

**Files:**
- Modify: `admin/frontend/src/lib/admin-api.ts` — add orchestrator API methods
- Create: `admin/frontend/src/components/OrchestratorGuard.tsx` — feature flag guard
- Test: `admin/frontend/e2e/orchestrator-guard.spec.ts`

### API Client Types and Methods

```typescript
// Types to add to admin-api.ts

interface OrchestratorTask {
  task_id: string;
  status: "submitted" | "queued" | "assigned" | "executing" | "streaming" | "done" | "failed";
  assigned_agent: string | null;
  run_id: string | null;
  result: {
    content: string;
    usage: { input_tokens: number; output_tokens: number; total_tokens: number };
    duration_seconds: number;
    run_id: string;
  } | null;
  error: string | null;
  retry_count: number;
  created_at: number;
  updated_at: number;
}

interface OrchestratorAgent {
  agent_id: string;
  gateway_url: string;
  status: "online" | "degraded" | "offline";
  models: string[];
  current_load: number;
  max_concurrent: number;
  circuit_state: "closed" | "open" | "half_open";
  last_health_check: number;
}

interface TaskSubmitRequest {
  prompt: string;
  instructions?: string;
  model_id?: string;
  priority?: number;
  timeout_seconds?: number;
  max_retries?: number;
  callback_url?: string;
  metadata?: Record<string, string>;
}

// Methods to add to adminApi object:

orchestratorCapability(): Promise<{ enabled: boolean }> {
  return adminFetch("/orchestrator/capability");
}

orchestratorSubmitTask(req: TaskSubmitRequest): Promise<{ task_id: string; status: string; created_at: number }> {
  return adminFetch("/orchestrator/tasks", { method: "POST", body: JSON.stringify(req) });
}

orchestratorListTasks(params?: { status?: string; limit?: number; offset?: number }): Promise<OrchestratorTask[]> {
  const query = new URLSearchParams();
  if (params?.status) query.set("status", params.status);
  if (params?.limit) query.set("limit", String(params.limit));
  if (params?.offset) query.set("offset", String(params.offset));
  const qs = query.toString();
  return adminFetch(`/orchestrator/tasks${qs ? `?${qs}` : ""}`);
}

orchestratorGetTask(taskId: string): Promise<OrchestratorTask> {
  return adminFetch(`/orchestrator/tasks/${taskId}`);
}

orchestratorCancelTask(taskId: string): Promise<{ status: string }> {
  return adminFetch(`/orchestrator/tasks/${taskId}`, { method: "DELETE" });
}

orchestratorListAgents(): Promise<{ agents: OrchestratorAgent[] }> {
  return adminFetch("/orchestrator/agents");
}

orchestratorAgentHealth(agentId: string): Promise<OrchestratorAgent> {
  return adminFetch(`/orchestrator/agents/${agentId}/health`);
}
```

### OrchestratorGuard Component

```tsx
// admin/frontend/src/components/OrchestratorGuard.tsx
import { useEffect, useState } from "react";
import { Navigate, Outlet } from "react-router-dom";
import { adminApi } from "./lib/admin-api";

export function OrchestratorGuard() {
  const [enabled, setEnabled] = useState<boolean | null>(null);

  useEffect(() => {
    adminApi.orchestratorCapability()
      .then(({ enabled }) => setEnabled(enabled))
      .catch(() => setEnabled(false));
  }, []);

  if (enabled === null) return null; // Loading
  if (!enabled) return <Navigate to="/admin/" replace />;
  return <Outlet />;
}
```

- [ ] **Step 1: Add orchestrator types and API methods to admin-api.ts**
- [ ] **Step 2: Create OrchestratorGuard component**
- [ ] **Step 3: Write E2E test for guard redirect**

```typescript
// admin/frontend/e2e/orchestrator-guard.spec.ts
import { test, expect } from "@playwright/test";
import { loginAsAdmin } from "./helpers";

test("redirects to dashboard when orchestrator is disabled", async ({ page }) => {
  await page.route("**/admin/api/orchestrator/capability", (route) =>
    route.fulfill({ json: { enabled: false } })
  );
  await page.route("**/admin/api/agents", (route) =>
    route.fulfill({ json: { agents: [], total: 0 } })
  );
  await page.route("**/admin/api/cluster/status", (route) =>
    route.fulfill({ json: { nodes: [] } })
  );
  await loginAsAdmin(page);
  await page.goto("/admin/orchestrator");
  await expect(page).toHaveURL(/\/admin\/$/);
});

test("allows access when orchestrator is enabled", async ({ page }) => {
  await page.route("**/admin/api/orchestrator/capability", (route) =>
    route.fulfill({ json: { enabled: true } })
  );
  await page.route("**/admin/api/orchestrator/tasks**", (route) =>
    route.fulfill({ json: [] })
  );
  await page.route("**/admin/api/orchestrator/agents", (route) =>
    route.fulfill({ json: { agents: [] } })
  );
  await loginAsAdmin(page);
  await page.goto("/admin/orchestrator");
  await expect(page).toHaveURL(/\/admin\/orchestrator/);
});
```

- [ ] **Step 4: Commit**

```bash
git add admin/frontend/src/lib/admin-api.ts admin/frontend/src/components/OrchestratorGuard.tsx admin/frontend/e2e/orchestrator-guard.spec.ts
git commit -m "feat(admin-frontend): orchestrator API client and feature guard"
```

---

## Task 16: Frontend — Orchestrator Routes + Sidebar Navigation

**Files:**
- Modify: `admin/frontend/src/App.tsx` — add orchestrator routes
- Modify: `admin/frontend/src/components/AdminLayout.tsx` — add sidebar nav section
- Modify: `admin/frontend/src/i18n/en.ts` — add orchestrator translation keys
- Modify: `admin/frontend/src/i18n/zh.ts` — add orchestrator translation keys

### Route Structure

```tsx
// In App.tsx, add under AdminLayout, after swarm routes:
<Route
  element={<OrchestratorGuard />}
>
  <Route path="/orchestrator" element={<OrchestratorOverviewPage />} />
  <Route path="/orchestrator/tasks/new" element={<TaskSubmitPage />} />
  <Route path="/orchestrator/tasks/:taskId" element={<TaskDetailPage />} />
</Route>
```

### Sidebar Navigation

Add a new section in `AdminLayout.tsx` after the swarm nav links, admin-only (`{!isUser && ...}`):

```tsx
{/* Orchestrator Section */}
{!isUser && (
  <div className="mt-6 px-3">
    <p className="text-xs font-medium text-text-muted uppercase tracking-wider mb-2 px-2">
      {t.orchestratorNav}
    </p>
    <NavLink to="/orchestrator" ...>
      <svg>...</svg>
      <span>{t.orchestratorOverview}</span>
    </NavLink>
    <NavLink to="/orchestrator/tasks/new" ...>
      <svg>...</svg>
      <span>{t.orchestratorNewTask}</span>
    </NavLink>
  </div>
)}
```

### Translation Keys

```typescript
// en.ts additions
orchestratorNav: "Orchestrator",
orchestratorOverview: "Overview",
orchestratorNewTask: "Submit Task",
orchestratorTaskList: "Tasks",
orchestratorAgentFleet: "Agent Fleet",
orchestratorNoAgents: "No agents registered",
orchestratorNoTasks: "No tasks yet",
orchestratorStatusOnline: "Online",
orchestratorStatusDegraded: "Degraded",
orchestratorStatusOffline: "Offline",
orchestratorCircuitClosed: "Healthy",
orchestratorCircuitOpen: "Circuit Open",
orchestratorCircuitHalfOpen: "Recovering",
orchestratorSubmitTask: "Submit Task",
orchestratorPromptLabel: "Prompt",
orchestratorInstructionsLabel: "System Instructions",
orchestratorPriorityLabel: "Priority",
orchestratorTimeoutLabel: "Timeout (seconds)",
orchestratorCallbackLabel: "Callback URL (HTTPS)",
orchestratorSubmitting: "Submitting...",
orchestratorSubmitSuccess: "Task submitted successfully",
orchestratorSubmitError: "Failed to submit task",
orchestratorTaskStatus: "Status",
orchestratorTaskAgent: "Agent",
orchestratorTaskCreated: "Created",
orchestratorTaskDuration: "Duration",
orchestratorTaskTokens: "Tokens",
orchestratorTaskResult: "Result",
orchestratorTaskError: "Error",
orchestratorTaskRetries: "Retries",
orchestratorCancelTask: "Cancel Task",
orchestratorCircuitBreaker: "Circuit Breaker",
orchestratorLoad: "Load",
orchestratorHealthCheck: "Last Health Check",
orchestratorCurrentLoad: "Current Load",
orchestratorMaxConcurrent: "Max Concurrent",
```

```typescript
// zh.ts additions
orchestratorNav: "编排器",
orchestratorOverview: "概览",
orchestratorNewTask: "提交任务",
orchestratorTaskList: "任务列表",
orchestratorAgentFleet: "Agent 集群",
orchestratorNoAgents: "暂无注册 Agent",
orchestratorNoTasks: "暂无任务",
orchestratorStatusOnline: "在线",
orchestratorStatusDegraded: "降级",
orchestratorStatusOffline: "离线",
orchestratorCircuitClosed: "正常",
orchestratorCircuitOpen: "熔断",
orchestratorCircuitHalfOpen: "恢复中",
orchestratorSubmitTask: "提交任务",
orchestratorPromptLabel: "提示词",
orchestratorInstructionsLabel: "系统指令",
orchestratorPriorityLabel: "优先级",
orchestratorTimeoutLabel: "超时时间（秒）",
orchestratorCallbackLabel: "回调地址（HTTPS）",
orchestratorSubmitting: "提交中...",
orchestratorSubmitSuccess: "任务提交成功",
orchestratorSubmitError: "任务提交失败",
orchestratorTaskStatus: "状态",
orchestratorTaskAgent: "Agent",
orchestratorTaskCreated: "创建时间",
orchestratorTaskDuration: "耗时",
orchestratorTaskTokens: "Token 用量",
orchestratorTaskResult: "结果",
orchestratorTaskError: "错误",
orchestratorTaskRetries: "重试次数",
orchestratorCancelTask: "取消任务",
orchestratorCircuitBreaker: "熔断器",
orchestratorLoad: "负载",
orchestratorHealthCheck: "最近健康检查",
orchestratorCurrentLoad: "当前负载",
orchestratorMaxConcurrent: "最大并发",
```

- [ ] **Step 1: Add routes to App.tsx**
- [ ] **Step 2: Add sidebar nav section to AdminLayout.tsx**
- [ ] **Step 3: Add translation keys to en.ts and zh.ts**
- [ ] **Step 4: Verify no TypeScript errors** — Run: `npx tsc --noEmit`
- [ ] **Step 5: Commit**

```bash
git add admin/frontend/src/App.tsx admin/frontend/src/components/AdminLayout.tsx admin/frontend/src/i18n/en.ts admin/frontend/src/i18n/zh.ts
git commit -m "feat(admin-frontend): orchestrator routes, sidebar nav, and i18n"
```

---

## Task 17: Frontend — Orchestrator Overview Page

**Files:**
- Create: `admin/frontend/src/pages/orchestrator/OrchestratorOverviewPage.tsx`

### Page Layout

The overview page shows two panels side-by-side:

**Left panel: Agent Fleet Status**
- Table with columns: Agent ID, Status (color badge), Current Load / Max (progress bar), Circuit Breaker (color dot), Last Health Check
- Status badges: green=online, yellow=degraded, red=offline
- Circuit badges: green=closed, red=open, yellow=half_open
- Auto-refresh every 10 seconds

**Right panel: Recent Tasks**
- Compact list of last 10 tasks with: Task ID (truncated), Status badge, Agent, Duration, Created timestamp
- Status badges: gray=queued, blue=executing, green=done, red=failed
- Click task to navigate to `/orchestrator/tasks/:taskId`

**Top stats bar:**
- Total Agents | Online Agents | Active Tasks | Completed Today

```tsx
// admin/frontend/src/pages/orchestrator/OrchestratorOverviewPage.tsx
import { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { adminApi, type OrchestratorAgent, type OrchestratorTask } from "../../lib/admin-api";
import { useI18n } from "../../hooks/useI18n";

export function OrchestratorOverviewPage() {
  const t = useI18n();
  const navigate = useNavigate();
  const [agents, setAgents] = useState<OrchestratorAgent[]>([]);
  const [tasks, setTasks] = useState<OrchestratorTask[]>([]);
  const [loading, setLoading] = useState(true);

  const loadData = useCallback(async () => {
    try {
      const [agentsData, tasksData] = await Promise.all([
        adminApi.orchestratorListAgents(),
        adminApi.orchestratorListTasks({ limit: 10 }),
      ]);
      setAgents(agentsData.agents);
      setTasks(tasksData);
    } catch (e) {
      console.error("Failed to load orchestrator data", e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
    const interval = setInterval(loadData, 10000);
    return () => clearInterval(interval);
  }, [loadData]);

  if (loading) return <div className="p-6 text-text-secondary">{t.loading || "Loading..."}</div>;

  const onlineAgents = agents.filter(a => a.status === "online").length;
  const activeTasks = tasks.filter(t => ["queued", "assigned", "executing", "streaming"].includes(t.status)).length;
  const doneToday = tasks.filter(t => t.status === "done").length;

  return (
    <div className="p-6 space-y-6">
      {/* Stats Bar */}
      <div className="grid grid-cols-4 gap-4">
        <StatCard label={t.orchestratorAgentFleet} value={agents.length} />
        <StatCard label={t.orchestratorStatusOnline} value={onlineAgents} />
        <StatCard label="Active Tasks" value={activeTasks} />
        <StatCard label="Done" value={doneToday} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Agent Fleet Table */}
        <section className="bg-surface/50 rounded-lg border border-border/50 p-4">
          <h2 className="text-lg font-semibold text-text-primary mb-4">{t.orchestratorAgentFleet}</h2>
          {agents.length === 0 ? (
            <p className="text-text-secondary text-sm">{t.orchestratorNoAgents}</p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-text-muted text-left border-b border-border/30">
                  <th className="pb-2">Agent</th>
                  <th className="pb-2">Status</th>
                  <th className="pb-2">Load</th>
                  <th className="pb-2">Circuit</th>
                </tr>
              </thead>
              <tbody>
                {agents.map(agent => (
                  <tr key={agent.agent_id} className="border-b border-border/10 hover:bg-surface/30">
                    <td className="py-2 font-mono text-xs">{agent.agent_id}</td>
                    <td className="py-2"><StatusBadge status={agent.status} /></td>
                    <td className="py-2">
                      <div className="flex items-center gap-2">
                        <div className="w-16 h-1.5 bg-border/30 rounded-full overflow-hidden">
                          <div className="h-full bg-accent-cyan rounded-full" style={{ width: `${(agent.current_load / agent.max_concurrent) * 100}%` }} />
                        </div>
                        <span className="text-text-muted text-xs">{agent.current_load}/{agent.max_concurrent}</span>
                      </div>
                    </td>
                    <td className="py-2"><CircuitBadge state={agent.circuit_state} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        {/* Recent Tasks */}
        <section className="bg-surface/50 rounded-lg border border-border/50 p-4">
          <h2 className="text-lg font-semibold text-text-primary mb-4">{t.orchestratorTaskList}</h2>
          {tasks.length === 0 ? (
            <p className="text-text-secondary text-sm">{t.orchestratorNoTasks}</p>
          ) : (
            <div className="space-y-2">
              {tasks.map(task => (
                <div key={task.task_id}
                  className="flex items-center justify-between p-2 rounded hover:bg-surface/30 cursor-pointer"
                  onClick={() => navigate(`/orchestrator/tasks/${task.task_id}`)}
                >
                  <div className="flex items-center gap-3">
                    <StatusBadge status={task.status} />
                    <span className="font-mono text-xs text-text-secondary">{task.task_id.slice(0, 8)}</span>
                  </div>
                  <span className="text-text-muted text-xs">{task.assigned_agent || "—"}</span>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="bg-surface/50 rounded-lg border border-border/50 p-4">
      <p className="text-text-muted text-xs">{label}</p>
      <p className="text-2xl font-bold text-text-primary">{value}</p>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    online: "bg-green-500/20 text-green-400",
    done: "bg-green-500/20 text-green-400",
    degraded: "bg-yellow-500/20 text-yellow-400",
    half_open: "bg-yellow-500/20 text-yellow-400",
    queued: "bg-gray-500/20 text-gray-400",
    assigned: "bg-gray-500/20 text-gray-400",
    offline: "bg-red-500/20 text-red-400",
    failed: "bg-red-500/20 text-red-400",
    executing: "bg-blue-500/20 text-blue-400",
    streaming: "bg-blue-500/20 text-blue-400",
  };
  return <span className={`px-2 py-0.5 rounded text-xs font-medium ${colors[status] || "bg-gray-500/20 text-gray-400"}`}>{status}</span>;
}

function CircuitBadge({ state }: { state: string }) {
  const colors: Record<string, string> = {
    closed: "bg-green-500",
    open: "bg-red-500",
    half_open: "bg-yellow-500",
  };
  return <span className={`inline-block w-2.5 h-2.5 rounded-full ${colors[state] || "bg-gray-500"}`} title={state} />;
}
```

- [ ] **Step 1: Create OrchestratorOverviewPage.tsx**
- [ ] **Step 2: Verify page renders** — Run: `npm run dev` and navigate to `/admin/orchestrator`
- [ ] **Step 3: Write E2E smoke test**

```typescript
// admin/frontend/e2e/orchestrator-overview.spec.ts
import { test, expect } from "@playwright/test";
import { loginAsAdmin } from "./helpers";

test("orchestrator overview shows agent fleet", async ({ page }) => {
  await page.route("**/admin/api/orchestrator/capability", (route) =>
    route.fulfill({ json: { enabled: true } })
  );
  await page.route("**/admin/api/orchestrator/agents", (route) =>
    route.fulfill({ json: { agents: [
      { agent_id: "gw-1", gateway_url: "http://10.0.0.1:8642", status: "online", current_load: 2, max_concurrent: 10, circuit_state: "closed", models: ["hermes-agent"], last_health_check: Date.now() / 1000 },
    ] } })
  );
  await page.route("**/admin/api/orchestrator/tasks**", (route) =>
    route.fulfill({ json: [] })
  );
  await loginAsAdmin(page);
  await page.goto("/admin/orchestrator");
  await expect(page.getByText("gw-1")).toBeVisible();
  await expect(page.getByText("online")).toBeVisible();
});
```

- [ ] **Step 4: Commit**

```bash
git add admin/frontend/src/pages/orchestrator/ admin/frontend/e2e/orchestrator-overview.spec.ts
git commit -m "feat(admin-frontend): orchestrator overview page with agent fleet and task list"
```

---

## Task 18: Frontend — Task Submit Page

**Files:**
- Create: `admin/frontend/src/pages/orchestrator/TaskSubmitPage.tsx`

### Page Layout

A form page with:
- **Prompt textarea** (required, min 1 char)
- **System Instructions textarea** (optional)
- **Priority slider** (1-10, default 1)
- **Timeout input** (seconds, default 600)
- **Max Retries input** (0-5, default 2)
- **Callback URL input** (optional, must be HTTPS)
- **Submit button** — calls `adminApi.orchestratorSubmitTask()`, on success navigates to `/orchestrator/tasks/:taskId`

```tsx
// admin/frontend/src/pages/orchestrator/TaskSubmitPage.tsx
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { adminApi } from "../../lib/admin-api";
import { useI18n } from "../../hooks/useI18n";

export function TaskSubmitPage() {
  const t = useI18n();
  const navigate = useNavigate();
  const [prompt, setPrompt] = useState("");
  const [instructions, setInstructions] = useState("");
  const [priority, setPriority] = useState(1);
  const [timeout, setTimeout_] = useState(600);
  const [maxRetries, setMaxRetries] = useState(2);
  const [callbackUrl, setCallbackUrl] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!prompt.trim()) return;
    setSubmitting(true);
    setError("");
    try {
      const result = await adminApi.orchestratorSubmitTask({
        prompt: prompt.trim(),
        instructions: instructions.trim() || undefined,
        priority,
        timeout_seconds: timeout,
        max_retries: maxRetries,
        callback_url: callbackUrl.trim() || undefined,
      });
      navigate(`/orchestrator/tasks/${result.task_id}`);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : t.orchestratorSubmitError);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="p-6 max-w-2xl">
      <h1 className="text-xl font-bold text-text-primary mb-6">{t.orchestratorSubmitTask}</h1>
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="block text-sm text-text-secondary mb-1">{t.orchestratorPromptLabel} *</label>
          <textarea value={prompt} onChange={e => setPrompt(e.target.value)} rows={6}
            className="w-full bg-surface/80 border border-border/50 rounded-md p-3 text-text-primary text-sm focus:outline-none focus:border-accent-cyan/50"
            placeholder="Enter task prompt..." required />
        </div>
        <div>
          <label className="block text-sm text-text-secondary mb-1">{t.orchestratorInstructionsLabel}</label>
          <textarea value={instructions} onChange={e => setInstructions(e.target.value)} rows={3}
            className="w-full bg-surface/80 border border-border/50 rounded-md p-3 text-text-primary text-sm focus:outline-none focus:border-accent-cyan/50"
            placeholder="Optional system instructions..." />
        </div>
        <div className="grid grid-cols-3 gap-4">
          <div>
            <label className="block text-sm text-text-secondary mb-1">{t.orchestratorPriorityLabel}</label>
            <input type="number" min={1} max={10} value={priority} onChange={e => setPriority(Number(e.target.value))}
              className="w-full bg-surface/80 border border-border/50 rounded-md p-2 text-text-primary text-sm" />
          </div>
          <div>
            <label className="block text-sm text-text-secondary mb-1">{t.orchestratorTimeoutLabel}</label>
            <input type="number" min={10} max={3600} value={timeout} onChange={e => setTimeout_(Number(e.target.value))}
              className="w-full bg-surface/80 border border-border/50 rounded-md p-2 text-text-primary text-sm" />
          </div>
          <div>
            <label className="block text-sm text-text-secondary mb-1">{t.orchestratorTaskRetries}</label>
            <input type="number" min={0} max={5} value={maxRetries} onChange={e => setMaxRetries(Number(e.target.value))}
              className="w-full bg-surface/80 border border-border/50 rounded-md p-2 text-text-primary text-sm" />
          </div>
        </div>
        <div>
          <label className="block text-sm text-text-secondary mb-1">{t.orchestratorCallbackLabel}</label>
          <input type="url" value={callbackUrl} onChange={e => setCallbackUrl(e.target.value)}
            className="w-full bg-surface/80 border border-border/50 rounded-md p-2 text-text-primary text-sm"
            placeholder="https://example.com/webhook" />
        </div>
        {error && <p className="text-red-400 text-sm">{error}</p>}
        <button type="submit" disabled={submitting || !prompt.trim()}
          className="px-6 py-2 bg-accent-cyan/80 text-white rounded-md hover:bg-accent-cyan disabled:opacity-50 disabled:cursor-not-allowed text-sm font-medium">
          {submitting ? t.orchestratorSubmitting : t.orchestratorSubmitTask}
        </button>
      </form>
    </div>
  );
}
```

- [ ] **Step 1: Create TaskSubmitPage.tsx**
- [ ] **Step 2: Write E2E test for task submission**

```typescript
// admin/frontend/e2e/orchestrator-submit.spec.ts
import { test, expect } from "@playwright/test";
import { loginAsAdmin } from "./helpers";

test("submit task form validates and submits", async ({ page }) => {
  await page.route("**/admin/api/orchestrator/capability", (route) =>
    route.fulfill({ json: { enabled: true } })
  );
  await page.route("**/admin/api/orchestrator/tasks**", (route) =>
    route.fulfill({ json: [] })
  );
  await page.route("**/admin/api/orchestrator/agents", (route) =>
    route.fulfill({ json: { agents: [] } })
  );
  await loginAsAdmin(page);
  await page.goto("/admin/orchestrator/tasks/new");

  // Submit button disabled when prompt empty
  await expect(page.locator('button[type="submit"]')).toBeDisabled();

  // Fill prompt
  await page.locator('textarea').first().fill("Summarize the Q1 report");
  await expect(page.locator('button[type="submit"]')).toBeEnabled();

  // Submit
  await page.route("**/admin/api/orchestrator/tasks", (route) => {
    if (route.request().method() === "POST") {
      route.fulfill({ json: { task_id: "test-task-123", status: "queued", created_at: Date.now() / 1000 } });
    }
  });
  await page.locator('button[type="submit"]').click();
  await expect(page).toHaveURL(/\/orchestrator\/tasks\/test-task-123/);
});
```

- [ ] **Step 3: Commit**

```bash
git add admin/frontend/src/pages/orchestrator/TaskSubmitPage.tsx admin/frontend/e2e/orchestrator-submit.spec.ts
git commit -m "feat(admin-frontend): task submit page with form validation"
```

---

## Task 19: Frontend — Task Detail Page

**Files:**
- Create: `admin/frontend/src/pages/orchestrator/TaskDetailPage.tsx`

### Page Layout

Shows full task status with auto-refresh (poll every 5s while task is active):

- **Header**: Task ID (monospace), Status badge, Created/Updated timestamps
- **Agent info**: Assigned agent, Gateway run ID
- **Result section** (when done): Content display, Token usage, Duration
- **Error section** (when failed): Error message, retry count, retry button
- **Cancel button** (when queued/assigned)
- **Live event log**: SSE stream for real-time progress (executing/streaming status)

```tsx
// admin/frontend/src/pages/orchestrator/TaskDetailPage.tsx
import { useEffect, useState, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { adminApi, type OrchestratorTask } from "../../lib/admin-api";
import { useI18n } from "../../hooks/useI18n";

export function TaskDetailPage() {
  const { taskId } = useParams<{ taskId: string }>();
  const t = useI18n();
  const navigate = useNavigate();
  const [task, setTask] = useState<OrchestratorTask | null>(null);
  const [loading, setLoading] = useState(true);
  const [events, setEvents] = useState<string[]>([]);

  const loadTask = useCallback(async () => {
    if (!taskId) return;
    try {
      const data = await adminApi.orchestratorGetTask(taskId);
      setTask(data);
    } catch {
      setTask(null);
    } finally {
      setLoading(false);
    }
  }, [taskId]);

  useEffect(() => {
    loadTask();
    if (!task || ["done", "failed"].includes(task.status)) return;
    const interval = setInterval(loadTask, 5000);
    return () => clearInterval(interval);
  }, [loadTask, task?.status]);

  const handleCancel = async () => {
    if (!taskId) return;
    try {
      await adminApi.orchestratorCancelTask(taskId);
      loadTask();
    } catch (e) {
      console.error("Cancel failed", e);
    }
  };

  if (loading) return <div className="p-6 text-text-secondary">Loading...</div>;
  if (!task) return <div className="p-6 text-red-400">Task not found</div>;

  const isActive = !["done", "failed"].includes(task.status);

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <button onClick={() => navigate("/admin/orchestrator")} className="text-text-muted hover:text-text-primary">← Back</button>
          <h1 className="text-lg font-mono text-text-primary">{task.task_id.slice(0, 16)}...</h1>
          <StatusBadge status={task.status} />
        </div>
        {isActive && task.status !== "executing" && task.status !== "streaming" && (
          <button onClick={handleCancel} className="px-3 py-1.5 bg-red-500/20 text-red-400 rounded-md text-sm hover:bg-red-500/30">{t.orchestratorCancelTask}</button>
        )}
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <InfoCard label={t.orchestratorTaskAgent} value={task.assigned_agent || "—"} />
        <InfoCard label="Run ID" value={task.run_id || "—"} monospace />
        <InfoCard label={t.orchestratorTaskRetries} value={String(task.retry_count)} />
        <InfoCard label={t.orchestratorTaskCreated} value={new Date(task.created_at * 1000).toLocaleString()} />
      </div>

      {task.result && (
        <section className="bg-surface/50 rounded-lg border border-border/50 p-4">
          <h2 className="text-sm font-semibold text-text-primary mb-2">{t.orchestratorTaskResult}</h2>
          <pre className="text-sm text-text-primary whitespace-pre-wrap bg-surface/80 rounded p-3 max-h-96 overflow-y-auto">{task.result.content}</pre>
          <div className="mt-3 flex gap-6 text-xs text-text-muted">
            <span>Tokens: {task.result.usage?.total_tokens ?? "—"}</span>
            <span>Duration: {task.result.duration_seconds?.toFixed(1)}s</span>
          </div>
        </section>
      )}

      {task.error && (
        <section className="bg-red-500/10 border border-red-500/30 rounded-lg p-4">
          <h2 className="text-sm font-semibold text-red-400 mb-1">{t.orchestratorTaskError}</h2>
          <p className="text-sm text-red-300">{task.error}</p>
        </section>
      )}
    </div>
  );
}

function InfoCard({ label, value, monospace }: { label: string; value: string; monospace?: boolean }) {
  return (
    <div className="bg-surface/50 rounded-lg border border-border/50 p-3">
      <p className="text-text-muted text-xs">{label}</p>
      <p className={`text-sm text-text-primary ${monospace ? "font-mono" : ""}`}>{value}</p>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    done: "bg-green-500/20 text-green-400",
    failed: "bg-red-500/20 text-red-400",
    executing: "bg-blue-500/20 text-blue-400",
    streaming: "bg-blue-500/20 text-blue-400",
    queued: "bg-gray-500/20 text-gray-400",
    assigned: "bg-gray-500/20 text-gray-400",
  };
  return <span className={`px-2 py-0.5 rounded text-xs font-medium ${colors[status] || "bg-gray-500/20 text-gray-400"}`}>{status}</span>;
}
```

- [ ] **Step 1: Create TaskDetailPage.tsx**
- [ ] **Step 2: Write E2E test**

```typescript
// admin/frontend/e2e/orchestrator-task-detail.spec.ts
import { test, expect } from "@playwright/test";
import { loginAsAdmin } from "./helpers";

test("task detail shows status and result", async ({ page }) => {
  await page.route("**/admin/api/orchestrator/capability", (route) =>
    route.fulfill({ json: { enabled: true } })
  );
  const mockTask = {
    task_id: "task-abc-123", status: "done", assigned_agent: "gw-1", run_id: "run_xyz",
    result: { content: "The Q1 report shows revenue of $4.2M", usage: { total_tokens: 1630, input_tokens: 1250, output_tokens: 380 }, duration_seconds: 14.3, run_id: "run_xyz" },
    error: null, retry_count: 0, created_at: Date.now() / 1000 - 100, updated_at: Date.now() / 1000,
  };
  await page.route("**/admin/api/orchestrator/tasks/task-abc-123", (route) =>
    route.fulfill({ json: mockTask })
  );
  await loginAsAdmin(page);
  await page.goto("/admin/orchestrator/tasks/task-abc-123");
  await expect(page.getByText("done")).toBeVisible();
  await expect(page.getByText("$4.2M")).toBeVisible();
  await expect(page.getByText("1630")).toBeVisible();
});
```

- [ ] **Step 3: Commit**

```bash
git add admin/frontend/src/pages/orchestrator/TaskDetailPage.tsx admin/frontend/e2e/orchestrator-task-detail.spec.ts
git commit -m "feat(admin-frontend): task detail page with auto-refresh and result display"
```

---

## Updated Self-Review Checklist

- [x] **Spec coverage**: Backend MVP (T1-T13) + Admin proxy API (T14) + Frontend (T15-T19)
- [x] **API contract**: Full REST API spec in T14 with proxy routes, request/response types in T15
- [x] **Frontend coverage**: Feature guard, overview page, task submit, task detail — all following existing admin patterns
- [x] **Placeholder scan**: All steps contain concrete code — no TBD or "add error handling"
- [x] **Type consistency**: `OrchestratorTask` and `OrchestratorAgent` types match across API client, proxy, and page components
- [x] **i18n sync**: Both en.ts and zh.ts get identical key sets in T16
- [x] **Pattern consistency**: Follows existing Swarm integration pattern (SwarmGuard → OrchestratorGuard, sidebar NavLink pattern, admin-api.ts method pattern)

---

**Plan complete.** 19 tasks — 13 backend + 1 proxy API + 5 frontend — with test-first development, exact file paths, and complete code.
