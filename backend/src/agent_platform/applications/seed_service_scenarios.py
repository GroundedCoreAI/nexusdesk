"""Seed the V1 service-scenario catalog after migrations.

The operation is idempotent and never overwrites operator edits:

    python -m agent_platform.applications.seed_service_scenarios
"""

import asyncio

from agent_platform.applications.customer_service.runtime_composition import runtime_services
from agent_platform.core_platform.platform_services.platform_settings.settings import Settings


async def main() -> None:
    settings = Settings()
    async with runtime_services(settings) as runtime:
        result = await runtime.groups.business.scenarios.seed_defaults(
            settings.tenant_id,
            "seed-service-scenarios",
        )
    print(
        "服务场景演示数据就绪，租户："
        f"{settings.tenant_id}；新增场景 {result['scenarios']} 个，"
        f"新增版本 {result['versions']} 个。"
    )


if __name__ == "__main__":
    asyncio.run(main())
