# Domain + Skills 分层标签体系设计

> 日期：2026-05-06
> 状态：讨论确认中
> 替代：现有 role (generalist/coder/analyst) + 手动 tags 系统

## 1. 背景与问题

### 现状
- `role` 字段：3 个固定枚举（generalist/coder/analyst），纯展示，不参与路由
- `tags` 字段：管理员手动输入 21 个平铺 toggle，承担所有路由语义
- Selector 路由：只看 tags Jaccard 相似度，role 完全忽略

### 问题
1. role 是摆设字段，和 tags 功能重叠
2. 3 个枚举覆盖不了实际场景（数据分析师、运维、客服等）
3. tags 平铺结构没有层次，用户不知道该填什么
4. Skills 不是标签而是有实质内容的 SKILL.md 文件，应自动提取而非手写

## 2. 设计决策

| 决策项 | 选择 | 理由 |
|--------|------|------|
| 分层结构 | Domain + Skills 两层 | 足够表达，不引入三层复杂度 |
| Agent-Domain 关系 | 单 Domain + 多 Skills | 一个 agent 主攻一个方向 |
| Skills 来源 | Agent 启动时自动上报 | 从已安装 SKILL.md 提取，不手动维护 |
| 路由粒度 | Tags 级别（从 SKILL.md 提取） | 更灵活，不需要任务提交者知道 skill 名称 |
| role 迁移 | 三阶段渐进迁移 | 阶段A:双读兼容 → 阶段B:数据迁移 → 阶段C:清理删除 |
| Domain 扩展 | 枚举 + 可扩展 | 初始 5 个，后续可加 |
| 保留 generalist | 是 | 作为万能 fallback agent |

## 3. 数据模型

### AgentMetadata 表变更

```python
DOMAINS = ["generalist", "code", "data", "ops", "creative"]

class AgentMetadata(Base):
    __tablename__ = "agent_metadata"

    agent_number = Column(Integer, primary_key=True)
    display_name = Column(String(100), default="")

    # --- 新字段 ---
    domain = Column(
        String(20),
        default="generalist",
        server_default="generalist",
        nullable=False,
    )
    skills = Column(
        JSONB,
        default=list,
        server_default="[]",
        nullable=False,
    )  # 从 AgentSkill 表聚合的路由用 tags: ["qa", "testing", ...]
    # GIN 索引用于 required_tags 子集查询
    __table_args__ = (
        Index("ix_agent_metadata_tags", "tags", postgresql_using="gin"),
        Index("ix_agent_metadata_skills", "skills", postgresql_using="gin"),
    )

    # --- 保留 ---
    tags = Column(
        JSONB,
        default=list,
        server_default="[]",
        nullable=False,
    )  # 自由标签，用于搜索/显示。过渡期内仍参与路由

    # --- 过渡期保留，阶段 C 删除 ---
    role = Column(String(50), default="generalist", server_default="generalist", nullable=False)

    description = Column(Text, default="")
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
```

> **设计说明**：删除了 `installed_skills` JSONB 列。Skill 详情通过 `AgentSkill` 表查询，`skills` JSONB 列作为路由反规范化缓存（从 AgentSkill 聚合写入），避免每次路由都 JOIN 查询。

### 数据迁移（三阶段渐进）

```sql
-- ========== 阶段 A：兼容部署（新增列，不删旧列）==========
-- 所有新字段有 server_default，无需立即迁移数据
-- 后端代码同时读 role 和 domain（domain 优先）

ALTER TABLE agent_metadata ADD COLUMN domain VARCHAR(20)
  NOT NULL DEFAULT 'generalist';
ALTER TABLE agent_metadata ADD COLUMN skills JSONB
  NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE agent_metadata ADD COLUMN IF NOT EXISTS description TEXT DEFAULT '';

-- 新建 AgentSkill 表（独立于 agent_metadata，用于存储 skill 详情）
CREATE TABLE IF NOT EXISTS agent_skills (
    id SERIAL PRIMARY KEY,
    agent_number INTEGER NOT NULL,
    skill_name VARCHAR(64) NOT NULL,
    description VARCHAR(1024) DEFAULT '',
    version VARCHAR(32) DEFAULT '',
    tags JSONB DEFAULT '[]'::jsonb NOT NULL,
    skill_dir VARCHAR(512) DEFAULT '',
    reported_at TIMESTAMPTZ DEFAULT NOW(),
    content_hash VARCHAR(64) DEFAULT '',
    CONSTRAINT ix_agent_skills_agent_skill UNIQUE (agent_number, skill_name)
);
CREATE INDEX IF NOT EXISTS ix_agent_skills_tags ON agent_skills USING gin (tags);

-- 新建幂等去重表
CREATE TABLE IF NOT EXISTS skill_report_ids (
    report_id VARCHAR(128) PRIMARY KEY,
    agent_number INTEGER NOT NULL,
    skills_count INTEGER DEFAULT 0,
    tags_aggregated JSONB DEFAULT '[]'::jsonb,
    processed_at TIMESTAMPTZ DEFAULT NOW()
);

-- ========== 阶段 B：数据迁移（确认新代码已部署后执行）==========

UPDATE agent_metadata SET domain = 'generalist' WHERE role = 'generalist';
UPDATE agent_metadata SET domain = 'code' WHERE role = 'coder';
UPDATE agent_metadata SET domain = 'data' WHERE role = 'analyst';

-- 等待 Agent 启动上报 skills 填充 skills 列（自动，无需手动）
-- 等待至少一个完整 discovery 周期（30s）

-- ========== 阶段 C：清理（确认所有 agent 已上报 skills）==========

-- 删除 7 天前的 report_id 记录
DELETE FROM skill_report_ids WHERE processed_at < NOW() - INTERVAL '7 days';

-- 删除 role 列（确认前端已移除 role fallback 代码后执行）
ALTER TABLE agent_metadata DROP COLUMN role;
```

> **迁移执行方式**：使用 `init_db()` 中的 `_run_migrations()` 函数在启动时执行，版本化跟踪。不引入 Alembic 以保持简单——每次迁移是一组幂等 SQL（`IF NOT EXISTS` / `ADD COLUMN IF NOT EXISTS`）。

## 4. Agent 上报 Skills 流程

```
Agent Gateway 启动
  → 扫描 ~/.hermes/skills/ 下的所有 SKILL.md
  → 提取每个 skill 的:
     - name: "dogfood"
     - description: "Systematic exploratory QA testing..."
     - tags: ["qa", "testing", "browser", "web"]  # metadata.hermes.tags
  → POST /internal/agents/{agent_number}/skills/report
     Header: X-Internal-Token: <token>
     Body: {
       "skills": [
         {"name": "dogfood", "description": "...", "tags": ["qa","testing"], ...},
         {"name": "code-review", "description": "...", "tags": ["code-review"], ...}
       ],
       "report_id": "3-1746493200-a1b2c3d4"
     }
  → Admin:
     1. 写入 AgentSkill 表（每个 skill 一行）
     2. 聚合 tags → 更新 AgentMetadata.skills JSONB
     3. 更新 AgentMetadata.domain（从部署 annotations）
  → Orchestrator discovery 下次轮询时获取新数据
```

### SKILL.md 示例

```yaml
---
name: dogfood
description: Systematic exploratory QA testing of web applications
version: 1.0.0
metadata:
  hermes:
    tags: [qa, testing, browser, web, dogfood]
---
```

## 5. 路由逻辑

### AgentProfile 新增字段

```python
# hermes_orchestrator/models/agent.py
@dataclass
class AgentProfile:
    agent_id: str
    role: str = "generalist"       # 过渡期保留，映射为 domain
    domain: str = "generalist"     # 新增：从 Admin API domain 字段读取
    tags: list[str] = field(default_factory=list)    # 旧路由字段，过渡期保留
    skills: list[str] = field(default_factory=list)  # 新增：路由用，从 AgentSkill 聚合
    # ... 保留现有字段
```

### 路由算法（修订版）

```
def select(task, candidates):
    # 预过滤: 排除不可用 agent
    eligible = [a for a in candidates
                if a.status in ("online", "degraded")
                and a.circuit_state != "open"
                and a.current_load < a.max_concurrent]

    # Level 0: domain 硬约束（读 a.domain，过渡期 fallback a.role）
    task_domain = task.domain or "generalist"
    domain_agents = [a for a in eligible if a.domain == task_domain]
    if not domain_agents:
        domain_agents = [a for a in eligible if a.domain == "generalist"]
    if not domain_agents:
        domain_agents = eligible

    # Level 1: required_tags 硬约束（过渡期同时检查 tags 和 skills）
    if task.required_tags:
        required_set = {t.lower() for t in task.required_tags}
        filtered = [a for a in domain_agents
                    if required_set <= {t.lower() for t in (a.skills + a.tags)}]
        if filtered:
            domain_agents = filtered
        else:
            # 放宽 domain 约束重试一次
            wider = [a for a in eligible
                     if required_set <= {t.lower() for t in (a.skills + a.tags)}]
            if wider:
                domain_agents = wider
            else:
                # required_tags 无法满足 → 重入队列而非标记失败
                return None, RoutingInfo(strategy="required_tags_unsatisfied", requeue=True)

    # Level 2: 加权评分
    # composite = 0.50 * jaccard + 0.35 * load_score + 0.15 * health
    task_keywords = extract_keywords(task.prompt + " " + task.instructions)
    soft_tags = set(task_keywords) | {t.lower() for t in task.required_tags} | {t.lower() for t in task.preferred_tags}

    for agent in domain_agents:
        jaccard_score, matched = compute_tag_score(soft_tags, agent.skills + agent.tags)
        load_pct = agent.current_load / agent.max_concurrent
        load_score = exp(-2.0 * load_pct)
        health_score = 1.0 if agent.status == "online" else 0.5
        if agent.circuit_state == "half_open":
            health_score *= 0.7
        composite = 0.50 * jaccard_score + 0.35 * load_score + 0.15 * health_score
        agent._route_score = composite

    # 排序: 评分降序 → 负载升序 → 注册时间升序
    domain_agents.sort(key=lambda a: (-a._route_score, a.current_load/a.max_concurrent))

    # Level 3: 原子负载预留（防止并发竞态）
    chosen = domain_agents[0]
    reserved = redis.hincrbyfloat(
        f"agent:{chosen.agent_id}:load", "current", 1
    )  # Lua 脚本: 原子检查+递增，超载则回滚
    if reserved > chosen.max_concurrent:
        redis.hincrbyfloat(f"agent:{chosen.agent_id}:load", "current", -1)
        # 递归尝试下一个 agent
        return select(task, domain_agents[1:])

    return chosen
```

## 6. 前端交互

### Agent 详情页 — MetadataCard

```
┌─ Agent Profile ──────────────────────────────────┐
│ Domain:  [generalist] [code] [data] [ops] [creative] │
│          ↑ 管理员单选卡片                           │
│                                                    │
│ Installed Skills（自动）                            │
│   ┌──────────┐ ┌───────────┐ ┌──────────┐         │
│   │ dogfood  │ │code-review│ │deployment│         │
│   │ QA测试    │ │ 代码审查   │ │ 部署运维  │         │
│   └──────────┘ └───────────┘ └──────────┘         │
│   ↑ 从 SKILL.md 自动提取，只读                      │
│                                                    │
│ Skill Tags（自动，用于路由）                         │
│   [qa] [testing] [browser] [code-review]            │
│   [deployment] [python] [api]                       │
│   ↑ 从 SKILL.md tags 聚合，只读                      │
│                                                    │
│ Free Tags（手动，用于搜索）                          │
│   [production] [team-alpha]                         │
│   [输入框 + 添加按钮]                                │
│                                                    │
│              [Save]                                 │
└────────────────────────────────────────────────────┘
```

### 任务提交页

```
Domain（必选）:
  [generalist] [code] [data] [ops] [creative]

Skill Tags（可选，用于精确路由）:
  [输入框 — 输入后自动匹配已有 skill tags]
  已选: [qa] [testing] [x]

（保留快速建议 toggle）
```

### Orchestrator Overview — Agent Fleet 表

| 列 | 内容 |
|----|------|
| Agent | hermes-gateway-1 |
| Domain | code |
| Skills | dogfood, code-review |
| Tags | qa, testing, python |
| Load | 30% ██████░░░░ |
| Status | ● Online |

## 7. 详细技术设计

### 7.1 Skill 上报接口设计

#### Admin 接收端

**端点**: `POST /internal/agents/{agent_number}/skills/report`
**认证**: `X-Internal-Token` header

```python
class SkillReportItem(BaseModel):
    name: str = Field(..., max_length=64)
    description: str = Field("", max_length=1024)
    version: str = Field("", max_length=32)
    tags: list[str] = Field(default_factory=list, max_length=50)  # 限制每个 skill 最多 50 个 tag
    skill_dir: str = Field("", max_length=512, pattern=r"^(?!.*\.\.)[^/].*$")  # 相对路径，禁止 ../ 和绝对路径
    content_hash: str = Field("", max_length=64)

class SkillReportRequest(BaseModel):
    skills: list[SkillReportItem] = Field(default_factory=list, max_length=200)
    report_id: str = Field("", max_length=64)  # 幂等 key

class SkillReportResponse(BaseModel):
    status: str          # "accepted" | "unchanged"
    skills_count: int
    tags_aggregated: list[str]
```

处理逻辑：全量替换语义（DELETE 旧 + INSERT 新），单事务内完成。聚合 tags 后同步更新 agent_metadata.skills JSONB。

#### AgentSkill 表 + ReportIdRecord 表

```python
class AgentSkill(Base):
    __tablename__ = "agent_skills"
    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_number = Column(Integer, nullable=False, index=True)
    skill_name = Column(String(64), nullable=False)
    description = Column(String(1024), default="")
    version = Column(String(32), default="")
    tags = Column(JSONB, default=list, server_default="[]")
    skill_dir = Column(String(512), default="")
    reported_at = Column(DateTime(timezone=True), server_default=func.now())
    content_hash = Column(String(64), default="")
    __table_args__ = (
        Index("ix_agent_skills_agent_skill", "agent_number", "skill_name", unique=True),
        Index("ix_agent_skills_tags", "tags", postgresql_using="gin"),
    )

class ReportIdRecord(Base):
    """幂等去重表。启动时清理 7 天前记录。"""
    __tablename__ = "skill_report_ids"
    report_id = Column(String(128), primary_key=True)
    agent_number = Column(Integer, nullable=False)
    skills_count = Column(Integer, default=0)
    tags_aggregated = Column(JSONB, default=list)
    processed_at = Column(DateTime(timezone=True), server_default=func.now())
```

#### 补充端点

**查询 Agent Skills（前端展示用）**: `GET /agents/{agent_id}/skills`
- 返回 `list[SkillReportItem]`，包含描述信息供 MetadataCard 展示

**轻量 Skill Tags 补全端点**: `GET /orchestrator/skill-tags`
- 返回 `{tags: list[str], domain_distribution: dict[str, int]}`
- 从所有 AgentSkill 聚合去重，前端 TaskSubmitPage 专用
- 不暴露 agent 级别数据，安全且轻量

**Agent 删除时级联清理**: 在 `agent_manager.py` 的 delete_agent 中添加：
```python
await session.execute(delete(AgentSkill).where(AgentSkill.agent_number == agent_number))
await session.execute(delete(ReportIdRecord).where(ReportIdRecord.agent_number == agent_number))
```

#### 内部 API 响应模型更新

```python
class AgentMetadataInternalResponse(BaseModel):
    agent_number: int
    tags: list[str]          # 保留，过渡期仍使用
    skills: list[str]        # 新增：路由用
    domain: str              # 新增：替代 role
    role: str | None = None  # 过渡期保留，阶段 C 删除
```

#### Agent 端扫描逻辑

新建 `gateway/skills_reporter.py`：

```
scan_skills_metadata()
  → 扫描 get_skills_dir() + get_external_skills_dirs()
  → 解析每个 SKILL.md 的 YAML frontmatter
  → 提取: name, description, version, metadata.hermes.tags
  → 计算 content_hash（frontmatter SHA256）
  → 返回 list[dict]

report_skills_sync(skills)
  → POST /internal/agents/{N}/skills/report
  → fire-and-forget，不阻塞 gateway 启动
```

#### 启动注入 + 定时刷新

```
start_gateway()
  → sync_skills()  # 现有：从 bundled 同步文件
  → report_skills_sync()  # 新增：启动时上报一次
  → runner.start()

GatewayRunner._skill_refresh_loop()
  → 每 6h（SKILL_REPORT_INTERVAL）重新扫描+上报
```

#### 幂等性保障

1. **report_id 去重**: 相同 report_id 直接返回 "unchanged"
2. **content_hash 比对**: frontmatter 未变则跳过写入
3. **全量替换**: 单事务 DELETE + INSERT，无中间状态

#### 数据库新增表

```python
class AgentSkill(Base):
    __tablename__ = "agent_skills"
    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_number = Column(Integer, nullable=False, index=True)
    skill_name = Column(String(64), nullable=False)
    description = Column(String(1024), default="")
    version = Column(String(32), default="")
    tags = Column(JSONB, default=list, server_default="[]")
    skill_dir = Column(String(512), default="")
    reported_at = Column(DateTime(timezone=True), server_default=func.now())
    content_hash = Column(String(64), default="")
    __table_args__ = (
        Index("ix_agent_skills_agent_skill", "agent_number", "skill_name", unique=True),
        Index("ix_agent_skills_tags", "tags", postgresql_using="gin"),
    )
```

### 7.2 三阶段路由算法

#### 完整流程

```
请求到达
  │
  ▼
[预过滤] 排除 offline / circuit_open / 超载 agent
  │ 无可用 → 尝试 half_open agents → 仍无 → 返回 None
  ▼
[阶段 1: Domain 硬约束]
  │ 匹配 task.domain → domain_matched
  │ 无匹配 → Fallback L1: generalist agents
  │ 仍无 → Fallback L2: 全量 eligible
  ▼
[阶段 2: required_tags 硬约束]
  │ required_tags ⊆ agent.skills → tag_filtered
  │ 不满足 → 放宽 domain 重试 → 仍不满足 → 返回 None
  ▼
[阶段 3: 加权评分]
  │ composite = 0.50 * jaccard + 0.35 * load_score + 0.15 * health
  │ 排序: 评分降序 → 负载升序 → 注册时间升序
  ▼
选择最优 agent
```

#### 评分权重（修订）

| 维度 | 权重 | 计算 | 范围 | 修订理由 |
|------|------|------|------|----------|
| Skills Jaccard | **0.50** | `len(match) / len(union)` | 0.0 ~ 1.0 | 从 0.65 下调，避免 Jaccard 压倒负载 |
| 负载因子 | **0.35** | `exp(-2.0 * load_pct)` | 0.13 ~ 1.0 | 从 0.25 上调，增强负载区分度 |
| 健康因子 | **0.15** | online=1.0, degraded=0.5, half_open*0.7 | 0.0 ~ 1.0 | 从 0.10 上调，使健康影响更明显 |

#### Task 模型新增字段

```python
# hermes_orchestrator/models/task.py
domain: str = "generalist"
preferred_tags: list[str] = field(default_factory=list)  # 软约束，合并到 Jaccard 输入

# hermes_orchestrator/models/api.py — TaskSubmitRequest 新增
domain: str = "generalist"              # 新增：必选，前端传入
preferred_tags: list[str] = []          # 新增：可选加分项
```

#### RoutingInfo.strategy 枚举（前后端共享）

```python
class RoutingStrategy(str, Enum):
    DOMAIN_TAG_MATCH = "domain_tag_match"
    DOMAIN_FALLBACK_TAG_MATCH = "domain_fallback_tag_match"
    LEAST_LOAD = "least_load"
    REQUIRED_TAGS_UNSATISFIED = "required_tags_unsatisfied"
    NO_AGENT = "no_agent"
```

### 7.3 前端交互设计

#### MetadataCard 改版

组件布局（从上到下）：

1. **Domain 卡片选择器** — `DomainCardSelector`
   - 5 个可视化卡片：Generalist / Code / Data / Ops / Creative
   - 选中态: `border-accent-cyan/50 bg-accent-cyan/5`
   - 使用 `aria-pressed` 无障碍属性
   - 布局: `grid grid-cols-5 gap-3`

2. **Installed Skills 只读列表** — `SkillList`
   - 数据源: `GET /agents/{id}/skills`（返回完整 skill 详情含描述）
   - 每行: `[skill 名称(等宽)] [描述(灰色小字)]`
   - 空状态: "暂无已安装 Skills"
   - 右上角刷新按钮

3. **Skill Tags 只读标签云** — `TagCloud`
   - 数据源: `GET /agents/{id}/metadata` 返回的 `skills` 数组
   - 标题旁标注"（用于智能路由）"
   - 样式: `bg-accent-cyan/10 text-accent-cyan border-accent-cyan/30`

4. **Free Tags 手动输入** — 保留现有功能，改名为 "自定义标签"

#### TaskSubmitPage 改版

1. **Domain 选择器** — `DomainRadioGroup`
   - 5 个 radio button + label，标注必选 `*`
   - 选中 Domain 后，下方 tag 补全源列表自动过滤

2. **Skill Tags 输入** — `TagInput`
   - 数据源: `GET /orchestrator/skill-tags`（轻量专用端点，不暴露 agent 详情）
   - 根据 Domain 过滤补全列表
   - 支持键盘 Enter 确认

3. **保留快速建议 toggle** — 数据源改为动态获取

#### TS 类型更新

```typescript
// admin-api.ts
interface AgentMetadata {
  agent_number: number;
  tags: string[];
  domain?: string;      // 新增，优先使用
  role?: string;        // 过渡期保留 fallback
  skills?: string[];    // 新增：路由用 tags
  display_name?: string;
  description?: string;
  updated_at?: number;
}

interface TaskSubmitRequest {
  prompt: string;
  instructions?: string;
  required_tags?: string[];
  domain?: string;           // 新增
  preferred_tags?: string[]; // 新增
}
```

#### Orchestrator Fleet 表格变更

列顺序: Agent | Status | **Domain/Skills** | Load | Circuit | Tags

- 合并 Domain+Skills 为一列（显示 "code · 3 skills"），避免 8 列溢出
- RoleBadge → DomainBadge（5 色对应 5 个 domain）

#### 新建组件

| 组件 | 路径 | 职责 |
|------|------|------|
| `DomainCardSelector` | `src/components/DomainCardSelector.tsx` | MetadataCard 用的卡片选择器 |
| `DomainRadioGroup` | `src/components/DomainRadioGroup.tsx` | TaskSubmitPage 用的 radio 组 |
| `domain-constants.ts` | `src/components/domain-constants.ts` | 共享 DOMAINS 常量 + i18n key |
| `SkillList` | `src/components/SkillList.tsx` | 只读 Skills 列表（数据来自 /agents/{id}/skills） |
| `TagCloud` | `src/components/TagCloud.tsx` | 只读标签云 |
| `TagInput` | `src/components/TagInput.tsx` | 可交互标签输入（数据来自 /orchestrator/skill-tags） |

#### i18n 新增 Key

```
domainLabel: "领域" / "Domain"
domainCode: "编码" / "Code"
domainCodeDesc: "软件开发、调试、代码审查" / "Software development, debugging, review"
domainData: "数据" / "Data"
domainOps: "运维" / "Ops"
domainCreative: "创意" / "Creative"
installedSkills: "已安装技能" / "Installed Skills"
skillTags: "技能标签" / "Skill Tags"
skillTagsRoutingHint: "用于智能路由" / "Used for intelligent routing"
freeTags: "自定义标签" / "Free Tags"
orchestratorAgentDomain: "领域" / "Domain"
orchestratorSkillCount: "技能数" / "Skills"
```

## 8. 实现范围（修订版：5 阶段渐进部署）

### Phase 0: 迁移基础设施
- `database.py` — 新增 `_run_migrations()` 启动时执行幂等 SQL
- `db_models.py` — 新增 AgentSkill、ReportIdRecord 模型
- `models.py` — 新增 SkillReportItem/Request/Response + AgentMetadataInternalResponse 更新
- SQL: 新增 domain/skills 列（不删 role）、创建 AgentSkill + ReportIdRecord 表

### Phase 1: 兼容部署（双读 role+domain，双读 tags+skills）
- `main.py` — 后端读 domain fallback role；新增 `POST /internal/agents/{id}/skills/report`、`GET /agents/{id}/skills`、`GET /orchestrator/skill-tags` 端点
- `agent_discovery.py` — 读 domain fallback role；读 skills + tags 合并
- `agent_selector.py` — 同时检查 tags 和 skills 做路由；原子负载预留
- `models/agent.py` — AgentProfile 新增 domain + skills 字段
- `models/task.py` — Task 新增 domain + preferred_tags 字段
- `models/api.py` — TaskSubmitRequest 新增 domain + preferred_tags
- `gateway/skills_reporter.py` — 新建：扫描 + 上报逻辑
- `gateway/run.py` — 注入启动上报 + 定时刷新任务
- 前端 TS 类型更新：AgentMetadata 读 domain fallback role

### Phase 2: 数据迁移
- 运行阶段 B SQL：UPDATE domain FROM role 映射
- 等待所有 agent 重启上报 skills（自动填充 skills 列）
- 等待至少一个完整 discovery 周期（30s）
- 验证：所有 AgentProfile.domain 和 AgentProfile.skills 已填充

### Phase 3: 路由切换 + 前端
- `agent_selector.py` — 只读 domain + skills（移除 tags 和 role fallback）
- `agent_discovery.py` — 只读 domain（移除 role fallback）
- 新建 DomainCardSelector、DomainRadioGroup、SkillList、TagCloud、TagInput 组件
- MetadataCard — 替换 role 为 Domain 卡片 + Skills 展示
- TaskSubmitPage — Domain radio + 动态 tag 补全（用 /orchestrator/skill-tags）
- Orchestrator Overview — 合并 Domain+Skills 列
- i18n 翻译（en.ts + zh.ts）

### Phase 4: 清理
- SQL: `ALTER TABLE agent_metadata DROP COLUMN role`
- 后端移除所有 role fallback 代码
- 前端移除 role fallback
- `templates.py` — Deployment 模板添加 HERMES_AGENT_NUMBER
- K8s Secret 添加 ADMIN_INTERNAL_TOKEN
- Prometheus metrics: route_total{strategy}, route_jaccard_score, route_fallback_total
- 路由回归测试场景清单

## 9. 专家审核结论

> 三个独立架构师分别审核了数据模型/API、路由算法、前端交互三个维度。
> 数据架构评审：**不通过** | 路由算法评审：**有条件通过** | 前端交互评审：**有条件通过**

### 9.1 CRITICAL — 必须在实现前修复

| ID | 维度 | 问题 | 影响 |
|----|------|------|------|
| C-D1 | 数据 | `DROP COLUMN role` 破坏性操作 — 5+ 代码位置仍读 role（main.py、models.py、agent_discovery.py），将返回 500 | 需要两阶段部署：先部署双读代码，再跑迁移，最后删列 |
| C-D2 | 数据 | `create_all()` 不会执行 ALTER TABLE — 新列和 AgentSkill 表不会被创建 | 需要集成 Alembic 或启动时 migration runner |
| C-D3 | 数据 | `ReportIdRecord` 表 schema 未定义 — 幂等功能无法实现 | 补充完整表定义 + 清理策略 |
| C-R1 | 路由 | `required_tags` 失败直接返回 None — 任务被标记 failed 不重试，但可能是暂时性状态（agent 离线） | 应重入队列而非标记失败 |
| C-R2 | 路由 | 并发路由竞态条件 — 多任务同时读同一 Redis 快照的 current_load，全部涌向同一 agent | 需要原子负载预留（HINCRBY 或 Lua 脚本） |
| C-R3 | 路由 | Admin DB `domain` 与 Orchestrator `AgentProfile.role` 字段名不匹配 — discovery 读不到 domain | agent_discovery.py 必须同步更新 |
| C-R4 | 路由 | `AgentProfile` 缺少 `skills` 字段 — 路由伪代码引用不存在的数据 | 必须在 AgentProfile 中新增 skills 字段 |
| C-F1 | 前端 | `AgentMetadata` TS 接口与后端不兼容 — 迁移后 role=undefined，页面崩溃 | 需要过渡期：前端读 domain fallback role |
| C-F2 | 前端 | `TaskSubmitRequest` 缺少 `domain` 字段 — domain 路由整个失效 | 必须更新 API 类型 |
| C-F3 | 前端 | `getAllAgentMetadata` 获取全量数据做 tag 补全 — 性能差 + 用户模式下数据泄露 | 需要专用轻量端点 `GET /orchestrator/skill-tags` |
| C-F4 | 前端 | `installed_skills` 数据来源矛盾 — MetadataCard 需要描述但 JSONB 只存名称 | 明确数据源：metadata response 包含描述 |

### 9.2 HIGH — 应该在 Phase 1 中修复

| ID | 维度 | 问题 | 建议 |
|----|------|------|------|
| H-D1 | 数据 | 现有 `tags` 从路由字段变为仅展示字段，路由立刻失效 | 过渡期 selector 同时读 tags 和 skills |
| H-D2 | 数据 | `AgentSkill` 表与 `agent_metadata.installed_skills` JSONB 数据重复 | 删除 installed_skills 列，需要时动态查询 |
| H-D3 | 数据 | `AgentMetadataInternalResponse` 缺少 domain/skills | 更新内部 API 响应模型 |
| H-D4 | 数据 | `skill_dir` 存在路径遍历风险 | 验证路径为相对路径 |
| H-R1 | 路由 | generalist fallback 可能形成热点 | 添加 fallback 频率监控 + 部署模板要求至少 1 个 generalist |
| H-R2 | 路由 | `exp(-2x)` 负载曲线低负载区区分度不足，Jaccard 压倒负载 | 调整权重为 Jaccard 0.50 + load 0.35 + health 0.15 |
| H-R3 | 路由 | Redis 序列化兼容性 — 滚动升级期间 30s 路由降级 | 升级后主动触发全量 discovery |
| H-F1 | 前端 | DomainSelector card/radio 双模式过度抽象 | 拆为 DomainCardSelector + DomainRadioGroup，共享常量 |
| H-F2 | 前端 | Orchestrator Fleet 表格 8 列溢出 | 合并 Domain+Skills 为一列或改用卡片布局 |

### 9.3 修订后的迁移策略

原设计的单步破坏性迁移不可行。改为三阶段渐进迁移：

**阶段 A（兼容部署）**：
- 后端同时读 role 和 domain（domain 优先，fallback role）
- 前端同时读 role 和 domain
- 新增 domain/installed_skills/skills 列（不删 role）
- selector 同时读 tags 和 skills 做路由
- 所有新增字段有 server_default，无需立即迁移数据

**阶段 B（数据迁移）**：
- 运行 SQL 迁移：UPDATE agent_metadata SET domain = role 映射
- Agent 启动后自动上报 skills，填充 skills 列
- 等待至少一个完整 discovery 周期（30s）

**阶段 C（清理）**：
- 确认所有 agent 已上报 skills
- 确认 selector 不再依赖 tags 做路由
- DROP COLUMN role
- 前端移除 role fallback 代码

### 9.4 审核人建议的补充项

- 添加 `preferred_tags` 的明确路由语义（作为 Jaccard 输入与 prompt 关键词合并）
- 为 `AgentProfile` 添加 `skills: list[str]` 字段 + 更新 to_dict/from_dict
- 使用 Alembic 或 app-level migration runner 替代裸 SQL
- 为 `skill_tags` 前端补全创建专用轻量端点
- 定义完整的 strategy 枚举（前后端共享）
- 添加路由回归测试场景清单
- 添加 Prometheus metrics：route_total{strategy}, route_jaccard_score, route_fallback_total
