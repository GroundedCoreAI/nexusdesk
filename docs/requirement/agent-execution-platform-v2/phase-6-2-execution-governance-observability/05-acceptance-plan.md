# Phase 6-2 · Execution Governance Observability — Acceptance Plan

> Status: 已批准作为后续验收的文档范围基线；未实施、未测试、未验收。本文只描述「将如何验收」，不包含任何已验收结论。
> Created: 2026-11-22
> Basis: Phase 6 `02-requirements.md` FR-16「可运维性」；本阶段 `01-business-goals.md`（G1~G4）、`02-requirements.md`（FR-1~FR-10、AC-1~AC-10）、`08-implementation-breakdown.md`（T-1~T-14、R-1~R-10、A-1~A-10、C-1~C-6）；批准范围基线中冻结的 SIG-1~SIG-8 分类。测试执行以本阶段 `04-test-plan.md` 为准。
> Scope note: 验收对象仅为「统一治理查询 API + 可视化 UI」。性能基线、真实不可信执行环境与高风险能力启用均为范围外或历史背景，不作为本阶段验收门槛。所有编号与措辞与基线逐字对齐；`0072` / `0073` 为 planning 值。

## 1. 验收范围与职责

逐条确认 AC-1~AC-10 对应的 A-1~A-10 场景，检查权限/租户隔离、Secret 零出现、数据完整性与迁移、兼容性零变更，并核对单一验收负责人记录。验收负责人组织并记录判定，执行人准备隔离环境、补充检查与整理证据；两者可由同一人担任，但须在记录中写明。不虚构独立的产品、QA、业务或财务角色；用量与审计的可信度由 A-7、C-2、C-4 及自动核对证据证明，不以财务签字替代技术证据。

本阶段不开放不可信多租户与生产 Codex 路由，不声称高风险能力启用或生产放行（R-10）。阶段验收通过本身不授权上述能力；相关批准需在阶段外单独取得，且不在本文预置结论。

## 2. 验收环境与前置条件

| 环境 | 用途 |
|---|---|
| 单元 + PG 分片环境 | 治理端点口径、权限拒绝、租户 JOIN、分页、真实表数据、`0072` / `0073` 升级与落库、并发唯一约束 |
| Playwright mock harness 环境 | tab 可见性、admin 门控、按需挂载、八类面板、过滤分页、空状态、四语与无 Secret 文本 |
| 静态检查 / CI 环境 | ruff、check:i18n、typecheck、build、迁移 head 单一性、无 Prometheus 依赖 |

**前置条件**：相关 T-1~T-14 任务已按 `08-implementation-breakdown.md` 完成；UT-1~UT-14、IT-1~IT-8、FE-1~FE-10、CM-1~CM-6 已实际执行并留下独立结论；迁移 head 已重验并记录。当前这些前置条件均未满足——本阶段尚未实施、未测试、未验收。真实性不可信环境、性能基线样本与高风险启用不作为前置条件（见第 5 节）。只使用可撤销 canary，禁止真实密钥。

## 3. 功能验收场景 A-1~A-10（一一对应 AC-1~AC-10）

| # | 场景 | 步骤 | 预期 | 证据 | 溯源 |
|---|---|---|---|---|---|
| A-1 | 统一治理 API 权限与错误码 | 分别以 admin、Reader、普通用户调用全部 `/observability/execution/*` 端点，注入 tenant/scope 过滤与 Secret canary，并构造无效分页 | 仅 admin 获得分页治理数据且过滤生效；非 admin 一律 403 `insufficient_role`；无效过滤/分页 400；任何响应无 Secret | UT-1、UT-2、UT-10、UT-11；`06-test-report.md`（尚未生成）；CI run（待记录）；单一验收负责人记录 | AC-1；FR-1；SIG-1~SIG-8；Phase 6 FR-16 |
| A-2 | Fencing 拒绝查询 | 制造旧 owner 写入产生 fencing 拒绝，按 time / reason / operation 过滤并分页，检查 JOIN `runtime_runs` 结果 | 记录带 tenant/scope；过滤与分页正确；UI 表呈现；孤立记录标注部署级且无 Secret | UT-3、UT-9；IT-2；FE-3；`06-test-report.md`（尚未生成）；单一验收负责人记录 | AC-2；FR-2；SIG-1；Phase 6 FR-16 |
| A-3 | Worker 丢失与恢复态 | 停止某 Worker 心跳触发 `worker.runtime.heartbeat` / `runtime.lease_expired` 检查（受控 fixture），再打开治理面板 | 复用 `GET /notifications/checklist`、`GET /notifications` 显示丢失与恢复态；UI 明示「部署级、非租户维度」；未新建事件历史表；Reader 路由行为不变 | FE-4、FE-6；CM-6；`06-test-report.md`（尚未生成）；单一验收负责人记录 | AC-3；FR-3；SIG-2；Phase 6 FR-16 |
| A-4 | 清理失败与取消未确认 | 分别设置 `cleanup_status='failed'`，以及 `cancel_requested_at` 非空且 `cancel_confirmed_at` 为空，调用清理失败端点 | 两类记录均返回；公开 `RunView` 字段零变更；host/workdir 告警仍在日志；状态歧义不伪报 cancelled | UT-4；IT-3；FE-9；`06-test-report.md`（尚未生成）；单一验收负责人记录 | AC-4；FR-4；SIG-3；Phase 6 FR-16 |
| A-5 | Outbox lag 与投递失败 | 注入 pending 滞留（最老 `available_at` 较早）与 failed `last_error` 的 `runtime_event_outbox` 行，调用 outbox 端点 | 返回 pending 数、滞留秒数、failed `last_error` 与 24h published 计数；UI 指标卡/表呈现；不触发发布副作用；无 Prometheus | UT-5；IT-4；CM-6；FE-3；`06-test-report.md`（尚未生成）；单一验收负责人记录 | AC-5；FR-5；SIG-4；Phase 6 FR-16 |
| A-6 | SSE 重放缺口 | 将客户端游标置于 `event_retention_floor_seq` 之前触发 409 `event_replay_gap` 与 `X-Event-Retention-Floor` 响应头，再查询缺口端点 | 409 分支写入一条有界缺口事件且查询可见；SSE `id` / `event_replay_gap` / 响应头语义不变；迁移 `0072` 号实施前已重验 head | UT-12、UT-13；IT-1、IT-6；CM-5；FE-9；`06-test-report.md`（尚未生成）；单一验收负责人记录 | AC-6；FR-6；SIG-5；Phase 6 FR-16 |
| A-7 | usage 冲突与修正链 | 制造被 `UNIQUE(run_id, source, source_event_id)` 拒绝的重复来源与 `supersedes_id` 修正链，调用 usage 冲突端点 | 修正链与重复来源均可见且按 `tenant_id` 过滤；聚合语义不变、不重复计数；可选真实冲突计数不在此阶段默认启用 | UT-6；IT-5；FE-3；`06-test-report.md`（尚未生成）；单一验收负责人记录 | AC-7；FR-7；SIG-6；Phase 6 FR-16 |
| A-8 | parser 诊断（不含原始样本） | 注入 `malformed` / `unknown_schema` / `unknown_type` / `size_limit` / `critical_terminal` 事件与含 Secret canary 的样本，查看 parser 端点与 UI | 仅显示分类计数/趋势与有界脱敏原因码；原始样本与 Secret 零出现；迁移 `0073` 号实施前已重验 head；collector 已接线 | UT-8、UT-14；IT-1、IT-7；CM-5；FE-4、FE-8；`06-test-report.md`（尚未生成）；单一验收负责人记录 | AC-8；FR-8；SIG-7；Phase 6 FR-16 |
| A-9 | 凭据吊销与审计 | 吊销一项凭据，调用 `GET /execution-credentials` 与 `GET /observability/execution/credential-audit?action=revoked` | 状态在现有路由显示 revoked；审计行可见且按 tenant 过滤；`public_metadata()` 无 Secret；越权 403 | UT-7；IT-8；FE-4、FE-8；`06-test-report.md`（尚未生成）；单一验收负责人记录 | AC-9；FR-9；SIG-8；Phase 6 FR-16 |
| A-10 | 前端执行治理 tab | 分别以普通用户和 admin 进入「运行与审计」页，切换两个 tab，强制空数据与错误响应，并切换 `zh-CN` / `zh-TW` / `en` / `hi` | 治理 tab 仅 admin 可见；组件仅在治理 tab 激活且 admin 时挂载；空状态 fail-closed；四语齐平且 `npm run check:i18n` 通过；`hashRouter` / 全局导航零变更；公开 `RunView` / SSE 零变更 | FE-1、FE-2、FE-5、FE-6、FE-7、FE-8、FE-9、FE-10；CM-2、CM-3、CM-4；`06-test-report.md`（尚未生成）；单一验收负责人记录 | AC-10；FR-10；SIG-1~SIG-8；Phase 6 FR-16 |

每个场景在执行后须记录：执行人、日期、环境、版本、攻击/故障点或受控 fixture、前置数据、实际结果、判定、日志/DB/DOM 证据链接。硬门槛环境不可用时标记 `pending_env`，阶段不得通过。证据尽量直接引用 `04-test-plan.md` 对应的 UT / IT / FE / CM 与 CI 结果，不重复跑完整套件；证据复用不降低门槛与不虚构角色的要求。

## 4. 关键人工检查 M-1~M-3

仅用于补充自动化未完全覆盖的界面语义与提示；不设置客户端或业务代表角色。每项记录执行人、目标 SHA、结果与证据。

| # | 检查 | 通过标准 |
|---|---|---|
| M-1 | 在界面上检查 tab 切换、治理请求发出时机与过滤/分页交互 | 非 admin 不触发治理请求；空状态与错误提示 fail-closed；不出现伪造恢复态或成功 |
| M-2 | 检查治理面板提示与错误文案 | 文案不含 Secret / host 细节，保留可供运维定位的关联信息 |
| M-3 | 检查四语切换后文案与空状态 | `zh-CN` / `zh-TW` / `en` / `hi` 齐平且语义一致；缺键时 `check:i18n` 拦截 |

## 5. 验收门槛 C-1~C-6（逐字沿用批准范围基线）

| 门槛 | 判定内容（逐字沿用基线） | 通过条件 | 证据 | 溯源 |
|---|---|---|---|---|
| C-1 | C-1 功能语义 | A-1~A-10 全部场景的步骤与预期成立；七个治理端点与八类面板按 FR-1~FR-10 返回和呈现；统一错误码与空状态符合约束 | A-1~A-10 记录；UT / IT / FE 独立结论；`06-test-report.md`（尚未生成） | FR-1~FR-10；AC-1~AC-10；G1 |
| C-2 | C-2 租户/权限隔离 | 所有新增 `/observability/execution/*` 端点仅 admin 可访问，非 admin 一律 403 `insufficient_role`；无 `tenant_id` 表 JOIN `runtime_runs`；跨租户默认拒绝；`worker_heartbeats` 明示部署级 | UT-1、UT-2、UT-9；IT-2、IT-8；A-1、A-2、A-7、A-9；单一验收负责人记录 | FR-1、FR-2、FR-5、FR-7、FR-9；R-1、R-2；G2 |
| C-3 | C-3 Secret 与脱敏 | 治理响应、`public_metadata()`、诊断与 UI 均无 Secret；parser 原始样本与 Secret 零出现，仅分类计数与有界脱敏原因码 | UT-10、UT-8；IT-7；FE-8；CM-6；A-1、A-8、A-9；单一验收负责人记录 | FR-1、FR-8、FR-9；R-4；G2 |
| C-4 | C-4 数据完整性与迁移 | 迁移 head 已重验单一性；`0072` / `0073` 与重验结果一致；已应用历史迁移零修改；409 缺口与 parser sink 落库有界；分页与 JOIN 口径正确；并发唯一约束生效 | UT-13、UT-14；IT-1、IT-2、IT-5、IT-6、IT-7；CM-5；A-6、A-8；单一验收负责人记录 | FR-6、FR-8；R-5；G4 |
| C-5 | C-5 兼容性（公开 RunView/SSE 不变） | 公开 `RunView` 字段零变更；SSE `id=sequence` / `event_replay_gap` / `X-Event-Retention-Floor` 零变更；`hashRouter` 与全局导航零变更；Reader 的 `GET /notifications/*` 行为不变；无 Prometheus | UT-4、UT-12；IT-3、IT-6；FE-9、FE-10；CM-1、CM-6；A-4、A-6、A-10；单一验收负责人记录 | FR-3、FR-4、FR-6、FR-10；R-3、R-7、R-8；G3 |
| C-6 | C-6 无 P0/P1 且单一验收记录 | 不存在 P0 / P1；M-1~M-3 完成或有等价自动化证据；仅有单一验收负责人记录，不虚构多角色签字 | `06-test-report.md`（尚未生成）；`07-acceptance-report.md`（尚未生成）；单一验收负责人记录（待填写） | 全部 FR / AC；G4 |

## 6. 范围限定说明

- **性能基线**：p50 / p95、Outbox 滞留阈值、容量与样本计数仅为历史背景或容量评审资料，不作为本阶段门槛；其缺失不产生 `pending_env`，也不得判定通过或失败。
- **真实不可信执行环境**：真实沙箱逃逸、网络对抗、多 Worker 故障注入不在本阶段范围。本阶段治理信号由确定性 fixture、PG 分片与 Playwright mock harness 产生；没有真实不可信环境不构成阶段阻塞。
- **高风险启用**：不可信多租户、生产 Codex 路由与生产放行均为范围外（R-10），不作为本阶段门槛；阶段验收通过不授权这些能力。
- 以上三项均不写入 A-1~A-10 / C-1~C-6 的通过条件，也不得用来掩盖功能、权限、Secret、数据完整性、迁移或兼容性问题。

## 7. 证据要求

1. **测试报告编号**：UT / IT / FE / CM 的独立结论汇总于 `06-test-report.md`；该文件当前尚未生成，报告编号待实际执行后分配，不得预填或预写。
2. **CI run**：CI 运行标识与链接待实际执行后记录于报告；当前无 CI run 编号，不得虚构。
3. **单一验收负责人记录**：仅保留一份验收记录，字段为验收负责人、执行人、日期、目标 SHA、判定、证据/遗留项。验收负责人与执行人当前均未指定，待执行阶段由用户确认；不虚构姓名、角色或签字。
4. **报告状态**：`06-test-report.md` / `07-acceptance-report.md` 尚未生成，按 R-6 不预写；不登记 issue 号或 PR 号（尚无）。

## 8. 验收结论规则

- **阶段通过**：A-1~A-10 与 C-1~C-6 全部通过，M-1~M-3 完成或有等价自动化证据，且无 P0 / P1。功能和兼容性以受控 fixture 与 mock harness 证据判定。仅单一验收负责人记录，不虚构多角色。阶段通过不授权高风险能力启用或生产放行。
- **有条件通过**：仅剩非安全、非权限/租户、非 Secret、非数据完整性/迁移、非兼容性、非 P0/P1 的 P2 / P3 遗留项，且每项有负责人、期限与验收负责人在单一记录中的说明；即便有条件通过也不授权高风险能力启用。
- **不通过**：任一门槛失败、出现有效越权、Secret 外泄、静默数据缺口、公开契约变更或 A/C 功能与安全准则失败；修复后重跑受影响项与受控回归。
- **pending_env 不改写为 pass**：环境不可用只能标记 `pending_env`，不得改写为 pass，不计入 C-1~C-6 通过，阶段状态保持「未测试、未验收」。
- **不得虚构角色**：不设独立产品、QA、业务、财务或安全签字角色；验收负责人与执行人可由同一人担任，但须如实记录；无人员或证据时不得通过门槛。
- **不得推断状态**：文档基线完整、用例编号齐备或场景写法完成，均不构成已实施、已测试或已验收的证据。只有在报告实际生成、证据齐备且无 P0 / P1 后，方可由验收负责人给出结论；在此之前结论栏保持「待验收（报告尚未生成）」。
