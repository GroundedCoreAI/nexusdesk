# Phase 1 · Routing Decisions Visible — Requirements

## User stories

**US-1 (customer service supervisor)**: As a customer service supervisor, I want to see which class
each customer message was judged into and on what basis, so that when a customer complains nobody
replied I can attribute it quickly instead of guessing from application logs.

**US-2 (overseas operations)**: As the operator responsible for overseas channels, I want a customer
saying "human" or "客服" to reach a human regardless of channel language, so that overseas users do
not get stuck in the bot flow.

**US-3 (product owner)**: As a product owner, I want the real share of each branch, so that I can
decide whether the `direct` / `lightweight` tier work is worth funding instead of scheduling by gut
feel.

**US-4 (engineering)**: As an engineer, I need a way to verify the ingress refactor item by item, so
that reworking the main customer-service path does not introduce regressions.

## Functional requirements

### FR-1 Routing decision capture

| Item | Description |
|---|---|
| Trigger point | After `CustomerService.send()` finishes its checks and before it executes an action |
| Input | Conversation row (`mode`, `customer_id`, `agent_id`), message text and length, effective memory switch and flags, human-request rule match result, and this request's `request_id` |
| Output | One `routing_decisions` row: `disposition`, `execution_tier`, `action`, `reason_code`, `matched_rule_id`, `decider`, `message_length` |
| Execution | Synchronous, written **inside `send()`'s existing transaction and isolated with a SAVEPOINT**; no new transaction, no change to lock order |
| Failure handling | A write failure **must not** affect message handling: roll back to the SAVEPOINT, log a WARN, increment the process-local per-tenant failure counter in `CustomerService` (returned as `routing_write_failures` by the routing summary), and continue with the existing branch; no retry. The counter is not aggregated across replicas/processes and resets on restart. When the connection drops or the transaction is invalid, existing database error handling decides that the whole request fails; absolute isolation is not promised |
| Boundary | **This phase publishes no events** (no consumer, and the two call paths really commit at different points); it writes the table only |

### FR-2 Decision semantics equivalent to the status quo (hard constraint)

A decision record is expressed by **dimension**, not as a single mode enum:

- `disposition`: business disposition (`reject` / `handoff` / `defer` / `continue`)
- `execution_tier`: execution tier, **only `continue` may carry a value**, and `agent` is the only
  value in this phase
- `action`: the execution instruction inside the customer-service capability; the executor dispatches
  on it, **not on `reason_code`**
- `reason_code`: explains **why**
- `matched_rule_id`: the concrete rule that matched (only human-request rules set it)

The decision sequence must be **action-equivalent** to the status quo (except the two intended changes
in FR-3 and FR-4):

| Current branch (`service.py`) | `disposition` | `execution_tier` | `action` | `reason_code` |
|---|---|---|---|---|
| Line 129 `mode == "closed"` | `reject` | `NULL` | `reject` | `conversation_closed` |
| Line 131 human-request rule hit | `handoff` | `NULL` | `request_handoff` | `user_requested_human` |
| Line 142 `mode == "human"` | `defer` | `NULL` | `defer` | `human_mode_active` |
| Line 142 `mode == "waiting"` | `defer` | `NULL` | `defer` | `waiting_mode_active` |
| Line 167 blacklist flag hit | `handoff` | `NULL` | `request_handoff` | `blacklist_flag` |
| Line 196 `model_backend == "unconfigured"` with no agent | `reject` | `NULL` | `reject` | `model_not_configured` |
| Everything else | `continue` | `agent` | `submit_agent_run` | `default_agent` |

Every row also writes `decider = "cs_routing_v1"` (the version of the rule set; **no longer
`legacy_branch_v1`**, because the rules now cover more than the legacy branches). **No reserved
columns** (`task_relation` / `escalate_from` / `decision_type` / `stage_ids` / `confidence` /
`profile_ref`); nothing is created before the semantics settle.

### FR-3 Human-request rules (deterministic keywords, not intent recognition)

| Item | Description |
|---|---|
| Trigger point | The same position as line 131 today, replacing the hard-coded set |
| Normalisation | Trim, case-fold, full-width to half-width, strip one trailing punctuation mark |
| Matching | The whole message must **equal** a rule phrase; **arbitrary substring containment is forbidden**, otherwise `your agent platform is slow` would be misjudged |
| Match scope | **Locale-agnostic union matching**: `locale` is rule metadata only and does not filter matching; one message may hit a rule from any locale |
| Rule shape | `{"id": "en_human_request_001", "locale": "en", "phrases": [...]}`; the **id must be explicit** and must not be built from "language + index", otherwise reordering the word list makes historical records point at the wrong rule |
| Stability and uniqueness | The rule id and normalised phrase are stable contracts across phases; rule ids are globally unique and normalised phrases must be globally unique. Reordering rules or phrases must not change the `matched_rule_id` for the same phrase |
| Output | On a hit: `disposition=handoff`, `reason_code=user_requested_human`, `matched_rule_id=<rule id>` |
| Default rules | zh-CN (`转人工`, `人工客服`, `客服`), zh-TW (`轉人工`), en (`human`, `real person`, `representative`, `human agent`), hi (`मानव`, `एजेंट`) |
| Failure handling | If configuration parsing or validation fails (including duplicate ids or duplicate normalised phrases such as `" HUMAN "` and `human`), fall back to the default rules and log a WARN; a configuration error must never turn a normal message into a handoff |

**Explicit boundary**: these are **configurable deterministic keyword rules**, not full multilingual
intent recognition. In-sentence phrasing such as `I want to speak to a human` does **not** match, and
that is a deliberate trade-off; a bare `agent` carries false-positive risk and is **explicitly not
supported**, so the default uses `human agent`.

### FR-4 The two 409s return a result (fixing lost decisions and channel retries)

| Item | Description |
|---|---|
| Current problem | `conversation_closed` (line 129) and `model_not_configured` (line 196) both `raise DomainError(409)`: the whole transaction rolls back, so the decision record is lost; the channel treats 409 as retryable and uses the first attempt plus up to 4 retries (default `max_attempts=5`, at most 5 attempts in total) before marking it failed, and the customer never receives a reply |
| Change | `send()` returns `{"conversation_id", "run": None, "rejected": "<reason_code>"}` instead of raising |
| Caller mapping | The messages endpoint in `platform_routes.py` maps `rejected` to 409 (external status code unchanged) |
| Channel behaviour | **No code change**: `_accept_envelope` already branches on `result["run"]` and, when it is `None`, writes `channel_receipts`, updates `channels.last_activity_at` and clears `last_error_code`; once `send()` stops raising, the inbound event is marked `processed` with `attempts==1`, no second attempt occurs, and retries stop |
| Blast radius | The exception contract of `send()` changes; this is the only caller-side change in this phase. Channel Reject moves from "failure and retry" to "successful first processing" with the normal successful side effects above |

### FR-5 Decision queries

| Item | Description |
|---|---|
| List | Newest first per conversation; `limit` defaults to 50 and is capped at 200; `before` is an opaque `base64("<created_at_iso>|<id>")` cursor, and the server pages by the `(created_at, id)` keyset |
| Aggregation | Counts by the two dimensions `disposition` and `reason_code`; the response includes `routing_write_failures` for the current process and tenant |
| Time range | `since` / `until` are ISO 8601; `since < until` is required; maximum span 31 days; both default to the last 7 days when omitted |
| Permissions | Reuses the existing tenant and scope isolation; unreachable across tenants |

### FR-6 Switch and configuration

| Item | Owner | Default | Description |
|---|---|---|---|
| `trace_enabled` | **Customer-service capability config** (`customer_service/routing/settings.py`) | `false` | When off, no decision rows are written; after migration and verification, enable it explicitly in the designated canary environment |
| `handoff_rules` | **Customer-service capability config** | The four-language default rules (with explicit ids) | Human-request rules |

- **Business configuration does not go into Core Settings**: the customer-service word list is a
  business rule, and putting it in `core_platform/.../settings.py` would drag business vocabulary into
  Core.
- Injection point: where `applications/platform_runtime/platform_services.py` constructs
  `CustomerService`; no module-level global.
- Environment-variable prefix `AGENT_CS_ROUTING_`; tenant-level overrides are limited by the existing
  mechanism (`CapabilityConfigService` is platform-level), so this phase **does not promise tenant
  overrides**.
- Canary rollout is environment/process-level, not tenant-level: keep `trace_enabled=false` after
  deployment, then set it to `true` in the designated canary environment after migration and
  verification, and observe for 7 days.
- **The switch controls recording only**; it does not roll back the FR-3 rule extension or the FR-4
  return contract.

## Non-functional requirements

- **Performance**: one extra single-row INSERT per message (inside a SAVEPOINT), added latency P95
  ≤ 5ms.
- **Compatibility**: **except FR-3 and FR-4**, every other path matches the baseline in HTTP status
  code and persisted side effects; the rule extension is an intended behaviour change (`human` moves
  from `continue` to `handoff`).
- **Multi-tenancy**: `tenant_id` / `business_id` / `workspace_id` are mandatory, and every read path
  carries scope predicates.
- **Privacy**: **no text, no digest**; only `message_length` (SHA-256 over short texts can be reversed
  with a dictionary, so it is not anonymisation).
- **Observability**: this phase relies on the decision table, the process-local
  `routing_write_failures` counter and WARN logs, and publishes no events. The counter is not
  aggregated across replicas/processes and resets on restart; cross-replica failure-rate measurement
  relies on WARN log aggregation.

## Acceptance criteria

| # | Scenario | Expected |
|---|---|---|
| AC-1 | Send a message to a `mode=closed` conversation | The API returns 409 `conversation_closed`; `send()` returns `rejected`; **the decision is persisted** as `reject / conversation_closed`; **no row is written to `conversation_messages`** (same as today) |
| AC-2 | Send `转人工` | Human takeover requested, no Run; decision `handoff / request_handoff / user_requested_human` with a non-empty `matched_rule_id` |
| AC-3 | Send `human` (English) | **Intended behaviour change**: previously `continue`, now a handoff; decision `handoff / user_requested_human` |
| AC-4 | Send a message to a `mode=human` conversation | Message persisted, no Run; decision `defer / human_mode_active` |
| AC-5 | A blacklisted customer sends a message with the switch on | Human takeover requested, no Run; decision `handoff / blacklist_flag` |
| AC-6 | An ordinary message | A Run is submitted; decision `continue / agent / submit_agent_run / default_agent` |
| AC-7 | No agent and `model_backend=unconfigured` | The API returns 409 `model_not_configured`; **the decision is persisted** as `reject / model_not_configured` |
| AC-8 | Repeat AC-1~AC-7 with `trace_enabled` off | Zero new decision rows; HTTP status codes match the baseline; **the FR-3 rule extension and the FR-4 return contract do not roll back with the switch** |
| AC-9 | Query one conversation's decisions / tenant aggregation | Cursor pagination is correct (no gap or duplicate at identical timestamps); aggregation by `disposition` and `reason_code` is correct; another tenant sees nothing; `since/until` validation applies |
| AC-10 | Inject a decision write failure (a trigger raises) | The main flow still succeeds (SAVEPOINT rollback); only a WARN; nothing is raised to the caller; `routing_write_failures` for the current tenant increases by 1 in the summary and stays unchanged for another tenant; the counter is process-local and resets on restart |
| AC-11 | Send `your agent platform is slow` / a bare `agent` | Exact matching and no bare `agent` in the default rules: no handoff; decision `continue/default_agent` |
| AC-12 | Channel inbound receives messages for the two 409 cases | The inbound event is marked `processed` with `attempts==1`; no second attempt and no retry; `channel_receipts` is written normally; `channels.last_activity_at` is updated and `last_error_code` is cleared (**verification only, no code change**) |
