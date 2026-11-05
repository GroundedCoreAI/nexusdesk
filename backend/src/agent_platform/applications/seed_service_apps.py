"""Seed the V1 consumer-service application after migrations.

The operation is idempotent and never overwrites operator edits:

    python -m agent_platform.applications.seed_service_apps
"""

import asyncio

from agent_platform.applications.customer_service.runtime_composition import runtime_services
from agent_platform.core_platform.platform_services.platform_settings.settings import Settings


async def main() -> None:
    settings = Settings()
    async with runtime_services(settings) as runtime:
        scenarios = runtime.groups.business.scenarios
        applications = runtime.groups.business.service_apps
        await scenarios.seed_defaults(
            settings.tenant_id,
            "seed-service-apps",
        )
        result = await applications.seed_defaults(
            settings.tenant_id,
            "seed-service-apps",
        )
    print(
        "服务应用演示数据就绪，租户："
        f"{settings.tenant_id}；新增应用 {result['applications']} 个。"
    )


if __name__ == "__main__":
    asyncio.run(main())
