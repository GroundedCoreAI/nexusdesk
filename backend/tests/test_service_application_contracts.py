from uuid import uuid4

import pytest
from pydantic import ValidationError

from agent_platform.business_capabilities.customer_service.service_apps.models import (
    ApplicationCapability,
    ApplicationChannel,
    ApplicationScenarioReference,
    ApplicationServiceCategory,
    ApplicationSimulationRequest,
    ServiceApplicationConfig,
    ServiceCatalogUpdateRequest,
)


def _config(**overrides) -> ServiceApplicationConfig:
    values = {
        "name": "购物消费服务应用",
        "description": "统一受理订单、物流和售后问题",
        "scenarios": [ApplicationScenarioReference(key="query-orders")],
        "capabilities": [
            ApplicationCapability(
                key="direct",
                type="direct",
                label="Direct",
                config={"reply": "请提供订单号。"},
            )
        ],
        "channels": [
            ApplicationChannel(key="web", name="官网帮助中心", type="web"),
        ],
    }
    values.update(overrides)
    return ServiceApplicationConfig(**values)


def test_application_config_references_scenarios_instead_of_copying_them():
    config = _config()

    assert config.scenarios[0].key == "query-orders"
    assert config.scenarios[0].version is None
    assert config.capabilities[0].type.value == "direct"
    assert config.channels[0].status.value == "active"


@pytest.mark.parametrize(
    "field,item",
    [
        ("scenarios", ApplicationScenarioReference(key="query-orders")),
        (
            "capabilities",
            ApplicationCapability(key="direct", type="direct", label="Direct"),
        ),
        ("channels", ApplicationChannel(key="web", name="Web", type="web")),
    ],
)
def test_application_collection_keys_must_be_unique(field, item):
    with pytest.raises(ValidationError, match=f"duplicate .* key: {item.key}"):
        _config(**{field: [item, item]})


def test_agent_capability_requires_agent_reference_and_rejects_cross_type_references():
    with pytest.raises(ValidationError, match="agent capability requires agent_id"):
        ApplicationCapability(key="assistant", type="agent", label="助手")

    with pytest.raises(ValidationError, match="only agent capabilities"):
        ApplicationCapability(
            key="knowledge",
            type="knowledge",
            label="知识",
            agent_id=uuid4(),
        )


def test_execution_order_must_not_contain_duplicates_or_blanks():
    with pytest.raises(ValidationError, match="duplicate execution stage"):
        _config(default_execution_order=["deterministic", "deterministic"])
    with pytest.raises(ValidationError, match="must not contain blank"):
        _config(default_execution_order=["deterministic", ""])


def test_application_simulation_can_select_scenario_and_snapshot_version():
    request = ApplicationSimulationRequest(
        message="我的订单到哪了？",
        scenario_key="track-logistics",
        application_version=8,
    )

    assert request.scenario_key == "track-logistics"
    assert request.application_version == 8

    with pytest.raises(ValidationError):
        ApplicationSimulationRequest(message="x", scenario_key="Track Logistics")
    with pytest.raises(ValidationError):
        ApplicationSimulationRequest(message="x", application_version=0)


def test_service_categories_are_unique_and_keep_application_order():
    config = _config(
        service_categories=[
            ApplicationServiceCategory(name="订单服务", order=10),
            ApplicationServiceCategory(name="售后服务", order=20),
        ]
    )

    assert [item.name for item in config.service_categories] == ["订单服务", "售后服务"]

    with pytest.raises(ValidationError, match="duplicate service category"):
        _config(
            service_categories=[
                ApplicationServiceCategory(name="订单服务", order=10),
                ApplicationServiceCategory(name="订单服务", order=20),
            ]
        )


def test_catalog_update_requires_existing_targets_and_rejects_self_merge():
    update = ServiceCatalogUpdateRequest(
        revision=3,
        categories=[
            ApplicationServiceCategory(name="交易服务", order=10),
            ApplicationServiceCategory(name="售后服务", order=20),
        ],
        category_changes={"订单服务": "交易服务"},
    )
    assert update.category_changes == {"订单服务": "交易服务"}

    with pytest.raises(ValidationError, match="target is not in the catalog"):
        ServiceCatalogUpdateRequest(
            revision=3,
            categories=[ApplicationServiceCategory(name="交易服务", order=10)],
            category_changes={"订单服务": "不存在"},
        )
    with pytest.raises(ValidationError, match="cannot map a category to itself"):
        ServiceCatalogUpdateRequest(
            revision=3,
            categories=[ApplicationServiceCategory(name="订单服务", order=10)],
            category_changes={"订单服务": "订单服务"},
        )
