# NexusDesk Agent Execution Platform v2 · Phased Planning Documents

> Status: Phase 0/1 was closed by an evidence-bound re-acceptance on 2026-11-18 under `11-scope-limited-acceptance-record-20261118.md`: **PASS (scope-limited)**, based on 13 lanes / 5,464 tests / 0 failures and a single acceptance-owner signature; **this is not a retroactive ratification by later merges**, and the historical text and test numbers in the Phase 0/1 07 reports are preserved unchanged. Later phase reports retain their own boundaries. Phase 5 Stage A (`codex/cli_exec/v1`) completed a **scope-limited** end-to-end acceptance on 2026-11-20 (PASS scope-limited), signed by the single acceptance owner JackChow; the authoritative record is `13-scope-limited-acceptance-record-20261120-phase7-stage-a.md`, and the Stage A unlock record for the single-tenant quickstart demo is in the final section of `phase-5-codex-integration/07-acceptance-report.md`. Tool calls needing the `bwrap` sandbox are blocked by Docker's default seccomp inside the container and are recorded as a deployment-hardening boundary; Stage B stays locked, and P5-IT-18 plus the separate Stage B unlock record remain unsatisfied; high-risk enablement (production Codex routing, untrusted multi-tenancy) was neither requested nor authorized. Phase 6 01–05 and bilingual 08 were code-reality checked and approved for direct-continue development on 2026-11-16; no Phase 6 implementation, test, acceptance, or untrusted-exposure approval is claimed. Phase 7 is deferred.
> Created: 2026-11-02
> Revised: 2026-11-21 (Phase 0/1 status line synchronized to "PASS (scope-limited)" per record `11`, explicitly stating that this is not a retroactive ratification by later merges; Review Guide synchronized; `09` §0 table split into two rows separating the closable acceptance-owner conclusion from the independent security approval that no machine can produce; Phase 4/5 07 status lines synchronized with records `12`/`13`; `05-pending-env.md` registration list archived with the evidence-package link and SHA256. No historical conclusion, execution record or test number is rewritten)
> Revised: 2026-11-20 (Phase 5 Stage A closure: corrects the stale "Stage A full acceptance has not passed" line, registers the signed scope-limited acceptance record `13` and the Stage A unlock record in `07`; states the in-container bwrap sandbox boundary and that Stage B and high-risk enablement stay locked; the CD `.env` version write-back trap is closed by PR #157. Phase 0/1 formal acceptance gaps are not retroactively completed by this revision)
> Revised: 2026-11-18 (phase 0–3 acceptance scope limited: performance/capacity/p50/p95/C11 latency, matched pairs and sample counts, ≤5%/≤50 ms, CI provenance/final-PR-head double-run/CI run URL, real or authorized historical samples, and multi-sample/large-sample data-volume requirements are not stage-acceptance gates and remain only as historical notes or out-of-scope statements; keep functional correctness, switch completeness, tenant isolation, Secret handling, data integrity, migration, terminal state/side effects, no open P0/P1, and a single acceptance-owner record; high-risk capability enablement stays a separate approval; phases 0–3 non-destructive lanes accept a governed shared production host)
> Revised: 2026-11-16 (Phase 6 implementation baseline added; current migration head and upstream acceptance boundaries recorded)
> Revised: 2026-11-13 (Phase 3 status line updated: T1–T9 implemented and the merged test lane passed, T6/T7/T8 with no blocking findings and their implementation plus this third documentation batch still uncommitted, T10/T11 in progress so 06/07 do not exist yet, T9 condition ① folded into #128; 08 §2 gains rulings R-42–R-52 and bilingual 03/04/05 carry the same batch content)
> Revised: 2026-11-13 (Phase 3 status line updated: T1–T6 plus T9 implemented, T5/T9 conditionally passed, T6 past test evidence and hardening, 4 unpushed local commits not merged, T7/T8 and T10/T11 not started so 06/07 do not exist; T12/T13 moved out of this phase to issues #127/#128 (08 R-39))
> Revised: 2026-11-13 (Phase 3 T1–T4 working-tree implementation status and task-level review/acceptance conclusions; phase-level 06/07 still not created)
> Revised: 2026-11-12 (synchronized actual Phase 2 status and froze Phase 3 design/breakdown)
> Basis: `docs/architecture/agent-execution-platform-v2.md`, Sections 17, 19, 20, and 22; actual phase 06/07 reports
>
> **2026-11-18 acceptance scope revision (phases 0–3)**: performance/capacity/latency (p50/p95, C11, matched pairs, sample counts, ≤5%/≤50 ms), CI provenance (final-PR-head double-run / CI run URL), real or authorized historical samples, and multi-sample/large-sample data-volume requirements are no longer stage-acceptance gates; they remain only as historical notes or explicit out-of-scope statements. Phase acceptance rests solely on functional correctness (A scenarios), switch completeness (default off, explicit on, off/on/rollback matrix, no silent fallback, no flag leakage into public surfaces/fingerprint), tenant isolation, Secret handling, data integrity, migration correctness, terminal-state semantics, side effects/cleanup, no open P0/P1, and a single acceptance-owner record. High-risk capability enablement stays a separate approval; phases 0–3 non-destructive lanes may run on a governed shared production host with run-scoped containers/ports/volumes/paths/credentials and no changes to co-tenant services.

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
- **Phase 3 stage-acceptance gate (scoped 2026-11-18)**: rests solely on this phase's A/C functional correctness, switch matrix, tenant isolation, Secret handling, data integrity, migration, terminal state/side effects, no open P0/P1, and a single acceptance-owner record. Upstream real-history samples, CI/real deployment, and performance/capacity or human-acceptance gaps are historical notes or out-of-stage-scope items under the 2026-11-18 revision; they no longer block phases 0–3 acceptance and are not written as `pending_env` / not passed. High-risk enablement still needs a separate approval; merged code cannot substitute for the kept gates.
- The migration head measured on 2026-11-12 is `0057_industry_pack_runtime`, and `0053_routing_decisions` already occupies the old planned number. Phase 3 therefore plans `0058_agent_execution_metadata` with `down_revision="0057_industry_pack_runtime"`. T2 must dynamically revalidate the target head; if it changes, revise the documents in lockstep and never edit applied migration history.
- **Phase 6 development entry**: direct-continue development is authorized on baseline `7772a32`; planned migrations are 0068 then 0069 from the measured single head `0067_merge_heads`. This does not satisfy Phase 0 or Phase 5 full-acceptance prerequisites. Real Session/Resume, production Codex routing, strong-sandbox/fault environments, and independent approvals remain gates under Phase 6 08 R-5–R-9.
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

- Phase 0/1: closed by a new evidence-bound re-acceptance under `11-scope-limited-acceptance-record-20261118.md` — **PASS (scope-limited)**, based on 13 lanes / 5,464 tests / 0 failures and a single acceptance-owner signature. **This is not a retroactive ratification by later merges.** The historical status lines, execution records and test numbers in both 07 reports are preserved; review against the "2026-11-18 scope-limited acceptance execution addendum" at the end of each 07 and record `11`. CI double-runs, real historical samples and multi-role signatures are out-of-scope historical notes under the 2026-11-18 revision, not gates.
- Phase 2: preserve conditional-pass boundaries, kept gates (switch matrix, isolation, data, migration, terminal state/side effects), and appendix evidence; performance/real-deployment gaps are out-of-scope historical notes under the 2026-11-18 revision. Do not rewrite history.
- Phase 3: review legacy aliases and canonical diffs, draft validation without Adapter instances, least privilege and cache invalidation, the five-snapshot start barrier, single-pass Provider rendering, the two-flag matrix, preview tenant isolation, and kept gates (default off, no silent fallback, no flag leakage). C11's 100 real samples are an out-of-scope historical note under the 2026-11-18 revision, not a gate.
- Phase 4/5: review process/Workspace isolation and native-protocol encapsulation against their actual reports.
- Phase 6: start from [08-implementation-breakdown.en.md](phase-6-security-reliability-events/08-implementation-breakdown.en.md), then review fencing coverage, direct-writer Outbox atomicity, dual sequence domains, credential/strong-sandbox enforcement, focused test reuse, and unresolved upstream/real-environment gates.
- Phase 7: after reactivation, review small independent slices.
