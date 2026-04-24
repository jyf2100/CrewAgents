# Hermes Agent K8s 多用户沙箱部署 - Critical 问题修复设计

**Date:** 2026-04-14
**Status:** Draft
**Authors:** K8s Expert + Architecture Expert

---

## 1. 概述

代码审查发现 3 个 Critical 问题和 6 个 Important 问题。本文档设计修复方案。

---

## 2. Critical 问题修复

### 2.1 Endpoints 命名不匹配（Critical #1）

**问题：** Gateway 查询 Endpoints 用 `user_id`（如 `alice`），但 registry-init 注册用 `POD_NAME`（如 `sandbox-alice-5f4b9c7d6-r8s9m`）。沙箱发现机制完全失效。

**修复方案：** Gateway 通过 OpenSandbox BatchSandbox CRD 的 label selector 查找 pod，再获取 Endpoints。

**架构：**
```
Gateway.get_sandbox_url(user_id)
  1. list_namespaced_custom_object("batchsandboxes", label_selector=f"user_id={user_id}")
     → 获取 BatchSandbox，name = "sandbox-{user_id}"
  2. read_namespaced_pod(name="sandbox-{user_id}")
     → 获取 Pod IP
  3. 返回 "http://{pod_ip}:8642"
```

**文件修改：**
- `gateway/sandbox_router.py`:
  - `get_sandbox_url(user_id)`: 改为先查 BatchSandbox label，再查 Pod IP
  - 添加 `get_pod_ip_from_batchsandbox(user_id)` 辅助方法

**代码：**
```python
def get_sandbox_url(self, user_id: str) -> Optional[str]:
    """通过 BatchSandbox label selector 查找 pod IP"""
    try:
        # 1. 查找用户的 BatchSandbox
        batch_sandboxes = self.sandbox_v1.list_namespaced_custom_object(
            group="sandbox.opensandbox.io",
            version="v1alpha1",
            namespace=K8S_NAMESPACE,
            plural="batchsandboxes",
            label_selector=f"user_id={user_id}"
        )
        items = batch_sandboxes.get("items", [])
        if not items:
            return None
        batch_name = items[0]["metadata"]["name"]

        # 2. 获取 Pod IP
        pod = self.core_v1.read_namespaced_pod(
            name=batch_name,
            namespace=K8S_NAMESPACE
        )
        pod_ip = pod.status.pod_ip
        if not pod_ip:
            return None
        return f"http://{pod_ip}:8642"
    except ApiException as e:
        if e.status == 404:
            return None
        raise
    except Exception:
        return None
```

**注意：** `wait_for_sandbox(user_id)` 不变，因为 OpenSandbox Pool 会创建 pod，Endpoints 注册后端点就存在了。

---

### 2.2 Init Container 等待逻辑错误（Critical #2）

**问题：** init container 在主容器之前运行，等待 `localhost:8642` 会 60 秒超时后跳过注册。

**修复方案：** 主容器 postStart hook 写标记文件到共享 volume，init container 轮询检查该文件。

**架构：**
```
Pod 启动顺序：
1. initContainer (registry-init) 启动
2. initContainer 轮询 /shared/registry_done 文件
3. 主容器 (sandbox) 启动，postStart hook 等待 Hermes 就绪后写 /shared/registry_done
4. initContainer 检测到文件，注册 Endpoints，退出
5. 主容器继续启动 Hermes Gateway
```

**修改文件：**
- `kubernetes/sandbox/pool.yaml`: 添加 shared volume + postStart hook
- `scripts/registry-init.py`: 轮询检查标记文件而非等待端口

**pool.yaml 修改：**
```yaml
volumes:
  - name: sandbox-data
    emptyDir: {}
  - name: shared
    emptyDir: {}
initContainers:
  - name: registry-init
    # ... existing env vars ...
    volumeMounts:
      - name: sandbox-data
        mountPath: /opt/data
      - name: shared
        mountPath: /shared
    command: ["python3", "/opt/hermes/scripts/registry-init.py"]
containers:
  - name: sandbox
    # ... existing config ...
    volumeMounts:
      - name: sandbox-data
        mountPath: /opt/data
      - name: shared
        mountPath: /shared
    lifecycle:
      postStart:
        exec:
          command:
            - /bin/sh
            - -c
            - |
              # 等待 Hermes Gateway 就绪（/health 返回 200）
              for i in $(seq 1 30); do
                if curl -sf http://localhost:8642/health > /dev/null 2>&1; then
                  echo "ready" > /shared/registry_done
                  exit 0
                fi
                sleep 2
              done
              # 超时，写入标记让 init container 继续（注册会在超时后进行）
              echo "timeout" > /shared/registry_done
    lifecycle:
      preStop:
        exec:
          command:
            - /bin/sh
            - -c
            - |
              curl -sf -X POST http://localhost:8080/deregister || true
              sleep 2
```

**registry-init.py 修改：**
```python
def wait_for_registration_marker(timeout: int = 120) -> bool:
    """等待主容器 postStart 写入的标记文件"""
    marker_path = "/shared/registry_done"
    start = time.time()
    while time.time() - start < timeout:
        try:
            with open(marker_path, "r") as f:
                content = f.read().strip()
                if content == "ready":
                    print("[registry-init] Sandbox ready, proceeding with registration")
                    return True
                elif content == "timeout":
                    print("[registry-init] Sandbox startup timeout, proceeding anyway")
                    return True
        except FileNotFoundError:
            pass
        time.sleep(2)
    print(f"[registry-init] Timeout waiting for marker file {marker_path}")
    return False
```

---

### 2.3 PostgreSQL 存储（Critical #3）

**问题：** 使用 emptyDir，Pod 重启数据丢失。

**修复方案：** 默认 emptyDir，文档说明如何启用 PVC。

**修改：** `kubernetes/postgres/statefulset.yaml` 添加清晰的注释，指导如何切换到 PVC。

---

## 3. Important 问题修复

### 3.1 Secret 密码 Placeholder

**修改：** `kubernetes/postgres/secret.yaml`

```yaml
stringData:
  username: hermes
  password: CHANGE_ME # Run: openssl rand -base64 24 | tr -d '\n'
```

部署前必须替换。

---

### 3.2 TTL Manager 架构调整

**问题：** 每个沙箱有独立 SQLite，TTL manager 无法查询。

**修复方案：** TTL manager 不依赖沙箱内数据库，改为通过 Gateway API 或 OpenSandbox 状态判断闲置。

**简化策略：** 每次 Gateway 路由请求时更新 Endpoints 的 `last_seen` annotation。TTL manager 扫描所有 Endpoints，超过 TTL 无更新的直接删除。

**文件修改：**
- `gateway/sandbox_router.py`: 每次路由时 PATCH Endpoints annotation `last_seen=NOW()`
- `scripts/ttl-manager.py`: 改为扫描 Endpoints annotation 判断闲置

**annotation 方案：**
```python
# gateway/sandbox_router.py - 每次路由时更新
def _update_endpoint_timestamp(self, user_id: str, pod_ip: str):
    """更新 Endpoints 的 last_seen timestamp annotation"""
    try:
        body = client.V1Endpoints(
            metadata=client.V1ObjectMeta(
                name=user_id,
                namespace=K8S_NAMESPACE,
                annotations={"last_seen": str(int(time.time()))}
            )
        )
        self.core_v1.patch_endpoints(name=user_id, namespace=K8S_NAMESPACE, body=body)
    except Exception:
        pass  # 静默失败，不阻塞路由

# ttl-manager.py - 扫描闲置
def scan_and_reclaim():
    cutoff = int(time.time()) - (SANDBOX_TTL_MINUTES * 60)
    for ep in endpoints.items:
        last_seen = ep.metadata.annotations.get("last_seen", "0")
        if int(last_seen) < cutoff:
            # 闲置超限，删除
            delete_batchsandbox(user_id)
            deregister_endpoints(user_id)
```

---

### 3.3 幂等性修复

**文件：** `gateway/sandbox_router.py`

```python
def create_sandbox(self, user_id: str) -> bool:
    # ... existing code ...
    try:
        self.sandbox_v1.create_namespaced_custom_object(...)
        return True
    except ApiException as e:
        if e.status == 409:  # Already exists - idempotent, success
            return True
        print(f"[SandboxRouter] Failed to create BatchSandbox: {e}")
        return False
```

---

### 3.4 命名澄清

**文件：** `gateway/sandbox_router.py`

```python
def is_pool_full(self) -> bool:
    """检查沙箱池是否已满。满返回 True，未满返回 False."""
    # ... existing implementation ...
```

---

### 3.5 单元测试（按需）

为以下文件补充单元测试：
- `scripts/registry-init.py`
- `scripts/registry-agent.py`
- `scripts/ttl-manager.py`

---

## 4. 文件变更汇总

| 文件 | 操作 | 说明 |
|------|------|------|
| `gateway/sandbox_router.py` | 修改 | label selector 查 pod IP；PATCH last_seen annotation；处理 409；重命名 |
| `kubernetes/sandbox/pool.yaml` | 修改 | 添加 shared volume；postStart hook |
| `scripts/registry-init.py` | 修改 | 轮询标记文件而非端口 |
| `kubernetes/postgres/secret.yaml` | 修改 | 密码改 placeholder |
| `kubernetes/postgres/statefulset.yaml` | 修改 | 完善注释 |
| `scripts/ttl-manager.py` | 修改 | 基于 annotation 判断闲置 |
| `tests/test_registry_init.py` | 新增 | registry-init 单元测试 |
| `tests/test_registry_agent.py` | 新增 | registry-agent 单元测试 |
| `tests/test_ttl_manager.py` | 新增 | ttl-manager 单元测试 |

---

## 5. 自审检查

- [ ] Endpoints 命名一致：Gateway 用 label selector，registry-init 注册用 user_id 作为 Endpoints 名
- [ ] Init container 不再等待端口，改为等待标记文件
- [ ] PostgreSQL 配置有明确注释说明如何启用 PVC
- [ ] Secret 无硬编码密码
- [ ] TTL manager 基于 Endpoints annotation 判断闲置
- [ ] BatchSandbox 创建处理 409 Conflict
- [ ] 所有新增代码有单元测试
