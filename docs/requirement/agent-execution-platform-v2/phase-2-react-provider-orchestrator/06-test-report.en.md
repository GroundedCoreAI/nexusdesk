# Phase 2 · React Provider and Execution Orchestrator — Test Report

> Status: Completed (local functional exit passed; production performance submetric `pending_env`)
> Created: 2026-11-11
> Basis: `04-test-plan.md` (P2-UT-01–24, P2-IT-01–20, P2-CM-01–08), `05-acceptance-plan.md`, `03-technical-design.md`, `08-implementation-breakdown.md` (R15/R16, T8)
> Executed by: T8 formal test execution agent; date: 2026-11-11

## 1. Test Scope and Environments

**Scope**: This run freshly executed every primary case in 04 and the affected regressions, covering Context/Request UUIDs, ReactAdapter, dual emit, ack/backpressure/no-stream, Orchestrator, Worker, errors/cancellation/timeouts/Leases, internal/Open SSE, real Memory, configuration/mixed Workers/rollback, migrations, and local test-double performance sampling. It did not run full `pytest`, create seeds or 07, or serve as T9 formal acceptance.

| Environment | Configuration | Purpose |
|---|---|---|
| Local host | Darwin 27.0.0; Python 3.11.9; uv 0.11.3 | Non-PG unit/integration tests, Ruff, architecture, and diff checks |
| Dedicated Docker PostgreSQL | `pgvector/pgvector:pg17`; container `nexusdesk-phase2-t6b-pg17-2b1d85c1afb9` | Real asyncpg, Repository, SSE, Memory, mixed Workers, Leases, and migrations |
| ASGI | `httpx.ASGITransport` with actual FastAPI routes | R15 internal/Open cursors, status codes, error bodies, replay, and redaction |
| Models/tools | demo/mock, programmable Runtime/Adapter, controlled Events/gates | Deterministic old/new parity, errors, cancellation, backpressure, and performance-method samples |
| Credentials | Silent injection from a repository-external mode-0600 env file | Connection configuration only; no connection string or credential in logs or reports |

> **Evidence lifecycle (important)**: `/Users/jackchow/.claude/jobs/a2066544/tmp` is a job-local temporary directory, not persistent repository evidence storage. After final resource cleanup for this run, links to its raw logs, node inventories, and performance JSON will become invalid and the original evidence cannot be re-reviewed. The appendices in this report retain only key result summaries and are not long-term archives of original evidence. This run produced no CI artifacts or other approved persistent archive; no archival is implied.

The original T6 database, container, and volume were retained. CM01 created a separate temporary empty database `phase2_t8_cm01_20261111_01` and dropped only that database after verification; the follow-up count was 0. See the [T8 evidence index](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-evidence.md).

**Skip notes**: The six Memory suites collected 158 nodes and produced **156 passed, 2 skipped**. The skips were `test_memory_events_postgres.py::test_p3_ut_02_probe_text_without_vector_column` and `test_p3_ut_03_vector_enabled_true_without_column_still_text`. The current PG17 database has the embedding column, while these alternatives require a degraded database without it; their reasons were `degraded-path assertion needs a database without the embedding column` and `needs a database without the embedding column`. Neither skip counts as a pass, and neither is an uncovered Phase 2 primary case.

## 2. Execution Overview

| Item | Result | Evidence |
|---|---|---|
| Non-PG `p2_` primary selection | 52 passed, 170 deselected in 3.29s | [E01](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-logs/nonpg-p2-selection.log) |
| Two complete core non-PG files | 205 passed in 3.21s | [E02](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-logs/nonpg-core-two-files.log) |
| `not postgres` selection across the reviewed 18-file set (17 files contain non-PG nodes) | 1032 passed, 14 deselected in 5.51s | [E03](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-logs/nonpg-full-reviewed-file-set.log) |
| 26 new T6b PG selections | 26 passed, 89 deselected in 13.17s | [E05](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-logs/pg-new-26.log) |
| Complete `test_runtime_postgres.py` | 45 passed in 9.89s | [E06](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-logs/pg-runtime-full.log) |
| Open + agent-config PG regression | 17 passed in 14.09s | [E07](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-logs/pg-open-agent-config.log) |
| Six Memory suites | 156 passed, 2 skipped in 78.06s | [E08](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-logs/pg-memory-six-suites.log) |
| T7 mixed/rollback/existing-row/settings/path-log selection | 23 passed in 1.88s | [E09](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-logs/pg-t7-mixed-rollback-existing-logs.log) |
| Complete `test_agent_model_required.py` real-PG remediation run | 2 passed in 1.60s | [E19](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-logs/pg-agent-model-required.log) |
| `uv run ruff check src tests` | All checks passed | [E13](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-logs/ruff-check.log) |
| `uv run ruff format --check src` | Whole-tree baseline deviation: 32 pre-existing unchanged files need formatting and 280 are formatted; the 12 Phase 2 source files passed a separate check | [E14a](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-logs/ruff-format.log), [E14b](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-logs/ruff-format-phase2-files.log) |
| Architecture gate | Raw tree failed only for four pre-existing ignored legacy roots; a clean export excluding only those roots passed | [E15](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-logs/architecture-clean-export.log) |
| Temporary-Git-metadata `diff --check` | Passed; original `.git` was not modified | [E16](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-logs/git-diff-check.log) |
| CI | Not executed; no push/PR in this run and no CI URL | §9 |

E01/E02/E03 overlap; E05/E06/E07/E08/E09/E19 also overlap. These counts prove actual execution and **must not be added as unique coverage**. All 14 E03 deselections were postgres-marked nodes: E07 covers 12 and E19 covers the two in `test_agent_model_required.py`; other deselections were covered by complete files or explicit selections.

## 3. Unit Test Results (P2-UT)

Counts below are actual pytest parameter-expanded cases; an unmarked function has one case. Fresh E01/E02/E03 executions cover the non-PG rows except UT16's two PG nodes, which E19 supplies; E05/E06/E09 additionally cover the other PG-related rows.

| ID | Case | Exact test location (expanded cases) | Environment | Result and fresh key evidence |
|---|---|---|---|---|
| P2-UT-01 | Context/Request UUIDs and Agent identity | The 15 unique exact functions in `backend/tests/test_execution_orchestrator.py` listed in Appendix B, 33 cases total | Local | **Passed**; exact stdlib UUIDs, controlled subclass conversion, original row/row.id preservation, malformed/nil/forged snapshot rejection, safe static `INVALID_REQUEST`, ordinary-error redaction, and CancelledError/KeyboardInterrupt rethrow; E02/E03 |
| P2-UT-02 | React identity, capabilities, and start | `backend/tests/test_react_engine_adapter.py::TestReactAdapter::test_capabilities_start_stream_collect_success`(1), `::test_prestart_errors_precede_handle_and_preserve_retryability`(1), `::test_request_identity_mismatch_fails_before_handle`(1); `backend/tests/test_execution_orchestrator.py::test_orchestrator_uses_fresh_adapters_and_isolates_concurrent_runs`(1) | Local | **Passed**; react/native/v1, four true capabilities, Handle UUID, one active execution, duplicate-start rejection, and fresh-instance isolation; E02/E03 |
| P2-UT-03 | Dual emit, first-event handshake, start→stream→collect | `backend/tests/test_react_engine_adapter.py::test_double_emit_first_gate_runtime_inputs_and_private_outcome`(1); `backend/tests/test_execution_orchestrator.py::test_orchestrator_fixed_selector_ack_order_and_single_private_outcome_collection`(1); `backend/tests/test_react_engine_adapter.py::TestReactAdapter::test_multiple_events_preserve_order_payload_and_empty_stream_terminates`(1) | Local | **Passed**; same runner/row/runtime_emit spies, no lost first event, `yield→await worker_emit→ack`, one completed Result, private history/dropped, and empty usage; E02/E03 |
| P2-UT-04 | Empty output, dropped, and usage packaging | `backend/tests/test_execution_orchestrator.py::test_completed_outcome_carries_memory_values_and_react_v1_empty_usage`(1), `::test_non_completed_outcomes_never_carry_memory_values`(2), `::test_private_outcome_has_no_public_serialization_surface`(1); `backend/tests/test_runtime_baseline.py::test_worker_on_completed_outcome_preserves_memory_row_history_and_dropped_verbatim`(1) | Local | **Passed**; public/private React v1 usage is `{}`, non-success writes no Memory, history/dropped remain verbatim, and no private serialization extension exists; E02/E03 |
| P2-UT-05 | Event mapping and forged-event isolation | `backend/tests/test_react_engine_adapter.py::test_double_emit_first_gate_runtime_inputs_and_private_outcome`(1), `::test_malformed_reserved_and_non_json_events_fail_before_worker_emit`(8); `::TestReactAdapter::test_duplicates_late_events_gaps_and_timestamps_follow_sequence_rules`(1), `::test_same_event_id_with_different_content_is_never_repaired`(1) | Local | **Passed**; model/knowledge/memory/extension names and payloads remain intact, forged run.*/tool.replay/non-JSON fails with protocol_error before worker_emit, and UUID/UTC/local sequence values are correct; E02/E03 |
| P2-UT-06 | All error sources, future codes, and timeouts | The 21 functions and 58 expanded cases in `backend/tests/test_react_engine_adapter.py` listed in Appendix F: eight explicit functions/34 cases plus three adversarial groups at five functions/five cases, five functions/ten cases, and three functions/nine cases | Local | **Passed**; 27 Phase 0 matrix cases, unknown RuntimeFault verbatim private code/public internal_error, ordinary unknown exception execution_error, distinct timeouts, descriptor/property redaction, and control-flow rethrow; E02/E03 |
| P2-UT-07 | cancel, aclose, races, and cleanup | `backend/tests/test_react_engine_adapter.py::TestReactAdapter::test_cancel_wins_gate_race_and_suppresses_late_events_and_success`(1), `::test_success_wins_gate_race_and_is_never_retroactively_cancelled`(1), `::test_repeated_concurrent_cancel_closes_stream_and_collectors`(1), `::test_early_aclose_cleans_owned_tasks_and_does_not_permit_replay`(1), `::test_pending_anext_is_woken_by_aclose_without_external_cancel`(1); `backend/tests/test_react_engine_adapter.py::test_cancel_blocked_producer_and_pending_consumer_suppresses_late_completion`(1) | Local | **Passed**; internal first-terminal-wins, idempotent cancel, late-success suppression, aclose waking put/get, no replay after close, and owned tasks done; E02/E03 |
| P2-UT-08 | Fixed selector and invalid combinations | `backend/tests/test_execution_orchestrator.py::test_resolution_failures_return_safe_failed_outcomes_without_fallback`(6), `::test_orchestrator_fixed_selector_ack_order_and_single_private_outcome_collection`(1), `::test_shared_composition_registers_fixed_descriptors_without_per_run_execution`(1) | Local | **Passed**; unknown versions/unregistered/disabled combinations fail safely without latest, legacy, or other-Engine fallback, and requests cannot override the production selector; E02/E03 |
| P2-UT-09 | ack/Outcome protocols and stage failures | `backend/tests/test_execution_orchestrator.py::test_acknowledging_event_stream_is_runtime_checkable_and_detected_structurally`(1), `::test_non_async_acknowledgement_capabilities_are_rejected`(5), `::test_outcome_collecting_adapter_is_private_runtime_checkable_and_async_verified`(1), `::test_protocol_free_public_result_fallback_is_deterministic`(6), `::test_each_execution_stage_failure_cleans_stream_and_returns_safe_failed`(5), `::test_append_cancelled_error_is_not_acknowledged_and_rethrows_after_cleanup`(1), `::test_collect_call_failures_are_execution_error_without_second_collection`(4); `backend/tests/test_react_engine_adapter.py::test_collect_outcome_completed_reuses_terminal_path_and_keeps_public_result_clean`(1), `::test_collect_outcome_failed_preserves_unknown_runtime_fault_legacy_code`(1), `::test_collect_outcome_cancelled_has_no_code_and_handle_validation_is_shared`(1) | Local | **Passed**; real-async/descriptor fail-closed checks, one React private collection, deterministic LocalTest fallback, append CancelledError without ack and rethrown, and unique drain/collect/finish; E02/E03 |
| P2-UT-10 | Worker flag and fingerprint | `backend/tests/test_runtime_baseline.py::test_worker_off_with_injected_orchestrator_uses_only_legacy`(1), `::test_worker_on_never_touches_legacy_factory_or_runtime`(1), `::test_worker_on_without_orchestrator_fails_safely_without_legacy_fallback`(1), `::test_worker_fingerprint_check_precedes_both_execution_paths`(2); `backend/tests/test_execution_orchestrator.py::test_runtime_fingerprint_excludes_only_the_orchestrator_rollout_flag`(1) | Local | **Passed**; mutually exclusive off/on paths, no fallback after on failure, consistent configuration_changed, and flag excluded from the fingerprint; E02/E03 |
| P2-UT-11 | Outcome→finish mapping | `backend/tests/test_runtime_baseline.py::test_worker_on_completed_outcome_preserves_memory_row_history_and_dropped_verbatim`(1), `::test_worker_on_non_completed_outcomes_have_no_memory_or_completion_values`(2), `::test_worker_on_ordinary_execution_failures_are_safely_finished`(3), `::test_worker_on_external_cancellation_cleans_orchestrator_and_finishes_cancelled`(1); `backend/tests/test_execution_orchestrator.py::test_worker_source_has_no_concrete_engine_branch_and_composition_injects_only_when_on`(1) | Local | **Passed**; correct completed/failed/cancelled output/error_code, Memory only on success, one Repository finish, and no Engine branch in Worker; E02/E03 |
| P2-UT-12 | Memory inputs/dropped old/new transfer | `backend/tests/test_runtime_baseline.py::test_p2_it03_truncation_summary_customer_memory_and_reasoning_match_legacy`(1), `::test_worker_on_completed_outcome_preserves_memory_row_history_and_dropped_verbatim`(1), `::test_worker_on_non_completed_outcomes_have_no_memory_or_completion_values`(2); `backend/tests/test_execution_orchestrator.py::test_runtime_memory_reinforce_is_immediately_visible_on_original_worker_row`(1) | Local | **Passed**; summary/customer_memory/history/dropped parity, no writeback on failure/cancellation, and reinforce visible on the original row; E02/E03 |
| P2-UT-13 | Settings default and environment override | `backend/tests/test_execution_orchestrator.py::test_execution_orchestrator_settings_default_and_process_lifetime`(1), `::test_execution_orchestrator_settings_parse_environment`(4), `::test_execution_orchestrator_settings_reject_invalid_environment`(1) | Local | **Passed**; default false, true/false/1/0 parsed correctly, invalid values rejected, and existing instances unaffected by later environment changes; E01/E02/E09 |
| P2-UT-14 | Dependency direction and public serialization | `backend/tests/test_execution_orchestrator.py::test_t2_core_modules_do_not_import_applications_business_or_react_adapter`(1), `::test_public_result_schema_has_no_t2_private_or_engine_metadata_extensions`(1), `::test_private_context_has_no_emit_or_public_serialization_surface`(1), `::test_private_outcome_has_no_public_serialization_surface`(1), `::test_worker_source_has_no_concrete_engine_branch_and_composition_injects_only_when_on`(1); clean-export `scripts/check_architecture.py` | Local/static | **Passed**; Core/Worker dependency boundaries and Context/Outcome/Result public surfaces remain unchanged, and the clean-export architecture gate passed; E02/E03/E15 |
| P2-UT-15 | ContextVar concurrency, nesting, and reset | `backend/tests/test_execution_orchestrator.py::test_scope_captures_context_into_new_object_without_later_contextvar_reads`(1), `::test_nested_scope_restores_outer_context_and_finally_clears_it`(1), `::test_scope_resets_after_resolve_failure_without_leaking_raw_context`(1), `::test_missing_or_wrong_context_fails_safely`(1), `::test_context_scope_is_isolated_between_concurrent_tasks`(1), `::test_react_adapter_factory_synchronously_captures_fresh_context_without_running_runtime`(1); `backend/tests/test_react_engine_adapter.py::test_adapter_never_reads_contextvar_after_explicit_capture`(1) | Local | **Passed**; concurrent isolation, nested restoration, finally reset after resolution/factory errors, safe missing/wrong Context failure, and no ContextVar read after Adapter creation; E02/E03 |
| P2-UT-16 | Fresh multi-Run instances and private isolation | `backend/tests/test_execution_orchestrator.py::test_orchestrator_uses_fresh_adapters_and_isolates_concurrent_runs`(1); `backend/tests/test_react_engine_adapter.py::TestReactAdapter::test_deterministic_fresh_runs_have_no_cross_instance_high_water`(1); `backend/tests/test_react_engine_adapter.py::test_parallel_emit_preserves_sequence_and_queue_order_under_capacity_one`(1); `backend/tests/test_agent_model_required.py::test_missing_model_draft_publish_legacy_run_and_rollback`(1), `::test_captured_unconfigured_run_never_uses_default`(1) | Local + PG17 | **Passed**; queue/runner/result/gate/row/history/emit are not shared and ack is execution-scoped; the two real-PG nodes prove agent_model_required for missing-model publish/legacy Run/rollback and that a captured unconfigured Run never invokes the default model; E02/E03/[E19](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-logs/pg-agent-model-required.log) |
| P2-UT-17 | Capacity one, slow delivery, and structured ack | `backend/tests/test_react_engine_adapter.py::test_capacity_one_slow_delivery_backpressure_and_exactly_once_ack`(1), `::test_ack_rejects_no_inflight_wrong_identity_and_cross_execution_then_aborts`(1), `::test_settled_ack_idempotence_is_active_only_and_terminal_releases_identities`(1); `backend/tests/test_execution_orchestrator.py::test_orchestrator_fixed_selector_ack_order_and_single_private_outcome_collection`(1) | Local | **Passed**; bare yield does not settle delivery, exactly-once ack follows successful worker_emit only, settled duplicates are idempotent, and wrong identity/cross-Run/no-in-flight aborts; E02/E03 |
| P2-UT-18 | no-stream, state machine, and terminal publication gate | `backend/tests/test_react_engine_adapter.py::test_no_stream_suppression_has_no_replay_and_unacked_event_gates_result`(1), `::test_emit_after_successful_return_is_suppressed_while_first_event_awaits_ack`(1), `::test_blocked_emitter_wakes_on_producer_finished_without_joining_drained_events`(1); `::TestReactAdapter::test_terminal_visibility_never_precedes_queued_or_active_stream_events`(1), `::test_claimed_empty_stream_does_not_block_successful_collection`(1), `::test_delivered_only_event_does_not_require_an_extra_poll_before_result`(1) | Local | **Passed**; never-claimed gate, explicit suppression, no replay, no terminal publication before ack, collectible idle claimed stream, and safe closed/terminal completion; E02/E03 |
| P2-UT-19 | collect/stream races and collector cancellation | `backend/tests/test_react_engine_adapter.py::TestReactAdapter::test_immediate_concurrent_and_repeated_collectors_share_result`(1), `::test_one_cancelled_collector_does_not_cancel_shared_execution`(1), `::test_lone_collector_cancellation_cleans_owned_work_before_propagation`(1), `::test_concurrent_second_consumer_and_claim_after_aclose_are_rejected`(1); `backend/tests/test_react_engine_adapter.py::test_collect_outcome_shared_collectors_and_lone_cancellation_match_public_semantics`(1) | Local | **Passed**; first choice wins, collectors receive one equal Result, shared collectors are shielded, and lone no-stream cancellation cleans up before rethrow; E02/E03 |
| P2-UT-20 | stream/protocol/emit/Notifier error boundaries | `backend/tests/test_react_engine_adapter.py::test_worker_emit_failure_and_append_cancellation_have_distinct_cleanup`(1), `::test_swallowed_notifier_delta_failure_acks_but_other_emit_failure_fails`(1), `::test_safe_worker_emit_exception_abort_still_uses_internal_execution_error`(1), `::test_taskgroup_failures_preserve_prior_events_and_stable_error_mapping`(3); `::TestReactAdapter::test_stream_errors_are_safe_for_stream_and_all_collectors`(6) | Local | **Passed**; runner errors propagate safely and publish failed, ordinary emit aborts/closes, designated swallowed Notifier delta failures ack normally, other exceptions fail, and tasks are cleaned; E02/E03 |
| P2-UT-21 | Exact reuse/replacement of 25 public Adapter functions | The 25 exact functions in `backend/tests/test_react_engine_adapter.py::TestReactAdapter` listed in Appendix C, 34 cases total; `backend/tests/test_react_engine_adapter.py::test_public_contract_has_exactly_nineteen_reuses_and_six_private_replacements`(1) | Local | **Passed**; 19 original functions inherited and executed individually (28 expanded cases), six same-purpose private replacements (six cases), and streaming harness explicitly performs `anext→worker_emit→ack`; E02/E03 |
| P2-UT-22 | Serial/parallel parity and canonicalizer | `backend/tests/test_execution_orchestrator.py::test_p2_ut22_serial_canonicalizer_normalizes_only_documented_instance_fields`(1), `::test_p2_ut22_model_call_messages_prompt_content_and_business_remain_diffs`(4), `::test_p2_ut22_serial_business_order_sequence_usage_and_replay_remain_diffs`(9), `::test_p2_ut22_rejects_wrong_types_and_negative_durations_before_normalizing`(8), `::test_p2_ut22_rejects_missing_model_timing_fields`(3), `::test_p2_ut22_parallel_tools_compare_by_call_id_and_preserve_model_rounds`(1), `::test_p2_ut22_parallel_rejects_completion_before_start_and_round_movement`(1), `::test_p2_ut22_unowned_parallel_events_are_per_round_multisets_not_global`(1), 29 cases total | Local | **Passed**; strict field validation, model_calls/business IDs/arguments/results/output/error/usage remain diffable, raw_latency is stored separately, and call_id partial order/per-round multiset work; E01/E02/E03 |
| P2-UT-23 | monitor_failure, Lease loss, stale append/finish, and commit order | `backend/tests/test_runtime_baseline.py::test_worker_on_monitor_cancels_the_same_orchestrator_task`(2); `backend/tests/test_execution_orchestrator.py::test_append_cancelled_error_is_not_acknowledged_and_rethrows_after_cleanup`(1); `backend/tests/test_runtime_postgres.py::test_p2_it09_running_first_commit_wins_for_cancel_finish_and_reaper`(4), `::test_p2_it09_queued_reaper_cancel_orders_and_cancelled_queue_timeout`(2), `::test_p2_it11_stale_react_append_rethrows_cleans_and_preserves_terminal`(3), `::test_p2_it11_worker_heartbeat_loss_is_worker_lost_not_user_cancellation`(1) | Local + PG17 | **Passed**; user cancellation differs from worker_lost, stale finish is a no-op, stale/cancelled/expired append neither acks nor persists and rethrows, and both first-commit-wins orders plus reaper variants pass; E02/E05/E06/E09 |
| P2-UT-24 | Fixed descriptors and low-cardinality observability | `backend/tests/test_execution_orchestrator.py::test_shared_composition_registers_fixed_descriptors_without_per_run_execution`(1); `backend/tests/test_runtime_baseline.py::test_worker_on_logs_only_low_cardinality_path_and_outcome`(1), `::test_worker_on_known_outcomes_keep_controlled_log_labels`(3), `::test_worker_on_terminal_log_uses_controlled_monotonic_duration`(1), `::test_real_react_orchestrator_worker_never_logs_unknown_legacy_code`(1) | Local | **Passed**; all six actual INFO lines contain path=orchestrator, tuple=react/native/v1, controlled status/error, and finite non-negative duration; no input/history/secrets/unknown legacy code; E04 |

## 4. Integration Test Results (P2-IT)

| ID | Case | Exact test location (expanded cases) | Environment | Result and fresh key evidence |
|---|---|---|---|---|
| P2-IT-01 | No-snapshot fixed text off/on | `backend/tests/test_runtime_baseline.py::test_p2_it01_no_snapshot_fixed_model_off_on_real_worker_parity`(1) | Local real RuntimeFactory/test double | **Passed**; real base_runtime old/new calls and strict output/history/dropped/event/usage/terminal parity, with no nil leakage; E01/E02/E03 |
| P2-IT-02 | Published snapshot, Profile, language, multiround tools | `backend/tests/test_agent_config_execution_compat.py::test_p2_it02_published_snapshot_language_and_multiround_tool_parity`(1) | Local | **Passed**; real snapshot Agent UUID, same Profile/tools/messages/budget, equivalent replies/events, and unchanged snapshot; E01/E03 |
| P2-IT-03 | Truncation, summary, customer_memory, reasoning | `backend/tests/test_runtime_baseline.py::test_p2_it03_truncation_summary_customer_memory_and_reasoning_match_legacy`(1) | Local | **Passed**; matching message order, dropped, successful memory_context, and reasoning-history retention/invisibility; E01/E02/E03 |
| P2-IT-04 | Complete new path and dual-emit boundary | `backend/tests/test_agent_config_execution_compat.py::test_p2_it04_full_new_path_owns_one_private_stream_and_public_delivery`(1); `backend/tests/test_execution_orchestrator.py::test_real_react_orchestration_preserves_dual_emit_order_and_unknown_legacy_code`(1), `::test_worker_source_has_no_concrete_engine_branch_and_composition_injects_only_when_on`(1) | Local | **Passed**; private runtime_emit/public worker_emit ordering, ack, one private Outcome collection, one finish, and no emit in Context; E01/E02/E03 |
| P2-IT-05 | Internal SSE R15, 200+ drain, and delta | `backend/tests/test_runtime_baseline.py::test_p2_it05_internal_sse_replay_delta_cursor_and_hidden_replay_parity`(1), `::test_p2_it05_internal_sse_last_event_id_drain_and_invalid_cursor`(1); `backend/tests/test_runtime_postgres.py::test_p0_it_07_internal_sse_after_and_last_event_id_use_strict_max`(1), `::test_p0_it_07_internal_sse_drains_more_than_200_events_before_terminal`(1), `::test_p0_it_07_internal_sse_does_not_replay_transient_model_delta`(1), `::test_p0_it_07_internal_sse_hides_terminal_tool_replay_and_advances_cursor`(1), `::test_p2_it20_real_pg_internal_run_scope_redaction_and_r15_errors`(1) | Local ASGI + PG17 ASGI | **Passed**; four manual-header forms return 400/`invalid_last_event_id`, four typed-after forms return 422; valid max/strict replay, IDs 1..204, no-ID delta is not replayed, and tool.replay is hidden while advancing the cursor; Appendix D, E01/E03/E05/E06 |
| P2-IT-06 | Open SSE R15, tool.replay, and redaction | `backend/tests/test_open_platform.py::test_p2_it06_open_sse_redaction_hidden_replay_and_cursor`(1), `::test_p2_it06_open_sse_typed_invalid_cursor_and_last_event_id`(1), `::test_p2_it20_real_pg_open_sse_drain_cursor_delta_and_authorization`(1) | Local ASGI + PG17 ASGI | **Passed**; three Open typed-header forms and four after forms return 422; valid max/strict replay, 201 extension events drained, and tool.replay/private fields hidden; Appendix D, E01/E03/E05/E07 |
| P2-IT-07 | All error sources and future unknown codes | `backend/tests/test_runtime_baseline.py::test_p2_it07_real_chain_failures_keep_legacy_codes_and_safe_logs`(4); full 27-case matrix under P2-UT-06 | Local | **Passed**; persisted legacy codes match public known mappings/internal_error, ordinary exceptions map to execution_error, and logs/APIs contain no sensitive source text; E01/E02/E03 |
| P2-IT-08 | Cancellation while waiting for model and repeated cancel | `backend/tests/test_runtime_baseline.py::test_p2_it08_cancel_waiting_model_repeat_cancel_and_late_release`(2) | Local, off/on | **Passed**; model task is actually cancelled and cleaned, final state is cancelled with empty output, and late release creates no second terminal; E01/E02/E03 |
| P2-IT-09 | Real-PG cancel/finish/reaper commit orders | `backend/tests/test_runtime_postgres.py::test_p2_it09_running_first_commit_wins_for_cancel_finish_and_reaper`(4), `::test_p2_it09_queued_reaper_cancel_orders_and_cancelled_queue_timeout`(2) | PG17 | **Passed**; first-commit-wins for both finish/reaper-first and cancel-first, one terminal, and retained worker_lost/queue_timeout variants; E05/E06/E09 |
| P2-IT-10 | model_timeout and run_timeout | `backend/tests/test_runtime_baseline.py::test_p2_it10_model_and_outer_run_timeout_parity_without_retry`(2) | Local | **Passed**; failed/model_timeout and failed/run_timeout respectively, no automatic retry, and tasks cleaned; E01/E02/E03 |
| P2-IT-11 | Late finish/append after Lease/reap | `backend/tests/test_runtime_postgres.py::test_p2_it11_stale_react_append_rethrows_cleans_and_preserves_terminal`(3), `::test_p2_it11_worker_heartbeat_loss_is_worker_lost_not_user_cancellation`(1); same-file `test_p0_it_06_terminal_rejects_late_append_and_repeat_finish`, `test_p0_it_06_wrong_owner_finish_and_append_do_not_write`, and `test_p0_it_06_expired_lease_rejects_append_and_finish`, one each | PG17 | **Passed**; Lease loss is not user cancellation, stale finish is a silent no-op, and append CancelledError neither acks nor persists nor rewrites the original terminal; E05/E06 |
| P2-IT-12 | off/on, mixed Workers, and rollback | `backend/tests/test_runtime_postgres.py::test_p2_it18_mixed_workers_exclusive_claim_parity_and_all_off_rollback`(1); 12 configuration/path cases from P2-UT-10/13 | PG17 + local | **Passed**; off-API rows are exclusively claimed by distinct on/off owners with equal results/events and no configuration_changed; after all-off rollback new Runs complete and existing terminals remain unchanged; E02/E05/E06/E09 |
| P2-IT-13 | Fail-fast after registry removal/disable | `backend/tests/test_execution_orchestrator.py::test_resolution_failures_return_safe_failed_outcomes_without_fallback`(6) | Local | **Passed**; all six resolution failures return safe failed outcomes without silent legacy or version fallback; E02/E03 |
| P2-IT-14 | Independent LocalTest Registry through the same Orchestrator/Worker | `backend/tests/test_execution_orchestrator.py::test_p2_it14_real_local_test_orchestrator_worker_repository_end_to_end`(4), `::test_real_local_test_uses_separate_selector_public_collect_and_no_private_ack`(2), `::test_protocol_free_public_result_fallback_is_deterministic`(6), `::test_real_local_external_adapter_cancel_returns_orchestrator_cancelled_fallback`(1) | Local | **Passed**; real LocalTest uses independent local-test/scripted/v1, yield=delivery, no private ack/Outcome, deterministic completed/failure/timeout/external-cancel mappings, and task cleanup; E02/E03 |
| P2-IT-15 | Parallel tools and extension business-event parity | `backend/tests/test_runtime_baseline.py::test_p2_it15_parallel_tools_and_business_events_keep_stable_payloads`(1); three parallel functions under P2-UT-22, one each | Local | **Passed**; call_id started/completed alignment, local partial order and model-round boundaries, per-round multiset without call_id, and unchanged stable payload/usage; E01/E02/E03 |
| P2-IT-16 | PG slow worker_emit, backpressure, failures, and late results | `backend/tests/test_runtime_postgres.py::test_p2_it16_real_pg_capacity_one_ack_backpressure_and_terminal_order`(1), `::test_p2_it16_emit_failure_and_cancelled_append_suppress_late_results`(2) | PG17 | **Passed**; capacity one does not deadlock and ack follows successful emit only; ordinary failure is failed, CancelledError is unacked/rethrown, late success does not overwrite, and tasks are cleaned; E05/E06 |
| P2-IT-17 | Real Memory transaction categories | `backend/tests/test_memory_postgres.py::test_p2_exec_it17_summary_history_dropped_off_on_real_pg`(2), `::test_p2_exec_it17_failure_and_cancel_have_no_memory_writeback`(4); `backend/tests/test_memory_customers_postgres.py::test_p2_exec_it17_extract_customer_injection_and_original_row_off_on`(2); plus all 158 nodes in six suites | PG17 | **Passed**; eight Phase 2 expanded cases and 156 suite cases passed; summary/history/dropped/extract/reinforce/injection, commit/rollback, no failure/cancel writeback, and tenant isolation; two alternate-environment skips listed separately, E05/E08 |
| P2-IT-18 | Existing rows, mixed claim, and real asyncpg UUID chain | `backend/tests/test_runtime_postgres.py::test_p2_it18_real_pg_claimed_uuid_enters_execution_context`(1), `::test_p2_it18_mixed_workers_exclusive_claim_parity_and_all_off_rollback`(1), `::test_p0_it_01_queued_claim_completed_lifecycle_persists_exact_state`(1), `::test_p0_it_04_reaper_cancelled_expired_running_lease_keeps_worker_lost`(1), `::test_p0_it_06_terminal_rejects_late_append_and_repeat_finish`(1) | PG17 real asyncpg | **Passed**; original asyncpg UUID-subclass object traverses Context→actual Adapter Request→application RuntimeFactory, original row/row.id object/type/value are unchanged, Request uses exact stdlib UUID, and existing queued/running/terminal rows plus rollback need no repair; Appendix D, E05/E06/E09 |
| P2-IT-19 | Dynamic Alembic empty DB and zero directory drift | `backend/tests/test_runtime_postgres.py::test_p2_it19_real_pg_dynamic_alembic_head_matches_current`(1); temporary empty-DB `alembic upgrade head`, `heads`, `current`; SHA256 comparison of 57 files | PG17 + static | **Passed**; upgrade succeeded, heads/current both `0057_industry_pack_runtime (head)`; 57/57 with zero path/hash drift and no downgrade; E05/E06/E10/E11 |
| P2-IT-20 | Cross-tenant Run/SSE, identity, and observability adversarial checks | `backend/tests/test_runtime_postgres.py::test_p2_it20_real_pg_internal_run_scope_redaction_and_r15_errors`(1); `backend/tests/test_open_platform.py::test_p2_it20_real_pg_open_sse_drain_cursor_delta_and_authorization`(1); `backend/tests/test_execution_orchestrator.py::test_p2_it20_forged_or_nil_agent_fails_before_registry_or_legacy_query`(1); `backend/tests/test_runtime_baseline.py::test_p2_it20_public_run_view_and_observability_exclude_private_fields`(1) | Local + PG17 ASGI | **Passed**; tenant/business/workspace filtering, cross-identity 403/404, forged/nil Agent rejected before Registry/query, no private fields in RunView/SSE, and no run_id in metrics; E01/E03/E05/E06/E07 |

## 5. Cross-Cutting Checks (P2-CM)

| ID | Check | Exact test location/check | Environment | Result and fresh evidence |
|---|---|---|---|---|
| P2-CM-01 | Migration and existing-row compatibility | P2-IT-19; `backend/tests/test_runtime_postgres.py::test_p2_it18_mixed_workers_exclusive_claim_parity_and_all_off_rollback`, `::test_p0_it_01_queued_claim_completed_lifecycle_persists_exact_state` | PG17 + static | **Passed**; empty-DB upgrade/heads/current, zero drift across 57 files, existing rows and rollback passed; temporary DB dropped and original DB/container/volume retained; E05/E06/E09–E11/E18 |
| P2-CM-02 | Configuration loading and default fallback | `backend/tests/test_execution_orchestrator.py::test_execution_orchestrator_settings_default_and_process_lifetime`(1), `::test_runtime_fingerprint_excludes_only_the_orchestrator_rollout_flag`(1); `backend/tests/test_runtime_baseline.py::test_worker_on_without_orchestrator_fails_safely_without_legacy_fallback`(1); also reuses P2-UT-10/13 and P2-IT-01/12/13 | Local + PG17 | **Passed**; default off, environment override, fingerprint exclusion, off/on parity, and no fallback after on failure; E01/E02/E05/E09 |
| P2-CM-03 | Audit, logs, and observability | `backend/tests/test_runtime_baseline.py::test_worker_on_logs_only_low_cardinality_path_and_outcome`(1), `::test_worker_on_terminal_log_uses_controlled_monotonic_duration`(1); P2-UT-24 contains five functions/seven cases total, of which E04's four Worker logging functions contain six cases and all six emit live INFO | Local | **Passed**; six actual path/tuple/status/error/duration lines, controlled `duration_ms=125.000`, and no secrets/raw stack/nil; these are test logs, not production traces/metrics; E04 |
| P2-CM-04 | Multi-tenancy and public data surface | `backend/tests/test_runtime_postgres.py::test_p2_it20_real_pg_internal_run_scope_redaction_and_r15_errors`(1); `backend/tests/test_open_platform.py::test_p2_it20_real_pg_open_sse_drain_cursor_delta_and_authorization`(1); also reuses the other P2-IT-20 functions and P2-IT-02 | Local + PG17 | **Passed**; cross-tenant/workspace requests are unreachable, public RunView/Open SSE field sets remain fixed, and no Outcome/Context/config/history/gateway internals leak; E03/E05–E07 |
| P2-CM-05 | API/SSE/Agent-config/frontend compatibility | `backend/tests/test_runtime_postgres.py::test_p0_it_07_internal_sse_after_and_last_event_id_use_strict_max`(1); `backend/tests/test_open_platform.py::test_p2_it20_real_pg_open_sse_drain_cursor_delta_and_authorization`(1); `backend/tests/test_agent_config_execution_compat.py::test_p2_it02_published_snapshot_language_and_multiround_tool_parity`(1); also reuses P2-IT-05/06/20, protected-surface path checks, and Phase 1 regressions | Local + PG17 + static | **Passed**; actual R15 route matrix in Appendix D; zero changed migration/ORM/public-route/schema/frontend paths, with public status/error bodies regressed through actual routes; E03/E05–E07/E16 |
| P2-CM-06 | Async resources and code quality | `backend/tests/test_react_engine_adapter.py::TestReactAdapter::test_early_aclose_cleans_owned_tasks_and_does_not_permit_replay`(1); `backend/tests/test_runtime_postgres.py::test_p2_it16_emit_failure_and_cancelled_append_suppress_late_results`(2); also reuses P2-UT-07/09/18–20, P2-IT-08/10/14/16, Ruff, format, architecture, and `diff --check` | Local + PG17 + static | **Passed (functional and Phase 2 changes)**; owned tasks done after success/failure/cancel/aclose/rollback; lint, 12 Phase 2 source-file format checks, clean-export architecture, and whitespace checks passed. Whole `src` has 32 pre-existing format deviations with zero overlap; see R-02. Whole-tree format success is not claimed; E02/E03/E06/E13–E16 |
| P2-CM-07 | Phase 1 protection, dual emit, and event ownership | `backend/tests/test_agent_config_execution_compat.py::test_p2_it04_full_new_path_owns_one_private_stream_and_public_delivery`(1); `backend/tests/test_react_engine_adapter.py::test_public_contract_has_exactly_nineteen_reuses_and_six_private_replacements`(1); also reuses P2-UT-03/05/09/14/21, P2-IT-04–07/14, and the 18-file regression | Local + PG17 | **Passed**; public DTO/Registry/LocalTest and RuntimeEngine/Factory semantics remain intact, worker_emit belongs only to Orchestrator, runtime_emit only to the private Runtime chain, forged events never reach worker_emit, and delta has no durable seq; E02/E03/E05–E07/E16 |
| P2-CM-08 | Evidence integrity, functional exit, and performance boundary | `backend/tests/test_execution_orchestrator.py::test_p2_cm08_performance_sampler_records_raw_pairs_and_pending_environment`(1); independent recomputation of `phase2-t8-performance.json` | Local test double | **Passed (evidence integrity/method)**; five warm-ups, 30 valid matched pairs, zero errors, 15/15 order, nearest-rank item 29 for N30; raw metrics complete, raw latency absent from canonical diff, and external latency not subtracted; production performance `pending_env`, no target claim; E01/E12 |

## 6. Regression Scope

This run applied `-m 'not postgres'` to the following reviewed 18-file set, producing **1032 passed, 14 deselected**; this was not full pytest. Seventeen files contained executed non-PG nodes. `test_agent_model_required.py` contributed only two deselected PG nodes and was executed completely under real PG17 in E19, so this group must not be described as 18 completely executed non-PG files:

- `test_execution_orchestrator.py`, `test_react_engine_adapter.py`, `test_runtime_baseline.py`, `test_runtime_baseline_fixtures.py`, `test_runtime_baseline_tooling.py`;
- `test_agent_config_execution_compat.py`, `test_open_platform.py`, `test_memory_summary.py`;
- `test_local_test_adapter.py`, `test_runtime_engine.py`, `test_memory_config.py`, `test_memory_governance.py`, `test_memory_injection.py`;
- `test_agent_execution_contracts.py`, `test_agent_execution_registries.py`, `test_extension_contracts.py`, `test_agent_model_required.py`, `test_agent_languages.py`.

Real PG additionally ran complete `test_runtime_postgres.py` (45), Open+agent-config (17), six Memory suites (156 passed/2 skipped), complete `test_agent_model_required.py` (2), 26 new selections, and 23 T7 selections. Groups overlap and are not cumulatively counted. Protected-path checks show zero migration/ORM/public-route/schema/frontend changes. T8 did not modify production code, tests, migrations, or frontend files.

## 7. Defects Found and Fixed During the Iteration

These are historical records from earlier review/implementation steps. This run found no new functional defect and has no open P0/P1. The fix column deliberately contains no invented SHA.

| # | Severity | Defect/review item | Found during | Fix commit | Current regression |
|---|---|---|---|---|---|
| D-01 | P1 (document contract) | R15 documentation conflict over 400/422 for internal manual Last-Event-ID versus typed after/Open typed cursors, risking incompatible expectations | Specification review | Fixed in the worktree; no commit was authorized in this phase. | Actual internal/Open ASGI matrices and valid max/strict replay all passed; IT05/06, CM05 |
| D-02 | P1 (production implementation) | Real `repo.claim()` returned an asyncpg UUID subclass rejected by the original exact-type Context check; the real-PG chain once produced 44 passed/1 failed | T6b R16 real PG | Fixed in the worktree; no commit was authorized in this phase. | All 33 UT01 cases and IT18 original row→Context→Request→RuntimeFactory passed without fixture preconversion |
| D-03 | P1 (implementation/coverage) | Six T6 specification-review gaps, including the no-snapshot real application Factory chain, LocalTest end-to-end through the same Orchestrator/Worker, canonicalizer suppression of model_calls/business diffs, the CM03 duration production omission, and the other specified coverage gaps | T6 specification review/T5 remediation | Fixed in the worktree; no commit was authorized in this phase. | IT01/04/14/15, UT22/24, CM03/07/08 passed; real Factory spies, four LocalTest E2E cases, 29 canonicalizer cases, and actual duration logs verified |
| D-04 | P1 (test reliability) | Undersized scheduling watchdogs and incomplete cleanup on cancellation/gated paths could cause environment-dependent failures or hangs | T6 quality review | Fixed in the worktree; no commit was authorized in this phase. | Cancellation, monitor, LocalTest, backpressure, and real-PG resource cleanup passed without hanging tasks |
| D-05 | P1 (test false green) | Postconditions could previously run after `finally` cleanup, creating a false-green branch when an unfinished owned task was injected | T6 adversarial quality review | Fixed in the worktree; no commit was authorized in this phase. | Owned-task assertions now take effect before cleanup; UT07/09/18–20 and IT08/14/16 passed |
| D-06 | P2 (documentation quality) | T7 runbooks conflated app healthcheck with runtime-worker running state and lacked clarity on command working directory/env source, one-off canary override scope, and reproducible evidence scripts | T7 quality review | Fixed in the worktree; no commit was authorized in this phase. | This run rechecked the corresponding run/rollback functional nodes and logs; documentation review is not presented as live production deployment |

## 8. Residual Risks and Boundaries

| # | Severity | Description | Disposition |
|---|---|---|---|
| R-01 | Environment pending | Real external-model/tool production performance was not measured; the test-double ratio is neither a production target nor regression conclusion | Only the performance submetric remains `pending_env`; T9 can be conditional at most and must obtain real same-environment matched-pair evidence under 05 §4 |
| R-02 | P2/pre-existing baseline | Whole-`src` format check found 32 files needing formatting; their overlap with Phase 2 changes is zero, and all 12 Phase 2 source files passed | Do not reformat out of scope in T8; handle in a separate baseline-format cleanup. This report must not be read as whole-tree format success |
| R-03 | Environment limitation | The raw worktree contains four pre-existing ignored legacy roots, `modules/apps/integrations/platform`, causing the raw architecture gate to fail | A clean source export excluding only those four roots passed; no user files were deleted. A clean CI checkout remains authoritative, but CI was not run |
| R-04 | Pending T9 | No production canary, deployment traces/metrics, real external-model performance, human UAT, or sign-off | Remains unexecuted and is not fabricated in 06; T9/the relevant environment tasks must supply evidence |
| R-05 | Environment limitation | Original `.git` has a macOS macl restriction | Repository-external temporary metadata was used for read-only diff/status; original `.git` was untouched, and direct `.git` success is not claimed |

## 9. CI Evidence

- **Not executed**. This run created no commit, push, or PR, so there is no CI run, head SHA, or URL.
- Local affected tests and static checks do not replace CI full unit/postgres/frontend results.
- This report does not claim full pytest, production deployment, production performance, human UAT, or formal acceptance.

## 10. Exit Conclusion

**Local functional exit passed; production performance submetric `pending_env`.** Every P2-UT-01–24, P2-IT-01–20, and P2-CM-01–08 row has fresh evidence from this run; all functional primary cases passed, and CM08 evidence integrity/measurement boundaries passed. The two Memory skips are alternate-environment cases and do not count as passes. This conclusion permits entry into T9 but is not complete Phase 2 acceptance; without production performance evidence, T9 can be conditional at most.

## Appendix A Local Output and Evidence Snapshots

> This appendix contains only key result summaries; see §1 for the temporary original-evidence link lifecycle and their non-reviewability after cleanup.

| Evidence | Raw output summary | Link |
|---|---|---|
| A-01 | `52 passed, 170 deselected in 3.29s` | [nonpg-p2-selection.log](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-logs/nonpg-p2-selection.log) |
| A-02 | `205 passed in 3.21s` | [nonpg-core-two-files.log](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-logs/nonpg-core-two-files.log) |
| A-03 | `1032 passed, 14 deselected in 5.51s` | [nonpg-full-reviewed-file-set.log](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-logs/nonpg-full-reviewed-file-set.log) |
| A-04 | `26 passed, 89 deselected in 13.17s` | [pg-new-26.log](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-logs/pg-new-26.log) |
| A-05 | `45 passed in 9.89s` | [pg-runtime-full.log](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-logs/pg-runtime-full.log) |
| A-06 | `17 passed in 14.09s` | [pg-open-agent-config.log](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-logs/pg-open-agent-config.log) |
| A-07 | `156 passed, 2 skipped in 78.06s` | [pg-memory-six-suites.log](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-logs/pg-memory-six-suites.log) |
| A-08 | `23 passed in 1.88s` | [pg-t7-mixed-rollback-existing-logs.log](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-logs/pg-t7-mixed-rollback-existing-logs.log) |
| A-09 | `6 passed in 0.64s`; six controlled path-log lines | [worker-path-logs.log](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-logs/worker-path-logs.log) |
| A-10 | `All checks passed!` | [ruff-check.log](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-logs/ruff-check.log) |
| A-11 | `12 files already formatted`; 32 additional pre-existing whole-tree deviations | [Phase 2 format](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-logs/ruff-format-phase2-files.log), [baseline attribution](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-logs/ruff-format-baseline-attribution.log) |
| A-12 | `architecture gate passed` (clean export) | [architecture-clean-export.log](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-logs/architecture-clean-export.log) |
| A-13 | 57/57 migration files; added/removed/sha256_changed all empty | [migration-drift.log](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-logs/migration-drift.log) |
| A-14 | 5 warm-ups, 30 pairs, 0 errors, 15/15, item 29 | [performance verification](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-logs/performance-independent-verification.log), [raw JSON](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-performance.json) |
| A-15 | `2 passed in 1.60s`; two real-PG nodes in `test_agent_model_required.py` | [pg-agent-model-required.log](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-logs/pg-agent-model-required.log) |

## Appendix B Exact P2-UT-01 Functions and Expanded Counts

All functions are in `backend/tests/test_execution_orchestrator.py`.

| Function | Count | Key assertion |
|---|---:|---|
| `test_snapshot_request_uses_claimed_row_and_real_agent_uuid_without_stringifying` | 1 | Exact stdlib UUID, real Agent UUID, react/native/v1 |
| `test_snapshot_agent_uuid_accepts_only_real_uuid_values` | 2 | Controlled parsing of UUID object/string |
| `test_missing_malformed_or_nil_snapshot_agent_identity_fails_closed` | 9 | Missing, empty, malformed, and nil fail safely |
| `test_malformed_run_config_or_snapshot_never_falls_back_to_legacy` | 4 | Malformed config never falls back to legacy |
| `test_request_mapping_access_failures_are_safe_invalid_requests` | 3 | Ordinary Mapping errors become safe redacted INVALID_REQUEST |
| `test_request_snapshot_config_access_failure_is_safe_invalid_request` | 1 | Snapshot-config access error is safe and redacted |
| `test_request_mapping_control_flow_is_not_swallowed` | 2 | CancelledError/KeyboardInterrupt rethrown by original type |
| `test_only_react_no_snapshot_legacy_request_uses_internal_anonymous_sentinel` | 1 | UUID(int=0) only in the restricted no-snapshot case |
| `test_claimed_execution_id_must_be_a_uuid` | 3 | String/None/integer rejected |
| `test_uuid_subclass_is_normalized_without_rewriting_claimed_row_identity` | 1 | Subclass converted to exact stdlib; original row/row.id unchanged |
| `test_execution_context_rejects_mismatched_uuid_values` | 1 | Mismatched values rejected; `is` does not replace value equality |
| `test_non_uuid_fake_with_uuid_string_is_rejected` | 1 | Forged non-UUID `__str__` rejected |
| `test_malicious_uuid_subclass_string_failure_is_safe_and_redacted` | 1 | Malicious ordinary `__str__` error made safe and redacted |
| `test_uuid_type_descriptor_failure_is_safe_and_redacted` | 1 | Ordinary descriptor error made safe and redacted |
| `test_uuid_subclass_string_control_flow_is_rethrown` | 2 | Original control-flow object rethrown |
| **Total (15 unique functions)** | **33** | E02/E03; real asyncpg chain also under IT18 |

## Appendix C Exact 25-Function Public Adapter List for P2-UT-21

Locations are `backend/tests/test_react_engine_adapter.py::TestReactAdapter::<function>`. The 19 “reused” functions are inherited and individually executed from `tests/agent_execution/adapter_contract_suite.py`; the six “private replacements” cover the same purposes in the React harness. Total: 25 functions and 34 expanded cases; the guard function adds one case.

| Function | Disposition | Count |
|---|---|---:|
| `test_capabilities_start_stream_collect_success` | Private replacement | 1 |
| `test_immediate_concurrent_and_repeated_collectors_share_result` | Reused | 1 |
| `test_concurrent_second_consumer_and_claim_after_aclose_are_rejected` | Reused | 1 |
| `test_multiple_events_preserve_order_payload_and_empty_stream_terminates` | Reused | 1 |
| `test_request_identity_mismatch_fails_before_handle` | Reused | 1 |
| `test_prestart_errors_precede_handle_and_preserve_retryability` | Private replacement | 1 |
| `test_stream_errors_are_safe_for_stream_and_all_collectors` | Reused | 6 |
| `test_pre_chained_safe_stream_error_does_not_retain_raw_exception_chain` | Reused | 1 |
| `test_unknown_exception_and_simulated_process_failure_are_distinct_and_safe` | Private replacement | 1 |
| `test_manual_clock_timeout_wakes_collectors_without_real_waiting` | Reused | 1 |
| `test_repeated_concurrent_cancel_closes_stream_and_collectors` | Reused | 1 |
| `test_cancel_wins_gate_race_and_suppresses_late_events_and_success` | Reused | 1 |
| `test_success_wins_gate_race_and_is_never_retroactively_cancelled` | Reused | 1 |
| `test_duplicates_late_events_gaps_and_timestamps_follow_sequence_rules` | Private replacement | 1 |
| `test_same_event_id_with_different_content_is_never_repaired` | Private replacement | 1 |
| `test_terminal_visibility_never_precedes_queued_or_active_stream_events` | Reused | 1 |
| `test_early_aclose_cleans_owned_tasks_and_does_not_permit_replay` | Reused | 1 |
| `test_one_cancelled_collector_does_not_cancel_shared_execution` | Reused | 1 |
| `test_lone_collector_cancellation_cleans_owned_work_before_propagation` | Reused | 1 |
| `test_deterministic_fresh_runs_have_no_cross_instance_high_water` | Private replacement | 1 |
| `test_pending_anext_is_woken_by_aclose_without_external_cancel` | Reused | 1 |
| `test_claimed_empty_stream_does_not_block_successful_collection` | Reused | 1 |
| `test_delivered_only_event_does_not_require_an_extra_poll_before_result` | Reused | 1 |
| `test_invalid_handles_are_rejected_by_stream_collect_and_cancel` | Reused | 5 |
| `test_raw_request_and_handle_values_fail_safely` | Reused | 1 |
| **Total** | **19 reused + 6 private replacements** | **34** |

## Appendix D Actual R15/R16 Route and Real-Driver Evidence

### D.1 R15 Internal/Open ASGI Matrix

| Route/node | Actual request forms | Actual assertions and result |
|---|---|---|
| Internal `test_p2_it20_real_pg_internal_run_scope_redaction_and_r15_errors` | Manual `Last-Event-ID: bad/-1/2147483648/1.5` with valid `after=1` | All four return **400** with `detail == invalid_last_event_id`; E05/E06 |
| Same node | Typed `after=-1/2147483648/bad/1.5` | All four return **422**; malformed Run UUID returns 422 and missing Run returns 404 |
| Internal `test_p0_it_07_internal_sse_after_and_last_event_id_use_strict_max` | `(after=2,header=1)`, `(after=1,header=2)`, boundary `(1,1)`, strict terminal `(2,2)` | All return 200; max/strict applies, boundary replays only seq 2, and strict terminal is empty without run.queued |
| Internal `test_p0_it_07_internal_sse_drains_more_than_200_events_before_terminal` | 201 durable extension events then completion; `after=200` | Full IDs 1..204, tail IDs 201..204, run.completed last |
| Internal `test_p0_it_07_internal_sse_does_not_replay_transient_model_delta` | Actual LISTEN/NOTIFY live delta; replay with `after=0` and `Last-Event-ID:2` | Live delta occurs exactly once with no `id:`; durable IDs 1..4; storage and both replays contain no delta/marker, terminal last |
| Internal `test_p0_it_07_internal_sse_hides_terminal_tool_replay_and_advances_cursor` | Write tool.replay after terminal; full and `after=terminal_seq` | Full response has no tool.replay/marker; empty 200 hidden tail proves cursor advancement |
| Open `test_p2_it20_real_pg_open_sse_drain_cursor_delta_and_authorization` | Typed `Last-Event-ID: bad/-1/2147483648`; typed `after=-1/2147483648/bad/1.5` | Three header + four after forms all return **422**; E05/E07 |
| Same node | `(after=terminal_seq,header=1)`, `(after=1,header=terminal_seq)` | Both return 200; after max/strict there is no run.completed or tool.replay |
| Same node | 201 extension events, hidden tool.replay after terminal, cross-key/user requests | Durable IDs 1..terminal_seq, terminal last; replay payload, private input, redact marker, gateway/history/outcome/context invisible; cross-identity 404 |
| Open `test_p2_it06_open_sse_typed_invalid_cursor_and_last_event_id` | Non-PG ASGI valid after/header plus bad/-1 header and -1 after | Valid request 200 with strict replay; invalid requests 422, supplementing the lightweight route regression |

### D.2 R16 Original asyncpg Row Evidence

The actual node `backend/tests/test_runtime_postgres.py::test_p2_it18_real_pg_claimed_uuid_enters_execution_context` passed in fresh E05/E06/E09:

1. `repo.claim()` directly supplies the original Mapping; `original_row_id` is a `UUID` instance but `type(...) is not UUID`, and its type module starts with `asyncpg.`. No fixture preconversion occurs.
2. The spy on the actual application-composed `RuntimeFactory` only records and delegates to the original `for_run`; it is called exactly once with `factory_row is claimed`, `factory_row_id is original_row_id`, and unchanged type/string value.
3. `context.row is claimed`, `context.row["id"] is original_row_id`, and its type is unchanged; `context.execution_id` and the actual Adapter `request.execution_id` are both **exact stdlib UUIDs** with values equal to the original row.id.
4. Execution actually completes; persisted events include `model.completed`, with `run.completed` last.
5. UT01 forged UUIDs, malicious ordinary `__str__`/descriptor errors, safe static `INVALID_REQUEST`, diagnostic redaction, and CancelledError/KeyboardInterrupt rethrow also passed; helper tests did not replace the real driver chain.

## Appendix E CM08 Raw Performance Method

> This appendix contains only key result summaries; the raw JSON link is subject to §1's lifecycle limitation and cannot be re-reviewed after final cleanup.

| Metric | Fresh result |
|---|---:|
| Warm-up pairs (excluded from samples) | 5 |
| Valid matched pairs / errors | 30 / 0 |
| old-first / new-first | 15 / 15 |
| Nearest rank | N=30, sorted one-based item 29 |
| old/new end-to-end p95 | 0.007500 / 0.095542 ms |
| old/new first-token p95 | 0.000292 / 0.093625 ms |
| paired-delta p95 | 0.089209 ms |
| adapter-overhead p95 | 0.095542 ms |
| end-to-end p95 ratio | 12.738933333333 |
| External latency subtracted | false |
| Production status / target claimed | `pending_env` / false |

Every pair's raw old/new end-to-end, first token, adapter overhead, delta, and ratio is retained in the [raw JSON](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t8-performance.json). Raw latency is excluded only from canonical functional diffs, not deleted from performance evidence or end-to-end measurements. These local test-double values prove only that the sampling/calculation method runs; the large ratio is neither a production performance failure nor success conclusion.

## Appendix F Exact P2-UT-06 Functions and Expanded Counts

All functions below are in `backend/tests/test_react_engine_adapter.py`. E02/E03 are the execution evidence; names and expanded counts were checked against E17's pytest collection/source inventory. Wildcards are not used as substitutes for function evidence.

| Group | Exact function | Count |
|---|---|---:|
| Explicit errors/timeouts | `test_phase_zero_runtime_fault_matrix_preserves_legacy_and_maps_safe_public_error` | 27 |
| Explicit errors/timeouts | `test_future_unknown_runtime_fault_uses_safe_fallback_and_verbatim_private_code` | 1 |
| Explicit errors/timeouts | `test_model_stream_not_supported_has_safe_fallback_without_losing_legacy_code` | 1 |
| Explicit errors/timeouts | `test_outer_timeout_is_run_timeout_not_model_timeout` | 1 |
| Explicit errors/timeouts | `test_model_timeout_runtime_fault_remains_distinct_from_outer_run_timeout` | 1 |
| Explicit errors/timeouts | `test_unknown_regular_exception_is_safe_execution_error` | 1 |
| Explicit errors/timeouts | `test_protocol_failure_is_safe_and_defaults_to_execution_error` | 1 |
| Explicit errors/timeouts | `test_protocol_failure_preserves_an_explicit_legacy_code` | 1 |
| RuntimeFault adversarial | `test_runtime_fault_subclass_uses_real_class_identity` | 1 |
| RuntimeFault adversarial | `test_runtime_fault_code_property_failure_is_safe_and_does_not_leak` | 1 |
| RuntimeFault adversarial | `test_runtime_fault_code_subclass_failure_is_safe_and_does_not_leak` | 1 |
| RuntimeFault adversarial | `test_runtime_fault_mro_failure_is_safe_and_does_not_leak` | 1 |
| RuntimeFault adversarial | `test_runtime_fault_failure_preserves_private_legacy_code` | 1 |
| ExceptionGroup adversarial | `test_nested_single_exception_group_preserves_original_runtime_mapping` | 4 |
| ExceptionGroup adversarial | `test_same_leaf_mapping_in_multi_exception_group_is_stable` | 1 |
| ExceptionGroup adversarial | `test_mixed_leaf_mapping_in_multi_exception_group_uses_safe_fallback` | 1 |
| ExceptionGroup adversarial | `test_exception_group_never_swallows_nested_control_flow` | 3 |
| ExceptionGroup adversarial | `test_nested_cancelled_base_exception_group_closes_real_runner_without_external_cancel` | 1 |
| Control-flow adversarial | `test_code_property_control_flow_is_not_swallowed` | 2 |
| Control-flow adversarial | `test_control_flow_is_never_mapped_to_regular_failure` | 4 |
| Control-flow adversarial | `test_failure_handler_control_flow_is_rethrown_after_cancellation_cleanup` | 3 |
| **Total** | **21 functions: 8 explicit + 5 RuntimeFault + 5 ExceptionGroup + 3 control-flow** | **58** |

## Post-acceptance verification appendix (T11)

> This appendix only adds the 2026-11-11 quickstart live verification; it does not rewrite the T8 body or historical evidence above. See the complete non-sensitive [T11 evidence](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t11-evidence.md) and [raw log directory](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t11-logs/). This round used the demo backend and makes no new production-performance claim.

### T11.1 Startup, default off, and seed

- Initially only the independent Phase 2 PG17 test container existed; there was no quickstart project or port conflict, so the standard `nexusdesk-quickstart` project was used without replacing an existing stack. The first direct Docker Hub build failed while reading metadata. Using the existing Compose `NODE_IMAGE/PYTHON_IMAGE` variables with dockerproxy then allowed `env -u AGENT_EXECUTION_ORCHESTRATOR_ENABLED sh nexusdesk quickstart` to succeed. The three services `postgres/app/mock-business` were healthy, with no `runtime-worker`.
- The default process reported `orchestrator=False embedded_worker=True`; authenticated HTTPS readiness returned 200/demo. Two real in-app seed invocations both exited 0: first created=`1/1/1/1/2/1`; second created all zero and preserved=`1/1/1/1/2/1`. Agent/OpenApp IDs and `agent_version=1` were unchanged. Exactly one real Agent and Profile version existed, and the two conversations referenced a real Agent UUID and `agent_id=NULL`, respectively.
- Default-off published Run `1298ac14-2e18-499b-8a83-6ebe8f894e8f` and no-snapshot Run `a3f57f5d-cd78-4cc8-bd48-de5340b65308` completed with output and `error_code=null`, without `configuration_changed`. Each Run ID had zero `path=orchestrator` lines. No legacy-specific log line is claimed.

### T11.2 Explicit on, controlled logs, and dual SSE

- The first explicit-on Run completed, but quickstart's WARNING root logger suppressed the Worker INFO controlled record. T11 paused and reported this production defect. The main session subsequently supplied the independently reviewed R17 logging fix. The original failure remains recorded; the app alone was rebuilt with the same volume and dockerproxy variables, without reseeding.
- Under R17 explicit on, published Run `acd0b330-3634-4867-b3eb-20b8f4c58248` and no-snapshot Run `89aedc66-21d5-4968-9754-566e74e62036` succeeded. Each had exactly one `path=orchestrator tuple=react/native/v1 status=completed` line, with `duration_ms` 114.641/2.829. A cross-check of all eight Runs in that on container, including SSE and checker attempts, matched eight IDs to eight controlled lines exactly once each. All were completed with finite nonnegative durations and no `execution_failed`, sensitive content, or silent fallback.
- Final internal published/no-snapshot Runs `5f6d70ca-f539-44d1-ab21-d840eab2cb3c` / `4d7e9b7f-9a73-4889-90e1-13b44f08db95` and Open Run `7f521b6f-3171-41f5-90a0-f8ffc68ce8a2` completed. After real internal/Open streams reached terminal, after=0 persistent replay yielded seq `[1,2,3,4,5]` on both APIs with identical payloads and terminal last. Supplying terminal cursor independently through `after` and `Last-Event-ID` returned no events, proving max-cursor and strict `seq>after` behavior without duplicates.
- Open added only the permitted no-ID `accepted(request_id,run_id)`. No tool inputs/results, retrieval content, gateway metadata, reasoning/history/config/input/context/outcome leaked. No-snapshot used only the internal API. Every temporary Key had a ten-minute expiry and was revoked in `finally`. Four Keys across the failed checker, manual success, and two live pytest runs were all finally revoked/inactive; no full Key was printed or retained in evidence.

### T11.3 Full-off rollback and immutability

- Before rollback, all 95 existing terminal Runs were snapshotted with status/output/error/timestamps, event count, terminal seq, and persistent-event SHA-256. After explicit `AGENT_EXECUTION_ORCHESTRATOR_ENABLED=false ... up -d --force-recreate --wait app`, the new process reported false.
- New published/no-snapshot Runs `a28cf8e7-319c-4948-a11a-8f7e97a5eaf6` / `46f541ad-35ff-4609-b72b-1c1270aae63e` completed. Both had zero orchestrator-path lines, as did the current off container overall.
- There were subsequently 103 Runs, but every field and event hash for all 95 pre-rollback Runs remained exactly unchanged. No Alembic downgrade, data repair, client change, new service, or `down -v` occurred.

### T11.4 New opt-in live test and actual commands

`backend/tests/test_execution_orchestrator_seed.py` adds `test_live_quickstart_internal_and_open_sse_replay`. It runs only with explicit `NEXUSDESK_LIVE_QUICKSTART=1`, a URL, and an existing admin token. Default CI neither controls Docker nor requires secrets; an unconfigured environment skips explicitly. Every node below was actually executed this round, and no skip/deselect was counted as a pass:

| Actual command (secrets injected only through shell variables) | Exit / result | Raw evidence |
|---|---|---|
| `NEXUSDESK_LIVE_QUICKSTART=1 ... uv run --directory backend pytest tests/test_execution_orchestrator_seed.py::test_live_quickstart_internal_and_open_sse_replay -v` | 0; **1 passed in 3.44s** before formatting and **1 passed in 3.36s** after formatting | [initial](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t11-logs/live-pytest.log), [final](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t11-logs/live-pytest-final.log) |
| With the existing restricted PG env: `uv run --directory backend pytest tests/test_execution_orchestrator_seed.py -k 'not live_quickstart' -v` | 0; **3 passed, 1 deselected in 2.34s** | [log](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t11-logs/seed-focused-postgres-pytest.log) |
| `uv run --directory backend ruff check tests/test_execution_orchestrator_seed.py` | final 0 | [log](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t11-logs/ruff-seed-final-recheck.log) |
| `uv run --directory backend ruff format --check tests/test_execution_orchestrator_seed.py` | initial post-addition 1; final 0 after formatting only this file | [initial](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t11-logs/ruff-format-seed-final.log), [final](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t11-logs/ruff-seed-final-recheck.log) |

The first SSE checker incorrectly assumed internal terminal data was a flat RunView instead of `{output,error_code}`; the second rejected Open's permitted no-ID `accepted`. Both were checker assumptions, preserved as failures. Only those assertions were corrected, without relaxing persistent-event, cursor, or leakage criteria. T8/T9 suites were not rerun wholesale. The final quickstart remains explicitly off and healthy; its volumes and the independent Phase 2 PG evidence resources are retained.

### T11.5 Conflicting nonzero cursor supplement (specification-review correction)

The reviewer correctly noted that the earlier `(after=5,Last-Event-ID=0)` and `(after=0,Last-Event-ID=5)` checks covered zero/nonzero boundaries but did not independently prove max selection for two conflicting nonzero cursors. The original checks and records remain. For both internal and Open APIs, the live node now adds `(after=4,Last-Event-ID=5)` and `(after=5,Last-Event-ID=4)`, each returning no persistent events. This proves that the larger nonzero cursor wins in either query/header position and that the boundary itself is strictly excluded.

The same opt-in live node was executed against the current healthy off stack (route cursors are independent of the execution flag), exiting 0 with **1 passed in 4.45s** ([raw log](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t11-logs/live-pytest-nonzero-cursor.log)). Ruff check and format both exited 0 ([check log](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t11-logs/ruff-nonzero-cursor.log)). Its temporary Key was revoked in `finally`; all five cumulative Keys are revoked/inactive ([non-sensitive metadata check](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t11-logs/open-key-revocation-nonzero-cursor-check.json)). No production file was changed, on was not enabled, and no old suite was rerun.

### T11.6 Live-test reliability quality supplement

Quality review identified two Important test-reliability issues. Only live helpers were changed, with every assertion retained: `_live_read_sse` now wraps its entire `aiter_lines()` consumption loop in `asyncio.timeout(60)`, while the caller's `async with client.stream(...)` closure semantics remain unchanged, so perpetual heartbeats cannot wait forever. The sole Open Key issue-response parse now saves `key_id=issued["id"]` before reading `app_key=issued["key"]`, ensuring `finally` can revoke by ID even if the key field is abnormal.

The same opt-in node was rerun on the current healthy off stack, exiting 0 with **1 passed in 4.38s** ([raw log](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t11-logs/live-pytest-quality-reliability.log)). Ruff check and format both exited 0 ([check log](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t11-logs/ruff-quality-reliability.log)). Its Key was revoked; all six cumulative Keys are revoked/inactive ([non-sensitive check](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t11-logs/open-key-revocation-quality-reliability-check.json)). No production file or old suite was changed/rerun, and historical execution counts above are not retroactively modified.

## Final cross-phase review supplement (R18, 2026-11-12)

- In `worker.py`, controlled terminal INFO for a normal Outcome now follows the successful return of its corresponding `repository.finish`. If finish raises an ordinary exception, no normal-Outcome record is published first; only the existing exception handler records one failed event and retries failed finish under the original control flow. Repository as sole terminal writer, first-commit-wins, stale/no-op behavior, Memory, off legacy, and exception/cancellation control flow remain unchanged.
- The new `test_worker_on_completed_finish_failure_logs_only_retry_failed` injects a completed-finish failure and asserts `finish_statuses == ['completed', 'failed']`, exactly one controlled failed log, no completed log, and a finite nonnegative duration. The new `test_worker_on_logs_terminal_only_after_successful_finish` strictly asserts `finish_started → finish_succeeded → log`.
- The two new nodes plus nine related Worker path-log/deployment node selections produced **16 passed in 1.17s**. Ruff check on `worker.py`, `test_runtime_baseline.py`, and `test_deployment.py` returned `All checks passed!`; format check returned `3 files already formatted`. See the [R18 evidence index](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-final-fix-evidence.md) for all nodes, commands, and raw logs.
- This supplement did not rerun old suites, rebuild quickstart, or produce an R18 live Run. T11 must still rebuild with final code and minimally revalidate one on Run (exactly one log consistent with its actual terminal state) and off rollback (no orchestrator log). R18 live closure must not be claimed before that check. Production performance, CI, real deployment canary, and human UAT/signoff remain outside this round.

## R18 final-code minimal live on/off closure supplement (2026-11-12)

The pending statement above remains the historical record; this appendix adds the later real execution without retroactively rewriting it. Existing data was reused. No seed, Open, dual SSE, or old suite was run; no temporary Open Key was issued and no production file was changed.

| Actual command (Compose file is always `/Users/jackchow/Documents/CodeLib/nexusdesk/deploy/quickstart/compose.yaml`) | Exit / evidence |
|---|---|
| `NODE_IMAGE=dockerproxy.net/library/node:22-alpine PYTHON_IMAGE=dockerproxy.net/library/python:3.12-slim-bookworm docker compose -f /Users/jackchow/Documents/CodeLib/nexusdesk/deploy/quickstart/compose.yaml build app` | 0; [build log](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t11-logs/r18-final-app-rebuild.log) |
| `AGENT_EXECUTION_ORCHESTRATOR_ENABLED=true docker compose -f /Users/jackchow/Documents/CodeLib/nexusdesk/deploy/quickstart/compose.yaml up -d --force-recreate --wait --wait-timeout 300 app` | 0; [on log](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t11-logs/r18-explicit-on-force-recreate.log) |
| `docker compose -f /Users/jackchow/Documents/CodeLib/nexusdesk/deploy/quickstart/compose.yaml exec -T app python /tmp/r18_internal_run_once.py phase2-orchestrator-published 'R18 minimal live on verification'` | 0; [Run response](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t11-logs/r18-on-published.json) |
| `AGENT_EXECUTION_ORCHESTRATOR_ENABLED=false docker compose -f /Users/jackchow/Documents/CodeLib/nexusdesk/deploy/quickstart/compose.yaml up -d --force-recreate --wait --wait-timeout 300 app` | 0; [off log](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t11-logs/r18-explicit-off-force-recreate.log) |
| `docker compose -f /Users/jackchow/Documents/CodeLib/nexusdesk/deploy/quickstart/compose.yaml exec -T app python /tmp/r18_internal_run_once.py phase2-orchestrator-published 'R18 minimal live off verification'` | 0; [Run response](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t11-logs/r18-off-published.json) |

- Explicit-on published Run `c8e390f2-18fa-4193-9f39-62bd79030563` reached real `completed` with nonempty output and `error_code=null`. For this ID, `path=orchestrator` count = **1**, completed = **1**, failed = **0**; the sole line contained `tuple=react/native/v1` and finite nonnegative `duration_ms=123.639`. [Log assertions](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t11-logs/r18-on-run-log-check.json).
- Explicit-off published Run `53b29563-5933-4f4e-9a7b-deea3a087b18` reached real `completed` with nonempty output and `error_code=null`. This ID had **0** orchestrator lines and **0** failed lines; the off container had **0** orchestrator lines overall. The old on Run still returned `completed`, with its complete RunView exactly unchanged after rollback. [Rollback checks](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t11-logs/r18-off-log-and-old-on-immutability-check.json).
- Final `postgres/app/mock-business` were all healthy with `orchestrator=False embedded_worker=True`; volumes and separate PG17 evidence resources remain. Two temporary-helper injection failures (permissions, then absence after recreate) created no Run; correcting setup did not relax assertions. See the [T11 evidence](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-t11-evidence.md) and [R18 evidence](/Users/jackchow/.claude/jobs/a2066544/tmp/phase2-final-fix-evidence.md) for complete commands and boundaries.
