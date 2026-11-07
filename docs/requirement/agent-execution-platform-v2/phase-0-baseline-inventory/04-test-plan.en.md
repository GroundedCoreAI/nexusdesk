# Phase 0 · Baseline and Inventory — Test Plan

> Status: Pending execution (during baseline construction)
> Created: 2026-11-02
> Basis: `02-requirements.md` (FR-1–FR-6, AC-1–AC-6), `03-technical-design.md` (no migration, actual state machine, compatibility fixtures, two-run baseline)

## 1. Test Scope and Principles

**Scope**: current code/test inventory, Run lifecycle and events, Agent configuration fixtures, ReAct/Worker/PostgreSQL/SSE regression, baseline metrics, and refactoring checklist.

**Principles**:

1. **Current behavior is authoritative**: preserve existing results before adding tests; never create compatibility by changing assertions around a defect.
2. **Determinism**: external Engines/models are excluded from required paths; control time, cancellation, and lease races with tasks and direct data setup.
3. **Bidirectional evidence**: state/configuration findings have both code references and test/runtime evidence; skips/xfails cannot hide coverage gaps.
4. **Minimal fixtures**: sanitize valid and invalid samples; do not pre-write future defaults into fixtures.
5. **No production change**: no migration or runtime flag; rollback-diff checks apply to test/document changes themselves.

## 2. Test Environments and Data Setup

| Environment | Purpose |
|---|---|
| Unit | Engine/Worker logic, error mapping, configuration models, and fixture-inventory validation |
| Integration (existing PostgreSQL fixtures) | claim/heartbeat/reap/finish/cancel, event persistence, published snapshots, and SSE |
| Mock/demo models and tools | Deterministic ReAct success, budget, error, and cancellation paths |
| Clean CI environment (two consecutive runs) | Reproducible test counts, coverage, duration, and skip/xfail/flaky baseline |

**Data conventions**: follow existing test IDs and fixture styles. Place new samples under `backend/tests/fixtures/agent_execution_baseline/` with field coverage and source categories. Construct lease expiry, queue timeout, and cancellation races directly or with synchronization primitives rather than real waits.

## 3. Unit Tests

| ID | Case | Expected | Trace |
|---|---|---|---|
| P0-UT-01 | Normal RuntimeEngine message/tool loop | Freeze output/history/event shapes and current results | FR-2/FR-4 |
| P0-UT-02 | Model/tool errors, budget exhaustion, and empty output | Existing error codes/output shapes remain; provider raw text is not leaked | FR-2/FR-4 |
| P0-UT-03 | Worker factory/runtime invocation and emit routing | Durable events use Repository; `model.delta` uses only notifier | FR-1/FR-2 |
| P0-UT-04 | Cancellation during execution and watcher cleanup | Existing cancellation semantics remain; no coroutine is leaked | FR-2/FR-4 |
| P0-UT-05 | Valid historical/default/boundary AgentConfig fixtures | Existing defaults, normalization, and validation agree per fixture; source fixtures remain unchanged | FR-3/AC-3 |
| P0-UT-06 | Unknown or invalid configuration fields | Existing model explicitly accepts or rejects; record results without future Engine mapping | FR-3 |
| P0-UT-07 | Fixture inventory matches files | Every fixture has version, covered fields, expectation, and sanitization marker; no orphan files | FR-3/FR-6 |
| P0-UT-08 | Static check of identifiers and Run/Execution examples | `(react,native,v1)` is consistent; no Task table or Worker Engine-branch assumption | FR-5/AC-5 |
| P0-UT-09 | Baseline result-count parsing | Pass/fail/skip/xfail and duration are complete; missing values are not zero | FR-6 |
| P0-UT-10 | Diff two baseline runs | Non-deterministic nodes are explicit; equal totals do not hide node changes | FR-6/AC-4 |

## 4. Integration Tests

| ID | Case | Expected | Trace |
|---|---|---|---|
| P0-IT-01 | Run create→claim→normal finish | `queued→running→completed`; owner/lease/output/history and terminal event match current behavior | AC-1/AC-2 |
| P0-IT-02 | Cancel queued and running Runs | Queued becomes terminal directly; late success cannot overwrite running cancellation | AC-2/FR-2 |
| P0-IT-03 | Execution timeout, RuntimeFault, and general error | Failed state, existing error code, and terminal event agree | FR-2/FR-4 |
| P0-IT-04 | Lease expiry, heartbeat loss, and reaper | Actual terminal state and `worker_lost` semantics have evidence; stale commits fail | AC-2 |
| P0-IT-05 | Queued timeout versus cancellation | Exactly one legal terminal state under existing precedence and one effective terminal commit | FR-2 |
| P0-IT-06 | Duplicate finish, late append, and concurrent Workers | Conditional updates reject illegal writes; event sequence and Run state agree | AC-2/FR-4 |
| P0-IT-07 | Durable events and SSE `after` replay | Ordering, cursor boundaries, terminal events, and transient-delta differences match current behavior | FR-2/FR-4 |
| P0-IT-08 | Historical draft→publish→snapshot→versioned read | Valid fixtures traverse the full path without rewriting history or cross-tenant reads | AC-3 |
| P0-IT-09 | Complete mock ReAct execution and current memory injection | Success/failure/cancellation and summary/memory calls match baseline | FR-1/FR-4 |
| P0-IT-10 | Two clean-environment runs with coverage on one commit | Node-level results agree; counts/duration/coverage/environment are complete | AC-4/AC-6 |

## 5. General Checks

| ID | Check | Pass criterion | Trace |
|---|---|---|---|
| P0-CM-01 | Commit and evidence completeness | Documents record SHA/worktree; core findings have `path:line` or test nodes; no unowned critical unknown | FR-1/AC-1 |
| P0-CM-02 | No production-model/migration drift | Diff contains no production execution refactor, Agent/Run JSONB rewrite, or Alembic migration | FR-3/scope |
| P0-CM-03 | Secret scan of fixtures and outputs | No tokens, connection strings, or customer PII; exceptions require security review and minimization | FR-3/NFR |
| P0-CM-04 | Baseline determinism | Node-level results agree; every skip/xfail/flaky case has reason, owner, and disposition | AC-4 |
| P0-CM-05 | Phase 1 entry checklist | Identifiers, coverage, duration, defects, and per-phase regression map are complete; zero P0/P1 blockers | FR-5/FR-6/AC-6 |

## 6. Regression Scope

- Existing `test_runtime_engine.py`, `test_runtime_postgres.py`, `test_runtime_availability.py`, and `test_runtime_scope.py`;
- Agent Config draft/publish/version/rollback, Run API, event/SSE, memory injection, and model/tool-gateway tests;
- Existing CI lint, migration checks, and affected backend suites still apply; adding no migration does not exempt repository migration checks.

## 7. Defect Levels and Exit Criteria

| Level | Definition | Handling |
|---|---|---|
| P0 blocker | Fixture secret leak; test destroys data; current code cannot build or core execution cannot be measured | Stop later phases, fix, and rebuild a clean baseline |
| P1 severe | Core path lacks evidence; non-deterministic results; valid historical configuration fails; weak assertions hide failure | Close and regress before Phase 1 |
| P2 normal | Non-critical coverage gap, incomplete document mapping, explainable performance variance | May proceed with owner/deadline after review |
| P3 minor | Formatting, naming, or non-critical report readability | Schedule a fix |

**Exit criteria**: all P0-UT/IT/CM pass; AC-1–AC-6 reproduce on the target commit; two runs agree at node level; no new applicable regression failures; every skip/xfail is explained; zero open P0/P1. Unavailable environments are `pending_env`, never passed.
