import asyncio

from agent_platform.applications.customer_service.runtime_composition import runtime_services
from agent_platform.core_platform.platform_services.platform_settings.settings import Settings


async def main():
    settings = Settings()
    async with runtime_services(settings) as services:
        try:
            await services.worker.serve()
        finally:
            services.worker.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
