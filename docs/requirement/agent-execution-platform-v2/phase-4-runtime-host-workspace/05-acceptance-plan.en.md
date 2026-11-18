# Phase 4 · Runtime Host, Process Supervision, and Workspace — Acceptance Plan

> Status: Pending execution (run before this phase goes live; no acceptance results currently exist)
> Created: 2026-11-02
> Revised: 2026-11-11 (lightweight small-team acceptance: reuse automated evidence; remove standalone UAT, duplicate metrics, and multi-role sign-off)
> Revised: 2026-11-14 (08 R-1: planned migration renumbered `0054`→`0059_execution_runtime_host`, actual predecessor `0058_agent_execution_metadata`)
> Revised: 2026-11-14 (coordination rulings 08 R-11/R-12: A6 evidence includes same-Run prepare convergence; A9 evidence includes persisted over-quota observations with structured excess alerts, not warn-only records)
> Revised: 2026-11-17 (aligned to the minimal-core-team acceptance standard: single acceptance owner, phase acceptance separated from high-risk capability enablement; technical criteria and hard gates unchanged)
> Revised: 2026-11-18 (scope-limited acceptance revision: performance/capacity/p50/p95/startup latency/event lag/recovery time/migration-lock budget, matched pairs and sample counts, CI provenance and final-PR-head CI runs/URLs, real or authorized historical samples, and multi-sample/large-sample data-volume requirements are no longer stage-acceptance gates and remain only as historical context or explicit out-of-scope notes; retained gates are functional correctness, Runtime Host/Workspace switch completeness, tenant isolation, Secret/credential handling, process/resource cleanup, data integrity and migration, terminal-state semantics, no P0/P1, and a single acceptance-owner record; high-risk enablement stays a separate approval. See §6.1)
> Basis: `01-business-goals.md` (G1–G5, success metrics), `02-requirements.md` (AC-1–AC-12); test execution follows `04-test-plan.md`

## 1. Acceptance Scope and Responsibility

Confirm every AC and retain evidence for cleanup, isolation, resource, and observability criteria. Untrusted execution remains disabled; out-of-bound file operations, mistaken kills, silently ignored resources, and non-drainable rollback are unacceptable. By default, the acceptance owner organizes and records the decision while the executor prepares isolated environments, performs supplementary checks, and organizes evidence; one person may hold both responsibilities. Do not invent independent product, QA, business, security, or operations roles, create no multi-role sign-off sheet, and run no independent UAT round. Developer self-verification proves conformance to this document, not real-user acceptance or an independent security audit. Phase acceptance does not constitute authorization to enable high-risk capabilities such as untrusted multi-tenant code execution or production engine routing; such enablement requires a separate independent security and operations approval record.

## 2. Acceptance Environments and Prerequisites

| Environment | Purpose |
|---|---|
| Production-like Linux + dedicated PostgreSQL | Two Adapters, real processes, Run/process/Workdir states, concurrency, and failure acceptance |
| Dedicated Linux cgroup v2 resource environment | CPU/memory/PID/disk/time/output boundaries and the full support matrix |
| Isolated filesystem and mount namespace | Traversal, symlinks/hardlinks/mount points, races, quotas, and safe cleanup using test sentinels only |
| Restartable Worker/container + dedicated execution volume | Orphan recovery, PID-reuse decisions, stable host_id, stop/drain, and rollback |
| macOS development subset/unsupported-platform comparison | Approximate rlimit/supervisor capabilities and required=true fail-closed behavior; does not replace full Linux acceptance |
| quickstart and production deployment-check environments | Default-off, legacy React, volume ownership, stop timeout, settings, and deployment rollback |
| Disposable production-like DB copy | Online migration, concurrent reads/writes, application rollback; downgrade only on the disposable DB |

**Prerequisites**: Phase 0 baseline and Phase 1–3 acceptance are complete; all applicable `04-test-plan.md` cases pass with no P0/P1; actual migration head/down_revision was revalidated during implementation. Use at least two dedicated tenants, independent scopes, and built-in trusted test targets, with no production customer data or real model keys. (Scope-limited revision 2026-11-18: the former "full acceptance has Linux/cgroup/mount/container environments" prerequisite and the "missing environment blocks its corresponding enablement promise" clause are no longer stage-acceptance gates, see §6.1; a missing environment must still be labelled `pending_env` honestly and never skipped or reported as a pass.)

## 3. Functional Acceptance Checklist (AC-1–AC-12)

| # | Criterion | Acceptance steps | Pass criteria | Traceability |
|---|---|---|---|---|
| A1 | AC-1 | Start/stop processes through the same Host using two different test Adapters; inspect dependencies, internal handles, and public APIs | Reuse without Host/Worker changes; Adapters have no direct spawn/signal/resource branches; public responses expose no PID/PGID/full path | FR-1; G1; US-1, US-2 |
| A2 | AC-2 | Run a normal process with bounded I/O, then inject spawn/pipe/registration failures and stdout/stderr floods | Normal result is correct; Worker is not blocked; failures leave no residue; output excess terminates the group, with no secrets in logs/DB | FR-2; G1, G2; US-1, US-5 |
| A3 | AC-3 | Spawn nested TERM-ignoring descendants, cancel, repeat cancellation, and submit late success | KILL reaches the whole group after grace and descendants actually exit; Run remains cancelled; cleanup is idempotent and late results are ineffective | FR-3; G2; US-2, US-5 |
| A4 | AC-4 | Trigger Run deadline, process wall timeout, and their races with cancellation separately | Earlier deadline wins; group/resources release; terminal state/reason are stable, with no duplicate terminal state, zombie, or leak | FR-3; G2; US-2, US-5 |
| A5 | AC-5 | Kill Worker/restart its container with live processes; then construct PID reuse, identity mismatch/absence, and DB outage | Matching orphans are recovered; mismatch kills are zero; DB failure causes no blind scan/kill; manual remediation/alerts are explicit and no Session replays | FR-4; G2, G5; US-3, US-5 |
| A6 | AC-6 | Concurrently create cross-tenant Workdirs; verify retention, restart recovery, cleanup failure, and retry after completion/failure/cancellation | Directories are unique with correct permissions; states/ownership recover; retention is correct; cleanup is idempotent, failures are visible/retryable, and Tombstones remain; re-preparing an interrupted same-Run record converges to `ready` or an explicit fail-closed refusal, never a returned `preparing` (08 R-11) | FR-5; G3, G5; US-3, US-4 |
| A7 | AC-7 | Submit absolute paths, `..`, encoding/separator bypasses, cross-tenant paths, and unapproved mounts through raw inputs | All reject before touching external resources; valid relative paths work; public APIs have no host-path entry | FR-6; G3; US-4, US-5 |
| A8 | AC-8 | In an isolated namespace, create symlinks/hardlinks/mount points to external sentinels and post-check replacement races, then read/write/clean | Zero successful external reads/writes/deletes; sentinels remain unchanged; uncertain scope stops with an alert and no host-level recursive deletion | FR-6; G3; US-4, US-5 |
| A9 | AC-9 | Exceed CPU/memory/PID/Workdir total and per-file/wall-time/output bounds individually under the full matrix, then start on an unsupported environment | Supported excess rejects/terminates within specified time and releases resources; missing required capabilities reject start; zero silent ignores or adjacent-Execution impact; over-quota disk observations are persisted in `size_bytes` with a structured excess alert rather than warn-only over a stale record (08 R-12) | FR-7; G4; US-5, US-6 |
| A10 | AC-10 | Replace the Sandbox test Provider and attempt arbitrary commands, uploaded code, untrusted multi-tenant execution, and configuration bypasses | Replace without Adapter/Host contract changes; 100% of untrusted-execution entries reject; Local Provider makes no strong-sandbox/network/credential promise | FR-8; G4, G5; US-6 |
| A11 | AC-11 | Observe normal, crash, orphan, cleanup_failed, resource-pressure, and stalled-reconcile states, then attempt public reads of internal fields | Metrics/logs/alerts cover every state and correlate Run/host; secrets, PID/PGID, and full paths stay out of public surfaces and evidence | FR-9; G5; US-3, US-7 |
| A12 | AC-12 | Upgrade `0059_execution_runtime_host` from the actual predecessor `0058_agent_execution_metadata`, verify default-off/legacy React, then drill stop admission → drain → verify → disable → application rollback | Only necessary tables/indexes are added; React has no regression; rollback leaves zero active orphans, retains both tables/audit, and needs no downgrade; cleanup_failed blocks full rollback | FR-4, FR-5, FR-10; G1, G5; US-2, US-3, US-7 |

Record for every scenario: executor, date, environment/support matrix, target commit, prerequisite data, actual operations, expected/actual result, decision, and process/resource/DB/filesystem/log evidence links. Failures or missing environments cannot be rewritten as passes; destructive evidence references only isolated sentinels and dedicated volumes.

**Evidence reuse**: A1–A12 directly reference the corresponding UT/IT/CM, CI, process, resource, database, and filesystem evidence in `06-test-report.md` wherever possible instead of manually repeating the full suite. Cleanup, orphan identification, path isolation, resource limits, and observability coverage are assessed directly from A/C criteria without a second business-metric acceptance round.

## 4. Key Manual Checks

Use these only to supplement operational usability that automation does not fully cover. Record executor, target SHA, result, and evidence for each; do not create Adapter, SRE, or tenant-representative roles.

| # | Check | Pass criterion |
|---|---|---|
| M1 | Review Host/Adapter responsibilities and the support matrix in the actual deployment guide | Responsibilities are clear; full Linux capabilities, macOS development approximations, and unsupported items are distinguishable, and Local Provider is not presented as an untrusted-code sandbox |
| M2 | Inspect normal and `cleanup_failed` samples and perform safe retry/manual remediation | Run terminal state, process exit, resource release, and Workdir deletion are distinguishable; public diagnostics expose no host path, PID, or secret, and internal evidence access is controlled |
| M3 | Follow the rollback runbook through stop admission, drain, verification, disablement, and rollback | The runbook is executable and verifies zero active processes first; `cleanup_failed` explicitly blocks rollback rather than forcing table cleanup |

## 5. Security, Data, and Release Hard Gates

| # | Check | Decision | Traceability |
|---|---|---|---|
| C1 | Host is decoupled from Adapters/Worker, and public APIs/handles expose no PID/PGID, host path, or environment | Must pass | AC-1; G1; FR-1 |
| C2 | Managed processes and descendants have 100% cleanup across the specified normal, cancellation, timeout, crash, and restart scenarios; cancellation/timeout stops the whole group within configured grace + kill timeout plus 2s observation allowance; late results cannot overwrite terminal state; failure to stop alerts and is never reported as successful cleanup | Veto; verify each case with monotonic timing and OS evidence | AC-2–AC-4; G2; FR-2, FR-3 |
| C3 | Recovery verifies host/boot/start token/digest together; zero PID-reuse kills and no blind kills on DB failure | Veto | AC-5; G2; FR-4 |
| C4 | Tenant/scope ownership is rechecked, with zero successful external reads/writes/deletes across traversal/encoding/link/mount/race cases | Veto | AC-6–AC-8; G3; FR-5, FR-6 |
| C5 | Missing required resource capabilities reject start, support matrix is truthful, and no limit is silently ignored, raised, or replaced by host totals | Veto | AC-9; G4; FR-7 |
| C6 | Arbitrary commands, uploaded code, and untrusted multi-tenant execution always reject; Local Provider is not advertised as a strong sandbox | Veto | AC-10; G4; FR-8 |
| C7 | Logs, events, DB metadata, public APIs, and acceptance evidence contain no tokens, keys, secret argv/env, or full host paths | Veto | AC-2, AC-11; G5; FR-2, FR-9 |
| C8 | Run, process, resource, and Workdir states are recorded separately; cleanup is idempotent, failures retryable, and Tombstones/audit retained | Must pass | AC-3–AC-6; G2, G3; FR-3–FR-5 |
| C9 | Active/orphan/failure/resource/disk/recovery batches have structured observability and alerts without uncontrolled high-cardinality labels | Must pass | AC-11; G5; FR-9 |
| C10 | `0059_execution_runtime_host` predecessor (`0058_agent_execution_metadata`) is revalidated before implementation, only necessary tables/indexes are added, history is unchanged, and production rollback does not downgrade | Must pass | AC-12; G5; FR-4, FR-5, FR-10 |
| C11 | New Host is off by default, React/Worker/SSE matches the Phase 0 baseline, and Phase 3 behavior does not regress | Veto | AC-12; G1, G5; FR-10 |
| C12 | Rollback stops admission and drains first, then rolls back the application at zero active; cleanup_failed blocks full rollback and records are not deleted | Veto | AC-12; G5; FR-10 |
| C13 | No real Codex, strong-sandbox/network/credential capability, or shared-execution-root multi-replica is enabled, and no Phase 5/6 scope leaks in | Must pass | AC-10, AC-12; G4; FR-8, FR-10 |
| C14 | Missing Linux/cgroup/mount/container items are labelled `pending_env` honestly; no approximation is presented as full support (revision 2026-11-18: the former "block their promise" clause is superseded, see §6.1) | Must pass (honest labelling; no longer blocks stage acceptance) | AC-5, AC-8, AC-9, AC-12; G2–G5; FR-4, FR-6, FR-7, FR-10 |

## 6. Pass Criteria and Acceptance Record

> Scope-limited revision 2026-11-18: this section is the authoritative statement of this revision and overrides any contrary wording in this document or in `06`/`07`/`08`; it rewrites no historical execution number or conclusion. The full gate reclassification is in §6.1.

- **Pass**: A1–A12 and C1–C14 all pass; M1–M3 are complete or have equivalent automated evidence; no P0/P1 remains; process/resource cleanup, isolation, Secret, migration, terminal-state, and rollback evidence is complete (no longer requires complete Linux/cgroup/mount/container environment evidence, supervision-overhead vs Phase 0 baseline comparison, final-head CI runs, or real historical samples).
- **Conditional pass**: only non-hard-gate P2/P3 residuals that do not affect security, process/resource reliability, isolation, observability, or rollback, each with an owner/deadline and an explanation from the acceptance owner in the record below; no veto item applies (environment/performance/CI/sample-class `pending_env`/`not_measured` no longer block stage acceptance, see §6.1).
- **Fail**: any AC or still-effective hard gate fails; any out-of-bound file operation, mistaken kill, untrusted execution, silently ignored resource, secret leak, active orphan, or non-drainable rollback occurs (a missing Phase 0 *performance* baseline alone no longer makes compatibility undecidable; behavioral compatibility is still decided by byte-parity pins and regression evidence). After fixing, reverify affected items and the complete security/recovery regression.

### 6.1 2026-11-18 Scope-Limited Gate Reclassification

- **No longer stage-acceptance blockers (retained only as historical context or explicit out-of-scope notes)**: Linux/cgroup v2 `memory.max`, `pids.max`, filesystem/project quota total, per-Execution CPU group hard ceiling, live mount-namespace experiments, deterministic real-OS PID-reuse corroboration, production-image restart/stop-timeout/rollback faces, full support-matrix sign-off (P4-CM-07), supervision overhead vs Phase 0 baseline (P4-IT-30, including p50/p95 and startup/event/recovery latency and migration-lock budget), matched pairs and sample counts, CI provenance and final-PR-head CI runs/URLs, real or authorized historical samples, and multi-sample/large-sample data-volume requirements. These retain their historical `pending_env`/`not_measured` labels and environment-fact records but no longer block the stage-acceptance conclusion or enablement-promise decisions.
- **Still gates**: functional correctness; Runtime Host/Workspace switch completeness (default off, explicit on, off/on/rollback, no silent fallback); tenant isolation and zero external reads/writes/deletes; Secret/credential handling; process and resource cleanup, terminal-state semantics, and ineffective late results; data integrity and migration (predecessor revalidation, no downgrade); no P0/P1; a single acceptance-owner record; no approximation presented as full support.
- **High-risk enablement stays separate**: `execution_runtime_host_enabled=true`, untrusted multi-tenant execution, production engine routing, and similar require a separate independent security and operations approval record and are never auto-unlocked by a scope-limited acceptance.

Produce the Phase 4 Acceptance Report with A/C evidence links, support matrix, raw C2 timing, key manual checks, migration/restart/rollback evidence, residuals, and the single record below; multi-role signatures are not required. Full pass covers trusted built-in test processes only and is not approval to expose untrusted multi-tenant code execution.

| Acceptance owner | Executor | Date | Target SHA | Decision | Evidence/residuals |
|---|---|---|---|---|---|
| To be filled | To be filled (may be the acceptance owner) | To be filled | To be filled | Pending acceptance | To be filled |
