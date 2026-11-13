# Phase 4 · Runtime Host, Process Supervision, and Workspace — Test Plan

> Status: Pending execution (run after this phase is implemented; no test results currently exist)
> Created: 2026-11-02
> Revised: 2026-11-11 (lightweight small-team acceptance: reuse automated evidence and remove multi-role sign-off requirements)
> Revised: 2026-11-14 (08 R-1/R-3/R-5: migration renumbered `0054`→`0059_execution_runtime_host` after revalidating head `0058_agent_execution_metadata`; new §2.1 registers the normative macOS-development-subset versus `pending_env` mapping for the current darwin execution host; test-file naming follows `test_agent_execution_phase4_*`)
> Basis: `02-requirements.md` (FR-1–FR-10, AC-1–AC-12), `03-technical-design.md` (Host, process groups, recovery, Workdir, resource matrix, and rollback)

## 1. Test Scope and Principles

**Scope**: RuntimeHost/Adapter decoupling, Process Runner/Supervisor/Registry, bounded I/O, cancellation/timeout, orphan recovery, Workspace/Execution Workdir, safe paths/cleanup, resource limits, Sandbox Provider, health observability, migration `0059_execution_runtime_host`, deployment, and rollback.

**Principles**:

1. **Baseline first**: React, Worker scheduling, and supervision-overhead baselines use Phase 0 measurements; until complete, mark them “pending Phase 0” and never derive expectations from the new implementation.
2. **Verify real processes**: process groups, TERM/KILL, exit, output floods, and resource boundaries must run repository-built-in trusted test targets, not claim success from mocked coroutines alone.
3. **Fail closed**: spawn/pipe/DB/identity/resource/cleanup failures must leave no unowned process, false success, or bypass around a denial.
4. **Adversarial inputs required**: traversal, encoding bypasses, cross-tenant paths, links/mount points, and check-use races must all demonstrate zero successful external reads/writes/deletes.
5. **Identity before PID**: recovery covers PID reuse and missing start identity; every mismatch forbids signals, with no fuzzy process-name/command-line cleanup.
6. **Verify states independently**: assert Run terminal state, process exit, resource release, and Workdir deletion separately; one cannot substitute for another.
7. **Isolate destructive tests**: use only dedicated temporary execution roots, containers, and sentinel files; never run recursive-deletion/mount experiments on developer host roots, production volumes, or real customer directories.
8. **Report environment capabilities honestly**: separate the full Linux matrix from the macOS development subset; mark missing items `pending_env` and never describe rlimit/monitoring approximations as cgroup-equivalent.
9. **Keep secrets out of evidence**: test targets receive no real model/platform keys; scan logs, DB metadata, events, and evidence attachments for sensitive data.
10. **Reuse evidence**: A/C acceptance directly references automated UT/IT/CM results and process/resource/DB/filesystem evidence instead of manually repeating the full suite; manual work is limited to key checks that cannot be automated.

## 2. Test Environments and Data Construction

| Environment | Purpose |
|---|---|
| Pure unit tests + fake clock | State machines, path normalization, recovery decisions, support matrix, settings bounds, and idempotent branches without OS processes |
| Linux real-process integration | Process groups, nested descendants, signals, bounded I/O, exit, timeout, cancellation, and resource supervision |
| Dedicated Linux cgroup v2 resource environment | Per-Execution CPU/memory/PID hard limits and resource release using built-in trusted workloads only |
| Explicitly supported macOS development subset | Non-equivalent POSIX rlimit/supervisor behavior and unsupported-capability denial; does not sign off full resource acceptance |
| Dedicated PostgreSQL + pytest fixtures | Process/Workdir records, locking, concurrency, crash recovery, DB failure, and cross-tenant checks |
| Restartable Worker/container environment | Orphan recovery and stop/drain with the same execution root, stable host_id, and new host_instance_id |
| Isolated filesystem/mount namespace | Symlinks, hardlinks, mount points, replacement races, quotas, and safe deletion, with all external targets being test sentinels |
| Two Phase 1 test Adapters + Phase 2/3 orchestration | Host reuse, ExecutionRequest/Effective prerequisites, events/terminal state, and Sandbox replacement |
| Disposable migration DB and production-like copy | Upgrade from actual predecessor, legacy React, concurrent reads/writes, application rollback, and paired downgrade |
| quickstart/production deployment-check environment | Default-off, execution volume, one Host, stop timeout, non-secret settings, and rollback |

**Data conventions**: use at least two tenants, multiple business/workspace scopes, and concurrent Runs. Executable targets and argv allowlists are fixed; child-process/CPU/memory/disk/output workloads are parameterized for tests but accept no user code. External link targets are isolated sentinels. Construct PID reuse deterministically with identity-decision substitutes first, then corroborate with an isolated OS experiment; never kill unrelated processes to “reuse a PID.” Each case independently cleans process groups, resource handles, Workdirs, and DB rows, and cleanup failure is itself a reported result.

### 2.1 macOS development-subset versus `pending_env` mapping (normative, 2026-11-14, 08 R-3)

The current execution host is macOS (darwin) with Docker available for PostgreSQL (dedicated pgvector container, `TEST_DATABASE_URL`). Until a Linux full-acceptance environment exists, the following partition governs every case in §3–§5 and overrides any ambiguity in a case's wording. Items measured here report pass only with the environment label attached; `pending_env` items keep their enablement promises blocked (Principle 8, 05 C14) and must never be approximated into a pass.

| Partition | Cases (halves) |
|---|---|
| Measurable on macOS | All P4-UT except the cgroup/quota/mount live halves; P4-IT-01–08, 10 (identity-substitute half), 11–18 (non-mount half), 21 (per-file half), 22, 23 (macOS column), 24–27, P4-CM-02–06, 08–13; process-group TERM/KILL and descendants, rlimit CPU/address-space/file-size approximations labeled non-equivalent, output bounds, wall-time races, path/link/race safety on APFS, Workdir lifecycle, registry reconcile and SIGKILL+restart process-level recovery, migration 0059 up/down on docker PG, default-off React parity, quickstart-profile container drill on local Docker |
| `pending_env` (Linux required) | P4-IT-19 (cgroup memory hard-limit half and CPU group-accounting hard ceiling), P4-IT-20 (cgroup pids per-Execution hard limit), P4-IT-21 (filesystem/project quota half), P4-IT-17 / P4-UT-13 (live mount-namespace half), P4-IT-10 (deterministic OS PID-reuse corroboration half), P4-IT-09 (production-image container restart/stop-timeout half), P4-IT-29 (production runtime-inspection half), P4-IT-30 (also `not_measured`: Phase 0 baseline gap, 08 R-2), P4-CM-07 (full support-matrix sign-off) |

## 3. Unit Tests

| ID | Case | Expected result | Traceability |
|---|---|---|---|
| P4-UT-01 | Two test Adapters call the same Host interface | Host has no Engine branch, public handles contain only platform fields, and Adapters do not directly spawn/signal | FR-1; AC-1 |
| P4-UT-02 | Unregistered executable, arbitrary argv/command, and sensitive environment | Reject before spawn; command digest is auditable without secret argv/env | FR-1, FR-2; AC-1, AC-2 |
| P4-UT-03 | stdout/stderr independently approach and exceed byte limits | Independent backpressure per stream; excess triggers group cleanup and a stable error without unbounded buffering | FR-2; AC-2 |
| P4-UT-04 | Cancellation state machine TERM → grace → KILL | Stable transition order, deadlines, and reason; repeated cancellation does not restart the machine | FR-3; AC-3 |
| P4-UT-05 | Run deadline, process wall deadline, and cancellation race | Earlier deadline wins, one cleanup owner, deterministic error/terminal state | FR-3; AC-4 |
| P4-UT-06 | Late success, duplicate exit, and repeated cleanup | Cancelled state is not overwritten, exited/cleanup states are idempotent, and release is not duplicated | FR-3; AC-3, AC-4 |
| P4-UT-07 | Host/instance/PID/PGID/start-token/command-digest match decision | Only a fully matching record becomes orphaned and enters managed cleanup | FR-4; AC-5 |
| P4-UT-08 | PID reuse, missing/mismatched identity, and another Host's records | Zero signals, cleanup_failed/manual remediation, and no unrelated record scans | FR-4; AC-5 |
| P4-UT-09 | Reconcile encounters DB outage | Bounded retry and alert, with no host-wide scan or command-name kill fallback | FR-4; AC-5 |
| P4-UT-10 | Workdir path generation, permissions, and state transitions | Unique per Run, client paths ineffective, legal states monotonic, and cleanup_failed retryable | FR-5; AC-6 |
| P4-UT-11 | Retention expiry, duplicate cleanup, and Tombstone | Success/failure retention applies separately; repeated calls delete no other directory and preserve records | FR-5; AC-6 |
| P4-UT-12 | Absolute paths, `..`, NUL, backslash, encoded/repeated separators, and excessive length | All rejected before opening external targets, while valid relative paths remain usable | FR-6; AC-7 |
| P4-UT-13 | Symlinks, hardlinks, mount points, and component-wise no-follow policy | Deny by default or use only explicit platform allowlists; check and use share one directory handle | FR-6; AC-8 |
| P4-UT-14 | Unprovable cleanup scope or replacement race | Stop immediately, preserve external sentinel, and alert, without host-level recursive deletion | FR-6; AC-8 |
| P4-UT-15 | CPU/memory/PID/disk support-matrix combinations | Explicitly label hard-limit/approximate/unsupported; reject start when a required capability is missing | FR-7; AC-9 |
| P4-UT-16 | Resource-excess reasons, sample deadlines, and idempotent release | Stable excess reasons, one resource-handle release, and no claim that monitoring is isolation | FR-7; AC-9 |
| P4-UT-17 | Local Sandbox and replacement Provider contracts | Host does not depend on an implementation; Local capabilities exclude network/credential/strong-isolation promises | FR-8; AC-10 |
| P4-UT-18 | Arbitrary commands, uploaded code, and untrusted multi-tenant switch bypasses | Every entry is hard-denied; configuration cannot turn Local Provider into untrusted-execution permission | FR-8; AC-10 |
| P4-UT-19 | FR-10 defaults, environment overrides, and invalid bounds | Off by default; invalid timeout/limit/host_id/root/interval values reject before startup | FR-10; AC-12 |
| P4-UT-20 | Registration failure after spawn and partial resource-preparation failure | Reverse cleanup through the same managed handle, with no unowned process or resource reference | FR-2, FR-4, FR-7; AC-2, AC-5 |
| P4-UT-21 | Serialize public results, logs, metrics, and DB metadata | No PID/PGID, full host path, token, environment value, or secret argv | FR-2, FR-9; AC-2, AC-11 |
| P4-UT-22 | Health aggregation, low-cardinality labels, and stalled reconcile | Active/orphan/failure/disk states correlate, anomalies alert, and no high-cardinality labels appear | FR-9; AC-11 |

## 4. Integration Tests

| ID | Case | Expected result | Traceability |
|---|---|---|---|
| P4-IT-01 | Two different test Adapters use the same Host through Orchestrator | Reuse without Host/Worker changes, independent protocol handling, and no internal OS fields in public APIs | AC-1; FR-1 |
| P4-IT-02 | Normal built-in test-process start, bounded bidirectional I/O, exit, and result commit | Correct exit/result and event order, with process/resource/Workdir states completing independently | AC-2; FR-2, FR-5 |
| P4-IT-03 | Inject spawn, pipe-read, start-identity, and registration failures | All created resources clean up, Run fails stably, and no unregistered process remains alive | AC-2; FR-2, FR-4 |
| P4-IT-04 | Flood stdout/stderr continuously while observing Worker scheduling | Each stream terminates the group at its limit, memory/logs stay bounded, and Worker heartbeat is not starved | AC-2; FR-2 |
| P4-IT-05 | Parent spawns nested TERM-ignoring children, then cancellation | KILL reaches the whole group after grace, all observable descendants exit, and resources/directory enter subsequent cleanup | AC-3; FR-3 |
| P4-IT-06 | Repeated cancellation, coroutine cancellation, and late Adapter success | Cleanup runs once, Run is cancelled, and late results cannot overwrite it | AC-3; FR-3 |
| P4-IT-07 | Trigger Run deadline, process wall timeout, and concurrent cancellation separately | Earlier deadline wins, group/resources release, and no duplicate terminal state, zombie, or residue remains | AC-4; FR-3 |
| P4-IT-08 | Kill Worker with live processes and restart with the same host_id | New instance processes only matching records, terminates/cleans orphans, and neither resumes protocols nor replays Runs | AC-5; FR-4 |
| P4-IT-09 | Container restart, persistent-volume retention, and stop-timeout drill | Records/Workdirs recover, stop drains first, and default cleanup finishes within stop grace | AC-5, AC-12; FR-4, FR-10 |
| P4-IT-10 | Construct PID reuse, start-token/digest mismatch, and unreadable identity | Zero mistaken kills of new processes, records enter manual remediation with alerts, and directories are not blindly deleted | AC-5; FR-4, FR-6 |
| P4-IT-11 | DB disconnection, lock conflicts, and partial batch failures during recovery | No blind scan/kill; bounded retries, no cross-batch privilege expansion, and observable stalled state | AC-5; FR-4, FR-9 |
| P4-IT-12 | Process alive after Run terminal state, and process exited with resource-cleanup failure | Both still clean up/alert according to actual state; neither Run nor exited substitutes for resource release | AC-3, AC-5, AC-11; FR-3, FR-4 |
| P4-IT-13 | Concurrently create Workdirs for multiple same-tenant/cross-tenant Runs | Unique paths, correct 0700/0600 permissions, no scope mixing, and complete records before start | AC-6; FR-5 |
| P4-IT-14 | Retention expiry after completion/failure/cancellation and Host restart recovery | Each retention policy applies, states recover, and expiry does not prematurely delete failure evidence | AC-6; FR-5 |
| P4-IT-15 | Permission/disk/DB failure during cleanup followed by repeated retries | cleanup_failed is visible/alerted, retries complete idempotently after repair, and Tombstone remains | AC-6; FR-5, FR-9 |
| P4-IT-16 | Submit traversal, encoding, cross-tenant paths, and unapproved mounts through raw API/internal calls | All reject before touching external resources, valid relative paths work, and no client host-path entry exists | AC-7; FR-6 |
| P4-IT-17 | Create symlinks/hardlinks/mount points to external sentinels, then read/write/export/clean | Zero successful external reads/writes/deletes, stable denial reasons, and no external content in artifacts | AC-8; FR-6 |
| P4-IT-18 | Replace directory/file with a link after checking while cleanup runs concurrently | Handles/no-follow block the race; uncertain scope stops, sentinel remains unchanged, and an alert fires | AC-8; FR-6 |
| P4-IT-19 | Exceed CPU-time and memory limits separately in the full-support environment | Timely termination and group release per the support matrix, stable resource errors, and no adjacent-Execution impact | AC-9; FR-7 |
| P4-IT-20 | Spawn processes beyond the PID limit | Reject/terminate at the configured bound without substituting host totals, with complete resource records | AC-9; FR-7 |
| P4-IT-21 | Exceed Workdir per-file and total limits separately | Reject/terminate and safely clean; disk usage remains isolated from other Runs/tenants | AC-9; FR-5, FR-7 |
| P4-IT-22 | Exceed wall time and output limits with added resource-sampling delay | Terminate within bounded time, backpressure works, and no unbounded buffering or supervisor-coroutine leak occurs | AC-4, AC-9; FR-2, FR-3, FR-7 |
| P4-IT-23 | Start on the macOS development subset, with cgroup disabled, and on an unsupported platform | Only explicitly supported items run; required=true rejects missing capabilities, with zero silent ignores | AC-9; FR-7, FR-10 |
| P4-IT-24 | Replace the Sandbox test Provider and attempt untrusted-execution entries | Replace without Adapter/Host contract changes; arbitrary commands/uploaded code/untrusted multi-tenant execution all reject | AC-10; FR-8 |
| P4-IT-25 | Observe normal, crash, orphan, cleanup-failure, resource-pressure, and stalled-reconcile states | Metrics/logs/alerts are complete and correlated; public reads expose no secrets, PID/PGID, or full paths | AC-11; FR-9 |
| P4-IT-26 | Upgrade `0059_execution_runtime_host` from the actual predecessor `0058_agent_execution_metadata` and concurrently read/write old/new Runs | Only two tables/indexes are added, constraints/locks are correct, and existing Repository/React reads/writes are unimpeded | AC-12; FR-4, FR-5, FR-10 |
| P4-IT-27 | Run React with default-off, then stop admission → drain → disable → application rollback | React matches the Phase 0 baseline; rollback leaves zero active orphans, retains both tables, and needs no downgrade | AC-12; FR-10 |
| P4-IT-28 | Attempt full rollback with active or cleanup_failed processes | Full rollback is blocked; new admission stops while recovery/cleanup continues, with explicit manual remediation | AC-5, AC-12; FR-4, FR-10 |
| P4-IT-29 | Inspect quickstart/production volumes, Host identity, and stop grace | Production mounts the execution volume only on runtime-worker, with no shared execution root and no secrets in example settings | AC-12; FR-10 |
| P4-IT-30 | Measure Worker/Repository latency under many short processes and slow I/O | Process operations do not block heartbeat/scheduling; record overhead against Phase 0 and do not pass unmeasured targets | AC-2, AC-11; FR-1, FR-9 |

## 5. General Checks (Applicable to This Phase)

| ID | Check | Pass criterion | Traceability |
|---|---|---|---|
| P4-CM-01 | Migration online behavior and numbering | Revalidate head/down_revision before implementation; add only necessary tables/indexes, edit no history, and use correct disposable-downgrade order | AC-12; FR-4, FR-5 |
| P4-CM-02 | Host/Adapter boundary | At least two Adapters reuse it; Worker/Adapters do not directly manage OS, and public models contain no PID/path | AC-1; FR-1 |
| P4-CM-03 | Process-group and I/O bounds | TERM/KILL covers descendants, stdout/stderr/memory/logs have limits, and cleanup is idempotent | AC-2–AC-4; FR-2, FR-3 |
| P4-CM-04 | Restart identity and orphan recovery | Verify host/boot/start token/digest together; zero PID-reuse kills and no blind kills on DB failure | AC-5; FR-4 |
| P4-CM-05 | Workdir state and ownership | Unique per Run, correct permissions, tenant/scope rechecks, and auditable retention/retry/Tombstone | AC-6; FR-5 |
| P4-CM-06 | Filesystem adversarial safety | Zero successful external reads/writes/deletes across traversal/encoding/link/mount/race matrix, with fail-closed uncertain scope | AC-7, AC-8; FR-6 |
| P4-CM-07 | Resource support matrix | Measure full Linux capabilities; label development approximations, reject missing required capabilities, and silently ignore none | AC-9; FR-7 |
| P4-CM-08 | Sandbox and untrusted-execution ban | Replaceable Provider does not weaken boundaries; arbitrary commands/uploaded code/untrusted multi-tenant execution always reject | AC-10; FR-8 |
| P4-CM-09 | Health and sensitive data | Active/orphan/failure/resource/disk states are observable; public surfaces, logs, events, and metadata contain no secrets or internal OS details | AC-11; FR-9 |
| P4-CM-10 | Configuration and deployment | FR-10 defaults/bounds are correct; one Host/execution root, dedicated production volume, stop timeout covers cleanup, and examples contain no secrets | AC-12; FR-10 |
| P4-CM-11 | Independent idempotent lifecycles | Run terminal state does not imply process/resource/directory release; repeated cancel/reconcile/cleanup causes no mistaken kill/deletion | AC-3–AC-6; FR-3–FR-5 |
| P4-CM-12 | Full rollback | Stop admission, drain and verify zero active before application rollback; retain new tables; cleanup_failed blocks full rollback | AC-12; FR-10 |
| P4-CM-13 | Legacy-path regression | Phase 0 React/Worker/Repository/SSE and Phase 3 capability/config/snapshot regressions are green, with no default-off side effects | AC-12; FR-1, FR-10 |
| P4-CM-14 | Environment limits and evidence integrity | Mark items `pending_env` when Linux/cgroup/mount/container environments are unavailable and block the corresponding enablement promise rather than passing them | AC-5, AC-8, AC-9, AC-12; FR-4, FR-6, FR-7, FR-10 |
| P4-CM-15 | Phase boundary | No real Codex, general untrusted execution, strong network/credential isolation, or multi-replica shared execution root is enabled | AC-10, AC-12; FR-8, FR-10 |

## 6. Regression Scope

- Phase 0 RuntimeEngine, Worker, Repository, cancellation/lease-loss/timeout, Run API, and SSE baselines; compatibility/performance conclusions without measurements remain “pending Phase 0” and block the corresponding promise.
- Existing `test_runtime_engine.py`, `test_runtime_postgres.py`, model/tool/knowledge access, and Agent config/publication tests; with Host off by default, no external process, directory, or event side effect may appear.
- Phase 1 Adapter/Protocol, Phase 2 Orchestrator/ExecutionRequest, and Phase 3 Effective/snapshot/Instruction Provider regressions; non-external-process React does not pass through Host.
- Run old-code compatibility, new-code empty-table, and locking tests before/after migration; after disposable downgrade, verify only planned tables were removed, and never experiment on production.
- Backend ruff, affected pytest, and full CI; Compose configuration checks, container stop/restart, and volume-permission checks. Every real-process test ends by verifying zero test descendants and zero modifications outside the temporary execution root.

## 7. Defect Severity and Exit Criteria

| Severity | Definition | Handling |
|---|---|---|
| P0 blocker | Cross-tenant/host file read/write/delete; unrelated-process kill; untrusted-code execution entry; secret leak; uncontrollable process group or recursive deletion | Stop acceptance immediately and isolate the environment; after fixing, rerun complete security, recovery, and regression suites |
| P1 critical | Descendant/resource leak; ineffective cancellation/timeout; failed orphan recovery; ignored required resource limit; corrupted Run/process state; rollback leaving active orphans | No acceptance or canary before fixing |
| P2 major | Non-blocking cleanup retry, reason-code, health-metric, retention-policy, or supervision-performance deviation | Only for non-hard-gate items without security/reliability impact: record owner/deadline and have the acceptance owner confirm conditional acceptance in the single acceptance record |
| P3 minor | Non-sensitive log, internal diagnostic, or documentation presentation issue | Schedule a fix; never conceal leakage, a false support matrix, or missing environments |

**Exit criteria**: all P4-UT/IT/CM pass; AC-1–AC-12 are reproducible; applicable regressions are green; no P0/P1 remains open; external modifications, unrelated-process kills, untrusted execution, and silently ignored limits are all zero; default-off React baseline diff is zero; rollback leaves zero active orphans. Mark unavailable-environment items `pending_env` and block their corresponding enablement promise rather than reporting a pass.
