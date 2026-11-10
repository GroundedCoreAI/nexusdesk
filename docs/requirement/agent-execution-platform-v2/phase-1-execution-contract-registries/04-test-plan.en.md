# Phase 1 · Execution Contracts and Registries — Test Plan

> Status: Pending review / Pending implementation
> Created: 2026-11-02
> Basis: `02-requirements.md` (FR-1–FR-6, AC-1–AC-8), `03-technical-design.md` (contract v1, exact registration resolution, LocalTestAdapter, no migration)

## 1. Test Scope and Principles

**Scope**: Six execution DTO groups, the complete Adapter Protocol lifecycle, Engine/Protocol/Adapter registries, version and compatibility matrices, error/event/cancellation semantics, LocalTestAdapter, and verification of zero production wiring.

**Principles**:

1. **Test the complete contract**: Three identity properties and all five methods—get_capabilities, start, stream_events, cancel, collect_result—have independent and combined assertions.
2. **Test fail-closed behavior**: Unknown, conflicting, incompatible, and disabled configurations never fall back to another implementation; errors expose no sensitive text.
3. **Test cancellation and late results**: Cancellation is idempotent, and late events/success after cancellation or a terminal state cannot change the logical result.
4. **Do not wait in time-based cases**: Test clocks/event gates construct timeout, long-running, and delay scenarios without real long sleeps.
5. **Test zero-wiring regression**: This phase has no production flag and must prove Worker/Factory/API and migrations remain unchanged.

## 2. Test Environments and Data Construction

| Environment | Purpose |
|---|---|
| Unit (pure memory) | DTOs, errors, capabilities, registries, version resolution, factory isolation, and event rules |
| Contract integration (LocalTestAdapter) | Complete async lifecycle, cancellation races, error scenarios, and duplicate/late events; no DB, network, model, or real process |
| Existing PG integration regression | Run `test_runtime_postgres.py` and related suites to confirm unchanged unwired behavior; use a dedicated `TEST_DATABASE_URL` |

**Data construction conventions**: Use fixed execution/tenant/agent IDs and event scripts; put `secret-marker` in error details to verify redaction; check for no pending task after every async case. The registration matrix includes at least one Engine, two Protocols, two Adapter versions, and undeclared combinations.

## 3. Unit Tests

| ID | Case | Expected | Traceability |
|---|---|---|---|
| P1-UT-01 | Parameterized valid payload and missing/unknown/illegal-state validation for all six models | Valid values preserve versions and IDs; every invalid value raises ValidationError | FR-1, AC-1 |
| P1-UT-02 | Mutate default config, metadata, artifacts, usage, payload, and capabilities collections on two instances | No mutable default is shared and the other instance is unaffected | FR-1, AC-1 |
| P1-UT-03 | execution_id and tuple consistency across Request/Handle/Result/Event | Mismatched identity cannot form a valid lifecycle; public Handle exposure follows the public API constraint | FR-1, FR-2 |
| P1-UT-04 | Result state and output/error combination validation | completed+error, failed without error, and cancelled with late-success output are rejected or normalization refuses them | FR-1, FR-2 |
| P1-UT-05 | category/code/retryable/details conversion for all ten ExecutionError types | Categories are complete and stable; secret-marker, stacks, and raw input never enter safe messages | FR-4, AC-4 |
| P1-UT-06 | EngineCapabilities defaults and explicit declarations | Undeclared items are false; declaring tool_calling does not change other capabilities or authorization | FR-2, FR-4, AC-4 |
| P1-UT-07 | AgentEvent unique event_id, monotonic sequence, and schema_version/source validation | Ordering/version are valid; duplicate event_id is identifiable and not silently discarded by this layer | FR-4 |
| P1-UT-08 | Independent Engine and Protocol registration and descriptor validation | Both record types exist independently; empty IDs, illegal versions, and conflicting duplicates are rejected | FR-3, AC-5 |
| P1-UT-09 | Valid tuple and two explicit-version resolutions | Exact factory instances are returned without latest; consecutive resolutions share no instance state | FR-3, AC-5 |
| P1-UT-10 | Unknown Engine/Protocol/version, undeclared combination, and disabled record resolution | Every case returns a stable ConfigurationError code without fallback | FR-3, FR-4, AC-6 |
| P1-UT-11 | Adapter factory identity/version differs from registration | The instance is rejected and not leaked to the caller; diagnostics contain no sensitive config | FR-3, AC-6 |
| P1-UT-12 | Static dependency-direction check for common contracts | contracts/registry do not import Worker, Repository, Factory, or a concrete Engine | FR-6, G1 |

## 4. Contract and Integration Tests

| ID | Case | Expected | Traceability |
|---|---|---|---|
| P1-IT-01 | Success scenario through capabilities→start→stream→collect | Five methods and identity properties work, event sequences are contiguous, result is completed, and output/usage match the script | AC-2, FR-2 |
| P1-IT-02 | Multi-event streaming and empty-event scenarios | Multiple events retain order/payload; an empty stream can produce a valid terminal result without hanging | FR-2, AC-2 |
| P1-IT-03 | Invalid scenario before start and EngineUnavailable during start | Invalid configuration/unavailable Engine fails before a valid Handle, with the correct category | FR-2, FR-5, AC-4 |
| P1-IT-04 | Parameterized ConfigurationError, ProtocolError, AuthenticationError, and PermissionDenied scenarios | Each maps to stable category/code/retryable with no credential or raw customer-input disclosure | AC-4, FR-4 |
| P1-IT-05 | ResourceExhausted, WorkspaceError, InternalError, and simulated process failure | Each has deterministic failed/error semantics; simulated process failure is not represented as real Host testing | AC-4, AC-7, FR-5 |
| P1-IT-06 | Test clock triggers Timeout | Timeout occurs without real waiting; no automatic retry and no claim of absent side effects | AC-7, FR-4 |
| P1-IT-07 | Start long-running scenario, cancel twice, then collect | cancel is idempotent, the stream closes promptly, result is cancelled, and all tasks are cleaned up | AC-3, FR-2 |
| P1-IT-08 | Race cancel against success, then inject late success/events | cancelled is not overwritten, no valid new event follows cancellation, and no second terminal state appears | AC-3, FR-2 |
| P1-IT-09 | Duplicate event_id and out-of-order/late sequence scenarios | The contract layer preserves anomalies for upper-layer detection without claiming persistent deduplication; tests finish deterministically | AC-7, FR-4 |
| P1-IT-10 | Add a test-only Engine/Protocol/Adapter and reuse the entire contract suite | Registration and suite passage require no common-contract or Worker modification | AC-5, G1, G2 |
| P1-IT-11 | Repeat every LocalTestAdapter scenario for at least two rounds | Semantics, errors, and event scripts are deterministic with no cross-scenario state or dangling tasks | AC-7, FR-5 |

## 5. General Checks (Applicable to This Phase)

| ID | Check | Pass criterion | Traceability |
|---|---|---|---|
| P1-CM-01 | Database migrations unchanged | Alembic head equals the actual target value recorded at implementation entry; no version file added/modified and no downgrade required | AC-8, G4 |
| P1-CM-02 | Zero production wiring and configuration unchanged | Worker/Factory/composition do not call the new path; no new runtime flag; legacy path remains the only path | AC-8, FR-6 |
| P1-CM-03 | Public API/SSE/Run contract compatibility | RunRequest/RunSnapshot/RunStatus, event names, and routes unchanged; relevant existing tests are green | AC-8, FR-6 |
| P1-CM-04 | Sensitive information and logs | DTO/registry/Adapter error output contains no secret-marker, credential, connection string, raw stack, or customer input | AC-4, non-functional |
| P1-CM-05 | Tenant and instance boundaries | Registries never rewrite tenant_id; different requests/resolved instances show no shared state | FR-1, FR-3, non-functional |
| P1-CM-06 | Code quality and dependency boundaries | Affected backend ruff/pytest checks are green; contracts/registry have no application-layer or concrete-Engine reverse dependency | FR-6, G1 |

## 6. Regression Scope

- `backend/tests/test_runtime_engine.py`: ReAct inference, tool loop, budgets, errors, and cancellation remain unchanged.
- `backend/tests/test_runtime_postgres.py`: Queue, lease, terminal state, event replay, and HTTP/SSE behavior remain unchanged.
- `backend/tests/test_open_platform.py`, `test_extension_contracts.py`: Public streams and existing Run/Extension ports remain unchanged.
- Run at least affected existing Agent snapshot, model Profile, and Memory tests; the unwired packages must cause no behavioral difference.

## 7. Defect Severity and Exit Criteria

| Severity | Definition | Handling |
|---|---|---|
| P0 blocker | Existing Run flow broken; data loss; cross-tenant or credential disclosure | Fix and run full regression before continuing |
| P1 severe | Lifecycle/terminal-state error; cancellation failure; incorrect resolution fallback; common contract blocks independent Adapters | Must be fixed before acceptance |
| P2 normal | Non-critical diagnostics, test determinism, or error-category deviation without production impact | May be accepted with a recorded issue and product sign-off |
| P3 minor | Documentation, naming, or non-sensitive log issue | Schedule a fix |

**Exit criteria**: All P1-UT/IT/CM pass; AC-1–AC-8 reproduce successfully; affected existing regression is green; no open P0/P1; no production behavioral diff, migration change, or dangling async task.
