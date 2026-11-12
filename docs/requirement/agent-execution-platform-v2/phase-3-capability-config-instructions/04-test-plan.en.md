# Phase 3 · Capabilities, Configuration, and Instructions — Test Plan

> Status: Pending implementation (execute after development; no test results currently exist)
> Created: 2026-11-02
> Revised: 2026-11-11 (lightweight small-team acceptance: reuse automated evidence and remove multi-role sign-off requirements)
> Basis: `02-requirements.md` (FR-1–FR-9, AC-1–AC-11), `03-technical-design.md` (compatibility layer, capability resolution, snapshot barrier, Instruction Provider, rollback)

## 1. Test Scope and Principles

**Scope**: AgentConfig compatibility and typed configuration, Registry integration, Declared/Available/Policy/Effective, read-only preview, Run snapshots, Instruction Providers, React Summary/Memory compatibility, migration `0053`, flags, and rollback.

**Principles**:

1. **Baseline first**: current behavior comes from Phase 0 measurements; until available, mark it “pending Phase 0” rather than deriving expectations from the new implementation.
2. **Flag fallback is mandatory**: with the master flag off, React matches Phase 2 point by point and non-React is rejected rather than switched to another Engine.
3. **Empty-state regression is mandatory**: historical NULL snapshots, missing Engine fields, and absent Summary/Memory retain explicit semantics.
4. **Malicious input is mandatory**: forged capabilities/policy, extra fields, cross-tenant access, sensitive snapshots, and oversized input require adversarial cases, not only happy paths.
5. **Failure paths are mandatory**: probe timeout, unknown policy, persistence failure, and pre-start failure all fail closed without partially authorized execution.
6. **No real waits in time-based cases**: use fake clocks, direct database setup, or controlled doubles for probe expiry, cache invalidation, and Run timeout.
7. **Side-effect-free replay**: snapshot-decision replay reads data only and never recalls real models, tools, or external Engines.
8. **Reuse evidence**: A/C acceptance directly references automated UT/IT/CM results and CI/database evidence instead of manually repeating the full suite; manual work is limited to key checks that cannot be automated.

## 2. Test Environments and Data Setup

| Environment | Purpose |
|---|---|
| Pure unit tests | Configuration mapping, schemas, capability intersection, policy narrowing, snapshot validation, and instruction rendering without a DB |
| Integration (dedicated PostgreSQL + pytest fixtures) | Draft/publication/Run/snapshot flows, cross-tenant access, concurrent reads/writes, cancellation, and failure |
| Phase 1 LocalTestAdapter + Phase 2 test Orchestrator | Declarations, start barrier, events, and terminal states without an external Engine |
| Mock/demo model and MemoryInjection doubles | Programmable React responses, Summary/Memory ordering, and existing rendering compatibility |
| Disposable migration database | Upgrade from the actual predecessor, old/new rows, concurrency, and downgrade; never connect to production |
| Frontend typecheck/i18n/component tests | Typed forms, read-only capability view, errors, and language resources |

**Data setup**: use authorized redacted Phase 0 fixtures and versioned samples; construct two tenants and multiple business/workspace scopes. Use deterministic doubles for declarations, probes, policy, and Providers. Inject snapshot persistence failure before the Adapter mock; construct cancellation/timeout through Repository state and fake clocks. Each test cleans its Runs, versions, and audits independently and shares no mutable policy.

## 3. Unit Tests

| ID | Case | Expected result | Traceability |
|---|---|---|---|
| P3-UT-01 | Normalize legacy configuration without `engine/react` | Produces `react/native/v1`, preserves legacy model/rounds/shared values, and does not mutate input | FR-1; AC-1 |
| P3-UT-02 | Equal old and new React aliases | Accepts and emits one canonical value with no duplicate source | FR-1, FR-2; AC-1, AC-2 |
| P3-UT-03 | Unequal old and new React aliases | Rejects explicitly and identifies the conflict without silently choosing | FR-2; AC-2 |
| P3-UT-04 | Unknown triple, latest, extra fields, and unrestricted configuration dictionary | Rejects all without bypassing the Registry | FR-2; AC-2 |
| P3-UT-05 | Profile ID/version alone, rounds out of bounds, unknown/duplicate disabled capabilities | Rejects or deduplicates under strict rules without widening bounds | FR-2, FR-4; AC-2 |
| P3-UT-06 | Declared=true with missing deployment or incompatible version | Available=false with a stable reason code; Declared remains unchanged | FR-3; AC-3 |
| P3-UT-07 | Probe timeout, exception, and cache hit/invalidation | Bounded unavailable result; complete cache keys, declaration changes invalidate old values, and no raw exception leaks | FR-3; AC-3 |
| P3-UT-08 | `workspace_required=true` without Workspace | Available=false and missing required capability blocks start | FR-3; AC-3 |
| P3-UT-09 | Lower-layer allow after platform/tenant/Agent/Execution denial | Effective=false, all decisions are recorded, and monotonicity holds | FR-4; AC-4 |
| P3-UT-10 | Unknown capability, unknown policy version, and missing policy source | Never defaults to authorization; rejects under least privilege or configuration error | FR-4; AC-4 |
| P3-UT-11 | Forge Declared/Available/Effective in ExecutionRequest input | Strict rejection and no client capability values in the server object | FR-5; AC-5 |
| P3-UT-12 | Tenant/actor differs from authenticated context | Ignores request identity fields, uses trusted context, and records the authorization error | FR-5; AC-5 |
| P3-UT-13 | Snapshot missing required fields, unserializable, or oversized | Validation fails and the start barrier remains closed | FR-6; AC-6 |
| P3-UT-14 | Nested token, API key, raw Memory, or host path in a snapshot | Rejects before persistence; logs and errors contain no sensitive plaintext | FR-6; AC-6 |
| P3-UT-15 | Repeat snapshot serialization and replay decisions | Stable keys/versions/reasons and read-only replay with no snapshot mutation | FR-6; AC-6 |
| P3-UT-16 | Empty/disabled React Summary and Memory | No empty messages; sequence matches the Phase 0 baseline | FR-7; AC-7 |
| P3-UT-17 | Summary, Memory, combined, and history truncation | System→Summary→Memory→history→user ordering and wording match exactly | FR-7; AC-7 |
| P3-UT-18 | Test Provider uses a different format | Business rendering runs once and native format is not forced into ReAct | FR-7; AC-8 |
| P3-UT-19 | Unknown Provider, duplicate context, or rendering-contract error | Explicit failure before start with no fallback to another Provider | FR-7; AC-7, AC-8 |
| P3-UT-20 | FR-9 settings defaults, environment overrides, and invalid bounds | Off by default, overrides work, and invalid timeout/cache/size values are rejected | FR-9; AC-10 |

## 4. Integration Tests

| ID | Case | Expected result | Traceability |
|---|---|---|---|
| P3-IT-01 | Load legacy draft → read without edits → normal edit/publication → React Run | No UPDATE to historical JSONB; new version is normalized; execution matches the Phase 0 baseline | AC-1; FR-1, FR-2 |
| P3-IT-02 | Publish valid new configuration and unknown/unavailable configuration | Valid input resolves exactly; invalid input is rejected before publication or admission, with no Adapter start | AC-2; FR-2 |
| P3-IT-03 | Execute through combined declarations, environment probes, and layered policy | All five data sets agree, Effective contains only capabilities allowed by every layer, and UI/Run share the resolver | AC-3, AC-4; FR-3, FR-4 |
| P3-IT-04 | Inject forged capabilities, policy, and host fields into Run/Agent/preview APIs | 4xx/domain errors, zero elevations, and complete security audits without sensitive plaintext | AC-5; FR-5 |
| P3-IT-05 | Tenant B reads tenant A configuration, preview, Run snapshots, and audits | All are unreachable; query isolation is not replaced by merely hiding fields | AC-5; FR-5 |
| P3-IT-06 | Inspect pre-start snapshots for a completed Run | Five columns are non-null with complete versions, start follows snapshot commit, and snapshots are immutable | AC-6; FR-6 |
| P3-IT-07 | Inspect snapshots after Adapter failure, user cancellation, and timeout | Original snapshots and correct existing terminal states remain; late results overwrite neither cancellation nor snapshots | AC-6; FR-6 |
| P3-IT-08 | Inject snapshot serialization/DB write failure | Run fails closed, Adapter.start count is zero, and no partial ExecutionRequest exists | AC-6; FR-6 |
| P3-IT-09 | Exercise Summary/Memory/switches/completion write-back through real MemoryInjection test adapters | Wording, order, budgets, logs, and write-back have zero diff from the Phase 0 baseline | AC-7; FR-7 |
| P3-IT-10 | Render the same context through React and test Engine Providers | Formats remain independent, rendering runs once, and native formats do not break public Run events | AC-8; FR-7 |
| P3-IT-11 | Change platform/tenant policy after preview, then execute | Preview is read-only; execution recomputes without reusing old authorization, and reason codes update | AC-4, AC-9; FR-4, FR-8 |
| P3-IT-12 | Execute legacy React with the master flag off and compare events/API/SSE | Phase 2 behavior matches, five columns are NULL, and no Phase 3 probes or snapshot side effects occur | AC-10; FR-8, FR-9 |
| P3-IT-13 | Execute non-React with the master flag off | Returns `execution_phase3_disabled`, React Adapter call count is zero, and historical snapshots remain readable | AC-10; FR-8, FR-9 |
| P3-IT-14 | Migrate from the actual predecessor and read/write old and new Runs concurrently | Exactly five columns are added, old rows are NULL, new rows are writable, and existing Repository statements are unblocked | AC-11; FR-6 |
| P3-IT-15 | Roll application back to the Phase 2 binary without downgrade | New nullable columns do not obstruct old code, React works, and history remains intact | AC-10, AC-11; FR-8 |
| P3-IT-16 | Validate old/new React configuration through Model Gateway and tools | Profile/version/authorization/Run correlation are unchanged, generic config cannot bypass them, and no keys enter snapshots | AC-1, AC-2, AC-6; FR-2, FR-6 |

## 5. General Checks (Applicable to This Phase)

| ID | Check | Pass standard | Traceability |
|---|---|---|---|
| P3-CM-01 | Online migration and numbering | Revalidate head/down_revision before implementation; add only five columns, no backfill/history edits; paired disposable downgrade | AC-11; FR-6 |
| P3-CM-02 | Configuration loading | Defaults, environment overrides, invalid bounds, and cache invalidation meet FR-9; sample files contain no secrets | AC-10; FR-9 |
| P3-CM-03 | Audit and observability | Engine/provider/policy versions and reason codes are complete; logs/events/audits contain no tokens, raw Memory, or host details | AC-5, AC-6; FR-5, FR-6 |
| P3-CM-04 | Tenant and scope isolation | Configuration, previews, snapshots, policy, and audits are isolated by tenant and business/workspace scope | AC-5; FR-5 |
| P3-CM-05 | Historical compatibility | 100% of valid Phase 0 fixtures pass as decided; original JSONB is not bulk-rewritten and failed fixtures have legacy-defect records | AC-1; FR-1 |
| P3-CM-06 | Snapshot immutability and null semantics | Persist before start and never update; do not invent backfills for historical NULLs or expose snapshots directly through public APIs | AC-6; FR-6 |
| P3-CM-07 | Capability authorization boundary | Declared/Available/Effective are never client authorization sources; lower layers cannot reverse an earlier denial | AC-3–AC-5; FR-3–FR-5 |
| P3-CM-08 | Frontend i18n and read-only view | No hardcoded user text, supported-language checks pass, and Effective has no edit/submission path | AC-9; FR-8 |
| P3-CM-09 | Full rollback | Flag and application rollback need no migration change; non-React never falls back, and snapshots/history remain intact | AC-10; FR-8, FR-9 |
| P3-CM-10 | Phase boundaries | No real Host/Workdir/Sandbox, Codex, general policy console, or automatic cross-Engine fallback | AC-2, AC-10; FR-2, FR-8 |

## 6. Regression Scope

- Phase 0 locked RuntimeEngine, Worker, Repository, cancellation/lease-loss/timeout, Run API, and SSE baselines; if Phase 0 has no measured result, the corresponding compatibility conclusion remains blocking and is not marked passed.
- Existing `test_runtime_engine.py`, `test_runtime_postgres.py`, Agent configuration/publication/rollback, Model Gateway, tools, and knowledge-access tests.
- Summary/Memory configuration, injection, fallback, injection-log, and completion-dispatch tests; compare message content, ordering, and switches individually.
- Frontend Agent edit/diff/publication, typecheck, `check:i18n`, and build; backend ruff and affected pytest locally, with the full suite in CI.
- After migration, test old-code compatibility and new-code null handling; never alter historical fixtures to hide existing invalid samples.

## 7. Defect Severity and Exit Criteria

| Severity | Definition | Handling |
|---|---|---|
| P0 blocking | Client/Adapter elevation, cross-tenant disclosure, secrets in snapshots, unauthorized Adapter start, or data loss | Stop acceptance immediately; fix and rerun all security and compatibility suites |
| P1 critical | Legacy incompatibility, incorrect Effective resolution, missing snapshots, Summary/Memory regression, or broken flag/non-React rejection | Must be fixed before acceptance |
| P2 major | Non-blocking reason-code, preview, performance-target, or general quality deviation | Only for non-hard-gate items without security/compatibility impact: record owner/deadline and have the acceptance owner confirm conditional acceptance in the single acceptance record |
| P3 minor | Wording, non-sensitive logging, or display issues | Schedule a fix; never use this level to hide hardcoded i18n or disclosure |

**Exit criteria**: all P3-UT/IT/CM pass; AC-1–AC-11 reproduce; applicable regressions are green; no open P0/P1; zero elevations or cross-tenant successes; snapshot coverage and sensitive scans meet targets; flag-off behavior has zero diff from Phase 2. Mark unavailable environments `pending_env` and block the corresponding launch claim rather than recording a pass.
