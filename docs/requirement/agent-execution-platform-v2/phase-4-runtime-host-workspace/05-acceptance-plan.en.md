# Phase 4 · Runtime Host, Process Supervision, and Workspace — Acceptance Plan

> Status: Pending execution (run before this phase goes live; no acceptance results currently exist)
> Created: 2026-11-02
> Basis: `01-business-goals.md` (G1–G5, success metrics), `02-requirements.md` (AC-1–AC-12); test execution follows `04-test-plan.md`

## 1. Acceptance Goals and Organization

Confirm that this phase is **functionally correct** (every AC reproduced), **operationally effective** (cleanup, isolation, resource, and observability metrics met), and **safe to enable** (untrusted execution off, no out-of-bound file operations/mistaken kills/silently ignored resources, and drainable rollback), then record a signed conclusion.

| Role | Responsibility |
|---|---|
| Product/platform owner | Facilitates acceptance; signs off Host boundary, phase scope, and P2 residual handling |
| QA | Executes A1–A12 and evidence; real-process, failure/adversarial/resource matrices, Phase 0 baseline comparison, and defect severity |
| Engineering lead | Provides environment/built-in test targets; migration/restart/rollback drills; metric data and fixes |
| Security owner | Veto authority for path/link/race, cross-tenant, untrusted execution, secrets, and mistaken-kill gates |
| Operations owner | Linux/cgroup/volume/container environment; canary, health alerts, stop/drain, and production suitability |
| Adapter engineering representative | UAT for two Adapters reusing Host, protocol ownership, and Sandbox replacement |
| SRE/tenant-security representative | UAT for resource bounds, cleanup-failure remediation, public redaction, and rollback operability |

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

**Prerequisites**: Phase 0 baseline and Phase 1–3 acceptance are complete; all applicable `04-test-plan.md` cases pass with no P0/P1; actual migration head/down_revision was revalidated during implementation; full acceptance has Linux/cgroup/mount/container environments. Use at least two dedicated tenants, independent scopes, and built-in trusted test targets, with no production customer data or real model keys. Mark any missing-environment item `pending_env` and block its corresponding enablement promise rather than skipping or passing it.

## 3. Functional Acceptance Checklist (AC-1–AC-12)

| # | Criterion | Acceptance steps | Pass criteria | Traceability |
|---|---|---|---|---|
| A1 | AC-1 | Start/stop processes through the same Host using two different test Adapters; inspect dependencies, internal handles, and public APIs | Reuse without Host/Worker changes; Adapters have no direct spawn/signal/resource branches; public responses expose no PID/PGID/full path | FR-1; G1; US-1, US-2 |
| A2 | AC-2 | Run a normal process with bounded I/O, then inject spawn/pipe/registration failures and stdout/stderr floods | Normal result is correct; Worker is not blocked; failures leave no residue; output excess terminates the group, with no secrets in logs/DB | FR-2; G1, G2; US-1, US-5 |
| A3 | AC-3 | Spawn nested TERM-ignoring descendants, cancel, repeat cancellation, and submit late success | KILL reaches the whole group after grace and descendants actually exit; Run remains cancelled; cleanup is idempotent and late results are ineffective | FR-3; G2; US-2, US-5 |
| A4 | AC-4 | Trigger Run deadline, process wall timeout, and their races with cancellation separately | Earlier deadline wins; group/resources release; terminal state/reason are stable, with no duplicate terminal state, zombie, or leak | FR-3; G2; US-2, US-5 |
| A5 | AC-5 | Kill Worker/restart its container with live processes; then construct PID reuse, identity mismatch/absence, and DB outage | Matching orphans are recovered; mismatch kills are zero; DB failure causes no blind scan/kill; manual remediation/alerts are explicit and no Session replays | FR-4; G2, G5; US-3, US-5 |
| A6 | AC-6 | Concurrently create cross-tenant Workdirs; verify retention, restart recovery, cleanup failure, and retry after completion/failure/cancellation | Directories are unique with correct permissions; states/ownership recover; retention is correct; cleanup is idempotent, failures are visible/retryable, and Tombstones remain | FR-5; G3, G5; US-3, US-4 |
| A7 | AC-7 | Submit absolute paths, `..`, encoding/separator bypasses, cross-tenant paths, and unapproved mounts through raw inputs | All reject before touching external resources; valid relative paths work; public APIs have no host-path entry | FR-6; G3; US-4, US-5 |
| A8 | AC-8 | In an isolated namespace, create symlinks/hardlinks/mount points to external sentinels and post-check replacement races, then read/write/clean | Zero successful external reads/writes/deletes; sentinels remain unchanged; uncertain scope stops with an alert and no host-level recursive deletion | FR-6; G3; US-4, US-5 |
| A9 | AC-9 | Exceed CPU/memory/PID/Workdir total and per-file/wall-time/output bounds individually under the full matrix, then start on an unsupported environment | Supported excess rejects/terminates within specified time and releases resources; missing required capabilities reject start; zero silent ignores or adjacent-Execution impact | FR-7; G4; US-5, US-6 |
| A10 | AC-10 | Replace the Sandbox test Provider and attempt arbitrary commands, uploaded code, untrusted multi-tenant execution, and configuration bypasses | Replace without Adapter/Host contract changes; 100% of untrusted-execution entries reject; Local Provider makes no strong-sandbox/network/credential promise | FR-8; G4, G5; US-6 |
| A11 | AC-11 | Observe normal, crash, orphan, cleanup_failed, resource-pressure, and stalled-reconcile states, then attempt public reads of internal fields | Metrics/logs/alerts cover every state and correlate Run/host; secrets, PID/PGID, and full paths stay out of public surfaces and evidence | FR-9; G5; US-3, US-7 |
| A12 | AC-12 | Upgrade `0054` from the actual predecessor, verify default-off/legacy React, then drill stop admission → drain → verify → disable → application rollback | Only necessary tables/indexes are added; React has no regression; rollback leaves zero active orphans, retains both tables/audit, and needs no downgrade; cleanup_failed blocks full rollback | FR-4, FR-5, FR-10; G1, G5; US-2, US-3, US-7 |

Record for every scenario: executor, date, environment/support matrix, target commit, prerequisite data, actual operations, expected/actual result, decision, and process/resource/DB/filesystem/log evidence links. Failures or missing environments cannot be rewritten as passes; destructive evidence references only isolated sentinels and dedicated volumes.

## 4. UAT Decision (Adapter Engineering and Operations Representatives)

- Adapters implement only Engine/Protocol and Host calls, without copying process-group, resource, or Workdir cleanup logic; replacing Sandbox Provider requires no protocol-code change.
- Operators can distinguish Run terminal state, process exit, resource release, and Workdir deletion, and can safely retry or manually remediate from cleanup_failed records.
- Public diagnostics expose no host path/PID/secret; internal operational evidence correlates by Run/host/tenant with controlled access.
- The support matrix clearly distinguishes full Linux capabilities, macOS development approximations, and unsupported items; deployers cannot mistake Local Provider for an untrusted-code sandbox.
- The rollback runbook is executable: stop admission, drain and verify zero active, then disable and roll back; cleanup_failed explicitly blocks rather than forcing table cleanup.

## 5. Business-Metric Acceptance

| Metric | Baseline | Target | Measurement method |
|---|---|---|---|
| External test-process and descendant cleanup rate | Pending Phase 0 review of existing cancellation/restart coverage; no external-process baseline exists | 100% cleanup across specified normal, cancellation, timeout, crash, and restart scenarios, with no managed descendants left | For each Run in all five categories, reconcile process group, descendants, resource handles, and Workdir records; cleanup_failed does not count as success |
| Cancellation/timeout to actual process-group stop latency | Pending Phase 0 existing-cancellation measurement; no OS-process baseline exists | Complete within configured grace + kill timeout plus 2s observation allowance; failure to stop must alert and cannot report cleanup success | Record trigger, TERM, KILL, last descendant exit, and alert with a monotonic clock, then calculate per case against its configuration |
| Orphan-identification safety | Pending Phase 0 Worker-recovery semantics review | 100% recoverable-orphan identification; zero PID-reuse/identity-mismatch kills; uncertain processes enter manual remediation | Count recovery, signals, and manual records across match/mismatch/missing-identity/cross-Host/DB-failure matrices |
| Workdir isolation and malicious-path denial rate | Pending Phase 0 file-path safety coverage review | 100% unique legal Execution directories; zero escapes across specified traversal, absolute-path, symlink/hardlink, and race cases | Check path/permission/ownership for concurrent legal samples; compare every external sentinel's content and metadata before/after the malicious matrix |
| Effective resource-limit enforcement rate | Pending Phase 0 deployment resource-control review | Within the support matrix, every CPU/memory/PID/disk/time/output excess terminates or rejects; zero silently ignored unsupported required capabilities | Persist the support matrix per environment, then record threshold, actual usage, termination/denial latency, release result, and adjacent Run state for each item |
| Host health and rollback observability coverage | Pending Phase 0 Worker health/metrics review | 100% structured observability for active processes, orphans, cleanup failures, Workdir usage/retention, and recovery batches; zero active orphans after rollback | Check metrics/logs/alerts against the state checklist, then independently reconcile DB and OS after full rollback rather than trusting application self-report |

## 6. Compliance Checks

| # | Check | Decision | Traceability |
|---|---|---|---|
| C1 | Host is decoupled from Adapters/Worker, and public APIs/handles expose no PID/PGID, host path, or environment | Must pass | AC-1; G1; FR-1 |
| C2 | Cancellation/timeout actually cleans the whole process group, late results cannot overwrite terminal state, and cleanup failure is not falsely reported as success | Veto | AC-2–AC-4; G2; FR-2, FR-3 |
| C3 | Recovery verifies host/boot/start token/digest together; zero PID-reuse kills and no blind kills on DB failure | Veto | AC-5; G2; FR-4 |
| C4 | Tenant/scope ownership is rechecked, with zero successful external reads/writes/deletes across traversal/encoding/link/mount/race cases | Veto | AC-6–AC-8; G3; FR-5, FR-6 |
| C5 | Missing required resource capabilities reject start, support matrix is truthful, and no limit is silently ignored, raised, or replaced by host totals | Veto | AC-9; G4; FR-7 |
| C6 | Arbitrary commands, uploaded code, and untrusted multi-tenant execution always reject; Local Provider is not advertised as a strong sandbox | Veto | AC-10; G4; FR-8 |
| C7 | Logs, events, DB metadata, public APIs, and acceptance evidence contain no tokens, keys, secret argv/env, or full host paths | Veto | AC-2, AC-11; G5; FR-2, FR-9 |
| C8 | Run, process, resource, and Workdir states are recorded separately; cleanup is idempotent, failures retryable, and Tombstones/audit retained | Must pass | AC-3–AC-6; G2, G3; FR-3–FR-5 |
| C9 | Active/orphan/failure/resource/disk/recovery batches have structured observability and alerts without uncontrolled high-cardinality labels | Must pass | AC-11; G5; FR-9 |
| C10 | `0054` predecessor is revalidated before implementation, only necessary tables/indexes are added, history is unchanged, and production rollback does not downgrade | Must pass | AC-12; G5; FR-4, FR-5, FR-10 |
| C11 | New Host is off by default, React/Worker/SSE matches the Phase 0 baseline, and Phase 3 behavior does not regress | Veto | AC-12; G1, G5; FR-10 |
| C12 | Rollback stops admission and drains first, then rolls back the application at zero active; cleanup_failed blocks full rollback and records are not deleted | Veto | AC-12; G5; FR-10 |
| C13 | No real Codex, strong-sandbox/network/credential capability, or shared-execution-root multi-replica is enabled, and no Phase 5/6 scope leaks in | Must pass | AC-10, AC-12; G4; FR-8, FR-10 |
| C14 | Missing Linux/cgroup/mount/container items are `pending_env` and block their corresponding promise, with no approximation presented as full support | Veto | AC-5, AC-8, AC-9, AC-12; G2–G5; FR-4, FR-6, FR-7, FR-10 |

## 7. Pass Criteria and Sign-off

- **Pass**: A1–A12 all pass; all six metrics meet targets; C1–C14 all pass; no P0/P1 remains; complete Linux/resource/adversarial-filesystem/restart/rollback evidence exists.
- **Conditional pass**: only P2/P3 residuals that do not affect security, process/resource reliability, isolation, observability, or rollback, each with an owner and deadline; no veto item or promise covered by `pending_env` is eligible for conditional pass.
- **Fail**: any AC, hard metric, or veto item fails; a missing Phase 0 baseline makes compatibility undecidable; or any out-of-bound file operation, mistaken kill, untrusted execution, silently ignored resource, secret leak, active orphan, or non-drainable rollback occurs. After fixing, reverify affected items and the complete security/recovery regression.

Produce the Phase 4 Acceptance Report with AC execution records, support matrix, raw metric data, compliance checks, migration/restart/rollback evidence, residual list, conclusion, and signatures (product/platform / QA / engineering / security / operations / Adapter representative). Full pass covers trusted built-in test processes only and is not approval to expose untrusted multi-tenant code execution.
