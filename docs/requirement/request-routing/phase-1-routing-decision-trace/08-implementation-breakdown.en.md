# Phase 1 · Routing Decisions Visible — Implementation Breakdown

> Status: adjudicated (technical lead breakdown; dev/qa use this as the execution baseline)
> Created: 2026-10-30
> Basis: all `01`~`05` documents + current-code inspection (backend @ `feat/phase-1-routing-decisions`)
> Constraints: Phase 1 only; no over-design; no `routing.decision_created` publication; no Outbox; no
> Core Platform changes; no channel business-branch changes.

## 0. Current-state inspection

This inspection executed no git commands and only read workspace files and code.

| Current state | Conclusion |
|---|---|
| `backend/migrations/versions/0053_routing_decisions.py` exists | The table, constraints and three indexes already have a draft; T1 must perform the final check |
| `backend/tests/test_routing_decisions_migration.py` exists | Migration SQL and PostgreSQL reversibility are covered; include it in T9 regression |
| `backend/src/agent_platform/business_capabilities/customer_service/service.py` already has routing wiring | `decide_ingress`, `_record_decision()`, Reject return and a per-tenant Counter are present; T4 must complete/verify them |
| `backend/src/agent_platform/applications/customer_service/platform_routes.py` already has query endpoints and Reject mapping | T5 must verify the behaviour and response contract |
| `backend/src/agent_platform/applications/platform_runtime/platform_services.py` already has configuration wiring | T5 must verify instance injection; it must not regress to a hidden module-level global |
| `backend/src/agent_platform/business_capabilities/customer_service/routing/` contains implementations of `__init__.py`, `decision.py`, `rules.py`, `settings.py` and `repository.py` | `settings.py` now defaults both `trace_enabled` and the `_default_settings()` fallback to `False` per R5; T2/T3 still need a final verification |
| `backend/tests/test_routing_*.py` already contains draft rule, decision, API, PostgreSQL, repository and migration tests | T6~T9 must complete, consolidate and regress them against the numbered cases in 04 |

This file is therefore organised as “complete unfinished implementation + verify already-landed
drafts”, not as a greenfield build.

## 1. Task breakdown (dependency order)

Critical path: **T1/T2 in parallel → T3 → T4 → T5 → T6/T7/T8 → T9**.

Parallel boundaries:

- T1 migration and T2 pure rules/configuration do not block each other.
- T6 rule and validator unit tests can start after T2; `CustomerService` cases wait for T4.
- T7 needs real PostgreSQL plus T1/T3/T4/T5; T8 verifies channels only, depends on T4/T5, and does
  not wait for the full T7 query-performance pass.
- T9 is the closure task and waits for T1~T8.

| # | Task | Files (new/modified) | Dependency | Trace |
|---|---|---|---|---|
| T1 | Migration check: verify `routing_decisions` fields, scope unique key, tier/length constraints, conversation/disposition/reason indexes, and `down_revision=0052_memory_tasks_tenant_index`; add no reserved columns | `backend/migrations/versions/0053_routing_decisions.py` (verify; modify only if needed) | — | FR-1, FR-2, FR-5; AC-1, AC-6, AC-7, AC-9; 04 P1-CM-01 |
| T2 | Complete the routing package: configuration model with explicit rule ids, normalisation and locale-agnostic union matching, duplicate-id/normalised-phrase validators, and the `decide_ingress()` sequence; configuration stays inside the customer-service capability, and `trace_enabled` must default to `False` | `backend/src/agent_platform/business_capabilities/customer_service/routing/__init__.py` (new/verify), `settings.py` (new/modify), `rules.py` (new/verify), `decision.py` (new/verify) | — | FR-2, FR-3, FR-6; AC-2, AC-3, AC-8, AC-11; 04 P1-UT-02~07, P1-UT-10~17 |
| T3 | Complete the repository: SAVEPOINT-isolated single-row write, `(created_at,id)` keyset query, aggregation by disposition/reason; return an explicit failure result, do not swallow connection-level errors; publish no events | `backend/src/agent_platform/business_capabilities/customer_service/routing/repository.py` (new/verify) | T1, T2 | FR-1, FR-5; AC-9, AC-10; 04 P1-IT-08~11, P1-IT-16 |
| T4 | Complete `CustomerService.send()`: decide, record, then execute by `action`; Reject writes no message; both 409s return `rejected`; process-local per-tenant failure Counter increments only when recording is enabled and the write fails | `backend/src/agent_platform/business_capabilities/customer_service/service.py` (modify/verify) | T2, T3 | FR-1~FR-4, FR-6; AC-1~AC-8, AC-10, AC-11; 04 P1-UT-01, P1-UT-04~09, P1-IT-01~09, P1-IT-12~14 |
| T5 | Wiring and API: construct and inject routing settings in `platform_services.py`; complete both read-only endpoints, Reject→409 mapping, cursor/time-window validation, and the summary `routing_write_failures` field | `backend/src/agent_platform/applications/platform_runtime/platform_services.py` (modify/verify), `backend/src/agent_platform/applications/customer_service/platform_routes.py` (modify/verify) | T3, T4 | FR-4, FR-5, FR-6; AC-1, AC-7, AC-9, AC-10; 04 P1-IT-10, P1-IT-11, P1-IT-16, P1-CM-02 |
| T6 | Unit tests: four-language rules, normalisation, exact-match counter-examples, locale-agnostic union, duplicate-id/normalised-phrase rejection, rule-id stability, decision mapping, switch off, per-tenant failure Counter | `backend/tests/test_routing_decisions_unit.py` (new) | T2, T4 | FR-2, FR-3, FR-6; AC-2, AC-3, AC-8, AC-10, AC-11; 04 P1-UT-01~17 |
| T7 | PostgreSQL integration tests: all decision classes persisted, both 409s persisted, Reject writes no message, SAVEPOINT isolation, outer rollback, cursor pagination, aggregation, tenant isolation, summary failure field | `backend/tests/test_routing_decisions_postgres.py` (new/extended) | T1, T3, T4, T5 | FR-1~FR-5; AC-1~AC-11; 04 P1-IT-01~14, P1-IT-16 |
| T8 | Channel end-to-end verification: **do not change the channel business branch**; both 409 inbound messages are `processed` on the first attempt, `attempts=1`, no second attempt; assert `channel_receipts`, `channels.last_activity_at`, `channels.last_error_code` | `backend/tests/test_routing_channel_postgres.py` (new/extended) | T4, T5 | FR-4; AC-12; 04 P1-IT-15 |
| T9 | Closure regression: migration up/down, real-query `EXPLAIN (ANALYZE, BUFFERS)`, relevant customer-service/runtime/channel suites, architecture gate, configuration defaults, and Chinese/English cross-check | `backend/tests/test_routing_decisions_migration.py` (modify/verify) and related existing tests; no new production code | T1~T8 | 04 §5~§7; P1-CM-01~05 |

Test paths are recommendations. If the repository's existing test layout is a better fit, files may be
reorganised without changing coverage or touching production code.

## 2. Document-versus-reality conflicts and adjudications

### R1 Channel attempts: the first attempt already moves from 0 to 1, and the retry cap is not “three”

The old wording described each of the two 409s as failing after a fixed three retries and required
attempts to stay unchanged after the fix.

Code reality:

- `backend/migrations/versions/0032_channel_inbound_outbox.py:28-29`: `attempts` defaults to 0 and
  `max_attempts` defaults to 5.
- `backend/src/agent_platform/business_capabilities/channel/service.py:758-765`: the worker executes
  `attempts=attempts+1` before calling `send()`.
- `backend/src/agent_platform/business_capabilities/channel/service.py:791-796`: after the attempt,
  `attempts` decides `processed` / `pending` / `failed`.

**Adjudication**:

- `attempts` means total executions; the first attempt increments it from 0 to 1.
- The default `max_attempts=5` means one first attempt plus at most four retries, five attempts total;
  the old baseline is not “three retries”.
- After the change, a permanent 409 returns normally, so the first execution is `status=processed`
  with `attempts=1`; there is no second attempt.
- All documents and tests must say: first attempt `attempts==1`, `status=processed`, no new `pending`;
  never describe attempts as unchanged.

Backfilled: `01-business-goals.md` success metrics/risks, `02-requirements.md` FR-4/AC-12,
`03-technical-design.md` channel flow, `04-test-plan.md` P1-IT-15, and
`05-acceptance-plan.md` A12/business metrics.

### R2 Human-request rules: locale-agnostic union, with rule id and normalised phrase as stable contracts

The old wording grouped rules by channel language and put `人工客服` in both zh-CN and zh-TW.

Code reality:

- `backend/src/agent_platform/business_capabilities/customer_service/service.py:125-144`: `send()`
  has no locale parameter.
- `backend/src/agent_platform/business_capabilities/customer_service/service.py:151-159`: the
  `decide_ingress()` call passes no channel language.
- The current workspace has no `customer_service/routing/` package, so the rule validator is not
  implemented yet.

**Adjudication**:

- Phase 1 matches the **locale-agnostic union** of all rules; `locale` is metadata only and does not
  filter matches.
- Rule ids are explicit and must not be derived from “locale + index”. Phase 1 and later Phase 2 use
  rule id and normalised phrase as stable contracts; an id must not be reused for new semantics.
- Normalised phrases (trim, case-fold, full-width to half-width, one trailing punctuation mark
  stripped) must be **globally unique**.
- The settings model must reject duplicate rule ids and duplicate normalised phrases; a parse or
  validation failure falls back to the default rules and logs a WARN.
- The exact default rules are:

| Rule id | locale | phrases |
|---|---|---|
| `zh_human_request_001` | `zh-CN` | `转人工`, `人工客服`, `客服` |
| `zhtw_human_request_001` | `zh-TW` | `轉人工` |
| `en_human_request_001` | `en` | `human`, `real person`, `representative`, `human agent` |
| `hi_human_request_001` | `hi` | `मानव`, `एजेंट` |

- A bare `agent` is not supported; use `real person` as the canonical English human expression, not
  the old two-word variant.
- Reordering rules or phrases must not change the `matched_rule_id` for the same phrase.

Backfilled: `01-business-goals.md` problems/scope/risks, `02-requirements.md` US-2/FR-3/AC-11,
`03-technical-design.md` configuration/rules, `04-test-plan.md` P1-UT-02~17, and
`05-acceptance-plan.md` UAT/acceptance steps.

### R3 Decision-write failure counter: process-local, per tenant, exposed through summary

The old wording only said “WARN only” and “failures are countable”, without saying where the count
lives.

Code reality:

- `backend/src/agent_platform/business_capabilities/customer_service/service.py:96`:
  `CustomerService` owns `_routing_write_failures: Counter[str]`.
- `backend/src/agent_platform/business_capabilities/customer_service/service.py:173-179`: it increments
  by `decision.tenant_id` only when recording is enabled and `record()` returns failure.
- `backend/src/agent_platform/business_capabilities/customer_service/service.py:328-332`: routing
  summary returns `routing_write_failures`.

**Adjudication**:

- The counter belongs to the `CustomerService` instance, is keyed by `tenant_id`, and is
  **process-local diagnostic state**.
- It is not a durable metric and does not aggregate across replicas; it resets on process restart.
  WARN logs remain the source for cross-replica alerting/log aggregation.
- `GET /routing-decisions/summary` returns the current process and current tenant's
  `routing_write_failures`; it is not promised to equal the global failure total.
- Production failure-rate metrics come from log/monitoring aggregation; the summary field supports
  single-process debugging and acceptance reproduction.
- A skip caused by `trace_enabled=false` is not a failure.

Backfilled: `01-business-goals.md` success metrics/risks, `02-requirements.md` FR-1/AC-10/non-functional
requirements, `03-technical-design.md` writes/queries, `04-test-plan.md` P1-IT-08/P1-IT-11, and
`05-acceptance-plan.md` A10/business metrics.

### R4 Channel Reject side effects: the normal success path writes a receipt and refreshes channel state

The old wording only said the inbound event becomes `processed`, without listing the other persisted
side effects of a successful return.

Code reality:

- `backend/src/agent_platform/business_capabilities/channel/service.py:661-672`: calls
  `customer.send()`; an empty `result["run"]` is treated as a normal result.
- `backend/src/agent_platform/business_capabilities/channel/service.py:673-689`: inserts
  `channel_receipts` and executes
  `UPDATE channels SET last_activity_at=now(),last_error_code=NULL`.
- `backend/src/agent_platform/business_capabilities/channel/service.py:791-816`: without an exception,
  the inbound event becomes `processed` and `processed_at` is set.

**Adjudication**:

- After `conversation_closed` / `model_not_configured` return `rejected`, the channel path treats
  them as normal success:
  - `channel_inbound_events.status='processed'`
  - `channel_inbound_events.attempts=1`
  - one new `channel_receipts` row
  - `channels.last_activity_at` refreshed
  - `channels.last_error_code` cleared
- There is no second attempt, no `pending`, and no retry for a permanent 409.
- These are intended FR-4 side effects and must not be mistaken for regressions.

Backfilled: `02-requirements.md` FR-4/AC-12, `03-technical-design.md` channel behaviour,
`04-test-plan.md` P1-IT-15, and `05-acceptance-plan.md` A12.

### R5 Default switch and canary: off by default, explicitly enabled in a designated canary

The old wording simultaneously said `trace_enabled` defaults to `true` and “enable the switch and
observe for 7 days”, which is contradictory.

Code reality:

- `backend/src/agent_platform/business_capabilities/customer_service/routing/settings.py:83` now
  defaults both `trace_enabled` and the `_default_settings()` fallback to `False` per this
  adjudication; regression tests must explicitly enable tracing before asserting writes.
- An earlier revision of
  `docs/requirement/request-routing/phase-1-routing-decision-trace/03-technical-design.md:210`
  described `trace_enabled` as enabled by default; this review backfilled it, and the current example
  is `False`.

**Adjudication**:

- The default is **`false`**.
- Deployment order: migrate → deploy the default-off build → smoke test → set
  `AGENT_CS_ROUTING_TRACE_ENABLED=true` in a designated canary environment → observe for 7 days →
  widen rollout.
- The switch is deployment/process-level environment configuration, not tenant-level and not a
  runtime dynamic toggle.
- It controls recording only and does not roll back FR-3 rule expansion or FR-4 return contracts.
- Before widening, inspect decision-write failure counts, WARN logs and summary distributions.

Backfilled: `02-requirements.md` FR-6, `03-technical-design.md` configuration/rollout,
`04-test-plan.md` P1-CM-02, and `05-acceptance-plan.md` A8/business metrics.

### R6 Examples and tests: canonical vocabulary plus zh-TW, hi and validator cases

The old wording mixed several English human-request variants, bare `agent` and Traditional Chinese
`客服`, and four-language coverage was incomplete.

Code reality:

- Matching is exact; there is no locale input, so language grouping cannot explain phrase matching.
- The current workspace has no rules module or corresponding unit tests.

**Adjudication**:

- Canonical examples: `human`, `real person`, `representative`, `human agent`, `转人工`, `人工客服`,
  `客服`, `轉人工`, `मानव`, `एजेंट`.
- Bare `agent`, `your agent platform is slow` and `human being` must remain non-matches.
- Add explicit tests: zh-TW `轉人工` → `zhtw_human_request_001`; hi `मानव`/`एजेंट` →
  `hi_human_request_001`.
- Add explicit tests that duplicate rule ids and duplicate normalised phrases are rejected by the
  validator.
- Add a locale-agnostic case: `客服` always matches `zh_human_request_001`, independent of channel
  locale.

Backfilled: `01-business-goals.md` examples, `02-requirements.md` FR-3/AC-11,
`03-technical-design.md` rule semantics, `04-test-plan.md` P1-UT-02~17, and
`05-acceptance-plan.md` UAT.

### R7 Scope ruling: no events, no Outbox, no channel business branch, zero Core business semantics

The old wording already deferred events, but the implementation baseline must lock this down to avoid
scope creep.

Code reality:

- `backend/src/agent_platform/business_capabilities/customer_service/service.py:151-170`: the current
  routing path only decides, records and applies; it publishes no `routing.decision_created`.
- The channel path can handle Reject as a normal result with its existing logic at
  `backend/src/agent_platform/business_capabilities/channel/service.py:661-689`, with no dedicated
  branch.
- Core Platform gains no new business configuration or rule vocabulary.

**Adjudication**:

- This phase publishes no `routing.decision_created`, creates no Outbox and adds no message-reliability
  infrastructure.
- `channel/service.py` gains no dedicated Reject branch; tests verify the existing success path only.
- Do not modify `core_platform`; do not put the customer-service vocabulary, switch or decision rules
  into Core Settings.
- Any future event work must separately review the real commit point, decision-id backfill and the
  existing event-bus scope defect.

Backfilled: `03-technical-design.md` known limitations/channel/rollout, `04-test-plan.md`
P1-IT-15/P1-CM-03/P1-CM-05, and `05-acceptance-plan.md` compliance checks.

## 3. Execution order, hand-off and red lines

### 3.1 Execution order

1. **T1 + T2 in parallel**: freeze the migration contract and the pure rules/configuration contract
   first. T2 must make the routing package importable.
2. **T3**: implement SAVEPOINT writes, queries and aggregation; publish no events.
3. **T4**: wire `send()`, complete Reject returns, the per-tenant failure Counter and the existing
   lock order.
4. **T5**: complete dependency injection, query endpoints, Reject→409 and the summary failure field.
5. **T6 / T7 / T8**: rule unit tests, PostgreSQL integration tests and channel end-to-end verification
   may run in parallel; channel verification does not wait for query-performance cases.
6. **T9**: run migration reversibility, EXPLAIN, relevant regression and the architecture gate, then
   feed the results into `06-test-report.md`.

### 3.2 Hand-off to dev

- Use the FR/AC in `02` and the decision sequence in `03` as the only behaviour contract. Log a new R
  item before widening scope if reality conflicts.
- The rule default switch is `false`; tests must explicitly enable it before checking writes.
- A `record()` failure may roll back only to the SAVEPOINT; it must not backfire on message handling
  or Run creation.
- Reject writes no `conversation_messages`; both 409s still return 409 at the HTTP boundary.
- Add no `routing.decision_created`, Outbox, Core configuration or dedicated channel business branch.
- Preserve the order “admission advisory lock → conversation row lock → decision write”.
- Every query endpoint must carry tenant/business/workspace predicates; the summary failure count
  must state that it is process-local and tenant-specific.

### 3.3 Hand-off to QA

- Execute P1-UT-01~17, P1-IT-01~16 and P1-CM-01~05 from `04-test-plan.md`.
- Channel cases must assert `status=processed`, `attempts=1`, a new receipt, refreshed
  `last_activity_at`, and `last_error_code=NULL`.
- Failure-counter cases must verify: main flow succeeds, WARN exists, the same tenant's summary count
  increases, another tenant does not, and a restart/new instance resets the count.
- Cover zh-CN, zh-TW, en and hi; duplicate normalised phrases and bare `agent` must have negative
  cases.
- Migration/query cases must run `EXPLAIN (ANALYZE, BUFFERS)` and verify keyset pagination does not
  skip or duplicate rows with identical timestamps.
- No events, no Outbox and zero Core business vocabulary are general checks, not optional
  functional-test footnotes.

### 3.4 Red lines

- Cross-tenant reads/writes, or decision records leaking message text/digests: stop immediately.
- Reject writing `conversation_messages`, or a closed-conversation message being persisted: stop
  immediately.
- A decision-write failure breaking message handling or Run creation: stop immediately.
- A permanent 409 still retrying, `attempts > 1`, or status not `processed`: stop immediately.
- Locale-dependent matching, duplicate phrases silently accepted, or bare `agent` misclassified:
  block the corresponding test.
- Business vocabulary/configuration in Core Platform, or an unapproved event: block the merge.

### 3.5 Delivery boundary

This file defines only the Phase 1 implementation and verification baseline. It does not implement
code, modify `01`~`05`, run git, or commit. The test report and acceptance report record the real
results after implementation.
