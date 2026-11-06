# Phase 3 · Capabilities, Configuration, and Instructions — Business Goals

> Status: Pending review (implementation has not started)
> Created: 2026-11-02
> Basis: `docs/architecture/agent-execution-platform-v2.md`, Sections 5, 6, 11, 14, 15, 17 Phase 3, 19, and 22; Phase 0–2 planning documents
> Estimated effort: ~2 weeks (re-estimate after the Phase 0 baseline)
> Dependencies: Phase 0 compatibility baseline complete; Phase 1 Execution Contract and Registries and Phase 2 React Provider and Orchestrator accepted

## Problems to Solve

### Problem 1: Agent configuration cannot safely express multi-Engine selection

The current `AgentConfig` in `backend/src/agent_platform/business_capabilities/agent_config/service.py` contains only ReAct-related fields, while `backend/src/agent_platform/applications/platform_runtime/runtime_factory.py` always constructs `RuntimeEngine`. Adding an unrestricted dictionary would allow unknown Engines, invalid types, and version drift into published snapshots, with no guarantee that legacy configurations remain loadable.

### Problem 2: Technical capability, environment availability, and authorization lack one decision chain

The architecture requires separate Declared, Available, Policy, and Effective stages, but no such chain exists today. Trusting Adapter declarations or client fields directly could mistake “supports terminal execution” for “is authorized to use a terminal,” while the UI, Orchestrator, and audit trail reach different conclusions for the same Run.

### Problem 3: Instructions and Summary/Memory injection are coupled to ReAct messages

`backend/src/agent_platform/core_platform/agent_runtime/engine.py` assembles SystemMessage objects directly. `worker.py` and `business_capabilities/memory/injection.py` already own summary and customer-memory retrieval, rendering, and switches. Without an Instruction Provider boundary, a new Engine must either reuse unsuitable ReAct structures or duplicate memory logic and diverge behaviorally.

### Problem 4: An execution lacks an immutable decision snapshot

The existing `runtime_runs.config` stores the Run input snapshot, but there are no separate snapshots for resolved execution configuration, layered capabilities, and policy. After publication, deployment probes, or policy changes, it is difficult to explain why a historical Run allowed or denied a capability.

## Business Goals

| Goal | Description |
|---|---|
| G1: Compatible, typed multi-Engine configuration | Resolve legacy configuration to `(react,native,v1)` by default; validate new configuration against the exact Engine/Protocol/Adapter triple while retaining the existing JSONB draft and publication chain |
| G2: Server-side capability governance | Establish a monotonically narrowing Declared → Available → Policy → Effective chain; neither clients nor Adapters can bypass environment or policy restrictions |
| G3: Replaceable Engine instruction rendering | Adapt instructions to Engine-specific formats through an Instruction Provider while reusing existing Summary/Memory switches, rendered text, ordering, and fallback behavior |
| G4: Traceable and reversible execution decisions | Persist resolved configuration, capability, and policy snapshots for every Run using the Phase 3 path; flag rollback must not affect historical snapshot reads |

## Success Metrics

| Metric | Baseline (current) | Target |
|---|---|---|
| Legacy Agent draft and published-snapshot compatibility | Pending Phase 0 measurement with real redacted and boundary fixtures | 100% of valid fixtures load, normalize, republish, and execute; historical JSONB is not rewritten in bulk |
| Rejection rate for invalid or unknown execution configuration | Pending Phase 0 inventory of current validation coverage | 100% rejection of unknown triples, type errors, extra fields, conflicting aliases, and unavailable required capabilities, with stable error codes |
| Successful client capability escalations | Pending Phase 0 inventory of request trust boundaries | Zero successful escalations through forged Declared/Available/Effective values, policy, or Engine-internal fields |
| Decision-snapshot completeness for Phase 3 Runs | Pending Phase 0 measurement of current Run metadata coverage | 100% snapshot coverage for completed, failed, cancelled, and timed-out Runs on the new path; Adapter start is blocked if snapshots are missing |
| React instruction compatibility regression pass rate | Pending Phase 0 baseline for Summary/Memory message sequences | Zero diff in existing message order and wording for empty, disabled, summary, customer-memory, and combined scenarios |
| Added configuration and capability resolution latency | Pending Phase 0 measurement of Run admission/claim latency | With cached registries and policy, p95 added server-side resolution time is at most 50ms per Run; external availability probes stay off the synchronous hot path |

## Scope

**Included**:

- Add Engine selection and typed Engine-specific configuration to the existing AgentConfig JSONB drafts and published snapshots, without a new Agent configuration table.
- Map legacy fields to normalized execution configuration and fix the default triple at `react/native/v1`.
- Resolve capability declarations, deployment availability, policy, and Effective capabilities, and expose a read-only view.
- Implement the Instruction Provider contract, React Provider, and test Provider while reusing existing Summary/Memory rendering results.
- Plan migration `0053_agent_execution_metadata` to add only nullable execution configuration, layered capability, and policy snapshot fields to `runtime_runs`.
- Design configuration, APIs, frontend types/display, auditing, tests, rollout, and rollback.

**Excluded** (later phases / explicitly not in scope):

- Runtime Host, real external processes, Execution Workdir, or Sandbox (Phase 4).
- Codex CLI/App-Server and its production instruction files or Skill mounts (Phase 5).
- Credential Broker, strong sandboxing, network egress, Fencing/Outbox, and other complete security/reliability capabilities (Phase 6).
- Separate Task/Execution tables, relational decomposition of Agent configuration, implicit latest Adapter selection, or automatic cross-Engine fallback.
- A general tenant-policy administration console; this phase integrates only trusted Policy Providers and static/existing policy sources.

## Risks and Constraints

- **Ambiguous dual-write configuration**: legacy root fields and new `react` fields can conflict; equal values may normalize, but different values must be rejected rather than silently choosing one.
- **Availability-probe instability**: external process or network probes can block execution; Phase 3 uses only bounded, cached deployment probes, treating failure as unavailable with a recorded reason.
- **Unclear policy provenance**: missing trusted sources must never default to allow; platform policy is a ceiling, and tenant/Agent/Execution policy can only narrow it.
- **Snapshot disclosure**: resolved configuration can contain internal identifiers or prompts; snapshots must exclude credentials, raw customer memory, and host secrets, and public responses must not expose internal snapshots directly.
- **Instruction regressions**: Provider refactoring can reorder or duplicate Summary/Memory; React must pass Phase 0 message-by-message compatibility tests.
- **Compatibility**: historical `agents.draft` and `agent_versions.config` remain untouched; old records acquire normalized forms only through normal user save/publication, never through a default-backfill migration.
- **Migration constraint**: `0053` is a planned identifier; revalidate the head and `down_revision` before implementation and never modify applied migration `0052` or earlier history.
