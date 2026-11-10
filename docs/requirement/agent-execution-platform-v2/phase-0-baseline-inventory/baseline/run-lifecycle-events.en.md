# Phase 0 Baseline · Run Lifecycle, Events, and SSE

> Baseline commit: `c6c47dec39025ebd4d1176c1e9925bac9c99c4fd`
> Inventory date: 2026-11-07; review revision: 2026-11-08
> Source of conclusions: static paths at the target commit; repeatable dynamic assertions are identified by actual nodes in `06-test-report.md`

## 1. States and Ownership

The only durable states are `queued`, `running`, `completed`, `failed`, and `cancelled`, enforced by both the core schema and database constraint (`backend/src/agent_platform/core_platform/agent_runtime/schemas.py:7-8`, `backend/migrations/versions/0001_runtime.py:23-44`).

- `queued`: no execution owner yet; `queue_expires_at` determines claim eligibility (`backend/src/agent_platform/core_platform/agent_runtime/repository.py:55-149,203-251`).
- A successful claim creates `running` with an owner and lease. **A currently valid owner/lease is required for heartbeat and ordinary append/finish; it is not an invariant that the stored state must satisfy at every instant.** The lease can expire while status remains running until Worker/reaper resolution (`backend/src/agent_platform/core_platform/agent_runtime/repository.py:203-281,297-317,368-391`).
- Terminal states set `finished_at`; ordinary completion clears the lease, and ordinary late finish cannot overwrite them (`backend/src/agent_platform/core_platform/agent_runtime/repository.py:283-325`).
- `cancel_requested` is a flag, not a sixth state. A running Run can remain running briefly after cancellation is requested until Worker/Repository coordination reaches cancelled (`backend/src/agent_platform/core_platform/agent_runtime/repository.py:327-366`).

## 2. Reachable Transitions

| Start/trigger | Actual result and fields | Evidence |
|---|---|---|
| New submission | Atomically writes queued, the user message, and `run.queued`; sets queue deadline | `backend/src/agent_platform/core_platform/agent_runtime/repository.py:55-149` |
| queued + successful claim | running; sets owner/started_at/lease_until and writes `run.started`; same tenant, unexpired, `FOR UPDATE SKIP LOCKED` | `backend/src/agent_platform/core_platform/agent_runtime/repository.py:203-251` |
| running + normal Engine return | completed; writes output/history, null error, clears lease; success hooks and `run.completed` share one transaction | `backend/src/agent_platform/core_platform/agent_runtime/worker.py:91-99`, `backend/src/agent_platform/core_platform/agent_runtime/repository.py:283-325` |
| running + `RuntimeFault` | failed with `error_code=exc.code` | `backend/src/agent_platform/core_platform/agent_runtime/worker.py:109-110` |
| running + outer execution timeout | failed/`run_timeout`; a per-model timeout is separately `model_timeout` | `backend/src/agent_platform/core_platform/agent_runtime/worker.py:111-112`, `backend/src/agent_platform/core_platform/agent_runtime/engine.py:57-65,183-196` |
| running + generic exception | failed/`execution_error`; logs contain only the Run ID, not raw provider exception text | `backend/src/agent_platform/core_platform/agent_runtime/worker.py:113-116` |
| queued + cancel | cancel flag=true, immediately cancelled/finished_at, `run.cancelled` data is `{}` | `backend/src/agent_platform/core_platform/agent_runtime/repository.py:327-366` |
| running + cancel | Writes cancel flag and `run.cancel_requested` while still running; later finish forces cancelled, clears output/error, and skips success hooks | `backend/src/agent_platform/core_platform/agent_runtime/repository.py:309-325,352-365` |
| Cancellation observed during execution | Heartbeat returns cancel and monitor cancels execution; the `CancelledError` path attempts cancelled | `backend/src/agent_platform/core_platform/agent_runtime/repository.py:272-281`, `backend/src/agent_platform/core_platform/agent_runtime/worker.py:56-69,100-108` |
| Worker stop | serve cancels execution; with valid owner/lease, the same `CancelledError` path can write cancelled even without an API cancel flag | `backend/src/agent_platform/core_platform/agent_runtime/worker.py:100-108,186-192` |
| Heartbeat lease loss/database failure | Monitor fails closed, cancels execution, and attempts failed/`worker_lost`; finish itself rejects expired lease/wrong owner | `backend/src/agent_platform/core_platform/agent_runtime/worker.py:56-69,100-108`, `backend/src/agent_platform/core_platform/agent_runtime/repository.py:297-317` |
| Expired running lease + reaper | Normally failed/`worker_lost`; if cancellation was already requested, cancelled retaining `error_code=worker_lost` | `backend/src/agent_platform/core_platform/agent_runtime/repository.py:368-391` |
| Expired queued deadline + reaper | Normally failed/`queue_timeout`; if the cancel flag is already present, cancelled retaining `error_code=queue_timeout` | `backend/src/agent_platform/core_platform/agent_runtime/repository.py:368-391` |
| Human handoff | queued becomes cancelled with reason=`human_handoff`; running gets the flag and reason-bearing cancel_requested | `backend/src/agent_platform/business_capabilities/human_handoff/service.py:125-153` |
| Any terminal + cancel | No update or new event; returns the current terminal state | `backend/src/agent_platform/core_platform/agent_runtime/repository.py:350-366` |
| Terminal/wrong owner/expired lease + ordinary finish | Silent no-op; no output/history/hooks/terminal event commits | `backend/src/agent_platform/core_platform/agent_runtime/repository.py:283-325` |
| Non-running/wrong owner/cancelled/expired + ordinary append | Raises `asyncio.CancelledError` before writing | `backend/src/agent_platform/core_platform/agent_runtime/repository.py:253-270` |

### 2.1 RuntimeFault Sources Extend Beyond Engine Literal Raises

Current literal Worker, Engine, and Factory paths include `configuration_changed`, `agent_model_required`, `model_round_limit`, `model_timeout`, `invalid_model_response`, `duplicate_tool_call_id`, `tool_call_limit`, `empty_model_response`, `model_output_too_large`, and `repeated_tool_call` (`backend/src/agent_platform/core_platform/agent_runtime/worker.py:109-110`, `backend/src/agent_platform/core_platform/agent_runtime/engine.py:31-115`, `backend/src/agent_platform/applications/platform_runtime/runtime_factory.py:103-114`).

Production Runs with snapshots use GatewayChatModel, which converts caught DomainError to `RuntimeFault(exc.code)`; only `model_stream_not_supported` falls back instead of being raised directly (`backend/src/agent_platform/applications/platform_runtime/runtime_factory.py:97-114`, `backend/src/agent_platform/core_platform/platform_services/model_gateway/gateway.py:551-604`). Additional currently chat-reachable error sources include at least:

- Resource/version: `model_resource_not_found`, `model_resource_disabled`, `model_profile_version_not_found` (`backend/src/agent_platform/core_platform/platform_services/model_gateway/catalog.py:103-115,306-318`).
- Input/capability: `model_input_too_large`, `model_tools_not_supported` (`backend/src/agent_platform/core_platform/platform_services/model_gateway/gateway.py:137-147`).
- Provider/transport: `model_provider_unavailable`, `model_rate_limited`, `model_provider_rejected`, `model_transport_error` (`backend/src/agent_platform/core_platform/platform_services/model_gateway/gateway.py:353-366,480-489`).
- Content governance: `content_blocked_input`, `content_blocked_output` (`backend/src/agent_platform/core_platform/platform_services/model_gateway/gateway.py:386-397`).
- Gateway governance: `gateway_concurrency_exceeded`, `gateway_request_quota_exceeded` (`backend/src/agent_platform/core_platform/platform_services/model_gateway/governance.py:369-393`).
- Credential resolution: `model_credential_unavailable` is raised when the referenced environment variable has no value; the Gateway resolves credentials at call time (`backend/src/agent_platform/core_platform/platform_services/model_gateway/catalog.py:83-90`, `backend/src/agent_platform/core_platform/platform_services/model_gateway/gateway.py:425-435`).
- Response/stream adapters: `model_response_too_large` is raised when bounded non-streaming or streaming responses exceed their limit; `model_stream_interrupted` is raised when a stream ends without `[DONE]` (`backend/src/agent_platform/core_platform/platform_services/model_gateway/adapters.py:115-123,281-307,350-353`).

This baseline categorizes current call sites; it is not a closed enum forbidding future DomainErrors. Later contracts must preserve stable original-code classification and sanitization boundaries.

## 3. Race and Cleanup Baseline

- **Cancellation does not unconditionally beat queue timeout.** If queued cancel commits first, reaper no longer selects the row; if reaper commits failed first, later cancel is a terminal no-op; if the cancel flag is already visible to reaper, the outcome is cancelled-with-`queue_timeout` (`backend/src/agent_platform/core_platform/agent_runtime/repository.py:327-391`).
- **Ordinary append and heartbeat are execution-time guards.** Transient `model.delta` deliberately bypasses both and can arrive best-effort around cancellation/terminal transitions without durable ordering guarantees (`backend/src/agent_platform/core_platform/agent_runtime/worker.py:48-69`, `backend/src/agent_platform/core_platform/agent_runtime/repository.py:253-281`).
- `_execute.finally` cancels and gathers watcher and execution; serve shutdown cancels and gathers dispatcher tasks (`backend/src/agent_platform/core_platform/agent_runtime/worker.py:117-123,186-192`).
- Worker reaps/claims only its configured tenant, limits claims by `worker_concurrency`, listens on `runtime_queue` NOTIFY, and polls every 0.5 seconds as fallback (`backend/src/agent_platform/core_platform/agent_runtime/worker.py:145-185`).
- Event interleaving across parallel tools is scheduling-dependent. Started precedes completed for the same tool, but no fixed global order across different call_ids is contractual (`backend/src/agent_platform/core_platform/agent_runtime/engine.py:107-145`).

## 4. Durable and Transient Events

Ordinary `_event` atomically increments `runtime_runs.event_seq`, inserts `(run_id, seq, type, data)`, and sends a durable-pointer NOTIFY; `run.queued` also notifies the Worker queue (`backend/src/agent_platform/core_platform/agent_runtime/repository.py:30-53`). The event primary key is `(run_id, seq)`. Sequence starts at 1 per Run and is not global (`backend/migrations/versions/0001_runtime.py:47-55`).

| Event/write path | Durable data shape |
|---|---|
| `run.queued`, `run.started` | `{}` (`backend/src/agent_platform/core_platform/agent_runtime/repository.py:143-145,243-244`) |
| `run.cancel_requested` | `{}` from Repository; `{"reason":"human_handoff"}` from handoff (`backend/src/agent_platform/core_platform/agent_runtime/repository.py:352-365`, `backend/src/agent_platform/business_capabilities/human_handoff/service.py:145-153`) |
| Ordinary-finish `run.completed`, `run.failed` | Both keys: `{"output": output_or_null, "error_code": error_or_null}` (`backend/src/agent_platform/core_platform/agent_runtime/repository.py:313-325`) |
| Reaper `run.failed`, `run.cancelled` | **Only** `error_code`, with no `output` key; the error is `queue_timeout` or `worker_lost` (`backend/src/agent_platform/core_platform/agent_runtime/repository.py:383-391`) |
| Other `run.cancelled` | `{}` for queued cancel; `{"reason":"human_handoff"}` for handoff; `{"output":null,"error_code":null}` for Worker finish (`backend/src/agent_platform/core_platform/agent_runtime/repository.py:323-325,357-365`, `backend/src/agent_platform/business_capabilities/human_handoff/service.py:125-145`) |
| `model.started` | `{"round": round_no}` (`backend/src/agent_platform/core_platform/agent_runtime/engine.py:31-38`) |
| `model.completed` | `round`, `tool_calls`, `usage`, `gateway_call_id`, `first_token_ms`, `duration_ms` (`backend/src/agent_platform/core_platform/agent_runtime/engine.py:85-97`) |
| `tool.started` | `name` and model tool `call_id` (`backend/src/agent_platform/core_platform/agent_runtime/engine.py:117-120`) |
| `tool.completed` | `name`, `call_id`, `ok`, `error`, `gateway_call_id`, `execution_status`, `tool_version`, `duration_ms` (`backend/src/agent_platform/core_platform/agent_runtime/engine.py:121-133`) |
| `summary.queued` | `{"dropped": count}` (`backend/src/agent_platform/applications/platform_runtime/runtime_hooks.py:74-84`) |
| `memory_extract.queued` | `{"customer_id": string}` (`backend/src/agent_platform/applications/platform_runtime/runtime_hooks.py:85-106`) |
| `memory.injected` | `items`, `flags`, `events`, `item_ids`; details separately store item id/section/score (`backend/src/agent_platform/business_capabilities/memory/injection.py:90-107`, `backend/src/agent_platform/applications/platform_runtime/runtime_hooks.py:109-134`) |
| `knowledge.retrieved` | `sources` with document id/title/version/chunk id (`backend/src/agent_platform/business_capabilities/knowledge/tools.py:61-76`) |
| `memory_search.completed` | `mode`, `hits`, `returned` (`backend/src/agent_platform/business_capabilities/memory/tools.py:99-106`) |
| `tool.replay` | `idempotency_key` and full tool `result`; an internal durable replay cache (`backend/src/agent_platform/core_platform/tool_gateway/replay.py:80-119`) |

Trusted/external tool contributions also receive raw `emit`, so business extension event names are not a closed enum (`backend/src/agent_platform/core_platform/platform_services/integrations/business_tools/platform_tools.py:26-47`). A later common envelope must not assume that only the table above exists.

### 4.1 `model.delta`

- Engine data contains `round` plus optional `text`/`reasoning`, excluding partial tool JSON (`backend/src/agent_platform/core_platform/agent_runtime/engine.py:43-55`).
- Worker converts it to notifier payload `{"k":"delta", ...data}` and returns without Repository append (`backend/src/agent_platform/core_platform/agent_runtime/worker.py:48-54`).
- Deltas have no database seq and cannot be replayed with after. Notifier failure drops deltas/reconnects without blocking durable events (`backend/src/agent_platform/core_platform/agent_runtime/notify.py:32-57`).
- Public SSE additionally has transient id-less `accepted` and midstream-authorization-failure `error` events (`backend/src/agent_platform/business_capabilities/open_platform/routes.py:324-336,366-370`).

### 4.2 Special `tool.replay` Boundary

`DurableToolReplayCache.put` increments event_seq and inserts `tool.replay` itself. It does not use `_event`, check Run status/owner/lease/cancellation, or send NOTIFY (`backend/src/agent_platform/core_platform/tool_gateway/replay.py:80-119`). A concurrent/direct invocation can therefore consume a sequence after terminal state. Both SSE implementations hide its payload while advancing the cursor (`backend/src/agent_platform/applications/customer_service/runtime_routes.py:115-121`, `backend/src/agent_platform/business_capabilities/open_platform/routes.py:371-390`). **This does not mean ordinary execution events may be written after terminal state, and ordinary append tests cannot substitute for this specialized-path test.**

## 5. SSE Replay and Field Exposure

### 5.1 Internal SSE

- Query `after` and `Last-Event-ID` combine as `max(after,last_id)`; malformed/out-of-range headers return 400 (`backend/src/agent_platform/applications/customer_service/runtime_routes.py:83-121`).
- Repository reads strict `seq > after`, ordered by seq, at most 200 rows per page (`backend/src/agent_platform/core_platform/agent_runtime/repository.py:175-201`).
- Output contains `id: seq`, `event: type`, and full JSON data; transient deltas have no id and do not advance the cursor (`backend/src/agent_platform/applications/customer_service/runtime_routes.py:115-145`).
- The stream ends only when the Run is terminal and the cursor reaches current event_seq. A full 200-event page drains immediately before waiting; a heartbeat comment follows 15 seconds without notification (`backend/src/agent_platform/applications/customer_service/runtime_routes.py:122-148`).

### 5.2 Public SSE

- Uses the same strict-after/max and terminal-drain rules, emits accepted first, polls every 0.5 seconds, and sends heartbeat on fixed ticks (`backend/src/agent_platform/business_capabilities/open_platform/routes.py:324-399,454-465`).
- Deltas expose only truthy visible text, not reasoning (`backend/src/agent_platform/business_capabilities/open_platform/routes.py:337-361`).
- Durable data is reduced to `run_id`; model events add only round/tool-call counts, and terminal events merge the full public RunView. Tool inputs, retrieval sources, usage, gateway ids, memory details, and replay payloads are not exposed (`backend/src/agent_platform/business_capabilities/open_platform/routes.py:371-390`).

## 6. Assertions Later Phases Must Preserve

1. Do not duplicate or bypass the five durable states, cancellation flag, or terminal protection with new Engine states.
2. Do not idealize `execution_error`, `run_timeout`, Engine/Factory/Model-Gateway RuntimeFault codes, or reaper cancellation variants into one error shape.
3. Preserve ordinary durable sequence/state transactions, strict-greater-than replay, terminal draining, and 200-event pagination.
4. Transient deltas never enter the durable cursor; public SSE never exposes reasoning, tool inputs, usage, gateway/memory/replay details.
5. Test ordinary append/finish separately from `tool.replay`. Any security fix requires its own requirement and small commit with explicit behavior-change evidence; Phase 0 baseline tests must not change it silently.
