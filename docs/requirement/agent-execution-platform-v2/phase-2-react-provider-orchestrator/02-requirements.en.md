# Phase 2 · React Provider and Execution Orchestrator — Requirements

> Status: Pending review / Pending implementation
> Created: 2026-11-02
> Basis: `docs/architecture/agent-execution-platform-v2.md`, Sections 4–7, 12, and 14–17, Phase 2; Phase 1 (FR-1–FR-6); `01-business-goals.md` (G1–G4)

## User Stories

**US-1 (Existing tenant user)**: As a user of an existing Agent, I want no Agent configuration or client changes after the internal refactor so that I continue to receive the same replies, events, and cancellation behavior.

**US-2 (Platform engineer)**: As a platform engineer, I want React to run through a common Adapter and orchestrator so that future Engines do not require changes to Worker core logic.

**US-3 (Platform operator)**: As a platform operator, I want the new path default-off, gradual, and reversible so that I can restore legacy execution without database operations if problems occur.

**US-4 (QA/SRE)**: As QA/SRE, I want to compare old/new output, events, errors, and terminal states so that repeatable evidence determines whether migration caused regressions.

## Functional Requirements

### FR-1 React Engine Adapter

| Item | Description |
|---|---|
| Trigger | When the new-path orchestrator resolves a claimed Run as `react/native/v1` and starts the Adapter |
| Input | ExecutionRequest, execution-private context (claimed row, history, summary/customer_memory, event callback), and a RuntimeEngine built by the existing RuntimeFactory |
| Output | Results from all five Adapter methods; ExecutionResult preserves output/usage/error, internal engine_metadata returns history and dropped to the orchestrator, and identity is react/native/v1 |
| Execution | Asynchronously wrap the existing `RuntimeEngine.run()` without rewriting the model/tool loop; start launches, stream forwards events, collect returns one result, and cancel is idempotent and stops the waiting execution |
| Failure handling | RuntimeFault, TimeoutError, CancelledError, and unknown exceptions map to ExecutionError/cancelled results while preserving original error_code; history/dropped never enter public APIs, logs, or SSE |

### FR-2 Execution Orchestrator

| Item | Description |
|---|---|
| Trigger | After Worker claims a Run with the flag on and validates its configuration fingerprint |
| Input | Claimed row, trusted tenant/conversation/agent context, event emission callback, and rendered Memory results |
| Output | ExecutionOutcome (status, output, history, dropped, normalized error_code); every execution uses an independent Adapter/Handle |
| Execution | Asynchronously construct Request→select compatibility default react/native/v1→resolve exact registry entry→start→consume stream_events→collect_result; no inference and no direct RuntimeEngine.run call |
| Failure handling | Registration/version/Adapter start failures produce a normalizable failure without silently falling back to another version or legacy; clean up event iterators and Adapter tasks; unknown exceptions remain execution_error externally |

### FR-3 Worker integration and retained responsibilities

| Item | Description |
|---|---|
| Trigger | RuntimeWorker._execute selects a path using the global flag; queue claim, heartbeat, and finish continue through existing logic |
| Input | Claimed row, legacy RuntimeFactory or new Orchestrator, owner, fingerprint, and MemoryInjectionPort |
| Output | Repository.finish parameters and events equivalent to legacy; new-path Worker recognizes neither React/Codex nor Adapter-private results |
| Execution | Flag off takes the unchanged legacy branch; flag on calls `orchestrator.execute(...)`; monitor continues per-second heartbeat and cancels the execution task on lease loss/cancellation |
| Failure handling | monitor_failure still commits failed/worker_lost; user cancellation still commits cancelled; Worker still calls Repository.finish, whose conditional update rejects terminal overwrites and expired owners |

### FR-4 Runtime Event, AgentEvent, and SSE compatibility

| Item | Description |
|---|---|
| Trigger | When React Runtime emits model/tool events or Repository emits run lifecycle events |
| Input | Existing `(kind, data)`, including model.started/delta/completed and tool.started/completed; AgentEvent is only an internal envelope on the new path |
| Output | Map back to the same `(kind, data)` before calling existing Worker emit; model.delta remains transient through Notifier only, other model/tool events persist through Repository.append, and run.* remains Repository-only |
| Execution | Preserve per-Execution emission order, original payloads, database seq, and Last-Event-ID semantics; internal AgentEvent fields do not replace SSE data or add duplicate terminal events |
| Failure handling | Missing fields or unknown mapped events cause controlled execution failure/diagnostics rather than silent renaming; SSE reconnect replay still reads runtime_events, and tool.replay filtering/open API redaction remain unchanged |

### FR-5 Errors, cancellation, timeout, and terminal states

| Item | Description |
|---|---|
| Trigger | On model/tool/configuration failure, run/model timeout, user cancellation, Worker lease loss, or late result |
| Input | RuntimeFault.code, ExecutionError, cancel_requested, heartbeat state, and ExecutionResult |
| Output | Existing RunStatus and error_code; preserve observable codes including agent_model_required, configuration_changed, model_round_limit, model_timeout, run_timeout, execution_error, and worker_lost |
| Execution | Adapter normalizes Engine errors, Orchestrator normalizes common results, and Worker/Repository decide Run terminal state; cancel propagates and awaits cleanup, and cancellation/timeout cannot be overwritten by late completed |
| Failure handling | Unknown exceptions produce safe logs and execution_error; cancel is idempotent and does not undo prior side effects; no automatic retry, Fencing Token, or recovery semantics are added |

### FR-6 Feature flag, observability, and rollback

| Setting | Level | Default | Description |
|---|---|---|---|
| `execution_orchestrator_enabled` (environment variable `AGENT_EXECUTION_ORCHESTRATOR_ENABLED`) | Global Settings / each API or Worker process | `false` | false uses the existing Factory/Runtime path; true uses Orchestrator; changes take effect through configuration rollout and rolling restart, not request-level hot switching |

| Item | Description |
|---|---|
| Trigger | During deployment, gradual rollout, observation, or rollback |
| Input | Flag value and safe structured logs/metrics (run_id, engine/protocol/adapter, path, terminal state, error category, duration; no input/config/history) |
| Output | Operational evidence identifying old/new path and resolved version; after disabling, all new Runs use legacy |
| Execution | New components are required to resolve only with the flag on; mixed Workers can serve the same queue; initialization/resolution failure with the flag on fails fast without silent legacy fallback |
| Failure handling | On anomalies, set the flag false and rolling-restart all related processes; in-flight Runs converge under existing cancellation/Lease rules, with no migration, data repair, or client change |

## Non-Functional Requirements

- **Performance**: The new path adds only in-process DTO/event mapping; paired Phase 0 model-script samples must show p95 end-to-end latency increase ≤5%, with first token and error rate also recorded. Demo data must not be presented as measured production baseline.
- **Compatibility**: Default off; existing Agent snapshots, RuntimeFactory model/tool/Memory rules, RunView, RunStatus, HTTP statuses, SSE events, and replay remain unchanged; migration head stays `0052`.
- **Multi-tenancy**: tenant/business/workspace continue to come from authenticated and persisted scope; registry resolution accepts no client-provided Engine or Effective capabilities; private history/metadata never enters public streams.
- **Reliability**: Preserve existing leases, cancellation precedence, single terminal commit, and late-result protection; each execution has independent tasks/queues, and shutdown/failure leaves no pending task.
- **Observability**: Correlate old/new path, Adapter tuple, duration, and terminal state by run_id; logs contain no model keys, tool credentials, raw input, history, or full exception text.

## Acceptance Criteria

| # | Scenario | Expected |
|---|---|---|
| AC-1 | Run identical no-tool model scripts through legacy and new paths, covering no Agent snapshot and a published Agent snapshot | output, history/dropped, model events, usage, terminal state, and error_code match; old snapshots need no changes and React resolves as react/native/v1 |
| AC-2 | Compare paths using identical tool calls, history truncation, summary/customer_memory, reasoning, and budget scripts | Tool arguments/results, message order, Memory completion context, reasoning exclusion from visible output, and budget errors are equivalent |
| AC-3 | With the flag on, inspect the call chain from Run submission to completion and inject another registered Adapter | Runs complete through registries and Orchestrator; Worker never invokes a concrete Engine; another Adapter requires no Worker core branch change |
| AC-4 | Compare old/new internal and open SSE for durable model/tool events, transient delta, run terminal events, Last-Event-ID, tool.replay, and sensitive fields | Event names/order/payload/seq/replay/heartbeat are equivalent; delta is not persisted; no duplicate terminal state, internal AgentEvent, or history/engine_metadata disclosure |
| AC-5 | Inject missing configuration, model timeout, round/tool budgets, invalid model response, and unknown exception | Run terminal states and existing error_code match, the new path does not collapse every error to execution_error, and logs/APIs contain no raw sensitive exception |
| AC-6 | Cancel during execution while releasing a success result, cancel repeatedly, then read Run and events | Adapter cancellation completes cleanup; final Run is cancelled with no output/late completed, repeated cancel is safe, and cancellation events match legacy |
| AC-7 | Trigger run_timeout, model_timeout, Lease lost, and expired-Worker late commit separately | Preserve failed/run_timeout, failed/model_timeout, and failed/worker_lost; Repository rejects expired/late success and emits one terminal event |
| AC-8 | Test default startup, explicit enablement, mixed old/new Workers, then disable and rolling-restart | Default uses only legacy; enabled uses only orchestrator; mixed results are equivalent; all new Runs use legacy after rollback; resolution failure while enabled never silently falls back |
| AC-9 | Inspect public API/Agent configuration/database diff, observability fields, migration head, and run existing regression | No public schema or migration changes and head is `0052`; logs trace path/tuple/terminal state without sensitive data, and existing tests are green |
