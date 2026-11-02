# Industry Pack runtime V1

> Status: development implementation landed; production acceptance is not complete
> Created: 2026-11-02
> Related:
> - [Multi-industry scenario packs](./industry-pack-v1.md)
> - [Customer service implementation roadmap](./implementation-roadmap-v1.md)
> - [Human workbench business context](./handoff-context-v1.md)

## 0. What this slice delivers

Before this slice, an industry pack could be compiled into a `ScenarioConfig`
and a `ServiceApplicationConfig`, but it could not be installed into a tenant.
There was also no unified provider registry, template upgrade flow or maturity
release gate.

This slice closes the development loop from a compilable asset to an installable,
configurable, upgradeable and checkable runtime asset:

1. An industry pack can be installed as real scenario drafts and a real service
   application draft.
2. Business objects, tools and human queues share one provider registry.
3. A later template version can be previewed through a three-way merge without
   silently overwriting tenant edits.
4. `alpha / beta / ga` maturity participates in backend readiness and the
   scenario publish gate.
5. The frontend exposes an industry-capability page inside service applications.

This is still not a production-complete delivery. Real provider invocation, tool
execution, real-channel ingress verification and production-data acceptance
remain outstanding.

## 1. Goals and boundaries

### 1.1 Goals

- Express industry differences through templates, configuration and registries,
  never through runtime `if industry` or `if pack_key` business branches.
- Installation and upgrades only modify drafts and never publish automatically.
- Isolate installation, upgrades, providers and readiness by tenant, business
  and workspace scope.
- Preserve local configuration on conflicts and block the upgrade apply.
- Enforce release checks on the backend; the frontend only explains and guides.

### 1.2 Non-goals

- A pack marketplace, signed distribution or external artifact repository.
- Real provider network calls, credential custody, health checks or retries.
- Automatic publishing of installed scenarios or applications.
- Upgrade rollback, field-by-field conflict resolution UI or automatic data
  migration.
- Treating the simulator and automated tests as a substitute for real-channel
  and production-data verification.

## 2. Data model

Migration `0057_industry_pack_runtime` adds three persistent tables. Every table
is scoped by `tenant_id + business_id + workspace_id`.

### 2.1 `service_provider_registry`

Stores three provider kinds:

- `object`: business-object data sources such as orders, invoices and logistics.
- `tool`: query, action and external-system invocation capabilities.
- `human_queue`: human handoff queues.

Key fields include `provider_key / kind / name / enabled / config / source /
source_ref / revision`. Within a scope, `kind + provider_key` is unique and only
the three kinds above are allowed.

### 2.2 `industry_pack_installations`

Stores one pack installation:

- Pack key, version, digest and maturity.
- Application key created by the installation.
- Scenario-template versions and digests.
- Mapping from template keys to installed scenario keys.
- Baseline snapshot of installed application and scenario configuration.
- Installation status and revision.

Within a scope, `pack_key + application_key` is unique.

### 2.3 `industry_pack_upgrades`

Stores upgrade previews and applications:

- Source version, target version and target digest.
- Merge plan, conflict paths and target configuration.
- `preview / clean / conflicted / applied / failed` status.
- Creator, applying actor and application timestamp.

The upgrade row references the installation through a scoped composite foreign
key and is deleted with the installation.

## 3. Provider registry

### 3.1 API

```text
GET  /api/v1/service-providers
GET  /api/v1/service-providers/{kind}/{key}
POST /api/v1/service-providers
PUT  /api/v1/service-providers/{kind}/{key}
```

Read endpoints allow read-only roles. Create and update require administrator
access.

### 3.2 Behavior

- Supports kind filters and search over key, name and description.
- Creating a duplicate `kind + key` returns 409.
- Updates require the current `revision`; stale writes return
  `service_provider_missing_or_revision_conflict`.
- `kind` and `key` form the stable identity and cannot be changed by an update.
- Create and update emit `service_provider.created` and
  `service_provider.updated` audit events.
- Pack installation idempotently creates disabled placeholder providers and
  never overwrites an operator-managed row with the same identity.
- Template upgrades also register disabled placeholders for providers newly
  introduced by the target version.
- Readiness only consumes enabled provider identities in the current scope.

The registry currently stores capability declarations and connection
configuration, not a complete connector runtime. Real authentication,
invocation, timeouts, retries and health checks remain future execution-layer
work.

## 4. Industry-pack installation

### 4.1 API

```text
GET  /api/v1/industry-packs
GET  /api/v1/industry-packs/{pack_key}
GET  /api/v1/industry-packs/installations
POST /api/v1/industry-packs/{pack_key}/install
POST /api/v1/industry-packs/installations/{id}/upgrade-preview
POST /api/v1/industry-packs/installations/{id}/upgrade
```

Installation request example:

```json
{
  "pack_version": "1.0.0",
  "application_key": "content-community-service",
  "install_scenarios": true
}
```

`install_scenarios=true` installs every scenario in the pack. `false` installs
only the scenarios referenced by the application blueprint. If omitted, the
current API defaults to installing all scenarios.

### 4.2 Installation result

- Creates real `service_scenarios` drafts for target scenarios.
- Creates a real service-application draft and maps blueprint references to the
  installed scenarios.
- Writes pack source, template version, template digest and maturity into
  scenario metadata.
- Saves an installation baseline snapshot for later three-way merges.
- Creates disabled provider placeholders required by the installed scenarios.
- Never publishes scenarios or applications automatically.

### 4.3 Idempotency and conflicts

- Same scope, pack and application key with the same digest returns the existing
  installation and `created=false`.
- Same installation identity with a different digest returns
  `industry_pack_installation_conflict`.
- An existing scenario with matching pack source metadata is reused and its
  draft is not overwritten.
- An existing scenario with a different source returns
  `industry_pack_scenario_collision`.
- An existing application with the same key returns
  `industry_pack_application_conflict`; it is never silently overwritten.

## 5. Template upgrade and three-way merge

### 5.1 Three inputs

- `base`: the template baseline saved at installation time.
- `local`: the tenant's current scenario or application draft.
- `incoming`: the template compiled from the target pack version.

### 5.2 Merge rules

- Compare `base / local / incoming` by field path.
- `entries / facts / decisions / recommendations / handlers` use `key` as list
  identity.
- `options` use `value` as identity.
- `fallback_order` and other ordinary lists merge by stable JSON value.
- Array indexes are never used as business identity.
- Keep a local value when only local changed.
- Adopt the incoming value when only the template changed.
- Auto-merge non-overlapping changes from both sides.
- Record a conflict and keep local when both sides changed the same path.
- Revalidate the merged result as `ScenarioConfig`; validation failure falls back
  to local and marks the result `blocked`.
- Application configuration also participates in preview and blocks application
  upgrade when it cannot be merged safely.

### 5.3 Preview and apply

- `upgrade-preview` writes a plan to `industry_pack_upgrades` and does not modify
  scenario or application drafts.
- Preview status is `clean / conflicted / blocked`.
- Only a `clean` preview can be applied.
- Apply rechecks scenario and application `draft_revision`; drift after preview
  returns `industry_pack_upgrade_preview_stale`.
- A successful apply updates drafts, installation version, baseline snapshot and
  the upgrade record, but does not publish.
- Conflicted, blocked or stale previews cannot partially write.

## 6. Maturity and release gates

Readiness adds two pack-scenario checks:

- `template-maturity`
- `provider-capability`

### 6.1 Template maturity

| Maturity | Release decision |
|---|---|
| `alpha` | Always blocked; validation and simulation only |
| `beta` | Allowed when the application has a `canary` customer channel; otherwise blocked |
| `ga` | Evaluated through the normal release checks |

The scenario publish endpoint also inspects pack maturity directly. An `alpha`
scenario returns:

```text
409 scenario_alpha_publish_forbidden
```

This prevents bypassing application readiness by publishing the scenario alone.

`config.industry_pack` is installer-owned reserved metadata. Normal scenario
creation rejects injected lineage, and updates to installed scenarios must keep
the existing lineage unchanged. An operator cannot change `alpha` to `ga` to
bypass the release gate.

### 6.2 Provider capability

For pack scenarios, readiness checks:

- `object.provider` through `object:{provider}`.
- Enabled-handler `tool` through `tool:{tool}`.
- Human handler or capability queues through `human_queue:{queue}`.

Missing capabilities block release. Check copy reports only how many business
data capabilities are missing; it does not expose provider keys, tool identifiers
or queue names to operators or customers.

Non-pack scenarios do not enable these two extra checks and retain their
existing readiness behavior.

## 7. Frontend

New route:

```text
/service-apps/industry
```

The entry lives inside Service Applications, adds no top-level navigation item
and does not restore the standalone `/service-scenarios` page.

The page has three sections:

- **Industry templates**: inspect packs, maturity, object/scenario counts and
  install them as drafts.
- **Provider capabilities**: filter and edit object, tool and human-queue
  providers.
- **Upgrade records**: inspect installations, run upgrade previews, show conflict
  paths and apply clean upgrades.

The readiness panel also renders `template-maturity` and `provider-capability`
checks so frontend and backend explanations stay aligned.

## 8. Relationship to the human workbench

Real scenario-context aggregation in the human workbench was already completed.
`GET /api/v1/handoffs/{id}/context` returns scenario, object, facts, decisions,
runs and routing evidence with server-side permission trimming and masking.

This slice adds industry packs, providers and release gates; it does not
reimplement workbench context. Real-channel handoff ingress remains to be
verified end to end.

## 9. Verification coverage

The codebase currently includes:

```text
backend/tests/test_industry_pack_migrations.py
backend/tests/test_industry_pack_merge.py
backend/tests/test_industry_pack_runtime.py
backend/tests/test_industry_pack_release_gate.py
backend/tests/test_service_application_readiness.py
backend/tests/test_handoff_context.py
```

Coverage focuses on:

- Migration creation, constraints, indexes and reversibility.
- Provider CRUD, revision conflicts and permissions.
- Pack-install idempotency, scenario/application drafts and provider placeholders.
- Three-way auto-merge, conflicts, deletion and validation failure.
- Upgrade preview, apply and revision drift.
- `alpha / beta / ga` and missing-provider release gates.
- Human-workbench context aggregation.

These tests provide regression protection for the development slice; they do not
constitute production acceptance.

## 10. Remaining work

1. **Real provider and tool execution**: the registry is not yet connected to
   real business systems and has no credential, retry, rate-limit, timeout,
   health-check or observability loop.
2. **Real-channel ingress verification**: workbench context is usable, but the
   complete WeCom/Feishu ingress, scenario execution and handoff path still needs
   end-to-end acceptance.
3. **Production-data acceptance**: validate permissions, masking, idempotency,
   failures and unknown-result semantics with real orders, accounts, refunds,
   logistics and human queues.
4. **Upgrade governance**: rollback, field-level conflict resolution, bulk
   upgrades and canary upgrade policy are still absent.
5. **Pack distribution**: only the built-in catalog exists; external package
   installation, signing, provenance validation and a version marketplace are
   not implemented.
6. **Production operations**: capacity, monitoring, alerting, audit retention,
   disaster recovery and release-rollback drills still need to be established.

Current conclusion: **the capability loop has landed as a development version
and can enter integration and acceptance; it must not yet be described as
production-ready.**
