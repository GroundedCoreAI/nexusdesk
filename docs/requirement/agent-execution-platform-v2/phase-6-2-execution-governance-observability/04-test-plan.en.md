# Phase 6-2 · Execution Governance Observability — Test Plan

> Status: Approved documentation-scope baseline for subsequent testing; not implemented, not tested, not accepted. This document describes only how testing will be conducted and contains no conclusion that anything has been executed, passed, or accepted.
> Created: 2026-11-22
> Basis: Phase 6 `02-requirements.md` FR-16 (operability); this phase's `02-requirements.md` (FR-1–FR-10, AC-1–AC-10), `03-technical-design.md`, and `08-implementation-breakdown.md` (T-1–T-14, R-1–R-10, UT-1–UT-14, IT-1–IT-8, FE-1–FE-10, CM-1–CM-6); frozen SIG-1–SIG-8 classifications from the approved scope baseline.
> Scope note: The test object is limited to the unified governance query API and visual UI. Execution semantics are not under test, no real untrusted execution environment is invoked, and no Prometheus or new monitoring dependency is introduced. All IDs, table names, fields, routes, and migration numbers follow the baseline; `0072` / `0073` are planning values and require a fresh single-head recheck before implementation.

## 1. Test Strategy

1. **Determinism first**: Every assertion is based on controllable clocks, fixed canaries, and deterministic fixtures; real-time sleeps or real network outcomes are never used as verdicts. Pagination, retention-lag seconds, and 24-hour counts are constructed from controlled timestamps and fixed row counts.
2. **PG shard isolation**: Integration tests run in shards, each with its own disposable database/schema loaded with real migration artifacts and real table data. Each shard can be replayed independently, and no mutable state is shared across shards. At least two tenants and multiple Runs cover JOINs and scope filtering.
3. **Playwright mock harness**: Frontend cases inject governance responses and admin/ordinary-user roles through a route-interception mock harness, without depending on a real backend or untrusted execution environment. Assertions cover whether requests are issued, tab visibility, mount timing, and the rendering of all eight panel types.
4. **No dependency on a real untrusted execution environment**: This stage does not perform real sandbox escapes, network attacks, fault injection, or real multi-Worker crashes. Governance signals are produced by deterministic data and controlled write points. Adversarial/fault validation that requires a genuinely untrusted environment is outside this stage's test scope (see Section 8).
5. **Permissions and tenant isolation come first**: For every governance endpoint, assert first that all non-admin callers receive 403 `insufficient_role`, then assert tenant/business_scope/workspace filtering. Tables without `tenant_id` always JOIN `runtime_runs` (by run_id) to obtain tenant/scope; orphan rows are labeled deployment-level.
6. **Zero tolerance for Secrets**: Every governance response, error, and diagnostic case injects a canary and asserts zero occurrences. Raw parser samples never enter any frontend model or assertion output; only category counts and bounded, redacted reason codes are verified.
7. **Dynamic migration-number recheck**: `0072` / `0073` are planning values and may be written into cases only after the head recheck passes. If the actual head differs, register an R-n ruling and update both language versions per R-5, then rerun against the actual numbers; never hard-code planning numbers into a passing verdict.
8. **No pre-written reports**: This plan does not generate `06-test-report.md` or `07-acceptance-report.md`; they are created only after testing and acceptance are actually performed. No issue or PR number is registered.

## 2. Test Environments and Data Construction

| Environment | Purpose | Key constraints |
|---|---|---|
| Unit (no DB) | Endpoint query semantics, permission denial, filter/pagination parsing, Secret canaries, error codes, and 409 branch logic | pytest with mocked services / controllable clock; zero real I/O |
| PG integration (sharded) | Migration upgrade, real table data, tenant JOIN / scope isolation, 409 gap persistence, parser sink persistence, concurrent unique constraints | One disposable database/schema per shard; real migrations `0070` / `0071` plus planned `0072` / `0073`; at least two tenants and multiple Runs |
| Playwright mock harness | Tab visibility, admin gating, on-demand mounting, eight panels, filtering/pagination, empty states, four locales | Route interception injects responses and roles; no real backend connection |
| Static checks | ruff / architecture, check:i18n, typecheck, build, single-head uniqueness, no Prometheus dependency | Executed locally or in CI; head-check result must be recorded |

**Data construction conventions**: Governance rows are built from real table-structure fixtures. Where `execution_fencing_denials` / `runtime_event_outbox` carry no tenant, associate them through `runtime_runs`. Construct orphan run_ids, cross-tenant Runs, pagination boundaries, duplicate `source_event_id` values, `supersedes_id` chains, all five parser categories, and Secret canaries. Never commit real keys; canaries must be revocable. If the PG or head-recheck environment is unavailable, mark the affected cases `pending_env`; a mock may not substitute for a hard gate.

## 3. Backend Unit Tests UT-1–UT-14

| ID | Case | Expected | Environment | Traceability |
|---|---|---|---|---|
| UT-1 | Governance route skeleton permission denial: call all `/observability/execution/*` endpoints as admin / Reader / ordinary user | Only admin receives data; all non-admin callers receive 403 `insufficient_role`; invalid filters/pagination return 400; error codes are uniform | Unit (no DB) | FR-1; SIG-1–SIG-8; T-1; R-1 |
| UT-2 | Unified scope resolution and pagination semantics: `resolve_scope()` + `scope_predicate()` and pagination parameter parsing | tenant/business_scope/workspace filters apply; pagination boundaries are consistent; empty results return a stable empty state | Unit (no DB) | FR-1; SIG-1–SIG-8; T-1; R-2 |
| UT-3 | Fencing query semantics: time / reason / operation filtering and pagination on `GET /observability/execution/fencing-denials` | Filtering and pagination are correct; field semantics match `execution_fencing_denials`; no Secret | Unit (no DB) | FR-2; SIG-1; T-2; R-2 |
| UT-4 | Cleanup-failure classification: `cleanup_status='failed'` and "cancellation requested but unconfirmed" on `GET /observability/execution/cleanup-failures` | Both categories are returned; ambiguous state is presented as "unconfirmed" and never reported as cancelled; `RunView` is unchanged | Unit (no DB) | FR-4; SIG-3; T-3; R-3 |
| UT-5 | Outbox aggregation semantics: pending count, oldest `available_at` lag seconds, failed `last_error`, 24-hour published count on `GET /observability/execution/outbox` | All four metrics are correct; no publication side effect; no Prometheus dependency | Unit (no DB) | FR-5; SIG-4; T-4; R-8 |
| UT-6 | Usage correction-chain semantics: `supersedes_id` chains and duplicate sources rejected by the unique constraint on `GET /observability/execution/usage-conflicts` | Chains and duplicate sources are visible; filtered by `tenant_id`; no double counting and no change to aggregation semantics | Unit (no DB) | FR-7; SIG-6; T-5; R-2 |
| UT-7 | Credential-audit semantics: action / tenant filtering on `GET /observability/execution/credential-audit?action=revoked` | Audit rows are filtered correctly; `public_metadata()` contains no Secret; unauthorized access returns 403 `insufficient_role` | Unit (no DB) | FR-9; SIG-8; T-6; R-1 |
| UT-8 | Parser diagnostic category-count semantics: `malformed/unknown_schema/unknown_type/size_limit/critical_terminal` | Only category counts and bounded, redacted reason codes; `execution_parser_raw_sample_enabled=false` is retained; raw samples produce zero output | Unit (no DB) | FR-8; SIG-7; T-8; R-4 |
| UT-9 | Tenant JOIN semantics: tables without `tenant_id` JOIN `runtime_runs` to obtain tenant/scope | JOIN results carry tenant/scope; orphan run_ids are labeled deployment-level; cross-tenant access is denied by default | Unit (no DB) | FR-1, FR-2, FR-5; SIG-1, SIG-4; T-2, T-4; R-2 |
| UT-10 | Secret canary filtering: inject canaries into all governance responses, errors, and diagnostics | Zero canary occurrences; no Secret field enters any response model | Unit (no DB) | FR-1, FR-8, FR-9; SIG-7, SIG-8; T-2–T-8; R-4 |
| UT-11 | Empty-state and error fail-closed behavior: empty results and query exceptions | Empty results yield a stable empty state; exceptions return a uniform error code and never degrade to Reader visibility | Unit (no DB) | FR-1, FR-10; SIG-1–SIG-8; T-1; R-1 |
| UT-12 | SSE 409 gap-write branch: a cursor older than `event_retention_floor_seq` triggers the 409 branch | One bounded gap event is written; write failure does not block the 409 response; `id=sequence` / `event_replay_gap` / `X-Event-Retention-Floor` are unchanged | Unit (no DB) | FR-6; SIG-5; T-7; R-5 |
| UT-13 | Migration `0072_execution_replay_gap_events` definition: down_revision, table/constraints, and expand → bounded backfill → validation → read-switch structure | Points to the rechecked single head; no applied historical migration is modified; bounded write failure does not affect the main flow | Unit (no DB) | FR-6; SIG-5; T-7; R-5 |
| UT-14 | Migration `0073_execution_parser_diagnostics` definition and collector wiring: down_revision, five category fields, sink switch | Points to the rechecked single head; Secrets / raw samples are never persisted; `ParserDiagnosticCollector` is wired and raw samples are not retained by default | Unit (no DB) | FR-8; SIG-7; T-8; R-4, R-5 |

## 4. PG Integration Tests IT-1–IT-8

| ID | Case | Expected | Environment | Traceability |
|---|---|---|---|---|
| IT-1 | Fresh-database migration chain upgrade: upgrade planned `0072` / `0073` from the rechecked single head | New tables/fields are created; historical migrations `0001`–`0071` (including `0068` / `0069`) are unmodified; head record is retained | PG integration (sharded) | FR-6, FR-8; SIG-5, SIG-7; T-7, T-8; R-5 |
| IT-2 | Fencing real table data, tenant JOIN isolation, and pagination: real `execution_fencing_denials` rows associated with `runtime_runs` | tenant/scope are correct; cross-tenant rows and pagination boundaries are correctly denied/split; orphan rows are labeled deployment-level | PG integration (sharded) | FR-1, FR-2; SIG-1; T-2; R-2 |
| IT-3 | Cleanup-failure real data: `cleanup_status='failed'` and "cancellation requested but unconfirmed" | Both categories are returned; public `RunView` fields have zero diff; host/workdir alerts remain in logs | PG integration (sharded) | FR-4; SIG-3; T-3; R-3 |
| IT-4 | Outbox real table metrics and side effects: pending retention and failed `last_error` in `runtime_event_outbox` | All four metrics agree with the real rows; no publication is triggered; `last_error` is bounded and redacted | PG integration (sharded) | FR-5; SIG-4; T-4; R-8 |
| IT-5 | Usage concurrent unique constraint and correction chain: concurrently write duplicate `source_event_id` values and construct a `supersedes_id` chain | Duplicate sources are rejected by `UNIQUE(run_id, source, source_event_id)`; the chain is persisted and isolated by `tenant_id`; aggregation is unchanged | PG integration (sharded) | FR-7; SIG-6; T-5; R-2 |
| IT-6 | SSE 409 gap persistence: a cursor older than `event_retention_floor_seq` triggers 409 | One bounded gap event is written and is queryable through the endpoint; the 409 header and SSE `id` / `event_replay_gap` semantics have zero diff | PG integration (sharded) | FR-6; SIG-5; T-7; R-5 |
| IT-7 | Parser sink persistence: five diagnostic categories written by the collector/sink into `execution_parser_diagnostics`, with Secret-bearing samples injected | Category counts are persisted; raw samples and Secrets are neither persisted nor surfaced in the UI | PG integration (sharded) | FR-8; SIG-7; T-8; R-4 |
| IT-8 | Credential-audit real data and tenant isolation: real `execution_credential_audit` rows filtered by tenant | Audit rows are visible and cross-tenant access is denied; `public_metadata()` contains no Secret; unauthorized access returns 403 | PG integration (sharded) | FR-9; SIG-8; T-6; R-1 |

## 5. Frontend Playwright Tests FE-1–FE-10

| ID | Case | Expected | Environment | Traceability |
|---|---|---|---|---|
| FE-1 | Governance tab visibility: admin and ordinary user enter the "Runs and Audit" page | "Run Overview" is always visible; the "Execution Governance" tab is visible to admin only | Playwright mock harness | FR-10; SIG-1–SIG-8; T-10; R-7 |
| FE-2 | Admin gating and on-demand mounting: switch both tabs and assert governance requests | A non-admin sees no tab and issues no `/observability/execution/*` request; the governance component mounts only when the governance tab is active and the user is admin | Playwright mock harness | FR-10; SIG-1–SIG-8; T-10; R-1, R-7 |
| FE-3 | Eight-panel rendering, group A: Fencing denials, cleanup failures, Outbox lag, usage conflicts | Four panels render from mock data; fields and labels are correct; the deployment-level label appears for Worker/no-tenant data | Playwright mock harness | FR-2, FR-4, FR-5, FR-7; SIG-1, SIG-3, SIG-4, SIG-6; T-10 |
| FE-4 | Eight-panel rendering, group B: Worker loss, SSE replay gaps, parser diagnostics, credential revocation audit | Four panels render; Worker status explicitly says "deployment-level, not tenant-scoped"; parser shows only category counts and redacted reason codes | Playwright mock harness | FR-3, FR-6, FR-8, FR-9; SIG-2, SIG-5, SIG-7, SIG-8; T-10; R-4 |
| FE-5 | Filtering and pagination: in-panel filters with `serverPagination` / `clientPagination` interactions | Filter conditions reach the correct endpoint; pagination boundaries are correct; no extra request is issued for unmounted panels | Playwright mock harness | FR-1, FR-10; SIG-1–SIG-8; T-10; R-7 |
| FE-6 | Empty-state fail-closed: force empty data and error responses | Stable empty state and loading; errors never degrade into fabricated recovery/success; one missing item does not block other panels | Playwright mock harness | FR-3, FR-10; SIG-1–SIG-8; T-10; R-9 |
| FE-7 | Four-locale i18n: switch to `zh-CN` / `zh-TW` / `en` / `hi` | Governance tab and all eight panels have parity across four locales; missing keys are blocked by `check:i18n` (see CM-2) | Playwright mock harness | FR-10; SIG-1–SIG-8; T-11; R-9 |
| FE-8 | No Secret text: inject canaries and raw samples into all mock responses | Page text, DOM, and request bodies contain no Secret or raw-sample text | Playwright mock harness | FR-8, FR-9, FR-10; SIG-7, SIG-8; T-10, T-11; R-4 |
| FE-9 | Public RunView / SSE zero-change: compare the "Run Overview" Panel and public Run data | Public `RunView` fields have zero diff; SSE `id=sequence` / `event_replay_gap` / `X-Event-Retention-Floor` are unchanged | Playwright mock harness | FR-3, FR-4, FR-6, FR-10; SIG-3, SIG-5; T-10; R-3 |
| FE-10 | Route and navigation zero-change: `hashRouter.ts` and global navigation | No `/observability/:sub` sub-route; the "Quality Operations" sidebar group and "Runs and Audit" entry are unchanged | Playwright mock harness | FR-10; SIG-1–SIG-8; T-10; R-7 |

## 6. General Checks CM-1–CM-6

| ID | Check | Pass criterion | Environment | Traceability |
|---|---|---|---|---|
| CM-1 | ruff / architecture check | Backend lint passes; governance endpoints live in `platform_routes.py`, in the same module as existing `/observability/*`; public contracts are unchanged | Static checks | FR-1; T-1; R-1 |
| CM-2 | `check:i18n` four-locale parity | `npm run check:i18n` passes; keys are aligned across `zh-CN` / `zh-TW` / `en` / `hi`; missing keys block release | Static checks | FR-10; T-11; R-9 |
| CM-3 | typecheck | Frontend type check passes; governance client request/response types match the T-1–T-8 contracts; no Secret field enters the frontend model | Static checks | FR-1–FR-9; T-9; R-7 |
| CM-4 | build | Frontend build passes; on-demand mounting of the governance component does not break existing artifacts | Static checks | FR-10; T-10, T-11; R-9 |
| CM-5 | Migration-chain single head | `backend/migrations/versions/` is rechecked to a single head; `0072` / `0073` agree with the recheck result; applied historical migrations are unmodified; the recheck result is recorded in the T-14 documentation-sync record | Static checks | FR-6, FR-8; SIG-5, SIG-7; T-7, T-8, T-14; R-5 |
| CM-6 | No Prometheus dependency | No Prometheus, no `/metrics`, and no new monitoring dependency; `monitor_checks` / `notifications` and structured logging are reused | Static checks | FR-5; SIG-4; T-4, T-14; R-8 |

## 7. skip / pending Handling Rules

1. Every skip must record its ID, reason, and owning task individually. A skip is never counted as a pass and never counts toward a C-1–C-6 gate.
2. `pending_env` applies only when the environment is genuinely unavailable: a PG shard, the head-recheck environment, the Playwright harness, or a CI command. A case marked `pending_env` must not be rewritten as a pass, and the stage remains "not tested, not accepted".
3. Cases that do not depend on a real untrusted environment (all of UT/IT/FE/CM) may not be skipped on the grounds of a "missing real sandbox/untrusted environment": such environments are outside this stage's scope, and mocks plus deterministic fixtures are the intended verdict mechanism.
4. If the actual head differs from planning `0072` / `0073` in UT-13 / UT-14 / IT-1 / CM-5, register an R-n ruling and update both language versions per R-5, then rerun against the actual numbers; do not skip the case and do not hard-code planning numbers into a passing verdict.
5. A failed case is handled as a defect and recorded first; the rerun scope is then decided. Fixtures must not be adjusted to mask a genuine failure.
6. Every case in this plan is currently "pending execution". No actual pass / fail / skip verdict exists before the reports are generated.

## 8. Scope Limitations and Evidence Handling

- **Out of scope / historical context only**: performance baselines (p50/p95, Outbox lag thresholds, capacity samples), a real untrusted execution environment (sandbox escapes, network attacks, real fault injection), and high-risk enablement (untrusted multi-tenancy, production Codex routes) are not stage test gates and do not create `pending_env`.
- **Evidence ownership**: Independent verdicts for UT / IT / FE / CM are written into `06-test-report.md` after actual execution (not yet generated); acceptance evidence is written into `07-acceptance-report.md` (not yet generated). Reports are not pre-written, and no issue or PR number is registered.
- **Truthful status**: This document is a test plan and provides no conclusion that implementation is complete or testing has passed. Until cases are actually executed and evidence is recorded, the stage remains "not implemented, not tested, not accepted".
