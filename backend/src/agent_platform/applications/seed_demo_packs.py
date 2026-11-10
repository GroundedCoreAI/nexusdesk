"""Install the four demo industry packs and make them usable immediately.

Installing a pack alone leaves every scenario as a draft and every provider as
a disabled placeholder, so the generated application can never pass its release
gate.  This seed promotes each demo pack to a working state:

1. install the pack (skipped when already installed),
2. enable the providers the pack declared,
3. publish every scenario,
4. publish the application.

The command is idempotent and never overwrites operator edits beyond the
promotion step:

    python -m agent_platform.applications.seed_demo_packs
"""

import asyncio
from typing import Any

from agent_platform.business_capabilities.customer_service.industry_packs.runtime_models import (
    IndustryPackInstallInput,
)
from agent_platform.core_platform.platform_services.persistence.store import (
    DomainError,
    execute,
)
from agent_platform.core_platform.platform_services.platform_settings.settings import Settings

from .customer_service.runtime_composition import runtime_services

DEMO_PACK_KEYS = ("shopping", "gaming", "creator", "mobility")


async def _enable_providers(engine, tenant: str, actor: str, pack_key: str) -> int:
    async with engine.begin() as connection:
        result = await execute(
            connection,
            """
UPDATE service_provider_registry
SET enabled=true,updated_by=:actor
WHERE tenant_id=:tenant AND source_ref=:pack_key AND NOT enabled
""",
            tenant=tenant,
            actor=actor,
            pack_key=pack_key,
        )
    return result.rowcount or 0


async def _publish_scenarios(business, tenant: str, actor: str, scenarios: dict[str, str]) -> int:
    published = 0
    for scenario_key in scenarios.values():
        row = await business.scenarios.get(tenant, scenario_key)
        if row["published_version"] is not None:
            continue
        revision = row.get("revision") or row["draft_revision"]
        await business.scenarios.publish(tenant, actor, scenario_key, revision)
        published += 1
    return published


async def _publish_application(
    business, tenant: str, actor: str, application_key: str
) -> bool | None:
    """Publish an installed application. ``None`` means an operator archived it."""

    try:
        application = await business.service_apps.get(tenant, application_key)
    except DomainError as error:
        # Archiving hides the row from every read path, including this one. The
        # operator's decision wins: re-seeding must not resurrect it.
        if error.code != "service_application_not_found":
            raise
        return None
    if application["published_version"] is not None:
        return False
    await business.service_apps.publish(
        tenant,
        actor,
        application["key"],
        application["revision"],
    )
    return True


def _installed_map(page: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """``list_installations`` serialises to a mapping, not a model."""

    return {item["pack_key"]: item for item in page["items"]}


async def promote_demo_packs(business: Any, tenant: str, actor: str) -> list[str]:
    """Install the demo packs and promote them to a published state.

    Idempotent: re-running only picks up packs that are still missing and never
    republishes a scenario or an application that already has a version.
    Returns one human-readable line per pack so callers can log or assert.
    """

    packs = business.industry_packs
    installed = _installed_map(await packs.list_installations(tenant))
    report: list[str] = []

    for pack_key in DEMO_PACK_KEYS:
        installation = installed.get(pack_key)
        if installation is None:
            result = await packs.install(
                tenant,
                actor,
                pack_key,
                IndustryPackInstallInput(),
            )
            installation = result["installation"]
            state = "已安装"
        else:
            state = "已存在"

        providers = await _enable_providers(packs.engine, tenant, actor, pack_key)
        scenarios = await _publish_scenarios(
            business,
            tenant,
            actor,
            installation["installed_scenarios"],
        )
        application_published = await _publish_application(
            business,
            tenant,
            actor,
            installation["application_key"],
        )
        if application_published is None:
            application_note = "应用已归档，跳过"
        elif application_published:
            application_note = "应用已发布"
        else:
            application_note = "应用此前已发布"
        report.append(
            f"{pack_key}: {state}；启用 Provider {providers} 个，"
            f"发布场景 {scenarios} 个，{application_note}。"
        )
    return report


async def main() -> None:
    settings = Settings()
    tenant, actor = settings.tenant_id, "seed-demo-packs"

    async with runtime_services(settings) as runtime:
        for line in await promote_demo_packs(runtime.groups.business, tenant, actor):
            print(line, flush=True)
        print(f"演示行业包就绪，租户：{tenant}。", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
