# Phase 4 · Runtime Host, Process Supervision, and Workspace — Implementation Breakdown

> Status: T1–T15 complete through batch B5 plus the B6 observability lane; T16 close-out executed by B6 (evidence summary in §8, full per-case results land in 06)
> Created: 2026-11-14
> Basis: `01-business-goals.en.md`, `02-requirements.en.md`, `03-technical-design.en.md`, `04-test-plan.en.md`, `05-acceptance-plan.en.md`, plus a code-reality review of branch `feat/agent-execution-platform-v2-phase4` (cut from completed Phase 3 at `c63fd4a`)
> Baseline facts: actual Alembic head is `0058_agent_execution_metadata` (down_revision `0057_industry_pack_runtime`); Phase 3 acceptance closed **conditionally passed** (see R-2); this development host is macOS (darwin) with Docker available for PostgreSQL (R-3)
> Working constraints: main workspace only, no git worktrees; RED before GREEN; never prewrite outcomes; 06/07 exist only after real execution; no push/PR from this flow

## 1. Implementation Rules

1. Follow the Phase 3 four-role process (see Phase 3 08 §1): design / development (backend lane; there is no frontend lane in Phase 4) / test / acceptance as independent passes, coordinator relaying between them; findings are fixed before the next task. Every task runs RED (failing test for the missing behavior, failing for the right reason) before GREEN.
2. Backend commands run from repository root: `uv run --directory backend ruff check src tests`, `uv run --directory backend pytest …`, and the architecture gate `uv run --directory backend python ../scripts/check_architecture.py`. Format-check only Phase 4 added/modified files.
3. PostgreSQL integration uses an independent pgvector Docker container with `TEST_DATABASE_URL` for pytest and `AGENT_DATABASE_URL` for Alembic (same pattern as Phase 3 08 §1.5–1.6); secrets live only in a mode-600 file outside the repository (suggest `/tmp/nexusdesk-phase4-pg.env`), never in code, scripts, docs, or reports.
4. **macOS honesty rule**: the executor host is darwin. Only items listed as measurable in §5 may be reported as passed here; `pending_env` items block their corresponding enablement promise (04 Principle 8, 05 C14) and are never substituted by an rlimit/supervisor approximation.
5. Architecture boundaries hold: `core_platform` must not import `applications` or `business_capabilities`; no dynamic Python loading (the Host executes only an allowlisted fixed executable + argv, never code); Worker keeps sole ownership of Run terminal states via `agent_runtime/repository.py`; the Host persists only its own two tables.
6. No new runtime dependencies without a coordinator ruling. In particular **psutil is not a dependency and must not be added**: start-identity probes use the standard library only (R-6).
7. The default-off invariant is absolute: with `execution_runtime_host_enabled=false` the React/Worker path stays byte-identical to the Phase 3 accepted state, no directory is created, no process is spawned, and no event is emitted.
8. Every documentation change updates both `.en.md` and `.md`. Do not edit applied migrations or historical documents' frozen conclusions; 01 keeps its self-exempt "planned identifier" wording (R-1).
9. Trusted test targets are repository-fixed (02 FR-8): parameterized test workloads run via the interpreter executing fixed target modules under `backend/tests/agent_execution/` (extend the existing helpers directory); no user-supplied code, no arbitrary argv, and the executable allowlist is a code constant.

## 2. Conflict Log and Design Decisions (Phase 4 numbering restarts at R-1)

| ID | Conflict/code reality | Frozen decision |
|---|---|---|
| R-1 | 01–05 planned migration `0054_execution_runtime_host` with planned predecessor `0053_agent_execution_metadata`. Reality: Phase 3 renumbered its migration 0053→`0058_agent_execution_metadata` (Phase 3 precedent: plan number drifted because `0053_routing_decisions` was already taken), and the actual head is `0058_agent_execution_metadata`, so `0054` is unusable | Phase 4 migration is **`0059_execution_runtime_host`**, `down_revision = "0058_agent_execution_metadata"`. 03 (header, §2, §3.2), 04 (§1 scope, P4-IT-26), 02 (AC-12) and 05 (A12, C10) are revised bilingually in this round; 01's bullet stays as written because it already commands revalidation before implementation. T2 revalidates `alembic heads` at execution time; if the head moved again, apply the same renumber-and-sync procedure, never edit history |
| R-2 | 01/03 require entry "Phase 0–3 accepted". Reality: Phase 3 07 closed **conditionally passed** — condition ① C11 `not_measured` (#129), condition ③ example seed/quickstart deferred to #127/#128, condition ④ upstream gaps (Phase 0 formal acceptance incomplete, Phase 1 incomplete, Phase 2 conditionally passed) | Per the Phase 3 R-1 precedent (development entry ≠ launch gate): Phase 4 **development entry is granted** on the merged and independently re-verified Phase 3 code; every upstream/condition gap carries forward and blocks only **enablement/rollout promises** (`execution_runtime_host_enabled=true` anywhere real), which Phase 4 must never make in this phase anyway (Host stays off by default). Phase 4 07 must record the same ceiling honestly |
| R-3 | 02 Portability and 04/05 assume a Linux full-acceptance environment plus a dedicated cgroup v2 environment; this whole phase is being developed on a darwin host | Adopt the §5 split: the measurable macOS development subset (process groups, TERM/KILL, rlimit CPU/address-space/file-size approximations labeled non-equivalent, output bounds, wall time, path safety incl. symlink/hardlink/races on APFS, Workdir lifecycle, registry/PG via docker pgvector, migration 0059 up/down, quickstart compose drills) is executed and reported here; cgroup v2 per-Execution memory/PID hard limits, filesystem/project quotas, mount-namespace experiments, deterministic OS PID-reuse corroboration, production-compose restart drills, and the Phase 0 supervision-overhead baseline are `pending_env` and block their AC-9/AC-5-promise rows, never reported as passes. 04 gains §2.1 registering this mapping bilingually |
| R-4 | 03 speaks of "Phase 1–3 Adapter/ExecutionRequest/Effective snapshot" prerequisites abstractly. Real interfaces the Host/orchestrator must connect to: `contracts/adapter.py::AgentEngineAdapter.start(request: ExecutionRequest) -> ExecutionHandle` (registry validates exactly one positional start argument); `ExecutionRequest` already carries `execution_workdir: OpaqueString \| None` (≤200 chars) and `effective_capabilities: dict[str,bool]`; `ExecutionHandle` already has `process_id: int \| None` (default None); `orchestration/orchestrator.py::ExecutionOrchestrator.execute(ExecutionContext, worker_emit) -> ExecutionOutcome` with the Phase 3 injected-seam pattern (`capabilities/snapshot_barrier/instruction_preparer`, all optional, `phase3_enabled` property); `ExecutionContext` (`orchestration/execution_context.py`) is a plain frozen dataclass with `row/execution_id/scope/owner/prepared_instructions/…` | (a) `ExecutionRequest.execution_workdir` carries the **platform-generated relative path** (`<tenant-digest>/<run-uuid>` form of 03 §4.5), never a host absolute path; the Host resolves it under `execution_workdir_root`. (b) **`ExecutionHandle.process_id` stays unset (None) for Host-managed executions**: 03 §4.1 "no PID in public" binds the HTTP/OpenAPI/event/Run-metadata surfaces, and internal OS identity travels only on the Host's `ManagedProcess`; a pin test asserts serialization of handles/requests/events contains no nonzero process id (03 §4.1 updated). (c) Phase 4 seams follow the Phase 3 pattern exactly: the Orchestrator/Host wiring arrives as optional injected ports (workdir provider, runtime host, resource/sandbox) defaulting to None — with them unset the Phase 3 path is byte-identical; adapters receive the Host through their own constructor at composition, never through a changed `AgentEngineAdapter.start` contract. (d) Phase 4 adds no Run columns; joins are by `run_id` FK to `runtime_runs.id` |
| R-5 | 03 §2 planned test files `test_runtime_host.py`, `test_process_supervisor.py`, `test_execution_workdir.py`, `test_runtime_host_postgres.py`, `test_execution_runtime_host_migrations.py`; the repository convention established by Phases 1–3 is `backend/tests/test_agent_execution_phaseN_*.py` (flat tests root; shared helpers under `backend/tests/agent_execution/`), the postgres marker is declared in `backend/pyproject.toml`, and migration tests read `TEST_DATABASE_URL` | Test files are renamed to `test_agent_execution_phase4_{workdir,runner,supervisor,registry,runtime_host,sandbox,orchestration,settings,migration,deployment}.py` (per §4 task tables); trusted process-target helpers extend `backend/tests/agent_execution/`. 03 §2 is revised bilingually; coverage IDs (P4-*) and expectations are unchanged |
| R-6 | 03 §4.4 requires a process-start identity (start token) to prevent PID-reuse kills; the backend has **no psutil** and adding it would be a new runtime dependency; identity sources differ per OS | Add `host/process_identity.py` (new row in 03 §2): Linux reads `/proc/<pid>/stat` starttime + `/proc/<pid>/cmdline` digest; macOS (development subset) shells to `ps -o lstart=,comm= -p <pid>` best-effort; PGID via `os.getpgid`. Any unavailable/unparsable identity counts as **mismatch** → no signal, `cleanup_failed`/manual remediation (already mandated by 03 §4.4), so the degradation is fail-closed, never a heuristic kill. Digest = SHA-256 of normalized executable+argv captured at spawn (03 table field `command_digest`) |
| R-7 | 03 §5.2 assumes production runtime-worker "mounts only the credentials volume". Reality: `deploy/production/compose.yaml` defines the volumes list **inside the `x-backend` YAML anchor** (`volumes: [credentials:/data/credentials]`, `stop_grace_period: 45s`), and YAML merge replaces whole keys: a service-level `volumes:` overrides, it does not append | The runtime-worker service must redeclare **both** entries (`credentials:/data/credentials` and `execution_data:/data/execution`) plus its `AGENT_EXECUTION_RUNTIME_HOST_ID`; API/channel/knowledge/memory workers stay on the anchor untouched (their absence of the execution volume is itself an AC-12 check). quickstart reuses the existing `app_data:/data` with `AGENT_EXECUTION_WORKDIR_ROOT=/data/execution` and its existing 45s stop grace. FR-10 default `data/execution` remains a relative development fallback; deployments always set the absolute path |
| R-8 | Phase 3 R-48 established that rollout flags and tuning families must not shift `_runtime_fingerprint_exclude_fields()` semantics in `applications/platform_runtime/runtime_composition.py`; nothing yet excludes the FR-10 family, and 03 §5.1 does not mention the fingerprint at all | All Phase 4 `execution_runtime_host_*` / `execution_workdir_*` / `execution_process_*` / `execution_resource_*` / `execution_sandbox_provider` settings join the fingerprint exclude set (changing a limit must never force queued Runs to `configuration_changed`), and 03 §5.1 gains one sentence registering this. `execution_runtime_host_enabled=false` still constructs the Registry/Workspace **recovery/cleanup** path when records exist (03 §5.1 last bullet), so composition starts a recovery-only Supervisor before refusing admission |
| R-9 | 03 §3.2 tables imply ORM-style persistence. Reality: `runtime_runs` has no SQLAlchemy model — `agent_runtime/repository.py` uses raw `text()` SQL over asyncpg, and Phase 3 T2 used private ORM mappings only where needed | Phase 4 persistence (`process_registry.py`, `workspace_manager.py`) follows the raw-SQL repository style with `SELECT … FOR UPDATE SKIP LOCKED` and conditional updates exactly as 03 §4.4 prescribes; private SQLAlchemy table definitions are allowed only for Alembic-free existence tests. No column is added to `runtime_runs`; the only touchpoints remain its `id` FK targets |
| R-10 | 03 §1 claims the quickstart app has "a `/data` persistent volume and 45s stop grace" and settings "have Run timeout, queue/concurrency, and business-storage limits but no external-process resource policy" — verified true (quickstart compose lines 60–71; settings.py has the Phase 2/3 `execution_*` family but nothing process/Workdir/resource); also verified there is no `host/` or `workspace/` subpackage under `agent_execution/` yet | No design change; recorded so the development lane trusts these paths as the only insertion points: new code lands under `core_platform/agent_execution/host/` and `core_platform/agent_execution/workspace/` (both new packages), composition in `applications/platform_runtime/runtime_composition.py`, settings in `core_platform/platform_services/platform_settings/settings.py` |
| R-11 | Added 2026-11-14 (coordination round 1, B2 development finding). `workspace_manager.prepare` uses `INSERT … ON CONFLICT (run_id) DO NOTHING`; on a concurrent same-Run prepare the loser reads the winner's row, which may still be `preparing` because the winner's filesystem build and the guarded `preparing→ready` update run after the insert — and a winner that crashes in between leaves a row nothing advances. Interim handling returned `preparing` as-is and delegated revalidation to the B5 barrier | The prepare contract is **(b) "ready-or-refuse with self-convergence", not (a) and not (c)**: (i) `prepare` never returns a `preparing` record. On conflict where the existing row is `preparing` — and its tenant/business/workspace match the presented trusted ids, a mismatch being a stable `workdir_persistence_conflict` — the late caller converges it itself: it reruns the same idempotent handle-based build (T5's `create_workdir`/`ensure_layout` are convergent by construction, so concurrent reruns are safe) and the same guarded conditional `preparing→ready` update, then refetches. (ii) Post-condition: a record in `ready` or `active`, or a `WorkspaceStateError` with a stable code — `retained`/`cleaning`/`deleted`/`cleanup_failed`/stuck-`preparing` all mean start-prevented under FR-5's failure row, never "sort of usable". (iii) The invariants survive unchanged: exactly one directory per Execution stays the `run_id` UNIQUE with no new edge in `WORKDIR_STATE_TRANSITIONS` (the loser's update is a no-op when the winner landed first); state recovery means a retried prepare — including after Host restart or barrier retry — converges a crashed winner's `preparing` row, and where nothing retries, `cleanup` already accepts `preparing`, so the sweeper path stays unchanged; cleanup idempotency is untouched. (iv) Rejected alternatives: (a) leaves the crashed-winner row stuck forever unless the barrier grows a polling loop or an unmandated stale-`preparing` sweeper state, and hands callers a not-usable record; (c) blocks inside `prepare` on a DB wait, violating the async/nonblocking NFR and inventing a timeout owner nobody has. **B5 (T13) wiring requirement**: the barrier calls `prepare` exactly once before `Host.start`, proceeds only when the returned status is `ready`/`active` (activate stays idempotent), treats any `prepare` error as fail-closed start-prevention — reverse-order cleanup through the existing T13 failure path, Run terminal state remaining Worker/Repository-owned — introduces no polling/retry loop, and never starts against `preparing`; a pin test asserts `prepare` returns only `ready`/`active` or raises. 03 §4.2, 04 P4-IT-13 and 05 A6 revised bilingually |
| R-12 | Added 2026-11-14 (coordination round 1, B2 development finding). At `retain`, disk accounting is best-effort: a *failed* observation (link/mount/unsupported-object abort) only warns and leaves the row's `size_bytes` stale — correct; but the development treatment also skips the DB update when the observation *succeeds* yet the total exceeds `quota_bytes`, so the durable record understates exactly the over-quota directories that operators, FR-9 disk metrics, and acceptance evidence need to see | FR-7/FR-5 accounting semantics frozen: (i) **`size_bytes`/`file_count` is defined as the latest _successful_ observation** — exactly the wording 03 §3.2 already carries; staleness is allowed, a failed/partial observation must never overwrite the record (fail-closed, 04 Principle 3; the skip-and-warn behavior on observation failure is correct and is kept), while a successful observation is **always persisted, including an over-quota one** — recording an observed violation is fact, not mutation, and over-quota never flips the retain decision (a failed outcome keeps the failed-retention evidence window) and never touches `last_error_code` (retain itself succeeded). (ii) **Alerting semantics for AC-9/AC-6 evidence**: a warning log alone over a stale record does not qualify as evidence; the excess signal is the persisted observation plus a structured warning/alert carrying a stable resource-excess reason code from the T12/P4-UT-16 vocabulary (no new `WorkdirErrorCode`; no full paths or secret text — C7). (iii) **Eventual consistency is mandatory**: every physical-deletion path — the interval sweeper, `cleanup_failed` retries, and the direct retain→clean branch — performs one best-effort re-observation before removal and persists the result when it succeeds; an observation failure there is tolerated (deletion still proceeds under its own scope rechecks) and the Tombstone keeps the final successful observation for audit. **T12 execution rule**: the resource-manager disk-accounting hook implements "persist on success / never persist partial / excess ⇒ persist plus structured reason code / re-observe before delete", and the P4-IT-13/15/21 evidence (04, revised bilingually) plus 05 A6/A9 assert the persisted over-quota observation and the alert signal, not a warn-only log. 03 §3.2/§4.2 revised bilingually |
| R-13 | Added 2026-11-14 (coordination round 2, B4 finding). On this Darwin host `setrlimit(RLIMIT_AS)` was measured to reject values below a floor around the current mapped address space (small values fail with EINVAL), so the RLIMIT_AS approximation is not unconditionally applicable on macOS, while 08 §5 and 04 §2.1 listed the "address-space rlimit approximation" as measurable without qualification | macOS `RLIMIT_AS` applicability is **probe-gated**: the resource manager runs a fork-based applicability probe, both branches pinned by tests — probe-applicable ⇒ the approximation applies and is labeled non-equivalent; probe-not-applicable ⇒ fail-closed (`execution_resource_enforcement_required=true` rejects the start of a memory-capped ProcessSpec; `false` runs unenforced with a structured warning), never a silent skip and never a recorded pass where the mechanism is unavailable. This refines, and does not contradict, the existing split: per-Execution memory **hard limits** stay Linux `pending_env` (cgroup rows), while the one-process rlimit **approximation** is conditionally measurable on macOS. Test lanes using `enforcement_required=false` for development workloads remain legitimate because the production-facing promise stays gated. 08 §5 and 04 §2.1 revised (04 bilingually) |
| R-14 | Added 2026-11-14 (coordination round 2, B4 finding). Kernel signal/errno timing for over-limit termination differs across platforms (SIGXFSZ vs EFBIG write errors; signal values 24/25 are not guaranteed identical Linux↔macOS), so B4 normalized alloc/write excess evidence to a stable trusted-exit code (86) plus a stderr marker, with `classify_result` additionally recognizing both signal forms; a B6/test agent asserting raw per-platform signals would cross-platform false-fail | Frozen one-liner: **platform-independent excess evidence is the stable reason code `runtime_host_resource_exceeded` plus mechanism/strength labels (03 §4.6 vocabulary); raw signal/exit values are Linux/macOS observation details and are never acceptance assertions.** The normalization mechanism is accepted; real excess shapes are re-verified against this evidence contract in T13/T15. Related deferral (Q3, no doc effect): support-probe fork overhead caching stays with T14 only if composition cost makes it necessary — a performance item, not a semantics change |

## 3. Batch and Task Order

Dependency spine: Batch 1 (data + config skeleton) unblocks everything; Batch 2 (workspace) and Batch 3 (process core) proceed in parallel after Batch 1; Batch 4 joins Batch 3's runner; Batch 5 wires; Batch 6 closes evidence.

| Batch | Tasks | Deliverable |
|---|---|---|
| **B1 Foundations** | T2, T3, T4 | Migration `0059`, FR-10 settings, internal host DTOs |
| **B2 Workspace** | T5, T6 | Path policy + Workdir layout, provider contract + durable manager |
| **B3 Process core** | T7, T8, T9, T10 | Runner + identity, Supervisor, durable Registry, RuntimeHost contract |
| **B4 Sandbox/resources** | T11, T12 | Sandbox Provider + Local Provider, Resource Manager + support probes |
| **B5 Wiring/deployment** | T13, T14 | Orchestrator integration, composition lifecycle + compose changes |
| **B6 Closure** | T15, T16 | Observability/secret hygiene, integration/regression close-out for 06 |

| Task | Content | Depends | Trace |
|---|---|---|---|
| T1 | This breakdown + bilingual 02/03/04/05 revisions | — | R-1–R-8 |
| T2 | Migration `0059_execution_runtime_host` (two tables + indexes) | T1 | FR-4, FR-5; AC-12; P4-IT-26, P4-CM-01 |
| T3 | FR-10 settings + validation + `.env.example` + fingerprint exclusion | T1 | FR-10; AC-12; P4-UT-19 |
| T4 | `host/host_models.py` internal DTOs | T3 | FR-1, FR-2; AC-1 |
| T5 | `workspace/workspace_policy.py` + `workspace/execution_workdir.py` | T3 | FR-6; AC-7, AC-8; P4-UT-10/12/13/14 |
| T6 | `workspace/workspace_provider.py` + `workspace/workspace_manager.py` | T2, T5 | FR-5; AC-6; P4-IT-13/14/15 |
| T7 | `host/process_identity.py` + `host/process_runner.py` | T4 | FR-2; AC-2; P4-UT-02/03/20, P4-IT-02/03/04 |
| T8 | `host/process_supervisor.py` | T7 | FR-3; AC-3, AC-4; P4-UT-04/05/06, P4-IT-05/06/07/12 |
| T9 | `host/process_registry.py` | T2, T7 | FR-4; AC-5; P4-UT-07/08/09, P4-IT-08/10/11 |
| T10 | `host/runtime_host.py` contract + composition surface + two process-capable test Adapters | T6, T8, T9, T11 | FR-1; AC-1; P4-UT-01/21, P4-IT-01 |
| T11 | `host/sandbox_provider.py` + `host/local_sandbox_provider.py` | T4 | FR-8; AC-10; P4-UT-15/17/18 |
| T12 | `host/resource_manager.py` (rlimits, sampling, disk accounting) | T7, T11 | FR-7; AC-9; P4-UT-15/16, P4-IT-19–23 |
| T13 | Orchestrator wiring (Workdir → Sandbox/resources → Host.start → events → cleanup barrier) | T10, T12 | FR-1–FR-5; AC-1–AC-6; P4-IT-01/02/27 |
| T14 | Composition lifecycle + deployment config (quickstart/production/.env.example) | T9, T13 | FR-9, FR-10; AC-12; P4-IT-09/27/28/29, P4-CM-10 |
| T15 | Health/metrics/structured logs + secret-scan pin tests | T8, T9, T13, T14 | FR-9; AC-11; P4-UT-21/22, P4-IT-25 |
| T16 | Integration/regression close-out (Phase 0/3 baselines, default-off zero-diff, §5 split evidence) | T15 | all AC; P4-IT-30, P4-CM-02–15 |

## 4. Detailed Tasks

### T2 — Migration `0059_execution_runtime_host.py` (B1)

- **Files**: `backend/migrations/versions/0059_execution_runtime_host.py` (new); `backend/tests/test_agent_execution_phase4_migration.py` (new).
- **RED**: after `uv run --directory backend alembic heads` revalidation (R-1), the PG test asserts the two tables, columns/CHECKs/indexes of 03 §3.2 (`execution_workdirs`: `(status,expires_at)`, `(tenant_id,status)`; `runtime_host_processes`: `(host_id,status)`, `(status,last_observed_at)`, `(tenant_id,status)`), the `run_id` UNIQUE FK cascade to `runtime_runs`, disposable downgrade order (processes before workdirs), and old-React read/write during upgrade.
- **GREEN**: same on the docker pgvector container; `alembic upgrade head` twice (idempotent chain), downgrade/upgrade round trip on a disposable DB.
- **Acceptance points**: exactly two tables, no `runtime_runs` column, no RuntimeHost service table, no history edit; `pending_env` applies only to the production-like concurrent-copy half (P4-IT-26 second clause) on Linux.

### T3 — FR-10 settings and rollout skeleton (B1)

- **Files**: `core_platform/platform_services/platform_settings/settings.py`; `backend/.env.example`; `backend/tests/test_agent_execution_phase4_settings.py` (new); `applications/platform_runtime/runtime_composition.py` (fingerprint exclude set only).
- **RED**: all nineteen 02 FR-10 keys exist with the defaults and bounds (bounded `Field` per 03 §5.1); enabled-state cross-validation (nonempty `execution_runtime_host_id`; `enforcement_required=true` must not admit an unsupported platform at composition — settings validate shape, the support probe lives in T11/T12); invalid bounds reject before startup; **the whole Phase 4 family is absent from the runtime fingerprint** (R-8), mirrored onto the Phase 3 static test name convention.
- **GREEN**: same pytest; `backend/.env.example` gains the non-secret block (pattern established by the Phase 3 `AGENT_EXECUTION_CAPABILITY_*` lines); ruff/format/architecture.
- **Acceptance points**: `execution_runtime_host_enabled` default false; no secret-shaped setting; env override prefix `AGENT_` unchanged.

### T4 — `host/host_models.py` internal DTOs (B1)

- **Files**: `core_platform/agent_execution/host/__init__.py`, `host/host_models.py` (new); `backend/tests/test_agent_execution_phase4_runner.py` (models section).
- **Content**: `ProcessSpec` (trusted executable id, allowlisted argv, minimal env map, workdir relative path, `ResourcePolicy`, output limits), `ResourcePolicy` (cpu/memory/pid/disk/wall/output), `ManagedProcess` (internal pid/pgid/start-token/command-digest/state machine `starting/running/terminating/exited/orphaned/cleanup_failed`), `ProcessResult`, `HostHealth`, reason-code constants. Strict pydantic models following `contracts/base.py` discipline (extra=forbid); these types are **internal**: never exported into `contracts/__init__.py` public contract surface, never serialized into events/Run metadata (02 FR-1 output row).
- **Acceptance points**: state-machine monotonic transitions unit-pinned; digest helper is the single source used later by T7/T9 (R-6).

### T5 — Workspace policy + Execution Workdir (B2)

- **Files**: `workspace/__init__.py`, `workspace/workspace_policy.py`, `workspace/execution_workdir.py` (new); `backend/tests/test_agent_execution_phase4_workdir.py`.
- **Content**: 03 §4.5 rules 1–5 as pure functions + handle-based operations: relative-path normalization and rejection (absolute, `..`, NUL, backslash, encoded/repeated separators, length), component-wise `open(..., O_NOFOLLOW)` walk from a verified root handle, `workdir/temp/logs` creation at 0700 (files 0600), disk accounting, no-follow recursive cleanup that stops on races, ownership recheck before any delete, execution-root owner/symlink validation at startup.
- **RED/GREEN**: full P4-UT-10/12/13/14 battery on APFS (macOS measurable, R-3), including hardlink and check-then-replace sentinels; mount-point denial logic is unit-tested with a substituted probe, live mount experiments stay `pending_env`.
- **Acceptance points**: zero successful external read/write/delete; the policy exposes no API that accepts a client path (AC-7).

### T6 — Workspace Provider + Manager (B2)

- **Files**: `workspace/workspace_provider.py`, `workspace/workspace_manager.py` (new); `backend/tests/test_agent_execution_phase4_workdir.py` (PG sections).
- **Content**: the prepare/activate/retain/cleanup contract (Protocol; type-level gate that only platform IDs enter), durable `execution_workdirs` records via raw-SQL repository (R-9), `preparing→ready→active→retained/cleaning→deleted/cleanup_failed` with `expires_at` retention (success vs failed periods), interval scan, idempotent retry, Tombstone retention.
- **RED/GREEN**: P4-UT-11, P4-IT-13/14/15 on docker PG; concurrent cross-tenant creation uniqueness; cleanup-failure injection keeps the record and alerts, never repoints elsewhere.
- **Acceptance points**: AC-6 states recover across a manager restart (process-level restart on macOS; container half in T14).

### T7 — Process identity + Runner (B3)

- **Files**: `host/process_identity.py`, `host/process_runner.py` (new); `backend/tests/agent_execution/` trusted target helpers (extended); `backend/tests/test_agent_execution_phase4_runner.py`.
- **Content**: spawn via `asyncio.create_subprocess_exec` with `start_new_session=True` (own process group), allowlist validation **before** spawn (R-10 rule: registry of fixed executable ids, never a caller path), minimal environment, `preexec_fn` hook points for T12 rlimits, per-stream bounded non-blocking reads with independent byte limits and backpressure (P4-UT-03), start-identity capture per R-6, reverse-order cleanup on spawn/pipe/registration failure (P4-UT-20) through the same managed handle.
- **RED/GREEN**: P4-UT-02/03/20/21, P4-IT-02/03/04 measured on macOS (process groups are POSIX; measurable per R-3); floods terminate the group with a stable error code; nothing secret in logs (`caplog` assertions).
- **Acceptance points**: AC-2 fully measurable here except the production-restart corroboration halves.

### T8 — Process Supervisor (B3)

- **Files**: `host/process_supervisor.py` (new); `backend/tests/test_agent_execution_phase4_supervisor.py`.
- **Content**: TERM → `execution_process_cancel_grace_seconds` → KILL → `execution_process_kill_timeout_seconds` state machine over the **process group**, descendant observation via the reconcile sample loop, wall-time deadline racing (earlier of Run/process deadline, 03 §4.3), idempotent repeated cancellation, `cleanup_failed` escalation with alert and never a false cleanup success, single cleanup owner under races (P4-UT-05), monotonic clock for deadlines with a wall-clock timestamp source for persisted fields (Phase 3 R-49 precedent — one injected POSIX clock).
- **RED/GREEN**: P4-UT-04/05/06 + P4-IT-05/06/07/12 on macOS with nested TERM-ignoring trusted children.
- **Acceptance points**: AC-3/AC-4 measurable here in full except late-success-into-Repository assertions that need T13 wiring.

### T9 — Durable Process Registry (B3)

- **Files**: `host/process_registry.py` (new); `backend/tests/test_agent_execution_phase4_registry.py`.
- **Content**: spawn/state persistence, bounded-batch reconcile using `FOR UPDATE SKIP LOCKED` + conditional updates (R-9), startup scan restricted to same `host_id` + execution root, verification chain host namespace/boot instance/`process_start_token`/`command_digest` (R-6), orphan decision table (match→managed TERM/KILL; any mismatch or unreadable identity→no signal, manual remediation), DB-outage bounded retry with zero host-wide scanning.
- **RED/GREEN**: P4-UT-07/08/09 (identity decision fully unit-testable with substitutes), P4-IT-08/11 on docker PG; P4-IT-10's deterministic real-PID-reuse half is `pending_env`, the substitute-decision half runs here (R-3).
- **Acceptance points**: AC-5 recovery honesty: unconfirmed processes never signaled, records auditable.

### T10 — RuntimeHost contract + two test Adapters (B3)

- **Files**: `host/runtime_host.py` (new); `backend/tests/agent_execution/` two process-capable test adapters (extending `adapters/testing/` or the tests helper package — either is fine as long as they are distinct engine triples behind the same `AgentEngineAdapter` contract); `backend/tests/test_agent_execution_phase4_runtime_host.py`.
- **Content**: `start/cancel/wait/reconcile/health/close` (03 §4.1 table), admission gate honoring `execution_runtime_host_enabled`, composition entry taking Runner+Supervisor+Registry+Workspace+Resource+Sandbox ports; Adapter-facing handle never carries OS fields (R-4b: `ExecutionHandle.process_id` stays None); Host never parses engine events and never commits Run terminal states.
- **RED/GREEN**: P4-UT-01/21, P4-IT-01 (two adapters, zero Host/Worker change), unregistered/target-rejection before spawn (P4-UT-02).
- **Acceptance points**: AC-1 reuse proof; `close()` = stop admission → drain → zero active (03 §5.1 last bullet).

### T11 — Sandbox Provider + Local Provider (B4)

- **Files**: `host/sandbox_provider.py`, `host/local_sandbox_provider.py` (new); `backend/tests/test_agent_execution_phase4_sandbox.py`.
- **Content**: replaceable Sandbox Protocol (prepare/start-hooks/release, capability matrix id/version), Local Provider declaring exactly its support-matrix row values (03 §4.6) with the untrusted-execution gate hard-coded (arbitrary command / uploaded code / untrusted multi-tenant flag rejected at every entry — settings cannot flip it, P4-UT-18), support probe registry per capability (cpu-group accounting, memory cgroup, pids cgroup, quota, rlimit fallbacks).
- **RED/GREEN**: P4-UT-15/17/18, P4-IT-24 (replacement without Host change), P4-IT-23 macOS column (only declared-supported subset starts; `execution_resource_enforcement_required=true` rejects missing required capability at start — measurable).
- **Acceptance points**: Local Provider makes no strong-sandbox/network/credential claim anywhere (AC-10, M1).

### T12 — Resource Manager (B4)

- **Files**: `host/resource_manager.py` (new); `backend/tests/test_agent_execution_phase4_sandbox.py` (resource sections).
- **Content**: apply `ResourcePolicy` through the Sandbox-declared mechanisms — RLIMIT_CPU/RLIMIT_AS/RLIMIT_FSIZE via runner preexec hooks (labeled approximate, never group-hard), supervisor-side descendant counting and RSS sampling for the reactive path (macOS measurable approximation), Workdir total/per-file quota enforcement hooks into T5 accounting, usage release idempotency (P4-UT-16), cgroup v2 adapter interface present but reporting unsupported on macOS → fail-closed for required per-Execution hard limits (R-3).
- **RED/GREEN**: CPU-time excess kill, address-space rejection, PID-count reactive bound, per-file and total disk excess terminate+clean — all measurable; cgroup memory/pids hard-limit cases marked `pending_env` in test metadata (skip-with-attribution, never silent skip).
- **Acceptance points**: AC-9 measurable subset + honest `pending_env` boundary; zero silently ignored limits.

### T13 — Orchestrator wiring (B5)

- **Files**: `orchestration/orchestrator.py`, `orchestration/execution_context.py`, `backend/tests/test_agent_execution_phase4_orchestration.py`.
- **Content**: add optional injected seams in the established Phase 3 style (`workdir_provider`, `runtime_host`, defaults None): for a process-capable adapter selection the barrier order is Effective validation (reuse R-16 start-block vocabulary) → Workdir prepare/ready → Sandbox/resource support check → Host.start → event stream unchanged → wait → Run result commit path unchanged → Workdir retain/clean decision (03 §4.2); cancellation/lease-loss reaches Host cleanup through the existing cancel task path; Run terminal state remains Worker/Repository-owned only (FR-1). React production triple path passes through untouched when the seams are unset or the Host is off.
- **RED/GREEN**: P4-IT-02 end-to-end with a trusted target through the Orchestrator, P4-IT-27 default-off React byte-parity (reuse Phase 3 regression suite unchanged), failure injection mid-barrier cleans in reverse with `Adapter.start=0` semantics equivalent.
- **Acceptance points**: AC-1/AC-2/AC-6 integration face; no public event gains OS fields (pin via contracts serialization test).

### T14 — Composition + deployment (B5)

- **Files**: `applications/platform_runtime/runtime_composition.py`, `applications/platform_runtime/runtime_factory.py` only if a construction seam requires it, `deploy/quickstart/compose.yaml`, `deploy/production/compose.yaml`, `deploy/production/.env.example`; `backend/tests/test_agent_execution_phase4_deployment.py`.
- **Content**: build Host/Supervisor/Registry/Workspace/Sandbox/Resources only per settings, startup order recovery-before-admission (R-8 recovery-only Supervisor when disabled with live records), shutdown order stop-admission→drain→close (mirror the Phase 3 warmer-close ordering discipline and its test); deployment per R-7 (runtime-worker redeclares both volumes + stable `AGENT_EXECUTION_RUNTIME_HOST_ID`; quickstart `/data/execution` on `app_data`; `.env.example` non-secret FR-10 block, no secrets).
- **RED/GREEN**: P4-IT-09 quickstart-profile container drill on local Docker (restartable), P4-IT-28 rollback block with `cleanup_failed`, P4-IT-29 static compose assertions (volume placement, one Host per root) + Linux production-runtime half `pending_env`; P4-CM-10.
- **Acceptance points**: AC-12 deployment face; stop grace 45s ≥ grace+kill+reconcile margin (assert in settings validation guidance).

### T15 — Observability + secret hygiene (B6)

- **Files**: host/workspace modules (log/metric emission), `backend/tests/test_agent_execution_phase4_runtime_host.py` (health sections) or a dedicated `test_agent_execution_phase4_observability.py`.
- **Content**: structured logs/metrics per 02 FR-9 (active processes, start failures, orphans, cleanup failures, recovery batches, exit reasons, disk usage/retention age) with Run ID/host_id correlation and low-cardinality labels, stalled-reconcile alert (P4-UT-22), health aggregation (`HostHealth`), recursive secret/OS-field scanners across logs, events, DB metadata fixtures (P4-UT-21 completion).
- **RED/GREEN**: P4-IT-25 on macOS (all states constructible except mount/cgroup rows); internal operational reads, if any HTTP surface is added, reuse authenticated internal management scope — otherwise this phase ships logs/metrics only (public Run APIs expose nothing new).
- **Acceptance points**: AC-11; no new public endpoint is created in Phase 4 unless a T-scope need proves unavoidable (defer candidate, §6).

### T16 — Integration/regression close-out (B6)

- **Files**: everything above; 06/07 are created by the test/acceptance lanes later, never here.
- **Content**: run the complete §5-measurable suite plus Phase 0/3 regression (`test_runtime_engine.py`, `test_runtime_postgres.py`, Phase 3 `test_agent_execution_phase3_*` green unchanged), ruff/format/architecture, default-off React baseline diff zero, every real-process test ends verifying zero surviving trusted-test descendants and zero changes outside the temporary execution root (04 §6 last bullet).
- **RED/GREEN**: this is the evidence-collection task; each case records pass / `pending_env` / `not_measured` per R-3 with the environment string (macOS darwin version, docker pgvector image) attached for 06.
- **Acceptance points**: P4-CM-02–15 boundary list.

## 5. macOS Measurable vs `pending_env` (normative mapping, mirrored into 04 §2.1)

**Measurable on this darwin host (report pass with environment label)**: process-group spawn/TERM/grace/KILL incl. nested TERM-ignoring children and idempotent cleanup (P4-UT-04/05/06, P4-IT-05/06/07/12); bounded per-stream output limits and flood termination (P4-UT-03, P4-IT-04); wall-time/deadline races (P4-UT-05); RLIMIT_CPU / RLIMIT_FSIZE approximations plus the probe-gated RLIMIT_AS approximation (08 R-13: fork applicability probe decides; not-applicable ⇒ fail-closed start rejection under `execution_resource_enforcement_required=true`, never a recorded pass), always labeled non-equivalent (P4-IT-19 CPU-approx half, P4-IT-21 per-file half); all path-safety cases incl. symlink/hardlink and check-then-replace races on APFS (P4-UT-12/13/14 non-mount, P4-IT-16/17/18 non-mount); Workdir lifecycle/retention/Tombstone/cleanup retry (P4-UT-10/11, P4-IT-13/14/15); Registry locking, reconcile, identity-decision substitutes, process-level SIGKILL+restart same-host_id recovery, DB-outage behavior (P4-UT-07/08/09, P4-IT-08/10-substitute/11); migration 0059 up/down + concurrent old/new reads on docker pgvector (P4-IT-26 local half, P4-CM-01); default-off React parity and full Phase 0/3 regressions (P4-IT-27, P4-CM-13); quickstart-profile compose/restart drill (P4-IT-09 local-Docker half, P4-IT-29 static-config half); settings bounds, secret scans, health aggregation, Host/Adapter boundary proofs (P4-UT-01/02/19/21/22, P4-IT-01/02/03/24/25, P4-IT-23 macOS column).

**`pending_env` (Linux-only; blocks its enablement promise, never reported as pass)**: cgroup v2 memory.max per-Execution hard limit (P4-IT-19 memory-hard half); cgroup v2 pids.max per-Execution hard limit (P4-IT-20); per-Execution CPU group accounting as hard ceiling (03 §4.6 row 1 full strength); filesystem/project quota enforcement (P4-IT-21 total-quota half); live mount-point experiments via mount namespaces (P4-UT-13 mount row, P4-IT-17 mount half); deterministic real OS PID-reuse kill corroboration (P4-IT-10 OS-experiment half); production-compose container restart/stop-timeout drill on the real runtime image (P4-IT-09 production half, P4-IT-29 runtime half, P4-IT-28 production face); full support-matrix sign-off (P4-CM-07); supervision-overhead vs Phase 0 baseline (P4-IT-30, also `not_measured` upstream: Phase 0 baseline gap per R-2).

## 6. Concession Boundaries

**Core — no concession, any failure is P0/P1 and blocks the phase**: untrusted/arbitrary execution gate (FR-8, C6); path/link/race containment with zero external modification (FR-6, C4); identity-verified recovery with zero mistaken signals (FR-4, C3); honest cleanup states — no false cleanup-success, `cleanup_failed` visible and blocking rollback (FR-3, C2/C12); secrets and OS identifiers never on public surfaces (C7); default-off React byte-parity (C11); migration correctness without history edits (C10); fail-closed support matrix — zero silently ignored required limits (C5).

**Low-priority / may be deferred to issues at acceptance**: any internal HTTP health endpoint (logs/metrics suffice for this phase); dashboards or alert routing beyond emitting structured signals; per-workload retention-class configurability beyond the two FR-10 retention settings; mount/export allowlist machinery (Phase 4 ships deny-only, no approved mount exists, so the allowlist code path may stay empty); quickstart demo seed or a Host-enabled quickstart example (mirror of Phase 3 #127/#128 pattern — the phase never enables the Host anywhere); P4-IT-30 overhead measurement until a Phase 0 baseline exists; metric label refinement (low-cardinality audit stays, prettier names go).

## 7. Definition of Done and Coordination

- Batches close only on RED/GREEN + both reviews + traceability; T13/T14 never merge before T5–T12 individual reviews pass.
- If an implementation fact conflicts with a ruling, revise this 08 and the bilingual 02/03/04/05 **first**, then code (Phase 3 discipline).
- `pending_env`/`not_measured` are terminal honest states for this run; they do not block development entry (R-2) but block any statement that AC-9/AC-5-full or enablement is proven (05 C14).
- The development lane must not touch `agent_runtime/repository.py` terminal-state logic, `contracts/adapter.py` start signature, or Phase 3 snapshot/barrier files except at the seams named in T13.

## 8. B6 Closure Register (2026-11-14, development lane)

This section is the single citable place for 06/07 to quote environment
attribution and pending items; it adds no semantics beyond §5's frozen split.

### 8.1 `pending_env` register (Linux-only, blocks its enablement promise per R-3)

| Item | Coverage IDs | macOS status |
|---|---|---|
| cgroup v2 `memory.max` per-Execution hard limit | P4-IT-19 (memory-hard half) | pending_env; rlimit approximation measured probe-gated (R-13), never substituted |
| cgroup v2 `pids.max` per-Execution hard limit | P4-IT-20 | pending_env; reactive PID-count bound sampled and measured here |
| Filesystem/project quota enforcement (total-Workdir hard quota) | P4-IT-21 (total-quota half) | pending_env; per-file RLIMIT_FSIZE half measured; accounting/excess-persist path measured (R-12) |
| Per-Execution CPU group accounting as hard ceiling | 03 §4.6 row 1 full strength | pending_env; RLIMIT_CPU approximation measured, labeled non-equivalent |
| Live mount-namespace mount-point experiments | P4-UT-13 mount row, P4-IT-17 mount half | pending_env; substituted-probe denial measured on APFS |
| Deterministic real OS PID-reuse kill corroboration | P4-IT-10 (OS-experiment half) | pending_env; decision-form substitutes + zero-signal pins measured |
| Production-image container restart / stop-timeout drill | P4-IT-09 production half, P4-IT-29 runtime half, P4-IT-28 production face | pending_env; **quickstart-profile local-Docker half NOW measured** (8.3) |
| Full support-matrix sign-off | P4-CM-07 | pending_env (Linux columns) |
| Supervision-overhead vs Phase 0 baseline | P4-IT-30 | `not_measured` upstream (Phase 0 baseline gap, R-2), not closable on this host |

### 8.2 Measured here (environment string for 06 to attach)

macOS darwin 27.0.0 x86_64; CPython 3.12.13 (uv); PostgreSQL via local Docker
`pgvector/pgvector:pg17` container `nexusdesk-phase4-pg` on `127.0.0.1:5443`
(secrets in a mode-600 file outside the repository only). Batch B6 executed
and passed: the full Phase 4 suite (`341 passed, 3 skipped with attribution`
— the cgroup/quota/mount pending_env lanes — with PG; all eleven
`test_agent_execution_phase4_*.py` files including the new observability
file's 31 cases — the P4-UT-21 full-surface secret scan over a real-process
run and the P4-UT-22 health/label/stalled-reconcile audit — and the closeout
group's 4 real-process cases inside the orchestration file (nested
ignore-term cancellation, output-flood termination, Run-deadline-wins race,
and a cross-process SIGKILL worker crash recovered by a same-host_id
identity-verified restart; zero surviving trusted-test descendants pinned
after each)), the whole
Phase 0–3 regression set with PG
(`758 passed, 3 skipped` across `phase3 or phase4` selection), and the full
non-PG repository suite (`2293 passed, 0 failed`).

### 8.3 Quickstart local-Docker drill (P4-IT-09 local half, measured)

`sh nexusdesk quickstart` rebuilt the app image (base layers seeded from the
dockerproxy mirror because direct Docker Hub metadata resolution failed on
this host), brought the stack up `Healthy`, then survived a
`docker compose restart app` round-trip with `--wait` re-greening. Verified
on the live containers: `alembic_version = 0059_execution_runtime_host`; both
Phase 4 tables exist (`execution_workdirs`, `runtime_host_processes`); the
app container carries `AGENT_EXECUTION_RUNTIME_HOST_ENABLED=false` with **no**
runtime-host id, `/data` contains only `credentials/` and `tls/` — no
`/data/execution` directory was created (default-off zero-side-effect
invariant, 08 §1.7); the React root returns 200. The production-image
runtime-worker half stays pending_env (8.1).

### 8.4 OPEN_Q1 disposition (Phase 3 postgres fixtures, pre-B6)

Reproduced on HEAD and on the Phase 3 tip `c63fd4a` with the same command:
`TEST_DATABASE_URL=postgresql://…` (plain-driver form) makes
`test_agent_execution_phase3_snapshots.py` / `_preview.py` reject at Settings
construction with `database_url must use postgresql+asyncpg`. That validator
ships since the initial commit (`7dce7ba`) — both trees fail identically —
and the same URL with the asyncpg driver scheme passes 148/148 on both trees
against the migrated container database. Conclusion: environment-shape
attribution, not a Phase 4 regression; no production-code change was made
for it. Lane note for 06/07: Phase 3 PG fixtures pass `TEST_DATABASE_URL`
verbatim into `Settings`, so they require the `postgresql+asyncpg://` form
while Phase 4 fixtures normalize either form internally.

### 8.5 Deferred candidates carried out of B6 (08 §6 vocabulary)

- Internal HTTP endpoint for operational health reads: **not added** (Phase 4
  ships logs/alerts/structured health only). The composed subsystem exposes
  `ExecutionRuntimeSubsystem.health_report()` (async `HostHealth`, including
  the Workdir stats columns of 02 FR-9) for in-process operational use; an
  authenticated internal REST surface is registered as an issue candidate.
- Alert routing/dashboards beyond emitting `AlertSink` records: unchanged
  deferral (08 §6).
