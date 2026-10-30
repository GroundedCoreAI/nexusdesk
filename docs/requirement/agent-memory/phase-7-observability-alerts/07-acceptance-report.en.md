# Phase 7 · Production Observability & Alerting — Acceptance Report

> Status: Completed (executed by AI agent; pending four-party human sign-off to take effect)
> Execution date: 2026-10-27
> Executor: AI acceptance agent (Claude Code)
> Basis: `05-acceptance-plan.md` (A1–A12, Drills 1–3, C1–C5, §7 pass criteria); test conclusions in `06-test-report.md` (649 green, P1 defects D1/D2/D3 closed)
> Branch: `feat/memory-observability-alerts`

## 1. Acceptance Environment & Substitution Statement

| Component | Form | Notes |
|---|---|---|
| PostgreSQL | Docker container `nexusdesk-pg17` (PG 17 + pgvector) | Acceptance DB `nexusdesk_accept`, Alembic head `0043` |
| API + embedded Worker | Local uvicorn (127.0.0.1:8765), `AGENT_EMBEDDED_WORKER=true` | **Equivalent substitution for the quickstart embedded form**: the in-process embedded Worker runs the same code path and the same alert scanner as the API container in the quickstart dual-container form |
| Standalone Worker | Local process `python -m agent_platform.apps.worker.memory` (`AGENT_EMBEDDED_WORKER=false`) | Drill 1 only; corresponds to the standalone worker container form in quickstart/compose |
| Frontend | vite dev (localhost:5199, proxied to the real API) + Playwright | Live-UI verification against the **real backend** (not mocked) |
| Mock services | embedding mock (127.0.0.1:9871), webhook mock (127.0.0.1:9872) | Drill 2 / A8 only |

**Substitution statement (recorded honestly)**: Docker networking is restricted on this machine, so the `sh nexusdesk quickstart` dual-container form was unavailable. As authorized by the task brief, "local uvicorn + embedded Worker" substitutes for the quickstart embedded form, and a "local standalone Worker process" substitutes for the standalone container form. Both share the full alerting/observability code paths with the forms they replace; the only difference is process packaging. A12's 1-hour continuous soak was substituted with ~40 minutes of multi-restart observation (see residual L-2).

**Non-default acceptance parameters** (observation-window tuning for acceptance only; no default values were changed): `AGENT_MEMORY_ALERT_SCAN_INTERVAL_MINUTES=1` (default 15), `AGENT_MEMORY_ALERT_WEBHOOK_URL` (A8 only), `AGENT_MEMORY_ALERT_ENABLED=false` (A9 only), `AGENT_MEMORY_EMBEDDING_PROFILE_ID/VERSION` (Drill 2 only), `AGENT_MEMORY_VECTOR_ENABLED=false` (Drill 3 only), `AGENT_EMBEDDED_WORKER=false` (Drill 1 standalone Worker only).

**Execution principle for time-based scenarios**: all time conditions (61-minute backlog age, 24h silence, cooldown expiry, heartbeat window breach, etc.) were constructed by `UPDATE`-ing database timestamp fields to aged states — no real waiting was performed; all numeric conclusions are reconciled as "direct SQL query vs API response".

## 2. AC Execution Record (A1–A12)

All scenarios below: executor = AI acceptance agent (Claude Code); date = 2026-10-27; environment = the acceptance stack in §1.

| # | Preconditions | Actual results (key SQL/response excerpts) | Verdict |
|---|---|---|---|
| A1 | Baseline seed: 2 customers, 5 memory_items (incl. canary text), 7 memory_tasks, runs/events for 2 agents, 11 injection_log rows, extract/maintenance/confirm audits | Observability endpoint returned all ten metric groups; reconciliation script 42/42 checks consistent (both 24h and 168h windows). Excerpts: `tasks.pending=1`, `by_kind.conversation_summary done=2/failed=1/avg=500ms`, `agents: alpha 2/5=0.4, beta 6/6=1.0`, `injection source=detail, by_section flag/profile/preference/event=1/1/1/8`; frontend live check passed all 7 group headings + alerts panel + 168h window-switch refetch (screenshot `fe_live_observability.png`) | Pass |
| A2 | Doomed task with `max_attempts=1` (bad payload), marked failed at 19:08:21Z | Embedded scanner wrote `memory.alert.task_failed` audit at 19:09:08Z (~47s, ≤ 2 scan periods), `details={"value":1,"window":"15m","threshold":0}`; alerts endpoint shows `{"rule":"task_failed","value":1.0,"threshold":0.0,"window":"15m"}` | Pass |
| A3 | Failure condition kept after A2; second failure induced | Second failure suppressed within the 60min cooldown: alert count held at 1 over an 80s observation; after aging the first alert's `created_at` by 61min, the rule refired with a new audit `value=2` | Pass |
| A4 | Pending task `created_at` aged 61min, `run_after` pushed +2h (unclaimable) | `memory.alert.pending_task_age` fired with `details={"value":3682,"window":"now","threshold":3600}` — contains oldest age and threshold; constructed task cleaned up afterwards | Pass |
| A5 | API stopped; 2 overdue tickets (`due_at<now`); rule-scan evidence audits aged beyond 2× interval | Manual scan (0.049s) fired `memory.alert.rule_scan_missed` (`value=2, window=30m`); after API restart the startup rule scan wrote fresh evidence and flagged tickets `complaint_risk`; rescan after aging the alert past cooldown returned `fired=[]` — no residual false alerts | Pass |
| A6 | All maintenance audits aged 25h (business activity present, no maintenance records) | `memory.alert.maintenance_silent` fired; observability endpoint `maintenance.overdue=[ttl_purge, decay, embedding_retry, rule_scan]` correct; audit timestamps restored afterwards | Pass |
| A7 | First 10 searches with 30% fallback (small sample); then topped up to 20 calls with 5 fallbacks (25%) | Small-sample state did not fire over 75s (≥20-call gate effective — prefer-miss-over-misfire); once qualified, `memory.alert.vector_fallback` fired with `details={"value":0.25,"threshold":0.2,"window":"24h"}` | Pass |
| A8 | `AGENT_MEMORY_ALERT_WEBHOOK_URL` pointed at the mock (9872) | Mock received compliant JSON: `{"rule":"pending_task_age","tenant":"local","value":3719,"threshold":3600,"window":"now","at":"2026-10-26T19:24:59Z"}`; after killing the mock, the alert audit still landed (R1 at 19:26:00), the log shows only `Memory alert webhook delivery failed` warning, and the next-period scan ran normally at 19:27:05 | Pass |
| A9 | Restarted with `AGENT_MEMORY_ALERT_ENABLED=false`, repeated A2's failure construction | After the task failed at 19:31:12Z, the alert audit count held at 10 over 150s (zero new); the metrics endpoint still returned all 17 sections (`tasks.failed_15m=2`) | Pass |
| A10 | agent-alpha: 5 runs, 2 injections; agent-beta: 6 runs, 6 injections; differentiated write/failure volumes | `agents` section per-agent values correct: alpha injection rate 0.4, beta 1.0; write/failure counts match direct SQL (included in A1's 42-check reconciliation) | Pass |
| A11 | Literal plan (migrate DB to 0040, no `memory_injection_log`) not executable due to code/schema version coupling (`duration_ms` column belongs to 0042) — recorded honestly; substitute: `DROP TABLE memory_injection_log` at head schema | Injection metrics degraded to event-count mode: `{"source":"events","avg_items":7.0,"by_section":{"flag":1,"profile":null,"preference":null,"event":2}}`, endpoint error-free (D3 `to_regclass` probe effective) | Pass (substituted execution, see residual L-1) |
| A12 | Embedded form, scan interval 1min, continuous multi-scenario operation | Between 19:09–19:42, 8 alerts were all persisted automatically by the API-embedded scanner on schedule; startup first-pass (rule_scan) audit visible; heartbeat audits are written in standalone form only (by design); duration substituted with ~40min multi-restart observation instead of a 1h continuous soak (see residual L-2) | Pass |

## 3. Drill Timing Records

| Drill | Execution & timing | Verdict |
|---|---|---|
| Drill 1: Worker down | Standalone Worker (`AGENT_EMBEDDED_WORKER=false`) wrote heartbeat audit → process killed → heartbeat record aged 31min → one standalone-form scan (0.047s) fired both `pending_task_age` (value=3663s) and `worker_heartbeat` (`value=31.0 > threshold=30, window=30m`) → Worker restarted, fresh heartbeat within 5min → after clearing conditions and passing cooldown, rescan returned `fired=[]` — no residual false alerts. Real-form detection-latency bound = heartbeat interval 300s + 30min window + 1 scan period, meeting the ≤30min discovery requirement (constructed aging makes it immediately decidable) | Pass |
| Drill 2: embedding service outage | Embed profile created via the real management API (`11561124-61df-486e-88ef-0198edb51921` v1, base pointing at mock 9871) → API restarted in vector form (no degradation warning in startup log) → mock taken down; 3 event writes raised the `embedding_failed` backlog 2→5→7→9 period over period → `memory.alert.embedding_growing` fired at 19:41:34Z (`{"value":9,"window":"2 scans","threshold":7}`, fired on the third reading after two consecutive rising scans) → mock restored and API restarted; startup maintenance `embedding_retry` drained the backlog 9→0 with audit `{"scanned":9,"succeeded":9,"failed":0,"result":"ok"}`; 9 vector columns backfilled | Pass |
| Drill 3: pgvector unavailable | With `AGENT_MEMORY_VECTOR_ENABLED=false`, probe confirmed `store impl: TsVectorStore / available(): text` → API restarted in forced text mode → 5 constructed `mode=text` search events → retrieval mode distribution `{"vector":14,"text":6,"keyword_fallback":5,"fallback_rate":0.2}` correctly shows the degraded mix. In pure text mode the `keyword_fallback` share is 0, so R4 cannot fire by construction (prefer-miss-over-misfire); the R4 firing path was demonstrated in A7. **Spec amendment record (final review)**: the R4 row of `02-requirements.md` originally read "keyword fallback + text mode share", which did not match the implementation and would false-fire at 100% in the quickstart pure-text topology; the final review amended the numerator to the keyword_fallback share (text is the configured mode of the TSVECTOR deployment form, not a degradation). The implementation already matches the amended spec — no code change needed | Pass |

## 4. Metric Reconciliation Data (A1 sample + full)

Method: direct SQL queries vs `GET /api/v1/observability/memory?window_hours={24,168}` responses compared field by field — **42/42 checks consistent** (both windows). Sample excerpts:

| Metric | Direct SQL | API response | Match |
|---|---|---|---|
| tasks.pending | 1 | 1 | ✓ |
| tasks.by_kind.conversation_summary (done/failed/avg_ms) | 2 / 1 / 500.0 | 2 / 1 / 500.0 | ✓ |
| extraction 24h runs/added/updated/pending/dropped/pii_masked | 3 / 6 / 3 / 2 / 1 / 3 | same | ✓ |
| hit_rate customer_runs / injected_runs | 11 / 8 | 11 / 8 | ✓ |
| agents alpha injection rate / beta injection rate | 0.4 / 1.0 | 0.4 / 1.0 | ✓ |
| injection source / by_section | detail / 1,1,1,8 | detail / 1,1,1,8 | ✓ |
| governance per-action counts (4 types) | 2/2/1/4 | 2/2/1/4 | ✓ |
| search calls / empty | 10 / 2 | 10 / 2 | ✓ |

## 5. Business-Metric Acceptance

| Metric | Target | Measured | Verdict |
|---|---|---|---|
| Metric coverage | All ten categories queryable and reconciled | A1: all ten groups present, 42/42 reconciled (24h+168h) | Pass |
| Alert discovery latency | ≤ 2 scan periods | A2: failure→alert ~47s (1min period); Drills 1/2 timings within bounds | Pass |
| Alert false-positive rate | ≤ 20% (tracked in the first-month post-launch observation window) | Zero false positives across constructed boundaries during acceptance (small sample, cooldown, pure text mode, post-recovery rescan); first-month tracking deferred to post-launch | Pass (tracking item) |
| Missed maintenance discoverable | Miss beyond 2 periods must alert | A5 (rule_scan_missed) and A6 (maintenance_silent) both fired | Pass |
| Zero new middleware | No new services in compose | `git diff main...HEAD -- compose.yaml deploy/ Dockerfile nexusdesk nexusdesk.ps1` is empty | Pass |

## 6. Compliance Checks (C1–C5)

| # | Item | Execution & result | Verdict |
|---|---|---|---|
| C1 (veto) | No memory plaintext/PII/connection strings/secrets in alert audits & webhook payloads | Regex scan of 15 blobs (14 `memory.alert.*` audits + 1 webhook payload): canary text "敏感内容样本ACC1", CN mobile numbers, emails, connection strings, Bearer, token values, password/secret keys — **zero hits**; structural check confirms `details` key set is strictly `{value, threshold, window}` | Pass |
| C2 (veto) | Alert scans must not block the claim main loop (single pass ≤5s) | Measured single-pass scan 0.042–0.049s (incl. one pass firing 2 rules at 0.047s), far below 5s; while the scanner was active, tasks were claimed+processed within the same second (observed repeatedly in A2 and Drill 2) — main loop unblocked | Pass |
| C3 | Metric aggregation bounded by time windows, no full-table scans | EXPLAIN spot-check on `nexusdesk_accept`: Index Scan `memory_tasks_tenant_status`, `runtime_events_type_created`; Index Only Scan `runtime_runs_tenant_id_key`; no Seq Scan (full evidence in `06-test-report.md` §C3, migration 0043 tenant indexes) | Pass |
| C4 | `memory_alert_enabled=false` disables everything | See A9: with the switch off, the failed task produced zero alerts while metrics kept flowing | Pass |
| C5 | Observability metrics & alerts tenant-isolated | Tenant `other` seed (pending+failed tasks and an alert audit) shows zero leakage in the `local` view: `tasks.pending=1`, `by_kind failed=0`, alerts list `[]` | Pass |

## 7. Threshold Default Confirmation Record

Code defaults (`backend/src/agent_platform/settings.py`) confirmed item by item against FR-4:

| Setting | Code default | FR-4 requirement | Confirmed |
|---|---|---|---|
| memory_alert_enabled | true | true | ✓ |
| memory_alert_scan_interval_minutes | 15 | 15 | ✓ |
| memory_alert_cooldown_minutes | 60 | 60 | ✓ |
| memory_alert_pending_task_max_age_minutes | 60 | 60 | ✓ |
| memory_alert_pending_backlog_threshold | 500 | 500 | ✓ |
| memory_alert_vector_fallback_rate | 0.2 | 0.2 | ✓ |
| memory_alert_webhook_url | "" (empty) | "" (empty) | ✓ |
| memory_alert_webhook_timeout_seconds | 5 | — (additive item beyond requirements; implements the FR-3 webhook ≤5s timeout constraint) | ✓ (additive, flagged) |

Module constants rechecked (`alerting.py` / `worker.py`): R1 window 15min ✓; R3 two consecutive rising scans ✓; R4 small-sample gate 20 calls/24h ✓; R5 silence window 24h ✓; R6 window = 2× rule-scan interval ✓; R8 heartbeat interval 300s / missing window 30min ✓. All consistent with `02-requirements.md`.

## 8. Residual Issues

| # | Severity | Item | Owner | Deadline |
|---|---|---|---|---|
| L-1 | P3 | A11's literal form (migrating to 0040 and running current code) is not executable due to code/schema version coupling; the D3 degradation contract was demonstrated via DROP TABLE at head schema this time; recommend documenting the "injection-degradation verification method" in ops docs | Engineering lead | 2026-11-03 |
| L-2 | P3 | A12's 1-hour continuous soak was substituted with ~40min multi-restart observation; redo a 1h continuous soak smoke test once the quickstart environment is restored | QA | 2026-11-10 |
| L-3 | P3 | Acceptance environment used local uvicorn embedded/standalone processes instead of the Docker quickstart dual-container form (Docker networking restricted on this machine); equivalence statement in §1; smoke-recheck once the environment is restored | Platform ops | 2026-11-10 |
| L-4 | P3 | Bulk-aging UPDATEs during acceptance gave several pending_task_age alerts identical `created_at` values (display-layer noise only); evidence is read by audit id — no fix needed | QA | Record only |
| L-5 | P3 | The FR-1 quality row originally promised confirm/reject rates in both 7d and 30d windows; only 7d is implemented. The final review amended `02-requirements.md` to 7d (30d listed as a future enhancement); no code change needed | Engineering lead | At future-enhancement scheduling |
| L-6 | P3 | For an active tenant with `memory_decay_enabled=false`, the "decay migration" card shows permanently overdue (the maintenance cadence table has no settings-based exemption for decay, unlike rule_scan); no R5 alert fires — display-layer redness only; a follow-up can skip the decay cadence in `_maintenance_section` when the switch is off | Engineering lead | At future-enhancement scheduling |

No P0/P1/P2 residuals.

## 9. Conclusion & Sign-off

**Conclusion: Conditionally passed.**

- A1–A12 all passed (A11 executed via authorized substitution; A12 duration-substituted);
- All three failure drills met their criteria;
- Veto items C1/C2 passed clean; C3–C5 passed;
- All threshold defaults and module constants confirmed correct;
- Residuals are 6 P3-level execution-coverage/documentation items only, each with an owner and deadline; the false-positive-rate metric is deferred to the first-month post-launch observation window per the plan.

This report was executed and generated by an AI acceptance agent; the conclusion takes final effect upon four-party human sign-off.

| Role | Signature | Date |
|---|---|---|
| Product owner | Executed by AI agent, pending human signature | — |
| QA | Executed by AI agent, pending human signature | — |
| Engineering lead | Executed by AI agent, pending human signature | — |
| Platform ops | Executed by AI agent, pending human signature | — |
