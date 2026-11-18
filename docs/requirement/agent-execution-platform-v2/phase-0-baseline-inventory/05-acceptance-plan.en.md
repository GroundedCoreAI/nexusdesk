# Phase 0 · Baseline and Inventory — Acceptance Plan

> Status: Pending execution (before Phase 1 starts)
> Created: 2026-11-02
> Revised: 2026-11-17 (aligned to the minimal-core-team acceptance standard: single acceptance owner; removed multi-role sign-off, standalone UAT, and the business-metric table; technical criteria and hard gates unchanged)
> Revised: 2026-11-18 (scope-limited acceptance revision: performance/capacity/p50/p95/C11 latency, matched pairs, sample counts, CI provenance/final-PR-head CI double-run/CI run URL, real or authorized historical samples, and multi-sample/large-sample-data-volume requirements are no longer stage-acceptance gates and remain only as historical context or explicit out-of-scope notes; functional correctness, tenant isolation, Secret handling, data integrity, migration, terminal-state semantics, cleanup, zero P0/P1, and a single acceptance-owner record remain gates; high-risk enablement stays separate)
> Basis: `01-business-goals.md` (G1–G3, success metrics), `02-requirements.md` (AC-1–AC-6); test basis in `04-test-plan.md`

## 0. 2026-11-18 Scope-Limited Acceptance Revision (supersedes later gate wording)

This section records the 2026-11-18 scope-limited acceptance revision. It takes precedence over any later wording that treats the items below as acceptance gates, veto items, "fail" conditions, or mandatory evidence; the original text is retained as historical context but is superseded by this section.

- **No longer stage-acceptance gates** (retained only as historical context or explicit out-of-scope notes): performance/capacity p50/p95/C11 latency and duration statistics; matched pairs and sample counts; CI provenance, final-PR-head CI double-run, and CI run URL; real or authorized historical samples; multi-sample/large-sample-data-volume requirements. Accordingly, §2's "clean CI twice on one commit" and "historical samples authorized/sanitized/inventoried" prerequisites, A3's "all historical samples," A4's "CI double-run determinism," and A6's coverage/duration/CI mapping statistics are not stage blockers.
- **Still stage-acceptance gates**: functional correctness (A1–A6 behavior and evidence), tenant isolation, Secret handling, data integrity, migration and protected-file zero drift, terminal-state semantics, side effects/cleanup, zero P0/P1, and a single acceptance-owner record; high-risk enablement still requires separate security and operations approval.
- **Historical numbers**: values in 06/07 such as 310 nodes, zero XPASS, coverage/duration, 5/5 and 16/16 are retained as historical evidence, are not rewritten, and are neither pass nor blocker conditions for this stage.

## 1. Acceptance Scope and Responsibility

Confirm that the baseline is **factual and traceable**, compatibility fixtures **load reproducibly**, and regression results are **deterministic and reusable**, so that Phase 1 can start with no P0/P1 baseline blockers.

Apply minimal-core-team acceptance: a single acceptance owner, who may execute and reach the verdict personally; where assistance is needed, an executor may be designated and may be the same person. No architecture/product/QA/engineering/security multi-role responsibility table, no multi-role sign-off sheet, and no standalone UAT round. Developer self-verification proves conformance to the written requirements only and does not claim real-user or independent business acceptance.

Passing phase acceptance does not authorize later phases or any high-risk capability; enabling a high-risk capability requires a separate independent security and operations approval record.

## 2. Acceptance Environments and Prerequisites

| Environment | Purpose |
|---|---|
| Clean backend worktree at the pinned commit | Code evidence, document, and diff inspection |
| Existing project PostgreSQL integration environment | Lifecycle, event, configuration-publication, and SSE scenarios |
| Clean CI environment (twice on one commit) | Reproducibility, coverage, and duration baseline [2026-11-18: no longer a stage-acceptance gate; retained as historical context; see §0] |

**Prerequisites**: all applicable `04-test-plan.md` cases pass; zero open P0/P1; historical fixtures are authorized, sanitized, and inventoried [2026-11-18: "historical fixtures authorized/sanitized/inventoried" is no longer a stage-acceptance gate; retained as historical context; see §0]; every `pending_env` has a required environment and owner rather than an implicit waiver.

## 3. Functional Acceptance Checklist (AC-1–AC-6)

| # | Acceptance steps | Pass criterion | Trace |
|---|---|---|---|
| A1 | Trace Run API/Composition through create, claim, execute, events, and terminal state; sample every dependency-graph finding | AC-1: every core entry and edge links to code/tests; owners and test mappings are complete; no critical unknown is unowned | FR-1 |
| A2 | Execute or inspect success, queued/running cancellation, timeout, lease loss, duplicate finish, and late events against the lifecycle inventory | AC-2: every reachable path has actual behavior and evidence; target differences are separate; terminal protection has no counterexample | AC-2 |
| A3 | Run all valid/invalid historical configuration fixtures and draft→publish→snapshot paths; scan fixtures/reports | AC-3: valid fixtures load under current rules, invalid fixtures fail explicitly, sources remain unchanged, cross-tenant reads fail, and scans find no secrets | AC-3 |
| A4 | Run the baseline twice in the same clean CI environment and compare nodes, skips/xfails, counts, and reports | AC-4: node-level results agree; every exception has a reason/owner; raw CI logs and commands are traceable; weak assertions hide nothing | AC-4 |
| A5 | Review identifiers, LocalTestAdapter naming constraints, Phase 1 examples, and Run/Execution/Task terminology | AC-5: `(react,native,v1)` is consistent; Run is one Execution; no Task dual-table, Worker branch, or undecided naming | AC-5 |
| A6 | Inspect baseline report, defect inventory, and Phase 1–7 refactoring checklist; hold the entry review | AC-6: commands/environment/coverage/duration/CI/regression mapping are complete; zero P0/P1; other items have owners and deadlines | AC-6 |

> **2026-11-18 scope-limited revision**: A3's "all historical samples/sample counts," A4's "same-environment CI double-run determinism," and A5/A6's coverage/duration/CI mapping statistics are no longer stage-acceptance gates (retained as historical context or explicit out-of-scope notes; see §0). Functional correctness, tenant isolation, Secret handling, data integrity, migration, terminal-state semantics, and zero P0/P1 across A1–A6 remain gates. Historical test numbers are not rewritten.

Record executor, date, target SHA, environment, setup, actual result, verdict, test nodes, and CI/screenshot links for every scenario. Reference existing 06/CI evidence for automated scenarios rather than re-running them; failures, skips, and `pending_env` must not be written as pass.

## 4. Key Manual Checks (only non-automatable applicable items, at most 3–5)

| # | Check | Pass criterion |
|---|---|---|
| M1 | Read the dependency graph and answer "which entry points change for a new Adapter?" | The answer matches the current implementation; target architecture is not presented as current state |
| M2 | Sample typical historical drafts and published versions, confirming no manual Engine field is required | Existing Agents need no manual migration; the scope promise holds |
| M3 | Confirm baseline failures cannot automatically become "acceptable regressions" in later phases | Defect inventory and entry review carry explicit owners and boundaries |

## 5. Security, Data, and Release Hard Gates

| # | Check | Verdict | Trace |
|---|---|---|---|
| C1 | Fixtures, logs, and reports contain no plaintext secrets, connection strings, or identifiable customer data | Veto | AC-3 |
| C2 | No applied migration, existing configuration, historical Run, or production execution path was changed | Must pass | AC-6 |
| C3 | Required tests do not call external paid models; skip/xfail and pending_env are recorded honestly | Must pass | AC-4 |
| C4 | Baseline binds to an explicit commit SHA; later phases have owners and entry conditions for incremental review | Must pass | AC-6 |
| C5 | Baseline tests/documents revert independently; any production-defect fix is isolated and the baseline updated | Must pass | AC-6 |

## 6. Pass Criteria and Acceptance Record

- **Pass**: A1–A6 and C1–C5 all have evidence and pass; M1–M3 are complete or have equivalent evidence; zero P0/P1 leftovers; Phase 1 entry checklist is complete.
- **Conditional pass**: only P2/P3 items that do not affect Phase 1 contract design remain, each with owner, deadline, and impact boundary, confirmed by the acceptance owner in the record below; security and fixture compatibility cannot be waived. [2026-11-18: "determinism" is no longer a stage-acceptance gate and can no longer be used to veto or require a conditional waiver; see §0.]
- **Fail**: any veto, insufficient core coverage, deleted/rewritten valid fixtures, or open P0/P1; re-run affected items and the complete baseline after remediation. [2026-11-18: "non-deterministic runs" is no longer a fail condition; see §0.]
- **Release note**: passing phase acceptance does not authorize later phases or any high-risk capability.

Produce the Phase 0 Acceptance Report with AC evidence, compliance checks, leftovers, target SHA, verdict, and the single acceptance record below; multi-role sign-off is not required.

| Acceptance owner | Executor | Date | Target SHA | Decision | Evidence/residuals |
|---|---|---|---|---|---|
| JackChow (confirmed by the user, 2026-11-18) | WorkBuddy automated acceptance execution | 2026-11-18 | `5170e140f10b117549cf54ba400131f5d7f95f69` | **PASS (scope-limited)** | `../11-scope-limited-acceptance-record-20261118.md` §7; evidence `20261118T125822Z.tar.gz` |
