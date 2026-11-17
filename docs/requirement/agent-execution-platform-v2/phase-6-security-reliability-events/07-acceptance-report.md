# Phase 6 · Security, Reliability, and Event Governance — Acceptance Report

> Status: Executed — **NOT PASSED**; code-focused acceptance evidence is ready within its stated limits, but required real-environment and upstream hard gates remain open
> Created: 2026-11-17
> Basis: `05-acceptance-plan.en.md` (A1–A16, M1–M3, C1–C12 and §6 decision rules), `06-test-report.md` (57 individual P6 rows and real-drill records), `08-implementation-breakdown.en.md` (R-5/R-6/R-9/R-17–R-19)
> Acceptance owner / executor: Phase 6 acceptance subagent (the same lightweight role; no fabricated product, QA, business, security, SRE or real-user approval)
> Target evidence SHA: `3a9bb52f2907afe24aa256f3baa86cb088b0679f` (test report and test additions; production target parent `d0f02fa3b173d7ebf815ea01db0ba594aa35208b`)

## 1. Acceptance Scope and Responsibility

This decision covers the Phase 6 Execution credential/Broker and redaction boundaries, strong-sandbox and managed-egress implementation, Fencing/recovery/retry, durable events/Outbox/SSE, native and terminal usage, parser diagnostics, migrations 0070/0071, composition and secure defaults. Automated results are reused from `06`; the acceptance subagent did not rerun the 260-test consolidated scope, the later Resume-equivalent test, or full suites.

This is not approval to enable untrusted execution, production Codex routing, App-Server Stage B, or a production release. Controlled adapters, local Docker, small disposable PostgreSQL databases and deterministic fault hooks prove their exercised boundaries only. They do not replace the required dedicated adversarial host, real two-Worker/mixed-infrastructure faults, representative production-data replica, Phase 0/5 upstream evidence or final CI.

**Precondition review:** the code-focused scope is green: 260 consolidated tests plus one distinct controlled Resume-equivalent test passed; the report contains exactly 22 UT + 25 IT + 10 CM rows, with 44 pass, 10 `pending_env`, 2 `pending_upstream`, 1 `not_measured`, and no known failed code row. D1–D5 are fixed and no known open code defect remains. However, the overall Phase 6 test gate is explicitly **NOT PASSED**, final-target CI is absent, and the hard gates below remain open. These are not P2/P3 conditional-pass waivers.

Evidence index: [06 execution overview](06-test-report.md#2-execution-overview), [06 UT rows](06-test-report.md#3-unit-tests-p6-ut--individual-results), [06 IT rows](06-test-report.md#4-integration-tests-p6-it--individual-results), [06 CM rows](06-test-report.md#5-general-checks-p6-cm--individual-results), [06 real drills/migrations/manual equivalents](06-test-report.md#8-real-drill-migration-and-manual-check-records), and [06 CI boundary](06-test-report.md#9-ci-evidence).

## 2. Acceptance Environment

| Environment | Configuration | Evidence carried and boundary |
|---|---|---|
| Local backend toolchain | macOS Darwin 27.0.0 arm64; Python 3.12.13 through `uv` | Reused ruff, architecture, unit and controlled integration evidence from 06 §§2–5 and Appendix A |
| PostgreSQL | `nexusdesk-phase6-pg`, PostgreSQL 17.11/pgvector, `127.0.0.1:55432/phase6`, head `0071_execution_credential`; uniquely named disposable migration databases | Real PG Fencing, event/Outbox, usage, SSE, migration and rollback evidence; not a representative production-data replica |
| Local Docker | Docker 29.9.2, Linux/aarch64, `alpine:latest` arm64; test-created internal networks and auto-removed containers | Real default-deny/read-only/PID, local memory/tmpfs containment, managed-proxy allow/deny/direct-bypass and child Secret-channel drills; not the complete dedicated adversarial environment |
| Controlled engines/adapters | Existing DemoModel, controlled Codex Host and controlled Resume-equivalent seams | Deterministic behavior only; no production Codex routing or real Stage B Session/Resume claim |
| Dedicated strong-sandbox/file/network and multi-Worker fault environment | Disposable production-like Linux host, managed services/decoys, at least two Workers and representative infrastructure faults | **Unavailable / `pending_env`** for A4–A9, A16 and dependent C gates |
| Representative migration/performance environment | Populated production-data replica, fixed load/fault sets and lock/latency measurement | **Unavailable / `pending_env` / `not_measured`** |
| Upstream Phase 0/5 and Stage B | Phase 0 current-target zero diff, Phase 5 full Stage A and real Session/Resume | **`pending_upstream`**; direct-continue and controlled fakes are not substitutes |
| CI | No push, PR or CI run requested | **Absent**, not passed; final backend/frontend evidence remains pending |

The secure disabled-state boundary was verified in the test evidence: `execution_untrusted_tenants_enabled=false`, `execution_sandbox_required=true`, `execution_network_default_deny=true`, and `execution_event_cleanup_enabled=false`. No independent security or SRE/operations approval is claimed.

## 3. Functional Acceptance Records (A1–A16)

| # | Verdict | Execution record and actual result | Evidence |
|---|---|---|---|
| A1 | **pass** | Credential ciphertext/AAD, tenant/Engine/Workspace/version binding, rotation, revocation, missing-key and admin-route behavior fail closed with Secret-free controlled audit/public views. | [06 §3 UT-01 and §4 IT-01](06-test-report.md): `test_execution_credentials.py` lifecycle/binding/route tests; `test_execution_credentials_migration.py`; CM-03/05 |
| A2 | **pending_upstream** | Grant Run/Engine/Workspace/scope/TTL, expiry/replay/cross-Execution denial and controlled new-Run reauthorization pass. Real Session Resume does not exist, so the actual Resume substep cannot pass. | [06 §3 UT-02/03 and §4 IT-02](06-test-report.md): `test_execution_t12_resume_grant.py::test_resume_equivalent_new_run_requires_and_receives_new_grant`; 08 R-9 |
| A3 | **pass** | Registered values, patterns, structured fields, raw samples, launch/output/SSE/Outbox/diagnostic/artifact boundaries redact or fail closed. A real Docker child received the controlled Secret without argv/stdout/stderr disclosure; controlled disclosure revoked the credential and closed Host admission with Secret-free audit. | [06 §4 IT-03 and §8.1](06-test-report.md#81-real-drill-matrix): R18 launch/emission/wiring suites; `test_execution_t12_real_drills.py::test_real_docker_child_receives_controlled_secret_without_echo`; CM-03 |
| A4 | **pending_env** | Local real Docker default-deny/read-only/minimal-mount/PID and nonzero memory/tmpfs exhaustion containment pass, with no residual containers. Dedicated-host escape, privilege, full cgroup/OOM attribution and no-sandbox acceptance matrix is incomplete. | [06 §4 IT-04 and §8.1](06-test-report.md#81-real-drill-matrix): `test_execution_sandbox.py`; `test_execution_t12_real_drills.py::test_real_docker_memory_and_tmpfs_exhaustion_do_not_affect_host` |
| A5 | **pending_env** | Real local internal-network managed proxy allowed exactly the authorized request and denied evil/metadata/direct-IP bypass, with proxy hits and residue checked. Production-like managed DNS-rebinding, redirect, metadata-decoy and comprehensive proxy-bypass acceptance remains open. | [06 §4 IT-05 and §8.1](06-test-report.md#81-real-drill-matrix): `test_execution_r18_allowlist_proxy.py::test_allowlist_proxy_permits_allowed_and_denies_metadata`; UT-06 |
| A6 | **pending_env** | Controlled traversal/link/TOCTOU and minimal-mount evidence passes. Real cross-tenant, device, malicious-artifact export and cleanup-residue attack acceptance remains incomplete. | [06 §3 UT-07 and §4 IT-06](06-test-report.md): Phase 4 Workdir cases and Docker mount tests; 06 §8.1 residual drill row |
| A7 | **pending_env** (Session substep also **pending_upstream**) | Available state/event/usage/replay/process/Workdir/resource stale-write surfaces and concurrent takeover races show zero effective controlled stale writes. Real two-Worker takeover is not executed, and real Session writes do not exist. | [06 §3 UT-08/09, §4 IT-07/09](06-test-report.md): `test_execution_fencing.py`, `test_execution_events.py`, `test_execution_usage.py`, `test_execution_r19_replay_terminal.py`, `test_execution_t12_matrix.py`; CM-06 |
| A8 | **pending_env** | Controlled live-reaper, fencing, takeover/heartbeat/finish race and late-result regressions preserve one effective terminal. Actual Worker SIGKILL, heartbeat stall, lease expiry and old-Worker late-success process drill is not executed. | [06 §4 IT-08/09 and §8.1](06-test-report.md): `test_execution_r19_boundary_reaper.py`, reused `test_runtime_postgres.py::test_lost_worker_is_failed_and_cannot_publish_late_result` |
| A9 | **pending_env** | Unconfirmed cancellation becomes failed rather than cancelled; confirmed normal/forced cleanup produces one terminal, with independent quota release. Real Worker-loss orphan/FD/mount/reservation and integrated mixed-fault proof remains open. | [06 §3 UT-11/12 and §4 IT-10/11/25](06-test-report.md): recovery and Phase 4 Supervisor cases; CM-08; M2 equivalent in §8.3 |
| A10 | **pass** | Only proven safe pre-launch/idempotent cases retry; timeout, disconnect and Worker loss with ambiguous side effects are refused. Safe attempts correlate, external-write manual retry requires idempotency, and Outbox retry retains stable identity without duplicate controlled effects. | [06 §3 UT-13 and §4 IT-12/13/17](06-test-report.md): `test_execution_recovery.py`, `test_execution_t12_matrix.py`, `test_execution_outbox.py`; D4 regression |
| A11 | **pass** | v1/additive metadata and unknown-version behavior remain explicit; concurrent durable sequence allocation is monotonic and producer dedup consumes no extra sequence. Small populated 0070 backfill preserves historical IDs/order. | [06 §3 UT-14/15 and §4 IT-14](06-test-report.md): event DTO tests; `test_execution_t12_matrix.py::test_concurrent_sequence_and_producer_dedup`; `test_execution_migration.py` |
| A12 | **pass** | Duplicate native delivery yields one event/sequence/Outbox/source-unique usage. Pre-commit hook failure rolls back state/event/Outbox/usage; post-commit and after-enqueue failures recover pending publication with idempotent identity and no partial terminal state. | [06 §3 UT-15/16 and §4 IT-15/16/17](06-test-report.md): `test_execution_t12_matrix.py` commit/publication fault cases; `test_execution_r18_native_usage.py`; CM-07 |
| A13 | **pass** | Strict cursor maximum, invalid 400, retention 409, 205 native events plus lifecycle replay, transient exclusion, reconnect and subscribe/finish terminal race all pass. SSE retains existing fields/`id=seq` and adds only reserved `_execution` metadata. | [06 §3 UT-17 and §4 IT-18/19](06-test-report.md): `test_execution_sse.py`, `test_execution_t12_matrix.py::test_sse_subscribe_terminal_race_delivers_final_event`; M1 equivalent in §8.3 |
| A14 | **pass** | Source uniqueness, old-epoch denial, corrections, explicit unknown and rebuildable aggregates pass. The actual Worker path persists native usage 7 and terminal usage 8 separately without recounting. | [06 §3 UT-18/19 and §4 IT-20](06-test-report.md): `test_execution_usage.py`; `test_execution_t12_worker_usage.py::test_worker_persists_adapter_native_usage_and_terminal_usage` |
| A15 | **pass** | Malformed/unknown/oversized/critical diagnostics are classified, bounded, correlated, redacted and rate-limited without recursive events. Twenty continuous failures emitted three diagnostics and suppressed seventeen; disclosure audit was Secret-free. | [06 §3 UT-20 and §4 IT-21](06-test-report.md): `test_execution_diagnostics.py`, `test_execution_r18_raw_sample_leak.py`, `test_execution_t12_additional.py`; M3 equivalent in §8.3 |
| A16 | **pending_upstream** (representative replica and CI also **pending_env**) | Actual 0067→0068→0069 open-platform→0070→0071 small populated chains, deterministic backfill, protected populated downgrade, empty 0071 downgrade, composition/settings and affected React/Codex/API/SSE regressions pass. Representative replica lock/rollout evidence, Phase 0 current-target zero diff, Phase 5 full Stage A and final CI are absent. Production Codex routing is not claimed. | [06 §4 IT-22/23/24, §8.2 and §9](06-test-report.md#82-migration-and-rollback): migration chain tests and consolidated affected scope; CM-01/02/04/09/10; 08 R-5/R-6 |

### Key Manual Check Results

No separate real-user UAT or developer-as-user claim is made. The three planned checks have automated equivalents in [06 §8.3](06-test-report.md#83-m1m3-equivalents):

| # | Verdict | Evidence |
|---|---|---|
| M1 — SSE client semantics | **pass by automated equivalent** | Strict max cursor, invalid 400, retention 409, 200+ replay, transient exclusion, terminal race and additive-only `_execution`; IT-18/19 and CM-07 |
| M2 — cancellation confirmation | **pass by automated equivalent for covered state machine** | Unconfirmed means failed, confirmed means one cancelled, live Worker reaper uses `RecoveryCoordinator` and fences before cleanup; UT-11/12 and IT-10/11. Real mixed-fault A9 remains `pending_env` |
| M3 — safe diagnostic messaging | **pass by automated equivalent** | Closed categories, bounded/rate-limited redacted samples, sink-failure isolation and Secret-free disclosure audit; UT-20, IT-21 and CM-03 |

## 4. Security, Data, Release Hard Gates and Necessary Measurements

| # | Verdict | Data / evidence and boundary |
|---|---|---|
| C1 | **pass** | A1/A3, IT-01/03 and CM-03: controlled public DB/API/log/event/SSE/diagnostic/artifact/audit surfaces and real child output contain no plaintext canary or grant Token. |
| C2 | **pending_env** | A4/IT-04 and CM-04 prove fail-closed policy and local containment, but the dedicated strong-sandbox escape/resource acceptance matrix is incomplete. No host fallback is authorized. |
| C3 | **pending_env** | A5/A6 and IT-05/06 have real local proxy/default-deny and controlled file evidence; full managed DNS/metadata/proxy and cross-tenant/file/artifact attacks remain open. |
| C4 | **pending_env** | A7/A8, IT-07–09 and CM-06 prove available controlled write surfaces and zero stale controlled commits; real two-Worker evidence and real Session coverage remain absent. |
| C5 | **pending_env** | A8/A9, IT-08–11/25 and CM-08 preserve controlled terminal/cancellation semantics, but actual Worker-loss/mixed-fault cleanup and final-event/resource consistency are incomplete. |
| C6 | **pending_env** | A10/A14 prove safe retry and source-unique accounting; A9/IT-25/CM-08 still require real orphan/process/FD/mount/volume/grant/reservation and mixed-fault reconciliation before the entire gate can pass. |
| C7 | **pass** | A11/A12, IT-14–17 and CM-07: pre/post-commit and publication fault tests establish Event Store source-of-truth, atomic state/event/Outbox/required usage and recoverable idempotent publication in the exercised scope. |
| C8 | **pass** | A13, IT-18/19 and CM-07: multipage replay, explicit 400/409, event identity/dedup, compatible `id=seq`, transient exclusion and terminal/final-event agreement pass. |
| C9 | **pass** | A14/A15, UT-18–20, IT-20/21 and CM-03/09: bounded/redacted/rate-limited diagnostics, source idempotency, corrections, unknown handling and actual Worker native+terminal usage pass. |
| C10 | **pending_env** | CM-01 passes single-head/revision/history protection; small populated 0070/0071 upgrade/backfill/data-preserving rollback passes. CM-02 and IT-22 still require representative production-replica online lock/backfill evidence. |
| C11 | **pending_upstream** | A16/IT-24 affected regressions pass and P0-I4 is closed by post-terminal/expired-lease replay denial. Phase 0 current-target zero diff, full Phase 5 Stage A and final CI remain absent; production Codex routing remains React-only/out of scope. |
| C12 | **pass — disabled-state gate only** | UT-21/22 and CM-04 verify untrusted=false, sandbox/default-deny=true and no security-degradation switch. This does not approve exposure. Independent security and SRE/operations approvals are absent and remain mandatory before enablement. |

### Engineering Measurements

| Measurement | Verdict | Record |
|---|---|---|
| Small populated 0070 migration observation | **measured, limited scope** | 0.376 seconds on the disposable local PG fixture; three migration/rollback tests passed in 6.61 seconds. This is not a representative lock percentile or production budget result. Evidence: [06 §8.2 / Appendix A-5](06-test-report.md#a-5-migrationrollback-drill). |
| Execution p50/p95 | **not_measured** | No representative fixed-load sample or accepted Phase 0 baseline exists. |
| Outbox lag | **not_measured** | Requires representative publisher/load/fault environment. |
| Recovery time | **not_measured** | Requires real multi-Worker/fault environment and sample definition. |
| Representative migration-lock duration | **not_measured / pending_env** | Requires a populated production-data replica; the 0.376-second local observation cannot substitute. |
| Final CI | **absent** | No push/PR/run exists at the target; no full-suite or frontend CI pass is claimed. |

## 5. Residual List

| # | Level | Residual and acceptance impact | Owner / dependency | Deadline |
|---|---|---|---|---|
| L1 | Hard gate / `pending_env` | Dedicated production-like sandbox escape/resource, managed network/DNS/metadata/proxy, file/device/cross-tenant/artifact and residue matrices are incomplete; blocks A4–A6 and C2/C3. | Coordinator to supply the disposable Linux/managed-service environment; testing to execute IT-04–06 and associated adversarial rows | Before any full Phase 6 pass; no conditional waiver |
| L2 | Hard gate / `pending_env` | Real two-Worker SIGKILL/heartbeat/late-result, cancellation/Worker-loss and mixed network-loss/disk-full/hang reconciliation is incomplete; blocks A7–A9 and C4–C6 and prevents full resource/quota proof under C6. | Coordinator/environment owner plus testing; complete IT-07/08/11/25 and CM-08 | Before any full Phase 6 pass; no conditional waiver |
| L3 | Hard gate / `pending_env` | Representative populated-replica online 0070/0071 backfill/lock/rollout/rollback evidence is absent; blocks A16/C10 and CM-02. | Coordinator/database environment owner plus testing | Before release/full Phase 6 acceptance |
| L4 | Hard gate / `pending_upstream` | Phase 0 current-target zero behavioral diff and Phase 5 full Stage A evidence remain absent; blocks A16/C11. Existing historical Phase 0 local evidence and scoped Phase 5 R18 readiness cannot be relabelled as these prerequisites. | Phase 0 and Phase 5 upstream acceptance/environment owners; coordinator to supply applicable evidence | Before full Phase 6 acceptance; direct-continue is not a substitute |
| L5 | Upstream capability / `pending_upstream` | Real Stage B Session/Resume and Session writes do not exist; blocks full A2 and the real Session portions of A7/C4. Production Codex routing/trusted-target/publish-path also remains unavailable and cannot be claimed by controlled tests. | Future Phase 5B Session owner; separate Codex routing/deployment owner for any production-enablement claim | Before the corresponding real-capability acceptance; not a Phase 6 scope expansion |
| L6 | Measurement / `not_measured` | p50/p95, Outbox lag, recovery time and representative migration-lock budget are unmeasured. | Phase 0 baseline/performance owner plus representative-environment owner | Before performance/release-budget approval; never infer improvement from the local 0.376-second observation |
| L7 | Verification / CI absent | No final-target full backend/frontend CI evidence exists. | Coordinator/CI after an explicitly requested push/PR | Before final merge/release evidence is claimed |
| L8 | Exposure-only approval dependency | Independent security and SRE/operations approvals are absent. This does not change C12's passing disabled-state verdict, but unconditionally blocks untrusted exposure. | Independently named security and SRE/operations approvers; not any of the four subagents | Before any request to set `execution_untrusted_tenants_enabled=true`; approvals must bind target SHA, tenant scope, batch plan, evidence and revocation conditions |

No known open code defect remains in the executed scope. L1–L8 are evidence/environment/upstream dependencies, not newly discovered code failures and not P2/P3 waivers.

### Low-Priority Follow-Up Candidates for Coordinator Review

No new Phase 6 main-flow issue is recommended from the executed evidence. Existing genuinely low-priority upstream candidates may be reviewed for later issue creation: Phase 5 D23/D24/D25/D27 (documentation/fixture/count drift), I20 (future `model_dump`→validate prompt-loss semantics) and I21 (test-comment traceability labels), plus Phase 0 P0-I3/P0-I5/P0-A3 (comment/format/citation cleanup). D26 must not be treated as unconditionally low priority if a new direct caller bypasses the current prevalidated-bytes boundary. No issues were created.

## 6. Conclusion and Single Acceptance Record

**Decision: NOT PASSED.** This is a code-focused readiness result, not a full or conditional Phase 6 pass.

- A verdicts: **8 pass, 6 `pending_env`, 2 `pending_upstream`, 0 fail**.
- C verdicts: **5 pass, 6 `pending_env`, 1 `pending_upstream`, 0 fail**.
- Combined A/C: **13 pass, 12 `pending_env`, 3 `pending_upstream`, 0 fail**; engineering measurements separately include `not_measured` items and CI is absent.
- Passing code-focused items: A1, A3, A10–A15 and C1, C7–C9, C12 (disabled state only).
- Overall acceptance is blocked by dedicated real-environment evidence (L1–L3), upstream prerequisites/capabilities (L4–L5), measurements and final CI (L6–L7). Under 05 §6, these hard-gate and real-environment gaps cannot be converted into a conditional P2/P3 pass.
- Untrusted execution remains false. This decision grants no production readiness, Stage B unlock, production Codex enablement or independent security/SRE approval.

| Acceptance owner | Executor | Date | Target SHA | Decision | Evidence / residual confirmation |
|---|---|---|---|---|---|
| Phase 6 acceptance subagent | Phase 6 acceptance subagent (same role; evidence reuse and read-only consistency checks only) | 2026-11-17 | `3a9bb52f2907afe24aa256f3baa86cb088b0679f` | **NOT PASSED — code-focused evidence ready; overall hard gates open** | `06-test-report.md` §§2–9 and this report; L1–L8 acknowledged as unresolved dependencies, not waived P2/P3 residuals |

> High-risk independent approval exception: none sought, issued or claimed. Untrusted multi-tenant execution stays disabled until full phase acceptance and separate independent security and SRE/operations approvals are complete. The acceptance owner cannot self-issue or waive those approvals.

## 7. Revision-Round Reverification Record

No acceptance-triggered production or test revision was made. Acceptance reused the final testing evidence at `3a9bb52f2907afe24aa256f3baa86cb088b0679f`; earlier development/testing rework rounds and D1–D5 regressions are recorded in `06` and the coordination ledger. No additional A/C reverification was executed and no earlier test verdict was changed.

## 8. Post-report CI compatibility and R-20 renumbering

PR #142's first CI run failed on baseline-suite compatibility, not on Phase 6 functionality. Commit `fc3245e` restored the legacy call shapes (omitting redundant `cleanup_confirmed=True`/empty usage), extended the replay port with optional Fencing evidence, and updated baseline tests for the reviewed additive contracts. `integration` had also merged its own `0068`/`0069`, so the PR merge result had two Alembic heads; the Phase 6 migrations were renumbered to `0070_execution_fencing` / `0071_execution_credential` after `0069_open_app_unique_name` (08 R-20), with tests and docs synchronized.

Re-verification on a fresh disposable PostgreSQL database migrated to head `0071_execution_credential`: unit lane 2323 passed / 6 skipped; affected postgres scope 418 passed / 1 skipped; migration evidence 3 passed with a 0.376s populated 0070 upgrade; ruff and architecture gates passed. Every earlier A/C and test-row verdict is unchanged, no new failed code row exists, and the L1–L8 items remain open for the same reasons. The decision stays **NOT PASSED**.
