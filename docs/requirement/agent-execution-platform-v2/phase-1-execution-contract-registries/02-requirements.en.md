# Phase 1 · Execution Contracts and Registries — Requirements

> Status: Pending review / Pending implementation
> Created: 2026-11-02
> Basis: `docs/architecture/agent-execution-platform-v2.md`, Sections 4–6 and 17, Phase 1; `01-business-goals.md` (G1–G4)

## User Stories

**US-1 (Adapter developer)**: As an Adapter developer, I want a stable, versioned common contract so that I can add an Engine without modifying Worker or common platform models.

**US-2 (Platform engineer)**: As a platform engineer, I want to register Engine, Protocol, and Adapter separately so that I can resolve an implementation by exact tuple and detect incompatible configuration before execution.

**US-3 (QA)**: As QA, I want a deterministic local Adapter that drives every lifecycle and failure scenario so that I can repeatedly verify contracts without external Engines or credentials.

**US-4 (Platform operator)**: As a platform operator, I want this phase to leave production Run flows and the database unchanged so that contract work adds no production cutover or rollback burden.

## Functional Requirements

### FR-1 Versioned execution data contracts

| Item | Description |
|---|---|
| Trigger | When an Adapter receives an execution, returns a handle/result, or exchanges events and capabilities with the platform |
| Input | Trusted execution context, Run-mapped data, and Adapter-native output; models include ExecutionRequest, ExecutionHandle, ExecutionResult, ExecutionError, AgentEvent, and EngineCapabilities |
| Output | Unambiguous DTOs validated with `extra="forbid"`; common fields carry `contract_version`/event `schema_version`, and Engine-private data is isolated in explicit metadata |
| Execution | Synchronous in-memory validation; no database, network, or model calls; safe collection defaults with no mutable state shared between instances |
| Failure handling | Missing fields, invalid identifiers, unknown fields, invalid states, or inconsistent IDs immediately raise validation errors; never infer unknown Engine configuration or log sensitive raw config |

### FR-2 Complete Adapter lifecycle contract

| Item | Description |
|---|---|
| Trigger | When a caller prepares to execute a resolved Adapter |
| Input | ExecutionRequest; the Adapter exposes engine_id, protocol_id, and adapter_version, and implements get_capabilities, start, stream_events, cancel, and collect_result |
| Output | start returns an ExecutionHandle matching execution_id; stream_events asynchronously yields AgentEvent; collect_result returns one logical terminal result; get_capabilities explicitly declares unsupported features |
| Execution | Fully asynchronous and non-blocking; event iteration and result collection are independently testable; process fields in a handle are internal and never enter public HTTP APIs |
| Failure handling | Start, protocol, and collection exceptions map to ExecutionError; cancel is idempotent and never turns user cancellation into internal failure; no valid event or success result may arrive after a terminal state |

### FR-3 Engine, Protocol, and Adapter registries

| Item | Description |
|---|---|
| Trigger | When application composition or a test registers descriptors/Adapter factories, or resolves an Adapter by tuple |
| Input | EngineDescriptor, ProtocolDescriptor, Adapter factories and supported `(engine_id, protocol_id)` combinations; the resolution key includes exact adapter_version |
| Output | Independent registration records or a new Adapter instance; valid combinations resolve, while unregistered/disabled/incompatible combinations produce stable configuration error codes |
| Execution | Synchronous in-process registration and resolution; each factory call creates an independent instance with no per-Execution state sharing; no network discovery or real health probes |
| Failure handling | Unknown IDs, version mismatches, undeclared combinations, conflicting duplicate registrations, and factory identity mismatches fail closed; resolution never falls back to another Engine or version |

### FR-4 Version, error, and event rules

| Item | Description |
|---|---|
| Trigger | When registering/resolving a version, or when an Adapter emits an error or event |
| Input | `contract_version=v1`, explicit `adapter_version` (example `v1` in this phase), event sequence, and error category |
| Output | ConfigurationError, EngineUnavailable, ProtocolError, AuthenticationError, PermissionDenied, ResourceExhausted, Timeout, Cancelled, WorkspaceError, InternalError; errors contain safe code, category, retryable, and restricted details |
| Execution | Pure in-memory conversion; AgentEvent uses a monotonically increasing per-execution sequence and unique event_id; duplicate/late events can be represented but are not deduplicated or persisted by this layer |
| Failure handling | Unsupported contract major versions and Adapter versions are rejected; default retry is advisory only and Phase 1 never retries automatically; error messages contain no credentials, raw stacks, or customer input |

### FR-5 LocalTestAdapter and common contract suite

| Item | Description |
|---|---|
| Trigger | When a local test or CI selects a LocalTestAdapter scenario |
| Input | Scripted scenarios: success, streaming, long running, invalid configuration, protocol error, authentication failure, permission denied, resource exhausted, timeout, cancellation, simulated process failure, and duplicate/late events |
| Output | Deterministic handles, event sequences, capabilities, results, or ExecutionError; tests control completion/cancellation gates without real processes or networks |
| Execution | Asynchronous in-memory implementation; test clocks or event gates control time and waits; repeating a scenario produces the same semantics |
| Failure handling | Invalid scenario definitions are rejected before start; tests clean up all waiting tasks; no real sleep for long timeouts, and simulated failures are not represented as real Runtime Host capabilities |

### FR-6 Isolated integration and compatibility constraints

| Item | Description |
|---|---|
| Trigger | When Phase 1 code is merged and CI regression runs |
| Input | New packages, tests that instantiate registries directly, and existing Runtime/API tests |
| Output | Phase 2 can import the new contracts; existing RuntimeFactory, RuntimeWorker, RunPort, and HTTP/SSE signatures and behavior remain unchanged |
| Execution | No production Worker call-path change and no runtime feature flag; Phase 1 has no enabled state, and rollback means not introducing/removing the unwired packages |
| Failure handling | Any existing Runtime regression blocks merge; new tests must not cause changes to existing event names, Run states, or table structures |

## Non-Functional Requirements

- **Performance**: Registration and DTO validation are in-process only and perform no I/O during resolution; Phase 1 does not change production Run latency, whose baseline is to be measured in Phase 0.
- **Compatibility**: Existing Agent snapshots, RunRequest/RunSnapshot, RunStatus, Runtime Events, and APIs remain unchanged; migration head stays at `0052`.
- **Multi-tenancy**: request tenant_id comes only from trusted context; registries do not use untrusted input for cross-tenant lookup, and logs/errors never expose config, credentials, or raw input.
- **Maintainability**: Engine/Protocol/Adapter identities and versions are explicit; common contracts do not import Factory, Worker, Repository, or any concrete Engine.
- **Reliability**: Idempotent cancellation, instance isolation, event ordering, and error semantics are repeatable in tests; persistent event deduplication and process cleanup are not claimed in this phase.

## Acceptance Criteria

| # | Scenario | Expected |
|---|---|---|
| AC-1 | Construct all six contract models with valid and invalid payloads, then mutate default collections on two instances | Valid models preserve fields and versions; invalid/unknown fields are rejected; mutable defaults are not shared |
| AC-2 | Invoke capabilities, start, stream_events, and collect_result on LocalTestAdapter in order | Tuple identity and execution_id match, events arrive in order, and the result is completed with scripted output/usage |
| AC-3 | Start a long-running scenario, call cancel twice, then consume events/result and attempt a late success | Both cancellations are safe, the stream ends with a cancelled result, late success does not overwrite cancellation, and no valid new event follows cancellation |
| AC-4 | Exercise every error category and unsupported-capability scenario | Every error has the specified category/code/retryable, sensitive text is absent, unsupported capabilities are explicitly false, and declarations are not treated as authorization |
| AC-5 | Independently register one Engine, two Protocols, and versioned Adapters, then resolve valid tuples | Engine and Protocol registration are not hard-bound; valid combinations return independent identity-matching Adapters without changing common contracts or Worker |
| AC-6 | Resolve unknown Engine/Protocol/version, undeclared combinations, and disabled entries; attempt conflicting duplicate registration and an identity-mismatched factory | All are rejected with stable configuration errors, with no implicit latest, cross-version, or other-Engine fallback |
| AC-7 | Replay LocalTestAdapter duplicate events, late events, timeout, resource exhaustion, and simulated process failure | Event anomalies remain accurately visible to upper layers; other scenarios produce deterministic terminal results/errors without external dependencies or dangling tasks |
| AC-8 | Inspect migration head and production Worker/Factory wiring, then run existing Runtime/API/SSE regression | Head remains `0052`, the new path is not connected to production Worker, and existing APIs, event names, states, and test behavior are unchanged |
