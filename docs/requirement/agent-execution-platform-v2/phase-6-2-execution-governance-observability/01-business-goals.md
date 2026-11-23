# Phase 6-2 · Execution Governance Observability — Business Goals

> Status: 已批准作为后续实施的文档范围基线；未实施、未测试、未验收
> Created: 2026-11-22
> Basis: Phase 6 `02-requirements.md` FR-16「可运维性」；本阶段 `01-business-goals.md`；治理信号分类与冻结编号以批准的范围基线为准（SIG-1~SIG-8、G1~G4、US-1~US-4、FR-1~FR-10、AC-1~AC-10）。
> Scope note: 本阶段仅补「统一治理查询 API + 可视化 UI」；不改执行语义、不加执行分支、不开放不可信多租户、不宣称生产放行。

## 背景

Phase 6 FR-16「可运维性」要求提供 Fencing 拒绝、Worker 丢失、清理失败、Outbox lag、重放缺口、usage 冲突、parser 错误和吊销的指标/告警/审计。Phase 6 已把这些治理事实持久化到表、日志、monitor 检查与内存计数中：

- 表：`execution_fencing_denials`、`runtime_event_outbox`、`runtime_usage_ledger`、`execution_credentials` / `execution_credential_grants` / `execution_credential_audit`、`worker_heartbeats`，以及 `runtime_runs` 上的 `cleanup_status` / `cleanup_updated_at` / `cancel_requested_at` / `cancel_confirmed_at` / `event_retention_floor_seq`。
- monitor 检查：`worker.runtime.heartbeat`、`runtime.lease_expired` → `monitor_checks` / `notifications`。
- 内存计数：`ParserDiagnosticCollector` 的 `self._counts` / `self._suppressed`（尚未在组合根实例化接线）。

但 Phase 6 没有提供统一治理查询 API，也没有治理 UI。`GET /api/v1/observability/summary`（Reader）不含任何治理信号；`GET /api/v1/audit`（Admin）读取 `audit_records`，不含 fencing / credential 治理审计。8 类治理信号的现状评估结论为：A 类（已有持久化且已有可用 API）仅 SIG-2、SIG-8 的状态部分；B 类（已有持久化但无查询 API）为 SIG-1、SIG-3、SIG-4、SIG-6、SIG-8 审计部分；C 类（缺持久化或接线）为 SIG-5、SIG-7；D 类（敏感内容，不进 UI）为 parser 原始样本与 Secret。

本阶段定位为「只补查询 API + 可视化 UI」：不重写上述事实，不加执行分支，不引入新监控依赖。

## 问题陈述

### 问题 1：治理事实已持久化，但 SRE / 管理员没有统一查询入口

除 SIG-2 可复用 Reader 的 `GET /notifications/checklist`、`GET /notifications`、SIG-8 状态可复用 `GET /execution-credentials` 外，其余信号均无路由读取：`execution_fencing_denials`、`runtime_event_outbox`、`runtime_usage_ledger`、`execution_credential_audit`、`runtime_runs.cleanup_status` 都没有对应查询端点；`operational_stats().outbox_pending` 仅测试引用、未挂路由。SRE 与管理员只能直接查库或翻日志，无法在一个统一入口按 tenant/scope、时间、原因、操作等维度筛选。

### 问题 2：治理信号没有 UI，fencing 拒绝 / outbox lag / 清理失败等不可见

现有全局页「运行与审计」（`observability`）是纵向堆叠 Panel 结构，没有治理 tab，也没有任何治理信号面板。SRE / 管理员无法在界面上看到 fencing 拒绝、outbox 滞留、清理失败与取消未确认、SSE 重放缺口、usage 修正链、credential 吊销审计和 parser 诊断，只能依赖告警事后响应，无法主动巡检。

### 问题 3：可见性扩张必须同时守住隔离、兼容与脱敏边界

可见性不是简单地把数据读出来：`execution_fencing_denials`、`runtime_event_outbox`、`worker_heartbeats` 没有 `tenant_id` 列，必须 JOIN `runtime_runs`（按 run_id）取 tenant/scope，或仅 Admin 且明确标注部署级；公开 `RunView` 不含 cleanup 字段，不能为了 UI 改公开契约；parser 原始样本与 Secret 属于 D 类敏感内容，永不进 UI；SIG-5、SIG-7 还缺持久化与接线，新迁移号 0072 / 0073 为 planning 值，实施前必须重验单一 head。

## 业务目标

| 目标 | 说明 |
|---|---|
| G1 治理信号可见 | 8 类治理信号经统一 admin 查询 API 与「执行治理」tab 集中呈现；SRE / 管理员可主动巡检 fencing 拒绝、outbox lag、清理失败、重放缺口、usage 冲突、parser 诊断与凭据吊销审计。 |
| G2 安全与 Secret 不外泄 | 所有新增 `/observability/execution/*` 端点 Admin-only；无 Secret、无 parser 原始样本进入任何响应或 UI；租户/scope 隔离与非 admin 拒绝均 fail-closed。 |
| G3 兼容、不改执行语义 | 不改公开 `RunView`、SSE 语义、`X-Event-Retention-Floor` 响应头、hashRouter 与全局导航；不加执行分支、不改清理与聚合逻辑，不引入 Prometheus 或新监控依赖。 |
| G4 可验证可追溯 | 每个 FR 有对应 AC 与 SIG 溯源；治理数据能按 tenant/scope 与 run_id 追溯到运行，空状态与错误统一且可验证；迁移 0072 / 0073 实施前重验 head，双语文档同步。 |

## 成功指标

| 指标 | 基线（现状） | 目标 |
|---|---|---|
| 可见性覆盖率 | 8 类信号已部分持久化，但有统一查询 API 与 UI 的为 0 类（SIG-2 仅复用 Reader checklist/notifications，SIG-8 状态仅复用 `GET /execution-credentials`）。 | 8 类信号均有 admin 可查询端点并在「执行治理」tab 可见（SIG-2 复用 Reader 路由、SIG-8 状态复用现有路由）；治理数据可见率 100%，空状态 fail-closed。 |
| 权限合规 | 新增治理端点 0 个，治理数据仅 admin 路由可读（`/audit`、凭据路由）。 | 所有 `/observability/execution/*` 端点 Admin-only；非 admin 一律 403 `insufficient_role`；普通用户与其他 tab 不触发治理查询。 |
| Secret 零泄露 | 现有公开视图与 `public_metadata()` 不含 Secret。 | 治理响应与 UI 中 Secret / parser 原始样本泄露为 0；仅显示分类计数与有界脱敏原因码。 |
| 兼容性 | 公开 `RunView`、SSE、hashRouter 与四语 i18n 既有键保持不变。 | 公开 `RunView` 字段、`event_replay_gap` / `X-Event-Retention-Floor` 语义、hashRouter 与全局导航均零变更；`npm run check:i18n` 四语键齐平。 |
| 性能轻量 | 治理查询未实现；无 `/metrics` 与 Prometheus。 | 治理端点分页 + 有界查询，治理 tab 按需挂载；不引入 Prometheus / 新监控依赖，复用 `monitor_checks` / `notifications` 与结构化日志。 |

## 范围

**包含**：

- 8 类治理信号的统一 admin 查询 API（`/api/v1/observability/execution/*`）与权限、tenant/scope 过滤（无 tenant_id 表 JOIN `runtime_runs`）。
- 前端「运行与审计」页顶部 antd `Tabs`：「运行总览」保留现有全部 Panel，「执行治理」新增且仅 admin 可见；治理子面板抽为独立组件 `ExecutionGovernancePanel.tsx`，按需挂载。
- 新迁移 `0072_execution_replay_gap_events`（SIG-5）与 `0073_execution_parser_diagnostics`（SIG-7），均为 planning 值，实施前重验单一 head；以及 409 分支有界写入点与 composition 中 parser collector/sink 接线。
- 脱敏、稳定空状态 fail-closed、四语 i18n 文案与 `npm run check:i18n`；复用 `monitor_checks` / `notifications` 与结构化日志。

**不包含**（后续阶段 / 明确不做）：

- 不开放不可信多租户 / 生产 Codex 路由；不声称高风险能力启用或生产放行（R-10）。
- 不引入 Prometheus、`/metrics` 或任何新监控依赖（R-8；Phase 7 文档亦明确排除）。
- 不改执行语义、不加执行分支；不改公开 `RunView`；不改 SSE 语义与响应头；不改 hashRouter 与全局导航（R-3、R-7）。
- 不建 Worker 丢失事件历史时间线表（如需另立后续需求）；不为 UI 便利伪报真实退出/取消确认。
- parser 原始样本与 Secret 永不进 UI（R-4）；不登记 issue / PR 号；不预写 `06-test-report.md` / `07-acceptance-report.md`（R-6）。

## 与其他阶段的关系

- **Phase 6（上游）**：提供治理事实的持久化与 FR-16「可运维性」要求。本阶段不重写这些事实，只在其上补统一查询 API 与 UI。
- **Phase 7**：明确排除 Prometheus。本阶段同样不引入 Prometheus 或新监控依赖，仅复用 `monitor_checks` / `notifications` 与结构化日志。
- **后续需求**：Worker 丢失历史时间线、真实 usage 冲突计数（可选 C 组件）等可另立需求；本阶段交付不声称生产放行。
- **06 / 07 报告**：按项目惯例，仅在实际测试 / 验收后创建，本阶段不预写。

## 风险与约束

- **迁移号为 planning 值**：0072 / 0073 实施前必须动态重验单一 head，若变化则同步修订双语文档；禁止修改已应用的历史迁移（R-5）。
- **无 tenant_id 的表**：`execution_fencing_denials`、`runtime_event_outbox` 必须 JOIN `runtime_runs`；`worker_heartbeats` 为部署级、无租户维度，UI 明示「部署级」（R-2）。
- **公开契约不变**：不改公开 `RunView`；cleanup 状态只经 admin 治理端点暴露（R-3）。
- **敏感内容**：parser 原始样本 / Secret 永不进 UI，只显示分类计数与有界脱敏原因码（R-4）。
- **前端设计规则**：遵循 `frontend-dev` 规则——单一主题色、标签在输入上方、无嵌套灰卡、稳定空状态与 loading（R-9）。
