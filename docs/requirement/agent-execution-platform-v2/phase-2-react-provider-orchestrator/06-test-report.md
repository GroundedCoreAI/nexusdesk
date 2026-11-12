# Phase 2 · React Provider 与执行编排器 — 测试报告

> 状态：已完成（本地功能出口通过；生产性能子指标 `pending_env`）
> 创建：2026-11-11
> 依据：`04-test-plan.md`（P2-UT-01～24、P2-IT-01～20、P2-CM-01～08）、`05-acceptance-plan.md`、`03-technical-design.md`、`08-implementation-breakdown.md`（R15/R16、T8）
> 执行：T8 正式测试执行代理；日期：2026-11-11

## 1. 测试范围与环境

**范围**：本轮重新执行 04 的全部主用例及受影响回归，覆盖 Context/Request UUID、ReactAdapter、双 emit、ack/背压/no-stream、Orchestrator、Worker、错误/取消/超时/Lease、内部/Open SSE、真实 Memory、配置/混合 Worker/回滚、迁移与本地 test-double 性能采样。没有执行全量 `pytest`，没有创建种子或 07，没有把本报告当作 T9 正式验收。

| 环境 | 配置 | 用途 |
|---|---|---|
| 本机 | Darwin 27.0.0；Python 3.11.9；uv 0.11.3 | 非 PG 单测/集成、Ruff、架构与差异检查 |
| 独立 Docker PostgreSQL | `pgvector/pgvector:pg17`；容器 `nexusdesk-phase2-t6b-pg17-2b1d85c1afb9` | 真实 asyncpg、Repository、SSE、Memory、混合 Worker、Lease 与迁移 |
| ASGI | `httpx.ASGITransport` 与实际 FastAPI 路由 | R15 内部/Open 游标、状态码、错误体、重放和脱敏 |
| 模型/工具 | demo/mock、可编程 Runtime/Adapter、受控 Event/gate | 确定性新旧对等、错误、取消、背压和性能方法样本 |
| 凭据 | 仓库外 mode-0600 env 文件静默注入 | 仅注入连接配置；日志和报告不记录连接串或凭据 |

> **证据生命周期（重要）**：`/Users/jackchow/.claude/jobs/a2066544/tmp` 是本 job 的本地临时目录，不是持久仓库证据区。本轮最终资源清理后，本文指向该目录的原始日志、节点清单和性能 JSON 链接将失效，原始证据不可复核；本报告附录仅保留关键结果摘要，不冒充原始证据长期归档。本轮未产生 CI artifacts 或其他经批准的持久归档，不暗示证据已经归档。

原 T6 数据库、容器和卷均保留。CM01 另建临时空库 `phase2_t8_cm01_20261111_01`，验证后仅删除该临时库；复查数据库数量为 0。证据总索引见 [T8 evidence index](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-evidence.md)。

**skip 说明**：Memory 六套件共 158 个节点，实际 **156 passed, 2 skipped**。跳过项为 `test_memory_events_postgres.py::test_p3_ut_02_probe_text_without_vector_column` 和 `test_p3_ut_03_vector_enabled_true_without_column_still_text`；当前 PG17 有 embedding 列，而这两项分别要求无 embedding 列的降级环境，原因为 `degraded-path assertion needs a database without the embedding column` 与 `needs a database without the embedding column`。两项均不计通过，也不属于未覆盖的 Phase 2 主用例。

## 2. 执行总览

| 项 | 结果 | 证据 |
|---|---|---|
| 非 PG `p2_` 主选择 | 52 passed, 170 deselected in 3.29s | [E01](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-logs/nonpg-p2-selection.log) |
| 两个核心非 PG 文件 | 205 passed in 3.21s | [E02](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-logs/nonpg-core-two-files.log) |
| 受审 18 文件集合的 `not postgres` 选择（17 个文件含非 PG 节点） | 1032 passed, 14 deselected in 5.51s | [E03](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-logs/nonpg-full-reviewed-file-set.log) |
| 26 个新 T6b PG 选择 | 26 passed, 89 deselected in 13.17s | [E05](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-logs/pg-new-26.log) |
| 完整 `test_runtime_postgres.py` | 45 passed in 9.89s | [E06](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-logs/pg-runtime-full.log) |
| Open + agent-config PG 回归 | 17 passed in 14.09s | [E07](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-logs/pg-open-agent-config.log) |
| 六个 Memory 套件 | 156 passed, 2 skipped in 78.06s | [E08](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-logs/pg-memory-six-suites.log) |
| T7 混合/回滚/存量行/settings/path-log 选择 | 23 passed in 1.88s | [E09](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-logs/pg-t7-mixed-rollback-existing-logs.log) |
| 完整 `test_agent_model_required.py` 真实 PG 补执行 | 2 passed in 1.60s | [E19](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-logs/pg-agent-model-required.log) |
| `uv run ruff check src tests` | All checks passed | [E13](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-logs/ruff-check.log) |
| `uv run ruff format --check src` | 全树基线偏差：32 个既存未改动文件需重排，280 个已符合；本阶段 12 个源文件另行检查全部通过 | [E14a](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-logs/ruff-format.log)、[E14b](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-logs/ruff-format-phase2-files.log) |
| 架构门禁 | 原始树仅因四个既存 ignored legacy 根失败；干净导出排除同四根后通过 | [E15](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-logs/architecture-clean-export.log) |
| 临时 Git metadata `diff --check` | 通过，原 `.git` 未修改 | [E16](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-logs/git-diff-check.log) |
| CI | 未执行；本轮无 push/PR，无 CI URL | §9 |

E01/E02/E03 相互重叠；E05/E06/E07/E08/E09/E19 也存在重叠。上述计数用于证明实际执行，**不得相加为独立覆盖数**。E03 的 14 个 deselect 均为 postgres 标记节点，其中 12 个由 E07 补足、`test_agent_model_required.py` 的 2 个由 E19 补足；其他 deselect 均由完整文件或明确选择覆盖。

## 3. 单元测试（P2-UT）逐条结果

下表“数量”是 pytest 参数展开后的实际用例数；未标参数的为 1。除 UT16 的两个 PG 节点由 E19 补足外，非 PG 行由本轮 E01/E02/E03 的新鲜执行覆盖；其他 PG 相关行另由 E05/E06/E09 覆盖。

| 编号 | 用例 | 精确测试位置（参数展开数） | 环境 | 结果与新鲜关键证据 |
|---|---|---|---|---|
| P2-UT-01 | Context/Request UUID 与 Agent 身份 | `backend/tests/test_execution_orchestrator.py` 附录 B 的 15 个不重复精确函数，共 33 例 | 本机 | **通过**；精确 stdlib UUID、子类受控转换、原 row/row.id 保留、快照畸形/nil/伪造拒绝、安全静态 `INVALID_REQUEST`、普通异常脱敏及 CancelledError/KeyboardInterrupt 重抛均通过；E02/E03 |
| P2-UT-02 | React 身份、能力与 start | `backend/tests/test_react_engine_adapter.py::TestReactAdapter::test_capabilities_start_stream_collect_success`(1)、`::test_prestart_errors_precede_handle_and_preserve_retryability`(1)、`::test_request_identity_mismatch_fails_before_handle`(1)；`backend/tests/test_execution_orchestrator.py::test_orchestrator_uses_fresh_adapters_and_isolates_concurrent_runs`(1) | 本机 | **通过**；react/native/v1、四项 true 能力、Handle UUID、单 active execution、重复 start 拒绝和 fresh 实例隔离；E02/E03 |
| P2-UT-03 | 双 emit、首发握手、start→stream→collect | `backend/tests/test_react_engine_adapter.py::test_double_emit_first_gate_runtime_inputs_and_private_outcome`(1)；`backend/tests/test_execution_orchestrator.py::test_orchestrator_fixed_selector_ack_order_and_single_private_outcome_collection`(1)；`backend/tests/test_react_engine_adapter.py::TestReactAdapter::test_multiple_events_preserve_order_payload_and_empty_stream_terminates`(1) | 本机 | **通过**；同 runner/row/runtime_emit spy、首事件不丢、`yield→await worker_emit→ack`、唯一 completed Result、私有 history/dropped 与空 usage；E02/E03 |
| P2-UT-04 | 空输出、dropped 与 usage 打包 | `backend/tests/test_execution_orchestrator.py::test_completed_outcome_carries_memory_values_and_react_v1_empty_usage`(1)、`::test_non_completed_outcomes_never_carry_memory_values`(2)、`::test_private_outcome_has_no_public_serialization_surface`(1)；`backend/tests/test_runtime_baseline.py::test_worker_on_completed_outcome_preserves_memory_row_history_and_dropped_verbatim`(1) | 本机 | **通过**；React v1 公共/私有 usage 均为 `{}`，非成功不写 Memory，history/dropped 原样保留且无私有序列化扩展；E02/E03 |
| P2-UT-05 | 事件映射与伪造隔离 | `backend/tests/test_react_engine_adapter.py::test_double_emit_first_gate_runtime_inputs_and_private_outcome`(1)、`::test_malformed_reserved_and_non_json_events_fail_before_worker_emit`(8)；`::TestReactAdapter::test_duplicates_late_events_gaps_and_timestamps_follow_sequence_rules`(1)、`::test_same_event_id_with_different_content_is_never_repaired`(1) | 本机 | **通过**；model/knowledge/memory/extension 原名同 payload，伪造 run.*/tool.replay/非 JSON 在 worker_emit 前 protocol_error，UUID/UTC/局部 seq 正确；E02/E03 |
| P2-UT-06 | 全来源错误、未来 code 与 timeout | `backend/tests/test_react_engine_adapter.py` 附录 F 的 21 个函数、58 个参数展开例：8 个显式函数 34 例，加三组对抗函数 5 函数/5 例、5 函数/10 例、3 函数/9 例 | 本机 | **通过**；27 项 Phase 0 矩阵、未知 RuntimeFault 私有原 code/公共 internal_error、未知普通异常 execution_error、双 timeout、描述符/属性异常脱敏与控制流重抛；E02/E03 |
| P2-UT-07 | cancel、aclose、竞争与清理 | `backend/tests/test_react_engine_adapter.py::TestReactAdapter::test_cancel_wins_gate_race_and_suppresses_late_events_and_success`(1)、`::test_success_wins_gate_race_and_is_never_retroactively_cancelled`(1)、`::test_repeated_concurrent_cancel_closes_stream_and_collectors`(1)、`::test_early_aclose_cleans_owned_tasks_and_does_not_permit_replay`(1)、`::test_pending_anext_is_woken_by_aclose_without_external_cancel`(1)；`backend/tests/test_react_engine_adapter.py::test_cancel_blocked_producer_and_pending_consumer_suppresses_late_completion`(1) | 本机 | **通过**；内部 first-terminal-wins、cancel 幂等、迟到成功抑制、aclose 唤醒 put/get、closed 不 replay、owned tasks done；E02/E03 |
| P2-UT-08 | 固定 selector 与无效组合 | `backend/tests/test_execution_orchestrator.py::test_resolution_failures_return_safe_failed_outcomes_without_fallback`(6)、`::test_orchestrator_fixed_selector_ack_order_and_single_private_outcome_collection`(1)、`::test_shared_composition_registers_fixed_descriptors_without_per_run_execution`(1) | 本机 | **通过**；未知版本/未注册/禁用组合安全失败，无 latest、legacy 或其他 Engine 回退，请求不能覆盖生产 selector；E02/E03 |
| P2-UT-09 | ack/Outcome 协议与各阶段异常 | `backend/tests/test_execution_orchestrator.py::test_acknowledging_event_stream_is_runtime_checkable_and_detected_structurally`(1)、`::test_non_async_acknowledgement_capabilities_are_rejected`(5)、`::test_outcome_collecting_adapter_is_private_runtime_checkable_and_async_verified`(1)、`::test_protocol_free_public_result_fallback_is_deterministic`(6)、`::test_each_execution_stage_failure_cleans_stream_and_returns_safe_failed`(5)、`::test_append_cancelled_error_is_not_acknowledged_and_rethrows_after_cleanup`(1)、`::test_collect_call_failures_are_execution_error_without_second_collection`(4)；`backend/tests/test_react_engine_adapter.py::test_collect_outcome_completed_reuses_terminal_path_and_keeps_public_result_clean`(1)、`::test_collect_outcome_failed_preserves_unknown_runtime_fault_legacy_code`(1)、`::test_collect_outcome_cancelled_has_no_code_and_handle_validation_is_shared`(1) | 本机 | **通过**；真异步/描述符 fail-closed、React 私有 collect 仅一次、LocalTest 固定回退、append CancelledError 不 ack 且重抛、drain/collect/finish 唯一；E02/E03 |
| P2-UT-10 | Worker 开关与 fingerprint | `backend/tests/test_runtime_baseline.py::test_worker_off_with_injected_orchestrator_uses_only_legacy`(1)、`::test_worker_on_never_touches_legacy_factory_or_runtime`(1)、`::test_worker_on_without_orchestrator_fails_safely_without_legacy_fallback`(1)、`::test_worker_fingerprint_check_precedes_both_execution_paths`(2)；`backend/tests/test_execution_orchestrator.py::test_runtime_fingerprint_excludes_only_the_orchestrator_rollout_flag`(1) | 本机 | **通过**；off/on 路径互斥，on 失败不兜底，configuration_changed 一致，flag 不进 fingerprint；E02/E03 |
| P2-UT-11 | Outcome→finish 映射 | `backend/tests/test_runtime_baseline.py::test_worker_on_completed_outcome_preserves_memory_row_history_and_dropped_verbatim`(1)、`::test_worker_on_non_completed_outcomes_have_no_memory_or_completion_values`(2)、`::test_worker_on_ordinary_execution_failures_are_safely_finished`(3)、`::test_worker_on_external_cancellation_cleans_orchestrator_and_finishes_cancelled`(1)；`backend/tests/test_execution_orchestrator.py::test_worker_source_has_no_concrete_engine_branch_and_composition_injects_only_when_on`(1) | 本机 | **通过**；completed/failed/cancelled output/error_code 正确，仅成功传 Memory，Repository finish 唯一，Worker 无 Engine 分支；E02/E03 |
| P2-UT-12 | Memory 输入/dropped 新旧传递 | `backend/tests/test_runtime_baseline.py::test_p2_it03_truncation_summary_customer_memory_and_reasoning_match_legacy`(1)、`::test_worker_on_completed_outcome_preserves_memory_row_history_and_dropped_verbatim`(1)、`::test_worker_on_non_completed_outcomes_have_no_memory_or_completion_values`(2)；`backend/tests/test_execution_orchestrator.py::test_runtime_memory_reinforce_is_immediately_visible_on_original_worker_row`(1) | 本机 | **通过**；summary/customer_memory/history/dropped 对等，失败/取消不写回，原 row 可见 reinforce；E02/E03 |
| P2-UT-13 | Settings 默认与环境覆盖 | `backend/tests/test_execution_orchestrator.py::test_execution_orchestrator_settings_default_and_process_lifetime`(1)、`::test_execution_orchestrator_settings_parse_environment`(4)、`::test_execution_orchestrator_settings_reject_invalid_environment`(1) | 本机 | **通过**；默认 false，true/false/1/0 正确，非法值拒绝，既有实例不随后续环境变化；E01/E02/E09 |
| P2-UT-14 | 依赖方向与公开序列化 | `backend/tests/test_execution_orchestrator.py::test_t2_core_modules_do_not_import_applications_business_or_react_adapter`(1)、`::test_public_result_schema_has_no_t2_private_or_engine_metadata_extensions`(1)、`::test_private_context_has_no_emit_or_public_serialization_surface`(1)、`::test_private_outcome_has_no_public_serialization_surface`(1)、`::test_worker_source_has_no_concrete_engine_branch_and_composition_injects_only_when_on`(1)；干净导出 `scripts/check_architecture.py` | 本机/静态 | **通过**；Core/Worker 依赖边界、Context/Outcome/Result 公开面不变，干净导出架构门禁通过；E02/E03/E15 |
| P2-UT-15 | ContextVar 并发、嵌套与复位 | `backend/tests/test_execution_orchestrator.py::test_scope_captures_context_into_new_object_without_later_contextvar_reads`(1)、`::test_nested_scope_restores_outer_context_and_finally_clears_it`(1)、`::test_scope_resets_after_resolve_failure_without_leaking_raw_context`(1)、`::test_missing_or_wrong_context_fails_safely`(1)、`::test_context_scope_is_isolated_between_concurrent_tasks`(1)、`::test_react_adapter_factory_synchronously_captures_fresh_context_without_running_runtime`(1)；`backend/tests/test_react_engine_adapter.py::test_adapter_never_reads_contextvar_after_explicit_capture`(1) | 本机 | **通过**；并发隔离、嵌套恢复、解析/工厂异常 finally reset、缺失/错误 Context 安全失败，Adapter 创建后不读 ContextVar；E02/E03 |
| P2-UT-16 | 多 Run fresh 实例与私有隔离 | `backend/tests/test_execution_orchestrator.py::test_orchestrator_uses_fresh_adapters_and_isolates_concurrent_runs`(1)；`backend/tests/test_react_engine_adapter.py::TestReactAdapter::test_deterministic_fresh_runs_have_no_cross_instance_high_water`(1)；`backend/tests/test_react_engine_adapter.py::test_parallel_emit_preserves_sequence_and_queue_order_under_capacity_one`(1)；`backend/tests/test_agent_model_required.py::test_missing_model_draft_publish_legacy_run_and_rollback`(1)、`::test_captured_unconfigured_run_never_uses_default`(1) | 本机 + PG17 | **通过**；queue/runner/result/gate/row/history/emit 不共享，ack 限本 execution；两个真实 PG 节点分别证明缺模型发布/旧版本运行/回滚保持 agent_model_required，以及已捕获未配置 Run 不调用默认模型；E02/E03/[E19](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-logs/pg-agent-model-required.log) |
| P2-UT-17 | 容量 1、慢投递与结构化 ack | `backend/tests/test_react_engine_adapter.py::test_capacity_one_slow_delivery_backpressure_and_exactly_once_ack`(1)、`::test_ack_rejects_no_inflight_wrong_identity_and_cross_execution_then_aborts`(1)、`::test_settled_ack_idempotence_is_active_only_and_terminal_releases_identities`(1)；`backend/tests/test_execution_orchestrator.py::test_orchestrator_fixed_selector_ack_order_and_single_private_outcome_collection`(1) | 本机 | **通过**；裸 yield 不结算，仅 worker_emit 成功后 exactly-once ack；重复已结算幂等，错误身份/跨 Run/无 in-flight abort；E02/E03 |
| P2-UT-18 | no-stream、状态机与终态发布门 | `backend/tests/test_react_engine_adapter.py::test_no_stream_suppression_has_no_replay_and_unacked_event_gates_result`(1)、`::test_emit_after_successful_return_is_suppressed_while_first_event_awaits_ack`(1)、`::test_blocked_emitter_wakes_on_producer_finished_without_joining_drained_events`(1)；`::TestReactAdapter::test_terminal_visibility_never_precedes_queued_or_active_stream_events`(1)、`::test_claimed_empty_stream_does_not_block_successful_collection`(1)、`::test_delivered_only_event_does_not_require_an_extra_poll_before_result`(1) | 本机 | **通过**；never-claimed gate、显式 suppression、无 replay、未 ack 不发布终态、空闲 claimed stream 可 collect、closed/terminal 安全结束；E02/E03 |
| P2-UT-19 | collect/stream 竞争与 collector 取消 | `backend/tests/test_react_engine_adapter.py::TestReactAdapter::test_immediate_concurrent_and_repeated_collectors_share_result`(1)、`::test_one_cancelled_collector_does_not_cancel_shared_execution`(1)、`::test_lone_collector_cancellation_cleans_owned_work_before_propagation`(1)、`::test_concurrent_second_consumer_and_claim_after_aclose_are_rejected`(1)；`backend/tests/test_react_engine_adapter.py::test_collect_outcome_shared_collectors_and_lone_cancellation_match_public_semantics`(1) | 本机 | **通过**；先到先赢、collectors 唯一相等 Result、共享 collector shield、单独 no-stream 取消清理后重抛；E02/E03 |
| P2-UT-20 | stream/protocol/emit/Notifier 异常边界 | `backend/tests/test_react_engine_adapter.py::test_worker_emit_failure_and_append_cancellation_have_distinct_cleanup`(1)、`::test_swallowed_notifier_delta_failure_acks_but_other_emit_failure_fails`(1)、`::test_safe_worker_emit_exception_abort_still_uses_internal_execution_error`(1)、`::test_taskgroup_failures_preserve_prior_events_and_stable_error_mapping`(3)；`::TestReactAdapter::test_stream_errors_are_safe_for_stream_and_all_collectors`(6) | 本机 | **通过**；runner 错误安全传播并发布 failed，普通 emit abort/aclose，指定 Notifier 已吞 delta 失败正常 ack，其他异常失败且任务清理；E02/E03 |
| P2-UT-21 | 公共 Adapter 25 函数精确复用/替代 | `backend/tests/test_react_engine_adapter.py::TestReactAdapter` 附录 C 的 25 个精确函数，共 34 例；`backend/tests/test_react_engine_adapter.py::test_public_contract_has_exactly_nineteen_reuses_and_six_private_replacements`(1) | 本机 | **通过**；19 个原函数逐项继承复用（28 个参数展开例），6 个同名目的私有替代（6 例），流式 harness 显式 `anext→worker_emit→ack`；E02/E03 |
| P2-UT-22 | 串行/并行 parity 与 canonicalizer | `backend/tests/test_execution_orchestrator.py::test_p2_ut22_serial_canonicalizer_normalizes_only_documented_instance_fields`(1)、`::test_p2_ut22_model_call_messages_prompt_content_and_business_remain_diffs`(4)、`::test_p2_ut22_serial_business_order_sequence_usage_and_replay_remain_diffs`(9)、`::test_p2_ut22_rejects_wrong_types_and_negative_durations_before_normalizing`(8)、`::test_p2_ut22_rejects_missing_model_timing_fields`(3)、`::test_p2_ut22_parallel_tools_compare_by_call_id_and_preserve_model_rounds`(1)、`::test_p2_ut22_parallel_rejects_completion_before_start_and_round_movement`(1)、`::test_p2_ut22_unowned_parallel_events_are_per_round_multisets_not_global`(1)，共 29 例 | 本机 | **通过**；严格字段校验、model_calls/业务 ID/参数/结果/output/error/usage 保持差异，raw_latency 另存，call_id 偏序与按轮 multiset 正确；E01/E02/E03 |
| P2-UT-23 | monitor_failure、失租、stale append/finish 与提交顺序 | `backend/tests/test_runtime_baseline.py::test_worker_on_monitor_cancels_the_same_orchestrator_task`(2)；`backend/tests/test_execution_orchestrator.py::test_append_cancelled_error_is_not_acknowledged_and_rethrows_after_cleanup`(1)；`backend/tests/test_runtime_postgres.py::test_p2_it09_running_first_commit_wins_for_cancel_finish_and_reaper`(4)、`::test_p2_it09_queued_reaper_cancel_orders_and_cancelled_queue_timeout`(2)、`::test_p2_it11_stale_react_append_rethrows_cleans_and_preserves_terminal`(3)、`::test_p2_it11_worker_heartbeat_loss_is_worker_lost_not_user_cancellation`(1) | 本机 + PG17 | **通过**；用户取消与 worker_lost 不混淆，stale finish no-op，stale/cancelled/expired append 不 ack/不落库并重抛，两种 first-commit-wins 与 reaper 变体通过；E02/E05/E06/E09 |
| P2-UT-24 | 固定描述符与低基数观测 | `backend/tests/test_execution_orchestrator.py::test_shared_composition_registers_fixed_descriptors_without_per_run_execution`(1)；`backend/tests/test_runtime_baseline.py::test_worker_on_logs_only_low_cardinality_path_and_outcome`(1)、`::test_worker_on_known_outcomes_keep_controlled_log_labels`(3)、`::test_worker_on_terminal_log_uses_controlled_monotonic_duration`(1)、`::test_real_react_orchestrator_worker_never_logs_unknown_legacy_code`(1) | 本机 | **通过**；六条实际 INFO 均含 path=orchestrator、tuple=react/native/v1、受控 status/error、有限非负 duration；无 input/history/秘密/未知 legacy code；E04 |

## 4. 集成测试（P2-IT）逐条结果

| 编号 | 用例 | 精确测试位置（参数展开数） | 环境 | 结果与新鲜关键证据 |
|---|---|---|---|---|
| P2-IT-01 | 无快照固定文本 off/on | `backend/tests/test_runtime_baseline.py::test_p2_it01_no_snapshot_fixed_model_off_on_real_worker_parity`(1) | 本机真实 RuntimeFactory/test double | **通过**；真实 base_runtime 新旧调用、output/history/dropped/事件/usage/终态严格对等，nil 不泄漏；E01/E02/E03 |
| P2-IT-02 | 已发布快照、Profile、语言、多轮工具 | `backend/tests/test_agent_config_execution_compat.py::test_p2_it02_published_snapshot_language_and_multiround_tool_parity`(1) | 本机 | **通过**；真实快照 Agent UUID、同 Profile/工具/消息/预算，回复与事件对等且快照未改；E01/E03 |
| P2-IT-03 | 截断、summary、customer_memory、reasoning | `backend/tests/test_runtime_baseline.py::test_p2_it03_truncation_summary_customer_memory_and_reasoning_match_legacy`(1) | 本机 | **通过**；消息顺序、dropped、成功 memory_context、reasoning 历史保留和不可见性一致；E01/E02/E03 |
| P2-IT-04 | 完整新路径与双 emit 边界 | `backend/tests/test_agent_config_execution_compat.py::test_p2_it04_full_new_path_owns_one_private_stream_and_public_delivery`(1)；`backend/tests/test_execution_orchestrator.py::test_real_react_orchestration_preserves_dual_emit_order_and_unknown_legacy_code`(1)、`::test_worker_source_has_no_concrete_engine_branch_and_composition_injects_only_when_on`(1) | 本机 | **通过**；私有 runtime_emit 与公共 worker_emit 顺序、ack、私有 Outcome 单次收集、一次 finish、Context 无 emit；E01/E02/E03 |
| P2-IT-05 | 内部 SSE R15、200+ 排空与 delta | `backend/tests/test_runtime_baseline.py::test_p2_it05_internal_sse_replay_delta_cursor_and_hidden_replay_parity`(1)、`::test_p2_it05_internal_sse_last_event_id_drain_and_invalid_cursor`(1)；`backend/tests/test_runtime_postgres.py::test_p0_it_07_internal_sse_after_and_last_event_id_use_strict_max`(1)、`::test_p0_it_07_internal_sse_drains_more_than_200_events_before_terminal`(1)、`::test_p0_it_07_internal_sse_does_not_replay_transient_model_delta`(1)、`::test_p0_it_07_internal_sse_hides_terminal_tool_replay_and_advances_cursor`(1)、`::test_p2_it20_real_pg_internal_run_scope_redaction_and_r15_errors`(1) | 本机 ASGI + PG17 ASGI | **通过**；手工 header 四形态 400/`invalid_last_event_id`，typed after 四形态 422；合法 max/strict replay、ID 1..204、无 ID delta 不重放、tool.replay 隐藏且 cursor 推进；详见附录 D，E01/E03/E05/E06 |
| P2-IT-06 | Open SSE R15、tool.replay 与脱敏 | `backend/tests/test_open_platform.py::test_p2_it06_open_sse_redaction_hidden_replay_and_cursor`(1)、`::test_p2_it06_open_sse_typed_invalid_cursor_and_last_event_id`(1)、`::test_p2_it20_real_pg_open_sse_drain_cursor_delta_and_authorization`(1) | 本机 ASGI + PG17 ASGI | **通过**；Open typed header 三形态及 after 四形态均 422；合法 max/strict replay、201 条扩展事件排空、tool.replay 与私有字段不可见；详见附录 D，E01/E03/E05/E07 |
| P2-IT-07 | 全来源错误与未来未知 code | `backend/tests/test_runtime_baseline.py::test_p2_it07_real_chain_failures_keep_legacy_codes_and_safe_logs`(4)；完整 27 项矩阵见 P2-UT-06 | 本机 | **通过**；持久 legacy code 与公共已知映射/internal_error 一致，普通异常 execution_error，日志/API 无敏感原文；E01/E02/E03 |
| P2-IT-08 | 等待模型时取消与重复 cancel | `backend/tests/test_runtime_baseline.py::test_p2_it08_cancel_waiting_model_repeat_cancel_and_late_release`(2) | 本机，off/on | **通过**；模型任务实际取消并清理，最终 cancelled、空 output，迟到 release 不产生第二终态；E01/E02/E03 |
| P2-IT-09 | 真实 PG cancel/finish/reaper 提交顺序 | `backend/tests/test_runtime_postgres.py::test_p2_it09_running_first_commit_wins_for_cancel_finish_and_reaper`(4)、`::test_p2_it09_queued_reaper_cancel_orders_and_cancelled_queue_timeout`(2) | PG17 | **通过**；finish/reaper 先提交与 cancel 先提交均 first-commit-wins，唯一终态，保留 worker_lost/queue_timeout 变体；E05/E06/E09 |
| P2-IT-10 | model_timeout 与 run_timeout | `backend/tests/test_runtime_baseline.py::test_p2_it10_model_and_outer_run_timeout_parity_without_retry`(2) | 本机 | **通过**；分别 failed/model_timeout、failed/run_timeout，无自动重试且任务清理；E01/E02/E03 |
| P2-IT-11 | Lease/reap 后迟到 finish/append | `backend/tests/test_runtime_postgres.py::test_p2_it11_stale_react_append_rethrows_cleans_and_preserves_terminal`(3)、`::test_p2_it11_worker_heartbeat_loss_is_worker_lost_not_user_cancellation`(1)；同文件 `test_p0_it_06_terminal_rejects_late_append_and_repeat_finish`、`test_p0_it_06_wrong_owner_finish_and_append_do_not_write`、`test_p0_it_06_expired_lease_rejects_append_and_finish` 各 1 | PG17 | **通过**；失租不是用户取消，stale finish 静默 no-op，append CancelledError 不 ack/不持久化且原终态不改；E05/E06 |
| P2-IT-12 | off/on、混合 Worker 与回滚 | `backend/tests/test_runtime_postgres.py::test_p2_it18_mixed_workers_exclusive_claim_parity_and_all_off_rollback`(1)；P2-UT-10/13 的 12 个配置/路径参数例 | PG17 + 本机 | **通过**；off API 行由不同 on/off owner 独占 claim，结果/事件相等，无 configuration_changed；全 off 后新 Run 完成且已有终态不变；E02/E05/E06/E09 |
| P2-IT-13 | 注册项删除/禁用后的 fail-fast | `backend/tests/test_execution_orchestrator.py::test_resolution_failures_return_safe_failed_outcomes_without_fallback`(6) | 本机 | **通过**；六类解析失败均安全 failed，无静默 legacy 或版本回退；E02/E03 |
| P2-IT-14 | LocalTest 独立 Registry 经同一编排/Worker | `backend/tests/test_execution_orchestrator.py::test_p2_it14_real_local_test_orchestrator_worker_repository_end_to_end`(4)、`::test_real_local_test_uses_separate_selector_public_collect_and_no_private_ack`(2)、`::test_protocol_free_public_result_fallback_is_deterministic`(6)、`::test_real_local_external_adapter_cancel_returns_orchestrator_cancelled_fallback`(1) | 本机 | **通过**；真实 LocalTest 独立 local-test/scripted/v1，yield=delivery、无私有 ack/Outcome，完成/失败/timeout/外部 cancel 映射确定且任务清理；E02/E03 |
| P2-IT-15 | 并行工具与扩展业务事件对等 | `backend/tests/test_runtime_baseline.py::test_p2_it15_parallel_tools_and_business_events_keep_stable_payloads`(1)；P2-UT-22 三个并行函数各 1 | 本机 | **通过**；call_id started/completed 对齐、局部偏序与模型轮边界、无 call_id 按轮 multiset，稳定 payload/usage 不变；E01/E02/E03 |
| P2-IT-16 | PG 慢 worker_emit、背压、失败与迟到结果 | `backend/tests/test_runtime_postgres.py::test_p2_it16_real_pg_capacity_one_ack_backpressure_and_terminal_order`(1)、`::test_p2_it16_emit_failure_and_cancelled_append_suppress_late_results`(2) | PG17 | **通过**；容量 1 不死锁，仅成功 emit 后 ack；普通失败为 failed，CancelledError 不 ack/重抛，迟到成功不覆盖且任务清理；E05/E06 |
| P2-IT-17 | 真实 Memory 五类事务 | `backend/tests/test_memory_postgres.py::test_p2_exec_it17_summary_history_dropped_off_on_real_pg`(2)、`::test_p2_exec_it17_failure_and_cancel_have_no_memory_writeback`(4)；`backend/tests/test_memory_customers_postgres.py::test_p2_exec_it17_extract_customer_injection_and_original_row_off_on`(2)；另完整执行六套件 158 节点 | PG17 | **通过**；8 个 Phase 2 参数例及六套件 156 通过；summary/history/dropped/extract/reinforce/injection、提交/回滚、失败/取消不写回与租户隔离；2 个替代环境 skip 另列，E05/E08 |
| P2-IT-18 | 存量行、混合 claim 与真实 asyncpg UUID 链 | `backend/tests/test_runtime_postgres.py::test_p2_it18_real_pg_claimed_uuid_enters_execution_context`(1)、`::test_p2_it18_mixed_workers_exclusive_claim_parity_and_all_off_rollback`(1)、`::test_p0_it_01_queued_claim_completed_lifecycle_persists_exact_state`(1)、`::test_p0_it_04_reaper_cancelled_expired_running_lease_keeps_worker_lost`(1)、`::test_p0_it_06_terminal_rejects_late_append_and_repeat_finish`(1) | PG17 真实 asyncpg | **通过**；原 asyncpg UUID 子类对象经 Context→实际 Adapter Request→应用 RuntimeFactory，原 row/row.id 对象/类型/值不变，Request 精确 stdlib UUID；存量 queued/running/terminal 与回滚无需修复；详见附录 D，E05/E06/E09 |
| P2-IT-19 | 动态 Alembic 空库与目录零漂移 | `backend/tests/test_runtime_postgres.py::test_p2_it19_real_pg_dynamic_alembic_head_matches_current`(1)；临时空库 `alembic upgrade head`、`heads`、`current`；57 文件 SHA256 对比 | PG17 + 静态 | **通过**；upgrade 成功，heads/current 均 `0057_industry_pack_runtime (head)`；57/57、零路径/哈希漂移，无 downgrade；E05/E06/E10/E11 |
| P2-IT-20 | 跨租户 Run/SSE、身份与观测对抗 | `backend/tests/test_runtime_postgres.py::test_p2_it20_real_pg_internal_run_scope_redaction_and_r15_errors`(1)；`backend/tests/test_open_platform.py::test_p2_it20_real_pg_open_sse_drain_cursor_delta_and_authorization`(1)；`backend/tests/test_execution_orchestrator.py::test_p2_it20_forged_or_nil_agent_fails_before_registry_or_legacy_query`(1)；`backend/tests/test_runtime_baseline.py::test_p2_it20_public_run_view_and_observability_exclude_private_fields`(1) | 本机 + PG17 ASGI | **通过**；tenant/business/workspace 过滤、跨身份 403/404、伪造/nil Agent 在 Registry/查询前拒绝、RunView/SSE 无私有字段，metrics 无 run_id；E01/E03/E05/E06/E07 |

## 5. 通用核对项（P2-CM）逐条结果

| 编号 | 核对项 | 精确测试位置/检查 | 环境 | 结果与新鲜证据 |
|---|---|---|---|---|
| P2-CM-01 | 数据库迁移与既有行兼容 | P2-IT-19；`backend/tests/test_runtime_postgres.py::test_p2_it18_mixed_workers_exclusive_claim_parity_and_all_off_rollback`、`::test_p0_it_01_queued_claim_completed_lifecycle_persists_exact_state` | PG17 + 静态 | **通过**；空库 upgrade/heads/current、57 文件零漂移、存量行和回滚通过；临时库已删除，原库/容器/卷保留；E05/E06/E09～E11/E18 |
| P2-CM-02 | 配置加载与默认兜底 | `backend/tests/test_execution_orchestrator.py::test_execution_orchestrator_settings_default_and_process_lifetime`(1)、`::test_runtime_fingerprint_excludes_only_the_orchestrator_rollout_flag`(1)；`backend/tests/test_runtime_baseline.py::test_worker_on_without_orchestrator_fails_safely_without_legacy_fallback`(1)；另复用 P2-UT-10/13、P2-IT-01/12/13 | 本机 + PG17 | **通过**；默认 off、环境覆盖、fingerprint 排除、off/on 对等及 on 失败不兜底均通过；E01/E02/E05/E09 |
| P2-CM-03 | 审计、日志与观测 | `backend/tests/test_runtime_baseline.py::test_worker_on_logs_only_low_cardinality_path_and_outcome`(1)、`::test_worker_on_terminal_log_uses_controlled_monotonic_duration`(1)；P2-UT-24 共五个函数 7 例，其中 E04 的四个 Worker 日志函数共 6 例且均输出实时 INFO | 本机 | **通过**；实际六行 path/tuple/status/error/duration 证据，受控 `duration_ms=125.000`，无私密/原始堆栈/nil；这只是测试日志，不是生产 trace/metrics；E04 |
| P2-CM-04 | 多租户与公开数据面 | `backend/tests/test_runtime_postgres.py::test_p2_it20_real_pg_internal_run_scope_redaction_and_r15_errors`(1)；`backend/tests/test_open_platform.py::test_p2_it20_real_pg_open_sse_drain_cursor_delta_and_authorization`(1)；另复用 P2-IT-20 其余函数及 P2-IT-02 | 本机 + PG17 | **通过**；跨租户/工作区不可达，公开 RunView/Open SSE 字段集合固定，无 Outcome/Context/config/history/gateway 内部字段；E03/E05～E07 |
| P2-CM-05 | API/SSE/Agent 配置/前端兼容 | `backend/tests/test_runtime_postgres.py::test_p0_it_07_internal_sse_after_and_last_event_id_use_strict_max`(1)；`backend/tests/test_open_platform.py::test_p2_it20_real_pg_open_sse_drain_cursor_delta_and_authorization`(1)；`backend/tests/test_agent_config_execution_compat.py::test_p2_it02_published_snapshot_language_and_multiround_tool_parity`(1)；另复用 P2-IT-05/06/20、保护面路径检查与 Phase 1 回归 | 本机 + PG17 + 静态 | **通过**；R15 实际路由矩阵见附录 D；迁移/ORM/公共路由/schema/前端变更路径均为 0，公共状态码/错误体由实际路由回归；E03/E05～E07/E16 |
| P2-CM-06 | 异步资源与代码质量 | `backend/tests/test_react_engine_adapter.py::TestReactAdapter::test_early_aclose_cleans_owned_tasks_and_does_not_permit_replay`(1)；`backend/tests/test_runtime_postgres.py::test_p2_it16_emit_failure_and_cancelled_append_suppress_late_results`(2)；另复用 P2-UT-07/09/18～20、P2-IT-08/10/14/16 及 Ruff、格式、架构、`diff --check` | 本机 + PG17 + 静态 | **通过（功能及本阶段改动）**；成功/失败/取消/aclose/回滚 owned tasks done；lint、12 个本阶段源文件格式、干净导出架构和 whitespace 通过。全 `src` 有 32 个零重叠既存格式偏差，见残留风险 R-02，不伪称全树格式通过；E02/E03/E06/E13～E16 |
| P2-CM-07 | Phase 1 保护面、双 emit 与事件所有权 | `backend/tests/test_agent_config_execution_compat.py::test_p2_it04_full_new_path_owns_one_private_stream_and_public_delivery`(1)；`backend/tests/test_react_engine_adapter.py::test_public_contract_has_exactly_nineteen_reuses_and_six_private_replacements`(1)；另复用 P2-UT-03/05/09/14/21、P2-IT-04～07/14 与 18 文件回归 | 本机 + PG17 | **通过**；公共 DTO/Registry/LocalTest 与 RuntimeEngine/Factory 语义保持，worker_emit 仅 Orchestrator，runtime_emit 仅私有 Runtime 链，伪造事件不到 worker_emit，delta 无持久 seq；E02/E03/E05～E07/E16 |
| P2-CM-08 | 证据诚信、功能出口与性能边界 | `backend/tests/test_execution_orchestrator.py::test_p2_cm08_performance_sampler_records_raw_pairs_and_pending_environment`(1)；独立重算 `phase2-t8-performance.json` | 本机 test double | **通过（证据诚信/方法）**；5 warm-up、30 有效 matched pairs、0 错误、15/15 顺序、N30 第 29 项 nearest-rank；原始指标完整，canonical diff 不含 raw latency，外部时延未扣除；生产性能 `pending_env`，不宣称达标；E01/E12 |

## 6. 回归范围

本轮对以下 18 个受审文件执行 `-m 'not postgres'` 选择，结果 **1032 passed, 14 deselected**，不是全量 pytest。其中 17 个文件含实际执行的非 PG 节点；`test_agent_model_required.py` 仅贡献两个 deselected PG 节点，并由 E19 在真实 PG17 下完整执行，不能把本组称为“18 个非 PG 文件均完整执行”：

- `test_execution_orchestrator.py`、`test_react_engine_adapter.py`、`test_runtime_baseline.py`、`test_runtime_baseline_fixtures.py`、`test_runtime_baseline_tooling.py`；
- `test_agent_config_execution_compat.py`、`test_open_platform.py`、`test_memory_summary.py`；
- `test_local_test_adapter.py`、`test_runtime_engine.py`、`test_memory_config.py`、`test_memory_governance.py`、`test_memory_injection.py`；
- `test_agent_execution_contracts.py`、`test_agent_execution_registries.py`、`test_extension_contracts.py`、`test_agent_model_required.py`、`test_agent_languages.py`。

真实 PG 另执行完整 `test_runtime_postgres.py`（45）、Open+agent-config（17）、六 Memory 套件（156 passed/2 skipped）、完整 `test_agent_model_required.py`（2），以及 26 个新增选择、23 个 T7 选择。各组有重叠，不重复累计。保护面路径检查显示 migration/ORM/public route/schema/frontend 均为 0 变更；未修改生产代码、测试、迁移或前端。

## 7. 迭代中发现并修复的缺陷

以下为本阶段前序评审/实施的历史记录；本轮没有发现新的功能缺陷，没有 P0/P1 遗留。修复提交列按要求不虚构 SHA。

| # | 级别 | 缺陷/评审项 | 发现环节 | 修复提交 | 本轮回归 |
|---|---|---|---|---|---|
| D-01 | P1（文档契约） | R15 内部手工 Last-Event-ID 与 typed after/Open typed 游标的 400/422 文档状态码冲突，可能导致错误兼容预期 | 规格评审 | 工作树修复；本阶段未授权commit | 实际内部/Open ASGI 矩阵及合法 max/strict replay 全部通过；IT05/06、CM05 |
| D-02 | P1（生产实现） | 真实 `repo.claim()` 返回 asyncpg UUID 子类，原 Context 精确类型检查拒绝，真实 PG 链曾出现 44 passed/1 failed | T6b R16 真实 PG | 工作树修复；本阶段未授权commit | UT01 33 例及 IT18 原 row→Context→Request→RuntimeFactory 全通过，无 fixture 预转换 |
| D-03 | P1（实现/覆盖） | T6 规格评审六项缺口：包括 no-snapshot 真实应用 Factory 链、LocalTest 经同一 Orchestrator/Worker 端到端、canonicalizer 不得吞 model_calls/业务差异、CM03 duration 生产遗漏及其余指定覆盖缺口 | T6 规格评审/T5 修复 | 工作树修复；本阶段未授权commit | IT01/04/14/15、UT22/24、CM03/07/08 全通过；真实 Factory spy、4 个 LocalTest E2E、29 个 canonicalizer 参数例和实际 duration 日志复核 |
| D-04 | P1（测试可靠性） | 取消/gated 路径使用过小调度 watchdog 且清理不完整，可能造成环境相关失败或悬挂 | T6 质量评审 | 工作树修复；本阶段未授权commit | 取消、monitor、LocalTest、背压与真实 PG 资源清理全通过，无悬挂任务 |
| D-05 | P1（测试假绿） | postcondition 曾可能位于 `finally` 清理之后，注入未完成 owned task 时存在假绿分支 | T6 对抗质量评审 | 工作树修复；本阶段未授权commit | owned-task 断言在清理前生效；本轮 UT07/09/18～20、IT08/14/16 全通过 |
| D-06 | P2（文档质量） | T7 runbook 曾混淆 app healthcheck 与 runtime-worker 运行状态、命令工作目录/env 来源及一次性 canary 覆盖范围，证据脚本复现说明不足 | T7 质量评审 | 工作树修复；本阶段未授权commit | 本轮复核运行/回滚对应功能节点及日志；未把文档复核冒充实机生产部署 |

## 8. 残留风险与边界

| # | 级别 | 描述 | 处置 |
|---|---|---|---|
| R-01 | 环境待补 | 真实外部模型/工具生产性能未测；test-double 比值不是生产达标或退化结论 | 仅性能子指标 `pending_env`；T9 最多有条件通过，须按 05 §4 补同环境真实 matched-pair 证据 |
| R-02 | P2/既存基线 | 全 `src` 格式检查发现 32 个文件需重排；它们与本阶段变更集合交集为 0，本阶段 12 个源文件全部通过 | 不在 T8 越权重排；另开基线格式清理，CI/提交门禁不得把本报告解释为全树格式通过 |
| R-03 | 环境限制 | 原始工作树有 `modules/apps/integrations/platform` 四个既存 ignored legacy 根，原始架构门禁因此失败 | 干净源导出仅排除同四根后门禁通过；未删除用户文件。CI 干净检出仍是权威环境，但本轮未运行 CI |
| R-04 | 待 T9 | 无生产 canary、部署 trace/metrics、真实外部模型性能或人工 UAT/签字 | 保持未执行，不在 06 伪造；由 T9/相应环境任务补证 |
| R-05 | 环境限制 | 原 `.git` 有 macOS macl 限制 | 使用仓库外临时 metadata 完成只读 diff/status；未修改原 `.git`，不声称直接 `.git` 检查成功 |

## 9. CI 证据

- **未执行**。本轮没有 commit、push 或 PR，因此没有 CI run、head SHA 或 URL。
- 本地受影响测试与静态检查不能替代 CI 全量 unit/postgres/frontend 结果。
- 本报告不声称全量 pytest、生产部署、生产性能、人工 UAT 或正式验收已经通过。

## 10. 出口结论

**本地功能出口通过；生产性能子指标 `pending_env`。** P2-UT-01～24、P2-IT-01～20、P2-CM-01～08 均有本轮新鲜证据，所有功能主用例通过，CM08 的证据诚信与测量边界通过。两个 Memory skip 是替代环境用例且未计通过。上述结论允许进入 T9，但不等于 Phase 2 完全验收；在生产性能证据缺失时 T9 最多有条件通过。

## 附录 A 本地执行输出与证据快照

> 本附录仅为关键结果摘要；临时原始证据链接的生命周期及清理后不可复核限制见 §1。

| 证据 | 原始输出摘要 | 链接 |
|---|---|---|
| A-01 | `52 passed, 170 deselected in 3.29s` | [nonpg-p2-selection.log](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-logs/nonpg-p2-selection.log) |
| A-02 | `205 passed in 3.21s` | [nonpg-core-two-files.log](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-logs/nonpg-core-two-files.log) |
| A-03 | `1032 passed, 14 deselected in 5.51s` | [nonpg-full-reviewed-file-set.log](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-logs/nonpg-full-reviewed-file-set.log) |
| A-04 | `26 passed, 89 deselected in 13.17s` | [pg-new-26.log](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-logs/pg-new-26.log) |
| A-05 | `45 passed in 9.89s` | [pg-runtime-full.log](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-logs/pg-runtime-full.log) |
| A-06 | `17 passed in 14.09s` | [pg-open-agent-config.log](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-logs/pg-open-agent-config.log) |
| A-07 | `156 passed, 2 skipped in 78.06s` | [pg-memory-six-suites.log](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-logs/pg-memory-six-suites.log) |
| A-08 | `23 passed in 1.88s` | [pg-t7-mixed-rollback-existing-logs.log](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-logs/pg-t7-mixed-rollback-existing-logs.log) |
| A-09 | `6 passed in 0.64s`；六条受控 path 日志 | [worker-path-logs.log](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-logs/worker-path-logs.log) |
| A-10 | `All checks passed!` | [ruff-check.log](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-logs/ruff-check.log) |
| A-11 | `12 files already formatted`；全树另有 32 个既存偏差 | [Phase 2 format](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-logs/ruff-format-phase2-files.log)、[baseline attribution](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-logs/ruff-format-baseline-attribution.log) |
| A-12 | `architecture gate passed`（干净导出） | [architecture-clean-export.log](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-logs/architecture-clean-export.log) |
| A-13 | 57/57 migration files；added/removed/sha256_changed 均为空 | [migration-drift.log](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-logs/migration-drift.log) |
| A-14 | 5 warm-up、30 pairs、0 errors、15/15、item 29 | [performance verification](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-logs/performance-independent-verification.log)、[raw JSON](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-performance.json) |
| A-15 | `2 passed in 1.60s`；`test_agent_model_required.py` 两个真实 PG 节点 | [pg-agent-model-required.log](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-logs/pg-agent-model-required.log) |

## 附录 B P2-UT-01 精确函数与参数展开数

文件均为 `backend/tests/test_execution_orchestrator.py`。

| 函数 | 数量 | 关键断言 |
|---|---:|---|
| `test_snapshot_request_uses_claimed_row_and_real_agent_uuid_without_stringifying` | 1 | 精确 stdlib UUID、真实 Agent UUID、react/native/v1 |
| `test_snapshot_agent_uuid_accepts_only_real_uuid_values` | 2 | UUID 对象/字符串受控解析 |
| `test_missing_malformed_or_nil_snapshot_agent_identity_fails_closed` | 9 | 缺失、空、畸形、nil 安全失败 |
| `test_malformed_run_config_or_snapshot_never_falls_back_to_legacy` | 4 | 畸形 config 不回退 legacy |
| `test_request_mapping_access_failures_are_safe_invalid_requests` | 3 | Mapping 普通异常转安全 INVALID_REQUEST 且脱敏 |
| `test_request_snapshot_config_access_failure_is_safe_invalid_request` | 1 | snapshot config 访问异常安全脱敏 |
| `test_request_mapping_control_flow_is_not_swallowed` | 2 | CancelledError/KeyboardInterrupt 原类型重抛 |
| `test_only_react_no_snapshot_legacy_request_uses_internal_anonymous_sentinel` | 1 | 仅受限无快照场景 UUID(int=0) |
| `test_claimed_execution_id_must_be_a_uuid` | 3 | 字符串/None/整数拒绝 |
| `test_uuid_subclass_is_normalized_without_rewriting_claimed_row_identity` | 1 | 子类转精确 stdlib；原 row/row.id 不变 |
| `test_execution_context_rejects_mismatched_uuid_values` | 1 | 值不匹配拒绝，不以 `is` 代替值相等 |
| `test_non_uuid_fake_with_uuid_string_is_rejected` | 1 | 伪造 `__str__` 非 UUID 拒绝 |
| `test_malicious_uuid_subclass_string_failure_is_safe_and_redacted` | 1 | 恶意 `__str__` 普通异常安全脱敏 |
| `test_uuid_type_descriptor_failure_is_safe_and_redacted` | 1 | 描述符普通异常安全脱敏 |
| `test_uuid_subclass_string_control_flow_is_rethrown` | 2 | 控制流原对象重抛 |
| **合计（15 个不重复函数）** | **33** | E02/E03；真实 asyncpg 链另见 IT18 |

## 附录 C P2-UT-21 公共 Adapter 25 函数精确清单

位置均为 `backend/tests/test_react_engine_adapter.py::TestReactAdapter::<函数>`。19 个“复用”来自 `tests/agent_execution/adapter_contract_suite.py` 原函数并逐项继承执行；6 个“私有替代”在 React harness 中覆盖同名目的。合计 25 函数、34 个参数展开例；守卫函数另执行 1 例。

| 函数 | 裁定 | 数量 |
|---|---|---:|
| `test_capabilities_start_stream_collect_success` | 私有替代 | 1 |
| `test_immediate_concurrent_and_repeated_collectors_share_result` | 复用 | 1 |
| `test_concurrent_second_consumer_and_claim_after_aclose_are_rejected` | 复用 | 1 |
| `test_multiple_events_preserve_order_payload_and_empty_stream_terminates` | 复用 | 1 |
| `test_request_identity_mismatch_fails_before_handle` | 复用 | 1 |
| `test_prestart_errors_precede_handle_and_preserve_retryability` | 私有替代 | 1 |
| `test_stream_errors_are_safe_for_stream_and_all_collectors` | 复用 | 6 |
| `test_pre_chained_safe_stream_error_does_not_retain_raw_exception_chain` | 复用 | 1 |
| `test_unknown_exception_and_simulated_process_failure_are_distinct_and_safe` | 私有替代 | 1 |
| `test_manual_clock_timeout_wakes_collectors_without_real_waiting` | 复用 | 1 |
| `test_repeated_concurrent_cancel_closes_stream_and_collectors` | 复用 | 1 |
| `test_cancel_wins_gate_race_and_suppresses_late_events_and_success` | 复用 | 1 |
| `test_success_wins_gate_race_and_is_never_retroactively_cancelled` | 复用 | 1 |
| `test_duplicates_late_events_gaps_and_timestamps_follow_sequence_rules` | 私有替代 | 1 |
| `test_same_event_id_with_different_content_is_never_repaired` | 私有替代 | 1 |
| `test_terminal_visibility_never_precedes_queued_or_active_stream_events` | 复用 | 1 |
| `test_early_aclose_cleans_owned_tasks_and_does_not_permit_replay` | 复用 | 1 |
| `test_one_cancelled_collector_does_not_cancel_shared_execution` | 复用 | 1 |
| `test_lone_collector_cancellation_cleans_owned_work_before_propagation` | 复用 | 1 |
| `test_deterministic_fresh_runs_have_no_cross_instance_high_water` | 私有替代 | 1 |
| `test_pending_anext_is_woken_by_aclose_without_external_cancel` | 复用 | 1 |
| `test_claimed_empty_stream_does_not_block_successful_collection` | 复用 | 1 |
| `test_delivered_only_event_does_not_require_an_extra_poll_before_result` | 复用 | 1 |
| `test_invalid_handles_are_rejected_by_stream_collect_and_cancel` | 复用 | 5 |
| `test_raw_request_and_handle_values_fail_safely` | 复用 | 1 |
| **合计** | **19 复用 + 6 私有替代** | **34** |

## 附录 D R15/R16 实际路由与真实驱动证据

### D.1 R15 内部/Open ASGI 矩阵

| 路由/节点 | 实际请求形态 | 实际断言与结果 |
|---|---|---|
| 内部 `test_p2_it20_real_pg_internal_run_scope_redaction_and_r15_errors` | 手工 `Last-Event-ID: bad/-1/2147483648/1.5`，并带合法 `after=1` | 四项均 **400**，`detail == invalid_last_event_id`；E05/E06 |
| 同上 | typed `after=-1/2147483648/bad/1.5` | 四项均 **422**；非法 Run UUID 422，不存在 Run 404 |
| 内部 `test_p0_it_07_internal_sse_after_and_last_event_id_use_strict_max` | `(after=2,header=1)`、`(after=1,header=2)`、边界 `(1,1)`、严格终态 `(2,2)` | 均 200；max/strict 生效，边界仅重放 seq 2，严格终态为空且不含 run.queued |
| 内部 `test_p0_it_07_internal_sse_drains_more_than_200_events_before_terminal` | 201 个持久扩展事件后完成；`after=200` | 全量 ID 1..204，tail ID 201..204，run.completed 最后 |
| 内部 `test_p0_it_07_internal_sse_does_not_replay_transient_model_delta` | 实际 LISTEN/NOTIFY live delta；`after=0` 与 `Last-Event-ID:2` 重放 | live delta 恰好一次且无 `id:`；持久 ID 1..4；落库和两种重放均无 delta/marker，终帧最后 |
| 内部 `test_p0_it_07_internal_sse_hides_terminal_tool_replay_and_advances_cursor` | terminal 后写 tool.replay；全量与 `after=terminal_seq` | 全量无 tool.replay/marker，隐藏尾部 200 空响应证明 cursor 推进 |
| Open `test_p2_it20_real_pg_open_sse_drain_cursor_delta_and_authorization` | typed `Last-Event-ID: bad/-1/2147483648`；typed `after=-1/2147483648/bad/1.5` | 三项 header + 四项 after 均 **422**；E05/E07 |
| 同上 | `(after=terminal_seq,header=1)`、`(after=1,header=terminal_seq)` | 均 200；max/strict 后无 run.completed、无 tool.replay |
| 同上 | 201 个扩展事件、terminal 后隐藏 tool.replay、跨 key/user 请求 | 持久 ID 1..terminal_seq，终帧最后；replay payload、private input、redact marker、gateway/history/outcome/context 均不可见；跨身份 404 |
| Open `test_p2_it06_open_sse_typed_invalid_cursor_and_last_event_id` | 非 PG ASGI 的合法 after/header 与 bad/-1 header、-1 after | 合法 200 且严格重放；非法均 422，补足轻量路由回归 |

### D.2 R16 原 asyncpg row 证据

实际节点 `backend/tests/test_runtime_postgres.py::test_p2_it18_real_pg_claimed_uuid_enters_execution_context` 本轮在 E05/E06/E09 中通过：

1. `repo.claim()` 直接返回原 Mapping；`original_row_id` 是 `UUID` 实例但 `type(...) is not UUID`，且类型模块以 `asyncpg.` 开头，没有 fixture 预转换。
2. 实际应用组合 `RuntimeFactory` 的 spy 仅记录并委托原 `for_run`；恰好调用一次，`factory_row is claimed`、`factory_row_id is original_row_id`，类型和字符串值不变。
3. `context.row is claimed`，`context.row["id"] is original_row_id` 且类型不变；`context.execution_id` 与 Adapter 实际收到的 `request.execution_id` 均为**精确 stdlib UUID**，值等于原 row.id。
4. 执行实际完成，持久事件含 `model.completed` 且最后为 `run.completed`。
5. UT01 的伪造 UUID、恶意 `__str__`/描述符普通异常、安全静态 `INVALID_REQUEST`、诊断脱敏和 CancelledError/KeyboardInterrupt 原样重抛同时通过；没有用 helper 单测替代真实驱动链。

## 附录 E CM08 性能原始口径

> 本附录仅为关键结果摘要；原始 JSON 链接受 §1 生命周期限制，最终清理后不可复核。

| 指标 | 新鲜结果 |
|---|---:|
| warm-up pairs（不计样本） | 5 |
| 有效 matched pairs / errors | 30 / 0 |
| old-first / new-first | 15 / 15 |
| nearest-rank | N=30，排序后 1-based 第 29 项 |
| old/new end-to-end p95 | 0.007500 / 0.095542 ms |
| old/new first-token p95 | 0.000292 / 0.093625 ms |
| paired-delta p95 | 0.089209 ms |
| adapter-overhead p95 | 0.095542 ms |
| end-to-end p95 ratio | 12.738933333333 |
| external latency subtracted | false |
| production status / target claimed | `pending_env` / false |

每对 raw old/new end-to-end、first token、adapter overhead、delta、ratio 均保存在 [原始 JSON](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-performance.json)。raw latency 仅排除在 canonical 功能 diff 外，未从性能证据或端到端口径删除。上述数值来自本地 test double，只证明采样与计算方法可执行；较大比值不构成生产性能失败或成功结论。

## 附录 F P2-UT-06 精确函数与参数展开数

以下函数均位于 `backend/tests/test_react_engine_adapter.py`。执行证据为 E02/E03，名称与展开数由 E17 的 pytest collection/源码清单核对；不使用通配符代替函数证据。

| 分组 | 精确函数 | 数量 |
|---|---|---:|
| 显式错误/timeout | `test_phase_zero_runtime_fault_matrix_preserves_legacy_and_maps_safe_public_error` | 27 |
| 显式错误/timeout | `test_future_unknown_runtime_fault_uses_safe_fallback_and_verbatim_private_code` | 1 |
| 显式错误/timeout | `test_model_stream_not_supported_has_safe_fallback_without_losing_legacy_code` | 1 |
| 显式错误/timeout | `test_outer_timeout_is_run_timeout_not_model_timeout` | 1 |
| 显式错误/timeout | `test_model_timeout_runtime_fault_remains_distinct_from_outer_run_timeout` | 1 |
| 显式错误/timeout | `test_unknown_regular_exception_is_safe_execution_error` | 1 |
| 显式错误/timeout | `test_protocol_failure_is_safe_and_defaults_to_execution_error` | 1 |
| 显式错误/timeout | `test_protocol_failure_preserves_an_explicit_legacy_code` | 1 |
| RuntimeFault 对抗 | `test_runtime_fault_subclass_uses_real_class_identity` | 1 |
| RuntimeFault 对抗 | `test_runtime_fault_code_property_failure_is_safe_and_does_not_leak` | 1 |
| RuntimeFault 对抗 | `test_runtime_fault_code_subclass_failure_is_safe_and_does_not_leak` | 1 |
| RuntimeFault 对抗 | `test_runtime_fault_mro_failure_is_safe_and_does_not_leak` | 1 |
| RuntimeFault 对抗 | `test_runtime_fault_failure_preserves_private_legacy_code` | 1 |
| ExceptionGroup 对抗 | `test_nested_single_exception_group_preserves_original_runtime_mapping` | 4 |
| ExceptionGroup 对抗 | `test_same_leaf_mapping_in_multi_exception_group_is_stable` | 1 |
| ExceptionGroup 对抗 | `test_mixed_leaf_mapping_in_multi_exception_group_uses_safe_fallback` | 1 |
| ExceptionGroup 对抗 | `test_exception_group_never_swallows_nested_control_flow` | 3 |
| ExceptionGroup 对抗 | `test_nested_cancelled_base_exception_group_closes_real_runner_without_external_cancel` | 1 |
| 控制流对抗 | `test_code_property_control_flow_is_not_swallowed` | 2 |
| 控制流对抗 | `test_control_flow_is_never_mapped_to_regular_failure` | 4 |
| 控制流对抗 | `test_failure_handler_control_flow_is_rethrown_after_cancellation_cleanup` | 3 |
| **合计** | **21 个函数：8 显式 + 5 RuntimeFault + 5 ExceptionGroup + 3 控制流** | **58** |

## 验收后验证附录（T11）

> 本附录只追加 2026-11-11 的 quickstart 实测，不改写上述 T8 正文或历史证据。完整非敏感证据见 [T11 evidence](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t11-evidence.md) 与 [原始日志目录](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t11-logs/)。本轮使用 demo backend，不新增生产性能结论。

### T11.1 起栈、默认 off 与 seed

- 初始仅有独立 Phase 2 PG17 测试容器，无 quickstart 项目或端口冲突，故使用标准 `nexusdesk-quickstart`，未覆盖既有栈。直接 Docker Hub 构建首次因元数据读取失败；随后通过 Compose 既有 `NODE_IMAGE/PYTHON_IMAGE` 变量使用 dockerproxy，`env -u AGENT_EXECUTION_ORCHESTRATOR_ENABLED sh nexusdesk quickstart` 成功。三服务 `postgres/app/mock-business` 均 healthy，无 `runtime-worker`。
- 默认进程实测 `orchestrator=False embedded_worker=True`，认证 HTTPS readiness 为 200/demo。app 内真实 seed 两次均 exit 0：首次 created=`1/1/1/1/2/1`，二次 created 全 0、preserved=`1/1/1/1/2/1`；Agent/OpenApp ID 与 `agent_version=1` 不变，Agent/Profile 各仅一个真实发布版本，两个会话分别为真实 Agent UUID 与 `agent_id=NULL`。
- 默认 off published Run `1298ac14-2e18-499b-8a83-6ebe8f894e8f`、no-snapshot Run `a3f57f5d-cd78-4cc8-bd48-de5340b65308` 均 completed、output 非空、`error_code=null`，无 `configuration_changed`；对应 Run ID 的 `path=orchestrator` 行均为 0。未臆造 legacy 专用日志。

### T11.2 显式 on、受控日志与双 SSE

- 初次显式 on 的 Run 虽 completed，但 quickstart 根 logger 为 WARNING，Worker 的 INFO 受控日志被吞，T11 因此暂停并报告生产缺陷。主会话随后提供经独立评审的 R17 日志配置修复；本轮保留原失败记录，用同一数据卷和 dockerproxy 变量重建 app，未重新 seed。
- R17 显式 on 后，published Run `acd0b330-3634-4867-b3eb-20b8f4c58248` 与 no-snapshot Run `89aedc66-21d5-4968-9754-566e74e62036` 均成功，各自恰好一条 `path=orchestrator tuple=react/native/v1 status=completed`，`duration_ms` 分别为 114.641/2.829。对该 on 容器全部 8 个 Run（含 SSE 与 checker 尝试）交叉核查，8 个 ID 对 8 条受控行且每个恰一次；均为 completed、有限非负 duration，无 `execution_failed`、敏感内容或静默 fallback。
- 最终内部 published/no-snapshot Run `5f6d70ca-f539-44d1-ab21-d840eab2cb3c` / `4d7e9b7f-9a73-4889-90e1-13b44f08db95` 和 Open Run `7f521b6f-3171-41f5-90a0-f8ffc68ce8a2` 均 completed。真实内部/Open stream 到 terminal 后，after=0 持久 replay 均为 seq `[1,2,3,4,5]`、终帧最后且内容一致；终态 cursor 分别放入 `after` 与 `Last-Event-ID` 均无事件，证明 max 与严格 `seq>after` 无重复。
- Open 仅多允许的无 ID `accepted(request_id,run_id)`；未泄露工具输入/结果、retrieval 内容、gateway metadata、reasoning/history/config/input/context/outcome。no-snapshot 仅走内部 API。所有临时 Key 均带 10 分钟过期并在 finally 撤销；跨失败 checker、手工成功和两次 live pytest 共 4 个 Key，最终全部 revoked/inactive，Key 原文未输出或落证据。

### T11.3 全 off 回滚与不可变性

- 回滚前对全部 95 个既有 terminal Run 保存 status/output/error/timestamps、事件数、终态 seq 和持久事件 SHA-256。显式 `AGENT_EXECUTION_ORCHESTRATOR_ENABLED=false ... up -d --force-recreate --wait app` 后，新进程为 false。
- 新 published/no-snapshot Run `a28cf8e7-319c-4948-a11a-8f7e97a5eaf6` / `46f541ad-35ff-4609-b72b-1c1270aae63e` 均 completed，对应 orchestrator 路径行均为 0，当前 off 容器整体也为 0。
- 后续共有 103 个 Run，但回滚前 95 个 Run 的上述字段与事件哈希全部逐项不变。无 Alembic downgrade、数据修复、客户端变化、新服务或 `down -v`。

### T11.4 新增 opt-in live 测试与实际命令

`backend/tests/test_execution_orchestrator_seed.py` 新增 `test_live_quickstart_internal_and_open_sse_replay`：只有显式提供 `NEXUSDESK_LIVE_QUICKSTART=1`、URL 和既有管理 token 才执行；默认 CI 不控制 Docker、不需要秘密，未配置时明确 skip。本轮以下节点均真实执行，skip/deselect 未计为通过：

| 实际命令（秘密仅由 shell 变量注入） | exit / 结果 | 原始证据 |
|---|---|---|
| `NEXUSDESK_LIVE_QUICKSTART=1 ... uv run --directory backend pytest tests/test_execution_orchestrator_seed.py::test_live_quickstart_internal_and_open_sse_replay -v` | 0；格式化前 **1 passed in 3.44s**，格式化后 **1 passed in 3.36s** | [首次](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t11-logs/live-pytest.log)、[最终](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t11-logs/live-pytest-final.log) |
| 既有受限 PG env 下 `uv run --directory backend pytest tests/test_execution_orchestrator_seed.py -k 'not live_quickstart' -v` | 0；**3 passed, 1 deselected in 2.34s** | [log](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t11-logs/seed-focused-postgres-pytest.log) |
| `uv run --directory backend ruff check tests/test_execution_orchestrator_seed.py` | 最终 0 | [log](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t11-logs/ruff-seed-final-recheck.log) |
| `uv run --directory backend ruff format --check tests/test_execution_orchestrator_seed.py` | 新增后首次 1；仅格式化本文件后最终 0 | [首次](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t11-logs/ruff-format-seed-final.log)、[最终](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t11-logs/ruff-seed-final-recheck.log) |

首次 SSE checker 错把内部 terminal data 当作扁平 RunView，实际为 `{output,error_code}`；第二次错拒 Open 允许的无 ID `accepted`。两次均为验证器假设错误，已保留记录并仅修正相应断言，未放松持久事件、游标或泄漏判据。未重跑 T8/T9 全套。最终 quickstart 保持显式 off、healthy，卷和独立 Phase 2 PG 证据资源均保留。

### T11.5 非零冲突游标补证（规格评审更正）

规格评审指出，前述 `(after=5,Last-Event-ID=0)` 与 `(after=0,Last-Event-ID=5)` 只覆盖零/非零边界，不能独立证明两个非零冲突游标取 max。保留原检查与记录，live 节点现对内部和 Open 各新增 `(after=4,Last-Event-ID=5)`、`(after=5,Last-Event-ID=4)`，两者均无持久事件；由此证明较大非零 cursor 无论位于 query 还是 header 都生效，且严格排除边界。

在当前 healthy off 栈执行同一 opt-in live 节点（路由 cursor 与执行开关无关），exit 0，**1 passed in 4.45s**，[原始日志](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t11-logs/live-pytest-nonzero-cursor.log)。目标文件 Ruff check/format 均 exit 0，[检查日志](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t11-logs/ruff-nonzero-cursor.log)。本次临时 Key 已 finally 撤销；累计 5 个 Key 全部 revoked/inactive，[非敏感元数据检查](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t11-logs/open-key-revocation-nonzero-cursor-check.json)。未改生产、未切换 on、未重跑旧套件。

### T11.6 Live 测试可靠性质量补证

质量评审指出两项 Important 测试可靠性问题，现已仅修改 live helper 并保留全部断言：`_live_read_sse` 的整个 `aiter_lines()` 消费循环外加 `asyncio.timeout(60)`，调用方 `async with client.stream(...)` 关闭语义不变，持续心跳不能使流无限等待；唯一 Open Key 签发响应解析处先保存 `key_id=issued["id"]`，再读取 `app_key=issued["key"]`，确保 key 字段异常时 finally 仍能按 ID 吊销。

当前 healthy off 栈重跑同一 opt-in 节点，exit 0，**1 passed in 4.38s**，[原始日志](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t11-logs/live-pytest-quality-reliability.log)；Ruff check/format 均 exit 0，[检查日志](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t11-logs/ruff-quality-reliability.log)。本次 Key 已撤销，累计 6 个 Key 全部 revoked/inactive，[非敏感检查](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t11-logs/open-key-revocation-quality-reliability-check.json)。未改生产或重跑旧套件，上述历史执行计数不作追溯修改。

## 最终跨阶段评审补证（R18，2026-11-12）

- `worker.py` 的正常 Outcome 受控终态 INFO 已移到对应 `repository.finish` 成功返回之后；finish 抛普通异常时不再提前发布正常 Outcome，只由既有异常处理器记录一次 failed 并按原控制流重试 failed finish。Repository 唯一终态写者、first-commit-wins、stale/no-op、Memory、off legacy 和异常/取消控制流未改。
- 新增 `test_worker_on_completed_finish_failure_logs_only_retry_failed`：completed finish 故障注入后，`finish_statuses == ['completed', 'failed']`，仅一条 failed 受控日志、无 completed 日志，duration 有限非负。新增 `test_worker_on_logs_terminal_only_after_successful_finish`：严格断言 `finish_started → finish_succeeded → log`。
- 两个新增节点与 9 个相关 Worker path-log/deployment 节点选择共执行 **16 passed in 1.17s**；目标 `worker.py`、`test_runtime_baseline.py`、`test_deployment.py` 的 Ruff check 为 `All checks passed!`，format check 为 `3 files already formatted`。完整节点、命令与原始日志见 [R18 证据索引](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-final-fix-evidence.md)。
- 本补证未重跑旧全套、未重建 quickstart，也未产生 R18 live Run 证据。T11 仍须用最终代码重建后最小复测一个 on Run（仅一条且与真实终态一致）及 off 回滚（无 orchestrator 日志）；在该复测完成前不得宣称 R18 live 闭环。生产性能、CI、真实部署 canary 和人工 UAT/签字不在本轮范围。

## R18 最终代码最小 live on/off 闭环补证（2026-11-12）

上述 pending 为历史记录；本附录追加后续真实执行，不追溯修改。复用现有数据，未运行 seed、Open、双 SSE 或旧全套，未签发临时 Open Key，未改生产。

| 实际命令（Compose 文件均为 `/Users/jackchow/Documents/CodeLib/nexusdesk/deploy/quickstart/compose.yaml`） | exit / 证据 |
|---|---|
| `NODE_IMAGE=dockerproxy.net/library/node:22-alpine PYTHON_IMAGE=dockerproxy.net/library/python:3.12-slim-bookworm docker compose -f /Users/jackchow/Documents/CodeLib/nexusdesk/deploy/quickstart/compose.yaml build app` | 0；[构建日志](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t11-logs/r18-final-app-rebuild.log) |
| `AGENT_EXECUTION_ORCHESTRATOR_ENABLED=true docker compose -f /Users/jackchow/Documents/CodeLib/nexusdesk/deploy/quickstart/compose.yaml up -d --force-recreate --wait --wait-timeout 300 app` | 0；[on 日志](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t11-logs/r18-explicit-on-force-recreate.log) |
| `docker compose -f /Users/jackchow/Documents/CodeLib/nexusdesk/deploy/quickstart/compose.yaml exec -T app python /tmp/r18_internal_run_once.py phase2-orchestrator-published 'R18 minimal live on verification'` | 0；[Run 响应](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t11-logs/r18-on-published.json) |
| `AGENT_EXECUTION_ORCHESTRATOR_ENABLED=false docker compose -f /Users/jackchow/Documents/CodeLib/nexusdesk/deploy/quickstart/compose.yaml up -d --force-recreate --wait --wait-timeout 300 app` | 0；[off 日志](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t11-logs/r18-explicit-off-force-recreate.log) |
| `docker compose -f /Users/jackchow/Documents/CodeLib/nexusdesk/deploy/quickstart/compose.yaml exec -T app python /tmp/r18_internal_run_once.py phase2-orchestrator-published 'R18 minimal live off verification'` | 0；[Run 响应](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t11-logs/r18-off-published.json) |

- on published Run `c8e390f2-18fa-4193-9f39-62bd79030563` 真实 completed、output 非空、`error_code=null`；该 ID 的 `path=orchestrator` 总数 **1**、completed **1**、failed **0**，唯一行含 `tuple=react/native/v1`，`duration_ms=123.639` 有限非负。[日志断言](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t11-logs/r18-on-run-log-check.json)。
- off published Run `53b29563-5933-4f4e-9a7b-deea3a087b18` 真实 completed、output 非空、`error_code=null`；该 ID 的 orchestrator 日志 **0**、failed **0**，off 容器整体 orchestrator 日志也为 **0**。旧 on Run 回读仍 completed，完整 RunView 与回滚前完全一致。[回滚检查](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t11-logs/r18-off-log-and-old-on-immutability-check.json)。
- 最终 `postgres/app/mock-business` 全 healthy，Settings 为 `orchestrator=False embedded_worker=True`，卷及独立 PG17 证据资源保留。两次临时 helper 权限/重建后缺失的注入失败均未创建 Run，修正后未放宽断言。完整命令与边界见 [T11 证据](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t11-evidence.md) 和 [R18 证据](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-final-fix-evidence.md)。
