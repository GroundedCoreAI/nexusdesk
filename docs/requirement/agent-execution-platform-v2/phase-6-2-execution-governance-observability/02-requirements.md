# Phase 6-2 · Execution Governance Observability — Requirements

> Status: 已批准作为后续实施的文档范围基线；未实施、未测试、未验收
> Created: 2026-11-22
> Basis: Phase 6 `02-requirements.md` FR-16「可运维性」；本阶段 `01-business-goals.md`（G1~G4）；治理信号分类与冻结编号以批准的范围基线为准（SIG-1~SIG-8、US-1~US-4、FR-1~FR-10、AC-1~AC-10）。
> Scope note: 本阶段仅补「统一治理查询 API + 可视化 UI」；所有新增 `/observability/execution/*` 端点 Admin-only，不开放不可信多租户，不引入 Prometheus，不改执行语义与公开契约。

## 用户故事

**US-1 SRE**：作为 SRE，我希望在一个统一入口按租户、scope、时间和原因查询 fencing 拒绝、outbox lag 与清理失败等治理信号，以便主动巡检而不是事后翻日志。

**US-2 安全管理员**：作为安全管理员，我希望在仅 admin 可见的界面查看凭据吊销审计与 parser 分类诊断，且其中不含任何 Secret 或原始样本，以便确认安全状态而不引入新的泄露面。

**US-3 平台运维**：作为平台运维，我希望看到 Worker 丢失/恢复态（明确标注部署级）、清理失败与取消未确认、Outbox 投递失败，且不改变执行语义，以便定位部署级故障并安全处置。

**US-4 财务/审计人员**：作为财务/审计人员，我希望看到 usage 修正链与重复来源被唯一约束拒绝的记录，并能追溯到 run、tenant 与 actor，以便核对用量数据的可信度。

## 功能需求

### FR-1 统一治理查询 API（admin、租户/scope 过滤、无 Secret、统一错误码）

溯源：SIG-1~SIG-8；Phase 6 FR-16「可运维性」；裁定 R-1 / R-2 / R-3。

| 项 | 说明 |
|---|---|
| 触发时机 | admin 打开「执行治理」tab，或直接调用 `/api/v1/observability/execution/*` 任一端点时。 |
| 输入 | admin 身份（`require("admin")`）；可选的 tenant_id / business_scope / workspace 过滤、时间窗、reason / operation / action 过滤与分页参数。 |
| 输出 | 分页治理数据（仅经 admin 端点返回），不含任何 Secret 字段；统一错误码：403 `insufficient_role`、400 无效过滤/分页、409 保留期缺口说明。 |
| 执行方式 | 统一前缀 `/api/v1/observability/execution/*`，全部 Admin-only；无 `tenant_id` 的表 JOIN `runtime_runs`（按 run_id）取 tenant/scope，沿用 `resolve_scope()` + `scope_predicate()`；credential 路由仅按 tenant，不做 business_scope。 |
| 失败处理 | 非 admin / 越权一律 403 `insufficient_role`；过滤或分页非法返回 400；查询异常以统一错误码返回，不降级为 Reader 可见；空结果返回稳定空状态。 |

### FR-2 Fencing 拒绝

溯源：SIG-1；Phase 6 FR-16；裁定 R-2。

| 项 | 说明 |
|---|---|
| 触发时机 | 旧 owner / epoch 写入被 `ownership.py` 的 `FencingDenialRecorder` 记录（回滚后独立事务）后，或 admin 查看 fencing 拒绝列表时。 |
| 输入 | `execution_fencing_denials` 的 `run_id, operation, reason, stale_owner, stale_lease_epoch, current_owner, current_lease_epoch, created_at`；time / reason / operation 过滤与分页参数。 |
| 输出 | admin `GET /observability/execution/fencing-denials` 分页列表，JOIN `runtime_runs` 带出 tenant/scope；UI 治理表。 |
| 执行方式 | 只读查询，不改 `FencingDenialRecorder` 写入语义；该表无 `tenant_id`，强制 JOIN `runtime_runs`（按 run_id）。 |
| 失败处理 | 找不到 run_id 的孤立记录标注为无租户/部署级并在 UI 明示；查询失败按 FR-1 统一错误码返回，不暴露 Secret。 |

### FR-3 Worker 丢失与恢复态

溯源：SIG-2；Phase 6 FR-16；裁定 R-1 / R-8。

| 项 | 说明 |
|---|---|
| 触发时机 | `worker.runtime.heartbeat` / `runtime.lease_expired` 监控检查运行并写入 `monitor_checks` / `notifications` 后，或 admin 打开治理面板查看 Worker 状态时。 |
| 输入 | `worker_heartbeats`（`worker_id/host/started_at/beat_at/detail` JSONB）与 `monitor_checks` / `notifications`。 |
| 输出 | 复用现有 `GET /notifications/checklist`、`GET /notifications` 呈现 Worker 丢失/恢复态；UI 明示「部署级、非租户维度」。 |
| 执行方式 | 不新建事件历史表；数据获取复用 Reader 路由，但治理 tab 仅 admin 可见且仅 admin 时挂载。 |
| 失败处理 | 检查未运行或数据缺失时展示稳定空状态；不伪造恢复态；单项缺失不阻塞其他治理面板。 |

### FR-4 清理失败与取消未确认

溯源：SIG-3；Phase 6 FR-16；裁定 R-3。

| 项 | 说明 |
|---|---|
| 触发时机 | `runtime_runs.cleanup_status='failed'`，或 `cancel_requested_at` 非空且 `cancel_confirmed_at` 为空时。 |
| 输入 | `runtime_runs.cleanup_status`（`not_started/in_progress/completed/failed`）、`cleanup_updated_at`、`cancel_requested_at`、`cancel_confirmed_at`。 |
| 输出 | admin `GET /observability/execution/cleanup-failures` 返回「cleanup_status='failed'」与「已请求取消但未确认」两类记录；UI 表；公开 `RunView` 不含这些字段。 |
| 执行方式 | 只读 admin 端点，不改 Run 状态机与清理逻辑；host/workdir 清理失败告警仍只进 `LoggingAlertSink`（日志，不落表）。 |
| 失败处理 | 查询失败按 FR-1 统一错误码返回；状态歧义时按「未确认」呈现，不伪报 cancelled。 |

### FR-5 Outbox lag 与投递失败

溯源：SIG-4；Phase 6 FR-16；裁定 R-1 / R-2 / R-8。

| 项 | 说明 |
|---|---|
| 触发时机 | admin 查看 Outbox 运维指标，或 `runtime_event_outbox` 出现 pending 滞留 / failed `last_error` 时。 |
| 输入 | `runtime_event_outbox`（`run_id, seq, event_id UNIQUE, status(pending/published), attempts, available_at, created_at, published_at, last_error`）；复用 `events/outbox.py` 的 `pending_count` 与重扫。 |
| 输出 | admin `GET /observability/execution/outbox`：pending 数、最老 `available_at` 的滞留秒数、failed 列 `last_error`、24h published 计数；UI 指标卡/表。 |
| 执行方式 | 只读查询；该表无 `tenant_id`，JOIN `runtime_runs`；不引入 Prometheus，复用 `runtime_composition.ExecutionRuntimeSubsystem.operational_stats()` 的 `outbox_pending`（此前仅测试引用，现挂 admin 路由）。 |
| 失败处理 | 统计或重扫异常按统一错误码返回；不触发发布副作用，不伪造投递成功。 |

### FR-6 SSE 重放缺口

溯源：SIG-5；Phase 6 FR-16；裁定 R-5。

| 项 | 说明 |
|---|---|
| 触发时机 | SSE 客户端游标早于 `runtime_runs.event_retention_floor_seq` 而触发 409 `event_replay_gap`，或 admin 查看缺口历史时。 |
| 输入 | `runtime_runs.event_retention_floor_seq`；409 响应头 `X-Event-Retention-Floor`（`runtime_routes.py`）；新表 `execution_replay_gap_events`（迁移 `0072_execution_replay_gap_events`，planning）。 |
| 输出 | 在 409 分支写一条有界缺口事件 + admin 查询端点 + UI 缺口列表。 |
| 执行方式 | 新迁移 0072（实施前重验单一 head）+ 409 分支有界写入；不改 SSE `id=sequence`、`event_replay_gap` 语义与 `X-Event-Retention-Floor` 响应头。 |
| 失败处理 | 缺口事件写入失败不阻断 SSE 409 正常响应；迁移号变化须同步修订双语文档；禁止修改已应用的历史迁移。 |

### FR-7 usage 冲突与修正链

溯源：SIG-6；Phase 6 FR-16；裁定 R-2。

| 项 | 说明 |
|---|---|
| 触发时机 | `runtime_usage_ledger` 出现 `supersedes_id` 自引用修正链，或 `UNIQUE(run_id, source, source_event_id)` 拒绝重复来源时。 |
| 输入 | `runtime_usage_ledger`（`run_id, tenant_id, lease_epoch, source, source_event_id, usage, cost, is_estimate, supersedes_id`）与 `events/usage.py::aggregate_effective_usage()` 重建逻辑。 |
| 输出 | admin `GET /observability/execution/usage-conflicts`：supersession 链与被唯一约束拒绝的重复来源；UI 展示修正链。 |
| 执行方式 | 只读查询，该表自带 `tenant_id`；不改聚合语义；如需真实冲突计数，在唯一冲突/supersede 处补一条审计写（C 组件，可选，另立后续需求）。 |
| 失败处理 | 链数据不完整时按已知部分展示并标注；不重复计数、不改写 usage 数据。 |

### FR-8 parser 诊断（不含原始样本）

溯源：SIG-7；Phase 6 FR-16；裁定 R-4 / R-5。

| 项 | 说明 |
|---|---|
| 触发时机 | `ParserDiagnosticCollector` 记录 `malformed/unknown_schema/unknown_type/size_limit/critical_terminal` 分类计数时，或 admin 查看诊断趋势时。 |
| 输入 | `ParserDiagnosticCollector`（`events/diagnostics.py`）的内存 `self._counts` / `self._suppressed` 与可选 sink；新表 `execution_parser_diagnostics`（迁移 `0073_execution_parser_diagnostics`，planning）。 |
| 输出 | admin 查询端点 + UI 分类计数/趋势；仅显示分类计数与有界脱敏原因码。 |
| 执行方式 | 迁移 0073 + 在 composition 接线 collector/sink；沿用现有开关 `execution_parser_raw_sample_enabled=false`；原始样本与 Secret 永不进 UI（D 类敏感）。 |
| 失败处理 | collector 未接线或数据缺失时 UI 空状态；原始样本或疑似 Secret 一律不输出；迁移号变化须同步修订双语文档。 |

### FR-9 凭据吊销与审计

溯源：SIG-8；Phase 6 FR-16；裁定 R-1。

| 项 | 说明 |
|---|---|
| 触发时机 | 凭据 `status` 变为 `revoked` / `superseded`，或 `execution_credential_audit` 写入 `revoked` / `grant_denied` 等 `action` 时。 |
| 输入 | `execution_credentials`（`status active/superseded/revoked`、`version`、`rotated_at`、`revoked_at`）、`execution_credential_grants`、`execution_credential_audit`（`action created/rotated/revoked/grant_issued/grant_denied/grant_used`、`outcome`、`reason_code`、`actor`）。 |
| 输出 | 当前吊销状态直接复用 `GET /execution-credentials`（零后端工作）；新增 admin `GET /observability/execution/credential-audit?action=revoked` + UI 审计表；`public_metadata()` 字段不含 Secret。 |
| 执行方式 | 两条 admin 路由均为 `require("admin")`；凭据路由只按 tenant、不做 business_scope；审计端点按 `tenant_id` 过滤。 |
| 失败处理 | 无匹配审计返回空状态；任何响应不返回 Secret；越权 403 `insufficient_role`。 |

### FR-10 前端执行治理 tab（admin、四语、空状态 fail-closed）

溯源：SIG-1~SIG-8；Phase 6 FR-16；裁定 R-7 / R-9。

| 项 | 说明 |
|---|---|
| 触发时机 | admin 进入「运行与审计」页（`observability`，组件 `frontend/src/features/observability/ObservabilityPage.tsx`）并激活顶部「执行治理」tab 时。 |
| 输入 | `useAccess` 的 admin 布尔；`useResource<T>(path, refreshMs)` 与 `serverPagination` / `clientPagination`；`t('中文键')` 与四语 `src/i18n/locales/{zh-CN,zh-TW,en,hi}.json`。 |
| 输出 | 顶部 antd `Tabs`：「运行总览」保留现有全部 Panel，「执行治理」新增且仅 admin 可见；治理子面板抽为独立组件 `ExecutionGovernancePanel.tsx`；四语文案齐平。 |
| 执行方式 | 治理组件仅在治理 tab 激活且 admin 时挂载；不新增全局导航项、不改 `hashRouter`；遵循 `frontend-dev` 设计规则（单一主题色、标签在输入上方、无嵌套灰卡、稳定空状态与 loading）。 |
| 失败处理 | 非 admin 不显示治理 tab、不触发治理查询；空数据/错误时 fail-closed 稳定空状态；`npm run check:i18n` 校验四语键齐平，缺键不得上线。 |

### 配置开关（沿用现有，不新增）

本阶段不引入任何新的配置开关；下表仅列出与治理可观测性相关、且在 Phase 6 FR-16 中已存在的开关。

| 配置开关 | 级别 | 默认值 | 说明 | 溯源 |
|---|---|---|---|---|
| `execution_parser_raw_sample_enabled` | Global settings | `false` | 沿用 Phase 6 FR-16 既有开关：原始样本默认不保留；本阶段永不将原始样本或 Secret 带入 UI，仅显示分类计数与有界脱敏原因码。 | SIG-7；Phase 6 FR-16；R-4 |

## 非功能需求

- **权限**：所有新增 `/observability/execution/*` 端点 Admin-only（`require("admin")`），与 `/audit` 及凭据路由一致，不向 Reader 暴露；Worker 丢失复用 Reader 的 `GET /notifications/*`，但「执行治理」tab 仅 admin 可见且挂载；403 `insufficient_role` 为统一拒绝码。
- **租户隔离**：`execution_fencing_denials`、`runtime_event_outbox` 无 `tenant_id`，必须 JOIN `runtime_runs`（按 run_id）取 tenant/scope；`worker_heartbeats` 为部署级、无租户维度，UI 明示「部署级」；`runtime_usage_ledger`、`execution_credential_audit` 自带 `tenant_id`；跨租户访问默认拒绝。
- **Secret**：parser 原始样本与 Secret 永不进 UI，只显示分类计数与有界脱敏原因码；`public_metadata()` 与所有治理响应不含 Secret。
- **多语 i18n**：沿用 `t('中文键')` 与四语 `src/i18n/locales/{zh-CN,zh-TW,en,hi}.json`，新增文案四语齐平，`npm run check:i18n` 必须通过。
- **兼容性**：不改公开 `RunView`；cleanup 状态只经 admin 治理端点暴露；不改 SSE `id=sequence`、`event_replay_gap` 语义与 `X-Event-Retention-Floor` 响应头；不改 `hashRouter` 与全局导航；新增字段仅在治理端点内部使用。
- **性能轻量**：治理端点分页 + 有界查询；治理组件按需挂载，普通用户/其他 tab 不触发查询；不引入 Prometheus、`/metrics` 或新监控依赖，复用 `monitor_checks` / `notifications` 与结构化日志。

## 验收标准

| # | 场景 | 预期 | 溯源 |
|---|---|---|---|
| AC-1 | 分别以 admin、Reader、普通用户身份调用全部 `/observability/execution/*` 端点，并注入 tenant/scope 过滤与 Secret canary。 | 仅 admin 获得分页治理数据且过滤生效；非 admin 一律 403 `insufficient_role`；任何响应均无 Secret；错误码统一。 | FR-1；SIG-1~SIG-8；Phase 6 FR-16 |
| AC-2 | 制造一次旧 owner 写入产生 fencing 拒绝，按 time/reason/operation 过滤并分页查询，检查 JOIN `runtime_runs` 结果。 | 返回记录带 tenant/scope；过滤与分页正确；UI 表呈现；孤立记录标注部署级且无 Secret。 | FR-2；SIG-1；Phase 6 FR-16 |
| AC-3 | 停止某 Worker 心跳触发 `worker.runtime.heartbeat` / `runtime.lease_expired` 检查，再打开治理面板。 | 复用 checklist/notifications 显示丢失与恢复态；UI 明示「部署级、非租户维度」；未新建事件历史表；Reader 路由行为不变。 | FR-3；SIG-2；Phase 6 FR-16 |
| AC-4 | 分别设置 `cleanup_status='failed'`，以及 `cancel_requested_at` 非空且 `cancel_confirmed_at` 为空，调用清理失败端点。 | 两类记录均返回；公开 `RunView` 字段零变更；host/workdir 告警仍在日志；状态歧义不伪报 cancelled。 | FR-4；SIG-3；Phase 6 FR-16 |
| AC-5 | 注入 pending 滞留（最老 `available_at` 较早）与 failed `last_error` 的 Outbox 行，调用 outbox 端点。 | 返回 pending 数、滞留秒数、failed `last_error` 与 24h published 计数；UI 指标卡/表呈现；不触发发布副作用。 | FR-5；SIG-4；Phase 6 FR-16 |
| AC-6 | 将客户端游标置于 `event_retention_floor_seq` 之前触发 409 `event_replay_gap` 与 `X-Event-Retention-Floor` 响应头，再查询缺口端点。 | 409 分支写入一条有界缺口事件且查询可见；SSE `id` / `event_replay_gap` / 响应头语义不变；迁移 0072 号实施前已重验 head。 | FR-6；SIG-5；Phase 6 FR-16 |
| AC-7 | 制造被 `UNIQUE(run_id, source, source_event_id)` 拒绝的重复来源与 `supersedes_id` 修正链，调用 usage 冲突端点。 | 修正链与重复来源均可见且按 `tenant_id` 过滤；聚合语义不变、不重复计数；可选真实冲突计数不在此阶段默认启用。 | FR-7；SIG-6；Phase 6 FR-16 |
| AC-8 | 注入 malformed / unknown_schema / unknown_type / size_limit / critical_terminal 事件与含 Secret canary 的样本，查看 parser 端点与 UI。 | 仅显示分类计数/趋势与有界脱敏原因码；原始样本与 Secret 零出现；迁移 0073 号实施前已重验 head；collector 已接线。 | FR-8；SIG-7；Phase 6 FR-16 |
| AC-9 | 吊销一项凭据，调用 `GET /execution-credentials` 与 `GET /observability/execution/credential-audit?action=revoked`。 | 状态在现有路由显示 revoked；审计行可见且按 tenant 过滤；`public_metadata()` 无 Secret；越权 403。 | FR-9；SIG-8；Phase 6 FR-16 |
| AC-10 | 分别以普通用户和 admin 进入「运行与审计」页，切换两个 tab，并强制空数据与错误响应。 | 治理 tab 仅 admin 可见；组件仅在治理 tab 激活且 admin 时挂载；空状态 fail-closed；四语齐平且 `npm run check:i18n` 通过；hashRouter/全局导航零变更。 | FR-10；SIG-1~SIG-8；Phase 6 FR-16 |
