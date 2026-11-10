# Phase 2 · React Provider and Execution Orchestrator — Test Plan

> Status: Pending review / Pending implementation
> Created: 2026-11-02
> Basis: `02-requirements.md` (FR-1–FR-6, AC-1–AC-9), `03-technical-design.md` (ReactAdapter, Orchestrator, SSE parity, terminal protection, default-off flag)

## 1. Test Scope and Principles

**Scope**: Complete ReactAdapter contract, Execution Orchestrator, Worker old/new paths, registry resolution, event/SSE compatibility, error/cancellation/timeout/Lease terminal states, global flag, mixed deployment, and rollback; external Engines and Runtime Host are excluded.

**Principles**:

1. **Old/new parity is mandatory**: Run legacy and orchestrator with identical model/tool response scripts and compare output, history/dropped, events, error codes, and terminal states field by field.
2. **Flag fallback is mandatory**: Default and explicit off both use legacy with zero diff from the Phase 0 baseline; enabled failures never silently fall back.
3. **Both SSE interfaces are mandatory**: Verify durable events, transient delta, cursor replay, terminal frames, filtering, and redaction separately for internal and open APIs.
4. **Terminal-state races are mandatory**: Real Repository decides races between cancellation/Lease lost and success; mocking finish alone is insufficient.
5. **Do not wait in time-based cases**: Use short configuration or controlled clocks for model/run timeout and direct database changes for lease expiration; no pending task remains after async cases.

## 2. Test Environments and Data Construction

| Environment | Purpose |
|---|---|
| Unit (fake Registry/Adapter/Runtime) | Request/Outcome, React five methods, mappings, Worker branches, errors, and cancellation cleanup without DB |
| Integration (PG 17 + dedicated TEST_DATABASE_URL) | claim/heartbeat/finish/cancel/reap, real event sequences, and Repository terminal protection |
| mock/demo models and MockTransport | Programmable model text, tool calls, timeout, and invalid responses; repeatable real HTTP tool paths |
| ASGI internal and open APIs | Internal `/api/v1/runs/{id}/events` and open-platform SSE/replay/public-field redaction |
| Two Worker configuration groups | Mixed legacy/orchestrator execution against one database and rolling rollback exercises |

**Data construction conventions**: Reuse the dedicated tenant, RunRepository, and BusinessRuntimePersistenceHooks from `test_runtime_postgres.py`; old/new paths use independent but identical fixtures/model scripts. Construct Agent snapshots, summary/customer_memory/history directly; change lease/queue times directly in the database; never use production credentials or customer data.

## 3. Unit Tests

| ID | Case | Expected | Traceability |
|---|---|---|---|
| P2-UT-01 | claimed row→ExecutionRequest mapping | execution_id=run.id and tenant/conversation/input are correct; legacy config fixes react/native/v1 and accepts no client Engine/Effective capabilities | FR-2, AC-1 |
| P2-UT-02 | ReactAdapter identity, capabilities, and successful start | Properties are react/native/v1, Handle execution_id matches, declared capabilities fit current React, and unsupported Session/approval are not enabled | FR-1, AC-3 |
| P2-UT-03 | React start→stream→collect success | Adapter alone calls RuntimeEngine.run once; output/usage and private history/dropped are complete, with completed result | FR-1, AC-1 |
| P2-UT-04 | Empty output, tool loop, and dropped-history result packaging | Matches original Runtime returns; history/dropped remain only in private Outcome/metadata, never public payload | FR-1, AC-2, AC-9 |
| P2-UT-05 | Bidirectional model/tool event mapping and unknown/missing-field events | Original kind/data and order are lossless; model.delta retains transient semantics; invalid events fail controlled rather than rename | FR-4, AC-4 |
| P2-UT-06 | Parameterized mapping for every RuntimeFault code, model/run timeout, CancelledError, and unknown exception | category is correct and public error_code is preserved; unknown maps to execution_error without sensitive exception body | FR-5, AC-5, AC-7 |
| P2-UT-07 | React cancel twice and cleanup before start/after failure | cancel is idempotent, execution task and event stream close, and no second result or pending task remains | FR-1, AC-6 |
| P2-UT-08 | Orchestrator valid resolution and unknown version/unregistered/disabled combinations | Valid combinations create independent Adapters; invalid ones fail explicitly with no latest/legacy/other-Engine fallback | FR-2, AC-3, AC-8 |
| P2-UT-09 | Orchestrator exceptions in start/stream/collect | Every stage cleans tasks/iterators and produces normalized failure; repeated collect/cancel cannot create a second terminal state | FR-2, FR-5 |
| P2-UT-10 | Worker flag false/true branches and fingerprint failure | false invokes only legacy and true only Orchestrator; configuration_changed behaves identically on both paths | FR-3, FR-6, AC-8 |
| P2-UT-11 | Worker new-path Outcome→finish parameter mapping | completed/failed/cancelled, output/history/error_code are correct; Worker reads no Engine-private type | FR-3, AC-3 |
| P2-UT-12 | Memory summary/customer_memory/dropped across old/new paths | Rendered inputs and memory_context arguments match, with no history/dropped loss | FR-1, FR-3, AC-2 |
| P2-UT-13 | Settings default and environment override | Default false; `AGENT_EXECUTION_ORCHESTRATOR_ENABLED=true/false` parses correctly and invalid values are rejected | FR-6, AC-8 |
| P2-UT-14 | Static dependency-direction and public-serialization checks | Worker/Orchestrator do not import RuntimeEngine; RunView/SSE contain no history, process_id, or engine_metadata | FR-2, FR-4, AC-3, AC-9 |

## 4. Integration Tests

| ID | Case | Expected | Traceability |
|---|---|---|---|
| P2-IT-01 | Fixed-text model without Agent snapshot, once per old/new path | output, history/dropped, model events/usage, run.completed, and error_code are identical | AC-1, FR-1 |
| P2-IT-02 | Published Agent snapshot, Gateway Profile, language, and multi-round tool calls across paths | Same Profile/tool arguments/message order/tool results/budgets, equivalent replies/events, and unchanged snapshot | AC-1, AC-2 |
| P2-IT-03 | History truncation + summary + customer_memory + reasoning | Injected message order, dropped, memory_context, reasoning history retention, and invisibility match legacy | AC-2 |
| P2-IT-04 | Complete new-path Run and inspect Registry/Factory/Adapter/Orchestrator/Worker calls | Execution uses only react/native/v1 and Orchestrator; Worker has no Engine branch and Repository finish occurs once | AC-3 |
| P2-IT-05 | Internal SSE old/new comparison and Last-Event-ID replay | Durable event names/seq/data/order match; delta is transient with no id/persistence; stream closes after terminal frame with no duplicate run event | AC-4 |
| P2-IT-06 | Open API SSE, tool.replay filtering, and invalid cursor | Redaction/filtering match legacy; Last-Event-ID/after behavior and 400 remain unchanged, with no private metadata/internal gateway fields | AC-4, AC-9 |
| P2-IT-07 | Missing model, invalid/empty model response, round/tool budgets, and unknown Provider exception across paths | RunView and durable run.failed error_code match; logs/APIs contain no sensitive raw text | AC-5 |
| P2-IT-08 | Cancel while model waits, then release success; repeat cancel | Adapter/model task receives cancellation and cleans up; final state is cancelled with empty output and no late run.completed | AC-6 |
| P2-IT-09 | Real PG cancel/finish race and another finish after terminal state | Repository has one terminal state, cancellation wins, later completion is ineffective, and event sequence has no second terminal state | AC-6 |
| P2-IT-10 | Construct model_timeout and run_timeout separately | failed/model_timeout and failed/run_timeout respectively match legacy; tasks clean up with no automatic retry | AC-7 |
| P2-IT-11 | Expire Lease directly in DB, reap, then let old Worker commit late success | heartbeat returns lost and final state is failed/worker_lost; late output is not written and terminal event is unique | AC-7 |
| P2-IT-12 | Default off, explicit on, two mixed Worker groups on one DB, then off rolling restart | off uses only legacy and on only orchestrator; mixed results are equivalent; all new Runs use legacy after rollback and in-flight Runs converge under existing rules | AC-8 |
| P2-IT-13 | Remove/disable a registration with flag on, then start or execute | Fail fast with safe diagnostics; never silently use legacy or another version | AC-8 |
| P2-IT-14 | Replace React with Phase 1 LocalTestAdapter through the same Orchestrator | Common success/failure/cancellation executes without changing Worker core, proving concrete-Engine decoupling | AC-3 |

## 5. General Checks (Applicable to This Phase)

| ID | Check | Pass criterion | Traceability |
|---|---|---|---|
| P2-CM-01 | Database migration and existing-row compatibility | Head remains `0052`; no version-file changes; existing queued/running/terminal Runs read/write and roll back without data repair | AC-9 |
| P2-CM-02 | Configuration loading and default fallback | New flag defaults false and environment override works; off path has zero diff from Phase 0 baseline | AC-8 |
| P2-CM-03 | Audit, logs, and observability | run_id exposes path, react/native/v1, duration, terminal state, and error category; no input/config/history/key/raw stack | AC-9 |
| P2-CM-04 | Multi-tenancy and public data surface | tenant/business/workspace filtering unchanged; cross-tenant Run/SSE inaccessible; public responses contain no Engine-private metadata | AC-4, AC-9 |
| P2-CM-05 | API/SSE/Agent configuration compatibility | RunView/RunStatus/HTTP statuses, internal/open SSE, and published snapshot structures unchanged; existing related tests green | AC-1, AC-4, AC-9 |
| P2-CM-06 | Async resources and code quality | No pending Adapter/Worker task after success/failure/cancellation/rollback; affected ruff/pytest green and no new reverse dependency | AC-3, AC-6, AC-9 |

## 6. Regression Scope

- `backend/tests/test_runtime_engine.py`: RuntimeEngine itself is unchanged, and existing inference/tool/budget/cancellation tests must remain green.
- `backend/tests/test_runtime_postgres.py`: Both old and new paths verify claim, events, cancellation, HTTP/SSE, slow-model interruption, and late results.
- `backend/tests/test_open_platform.py`: Open API idempotency, authorization, event redaction, replay, and message ledger remain unchanged.
- `test_agent_model_required.py`, `test_agent_languages.py`: Old snapshots, model Profiles, and language behavior remain unchanged.
- Memory suites `test_memory_injection.py`, `test_memory_summary.py`, `test_memory_customers.py`, `test_memory_config.py`, `test_memory_governance.py`: Input injection and completion write-back are equivalent.
- `test_extension_contracts.py`: Existing RunPort/RuntimeBindings/RuntimeFactory remain compatible, and Engines are not inserted into Extension Registry.

## 7. Defect Severity and Exit Criteria

| Severity | Definition | Handling |
|---|---|---|
| P0 blocker | Reply/tool main flow broken; data loss; cross-tenant or credential disclosure; incorrect terminal overwrite | Immediately disable new path, fix, and run complete regression |
| P1 severe | Old/new semantic mismatch; SSE regression; cancellation/Lease failure; flag/rollback failure; Worker still coupled to Engine | Must be fixed before rollout expansion or acceptance |
| P2 normal | Non-critical performance degradation, missing diagnostics, or non-sensitive field difference without compatibility impact | May be accepted with a recorded issue and product sign-off |
| P3 minor | Documentation, naming, or non-sensitive log issue | Schedule a fix |

**Exit criteria**: All P2-UT/IT/CM pass; AC-1–AC-9 reproduce successfully; affected regression is green; off baseline diff is zero; cancellation/timeout/late results have no terminal-state error; no open P0/P1, migration change, or dangling task. Unmeasured performance must not be marked as meeting target.
