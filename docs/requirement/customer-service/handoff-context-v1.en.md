# Human workbench business context (H2 slice)

> Status: backend, frontend and live-data verification are all in place
> Created: 2026-11-02
> Related:
> - [Human workbench V1](./human-workbench-v1.md)
> - [Customer service implementation roadmap](./implementation-roadmap-v1.md)
> - [Industry Pack runtime](./industry-pack-runtime-v1.md)

## 0. What this slice fixes

The V1 workbench could only show the handoff summary, recent messages, pending
actions and recent runs. An operator could not see which order the customer was
talking about, what the system looked up, or what the customer confirmed.

This slice delivers two things:

1. **Scenario traces can be bound to a real conversation**, instead of existing
   only as isolated records produced by the simulator.
2. **A handoff context aggregation endpoint**, `GET /api/v1/handoffs/{id}/context`,
   which returns scenario, object, facts, decisions and execution evidence in one
   response while keeping permission trimming and masking on the server.

## 1. Binding traces to conversations

### 1.1 Data layer

`service_scenario_traces` gains a nullable `conversation_id` column:

- Foreign key to `runtime_conversations(id)` with `ON DELETE SET NULL`.
- Index `(tenant_id, business_id, workspace_id, conversation_id, created_at DESC)`.
- Migration: `backend/migrations/versions/0056_scenario_trace_conversation.py`.

Nullability is deliberate: simulator evidence is not bound to a conversation, and
existing rows need no backfill.

### 1.2 Write path

`SimulationRequest` accepts an optional `conversation_id`:

```json
POST /api/v1/service-scenarios/simulate?scenario_key=query-orders
{
  "message": "I want a refund",
  "conversation_id": "2f1c...",
  "object": {"id": "SO-1", "type": "order", "status": "shipped", "facts": {"status": "shipped"}}
}
```

Before writing, the conversation is verified inside the same transaction against
the caller's tenant and business scope. A mismatch returns
`404 conversation_not_found`, so a cross-tenant trace can never be written.

Application-level simulation, `POST /api/v1/service-apps/{key}/simulate`, passes
the same field through.

## 2. Aggregation endpoint

```text
GET /api/v1/handoffs/{id}/context
```

### 2.1 Response shape

| Field | Source | Notes |
|---|---|---|
| `handoff` | `handoffs` | Status, assignee, reason, summary, revision |
| `conversation` | `runtime_conversations` | Mode, source, external id, `has_customer` boolean |
| `application` | `trace.application` of the latest trace | Application snapshot written by application-level simulation |
| `scenario` | Latest bound trace | Scenario key, name, version, handler capability, outcome |
| `object` | Trace `object_ref` | Only `type / id / status` |
| `facts` | Trace `facts` | Already filtered for the operator view |
| `decisions` | Trace `decisions` | `selected` maps to selected, everything else to pending |
| `actions` | `pending_actions` | Projects only `title/description`, plus `valid` |
| `runs` | `runtime_runs` | Latest 10 statuses and failure codes |
| `routing` | `routing_decisions` | Handoff reason, disposition and execution tier |
| `traces` | `service_scenario_traces` | Latest 10 trace summaries |

### 2.2 Permissions and masking

1. The handoff row is read with tenant plus business scope; anything outside that
   scope returns `404 handoff_not_found`.
2. Every follow-up query carries the same scope predicate. Nothing is stitched
   together on the client.
3. Facts are filtered by `audiences`: only entries listing `human` or `agent`
   survive, so customer-only projections never reach the operator view.
4. Implementation details such as `source`, provider names, queue names and rule
   keys stay server-side.
5. Customer identity is reduced to `has_customer`; `customer_id` is never echoed.
6. Masking follows the `masked` flag produced when facts are projected, so the
   response only carries `masked: true` together with the already-masked value.

### 2.3 Empty-state semantics

Without a bound trace:

- `scenario`, `application` and `object` are `null`.
- `facts`, `decisions` and `traces` are empty arrays.
- `routing` is an empty array: a conversation created through the internal API has
  no ingress decision, and the aggregator must not invent a reason.

The frontend renders "automatic service has not bound a scenario trace yet" rather
than fabricated success data.

## 3. Frontend

`HandoffPage` gains an "automatic service" section:

- Service scenario, scenario version, business object (type · identifier).
- Business facts, including a masked marker.
- User decisions (selected / pending).
- Empty state, load failure and retry.

Eight new messages, synchronised across four locales (`check:i18n` passes with
1866 entries).

## 4. Tests

`backend/tests/test_handoff_context.py` (6 cases, all passing):

1. With no trace the context is honestly empty while runs stay visible.
2. With a bound trace the scenario, object, facts and decisions are restored, and
   customer-only facts plus provider names do not leak.
3. A trace bound to another conversation does not appear in this context.
4. An unknown handoff returns `404 handoff_not_found`.
5. A read-only role can read the context but cannot claim the handoff.
6. A conversation outside the tenant cannot receive a trace
   (`404 conversation_not_found`).

Live verification (local 8000, `admin / nexusdesk`, scenario `track-logistics`):

```text
POST /api/v1/conversations                        → 201
POST /api/v1/service-scenarios/simulate           → 200, echoes conversation_id
POST /api/v1/conversations/{id}/handoffs          → 200
GET  /api/v1/handoffs/{id}/context                → 200
      scenario: track-logistics v1 / query / succeeded / query_executed
      object:   order · SO-E2E-…
      facts:    5 entries, amount returns *99.0 with masked=true
      decisions: select_order / confirm_object / choose_intent all pending
      traces 1 · routing 0 · runs 1 · actions 0
POST /handoffs/{id}/transition claim → close      → 200 / 200
```

`application` being `null` is expected here: the probe used the scenario
simulation entry, not application-level simulation, so there is no application
snapshot to restore.

## 5. What is still missing

1. **Runtime does not write traces yet.** Only the simulation entry writes one. A
   real conversation routed into a scenario should record a `simulation=false`
   trace; that is the key next step.
2. The scenario version is not frozen when the conversation is created, so it can
   only be inferred from the latest trace.
3. Handoffs from real channel ingress are still uncovered: this verification used
   a conversation created through the platform API, so `routing` stayed empty. A
   full WeCom/Feishu ingress, scenario execution and handoff path is still needed.
4. Fact refresh policy (`refresh`) is not applied to the operator view; only the
   trace snapshot is returned.

## 6. Alignment with the Industry Pack runtime

`alpha / beta / ga` maturity and provider-capability checks are now part of
readiness:

- `alpha` scenarios must be blocked from release.
- `beta` scenarios pass only when the application has a `canary` channel.
- `ga` scenarios participate in the normal release checks.
- Pack scenarios are blocked when required objects, tools or human queues are
  missing.

The scenario-level publish endpoint also blocks `alpha` directly with:

```text
scenario_alpha_publish_forbidden
```

This slice does not reimplement human-workbench context. The workbench still needs
real-channel handoff verification for trace writes, frozen scenario versions,
fact refresh and permission masking.
