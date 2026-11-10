# Phase 0 · Baseline and Inventory — Technical Design

> Status: Pending review (implementation has not started)
> Created: 2026-11-02
> Basis: `02-requirements.md` (FR-1–FR-6, AC-1–AC-6), architecture Sections 15 and 17
> Verification boundary: planning inspected `integration` at `fb3f424`; execution must record the SHA and working-tree state again on a clean target commit

## Change Overview

| Layer | File | Change |
|---|---|---|
| Baseline artifact | `docs/requirement/agent-execution-platform-v2/phase-0-baseline-inventory/baseline/runtime-dependencies.md` (+`.en.md`) | Target commit, dependency graph, interfaces, and test mappings |
| Baseline artifact | `baseline/run-lifecycle-events.md` (+`.en.md`) in the same directory | Actual transitions, event semantics, races, and differences from target behavior |
| Baseline artifact | `baseline/configuration-compatibility.md` (+`.en.md`) in the same directory | Fixture provenance, coverage matrix, compatibility results, and existing defects |
| Baseline artifact | `baseline/regression-baseline.md` (+`.en.md`) in the same directory | Commands, environment, two runs, coverage/duration, and CI links |
| Baseline artifact | `baseline/refactoring-checklist.md` (+`.en.md`) in the same directory | Identifiers, phase checks, open items, and entry conditions |
| Tests | `backend/tests/test_runtime_baseline.py` | Freeze Worker/Engine result, event, and error behavior; split by current conventions if needed |
| Tests | `backend/tests/test_runtime_postgres.py` | Add missing lifecycle/race baselines without duplicating existing coverage |
| Tests | `backend/tests/test_agent_config_execution_compat.py` | Historical configuration, published-snapshot, and boundary-fixture compatibility |
| Test data | `backend/tests/fixtures/agent_execution_baseline/` | Sanitized, versioned, minimal JSON fixtures and inventory |
| Current dependencies | `core_platform/agent_runtime/{engine,worker,repository,schemas}.py` | Read-only inspection; no production refactoring in this phase |
| Current composition | `applications/platform_runtime/{runtime_factory,runtime_composition}.py`, `business_capabilities/agent_config/service.py`, `extension_contracts/runtime.py` | Read-only inspection and interface mapping |

**Data model and migrations**: no new table, column, or backfill; no migration number is assigned. Do not alter existing `agents.draft`, `agent_versions.config`, or `runtime_runs.config` structures to fit a future model.

## Current Execution Dependency Baseline (Revalidate During Execution)

```mermaid
flowchart LR
    API[Run API / SSE] --> Repo[RunRepository]
    Repo --> DB[(runtime_runs / runtime_events / runtime_conversations)]
    Worker[RuntimeWorker] --> Repo
    Worker --> Factory[RuntimeFactory.for_run]
    Factory --> Engine[RuntimeEngine]
    Factory --> Gateway[Model/Tool gateways and RuntimeBindings]
    Worker --> Memory[MemoryInjectionPort]
    Engine --> Emit[emit callback]
    Emit --> Repo
    Emit --> Notify[transient model.delta notifier]
```

Add exact references for actual API, Composition, and test entry points, distinguishing construction-time from per-Run dependencies. Record compatibility exports under `modules/` if present, but do not treat them as a second implementation.

## Core Flows

### 1. Pin the Commit and Build Inventory Evidence

```text
Confirm clean target commit and SHA
  → Run existing affected tests and preserve raw results
  → Trace API/Composition to Worker/Repository/Factory/Engine in both directions
  → Register interfaces, owners, events, data access, and test mappings
  → Before later phases, compare the new SHA and append deltas rather than overwriting history
```

Every finding includes `path:line` or a test node as evidence. Use `unknown` where verification is impossible; never infer current support from target architecture.

### 2. Freeze the Actual Run and Event State Machine

Inspect at least these current paths:

| Start | Trigger | Currently recorded outcome/behavior |
|---|---|---|
| `queued` | Successful `claim` | `running`, with owner/lease set |
| `running` | Normal return | `completed`, with output/history and `run.completed` |
| `running` | RuntimeFault/general exception/execution timeout | `failed`, mapped to existing error codes |
| `queued` | Cancel | Directly `cancelled` |
| `running` | Cancel | Cancellation request; Worker/Repository cooperate toward `cancelled`; late completion cannot overwrite it |
| `running` | Lease loss or reaper | `failed(worker_lost)` or the corresponding existing behavior |
| `queued` | Queue deadline/reaper | `failed(queue_timeout)`; freeze cancellation precedence from code |
| Any terminal state | Late finish/duplicate event | Repository conditional updates reject illegal transitions; retain test evidence |

The event inventory separately records durable events and transient `model.delta` notifications, sequence origins, SSE `after` replay semantics, terminal-event fields, and secret boundaries. If this table differs from actual code, revise it with evidence before writing tests.

### 3. Build Configuration Compatibility Fixtures

```text
Extract and sanitize authorized historical draft/published configs
  + construct default, minimal, maximum-boundary, unknown/invalid-field fixtures
  → Inventory fixture version, source category, covered fields, expected result (never secrets)
  → AgentConfig.model_validate + existing publish/snapshot paths
  → Compare unchanged source input, existing defaults, and error semantics
```

Fixtures contain no real tokens, URL credentials, customer content, or identifiable personal information. If a real sample cannot enter the repository, retain only field shapes and sanitized values and document the evidence limitation.

### 4. Establish and Measure the Regression Baseline

- Run existing `test_runtime_engine.py`, `test_runtime_postgres.py`, `test_runtime_availability.py`, `test_runtime_scope.py`, and Agent Config/API/SSE tests before filling gaps, avoiding duplication.
- Mock models/tools cover success, empty output, budgets, errors, and cancellation; PostgreSQL cases construct lease/cancellation/terminal races directly rather than waiting in real time.
- Measure with the project's existing coverage tooling; do not add meaningless tests for a percentage. Report behavioral coverage alongside line coverage.
- Execute twice in the same clean environment; preserve full commands, UTC timestamps, dependency versions, pass/fail/skip/xfail counts, and duration. Add CI links when available.

### 5. Freeze Identifiers and the Checklist

- Initial production identifier: `(react, native, v1)`; Engine, Protocol, and Adapter dimensions are named independently, not by Python class name.
- LocalTestAdapter uses distinct test Engine/Protocol identifiers that do not collide with production React; exact values are registered during Phase 1 contract review.
- Initially `Run = one Execution attempt`; Phase 1 defines the mapping between `execution_id` and the existing Run ID without creating a Task table.
- Map checklist entries to Phase 1–7 compatibility, rollback, migration, security, and regression requirements, identifying mandatory baseline tests.

## Configuration

No settings or AgentConfig fields are added. Tests provide model, lease, event-cursor, and similar inputs through existing constructors/fixtures without introducing production flags.

## Model Invocation Path

Baseline tests use the existing model-gateway and mock/demo boundaries and never call external paid models directly. Real models may be used only for separately labeled non-blocking compatibility observations, never in the deterministic baseline. Usage remains in existing `gateway_calls`; no new usage model is introduced.

## Test Overview

| Layer | Cases |
|---|---|
| Unit | Engine result/error/budget, Worker invocation shape, configuration normalization and invalid inputs |
| Integration | PostgreSQL lifecycle/lease/cancellation/terminal states, event persistence and SSE cursors, draft→publish→snapshot |
| Regression | Existing runtime, agent config, API/SSE suites; two-run and skip/xfail differences |
| Non-functional | Coverage/duration baseline, fixture secret scanning, test determinism |

See `04-test-plan.md` for detailed cases.

## Rollout and Rollback

- Tests and documents can merge independently, with no database migration or production-path switch.
- If new tests expose existing failures, do not skip them; use the defect-decision process. Revert only the affected test/document changes to roll back this phase.
- Any necessary production-defect fix requires a separate small commit, before/after evidence, and a baseline update; do not mix it into bulk inventory changes.
- Phase 1 entry requires AC-1–AC-6, zero unresolved P0/P1 items, and confirmation that target-SHA deltas were reviewed.
