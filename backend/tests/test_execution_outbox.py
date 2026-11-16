"""Phase 6 T-04: transactional Outbox onto the existing durable event bus.

One publishable durable event yields one Outbox row in the same transaction.
The dispatcher builds the existing EventEnvelope contract, enqueues it through
an *acknowledged* port on DurableEventBus, and only then marks it published.
Crash-before/after publication is safe to retry because the event_id is the
bus idempotency key. Reconciliation recovers rows missing at/after the rollout
watermark and never republishes history.
"""

import os
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text

from agent_platform.applications.platform_runtime.runtime_hooks import (
    BusinessRuntimePersistenceHooks,
)
from agent_platform.core_platform.agent_execution.contracts import AgentEvent
from agent_platform.core_platform.agent_execution.events.envelope import from_agent_event
from agent_platform.core_platform.agent_execution.events.outbox import OutboxDispatcher
from agent_platform.core_platform.agent_runtime.repository import RunRepository
from agent_platform.core_platform.agent_runtime.schemas import RunRequest
from agent_platform.core_platform.platform_services.events import DurableEventBus
from agent_platform.core_platform.platform_services.persistence.database import create_engine
from agent_platform.core_platform.platform_services.platform_settings.settings import Settings
from agent_platform.extension_contracts import EventEnvelope

pytestmark = [pytest.mark.asyncio, pytest.mark.postgres]


class RecordingPublisher:
    def __init__(self) -> None:
        self.events: list[EventEnvelope] = []
        self.fail_next = False

    async def enqueue(self, event: EventEnvelope) -> bool:
        if self.fail_next:
            raise RuntimeError("transport unavailable")
        self.events.append(event)
        return True


@pytest_asyncio.fixture
async def outbox(repo):
    repository, tenant = repo
    engine = repository.engine
    publisher = RecordingPublisher()
    dispatcher = OutboxDispatcher(engine, publisher, batch_size=20, tenant_id=tenant)
    try:
        yield repository, tenant, engine, publisher, dispatcher
    finally:
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM memory_tasks WHERE tenant_id=:tenant"), {"tenant": tenant}
            )


@pytest_asyncio.fixture
async def repo():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a migrated, dedicated PostgreSQL test database")
    tenant = "outbox-" + uuid4().hex
    settings = Settings(database_url=url, tenant_id=tenant, embedded_worker=False)
    engine = create_engine(settings)
    repository = RunRepository(engine, BusinessRuntimePersistenceHooks())
    try:
        yield repository, tenant
    finally:
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM memory_tasks WHERE tenant_id=:tenant"), {"tenant": tenant}
            )
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


async def _claim(repo, tenant, owner, conversation="outbox"):
    submitted = await repo.submit(
        tenant,
        RunRequest(conversation_id=conversation, message="outbox"),
        {"fingerprint": "phase6"},
        1000,
        100,
        120,
    )
    row = await repo.claim(owner, 120, tenant)
    assert row is not None and row["id"] == submitted["id"]
    return row


async def _append(repository, run_id, owner, epoch, *, trace_id=None, event_type="extension.note"):
    event = AgentEvent(
        event_id=uuid4(),
        execution_id=run_id,
        engine_id="react",
        protocol_id="native",
        adapter_version="v1",
        sequence=1,
        event_type=event_type,
        source="engine_native",
        timestamp=datetime.now(UTC),
        payload={"note": "x"},
        trace_id=trace_id,
    )
    return await repository.append_event(
        run_id, owner, from_agent_event(event), lease_epoch=epoch
    ), event


async def _outbox_row(engine, run_id, seq):
    async with engine.connect() as conn:
        return (
            (
                await conn.execute(
                    text(
                        "SELECT status,attempts,last_error,available_at,published_at"
                        " FROM runtime_event_outbox WHERE run_id=:id AND seq=:seq"
                    ),
                    {"id": run_id, "seq": seq},
                )
            )
            .mappings()
            .first()
        )


async def test_dispatch_publishes_through_the_existing_envelope(outbox):
    repository, tenant, engine, publisher, dispatcher = outbox
    owner = uuid4()
    claimed = await _claim(repository, tenant, owner)
    run_id, epoch = claimed["id"], claimed["lease_epoch"]
    trace = uuid4()
    result, event = await _append(repository, run_id, owner, epoch, trace_id=str(trace))

    published = await dispatcher.dispatch_once()
    assert published >= 1
    row = await _outbox_row(engine, run_id, result.seq)
    assert row["status"] == "published"
    assert row["published_at"] is not None

    envelope = next(item for item in publisher.events if item.event_id == event.event_id)
    assert envelope.tenant_id == tenant
    assert envelope.aggregate_type == "runtime_run"
    assert envelope.aggregate_id == str(run_id)
    assert envelope.event_type == "extension.note"
    assert envelope.event_version == 1
    assert envelope.idempotency_key == str(event.event_id)
    assert envelope.correlation_id == trace
    assert envelope.payload == {"note": "x"}
    # A second scan does not republish the already-published row.
    assert await dispatcher.dispatch_once() == 0


async def test_trace_id_that_is_not_a_uuid_never_becomes_correlation(outbox):
    repository, tenant, _engine, publisher, dispatcher = outbox
    owner = uuid4()
    claimed = await _claim(repository, tenant, owner)
    run_id, epoch = claimed["id"], claimed["lease_epoch"]
    _result, event = await _append(repository, run_id, owner, epoch, trace_id="not-a-uuid")

    await dispatcher.dispatch_once()
    envelope = next(item for item in publisher.events if item.event_id == event.event_id)
    assert envelope.correlation_id is None


async def test_failed_publication_stays_pending_with_bounded_error(outbox):
    repository, tenant, engine, publisher, dispatcher = outbox
    owner = uuid4()
    claimed = await _claim(repository, tenant, owner)
    run_id, epoch = claimed["id"], claimed["lease_epoch"]
    result, _event = await _append(repository, run_id, owner, epoch)

    publisher.fail_next = True
    assert await dispatcher.dispatch_once() == 0
    row = await _outbox_row(engine, run_id, result.seq)
    assert row["status"] == "pending"
    assert row["attempts"] == 1
    assert row["last_error"] == "RuntimeError"  # type name only, no message/payload
    assert row["available_at"] > datetime.now(UTC)

    # Crash-before-publication retry: make it eligible and publish once.
    publisher.fail_next = False
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE runtime_event_outbox SET available_at=now() WHERE run_id=:id AND seq=:seq"
            ),
            {"id": run_id, "seq": result.seq},
        )
    assert await dispatcher.dispatch_once() >= 1
    row = await _outbox_row(engine, run_id, result.seq)
    assert row["status"] == "published"


async def test_reconcile_recovers_post_watermark_gaps_only(outbox):
    repository, tenant, engine, _publisher, dispatcher = outbox
    owner = uuid4()
    claimed = await _claim(repository, tenant, owner)
    run_id, epoch = claimed["id"], claimed["lease_epoch"]
    result, _ = await _append(repository, run_id, owner, epoch)

    # Simulate a direct writer that bypassed the trigger: the event exists but
    # its Outbox row is missing. Reconciliation must recreate it.
    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM runtime_event_outbox WHERE run_id=:id AND seq=:seq"),
            {"id": run_id, "seq": result.seq},
        )
    assert await dispatcher.reconcile() >= 1
    assert (await _outbox_row(engine, run_id, result.seq))["status"] == "pending"
    assert await dispatcher.dispatch_once() >= 1

    # Pre-watermark history is never republished: move an event before the
    # recorded watermark, delete its Outbox row, and reconcile again.
    async with engine.begin() as conn:
        watermark = await conn.scalar(
            text("SELECT created_after FROM runtime_event_outbox_watermark WHERE id='default'")
        )
        await conn.execute(
            text("UPDATE runtime_events SET created_at=:created WHERE run_id=:id AND seq=:seq"),
            {
                "created": watermark.replace(year=watermark.year - 1),
                "id": run_id,
                "seq": result.seq,
            },
        )
        await conn.execute(
            text("DELETE FROM runtime_event_outbox WHERE run_id=:id AND seq=:seq"),
            {"id": run_id, "seq": result.seq},
        )
    assert await dispatcher.reconcile() == 0
    assert await _outbox_row(engine, run_id, result.seq) is None


async def test_durable_bus_enqueue_is_acknowledged_and_idempotent(outbox):
    _repository, tenant, engine, _publisher, _dispatcher = outbox
    bus = DurableEventBus(engine)
    event = EventEnvelope(
        event_id=uuid4(),
        event_type="extension.test",
        tenant_id=tenant,
        aggregate_type="runtime_run",
        aggregate_id=str(uuid4()),
        idempotency_key="idem-" + uuid4().hex,
    )

    assert await bus.enqueue(event) is True
    assert await bus.enqueue(event) is True
    async with engine.connect() as conn:
        tasks = await conn.scalar(
            text(
                "SELECT count(*) FROM memory_tasks WHERE tenant_id=:tenant"
                " AND kind='extension_event'"
            ),
            {"tenant": tenant},
        )
    assert tasks == 1
    assert UUID(event.event_id.hex) == event.event_id
