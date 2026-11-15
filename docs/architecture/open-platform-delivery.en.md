# Open Platform as the Unified External Delivery Layer: Delivery Plan

> Status: Phase 0 and Phase 1 (backend + public contract + frontend binding entry) implemented and verified; Phase 2 onward not started
> Goal: upgrade the open platform from an "Agent API gateway" into an "external delivery control plane" — onboard Service Applications first, then gradually fold every external access path into it.

---

## 1. Positioning and Target State

### 1.1 One-sentence positioning

**Every external entry point is authorized, rate limited, and audited through an open platform application object; the execution unit can be an Agent, or a Service Application (the preferred option).**

### 1.2 Three-layer structure

| Layer | Carrier | Responsibility |
|---|---|---|
| Delivery layer | `open_platform` (`open_applications`) | One credential set, one set of access channels, one quota and audit trail |
| Execution layer | `service_apps` / `agent_runtime` | Service Application (skills, connections, rules, greeting, knowledge, handoff) or a bare Agent |
| Channel layer | `channels` | Enterprise messaging channels (WeCom / Feishu / DingTalk / Slack / Telegram …) |

### 1.3 Core relationships

```
open_application (1) ──binds──> (1) execution subject
                                   ├── service_application (recommended, full orchestration)
                                   └── agent (legacy, bare execution unit)
open_application (1) ──enables──> (N) access methods
                                   ├── Hosted Web
                                   ├── Embed
                                   ├── API / SDK
                                   ├── messaging channel
                                   └── Playground
```

**Key constraint: one open platform application binds exactly one execution subject and may enable multiple access methods.** This is how "application-centric" lands in the data model.

---

## 2. Current State Inventory

### 2.1 Already available (no rewrite needed)

| Capability | Location | Notes |
|---|---|---|
| Application keys | `open_api_keys` (`opk_`) | Hashed at rest, prefix display, expiry, rotation with overlap window, max 10 |
| Rate limiting / concurrency | `open_rate_windows`, `max_concurrency` | Per-minute window plus active run counting |
| Idempotency | `open_runs.idempotency_key + payload_hash` | Same key with same payload returns the original run; different payload returns 409 |
| SSE stream | `stream_response()` | `accepted / model.delta / tool.* / run.*`, supports `Last-Event-ID` resumption, public stream already filters retrieval snippets and tool inputs |
| Request audit | `open_request_logs` | Route, status code, duration, error code, run_id, request_id |
| Webhook callbacks | `open_webhooks` / `open_deliveries` | Signed delivery, retries, delivery records |
| Knowledge sync | `open_sync_tasks` / `open_synced_documents` | External document create/update/delete plus publish tasks |
| Enterprise identity | `enterprise_providers` / `enterprise_sessions` | OIDC / WeCom / Feishu / DingTalk, `chat_` session tokens, embed domain allowlist |
| Embed config | `open_embed_configs` | Domain allowlist, title, theme color, login provider |
| Embed frontend | `features/open-platform/EmbedChat.tsx` | postMessage handshake, SSO token exchange, streaming rendering |
| Channels | `channels` + `/api/v1/ingress/channels/{id}/*` | 8 provider types, version foreign-key pinning, inbound dedupe, receipts |
| Application session path | `service_apps/sessions.py` | `open_session` / `send_message` are **already parameterized** (`kind` / `source` / `context_override` / `allow_unpublished`) |

### 2.2 Gaps (what this plan closes)

| Gap | Impact |
|---|---|
| `open_applications` can only authorize Agents | Service Applications cannot be delivered; the open platform cannot use the skills, connections, rules, or knowledge configured inside an application |
| No public conversation entry point inside the platform | Hosted Web does not exist at all |
| Embed only supports Agents | The embedded window runs a bare Agent, not the customer service application the customer configured |
| Channels are a sibling page in the UI, not attributed to an application | "What entry points does this application expose?" cannot be answered in one place |
| Application `status='offline'` has no effect | Channels keep running after the application goes offline (confirmed in the previous round) |
| Ledger has no source field | Cannot distinguish "sent from the backend experience" from "sent by an open platform customer" |

---

## 3. Data Model

### 3.1 New: delivery subject binding

```sql
-- Proposed addition
CREATE TABLE open_application_targets (
  app_id       uuid NOT NULL REFERENCES open_applications(id) ON DELETE CASCADE,
  target_kind  text NOT NULL CHECK (target_kind IN ('agent','service_application')),
  target_id    uuid NOT NULL,
  version_pin  integer,          -- NULL = follow the latest release
  created_at   timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (app_id, target_kind, target_id)
);

-- An application may bind only one Service Application
CREATE UNIQUE INDEX open_targets_single_application
  ON open_application_targets(app_id) WHERE target_kind = 'service_application';
```

**Why not reshape `agent_ids`:**

- `agent_ids uuid[] + agent_versions jsonb` is the old paradigm for "one key accesses multiple Agents"; semantically it is an **authorization list**;
- A Service Application carries full orchestration and is semantically a **delivery subject**, naturally unique;
- The new table separates the two semantics explicitly; adding workflow / agent-team later only requires extending the `target_kind` enum.

**Migration compatibility:** where existing `agent_ids` is non-empty, write rows with `target_kind='agent'` (one row per agent) during migration; the legacy path is preserved and "create application" in the frontend offers the two options.

### 3.2 Relaxed constraints

```sql
-- Proposed change
runtime_conversations_source_check  → add 'open_platform'
open_sessions.agent_id              → DROP NOT NULL (no agent in application mode)
```

**What we deliberately do not do:**

- Do not add columns to `service_application_conversations`. The source is written into the existing `metadata`
  (`{"source":"open_platform","open_app_id":"..."}`), and statistics keep using `kind='customer'`, because open platform
  conversations are real customer conversations and belong in the workspace.
- Do not change the `kind` enum (`customer` / `debug` stay as they are).

### 3.3 Conversation namespaces

| Entry point | external_conversation_id | Constraint |
|---|---|---|
| Backend experience | `app:{key}:{session_digest}` | Platform login session |
| Debug | `debug:{session_key}` | `kind='debug'` |
| Channels | Provided by the channel | `channel_id` not null |
| **Open platform** | `open:{open_app_id}:{digest(external_user, external_session)}` | `kind='customer'`, `source='open_platform'` |

The existing `open_sessions` already carries the `(app_id, external_user_id, external_session_id)` uniqueness semantics, so it can be reused directly; only conversation creation is delegated to `service_apps.sessions.open_session()`.

---

## 4. Execution Path

### 4.1 Current (Agent mode)

```
POST /openapi/v1/conversations/{cid}/messages
  → open_platform.submit()
  → snapshot = platform.snapshot + agents.snapshot(version_pin)
  → repository.submit(RunRequest)          # submit straight to the runtime
  → INSERT open_runs
```

### 4.2 Target (Service Application mode)

```
POST /openapi/v1/conversations/{cid}/messages
  → open_platform.submit()
  → resolve target_kind == 'service_application'
  → service_apps.sessions.send_message(
        tenant, application_key, conversation_id,
        content,
        actor="open_platform",
        idempotency_key=<Idempotency-Key>,
        external_user_id=<X-External-User-ID>,
        kind="customer",
    )
  → reuse: routing decision → admission → queue → worker → ledger → events
  → INSERT open_runs (linked to run_id)
```

**This is the crux of the whole plan: skills, connections, business rules, knowledge base, handoff, ledger, reply events — all reused with zero rewriting.**
`open_session` / `send_message` were parameterized for the debug path in the previous round; this round only reuses the same switches.

### 4.3 Version pinning

- `version_pin` is NULL: each new conversation takes the current `published_version`, while existing conversations keep their original version (`resolve()` already records the version per turn)
- `version_pin` has a value: `allow_unpublished=False`, `resolve(application_id, version_pin)`
- When the application publishes a new version, the open platform **does not follow automatically** (the external behavioral contract must stay stable); the UI surfaces "a new version is available"

### 4.4 Three identity layers (must not be mixed)

| Identity | Carrier | Purpose |
|---|---|---|
| Visitor | `X-External-User-ID` or a `chat_` session token | Who is talking |
| Accessing application | `Bearer opk_` | Which system is calling and whose quota is consumed |
| Execution identity | `connections` credentials inside the application snapshot | With what permissions the Agent calls enterprise tools |

Long-lived keys only ever appear server-side; Embed / Hosted Web always use short-lived `chat_` tokens, and those tokens are only usable on conversation paths under `openapi/v1` (the existing `chat_scope_required` check already enforces this).

---

## 5. Mapping the Five Access Methods

| # | Access method | Current state | Gap | Plan | Priority |
|---|---|---|---|---|---|
| 1 | **Hosted Web** | None | Everything | New public page plus public conversation API (see 5.1) | P0 |
| 2 | **Embed** | `EmbedChat.tsx` + `open_embed_configs` + SSO | Agents only | Add `target` to the config, `/sso/embed/{app}` returns application info, frontend hides the Agent selector | P1 |
| 3 | **API / SDK** | Full `/openapi/v1` | Agents only | Make `agent_id` optional on `/conversations`; when absent, route by the bound subject | **P0** |
| 4 | **Messaging channels** | `channels` + ingress | Not attributed to an application | Add a "Channels" tab to open platform details, reusing `ChannelsPage` filtered to this application | P1 |
| 5 | **Playground** | Application "customer interaction" debug + open platform debug | Two separate entry points | For application mode, the open platform debug tab reuses the `preview` path | P1 |

### 5.1 Minimal Hosted Web implementation

- Route: `/a/{public_slug}` (`open_applications` gains `public_slug`, plus optional `public_access` enum: `anonymous` / `login` / `disabled`)
- Frontend: a new page reusing `EmbedChat`'s streaming render logic, dropping the postMessage handshake in favor of a direct token exchange:
  - `anonymous` → the server issues an anonymous `chat_` token (TTL-limited, scoped to that app)
  - `login` → reuse the existing OIDC / WeCom / Feishu login
- Backend: `GET /api/v1/public/apps/{slug}` (display config) + `POST /api/v1/public/apps/{slug}/token`
- Conversation: the external user ID is a browser-persisted uuid (localStorage), behaving like the debug session's `session_key`

### 5.2 Embed extension points

The current `EmbedChat` flow is: parent page postMessages a token → `/openapi/v1/agents` → user picks an Agent → `/conversations`.
In application mode it becomes: parent page hands over a token → straight into the conversation (no Agent selector), with greeting and title coming from the application snapshot plus embed config.

Appearance ownership: **title and theme color come from `open_embed_configs`; greeting, business rules, and skills come from the Service Application snapshot** — the two do not overlap.

---

## 6. Phased Rollout

### Phase 0: Foundation (data model) — done

| Item | Detail |
|---|---|
| Migration | `0065_open_platform_targets`: create `open_application_targets` + backfill existing agents (all 10 applications backfilled); add `open_platform` to `runtime_conversations.source`; relax `open_sessions.agent_id` |
| Service | `service.py` gains `target()` / `delivery()` (including version pinning); `check()` gains a "target availability" check (application published / not offline / not archived, fail closed) |
| Acceptance | Existing Agent application behavior unchanged (`test_open_platform.py` 6 passed); migration round trip `downgrade -1` + `upgrade head` passes |

### Phase 1: Open platform onboards applications (P0, core) — backend done

| Item | Detail |
|---|---|
| Backend | `submit()` branches to `service_apps.sessions.send_message`; `create_session` branches to `open_session` (`release_version` pinning + `metadata` source marker); `agent_id` becomes optional in `create_conversation` |
| Contract | `POST /conversations` routes by the bound subject when `agent_id` is omitted; `GET /openapi/v1/targets` returns the delivery subject and version; `GET /open-platform/service-applications`, `.../versions` for the admin console |
| Frontend | **Done**: create/edit application becomes "optionally bind a service application + version pinning"; binding auto-links the Agent (the authorization list becomes read-only); list cards and config page show the delivery subject and version; integration doc examples adapt to the subject (application mode omits `agent_id`); online debug hides the Agent selector in application mode; integration config hides Agent version fixing in application mode |
| Acceptance | Real HTTP end-to-end 13/13 passing (`backend/scripts/e2e_open_platform_delivery.py`): `opk_` key → `/targets` → create conversation (`agent_id` is null) → send message → SSE `run.completed` → ledger `kind=customer` with `metadata.source=open_platform` → visible in the backend workspace → records present in `open_runs` / `open_request_logs` |

### Phase 2: Unified delivery detail page (P0)

| Item | Detail |
|---|---|
| Frontend | Add a "delivery methods" overview card at the top of application details: Web / Embed / API / channels / Playground, each with enablement state and a quick config link |
| Backend | New `GET /open-platform/applications/{id}/delivery` aggregate: bound subject, enabled channels, key count, last-7-day conversations / success rate / average response time |
| Acceptance | An administrator can see on one page which entry points an application exposes and how to enable them |

### Phase 3: Hosted Web + Embed extension (P1)

| Item | Detail |
|---|---|
| Backend | `public_slug` / `public_access`; public config and token issuance endpoints; embed supports application mode |
| Frontend | `/a/{slug}` public page; embed hides the Agent selector in application mode |
| Acceptance | An anonymous visitor can hold a conversation by opening the public link; embedding works on allowlisted domains and returns 403 on others |

### Phase 4: Channel attribution (P1)

| Item | Detail |
|---|---|
| Frontend | "Channels" tab on open platform details, filtering `ChannelsPage` by `application_id` |
| Backend | On channel create/version switch, verify whether the owning application is bound as a delivery subject (warn but do not block) |
| Acceptance | Channels can be created and inbound records viewed directly from application details |

### Phase 5: Governance convergence (P2)

| Item | Detail |
|---|---|
| Version consistency | Warn when "the version pinned by the open platform ≠ the application's latest published version", plus one-click upgrade |
| Offline linkage | When an application is `offline`, its open platform application is automatically set to `disabled` and new conversations are rejected (**fix the ineffective `offline` first**) |
| Unified quota | Channel inbound traffic also counts toward `open_rate_windows` (optional, per-provider limiting) |
| Unified audit | Channel inbound, Web, and Embed traffic all flow into `open_request_logs` (distinguished by `route`) |

---

## 7. Decisions to Confirm

| # | Decision | Recommendation |
|---|---|---|
| 1 | Can one open platform application bind multiple execution subjects? | **No.** Multiple subjects defeat the purpose of "one credential set"; if you need several, create several open platform applications |
| 2 | Should versions be pinned or follow by default? | **Pinned by default**, with a "follow latest" toggle in the UI; external contract stability takes precedence |
| 3 | Default access control for Hosted Web? | **`login` by default**; anonymous access must be enabled explicitly (so public links are not crawled) |
| 4 | Keep the legacy multi-authorization Agent mode? | **Keep but mark as legacy**; new applications no longer offer multi-select |
| 5 | Must channels go through the open platform? | **Not mandatory.** Channels keep connecting directly to applications; the open platform only provides a unified view, avoiding changes to the stable ingress path |
| 6 | Do open platform conversations appear in the workspace? | **Yes.** They are real customer conversations, unlike backend experience or debug sessions |

---

## 8. Risks and Pitfalls

| Risk | Explanation | Mitigation |
|---|---|---|
| Offline has no effect | Neither `resolve()` nor channel ingress checks `status`; onboarding the open platform amplifies this | Bring forward from Phase 5: reject `status='offline'` in `open_session`, replay historical conversations through a separate branch |
| Dual-track versions | Application release version, open platform `version_pin`, and channel `application_version` are independent | Document all three semantics in one place; surface inconsistencies in the UI |
| Conversation namespace collision | Open platform `open:{app_id}:{digest}` and backend experience `app:{key}:{digest}` have different origins, so the same customer has two conversations | Accept it (different entry points, different identities) and state it in the docs |
| Public stream leaks internal data | `stream_response` already filters retrieval snippets and tool inputs, but application mode emits more `tool.*` events | Reuse the same filter; do not fork by mode |
| Inconsistent idempotency semantics | `open_runs` uses `payload_hash`, `send_message` uses `_turn_by_idempotency_key` | The open platform layer performs idempotency first (same key returns the original run); the lower layer only acts as a backstop |
| Ledger source not filterable | The source lives in `metadata`, so SQL filtering needs `metadata->>'source'` | Add a generated column plus index later if reporting requires it |

---

## 9. Explicitly Out of Scope

- No fifth runtime or a separate API gateway process
- No rewriting of channel adapters (the 8 provider types already work)
- No splitting "Web publishing / API publishing / Embed publishing" into three separate admin modules
- No long-lived `opk_` keys in browsers or frontend SDKs

---

## 10. Suggested Execution Order

```
Phase 0 (model) → Phase 1 (API onboards applications) ★ core value
                → Phase 2 (delivery detail page: make entry points visible)
                → Phase 3 (Hosted Web / Embed)
                → Phase 4 (channel attribution)
                → Phase 5 (governance convergence)
```

Once Phase 1 lands, the product narrative holds: **"create an application → publish → bind and issue keys in the open platform → external systems call the same skills and knowledge."**
Each later phase merely adds another card to the same delivery detail page.

---

## 11. Implementation Record (Phases 0 / 1)

### 11.1 Changed files

| Layer | File | Notes |
|---|---|---|
| Migration | `backend/migrations/versions/0065_open_platform_targets.py` | Binding table + partial unique index + backfill + relaxed `source` CHECK + nullable `open_sessions.agent_id` |
| Migration | `backend/migrations/versions/0064_application_debug_sessions.py` | Debug session source (prerequisite) |
| Sessions | `service_apps/sessions.py` | `open_session` supports `release_version` / `metadata`; `_application` supports `allow_offline`; `send_message` allows offline applications for existing conversations |
| Runtime | `conversation/service.py` | Adds `open_platform` to the valid `source` values |
| Service | `open_platform/service.py` | Binding validation, `targets()` / `target()` / `delivery()` / `describe()`, dual branches for `create_session` / `submit`, `session()` ownership check by `application_id` |
| Contract | `open_platform/routes.py` | Application details return the resolved `target` (name/key/version/pinned); list items carry `target`; new `GET /open-platform/service-applications(+ /versions)`; new `GET /openapi/v1/targets`; `agent_id` optional on conversations |
| Frontend | `frontend/src/features/open-platform/*` | Editor binds a service application (optional) + auto-linked Agent, delivery display on config page and list cards, integration doc and online debug adapt to the subject, four-language strings kept in sync |
| Tests | `backend/tests/test_open_platform_delivery.py` | 3 cases: binding rules, real customer path, version pinning and offline gate |
| Verification | `backend/scripts/e2e_open_platform_delivery.py` | Real-socket HTTP end-to-end script (separate tenant, does not affect the dev environment) |

### 11.2 Key semantics (implementation is the contract)

- **Binding uniqueness**: there is a partial unique index on `target_kind='service_application'`, so one open platform application binds exactly one service application; after binding, `agent_ids` is **derived automatically** from the Agent wrapped by the service application (used for display and the `/openapi/v1/agents` list), while runtime routing only honors the delivery target and public conversation creation still rejects `agent_id` (`agent_id_not_applicable` 422).
- **Version pinning**: `version_pin IS NULL` follows the current `published_version`; a value pins it. The `pinned` field on `/targets` indicates whether it is pinned.
- **Offline fail closed**: when the application is `archived` / `offline` / unpublished, `/targets`, `/conversations`, and `/sessions` all return 409 instead of silently falling back to the Agent path; follow-up messages on existing conversations are still allowed (`allow_offline`).
- **Traceable source**: `runtime_conversations.source='open_platform'`, and the ledger's `service_application_conversations.metadata` records `source` / `open_app_id` / `runtime_conversation_id`; `kind` remains `customer`, so these conversations appear in the workspace and in application conversation records.

### 11.3 How to re-run

```bash
cd backend
export TEST_DATABASE_URL='postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/agent_platform_test'
.venv/Scripts/python.exe -m pytest tests/test_open_platform.py tests/test_open_platform_delivery.py -q
.venv/Scripts/python.exe scripts/e2e_open_platform_delivery.py
```

The E2E script writes data under a dedicated `test-e2e-*` tenant and does not clean up afterwards (it targets the test database); to re-inspect, query `runtime_conversations` / `service_application_conversations` / `open_runs` by tenant.

### 11.4 Known gaps

1. The delivery detail page does not yet aggregate the "Web / Embed / API / channels / Playground" overview — that is Phase 2.
2. There is no operational view on the open platform application side for "what happens to old conversations after switching the delivery subject"; today a `session_target_conflict` 409 forces a new conversation.
3. The demo model never issues real skill calls, so E2E can only verify "same path + ledger + source"; skill invocation needs a real model or a mock business to be verified once more.
