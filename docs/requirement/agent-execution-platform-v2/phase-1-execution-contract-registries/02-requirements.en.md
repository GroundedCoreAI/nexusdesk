# Phase 1 · Execution Contracts and Registries — Requirements

> Status: Design decisions frozen (R1–R11); local test and local automated acceptance evidence exists, the full suite and CI remain pending, and formal human acceptance/sign-off is incomplete
> Created: 2026-11-02; design frozen: 2026-11-08
> Revised: 2026-11-09 (R11 owned-task documentation clarification; no lifecycle behavior change)
> Basis: `docs/architecture/agent-execution-platform-v2.md`, Sections 4–6 and 17, Phase 1; `01-business-goals.en.md` (G1–G4); `08-implementation-breakdown.en.md` (R1–R11, T1–T8)

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
| Output | Strict immutable Phase 1 DTOs that reuse ContractModel without modifying it; `extra="forbid"`, `strict=True`, `str_strip_whitespace=False`, common `contract_version`/event `schema_version`, and no trimming of raw input or IDs; ExecutionError safely round-trips through mapping/JSON without a new schema, with serialized message used only as a static-catalog integrity token |
| Execution | Synchronous in-memory validation with no database, network, or model calls; safe collection factories; cross-object identity checked at the Adapter boundary/common suite rather than repaired implicitly between models |
| Failure handling | Missing fields, invalid identifiers, unknown fields, invalid states, and inconsistent IDs are rejected immediately; invalid Result combinations are never repaired by clearing fields or changing state; arbitrary, mismatched, or non-string ExecutionError message input (including when code is missing/invalid) raises ValidationError, and only a string exactly equal to the supplied code's static catalog message may be discarded/recomputed as a no-op token; never infer unknown Engine configuration or log sensitive raw config |

### FR-2 Complete Adapter lifecycle contract

| Item | Description |
|---|---|
| Trigger | When a caller prepares to execute a resolved Adapter |
| Input | ExecutionRequest; the Adapter exposes engine_id, protocol_id, and adapter_version, and implements get_capabilities, start, stream_events, cancel, and collect_result |
| Output | start returns an ExecutionHandle matching every ExecutionKey; stream_events asynchronously yields AgentEvent; collect_result returns one logical terminal result; get_capabilities explicitly declares 11 strict boolean capabilities |
| Execution | Fully asynchronous and non-blocking; one active execution per instance; result collection may start immediately after start and run concurrently with streaming, with repeated/concurrent calls returning equal Results; process fields remain internal |
| Failure handling | Start, protocol, and collection exceptions map to safe ExecutionError; cancel is repeatable/concurrent and the first terminal state wins; no event appears after the terminal Result is visible; waiter cancellation and early iterator close both clean up tasks |

### FR-3 Engine, Protocol, and Adapter registries

| Item | Description |
|---|---|
| Trigger | When application composition or a test registers descriptors/Adapter factories, or resolves an Adapter by tuple |
| Input | EngineDescriptor, ProtocolDescriptor, AdapterDescriptor, and synchronous no-argument Adapter factories stored separately from descriptors; the resolution key includes exact adapter_version |
| Output | Independent registration records or a new Adapter instance; valid combinations resolve, while unregistered/disabled/incompatible combinations produce stable configuration error codes; no still-live object previously returned by the same registration may be returned again by a later resolution |
| Execution | Synchronous in-process registration and resolution; one factory maps to exactly one tuple and every resolution creates an independent instance; track returned instances per exact registration with weakrefs, compare live objects only with `is`, prune dead references during resolution, never strongly retain Adapters, invoke arbitrary `__eq__`, or store reusable bare `id()` values; referenced Engine/Protocol records must exist before Adapter registration; no network discovery or health probes |
| Failure handling | Unknown IDs, version mismatches, undeclared combinations, every duplicate registration (including identical duplicates), and factory failure/identity mismatch/missing methods fail closed; live singleton or A→B→A cycled reuse and non-weak-referenceable candidates are rejected before escape with `configuration_error/adapter_contract_mismatch`; no fallback to another Engine or version |

### FR-4 Version, error, and event rules

| Item | Description |
|---|---|
| Trigger | When registering/resolving a version, or when an Adapter emits an error or event |
| Input | `contract_version=v1`, event `schema_version=v1`, explicit `adapter_version`, event sequence, and error category |
| Output | Ten lower-snake-case categories, a static code catalog with unique category ownership, safe read-only computed messages, retryable and restricted details; direct and nested mapping/JSON round trips preserve the safe model_dump representation; native event payloads remain intact |
| Execution | Pure in-memory conversion; input message is accepted only as an integrity-token string exactly equal to the supplied code's static catalog message, then discarded/recomputed during before-validation, with every other value rejected; each active execution tracks a high-water mark, yields exact duplicates unchanged without advancing it, yields late lower-sequence events with new IDs unchanged, and permits gaps above the mark; no persistent deduplication |
| Failure handling | Unsupported contract major versions and Adapter versions are rejected; the same event_id with different content is `protocol_error/event_identity_conflict`; Phase 1 never retries automatically; errors contain no credentials, raw exception text, stacks, or customer input |

### FR-5 LocalTestAdapter and common contract suite

| Item | Description |
|---|---|
| Trigger | When a local test or CI selects a LocalTestAdapter scenario |
| Input | Scripted capabilities, start error, ordered events, terminal result, completion/per-event gates, stream error, timeout, simulated process failure, and explicit duplicate/late events |
| Output | Deterministic handles, events, capabilities, results, or ExecutionError under fixed identity `(local-test,scripted,v1)`; scenarios cannot override identity |
| Execution | Asynchronous in-memory implementation; UUIDv5/fixed-epoch event defaults, fake clock and `asyncio.Event` controls, and a fresh Adapter per run; the common suite imports no concrete LocalTestAdapter types |
| Failure handling | Invalid scenarios fail before a Handle exists; cancellation/timeout releases waits; post-terminal injection is suppressed; completion awaits owned tasks and asserts no Adapter/test pending task; simulated failure is never described as real Runtime Host capability |

### FR-6 Isolated integration and compatibility constraints

| Item | Description |
|---|---|
| Trigger | When Phase 1 code is merged and CI regression runs |
| Input | New packages, tests that instantiate registries directly, and existing Runtime/API tests |
| Output | Phase 2 can import the new contracts; existing RuntimeFactory, RuntimeWorker, RunPort, ContractModel, and HTTP/SSE signatures and behavior remain unchanged |
| Execution | No production Worker call-path change or runtime feature flag; dependency direction is `extension_contracts.base <- contracts <- registry/adapters.testing`; rollback reverts unwired packages |
| Failure handling | Any existing Runtime regression blocks merge; new tests must not cause changes to existing event names, Run states, table structures, Settings, or the lockfile |

## Non-Functional Requirements

- **Performance**: Registration and DTO validation are in-process only and perform no I/O during resolution; Phase 1 does not change production Run latency, whose baseline is to be measured in Phase 0.
- **Compatibility**: Existing Agent snapshots, RunRequest/RunSnapshot, RunStatus, Runtime Events, and APIs remain unchanged; migration head remains `0057_industry_pack_runtime` from entry commit `4dfcfb41e9cbb799753986c2d76134514bbd19be`, with zero `backend/uv.lock` diff.
- **Multi-tenancy**: request tenant_id comes only from trusted context; registries do not use untrusted input for cross-tenant lookup, and logs/errors never expose config, credentials, or raw input.
- **Maintainability**: Contracts do not import Registry/Worker/Repository/Factory/concrete Engines; Registry imports no concrete Adapter; LocalTestAdapter imports no Registry; package entry points do not eagerly import test Adapters.
- **Reliability**: Idempotent cancellation, instance isolation, shared terminal state, event high-water behavior, and error semantics are repeatable in tests; persistent event deduplication and real process supervision are not claimed.

## Acceptance Criteria

| # | Scenario | Expected |
|---|---|---|
| AC-1 | Construct all six contract models with valid and invalid payloads, then mutate default collections on two instances | Valid models preserve fields, versions, and untrimmed raw input; invalid/unknown fields and invalid Result combinations are rejected; mutable defaults are not shared |
| AC-2 | Invoke capabilities, start, stream_events, and collect_result on LocalTestAdapter in order | Tuple identity and ExecutionKey match, events arrive in order, and the result is completed with scripted output/usage |
| AC-3 | Start a long-running scenario, call cancel twice, then consume events/result and attempt a late success | Both cancellations are safe, the stream ends with a cancelled result, late success does not overwrite cancellation, and no new event is visible after cancellation |
| AC-4 | Exercise every error category and unsupported-capability scenario | Every error has the static catalog's category/code/message/retryable, direct and nested mapping/JSON round trips preserve the safe model_dump, arbitrary/mismatched/non-string message is rejected, sensitive text is absent, all 11 undeclared capabilities are false, and declarations are not treated as authorization |
| AC-5 | Independently register Engine, Protocol, and versioned Adapters, then reuse the common suite with a structurally independent second Adapter; resolve repeatedly while objects remain live and cover singleton, A→B→A cycle, non-weak-referenceable candidates, and dead-object collection | Valid combinations return independent identity-matching Adapters; live singleton/cycled reuse and non-weak-referenceable candidates are rejected before escape with `adapter_contract_mismatch`; weakref/gc evidence proves the registry does not strongly retain Adapters, dead references are pruned, and address reuse is not identity; the second Adapter is not a LocalTestAdapter subclass and requires no common-contract or Worker changes |
| AC-6 | Resolve unknown/disabled Engine, Protocol, versions, and undeclared combinations in the decided order; exercise every duplicate registration and factory failure | All are rejected with stable configuration errors, factory instances do not escape before identity/contract/freshness checks, and no implicit latest, cross-version, or other-Engine fallback occurs |
| AC-7 | Replay duplicate/conflicting/late events, timeout, resource exhaustion, and simulated process failure | Exact duplicates and late events remain visible, event_id conflicts are rejected, and other scenarios produce deterministic terminal results/errors without external dependencies or dangling tasks |
| AC-8 | Inspect migration head, lockfile, and production Worker/Factory wiring, then run existing Runtime/API/SSE regression | Head remains `0057_industry_pack_runtime`, lockfile/protected files have zero diff, the new path is not connected to production, and existing APIs, event names, states, and test behavior are unchanged |
