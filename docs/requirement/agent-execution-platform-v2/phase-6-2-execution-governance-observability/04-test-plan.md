# Phase 6-2 · Execution Governance Observability — Test Plan

> Status: 已批准作为后续测试的文档范围基线；未实施、未测试、未验收。本文只描述「将如何测」，不包含任何已执行、已通过或已验收的结论。
> Created: 2026-11-22
> Basis: Phase 6 `02-requirements.md` FR-16「可运维性」；本阶段 `02-requirements.md`（FR-1~FR-10、AC-1~AC-10）、`03-technical-design.md`、`08-implementation-breakdown.md`（T-1~T-14、R-1~R-10、UT-1~UT-14、IT-1~IT-8、FE-1~FE-10、CM-1~CM-6）；批准范围基线中冻结的 SIG-1~SIG-8 分类。
> Scope note: 测试对象仅为「统一治理查询 API + 可视化 UI」。不测试执行语义变更，不调用真实不可信执行环境，不引入 Prometheus 或新监控依赖。所有编号、表名、字段、路由与迁移号均以基线为准；`0072` / `0073` 为 planning 值，实施前须重验单一 head。

## 1. 测试策略

1. **确定性优先**：所有断言基于可控时钟、固定 canary 与确定性 fixture；不用真实时间 sleep 或真实网络结果作为判定依据。分页、滞留秒数、24h 计数等口径通过可控时间戳与固定行数构造。
2. **PG 分片隔离**：集成测试按分片运行，每片使用独立的 disposable database / schema，加载真实迁移产物与真实表数据；每片可独立重放，禁止跨片共享可变状态。至少两个租户与多个 run 覆盖 JOIN 与 scope 过滤。
3. **Playwright mock harness**：前端用例通过路由拦截的 mock harness 注入治理响应与 admin / 普通用户角色，不依赖真实后端或不可信执行环境；断言覆盖请求是否发出、tab 可见性、组件挂载时机与八类面板渲染结果。
4. **不依赖真实不可信执行环境**：本阶段不执行真实沙箱逃逸、网络对抗、故障注入或真实多 Worker 崩溃；治理信号由确定性数据与受控写入点产生。需要真实不可信环境的对抗/故障验证不在本阶段测试范围（见第 8 节范围限定）。
5. **权限与租户隔离前置**：每个治理端点先断言非 admin 一律 403 `insufficient_role`，再断言 tenant / business_scope / workspace 过滤生效；无 `tenant_id` 的表固定 JOIN `runtime_runs`（按 run_id）取 tenant/scope，孤立记录标注为部署级。
6. **Secret 零容忍**：每个治理响应、错误与诊断用例注入 canary 并断言零出现；parser 原始样本永不进入任何前端模型或断言输出面，仅验证分类计数与有界脱敏原因码。
7. **迁移号动态重验**：`0072` / `0073` 为 planning 值，仅在 head 重验通过后方可写入用例；若实际 head 变化，按 R-5 先登记 R-n 裁定并同步双语文档，再以实际编号重跑，不得写死 planning 号判定通过。
8. **报告不预写**：本计划不生成 `06-test-report.md` / `07-acceptance-report.md`；仅在实际测试与验收执行后创建，不登记 issue 号或 PR 号。

## 2. 测试环境与数据构造

| 环境 | 用途 | 关键约束 |
|---|---|---|
| 单元（无 DB） | 端点查询口径、权限拒绝、过滤/分页解析、Secret canary、错误码与 409 分支逻辑 | pytest + mock service / 可控时钟；零真实 I/O |
| PG 集成（分片） | 迁移升级、真实表数据、租户 JOIN / scope 隔离、409 缺口落库、parser sink 落库、并发唯一约束 | 每片独立 disposable database / schema；真实迁移 `0070` / `0071` + planned `0072` / `0073`；至少两个租户与多个 run |
| Playwright mock harness | tab 可见性、admin 门控、按需挂载、八类面板、过滤分页、空状态、四语 | 路由拦截注入响应与角色；不连真实后端 |
| 静态检查 | ruff / 架构、check:i18n、typecheck、build、head 单一性、无 Prometheus 依赖 | 本地或 CI 命令执行；head 检查结果须留痕 |

**数据构造约定**：治理行以真实表结构 fixture 构造，`execution_fencing_denials` / `runtime_event_outbox` 不自带 tenant 时通过 `runtime_runs` 关联；构造孤立 run_id、跨租户 run、分页边界、重复 `source_event_id`、`supersedes_id` 链、五类 parser 分类与 Secret canary。禁止提交真实密钥；canary 必须可撤销。若 PG 或 head 重验环境不可用，相关用例标记 `pending_env`，不得以 mock 替代硬门槛。

## 3. 后端单元测试 UT-1~UT-14

| ID | 用例 | 预期 | 环境 | 溯源 |
|---|---|---|---|---|
| UT-1 | 治理路由骨架权限拒绝：以 admin / Reader / 普通用户身份调用全部 `/observability/execution/*` 端点 | 仅 admin 获得数据；非 admin 一律 403 `insufficient_role`；无效过滤/分页 400；错误码统一 | 单元（无 DB） | FR-1；SIG-1~SIG-8；T-1；R-1 |
| UT-2 | 统一 scope 解析与分页口径：`resolve_scope()` + `scope_predicate()` 与分页参数解析 | tenant/business_scope/workspace 过滤生效；分页参数边界一致；空结果返回稳定空状态 | 单元（无 DB） | FR-1；SIG-1~SIG-8；T-1；R-2 |
| UT-3 | Fencing 查询口径：`GET /observability/execution/fencing-denials` 的 time / reason / operation 过滤与分页 | 过滤与分页正确；字段口径与 `execution_fencing_denials` 一致；无 Secret | 单元（无 DB） | FR-2；SIG-1；T-2；R-2 |
| UT-4 | 清理失败两类判定：`GET /observability/execution/cleanup-failures` 的 `cleanup_status='failed'` 与「已请求取消未确认」 | 两类均返回；状态歧义按「未确认」呈现，不伪报 cancelled；不改 `RunView` | 单元（无 DB） | FR-4；SIG-3；T-3；R-3 |
| UT-5 | Outbox 聚合口径：`GET /observability/execution/outbox` 的 pending 数、最老 `available_at` 滞留秒、failed `last_error`、24h published 计数 | 四项口径正确；不触发发布副作用；不引入 Prometheus | 单元（无 DB） | FR-5；SIG-4；T-4；R-8 |
| UT-6 | usage 修正链口径：`GET /observability/execution/usage-conflicts` 的 `supersedes_id` 链与唯一约束拒绝的重复来源 | 链与重复来源可见；按 `tenant_id` 过滤；不重复计数、不改聚合语义 | 单元（无 DB） | FR-7；SIG-6；T-5；R-2 |
| UT-7 | 凭据审计口径：`GET /observability/execution/credential-audit?action=revoked` 按 action / tenant 过滤 | 审计行过滤正确；`public_metadata()` 无 Secret；越权 403 `insufficient_role` | 单元（无 DB） | FR-9；SIG-8；T-6；R-1 |
| UT-8 | parser 诊断分类计数口径：`malformed/unknown_schema/unknown_type/size_limit/critical_terminal` 五类 | 仅分类计数与有界脱敏原因码；`execution_parser_raw_sample_enabled=false` 沿用；原始样本零输出 | 单元（无 DB） | FR-8；SIG-7；T-8；R-4 |
| UT-9 | 租户 JOIN 口径：无 `tenant_id` 表 JOIN `runtime_runs` 取 tenant/scope | JOIN 结果带 tenant/scope；孤立 run_id 标注部署级；跨租户访问默认拒绝 | 单元（无 DB） | FR-1、FR-2、FR-5；SIG-1、SIG-4；T-2、T-4；R-2 |
| UT-10 | Secret canary 过滤：向所有治理响应、错误与诊断注入 canary | canary 零出现；Secret 字段不进入任何响应模型 | 单元（无 DB） | FR-1、FR-8、FR-9；SIG-7、SIG-8；T-2~T-8；R-4 |
| UT-11 | 空状态与错误 fail-closed：空结果与查询异常 | 空结果稳定空状态；异常以统一错误码返回，不降级为 Reader 可见 | 单元（无 DB） | FR-1、FR-10；SIG-1~SIG-8；T-1；R-1 |
| UT-12 | SSE 409 缺口写入分支：游标早于 `event_retention_floor_seq` 触发 409 分支 | 写一条有界缺口事件；写入失败不阻断 409；`id=sequence` / `event_replay_gap` / `X-Event-Retention-Floor` 零变更 | 单元（无 DB） | FR-6；SIG-5；T-7；R-5 |
| UT-13 | 迁移 `0072_execution_replay_gap_events` 定义：down_revision、表/约束、expand→有界回填→校验→读切换结构 | 指向重验后的唯一 head；不改已应用历史迁移；有界写入失败不影响主流程 | 单元（无 DB） | FR-6；SIG-5；T-7；R-5 |
| UT-14 | 迁移 `0073_execution_parser_diagnostics` 定义与 collector 接线：down_revision、五类分类字段、sink 开关 | 指向重验后的唯一 head；Secret / 原始样本不落表；`ParserDiagnosticCollector` 接线且默认不保留原始样本 | 单元（无 DB） | FR-8；SIG-7；T-8；R-4、R-5 |

## 4. PG 集成测试 IT-1~IT-8

| ID | 用例 | 预期 | 环境 | 溯源 |
|---|---|---|---|---|
| IT-1 | 新库迁移链升级：从重验后的唯一 head 升级 planned `0072` / `0073` | 新表/字段创建成功；历史迁移 `0001`~`0071`（含 `0068` / `0069`）零修改；head 记录留痕 | PG 集成（分片） | FR-6、FR-8；SIG-5、SIG-7；T-7、T-8；R-5 |
| IT-2 | Fencing 真实表数据、JOIN 租户隔离与分页：`execution_fencing_denials` 真实行关联 `runtime_runs` | tenant/scope 正确；跨租户与分页边界被正确拒绝/切分；孤立行标注部署级 | PG 集成（分片） | FR-1、FR-2；SIG-1；T-2；R-2 |
| IT-3 | 清理失败两类真实数据：`cleanup_status='failed'` 与「已请求取消未确认」 | 两类均返回；公开 `RunView` 字段零变更；host/workdir 告警仍在日志 | PG 集成（分片） | FR-4；SIG-3；T-3；R-3 |
| IT-4 | Outbox 真实表指标口径与副作用：`runtime_event_outbox` pending 滞留与 failed `last_error` | 四项指标与真实行一致；不触发发布；`last_error` 有界脱敏 | PG 集成（分片） | FR-5；SIG-4；T-4；R-8 |
| IT-5 | usage 并发唯一约束与修正链：并发写入重复 `source_event_id` 并构造 `supersedes_id` 链 | 重复来源被 `UNIQUE(run_id, source, source_event_id)` 拒绝；链落库且按 `tenant_id` 隔离；聚合不变 | PG 集成（分片） | FR-7；SIG-6；T-5；R-2 |
| IT-6 | SSE 409 缺口落库：游标置于 `event_retention_floor_seq` 之前触发 409 | 缺口事件写入一条且有界；端点可查；409 响应头与 SSE `id` / `event_replay_gap` 语义零 diff | PG 集成（分片） | FR-6；SIG-5；T-7；R-5 |
| IT-7 | parser sink 落库：五类诊断经 collector/sink 写入 `execution_parser_diagnostics`，并注入含 Secret 的样本 | 分类计数落库；原始样本与 Secret 零落库、零进 UI | PG 集成（分片） | FR-8；SIG-7；T-8；R-4 |
| IT-8 | 凭据审计真实数据与租户隔离：`execution_credential_audit` 真实行按 tenant 过滤 | 审计行可见且跨租户拒绝；`public_metadata()` 无 Secret；越权 403 | PG 集成（分片） | FR-9；SIG-8；T-6；R-1 |

## 5. 前端 Playwright 测试 FE-1~FE-10

| ID | 用例 | 预期 | 环境 | 溯源 |
|---|---|---|---|---|
| FE-1 | 治理 tab 显示/隐藏：admin 与普通用户进入「运行与审计」页 | 「运行总览」始终可见；「执行治理」tab 仅 admin 可见 | Playwright mock harness | FR-10；SIG-1~SIG-8；T-10；R-7 |
| FE-2 | admin 门控与按需挂载：切换两个 tab 并断言治理请求 | 非 admin 不显示 tab 且不发出任何 `/observability/execution/*` 请求；治理组件仅在治理 tab 激活且 admin 时挂载 | Playwright mock harness | FR-10；SIG-1~SIG-8；T-10；R-1、R-7 |
| FE-3 | 八类面板渲染 A 组：Fencing 拒绝、清理失败、Outbox lag、usage 冲突 | 四类面板按 mock 数据渲染；字段与标签正确；部署级标注出现于 Worker/无租户数据 | Playwright mock harness | FR-2、FR-4、FR-5、FR-7；SIG-1、SIG-3、SIG-4、SIG-6；T-10 |
| FE-4 | 八类面板渲染 B 组：Worker 丢失、SSE 重放缺口、parser 诊断、凭据吊销审计 | 四类面板渲染；Worker 明示「部署级、非租户维度」；parser 仅显示分类计数与脱敏原因码 | Playwright mock harness | FR-3、FR-6、FR-8、FR-9；SIG-2、SIG-5、SIG-7、SIG-8；T-10；R-4 |
| FE-5 | 过滤与分页：面板内过滤控件与 `serverPagination` / `clientPagination` 交互 | 过滤条件传给正确端点；分页边界正确；不额外触发未挂载面板的请求 | Playwright mock harness | FR-1、FR-10；SIG-1~SIG-8；T-10；R-7 |
| FE-6 | 空状态 fail-closed：强制空数据与错误响应 | 稳定空状态与 loading；错误不降级为展示伪造恢复态/成功；单项缺失不阻塞其他面板 | Playwright mock harness | FR-3、FR-10；SIG-1~SIG-8；T-10；R-9 |
| FE-7 | 四语 i18n：切到 `zh-CN` / `zh-TW` / `en` / `hi` | 治理 tab 与八类面板文案四语齐平；键缺失被 `check:i18n` 拦截（见 CM-2） | Playwright mock harness | FR-10；SIG-1~SIG-8；T-11；R-9 |
| FE-8 | 无 Secret 文本：注入 canary 与 raw sample 到所有 mock 响应 | 页面文本、DOM 与请求体均无 Secret / 原始样本文本 | Playwright mock harness | FR-8、FR-9、FR-10；SIG-7、SIG-8；T-10、T-11；R-4 |
| FE-9 | 公开 RunView / SSE 零变更：对比「运行总览」Panel 与公开 Run 数据 | 公开 `RunView` 字段零 diff；SSE `id=sequence` / `event_replay_gap` / `X-Event-Retention-Floor` 零变更 | Playwright mock harness | FR-3、FR-4、FR-6、FR-10；SIG-3、SIG-5；T-10；R-3 |
| FE-10 | 路由与导航零变更：`hashRouter.ts` 与全局导航 | 无 `/observability/:sub` 子路由；侧边栏「质量运营」组与「运行与审计」入口零变更 | Playwright mock harness | FR-10；SIG-1~SIG-8；T-10；R-7 |

## 6. 一般检查 CM-1~CM-6

| ID | 检查 | 通过标准 | 环境 | 溯源 |
|---|---|---|---|---|
| CM-1 | ruff / 架构检查 | 后端 lint 通过；治理端点落在 `platform_routes.py`，与现有 `/observability/*` 同模块；未改公开契约 | 静态检查 | FR-1；T-1；R-1 |
| CM-2 | `check:i18n` 四语齐平 | `npm run check:i18n` 通过；`zh-CN` / `zh-TW` / `en` / `hi` 键齐平，缺键不得上线 | 静态检查 | FR-10；T-11；R-9 |
| CM-3 | typecheck | 前端类型检查通过；治理 client 请求/响应类型与 T-1~T-8 契约一致，无 Secret 字段进入前端模型 | 静态检查 | FR-1~FR-9；T-9；R-7 |
| CM-4 | build | 前端构建通过；治理组件按需挂载不破坏现有产物 | 静态检查 | FR-10；T-10、T-11；R-9 |
| CM-5 | 迁移链 head 单一性 | `backend/migrations/versions/` 重验唯一 head；`0072` / `0073` 与重验结果一致；已应用历史迁移零修改；重验结果写入 T-14 文档同步记录 | 静态检查 | FR-6、FR-8；SIG-5、SIG-7；T-7、T-8、T-14；R-5 |
| CM-6 | 无 Prometheus 依赖 | 无 Prometheus、无 `/metrics`、无新监控依赖；复用 `monitor_checks` / `notifications` 与结构化日志 | 静态检查 | FR-5；SIG-4；T-4、T-14；R-8 |

## 7. skip / pending 处理规则

1. 任何 skip 必须逐条记录编号、原因与归属任务；skip 不得记为 pass，也不得计入 C-1~C-6 门槛通过。
2. `pending_env` 仅用于环境确实不可用：PG 分片、head 重验环境、Playwright harness 或 CI 命令缺失。标记为 `pending_env` 的用例不得改写为 pass，阶段状态保持「未测试、未验收」。
3. 不依赖真实不可信环境的用例（UT/IT/FE/CM 全部）不得以「缺少真实沙箱/不可信环境」为由 skip：这些环境不在本阶段测试范围，mock 与确定性 fixture 即为设计的判定手段。
4. UT-13 / UT-14 / IT-1 / CM-5 若实际 head 与 planning `0072` / `0073` 不同，按 R-5 先登记 R-n 裁定并同步双语文档，再以实际编号重跑；不得直接跳过，也不得写死 planning 号判定通过。
5. 用例失败先按缺陷处理并登记，再决定重跑范围；不得以调整 fixture 掩盖真实失败。
6. 本计划下所有用例当前状态均为「待执行」；在报告生成前不存在任何 pass / fail / skip 的实际结论。

## 8. 范围限定与证据处理

- **范围外 / 仅历史背景**：性能基线（p50/p95、Outbox 滞留阈值、容量样本）、真实不可信执行环境（沙箱逃逸、网络对抗、真实故障注入）、高风险启用（不可信多租户、生产 Codex 路由）均不作为本阶段测试门槛，也不产生 `pending_env`。
- **证据归属**：UT / IT / FE / CM 的独立结论写入实际执行后的 `06-test-report.md`（当前尚未生成）；验收证据写入 `07-acceptance-report.md`（当前尚未生成）。不预写报告，不登记 issue 号或 PR 号。
- **状态真实**：本文件是测试计划，不提供实施完成或测试通过的结论；在用例实际执行并记录证据前，阶段保持「未实施、未测试、未验收」。
