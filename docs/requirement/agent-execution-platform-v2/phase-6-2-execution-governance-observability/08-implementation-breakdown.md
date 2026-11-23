# Phase 6-2 · Execution Governance Observability — Implementation Breakdown

> Status: 已批准作为后续实施的文档基线；所有任务均未实施、未测试、未验收。本文件不提供任何实施完成或验收通过的结论。
> Created: 2026-11-22
> Basis: Phase 6 `02-requirements.md` FR-16「可运维性」；本阶段 `01-business-goals.md`（G1~G4）、`02-requirements.md`（FR-1~FR-10、AC-1~AC-10）、`03-technical-design.md`；批准范围基线中的冻结编号（SIG-1~SIG-8、R-1~R-10、T-1~T-14、UT-1~UT-14、IT-1~IT-8、FE-1~FE-10、CM-1~CM-6、A-1~A-10、C-1~C-6）。
> Scope note: 当前集成基线下 `backend/migrations/versions/` 已应用到 `0071_execution_credential.py`（更早的 `0068_open_application_archive.py` / `0069_open_application_unique_name.py` 为历史）。严禁修改任何已应用历史迁移；`0072` / `0073` 仅为 planning 值。

## 1. 实施顺序与开发入口

### 1.1 交付形态

采用 **加性、按垂直切片** 的交付形态，不新建平行子系统：

1. 治理查询骨架与 B 类端点（T-1~T-6）：在现有 observability 路由内加 Admin-only 治理端点，全部只读。
2. 计划迁移与写入接线（T-7~T-8）：0072 + SSE 409 写入点、0073 + parser collector 接线，实施前重验 head。
3. 前端、文案与验证（T-9~T-13）：API client 类型、治理 tab 与面板、四语 i18n、后端单测/集成测试、前端 Playwright 回归。
4. 组合根与文档同步（T-14）：现状复核、部署样例确认、双语文档一致性。

替代方案（被否决）：新建独立治理服务/事件存储会造成第二份事实来源；一次性横向大爆炸实现会推迟首个可验证行为。本阶段不开放不可信多租户，不改变执行语义。

### 1.2 开发入口与历史迁移约束

- 当前集成基线：`backend/migrations/versions/0070_execution_fencing_event_outbox.py` 与 `0071_execution_credential.py` 已存在并构成迁移链末端；`0068` / `0069` 为已合并的历史迁移。
- 开发入口为「当前集成基线」，禁止修改 `0001`~`0071` 中任何已应用历史迁移；新增迁移只能向后追加。
- 所有新路由落在 `backend/src/agent_platform/applications/customer_service/platform_routes.py`，与现有 `/observability/*` 同模块；不改公开 `RunView`、不改 SSE 响应契约、不改 `hashRouter.ts` 与全局导航。
- 任何新发现的路径、迁移号或公开契约冲突，必须先登记 R-n 裁定并同步修订 01/02/03/08 双语文档，再改生产代码。

### 1.3 任务拆解

> 下列「涉及文件」中标注「新增」的文件为本阶段计划新建；其余均为现有文件修改点。`core_platform/...`、`applications/...` 路径位于 `backend/src/agent_platform/` 之下；表中为简洁省略该前缀处已注明。

| # | 任务 | 目标 | 涉及文件 | 依赖 | 验证点 | 溯源 |
|---|---|---|---|---|---|---|
| T-1 | 统一治理路由骨架与权限/scope | 建立 `/api/v1/observability/execution/*` 只读路由骨架；统一 `require("admin")`、`resolve_scope()` + `scope_predicate()`、分页参数与错误码；确认注册 | `backend/src/agent_platform/applications/customer_service/platform_routes.py`；`backend/src/agent_platform/applications/customer_service/application.py` | — | 非 admin 全部 403 `insufficient_role`；400 无效过滤/分页；scope 过滤生效；空结果稳定空状态 | FR-1；SIG-1~SIG-8；Phase 6 FR-16；R-1/R-2/R-3 |
| T-2 | Fencing 端点 + service | 新增 `GET /observability/execution/fencing-denials`；JOIN `runtime_runs` 带出 tenant/scope；time/reason/operation 过滤与分页 | `platform_routes.py`；`core_platform/agent_execution/reliability/ownership.py`（只读，不改写入语义）；`runtime_runs` JOIN | T-1 | 记录带 tenant/scope；过滤与分页正确；孤立记录标注部署级；无 Secret | FR-2；SIG-1；Phase 6 FR-16；R-2 |
| T-3 | 清理失败端点 | 新增 `GET /observability/execution/cleanup-failures`，返回 `cleanup_status='failed'` 与「已请求取消未确认」两类 | `platform_routes.py`；`schemas.py`（`RunView` 定义处，约 18-27，仅确认零改） | T-1 | 两类记录均返回；公开 `RunView` 字段零变更；状态歧义按未确认呈现，不伪报 cancelled | FR-4；SIG-3；Phase 6 FR-16；R-3 |
| T-4 | Outbox 端点 | 新增 `GET /observability/execution/outbox`：pending 数、最老 `available_at` 滞留秒数、failed `last_error`、24h published 计数 | `platform_routes.py`；`core_platform/agent_execution/events/outbox.py`（复用 `pending_count`/重扫）；`backend/src/agent_platform/applications/platform_runtime/runtime_composition.py`（挂 `operational_stats().outbox_pending`） | T-1 | 四项指标正确；JOIN `runtime_runs` 生效；不触发发布副作用；无 Prometheus | FR-5；SIG-4；Phase 6 FR-16；R-1/R-2/R-8 |
| T-5 | usage 冲突端点 | 新增 `GET /observability/execution/usage-conflicts`：supersession 链与唯一约束拒绝的重复来源 | `platform_routes.py`；`core_platform/agent_execution/events/usage.py`（复用 `aggregate_effective_usage()`） | T-1 | 链与重复来源可见；按 `tenant_id` 过滤；不重复计数、不改聚合语义；真实冲突计数不默认启用 | FR-7；SIG-6；Phase 6 FR-16；R-2 |
| T-6 | 凭据审计端点 | 新增 `GET /observability/execution/credential-audit?action=revoked`；吊销状态复用 `GET /execution-credentials` | `platform_routes.py`；`backend/src/agent_platform/applications/customer_service/execution_credential_routes.py`（复用 `public_metadata()`、`require("admin")`） | T-1 | 审计行按 tenant 过滤可见；`public_metadata()` 无 Secret；越权 403；无匹配空状态 | FR-9；SIG-8；Phase 6 FR-16；R-1 |
| T-7 | 迁移 0072 + 409 写入点 | 新迁移 `0072_execution_replay_gap_events`（planned）；在 SSE 409 分支 best-effort 写一条有界缺口事件 + admin 查询端点 `replay-gaps` | `backend/migrations/versions/0072_execution_replay_gap_events.py`（新增，planned）；`backend/src/agent_platform/applications/customer_service/runtime_routes.py`（约 105-112）；`platform_routes.py` | T-1；head 重验通过 | 新库升级成功；409 写入一条且有界；写入失败不阻断 409；SSE `id=sequence` / `event_replay_gap` / `X-Event-Retention-Floor` 零变更 | FR-6；SIG-5；Phase 6 FR-16；R-5 |
| T-8 | 迁移 0073 + parser collector 接线 | 新迁移 `0073_execution_parser_diagnostics`（planned）；在 composition 接线 collector/sink + admin 查询端点 `parser-diagnostics` | `backend/migrations/versions/0073_execution_parser_diagnostics.py`（新增，planned）；`core_platform/agent_execution/events/diagnostics.py`；`backend/src/agent_platform/applications/platform_runtime/runtime_composition.py`；`platform_routes.py` | T-1；head 重验通过 | 五类分类计数可见；原始样本与 Secret 零出现；collector 已接线；`execution_parser_raw_sample_enabled=false` 沿用 | FR-8；SIG-7；Phase 6 FR-16；R-4/R-5 |
| T-9 | 前端 API client 类型与函数 | 定义治理端点请求/响应类型与调用函数，契约与 T-1~T-8 对齐 | `frontend/src/shared/api/client.ts`（及治理类型定义，按现有分层落位） | T-1~T-6（契约冻结） | 类型与契约一致；错误按 fail-closed 处理；无 Secret 字段进入前端模型 | FR-1~FR-9；SIG-1~SIG-8；R-7/R-9 |
| T-10 | 前端治理 tab 与面板组件 | `ObservabilityPage.tsx` 顶部加 antd `Tabs`；新增 `ExecutionGovernancePanel.tsx`；复用基础组件；admin 门控 | `frontend/src/features/observability/ObservabilityPage.tsx`；`frontend/src/features/observability/ExecutionGovernancePanel.tsx`（新增）；复用 `useResource`/`Panel`/`Table`/`Trace`/`serverPagination`（`frontend/src/shared/api/client.ts`、`frontend/src/app/hashRouter.ts` 仅确认零改） | T-9 | 治理 tab 仅 admin 可见；仅治理 tab 激活且 admin 时挂载；「运行总览」Panel 零删改；空状态/loading 稳定 | FR-10；SIG-1~SIG-8；Phase 6 FR-16；R-7/R-9 |
| T-11 | 四语文案与 check:i18n | 新增文案 `t('中文键')`，四语齐平并通过 `npm run check:i18n` | `frontend/src/i18n/locales/zh-CN.json`；`frontend/src/i18n/locales/zh-TW.json`；`frontend/src/i18n/locales/en.json`；`frontend/src/i18n/locales/hi.json` | T-10 | 四个 locale 键齐平；`npm run check:i18n` 通过；缺键不得上线 | FR-10；SIG-1~SIG-8；R-7/R-9 |
| T-12 | 后端单测/集成测试 | 完成 UT-1~UT-14（后端单元）与 IT-1~IT-8（PG 集成），覆盖权限/租户/脱敏/迁移/SSE 兼容 | `backend/tests/`（新增治理端点单测/集成测试，按现有测试惯例命名；复用现有 observability/credential/migration 相关测试） | T-1~T-8 | 每个 UT/IT 有独立结论；Secret canary 零出现；跨租户拒绝；公开 `RunView`/SSE 零 diff；迁移新库升级通过 | AC-1~AC-9；FR-1~FR-9；R-5 |
| T-13 | 前端 Playwright 回归 | 完成 FE-1~FE-10，覆盖 tab 可见性、按需挂载、空状态、分页与四语 | 前端 Playwright 回归用例（FE-1~FE-10，按现有前端测试目录落位） | T-10、T-11 | admin/普通用户分角色断言；无治理请求泄漏；空状态 fail-closed；hashRouter/全局导航零变更 | AC-10；FR-10；R-7/R-9 |
| T-14 | 组合根/settings/部署样例接线与文档同步 | 确认 0072/0073 head 重验记录、组合根接线、部署样例无 Secret、双语文档一致；CM-1~CM-6 一般检查 | `backend/src/agent_platform/applications/platform_runtime/runtime_composition.py`；现有 `backend/.env.example` / `deploy/` 部署样例（仅确认，不新增开关）；本阶段 `01`~`03`、`08` 双语文档 | T-7、T-8、T-13 | 无新配置开关；样例无 Secret/密钥；迁移号与 head 记录一致；双语逐段对应；CM-1~CM-6 通过 | FR-1~FR-10；SIG-1~SIG-8；R-5/R-6/R-8/R-10 |

`core_platform/...`、`applications/...` 路径以 `backend/src/agent_platform/` 为根；表中省略前缀者仅指该根下的同名模块。所有「新增」文件在实施前须先完成 R-n 登记与双语文档同步（若涉及新路径/迁移号/公开契约变化）。

## 2. 关键裁定 R-1~R-10

以下裁定逐字沿用批准范围基线，均采用「文档 / 现实 / 裁定」结构。

### R-1 — 治理端点 Admin-only

- **文档**：FR-1 要求统一治理查询 API；FR-3 的 Worker 状态需要展示。
- **现实**：既有 `/audit` 与 `execution_credential_routes.py` 五个路由均为 admin；`GET /notifications/*` 为 Reader；治理数据此前无任何专用路由。
- **裁定**：所有新增 `/observability/execution/*` 端点 Admin-only（对齐 `/audit` 与凭据路由），不向 Reader 暴露；Worker 丢失复用 Reader 的 `/notifications/*` 但治理 tab 仅 admin。

### R-2 — 无 tenant_id 的表处理

- **文档**：FR-1/FR-5/FR-7 要求租户/scope 过滤。
- **现实**：`execution_fencing_denials`、`runtime_event_outbox` 无 `tenant_id`；`worker_heartbeats` 为部署级；`runtime_usage_ledger`、`execution_credential_audit` 自带 `tenant_id`。
- **裁定**：`execution_fencing_denials`/`runtime_event_outbox` 无 tenant_id，必须 JOIN `runtime_runs`；`worker_heartbeats` 为部署级、无租户维度，UI 明示「部署级」。

### R-3 — 公开 RunView 不变

- **文档**：FR-4 需要暴露 cleanup 状态与取消未确认。
- **现实**：`RunView`（`schemas.py:18-27`）不含 `cleanup_status` / `cancel_requested_at` / `cancel_confirmed_at` 等字段；公开契约被现有客户端使用。
- **裁定**：不改公开 `RunView`；cleanup 状态只经 admin 治理端点暴露。

### R-4 — parser 敏感内容

- **文档**：FR-8 要求 parser 诊断可视化。
- **现实**：`execution_parser_raw_sample_enabled=false`；`ParserDiagnosticCollector` 只有内存计数与可选 sink；原始样本属于 D 类敏感内容。
- **裁定**：parser 原始样本/Secret 永不进 UI；只显示分类计数与有界脱敏原因码。

### R-5 — 迁移号 planning

- **文档**：03 规划 `0072_execution_replay_gap_events` 与 `0073_execution_parser_diagnostics`。
- **现实**：当前 head 为 `0071_execution_credential`（0068/0069 已为历史）；head 可能在实施前因集成分支推进而变化。
- **裁定**：迁移号 `0072`/`0073` 为 planning 值；实施前必须动态重验单一 head，若变化则同步修订双语文档，禁止改已应用历史迁移。

### R-6 — 不预写报告

- **文档**：阶段惯例要求 06/07 报告。
- **现实**：本阶段尚无实际测试与验收执行，无证据可写入报告。
- **裁定**：不预写 `06-test-report.md` / `07-acceptance-report.md`。

### R-7 — 前端路由零变更

- **文档**：FR-10 要在「运行与审计」页内新增治理 tab。
- **现实**：`hashRouter.ts` 的 `pages` 含 `observability`，但无 `/observability/:sub` 子路由；页面当前为纵向 Panel。
- **裁定**：新增前端 tab 不改 hashRouter/全局导航；治理组件按需挂载。

### R-8 — 无新监控依赖

- **文档**：FR-5 需要 Outbox lag 与投递失败指标。
- **现实**：无 Prometheus、无 `/metrics`；已有 `monitor_checks` / `notifications` 与结构化日志；Phase 7 明确排除 Prometheus。
- **裁定**：不引入 Prometheus 或新监控依赖；复用 `monitor_checks`/`notifications` 与结构化日志。

### R-9 — 前端设计规则

- **文档**：FR-10 要求前端治理 tab 与稳定空状态。
- **现实**：项目有 `frontend-dev` 设计规则，既有页面使用 `Panel`/`Table`/`Tag` 等惯例。
- **裁定**：前端遵循 `frontend-dev` 设计规则：单一主题色、标签在输入上方、无嵌套灰卡、稳定空状态与 loading。

### R-10 — 不开放高风险能力

- **文档**：阶段目标为治理可见性。
- **现实**：执行语义、不可信租户开关、生产 Codex 路由均不在本阶段授权范围内。
- **裁定**：不开放不可信多租户/生产 Codex 路由；本阶段不声称高风险能力启用或生产放行。

## 3. 迁移号重验规则（R-5 执行细则）

1. 在 T-7 / T-8 创建迁移文件 **之前**，对 `backend/migrations/versions/` 执行 head 检查，确认唯一 head。当前集成基线预期为 `0071_execution_credential`（planned `0072` 的 `down_revision`，`0073` 的 `down_revision` 为 `0072`）。
2. 若实际 head 与预期不同，不得直接沿用例外编号创建文件：先登记新的 R-n 裁定（写明「文档 / 现实 / 裁定」），再同步修订 `01`/`02`/`03`/`08` 双语文档中的迁移号，最后才创建迁移文件。
3. 禁止修改任何已应用历史迁移（含 `0001`~`0071`，以及 `0068` / `0069`）；新增只能向后追加。
4. 新迁移采用 expand → 有界回填 → 校验 → 读切换；有界写入失败不影响主流程（SSE 409 不阻断，parser sink 失败只记日志）。
5. 迁移号重验结果须写入 T-14 的文档同步记录，作为 CM 一般检查与 C-4 数据完整性与迁移门槛的证据。

## 4. 测试编号与完成定义（DoD）

### 4.1 测试与验收编号映射

| 层 | 编号范围 | 覆盖内容 | 归属任务 |
|---|---|---|---|
| 后端单元 | UT-1~UT-14 | 权限/错误码、scope 过滤、分页、各端点查询口径、Secret canary、空状态、409 兼容等 | T-12 |
| PG 集成 | IT-1~IT-8 | 新库升级、JOIN 租户隔离、0072/0073 写入、SSE 409 语义零 diff、公开 `RunView` 零 diff、跨租户拒绝 | T-12 |
| 前端 Playwright | FE-1~FE-10 | tab 可见性、按需挂载、分页、空状态 fail-closed、四语、hashRouter 零变更 | T-13 |
| 一般检查 | CM-1~CM-6 | i18n 键齐平、无 Prometheus、无 Secret/原始样本进 UI、迁移 head 记录、双语对应、无 issue/PR 号预写 | T-14 |
| 验收场景 | A-1~A-10 | 一一对应 AC-1~AC-10 | 实际验收阶段 |
| 门槛 | C-1~C-6 | C-1 功能语义；C-2 租户/权限隔离；C-3 Secret 与脱敏；C-4 数据完整性与迁移；C-5 兼容性（公开 RunView/SSE 不变）；C-6 无 P0/P1 且单一验收记录 | 实际验收阶段 |

### 4.2 完成定义（DoD）

单任务完成需同时满足：

- 目标中列明的端点/组件/迁移字段全部按 03 技术设计与冻结编号实现，涉及文件与基线一致。
- 对应验证点全部通过，并留下可追溯的测试/检查记录；未通过的项不得标记完成。
- 若发现与基线冲突，先登记 R-n 并同步双语文档，再继续实施。

整体 DoD（阶段级）需同时满足：

1. T-1~T-14 全部完成；UT-1~UT-14、IT-1~IT-8、FE-1~FE-10、CM-1~CM-6 均有独立结论与证据。
2. AC-1~AC-10 对应 A-1~A-10 逐条执行并写入验收记录；C-1~C-6 门槛全部满足，无 P0/P1，且只有单一验收记录。
3. 兼容性硬约束成立：公开 `RunView` 零变更、SSE `id=sequence` / `event_replay_gap` / `X-Event-Retention-Floor` 零变更、`hashRouter` 与全局导航零变更、无 Prometheus。
4. 安全硬约束成立：治理响应与 `public_metadata()` 无 Secret；parser 原始样本与 Secret 零出现；跨租户治理数据默认拒绝。
5. 迁移约束成立：0072/0073 已重验单一 head；已应用历史迁移零修改；双语文档迁移号一致。
6. 文档约束成立：01/02/03/08 中英逐段对应；`npm run check:i18n` 通过；不预写 `06-test-report.md` / `07-acceptance-report.md`；不登记 issue/PR 号。
7. 状态真实：只有在上述全部完成后，才可把状态从「未实施、未测试、未验收」更新；在此之前所有任务保持未完成。
