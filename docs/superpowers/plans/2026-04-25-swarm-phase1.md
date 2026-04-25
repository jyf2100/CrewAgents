# Swarm Collaboration Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy Redis infrastructure, implement core swarm messaging/exactly-once/circuit-breaker/degradation, and add Admin Panel swarm overview with SSE real-time updates.

**Architecture:** Redis single-node (AOF + PVC) provides the message bus. Per-Agent Streams + Consumer Groups for durable task delivery; Pub/Sub for advisory wake-ups. Five-layer exactly-once defense. Circuit breaker with graceful degradation to standalone mode. Admin Panel exposes REST + SSE endpoints; frontend uses Zustand stores.

**Tech Stack:** Python 3.11, redis-py[hiredis], FastAPI, React 19, Zustand, EventSource (SSE), K8s manifests

**Design Spec:** `docs/superpowers/specs/2026-04-25-swarm-collaboration-design.md`

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `pyproject.toml` | Add `redis[hiredis]>=5.0` dependency |
| Create | `hermes_agent/swarm/__init__.py` | Package init, public API exports |
| Create | `hermes_agent/swarm/connection_config.py` | Connection pool sizing per agent role |
| Create | `hermes_agent/swarm/redis_connection.py` | Redis connection factory (standalone/Sentinel) |
| Create | `hermes_agent/swarm/health.py` | Redis PING + INFO health check |
| Create | `hermes_agent/swarm/circuit_breaker.py` | CLOSED/OPEN/HALF_OPEN state machine |
| Create | `hermes_agent/swarm/reconnect.py` | Exponential backoff with jitter |
| Create | `hermes_agent/swarm/exactly_once.py` | Dedup, execution guard, cancel, DLQ |
| Create | `hermes_agent/swarm/messaging.py` | Stream ops: publish_task, read_task, ack_task, reclaim_task |
| Create | `hermes_agent/swarm/client.py` | SwarmClient: register, heartbeat, submit, wait |
| Create | `hermes_agent/swarm/resilient_client.py` | Wraps SwarmClient with degradation |
| Create | `hermes_agent/tools/swarm_tool.py` | swarm_delegate tool handler (is_async=False) |
| Modify | `hermes_agent/model_tools.py` | Add `"tools.swarm_tool"` to `_modules` |
| Create | `kubernetes/swarm/redis-config.yaml` | Redis ConfigMap (AOF, maxmemory, etc.) |
| Create | `kubernetes/swarm/redis-secret.yaml` | Redis password Secret |
| Create | `kubernetes/swarm/redis-pv.yaml` | PV + PVC (5Gi, local) |
| Create | `kubernetes/swarm/redis.yaml` | Deployment + Service + redis-exporter sidecar |
| Create | `kubernetes/swarm/redis-networkpolicy.yaml` | Ingress from hermes-agent namespace only |
| Create | `admin/backend/swarm_models.py` | Pydantic models for swarm API |
| Create | `admin/backend/swarm_routes.py` | FastAPI routes (/swarm/capability, agents, metrics, SSE) |
| Modify | `admin/backend/main.py` | Include swarm router |
| Create | `admin/frontend/src/lib/swarm-sse.ts` | EventSource wrapper with reconnection + token refresh |
| Create | `admin/frontend/src/stores/swarmRegistry.ts` | Zustand store for agent registry |
| Create | `admin/frontend/src/stores/swarmEvents.ts` | Zustand store for SSE event lifecycle |
| Create | `admin/frontend/src/components/SwarmGuard.tsx` | Feature flag route guard |
| Create | `admin/frontend/src/components/RedisHealthCard.tsx` | Redis health display card |
| Create | `admin/frontend/src/pages/swarm/SwarmOverviewPage.tsx` | Main swarm overview page |
| Modify | `admin/frontend/src/App.tsx` | Add swarm routes under SwarmGuard |
| Modify | `admin/frontend/src/components/AdminLayout.tsx` | Sidebar swarm section |
| Modify | `admin/frontend/src/i18n/en.ts` | ~20 swarm i18n keys |
| Modify | `admin/frontend/src/i18n/zh.ts` | ~20 swarm i18n keys |
| Create | `tests/test_swarm/__init__.py` | Test package |
| Create | `tests/test_swarm/test_connection.py` | Connection factory + config tests |
| Create | `tests/test_swarm/test_health.py` | Health check tests |
| Create | `tests/test_swarm/test_circuit_breaker.py` | Circuit breaker state machine tests |
| Create | `tests/test_swarm/test_reconnect.py` | Backoff timing tests |
| Create | `tests/test_swarm/test_exactly_once.py` | Dedup + guard + cancel tests |
| Create | `tests/test_swarm/test_messaging.py` | Stream publish/read/ack/reclaim tests |
| Create | `tests/test_swarm/test_client.py` | SwarmClient integration tests |
| Create | `tests/test_swarm/test_resilient.py` | Degradation flow tests |
| Create | `admin/frontend/e2e/swarm.spec.ts` | Admin swarm E2E tests |

---

## Plan A: Redis Infrastructure (Tasks 1–7)

### Task 1: Add redis dependency

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add dependency to pyproject.toml**

In the `[project.optional-dependencies]` section (or main dependencies), add:

```toml
dependencies = [
    # ... existing deps ...
    "redis[hiredis]>=5.0,<6.0",
]
```

If using extras group instead:

```toml
[project.optional-dependencies]
swarm = ["redis[hiredis]>=5.0,<6.0"]
all = ["redis[hiredis]>=5.0,<6.0"]  # add to existing all list
```

- [ ] **Step 2: Install and verify**

```bash
source venv/bin/activate && uv pip install -e ".[all,dev]"
python -c "import redis; print(redis.__version__)"
```
Expected: version string like `5.x.x`

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "chore: add redis[hiredis] dependency for swarm module"
```

---

### Task 2: Create swarm package + connection config

**Files:**
- Create: `hermes_agent/swarm/__init__.py`
- Create: `hermes_agent/swarm/connection_config.py`
- Create: `tests/test_swarm/__init__.py`
- Create: `tests/test_swarm/test_connection.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_swarm/test_connection.py
import pytest
from hermes_agent.swarm.connection_config import ConnectionConfig, compute_pool_size


def test_compute_pool_size_worker():
    cfg = ConnectionConfig(role="worker", max_concurrent_tasks=3)
    assert compute_pool_size(cfg) == 2 + 3  # base(2) + per_task(1)*3


def test_compute_pool_size_supervisor():
    cfg = ConnectionConfig(role="supervisor", max_concurrent_tasks=5)
    assert compute_pool_size(cfg) == 2 + 5 + 4  # base + tasks + supervisor_extra


def test_connection_config_defaults():
    cfg = ConnectionConfig(role="worker", max_concurrent_tasks=2)
    assert cfg.socket_timeout == 5.0
    assert cfg.socket_connect_timeout == 3.0
    assert cfg.retry_on_timeout is True
    assert cfg.health_check_interval == 15


def test_connection_config_rejects_invalid_role():
    with pytest.raises(ValueError):
        ConnectionConfig(role="invalid", max_concurrent_tasks=1)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_swarm/test_connection.py -v
```
Expected: FAIL (module not found)

- [ ] **Step 3: Write minimal implementation**

```python
# hermes_agent/swarm/__init__.py
"""Hermes Swarm Collaboration module."""
```

```python
# hermes_agent/swarm/connection_config.py
from dataclasses import dataclass

_VALID_ROLES = ("worker", "supervisor")


@dataclass(frozen=True)
class ConnectionConfig:
    role: str
    max_concurrent_tasks: int
    socket_timeout: float = 5.0
    socket_connect_timeout: float = 3.0
    retry_on_timeout: bool = True
    health_check_interval: int = 15

    def __post_init__(self):
        if self.role not in _VALID_ROLES:
            raise ValueError(f"Invalid role: {self.role!r}. Must be one of {_VALID_ROLES}")


def compute_pool_size(cfg: ConnectionConfig) -> int:
    base = 2
    per_task = 1
    pool = base + cfg.max_concurrent_tasks * per_task
    if cfg.role == "supervisor":
        pool += 4
    return pool
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/test_swarm/test_connection.py -v
```
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add hermes_agent/swarm/__init__.py hermes_agent/swarm/connection_config.py tests/test_swarm/
git commit -m "feat(swarm): add connection config module with pool sizing"
```

---

### Task 3: Redis connection factory

**Files:**
- Create: `hermes_agent/swarm/redis_connection.py`
- Modify: `tests/test_swarm/test_connection.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_swarm/test_connection.py`:

```python
from unittest.mock import patch, MagicMock
from hermes_agent.swarm.redis_connection import create_redis_pool


def test_create_redis_pool_standalone():
    cfg = ConnectionConfig(role="worker", max_concurrent_tasks=3)
    with patch("hermes_agent.swarm.redis_connection.redis.Redis") as mock_redis_cls:
        mock_instance = MagicMock()
        mock_redis_cls.return_value = mock_instance
        pool = create_redis_pool("redis://localhost:6379/0", cfg)
        mock_redis_cls.assert_called_once()
        call_kwargs = mock_redis_cls.call_args[1]
        assert call_kwargs["max_connections"] == 5  # 2 + 3
        assert call_kwargs["socket_timeout"] == 5.0
        assert call_kwargs["decode_responses"] is True


def test_create_redis_pool_with_password():
    cfg = ConnectionConfig(role="worker", max_concurrent_tasks=2)
    with patch("hermes_agent.swarm.redis_connection.redis.Redis") as mock_redis_cls:
        create_redis_pool("redis://localhost:6379/0", cfg, password="s3cret")
        call_kwargs = mock_redis_cls.call_args[1]
        assert call_kwargs["password"] == "s3cret"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_swarm/test_connection.py::test_create_redis_pool_standalone -v
```
Expected: FAIL (module not found)

- [ ] **Step 3: Write implementation**

```python
# hermes_agent/swarm/redis_connection.py
from __future__ import annotations

import redis

from .connection_config import ConnectionConfig, compute_pool_size


def create_redis_pool(
    url: str,
    cfg: ConnectionConfig,
    password: str | None = None,
) -> redis.Redis:
    return redis.Redis.from_url(
        url,
        password=password,
        max_connections=compute_pool_size(cfg),
        socket_timeout=cfg.socket_timeout,
        socket_connect_timeout=cfg.socket_connect_timeout,
        retry_on_timeout=cfg.retry_on_timeout,
        health_check_interval=cfg.health_check_interval,
        decode_responses=True,
    )
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_swarm/test_connection.py -v
```
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add hermes_agent/swarm/redis_connection.py tests/test_swarm/test_connection.py
git commit -m "feat(swarm): add redis connection factory"
```

---

### Task 4: Redis health check

**Files:**
- Create: `hermes_agent/swarm/health.py`
- Create: `tests/test_swarm/test_health.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_swarm/test_health.py
from unittest.mock import MagicMock
from hermes_agent.swarm.health import check_redis_health, RedisHealth


def test_check_redis_health_ok():
    mock_redis = MagicMock()
    mock_redis.ping.return_value = True
    mock_redis.info.return_value = {
        "redis_version": "7.2.0",
        "connected_clients": 5,
        "used_memory": 100_000_000,
        "maxmemory": 400_000_000,
        "uptime_in_seconds": 86400,
        "aof_enabled": 1,
    }
    health = check_redis_health(mock_redis)
    assert isinstance(health, RedisHealth)
    assert health.connected is True
    assert health.latency_ms >= 0
    assert health.memory_used_percent == pytest.approx(25.0)
    assert health.aof_enabled is True


def test_check_redis_health_unreachable():
    import redis as _redis
    mock_redis = MagicMock()
    mock_redis.ping.side_effect = _redis.ConnectionError("refused")
    health = check_redis_health(mock_redis)
    assert health.connected is False
```

Note: add `import pytest` at top.

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_swarm/test_health.py -v
```
Expected: FAIL

- [ ] **Step 3: Write implementation**

```python
# hermes_agent/swarm/health.py
from __future__ import annotations

import time
from dataclasses import dataclass

import redis as _redis


@dataclass(frozen=True)
class RedisHealth:
    connected: bool
    latency_ms: float = -1.0
    memory_used_percent: float = 0.0
    connected_clients: int = 0
    uptime_seconds: int = 0
    aof_enabled: bool = False
    version: str = ""
    error: str = ""


def check_redis_health(r: _redis.Redis) -> RedisHealth:
    try:
        start = time.monotonic()
        r.ping()
        latency = (time.monotonic() - start) * 1000

        info = r.info()
        maxmem = info.get("maxmemory", 0) or 1
        used = info.get("used_memory", 0)

        return RedisHealth(
            connected=True,
            latency_ms=round(latency, 2),
            memory_used_percent=round(used / maxmem * 100, 1),
            connected_clients=info.get("connected_clients", 0),
            uptime_seconds=info.get("uptime_in_seconds", 0),
            aof_enabled=bool(info.get("aof_enabled", 0)),
            version=info.get("redis_version", "unknown"),
        )
    except (_redis.ConnectionError, _redis.TimeoutError) as exc:
        return RedisHealth(connected=False, error=str(exc))
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_swarm/test_health.py -v
```
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add hermes_agent/swarm/health.py tests/test_swarm/test_health.py
git commit -m "feat(swarm): add redis health check module"
```

---

### Task 5: K8s Redis manifests

**Files:**
- Create: `kubernetes/swarm/redis-config.yaml`
- Create: `kubernetes/swarm/redis-secret.yaml`
- Create: `kubernetes/swarm/redis-pv.yaml`
- Create: `kubernetes/swarm/redis.yaml`

- [ ] **Step 1: Create Redis ConfigMap**

```yaml
# kubernetes/swarm/redis-config.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: hermes-redis-config
  namespace: hermes-agent
data:
  redis.conf: |
    bind 0.0.0.0
    port 6379
    protected-mode no
    timeout 300
    tcp-keepalive 60

    appendonly yes
    appendfilename "appendonly.aof"
    appendfsync everysec
    auto-aof-rewrite-percentage 100
    auto-aof-rewrite-min-size 64mb

    save 900 1
    save 300 10
    save 60 10000
    rdbcompression yes
    dir /data

    maxmemory 384mb
    maxmemory-policy allkeys-lru

    maxclients 200
    slowlog-log-slower-than 10000
    slowlog-max-len 128
```

- [ ] **Step 2: Create Redis Secret template**

```yaml
# kubernetes/swarm/redis-secret.yaml
apiVersion: v1
kind: Secret
metadata:
  name: hermes-redis-secret
  namespace: hermes-agent
type: Opaque
stringData:
  redis-password: CHANGE_ME_GENERATE_WITH_openssl_rand_hex_32
```

- [ ] **Step 3: Create PV + PVC**

```yaml
# kubernetes/swarm/redis-pv.yaml
apiVersion: v1
kind: PersistentVolume
metadata:
  name: hermes-redis-pv
spec:
  capacity:
    storage: 5Gi
  accessModes:
    - ReadWriteOnce
  persistentVolumeReclaimPolicy: Retain
  storageClassName: local-storage
  local:
    path: /data/hermes-redis
  nodeAffinity:
    required:
      nodeSelectorTerms:
        - matchExpressions:
            - key: kubernetes.io/hostname
              operator: In
              values:
                - hermes-node
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: hermes-redis-pvc
  namespace: hermes-agent
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: local-storage
  resources:
    requests:
      storage: 5Gi
  volumeName: hermes-redis-pv
```

- [ ] **Step 4: Create Deployment + Service**

```yaml
# kubernetes/swarm/redis.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: hermes-redis
  namespace: hermes-agent
  labels:
    app: hermes-redis
spec:
  replicas: 1
  strategy:
    type: Recreate
  selector:
    matchLabels:
      app: hermes-redis
  template:
    metadata:
      labels:
        app: hermes-redis
    spec:
      containers:
        - name: redis
          image: redis:7-alpine
          command: ["redis-server", "/etc/redis/redis.conf", "--requirepass", "$(REDIS_PASSWORD)"]
          env:
            - name: REDIS_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: hermes-redis-secret
                  key: redis-password
          ports:
            - containerPort: 6379
          readinessProbe:
            exec:
              command: ["redis-cli", "-a", "$(REDIS_PASSWORD)", "ping"]
            initialDelaySeconds: 5
            periodSeconds: 10
          livenessProbe:
            exec:
              command: ["redis-cli", "-a", "$(REDIS_PASSWORD)", "ping"]
            initialDelaySeconds: 15
            periodSeconds: 20
          resources:
            requests:
              cpu: 100m
              memory: 128Mi
            limits:
              cpu: 500m
              memory: 512Mi
          volumeMounts:
            - name: redis-data
              mountPath: /data
            - name: redis-config
              mountPath: /etc/redis
        - name: redis-exporter
          image: oliver006/redis_exporter:latest
          env:
            - name: REDIS_ADDR
              value: "redis://localhost:6379"
            - name: REDIS_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: hermes-redis-secret
                  key: redis-password
          ports:
            - containerPort: 9121
          resources:
            requests:
              cpu: 50m
              memory: 64Mi
            limits:
              cpu: 200m
              memory: 128Mi
      volumes:
        - name: redis-data
          persistentVolumeClaim:
            claimName: hermes-redis-pvc
        - name: redis-config
          configMap:
            name: hermes-redis-config
---
apiVersion: v1
kind: Service
metadata:
  name: hermes-redis
  namespace: hermes-agent
spec:
  selector:
    app: hermes-redis
  ports:
    - name: redis
      port: 6379
      targetPort: 6379
    - name: metrics
      port: 9121
      targetPort: 9121
```

- [ ] **Step 5: Validate YAML syntax**

```bash
for f in kubernetes/swarm/redis-config.yaml kubernetes/swarm/redis-secret.yaml kubernetes/swarm/redis-pv.yaml kubernetes/swarm/redis.yaml; do
  python -c "import yaml; yaml.safe_load(open('$f'))" && echo "$f: OK"
done
```
Expected: all 4 files print OK

- [ ] **Step 6: Commit**

```bash
mkdir -p kubernetes/swarm
git add kubernetes/swarm/
git commit -m "feat(swarm): add K8s Redis manifests (config, secret, PV, deployment)"
```

---

### Task 6: Redis NetworkPolicy

**Files:**
- Create: `kubernetes/swarm/redis-networkpolicy.yaml`

- [ ] **Step 1: Create NetworkPolicy**

```yaml
# kubernetes/swarm/redis-networkpolicy.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: hermes-redis-netpol
  namespace: hermes-agent
spec:
  podSelector:
    matchLabels:
      app: hermes-redis
  policyTypes:
    - Ingress
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              name: hermes-agent
      ports:
        - protocol: TCP
          port: 6379
        - protocol: TCP
          port: 9121
```

- [ ] **Step 2: Validate and commit**

```bash
python -c "import yaml; yaml.safe_load(open('kubernetes/swarm/redis-networkpolicy.yaml'))" && echo "OK"
git add kubernetes/swarm/redis-networkpolicy.yaml
git commit -m "feat(swarm): add Redis NetworkPolicy"
```

---

### Task 7: Infrastructure integration test

**Files:**
- Create: `tests/test_swarm/test_infrastructure.py`

- [ ] **Step 1: Write integration test (mock Redis)**

```python
# tests/test_swarm/test_infrastructure.py
"""Infrastructure integration test — validates full connection setup with mocked Redis."""
from unittest.mock import patch, MagicMock
from hermes_agent.swarm.connection_config import ConnectionConfig
from hermes_agent.swarm.redis_connection import create_redis_pool
from hermes_agent.swarm.health import check_redis_health


def test_full_connection_health_flow():
    """Simulate: create pool → ping → check health."""
    cfg = ConnectionConfig(role="worker", max_concurrent_tasks=3)

    with patch("hermes_agent.swarm.redis_connection.redis.Redis") as mock_cls:
        mock_redis = MagicMock()
        mock_cls.from_url.return_value = mock_redis
        mock_redis.ping.return_value = True
        mock_redis.info.return_value = {
            "redis_version": "7.2.0",
            "connected_clients": 5,
            "used_memory": 100_000_000,
            "maxmemory": 400_000_000,
            "uptime_in_seconds": 86400,
            "aof_enabled": 1,
        }

        pool = create_redis_pool("redis://hermes-redis:6379/0", cfg, password="test")
        health = check_redis_health(pool)

        assert health.connected is True
        assert health.memory_used_percent == pytest.approx(25.0)
```

- [ ] **Step 2: Run and commit**

```bash
python -m pytest tests/test_swarm/test_infrastructure.py -v
git add tests/test_swarm/test_infrastructure.py
git commit -m "test(swarm): add infrastructure integration test"
```

---

## Plan B: Core Swarm Runtime (Tasks 8–17)

### Task 8: Circuit breaker

**Files:**
- Create: `hermes_agent/swarm/circuit_breaker.py`
- Create: `tests/test_swarm/test_circuit_breaker.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_swarm/test_circuit_breaker.py
import time
from unittest.mock import MagicMock
import redis as _redis
from hermes_agent.swarm.circuit_breaker import CircuitBreaker, CircuitState


def test_starts_closed():
    cb = CircuitBreaker(failure_threshold=3, recovery_timeout=1.0)
    assert cb.state == CircuitState.CLOSED


def test_opens_after_threshold():
    cb = CircuitBreaker(failure_threshold=3, recovery_timeout=1.0)
    for _ in range(3):
        cb.record_failure()
    assert cb.state == CircuitState.OPEN


def test_half_open_after_timeout():
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.1)
    cb.record_failure()
    cb.record_failure()
    assert cb.state == CircuitState.OPEN
    time.sleep(0.15)
    # next call should transition to HALF_OPEN
    result = cb.call(lambda: "ok")
    assert cb.state == CircuitState.HALF_OPEN


def test_closes_after_success_threshold():
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.1, success_threshold=2)
    cb.record_failure()
    cb.record_failure()
    time.sleep(0.15)
    cb.call(lambda: "ok")  # HALF_OPEN
    cb.record_success()
    assert cb.state == CircuitState.CLOSED


def test_call_returns_none_when_open():
    cb = CircuitBreaker(failure_threshold=1, recovery_timeout=10.0)
    cb.record_failure()
    assert cb.state == CircuitState.OPEN
    result = cb.call(lambda: "should not run")
    assert result is None


def test_connection_errors_trigger_failure():
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=1.0)
    fn = MagicMock(side_effect=_redis.ConnectionError("refused"))
    result = cb.call(fn)
    assert result is None
    assert cb.state == CircuitState.OPEN


def test_non_connection_errors_propagate():
    cb = CircuitBreaker(failure_threshold=3, recovery_timeout=1.0)
    with pytest.raises(ValueError):
        cb.call(lambda: (_ for _ in ()).throw(ValueError("bad")))
```

Note: add `import pytest` at top.

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_swarm/test_circuit_breaker.py -v
```
Expected: FAIL

- [ ] **Step 3: Write implementation**

```python
# hermes_agent/swarm/circuit_breaker.py
from __future__ import annotations

import enum
import time
import logging
from typing import Any, Callable

import redis as _redis

logger = logging.getLogger(__name__)

_CONNECTION_ERRORS = (
    _redis.ConnectionError,
    _redis.TimeoutError,
    OSError,
)


class CircuitState(enum.Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    def __init__(
        self,
        failure_threshold: int = 5,
        success_threshold: int = 2,
        recovery_timeout: float = 30.0,
        timeout_per_call: float = 3.0,
    ):
        self._failure_threshold = failure_threshold
        self._success_threshold = success_threshold
        self._recovery_timeout = recovery_timeout
        self._timeout_per_call = timeout_per_call
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: float = 0.0

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN:
            if time.monotonic() - self._last_failure_time >= self._recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                self._success_count = 0
        return self._state

    def record_success(self) -> None:
        self._success_count += 1
        if self._state == CircuitState.HALF_OPEN and self._success_count >= self._success_threshold:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            logger.info("circuit breaker: CLOSED (recovered)")

    def record_failure(self) -> None:
        self._failure_count += 1
        self._last_failure_time = time.monotonic()
        if self._failure_count >= self._failure_threshold:
            self._state = CircuitState.OPEN
            logger.warning("circuit breaker: OPEN (%d failures)", self._failure_count)

    def call(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        current = self.state
        if current == CircuitState.OPEN:
            return None
        try:
            result = fn(*args, **kwargs)
            self.record_success()
            return result
        except _CONNECTION_ERRORS as exc:
            self.record_failure()
            logger.debug("circuit breaker: connection error: %s", exc)
            return None
        except Exception:
            raise
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_swarm/test_circuit_breaker.py -v
```
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add hermes_agent/swarm/circuit_breaker.py tests/test_swarm/test_circuit_breaker.py
git commit -m "feat(swarm): add circuit breaker with CLOSED/OPEN/HALF_OPEN states"
```

---

### Task 9: Reconnect with exponential backoff

**Files:**
- Create: `hermes_agent/swarm/reconnect.py`
- Create: `tests/test_swarm/test_reconnect.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_swarm/test_reconnect.py
from hermes_agent.swarm.reconnect import ReconnectPolicy, compute_backoff


def test_compute_backoff_increases():
    policy = ReconnectPolicy(initial_delay=1.0, max_delay=60.0, multiplier=2.0, jitter=0.1)
    delays = [compute_backoff(policy, attempt) for attempt in range(6)]
    # Without jitter: 1, 2, 4, 8, 16, 32
    for i in range(1, len(delays)):
        assert delays[i] >= delays[i - 1] * (1.0 - policy.jitter)


def test_compute_backoff_capped():
    policy = ReconnectPolicy(initial_delay=1.0, max_delay=10.0, multiplier=2.0, jitter=0.0)
    assert compute_backoff(policy, 100) == 10.0


def test_compute_backoff_jitter_range():
    policy = ReconnectPolicy(initial_delay=1.0, max_delay=60.0, multiplier=2.0, jitter=0.1)
    for _ in range(100):
        d = compute_backoff(policy, 0)
        assert 0.9 <= d <= 1.1  # 1.0 +/- 10%
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_swarm/test_reconnect.py -v
```
Expected: FAIL

- [ ] **Step 3: Write implementation**

```python
# hermes_agent/swarm/reconnect.py
from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True)
class ReconnectPolicy:
    initial_delay: float = 1.0
    max_delay: float = 60.0
    multiplier: float = 2.0
    jitter: float = 0.1


def compute_backoff(policy: ReconnectPolicy, attempt: int) -> float:
    delay = min(policy.initial_delay * (policy.multiplier ** attempt), policy.max_delay)
    jitter_range = delay * policy.jitter
    return delay + random.uniform(-jitter_range, jitter_range)
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_swarm/test_reconnect.py -v
```
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add hermes_agent/swarm/reconnect.py tests/test_swarm/test_reconnect.py
git commit -m "feat(swarm): add exponential backoff reconnect with jitter"
```

---

### Task 10: Exactly-once semantics

**Files:**
- Create: `hermes_agent/swarm/exactly_once.py`
- Create: `tests/test_swarm/test_exactly_once.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_swarm/test_exactly_once.py
from unittest.mock import MagicMock
from hermes_agent.swarm.exactly_once import ExactlyOnceGuard


def test_dedup_allows_first():
    guard = ExactlyOnceGuard(ttl=300)
    mock_redis = MagicMock()
    mock_redis.setnx.return_value = 1
    assert guard.acquire_dedup(mock_redis, "task-123", "agent-1") is True
    mock_redis.setnx.assert_called_once()


def test_dedup_blocks_duplicate():
    guard = ExactlyOnceGuard(ttl=300)
    mock_redis = MagicMock()
    mock_redis.setnx.return_value = 0
    assert guard.acquire_dedup(mock_redis, "task-123", "agent-1") is False


def test_execution_guard_allows_new():
    guard = ExactlyOnceGuard(ttl=600)
    mock_redis = MagicMock()
    mock_redis.setnx.return_value = 1
    assert guard.begin_execution(mock_redis, "task-123", "agent-1") is True


def test_execution_guard_blocks_running():
    guard = ExactlyOnceGuard(ttl=600)
    mock_redis = MagicMock()
    mock_redis.setnx.return_value = 0
    assert guard.begin_execution(mock_redis, "task-123", "agent-1") is False


def test_is_cancelled():
    guard = ExactlyOnceGuard(ttl=300)
    mock_redis = MagicMock()
    mock_redis.exists.return_value = 1
    assert guard.is_cancelled(mock_redis, "task-123") is True


def test_send_to_dlq():
    guard = ExactlyOnceGuard(ttl=300)
    mock_redis = MagicMock()
    guard.send_to_dlq(mock_redis, "task-123", "agent-1", "timeout")
    mock_redis.xadd.assert_called_once()
    args = mock_redis.xadd.call_args
    assert "hermes:stream:swarm.dlq" == args[0][0]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_swarm/test_exactly_once.py -v
```
Expected: FAIL

- [ ] **Step 3: Write implementation**

```python
# hermes_agent/swarm/exactly_once.py
from __future__ import annotations

import json
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class ExactlyOnceGuard:
    dedup_ttl: int = 300
    exec_guard_ttl: int = 600
    cancel_ttl: int = 300
    result_ttl: int = 300

    def acquire_dedup(self, redis_client, task_id: str, sender_id: str) -> bool:
        key = f"hermes:swarm:dedup:{task_id}"
        return bool(redis_client.setnx(key, sender_id, ex=self.dedup_ttl))

    def begin_execution(self, redis_client, task_id: str, agent_id: str) -> bool:
        key = f"hermes:swarm:exec:{task_id}"
        value = json.dumps({"agent_id": agent_id, "started_at": time.time(), "status": "running"})
        return bool(redis_client.setnx(key, value, ex=self.exec_guard_ttl))

    def is_cancelled(self, redis_client, task_id: str) -> bool:
        return bool(redis_client.exists(f"hermes:swarm:cancel:{task_id}"))

    def set_cancel(self, redis_client, task_id: str, reason: str) -> None:
        redis_client.set(f"hermes:swarm:cancel:{task_id}", reason, ex=self.cancel_ttl)

    def write_result(self, redis_client, task_id: str, result_json: str) -> None:
        key = f"hermes:swarm:result:{task_id}"
        redis_client.rpush(key, result_json, ex=self.result_ttl)

    def send_to_dlq(self, redis_client, task_id: str, agent_id: str, reason: str) -> None:
        redis_client.xadd(
            "hermes:stream:swarm.dlq",
            {"task_id": task_id, "agent_id": str(agent_id), "reason": reason, "timestamp": str(time.time())},
            maxlen=10000,
            approximate=True,
        )
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_swarm/test_exactly_once.py -v
```
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add hermes_agent/swarm/exactly_once.py tests/test_swarm/test_exactly_once.py
git commit -m "feat(swarm): add exactly-once guard (dedup, exec guard, cancel, DLQ)"
```

---

### Task 11: Messaging layer (Streams + Pub/Sub)

**Files:**
- Create: `hermes_agent/swarm/messaging.py`
- Create: `tests/test_swarm/test_messaging.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_swarm/test_messaging.py
from unittest.mock import MagicMock, call
from hermes_agent.swarm.messaging import SwarmMessaging


def test_publish_task():
    msg = SwarmMessaging(mock_redis=MagicMock())
    msg._redis.xadd.return_value = "1234567890-0"
    msg._redis.publish.return_value = 1

    msg.publish_task(
        target_agent_id=3,
        task_id="t-001",
        task_type="code-review",
        goal="Review agent_manager.py",
        sender_id=1,
    )

    msg._redis.xadd.assert_called_once()
    stream_name = msg._redis.xadd.call_args[0][0]
    assert stream_name == "hermes:stream:agent.3.tasks"

    msg._redis.publish.assert_called_once()
    channel = msg._redis.publish.call_args[0][0]
    assert channel == "swarm.advisory.task"


def test_read_task():
    mock_redis = MagicMock()
    mock_redis.xreadgroup.return_value = [
        ("hermes:stream:agent.3.tasks", [("12345-0", {"task_id": "t-001", "goal": "test"})])
    ]
    msg = SwarmMessaging(mock_redis=mock_redis)
    messages = msg.read_task(agent_id=3, consumer="c-1", block_ms=1000)
    assert len(messages) == 1
    assert messages[0]["task_id"] == "t-001"


def test_ack_task():
    mock_redis = MagicMock()
    msg = SwarmMessaging(mock_redis=mock_redis)
    msg.ack_task(agent_id=3, group="agent.3.worker", msg_id="12345-0")
    mock_redis.xack.assert_called_once_with(
        "hermes:stream:agent.3.tasks", "agent.3.worker", "12345-0"
    )


def test_reclaim_task():
    mock_redis = MagicMock()
    mock_redis.xpending_range.return_value = [{"message_id": "123-0", "idle": 200000}]
    mock_redis.xclaim.return_value = [("123-0", {"task_id": "t-old"})]
    msg = SwarmMessaging(mock_redis=mock_redis)
    reclaimed = msg.reclaim_tasks(agent_id=3, min_idle_ms=180000, consumer="supervisor-1")
    assert len(reclaimed) == 1
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_swarm/test_messaging.py -v
```
Expected: FAIL

- [ ] **Step 3: Write implementation**

```python
# hermes_agent/swarm/messaging.py
from __future__ import annotations

import json
import time
from typing import Any


class SwarmMessaging:
    MSG_VERSION = "1"
    DEFAULT_MAXLEN = 10000

    def __init__(self, mock_redis: Any = None, redis_client: Any = None):
        self._redis = mock_redis or redis_client

    def publish_task(
        self,
        target_agent_id: int,
        task_id: str,
        task_type: str,
        goal: str,
        sender_id: int,
        capability: str = "",
        input_data: str = "",
        priority: int = 1,
        deadline_ts: float = 0.0,
        trace_id: str = "",
    ) -> str:
        stream = f"hermes:stream:agent.{target_agent_id}.tasks"
        fields = {
            "msg_version": self.MSG_VERSION,
            "task_id": task_id,
            "task_type": task_type,
            "goal": goal,
            "capability": capability,
            "input_data": input_data,
            "sender_id": str(sender_id),
            "priority": str(priority),
            "deadline_ts": str(deadline_ts),
            "trace_id": trace_id,
            "timestamp": str(time.time()),
        }
        msg_id = self._redis.xadd(stream, fields, maxlen=self.DEFAULT_MAXLEN, approximate=True)
        self._redis.publish("swarm.advisory.task", json.dumps({"task_id": task_id, "target": target_agent_id}))
        return msg_id

    def read_task(self, agent_id: int, consumer: str, block_ms: int = 5000, count: int = 1) -> list[dict]:
        stream = f"hermes:stream:agent.{agent_id}.tasks"
        group = f"agent.{agent_id}.worker"
        result = self._redis.xreadgroup(group, consumer, {stream: ">"}, count=count, block=block_ms)
        messages = []
        if result:
            for _, msgs in result:
                for msg_id, fields in msgs:
                    fields["_msg_id"] = msg_id
                    messages.append(fields)
        return messages

    def ack_task(self, agent_id: int, group: str, msg_id: str) -> None:
        stream = f"hermes:stream:agent.{agent_id}.tasks"
        self._redis.xack(stream, group, msg_id)

    def reclaim_tasks(self, agent_id: int, min_idle_ms: int, consumer: str) -> list[dict]:
        stream = f"hermes:stream:agent.{agent_id}.tasks"
        group = f"agent.{agent_id}.worker"
        pending = self._redis.xpending_range(stream, group, min=min_idle_ms, max="+", count=10)
        if not pending:
            return []
        ids = [p["message_id"] for p in pending]
        claimed = self._redis.xclaim(stream, group, consumer, min_idle_time=min_idle_ms, message_ids=ids)
        return [(mid, fields) for mid, fields in claimed]
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_swarm/test_messaging.py -v
```
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add hermes_agent/swarm/messaging.py tests/test_swarm/test_messaging.py
git commit -m "feat(swarm): add messaging layer (Streams + Pub/Sub)"
```

---

### Task 12: SwarmClient core

**Files:**
- Create: `hermes_agent/swarm/client.py`
- Create: `tests/test_swarm/test_client.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_swarm/test_client.py
from unittest.mock import MagicMock, patch
from hermes_agent.swarm.client import SwarmClient


def test_register_writes_registry():
    mock_redis = MagicMock()
    mock_redis.hset.return_value = 1
    client = SwarmClient(agent_id=3, redis_client=mock_redis, capabilities=["code-review"], max_tasks=3)
    client.register(display_name="Agent-3")
    mock_redis.hset.assert_called()
    call_args = mock_redis.hset.call_args
    assert call_args[0][0] == "hermes:registry"


def test_heartbeat_sets_key():
    mock_redis = MagicMock()
    client = SwarmClient(agent_id=3, redis_client=mock_redis, capabilities=[], max_tasks=1)
    client.heartbeat()
    mock_redis.setex.assert_called_once()
    key = mock_redis.setex.call_args[0][0]
    assert key == "hermes:heartbeat:3"


def test_submit_task():
    mock_redis = MagicMock()
    client = SwarmClient(agent_id=1, redis_client=mock_redis, capabilities=[], max_tasks=3)
    with patch.object(client, "_messaging") as mock_msg:
        mock_msg.publish_task.return_value = "msg-001"
        task_id = client.submit_task(target_agent_id=5, task_type="review", goal="Review code")
        assert task_id is not None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_swarm/test_client.py -v
```
Expected: FAIL

- [ ] **Step 3: Write implementation**

```python
# hermes_agent/swarm/client.py
from __future__ import annotations

import json
import time
import uuid
from typing import Any

from .messaging import SwarmMessaging


class SwarmClient:
    def __init__(
        self,
        agent_id: int,
        redis_client: Any,
        capabilities: list[str],
        max_tasks: int = 3,
    ):
        self.agent_id = agent_id
        self._redis = redis_client
        self.capabilities = capabilities
        self.max_tasks = max_tasks
        self._messaging = SwarmMessaging(redis_client=redis_client)

    def register(self, display_name: str = "") -> None:
        profile = {
            "agent_id": str(self.agent_id),
            "display_name": display_name or f"Agent-{self.agent_id}",
            "capabilities": json.dumps(self.capabilities),
            "status": "online",
            "max_concurrent_tasks": str(self.max_tasks),
            "current_tasks": "0",
            "registered_at": str(time.time()),
            "last_heartbeat": str(time.time()),
            "inbox_channel": f"agent.{self.agent_id}.inbox",
        }
        self._redis.hset("hermes:registry", str(self.agent_id), json.dumps(profile))
        self._redis.publish("swarm.advisory.online", json.dumps({"agent_id": self.agent_id}))

    def heartbeat(self) -> None:
        self._redis.setex(f"hermes:heartbeat:{self.agent_id}", 60, str(time.time()))

    def submit_task(
        self,
        target_agent_id: int,
        task_type: str,
        goal: str,
        input_data: str = "",
        timeout: int = 120,
    ) -> str:
        task_id = str(uuid.uuid4())
        self._messaging.publish_task(
            target_agent_id=target_agent_id,
            task_id=task_id,
            task_type=task_type,
            goal=goal,
            sender_id=self.agent_id,
            input_data=input_data,
        )
        return task_id

    def wait_for_result(self, task_id: str, timeout: int = 120) -> dict | None:
        key = f"hermes:swarm:result:{task_id}"
        result = self._redis.blpop(key, timeout=timeout)
        if result:
            _, data = result
            return json.loads(data)
        return None
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_swarm/test_client.py -v
```
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add hermes_agent/swarm/client.py tests/test_swarm/test_client.py
git commit -m "feat(swarm): add SwarmClient with register, heartbeat, submit, wait"
```

---

### Task 13: ResilientSwarmClient with degradation

**Files:**
- Create: `hermes_agent/swarm/resilient_client.py`
- Create: `tests/test_swarm/test_resilient.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_swarm/test_resilient.py
from unittest.mock import MagicMock
from hermes_agent.swarm.resilient_client import ResilientSwarmClient, SwarmMode
from hermes_agent.swarm.client import SwarmClient


def test_starts_in_swarm_mode():
    inner = MagicMock(spec=SwarmClient)
    rclient = ResilientSwarmClient(inner=inner)
    assert rclient.mode == SwarmMode.SWARM


def test_degrades_on_connection_error():
    import redis as _redis
    inner = MagicMock(spec=SwarmClient)
    inner.register.side_effect = _redis.ConnectionError("refused")
    degrade_cb = MagicMock()
    rclient = ResilientSwarmClient(inner=inner, on_degrade=degrade_cb)
    rclient.start()
    assert rclient.mode == SwarmMode.STANDALONE
    degrade_cb.assert_called_once()


def test_submit_returns_none_in_standalone():
    inner = MagicMock(spec=SwarmClient)
    rclient = ResilientSwarmClient(inner=inner)
    rclient._mode = SwarmMode.STANDALONE
    result = rclient.submit_task(target_agent_id=5, task_type="review", goal="test")
    assert result is None


def test_heartbeat_noop_in_standalone():
    inner = MagicMock(spec=SwarmClient)
    rclient = ResilientSwarmClient(inner=inner)
    rclient._mode = SwarmMode.STANDALONE
    rclient.heartbeat()
    inner.heartbeat.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_swarm/test_resilient.py -v
```
Expected: FAIL

- [ ] **Step 3: Write implementation**

```python
# hermes_agent/swarm/resilient_client.py
from __future__ import annotations

import enum
import logging
from typing import Any, Callable

import redis as _redis

from .client import SwarmClient

logger = logging.getLogger(__name__)


class SwarmMode(enum.Enum):
    SWARM = "swarm"
    STANDALONE = "standalone"


class ResilientSwarmClient:
    def __init__(
        self,
        inner: SwarmClient,
        on_degrade: Callable[[], None] | None = None,
        on_recover: Callable[[], None] | None = None,
    ):
        self._inner = inner
        self._mode = SwarmMode.SWARM
        self._on_degrade = on_degrade
        self._on_recover = on_recover

    @property
    def mode(self) -> SwarmMode:
        return self._mode

    def start(self) -> None:
        try:
            self._inner.register()
        except _redis.ConnectionError as exc:
            logger.warning("swarm: Redis unreachable, entering standalone mode: %s", exc)
            self._mode = SwarmMode.STANDALONE
            if self._on_degrade:
                self._on_degrade()

    def heartbeat(self) -> None:
        if self._mode == SwarmMode.STANDALONE:
            return
        try:
            self._inner.heartbeat()
        except _redis.ConnectionError:
            logger.warning("swarm: heartbeat failed, degrading to standalone")
            self._mode = SwarmMode.STANDALONE
            if self._on_degrade:
                self._on_degrade()

    def submit_task(self, target_agent_id: int, task_type: str, goal: str, **kwargs: Any) -> str | None:
        if self._mode == SwarmMode.STANDALONE:
            return None
        try:
            return self._inner.submit_task(target_agent_id=target_agent_id, task_type=task_type, goal=goal, **kwargs)
        except _redis.ConnectionError:
            self._mode = SwarmMode.STANDALONE
            if self._on_degrade:
                self._on_degrade()
            return None

    def wait_for_result(self, task_id: str, timeout: int = 120) -> dict | None:
        if self._mode == SwarmMode.STANDALONE:
            return None
        return self._inner.wait_for_result(task_id, timeout)
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_swarm/test_resilient.py -v
```
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add hermes_agent/swarm/resilient_client.py tests/test_swarm/test_resilient.py
git commit -m "feat(swarm): add ResilientSwarmClient with graceful degradation"
```

---

### Task 14: swarm_delegate tool handler

**Files:**
- Create: `hermes_agent/tools/swarm_tool.py`

- [ ] **Step 1: Write the tool handler**

```python
# hermes_agent/tools/swarm_tool.py
"""
swarm_delegate tool — delegates a task to the best-suited swarm agent.

Uses the three-thread architecture from delegate_tool.py:
  - Tool executor thread (sync, blocks on result)
  - Inner worker thread (runs async Redis operations)
  - Heartbeat daemon thread (keeps agent alive)
"""
from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

logger = logging.getLogger(__name__)

_SWARM_TIMEOUT = 120
_HEARTBEAT_INTERVAL = 30
_HEARTBEAT_TTL = 60

# Module-level reference set by _init_swarm_client during agent startup.
_swarm_client: Any = None


def _init_swarm_client(client: Any) -> None:
    global _swarm_client
    _swarm_client = client


def check_swarm_requirements() -> bool:
    if _swarm_client is None:
        return False
    from hermes_agent.swarm.resilient_client import SwarmMode
    return _swarm_client.mode == SwarmMode.SWARM


def _heartbeat_loop(stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        try:
            if _swarm_client is not None:
                _swarm_client.heartbeat()
        except Exception as exc:
            logger.debug("swarm heartbeat error: %s", exc)
        stop_event.wait(_HEARTBEAT_INTERVAL)


def _swarm_delegate_worker(goal: str, capability: str, input_data: str, target_agent_id: int | None) -> str:
    """Runs in inner worker thread. Returns JSON result string."""
    if _swarm_client is None:
        return json.dumps({"status": "error", "error": "swarm not initialized"})

    task_type = capability
    task_id = _swarm_client.submit_task(
        target_agent_id=target_agent_id or 0,
        task_type=task_type,
        goal=goal,
        input_data=input_data,
    )
    if task_id is None:
        return json.dumps({"status": "error", "error": "swarm unavailable (standalone mode)"})

    result = _swarm_client.wait_for_result(task_id, timeout=_SWARM_TIMEOUT)
    if result is None:
        return json.dumps({"status": "error", "error": f"task {task_id} timed out after {_SWARM_TIMEOUT}s"})

    return json.dumps({"status": "ok", "task_id": task_id, "result": result})


def handle_swarm_delegate(goal: str, capability: str, input_data: str = "", target_agent_id: int | None = None, timeout: int = _SWARM_TIMEOUT) -> str:
    """Tool handler registered in the tool registry."""
    stop_heartbeat = threading.Event()
    heartbeat_thread = threading.Thread(target=_heartbeat_loop, args=(stop_heartbeat,), daemon=True)
    heartbeat_thread.start()

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future: Future[str] = executor.submit(
                _swarm_delegate_worker, goal, capability, input_data, target_agent_id
            )
            return future.result(timeout=timeout + 10)
    except Exception as exc:
        return json.dumps({"status": "error", "error": str(exc)})
    finally:
        stop_heartbeat.set()


SCHEMA = {
    "type": "function",
    "function": {
        "name": "swarm_delegate",
        "description": "将任务委派给蜂群中最合适的 Agent 执行。需要蜂群模式已启用且 Redis 可达。",
        "parameters": {
            "type": "object",
            "properties": {
                "goal": {"type": "string", "description": "任务目标描述"},
                "capability": {"type": "string", "description": "所需能力，如 code-review, data-analysis, translation"},
                "input_data": {"type": "string", "description": "输入数据（可选）", "default": ""},
                "target_agent_id": {"type": "integer", "description": "目标 Agent ID（可选，不指定则自动路由）", "default": None},
                "timeout": {"type": "integer", "description": "超时秒数", "default": 120},
            },
            "required": ["goal", "capability"],
        },
    },
}
```

- [ ] **Step 2: Commit**

```bash
git add hermes_agent/tools/swarm_tool.py
git commit -m "feat(swarm): add swarm_delegate tool with three-thread architecture"
```

---

### Task 15: Register swarm tool in model_tools.py

**Files:**
- Modify: `hermes_agent/model_tools.py`

- [ ] **Step 1: Add module to _modules list**

Find the `_modules` list in `hermes_agent/model_tools.py` and add `"tools.swarm_tool"`:

```python
_modules = [
    # ... existing modules ...
    "tools.swarm_tool",
]
```

- [ ] **Step 2: Verify import works**

```bash
python -c "from hermes_agent.tools.swarm_tool import SCHEMA; print(SCHEMA['function']['name'])"
```
Expected: `swarm_delegate`

- [ ] **Step 3: Commit**

```bash
git add hermes_agent/model_tools.py
git commit -m "feat(swarm): register swarm_tool in model_tools module list"
```

---

### Task 16: Package __init__.py exports

**Files:**
- Modify: `hermes_agent/swarm/__init__.py`

- [ ] **Step 1: Update __init__.py with public API**

```python
# hermes_agent/swarm/__init__.py
"""Hermes Swarm Collaboration module."""

from .connection_config import ConnectionConfig, compute_pool_size
from .redis_connection import create_redis_pool
from .health import RedisHealth, check_redis_health
from .circuit_breaker import CircuitBreaker, CircuitState
from .reconnect import ReconnectPolicy, compute_backoff
from .exactly_once import ExactlyOnceGuard
from .messaging import SwarmMessaging
from .client import SwarmClient
from .resilient_client import ResilientSwarmClient, SwarmMode

__all__ = [
    "ConnectionConfig",
    "compute_pool_size",
    "create_redis_pool",
    "RedisHealth",
    "check_redis_health",
    "CircuitBreaker",
    "CircuitState",
    "ReconnectPolicy",
    "compute_backoff",
    "ExactlyOnceGuard",
    "SwarmMessaging",
    "SwarmClient",
    "ResilientSwarmClient",
    "SwarmMode",
]
```

- [ ] **Step 2: Verify imports**

```bash
python -c "from hermes_agent.swarm import SwarmClient, CircuitBreaker, SwarmMode; print('OK')"
```
Expected: OK

- [ ] **Step 3: Commit**

```bash
git add hermes_agent/swarm/__init__.py
git commit -m "feat(swarm): update __init__.py with public API exports"
```

---

### Task 17: End-to-end flow test

**Files:**
- Create: `tests/test_swarm/test_e2e_flow.py`

- [ ] **Step 1: Write the E2E flow test (all mocks)**

```python
# tests/test_swarm/test_e2e_flow.py
"""End-to-end swarm flow test with mocked Redis."""
import json
from unittest.mock import MagicMock, patch
from hermes_agent.swarm import (
    ConnectionConfig,
    create_redis_pool,
    SwarmClient,
    ResilientSwarmClient,
    SwarmMode,
    ExactlyOnceGuard,
    CircuitBreaker,
)


def test_full_delegation_flow():
    """Agent A registers, submits task to Agent B, B reads + executes, A gets result."""
    cfg = ConnectionConfig(role="worker", max_concurrent_tasks=2)

    mock_redis = MagicMock()
    mock_redis.ping.return_value = True
    mock_redis.info.return_value = {"redis_version": "7.2", "used_memory": 100, "maxmemory": 400, "uptime_in_seconds": 100, "aof_enabled": 1, "connected_clients": 1}
    mock_redis.hset.return_value = 1
    mock_redis.setex.return_value = True
    mock_redis.xadd.return_value = "1000-0"
    mock_redis.publish.return_value = 1
    mock_redis.rpush.return_value = 1
    mock_redis.blpop.return_value = ("hermes:swarm:result:t-001", json.dumps({"status": "completed", "output": "LGTM"}))

    # Agent A (sender)
    client_a = SwarmClient(agent_id=1, redis_client=mock_redis, capabilities=["supervision"], max_tasks=5)
    client_a.register(display_name="Supervisor")

    # Submit task
    task_id = client_a.submit_task(target_agent_id=2, task_type="code-review", goal="Review main.py")
    assert task_id is not None

    # Agent A waits for result
    result = client_a.wait_for_result(task_id, timeout=5)
    assert result is not None
    assert result["status"] == "completed"


def test_degradation_under_failure():
    """When Redis goes down, client degrades gracefully."""
    import redis as _redis
    mock_redis = MagicMock()
    mock_redis.hset.side_effect = _redis.ConnectionError("Connection refused")

    inner = SwarmClient(agent_id=5, redis_client=mock_redis, capabilities=["test"], max_tasks=1)
    degraded = MagicMock()
    rclient = ResilientSwarmClient(inner=inner, on_degrade=degraded)
    rclient.start()

    assert rclient.mode == SwarmMode.STANDALONE
    degraded.assert_called_once()

    # Submit returns None in standalone
    assert rclient.submit_task(target_agent_id=1, task_type="test", goal="x") is None
```

- [ ] **Step 2: Run test**

```bash
python -m pytest tests/test_swarm/test_e2e_flow.py -v
```
Expected: 2 passed

- [ ] **Step 3: Commit**

```bash
git add tests/test_swarm/test_e2e_flow.py
git commit -m "test(swarm): add end-to-end flow test with degradation"
```

---

## Plan C: Admin Panel (Tasks 18–27)

### Task 18: Backend swarm Pydantic models

**Files:**
- Create: `admin/backend/swarm_models.py`

- [ ] **Step 1: Write the models**

```python
# admin/backend/swarm_models.py
from pydantic import BaseModel
from typing import Optional


class SwarmCapabilityResponse(BaseModel):
    enabled: bool


class SwarmAgentProfile(BaseModel):
    agent_id: int
    display_name: str
    capabilities: list[str]
    status: str  # "online" | "offline" | "busy"
    current_tasks: int
    max_concurrent_tasks: int
    last_heartbeat: float
    model: str = ""


class RedisHealthResponse(BaseModel):
    connected: bool
    latency_ms: float = -1.0
    memory_used_percent: float = 0.0
    connected_clients: int = 0
    uptime_seconds: int = 0
    aof_enabled: bool = False
    version: str = ""


class StreamInfo(BaseModel):
    stream_name: str
    length: int
    pending_count: int


class SwarmMetricsResponse(BaseModel):
    timestamp: float
    swarm_enabled: bool
    agents: list[SwarmAgentProfile]
    agents_online: int
    agents_offline: int
    agents_busy: int
    queues: dict
    redis_health: RedisHealthResponse
    tasks_submitted_last_5m: int = 0
    tasks_completed_last_5m: int = 0
    tasks_failed_last_5m: int = 0


class SSETokenResponse(BaseModel):
    token: str
    expires_in: int
```

- [ ] **Step 2: Verify**

```bash
cd admin/backend && python -c "from swarm_models import SwarmMetricsResponse; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add admin/backend/swarm_models.py
git commit -m "feat(admin): add swarm Pydantic models for API"
```

---

### Task 19: Backend swarm routes

**Files:**
- Create: `admin/backend/swarm_routes.py`

- [ ] **Step 1: Write the routes**

```python
# admin/backend/swarm_routes.py
from fastapi import APIRouter, Query, Request
from typing import Optional

from swarm_models import (
    SwarmCapabilityResponse,
    SwarmAgentProfile,
    SwarmMetricsResponse,
    RedisHealthResponse,
    SSETokenResponse,
)

router = APIRouter(prefix="/swarm", tags=["swarm"])


def _get_redis(request: Request):
    return request.app.state.swarm_redis


@router.get("/capability", response_model=SwarmCapabilityResponse)
async def get_capability(request: Request):
    redis = _get_redis(request)
    if redis is None:
        return SwarmCapabilityResponse(enabled=False)
    try:
        redis.ping()
        return SwarmCapabilityResponse(enabled=True)
    except Exception:
        return SwarmCapabilityResponse(enabled=False)


@router.get("/agents", response_model=list[SwarmAgentProfile])
async def get_swarm_agents(request: Request):
    redis = _get_redis(request)
    if redis is None:
        return []
    agents = []
    raw = redis.hgetall("hermes:registry")
    for agent_id_str, profile_json in raw.items():
        import json
        profile = json.loads(profile_json)
        agents.append(SwarmAgentProfile(
            agent_id=int(profile.get("agent_id", agent_id_str)),
            display_name=profile.get("display_name", f"Agent-{agent_id_str}"),
            capabilities=json.loads(profile.get("capabilities", "[]")),
            status=profile.get("status", "unknown"),
            current_tasks=int(profile.get("current_tasks", 0)),
            max_concurrent_tasks=int(profile.get("max_concurrent_tasks", 3)),
            last_heartbeat=float(profile.get("last_heartbeat", 0)),
            model=profile.get("model", ""),
        ))
    return agents


@router.get("/metrics", response_model=SwarmMetricsResponse)
async def get_swarm_metrics(request: Request):
    import time
    redis = _get_redis(request)
    if redis is None:
        return SwarmMetricsResponse(
            timestamp=time.time(), swarm_enabled=False, agents=[],
            agents_online=0, agents_offline=0, agents_busy=0,
            queues={}, redis_health=RedisHealthResponse(connected=False),
        )

    redis.ping()
    info = redis.info()
    agents = await get_swarm_agents(request)

    online = sum(1 for a in agents if a.status == "online")
    offline = sum(1 for a in agents if a.status == "offline")
    busy = sum(1 for a in agents if a.status == "busy")

    return SwarmMetricsResponse(
        timestamp=time.time(),
        swarm_enabled=True,
        agents=agents,
        agents_online=online,
        agents_offline=offline,
        agents_busy=busy,
        queues={"streams": [], "total_pending": 0},
        redis_health=RedisHealthResponse(
            connected=True,
            latency_ms=0,
            memory_used_percent=round(info.get("used_memory", 0) / max(info.get("maxmemory", 1), 1) * 100, 1),
            connected_clients=info.get("connected_clients", 0),
            uptime_seconds=info.get("uptime_in_seconds", 0),
            aof_enabled=bool(info.get("aof_enabled", 0)),
            version=info.get("redis_version", ""),
        ),
    )


@router.post("/events/token", response_model=SSETokenResponse)
async def create_sse_token(request: Request):
    import secrets
    redis = _get_redis(request)
    token = f"sse_{secrets.token_hex(16)}"
    ttl = 1800
    if redis:
        redis.setex(f"hermes:sse:token:{token}", ttl, "valid")
    return SSETokenResponse(token=token, expires_in=ttl)


@router.get("/events/stream")
async def sse_stream(request: Request, token: str = Query(...)):
    from fastapi.responses import StreamingResponse
    import asyncio
    import json

    redis = _get_redis(request)
    if redis is None:
        return StreamingResponse(iter(["data: {\"error\": \"redis unavailable\"}\n\n"]), media_type="text/event-stream")

    stored = redis.get(f"hermes:sse:token:{token}")
    if stored is None:
        return StreamingResponse(iter(["data: {\"error\": \"invalid token\"}\n\n"]), media_type="text/event-stream")

    redis.delete(f"hermes:sse:token:{token}")

    async def event_generator():
        seq = 0
        try:
            while True:
                seq += 1
                yield f"id: {seq}\nevent: heartbeat\ndata: {{}}\n\n"
                await asyncio.sleep(30)
        except asyncio.CancelledError:
            pass

    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

- [ ] **Step 2: Commit**

```bash
git add admin/backend/swarm_routes.py
git commit -m "feat(admin): add swarm FastAPI routes (capability, agents, metrics, SSE)"
```

---

### Task 20: Include swarm router in main.py

**Files:**
- Modify: `admin/backend/main.py`

- [ ] **Step 1: Add swarm router import and include**

In `admin/backend/main.py`, add the swarm router. Find the section where other routers are included and add:

```python
from swarm_routes import router as swarm_router
app.include_router(swarm_router, prefix="/admin/api")
```

Also initialize the Redis connection on app startup. In the lifespan or startup event:

```python
import os
import redis

@app.on_event("startup")
async def init_swarm_redis():
    redis_url = os.environ.get("SWARM_REDIS_URL", "")
    if redis_url:
        try:
            r = redis.from_url(redis_url, decode_responses=True, socket_connect_timeout=3)
            r.ping()
            app.state.swarm_redis = r
        except Exception:
            app.state.swarm_redis = None
    else:
        app.state.swarm_redis = None
```

- [ ] **Step 2: Verify**

```bash
cd admin/backend && python -c "from main import app; print([r.path for r in app.routes if '/swarm' in str(getattr(r, 'path', ''))])"
```

- [ ] **Step 3: Commit**

```bash
git add admin/backend/main.py
git commit -m "feat(admin): include swarm router and init Redis connection"
```

---

### Task 21: Frontend SSE wrapper

**Files:**
- Create: `admin/frontend/src/lib/swarm-sse.ts`

- [ ] **Step 1: Write the SSE wrapper**

```typescript
// admin/frontend/src/lib/swarm-sse.ts

const RECONNECT_BASE_DELAY = 1000;
const RECONNECT_MAX_DELAY = 30000;
const MAX_RECONNECT_ATTEMPTS = 10;
const HEARTBEAT_TIMEOUT_MS = 60000;
const TOKEN_REFRESH_MARGIN_MS = 60000;

export interface SwarmSSEConfig {
  baseUrl: string;
  getToken: () => Promise<string>;
  onEvent: (type: string, data: unknown) => void;
  onConnectionChange?: (connected: boolean) => void;
}

export class SwarmSSE {
  private es: EventSource | null = null;
  private config: SwarmSSEConfig;
  private token = "";
  private tokenExpiresAt = 0;
  private reconnectAttempts = 0;
  private heartbeatTimer: ReturnType<typeof setTimeout> | null = null;
  private tokenRefreshTimer: ReturnType<typeof setTimeout> | null = null;
  private stopped = false;
  private lastEventId = "";

  constructor(config: SwarmSSEConfig) {
    this.config = config;
  }

  async connect(): Promise<void> {
    this.stopped = false;
    await this.refreshToken();
    this.createEventSource();
  }

  stop(): void {
    this.stopped = true;
    this.cleanup();
  }

  private async refreshToken(): Promise<void> {
    this.token = await this.config.getToken();
    this.tokenExpiresAt = Date.now() + 1800 * 1000;

    this.tokenRefreshTimer = setTimeout(async () => {
      if (!this.stopped) {
        await this.refreshToken();
        this.lastEventId = this.es?.readyState === EventSource.OPEN
          ? this.lastEventId
          : "";
        this.cleanup();
        this.createEventSource();
      }
    }, 1800 * 1000 - TOKEN_REFRESH_MARGIN_MS);
  }

  private createEventSource(): void {
    const url = new URL(`${this.config.baseUrl}/admin/api/swarm/events/stream`);
    url.searchParams.set("token", this.token);
    if (this.lastEventId) {
      url.searchParams.set("lastEventId", this.lastEventId);
    }

    this.es = new EventSource(url.toString());

    this.es.onopen = () => {
      this.reconnectAttempts = 0;
      this.config.onConnectionChange?.(true);
      this.resetHeartbeatTimeout();
    };

    this.es.onmessage = (e) => {
      this.lastEventId = e.lastEventId;
      this.config.onEvent(e.type || "message", JSON.parse(e.data));
      this.resetHeartbeatTimeout();
    };

    this.es.onerror = () => {
      this.config.onConnectionChange?.(false);
      this.es?.close();
      if (!this.stopped) {
        this.scheduleReconnect();
      }
    };
  }

  private resetHeartbeatTimeout(): void {
    if (this.heartbeatTimer) clearTimeout(this.heartbeatTimer);
    this.heartbeatTimer = setTimeout(() => {
      if (!this.stopped) {
        this.es?.close();
        this.scheduleReconnect();
      }
    }, HEARTBEAT_TIMEOUT_MS);
  }

  private scheduleReconnect(): void {
    if (this.reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) return;
    const delay = Math.min(
      RECONNECT_BASE_DELAY * Math.pow(2, this.reconnectAttempts),
      RECONNECT_MAX_DELAY,
    );
    this.reconnectAttempts++;
    setTimeout(() => {
      if (!this.stopped) this.connect();
    }, delay);
  }

  private cleanup(): void {
    this.es?.close();
    this.es = null;
    if (this.heartbeatTimer) clearTimeout(this.heartbeatTimer);
    if (this.tokenRefreshTimer) clearTimeout(this.tokenRefreshTimer);
  }
}
```

- [ ] **Step 2: Commit**

```bash
git add admin/frontend/src/lib/swarm-sse.ts
git commit -m "feat(admin): add SwarmSSE wrapper with reconnection and token refresh"
```

---

### Task 22: Zustand swarmRegistry store

**Files:**
- Create: `admin/frontend/src/stores/swarmRegistry.ts`

- [ ] **Step 1: Write the store**

```typescript
// admin/frontend/src/stores/swarmRegistry.ts
import { create } from "zustand";
import { adminFetch } from "../lib/admin-api";

export interface SwarmAgent {
  agent_id: number;
  display_name: string;
  capabilities: string[];
  status: "online" | "offline" | "busy";
  current_tasks: number;
  max_concurrent_tasks: number;
  last_heartbeat: number;
  model: string;
}

interface SwarmRegistryState {
  agents: SwarmAgent[];
  loading: boolean;
  error: string | null;
  fetchAgents: () => Promise<void>;
  handleEvent: (type: string, data: unknown) => void;
}

export const useSwarmRegistry = create<SwarmRegistryState>((set) => ({
  agents: [],
  loading: false,
  error: null,

  fetchAgents: async () => {
    set({ loading: true, error: null });
    try {
      const res = await adminFetch("/admin/api/swarm/agents");
      const agents: SwarmAgent[] = await res.json();
      set({ agents, loading: false });
    } catch (e: unknown) {
      set({ error: String(e), loading: false });
    }
  },

  handleEvent: (type, data) => {
    const d = data as Record<string, unknown>;
    if (type === "agent_online" || type === "agent_offline") {
      set((state) => {
        const agentId = d.agent_id as number;
        const status = type === "agent_online" ? "online" : "offline";
        return {
          agents: state.agents.map((a) =>
            a.agent_id === agentId ? { ...a, status: status as SwarmAgent["status"] } : a,
          ),
        };
      });
    }
  },
}));
```

- [ ] **Step 2: Commit**

```bash
mkdir -p admin/frontend/src/stores
git add admin/frontend/src/stores/swarmRegistry.ts
git commit -m "feat(admin): add Zustand swarmRegistry store"
```

---

### Task 23: Zustand swarmEvents store

**Files:**
- Create: `admin/frontend/src/stores/swarmEvents.ts`

- [ ] **Step 1: Write the store**

```typescript
// admin/frontend/src/stores/swarmEvents.ts
import { create } from "zustand";
import { SwarmSSE } from "../lib/swarm-sse";
import { adminFetch } from "../lib/admin-api";

interface SwarmEventsState {
  connected: boolean;
  sse: SwarmSSE | null;
  connect: (baseUrl: string) => Promise<void>;
  disconnect: () => void;
}

export const useSwarmEvents = create<SwarmEventsState>((set, get) => ({
  connected: false,
  sse: null,

  connect: async (baseUrl: string) => {
    const existing = get().sse;
    if (existing) return;

    const sse = new SwarmSSE({
      baseUrl,
      getToken: async () => {
        const res = await adminFetch("/admin/api/swarm/events/token", { method: "POST" });
        const data = await res.json();
        return data.token;
      },
      onEvent: (type, data) => {
        const { useSwarmRegistry } = require("./swarmRegistry") as typeof import("./swarmRegistry");
        useSwarmRegistry.getState().handleEvent(type, data);
      },
      onConnectionChange: (connected) => set({ connected }),
    });

    set({ sse });
    await sse.connect();
  },

  disconnect: () => {
    get().sse?.stop();
    set({ sse: null, connected: false });
  },
}));
```

- [ ] **Step 2: Commit**

```bash
git add admin/frontend/src/stores/swarmEvents.ts
git commit -m "feat(admin): add Zustand swarmEvents store for SSE lifecycle"
```

---

### Task 24: SwarmGuard + RedisHealthCard

**Files:**
- Create: `admin/frontend/src/components/SwarmGuard.tsx`
- Create: `admin/frontend/src/components/RedisHealthCard.tsx`

- [ ] **Step 1: Write SwarmGuard**

```tsx
// admin/frontend/src/components/SwarmGuard.tsx
import { useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { adminFetch } from "../lib/admin-api";

export function SwarmGuard({ children }: { children: React.ReactNode }) {
  const [enabled, setEnabled] = useState<boolean | null>(null);

  useEffect(() => {
    adminFetch("/admin/api/swarm/capability")
      .then((r) => r.json())
      .then((d) => setEnabled(d.enabled))
      .catch(() => setEnabled(false));
  }, []);

  if (enabled === null) return null;
  if (!enabled) return <Navigate to="/" replace />;
  return <>{children}</>;
}
```

- [ ] **Step 2: Write RedisHealthCard**

```tsx
// admin/frontend/src/components/RedisHealthCard.tsx
import { useTranslation } from "react-i18n-markdown";

interface RedisHealth {
  connected: boolean;
  latency_ms: number;
  memory_used_percent: number;
  connected_clients: number;
  uptime_seconds: number;
  aof_enabled: boolean;
  version: string;
}

export function RedisHealthCard({ health }: { health: RedisHealth }) {
  const { t } = useTranslation();
  const statusColor = health.connected
    ? "text-green-400"
    : "text-red-400";

  return (
    <div className="glass rounded-xl p-4">
      <h3 className="text-sm font-semibold text-text-secondary mb-2">
        Redis {t("swarmHealth")}
      </h3>
      <div className="space-y-1 text-sm">
        <div className="flex justify-between">
          <span>Status</span>
          <span className={statusColor}>
            {health.connected ? "Connected" : "Disconnected"}
          </span>
        </div>
        {health.connected && (
          <>
            <div className="flex justify-between">
              <span>Latency</span>
              <span>{health.latency_ms.toFixed(1)} ms</span>
            </div>
            <div className="flex justify-between">
              <span>Memory</span>
              <span>{health.memory_used_percent.toFixed(1)}%</span>
            </div>
            <div className="flex justify-between">
              <span>Clients</span>
              <span>{health.connected_clients}</span>
            </div>
            <div className="flex justify-between">
              <span>Version</span>
              <span>{health.version}</span>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add admin/frontend/src/components/SwarmGuard.tsx admin/frontend/src/components/RedisHealthCard.tsx
git commit -m "feat(admin): add SwarmGuard route guard and RedisHealthCard"
```

---

### Task 25: SwarmOverviewPage

**Files:**
- Create: `admin/frontend/src/pages/swarm/SwarmOverviewPage.tsx`

- [ ] **Step 1: Write the page**

```tsx
// admin/frontend/src/pages/swarm/SwarmOverviewPage.tsx
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18n-markdown";
import { useSwarmRegistry } from "../../stores/swarmRegistry";
import { adminFetch } from "../../lib/admin-api";
import { RedisHealthCard } from "../../components/RedisHealthCard";

interface SwarmMetrics {
  agents_online: number;
  agents_offline: number;
  agents_busy: number;
  redis_health: {
    connected: boolean;
    latency_ms: number;
    memory_used_percent: number;
    connected_clients: number;
    uptime_seconds: number;
    aof_enabled: boolean;
    version: string;
  };
}

export default function SwarmOverviewPage() {
  const { t } = useTranslation();
  const { agents, loading, fetchAgents } = useSwarmRegistry();
  const [metrics, setMetrics] = useState<SwarmMetrics | null>(null);

  useEffect(() => {
    fetchAgents();
    adminFetch("/admin/api/swarm/metrics")
      .then((r) => r.json())
      .then(setMetrics)
      .catch(() => {});
  }, [fetchAgents]);

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold glow-pink-text">{t("swarmOverview")}</h1>

      {/* Stats row */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <StatCard label="Online" value={metrics?.agents_online ?? 0} color="text-green-400" />
        <StatCard label="Busy" value={metrics?.agents_busy ?? 0} color="text-cyan-400" />
        <StatCard label="Offline" value={metrics?.agents_offline ?? 0} color="text-gray-400" />
        <StatCard label="Total" value={agents.length} color="text-white" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Agent grid */}
        <div className="lg:col-span-2">
          <h2 className="text-lg font-semibold mb-3">{t("swarmAgents")}</h2>
          {loading ? (
            <div className="text-text-secondary">{t("loading")}</div>
          ) : agents.length === 0 ? (
            <div className="text-text-secondary">{t("swarmNoAgents")}</div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {agents.map((agent) => (
                <AgentCard key={agent.agent_id} agent={agent} />
              ))}
            </div>
          )}
        </div>

        {/* Redis health */}
        <div>
          {metrics?.redis_health && <RedisHealthCard health={metrics.redis_health} />}
        </div>
      </div>
    </div>
  );
}

function StatCard({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div className="glass rounded-xl p-4 text-center">
      <div className={`text-3xl font-bold ${color}`}>{value}</div>
      <div className="text-sm text-text-secondary">{label}</div>
    </div>
  );
}

function AgentCard({ agent }: { agent: import("../../stores/swarmRegistry").SwarmAgent }) {
  const statusColor =
    agent.status === "online" ? "bg-green-400" :
    agent.status === "busy" ? "bg-cyan-400" :
    "bg-gray-500";

  return (
    <div className="glass rounded-xl p-4">
      <div className="flex items-center justify-between mb-2">
        <span className="font-semibold">{agent.display_name}</span>
        <span className={`w-2 h-2 rounded-full ${statusColor}`} />
      </div>
      <div className="text-xs text-text-secondary mb-2">Agent #{agent.agent_id}</div>
      <div className="flex flex-wrap gap-1">
        {agent.capabilities.map((cap) => (
          <span key={cap} className="text-xs bg-accent-cyan/10 text-accent-cyan px-2 py-0.5 rounded">
            {cap}
          </span>
        ))}
      </div>
      <div className="mt-2 text-xs text-text-secondary">
        Load: {agent.current_tasks}/{agent.max_concurrent_tasks}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
mkdir -p admin/frontend/src/pages/swarm
git add admin/frontend/src/pages/swarm/SwarmOverviewPage.tsx
git commit -m "feat(admin): add SwarmOverviewPage with agent grid and Redis health"
```

---

### Task 26: App routing, sidebar, and i18n

**Files:**
- Modify: `admin/frontend/src/App.tsx`
- Modify: `admin/frontend/src/components/AdminLayout.tsx`
- Modify: `admin/frontend/src/i18n/en.ts`
- Modify: `admin/frontend/src/i18n/zh.ts`

- [ ] **Step 1: Add swarm routes to App.tsx**

Import and add under a `SwarmGuard` wrapper:

```tsx
import { SwarmGuard } from "./components/SwarmGuard";
import SwarmOverviewPage from "./pages/swarm/SwarmOverviewPage";

// In the routes section, add:
<Route element={<SwarmGuard><Outlet /></SwarmGuard>}>
  <Route path="/swarm" element={<SwarmOverviewPage />} />
</Route>
```

Note: `Outlet` is from `react-router-dom`.

- [ ] **Step 2: Add swarm section to AdminLayout sidebar**

Find the sidebar navigation section and add:

```tsx
{/* Swarm section */}
<div className="px-4 py-2 text-xs uppercase text-text-secondary tracking-wider">
  Swarm
</div>
<NavLink to="/swarm" className={({ isActive }) => `flex items-center gap-3 px-4 py-2 rounded-lg ${isActive ? "bg-accent-cyan/10 text-accent-cyan" : "text-text-secondary hover:text-white"}`}>
  {/* IconSwarm SVG */}
  <svg viewBox="0 0 24 24" className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth="1.5">
    <circle cx="12" cy="5" r="2.5" />
    <circle cx="5" cy="14" r="2.5" />
    <circle cx="19" cy="14" r="2.5" />
    <circle cx="8" cy="20" r="2.5" />
    <circle cx="16" cy="20" r="2.5" />
    <line x1="12" y1="7.5" x2="5" y2="11.5" />
    <line x1="12" y1="7.5" x2="19" y2="11.5" />
    <line x1="5" y1="14" x2="8" y2="17.5" />
    <line x1="19" y1="14" x2="16" y2="17.5" />
    <line x1="8" y1="20" x2="16" y2="20" />
  </svg>
  Swarm Overview
</NavLink>
```

- [ ] **Step 3: Add i18n keys to en.ts**

```typescript
// Add to the swarm section of en.ts:
swarmOverview: "Swarm Overview",
swarmAgents: "Swarm Agents",
swarmNoAgents: "No swarm agents registered",
swarmHealth: "Health",
swarmConnected: "Connected",
swarmDisconnected: "Disconnected",
swarmReconnecting: "Reconnecting...",
navSwarm: "Swarm",
```

- [ ] **Step 4: Add i18n keys to zh.ts**

```typescript
swarmOverview: "蜂群概览",
swarmAgents: "蜂群 Agent",
swarmNoAgents: "没有已注册的蜂群 Agent",
swarmHealth: "健康状态",
swarmConnected: "已连接",
swarmDisconnected: "已断开",
swarmReconnecting: "重新连接中...",
navSwarm: "蜂群",
```

- [ ] **Step 5: Commit**

```bash
git add admin/frontend/src/App.tsx admin/frontend/src/components/AdminLayout.tsx admin/frontend/src/i18n/en.ts admin/frontend/src/i18n/zh.ts
git commit -m "feat(admin): add swarm routing, sidebar section, and i18n keys"
```

---

### Task 27: Build verification + E2E test

**Files:**
- Create: `admin/frontend/e2e/swarm.spec.ts`

- [ ] **Step 1: Verify frontend build**

```bash
cd admin/frontend && npx tsc --noEmit && npm run build
```
Expected: no errors

- [ ] **Step 2: Write E2E test**

```typescript
// admin/frontend/e2e/swarm.spec.ts
import { test, expect } from "@playwright/test";

test.describe("Swarm Overview", () => {
  test.beforeEach(async ({ page }) => {
    await page.route("**/admin/api/login", async (route) => {
      await route.fulfill({ status: 200, body: JSON.stringify({ success: true }) });
    });
    await page.route("**/admin/api/swarm/capability", async (route) => {
      await route.fulfill({ status: 200, body: JSON.stringify({ enabled: true }) });
    });
    await page.route("**/admin/api/swarm/agents", async (route) => {
      await route.fulfill({
        status: 200,
        body: JSON.stringify([
          { agent_id: 1, display_name: "Supervisor", capabilities: ["supervision"], status: "online", current_tasks: 0, max_concurrent_tasks: 5, last_heartbeat: Date.now() / 1000, model: "claude-sonnet" },
          { agent_id: 3, display_name: "Code Reviewer", capabilities: ["code-review", "refactoring"], status: "busy", current_tasks: 2, max_concurrent_tasks: 3, last_heartbeat: Date.now() / 1000, model: "claude-sonnet" },
        ]),
      });
    });
    await page.route("**/admin/api/swarm/metrics", async (route) => {
      await route.fulfill({
        status: 200,
        body: JSON.stringify({
          agents_online: 1, agents_offline: 0, agents_busy: 1,
          redis_health: { connected: true, latency_ms: 1.2, memory_used_percent: 5.3, connected_clients: 3, uptime_seconds: 86400, aof_enabled: true, version: "7.2.0" },
        }),
      });
    });
  });

  test("shows swarm overview with agent cards", async ({ page }) => {
    await page.goto("/swarm");
    await expect(page.getByText("Supervisor")).toBeVisible();
    await expect(page.getByText("Code Reviewer")).toBeVisible();
    await expect(page.getByText("code-review")).toBeVisible();
  });

  test("shows Redis health card", async ({ page }) => {
    await page.goto("/swarm");
    await expect(page.getByText("Connected")).toBeVisible();
    await expect(page.getByText("7.2.0")).toBeVisible();
  });

  test("hides swarm when capability returns false", async ({ page }) => {
    await page.route("**/admin/api/swarm/capability", async (route) => {
      await route.fulfill({ status: 200, body: JSON.stringify({ enabled: false }) });
    });
    await page.goto("/swarm");
    await expect(page).toHaveURL(/\/$/);
  });
});
```

- [ ] **Step 3: Run E2E test**

```bash
cd admin/frontend && npx playwright test e2e/swarm.spec.ts
```
Expected: 3 passed

- [ ] **Step 4: Commit**

```bash
git add admin/frontend/e2e/swarm.spec.ts
git commit -m "test(admin): add swarm E2E tests (overview, health, capability guard)"
```

---

## Self-Review Checklist

- [x] **Spec coverage**: Every section in the design spec Phase 1 has a corresponding task
- [x] **Placeholder scan**: No TBD, TODO, or "implement later" placeholders
- [x] **Path consistency**: All paths use `hermes_agent/` (not `hermes/`)
- [x] **Type consistency**: SwarmClient constructor signature matches across client.py, resilient_client.py, and swarm_tool.py
- [x] **Import consistency**: All cross-module imports use relative paths within `hermes_agent/swarm/`
