# Phase 2 · React Provider and Execution Orchestrator — Acceptance Plan

> Status: Local T2–T11 and R17 live validation are complete, as are the R18 production remediation and focused validation; see 06/07 and their appendices. Minimal R18 live on/off revalidation is complete; the overall result remains conditionally passed
> Created: 2026-11-02
> Revised: 2026-11-12 (R18 and current-status alignment; design-phase content remains a historical plan)
> Basis: `01-business-goals.md` (G1–G4), `02-requirements.md` (US-1–US-4, FR-1–FR-6, AC-1–AC-9), `03-technical-design.md`, `04-test-plan.md`, `08-implementation-breakdown.md` (R1–R18, T8–T11)

## 1. Acceptance Organization and Evidence Boundaries

| Role | Responsibility |
|---|---|
| Backend owner | Explain implementation boundaries against R1–R18/T1–T7 and provide off/on path, call-chain, error/cancellation, and resource-cleanup evidence |
| QA | Execute every primary 04 test and create bilingual 06; prepare equivalent controlled fixtures, serial/parallel diffs, real PG, both SSE APIs, Memory, and rollback evidence |
| SRE/release owner | Verify default off, explicit on, off API/on Worker, mixed Workers, existing rows, rolling restart, and rollback; review low-cardinality observability |
| Security/platform reviewer | Review UUID/nil identity boundaries, cross-tenant isolation, public errors, HTTP/SSE/log/metric redaction, and dependency direction |
| Product/business acceptor | Decide whether replies, tools, Memory, events, errors, and cancellation remain compatible and sign accepted residual items |
| Human acceptance owner | Create bilingual 07 only after A1–A9 primary scenarios and C1–C5 have actual evidence, stating passed/conditionally passed/failed and signoff |

**Evidence boundaries**:

- Code merge, automated testing, and human acceptance are three independent states; Phase 1 merging into integration through `0a6c4b5` substitutes for no human acceptance.
- T8 local/dedicated-environment execution, CI runs, and T9 human operations separately record executor, time, environment, commit, commands/operations, and raw evidence links; none signs for another.
- Every primary 04 test has an independent 06 row and every 05 A/C item an independent 07 judgment. Skip, unrun work, and insufficient environment are never passed; insufficient real environment or human signoff is `pending_env`.
- The current design freeze creates no Phase 2 06/07 and prefills no result. Create them only after actual T8/T9 completion; T11 only appends post-acceptance sections and never rewrites earlier evidence.

## 2. Environments, Data, and Entry Conditions

### 2.1 Primary Acceptance (T9) Entry Conditions

1. T1–T7 complete in dependency order, the T8 primary-test exit is met, no P0/P1 remains open, and the off path has zero baseline behavior diff.
2. Use an independently created `pgvector/pgvector:pg17` Docker container with a fresh dedicated DB and volume; the connection string remains only in a restricted env file outside the repository, is injected through `TEST_DATABASE_URL`/`AGENT_DATABASE_URL`, and is never printed.
3. Dynamically record current Alembic heads, empty-database upgrade/current, and before/after migration-directory inventory/hashes; the 0057 design observation is not a permanent acceptance constant.
4. Old/new paths use equivalent controlled fixtures: no-snapshot legacy base_runtime, a real published Agent snapshot, fixed/parallel tools, timeout/errors, history/summary/customer_memory/reasoning; never borrow production customer data or credentials.
5. **T9 does not create the Phase 2-specific example seed early**; use controlled test fixtures so example-data preparation does not contaminate formal acceptance.

### 2.2 Post-Acceptance Seed Supplement (T10/T11)

Only after T8 testing and T9 formal acceptance complete may T10 add Phase 2-specific, idempotent, low-sensitivity, recognizably namespaced example data and T11 validate quickstart default off, explicit on, embedded Worker, both SSE APIs, path logs, and off rollback. Append T11 results as post-acceptance-validation sections to A8/C items and 06/07; failures reopen defects and affected acceptance items rather than being retroactively approved.

## 3. AC-by-AC Acceptance Scenarios

### A1: Fixed React Identity, No-Snapshot/Published-Snapshot, and Serial Reply Parity

- **Traceability**: AC-1; FR-1/2; G1/G2; R2/R7/R8/R16; P2-UT-01–04, P2-IT-01/02/18/20.
- **Steps**: Prepare no-snapshot legacy base_runtime and a real published snapshot separately and run the same serial no-tool script under default off and explicit on. Execute P2-UT-01 cases for original-object preservation of exact stdlib UUIDs, controlled UUID-subclass conversion, strings/integers/None/forged non-UUID values, value mismatch, ordinary exceptions from malicious `__str__`/descriptors, and control-flow re-raise. Through P2-IT-18, obtain a claimed row from the real asyncpg driver without fixture pre-normalization, execute the actual claimed row→ExecutionContext→ExecutionRequest chain, and spy the RuntimeFactory argument. Inspect the real UUID from `config.agent.id`, safe failure for missing/malformed/nil, and the restricted UUID(int=0) sentinel; compare output, successful history/dropped, stable payload, order, per-Run sequence, usage, error_code, terminal frame, and replay from every cursor.
- **Pass criteria**: Normalization preserves the original object for an exact stdlib UUID and converts a UUID subclass to an exact stdlib UUID. Normalize row.id and execution_id separately and require value equality with `==`, never `is`; public Request.execution_id is an exact stdlib UUID whose value directly equals claimed row.id. In the real asyncpg chain, `context.row is claimed_row`, RuntimeFactory receives that same original row, and original row.id retains the same object identity, type, and value without copying, replacement, or rewriting. Strings/integers/None/forged non-UUID values/value mismatch and malicious ordinary exceptions produce only safe static `INVALID_REQUEST`, while control-flow exceptions re-raise unchanged. Never borrow a Run/conversation UUID as Agent; nil never enters selectors/authorization/queries/DB/HTTP/SSE/logs/metrics/metadata; production resolves only react/native/v1; serial differences are limited to explicitly validated paths in 03 section 7.3. usage is non-optional and never None; without aggregation input React v1 public Result/private Outcome usage is `{}`, neither an existing aggregate nor fabricated zero tokens, while model.completed usage remains verbatim.
- **Evidence**: Controlled-fixture description, old/new structured results, event/replay field diffs, identity adversarial cases, and actual test nodes. For R16, additionally attach the real asyncpg driver return type; before/after normalization object identity, type, and value relationships; assertions/raw output proving exact stdlib UUID in Request with value equality to row.id, `context.row is claimed_row`, `context.row["id"] is original_row_id`, the same original row received by RuntimeFactory, and unchanged original row.id; plus safe static `INVALID_REQUEST` for forged input and malicious ordinary exceptions and control-flow re-raise evidence. Helper-only tests or fixture preconversion cannot replace P2-IT-18's real chain. Report raw latency separately rather than replacing it with canonical diff.

### A2: Tools, Parallel Partial Order, Memory, and Reasoning Parity

- **Traceability**: AC-2; FR-1/3; G1/G2; R4/R7/R11; P2-UT-04/12/22, P2-IT-02/03/15/17.
- **Steps**: Run off/on with identical model rounds, serial/parallel tool arguments/results, budgets, history truncation, summary/customer_memory, and reasoning scripts; align started/completed by call_id, inspect model-round boundaries and no-call_id parallel-event multisets; verify summary/history/extract/reinforce/injection transactions in real PG.
- **Pass criteria**: Tool sets, per-call_id started→completed partial order, model-round boundaries, arguments/results, and budget errors match; parallel branches need no cross-path global order/absolute sequence; successful history/dropped reaches Memory only through private Outcome and failed/cancelled execution does not write back. usage is non-optional and never None; without aggregation input React v1 Result/Outcome usage is `{}`, neither an existing aggregate nor zero tokens, while model.completed usage is verbatim.
- **Evidence**: call_id/model-round alignment, original payloads and usage, Memory input/commit/rollback and tenant-isolation records; never normalize call_id, business IDs, tool arguments/results, output/error/usage.

### A3: Orchestrator Call Chain, Sync/Async Assembly, and LocalTest Decoupling

- **Traceability**: AC-3; FR-2/3; G2/G3; R3/R5/R8/R14; P2-UT-02/03/08–11/14–16/21/24, P2-IT-04/14.
- **Steps**: Inspect and demonstrate synchronous no-await ContextVar set→registry.resolve→finally reset and application zero-argument fresh-factory capture of Context containing no emit. Worker passes its original callback as separate worker_emit to Orchestrator; the Adapter runner creates private runtime_emit and passes the same function object with the same claimed row to for_run/run. Execute concurrency, nesting, exceptions, multiple Runs, and dual-emit spies; verify exactly one React-private `collect_outcome` after drain and all three completed/failed/cancelled Outcomes, then run protocol-free LocalTest through the same Orchestrator/Worker with a separate Registry/selector for public-collect→Outcome fallback success/failure/cancellation.
- **Pass criteria**: Worker has no Engine-type branch and Core imports no applications/business; Factory/PlatformTools/RuntimeEngine cannot reach worker_emit, and Orchestrator exclusively invokes it only after public-stream retrieval. Context neither leaks across tasks nor fails to reset, Adapter never reads ContextVar after creation, each instance has one active execution and no shared state, agent_model_required retains its legacy code, and enabled failure never falls back. React detects Core-private `AcknowledgingEventStream` and acknowledges after successful worker_emit; LocalTest has no protocol and retains pre-claim queueing, terminal discard, and yield=delivery. `OutcomeCollectingAdapter` verifies genuine async capability and descriptor fail-closed behavior. React neither repeats public/private collection nor accesses `_execution`; completed retains real history/dropped, failed retains original codes including unknown RuntimeFault, and cancelled has no code. LocalTest uses only deterministic public-error-code fallback, and public Result/engine_metadata contain no private fields.
- **Evidence**: Call-chain logs/traces, dependency static checks, concurrent/exception output, and per-stage dual-emit spy order/counts; actual nodes/output for Outcome protocol detection, all three React and LocalTest states, Handle/collector/cancellation consistency, single collection, and no `_execution` access. Under 03 section 4.2 list all 25 public-suite functions individually: 19 reused (streaming cases explicitly wrapped with worker_emit/ack), six excluded, and every private replacement result; private-protocol tests use raw stream directly. Never claim that the public AsyncIterator suite independently proves private ack delivery.

### A4: Open Events, Ack Backpressure, Internal/Open SSE, and Replay Compatibility

- **Traceability**: AC-4; FR-4; G1/G4; R5/R6/R7/R15; P2-UT-05/17–21, P2-IT-05/06/15/16.
- **Steps**: Send model.delta/model/tool, knowledge.retrieved, memory_search.completed, and extension business events; forge run.*/tool.replay and malformed events while recording runtime_emit→public yield→worker_emit→ack spies. Verify start→immediate-stream loses no first event, a lone no-stream collector explicitly releases the gate, stream after closed/terminal, and cancel/aclose wakes the first-emission gate. Control races with capacity one, multiple events and slow worker_emit, blocked put/get, invalid/duplicate/out-of-order/cross-execution ack, append/emit failure, and late results; test Last-Event-ID, after, 200+ draining, delta, tool.replay, and field filtering separately on internal/Open APIs. Through actual ASGI/FastAPI routes, separately exercise invalid/out-of-range manually parsed internal Last-Event-ID, internal typed-after type/range errors, Open typed-after and Last-Event-ID type/range errors, and valid max/strict replay on both APIs.
- **Pass criteria**: Valid business events retain original name/JSON payload without an allowlist and reach worker_emit exactly once only through the public stream; reserved events retain sole ownership and forgeries never reach worker_emit. React-private never-claimed/claimed-active/closed/terminal and first-call collect/stream linearization are correct, and no-stream suppression is not analogized to LocalTest. Yield is not delivery; ack matches execution_id/event_id against unique in-flight exactly once, repeated settled ack is idempotent, and wrong-identity/out-of-order/no-in-flight ack produces safe protocol_error and abort. Pending runner result publishes uniquely once producer is finished and queued+in-flight undelivered=0, without an idle unclosed claimed stream blocking collect; drain→collect→Worker finish leaves run.* terminal frames last. Delta has no DB sequence/replay and hidden tool.replay advances cursor. Internal manual-header boundaries return `400 / invalid_last_event_id`; internal typed-after and Open typed-after/header boundaries return 422; valid cursors combine through `max(after,last_id)` and replay strictly only `seq>after`. Never interchange 400/422 or change routes, schemas, status codes, or error bodies; no duplicate terminal, private-data disclosure, or dangling task exists.
- **Evidence**: Original event input/output comparison, dual-emit and queue/ack-identity state traces, first-emission/no-stream/closed/terminal traces, both SSE cursor/replay records, boundary results for Notifier-swallowed PG/OS delta failures versus other emit exceptions, and task-cleanup inventory. Separately attach the actual internal-route manual-header `400 / invalid_last_event_id` response, actual internal-route typed-after 422 response, actual Open-route typed-after/header 422 responses, and request/response plus replay sequences proving valid `max(after,last_id)` and strict `seq>after` on both APIs; helper unit tests cannot substitute for this ASGI/FastAPI route evidence.

### A5: Complete Error Matrix and Safe Failure

- **Traceability**: AC-5; FR-5; G1/G4; R4/R6; P2-UT-06/09/20, P2-IT-07/16.
- **Steps**: Inject every 03 section 6.1 row: agent_model_required/configuration_changed, invalid/empty responses, duplicate/repeated tool calls, round/tool/output budgets, model_resource_not_found/disabled, model_profile_version_not_found, model_input_too_large, model_tools_not_supported, model_provider_unavailable/model_rate_limited/model_provider_rejected/model_transport_error, content_blocked_input/output, gateway_concurrency_exceeded/request_quota_exceeded, model_credential_unavailable, model_response_too_large, model_stream_interrupted, and model/run timeout. Also inject a future unknown RuntimeFault code, reserved/malformed events, ordinary stream/worker_emit, stale append, and unknown ordinary exceptions; inspect public ExecutionResult and RunView/run.failed.
- **Pass criteria**: Public output contains only safe ExecutionErrorCode/static messages without Provider/Domain text; every known/future-unknown RuntimeFault retains its original private legacy_error_code verbatim, future codes use public internal_error safe fallback, unknown ordinary exceptions use internal_error/execution_error, and ordinary emit failure is failed, not cancelled. agent_model_required never becomes adapter_factory_failed and model_stream_not_supported currently falls back. CancelledError from stale/cancelled/expired append is unacknowledged/unpersisted, aborts/acloses and re-raises without changing the original terminal state or becoming ordinary execution_error; no secret, input/config/history, raw exception, or stack reaches public surfaces.
- **Evidence**: Row-by-row results for the complete matrix in 03 section 6.1, public/private error comparison, and safe log/API checks; sampling cannot replace any missing row.

### A6: Cancellation, Aclose, Collector Cancellation, and Late-Result Protection

- **Traceability**: AC-6; FR-1/4/5; G1/G3; R5/R6/R10; P2-UT-07/18–20, P2-IT-08/09/16.
- **Steps**: Explicitly cancel before first-emission release, while model waits, producer has a full queue, consumer waits, and completion races, then release success; repeat cancel/aclose; cancel a lone no-stream collector, a shared collector, and the Orchestrator caller separately. In real PG use gates for finish/reaper-first followed by cancel and cancel-first followed by late finish.
- **Pass criteria**: Explicit Adapter cancel uses internal first-terminal-wins, returns cancelled with no output/error, and never retroactively cancels a completed Result. Shared collectors are shielded, lone no-stream collector cancellation wakes the gate and stops execution without borrowing LocalTest semantics, and caller CancelledError cleans up and re-raises; queue/runner are atomically suppressed, cancelled, and drained, and late events/success create no second terminal. Run persistence uses submission-order first-commit-wins: finish/reaper-first makes cancel a no-op, while cancel-first prevents late-finish overwrite; all owned tasks are done.
- **Evidence**: Event/gate-controlled timelines for both orders, Adapter Result and Repository conditional update/event sequence, repeated-operation results, and task states; outer timeout only prevents hangs and sleep coincidence is not evidence.

### A7: Model/Run Timeout, Lease Loss, and Unique Terminal State

- **Traceability**: AC-7; FR-5; G1/G3/G4; R4/R10; P2-UT-23, P2-IT-10/11.
- **Steps**: Construct model_timeout and run_timeout independently; lose heartbeat, expire the Lease, let reaper take over, then release stale Worker success/append/finish; simultaneously race cancellation, timeout, and completion.
- **Pass criteria**: Results are failed/model_timeout, failed/run_timeout, and failed/worker_lost respectively; lease loss is not user cancellation. Stale/terminal/wrong-owner/expired finish silently no-ops, while stale/cancelled/expired append persists nothing and raises CancelledError, with Orchestrator leaving it unacknowledged, cleaning up, and re-raising without changing the original terminal state or mapping to ordinary execution_error. Reaper retains cancelled-with-worker_lost/queue_timeout variants, with no automatic retry or second terminal; cooperative coroutines drain boundedly under outer timeout, with no forced-termination claim for non-cooperative coroutines.
- **Evidence**: Real PG owner/lease/terminal rows, monitor_failure results, distinct append/finish control flow, both commit orders and reaper variants, stale Worker logs, and unique terminal events; resource-cleanup failure is separately P0/P1 and cannot be ignored.

### A8: Default Off, Rollout, Mixed Workers, Rollback, and Post-Acceptance Seed Appendix

- **Traceability**: AC-8; FR-6; G3/G4; R9/R12; P2-UT-10/13/24, P2-IT-12/13/18; appendix P2-CM-09/10.
- **T9 primary steps**: Start by default, explicitly on, off API/on Worker, and with mixed legacy/orchestrator Workers; inspect fingerprint, existing queued/running/terminal rows, and mixed claims; disable/remove a registration to observe fail fast; finally set all processes off and rolling-restart.
- **Primary pass criteria**: off uses only legacy and on only Orchestrator, with flag excluded from fingerprint; mixed execution never shares/reclaims a row or rewrites terminal; new Runs use only legacy after rollback and in-flight work converges under cancellation/Lease; enabled failure never silently falls back and no migration, data repair, or client change is required.
- **Post-acceptance appendix**: Execute T10/T11 only after T9 formal acceptance; the new seed must do more than rerun existing seeds and must have a Phase 2-specific namespace, real Agent IDs, idempotency, and low sensitivity, using only existing schema/API/published snapshots; quickstart verifies off/on for published-snapshot and no-snapshot legacy base-runtime examples, embedded Worker, both SSE APIs, path logs, and off rollback with no new service.
- **Evidence**: Primary acceptance stores configuration/process/path/fingerprint/existing-row/rollback records; T11 appends second-seed-run results and actual quickstart logs/SSE. T9 prewrites no seed result and a T11 failure reopens this item.

### A9: Zero Public Change, Dynamic Migrations, Observability, and Regression Completeness

- **Traceability**: AC-9; FR-4/6; G3/G4; R1/R4/R11/R15; P2-CM-01–08, P2-IT-05/06/19/20.
- **Steps**: Dynamically run heads/empty-database upgrade/current and compare migration directories before/after; review ORM, public HTTP/SSE routes, schemas, status codes, error bodies, and frontend diffs; inspect Phase 1 protected surfaces, cross-tenant isolation, public errors/fields, logs/traces/metrics; reconcile affected tests, CI, and human evidence individually, and review A4's R15 actual-route responses.
- **Pass criteria**: No added/modified migration, ORM, public schema, or frontend exists; public API routes, schemas, status codes, and error bodies have zero changes, and R15's existing internal manual-header 400, internal typed-after 422, and Open typed-after/header 422 are never interchanged or rewritten. Current heads dynamically match the baseline, directory drift is zero, and existing rows remain compatible; run_id is limited to logs/traces, metric labels are low-cardinality, and no nil/secret/input/config/history/raw stack appears; Phase 1 DTO/Registry/LocalTest, Repository/hooks, and API behavior remain unchanged; every test/A/C item has locatable evidence. Every P2 functional UT/IT/CM must pass, while CM08 evidence-integrity/measurement boundaries may pass independently; insufficient real performance evidence leaves only that submetric pending_env, does not negate functional exit, and caps T9 at conditionally passed.
- **Evidence**: Read-only command output, version-directory inventory/hashes, public-route/schema/status-code/error-body and frontend diffs, A4's actual ASGI/FastAPI route records for all three invalid-cursor boundaries plus valid max/strict replay, cross-tenant and observability samples, actual tests, and CI links; an unrun local full suite is never called fully passing.

## 4. Business and Performance Metric Measurement

| Metric | Method and pass criterion | Evidence boundary |
|---|---|---|
| Reply/tool/Memory parity | Compare under A1/A2 strict serial rules, parallel partial order/multisets, and real PG transactions; stable fields have zero unintended difference | Preserve original values and exact canonical paths; never globally remove IDs or hide differences |
| Event/SSE/terminal compatibility | Replay every cursor under A4, inspect contiguous per-Run sequence, transient delta, tool.replay cursor, terminal-last position, and unique terminal state | Internal/Open evidence is separate; AgentEvent sequence never replaces DB/SSE ID |
| Cancellation/timeout/Lease convergence | Under A6/A7 controlled races and real PG, inspect classification, cleanup, and late-result protection | Outer timeout is not functional duration; non-cooperative coroutines have no forced-kill promise |
| Rollback recoverability | After all-off rolling restart, new Runs use only legacy with no migration/data repair/client change | Preserve before/after configuration, process, and path evidence |
| Performance | Paired sampling under the reproducible method below in an equivalent real external environment shows new-path nearest-rank p95 end-to-end latency increase ≤5%; report first token, raw paired overhead, and error rate independently | Canonical diff cannot replace performance; test doubles support functional evidence only, and insufficient real external environment is `pending_env`, never claimed as passing |
| Post-acceptance examples | T10/T11 idempotent seed and quickstart off/on/rollback appendix actually complete | Append only new evidence; failures reopen A8/C items |

### 4.1 Reproducible Performance Sampling and Calculation

1. **Fixed matched pairs**: Collect at least **30 valid matched pairs per fixed scenario**, each containing one legacy-off and one orchestrator-on execution of identical input. First run **five matched warm-up pairs** to warm processes, connections, and caches; label warm-ups explicitly and exclude them from the 30 sample pairs. Never silently discard failures/anomalous samples; record error rate separately.
2. **Equivalent environment and order**: Use the same host/container resources, script, real model and Profile, tool configuration, data, and dependency versions. Alternate off/on or use a balanced order, preserving order, nonsensitive environment identifiers, and raw samples so path is not confused with time/cache trends.
3. **p95 algorithm**: Sort old/new end-to-end samples independently in ascending order and use **nearest-rank**, taking the 1-based `ceil(0.95 × N)`th value; for N=30 take the **29th** value. The target is `p95(new) <= p95(old) * 1.05`; do not substitute interpolation or report only means.
4. **Independent metrics**: Preserve raw old/new end-to-end values, paired delta/ratio, raw Adapter overhead, first token, and error rate for every pair. Present paired overhead separately from p95; canonical diff cannot replace or hide raw latency.
5. **External-latency boundary**: Real external model/tool latency is included in end-to-end measurements and must not be deducted to conceal regression. Adapter-internal overhead may be reported separately for diagnosis but cannot replace the end-to-end target.
6. **Insufficient environment**: Test doubles, mock/demo models, and MockTransport prove functionality/measurement mechanics only, never production performance. Without real external models/tools or an equivalent environment, mark the performance submetric `pending_env`; functional tests and CM08 evidence integrity may pass independently, but T9 is capped at conditionally passed/pending performance evidence, never fully passed.

## 5. Compliance Checks

| ID | Check | Pass criterion and evidence | Traceability |
|---|---|---|---|
| C1 | Database and public compatibility | No migration/ORM/public HTTP/SSE schema/frontend change; public API routes, schemas, status codes, and error bodies have zero changes, with actual ASGI/FastAPI route evidence for R15 internal manual-header 400, internal typed-after 422, Open typed-after/header 422, and valid max/strict replay; dynamic heads, empty-database upgrade, zero directory drift, and existing-row evidence are complete; Phase 1 DTOs remain unchanged | AC-4/9, R1/R15, P2-IT-05/06, P2-CM-01/05/07 |
| C2 | Identity, multi-tenancy, and sensitive information | R16 private Execution UUID normalization has complete evidence: original-object preservation for exact stdlib UUIDs, controlled UUID-subclass conversion, two-sided `==` value equality, exact stdlib UUID in public Request, the real asyncpg chain, and original-row retention by Context/RuntimeFactory. Forged input and malicious ordinary exceptions produce only safe static `INVALID_REQUEST`, control flow re-raises, and original row.id remains unchanged. Snapshot Agent UUID is strict and nil remains internal-only without leakage/query; cross-tenant access fails; public errors/Result/logs/metrics contain no secret, raw exception, history/Outcome/Context | AC-1/4/5/9, R2/R4/R16, P2-UT-01, P2-IT-18/20, P2-CM-03/04 |
| C3 | Dual emits, event ownership, and structured delivery semantics | Context contains no emit, worker_emit belongs only to Worker/Orchestrator, and runtime_emit only to the private Runtime chain; ordinary business events pass through the public stream, run.* is Repository-only, tool.replay DurableToolReplayCache-only, and delta Notifier-only, with forgeries never reaching worker_emit. React first-emission/no-stream and ack identity/exactly-once/abort have independent evidence, all 25 public-suite functions have explicit decisions, and LocalTest pre-claim queueing/terminal discard/yield=delivery remains unchanged | AC-3/4, R3/R5/R6, P2-UT-03/05/09/17–21 |
| C4 | Configuration, release, and dependency governance | Default off, startup application, fingerprint exclusion, enabled fail-fast, mixed Workers/rollback are evidenced; Core has no reverse application dependency, second ReAct, or new service | AC-3/8, R3/R8/R9, P2-CM-02/06 |
| C5 | Lifecycle, functional/performance exit, and evidence integrity | T8 creates bilingual 06 and T9 bilingual 07 only after execution; every test/A/C item has an actual result, all functional UT/IT/CM pass, and CM08 evidence-integrity/measurement boundaries pass independently. Local/CI/human evidence remains separate, performance pending_env is honest with T9 capped at conditionally passed, and T10/T11 occur after acceptance, append only, and reopen on failure | AC-8/9, R11/R12, all primary/appendix cases in 04 |

## 6. Pass Criteria, Residual Items, and Signoff

### 6.1 Formal Primary Acceptance (T9)

- A1–A9 **primary scenarios** and C1–C5 all have evidence and meet their criteria; the T8 primary-test exit is met and no P0/P1 remains open.
- P2 permits conditional acceptance only with explicit product/business acceptance and an owner, deadline, and impact scope; P3 items are scheduled.
- If the real external environment cannot support performance measurement, mark only the performance submetric `pending_env`; this does not negate fully green functional UT/IT/CM or independently passed CM08 evidence-integrity/measurement boundaries, but T9 overall is capped at conditionally passed/pending performance evidence and can never be fully passed.
- Acceptors sign conclusion, date, commit, evidence links, and residual items; code merge or green CI alone cannot replace signoff.

### 6.2 Post-Acceptance Appendix (T11)

T10/T11 does not retroactively become a prerequisite performed before T9; actual results must be appended to 06/07 and the A8/C5 appendix. If seed or quickstart validation fails, reopen A8 and related C items and restore the conclusion only after fix and revalidation; retain prior report text and failure evidence.

### 6.3 Signoff Table (Completed During Actual Acceptance)

| Role | Name | Conclusion | Date | Evidence/notes |
|---|---|---|---|---|
| Backend owner | To be completed | Pending acceptance | To be completed | To be completed |
| QA | To be completed | Pending acceptance | To be completed | To be completed |
| SRE/release owner | To be completed | Pending acceptance | To be completed | To be completed |
| Security/platform reviewer | To be completed | Pending acceptance | To be completed | To be completed |
| Product/business acceptor | To be completed | Pending acceptance | To be completed | To be completed |
