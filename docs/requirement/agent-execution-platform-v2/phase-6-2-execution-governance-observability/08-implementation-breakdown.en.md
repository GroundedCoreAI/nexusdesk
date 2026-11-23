# Phase 6-2 · Execution Governance Observability — Implementation Breakdown

> Status: Approved documentation baseline for subsequent implementation; no task is implemented, tested, or accepted. This document provides no conclusion of completed implementation or passed acceptance.
> Created: 2026-11-22
> Basis: Phase 6 `02-requirements.en.md` FR-16 (Operability); this phase's `01-business-goals.en.md` (G1–G4), `02-requirements.en.md` (FR-1–FR-10, AC-1–AC-10), and `03-technical-design.en.md`; frozen numbering from the approved scope baseline (SIG-1–SIG-8, R-1–R-10, T-1–T-14, UT-1–UT-14, IT-1–IT-8, FE-1–FE-10, CM-1–CM-6, A-1–A-10, C-1–C-6).
> Scope note: Under the current integration baseline, `backend/migrations/versions/` has been applied through `0071_execution_credential.py` (the earlier `0068_open_application_archive.py` / `0069_open_application_unique_name.py` are history). Applied historical migrations must never be modified; `0072` / `0073` are planning values only.

## 1. Delivery Shape, Implementation Order, and Development Entry

### 1.1 Delivery shape

Use an **additive, vertical-slice** delivery shape; no parallel subsystem is created:

1. Governance query skeleton and Class B endpoints (T-1–T-6): add Admin-only governance endpoints inside the existing observability routes, all read-only.
2. Planned migrations and write wiring (T-7–T-8): 0072 plus the SSE 409 write point, and 0073 plus parser collector wiring, with head re-verification before implementation.
3. Frontend, copy, and verification (T-9–T-13): API client types, governance tab and panel, four-language i18n, backend unit/integration tests, and frontend Playwright regression.
4. Composition root and documentation sync (T-14): current-state recheck, deployment-example confirmation, and bilingual document consistency.

Alternatives considered and rejected: a standalone governance service/event store would create a second source of truth; a one-shot horizontal big-bang implementation would delay the first verifiable behavior. This phase opens no untrusted multi-tenancy and changes no execution semantics.

### 1.2 Development entry and historical-migration constraint

- Current integration baseline: `backend/migrations/versions/0070_execution_fencing_event_outbox.py` and `0071_execution_credential.py` exist and form the end of the migration chain; `0068` / `0069` are already-merged historical migrations.
- The development entry is the "current integration baseline". No applied historical migration from `0001` to `0071` may be modified; new migrations can only be appended forward.
- All new routes land in `backend/src/agent_platform/applications/customer_service/platform_routes.py`, in the same module as the existing `/observability/*` routes; the public `RunView`, the SSE response contract, and `hashRouter.ts` / global navigation are unchanged.
- Any newly discovered path, migration number, or public-contract conflict must first be recorded as an R-n ruling and synchronized into the bilingual 01/02/03/08 documents before production code is changed.

### 1.3 Task breakdown

> Files marked "new" in the "Files" column are planned new files for this phase; all others are modification points in existing files. Paths `core_platform/...` and `applications/...` are rooted at `backend/src/agent_platform/`; where the table omits that prefix, the note applies.

| # | Task | Goal | Files (new/modified) | Depends | Quick-check scope | Traceability |
|---|---|---|---|---|---|---|
| T-1 | Unified governance route skeleton and permissions/scope | Build the read-only `/api/v1/observability/execution/*` route skeleton; unify `require("admin")`, `resolve_scope()` + `scope_predicate()`, pagination parameters, and error codes; confirm registration | `backend/src/agent_platform/applications/customer_service/platform_routes.py`; `backend/src/agent_platform/applications/customer_service/application.py` | — | Non-Admin callers all receive 403 `insufficient_role`; 400 for invalid filters/pagination; scope filtering works; empty result returns a stable empty state | FR-1; SIG-1–SIG-8; Phase 6 FR-16; R-1/R-2/R-3 |
| T-2 | Fencing endpoint + service | Add `GET /observability/execution/fencing-denials`; JOIN `runtime_runs` to derive tenant/scope; time/reason/operation filters and pagination | `platform_routes.py`; `core_platform/agent_execution/reliability/ownership.py` (read-only, writer semantics unchanged); `runtime_runs` JOIN | T-1 | Records carry tenant/scope; filtering and pagination correct; orphan records labeled deployment-level; no Secret | FR-2; SIG-1; Phase 6 FR-16; R-2 |
| T-3 | Cleanup-failure endpoint | Add `GET /observability/execution/cleanup-failures`, returning both `cleanup_status='failed'` and "cancellation requested but unconfirmed" | `platform_routes.py`; `schemas.py` (RunView definition, around 18-27, confirm zero change only) | T-1 | Both categories returned; public `RunView` fields unchanged; ambiguous states presented as unconfirmed, never falsely as cancelled | FR-4; SIG-3; Phase 6 FR-16; R-3 |
| T-4 | Outbox endpoint | Add `GET /observability/execution/outbox`: pending count, stall seconds of the oldest `available_at`, failed `last_error`, and 24-hour published count | `platform_routes.py`; `core_platform/agent_execution/events/outbox.py` (reuse `pending_count`/rescan); `backend/src/agent_platform/applications/platform_runtime/runtime_composition.py` (attach `operational_stats().outbox_pending`) | T-1 | Four metrics correct; JOIN to `runtime_runs` effective; no publishing side effect; no Prometheus | FR-5; SIG-4; Phase 6 FR-16; R-1/R-2/R-8 |
| T-5 | Usage-conflict endpoint | Add `GET /observability/execution/usage-conflicts`: supersession chains and duplicate sources rejected by the uniqueness constraint | `platform_routes.py`; `core_platform/agent_execution/events/usage.py` (reuse `aggregate_effective_usage()`) | T-1 | Chains and duplicate sources visible; filtered by `tenant_id`; no double counting and aggregation semantics unchanged; true conflict counting not enabled by default | FR-7; SIG-6; Phase 6 FR-16; R-2 |
| T-6 | Credential-audit endpoint | Add `GET /observability/execution/credential-audit?action=revoked`; revocation state reuses `GET /execution-credentials` | `platform_routes.py`; `backend/src/agent_platform/applications/customer_service/execution_credential_routes.py` (reuse `public_metadata()` and `require("admin")`) | T-1 | Audit rows visible and tenant-filtered; `public_metadata()` has no Secret; 403 when unauthorized; empty state when no match | FR-9; SIG-8; Phase 6 FR-16; R-1 |
| T-7 | Migration 0072 + 409 write point | New migration `0072_execution_replay_gap_events` (planned); write one bounded gap event best-effort on the SSE 409 branch, plus Admin query endpoint `replay-gaps` | `backend/migrations/versions/0072_execution_replay_gap_events.py` (new, planned); `backend/src/agent_platform/applications/customer_service/runtime_routes.py` (around 105-112); `platform_routes.py` | T-1; head re-verification passed | Fresh upgrade succeeds; one bounded row written on 409; write failure does not block 409; SSE `id=sequence` / `event_replay_gap` / `X-Event-Retention-Floor` unchanged | FR-6; SIG-5; Phase 6 FR-16; R-5 |
| T-8 | Migration 0073 + parser collector wiring | New migration `0073_execution_parser_diagnostics` (planned); wire collector/sink in composition, plus Admin query endpoint `parser-diagnostics` | `backend/migrations/versions/0073_execution_parser_diagnostics.py` (new, planned); `core_platform/agent_execution/events/diagnostics.py`; `backend/src/agent_platform/applications/platform_runtime/runtime_composition.py`; `platform_routes.py` | T-1; head re-verification passed | Five classified counts visible; zero raw samples or Secrets; collector wired; `execution_parser_raw_sample_enabled=false` reused | FR-8; SIG-7; Phase 6 FR-16; R-4/R-5 |
| T-9 | Frontend API client types and functions | Define request/response types and call functions for governance endpoints, aligned with T-1–T-8 contracts | `frontend/src/shared/api/client.ts` (plus governance type definitions, placed per existing layering) | T-1–T-6 (contracts frozen) | Types match contracts; errors fail closed; no Secret field enters the frontend model | FR-1–FR-9; SIG-1–SIG-8; R-7/R-9 |
| T-10 | Frontend governance tab and panel component | Add antd `Tabs` at the top of `ObservabilityPage.tsx`; add `ExecutionGovernancePanel.tsx`; reuse foundation components; Admin gating | `frontend/src/features/observability/ObservabilityPage.tsx`; `frontend/src/features/observability/ExecutionGovernancePanel.tsx` (new); reuse `useResource`/`Panel`/`Table`/`Trace`/`serverPagination` (`frontend/src/shared/api/client.ts`, `frontend/src/app/hashRouter.ts` confirmed zero change only) | T-9 | Governance tab visible only to Admin; mounts only when the tab is active and the user is Admin; "Run Overview" Panels unchanged; empty states/loading stable | FR-10; SIG-1–SIG-8; Phase 6 FR-16; R-7/R-9 |
| T-11 | Four-language copy and check:i18n | Add copy as `t('Chinese key')`, aligned across four locales, passing `npm run check:i18n` | `frontend/src/i18n/locales/zh-CN.json`; `frontend/src/i18n/locales/zh-TW.json`; `frontend/src/i18n/locales/en.json`; `frontend/src/i18n/locales/hi.json` | T-10 | Keys aligned across all four locales; `npm run check:i18n` passes; missing keys block release | FR-10; SIG-1–SIG-8; R-7/R-9 |
| T-12 | Backend unit/integration tests | Complete UT-1–UT-14 (backend unit) and IT-1–IT-8 (PG integration), covering permissions/tenants/redaction/migration/SSE compatibility | `backend/tests/` (new governance endpoint unit/integration tests, named per existing conventions; reuse existing observability/credential/migration tests) | T-1–T-8 | Every UT/IT has an individual verdict; Secret canary shows zero occurrences; cross-tenant denial; public `RunView`/SSE zero diff; fresh migration upgrade passes | AC-1–AC-9; FR-1–FR-9; R-5 |
| T-13 | Frontend Playwright regression | Complete FE-1–FE-10, covering tab visibility, on-demand mounting, empty states, pagination, and four languages | Frontend Playwright cases (FE-1–FE-10, placed per existing frontend test layout) | T-10, T-11 | Role-based assertions for Admin/ordinary user; no governance-request leakage; empty states fail closed; hashRouter/global navigation unchanged | AC-10; FR-10; R-7/R-9 |
| T-14 | Composition root/settings/deployment-example wiring and documentation sync | Confirm the 0072/0073 head re-verification record, composition wiring, Secret-free deployment examples, and bilingual document consistency; CM-1–CM-6 general checks | `backend/src/agent_platform/applications/platform_runtime/runtime_composition.py`; existing `backend/.env.example` / `deploy/` examples (confirm only, no new switches); this phase's `01`–`03` and `08` bilingual documents | T-7, T-8, T-13 | No new config switch; examples contain no Secret/key; migration numbers consistent with the head record; bilingual paragraph-by-paragraph alignment; CM-1–CM-6 pass | FR-1–FR-10; SIG-1–SIG-8; R-5/R-6/R-8/R-10 |

`core_platform/...` and `applications/...` are rooted at `backend/src/agent_platform/`; where the table omits the prefix, it refers to the same module under that root. Every "new" file requires R-n registration and bilingual document synchronization before implementation if it changes a path, migration number, or public contract.

## 2. Key Rulings R-1–R-10

The following rulings are carried over verbatim in substance from the approved scope baseline, each using a "Documents / Reality / Ruling" structure.

### R-1 — Governance endpoints are Admin-only

- **Documents**: FR-1 requires a unified governance query API; FR-3 requires Worker state display.
- **Reality**: `/audit` and all five `execution_credential_routes.py` routes are Admin; `GET /notifications/*` are Reader; governance data previously had no dedicated route.
- **Ruling**: Every new `/observability/execution/*` endpoint is Admin-only (aligned with `/audit` and the credential routes) and is not exposed to Readers; Worker loss reuses the Reader `/notifications/*` routes, but the governance tab is Admin-only.

### R-2 — Tables without tenant_id

- **Documents**: FR-1/FR-5/FR-7 require tenant/scope filtering.
- **Reality**: `execution_fencing_denials` and `runtime_event_outbox` have no `tenant_id`; `worker_heartbeats` is deployment-level; `runtime_usage_ledger` and `execution_credential_audit` carry their own `tenant_id`.
- **Ruling**: `execution_fencing_denials`/`runtime_event_outbox` have no tenant_id and must be joined to `runtime_runs`; `worker_heartbeats` is deployment-level with no tenant dimension and is explicitly labeled "deployment-level" in the UI.

### R-3 — Public RunView unchanged

- **Documents**: FR-4 requires exposing cleanup status and unconfirmed cancellation.
- **Reality**: `RunView` (`schemas.py:18-27`) does not include `cleanup_status` / `cancel_requested_at` / `cancel_confirmed_at`; the public contract is consumed by existing clients.
- **Ruling**: The public `RunView` is unchanged; cleanup status is exposed only through Admin governance endpoints.

### R-4 — Parser sensitive content

- **Documents**: FR-8 requires parser diagnostics visualization.
- **Reality**: `execution_parser_raw_sample_enabled=false`; `ParserDiagnosticCollector` has only in-memory counts and an optional sink; raw samples are Class D sensitive content.
- **Ruling**: Parser raw samples/Secrets never enter the UI; display only classified counts and bounded, redacted reason codes.

### R-5 — Migration numbers are planning values

- **Documents**: 03 plans `0072_execution_replay_gap_events` and `0073_execution_parser_diagnostics`.
- **Reality**: The current head is `0071_execution_credential` (0068/0069 are already history); the head may change before implementation as the integration branch advances.
- **Ruling**: Migration numbers `0072`/`0073` are planning values; the single head must be dynamically re-verified before implementation, and if it changes the bilingual documents must be updated in sync; applied historical migrations must never be modified.

### R-6 — No pre-written reports

- **Documents**: Phase conventions call for 06/07 reports.
- **Reality**: No test or acceptance execution has occurred in this phase, so there is no evidence to put in a report.
- **Ruling**: Do not pre-write `06-test-report.en.md` / `07-acceptance-report.en.md`.

### R-7 — Zero frontend router change

- **Documents**: FR-10 adds a governance tab inside the "Runs and Audit" page.
- **Reality**: `hashRouter.ts` `pages` includes `observability` but has no `/observability/:sub` sub-route rule; the page is currently vertically stacked Panels.
- **Ruling**: The new frontend tab does not change hashRouter/global navigation; the governance component mounts on demand.

### R-8 — No new monitoring dependency

- **Documents**: FR-5 requires Outbox lag and delivery-failure metrics.
- **Reality**: There is no Prometheus and no `/metrics`; `monitor_checks` / `notifications` and structured logs already exist; Phase 7 explicitly excludes Prometheus.
- **Ruling**: Do not introduce Prometheus or any new monitoring dependency; reuse `monitor_checks`/`notifications` and structured logs.

### R-9 — Frontend design rules

- **Documents**: FR-10 requires a frontend governance tab and stable empty states.
- **Reality**: The project has `frontend-dev` design rules, and existing pages use the `Panel`/`Table`/`Tag` conventions.
- **Ruling**: The frontend follows the `frontend-dev` design rules: single theme color, labels above inputs, no nested gray cards, stable empty states and loading.

### R-10 — No high-risk capability enablement

- **Documents**: The phase goal is governance visibility.
- **Reality**: Execution semantics, the untrusted-tenant switch, and production Codex routing are outside this phase's authorization.
- **Ruling**: Do not open untrusted multi-tenancy or production Codex routes; this phase does not claim high-risk capability enablement or production rollout.

## 3. Migration Number Re-verification Rule (R-5 Execution Detail)

1. **Before** creating migration files in T-7 / T-8, run a head check on `backend/migrations/versions/` and confirm a single head. The current integration baseline is expected to be `0071_execution_credential` (planned `0072` takes it as `down_revision`, and `0073` takes `0072` as `down_revision`).
2. If the actual head differs from the expectation, do not create files using the stale numbers: first register a new R-n ruling (with "Documents / Reality / Ruling"), then synchronize the migration numbers in the bilingual `01`/`02`/`03`/`08` documents, and only then create the migration files.
3. Never modify an applied historical migration (including `0001`–`0071`, and `0068` / `0069`); additions are forward-only.
4. New migrations follow expand → bounded backfill → validate → read switch; bounded-write failure does not affect the main flow (SSE 409 is not blocked; a parser sink failure is logged only).
5. The head re-verification result must be recorded in T-14's documentation sync and serve as evidence for the CM general checks and the C-4 data-integrity/migration gate.

## 4. Test Numbering and Definition of Done (DoD)

### 4.1 Test and acceptance numbering map

| Layer | Number range | Coverage | Owning task |
|---|---|---|---|
| Backend unit | UT-1–UT-14 | Permissions/error codes, scope filtering, pagination, per-endpoint query semantics, Secret canary, empty states, 409 compatibility | T-12 |
| PostgreSQL integration | IT-1–IT-8 | Fresh upgrade, JOIN tenant isolation, 0072/0073 writes, SSE 409 semantic zero diff, public `RunView` zero diff, cross-tenant denial | T-12 |
| Frontend Playwright | FE-1–FE-10 | Tab visibility, on-demand mounting, pagination, fail-closed empty states, four languages, hashRouter zero change | T-13 |
| General checks | CM-1–CM-6 | i18n key alignment, no Prometheus, no Secret/raw sample in the UI, migration head record, bilingual alignment, no pre-written issue/PR numbers | T-14 |
| Acceptance scenarios | A-1–A-10 | One-to-one with AC-1–AC-10 | Actual acceptance phase |
| Gates | C-1–C-6 | C-1 functional semantics; C-2 tenant/permission isolation; C-3 Secret and redaction; C-4 data integrity and migration; C-5 compatibility (public RunView/SSE unchanged); C-6 no P0/P1 and a single acceptance record | Actual acceptance phase |

### 4.2 Definition of Done (DoD)

A single task is complete only when all of the following hold:

- Every endpoint/component/migration field named in its goal is implemented per the 03 technical design and the frozen numbering, and the files involved match the baseline.
- Every listed quick-check passes and leaves a traceable test/check record; a failing item is not marked complete.
- If a conflict with the baseline is found, an R-n ruling is registered and the bilingual documents are synchronized before implementation continues.

The overall (phase-level) DoD requires all of the following:

1. T-1–T-14 are all complete, and UT-1–UT-14, IT-1–IT-8, FE-1–FE-10, and CM-1–CM-6 each carry an individual verdict and evidence.
2. A-1–A-10 corresponding to AC-1–AC-10 are executed and recorded one by one; all gates C-1–C-6 are met, with no P0/P1 and a single acceptance record.
3. Compatibility hard constraints hold: public `RunView` zero change, SSE `id=sequence` / `event_replay_gap` / `X-Event-Retention-Floor` zero change, `hashRouter` and global navigation zero change, and no Prometheus.
4. Security hard constraints hold: governance responses and `public_metadata()` contain no Secret; parser raw samples and Secrets show zero occurrences; cross-tenant governance data is denied by default.
5. Migration constraints hold: 0072/0073 have been re-verified against a single head; applied historical migrations are unmodified; migration numbers match across bilingual documents.
6. Documentation constraints hold: 01/02/03/08 are paragraph-by-paragraph aligned in Chinese and English; `npm run check:i18n` passes; `06-test-report.en.md` / `07-acceptance-report.en.md` are not pre-written; no issue/PR numbers are registered.
7. Status is truthful: only after all of the above is complete may the status be changed from "not implemented, not tested, not accepted"; until then every task remains incomplete.
