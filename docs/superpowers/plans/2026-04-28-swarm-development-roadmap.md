# Hermes Swarm 开发路线图（更新于 2026-04-28）

> **状态**: 进行中
> **基于**: `docs/superpowers/specs/2026-04-25-swarm-collaboration-design.md`

---

## 完成情况总览

| Phase | 内容 | 原计划 | 实际完成 | 状态 |
|-------|------|--------|----------|------|
| Phase 1 | 基础设施 | 4 周 | 2026-04-25 ~ 04-26 | ✅ 已完成 |
| Phase 3a | Crew CRUD + Workflow | Phase 3 内 | 2026-04-27 | ✅ 已完成（提前） |
| Phase 3b | Crew Execution + E2E | Phase 3 内 | 2026-04-28 | ✅ 已完成 |
| — | E2E 测试覆盖 | 持续 | 2026-04-28 | ✅ 已完成 |
| — | K8s 部署持久化 | 持续 | 2026-04-28 | ✅ 已完成 |
| Phase 2 | 任务监控 | Phase 2 | — | 🔲 未开始 |
| Phase 3c | 知识库（集成 Ultron） | Phase 3 | — | 🔲 未开始 |
| Phase 4 | 弹性与优化 | Phase 4 | — | 🔲 未开始 |

---

## ✅ Phase 1: 基础设施（已完成）

**完成日期**: 2026-04-25 ~ 04-26
**提交范围**: `232b5dbf..e82c1a92`

### 交付物
- [x] Redis 单节点部署（AOF + PVC）+ K8s manifests
- [x] Agent Registry + 心跳机制
- [x] 消息传输层（Streams + Pub/Sub 双层）
- [x] Exactly-Once 语义（五层防御）
- [x] 连接管理 + 熔断器 + 优雅降级
- [x] Admin Panel Swarm 概览页 + Redis 健康卡片
- [x] SSE 实时事件推送 + 一次性 Token 认证
- [x] 后端单元测试（10 个测试文件）
- [x] 前端 E2E 测试（swarm.spec.ts 3 个基础用例）

### 关键文件
- `hermes_agent/swarm/` — 运行时核心（13 个模块）
- `admin/backend/swarm_routes.py` — REST + SSE API
- `admin/backend/swarm_models.py` — Pydantic 模型
- `admin/frontend/src/pages/swarm/SwarmOverviewPage.tsx`
- `admin/frontend/src/stores/swarmRegistry.ts` / `swarmEvents.ts`
- `admin/frontend/src/lib/swarm-sse.ts`
- `kubernetes/swarm/` — Redis K8s manifests

---

## ✅ Phase 3a: Crew CRUD + Workflow（已完成，提前交付）

**完成日期**: 2026-04-27
**提交范围**: `9f802b29..5649f4ba`
**备注**: 原 Phase 3 的 Crew 管理提前实现

### 交付物
- [x] Crew CRUD API（POST/GET/PUT/DELETE）
- [x] CrewStore（Redis 持久化）
- [x] WorkflowEngine（sequential/parallel/DAG 执行）
- [x] 分布式锁防止并发执行
- [x] 并发限制（Semaphore, max 4）
- [x] Admin Panel Crew 列表页 + 创建/编辑页
- [x] Zustand swarmCrews store
- [x] DAG 循环依赖检测（前端 + 后端）
- [x] i18n 中英文（~30 个 crew 相关 key）
- [x] 安全审计修复（lock safety, SSTI, thread race）

### 关键文件
- `admin/swarm/crew_store.py` — Redis-backed CRUD
- `admin/backend/swarm_routes.py` — Crew + Execution endpoints
- `admin/backend/swarm_models.py` — DAG 验证
- `admin/frontend/src/pages/swarm/CrewListPage.tsx`
- `admin/frontend/src/pages/swarm/CrewEditPage.tsx`
- `admin/frontend/src/stores/swarmCrews.ts`

---

## ✅ Phase 3b: Crew Execution + E2E 覆盖（已完成）

**完成日期**: 2026-04-28

### 交付物
- [x] Crew 执行 API（POST /crews/{id}/execute + 轮询）
- [x] 执行状态 UI（pending → running → completed/failed）
- [x] 409 Conflict（并发执行保护）+ 429 Rate Limit 处理
- [x] 占位页面（Tasks "Coming Soon" + Knowledge "Coming Soon"）
- [x] 品牌名更新支持

### E2E 测试覆盖（34 个用例，全部通过）

| 测试文件 | 用例数 | 覆盖内容 |
|----------|--------|----------|
| swarm.spec.ts | 10 | Agent 卡片、状态、stats、Redis 健康、吞吐指标、空状态、load bar |
| crew.spec.ts | 13 | CRUD 全流程、表单验证、DAG 依赖、循环检测、workflow 切换 |
| crew-execution.spec.ts | 6 | 执行启动、状态轮询、失败处理、409/429 错误 |
| swarm-guard.spec.ts | 6 | 禁用重定向、故障重定向、启用访问、侧边栏导航 |

### 全项目 E2E 统计
- 9 个测试文件，69 个用例
- 覆盖: Login, Dashboard, Agent Detail, Create Agent, Settings, Swarm, Crew, Crew Execution, SwarmGuard

---

## ✅ K8s 部署持久化（已于 2026-04-28 完成）

| 项目 | 状态 | YAML 文件 |
|------|------|-----------|
| `hermes-ingress` | ✅ | `kubernetes/admin/ingress.yaml` |
| `hermes-webui-ingress` | ✅ | `kubernetes/webui/ingress.yaml` |
| `hermes-webui` Service | ✅ | `kubernetes/webui/service.yaml` (NodePort:8080→48080) |
| `kubernetes/admin/` | ✅ | `deployment.yaml` + `service.yaml` + `ingress.yaml` |
| `hermes-gateway-1` Service | ✅ | `kubernetes/gateway/service.yaml` |
| WebUI PVC | 🔲 | 无持久化存储，重启丢数据 |
| Agent 删除同步 Ingress | 🔲 | 删除 agent 不清理 Ingress 路径 |

---

## 🔲 Phase 2: 任务监控（未开始）

**预估**: 4 周
**前置依赖**: Phase 1 ✅

### 计划交付物
- [ ] 任务提交 API（POST /swarm/tasks）
- [ ] 任务状态查询（GET /swarm/tasks/{id}）
- [ ] 任务追踪链（GET /swarm/tasks/{id}/trace）
- [ ] Sync/Async 桥接（三线程架构）
- [ ] 跨 Agent 工具调用
- [ ] 停滞消息扫描器
- [ ] Admin Panel 任务监控页（`/swarm/tasks`）
- [ ] 任务详情页（`/swarm/tasks/:id`）— 追踪泳道时间线
- [ ] SSE 实时任务更新
- [ ] E2E 测试覆盖

### 关键文件（计划）
- `admin/frontend/src/pages/swarm/TaskMonitorPage.tsx`
- `admin/frontend/src/pages/swarm/TaskDetailPage.tsx`

---

## 🔲 Phase 3c: 知识库（集成 Ultron，未开始）

**预估**: 2 周（大幅缩短，直接集成 Ultron SDK）
**前置依赖**: Phase 1 ✅
**参考**: `docs/ultron-research.md`、[Ultron GitHub](https://github.com/modelscope/ultron)

### 策略变更说明

~~原计划从零构建知识库（Redis → Qdrant 向量库）~~。经研究 Ultron 后决定**直接集成 Ultron SDK**，而非重新实现。Ultron 提供：

- **Memory Hub**: 分层存储（HOT/WARM/COLD）+ 语义搜索 + PII 脱敏 + 时间衰减
- **Skill Hub**: 经验蒸馏为可复用技能 + 82K+ ModelScope 技能市场
- **Harness Hub**: Agent 蓝图发布与共享
- **存储**: SQLite（零运维），无需额外向量数据库
- **Embedding**: DashScope `text-embedding-v4` 或本地 `sentence-transformers`

### Ultron 集成方式

```python
from ultron import Ultron, UltronConfig

# 最小配置 — 复用 Hermes 的 LLM endpoint
config = UltronConfig(
    embedding_backend="dashscope",
    llm_base_url="http://hermes-gateway:8642/v1",
    llm_model="qwen-plus"
)
ultron = Ultron(config=config)
```

安装: `pip install git+https://github.com/modelscope/ultron.git`

### 交付物

- [ ] Ultron SDK 集成（依赖安装 + 配置初始化）
- [ ] Admin 后端 Ultron 代理 API（转发 Memory/Skill/Harness 请求）
- [ ] Agent Loop 集成钩子（context compression → 写入 Memory Hub）
- [ ] Agent 启动钩子（新会话 → 检索相关记忆注入 system prompt）
- [ ] Admin Panel 知识库页面（`/swarm/knowledge`，替代 ComingSoon）
  - 记忆列表（按层级/权重排序）
  - 语义搜索
  - 技能库浏览
- [ ] E2E 测试覆盖

### 关键文件（计划）
- `admin/backend/ultron_routes.py` — Ultron 代理 API
- `admin/backend/ultron_config.py` — Ultron 配置管理
- `admin/frontend/src/pages/swarm/KnowledgeBasePage.tsx`
- `admin/frontend/src/stores/swarmKnowledge.ts`

### 与 Hermes 现有系统的对接

| Ultron API | Hermes 对接点 |
|------------|-------------|
| `upload_memory()` | Agent Loop context compression 完成后调用 |
| `search_memories()` | 新会话启动时，语义检索注入 system prompt |
| `search_skills()` | 工具注册时，搜索相关技能 |
| `upload_skills()` | 经验蒸馏后的技能发布 |
| `harness_sync_up()` | Admin Panel 创建/更新 agent 时同步蓝图 |

---

## 🔲 Phase 4: 弹性与优化（未开始）

**预估**: 2 周
**前置依赖**: Phase 2 + Phase 3c

### 计划交付物
- [ ] Redis Sentinel 高可用
- [ ] KEDA 自适应扩缩容
- [ ] 负载感知动态路由
- [ ] Redis 监控告警
- [ ] 性能基准测试 + 优化

---

## 关键风险

| 风险 | 影响 | 缓解 |
|------|------|------|
| Redis 单点故障 | 消息丢失 | AOF + PVC 已部署；Phase 4 迁移 Sentinel |
| Agent 删除不同步 Ingress | 孤立路由 | 需在 admin backend delete 逻辑中修复 |
| WebUI 无 PVC | 重启丢数据 | 需添加持久化存储 |
| Playwright 版本兼容性 | CI 不稳定 | 当前固定 1.59.1，运行正常 |
| Ultron SDK 稳定性 | 依赖风险 | 可 fork 锁定版本；API 简单，必要时自行实现 |

---

## 下一步建议

1. **P1 — WebUI PVC**: 添加持久化存储
2. **Phase 3c — Ultron 集成**: 安装 Ultron SDK，搭建 admin 代理 API，替换 ComingSoon 页面
3. **Phase 2 — 任务监控**: 任务追踪页面开发
