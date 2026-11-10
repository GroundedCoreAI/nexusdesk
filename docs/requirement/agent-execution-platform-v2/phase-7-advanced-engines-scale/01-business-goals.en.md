# Phase 7 · Advanced Engine Capabilities and Scale — Business Goals

> Status: Deferred (early-stage project; planning is retained, but implementation, testing, and acceptance are not starting)
> Deferral decision: 2026-11-07; FR-1~FR-11 are tracked as lowest-priority P4 GitHub issues (#110~#120), indexed under “Deferral and Requirement Tracking” in `02-requirements.en.md`
> Created: 2026-11-02
> Basis: `docs/architecture/agent-execution-platform-v2.md` §17 Phase 7, §18, §19, and §22; code and Alembic migration review performed on 2026-11-02
> Phase: Phase 7 (advanced capabilities, lowest priority P4; depends on accepted Phase 0~6 capabilities)
> Estimated effort: Estimate the 9 independent small-PR slices separately; no Big Bang overall schedule commitment
> Dependencies: Phase 0 baseline and regression evidence, Phase 1~2 common execution contracts and orchestrator, Phase 3 capabilities/instructions, Phase 4 Workspace/Runtime Host, and Phase 6 security/event governance; a slice with unmet dependencies must not launch

## Problems to Solve

### Problem 1: The execution path is still fixed to ReAct and lacks an extension boundary

Today `backend/src/agent_platform/core_platform/agent_runtime/worker.py` invokes the Runtime directly, while `backend/src/agent_platform/applications/platform_runtime/runtime_factory.py` constructs a fixed `RuntimeEngine`. No common Engine/Protocol/Adapter registry is implemented. Adding vendor integrations directly would couple protocol differences, process management, and routing policy back into the Worker.

### Problem 2: Advanced capabilities lack a unified, degradable governance contract

Session Resume, human approval, interactive input, and dynamic model selection cannot rely on an Adapter merely claiming support. `RunStatus` currently contains only queued/running/completed/failed/cancelled; durable execution waits, Session reauthorization, and side-effect-safe fallback are not implemented. If each Engine interprets capabilities independently, UI, authorization, and failure semantics will diverge.

### Problem 3: Existing model governance is useful but does not govern all Engine usage or scale

The model gateway already provides versioned Profiles, model-route fallback, call usage, and estimated costs, and the Runtime already has queue and tenant capacity limits. They do not yet cover native Engine usage, multiple currencies/unknown costs, cross-Worker fair scheduling, or Runtime Profile health and circuit breaking. Rebuilding or double-counting these concerns would produce incorrect governance.

### Problem 4: Skill, Artifact, and health features would increase security and operational exposure without platform boundaries

The existing knowledge/tool workspaces and S3 archive are not a general execution Skill/Artifact Store. Exposing host paths, object keys, or vendor directory formats would create cross-tenant access, path escape, credential leakage, and format lock-in risks. Process-local health state would also be insufficient for consistent multi-Worker routing.

## Business Goals

| Goal | Description |
|---|---|
| G1: Verifiable Adapter ecosystem | Integrate a new Engine through `(engine_id, protocol_id, adapter_version)` and common contract tests without changing Worker core or the common Engine contract. Claude, ACP, OpenClaw, and similar names are Adapter examples only, not delivery commitments. |
| G2: Policy-bound routing and fallback | Fall back only for explicit, side-effect-free, retryable failures. Re-evaluate tenant, Agent, Workspace, credential, and capability authorization for every candidate; permissions may only narrow. |
| G3: Basic execution remains available | An Engine without advanced capabilities can still perform basic execution according to Effective capabilities. Missing required capabilities fail before execution; security requirements must never silently degrade. |
| G4: Resumable Sessions with reauthorization | Bind a Session to tenant, conversation, Engine/Protocol/Adapter, Workspace, and policy version. Reauthorize before resume; expired or unauthorized resume fails closed. |
| G5: Recoverable human collaboration | Use durable waits, idempotent decisions, separation of duties, and expiry semantics for human approval and interactive input. Waiting releases execution resources and resume does not repeat side effects. |
| G6: Auditable dynamic model selection | Deterministically select a versioned model Profile within tenant and Agent allowlists and snapshot the reason. Existing fixed-Profile behavior remains compatible. |
| G7: Unified usage/cost without double counting | Combine model-gateway and native Engine usage while distinguishing additive from informational data, known from unknown costs, and different currencies. No cross-tenant visibility. |
| G8: Tenant fairness and global quotas | Add cross-Worker atomic quotas and starvation-resistant scheduling while retaining the existing queue/Lease model; limit noisy neighbors and exclude waiting from running quotas. |
| G9: Governed Skills and Artifacts | Version Skills with source, permissions, and content hash and mount them read-only through Engine-specific adapters. Give Artifacts tenant authorization, hashes, retention, and safe downloads without exposing host paths. |
| G10: Operable Runtime Profiles | Version Runtime Profiles for resource and Adapter configuration. Health checks, circuit breaking, and half-open recovery affect Available rather than authorization and remain auditable. |
| G11: Independently reversible incremental delivery | Give each slice an independent, default-off feature flag, small PRs, contract tests, launch review, and rollback evidence instead of launching all of Phase 7 at once. |

## Success Metrics

> “Not measured” below means neither zero nor passed. Phase 0 must establish each baseline in a named environment and record samples, load, and measurement method. No comparative improvement may be claimed while its baseline is missing.

| Metric | Baseline (current) | Target |
|---|---|---|
| Adapter contract pass rate and Worker decoupling | Not measured; Phase 0 to record existing Adapter/contract coverage (no common Adapter suite currently exists) | 100% of applicable contract cases pass for every launched Adapter; Worker core diff is 0 for a new Adapter and the common Engine contract has no unnecessary change. |
| Fallback authorization and side-effect safety | Not measured; Phase 0 to record current error/retry behavior | Zero unauthorized fallbacks, automatic fallbacks after side effects, or cross-tenant fallbacks; every fallback records its reason and policy snapshot. |
| Basic-capability compatibility | Not measured; Phase 0 to pin ReAct requests, events, terminal states, and UI baseline | With advanced capabilities off or unavailable, 100% of Phase 0 basic-execution regressions pass and flag-off behavioral diff is zero. |
| Session resume security | Not measured; Phase 0 to inventory conversation and authorization behavior | Reauthorization occurs for 100% of applicable resumes; expired, revoked, binding-changed, and cross-tenant resumes are blocked 100%. |
| Human wait and decision correctness | Not measured; Phase 0 to record current approval and Run behavior | Waiting holds no running Lease/quota; duplicate decisions cause neither a second resume nor a second side effect; unauthorized, self-approved, and expired decisions are blocked 100%. |
| Dynamic model-selection auditability | Not measured; Phase 0 to record fixed-Profile selection and model fallback | 100% of selections stay within allowlists and persist Profile ID/version/reason; legacy configuration selection matches Phase 0. |
| Usage completeness and cost semantics | Not measured; Phase 0 to measure gateway coverage, unknown costs, and latency | 100% of records have source and idempotency keys; duplicate reports do not double aggregates; unknown cost is never displayed as 0; currencies are never directly summed. |
| Quota and fairness | Not measured; Phase 0 to measure queue throughput, P95 wait, and noisy-neighbor scenarios | Multi-Worker stress never exceeds limits; under the agreed two-tenant load, the light tenant progresses in every test batch and its P95 queue wait is no more than 2× the same-environment idle baseline. |
| Skill/Artifact security and reproducibility | Not measured; Phase 0 to inventory Workspace and object-storage boundaries | 100% of execution snapshots pin Skill version/hash; cross-tenant downloads, path escapes, tampered mounts, and expired downloads are blocked 100%. |
| Runtime health governance | Not measured; Phase 0 to record Engine availability and failure recovery | 100% of circuit/half-open transitions match the contract; stale health data is never treated as healthy; health probes perform no tenant business side effects. |
| Slice rollback capability | Not measured; Phase 0 to record release and rollback processes | Every launched slice can be disabled independently; applicable Phase 0 behavioral diff is zero after disabling, with no historical-data deletion or down migration required. |

## Scope

**Included**: The following are unified planning candidates, not blanket launch approval. Each slice requires design review of dependencies, migration head, API/UI, test evidence, and actual launch scope.

| Slice | Capability scope | Independent flag (default off) | Primary dependencies |
|---|---|---|---|
| S7-01 | Adapter SDK, enhanced LocalTestAdapter, common contract and compatibility tests | `phase7_adapter_sdk_enabled` | Phase 1 contracts/registry |
| S7-02 | Policy routing, safe fallback, basic-capability degradation, Effective capability projection | `phase7_safe_routing_enabled` | Phase 1~3; S7-01 test adapter |
| S7-03 | Engine Session lifecycle and reauthorized Resume | `phase7_session_resume_enabled` | Phase 2~4 and Phase 6 |
| S7-04 | Human approval, interactive input, durable waiting, and resume | `phase7_human_interaction_enabled` | Phase 2 and Phase 6; reuse existing approval port |
| S7-05 | Dynamic model Profile selection and snapshots | `phase7_dynamic_model_enabled` | Phase 2 React Provider; existing model gateway |
| S7-06 | Engine usage normalization, cost aggregation, and reports | `phase7_engine_usage_enabled` | Phase 1 event contract; S7-01 |
| S7-07 | Cross-Worker global/tenant quotas and fair scheduling | `phase7_fair_scheduling_enabled` | Phase 2 orchestrator and existing durable queue |
| S7-08 | Shared read-only Skill Store, Engine Skill Adapters, and Artifact Store | `phase7_skill_artifact_enabled` | Phase 3~4 and Phase 6 |
| S7-09 | Runtime Profiles, health checks, circuit breaking, and half-open recovery | `phase7_runtime_profile_enabled` | Phase 1 registry and Phase 4 Runtime Host |

**Excluded** (later phases / explicitly not doing):
- No delivery or licensing commitment for any specific vendor Engine/Protocol. Claude, ACP, OpenClaw, remote, and custom Engines are Adapter examples only.
- No single core migration or large PR for all slices, and no use of Engine counts as a substitute for architecture acceptance.
- No microservice split or wholesale replacement of the existing Worker queue, Lease, Heartbeat, and terminal-state protection.
- No automatic introduction of first-class Task/Execution dual tables, task priorities, or cross-Engine resume after side effects; a separate requirement is needed if evidence justifies them.
- No blind automatic fallback after timeout, unknown outcome, streamed output, approval, Artifact creation, or external side effects.
- Cost estimates are not supplier invoices. No currency conversion without rate/snapshot data, and no treatment of missing usage/cost as zero.
- No cross-tenant writable Skills, anonymous Artifact links, arbitrary client-provided host commands, or untrusted code execution before sandbox, network, and credential isolation are accepted.

## Risks and Constraints

- **Dependencies first**: This document references target `agent_execution` boundaries; it does not claim those modules exist. Implementation must revalidate the accepted Phase 0~6 reality.
- **Migration drift**: The current latest migration is `0052_memory_tasks_tenant_index`. Any `0058+` identifier in these documents is a planning number, not an existing file. Recheck head, renumber, and set the real `down_revision` before implementation.
- **Privilege amplification**: Fallback, dynamic models, Resume, and health recovery can change the execution target. Every target change must recompute Effective capabilities using the trusted tenant context.
- **Unknown side effects**: Timeout and disconnection do not prove an Engine performed no work. Stop automatic fallback by default and expose auditable unknown/failure semantics.
- **Duplicate data**: The model gateway already records model-call costs. Engine aggregate usage must declare whether it is additive and must not be summed again with model calls.
- **Compatibility**: waiting, Effective capabilities, and new events are additive changes. Existing Runs, published Agent snapshots, SSE cursors, and fixed-Profile behavior must remain readable and replayable.
- **Sensitive information**: Configuration stores Secret references only. Logs, events, Skill metadata, Artifact metadata, and reports must not contain plaintext tokens, sensitive host paths, or cross-tenant identifiers.
- **Launch boundary**: These documents define unified testable contracts, not approval to launch everything. Scope, thresholds, real models/Engines, capacity, and production samples require sign-off for each slice.
