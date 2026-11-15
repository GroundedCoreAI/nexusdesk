# Phase 4 · Runtime Host, Process Supervision, and Workspace — Test Report

> Status: executed and re-verified (round 1 = single authoritative full-table run; round 3 = targeted rerun of D-1/IT-09 only; round 4 = CI-discovered D-2 fixed and the full Phase 4 suite re-run on both macOS and a Linux kernel). Conclusion: **57 pass, 8 pass-with-pending_env-halves, 1 pending_env, 1 not_measured, 0 fail**; both defects — **D-1 (P1)** fixed at `2a2d626` and **D-2 (P1)** fixed in round 4 — are closed, so the §10 exit criteria are **met for the macOS development subset**, now also corroborated by an identical Linux-container result; the Linux-dependent halves still `pending_env`, which keep every enablement promise (`execution_runtime_host_enabled=true`) blocked as designed
> Created: 2026-11-14
> Basis: `04-test-plan.en.md` (revised 2026-11-14, §2.1 normative macOS/pending_env partition; P4-UT-01–22, P4-IT-01–30, P4-CM-01–15), `08-implementation-breakdown.en.md` (R-1–R-14, §5 split, §8.1–8.4 closure register incl. the §8.3 revision), `02-requirements.md` (FR/AC), `03-technical-design.md`
> Executed by: the Phase 4 test lane (independent evidence collection; no implementation code, no doc changes outside this file, no git writes); dates: round 1 2026-11-14 02:45–03:35 CST, round 3 2026-11-14 03:45–04:00 CST
> Rule: every row below records commands actually executed on this host and their verbatim tails (Appendix A). Anything not executed, environment-missing, or blocked is recorded as `pending_env` / `not_measured` / `fail`, never as a pass (04 Principle 8, 08 §1.4). Round 3 reran only the D-1 blast radius (E11–E17); the 67-row table from round 1 remains the single authoritative execution and was not repeated.

## 1. Scope and environment

**Scope**: all 67 P4 cases (22 UT / 30 IT / 15 CM) as revised (R-1 migration `0059`, R-11 prepare convergence, R-12 over-quota accounting, R-13 probe-gated `RLIMIT_AS`, R-14 platform-independent excess evidence), the Phase 0–3 regression surface, the quality gates, and the quickstart local-Docker drill (08 §8.3). This report performs no acceptance and draws no 07 conclusion.

| Item | Measured value | Evidence |
|---|---|---|
| Branch / HEAD | `feat/agent-execution-platform-v2-phase4`; round 1 at `12d0f978521adbd72e666c56fbc1d90f3c01a1b2`, round 3 at **`2a2d626279e63a61b5f5f12440f98289ab95703f`** (the D-1 fix); working tree clean at both starts (`git status --porcelain` = 0 entries apart from this report file) | A-0 |
| Operating system | macOS (Darwin 27.0.0, ProductVersion 27.0.1), x86_64, timezone +0800 | `sw_vers`, `uname -m` |
| Backend toolchain | Python 3.12.13 (uv), uv 0.11.3; `uv run ruff`/`pytest` from `backend/` | A-0 |
| PostgreSQL | container `nexusdesk-phase4-pg` (image `pgvector/pgvector:pg17`, running, `127.0.0.1:5443->5432/tcp`), database migrated to `0059_execution_runtime_host` | `docker ps` |
| Credentials | mode-0600 file `/tmp/nexusdesk-phase4-pg.env` outside the repository only; no connection string or password appears in this report, the logs, or any repository file | `ls -l` |
| `TEST_DATABASE_URL` shape | `postgresql+asyncpg://…` (08 §8.4 Q1 recipe: the Phase 3 postgres fixtures pass the value verbatim into `Settings`, whose validator rejects the plain `postgresql://` form since the initial commit `7dce7ba` — a known baseline environment-shape fact, not a Phase 4 defect; Phase 4 fixtures additionally normalize either form internally) | 08 §8.4, A-0 |
| Alembic head | `alembic heads` = `0059_execution_runtime_host (head)` | A-0 |
| Raw logs of this round | `/tmp/p4t-logs/` (local temporary directory, not a persistent evidence archive; references below keep the verbatim tails this file claims) | — |
| Execution window | round 1: 2026-11-14 02:45–03:35 CST (HEAD `12d0f97`); round 3: 2026-11-14 03:45–04:00 CST (HEAD `2a2d626`) | `date` |

**Skip semantics**: with `TEST_DATABASE_URL` unset the PG halves skip by fixture design ("Set TEST_DATABASE_URL to a PostgreSQL role with CREATEDB"); every case in this report was therefore executed in the **PG-enabled** configuration (E02/E04–E07). The three `pending_env` skips print their attribution (08 R-3) and are itemised in §9.

## 2. Execution overview (commands and output tails)

All commands run from the repository root; every PostgreSQL command uses this prefix (secrets stay inside the shell environment):

```bash
set -a; . /tmp/nexusdesk-phase4-pg.env; set +a
export TEST_DATABASE_URL="${TEST_DATABASE_URL/postgresql:\/\//postgresql+asyncpg://}"
export AGENT_DATABASE_URL="$TEST_DATABASE_URL"
```

| # | Command | Output tail (verbatim) | exit |
|---|---|---|---|
| E01 | `env -u TEST_DATABASE_URL … pytest tests/ -k phase4 -q -rs` (no-PG configuration) | `302 passed, 42 skipped, 2503 deselected, 20 warnings in 4.28s` (39 fixture skips + 3 `pending_env` attribution skips) | 0 |
| E02 | `… pytest tests/ -k phase4 -q -rs` (PG enabled) | `341 passed, 3 skipped, 2503 deselected, 46 warnings in 41.05s` — the 3 skips are exactly the 08 §8.1 `pending_env` lanes | 0 |
| E03 | `… pytest tests/test_agent_execution_phase4_observability.py -q -rs` | `31 passed in 2.38s` (FR-9 surface incl. the P4-UT-21 full-surface secret scan over a real-process run) | 0 |
| E04 | `… pytest <4 T16 close-out nodes> -v -rs` (real-process e2e, subprocess spawn allowed) | `4 passed, 6 warnings in 4.43s` — nested ignore-TERM cancellation, output-flood termination, Run-deadline-wins race, cross-process SIGKILL worker crash recovered by same-`host_id` identity-verified restart; each ends asserting zero surviving trusted-test descendants | 0 |
| E05 | per-file runs (11 files, PG enabled) | settings `71 passed`; workdir `68 passed`; runner `81 passed`; supervisor `17 passed`; registry `11 passed`; runtime_host `10 passed`; sandbox `23 passed, 3 skipped`; orchestration `18 passed`; deployment `7 passed`; migration `4 passed` | 0 |
| E06 | `… pytest tests/ -k "phase3 or phase4" -q -rs` (PG enabled) | `758 passed, 3 skipped, 2086 deselected, 48 warnings in 54.94s` — equals the B6 handoff figure exactly | 0 |
| E07 | `env -u TEST_DATABASE_URL … pytest -q -rs` (full suite, PG sections auto-skip) | `2293 passed, 554 skipped, 25 warnings in 18.41s` — equals the B6 handoff figure exactly; 0 failed | 0 |
| E08 | `uv run ruff check src tests` | `All checks passed!` | 0 |
| E09 | `uv run python ../scripts/check_architecture.py` | `architecture gate passed` | 0 |
| E10 | `uv run ruff format --check <36 Phase 4 touched .py files + host/workspace packages>` | `27 files already formatted`; scoped rerun over the `git diff c63fd4a..HEAD --name-only` Python set: `36 files already formatted` | 0 |
| E11 | *(round 1, HEAD `12d0f97`, superseded)* `sh nexusdesk quickstart` on pre-existing volumes | `container nexusdesk-quickstart-app-1 is unhealthy` after `--wait-timeout 300`; app crash-looped (RestartCount 12) | 1 |
| E12 | *(round 1, HEAD `12d0f97`, superseded)* `down -v` then `sh nexusdesk quickstart` (true fresh boot, all volumes destroyed) | `container nexusdesk-quickstart-app-1 is unhealthy`; same deterministic traceback (24 identical failures in the container log) — this is the run that found **D-1** | 1 |
| E13 | *(round 1)* post-drill probes on the failing fresh stack | `alembic_version` = `0059_execution_runtime_host`; both Phase 4 tables present; `/data` = `credentials`, `tls` only; `AGENT_EXECUTION_RUNTIME_HOST_ENABLED=false`, host-id env absent. **Probe correction (integrity note)**: the round-1 `curl http://127.0.0.1:8080/` → `400` was an artifact of probing the TLS port over plain HTTP (nginx serves HTTPS on 8080 — confirmed by E16b where `https` → 200 and `http` → 400 on a healthy stack), so that single probe was never valid evidence of "backend down". D-1 stands on the decisive evidence instead: 24 identical `execution_configuration_invalid` tracebacks, `health=starting` with `RestartCount 12`, and the deterministic out-of-container repro in A-6 | 0 (probes) |
| E14 | *(round 3, HEAD `2a2d626`)* `pytest tests/test_seed_agent_profile_binding.py tests/test_agent_config_execution_compat.py -q` (no PG) | `8 passed, 14 skipped, 1 warning in 1.35s` (the skips are the PG-gated compat half, executed next) | 0 |
| E15 | *(round 3)* same affected surface with PG enabled, `-rs` | `22 passed, 1 warning in 7.07s` — **zero skips**, so the 3 new binding cases + all 19 compat cases actually executed | 0 |
| E16 | *(round 3)* `down -v` → `sh nexusdesk quickstart` fresh-volume drill on the fix tree | `Container nexusdesk-quickstart-app-1 Healthy`, `up_exit=0`; `health=healthy restarts=0`; `https://127.0.0.1:8080/` → **200** serving the React shell; crash markers in the app log = **0**; `alembic_version` = `0059_execution_runtime_host`; both tables present; `agents JOIN agent_versions` = **14** published (32 agents total) incl. all six memory-quadrant demo agents that crashed pre-fix; `/data` = `credentials`, `tls` only with `WORKDIR_ROOT=/data/execution` declared yet **never created**; `enabled=false`, host-id env count 0 | 0 |
| E17 | *(round 3)* `docker compose restart app` + poll-to-healthy, then `pytest tests/ -k phase4 -q -rs` with PG | restart re-greened in ~21 s (`restart_exit=0`, `restarts=0`, `https` → 200, crash markers 0, `alembic` still 0059, still 14 published — seed idempotent on re-boot, `/data` unchanged, `enabled=false`); smoke = **`341 passed, 3 skipped, 2506 deselected`** — identical to E02 (deselected grew 2503→2506 by exactly the 3 new binding tests) | 0 |

E01–E02 and the E05 per-file runs overlap by construction; the counts prove the commands ran and must not be summed into an independent coverage figure. The eleven `test_agent_execution_phase4_*.py` files collect **344** nodes.

## 3. Unit tests (P4-UT-01–22)

Aliases (paths relative to `backend/tests/`): `RUN` = `test_agent_execution_phase4_runner.py`; `SUP` = `test_agent_execution_phase4_supervisor.py`; `REG` = `test_agent_execution_phase4_registry.py`; `RH` = `test_agent_execution_phase4_runtime_host.py`; `WD` = `test_agent_execution_phase4_workdir.py`; `SBX` = `test_agent_execution_phase4_sandbox.py`; `SET` = `test_agent_execution_phase4_settings.py`; `OBS` = `test_agent_execution_phase4_observability.py`; `ORCH` = `test_agent_execution_phase4_orchestration.py`; `MIG` = `test_agent_execution_phase4_migration.py`; `DEP` = `test_agent_execution_phase4_deployment.py`. All rows: environment **macOS darwin 27.0.0 x86_64 / CPython 3.12.13 (uv); PG lanes via docker pgvector `pg17` (08 §8.2 string)**, evidence E02/E05.

| ID | Case | Test location (carrying functions) | Result | Boundary / evidence |
|---|---|---|---|---|
| P4-UT-01 | Two Adapters share the Host interface, no Engine branch, no direct spawn/signal | `RH::test_two_adapters_share_one_host_with_zero_engine_branching`, `RH::test_adapters_contain_no_direct_spawn_or_signal_code` | pass | AC-1 reuse proof at unit level |
| P4-UT-02 | Unregistered executable / arbitrary argv / sensitive env rejected pre-spawn; digest auditable without secrets | `RUN::test_registry_rejects_unregistered_and_arbitrary_argv`, `RUN::test_unregistered_executable_id_is_rejected`, `RUN::test_digest_helper_is_deterministic_and_argv_sensitive`, `RUN::test_digest_never_contains_argv_or_environment_text`, `RH::test_untrusted_target_rejected_before_record_and_spawn` | pass | digest = SHA-256, argv/env text never present (R-6) |
| P4-UT-03 | Per-stream byte limits, independent backpressure, group cleanup, stable error | `RUN::test_independent_per_stream_byte_limits_with_backpressure`, `RUN::test_host_gate_blocks_before_any_spawn` | pass | no unbounded buffering asserted on both streams independently |
| P4-UT-04 | TERM → grace → KILL machine, stable order/deadlines/reason; repeated cancel does not restart it | `SUP::test_honored_term_never_escalates_to_kill`, `SUP::test_ignored_term_escalates_to_group_kill`, `SUP::test_repeated_cancellation_enters_one_machine` | pass | fake-clock state machine |
| P4-UT-05 | Run deadline vs wall deadline vs cancellation race: earlier wins, one cleanup owner | `SUP::test_repeated_cancellation_enters_one_machine`, `SUP::test_cancel_after_result_returns_retained_progress`, `SUP::test_supervisor_requires_positive_windows` | pass | single-owner determinism without real processes |
| P4-UT-06 | Late success / duplicate exit / repeated cleanup are idempotent | `SUP::test_cancel_after_result_returns_retained_progress`, `SUP::test_real_normal_exit_and_repeat_semantics`, `SUP::test_terminal_handle_without_record_is_refused` | pass | cancelled state never overwritten |
| P4-UT-07 | Full identity match → orphaned → managed cleanup | `REG::test_decision_table_match_terminates`, `REG::test_decision_table_gone_group_is_absent` | pass | decision table over host/boot/PID/PGID/token/digest |
| P4-UT-08 | PID reuse / mismatched / foreign-host records → zero signals, manual remediation | `REG::test_decision_table_pid_reuse_gets_zero_signals`, `REG::test_decision_table_unavailable_identity_is_mismatch`, `REG::test_every_write_reasserts_host_id` | pass | fail-closed identity per R-6; OS corroboration tracked at IT-10 |
| P4-UT-09 | Reconcile under DB outage: bounded retry + alert, no host-wide scan | `REG::test_db_outage_raises_unavailable_without_any_scan`, `REG::test_registry_wraps_dbapi_errors_as_unavailable` | pass | zero command-name kill fallback |
| P4-UT-10 | Workdir path generation, permissions, monotonic states, retryable cleanup_failed | `WD::test_policy_accepts_platform_generated_relative_paths`, `WD::test_created_layout_is_0700_directories_under_a_0700_root`, `WD::test_workdir_status_machine_is_monotone_and_honest` | pass | client paths have no entry (see IT-16) |
| P4-UT-11 | Retention expiry split success/failed; duplicate cleanup deletes nothing else; Tombstone kept | `WD::test_retain_failed_window_and_state_rejection`, `WD::test_expired_retention_scan_selects_only_matured_rows`, `WD::test_remove_reports_already_absent_honestly` | pass | — |
| P4-UT-12 | Absolute/`..`/NUL/backslash/encoded separators/over-length all rejected; valid relative usable | `WD::test_policy_rejects_every_untrusted_path_shape`, `WD::test_tenant_digest_and_generated_path_are_never_raw_display_names` | pass | rejected before opening any external target |
| P4-UT-13 | Symlink/hardlink/mount policy, component-wise no-follow, shared handle | `WD::test_component_replace_sentinel_denies_symlinked_intermediate`, `WD::test_hardlink_denies_cleanup_but_never_touches_the_external_inode`, `WD::test_mount_denial_via_substituted_probe_aborts_before_deleting` | pass (measured half) | live mount-namespace half `pending_env` (04 §2.1, 08 §8.1); denial logic proven with substituted probe on APFS |
| P4-UT-14 | Unprovable cleanup scope / replacement race → stop, sentinel preserved, alert, no host-level recursion | `WD::test_removal_stops_on_deletion_race`, `WD::test_removal_refuses_outside_recorded_scope_and_foreign_owner` | pass | — |
| P4-UT-15 | Support-matrix combinations labeled hard/approximate/unsupported; missing required capability rejects start | `SBX::test_local_matrix_declares_supported_subset_and_holds_no_strong_claims`, `SBX::test_ladder_prefers_hard_then_labels_approximate_then_refuses`, `SBX::test_sampling_observes_real_group_and_excess_wires_to_supervisor` | pass | Linux hard-strength columns tracked at CM-07/IT-19/IT-20 |
| P4-UT-16 | Stable excess reasons, one resource-handle release, monitoring ≠ isolation | `SBX::test_release_is_idempotent_through_resource_manager`, `SBX::test_gate_refuses_even_when_enforcement_relaxed`, `SBX::test_rlimit_kill_classification_and_non_interference` | pass | excess vocabulary per R-14: reason code + mechanism/strength labels only |
| P4-UT-17 | Local Sandbox + replacement Provider contracts; Local declares no network/credential/strong isolation | `SBX::test_unenforced_is_recorded_not_silent`, `SBX::test_local_provider_end_to_end_admits_applies_releases`, `SBX::test_host_module_never_references_a_concrete_provider` | pass | AC-10/M1 wording audit inside the test |
| P4-UT-18 | Arbitrary commands / uploaded code / untrusted multi-tenant always denied; settings cannot flip | `SBX::test_every_untrusted_entry_is_refused_before_anything`, `SBX::test_gate_has_no_configuration_path`, `SBX::test_gate_refuses_even_when_enforcement_relaxed` | pass | gate is code-resident (08 §1.7 invariant) |
| P4-UT-19 | FR-10 defaults, `AGENT_` env overrides, invalid bounds reject before startup | `SET` file: 11 functions / 71 nodes incl. `test_phase4_settings_family_has_nineteen_fr10_keys`, `…_reject_values_outside_bounds`, `…_accept_inclusive_boundaries`, `…_family_is_named_by_the_fingerprint_exclude_set` | pass | default-off + R-8 fingerprint exclusion |
| P4-UT-20 | Registration-after-spawn and partial resource-prep failures clean up in reverse through the managed handle | `RUN::test_pipe_setup_failure_kills_group_and_reaps`, `RUN::test_spawn_failure_surfaces_when_exec_fails`, `ORCH::test_r11_violation_shape_is_refused_with_reverse_cleanup` | pass | no unowned process survives (failure injection) |
| P4-UT-21 | Public results/logs/metrics/DB metadata serialize no PID/PGID, host paths, tokens, env values, secret argv | `OBS::test_full_surface_secret_scan_real_run`, `OBS::test_observability_surface_stays_internal`, `RH::test_public_serialization_never_leaks_os_identity`, `RUN::test_secret_environment_values_never_reach_logs_or_output` | pass | scan covers a real-process run end to end (R-4b pin included) |
| P4-UT-22 | Health aggregation, low-cardinality labels, stalled reconcile alerts | `OBS::test_observability_vocabulary_is_frozen_and_low_cardinality`, `OBS::test_health_model_exposes_counters_with_zero_defaults`, `OBS::test_stalled_reconcile_alerts_once_per_episode` | pass | labels frozen in the vocabulary module |

## 4. Integration tests (P4-IT-01–30)

Environment column is abbreviated: **mac** = macOS development subset (04 §2.1 row 1, PG via docker pgvector where applicable); **pe** = Linux `pending_env` half (04 §2.1 row 2, 08 §8.1).

| ID | Case | Test location | Env | Result | Evidence / boundary |
|---|---|---|---|---|---|
| P4-IT-01 | Two different Adapters through the Orchestrator reuse one Host | `RH::test_two_adapters_share_one_host_with_zero_engine_branching`, `ORCH::test_orchestrator_end_to_end_with_real_processes` (distinct process-capable test adapters, `tests/agent_execution/process_test_adapters.py`) | mac | pass | zero Host/Worker source change between adapters |
| P4-IT-02 | Normal real-process start, bounded I/O, exit, result commit, event order | `ORCH::test_orchestrator_end_to_end_with_real_processes`, `ORCH::test_completed_run_prepares_once_activates_retains_success_window`, `RH::test_wait_persists_honest_exit_status`, `SUP::test_real_normal_exit_and_repeat_semantics` | mac | pass | E02/E04; process/resource/Workdir states complete independently |
| P4-IT-03 | Injected spawn / pipe / identity / registration failures | `RUN::test_spawn_failure_surfaces_when_exec_fails`, `RUN::test_pipe_setup_failure_kills_group_and_reaps`, `ORCH::test_start_failure_cleans_workdir_in_reverse`, `ORCH::test_activate_failure_cleans_and_blocks_start`, `ORCH::test_prepare_refusal_prevents_start_without_recorded_directory` | mac | pass | fail-closed, no unregistered process alive after each injection |
| P4-IT-04 | stdout/stderr floods while observing Worker scheduling | `SUP::test_real_output_flood_terminates_with_stable_reason`, `ORCH::test_orchestrator_output_flood_termination_e2e` (T16 close-out, real process) | mac | pass | group terminated at per-stream limit, stable `runtime_host_output_limit` reason, bounded memory |
| P4-IT-05 | Nested TERM-ignoring children; KILL sweeps the group | `SUP::test_real_nested_term_ignoring_children_die_with_the_group`, `ORCH::test_orchestrator_nested_ignore_term_cancellation_e2e` (T16 close-out), `SBX::test_child_group_membership_probe` | mac | pass | all observable descendants exited; zero surviving trusted-test descendants asserted |
| P4-IT-06 | Repeated cancellation, coroutine cancellation, late Adapter success | `ORCH::test_orchestrator_cancellation_race_with_real_process`, `ORCH::test_cancellation_wins_and_retains_cancellation_window`, `SUP::test_cancel_after_result_returns_retained_progress` | mac | pass | cleanup once; late result cannot overwrite cancelled Run |
| P4-IT-07 | Run deadline / wall timeout / cancellation, separately | `SUP::test_real_wall_deadline_terminates_group`, `SUP::test_real_earlier_run_deadline_wins_over_process_wall`, `ORCH::test_host_run_deadline_earlier_than_wall_with_real_process` (T16 close-out) | mac | pass | earlier deadline wins, no duplicate terminal state or zombie |
| P4-IT-08 | Kill Worker with live processes; restart same `host_id` recovers orphans | `REG::test_restart_recovery_terminates_identity_matched_orphan` (PG), `ORCH::test_worker_sigkill_crash_and_restart_recovery_e2e` (T16 close-out: real `subprocess.Popen` worker SIGKILLed, orphan survived, new boot instance terminated it via the identity-verified machine), `RH::test_disabled_host_still_recovers_existing_records` | mac | pass | E04; protocols never resumed, Runs never replayed; container-restart corroboration at IT-09 |
| P4-IT-09 | Container restart, persistent volume, stop-timeout drill | quickstart local-Docker drill (08 §8.3 recipe) — round 1 E11/E12/E13 found D-1; round 3 E16/E17 re-drilled on the fix tree `2a2d626` from **destroyed volumes** | mac + pe | **pass** (local-Docker half, round 3) | production half remains `pending_env` (08 §8.1). Fresh-volume drill on the fix tree: build → `up --wait` reached **Healthy** with `restarts=0`, seed completed publishing (`agents JOIN agent_versions` = 14, incl. the six memory-quadrant agents that crashed pre-fix), app log has **zero** `execution_configuration_invalid` / `Traceback` / `Deployment initialization failed` (24 before the fix), React root **200 over HTTPS**, `alembic_version=0059_execution_runtime_host` with both Phase 4 tables present, default-off zero-side-effect held (`enabled=false`, no host id, `/data` only `credentials/`+`tls/` while `WORKDIR_ROOT=/data/execution` was declared and never created), and `docker compose restart app` re-greened in ~21 s with the seed idempotent on re-boot (still 14, still no `/data/execution`). No image retag was needed this round — the base layers resolved from the local mirror cache, so no dockerproxy environment caveat applies. See §7 D-1 (fixed) |
| P4-IT-10 | PID-reuse construction, token/digest mismatch, unreadable identity → zero mistaken kills | `REG::test_decision_table_pid_reuse_gets_zero_signals`, `REG::test_pid_reuse_substitute_forbids_signals`, `REG::test_decision_table_unavailable_identity_is_mismatch` | mac (substitute half) | pass (measured half) | deterministic OS PID-reuse kill corroboration half `pending_env` (04 §2.1, 08 §8.1); records land in manual remediation with alerts, never blind-deleted |
| P4-IT-11 | DB disconnect / lock conflicts / partial batches during recovery | `REG::test_db_outage_raises_unavailable_without_any_scan`, `REG::test_pending_batches_are_bounded_and_skip_locked` (PG), `OBS::test_reconcile_deferral_alerts_on_registry_outage` | mac + PG | pass | `FOR UPDATE SKIP LOCKED` batches bounded, stalled state observable, no cross-batch privilege |
| P4-IT-12 | Process alive after Run terminal; exited with cleanup failure — both cleaned/alerted per actual state | `SUP::test_kill_ignored_is_cleanup_failed_with_alert_never_false_success`, `OBS::test_registry_durable_cleanup_failed_landing_alerts_once`, `WD::test_cleanup_failure_retains_record_and_never_repoints` | mac | pass | Run terminal ≠ release substituted anywhere (Principle 6) |
| P4-IT-13 | Concurrent same-tenant/cross-tenant Workdir creation; same-Run prepare converges to one `ready` (R-11) | `WD::test_concurrent_cross_tenant_prepare_and_fk_gate` (PG), `WD::test_prepare_converges_crashed_preparing_winner`, `WD::test_prepare_refuses_id_mismatch_and_post_terminal`, `WD::test_provider_takes_no_path_arguments` | mac + PG | pass | prepare never returns `preparing` (pin included); 0700/0600 verified; R-12 stale row never returned |
| P4-IT-14 | Retention expiry after completion/failure/cancellation; recovery across manager restart | `WD::test_prepare_activate_retain_cleanup_survive_a_manager_restart` (PG, process-level restart), `ORCH::test_failed_run_retains_failed_window_without_cleanup`, `WD::test_expired_retention_scan_selects_only_matured_rows` | mac + PG | pass | failed-evidence window never prematurely deleted |
| P4-IT-15 | Cleanup failures then repeated retries; Tombstone carries final successful observation (R-12) | `WD::test_prepare_fs_failure_records_cleanup_failed_then_recovers`, `WD::test_cleanup_reobserves_before_delete_and_keeps_final_observation`, `OBS::test_over_quota_and_cleanup_failed_landing_alerts_pg` | mac + PG | pass | retry idempotent after repair; alert visible; re-observation before delete pinned |
| P4-IT-16 | Adversarial paths via raw API/internal calls; valid relative paths work; no client host-path entry | `WD::test_tampered_relative_path_is_refused_and_marked_failed` (PG), `ORCH::test_missing_trusted_scope_fails_closed_before_any_side_effect`, `WD::test_provider_takes_no_path_arguments` | mac + PG | pass | zero external touches on rejection paths |
| P4-IT-17 | Symlinks/hardlinks/mount points to external sentinels; read/write/export/clean | `WD::test_symlink_inside_workdir_is_removed_without_touching_target`, `WD::test_hardlink_denies_cleanup_but_never_touches_the_external_inode`, `WD::test_component_replace_sentinel_denies_symlinked_intermediate` (APFS) | mac (non-mount half) | pass (measured half) | live mount-namespace half `pending_env` (04 §2.1); zero successful external read/write/delete on the measured matrix |
| P4-IT-18 | Replace directory/file with a link during concurrent cleanup | `WD::test_removal_stops_on_deletion_race`, `WD::test_component_replace_sentinel_denies_symlinked_intermediate` | mac | pass | uncertain scope stops, sentinel byte-identical, alert fired |
| P4-IT-19 | Exceed CPU-time and memory limits | `SBX::test_rlimit_cpu_excess_classifies_and_terminates` (approximation, labeled non-equivalent), `SBX::test_enforcement_decision_matches_address_space_applicability` (R-13 probe gate) | mac + pe | pass (measured half) | `SBX::test_cgroup_memory_hard_limit_full_acceptance` **skip with attribution** (E02: "cgroup v2 memory.max per-Execution hard limit needs the dedicated Linux full-acceptance environment"); RLIMIT_AS branch fail-closed when probe not applicable — never a recorded pass (R-13); excess evidence asserted via reason code + labels only (R-14) |
| P4-IT-20 | Spawn beyond the PID limit | `SBX::test_sampling_excess_decisions_pid_and_disk` (reactive sampled bound) | mac + pe | pass (measured half) | `SBX::test_cgroup_pids_hard_limit_full_acceptance` **skip with attribution** (pids.max hard limit pending_env, 08 §8.1); host totals never substituted for the bound |
| P4-IT-21 | Exceed per-file and total Workdir limits | `SBX::test_rlimit_fsize_excess_classifies_and_terminates` (per-file), `WD::test_retain_persists_overquota_observation_with_structured_alert`, `WD::test_failed_observation_never_overwrites_persisted_value` (R-12 accounting) | mac + pe | pass (measured half) | total-quota (fs/project quota) half `pending_env`: `SBX::test_fs_quota_total_enforcement_full_acceptance` **skip with attribution**; over-quota successful observation persisted + structured alert, not warn-only (R-12); disk isolation from other Runs asserted |
| P4-IT-22 | Wall-time + output excess with resource-sampling delay; backpressure; no supervisor leak | `SUP::test_real_output_flood_terminates_with_stable_reason`, `SBX::test_watch_returns_first_excess_and_alerts`, `ORCH::test_host_run_deadline_earlier_than_wall_with_real_process` | mac | pass | bounded termination time; sampling watch terminates; no unbounded buffering |
| P4-IT-23 | Start on macOS subset, cgroup disabled, and unsupported platform | `SBX::test_support_unsupported_refuses_before_record_or_spawn`, `SBX::test_enforcement_decision_matches_address_space_applicability`, `SBX::test_watch_returns_first_excess_and_alerts` | mac | pass | `execution_resource_enforcement_required=true` rejects missing capability at start; zero silent ignores (`SBX::test_unenforced_is_recorded_not_silent` records any unenforced lane) |
| P4-IT-24 | Replace Sandbox test Provider; untrusted entries still rejected | `SBX::test_provider_swap_needs_no_host_or_adapter_change`, `SBX::test_host_module_never_references_a_concrete_provider`, `SBX::test_gate_refuses_even_when_enforcement_relaxed` | mac | pass | contract unchanged after swap; all three untrusted entry classes rejected |
| P4-IT-25 | Observe normal/crash/orphan/cleanup-failure/resource-pressure/stalled-reconcile; no secrets on public reads | `OBS` file (31 cases, E03) incl. `test_full_surface_secret_scan_real_run`, `test_sweep_batch_reports_candidate_count_and_survives_failures`, `test_reconcile_manual_remediation_alerts_and_counts`, `test_supervisor_cleanup_failed_alert_carries_run_correlation` | mac (+PG lane) | pass | metrics/logs correlated by run_id/host_id; public surfaces scanned clean |
| P4-IT-26 | Upgrade `0059` from actual predecessor `0058` with concurrent old/new reads | `MIG::test_0059_revision_chain_is_a_single_head_on_0058`, `MIG::test_0059_upgrade_sql_contract_is_two_tables_and_five_indexes`, `MIG::test_0059_downgrade_drops_processes_before_workdirs`, `MIG::test_0059_chain_fk_semantics_and_reacts_across_upgrade` | mac + docker PG | pass | exactly two tables, no `runtime_runs` column, disposable downgrade order verified on the pgvector container; React reads/writes unimpeded across the upgrade |
| P4-IT-27 | Default-off React parity; stop admission → drain → disable → application rollback | `ORCH::test_seams_inert_for_react_selection_byte_parity`, `ORCH::test_closed_admission_cleans_prepared_workdir_and_blocks_start`, `RH::test_disabled_host_admits_nothing_and_touches_no_record`, `RH::test_close_stops_admission_drains_and_leaves_zero_active`, `RH::test_disabled_host_still_recovers_existing_records` | mac | pass | byte-parity to the Phase 3 accepted path with seams unset; rollback keeps both tables and needs no downgrade; the live default-off probe held in both rounds (E13 round 1, E16/E17 round 3: no `/data/execution`, `enabled=false`, no host id) |
| P4-IT-28 | Full rollback attempted with active / cleanup_failed processes | `RH::test_close_stops_admission_drains_and_leaves_zero_active` (admission stop + drain to zero active), `REG` manual-remediation lanes (`test_pid_reuse_substitute_forbids_signals`; rows keep `cleanup_failed`/manual-remediation and are never skipped), `WD::test_cleanup_failure_retains_record_and_never_repoints` | mac | pass (measured half) | the rollback procedure face on the production image (old code deployed with live processes) is `pending_env` (08 §8.1); on this host the blocking behavior — recovery/cleanup continues while admission is closed and uncertain-scope records demand manual remediation — is the composed evidence above |
| P4-IT-29 | Quickstart/production volumes, Host identity, stop grace | `DEP::test_production_runtime_worker_declares_both_volumes_and_host_identity`, `DEP::test_production_other_workers_have_no_execution_surface`, `DEP::test_quickstart_execution_defaults_are_off_and_rooted`, `DEP::test_quickstart_default_windows_fit_the_stop_grace`, `DEP::test_production_env_example_carries_the_fr10_block_with_no_secrets`, `DEP::test_backend_env_example_mirrors_the_fr10_defaults`, `DEP::test_compose_files_stay_parseable_after_phase4` | mac (static config half) | pass (measured half) | production-image runtime inspection half `pending_env` (08 §8.1); static face proves: execution volume only on runtime-worker, one host id per root, no shared execution root, examples secret-free (R-7) |
| P4-IT-30 | Supervision overhead vs Phase 0 baseline | — (no measuring test exists by design; the Phase 0 baseline is absent) | — | **not_measured / pending_env** | upstream Phase 0 baseline gap (08 R-2/§8.1); no target may be passed unmeasured (04 §4 IT-30 wording); blocks the corresponding enablement promise |

## 5. General checks (P4-CM-01–15)

| ID | Check | Evidence (location / command) | Env | Result | Boundary |
|---|---|---|---|---|---|
| P4-CM-01 | Migration online behavior and numbering | `MIG` 4 tests (E05); `alembic heads` = `0059_execution_runtime_host (head)`; `git diff --name-only c63fd4a..HEAD -- backend/migrations` = **A** `0059_execution_runtime_host.py` only (zero history edits); fresh-boot stack reached 0059 (E13) | mac + PG | pass | R-1 renumber procedure satisfied and revalidated at execution time |
| P4-CM-02 | Host/Adapter boundary | `RH::test_adapters_contain_no_direct_spawn_or_signal_code` (source scan), arch gate E09 `architecture gate passed`, public-model no-PID pins in `RH::test_public_serialization_never_leaks_os_identity` | mac | pass | two Adapters reuse the Host (IT-01) |
| P4-CM-03 | Process-group and I/O bounds | group coverage: `SUP::test_real_nested_term_ignoring_children_die_with_the_group`; stdout/stderr bounds: `RUN::test_independent_per_stream_byte_limits_with_backpressure`; log volume bounds in the observability sink design (structured lines only, bounded facts — `OBS::test_record_rejects_oversized_fact_strings`); idempotent cleanup per IT-12/UT-06 | mac | pass | — |
| P4-CM-04 | Restart identity and orphan recovery | host/boot/token/digest chain in `REG::test_restart_recovery_terminates_identity_matched_orphan` + `RUN::test_identity_matches_is_fail_closed` + `RUN::test_start_token_capture_is_platform_honest`; zero blind kills under DB failure (UT-09/IT-11) | mac | pass | PID-reuse kill corroboration half pending_env (IT-10) |
| P4-CM-05 | Workdir state and ownership | monotonic machine (`WD::test_workdir_status_machine_is_monotone_and_honest`), ownership rechecks (`WD::test_removal_refuses_outside_recorded_scope_and_foreign_owner`), retention/retry/Tombstone auditable (IT-14/IT-15) | mac + PG | pass | — |
| P4-CM-06 | Filesystem adversarial safety | traversal/encoding matrix `WD::test_policy_rejects_every_untrusted_path_shape`; link/race set `WD::test_symlink…/test_hardlink…/test_removal_stops_on_deletion_race`; fail-closed uncertain scope `WD::test_mount_denial_via_substituted_probe_aborts_before_deleting`; zero external modification across all of IT-16/17/18 | mac | pass | live mount half pending_env |
| P4-CM-07 | Resource support matrix (full Linux sign-off) | macOS column measured (`SBX::test_local_matrix_declares_supported_subset_and_holds_no_strong_claims`, `…_ladder_prefers_hard_then_labels_approximate_then_refuses`); approximations labeled non-equivalent; `enforcement_required=true` refuses missing capability | mac (column) | **skip — pending_env** | full matrix sign-off requires Linux (04 §2.1, 08 §8.1); blocks the AC-9 enablement promise |
| P4-CM-08 | Sandbox and untrusted-execution ban | `SBX::test_every_untrusted_entry_is_refused_before_anything`, `SBX::test_gate_has_no_configuration_path`; provider swap without weakening (IT-24) | mac | pass | code-resident gate, settings cannot flip |
| P4-CM-09 | Health and sensitive data | E03 (31/31) + secret scan over logs/events/DB metadata/real run (`OBS::test_full_surface_secret_scan_real_run`); deployment examples secret-free (`DEP::test_production_env_example_carries_the_fr10_block_with_no_secrets`) | mac | pass | no new public endpoint shipped (08 §8.5) |
| P4-CM-10 | Configuration and deployment | 19 FR-10 keys + bounds + defaults (`SET`, 71 nodes); compose structural set (`DEP`, 7 nodes) incl. one Host/one execution root and 45 s grace ≥ cancel+kill windows; `.env.example` non-secret blocks; live default-off probe E13 (round 1) and E16/E17 (round 3) | mac | pass | the live quickstart runtime face is where round 1 found D-1 (tracked at IT-09); fixed at `2a2d626` and re-drilled green in round 3, so no residual caveat |
| P4-CM-11 | Independent idempotent lifecycles | terminal-state independence (IT-12), repeated cancel/reconcile/cleanup without mistaken kill or deletion (`SUP::test_repeated_cancellation_enters_one_machine`, `REG` PG reconcile idempotence, `WD::test_cleanup_reobserves_before_delete…`) | mac + PG | pass | — |
| P4-CM-12 | Full rollback procedure | admission-stop/drain (`RH::test_close_stops_admission_drains_and_leaves_zero_active`), tables retained without downgrade (IT-26 pair + IT-27 rollback half), `cleanup_failed` blocks completion and demands manual remediation (IT-28 composition) | mac | pass | production-image rollback face pending_env (08 §8.1) |
| P4-CM-13 | Legacy-path regression | E06 `758 passed, 3 skipped` (Phase 0–3 selection with PG); E07 full suite `2293 passed, 0 failed` without PG; default-off zero side effects byte-parity test (IT-27) and E13 probe | mac + PG | pass | equals the B6 handoff figures exactly |
| P4-CM-14 | Environment limits and evidence integrity | every unavailable environment item is recorded `pending_env`/`not_measured` with attribution (§9), the skips print the attribution string themselves (E01/E02 `-rs` tails), and the corresponding enablement promises stay blocked | — | pass | this report is the honest ledger; no approximation passed as cgroup-equivalent (Principle 8) |
| P4-CM-15 | Phase boundary | grep sweep: no Codex integration; untrusted-execution flags exist only as deny inputs (`local_sandbox_provider.py` hard-rejects `arbitrary_command/uploaded_code/untrusted_multi_tenant`, no enable path); no multi-replica shared execution root (one-host-per-root pinned in `DEP`); Host stays default-off everywhere | mac | pass | network/credential isolation not claimed anywhere (UT-17/CM-08) |

## 6. Regression scope (04 §6)

- Phase 0/1/2/3 surface: `pytest tests/ -k "phase3 or phase4"` with PG = **758 passed, 3 skipped (attribution only)** in 54.9 s (E06); the three skips are the Phase 4 pending_env lanes, so no Phase 0–3 test skips or changes behavior.
- Full backend suite without PG env, round 1 at `12d0f97`: **2293 passed, 0 failed, 554 skipped** (E07) — PG lanes skip by fixture design; identical to the B6 handoff.
- Full backend suite without PG env at the fix commit `2a2d626`: **2296 passed, 0 failed** — *not independently re-executed by this lane* (round 3 was deliberately scoped to the D-1 blast radius to avoid a second full-table run); the figure is cited from the development lane's round-3 report and is consistent with round 1 plus exactly the 3 new `test_seed_agent_profile_binding.py` cases.
- Round-3 affected surface (independently executed here): `test_seed_agent_profile_binding.py` + `test_agent_config_execution_compat.py` = **22 passed, 0 skipped** with PG (E15; 8 passed/14 skipped without PG, E14), and the Phase 4 selection smoke = **341 passed, 3 attributed skips** (E17) — byte-for-byte the E02 result, so the fix moved nothing in the Phase 4 surface.
- Fix-scope audit (independently confirmed here): `git diff --name-only 12d0f97..2a2d626` touches only `applications/seed_memory_common.py`, the new test file, and 08 §8.3; `contracts/config.py` (`normalize_execution_config`), `business_capabilities/agent_config/` (`AgentService`, `ReactConfig`) are **untouched**, and the non-react branch of `ensure_agent` keeps the historical two-line plain assignment verbatim — so the "non-react path byte-identical" claim holds. `grep` over `src/` confirms the fixed site was the **only** post-construction `model_profile_id`/`model_profile_version` assignment in the tree (see T-Risk-6).
- Default-off React parity: `ORCH::test_seams_inert_for_react_selection_byte_parity` + byte-identical Phase 3 path assertions hold; the Phase 3 snapshot/barrier/orchestrator suites were not modified by Phase 4 except at the T13 seams (traceable in `git diff c63fd4a..HEAD`).
- Migration compatibility: old-code reads/writes across the 0058→0059 upgrade pinned on docker PG (`MIG::test_0059_chain_fk_semantics_and_reacts_across_upgrade`); paired downgrade order verified on a disposable DB (no production DB was touched at any point).
- Gates: ruff **All checks passed!** (E08), architecture gate **passed** (E09), scoped format check clean over the 36 touched + 27 phase-4-owned files (E10). No frontend surface exists in Phase 4 (08 §1), so `typecheck`/`i18n`/`build` are not applicable.
- Process hygiene: every real-process group above ends with the pinned "zero surviving trusted-test descendants" check (E04; per IT-02/04/05/07/08 test bodies); all destructive filesystem work ran under `tmp_path` execution roots or the disposable quickstart/PG containers, never on host roots or customer data (04 Principle 7).

## 7. Defects found during execution

| # | Level | Defect | Found by | Reproduction | Symptom | Traceability / origin | Disposition |
|---|---|---|---|---|---|---|---|
| D-1 | **P1 — FIXED (round 3)** | Quickstart first-boot never reached Healthy: deployment initialization crashed when the Phase-5 memory demo seed published its generated agents. **Root cause (one line)**: `seed_memory_common.ensure_agent` assigned the legacy `model_profile_id`/`model_profile_version` *after* constructing `AgentConfig`, leaving the canonical `react` alias at explicit nulls, so the draft's JSONB round-trip re-validated at `publish` as `react.model_profile_id=None` conflicting with the now-set legacy alias → `DomainError("execution_configuration_invalid", 409)` → entrypoint abort → container crash loop (RestartCount 12 observed) | P4-IT-09 quickstart re-drill, round 1 (E11/E12/E13) | Round 1: `sh nexusdesk quickstart` on destroyed volumes (E12) + out-of-container repro (A-6). **Round 3 verification on the fix tree**: same fresh-volume drill now Healthy (E16) | Round 1 symptom: app unhealthy, 24 identical tracebacks, crash loop. (Integrity note: the round-1 `http://` → 400 probe was a TLS-port protocol artifact, not evidence — see E13; the crash evidence above is independent and decisive.) Round 3: Healthy, `restarts=0`, **zero** crash markers, React 200 over HTTPS, 14 agents published | AC-12 / FR-10 deployment drill; **origin: introduced by Phase 3 commit `4318042`** (typed execution config) — `git diff c63fd4a..12d0f97` proved every file on the failing path byte-identical between the Phase 3 tip and round-1 HEAD; Phase 3 deferred the quickstart/seed drill (08 R-2 condition ③, #127/#128) so it was never executed there. Phase 4 code is exonerated by that identical-path diff. The B6 §8.3 Healthy claim was not a fabrication but was produced on a **re-used stale volume**, where `ensure_agent` finds the agents already present and skips the `publish` call entirely — masking the crash path; 08 §8.3 has since been revised by the dev lane to record this (T-Risk-2, closed) | **Fixed by `2a2d626` (round 3)**: react engines bind the profile at construction time (dump → write the identical value into *both* the `react` and legacy aliases → re-validate, which the Phase 3 normalizer accepts because it only rejects *unequal* pairs); the non-react branch keeps the historical plain assignment verbatim. `normalize_execution_config` / `AgentService` / `ReactConfig` untouched. Two new contract cases reverse-pin that a post-mutation draft is still rejected. **Targeted rerun result**: IT-09 drill green (E16/E17), affected surface 22 passed/0 skipped (E15), Phase 4 smoke unchanged at 341 passed/3 attributed skips (E17) |

No P0 was found, and D-1 is the only defect raised across both rounds — now closed, so **no P0/P1 remains open**. No other failing case exists in the measured set: every other measured case passed on first execution in round 1 and the round-3 reruns reproduced the same figures (the B6→HEAD test-only commit `12d0f97` retargeted one Phase 3 migration test, which re-passed inside E06; the fix commit `2a2d626` changed no Phase 4 result, E17).

### 7.1 Round 4: CI-discovered platform defect (D-2, P1) and its fix

CI run `43544575078` on PR #137 (job "Backend tests (postgres 1/2)") failed exactly one case with `AssertionError: assert 9 == 24` in `test_rlimit_cpu_excess_classifies_and_terminates`. This was **not** a test-wording problem: it exposed a classification defect that is invisible on macOS and only appears on the production target platform.

| # | Level | Defect | Found by | Reproduction | Symptom | Traceability / origin | Disposition |
|---|---|---|---|---|---|---|---|
| D-2 | **P1 — FIXED** | CPU-limit excess was misclassified on Linux. `ResourceManager.classify_result` attributed resource excess only from signal numbers 24/25 (SIGXCPU/SIGXFSZ) or trusted-target exit 86. With `soft==hard` `RLIMIT_CPU`, **Linux delivers SIGKILL(9) in the same tick** (measured directly in a Linux container: `signaled=True signal=9`) while macOS stops at SIGXCPU. A SIGKILL is indistinguishable by number from the Supervisor's own escalation, so on Linux a CPU-limit kill fell through to a plain `exited` — violating FR-7 and ruling R-14 (the stable reason code is the cross-platform contract) precisely where it matters | CI on PR #137, `postgres 1/2` job; reproduced in a Linux container (see A-11) | `pytest tests/test_agent_execution_phase4_sandbox.py::test_rlimit_cpu_excess_classifies_and_terminates` on Linux; kernel probe with `RLIMIT_CPU=(1,1)` | `ProcessResult(term_signal=9, stdout=b'', stderr=b'', wall_seconds=0.994, reason_code=exited)` — the empty stderr confirms the process was signal-killed rather than self-normalizing (the fsize path prints `resource-exceeded=fsize` and exits 86) | FR-7 / AC-9; ruling R-14. **Origin: Phase 4** (`bdfe087`), present in the round-1/round-3 macOS evidence because the macOS kernel path takes the SIGXCPU branch and never exercises SIGKILL | **Fixed**: attribution now uses the **initiator's recorded fact**, not the signal number — an otherwise-ambiguous SIGKILL over a Reservation whose CPU dimension resolved to `cpu_rlimit` at a non-`unenforced` strength is the kernel's CPU-limit enforcement, because the Supervisor never returns `REASON_EXITED` for its own escalations (those set CANCELLED / WALL_TIMEOUT / OUTPUT_LIMIT / PIPE_SETUP). Non-interference is pinned by unit tests: a SIGKILL *without* an applied CPU rlimit stays a plain exit, and a Supervisor-initiated SIGKILL carrying a non-EXITED reason is never reattributed. The end-to-end case now asserts the stable reason code plus the mechanism/strength label and accepts either documented signal (`{24, 9}`), never a single platform's number |

**Round-4 verification (both platforms, full Phase 4 suite, not just the one case):** macOS `23 passed / 3 skipped` for the sandbox file and `341 passed / 3 attributed skips` for all `-k phase4`; Linux container (real kernel, independent PG on :5444) `341 passed / 3 attributed skips` — identical to macOS, where CI's failing job had shown 274 passed / 1 failed / 9 skipped. The three skips remain correctly attributed: inside the Linux container `/sys/fs/cgroup` is **read-only** (Docker Desktop VM), so child cgroups cannot be created and the cgroup/fs-quota lanes stay legitimately `pending_env` rather than being faked. Nothing else in the resource-classification family (fsize 25 / exit 86, memory, PID, disk) needed a change — the defect was specific to the one signal the kernel cannot make unique.


## 8. pending_env / not_measured register (execution-round view; authoritative ledger stays 08 §8.1)

| Item | Cases/halves | Recorded as | Attribution (skip message / row) |
|---|---|---|---|
| cgroup v2 `memory.max` per-Execution hard limit | P4-IT-19 memory half | skip-with-attribution | `SBX:748 "pending_env (08 R-3): cgroup v2 memory.max …"` |
| cgroup v2 `pids.max` per-Execution hard limit | P4-IT-20 | skip-with-attribution | `SBX:757 "… pids.max …"` (reactive sampled half measured) |
| Filesystem/project quota enforcement | P4-IT-21 total half | skip-with-attribution | `SBX:766 "… filesystem/project quota …"` (per-file + accounting halves measured) |
| Live mount-namespace experiments | P4-UT-13, P4-IT-17 mount halves | pending_env halves | substituted-probe denial measured on APFS |
| Deterministic OS PID-reuse kill corroboration | P4-IT-10 OS-experiment half | pending_env half | substitute-decision + zero-signal pins measured |
| Production-image container restart / stop-timeout / runtime face | P4-IT-09 prod half, P4-IT-28 prod face, P4-IT-29 runtime half | pending_env | the quickstart-profile local half **is** measured and green (round 3, E16/E17); only the production-image runtime face stays blocked |
| Full support-matrix sign-off | P4-CM-07 | skip-pending_env | macOS column measured |
| Supervision overhead vs Phase 0 baseline | P4-IT-30 | not_measured + pending_env | upstream Phase 0 baseline gap (08 R-2) |

Per 04 §7/§2.1 and 05 C14 these rows keep their enablement promises blocked; none was substituted by an rlimit/supervisor approximation (Principle 8). The plain-driver `TEST_DATABASE_URL` form rejection (08 §8.4) is an environment-shape fact on the Phase 3 fixtures, verified consistent, not counted as a defect.

## 9. Residual risks (T-Risk numbering avoids the 08 R-n series)

| # | Level | Description | Disposition |
|---|---|---|---|
| T-Risk-1 | ~~P1~~ **resolved** | Round 1: any claim that quickstart boots clean was false at `12d0f97` (D-1). | Closed in round 3 — D-1 fixed at `2a2d626`, fresh-volume drill re-passed with `restarts=0` and zero crash markers (E16/E17). Nothing further owed |
| T-Risk-2 | ~~P3~~ **closed** | Round 1 recorded an unexplained divergence between B6's §8.3 "Healthy" claim and this lane's failing fresh boot at the same code paths. | **Root cause established: stale-volume masking, not conflicting evidence.** `ensure_agent` is idempotent by agent name — on a re-used volume the demo agents already exist, so the `publish` call that crashes is skipped entirely and the stack looks Healthy; only a volume-destroyed first boot reaches the crash path. This lane's round-1 `down -v` + fresh boot is what exposed it, and round 3 confirmed the same procedure passes on the fix tree. 08 §8.3 has been revised by the dev lane to state this. Residual process lesson: any quickstart drill must destroy volumes first, or it silently tests nothing |
| T-Risk-3 | ~~P3~~ **resolved** | Round 1: the seed→publish path had zero unit-test coverage, which is why 2293 green backend tests coexisted with a crash-looping quickstart. | Closed — `backend/tests/test_seed_agent_profile_binding.py` (3 cases) added by the fix: construction-time binding survives the publish reparse, a post-mutation draft shape stays **rejected** (reverse pin), and equal aliases round-trip cleanly. Executed here: 3/3 pass (E15) |
| T-Risk-4 | — | All §8 `pending_env` halves stay open until a Linux full-acceptance environment exists; they block enablement (`execution_runtime_host_enabled=true`), which Phase 4 never promises (08 R-2). | Carried as planned; no action this round. This is the only thing standing between "development subset proven" and "full AC-9/AC-5 proven" |
| T-Risk-5 | P3 | `applications/seed_memory_common.py` is a **pre-existing unformatted legacy file**: `ruff format --check` reports "1 file would be reformatted" at the fix commit *and* at its parent `12d0f97` (verified here by formatting the parent's blob), so the debt predates D-1 and the fix deliberately did not reformat it (keeping the diff reviewable). `ruff check` (lint) passes on it. | Non-blocking chore debt → recommend a separate `chore(backend)` formatting commit tracked as an issue; must not be folded into a Phase 4 functional change |
| T-Risk-6 | P3 | Same-pattern risk in future seed code: assigning `model_profile_id`/`model_profile_version` after `AgentConfig` construction reintroduces D-1 exactly. This lane independently confirmed by `grep` that the fixed site was the **only** such assignment in `src/` today, so there is no second live instance. | Recommend adding "model profile bound at construction, never post-mutation" to the code-review checklist (and the Phase 5+ seed authoring notes); the new reverse-pin test in T-Risk-3 is the automated backstop |

## 10. Exit criteria verdict and CI evidence

**Verdict: exit criteria MET for the macOS development subset, with the Linux-dependent rows honestly blocked (04 §7).** Clause by clause:

| 04 §7 clause | Status | Evidence |
|---|---|---|
| All P4-UT/IT/CM pass | **met** on every case measurable on this host: 57 full pass + 8 pass on their measured halves; the only non-pass rows are `pending_env`/`not_measured` (CM-07, IT-30 and the eight Linux halves), which 04 §7 explicitly treats as honest blocked states, *not* failures | §3–§5 tables, E02/E05/E17 |
| AC-1–AC-12 reproducible | **met** to the extent each AC is host-measurable; AC-9 (resource matrix) and the AC-5 production-restart face stay partial by environment, per 04 §2.1 | §3–§5 traceability column |
| Applicable regressions green | **met** — Phase 0–3 selection 758 passed/3 attributed skips (E06), full non-PG 2293 passed/0 failed at round-1 HEAD (E07) and 2296/0 at the fix commit (dev lane, cited not re-run), affected surface 22 passed/0 skipped (E15), Phase 4 smoke unchanged 341/3 (E17) | §6 |
| No P0/P1 remains open | **met** — D-1 (the sole P1) fixed at `2a2d626` and re-verified; zero P0 ever found | §7 |
| Zero external modifications, unrelated-process kills, untrusted execution, silently ignored limits | **met** — adversarial matrix IT-16/17/18 with sentinels byte-identical, identity-verified recovery with zero mistaken signals (UT-07/08, IT-08/10), untrusted gate hard-denied with no configuration path (UT-18, CM-08/15), every unenforced lane recorded rather than skipped (IT-23) | §3–§5 |
| Default-off React baseline diff zero | **met** — byte-parity test plus the live probe in both rounds: `enabled=false`, no host id, `/data/execution` declared but never created | IT-27, E13/E16 |
| Rollback leaves zero active orphans | **met** — drain-to-zero-active, tables retained without downgrade, `cleanup_failed` blocks completion and demands manual remediation | IT-27/IT-28, CM-12 |
| Unavailable-environment items blocked, not passed | **met** — 9 rows in §8 carry attribution strings printed by the skips themselves | §8, E01/E02 `-rs` |

- CI evidence: **pending** — the branch is unpushed by instruction, so no GitHub Actions run exists yet; push/PR CI (backend job including the full PG matrix) is to be appended after the coordinator's checkpoint push. Local CI-equivalent gates all green: E02/E06/E07/E08/E09/E10 plus round-3 E15/E17.
- Round-3 rerun scope was deliberately limited to the D-1 blast radius (fresh-volume drill E16/E17, affected surface E14/E15, Phase 4 smoke); the 67-row table from round 1 stands as the single authoritative execution and was not repeated, per the round-1 constraint.

### 10.1 Handoff to the acceptance lane (04 Principle 10: reuse, do not re-measure)

**Cite this report directly — no re-execution needed**: AC-1 (Host/Adapter decoupling, IT-01/CM-02), AC-2 (bounded spawn/IO with injected failures, IT-02/03/04), AC-3 and AC-4 (cancellation/deadline machines and races, IT-05/06/07/12), AC-6 (Workdir lifecycle, retention, Tombstone, R-11/R-12 accounting, IT-13/14/15), AC-7 and AC-8 (path/link/race containment with sentinels, IT-16/17/18), AC-10 (untrusted-execution ban and provider swap, IT-24/CM-08), AC-11 (observability and the full-surface secret scan, IT-25/CM-09), AC-12 configuration/migration/rollback faces (IT-26/27/28, CM-01/10/12), plus every gate (E08/E09/E10) and the regression set (E06/E07/E15/E17).

**Must be executed live by acceptance, because 06 cannot transfer them**: (a) any statement that AC-5 or AC-9 are *fully* proven — they are not; the nine §8 rows stay `pending_env`/`not_measured` and block the enablement promise, so acceptance must record that ceiling explicitly rather than reading a pass; (b) the quickstart drill's *user-visible* face if acceptance wants first-hand confirmation — the stack is left up and healthy (A-10) and re-drilling requires `down -v` first (T-Risk-2); (c) the production compose/runtime face (IT-09/28/29 production halves), which needs a Linux host; (d) CI, still pending until the branch is pushed. Acceptance must also carry the Phase 3 conditional ceiling forward (08 R-2) — Phase 4 never enables the Host, so no rollout claim is available to sign here.

## Appendix A — Local execution output snapshots (2026-11-14, repository root; secrets redacted by construction — none ever entered these files)

A-0 environment and gates

```text
$ git rev-parse HEAD && git status --porcelain | wc -l
12d0f978521adbd72e666c56fbc1d90f3c01a1b2
0
$ sw_vers; uname -m; uv run --directory backend python -V
ProductName: macOS  ProductVersion: 27.0.1  BuildVersion: 26A434
x86_64
Python 3.12.13
$ docker ps --format … | grep nexusdesk-phase4-pg
65c4aab91dc1  pgvector/pgvector:pg17  Up 3 hours  127.0.0.1:5443->5432/tcp
$ uv run --directory backend alembic heads
0059_execution_runtime_host (head)
$ uv run --directory backend ruff check src tests        → All checks passed!
$ uv run --directory backend python ../scripts/check_architecture.py → architecture gate passed
$ uv run --directory backend ruff format --check <27 files> / <36 touched files> → already formatted (both scopes)
```

A-1 phase4 without PG (E01) / with PG (E02)

```text
302 passed, 42 skipped, 2503 deselected, 20 warnings in 4.28s
341 passed, 3 skipped, 2503 deselected, 46 warnings in 41.05s
SKIPPED [1] tests/test_agent_execution_phase4_sandbox.py:748: pending_env (08 R-3): cgroup v2 memory.max per-Execution hard limit needs the dedicated Linux full-acceptance environment
SKIPPED [1] tests/test_agent_execution_phase4_sandbox.py:757: pending_env (08 R-3): cgroup v2 pids.max per-Execution hard limit needs the dedicated Linux full-acceptance environment
SKIPPED [1] tests/test_agent_execution_phase4_sandbox.py:766: pending_env (08 R-3): filesystem/project quota enforcement needs the dedicated Linux full-acceptance environment
```

A-2 observability file (E03) and T16 close-out group (E04, -v)

```text
31 passed in 2.38s
test_orchestrator_nested_ignore_term_cancellation_e2e PASSED [ 25%]
test_orchestrator_output_flood_termination_e2e PASSED [ 50%]
test_host_run_deadline_earlier_than_wall_with_real_process PASSED [ 75%]
test_worker_sigkill_crash_and_restart_recovery_e2e PASSED [100%]
4 passed, 6 warnings in 4.43s
```

A-3 per-file tails (E05)

```text
settings   71 passed in 1.09s      workdir     68 passed in 2.22s
runner     81 passed in 0.44s      supervisor  17 passed in 1.71s
registry   11 passed in 1.63s      runtime_host 10 passed in 1.72s
sandbox    23 passed, 3 skipped, 27 warnings in 23.05s
orchestration 18 passed, 14 warnings in 6.28s
deployment 7 passed in 0.07s       migration 4 passed, 4 warnings in 3.28s
```

A-4 regression (E06) / full suite (E07)

```text
758 passed, 3 skipped, 2086 deselected, 48 warnings in 54.94s
2293 passed, 554 skipped, 25 warnings in 18.41s   (exit 0)
```

A-5 quickstart drill, **round 1 at `12d0f97` — kept as the D-1 discovery record; superseded by A-7** (E11 stale-state attempt, E12 fresh boot, E13 probes)

```text
$ sh nexusdesk quickstart                      # both attempts, after down -v for E12
Container nexusdesk-quickstart-postgres-1 Healthy
Container nexusdesk-quickstart-mock-business-1 Healthy
container nexusdesk-quickstart-app-1 is unhealthy      (exit 1; --wait-timeout 300)

$ docker inspect …app-1 → health=starting restarts=12  (crash loop)
$ docker logs app-1 (tail, repeated 24x):
  File ".../applications/seed_memory_common.py", line 118, in ensure_agent
    await p.business.agents.publish(tenant, actor, agent["id"], agent["draft_revision"])
  File ".../business_capabilities/agent_config/service.py", line 245, in parse_config
    raise DomainError("execution_configuration_invalid", 409) from None
DomainError: execution_configuration_invalid
Deployment initialization failed: CalledProcessError. See deployment README.

$ docker exec postgres psql -tAc "select version_num from alembic_version;"   → 0059_execution_runtime_host
$ docker exec postgres psql -tAc "…tables…"                                    → execution_workdirs / runtime_host_processes
$ docker exec app sh -c 'ls /data'                                             → credentials  tls   (no /data/execution)
enabled=false ; host-id env count 0
$ curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/                → 400
  # correction: 8080 is the TLS port, so this plain-HTTP probe returns 400 on a
  # healthy stack too (A-7 shows https→200 / http→400 side by side). It is NOT
  # evidence of the failure; the tracebacks + unhealthy + RestartCount 12 are.
```

A-6 D-1 deterministic code-level reproduction (outside the repository)

```text
$ uv run --directory backend python /tmp/p4t-logs/repro_seed_cfg.py
draft keys: [... 'model_profile_id', 'model_profile_version', 'react', ...]
react in draft: {'model_profile_id': None, 'model_profile_version': None, 'max_model_rounds': 6} | profile id set: True
ROUND-TRIP FAILS: ValidationError
1 validation error for AgentConfig
react.model_profile_id
  Value error, react.model_profile_id conflicts with legacy model_profile_id [type=value_error, input_value=None, input_type=NoneType]
```

A-7 quickstart fresh-volume drill, **round 3 at the fix commit `2a2d626`** (E16 — the D-1 closure evidence)

```text
$ docker compose -f deploy/quickstart/compose.yaml down -v   # destroy volumes FIRST (T-Risk-2 lesson)
$ docker volume ls | grep -c quickstart                      → 0
$ sh nexusdesk quickstart
Container nexusdesk-quickstart-postgres-1 Healthy
Container nexusdesk-quickstart-mock-business-1 Healthy
Container nexusdesk-quickstart-app-1 Healthy
NexusDesk demo: https://localhost:8080
up_exit=0                                                    # --wait-timeout 300 satisfied

$ docker inspect …app-1 → health=healthy restarts=0
$ curl -sk -o /dev/null -w '%{http_code}' https://127.0.0.1:8080/   → 200
$ curl -s  -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/    → 400   (TLS port; see A-5 correction)
$ curl -sk https://127.0.0.1:8080/ | head -c 120
<!doctype html>
<html lang="zh-CN"><head><meta charset="UTF-8" /><meta name="viewport" content="width=device-width, init

$ docker logs app-1 | grep -c execution_configuration_invalid → 0     (was 24 pre-fix)
$ docker logs app-1 | grep -c Traceback                       → 0
$ docker logs app-1 | grep -c "Deployment initialization failed" → 0

$ psql -tAc "select version_num from alembic_version;"        → 0059_execution_runtime_host
$ psql -tAc "…information_schema.tables…"                     → execution_workdirs / runtime_host_processes
$ psql -tAc "select count(*) from agents a join agent_versions v on v.agent_id=a.id;" → 14
$ psql -tAc "select count(*) from agents;"                    → 32
$ psql -tAc "select a.name from agents a join agent_versions v …"  → incl. 记忆全开助手 / 记忆关闭助手 /
  只读记忆助手 / 人工审核记忆助手 / 画像演示助手 / 摘要演示助手 …  (the seed_memory_phase5 quadrant set
  that crash-looped pre-fix — all published)

$ docker exec app sh -c 'ls /data'                            → credentials  tls
$ docker exec app … enabled=$AGENT_EXECUTION_RUNTIME_HOST_ENABLED → false
$ docker exec app … host_id_count=$(env | grep -c AGENT_EXECUTION_RUNTIME_HOST_ID) → 0
$ docker exec app … workdir_root=$AGENT_EXECUTION_WORKDIR_ROOT → /data/execution   (declared, never created)
```

Note: no base-image retag was needed this round — the layers resolved from the local mirror cache, so unlike B6's §8.3 there is no dockerproxy environment caveat to attach.

A-8 restart round-trip, round 3 (E17 first half)

```text
=== restart issued 03:56:57 ===
 Container nexusdesk-quickstart-app-1 Restarting
 Container nexusdesk-quickstart-app-1 Started
restart_exit=0
=== re-healthy 03:57:18 ===                      # ~21 s
health=healthy restarts=0 startedAt=2026-11-13T19:57:00Z
https_root_after_restart=200
crash_markers=0                                  # execution_configuration_invalid|Traceback|init-failed
0059_execution_runtime_host
14                                               # seed idempotent on re-boot: still 14, no duplicates
credentials
tls
enabled=false
```

(`docker compose restart` rejects `--wait` in this compose version — the first attempt exited 1 on `unknown flag: --wait` before doing anything; the round-trip above was therefore driven by an explicit poll-to-healthy loop, which is the stronger form of the check.)

A-9 affected surface and fix-scope audit, round 3 (E14/E15/E17)

```text
$ uv run pytest tests/test_seed_agent_profile_binding.py tests/test_agent_config_execution_compat.py -q
8 passed, 14 skipped, 1 warning in 1.35s                 # skips = PG-gated compat half
$ (same, PG enabled, -rs)
22 passed, 1 warning in 7.07s                            # zero skips → everything executed
$ uv run pytest tests/test_seed_agent_profile_binding.py -q
3 passed, 1 warning in 0.82s
   ::test_ensure_agent_binding_survives_publish_reparse
   ::test_post_mutation_draft_shape_stays_rejected        # reverse pin
   ::test_equal_aliases_round_trip_cleanly
$ (PG enabled) pytest tests/ -k phase4 -q -rs
341 passed, 3 skipped, 2506 deselected, 46 warnings in 41.16s   # == E02; deselected +3 = the new cases
SKIPPED …sandbox.py:748 / :757 / :766  pending_env (08 R-3) …    # unchanged attributions

$ git diff --name-only 12d0f97..2a2d626 -- …contracts/config.py …business_capabilities/agent_config/
(empty)                                                  # normalizer / AgentService / ReactConfig untouched
$ grep -rn "\.model_profile_id = \|\.model_profile_version = " src/ | grep -v seed_memory_common.py
(empty)                                                  # fixed site was the only one (T-Risk-6)
$ uv run ruff format --check src/…/seed_memory_common.py → 1 file would be reformatted
$ uv run ruff format --check <same file at parent 12d0f97> → 1 file would be reformatted   # pre-existing (T-Risk-5)
$ uv run ruff check src/…/seed_memory_common.py          → All checks passed!
```

A-10 stack state left behind: the quickstart stack is **up and healthy** on fresh volumes (app/postgres/mock all healthy, `restarts=0`) and `nexusdesk-phase4-pg` is running as before, so the acceptance lane can inspect the live drill directly. Round 1's crash-looping app container was stopped at the time to end the restart loop; round 3 replaced that state entirely. The working tree remained clean throughout both rounds except this report file.
