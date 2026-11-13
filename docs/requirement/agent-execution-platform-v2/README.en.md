# NexusDesk Agent Execution Platform v2 · Phased Planning Documents

> Status: formal Phase 0 and Phase 1 acceptance remains incomplete; Phase 2 code merged into integration through `3969258`, and its 07 conclusion is **conditionally passed**, with production performance, CI/real deployment, human UAT/sign-off, and durable evidence still open; Phase 3 01–05 were calibrated against merged code and 08 was added on 2026-11-12, and T1–T4 are now implemented on the feature branch `feat/agent-execution-platform-v2-phase3` working tree, having passed task-level dual review plus acceptance (**not yet committed or pushed, not in main/integration**), while phase-level testing and acceptance have not been performed and 06/07 do not exist yet; Phases 4–6 have not started; Phase 7 is deferred
> Created: 2026-11-02
> Revised: 2026-11-13 (Phase 3 T1–T4 working-tree implementation status and task-level review/acceptance conclusions; phase-level 06/07 still not created)
> Revised: 2026-11-12 (synchronized actual Phase 2 status and froze Phase 3 design/breakdown)
> Basis: `docs/architecture/agent-execution-platform-v2.md`, Sections 17, 19, 20, and 22; actual phase 06/07 reports

## Background

The code now retains both the legacy Runtime and a default-off Orchestrator path. Phase 1 exact Registry/Adapter contracts and Phase 2 `ExecutionOrchestrator`, `ExecutionContext`, `ReactAdapter`, and composition wiring exist, but AgentConfig still lacks typed Engine configuration, capability-policy resolution, decision snapshots, and Instruction Providers. Adding external Engines directly would still spread configuration, authorization, and instruction-format branches through Worker and Runtime.

This directory is the single planning root for Agent Execution Platform v2. Code merge, development entry, automated assisted acceptance, and final launch gates are different facts. Plans do not claim implemented capabilities, and conditional acceptance of one phase does not mean all upstream phases are formally accepted.

## Overall Principles

1. **Contract first, incremental refactoring**: extend the existing Execution Contract, Registry, Orchestrator, and ReactAdapter rather than building a parallel execution stack.
2. **Unify governance, not Engine internals**: preserve each Engine's reasoning loop, tool model, and native protocol.
3. **Compatibility and reversibility**: reuse Runs, the Worker queue, Lease/Heartbeat, events, and Agent publication snapshots; explicit flag matrices select paths.
4. **Capability is not authorization**: the server monotonically narrows Declared capabilities through deployment Available and trusted Policy into Effective; client input cannot elevate privileges.
5. **Security and evidence are launch gates**: isolation, credentials, network controls, and resource governance precede untrusted multi-tenant execution; `pending_env`, skips, and unmeasured items are never passes.
6. **Lightweight small-team acceptance**: reuse automated evidence, retain only an acceptance owner and executor (who may be the same person), a few manual checks, and one acceptance record; invent no independent roles.
7. **Verify every phase independently**: G/US/FR/AC, test cases, and acceptance steps remain traceable; create 06/07 only after actual testing/acceptance.

## Phase Roadmap

| Phase | Topic | Core value | Priority | Estimate* | Directory |
|---|---|---|---|---|---|
| Phase 0 | Baseline and inventory | Freeze current behavior, compatibility fixtures, and regression safeguards | P0 | ~1–1.5 weeks | [phase-0-baseline-inventory/](phase-0-baseline-inventory/) |
| Phase 1 | Execution Contract and Registries | Establish a stable Engine/Protocol/Adapter boundary | P0 | ~1.5–2 weeks | [phase-1-execution-contract-registries/](phase-1-execution-contract-registries/) |
| Phase 2 | React Provider and Execution Orchestrator | Remove Worker dependency on a concrete Runtime | P0 | ~2–3 weeks | [phase-2-react-provider-orchestrator/](phase-2-react-provider-orchestrator/) |
| Phase 3 | Capability, configuration, and instructions | Typed multi-Engine configuration, capability governance, and snapshots | P0 | ~2 weeks, re-estimate before implementation | [phase-3-capability-config-instructions/](phase-3-capability-config-instructions/) |
| Phase 4 | Runtime Host, process supervision, and Workspace | Managed processes and isolated work directories for external Engines | P1 | ~3–4 weeks | [phase-4-runtime-host-workspace/](phase-4-runtime-host-workspace/) |
| Phase 5 | Codex integration | Validate the multi-protocol architecture with CLI, then App-Server | P1 | ~8 weeks (A/B serial) | [phase-5-codex-integration/](phase-5-codex-integration/) |
| Phase 6 | Security, reliability, and event governance | Meet the production gate for untrusted multi-tenant execution | P1 | ~4–6 weeks | [phase-6-security-reliability-events/](phase-6-security-reliability-events/) |
| Phase 7 | Advanced Engine capabilities and scale | Expand ecosystem, governance, and cost controls in independent slices | P4 (deferred) | Review per slice after rescheduling | [phase-7-advanced-engines-scale/](phase-7-advanced-engines-scale/) |

> **Phase 7 deferral (2026-11-07)**: no implementation, testing, or acceptance is active. FR-1~FR-11 remain lowest-priority P4 issues #110~#120 and are not delivery commitments until explicitly reactivated.

\* Estimates support planning only and are not commitments; re-estimate against actual baselines and open gates.

Every phase has bilingual `01`–`05`; large phases also have bilingual `08`. Create `06-test-report.md` / `07-acceptance-report.md` only after actual testing/acceptance. Post-acceptance checks such as quickstart only append to existing reports and never prewrite outcomes.

## Dependencies, Development Entry, and Migration Conventions

- The default order is Phase 0 → 1 → 2 → 3 → 4 → 5A → 5B → 6 → 7; Phase 7 is deferred.
- **Phase 3 development entry**: baseline `3969258` provides the required Phase 1/2 code, with a focused baseline of 163 passed / 5 skipped. This permits implementation under 08; it does not prove full CI, upstream formal acceptance, or production approval.
- **Phase 3 final launch gate**: besides this phase's A/C items, upstream real-history samples, CI/real deployment, performance, and human-acceptance gaps remain governed by their reports. Any gap affecting this phase stays `pending_env` / not passed until closed; merged code or deleted gates cannot substitute for evidence.
- The migration head measured on 2026-11-12 is `0057_industry_pack_runtime`, and `0053_routing_decisions` already occupies the old planned number. Phase 3 therefore plans `0058_agent_execution_metadata` with `down_revision="0057_industry_pack_runtime"`. T2 must dynamically revalidate the target head; if it changes, revise the documents in lockstep and never edit applied migration history.
- When design conflicts with code reality, record an R-n decision and revise all affected bilingual files before implementation.

## Phase 2 Deliverables and Phase 3 Continuation

Phase 2 ReactAdapter creates a gated runner in `start`; RuntimeFactory subsequently assembles the model, tools, and effective system prompt inside that runner. The Orchestrator preserves worker_emit/runtime_emit dual emission, structured acknowledgment, Memory Outcome, and public Run/SSE semantics. Phase 2 07 and appendices record conditional passage and quickstart follow-up evidence, not unrestricted formal acceptance.

Phase 3 extends these components rather than copying the execution chain. `Repository.claim` still publishes `run.started` first; the Phase 3 “start barrier” refers specifically to `Adapter.start` and Runtime/tool/model side effects, without changing public event order. With the Phase 3 flag off, the deployment's original Phase 2 on/off path is preserved exactly. Non-React in any off state fails explicitly with `execution_phase3_disabled` and never silently runs as React.

## Explicit Overall Non-Goals

- **No microservice split in the initial migration**: retain a modular monolith.
- **No scheduler rewrite**: retain the persistent Worker queue, Lease/Heartbeat, and existing terminal-state ownership.
- **No Task/Execution dual-table model**: a Run remains one Execution attempt.
- **No mandatory Session/approval/interaction support for every Engine**: these remain declared and resolved optional capabilities.
- **No erasure of native events**: standardize the envelope without forcing ReAct Tool Calling semantics.
- **No shared-storage change without measurements**: assess capacity, latency, isolation, and cost first.
- **No unrestricted host privileges for untrusted tasks**: isolation, credentials, and network policy are hard gates.
- **No Postman publication, external preview service, or new frontend test framework**: retain OpenAPI, Playwright, and the current deployment shape.

## Review Guide

- Phase 0/1: track formal acceptance gaps in their own 07 reports; later merges do not retroactively complete them.
- Phase 2: preserve conditional-pass boundaries, performance/real-deployment gaps, and appendix evidence without rewriting history.
- Phase 3: review legacy aliases and canonical diffs, draft validation without Adapter instances, least privilege and cache invalidation, the five-snapshot start barrier, single-pass Provider rendering, the two-flag matrix, preview tenant isolation, and C11's 100 real samples.
- Phase 4/5/6: review process/Workspace isolation, native-protocol encapsulation, and security/event governance respectively; do not pull their scope into Phase 3.
- Phase 7: after reactivation, review small independent slices.
