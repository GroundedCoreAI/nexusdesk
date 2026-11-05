# Phase 1 · Routing Decisions Visible — Business Goals

> Phase: Phase 1 (MVP, with two intended behaviour changes: FR-3 and FR-4)
> Estimated effort: ~1 week
> Dependency: none (does not depend on Phase 2-4)

## Problems to solve

### Problem 1: ingress decisions are invisible, production issues cannot be attributed

`business_capabilities/customer_service/service.py::send()` uses a chain of `if` statements to decide
where a message goes:

| Line | Branch | Result |
|---|---|---|
| 129 | `mode == "closed"` | `DomainError("conversation_closed", 409)` |
| 131 | `message.strip() in {"转人工","人工客服"}` | Request human takeover, no Run created |
| 142 | `mode in {"human","waiting"}` | Persist only, no Run created |
| 167 | Blacklist flag hit with the switch on | Request human takeover, no Run created |
| other | — | Submit a Run, enter the ReAct loop |

All five branches **leave no structured record**. Typical damage: a customer complains "I sent a
message and nobody answered"; investigating means paging through application logs and inferring from
conversation state by hand, and even then nobody can answer "which class was this message judged as,
and on what basis". Every recurrence of the same question starts the investigation from scratch.

### Problem 2: handoff detection covers Chinese only and is not configurable

Line 131 hard-codes `{"转人工", "人工客服"}`. The platform already ships 7 channel adapters and 4
languages, so an overseas user on Telegram / Discord / Slack saying `human` or `客服` is not
recognised, and the message enters the ordinary ReAct flow instead of a handoff. A bare `agent` is
explicitly excluded from the default rules because of its false-positive risk. The word list also
lives in service code, so a tenant cannot configure its own human-request phrasing.

### Problem 3: no routing data, so later tiers cannot prove their value

Phase 2's `direct` tier and Phase 3's `lightweight` tier both presuppose that **simple questions are a
large enough share of real traffic**. Today there is no aggregation by branch or by reason, so nobody
can answer "if we build deterministic answers, how much traffic do they absorb and how much latency do
they save". Investing in tier work without that data means an uncertain return.

## Business goals

| Goal | Description |
|---|---|
| G1: decisions queryable | Every inbound message produces one structured decision record (which class, on what basis, where it went), queryable and aggregatable by conversation, tenant and reason |
| G2: human requests configurable and multilingual | Human-request detection covers zh-CN / zh-TW / en / hi with **deterministic keyword rules** (not intent recognition); deterministic hits outrank the model; the rules are owned by the customer-service capability and never enter Core |
| G3: a routing baseline | Branch shares and reason distributions can be counted, giving Phase 2/3 a basis for return estimates |

## Success metrics

| Metric | Baseline (today) | Target |
|---|---|---|
| Decision coverage | 0 (no records at all) | **100% when the database is healthy**, including both Reject branches (`conversation_closed` / `model_not_configured`); write failures are counted separately and excluded from coverage |
| Decision write failure rate | — | < 0.1% and observable (the process-local per-tenant failure counter inside CustomerService plus WARN logs; aggregate logs across replicas for the cross-replica rate) |
| Compatibility | — | **Except FR-3 (rule extension) and FR-4 (two 409s return a result)**, every other branch matches the baseline in HTTP status code and persisted side effects |
| Human-request rule hits | 2 hard-coded Chinese words only | All four-language cases hit; in-sentence phrasing (`I want to speak to a human`) is explicitly recorded as a known gap |
| Decision write cost | — | Added write latency P95 ≤ 5ms per message (one row inside a SAVEPOINT) |
| Routing data availability | none | Shares aggregatable by `disposition` and `reason_code`, enough to size Phase 2 |
| Channel retries on permanent 409 | each of the two 409s gets the first attempt plus up to 4 retries (default `max_attempts=5`, at most 5 attempts in total), then failed | The first attempt is marked `processed` with `attempts=1`; no second attempt and no retries |

## Scope

**Included**:

- Routing decision data model and migration (`0053_routing_decisions`)
- `send()` refactor: turn the implicit `if` chain into explicit decision output (**the execution result
  does not change except for the two intended behaviour changes in FR-3 and FR-4**)
- Human-request rules (four languages, configured by the customer-service capability, matched as a
  locale-agnostic union, rules carry an explicit id; locale is metadata only and normalised phrases
  are globally unique)
- **Contract change for the two 409s**: `conversation_closed` and `model_not_configured` return a
  `rejected` result instead of raising, so the decision record can be persisted, and the channel's
  useless retries on a permanent 409 stop
- Decision query API (aggregation by conversation / by tenant, keyset cursor pagination and a maximum
  time span)
- `trace_enabled` defaults to off; after migration and verification, enable it explicitly in a
  designated canary environment and observe for 7 days

**Excluded** (later phases, or explicitly out of scope):

- **Event publication** — this phase does not publish `routing.decision_created`. Nothing consumes it
  yet, and publishing needs the decision id filled in, a way to tell where the two call paths really
  commit (when a channel passes an external connection, `transaction()` does not commit), and would
  amplify the existing scope defect in the event bus. Add it once a consumer exists and delivery
  semantics are clear
- `direct` / `lightweight` execution tiers — Phase 2 / Phase 3. **The only response path implemented
  today is the ReAct loop** (`core_platform/agent_runtime/engine.py`); there is no "deterministic
  answer without a model" path and no "lightweight retrieval answer" path
- `Resume` (resume a task across turns) — Phase 4, depends on the in-conversation task model
- `Escalate` (change the handling subject or policy mid-execution) — Phase 3
- Core Platform's provider host and execution-tier loop — Phase 3 (when a second execution path exists)
- The in-conversation task model `conversation_tasks` — Phase 4
- Execution Profile and budget management — Phase 3
- Frontend routing configuration page — from Phase 2 (this phase provides the query API only)
- A model classifier — this phase uses no model in routing decisions
- **Tenant-level overrides of human-request rules** — the existing `CapabilityConfigService` is
  platform-level with no tenant override, so this phase offers environment-variable configuration only
- **Reliable event delivery (Outbox)** — the repository has no Outbox, this phase publishes no events,
  and message-reliability infrastructure is not built

**How this phase relates to the path model**: except for the two intended changes in FR-3 and FR-4,
Phase 1 records **behaviour that already exists** and adds no path. The five existing branches collapse
into 4 business dispositions (Reject / Handoff / Defer / Continue); only `continue` has
`execution_tier='agent'`, while Reject / Handoff / Defer use `NULL`. **No reserved columns**
(`task_relation` / `escalate_from` / `decision_type` / `stage_ids` / `confidence` / `profile_ref`) —
creating columns before the semantics settle means letting an unproven abstraction hold later phases
hostage.

**Incidental fixes (tightly coupled to this phase, independent of later tiers)**:

- Human-request detection goes from "two Chinese words" to a four-language rule set (Problem 2);
  otherwise the Handoff path effectively does not exist for overseas channels
- **Reject is currently silent for channel customers**: after `conversation_closed` raises 409, the
  channel records `error_code` and keeps trying with the first attempt plus up to 4 retries (default
  `max_attempts=5`) until it fails, and the customer never receives any reply. This phase uses the
  FR-4 contract change to **persist the decision and stop the useless retries**; the customer-visible
  scripted reply still arrives with the Phase 2 Direct tier (a fixed script, no FAQ data needed)

## Risks and constraints

- **Risk of changing behaviour by accident**: `send()` is the main customer-service path, so any change
  in branch semantics hits production directly. Mitigation: separate decision output from execution
  (compute the decision first, then execute it), and lock equivalence with a `reason_code` ↔ original
  branch mapping table plus branch-by-branch comparison tests.
- **Lock-order risk**: `send()` already fixes the order "admission lock `pg_advisory_xact_lock(71432019)`
  → conversation row `FOR UPDATE`" (lines 116-128). The decision write must happen inside the same
  transaction and **after** that lock order; no new transaction and no earlier lock acquisition,
  otherwise an inverted lock order can deadlock.
- **Write cost**: one row per message. Mitigation: single-row insert, indexes designed around query
  paths, and a switch that turns the whole thing off; if volume grows, move to asynchronous event
  aggregation (not in this phase).
- **Data lifecycle**: this table **stores neither message text nor a digest** (SHA-256 over short texts
  such as "refund / check order" can be reversed with a dictionary, so it is not anonymisation). Only
  `message_length` and `request_id`.
- **Transaction-semantics risk**: if an observability write failure simply swallows the Python
  exception, the PostgreSQL transaction is already aborted and every later business write fails,
  killing the main flow in exactly the scenario the write was meant to protect. Mitigation: isolate
  with a `SAVEPOINT` (`begin_nested()`, already used at `conversation/service.py:346`). Boundary: when
  the connection drops or the transaction is invalid, the SAVEPOINT is equally ineffective and existing
  error handling decides the request fails; **absolute isolation is not promised**.
- **Intended behaviour-change risk**: this phase is **not zero behaviour change**. The rule extension
  turns messages such as `human` / `real person` / `客服` from "continue to Agent" into "handoff";
  the return contract of the two 409s changes as well, and the switch cannot roll either back.
  Mitigation: list both as intended changes in 01/02/05, give A3 its own acceptance item, and have A8
  require product to confirm that "the switch only turns recording off, it does not roll behaviour
  back".
- **Deferred-event risk**: this phase publishes no events, so external systems relying on
  `routing.decision_created` get nothing (there is no consumer today). Logged as known limitation L1.
- **Reject contract-change risk**: `send()` moves from raising to returning a `rejected` result, and
  both callers (the HTTP messages endpoint and channel inbound) must change together; a missed caller
  turns a 409 into a 200 or leaves the channel retrying. Mitigation: AC-1 / AC-7 / AC-12 lock both
  callers.
- **Compatibility**: the new table is purely additive and does not alter existing tables; existing
  conversations need no backfill. **Except FR-3 and FR-4**, every other branch matches the baseline in
  HTTP status code and persisted side effects.
