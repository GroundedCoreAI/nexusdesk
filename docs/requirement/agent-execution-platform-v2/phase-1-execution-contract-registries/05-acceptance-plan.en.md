# Phase 1 · Execution Contracts and Registries — Acceptance Plan

> Status: Pending review / Pending implementation
> Created: 2026-11-02
> Basis: `01-business-goals.md` (G1–G4 and success metrics), `02-requirements.md` (AC-1–AC-8); execution follows `04-test-plan.md`

## 1. Acceptance Objectives and Organization

Confirm that contracts and registries are **independently extensible, lifecycle-correct, deterministic in tests, and have zero impact on the current production path**, with sign-off from product, QA, engineering, and an Adapter representative. This is an acceptance plan, not a claim that functionality is implemented or accepted.

| Role | Responsibility |
|---|---|
| Product owner | Facilitate acceptance; confirm scope and later-phase boundaries; sign off P2 residual disposition |
| QA | Execute A1–A8, verify test evidence and determinism, and provide regression conclusion and defect severity |
| Engineering lead | Supply implementation, dependency-direction, no-migration/zero-wiring evidence, metric measurements, and fixes |
| Adapter development representative | Perform UAT with an independent test Adapter and confirm no common-contract or Worker changes are needed |

## 2. Acceptance Environment and Prerequisites

| Environment | Purpose |
|---|---|
| CI / local pure Python | All contract, registry, and LocalTestAdapter scenarios; no external Engine, credential, or network dependency |
| Dedicated PostgreSQL regression | Verify existing Runtime/API/SSE behavior and unchanged migration head |
| Document and code review | Check paths, versions, dependency boundaries, error redaction, and Phase 2 non-goals |

**Prerequisites**: Every case in `04-test-plan.md` passes with no open P0/P1; provide the CI run, test logs, changed-file list, and `alembic heads` evidence. Use dedicated acceptance data/test tenants and no real customer input or credentials.

## 3. Functional Acceptance Checklist (AC-1–AC-8)

| # | Acceptance steps | Pass criterion |
|---|---|---|
| A1 | For AC-1: run positive/negative parameterized cases for all six DTO groups and demonstrate that mutating one instance's default collection does not affect another | Every invalid input is rejected, versions/IDs are correct, the other default is unchanged, and evidence links to P1-UT-01–02 |
| A2 | For AC-2: select success and streaming scripts and execute capabilities→start→stream→collect, checking identity, events, and result | Five methods and identity properties conform, events are ordered, completed output matches the script, and no task dangles |
| A3 | For AC-3: start a long-running scenario, cancel twice, release the success gate, and inject late events | Both cancels are safe; the sole result is cancelled with no success output; late events create no valid new event or second terminal state |
| A4 | For AC-4: exercise ten error categories and capability declarations, placing `secret-marker` in raw exceptions/details | category/code/retryable match the matrix; undeclared capabilities are false; all caller-visible output omits the marker |
| A5 | For AC-5: the Adapter representative independently adds a test Engine, two Protocols, and versioned implementations, reuses the common suite, and resolves twice | No common-contract/Worker change is needed; valid combinations pass; resolutions are independent identity-matching instances |
| A6 | For AC-6: execute unknown ID, unknown version, undeclared combination, disabled, conflicting duplicate, and identity-mismatched factory cases | Every case fails closed with stable error codes and no latest, alternate-version, or other-Engine fallback |
| A7 | For AC-7: run duplicate/late events, timeout, resource exhaustion, and simulated process failure twice and inspect asyncio tasks | Semantics repeat, anomalous events are identifiable, timeout/failure categories are correct, and there is no external dependency or pending task |
| A8 | For AC-8: inspect production Worker/Factory diff, run existing Runtime/API/SSE regression, and query migration head | No production wiring; old APIs/events/states show zero diff; head is `0052` and regression is green |

Every scenario record must include executor, date, environment, fixtures, actual result, verdict, and CI/log link. A failed item cannot be marked passed or waived merely because it concerns the test implementation.

## 4. UAT Decision (Adapter Development Representative)

- A test Adapter can be completed using only common contracts and registry interfaces, without understanding or modifying Worker, Repository, or RuntimeFactory.
- Success, error, and cancellation diagnostics locate configuration/protocol problems without exposing raw credentials, config, or customer content.
- Simulated process failure in LocalTestAdapter is explicitly distinguished from real process supervision in Phase 4; acceptance records must not conflate them.

## 5. Business Metric Acceptance

| Metric | Baseline | Target | Measurement |
|---|---|---|---|
| Contract branch and five-method coverage | To be inventoried in Phase 0 | 100% of defined contract branches and all five methods have passing cases | Export the P1-UT/IT traceability matrix and CI result; check each method, and fail if any is missing |
| Valid/invalid combination resolution accuracy | To be inventoried in Phase 0 | 100% valid resolution and 100% invalid rejection in the fixed matrix | Cover at least one Engine, two Protocols, two versions, and every invalid category; retain every row result |
| LocalTestAdapter deterministic scenario pass rate | To be inventoried in Phase 0 | 100% pass in both rounds for all specified scenarios with no pending task | Run twice consecutively in one environment and retain separate logs and task-cleanup assertions |
| Common-contract/Worker changes for a new Adapter | To be measured in Phase 0 | 0 changes | Review the test-only Adapter changed-file list and common-suite reuse evidence |
| Impact on existing Run latency and error rate | To be measured in Phase 0 | Zero production behavioral diff and no added execution overhead | Use zero production-wiring diff and existing regression as evidence; do not invent performance figures here—measure them in Phase 0/2 |

## 6. Compliance Checks

| # | Check | Decision |
|---|---|---|
| C1 | DTOs, registries, errors, and logs contain no plaintext credential, connection string, raw stack, or customer input | Veto item |
| C2 | Tenant boundaries, Run/Extension public ports, Agent snapshots, HTTP/SSE, and table structures remain unchanged; head remains `0052` | Must pass |
| C3 | The new path is absent from production composition; rollback only reverts unwired code and needs no migration or data repair | Must pass |
| C4 | Effective capabilities are not conflated with Declared capabilities, and registries do not perform authorization, scheduling, or process supervision | Must pass |

## 7. Pass Criteria and Sign-off

- **Pass**: A1–A8 all pass; the first four engineering hard metrics are met; C1–C4 all pass; no P0/P1 remains.
- **Conditional pass**: Only P2/P3 issues remain, each with an owner and deadline; AC, production compatibility, and sensitive-information issues cannot be waived.
- **Fail**: Any veto item, AC, or hard metric fails; after fixes, rerun affected items and related regression.
- **Baseline note**: Values marked “to be measured/inventoried in Phase 0” must not later be presented as existing measurements; this phase evaluates targets with a fixed test matrix, while production performance baselines remain for Phase 0/2.

Produce the Phase 1 Acceptance Report containing AC records, metric matrix, CI/migration evidence, compliance results, residual list, and the sign-off below.

| Role | Name | Date | Conclusion | Signature |
|---|---|---|---|---|
| Product owner | To be completed | To be completed | To be completed | To be completed |
| QA | To be completed | To be completed | To be completed | To be completed |
| Engineering lead | To be completed | To be completed | To be completed | To be completed |
| Adapter development representative | To be completed | To be completed | To be completed | To be completed |
