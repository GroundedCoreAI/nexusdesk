# Phase 6-2 · Execution Governance Observability — Business Goals

> Status: Approved documentation scope baseline for subsequent implementation; not implemented, not tested, not accepted
> Created: 2026-11-22
> Basis: Phase 6 `02-requirements.en.md` FR-16 (Operability); this phase's `01-business-goals.en.md`; signal classification and frozen numbering follow the approved scope baseline (SIG-1–SIG-8, G1–G4, US-1–US-4, FR-1–FR-10, AC-1–AC-10).
> Scope note: This phase adds only a unified governance query API and a visualization UI. It does not change execution semantics, add execution branches, open untrusted multi-tenancy, or claim production readiness.

## Background

Phase 6 FR-16 (Operability) requires metrics, alerts, and audit for Fencing denials, Worker loss, cleanup failures, Outbox lag, replay gaps, usage conflicts, parser errors, and revocations. Phase 6 has already persisted these governance facts in tables, logs, monitor checks, and in-memory counters:

- Tables: `execution_fencing_denials`, `runtime_event_outbox`, `runtime_usage_ledger`, `execution_credentials` / `execution_credential_grants` / `execution_credential_audit`, `worker_heartbeats`, and `cleanup_status` / `cleanup_updated_at` / `cancel_requested_at` / `cancel_confirmed_at` / `event_retention_floor_seq` on `runtime_runs`.
- Monitor checks: `worker.runtime.heartbeat` and `runtime.lease_expired` feeding `monitor_checks` / `notifications`.
- In-memory counters: `ParserDiagnosticCollector`'s `self._counts` / `self._suppressed` (not yet wired through an instantiation in the composition root).

Phase 6, however, provides neither a unified governance query API nor a governance UI. `GET /api/v1/observability/summary` (Reader) contains no governance signals, and `GET /api/v1/audit` (Admin) reads `audit_records`, which excludes fencing and credential governance audit. The assessment of the eight signal classes is: Class A (already persisted with a usable API) covers only SIG-2 and the status portion of SIG-8; Class B (persisted but no query API) covers SIG-1, SIG-3, SIG-4, SIG-6, and the audit portion of SIG-8; Class C (missing persistence or wiring) covers SIG-5 and SIG-7; Class D (sensitive content, never in the UI) covers raw parser samples and Secrets.

This phase is scoped to "query API plus visualization UI only": it does not rewrite those facts, add execution branches, or introduce new monitoring dependencies.

## Problem Statement

### Problem 1: Governance facts are persisted, but SREs and administrators have no unified query entry point

Except for SIG-2, which reuses the Reader endpoints `GET /notifications/checklist` and `GET /notifications`, and the SIG-8 status portion, which reuses `GET /execution-credentials`, no route reads the remaining signals: `execution_fencing_denials`, `runtime_event_outbox`, `runtime_usage_ledger`, `execution_credential_audit`, and `runtime_runs.cleanup_status` all lack query endpoints; `operational_stats().outbox_pending` is referenced only by tests and is not attached to a route. SREs and administrators can only query the database directly or scan logs, with no single entry point to filter by tenant/scope, time, reason, operation, and similar dimensions.

### Problem 2: Governance signals have no UI, so fencing denials, Outbox lag, and cleanup failures are invisible

The existing global page "Runs and Audit" (`observability`) is a vertically stacked Panel layout with no governance tab and no governance panels. SREs and administrators cannot see fencing denials, Outbox backlog, cleanup failures and unconfirmed cancellations, SSE replay gaps, usage correction chains, credential revocation audit, or parser diagnostics in the interface. They can only react to alerts after the fact, without a way to inspect governance state proactively.

### Problem 3: Expanding visibility must simultaneously preserve isolation, compatibility, and redaction boundaries

Visibility is not simply a matter of reading the data out. `execution_fencing_denials`, `runtime_event_outbox`, and `worker_heartbeats` have no `tenant_id` column and must be joined to `runtime_runs` (on run_id) to derive tenant/scope, or be restricted to Admin and explicitly labeled deployment-level. The public `RunView` does not include cleanup fields, so the public contract must not be changed for the sake of the UI. Raw parser samples and Secrets are Class D sensitive content and must never enter the UI. SIG-5 and SIG-7 also lack persistence and wiring; the new migration numbers 0072 and 0073 are planning values, and the single head must be re-verified before implementation.

## Business Goals

| Goal | Description |
|---|---|
| G1 Make governance signals visible | All eight classes of governance signals are surfaced through a unified Admin query API and an "Execution Governance" tab; SREs and administrators can proactively inspect fencing denials, Outbox lag, cleanup failures, replay gaps, usage conflicts, parser diagnostics, and credential revocation audit. |
| G2 Security and no Secret leakage | Every new `/observability/execution/*` endpoint is Admin-only; no Secret and no raw parser sample enters any response or UI; tenant/scope isolation and non-Admin denial both fail closed. |
| G3 Compatibility, no execution-semantic change | The public `RunView`, SSE semantics, the `X-Event-Retention-Floor` response header, the hashRouter, and global navigation remain unchanged; no execution branch is added, cleanup and aggregation logic are untouched, and no Prometheus or new monitoring dependency is introduced. |
| G4 Verifiable and traceable | Every FR has a corresponding AC and SIG traceability entry; governance data is traceable to a run by tenant/scope and run_id; empty states and errors are uniform and verifiable; migrations 0072 and 0073 re-verify the head before implementation, with the bilingual documents updated in sync. |

## Success Metrics

| Metric | Baseline (current) | Target |
|---|---|---|
| Visibility coverage | None of the eight signal classes has both a unified query API and a UI (SIG-2 only reuses the Reader checklist/notifications; the SIG-8 status portion only reuses `GET /execution-credentials`). | All eight signal classes have an Admin-queryable endpoint and are visible in the "Execution Governance" tab (SIG-2 reuses the Reader route, the SIG-8 status portion reuses the existing route); 100% of governance data is visible, with fail-closed empty states. |
| Permission compliance | Zero new governance endpoints; governance data is readable only through Admin routes (`/audit` and credential routes). | Every `/observability/execution/*` endpoint is Admin-only; non-Admin callers uniformly receive 403 `insufficient_role`; ordinary users and other tabs do not trigger governance queries. |
| Zero Secret leakage | Existing public views and `public_metadata()` contain no Secrets. | Zero Secret or raw parser sample disclosures in governance responses and the UI; only classified counts and bounded, redacted reason codes are displayed. |
| Compatibility | The public `RunView`, SSE, the hashRouter, and existing four-language i18n keys remain unchanged. | Zero change to public `RunView` fields, to `event_replay_gap` / `X-Event-Retention-Floor` semantics, or to the hashRouter and global navigation; `npm run check:i18n` passes with keys aligned across all four locales. |
| Lightweight performance | Governance queries are not implemented; there is no `/metrics` and no Prometheus. | Governance endpoints use pagination and bounded queries, and the governance tab mounts on demand; no Prometheus or new monitoring dependency is introduced; reuse `monitor_checks` / `notifications` and structured logs. |

## Scope

**Included**:

- A unified Admin query API for the eight governance signal classes (`/api/v1/observability/execution/*`), with permission handling and tenant/scope filtering (tables without a `tenant_id` are joined to `runtime_runs`).
- Antd `Tabs` at the top of the "Runs and Audit" page: "Run Overview" retains every existing Panel, while "Execution Governance" is new and Admin-only; the governance sub-panel is extracted as a standalone component, `ExecutionGovernancePanel.tsx`, mounted on demand.
- New migrations `0072_execution_replay_gap_events` (SIG-5) and `0073_execution_parser_diagnostics` (SIG-7), both planning values with the single head re-verified before implementation, plus a bounded write point on the 409 branch and parser collector/sink wiring in the composition root.
- Redaction, stable fail-closed empty states, four-language i18n copy, and `npm run check:i18n`; reuse of `monitor_checks` / `notifications` and structured logs.

**Excluded** (later phase / explicitly out of scope):

- No untrusted multi-tenancy or production Codex routes; no claim that high-risk capabilities are enabled or that production is cleared (R-10).
- No Prometheus, `/metrics`, or any new monitoring dependency (R-8; Phase 7 documentation also explicitly excludes Prometheus).
- No change to execution semantics, no added execution branches, no change to the public `RunView`, no change to SSE semantics or response headers, and no change to the hashRouter or global navigation (R-3, R-7).
- No Worker-loss event-history timeline table (to be raised as a separate requirement if needed); no false reporting of actual exit/cancellation confirmation for UI convenience.
- Raw parser samples and Secrets never enter the UI (R-4); no issue or PR numbers are registered; `06-test-report.md` and `07-acceptance-report.md` are not pre-written (R-6).

## Relationship to Other Phases

- **Phase 6 (upstream)**: Provides the persistence of governance facts and the FR-16 (Operability) requirement. This phase does not rewrite those facts; it adds only a unified query API and UI on top of them.
- **Phase 7**: Explicitly excludes Prometheus. This phase likewise introduces no Prometheus or new monitoring dependency, reusing only `monitor_checks` / `notifications` and structured logs.
- **Later requirements**: A Worker-loss history timeline and true usage-conflict counting (the optional Class C component) may be raised as separate requirements; this phase makes no production-readiness claim.
- **06 / 07 reports**: Per project convention, these are created only after actual testing and acceptance; they are not pre-written in this phase.

## Risks and Constraints

- **Migration numbers are planning values**: 0072 and 0073 must have the single head dynamically re-verified before implementation, and the bilingual documents updated in sync if it changes; applied historical migrations must never be modified (R-5).
- **Tables without a `tenant_id`**: `execution_fencing_denials` and `runtime_event_outbox` must be joined to `runtime_runs`; `worker_heartbeats` is deployment-level with no tenant dimension and must be explicitly labeled "deployment-level" in the UI (R-2).
- **Public contract unchanged**: The public `RunView` is not modified; cleanup status is exposed only through Admin governance endpoints (R-3).
- **Sensitive content**: Raw parser samples and Secrets never enter the UI; only classified counts and bounded, redacted reason codes are displayed (R-4).
- **Frontend design rules**: Follow the `frontend-dev` rules—a single theme color, labels above inputs, no nested gray cards, and stable empty states and loading indicators (R-9).
