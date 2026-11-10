import pytest
from sqlalchemy import text
from test_platform_postgres import execute_next
from test_platform_postgres import platform as _platform_fixture

from agent_platform.applications import seed, seed_demo_packs
from agent_platform.applications.seed_demo_packs import DEMO_PACK_KEYS
from agent_platform.business_capabilities.customer_service.industry_packs import (
    build_creator_pack,
    build_gaming_pack,
    build_mobility_pack,
    build_shopping_pack,
)

platform = _platform_fixture
pytestmark = [pytest.mark.asyncio, pytest.mark.postgres]

# The quickstart stack promotes these packs on first boot; derive expectations
# from the manifests so adding or resizing a pack does not break this test.
DEMO_MANIFESTS = {
    manifest.pack_key: manifest
    for manifest in (
        build_shopping_pack(),
        build_gaming_pack(),
        build_creator_pack(),
        build_mobility_pack(),
    )
}
EXPECTED_SCENARIOS = sum(len(DEMO_MANIFESTS[key].scenario_templates) for key in DEMO_PACK_KEYS)


async def test_quickstart_seed_is_repeatable_and_scenarios_work(platform, monkeypatch):
    client, services, settings = platform
    monkeypatch.setattr(seed, "Settings", lambda: settings)
    monkeypatch.setattr(seed_demo_packs, "Settings", lambda: settings)
    # First boot runs two independent seeders: the workspace sample and the demo
    # industry packs. Both must be idempotent, so every one runs twice.
    await seed.main()
    await seed.main()
    await seed_demo_packs.main()
    await seed_demo_packs.main()
    async with services.groups.runtime.engine.connect() as connection:
        for table in ("agents", "knowledge_bases", "gateway_profiles", "runtime_conversations"):
            count = await connection.scalar(
                text(f"SELECT count(*) FROM {table} WHERE tenant_id=:tenant"),
                {"tenant": settings.tenant_id},
            )
            assert count == 1, table
        scenario_count = await connection.scalar(
            text("SELECT count(*) FROM service_scenarios WHERE tenant_id=:tenant"),
            {"tenant": settings.tenant_id},
        )
        assert scenario_count == EXPECTED_SCENARIOS
        application_count = await connection.scalar(
            text("SELECT count(*) FROM service_applications WHERE tenant_id=:tenant"),
            {"tenant": settings.tenant_id},
        )
        assert application_count == len(DEMO_PACK_KEYS)
        cid = await connection.scalar(
            text("SELECT id FROM runtime_conversations WHERE tenant_id=:tenant"),
            {"tenant": settings.tenant_id},
        )
    scenarios = (await client.get("/api/v1/service-scenarios")).json()
    assert scenarios["total"] == EXPECTED_SCENARIOS
    assert all(item["status"] == "published" for item in scenarios["items"])
    applications = (await client.get("/api/v1/service-apps")).json()
    assert applications["total"] == len(DEMO_PACK_KEYS)
    for pack_key in DEMO_PACK_KEYS:
        deployed = await client.get(f"/api/v1/service-apps/{pack_key}-service")
        assert deployed.status_code == 200, (pack_key, deployed.text)
    response = await client.post(
        f"/api/v1/conversations/{cid}/messages", json={"content": "发货需要多久？"}
    )
    assert response.status_code == 202, response.text
    result = await execute_next(services, settings)
    assert result["status"] == "completed", result
    assert "48" in result["output"]
    response = await client.post(
        f"/api/v1/conversations/{cid}/messages", json={"content": "请创建售后工单"}
    )
    assert response.status_code == 202, response.text
    result = await execute_next(services, settings)
    assert result["status"] == "completed", result
    assert (await client.get("/api/v1/tickets")).json() == []
    detail = (await client.get(f"/api/v1/conversations/{cid}")).json()
    action_id = detail["actions"][0]["id"]
    response = await client.post(f"/api/v1/actions/{action_id}/decision", json={"approve": True})
    assert response.status_code == 200, response.text
    assert len((await client.get("/api/v1/tickets")).json()) == 1
