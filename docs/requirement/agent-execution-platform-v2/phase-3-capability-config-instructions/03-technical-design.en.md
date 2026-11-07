# Phase 3 · Capabilities, Configuration, and Instructions — Technical Design

> Status: Pending review (implementation has not started; all modules and migrations below are planned)
> Created: 2026-11-02
> Basis: `01-business-goals.md` (G1–G4), `02-requirements.md` (FR-1–FR-9, AC-1–AC-11), architecture Sections 3, 5, 6, 11, 14–17, and 21
> Current-state review: `integration` working tree on 2026-11-02; migration head is `0052_memory_tasks_tenant_index`

## 1. Current-State Mapping and Design Decisions

| Current evidence | Verified finding | Decision for this phase |
|---|---|---|
| `business_capabilities/agent_config/service.py` | `AgentConfig(extra=forbid)` uses the existing JSONB draft/publication chain and has no Engine fields | Extend the same model and JSONB, with no Agent configuration table or historical snapshot edits; add one compatibility normalization entry point |
| `applications/platform_runtime/runtime_factory.py` | `for_run()` always constructs `RuntimeEngine`, and `effective()` combines system prompt and language rules | After Phase 2, the Orchestrator/Registry supplies the Adapter; compute the effective React prompt once and pass it to the Instruction Provider |
| `core_platform/agent_runtime/worker.py`, `engine.py` | Worker obtains rendered Summary/Memory, and Engine fixes SystemMessage ordering | Preserve MemoryInjection business ownership; Providers replace only format adaptation, not memory reads, budgets, or completion write-back |
| `business_capabilities/memory/injection.py` | Summary/Memory switches, rendering, fallback, and injection logs already exist | Reuse their results unchanged; React and test Providers must not implement another wording or query path |
| `core_platform/agent_runtime/repository.py`, migrations `0001/0002` | Run has `config` JSONB; Agent drafts and versions use `agents.draft` and `agent_versions.config` | Add separate Run decision-snapshot columns; retain AgentConfig in existing JSONB and do not confuse input and resolved-decision snapshots |
| `platform_settings/settings.py` | `AGENT_` prefix, Pydantic Settings, and environment overrides are established patterns | Follow them for new flags; secrets remain in separate environment/credential facilities, never snapshots or sample configuration |
| Phase 1–2 plans | Registry, Capabilities, ExecutionRequest, and Orchestrator are prerequisites and do not yet exist in the current tree | Integrate only with their accepted contracts; if those contracts change, revise and review this design first rather than adding Engine branches to Worker |

## 2. Change Overview

| Layer | File | Change |
|---|---|---|
| Migration | `backend/migrations/versions/0053_agent_execution_metadata.py` | Plan five nullable Run decision-snapshot columns; revalidate head/down_revision before implementation |
| Configuration model | `backend/src/agent_platform/core_platform/agent_execution/config/execution_config.py` | Define versioned ExecutionConfig, EngineSelector, ReactConfig, and strict validation |
| Compatibility | `backend/src/agent_platform/core_platform/agent_execution/config/legacy_config.py` | Map legacy root fields, apply defaults, and detect alias conflicts without side effects |
| Capabilities | `backend/src/agent_platform/core_platform/agent_execution/capability/capability_resolver.py` | Resolve Declared/Available/Policy/Effective and invalidate caches |
| Policy | `backend/src/agent_platform/core_platform/agent_execution/capability/capability_policy.py` | Trusted Policy Provider, layered narrowing, and source/reason snapshots |
| Instructions | `backend/src/agent_platform/core_platform/agent_execution/instructions/instruction_provider.py` | Provider contract, InstructionInput/RenderedInstructions, and version identity |
| React instructions | `backend/src/agent_platform/core_platform/agent_execution/instructions/react_instruction_provider.py` | Preserve existing React message ordering and wording |
| Rendering | `backend/src/agent_platform/core_platform/agent_execution/instructions/instruction_renderer.py` | Assemble shared fragments and empty-state rules without reading Memory Store |
| Orchestration | `backend/src/agent_platform/core_platform/agent_execution/orchestration/orchestrator.py` | Enforce configuration → capabilities → snapshots → instructions → Adapter start |
| Context | `backend/src/agent_platform/core_platform/agent_execution/orchestration/execution_context.py` | Server-only tenant/actor/policy/Execution context |
| Agent configuration | `backend/src/agent_platform/business_capabilities/agent_config/service.py` | Integrate normalized configuration, Registry schema validation, publication/rollback/preview compatibility |
| Run persistence | `backend/src/agent_platform/core_platform/agent_runtime/repository.py` | Persist five snapshots before Adapter start; read historical nulls and internal snapshots |
| Composition | `backend/src/agent_platform/applications/platform_runtime/runtime_composition.py` | Register configuration/capability/policy/Instruction Providers through the composition root |
| Configuration | `backend/src/agent_platform/core_platform/platform_services/platform_settings/settings.py` | Add FR-9 flags, probe controls, and snapshot limits |
| Frontend | `frontend/src/shared/api/client.ts`, `frontend/src/features/agents/AgentsPage.tsx` | Typed Engine configuration, read-only Effective preview, and error display |
| i18n | `frontend/src/i18n/index.ts` and actual split language resources | Internationalize every new user-visible string in all supported languages; no hardcoded text |
| Deployment example | `deploy/production/.env.example` | Add non-secret flag placeholders and documentation only, with Phase 3 off by default |
| Tests | `backend/tests/test_agent_execution_config.py`, `test_capability_resolver.py`, `test_instruction_providers.py`, `test_agent_execution_metadata_migrations.py` | Planned deterministic and migration tests; see 04 for cases |

## 3. Data Model

### 3.1 Migration `0053_agent_execution_metadata.py`

> Planned identifier: its direct predecessor is the current head `0052_memory_tasks_tenant_index`. If the head changes before implementation, create the correct new linkage and revise this document; never edit migration history.

| Table | New column | Type/nullability | Purpose |
|---|---|---|---|
| `runtime_runs` | `execution_config_snapshot` | JSONB NULL | Normalized configuration, Agent version, Engine triple, and Instruction Provider version |
| `runtime_runs` | `declared_capabilities_snapshot` | JSONB NULL | Trusted Adapter declarations and contract version |
| `runtime_runs` | `available_capabilities_snapshot` | JSONB NULL | Environment decisions, reason codes, probe version, and timestamp |
| `runtime_runs` | `effective_capabilities_snapshot` | JSONB NULL | Final per-capability booleans and resolution digest |
| `runtime_runs` | `execution_policy_snapshot` | JSONB NULL | Policy version, sources, and layered allow/deny decisions |

Design points:

- Add columns only, with no defaults or backfill; NULL on old rows explicitly means pre-Phase 3, and existing reads/writes need not know the new columns.
- Add no columns to `agents`/`agent_versions` and no separate Task/Execution, Engine Session, RuntimeHost, or Workdir tables.
- Keep the Engine triple inside the execution configuration snapshot and add no query indexes in this phase; evaluate indexes only when real filtering needs arise.
- Paired downgrade drops exactly these five columns and is rehearsed only on a disposable database; production rollback retains columns and history.
- The application writes each Run snapshot once and never updates it when configuration, policy, or probes change; public APIs continue to return allowlisted fields.

### 3.2 AgentConfig JSONB Structure

| Area | Fields | Rules |
|---|---|---|
| Shared | Existing system/tool/knowledge/reply_language/summary/memory fields | Preserve names and semantics to avoid unrelated migration |
| Selection | `engine.engine_id/protocol_id/adapter_version` | Default `react/native/v1`; exact registration required and latest forbidden |
| React | `react.model_profile_id/model_profile_version/max_model_rounds` | Strict types and existing bounds; equal legacy aliases are readable and unequal aliases rejected |
| Agent policy | `disabled_capabilities` | Deduplicated registered capability names only; narrowing only, with no `effective_capabilities` input |

Save or publication persists a normalized new draft/version; reading a historical object causes no database UPDATE. Rolling back to an old published version validates it through the compatibility layer without modifying the target version.

### 3.3 Snapshot Content and Sensitive Boundaries

| Snapshot | Required content | Explicitly excluded |
|---|---|---|
| Execution Config | schema_version, agent_id/version, engine, effective shared and Engine-specific values, instruction_provider id/version | Tokens, API keys, plaintext credentials, raw Summary/Memory, and host environment |
| Declared | schema_version, capabilities, adapter contract/version | Client-supplied values and process/path details |
| Available | Per-capability available/reason_code, probe_version, probed_at | Raw probe stderr, network secrets, and internal command lines |
| Policy | schema_version, policy_version, layered source/reason/allowed, and source versions | Secret policy content, other tenants' rules, and authentication material |
| Effective | schema_version, final capabilities, resolution_digest | External values that can override results and raw customer context |

Apply JSON size limits and recursive sensitive-key checks to every snapshot. Digests support correlation but are not a redaction mechanism; never persist sensitive plaintext and rely on log masking afterward.

## 4. Core Flows

### 4.1 Configuration load and publication (`legacy_config.py`, `service.py`)

```
Read JSONB → identify legacy/new fields → validate alias consistency → default react/native/v1
→ resolve exact triple through Registry → validate against Adapter schema → immutable ExecutionConfig
```

- Loading historical configuration normalizes only in memory; only user save/publication persists the new form.
- Publication retains existing model Profile, tool, knowledge-base, and tenant/scope checks; new Engine fields cannot bypass them.
- Phase 3 fully enables only React and test Adapters; unregistered production Engines are rejected, and Codex schemas remain Phase 5 work.

### 4.2 Capability resolution (`capability_resolver.py`)

```
Adapter.get_capabilities → Declared
Declared + bounded deployment probes/version matrix → Available
Available + platform ceiling → tenant policy → published Agent disabled items → trusted Execution restrictions
→ Effective + snapshots for every layer
```

- Intersect per capability rather than merging dictionaries; unknown capability names default to false and produce a configuration/contract error.
- Cache keys include at least tenant-independent deployment identity, Engine triple, and probe version; policy changes invalidate relevant resolution entries.
- Convert probe timeout/errors to stable reason codes; never write raw exceptions, stderr, or paths to events.
- UI preview and actual Runs use the same resolver; execution uses a fresh snapshot and never treats a previous UI preview as authorization.

### 4.3 Run snapshot and start barrier (`orchestrator.py`, `repository.py`)

```
Run created → resolve configuration/capabilities/policy → validate and serialize snapshots
→ persist in one durability boundary → reread critical identifiers → construct ExecutionRequest
→ render instructions → Adapter.start
```

- No failure path may call Adapter.start; existing Orchestrator/Repository terminal-state ownership fails the Run closed.
- Cancellation/timeout after start retains the original snapshots; late results modify neither snapshots nor an existing cancelled terminal state.
- With `execution_phase3_enabled=false`, only the Phase 2 React compatibility path runs and all five columns stay NULL; non-React fails explicitly.

### 4.4 Instruction rendering (Instruction Provider)

```
Existing RuntimeFactory effective system prompt (platform + Agent + reply language)
+ existing MemoryInjection.render_summary / customer_memory results
+ kept history + current input
→ InstructionInput (exactly one of each category)
→ Engine Instruction Provider → Adapter-native instructions
```

- React ordering remains System → Summary (nonempty and enabled) → Memory (nonempty) → kept history → user.
- Providers do not recombine platform/Agent prompts, read or write Summary/Memory, or change history_turns, budgets, injection logs, or completion dispatch.
- A test Provider demonstrates an independent format; Phase 3 does not implement Codex file discovery, Skill mounts, or Workspace file writes.

### 4.5 Read-only preview and audit

- Preview APIs accept only Agent/version identifiers and trusted tenant/scope, resolving on the server; they accept neither Effective values nor policy versions.
- Responses contain displayable capabilities, stable reason codes, and configuration schema metadata only, never internal snapshots, policy secrets, or raw probe output.
- Agent publish/rollback audits add the Engine triple and configuration schema version; internal Run audits can correlate snapshots without recording sensitive values.

## 5. Configuration

Planned additions to `backend/src/agent_platform/core_platform/platform_services/platform_settings/settings.py`:

| Configuration | Type | Default | Constraints |
|---|---|---|---|
| `execution_phase3_enabled` | bool | `false` | Off for initial deployment; see 4.3 for React compatibility and non-React rejection |
| `execution_capability_policy_version` | str | `v1` | Nonempty supported version, read only by the server |
| `execution_capability_probe_timeout_seconds` | float | `2.0` | `(0,10]`; unbounded probes are forbidden |
| `execution_capability_probe_cache_seconds` | int | `30` | `[0,300]`; 0 disables caching but still adds no hot-path external calls |
| `execution_snapshot_max_bytes` | int | `65536` | `[4096,262144]`, checked per snapshot |

Environment variables retain the `AGENT_` prefix. `.env.example` contains only non-secret values; Engine tokens are not Phase 3 configuration.

## 6. Model Invocation Path

React continues to select models through the existing Model Gateway using the published model Profile ID/version, retaining `RuntimeFactory.bound_model` validation and Run correlation. The new structure changes only where configuration lives, not model resolution or secret flow. Missing valid Profiles still return `agent_model_required`, and tool-calling validation remains unchanged. Later phases define other Engines' model/credential paths; this phase must not bypass the Gateway through generic `config`.

## 7. Test Plan Summary

| Layer | Cases |
|---|---|
| Unit | Legacy mapping, alias conflicts, strict schemas, four-layer monotonicity, forged-input rejection, snapshot sensitivity/size checks, React/test Provider rendering |
| Integration | Draft → publish → Run → snapshot, policy changes, probe failures, cancellation/failure snapshots, cross-tenant access, and flag rollback |
| Migration | Upgrade from actual predecessor, old-row NULLs, new-row writes, concurrent reads/writes, paired downgrade, and historical-migration verification |
| Regression | Phase 0 React/Worker/Repository/SSE baseline and applicable Agent configuration and Summary/Memory suites |

See `04-test-plan.md` for detailed cases, failure injection, and malicious paths.

## 8. Rollout and Rollback

1. **Entry**: Phase 0 baseline and Phase 1–2 acceptance complete; revalidate migration head, target commit, and contract versions.
2. **Migration**: five nullable columns run online in a transaction with no default backfill or bulk rewrite; validate reads/writes and locks on a production-like copy first.
3. **Canary**: deploy with `execution_phase3_enabled=false` and confirm zero React diff; then enable only for test tenants/test Adapters and observe resolution latency, denial reasons, and snapshot sizes.
4. **Enable**: turn on only after AC and security gates pass; the flag does not make unregistered production Engines available.
5. **Flag rollback**: disabling the master switch stops new Phase 3 paths; non-React fails explicitly and never silently runs as React. Retain snapshot columns and Agent JSONB.
6. **Code rollback**: return to Phase 2-compatible code, which ignores the new nullable columns; no nonexistent non-null defaults are required and no database downgrade is needed.
7. **Data rollback**: rehearse downgrade only on disposable environments; any production column removal requires a separate change review and is not coupled to application rollback.
