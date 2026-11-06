# NexusDesk Agent Execution Platform v2 · Phased Planning Documents

> Status: Phase 0–7 requirements-analysis documents are pending review; implementation has not started
> Created: 2026-11-02
> Basis: `docs/architecture/agent-execution-platform-v2.md`, Sections 17, 19, 20, and 22

## Background

Today `RuntimeWorker` directly invokes the fixed LangGraph ReAct Runtime built by `RuntimeFactory`. A stable Engine Adapter boundary between execution governance, engine selection, and concrete reasoning implementations is missing. Adding external engines such as Codex directly would spread protocol, process, and credential branches through Worker and Runtime.

This directory is the single planning root for Agent Execution Platform v2. Documents `01`–`05` must be reviewed before each phase proceeds to breakdown, implementation, testing, and acceptance. These plans do not claim that any capability already exists.

## Overall Principles

1. **Contract first, incremental refactoring**: stabilize the Execution Contract and Registries before migrating React and integrating external Engines.
2. **Unify governance, not Engine internals**: preserve each Engine's reasoning loop, tool model, and native protocol.
3. **Compatibility and reversibility**: reuse existing Runs, the Worker queue, Lease/Heartbeat, events, and Agent publication snapshots; use flags to switch between old and new paths.
4. **Capability is not authorization**: the platform must derive Effective capabilities from deployment availability and tenant policy; client input cannot elevate privileges.
5. **Security is a launch gate**: isolation, credentials, network controls, and resource governance are mandatory before untrusted multi-tenant code execution.
6. **Verify every phase independently**: G/US/FR/AC, test cases, and acceptance steps remain traceable; actual test and acceptance outcomes belong in separate reports.

## Phase Roadmap

| Phase | Topic | Core value | Priority | Estimate* | Directory |
|---|---|---|---|---|---|
| Phase 0 | Baseline and inventory | Freeze current behavior, compatibility fixtures, and regression safeguards | P0 | ~1–1.5 weeks | [phase-0-baseline-inventory/](phase-0-baseline-inventory/) |
| Phase 1 | Execution Contract and Registries | Establish a stable Engine/Protocol/Adapter boundary | P0 | ~1.5–2 weeks | [phase-1-execution-contract-registries/](phase-1-execution-contract-registries/) |
| Phase 2 | React Provider and Execution Orchestrator | Remove Worker dependency on a concrete Runtime | P0 | ~2–3 weeks | [phase-2-react-provider-orchestrator/](phase-2-react-provider-orchestrator/) |
| Phase 3 | Capability, configuration, and instructions | Typed multi-Engine configuration, capability governance, and snapshots | P0 | ~2 weeks | [phase-3-capability-config-instructions/](phase-3-capability-config-instructions/) |
| Phase 4 | Runtime Host, process supervision, and Workspace | Managed processes and isolated work directories for external Engines | P1 | ~3–4 weeks | [phase-4-runtime-host-workspace/](phase-4-runtime-host-workspace/) |
| Phase 5 | Codex integration | Validate the multi-protocol architecture with CLI, then App-Server | P1 | ~8 weeks (A/B serial) | [phase-5-codex-integration/](phase-5-codex-integration/) |
| Phase 6 | Security, reliability, and event governance | Meet the production gate for untrusted multi-tenant execution | P1 | ~4–6 weeks | [phase-6-security-reliability-events/](phase-6-security-reliability-events/) |
| Phase 7 | Advanced Engine capabilities and scale | Expand the ecosystem, governance, and cost controls in independent slices | P2 | Review per slice | [phase-7-advanced-engines-scale/](phase-7-advanced-engines-scale/) |

\* Estimates support planning discussions only and are not delivery commitments; re-estimate after the Phase 0 baseline.

Each phase contains:

- `01-business-goals.md` / `.en.md`: problems, goals, success metrics, scope, and risks;
- `02-requirements.md` / `.en.md`: US, FR, non-functional requirements, and AC;
- `03-technical-design.md` / `.en.md`: current-state mapping, file-level changes, data and flows, rollout and rollback;
- `04-test-plan.md` / `.en.md`: UT/IT/CM, regression scope, defect levels, and exit criteria;
- `05-acceptance-plan.md` / `.en.md`: AC-by-AC acceptance, business metrics, compliance checks, and sign-off;
- `06-test-report.md` and `07-acceptance-report.md`: created only after actual testing/acceptance;
- `08-implementation-breakdown.md`: created for large phases after design review and before implementation.

## Dependency and Migration Conventions

- The default order is Phase 0 → 1 → 2 → 3 → 4 → 5A → 5B → 6 → 7. Security items may be reviewed earlier, but later launch gates must not be weakened.
- The migration head verified during planning is `0052_memory_tasks_tenant_index`. Numbers `0053+` in these documents are **planned identifiers**. Revalidate the head and adjust `down_revision` against the target commit; never edit an applied historical migration.
- Phase 0 dependency maps, lifecycle records, and compatibility baselines remain under this root in the corresponding phase, avoiding a second documentation source.
- If a design conflicts with code reality, record a decision and revise the affected documents before changing implementation.

## Explicit Overall Non-Goals

- **No microservice split in the initial migration**: establish modular-monolith boundaries first.
- **No scheduler rewrite**: retain the persistent Worker queue, Lease/Heartbeat, and existing terminal-state ownership.
- **No immediate Task/Execution dual-table model**: initially, a Run is one Execution attempt.
- **No mandatory Session/approval/interaction support for every Engine**: these remain declared and resolved optional capabilities.
- **No erasure of native events**: standardize the envelope without forcing ReAct Tool Calling semantics.
- **No shared-storage change without measurements**: assess capacity, latency, isolation, and cost first.
- **No unrestricted host privileges for untrusted tasks**: isolation, credentials, and network policy are hard gates.

## Review Guide

- Phase 0: reproducibility of the current-state and test baseline; representativeness of historical configuration fixtures; identifier freeze.
- Phase 1: contract stability without host-detail leakage; explicit Adapter versioning, cancellation, and error semantics.
- Phase 2: behavioral equivalence of old and new React paths; Worker depends only on Orchestrator; rollback requires no data reversal.
- Phase 3: lossless legacy defaults; client cannot elevate Effective capabilities; snapshots explain every execution decision.
- Phase 4: process-tree cleanup, path/symlink isolation, and resource limits survive failure and adversarial tests.
- Phase 5: App-Server starts only after CLI stabilizes; native protocols stay inside Providers; untrusted execution remains gated.
- Phase 6: Fencing, Outbox, deduplication, and SSE replay cover races; secrets are masked across logs, events, and artifacts.
- Phase 7: delivery remains sliced; routing and fallback re-evaluate policy; Engines without advanced capabilities retain basic execution.
