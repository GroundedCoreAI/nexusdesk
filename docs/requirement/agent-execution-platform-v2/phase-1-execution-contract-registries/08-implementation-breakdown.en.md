# Phase 1 - Execution Contracts and Registries: Implementation Breakdown

> Status: Decided (R1–R11 are the current frozen technical-design baseline and dev/qa execute T1–T8); local test and local automated acceptance evidence exists, the full suite and CI remain pending, and formal human acceptance/sign-off is incomplete
> Created: 2026-11-08
> Revised: 2026-11-09 (R11 owned-task documentation clarification; no lifecycle behavior change)
> Basis: all Chinese and English documents `01` through `05`, independent design review, and current-code inspection (backend @ `4dfcfb41e9cbb799753986c2d76134514bbd19be`)
> Constraints: isolated document/code implementation; no production wiring, API/SSE, Settings, migration, frontend, deploy, external Engine, or credential changes; run affected checks locally and leave the full suite to CI under repository convention; never report an unrun check as passed

## 1. Implementation Entry and Accepted Risk

| Item | Frozen baseline |
|---|---|
| Branch / target commit | `feat/agent-execution-platform-v2-phase1` / `4dfcfb41e9cbb799753986c2d76134514bbd19be` |
| Alembic | Sole head is `0057_industry_pack_runtime`; Phase 1 adds or modifies no migration |
| New-package state | `backend/src/agent_platform/core_platform/agent_execution` does not yet exist; every implementation path is proposed and new |
| Existing base class | `extension_contracts.base.ContractModel` already has `frozen=True`, `extra="forbid"`, `allow_inf_nan=False`, and `str_strip_whitespace=True`; Phase 1 only overrides strictness in a subclass and leaves the existing file zero-diff |
| Dependencies | `backend/uv.lock` remains unchanged and this phase adds no dependency |
| Phase 0 state | Implementation is committed and pushed, but clean committed-artifact CI double-runs, authorized real historical samples, and human sign-offs remain open; formal acceptance is incomplete |

**Entry-risk decision**: The user explicitly requested Phase 1 startup, so the open Phase 0 items above are an accepted entry risk that the product owner and QA continue to track. This is not Phase 0 acceptance, sign-off, or approval. No Phase 1 implementation, test, or acceptance evidence may be used retroactively as a Phase 0 passing conclusion.

## 2. Design Decision Summary

The independent design review returned **DESIGN NEEDS DECISIONS**. R1–R8 were the controller-approved initial closure decisions. Before code changes, T2 quality review on 2026-11-08 found the ExecutionError.message serialization round-trip defect, which the controller closed by adding R9. On the same date, T3 quality review confirmed that singleton/cycled factories can reuse still-live Adapters, which the controller closed by adding R10 for live-instance freshness. On 2026-11-09, final review found that some wording incorrectly required a finally empty Adapter-owned task set instead of no pending task, conflicting with the implementation/tests that retain completed task references and assert that all are done; the controller closed this as documentation-only clarification R11. Current R1–R11 have been backfilled into the affected 01–05 documents. Implementation must not replace these explicit rules with assumptions or library defaults. The historical T1 task record still describes only the R1–R8 freeze at that time and is not rewritten as though R9/R10/R11 had already existed; T2 retains its R9 scope and is not rewritten as though R10/R11 had already existed.

| # | Decision topic | Frozen conclusion | Backfilled documents |
|---|---|---|---|
| R1 | DTO base, identity, fields, and cross-object consistency | Strict non-trimming Phase 1 subclass; exact ExecutionKey/DTO fields; explicit versions and bounded opaque strings; cross-object consistency only at the Adapter boundary/common suite | 02 FR-1/FR-4, 03 R1, 04 UT-01–07 |
| R2 | Result terminal combinations | Reject invalid combinations without repair; fixed output/error rules for completed/failed/cancelled; late success suppressed by state | 02 FR-1/FR-2, 03 R2, 04 UT-04/IT-06–08 |
| R3 | Safe exceptions and static error catalog | DTO/AdapterExecutionError/ConfigurationError separation; ten categories, unique code ownership, static messages, restricted details, and no raw-exception disclosure | 02 FR-4, 03 R3, 04 UT-05/IT-03–06 |
| R4 | Event anomalies and high-water | Yield exact duplicates unchanged without advancing; reject event_id conflicts; yield late new IDs unchanged; allow gaps; suppress after terminal state | 02 FR-4, 03 R4, 04 IT-09 |
| R5 | Adapter signatures, shared terminal state, and cleanup | One active execution per instance; immediate/concurrent/idempotent collection; first terminal state wins cancellation races; no post-terminal event; cleanup on every exit | 02 FR-2, 03 R5, 04 IT-01/07/08/11 |
| R6 | Three registries and exact resolution | Descriptors separate from factories; reject every duplicate; fixed error precedence; fresh instance per resolution; identity/contract checks before escape | 02 FR-3, 03 R6, 04 UT-08–11 |
| R7 | Deterministic LocalTestAdapter | Fixed identity, declarative scenarios, UUIDv5/fixed epoch, fake clock/gates, first-terminal protection, full task cleanup; simulated failure is not Host evidence | 02 FR-5, 03 R7, 04 IT-01–09/11 |
| R8 | Reusable suite, second Adapter, and dependency direction | Abstract pytest suite has no concrete LocalTest dependency; structurally independent second Adapter; one-way Contracts/Registry/Adapter dependencies and no eager test-Adapter imports | 02 FR-6, 03 file overview/R7, 04 UT-12/IT-10 |
| R9 | Safe ExecutionError.message serialization round trips | Only an exact static-catalog string is a no-op integrity token discarded/recomputed before validation; arbitrary/mismatched/non-string message or message with missing/invalid code is rejected; direct/nested mapping/JSON preserves safe model_dump | 02 FR-1/FR-4/AC-4, 03 R9, 04 UT-05, 05 A4 |
| R10 | Live-instance freshness for every resolution | Track live objects per exact registration with weakrefs + `is`; reject singleton/A→B→A reuse and non-weakref candidates before escape; prune dead references, never strongly retain instances or use `__eq__`/bare `id()`, and never treat address reuse as identity | 02 FR-3/AC-5, 03 R6/R10, 04 UT-09/UT-11, 05 A5/A6 |
| R11 | Owned-task completion assertions and retained references | All owned tasks are awaited/done, with no Adapter-owned or test-created pending task; completed task references may be retained and checked with `all(done)`; a pre-execution empty-set assertion is a separate condition; documentation only, with no lifecycle behavior change | 03 R7/R11, 04 section 2/IT-11, 08 R7/R11 |

### R1 DTO schemas / identity

1. Reuse `extension_contracts.base.ContractModel` without modifying it. Add `ExecutionContractModel(ContractModel)` with explicit `strict=True` and `str_strip_whitespace=False`, retaining `frozen=True`, `extra="forbid"`, and `allow_inf_nan=False`. Never pre-trim raw input.
2. `ExecutionKey = execution_id: UUID + engine_id + protocol_id + adapter_version`, shared by Request/Handle/Result/Event. Request/Handle/Result/Error/Capabilities carry `contract_version: Literal["v1"]="v1"`; Event carries `schema_version: Literal["v1"]="v1"`. Explicit unsupported versions fail.
3. Engine/Protocol IDs match `^[a-z0-9][a-z0-9_-]{0,63}$`; versions match `^v[1-9][0-9]*$`. Reject `latest`, `v0`, `v01`, whitespace, and non-string coercion.
4. Common opaque strings are nonempty, at most 200 characters, control-character-free, and free of leading/trailing whitespace; IDs are never trimmed. `event_type` is at most 100 characters and matches `^[a-z0-9]+(?:[._-][a-z0-9]+)*$`. Request.input is not an opaque ID, permits newlines, and remains verbatim.

| DTO | Frozen fields (fields without stated defaults are required) |
|---|---|
| ExecutionRequest | ExecutionKey; `tenant_id: str` 1–200; `agent_id: UUID`; `conversation_id: UUID \| None = None`; `input: str` 1–200000 preserved verbatim; `config: dict[str, JsonValue] = factory(dict)`; `effective_capabilities: dict[str, bool] = factory(dict)`; `engine_session_id/workspace_id/trace_id: bounded nonempty str \| None = None`; `execution_workdir: str \| None = None` (opaque, no filesystem validation); `timeout_seconds: int \| None = None`, strictly >0 |
| ExecutionHandle | ExecutionKey; `provider_session_id: str \| None = None`; `process_id: int \| None = None`, strictly >0; `status: Literal["running"]="running"`; `metadata: dict[str, JsonValue] = factory(dict)`. Only Result has terminal states |
| ExecutionResult | ExecutionKey; required `status: Literal["completed","failed","cancelled"]`; `output: str \| None = None`; `artifacts: list[dict[str, JsonValue]] = factory(list)`; `usage/engine_metadata: dict[str, JsonValue] = factory(dict)`; `error: ExecutionError \| None = None` |
| ExecutionError | `contract_version`; required category/code enums; read-only serialized computed `message` derived only from the static code catalog; `retryable: bool = False`; restricted details default empty |
| AgentEvent | required `event_id: UUID`; ExecutionKey; `schema_version`; `engine_session_id: str \| None = None`; `sequence: int >= 1`; bounded lowercase dot/slug `event_type`; `source: Literal["platform","engine_native"]`; required timezone-aware datetime normalized to UTC; `payload: dict[str, JsonValue] = factory(dict)`; `trace_id: str \| None = None`. Deterministic Adapter execution has no wall-clock/random default factories |
| EngineCapabilities | `contract_version`; the 11 documented fields `streaming`, `persistent_session`, `session_resume`, `cancellation`, `human_approval`, `interactive_input`, `tool_calling`, `file_operations`, `terminal_execution`, `native_events`, and `workspace_required`, all strict bool=False; no implication rules |

Cross-object checks are not Pydantic cross-model magic: the Request tuple equals Adapter identity; Handle equals Request on every ExecutionKey field; Result/Event equal Handle on every ExecutionKey field; Event.engine_session_id equals Handle.provider_session_id, including None. The Adapter boundary and common contract suite reject mismatches and never repair them.

### R2 Result rules

| status | output | error | artifacts / usage / engine_metadata |
|---|---|---|---|
| completed | str or None | must be None | all allowed |
| failed | must be None | required and cannot have cancelled category | all allowed |
| cancelled | must be None | must be None | all allowed |

Malformed combinations directly raise ValidationError; never clear fields or change state to make them valid. Built-in TimeoutError maps to `failed + timeout/execution_timeout`; user cancellation maps to a cancelled Result without error. Late success is suppressed by Adapter state, not cleaned from a success DTO.

### R3 Errors

- `ExecutionError` is a data DTO; `AdapterExecutionError(Exception)` carries one safe ExecutionError; `ConfigurationError(AdapterExecutionError)` covers Registry and lifecycle/configuration misuse.
- Direct malformed DTO construction raises Pydantic ValidationError. Registry/Adapter boundaries convert validation failures without copying raw Pydantic values or exception strings. Wrong caller Handles/state use configuration errors; malformed Adapter-produced Handle/Event/Result uses protocol errors.
- Built-in `TimeoutError` maps to `timeout/execution_timeout`; unknown Exception maps to `internal_error/internal_error` without `str(exc)` or stack. Caller-task `asyncio.CancelledError` propagates after cleanup; explicit Adapter cancel produces a cancelled Result.
- The ten categories are `configuration_error`, `engine_unavailable`, `protocol_error`, `authentication_error`, `permission_denied`, `resource_exhausted`, `timeout`, `cancelled`, `workspace_error`, and `internal_error`. Each code belongs to exactly one category.
- `retryable` defaults to False; only explicit pre-start `engine_unavailable` / `resource_exhausted` may be True; post-start failure and timeout default to False; Phase 1 never retries automatically.
- Details defaults to empty and permits only bounded, strictly validated `engine_id`, `protocol_id`, `adapter_version`, `field`, and `operation`. IDs/versions follow R1 patterns and field/operation follow bounded slug validation; arbitrary exception text, config, input, provider response, reason, and extra keys are forbidden.

**Static code/message catalog** (messages are the complete fixed implementation strings, without interpolation):

| category | code | Static message | Retryable rule |
|---|---|---|---|
| configuration_error | invalid_request | Execution request is invalid. | False |
| configuration_error | invalid_handle | Execution handle is invalid. | False |
| configuration_error | invalid_result | Execution result is invalid. | False |
| configuration_error | invalid_event | Agent event is invalid. | False |
| configuration_error | invalid_scenario | Local test scenario is invalid. | False |
| configuration_error | invalid_adapter_state | Adapter state does not allow this operation. | False |
| configuration_error | duplicate_engine | Engine is already registered. | False |
| configuration_error | duplicate_protocol | Protocol is already registered. | False |
| configuration_error | duplicate_adapter | Adapter is already registered for this exact tuple. | False |
| configuration_error | unknown_engine | Engine is not registered. | False |
| configuration_error | engine_disabled | Engine is disabled. | False |
| configuration_error | unknown_protocol | Protocol is not registered. | False |
| configuration_error | protocol_disabled | Protocol is disabled. | False |
| configuration_error | incompatible_engine_protocol | Engine and protocol have no registered adapter combination. | False |
| configuration_error | unknown_adapter_version | Adapter version is not registered for this engine and protocol. | False |
| configuration_error | adapter_disabled | Adapter is disabled. | False |
| configuration_error | adapter_factory_failed | Adapter factory failed safely. | False |
| configuration_error | adapter_identity_mismatch | Adapter identity does not match its registration. | False |
| configuration_error | adapter_contract_mismatch | Adapter does not implement the required contract. | False |
| engine_unavailable | engine_unavailable | Engine is unavailable. | May be True only explicitly before start; otherwise False |
| protocol_error | protocol_error | Adapter protocol failed. | False |
| protocol_error | event_identity_conflict | Event identity conflicts with different content. | False |
| authentication_error | authentication_failed | Engine authentication failed. | False |
| permission_denied | permission_denied | Engine permission was denied. | False |
| resource_exhausted | resource_exhausted | Engine resources are exhausted. | May be True only explicitly before start; otherwise False |
| timeout | execution_timeout | Execution timed out. | False |
| cancelled | execution_cancelled | Execution was cancelled. | False; never attached to a cancelled Result |
| workspace_error | workspace_error | Engine workspace operation failed. | False |
| internal_error | internal_error | Execution failed internally. | False |
| internal_error | simulated_process_failure | Simulated process failure occurred. | False; not Host evidence |

### R4 Event stream semantics

- A standalone Event validates its own fields only. Normal LocalTest streams use contiguous `1..N`; other Adapters may be monotonic with gaps. High-water tracking is isolated per active execution, with no global/persistent registry.
- An exact duplicate has the same `(execution_id,event_id)` and full DTO equality: yield unchanged, do not advance high-water, and do not deduplicate/drop it.
- The same event_id with different content raises `protocol_error/event_identity_conflict` without repair. A new event_id with `sequence <= high-water` is late/out-of-order: yield unchanged and do not lower the mark. A new event_id above the mark permits gaps: yield and advance. Timestamp is not an ordering key.
- Observable anomalies apply only while active. After cancellation or another terminal Result, LocalTest closes the stream and suppresses later scripted events/results while preserving the first terminal state.

### R5 Adapter signatures / lifecycle

```python
@property engine_id / protocol_id / adapter_version -> str
async get_capabilities() -> EngineCapabilities
async start(request: ExecutionRequest) -> ExecutionHandle
def stream_events(handle: ExecutionHandle) -> AsyncIterator[AgentEvent]  # normally async generator
async cancel(handle: ExecutionHandle) -> None
async collect_result(handle: ExecutionHandle) -> ExecutionResult
```

1. Each Adapter instance has one active execution and each resolution returns a fresh instance; a second start fails with `configuration_error/invalid_adapter_state`. Once the first `stream_events(handle)` call has validly created a consumer, every second consumer attempt fails with `configuration_error/invalid_adapter_state`, whether concurrent with the first iterator or sequential after the first iterator closes. Phase 1 has no stream replay/restart semantics.
2. `collect_result` may be called immediately after start and concurrently with stream consumption. One shared terminal future makes repeated/concurrent calls return equal Results; shield the shared execution so one waiting caller's cancellation does not cancel it.
3. No event becomes visible after the terminal Result is visible. cancel requires a valid Handle; before terminal state it atomically wins if it completes first, returning a cancelled Result and closing the stream. Repeated/concurrent cancel is safe; after another terminal state it is a no-op, and an already-successful result remains successful.
4. Early async-generator `aclose()`, timeout, stream failure, and collector cancellation leave no Adapter-owned pending task. Waiter-cancellation isolation and final cleanup must both hold; shielding must not hide a leak.
5. Wrong Handles/state use safe configuration errors; malformed Adapter-produced Handle/Event/Result uses protocol errors.

### R6 Registries

- Descriptors are `EngineDescriptor(engine_id,enabled=True)`, `ProtocolDescriptor(protocol_id,enabled=True)`, and `AdapterDescriptor(engine_id,protocol_id,adapter_version,enabled=True)`. A synchronous `Callable[[],AgentEngineAdapter]` factory is stored separately; one registration maps to exactly one tuple, and one no-arg factory cannot be registered for multiple combinations.
- Duplicate Engine, Protocol, or exact Adapter registration is rejected even when identical. Referenced Engine/Protocol records must exist before Adapter registration; disabled records may register but not resolve.
- Resolution order is fixed: `unknown_engine -> engine_disabled -> unknown_protocol -> protocol_disabled -> incompatible_engine_protocol (the pair has no registration) -> unknown_adapter_version (the pair exists only at other versions) -> adapter_disabled`.
- Factory failure, wrong identity, and missing methods map respectively to `adapter_factory_failed`, `adapter_identity_mismatch`, and `adapter_contract_mismatch`. Check identity and contract before an instance escapes; call the factory again on every resolution. No latest, fallback, discovery, health probing, singleton, or network access.
- Lifecycle bound-signature checks use `Signature.bind` placeholders on bound methods without executing them: bind zero arguments for `get_capabilities` and one each for `start`/`stream_events`/`cancel`/`collect_result`; wrong arity maps to `adapter_contract_mismatch` without instance escape. This clarifies R5 signature checking and adds no lifecycle method.
- Every successful resolution must also satisfy R10 live-instance freshness; calling the factory again alone does not prove a fresh instance.

### R7 LocalTestAdapter

- The test-only declarative `LocalTestScenario` contains capabilities, start_error, ordered events, terminal result, optional completion_gate, per-event wait_for_gate, optional stream_error, and timeout/process_failure switches. Events permit explicit sequence/event_id/timestamp overrides and `duplicate_of` exact duplicates; other defaults are deterministic.
- Identity is fixed at `(local-test,scripted,v1)` and is not scenario-overridable; a Request naming another tuple fails before a Handle exists. The second Adapter is fixed at `(contract-probe,contract-scripted,v1)`.
- Event IDs derive from execution_id+ordinal through UUIDv5; timestamps use fixed epoch+ordinal offsets; scenario execution forbids uuid4/datetime.now. A manually advanced fake clock controls timeout and asyncio.Event gates control completion/events; real sleep never decides results.
- Timeout wakes waiters and produces failed Timeout; cancel releases gates and closes the stream. Post-terminal controls may attempt injection, but the Adapter suppresses it and preserves the first terminal state. Every run uses a fresh Adapter.
- Success/failure/cancel/timeout/iterator close await all owned tasks; assertions require every owned task to be done and no Adapter-owned or test-created pending task. Completed task references may remain for inspection, so the final task set need not be empty; a pre-execution empty-set assertion is a separate, independent condition. process_id remains None; simulated failure is `internal_error/simulated_process_failure`, not Host evidence.

### R8 Reusable suite / dependencies

- Pytest-only `backend/tests/agent_execution/adapter_contract_suite.py` provides abstract scenario construction, gate/clock controls, and cleanup assertions without importing concrete LocalTestAdapter types.
- `backend/tests/agent_execution/contract_probe_adapter.py` is a structurally independent second Adapter, not a LocalTestAdapter subclass, with identity `(contract-probe,contract-scripted,v1)`; it reuses the same success, empty/multi-event, error, cancellation, duplicate/late, idempotent collection, and cleanup suite.
- Dependencies flow as `extension_contracts.base <- agent_execution.contracts <- registry and adapters.testing`, with tests depending on them. Contracts do not import Registry/Worker/Repository/Factory/concrete Engines; Registry imports no concrete Adapter; LocalTestAdapter imports no Registry; package `__init__` files do not eagerly import test Adapters.

### R9 ExecutionError.message safe round-trip (T2 quality review, 2026-11-08)

**Discovery**: Before code changes, T2 quality review confirmed that serialized computed `message` conflicts with `extra="forbid"`, causing `ExecutionError.model_validate(error.model_dump())`, `model_validate_json(error.model_dump_json())`, and nested failed ExecutionResult JSON round trips to reject valid safe DTOs. The round-trip defect must be closed without opening arbitrary error text.

**Controller ruling**:

1. message remains a read-only serialized computed value derived only from the static catalog for the supplied code. If direct construction, mapping, or JSON input contains message, accept only a string exactly equal to that code's static catalog message; it is only a no-op integrity token, removed/discarded during before-validation and recomputed from code, never stored separately and never overriding the computed property. An exact catalog value in direct construction receives the same token treatment only.
2. Arbitrary, mismatched, non-string, or otherwise dynamic message raises Pydantic ValidationError; message input with missing/invalid code is also rejected rather than silently ignored. The rule applies consistently to direct construction, model_validate/model_validate_json, and ExecutionError nested in failed Result.
3. Successful direct `model_validate(model_dump())`, direct `model_validate_json(model_dump_json())`, and nested failed-Result mapping/JSON round trips preserve the safe model_dump representation. Arbitrary caller text remains forbidden, with no weakening of traceback or exception redaction.
4. No new DTO schema, transport persistence, or API change is introduced. T2 must include positive/negative direct and nested R9 cases in P1-UT-05 and complete spec/quality review before proceeding.

### R10 Live-instance freshness (T3 quality review, 2026-11-08)

**Discovery**: T3 quality review confirmed that a singleton factory can return the same still-live Adapter across resolutions, and an A→B→A cycling factory can reuse its first object. Calling the factory every time does not prevent shared active execution/state, so fresh-instance detection, failure classification, and lifecycle constraints must be frozen before implementation.

**Controller ruling**:

1. Every successful resolve must return an object distinct from every other still-live object previously returned by that exact registration. A second return of a live singleton and the third A→B→A reuse fail with `ConfigurationError` + `configuration_error/adapter_contract_mismatch`, and the repeated object cannot escape.
2. The Registry keeps weak references to returned objects per exact registration and compares identity only with `is`; never invoke arbitrary `__eq__` or use reusable bare `id()`. Prune dead references during resolution and never strongly retain Adapters or extend their lifetime for freshness. Dead objects do not block later new objects, even under CPython address reuse.
3. Reject non-weak-referenceable candidates before first return with `adapter_contract_mismatch`. Adapter implementations must support weakrefs; normal classes do, while `__slots__` classes need `__weakref__`. This is a factory/implementation constraint and adds no public Run/API field.
4. Freshness runs after existing awaitable cleanup, identity checks, and lifecycle contract checks, but before instance escape. Ordinary weakref/tracking failures map safely to `adapter_contract_mismatch` without raw exception text; `CancelledError` and other `BaseException` control flow continue to propagate.
5. T3 must use P1-UT-09 to cover `is not` for two simultaneously live results, singleton, A→B→A, non-weakref candidates, no arbitrary `__eq__` invocation, weakref/gc proof of no strong retention and dead-reference pruning, and address reuse not acting as identity. P1-UT-11 uses `Signature.bind` placeholders for zero/one-argument arity; synchronous resolve rejects a factory-returned Future/Task with `adapter_contract_mismatch` and cancels it as cleanup, asserts `future.cancelled()`, additionally awaits every Task fixture through cleanup, and leaves no pending task; a separate boundary case proves `CancelledError`/other `BaseException` propagation independently from Future/Task cleanup. This does not expand the synchronous factory API.
6. Add no global singleton registry, strong instance cache, network, or threading behavior. T3 must synchronize this ruling and 02–05 before Registry implementation and close spec/quality review before T4.

### R11 Owned-task completion assertions and retained references (final-review documentation clarification, 2026-11-09)

**Discovery**: Some wording in 03/04/08 required a finally empty Adapter-owned task set, while the implementation and tests retain completed task references and assert `all(task.done() for task in owned_tasks)` plus no pending task. A finally empty set is not the same condition as all tasks being done with none left dangling.

**Controller ruling**:

1. Success/failure/cancel/timeout/iterator close and other completion paths must await every Adapter-owned task, and all of those tasks must be done. No Adapter-owned or test-created pending task may remain.
2. The Adapter and tests may retain completed task references for inspection. Final assertions require all retained owned tasks to be done (for example, `all(done)`), not an empty final task set.
3. A pre-execution assertion that the Adapter-owned task set is empty proves that a fresh execution inherited no tasks. It is a separate condition from having no pending task after completion and must not be removed or conflated by this clarification.
4. This ruling only aligns the Chinese and English wording in 03/04/08; it changes no lifecycle code, task ownership, or cleanup behavior. The later evidence task will update 06/07 evidence and conclusions from actual execution results.

## 3. Tasks in Dependency Order

Dependency path: **T1 design freeze -> T2 contracts -> T3 registries -> T4 common suite and LocalTest -> T5 independent second Adapter -> T6 isolation/regression evidence -> T7 test report -> T8 acceptance report and final independent review**. Registry/Adapter code in T3 and T4 retains one-way dependencies; T5 must not change common interfaces to fit the suite.

| # | Task | Files (new/modified) | Depends on | Traceability | Verification gate |
|---|---|---|---|---|---|
| T1 | Freeze R1–R8, backfill 01–05, create the bilingual breakdown, and update root README status; write no code | This directory's `01-business-goals.md`, `02-requirements.md`, `03-technical-design.md`, `04-test-plan.md`, `05-acceptance-plan.md`, and this file (each with `.en.md`); topic `README.md` / `README.en.md` | — | R1–R8; all G/FR/AC | Substantive Chinese/English parity; complete R1–R8 and T1–T8; documents only; run `git diff --check` for tracked edits plus explicit trailing-whitespace/final-newline checks covering all 14 documents, including both untracked 08 files; do not require `git add` or change the index; no claim of Phase 0 acceptance or passing Phase 1 tests |
| T2 | Implement strict contracts, safe error catalog, and Adapter Protocol | New `backend/src/agent_platform/core_platform/agent_execution/{__init__.py,contracts/{__init__.py,base.py,common.py,request.py,handle.py,result.py,events.py,capabilities.py,errors.py,adapter.py}}`; new `backend/tests/test_agent_execution_contracts.py` | T1 | FR-1/FR-2/FR-4, AC-1/AC-4, P1-UT-01–07 and P1-UT-12 (contracts/package-entry-point portion), R1–R3/R5/R8/R9 | Run that test file, UT-01–07, and only the UT-12 contracts/package-entry-point dependency assertions; add and run assertions only for subjects that now exist, without requiring Registry/LocalTestAdapter subjects early, but any module scheduled for this task must fail if absent rather than skip or pass because it is absent; check exact fields, static catalog, ValidationError, safe mapping, and R9 direct/nested mapping/JSON round trips plus arbitrary/mismatched/non-string message rejection; spec review then quality review, with every finding fixed and re-reviewed before T3 |
| T3 | Implement three registries, descriptors, exact resolution, and factory checks | New `backend/src/agent_platform/core_platform/agent_execution/registry/{__init__.py,engine_registry.py,protocol_registry.py,adapter_registry.py}`; new `backend/tests/test_agent_execution_registries.py` | T2 | FR-3, AC-5/AC-6, P1-UT-08–11 and P1-UT-12 (new Registry portion), registration/resolution prerequisites of P1-IT-03/04, R3/R5/R6/R8/R10 | Run Registry tests, UT-08–11, and the accumulated UT-12 contracts/package-entry-point plus new Registry dependency assertions; an absent Registry module or an assertion that did not actually execute must fail rather than skip/absent-pass, while the LocalTestAdapter portion is not required yet; verify duplicates, references, disabled entries, error precedence, and three factory failures; under R10 verify `is not` for two live results, live singleton/A→B→A/non-weakref rejection without escape, weakref/gc no-strong-retention and dead-reference pruning, and no `__eq__`/bare `id()`/address-reuse identity; use `Signature.bind` placeholders for zero capabilities arguments/one argument for each other method and wrong arity; synchronous resolve rejects a Future/Task candidate with `adapter_contract_mismatch` and cancels it as cleanup, asserting `future.cancelled()`, awaited Task-fixture cleanup, and no pending task, with `BaseException` propagation verified independently; name and actually execute the lifecycle-shape/signature, freshness/weakref, singleton/cycle, Future/Task cleanup, and safe-inspection regressions (no premature instance escape or raw exception text); close spec review then quality review before T4 |
| T4 | Implement reusable pytest contract suite and deterministic LocalTestAdapter | New `backend/tests/agent_execution/{__init__.py,adapter_contract_suite.py}`; new `backend/src/agent_platform/core_platform/agent_execution/adapters/{__init__.py,testing/{__init__.py,local_test_adapter.py}}`; new `backend/tests/test_local_test_adapter.py` | T2 (suite/Adapter), T3 (composition verification) | FR-2/FR-4/FR-5, AC-2/AC-3/AC-4/AC-7, P1-IT-01–09/11, related P1-UT-03/05/07, P1-UT-12 (completed in this task), and P1-CM-04/05, R2–R5/R7/R8 | Add and run UT-12 assertions that LocalTestAdapter does not import Registry and package entry points do not eagerly import test Adapters, then run the complete P1-UT-12 together with the accumulated T2/T3 assertions; absent LocalTestAdapter/package entry points or assertions that did not actually execute must fail rather than skip/absent-pass; run at least two consecutive rounds covering immediate/concurrent collection, event anomalies, cancellation races, fake clock, aclose, and all errors, and assert owned/test task cleanup; close spec review then quality review before T5 |
| T5 | Add a structurally independent second Adapter and reuse the same suite and registration tests | New `backend/tests/agent_execution/contract_probe_adapter.py` and `backend/tests/test_agent_execution_contract_probe.py`; do not change T2 common contracts, T3 Registry interfaces, or Worker | T3, T4 | AC-5, P1-IT-10, G1/G2, R8 | Fixed `(contract-probe,contract-scripted,v1)`; verify non-inheritance and no concrete LocalTest imports in the suite; reuse success, empty/multi-event, error, cancellation, duplicate/late, idempotent collection, cleanup, and registration; zero common-contract/Worker diff; close spec review then quality review before T6 |
| T6 | Produce isolation, static-check, architecture, and applicable regression evidence | No planned code/document modification; inspect T2–T5 files, protected files, `backend/migrations/versions/`, and `backend/uv.lock` read-only, preserving raw output for T7 | T5 | Complete P1-UT-12 rerun, P1-CM-01–06, AC-8, 04 section 6, FR-6/G4 | Run every T6 gate below and rerun complete P1-UT-12 (contracts/package entry points, Registry, LocalTestAdapter, and no-eager-test-import all actually execute; absence must not skip/absent-pass); zero protected-file diff, head=0057, unchanged lockfile; full suite remains in CI and unrun items are recorded honestly; close spec review then quality review before T7 |
| T7 | Execute 04 item by item and write the bilingual test report only from actual evidence | New `06-test-report.md` / `06-test-report.en.md`, created only when T7 actually executes | T6 | All P1-UT/IT/CM in 04, AC-1–8, T2–T6 | One independent row per UT/IT/CM with file::case, environment, result, and evidence; record defects D-n, residual risks, skip/pending_env, and CI boundaries; never prewrite passes |
| T8 | Execute 05 item by item, write the bilingual acceptance report, and complete a final independent overall review | New `07-acceptance-report.md` / `07-acceptance-report.en.md`, created only during actual T8 acceptance | T7 | 05 A1–A8, C1–C4, business metrics, and sign-offs | Mark unavailable environments `pending_env` and human sign-offs `pending`, never pre-approved; all final independent overall-review findings must be fixed and re-reviewed before completion |

Reports follow the requirement-lifecycle skill's `06-test-report.md` / `07-acceptance-report.md` templates. T1 does not create 06/07; T7/T8 record only actual execution evidence.

### T6 reproducible verification gates

Run affected tests and static checks from `backend/` (paths remain exact to files added in T2–T5):

```bash
uv run pytest tests/test_agent_execution_contracts.py tests/test_agent_execution_registries.py tests/test_local_test_adapter.py tests/test_agent_execution_contract_probe.py
uv run ruff check src tests
uv run ruff format --check src/agent_platform/core_platform/agent_execution tests/agent_execution tests/test_agent_execution_contracts.py tests/test_agent_execution_registries.py tests/test_local_test_adapter.py tests/test_agent_execution_contract_probe.py
uv run pytest tests/test_core_boundaries.py
uv run pytest tests/test_runtime_engine.py tests/test_runtime_postgres.py tests/test_open_platform.py tests/test_extension_contracts.py tests/test_runtime_baseline.py
uv run alembic heads
```

- PostgreSQL regression uses a dedicated `TEST_DATABASE_URL`; when the environment is unavailable, record `pending_env` rather than claiming an unrun check passed.
- From the repository root, run `git diff --exit-code 4dfcfb41e9cbb799753986c2d76134514bbd19be -- <protected paths>` against the entry baseline. Protected paths include at least:
  - `backend/src/agent_platform/extension_contracts/base.py` and `runtime.py`;
  - `backend/src/agent_platform/applications/platform_runtime/runtime_factory.py` and `runtime_composition.py`;
  - `backend/src/agent_platform/applications/customer_service/runtime_factory.py` and `runtime_composition.py`;
  - `backend/src/agent_platform/core_platform/agent_runtime/worker.py`, `repository.py`, and `schemas.py`;
  - `backend/migrations/versions/`, `backend/pyproject.toml`, and `backend/uv.lock`;
  - `backend/src/agent_platform/business_capabilities/customer_service/routing/settings.py` and `backend/src/agent_platform/core_platform/platform_services/platform_settings/settings.py`;
  - `backend/.env.example`, `deploy/production/.env.example`, and `frontend/.env.example`;
  - zero diff across the entire `frontend/` and `deploy/` directories.

Except for `backend/src/agent_platform/core_platform/agent_execution/`, `backend/tests/agent_execution/`, and the four new test files explicitly listed in T2–T5, plus the documents listed in T1/T7/T8, every other existing repository path must remain zero-diff. The protected list above is a minimum set, not permission to modify unlisted existing paths.
- `alembic heads` must remain `0057_industry_pack_runtime`, and `backend/uv.lock` must have zero diff. The full test suite is not mandatory locally before commit under repository convention; CI runs it on push/PR. This task has no automatic commit/push/PR step and must not claim unrun CI passed.

## 4. Completion and Stop Conditions

- **Stop for design deviation**: If implementation conflicts with current R1–R11 or 01–05, first add an R entry explaining why and synchronize affected Chinese/English documents, then change code; never silently change contracts.
- **Two serial review gates**: After each implementation task T2–T6, perform spec review and then quality review; do not start the next task until every finding is fixed and re-reviewed. T7/T8 evidence and the final overall review likewise cannot close with unresolved findings.
- **Hard scope boundary**: No production wiring, public API/SSE, Settings/environment variable, Alembic migration, frontend, deploy, external Engine, credential, or real Runtime Host change; no existing ContractModel or lockfile modification.
- **Hard evidence boundary**: Without actual test, CI, real-sample, environment, or human-signoff evidence, retain open/pending/pending_env; the Phase 0 entry risk is not acceptance, and Phase 1 startup is not passing tests.
- **Stop for safety/determinism**: Sensitive-text disclosure, cross-tenant state, terminal-state overwrite, repairing rather than rejecting event identity conflicts, real sleep deciding results, or dangling tasks follow the P0/P1 rules in 04.
- **No automatic commits**: This breakdown contains no automatic commit, push, or PR step; only a later explicit user request starts the repository submission workflow.
