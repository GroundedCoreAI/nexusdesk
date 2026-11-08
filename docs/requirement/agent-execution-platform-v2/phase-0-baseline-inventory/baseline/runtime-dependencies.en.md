# Phase 0 Baseline · Runtime Execution Dependencies and Interfaces

> Baseline commit: `c6c47dec39025ebd4d1176c1e9925bac9c99c4fd`
> Inventory date: 2026-11-07; review revision: 2026-11-08
> Evidence scope: static code and existing tests at the target commit; added regression nodes and double-run results are in `06-test-report.md`
> Migration boundary: target head is `0057_industry_pack_runtime`; Phase 0 adds and modifies no migration

## 1. Entry Points and Public Contracts

| Entry point | Current path | Key behavior |
|---|---|---|
| Internal Runtime API | `backend/src/agent_platform/applications/customer_service/runtime_routes.py:40-89` | Mounted at `/api/v1`; Run submit/get/cancel and event SSE; submission passes through `RuntimeAdmission.submit` |
| Open platform and public SSE | `backend/src/agent_platform/business_capabilities/open_platform/routes.py:256-260,408-465`, `backend/src/agent_platform/business_capabilities/open_platform/service.py:377-439` | Mounted at `/openapi/v1`; application/session authorization and idempotency precede the same Run persistence path |
| Customer-service ingress | `backend/src/agent_platform/business_capabilities/customer_service/service.py:243-276` | Can submit a published Agent snapshot through the same Repository |
| Worker | `backend/src/agent_platform/applications/application_factory.py:76-132`, `backend/src/agent_platform/applications/worker/__main__.py:7-19` | Lifespan controls the embedded Worker; the standalone Worker calls the same `serve()` |

Three input/port surfaces exist and must not be conflated:

1. The **internal Run API** directly accepts the core `RunRequest` in `backend/src/agent_platform/core_platform/agent_runtime/schemas.py:7-26`. It has an external string `conversation_id`, a maximum 8,000-character `message`, and `extra="forbid"`; `RunView` does not expose owner, lease, config, history, or event sequence.
2. **Open-platform submission** accepts `MessageInput`: `message`, `stream`, and `wait_seconds` (default 30, range 0–30), with the conversation UUID in the URL path and a required `Idempotency-Key` header of length 1–128 (`backend/src/agent_platform/business_capabilities/open_platform/routes.py:256-260,408-428`). Only after application/session resolution does the service construct the internal core `RunRequest` (`backend/src/agent_platform/business_capabilities/open_platform/service.py:418-426`); public queries/terminal views reuse `RunView` where applicable.
3. `backend/src/agent_platform/extension_contracts/runtime.py:21-55,203-213` separately declares capability-neutral `RunRequest`/`RunSnapshot`/`RunEvent`/`RunPort`, with tenant, UUID conversation, `input`, config, idempotency key, and an event field named `sequence`. At the target commit this port is not wired into HTTP execution; its fields and limits are not either current HTTP contract.

## 2. Core Internal Interfaces

| Component | Interface and evidence | Current responsibility |
|---|---|---|
| Admission | `backend/src/agent_platform/core_platform/agent_runtime/admission.py:17-67` | Resolve conversation and Agent snapshot, enforce capacity/one-active-conversation rules, submit a queued Run |
| Repository | `backend/src/agent_platform/core_platform/agent_runtime/repository.py:23-65,151-203,203-285,327-391` | `submit/get/events/claim/append/heartbeat/finish/cancel/reap`; owns state and durable-event transactions |
| Worker | `backend/src/agent_platform/core_platform/agent_runtime/worker.py:16-54,145-195` | One owner UUID per Worker; exclusive claim, heartbeat monitoring, execution, cancellation, and cleanup |
| Factory | `backend/src/agent_platform/applications/platform_runtime/runtime_factory.py:20-127` | `effective(snapshot)` computes settings; `for_run(row, emit)` builds the Runtime for each snapshotted Run |
| Engine | `backend/src/agent_platform/core_platform/agent_runtime/engine.py:20-29,147-221` | Two-node LangGraph ReAct; `run()` returns `(output, final_history, dropped)` |
| Bindings | `backend/src/agent_platform/applications/platform_runtime/service_groups.py:121-141` | Aggregates Engine/settings/snapshot, tool/policy/retrieval/customer/memory/gateway/ledger/replay/events and other process resources |
| Memory ports | `backend/src/agent_platform/extension_contracts/runtime.py:151-200`, `backend/src/agent_platform/core_platform/agent_runtime/hooks.py:18-35` | Actively used memory-injection and persistence-hook boundaries |

The target Git tree has no second Runtime implementation under `backend/src/agent_platform/modules/`; ignored local `__pycache__` is not baseline source or evidence of another architecture module.

## 3. Construction-Time and Per-Run Dependencies

### 3.1 Process composition

`runtime_services()` is the composition root:

1. Read public tool specifications and compute a fingerprint, explicitly excluding credentials and selected Worker/database settings; create the SQL engine, LISTEN/NOTIFY listener, and notifier (`backend/src/agent_platform/applications/platform_runtime/runtime_composition.py:94-141`).
2. Create shared tool/model HTTP clients, base ToolGateway, base model and RuntimeEngine, and a RunRepository with business persistence hooks (`backend/src/agent_platform/applications/platform_runtime/runtime_composition.py:152-190`).
3. Create the shared memory store/service groups/RuntimeBindings, then one RuntimeFactory, RuntimeAdmission, and RuntimeWorker (`backend/src/agent_platform/applications/platform_runtime/runtime_composition.py:235-292,307-332`).

Multiple Runs reuse these process resources. Later refactoring must not silently reconstruct model HTTP clients, tool policy, memory services, or Repository for every request.

### 3.2 Submission and claim

- Admission stores the published Agent snapshot in `runtime_runs.config`, including agent id/version, raw versioned config, tool snapshot, and `is_example` (`backend/src/agent_platform/core_platform/agent_runtime/admission.py:34-67`, `backend/src/agent_platform/business_capabilities/agent_config/service.py:396-426`).
- Claim, not submit, loads conversation history, rolling summary, and customer_id (`backend/src/agent_platform/core_platform/agent_runtime/repository.py:203-251`).
- A successful claim sets owner, started_at, and lease_until before entering running (`backend/src/agent_platform/core_platform/agent_runtime/repository.py:203-251`).

### 3.3 Each claimed Run

1. Worker binds tenant/business/workspace scope and compares the stored fingerprint with the current process fingerprint; mismatch raises `RuntimeFault("configuration_changed")` (`backend/src/agent_platform/core_platform/agent_runtime/worker.py:38-46,71-80`).
2. Production calls `RuntimeFactory.for_run(row, emit)` for every Run. Without an Agent snapshot it returns the shared base Engine; with a snapshot it creates per-Run ToolGateway, PlatformTools, GatewayChatModel, effective settings, and Engine (`backend/src/agent_platform/applications/platform_runtime/runtime_factory.py:76-114`).
3. `effective()` merges prompt/language policy, constrains rounds through policy, and combines global and Agent summary switches (`backend/src/agent_platform/applications/platform_runtime/runtime_factory.py:51-74`).
4. Worker also accepts a direct Runtime object without `for_run` as a compatibility/test path (`backend/src/agent_platform/core_platform/agent_runtime/worker.py:76-88`); this is not the production Factory path.
5. Worker renders summary and asynchronously reads customer memory before calling Engine. `MemoryInjectionPort` receives the Worker process settings, not Factory's per-Agent effective settings; Agent memory configuration is separately read from `row.config` (`backend/src/agent_platform/core_platform/agent_runtime/worker.py:81-89,125-138`, `backend/src/agent_platform/business_capabilities/memory/injection.py:48-59`).

## 4. Data Access and Side-Effect Boundaries

| Data | Current readers/writers and evidence | Baseline constraint |
|---|---|---|
| `runtime_runs` | Primarily Repository (`backend/src/agent_platform/core_platform/agent_runtime/repository.py:55-149,203-391`); specialized handoff writes (`backend/src/agent_platform/business_capabilities/human_handoff/service.py:125-153`) | Engine must not directly change state, owner/lease, cancel flag, event_seq, output/error, or timestamps |
| `runtime_events` | Repository `_event` (`backend/src/agent_platform/core_platform/agent_runtime/repository.py:30-53`); specialized DurableToolReplayCache writer (`backend/src/agent_platform/core_platform/tool_gateway/replay.py:80-119`) | Ordinary events share the state transaction; `(run_id, seq)` is the primary key and seq is a per-Run cursor |
| `runtime_conversations` | submit/claim/finish hooks (`backend/src/agent_platform/core_platform/agent_runtime/repository.py:55-149,203-325`, `backend/src/agent_platform/applications/platform_runtime/runtime_hooks.py:49-84`) | History, summary, and customer binding flow between claim and finish |
| Agent draft/version/snapshot | AgentConfig service and Admission/Factory (`backend/src/agent_platform/business_capabilities/agent_config/service.py:396-426`, `backend/src/agent_platform/applications/platform_runtime/runtime_factory.py:51-114`) | Later publication must not rewrite an existing version; a Run pins its submission snapshot |
| Tool/model calls | ToolGateway, GatewayChatModel (`backend/src/agent_platform/core_platform/agent_runtime/engine.py:31-145`, `backend/src/agent_platform/core_platform/platform_services/model_gateway/gateway.py:551-604`) | Engine calls abstractions; raw provider exception text must not enter ordinary failure terminals or public SSE |
| Memory/summary | Worker, MemoryInjection, completion hooks (`backend/src/agent_platform/core_platform/agent_runtime/worker.py:81-99`, `backend/src/agent_platform/applications/platform_runtime/runtime_hooks.py:49-135`) | Completion hooks run only on success; failed/cancelled execution must not impersonate successful side effects |

## 5. Existing Test Mapping and Added Baseline Responsibilities

| Dependency area | Existing target evidence | Phase 0 additions |
|---|---|---|
| Engine loop/budgets/errors | `backend/tests/test_runtime_engine.py:50-237`: normal tool loop, parallel tools, argument validation, budgets, empty output, model timeout, and HTTP sanitization | Complete event payloads, Worker generic-exception mapping, and transient delta split |
| Queue/lease/cancellation | `backend/tests/test_runtime_postgres.py:60-144,279-307`: exclusive claim, tenant isolation, late finish after cancellation, lease loss, queue timeout, and in-flight cancellation | Full lifecycle, failure terminals, late append, reaper variants, and SSE cursor boundaries |
| API/SSE | `backend/tests/test_runtime_postgres.py:171-202`, `backend/tests/test_open_platform.py:109-159,222-257` | Freeze strict-after behavior, hidden replay payloads, and public-field reduction |
| Agent snapshots | `backend/tests/test_platform_postgres.py:277-301`, `backend/tests/test_memory_config.py:38-201` for existing default/legacy/boundary cases | Synthetic legacy-shape fixtures for publication/snapshot compatibility and tenant isolation; real-production representativeness remains separate |
| Process composition | `backend/tests/test_runtime_postgres.py:147-168,205-272`, `backend/tests/test_platform_postgres.py:277-301` for indirect coverage | Later phases must rerun both Factory and direct-Runtime paths, not only a new abstraction |

## 6. Known Differences and Later Constraints

- The specialized `tool.replay` writer lacks ordinary append's full owner/lease/terminal protection (`backend/src/agent_platform/core_platform/tool_gateway/replay.py:80-119` versus `backend/src/agent_platform/core_platform/agent_runtime/repository.py:253-270`); see `run-lifecycle-events.md`. Phase 0 records rather than fixes it.
- The open-platform `message()` stream comment says token deltas are absent, while the implementation emits visible-text deltas (`backend/src/agent_platform/business_capabilities/open_platform/routes.py:408-428,337-361`). This is an existing P2 comment/documentation discrepancy.
- No real historical published snapshots were supplied; current fixtures cannot establish production-sample representativeness. See `configuration-compatibility.md`.
- Later Engine/Protocol/Adapter abstractions must preserve the public HTTP contracts, per-Run snapshot, fingerprint, tenant/workspace binding, and completion transaction. They must not infer current production behavior from the neutral `RunPort`.
