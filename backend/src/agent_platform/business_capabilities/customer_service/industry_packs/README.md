# Industry Pack Runtime V1

This package implements both the compiler and the runtime installation slice of
the industry-pack design:

- a strict manifest model and deterministic compiler that produce the existing
  `ScenarioConfig` / `ServiceApplicationConfig`;
- tenant-scoped pack installation, provider registration, upgrade preview and
  three-way merge;
- maturity and provider-capability checks consumed by the existing release gate.

Runtime business logic must never branch on
`config.industry_pack.pack_key`; that metadata is only for lineage, audit,
upgrade and display.

## Manifest Contract

`IndustryPackManifest` contains:

- `pack_key`, `pack_version`, `maturity`
- `catalog_categories`
- `object_templates`
- `scenario_templates`
- `sample_data` and `acceptance_cases`
- optional `application_blueprint`

`ObjectTemplate` owns reusable object facts and candidate strategy.
`ScenarioTemplate.config` contains the task-specific portion of an existing
`ScenarioConfig` payload: entries, decisions, recommendations, handlers,
fallback order and matching.

The following scenario fields are owned by the manifest and applied during
compilation:

- `name` and `description` from `ScenarioTemplate`
- `domain` defaults to the pack name
- `template` from `execution_template`
- `category` resolved from `catalog_category_key`
- `object` and `facts` derived from `object_template_key`
- `channels` from the scenario template when present
- `config.industry_pack` source metadata

## Compilation Contract

```python
from agent_platform.business_capabilities.customer_service.industry_packs import (
    IndustryPackCompiler,
    IndustryPackManifest,
)

manifest = IndustryPackManifest.model_validate(pack_data)
compiler = IndustryPackCompiler(manifest)
scenario = compiler.compile_scenario("account-status-query")

application = compiler.compile_application()
existing_application_config = application.config
```

`compile_application()` returns a `CompiledApplicationBlueprint` wrapper because
the existing `ServiceApplicationConfig` has no industry extension field.  The
wrapper contains:

- `application_key`
- `application: ServiceApplicationConfig`
- `industry_pack` source metadata
- deterministic `digest`

Use `compile_application_config()` when only the existing
`ServiceApplicationConfig` is needed.

Compilation performs these checks:

1. `pack_key`, template keys and SemVer versions are valid.
2. Catalog category, object template and scenario template keys are unique.
3. Scenario category and object references exist.
4. Scenario channels belong to `supported_channels`.
5. Application-blueprint category and scenario references exist.
6. Blueprint version pins match the referenced scenario-template versions.
7. Samples and acceptance cases reference existing scenarios, decisions,
   handlers and business-fact fields.
8. Scenarios with human handlers have an enabled human capability in the
   application blueprint.
9. The resulting payloads pass the existing `ScenarioConfig` and
   `ServiceApplicationConfig` validation.

The source metadata written to `config.industry_pack` is:

```json
{
  "pack_key": "content-community",
  "pack_version": "1.0.0",
  "template_key": "account-status-query",
  "template_version": "1.0.0",
  "template_digest": "sha256:...",
  "scenario_kind": "query",
  "maturity": "ga",
  "catalog_category_key": "account-security"
}
```

`template_digest` is SHA-256 over canonical JSON (sorted keys, compact
separators, UTF-8) of the template before source metadata is added.

## Runtime Contract

Migration `0057_industry_pack_runtime` adds three scoped tables:

- `service_provider_registry`
- `industry_pack_installations`
- `industry_pack_upgrades`

The installation API is:

```text
GET  /api/v1/industry-packs
GET  /api/v1/industry-packs/{pack_key}
GET  /api/v1/industry-packs/installations
POST /api/v1/industry-packs/{pack_key}/install
POST /api/v1/industry-packs/installations/{id}/upgrade-preview
POST /api/v1/industry-packs/installations/{id}/upgrade
```

Installing a pack:

1. Creates real scenario drafts for the selected templates.
2. Creates a real service-application draft and maps the application blueprint
   to the installed scenarios.
3. Persists pack source, template versions, template digests and maturity in
   scenario metadata.
4. Saves the installation baseline used by later three-way merges.
5. Idempotently creates disabled provider placeholders for required objects,
   tools and human queues.
6. Never publishes automatically and never silently overwrites a tenant draft.

The same pack and application key with the same digest returns the existing
installation (`created=false`). A different digest is a conflict. An existing
scenario with matching pack source metadata is reused; an existing application
with the same key is rejected rather than overwritten.

## Provider Registry

`ServiceProviderRegistry` supports three kinds:

- `object`
- `tool`
- `human_queue`

The registry is scoped by tenant, business and workspace. It provides list, get,
create and update operations, revision-based conflict control, audit events and
idempotent disabled placeholders for pack requirements. Readiness consumes only
enabled identities.

Template upgrades also register disabled placeholders for providers newly
introduced by the target version.

This is a declaration and configuration registry, not a real connector runtime.
Credential custody, authentication, invocation, retry, timeout, health checks
and result-unknown handling remain future execution-layer work.

## Upgrade and Merge

An upgrade compares:

- `base`: the baseline saved at installation;
- `local`: the current tenant draft;
- `incoming`: the target pack version.

`entries / facts / decisions / recommendations / handlers` merge by `key`,
`options` merge by `value`, and `fallback_order` / ordinary lists merge by stable
JSON value. Conflicting changes keep local and block apply. A preview writes an
`industry_pack_upgrades` record without modifying drafts. Applying a clean
preview rechecks scenario and application `draft_revision` and still does not
publish.

## Release Gate

Pack scenarios add two readiness checks:

- `template-maturity`
- `provider-capability`

`alpha` is always blocked. `beta` requires an application `canary` channel.
`ga` follows the normal release checks. Missing object, tool or human-queue
providers block pack scenarios, while non-pack scenarios retain their previous
readiness behavior. Check copy does not expose internal provider or queue
identities.

The scenario publish endpoint also rejects `alpha` directly with
`scenario_alpha_publish_forbidden`, so the application readiness gate cannot be
bypassed by publishing the scenario alone.

Pack lineage under `config.industry_pack` is owned by the installer. Normal
scenario create/update APIs reject injected lineage and reject changes to the
lineage of an installed scenario, so maturity cannot be edited from `alpha` to
`ga` to bypass the release gate.

## Frontend

The Service Applications area exposes `/service-apps/industry` with three
sections:

- industry template installation;
- provider capability management;
- installation and upgrade records.

No top-level navigation item or standalone `/service-scenarios` page is added.
The readiness panel renders the new maturity and provider checks.

## Object Compilation

For a scenario with `object_template_key`, the compiler injects:

- `object.type` from `object_type`
- `object.provider` from `provider_key`
- `object.mode` from `default_mode`
- `object.required` from the mode
- candidate strategy and permission scope
- object-template facts

Scenario-level facts may override a fact with the same key. A scenario object
override may customize presentation configuration, but it may not change the
template's protected `type`, `provider`, `mode` or `required` values.

## Content Community Pack

`content_community.py` provides the first complete pack asset:

- 6 business-object templates
- 11 scenario templates: 3 `ga`, 6 `beta`, 2 `alpha`
- 11 simulation samples and 11 acceptance cases
- 6 application catalog categories
- an application blueprint for the 3 `ga` scenarios
- web, app, WeChat and H5 customer channels
- a `content-support` human handoff capability

The samples execute through the existing deterministic simulator.  Tool calls
are intentionally not made in this increment.

## Local Life Pack

`local_life.py` is the second pack compiled through exactly the same
`IndustryPackCompiler` and existing `ScenarioConfig` /
`ServiceApplicationConfig` contracts:

- 4 business-object templates: order, reservation/verification record,
  refund/after-sales case and merchant/store
- 6 scenario templates: 2 `ga`, 3 `beta`, 1 `alpha`
- 6 simulation samples and 6 acceptance cases
- an application blueprint for the 2 `ga` scenarios
- web, app, WeChat and H5 customer channels
- a `local-life-support` human handoff capability

The refund/after-sales action requires a `confirm_action` decision and has a
human fallback.  Adding this pack required no change to the scenario,
service-application or runtime models.

## Deferred

The following work remains outside this development slice:

- policy-template composition
- actual tool execution for sample and acceptance cases
- real provider connectors, credentials, health checks, retry and observability
- external pack distribution, signing and provenance verification
- upgrade rollback, field-level conflict resolution UI and bulk upgrade
- real WeCom/Feishu ingress through scenario execution to human handoff
- production-data acceptance for permissions, masking, idempotency and unknown
  results

## Verification

From `backend`:

```powershell
python -m pytest `
  tests/test_industry_packs.py `
  tests/test_industry_pack_migrations.py `
  tests/test_industry_pack_merge.py `
  tests/test_industry_pack_runtime.py `
  tests/test_industry_pack_release_gate.py -q
python -m ruff check `
  src/agent_platform/business_capabilities/customer_service/industry_packs `
  src/agent_platform/business_capabilities/customer_service/providers `
  tests/test_industry_pack_migrations.py `
  tests/test_industry_pack_merge.py `
  tests/test_industry_pack_runtime.py `
  tests/test_industry_pack_release_gate.py
```

These tests provide regression coverage for the development slice. They do not
replace real provider, channel and production-data acceptance.
