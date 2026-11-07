# Phase 0 · Baseline and Inventory — Acceptance Plan

> Status: Pending execution (before Phase 1 starts)
> Created: 2026-11-02
> Basis: `01-business-goals.md` (G1–G3, success metrics), `02-requirements.md` (AC-1–AC-6); test basis in `04-test-plan.md`

## 1. Acceptance Objectives and Organization

Confirm that the baseline is **factual and traceable**, compatibility fixtures **load reproducibly**, and regression results are **deterministic and reusable**, with no P0/P1 baseline blockers before Phase 1.

| Role | Responsibility |
|---|---|
| Architecture lead | Chair review; decide dependency boundaries, actual/target differences, and identifiers |
| Product owner | Confirm the no-manual-migration promise for existing Agents and disposition P2 leftovers |
| QA | Execute AC, compare two runs, classify defects, and archive evidence |
| Engineering lead | Provide clean environments, CI/coverage/duration data, and open-item fixes |
| Security representative | Review historical-fixture sanitization and report secret boundaries |

## 2. Acceptance Environments and Prerequisites

| Environment | Purpose |
|---|---|
| Clean backend worktree at the pinned commit | Code evidence, document, and diff inspection |
| Existing project PostgreSQL integration environment | Lifecycle, event, configuration-publication, and SSE scenarios |
| Clean CI environment (twice on one commit) | Reproducibility, coverage, and duration baseline |

**Prerequisites**: all applicable `04-test-plan.md` cases pass; zero open P0/P1; historical fixtures are authorized, sanitized, and inventoried; every `pending_env` has a required environment and owner rather than an implicit waiver.

## 3. Functional Acceptance Checklist (AC-1–AC-6)

| # | Acceptance steps | Pass criterion |
|---|---|---|
| A1 | Trace Run API/Composition through create, claim, execute, events, and terminal state; sample every dependency-graph finding | AC-1: every core entry and edge links to code/tests; owners and test mappings are complete; no critical unknown is unowned |
| A2 | Execute or inspect success, queued/running cancellation, timeout, lease loss, duplicate finish, and late events against the lifecycle inventory | AC-2: every reachable path has actual behavior and evidence; target differences are separate; terminal protection has no counterexample |
| A3 | Run all valid/invalid historical configuration fixtures and draft→publish→snapshot paths; scan fixtures/reports | AC-3: valid fixtures load under current rules, invalid fixtures fail explicitly, sources remain unchanged, cross-tenant reads fail, and scans find no secrets |
| A4 | Run the baseline twice in the same clean CI environment and compare nodes, skips/xfails, counts, and reports | AC-4: node-level results agree; every exception has a reason/owner; raw CI logs and commands are traceable; weak assertions hide nothing |
| A5 | Review identifiers, LocalTestAdapter naming constraints, Phase 1 examples, and Run/Execution/Task terminology | AC-5: `(react,native,v1)` is consistent; Run is one Execution; no Task dual-table, Worker branch, or undecided naming |
| A6 | Inspect baseline report, defect inventory, and Phase 1–7 refactoring checklist; hold the entry review | AC-6: commands/environment/coverage/duration/CI/regression mapping are complete; zero P0/P1; other items have owners and deadlines |

Record executor, date, target SHA, environment, setup, actual result, verdict, test nodes, and CI/screenshot links for every scenario.

## 4. UAT Review (Architecture and Agent Configuration Representatives)

- The architecture representative confirms the graph answers “which entry points change for a new Adapter?” and does not present target architecture as current implementation.
- The Agent configuration representative samples typical historical drafts and published versions, confirming no manual Engine field is required in this phase.
- QA and engineering agree that baseline failures cannot automatically become “acceptable regressions” in later phases.

## 5. Business Metric Acceptance

| Metric | Baseline | Target | Measurement |
|---|---|---|---|
| Core-module inventory coverage | No unified inventory | 100% | Check every FR-1 module for owner, call relationships, data/events, and test mapping; any omission fails |
| State-transition and public-event semantic coverage | Scattered | 100% | Generate the reachable-path list from code and reconcile every item with A2 evidence; unknowns do not count as covered |
| Included configuration-fixture load rate | Measured in Phase 0 | 100%; existing failures require decisions | Execute every versioned fixture with a fixed denominator; never remove failures to improve the rate |
| Two-run reproducibility | To be measured | 100% node-result agreement | Compare complete node IDs and outcomes; review skip/xfail/flaky separately |
| Baseline blockers | Not consolidated | P0/P1=0 | Reconcile defect tracker and baseline open items; other items need owner, affected phase, and deadline |

## 6. Compliance Checks

| # | Check | Verdict requirement |
|---|---|---|
| C1 | Fixtures, logs, and reports contain no plaintext secrets, connection strings, or identifiable customer data | Veto |
| C2 | No applied migration, existing configuration, historical Run, or production execution path was changed | Must pass |
| C3 | Required tests do not call external paid models; skip/xfail and pending_env are recorded honestly | Must pass |
| C4 | Baseline binds to an explicit commit SHA; later phases have owners and entry conditions for incremental review | Must pass |
| C5 | Baseline tests/documents revert independently; any production-defect fix is isolated and the baseline updated | Must pass |

## 7. Pass Criteria and Sign-Off

- **Pass**: A1–A6 and all five business metrics pass; C1–C5 pass; zero P0/P1 leftovers; Phase 1 entry checklist is complete.
- **Conditional pass**: only P2/P3 items that do not affect Phase 1 contract design remain, each with owner, deadline, and impact boundary; security, fixture compatibility, and determinism cannot be waived.
- **Fail**: any veto, insufficient core coverage, deleted/rewritten valid fixtures, non-deterministic runs, or open P0/P1; re-run affected items and the complete baseline after remediation.

Produce the Phase 0 Acceptance Report with AC evidence, baseline metrics, compliance checks, leftovers, target SHA, and sign-off (architecture/product/QA/engineering/security).
