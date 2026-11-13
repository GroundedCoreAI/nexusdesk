# Phase 1 · Skill-Centric Application Runtime - Business Goals

> Status: Requirements baseline implemented and targeted validation complete; full acceptance remains pending
> Created: 2026-11-11
> Basis: topic [README](../README.en.md); code review of the existing service application, Provider, scenario, industry-pack and channel implementation (migrations through `0057_industry_pack_runtime`)
> Estimate: approximately 3-4 weeks, including a one-time pre-release breaking refactor

## Problems to solve

### Problem 1: A service application is not yet a real business boundary

The v1 configuration in `backend/src/agent_platform/business_capabilities/customer_service/service_apps/models.py` treats an Agent as one `capabilities` type while retaining `scenarios`, `capabilities` and `default_execution_order`. Operators must understand "application -> scenario -> capability -> Agent" before they can configure one business service.

Typical failure: two applications both need "order lookup", but the order-system URLs, authentication and confirmation rules differ. The current model can only create global same-named Providers or reference global tools from scenarios; it cannot express "same skill, different application, different connection".

### Problem 2: Connections are not application assets, so isolation and authorization are unprovable

`service_provider_registry` is scoped only by tenant/business/workspace and has no `application_id`. Real URLs, headers and credentials live in `registered_tools` / `tool_credentials`, while scenarios can reach those global resources through `ScenarioToolBridge`.

Typical failure: after application A configures order lookup, application B or another application using the same Agent may see tools it should not use. Audit also cannot answer which application version and connection produced a call.

### Problem 3: Release versions do not constrain real ingress

Although `service_application_versions` exists, `channels` still store `agent_id` directly and `runtime_conversations` records only `agent_id`. Channel inbound messages bypass the published service-application version, so promises such as "draft edits do not affect production" and "roll back an application version" do not hold for real channels.

Typical failure: after an operator rolls back an application, new channel messages still run the Agent's current version; troubleshooting cannot locate the application version from the conversation.

### Problem 4: Too many intermediate concepts and historical mechanisms

Scenarios, Providers, integration capabilities, industry-pack installation, upgrade preview, conflict merge and upgrade history form a second lifecycle. Users must learn internal abstractions instead of moving faster through "copy example -> configure connection -> bind channel -> preview and publish".

Typical failure: an edited industry example cannot be restored, while upgrade history and merge logic add maintenance cost without a confirmed production requirement.

### Problem 5: Frontend/backend responsibility and page boundaries are out of control

Backend `ServiceApplicationService` is 1,485 lines and `ChannelService` is 1,019 lines; frontend `ServiceAppsPage.tsx` is 2,384 lines and `IndustryCapabilitiesPage.tsx` is 1,021 lines. Application configuration, scenario debugging, industry templates, Provider configuration and release state are entangled.

## Business goals

| Goal | Description |
|---|---|
| G1: The service application is the single business delivery unit | Each application directly binds one Agent version and owns its skills, connections, rules and channels; no scenario/capability indirection |
| G2: Skills and connections are fully application-isolated | Skill keys are unique within an application; different applications may use the same skill name with different connections, credentials and safety rules; runtime resolves only application-authorized resources |
| G3: Releases are immutable and traceable | Publishing produces a v2 snapshot; draft edits do not affect production; rollback creates a new historical version; channels, inbound events, conversations and runs record the application version |
| G4: Standard examples are safely reusable | Standard examples exist as immutable sample applications that can only be previewed and copied; copies become user-owned; startup seeding never overwrites user edits |
| G5: Concepts and UI converge | Primary concepts reduce to service application, Agent, skill, application connection and customer channel; each application uses Overview / Agent / Skills / Business Rules / Preview & Debug / Customer Channels & Release |
| G6: Pre-release clean-break | Remove Provider, Scenario, execution capability, integration capability, upgrade history and legacy API/UI/table references; no data migration, dual read or compatibility layer |

## Success metrics

| Metric | Baseline | Target |
|---|---|---|
| Legacy intermediate concepts in application configuration | At least 3 categories - scenario, capability and Provider - still participate in the main flow | 0 in new UI/API/runtime; only the five primary concepts |
| Same-named skills across applications | No application-level connection; isolation cannot be proven | Integration test with two applications and different URLs/credentials passes 100% |
| Cross-application skill/connection leakage | No automated guarantee; the global tool bridge creates bypasses | 0 leaks in security/integration tests, including one Agent referenced by multiple applications |
| Channel message traceability to application version | Channels and conversations currently record only Agent | Application-version coverage in inbound events, conversations and runs is 100% |
| Draft edit affecting production | Channel path bypasses application releases | Online behavior diff after draft edit is 0; behavior switches only after republishing |
| Direct editing/restart overwrite of examples | Installation and upgrade flows allow complex edits/merges | 100% of example edit requests are rejected; restart never overwrites user applications |
| Time from copying an example to first preview | No formal baseline | Median <= 10 minutes across a five-operator UAT sample |
| Legacy concept residue | Provider/Scenario/upgrade routes and components remain | Search result for the defined cleanup scope is 0, excluding historical docs and migration files |
| Main application page component size | `ServiceAppsPage.tsx` is 2,384 lines | Each newly split/changed page component is <= 800 lines and business sections are independent |
| Application list scale | `/service-apps` currently returns all items | Default page size 10, server-side pagination aligned with Ant Design Table/Pagination |

## Scope

**Included:**

- Direct application-to-Agent/version binding.
- Application skills, application connections, secure credential storage and CRUD.
- v2 release snapshots, publish checks, immutable versions, rollback and diff summary.
- Application-scoped runtime resolution and Agent tool allow-listing.
- Application-version pinning for channels, inbound outbox, conversations and runs.
- Standard-example seeding, immutable examples and copy-to-my-application.
- Application list pagination, internal information architecture, skill tables and connection testing.
- Removal of legacy Scenario/Provider/Industry Installation/Upgrade backend, frontend, APIs, tests and types.
- One-time `0058_service_application_v2` breaking migration and fresh-database initialization verification.
- Chinese/English copy, permissions, audit, observability and security tests.

**Excluded:**

- No legacy data conversion, compatibility API, dual read/write or redirects for removed routes.
- No general drag-and-drop workflow designer.
- No external intent Router.
- No industry-pack installation instances, upgrade preview, three-way merge or upgrade history.
- No complex rule DSL in this phase; safety rules initially use deterministic skill-level fields and application-level fallback configuration.
- No cross-application connection/credential sharing or platform-level business-object Template.
- No Phase 2 bulk channel rollout, automatic traffic switching or advanced operations analytics.

## Risks and constraints

- **Breaking migration risk**: `0058` removes legacy service-scenario/Provider/industry-installation tables. Mitigation: the product is not generally available; back up development data before upgrade; fresh-database initialization and regression are release gates.
- **Runtime bypass risk**: application isolation fails if Agents can continue to reference `registered_tools` directly. Mitigation: customer application runtime accepts only skills in the release snapshot; the global tool catalog remains for administration and debugging, not direct application authorization.
- **Credential leakage risk**: connection editing and publishing are the most likely paths to leak secrets into JSON or logs. Mitigation: store only Vault ciphertext, keep only `credential_ref` and digest in releases, and expose only `credentials_configured` in APIs.
- **Channel version complexity**: channels explicitly pin a version, and publishing does not auto-switch them. Mitigation: the UI clearly shows the bound version and version switching is a separate audited action; Phase 2 may add bulk/gradual rollout.
- **Example/application confusion**: users may think they can edit standard examples. Mitigation: mark sample cards clearly, disable editing and expose only Copy as My Application; the copy retains lineage only.
- **Capability expansion**: teams may put general business processes back into the application layer. Mitigation: one skill represents one explicit business action; complex decisions remain with the Agent, while safety boundaries use deterministic fields.
- **Compatibility**: legacy service-application configurations are not preserved and development data must be reset. Code, frontend and migration `0058` must ship together; rolling mixed deployments are forbidden.
