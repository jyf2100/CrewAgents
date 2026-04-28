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
| — | K8s 部署持久化 | 持续 | 2026-04-28 | ⚠️ 部分完成 |
| Phase 2 | 任务监控 | Phase 2 | — | 🔲 未开始 |
| Phase 3c | 知识库 | Phase 3 | — | 🔲 未开始 |
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

## ⚠️ 待处理：K8s 部署持久化

以下配置只存在于 etcd，未持久化到 YAML 文件：

| 项目 | 问题 | 优先级 |
|------|------|--------|
| `hermes-ingress` | 4 条路径规则无 YAML 文件 | P0 |
| `hermes-webui-ingress` | WebUI 根路径无 YAML 文件 | P0 |
| `hermes-webui` Service | YAML 仍是 ClusterIP:8080，实际为 NodePort:48080 | P0 |
| `kubernetes/admin/` | Admin deployment/service YAML 不在仓库 | P1 |
| WebUI PVC | 无持久化存储，重启丢数据 | P1 |
| Agent 删除同步 Ingress | 删除 agent 不清理 Ingress 路径 | P2 |

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

## 🔲 Phase 3c: 知识库（未开始）

**预估**: 3 周
**前置依赖**: Phase 1 ✅

### 计划交付物
- [ ] 共享记忆层（Redis → Qdrant 向量库）
- [ ] 知识库 CRUD API
- [ ] 知识搜索（向量相似度 + 关键词）
- [ ] Admin Panel 知识库页面（`/swarm/knowledge`）
- [ ] Agent 间知识共享协议
- [ ] E2E 测试覆盖

### 关键文件（计划）
- `admin/frontend/src/pages/swarm/KnowledgeBasePage.tsx`
- `hermes_agent/swarm/knowledge.py`

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

---

## 下一步建议

1. **P0 — 配置持久化**: 将 Ingress/Service YAML 保存到仓库（1-2 小时）
2. **P0 — 提交当前工作**: 品牌更新 + E2E 测试 + ComingSoon 页面（本会话未提交）
3. **P1 — WebUI PVC**: 添加持久化存储
4. **Phase 2 开始**: 任务监控页面开发
