import asyncio

from agent_platform.applications.customer_service.runtime_composition import runtime_services
from agent_platform.core_platform.platform_services.platform_settings.settings import Settings


async def main():
    settings = Settings()
    async with runtime_services(settings) as services:
        business = services.groups.business
        while True:
            if not await business.knowledge_workspace.run_next(
                settings.tenant_id
            ) and not await business.ingestion.run_next(settings.tenant_id):
                await asyncio.sleep(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
