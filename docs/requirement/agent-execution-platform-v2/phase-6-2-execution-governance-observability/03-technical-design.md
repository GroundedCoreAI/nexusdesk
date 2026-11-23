# Phase 6-2 · Execution Governance Observability — Technical Design

> Status: 已批准作为后续实施的文档范围基线；未实施、未测试、未验收。本文件不宣称任何端点、迁移、组件或测试已经完成。
> Created: 2026-11-22
> Basis: Phase 6 `02-requirements.md` FR-16「可运维性」；本阶段 `01-business-goals.md`（G1~G4）与 `02-requirements.md`（FR-1~FR-10、AC-1~AC-10）；批准范围基线中的治理信号分类（SIG-1~SIG-8）与关键裁定（R-1~R-10）。
> Scope note: 本阶段只补「统一治理查询 API + 可视化 UI」。不改执行语义、不加执行分支、不开放不可信多租户、不引入 Prometheus，不预写 `06-test-report.md` / `07-acceptance-report.md`。

## 1. 架构总览

### 1.1 分层与边界

| 层 | 设计落点 | 约束 |
|---|---|---|
| 后端治理查询层 | `backend/src/agent_platform/applications/customer_service/platform_routes.py` 内新增 `/api/v1/observability/execution/*` 只读端点；统一依赖 `require("admin")`、`resolve_scope()` + `scope_predicate()`、统一分页与错误码 | 与 `/audit`、凭据路由同级；全部 Admin-only，不向 Reader 暴露（R-1） |
| 数据源适配 | 各 SIG 的既有表/检查直接查询；无 `tenant_id` 的表 JOIN `runtime_runs`（按 run_id）取 tenant/scope（R-2） | 只读；不改原写入方语义；不复制出第二份数据源 |
| 计划新增持久化 | 迁移 `0072_execution_replay_gap_events`（SIG-5）、`0073_execution_parser_diagnostics`（SIG-7），均为 planning 值 | 实施前必须动态重验单一 head（R-5）；禁止修改已应用历史迁移 |
| 前端可视化层 | `frontend/src/features/observability/ObservabilityPage.tsx` 顶部加 antd `Tabs`：「运行总览」保留现有全部 Panel，「执行治理」为新增 tab；子面板抽为 `ExecutionGovernancePanel.tsx` | 仅 admin 可见且仅 admin 时挂载；不新增全局导航、不改 `hashRouter`（R-7） |
| 复用基础 | `useResource<T>(path, refreshMs)`、`Panel`、`Table`、`Tag`、`Badge`、`Alert`、`useAccess`、`useAction`、`Trace`、`time`、`serverPagination` / `clientPagination` | 遵循 `frontend-dev` 设计规则：单一主题色、标签在输入上方、无嵌套灰卡、稳定空状态与 loading（R-9） |

### 1.2 现状事实与设计约束

以下事实来自代码与批准基线，是本设计不可推翻的输入：

| 区域 | 已核实事实 | 设计后果 |
|---|---|---|
| 公开聚合 | `platform_routes.py:1541` 的 `GET /observability/summary`（Reader）仅返回 `total, completed, failed, cancelled, running, queued, average_seconds, p95_seconds, tokens, ttfc{p50_ms,p95_ms,samples}`，不含任何治理信号 | 治理端点独立新增，不改写 summary 语义 |
| 既有 observability | `/observability/gateways`、`/observability/memory`、`/observability/memory/alerts`、`/observability/runs`、`/observability/runs/{rid}/trace` 为 Reader；`/audit` 为 Admin，读 `audit_records`，不含 fencing/credential 治理审计 | 治理接入复用同页但新增 admin 前缀；不把治理数据塞进 `/audit` |
| 凭据路由 | `execution_credential_routes.py` 五个路由全部 `require("admin")`；`public_metadata()` 字段为 `credential_ref, tenant_id, name, credential_type, key_version, version, status, allowed_engines, allowed_workspaces, created_at, updated_at, rotated_at, revoked_at`，永不返回 Secret | 吊销状态零后端工作直接复用；审计仅新增只读端点 |
| 权限原语 | `Reader = Depends(principal)`（任意登录）；`Operator = admin\|operator`；`Admin = require("admin")`；403 `insufficient_role` | 治理端点统一用 `Admin`；越权一律 403，不降级为 Reader |
| 租户缺口 | `execution_fencing_denials`、`runtime_event_outbox`、`worker_heartbeats` 无 `tenant_id`；`runtime_usage_ledger`、`execution_credential_audit` 自带 `tenant_id` | 前者 JOIN `runtime_runs` 或明确标注部署级；后者直接按 `tenant_id` 过滤 |
| 监控依赖 | 无 Prometheus、无 `/metrics`；Phase 7 文档明确排除 Prometheus | 复用 `monitor_checks` / `notifications` 与结构化日志（R-8） |
| 前端现状 | `observability` = 「运行与审计」，侧边栏「质量运营」组，图标 `LineChartOutlined`；页面为纵向堆叠 Panel，不是 tab 结构；`hashRouter.ts` 的 `pages` 含 `observability`，无 `/observability/:sub` 子路由 | 在页内加 Tabs，零改路由（R-7） |

### 1.3 治理信号分类总览

分类定义：A = 已有持久化且已有可用 API，前端直接接入；B = 已有持久化但无查询 API，需新增端点；C = 缺少持久化或接线，需新增迁移/写入点；D = 敏感内容，不进 UI。

| ID | 信号 | 分类 | 本阶段最小工作 |
|---|---|---|---|
| SIG-1 | Fencing 拒绝 | B | 新增 admin fencing-denials 端点 + UI 表 |
| SIG-2 | Worker 丢失 | A（带 caveat） | 复用 checklist/notifications 面板，明示部署级 |
| SIG-3 | 清理失败 | B | 新增 admin cleanup-failures 端点 + UI 表，不改公开 `RunView` |
| SIG-4 | Outbox lag | B | 新增 admin outbox 端点 + UI 指标卡/表 |
| SIG-5 | SSE 重放缺口 | C | 迁移 0072 + 409 分支有界写入 + admin 端点 + UI |
| SIG-6 | usage 冲突 | B（含 C 组件） | 新增 admin usage-conflicts 端点 + UI 修正链；真实冲突计数审计写为可选 |
| SIG-7 | parser 原生事件诊断 | C；原始样本为 D | 迁移 0073 + collector/sink 接线 + admin 端点 + UI 分类计数 |
| SIG-8 | 凭据吊销 | A（状态）+ B（审计） | 状态复用 `GET /execution-credentials`；新增 admin credential-audit 端点 + UI |

## 2. 治理信号：数据源、SQL 口径与 API 契约

所有端点共性（FR-1）：路径前缀 `/api/v1/observability/execution/*`；方法均为 `GET`；权限 `require("admin")`，非 admin / 越权 403 `insufficient_role`；过滤或分页非法 400；租户/scope 过滤沿用 `resolve_scope()` + `scope_predicate()`，凭据端点仅按 `tenant_id` 不做 business_scope；统一分页参数 `page`（默认 1）与 `page_size`（默认 20，上限 100）；查询异常返回统一错误码，不降级为 Reader 可见，空结果返回稳定空状态。下表在各 SIG 中只列差异项。

### 2.1 SIG-1 Fencing 拒绝（B）

数据源：`execution_fencing_denials`（迁移 `0070_execution_fencing_event_outbox.py`），字段 `run_id, operation, reason, stale_owner, stale_lease_epoch, current_owner, current_lease_epoch, created_at`；写入方为 `core_platform/agent_execution/reliability/ownership.py` 的 `FencingDenialRecorder`（回滚后独立事务）。当前无任何路由读取该表。

SQL 聚合口径：按 `created_at DESC` 排序的明细查询，`JOIN runtime_runs r ON d.run_id = r.id` 带出 `tenant_id` 与 business/workspace scope；过滤 `created_at` 时间窗、`reason`、`operation`；不聚合、不改写写入内容。

API 契约：

| 项 | 值 |
|---|---|
| 路径 / 方法 | `GET /api/v1/observability/execution/fencing-denials` |
| query 参数 | `from`, `to`, `reason`, `operation`, `tenant_id`, `business_scope`, `workspace`, `page`, `page_size` |
| 返回结构 | `{ items: [{ run_id, operation, reason, stale_owner, stale_lease_epoch, current_owner, current_lease_epoch, created_at, tenant_id, scope }], total, page, page_size }` |
| 错误码 | 403 `insufficient_role`；400 无效过滤/分页 |
| 租户/scope | 表无 `tenant_id`，强制 JOIN `runtime_runs`；孤立 run_id 标注为部署级 |
| 分页 | server-side，统一 `page` / `page_size` |

### 2.2 SIG-2 Worker 丢失（A，带 caveat）

数据源：`worker_heartbeats`（迁移 `0060_monitoring`：`worker_id/host/started_at/beat_at/detail` JSONB）+ monitoring check `worker.runtime.heartbeat` → `monitor_checks` / `notifications`；另有 `runtime.lease_expired` 检查。已有 `GET /notifications/checklist`、`GET /notifications`（Reader）。

SQL 聚合口径：不新增查询 SQL；消费现有 checklist/notifications 结构，提取 heartbeat 与 lease_expired 项的当前状态与 `beat_at`；按 `worker_id` 展示，不构造历史时间线。

API 契约：不新增治理端点，复用现有 reader 路由；仅在 admin 治理 tab 内呈现。

| 项 | 值 |
|---|---|
| 路径 / 方法 | 复用 `GET /notifications/checklist`、`GET /notifications`（均为 Reader）；治理 tab 仍 Admin-only |
| query 参数 | 沿用现有路由参数 |
| 返回结构 | 现有 checklist/notifications 结构；UI 明示「部署级、非租户维度」 |
| 错误码 | 沿用现有路由；数据缺失时 UI 稳定空状态 |
| 租户/scope | 部署级，无租户维度（R-2） |
| 分页 | 沿用现有路由 |

### 2.3 SIG-3 清理失败与取消未确认（B）

数据源：`runtime_runs` 的 `cleanup_status CHECK IN(not_started,in_progress,completed,failed)`、`cleanup_updated_at`、`cancel_requested_at`、`cancel_confirmed_at`（0070）。host/workdir 清理失败告警只进 `LoggingAlertSink`（日志，不落表）；`RunView`（`schemas.py:18-27`）不含这些字段。

SQL 聚合口径：两类并集——(a) `cleanup_status = 'failed'`；(b) `cancel_requested_at IS NOT NULL AND cancel_confirmed_at IS NULL`。按 `cleanup_updated_at DESC` 排序，`runtime_runs` 自带 tenant/scope，直接过滤。

API 契约：

| 项 | 值 |
|---|---|
| 路径 / 方法 | `GET /api/v1/observability/execution/cleanup-failures` |
| query 参数 | `category=failed\|unconfirmed_cancel`（可选，缺省两类都返回）, `from`, `to`, `tenant_id`, `business_scope`, `workspace`, `page`, `page_size` |
| 返回结构 | `{ items: [{ run_id, category, cleanup_status, cleanup_updated_at, cancel_requested_at, cancel_confirmed_at, tenant_id, scope }], total, page, page_size }` |
| 错误码 | 403 `insufficient_role`；400 无效过滤/分页 |
| 租户/scope | `runtime_runs` 自带 tenant/scope，直接过滤；不改公开 `RunView`（R-3） |
| 分页 | server-side，统一 `page` / `page_size` |

### 2.4 SIG-4 Outbox lag（B）

数据源：`runtime_event_outbox`（0070）：`run_id, seq, event_id UNIQUE, status(pending/published), attempts, available_at, created_at, published_at, last_error`；`events/outbox.py` 有 `pending_count` 与重扫；`runtime_composition.ExecutionRuntimeSubsystem.operational_stats()` 返回 `outbox_pending`，当前仅测试引用、未挂路由。

SQL 聚合口径：pending 数 = `COUNT(*) WHERE status='pending'`；滞留秒数 = `EXTRACT(EPOCH FROM (now() - MIN(available_at))) WHERE status='pending'`；failed 明细 = `status='pending' AND last_error IS NOT NULL` 的 `last_error`（有界脱敏字符串，不含事件 payload）；24h published 计数 = `COUNT(*) WHERE status='published' AND published_at >= now() - interval '24 hours'`。该表无 `tenant_id`，JOIN `runtime_runs`（按 run_id）取 tenant/scope。

API 契约：

| 项 | 值 |
|---|---|
| 路径 / 方法 | `GET /api/v1/observability/execution/outbox` |
| query 参数 | `tenant_id`, `business_scope`, `workspace`, `page`, `page_size`（明细表分页） |
| 返回结构 | `{ pending_count, oldest_available_at, stall_seconds, last_errors: [{ run_id, seq, attempts, available_at, last_error }], published_24h, total, page, page_size }` |
| 错误码 | 403 `insufficient_role`；400 无效分页/过滤 |
| 租户/scope | JOIN `runtime_runs`；复用 `operational_stats().outbox_pending` 做指标卡交叉校验（R-1/R-2/R-8） |
| 分页 | 指标为全局/按 scope 聚合，`last_errors` 明细 server-side 分页 |

### 2.5 SIG-5 SSE 重放缺口（C）

数据源：目前只有 `runtime_runs.event_retention_floor_seq`（0070，随保留清理原子推进）+ SSE 路由 409 `event_replay_gap` 与响应头 `X-Event-Retention-Floor`（`runtime_routes.py:105-112`）；无任何缺口发生记录或查询 API。计划新增表 `execution_replay_gap_events`（迁移 `0072_execution_replay_gap_events`，planning）。

SQL 聚合口径：按 `created_at DESC` 的明细查询，按 run_id / tenant / 时间窗过滤；不聚合原始 SSE 内容。

API 契约：

| 项 | 值 |
|---|---|
| 路径 / 方法 | `GET /api/v1/observability/execution/replay-gaps` |
| query 参数 | `from`, `to`, `run_id`, `tenant_id`, `business_scope`, `workspace`, `page`, `page_size` |
| 返回结构 | `{ items: [{ id, run_id, requested_cursor_seq, retention_floor_seq, reason_code, created_at, tenant_id, scope }], total, page, page_size }` |
| 错误码 | 403 `insufficient_role`；400 无效过滤/分页；409 保留期缺口说明沿用 SSE 路由，不在本查询端点产生 |
| 租户/scope | 计划表写入时从已授权 run 复制 `tenant_id`，按 `tenant_id` 过滤；JOIN `runtime_runs` 取 scope |
| 分页 | server-side，统一 `page` / `page_size` |

### 2.6 SIG-6 usage 冲突与修正链（B，含 C 组件）

数据源：`runtime_usage_ledger`（0070）：`run_id, tenant_id, lease_epoch, source, source_event_id, usage, cost, is_estimate, supersedes_id`（自引用修正链），`UNIQUE(run_id, source, source_event_id)`；重建逻辑为 `events/usage.py::aggregate_effective_usage()`。当前无显式冲突事件、无 API。

SQL 聚合口径：修正链 = 以 `supersedes_id` 为自引用递归展开 `(run_id, source, source_event_id, id, supersedes_id, usage, cost, is_estimate)`，仅有效叶子进入聚合；重复来源 = 被唯一约束拒绝的 `(run_id, source, source_event_id)` 尝试记录（如需计数，在唯一冲突/supersede 处补一条审计写，C 组件，可选）；不改 `aggregate_effective_usage()` 语义、不重复计数。表自带 `tenant_id`，直接过滤。

API 契约：

| 项 | 值 |
|---|---|
| 路径 / 方法 | `GET /api/v1/observability/execution/usage-conflicts` |
| query 参数 | `from`, `to`, `run_id`, `tenant_id`, `business_scope`, `workspace`, `kind=chain\|duplicate`, `page`, `page_size` |
| 返回结构 | `{ items: [{ run_id, tenant_id, source, source_event_id, supersedes_id, usage, cost, is_estimate, kind }], total, page, page_size }` |
| 错误码 | 403 `insufficient_role`；400 无效过滤/分页 |
| 租户/scope | 表自带 `tenant_id`，直接过滤；链不完整时按已知部分展示并标注 |
| 分页 | server-side，统一 `page` / `page_size` |

### 2.7 SIG-7 parser 原生事件诊断（C；原始样本为 D）

数据源：无表。`core_platform/agent_execution/events/diagnostics.py` 的 `ParserDiagnosticCollector` 只有内存 `self._counts` / `self._suppressed` 与可选 sink；`execution_parser_raw_sample_enabled=false`；代码内未发现生产实例化，实际未接线。类别：`malformed/unknown_schema/unknown_type/size_limit/critical_terminal`。计划新增表 `execution_parser_diagnostics`（迁移 `0073_execution_parser_diagnostics`，planning）。

SQL 聚合口径：按时间桶 + `category` + 有界脱敏 `reason_code` 汇总 `COUNT(*)`，形成分类计数与趋势；原始样本与 Secret 永不落表、永不进 UI。

API 契约：

| 项 | 值 |
|---|---|
| 路径 / 方法 | `GET /api/v1/observability/execution/parser-diagnostics` |
| query 参数 | `from`, `to`, `category`, `tenant_id`, `business_scope`, `workspace`, `bucket`, `page`, `page_size` |
| 返回结构 | `{ items: [{ bucket_start, category, reason_code, count, tenant_id, run_id }], total, page, page_size }`；只含分类计数与有界脱敏原因码 |
| 错误码 | 403 `insufficient_role`；400 无效过滤/分页 |
| 租户/scope | 计划表写入时从已授权上下文复制 `tenant_id`；collector 未接线或数据缺失时 UI 空状态（R-4/R-5） |
| 分页 | server-side，统一 `page` / `page_size` |

### 2.8 SIG-8 凭据吊销与审计（A 状态 + B 审计）

数据源：`execution_credentials`（`status active/superseded/revoked`, `version`, `rotated_at`, `revoked_at`）、`execution_credential_grants`、`execution_credential_audit`（`action created/rotated/revoked/grant_issued/grant_denied/grant_used`, `outcome`, `reason_code`, `actor`），均 0071。已有 `GET /execution-credentials` 等 5 个 admin 路由，但无路由读取 `execution_credential_audit`。

SQL 聚合口径：当前吊销状态直接复用 `GET /execution-credentials`（零后端工作）；审计为按 `action`, `tenant_id`, 时间窗过滤的明细查询，按时间倒序。

API 契约：

| 项 | 值 |
|---|---|
| 路径 / 方法 | 状态复用 `GET /api/v1/execution-credentials`；审计新增 `GET /api/v1/observability/execution/credential-audit` |
| query 参数 | 审计：`action=revoked`（默认重点）、`from`, `to`, `tenant_id`, `page`, `page_size`；仅按 tenant，不做 business_scope |
| 返回结构 | `{ items: [{ id, credential_ref, action, outcome, reason_code, actor, created_at, tenant_id }], total, page, page_size }`；`public_metadata()` 字段不含 Secret |
| 错误码 | 403 `insufficient_role`；400 无效过滤/分页；无匹配返回空状态 |
| 租户/scope | 审计表自带 `tenant_id`，直接过滤；两条路由均 `require("admin")` |
| 分页 | server-side，统一 `page` / `page_size` |

## 3. 计划新增迁移（planned，实施前重验 head）

下表字段均依据批准基线给出的事实推导，属于 **计划值**；任何字段在实现前须与代码现实复核。迁移号 `0072` / `0073` 为 planning 值，实施前必须动态重验单一 head；若 head 变化，按 R-n 记录并同步修订双语文档，禁止修改已应用历史迁移（R-5）。

### 3.1 `0072_execution_replay_gap_events`（SIG-5，planned）

| 字段 | 类型/约束 | 依据与用途 |
|---|---|---|
| `id` | UUID PK | 缺口事件身份 |
| `run_id` | UUID FK → `runtime_runs(id)` | 409 分支已授权 run；用于 JOIN 取 tenant/scope |
| `tenant_id` | TEXT + index | 写入时从已授权 run 复制，便于有界租户过滤 |
| `requested_cursor_seq` | INTEGER | 触发 409 的客户端游标（早于 floor） |
| `retention_floor_seq` | INTEGER | 当时的 `event_retention_floor_seq`，与 `X-Event-Retention-Floor` 一致 |
| `reason_code` | TEXT | 有界稳定原因码（如 `cursor_below_floor`），不含 payload 或 Secret |
| `created_at` | TIMESTAMPTZ | 缺口发生时间，用于排序与时间窗过滤 |

不存储任何 SSE 事件 payload、原始样本或 Secret；409 写入失败不阻断正常 409 响应。

### 3.2 `0073_execution_parser_diagnostics`（SIG-7，planned）

| 字段 | 类型/约束 | 依据与用途 |
|---|---|---|
| `id` | UUID PK | 诊断桶身份 |
| `tenant_id` | TEXT NULL + index | 写入时从已授权上下文复制；无上下文时为空（部署级） |
| `run_id` | UUID NULL | 与 run 的关联；与 `ParserDiagnosticCollector` 的 run/protocol/adapter 关联口径对齐 |
| `category` | TEXT CHECK IN (`malformed`, `unknown_schema`, `unknown_type`, `size_limit`, `critical_terminal`) | 基线规定的五类 |
| `reason_code` | TEXT NULL | 有界脱敏原因码；**原始样本与 Secret 永不落表** |
| `count` | INTEGER NOT NULL | 桶内分类计数 |
| `bucket_start` | TIMESTAMPTZ | 趋势时间桶起点 |

沿用现有 `execution_parser_raw_sample_enabled=false`，本阶段不新增开关。

## 4. 写入点与接线设计

### 4.1 SSE 409 缺口写入点（SIG-5）

```text
SSE 客户端游标 < runtime_runs.event_retention_floor_seq
→ runtime_routes.py 返回 409 event_replay_gap + X-Event-Retention-Floor（约 105-112）
→ 在同一请求内以 best-effort 独立事务写一条 execution_replay_gap_events
→ 记录 run_id/tenant_id/requested_cursor_seq/retention_floor_seq/reason_code/created_at
→ 写入失败仅记日志，不阻断 409 响应
→ 公开 SSE 语义（id=sequence、event_replay_gap、响应头）零变更
```

写入发生在只读 SSE 路径，不能让审计写入改变 SSE 的状态码、头或事件序列；其失败必须被吞掉并只留日志。

### 4.2 parser collector 接线点（SIG-7）

```text
events/diagnostics.py 的 ParserDiagnosticCollector（内存 _counts/_suppressed + 可选 sink）
→ 在 runtime_composition.ExecutionRuntimeSubsystem 构造时实例化 collector 与持久化 sink
→ sink 按时间桶把分类计数写入 execution_parser_diagnostics（0073）
→ reason_code 有界脱敏；原始样本与 Secret 即使被临时采集也不进入 sink/UI
→ execution_parser_raw_sample_enabled 沿用 false，不新增开关
```

当前生产代码未发现 collector 实例化，接线属于本阶段最小工作之一；未接线时 UI 显示稳定空状态，不伪造数据。

## 5. 前端设计

### 5.1 页面结构

`frontend/src/features/observability/ObservabilityPage.tsx` 由纵向堆叠 Panel 改为顶部 antd `Tabs`：

| Tab | 可见性 | 内容 |
|---|---|---|
| 「运行总览」 | 所有可见「运行与审计」页的用户 | 保留现有全部 Panel（指标卡、记忆观测+治理操作、记忆告警、扩展运行状态、事件投递运维、最近运行+运行详情 Trace、近 24 小时网关计量、操作审计），零删改 |
| 「执行治理」 | 仅 `useAccess` 的 `admin` 布尔为真时可见 | 挂载独立组件 `frontend/src/features/observability/ExecutionGovernancePanel.tsx`（新增） |

治理组件仅在「执行治理」tab 激活且 admin 时挂载，避免普通用户或其他 tab 触发治理查询；不新增全局导航项、不改 `hashRouter.ts`（R-7）。

### 5.2 组件与数据流

`ExecutionGovernancePanel.tsx` 以 SIG 对应子面板组织：Fencing 拒绝表、Worker 状态（部署级标注）、清理失败表、Outbox 指标卡+失败表、SSE 缺口表、usage 修正链表、parser 分类计数/趋势、凭据吊销状态（复用现有路由）+ 审计表。各子面板复用：

| 复用点 | 用途 |
|---|---|
| `useResource<T>(path, refreshMs)` | 调用 `shared/api/client.ts` 加载治理端点；空数据/错误 fail-closed |
| `Panel` / `Table` / `Tag` / `Badge` / `Alert` | 统一卡片、表格、状态标记、告警 |
| `serverPagination` / `clientPagination` | 治理表沿用 ObservabilityPage 既有分页惯例 |
| `Trace` | 运行详情复用现有 Trace 视图 |
| `time` | 时间窗与时间戳格式化 |
| `useAccess` / `useAction` | admin 门控与操作态 |

### 5.3 admin 门控与 fail-closed

非 admin：不渲染治理 tab、不挂载治理组件、不发起任何 `/observability/execution/*` 请求。空数据或错误响应：各子面板显示稳定空状态，不伪造恢复态、不伪造投递成功、不伪造冲突计数。所有新增文案使用 `t('中文键')`，并在 `src/i18n/locales/{zh-CN,zh-TW,en,hi}.json` 四语齐平，`npm run check:i18n` 必须通过，缺键不得上线。遵循 `frontend-dev` 设计规则：单一主题色、标签在输入上方、无嵌套灰卡、稳定空状态与 loading（R-9）。

## 6. 安全设计

| 维度 | 措施 | 裁定 |
|---|---|---|
| 权限 | 所有新增 `/observability/execution/*` 端点 `require("admin")`；与 `/audit` 与凭据路由一致；越权 403 `insufficient_role`；Worker 丢失复用 Reader `GET /notifications/*` 但治理 tab 仅 admin | R-1 |
| 租户 JOIN | `execution_fencing_denials`、`runtime_event_outbox` JOIN `runtime_runs` 取 tenant/scope；`worker_heartbeats` 部署级并 UI 明示；`runtime_usage_ledger`、`execution_credential_audit` 按自带 `tenant_id` 过滤；跨租户默认拒绝 | R-2 |
| Secret 零泄露 | `public_metadata()` 与所有治理响应不含 Secret；parser 只显示分类计数与有界脱敏原因码；Secret canary 测试必须零出现 | R-4 |
| 原始样本 | 原始样本永不进 UI；`execution_parser_raw_sample_enabled=false` 沿用；0073 表不存原始样本 | R-4 |
| 不开放高风险 | 不开放不可信多租户/生产 Codex 路由；本阶段不声称高风险能力启用或生产放行 | R-10 |
| 无新监控依赖 | 不引入 Prometheus / `/metrics`；复用 `monitor_checks` / `notifications` 与结构化日志 | R-8 |

## 7. 兼容与回退

| 兼容面 | 设计保证 |
|---|---|
| 公开 `RunView` | 零变更；cleanup 状态只经 admin 治理端点暴露（R-3） |
| SSE | `id=sequence`、`event_replay_gap` 语义、`X-Event-Retention-Floor` 响应头零变更；409 写入为 best-effort 旁路 |
| 公开 summary | `GET /observability/summary` 字段与语义零变更 |
| 路由/导航 | `hashRouter.ts` 与全局导航零变更；仅页内 Tabs |
| 依赖 | 无 Prometheus、无新监控依赖 |
| 迁移 | 不修改已应用历史迁移；0072/0073 为规划新增，实施前重验 head |

回退策略：撤销治理路由注册并卸载治理 tab 组件即可停用全部治理查询能力，不影响执行路径；0072/0073 若已应用，回退仅停止写入/查询，不做数据删除式降级。任何 Secret 泄露、跨租户治理数据暴露、SSE 语义变化或公开 `RunView` 变更都立即停止并回滚。

## 8. 配置开关

本阶段不引入任何新配置开关。下表仅列出与治理可观测性相关且已在 Phase 6 FR-16 存在的开关。

| 配置开关 | 默认值 | 说明 | 溯源 |
|---|---|---|---|
| `execution_parser_raw_sample_enabled` | `false` | 沿用 Phase 6 FR-16 既有开关；原始样本默认不保留；本阶段永不将原始样本或 Secret 带入 UI，仅显示分类计数与有界脱敏原因码 | SIG-7；Phase 6 FR-16；R-4 |
