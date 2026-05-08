# Admin 独立发现 Agent Skills（不修改上游 Gateway）

## Context

当前 skills 上报依赖 `gateway/skills_reporter.py`（本地添加的代码，非官方功能），gateway 主动 POST 到 admin。这导致与上游 Hermes 代码耦合，升级时需处理冲突。改为 **admin 面板自主扫描 agent pod 上的 skills 目录**，通过已有的 K8s exec 能力读取 SKILL.md 文件，解析后存入数据库。前端无需任何改动。

## 现有基础设施

- `k8s_client.py` 的 `list_dir()` 和 `read_file_from_pod()` 已支持 `/opt/data/` 路径前缀
- `_stream_api` 独立实例已解决 WebSocket 竞态问题
- `agent_skills` DB 表、`SkillReportItem` 模型、`GET /agents/{id}/skills` 端点已就绪
- 前端 `SkillList` 组件已消费 `SkillEntry[]` 渲染

## 修改文件

### 1. 新增：`admin/backend/skill_scanner.py`

Skills 扫描模块，核心逻辑：

```python
SKILL_PATHS = ["/opt/data/skills"]

async def scan_skills(k8s: K8sClient, pod_name: str) -> list[SkillReportItem]:
    """扫描 pod 上所有 SKILL.md，返回技能列表。"""
    skills = []
    for root in SKILL_PATHS:
        try:
            entries = await k8s.list_dir(pod_name, root)
        except Exception:
            continue  # 目录不存在则跳过
        for entry in entries:
            if entry["type"] != "dir":
                continue
            skill_dir = f"{root}/{entry['name']}"
            try:
                raw, _ = await k8s.read_file_from_pod(pod_name, f"{skill_dir}/SKILL.md")
            except Exception:
                continue
            item = _parse_skill_md(raw.decode("utf-8"), entry["name"], skill_dir)
            if item:
                skills.append(item)
    return skills

def _parse_skill_md(content: str, fallback_name: str, skill_dir: str) -> SkillReportItem | None:
    """解析 SKILL.md YAML frontmatter。"""
    # 提取 --- 之间的 YAML
    # 解析 name, description, version, metadata.hermes.tags
    # 计算 content_hash (SHA-256[:32])
    # 返回 SkillReportItem
```

### 2. 修改：`admin/backend/main.py`

**替换 `GET /agents/{agent_id}/skills` 的实现**（当前从 DB 读，改为从 pod 扫描 + 缓存到 DB）：

```
GET /agents/{agent_id}/skills
```

逻辑：
1. 查找 agent 的 running pod
2. 调用 `scan_skills(k8s, pod_name)` 扫描
3. 用扫描结果 **full-replace** `agent_skills` 表（复用现有的 upsert 逻辑）
4. 更新 `agent_metadata.skills` 聚合 tags
5. 返回 `list[SkillReportItem]`

如果 pod 不在运行，回退到从 `agent_skills` 表返回上次缓存的结果。

**删除 `POST /internal/agents/{number}/skills/report` 端点**（不再需要 gateway 推送）。

### 3. 清理：`admin/backend/templates.py`

移除 `render_deployment` 中的这两个环境变量（gateway 不再需要）：
```python
{"name": "ADMIN_INTERNAL_TOKEN", "value": "hermes-internal"},
{"name": "SKILL_REPORT_ADMIN_URL", "value": f"http://hermes-admin.{namespace}.svc.cluster.local:48082"},
```

### 4. 清理：`admin/backend/db_models.py`

可删除 `ReportIdRecord`（`skill_report_ids` 表）—— 幂等性检查不再需要。或者保留不管，不影响功能。

## 不需要修改的文件

- **前端**：`SkillList` 组件、`admin-api.ts` 的 `getAgentSkills()`、`AgentDetailPage.tsx` 全部不变
- **上游 gateway**：完全不动
- **DB schema**：`agent_skills` 表结构不变

## 验证

1. 启动 admin → 打开 agent 详情页 → Skills 区域显示已安装的技能列表
2. Agent 未运行时 → 显示上次缓存的结果（或空列表 + 提示）
3. 确认 `gateway/skills_reporter.py` 不再被调用（可删除或保留不启用）
4. 确认 deployment 模板不再注入 `ADMIN_INTERNAL_TOKEN` 和 `SKILL_REPORT_ADMIN_URL`
