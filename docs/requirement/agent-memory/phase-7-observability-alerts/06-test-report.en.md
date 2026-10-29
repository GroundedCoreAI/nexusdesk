# Phase 7 · Production Observability & Alerting — Test Report

> Status: **re-test PASSED** (all 3 P1 defects from round one fixed and re-verified green; exit criteria met — only acceptance-phase items honestly remain)
> Executed: 2026-10-27, Task 5a (full functional test matrix on a real PostgreSQL); re-tested the same day after the fix round
> Reference: `04-test-plan.md` (P7-UT-01~11, P7-IT-01~13, P7-API-01~04, P7-FE-01~04, §8 exit criteria)

## 1. Execution environment

| Item | Value |
|---|---|
| Branch | `feat/memory-observability-alerts` |
| Round-one commits | `b0fe1cd` (Phase 7 range `849d053..HEAD`) + performance test `0abed55` |
| Re-test commit | `87f0d50` (fix round: `cfe550c` test INSERT column completion, `4655a22` tenant indexes + query adjustments, `87f0d50` performance-test seed reshape) |
| Database | PostgreSQL 17.11 (Debian, aarch64), Docker container `nexusdesk-pg17` (`pgvector/pgvector:pg17`), pgvector 0.8.7 |
| Test databases | `nexusdesk_test` (at alembic head `0043_memory_tasks_tenant_index` for the re-test); migration tests derive random disposable databases from `nexusdesk_migtest` |
| Backend runtime | Python 3.11.9, pytest 9.1.1, pytest-asyncio 1.4.0 (`backend/.venv`, uv-managed) |
| Frontend | Vite 7 dev server (:5173), Playwright Chromium headless |
| Env vars | `TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/nexusdesk_test`; `MIGRATION_TEST_DATABASE_URL=.../nexusdesk_migtest` |

Note: round one was the **first real-PG execution ever** for all Phase 7 PG suites (`*_postgres.py`, migrations) — previously always skipped without `TEST_DATABASE_URL`; with pgvector present, the vector-gated cases (vector search leg, embedding retry audit) actually ran.

## 2. Scope vs. principles

| Principle (04-test-plan §1) | Outcome |
|---|---|
| 1 Value reconciliation | Round one: main reconciliation case blocked by defect D1. After the fix, `test_p7_it_memory_summary_health_sections_reconcile` passes — all ten sections reconcile value-by-value against direct DB queries, including the 168h-window variant |
| 2 No waiting in time-based cases | Confirmed: aging/overdue constructed by rewriting DB timestamps, alert checks triggered as single manual passes; re-test PG suites: 27 cases in 12.4s |
| 3 Alerts prefer misses over false positives | R3 restart resampling, R4 small-sample gate, R5/R6 exemptions, R8 embedded exemption all green in unit tests; on the PG side the R3 three-cycle rise, R4 above-rate firing and R5 heartbeat-evidence exclusion all pass on re-test |
| 4 Zero sensitive data in alerts | Static scan: zero findings (§5); the dedicated dynamic case `test_alert_details_never_carry_content` passes on re-test — the seeded plaintext never appears in any alert details |
| 5 Existing observability unbroken | Zero non-Phase-7 failures throughout (round one: 642 passed; fix-round full run: 649 passed); the Phase 4 observability-page frontend spec passes |

## 3. Results matrix (test-plan ID mapping)

### 3.1 Unit tests (P7-UT)

Command: `uv run pytest tests/test_memory_alerting.py tests/test_memory_observability_summary.py tests/test_memory_search_tool.py` → **36 passed in 0.29s** (includes 9 pre-existing search_tool cases; identical in both rounds).

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

### 3.2 Integration tests (P7-IT, real PG)

Re-test command: `uv run pytest tests/test_memory_observability_postgres.py tests/test_memory_alerting_postgres.py tests/test_memory_observability_summary_postgres.py tests/test_memory_observability_migrations.py` → **27 passed in 12.42s**, zero failures, zero skips (round one: 20 passed / 5 failed; all 5 failures shared the root cause of test-code raw SQL missing NOT NULL columns — fixed and green now, see §7).

| ID | Implementing test(s) | Round 1 | Re-test | Notes |
|---|---|---|---|---|
| P7-IT-01 task health metrics | `test_p7_it_memory_summary_health_sections_reconcile` (main reconciliation); `test_p7_it_duration_ms_written_for_done_and_failed` | FAIL / PASS | **PASS** | Round one blocked by D1; on re-test all counts, oldest age and by_kind avg/P95 reconcile with direct queries |
| P7-IT-02 embedding metrics | Same reconciliation case; `test_p7_it_embedding_retry_audit_counts_outcomes` | FAIL / PASS | **PASS** | Retry audit {scanned:2,succeeded:1,failed:1} and summary section both reconcile |
| P7-IT-03 search modes & quality | `test_p7_it_search_event_modes` | PASS | **PASS** | text/keyword_fallback/vector modes all executed (pgvector image; vector leg not skipped); hits/returned reconcile |
| P7-IT-04 maintenance health | `test_p7_it_maintenance_audits_ttl_and_injection_purge`, `test_p7_it_maintenance_quiet_pass_writes_no_audit`, `test_p7_it_maintenance_failure_writes_failed_audit_and_reraises`, `test_p7_it_rule_scan_audit`, `test_p7_it_rule_scan_not_overdue_when_scan_disabled` | PASS | **PASS** | Per-job audit shapes, silent quiet passes, failure audit + re-raise, overdue-list semantics all as designed |
| P7-IT-05 agent dimension | agents section inside the main reconciliation case | FAIL | **PASS** | Round one blocked by D1; on re-test the two agents' differentiated traffic reconciles per-agent injection rates (write/failure volumes stay None per the documented degradation) |
| P7-IT-06 alert end-to-end | `test_alert_task_failed_writes_audit_and_cooldown_suppresses` | PASS | **PASS** | R1 condition → single scan → `memory.alert.task_failed` persisted; details exactly {value:1,threshold:0,window:"15m"} |
| P7-IT-07 alert cooldown | Cooldown half of the same case (second scan adds nothing) | PASS | **PASS** | Post-cooldown re-fire covered by the unit truth table |
| P7-IT-08 R4/R5/R6 firing | R4: `test_r4_vector_fallback_fires_above_rate_with_min_calls`; R5: `test_r5_maintenance_silent_fires_with_activity_and_is_exempt_when_idle`, `test_r5_heartbeat_rows_are_not_maintenance_evidence`; R6: `test_r6_exempt_without_overdue_tickets`, `test_r6_fires_with_overdue_tickets_and_no_evidence`; plus R3 PG: `test_r3_rising_backlog_across_three_scans_fires` | R4 FAIL / R3 FAIL; R5, R6 PASS | **all PASS** | R4 blocked by D1 and R3 by D2 in round one; on re-test R4 persists value 0.25/threshold 0.2 and R3 the three-cycle value 3 |
| P7-IT-09 webhook | `test_webhook_payload_shape_and_failure_isolated` | PASS | **PASS** | Payload exactly {rule,tenant,value,threshold,window,at}, timeout=5; a TimeoutError sender still lets the scan complete and the audit persist |
| P7-IT-10 master switch | `test_master_switch_off_writes_nothing` (+ unit `test_scanner_master_switch_off_never_touches_db`) | PASS | **PASS** | Disabled: no scan, no audits, no heartbeat; metrics endpoints unaffected (regression green) |
| P7-IT-11 no sensitive data in alerts | Dynamic: `test_alert_details_never_carry_content`; static: full alert/webhook payload code-path scan (§5) | Dynamic FAIL (blocked by D2) / static PASS | **PASS** | Re-test: the seeded plaintext appears in no alert details, and the details key set is exactly {value,threshold,window} |
| P7-IT-12 migration backfill | `test_memory_observability_migrations.py`: `test_0042_adds_duration_ms_and_downgrade_drops_it`; re-test adds `test_0043_adds_tenant_indexes_and_downgrade_drops_them` | PASS | **PASS** | 0042 only adds `duration_ms` (D1 adjustment: created_at exists since 0030, no run_after backfill needed); 0043's three indexes round-trip upgrade/downgrade on a random disposable DB |
| P7-IT-13 observability performance | `test_memory_observability_perf_postgres.py::test_p7_it13_observability_performance_at_10k_scale` (deliverable of this report — added in `0abed55`, evolved with the fixes in `4655a22`/`87f0d50`) | FAIL (EXPLAIN leg) | **PASS** | Both legs meet the bar on re-test; data in §4 |

### 3.3 API tests (P7-API)

| ID | Implementing test(s) | Result | Notes |
|---|---|---|---|
| P7-API-01 `/observability/memory` extension | `test_p7_it_memory_summary_empty_tenant` (new-field structure and defaults) + the re-tested reconciliation case (field values); existing-field contract guarded by the Phase 4 regression suite and the frontend spec | PASS | Field-value reconciliation was blocked by D1 in round one; unblocked on re-test |
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

## 4. P7-IT-13 performance data (re-test measurements)

Data volumes (since `87f0d50` the seed is production-shaped multi-tenant: the target tenant plus 40 small decoy tenants, so tenant-filter selectivity approximates a production distribution; `ANALYZE` after seeding):

| Table | Target tenant | Decoys (40 tenants) | Total |
|---|---|---|---|
| `memory_tasks` | 12,000 | 30,000 (750/tenant) | 42,000 |
| `runtime_runs` | 500 | 25,000 (625/tenant; target ≈ 2%) | 25,500 |
| `runtime_events` | 12,000 (500 runs × 24) | 600,000 | 612,000 |
| `audit_records` | 50 (memory.alert.*) | 20,000 (500/tenant) | 20,050 |

(a) Response times: one warm-up, then 20 timed calls per surface; the 2s bound held for every call (re-test measurements):

| Surface | Median | Max | Verdict |
|---|---|---|---|
| `memory_summary` (24h window) | 12.8 ms | 19.2 ms | PASS |
| `memory_summary` (168h window) | 28.9 ms | 31.7 ms | PASS |
| `memory_alerts` (24h window) | 1.5 ms | 1.9 ms | PASS |

(The fix round's own verification run recorded the same millisecond-scale maxima: 22.5 / 35.9 / 2.4 ms; both rounds sit far below the 2s bound.)

(b) EXPLAIN (each of the six key aggregates asserted free of Seq Scan on the large tables): **all met on re-test** — migration 0043 adds the `memory_tasks(tenant_id,created_at)`, `memory_tasks(tenant_id,status)` and `runtime_events(type,created_at)` indexes, and the activity probe EXISTS was split into two index-servable branches:

| Query | Re-test plan | Verdict |
|---|---|---|
| tasks main aggregate | Bitmap Index Scan `memory_tasks_tenant_status` | PASS |
| tasks by_kind (window + status filter) | Bitmap Index Scan `memory_tasks_tenant_created` | PASS |
| maintenance activity EXISTS | Two Index Only Scans (`memory_tasks_tenant_created` + `memory_tasks_tenant_status`) | PASS |
| search_modes/quality join | Bitmap Index Scan `runtime_events_type_created` + Index Only Scan `runtime_runs_tenant_id_key` | PASS |
| maintenance section (audit_records) | Bitmap Index Scan `audit_tenant` | PASS |
| alerts listing (audit_records) | Bitmap Index Scan `audit_tenant` | PASS |

Round-one contrast: the three tasks aggregates were (Parallel) Seq Scans on memory_tasks and the search join was a Parallel Seq Scan on runtime_events (see defect D3 closure in §7). Round-one response times actually met the bound too (median ≤ 39ms) — the defect was the plan shape violating the design criterion; after the fix all six queries are index-served, with medians ≤ 29ms at 万级 scale.

## 5. Sensitive-data scan (P7-IT-11 / principle 4 evidence)

Static scan scope (every alert and payload code path):

- `modules/memory/alerting.py`: `Alert` carries only {name,value,threshold,window}; audit kwargs are only value/threshold/window; the webhook payload is a fixed 6-key shape {rule,tenant,value,threshold,window,at}; `collect()` runs count/EXISTS window aggregates only and never SELECTs any content/payload column.
- `modules/memory/worker.py`: `memory.maintenance.completed` details are {job,result,stats} (stats all counters: expired/purged/scanned/succeeded/failed/marked/flags_removed); `.failed` is {job,error=str(exc)[:500]} (truncated; exceptions originate from the gateway/store layer and contain no memory plaintext — the embedding retry reads content solely to embed it and writes it nowhere); heartbeat audit stats are an empty dict.
- `modules/observability/service.py`: `memory_alerts` reads back only the value/threshold/window keys of details.
- Dynamic assertions (passing on re-test): `test_alert_details_never_carry_content` asserts the seeded plaintext "敏感内容样本" appears in no alert details and the details key set is exactly {value,threshold,window}; the R1 audit details equal exactly {"value":1,"threshold":0,"window":"15m"}; the webhook payload key set equals exactly the six keys above.

Conclusion: **zero sensitive data, confirmed both dynamically and statically** (the dynamic case was blocked by D2 in round one; closed on re-test).

## 6. Regression results (full Phase 1-6 + Phase 7)

| Round | Command | Result |
|---|---|---|
| Round one (`b0fe1cd` + `0abed55`, DB head 0042) | Full `uv run pytest` with both env vars | 642 passed, 5 failed, 3 skipped, 195.9s (650 items; performance test counted separately) |
| Re-test (`87f0d50`, DB head 0043) | Same (executed by the fix round) | **649 passed, 0 failed, 3 skipped, 207s** |
| Re-test (re-verified while writing this report) | The four Phase 7 PG files | **27 passed in 12.42s** |
| Re-test (same) | Performance test with `-s` | **1 passed in 52.63s** (the multi-tenant seed dominates the runtime) |

- Phase 7 totals 54 cases (alerting 19, summary 5, search_tool +3, observability_postgres 7, alerting_postgres 12, summary_postgres 6, migrations 2, perf 1).
- Round one's 5 failures all sat in Phase-7-added test files (defects D1/D2); **zero non-Phase-7 failures across both rounds** — no Phase 1-6 regression.
- The 3 skips are pre-existing conventions, unrelated to Phase 7: `test_knowledge_workspace.py` (opt-in real Milvus), `test_memory_events_postgres.py` ×2 (degraded legs require a plain-PG database without the embedding column — the Phase 3 dual-mode matrix convention; with pgvector present the opposite legs ran for real).
- `uv run ruff check src tests`: All checks passed (both rounds).
- Known pre-existing frontend e2e failures (tickets-antd ×2, one login layout spec, the E2E_CHROME_PATH issue) were out of scope; the two target spec files went 14/14 green.

## 7. Defect list (all closed)

| ID | Severity | Defect | Round-one evidence | Fix & re-test |
|---|---|---|---|---|
| D1 | P1 | Three Phase 7 PG-test raw `INSERT INTO runtime_runs` statements omit the NOT NULL `queue_expires_at` column (present since migration 0001): `test_memory_alerting_postgres.py:97`, `test_memory_observability_summary_postgres.py:81`, `:370` | `NotNullViolationError: null value in column "queue_expires_at"`; psql minimal repro identical; blocked 3 cases | **Closed** — `cfe550c` completes the INSERTs (following the `test_memory_injection_postgres.py:89` convention); on re-test `test_r4_vector_fallback_*` and both summary reconciliation cases go green |
| D2 | P1 | `test_memory_alerting_postgres.py::make_pending_item` `INSERT INTO memory_items` omits the NOT NULL `customer_id` column (introduced by migration 0035) | `NotNullViolationError: null value in column "customer_id"`; psql minimal repro identical; blocked 2 cases | **Closed** — fixed in the same `cfe550c` (create a `memory_customers` row first, then reference it); on re-test `test_alert_details_never_carry_content` and `test_r3_rising_backlog_*` go green |
| D3 | P1 | Observability aggregates full-scanned `memory_tasks` structurally (tasks main, by_kind, maintenance-activity EXISTS; the alerting `collect()` query shared the shape) and the `runtime_events` join planner-chose a Seq Scan; root cause: no tenant/created_at indexes | Round-one EXPLAIN: Parallel Seq Scan on memory_tasks ×3, on runtime_events ×1; round-one response ≤ 50ms at 万级 — not "dragging down the DB", hence P1 not P0 | **Closed** — `4655a22` adds migration 0043 (`memory_tasks(tenant_id,created_at)`, `(tenant_id,status)`, `runtime_events(type,created_at)`) and splits the activity-probe EXISTS into two index-servable branches; `87f0d50` reshapes the perf-test seed into 40 small decoy tenants (production-shaped selectivity, eliminating planner coin flips). On re-test all six EXPLAIN legs are index-served (§4) and the performance test goes green |

Grading rationale: D1/D2 were test-code defects (production logic untouched) but blocked the value-reconciliation and sensitive-data dedicated cases in round one — P1. D3 violated the design's explicit explain criterion — also P1. None of the three involved sensitive-data leakage or main-loop blocking (both P0专项 checks came back negative). **No defects remain open.**

## 8. Exit-criteria checklist (04-test-plan §8)

| Criterion | Verdict | Notes |
|---|---|---|
| All cases pass | **Met** | Re-test: unit 36 + PG 27 + perf 1 all green; full regression 649 passed / 0 failed |
| AC-1~AC-12 reproduced | Met (within test scope) | AC-1/2/3/4/5/6/7/8/9/10 all backed by passing cases (the AC-1 reconciliation main case, AC-4 R2, AC-7 R4 incl. the small-sample gate, and the AC-10 agents section all green on re-test); AC-11 unit-level pass; **AC-12 belongs to Task 5b acceptance** (quickstart dual-container) |
| Zero sensitive data in alerts (blocker) | **Met** | Zero static findings + the dedicated dynamic case passes on re-test (§5) |
| No main-loop blocking (blocker) | Met | Webhook failure only logs (executed in the PG case); scan/heartbeat have due gates and attempt stamping |
| Metric reconciliation consistent (blocker) | **Met** | Re-test reconciliation main case + 168h-window variant pass, value-by-value against direct DB queries |
| Phase 1-6 regression all green | Met | 649 passed, zero non-Phase-7 failures, 3 skips all pre-existing environment conventions |
| No open P0/P1 | **Met** | D1/D2/D3 all fixed and closed on re-test (§7) |

**Overall conclusion**: all exit criteria are met. The only honest carry-overs are acceptance-phase (Task 5b) items: P7-FE-04 quickstart TSVECTOR form and the container-based drills (AC-12 etc.) — not test defects of this round. The phase may proceed to Task 5b acceptance.

## 9. Appendix: command reference

```bash
# Phase 7 unit suites (36 passed)
uv run pytest tests/test_memory_alerting.py tests/test_memory_observability_summary.py tests/test_memory_search_tool.py
# Phase 7 PG suites + migrations (re-test 27 passed; round one 20 passed / 5 failed)
uv run pytest tests/test_memory_observability_postgres.py tests/test_memory_alerting_postgres.py \
  tests/test_memory_observability_summary_postgres.py tests/test_memory_observability_migrations.py
# Full regression (round one 642 passed / 5 failed / 3 skipped; re-test 649 passed / 0 failed / 3 skipped)
uv run pytest
# Performance (P7-IT-13; round one EXPLAIN leg FAIL, re-test 1 passed)
uv run pytest tests/test_memory_observability_perf_postgres.py -s
# Lint
uv run ruff check src tests
# Frontend
cd frontend && npm run typecheck && npm run check:i18n && npm run build
npx playwright test tests/memory-observability.spec.ts tests/memory.spec.ts   # 14 passed
```
