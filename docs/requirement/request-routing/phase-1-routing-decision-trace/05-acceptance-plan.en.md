# Phase 1 · Routing Decisions Visible — Acceptance Plan

> Status: to be executed (before this phase goes live)
> Created: 2026-10-30
> Basis: `01-business-goals.md` (G1~G3, success metrics), `02-requirements.md` (AC-1~AC-12); test
> execution follows `04-test-plan.md`

## 1. Acceptance goals and organisation

Confirm that this phase's deliverables are **functionally correct** (every AC reproduces),
**business-effective** (routing data is obtainable) and **safe to ship** (SAVEPOINT isolation, the two
409 contracts are under control, the switch can be turned off), then give a signed conclusion.

| Role | Responsibility |
|---|---|
| Product owner | Chairs acceptance; confirms the two intended behaviour changes in FR-3/FR-4; signs off P2 leftovers |
| QA | Executes and records AC scenarios; regression conclusion; defect severity |
| Engineering lead | Environment readiness; produces write-latency and failure-count data; fixes defects |
| Customer service operations representative | Judges the acceptability of the four-language rules (UAT) |

## 2. Acceptance environment and preconditions

| Environment | Purpose |
|---|---|
| Production-like environment (4 languages, including an English channel) | Functional acceptance, metric measurement |
| quickstart dual container (demo model) | Deployment-promise check (no model call involved, only verifying no regression) |

**Preconditions**: every case in `04-test-plan.md` passes with no open P0/P1; acceptance uses a
dedicated tenant and dedicated conversations; the baseline snapshot (HTTP status codes + persisted side
effects) has been captured from the pre-change version. `trace_enabled` defaults to `false` at
deployment. After migration and deployment smoke checks, the acceptance team explicitly sets it to
`true` in the dedicated acceptance environment/designated canary and confirms that decision rows are
writable before executing A1~A12. Metric measurement follows a 7-day observation after enabling. A8
separately turns recording off for its replay and restores it to `true` afterwards. This switch is
environment/process scoped, not tenant scoped.

## 3. Functional acceptance checklist (mapping AC-1~AC-12)

> This phase accepts **4 business dispositions** (Reject / Handoff / Defer / Continue) and **1 execution
> tier** (Agent) only; only `continue` carries `execution_tier='agent'`, while the other three
> dispositions use `NULL`.
> Direct / Lightweight / Resume / Escalate belong to later phases: not accepted, not promised.
> **This phase has two intended behaviour changes**: the FR-3 rule extension (English / Traditional
> Chinese / Hindi can reach a human) and FR-4 (the two 409s return a result).

| # | Acceptance step | Pass criterion |
|---|---|---|
| A1 | Close a conversation, then send a message | HTTP 409; one decision row `reject/conversation_closed`; **no new row in `conversation_messages`** (same as today) |
| A2 | Send `转人工` | Human takeover requested, no Run; decision `handoff/request_handoff` with a non-empty `matched_rule_id` |
| A3 | Send `human` (English channel) | Handoff; decision `handoff/user_requested_human`; **recorded as an intended difference from the baseline** |
| A4 | Send a message to a `mode=human` conversation | Message persisted, no Run; decision `defer/human_mode_active` |
| A5 | A blacklisted customer sends a message | Human takeover requested; decision `handoff/blacklist_flag` |
| A6 | Send an ordinary enquiry | A Run and a reply come out normally; decision `continue/agent/submit_agent_run` |
| A7 | Send a message with no agent and `model_backend=unconfigured` | HTTP 409 `model_not_configured`; decision `reject/model_not_configured` |
| A8 | After A1~A7 pass, temporarily turn `trace_enabled` off, replay A1~A7, then restore it | Zero new decision rows; HTTP status codes match the baseline; **FR-3/FR-4 do not roll back with the switch** (design decision, product must confirm it understands) |
| A9 | Query conversation decisions / tenant aggregation | Cursor pagination does not skip or duplicate identical timestamps; the aggregated distribution is correct; another tenant sees nothing; `since/until` validation applies |
| A10 | Inject a decision write failure | The main flow still succeeds; a WARN appears in the logs; the summary's `routing_write_failures` increments for the current tenant and remains unchanged for another tenant; it comes from the process-local Counter inside CustomerService, is not aggregated across replicas, and resets on restart |
| A11 | Send `your agent platform is slow` / a bare `agent` | No handoff; decision `continue/default_agent` |
| A12 | A channel sends a message to a closed conversation / to a conversation with no model configured | For each inbound event: `status=processed` and `attempts=1`, with no second attempt and no retry; exactly one `channel_receipts` row is written; `channels.last_activity_at` is updated and `last_error_code IS NULL` (no code change) |

Record for every scenario: executor, date, environment, precondition data, actual result, verdict, and
screenshot/log links.

## 4. UAT judgement (customer service operations representative)

- Whether the four-language deterministic keyword rules cover real customer phrasing (sample 20 real
  conversations, judge false positives and misses by hand; the threshold is confirmed by operations).
  In-sentence phrasing (`I want to speak to a human`) is known not to match, and operations must
  confirm that is acceptable.
- Whether the decision records are enough to support complaint attribution (verified by reviewing 3
  historical complaints).

## 5. Business metric acceptance

| Metric | Baseline | Target | Measurement |
|---|---|---|---|
| Decision coverage | 0 | **100% when the database is healthy** (including both Reject branches); write failures are counted and alerted separately, excluded from coverage | 100 consecutive messages from the dedicated tenant; decision rows / requests that returned successfully |
| Decision write failure rate | — | < 0.1% and observable | Aggregate WARN logs across replicas; the summary's `routing_write_failures` covers only the current process/tenant, resets on restart, and is not a global failure-rate source by itself |
| Added write latency P95 | — | ≤ 5ms | Statement duration of the decision INSERT, sample ≥ 100 |
| Human-request rule hits | 2 hard-coded Chinese words only | All four-language cases hit | Run the acceptance case set item by item |
| Routing data availability | none | Aggregatable by `disposition` and `reason_code` | Run A9 and export the distribution once, as input for the Phase 2 return estimate |
| Channel retries on permanent 409 | each of the two 409s starts with one attempt plus at most four retries (`max_attempts` defaults to 5), then fails | 0 retries; the first processing sets `processed` and `attempts=1` | Check `channel_inbound_events.attempts/status`, `channel_receipts`, and `channels.last_activity_at/last_error_code` |

## 6. Compliance checks

| # | Check | Verdict |
|---|---|---|
| C1 | Decision records contain no message text, digest or customer-sensitive information (only length and correlation ids) | Veto |
| C2 | Unreachable across tenants (both list and aggregation verified) | Must pass |
| C3 | The switch can turn recording off; **the FR-3/FR-4 behaviour changes can only be undone by rolling back the code, which has been stated explicitly** | Must pass |
| C4 | Core Platform has no business semantics introduced (architecture gate + manual string check) | Must pass |
| C5 | Business configuration (switch, human-request rules) is defined inside the customer-service capability, with zero new business items in `core_platform` settings | Must pass |

> C4 note: this project's architecture gate only checks import relationships and **does not check
> business vocabulary inside strings**. Core should be untouched in this phase, so a manual check costs
> very little.
> C5 note: putting the customer-service word list into Core Settings would drag phrases such as
> "转人工/人工客服/representative" into Core, the same kind of boundary violation, so it is listed
> separately.

## 7. Pass criteria and sign-off

- **Pass**: A1~A12 all pass; coverage (under healthy conditions) and write latency meet target; all
  compliance items pass; no P0/P1 leftovers; the distribution data Phase 2 needs has been produced.
- **Conditional pass**: only P2/P3 leftovers, each with an owner and a deadline, and the hard metrics
  meet target.
- **Fail**: any veto item triggers, or A1 shows "a message on a closed conversation got persisted", or
  A10 fails the transaction-isolation bar, or A8's switch semantics differ from what product understood.

Output the "Phase 1 Acceptance Report": AC execution records, metric measurements, compliance results,
the leftover list, and the conclusion with signatures (product / QA / engineering / customer service
operations).
