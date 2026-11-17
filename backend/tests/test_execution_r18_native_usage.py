"""Phase 6 R-18(c): native usage routed through Adapter/Orchestrator boundary.

Native usage events carry stable producer identity and flow through the
Orchestrator into the ownership-checked source-unique ledger with
duplicate/old-epoch/correction/unknown semantics.
"""
import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text

from agent_platform.applications.platform_runtime.runtime_hooks import (
    BusinessRuntimePersistenceHooks,
)
from agent_platform.core_platform.agent_execution.contracts import AgentEvent
from agent_platform.core_platform.agent_execution.events.envelope import (
    from_agent_event,
)
from agent_platform.core_platform.agent_runtime.repository import RunRepository
from agent_platform.core_platform.agent_runtime.schemas import RunRequest
from agent_platform.core_platform.platform_services.persistence.database import (
    create_engine,
)
from agent_platform.core_platform.platform_services.platform_settings.settings import (
    Settings,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.postgres]


@pytest_asyncio.fixture
async def repo():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a migrated, dedicated PostgreSQL test database")
    tenant = "r18-usage-" + uuid4().hex
    settings = Settings(database_url=url, tenant_id=tenant, embedded_worker=False)
    engine = create_engine(settings)
    repository = RunRepository(engine, BusinessRuntimePersistenceHooks())
    try:
        yield repository, tenant, engine
    finally:
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM execution_fencing_denials WHERE run_id IN "
                     "(SELECT id FROM runtime_runs WHERE tenant_id=:t)"), {"t": tenant}
            )
            await conn.execute(text("DELETE FROM runtime_runs WHERE tenant_id=:t"), {"t": tenant})
            await conn.execute(
                text("DELETE FROM runtime_conversations WHERE tenant_id=:t"), {"t": tenant}
            )
        await engine.dispose()


async def _claim(repo, tenant, owner):
    run = await repo.submit(
        tenant, RunRequest(conversation_id="nu-" + uuid4().hex[:6], message="x"),
        {"fingerprint": "nu"}, 1000, 100, 120,
    )
    claimed = await repo.claim(owner, 120, tenant)
    return run["id"], claimed


def _usage_event(run_id, *, usage, producer_id="codex", producer_event_id="u-1", event_id=None):
    return AgentEvent(
        event_id=event_id or uuid4(),
        execution_id=run_id, engine_id="codex", protocol_id="cli_exec", adapter_version="v1",
        sequence=1, event_type="codex.usage", source="engine_native",
        timestamp=datetime.now(UTC), payload={"usage": usage},
        producer_id=producer_id, producer_event_id=producer_event_id,
    )


async def test_native_usage_event_persists_source_unique_ledger(repo):
    repository, tenant, engine = repo
    owner = uuid4()
    run_id, claimed = await _claim(repository, tenant, owner)
    event = _usage_event(run_id, usage={"total_tokens": 7})
    write = from_agent_event(event)
    result = await repository.append_event(
        run_id, owner, write, lease_epoch=claimed["lease_epoch"]
    )
    assert result.duplicate is False
    # Native usage is extracted into the source-unique ledger.
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text("SELECT source,source_event_id,usage FROM runtime_usage_ledger"
                     " WHERE run_id=:id"), {"id": run_id},
            )
        ).mappings().all()
    assert len(rows) == 1
    assert rows[0]["source"] == "codex"
    assert rows[0]["source_event_id"] == "u-1"
    assert rows[0]["usage"] == {"total_tokens": 7}

    # Duplicate native event with a new event_id does not recount.
    resent = _usage_event(run_id, usage={"total_tokens": 99}, event_id=uuid4())
    dup = await repository.append_event(
        run_id, owner, from_agent_event(resent), lease_epoch=claimed["lease_epoch"]
    )
    assert dup.duplicate is True
    async with engine.connect() as conn:
        count = await conn.scalar(
            text("SELECT count(*) FROM runtime_usage_ledger WHERE run_id=:id"), {"id": run_id}
        )
    assert count == 1


async def test_native_usage_unknown_is_explicit_not_zero_filled(repo):
    repository, tenant, engine = repo
    owner = uuid4()
    run_id, claimed = await _claim(repository, tenant, owner)
    event = _usage_event(run_id, usage={"status": "unknown"})
    await repository.append_event(
        run_id, owner, from_agent_event(event), lease_epoch=claimed["lease_epoch"]
    )
    async with engine.connect() as conn:
        usage = await conn.scalar(
            text("SELECT usage FROM runtime_usage_ledger WHERE run_id=:id"), {"id": run_id}
        )
    assert usage == {"status": "unknown"}
