from __future__ import annotations

import pytest

from agent_platform.business_capabilities.customer_service.industry_packs.compiler import (
    IndustryPackCompiler,
)
from agent_platform.business_capabilities.customer_service.industry_packs.creator import (
    CREATOR_PACK,
    build_creator_pack,
)
from agent_platform.business_capabilities.customer_service.industry_packs.gaming import (
    GAMING_PACK,
    build_gaming_pack,
)
from agent_platform.business_capabilities.customer_service.industry_packs.installations import (
    _default_packs,
)
from agent_platform.business_capabilities.customer_service.industry_packs.mobility import (
    MOBILITY_PACK,
    build_mobility_pack,
)
from agent_platform.business_capabilities.customer_service.industry_packs.models import (
    IndustryPackManifest,
    IndustryPackMaturity,
)
from agent_platform.business_capabilities.customer_service.industry_packs.shopping import (
    SHOPPING_PACK,
    build_shopping_pack,
)
from agent_platform.business_capabilities.customer_service.scenarios.simulation import simulate
from agent_platform.business_capabilities.customer_service.service_apps.models import (
    ApplicationScenarioReference,
)
from agent_platform.business_capabilities.customer_service.service_apps.readiness import (
    ScenarioReadinessSnapshot,
    evaluate_application_readiness,
)

DEMO_PACKS = [
    pytest.param(SHOPPING_PACK, build_shopping_pack, id="shopping"),
    pytest.param(GAMING_PACK, build_gaming_pack, id="gaming"),
    pytest.param(CREATOR_PACK, build_creator_pack, id="creator"),
    pytest.param(MOBILITY_PACK, build_mobility_pack, id="mobility"),
]


def _samples_by_scenario(manifest: IndustryPackManifest) -> dict[str, object]:
    return {sample.scenario_template_key: sample for sample in manifest.sample_data}


def test_demo_registry_ships_exactly_the_four_packs():
    assert list(_default_packs()) == ["shopping", "gaming", "creator", "mobility"]


@pytest.mark.parametrize(("manifest", "_build"), DEMO_PACKS)
def test_demo_pack_leaves_no_catalog_category_empty(manifest, _build):
    used = {template.catalog_category_key for template in manifest.scenario_templates}

    assert [
        category.key for category in manifest.catalog_categories if category.key not in used
    ] == []


@pytest.mark.parametrize(("manifest", "_build"), DEMO_PACKS)
def test_demo_pack_scenarios_are_all_ga(manifest, _build):
    assert {template.maturity for template in manifest.scenario_templates} == {
        IndustryPackMaturity.GA
    }


@pytest.mark.parametrize(("manifest", "_build"), DEMO_PACKS)
def test_demo_pack_action_scenarios_require_a_non_skippable_confirmation(manifest, _build):
    action_templates = [
        template
        for template in manifest.scenario_templates
        if template.execution_template == "action"
    ]

    assert action_templates
    for template in action_templates:
        confirmations = [
            decision
            for decision in template.config["decisions"]
            if decision["kind"] == "confirm_action"
        ]
        assert len(confirmations) == 1
        confirmation = confirmations[0]
        assert confirmation["required"] is True
        assert confirmation["confirm"] is True
        assert confirmation["allow_skip"] is False


@pytest.mark.parametrize(("manifest", "_build"), DEMO_PACKS)
def test_demo_pack_blueprint_references_every_scenario(manifest, _build):
    blueprint = manifest.application_blueprint

    assert blueprint is not None
    assert blueprint.scenario_template_keys == [
        template.template_key for template in manifest.scenario_templates
    ]
    assert set(blueprint.catalog_category_keys) == {
        category.key for category in manifest.catalog_categories
    }


@pytest.mark.parametrize(("manifest", "_build"), DEMO_PACKS)
def test_demo_pack_every_object_template_is_used_by_a_scenario(manifest, _build):
    referenced = {
        template.object_template_key
        for template in manifest.scenario_templates
        if template.object_template_key is not None
    }

    assert {item.object_template_key for item in manifest.object_templates} == referenced


@pytest.mark.parametrize(("manifest", "_build"), DEMO_PACKS)
def test_demo_pack_declares_the_identities_readiness_checks(manifest, _build):
    """The release gate asks for ``object:``, ``tool:`` and ``human_queue:`` identities."""

    compiler = IndustryPackCompiler(manifest)
    provider_keys = {item.provider_key for item in manifest.object_templates}
    for template in manifest.scenario_templates:
        config = compiler.compile_scenario(template.template_key)
        if config.object is not None:
            assert config.object.provider in provider_keys
        for handler in config.handlers:
            if handler.tool:
                assert handler.tool
            if handler.type == "human":
                assert handler.queue


@pytest.mark.parametrize(("manifest", "_build"), DEMO_PACKS)
def test_demo_pack_samples_pass_their_acceptance_cases(manifest, _build):
    compiler = IndustryPackCompiler(manifest)
    samples = _samples_by_scenario(manifest)

    assert {case.scenario_template_key for case in manifest.acceptance_cases} == set(samples)
    for case in manifest.acceptance_cases:
        sample = samples[case.scenario_template_key]
        config = compiler.compile_scenario(case.scenario_template_key)
        trace = simulate(
            case.scenario_template_key,
            config.name,
            None,
            "draft",
            config,
            sample.as_simulation_request(),
        )

        assert trace.result["status"] == case.then.result_status
        assert trace.handler is not None
        assert trace.handler["type"] == case.then.handler_type.value
        projected = {fact["key"]: fact for fact in trace.facts}
        assert set(case.then.must_include_facts) <= set(projected)
        for forbidden in case.then.must_not_include:
            if forbidden in projected:
                assert projected[forbidden]["masked"] is True


@pytest.mark.parametrize(("manifest", "_build"), DEMO_PACKS)
def test_demo_pack_digest_is_deterministic(manifest, _build):
    first = IndustryPackCompiler(manifest)
    second = IndustryPackCompiler(_build())

    assert first.digest == second.digest
    assert first.compile_application().digest == second.compile_application().digest


@pytest.mark.parametrize(("manifest", "_build"), DEMO_PACKS)
def test_demo_pack_reaches_ready_state_once_promoted(manifest, _build):
    """After ``seed_demo_packs`` publishes scenarios and enables providers, the
    release gate must pass with no blocked or warning check."""

    compiler = IndustryPackCompiler(manifest)
    application = compiler.compile_application_config()
    snapshots: list[ScenarioReadinessSnapshot] = []
    identities: set[str] = set()

    for template in manifest.scenario_templates:
        config = compiler.compile_scenario(template.template_key)
        if config.object is not None:
            identities.add(f"object:{config.object.provider}")
        for handler in config.handlers:
            if handler.tool:
                identities.add(f"tool:{handler.tool}")
            if handler.type == "human" and handler.queue:
                identities.add(f"human_queue:{handler.queue}")
        snapshots.append(
            ScenarioReadinessSnapshot(
                reference=ApplicationScenarioReference(
                    key=template.template_key,
                    version=None,
                    enabled=True,
                ),
                name=config.name,
                scenario_status="published",
                published_version=1,
                effective_version=1,
                version_available=True,
                effective_config=config,
                has_unpublished_changes=False,
            )
        )

    result = evaluate_application_readiness(
        application_key=application.name,
        application_name=application.name,
        revision=1,
        application_status="draft",
        application=application,
        scenarios=snapshots,
        available_provider_identities=identities,
    )

    assert result.status.value == "ready"
    assert result.can_publish is True
    assert result.counts.blocked == 0
    assert result.counts.warning == 0


@pytest.mark.asyncio
async def test_seed_leaves_an_archived_demo_application_alone():
    """Re-seeding must not resurrect an application an operator archived."""

    from agent_platform.applications.seed_demo_packs import _publish_application
    from agent_platform.core_platform.platform_services.persistence.store import (
        DomainError,
    )

    class Apps:
        def __init__(self, error=None):
            self.error = error
            self.published = []

        async def get(self, tenant, key):
            assert (tenant, key) == ("local", "shopping-service")
            if self.error is not None:
                raise self.error
            return {"key": key, "revision": 3, "published_version": None}

        async def publish(self, tenant, actor, key, revision):
            self.published.append((tenant, actor, key, revision))
            return {"key": key, "version": 1}

    archived = Apps(error=DomainError("service_application_not_found", 404))
    business = type("Business", (), {"service_apps": archived})()
    assert await _publish_application(business, "local", "actor", "shopping-service") is None
    assert archived.published == []

    # Any other domain error still surfaces: only the missing row is forgiving.
    failing = Apps(error=DomainError("service_application_revision_conflict", 409))
    business = type("Business", (), {"service_apps": failing})()
    with pytest.raises(DomainError, match="revision_conflict"):
        await _publish_application(business, "local", "actor", "shopping-service")

    fresh = Apps()
    business = type("Business", (), {"service_apps": fresh})()
    assert await _publish_application(business, "local", "actor", "shopping-service") is True
    assert fresh.published == [("local", "actor", "shopping-service", 3)]
