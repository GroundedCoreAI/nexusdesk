# Industry Pack Compiler V1

This package implements the first code increment of the industry-pack design:
a strict manifest model and a deterministic compiler that produces the
existing `ScenarioConfig`.

It does **not** add runtime pack tables, routes, migrations, or scenario
models. Runtime business logic must never branch on
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

This increment intentionally leaves these for later slices:

- policy-template composition
- actual tool execution for sample and acceptance cases
- provider and tool registry availability checks
- application blueprint persistence as a tenant application
- template upgrade/three-way merge
- backend-enforced release gates

## Verification

From `backend`:

```powershell
python -m pytest tests/test_industry_packs.py -q
python -m ruff check src/agent_platform/business_capabilities/customer_service/industry_packs tests/test_industry_packs.py
```
