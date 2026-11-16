"""Standalone memory-worker entry for the production topology.

Runs the memory_tasks claim loop as its own process so production scales it
independently of the runtime worker (``AGENT_EMBEDDED_WORKER=false`` there).
Replicas are safe: claiming uses ``FOR UPDATE SKIP LOCKED`` plus a 120-second
lease with heartbeat renewal and a reaper. Quickstart/development embed the
same loop in the API process instead; see
``agent_platform.business_capabilities.memory.bootstrap``.
"""

import asyncio
import logging

from agent_platform.applications.customer_service.runtime_composition import runtime_services
from agent_platform.applications.platform_runtime.worker_heartbeat import start_heartbeat
from agent_platform.business_capabilities.memory.bootstrap import build_memory_worker
from agent_platform.core_platform.platform_services.platform_settings.settings import Settings

logger = logging.getLogger(__name__)


async def main(settings=None):
    settings = settings or Settings()
    async with runtime_services(settings) as services:
        worker = build_memory_worker(services.groups, settings)
        beat = start_heartbeat(services.groups.runtime.engine, "memory")
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
