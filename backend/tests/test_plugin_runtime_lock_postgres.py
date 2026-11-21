import asyncio

import pytest
import pytest_asyncio
from conftest import require_test_database_url

from agent_platform.core_platform.extension_platform import (
    CapabilityRegistry,
    CapabilityRuntimeStateService,
)
from agent_platform.core_platform.platform_services.persistence.database import create_engine
from agent_platform.core_platform.platform_services.platform_settings.settings import Settings

pytestmark = [pytest.mark.asyncio, pytest.mark.postgres]


@pytest_asyncio.fixture
async def runtime_state_service():
    url = require_test_database_url()
    settings = Settings(database_url=url, embedded_worker=False)
    engine = create_engine(settings)
    try:
        yield CapabilityRuntimeStateService(engine, CapabilityRegistry())
    finally:
        await engine.dispose()


async def test_lifecycle_advisory_lock_serializes_process_operations(runtime_state_service):
    order: list[str] = []

    async def first():
        order.append("first:start")
        await asyncio.sleep(0.05)
        order.append("first:end")

    async def second():
        order.append("second:start")
        order.append("second:end")

    await asyncio.gather(
        runtime_state_service.run_lifecycle_locked("sample-operations", first),
        runtime_state_service.run_lifecycle_locked("sample-operations", second),
    )

    assert order in (
        ["first:start", "first:end", "second:start", "second:end"],
        ["second:start", "second:end", "first:start", "first:end"],
    )
