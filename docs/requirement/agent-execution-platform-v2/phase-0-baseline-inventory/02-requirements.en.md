# Phase 0 · Baseline and Inventory — Requirements

> Status: In progress (implementation started on 2026-11-07)
> Created: 2026-11-02
> Basis: `01-business-goals.md` (G1–G3), architecture Section 17 (Phase 0)

## User Stories

**US-1 (Platform developer)**: As an execution-platform developer, I want code-verified call and state diagrams so that contract extraction does not miss implicit dependencies.

**US-2 (QA)**: As QA, I want repeatable current-behavior tests and recorded outcomes so that later refactoring regressions are identifiable.

**US-3 (Tenant administrator)**: As an administrator of existing Agents, I want historical drafts and published versions to keep loading so that platform evolution does not require bulk manual edits.

**US-4 (Architecture reviewer)**: As a reviewer, I want one record of identifiers, scope, and open questions so that every phase uses the same terminology and entry conditions.

## Functional Requirements

### FR-1 Target Commit and Dependency Inventory

| Item | Description |
|---|---|
| Trigger | At Phase 0 start; incremental review before each later phase |
| Input | Clean target commit, backend modules and tests, related deployment/configuration entry points |
| Output | Commit SHA, module dependency graph, public/internal interfaces, owners, test mappings, and delta records |
| Execution | Primarily static code inspection with minimal runtime verification; never infer current state solely from old documents |
| Failure | Mark unverifiable dependencies `unknown` with an owner; items blocking Phase 1 cannot remain blank |

### FR-2 Run Lifecycle and Event-Semantics Baseline

| Item | Description |
|---|---|
| Trigger | During inventory and before regression-test design |
| Input | Repository/Worker/Engine, API/SSE code, and existing tests |
| Output | Every reachable transition, terminal-state protection, cancellation/timeout/lease-loss flow, event type/order/replay, and transient-event differences |
| Execution | Cross-check code paths against test evidence; do not substitute an ideal state diagram for actual behavior |
| Failure | Where code and documents differ, record actual behavior from code/runtime evidence and list target behavior separately |

### FR-3 Agent Configuration and Published-Snapshot Compatibility Fixtures

| Item | Description |
|---|---|
| Trigger | While establishing the regression baseline |
| Input | Authorized sanitized historical configurations, published snapshots, and default/boundary/invalid constructed fixtures |
| Output | Versioned fixtures, expected normalized results, load/publish/snapshot assertions, and a coverage inventory |
| Execution | Load automatically through existing `AgentConfig` and publication paths without writing future Engine defaults into source fixtures |
| Failure | Record existing load failures separately and retain fixtures; invalid fixtures fail explicitly; no sensitive source text enters the repository |

### FR-4 Existing Execution-Behavior Regression Baseline

| Item | Description |
|---|---|
| Trigger | Establish during Phase 0; run the applicable subset after later changes |
| Input | Deterministic mock models/tools, PostgreSQL fixtures, configuration fixtures, and event consumers |
| Output | ReAct success/failure/budget, queue/lease/cancellation/terminal-state, event/SSE, configuration compatibility tests, and a baseline report |
| Execution | Repeatable in CI; no real waiting for time-based cases and no external service on required paths |
| Failure | Record reasons for failures, skips, xfails, and flaky tests; never weaken assertions to obtain a green result |

### FR-5 Identifiers and Initial Migration Conventions

| Item | Description |
|---|---|
| Trigger | Before Phase 1 contract authoring |
| Input | Architecture Engine/Protocol/Adapter examples and the existing React implementation |
| Output | Initial identifier `(react,native,v1)`, LocalTestAdapter test-identifier convention, version format, and Run-as-one-Execution explanation |
| Execution | Freeze after architecture review; register and compatibility-check new identifiers rather than adding Worker branches |
| Failure | Resolve naming conflicts or unclear semantics in Phase 0; implementation must not make implicit decisions on open items |

### FR-6 Baseline Metrics and Refactoring Checklist

| Item | Description |
|---|---|
| Trigger | After regression tests stabilize and before Phase 0 acceptance |
| Input | Two clean-environment results, coverage, test duration, known defects, and downstream design questions |
| Output | Reproducible commands, test/coverage/duration baseline, defect inventory, per-phase regression map, and refactoring checklist |
| Execution | Run twice on the same commit and environment; record environmental differences and never record missing data as zero |
| Failure | Locate or isolate non-deterministic results with explicit labels; unresolved P0/P1 items block Phase 1 |

No runtime configuration flag or database field is added in this phase.

## Non-Functional Requirements

- **Reproducibility**: record commit, commands, environment, and fixture versions; results do not depend on external models or real waits.
- **Compatibility**: do not alter existing configuration JSONB, Run tables, or public APIs for a future model; no migration in this phase.
- **Security**: sanitize and minimize fixtures; no tokens, connection strings, or identifiable customer data in fixtures, logs, or reports.
- **Maintainability**: assert reviewed public/critical internal behavior rather than coupling tests to irrelevant private details.
- **Performance**: use existing CI resources and measure actual duration; review budget exceptions separately rather than inventing targets.

## Acceptance Criteria

| # | Scenario | Expected |
|---|---|---|
| AC-1 | Inspect core execution and configuration modules at the pinned commit and trace one Run from creation to terminal state | The graph covers every FR-1 entry; every edge links to code; no critical unknown lacks an owner |
| AC-2 | Compare code and tests for success, cancellation, timeout, lease loss, and repeated terminal-state scenarios | Lifecycle/event inventory covers every reachable path, separates actual from target behavior, and includes evidence |
| AC-3 | Load every sanitized historical, default, boundary, and invalid Agent configuration fixture | Valid fixtures follow existing rules; invalid fixtures fail explicitly; sources are not migrated or rewritten; secret scanning passes |
| AC-4 | Run the baseline suite twice in a clean environment on one commit and inspect CI evidence | Results agree; every skip/xfail/flaky case is explained; failures are not hidden by weaker assertions |
| AC-5 | Use frozen identifiers in Phase 1 examples and review Run/Execution terminology | Examples consistently use `(react,native,v1)`; no Worker Engine branch or competing terminology; open names have decisions |
| AC-6 | Inspect the baseline report and refactoring checklist during the Phase 1 entry review | Commands, coverage, duration, defects, and regression mappings are complete; zero P0/P1 blockers; other items have owners and deadlines |
