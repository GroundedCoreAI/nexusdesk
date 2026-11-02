"""Pure release-gate tests for pack maturity and provider readiness."""

from __future__ import annotations

from copy import deepcopy

from agent_platform.business_capabilities.customer_service.industry_packs.compiler import (
    IndustryPackCompiler,
)
from agent_platform.business_capabilities.customer_service.industry_packs.content_community import (
    build_content_community_pack,
)
from agent_platform.business_capabilities.customer_service.service_apps.models import (
    ApplicationScenarioReference,
    ServiceApplicationConfig,
)
from agent_platform.business_capabilities.customer_service.service_apps.readiness import (
    ScenarioReadinessSnapshot,
    evaluate_application_readiness,
)


def _pack_scenario(maturity: str):
    manifest = deepcopy(build_content_community_pack())
    template = next(item for item in manifest.scenario_templates if item.maturity.value == maturity)
    return template.template_key, IndustryPackCompiler(manifest).compile_scenario(
        template.template_key
    )


def _application(scenario_key: str, *, canary: bool = False) -> ServiceApplicationConfig:
    return ServiceApplicationConfig.model_validate(
        {
            "name": "模板发布门禁",
            "description": "",
            "scenarios": [
                {
                    "key": scenario_key,
                    "version": 1,
                    "enabled": True,
                }
            ],
            "capabilities": [],
            "channels": [
                {
                    "key": "web",
                    "name": "官网",
                    "type": "web",
                    "status": "canary" if canary else "active",
                }
            ],
        }
    )


def _snapshot(
    scenario_key: str,
    config,
) -> ScenarioReadinessSnapshot:
    return ScenarioReadinessSnapshot(
        reference=ApplicationScenarioReference(
            key=scenario_key,
            version=1,
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


def _required_providers(config) -> set[str]:
    identities = set()
    if config.object is not None:
        identities.add(f"object:{config.object.provider}")
    for handler in config.handlers:
        if not handler.enabled:
            continue
        if handler.tool:
            identities.add(f"tool:{handler.tool}")
        if handler.type.value == "human" and handler.queue:
            identities.add(f"human_queue:{handler.queue}")
    return identities


def test_alpha_pack_scenario_is_blocked_by_template_maturity():
    scenario_key, config = _pack_scenario("alpha")
    result = evaluate_application_readiness(
        application_key="alpha-app",
        application_name="Alpha",
        revision=1,
        application_status="draft",
        application=_application(scenario_key),
        scenarios=[_snapshot(scenario_key, config)],
        available_provider_identities=_required_providers(config),
    )

    checks = {item.key: item.status for item in result.scenarios[0].checks}
    assert checks["template-maturity"] == "blocked"
    assert result.can_publish is False
    serialized = str(result.model_dump(mode="json"))
    assert config.object is None or config.object.provider not in serialized


def test_beta_pack_scenario_requires_canary_channel():
    scenario_key, config = _pack_scenario("beta")
    available = _required_providers(config)
    active = evaluate_application_readiness(
        application_key="beta-app",
        application_name="Beta",
        revision=1,
        application_status="draft",
        application=_application(scenario_key),
        scenarios=[_snapshot(scenario_key, config)],
        available_provider_identities=available,
    )
    active_checks = {item.key: item.status for item in active.scenarios[0].checks}
    assert active_checks["template-maturity"] == "blocked"

    canary = evaluate_application_readiness(
        application_key="beta-app",
        application_name="Beta",
        revision=1,
        application_status="draft",
        application=_application(scenario_key, canary=True),
        scenarios=[_snapshot(scenario_key, config)],
        available_provider_identities=available,
    )
    canary_checks = {item.key: item.status for item in canary.scenarios[0].checks}
    assert canary_checks["template-maturity"] == "pass"


def test_pack_scenario_provider_requirements_block_missing_configuration():
    scenario_key, config = _pack_scenario("ga")
    application = _application(scenario_key)
    snapshot = _snapshot(scenario_key, config)
    missing = evaluate_application_readiness(
        application_key="provider-app",
        application_name="Provider",
        revision=1,
        application_status="draft",
        application=application,
        scenarios=[snapshot],
        available_provider_identities=set(),
    )
    missing_checks = {item.key: item.status for item in missing.scenarios[0].checks}
    assert missing_checks["provider-capability"] == "blocked"

    configured = evaluate_application_readiness(
        application_key="provider-app",
        application_name="Provider",
        revision=1,
        application_status="draft",
        application=application,
        scenarios=[snapshot],
        available_provider_identities=_required_providers(config),
    )
    configured_checks = {item.key: item.status for item in configured.scenarios[0].checks}
    assert configured_checks["provider-capability"] == "pass"
