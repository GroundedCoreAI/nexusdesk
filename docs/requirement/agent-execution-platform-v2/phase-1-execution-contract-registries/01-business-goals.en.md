# Phase 1 · Execution Contracts and Registries — Business Goals

> Status: Pending review / Pending implementation
> Created: 2026-11-02
> Basis: `docs/architecture/agent-execution-platform-v2.md`, Sections 4–6, 15–17, and 19–21, Phase 1

## Problems to Solve

### Problem 1: No independent execution boundary between the platform and the concrete ReAct Runtime

Currently, `backend/src/agent_platform/applications/platform_runtime/runtime_factory.py` directly constructs `RuntimeEngine`, and `backend/src/agent_platform/core_platform/agent_runtime/worker.py` directly invokes its `run()`. `backend/src/agent_platform/extension_contracts/runtime.py` defines only Run, Runtime business ports, and bindings; it has no Engine Adapter contract for start, events, cancellation, and results. Adding an Engine would therefore require more engine-specific branches in the Factory or Worker, making independent testing and evolution difficult.

### Problem 2: Engine, Protocol, and Adapter cannot be registered independently or resolved by version

There is currently no `core_platform/agent_execution` package and no Engine/Protocol/Adapter registries. The architecture's `(engine_id, protocol_id, adapter_version)` tuple, compatibility validation, and explicit rejection of unknown configurations are absent. A new Adapter cannot be validated without changing common execution code.

### Problem 3: Adapter error, cancellation, and capability semantics lack repeatable verification

The existing `RuntimeFault`, Run states, and Runtime Events serve the single ReAct path and are not yet a cross-Engine contract. Without a deterministic Adapter independent of external Engines, the future orchestrator cannot reliably cover streaming, failure, timeout, cancellation, and duplicate or late events.

## Business Goals

| Goal | Description |
|---|---|
| G1: Stable common execution contracts | Define versioned Request, Handle, Result, Error, Event, Capabilities, and a complete Adapter Protocol while isolating Engine-native details |
| G2: Extensible resolution | Register Engine, Protocol, and Adapter independently, resolve by exact tuple, and reject unknown, duplicate, or incompatible configurations |
| G3: Contract quality gate | Use LocalTestAdapter and common contract tests for success, streaming, errors, timeout, and cancellation without an external Engine |
| G4: Preserve current runtime behavior | Do not switch the production execution path, change public Run APIs, or add database migrations in this phase; provide a reversible foundation for Phase 2 |

## Success Metrics

| Metric | Baseline (current) | Target |
|---|---|---|
| Contract test coverage for six common models and five Adapter methods | To be inventoried in Phase 0 | 100% of defined contract branches and all five Adapter methods have cases; CI is green |
| Resolution accuracy for valid/invalid registry combinations | To be inventoried in Phase 0; no registry currently exists | 100% successful resolution for valid combinations and 100% rejection for invalid combinations in the fixed compatibility matrix |
| LocalTestAdapter contract scenario pass rate | To be inventoried in Phase 0; this Adapter does not currently exist | 100% pass for success, streaming, cancellation, timeout, and every specified error category; repeated runs are deterministic |
| Public contract changes required to add an Adapter | To be measured in Phase 0 | A new test-only Adapter requires zero changes to common contracts and Worker |
| Impact on existing Run execution latency and error rate | Latency and error-rate baselines to be measured in Phase 0 | New code is not connected to production; behavioral diff is zero, with no additional execution latency or errors |

## Scope

**Included**:
- Add versioned execution contract models, Adapter Protocol, and error categories.
- Add Engine Registry, Protocol Registry, Adapter Registry, and exact-version resolution.
- Add deterministic LocalTestAdapter, reusable contract tests, and registry tests.
- Define internal handle fields, event ordering, duplicate/late events, idempotent cancellation, and explicit unsupported capabilities.

**Excluded** (later phases / explicitly not done):
- React Provider, Worker orchestrator integration, and production path switching (Phase 2).
- Engine selection in Agent configuration, Effective capability calculation, and policy snapshots (Phase 3).
- Runtime Host, real process supervision, Workspace, and sandboxing (Phase 4).
- Codex or other external Engine integrations (Phase 5 and later).
- Separate Task/Execution tables, any Alembic migration, microservice decomposition, and a complex scheduler (explicitly excluded here).

## Risks and Constraints

- **Over-designed contracts**: Including every Engine-private concept would undermine stability; fix only fields required across Engines and isolate the rest in versioned native metadata.
- **Non-deterministic version resolution**: Automatically selecting the “latest” version makes a Run irreproducible; Phase 1 requires explicit `adapter_version` and forbids implicit latest.
- **An overly permissive test double**: LocalTestAdapter could hide lifecycle errors; the common contract suite is mandatory for every later Adapter, not merely a test of the test implementation.
- **Confusing cancellation with side effects**: Cancellation stops subsequent execution but cannot promise to undo completed tool side effects; error and result models must preserve this meaning.
- **Compatibility**: Existing `agent_runtime`, `extension_contracts/runtime.py`, HTTP/SSE, and table structures remain unchanged; new packages are used only by tests that instantiate them directly. The current migration head is `0052` and must remain `0052` after this phase.
