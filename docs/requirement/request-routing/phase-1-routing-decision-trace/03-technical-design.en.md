# Phase 1 · Routing Decisions Visible — Technical Design

> The current code was checked before writing this document (`service.py` decision branches,
> `store.py::transaction`, the `channel/service.py` call path, `events.py::_ensure_task`, the `0041`
> observability-table convention, the mount prefix in `application.py`).
> Revised (2026-10-30): initial version.
> Revised (2026-10-30): rewritten after technical review — SAVEPOINT isolation for decision writes,
> Reject and model_not_configured return results, unshaped reserved columns removed, configuration
> moved to the business capability.
> Revised (2026-10-30): corrected after the second review round — **this phase publishes no events**,
> the Reject branch no longer calls `add_message`, the channel change is reduced to "verification
> only", and compatibility is restated as "equivalent at the HTTP boundary and in persisted side
> effects only".
> Revised (2026-10-30): corrected after the third review round — channel `attempts` and the default
> `max_attempts` contract were aligned, rules became a locale-agnostic union with id/phrase
> uniqueness validation, the process-local write-failure counter was specified, the channel receipt
> side effects for Reject were made explicit, and the switch defaults to false with environment-level
> canarying.

## The exact definition of Phase 1

This phase is **not** "pure observability with zero behaviour change". It combines three things:

1. **Decisions visible**: the implicit `if` chain in `send()` becomes queryable `routing_decisions`
   records
2. **Human-request rules extended**: from two hard-coded Chinese words to configurable four-language
   rules
3. **Channel retry fix**: the two permanent 409s (`conversation_closed` / `model_not_configured`) never
   reach a second attempt. With the default
   `channel_inbound_events.max_attempts = 5`, the baseline is the first attempt plus at most four
   retries, for at most five attempts before `failed`; after the change the first attempt is
   `processed`.

So the compatibility promise is: **except FR-3 (rule extension) and FR-4 (the two 409s return a
result), every other path is equivalent to the baseline at the HTTP boundary and in persisted side
effects.**

## Change overview

| Layer | File | Change |
|---|---|---|
| Migration | `backend/migrations/versions/0053_routing_decisions.py` | Create the `routing_decisions` table, three indexes, three CHECKs and one unique constraint |
| New module | `backend/src/agent_platform/business_capabilities/customer_service/routing/__init__.py` | Package entry point |
| New module | `backend/src/agent_platform/business_capabilities/customer_service/routing/decision.py` | `RoutingDecision` dataclass, constants, the `decide_ingress()` decision sequence |
| New module | `backend/src/agent_platform/business_capabilities/customer_service/routing/rules.py` | Normalisation and human-request rule matching |
| New module | `backend/src/agent_platform/business_capabilities/customer_service/routing/repository.py` | Decision writes (SAVEPOINT) and queries |
| New module | `backend/src/agent_platform/business_capabilities/customer_service/routing/settings.py` | `CustomerServiceRoutingSettings` (business config does not go into Core) |
| Entry point | `backend/src/agent_platform/business_capabilities/customer_service/service.py` | `send()` becomes "decide, record, execute"; the two 409s return `rejected` |
| API | `backend/src/agent_platform/applications/customer_service/platform_routes.py` | Two read-only endpoints; the messages endpoint maps `rejected` to 409 |
| Wiring | `backend/src/agent_platform/applications/platform_runtime/platform_services.py` | Inject the routing settings where `CustomerService` is constructed (no module-level global) |
| Channel | `backend/src/agent_platform/business_capabilities/channel/service.py` | **No code change**, verification only: when `send()` returns `rejected`, the receipt is still written and the inbound event is `processed` with `attempts==1` on its first attempt, with no second attempt |
| Events | — | **This phase publishes no events** (no consumer; the reason is under "Known limitations") |
| Frontend | — | No changes |

**Zero Core Platform changes**: no new ports, no new execution tiers, no modification of
`agent_runtime`, and no business configuration added to Core Settings.

## Data model

### Migration `0053_routing_decisions.py`

```sql
CREATE TABLE routing_decisions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       TEXT        NOT NULL,
    business_id     TEXT        NOT NULL,
    workspace_id    TEXT        NOT NULL,
    conversation_id UUID        NOT NULL,   -- no FK: matches memory_injection_log / audit_records
    request_id      UUID        NOT NULL,   -- one per send(), pairing a decision with an inbound attempt
    disposition     TEXT        NOT NULL,   -- reject | handoff | defer | continue
    execution_tier  TEXT        NULL,       -- agent (the only value in this phase)
    action          TEXT        NOT NULL,   -- execution instruction inside customer service
    reason_code     TEXT        NOT NULL,   -- explains "why"; carries no dispatch responsibility
    matched_rule_id TEXT        NULL,       -- id of the matched rule
    decider         TEXT        NOT NULL,   -- cs_routing_v1
    message_length  INTEGER     NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT routing_decisions_request_unique
        UNIQUE (tenant_id, business_id, workspace_id, request_id),
    CONSTRAINT routing_decisions_tier_requires_continue
        CHECK (execution_tier IS NULL OR disposition = 'continue'),
    CONSTRAINT routing_decisions_tier_known
        CHECK (execution_tier IS NULL OR execution_tier = 'agent'),
    CONSTRAINT routing_decisions_length_non_negative
        CHECK (message_length >= 0)
);

CREATE INDEX routing_decisions_conversation
    ON routing_decisions(tenant_id, business_id, workspace_id, conversation_id, created_at DESC, id DESC);

CREATE INDEX routing_decisions_disposition
    ON routing_decisions(tenant_id, business_id, workspace_id, disposition, created_at DESC);

CREATE INDEX routing_decisions_reason
    ON routing_decisions(tenant_id, business_id, workspace_id, reason_code, created_at DESC);
```

`down_revision` points to `0052_memory_tasks_tenant_index`.

Design notes:

- **No foreign keys.** Observability and audit tables in this repository do not use foreign keys:
  `memory_injection_log` (0041) has a bare `run_id UUID NOT NULL` plus `retention_days`, and
  `audit_records` uses `resource TEXT`. A `REFERENCES ... ON DELETE CASCADE` would delete audit data
  when a conversation is deleted.
- **The CHECK is one-way.** It only enforces "a tier requires `continue`", not "`continue` requires a
  tier"; otherwise future `continue + clarification` combinations without a tier would be locked out.
- **The value sets of `disposition` / `action` are deliberately unconstrained.** They are open business
  sets, and adding a disposition should not need a database change; code constants enforce them.
  `execution_tier` is the exception: this phase has only `agent`, so a CHECK blocks miswrites.
- **No `message_digest`.** SHA-256 is not anonymisation: customer-service messages are highly
  enumerable ("refund", "check order", "转人工"), and a dictionary recovers them. Only
  `message_length` is stored.
- **No reserved columns.** `task_relation` / `escalate_from` / `decision_type` / `stage_ids` /
  `confidence` / `profile_ref` are all omitted: their semantics are unsettled, and creating columns
  early lets an unproven abstraction hold later phases hostage.
- **Retention** follows the observability-table approach (see `memory_injection_log_retention_days`);
  the cleanup job is not implemented in this phase.

## Core flow

### 1. `send()` becomes "decide, record, execute"

```python
async with transaction(self.engine, connection) as c:
    await execute(c, "SELECT pg_advisory_xact_lock(71432019)")   # lock order unchanged: admission lock first
    conv = required(await one(c, "SELECT ... FOR UPDATE", ...))  # conversation lock second
    request_id = uuid4()

    decision = await decide_ingress(c, self, conv, message, request_id)
    await self._record_decision(c, conv, decision)               # SAVEPOINT isolation
    return await self._apply_decision(c, conv, decision, message)
```

The `decide_ingress` decision sequence:

| # | Check | IO |
|---|---|---|
| 1 | `conv["mode"] == "closed"` → `reject/conversation_closed` | none |
| 2 | Human-request rule hit → `handoff/user_requested_human` | none |
| 3 | `mode in {"human","waiting"}` → `defer` | none |
| 4 | Blacklist flag → `handoff/blacklist_flag` | Fetch `agent_snapshot` + `active_flags` (**same position as today**, still after the first three steps) |
| 5 | No agent and `model_backend == "unconfigured"` → `reject/model_not_configured` | Reuses the snapshot fetched in step 4, no extra query |
| 6 | Everything else → `continue/agent/submit_agent_run/default_agent` | none |

**Key constraint**: today `agent_snapshot` is queried only after the first three branches are passed
(`service.py` lines 164-166). Keep that position, otherwise the query count and lock hold time for
ordinary messages change. `model_not_configured` moves from "raise when submitting the Run" to step 5
of the decision sequence, and **adds no query**.

### 2. `_apply_decision` dispatches on `action` (not on `reason_code`)

```python
if decision.action == "reject":
    # same as today: no message write, no Run. The current closed branch raises straight away, with no add_message
    return {"conversation_id": cid, "run": None, "rejected": decision.reason_code}
if decision.action == "request_handoff":
    await add_message(c, cid, "user", message)
    handoff = await self.handoffs.request(...)
    return {"conversation_id": cid, "run": None, "handoff": handoff}
if decision.action == "defer":
    await add_message(...); await execute(... history update ...)
    return {"conversation_id": cid, "run": None}
if decision.action == "submit_agent_run":
    return await self._submit_run(c, conv, decision, message)
raise DomainError("routing_action_unhandled", 500)
```

**Two points about the Reject branch**:

1. **No message write.** Today `service.py:129` raises `DomainError` directly and never calls
   `add_message`; adding one here would turn "messages on a closed conversation get persisted" into a
   new side effect nobody approved (`add_message` inserts into `conversation_messages`, and a non-user
   role also creates a dispatch).
2. **No exception.** Raising would roll back the whole transaction and take the decision record with
   it. Return `{"rejected": reason_code}` instead and let the caller map it.

**The two 409s change together** (one class of defect: a permanent rejection that the channel retries):

| Original branch | After the change |
|---|---|
| `service.py:129-130` `raise DomainError("conversation_closed", 409)` | Returns `{"rejected": "conversation_closed"}` |
| `service.py:192-196` `raise DomainError("model_not_configured", 409)` | Step 5 of the decision sequence + returns `{"rejected": "model_not_configured"}` |

Caller mapping: when the messages endpoint in `platform_routes.py` receives `rejected`, it raises
`DomainError(reason, 409)`, so the external status code is unchanged.

**The channel layer needs no code change**: `_accept_envelope` in `channel/service.py` already branches
on `result["run"]`; when it is `None`, it writes a `channel_receipts` row, updates
`channels.last_activity_at`, and clears `channels.last_error_code`. The channel worker increments the
attempt from 0 to 1 before calling `send()` (`channel/service.py:758-762`). Once `send()` returns
`rejected` instead of raising, the inbound event is marked `processed` with `attempts==1` and never
reaches a second attempt. **This phase only verifies, it adds no branch.**

### 3. Decision write (`routing/repository.py`)

```python
async def record(conn, decision) -> bool:
    try:
        async with conn.begin_nested():          # SAVEPOINT: only this small section rolls back on failure
            await conn.execute(text(INSERT_SQL), {...})
        return True
    except Exception:                            # an observability failure must not backfire on the business
        logger.warning("routing decision not recorded", exc_info=True)
        return False
```

- **The business service owns the failure counter**: `CustomerService._record_decision()` first checks
  `trace_enabled`; when off it skips without counting. When on it calls `record()` and, only when the
  result is `False`, increments `self._routing_write_failures[decision.tenant_id]`. This counter is a
  **current-process, current-tenant** diagnostic: it is not aggregated across replicas and resets on
  process restart. The WARN log remains, and a cross-replica failure rate is measured by aggregating
  logs.
- **Why a SAVEPOINT is mandatory**: after a failed statement PostgreSQL puts the transaction into an
  aborted state, and even if Python catches the exception later SQL still reports
  `current transaction is aborted`, so `_apply_decision`'s message write and Run creation all fail —
  killing the main flow in exactly the scenario the write was meant to protect. `begin_nested()`
  already has precedent in this repository (`conversation/service.py:346`).
- **Boundary**: a SAVEPOINT isolates statement-level errors only. If the connection drops or the
  transaction is already invalid, rolling back to the savepoint is equally ineffective and existing
  database error handling decides the whole request fails — **"never affects the business" is not
  promised**.
- **No events**: `record()` writes the table only and publishes nothing (see "Known limitations").

### 4. Query API (`applications/customer_service/platform_routes.py`)

Customer-service business routes actually live in `platform_routes.py` (which already defines
`/conversations/{cid}`, `/conversations/{cid}/messages` and `/handoffs`) and are mounted by
`applications/customer_service/application.py` with `prefix=api_prefix` (`/api/v1`); `routes.py` has
only `/health`, `/modules` and `/deployment`.

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/conversations/{cid}/routing-decisions` | `limit` (default 50, max 200) + `before` cursor |
| `GET` | `/api/v1/routing-decisions/summary?since=&until=` | Counts aggregated by `disposition` / `reason_code`, plus `routing_write_failures` for the current process and current tenant |

- **Cursor format**: `before` is an opaque `base64("<created_at_iso>|<id>")` string; the server decodes
  it and pages by `(created_at, id) < (before_at, before_id)`. A composite cursor is mandatory,
  otherwise rows sharing a timestamp are skipped.
- `summary` validation: ISO 8601; `since < until`; maximum span 31 days; both default to the last 7
  days when omitted.
- `summary.routing_write_failures` is process-local: it covers only SAVEPOINT write failures accumulated
  by the replica handling this request during its current process lifetime. It is not aggregated
  across replicas and resets on restart; the response must preserve this boundary and must not present
  it as a global failure total.
- Both endpoints carry full scope predicates, and permissions reuse the existing `Operator` / `Reader`
  dependencies.

### 5. Index verification

The three indexes are designed around query shapes. After implementation they must be checked by
running `EXPLAIN (ANALYZE, BUFFERS)` on real SQL, focusing on whether `summary` still uses an index
under `since`/`until` range filtering plus aggregation (range plus aggregation may need a
`(tenant,business,workspace,created_at,disposition)` order). Adjust from the results, then finalise the
migration.

## Configuration

New `business_capabilities/customer_service/routing/settings.py` (business config does not go into
Core Settings):

```python
class RoutingRule(BaseModel):
    id: str                                   # stable id, e.g. en_human_request_001
    locale: str                               # zh-CN / zh-TW / en / hi
    phrases: list[str]

class CustomerServiceRoutingSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGENT_CS_ROUTING_", extra="ignore")

    trace_enabled: bool = False
    handoff_rules: list[RoutingRule] = [
        RoutingRule(id="zh_human_request_001", locale="zh-CN",
                    phrases=["转人工", "人工客服", "客服"]),
        RoutingRule(id="zhtw_human_request_001", locale="zh-TW", phrases=["轉人工"]),
        RoutingRule(id="en_human_request_001", locale="en",
                    phrases=["human", "real person", "representative", "human agent"]),
        RoutingRule(id="hi_human_request_001", locale="hi", phrases=["मानव", "एजेंट"]),
    ]

    @model_validator(mode="after")
    def validate_rule_identity(self):
        # Rule ids and normalised phrases must both be globally unique.
        ...
        return self
```

- **Rules carry an explicit id**: `matched_rule_id` must not be derived from "locale + list index",
  otherwise reordering the word list makes historical records point at the wrong rule.
- **Stable rule identity**: `RoutingRule.id` and the normalised phrase are a stable contract shared by
  Phase 1 and Phase 2. Reordering rules or phrases must not change the `matched_rule_id` for an
  existing phrase. New semantics require a new id or an explicit migration; an old id must never be
  reused for a different rule.
- **Global uniqueness validation**: a Pydantic model validator (or equivalent) must reject duplicate
  ids and duplicate normalised phrases. For example, configuring both `" HUMAN "` and `"human"` across
  two rules is invalid.
- **Locale is not a matching input**: `locale` is rule provenance and operational metadata only. This
  phase matches the union of all rules, locale-agnostically; it does not filter by channel language
  and does not put locale into `matched_rule_id`.
- **Injection point**: inject the instance where `applications/platform_runtime/platform_services.py`
  constructs `CustomerService`, not as a module-level global.
- Environment variables: `AGENT_CS_ROUTING_TRACE_ENABLED`, `AGENT_CS_ROUTING_HANDOFF_RULES` (JSON).
- **Fallback on failure**: when parsing or validator validation fails, fall back to the default rules
  and log a WARN; a configuration error must never turn a normal message into a handoff.
- **Default off**: `trace_enabled` defaults to `false`. After deployment, explicitly set it to `true` in
  a designated canary environment and observe for 7 days. This is environment/process-level
  canarying, not tenant-level override. The switch controls recording only and does not roll back the
  FR-3/FR-4 behaviour changes.
- **Known limitation**: the existing `CapabilityConfigService` is platform-level (shared by the
  process, no tenant override), so this phase **does not promise tenant-level overrides** and offers
  environment-variable configuration only.

## Rule semantics (explicit boundaries, no overclaiming)

This phase implements **configurable deterministic keyword rules**, not multilingual human-handoff
intent recognition:

1. **Normalisation**: trim, case-fold, and convert full-width to half-width.
2. **Matching**: the whole message must **equal** a rule phrase (exact match); **arbitrary substring
   containment is forbidden**, otherwise `your agent platform is slow` would be misjudged as a handoff.
3. **Punctuation**: a single trailing punctuation mark is stripped before comparison (`human.` matches
   `human`).
4. **Locale-agnostic union**: matching iterates all rules and `locale` does not participate in
   filtering. `客服`, `轉人工`, `human`, and `मानव` are matched from the same union regardless of
   channel language.
5. **Traceable hits**: `matched_rule_id` is written, so tuning the word list does not require logs.
6. **Stable rule identity**: explicit ids and normalised phrases are globally unique; reordering rules
   or phrases cannot change the `matched_rule_id` for an existing phrase.
7. **Known recall gap**: in-sentence phrasing such as `I want to speak to a human` does not match. A
   **deliberate trade-off** (exact matching first, to avoid false positives); better recall belongs to
   the Phase 2 rule upgrade, and this phase adds no NLP classifier.
8. **A bare `agent` is explicitly unsupported**: the default uses `human agent` to avoid
   false-positive matches. Other near-synonyms are not in the default list; use `real person` for the
   default human-request phrase.

## Known limitations and follow-ups

| # | Item | Handling |
|---|---|---|
| L1 | **This phase publishes no events.** Nothing consumes `routing.decision_created`; publishing it needs the decision id filled in, a way to tell where the two call paths really commit (when a channel passes an external connection, `transaction()` does not commit), and would amplify L2 below | Add once a consumer exists and delivery semantics are clear; evaluate an Outbox then |
| L2 | **The event bus has an existing scope defect**: `events.py::_ensure_task` reads `payload.get("business_id")` from the wrapper dict, but the field actually lives inside `event.payload`, so it falls back to the default `customer-service/default` | An existing problem unrelated to this phase; logged for fixing, not blocking |
| L3 | **Decision coverage is not unconditionally 100%**: when the SAVEPOINT fails the request succeeds without a record; other error paths after the decision still roll back with the transaction | Metric becomes "100% when the database is healthy"; keep the WARN and expose `routing_summary.routing_write_failures` for the current process and current tenant. This counter is not aggregated across replicas and resets on restart; measure the cross-replica rate by aggregating logs |
| L4 | Retention / cleanup job not implemented | Follow up with `memory_injection_log_retention_days` as the reference |

## Model call path

This phase **involves no model**: every decision is a deterministic rule, there is no
`model_gateway` call and no token consumption.

## Test approach

| Layer | Cases |
|---|---|
| Unit | Decision sequence maps one-to-one onto the current branches; normalisation and exact-match boundaries (trailing punctuation, full-width, case); zh-CN / zh-TW / en / hi default rules; locale-agnostic union; bare `agent` and non-default near-synonyms do not match; stable id/phrase identity; duplicate ids and duplicate normalised phrases rejected by the validator; invalid configuration falls back to defaults; nothing written when the switch is off |
| Integration | The six branches behave consistently with their decision records; **both 409s return `rejected` with the decision persisted**; the main flow still succeeds after an injected SAVEPOINT failure and the summary failure counter increments; an outer rollback rolls the decision back too; cursor pagination and aggregation; tenant isolation |
| Channel | Both 409 messages are `processed` on their first attempt with `attempts==1` and no second attempt; `channel_receipts` has a receipt, `channels.last_activity_at` is updated, and `last_error_code` is empty (verification only; no channel code change) |
| Regression | Existing customer-service and runtime suites all green; the HTTP status codes of the two 409s are unchanged; existing human-handoff and channel-inbound cases do not regress |

## Rollout and rollback

- **Migration**: creates a table and indexes only, runs online; existing data needs no backfill.
- **Default off**: `trace_enabled` defaults to `false`; `AGENT_CS_ROUTING_TRACE_ENABLED=false` means no
  decision writes. **Note**: the rule extension and the return contract of the two 409s **do not roll
  back with the switch** (they are intended behaviour changes).
- **Rollback**: to return to fully old behaviour the code must be rolled back; the migration
  `downgrade` only runs `DROP TABLE routing_decisions`.
- **Canary**: after migration and verification, explicitly set `AGENT_CS_ROUTING_TRACE_ENABLED=true`
  in a designated canary environment/process, observe for 7 days, and use `summary` to confirm the
  `disposition` / `reason_code` distributions match expectations. Then widen the rollout and decide
  whether Phase 2 starts. This phase has no tenant-level switch, so the canary must not be described
  as per-tenant rollout.
