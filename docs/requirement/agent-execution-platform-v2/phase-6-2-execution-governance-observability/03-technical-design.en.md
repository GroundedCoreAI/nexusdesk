# Phase 6-2 · Execution Governance Observability — Technical Design

> Status: Approved documentation scope baseline for subsequent implementation; not implemented, not tested, not accepted. This document does not claim that any endpoint, migration, component, or test has been completed.
> Created: 2026-11-22
> Basis: Phase 6 `02-requirements.en.md` FR-16 (Operability); this phase's `01-business-goals.en.md` (G1–G4) and `02-requirements.en.md` (FR-1–FR-10, AC-1–AC-10); governance signal classification (SIG-1–SIG-8) and key rulings (R-1–R-10) from the approved scope baseline.
> Scope note: This phase adds only a unified governance query API and a visualization UI. Execution semantics are unchanged, no execution branch is added, no untrusted multi-tenancy is opened, no Prometheus is introduced, and `06-test-report.en.md` / `07-acceptance-report.en.md` are not pre-written.

## 1. Architecture Overview

### 1.1 Layers and boundaries

| Layer | Design landing point | Constraints |
|---|---|---|
| Backend governance query layer | New read-only `/api/v1/observability/execution/*` endpoints in `backend/src/agent_platform/applications/customer_service/platform_routes.py`; shared dependencies `require("admin")`, `resolve_scope()` + `scope_predicate()`, unified pagination and error codes | Same tier as `/audit` and the credential routes; all Admin-only and not exposed to Readers (R-1) |
| Data-source adaptation | Query each SIG's existing tables/checks directly; tables without `tenant_id` are joined to `runtime_runs` (on run_id) to derive tenant/scope (R-2) | Read-only; original writer semantics unchanged; no second source of truth is copied |
| Planned new persistence | Migrations `0072_execution_replay_gap_events` (SIG-5) and `0073_execution_parser_diagnostics` (SIG-7), both planning values | The single head must be dynamically re-verified before implementation (R-5); applied historical migrations must never be modified |
| Frontend visualization layer | Add antd `Tabs` at the top of `frontend/src/features/observability/ObservabilityPage.tsx`: "Run Overview" retains every existing Panel, while "Execution Governance" is new; the sub-panel is extracted as `ExecutionGovernancePanel.tsx` | Visible and mounted only for an Admin; no global navigation item and no `hashRouter` change (R-7) |
| Reused foundation | `useResource<T>(path, refreshMs)`, `Panel`, `Table`, `Tag`, `Badge`, `Alert`, `useAccess`, `useAction`, `Trace`, `time`, `serverPagination` / `clientPagination` | Follow `frontend-dev` design rules: single theme color, labels above inputs, no nested gray cards, stable empty states and loading (R-9) |

### 1.2 Verified facts and design constraints

The following facts come from code and the approved baseline and are binding inputs to this design:

| Area | Verified fact | Design consequence |
|---|---|---|
| Public aggregate | `GET /observability/summary` (Reader) at `platform_routes.py:1541` returns only `total, completed, failed, cancelled, running, queued, average_seconds, p95_seconds, tokens, ttfc{p50_ms,p95_ms,samples}` and contains no governance signal | Governance endpoints are added independently; summary semantics are not rewritten |
| Existing observability | `/observability/gateways`, `/observability/memory`, `/observability/memory/alerts`, `/observability/runs`, `/observability/runs/{rid}/trace` are Reader; `/audit` is Admin and reads `audit_records`, without fencing/credential governance audit | Governance is attached to the same page but under a new Admin prefix; governance data is not folded into `/audit` |
| Credential routes | All five routes in `execution_credential_routes.py` use `require("admin")`; `public_metadata()` fields are `credential_ref, tenant_id, name, credential_type, key_version, version, status, allowed_engines, allowed_workspaces, created_at, updated_at, rotated_at, revoked_at` and never return a Secret | Revocation state is reused with zero backend work; audit adds a read-only endpoint only |
| Permission primitives | `Reader = Depends(principal)` (any login); `Operator = admin\|operator`; `Admin = require("admin")`; 403 `insufficient_role` | Governance endpoints uniformly use `Admin`; unauthorized access is always 403 and never degrades to Reader |
| Tenant gap | `execution_fencing_denials`, `runtime_event_outbox`, and `worker_heartbeats` have no `tenant_id`; `runtime_usage_ledger` and `execution_credential_audit` carry their own `tenant_id` | The former are joined to `runtime_runs` or explicitly labeled deployment-level; the latter filter directly on `tenant_id` |
| Monitoring dependency | No Prometheus and no `/metrics`; Phase 7 documentation explicitly excludes Prometheus | Reuse `monitor_checks` / `notifications` and structured logs (R-8) |
| Frontend status | `observability` = "Runs and Audit" in the "Quality Operations" sidebar group, icon `LineChartOutlined`; the page is vertically stacked Panels, not tabs; `hashRouter.ts` `pages` includes `observability`, with no `/observability/:sub` sub-route rule | Tabs are added inside the page with zero router changes (R-7) |

### 1.3 Governance signal classification overview

Classification: A = persisted with a usable API, the frontend integrates directly; B = persisted with no query API, a new endpoint is required; C = persistence or wiring is missing, a new migration/write point is required; D = sensitive content, never enters the UI.

| ID | Signal | Class | Minimum work in this phase |
|---|---|---|---|
| SIG-1 | Fencing denials | B | New Admin fencing-denials endpoint + UI table |
| SIG-2 | Worker loss | A (with caveat) | Reuse the checklist/notifications panel, explicitly labeled deployment-level |
| SIG-3 | Cleanup failures | B | New Admin cleanup-failures endpoint + UI table, public `RunView` unchanged |
| SIG-4 | Outbox lag | B | New Admin outbox endpoint + UI metric cards/table |
| SIG-5 | SSE replay gaps | C | Migration 0072 + bounded write on the 409 branch + Admin endpoint + UI |
| SIG-6 | Usage conflicts | B (with a C component) | New Admin usage-conflicts endpoint + UI correction chain; a true-conflict-count audit write is optional |
| SIG-7 | Parser native event diagnostics | C; raw samples are D | Migration 0073 + collector/sink wiring + Admin endpoint + UI classified counts |
| SIG-8 | Credential revocation | A (state) + B (audit) | State reuses `GET /execution-credentials`; new Admin credential-audit endpoint + UI |

## 2. Governance Signals: Data Sources, SQL Semantics, and API Contracts

Common properties of every endpoint (FR-1): path prefix `/api/v1/observability/execution/*`; method is `GET` throughout; permission `require("admin")`, with 403 `insufficient_role` for non-Admin or unauthorized callers; 400 for invalid filters/pagination; tenant/scope filtering reuses `resolve_scope()` + `scope_predicate()`, while credential endpoints filter by `tenant_id` only and do not apply business_scope; unified pagination parameters `page` (default 1) and `page_size` (default 20, cap 100); query errors return a unified error code and never degrade to Reader visibility, and an empty result returns a stable empty state. The tables below list only the differences per SIG.

### 2.1 SIG-1 Fencing denials (B)

Data source: `execution_fencing_denials` (migration `0070_execution_fencing_event_outbox.py`) with fields `run_id, operation, reason, stale_owner, stale_lease_epoch, current_owner, current_lease_epoch, created_at`; written by `FencingDenialRecorder` in `core_platform/agent_execution/reliability/ownership.py` (in a separate transaction after rollback). No route currently reads this table.

SQL semantics: a detail query ordered by `created_at DESC`, with `JOIN runtime_runs r ON d.run_id = r.id` to derive `tenant_id` and business/workspace scope; filters on a `created_at` time window, `reason`, and `operation`; no aggregation and no rewriting of written content.

API contract:

| Item | Value |
|---|---|
| Path / method | `GET /api/v1/observability/execution/fencing-denials` |
| query parameters | `from`, `to`, `reason`, `operation`, `tenant_id`, `business_scope`, `workspace`, `page`, `page_size` |
| Response shape | `{ items: [{ run_id, operation, reason, stale_owner, stale_lease_epoch, current_owner, current_lease_epoch, created_at, tenant_id, scope }], total, page, page_size }` |
| Error codes | 403 `insufficient_role`; 400 invalid filters/pagination |
| Tenant/scope | The table has no `tenant_id`, so a JOIN to `runtime_runs` is mandatory; orphan run_ids are labeled deployment-level |
| Pagination | Server-side, unified `page` / `page_size` |

### 2.2 SIG-2 Worker loss (A, with caveat)

Data source: `worker_heartbeats` (migration `0060_monitoring`: `worker_id/host/started_at/beat_at/detail` JSONB) plus the monitoring check `worker.runtime.heartbeat` → `monitor_checks` / `notifications`; a `runtime.lease_expired` check also exists. `GET /notifications/checklist` and `GET /notifications` already exist (Reader).

SQL semantics: no new query SQL; consume the existing checklist/notifications structure to extract current state and `beat_at` for heartbeat and lease_expired items; display by `worker_id`, without constructing a historical timeline.

API contract: no new governance endpoint; presentation reuses the existing Reader routes, while the governance tab remains Admin-only.

| Item | Value |
|---|---|
| Path / method | Reuse `GET /notifications/checklist` and `GET /notifications` (both Reader); the governance tab is still Admin-only |
| query parameters | Inherit the existing routes' parameters |
| Response shape | Existing checklist/notifications structure; the UI explicitly labels "deployment-level, not tenant-scoped" |
| Error codes | Inherit the existing routes; a stable empty state when data is missing |
| Tenant/scope | Deployment-level, with no tenant dimension (R-2) |
| Pagination | Inherit the existing routes |

### 2.3 SIG-3 Cleanup failures and unconfirmed cancellation (B)

Data source: `runtime_runs.cleanup_status CHECK IN(not_started,in_progress,completed,failed)`, `cleanup_updated_at`, `cancel_requested_at`, and `cancel_confirmed_at` (0070). Host/workdir cleanup-failure alerts go only to `LoggingAlertSink` (logs, not a table); `RunView` (`schemas.py:18-27`) does not include these fields.

SQL semantics: a union of two categories — (a) `cleanup_status = 'failed'`; (b) `cancel_requested_at IS NOT NULL AND cancel_confirmed_at IS NULL`. Ordered by `cleanup_updated_at DESC`; `runtime_runs` carries its own tenant/scope, so filtering is direct.

API contract:

| Item | Value |
|---|---|
| Path / method | `GET /api/v1/observability/execution/cleanup-failures` |
| query parameters | `category=failed\|unconfirmed_cancel` (optional; both categories by default), `from`, `to`, `tenant_id`, `business_scope`, `workspace`, `page`, `page_size` |
| Response shape | `{ items: [{ run_id, category, cleanup_status, cleanup_updated_at, cancel_requested_at, cancel_confirmed_at, tenant_id, scope }], total, page, page_size }` |
| Error codes | 403 `insufficient_role`; 400 invalid filters/pagination |
| Tenant/scope | `runtime_runs` carries its own tenant/scope and is filtered directly; the public `RunView` is unchanged (R-3) |
| Pagination | Server-side, unified `page` / `page_size` |

### 2.4 SIG-4 Outbox lag (B)

Data source: `runtime_event_outbox` (0070): `run_id, seq, event_id UNIQUE, status(pending/published), attempts, available_at, created_at, published_at, last_error`; `events/outbox.py` provides `pending_count` and rescanning; `runtime_composition.ExecutionRuntimeSubsystem.operational_stats()` returns `outbox_pending`, currently referenced only by tests and not attached to a route.

SQL semantics: pending count = `COUNT(*) WHERE status='pending'`; stall seconds = `EXTRACT(EPOCH FROM (now() - MIN(available_at))) WHERE status='pending'`; failed detail = `last_error` for `status='pending' AND last_error IS NOT NULL` (a bounded, redacted string with no event payload); 24-hour published count = `COUNT(*) WHERE status='published' AND published_at >= now() - interval '24 hours'`. The table has no `tenant_id`, so it is joined to `runtime_runs` (on run_id) to derive tenant/scope.

API contract:

| Item | Value |
|---|---|
| Path / method | `GET /api/v1/observability/execution/outbox` |
| query parameters | `tenant_id`, `business_scope`, `workspace`, `page`, `page_size` (detail-table pagination) |
| Response shape | `{ pending_count, oldest_available_at, stall_seconds, last_errors: [{ run_id, seq, attempts, available_at, last_error }], published_24h, total, page, page_size }` |
| Error codes | 403 `insufficient_role`; 400 invalid pagination/filters |
| Tenant/scope | JOIN to `runtime_runs`; reuse `operational_stats().outbox_pending` for metric-card cross-checking (R-1/R-2/R-8) |
| Pagination | Metrics are global/scope-aggregated; `last_errors` detail is server-side paginated |

### 2.5 SIG-5 SSE replay gaps (C)

Data source: currently only `runtime_runs.event_retention_floor_seq` (0070, advanced atomically with retention cleanup) plus the SSE route's 409 `event_replay_gap` and response header `X-Event-Retention-Floor` (`runtime_routes.py:105-112`); there is no gap occurrence record or query API. A new table `execution_replay_gap_events` is planned (migration `0072_execution_replay_gap_events`, planning).

SQL semantics: a detail query ordered by `created_at DESC`, filtered by run_id / tenant / time window; no aggregation of raw SSE content.

API contract:

| Item | Value |
|---|---|
| Path / method | `GET /api/v1/observability/execution/replay-gaps` |
| query parameters | `from`, `to`, `run_id`, `tenant_id`, `business_scope`, `workspace`, `page`, `page_size` |
| Response shape | `{ items: [{ id, run_id, requested_cursor_seq, retention_floor_seq, reason_code, created_at, tenant_id, scope }], total, page, page_size }` |
| Error codes | 403 `insufficient_role`; 400 invalid filters/pagination; the 409 retention-gap explanation stays with the SSE route and is not produced by this query endpoint |
| Tenant/scope | The planned table copies `tenant_id` from the authorized run at write time and filters on it; JOIN to `runtime_runs` for scope |
| Pagination | Server-side, unified `page` / `page_size` |

### 2.6 SIG-6 Usage conflicts and correction chains (B, with a C component)

Data source: `runtime_usage_ledger` (0070): `run_id, tenant_id, lease_epoch, source, source_event_id, usage, cost, is_estimate, supersedes_id` (self-referencing correction chain), `UNIQUE(run_id, source, source_event_id)`; rebuild logic is `events/usage.py::aggregate_effective_usage()`. There is currently no explicit conflict event and no API.

SQL semantics: correction chains are expanded recursively via `supersedes_id` into `(run_id, source, source_event_id, id, supersedes_id, usage, cost, is_estimate)`, with only effective leaves entering aggregates; duplicate sources are `(run_id, source, source_event_id)` attempts rejected by the uniqueness constraint (if a true count is needed, an audit write is added at the unique-conflict/supersede point — a Class C, optional component); `aggregate_effective_usage()` semantics are not changed and nothing is double-counted. The table carries its own `tenant_id` for direct filtering.

API contract:

| Item | Value |
|---|---|
| Path / method | `GET /api/v1/observability/execution/usage-conflicts` |
| query parameters | `from`, `to`, `run_id`, `tenant_id`, `business_scope`, `workspace`, `kind=chain\|duplicate`, `page`, `page_size` |
| Response shape | `{ items: [{ run_id, tenant_id, source, source_event_id, supersedes_id, usage, cost, is_estimate, kind }], total, page, page_size }` |
| Error codes | 403 `insufficient_role`; 400 invalid filters/pagination |
| Tenant/scope | The table carries its own `tenant_id` for direct filtering; incomplete chains are shown as the known portion with an explicit marker |
| Pagination | Server-side, unified `page` / `page_size` |

### 2.7 SIG-7 Parser native event diagnostics (C; raw samples are D)

Data source: no table. `ParserDiagnosticCollector` in `core_platform/agent_execution/events/diagnostics.py` has only in-memory `self._counts` / `self._suppressed` plus an optional sink; `execution_parser_raw_sample_enabled=false`; no production instantiation is found in code, so it is effectively unwired. Categories: `malformed/unknown_schema/unknown_type/size_limit/critical_terminal`. A new table `execution_parser_diagnostics` is planned (migration `0073_execution_parser_diagnostics`, planning).

SQL semantics: aggregate `COUNT(*)` by time bucket + `category` + bounded, redacted `reason_code` to produce classified counts and trends; raw samples and Secrets are never persisted and never enter the UI.

API contract:

| Item | Value |
|---|---|
| Path / method | `GET /api/v1/observability/execution/parser-diagnostics` |
| query parameters | `from`, `to`, `category`, `tenant_id`, `business_scope`, `workspace`, `bucket`, `page`, `page_size` |
| Response shape | `{ items: [{ bucket_start, category, reason_code, count, tenant_id, run_id }], total, page, page_size }`; contains only classified counts and bounded, redacted reason codes |
| Error codes | 403 `insufficient_role`; 400 invalid filters/pagination |
| Tenant/scope | The planned table copies `tenant_id` from the authorized context at write time; when the collector is unwired or data is missing, the UI shows a stable empty state (R-4/R-5) |
| Pagination | Server-side, unified `page` / `page_size` |

### 2.8 SIG-8 Credential revocation and audit (A state + B audit)

Data source: `execution_credentials` (`status active/superseded/revoked`, `version`, `rotated_at`, `revoked_at`), `execution_credential_grants`, and `execution_credential_audit` (`action created/rotated/revoked/grant_issued/grant_denied/grant_used`, `outcome`, `reason_code`, `actor`), all from 0071. Five Admin routes including `GET /execution-credentials` already exist, but no route reads `execution_credential_audit`.

SQL semantics: current revocation state reuses `GET /execution-credentials` with zero backend work; audit is a detail query filtered by `action`, `tenant_id`, and a time window, ordered by time descending.

API contract:

| Item | Value |
|---|---|
| Path / method | State reuses `GET /api/v1/execution-credentials`; audit adds `GET /api/v1/observability/execution/credential-audit` |
| query parameters | Audit: `action=revoked` (default focus), `from`, `to`, `tenant_id`, `page`, `page_size`; tenant only, no business_scope |
| Response shape | `{ items: [{ id, credential_ref, action, outcome, reason_code, actor, created_at, tenant_id }], total, page, page_size }`; `public_metadata()` fields contain no Secret |
| Error codes | 403 `insufficient_role`; 400 invalid filters/pagination; no match returns an empty state |
| Tenant/scope | The audit table carries its own `tenant_id` for direct filtering; both routes use `require("admin")` |
| Pagination | Server-side, unified `page` / `page_size` |

## 3. Planned New Migrations (planned, re-verify head before implementation)

All fields below are derived from facts in the approved baseline and are **planned values**; every field must be re-checked against code reality before implementation. Migration numbers `0072` / `0073` are planning values: the single head must be dynamically re-verified before implementation; if the head changes, record it as an R-n ruling and update the bilingual documents in sync. Applied historical migrations must never be modified (R-5).

### 3.1 `0072_execution_replay_gap_events` (SIG-5, planned)

| Field | Type/constraint | Basis and purpose |
|---|---|---|
| `id` | UUID PK | Gap-event identity |
| `run_id` | UUID FK → `runtime_runs(id)` | The authorized run on the 409 branch; used to JOIN for tenant/scope |
| `tenant_id` | TEXT + index | Copied from the authorized run at write time for bounded tenant filtering |
| `requested_cursor_seq` | INTEGER | The client cursor that triggered 409 (earlier than the floor) |
| `retention_floor_seq` | INTEGER | The `event_retention_floor_seq` at that time, consistent with `X-Event-Retention-Floor` |
| `reason_code` | TEXT | Bounded stable reason code (e.g. `cursor_below_floor`), with no payload or Secret |
| `created_at` | TIMESTAMPTZ | Gap occurrence time, used for ordering and time-window filtering |

No SSE event payload, raw sample, or Secret is stored; a gap-event write failure does not block the normal 409 response.

### 3.2 `0073_execution_parser_diagnostics` (SIG-7, planned)

| Field | Type/constraint | Basis and purpose |
|---|---|---|
| `id` | UUID PK | Diagnostic bucket identity |
| `tenant_id` | TEXT NULL + index | Copied from the authorized context at write time; null when there is no context (deployment-level) |
| `run_id` | UUID NULL | Association with a run, aligned with the `ParserDiagnosticCollector` run/protocol/adapter correlation |
| `category` | TEXT CHECK IN (`malformed`, `unknown_schema`, `unknown_type`, `size_limit`, `critical_terminal`) | The five categories specified by the baseline |
| `reason_code` | TEXT NULL | Bounded, redacted reason code; **raw samples and Secrets are never persisted** |
| `count` | INTEGER NOT NULL | Classified count within the bucket |
| `bucket_start` | TIMESTAMPTZ | Start of the trend time bucket |

The existing `execution_parser_raw_sample_enabled=false` switch is reused; no new switch is added in this phase.

## 4. Write Points and Wiring Design

### 4.1 SSE 409 gap write point (SIG-5)

```text
SSE client cursor < runtime_runs.event_retention_floor_seq
→ runtime_routes.py returns 409 event_replay_gap + X-Event-Retention-Floor (around 105-112)
→ within the same request, write one execution_replay_gap_events row in a best-effort separate transaction
→ record run_id/tenant_id/requested_cursor_seq/retention_floor_seq/reason_code/created_at
→ a write failure is logged only and does not block the 409 response
→ public SSE semantics (id=sequence, event_replay_gap, response header) are unchanged
```

The write happens on a read-only SSE path and must not change the SSE status code, headers, or event sequence; its failure must be swallowed and leave only a log.

### 4.2 Parser collector wiring point (SIG-7)

```text
ParserDiagnosticCollector in events/diagnostics.py (in-memory _counts/_suppressed + optional sink)
→ instantiate the collector and a persistence sink during runtime_composition.ExecutionRuntimeSubsystem construction
→ the sink writes classified counts by time bucket into execution_parser_diagnostics (0073)
→ reason_code is bounded and redacted; even temporarily collected raw samples and Secrets never enter the sink/UI
→ execution_parser_raw_sample_enabled stays false; no new switch
```

No production instantiation of the collector is found in current code, so wiring is one of this phase's minimum tasks; when unwired, the UI shows a stable empty state and never fabricates data.

## 5. Frontend Design

### 5.1 Page structure

`frontend/src/features/observability/ObservabilityPage.tsx` changes from vertically stacked Panels to antd `Tabs` at the top:

| Tab | Visibility | Content |
|---|---|---|
| "Run Overview" | All users who can see the "Runs and Audit" page | Retains every existing Panel (metric cards, memory observation + governance actions, memory alerts, extension runtime state, event-delivery operations, recent runs + run detail Trace, 24-hour gateway metering, operation audit), with zero deletion or modification |
| "Execution Governance" | Only when the `admin` boolean from `useAccess` is true | Mounts the standalone component `frontend/src/features/observability/ExecutionGovernancePanel.tsx` (new) |

The governance component mounts only when the "Execution Governance" tab is active and the user is an Admin, so ordinary users or other tabs never trigger governance queries; no global navigation item is added and `hashRouter.ts` is unchanged (R-7).

### 5.2 Components and data flow

`ExecutionGovernancePanel.tsx` is organized into SIG-corresponding sub-panels: fencing-denial table, Worker state (deployment-level label), cleanup-failure table, Outbox metric cards + failure table, SSE gap table, usage correction-chain table, parser classified counts/trend, credential revocation state (reusing the existing route) + audit table. Each sub-panel reuses:

| Reuse point | Purpose |
|---|---|
| `useResource<T>(path, refreshMs)` | Call `shared/api/client.ts` to load governance endpoints; empty data/errors fail closed |
| `Panel` / `Table` / `Tag` / `Badge` / `Alert` | Unified cards, tables, status tags, alerts |
| `serverPagination` / `clientPagination` | Governance tables follow the pagination convention already in ObservabilityPage |
| `Trace` | Run detail reuses the existing Trace view |
| `time` | Time-window and timestamp formatting |
| `useAccess` / `useAction` | Admin gating and action state |

### 5.3 Admin gating and fail-closed behavior

Non-Admin users: the governance tab is not rendered, the governance component is not mounted, and no `/observability/execution/*` request is issued. Empty data or error responses: each sub-panel shows a stable empty state — recovery state, delivery success, and conflict counts are never fabricated. All new copy uses `t('Chinese key')` and is aligned across the four locales in `src/i18n/locales/{zh-CN,zh-TW,en,hi}.json`; `npm run check:i18n` must pass, and a missing key blocks release. Follow the `frontend-dev` design rules: single theme color, labels above inputs, no nested gray cards, stable empty states and loading (R-9).

## 6. Security Design

| Dimension | Measure | Ruling |
|---|---|---|
| Permissions | Every new `/observability/execution/*` endpoint uses `require("admin")`, consistent with `/audit` and the credential routes; unauthorized access is 403 `insufficient_role`; Worker loss reuses the Reader `GET /notifications/*` routes but the governance tab is Admin-only | R-1 |
| Tenant JOIN | `execution_fencing_denials` and `runtime_event_outbox` are joined to `runtime_runs` for tenant/scope; `worker_heartbeats` is deployment-level and explicitly labeled in the UI; `runtime_usage_ledger` and `execution_credential_audit` filter on their own `tenant_id`; cross-tenant access is denied by default | R-2 |
| Zero Secret leakage | `public_metadata()` and all governance responses contain no Secret; parser displays only classified counts and bounded, redacted reason codes; a Secret-canary test must show zero occurrences | R-4 |
| Raw samples | Raw samples never enter the UI; `execution_parser_raw_sample_enabled=false` is reused; the 0073 table stores no raw samples | R-4 |
| No high-risk exposure | No untrusted multi-tenancy or production Codex route is opened; this phase does not claim high-risk capability enablement or production rollout | R-10 |
| No new monitoring dependency | No Prometheus / `/metrics`; reuse `monitor_checks` / `notifications` and structured logs | R-8 |

## 7. Compatibility and Rollback

| Compatibility surface | Design guarantee |
|---|---|
| Public `RunView` | Zero change; cleanup status is exposed only through Admin governance endpoints (R-3) |
| SSE | `id=sequence`, `event_replay_gap` semantics, and the `X-Event-Retention-Floor` header are unchanged; the 409 write is a best-effort side path |
| Public summary | `GET /observability/summary` fields and semantics are unchanged |
| Routes/navigation | `hashRouter.ts` and global navigation are unchanged; only in-page Tabs are added |
| Dependencies | No Prometheus and no new monitoring dependency |
| Migrations | Applied historical migrations are not modified; 0072/0073 are planned additions with head re-verification before implementation |

Rollback strategy: unregistering the governance routes and unmounting the governance tab component disables all governance query capability without affecting the execution path; if 0072/0073 have been applied, rollback stops writes/queries only and performs no data-deleting downgrade. Any Secret leakage, cross-tenant governance-data exposure, SSE semantic change, or public `RunView` change stops work and triggers immediate rollback.

## 8. Configuration Switches

This phase introduces no new configuration switch. The table below lists only the governance-observability-related switch that already exists in Phase 6 FR-16.

| Switch | Default | Description | Traceability |
|---|---|---|---|
| `execution_parser_raw_sample_enabled` | `false` | Existing Phase 6 FR-16 switch: raw samples are not retained by default; this phase never brings raw samples or Secrets into the UI, displaying only classified counts and bounded, redacted reason codes | SIG-7; Phase 6 FR-16; R-4 |
