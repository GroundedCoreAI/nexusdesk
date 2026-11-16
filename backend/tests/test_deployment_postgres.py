import pytest
from sqlalchemy import text
from test_platform_postgres import platform as _platform_fixture

from agent_platform.applications import seed, seed_service_apps
from agent_platform.business_capabilities.customer_service.service_apps.seed import (
    example_applications,
)

platform = _platform_fixture
pytestmark = [pytest.mark.asyncio, pytest.mark.postgres]


async def test_quickstart_seed_is_repeatable_and_installs_service_application_examples(
    platform, monkeypatch
):
    client, services, settings = platform
    monkeypatch.setattr(seed, "Settings", lambda: settings)
    monkeypatch.setattr(seed_service_apps, "Settings", lambda: settings)

    # The workspace seed and the independent v2 example installer must both be
    # idempotent. Running each twice models a restart on the same database.
    await seed.main()
    await seed.main()
    await seed_service_apps.main()
    await seed_service_apps.main()

    async with services.groups.runtime.engine.connect() as connection:
        for table in ("agents", "knowledge_bases", "gateway_profiles"):
            count = await connection.scalar(
                text(f"SELECT count(*) FROM {table} WHERE tenant_id=:tenant"),
                {"tenant": settings.tenant_id},
            )
            assert count == 1, table

    applications = (await client.get("/api/v1/service-apps")).json()
    expected_keys = {
        item["key"]
        for item in example_applications(
            {
                "id": "00000000-0000-0000-0000-000000000001",
                "name": "seed contract",
                "version": 1,
            }
        )
    }
    listed = applications["items"]
    assert applications["total"] == len(expected_keys)
    assert {item["key"] for item in listed} == expected_keys
    assert all(item["origin"] == "example" and item["immutable"] for item in listed)
    assert all(item["status"] == "published" for item in listed)
    assert all(item["published_version"] == 1 for item in listed)
    for item in listed:
        detail = await client.get(f"/api/v1/service-apps/{item['key']}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["published_version"] == 1

    # A second installer run must not append versions or overwrite examples.
    versions = {
        item["key"]: (await client.get(f"/api/v1/service-apps/{item['key']}/versions")).json()
        for item in listed
    }
    assert all(result["total"] == 1 for result in versions.values())
