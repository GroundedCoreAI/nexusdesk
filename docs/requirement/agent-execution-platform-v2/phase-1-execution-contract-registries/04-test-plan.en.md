# Phase 1 · Execution Contracts and Registries — Test Plan

> Status: Design decisions frozen (R1–R11); local test and local automated acceptance evidence exists, the full suite and CI remain pending, and formal human acceptance/sign-off is incomplete
> Created: 2026-11-02; design frozen: 2026-11-08
> Revised: 2026-11-09 (R11 owned-task documentation clarification; no lifecycle behavior change)
> Basis: `02-requirements.en.md` (FR-1–FR-6, AC-1–AC-8), `03-technical-design.en.md` (contract v1, exact registration resolution, LocalTestAdapter, no migration), `08-implementation-breakdown.en.md` (R1–R11, T1–T8)

## 1. Test Scope and Principles

**Scope**: Six strict execution DTO groups, the safe error catalog, complete Adapter Protocol lifecycle, Engine/Protocol/Adapter registries, version/compatibility matrices, event high-water behavior, LocalTestAdapter, a structurally independent second Adapter, and zero-production-wiring verification.

**Principles**:

1. **Test the complete contract**: Three identity properties and all five methods—get_capabilities, start, stream_events, cancel, collect_result—have independent and combined assertions; both Adapters reuse the same suite.
2. **Test strict input**: Raw input is not trimmed, IDs/versions are not coerced, invalid Result combinations are only rejected rather than cleaned, and cross-object consistency is verified at the Adapter boundary.
3. **Test fail-closed behavior**: Unknown, duplicate, incompatible, and disabled configurations are rejected in fixed order; errors expose only the static catalog and restricted details.
4. **Test cancellation and terminal state**: Immediate/concurrent/repeated collection shares one terminal result; cancellation races and late events/success cannot change the first terminal state; no event is visible after the terminal Result is visible.
5. **Do not wait in time-based cases**: A manual fake clock/event gates construct timeout, long-running, and delay scenarios without real sleep deciding results.
6. **Test zero-wiring regression**: Prove that ContractModel, Worker/Factory/API, migrations, lockfile, and protected files remain unchanged.

## 2. Test Environments and Data Construction

| Environment | Purpose |
|---|---|
| Unit (pure memory) | DTOs, error catalog, capabilities, registries, version resolution, factory isolation, and dependency direction |
| Contract integration (two test Adapters) | Complete async lifecycle, cancellation races, error scenarios, and duplicate/conflicting/late events; no DB, network, model, or real process |
| Existing PG integration regression | Run `test_runtime_postgres.py` and related suites to confirm unchanged unwired behavior; use a dedicated `TEST_DATABASE_URL` |

**Data construction conventions**: Use fixed execution/tenant/agent IDs. LocalTest event IDs derive from execution_id+ordinal through UUIDv5, and timestamps use fixed epoch+ordinal. Attempt to inject `secret-marker` through raw exceptions, input/config/provider responses, and forbidden details keys; assert rejection or absence from safe output, and never place arbitrary text in valid details. After every async case, confirm that all owned tasks are awaited/done and no Adapter-owned or test-created pending task remains. Completed task references may be retained and checked with `all(done)`; the final task set need not be empty. A pre-execution empty-set assertion is a separate, independent condition.

The registration matrix contains at least independent Engine/Protocol records, two explicit Adapter versions, disabled entries, and undeclared combinations. The LocalTest tuple is `(local-test,scripted,v1)` and the second Adapter tuple is `(contract-probe,contract-scripted,v1)`.

## 3. Unit Tests

| ID | Case | Expected | Traceability |
|---|---|---|---|
| P1-UT-01 | Parameterized valid/missing/unknown/illegal version, ID, opaque string, timestamp, and state validation for all six models | Valid values remain verbatim; every invalid value raises ValidationError; strict mode rejects coercion and input is not trimmed | FR-1, AC-1 |
| P1-UT-02 | Mutate default config, metadata, artifacts, usage, payload, effective_capabilities, and other collections on two instances | No mutable default is shared and the other instance is unaffected | FR-1, AC-1 |
| P1-UT-03 | ExecutionKey, Adapter identity, and Event/Handle session consistency across Request/Handle/Result/Event | Standalone DTOs validate only themselves; mismatches are rejected at the Adapter boundary/common suite and never repaired | FR-1, FR-2 |
| P1-UT-04 | Positive/negative output/error combinations for all three Result terminal states | completed+error, failed without error/with output/with cancelled error, and cancelled with output or error directly raise ValidationError; valid artifacts/usage/engine_metadata are allowed in every state | FR-1, FR-2 |
| P1-UT-05 | Conversion for ten categories, every static-catalog code, read-only computed message, retryable, restricted details, and direct ExecutionError plus failed-Result-nested mapping/JSON round trips | Codes have unique category ownership; direct `model_validate(model_dump())`, direct `model_validate_json(model_dump_json())`, and nested mapping/JSON round trips succeed while preserving the safe model_dump; an exact catalog message is only a recomputed no-op token; arbitrary/mismatched/non-string message and message with missing/invalid code raise ValidationError and never override the computed property; exception/input/config/provider text and stacks never leak | FR-1, FR-4, AC-4, R9 |
| P1-UT-06 | Defaults and explicit declarations for all 11 EngineCapabilities | Undeclared items are strict false; declaring tool_calling changes no other capability or authorization, and non-booleans are rejected | FR-2, FR-4, AC-4 |
| P1-UT-07 | AgentEvent event_id, sequence, event_type, schema_version/source, UTC timestamp, and payload | Fields validate; standalone Event imposes no cross-event ordering, and wall-clock/random default factories are forbidden | FR-4 |
| P1-UT-08 | Independent Engine/Protocol/Adapter descriptor registration plus duplicate/reference checks | Engine/Protocol exist independently; identical and conflicting duplicates are rejected; unknown references fail; disabled records register but do not resolve | FR-3, AC-5 |
| P1-UT-09 | Valid tuple and two explicit-version resolutions; consecutive independent resolutions while objects remain live, singleton, A→B→A cycle, non-weak-referenceable candidate, dead-reference collection, address reuse, and custom `__eq__` | Exact factory instances are returned without latest; every resolution calls the factory again, two simultaneously live results differ by `is not`, and no state is shared; a second return of the same live singleton and the third A→B→A reuse fail with `configuration_error/adapter_contract_mismatch` without object escape; a non-weak-referenceable candidate fails before its first return; weakref/gc proves the registry does not strongly retain Adapters, dead references are pruned during resolution, later new objects are unaffected by address reuse, and identity never uses bare `id()`; arbitrary `__eq__` is never invoked | FR-3, AC-5, R10 |
| P1-UT-10 | Unknown/disabled Engine and Protocol, undeclared pair, alternate version, and disabled Adapter resolution | Stable codes follow exactly unknown_engine→engine_disabled→unknown_protocol→protocol_disabled→incompatible_engine_protocol→unknown_adapter_version→adapter_disabled | FR-3, FR-4, AC-6 |
| P1-UT-11 | Factory exception, identity/version mismatch, missing Protocol methods, wrong lifecycle bound-signature arity, awaitable rejection/cleanup for a Future/Task-returning factory, and a separate `BaseException` boundary | The first three map respectively to adapter_factory_failed, adapter_identity_mismatch, and adapter_contract_mismatch; use `Signature.bind` placeholders on bound methods without executing them, binding zero arguments for `get_capabilities` and one for each of the other four methods, with wrong arity mapping to adapter_contract_mismatch; no instance escapes before checks; synchronous resolve rejects a factory-returned Future/Task with adapter_contract_mismatch and cancels the returned Future/Task as cleanup, asserting `future.cancelled()` and additionally awaiting any Task fixture through cleanup with no pending task; a separate boundary case proves `CancelledError`/other `BaseException` control flow is neither swallowed nor rewritten and is asserted independently from Future/Task cleanup; diagnostics contain no sensitive config or raw exception text | FR-3, AC-6, R3/R5/R10 |
| P1-UT-12 | Static dependency-direction checks for contracts, Registry, LocalTestAdapter, and package entry points, added incrementally as T2 contracts/package entry points→T3 Registry→T4 LocalTestAdapter/no-eager-test-import, then rerun completely in T6 | Contracts do not import Registry/Worker/Repository/Factory/concrete Engines; Registry imports no concrete Adapter; LocalTestAdapter imports no Registry; entry points do not eagerly import test Adapters; existing ContractModel has zero diff; a module scheduled for the current task must fail if absent rather than skip or pass because it is absent, and the complete item exists only at T4 | FR-6, G1 |

## 4. Contract and Integration Tests

| ID | Case | Expected | Traceability |
|---|---|---|---|
| P1-IT-01 | Success through capabilities→start→stream→collect; cover immediate/concurrent/repeated collect after start, a second start, a concurrent second consumer after the first stream consumer is validly created, and a sequential second consumer after the first iterator `aclose()` | Five methods and identity properties work, LocalTest sequences are contiguous, and every collection returns an equal completed Result; second start and both second-consumer attempts fail with `configuration_error/invalid_adapter_state`, with no stream replay/restart | AC-2, FR-2 |
| P1-IT-02 | Multi-event streaming and empty-event scenarios | Multiple events retain order/payload; an empty stream produces a valid terminal result without hanging | FR-2, AC-2 |
| P1-IT-03 | Invalid scenario before start, Request tuple mismatch, and pre-start EngineUnavailable/ResourceExhausted | Every case fails before a valid Handle with the correct category; only explicitly pre-start EngineUnavailable and ResourceExhausted may be retryable, post-start failures and timeout default to False, and Phase 1 does not retry | FR-2, FR-5, AC-4 |
| P1-IT-04 | Parameterized ConfigurationError, ProtocolError, AuthenticationError, and PermissionDenied scenarios | Each maps to static category/code/message/retryable; Registry/Adapter boundaries copy neither raw Pydantic values nor exception strings | AC-4, FR-4 |
| P1-IT-05 | WorkspaceError, InternalError, unknown Exception, and simulated process failure | Unknown exceptions map only to internal_error/internal_error; simulated failure is internal_error/simulated_process_failure; process_id is None and no real Host behavior is asserted | AC-4, AC-7, FR-5 |
| P1-IT-06 | Manual fake clock triggers built-in TimeoutError | Waiters wake without real waiting and receive failed + timeout/execution_timeout; no automatic retry, and post-start timeout defaults to non-retryable | AC-7, FR-4 |
| P1-IT-07 | Start long-running scenario, repeat/run cancel concurrently, then collect results/events concurrently | cancel is idempotent, gates release and the stream closes, every collection returns an equal cancelled Result (error=None), and owned/test tasks are cleaned up | AC-3, FR-2 |
| P1-IT-08 | Separately control cancellation-first and success-first races, then inject late success/events | The first terminal state wins atomically; cancel after success is a no-op and success after cancellation is suppressed; no event is visible after the terminal Result and no second terminal state exists | AC-3, FR-2 |
| P1-IT-09 | Exact duplicate, same event_id with different content, low sequence under a new event_id, valid gaps, and early aclose | Full duplicates and late events yield unchanged without advancing/lowering the mark; content conflict is event_identity_conflict; gaps are valid; timestamp does not order; iterator close leaves no pending task | AC-7, FR-4 |
| P1-IT-10 | Register second Adapter `(contract-probe,contract-scripted,v1)` and reuse the complete common success, empty/multi-event, error, cancellation, duplicate/late, idempotent collection, and cleanup suite | The second Adapter is structurally independent and not a LocalTestAdapter subclass; the suite imports no concrete LocalTest types; common contracts, Registry interfaces, and Worker need no changes | AC-5, G1, G2 |
| P1-IT-11 | Repeat every LocalTestAdapter scenario for at least two rounds, including stream failure/collector cancellation | Semantics, errors, and scripts are deterministic without cross-scenario state; after success/failure/cancel/timeout/iterator close all owned tasks are awaited/done and no Adapter-owned or test-created pending task remains; completed task references may be retained and checked with `all(done)`, while the pre-execution empty-set assertion remains separate | AC-7, FR-5, R11 |

## 5. General Checks (Applicable to This Phase)

| ID | Check | Pass criterion | Traceability |
|---|---|---|---|
| P1-CM-01 | Database migrations unchanged | `alembic heads` is `0057_industry_pack_runtime`; no version file added/modified relative to `4dfcfb41e9cbb799753986c2d76134514bbd19be`, and no downgrade is required | AC-8, G4 |
| P1-CM-02 | Zero production wiring and configuration unchanged | Worker/Factory/composition do not call the new path; no new runtime flag, Settings, external Engine, credential, frontend, or deploy change | AC-8, FR-6 |
| P1-CM-03 | Public API/SSE/Run contract compatibility | RunRequest/RunSnapshot/RunStatus, event names, and routes unchanged; relevant existing Runtime/API/SSE tests are green | AC-8, FR-6 |
| P1-CM-04 | Sensitive information and logs | DTO/registry/Adapter safe output contains no secret-marker, credential, connection string, raw Pydantic values, raw exception text, raw stack, or customer input | AC-4, non-functional |
| P1-CM-05 | Tenant and instance boundaries | Registries never rewrite tenant_id; different requests/resolved instances show no shared state; event high-water exists only per active execution | FR-1, FR-3, non-functional |
| P1-CM-06 | Code quality and dependency boundaries | New tests plus `ruff check src tests`, affected-file `ruff format --check`, and `test_core_boundaries.py` are green; R8 dependency direction holds and `backend/uv.lock` has zero diff | FR-6, G1 |

## 6. Regression Scope

- `backend/tests/test_runtime_engine.py`: ReAct inference, tool loop, budgets, errors, and cancellation remain unchanged.
- `backend/tests/test_runtime_postgres.py`: Queue, lease, terminal state, event replay, and HTTP/SSE behavior remain unchanged.
- `backend/tests/test_open_platform.py`, `test_extension_contracts.py`: Public streams, ContractModel, and existing Run/Extension ports remain unchanged.
- `backend/tests/test_runtime_baseline.py`, `test_core_boundaries.py`: Phase 0 baseline and architecture boundaries remain valid.
- Run at least affected existing Agent snapshot, model Profile, and Memory tests; the unwired packages must cause no behavioral difference.

## 7. Defect Severity and Exit Criteria

| Severity | Definition | Handling |
|---|---|---|
| P0 blocker | Existing Run flow broken; data loss; cross-tenant or credential disclosure | Fix and run full regression before continuing |
| P1 severe | Lifecycle/terminal-state error; cancellation failure; incorrect resolution fallback; common contract blocks independent Adapters; event identity conflict repaired | Must be fixed before acceptance |
| P2 normal | Non-critical diagnostics, test determinism, or error-category deviation without production impact | May be accepted with a recorded issue and product sign-off |
| P3 minor | Documentation, naming, or non-sensitive log issue | Schedule a fix |

**Exit criteria**: Every P1-UT/IT/CM item is actually executed and passes; AC-1–AC-8 reproduce successfully; affected existing regression is green; no open P0/P1; no production behavioral diff, migration/lockfile change, or dangling async task. The full suite remains a CI responsibility under repository convention, and unrun local or CI items must not be recorded as passed.
