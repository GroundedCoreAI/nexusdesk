# Phase 0 - Baseline and Inventory: Implementation Breakdown

> Status: In progress (tasked against the target commit; findings are recorded during implementation)
> Created: 2026-11-07
> Basis: all documents `01` through `05` plus current-code inspection (backend @ `c6c47dec39025ebd4d1176c1e9925bac9c99c4fd`)
> Constraints: add only tests, fixtures, and bilingual baseline documents; do not change the production execution path or add migrations; run affected suites locally and verify the full suite and clean CI evidence separately under 04/05

## 1. Tasks in dependency order

Dependency path: **lock the target and environment -> inventory current behavior with evidence -> fill fixture and regression gaps -> produce the baseline and checklist -> execute twice and report**. Runtime, configuration compatibility, and result-tooling investigations can run in parallel. Record any document-versus-code conflict as R-n before changing tests or documents.

| # | Task | Files (new/modified) | Depends on | Traceability |
|---|---|---|---|---|
| T1 | Lock the target SHA, inspect the worktree, prepare and migrate an isolated PostgreSQL database, and preserve raw results from existing suites | `baseline/regression-baseline.md` (+`.en.md`) | — | FR-1/FR-4/FR-6, AC-1/AC-4; R1/R2 |
| T2 | Inventory Run API/SSE, Composition, Factory, Worker, Repository, Engine, memory injection, and test mapping | `baseline/runtime-dependencies.md` (+`.en.md`) | T1 | FR-1, AC-1 |
| T3 | Record the actual Run state machine, cancellation/timeout/lease-loss/terminal protection, events, and SSE replay semantics | `baseline/run-lifecycle-events.md` (+`.en.md`) | T1 | FR-2, AC-2 |
| T4 | Create sourced, redacted, versioned AgentConfig fixtures and a manifest | `backend/tests/fixtures/agent_execution_baseline/` | T1 | FR-3, AC-3; R3 |
| T5 | Add only missing unit coverage for current Engine/Worker behavior, result parsing, and double-run comparison | `backend/tests/test_runtime_baseline.py` (new) and necessary test helpers | T2/T3 | FR-1/FR-2/FR-4/FR-6, P0-UT-01~04/08~10 |
| T6 | Add AgentConfig loading, invalid-input, fixture-manifest, draft-to-publish-to-snapshot, and tenant-isolation tests | `backend/tests/test_agent_config_execution_compat.py` (new) | T4 | FR-3, P0-UT-05~07, P0-IT-08 |
| T7 | Add only uncovered PostgreSQL lifecycle, race, event, and SSE cases | `backend/tests/test_runtime_postgres.py` | T2/T3 | FR-2/FR-4, P0-IT-01~07/09 |
| T8 | Produce the compatibility matrix, reproducible commands, coverage/timing, defects, per-phase regression mapping, frozen identifiers, and checklist | `baseline/configuration-compatibility.md`, `baseline/regression-baseline.md`, `baseline/refactoring-checklist.md` (each +`.en.md`) | T2~T7 | FR-3/FR-5/FR-6, AC-3~6 |
| T9 | Execute every UT/IT/CM item in 04, run affected suites twice, compare node results, and write the factual test report | `06-test-report.md` (+`.en.md`) | T5~T8 | all of 04, AC-1~6 |
| T10 | Execute automatable acceptance items from 05; mark missing CI, real-sample, or human-signoff evidence `pending_env` rather than passing it early | `07-acceptance-report.md` (+`.en.md`) | T9 | all of 05 |

Reports follow the requirement-lifecycle templates for `06-test-report.md` and `07-acceptance-report.md`. They record actual evidence only; no passing conclusion is prewritten when development starts.

## 2. Document-versus-reality findings and decisions

### R1 The planning checkpoint differs from the execution target

The header of 03 records planning checkpoint `fb3f424` and requires a new SHA at execution time. This phase created `feat/agent-execution-platform-v2-phase0` from the latest `integration` at `c6c47dec39025ebd4d1176c1e9925bac9c99c4fd`, with an initially clean worktree. **Decision:** bind baseline conclusions to `c6c47de`. Reports distinguish the unmodified target commit from the later commit containing baseline artifacts; they must not describe both as one SHA.

### R2 Tests and Alembic use different connection environment entries

Documents 03/04 require a dedicated PostgreSQL database and `TEST_DATABASE_URL` but do not give the clean-database migration command. Tests use `TEST_DATABASE_URL`, while `backend/migrations/env.py` reads `AGENT_DATABASE_URL` through `Settings`. Setting only the former leaves Alembic on its default connection; running against an unmigrated empty database fails with `relation "runtime_runs" does not exist`. **Decision:** set `AGENT_DATABASE_URL` for the dedicated empty database and run `alembic upgrade head`, then set `TEST_DATABASE_URL` to the same connection for pytest. Neither value may be committed. Preserve environment-calibration failures and counts, but exclude them from the formal double run.

### R3 Real historical samples and repository-built samples need distinct labels

02 FR-3 and 03 section 3 prefer authorized, redacted historical configurations and published snapshots. No production or customer snapshot has been supplied for this phase, so constructed JSON cannot be called a real historical sample. Repository history can establish older `AgentConfig` field shapes. **Decision:** initial fixtures use synthetic values without customer content and identify their source category as historical field shape, current boundary, or invalid construction. The compatibility report separately records the unverified representativeness of real published snapshots and a follow-up owner. Samples are never deleted or given fictitious provenance to meet a metric.

### R4 The current migration head is 0057; a fixed 0052 acceptance target is stale

The root README records `0052_memory_tasks_tenant_index` as the planning observation from 2026-11-02, while several Phase 1 documents treat `0052` as a permanent future acceptance value. At target commit `c6c47de`, `alembic heads` returns `0057_industry_pack_runtime (head)`. **Decision:** Phase 0 adds no migration and records/verifies `0057`. The root README distinguishes the historical planning observation; Phase 1 requires no change relative to its implementation-time target head. Later phases revalidate their own head at startup rather than receiving bulk renumbering edits in this phase.

### R5 Coverage and node-level double-run tooling do not exist

Section 4 of 03 says to use the project's existing coverage tooling. The dev dependencies contain pytest, httpx, ruff, pytest-asyncio, and pytest-split, but neither coverage nor pytest-cov; CI produces no JUnit or repeated-run comparison artifacts. **Decision:** add `pytest-cov` to the dev group in `backend/pyproject.toml` and update `uv.lock`, without changing production dependencies. Add `backend/scripts/runtime_baseline.py`, using only the standard library to parse JUnit counts, skip reasons, and per-node outcomes and compare two runs. Missing coverage is not 0%.

### R6 Not every late event is rejected by Repository conditional updates

Section 2 of 03 generalizes terminal protection and duplicate-event rejection to Repository conditional updates. Ordinary `finish` is a silent no-op for a terminal run, wrong owner, or lost lease, and ordinary `append` raises `CancelledError`. `DurableToolReplayCache.put`, however, increments `event_seq` and writes `tool.replay` without checking Run status, owner, lease, or cancellation. **Decision:** document ordinary execution events separately from internal replay-cache events. Do not change production code or assertions to fit an idealized model; freeze the current SSE behavior that hides replay payloads while advancing the cursor.

### R7 Configuration normalization differs by read, publish, and snapshot stage

Section 3 of 03 asks for normalized results and unchanged source samples, which could be read as materializing defaults on every read. Create/update/publish write all current defaults, but raw draft/version reads and `snapshot()` return stored JSON without materializing validation defaults; snapshot also indexes `tool_names` before validation. **Decision:** the valid publish integration fixture retains core execution keys. Assert that the raw draft is unchanged, the published version is normalized, and later operations do not rewrite an existing version. Record the current limitation of extremely sparse raw versions instead of claiming they are executable.

### R8 Local static checks must distinguish the target tree from residue

`ruff check src tests` passes on the target tree. Full `ruff format --check src` exposes pre-existing `seed_memory_*` formatting differences, and ignored legacy directories/`__pycache__` in the current working directory trigger the architecture gate even though it passes in a clean worktree of the target commit. **Decision:** do not delete pre-existing ignored user files or format unrelated production scripts in Phase 0. Record formatting as an existing P3 item, use the clean worktree and CI for architecture evidence, and run formatting checks on added/modified Python files individually.

### R9 Concrete LocalTestAdapter identifiers cannot be decided implicitly during implementation

Section 5 of 03 originally deferred exact values to Phase 1 contract review, while FR-5 in 02 requires naming conflicts or unclear semantics to be resolved in Phase 0 and AC-5 requires decisions for open names. The architecture and Phase 1 documents define only the LocalTestAdapter class and scenarios, not concrete test Engine/Protocol IDs. **Decision:** Phase 0 freezes the production tuple `(react,native,v1)` and the LocalTestAdapter-only tuple `(local-test,scripted,v1)`. The latter must not become a production Agent default or evidence of real process supervision. Phase 1 contract tests explicitly assert that the two identities are independent.

## 3. Completion and stop conditions

- Mark any core current-state conclusion without `path:line` or test-node evidence as `unknown` with an owner; never infer current behavior from the target architecture.
- Record and adjudicate an existing-behavior failure before changing it. Never weaken assertions, rewrite fixtures, or refactor production code merely to obtain a green run.
- Stop under the P0/P1 rules in 04 if new tests become nondeterministic, expose sensitive data, or cross tenant boundaries.
- Full acceptance must satisfy 05. Local development completion does not authorize Phase 1.
