# Phase 1 · Routing Decisions Visible — Test Plan

> Status: to be executed (after this phase's development completes)
> Created: 2026-10-30
> Basis: `02-requirements.md` (FR-1~FR-6, AC-1~AC-12), `03-technical-design.md` (decision sequence,
> SAVEPOINT, the two 409 contracts, no events)

## 1. Test scope and principles

**Scope**: the `routing_decisions` table and migration, the four modules under
`customer_service/routing/`, the `send()` refactor, the two query endpoints, and the customer-service
capability configuration.

**Principles**:

1. **Equivalence is limited to the HTTP boundary and persisted side effects**: Phase 1 has two
   intended changes, FR-3 and FR-4, so **`send()`'s internal return value is not required to equal
   the baseline**.
2. **SELECT count and order are mandatory tests**: `agent_snapshot` must not be queried early; the
   total SQL count is expected to be `+1` (the new decision INSERT).
3. **Failures must not backfire, and that is mandatory**: after injecting a SAVEPOINT failure the
   main flow must still succeed.
4. **Both 409s must be tested**: `conversation_closed` and `model_not_configured` are the same class
   of defect, so testing one is not enough.
5. **Reject must not write a message**: the current closed branch writes nothing to
   `conversation_messages`, and the test must assert the refactor does not either.
6. **No waiting on time**: this phase has no backoff or expiry logic.

## 2. Test environment and data setup

| Environment | Purpose |
|---|---|
| Unit (no DB) | Decision sequence, rule normalisation and exact matching, switch behaviour, rule id stability |
| Integration (PG + `pytest.mark.postgres`) | Decision persistence, transaction/rollback, queries and aggregation, tenant isolation, channel inbound |
| SQL counting (`before_cursor_execute`) | SELECT count and order, lock order |

**Data setup**: write rows directly to build the four `mode` values; blacklist via
`upsert_flag(..., "blacklist", ...)`; `model_not_configured` via `settings.model_backend="unconfigured"`
on a conversation with no agent; write failures via a temporary trigger; the baseline comparison runs
the same cases on the pre-change branch and records HTTP status and a persistence snapshot.

Integration cases run with `trace_enabled=true` by default (including the baseline `+1` SQL assertion
in P1-IT-13). Only P1-IT-12 explicitly turns recording off to verify AC-8.

## 3. Unit tests

| # | Case | Expected | Trace |
|---|---|---|---|
| P1-UT-01 | `mode=closed` decision | `reject / action=reject / conversation_closed`, `execution_tier=NULL` | FR-2, AC-1 |
| P1-UT-02 | Chinese `转人工` / `人工客服` / `客服` hit | `handoff / request_handoff / user_requested_human`, `matched_rule_id=zh_human_request_001` | FR-2, FR-3, AC-2 |
| P1-UT-03 | English `human` / `real person` / `representative` / `human agent` hit | `handoff`, `matched_rule_id=en_human_request_001` | FR-3, AC-3 |
| P1-UT-04 | `mode=human` / `mode=waiting` | `defer / action=defer`, `human_mode_active` / `waiting_mode_active` | FR-2, AC-4 |
| P1-UT-05 | Blacklist with the switch on | `handoff / blacklist_flag` | FR-2, AC-5 |
| P1-UT-06 | Everything else | `continue / agent / submit_agent_run / default_agent` | FR-2, AC-6 |
| P1-UT-07 | Normalisation boundaries: `" HUMAN "`, `"ＨＵＭＡＮ"`, `"human."` | Hit (including trailing-punctuation stripping) | FR-3 |
| P1-UT-08 | Exact-match counter-examples: `"your agent platform is slow"`, `"human being"`, bare `"agent"` | **No hit** | FR-3, AC-11 |
| P1-UT-09 | `trace_enabled=false` | No write call is made | FR-6, AC-8 |
| P1-UT-10 | Rule configuration is invalid JSON | Falls back to the default rules and logs a WARN, no raise | FR-3 |
| P1-UT-11 | Persisted parameters | Only `message_length` and `request_id`; no `message_digest` column, no reserved columns | FR-1, FR-2 |
| P1-UT-12 | Rule id stability | After reordering `handoff_rules`, the same phrase still matches the same `matched_rule_id` | FR-3 |
| P1-UT-13 | Constraint invariants | `reject` with `execution_tier` rejected; `continue` without a tier **allowed**; `message_length<0` rejected; duplicate `request_id` in one scope rejected | FR-2 |
| P1-UT-14 | zh-TW `轉人工` hit | `handoff`, `matched_rule_id=zhtw_human_request_001` | FR-3 |
| P1-UT-15 | Hindi `मानव` / `एजेंट` hit | `handoff`, `matched_rule_id=hi_human_request_001` | FR-3 |
| P1-UT-16 | Locale-agnostic union matching | The matcher reads neither `locale` nor the channel language; `客服` still deterministically matches `zh_human_request_001` when the channel declares `en` or `zh-TW` | FR-3 |
| P1-UT-17 | Globally unique rule ids and normalised phrases | The settings-model validator rejects a duplicate rule id, or two rules configuring `" HUMAN "` and `human` (identical after normalisation) | FR-3 |

## 4. Integration tests

| # | Case | Expected | Trace |
|---|---|---|---|
| P1-IT-01 | Send a message to a `closed` conversation | HTTP 409; `send()` returns `rejected`; one decision row `reject/conversation_closed`; **no new row in `conversation_messages`** | AC-1 |
| P1-IT-02 | Chinese handoff | Returns `handoff`, `run=None`; one decision row `handoff/request_handoff` | AC-2 |
| P1-IT-03 | English `human` | Same as P1-IT-02 (**recorded as an intended difference from the baseline**) | AC-3 |
| P1-IT-04 | `mode=human` conversation | Message persisted, history updated, `run=None`; decision `defer/human_mode_active` | AC-4 |
| P1-IT-05 | Blacklisted customer | Human takeover requested; decision `handoff/blacklist_flag` | AC-5 |
| P1-IT-06 | Ordinary message | Run created and persisted side effects match the baseline; decision `continue/agent` | AC-6 |
| P1-IT-07 | No agent and `model_backend=unconfigured` | HTTP 409 `model_not_configured`; one decision row `reject/model_not_configured` | AC-7 |
| P1-IT-08 | Inject a decision write failure | **The main flow still succeeds after the SAVEPOINT rollback** (message persisted, Run created); a WARN is logged and nothing is raised; this tenant's in-process Counter-backed `routing_write_failures` increments by one and another tenant is unchanged; it resets on restart | AC-10 |
| P1-IT-09 | `_submit_run` raises and the outer transaction rolls back | No decision row (it lives and dies with the business outcome) | FR-1 |
| P1-IT-10 | Tenant B queries tenant A's conversation decisions | Empty result, no leakage | FR-5, AC-9 |
| P1-IT-11 | Aggregation endpoint | `disposition` / `reason_code` counts match what was written; `since/until` format and span validation apply | AC-9 |
| P1-IT-12 | Rerun AC-1~AC-7 with the switch off | Zero new decision rows; HTTP status codes match the baseline; **the FR-3 rule extension and the FR-4 contract do not roll back with the switch** | AC-8 |
| P1-IT-13 | SELECT count and order (recording enabled) | Same as before the refactor (proving `agent_snapshot` is not queried early); total SQL count is baseline `+1` (the new decision INSERT) | FR-2, 03 key constraint |
| P1-IT-14 | Lock-order assertions | Admission lock before conversation lock; the decision write adds no new lock | 01 risks, FR-1 |
| P1-IT-15 | Channel inbound receives the two 409 messages | For each event: first processing sets `status=processed` and `attempts=1`, with no second attempt and no pending/retry; exactly one `channel_receipts` row is written; `channels.last_activity_at` is updated and `last_error_code IS NULL` (no code change) | AC-12 |
| P1-IT-16 | Cursor pagination | Multiple rows sharing `created_at` are neither skipped nor duplicated (secondary ordering by `id`) | AC-9 |

## 5. General checklist (as applicable to this phase)

| # | Check | Pass criterion |
|---|---|---|
| P1-CM-01 | Migration is online-safe | Existing database `upgrade head` succeeds; `downgrade` drops only the new table; no existing table changed; `EXPLAIN (ANALYZE)` confirms the three indexes are hit by real queries |
| P1-CM-02 | Config loading and ownership | `trace_enabled` defaults to `false`; `AGENT_CS_ROUTING_TRACE_ENABLED` / `AGENT_CS_ROUTING_HANDOFF_RULES` overrides take effect; after deployment it stays off, then the designated environment/process canary explicitly enables it for a 7-day observation; this is not tenant-level canarying; **config defined inside the customer-service capability, zero new business items in `core_platform` settings** |
| P1-CM-03 | Observability surface | Table fields complete; **no event is published** (assert no new event task); no message text |
| P1-CM-04 | Tenant isolation | Unreachable across tenants (both list and aggregation verified) |
| P1-CM-05 | Core boundary | No new import of business modules in `core_platform`, no new business vocabulary (including strings); architecture gate passes |

## 6. Regression scope

- Whole backend: `pytest -m "not postgres"` and `pytest -m postgres` (two CI shards)
- Focused regression: `tests/test_*customer_service*`, `tests/test_runtime_postgres.py`, human-takeover
  cases, channel inbound cases
- Assertions: with the new table empty, existing behaviour is unchanged; **the HTTP status codes of the
  two 409s are unchanged**

## 7. Defect severity and exit criteria

| Severity | Definition | Handling |
|---|---|---|
| P0 blocking | The main flow is broken; messages are lost or messages that must not be persisted are persisted; cross-tenant leakage | Fix and regress before continuing |
| P1 serious | Branch behaviour differs from the baseline (except FR-3/FR-4); the switch is ineffective; a decision write failure affects the main flow | May not enter acceptance before fixing |
| P2 normal | Rule coverage gaps; aggregation discrepancies | Record and accept with known issues, product sign-off required |
| P3 minor | Wording, logs, comments | Schedule a fix |

**Exit criteria**: UT/IT/CM all pass; AC-1~AC-12 reproduce in the integration environment; the
regression suite is green; **the main flow still succeeds under injected SAVEPOINT failures**; **the
HTTP status codes of the two 409s match the baseline**; no open P0/P1.
