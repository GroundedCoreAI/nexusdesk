"""Provider registry and industry-pack installation integration tests."""

from __future__ import annotations

from copy import deepcopy
from uuid import UUID

import pytest
from test_platform_postgres import platform as _platform

from agent_platform.business_capabilities.customer_service.industry_packs.content_community import (
    build_content_community_pack,
)
from agent_platform.business_capabilities.customer_service.industry_packs.installations import (
    IndustryPackService,
)
from agent_platform.business_capabilities.customer_service.industry_packs.runtime_models import (
    IndustryPackUpgradeInput,
    IndustryPackUpgradePreviewRequest,
)
from agent_platform.extension_contracts import BusinessScope

platform = _platform
pytestmark = [pytest.mark.asyncio, pytest.mark.postgres]


async def test_provider_registry_crud_and_revision_conflict(platform):
    client, _services, _settings = platform
    created = await client.post(
        "/api/v1/service-providers",
        json={
            "key": "orders.read",
            "kind": "object",
            "name": "订单数据",
            "description": "订单查询数据源",
            "enabled": False,
            "config": {"endpoint": "internal"},
        },
    )
    assert created.status_code == 201, created.text
    provider = created.json()
    assert provider["key"] == "orders.read"
    assert provider["revision"] == 1

    listed = await client.get("/api/v1/service-providers?kind=object")
    assert listed.status_code == 200, listed.text
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["key"] == "orders.read"

    updated = await client.put(
        "/api/v1/service-providers/object/orders.read",
        json={
            "key": "orders.read",
            "kind": "object",
            "name": "订单主数据",
            "description": "订单查询数据源",
            "enabled": True,
            "config": {"endpoint": "internal"},
            "revision": 1,
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["enabled"] is True
    assert updated.json()["revision"] == 2

    stale = await client.put(
        "/api/v1/service-providers/object/orders.read",
        json={
            "key": "orders.read",
            "kind": "object",
            "name": "过期修改",
            "enabled": False,
            "config": {},
            "revision": 1,
        },
    )
    assert stale.status_code == 409
    assert stale.json()["detail"] == "service_provider_missing_or_revision_conflict"


async def test_install_pack_is_idempotent_and_creates_drafts_and_provider_requirements(platform):
    client, _services, _settings = platform

    installed = await client.post(
        "/api/v1/industry-packs/content-community/install",
        json={"install_scenarios": True},
    )
    assert installed.status_code == 201, installed.text
    payload = installed.json()
    assert payload["created"] is True
    installation = payload["installation"]
    assert installation["application_key"] == "content-community-service"
    assert installation["status"] == "installed"
    assert len(installation["installed_scenarios"]) == 11

    repeated = await client.post(
        "/api/v1/industry-packs/content-community/install",
        json={},
    )
    assert repeated.status_code == 201, repeated.text
    assert repeated.json()["created"] is False

    scenarios = await client.get("/api/v1/service-scenarios")
    assert scenarios.status_code == 200, scenarios.text
    assert scenarios.json()["total"] == 11
    assert all(item["status"] == "draft" for item in scenarios.json()["items"])

    application = await client.get("/api/v1/service-apps/content-community-service")
    assert application.status_code == 200, application.text
    assert application.json()["status"] == "draft"
    assert application.json()["scenario_count"] == 3

    providers = await client.get("/api/v1/service-providers")
    assert providers.status_code == 200, providers.text
    assert providers.json()["total"] > 0
    assert all(item["enabled"] is False for item in providers.json()["items"])

    readiness = await client.get("/api/v1/service-apps/content-community-service/readiness")
    assert readiness.status_code == 200, readiness.text
    checks = {item["key"]: item["status"] for item in readiness.json()["scenarios"][0]["checks"]}
    assert checks["provider-capability"] == "blocked"
    assert checks["template-maturity"] == "pass"

    alpha_scenario = await client.get("/api/v1/service-scenarios/content-appeal")
    assert alpha_scenario.status_code == 200, alpha_scenario.text
    tampered_config = deepcopy(alpha_scenario.json()["config"])
    tampered_config["config"]["industry_pack"]["maturity"] = "ga"
    tampered = await client.put(
        "/api/v1/service-scenarios/content-appeal",
        json={
            "config": tampered_config,
            "revision": alpha_scenario.json()["revision"],
        },
    )
    assert tampered.status_code == 409
    assert tampered.json()["detail"] == "scenario_industry_pack_metadata_immutable"

    alpha = await client.post(
        "/api/v1/service-scenarios/content-appeal/publish",
        json={"revision": 1},
    )
    assert alpha.status_code == 409
    assert alpha.json()["detail"] == "scenario_alpha_publish_forbidden"


async def test_upgrade_preview_and_apply_merge_template_with_local_edit(platform):
    client, services, settings = platform
    installed = await client.post(
        "/api/v1/industry-packs/content-community/install",
        json={"install_scenarios": False},
    )
    assert installed.status_code == 201, installed.text
    installation = installed.json()["installation"]

    current = await client.get("/api/v1/service-scenarios/account-status-query")
    assert current.status_code == 200, current.text
    scenario = current.json()
    local_config = dict(scenario["config"])
    local_config["description"] = "租户自定义的账号状态说明"
    updated = await client.put(
        "/api/v1/service-scenarios/account-status-query",
        json={"config": local_config, "revision": scenario["revision"]},
    )
    assert updated.status_code == 200, updated.text

    target_manifest = deepcopy(build_content_community_pack())
    target_manifest.pack_version = "1.1.0"
    for template in target_manifest.scenario_templates:
        template.template_version = "1.1.0"
        if template.template_key == "account-status-query":
            template.name = "账号状态查询（新版）"
            template.config["handlers"][0]["tool"] = "community.account.status.v2"
    assert target_manifest.application_blueprint is not None
    for key in target_manifest.application_blueprint.scenario_template_versions:
        target_manifest.application_blueprint.scenario_template_versions[key] = "1.1.0"

    scope = BusinessScope(
        tenant_id=settings.tenant_id,
        business_id="customer-service",
        workspace_id="default",
    )
    pack_service = IndustryPackService(
        services.repository.engine,
        services.groups.business.providers,
        packs={"content-community": target_manifest},
    )
    preview = await pack_service.preview_upgrade(
        settings.tenant_id,
        "platform-admin",
        UUID(installation["id"]),
        IndustryPackUpgradePreviewRequest(target_version="1.1.0"),
        scope=scope,
    )
    assert preview["status"] == "clean", preview
    target_preview = next(
        item for item in preview["scenarios"] if item["template_key"] == "account-status-query"
    )
    assert target_preview["status"] == "clean"
    assert target_preview["merged_config"]["name"] == "账号状态查询（新版）"
    assert target_preview["merged_config"]["description"] == "租户自定义的账号状态说明"

    applied = await pack_service.apply_upgrade(
        settings.tenant_id,
        "platform-admin",
        UUID(installation["id"]),
        IndustryPackUpgradeInput(
            preview_id=UUID(preview["id"]),
            target_version="1.1.0",
        ),
        scope=scope,
    )
    assert applied["applied"] is True
    assert applied["installation"]["pack_version"] == "1.1.0"

    upgraded = await client.get("/api/v1/service-scenarios/account-status-query")
    assert upgraded.status_code == 200, upgraded.text
    assert upgraded.json()["config"]["name"] == "账号状态查询（新版）"
    assert upgraded.json()["config"]["description"] == "租户自定义的账号状态说明"
    upgraded_providers = await client.get(
        "/api/v1/service-providers?kind=tool&q=community.account.status.v2"
    )
    assert upgraded_providers.status_code == 200, upgraded_providers.text
    assert upgraded_providers.json()["total"] == 1
    assert upgraded_providers.json()["items"][0]["enabled"] is False


async def test_install_requires_admin(platform):
    client, _services, _settings = platform
    viewer_headers = {"Authorization": "Bearer platform-viewer"}
    denied = await client.post(
        "/api/v1/industry-packs/local-life/install",
        json={},
        headers=viewer_headers,
    )
    assert denied.status_code == 403
