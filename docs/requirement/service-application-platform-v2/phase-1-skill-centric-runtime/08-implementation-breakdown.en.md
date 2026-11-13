# Phase 1 · Skill-Centric Application Runtime - Implementation Breakdown

> Status: Core tasks implemented; targeted tests, migration and static gates pass; full CI, empty-volume quickstart and manual UAT remain pending
> Created: 2026-11-11
> Basis: all planning documents [01](01-business-goals.en.md)-[05](05-acceptance-plan.en.md) plus current-code review
> Constraints: clean-break; no legacy data migration or compatibility layer; development data may be reset; backend/frontend/migration ship together

## 1. Task breakdown

Critical path: **migration -> v2 contracts -> connections/skills -> releases -> application runtime -> channels/conversations -> APIs -> legacy removal -> frontend -> tests/deployment**.

T3/T4 can run in parallel after T2. T8/T9 can start after T5 but merge in order. T14/T15 can run in parallel after T12/T13 interfaces stabilize.

| # | Task | Files (new/modified) | Depends on | Trace |
|---|---|---|---|---|
| T1 | Add `0058_service_application_v2`: remove legacy scenario/Provider/industry tables; recreate app v2, skills, connections, credentials, versions and traces; extend channels/inbound/conversations | `backend/migrations/versions/0058_service_application_v2.py` (new) | - | FR-1/2/3/4/6/9/10/15, AC-1/4/6/11 |
| T2 | Rewrite application contracts: Application, Skill, Connection, RuleConfig, v2 version snapshot; reject v1 fields | `.../service_apps/models.py` | T1 | FR-1-FR-6, AC-1/2/4/5 |
| T3 | Connection service: CRUD, same-app references, HttpTool validation, EgressPolicy tests, Vault credential rotation | `.../service_apps/connections.py` (new) | T1/T2 | FR-3/FR-4, AC-2/12 |
| T4 | Skill service: CRUD, argument/result mappings, safety, same-app connection constraint, action-write rules | `.../service_apps/skills.py` (new) | T1/T2 | FR-2/FR-5, AC-1/2/3 |
| T5 | Release service: readiness, canonical snapshot, digest, version history, diff and append-only rollback | `.../service_apps/releases.py` (new) | T2/T3/T4 | FR-6/FR-7, AC-4/5 |
| T6 | Application service refactor: CRUD, pagination, Agent binding, example immutability, versions, archive/restore | `.../service_apps/service.py` | T2/T5 | FR-1/FR-12/FR-14, AC-1/9 |
| T7 | Examples/templates: consolidate code templates into app v2; reserved `example-` key; idempotent seed, copy and lineage | `.../service_apps/seed.py` (modified) | T2/T6 | FR-11, AC-7/8/11 |
| T8 | Application runtime resolver: application version -> Agent version -> skill/connection/builtin allow-list; trace metadata | `.../service_apps/runtime.py` (new) | T5 | FR-8/FR-10, AC-2/3/6 |
| T9 | Run injection: `CustomerService._submit_run` adds application context; `RuntimeFactory` uses only app connections/authorized skills | `.../customer_service/service.py`, `applications/platform_runtime/runtime_factory.py` | T8 | FR-8, AC-3/4 |
| T10 | Channel changes: `ChannelInput.application_id/version`; channel CRUD/version switch; pinned inbound outbox | `.../channel/service.py`, `applications/customer_service/platform_routes.py` | T6/T8 | FR-9, AC-4/6 |
| T11 | Conversations/traces: write app/version; application traces; retain derived Agent fields | `.../conversation/service.py`, `applications/platform_runtime/platform_services.py` | T9/T10 | FR-10, AC-6/12 |
| T12 | Application v2 APIs: app/skill/connection/test/publish/rollback/copy/pagination/trace; remove old router registration | `.../service_apps/routes.py`, `applications/customer_service/application.py` | T3-T11 | FR-12/13/15, AC-9/10 |
| T13 | Backend clean-break: delete Provider/Scenario/ToolBridge/Industry Installation/Upgrade wiring and modules; retain template compilation | `applications/platform_runtime/platform_services.py`, `service_groups.py`, `customer_service/{providers,scenarios,industry_packs}/**` | T9/T12 | FR-15, AC-10 |
| T14 | Frontend APIs/types: remove Provider/Scenario/Upgrade; add app v2, skill, connection, version, pagination types/client | `frontend/src/shared/api/client.ts` | T12 | FR-1/2/3/6/12, AC-1/4/9 |
| T15 | Application catalog split: standard examples/my apps filters, read-only examples, copy, default 10 pagination | `frontend/src/features/service-apps/catalog/**`, `ServiceAppsPage.tsx` | T14 | FR-11/12, AC-7/9 |
| T16 | Application detail: six tabs; overview/Agent components; draft/live state | `features/service-apps/detail/**` | T14/T15 | FR-13, AC-1/4/9 |
| T17 | Skill/connection UI: AntD Table/Drawer, pagination, schema/mappings, safety, tests, no credential echo | `features/service-apps/skills/**`, `connections/**` | T14/T16 | FR-2/3/4/5/13, AC-2/9/12 |
| T18 | Rules/debug/channel-release UI: fallback/handoff, draft-preview write gate, channel version switch, readiness/history/rollback | `features/service-apps/rules/**`, `debug/**`, `release/**` | T12/T14 | FR-5/6/7/9/13, AC-4/5/6/9 |
| T19 | Frontend clean-break: delete `service-scenarios`, industry page, `/service-apps/industry`, old navigation/styles/tests | `frontend/src/features/service-scenarios/**`, `IndustryCapabilitiesPage.tsx`, `app/App.tsx` | T15-T18 | FR-15, AC-9/10 |
| T20 | i18n/visual: application, skill, connection, rules, version and error copy in Chinese/English; bottom-aligned pagination | `frontend/src/i18n/**`, `features/service-apps/**/*.css` | T15-T19 | FR-12/13, AC-9 |
| T21 | Backend tests: contracts, connections/credentials, skills/rules, release/rollback, runtime isolation, channels, examples, migration | `backend/tests/test_service_application_v2_*.py` | T1-T13 | 04 UT/IT |
| T22 | Frontend tests: catalog pagination, six tabs, Table/Drawer, read-only examples, old routes absent, Chinese/English | `frontend/tests/service-app-v2*.spec.ts` | T14-T20 | 04 IT/CM |
| T23 | Configuration/deployment/docs: settings, seed startup, empty quickstart, CI, doc backfill and superseded-topic status | `settings.py`, `applications/**/main.py`, `deploy/**`, `docs/**` | T1-T22 | 03 configuration/deployment, AC-10/11 |

## 2. Merge units and gates

### 2.1 Unit 1: data and application contracts

T1 + T2.

Gate:

- Empty database migration succeeds.
- v1 configuration is rejected.
- Application requires Agent/version.
- Skill/connection/credential tables have same-application foreign keys and unique constraints.

### 2.2 Unit 2: configuration and releases

T3 + T4 + T5 + T6 + T7.

Gate:

- Two applications can store same-named skills with different connections.
- Credential APIs never echo secrets.
- Readiness blocks missing Agent/connection/credential.
- Publish/rollback only append versions.
- Seed/copy tests pass.

### 2.3 Unit 3: runtime and channels

T8 + T9 + T10 + T11.

Gate:

- One Agent referenced by A/B gets isolated tool sets.
- Channel inbound outbox pins application version.
- Conversation/run/trace are traceable.
- Global Tool Gateway is no longer implicit customer-application authorization.

### 2.4 Unit 4: APIs and clean-break

T12 + T13.

Gate:

- New APIs green.
- Legacy APIs absent from router table.
- Provider/Scenario/IndustryPack wiring no longer starts.
- Template content can still produce examples.

### 2.5 Unit 5: frontend

T14-T20.

Gate:

- Five primary-concept UI.
- Default page size 10, AntD native pagination and bottom alignment.
- Examples read-only/copyable.
- `service-scenarios` and `/service-apps/industry` absent.
- Chinese/English, typecheck, build and E2E green.

### 2.6 Unit 6: verification and delivery

T21-T23.

Gate:

- 04 exit criteria met.
- Empty quickstart starts once.
- CI, deployment notes, docs index and superseded-topic notice complete.

## 3. Document-versus-reality decisions

### R1 Migration head and new revision

The docs require a v2 migration. Reality: current head is `0057_industry_pack_runtime`, with historical `0054`-`0057` already present and immutable. **Decision**: add `0058_service_application_v2.py`, `down_revision="0057_industry_pack_runtime"`, and perform the breaking cleanup there.

### R2 Provider is not an application connection

Target is `service_application_connections`. Reality: `service_provider_registry` is tenant/business/workspace scoped, has no `application_id`, and stores descriptor/config rather than a real execution connection. **Decision**: do not extend the Provider table; add application connection/credential tables and delete Provider Registry/routes.

### R3 Credentials live in Tool Gateway

Docs require Vault ciphertext. Reality: `HttpTool.credential_id` points to `tool_credentials`, with `RegisteredTool`/Tool Workspace handling inheritance. **Decision**: application connections use a dedicated credential table and `CredentialVault`; releases retain only `credential_ref`; no global `tool_credentials` in application release snapshots.

### R4 Channels currently bind Agent

Docs require application-version binding. Reality: `ChannelInput.agent_id`, `channels.agent_id`, and ingress calls `conversations.create(..., current["agent_id"])`. **Decision**: `channels` stores `application_id/application_version` and drops agent; `channel_inbound_events` stores the same pinned version; `runtime_conversations.agent_id/version` remain only as derived query denormalization.

### R5 RuntimeFactory currently uses Agent global tool snapshot

Docs require application skill isolation. Reality: `RuntimeFactory.for_run` builds every HTTP ToolGateway from `snapshot["agent"]["tools"]`. **Decision**: when `snapshot["application"]` exists, build tools only from application connections; do not implicitly inject Agent custom global tools. Agent built-ins still intersect release authorization.

### R6 Actual frontend page sizes

Earlier discussion said `ServiceAppsPage.tsx` exceeded 3,000 lines. Actual measurement is 2,384; `IndustryCapabilitiesPage.tsx` is 1,021. **Decision**: use measured values; route orchestration <= 300 lines and independent business tabs <= 800. Backfill the revision note in `03`.

### R7 Legacy tests cover many Provider/Scenario paths

Reality: backend has `test_service_scenario_*`, `test_scenario_tool_bridge*`, `test_industry_pack_*`; frontend has `service-scenarios.spec.ts` and `industry-capabilities.spec.ts`. **Decision**: delete tests for removed concepts and add v2 tests. Do not keep the old runtime by merely changing assertions.

### R8 Industry templates are coupled to installation lifecycle

Reality: `industry_packs/compiler.py` compiles Scenario/Capability and `installations.py` manages installation/upgrade/merge. **Decision**: retain the useful template content and deterministic compilation ideas in `service_apps/seed.py` to produce v2 examples; delete installations/upgrades/merge and `/industry-packs` routes.

### R9 Executed Alembic migrations are immutable

Clean-break conflicts with migration rules. **Decision**: do not modify `0054`-`0057`; `0058` drops/recreates legacy tables. The migration is not a legacy-data upgrade; the database is reset before general availability.

### R10 `agent_id` is still used by conversations/memory/statistics

Reality: conversation lists, Agent deletion checks and memory summary/extraction rely on `runtime_conversations.agent_id`. **Decision**: retain `agent_id/agent_version` as derived columns from the application release. Remove "channels bind Agent directly" semantics without dropping every column; historical-run diagnostics are read-only.

### R11 Application list is currently unpaginated

Reality: `ServiceApplicationService.list` returns all items/total and the frontend renders directly. **Decision**: v2 list uses server page/page_size, default 10; frontend uses AntD native pagination and bottom alignment.

### R12 Existing industry installation creates applications at startup

Reality: industry pack installation/seed may create `service_applications` and retain installation state. **Decision**: `0058` deletes installation state and old applications; new seed uses reserved `example-` keys to create immutable examples with `ON CONFLICT DO NOTHING` and never updates.

### R13 Current publish requires at least one scenario

Reality: `_resolve_for_publish` fails with `service_application_scenario_required` when no enabled scenario exists. **Decision**: v2 publishing requires direct Agent binding and valid skills, not a scenario. Knowledge-only applications may have zero query/action skills but still require an Agent and release policy.

### R14 Current readiness depends on ScenarioService/Provider

Reality: `ServiceApplicationService` takes `ScenarioService` and `ServiceProviderRegistry`, and readiness collects scenario/provider identities. **Decision**: v2 readiness checks application skills/connections/credentials/Agent. Complete T3-T5 before deleting dependencies to avoid import breakage.

### R15 Removing industry entry does not remove template content

Reality: template content is deeply coupled to Provider requirements and scenario compilation. **Decision**: delete `/service-apps/industry` and standalone industry navigation; retain a Standard Examples origin filter in the application catalog. Template code only generates examples and creates no runtime special branch.

### R16 Channel inbound outbox has no application fields

Reality: `channel_inbound_events` links only `channel_id`; worker reads the current channel later. **Decision**: write `application_id/application_version` at enqueue and let the worker use the event-pinned version rather than overwrite it with current channel binding.

### R17 v1 version table structure is insufficient

Reality: `service_application_versions` has only `config/source_version`, without `schema_version/config_digest`. **Decision**: recreate on clean-break with `schema_version/config_digest`; migrate no old version rows.

### R18 Examples need a reserved key namespace

Reality: application keys are globally unique; a future user key could conflict with seed. **Decision**: examples use reserved `example-` prefix; create/copy APIs reject new user keys with that prefix. `0058` recreates tables, so no old user key conflict exists.

### R19 Examples cannot embed real credentials

Reality: connection credentials are Vault-encrypted and tenant/resource-bound, so code templates cannot carry real tenant ciphertext. **Decision**: templates contain mock/demo or unauthenticated connections. User copies requiring real auth must configure credentials; non-secret connection config may be copied with `credentials_configured=false`.

### R20 Removing legacy APIs requires composition and tests

Reality: legacy routers are registered in `applications/customer_service/application.py` and services assembled in `PlatformServices`. **Decision**: T13 removes router registration, service fields, `ServiceGroups` fields, imports and tests together. Deleting only router files would break startup/tests.

### R21 Customer applications must be distinguished from platform-internal tools

Reality: the global Tool Gateway catalog has legitimate admin/debug uses. **Decision**: keep Tool Gateway itself; only forbid implicit authorization in customer application runtime. Platform-internal tools may remain, but must not appear in unapproved application skill lists.

### R22 Configuration module path differs from the design

Reality: `backend/src/agent_platform/settings.py` does not exist. The actual centralized settings entry point is `backend/src/agent_platform/core_platform/platform_services/platform_settings/settings.py`. **Decision**: use the actual path, revise the change summary and configuration section in 03, and add new settings only to that module rather than creating a parallel settings file for the migration.

## 4. Handoff

### 4.1 Engineering

- Follow merge units strictly; merge T1/T2 first and do not change runtime before T3-T7.
- After each unit, check FRs against 03 paths.
- Log new mismatches as R-n and backfill 03 before coding around them.
- Do not modify migrations 0054-0057; legacy table cleanup belongs only to 0058.
- Every connection execution goes through EgressPolicy/Vault; temporary plaintext credentials or policy bypasses are forbidden.

### 4.2 QA

- Execute all 04 cases, not just a single-app happy path.
- The key dataset must include A/B same-named skills, one Agent with two apps, draft edits after publish, and channel rollback after ingress.
- Judge clean-break through router tables/source search/404, not UI hiding.
- Test both empty and `0057` pre-release databases and confirm data loss is expected, not accidental.

### 4.3 Product and acceptance

- Accept against 05 A1-A12 and C1-C7.
- UAT focuses on completing "copy example -> configure connection -> preview -> publish -> bind channel" without engineering explanation, not on visual polish alone.
- Any design that still requires users to understand scenarios/Provider/upgrade history means concept convergence has failed.
