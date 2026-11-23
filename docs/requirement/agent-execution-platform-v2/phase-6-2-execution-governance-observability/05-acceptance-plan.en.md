# Phase 6-2 · Execution Governance Observability — Acceptance Plan

> Status: Approved documentation-scope baseline for subsequent acceptance; not implemented, not tested, not accepted. This document describes only how acceptance will be conducted and contains no acceptance conclusion.
> Created: 2026-11-22
> Basis: Phase 6 `02-requirements.md` FR-16 (operability); this phase's `01-business-goals.md` (G1–G4), `02-requirements.md` (FR-1–FR-10, AC-1–AC-10), and `08-implementation-breakdown.md` (T-1–T-14, R-1–R-10, A-1–A-10, C-1–C-6); frozen SIG-1–SIG-8 classifications from the approved scope baseline. Test execution is governed by this phase's `04-test-plan.md`.
> Scope note: The acceptance object is limited to the unified governance query API and visual UI. Performance baselines, a real untrusted execution environment, and high-risk capability enablement are out of scope or historical context only and are not stage-acceptance gates. All IDs and wording align verbatim with the baseline; `0072` / `0073` are planning values.

## 1. Acceptance Scope and Responsibility

Confirm A-1–A-10, which map one-to-one to AC-1–AC-10, checking permission/tenant isolation, zero Secret exposure, data integrity and migration, and zero-change compatibility, and verify a single acceptance-owner record. The acceptance owner organizes and records the verdict; the executor prepares isolated environments, performs supplementary checks, and assembles evidence. One person may hold both responsibilities, but this must be stated in the record. Do not invent independent product, QA, business, or finance roles. The trustworthiness of usage and audit data is proven by A-7, C-2, C-4, and automated reconciliation evidence, not by a finance signature replacing technical evidence.

This stage does not open untrusted multi-tenancy or production Codex routes and does not claim high-risk capability enablement or production rollout (R-10). Passing stage acceptance does not authorize those capabilities; the related approvals must be obtained separately outside this stage and are not presupposed here.

## 2. Acceptance Environments and Prerequisites

| Environment | Purpose |
|---|---|
| Unit + PG shard environment | Governance endpoint semantics, permission denial, tenant JOIN, pagination, real table data, `0072` / `0073` upgrade and persistence, concurrent unique constraints |
| Playwright mock harness environment | Tab visibility, admin gating, on-demand mounting, eight panels, filtering/pagination, empty states, four locales, and no Secret text |
| Static check / CI environment | ruff, check:i18n, typecheck, build, single migration head, no Prometheus dependency |

**Prerequisites**: The relevant T-1–T-14 tasks are complete per `08-implementation-breakdown.md`; UT-1–UT-14, IT-1–IT-8, FE-1–FE-10, and CM-1–CM-6 have actually been executed with independent verdicts; the migration head has been rechecked and recorded. None of these prerequisites currently hold — the stage is not implemented, not tested, and not accepted. A genuinely untrusted environment, performance-baseline samples, and high-risk enablement are not prerequisites (see Section 6). Use only revocable canaries; real Secrets are prohibited.

## 3. Functional Acceptance Scenarios A-1–A-10 (One-to-One with AC-1–AC-10)

| # | Scenario | Steps | Expected | Evidence | Traceability |
|---|---|---|---|---|---|
| A-1 | Unified governance API permissions and error codes | Call all `/observability/execution/*` endpoints as admin, Reader, and an ordinary user; inject tenant/scope filters and a Secret canary; construct invalid pagination | Only admin receives paginated governance data with filters applied; all non-admin callers receive 403 `insufficient_role`; invalid filters/pagination return 400; no response contains a Secret | UT-1, UT-2, UT-10, UT-11; `06-test-report.md` (not yet generated); CI run (to be recorded); single acceptance-owner record | AC-1; FR-1; SIG-1–SIG-8; Phase 6 FR-16 |
| A-2 | Fencing denial query | Produce a fencing denial from a stale-owner write, filter by time / reason / operation with pagination, and inspect JOIN `runtime_runs` results | Rows carry tenant/scope; filtering and pagination are correct; the UI table renders; orphan rows are labeled deployment-level with no Secret | UT-3, UT-9; IT-2; FE-3; `06-test-report.md` (not yet generated); single acceptance-owner record | AC-2; FR-2; SIG-1; Phase 6 FR-16 |
| A-3 | Worker loss and recovery state | Stop a Worker heartbeat to trigger `worker.runtime.heartbeat` / `runtime.lease_expired` checks (controlled fixture), then open the governance panel | Reuse `GET /notifications/checklist` and `GET /notifications` to show loss and recovery; the UI explicitly says "deployment-level, not tenant-scoped"; no new event-history table; Reader route behavior is unchanged | FE-4, FE-6; CM-6; `06-test-report.md` (not yet generated); single acceptance-owner record | AC-3; FR-3; SIG-2; Phase 6 FR-16 |
| A-4 | Cleanup failures and unconfirmed cancellation | Set `cleanup_status='failed'`, then set a non-null `cancel_requested_at` with a null `cancel_confirmed_at`; call the cleanup-failure endpoint | Both categories are returned; public `RunView` fields have zero diff; host/workdir alerts remain in logs; ambiguous state is not reported as cancelled | UT-4; IT-3; FE-9; `06-test-report.md` (not yet generated); single acceptance-owner record | AC-4; FR-4; SIG-3; Phase 6 FR-16 |
| A-5 | Outbox lag and delivery failures | Inject `runtime_event_outbox` rows with pending retention (older `available_at`) and failed `last_error`; call the outbox endpoint | Returns pending count, lag seconds, failed `last_error`, and the 24-hour published count; UI metric cards/table render; no publication side effect; no Prometheus | UT-5; IT-4; CM-6; FE-3; `06-test-report.md` (not yet generated); single acceptance-owner record | AC-5; FR-5; SIG-4; Phase 6 FR-16 |
| A-6 | SSE replay gap | Place the client cursor before `event_retention_floor_seq` to trigger 409 `event_replay_gap` and the `X-Event-Retention-Floor` header, then query the gap endpoint | The 409 branch writes one bounded gap event that is queryable; SSE `id` / `event_replay_gap` / header semantics are unchanged; migration `0072` head was rechecked before implementation | UT-12, UT-13; IT-1, IT-6; CM-5; FE-9; `06-test-report.md` (not yet generated); single acceptance-owner record | AC-6; FR-6; SIG-5; Phase 6 FR-16 |
| A-7 | Usage conflicts and correction chain | Produce duplicate sources rejected by `UNIQUE(run_id, source, source_event_id)` and a `supersedes_id` chain; call the usage-conflicts endpoint | Chain and duplicate sources are visible and filtered by `tenant_id`; aggregation is unchanged with no double counting; optional real-conflict counting is not enabled by default in this stage | UT-6; IT-5; FE-3; `06-test-report.md` (not yet generated); single acceptance-owner record | AC-7; FR-7; SIG-6; Phase 6 FR-16 |
| A-8 | Parser diagnostics without raw samples | Inject `malformed` / `unknown_schema` / `unknown_type` / `size_limit` / `critical_terminal` events plus a Secret-canary sample; inspect the parser endpoint and UI | Only category counts/trends and bounded, redacted reason codes are shown; raw samples and Secrets have zero presence; migration `0073` head was rechecked before implementation; the collector is wired | UT-8, UT-14; IT-1, IT-7; CM-5; FE-4, FE-8; `06-test-report.md` (not yet generated); single acceptance-owner record | AC-8; FR-8; SIG-7; Phase 6 FR-16 |
| A-9 | Credential revocation and audit | Revoke one credential; call `GET /execution-credentials` and `GET /observability/execution/credential-audit?action=revoked` | Status shows revoked on the existing route; audit rows are visible and filtered by tenant; `public_metadata()` contains no Secret; unauthorized access returns 403 | UT-7; IT-8; FE-4, FE-8; `06-test-report.md` (not yet generated); single acceptance-owner record | AC-9; FR-9; SIG-8; Phase 6 FR-16 |
| A-10 | Frontend governance tab | As an ordinary user and then admin, enter the "Runs and Audit" page, switch both tabs, force empty data and error responses, and switch among `zh-CN` / `zh-TW` / `en` / `hi` | The governance tab is visible to admin only; the component mounts only when the governance tab is active and the user is admin; empty states fail closed; four locales are aligned and `npm run check:i18n` passes; `hashRouter` / global navigation have zero change; public `RunView` / SSE have zero change | FE-1, FE-2, FE-5, FE-6, FE-7, FE-8, FE-9, FE-10; CM-2, CM-3, CM-4; `06-test-report.md` (not yet generated); single acceptance-owner record | AC-10; FR-10; SIG-1–SIG-8; Phase 6 FR-16 |

For every scenario, record after execution: executor, date, environment, versions, attack/fault point or controlled fixture, prerequisite data, actual result, verdict, and log/DB/DOM evidence links. When a hard-gate environment is unavailable, mark it `pending_env`; the stage must not pass. Evidence should reference the corresponding UT / IT / FE / CM and CI results in `04-test-plan.md` wherever possible rather than repeating the full suite; evidence reuse does not relax the gates or the no-invented-roles requirement.

## 4. Key Manual Checks M-1–M-3

Use these only to supplement client semantics and messaging that automation does not fully cover. Do not create client or business-representative roles. Record executor, target SHA, result, and evidence for each.

| # | Check | Pass criterion |
|---|---|---|
| M-1 | Exercise tab switching, governance request timing, and filter/pagination interaction in the UI | A non-admin triggers no governance request; empty states and error messages fail closed; no fabricated recovery state or success appears |
| M-2 | Inspect governance-panel messages and error copy | Copy contains no Secret / host details and retains correlation information needed for operational diagnosis |
| M-3 | Inspect copy and empty states after switching among four locales | `zh-CN` / `zh-TW` / `en` / `hi` are aligned and consistent; missing keys are blocked by `check:i18n` |

## 5. Acceptance Gates C-1–C-6 (Verbatim from the Approved Scope Baseline)

| Gate | Gate content (verbatim from baseline) | Pass condition | Evidence | Traceability |
|---|---|---|---|---|
| C-1 | C-1 功能语义 (functional semantics) | All steps and expected results of A-1–A-10 hold; seven governance endpoints and eight panel categories return and render per FR-1–FR-10; uniform error codes and empty states satisfy the constraints | A-1–A-10 records; UT / IT / FE independent verdicts; `06-test-report.md` (not yet generated) | FR-1–FR-10; AC-1–AC-10; G1 |
| C-2 | C-2 租户/权限隔离 (tenant/permission isolation) | All new `/observability/execution/*` endpoints are admin-only, with 403 `insufficient_role` for all non-admin callers; tables without `tenant_id` JOIN `runtime_runs`; cross-tenant access is denied by default; `worker_heartbeats` is labeled deployment-level | UT-1, UT-2, UT-9; IT-2, IT-8; A-1, A-2, A-7, A-9; single acceptance-owner record | FR-1, FR-2, FR-5, FR-7, FR-9; R-1, R-2; G2 |
| C-3 | C-3 Secret 与脱敏 (Secret handling and redaction) | Governance responses, `public_metadata()`, diagnostics, and the UI contain no Secret; raw parser samples and Secrets have zero presence, with only category counts and bounded, redacted reason codes | UT-10, UT-8; IT-7; FE-8; CM-6; A-1, A-8, A-9; single acceptance-owner record | FR-1, FR-8, FR-9; R-4; G2 |
| C-4 | C-4 数据完整性与迁移 (data integrity and migration) | The migration head is rechecked to a single head; `0072` / `0073` agree with the recheck; applied historical migrations are unmodified; 409 gaps and parser sink persistence are bounded; pagination and JOIN semantics are correct; concurrent unique constraints take effect | UT-13, UT-14; IT-1, IT-2, IT-5, IT-6, IT-7; CM-5; A-6, A-8; single acceptance-owner record | FR-6, FR-8; R-5; G4 |
| C-5 | C-5 兼容性（公开 RunView/SSE 不变） (compatibility: public RunView/SSE unchanged) | Public `RunView` fields have zero change; SSE `id=sequence` / `event_replay_gap` / `X-Event-Retention-Floor` have zero change; `hashRouter` and global navigation have zero change; the Reader `GET /notifications/*` behavior is unchanged; no Prometheus | UT-4, UT-12; IT-3, IT-6; FE-9, FE-10; CM-1, CM-6; A-4, A-6, A-10; single acceptance-owner record | FR-3, FR-4, FR-6, FR-10; R-3, R-7, R-8; G3 |
| C-6 | C-6 无 P0/P1 且单一验收记录 (no P0/P1 and a single acceptance record) | No P0 / P1 exists; M-1–M-3 are complete or have equivalent automated evidence; there is exactly one acceptance-owner record and no invented multi-role signature | `06-test-report.md` (not yet generated); `07-acceptance-report.md` (not yet generated); single acceptance-owner record (to be filled in) | All FR / AC; G4 |

## 6. Scope Limitations

- **Performance baselines**: p50 / p95, Outbox lag thresholds, capacity and sample counts are historical context or capacity-review material only and are not stage gates; their absence creates no `pending_env` and cannot determine pass or fail.
- **Real untrusted execution environment**: real sandbox escapes, network attacks, and multi-Worker fault injection are outside this stage. Governance signals are produced by deterministic fixtures, PG shards, and the Playwright mock harness; the absence of a genuinely untrusted environment is not a stage blocker.
- **High-risk enablement**: untrusted multi-tenancy, production Codex routes, and production rollout are out of scope (R-10), are not stage gates, and passing stage acceptance does not authorize them.
- None of the above three items are written into the pass conditions of A-1–A-10 / C-1–C-6, and they may not be used to mask functional, permission, Secret, data-integrity, migration, or compatibility problems.

## 7. Evidence Requirements

1. **Test report ID**: Independent verdicts for UT / IT / FE / CM are consolidated in `06-test-report.md`. That file is not yet generated; the report ID is assigned only after actual execution and must not be pre-filled or pre-written.
2. **CI run**: The CI run identifier and link are recorded in the report only after actual execution. No CI run ID exists yet and none may be fabricated.
3. **Single acceptance-owner record**: Exactly one record is kept, with fields for acceptance owner, executor, date, target SHA, verdict, and evidence/residuals. The acceptance owner and executor are not yet designated and will be confirmed by the user at execution time; no name, role, or signature is invented.
4. **Report status**: `06-test-report.md` / `07-acceptance-report.md` are not yet generated and, per R-6, are not pre-written. No issue or PR number is registered (none exists).

## 8. Acceptance Conclusion Rules

- **Stage pass**: A-1–A-10 and C-1–C-6 all pass, M-1–M-3 are complete or have equivalent automated evidence, and no P0 / P1 remains. Functional and compatibility criteria are judged from controlled-fixture and mock-harness evidence. There is exactly one acceptance-owner record and no invented roles. Stage pass does not authorize high-risk capability enablement or production rollout.
- **Conditional pass**: Only P2 / P3 residuals remain that are not security-, permission/tenant-, Secret-, data-integrity/migration-, compatibility-, or P0/P1-related, each with an owner and deadline plus an explanation by the acceptance owner in the single record. Even a conditional pass does not authorize high-risk enablement.
- **Fail**: any gate fails, or an effective privilege escalation, Secret disclosure, silent data gap, public-contract change, or A/C functional/security criterion failure occurs; after fixes, rerun affected items and controlled regressions.
- **`pending_env` is never rewritten as a pass**: an unavailable environment may only be marked `pending_env`; it is not counted toward C-1–C-6, and the stage remains "not tested, not accepted".
- **No invented roles**: no independent product, QA, business, finance, or security signature role is created. The acceptance owner and executor may be the same person but must be recorded truthfully. Without the required personnel or evidence, no gate may pass.
- **No inferred status**: a complete documentation baseline, a full set of case IDs, or finished scenario wording is not evidence that anything is implemented, tested, or accepted. Only after reports are actually generated, evidence is complete, and no P0 / P1 remains may the acceptance owner issue a verdict; until then the verdict field stays "pending acceptance (reports not yet generated)".
