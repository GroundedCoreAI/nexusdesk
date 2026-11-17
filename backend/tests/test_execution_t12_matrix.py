"""Phase 6 T-12: remaining deterministic concurrency/fault/matrix evidence."""

import asyncio
import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from test_runtime_postgres import internal_runtime_client

from agent_platform.applications.platform_runtime.runtime_hooks import (
    BusinessRuntimePersistenceHooks,
)
from agent_platform.core_platform.agent_execution.contracts import AgentEvent
from agent_platform.core_platform.agent_execution.events.envelope import from_agent_event
from agent_platform.core_platform.agent_execution.events.outbox import OutboxDispatcher
from agent_platform.core_platform.agent_runtime.repository import RunRepository
from agent_platform.core_platform.agent_runtime.schemas import RunRequest
from agent_platform.core_platform.platform_services.persistence.database import create_engine
from agent_platform.core_platform.platform_services.platform_settings.settings import Settings

pytestmark = [pytest.mark.asyncio, pytest.mark.postgres]


@pytest_asyncio.fixture
async def repo():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a migrated, dedicated PostgreSQL test database")
    tenant = "t12-" + uuid4().hex
    settings = Settings(database_url=url, tenant_id=tenant, embedded_worker=False)
    engine = create_engine(settings)
    repository = RunRepository(engine, BusinessRuntimePersistenceHooks())
    try:
        yield repository, tenant, engine, settings
    finally:
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM execution_fencing_denials WHERE run_id IN "
                     "(SELECT id FROM runtime_runs WHERE tenant_id=:t)"), {"t": tenant}
            )
            await conn.execute(text("DELETE FROM memory_tasks WHERE tenant_id=:t"), {"t": tenant})
            await conn.execute(text("DELETE FROM runtime_runs WHERE tenant_id=:t"), {"t": tenant})
            await conn.execute(
                text("DELETE FROM runtime_conversations WHERE tenant_id=:t"), {"t": tenant}
            )
        await engine.dispose()


async def _claim(repository, tenant, owner=None):
    submitted = await repository.submit(
        tenant,
        RunRequest(conversation_id="t12-" + uuid4().hex[:8], message="m"),
        {"fingerprint": "t12"},
        1000,
        100,
        120,
    )
    claimed = await repository.claim(owner or uuid4(), 120, tenant)
    assert claimed is not None and claimed["id"] == submitted["id"]
    return claimed


def _event(run_id, *, producer=None, event_id=None, event_type="extension.note"):
    return AgentEvent(
        event_id=event_id or uuid4(), execution_id=run_id,
        engine_id="react", protocol_id="native", adapter_version="v1",
        sequence=1, event_type=event_type, source="engine_native",
        timestamp=datetime.now(UTC), payload={"note": "x"},
        producer_id=None if producer is None else producer,
        producer_event_id=None if producer is None else "native-1",
    )


async def test_takeover_heartbeat_finish_race_has_one_effective_terminal(repo):
    repository, tenant, engine, _ = repo
    owner_a, owner_b = uuid4(), uuid4()
    claimed = await _claim(repository, tenant, owner_a)
    run_id = claimed["id"]
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE runtime_runs SET lease_until=now()-interval '1 second' WHERE id=:id"),
            {"id": run_id},
        )
    barrier = asyncio.Event()

    async def old_finish():
        await barrier.wait()
        await repository.finish(
            run_id, owner_a, "completed", output="old", history=[], lease_epoch=1
        )

    async def old_heartbeat():
        await barrier.wait()
        return await repository.heartbeat(run_id, owner_a, 120, lease_epoch=1)

    async def takeover():
        await barrier.wait()
        return await repository.takeover(owner_b, 120, tenant)

    finish_task = asyncio.create_task(old_finish())
    heartbeat_task = asyncio.create_task(old_heartbeat())
    takeover_task = asyncio.create_task(takeover())
    barrier.set()
    await asyncio.gather(finish_task, heartbeat_task, takeover_task)
    taken = takeover_task.result()
    async with engine.connect() as conn:
        row = (
            (await conn.execute(text("SELECT * FROM runtime_runs WHERE id=:id"), {"id": run_id}))
            .mappings().one()
        )
        terminals = (
            await conn.execute(
                text("SELECT type FROM runtime_events WHERE run_id=:id "
                     "AND type IN ('run.completed','run.failed','run.cancelled')"), {"id": run_id}
            )
        ).scalars().all()
    assert len(terminals) <= 1
    if taken is not None:
        assert taken["lease_epoch"] == 2
        assert heartbeat_task.result() == "lost"
        assert row["owner"] == owner_b
        assert row["status"] == "running"
        await repository.append_event(
            run_id, owner_b, from_agent_event(_event(run_id)), lease_epoch=2
        )
        await repository.finish(run_id, owner_b, "completed", output="done", history=[], lease_epoch=2)
    else:
        if row["status"] == "running":
            # SKIP LOCKED may defer takeover while the old finish holds the row;
            # once that lock is released, recovery must be able to fence it.
            taken = await repository.takeover(owner_b, 120, tenant)
            assert taken is not None and taken["lease_epoch"] == 2
            await repository.finish(
                run_id, owner_b, "completed", output="done", history=[], lease_epoch=2
            )
        else:
            assert row["status"] == "completed"
            assert row["output"] == "old"


async def test_concurrent_sequence_and_producer_dedup(repo):
    repository, tenant, engine, _ = repo
    owner = uuid4()
    claimed = await _claim(repository, tenant, owner)
    run_id, epoch = claimed["id"], claimed["lease_epoch"]

    async def append(event):
        return await repository.append_event(
            run_id, owner, from_agent_event(event), lease_epoch=epoch
        )

    unique = await asyncio.gather(*(append(_event(run_id)) for _ in range(20)))
    assert len({item.seq for item in unique}) == 20
    duplicates = await asyncio.gather(
        *(append(_event(run_id, producer="codex")) for _ in range(12))
    )
    assert len({item.seq for item in duplicates}) == 1
    assert sum(not item.duplicate for item in duplicates) == 1
    async with engine.connect() as conn:
        sequences = (
            await conn.execute(
                text("SELECT seq FROM runtime_events WHERE run_id=:id ORDER BY seq"), {"id": run_id}
            )
        ).scalars().all()
        producer_events = await conn.scalar(
            text("SELECT count(*) FROM runtime_events WHERE run_id=:id AND producer_id='codex'"),
            {"id": run_id},
        )
        producer_outbox = await conn.scalar(
            text("SELECT count(*) FROM runtime_event_outbox o JOIN runtime_events e "
                 "ON o.run_id=e.run_id AND o.seq=e.seq "
                 "WHERE e.run_id=:id AND e.producer_id='codex'"), {"id": run_id}
        )
    assert sequences == list(range(1, len(sequences) + 1))
    assert producer_events == 1
    assert producer_outbox == 1


async def test_finish_precommit_hook_fault_rolls_back_everything(repo, monkeypatch):
    repository, tenant, engine, _ = repo
    owner = uuid4()
    claimed = await _claim(repository, tenant, owner)
    run_id = claimed["id"]

    async def crash(*args):
        raise RuntimeError("precommit-canary-not-persisted")

    monkeypatch.setattr(repository.hooks, "on_finished", crash)
    with pytest.raises(RuntimeError, match="precommit"):
        await repository.finish(
            run_id, owner, "completed", output="done", history=[], usage={"total_tokens": 4}, lease_epoch=1
        )
    async with engine.connect() as conn:
        row = (
            (await conn.execute(text("SELECT status,event_seq FROM runtime_runs WHERE id=:id"),
                                {"id": run_id})).mappings().one()
        )
        event_count = await conn.scalar(
            text("SELECT count(*) FROM runtime_events WHERE run_id=:id AND type='run.completed'"),
            {"id": run_id},
        )
        usage_count = await conn.scalar(
            text("SELECT count(*) FROM runtime_usage_ledger WHERE run_id=:id"), {"id": run_id}
        )
    assert row["status"] == "running"
    assert event_count == usage_count == 0


async def test_finish_postcommit_fault_recovers_pending_outbox(repo):
    repository, tenant, engine, _ = repo
    owner = uuid4()
    claimed = await _claim(repository, tenant, owner)
    run_id = claimed["id"]
    original = repository.finish

    async def postcommit_crash(*args, **kwargs):
        await original(*args, **kwargs)
        raise RuntimeError("postcommit")

    with pytest.raises(RuntimeError, match="postcommit"):
        await postcommit_crash(run_id, owner, "completed", output="done", history=[], lease_epoch=1)
    row = await repository.get(run_id, tenant)
    assert row["status"] == "completed"

    class Publisher:
        def __init__(self):
            self.calls = 0

        async def enqueue(self, event):
            self.calls += 1
            return True

    publisher = Publisher()
    dispatcher = OutboxDispatcher(engine, publisher, tenant_id=tenant)
    assert await dispatcher.dispatch_once() >= 1
    assert await dispatcher.pending_count() == 0
    assert publisher.calls >= 3  # queued, started, completed


async def test_outbox_after_enqueue_crash_is_idempotent_on_rescan(repo):
    repository, tenant, engine, _ = repo
    owner = uuid4()
    claimed = await _claim(repository, tenant, owner)
    run_id = claimed["id"]
    appended = await repository.append_event(
        run_id, owner, from_agent_event(_event(run_id)), lease_epoch=1
    )

    class Drain:
        async def enqueue(self, event):
            return True

    await OutboxDispatcher(engine, Drain(), tenant_id=tenant).dispatch_once()

    class CrashAfterAccept:
        def __init__(self):
            self.accepted = []
            self.crashed = False

        async def enqueue(self, event):
            self.accepted.append(event.event_id)
            if not self.crashed:
                self.crashed = True
                raise RuntimeError("after_accept")
            return True

    publisher = CrashAfterAccept()
    dispatcher = OutboxDispatcher(engine, publisher, tenant_id=tenant, batch_size=100)
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE runtime_event_outbox SET status='pending',available_at=now() "
                 "WHERE run_id=:id AND seq=:seq"), {"id": run_id, "seq": appended.seq}
        )
    await dispatcher.dispatch_once()
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE runtime_event_outbox SET available_at=now() WHERE run_id=:id"),
            {"id": run_id},
        )
    await dispatcher.dispatch_once()
    assert len(publisher.accepted) >= 2
    assert publisher.accepted[0] == publisher.accepted[1]
    assert await dispatcher.pending_count() == 0


async def test_sse_subscribe_terminal_race_delivers_final_event(repo):
    repository, tenant, engine, settings = repo
    owner = uuid4()
    claimed = await _claim(repository, tenant, owner)
    run_id = claimed["id"]
    async with internal_runtime_client(settings) as (_app, client):
        response_task = asyncio.create_task(
            client.get(f"/api/v1/runs/{run_id}/events?after=0", timeout=10)
        )
        await asyncio.sleep(0.2)
        await repository.finish(
            run_id, owner, "completed", output="raced", history=[], lease_epoch=1
        )
        response = await asyncio.wait_for(response_task, timeout=10)
    assert response.status_code == 200
    assert '"output":"raced"' in response.text.replace(" ", "")
    assert "run.completed" in response.text


@pytest.mark.parametrize("error_code", ["run_timeout", "external_write_disconnect", "worker_lost"])
async def test_prepare_retry_refuses_ambiguous_or_postlaunch_failure(repo, error_code):
    repository, tenant, _engine, _ = repo
    owner = uuid4()
    claimed = await _claim(repository, tenant, owner)
    run_id = claimed["id"]
    await repository.finish(run_id, owner, "failed", error=error_code, lease_epoch=1)
    assert await repository.prepare_retry(run_id, tenant) is None


async def test_external_write_policy_requires_explicit_idempotency_for_manual_retry(repo):
    repository, tenant, engine, _ = repo
    owner = uuid4()
    claimed = await _claim(repository, tenant, owner)
    run_id = claimed["id"]
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE runtime_runs SET side_effect_policy=CAST(:policy AS jsonb) WHERE id=:id"),
            {"policy": '{"side_effects": true}', "id": run_id},
        )
    await repository.finish(run_id, owner, "failed", error="post_launch", lease_epoch=1)
    assert await repository.prepare_retry(run_id, tenant) is None
    async with engine.connect() as conn:
        retries = await conn.scalar(
            text("SELECT count(*) FROM runtime_runs WHERE retry_of_run_id=:id"), {"id": run_id}
        )
    assert retries == 0
