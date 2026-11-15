# Phase 1 · 技能中心的应用运行时 — 测试方案

> 状态：定向测试已执行并通过；按用户要求未运行无关全仓回归，全量 CI、quickstart 空卷与人工 UAT 待执行。执行证据见 [06-test-report.md](06-test-report.md)
> 创建：2026-11-11
> 依据：[02-requirements.md](02-requirements.md)（FR-1～FR-15、AC-1～AC-12）、[03-technical-design.md](03-technical-design.md)

本文件保留完整测试基线。当前交付只执行与本次服务应用 v2 改动直接相关的单元、集成、迁移、前端门禁和 E2E 用例；不得把本文件中的全部用例视为已经执行或通过。

## 1. 测试范围与原则

**范围**：

- 应用 v2 契约、技能、连接、凭据、规则、发布、回滚、分页与 trace。
- 应用级运行时解析、同一 Agent 多应用隔离、全局工具旁路封堵。
- 渠道/入站事件/会话的应用版本固定。
- 标准案例 seed、不可变、复制和重启幂等。
- `0058` 破坏式迁移、空库初始化和旧表清理。
- 前端应用目录、详情页签、技能 Table/Drawer、只读示例和旧路由删除。
- 旧 Provider/Scenario/Industry Upgrade 代码、API、类型与测试删除。

**原则**：

1. **应用隔离必测**：不能只测“单应用可用”，必须构造两个应用同名技能/不同连接，以及同一 Agent 多应用。
2. **发布边界必测**：任何草稿修改都不能影响已绑定线上版本的渠道。
3. **版本固定必测**：入站 outbox、会话和 run 必须保留入站时应用版本。
4. **秘密不落明文必测**：API、数据库查询结果、发布 JSON、trace、审计和日志均检查。
5. **clean-break 必测**：旧路由/API/模块/类型不存在，不以 301/兼容行为通过。
6. **时间与网络不等待**：超时、重试、lease 通过直接改库或 mock 时钟构造；外部连接使用本地 mock server。
7. **迁移只测新增链**：不修改历史迁移；在空库和 `0057` 样本库分别执行 `0058`。

## 2. 测试环境与数据构造

| 环境 | 用途 |
|---|---|
| 单元测试（无 DB） | Pydantic 契约、digest、readiness 纯函数、映射/safety、分页参数 |
| PostgreSQL 集成 fixture | 应用/技能/连接/版本、渠道、outbox、会话、审计、迁移 |
| 本地 mock HTTP server | 连接测试、同名技能不同 endpoint、认证 Header 与响应校验 |
| demo/mock 模型 | Agent run 使用可编程工具调用，不依赖外部模型 |
| 前端 Vitest/Playwright + mock API | 目录分页、页签、Table/Drawer、示例只读、旧页面删除 |

**数据构造约定**：

- 应用 A/B 位于同租户同业务/工作区，便于证明应用级隔离。
- 同一 Agent 选择一个已发布版本，供 A/B 同时绑定。
- `order_lookup` 同时存在于 A/B，分别指向 `/a/orders` 与 `/b/orders`，返回可区分结果。
- 发布后直接修改数据库草稿或通过 API 修改，断言旧版本 JSON 与 digest 不变。
- 渠道入站测试直接调用 webhook/enqueue，再手动 claim worker，断言 outbox 固定版本。
- 示例复制测试要求预置一个 example 和一个已修改 user copy，再执行 seed。

## 3. 单元测试

| 编号 | 用例 | 预期 | 溯源 |
|---|---|---|---|
| P1-UT-01 | 解析 v1 配置含 `scenarios/capabilities` | v2 契约拒绝，字段错误清晰 | FR-1/FR-15，AC-9/AC-10 |
| P1-UT-02 | 创建应用未提供 Agent 或 Agent 归档 | 校验失败 `application_agent_required/not_found` | FR-1，AC-1 |
| P1-UT-03 | 指定不存在的 Agent version | 校验失败，不生成 draft | FR-1/FR-6，AC-1 |
| P1-UT-04 | 同应用重复 skill key / 跨应用相同 key | 同应用拒绝；跨应用允许 | FR-2，AC-2 |
| P1-UT-05 | 使用 `agent` 作为 skill type | enum 拒绝 | FR-2，AC-9 |
| P1-UT-06 | action 写技能未配置确认且无安全豁免 | readiness 失败或保存 422 | FR-5，AC-1 |
| P1-UT-07 | connection endpoint 含 userinfo/query/fragment | `HttpTool` 风格校验拒绝 | FR-3，C1 |
| P1-UT-08 | public headers 含 Authorization/Token | 拒绝并要求凭据配置 | FR-3/FR-4，C1 |
| P1-UT-09 | 保存连接凭据后读取 API 响应 | 只有 `credentials_configured=true`，无明文/密文 | FR-4，AC-12/C1 |
| P1-UT-10 | 凭据 payload 序列化到发布快照 | 快照只出现 `credential_ref` 与 digest | FR-4/FR-6，C1 |
| P1-UT-11 | 同一配置不同 JSON key 顺序计算 digest | digest 完全相同 | FR-6，AC-4 |
| P1-UT-12 | 缺少连接凭据/连接被删除后 readiness | 阻止发布，返回明确检查项 | FR-6，AC-4 |
| P1-UT-13 | 引用其他应用的 connection_id | 技能保存拒绝 | FR-2/FR-3，AC-2 |
| P1-UT-14 | Agent tools 含全局自定义 tool，应用无对应 skill | runtime 白名单不包含全局自定义 tool | FR-8，AC-3 |
| P1-UT-15 | Agent tools 含 builtin，应用规则允许 | 只保留 builtin ∩ 应用授权 | FR-8，AC-3 |
| P1-UT-16 | 同一 skill key 对应 A/B connection | resolver 按 application_id 返回正确 endpoint | FR-8，AC-2/AC-3 |
| P1-UT-17 | 直接编辑/删除 example | handler 拒绝 `example_immutable` | FR-11，AC-7 |
| P1-UT-18 | 复制 example | 新应用 `origin=user/immutable=false`，来源保留 | FR-11，AC-7 |
| P1-UT-19 | 应用分页默认/最大值/非法 page | 默认 10、最大 100、非法拒绝 | FR-12，AC-9 |
| P1-UT-20 | rollback 目标版本生成新版本 | `source_version=target`，原版本不变 | FR-7，AC-5 |
| P1-UT-21 | `on_error` 与 timeout 规则求值异常 | 拒绝执行并返回 `rule_evaluation_failed` | FR-5，C1 |
| P1-UT-22 | 金额/权限限制不满足 | 不调用外部连接，返回规则拒绝 | FR-5，C1 |

## 4. 集成测试

| 编号 | 用例 | 预期 | 溯源 |
|---|---|---|---|
| P1-IT-01 | 创建应用 → 选 Agent → 建技能/连接 → readiness → publish | 生成 v2 快照；`published_version=1`；审计完整 | FR-1/FR-6，AC-1 |
| P1-IT-02 | A/B 同名 `order_lookup` 指向不同 mock endpoint | A 取 A 数据、B 取 B 数据；修改 A endpoint 后 B 结果不变 | FR-2/FR-3/FR-8，AC-2 |
| P1-IT-03 | 同一 Agent 被 A/B 绑定，分别运行带工具调用 | 每次 run 只出现所属应用技能；无全局 tool | FR-8，AC-3 |
| P1-IT-04 | 已发布后修改 A 草稿技能/连接，再通过渠道运行 | run 仍按旧版本；trace 版本不变；UI flag 为未发布 | FR-6/FR-9，AC-4 |
| P1-IT-05 | 重新发布 A 并显式切换渠道版本 | 新消息使用新版本；旧入站事件仍使用入站固定版本 | FR-7/FR-9，AC-4/AC-6 |
| P1-IT-06 | 回滚到 v1 | 生成 v3（source=v1），published=v3；v1/v2 内容不变 | FR-7，AC-5 |
| P1-IT-07 | 渠道 webhook 入站 → outbox → worker | channel/event/conversation/run 均记录相同 app/version | FR-9/FR-10，AC-6 |
| P1-IT-08 | 入站后、处理前回滚应用 | outbox 仍按入站版本执行；后续新事件按新绑定版本 | FR-9/FR-10，AC-5/AC-6 |
| P1-IT-09 | 切换渠道到未发布/不存在版本 | 409/422，不修改原绑定 | FR-9，AC-6 |
| P1-IT-10 | 首次 seed + 二次启动 | 示例只存在一份；用户 copy 不被更新 | FR-11，AC-8 |
| P1-IT-11 | 复制 example 后编辑副本 | 副本可编辑；example 内容/digest 不变 | FR-11，AC-7 |
| P1-IT-12 | 访问 `/service-providers`、`/service-scenarios`、industry upgrade API | FastAPI 路由表不存在并返回 404；无兼容 handler | FR-15，AC-10 |
| P1-IT-13 | 空库执行 `0058` 后 seed、开始发布并接收渠道消息 | 一次成功，无手工 DDL | 迁移/FR-11，AC-11 |
| P1-IT-14 | 在 `0057` 结构预发布库执行 `0058` | 旧服务表被删除；新表/列存在；无数据转换错误；记录数据丢失预期 | 迁移，AC-11 |
| P1-IT-15 | 保存/轮换凭据、发布、运行、查看 trace/审计 | 各响应和库内审计无明文；连接执行能正确使用密文 | FR-4/FR-10，AC-12 |
| P1-IT-16 | 租户/业务/工作区跨范围访问应用、技能、连接 | 均表现为 404，无法借用同租户其他 workspace 资源 | FR-14，C2 |
| P1-IT-17 | `GET /service-apps?page=1&page_size=10` | 返回 page/page_size/total；排序稳定，10 条截断 | FR-12，AC-9 |
| P1-IT-18 | trace 记录技能/连接调用 | 含 app/version、agent/version、skill、connection、耗时、结果码；敏感值脱敏 | FR-10，AC-6/AC-12 |

## 5. 通用核对项

| 编号 | 核对项 | 通过标准 |
|---|---|---|
| P1-CM-01 | 迁移线性 | 空库和 `0057` 样本执行 `upgrade head` 成功；历史迁移未修改 |
| P1-CM-02 | 配置加载 | 示例 seed、timeout、page size、preview write、key file 默认值和环境覆盖正确 |
| P1-CM-03 | 前端三门槛 | `npm run typecheck`、`npm run check:i18n`、`npm run build` 全绿 |
| P1-CM-04 | 后端静态检查 | `uv run ruff check src tests` 通过；相关 pytest 全绿 |
| P1-CM-05 | 旧概念残留扫描 | `src/`、`frontend/src/`、router 注册、client 类型中 Provider/Scenario/ToolBridge/industry upgrade 目标范围无残留 |
| P1-CM-06 | 秘密扫描 | 发布 JSON、API fixture、日志、审计、trace、git diff 无明文 token/key/password |
| P1-CM-07 | 权限 | Reader 不能写；Admin 可发布；跨 scope 不可见；403/404 语义正确 |
| P1-CM-08 | i18n | 新增用户可见文案中英文齐全；示例、技能、连接、规则、发布/回滚均有翻译 |
| P1-CM-09 | 分页 UI | Ant Design 原生分页；默认 10；底部对齐；总数/页码/切换正常 |
| P1-CM-10 | 文档一致性 | 中英文档成对存在；编号可溯源；03 路径/迁移号与实际实现一致 |
| P1-CM-11 | 审计 | 关键动作均落审计，详情无秘密；失败发布留下可定位错误 |
| P1-CM-12 | quickstart | 空卷启动一次完成迁移/seed；重启幂等；健康检查通过 |

## 6. 回归范围

- Agent 草稿、发布、版本快照与归档。
- 会话创建、消息提交、run 提交/执行与 SSE。
- 渠道 Provider catalog、generic webhook、inbound outbox、delivery worker。
- 知识库检索、记忆工具、工单/人工协同、审批。
- RBAC、身份、审计、运行与观测。
- 前端应用导航、Agent 管理、会话工作台、渠道页、全量 i18n/typecheck/build。
- 删除旧 Scenario/Provider/Industry 后，所有仍通过它们装配的服务不得导入失败。

回归原则：新应用上下文为空的历史 run 不应在客户渠道出现；平台内部诊断若需要旧 run 重放，必须以只读/测试路径处理，不恢复客户流量兼容。

## 7. 缺陷分级与出口准则

| 级别 | 定义 | 处理 |
|---|---|---|
| P0 阻断 | 跨租户/跨应用技能或凭据泄露；渠道绕过应用版本；发布快照可变；数据破坏超预期 | 停线修复并全量回归 |
| P1 严重 | 同名技能调用错误连接；示例可编辑/seed 覆盖；回滚不生效；迁移失败；明文秘密 | 修复前不得验收 |
| P2 一般 | 分页/空态/文案/local trace 瑕疵；不影响主流程 | 有 owner/期限后可带问题验收 |
| P3 轻微 | 样式细节、非关键日志 | 排期修复 |

**出口准则**：

- P1-UT/IT/CM 全部通过，含新增 E2E 用例。
- 空库 quickstart 和 `0057 → 0058` 破坏式迁移均通过。
- 两应用同名技能、同一 Agent 多应用、渠道入站固定版本三个主场景连续执行通过。
- 旧路由/API/类型目标清理结果为 0。
- 无 P0/P1 未关闭，无明文凭据残留。
- 回归套件全绿；CI 结果已记录。
