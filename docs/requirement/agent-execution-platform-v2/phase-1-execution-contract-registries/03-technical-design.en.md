# Phase 1 · Execution Contracts and Registries — Technical Design

> Status: Pending review / Pending implementation
> Created: 2026-11-02
> Basis: `docs/architecture/agent-execution-platform-v2.md`, Sections 4–6, 15–17, and 19, Phase 1; `02-requirements.md` (FR-1–FR-6, AC-1–AC-8)

## Current-State Review and Change Overview

Current state: `RuntimeEngine.run()` is in `core_platform/agent_runtime/engine.py`; `RuntimeWorker` obtains and executes a Runtime directly through `RuntimeFactory.for_run()`; `RunRepository` already handles queueing, leases, events, and terminal states; `extension_contracts/runtime.py` is the Run/business port boundary. Every `agent_execution` path below is **proposed and does not currently exist**. This document does not claim implementation.

| Layer | File | Change |
|---|---|---|
| Migration | `backend/migrations/versions/` | Add or modify no migration; current head `0052_memory_tasks_tenant_index.py` remains unchanged |
| New module | `backend/src/agent_platform/core_platform/agent_execution/contracts/{request,handle,result,events,capabilities,errors}.py` | Six versioned DTO groups and error categories; no Runtime/application dependency |
| New module | `backend/src/agent_platform/core_platform/agent_execution/contracts/adapter.py` | AgentEngineAdapter Protocol and identity/lifecycle constraints |
| New module | `backend/src/agent_platform/core_platform/agent_execution/registry/{engine_registry,protocol_registry,adapter_registry}.py` | Descriptors, independent registration, compatibility matrix, and exact-tuple resolution |
| New module | `backend/src/agent_platform/core_platform/agent_execution/adapters/testing/local_test_adapter.py` | Programmable deterministic contract Adapter with no external dependencies |
| Tests | `backend/tests/{test_agent_execution_contracts,test_agent_execution_registries,test_local_test_adapter}.py` | Model, registration/version, and complete Adapter contract tests |
| Existing entry points | `runtime_factory.py`, `runtime_composition.py`, `worker.py`, `repository.py`, `schemas.py`, `extension_contracts/runtime.py` | No production wiring, public Run port, or existing model change in this phase |
| Deployment/config/frontend | `deploy/`, Settings, `.env.example`, `frontend/` | No changes and no new flag in this phase |

## Data Model and Module Boundaries

### Contract fields and invariants

| Model | Required common fields | Key invariants |
|---|---|---|
| ExecutionRequest | execution/tenant/agent/conversation IDs, engine/protocol/adapter tuple, input, config, effective_capabilities, optional session/workdir/timeout/trace | IDs are non-empty and execution_id spans the lifecycle; trusted callers supply config; this phase does not calculate Effective capabilities |
| ExecutionHandle | execution_id, tuple, provider_session_id, internal process_id, status, metadata | execution_id matches request; process_id/metadata are not automatically exposed through RunView or SSE |
| ExecutionResult | execution_id, completed/failed/cancelled, output, artifacts, usage, engine_metadata, error | completed cannot include error; failed requires a normalized error; cancelled cannot expose late-success output |
| ExecutionError | category, stable code, safe message, retryable, restricted details | category covers all ten FR-4 types; raw exceptions are internal causes only and sensitive text is never serialized |
| AgentEvent | event_id, schema_version, execution_id, sequence, event_type, source, timestamp, payload, trace_id | sequence is monotonic within an execution; event_id identifies duplicates; this phase does not write runtime_events |
| EngineCapabilities | streaming, persistent_session, session_resume, cancellation, human_approval, interactive_input, tool_calling, file_operations, terminal_execution, native_events, workspace_required | Undeclared capabilities are false; Declared does not imply Available/Effective or authorization |

Contracts use explicit `contract_version=v1`, and AgentEvent uses `schema_version=v1`. An incompatible major version requires a new model/conversion layer rather than a silent v1 semantic change. DTOs reject unknown fields and shared mutable defaults.

### Responsibility boundaries

- `contracts` expresses data and the Adapter Protocol only; it does not operate the Worker queue, decide tenant authorization, or commit Run terminal states.
- `registry` stores descriptors, compatibility relations, and factories only; it performs no dynamic network discovery, real health check, or RuntimeEngine construction.
- `LocalTestAdapter` simulates Adapter semantics only; “process failure” is a test scenario, not evidence of a Process Supervisor.
- Existing `extension_contracts/runtime.py` continues to serve business capabilities; Engine Adapters must not be inserted into the Capability/Extension Registry.

## Core Flows

### 1. Registration and exact resolution (`registry/`)

```
Register Engine → register Protocol → register Adapter factory and supported combinations
→ validate descriptor identity, version, combinations, and duplicate conflicts
→ resolve(engine_id, protocol_id, adapter_version)
→ exact lookup and new instance → validate instance identity → return or raise ConfigurationError
```

- Engine and Protocol register independently; Adapter registration declares allowed combinations, and resolution never guesses.
- Before implementation, fix duplicate handling as either “all duplicates rejected” or “only exact duplicates idempotent”; tests must lock the selected rule. Conflicts are always rejected. Acceptance here assumes “all duplicates rejected” to expose composition errors early.
- No latest, version ranges, or automatic downgrade; disabled and unknown IDs fail closed.

### 2. Adapter lifecycle (`contracts/adapter.py`)

```
get_capabilities → start(request) → concurrently consume stream_events(handle)
→ collect_result(handle) → completed / failed / cancelled
                      ↘ cancel(handle) (at any running point, idempotent) ↗
```

- A failed start cannot return a partially valid Handle; stream protocol errors must reach the caller and map to an error.
- collect_result returns after normal stream completion; after cancel the stream must end, and repeated cancel/result collection cannot create a second terminal state.
- Cancellation does not undo completed side effects; timeout does not prove the Engine performed no work. retryable is metadata only, with no automatic retry here.
- Duplicate/late events remain observable at the contract layer; persistent deduplication and SSE replay remain the responsibility of later orchestration and the existing Repository.

### 3. LocalTestAdapter scenario driving (`adapters/testing/local_test_adapter.py`)

A scenario defines identity, capabilities, start error, event script, result, completion/cancellation gates, and late events. A test clock advances timeout, while event gates control long-running and cancellation cases. Every scenario verifies five methods and three identity properties and cleans up async iterators/tasks after failure.

### 4. Error and event boundaries

| Source | Normalized result | Not done in this phase |
|---|---|---|
| DTO/registration/version error | ConfigurationError with stable code and no automatic fallback | No Agent configuration change or database write |
| Adapter start/protocol/collection exception | Corresponding ExecutionError; unknown exceptions become InternalError | Raw exception text is not exposed to APIs |
| Timeout/Cancelled | Timeout or Cancelled, retaining retry advice | No inference that side effects were rolled back and no automatic retry |
| Native event | AgentEvent(source=engine_native) retaining payload | No forced conversion to ReAct Tool Calling abstractions |

## Configuration and Model Invocation Path

This phase adds no Settings, environment variables, or AgentConfig and has no model invocation path. Tests construct trusted requests without real credentials, model Profiles, or tenant configuration. Phase 3 will generate config and Effective capabilities from typed configuration.

## Test Approach

| Layer | Cases |
|---|---|
| Unit | Six DTO groups, default isolation, ten error types, capability defaults, registration/version/compatibility matrix, and factory instance isolation |
| Contract/integration | LocalTestAdapter full lifecycle, five methods, event ordering, idempotent cancellation, timeout, every error category, and duplicate/late events |
| Regression | Existing `test_runtime_engine.py`, `test_runtime_postgres.py`, and API/SSE tests; verify no production wiring and unchanged migration head |

See `04-test-plan.md` for detailed steps and traceability.

## Rollout and Rollback

- New packages are not wired into the production composition root; there are no database, deployment, or runtime-flag changes. Merging adds only modules directly callable by tests.
- CI must demonstrate zero diff in existing Runtime/API regression; this phase must not change event structures or Run states.
- Rollback reverts the unwired packages and tests, with no Alembic downgrade, data repair, or Worker switch.
- Before Phase 2 integration, recheck v1 contracts against actual React behavior. Any incompatible change requires a documented version decision rather than silent modification.
