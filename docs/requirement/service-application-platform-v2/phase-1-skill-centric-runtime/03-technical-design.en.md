# Phase 1 · Skill-Centric Application Runtime - Technical Design

> Status: Technical plan implemented, including code and migration `0058`; targeted validation passes and full CI remains pending
> Created: 2026-11-11
> Basis: [01-business-goals.md](01-business-goals.en.md), [02-requirements.md](02-requirements.en.md)
> Code review: branch `feat/customer-service-optimization`, Alembic head `0057_industry_pack_runtime`

## 1. Change overview

| Layer | Files | Change |
|---|---|---|
| Migration | `backend/migrations/versions/0058_service_application_v2.py` (new) | One-time removal of legacy scenario/Provider/industry-installation tables; recreate application v2, skills, connections, credentials and traces; extend channels, inbound events and conversations |
| Models | `backend/src/agent_platform/business_capabilities/customer_service/service_apps/models.py` | Replace Scenario/Capability v1 with Application / Skill / Connection / RuleConfig v2 |
| Application service | `.../service_apps/service.py` | Application CRUD, pagination, publish, rollback, copy and readiness; split instead of growing further |
| Skills | `.../service_apps/skills.py` (new) | Skill CRUD, schema/mapping validation, safety rules and release checks |
| Connections | `.../service_apps/connections.py` (new) | Application connection CRUD, testing, credential rotation and runtime resolution |
| Releases | `.../service_apps/releases.py` (new) | v2 snapshots, canonical digest, version diff, readiness and rollback |
| Runtime | `.../service_apps/runtime.py` (new) | `ApplicationRuntimeResolver`: application version -> Agent version -> authorized skills/connections |
| Examples and templates | `.../service_apps/seed.py` (modified) | Code-defined standard cases, immutable example seed, copying and lineage; no industry installation/upgrade lifecycle |
| APIs | `.../service_apps/routes.py` | Application, skill, connection, connection test, publish/rollback/copy and pagination APIs |
| Channels | `backend/src/agent_platform/business_capabilities/channel/service.py`, `applications/customer_service/platform_routes.py` | `ChannelInput.agent_id` -> `application_id/application_version`; pin inbound versions |
| Conversations | `backend/src/agent_platform/business_capabilities/conversation/service.py` | Write `application_id/application_version`; retain `agent_id` only as query denormalization |
| Runtime | `backend/src/agent_platform/business_capabilities/customer_service/service.py`, `applications/platform_runtime/runtime_factory.py` | Inject application context at run submission; merge Agent builtins and application skills; isolate global tools |
| Composition | `backend/src/agent_platform/applications/platform_runtime/platform_services.py`, `service_groups.py` | Remove Provider/Scenario/ToolBridge/IndustryPackService; wire application runtime and examples |
| Settings | `backend/src/agent_platform/core_platform/platform_services/platform_settings/settings.py` | Example seed, connection timeout/page size/preview write/credential keys |
| Frontend directories | `frontend/src/features/service-apps/` | Split into catalog, detail, Agent, skills, rules, debug and channels-release components |
| Frontend API | `frontend/src/shared/api/client.ts` | Remove Scenario/Provider/Industry Upgrade types/functions; add application v2, skill, connection and pagination types |
| Frontend removals | `frontend/src/features/service-scenarios/`, `IndustryCapabilitiesPage.tsx` | Delete directory/page; no `/service-apps/industry` route |
| Tests | `backend/tests/test_service_application_v2*.py`, `frontend/tests/service-app-v2*.spec.ts` | Data, release, isolation, channel, example, E2E and clean-break tests |

## 2. Current versus target

| Current | Target |
|---|---|
| `service_applications.draft` v1: `scenarios/capabilities/default_execution_order/channels` | v2: bound Agent, skills, application connections, application rules and channel references |
| Agent is `CapabilityType.AGENT` | Agent is a single application-level binding, not a skill/capability type |
| `service_provider_registry` lacks `application_id` | Connections live in `service_application_connections` and are isolated by `application_id` |
| Credentials live in `tool_credentials`, tied to global `registered_tools` | Credentials live in application connection credentials as Vault ciphertext; releases keep only a credential ref |
| `ScenarioToolBridge` reaches global tools/queues/providers | Skills resolve only through their application connection; old bridge is deleted |
| Channels/conversations bind only `agent_id` | Channels/inbound events/conversations bind `application_id/application_version`; Agent is derived from the application release |
| Industry-pack installation + upgrade preview + three-way merge | Code template -> immutable example -> user-owned copy; no installation/upgrade history |
| Application list returns all items | Server-side pagination, default 10 |
| `ServiceAppsPage.tsx` 2,384 lines, `IndustryCapabilitiesPage.tsx` 1,021 lines | Pages split; old industry page deleted |

> Revision (2026-11-11): the measured size of `ServiceAppsPage.tsx` is 2,384 lines; the earlier "over 3,000 lines" shorthand is not used.

## 3. Data model and migration

### 3.1 Migration strategy

Historical migrations `0054`-`0057` are part of the Alembic chain and must not be edited. Add:

```text
backend/migrations/versions/0058_service_application_v2.py
down_revision = "0057_industry_pack_runtime"
```

The product is not generally available, so `0058` is a **one-time breaking migration**:

- Drop `service_scenario_traces`.
- Drop `service_scenario_versions` and `service_scenarios`.
- Drop `service_provider_registry`.
- Drop `industry_pack_upgrades` and `industry_pack_installations`.
- Drop and recreate `service_application_versions` and `service_applications`.
- Create application skills, connections, connection credentials and application traces.
- Add application fields to `channels`, `channel_inbound_events` and `runtime_conversations`.

No legacy data conversion is performed. Back up development data before upgrade; there is no production data promise because the product is not live. `downgrade()` restores only old schema shells, not deleted data, and says so in the migration docstring.

### 3.2 `service_applications`

```sql
CREATE TABLE service_applications (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id TEXT NOT NULL,
  business_id TEXT NOT NULL,
  workspace_id TEXT NOT NULL,
  application_key TEXT NOT NULL,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  agent_id UUID NOT NULL REFERENCES agents(id),
  agent_version INTEGER NOT NULL CHECK (agent_version > 0),
  origin TEXT NOT NULL DEFAULT 'user'
    CHECK (origin IN ('user', 'example')),
  template_key TEXT NULL,
  template_version TEXT NULL,
  immutable BOOLEAN NOT NULL DEFAULT false,
  status TEXT NOT NULL DEFAULT 'draft'
    CHECK (status IN ('draft', 'review', 'published', 'offline')),
  draft JSONB NOT NULL,
  draft_revision INTEGER NOT NULL DEFAULT 1 CHECK (draft_revision > 0),
  published_version INTEGER NULL CHECK (published_version > 0),
  archived BOOLEAN NOT NULL DEFAULT false,
  created_by TEXT NOT NULL,
  updated_by TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, business_id, workspace_id, application_key),
  UNIQUE (tenant_id, business_id, workspace_id, id),
  CHECK (origin = 'user' OR immutable = true)
);
```

Constraints:

- `agent_id/agent_version` is the current draft binding; published behavior comes from release snapshots.
- Examples must be `immutable=true`; user applications must be `immutable=false`.
- `template_key/template_version` is lineage only and creates no upgrade relationship.
- Application updates validate `draft_revision`; Agent changes are audited.

### 3.3 `service_application_skills`

```sql
CREATE TABLE service_application_skills (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id TEXT NOT NULL,
  business_id TEXT NOT NULL,
  workspace_id TEXT NOT NULL,
  application_id UUID NOT NULL,
  skill_key TEXT NOT NULL,
  type TEXT NOT NULL CHECK (type IN ('knowledge','query','action','handoff')),
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  enabled BOOLEAN NOT NULL DEFAULT true,
  connection_id UUID NULL,
  config JSONB NOT NULL DEFAULT '{}'::jsonb,
  revision INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0),
  created_by TEXT NOT NULL,
  updated_by TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, business_id, workspace_id, application_id, skill_key),
  FOREIGN KEY (tenant_id, business_id, workspace_id, application_id)
    REFERENCES service_applications (tenant_id, business_id, workspace_id, id)
    ON DELETE CASCADE
);
```

`config` structure:

```json
{
  "parameters": {"type": "object", "additionalProperties": false, "properties": {}},
  "argument_mapping": {},
  "result_mapping": {},
  "result_schema": {},
  "safety": {
    "requires_confirmation": false,
    "max_amount": null,
    "allowed_roles": [],
    "idempotency": "none",
    "timeout_seconds": 10,
    "on_error": "fail"
  }
}
```

### 3.4 `service_application_connections`

```sql
CREATE TABLE service_application_connections (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id TEXT NOT NULL,
  business_id TEXT NOT NULL,
  workspace_id TEXT NOT NULL,
  application_id UUID NOT NULL,
  connection_key TEXT NOT NULL,
  name TEXT NOT NULL,
  executor_kind TEXT NOT NULL
    CHECK (executor_kind IN ('http','internal','human_queue')),
  endpoint TEXT NULL,
  method TEXT NOT NULL DEFAULT 'GET'
    CHECK (method IN ('GET','POST')),
  public_headers JSONB NOT NULL DEFAULT '{}'::jsonb,
  auth_kind TEXT NOT NULL DEFAULT 'none'
    CHECK (auth_kind IN ('none','bearer','api_key','custom')),
  timeout_seconds INTEGER NOT NULL DEFAULT 10
    CHECK (timeout_seconds BETWEEN 1 AND 60),
  max_response_bytes INTEGER NOT NULL DEFAULT 16000
    CHECK (max_response_bytes BETWEEN 128 AND 100000),
  config JSONB NOT NULL DEFAULT '{}'::jsonb,
  revision INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0),
  created_by TEXT NOT NULL,
  updated_by TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, business_id, workspace_id, application_id, connection_key),
  FOREIGN KEY (tenant_id, business_id, workspace_id, application_id)
    REFERENCES service_applications (tenant_id, business_id, workspace_id, id)
    ON DELETE CASCADE
);
```

HTTP connections reuse `HttpTool` validation for endpoint, headers, schema, response size and timeout. Public headers reject Authorization/Cookie/token-like values; sensitive authentication goes through the credential table.

### 3.5 `service_application_connection_credentials`

```sql
CREATE TABLE service_application_connection_credentials (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id TEXT NOT NULL,
  business_id TEXT NOT NULL,
  workspace_id TEXT NOT NULL,
  connection_id UUID NOT NULL UNIQUE,
  encrypted_secret TEXT NOT NULL,
  key_version INTEGER NOT NULL DEFAULT 1,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  FOREIGN KEY (tenant_id, business_id, workspace_id, connection_id)
    REFERENCES service_application_connections (tenant_id, business_id, workspace_id, id)
    ON DELETE CASCADE
);
```

Use `CredentialVault.encrypt(payload, tenant, connection_id, vault_spec, create=True)`. APIs return only:

```json
{"auth_kind": "bearer", "credentials_configured": true}
```

### 3.6 `service_application_versions`

```sql
CREATE TABLE service_application_versions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id TEXT NOT NULL,
  business_id TEXT NOT NULL,
  workspace_id TEXT NOT NULL,
  application_id UUID NOT NULL,
  version INTEGER NOT NULL CHECK (version > 0),
  schema_version TEXT NOT NULL CHECK (schema_version = 'v2'),
  config JSONB NOT NULL,
  config_digest TEXT NOT NULL,
  source_version INTEGER NULL CHECK (source_version > 0),
  created_by TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, business_id, workspace_id, application_id, version),
  FOREIGN KEY (tenant_id, business_id, workspace_id, application_id)
    REFERENCES service_applications (tenant_id, business_id, workspace_id, id)
    ON DELETE CASCADE
);
```

Release snapshot example:

```json
{
  "schema_version": "v2",
  "agent": {"id": "uuid", "version": 3},
  "skills": [
    {
      "key": "order_lookup",
      "type": "query",
      "connection_key": "orders-api",
      "parameters": {},
      "argument_mapping": {},
      "result_mapping": {},
      "safety": {}
    }
  ],
  "connections": [
    {
      "key": "orders-api",
      "executor_kind": "http",
      "endpoint": "https://orders.example.com/v1/orders",
      "method": "GET",
      "auth_kind": "bearer",
      "credential_ref": "uuid",
      "revision": 2,
      "digest": "sha256:..."
    }
  ],
  "rules": {"fallback": "handoff", "handoff_queue": "customer-service"},
  "channels": [{"channel_id": "uuid", "provider": "slack"}]
}
```

`credential_ref` is a server-generated reference, not plaintext; the snapshot contains no encrypted secret.

### 3.7 `service_application_traces`

```sql
CREATE TABLE service_application_traces (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id TEXT NOT NULL,
  business_id TEXT NOT NULL,
  workspace_id TEXT NOT NULL,
  application_id UUID NOT NULL,
  application_version INTEGER NOT NULL,
  conversation_id UUID NULL,
  run_id UUID NULL,
  agent_id UUID NOT NULL,
  agent_version INTEGER NOT NULL,
  trace JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

`trace` records application key/version, skill, connection, redacted argument summary, result code, latency and state. It must not record request headers, credentials or full sensitive responses.

### 3.8 Channels, inbound events and conversations

```sql
ALTER TABLE channels
  ADD COLUMN application_id UUID NOT NULL,
  ADD COLUMN application_version INTEGER NOT NULL CHECK (application_version > 0),
  DROP COLUMN agent_id;

ALTER TABLE channel_inbound_events
  ADD COLUMN application_id UUID NOT NULL,
  ADD COLUMN application_version INTEGER NOT NULL;

ALTER TABLE runtime_conversations
  ADD COLUMN application_id UUID NULL,
  ADD COLUMN application_version INTEGER NULL,
  ADD COLUMN agent_version INTEGER NULL;
```

Notes:

- A channel explicitly pins an application version; switching is a separate API/UI action.
- `channel_inbound_events` pins the version at ingress to prevent publishing/rollback during queueing from changing processing.
- New channel conversations must have application context; application conversations have non-null `application_id/version`.
- `agent_id/agent_version` remain as derived query denormalization from the application release and are not the sole channel routing source.

## 4. APIs

### 4.1 Applications

| Method | Path | Purpose |
|---|---|---|
| GET | `/service-apps?page=&page_size=&status=&origin=&q=` | Server-side pagination |
| POST | `/service-apps` | Create a user application |
| GET | `/service-apps/{key}` | Detail with helper flags |
| PUT | `/service-apps/{key}` | Update draft and revision |
| POST | `/service-apps/{key}/copy` | Copy an example into a user application |
| POST | `/service-apps/{key}/publish` | Publish v2 |
| POST | `/service-apps/{key}/rollback` | Append-only rollback |
| POST | `/service-apps/{key}/archive` / `restore` | Lifecycle |
| GET | `/service-apps/{key}/versions` | Version history |
| GET | `/service-apps/{key}/readiness` | Release checks |
| GET | `/service-apps/{key}/traces` | Paginated traces |

Handler layer returns `403 service_application_example_immutable` for example edits/deletes.

### 4.2 Skills

| Method | Path | Purpose |
|---|---|---|
| GET | `/service-apps/{key}/skills?page=&page_size=&q=` | Table data |
| POST | `/service-apps/{key}/skills` | Create |
| PUT | `/service-apps/{key}/skills/{skill_key}` | Update with revision |
| PATCH | `/service-apps/{key}/skills/{skill_key}` | Enable/disable |
| DELETE | `/service-apps/{key}/skills/{skill_key}` | Delete draft skill |
| POST | `/service-apps/{key}/skills/{skill_key}/test` | Test through draft or published connection |

### 4.3 Connections

| Method | Path | Purpose |
|---|---|---|
| GET | `/service-apps/{key}/connections` | List without secrets |
| POST | `/service-apps/{key}/connections` | Create |
| PUT | `/service-apps/{key}/connections/{connection_key}` | Update public configuration |
| PUT | `/service-apps/{key}/connections/{connection_key}/credentials` | Save/rotate ciphertext |
| POST | `/service-apps/{key}/connections/{connection_key}/test` | Connectivity test |
| DELETE | `/service-apps/{key}/connections/{connection_key}` | Delete when unreferenced |

### 4.4 Channels

`ChannelInput` becomes:

```python
class ChannelInput(NameInput):
    application_id: UUID
    application_version: int = Field(ge=1)
    provider: str = "generic_webhook"
    config: dict[str, object] = Field(default_factory=dict)
    credentials: dict[str, str] = Field(default_factory=dict)
```

Add:

```text
PUT /channels/{cid}/application-version
```

Before switching, validate that the target application version is published and channel-compatible.

## 5. Core flows

### 5.1 Create/edit an application

```text
Admin
 -> validate scope, key and non-archived Agent
 -> validate agent_version exists
 -> save v2 draft + draft_revision
 -> audit application.created/updated
```

Parent application and skill/connection children are tightly bound by `application_id + scope`; clients cannot submit a connection id from another application.

### 5.2 Save skills and connections

```text
Save connection
 -> validate endpoint/headers/auth/timeout using HttpTool rules
 -> encrypt credentials through Vault when present
 -> increment revision

Save skill
 -> if a connection is referenced, ensure it belongs to the same application
 -> validate JSON Schema, mappings and safety
 -> an action write without confirmation/exemption blocks publishing or returns 422
```

Connection tests must pass through `EgressPolicy`; arbitrary `httpx` calls that bypass the policy are forbidden.

### 5.3 Publish

```text
publish(key, revision)
 -> lock application
 -> validate draft_revision
 -> readiness:
    Agent/version resolvable
    every enabled query/action skill has a same-application connection
    credentials exist when auth requires them
    schema/mappings/safety valid
    examples cannot be published as editable applications
    channel references valid
 -> read connection revisions and credential_ref
 -> build canonical config v2 + digest
 -> INSERT version=max+1
 -> UPDATE application.published_version
 -> audit application.published
```

Publishing never changes a channel binding automatically. A channel administrator explicitly switches versions afterward.

### 5.4 Rollback

```text
rollback(key, target_version, revision)
 -> read target config
 -> validate target Agent/connection references
 -> create new highest version with source_version=target_version
 -> set published_version to the new version
 -> audit application.rolled_back
```

`published_version` is not pointed directly at the old row, keeping version audit linear and source explicit.

### 5.5 Application-scoped runtime resolution

```python
class ApplicationRuntimeResolver:
    async def resolve(
        self,
        conn,
        tenant: str,
        application_id: UUID,
        application_version: int,
        conversation_id: UUID,
    ) -> ApplicationRuntimeContext:
        release = await self.releases.get(...)
        agent_snapshot = await self.agents.snapshot(
            tenant, release["agent"]["id"], conn, release["agent"]["version"]
        )
        skills = [s for s in release["skills"] if s["enabled"]]
        connections = {
            c["key"]: c for c in release["connections"]
            if c["key"] in {s["connection_key"] for s in skills}
        }
        builtin_tools = intersect(
            agent_snapshot["config"]["tool_names"], PLATFORM_BUILTINS
        )
        return ApplicationRuntimeContext(
            application_id=application_id,
            application_version=application_version,
            agent_snapshot=agent_snapshot,
            skills=skills,
            connections=connections,
            builtin_tools=builtin_tools,
        )
```

`CustomerService._submit_run` writes the context into the run snapshot:

```json
{
  "agent": {},
  "application": {
    "id": "...",
    "version": 7,
    "skills": [],
    "connections": [],
    "builtin_tools": []
  }
}
```

`RuntimeFactory.for_run`:

1. If `snapshot["application"]` exists, build HTTP `ToolGateway` only from application connections.
2. Expose only the intersection of application-authorized skills and Agent built-ins.
3. Resolve connections by `application_id + connection_key + revision` and validate credentials.
4. Stop injecting custom global tools from Agent `tool_snapshot` unconditionally.

The global tool catalog may remain for administration/debugging but is not implicit authorization for application runtime.

### 5.6 Channel ingress

```text
Webhook
 -> read channels.application_id/application_version
 -> pin application_id/application_version on inbound outbox row
 -> worker claim
 -> find/create conversation with application/version
 -> resolver builds the run snapshot from the pinned version
 -> trace links application/version/skill/connection
```

If a channel is disabled before processing, existing rules mark the event failed; it must not fall back to the Agent's current version.

### 5.7 Example seed and copy

```text
startup seed
 -> compute template_key/version/digest for each code template
 -> INSERT service_application(origin=example, immutable=true)
    ON CONFLICT(scope, key) DO NOTHING
 -> never UPDATE an existing row

copy example
 -> read full example config
 -> new key/name, origin=user, immutable=false
 -> regenerate skill/connection ids; copy credential references or require reconfiguration
 -> audit copied_from_example
```

Examples must not contain real external credentials. Templates may use mock/demo connections; copies require configured credentials where needed.

### 5.8 Remove legacy paths

Backend removal:

- `providers/models.py`, `providers/service.py`, `providers/routes.py`, `providers/executors.py`.
- `scenarios/models.py`, `scenarios/service.py`, `scenarios/routes.py`, `scenarios/simulation.py`, `scenarios/tool_bridge.py`, `scenarios/seed.py`.
- `industry_packs/installations.py`, `merge.py`, `runtime_models.py`, `routes.py`.
- Provider/Scenario/IndustryPack composition in `PlatformServices`, plus `ScenarioToolBridge`.
- Legacy router registration in `applications/customer_service/application.py`.

Retain and refactor industry template content: consolidate the useful pack-manifest content into `service_apps/seed.py` to generate application-v2 standard examples only, with no tenant installation state.

Frontend removal:

- `features/service-scenarios/**`.
- `features/service-apps/IndustryCapabilitiesPage.tsx`.
- `/service-apps/industry` title, description and route branches in `App.tsx`.
- ServiceProvider, ServiceScenario and Industry Installation/Upgrade types/functions in `shared/api/client.ts`.
- Related CSS, i18n and Playwright tests.

## 6. Frontend design

### 6.1 Application catalog

```text
Service applications
├── Filters: All / My applications / Standard examples / Published / Configuring
├── Card: name, description, Agent, skill count, release status, origin tag
├── Actions: Open; examples only Preview / Copy as My Application
└── Bottom pagination: default 10
```

There is no separate "industry capability" entry; standard examples are an origin filter in the application catalog.

### 6.2 Application detail

```text
Overview | Agent | Skills | Business Rules | Preview & Debug | Customer Channels & Release
```

- **Overview**: status, bound Agent/version, skill/connection health, unpublished changes and recent traces.
- **Agent**: select Agent/version; show read-only prompt/model/knowledge summary and link to Agent management.
- **Skills**: Ant Design Table + Drawer.
- **Business Rules**: application fallback/handoff and a skill-level confirmation/amount/permission/idempotency summary.
- **Preview & Debug**: distinguish draft preview from published version; writes disabled by default.
- **Customer Channels & Release**: channel-bound versions, version switching, release checks, history and rollback.

### 6.3 Component split

```text
features/service-apps/
├── ServiceAppsPage.tsx                 # route orchestration, target <= 300 lines
├── catalog/ApplicationCatalog.tsx
├── detail/ApplicationDetail.tsx
├── detail/ApplicationOverviewTab.tsx
├── detail/ApplicationAgentTab.tsx
├── skills/SkillsTab.tsx
├── skills/SkillDrawer.tsx
├── connections/ConnectionsSection.tsx
├── connections/ConnectionDrawer.tsx
├── rules/ApplicationRulesTab.tsx
├── debug/ApplicationDebugTab.tsx
└── release/ChannelsReleaseTab.tsx
```

Constraints:

- Tables use Ant Design Table's native `pagination`: default 10, options 20/50, total count and bottom alignment.
- All visible copy uses i18n.
- Secret fields use password controls, are cleared after save and never repopulated.
- Examples expose only read-only view and Copy.

## 7. Configuration

`backend/src/agent_platform/core_platform/platform_services/platform_settings/settings.py`:

```python
service_app_examples_enabled: bool = True
service_app_connection_timeout_seconds: int = 10       # Field(ge=1, le=60)
service_app_connection_timeout_max: int = 60           # Field(ge=1, le=60)
service_app_default_page_size: int = 10                # Field(ge=1, le=100)
service_app_preview_write_enabled: bool = False
```

Credential encryption reuses the existing `model_credential_key_file` / Vault configuration; if isolation is required, add `service_app_credential_key_file`. Missing keys must never degrade to plaintext.

## 8. Model call path

This phase does not change Model Gateway:

- Agents continue to use `model_profile_id/model_profile_version`.
- An application binds an Agent version; runtime uses that Agent snapshot's profile and does not choose a model itself.
- The Agent proposes skill calls; deterministic rules approve them before application connections execute.
- Usage continues to be recorded in `gateway_calls` by `run_id`.

## 9. Observability and audit

- Application traces link `application_id/version`, `agent_id/version`, `skill_key` and `connection_key`.
- Audited actions: application create/update/publish/rollback/archive/copy, skill changes, connection changes, credential status and channel-version switching.
- Audit details never include connection secrets, Authorization, Cookie or complete external responses.
- Publish failures record explicit readiness codes, never credential values.

## 10. Test summary

| Layer | Cases |
|---|---|
| Unit | v2 contracts, schema/mappings, safety, digest, readiness, immutable examples, pagination parameters |
| Integration | Two applications with same-named skills/different connections, same-Agent isolation, publish/rollback, pinned channel ingress, seed/copy, audit redaction |
| Migration | Fresh `0058`, pre-release legacy-table removal, post-migration seed and publish |
| Frontend | Catalog pagination, detail tabs, skills Table/Drawer, read-only examples, legacy route removal |
| Regression | RBAC, Agent publishing, conversations, channel outbox/delivery, knowledge/memory, runs and audit |

Detailed cases are in `04-test-plan.md`.

## 11. Deployment and rollback

- `0058` is destructive; back up first. Quickstart should prefer `down` and a fresh data volume.
- Backend, frontend and migration ship together; old frontend against new backend and rolling mixed deployments are forbidden.
- Phase 1 provides no runtime switch back to the old model; clean-break is a product decision.
- Application behavior rolls back through application versions and channel bindings.
- Migration downgrade is for restoring schema shape in development only and does not restore data. Production rollback restores a backup and deploys the previous version.
- Seed is idempotent on every startup and never modifies user applications.
