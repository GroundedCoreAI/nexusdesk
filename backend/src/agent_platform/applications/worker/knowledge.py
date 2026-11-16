import asyncio

from agent_platform.applications.customer_service.runtime_composition import runtime_services
from agent_platform.applications.platform_runtime.worker_heartbeat import start_heartbeat
from agent_platform.business_capabilities.knowledge.bootstrap import build_knowledge_worker
from agent_platform.core_platform.platform_services.platform_settings.settings import Settings


async def main():
    settings = Settings()
    async with runtime_services(settings) as services:
        worker = build_knowledge_worker(services.groups.business, settings)
        beat = start_heartbeat(services.groups.runtime.engine, "knowledge")
        try:
            await worker.serve()
        finally:
            worker.stop()
            beat.cancel()
            await asyncio.gather(beat, return_exceptions=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
