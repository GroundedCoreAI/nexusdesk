from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest
from pydantic import ValidationError

from agent_platform.business_capabilities.customer_service.industry_packs.compiler import (
    CompiledApplicationBlueprint,
    IndustryPackCompileError,
    IndustryPackCompiler,
    compile_scenario_template,
    stable_digest,
)
from agent_platform.business_capabilities.customer_service.industry_packs.content_community import (
    CONTENT_COMMUNITY_PACK,
    build_content_community_pack,
)
from agent_platform.business_capabilities.customer_service.industry_packs.local_life import (
    LOCAL_LIFE_PACK,
    build_local_life_pack,
)
from agent_platform.business_capabilities.customer_service.industry_packs.models import (
    ApplicationBlueprint,
    CatalogCategoryTemplate,
    IndustryPackManifest,
    ObjectTemplate,
    ScenarioTemplate,
)
from agent_platform.business_capabilities.customer_service.scenarios.models import (
    ScenarioConfig,
)
from agent_platform.business_capabilities.customer_service.scenarios.simulation import simulate
from agent_platform.business_capabilities.customer_service.service_apps.models import (
    ServiceApplicationConfig,
)


def _object_template(
    *,
    object_template_key: str = "community-account",
    object_type: str = "community_account",
    provider_key: str = "community_account_provider",
) -> ObjectTemplate:
    return ObjectTemplate(
        object_template_key=object_template_key,
        object_type=object_type,
        name="社区账号",
        description="内容社区的用户账号",
        provider_key=provider_key,
        default_mode="required",
        fact_fields=[
            {
                "key": "account_status",
                "label": "账号状态",
                "source": "status",
                "order": 10,
            },
            {
                "key": "registered_at",
                "label": "注册时间",
                "source": "created_at",
                "order": 20,
            },
        ],
        sensitive_fields=["registered_at"],
    )


def _scenario_template(
    *,
    template_key: str = "account-status-query",
    object_template_key: str | None = "community-account",
    config: dict[str, Any] | None = None,
    name: str = "账号状态查询",
) -> ScenarioTemplate:
    return ScenarioTemplate(
        template_key=template_key,
        template_version="1.0.0",
        name=name,
        description="查询当前用户账号状态与注册时间",
        scenario_kind="query",
        execution_template="query",
        maturity="ga",
        catalog_category_key="account-security",
        object_template_key=object_template_key,
        config=config
        or {
            "domain": "内容社区",
            "entries": [
                {
                    "key": "natural-language",
                    "type": "natural_language",
                    "label": "自然语言",
                }
            ],
            "decisions": [],
            "recommendations": [],
            "handlers": [
                {
                    "key": "account-query",
                    "type": "query",
                    "label": "查询账号状态",
                    "tool": "community.account.status",
                }
            ],
            "fallback_order": ["account-query"],
            "matching": {"keywords": ["账号为什么不能登录"], "intents": []},
        },
    )


def _manifest(**overrides: Any) -> IndustryPackManifest:
    values: dict[str, Any] = {
        "schema_version": "v1",
        "pack_key": "content-community",
        "name": "内容社区",
        "description": "账号、内容、会员权益与社区治理服务",
        "pack_version": "1.0.0",
        "maturity": "beta",
        "supported_channels": ["web", "app", "wechat"],
        "catalog_categories": [
            CatalogCategoryTemplate(
                key="account-security",
                name="账号与安全",
                order=10,
            )
        ],
        "object_templates": [_object_template()],
        "scenario_templates": [_scenario_template()],
        "application_blueprint": ApplicationBlueprint(
            application_key="content-community-service",
            name="内容社区服务",
            catalog_category_keys=["account-security"],
            scenario_template_keys=["account-status-query"],
        ),
    }
    values.update(overrides)
    return IndustryPackManifest.model_validate(values)


def test_content_community_scenario_compiles_to_existing_config_with_source_metadata():
    manifest = _manifest()
    compiler = IndustryPackCompiler(manifest)

    config = compiler.compile_scenario("account-status-query")

    assert isinstance(config, ScenarioConfig)
    assert config.name == "账号状态查询"
    assert config.domain == "内容社区"
    assert config.category == "账号与安全"
    assert config.template == "query"
    assert config.object is not None
    assert config.object.type == "community_account"
    assert config.object.provider == "community_account_provider"
    assert config.object.required is True
    assert {fact.key for fact in config.facts} == {"account_status", "registered_at"}
    assert next(fact for fact in config.facts if fact.key == "registered_at").masked is True

    source = config.config["industry_pack"]
    assert source["pack_key"] == "content-community"
    assert source["pack_version"] == "1.0.0"
    assert source["template_key"] == "account-status-query"
    assert source["template_version"] == "1.0.0"
    assert source["template_digest"] == compiler.digest_scenario_template("account-status-query")
    assert source["scenario_kind"] == "query"
    assert source["maturity"] == "ga"
    assert source["catalog_category_key"] == "account-security"

    assert compile_scenario_template(manifest, "account-status-query") == config


def test_missing_scenario_template_is_rejected():
    compiler = IndustryPackCompiler(_manifest())

    with pytest.raises(IndustryPackCompileError, match="scenario template not found: missing"):
        compiler.compile_scenario("missing")


def test_unknown_object_template_is_rejected():
    scenario = _scenario_template(object_template_key="missing-object")
    manifest = _manifest(scenario_templates=[scenario])

    with pytest.raises(
        IndustryPackCompileError,
        match="references unknown object template: missing-object",
    ):
        IndustryPackCompiler(manifest)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        (
            {
                "catalog_categories": [
                    {"key": "account-security", "name": "账号与安全"},
                    {"key": "account-security", "name": "账号安全"},
                ]
            },
            "duplicate catalog category key: account-security",
        ),
        (
            {
                "object_templates": [
                    _object_template(),
                    _object_template(object_type="another_account"),
                ]
            },
            "duplicate object template key: community-account",
        ),
        (
            {
                "scenario_templates": [
                    _scenario_template(),
                    _scenario_template(name="重复场景"),
                ]
            },
            "duplicate scenario template key: account-status-query",
        ),
    ],
)
def test_duplicate_keys_are_rejected(overrides, message):
    manifest = _manifest(**overrides)

    with pytest.raises(IndustryPackCompileError, match=message):
        IndustryPackCompiler(manifest)


def test_template_digest_is_stable_across_mapping_order():
    first = {
        "z": [{"b": 2, "a": 1}],
        "a": {"second": True, "first": "值"},
    }
    second = {
        "a": {"first": "值", "second": True},
        "z": [{"a": 1, "b": 2}],
    }

    assert stable_digest(first) == stable_digest(second)
    assert stable_digest(first).startswith("sha256:")

    manifest = _manifest()
    reordered_payload = deepcopy(manifest.model_dump(mode="json"))
    reordered_payload["scenario_templates"][0]["config"] = {
        key: reordered_payload["scenario_templates"][0]["config"][key]
        for key in reversed(list(reordered_payload["scenario_templates"][0]["config"]))
    }
    reordered = IndustryPackManifest.model_validate(reordered_payload)

    assert IndustryPackCompiler(manifest).digest_scenario_template(
        "account-status-query"
    ) == IndustryPackCompiler(reordered).digest_scenario_template("account-status-query")


def test_scenario_object_override_cannot_change_protected_identity():
    scenario_config = _scenario_template().config
    scenario_config["object"] = {
        "type": "community_account",
        "provider": "another_provider",
        "required": True,
        "mode": "required",
    }
    compiler = IndustryPackCompiler(
        _manifest(scenario_templates=[_scenario_template(config=scenario_config)])
    )

    with pytest.raises(IndustryPackCompileError, match="protected field: provider"):
        compiler.compile_scenario("account-status-query")


def test_application_blueprint_references_must_exist():
    manifest = _manifest(
        application_blueprint=ApplicationBlueprint(
            name="内容社区服务",
            scenario_template_keys=["missing-scenario"],
        )
    )

    with pytest.raises(
        IndustryPackCompileError,
        match="references unknown scenario template: missing-scenario",
    ):
        IndustryPackCompiler(manifest)


def test_manifest_rejects_invalid_versions_and_reserved_metadata():
    with pytest.raises(ValidationError, match="pack_version"):
        _manifest(pack_version="1.0")

    scenario = _scenario_template()
    scenario.config["config"] = {"industry_pack": {"pack_key": "forged"}}
    with pytest.raises(ValidationError, match="reserved key 'industry_pack'"):
        _manifest(scenario_templates=[scenario])


def test_content_community_pack_has_complete_assets_and_maturity_split():
    manifest = build_content_community_pack()

    assert manifest.pack_key == "content-community"
    assert manifest.pack_version == "1.0.0"
    assert len(manifest.catalog_categories) == 6
    assert len(manifest.object_templates) == 6
    assert len(manifest.scenario_templates) == 11
    assert len(manifest.sample_data) == 11
    assert len(manifest.acceptance_cases) == 11

    ga = [item.template_key for item in manifest.scenario_templates if item.maturity == "ga"]
    beta = [item.template_key for item in manifest.scenario_templates if item.maturity == "beta"]
    alpha = [item.template_key for item in manifest.scenario_templates if item.maturity == "alpha"]
    assert ga == [
        "account-status-query",
        "content-status-query",
        "membership-benefit-query",
    ]
    assert len(beta) == 6
    assert alpha == ["account-penalty-appeal", "content-appeal"]
    assert {item.object_type for item in manifest.object_templates} == {
        "community_account",
        "community_content",
        "membership_entitlement",
        "membership_order",
        "governance_case",
        "merchant_collaboration",
    }


def test_content_community_pack_references_and_scenarios_are_complete():
    compiler = IndustryPackCompiler(CONTENT_COMMUNITY_PACK)
    manifest = compiler.manifest
    scenario_keys = {item.template_key for item in manifest.scenario_templates}
    sample_ids = {item.sample_id for item in manifest.sample_data}
    case_ids = {item.case_id for item in manifest.acceptance_cases}

    assert len(compiler.compile_all()) == 11
    for template in manifest.scenario_templates:
        assert template.sample_refs
        assert template.acceptance_case_refs
        assert set(template.sample_refs) <= sample_ids
        assert set(template.acceptance_case_refs) <= case_ids
        assert (
            compiler.compile_scenario(template.template_key).config["industry_pack"]["maturity"]
            == template.maturity.value
        )

    for sample in manifest.sample_data:
        assert sample.scenario_template_key in scenario_keys
    for case in manifest.acceptance_cases:
        assert case.scenario_template_key in scenario_keys


def test_content_community_samples_execute_through_existing_simulator():
    compiler = IndustryPackCompiler(CONTENT_COMMUNITY_PACK)
    samples_by_scenario = {
        sample.scenario_template_key: sample for sample in compiler.manifest.sample_data
    }

    for case in compiler.manifest.acceptance_cases:
        sample = samples_by_scenario[case.scenario_template_key]
        config = compiler.compile_scenario(sample.scenario_template_key)
        trace = simulate(
            sample.scenario_template_key,
            config.name,
            None,
            "draft",
            config,
            sample.as_simulation_request(),
        )

        assert trace.result["status"] == case.then.result_status
        assert trace.handler is not None
        assert trace.handler["type"] == case.then.handler_type.value
        projected_facts = {fact["key"]: fact for fact in trace.facts}
        projected_fact_keys = set(projected_facts)
        assert set(case.then.must_include_facts) <= projected_fact_keys
        for forbidden_fact in case.then.must_not_include:
            if forbidden_fact in projected_facts:
                assert projected_facts[forbidden_fact]["masked"] is True


def test_application_blueprint_compiles_to_existing_service_application_config():
    compiler = IndustryPackCompiler(CONTENT_COMMUNITY_PACK)

    compiled = compiler.compile_application()

    assert isinstance(compiled, CompiledApplicationBlueprint)
    assert isinstance(compiled.application, ServiceApplicationConfig)
    assert compiled.application_key == "content-community-service"
    assert compiled.config is compiled.application
    assert [category.name for category in compiled.application.service_categories] == [
        "账号与安全",
        "内容与创作",
        "会员与权益",
        "社区治理",
        "商家合作",
        "通用服务",
    ]
    assert [scenario.key for scenario in compiled.application.scenarios] == [
        "account-status-query",
        "content-status-query",
        "membership-benefit-query",
    ]
    assert {channel.key for channel in compiled.application.channels} == {
        "web",
        "app",
        "wechat",
        "h5",
    }
    human = next(
        capability for capability in compiled.application.capabilities if capability.type == "human"
    )
    assert human.queue == "content-support"
    assert compiled.industry_pack["pack_key"] == "content-community"
    assert compiled.industry_pack["maturity"] == "beta"
    assert compiled.industry_pack["scenario_template_versions"] == {
        "account-status-query": "1.0.0",
        "content-status-query": "1.0.0",
        "membership-benefit-query": "1.0.0",
    }
    assert compiler.compile_application_config() == compiled.application


def test_application_blueprint_digest_is_deterministic():
    first = IndustryPackCompiler(CONTENT_COMMUNITY_PACK).compile_application()
    second = IndustryPackCompiler(build_content_community_pack()).compile_application()

    assert first == second
    assert first.digest == second.digest
    assert first.digest.startswith("sha256:")
    assert first.industry_pack["blueprint_digest"] == stable_digest(
        CONTENT_COMMUNITY_PACK.application_blueprint
    )


def test_application_blueprint_version_mismatch_is_rejected():
    manifest = build_content_community_pack()
    manifest.application_blueprint.scenario_template_versions["account-status-query"] = "9.9.9"

    with pytest.raises(
        IndustryPackCompileError,
        match="version mismatch for scenario template 'account-status-query'",
    ):
        IndustryPackCompiler(manifest)


def test_application_blueprint_requires_human_capability_for_human_handlers():
    manifest = build_content_community_pack()
    manifest.application_blueprint.capabilities = [
        capability
        for capability in manifest.application_blueprint.capabilities
        if capability.type.value != "human"
    ]

    with pytest.raises(
        IndustryPackCompileError,
        match="must declare an enabled human capability",
    ):
        IndustryPackCompiler(manifest).compile_application()


def test_sample_unknown_fact_reference_is_rejected():
    manifest = build_content_community_pack()
    sample = next(
        item for item in manifest.sample_data if item.sample_id == "sample-account-status-query"
    )
    sample.object.facts["unknown_fact"] = "value"

    with pytest.raises(
        IndustryPackCompileError,
        match="sample 'sample-account-status-query' references unknown fact fields: unknown_fact",
    ):
        IndustryPackCompiler(manifest)


def test_acceptance_unknown_fact_reference_is_rejected():
    manifest = build_content_community_pack()
    case = next(
        item for item in manifest.acceptance_cases if item.case_id == "case-account-status-query"
    )
    case.then.must_include_facts.append("unknown_fact")

    with pytest.raises(
        IndustryPackCompileError,
        match="acceptance case 'case-account-status-query' references unknown fact fields",
    ):
        IndustryPackCompiler(manifest)


def test_sample_unknown_scenario_reference_is_rejected():
    manifest = build_content_community_pack()
    manifest.sample_data[0].scenario_template_key = "missing-scenario"

    with pytest.raises(
        IndustryPackCompileError,
        match="sample 'sample-account-status-query' references unknown scenario template",
    ):
        IndustryPackCompiler(manifest)


def test_local_life_pack_has_required_assets_and_maturity_split():
    manifest = build_local_life_pack()

    assert manifest.pack_key == "local-life"
    assert manifest.pack_version == "1.0.0"
    assert len(manifest.catalog_categories) == 5
    assert len(manifest.object_templates) == 4
    assert len(manifest.scenario_templates) == 6
    assert len(manifest.sample_data) == 6
    assert len(manifest.acceptance_cases) == 6
    assert {item.object_type for item in manifest.object_templates} == {
        "local_life_order",
        "reservation_record",
        "refund_after_sales",
        "merchant_store",
    }

    scenario_keys = {item.template_key for item in manifest.scenario_templates}
    assert {
        "order-status-query",
        "reservation-progress-query",
        "fulfillment-exception-diagnosis",
        "refund-after-sales",
    } <= scenario_keys

    ga = [item.template_key for item in manifest.scenario_templates if item.maturity == "ga"]
    beta = [item.template_key for item in manifest.scenario_templates if item.maturity == "beta"]
    alpha = [item.template_key for item in manifest.scenario_templates if item.maturity == "alpha"]
    assert ga == ["order-status-query", "reservation-progress-query"]
    assert len(beta) == 3
    assert alpha == ["refund-after-sales"]


def test_local_life_required_scenarios_compile_with_existing_contract():
    compiler = IndustryPackCompiler(LOCAL_LIFE_PACK)
    required_scenarios = {
        "order-status-query": "query",
        "reservation-progress-query": "query",
        "fulfillment-exception-diagnosis": "consult",
        "refund-after-sales": "action",
    }

    for template_key, execution_template in required_scenarios.items():
        config = compiler.compile_scenario(template_key)

        assert isinstance(config, ScenarioConfig)
        assert config.template == execution_template
        assert config.config["industry_pack"]["pack_key"] == "local-life"
        assert config.config["industry_pack"]["template_key"] == template_key
        assert config.object is not None


def test_local_life_action_requires_confirmation_and_human_fallback():
    compiler = IndustryPackCompiler(LOCAL_LIFE_PACK)
    config = compiler.compile_scenario("refund-after-sales")
    action_handler = next(handler for handler in config.handlers if handler.type == "action")
    human_handler = next(handler for handler in config.handlers if handler.type == "human")

    assert any(decision.kind == "confirm_action" for decision in config.decisions)
    assert action_handler.config["requires_confirmation"] is True
    assert human_handler.queue == "local-life-after-sales"

    sample = next(
        item
        for item in compiler.manifest.sample_data
        if item.sample_id == "sample-refund-after-sales"
    )
    trace = simulate(
        "refund-after-sales",
        config.name,
        None,
        "draft",
        config,
        sample.as_simulation_request(),
    )
    assert trace.result["status"] == "needs_input"
    assert trace.result["reason"] == "action_confirmation_required"
    assert trace.handler is not None
    assert trace.handler["type"] == "action"


def test_local_life_application_blueprint_compiles_to_existing_config():
    compiler = IndustryPackCompiler(LOCAL_LIFE_PACK)
    compiled = compiler.compile_application()

    assert compiled.application_key == "local-life-service"
    assert isinstance(compiled.application, ServiceApplicationConfig)
    assert [category.name for category in compiled.application.service_categories] == [
        "订单与履约",
        "预约与到店",
        "退款与售后",
        "商家与门店",
        "通用服务",
    ]
    assert [scenario.key for scenario in compiled.application.scenarios] == [
        "order-status-query",
        "reservation-progress-query",
    ]
    assert {channel.key for channel in compiled.application.channels} == {
        "web",
        "app",
        "wechat",
        "h5",
    }
    human_queues = {
        capability.queue
        for capability in compiled.application.capabilities
        if capability.type == "human"
    }
    assert human_queues == {"local-life-support", "local-life-after-sales"}
    assert compiled.industry_pack["pack_key"] == "local-life"
    assert compiled.industry_pack["maturity"] == "beta"


def test_local_life_references_and_samples_are_complete():
    compiler = IndustryPackCompiler(LOCAL_LIFE_PACK)
    manifest = compiler.manifest
    scenario_keys = {item.template_key for item in manifest.scenario_templates}
    sample_ids = {item.sample_id for item in manifest.sample_data}
    case_ids = {item.case_id for item in manifest.acceptance_cases}

    assert len(compiler.compile_all()) == 6
    for template in manifest.scenario_templates:
        assert template.template_key in scenario_keys
        assert set(template.sample_refs) <= sample_ids
        assert set(template.acceptance_case_refs) <= case_ids
    for object_template in manifest.object_templates:
        assert object_template.sample_refs
        assert set(object_template.sample_refs) <= sample_ids

    samples_by_scenario = {sample.scenario_template_key: sample for sample in manifest.sample_data}
    for case in manifest.acceptance_cases:
        sample = samples_by_scenario[case.scenario_template_key]
        config = compiler.compile_scenario(case.scenario_template_key)
        trace = simulate(
            case.scenario_template_key,
            config.name,
            None,
            "draft",
            config,
            sample.as_simulation_request(),
        )
        projected_facts = {fact["key"]: fact for fact in trace.facts}

        assert trace.result["status"] == case.then.result_status
        assert trace.handler is not None
        assert trace.handler["type"] == case.then.handler_type.value
        assert set(case.then.must_include_facts) <= set(projected_facts)
        for forbidden_fact in case.then.must_not_include:
            if forbidden_fact in projected_facts:
                assert projected_facts[forbidden_fact]["masked"] is True


def test_local_life_pack_and_application_digests_are_deterministic():
    first_compiler = IndustryPackCompiler(LOCAL_LIFE_PACK)
    second_compiler = IndustryPackCompiler(build_local_life_pack())
    first_application = first_compiler.compile_application()
    second_application = second_compiler.compile_application()

    assert first_compiler.digest == second_compiler.digest
    assert first_application == second_application
    assert first_application.digest == second_application.digest
    assert first_application.digest.startswith("sha256:")


def test_local_life_pack_does_not_change_content_community_pack():
    content_before = IndustryPackCompiler(CONTENT_COMMUNITY_PACK)
    content_digest_before = content_before.digest

    local_life = IndustryPackCompiler(build_local_life_pack())
    assert len(local_life.compile_all()) == 6
    assert local_life.compile_application().application_key == "local-life-service"

    content_after = IndustryPackCompiler(CONTENT_COMMUNITY_PACK)
    assert content_after.digest == content_digest_before
    assert len(content_after.compile_all()) == 11
    assert len(content_after.manifest.object_templates) == 6
    assert content_after.manifest.pack_key == "content-community"
    assert content_after.compile_application().application_key == "content-community-service"
