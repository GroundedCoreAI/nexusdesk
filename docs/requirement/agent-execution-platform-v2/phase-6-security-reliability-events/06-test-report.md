# Phase 6 · Security, Reliability, and Event Governance — Test Report

> Status: Completed code-focused execution; under the 2026-11-18 scope-limited revision, the functional/security/switch evidence satisfies current-stage acceptance. The `pending_env`, `pending_upstream`, `not_measured`, and CI items below are retained as historical records only and are out of scope for the current stage, not exit blockers.
> Created: 2026-11-17
> Revised: 2026-11-18 (scope-limited acceptance revision: CI provenance/final-PR-head CI evidence, performance/p50/p95/Outbox lag/recovery time/lock budget, sample counts, matched pairs, report latency, and real/authorized historical baselines are no longer exit criteria; all historical test numbers and verdicts are preserved unchanged; only their stage-gate status was revised)
> Basis: `04-test-plan.en.md` (P6-UT-01–22, P6-IT-01–25, P6-CM-01–10), `02-requirements.en.md` (FR/AC), `08-implementation-breakdown.en.md` (R-1–R-19)
> Execution: testing subagent; target development SHA `d0f02fa3b173d7ebf815ea01db0ba594aa35208b`; test additions committed separately below

## 1. Test Scope and Environments

Scope followed all 57 rows in 04, plus Phase 0 P0-I4 disposition, R-18/R-19 production wiring, real child environment forwarding, retry safety, focused fault/concurrency coverage, and reusable affected regressions. Historical 155/915/364/196 totals overlap and were not added or repeated wholesale.

| Environment | Exact configuration | Use |
|---|---|---|
| Host | Darwin 27.0.0 arm64; `uv run` Python 3.12.13 | pytest, ruff, architecture gate |
| PostgreSQL | Existing `nexusdesk-phase6-pg`, PostgreSQL 17.11/pgvector, `127.0.0.1:55432/phase6`, head `0071_execution_credential`; role has CREATEDB | PG integration and uniquely named disposable migration databases |
| Docker | Docker 29.9.2, Linux/aarch64, `alpine:latest` arm64 | Real container, internal-network/proxy, Secret-channel and resource drills |
| Models/engines | Controlled adapters/orchestrators and existing DemoModel/Codex Host tests | Deterministic behavior; no production Codex routing claim |
| CI | No PR/push requested; no CI run exists | Full final backend/frontend suite remains CI-owned |

No pre-existing container or volume was stopped/deleted. Tests created only disposable databases, networks and auto-removed containers. Post-drill inspection showed only `nexusdesk-phase6-pg` and no residual `nexus-egress-*` network. Secure defaults were read directly: `execution_untrusted_tenants_enabled=false`, `execution_sandbox_required=true`, `execution_network_default_deny=true`, `execution_event_cleanup_enabled=false`.

**Skip/boundary statement:** the consolidated scope had no skips. Earlier invocation of the R2 PG tests without `TEST_DATABASE_URL` produced two expected skips and was rerun correctly with PG; it is not counted as evidence. Local Docker is not a dedicated production-like adversarial Linux host. Real two-Worker SIGKILL/mixed infrastructure faults, representative populated-replica locks, full sandbox/file attack acceptance, Phase 0/5 evidence and real Session/Resume remain explicitly open below.

## 2. Execution Overview

| Item | Result | Evidence |
|---|---|---|
| Consolidated affected Phase 6 + runtime + Codex scope | **260 passed, 37 warnings, 0 failed/skipped in 36.90s** | Appendix A-2 |
| Post-format T-12 additions | **5 passed in 1.67s** | Appendix A-3 |
| Controlled Resume-equivalent grant reauthorization | **1 passed in 0.52s** | Appendix A-4 |
| Populated migration/rollback duration rerun | **3 passed in 6.61s; 0070 upgrade 0.376s** | Appendix A-5 |
| `uv run ruff check src tests` | All checks passed | Appendix A-1 |
| New-file format checks | Passed | Appendix A-1 |
| Architecture gate | Passed | Appendix A-1 |
| 57-row verdicts | **44 pass, 10 pending_env, 2 pending_upstream, 1 not_measured; 0 known failed code rows** | §3–5 |
| CI | **Not run / absent** | §9 |

The latest distinct scope accounts for 261 tests: the 260-test consolidated run plus the later Resume test. The five post-format tests are already members of the 260 and were rerun only to verify formatting did not alter behavior. Earlier 22/10/5/3-case focused runs and development's 196-case run overlap this scope and are not additive.

## 3. Unit Tests (P6-UT) — Individual Results

All locations are under `backend/tests/`. “PG” means the environment above; “reuse” means unchanged passed evidence retained under 08 §3.

| ID | Test location(s) | Environment | Verdict / evidence |
|---|---|---|---|
| P6-UT-01 | `test_execution_credentials.py::test_missing_runtime_key_fails_closed_without_auto_creation`, `::test_ciphertext_is_bound_to_credential_tenant_and_version`, `::test_credential_create_rotate_revoke_is_versioned` | PG | **pass** — missing key/binding/rotation/revocation fail closed |
| P6-UT-02 | `test_execution_credentials.py::test_grants_bind_run_engine_workspace_scope_and_ttl`, `::test_grant_denials_cover_expiry_revocation_scope_and_tenant` | PG | **pass** — Run/Engine/Workspace/scope/TTL/replay binding |
| P6-UT-03 | `test_execution_t12_resume_grant.py::test_resume_equivalent_new_run_requires_and_receives_new_grant` | PG | **pass** — controlled new-Run reauthorization; real Session Resume remains IT-02 pending_upstream |
| P6-UT-04 | `test_execution_credentials.py::test_common_redaction_covers_registered_values_patterns_and_structure`; `test_execution_r18_raw_sample_leak.py` | Local/PG | **pass** — nested/pattern/canary/bounded redaction and raw-sample fail-closed behavior |
| P6-UT-05 | `test_execution_sandbox.py::test_local_provider_still_rejects_every_untrusted_shape`, `::test_docker_launch_plan_is_server_generated_default_deny_and_minimal`; `test_execution_phase6_settings.py::test_untrusted_execution_cannot_disable_the_sandbox_or_use_local` | Local | **pass** — server-owned policy and Local denial |
| P6-UT-06 | `test_execution_sandbox.py::test_network_policy_allows_only_public_allowlisted_destinations`, `::test_network_policy_denies_private_loopback_linklocal_and_metadata`, `::test_dns_rebinding_and_redirects_are_checked_per_hop` | Local | **pass** — pure per-hop/IP decisions |
| P6-UT-07 | `test_agent_execution_phase4_workdir.py::test_policy_rejects_every_untrusted_path_shape`, `::test_component_replace_sentinel_denies_symlinked_intermediate`, `::test_hardlink_denies_cleanup_but_never_touches_the_external_inode`, `::test_removal_stops_on_deletion_race` | Reuse | **pass** — unchanged path/link/TOCTOU evidence |
| P6-UT-08 | `test_execution_fencing.py::test_claim_epoch_and_takeover_are_monotonic` | PG | **pass** — monotonic epoch/conditional writes |
| P6-UT-09 | `test_execution_phase6_dtos.py::test_ownership_operations_cover_every_fenced_write_surface`; stale-write tests in `test_execution_fencing.py`, `test_execution_events.py`, `test_execution_usage.py`; `test_execution_r19_replay_terminal.py` | PG | **pass** — available state/event/usage/replay/process/Workdir/resource surfaces |
| P6-UT-10 | `test_execution_recovery.py`; `test_execution_r19_boundary_reaper.py::test_recovery_fences_epoch_before_cleanup_runs`, `::test_live_worker_reaper_uses_confirmed_recovery` | PG | **pass** — recovery/cleanup decision and live reaper wiring |
| P6-UT-11 | `test_execution_recovery.py::test_terminal_decision_never_confirms_cancelled_without_cleanup`, `::test_unconfirmed_cancellation_is_failed_never_cancelled`, `::test_confirmed_cancellation_reports_cancelled_once` | PG | **pass** — confirmed/idempotent cancellation |
| P6-UT-12 | `test_execution_t12_additional.py::test_run_capacity_and_host_reservation_release_independently`; `test_execution_fencing.py::test_resource_release_honors_an_ownership_guard` | PG | **pass** — independent capacity/reservation release and idempotency |
| P6-UT-13 | `test_execution_recovery.py::test_retry_matrix_only_retries_proven_safe_cases`; `test_execution_t12_matrix.py::test_prepare_retry_refuses_ambiguous_or_postlaunch_failure` | PG | **pass** — ambiguous timeout/disconnect/Worker loss denied |
| P6-UT-14 | `test_execution_phase6_dtos.py` event identity/version tests; `test_execution_events.py::test_adapter_sequence_is_metadata_and_durable_sequence_is_database_owned` | PG | **pass** — current v1 and unknown-version boundary preserved |
| P6-UT-15 | `test_execution_t12_matrix.py::test_concurrent_sequence_and_producer_dedup` | PG | **pass** — 20 concurrent unique writes, 12-way producer dedup, contiguous seq/one Outbox |
| P6-UT-16 | `test_execution_outbox.py::test_dispatch_publishes_through_the_existing_envelope`, `::test_failed_publication_stays_pending_with_bounded_error` | PG | **pass** — pending/published/backoff/stable error |
| P6-UT-17 | `test_execution_sse.py::test_cursor_merge_uses_strict_maximum_of_query_and_header`, `::test_invalid_cursors_are_rejected`, `::test_retention_gap_is_only_below_a_positive_floor`, `::test_cursor_below_retention_floor_returns_explicit_409` | Local/PG | **pass** — strict max, 400/409 semantics |
| P6-UT-18 | `test_execution_usage.py::test_normalize_usage_keeps_unknown_explicit_and_never_zero_fills`, `::test_aggregate_effective_usage_ignores_superseded_rows`, `::test_native_usage_is_idempotent_and_corrections_form_a_chain` | PG | **pass** — uniqueness/corrections/unknown/rebuild |
| P6-UT-19 | `test_execution_usage.py::test_old_epoch_usage_is_denied_and_creates_no_ledger_or_outbox` | PG | **pass** — zero stale ledger/Outbox writes |
| P6-UT-20 | `test_execution_diagnostics.py`; `test_execution_r18_raw_sample_leak.py`; `test_execution_t12_additional.py::test_continuous_diagnostics_are_bounded_redacted_and_trigger_disclosure` | PG | **pass** — categories/rate limits/no recursion/redaction |
| P6-UT-21 | `test_execution_phase6_settings.py`; `test_execution_phase6_invariants.py::test_defaults_never_enable_untrusted_or_history_deletion` | Local | **pass** — bounded secure defaults |
| P6-UT-22 | `test_execution_phase6_invariants.py::test_outbox_trigger_is_independent_of_the_publisher_switch`; `test_execution_phase6_settings.py::test_phase6_rollout_family_stays_out_of_the_runtime_fingerprint` | PG | **pass** — publisher switch does not disable source-of-truth/security |

## 4. Integration Tests (P6-IT) — Individual Results

| ID | Test location(s) | Verdict / evidence |
|---|---|---|
| P6-IT-01 | `test_execution_credentials.py` lifecycle/audit/admin-route tests; `test_execution_credentials_migration.py` | **pass** — encrypted/versioned/tenant-role/Secret-free controlled evidence |
| P6-IT-02 | Direct grant adversarial tests plus `test_execution_t12_resume_grant.py` | **pending_upstream** — controlled reauthorization passes; real Stage B Session/Resume does not exist (R-9) |
| P6-IT-03 | `test_execution_r18_launch_redaction.py`, `test_execution_r18_emission_redaction.py`, `test_execution_r18_wiring.py`, `test_execution_t12_real_drills.py::test_real_docker_child_receives_controlled_secret_without_echo` | **pass** — Host/Broker, SSE/Outbox/artifact redaction, disclosure revoke/admission close, real child Secret without argv/output leak |
| P6-IT-04 | `test_execution_sandbox.py` real default-deny/read-only/PID tests; `test_execution_t12_real_drills.py::test_real_docker_memory_and_tmpfs_exhaustion_do_not_affect_host` | **pending_env** — local containment/nonzero exhaustion evidence passes; dedicated host escape/privilege/cgroup/OOM attribution matrix not complete |
| P6-IT-05 | `test_execution_r18_allowlist_proxy.py::test_allowlist_proxy_permits_allowed_and_denies_metadata`; network pure tests | **pending_env** — real internal-network allowed request, evil proxy denial, metadata/direct-IP denial and residue pass locally; production managed DNS/rebinding/decoy matrix remains |
| P6-IT-06 | Phase 4 Workdir tests (reuse), Docker minimal mounts | **pending_env** — controlled path/mount evidence; real cross-tenant/device/malicious-artifact export/residue attack matrix remains |
| P6-IT-07 | `test_execution_fencing.py`, `test_execution_events.py`, `test_execution_usage.py`, `test_execution_r19_replay_terminal.py` | **pending_env** — controlled zero-stale-write matrix passes; real two-Worker drill remains; real Session substep also pending_upstream |
| P6-IT-08 | `test_execution_r19_boundary_reaper.py`, reused `test_runtime_postgres.py::test_lost_worker_is_failed_and_cannot_publish_late_result` | **pending_env** — controlled live reaper passes; actual Worker SIGKILL/heartbeat-stall/late-result process drill not executed |
| P6-IT-09 | `test_execution_t12_matrix.py::test_takeover_heartbeat_finish_race_has_one_effective_terminal` | **pass** — concurrent race and deferred `SKIP LOCKED` recovery preserve one effective terminal |
| P6-IT-10 | Recovery confirmation tests; reused real TERM/KILL/wall cases in `test_agent_execution_phase4_supervisor.py` | **pass** — confirmed normal/forced state machine; mixed-fault residue remains IT-25 |
| P6-IT-11 | `test_execution_recovery.py::test_reap_cleanup_failure_is_failed_and_alertable`; live reaper test | **pending_env** — cleanup failure is honest in controlled path; real Worker-loss orphan/FD/mount/reservation proof remains |
| P6-IT-12 | `test_execution_t12_matrix.py::test_prepare_retry_refuses_ambiguous_or_postlaunch_failure`; `test_execution_recovery.py::test_safe_retry_correlates_without_duplicate_attempts` | **pass** — safe correlation and ambiguous refusal after D4 fix |
| P6-IT-13 | `test_execution_t12_matrix.py::test_external_write_policy_requires_explicit_idempotency_for_manual_retry`; replay idempotency tests | **pass** — no automatic replay with external effects; controlled idempotency boundary preserved |
| P6-IT-14 | `test_execution_t12_matrix.py::test_concurrent_sequence_and_producer_dedup`; event DTO tests | **pass** — compatible v1/unknown handling and concurrent monotonic seq |
| P6-IT-15 | Concurrent dedup test plus `test_execution_r18_native_usage.py` | **pass** — one event/seq/Outbox/source-unique usage under duplicate delivery |
| P6-IT-16 | `test_execution_t12_matrix.py::test_finish_precommit_hook_fault_rolls_back_everything`, `::test_finish_postcommit_fault_recovers_pending_outbox` | **pass** — no partial pre-commit state/usage; post-commit rescan completes pending Outbox |
| P6-IT-17 | `test_execution_t12_matrix.py::test_outbox_after_enqueue_crash_is_idempotent_on_rescan`; `test_execution_outbox.py::test_durable_bus_enqueue_is_acknowledged_and_idempotent` | **pass** — after-accept failure retries with stable event identity/idempotency |
| P6-IT-18 | `test_execution_sse.py::test_multipage_reconnect_terminal_catchup_and_additive_metadata`; existing 200+/transient runtime SSE tests | **pass** — 205 native events plus lifecycle frames, reconnect and additive `_execution` only |
| P6-IT-19 | `test_execution_t12_matrix.py::test_sse_subscribe_terminal_race_delivers_final_event`; cursor 400/409 tests | **pass** — final event observed across subscribe/finish race |
| P6-IT-20 | `test_execution_t12_worker_usage.py::test_worker_persists_adapter_native_usage_and_terminal_usage`; usage correction/old-epoch tests | **pass** — actual Worker path persists native 7 and terminal 8 separately, without recount |
| P6-IT-21 | `test_execution_t12_additional.py::test_continuous_diagnostics_are_bounded_redacted_and_trigger_disclosure`; diagnostics mapper tests | **pass** — 20 failures limited to 3, 17 suppressed, redacted, disclosure audit Secret-free |
| P6-IT-22 | `test_execution_migration.py::test_0070_chain_backfill_outbox_usage_and_data_preserving_downgrade` | **pending_env** — real small populated upgrade/backfill/direct writer passes (0.376s); representative replica lock budget absent |
| P6-IT-23 | `test_execution_credentials_migration.py::test_0071_chain_versions_grants_and_data_preserving_downgrade`, `::test_0071_empty_downgrade_succeeds` | **pass** — populated protection and empty downgrade |
| P6-IT-24 | Composition/settings/invariants plus consolidated React/Codex/API/SSE regressions | **pending_upstream** — affected code is green; Phase 0 zero-diff and full Phase 5 Stage A prerequisites remain, CI absent |
| P6-IT-25 | Controlled fault tests and real resource drills | **pending_env** — no real mixed SIGKILL + network loss + disk full + hang reconciliation run |

## 5. General Checks (P6-CM) — Individual Results

| ID | Evidence | Environment | Verdict |
|---|---|---|---|
| P6-CM-01 | `test_execution_phase6_invariants.py::test_single_migration_head_and_revision_lengths`; both migration chain tests | Local/PG | **pass** — single `0071_execution_credential`, IDs <=32, additive historical protection |
| P6-CM-02 | 0070 populated deterministic backfill/repeat upgrade | Small local PG | **pending_env** — representative populated-replica lock evidence not measured |
| P6-CM-03 | R18 boundary canaries, audit tests, deployment/migration Secret scans, real child no-echo | PG/Docker | **pass** — controlled ordinary outputs/audit contain no canary/grant token |
| P6-CM-04 | Settings/invariants and direct secure-default read | Local | **pass** — verified disabled-state C12 gate; untrusted=false, sandbox/default-deny=true |
| P6-CM-05 | Credential tenant/route tests, fencing, Outbox tenant scope, reused Workdir isolation | PG/reuse | **pass** — controlled tenant/Workspace isolation; real attacks remain IT-04–06 |
| P6-CM-06 | Static operation vocabulary plus dynamic stale-write/fault tests | PG | **pass** — available write surfaces fenced; real Worker drill remains IT-07/08 |
| P6-CM-07 | Outbox fault, SSE multipage/retention/race and terminal tests | PG/HTTP | **pass** — source-of-truth/replay/final-event consistency |
| P6-CM-08 | Composition loops, cleanup failure, independent quota, local container residue checks | PG/Docker | **pending_env** — full mixed-failure process/FD/mount/volume/grant/alert reconciliation absent |
| P6-CM-09 | Read-only script compared English/Chinese ID sets in 02/03/04/05/08 and counted 22/25/10 IDs | Local | **pass** — `IDs_MATCH` for all five pairs; UT=22, IT=25, CM=10 |
| P6-CM-10 | Only small migration duration measured | Local | **not_measured** — p50/p95, Outbox lag, recovery time and representative locks await Phase 0/representative environment |

## 6. Regression Scope

- The consolidated command included all new R-18/R-19/R2/T-12 tests, existing Phase 6 credential/migration/fencing/event/Outbox/SSE/usage/recovery/composition tests, `test_runtime_postgres.py`, `tests/agent_execution/test_codex_host_integration.py`, and `test_host_stdin_delivery.py`: **260 passed**.
- Unchanged Phase 4 Supervisor and Workdir evidence is reused under 08 §3; no wholesale old 915/364 run was repeated.
- Existing runtime SSE replay regression was retained with the R-19 terminal-replay correction: replay is written before finish, and post-terminal replay is denied. Phase 0 P0-I4 is closed by `test_execution_r19_replay_terminal.py` post-terminal and expired-lease denial, not silently inherited.
- Production adapter selection remains React-only and Stage B remains locked. Controlled Codex tests are not production-routing evidence.

## 7. Defects Found and Fixed During Review/Testing

| # | Severity | Defect | Discovery | Fix | Regression |
|---|---|---|---|---|---|
| D1 | P0/P1 | Broker/Secret launch, boundary redaction/disclosure and native usage were not wired into production | Testing preflight | `7bc2585`, `54e99e0`, `d95b5ef` | R18 suites and actual Worker native usage pass |
| D2 | P1 | Open-bridge allowlist, pre-fence cleanup, unsafe live reaper and post-terminal replay | Testing preflight | `fc0e1c2`, `7ccb2b7`, `643b7e9` | R19 boundary/replay suites pass; P0-I4 closed |
| D3 | P1 | Broker denial leaked reservation; Docker plan omitted consumed Secret | T-12 original probes | `5539c91` | `test_execution_r2_reservation_and_secret.py` passes |
| D4 | P1 | `prepare_retry` allowed timeout/disconnect/Worker loss with NULL side-effect policy | New T-12 RED test | `d5633eb` | Three ambiguous cases plus safe retry pass |
| D5 | P0/P1 | Docker CLI environment was not forwarded into the real child, dropping proxy and Secret channels | Strengthened real allowlist RED drill | `d0f02fa` | Real allow/deny/direct-bypass and real-child Secret tests pass; Secret values absent from argv |

No known open code defect remains in the executed scope. Warnings were existing Alembic deprecation and multi-threaded `fork()` deprecation warnings; they did not conceal failures and are not promoted without a demonstrated behavior impact.

## 8. Real Drill, Migration and Manual-Check Records

### 8.1 Real drill matrix

| Drill | Result | Evidence / limit |
|---|---|---|
| Managed allowlist positive path | **pass** | Internal Docker network + DNS decoy; allowed request returned proxied `ok`, exact allow hit=1 |
| Non-allowlisted/metadata/direct bypass | **pass locally** | `evil.example` proxy deny hit=1; metadata and direct `1.1.1.1:80` denied; no `*_OPEN` marker |
| Drill residue | **pass** | No test containers; only test-created internal network removed; PG container retained |
| Real child Secret channel | **pass** | Child validated expected Secret and printed only `CHANNEL_OK`; no Secret in argv/stdout/stderr |
| Default deny/read-only/minimal mounts/PID | **pass** | Existing real Docker tests in consolidated run |
| Memory/tmpfs exhaustion | **pass as local containment evidence only** | Commands terminated nonzero, host Workdir remained writable, no containers; not dedicated OOM/cgroup attribution |
| Secret disclosure response | **pass controlled** | Credential revoked, Host admission closed, Secret-free audit |
| Real two-Worker SIGKILL/late result | **pending_env** | Not executed; controlled races/reaper tests are not a substitute |
| Mixed network-loss/disk-full/hang reconciliation | **pending_env** | Not executed as an integrated infrastructure drill |
| Full file/artifact/escape/metadata decoy acceptance | **pending_env** | Requires dedicated adversarial host and production-like managed services |

### 8.2 Migration and rollback

- Actual chain from `0067_merge_heads` through the merged open-platform migrations `0068_open_application_archive` and `0069_open_app_unique_name`, then `0070_execution_fencing` and `0071_execution_credential`, succeeded on disposable PG databases.
- Deterministic historical event IDs, no historical Outbox flood, old-shaped direct-writer trigger, `tool.replay` exclusion, source-unique usage and populated-downgrade guards passed.
- 0070 small populated upgrade duration: **0.376s**. This is not a representative lock-time percentile or production-replica measurement.
- 0071 populated downgrade refused data destruction; empty downgrade succeeded.

### 8.3 M1–M3 equivalents

| Check | Automated equivalent | Result |
|---|---|---|
| M1 SSE client semantics | Strict max cursor, invalid 400, retention 409, 200+ replay, transient exclusion, terminal race, additive `_execution` | pass |
| M2 cancellation confirmation | Unconfirmed => failed, confirmed => one cancelled, live Worker reaper uses `RecoveryCoordinator`, fence before cleanup | pass |
| M3 safe diagnostic messaging | Closed categories, bounded/rate-limited redacted samples, sink failure isolation, Secret-free disclosure audit | pass |

### 8.4 Residual risks / acceptance inputs

Scope note (2026-11-18): R1–R4 are superseded as current-stage exit criteria and are out of scope for the current stage; they remain as historical context or separate high-risk-enablement/production-rollout inputs. R5 remains a separate exposure-approval item, not a stage gate. All historical status labels and numbers below are preserved unchanged.

| # | Level | Residual | Required owner/input |
|---|---|---|---|
| R1 | Out of scope (2026-11-18); formerly Hard gate | Real dedicated sandbox/file/network and two-Worker/mixed-fault matrices incomplete | Historical context only; may be revisited for production rollout; complete IT-04–08/11/22/25 and CM-02/08 if revisited |
| R2 | Out of scope (2026-11-18); formerly Hard gate; real capability separate | Phase 0 zero-diff and Phase 5 full Stage A evidence absent; real Session/Resume and production Codex routing unavailable | Historical context / high-risk enablement; IT-02/24 and real Session portions of IT-07 retain historical `pending_upstream` |
| R3 | Out of scope (2026-11-18); formerly Measurement | p50/p95, Outbox lag, recovery time and representative lock budget not measured | Historical context / performance-review owner if revisited; CM-10 remains `not_measured` |
| R4 | Out of scope (2026-11-18); formerly Verification | No PR/CI run at this target | Historical context only; CI provenance is not a stage gate |
| R5 | Separate exposure control (not a stage gate) | Independent security and SRE/operations approvals absent | Blocks enabling untrusted execution only; C12 disabled-state check passes while the switch remains false |

## 9. CI Evidence

Historical record only; out of scope for current-stage acceptance under the 2026-11-18 revision. CI provenance, final-PR-head CI runs and URLs are not stage-exit criteria, and their absence is not a blocker.

- PR: none requested/created.
- CI run: **absent**, not passed (historical record).
- Target development SHA: `d0f02fa3b173d7ebf815ea01db0ba594aa35208b`.
- Testing commit SHA: recorded in the coordination handoff after local commit.
- Overall test conclusion: code-focused scope passes and satisfies current-stage functional/security/switch acceptance; R1–R4 are out of scope for the current stage. No untrusted exposure is enabled.

## Appendix A — Local Command Output Snapshots (2026-11-17)

All pytest commands ran from `backend/`; PG cases used `TEST_DATABASE_URL=postgresql+asyncpg://agent:agent_dev@127.0.0.1:55432/phase6`.

### A-1 Quality gates

```text
uv run ruff check src tests
All checks passed!

uv run ruff format --check tests/test_execution_t12_additional.py tests/test_execution_t12_real_drills.py tests/test_execution_t12_worker_usage.py
3 files already formatted

uv run --directory backend python ../scripts/check_architecture.py
architecture gate passed
```

### A-2 Consolidated affected scope

```text
uv run pytest \
  tests/test_execution_phase6_dtos.py tests/test_execution_phase6_settings.py \
  tests/test_execution_phase6_invariants.py tests/test_execution_migration.py \
  tests/test_execution_credentials_migration.py tests/test_execution_credentials.py \
  tests/test_execution_diagnostics.py tests/test_execution_events.py \
  tests/test_execution_fencing.py tests/test_execution_outbox.py \
  tests/test_execution_recovery.py tests/test_execution_sandbox.py \
  tests/test_execution_sse.py tests/test_execution_usage.py tests/test_execution_composition.py \
  tests/test_execution_r18_allowlist_proxy.py tests/test_execution_r18_emission_redaction.py \
  tests/test_execution_r18_launch_redaction.py tests/test_execution_r18_native_usage.py \
  tests/test_execution_r18_raw_sample_leak.py tests/test_execution_r18_wiring.py \
  tests/test_execution_r19_boundary_reaper.py tests/test_execution_r19_replay_terminal.py \
  tests/test_execution_r2_reservation_and_secret.py tests/test_execution_t12_matrix.py \
  tests/test_execution_t12_real_drills.py tests/test_execution_t12_worker_usage.py \
  tests/test_execution_t12_additional.py tests/test_runtime_postgres.py \
  tests/agent_execution/test_codex_host_integration.py \
  tests/agent_execution/test_host_stdin_delivery.py -q

........................................................................ [ 27%]
........................................................................ [ 55%]
........................................................................ [ 83%]
............................................                             [100%]
260 passed, 37 warnings in 36.90s
```

### A-3 Post-format additions

```text
uv run pytest tests/test_execution_t12_real_drills.py \
  tests/test_execution_t12_worker_usage.py tests/test_execution_t12_additional.py -q
.....                                                                    [100%]
5 passed, 1 warning in 1.67s
```

### A-4 Resume-equivalent reauthorization

```text
uv run pytest tests/test_execution_t12_resume_grant.py -q
.                                                                        [100%]
1 passed in 0.52s
```

### A-5 Migration/rollback drill

```text
uv run pytest \
  tests/test_execution_migration.py::test_0070_chain_backfill_outbox_usage_and_data_preserving_downgrade \
  tests/test_execution_credentials_migration.py::test_0071_chain_versions_grants_and_data_preserving_downgrade \
  tests/test_execution_credentials_migration.py::test_0071_empty_downgrade_succeeds -q -s

0070 populated upgrade duration: 0.376s
3 passed, 1 warning in 6.61s
```

## 10. Post-report CI compatibility and R-20 renumbering

PR #142's first CI run exposed baseline-suite incompatibilities, not Phase 6 code failures. Commit `fc3245e` restored the legacy call shapes (omitting redundant `cleanup_confirmed=True`/empty usage), extended the replay port with optional Fencing evidence, and updated baseline tests for the reviewed additive contracts. The `integration` branch had also merged its own `0068`/`0069`, so the PR merge result had two Alembic heads; the Phase 6 migrations were renumbered to `0070_execution_fencing` / `0071_execution_credential` after `0069_open_app_unique_name` (08 R-20), with tests and docs synchronized.

Re-verification after the merge and renumbering, on a fresh disposable PostgreSQL database migrated to head `0071_execution_credential`:

```text
unit lane:            2323 passed, 6 skipped
affected postgres:     418 passed, 1 skipped (execution/runtime/replay/open-platform/Codex-Host scope)
migration evidence:      3 passed; 0070 populated upgrade 0.376s
ruff check / architecture gate: passed
```

All previously recorded row verdicts are unchanged; no new failed code row exists. The `pending_env`, `pending_upstream`, `not_measured` and CI items above retain their historical status but are out of scope for current-stage acceptance under the 2026-11-18 revision; this section is retained as historical context, not as exit evidence.
