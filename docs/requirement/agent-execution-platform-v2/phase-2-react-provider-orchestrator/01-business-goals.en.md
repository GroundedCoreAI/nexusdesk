# Phase 2 · React Provider and Execution Orchestrator — Business Goals

> Status: Pending review / Pending implementation
> Created: 2026-11-02
> Basis: `docs/architecture/agent-execution-platform-v2.md`, Sections 4–7, 12, 14–17, and 19–22, Phase 2; Phase 1 (G1–G4)

## Problems to Solve

### Problem 1: Worker is coupled to fixed ReAct Runtime construction and invocation

`backend/src/agent_platform/core_platform/agent_runtime/worker.py` currently obtains a Runtime through `RuntimeFactory.for_run()` and directly calls `run()`; `backend/src/agent_platform/applications/platform_runtime/runtime_factory.py` always constructs `RuntimeEngine`. Worker therefore knows the concrete Runtime output `(output, history, dropped)` and exception forms, preventing future Engines from reusing one orchestration path.

### Problem 2: No component coordinates the common Execution lifecycle

The contracts and registries planned in Phase 1 need an Execution Orchestrator. No component currently maps Run→ExecutionRequest, resolves `react/native/v1`, coordinates Adapter start/stream/cancel/collect, and normalizes results/errors. Adding these responsibilities directly to Worker would further increase its engine-specific knowledge.

### Problem 3: Refactoring must preserve observable Run, event, and SSE behavior

The existing `RunRepository` provides queued/running/completed/failed/cancelled, cancellation precedence, rejection of late commits after lease loss, durable event sequences, and replay. Internal and open APIs also distinguish durable events from transient `model.delta`. Changing event names, payloads, cursors, terminal states, or error codes would break the console and open API clients.

### Problem 4: The first major refactor has no gradual, reversible execution entry point

Only the legacy Runtime call path currently exists; there is no old/new path flag. A default-off orchestration path, compatibility across mixed Worker groups, and recovery without database rollback are required to avoid cutting over all execution traffic at once.

## Business Goals

| Goal | Description |
|---|---|
| G1: React becomes the first common Provider | Preserve LangGraph ReAct inference and tool execution, wrap them in a complete React Adapter, and resolve it through registries as `react/native/v1` |
| G2: Decouple Worker from concrete Engines | The orchestrator manages the Adapter lifecycle and common results; Worker retains queueing, Lease/Heartbeat, cancellation monitoring, and Repository terminal commits without knowing Engine internals |
| G3: Zero regression for existing users | Old and new paths are equivalent in output, history, Memory, events, SSE, error codes, cancellation, and terminal states; public APIs remain unchanged |
| G4: Controlled migration and rapid rollback | Enable the new path gradually through a default-off global flag; rollback only switches to legacy and performs a rolling restart, with no migration or data repair |

## Success Metrics

| Metric | Baseline (current) | Target |
|---|---|---|
| Semantic parity on fixed React regression corpus | Output, history/dropped, event, and error-code baselines to be established in Phase 0 | With identical model scripts, 100% parity for output, history/dropped, event type/order/payload, error_code, and terminal state |
| Coverage of React execution through registries and orchestrator | To be inventoried in Phase 0; currently zero new-path executions | 100% of acceptance Runs with the flag on use `react/native/v1` and the orchestrator; Worker never directly invokes a concrete Engine |
| Internal and open SSE compatibility | Existing event sequences, payloads, Last-Event-ID, and delta baselines to be recorded in Phase 0 | 100% parity for event names, durable seq/replay, transient delta, and terminal frames in fixed scenarios; no new internal metadata disclosure |
| Correctness of cancellation, timeout, and late-result protection | Existing Repository/Worker case results to be inventoried in Phase 0 | 100% specified terminal states for cancellation races, run/model timeout, and Lease lost; zero late-success overwrites |
| New-path execution performance and stability | p50/p95, first token, error rate, and resource baselines to be measured in Phase 0 | New-path p95 end-to-end latency increase ≤5% on identical samples and zero additional errors; sampling defined in the acceptance plan |
| Rollback recovery | Current deployment recovery baseline to be exercised and recorded in Phase 0 | After flag-off and rolling restart, 100% of new Runs use legacy; no Alembic downgrade, data repair, or client change |

## Scope

**Included**:
- Implement a React Adapter, internal Runtime Event↔AgentEvent mapping, and ExecutionError mapping using Phase 1 contracts.
- Implement Execution Orchestrator with legacy configurations fixed to `react/native/v1` in this phase.
- Add Worker old/new path branches, composition-root wiring, and a default-off global feature flag.
- Preserve Repository ownership of terminal states/events and verify internal/open SSE, Memory, errors, cancellation, timeout, and Lease behavior.
- Run old/new parity regression, mixed-Worker migration, and rollback exercises.

**Excluded** (later phases / explicitly not done):
- Changes to LangGraph inference, tool protocols, Memory business rules, or model Profile selection.
- Engine/Protocol fields in Agent configuration, Effective capability calculation, and configuration/policy snapshots (Phase 3).
- Runtime Host, external processes, Workspace, sandbox, and credential broker (Phase 4).
- Codex/other Engines, Session Resume, and new human-approval capabilities (Phase 5 and later).
- New Task/Execution tables, Lease Epoch/Fencing Token, transactional Outbox, and new SSE replay protocols (Phase 6 or later).
- Any Alembic migration, public HTTP/SSE schema change, or microservice decomposition (explicitly excluded here).

## Risks and Constraints

- **Timing changes in the Adapter**: Queue forwarding could reorder delta and durable events; use the same emission callback and ordering tests, while run terminal events remain Repository-only.
- **Error-code regression**: Common ExecutionError must not collapse `model_timeout`, `agent_model_required`, and other existing codes into generic errors; mappings must preserve public error_code without exposing raw exceptions.
- **Incomplete cancellation cleanup**: Coroutine cancellation must propagate to Adapter execution and await cleanup; cancellation does not undo tool side effects, and Repository continues to reject late results.
- **Inconsistent flags**: Mixed Workers may use different paths; both paths must remain equivalent, and registration/resolution failure with the flag on must fail explicitly rather than silently fall back.
- **Compatibility**: Default `execution_orchestrator_enabled=false`; existing Agent snapshots need no changes and resolve to `react/native/v1`. Current migration head is `0052` and must remain `0052` after this phase.
