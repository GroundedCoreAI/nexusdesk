# Phase 0 · Baseline and Inventory — Business Goals

> Status: In progress (implementation started on 2026-11-07)
> Created: 2026-11-02
> Basis: `docs/architecture/agent-execution-platform-v2.md`, Sections 15 and 17 (Phase 0); all later phases depend on these findings
> Estimated effort: ~1–1.5 weeks
> Dependencies: target `integration` commit builds; existing PostgreSQL test environment is available

## Problems to Solve

### Problem 1: Refactoring evidence is scattered through implementation

`core_platform/agent_runtime/worker.py` directly holds a `runtime`; `applications/platform_runtime/runtime_factory.py` constructs the fixed `RuntimeEngine`; `repository.py` coordinates Run persistence, leases, and events. Without a dependency map verified against the target commit, extracting Adapters and an Orchestrator could miss compatibility entry points, memory injection, or test doubles.

### Problem 2: Compatibility promises lack repeatable evidence

Run states, cancellation races, event semantics, and Agent draft/publication snapshots are distributed across code and existing tests. There is no unified baseline of fixtures and outcomes for this refactoring, so later claims of unchanged behavior cannot distinguish pre-existing defects from regressions.

### Problem 3: Extension decisions lack a single baseline

Engine/Protocol/Adapter identifiers, the initial Run/Execution relationship, and phase entry conditions must be frozen. Otherwise phases may independently invent names, states, or configuration mappings.

## Business Goals

| Goal | Description |
|---|---|
| G1: Establish a verifiable current-state baseline | Produce a dependency map, Run lifecycle, event semantics, and configuration compatibility inventory for the target commit, with every finding linked to code or tests |
| G2: Establish regression safeguards | Use deterministic automated tests to freeze critical existing ReAct, Worker, repository, SSE, and configuration-loading behavior |
| G3: Freeze downstream design inputs | Standardize identifiers and phase entry conditions; record coverage, performance, and known-defect baselines for planning and acceptance |

## Success Metrics

| Metric | Current baseline | Target |
|---|---|---|
| Core-module inventory coverage | No unified inventory | 100% of Runtime Engine, Worker, Repository, Factory, Composition, Agent Config, extension contracts, and API/SSE entry points have owners, call relationships, and test mappings |
| Run-state and event-semantic coverage | Scattered across code and tests | 100% of code-reachable transitions, cancellation/timeout/lease-loss paths, and public event types are registered; unknowns are explicit |
| Legacy Agent configuration fixture pass rate | To be measured | 100% of included sanitized production samples and boundary fixtures load; failed fixtures receive existing-defect records rather than silent removal |
| Baseline regression reproducibility | To be measured | Two consecutive runs in the same clean environment agree; every skip/xfail is explained; CI retains commands and result links |
| Open baseline questions for later phases | Not consolidated | Zero unresolved P0/P1 blockers; every other item has an owner, affected phase, and decision deadline |

## Scope

**Included**:

- Pin the target commit and inventory execution, configuration, event, and composition dependencies;
- Record Run lifecycle, event fields, cancellation/lease-loss/terminal-state semantics;
- Build sanitized configuration and published-snapshot compatibility fixtures;
- Add current-behavior regression tests and measure coverage, duration, and known flaky/skipped tests;
- Freeze initial identifiers, the Run-as-one-Execution convention, and the refactoring checklist.

**Excluded**:

- Execution Contract, Registry, Orchestrator, or React Adapter implementation (Phases 1–2);
- Multi-Engine configuration, Runtime Host, Codex, security, and scale features (Phases 3–7);
- Production-code refactoring, historical-data migration, or improvement of existing functional metrics;
- Rewriting existing tests under the name of baselining to conceal regressions.

## Risks and Constraints

- **Baseline staleness**: continued branch evolution can invalidate findings; record the commit SHA and re-check differences before each phase.
- **Unrepresentative fixtures**: synthetic data may miss historical field combinations; include authorized sanitized snapshots and record their provenance and coverage limits.
- **Pre-existing defects**: baseline tests may expose problems; log and review them rather than changing behavior without a decision.
- **Coverage misuse**: line coverage does not prove behavioral compatibility; freeze states, events, errors, and configuration semantics as well.
- **Compatibility**: this phase adds tests and documents only. Any necessary existing-defect fix is isolated, independently reversible, and reflected in the baseline.
