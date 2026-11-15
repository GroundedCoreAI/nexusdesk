# Phase 1 · 技能中心的应用运行时 — 实施拆解方案

> 状态：核心任务已实施；定向测试、迁移与静态门禁通过；全量 CI、quickstart 空卷与人工 UAT 待执行
> 创建：2026-11-11
> 依据：[01](01-business-goals.md)～[05](05-acceptance-plan.md) 全部规划文档 + 现状代码核查
> 约束：clean-break；不做旧数据迁移与兼容层；开发库允许清空；后端/前端/迁移必须同版本部署

## 1. 任务拆解

依赖主线：**迁移 → v2 契约 → 连接/技能 → 发布 → 应用运行时 → 渠道/会话 → API → 旧代码删除 → 前端 → 测试/部署**。

T3/T4 可在 T2 后并行；T8/T9 可在 T5 后并行设计接口，但需按顺序合并；T14/T15 可在 T12/T13 接口稳定后并行。

| # | 任务 | 文件（新建/修改） | 依赖 | 溯源 |
|---|---|---|---|---|
| T1 | 新增 `0058_service_application_v2`：删除旧服务场景/Provider/行业安装表；重建应用 v2、技能、连接、凭据、版本、trace；扩展渠道/入站/会话 | `backend/migrations/versions/0058_service_application_v2.py`（新） | — | FR-1/2/3/4/6/9/10/15，AC-1/4/6/11 |
| T2 | 重写应用契约：Application、Skill、Connection、RuleConfig、v2 version snapshot；禁止 v1 字段 | `.../service_apps/models.py` | T1 | FR-1～FR-6，AC-1/2/4/5 |
| T3 | 应用连接服务：CRUD、同应用引用校验、HttpTool 校验、EgressPolicy 测试、Vault 凭据轮换 | `.../service_apps/connections.py`（新） | T1/T2 | FR-3/FR-4，AC-2/12 |
| T4 | 应用技能服务：CRUD、参数/结果映射、safety、同应用连接约束、action 写入规则 | `.../service_apps/skills.py`（新） | T1/T2 | FR-2/FR-5，AC-1/2/3 |
| T5 | 发布服务：readiness、canonical snapshot、digest、版本历史、diff、追加式回滚 | `.../service_apps/releases.py`（新） | T2/T3/T4 | FR-6/FR-7，AC-4/5 |
| T6 | 应用服务重构：CRUD、分页、Agent binding、示例 immutable 检查、版本列表、归档/恢复 | `.../service_apps/service.py` | T2/T5 | FR-1/FR-12/FR-14，AC-1/9 |
| T7 | 示例/模板：代码模板收敛到应用 v2；reserved `example-` key；幂等 seed、复制、lineage | `.../service_apps/seed.py`（改） | T2/T6 | FR-11，AC-7/8/11 |
| T8 | 应用运行时解析器：应用版本 → Agent 版本 → 技能/连接/builtin 白名单；trace metadata | `.../service_apps/runtime.py`（新） | T5 | FR-8/FR-10，AC-2/3/6 |
| T9 | Run 注入：`CustomerService._submit_run` 注入 application context；`RuntimeFactory` 仅用应用连接/授权技能 | `.../customer_service/service.py`、`applications/platform_runtime/runtime_factory.py` | T8 | FR-8，AC-3/4 |
| T10 | 渠道改造：`ChannelInput.application_id/version`；channel CRUD/版本切换；入站 outbox 固定版本 | `.../channel/service.py`、`applications/customer_service/platform_routes.py` | T6/T8 | FR-9，AC-4/6 |
| T11 | 会话/trace：会话写 application/version；应用 trace；保留派生 agent 字段 | `.../conversation/service.py`、`applications/platform_runtime/platform_services.py` | T9/T10 | FR-10，AC-6/12 |
| T12 | 应用 v2 API：应用/技能/连接/测试/发布/回滚/复制/分页/trace；旧 API 注册移除 | `.../service_apps/routes.py`、`applications/customer_service/application.py` | T3～T11 | FR-12/13/15，AC-9/10 |
| T13 | 后端 clean-break：删 Provider/Scenario/ToolBridge/Industry Installation/Upgrade 装配与模块；保留模板编译逻辑 | `applications/platform_runtime/platform_services.py`、`service_groups.py`、`customer_service/{providers,scenarios,industry_packs}/**` | T9/T12 | FR-15，AC-10 |
| T14 | 前端 API/类型：删 Provider/Scenario/Upgrade；加应用 v2、技能、连接、版本、分页类型和 client | `frontend/src/shared/api/client.ts` | T12 | FR-1/2/3/6/12，AC-1/4/9 |
| T15 | 应用目录拆分：标准案例/我的应用筛选、只读示例、复制、分页默认 10 | `frontend/src/features/service-apps/catalog/**`、`ServiceAppsPage.tsx` | T14 | FR-11/12，AC-7/9 |
| T16 | 应用详情：六页签；概览/智能体组件；草稿/线上状态 | `features/service-apps/detail/**` | T14/T15 | FR-13，AC-1/4/9 |
| T17 | 技能/连接 UI：AntD Table/Drawer、分页、schema/映射、安全规则、测试、凭据不回显 | `features/service-apps/skills/**`、`connections/**` | T14/T16 | FR-2/3/4/5/13，AC-2/9/12 |
| T18 | 规则/调试/渠道发布 UI：fallback/handoff、草稿预览 write gate、渠道版本切换、发布检查/历史/回滚 | `features/service-apps/rules/**`、`debug/**`、`release/**` | T12/T14 | FR-5/6/7/9/13，AC-4/5/6/9 |
| T19 | 前端 clean-break：删除 `service-scenarios`、行业能力页、`/service-apps/industry`、旧导航/样式/测试 | `frontend/src/features/service-scenarios/**`、`IndustryCapabilitiesPage.tsx`、`app/App.tsx` | T15～T18 | FR-15，AC-9/10 |
| T20 | i18n/视觉：应用、技能、连接、规则、版本、错误码、示例标识中英文；分页底部对齐 | `frontend/src/i18n/**`、`features/service-apps/**/*.css` | T15～T19 | FR-12/13，AC-9 |
| T21 | 后端测试：contracts、connections/credentials、skills/rules、release/rollback、runtime isolation、channel、examples、migration | `backend/tests/test_service_application_v2_*.py` | T1～T13 | 04 UT/IT |
| T22 | 前端测试：目录分页、六页签、Table/Drawer、示例只读、旧路由不存在、中英文 | `frontend/tests/service-app-v2*.spec.ts` | T14～T20 | 04 IT/CM |
| T23 | 配置/部署/文档收尾：settings、seed 启动、quickstart 空卷、CI、文档回填与旧主题状态 | `settings.py`、`applications/**/main.py`、`deploy/**`、`docs/**` | T1～T22 | 03 配置/上线，AC-10/11 |

## 2. 实施顺序与合并门槛

### 2.1 第一合并单元：数据与应用契约

T1 + T2。

门槛：

- 空库迁移成功。
- v1 配置被拒绝。
- 应用必须绑定 Agent/version。
- 技能/连接/凭据表具备同 application 外键与唯一约束。

### 2.2 第二合并单元：配置与发布

T3 + T4 + T5 + T6 + T7。

门槛：

- 两应用同名技能可保存不同连接。
- 凭据 API 不回显。
- readiness 阻止缺 Agent/连接/凭据的发布。
- 发布/回滚仅追加版本。
- seed/copy 测试通过。

### 2.3 第三合并单元：运行时与渠道

T8 + T9 + T10 + T11。

门槛：

- 同一 Agent 被 A/B 引用时工具集合隔离。
- 渠道入站 outbox 固定应用版本。
- 会话/run/trace 可追溯。
- 全局 Tool Gateway 不再隐式授权客户应用。

### 2.4 第四合并单元：API 与 clean-break

T12 + T13。

门槛：

- 新 API 全绿。
- 旧 API 路由表中不存在。
- Provider/Scenario/IndustryPack 装配不再启动。
- 模板内容仍能生成标准案例。

### 2.5 第五合并单元：前端

T14～T20。

门槛：

- 五主概念 UI。
- 默认分页 10、AntD 原生分页、底部对齐。
- 示例只读/可复制。
- 旧 `service-scenarios` 和 `/service-apps/industry` 不存在。
- 中英文、typecheck、build、E2E 全绿。

### 2.6 第六合并单元：验证与交付

T21～T23。

门槛：

- 04 出口准则满足。
- quickstart 空卷一次启动。
- CI、部署说明、文档索引与旧主题取代说明完成。

## 3. 文档与现实不一致清单及裁定

### R1 迁移 head 与新增编号

文档要求新增 v2 迁移。现实：当前 head 为 `0057_industry_pack_runtime`，历史迁移 `0054`～`0057` 已存在且不可修改。**裁定**：新增 `0058_service_application_v2.py`，`down_revision="0057_industry_pack_runtime"`；破坏式清理在该迁移中执行。

### R2 Provider 不是应用级连接

文档目标是 `service_application_connections`。现实：`service_provider_registry` 按租户/业务/工作区隔离，无 `application_id`，且只保存描述/config，不是真实执行连接。**裁定**：不扩展现有 Provider 表；新建应用连接/凭据表，删除 Provider Registry 及路由。

### R3 凭据位于 Tool Gateway

文档要求 Vault 密文。现实：`HttpTool.credential_id` 指向 `tool_credentials`，`RegisteredTool`/Tool Workspace 负责认证继承。**裁定**：新应用连接使用独立凭据表与 `CredentialVault`；发布只保留 `credential_ref`；全局 `tool_credentials` 不进入应用发布快照。

### R4 渠道当前绑定 Agent

文档要求渠道绑定应用版本。现实：`ChannelInput.agent_id`，`channels.agent_id`，入站调用 `conversations.create(..., current["agent_id"])`。**裁定**：`channels` 改存 `application_id/application_version` 并删除 agent 列；`channel_inbound_events` 增同列固定版本；`runtime_conversations.agent_id/version` 仅作派生查询冗余。

### R5 RuntimeFactory 当前使用 Agent 全局 tool snapshot

文档要求应用技能隔离。现实：`RuntimeFactory.for_run` 从 `snapshot["agent"]["tools"]` 构建全部 HTTP ToolGateway。**裁定**：存在 `snapshot["application"]` 时仅从应用 connections 构建工具；Agent 自定义全局 tool 不再隐式注入。Agent builtin 仍需与发布配置求交集。

### R6 前端页面实际规模

早期讨论称 `ServiceAppsPage.tsx` 超过 3000 行。现实实测为 2384 行，`IndustryCapabilitiesPage.tsx` 为 1021 行。**裁定**：以实测为基线；路由编排目标 ≤ 300 行，各业务页签独立且 ≤ 800 行。回填 `03` 修订说明。

### R7 旧测试覆盖大量 Provider/Scenario

现实：`backend/tests` 存在 `test_service_scenario_*`、`test_scenario_tool_bridge*`、`test_industry_pack_*` 等，前端存在 `service-scenarios.spec.ts`、`industry-capabilities.spec.ts`。**裁定**：删除针对旧概念的测试；新增 v2 测试。不得仅改断言保留旧运行时。

### R8 行业模板与安装生命周期耦合

现实：`industry_packs/compiler.py` 编译 Scenario/Capability，`installations.py` 管理 installation/upgrade/merge。**裁定**：保留有价值的模板内容/确定性编译思想，收敛到 `service_apps/seed.py` 输出应用 v2 示例；彻底删除 installations/upgrades/merge 与 `/industry-packs` 路由。

### R9 Alembic 已执行迁移不可改

clean-break 与迁移规范存在张力。**裁定**：不修改 `0054`～`0057`；`0058` 删除/重建旧表。迁移不作为旧数据升级方案，正式上线前清库。

### R10 `agent_id` 仍被会话/记忆/统计使用

现实：会话列表、Agent 管理删除检查、memory summary/extraction 等依赖 `runtime_conversations.agent_id`。**裁定**：保留 `agent_id/agent_version` 派生列，写入值为应用发布快照绑定；移除“渠道直接绑定 Agent”语义，但不做全库去列。涉及历史 run 的诊断按只读处理。

### R11 应用列表当前无分页

现实：`ServiceApplicationService.list` 返回全部 items/total；前端直接渲染。**裁定**：v2 list 采用 page/page_size 服务端分页，默认 10；前端使用 AntD 原生分页并底部对齐。

### R12 现有行业安装会在启动时创建应用

现实：行业 pack 安装/seed 可能创建 `service_applications` 并保留 installation 状态。**裁定**：`0058` 删除安装状态和旧应用；新 seed 用 reserved `example-` 前缀创建 immutable examples。`ON CONFLICT DO NOTHING`，绝不 update。

### R13 当前应用发布要求至少一个场景

现实：`_resolve_for_publish` 要求 enabled scenario，否则 `service_application_scenario_required`。**裁定**：v2 发布要求直接 Agent binding 与合法技能，不要求 scenario；knowledge-only 应用允许 0 个 query/action，但必须有 Agent 与发布策略。

### R14 当前 API 通过 ScenarioService/Provider 求 readiness

现实：`ServiceApplicationService` 构造依赖 `ScenarioService` 与 `ServiceProviderRegistry`，readiness 收集 scenario/provider identity。**裁定**：v2 readiness 改为应用技能/连接/凭据/Agent 检查；先完成 T3～T5，再删除依赖，避免导入断裂。

### R15 行业模板入口删除不等于内容删除

现实：行业模板内容与 Provider 需求、scenario 编译深度耦合。**裁定**：删除 `/service-apps/industry` 与独立行业能力导航；保留应用目录中的“标准案例”来源筛选。模板代码只生成 examples，不能成为运行时特殊分支。

### R16 渠道入站 outbox 当前无应用字段

现实：`channel_inbound_events` 只关联 `channel_id`，worker 读取时再取 channel。**裁定**：在 enqueue 时写入 `application_id/application_version`；worker 使用事件固定版本，不重新读取渠道当前绑定来覆盖。

### R17 v1 版本表结构不足

现实：`service_application_versions` 只有 `config/source_version`，无 `schema_version/config_digest`。**裁定**：clean-break 重建表，增加 `schema_version/config_digest`；旧版本记录不迁移。

### R18 示例 key 必须保留命名空间

现实：应用 key 全局唯一，若未来用户创建同名 key，seed 会冲突。**裁定**：示例 key 使用保留前缀 `example-`；用户创建/复制 API 拒绝以 `example-` 开头的新 key。`0058` 重建后不存在旧用户 key 冲突。

### R19 示例凭据不能真实内置

现实：连接凭据通过 Vault 加密且有租户/资源绑定，代码模板无法携带真实租户密文。**裁定**：模板只含 mock/demo 或无认证连接；复制后的用户应用如需要真实认证，必须重新配置凭据。复制时可复制无秘密的连接配置，但 `credentials_configured=false`。

### R20 删除旧 API 需要同时处理装配与测试

现实：旧路由在 `applications/customer_service/application.py` 注册，服务在 `PlatformServices` 装配。**裁定**：T13 同时删路由注册、服务字段、`ServiceGroups` 字段、导入与测试；仅删 Router 文件会造成启动/测试失败。

### R21 客户应用与平台内部工具需要区分

现实：Tool Gateway 的全局工具目录有合法管理/调试用途。**裁定**：不删除 Tool Gateway 本身；只禁止其在客户应用 runtime 中作为隐式授权来源。平台内部工具仍可由平台能力使用，但不得出现在应用未授权技能列表。

### R22 配置模块路径与文档不一致

现实：仓库不存在 `backend/src/agent_platform/settings.py`；实际统一配置入口是 `backend/src/agent_platform/core_platform/platform_services/platform_settings/settings.py`。**裁定**：以实际路径为准，修订 03 的改动总览与配置章节；新增配置只能落在该模块，禁止为迁移文档新建一个平行 settings 文件。

## 4. 交接要点

### 4.1 给研发

- 严格按合并单元推进；T1/T2 先合并，T3～T7 完成后才可改运行时。
- 每完成一个合并单元，对照 02 的 FR 与 03 的路径自查。
- 发现新差异先登记为 R-n 并回填 03，不直接按旧代码猜设计。
- 迁移不修改 0054～0057；旧表清理只在 0058。
- 任何连接执行必须走 EgressPolicy/Vault；禁止临时明文凭据或绕过策略。

### 4.2 给 QA

- 按 04 用例逐条执行，不得只跑“单应用 happy path”。
- 重点数据集必须包含 A/B 同名技能、同一 Agent 双应用、发布后草稿修改、渠道排队后回滚。
- clean-break 以路由表/源码搜索/404 判定，不以 UI 隐藏判定。
- 迁移测试分别覆盖空库与 `0057` 预发布库，并确认数据丢失是预期而非意外。

### 4.3 给产品/验收

- 验收以 05 的 A1～A12 和 C1～C7 为基线。
- UAT 重点不是页面美观单项，而是能否无研发解释完成“复制案例 → 配置连接 → 预览 → 发布 → 绑渠道”。
- 任何仍要求用户理解场景/Provider/升级记录的设计，均视为概念收敛未完成。
