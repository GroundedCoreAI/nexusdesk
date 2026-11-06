# Phase 2 · React Provider and Execution Orchestrator — Acceptance Plan

> Status: Pending review / Pending implementation
> Created: 2026-11-02
> Basis: `01-business-goals.md` (G1–G4 and success metrics), `02-requirements.md` (AC-1–AC-9); execution follows `04-test-plan.md`

## 1. Acceptance Objectives and Organization

Confirm that React Provider and the orchestrator are **functionally equivalent, decouple Worker, keep SSE/terminal states reliable, support gradual rollback, and are transparent to existing tenants**, with a signed conclusion. This is a pending plan, not a claim that the new path is implemented, measured, or released.

| Role | Responsibility |
|---|---|
| Product owner | Facilitate acceptance; assess existing tenant experience and scope; sign off P2 residual disposition |
| QA | Execute A1–A9, old/new diff, dual SSE, and regression; classify defects and archive evidence |
| Engineering lead | Provide implementation/test environments, performance/error-rate measurements, and fixes |
| SRE/operations representative | Exercise gradual rollout, mixed Workers, monitoring, and rollback; sign deployment/runtime UAT |
| Tenant/customer-service representative | Perform business UAT for replies, tool results, streaming experience, and cancellation |

## 2. Acceptance Environment and Prerequisites

| Environment | Purpose |
|---|---|
| Production-like dedicated environment (fixed mock and real model groups) | A1–A9, functional parity, performance, and error-rate measurement; real models are not used for deterministic verbatim diff |
| Dedicated PostgreSQL + two Worker configuration groups | Terminal races, Lease lost, mixed old/new paths, and rolling rollback |
| quickstart demo environment | Default off, explicit on, existing API/SSE, and zero additional deployment components |

**Prerequisites**: Every `04-test-plan.md` case passes with no open P0/P1; Phase 0 baseline data is archived; dedicated acceptance tenants/model scripts/tool fixtures are ready; off/on configuration and rollback runbook are prepared. Real-model tests use controlled low-sensitivity data, and output randomness is not mistaken for Adapter differences.

## 3. Functional Acceptance Checklist (AC-1–AC-9)

| # | Acceptance steps | Pass criterion |
|---|---|---|
| A1 | For AC-1: run identical fixed model scripts for no snapshot and a published Agent, once each with legacy/on, and export Run, events, and internal test Outcome | output, history/dropped, model events/usage, terminal state, and error_code all match; Agent snapshot is unchanged and resolution records react/native/v1 |
| A2 | For AC-2: run tool-loop, history-truncation, summary/customer_memory, reasoning, and budget scripts, comparing messages and Memory calls | Tool arguments/results, message order, dropped/memory_context, reasoning history, and budget errors are equivalent; reasoning is absent from visible output |
| A3 | For AC-3: trace one enabled-path call chain, then replace React with LocalTestAdapter for common success/failure/cancellation | Production Run uses Registry→Orchestrator→ReactAdapter; Worker has no Engine-specific call; replacing Adapter changes no Worker core and finishes once |
| A4 | For AC-4: read old/new internal and open SSE and verify delta, durable events, terminal frames, Last-Event-ID, tool.replay, and cross-tenant access | Type/order/payload/seq/replay/heartbeat match baseline; delta is not persisted; no duplicate terminal state, private metadata, history, or new sensitive field |
| A5 | For AC-5: inject missing model, model timeout, invalid/empty response, round/tool budgets, and unknown exception individually | RunView/run.failed error_code matches on both paths without generic loss; logs/APIs contain no raw sensitive exception |
| A6 | For AC-6: cancel during execution while releasing success, repeat cancel, and inspect Adapter tasks plus PG terminal state/events | Cleanup completes; final state is cancelled with no output, late completed, or second terminal state; cancellation matches legacy and no task is pending |
| A7 | For AC-7: trigger run/model timeout and Lease lost, then submit an expired Worker success | error_code is run_timeout, model_timeout, and worker_lost respectively; terminal states are correct, late output is rejected, and terminal event is unique |
| A8 | For AC-8: verify default off, explicit on, mixed Workers, then cause enabled-path resolution failure; finally set off and rolling-restart | off/on path selection is correct and mixed execution is equivalent; resolution failure never silently falls back; every new Run uses legacy after rollback with no DB operation |
| A9 | For AC-9: inspect API/Agent configuration/migration diff, log observability, and existing regression | Public schemas unchanged, head=`0052`, logs contain safe path/tuple/terminal state without sensitive content, and regression is green |

Every scenario record must include executor, date, environment, flag state, fixtures/script version, actual result, verdict, Run ID, and CI/log/SSE evidence links. Old/new diff must include machine-readable results, not merely “manually looks identical.”

## 4. UAT Decision (Tenant/Customer-Service Representative and SRE)

- Without changing Agent or client, the tenant/customer-service representative confirms replies, tool results, streaming, error presentation, and cancellation match the legacy experience.
- SRE can distinguish legacy from orchestrator and locate react/native/v1 and terminal state in safe logs/metrics, but cannot read input/config/history/credentials from logs.
- SRE independently performs an on→off rolling rollback and confirms all new Runs use legacy, in-flight Runs converge under existing rules, and no migration or client action is needed.

## 5. Business Metric Acceptance

| Metric | Baseline | Target | Measurement |
|---|---|---|---|
| Semantic parity on fixed React regression corpus | To be established in Phase 0 | 100% parity for output/history/dropped/events/error_code/terminal state | Cover at least no snapshot, snapshot, tools, Memory, and failure groups; compare legacy/on with identical scripts and save diff |
| New-path registration and orchestration coverage | To be inventoried in Phase 0 | 100% of enabled acceptance Runs use react/native/v1 and Orchestrator, with zero direct Worker Engine calls | Aggregate safe path/tuple logs for all acceptance Runs and call-chain tests; sampling cannot replace the complete count |
| SSE compatibility | Baseline to be recorded in Phase 0 | 100% event/seq/replay/delta/terminal-frame parity in fixed scenarios and zero new disclosed fields | Cover at least success, tools, cancellation, failure, and replay on both internal and open APIs; save normalized SSE diff |
| Cancellation/timeout/late-result protection accuracy | To be inventoried in Phase 0 | 100% correct in specified scenarios and zero late-success overwrites | Execute A6/A7 and real PG race cases; check status, output, error_code, and terminal-event count for every Run |
| New-path performance and stability | To be measured in Phase 0 | p95 end-to-end latency increase ≤5% and zero additional errors | Alternate legacy/on for ≥30 fixed-script Runs each in one environment; record p50/p95/first token/error rate/resources; insufficient samples are pending_env |
| Rollback recovery | To be exercised in Phase 0 | 100% of new Runs use legacy after rollback, with no downgrade/data repair/client change | After mixed-Worker execution, set off and rolling-restart; inspect path logs for at least 20 new Runs and in-flight convergence records |

## 6. Compliance Checks

| # | Check | Decision |
|---|---|---|
| C1 | Logs, errors, Execution metadata, and internal/open SSE contain no key, raw stack, input/config/history, or unauthorized customer data | Veto item |
| C2 | tenant/business/workspace isolation and public-field filtering remain unchanged, and cross-tenant Run/SSE is inaccessible | Veto item |
| C3 | Flag defaults false; off/on/mixed/rollback are all verified; rollback needs no Alembic downgrade, data repair, or client change | Must pass |
| C4 | RunRepository remains the sole Run terminal-state/durable-event committer, and cancellation, Lease lost, and late-success protection are not bypassed | Veto item |
| C5 | Public API/SSE/Agent snapshots and table structures remain unchanged with head `0052`; no Phase 3–6 functionality is included | Must pass |

## 7. Pass Criteria and Sign-off

- **Pass**: A1–A9 all pass; semantic/SSE/terminal-state/rollback hard metrics are met, and performance sampling meets target or has reviewed valid-environment data; C1–C5 all pass; no P0/P1 remains.
- **Conditional pass**: Only P2/P3 issues remain, each with an owner and deadline; parity, sensitive information, terminal states, flags, and migration hard requirements cannot be waived.
- **Fail**: Any veto item, AC, or hard metric fails; keep/restore off immediately, fix, and rerun affected items plus all old/new path regression.
- **Baseline and environment note**: Never invent Phase 0 measurements; insufficient performance environment/samples are marked `pending_env`, and performance compliance or full enablement cannot be claimed before valid data exists.

Produce the Phase 2 Acceptance Report containing AC records, old/new diff, metric data, rollout/rollback evidence, compliance results, residual list, conclusion, and the sign-off below.

| Role | Name | Date | Conclusion | Signature |
|---|---|---|---|---|
| Product owner | To be completed | To be completed | To be completed | To be completed |
| QA | To be completed | To be completed | To be completed | To be completed |
| Engineering lead | To be completed | To be completed | To be completed | To be completed |
| SRE/operations representative | To be completed | To be completed | To be completed | To be completed |
| Tenant/customer-service representative | To be completed | To be completed | To be completed | To be completed |
