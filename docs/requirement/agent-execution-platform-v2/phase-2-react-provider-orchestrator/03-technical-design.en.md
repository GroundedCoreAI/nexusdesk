# Phase 2 · React Provider and Execution Orchestrator — Technical Design

> Status: Local T2–T11 and R17 live validation are complete, as are the R18 production remediation and focused validation; see 06/07 and their appendices. Minimal R18 live on/off revalidation is complete; the overall result remains conditionally passed
> Created: 2026-11-02
> Revised: 2026-11-12 (R18: Worker terminal logs follow successful normal finish; current-status alignment)
> Basis: `docs/architecture/agent-execution-platform-v2.md`, Sections 4–7, 12, 14–17, 19, and 21; Phase 0 `baseline/run-lifecycle-events.md`; Phase 1 `backend/tests/agent_execution/adapter_contract_suite.py`; `02-requirements.md` (FR-1–FR-6, AC-1–AC-9); `08-implementation-breakdown.md` (R1–R18, T1–T11); backend baseline `0a6c4b5`

## 1. Current-State Review and Change Overview

Phase 1 code has merged into integration through merge `0a6c4b5`, while formal human acceptance remains separate. `RuntimeEngine.run()` returns `(output, history, dropped)`; Worker handles fingerprint, Memory rendering, heartbeat/cancel monitoring, Runtime invocation, and `repository.finish()`; Repository atomically maintains event sequences, owner/lease, submission-order terminal protection, and distinct append/finish control flow; the composition root assembles the single RuntimeFactory/Worker; internal/open routes consume the existing event table and Notifier. Except for existing-state notes, everything below is **proposed and not implemented**.

The read-only command `uv run --directory backend alembic heads` observed `0057_industry_pack_runtime (head)` on 2026-11-10. This describes only the current baseline; implementation and testing must read it dynamically again and must not treat it as a permanent acceptance constant.

| Layer | File | Change |
|---|---|---|
| Migration/ORM/frontend | `backend/migrations/versions/`, existing ORM, `frontend/` | Zero additions/modifications; tests dynamically compare heads, empty-database upgrade, and before/after directory inventories/hashes |
| New module | `backend/src/agent_platform/core_platform/agent_execution/adapters/react/{__init__.py,adapter.py}` | ReactAdapter five methods, first-emission gate, private runtime_emit, ack-aware stream, cancellation, and unique terminal state |
| New module | `.../adapters/react/event_mapper.py` | Open business-event mapping from `(kind,data)` to AgentEvent and back, plus reserved-event rejection |
| New module | `.../adapters/react/error_mapper.py` | Safe public mapping for every Engine/Gateway/Domain RuntimeFault, future unknown codes, Timeout, and unknown exceptions while privately retaining original codes |
| New module | `.../agent_execution/orchestration/{__init__.py,execution_context.py}` | Private ExecutionContext and synchronous ContextVar capture/reset scope; contains neither worker_emit nor runtime_emit |
| New module | `.../orchestration/execution_lifecycle.py` | Private ExecutionOutcome, non-optional usage, runtime-checkable AcknowledgingEventStream and OutcomeCollectingAdapter/helpers, and pure conversion without importing React |
| New module | `.../orchestration/orchestrator.py` | Fixed selection, exclusive worker_emit, start→claim→release, ack/Outcome protocol detection, ack after worker_emit, drain→single React-private collect or LocalTest public fallback, and abort/aclose |
| Application factory | `backend/src/agent_platform/applications/platform_runtime/react_adapter_factory.py` | Synchronous zero-argument factory captures current Context into a new instance; no await, worker_emit access, or later ContextVar reads |
| Existing Factory | `.../platform_runtime/runtime_factory.py` | Preserve existing ReAct construction; on-path Adapter passes private runtime_emit to both for_run and runtime.run while legacy off remains unchanged |
| Composition root | `.../platform_runtime/runtime_composition.py` | Register react/native/v1, build Orchestrator, optionally inject Worker, and exclude the new flag from fingerprint |
| Worker | `backend/src/agent_platform/core_platform/agent_runtime/worker.py` | Final `orchestrator=None`; unchanged off path, on-path original callback passed as worker_emit, and retained Memory/monitor/finish |
| Settings | `backend/src/agent_platform/core_platform/platform_services/platform_settings/settings.py` | Add `execution_orchestrator_enabled: bool = False` |
| Environment/deployment | `backend/.env.example`, `deploy/production/.env.example`, `compose.yaml`, `deploy/quickstart/compose.yaml`, `deploy/production/compose.yaml` | Add only necessary AGENT_EXECUTION_ORCHESTRATOR_ENABLED placeholders/interpolation; no new service, secret, or UI |
| Quickstart logging | `deploy/quickstart/uvicorn-logging.yaml`, `deploy/quickstart/supervisord.conf`, `Dockerfile` | R17: quickstart API loads a dedicated configuration through `--log-config`; only the Worker logger emits controlled path logs at INFO while root stays WARNING, with no new service or sensitive field |
| Protected modules | Phase 1 contracts/registries/LocalTest, `agent_runtime/{engine,repository,schemas}.py`, runtime hooks, API/SSE routes | Remain unchanged; any parity fix requires a new R and synchronized design first, with no public schema/terminal semantic change |
| Tests | New `backend/tests/test_react_engine_adapter.py`, `test_execution_orchestrator.py`; extend `test_runtime_baseline.py`, `test_runtime_postgres.py`, `test_open_platform.py`, `test_agent_config_execution_compat.py`, and real Memory tests | Dual-emit spies, function-by-function common/private contract coverage, concurrency/ack/backpressure, PG/SSE/Memory, errors/cancellation/Lease, mixed-Worker/rollback evidence |

## 2. Data Model and Responsibility Boundaries

### 2.1 No Database Model Change and Identity Rules

One `runtime_runs` row remains one Execution attempt. `ExecutionRequest.execution_id` retains its Phase 1 UUID field, must contain an exact stdlib UUID, and has a value directly equal to claimed `row.id`; never create another Execution ID. Under R16, the ExecutionContext-private boundary normalizes `row.id` and the supplied `execution_id` separately and compares their values with `==`, never `is`: an exact stdlib UUID is returned unchanged with its original object identity, while a UUID subclass such as asyncpg's return type undergoes controlled value conversion such as `UUID(str(value))` to produce an exact stdlib UUID. This transient canonical parse occurs only at the private boundary, is not prohibited public stringification, and changes no public DTO, schema, or serialization shape. Strings, integers, None, forged non-UUID values, and value mismatches fail safely with static `INVALID_REQUEST`; ordinary exceptions raised by a malicious subclass `__str__` or descriptor likewise become safe static `INVALID_REQUEST` without disclosing the original exception, while control-flow exceptions re-raise unchanged. Add no Engine columns, Task tables, Session tables, or event fields; the fixed tuple appears only in in-memory DTOs and safe logs/traces.

Agent identity rules:

1. With a snapshot, strictly parse the real UUID from `config.agent.id`; missing, malformed, or nil values fail safely with no fallback or borrowed row/conversation UUID.
2. Only with no snapshot and React + legacy `base_runtime`, the internal Request may use `UUID(int=0)` as an anonymous unbound Agent to remain compatible with the Phase 1 DTO.
3. The nil sentinel never enters selectors, authorization, tenant/credential/Agent queries, DB, HTTP/SSE, logs, metrics, or engine_metadata; the runtime factory never uses nil to query an Agent.
4. Phase 3 removes this compatibility sentinel through a formal identity model; Phase 1 DTOs remain unchanged.

### 2.2 Private Context, Dual Emits, and Results

| Object | Contents and direction | Visible scope/prohibitions |
|---|---|---|
| ExecutionContext | `context.row` is the same original claimed Mapping, plus normalized exact-stdlib-UUID execution_id, history, summary_message, customer_memory, trace/timeout, and related values | Worker→Orchestrator→synchronous application-factory capture→ReactAdapter; **contains neither worker_emit nor runtime_emit**, is never serialized or shared across executions; the original `row.id` is never copied, replaced, or rewritten, `RuntimeFactory.for_run` continues to receive the original row, and public Request uses the normalized exact stdlib UUID |
| worker_emit | Original Worker event callback, Worker→`orchestrator.execute(context, worker_emit)`; sole existing callback that writes Repository.append or Notifier | Worker/Orchestrator only; never enters Context, Adapter, RuntimeFactory, PlatformTools, or RuntimeEngine |
| runtime_emit | ReactAdapter-private callback; the same function object is passed to both `RuntimeFactory.for_run(row, runtime_emit)` and `runtime.run(..., runtime_emit, ...)` | Only performs `(kind,data)→AgentEvent→React-private stream`; never directly reaches worker_emit, Repository, or Notifier |
| ExecutionOutcome | status, output, history, dropped, legacy error_code, non-optional usage, and private helper values | ReactAdapter-private `collect_outcome`→Orchestrator→Worker; protocol-free LocalTest uses only public `collect_result→from_result` deterministic fallback; history/dropped reach Memory completion hooks only after successful execution |
| Public ExecutionResult | Unchanged Phase 1 fields with safe status/output/usage/artifacts/engine_metadata/error | engine_metadata cannot smuggle history, dropped, Outcome, Context, callbacks, or new HTTP/SSE fields |
| AgentEvent | UUID event_id, UTC timestamp, local monotonic sequence, source=engine_native, original event_type/payload | In-process envelope only; changes neither DB event_seq nor SSE ID |

Worker retains queueing, concurrency, owner, heartbeat, fingerprint, and final finish; Orchestrator never writes the DB directly; Adapter never operates the queue, decides authorization, or calls Repository.finish. Core imports no applications/business; the application composition root injects RuntimeFactory capability.

## 3. Synchronous Registry, Asynchronous Runtime, and Dual-Emit Assembly

A Registry factory remains a synchronous `Callable[[], AgentEngineAdapter]`, zero-argument and fresh-instance. Never use an async factory or await `RuntimeFactory.for_run()` inside synchronous resolve.

```text
Worker._execute(on)
  └─ orchestrator.execute(context, worker_emit)

Orchestrator
  └─ synchronous no-await section:
       token = execution_context_var.set(context)  # context contains no emit
       try: adapter = registry.resolve(react, native, v1)
       finally: execution_context_var.reset(token)

Application zero-argument ReactAdapterFactory (called indirectly only in that section)
  └─ read and validate current ExecutionContext
     → capture context and RuntimeFactory reference into a new ReactAdapter
     → return; Adapter never reads ContextVar afterward and knows no worker_emit

adapter.start(request)
  └─ create runner and a closed first-emission gate
     → runner creates private runtime_emit
     → await runtime_factory.for_run(same claimed row, runtime_emit)
     → runtime.run(..., the same runtime_emit, ...)

Normal Orchestrator path
  └─ start → synchronously claim stream_events (opening the emission gate)
     → take AgentEvent from public stream
     → restore (kind,data) → await worker_emit(kind,data)
     → await acknowledge(event) only after success
     → drain
     → React: await collect_outcome(handle)  # private entry, exactly once
       LocalTest: await collect_result(handle)
                 → ExecutionOutcome.from_result(..., explicit deterministic legacy code)  # fallback only without protocol
```

Missing Context, wrong type, overwritten Context, repeated start, and factory exceptions fail safely with finally reset. `agent_model_required` is a RuntimeFault in the Adapter runner/lifecycle and retains its legacy code rather than becoming `adapter_factory_failed`. No enabled-path failure silently falls back to legacy.

Spies must prove that for_run/run receive the same runtime_emit and that Factory/PlatformTools/RuntimeEngine have no worker_emit path; model.delta, knowledge.retrieved, memory_search.completed, and extension events reach worker_emit exactly once only after public-stream retrieval, while forged run.*/tool.replay is rejected before worker_emit.

## 4. ReactAdapter Lifecycle, Structured Acknowledgment, and Terminal State Machine

### 4.1 Capabilities and Public Contract

Identity is fixed at `react/native/v1`; `streaming/cancellation/tool_calling/native_events=true` and the other seven unsupported capabilities=false. Each instance has one active execution and fully implements the existing five methods without adding public signatures or DTO fields.

The public AsyncIterator has no downstream acknowledgment, so the common suite alone cannot prove React's delivery after worker_emit. The React harness explicitly wraps the public stream: `event=await anext(raw_stream)`→record and `await worker_emit(event.event_type, event.payload)`→`await raw_stream.acknowledge(event)`; aclose/exceptions delegate to abort/aclose. Private-protocol tests use the raw stream directly. The five public methods remain unchanged.

LocalTest actually queues before claim, discards its queue at terminal, and settles delivery at `__anext__` yield; React must no longer claim that “no-consumer suppression is equivalent to LocalTest.” LocalTest does not implement AcknowledgingEventStream. When Orchestrator does not detect that protocol it still awaits worker_emit but performs no extra ack, explicitly retaining LocalTest's Adapter-internal `yield = delivery`.

### 4.2 Function-by-Function Reuse/Exclusion List for adapter_contract_suite.py

The React harness subclasses `AdapterContractSuite`, implementing controls with scripted RuntimeFactory/Runtime, a worker_emit spy, the acknowledgment wrapper, and manual clocks/gates; every reused streaming function goes through the explicit worker_emit/ack wrapper above. This complete frozen list replaces any generic “applicable cases” wording.

| Common test function | React decision and harness/private replacement |
|---|---|
| `test_capabilities_start_stream_collect_success` | **Exclude original**: hardcoded scenario usage/artifacts/engine_metadata do not fit React v1 without aggregation input. Private replacement retains identity, unchanged Request, Handle, repeated start, events, and completed assertions, but usage={}, artifacts=[], engine_metadata={}, using worker_emit/ack |
| `test_immediate_concurrent_and_repeated_collectors_share_result` | **Reuse original**: first collector on never-claimed explicitly selects no-stream suppression and releases the gate; shared shielded Result |
| `test_concurrent_second_consumer_and_claim_after_aclose_are_rejected` | **Reuse original**: synchronous single claim and closed re-claim rejection |
| `test_multiple_events_preserve_order_payload_and_empty_stream_terminates` | **Reuse original + ack wrapper**: verify order/payload and normal empty-stream completion after the first-emission handshake |
| `test_request_identity_mismatch_fails_before_handle` | **Reuse original**: identity errors fail safely before Handle |
| `test_prestart_errors_precede_handle_and_preserve_retryability` | **Exclude original**: React v1 has no LocalTest arbitrary prestart_error scenario. Private replacement covers real Request/Context/state preconditions; RuntimeFault is tested in runner under the matrix |
| `test_stream_errors_are_safe_for_stream_and_all_collectors` | **Reuse original**: harness injects runner/stream safe errors and verifies all collectors |
| `test_pre_chained_safe_stream_error_does_not_retain_raw_exception_chain` | **Reuse original**: preserve exception-chain sanitization |
| `test_unknown_exception_and_simulated_process_failure_are_distinct_and_safe` | **Exclude original**: external process failure is not part of React v1. Private replacement retains only unknown-exception safe internal_error/execution_error and makes no simulated_process_failure assertion |
| `test_manual_clock_timeout_wakes_collectors_without_real_waiting` | **Reuse original**: harness injects a manual scheduler/clock, maps outer execution_timeout/run_timeout, and uses no real waiting |
| `test_repeated_concurrent_cancel_closes_stream_and_collectors` | **Reuse original**: cancellation wakes first-emission gate, stream, and collectors |
| `test_cancel_wins_gate_race_and_suppresses_late_events_and_success` | **Reuse original**: Adapter first-terminal-wins and late-event/success suppression |
| `test_success_wins_gate_race_and_is_never_retroactively_cancelled` | **Reuse original**: cancel after completed never rewrites the Result |
| `test_duplicates_late_events_gaps_and_timestamps_follow_sequence_rules` | **Exclude original**: React generates local UUID/UTC/monotonic sequence from raw kind/data and accepts no LocalTest external seq/duplicate_of. Private replacement verifies distinct event_ids for duplicate raw events and contiguous local sequence, with no out-of-order input concept |
| `test_same_event_id_with_different_content_is_never_repaired` | **Exclude original**: runtime_emit accepts no external event_id and cannot construct same-ID different content. Private replacement verifies forged envelope fields are rejected/not interpreted and duplicate raw payloads never merge IDs |
| `test_terminal_visibility_never_precedes_queued_or_active_stream_events` | **Reuse original + ack wrapper**: Result follows all active-stream acknowledgments; immediate collect wins no-stream selection and post-terminal stream is empty |
| `test_early_aclose_cleans_owned_tasks_and_does_not_permit_replay` | **Reuse original + ack wrapper**: explicit worker_emit/ack for first event, aclose cleanup, and no replay |
| `test_one_cancelled_collector_does_not_cancel_shared_execution` | **Reuse original**: shared collectors are shielded |
| `test_lone_collector_cancellation_cleans_owned_work_before_propagation` | **Reuse original**: lone no-stream collector cancellation cleans up and re-raises |
| `test_deterministic_fresh_runs_have_no_cross_instance_high_water` | **Exclude original**: externally assigned [5,2] sequence does not fit React-local generation. Private replacement verifies each fresh Run starts at local sequence 1 and shares no event/result object or state |
| `test_pending_anext_is_woken_by_aclose_without_external_cancel` | **Reuse original**: aclose wakes pending anext and the first-emission gate |
| `test_claimed_empty_stream_does_not_block_successful_collection` | **Reuse original**: stream arrives first, and producer-finished plus undelivered=0 publishes Result without requiring the idle caller to aclose first |
| `test_delivered_only_event_does_not_require_an_extra_poll_before_result` | **Reuse original + ack wrapper**: no extra poll is needed before collect after worker_emit/ack |
| `test_invalid_handles_are_rejected_by_stream_collect_and_cancel` | **Reuse original**: Handle validation across relevant methods is unchanged |
| `test_raw_request_and_handle_values_fail_safely` | **Reuse original**: raw invalid objects fail safely without disclosure |

### 4.3 React-Private Stream States and First-Emission Handshake

Stream state is explicitly `never-claimed → claimed-active → closed`, with execution separately pending/terminal; never conflate these states with LocalTest internals.

1. **start**: Create runner and a closed first-emission gate. Before synchronous stream_events claim or explicit no-stream collector selection, runner may assemble/wait but the first runtime_emit cannot enter the React stream or reach worker_emit.
2. **Stream arrives first**: Before returning the iterator, stream_events atomically sets claimed-active and opens the gate; only then may runner emit, ensuring that start→immediate-stream loses no first event.
3. **Collect arrives first on never-claimed**: A lone or shared collector explicitly selects React-private **no-stream suppression**, atomically retaining never-claimed/no-stream mode and opening the gate. Events neither enqueue, block, nor reach worker_emit; a later stream is empty/ends under terminal semantics with no replay.
4. **Race**: First collect/stream selection linearizes under one state lock; normal Orchestrator always claims stream first, drains, then collects and does not depend on the race.
5. **Closed/terminal**: An active stream drains accepted acknowledged events before ending closed at terminal; aclose/cancel wakes the first-emission gate and put/get and cleans up, and a closed stream cannot be claimed again. First stream after never-claimed no-stream/cancel terminal is empty with no replay.

LocalTest retains its original pre-claim queueing, terminal discard, and yield=delivery semantics; the React rules above apply only to React's private implementation.

### 4.4 Core-Private AcknowledgingEventStream Protocol

Define a runtime-checkable structured Protocol/helper in `orchestration/execution_lifecycle.py` without importing concrete React:

```text
AcknowledgingEventStream(AsyncIterator[AgentEvent])
  async acknowledge(event)
  async abort(error)
  async aclose()
```

The helper performs `isinstance` protocol detection on a public `AsyncIterator[AgentEvent]` and returns private capability or None. Rules:

- Each execution has at most one in-flight event; ack must match both execution_id and event_id against that current in-flight event.
- Successful ack decrements undelivered exactly once and wakes producer; repeated acknowledgment of the same settled execution/event identity is idempotent without another decrement.
- Wrong execution/event identity, no in-flight event, out-of-order ack, or cross-execution ack is safe protocol_error and invokes abort cleanup; never guess, repair, or automatically acknowledge at bare yield.
- When Orchestrator detects React's private protocol, it acknowledges only after successful worker_emit; when absent, the fallback applies only to LocalTest yield=delivery and invents no ack.
- Ordinary worker_emit/stream exceptions use abort/aclose and publish failed Outcome; append/caller CancelledError uses abort/aclose and re-raises rather than mapping to ordinary execution_error.

### 4.5 Production, Backpressure, and Terminal Publication

Use Condition plus bounded deque under one state lock for stream state, producer finished, terminal published, queued/in-flight undelivered, settled ack identities, pending result, shielded terminal future, and runner.

1. Queue capacity is at least one and limits only queued buffer; one yielded unacknowledged in-flight event may also exist. A full active stream waits on Condition.
2. Pop/yield is not React delivery; Orchestrator takes the public event and awaits worker_emit, and only subsequent ack decrements undelivered. The test-side common streaming suite explicitly performs the same steps.
3. Normal runner completion stores pending result first and publishes the unique Result when producer is finished and queued+in-flight undelivered=0. An idle claimed but unclosed stream does not block collect, and terminal wakes the stream; active events cannot skip acknowledgment before Result.
4. Normal Orchestrator fully drains before collect and Worker finishes last, keeping Repository run.* terminal frames last.
5. Runner stream/protocol failure is safely raised to the consumer, treated as delivered to release waiters, and then publishes failed Result without hanging collectors.
6. cancel/aclose/ordinary emit failure atomically suppresses queued/late events, wakes put/get and the first-emission gate, cancels and drains runner, and suppresses late success.

### 4.6 Cancellation, Append/Finish, and Cleanup Matrix

| Trigger | Required behavior | Result |
|---|---|---|
| Explicit adapter.cancel | Adapter-internal first-terminal-wins; close stream, wake gate/put/get, cancel and drain runner, repeated cancel safe | If no terminal exists, cancelled Result with output=None/error=None; completed Result is never retroactively cancelled |
| Async-generator aclose | Same execution cleanup as explicit cancel, wakes first-emission gate, no runner leak | Converges under Adapter cancellation semantics; closed cannot replay |
| Ordinary stream/worker_emit/Notifier non-swallowed exception | abort/aclose and suppress later events/success | Safe failed Outcome with public internal_error and legacy execution_error, never cancelled |
| stale/cancelled/expired `worker_emit→Repository.append` | Repository raises `asyncio.CancelledError`; event is unacknowledged and not persisted, and Orchestrator/Adapter clean up and re-raise control flow | Never ordinary execution_error or an overwrite of the original terminal state; monitor/committed state determines Run |
| stale/terminal/wrong-owner/expired Repository.finish | Repository silently no-ops without committing output/history/hooks/terminal event | Preserve the first committed terminal state; never describe append as no-op |
| Specified PG/OS delta failure already swallowed by Notifier | Preserve best-effort behavior and acknowledge delta normally; other exceptions follow ordinary worker_emit failure | No durable delta or new error field |
| Caller CancelledError | Clean owned iterator/runner/tasks and re-raise | Worker monitor chooses cancelled or failed/worker_lost; lease loss is not user cancellation |
| Lone no-stream collector cancellation | Stop execution, wake gate, and clean up; shared collectors are shielded | Matches common collector contract |
| Non-cooperative runner | Outer timeout records cleanup failure/dangling risk and fails closed | Bounded drain only for cooperative coroutines; never claim forced termination |

Every owned task must ultimately be awaited/done. Persistence is not unconditionally cancellation-first: Runs use submission-order first-commit-wins; finish/reaper committing first makes cancel a no-op, while cancel committing first prevents late-finish overwrite. Reaper continues to produce cancelled-with-worker_lost/queue_timeout variants. Tests use Events/gates to control both orders, never sleep coincidence.

### 4.7 Core-Private Outcome Collection and LocalTest Fallback

`execution_lifecycle.py` additionally defines Core-private runtime-checkable `OutcomeCollectingAdapter`:

```text
OutcomeCollectingAdapter
  async collect_outcome(handle) -> ExecutionOutcome
```

The helper structurally inspects an Adapter and verifies that `collect_outcome` is a genuinely async callable. Descriptor-access exceptions, synchronous functions, async-looking return values, and malformed capabilities all fail closed as protocol-free without invoking the capability. The Protocol/helper imports no React and joins neither Phase 1 `AgentEngineAdapter`, public contracts, nor public serialization.

ReactAdapter-private `collect_outcome` and public `collect_result` share one internal terminal-collection implementation: Handle validation, stream-first/no-stream selection, collector counting, shielded futures, lone/shared collector cancellation, and cleanup are identical. At terminal it returns the same Outcome already published inside the Adapter rather than rebuilding one or guessing a legacy code. Orchestrator calls `collect_outcome` exactly once when it detects this protocol on React, never calls `collect_result` before a supplementary private collection, and never accesses `_execution`. Completed retains real history/dropped, failed retains the original RuntimeFault legacy code including future unknown codes, and cancelled has no code; none of these private values enters public Result or engine_metadata.

LocalTest does not implement this private protocol. Only when detection finds no protocol does Orchestrator call public `collect_result` and explicitly convert it using the table below. For failed Results, `ExecutionOutcome.from_result` still requires an explicit legacy code and gains no inference from message/details/Provider text or unknown fields.

| Protocol-free LocalTest public Result | Private Outcome |
|---|---|
| completed | `history=[]`, `dropped=[]`, retaining safe public output/usage and related values |
| failed with public error code `execution_timeout` | failed with `legacy_error_code="run_timeout"` |
| failed with any other public error code, including internal/protocol/simulated process failures | failed with `legacy_error_code="execution_error"` |
| cancelled | cancelled with no error/code |

This lossy compatibility fallback exists only for protocol-free LocalTest; React must never lose its original code through this path. If an Adapter exposes the private protocol, collection failure must not silently downgrade to public collection. Worker finishes only after drain→collect completes, preserving unique terminal state and run.* terminal-frame ordering.

## 5. Event Mapping, Dual-Emit Spies, and SSE Ownership

| Source | React internal handling | Final destination |
|---|---|---|
| Every valid ordinary business event (model/tool, knowledge.retrieved, memory_search.completed, extension events) | runtime_emit converts original name/same JSON payload to AgentEvent; after public-stream retrieval Orchestrator restores it, awaits worker_emit, then acknowledges on success; no allowlist | Existing worker_emit chooses Repository.append or Notifier exactly once per event |
| model.delta | Uses the same dual-emit/ack boundary and never calls Notifier directly in runtime_emit | worker_emit→Notifier best-effort with no DB sequence/replay |
| Raw Adapter run.* | Safe protocol_error before worker_emit | run.* only from Repository.submit/claim/cancel/finish/reap |
| Raw Adapter tool.replay | Safe protocol_error before worker_emit | tool.replay only from DurableToolReplayCache |
| Internal AgentEvent/Outcome/Context/emit callbacks | Never enter public payload | Internal/Open SSE schemas and field filtering remain unchanged |

Spy tests separately record runtime_emit, public yield, worker_emit, Repository/Notifier, and acknowledgment ordering; cover model.delta, knowledge.retrieved, memory_search.completed, extension events, and forged run.*/tool.replay, asserting that no Factory/PlatformTools/RuntimeEngine event can bypass the public stream and reach worker_emit directly.

Internal/Open SSE cursor validation retains the following R15 matrix for the existing routes. Never change the internal manually parsed header response from 400 to 422 or the Open typed-validation response from 422 to 400:

| API and parameter | Validation mechanism | Invalid, type, or range error | Existing response |
|---|---|---|---|
| Internal `Last-Event-ID` | Handler manually parses the header | Value that cannot be parsed as an integer or is otherwise invalid, or outside `[0,2147483647]` | `400 / invalid_last_event_id` |
| Internal `after` | FastAPI typed Query | Type error or outside `[0,2147483647]` | `422` |
| Open `after` | FastAPI typed Query | Type error or outside `[0,2147483647]` | `422` |
| Open `Last-Event-ID` | FastAPI typed Header | Type error or outside `[0,2147483647]` | `422` |
| Valid internal/Open cursors | Compute effective after with `max(after,last_id)` | None; absent cursors retain existing defaults | Replay strictly only `seq>after`, never repeating the boundary event |

Phase 2 changes none of these routes, schemas, status codes, or error bodies. Internal/Open SSE continues to preserve draining beyond 200 events, no-ID delta non-replay, hidden tool.replay payload with cursor advancement, terminal position, and public-field filtering. AgentEvent.sequence is Adapter-local only and never replaces DB event_seq/SSE id. P2-IT-05/06 in 04 must verify this matrix through the actual ASGI/FastAPI routes; helper unit tests cannot substitute for route evidence.

## 6. Errors, Usage, and Terminal Mapping

### 6.1 Complete Phase 0 Source Error Matrix

The following covers the Engine/Factory/Gateway/Domain inventory in Phase 0 `baseline/run-lifecycle-events.md:38–52`. Private Outcome/Run legacy_error_code always retains the original RuntimeFault code, while public output uses only the safe catalog and never copies Provider/Domain text.

| Original RuntimeFault/condition | Public category/code | Private legacy_error_code / Run result |
|---|---|---|
| agent_model_required, configuration_changed | configuration_error / invalid_request | failed / original code; agent_model_required never becomes adapter_factory_failed |
| model_resource_not_found, model_resource_disabled, model_profile_version_not_found | configuration_error / invalid_request | failed / each original code |
| model_input_too_large | resource_exhausted / resource_exhausted | failed / model_input_too_large |
| model_tools_not_supported | configuration_error / invalid_request | failed / model_tools_not_supported |
| invalid_model_response, empty_model_response, duplicate_tool_call_id, repeated_tool_call | protocol_error / protocol_error | failed / each original code |
| model_round_limit, tool_call_limit, model_output_too_large | resource_exhausted / resource_exhausted | failed / each original code |
| model_provider_unavailable, model_rate_limited, model_provider_rejected, model_transport_error | engine_unavailable / engine_unavailable | failed / each original code; no new Worker automatic retry |
| content_blocked_input, content_blocked_output | permission_denied / permission_denied | failed / each original code |
| gateway_concurrency_exceeded, gateway_request_quota_exceeded | resource_exhausted / resource_exhausted | failed / each original code |
| model_credential_unavailable | authentication_error / authentication_failed | failed / model_credential_unavailable |
| model_response_too_large | resource_exhausted / resource_exhausted | failed / model_response_too_large |
| model_stream_interrupted | engine_unavailable / engine_unavailable | failed / model_stream_interrupted |
| model_timeout | timeout / execution_timeout | failed / model_timeout |
| Outer TimeoutError from RuntimeEngine.run | timeout / execution_timeout | failed / run_timeout |
| Any future/unrecognized RuntimeFault(code) | internal_error / internal_error safe fallback | failed / **original code retained verbatim**, never discarded because the public enum is unknown |
| Unknown ordinary Exception or ordinary stream/worker_emit failure | internal_error / internal_error | failed / execution_error |
| Adapter reserved run.*/tool.replay, malformed event, or ack identity/order error | protocol_error / protocol_error | failed / execution_error (or retain an explicit existing legacy code) |
| Explicit Adapter cancel | No ExecutionError | cancelled / no error or output |
| heartbeat lost | Worker-side safe internal/worker_lost semantics | failed / worker_lost; reaper may produce cancelled-with-worker_lost |

`model_stream_not_supported` currently falls back in GatewayChatModel rather than directly raising RuntimeFault; if a future call site raises it, retain the original code plus safe public mapping/fallback rather than silently dropping it. CancelledError from stale/cancelled/expired append is control flow and does not enter the ordinary-exception mapping above.

### 6.2 Usage and Private Completion Values

- `ExecutionResult.usage` and Outcome usage are non-optional and never None. React v1's current `RuntimeEngine.run()` returns only `(output, history, dropped)` and provides no aggregate usage input, so both public Result and private Outcome usage are `{}`; this is neither “reuse of an existing Runtime aggregate” nor fabricated `prompt_tokens=0` or other zero values.
- Preserve usage in `model.completed` verbatim, including unknown but valid extension fields; never derive a new Result usage aggregation from that event.
- output/history/dropped are explicit private Outcome fields; failed/cancelled execution does not return history/dropped to Memory completion hooks.
- Add no HTTP/SSE fields through engine_metadata, Outcome, Context, or emit callbacks, and never log secrets, raw exceptions, or nil Agent identity.

## 7. Old/New Path Parity Rules

### 7.1 Serial Deterministic Scripts

With identical model/tool scripts, compare output, error, usage, history/dropped on success, stable payloads, event order, per-Run contiguous DB sequence, terminal position, and strict replay from every cursor. Valid business event names and payloads must not be rewritten by the Adapter.

### 7.2 Parallel Tools and Model Rounds

- Align tool.started/tool.completed by call_id; require equal sets, local started→completed partial order for each call_id, and identical model-round boundaries.
- Independent parallel branches need not have identical global ordering or absolute sequence numbers across paths; each Run's own sequence remains contiguous and terminal last.
- Business events in parallel regions without an attributable call_id are compared as per-model-round multisets rather than forced global order.

### 7.3 Only These Explicit Paths May Be Canonicalized

| Scope | Canonicalizable fields |
|---|---|
| DTO | event_id, timestamp, Run-instance/timing identifiers |
| model.completed payload | gateway_call_id, first_token_ms, duration_ms |
| tool.completed payload | gateway_call_id, duration_ms |

Validate original field type, nullability, and nonnegative duration before canonicalization. Never normalize call_id, business document/chunk IDs, tool arguments/results, output, error_code, or usage, and never globally remove IDs. Raw latency is independent performance evidence and cannot be omitted merely because canonical diff is empty.

## 8. Configuration, Composition, Rollout, and Rollback

`Settings.execution_orchestrator_enabled=False`, overridden by `AGENT_EXECUTION_ORCHESTRATOR_ENABLED`. Default off; read at process startup and applied by rolling restart, never request-hot-switched. Exclude this flag from the runtime-composition fingerprint so off API/on Worker and mixed Workers do not report configuration_changed.

The shared composition root registers EngineDescriptor(react), ProtocolDescriptor(native), AdapterDescriptor(react/native/v1), builds the same Orchestrator, and optionally injects it into Worker. The production selector fixes a trusted tuple and accepts no request override. LocalTest uses only a separate Registry/selector while sharing Orchestrator/Worker and has no private ack protocol.

Rollout order: merge default-off and complete CI/dedicated-environment parity evidence→enable small Worker groups→observe low-cardinality metrics, safe logs, SSE, terminal states, and raw latency→expand gradually. Record that existing queued/running/terminal rows remain readable, mixed claims never share rows, running in-flight work converges under existing cancellation/Lease rules, and terminal rows are never rewritten. On anomalies, set every process off and rolling-restart; no Alembic downgrade, data repair, or client change is needed.

> Revised (2026-11-12, R17): during T11 quickstart live validation, an explicit-on published Run completed with no error_code, but the container emitted no `path=orchestrator` log. The Worker logger emits INFO, which root WARNING filtered. The controlled path log is an acceptance and runtime-observability contract; its absence is a deployment defect and cannot be closed merely because unit-test caplog sees the event.
>
> The quickstart supervisor API command loads a dedicated YAML through `--log-config /app/deploy/uvicorn-logging.yaml`, and the quickstart image copies that file into `/app/deploy/`. The configuration gives only `agent_platform.core_platform.agent_runtime.worker` an INFO level, dedicated stdout handler, and `propagate: false`, with `disable_existing_loggers: false`; root remains WARNING, the default uvicorn/access INFO handlers are preserved verbatim, and other existing loggers are neither disabled nor made more verbose. Worker retains `logger.info`, performs no import-time logging configuration, does not change the event to warning, and adds no secret, raw exception, input/config/history, private row, or other sensitive field; the off path still emits no orchestrator log. Focused tests must load the actual uvicorn configuration and verify Worker INFO visibility, root WARNING, preservation of existing loggers, and entry-point wiring. T11 must still rebuild quickstart and revalidate real on/off Runs; unit tests are not live evidence.

> Revised (2026-11-12, R18): final cross-phase review found that a normal Outcome logged completed/failed before `repository.finish`. If finish raised an ordinary exception, the existing exception handler logged failed again and retried finish, producing contradictory completed+failed records. Controlled terminal INFO for a normal Outcome must move after its corresponding `repository.finish` returns successfully. If finish raises, no normal-Outcome record may precede it; only the existing exception path records one failed event. Repository remains the sole terminal writer, and first-commit-wins, stale/no-op, Memory, off legacy, and exception/cancellation control flow remain unchanged.
>
> R18 permits only focused changes to `backend/src/agent_platform/core_platform/agent_runtime/worker.py` and `backend/tests/test_runtime_baseline.py`. Fault injection must make the first completed finish raise an ordinary exception for a completed Outcome, then let the subsequent failed finish succeed, asserting `finish_statuses=['completed','failed']`, exactly one failed log, and no completed log. A separate check asserts that normal logging occurs only after successful finish returns. With final code, T11 minimally rebuilds and revalidates one on Run plus off rollback: on has exactly one log consistent with the actual terminal state and off has no orchestrator log. This task does not rebuild quickstart itself.

## 9. Testing, Performance Evidence, Reports, and Post-Acceptance Seed

See 04 for cases, 05 for acceptance, and 08 for task order. T8 creates bilingual 06 only after executing every test row; T9 creates bilingual 07 only after executing every acceptance row. Neither may prewrite passage.

Functional exit and performance submetrics are separate: every P2 functional UT/IT/CM must pass, and P2-CM-08 evidence-integrity/measurement-boundary checks may independently pass; without a real external model/tool environment, only the performance submetric is `pending_env`, and test doubles cannot establish production performance. T9 is then capped at conditionally passed, never fully passed. The performance method is fixed in 05 section 4: same environment and scripts, at least 30 matched pairs, five warm-up pairs excluded, nearest-rank p95, and explicit raw-overhead/external-model-latency boundaries.

The user explicitly requires new example seed data **only after development, testing, and formal acceptance are complete**. T10 adds Phase 2-specific, idempotent, low-sensitivity, recognizably namespaced data using existing schema/API/published snapshots, with no Engine field, migration, UI, or fabricated Agent ID; it covers published-snapshot and no-snapshot legacy base-runtime scenarios under off/on. T11 validates quickstart default-off, explicit-on, embedded Worker, internal/Open SSE, path logs, and off rollback with no new service. Append actual outcomes as post-acceptance-validation appendices to existing 06/07 without rewriting earlier evidence; failures reopen defects and affected acceptance items.
