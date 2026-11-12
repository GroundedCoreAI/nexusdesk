# Phase 2 · React Provider and Execution Orchestrator — Business Goals

> Status: Local T2–T11 and R17 live validation are complete, as are the R18 production remediation and focused validation; see 06/07 and their appendices. Minimal R18 live on/off revalidation is complete; the overall result remains conditionally passed
> Created: 2026-11-02
> Revised: 2026-11-12 (R18 and current-status alignment; design-phase content remains a historical plan)
> Basis: `docs/architecture/agent-execution-platform-v2.md`, Sections 4–7, 12, 14–17, and 19–22; Phase 1 code merged into integration through merge `0a6c4b5`, which is not formal human acceptance; `08-implementation-breakdown.md` (R1–R18, T1–T11)

## Problems to Solve

### Problem 1: Worker is coupled to fixed ReAct Runtime construction and invocation

`backend/src/agent_platform/core_platform/agent_runtime/worker.py` currently obtains a Runtime through `RuntimeFactory.for_run()` and directly calls `run()`; `runtime_factory.py` always constructs `RuntimeEngine`. Worker therefore knows the concrete Runtime output `(output, history, dropped)` and exception forms, preventing future Engines from reusing one orchestration path.

### Problem 2: No component coordinates the common Execution lifecycle

The Phase 1 contracts and registries now merged need an Execution Orchestrator. No component currently maps a claimed Run to ExecutionRequest, exactly resolves `react/native/v1`, coordinates Adapter start/stream/cancel/collect, and normalizes results/errors. Adding these responsibilities directly to Worker would further increase its engine-specific knowledge.

### Problem 3: Refactoring must preserve observable Run, event, and SSE behavior

The existing `RunRepository` provides queued/running/completed/failed/cancelled, submission-order first-commit-wins, rejection of late commits after lease loss, durable event sequences, and replay. Internal and open APIs distinguish durable events from transient `model.delta`. Changing event names, stable payloads, cursors, terminal states, or error codes would break clients. The public AsyncIterator has no downstream acknowledgment, so dequeue/yield alone cannot prove that Worker successfully persisted or emitted an event.

### Problem 4: The first major refactor has no gradual, reversible execution entry point

Only the legacy Runtime call path currently exists. A default-off orchestration path, compatibility across mixed Worker groups, and recovery without database rollback are required to avoid cutting over all execution traffic at once.

## Business Goals

| Goal | Description |
|---|---|
| G1: React becomes the first common Provider | Preserve LangGraph ReAct inference and tool execution, wrap them in a complete React Adapter, and resolve the fixed `react/native/v1` identity through registries; reuse the existing RuntimeFactory/RuntimeEngine rather than writing a second ReAct |
| G2: Decouple Worker from concrete Engines | The orchestrator manages the Adapter lifecycle, public Result, and private Outcome; Worker retains queueing, Lease/Heartbeat, cancellation monitoring, Memory completion hooks, and Repository terminal commits without knowing Engine internals |
| G3: Zero regression for existing users | Old and new paths remain equivalent under the deterministic/parallel rules in 03 for output, history, Memory, events, SSE, error codes, cancellation, and terminal states; public APIs, the database, and frontend remain unchanged |
| G4: Controlled migration and rapid rollback | Enable the new path through a default-off flag applied at process startup; rollback switches to legacy with a rolling restart and requires no migration or data repair |

## Success Metrics

| Metric | Baseline (current) | Target |
|---|---|---|
| Semantic parity on fixed React regression corpus | Phase 0 established current-state baselines; Phase 2 produces separate machine-readable comparisons | For serial deterministic scripts, 100% parity for output, history/dropped, error, usage, stable payloads, ordering, per-Run contiguous sequences, terminal position, and strict replay. For parallel tools, align sets and local partial order by call_id and canonicalize only the explicit paths in 03; absolute sequence numbers and global branch order need not match across paths |
| Coverage of React execution through registries and orchestrator | No new-path executions | 100% of enabled acceptance Runs use `react/native/v1` and the orchestrator; Worker never directly invokes a concrete Engine, and there is no client selection, latest, or silent fallback |
| Internal and open SSE compatibility | Phase 0 fixed Last-Event-ID, delta, tool.replay, and related baselines | Verify the rules in 03 for internal/Open SSE Last-Event-ID, after, draining beyond 200 events, no-ID delta non-replay, hidden tool.replay with cursor advancement, and public-field filtering, with no new private-metadata disclosure; preserve the R15 cursor-validation baseline: invalid/out-of-range manually parsed internal Last-Event-ID returns 400/invalid_last_event_id, typed type/range errors for internal after and Open after/Last-Event-ID return 422, and valid cursors continue to use max(after,last_id) with strict seq>after replay |
| Correctness of cancellation, timeout, and late-result protection | Phase 0 inventoried Repository/Worker behavior | 100% correct unique terminal states across cancellation races, run/model timeout, Lease lost, blocked producer/consumer, aclose, and append/emit failures; zero late-success overwrites and all owned tasks complete |
| New-path execution performance and stability | Requires a real environment and human review | Under 05 section 4, use the same environment/scripts for at least 30 matched pairs, exclude five warm-up pairs, and verify new-path nearest-rank p95 end-to-end latency increase ≤5% with zero additional errors; report raw latency separately rather than hiding it behind canonical diffs. Insufficient real external environments leave only the performance submetric `pending_env`; functional exit is independent and T9 is capped at conditionally passed |
| Rollback recovery | Phase 0 recorded existing deployment and recovery behavior | After flag-off and rolling restart, 100% of new Runs use legacy; existing queued/running/terminal rows remain readable, and mixed claims/in-flight Runs converge under existing rules, with no Alembic downgrade, data repair, or client change |
| Post-acceptance example reproducibility | No Phase 2-specific example seed exists | Only after development, testing, and formal acceptance, add idempotent, low-sensitivity, recognizably namespaced Phase 2 example seed data and validate it through quickstart default-off, explicit-on, embedded Worker, both SSE APIs, and off rollback; append actual outcomes only to 06/07 appendices |

## Scope

**Included**:
- A React Adapter based on Phase 1 contracts, open business-event mapping, safe error mapping, a private ack-aware stream, and ExecutionOutcome.
- Execution Orchestrator, synchronous ContextVar capture/reset scope, fixed `react/native/v1` selection, and a separate LocalTest Registry/selector.
- A final optional `orchestrator=None` Worker parameter, composition-root wiring, and a default-off global flag.
- Repository ownership of terminal states/durable events, plus internal/Open SSE, real Memory, error, cancellation, timeout, and Lease verification.
- Old/new parity regression, isolated PostgreSQL 17, mixed-Worker migration, and rollback exercises.
- **Post-acceptance** T10/T11 example seed creation and quickstart revalidation, with factual 06/07 appendices.

**Excluded** (later phases / explicitly not done):
- Changes to LangGraph inference, tool protocols, Memory business rules, or model Profile selection.
- Engine/Protocol fields in Agent configuration, Effective capability calculation, or configuration/policy snapshots; the formal identity model that removes the nil compatibility sentinel belongs to Phase 3.
- Runtime Host, external processes, Workspace, sandbox, credential broker, Codex/other Engines, Session Resume, or new human-approval capabilities.
- New Task/Execution tables, Lease Epoch/Fencing Token, transactional Outbox, new SSE replay protocols, or automatic retry.
- Any Alembic migration, ORM, public HTTP/SSE schema, or frontend code change; no new deployment service or UI.

## Risks and Constraints

- **Identity contamination**: `execution_id` remains a UUID and directly uses the claimed row ID. The Agent UUID must be parsed strictly from the real snapshot. Only a no-snapshot React Run using legacy base_runtime may use `UUID(int=0)` as an anonymous unbound internal sentinel; it must never enter queries, authorization, DB, HTTP/SSE, logs, metrics, or engine_metadata. Never borrow a Run/conversation UUID as Agent identity.
- **Adapter timing changes**: worker_emit and private runtime_emit must remain isolated; the first-emission gate stays closed until synchronous stream claim or explicit no-stream selection. The queue is bounded and distinguishes yield from private acknowledgment after successful worker_emit. A React no-stream collector explicitly selects private no-stream suppression rather than borrowing LocalTest semantics; an active stream applies backpressure, and terminal Result publishes only after producer completion with queued+in-flight undelivered=0.
- **Error-code and usage regression**: Common ExecutionError must not collapse original codes from any Phase 0 source or future unknown RuntimeFault. Unknown ordinary exceptions map publicly to internal_error and to legacy execution_error. usage is non-optional and never None; without aggregation input, React v1 public Result and private Outcome usage are both `{}`, neither an existing aggregate nor fabricated zero token counts.
- **Incomplete cancellation cleanup**: cancel, aclose, emit failure, and caller CancelledError must wake the first-emission gate/waiters, cancel and drain the runner, and suppress late success. Explicit Adapter cancellation uses first-terminal-wins, while Run persistence uses submission-order first-commit-wins; stale finish is a no-op whereas stale append raises CancelledError. Bounded cleanup is promised only for cooperative coroutines under an outer timeout, not forced termination of non-cooperative coroutines or reversal of tool side effects.
- **Inconsistent flags**: Mixed Workers may use different paths. The flag is excluded from the runtime-composition fingerprint, and enabled-path failure is explicit rather than silent fallback. `run_id` appears only in logs/traces and metrics remain low-cardinality.
- **Migration and evidence boundaries**: The read-only observation of `uv run --directory backend alembic heads` on 2026-11-10 was `0057_industry_pack_runtime (head)`; this is a baseline observation, not a constant. Tests must dynamically verify heads, empty-database upgrade, and zero migration-directory drift before and after. Phase 1 code merge is not human acceptance; Phase 2 06/07 are created only during actual T8/T9 execution.
