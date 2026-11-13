# Phase 1 · Skill-Centric Application Runtime - Test Plan

> Status: Targeted tests executed and passing; unrelated repository-wide regression was intentionally not run at the user's request, while full CI, empty-volume quickstart and manual UAT remain pending. Evidence: [06-test-report.en.md](06-test-report.en.md)
> Created: 2026-11-11
> Basis: [02-requirements.md](02-requirements.en.md) (FR-1-FR-15, AC-1-AC-12), [03-technical-design.md](03-technical-design.en.md)

This document remains the complete test baseline. The current delivery only executed unit, integration, migration, frontend-gate and E2E cases directly related to the service-application v2 changes; all cases in this document must not be treated as executed or passing.

## 1. Test scope and principles

**Scope**:

- Application v2 contracts, skills, connections, credentials, rules, release, rollback, pagination and traces.
- Application-scoped runtime resolution, same-Agent multi-application isolation and global-tool bypass closure.
- Application-version pinning for channels, inbound events and conversations.
- Standard-example seed, immutability, copying and restart idempotency.
- `0058` breaking migration, fresh-database initialization and legacy-table cleanup.
- Frontend catalog, detail tabs, skills Table/Drawer, read-only examples and legacy-route removal.
- Removal of legacy Provider/Scenario/Industry Upgrade code, APIs, types and tests.

**Principles**:

1. **Application isolation is mandatory**: testing one application working is insufficient; construct two applications with same-named skills/different connections and one Agent used by both.
2. **Release boundary is mandatory**: no draft edit may affect a channel bound to a published version.
3. **Version pinning is mandatory**: inbound outbox, conversation and run retain the version at ingress.
4. **No plaintext secrets is mandatory**: inspect APIs, database query results, release JSON, traces, audit and logs.
5. **Clean-break is mandatory**: legacy routes/APIs/modules/types are absent; 301 or compatibility behavior is a failure.
6. **No time/network waiting**: construct timeout, retry and lease states by direct DB update or clock mock; external connections use a local mock server.
7. **Only the new migration chain is tested**: historical migrations are not edited; run `0058` against both an empty database and a `0057` sample.

## 2. Environment and data construction

| Environment | Purpose |
|---|---|
| Unit tests (no DB) | Pydantic contracts, digest, pure readiness, mappings/safety and pagination parameters |
| PostgreSQL integration fixture | Applications/skills/connections/versions, channels, outbox, conversations, audit and migrations |
| Local mock HTTP server | Connection tests, same-named skills with different endpoints, auth headers and response validation |
| Demo/mock model | Agent runs with programmable tool calls, with no external model dependency |
| Frontend Vitest/Playwright + mock API | Catalog pagination, tabs, Table/Drawer, read-only examples and legacy-page removal |

**Data construction conventions**:

- Applications A/B share a tenant, business and workspace to prove application-level isolation.
- One published Agent version is available to both A and B.
- `order_lookup` exists in both A and B, points to `/a/orders` and `/b/orders`, and returns distinguishable results.
- After publishing, edit the draft by API or DB and assert old version JSON/digest are unchanged.
- Channel ingress tests call webhook/enqueue and then manually claim the worker; assert outbox stores the pinned version.
- Example tests prepare one example and one modified user copy, then run seed again.

## 3. Unit tests

| ID | Case | Expected | Trace |
|---|---|---|---|
| P1-UT-01 | Parse v1 config with `scenarios/capabilities` | v2 contract rejects with clear field errors | FR-1/FR-15, AC-9/AC-10 |
| P1-UT-02 | Create without Agent or with archived Agent | Validation fails `application_agent_required/not_found` | FR-1, AC-1 |
| P1-UT-03 | Specify a missing Agent version | Validation fails; no draft is generated | FR-1/FR-6, AC-1 |
| P1-UT-04 | Duplicate skill key in one app / same key across apps | Duplicate rejected in one app; allowed across apps | FR-2, AC-2 |
| P1-UT-05 | Use `agent` as skill type | Enum rejects | FR-2, AC-9 |
| P1-UT-06 | Action write without confirmation and no exemption | Readiness fails or save returns 422 | FR-5, AC-1 |
| P1-UT-07 | Connection endpoint contains userinfo/query/fragment | `HttpTool`-style validation rejects | FR-3, C1 |
| P1-UT-08 | Public headers include Authorization/Token | Reject and require credentials | FR-3/FR-4, C1 |
| P1-UT-09 | Read API after saving connection credentials | Only `credentials_configured=true`; no plaintext/ciphertext | FR-4, AC-12/C1 |
| P1-UT-10 | Serialize credential payload into a release snapshot | Snapshot contains only `credential_ref` and digest | FR-4/FR-6, C1 |
| P1-UT-11 | Compute digest with different JSON key order | Digest is identical | FR-6, AC-4 |
| P1-UT-12 | Missing credential/deleted connection readiness | Publishing blocked with explicit check | FR-6, AC-4 |
| P1-UT-13 | Reference another application's connection id | Skill save rejected | FR-2/FR-3, AC-2 |
| P1-UT-14 | Agent tools include a global custom tool without app skill | Runtime allow-list excludes global custom tool | FR-8, AC-3 |
| P1-UT-15 | Agent tools include built-ins allowed by app rules | Keep only builtin ∩ application authorization | FR-8, AC-3 |
| P1-UT-16 | Same skill key maps to A/B connections | Resolver returns the correct endpoint by application_id | FR-8, AC-2/AC-3 |
| P1-UT-17 | Direct edit/delete of an example | Handler rejects `example_immutable` | FR-11, AC-7 |
| P1-UT-18 | Copy an example | New app has `origin=user/immutable=false`, lineage retained | FR-11, AC-7 |
| P1-UT-19 | Default/max/invalid application pagination | Default 10, maximum 100, invalid rejected | FR-12, AC-9 |
| P1-UT-20 | Rollback creates a new version | `source_version=target`; old versions unchanged | FR-7, AC-5 |
| P1-UT-21 | Rule evaluation error in `on_error`/timeout | Reject with `rule_evaluation_failed` | FR-5, C1 |
| P1-UT-22 | Amount/permission limit not met | No external call; deterministic rejection | FR-5, C1 |

## 4. Integration tests

| ID | Case | Expected | Trace |
|---|---|---|---|
| P1-IT-01 | Create app -> select Agent -> add skills/connections -> readiness -> publish | v2 snapshot generated; `published_version=1`; audit complete | FR-1/FR-6, AC-1 |
| P1-IT-02 | A/B same `order_lookup` point to different mock endpoints | A gets A data, B gets B data; editing A endpoint does not change B | FR-2/FR-3/FR-8, AC-2 |
| P1-IT-03 | One Agent bound to A/B, each runs a tool call | Each run exposes only its application skills; no global tool | FR-8, AC-3 |
| P1-IT-04 | Edit A draft skill/connection after publish, then run through channel | Run keeps old version; trace version unchanged; UI flag says unpublished | FR-6/FR-9, AC-4 |
| P1-IT-05 | Republish A and explicitly switch channel version | New messages use new version; old inbound events keep ingress version | FR-7/FR-9, AC-4/AC-6 |
| P1-IT-06 | Roll back to v1 | Create v3 (source=v1), published=v3; v1/v2 unchanged | FR-7, AC-5 |
| P1-IT-07 | Channel webhook ingress -> outbox -> worker | Channel/event/conversation/run all record same app/version | FR-9/FR-10, AC-6 |
| P1-IT-08 | Roll back after ingress but before processing | Outbox still runs ingress version; later events use new binding | FR-9/FR-10, AC-5/AC-6 |
| P1-IT-09 | Switch channel to unpublished/missing version | 409/422; original binding unchanged | FR-9, AC-6 |
| P1-IT-10 | First seed + second startup | Examples exist once; user copy is not updated | FR-11, AC-8 |
| P1-IT-11 | Copy example and edit copy | Copy editable; example content/digest unchanged | FR-11, AC-7 |
| P1-IT-12 | Access `/service-providers`, `/service-scenarios`, industry upgrade APIs | FastAPI route table absent and 404; no compatibility handler | FR-15, AC-10 |
| P1-IT-13 | Empty DB -> `0058` -> seed -> publish -> receive channel message | Succeeds once; no manual DDL | Migration/FR-11, AC-11 |
| P1-IT-14 | Run `0058` on a `0057` pre-release database | Legacy service tables removed; new tables/columns exist; no conversion error; expected data loss recorded | Migration, AC-11 |
| P1-IT-15 | Save/rotate credentials, publish, run, inspect trace/audit | No plaintext in responses/database audit; ciphertext used correctly | FR-4/FR-10, AC-12 |
| P1-IT-16 | Cross-tenant/business/workspace access to apps, skills, connections | All return 404 and cannot borrow another workspace resource | FR-14, C2 |
| P1-IT-17 | `GET /service-apps?page=1&page_size=10` | Returns page/page_size/total; stable ordering and 10-item limit | FR-12, AC-9 |
| P1-IT-18 | Trace a skill/connection call | Contains app/version, agent/version, skill, connection, latency/result code; sensitive values redacted | FR-10, AC-6/AC-12 |

## 5. Common checks

| ID | Check | Pass standard |
|---|---|---|
| P1-CM-01 | Migration linearity | Empty and `0057` samples reach head; historical migrations unmodified |
| P1-CM-02 | Configuration loading | Example seed, timeout, page size, preview write and key-file defaults/override correct |
| P1-CM-03 | Frontend gates | `npm run typecheck`, `npm run check:i18n`, `npm run build` all pass |
| P1-CM-04 | Backend static checks | `uv run ruff check src tests` passes; relevant pytest green |
| P1-CM-05 | Legacy residue scan | No target Provider/Scenario/ToolBridge/industry-upgrade residue in `src/`, `frontend/src/`, router registration or client types |
| P1-CM-06 | Secret scan | No plaintext token/key/password in release JSON, API fixtures, logs, audit, traces or git diff |
| P1-CM-07 | Authorization | Reader cannot write; Admin can publish; cross-scope invisible; 403/404 correct |
| P1-CM-08 | i18n | All new user copy exists in Chinese and English, including examples, skills, connections, rules and release/rollback |
| P1-CM-09 | Pagination UI | Ant Design native pagination; default 10; bottom alignment; total/page/change work |
| P1-CM-10 | Document consistency | Chinese/English pairs exist; traceability IDs resolve; 03 paths/migration number match implementation |
| P1-CM-11 | Audit | Key actions are audited without secrets; failed publish leaves a locateable error |
| P1-CM-12 | Quickstart | Empty volume migrates/seeds once; restart idempotent; health checks pass |

## 6. Regression scope

- Agent draft, publish, version snapshot and archive.
- Conversation creation, message/run submission and SSE.
- Channel Provider catalog, generic webhook, inbound outbox and delivery worker.
- Knowledge retrieval, memory tools, tickets/human handoff and approval.
- RBAC, identity, audit, runs and observability.
- Frontend application navigation, Agent management, conversation workbench, channels page and full i18n/typecheck/build.
- Removing legacy Scenario/Provider/Industry composition must not break imports during application assembly.

Regression principle: historical runs without application context must not appear on customer channels. If internal diagnostics need replay, use a read-only/test path; do not restore customer-traffic compatibility.

## 7. Defect levels and exit criteria

| Level | Definition | Handling |
|---|---|---|
| P0 Blocker | Cross-tenant/application skill or credential leak; channel bypasses application version; mutable release; unexpected data destruction | Stop work, fix and full regression |
| P1 Critical | Same-named skill calls wrong connection; example editable/seed overwrite; rollback ineffective; migration failure; plaintext secret | No acceptance before fix |
| P2 Normal | Pagination/empty state/copy/local trace defects that do not break main flow | May accept with owner/deadline |
| P3 Minor | Style detail or non-critical log | Schedule fix |

**Exit criteria**:

- All P1-UT/IT/CM cases pass, including new E2E cases.
- Both empty quickstart and `0057 -> 0058` breaking migration pass.
- Three main scenarios run consecutively: two apps with same-named skills, one Agent across apps, pinned channel ingress.
- Legacy route/API/type cleanup result is 0.
- No open P0/P1 and no plaintext credential residue.
- Regression suite green and CI result recorded.
