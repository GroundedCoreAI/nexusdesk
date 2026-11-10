# Phase 1 · Execution Contracts and Registries — Technical Design

> Status: Design decisions frozen (R1–R11); local test and local automated acceptance evidence exists, the full suite and CI remain pending, and formal human acceptance/sign-off is incomplete
> Created: 2026-11-02; design frozen: 2026-11-08
> Revised: 2026-11-09 (R11 owned-task documentation clarification; no lifecycle behavior change); 2026-11-10 (record the Phase 0 frozen production Adapter identity; no design or behavior change)
> Basis: `docs/architecture/agent-execution-platform-v2.md`, Sections 4–6, 15–17, and 19, Phase 1; `02-requirements.en.md` (FR-1–FR-6, AC-1–AC-8); `08-implementation-breakdown.en.md` (R1–R11, T1–T8)

## Current-State Review and Change Overview

The implementation entry is fixed at `4dfcfb41e9cbb799753986c2d76134514bbd19be`: `core_platform/agent_execution` does not yet exist and the Alembic head is `0057_industry_pack_runtime`. `RuntimeEngine.run()`, `RuntimeWorker`, `RuntimeFactory`, and `RunRepository` continue to own the existing ReAct/Run path; `extension_contracts/runtime.py` remains the Run/business-port boundary. Every `agent_execution` path below is **proposed**; this document does not claim implementation or passing tests.

The user explicitly requested that Phase 1 start. The still-open Phase 0 clean committed-artifact CI double-runs, authorized real historical samples, and human sign-offs are therefore recorded as an **accepted entry risk**, not as formal Phase 0 acceptance or approval.

| Layer | File | Change |
|---|---|---|
| Migration/dependencies | `backend/migrations/versions/`, `backend/uv.lock` | No additions or modifications; head remains `0057_industry_pack_runtime` at entry and completion, with zero lockfile diff |
| Contracts | `backend/src/agent_platform/core_platform/agent_execution/contracts/{base,common,request,handle,result,events,capabilities,errors}.py` | Strict Phase 1 base, ExecutionKey/safe aliases, six versioned DTO groups, and static error catalog |
| Adapter protocol | `backend/src/agent_platform/core_platform/agent_execution/contracts/adapter.py` | AgentEngineAdapter Protocol and identity/lifecycle constraints |
| Registries | `backend/src/agent_platform/core_platform/agent_execution/registry/{engine_registry,protocol_registry,adapter_registry}.py` | Descriptors, independent registration, and exact-tuple resolution; factories stored separately from descriptors |
| Test Adapter | `backend/src/agent_platform/core_platform/agent_execution/adapters/testing/local_test_adapter.py` | Programmable deterministic LocalTestScenario/LocalTestAdapter with no external dependencies |
| Reusable suite | `backend/tests/agent_execution/adapter_contract_suite.py` | Abstract scenarios, gate/fake-clock controls, and cleanup assertions depending only on common contracts; no concrete LocalTestAdapter imports |
| Second Adapter | `backend/tests/agent_execution/contract_probe_adapter.py` | Structurally independent and not a LocalTestAdapter subclass, with fixed tuple `(contract-probe,contract-scripted,v1)` |
| Tests | `backend/tests/{test_agent_execution_contracts,test_agent_execution_registries,test_local_test_adapter,test_agent_execution_contract_probe}.py` | DTO/error and registry tests plus the same contract suite for both Adapters |
| Package entry points | `__init__.py` in the new packages above | Export common contract/registry interfaces only; never eagerly import test Adapters |
| Existing entry points | `runtime_factory.py`, `runtime_composition.py`, `worker.py`, `repository.py`, `schemas.py`, `extension_contracts/{base,runtime}.py` | Zero diff in this phase; no ContractModel, production wiring, public Run port, or existing model change |
| Deployment/config/frontend | `deploy/`, Settings, `.env.example`, `frontend/` | Zero diff, with no new flag or credential |

## Data Model and Module Boundaries

### R1: Strict DTOs, identity, and exact fields

Reuse `extension_contracts.base.ContractModel` without modifying it. Add `ExecutionContractModel(ContractModel)`, explicitly retaining `frozen=True`, `extra="forbid"`, and `allow_inf_nan=False` while setting `strict=True` and `str_strip_whitespace=False`. Raw input is not trimmed, and strict mode rejects coercion from non-strings to strings.

`ExecutionKey` contains only `execution_id: UUID`, `engine_id`, `protocol_id`, and `adapter_version`, shared by Request/Handle/Result/Event:

- Request/Handle/Result/Error/Capabilities use `contract_version: Literal["v1"] = "v1"`; Event uses `schema_version: Literal["v1"] = "v1"`. Explicitly supplying another version fails.
- Engine/Protocol IDs match `^[a-z0-9][a-z0-9_-]{0,63}$`; Adapter versions match `^v[1-9][0-9]*$`. Reject `latest`, `v0`, `v01`, surrounding whitespace, and non-strings.
- Common opaque strings are nonempty, at most 200 characters, control-character-free, and free of leading/trailing whitespace; IDs are never trimmed. `input` is not an opaque ID: original newlines and other content are preserved verbatim.
- `event_type` is at most 100 characters and matches `^[a-z0-9]+(?:[._-][a-z0-9]+)*$`; event sequence starts at 1.

This phase preserves the Phase 0 frozen production Adapter identity `(react,native,v1)`, which remains independent of the LocalTestAdapter and ContractProbe test identities. Phase 1 fixes the common contracts and registration semantics only; this statement does not claim that production Adapter wiring is complete.

| Model | Exact fields and defaults | Key invariants |
|---|---|---|
| ExecutionRequest | ExecutionKey; `tenant_id: str` (1–200); `agent_id: UUID`; `conversation_id: UUID \| None = None`; `input: str` (1–200000, verbatim); `config: dict[str, JsonValue]` and `effective_capabilities: dict[str, bool]` with default factories; `engine_session_id/workspace_id/trace_id: str \| None = None`; `execution_workdir: str \| None = None`; `timeout_seconds: int \| None = None` | timeout is strictly `>0`; workdir is opaque with no filesystem validation; Effective capabilities are not computed in this phase |
| ExecutionHandle | ExecutionKey; `provider_session_id: str \| None = None`; `process_id: int \| None = None` (strictly `>0`); `status: Literal["running"] = "running"`; `metadata: dict[str, JsonValue]` factory default | Only Result has terminal states; process_id/metadata are not automatically exposed through RunView or SSE |
| ExecutionResult | ExecutionKey; required `status: Literal["completed","failed","cancelled"]`; `output: str \| None = None`; `artifacts: list[dict[str, JsonValue]]` factory default; `usage/engine_metadata: dict[str, JsonValue]` factory defaults; `error: ExecutionError \| None = None` | State combinations follow R2; collection defaults are not shared |
| ExecutionError | `contract_version`; required `category` and `code` enums; serialized read-only computed `message`; `retryable: bool = False`; restricted `details` default empty | message is computed only from the static code catalog; callers cannot supply dynamic text and raw exceptions are not serialized |
| AgentEvent | required `event_id: UUID`; ExecutionKey; `schema_version`; `engine_session_id: str \| None = None`; `sequence: int >= 1`; `event_type`; `source: Literal["platform","engine_native"]`; required timezone-aware `timestamp`; `payload: dict[str, JsonValue]` factory default; `trace_id: str \| None = None` | timestamp is normalized to UTC but is not an ordering key; standalone Event validates fields only; no wall-clock/random default factories |
| EngineCapabilities | `contract_version`; 11 strict booleans defaulting to False: `streaming`, `persistent_session`, `session_resume`, `cancellation`, `human_approval`, `interactive_input`, `tool_calling`, `file_operations`, `terminal_execution`, `native_events`, `workspace_required` | No implication rules; Declared is neither Available/Effective nor authorization |

Cross-object consistency is enforced at the **Adapter boundary and in the common contract suite**, not through implicit cross-model Pydantic validation: the Request tuple equals Adapter identity; Handle equals Request on every ExecutionKey field; Result/Event equal Handle on every ExecutionKey field; Event `engine_session_id` equals Handle `provider_session_id`, including None on both sides. Every mismatch is rejected and never repaired.

### R2: Result state combinations

Invalid combinations raise ValidationError directly; fields or states are never changed to repair them:

| status | output | error | artifacts / usage / engine_metadata |
|---|---|---|---|
| completed | str or None | must be None | all allowed |
| failed | must be None | required, with category other than cancelled | all allowed |
| cancelled | must be None | must be None | all allowed |

A built-in `TimeoutError` produces `failed + timeout/execution_timeout`; explicit user cancellation produces a cancelled Result without error. Late success is suppressed by Adapter state, not by constructing a success DTO and cleaning its output/error afterward.

### R3: Safe errors and static code catalog

`ExecutionError` is a data DTO; `AdapterExecutionError(Exception)` carries one safe ExecutionError; `ConfigurationError(AdapterExecutionError)` covers registry and lifecycle/configuration misuse. Direct malformed DTO construction raises Pydantic ValidationError. Registry/Adapter boundaries convert validation failures without copying raw Pydantic values or exception strings.

The ten lower-snake-case categories are `configuration_error`, `engine_unavailable`, `protocol_error`, `authentication_error`, `permission_denied`, `resource_exhausted`, `timeout`, `cancelled`, `workspace_error`, and `internal_error`. Each code belongs to exactly one category:

| category | codes |
|---|---|
| configuration_error | invalid_request, invalid_handle, invalid_result, invalid_event, invalid_scenario, invalid_adapter_state, duplicate_engine, duplicate_protocol, duplicate_adapter, unknown_engine, engine_disabled, unknown_protocol, protocol_disabled, incompatible_engine_protocol, unknown_adapter_version, adapter_disabled, adapter_factory_failed, adapter_identity_mismatch, adapter_contract_mismatch |
| engine_unavailable | engine_unavailable |
| protocol_error | protocol_error, event_identity_conflict |
| authentication_error | authentication_failed |
| permission_denied | permission_denied |
| resource_exhausted | resource_exhausted |
| timeout | execution_timeout |
| cancelled | execution_cancelled |
| workspace_error | workspace_error |
| internal_error | internal_error, simulated_process_failure |

Static messages come only from the code catalog and contain no dynamic sensitive values. `details` is a restricted, extra-forbidding structure that defaults to empty and permits only `engine_id`, `protocol_id`, `adapter_version`, `field`, and `operation`. Values are bounded strict strings validated by the corresponding ID/version/slug rules; exception text, config, input, provider responses, and free-form reason are not accepted.

Built-in `TimeoutError` maps to `timeout/execution_timeout`; unknown Exception maps to `internal_error/internal_error` without `str(exc)` or a stack. Caller-task `asyncio.CancelledError` propagates after cleanup; explicit Adapter cancel produces a cancelled Result rather than attaching a cancelled error to that Result. `retryable` defaults to False; only explicit pre-start `engine_unavailable` / `resource_exhausted` may be True, while post-start failure and timeout default to False. Phase 1 never retries automatically.

### R9: Safe ExecutionError.message serialization round trips (T2 quality review, 2026-11-08)

Before code changes, T2 quality review confirmed that `message` is a serialized computed field, while `extra="forbid"` rejects that serialized field as extra during `ExecutionError.model_validate(error.model_dump())`, `model_validate_json(error.model_dump_json())`, and JSON round trips of an Error nested in failed ExecutionResult. R9 closes this defect without a new DTO schema, transport persistence, or API change:

1. `message` remains a read-only serialized computed value derived only from the static catalog entry for the supplied code; it never becomes caller-overridable text.
2. Before-validation handles direct construction, mapping/JSON input, and Errors nested in failed Results: if input contains `message`, accept it only when it is a string exactly equal to the static catalog message for the supplied code, as a no-op integrity token. Remove/discard it during before-validation and recompute from code without storing caller text separately. Direct construction with an exact catalog value is only the same no-op token.
3. Arbitrary, mismatched, non-string, or otherwise dynamic `message` values raise Pydantic ValidationError; when code is missing/invalid and input still contains `message`, reject it as well rather than silently ignoring arbitrary message input.
4. Successful direct `model_validate(model_dump())`, direct `model_validate_json(model_dump_json())`, and nested failed-Result mapping/JSON round trips must preserve the safe `model_dump` representation; input never overrides the computed property. Arbitrary caller text remains forbidden, and traceback/exception redaction rules are unchanged.

### Responsibility boundaries and dependency direction

- `contracts` expresses data and the Adapter Protocol only; it does not operate the Worker queue, decide tenant authorization, or commit Run terminal states.
- `registry` stores descriptors and independent factories only; it performs no dynamic network discovery, real health checks, or RuntimeEngine construction, and imports no concrete Adapter.
- `LocalTestAdapter` simulates Adapter semantics and does not import Registry; “process failure” is not evidence of a Process Supervisor.
- Dependencies flow only as `extension_contracts.base <- agent_execution.contracts <- registry and adapters.testing`; tests then depend on those modules. Contracts must not import Registry/Worker/Repository/Factory/concrete Engines, and package `__init__` files must not eagerly import test Adapters.
- Existing `extension_contracts/base.py` and `runtime.py` remain zero-diff; Engine Adapters are not inserted into the Capability/Extension Registry.

## Core Flows

### R5: Adapter signatures and lifecycle

```python
@property engine_id / protocol_id / adapter_version -> str
async get_capabilities() -> EngineCapabilities
async start(request: ExecutionRequest) -> ExecutionHandle
def stream_events(handle: ExecutionHandle) -> AsyncIterator[AgentEvent]  # normally an async generator
async cancel(handle: ExecutionHandle) -> None
async collect_result(handle: ExecutionHandle) -> ExecutionResult
```

- Each Adapter instance has one active execution, and every Registry resolution creates a fresh instance. A second start fails with `configuration_error/invalid_adapter_state`.
- Once the first `stream_events(handle)` call has validly created a consumer, every second consumer attempt fails with `configuration_error/invalid_adapter_state`, whether it is concurrent with the first iterator or sequential after the first iterator closes. Phase 1 has no stream replay/restart semantics.
- `collect_result` may be called immediately after start and concurrently with stream consumption. Repeated/concurrent calls share one terminal future and return equal Results; cancellation of one waiting caller must not cancel the shared execution.
- No event becomes visible after the terminal Result is visible. cancel requires a valid Handle; before terminal state it atomically wins if it completes first, returning a cancelled Result and closing the stream. Repeated/concurrent cancel is safe; after another terminal state it is a no-op, and an already-successful result remains successful.
- Early async-generator `aclose()`, timeout, stream failure, and collector cancellation all clean up without an Adapter-owned pending task.
- Wrong Handles/state use safe configuration errors; malformed Handle/Event/Result produced by the Adapter itself uses protocol errors. Caller `invalid_*` misuse and Adapter-produced protocol violations remain distinct.

### R4: Event anomalies and the high-water mark

A standalone AgentEvent validates fields only. Normal LocalTest streams use contiguous `1..N`; other Adapters may have monotonically increasing sequences with gaps. Each active execution independently tracks a high-water mark, with no global or persistent registry:

1. The same `(execution_id,event_id)` and full DTO equality is an exact duplicate: yield it unchanged, do not advance the high-water mark, and do not deduplicate/drop it.
2. The same event_id with different content raises `protocol_error/event_identity_conflict`; never repair the event.
3. A new event_id with `sequence <= high-water` is late/out-of-order: yield unchanged and do not lower the high-water mark.
4. A new event_id above the high-water mark is valid despite gaps: yield and advance to that sequence. Timestamp is not an ordering key.

These observable anomalies apply while the execution is active. After cancellation or another terminal Result, LocalTest closes the stream and suppresses later scripted events/results; the first terminal state cannot be overwritten.

### R6: Registration and exact resolution

Descriptors are `EngineDescriptor(engine_id, enabled=True)`, `ProtocolDescriptor(protocol_id, enabled=True)`, and `AdapterDescriptor(engine_id, protocol_id, adapter_version, enabled=True)`. A synchronous `Callable[[], AgentEngineAdapter]` factory is stored separately from its descriptor; one factory registers exactly one tuple and cannot cover multiple combinations.

Duplicate Engine, Protocol, or exact Adapter registration is always rejected, even when identical. Referenced Engine/Protocol records must exist before Adapter registration; disabled descriptors may register but cannot resolve. Resolution returns the first configuration error in this order:

`unknown_engine -> engine_disabled -> unknown_protocol -> protocol_disabled -> incompatible_engine_protocol (the pair has no registration) -> unknown_adapter_version (the pair exists only at other versions) -> adapter_disabled`.

Factory exceptions, wrong instance identity, and missing protocol methods map respectively to `adapter_factory_failed`, `adapter_identity_mismatch`, and `adapter_contract_mismatch`; identity and contract checks finish before the instance escapes. Every resolve calls the factory again. No latest, fallback, discovery, health probing, singleton, or network access is allowed.

Lifecycle bound-signature checks use `Signature.bind` placeholders on bound methods without executing them: bind zero arguments for `get_capabilities` and one argument each for `start`, `stream_events`, `cancel`, and `collect_result`. Wrong arity is rejected with `adapter_contract_mismatch` before instance escape. This only clarifies Registry checking of R5's exact signatures and adds no lifecycle method.

### R10: Live-instance freshness for every resolution (T3 quality review, 2026-11-08)

T3 quality review confirmed that a singleton factory can return the same still-live Adapter across resolutions, while an A→B→A cycling factory can reuse its first object, violating one-active-execution-per-instance and state isolation. In addition to calling the factory again, every successful resolve must satisfy these fresh-instance rules:

1. The returned object must differ from every other still-live object previously returned by that **exact registration**. Live singleton or A→B→A cycled reuse is rejected on the later call with `ConfigurationError` + `configuration_error/adapter_contract_mismatch`, and the repeated object cannot escape.
2. Track returned objects with weak references per exact registration and compare identity only with `is`; never invoke arbitrary `__eq__` or use a reusable bare `id()` as identity. Prune dead references during resolution, and never strongly retain Adapters or extend their lifetime for freshness tracking.
3. Dead previously returned objects do not block later new objects, even when CPython reuses an address. Reject a non-weak-referenceable candidate before its first return with `adapter_contract_mismatch`. Adapter implementations must support weakrefs: normal classes do, while `__slots__` classes need `__weakref__`. This is a factory/implementation constraint, not a public Run/API field.
4. Freshness runs after existing awaitable cleanup, identity checks, and lifecycle contract checks, but before instance escape. Ordinary weakref/tracking failures map safely to `adapter_contract_mismatch` without raw exception text; `asyncio.CancelledError` and other `BaseException` control flow are neither swallowed nor rewritten.
5. When synchronous resolve encounters a factory-returned Future/Task, it must not await it or expand the factory into an asynchronous-factory API; reject the awaitable with `adapter_contract_mismatch` and cancel the returned Future/Task as cleanup. T3 must assert `future.cancelled()`, additionally await any Task fixture through cleanup, and leave no pending task. Caller `CancelledError`/other `BaseException` propagation is a separate boundary rule, tested independently from Future/Task cleanup.
6. Add no global singleton registry, strong instance cache, network, or threading behavior, and do not replace freshness with health probing or discovery.

### R7: LocalTestAdapter scenario driving

The test-only `LocalTestScenario` contains capabilities, start_error, ordered events, terminal result, optional completion_gate, per-event wait_for_gate, optional stream_error, and timeout/process_failure switches. Event scripts permit explicit sequence/event_id/timestamp overrides and `duplicate_of` exact duplicates; all other values have deterministic defaults.

- Identity is fixed at `(local-test,scripted,v1)` and cannot be overridden by a scenario; a Request naming another tuple fails before a Handle exists. The second Adapter is fixed at `(contract-probe,contract-scripted,v1)`.
- Event IDs derive from `execution_id + ordinal` using UUIDv5; timestamps use a fixed epoch plus ordinal offsets. Scenario execution forbids `uuid4()` / `datetime.now()`.
- A manually advanced fake clock controls timeout, and `asyncio.Event` gates control completion/events; real sleep never decides expected results.
- Timeout wakes waiters and produces failed Timeout; cancel releases gates and closes the stream. Post-terminal controls may attempt injection, but the Adapter suppresses it and preserves the first terminal state.
- Every run uses a fresh Adapter. Success/failure/cancel/timeout/iterator close await all owned tasks; assertions require every owned task to be done and no Adapter-owned or test-created pending task. Completed task references may remain for inspection, so the final task set need not be empty; a pre-execution empty-set assertion is a separate, independent condition.
- `process_id` remains None; simulated process failure uses `internal_error/simulated_process_failure` and is not Runtime Host evidence.

The common pytest suite reuses these semantics through abstract scenario construction, gate/clock controls, and cleanup assertions without importing concrete LocalTestAdapter types. The second Adapter does not subclass LocalTestAdapter and reuses the complete success, empty/multi-event, error, cancellation, duplicate/late, idempotent collection, and cleanup suite.

### R11: Owned-task completion assertions and retained references (final-review documentation clarification, 2026-11-09)

Final review found that some older wording requiring a finally empty Adapter-owned task set conflicted with the implementation/tests retaining completed task references. The consistent rule is that all owned tasks are awaited/done and no Adapter-owned or test-created pending task remains; completed task references may be retained and checked with `all(done)`. A pre-execution empty-set assertion verifies that a fresh execution inherited no tasks and is a separate, independent condition. This clarification changes no lifecycle code, task ownership, or cleanup behavior.

## Configuration and Model Invocation Path

This phase adds no Settings, environment variables, AgentConfig, external Engine, credential, or model invocation path. Tests construct trusted requests without real credentials, model Profiles, or tenant configuration. Phase 3 will generate config and Effective capabilities from typed configuration.

## Test Approach

| Layer | Cases |
|---|---|
| Unit | Strict/non-trimming DTOs, exact fields and default isolation, invalid Result combinations, static error catalog, capability defaults, cross-object boundaries, resolution order/factory checks, and dependency direction |
| Contract/integration | Two structurally independent Adapters reuse five-method, immediate/concurrent/idempotent collection, event-anomaly, cancellation-race, timeout, all-error-category, and cleanup cases |
| Regression | New tests, ruff check/format check, `test_core_boundaries.py`, and applicable Phase 0 Runtime/API/SSE regressions; zero protected-file diff and unchanged head/lockfile |

See `04-test-plan.en.md` for detailed steps and traceability. The full suite remains a CI responsibility under repository convention; unrun CI must never be reported as passed.

## Rollout and Rollback

- New packages are not wired into production composition; there are no database, deployment, runtime-flag, API/SSE, frontend, or credential changes.
- Rollback only reverts the unwired packages and tests, with no Alembic downgrade, data repair, or Worker switch.
- Any deviation from R1–R11 requires a new decision entry and synchronized 01–05/08 updates before implementation changes. Phase 2 integration must also revalidate v1 against actual React behavior.
