"""Phase 6 T-04: preserve AgentEvent identity and deduplicate durably.

The durable ``runtime_events.seq`` stays the sole Run sequence. The adapter
sequence is producer metadata only. A duplicate event_id or producer key
returns the original durable result without consuming a new sequence, and
internal ``tool.replay`` receives identity but never a public Outbox row.
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
    EventProducerIdentity,
    from_agent_event,
)
from agent_platform.core_platform.agent_execution.reliability.ownership import OwnershipDenied
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
    tenant = "events-" + uuid4().hex
    settings = Settings(database_url=url, tenant_id=tenant, embedded_worker=False)
    engine = create_engine(settings)
    repository = RunRepository(engine, BusinessRuntimePersistenceHooks())
    try:
        yield repository, tenant
    finally:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "DELETE FROM execution_fencing_denials WHERE run_id IN "
                    "(SELECT id FROM runtime_runs WHERE tenant_id=:tenant)"
                ),
                {"tenant": tenant},
            )
            await conn.execute(
                text("DELETE FROM runtime_runs WHERE tenant_id=:tenant"), {"tenant": tenant}
            )
            await conn.execute(
                text("DELETE FROM runtime_conversations WHERE tenant_id=:tenant"),
                {"tenant": tenant},
            )
        await engine.dispose()


async def _claim(repo, tenant, owner, conversation="events"):
    submitted = await repo.submit(
        tenant,
        RunRequest(conversation_id=conversation, message="events"),
        {"fingerprint": "phase6"},
        1000,
        100,
        120,
    )
    row = await repo.claim(owner, 120, tenant)
    assert row is not None and row["id"] == submitted["id"]
    return row


def _event(run_id, *, sequence=1, event_type="extension.note", event_id=None, producer=None):
    return AgentEvent(
        event_id=event_id or uuid4(),
        execution_id=run_id,
        engine_id="react",
        protocol_id="native",
        adapter_version="v1",
        sequence=sequence,
        event_type=event_type,
        source="engine_native",
        timestamp=datetime.now(UTC),
        payload={"note": sequence},
        producer_id=None if producer is None else producer.producer_id,
        producer_event_id=None if producer is None else producer.producer_event_id,
    )


async def _counts(repo, run_id):
    async with repo.engine.connect() as conn:
        events = await conn.scalar(
            text("SELECT count(*) FROM runtime_events WHERE run_id=:id"), {"id": run_id}
        )
        outbox = await conn.scalar(
            text("SELECT count(*) FROM runtime_event_outbox WHERE run_id=:id"), {"id": run_id}
        )
        return events, outbox


async def _event_seq(repo, event_id):
    async with repo.engine.connect() as conn:
        return await conn.scalar(
            text("SELECT seq FROM runtime_events WHERE event_id=:id"), {"id": event_id}
        )


async def test_duplicate_event_id_consumes_no_new_sequence(repo):
    repository, tenant = repo
    owner = uuid4()
    claimed = await _claim(repository, tenant, owner)
    run_id, epoch = claimed["id"], claimed["lease_epoch"]
    event = _event(run_id)
    write = from_agent_event(event)

    before, _ = await _counts(repository, run_id)
    first = await repository.append_event(run_id, owner, write, lease_epoch=epoch)
    assert first.duplicate is False
    assert first.seq == await _event_seq(repository, event.event_id)
    after_first, _ = await _counts(repository, run_id)
    assert after_first == before + 1

    second = await repository.append_event(run_id, owner, write, lease_epoch=epoch)
    assert second.duplicate is True
    assert second.seq == first.seq
    assert second.event_id == event.event_id
    after_second, _ = await _counts(repository, run_id)
    assert after_second == after_first


async def test_producer_key_deduplicates_a_resend_with_a_new_event_id(repo):
    repository, tenant = repo
    owner = uuid4()
    claimed = await _claim(repository, tenant, owner)
    run_id, epoch = claimed["id"], claimed["lease_epoch"]
    producer = EventProducerIdentity("codex", "native-1")

    first_event = _event(run_id, producer=producer)
    first = await repository.append_event(
        run_id, owner, from_agent_event(first_event), lease_epoch=epoch
    )
    resent_event = _event(run_id, producer=producer, event_id=uuid4())
    resent = await repository.append_event(
        run_id, owner, from_agent_event(resent_event), lease_epoch=epoch
    )

    assert resent.duplicate is True
    assert resent.seq == first.seq
    assert resent.event_id == first_event.event_id
    rows, _ = await _counts(repository, run_id)
    assert await _event_seq(repository, resent_event.event_id) is None
    assert rows == first.seq  # queued+started events plus this one


async def test_adapter_sequence_is_metadata_and_durable_sequence_is_database_owned(repo):
    repository, tenant = repo
    owner = uuid4()
    claimed = await _claim(repository, tenant, owner)
    run_id, epoch = claimed["id"], claimed["lease_epoch"]

    one = await repository.append_event(
        run_id, owner, from_agent_event(_event(run_id, sequence=1)), lease_epoch=epoch
    )
    nine = await repository.append_event(
        run_id, owner, from_agent_event(_event(run_id, sequence=9)), lease_epoch=epoch
    )
    assert nine.seq == one.seq + 1
    async with repository.engine.connect() as conn:
        stored = (
            await conn.execute(
                text("SELECT seq,type FROM runtime_events WHERE run_id=:id ORDER BY seq"),
                {"id": run_id},
            )
        ).all()
    # No adapter sequence is copied over the durable one and no gap appears.
    assert [row[0] for row in stored] == list(range(1, len(stored) + 1))


async def test_stale_epoch_event_write_rolls_back_and_audits(repo):
    repository, tenant = repo
    owner_a, owner_b = uuid4(), uuid4()
    claimed = await _claim(repository, tenant, owner_a)
    async with repository.engine.begin() as conn:
        await conn.execute(
            text("UPDATE runtime_runs SET lease_until=now()-interval '1 second' WHERE id=:id"),
            {"id": claimed["id"]},
        )
    taken = await repository.takeover(owner_b, 120, tenant)
    assert taken["lease_epoch"] == 2
    run_id = claimed["id"]

    before, _ = await _counts(repository, run_id)
    with pytest.raises(OwnershipDenied):
        await repository.append_event(
            run_id,
            owner_a,
            from_agent_event(_event(run_id)),
            lease_epoch=1,
        )
    assert await _counts(repository, run_id) == (before, _)

    async with repository.engine.connect() as conn:
        denial = (
            await conn.execute(
                text(
                    "SELECT operation,reason FROM execution_fencing_denials"
                    " WHERE run_id=:id ORDER BY created_at DESC LIMIT 1"
                ),
                {"id": run_id},
            )
        ).first()
    assert denial[0] == "append" and denial[1] in {"stale_epoch", "owner_mismatch"}

    result = await repository.append_event(
        run_id, owner_b, from_agent_event(_event(run_id)), lease_epoch=2
    )
    assert result.duplicate is False


async def test_internal_replay_receives_identity_and_no_outbox(repo):
    repository, tenant = repo
    owner = uuid4()
    claimed = await _claim(repository, tenant, owner)
    run_id, epoch = claimed["id"], claimed["lease_epoch"]
    event = _event(run_id, sequence=1, event_type="tool.replay")
    before_events, before_outbox = await _counts(repository, run_id)

    await repository.append_event(run_id, owner, from_agent_event(event), lease_epoch=epoch)
    events, outbox = await _counts(repository, run_id)
    assert events == before_events + 1
    assert outbox == before_outbox  # no public Outbox for internal replay
    async with repository.engine.connect() as conn:
        assert not await conn.scalar(
            text("SELECT 1 FROM runtime_event_outbox WHERE run_id=:id AND event_id=:event_id"),
            {"id": run_id, "event_id": event.event_id},
        )
