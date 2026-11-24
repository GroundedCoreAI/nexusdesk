# Phase 1 · UI-managed model egress hosts — Test Plan

> Status: to be executed after implementation
> Created: 2026-11-24
> Basis: `02-requirements.md` (FR-1..FR-10, AC-1..AC-8), `03-technical-design.md`

## 1. Scope and Principles

**Scope**: migration, host validation/store, effective allowlist, management API,
console page, inline allow action, i18n copy.

**Principles**:

1. **Switch-off parity**: with `AGENT_MODEL_GATEWAY_UI_ALLOWED_HOSTS=false`, every
   existing gateway test and behaviour is unchanged.
2. **Empty-state parity**: an empty `gateway_allowed_hosts` table changes nothing.
3. **Fail closed**: invalid/private/unresolved hosts, missing tenant scope and
   disabled management never fall back to allow.
4. **No blocking DNS in async paths**: resolution runs through a worker thread and
   is not called on env-only hosts.
5. **No performance/CI gates**: exit criteria are functional correctness, switch
   completeness, tenant isolation, secret-free audit, data integrity, migration
   and no P0/P1.

## 2. Environment

| Environment | Use |
|---|---|
| Unit | Pure host normalization/resolution logic with fake resolvers |
| Postgres integration | Store CRUD, tenant isolation, audit, cache invalidation |
| Frontend typecheck/i18n/build | Console page and four-locale copy |

## 3. Unit Tests

| ID | Case | Expected | Trace |
|---|---|---|---|
| P1-UT-01 | Normalize `www.duckcoding.ai` | Returns same lowercase host | FR-4 |
| P1-UT-02 | Normalize `https://www.duckcoding.ai/v1` | Returns `www.duckcoding.ai` | FR-4 |
| P1-UT-03 | Reject `http://`, userinfo, query, fragment, wildcard, path-only | `model_host_invalid` | FR-4 |
| P1-UT-04 | Reject `127.0.0.1`, `::1`, `localhost`, single-label, metadata name | `model_host_not_public` | FR-4 |
| P1-UT-05 | Resolver returns a private/reserved address | `model_host_not_public` | FR-4 |
| P1-UT-06 | Resolver returns no address | `model_host_unresolved` | FR-4 |
| P1-UT-07 | Switch off: `effective()` is empty; add/remove raise disabled | `model_host_management_disabled` | FR-9/FR-10 |
| P1-UT-08 | Cache TTL expiry triggers one reload; write invalidates immediately | Store reload count matches | FR-10 |

## 4. Integration Tests

| ID | Case | Expected | Trace |
|---|---|---|---|
| P1-IT-01 | Admin adds a public host, then saves a channel using it | 201, channel 200, probe available | AC-2 |
| P1-IT-02 | Non-admin calls list/add/delete | 403, nothing persisted | AC-5 |
| P1-IT-03 | Tenant A and B | Each sees only its own managed rows; B cannot use A's host | AC-6 |
| P1-IT-04 | Remove a host used by a channel | Channel save/probe returns `model_address_not_allowed`; audit row exists | AC-4 |
| P1-IT-05 | Env list contains `api.openai.com`, managed list empty | Still allowed with the switch on and off | AC-7 |
| P1-IT-06 | Add duplicate host | Idempotent or `model_host_exists`; exactly one row | FR-2 |
| P1-IT-07 | Disabled switch with pre-existing rows | Rows are not effective; mutations refused | AC-1 |
| P1-IT-08 | Audit content | Tenant, actor, host only; no secret fields | FR-8 |

## 5. Common Checks

| ID | Check | Pass criteria |
|---|---|---|
| P1-CM-01 | Migration online | `upgrade head` on an existing DB succeeds; `downgrade -1` drops only the new table |
| P1-CM-02 | Default configuration | `model_gateway_ui_allowed_hosts` is `false`; env override works |
| P1-CM-03 | Audit/observability | Add/remove audit rows; no secret or token logged |
| P1-CM-04 | Tenant isolation | Cross-tenant read/write impossible through API and catalogue |
| P1-CM-05 | Secret scan | No key material in table, audit or responses |

## 6. Regression Scope

- `backend/tests/test_model_gateway.py`
- `backend/tests/test_codex_model_gateway_route.py`
- `backend/tests/test_model_discovery.py`
- `backend/tests/test_gateway_governance.py`
- `frontend` `npm run typecheck`, `npm run check:i18n`, `npm run build`

The empty table and default-off switch must leave these suites unchanged.

## 7. Defect Levels and Exit Criteria

| Level | Definition | Handling |
|---|---|---|
| P0 | Broken main flow, data loss, cross-tenant leak | Fix and regress |
| P1 | Wrong allow/deny decision, switch ineffective | Fix before acceptance |
| P2 | UX/policy deviation | Record owner and deadline |
| P3 | Copy/log issue | Schedule |

**Exit**: all UT/IT/CM pass, AC scenarios reproduced in an integration
environment, regression green, switch-off diff zero, no open P0/P1.
