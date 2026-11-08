# Phase 0 · 基线与盘点 — 测试报告

> 状态：修正后的本地正式双跑 310 节点比较与两轮 XPASS 日志审计通过；完整 Phase 0 验收 / Phase 1 入口尚未批准
> 创建：2026-11-08
> 依据：`04-test-plan.md`（P0-UT-01～10、P0-IT-01～10、P0-CM-01～05）、`02-requirements.md`（FR-1～FR-6、AC-1～AC-6）、`baseline/regression-baseline.md`
> 执行：修正后的本地正式 Run 1 / Run 2 于 UTC 2026-11-07 完成；2026-11-08 仅复核实际产物并回填文档，未重跑或替换正式轮次

## 1. 测试范围与环境

**范围**：`baseline/regression-baseline.md` §4 所列、顺序完全相同的 25 个套件。修正后的两轮实际 JUnit summary 均含 310 个唯一节点，全部 `outcome=passed`；总数由修复前 303 节点、5 个 XPASS 工具回归和 2 个长耗时终端格式回归组成。可复现的完整有序命令、环境文件约束、迁移、树身份、逐轮日志审计和比较命令保留在该基线 §5。本报告不另造简化命令替代它。

| 项 | 正式执行环境 |
|---|---|
| 本机 / 分支 | macOS；`feat/agent-execution-platform-v2-phase0` |
| Python / uv | Python 3.11.9；uv 0.11.3 (`45da18ac3`) |
| 测试工具 | pytest 9.1.1；pytest-asyncio 1.4.0；pytest-cov 7.1.0；coverage 7.17.2 |
| 主要依赖 | SQLAlchemy 2.0.54；Pydantic 2.13.5；asyncpg 0.31.0；httpx 0.28.1 |
| PostgreSQL | 17.11 (Debian 17.11-1.pgdg12+2)；`pgvector/pgvector:pg17` |
| 数据库隔离 | Run 1、Run 2 各用一个独立空库；测试前分别迁移并核实到 `0057_industry_pack_runtime` |
| 外部服务 | 无外部 provider 为必过条件；使用 demo/mock、受控本地 HTTP 与 PostgreSQL |
| 环境证据 | `/tmp/nexusdesk-phase0-environment.log` |

当前 JUnit summary 在两轮均未记录 skip、xfail 或 strict xpass，因此没有需要隐藏的跳过项。non-strict XPASS 在 JUnit 中只是普通 passed，故两轮 `-rA` 日志均另行执行 `audit-log`：每轮正式审计和比较门禁重新审计均 exit 0，`summary_entries=310`、`xpass=[]`、`xpass_count=0`。干净 CI、真实授权样本和人工验收不在本次本地执行能力内，边界见 §5、§8、§9。

## 2. 执行总览

| 项 | Run 1 | Run 2 | 比较 / 证据 |
|---|---|---|---|
| base HEAD 元数据 | `c6c47dec39025ebd4d1176c1e9925bac9c99c4fd` | 同左 | 只是 base 元数据，**不是**被测未提交树的 SHA |
| 被测树身份 | `sha256=f7d3ae857427b5d0173c080f4e6678755f4562730629d3155c2b7d2c44c0d2b1 files=1018` | 同左 | 两轮 before/after 四份文件完全相同 |
| UTC 起止 | 2026-11-07T21:37:50Z ～ 2026-11-07T21:40:16Z | 2026-11-07T21:41:09Z ～ 2026-11-07T21:43:36Z | 各自 `.metadata.txt` |
| JUnit tests/failures/errors/skipped | 310 / 0 / 0 / 0 | 310 / 0 / 0 / 0 | 310 个唯一节点均 passed |
| JUnit xfail / xpass | 0 / 0 | 0 / 0 | 全部节点 passed；non-strict XPASS 不由 JUnit 推断 |
| `-rA` 日志审计 | exit 0；310 条、零 XPASS | exit 0；310 条、零 XPASS | `xpass=[]`、`xpass_count=0`；比较门禁重新审计亦成功 |
| JUnit time | 145.281s | 145.353s | 耗时仅观察，不参与等价判定 |
| coverage | 9886/18534 = 53.339807920578394%（53.34%） | 9900/18534 = 53.4153447717708%（53.42%） | 各自 `.coverage.json` |
| pytest / summary / audit 退出码 | 0 / 0 / 0 | 0 / 0 / 0 | pytest 真实退出码未被包装器覆盖 |
| tree-after / 轮内 cmp / wrapper 退出码 | 0 / 0 / 0 | 0 / 0 / 0 | 轮内树身份均不变，包装器成功 |
| 节点比较 | — | — | 比较门禁重新审计后 compare exit 0；`/tmp/nexusdesk-phase0-compare.json`：`identical=true`，四类差异均为空 |

`/tmp/nexusdesk-phase0-identity-checks.json` 的 `run1_within`、`run2_within`、`cross_run_tree`、`cross_run_base` 全为 `true`。两轮之间没有仓库文件变化；比较是在身份门禁及两轮日志审计全部通过后进行的两份真实 JUnit 比较，不是 §7 所述早期 self-compare。被测产物当时是未提交工作树；最终产物提交 SHA 未创建，见 P0-CM-01 的 `pending_commit` 边界。本报告属于事后文档回填，不把上述哈希冒充为包含事后报告编辑的新树身份。本报告 60 个不同测试函数引用（含参数化函数的全部节点）已逐一映射到两轮 summary，均存在且 passed。

## 3. 单元测试（P0-UT）逐条结果

下表测试文件均位于 `backend/tests/`。写函数名并注明参数节点数时，指该函数在 summary 中对应的全部精确 `(classname,name)` 参数化节点；这些节点已逐一对照两轮 summary。

| 编号 | 需求 / 溯源 | 具体测试节点或执行证据 | 实际结果 | 状态 / 边界 |
|---|---|---|---|---|
| P0-UT-01 | Engine 正常消息—工具循环；FR-2/FR-4 | `test_runtime_engine.py::test_model_tool_observe_reply_and_history`；`test_runtime_baseline.py::test_engine_emits_streaming_model_event_payload_essentials`、`test_engine_emits_tool_event_payload_essentials`、`test_engine_returns_trimmed_history_and_only_dropped_old_messages` | 工具请求参数、`ToolMessage` 回灌、最终答复、事件顺序、流式 delta、usage/gateway 字段及 history/dropped 均有断言；两轮全过 | 本地通过 |
| P0-UT-02 | 模型/工具异常、预算、空输出与脱敏；FR-2/FR-4 | `test_runtime_engine.py::test_execution_guards`（3 个参数节点）、`test_tool_budget_rejected_before_execution`、`test_model_timeout`、`test_tool_timeout_and_cancellation`、`test_http_failures_are_sanitized`（4 个参数节点）；`test_runtime_baseline.py::test_worker_maps_outer_timeout_to_run_timeout`、`test_worker_preserves_runtime_fault_code`（2 个参数节点）、`test_worker_sanitizes_ordinary_exception_to_execution_error` | `model_round_limit`、`repeated_tool_call`、`empty_model_response`、`tool_call_limit`、模型/工具/外层超时、HTTP 错误与 worker 错误码均符合现状；合成 provider 标记未进入持久化结果 | 本地通过 |
| P0-UT-03 | Worker emit 持久化与 transient 分流；FR-1/FR-2 | `test_runtime_baseline.py::test_worker_model_delta_is_transient_and_ordinary_event_is_appended` | `model.delta` 只进入 notifier 且映射为 `k=delta`；`model.completed` 进入 Repository；finish 为 completed | 本地通过 |
| P0-UT-04 | 执行取消与 watcher/task 清理；FR-2/FR-4 | `test_runtime_postgres.py::test_cancellation_interrupts_inflight_model`；`test_runtime_engine.py::test_tool_timeout_and_cancellation` | 前者断言进行中模型进入 `finally`、Run 到 cancelled，并在 `finally` 中 `worker.stop()` 后 await worker task；后者断言工具 task 传播 `CancelledError` | 测试两轮通过；**限定证据**：证明上述模型中断、工具取消和 worker task 收束，未枚举全局 asyncio task/watcher，故不宣称所有 watcher 均无泄漏 |
| P0-UT-05 | 5 个合法 fixture、默认规范化与源不变；FR-3/AC-3 | `test_runtime_baseline_fixtures.py::test_fixture_manifest_covers_exact_files_and_all_valid_configs`；`test_agent_config_execution_compat.py::test_p0_it_08_legacy_raw_draft_publishes_normalized_v1`（2 个参数节点） | 5 个合法用例全部校验通过；minimal 的 16 项默认值逐项相等；两个 legacy 发布用例均断言源 fixture 字节不变 | 本地通过；两个 legacy 有显式源字节断言，其他合法 fixture 走只读加载；真实授权样本代表性仍 `pending_env`（P0-I2） |
| P0-UT-06 | 16 个非法/未知字段的精确结果；FR-3 | `test_runtime_baseline_fixtures.py::test_invalid_fixtures_declare_exact_pydantic_error_locations` | 16 个非法用例均抛 `ValidationError`，规范化后的完整 Pydantic `loc` 集合逐项相等；根错误 `[[]]` 与集合整数下标均保留 | 本地通过；不把未知 `engine` 的拒绝解释成未来映射批准 |
| P0-UT-07 | 7 文件清单一一对应、版本/覆盖/脱敏；FR-3/FR-6 | 同上 manifest 测试；只读核查 `backend/tests/fixtures/agent_execution_baseline/manifest.v1.json`；§5 P0-CM-03 扫描 | 目录恰为 manifest + 6 个 payload；各 payload 均有 `fixture_version=v1`、`covered_fields`、`covered_cases`、预期与来源/合成值政策；无孤立文件 | 本地通过；`production_samples=false`，不能替代真实样本评审 |
| P0-UT-08 | 冻结 ID、Run 术语、无 Worker Engine 分支；FR-5/AC-5 | `test_agent_config_execution_compat.py::test_p0_ut_08_frozen_identities_terminology_and_worker_neutrality` | 中英架构/Phase 1 设计/checklist 中 `(react,native,v1)`、`(local-test,scripted,v1)`、Run=一次 Execution、无双表/无 Engine 分支均匹配；AST 检查 Worker 无选择字段或 provider if | 本地通过；这是静态冻结证据，不是 Phase 1 已接线或已放行 |
| P0-UT-09 | JUnit 计数、outcome、耗时与缺失值；FR-6 | `test_runtime_baseline_tooling.py::test_summary_aggregates_leaf_suites_without_double_counting`、`test_summary_single_suite_classifies_all_outcomes_and_skip_reasons`、`test_summary_output_is_deterministic_and_mirrors_output_file`、`test_summary_rejects_invalid_structure`（7 个参数节点）、`test_summary_rejects_malformed_xml_with_concise_error` | leaf 汇总不重复；passed/failed/error/skipped/xfail/xpass 与原因完整；耗时保留；缺 tests、非法 time/tests、空身份、重复、非 leaf 和坏 XML 均明确 exit 2，缺失值不填 0 | 本地通过 |
| P0-UT-10 | 真正的节点级双跑比较；FR-6/AC-4 | `test_runtime_baseline_tooling.py::test_compare_reports_node_differences_and_count_metadata`、`test_compare_ignores_duration_only_changes`、`test_cli_subprocess_emits_json_and_node_diff_exit_code`；`/tmp/nexusdesk-phase0-compare.json` | 工具测试证明 added/missing/outcome/skip-reason 可检出、仅耗时变化可忽略、差异 exit 1；正式两份 JUnit 比较为 `identical=true`，added/missing/outcome_changes/skip_reason_changes 均 `[]` | 本地通过；不是早期 self-compare，也不是干净 CI 双跑 |

P0-UT-09/10 的工具回归现包含 7 个新增节点：`test_summary_classifies_pytest_strict_xpass_skipped_message`、`test_real_pytest_strict_xpass_is_classified_as_xpass`、`test_real_pytest_non_strict_xpass_requires_and_fails_log_audit`、`test_audit_log_cli_accepts_real_clean_pytest_log`、`test_audit_log_cli_rejects_real_pytest_log_without_summary_evidence`，以及 `test_audit_log_accepts_pytest_long_duration_terminal_summary`、`test_audit_log_rejects_malformed_long_duration_terminal_summary`。前 5 个固定 strict JUnit 分类、non-strict JUnit 限制与 `-rA` 日志 exit 0/1/2 语义；后 2 个固定真实 `(0:02:24)` 长耗时后缀及 malformed 输入拒绝。两轮独立 spec/quality 评审分别批准 XPASS 修复和终端解析修复；当前 `test_runtime_baseline_tooling.py` 共 23 个节点，全部纳入并通过本次 310 节点正式双跑。

## 4. 集成测试（P0-IT）逐条结果

| 编号 | 需求 / 溯源 | 具体测试节点或执行证据 | 实际结果 | 状态 / 边界 |
|---|---|---|---|---|
| P0-IT-01 | completed 生命周期；AC-1/AC-2 | `test_runtime_postgres.py::test_p0_it_01_queued_claim_completed_lifecycle_persists_exact_state` | queued/running/completed 的 owner、lease、时间、output、持久 history 与 3 个精确终态事件均相等；重复 finish 不改状态/事件 | 本地 PostgreSQL 通过 |
| P0-IT-02 | queued/running 取消；AC-2/FR-2 | `test_runtime_postgres.py::test_queue_expiration_and_cancel_without_worker`、`test_cancellation_wins_finish_race_and_event_replay`、`test_cancellation_interrupts_inflight_model` | queued 直接 cancelled；running 出现 cancel_requested 后迟到 completed 不覆盖，终态为 cancelled 且事件可重放；进行中模型被取消 | 本地 PostgreSQL 通过 |
| P0-IT-03 | 真实 Worker 三类失败；FR-2/FR-4 | `test_runtime_postgres.py::test_p0_it_03_real_worker_persists_sanitized_failure_terminal`（3 个参数节点） | `controlled_runtime_fault`、`run_timeout`、`execution_error` 三种失败均持久化精确终态/事件；合成 provider 原文不在事件、output、error_code 或 caplog | 本地 PostgreSQL 通过 |
| P0-IT-04 | lease/heartbeat/reaper 与 cancelled-with-error；AC-2 | `test_runtime_postgres.py::test_lost_worker_is_failed_and_cannot_publish_late_result`、`test_p0_it_04_reaper_cancelled_expired_running_lease_keeps_worker_lost`、`test_p0_it_04_manual_queued_cancel_flag_reaps_cancelled_with_queue_timeout` | 失租 heartbeat 为 lost，reap 后 `failed/worker_lost`，迟到结果无效；已请求取消的失租 running 为 `cancelled/worker_lost`；手工 queued 中间态为 `cancelled/queue_timeout` | 本地 PostgreSQL 通过；queued 中间态明确由 SQL 构造，不冒充公开 API 可达路径 |
| P0-IT-05 | 两种提交顺序与并发竞争；FR-2 | `test_runtime_postgres.py::test_p0_it_05_queued_cancel_and_reap_commit_orders`（2 个参数节点）、`test_p0_it_05_concurrent_queued_cancel_reap_has_one_terminal_transition` | cancel-first 为 cancelled，reap-first 为 `failed/queue_timeout`；并发只允许一个合法终态事件，重复 cancel/reap 不再改变状态或事件 | 本地 PostgreSQL 通过；并发终态允许集合是现状语义，不强行固定单一赢家 |
| P0-IT-06 | 重复 finish、迟到 append、排他 claim；AC-2/FR-4 | `test_runtime_postgres.py::test_p0_it_06_terminal_rejects_late_append_and_repeat_finish`、`test_p0_it_06_cancel_requested_rejects_append_and_forces_cancelled_finish`、`test_p0_it_06_expired_lease_rejects_append_and_finish`、`test_p0_it_06_wrong_owner_finish_and_append_do_not_write`、`test_concurrent_submit_and_exclusive_claim` | 终态/取消/失租/错误 owner 的非法写入均被拒绝；5 个并发 claim 仅 1 个成功；Run 状态与事件序列保持不变 | 本地 PostgreSQL 通过 |
| P0-IT-07 | 严格 SSE max、分页、transient 与 replay；FR-2/FR-4 | `test_runtime_postgres.py::test_p0_it_07_internal_sse_after_and_last_event_id_use_strict_max`、`test_p0_it_07_internal_sse_drains_more_than_200_events_before_terminal`、`test_p0_it_07_internal_sse_does_not_replay_transient_model_delta`、`test_p0_it_07_internal_sse_hides_terminal_tool_replay_and_advances_cursor` | `max(after,Last-Event-ID)` 边界正确；204 个事件可排空且 after=200 返回 201～204；delta 不重放；终态后专用 `tool.replay` 的 payload 被 SSE 隐藏且游标推进 | 本地 PostgreSQL 通过；P0-I4 的终态后 seq 消耗边界仍 P2/open，未安全修复 |
| P0-IT-08 | 两个 legacy 发布/v2/跨租户/queued 快照/稀疏限制；AC-3 | `test_agent_config_execution_compat.py::test_p0_it_08_legacy_raw_draft_publishes_normalized_v1`（2 个参数节点）、`test_later_draft_and_v2_do_not_rewrite_v1_or_cross_tenant_boundary`、`test_queued_run_keeps_v1_snapshot_after_v2_is_published`、`test_sparse_raw_version_exposes_direct_snapshot_tool_names_limitation` | 两个 raw legacy draft 均发布为完整规范化 v1，v2 不改写 v1；跨租户分别得到既定 404；queued Run 保留 v1；手工稀疏 raw version 的直接 snapshot 抛 `KeyError("tool_names")` | 公开链路本地通过；P0-I7 存储阶段限制仍 P2/open，真实样本仍 `pending_env` |
| P0-IT-09 | 完成 hook、mock ReAct、summary/memory/injection；FR-1/FR-4 | `test_runtime_postgres.py::test_p0_it_09_completion_hooks_run_only_for_completed_runs`、`test_worker_runs_real_graph_and_persists_events`；`test_memory_postgres.py::test_p1_it_01_truncation_dispatches_task_and_summary_is_written`；`test_memory_customers_postgres.py::test_p2_it_08_injection_sits_between_summary_and_history`；`test_memory_injection_postgres.py::test_p6_it_01_run_writes_one_row_per_injected_item`、`test_p6_it_02_event_counts_and_item_ids_match_detail_rows` | completed/failed/cancelled 三态仅 completed 调用完成 hook 并写 assistant/history；真实 graph 持久事件完成；summary 任务与写入、memory 注入位置、逐 item 明细和事件计数均符合断言 | 本地 PostgreSQL 通过；不需要外部 provider |
| P0-IT-10 | 正式双跑、覆盖率与环境产物；AC-4/AC-6 | §2 全部正式产物；`baseline/regression-baseline.md` §5 的精确命令；`/tmp/nexusdesk-phase0-compare.json`、`/tmp/nexusdesk-phase0-coverage-diff.json` | 同一未提交树、两个独立空库、25 套件两轮均 310 passed，节点完全一致；两轮审计 310 条且零 XPASS，覆盖率与环境信息已保存 | **修正后本地双跑门禁通过**；同一已提交产物的干净 CI 双跑与链接仍 `pending_env`，不构成就 AC-4 的无限制完整验收 |

## 5. 通用核对项（P0-CM）逐条结果

| 编号 | 核对项 / 溯源 | 执行或产物证据 | 实际结果 | 状态 / 边界 |
|---|---|---|---|---|
| P0-CM-01 | 提交与证据完整性；FR-1/AC-1 | 两轮 `.base-commit.txt`、`.tree-before.txt`、`.tree-after.txt`、`.metadata.txt`；`/tmp/nexusdesk-phase0-identity-checks.json`；本报告逐条节点映射 | base + 确定性树哈希完整标识被测未提交树，四项身份检查全 true；报告保留具体节点/产物 | **本地证据通过；`pending_commit`**：未请求也未创建最终产物提交，故没有最终 committed-artifact SHA，不能伪称 base HEAD 就是该 SHA |
| P0-CM-02 | 无生产执行/迁移漂移；FR-3/范围 | T9 只读执行 `git diff --name-only c6c47dec39025ebd4d1176c1e9925bac9c99c4fd -- backend/src backend/migrations`，并以同路径范围执行 `git ls-files --others --exclude-standard` | 两条命令输出均为空；现有变更中的后端执行相关文件是测试、基线脚本与 dev 测试依赖，不是生产执行重构或迁移 | 本地通过 |
| P0-CM-03 | fixture、正式输出与回填文档敏感信息扫描；FR-3/非功能 | `/tmp/nexusdesk-phase0-doc-backfill-secret-scan.json`；manifest 合成值政策 | 对 7 个 fixture、两轮 log/XML/summary/audit/coverage JSON/base/tree/metadata、共享 identity/compare/coverage-diff/environment/wrapper/compare-gate 及八份回填文档共 40 文件，扫描数据库 URL、私钥、GitHub/OpenAI 风格 token、AWS key、非测试 Bearer 和凭据赋值等 8 类模式，`findings=[]`、`missing_files=[]` | 本地定向扫描通过；不是对所有秘密形式的数学证明，真实样本授权/代表性仍 `pending_env` |
| P0-CM-04 | 本地节点确定性；AC-4 | 两轮 summary 与 audit；`/tmp/nexusdesk-phase0-compare.json`；`/tmp/nexusdesk-phase0-coverage-diff.json` | 310 个节点均 passed，added/missing/outcome/skip-reason 无差异，两轮审计均 310 条且零 XPASS；耗时差不参与等价 | 修正后本地节点与 XPASS 审计门禁通过。覆盖率行集合并非逐行等价，观察见 §6，不能据此证明或隐瞒 flaky |
| P0-CM-05 | Phase 1 入口清单；FR-5/FR-6/AC-6 | 本报告 ID、计数、耗时、覆盖率、缺陷与边界；`baseline/refactoring-checklist.md` §1～§5 的冻结标识、通用门禁、Phase 1～7 映射和入口清单；`07-acceptance-report.md` | 本地记录已覆盖上述资料；两轮未暴露新的 P0/P1 实现缺陷 | **本地清单证据已登记，Phase 1 入口未批准**：07 已创建并明确为“待验收 / 未批准”；P0-I1 CI、P0-I2 真实样本、最终提交证据与人工验收/签字未完成；不虚构最终 P0/P1 验收计数，不给予有条件通过，不放行 Phase 1 |

## 6. 回归、节点比较与覆盖率观察

- 两轮均使用同一 25 套件有序范围和同一确定性树身份；310 个唯一节点的集合及 outcome 完全一致，JUnit 的 failures/errors/skipped/xfail/xpass 均为 0。non-strict XPASS 由两轮 `-rA` 日志独立审计，正式逐轮及比较门禁重新执行均 exit 0、310 条记录、零 XPASS。
- `/tmp/nexusdesk-phase0-compare.json` 是 Run 1 JUnit 对 Run 2 JUnit 的真实比较：`identical=true`，`added=[]`、`missing=[]`、`outcome_changes=[]`、`skip_reason_changes=[]`，compare exit 0。JUnit time 从 145.281s 到 145.353s 的变化不属于等价判据，也不单独证明 flaky。
- 覆盖率不是逐行等价：Run 1 为 9886/18534，Run 2 为 9900/18534，净多 14 条已覆盖行。`/tmp/nexusdesk-phase0-coverage-diff.json` 显示 8 个文件的 executed-line 集合存在差异：`channel/service.py`、`memory/decay.py`、`memory/service.py`、`open_platform/routes.py`、`open_platform/service.py`、`open_platform/webhooks.py`、`model_gateway/catalog.py`、`model_gateway/governance.py`。每文件的 run1-only/run2-only 精确行号保留在该 JSON。
- 上述覆盖率差异与节点全一致同时如实保留；它是覆盖率观察，不是 flaky 测试证明，也不允许被 53.34%/53.42% 的两位小数展示或全绿节点总数掩盖。

## 7. 正式执行中发现的缺陷

修正后的两轮正式执行**未暴露新的 P0/P1 实现缺陷**。这句话只描述两轮实际结果，不消除 CI、真实样本、最终提交或人工验收证据门槛，也不给出未经后续验收核定的最终 P0/P1 开放数量。以下工具门禁缺陷单独保留，不混入生产实现失败率：

| ID | 发现环节 | 实际缺陷与影响 | 修复、评审与回归 | 当前处置 |
|---|---|---|---|---|
| P0-D1 | 最终工具评审 | JUnit 对 strict XPASS 的分类不足，且 non-strict XPASS 在 JUnit 中只是普通 passed；旧 303 节点双跑没有逐轮日志审计，不能满足修正后的零 XPASS 证据要求 | 修正 strict JUnit 分类并增加 `-rA` fail-closed 审计；新增 5 个真实 pytest/审计回归，第一轮独立 spec 与 quality 评审均批准 | 已修复；旧 303 节点产物保留为被取代历史，当前 310 节点双跑两轮审计通过 |
| P0-D2 | 修正后第一次 Run 1 比较前审计 | pytest exit 0、308 个 JUnit 节点全 passed、time 144.515s、树稳定，但真实终端 `308 passed in 144.54s (0:02:24)` 被审计器以 exit 2 拒绝；没有正式 audit JSON，Run 2/compare 未启动。**这不是测试失败，也不是通过的正式轮次** | 解析器接受 `(H:MM:SS)` 并继续拒绝 malformed 输入；新增 2 个回归，第二轮独立 spec 与 quality 评审均批准。原日志事后诊断 exit 0、308 条、零 XPASS，但未提升为正式证据 | 已修复；该尝试归档隔离，随后以新 Run 1 空库重启并完成当前 310 节点双跑 |

被取代的 303 节点产物归档为 `/tmp/nexusdesk-phase0-superseded-20261107-3d4f9b06/`；其 tree 为 `sha256=3d4f9b06cbdd5de89250d888c0ea695d145e6051d4cc995c64107947fc14e729 files=1014`。所选源没有实际 xfail 标记，但两轮均无 audit 产物，只能作为该旧树的 JUnit 历史，不能作为修正后门禁证据。被拒绝的 308 节点 Run 1 归档为 `/tmp/nexusdesk-phase0-rejected-run1-20261107-19548c1d/`，tree 为 `sha256=19548c1df1591a9fb084e4bb178694d782a50c74c870d0ab4c936975e42d11b9 files=1018`，UTC 为 2026-11-07T21:20:28Z～21:22:53Z。

另保留一项非正式历史：早期 24 套件演练中 pytest 已完成并生成完整产物，随后 zsh 包装器因 `read-only variable: status` 失败。该轮不是正式双跑；正式模板已改用 `test_rc`，当前两轮 pytest/summary/audit/tree/wrapper 退出码均为 0。此历史不能与正式失败率混合，也不能删除。

## 8. 残留风险与未决项

| ID | 级别 / 状态 | 实际边界与处置 |
|---|---|---|
| P0-I1 | `pending_env` | 同一已提交产物的干净 CI 双跑、原始 artifact 与链接尚不存在；研发负责人 + QA 在 Phase 1 入口评审前补证。本地双跑不替代 CI AC-4 |
| P0-I2 | `pending_env` | 未提供经授权的真实历史发布快照；现有 fixture 仅为合成字段形状。Agent 配置代表 + 安全代表须补样或形成正式范围裁定 |
| P0-I3 | P2 / open | 开放平台 stream 注释称无 token delta，实际会输出可见文本 delta；开放平台后端 owner 在 Phase 2 前处置 |
| P0-I4 | P2 / open | 专用 `tool.replay` 可在终态后消耗 seq；专门 SSE 测试已证明 payload 隐藏与游标推进，但安全/行为边界未修复或裁定，最迟 Phase 6 安全门槛前处理 |
| P0-I5 | P3 / open | 既有 `seed_memory_*` 全量格式检查差异保留给对应脚本 owner；不在 Phase 0 混入无关批量格式化 |
| P0-I6 | 环境说明 | ignored 旧目录/`__pycache__` 会干扰本地架构扫描；干净目标 worktree 门禁通过，不删除用户文件制造干净结果 |
| P0-I7 | P2 / open | 手工极稀疏 raw version 虽通过 AgentConfig 输入校验，直接 `snapshot()` 抛 `KeyError("tool_names")`；AgentConfig + Runtime owner 在 Phase 3 前解决或正式裁定并补回归 |

## 9. CI 证据与验收边界

- 既有 CI run <https://github.com/GroundedCoreAI/nexusdesk/actions/runs/42227604191> 仅是 base 现状后端单次支持证据，head 为 `16aed12eb095f29bed5c536b5fcbf68e510136c4`；不包含本阶段新增测试、覆盖率、JUnit artifact 或双跑比较。
- 含 Phase 0 产物的提交尚未创建、推送或运行 CI；正式干净 CI 双跑及链接保持 `pending_env`。本报告没有声称任何新 CI 成功。
- 本报告不是 `07-acceptance-report.md`，没有人工签字，也不把本地测试通过改写成 AC-1～AC-6 全部无限制验收通过。Phase 0 完整验收和 Phase 1 入口仍须完成 §8 证据门槛与后续人工验收。

## 10. 结论

**修正后的本地正式双跑 310 节点比较与两轮 XPASS 日志审计通过；完整 Phase 0 验收 / Phase 1 入口尚未批准。**

## 附录 A 正式产物索引

| 产物 | Run 1 | Run 2 |
|---|---|---|
| 原始日志 | `/tmp/nexusdesk-phase0-run1.log` | `/tmp/nexusdesk-phase0-run2.log` |
| JUnit | `/tmp/nexusdesk-phase0-run1.xml` | `/tmp/nexusdesk-phase0-run2.xml` |
| summary | `/tmp/nexusdesk-phase0-run1.summary.json` | `/tmp/nexusdesk-phase0-run2.summary.json` |
| XPASS 日志审计 | `/tmp/nexusdesk-phase0-run1.xpass-audit.json` | `/tmp/nexusdesk-phase0-run2.xpass-audit.json` |
| coverage JSON | `/tmp/nexusdesk-phase0-run1.coverage.json` | `/tmp/nexusdesk-phase0-run2.coverage.json` |
| coverage 数据 | `/tmp/nexusdesk-phase0-run1.coverage` | `/tmp/nexusdesk-phase0-run2.coverage` |
| base 元数据 | `/tmp/nexusdesk-phase0-run1.base-commit.txt` | `/tmp/nexusdesk-phase0-run2.base-commit.txt` |
| tree-before | `/tmp/nexusdesk-phase0-run1.tree-before.txt` | `/tmp/nexusdesk-phase0-run2.tree-before.txt` |
| tree-after | `/tmp/nexusdesk-phase0-run1.tree-after.txt` | `/tmp/nexusdesk-phase0-run2.tree-after.txt` |
| metadata | `/tmp/nexusdesk-phase0-run1.metadata.txt` | `/tmp/nexusdesk-phase0-run2.metadata.txt` |

上表是当前修正后正式产物索引；两份审计均存在且 exit 0，比较门禁在节点比较前重新执行并确认相同结果。事后文档回填未重跑、覆盖或替换这些正式产物。

共享产物：

- `/tmp/nexusdesk-phase0-identity-checks.json`
- `/tmp/nexusdesk-phase0-compare.json`
- `/tmp/nexusdesk-phase0-coverage-diff.json`
- `/tmp/nexusdesk-phase0-environment.log`
- `/tmp/nexusdesk-phase0-compare-gate.log`
- `/tmp/nexusdesk-phase0-doc-backfill-secret-scan.json`（本次只读扫描，不属于两轮正式 pytest 产物）
- `/tmp/nexusdesk-phase0-t9-secret-scan.json`（T9 历史只读扫描，不属于两轮正式 pytest 产物）
