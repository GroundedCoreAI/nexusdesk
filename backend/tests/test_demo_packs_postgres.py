"""PostgreSQL integration test: a fresh tenant reaches a publishable state.

The unit tests in ``test_demo_packs.py`` stop at the compiler. This one exercises
the path a real deployment takes — install the pack, enable its providers,
publish every scenario, publish the application — and asserts the release gate
accepts the result. It is the regression guard for the seed script's assumptions
about the service layer's return types.
"""

import pytest
from test_platform_postgres import platform as _platform

from agent_platform.applications.seed_demo_packs import DEMO_PACK_KEYS, promote_demo_packs

platform = _platform
pytestmark = [pytest.mark.asyncio, pytest.mark.postgres]


async def test_promote_publishes_every_demo_pack_and_passes_the_gate(platform):
    _client, runtime, settings = platform
    business = runtime.groups.business

    await promote_demo_packs(business, settings.tenant_id, "test")

    listed = await business.service_apps.list(settings.tenant_id)
    keys = {item["key"] for item in listed["items"]}
    assert keys == {f"{pack_key}-service" for pack_key in DEMO_PACK_KEYS}

    for item in listed["items"]:
        assert item["status"] == "published", item["key"]
        assert item["published_version"] == 1, item["key"]
        assert item["scenario_count"] > 0, item["key"]

        readiness = await business.service_apps.readiness(settings.tenant_id, item["key"])
        assert readiness["status"] == "ready", (
            item["key"],
            [(check["key"], check["status"]) for check in readiness["checks"]],
        )
        assert readiness["can_publish"] is True
        assert readiness["counts"]["blocked"] == 0


async def test_promote_is_idempotent(platform):
    _client, runtime, settings = platform
    business = runtime.groups.business

    await promote_demo_packs(business, settings.tenant_id, "test")
    before = await business.service_apps.list(settings.tenant_id)
    versions_before = {item["key"]: item["published_version"] for item in before["items"]}

    report = await promote_demo_packs(business, settings.tenant_id, "test")
    after = await business.service_apps.list(settings.tenant_id)
    versions_after = {item["key"]: item["published_version"] for item in after["items"]}

    assert versions_after == versions_before
    assert all("此前已发布" in line for line in report)
    assert all("发布场景 0 个" in line for line in report)
