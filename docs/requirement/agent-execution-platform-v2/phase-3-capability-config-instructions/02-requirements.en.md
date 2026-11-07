# Phase 3 · Capabilities, Configuration, and Instructions — Requirements

> Status: Pending review (implementation has not started)
> Created: 2026-11-02
> Basis: `01-business-goals.md` (G1–G4); architecture Sections 5, 6, 11, 14, and 17 Phase 3

## User Stories

**US-1 (Tenant administrator)**: As a tenant administrator, I want legacy Agents to run without edits and new Agents to select a supported Engine/Protocol, so the platform can evolve without a bulk migration.

**US-2 (Platform developer)**: As a platform developer, I want strict types and versioned resolution for every Engine configuration, so new Engines do not spread unrestricted dictionaries and conditionals through shared code.

**US-3 (Security administrator)**: As a security administrator, I want Effective capabilities computed only by the server from environment and policy, so Adapter declarations or client requests cannot become authorization.

**US-4 (Execution platform developer)**: As an execution platform developer, I want Engine-specific instruction rendering that reuses Summary/Memory business logic, so new Engines preserve context behavior.

**US-5 (QA/auditor)**: As QA or an auditor, I want configuration, capability, and policy snapshots for a Run, so I can replay allow/deny decisions and identify version differences.

**US-6 (Operator)**: As an operator, I want to disable Phase 3 completely without silently downgrading non-React configurations, so incidents can be rolled back safely.

## Functional Requirements

### FR-1 Legacy configuration compatibility and normalization

| Item | Description |
|---|---|
| Trigger | Load a draft, published version, execution snapshot, or diff; save or publish as a user |
| Input | Existing JSONB configuration that may lack `engine` and `react` and contain only legacy root fields |
| Output | Normalized execution configuration defaulting to `(engine_id=react, protocol_id=native, adapter_version=v1)`; original historical JSONB remains unchanged |
| Execution | Synchronous pure mapping; execution and configuration validation share one compatibility layer rather than separate default logic |
| Failure | Reject invalid legacy fields under existing rules with stable error codes; never drop unknown fields or relax `extra=forbid` for compatibility |
| Traceability | G1; US-1 |

### FR-2 Typed Engine selection and Engine-specific configuration

| Item | Description |
|---|---|
| Trigger | Agent draft create/update, publication, rollback, snapshot resolution, and Run admission |
| Input | Explicit `engine` triple, Registry-provided configuration schema, shared fields, and Engine-specific fields |
| Output | Validated immutable execution configuration; new canonical React configuration uses `react.model_profile_id/model_profile_version/max_model_rounds`, with legacy root fields as compatibility aliases |
| Execution | Strict Pydantic validation with extra fields forbidden; resolve the exact Adapter through the Registry, with no latest alias or arbitrary configuration dictionary |
| Failure | Reject unknown/incompatible triples, missing required fields, type errors, and unequal aliases; unavailable configuration cannot be published or started |
| Traceability | G1; US-1, US-2 |

### FR-3 Declared and Available capability resolution

| Item | Description |
|---|---|
| Trigger | Cache declarations on Adapter registration/health changes; resolve Available during Run orchestration and capability preview |
| Input | Trusted Adapter `EngineCapabilities`, Adapter/Protocol versions, deployment probes, and environment constraints |
| Output | Declared snapshot plus per-capability Available booleans, reason codes, and probe version/time; Available never exceeds Declared |
| Execution | Declarations are read-only; deployment probes have timeouts and caching, and the hot path starts no external Engine; `workspace_required=true` without Workspace is unavailable |
| Failure | Probe failure, timeout, or unknown version means unavailable/explicit rejection rather than allow; record secret-free reason codes |
| Traceability | G2; US-2, US-3 |

### FR-4 Policy and Effective capability resolution

| Item | Description |
|---|---|
| Trigger | After Available resolution and before ExecutionRequest construction; UI capability preview uses the same resolver |
| Input | Available capabilities, platform capability ceiling, trusted tenant policy, published Agent `disabled_capabilities`, and trusted Execution context |
| Output | Per-capability policy decisions, source/version/reason codes, and final Effective values; once any layer is false, no later layer can restore true |
| Execution | Server-side monotonic narrowing; Agent/Execution can only disable or tighten, and client Run requests provide neither policy nor Effective input |
| Failure | Missing policy uses existing least-privilege defaults; unknown policy version or denial of a required capability blocks start; never fall back across Engines automatically |
| Traceability | G2; US-3, US-6 |

### FR-5 Client-input and public-capability-view anti-elevation controls

| Item | Description |
|---|---|
| Trigger | Run API, Agent API, capability preview/API serialization, and ExecutionRequest construction |
| Input | Requests that may forge `declared/available/effective_capabilities`, policy versions, host fields, or unauthorized Engine configuration |
| Output | Strict rejection of unknown fields; public views expose only Effective values and necessary reasons visible to the current principal, never internal probes or policy secrets |
| Execution | Tenant/actor comes from the authenticated context; the server constructs ExecutionRequest entirely from snapshots and never passes client objects through |
| Failure | Elevation attempts return 4xx/stable domain errors and a security audit; forged values must never be executed after merely being ignored |
| Traceability | G2; US-3 |

### FR-6 Execution configuration, capability, and policy snapshots

| Item | Description |
|---|---|
| Trigger | After Run creation/orchestration resolution and before Adapter `start`; read during historical Run queries and audits |
| Input | Normalized execution configuration, Declared/Available/Effective capabilities, policy decisions and versions, Agent publication version, and Instruction Provider identity |
| Output | Immutable JSONB snapshots on `runtime_runs`, correlated by Run ID; the Engine triple is included in the execution configuration snapshot |
| Execution | Persist in one durability boundary before start; snapshots have schema versions, size limits, and sensitive-field denylists, and are not exposed directly by public APIs |
| Failure | Serialization, size, or required-field validation failure fails the Run without Adapter start; historical nulls mean pre-Phase 3 records and are not backfilled with invented values |
| Traceability | G4; US-5 |

### FR-7 Instruction Provider and React compatibility

| Item | Description |
|---|---|
| Trigger | After the Orchestrator obtains history and rendered Summary/Memory and prepares Adapter input |
| Input | System Prompt, reply-language rule, Conversation Context, rendered Summary/Memory, and optional Skill/Workspace context placeholders |
| Output | Engine-native instructions with provider ID/version; React preserves System → Summary → Memory → kept history → user ordering |
| Execution | Providers only adapt formats; MemoryInjection retains reads, switches, budgets, and wording, and Providers neither query memory stores nor inject twice |
| Failure | Unknown Provider or rendering-contract errors block start; empty or disabled Summary/Memory uses existing fallback and creates no empty messages |
| Traceability | G3; US-4 |

### FR-8 Configuration and capability display, audit, and rollback

| Item | Description |
|---|---|
| Trigger | Administrator edits/previews an Agent, auditor views a Run, or operator changes the Phase 3 flag or rolls back |
| Input | Typed draft, read-only Effective preview, snapshots, deployment flag, and audit events |
| Output | Internationalized forms/errors, non-editable Effective view, and configuration/policy version audit; disabling the flag restores Phase 2 React behavior |
| Execution | All user-visible text uses i18n; rollback neither deletes snapshots nor rewrites Agent JSONB in bulk, and non-React is explicitly rejected while disabled instead of running as React |
| Failure | Probe failure displays unavailable rather than available; non-React with the flag off returns `execution_phase3_disabled`; audits contain no secrets |
| Traceability | G1, G2, G4; US-1, US-3, US-5, US-6 |

### FR-9 Configuration switches

| Configuration | Level | Default | Description |
|---|---|---|---|
| `execution_phase3_enabled` | Global settings | `false` | Phase 3 master switch; off permits only the Phase 2 React path and never silently downgrades non-React |
| `execution_capability_policy_version` | Global settings / trusted Policy Provider | `v1` | Server-side default policy version; clients cannot set it |
| `execution_capability_probe_timeout_seconds` | Global settings | `2.0` | Timeout for each bounded deployment probe; timeout can mean unavailable |
| `execution_capability_probe_cache_seconds` | Global settings | `30` | Availability-result cache TTL; declaration and policy changes invalidate relevant entries |
| `execution_snapshot_max_bytes` | Global settings | `65536` | Serialization limit per snapshot type; exceeding it blocks start |
| `engine` | AgentConfig JSONB | `{engine_id:react,protocol_id:native,adapter_version:v1}` | Only the compatibility layer supplies the default; new values must be registered exactly |
| `react` | AgentConfig JSONB | Derived from legacy root fields | Typed React configuration; unequal legacy aliases are rejected |
| `disabled_capabilities` | Published AgentConfig / trusted Agent policy | `[]` | Can only further disable Available capabilities, never grant or override platform/tenant policy |

## Non-Functional Requirements

- **Performance**: cache registries, schemas, and trusted policy first; target at most 50ms p95 added resolution time, bound every probe, and make no external Engine calls on the request hot path.
- **Compatibility**: preserve legacy drafts, published snapshots, model/tool validation, Summary/Memory switches, and public Run/SSE behavior; historical null snapshots have explicit semantics.
- **Multi-tenancy**: query Agents, policy, and Runs by authenticated tenant and business/workspace scope; cross-tenant configuration, previews, snapshots, and audits are unreachable.
- **Security**: capability is not authorization; snapshots and logs contain no API keys, tokens, raw customer memory, plaintext credential references, or internal host paths.
- **Auditability**: snapshots include schema/provider/policy versions and per-capability reason codes; decisions are replayable without rerunning side-effecting Engines.
- **Reversibility**: the master flag rolls back without a database downgrade; disabling the new path neither deletes nor rewrites history and never runs a non-React request on another Engine.

## Acceptance Criteria

| # | Scenario | Expected result | Traceability |
|---|---|---|---|
| AC-1 | Load Phase 0 legacy drafts, published snapshots, and default/boundary fixtures, then execute React | Every valid fixture defaults to `react/native/v1`; model/tool/summary/memory behavior is unchanged and historical JSONB is not rewritten | FR-1; G1; US-1 |
| AC-2 | Save valid `react` configuration, then submit type errors, extra fields, unknown triples, and unequal old/new aliases | Valid configuration passes and resolves exactly; every invalid configuration is rejected consistently before publication or Adapter start | FR-2; G1; US-2 |
| AC-3 | Simulate declared support with missing deployment, incompatible version, probe timeout, and `workspace_required` without Workspace | Available is false per item with reason codes and never exceeds Declared; missing required capabilities block start | FR-3; G2; US-2, US-3 |
| AC-4 | Disable a capability at platform, tenant, Agent, and Execution layers, then attempt to re-enable it at a lower layer | Effective remains false; snapshots record each source, version, and reason, with no exception to monotonic narrowing | FR-4; G2; US-3 |
| AC-5 | Forge Declared, Available, Effective, policy versions, and host-internal fields in Run/Agent/API requests, and attempt cross-tenant preview | Requests are rejected or invalid under strict schemas, successful elevations are zero, cross-tenant access is unreachable, and security audits exist | FR-5; G2; US-3 |
| AC-6 | Inspect snapshots for completed, failed, cancelled, and timed-out Runs, and construct oversized/secret-containing snapshot candidates | Normal Runs have complete immutable snapshots before Adapter start; invalid snapshots prevent start; historical nulls remain, and public responses leak no internals | FR-6; G4; US-5 |
| AC-7 | Compare React messages for empty, disabled, Summary, Memory, Summary+Memory, and history-truncation scenarios | Ordering, wording, switches, and budgets have zero diff from the Phase 0 baseline, with no duplicate injection or empty messages | FR-7; G3; US-4 |
| AC-8 | Render the same Summary/Memory inputs through a test Engine Provider whose format differs from React | Engine formats vary independently, business rendering runs once, and native formats are not forced into ReAct messages | FR-7; G3; US-4 |
| AC-9 | Edit configuration and preview capabilities as an administrator, then change platform/tenant policy | Forms and errors are fully internationalized; Effective remains read-only and updates from server recomputation, with no UI elevation path or internal snapshot disclosure | FR-4, FR-5, FR-8; G1, G2; US-1, US-3 |
| AC-10 | Enable and then disable `execution_phase3_enabled`, run legacy React and non-React configurations, and inspect historical snapshots | Legacy React returns to Phase 2 behavior; non-React fails explicitly without fallback; historical snapshots remain readable with no migration rollback | FR-8, FR-9; G4; US-6 |
| AC-11 | Upgrade the planned migration from the `0052` baseline, verify old/new rows and concurrent reads/writes, and test paired downgrade only on a disposable database | Exactly five nullable snapshot columns are added; legacy behavior is unaffected; actual head/down_revision was revalidated and no historical migration changed | FR-6; G1, G4; US-5, US-6 |
