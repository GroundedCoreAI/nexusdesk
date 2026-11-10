# Phase 0 · Baseline and Inventory — Test Report

> Status: Both the historical 2026-11-07 uncommitted-tree double run and the subsequent 2026-11-09 committed-artifact local Docker double run passed 310-node comparison and zero-XPASS audits; complete Phase 0 acceptance / Phase 1 entry not yet approved
> Created: 2026-11-08
> Basis: `04-test-plan.en.md` (P0-UT-01–10, P0-IT-01–10, P0-CM-01–05), `02-requirements.en.md` (FR-1–FR-6, AC-1–AC-6), `baseline/regression-baseline.en.md`
> Execution: Historical uncommitted-tree Run 1 / Run 2 completed on UTC 2026-11-07; the subsequent independent local Docker/pgvector double run of committed artifact `4dfcfb41e9cbb799753986c2d76134514bbd19be` completed on UTC 2026-11-09; documentation was backfilled on 2026-11-10 without rerunning or replacing any historical round

## 1. Test Scope and Environment

**Scope**: The same 25 suites in the identical order listed in `baseline/regression-baseline.en.md` §4. Each corrected JUnit summary contains 310 unique nodes, all with `outcome=passed`. The total comprises the pre-fix 303 nodes, five XPASS tooling regressions, and two long-duration terminal-format regressions. The complete ordered reproducible command, environment-file constraints, migration, tree-identity steps, per-run log audit, and comparison command are retained in baseline §5. This report does not substitute a simplified command.

| Item | Formal execution environment |
|---|---|
| Local host / branch | macOS; `feat/agent-execution-platform-v2-phase0` |
| Python / uv | Python 3.11.9; uv 0.11.3 (`45da18ac3`) |
| Test tooling | pytest 9.1.1; pytest-asyncio 1.4.0; pytest-cov 7.1.0; coverage 7.17.2 |
| Key dependencies | SQLAlchemy 2.0.54; Pydantic 2.13.5; asyncpg 0.31.0; httpx 0.28.1 |
| PostgreSQL | 17.11 (Debian 17.11-1.pgdg12+2); `pgvector/pgvector:pg17` |
| Database isolation | A separate empty database for each of Run 1 and Run 2; each was migrated and verified at `0057_industry_pack_runtime` before testing |
| External services | No external provider was required; demo/mock models, controlled local HTTP, and PostgreSQL were used |
| Environment evidence | `/tmp/nexusdesk-phase0-environment.log` |

The current JUnit summaries record no skip, xfail, or strict-xpass nodes, so no skipped item is hidden. Non-strict XPASS is an ordinary JUnit pass, so each `-rA` log was also checked with `audit-log`: every formal per-run audit and comparison-gate rerun exited 0 with `summary_entries=310`, `xpass=[]`, and `xpass_count=0`. Clean CI, authorized real samples, and human acceptance were outside this local execution; their boundaries are recorded in §5, §8, and §9.

## 2. Execution Overview

### 2.1 History: 2026-11-07 uncommitted-tree local double run

| Item | Run 1 | Run 2 | Comparison / evidence |
|---|---|---|---|
| Base HEAD metadata | `c6c47dec39025ebd4d1176c1e9925bac9c99c4fd` | Same | Base metadata only, **not** the SHA of the tested uncommitted tree |
| Tested-tree identity | `sha256=f7d3ae857427b5d0173c080f4e6678755f4562730629d3155c2b7d2c44c0d2b1 files=1018` | Same | All four before/after files across both runs are identical |
| UTC start/end | 2026-11-07T21:37:50Z–2026-11-07T21:40:16Z | 2026-11-07T21:41:09Z–2026-11-07T21:43:36Z | Respective `.metadata.txt` |
| JUnit tests/failures/errors/skipped | 310 / 0 / 0 / 0 | 310 / 0 / 0 / 0 | All 310 unique nodes passed |
| JUnit xfail / xpass | 0 / 0 | 0 / 0 | Every node passed; non-strict XPASS is not inferred from JUnit |
| `-rA` log audit | exit 0; 310 entries, zero XPASS | exit 0; 310 entries, zero XPASS | `xpass=[]`, `xpass_count=0`; comparison-gate audit reruns also succeeded |
| JUnit time | 145.281s | 145.353s | Duration is observational and excluded from equivalence |
| Coverage | 9886/18534 = 53.339807920578394% (53.34%) | 9900/18534 = 53.4153447717708% (53.42%) | Respective `.coverage.json` |
| pytest / summary / audit exit codes | 0 / 0 / 0 | 0 / 0 / 0 | The wrapper did not overwrite the real pytest exit code |
| tree-after / within-run cmp / wrapper exit codes | 0 / 0 / 0 | 0 / 0 / 0 | Tree identity was unchanged within each run and each wrapper succeeded |
| Node comparison | — | — | Comparison-gate audit reruns preceded compare exit 0; `/tmp/nexusdesk-phase0-compare.json`: `identical=true`; all four difference lists empty |

In `/tmp/nexusdesk-phase0-identity-checks.json`, `run1_within`, `run2_within`, `cross_run_tree`, and `cross_run_base` are all `true`. No repository files changed between rounds. The comparison used two real JUnit files only after every identity gate and both log audits passed; it is not the earlier self-comparison described in §7. The tested artifact was then an uncommitted working tree, and the hash above is retained solely as that historical round's tree identity. All 60 distinct test functions cited in this report, including every parameterized node for those functions, were mapped individually to both historical summaries and found present and passing.

### 2.2 Subsequent: 2026-11-09 committed-artifact local Docker double run

The tested implementation/baseline artifact commit `4dfcfb41e9cbb799753986c2d76134514bbd19be` has been created and pushed. A subsequent double run used this **exact committed artifact** with two independent clean Docker/pgvector PostgreSQL 17 containers, volumes, and temporary credentials. It is local supporting evidence, not GitHub Actions CI, and does not replace §2.1 history. The documentation-only backfill of 2026-11-10 is not included in that tested SHA; neither the SHA nor this run may be presented as test/CI evidence for a later PR head. Clean CI on the final PR head remains `pending_env`.

| Item | Run 1 | Run 2 | Comparison / evidence |
|---|---|---|---|
| Commit / tree identity | `4dfcfb41e9cbb799753986c2d76134514bbd19be`; `sha256=063150feec809290c2945a6e305f133e41330518f9d3cda9ca60cd3c85b449ab files=1018` | Same | Before/after and cross-run identities matched |
| UTC start/end | 2026-11-09T14:29:13Z–14:30:42Z | 2026-11-09T14:32:00Z–14:33:34Z | Respective metadata |
| Scope / Alembic | Same ordered 25 suites; `0057_industry_pack_runtime (head)` | Same | Two independent empty pgvector databases |
| JUnit tests/failures/errors/skipped | 310 / 0 / 0 / 0 | 310 / 0 / 0 / 0 | All 310 unique nodes passed |
| `-rA` log audit | 310 entries, zero XPASS, exit 0 | 310 entries, zero XPASS, exit 0 | Non-strict XPASS is not hidden |
| JUnit time | 86.391s | 90.885s | Observational only |
| Coverage | 9890/18534 = 53.36138987806194% | 9882/18534 = 53.318225963094854% | Eight-file executed-line differences in §6 |
| Node comparison | — | — | `identical=true`; `added=[]`, `missing=[]`, `outcome_changes=[]`, `skip_reason_changes=[]`; compare exit 0 |

Ruff, the architecture gate, and the zero-production/migration-drift checks for `backend/src` and `backend/migrations` relative to base all passed. An actual `git revert --no-commit HEAD` drill ran in a separate disposable clone; the reverted result had no difference from base `c6c47dec39025ebd4d1176c1e9925bac9c99c4fd`, and no revert ran in the main working tree. Targeted scanning of 47 formal text evidence files returned `findings=[]` and `read_errors=[]`; credential environment files were not read, and binary coverage data was explicitly excluded. Docker resources and temporary credentials were cleaned up afterward. The original summary and index are `/tmp/nexusdesk-phase0-docker-acceptance.t8jnUT/ACCEPTANCE-RESULT.md`, `shared/acceptance-summary.json`, `shared/compare.json`, and `shared/secret-scan.json`.

## 3. Unit Test (P0-UT) Traceability

All test files below are under `backend/tests/`. Where a function name is followed by a parameterized-node count, it denotes every exact `(classname,name)` node for that function in the summaries; each was checked against both runs.

| ID | Requirement / trace | Concrete test node(s) or execution evidence | Actual result | Status / boundary |
|---|---|---|---|---|
| P0-UT-01 | Normal Engine message/tool loop; FR-2/FR-4 | `test_runtime_engine.py::test_model_tool_observe_reply_and_history`; `test_runtime_baseline.py::test_engine_emits_streaming_model_event_payload_essentials`, `test_engine_emits_tool_event_payload_essentials`, `test_engine_returns_trimmed_history_and_only_dropped_old_messages` | Assertions cover tool request arguments, `ToolMessage` feedback, final answer, event order, streaming deltas, usage/gateway fields, and history/dropped; all passed in both runs | Local pass |
| P0-UT-02 | Model/tool exceptions, budgets, empty output, and sanitization; FR-2/FR-4 | `test_runtime_engine.py::test_execution_guards` (3 parameterized nodes), `test_tool_budget_rejected_before_execution`, `test_model_timeout`, `test_tool_timeout_and_cancellation`, `test_http_failures_are_sanitized` (4 parameterized nodes); `test_runtime_baseline.py::test_worker_maps_outer_timeout_to_run_timeout`, `test_worker_preserves_runtime_fault_code` (2 parameterized nodes), `test_worker_sanitizes_ordinary_exception_to_execution_error` | `model_round_limit`, `repeated_tool_call`, `empty_model_response`, `tool_call_limit`, model/tool/outer timeouts, HTTP errors, and worker error codes match current behavior; the synthetic provider marker is absent from persisted results | Local pass |
| P0-UT-03 | Worker emit persistence versus transient routing; FR-1/FR-2 | `test_runtime_baseline.py::test_worker_model_delta_is_transient_and_ordinary_event_is_appended` | `model.delta` goes only to the notifier as `k=delta`; `model.completed` goes to the Repository; finish is completed | Local pass |
| P0-UT-04 | Cancellation during execution and watcher/task cleanup; FR-2/FR-4 | `test_runtime_postgres.py::test_cancellation_interrupts_inflight_model`; `test_runtime_engine.py::test_tool_timeout_and_cancellation` | The first asserts that the in-flight model enters `finally`, the Run becomes cancelled, and `worker.stop()` is followed by awaiting the worker task in `finally`; the second asserts `CancelledError` propagation from the tool task | Tests passed in both runs; **bounded evidence**: this proves the stated model interruption, tool cancellation, and worker-task convergence, but does not enumerate global asyncio tasks/watchers and therefore does not claim every watcher is leak-free |
| P0-UT-05 | Five valid fixtures, default normalization, and unchanged sources; FR-3/AC-3 | `test_runtime_baseline_fixtures.py::test_fixture_manifest_covers_exact_files_and_all_valid_configs`; `test_agent_config_execution_compat.py::test_p0_it_08_legacy_raw_draft_publishes_normalized_v1` (2 parameterized nodes) | All five valid cases validate; all 16 minimal defaults match exactly; both legacy publication cases assert byte-identical source fixtures | Local pass; the two legacy fixtures have explicit source-byte assertions and the other valid fixtures follow read-only loading; authorized real-sample representativeness remains `pending_env` (P0-I2) |
| P0-UT-06 | Exact outcomes for 16 invalid/unknown-field cases; FR-3 | `test_runtime_baseline_fixtures.py::test_invalid_fixtures_declare_exact_pydantic_error_locations` | All 16 invalid cases raise `ValidationError`, with exact equality of complete normalized Pydantic `loc` sets; root error `[[]]` and integer collection indexes are preserved | Local pass; rejection of unknown `engine` is not treated as approval of a future mapping |
| P0-UT-07 | One-to-one seven-file manifest, version/coverage/redaction; FR-3/FR-6 | The manifest test above; read-only inspection of `backend/tests/fixtures/agent_execution_baseline/manifest.v1.json`; P0-CM-03 scan in §5 | The directory contains exactly the manifest plus six payloads; every payload has `fixture_version=v1`, `covered_fields`, `covered_cases`, expectations, and provenance/synthetic-value policy; no orphan files | Local pass; `production_samples=false`, so this does not replace real-sample review |
| P0-UT-08 | Frozen IDs, Run terminology, no Worker Engine branch; FR-5/AC-5 | `test_agent_config_execution_compat.py::test_p0_ut_08_frozen_identities_terminology_and_worker_neutrality` | Bilingual architecture/Phase 1 design/checklist assertions match `(react,native,v1)`, `(local-test,scripted,v1)`, Run=one Execution attempt, no dual tables, and no Engine branches; AST checks find no Worker selection fields or provider if | Local pass; this is static freeze evidence, not Phase 1 wiring or release approval |
| P0-UT-09 | JUnit counts, outcomes, durations, and missing values; FR-6 | `test_runtime_baseline_tooling.py::test_summary_aggregates_leaf_suites_without_double_counting`, `test_summary_single_suite_classifies_all_outcomes_and_skip_reasons`, `test_summary_output_is_deterministic_and_mirrors_output_file`, `test_summary_rejects_invalid_structure` (7 parameterized nodes), `test_summary_rejects_malformed_xml_with_concise_error` | Leaf aggregation does not double-count; passed/failed/error/skipped/xfail/xpass and reasons are retained; durations are retained; missing tests, invalid time/tests, empty identity, duplicates, non-leaf structure, and malformed XML all explicitly exit 2 rather than defaulting missing values to 0 | Local pass |
| P0-UT-10 | Genuine node-level two-run comparison; FR-6/AC-4 | `test_runtime_baseline_tooling.py::test_compare_reports_node_differences_and_count_metadata`, `test_compare_ignores_duration_only_changes`, `test_cli_subprocess_emits_json_and_node_diff_exit_code`; historical `/tmp/nexusdesk-phase0-compare.json` and subsequent `/tmp/nexusdesk-phase0-docker-acceptance.t8jnUT/shared/compare.json` | Tool tests prove detection of added/missing/outcome/skip-reason changes, duration-only tolerance, and difference exit 1; both the historical uncommitted-tree and subsequent committed-artifact Docker comparisons have `identical=true` with all four difference lists `[]` | Both local evidence sets pass; neither is the earlier self-comparison nor a clean-CI double run |

P0-UT-09/10 tooling regressions now include seven added nodes: `test_summary_classifies_pytest_strict_xpass_skipped_message`, `test_real_pytest_strict_xpass_is_classified_as_xpass`, `test_real_pytest_non_strict_xpass_requires_and_fails_log_audit`, `test_audit_log_cli_accepts_real_clean_pytest_log`, `test_audit_log_cli_rejects_real_pytest_log_without_summary_evidence`, plus `test_audit_log_accepts_pytest_long_duration_terminal_summary` and `test_audit_log_rejects_malformed_long_duration_terminal_summary`. The first five pin strict-JUnit classification, the non-strict JUnit limitation, and `-rA` log exit 0/1/2 semantics; the last two pin the real `(0:02:24)` long-duration suffix and malformed-input rejection. Two independent spec/quality review rounds approved the XPASS fix and terminal-parser fix respectively. `test_runtime_baseline_tooling.py` now has 23 nodes, all included and passing in the current 310-node formal double run.

## 4. Integration Test (P0-IT) Traceability

| ID | Requirement / trace | Concrete test node(s) or execution evidence | Actual result | Status / boundary |
|---|---|---|---|---|
| P0-IT-01 | Completed lifecycle; AC-1/AC-2 | `test_runtime_postgres.py::test_p0_it_01_queued_claim_completed_lifecycle_persists_exact_state` | Owner, lease, timestamps, output, persisted history, and three exact terminal events match across queued/running/completed; repeat finish changes neither state nor events | Local PostgreSQL pass |
| P0-IT-02 | Queued/running cancellation; AC-2/FR-2 | `test_runtime_postgres.py::test_queue_expiration_and_cancel_without_worker`, `test_cancellation_wins_finish_race_and_event_replay`, `test_cancellation_interrupts_inflight_model` | Queued becomes cancelled directly; after running cancel_requested, a late completed does not overwrite cancelled and events replay correctly; the in-flight model is cancelled | Local PostgreSQL pass |
| P0-IT-03 | Three real-worker failures; FR-2/FR-4 | `test_runtime_postgres.py::test_p0_it_03_real_worker_persists_sanitized_failure_terminal` (3 parameterized nodes) | `controlled_runtime_fault`, `run_timeout`, and `execution_error` each persist the exact failure terminal/events; synthetic provider text is absent from events, output, error_code, and caplog | Local PostgreSQL pass |
| P0-IT-04 | Lease/heartbeat/reaper including cancelled-with-error; AC-2 | `test_runtime_postgres.py::test_lost_worker_is_failed_and_cannot_publish_late_result`, `test_p0_it_04_reaper_cancelled_expired_running_lease_keeps_worker_lost`, `test_p0_it_04_manual_queued_cancel_flag_reaps_cancelled_with_queue_timeout` | Expired-lease heartbeat returns lost; reaping produces `failed/worker_lost` and late results are ineffective; cancel-requested expired running becomes `cancelled/worker_lost`; the manual queued intermediate state becomes `cancelled/queue_timeout` | Local PostgreSQL pass; the queued intermediate state is explicitly SQL-constructed rather than claimed reachable through the public API |
| P0-IT-05 | Both commit orders and concurrent race; FR-2 | `test_runtime_postgres.py::test_p0_it_05_queued_cancel_and_reap_commit_orders` (2 parameterized nodes), `test_p0_it_05_concurrent_queued_cancel_reap_has_one_terminal_transition` | Cancel-first yields cancelled and reap-first yields `failed/queue_timeout`; the race permits only one valid terminal event, and repeated cancel/reap changes neither state nor events | Local PostgreSQL pass; the allowed concurrent-terminal set records current semantics rather than forcing one winner |
| P0-IT-06 | Repeat finish, late append, exclusive claim; AC-2/FR-4 | `test_runtime_postgres.py::test_p0_it_06_terminal_rejects_late_append_and_repeat_finish`, `test_p0_it_06_cancel_requested_rejects_append_and_forces_cancelled_finish`, `test_p0_it_06_expired_lease_rejects_append_and_finish`, `test_p0_it_06_wrong_owner_finish_and_append_do_not_write`, `test_concurrent_submit_and_exclusive_claim` | Illegal writes after terminal/cancel/lease-loss and from the wrong owner are rejected; only 1 of 5 concurrent claims succeeds; Run state and event sequence remain unchanged | Local PostgreSQL pass |
| P0-IT-07 | Strict SSE max, pagination, transient behavior, and replay; FR-2/FR-4 | `test_runtime_postgres.py::test_p0_it_07_internal_sse_after_and_last_event_id_use_strict_max`, `test_p0_it_07_internal_sse_drains_more_than_200_events_before_terminal`, `test_p0_it_07_internal_sse_does_not_replay_transient_model_delta`, `test_p0_it_07_internal_sse_hides_terminal_tool_replay_and_advances_cursor` | `max(after,Last-Event-ID)` boundaries are correct; 204 events drain and after=200 returns 201–204; deltas are not replayed; the specialized post-terminal `tool.replay` payload is hidden from SSE and the cursor advances | Local PostgreSQL pass; P0-I4 post-terminal seq consumption remains P2/open and is not security-fixed |
| P0-IT-08 | Two legacy publish cases, v2, cross-tenant, queued snapshot, sparse limitation; AC-3 | `test_agent_config_execution_compat.py::test_p0_it_08_legacy_raw_draft_publishes_normalized_v1` (2 parameterized nodes), `test_later_draft_and_v2_do_not_rewrite_v1_or_cross_tenant_boundary`, `test_queued_run_keeps_v1_snapshot_after_v2_is_published`, `test_sparse_raw_version_exposes_direct_snapshot_tool_names_limitation` | Both raw legacy drafts publish as complete normalized v1; v2 does not rewrite v1; cross-tenant access returns the respective established 404s; queued Run retains v1; direct snapshot of a manual sparse raw version raises `KeyError("tool_names")` | Public path passes locally; P0-I7 storage-stage limitation remains P2/open and real samples remain `pending_env` |
| P0-IT-09 | Completion hooks, mock ReAct, summary/memory/injection; FR-1/FR-4 | `test_runtime_postgres.py::test_p0_it_09_completion_hooks_run_only_for_completed_runs`, `test_worker_runs_real_graph_and_persists_events`; `test_memory_postgres.py::test_p1_it_01_truncation_dispatches_task_and_summary_is_written`; `test_memory_customers_postgres.py::test_p2_it_08_injection_sits_between_summary_and_history`; `test_memory_injection_postgres.py::test_p6_it_01_run_writes_one_row_per_injected_item`, `test_p6_it_02_event_counts_and_item_ids_match_detail_rows` | Across completed/failed/cancelled, only completed invokes the completion hook and writes assistant/history; the real graph persists events to completion; summary dispatch/write, memory-injection position, per-item details, and event counts satisfy assertions | Local PostgreSQL pass; no external provider required |
| P0-IT-10 | Formal double run, coverage, and environment artifacts; AC-4/AC-6 | Both artifact sets in §2; historical command in `baseline/regression-baseline.en.md` §5 and subsequent Docker evidence in §6; `/tmp/nexusdesk-phase0-compare.json`, `/tmp/nexusdesk-phase0-coverage-diff.json`, `/tmp/nexusdesk-phase0-docker-acceptance.t8jnUT/shared/compare.json` | Both the historical uncommitted-tree run and the subsequent Docker run of exact commit `4dfcfb41e9cbb799753986c2d76134514bbd19be` covered the same ordered 25 suites, with 310 passed nodes, identical node outcomes, and zero XPASS in every run; coverage and environment data are retained separately | **Historical and committed-artifact local node/XPASS gates pass**; clean GitHub Actions CI double-run artifacts/links for the final PR head remain `pending_env`, so this is not unrestricted complete AC-4 acceptance |

## 5. General Checks (P0-CM) Traceability

| ID | Check / trace | Execution or artifact evidence | Actual result | Status / boundary |
|---|---|---|---|---|
| P0-CM-01 | Commit and evidence completeness; FR-1/AC-1 | Historical runs' `.base-commit.txt`, `.tree-before.txt`, `.tree-after.txt`, `.metadata.txt` and `/tmp/nexusdesk-phase0-identity-checks.json`; subsequent Docker `shared/acceptance-summary.json` and per-run identity artifacts | Historical base plus tree hash identifies the uncommitted tree; subsequent exact commit `4dfcfb41e9cbb799753986c2d76134514bbd19be` is bound to tree `063150fe…449ab files=1018`, with matching identities across runs | **Commit existence/binding for the tested artifact is closed**: the commit is pushed; subsequent documentation backfill is outside the tested SHA, and final-PR-head CI and human signoff remain separate open gates |
| P0-CM-02 | No production-execution/migration drift; FR-3/scope | Historical T9 read-only checks; on 2026-11-09, repeated zero-drift checks of `backend/src` and `backend/migrations` relative to base for commit `4dfcfb41e9cbb799753986c2d76134514bbd19be` | Neither historical nor subsequent checks found production-execution or migration drift; changes remain limited to tests, baseline tooling, documents, and dev test dependencies | Local pass; subsequent documentation backfill is outside the tested SHA |
| P0-CM-03 | Secret scan of fixtures, formal outputs, and backfilled documents; FR-3/NFR | Historical `/tmp/nexusdesk-phase0-doc-backfill-secret-scan.json`; subsequent `/tmp/nexusdesk-phase0-docker-acceptance.t8jnUT/shared/secret-scan.json`; manifest synthetic-value policy | The historical 40-file scan found nothing; the subsequent targeted scan of 47 formal text evidence files returned `findings=[]` and `read_errors=[]`, did not read two credential environment files, and excluded two binary coverage files | Both local targeted scans pass; neither is mathematical proof against every secret form, and authorized real-sample representativeness remains `pending_env` |
| P0-CM-04 | Local node determinism; AC-4 | Historical summaries/audits/compare/coverage-diff; subsequent Docker `shared/compare.json` and `shared/acceptance-summary.json` | Both double runs have 310 passing nodes, empty added/missing/outcome/skip-reason differences, and 310 audit entries with zero XPASS per run; duration differences do not participate in equivalence | Historical and committed-artifact local node/XPASS-audit gates pass; each set has eight-file executed-line differences as recorded in §6, so neither is line-identical and neither proves nor hides flakiness |
| P0-CM-05 | Phase 1 entry checklist; FR-5/FR-6/AC-6 | IDs, counts, durations, coverage, defects, and boundaries in this report; frozen IDs, general gates, Phase 1–7 mapping, and entry checklist in `baseline/refactoring-checklist.en.md` §1–§5; `07-acceptance-report.en.md`; subsequent committed-artifact Docker and actual-revert evidence | Local records cover the listed material; neither formal double run exposed a new P0/P1 implementation defect, and the tested commit exists and is bound | **Local checklist evidence recorded; Phase 1 entry not approved**: 07 is explicitly “pending acceptance / not approved”; P0-I1 clean CI on the final PR head, P0-I2 real samples, and human acceptance/signoff remain incomplete; no final P0/P1 acceptance count is fabricated, no conditional pass is granted, and Phase 1 is not released |

## 6. Regression, Node Comparison, and Coverage Observation

- Both runs used the identical ordered 25-suite scope and deterministic tree identity. The set and outcomes of all 310 unique nodes match exactly; JUnit failures/errors/skipped/xfail/xpass are all zero. Non-strict XPASS was independently audited in both `-rA` logs: every formal per-run audit and comparison-gate rerun exited 0 with 310 entries and zero XPASS.
- `/tmp/nexusdesk-phase0-compare.json` is a genuine comparison of Run 1 JUnit against Run 2 JUnit: `identical=true`, `added=[]`, `missing=[]`, `outcome_changes=[]`, and `skip_reason_changes=[]`, with compare exit 0. The JUnit time change from 145.281s to 145.353s is not an equivalence criterion and does not alone prove flakiness.
- Coverage is not line-by-line equivalent: Run 1 covers 9886/18534 lines and Run 2 covers 9900/18534, a net 14 more covered lines. `/tmp/nexusdesk-phase0-coverage-diff.json` reports executed-line-set differences in eight files: `channel/service.py`, `memory/decay.py`, `memory/service.py`, `open_platform/routes.py`, `open_platform/service.py`, `open_platform/webhooks.py`, `model_gateway/catalog.py`, and `model_gateway/governance.py`. Exact per-file run1-only/run2-only line numbers remain in that JSON.
- This coverage difference and the identical node outcomes are both retained. It is a coverage observation, not proof of flaky tests, and must not be hidden by the two-decimal 53.34%/53.42% display or the green aggregate node count.
- The subsequent Docker double run also has 310/310 matching nodes and zero XPASS, with JUnit times 86.391s/90.885s and coverage 9890/18534 versus 9882/18534. `/tmp/nexusdesk-phase0-docker-acceptance.t8jnUT/shared/acceptance-summary.json` records a separate set of eight files with executed-line differences: `channel/service.py`, `memory/decay.py`, `memory/service.py`, `memory/worker.py`, `open_platform/service.py`, Runtime `worker.py`, `model_gateway/catalog.py`, and `model_gateway/gateway.py`. Exact line numbers remain in the JSON; this observation is neither hidden nor called line-identical, and it does not alone prove flakiness.

## 7. Defects Found During Formal Execution

Neither the historical corrected formal runs nor the subsequent committed-artifact Docker formal runs **exposed a new P0/P1 implementation defect**. This statement describes only the formal rounds' actual results; it does not remove CI, real-sample, or human-acceptance evidence gates and does not establish a final open P0/P1 count before later acceptance review. The following tooling-gate defects are retained separately from the production-implementation failure rate:

| ID | Discovery point | Actual defect and impact | Fix, reviews, and regression | Current disposition |
|---|---|---|---|---|
| P0-D1 | Final tooling review | Strict-XPASS JUnit classification was insufficient, and non-strict XPASS was an ordinary JUnit pass. The old 303-node double run had no per-run log audits and could not satisfy the corrected zero-XPASS evidence requirement | Correct strict-JUnit classification and add fail-closed `-rA` auditing; add five real-pytest/audit regressions, with both independent spec and quality approval in the first review round | Fixed; the old 303-node artifacts remain superseded history, and both audits passed in the current 310-node double run |
| P0-D2 | Pre-comparison audit of the first corrected Run 1 attempt | Pytest exited 0, all 308 JUnit nodes passed, time was 144.515s, and the tree was stable, but the auditor rejected the real terminal `308 passed in 144.54s (0:02:24)` with exit 2. No formal audit JSON existed, and Run 2/compare were not started. **This was neither a test failure nor a passing formal run** | Accept `(H:MM:SS)` while continuing to reject malformed input; add two regressions, with both independent spec and quality approval in the second review round. A later diagnosis of the original log returned exit 0 with 308 entries and zero XPASS but was not promoted to formal evidence | Fixed; the attempt remains archived separately, and the current 310-node double run was subsequently restarted with a fresh Run 1 database and completed |

The superseded 303-node artifacts are archived at `/tmp/nexusdesk-phase0-superseded-20261107-3d4f9b06/`, with tree `sha256=3d4f9b06cbdd5de89250d888c0ea695d145e6051d4cc995c64107947fc14e729 files=1014`. The selected sources had no actual xfail markers, but neither run had an audit artifact. They remain JUnit history for that old tree only, not evidence for the corrected gate. The rejected 308-node Run 1 is archived at `/tmp/nexusdesk-phase0-rejected-run1-20261107-19548c1d/`, with tree `sha256=19548c1df1591a9fb084e4bb178694d782a50c74c870d0ab4c936975e42d11b9 files=1018` and UTC range 2026-11-07T21:20:28Z–21:22:53Z.

One item of non-formal history is also retained: in the earlier 24-suite rehearsal, pytest completed and generated the full artifacts, after which the zsh wrapper failed with `read-only variable: status`. That rehearsal was not a formal double run. The formal template now uses `test_rc`, and all current pytest/summary/audit/tree/wrapper exit codes are 0. This history is neither mixed into the formal failure rate nor deleted.

Rejected/failed attempts in the subsequent Docker harness likewise do not count toward the formal double run: the first image lacked `.git` and was rejected with exit 128 before pytest or migration (`rejected-run1-no-git.*`); after that fix, an incorrect Alembic working directory failed before pytest without migrating the database (`rejected-run1-migration-path-*`); and an extra random `AGENT_API_TOKEN` conflicted with a development-mode end-to-end test's assumptions, producing 309 passed and 1 failed (`test_runtime_postgres.py::test_end_to_end_demo_uses_real_http_and_persistent_events`, HTTP 401 rather than 202; `failed-run1-auth-*`). None is passing evidence. Only after old containers/volumes were removed did the §2.2 formal double run proceed with new temporary credentials and two independent empty databases.

## 8. Residual Risks and Open Items

| ID | Severity / status | Actual boundary and disposition |
|---|---|---|
| P0-I1 | `pending_env` | Tested commit `4dfcfb41e9cbb799753986c2d76134514bbd19be` exists and is pushed, but clean GitHub Actions CI double-run artifacts and links for the final PR head do not yet exist; engineering lead + QA must supply them before Phase 1 entry review. Subsequent documentation backfill is outside the tested SHA, and local Docker runs do not replace CI AC-4 |
| P0-I2 | `pending_env` | No authorized, sanitized real historical drafts and published snapshots with a provenance inventory were supplied; current fixtures are synthetic field shapes only. Agent-config and security representatives must supply samples or record a formal scope decision |
| P0-I3 | P2 / open | The open-platform stream comment says no token delta although visible-text deltas are emitted; open-platform backend owner to resolve before Phase 2 |
| P0-I4 | P2 / open | A specialized `tool.replay` can consume seq after terminal state; the dedicated SSE test proves payload hiding and cursor advancement, but the security/behavior boundary is unfixed and unadjudicated, due no later than the Phase 6 security gate |
| P0-I5 | P3 / open | Existing `seed_memory_*` full-format-check differences remain with the owning script maintainers; no unrelated bulk formatting is mixed into Phase 0 |
| P0-I6 | Environment note | Ignored legacy directories/`__pycache__` interfere with local architecture scanning; the gate passes in a clean target worktree, and no user files are deleted to manufacture a clean result |
| P0-I7 | P2 / open | A manually inserted extremely sparse raw version passes AgentConfig input validation but direct `snapshot()` raises `KeyError("tool_names")`; AgentConfig + Runtime owners must resolve or formally adjudicate it with regression before Phase 3 |

## 9. CI Evidence and Acceptance Boundary

- Existing CI run <https://github.com/GroundedCoreAI/nexusdesk/actions/runs/42227604191> is only single-run supporting evidence for the base backend, at head `16aed12eb095f29bed5c536b5fcbf68e510136c4`; it contains none of the new Phase 0 tests, coverage, JUnit artifacts, or double-run comparison.
- The tested implementation/baseline commit `4dfcfb41e9cbb799753986c2d76134514bbd19be` has been created and pushed, and §2.2's local Docker double run used that exact SHA. The subsequent documentation-only backfill will create a later PR head outside that SHA, and no PR had been created as of this documentation backfill on 2026-11-10. Formal clean GitHub Actions CI double-run evidence and links for the final PR head remain `pending_env`; this report claims no new CI success and does not substitute Docker for CI.
- This is not `07-acceptance-report.en.md`, contains no human signoff, and does not turn local test success into unrestricted acceptance of all AC-1–AC-6. Complete Phase 0 acceptance and Phase 1 entry still require the evidence gates in §8 and subsequent human acceptance.

## 10. Conclusion

**Both the historical uncommitted-tree double run and the subsequent local Docker double run of exact commit `4dfcfb41e9cbb799753986c2d76134514bbd19be` passed 310-node comparison and zero-XPASS audits; complete Phase 0 acceptance / Phase 1 entry not yet approved.** Subsequent documentation backfill is outside the tested SHA; clean CI on the final PR head, real samples, and human signoff remain independent gates.

## Appendix A Historical Formal Artifact Index (2026-11-07 uncommitted tree)

| Artifact | Run 1 | Run 2 |
|---|---|---|
| Raw log | `/tmp/nexusdesk-phase0-run1.log` | `/tmp/nexusdesk-phase0-run2.log` |
| JUnit | `/tmp/nexusdesk-phase0-run1.xml` | `/tmp/nexusdesk-phase0-run2.xml` |
| Summary | `/tmp/nexusdesk-phase0-run1.summary.json` | `/tmp/nexusdesk-phase0-run2.summary.json` |
| XPASS log audit | `/tmp/nexusdesk-phase0-run1.xpass-audit.json` | `/tmp/nexusdesk-phase0-run2.xpass-audit.json` |
| Coverage JSON | `/tmp/nexusdesk-phase0-run1.coverage.json` | `/tmp/nexusdesk-phase0-run2.coverage.json` |
| Coverage data | `/tmp/nexusdesk-phase0-run1.coverage` | `/tmp/nexusdesk-phase0-run2.coverage` |
| Base metadata | `/tmp/nexusdesk-phase0-run1.base-commit.txt` | `/tmp/nexusdesk-phase0-run2.base-commit.txt` |
| tree-before | `/tmp/nexusdesk-phase0-run1.tree-before.txt` | `/tmp/nexusdesk-phase0-run2.tree-before.txt` |
| tree-after | `/tmp/nexusdesk-phase0-run1.tree-after.txt` | `/tmp/nexusdesk-phase0-run2.tree-after.txt` |
| Metadata | `/tmp/nexusdesk-phase0-run1.metadata.txt` | `/tmp/nexusdesk-phase0-run2.metadata.txt` |

This is the formal artifact index for the historical corrected double run of 2026-11-07. Both audit files exist and exited 0, and the comparison gate reran and confirmed the same results before node comparison. Subsequent documentation backfill did not rerun, overwrite, or replace these historical artifacts.

Shared artifacts:

- `/tmp/nexusdesk-phase0-identity-checks.json`
- `/tmp/nexusdesk-phase0-compare.json`
- `/tmp/nexusdesk-phase0-coverage-diff.json`
- `/tmp/nexusdesk-phase0-environment.log`
- `/tmp/nexusdesk-phase0-compare-gate.log`
- `/tmp/nexusdesk-phase0-doc-backfill-secret-scan.json` (current read-only scan, not a formal pytest artifact from either run)
- `/tmp/nexusdesk-phase0-t9-secret-scan.json` (T9 historical read-only scan, not a formal pytest artifact from either run)

## Appendix B Subsequent Committed-Artifact Docker Artifact Index (2026-11-09)

Root: `/tmp/nexusdesk-phase0-docker-acceptance.t8jnUT/`.

- Execution result and boundaries: `ACCEPTANCE-RESULT.md`
- Run 1 / Run 2 raw logs, JUnit, summaries, audits, coverage, migration, tree identity, and metadata: `run1-artifacts/`, `run2-artifacts/`
- Node comparison: `shared/compare.json`
- Summary and eight-file coverage-line differences: `shared/acceptance-summary.json`
- Scan of 47 text evidence files: `shared/secret-scan.json`
- Non-formal failed/rejected evidence: `rejected-run1-no-git.*`, `rejected-run1-migration-path-*`, `failed-run1-auth-*`

Credential environment files were not read and have been deleted; binary coverage data is outside the text-scan scope. Docker resources and temporary credentials were cleaned up.
