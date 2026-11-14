# Phase 3 · Capabilities, Configuration, and Instructions — Requirements

> Status: design calibrated (implementation not started; G1–G4, US-1–US-6, FR-1–FR-9, AC-1–AC-11 retained)
> Created: 2026-11-02
> Revised: 2026-11-13 (FR-9 adds six capability settings rows, per R-18/R-19)
> Revised: 2026-11-12 (code reality, preview contract, start barrier, flag matrix, and migration)
> Basis: `01-business-goals.md` (G1–G4); architecture Sections 5, 6, 11, 14, and 17 Phase 3

## User Stories

**US-1 (tenant administrator)**: As a tenant administrator, I want existing Agents to run unchanged and new Agents to select a supported Engine/Protocol, enabling gradual evolution without bulk migration.

**US-2 (platform developer)**: As a platform developer, I want strict typed and versioned configuration per Engine so new Engines do not spread unrestricted dictionaries and conditionals through common code.

**US-3 (security administrator)**: As a security administrator, I want Effective capabilities computed only by the server from environment and policy, so Adapter declarations and client requests cannot grant authorization.

**US-4 (execution-platform developer)**: As an execution-platform developer, I want Engine-specific instruction rendering with shared Summary/Memory business logic, preserving context behavior across Engines.

**US-5 (QA/auditor)**: As QA or an auditor, I want configuration, capability, and policy snapshots for a Run so I can replay allow/deny decisions and locate version differences.

**US-6 (operator)**: As an operator, I want Phase 3 to be globally disableable without silently downgrading non-React configurations, enabling safe rollback.

## Functional Requirements

### FR-1 Legacy configuration compatibility and normalization

| Item | Description |
|---|---|
| Trigger | Loading drafts, published versions, execution snapshots, or diffs; saving/publishing |
| Input | Existing JSONB configuration, potentially without `engine`/`react` and containing only legacy root fields |
| Output | Normalized `ExecutionConfig` defaulting to `(react,native,v1)`; original historical JSONB unchanged |
| Processing | Shared synchronous pure mapping for drafts, publication, preview, execution, and diffs; in-memory normalization never causes UPDATE on GET/normal reads |
| Failure | Reject invalid legacy fields with stable errors; never drop unknown fields or relax `extra=forbid` |
| Trace | G1; US-1 |

### FR-2 Typed Engine selection and Engine-specific configuration

| Item | Description |
|---|---|
| Trigger | Draft create/update, publish, rollback, snapshot parsing, preview, and Run admission |
| Input | Explicit `engine` triple, Registry configuration schema, shared and Engine-specific fields |
| Output | Strict immutable `ExecutionConfig`; new React shape uses `react.model_profile_id/model_profile_version/max_model_rounds`, with legacy roots as aliases |
| Processing | Strict Pydantic validation; exact Registry metadata validates drafts without latest or arbitrary dictionaries; execution alone resolves a fresh Adapter |
| Failure | Reject unknown/incompatible triples, missing fields, type errors, and unequal aliases; never publish/start invalid configuration or substitute another Engine |
| Trace | G1; US-1, US-2 |

### FR-3 Declared and Available capability resolution

| Item | Description |
|---|---|
| Trigger | Registration metadata defines Declared; Run orchestration and preview read Available from trusted deployment probes |
| Input | Trusted registered declarations, exact versions, deployment probe, and Workspace availability generation |
| Output | Declared snapshot and per-capability Available booleans, stable reasons, probe version/time; Available never exceeds Declared |
| Processing | Read-only declarations; server-controlled timeout, bounded cache, and invalidation; hot paths start no external Engine; `workspace_required=true` is unavailable without Workspace |
| Failure | Missing/failed/timed-out/stale/unknown-version probes mean unavailable or explicit rejection, with no raw exception or secret leakage |
| Trace | G2; US-2, US-3 |

### FR-4 Policy and Effective capability resolution

| Item | Description |
|---|---|
| Trigger | After Available and before ExecutionRequest; preview and Runs share the resolver |
| Input | Available, platform ceiling, trusted tenant policy, published Agent `disabled_capabilities`, trusted Execution restrictions |
| Output | Per-capability Policy decisions, source/version/reasons, and final Effective; false at any layer cannot become true below |
| Processing | Server-side least-privilege monotonic narrowing; Agent/Execution only disable; public Run input has no Policy/Effective fields |
| Failure | Unknown capabilities/policy versions fail closed; missing/untrusted policy grants only the minimum; denied required capabilities block start without Engine fallback |
| Trace | G2; US-3, US-6 |

### FR-5 Anti-elevation for client input and public capability views

| Item | Description |
|---|---|
| Trigger | Run API, Agent API, `POST /api/v1/agents/execution-preview`, and ExecutionRequest construction |
| Input | Requests potentially forging `declared/available/effective/effective_capabilities`, policy versions, host fields, or unauthorized configuration |
| Output | Strict rejection of unknown/forged fields; preview returns only Engine identity, safe schema metadata, and `{name,effective,reason_code}`, never internal snapshots, raw probes/policy, or paths |
| Processing | Tenant/actor/business/workspace come from authentication; optional `agent_id` loads under the same scope and unsaved drafts are supported; the server alone builds ExecutionRequest |
| Failure | Schema errors retain 422 behavior and scoped missing Agents retain 404; elevation attempts yield stable domain errors/security audit; preview creates no Run, Adapter, or future authorization |
| Trace | G2; US-3 |

### FR-6 Execution configuration, capability, and policy snapshots

| Item | Description |
|---|---|
| Trigger | After Phase 3 orchestration resolution and before `Adapter.start`; historical audit is read-only |
| Input | Normalized configuration, Declared, Available, Effective, Policy decisions, and Agent/Provider versions |
| Output | Five nullable `runtime_runs` JSONB columns for execution config, Declared, Available, Effective, and execution policy; the Engine triple belongs to configuration |
| Processing | Versioned DTOs, per-type size limits, recursive denylist, and one DB commit before Adapter/Runtime/tool/model side effects; completed/failed/cancelled/timed-out Runs never rewrite them |
| Failure | Serialization, sensitive scanning, size, or DB commit failure fails the Run with `Adapter.start=0`; existing claim still publishes `run.started` first; historical NULL means pre-Phase 3 and is not backfilled |
| Trace | G4; US-5 |

### FR-7 Instruction Provider and React compatibility

| Item | Description |
|---|---|
| Trigger | After Orchestrator obtains history/rendered Summary/Memory and before creating the React runner |
| Input | `InstructionInput`: computed system prompt, reply-language result, history/current input, rendered Summary/Memory, controlled Engine placeholders |
| Output | Provider ID/version and Engine-native instructions; React retains System → Summary → Memory → kept history → current user exactly |
| Processing | Compute system prompt and Summary/Memory business rendering once each; Providers only adapt format and do not query Memory/rebuild prompts; ReactAdapter creates its runner after preparation |
| Failure | Unknown Provider or rendering errors prevent Adapter.start; empty/disabled states retain existing behavior without empty messages or changes to dual emit/ack/Outcome |
| Trace | G3; US-4 |

### FR-8 Configuration/capability display, audit, and rollback

| Item | Description |
|---|---|
| Trigger | Agent editing/preview, audit, flag changes, or application rollback |
| Input | Typed drafts, read-only Effective, private snapshots, both flags, and audit events |
| Output | Modest extraction inside the existing React 19 + antd v6 AgentsPage; complete `zh-CN/zh-TW/en/hi` text; Effective is read-only and disabled capabilities only narrow |
| Processing | Retain OpenAPI conventions; rollback deletes no snapshots and rewrites no JSONB; Phase 3 off exactly retains the deployment's original Phase 2 on/off path |
| Failure | Probe failures display unavailable/stable reasons; non-React in every off state returns `execution_phase3_disabled`; preview neither creates nor authorizes a Run, and audit contains no secrets |
| Trace | G1, G2, G4; US-1, US-3, US-5, US-6 |

### FR-9 Settings

| Setting | Layer | Default | Description |
|---|---|---|---|
| `execution_phase3_enabled` | global settings | `false` | Phase 3 switch; forms a four-state matrix with `execution_orchestrator_enabled` |
| `execution_capability_policy_version` | global settings / trusted Policy Provider | `v1` | Default policy version; not client-settable |
| `execution_capability_probe_timeout_seconds` | global settings | `2.0` | Bounded deployment probe timeout |
| `execution_capability_probe_cache_seconds` | global settings | `30` | Probe cache; identity/declaration/probe/Workspace generation changes invalidate it |
| `execution_capability_policy_cache_seconds` | global settings | `30` | Policy/Effective cache; tenant/Agent/version/policy revision/disabled/restriction digest changes invalidate it |
| `execution_snapshot_max_bytes` | global settings | `65536` | UTF-8 JSON limit **per snapshot type**; excess prevents start |
| `execution_capability_policy_timeout_seconds` | global settings | `2.0` | Bounded policy-source wait (R-18), `gt=0, le=10`, same ceiling as the probe |
| `execution_capability_probe_max_concurrency` | global settings | `4` | Per-process probe concurrency limit (R-18), `ge=1, le=32` |
| `execution_capability_cache_capacity` | global settings | `512` | Entry bound shared by the Available and Policy LRU caches (R-18), `ge=16, le=100000` |
| `execution_capability_cache_retry_seconds` | global settings | `5.0` | Same-source interval for cache error retry and warmer failure backoff (R-18), strictly positive, `le=60` |
| `execution_capability_warm_refresh_seconds` | global settings | `10.0` | Controlled background warmer cadence (R-18), `gt=0, le=300`; must stay below both cache TTLs when Phase 3 is on |
| `execution_capability_deployment_identity` | global settings | `default` | Deployment identity label in the Available/Policy keys (R-18), `Slug` pattern; identical across processes of one logical deployment |
| `engine` | AgentConfig JSONB | `{react,native,v1}` | Defaulted only by compatibility; new values require exact registration |
| `react` | AgentConfig JSONB | derived from legacy roots | Typed configuration; unequal aliases are rejected |
| `disabled_capabilities` | published AgentConfig / trusted Agent policy | `[]` | Only disables; cannot grant or override ceiling/tenant policy |

All newly listed `execution_capability_*` fields above are non-secret and safe by default; the `*_cache_seconds` and `*_retry/refresh_seconds` lower bounds are strictly greater than zero (R-19—Phase 3 offers no "TTL 0 / never expires" mode). When `execution_phase3_enabled=true`, settings validate `warm_refresh < min(probe, policy TTL)` and fail startup otherwise.

Flag semantics:

| `execution_phase3_enabled` | `execution_orchestrator_enabled` | Behavior |
|---|---|---|
| false | false | Exact original Phase 2 legacy Runtime path, with no Phase 3 probing/snapshots |
| false | true | Exact original Phase 2 Orchestrator React path, with no Phase 3 probing/snapshots |
| true | false | Unavailable/misconfigured; fail closed, never silently use legacy React |
| true | true | Phase 3 resolution, snapshots, Providers, and Orchestrator path |

Non-React in every Phase 3-off state returns `execution_phase3_disabled` with zero React Adapter calls.

## Non-Functional Requirements

- **Performance**: collect at least 100 valid paired samples on the warmed real resolver/admission path; added p95 ≤50ms; probes never block the synchronous hot path without bounds.
- **Compatibility**: preserve old drafts/publications, model/tool validation, Summary/Memory, public Run/SSE, and `run.started` ordering; historical NULL semantics remain explicit.
- **Multi-tenancy**: scope Agents, policies, Runs, and previews by authenticated tenant and business/workspace; cross-scope retains existing not-found behavior.
- **Security**: snapshots recursively reject secrets, raw customer memory, and host details; least privilege by default; preview and Adapter declarations are not authorization.
- **Auditability**: private snapshots contain schema/provider/policy versions and reasons; decision replay is read-only and public responses are allowlisted.
- **Rollback**: disabling the new path needs no downgrade, deletes/rewrites no history, and never substitutes an Engine for non-React.

## Acceptance Criteria

| # | Scenario | Expected | Trace |
|---|---|---|---|
| AC-1 | Load Phase 0 legacy drafts/publications and default/boundary fixtures, then run React | Valid fixtures default to `react/native/v1`; model/tool/Summary/Memory unchanged; historical JSONB untouched; canonical diffs contain no default noise | FR-1; G1; US-1 |
| AC-2 | Save valid `react`, then submit type errors, extra fields, unknown triples, and unequal aliases | Valid configuration passes; invalid input is stably rejected; metadata validation instantiates no Adapter | FR-2; G1; US-2 |
| AC-3 | Declared support with missing/incompatible deployment, probe timeout, and no Workspace | Available=false with reasons and never exceeds Declared; missing required capabilities block start | FR-3; G2; US-2, US-3 |
| AC-4 | Disable at each layer, then re-enable below | Effective remains false; snapshots explain source/version/reason and monotonic narrowing | FR-4; G2; US-3 |
| AC-5 | Forge layered fields in Run/Agent/preview and attempt cross-tenant preview | Strict rejection and zero elevation; cross-tenant inaccessible with security audit; preview creates no Run | FR-5; G2; US-3 |
| AC-6 | Inspect snapshots for four terminal states and construct oversized/nested-secret/DB-failure cases | Five snapshots commit once before Adapter.start and remain immutable; failures mean start=0; historical NULL stays and public responses disclose nothing | FR-6; G4; US-5 |
| AC-7 | Compare React messages for empty, disabled, Summary, Memory, combined, and truncation cases | Zero baseline diff in order/text/budget, no duplicate/empty messages, and one business-rendering pass | FR-7; G3; US-4 |
| AC-8 | Render a different format with a test Provider using the same input | Independent format, one business-rendering pass, no forced ReAct conversion or second Memory rendering | FR-7; G3; US-4 |
| AC-9 | Edit/preview, change policy, and cover four locales plus M1–M3 | Effective is read-only/server-recomputed, disabled only narrows, four locales complete, no elevation/internal snapshots | FR-4, FR-5, FR-8; G1, G2; US-1, US-3 |
| AC-10 | Exercise the flag matrix with React/non-React and inspect history | Off preserves the deployment's original Phase 2 path; on+orchestrator-off fails closed; non-React never silently degrades; history remains readable | FR-8, FR-9; G4; US-6 |
| AC-11 | Upgrade `0058_agent_execution_metadata` from its planned predecessor; test old/new rows, concurrency, and disposable downgrade | Only five nullable columns; dynamically revalidate head/down_revision before implementation, currently `0057_industry_pack_runtime`; never edit historical migrations | FR-6; G1, G4; US-5, US-6 |
