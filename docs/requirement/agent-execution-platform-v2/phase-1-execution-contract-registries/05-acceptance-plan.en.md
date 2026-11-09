# Phase 1 · Execution Contracts and Registries — Acceptance Plan

> Status: Design decisions frozen (R1–R11); local test and local automated acceptance evidence exists, the full suite and CI remain pending, and formal human acceptance/sign-off is incomplete
> Created: 2026-11-02; design frozen: 2026-11-08
> Revised: 2026-11-09 (R11 owned-task documentation clarification; no lifecycle behavior change)
> Basis: `01-business-goals.en.md` (G1–G4 and success metrics), `02-requirements.en.md` (AC-1–AC-8); execution follows `04-test-plan.en.md`; decisions and tasks are in `08-implementation-breakdown.en.md` (R1–R11, T1–T8)

## 1. Acceptance Objectives and Organization

Confirm that contracts and registries are **independently extensible, lifecycle-correct, deterministic in tests, and have zero impact on the current production path**, with sign-off from product, QA, engineering, and an Adapter representative. This is an acceptance plan, not a claim that functionality is implemented or accepted.

| Role | Responsibility |
|---|---|
| Product owner | Facilitate acceptance; confirm scope and later-phase boundaries; sign off P2 residual disposition |
| QA | Execute A1–A8, verify test evidence and determinism, and provide regression conclusion and defect severity |
| Engineering lead | Supply implementation, dependency-direction, no-migration/zero-wiring evidence, metric measurements, and fixes |
| Adapter development representative | Perform UAT with a structurally independent second test Adapter and confirm no common-contract or Worker changes are needed |

## 2. Acceptance Environment and Prerequisites

| Environment | Purpose |
|---|---|
| CI / local pure Python | All contract, registry, LocalTestAdapter, and second-Adapter scenarios; no external Engine, credential, or network dependency |
| Dedicated PostgreSQL regression | Verify existing Runtime/API/SSE behavior and unchanged migration head |
| Document and code review | Check paths, versions, dependency boundaries, error redaction, and Phase 2 non-goals |

**Prerequisites**: Every case in `04-test-plan.en.md` is actually executed and passes with no open P0/P1; provide the CI run, test logs, changed-file list, protected-file diff, and `alembic heads` evidence. Use dedicated acceptance data/test tenants and no real customer input or credentials.

**Entry-risk boundary**: The user's request to start Phase 1 only accepts the open Phase 0 items as an entry risk. Phase 0 clean committed-artifact CI double-runs, authorized real historical samples, and human sign-offs still require their own evidence; Phase 1 startup, testing, or acceptance must never be cited as formal Phase 0 approval.

## 3. Functional Acceptance Checklist (AC-1–AC-8)

| # | Acceptance steps | Pass criterion |
|---|---|---|
| A1 | For AC-1: run positive/negative parameterized cases for all six DTO groups, demonstrate verbatim raw input, and mutate one instance's default collection before reading another | Every invalid input and Result combination is rejected; versions/IDs are correct and input is not trimmed; the other default is unchanged; evidence links to P1-UT-01–04 |
| A2 | For AC-2: select success and streaming scripts, execute capabilities→start→stream→collect, and demonstrate immediate/concurrent/repeated collection, a second start, and both concurrent and sequential-after-iterator-close second stream consumers after the first consumer is created | Five methods and identity properties conform, events are ordered, and every collection returns an equal completed Result; second start and both second-consumer attempts fail with `configuration_error/invalid_adapter_state`, with no stream replay/restart or dangling task |
| A3 | For AC-3: separately control cancellation-first and success-first races, repeat cancel, and inject late events/success | The first terminal state is preserved; cancellation-first yields only cancelled without error/output; cancel after success is a no-op; no event is visible after the terminal Result is visible |
| A4 | For AC-4: exercise ten error categories, every static-catalog code, and all 11 capabilities; execute direct ExecutionError and failed-Result-nested mapping/JSON round trips; attempt arbitrary/mismatched message, raw-exception, and illegal-details `secret-marker` injection | category/code/message/retryable match the matrix; direct and nested round trips preserve the safe model_dump and an exact message is only a no-op integrity token; arbitrary/mismatched/non-string message and illegal details raise ValidationError; undeclared capabilities are false; all caller-visible output omits the marker |
| A5 | For AC-5: the Adapter representative independently adds `(contract-probe,contract-scripted,v1)` and reuses the common suite; retain two resolved objects to prove distinct live identities, then exercise singleton, A→B→A cycle, non-weak-referenceable candidate, and weakref/gc collection scenarios | The second Adapter is not a LocalTestAdapter subclass; no common-contract/Registry-interface/Worker change is needed; valid combinations pass; both live results are independent identity-matching instances; live singleton/cycled reuse and non-weak-referenceable candidates are rejected before escape with `configuration_error/adapter_contract_mismatch`; weakref/gc proves no strong Adapter retention, dead references are pruned, later new objects are unaffected by address reuse, and arbitrary `__eq__` is not invoked |
| A6 | For AC-6: execute unknown/disabled IDs, unknown versions, undeclared combinations, every duplicate registration, factory exception/identity mismatch/missing methods, wrong bound-signature arity, awaitable rejection/cleanup for a Future/Task-returning factory, and a separate `BaseException` boundary in fixed order | Every case fails closed with stable error codes and precedence; `Signature.bind` placeholder checks require zero arguments for capabilities and one for each other method, with wrong arity mapping to `adapter_contract_mismatch`; no instance escapes before checks; synchronous resolve rejects the Future/Task and cancels it as cleanup, `future.cancelled()` is true, every Task fixture is awaited through cleanup, and no pending task remains; a separate boundary case proves `CancelledError`/other `BaseException` propagation is neither swallowed nor rewritten; no latest, alternate-version, or other-Engine fallback occurs |
| A7 | For AC-7: run exact duplicates, event_id conflicts, late/gap events, timeout, resource exhaustion, and simulated process failure twice and inspect asyncio tasks | Duplicate/late events remain verbatim and visible, conflicts are rejected, gaps are valid, other semantics repeat with correct categories, and no external dependency or Adapter-owned/test-created pending task remains |
| A8 | For AC-8: inspect ContractModel, production Worker/Factory, protected-file and lockfile diffs, run existing Runtime/API/SSE regression, and query migration head | No production wiring and zero diff in old APIs/events/states/protected files; head is `0057_industry_pack_runtime`, lockfile is unchanged, and regression is green |

Every scenario record must include executor, date, environment, fixtures, actual result, verdict, and CI/log link. A failed item cannot be marked passed or waived merely because it concerns the test implementation. Mark unavailable environments `pending_env` and incomplete human sign-offs `pending`; never pre-approve them.

## 4. UAT Decision (Adapter Development Representative)

- A second test Adapter can be completed using only common contracts and registry interfaces, without understanding or modifying Worker, Repository, or RuntimeFactory and without subclassing LocalTestAdapter.
- Success, error, and cancellation diagnostics locate configuration/protocol problems without exposing raw credentials, config, exception text, or customer content.
- Simulated process failure in LocalTestAdapter is explicitly distinguished from real process supervision in Phase 4; acceptance records must not conflate them.

## 5. Business Metric Acceptance

| Metric | Baseline | Target | Measurement |
|---|---|---|---|
| Contract branch and five-method coverage | To be inventoried in Phase 0 | 100% of defined contract branches and all five methods have passing cases | Export the P1-UT/IT traceability matrix and CI result; check each method, and fail if any is missing |
| Valid/invalid combination resolution accuracy | To be inventoried in Phase 0 | 100% valid resolution and 100% invalid rejection in the fixed matrix | Cover at least independent Engine/Protocol records, two versions, disabled entries, and every invalid category; retain every row and error-precedence result |
| LocalTestAdapter deterministic scenario pass rate | To be inventoried in Phase 0 | 100% pass in both rounds for all specified scenarios with no pending task | Run twice consecutively in one environment and retain separate logs and Adapter/test task-cleanup assertions |
| Common-contract/Worker changes for a new Adapter | To be measured in Phase 0 | 0 changes | Review the second Adapter's changed-file list, non-inheritance structure, and common-suite reuse evidence |
| Impact on existing Run latency and error rate | To be measured in Phase 0 | Zero production behavioral diff and no added execution overhead | Use zero production-wiring/protected-file diff and existing regression as evidence; do not invent performance figures here—measure them in Phase 0/2 |

## 6. Compliance Checks

| # | Check | Decision |
|---|---|---|
| C1 | DTOs, registries, errors, and logs contain no plaintext credential, connection string, raw Pydantic values, raw exception text, raw stack, or customer input | Veto item |
| C2 | Tenant boundaries, Run/Extension public ports, ContractModel, Agent snapshots, HTTP/SSE, and table structures remain unchanged; head remains `0057_industry_pack_runtime` with zero lockfile diff | Must pass |
| C3 | The new path is absent from production composition; rollback only reverts unwired code and needs no migration or data repair | Must pass |
| C4 | Effective capabilities are not conflated with Declared capabilities, and registries do not perform authorization, scheduling, or process supervision | Must pass |

## 7. Pass Criteria and Sign-off

- **Pass**: A1–A8 all pass; the first four engineering hard metrics are met; C1–C4 all pass; no P0/P1 remains.
- **Conditional pass**: Only P2/P3 issues remain, each with an owner and deadline; AC, production compatibility, and sensitive-information issues cannot be waived.
- **Fail**: Any veto item, AC, or hard metric fails; after fixes, rerun affected items and related regression.
- **Baseline note**: Values marked “to be measured/inventoried in Phase 0” must not later be presented as existing measurements; this phase evaluates targets with a fixed test matrix, while production performance baselines remain for Phase 0/2. Accepting the Phase 0 entry risk is not a Phase 0 acceptance signature.

Produce the Phase 1 Acceptance Report containing AC records, metric matrix, CI/migration evidence, compliance results, residual list, and the sign-off below. Populate the report only from actual evidence.

| Role | Name | Date | Conclusion | Signature |
|---|---|---|---|---|
| Product owner | To be completed | To be completed | To be completed | To be completed |
| QA | To be completed | To be completed | To be completed | To be completed |
| Engineering lead | To be completed | To be completed | To be completed | To be completed |
| Adapter development representative | To be completed | To be completed | To be completed | To be completed |
