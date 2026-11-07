# Phase 2 · React Provider and Execution Orchestrator — Technical Design

> Status: Pending review / Pending implementation
> Created: 2026-11-02
> Basis: `docs/architecture/agent-execution-platform-v2.md`, Sections 4–7, 12, 14–17, 19, and 21, Phase 2; `02-requirements.md` (FR-1–FR-6, AC-1–AC-9)

## Current-State Review and Change Overview

Verified current state: `RuntimeEngine.run()` in `engine.py` returns `(output, history, dropped)`; `worker.py` handles fingerprint, Memory rendering, heartbeat/cancel monitoring, Runtime invocation, and `repository.finish()`; `repository.py` atomically maintains event sequences, cancellation precedence, owner/lease checks, and terminal protection; `runtime_composition.py` assembles the single RuntimeFactory/Worker; `runtime_routes.py` and open-platform routes consume the existing event table and Notifier directly. Except for “existing” notes, everything below is **proposed and not implemented**.

| Layer | File | Change |
|---|---|---|
| Migration | `backend/migrations/versions/` | Add or modify no migration; current head `0052_memory_tasks_tenant_index.py` remains unchanged |
| New module | `backend/src/agent_platform/core_platform/agent_execution/adapters/react/adapter.py` | ReactAdapter five methods wrapping existing RuntimeEngine and retaining execution-private history/dropped results |
| New module | `backend/src/agent_platform/core_platform/agent_execution/adapters/react/event_mapper.py` | Lossless `(kind,data)`→internal AgentEvent→same `(kind,data)` mapping |
| New module | `backend/src/agent_platform/core_platform/agent_execution/adapters/react/error_mapper.py` | Explicit RuntimeFault/Timeout/Cancelled/unknown exception to ExecutionError mapping |
| New module | `backend/src/agent_platform/core_platform/agent_execution/orchestration/{execution_context,execution_lifecycle,orchestrator}.py` | Private execution context, Outcome, registry resolution, and complete Adapter lifecycle |
| Existing adapter | `backend/src/agent_platform/applications/platform_runtime/runtime_factory.py` | Preserve ReAct Runtime construction and legacy property; move Engine selection to Registry without adding other Engine branches to Factory |
| Entry point | `backend/src/agent_platform/applications/platform_runtime/runtime_composition.py` | Register React Provider and build Orchestrator; inject both legacy and new-path dependencies into Worker |
| Worker | `backend/src/agent_platform/core_platform/agent_runtime/worker.py` | Add flag branch and Orchestrator invocation; retain Memory, heartbeat, cancel monitor, and finish |
| Configuration | `backend/src/agent_platform/core_platform/platform_services/platform_settings/settings.py` | Add `execution_orchestrator_enabled: bool = false` |
| Repository/API | `agent_runtime/{repository,schemas}.py`, `extension_contracts/runtime.py`, `customer_service/runtime_routes.py`, open API routes | No change in principle; any parity fix requires a prior design revision and cannot change public schemas/terminal semantics |
| Tests | `backend/tests/{test_react_engine_adapter,test_execution_orchestrator,test_runtime_postgres,test_open_platform}.py` | Add Adapter/orchestrator tests and extend old/new path, SSE, terminal-state, and rollback regression |
| Deployment/frontend | `deploy/`, `.env.example`, `frontend/` | No new service or UI; deployment documentation may add a flag placeholder; frontend unchanged |

## Data Model and Responsibility Boundaries

### No database model changes

One `runtime_runs` row continues to represent one Execution attempt, with `execution_id = str(run.id)`. Add no Engine columns, Task tables, Session tables, or event-table fields. The compatibility layer fixes selection to `react/native/v1`; the tuple exists only in in-memory Handles/safe logs until Phase 3 designs configuration and snapshot persistence.

### Private context and common results

| Object | Contents | Owner-visible scope |
|---|---|---|
| ExecutionContext | claimed row, execution_id, history, summary_message, customer_memory, emit, trace/timeout | Worker→Orchestrator→React Adapter only; never serialized to HTTP/SSE/ordinary logs |
| ExecutionOutcome | status, output, history, dropped, error_code, optional usage | Orchestrator→Worker; Worker reads only fields needed by finish/Memory |
| React-private engine_metadata | history, dropped, and React-private execution information | In-process only; never in RunView, public ExecutionResult, or SSE |
| Public ExecutionResult/Error/Event | Phase 1 v1 contracts | Adapter/Orchestrator boundary; public APIs continue to use existing RunView/RunEvent |

Worker retains queueing, concurrency, owner, heartbeat, configuration fingerprint, and final `finish()`; Orchestrator never writes the database directly, avoiding two terminal-state committers. Adapter never operates the queue, decides authorization, or calls Repository.finish.

## Core Flows

### 1. Composition and registration (`runtime_composition.py`)

```
Build existing RuntimeEngine + RuntimeFactory (legacy retained)
→ register Engine(react), Protocol(native), Adapter(v1 + ReactAdapterFactory)
→ build ExecutionOrchestrator(registry)
→ RuntimeWorker(repository, legacy_factory, orchestrator, settings, ...)
```

- Within execution scope, ReactAdapterFactory uses the existing `RuntimeFactory.for_run(row, adapter_emit)` to build RuntimeEngine, then binds runtime/history/Memory inputs to an independent ReactAdapter; concrete Engine construction stays out of Worker/Orchestrator.
- Flag off retains the original construction/call path; flag on makes incomplete registration/construction fail explicitly at startup or first execution rather than silently using legacy.
- RuntimeFactory remains the ReAct assembler, not a general Registry; this phase adds no Codex or similar branches to Factory.

### 2. New-path execution (`orchestrator.py`)

```
Worker validates fingerprint and renders Memory
→ Orchestrator constructs ExecutionRequest from row (fixed react/native/v1)
→ Registry resolves exactly and creates ReactAdapter from ExecutionContext
→ adapter.start(request) returns Handle
→ consume stream_events, restore events to (kind,data), and call Worker-provided emit
→ adapter.collect_result → ExecutionOutcome
→ Worker computes memory_context and calls Repository.finish
```

- Request tenant/agent/conversation/input comes from the claimed row and trusted snapshot; this phase accepts no client Engine selection or Effective capabilities.
- ReactAdapter start creates an independent execution task and bounded internal event queue; stream_events forwards and collect_result awaits the task and reads one result. A full queue or departed consumer must cancel the producer rather than buffer delta indefinitely.
- The legacy branch directly invoking `runtime.run()` remains separate for field-by-field comparison; both paths share Repository and SSE but never in-flight Adapter state.

### 3. Event and SSE parity (`event_mapper.py` + existing Worker emit)

| Current source | New-path internal handling | Final existing destination |
|---|---|---|
| model.started/model.completed/tool.started/tool.completed | Convert to AgentEvent(source=engine_native), preserve kind/payload, then restore | Worker emit→Repository.append→durable seq→internal/open SSE |
| model.delta | Same envelope with transient semantics; never write internal AgentEvent to the database | Worker emit→Notifier.send→transient SSE with no id or durable record |
| run.queued/started/cancel_requested/completed/failed/cancelled | Adapter emits none of these platform terminal events | Existing Repository.submit/claim/cancel/finish/reap remains the sole emitter |
| tool.replay and open API field filtering | Does not enter the new React mapping or passes through by original type | Existing routes continue filtering/redaction and public payloads remain unchanged |

AgentEvent.sequence is only for Adapter-internal order checks and cannot replace `runtime_runs.event_seq`; SSE `id` still comes from database seq. Open API model/run field pruning, internal delta format, and 15-second heartbeat remain unchanged.

### 4. Error mapping and terminal commit

| Original condition | ExecutionError category | Existing external error_code / terminal state |
|---|---|---|
| RuntimeFault(code) | Configuration/Protocol/ResourceExhausted/Internal according to an explicit table | failed / preserve original code, such as agent_model_required or model_round_limit |
| RuntimeFault for model timeout | Timeout | failed / model_timeout |
| Outer TimeoutError from RuntimeEngine.run | Timeout | failed / run_timeout |
| User/Worker cancellation | Cancelled | cancelled / no error; Lease lost exception below |
| Cancellation caused by heartbeat=lost | Internal + worker_lost context | failed / worker_lost |
| Unknown exception | InternalError, safe log without exception body | failed / execution_error |

On cancellation, Worker cancels the execution task; Orchestrator calls idempotent `adapter.cancel(handle)` at its cleanup boundary, stops event iteration, awaits execution-task exit, then returns cancellation semantics to Worker. Cleanup is bounded and cannot hang forever. Worker monitor_failure takes precedence and commits failed/worker_lost; Repository.finish retains its TERMINAL, owner, lease, and cancel_requested conditions so late completed cannot overwrite cancellation/failure.

### 5. Feature flag and rollback

Proposed Settings field: `execution_orchestrator_enabled: bool = False`, overridden by `AGENT_EXECUTION_ORCHESTRATOR_ENABLED`. Default false; processes read it at startup, switching requires rolling restart, and request-level/dynamic hot switching is unsupported.

A gradual rollout can enable some Workers while others remain disabled because the Repository contract is identical. Rollback sets every process to false and rolling-restarts; in-flight executions converge under existing cancellation/Lease rules and running rows are never forcibly rewritten to a new state for rollback.

## Model Invocation Path

ReactAdapter does not change the existing order: `RuntimeFactory.for_run()` reads the Agent snapshot; with a snapshot, `bound_model()` uses GatewayChatModel and the specified `model_profile_id/version`, while missing configuration still raises `agent_model_required`; without a snapshot, base_runtime is used. Tools, language, rounds, Memory, stream_model_deltas, and gateway usage records all reuse existing behavior with no new model call or retry.

## Test Approach

| Layer | Cases |
|---|---|
| Unit | React identity/capabilities/lifecycle, event/error mapping, Request/Outcome, Worker flag, cancellation cleanup, and configuration default |
| Integration | Old/new parity with identical model scripts, tools/Memory, Orchestrator registry resolution, internal/open SSE, and PG cancellation/timeout/Lease terminal states |
| Regression | `test_runtime_engine.py`, `test_runtime_postgres.py`, `test_open_platform.py`, and affected Agent configuration/language/model and Memory suites |
| Rollback | Default off, explicit on, mixed Workers, no fallback on resolution failure, legacy-only after off rolling restart, and no migration change |

See `04-test-plan.md` for detailed steps and traceability.

## Rollout and Rollback

- First merge the default-off Adapter/Orchestrator/Worker branch and complete old/new parity in CI and a dedicated environment; then enable small Worker groups while observing error rate, latency, SSE, and terminal states.
- Registration/resolution failure while enabled must be visible and alertable, never hidden by automatic legacy fallback; old/new logs contain only safe identifiers and metrics.
- Any new-path P0/P1 or metric breach disables the flag and triggers rolling restart; no Alembic downgrade, data migration, or client change is needed.
- Do not introduce Phase 3 configuration, external Engines, Host, or event-reliability work in the same PR; otherwise parity differences cannot be isolated.
