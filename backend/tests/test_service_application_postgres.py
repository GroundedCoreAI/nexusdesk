"""PostgreSQL integration tests for versioned service applications."""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from test_platform_postgres import create_agent
from test_platform_postgres import platform as _platform

from agent_platform.extension_contracts import BusinessScope

platform = _platform
pytestmark = [pytest.mark.asyncio, pytest.mark.postgres]


def _config(*, name: str = "购物消费服务应用", agent_id: str | None = None) -> dict:
    capabilities = [
        {
            "key": "direct",
            "type": "direct",
            "label": "Direct",
            "config": {"reply": "请提供订单号。"},
        }
    ]
    if agent_id:
        capabilities.append(
            {
                "key": "shopping-agent",
                "type": "agent",
                "label": "购物消费助手",
                "agent_id": agent_id,
            }
        )
    return {
        "name": name,
        "description": "订单、物流、售后和发票服务的统一应用",
        "scenarios": [{"key": "query-orders"}],
        "capabilities": capabilities,
        "default_execution_order": ["deterministic", "action", "agent", "human"],
        "channels": [
            {"key": "web", "name": "官网帮助中心", "type": "web"},
        ],
    }


async def _create_application(client, key: str, config: dict) -> dict:
    response = await client.post(
        "/api/v1/service-apps",
        json={"key": key, "config": config},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_application_publish_pins_scenario_and_agent_and_records_application_trace(
    platform,
):
    client, services, settings = platform
    agent, _ = await create_agent(client)
    await services.groups.business.scenarios.seed_defaults(settings.tenant_id)
    key = "consumer-" + uuid4().hex[:10]
    created = await _create_application(
        client,
        key,
        _config(agent_id=agent["id"]),
    )
    assert created["status"] == "draft"
    assert created["scenario_count"] == 1

    published = await client.post(
        f"/api/v1/service-apps/{key}/publish",
        json={"revision": created["revision"]},
    )
    assert published.status_code == 200, published.text
    release = published.json()
    assert release["version"] == 1
    assert release["config"]["scenarios"][0]["version"] == 3
    agent_capability = next(
        item for item in release["config"]["capabilities"] if item["type"] == "agent"
    )
    assert agent_capability["agent_version"] == 1
    assert agent_capability["agent_name"] == "售后客服"

    simulation = await client.post(
        f"/api/v1/service-apps/{key}/simulate",
        json={
            "message": "我的订单到哪了？",
            "scenario_key": "query-orders",
            "application_version": 1,
        },
    )
    assert simulation.status_code == 200, simulation.text
    trace = simulation.json()
    assert trace["application_key"] == key
    assert trace["application_version"] == 1
    assert trace["scenario_key"] == "query-orders"
    assert trace["scenario_version"] == 3
    assert trace["trace_id"]

    traces = await client.get(f"/api/v1/service-apps/{key}/traces")
    assert traces.status_code == 200, traces.text
    items = traces.json()["items"]
    assert len(items) == 1
    assert items[0]["trace"]["application"]["key"] == key
    assert items[0]["scenario_version"] == 3

    versions = await client.get(f"/api/v1/service-apps/{key}/versions")
    assert versions.status_code == 200
    assert versions.json()["published_version"] == 1
    assert versions.json()["items"][0]["config"]["scenarios"][0]["version"] == 3


async def test_application_update_publish_rollback_and_scope(platform):
    client, services, settings = platform
    await services.groups.business.scenarios.seed_defaults(settings.tenant_id)
    key = "rollback-" + uuid4().hex[:10]
    created = await _create_application(client, key, _config())
    first = await client.post(
        f"/api/v1/service-apps/{key}/publish",
        json={"revision": created["revision"]},
    )
    assert first.status_code == 200, first.text
    first_payload = first.json()

    updated = await client.put(
        f"/api/v1/service-apps/{key}",
        json={
            "config": _config(name="购物消费服务应用 V2"),
            "revision": first_payload["revision"],
        },
    )
    assert updated.status_code == 200, updated.text
    second = await client.post(
        f"/api/v1/service-apps/{key}/publish",
        json={"revision": updated.json()["revision"]},
    )
    assert second.status_code == 200, second.text
    assert second.json()["version"] == 2

    rolled_back = await client.post(
        f"/api/v1/service-apps/{key}/rollback",
        json={"version": 1, "revision": second.json()["revision"]},
    )
    assert rolled_back.status_code == 200, rolled_back.text
    assert rolled_back.json()["name"] == "购物消费服务应用"
    assert rolled_back.json()["published_version"] == 1

    applications = services.groups.business.service_apps
    own_scope = BusinessScope(
        tenant_id=settings.tenant_id,
        business_id="customer-service",
        workspace_id="default",
    )
    other_workspace = BusinessScope(
        tenant_id=settings.tenant_id,
        business_id="customer-service",
        workspace_id="another-workspace",
    )
    other_tenant = BusinessScope(
        tenant_id="another-tenant",
        business_id="customer-service",
        workspace_id="default",
    )
    assert len((await applications.list(settings.tenant_id, scope=own_scope))["items"]) == 1
    assert (
        await applications.list(settings.tenant_id, scope=other_workspace)
    )["items"] == []
    assert (await applications.list("another-tenant", scope=other_tenant))["items"] == []


async def test_seed_default_application_is_idempotent(platform):
    _client, services, settings = platform
    await services.groups.business.scenarios.seed_defaults(settings.tenant_id)
    applications = services.groups.business.service_apps

    first = await applications.seed_defaults(settings.tenant_id)
    second = await applications.seed_defaults(settings.tenant_id)

    assert first == {"applications": 1}
    assert second == {"applications": 0}
    detail = await applications.get(settings.tenant_id, "consumer-service")
    assert detail["key"] == "consumer-service"
    assert detail["scenario_count"] == 6
    assert {channel["key"] for channel in detail["config"]["channels"]} == {
        "web",
        "wecom",
        "open-api",
        "h5",
    }
    assert [item["name"] for item in detail["config"]["service_categories"]] == [
        "订单服务",
        "售后服务",
        "发票服务",
        "规则与知识",
        "投诉反馈",
    ]


async def test_service_catalog_reorder_rename_and_merge_update_scenario_drafts(platform):
    client, services, settings = platform
    await services.groups.business.scenarios.seed_defaults(settings.tenant_id)
    await services.groups.business.service_apps.seed_defaults(settings.tenant_id)
    detail = (
        await client.get("/api/v1/service-apps/consumer-service")
    ).json()

    response = await client.put(
        "/api/v1/service-apps/consumer-service/service-catalog",
        json={
            "revision": detail["revision"],
            "categories": [
                {"name": "投诉反馈", "order": 1},
                {"name": "交易服务", "order": 2},
                {"name": "规则与知识", "order": 3},
                {"name": "发票服务", "order": 4},
            ],
            "category_changes": {
                "订单服务": "交易服务",
                "售后服务": "交易服务",
            },
        },
    )
    assert response.status_code == 200, response.text
    updated = response.json()
    assert [item["name"] for item in updated["config"]["service_categories"]] == [
        "投诉反馈",
        "交易服务",
        "规则与知识",
        "发票服务",
    ]
    assert [item["order"] for item in updated["config"]["service_categories"]] == [
        10,
        20,
        30,
        40,
    ]

    for key in ("query-orders", "track-logistics", "after-sales"):
        scenario = (
            await client.get(f"/api/v1/service-scenarios/{key}")
        ).json()
        assert scenario["config"]["category"] == "交易服务"

    stale = await client.put(
        "/api/v1/service-apps/consumer-service/service-catalog",
        json={
            "revision": detail["revision"],
            "categories": [
                {"name": "交易服务", "order": 1},
                {"name": "规则与知识", "order": 2},
                {"name": "发票服务", "order": 3},
                {"name": "投诉反馈", "order": 4},
            ],
            "category_changes": {},
        },
    )
    assert stale.status_code == 409
    assert stale.json()["detail"] == "service_application_revision_conflict"

    missing_reference = await client.put(
        "/api/v1/service-apps/consumer-service/service-catalog",
        json={
            "revision": updated["revision"],
            "categories": [{"name": "交易服务", "order": 1}],
            "category_changes": {},
        },
    )
    assert missing_reference.status_code == 422
    assert missing_reference.json()["detail"] == "service_catalog_category_required"


async def test_application_archive_hides_requires_offline_and_restores(platform):
    client, services, settings = platform
    await services.groups.business.scenarios.seed_defaults(settings.tenant_id)
    key = "archive-" + uuid4().hex[:10]
    created = await _create_application(client, key, _config())

    # A draft that never shipped can be archived straight away.
    archived = await client.post(
        f"/api/v1/service-apps/{key}/archive",
        json={"revision": created["revision"]},
    )
    assert archived.status_code == 200, archived.text
    assert archived.json()["archived"] is True
    assert (await client.get("/api/v1/service-apps")).json()["items"] == []
    archived_page = (await client.get("/api/v1/service-apps?archived=true")).json()
    assert [item["key"] for item in archived_page["items"]] == [key]
    # Archived rows are invisible to every direct read path.
    assert (await client.get(f"/api/v1/service-apps/{key}")).status_code == 404

    restored = await client.post(f"/api/v1/service-apps/{key}/restore")
    assert restored.status_code == 200, restored.text
    assert restored.json()["archived"] is False
    assert (await client.get(f"/api/v1/service-apps/{key}")).status_code == 200
    # Restoring something that is not archived is a missing row, not a silent no-op.
    assert (await client.post(f"/api/v1/service-apps/{key}/restore")).status_code == 404

    published = await client.post(
        f"/api/v1/service-apps/{key}/publish",
        json={"revision": restored.json()["revision"]},
    )
    assert published.status_code == 200, published.text
    # A live release has to be taken offline first; archiving must not hide it.
    blocked = await client.post(
        f"/api/v1/service-apps/{key}/archive",
        json={"revision": published.json()["revision"]},
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"] == "service_application_must_be_offline"

    offline = await client.post(
        f"/api/v1/service-apps/{key}/status",
        json={"status": "offline", "revision": published.json()["revision"]},
    )
    assert offline.status_code == 200, offline.text
    final = await client.post(
        f"/api/v1/service-apps/{key}/archive",
        json={"revision": offline.json()["revision"]},
    )
    assert final.status_code == 200, final.text
    # Archiving hides the row; it never drops the release it points at.
    assert final.json()["published_version"] == published.json()["version"]


async def test_application_purge_needs_archive_and_drops_version_history(platform):
    client, services, settings = platform
    await services.groups.business.scenarios.seed_defaults(settings.tenant_id)
    key = "purge-" + uuid4().hex[:10]
    created = await _create_application(client, key, _config())

    # A live row is not deletable: purge only touches what archive already hid.
    refused = await client.delete(f"/api/v1/service-apps/{key}")
    assert refused.status_code == 404
    assert refused.json()["detail"] == "service_application_archived_not_found"

    published = await client.post(
        f"/api/v1/service-apps/{key}/publish",
        json={"revision": created["revision"]},
    )
    assert published.status_code == 200, published.text
    offline = await client.post(
        f"/api/v1/service-apps/{key}/status",
        json={"status": "offline", "revision": published.json()["revision"]},
    )
    assert offline.status_code == 200, offline.text
    archived = await client.post(
        f"/api/v1/service-apps/{key}/archive",
        json={"revision": offline.json()["revision"]},
    )
    assert archived.status_code == 200, archived.text

    engine = services.repository.engine

    async def version_rows() -> int:
        async with engine.connect() as connection:
            return await connection.scalar(
                text(
                    "SELECT count(*) FROM service_application_versions "
                    "WHERE tenant_id=:tenant AND application_id=:id"
                ),
                {"tenant": settings.tenant_id, "id": UUID(created["id"])},
            )

    assert await version_rows() >= 1

    purged = await client.delete(f"/api/v1/service-apps/{key}")
    assert purged.status_code == 200, purged.text
    assert purged.json() == {"key": key, "deleted": True}
    assert (await client.get("/api/v1/service-apps?archived=true")).json()["items"] == []
    assert (await client.get(f"/api/v1/service-apps/{key}")).status_code == 404
    # Second purge is a missing row, not a silent success.
    assert (await client.delete(f"/api/v1/service-apps/{key}")).status_code == 404
    # Version snapshots go with the application; the FK cascades.
    assert await version_rows() == 0
    # And the key is free again.
    again = await _create_application(client, key, _config())
    assert again["revision"] == 1
