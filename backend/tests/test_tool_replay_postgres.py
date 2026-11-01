import asyncio
import hashlib
import os
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text

from agent_platform.applications.platform_runtime.runtime_hooks import (
    BusinessRuntimePersistenceHooks,
)
from agent_platform.core_platform.agent_runtime.repository import RunRepository
from agent_platform.core_platform.agent_runtime.schemas import RunRequest
from agent_platform.core_platform.platform_services.persistence.database import create_engine
from agent_platform.core_platform.platform_services.platform_settings.settings import Settings
from agent_platform.core_platform.tool_gateway.replay import DurableToolReplayCache

pytestmark = [pytest.mark.asyncio, pytest.mark.postgres]


@pytest_asyncio.fixture
async def database():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a migrated, dedicated PostgreSQL test database")
    tenant = "replay-" + str(uuid4())
    settings = Settings(database_url=url, tenant_id=tenant, embedded_worker=False)
    engine = create_engine(settings)
    repository = RunRepository(engine, BusinessRuntimePersistenceHooks())
    try:
        yield repository, settings
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM runtime_runs WHERE tenant_id=:tenant"),
                {"tenant": tenant},
            )
            await connection.execute(
                text("DELETE FROM runtime_conversations WHERE tenant_id=:tenant"),
                {"tenant": tenant},
            )
        await engine.dispose()


async def test_durable_replay_survives_cache_recreation(database):
    repository, settings = database
    row = await repository.submit(
        settings.tenant_id,
        RunRequest(conversation_id="replay-session", message="hello"),
        {"fingerprint": "test"},
        10,
        10,
        120,
    )
    digest = hashlib.sha256(b"same-write").hexdigest()
    key = f"runtime:{row['id']}:{digest}"
    result = {
        "ok": True,
        "data": {"accepted": True, "external_id": "order-1"},
        "call_id": "gateway-1",
    }

    first = DurableToolReplayCache(repository.engine)
    await asyncio.gather(
        first.put(key, result), DurableToolReplayCache(repository.engine).put(key, result)
    )
    assert await first.get(key) == result

    recreated = DurableToolReplayCache(repository.engine)
    assert await recreated.get(key) == result

    before = (await repository.get(row["id"], settings.tenant_id))["event_seq"]
    await recreated.put(key, result)
    after = (await repository.get(row["id"], settings.tenant_id))["event_seq"]
    assert after == before

    events = await repository.events(row["id"], settings.tenant_id)
    replay_events = [event for event in events if event["type"] == "tool.replay"]
    assert len(replay_events) == 1
    assert replay_events[0]["data"]["result"] == result


async def test_durable_replay_rejects_malformed_key(database):
    repository, _settings = database
    cache = DurableToolReplayCache(repository.engine)

    with pytest.raises((ValueError, IndexError)):
        await cache.get("runtime:not-a-uuid:short")
