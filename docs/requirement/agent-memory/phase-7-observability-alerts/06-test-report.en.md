# Phase 7 · Production Observability & Alerting — Test Report

> Status: executed (exit criteria NOT met; 3 open P1 defects pending fix + regression)
> Executed: 2026-10-27, Task 5a (full functional test matrix on a real PostgreSQL)
> Reference: `04-test-plan.md` (P7-UT-01~11, P7-IT-01~13, P7-API-01~04, P7-FE-01~04, §8 exit criteria)

## 1. Execution environment

| Item | Value |
|---|---|
| Branch / commit | `feat/memory-observability-alerts` @ `b0fe1cd` (Phase 7 range `849d053..HEAD`; the new performance test is commit `0abed55`) |
| Database | PostgreSQL 17.11 (Debian, aarch64), Docker container `nexusdesk-pg17` (`pgvector/pgvector:pg17`), pgvector 0.8.7 |
| Test databases | `nexusdesk_test` (migrated to alembic head `0042_memory_observability`); migration tests derive random disposable databases from `nexusdesk_migtest` |
| Backend runtime | Python 3.11.9, pytest 9.1.1, pytest-asyncio 1.4.0 (`backend/.venv`, uv-managed) |
| Frontend | Vite 7 dev server (:5173), Playwright Chromium headless |
| Env vars | `TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/nexusdesk_test`; `MIGRATION_TEST_DATABASE_URL=.../nexusdesk_migtest` |

Note: all Phase 7 PG suites (`*_postgres.py`, migrations) ran on a real PostgreSQL **for the first time** (previously always skipped without `TEST_DATABASE_URL`); with pgvector present, the vector-gated cases (vector search leg, embedding retry audit) actually ran.

## 2. Scope vs. principles

| Principle (04-test-plan §1) | Outcome |
|---|---|
| 1 Value reconciliation | The main reconciliation case `test_p7_it_memory_summary_health_sections_reconcile` is blocked by defect D1 (FAIL); empty-tenant structure/defaults pass; per-section reconciliations (embedding retry, maintenance audits, search modes) pass |
| 2 No waiting in time-based cases | Confirmed: aging/overdue constructed by rewriting DB timestamps, alert checks triggered as single manual passes; 3 PG files / 25 cases in 9.2s |
| 3 Alerts prefer misses over false positives | R3 restart resampling, R4 small-sample gate, R5/R6 exemptions, R8 embedded exemption all green in unit tests; the PG regression that heartbeat rows are not R5 evidence passes |
| 4 Zero sensitive data in alerts | Static scan: zero findings (§5); the dedicated dynamic case is blocked by defect D2; shape assertions (details ⊆ {value,threshold,window}) hold in the passing cases |
| 5 Existing observability unbroken | Phase 1-6 regression: 642 passed, zero non-Phase-7 failures; the Phase 4 observability-page frontend spec passes |

## 3. Results matrix (test-plan ID mapping)

### 3.1 Unit tests (P7-UT)

Command: `uv run pytest tests/test_memory_alerting.py tests/test_memory_observability_summary.py tests/test_memory_search_tool.py` → **36 passed in 0.29s** (includes 9 pre-existing search_tool cases).

| ID | Implementing test(s) | Result |
|---|---|---|
| P7-UT-01 R1 task failed | `test_memory_alerting.py::test_r1_task_failed_truth_table` | PASS |
| P7-UT-02 R2 backlog age | `test_r2_pending_task_age_truth_table` | PASS |
| P7-UT-03 R3 embedding growing | `test_r3_rising_across_two_consecutive_scans_fires_on_third`, `test_r3_not_rising_or_zero_backlog_stays_quiet`, `test_r3_restart_resamples_from_scratch` | PASS |
| P7-UT-04 R4 fallback rate | `test_r4_minimum_calls_gate` (25% rate / 25 calls fires; 15 calls silent; 10% rate silent) | PASS |
| P7-UT-05 R5 maintenance silent | `test_r5_exemptions_and_fire` | PASS |
| P7-UT-06 R6 rule scan missed | `test_r6_exemptions_and_fire`, `test_scanner_interval_zero_disables` | PASS |
| P7-UT-07 R7 pending backlog | `test_r7_pending_backlog_threshold` (exactly-at-threshold silent) | PASS |
| P7-UT-08 R8 worker heartbeat | `test_r8_standalone_only` (quickstart embedded exempt) | PASS |
| P7-UT-09 cooldown | `test_cooldown_active_pure_logic` (end-to-end cooldown under P7-IT-07) | PASS |
| P7-UT-10 duration_ms recording | Covered by the PG case `test_memory_observability_postgres.py::test_p7_it_duration_ms_written_for_done_and_failed` (done/failed/retry-requeue all timed); no unit-level case — the worker needs a real engine | PASS (PG layer) |
| P7-UT-11 degrade-source selection (D3) | `test_memory_observability_summary.py`, 5 cases: detail four-section split, no-run no-average, events-mode lumping of profile/preference, etc. | PASS |

### 3.2 Integration tests (P7-IT, first real-PG execution)

Command: `uv run pytest tests/test_memory_observability_postgres.py tests/test_memory_alerting_postgres.py tests/test_memory_observability_summary_postgres.py tests/test_memory_observability_migrations.py` → 26 cases: **20 passed, 5 failed, plus 1 migration case passed**; zero skips.

| ID | Implementing test(s) | Result | Notes |
|---|---|---|---|
| P7-IT-01 task health metrics | `test_p7_it_memory_summary_health_sections_reconcile` (main reconciliation); `test_p7_it_duration_ms_written_for_done_and_failed` | **FAIL / PASS** | Main reconciliation blocked by D1; three-state duration recording passes |
| P7-IT-02 embedding metrics | Same reconciliation case; `test_p7_it_embedding_retry_audit_counts_outcomes` | **FAIL / PASS** | Retry audit {scanned:2,succeeded:1,failed:1} reconciles; summary section blocked by D1 |
| P7-IT-03 search modes & quality | `test_p7_it_search_event_modes` | PASS | text/keyword_fallback/vector modes all executed (pgvector image; vector leg not skipped); hits/returned reconcile |
| P7-IT-04 maintenance health | `test_p7_it_maintenance_audits_ttl_and_injection_purge`, `test_p7_it_maintenance_quiet_pass_writes_no_audit`, `test_p7_it_maintenance_failure_writes_failed_audit_and_reraises`, `test_p7_it_rule_scan_audit`, `test_p7_it_rule_scan_not_overdue_when_scan_disabled` | PASS | Per-job audit shapes, silent quiet passes, failure audit + re-raise, overdue-list semantics all as designed |
| P7-IT-05 agent dimension | agents section inside the main reconciliation case | **FAIL** | Blocked by D1 (seed cannot insert runtime_runs) |
| P7-IT-06 alert end-to-end | `test_alert_task_failed_writes_audit_and_cooldown_suppresses` | PASS | R1 condition → single scan → `memory.alert.task_failed` persisted; details exactly {value:1,threshold:0,window:"15m"} |
| P7-IT-07 alert cooldown | Cooldown half of the same case (second scan adds nothing) | PASS | Post-cooldown re-fire covered by the unit truth table |
| P7-IT-08 R4/R5/R6 firing | R4: `test_r4_vector_fallback_fires_above_rate_with_min_calls`; R5: `test_r5_maintenance_silent_fires_with_activity_and_is_exempt_when_idle`, `test_r5_heartbeat_rows_are_not_maintenance_evidence`; R6: `test_r6_exempt_without_overdue_tickets`, `test_r6_fires_with_overdue_tickets_and_no_evidence`; plus R3 PG: `test_r3_rising_backlog_across_three_scans_fires` | **R4 FAIL / R3 FAIL; R5, R6 PASS** | R4 blocked by D1; R3 blocked by D2; the R5 heartbeat-exclusion regression (review-fix item) passes |
| P7-IT-09 webhook | `test_webhook_payload_shape_and_failure_isolated` | PASS | Payload exactly {rule,tenant,value,threshold,window,at}, timeout=5; a TimeoutError sender still lets the scan complete and the audit persist |
| P7-IT-10 master switch | `test_master_switch_off_writes_nothing` (+ unit `test_scanner_master_switch_off_never_touches_db`) | PASS | Disabled: no scan, no audits, no heartbeat; metrics endpoints unaffected (regression green) |
| P7-IT-11 no sensitive data in alerts | Dynamic: `test_alert_details_never_carry_content`; static: full alert/webhook payload code-path scan (§5) | **Dynamic FAIL (blocked by D2) / static PASS** | Zero static findings; shape assertions hold in passing cases; dedicated case must be re-run after the D2 fix |
| P7-IT-12 migration backfill | `test_memory_observability_migrations.py::test_0042_adds_duration_ms_and_downgrade_drops_it` (random disposable DB, upgrade/downgrade) | PASS | 0042 only adds `duration_ms` (D1 adjustment: created_at exists since 0030, no run_after backfill needed); NULL-row aggregation exclusion covered by the IT-01 duration case |
| P7-IT-13 observability performance | New `test_memory_observability_perf_postgres.py::test_p7_it13_observability_performance_at_10k_scale` (deliverable of this report, committed) | **FAIL** | Response-time leg PASS (§4 data); EXPLAIN leg detects full-table scans — defect D3 |

### 3.3 API tests (P7-API)

| ID | Implementing test(s) | Result | Notes |
|---|---|---|---|
| P7-API-01 `/observability/memory` extension | `test_p7_it_memory_summary_empty_tenant` (new-field structure and defaults); existing-field contract guarded by the Phase 4 regression suite and the frontend spec | PASS (structure) | Field-value reconciliation blocked by D1 (see P7-IT-01) |
| P7-API-02 `/observability/memory/alerts` | `test_p7_it_memory_alerts_endpoint`, `test_p7_it_memory_endpoint_window_validation` | PASS | Newest-first, window_hours filter, 1-168 validation 422, unauthenticated 401, non-alert audits excluded |
| P7-API-03 no-Phase-6 form | Unit D3 cases (`test_injection_events_degrade_lumps_profile_and_preference` etc., `source=="events"`) | PASS (unit level) | The service-layer `to_regclass` probe branch is unit-covered; no PG-level "table physically absent" case |
| P7-API-04 tenant isolation | Structural coverage: every Phase 7 SQL filters `tenant_id`; empty-tenant / exact-count assertions pass while other tenants' leftover rows exist in the shared DB | Partial | No dedicated cross-tenant negative case; recommend adding one (P3 suggestion, not a defect) |

### 3.4 Frontend tests (P7-FE, Playwright against dev server :5173)

Command: `npx playwright test tests/memory-observability.spec.ts tests/memory.spec.ts` → **14 passed (22.6s)**. Gates: `npm run typecheck`, `npm run check:i18n` (1658 translations across four locales), `npm run build` — all green.

| ID | Implementing test(s) | Result | Notes |
|---|---|---|---|
| P7-FE-01 grouped cards | `memory-observability.spec.ts` "renders grouped health sections" + "window switch refetches" | PASS | Seven groups (tasks / embedding / search / maintenance / agents / injection / quality) render; percentage and decimal formatting; window switch refetches with `window_hours=168` |
| P7-FE-02 overdue emphasis | First case above | PASS | Overdue banner + red cell assertions |
| P7-FE-03 alerts list | "memory alerts list renders rule labels and em dash for null values" | PASS | Localized rule labels, value/threshold rendering, em dash for nulls; empty state thinly covered (page renders fine with alerts=[], no dedicated empty-state element assertion) |
| P7-FE-04 quickstart form | — | **DEFERRED** | Task 5b acceptance scope (quickstart dual-container TSVECTOR form); not executed in this round |

Also deferred to Task 5b: the container-based drills (dead-worker heartbeat alert, embedded-worker periodic scan — the "quickstart dual-container" row of 04-test-plan §2).

## 4. P7-IT-13 performance data (measured)

Data volumes (target tenant plus a larger decoy tenant so tenant filtering is genuinely selective; `ANALYZE` after seeding):

| Table | Target tenant | Decoy tenant | Total |
|---|---|---|---|
| `memory_tasks` | 12,000 | 30,000 | 42,000 |
| `runtime_events` | 12,000 (500 runs × 24) | 36,000 (1,500 runs × 24) | 48,000 |
| `audit_records` | 50 (memory.alert.*) | 20,000 | 20,050 |

(a) Response times: one warm-up, then 20 timed calls per surface; the 2s bound held for every call:

| Surface | Median | Max | Verdict |
|---|---|---|---|
| `memory_summary` (24h window) | 26.7 ms | 34.2 ms | PASS |
| `memory_summary` (168h window) | 29.2 ms | 31.1 ms | PASS |
| `memory_alerts` (24h window) | 1.9 ms | 2.3 ms | PASS |

(b) EXPLAIN (each key aggregate asserted free of Seq Scan on the large tables): **not met** — 4 of 6 queries full-scan a large table (defect D3):

| Query | Plan | Verdict |
|---|---|---|
| tasks main aggregate | Parallel Seq Scan on memory_tasks (no tenant index exists) | FAIL |
| tasks by_kind (window + status filter) | Parallel Seq Scan on memory_tasks | FAIL |
| maintenance activity EXISTS | Seq Scan on memory_tasks | FAIL |
| search_modes/quality join | Parallel Seq Scan on runtime_events + Hash Join (runtime_runs side uses the `runtime_tenant` bitmap at 84k rows; at 2k rows the planner's seq choice is legitimate) | FAIL (runtime_events) |
| maintenance section (audit_records) | Index Scan `audit_tenant` | PASS |
| alerts listing (audit_records) | Index Scan `audit_tenant` | PASS |

Conclusion: at 万级 scale the response-time headroom is ample (≤ 50 ms), but the three `memory_tasks` aggregates (and the same-shaped alerting `collect()` query) sequentially scan structurally, contrary to the technical design's "existing indexes + window filters, explain verifies no full scans"; `memory_tasks` has no TTL and grows unboundedly, so the cost rises linearly with table size.

## 5. Sensitive-data scan (P7-IT-11 / principle 4 evidence)

Static scan scope (every alert and payload code path in `git diff 849d053..HEAD`):

- `modules/memory/alerting.py`: `Alert` carries only {name,value,threshold,window}; audit kwargs are only value/threshold/window; the webhook payload is a fixed 6-key shape {rule,tenant,value,threshold,window,at}; `collect()` runs count/EXISTS window aggregates only and never SELECTs any content/payload column.
- `modules/memory/worker.py`: `memory.maintenance.completed` details are {job,result,stats} (stats all counters: expired/purged/scanned/succeeded/failed/marked/flags_removed); `.failed` is {job,error=str(exc)[:500]} (truncated; exceptions originate from the gateway/store layer and contain no memory plaintext — the embedding retry reads content solely to embed it and writes it nowhere); heartbeat audit stats are an empty dict.
- `modules/observability/service.py`: `memory_alerts` reads back only the value/threshold/window keys of details.
- Dynamic assertions (in passing cases): the R1 audit details equal exactly {"value":1,"threshold":0,"window":"15m"}; the webhook payload key set equals exactly the six keys above.

Conclusion: zero sensitive-data findings. The dedicated dynamic case `test_alert_details_never_carry_content` (asserts the seeded plaintext "敏感内容样本" appears in no alert details) is blocked by D2 and must be re-run after the fix for final confirmation.

## 6. Regression results (full Phase 1-6 + Phase 7)

Command: full `uv run pytest` with both env vars → **642 passed, 5 failed, 3 skipped in 195.9s** (650 items; the new performance test is not part of that run).

- Phase 7 adds 53 cases (alerting 19, summary 5, search_tool +3, observability_postgres 7, alerting_postgres 12, summary_postgres 6, migrations 1).
- **All 5 failures sit in Phase-7-added test files** (`git diff --name-status` shows A for all of them), with the same root cause — test-code raw SQL missing NOT NULL columns (defects D1/D2). **Zero non-Phase-7 failures** — no Phase 1-6 regression.
- The 3 skips are pre-existing conventions, unrelated to Phase 7: `test_knowledge_workspace.py` (opt-in real Milvus), `test_memory_events_postgres.py` ×2 (degraded legs require a plain-PG database without the embedding column — the Phase 3 dual-mode matrix convention; with pgvector present the opposite legs ran for real).
- `uv run ruff check src tests`: All checks passed (including the new performance test file).
- Known pre-existing frontend e2e failures (tickets-antd ×2, one login layout spec, the E2E_CHROME_PATH issue) were out of scope this round; the two target spec files went 14/14 green.

## 7. Defect list

| ID | Severity | Defect | Evidence | Fix direction |
|---|---|---|---|---|
| D1 | P1 | Three Phase 7 PG-test raw `INSERT INTO runtime_runs` statements omit the NOT NULL `queue_expires_at` column (present since migration 0001), exposed by the first real-PG execution: `test_memory_alerting_postgres.py:97`, `test_memory_observability_summary_postgres.py:81`, `:370` | `NotNullViolationError: null value in column "queue_expires_at"`; psql minimal repro identical; blocks `test_r4_vector_fallback_*`, `test_p7_it_memory_summary_health_sections_reconcile`, `test_p7_it_memory_summary_window_hours_168` | Add the column in test code (follow the existing convention at `test_memory_injection_postgres.py:89`, e.g. `now()-interval '1 day'`); production insert path in `repository.py` already sets it — no production change needed |
| D2 | P1 | `test_memory_alerting_postgres.py::make_pending_item` (lines 70-82) `INSERT INTO memory_items` omits the NOT NULL `customer_id` column (introduced by migration 0035) | `NotNullViolationError: null value in column "customer_id"`; psql minimal repro identical; blocks `test_alert_details_never_carry_content`, `test_r3_rising_backlog_across_three_scans_fires` | Test helper should create a `memory_customers` row first and reference it (the `test_memory_events_postgres.py::make_customer` convention); production write paths unaffected |
| D3 | P1 | Observability aggregates full-scan `memory_tasks` structurally: tasks main aggregate, by_kind, maintenance-activity EXISTS (the alerting `collect()` query shares the shape); `runtime_events` planner-chosen Seq Scan in the hash join at 48k rows. Root cause: `memory_tasks` has only its PK and a partial pending index — no tenant/created_at index | §4 EXPLAIN table; performance test's EXPLAIN leg FAILs. Measured ≤ 50 ms at 万级 — not "dragging down the DB", hence not P0; but the table has no TTL and grows unboundedly, escalating to P0 at scale | New migration adding an index (e.g. `memory_tasks(tenant_id, created_at)`; the alerting queries may need a `(tenant_id, status)` partial/composite index); re-check `runtime_events` plans after the fix. The performance test must turn green |

Grading rationale: D1/D2 are test-code defects (production logic untouched), but they block the value-reconciliation and sensitive-data dedicated cases, so the exit criterion "all cases pass" fails — P1. D3 violates the design's explicit explain criterion — also P1. None of the three involves sensitive-data leakage or main-loop blocking (both P0专项 checks came back negative).

## 8. Exit-criteria checklist (04-test-plan §8)

| Criterion | Verdict | Notes |
|---|---|---|
| All cases pass | **Not met** | 6 failures (5 blocked by D1×3/D2×2 + the P7-IT-13 performance test's EXPLAIN leg) |
| AC-1~AC-12 reproduced | Partial | AC-2/3/5/6/8/9 backed by passing cases; AC-1/4/7/10 blocked by D1/D2 or unit-only; AC-11 unit-level pass; AC-12 belongs to Task 5b |
| Zero sensitive data in alerts (blocker) | None found so far | Zero static findings + shape assertions in passing cases; final confirmation pending the dedicated dynamic case after the D2 fix |
| No main-loop blocking (blocker) | Met | Webhook failure only logs (executed in the PG case); scan/heartbeat have due gates and attempt stamping |
| Metric reconciliation consistent (blocker) | **Not met** | Main reconciliation case blocked by D1 |
| Phase 1-6 regression all green | Met | 642 passed, zero non-Phase-7 failures, 3 skips all pre-existing environment conventions |
| No open P0/P1 | **Not met** | D1, D2, D3 open (3× P1) |

**Overall conclusion**: this round does not satisfy the exit criteria. Once the three P1 defects (two test-code NOT NULL omissions, one missing observability index) are fixed and regression is green, the phase can proceed to Task 5b acceptance (quickstart form, container drills).

## 9. Appendix: command reference

```bash
# Phase 7 unit suites (36 passed)
uv run pytest tests/test_memory_alerting.py tests/test_memory_observability_summary.py tests/test_memory_search_tool.py
# Phase 7 PG suites + migrations (20 passed, 5 failed + migration 1 passed)
uv run pytest tests/test_memory_observability_postgres.py tests/test_memory_alerting_postgres.py \
  tests/test_memory_observability_summary_postgres.py tests/test_memory_observability_migrations.py
# Full regression (642 passed, 5 failed, 3 skipped)
uv run pytest
# Performance (P7-IT-13, new deliverable; EXPLAIN leg FAILs)
uv run pytest tests/test_memory_observability_perf_postgres.py -s
# Lint
uv run ruff check src tests
# Frontend
cd frontend && npm run typecheck && npm run check:i18n && npm run build
npx playwright test tests/memory-observability.spec.ts tests/memory.spec.ts   # 14 passed
```
