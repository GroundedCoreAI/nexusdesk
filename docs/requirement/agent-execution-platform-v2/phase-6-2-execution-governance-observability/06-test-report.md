# Phase 6-2 · Execution Governance Observability — Test Report

> 状态：已执行
> 执行日期：2026-11-23
> 目标版本：分支 `feat/phase-6-2-execution-governance`，`git rev-parse HEAD` = `19ad42d1e32f46e1e477cc1c292e1e9474e1ec52`
> 证据说明：本报告为独立验收子代理（accept-gov）在隔离验收环境中的**实际执行结果**。关键项进行了独立重跑复核，其余项复用阶段内已执行并留痕的独立结论；证据复用不降低门槛。实施代码目前位于上述 HEAD 之上的工作区（未提交），被测试对象即该工作区状态；HEAD SHA 标识版本基线。
> 范围：统一治理查询 API + 可视化 UI。性能基线、真实不可信执行环境、高风险能力启用为范围外（见 05 §6），不产生 `pending_env`。

## 1. 执行环境

| 环境 | 配置 |
|---|---|
| Python | `backend/.venv/bin/python` = Python 3.12.13 |
| PostgreSQL | 临时容器 `nexusdesk-gov-pg`，`127.0.0.1:55432`，DB `nexusdesk_test`，schema 已升级至 `0073_execution_parser_diag` head |
| DB URL | `postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/nexusdesk_test`（`AGENT_DATABASE_URL` / `TEST_DATABASE_URL` / `MIGRATION_TEST_DATABASE_URL` 同源） |
| 运行模式 | `AGENT_ENVIRONMENT=development`；每用例 `TMPDIR=$(mktemp -d /tmp/acc-XXXXXX)` 隔离 |
| 前端 | Node/npm；Vite dev server `127.0.0.1:5173`；Playwright（1 worker，headless Chromium） |

---

## 2. 后端单元测试 UT-1~UT-14

执行结果：`backend/tests/test_execution_governance_observability.py` **15 passed / 0 fail / 0 skip**（独立重跑确认）；迁移定义与 collector 接线由 `test_execution_diagnostics.py` + `test_execution_phase6_invariants.py` 的 **19 passed** 及 `test_execution_credentials_migration.py` 的 **5 passed** 覆盖。

> 编号映射说明：实现测试文件内部的 `test_ut*` 标签与 `04-test-plan.md` 的 UT 编号并非逐一对应。以下按 `04-test-plan.md` 的计划编号汇总，并标注实际覆盖该计划点的测试函数（以覆盖内容为准，不以函数标签为准）。

| 计划编号 | 覆盖内容 | 实际测试函数 / 证据 | 结果 |
|---|---|---|---|
| UT-1 | 治理路由骨架权限拒绝；仅 admin 通过，非 admin 403 `insufficient_role`；无效过滤/分页 400 | `test_ut1_all_governance_routes_registered`、`test_ut2_non_admin_is_denied_on_every_endpoint`、`test_ut3_invalid_pagination_returns_400`、`test_ut4_invalid_time_filter_returns_400`、`test_ut5_invalid_enum_filter_returns_400` | PASS |
| UT-2 | 统一 scope 解析与分页口径 | `test_ut8_scope_clause_uses_resolve_scope_and_scope_predicate`、`test_ut3_invalid_pagination_returns_400` | PASS |
| UT-3 | Fencing 查询口径（time/reason/operation 过滤 + 分页，无 Secret） | `test_ut9_fencing_denials_join_and_orphan_label` | PASS |
| UT-4 | 清理失败两类判定；歧义按「未确认」；不改 RunView | `test_ut10_cleanup_failures_two_categories_and_runview_zero_diff` | PASS |
| UT-5 | Outbox 四项指标口径；无发布副作用；无 Prometheus | `test_ut11_outbox_metrics_without_publish_side_effect` | PASS |
| UT-6 | usage 修正链口径；按 tenant 过滤；不重复计数 | `test_ut12_usage_conflicts_kind_and_tenant_filter` | PASS |
| UT-7 | 凭据审计口径；`public_metadata()` 无 Secret；越权 403 | `test_ut13_credential_audit_secret_free`、`test_ut2_non_admin_is_denied_on_every_endpoint` | PASS |
| UT-8 | parser 五类诊断分类计数；原始样本零输出 | `test_ut14_replay_and_parser_are_allowlisted_and_canary_free` | PASS |
| UT-9 | 租户 JOIN 口径；孤立 run_id 标注部署级；跨租户默认拒绝 | `test_ut6_cross_tenant_request_fails_closed`、`test_ut7_orphan_tenant_clause_allows_deployment_level`、`test_ut9_fencing_denials_join_and_orphan_label` | PASS |
| UT-10 | Secret canary 零出现；Secret 字段不进入响应模型 | `test_ut13_credential_audit_secret_free`、`test_ut14_replay_and_parser_are_allowlisted_and_canary_free`、`test_ut14b_sink_never_retains_raw_sample` | PASS |
| UT-11 | 空状态与错误 fail-closed；统一错误码，不降级为 Reader 可见 | `test_ut3_invalid_pagination_returns_400`、`test_ut5_invalid_enum_filter_returns_400`、`test_ut2_non_admin_is_denied_on_every_endpoint` | PASS |
| UT-12 | SSE 409 缺口写入分支；`id=sequence` / `event_replay_gap` / 响应头零变更 | `test_execution_diagnostics.py` + `test_execution_phase6_invariants.py`（19 passed）；`test_it6_sse_409_gap_write_and_contract_zero_diff` | PASS |
| UT-13 | 迁移 `0072_execution_replay_gap_events` 定义；单一 head；历史零改 | `test_it1_migration_head_chain_is_single_and_additive`、`test_execution_credentials_migration.py`（5 passed）；alembic heads 重验 | PASS |
| UT-14 | 迁移 `0073_execution_parser_diagnostics` 定义与 collector 接线；Secret/原始样本不落表 | `test_ut14b_sink_never_retains_raw_sample`、`test_it1_migration_head_chain_is_single_and_additive`、`test_it7_parser_diagnostics_wiring_and_canary_zero` | PASS |

**skip：无。** 所有 UT 实际执行并通过。

---

## 3. PG 集成测试 IT-1~IT-8

执行结果：`backend/tests/test_execution_governance_observability_postgres.py` **9 passed / 0 fail / 0 skip**（真实 PG，独立重跑确认，9 warnings 为既有弃用告警，与本阶段无关）。抗污染复核：注入 10 条脏数据后仍 9/9；跑完相关治理表 count=0。

| 计划编号 | 覆盖内容 | 实际测试函数 | 结果 |
|---|---|---|---|
| IT-1 | 新库迁移链升级至新 head；历史 `0001`~`0071` 零修改；head 留痕 | `test_it1_migration_head_chain_is_single_and_additive`、`test_it1b_fresh_database_upgrades_through_new_head` | PASS |
| IT-2 | Fencing 真实表 JOIN 租户隔离、分页、孤立行部署级标注 | `test_it2_fencing_join_tenant_isolation_and_orphan` | PASS |
| IT-3 | 清理失败两类真实数据；公开 RunView 零变更 | `test_it3_cleanup_failure_categories_and_runview_zero_diff` | PASS |
| IT-4 | Outbox 真实指标口径；无发布副作用；`last_error` 有界 | `test_it4_outbox_metrics_and_no_publish_side_effect` | PASS |
| IT-5 | usage 并发唯一约束 + 修正链；按 tenant 隔离；聚合不变 | `test_it5_usage_conflicts_tenant_filter_and_aggregation_unchanged` | PASS |
| IT-6 | SSE 409 缺口落库有界；409 响应头与 SSE 语义零 diff | `test_it6_sse_409_gap_write_and_contract_zero_diff` | PASS |
| IT-7 | parser sink 真实 mapper→collector→落库；原始样本与 Secret 零落库/零进 UI | `test_it7_parser_diagnostics_wiring_and_canary_zero` | PASS |
| IT-8 | 凭据审计真实数据按 tenant 过滤；`public_metadata()` 无 Secret；越权 403 | `test_it8_credential_audit_tenant_filter_and_no_secret` | PASS |

**skip：无。**

> IT-7 反 no-op 接线验证：该用例刻意通过持有 composition 接线的**真实 React/Codex mapper** 驱动（而非直接调用 `collector.report`），并断言 `tenant_id` 来自授权 run scope，可捕获 collector 未接线（SIG-7）或 sink 空转的退化。

---

## 4. 前端 Playwright 测试 FE-1~FE-10

执行结果：`frontend/tests/execution-governance.spec.ts` **10 passed / 0 fail**（mock harness，独立重跑确认）。

| 计划编号 | 覆盖内容 | 测试用例 | 结果 |
|---|---|---|---|
| FE-1 | 治理 tab 仅 admin 可见；运行总览始终可见 | `FE-1 ... tab is admin-only` | PASS |
| FE-2 | 非 admin 不发出治理请求；组件按需挂载 | `FE-2 no governance request is issued by a viewer...` | PASS |
| FE-3 | 八类面板渲染（A/B 组合由 FE-3/FE-4 覆盖） | `FE-3 activation mounts all signals` | PASS |
| FE-4 | 八类面板 B 组（Worker/SSE/parser/凭据）渲染 | `FE-4 all eight governance signals render` | PASS |
| FE-5 | 过滤控件传参正确 | `FE-5 filters change the server query` | PASS |
| FE-6 | 服务端分页边界 | `FE-6 pagination is server-side` | PASS |
| FE-7 | 空状态 fail-closed | `FE-7 empty responses fail closed` | PASS |
| FE-8 | 每个治理端点 403 时 fail-closed，不降级展示数据 | `FE-8 a 403 on every governance endpoint fails closed` | PASS |
| FE-9 | Secret / key / 原始样本 canary 零进 DOM；公开 RunView/SSE 零变更 | `FE-9 Secret, key and raw-sample canaries never reach the DOM` | PASS |
| FE-10 | 四语翻译；hashRouter 与全局导航零变更 | `FE-10 four locales translate the tab...` | PASS |

**skip：无。**

---

## 5. 一般检查 CM-1~CM-6

| 计划编号 | 检查 | 命令 / 证据 | 结果 |
|---|---|---|---|
| CM-1 | ruff / 架构检查 | `.venv/bin/python -m ruff check`（10 个变更文件）→ `All checks passed!`；治理端点位于 `platform_routes.py`，与现有 `/observability/*` 同模块 | PASS |
| CM-2 | `check:i18n` 四语齐平 | `npm run check:i18n` → `Verified 2690 translations in zh-CN, zh-TW, en, hi` | PASS |
| CM-3 | typecheck | `npm run typecheck`（`tsc --noEmit`）→ 通过；治理 client 类型无 Secret 字段进入前端模型 | PASS |
| CM-4 | build | `npm run build` → `✓ built in 2.96s`（仅有既有的 chunk>500kB 警告，非阻塞） | PASS |
| CM-5 | 迁移链 head 单一性 | `alembic heads` → `0073_execution_parser_diag (head)`（唯一）；链 `0071→0072→0073`；历史迁移 `0001`~`0071` 工作区零修改 | PASS |
| CM-6 | 无 Prometheus 依赖 | 变更文件 grep：仅注释性提及（"no Prometheus/metrics surface"），无 import、无 `/metrics`、无新监控依赖 | PASS |

---

## 6. skip / pending_env 汇总

| 编号 | 状态 | 原因 | 归属 |
|---|---|---|---|
| — | 无 | 本阶段范围内所有 UT / IT / FE / CM 均实际执行并通过，无 skip、无 pending_env | — |

**范围外、不阻塞（05 §6）**：`backend/tests/agent_execution/test_host_stdin_delivery.py::test_real_codex_consumes_the_prompt_through_the_host` 需要真实 Codex CLI（`/usr/local/bin/codex`）；该文件未被阶段 6-2 修改，属「真实不可信执行环境 / 真实 Provider」范围外项，按 05 §6 不产生 `pending_env`、不作为本阶段门槛，不影响结论。

---

## 7. 总计

| 类别 | 通过 | 失败 | skip / pending_env |
|---|---|---|---|
| 后端单元（治理） | 15 | 0 | 0 |
| 后端单元（诊断/不变量） | 19 | 0 | 0 |
| 迁移测试 | 5 | 0 | 0 |
| PG 集成 | 9 | 0 | 0 |
| 前端 E2E | 10 | 0 | 0 |
| 一般检查 CM | 6 | 0 | 0 |

**结论：所有范围内用例通过，无 P0 / P1。** 详细验收判定见 `07-acceptance-report.md`。
