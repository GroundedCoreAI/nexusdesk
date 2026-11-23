# Phase 6-2 · Execution Governance Observability — Requirements

> Status: Approved documentation scope baseline for subsequent implementation; not implemented, not tested, not accepted
> Created: 2026-11-22
> Basis: Phase 6 `02-requirements.en.md` FR-16 (Operability); this phase's `01-business-goals.en.md` (G1–G4); signal classification and frozen numbering follow the approved scope baseline (SIG-1–SIG-8, US-1–US-4, FR-1–FR-10, AC-1–AC-10).
> Scope note: This phase adds only a unified governance query API and a visualization UI. Every new `/observability/execution/*` endpoint is Admin-only; no untrusted multi-tenancy is opened, no Prometheus is introduced, and execution semantics and public contracts are unchanged.

## User Stories

**US-1 SRE**: As an SRE, I want to query fencing denials, Outbox lag, cleanup failures, and other governance signals in one place by tenant, scope, time, and reason so that I can inspect governance state proactively rather than reacting to logs after the fact.

**US-2 Security administrator**: As a security administrator, I want to review credential revocation audit and classified parser diagnostics in an Admin-only view containing no Secrets or raw samples so that I can verify security state without introducing a new disclosure surface.

**US-3 Platform operator**: As a platform operator, I want to see Worker loss/recovery state (explicitly labeled deployment-level), cleanup failures and unconfirmed cancellations, and Outbox delivery failures without changing execution semantics so that I can locate and safely handle deployment-level faults.

**US-4 Finance and audit staff**: As finance and audit staff, I want to see usage correction chains and records rejected by the uniqueness constraint, traceable to run, tenant, and actor, so that I can verify the trustworthiness of usage data.

## Functional Requirements

### FR-1 Unified governance query API (Admin-only, tenant/scope filtering, no Secrets, unified error codes)

Traceability: SIG-1–SIG-8; Phase 6 FR-16 (Operability); rulings R-1 / R-2 / R-3.

| Item | Description |
|---|---|
| Trigger | When an Admin opens the "Execution Governance" tab or calls any `/api/v1/observability/execution/*` endpoint directly. |
| Input | Admin identity (`require("admin")`); optional tenant_id / business_scope / workspace filters, a time window, reason / operation / action filters, and pagination parameters. |
| Output | Paginated governance data returned only through Admin endpoints, with no Secret fields; unified error codes: 403 `insufficient_role`, 400 for invalid filters/pagination, 409 for a retention-gap explanation. |
| Execution mode | A common `/api/v1/observability/execution/*` prefix, all Admin-only; tables without a `tenant_id` are joined to `runtime_runs` (on run_id) to derive tenant/scope, reusing `resolve_scope()` + `scope_predicate()`; credential routes filter by tenant only and do not apply business_scope. |
| Failure handling | Non-Admin or unauthorized callers uniformly receive 403 `insufficient_role`; invalid filters or pagination return 400; query errors return a unified error code and never degrade to Reader visibility; an empty result returns a stable empty state. |

### FR-2 Fencing denials

Traceability: SIG-1; Phase 6 FR-16; ruling R-2.

| Item | Description |
|---|---|
| Trigger | After a stale owner/epoch write is recorded by `FencingDenialRecorder` in `ownership.py` (in a separate transaction after rollback), or when an Admin views the fencing-denial list. |
| Input | `execution_fencing_denials` fields `run_id, operation, reason, stale_owner, stale_lease_epoch, current_owner, current_lease_epoch, created_at`; time / reason / operation filters and pagination parameters. |
| Output | Admin `GET /observability/execution/fencing-denials` paginated list, joined to `runtime_runs` to include tenant/scope; a governance UI table. |
| Execution mode | Read-only query; the `FencingDenialRecorder` write semantics are unchanged; the table has no `tenant_id`, so it is always joined to `runtime_runs` (on run_id). |
| Failure handling | Orphan records with no matching run_id are labeled as tenantless/deployment-level and explicitly marked in the UI; query failures return the FR-1 unified error code and expose no Secrets. |

### FR-3 Worker loss and recovery state

Traceability: SIG-2; Phase 6 FR-16; rulings R-1 / R-8.

| Item | Description |
|---|---|
| Trigger | After the `worker.runtime.heartbeat` / `runtime.lease_expired` monitor checks run and write to `monitor_checks` / `notifications`, or when an Admin opens the governance panel to inspect Worker state. |
| Input | `worker_heartbeats` (`worker_id/host/started_at/beat_at/detail` JSONB) plus `monitor_checks` / `notifications`. |
| Output | Reuse of the existing `GET /notifications/checklist` and `GET /notifications` to present Worker loss and recovery state; the UI explicitly labels this "deployment-level, not tenant-scoped". |
| Execution mode | No new event-history table; data retrieval reuses the Reader routes, but the governance tab is Admin-only and mounts only for an Admin. |
| Failure handling | When checks have not run or data is missing, a stable empty state is shown; recovery state is never fabricated; a missing item does not block the other governance panels. |

### FR-4 Cleanup failures and unconfirmed cancellation

Traceability: SIG-3; Phase 6 FR-16; ruling R-3.

| Item | Description |
|---|---|
| Trigger | When `runtime_runs.cleanup_status='failed'`, or when `cancel_requested_at` is non-null while `cancel_confirmed_at` is null. |
| Input | `runtime_runs.cleanup_status` (`not_started/in_progress/completed/failed`), `cleanup_updated_at`, `cancel_requested_at`, `cancel_confirmed_at`. |
| Output | Admin `GET /observability/execution/cleanup-failures` returns two categories: `cleanup_status='failed'` and "cancellation requested but unconfirmed"; a UI table; the public `RunView` does not include these fields. |
| Execution mode | Read-only Admin endpoint; the Run state machine and cleanup logic are unchanged; host/workdir cleanup-failure alerts still go only to `LoggingAlertSink` (logs, not a table). |
| Failure handling | Query failures return the FR-1 unified error code; ambiguous states are presented as "unconfirmed" and never falsely reported as cancelled. |

### FR-5 Outbox lag and delivery failures

Traceability: SIG-4; Phase 6 FR-16; rulings R-1 / R-2 / R-8.

| Item | Description |
|---|---|
| Trigger | When an Admin views Outbox operational metrics, or when `runtime_event_outbox` shows pending backlog or a failed `last_error`. |
| Input | `runtime_event_outbox` (`run_id, seq, event_id UNIQUE, status(pending/published), attempts, available_at, created_at, published_at, last_error`); reuse of `pending_count` and rescanning from `events/outbox.py`. |
| Output | Admin `GET /observability/execution/outbox`: pending count, stall seconds of the oldest `available_at`, failed `last_error`, and a 24-hour published count; UI metric cards/table. |
| Execution mode | Read-only query; the table has no `tenant_id` and is joined to `runtime_runs`; no Prometheus is introduced, and `outbox_pending` from `runtime_composition.ExecutionRuntimeSubsystem.operational_stats()` is reused (previously referenced only by tests, now attached to an Admin route). |
| Failure handling | Statistics or rescan errors return a unified error code; no publishing side effect is triggered and delivery success is never fabricated. |

### FR-6 SSE replay gaps

Traceability: SIG-5; Phase 6 FR-16; ruling R-5.

| Item | Description |
|---|---|
| Trigger | When an SSE client cursor predates `runtime_runs.event_retention_floor_seq` and triggers 409 `event_replay_gap`, or when an Admin views gap history. |
| Input | `runtime_runs.event_retention_floor_seq`; the 409 response header `X-Event-Retention-Floor` (`runtime_routes.py`); a new table `execution_replay_gap_events` (migration `0072_execution_replay_gap_events`, planning). |
| Output | One bounded gap event written on the 409 branch, plus an Admin query endpoint and a UI gap list. |
| Execution mode | New migration 0072 (single head re-verified before implementation) plus a bounded write on the 409 branch; SSE `id=sequence`, `event_replay_gap` semantics, and the `X-Event-Retention-Floor` header are unchanged. |
| Failure handling | A gap-event write failure does not block the normal SSE 409 response; a migration-number change requires the bilingual documents to be updated in sync; applied historical migrations must never be modified. |

### FR-7 Usage conflicts and correction chains

Traceability: SIG-6; Phase 6 FR-16; ruling R-2.

| Item | Description |
|---|---|
| Trigger | When `runtime_usage_ledger` contains a `supersedes_id` self-referencing correction chain, or when `UNIQUE(run_id, source, source_event_id)` rejects a duplicate source. |
| Input | `runtime_usage_ledger` (`run_id, tenant_id, lease_epoch, source, source_event_id, usage, cost, is_estimate, supersedes_id`) and the rebuild logic in `events/usage.py::aggregate_effective_usage()`. |
| Output | Admin `GET /observability/execution/usage-conflicts`: the supersession chain and duplicate sources rejected by the uniqueness constraint; the UI displays the correction chain. |
| Execution mode | Read-only query; the table carries its own `tenant_id`; aggregation semantics are unchanged; if a true conflict count is needed, an audit write is added at the unique-conflict/supersede point (Class C component, optional, raised as a separate requirement). |
| Failure handling | Incomplete chain data is presented as the known portion with an explicit marker; usage data is never double-counted or rewritten. |

### FR-8 Parser diagnostics (excluding raw samples)

Traceability: SIG-7; Phase 6 FR-16; rulings R-4 / R-5.

| Item | Description |
|---|---|
| Trigger | When `ParserDiagnosticCollector` records classified counts for `malformed/unknown_schema/unknown_type/size_limit/critical_terminal`, or when an Admin views diagnostic trends. |
| Input | `ParserDiagnosticCollector` in `events/diagnostics.py` with in-memory `self._counts` / `self._suppressed` and an optional sink; a new table `execution_parser_diagnostics` (migration `0073_execution_parser_diagnostics`, planning). |
| Output | An Admin query endpoint plus UI classified counts/trends; only classified counts and bounded, redacted reason codes are displayed. |
| Execution mode | Migration 0073 plus collector/sink wiring in the composition root; reuse of the existing `execution_parser_raw_sample_enabled=false` switch; raw samples and Secrets never enter the UI (Class D sensitive). |
| Failure handling | When the collector is unwired or data is missing, the UI shows an empty state; raw samples or suspected Secrets are never emitted; a migration-number change requires the bilingual documents to be updated in sync. |

### FR-9 Credential revocation and audit

Traceability: SIG-8; Phase 6 FR-16; ruling R-1.

| Item | Description |
|---|---|
| Trigger | When a credential's `status` changes to `revoked` / `superseded`, or when `execution_credential_audit` records a `revoked` / `grant_denied` action. |
| Input | `execution_credentials` (`status active/superseded/revoked`, `version`, `rotated_at`, `revoked_at`), `execution_credential_grants`, and `execution_credential_audit` (`action created/rotated/revoked/grant_issued/grant_denied/grant_used`, `outcome`, `reason_code`, `actor`). |
| Output | The current revocation state reuses `GET /execution-credentials` with zero backend work; a new Admin `GET /observability/execution/credential-audit?action=revoked` plus a UI audit table; `public_metadata()` fields contain no Secrets. |
| Execution mode | Both Admin routes use `require("admin")`; credential routes filter by tenant only and do not apply business_scope; the audit endpoint filters by `tenant_id`. |
| Failure handling | No matching audit returns an empty state; no response returns a Secret; unauthorized access receives 403 `insufficient_role`. |

### FR-10 Frontend execution governance tab (Admin-only, four languages, fail-closed empty state)

Traceability: SIG-1–SIG-8; Phase 6 FR-16; rulings R-7 / R-9.

| Item | Description |
|---|---|
| Trigger | When an Admin enters the "Runs and Audit" page (`observability`, component `frontend/src/features/observability/ObservabilityPage.tsx`) and activates the top "Execution Governance" tab. |
| Input | The `admin` boolean from `useAccess`; `useResource<T>(path, refreshMs)` with `serverPagination` / `clientPagination`; `t('Chinese key')` with the four locales in `src/i18n/locales/{zh-CN,zh-TW,en,hi}.json`. |
| Output | Antd `Tabs` at the top: "Run Overview" retains every existing Panel, while "Execution Governance" is new and Admin-only; the governance sub-panel is extracted as a standalone component, `ExecutionGovernancePanel.tsx`; copy is aligned across all four locales. |
| Execution mode | The governance component mounts only when the governance tab is active and the user is an Admin; no global navigation item is added and the hashRouter is unchanged; follow the `frontend-dev` design rules (single theme color, labels above inputs, no nested gray cards, stable empty states and loading). |
| Failure handling | Non-Admin users do not see the governance tab and do not trigger governance queries; empty data or errors yield a stable fail-closed empty state; `npm run check:i18n` verifies keys across all four locales, and missing keys block release. |

### Configuration switches (existing only, none added)

This phase introduces no new configuration switches. The table below lists only the governance-observability-related switch that already exists in Phase 6 FR-16.

| Switch | Level | Default | Description | Traceability |
|---|---|---|---|---|
| `execution_parser_raw_sample_enabled` | Global settings | `false` | Existing Phase 6 FR-16 switch: raw samples are not retained by default; this phase never brings raw samples or Secrets into the UI, displaying only classified counts and bounded, redacted reason codes. | SIG-7; Phase 6 FR-16; R-4 |

## Non-functional Requirements

- **Permissions**: Every new `/observability/execution/*` endpoint is Admin-only (`require("admin")`), consistent with `/audit` and the credential routes, and is not exposed to Readers; Worker loss reuses the Reader `GET /notifications/*` routes, but the "Execution Governance" tab is Admin-only and mounts only for an Admin; 403 `insufficient_role` is the uniform denial code.
- **Tenant isolation**: `execution_fencing_denials` and `runtime_event_outbox` have no `tenant_id` and must be joined to `runtime_runs` (on run_id) to derive tenant/scope; `worker_heartbeats` is deployment-level with no tenant dimension and is explicitly labeled "deployment-level" in the UI; `runtime_usage_ledger` and `execution_credential_audit` carry their own `tenant_id`; cross-tenant access is denied by default.
- **Secrets**: Raw parser samples and Secrets never enter the UI; only classified counts and bounded, redacted reason codes are displayed; `public_metadata()` and all governance responses contain no Secrets.
- **Multi-language i18n**: Reuse `t('Chinese key')` and the four locales in `src/i18n/locales/{zh-CN,zh-TW,en,hi}.json`; new copy is aligned across all four locales and `npm run check:i18n` must pass.
- **Compatibility**: The public `RunView` is unchanged; cleanup status is exposed only through Admin governance endpoints; SSE `id=sequence`, `event_replay_gap` semantics, and the `X-Event-Retention-Floor` response header are unchanged; the hashRouter and global navigation are unchanged; new fields are used only inside governance endpoints.
- **Lightweight performance**: Governance endpoints use pagination and bounded queries; the governance component mounts on demand, with no queries triggered for ordinary users or other tabs; no Prometheus, `/metrics`, or new monitoring dependency is introduced, and `monitor_checks` / `notifications` plus structured logs are reused.

## Acceptance Criteria

| # | Scenario | Expected | Traceability |
|---|---|---|---|
| AC-1 | Call every `/observability/execution/*` endpoint as an Admin, a Reader, and an ordinary user, injecting tenant/scope filters and a Secret canary. | Only the Admin receives paginated governance data with filters applied; non-Admin callers uniformly receive 403 `insufficient_role`; no response contains a Secret; error codes are unified. | FR-1; SIG-1–SIG-8; Phase 6 FR-16 |
| AC-2 | Produce a fencing denial from one stale-owner write, filter and paginate by time/reason/operation, and inspect the JOIN with `runtime_runs`. | Returned records carry tenant/scope; filtering and pagination are correct; the UI table renders; orphan records are labeled deployment-level with no Secrets. | FR-2; SIG-1; Phase 6 FR-16 |
| AC-3 | Stop a Worker heartbeat to trigger `worker.runtime.heartbeat` / `runtime.lease_expired`, then open the governance panel. | Reused checklist/notifications show loss and recovery state; the UI explicitly labels "deployment-level, not tenant-scoped"; no event-history table is created; Reader route behavior is unchanged. | FR-3; SIG-2; Phase 6 FR-16 |
| AC-4 | Set `cleanup_status='failed'`, and separately set `cancel_requested_at` non-null with `cancel_confirmed_at` null, then call the cleanup-failure endpoint. | Both categories are returned; public `RunView` fields are unchanged; host/workdir alerts remain in logs; ambiguous states are not falsely reported as cancelled. | FR-4; SIG-3; Phase 6 FR-16 |
| AC-5 | Inject Outbox rows with pending backlog (an old `available_at`) and a failed `last_error`, then call the outbox endpoint. | The pending count, stall seconds, failed `last_error`, and 24-hour published count are returned; UI metric cards/table render; no publishing side effect is triggered. | FR-5; SIG-4; Phase 6 FR-16 |
| AC-6 | Place a client cursor before `event_retention_floor_seq` to trigger 409 `event_replay_gap` and the `X-Event-Retention-Floor` header, then query the gap endpoint. | One bounded gap event is written on the 409 branch and visible in the query; SSE `id` / `event_replay_gap` / header semantics are unchanged; migration 0072 was re-verified against the head before implementation. | FR-6; SIG-5; Phase 6 FR-16 |
| AC-7 | Produce a duplicate source rejected by `UNIQUE(run_id, source, source_event_id)` and a `supersedes_id` correction chain, then call the usage-conflict endpoint. | The chain and duplicate source are visible and filtered by `tenant_id`; aggregation semantics are unchanged with no double counting; optional true conflict counting is not enabled by default in this phase. | FR-7; SIG-6; Phase 6 FR-16 |
| AC-8 | Inject malformed / unknown_schema / unknown_type / size_limit / critical_terminal events and a Secret-canary sample, then view the parser endpoint and UI. | Only classified counts/trends and bounded, redacted reason codes are displayed; zero raw samples or Secrets appear; migration 0073 was re-verified against the head before implementation; the collector is wired. | FR-8; SIG-7; Phase 6 FR-16 |
| AC-9 | Revoke a credential, then call `GET /execution-credentials` and `GET /observability/execution/credential-audit?action=revoked`. | The existing route shows status revoked; audit rows are visible and filtered by tenant; `public_metadata()` contains no Secret; unauthorized access receives 403. | FR-9; SIG-8; Phase 6 FR-16 |
| AC-10 | Enter "Runs and Audit" as an ordinary user and as an Admin, switch both tabs, and force empty-data and error responses. | The governance tab is Admin-only; the component mounts only when the governance tab is active and the user is an Admin; empty states fail closed; all four locales are aligned and `npm run check:i18n` passes; hashRouter/global navigation are unchanged. | FR-10; SIG-1–SIG-8; Phase 6 FR-16 |
