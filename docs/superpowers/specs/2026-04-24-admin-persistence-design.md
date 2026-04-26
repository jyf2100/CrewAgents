# Admin Panel 数据持久化设计

## 背景

Admin 面板有两类配置在 Pod 重启后丢失：
1. **模板文件**：用户通过设置页面编辑后写入 `/app/templates/`（容器内），无 volume 挂载，重启回退到镜像默认值
2. **默认资源限制**：纯内存 Python 对象，重启回退到 Pydantic 硬编码默认值

已有的持久化模式：`/data/hermes/_admin/` 目录，admin_key 已在此存储。

## 设计方案

### 持久化目录结构

```
/data/hermes/_admin/
├── admin_key                          # 已有
├── default_resources.json             # 新增：默认资源限制
└── templates/                         # 新增：自定义模板覆盖
    ├── deployment.yaml
    ├── .env.template
    ├── config.yaml.template
    └── SOUL.md.template
```

### 1. 模板持久化

**策略**：双层读取 — 优先读取 `_admin/templates/`，不存在则 fallback 到 `/app/templates/`（镜像默认）

**templates.py 变更**：

- `__init__` 新增 `persist_dir` 参数，路径为 `{data_root}/_admin/templates`
- `_read_template()` 改为先检查 `persist_dir`，有则读取；否则读取 `templates_dir`（镜像默认）
- `_write_template()` 写入 `persist_dir`（不影响镜像文件）
- 删除时只删 `persist_dir` 中的文件（回退到默认）

```python
def _read_template(self, name: str) -> str:
    # 优先读取持久化版本
    persisted = os.path.join(self.persist_dir, name)
    if os.path.isfile(persisted):
        with open(persisted) as f:
            return f.read()
    # fallback 到镜像默认
    default = os.path.join(self.templates_dir, name)
    if os.path.isfile(default):
        with open(default) as f:
            return f.read()
    return ""

def _write_template(self, name: str, content: str) -> None:
    os.makedirs(self.persist_dir, exist_ok=True)
    path = os.path.join(self.persist_dir, name)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(content)
    os.replace(tmp, path)
```

**main.py 变更**：
- 传入 `data_root` 给 `TemplateGenerator`

```python
tpl = TemplateGenerator(data_root=HERMES_DATA_ROOT)
```

### 2. 默认资源限制持久化

**策略**：JSON 文件，启动时加载，修改时写入

**文件格式** (`default_resources.json`):
```json
{
  "cpu_request": "500m",
  "cpu_limit": "2000m",
  "memory_request": "1Gi",
  "memory_limit": "2Gi"
}
```

**agent_manager.py 变更**：

- `__init__` 中调用 `_load_default_resources()` 从文件加载
- `set_default_resource_limits()` 写入文件

```python
def _default_resources_path(self) -> str:
    admin_dir = os.path.join(self.config_mgr.data_root, "_admin")
    return os.path.join(admin_dir, "default_resources.json")

def _load_default_resources(self) -> DefaultResourceLimits:
    path = self._default_resources_path()
    if os.path.isfile(path):
        try:
            with open(path) as f:
                data = json.load(f)
            return DefaultResourceLimits(**data)
        except Exception:
            pass
    return DefaultResourceLimits()

def set_default_resource_limits(self, limits: DefaultResourceLimits) -> None:
    self._default_resources = limits
    admin_dir = os.path.join(self.config_mgr.data_root, "_admin")
    os.makedirs(admin_dir, exist_ok=True)
    path = self._default_resources_path()
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(limits.model_dump(), f, indent=2)
    os.replace(tmp, path)
```

### 涉及文件

| 文件 | 变更 |
|------|------|
| `templates.py` | 新增 `persist_dir`，双层读取，写入持久化目录 |
| `agent_manager.py` | 资源限制加载/保存到 JSON 文件 |
| `main.py` | 传入 `data_root` 给 `TemplateGenerator` |

### 不涉及

- 前端无变更
- API 接口无变更
- K8s 部署无变更

### 优势

- 复用现有 `/data/hermes/_admin/` 目录模式
- 原子写入（`os.replace`），避免部分写入
- 向后兼容：无持久化文件时自动使用默认值
- 不影响 Docker 镜像中的原始模板
