"""Phase 6 R-19: tool.replay is fenced against terminal state and expired lease.

The replay put reads status/lease_valid under the row lock but only denied on
missing Run or owner/epoch mismatch. A current owner/epoch could still insert
tool.replay after terminal state or with an expired lease, advancing event_seq
and creating a replay row. Deny those cases under the same lock.
"""
import os
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text

from agent_platform.applications.platform_runtime.runtime_hooks import (
    BusinessRuntimePersistenceHooks,
)
from agent_platform.core_platform.agent_execution.reliability.ownership import (
    OwnershipDenied,
)
from agent_platform.core_platform.agent_runtime.repository import RunRepository
from agent_platform.core_platform.agent_runtime.schemas import RunRequest
from agent_platform.core_platform.platform_services.persistence.database import (
    create_engine,
)
from agent_platform.core_platform.platform_services.platform_settings.settings import (
    Settings,
)
from agent_platform.core_platform.tool_gateway.replay import DurableToolReplayCache

pytestmark = [pytest.mark.asyncio, pytest.mark.postgres]


@pytest_asyncio.fixture
async def repo():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a migrated, dedicated PostgreSQL test database")
    tenant = "r19-replay-" + uuid4().hex
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
        tenant, RunRequest(conversation_id="rp-" + uuid4().hex[:6], message="x"),
        {"fingerprint": "rp"}, 1000, 100, 120,
    )
    claimed = await repo.claim(owner, 120, tenant)
    return run["id"], claimed


async def _counts(engine, run_id):
    async with engine.connect() as conn:
        event_seq = await conn.scalar(
            text("SELECT event_seq FROM runtime_runs WHERE id=:id"), {"id": run_id}
        )
        replay = await conn.scalar(
            text("SELECT count(*) FROM runtime_events WHERE run_id=:id AND type='tool.replay'"),
            {"id": run_id},
        )
        outbox = await conn.scalar(
            text("SELECT count(*) FROM runtime_event_outbox WHERE run_id=:id"), {"id": run_id}
        )
    return event_seq, replay, outbox


async def test_replay_denied_after_terminal_state(repo):
    repository, tenant, engine = repo
    owner = uuid4()
    run_id, claimed = await _claim(repository, tenant, owner)
    await repository.finish(
        run_id, owner, "completed", output="done", history=[],
        lease_epoch=claimed["lease_epoch"],
    )
    key = f"runtime:{run_id}:" + "a" * 64
    cache = DurableToolReplayCache(engine)
    before = await _counts(engine, run_id)
    with pytest.raises(OwnershipDenied) as exc:
        await cache.put(key, {"result": "late"}, owner=owner, lease_epoch=claimed["lease_epoch"])
    assert exc.value.reason in {"run_terminal", "run_missing"}
    after = await _counts(engine, run_id)
    assert after == before  # no event_seq advance, no replay row, no outbox row
    async with engine.connect() as conn:
        denial = (
            await conn.execute(
                text("SELECT operation,reason FROM execution_fencing_denials"
                     " WHERE run_id=:id ORDER BY created_at DESC LIMIT 1"),
                {"id": run_id},
            )
        ).first()
    assert denial is not None and denial[0] == "tool_replay"


async def test_replay_denied_with_expired_lease(repo):
    repository, tenant, engine = repo
    owner = uuid4()
    run_id, claimed = await _claim(repository, tenant, owner)
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE runtime_runs SET lease_until=now()-interval '1 second' WHERE id=:id"),
            {"id": run_id},
        )
    key = f"runtime:{run_id}:" + "a" * 64
    cache = DurableToolReplayCache(engine)
    before = await _counts(engine, run_id)
    with pytest.raises(OwnershipDenied) as exc:
        await cache.put(key, {"result": "late"}, owner=owner, lease_epoch=claimed["lease_epoch"])
    assert exc.value.reason in {"lease_lost", "run_terminal", "run_missing"}
    after = await _counts(engine, run_id)
    assert after == before
