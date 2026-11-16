# Phase 1 · Skill-Centric Application Runtime - Requirements

> Status: Requirements baseline implemented and targeted validation complete; full acceptance remains pending
> Created: 2026-11-11
> Basis: [01-business-goals.md](01-business-goals.en.md) (G1-G6)

## User stories

**US-1 (Application administrator)**: As an application administrator, I want to create a service application by directly selecting an Agent and version so I no longer need to understand scenario/capability layers.

**US-2 (Application administrator)**: As an application administrator, I want to configure skills and connections inside an application so same-named skills such as order lookup can use different URLs and credentials across applications.

**US-3 (Application administrator)**: As an application administrator, I want human confirmation, amount/permission, idempotency, timeout and fallback rules on a skill so high-impact writes are not left to model discretion.

**US-4 (Application administrator)**: As an application administrator, I want publish, rollback and version diffs so production behavior is stable and traceable.

**US-5 (Channel administrator)**: As a channel administrator, I want to bind a customer channel to a published application version so draft changes cannot accidentally affect live customers.

**US-6 (Operator)**: As an operator, I want to copy an editable application from a standard example so I can start quickly without dirtying the example.

**US-7 (Support supervisor)**: As a support supervisor, I want to trace a conversation to its application, Agent, skill and connection so I can troubleshoot and audit it.

**US-8 (Engineering/operations)**: As engineering or operations, I want to remove pre-release legacy concepts and dual-track code so the system maintains one understandable application runtime.

## Functional requirements

### FR-1 Service application structure

| Item | Description |
|---|---|
| Trigger | Create, edit or open a service application |
| Input | Name, description, type, origin, bound Agent, skills, connections, application-level rules and channels |
| Output | v2 application draft and summary; no scenarios, capabilities, Providers or execution order |
| Execution | Synchronous CRUD; saves use revision optimistic locking |
| Failure handling | Duplicate key, missing/unpublished Agent or cross-scope reference returns an explicit 4xx; no partial save |

An application binds exactly one Agent. The Agent must exist, not be archived and have a publishable version. Origin is `user` or `example`; examples are `immutable=true` and can only be previewed or copied.

### FR-2 Skill model

| Item | Description |
|---|---|
| Trigger | Add, edit, enable/disable or delete a skill |
| Input | Key, name, description, type, connection, parameter schema, argument mapping, result mapping, safety rules and failure policy |
| Output | Application-unique skill record; skill entry in the release snapshot |
| Execution | Synchronous CRUD; only the draft changes until publishing |
| Failure handling | Invalid schema, missing connection, duplicate key or cross-application connection reference is rejected |

Skill types are `knowledge`, `query`, `action` and `handoff`. `agent` is no longer a skill type; the Agent is an application-level binding. `action` must declare whether it writes; high-impact writes require human confirmation or an explicitly audited safety exemption.

### FR-3 Application connections

| Item | Description |
|---|---|
| Trigger | Configure an external HTTP service, internal action or human queue |
| Input | Key, name, executor type, endpoint, method, public headers, auth mode, timeout, response limit and configuration |
| Output | A connection owned only by that application; APIs never return plaintext credentials |
| Execution | Synchronous CRUD; connection testing may be asynchronous or a short synchronous call |
| Failure handling | Unsafe endpoint, header conflict, missing credential or failed test returns a locateable error without exposing secrets |

Connection keys are unique within an application. Applications never share an instance, credential, revision or edit permission even when endpoints match. Credentials in URLs and dynamic query/fragment values are forbidden.

### FR-4 Connection credentials

| Item | Description |
|---|---|
| Trigger | Save or rotate connection credentials |
| Input | Bearer token, API key, custom header ciphertext or reference |
| Output | Ciphertext in `service_application_connection_credentials`; response exposes only `credentials_configured=true` |
| Execution | Same transaction as connection save or a separate rotate action |
| Failure handling | Encryption failure fails the whole operation; Vault outage never degrades to plaintext; audit records status only |

Credentials may be decrypted only by the application connection resolver in that application's runtime context. Release JSON, run snapshots, traces, audit, logs and error messages never contain plaintext.

### FR-5 Business rules and safety boundaries

| Item | Description |
|---|---|
| Trigger | Before, during and after skill invocation |
| Input | `requires_confirmation`, `max_amount`, `allowed_roles`, `idempotency_key`, `timeout_seconds`, `on_error`, `result_schema`, application-level fallback/handoff configuration |
| Output | Allow, require human confirmation, reject, timeout, fallback or secondary manual handling |
| Execution | Deterministic runtime checks; the model may propose calls but cannot bypass rules |
| Failure handling | Rule evaluation failure rejects with `rule_evaluation_failed`; write idempotency conflicts do not repeat execution |

### FR-6 Release snapshot

| Item | Description |
|---|---|
| Trigger | Administrator clicks Publish |
| Input | Current draft revision, bound Agent version, skills, connection metadata, rules and channel references |
| Output | Immutable `service_application_versions.config` v2; application `published_version` update |
| Execution | One transaction; readiness first, then snapshot generation |
| Failure handling | Unpublished Agent, unconfigured connection, missing credential, invalid skill or revision conflict blocks publishing with no partial version |

The snapshot contains `schema_version="v2"`, Agent id/version, skills array, public connection metadata plus `credential_ref` and digest, and channel configuration. Releases are immutable; draft edits do not modify any published version.

### FR-7 Rollback and version history

| Item | Description |
|---|---|
| Trigger | Administrator rolls back to a historical version |
| Input | Target version and current application revision |
| Output | A new highest version generated from the target snapshot; `source_version` points to the target |
| Execution | Synchronous single transaction |
| Failure handling | Missing target version, unavailable Agent/connection or revision conflict returns 409/422; existing history is preserved |

Rollback appends history rather than modifying old versions. New messages use the new published version produced by rollback; inbound events keep the version pinned when they entered.

### FR-8 Application-scoped runtime

| Item | Description |
|---|---|
| Trigger | Before submitting an Agent run |
| Input | Application id, application version, bound Agent version, conversation and message |
| Output | Run snapshot with application context: authorized skills, connection resolver references, rules and trace metadata |
| Execution | Resolve release snapshot and Agent snapshot in the same transaction that submits the run |
| Failure handling | Unavailable application version, missing Agent version or inconsistent skill/connection rejects the run and emits an observable error |

Runtime exposes only "Agent-selected built-in tools intersected with application-authorized skills". Custom HTTP skills must not enter the customer application runtime through global `registered_tools`. When one Agent is referenced by multiple applications, each application sees a different skill/connection set.

### FR-9 Channel binding

| Item | Description |
|---|---|
| Trigger | Create a channel, switch its version or receive an inbound message |
| Input | Application id, published application version, channel provider configuration and credentials |
| Output | Channel stores the application binding; every inbound event stores application id/version |
| Execution | Channel creation is synchronous; ingress continues through outbox + worker |
| Failure handling | Unpublished application or invalid version rejects create/switch; disabled channels mark inbound work unavailable |

Channels do not bind `agent_id` directly. Publishing an application never silently changes existing channels; switching a bound version is explicit and audited.

### FR-10 Conversation and run traceability

| Item | Description |
|---|---|
| Trigger | Create a conversation, submit a run or record a trace |
| Input | Channel/application context |
| Output | `runtime_conversations.application_id/application_version`, application snapshot in `runtime_runs`, application trace |
| Execution | Same transaction as creation/submission |
| Failure handling | A new channel conversation without application context must fail and never fall back to a bare Agent |

`agent_id` may remain as a query denormalization derived from the application binding, but it is not the sole channel routing source. An application trace records at least application key/version, Agent id/version, skill key, connection key, result code and latency.

### FR-11 Standard examples

| Item | Description |
|---|---|
| Trigger | Startup seed, browsing examples or copying an example |
| Input | Code-defined application template and target application key/name |
| Output | Immutable sample application and a user-owned copy |
| Execution | Idempotent seed; copy in one transaction |
| Failure handling | Seed conflicts do not overwrite; direct edit/delete of examples returns 403; duplicate copy key returns 409 |

Examples carry `origin=example`, `template_key`, `template_version` and `immutable=true`. After copy, `origin=user`, `immutable=false`, and source lineage remains; editing the copy never changes the example.

### FR-12 Application list and pagination

| Item | Description |
|---|---|
| Trigger | Open the application catalog or standard-example list |
| Input | page, page_size, status, origin, keyword and archived flag |
| Output | `items/total/page/page_size` |
| Execution | Server-side pagination |
| Failure handling | Schema validation rejects invalid page/page_size |

Default `page_size=10`, maximum 100. Frontend pagination uses Ant Design components and is bottom-aligned with the table/list.

### FR-13 Application information architecture

Application detail has six tabs:

1. Application Overview
2. Agent
3. Skills
4. Business Rules
5. Preview & Debug
6. Customer Channels & Release

The Skills tab uses an Ant Design Table showing at least skill, type, connection, enabled state, latest test, release check and actions. The edit drawer includes basic information, connection, argument mapping, result mapping, safety rules and connection testing.

### FR-14 Permissions and audit

| Operation | Minimum permission | Example audit action |
|---|---|---|
| Read application/skill/connection metadata | Reader | Reads are authorized but not audit-logged |
| Edit application/skill/rules | Admin | `service_application.updated` |
| Save/rotate connection credentials | Admin | `service_application.connection.credential_configured` without the value |
| Publish/rollback/archive | Admin | `service_application.published/rolled_back` |
| Switch channel version | Admin | `channel.application_version_changed` |
| Copy example | Admin | `service_application.copied_from_example` |

All resources are isolated by tenant/business/workspace/application. Cross-scope IDs must appear not found.

### FR-15 Clean-break removals

New code and UI must remove:

- `/service-providers` and `/service-scenarios` APIs, router registration, services, models and tests.
- `/industry-packs/installations`, upgrade preview/apply/history APIs and UI.
- `ScenarioToolBridge`, scenario handlers and v1 application `capabilities/scenarios/default_execution_order`.
- Frontend `features/service-scenarios`, `IndustryCapabilitiesPage`, Provider/Scenario types and client functions.
- `/service-apps/industry` route with no redirect.

Historical migrations `0054`-`0057` are not edited; new breaking migration `0058` performs cleanup.

## Configuration

| Key | Level | Default | Meaning |
|---|---|---|---|
| `service_app_examples_enabled` | Global settings | `true` | Idempotently install standard examples at startup; disabling does not delete existing examples |
| `service_app_connection_timeout_seconds` | Global settings | `10` | Default timeout for new connections; skills may override within limits |
| `service_app_connection_timeout_max` | Global settings | `60` | Hard timeout ceiling |
| `service_app_default_page_size` | Global settings | `10` | Default application-list page size |
| `service_app_preview_write_enabled` | Global settings | `false` | Whether draft previews may execute write skills; default simulates and performs no external writes |
| `service_app_credential_key_file` | Global settings | Reuse existing Vault setting | Encryption key file for connection credentials; never committed |

These switches do not enable a legacy Scenario/Provider compatibility path. Clean-break leaves no dual-track switch.

## Non-functional requirements

- **Isolation**: Every query and runtime resolution includes tenant/business/workspace/application. Cross-application and cross-tenant resources appear not found.
- **Security**: Credentials are encrypted at rest; plaintext never appears in APIs, logs, audit, release JSON or traces. HTTP connections reuse fixed-endpoint validation, header validation, egress policy, response-size and timeout limits from Tool Gateway.
- **Performance**: For applications with up to 50 skills and 20 connections, publish checks and snapshot creation P95 < 1 second excluding external connection tests; runtime application-context resolution P95 < 100 ms.
- **Consistency**: Publishing, rollback, channel-version switching and inbound version pinning use transactions; revision conflicts never overwrite another editor.
- **Usability**: All user-facing copy uses i18n; tables/pagination support keyboard use, empty/loading/error states; Chinese and English stay in sync.
- **Maintainability**: The main application page is split; backend dual-track modules are removed; one file does not carry multiple lifecycles again.
- **Audit**: Publishing, rollback, credential status, channel-version switching and example copy are audited without sensitive values.
- **Deployment**: Quickstart fresh database migrates and seeds in one startup; production upgrade requires an explicit destructive reset window and forbids rolling mixed deployments.

## Acceptance criteria

| # | Scenario | Expected |
|---|---|---|
| AC-1 | Create an application and directly select an Agent release version | Application saves; detail displays bound Agent/version; no scenario/capability fields |
| AC-2 | Applications A and B each configure `order_lookup` with different URLs/credentials | Each calls its own endpoint; editing A does not affect B; logs expose no credentials |
| AC-3 | One Agent is referenced by A and B | A's conversation exposes only A-authorized skills; B exposes only B's; no global-tool bypass |
| AC-4 | Edit a draft skill/connection after publishing | Live channels keep using the published version; UI shows unpublished changes; republishing switches behavior |
| AC-5 | Roll back to a historical version | A new highest version is created with source version; new messages use the rollback version; history is unchanged |
| AC-6 | Bind a channel to a published application version and receive a message | Inbound event, conversation and run record application id/version; conversation traces to skill/connection |
| AC-7 | Browse and directly edit a standard example | Edit/delete rejected; copy produces a fully editable application; editing the copy does not affect the example |
| AC-8 | Restart quickstart after editing a copied application | Seed does not overwrite the user app; standard examples are not duplicated |
| AC-9 | Configure an application through the new UI | Only service application, Agent, skill, application connection and customer channel are primary concepts; legacy intermediates invisible |
| AC-10 | Visit legacy Provider/Scenario/Industry upgrade/`service-apps/industry` entry points | Route/API/component absent or 404; no redirect or compatibility layer |
| AC-11 | Start from an empty database through migration/seed | `0058` succeeds once; examples are seeded; an application can be created, published and receive channel messages |
| AC-12 | Audit connection, publish, rollback and channel-version changes | Audit captures actor, resource, version and status; no plaintext credential appears anywhere |
