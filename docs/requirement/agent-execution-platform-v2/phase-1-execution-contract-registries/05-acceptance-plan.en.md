# Phase 1 · Execution Contracts and Registries — Acceptance Plan

> Status: Design decisions frozen (R1–R11); local test and local automated acceptance evidence exists, the full suite and CI remain pending, and formal acceptance is pending
> Created: 2026-11-02; design frozen: 2026-11-08
> Revised: 2026-11-17 (aligned to the minimal-core-team acceptance standard: single acceptance owner; removed multi-role sign-off, Adapter UAT, and the business-metric table; technical criteria and hard gates unchanged)
> Basis: `01-business-goals.en.md` (G1–G4 and success metrics), `02-requirements.en.md` (AC-1–AC-8); execution follows `04-test-plan.en.md`; decisions and tasks are in `08-implementation-breakdown.en.md` (R1–R11, T1–T8)

## 1. Acceptance Scope and Responsibility

Confirm that contracts and registries are **independently extensible, lifecycle-correct, deterministic in tests, and have zero impact on the current production path**. This is an acceptance plan, not a claim that functionality is implemented or accepted.

Apply minimal-core-team acceptance: a single acceptance owner, who may execute and reach the verdict personally; where assistance is needed, an executor may be designated and may be the same person. No product/QA/engineering/Adapter-representative multi-role responsibility table, no multi-role sign-off sheet, and no standalone UAT round. Second-Adapter extensibility is verified within the A5 automated criterion rather than through an Adapter-representative sign-off. Developer self-verification does not claim real-user or independent acceptance.

Passing phase acceptance does not authorize later phases or any high-risk capability; enabling a high-risk capability requires a separate independent security and operations approval record.

## 2. Acceptance Environment and Prerequisites

| Environment | Purpose |
|---|---|
| CI / local pure Python | All contract, registry, LocalTestAdapter, and second-Adapter scenarios; no external Engine, credential, or network dependency |
| Dedicated PostgreSQL regression | Verify existing Runtime/API/SSE behavior and unchanged migration head |
| Document and code review | Check paths, versions, dependency boundaries, error redaction, and Phase 2 non-goals |

**Prerequisites**: Every case in `04-test-plan.en.md` is actually executed and passes with no open P0/P1; provide the CI run, test logs, changed-file list, protected-file diff, and `alembic heads` evidence. Use dedicated acceptance data/test tenants and no real customer input or credentials.

**Entry-risk boundary**: The user's request to start Phase 1 only accepts the open Phase 0 items as an entry risk. Phase 0's clean committed-artifact CI double-run and authorized real historical fixtures still require their own evidence; Phase 1 startup, testing, or acceptance must never be cited as formal Phase 0 approval.

## 3. Functional Acceptance Checklist (AC-1–AC-8)

| # | Acceptance steps | Pass criterion | Trace |
|---|---|---|---|
| A1 | For AC-1: run positive/negative parameterized cases for all six DTO groups, demonstrate verbatim raw input, and mutate one instance's default collection before reading another | Every invalid input and Result combination is rejected; versions/IDs are correct and input is not trimmed; the other default is unchanged; evidence links to P1-UT-01–04 | AC-1 |
| A2 | For AC-2: select success and streaming scripts, execute capabilities→start→stream→collect, and demonstrate immediate/concurrent/repeated collection, a second start, and both concurrent and sequential-after-iterator-close second stream consumers after the first consumer is created | Five methods and identity properties conform, events are ordered, and every collection returns an equal completed Result; second start and both second-consumer attempts fail with `configuration_error/invalid_adapter_state`, with no stream replay/restart or dangling task | AC-2 |
| A3 | For AC-3: separately control cancellation-first and success-first races, repeat cancel, and inject late events/success | The first terminal state is preserved; cancellation-first yields only cancelled without error/output; cancel after success is a no-op; no event is visible after the terminal Result is visible | AC-3 |
| A4 | For AC-4: exercise ten error categories, every static-catalog code, and all 11 capabilities; execute direct ExecutionError and failed-Result-nested mapping/JSON round trips; attempt arbitrary/mismatched message, raw-exception, and illegal-details `secret-marker` injection | category/code/message/retryable match the matrix; direct and nested round trips preserve the safe model_dump and an exact message is only a no-op integrity token; arbitrary/mismatched/non-string message and illegal details raise ValidationError; undeclared capabilities are false; all caller-visible output omits the marker | AC-4 |
| A5 | For AC-5: a structurally independent second Adapter adds `(contract-probe,contract-scripted,v1)` using only the public contract and reuses the common suite; retain two resolved objects to prove distinct live identities, then exercise singleton, A→B→A cycle, non-weak-referenceable candidate, and weakref/gc collection scenarios | The second Adapter is not a LocalTestAdapter subclass; no common-contract/Registry-interface/Worker/RuntimeFactory/Repository change is needed; valid combinations pass; both live results are independent identity-matching instances; live singleton/cycled reuse and non-weak-referenceable candidates are rejected before escape with `configuration_error/adapter_contract_mismatch`; weakref/gc proves no strong Adapter retention, dead references are pruned, later new objects are unaffected by address reuse, and arbitrary `__eq__` is not invoked | AC-5 |
| A6 | For AC-6: execute unknown/disabled IDs, unknown versions, undeclared combinations, every duplicate registration, factory exception/identity mismatch/missing methods, wrong bound-signature arity, awaitable rejection/cleanup for a Future/Task-returning factory, and a separate `BaseException` boundary in fixed order | Every case fails closed with stable error codes and precedence; `Signature.bind` placeholder checks require zero arguments for capabilities and one for each other method, with wrong arity mapping to `adapter_contract_mismatch`; no instance escapes before checks; synchronous resolve rejects the Future/Task and cancels it as cleanup, `future.cancelled()` is true, every Task fixture is awaited through cleanup, and no pending task remains; a separate boundary case proves `CancelledError`/other `BaseException` propagation is neither swallowed nor rewritten; no latest, alternate-version, or other-Engine fallback occurs | AC-6 |
| A7 | For AC-7: run exact duplicates, event_id conflicts, late/gap events, timeout, resource exhaustion, and simulated process failure twice and inspect asyncio tasks | Duplicate/late events remain verbatim and visible, conflicts are rejected, gaps are valid, other semantics repeat with correct categories, and no external dependency or Adapter-owned/test-created pending task remains | AC-7 |
| A8 | For AC-8: inspect ContractModel, production Worker/Factory, protected-file and lockfile diffs, run existing Runtime/API/SSE regression, and query migration head | No production wiring and zero diff in old APIs/events/states/protected files; head is `0057_industry_pack_runtime`, lockfile is unchanged, and regression is green | AC-8 |

Every scenario record must include executor, date, environment, fixtures, actual result, verdict, and CI/log link. A failed item cannot be marked passed or waived merely because it concerns the test implementation. Mark unavailable environments `pending_env`; automated scenarios reference existing 06/CI evidence rather than being re-run manually.

## 4. Key Manual Checks (only non-automatable applicable items, at most 3–5)

| # | Check | Pass criterion |
|---|---|---|
| M1 | Judge the changes needed for a second Adapter using only the public contract and registry interfaces | No need to understand or modify Worker/Repository/RuntimeFactory and no inheritance from LocalTestAdapter; diagnostics locate configuration/protocol problems without exposing raw credentials or customer content |
| M2 | Review diagnostics in error and cancellation scenarios | Problems are locatable without raw credentials, config, exception text, or customer content |
| M3 | Distinguish LocalTestAdapter simulated process failure from Phase 4 real process supervision | The acceptance record does not conflate the two kinds of process failure |

## 5. Security, Data, and Release Hard Gates

| # | Check | Decision | Trace |
|---|---|---|---|
| C1 | DTOs, registries, errors, and logs contain no plaintext credential, connection string, raw Pydantic values, raw exception text, raw stack, or customer input | Veto item | AC-4 |
| C2 | Tenant boundaries, Run/Extension public ports, ContractModel, Agent snapshots, HTTP/SSE, and table structures remain unchanged; head remains `0057_industry_pack_runtime` with zero lockfile diff | Must pass | AC-8 |
| C3 | The new path is absent from production composition; rollback only reverts unwired code and needs no migration or data repair | Must pass | AC-8 |
| C4 | Effective capabilities are not conflated with Declared capabilities, and registries do not perform authorization, scheduling, or process supervision | Must pass | AC-5 |

## 6. Pass Criteria and Acceptance Record

- **Pass**: A1–A8 and C1–C4 all have evidence and pass; M1–M3 are complete or have equivalent evidence; zero P0/P1 leftovers.
- **Conditional pass**: Only P2/P3 residuals remain, each with an owner and deadline, confirmed by the acceptance owner in the record below; no waiver of AC, production compatibility, or sensitive-information issues.
- **Fail**: Any veto item or unmet AC; after fixes, rerun affected items and related regression.
- **Baseline note**: Values marked "to be measured/inventoried in Phase 0" must not later be presented as existing measurements; this phase evaluates targets with a fixed test matrix, while production performance baselines remain for Phase 0/2. Accepting the Phase 0 entry risk is not a Phase 0 acceptance sign-off.
- **Release note**: passing phase acceptance does not authorize later phases or any high-risk capability.

Produce the Phase 1 Acceptance Report with AC records, CI/migration evidence, compliance results, residual list, verdict, and the single acceptance record below; multi-role sign-off is not required. Populate the report only from actual evidence.

| Acceptance owner | Executor | Date | Target SHA | Decision | Evidence/residuals |
|---|---|---|---|---|---|
| To be filled | To be filled (may be the acceptance owner) | To be filled | To be filled | Pending acceptance | To be filled |
