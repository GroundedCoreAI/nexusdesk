"""Phase 6 T-03: monotonic lease epochs and zero effective stale writes.

The PostgreSQL matrix claims a Run as Worker A, takes it over as Worker B with
a larger epoch, then lets A attempt every fenced mutation (snapshot, append,
finish, heartbeat, usage, tool replay, process record, Workdir). Every stale
attempt must write nothing, and each denial must be recorded in a separate
transaction. A unit test covers the in-memory resource-release guard, which
cannot be proven by SQL alone.
"""

import asyncio
import os
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from test_agent_execution_phase3_snapshots import make_payloads

from agent_platform.applications.platform_runtime.runtime_hooks import (
    BusinessRuntimePersistenceHooks,
)
from agent_platform.core_platform.agent_execution.contracts import ConfigurationError
from agent_platform.core_platform.agent_execution.host.process_registry import ProcessRegistry
from agent_platform.core_platform.agent_execution.host.resource_manager import ResourceManager
from agent_platform.core_platform.agent_execution.host.sandbox_provider import SandboxReservation
from agent_platform.core_platform.agent_execution.reliability.ownership import (
    ExecutionOwnership,
    OwnershipDenied,
)
from agent_platform.core_platform.agent_execution.workspace.workspace_manager import (
    ExecutionWorkspaceManager,
)
from agent_platform.core_platform.agent_runtime.repository import RunRepository
from agent_platform.core_platform.agent_runtime.schemas import RunRequest
from agent_platform.core_platform.platform_services.persistence.database import create_engine
from agent_platform.core_platform.platform_services.platform_settings.settings import Settings
from agent_platform.core_platform.tool_gateway.replay import DurableToolReplayCache

pytestmark = [pytest.mark.asyncio, pytest.mark.postgres]


@pytest_asyncio.fixture
async def repo():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a migrated, dedicated PostgreSQL test database")
    tenant = "fencing-" + uuid4().hex
    settings = Settings(database_url=url, tenant_id=tenant, embedded_worker=False)
    engine = create_engine(settings)
    repository = RunRepository(engine, BusinessRuntimePersistenceHooks())
    try:
        yield repository, tenant, url
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


async def _claim(repo, tenant, owner, *, conversation="f"):
    submitted = await repo.submit(
        tenant,
        RunRequest(conversation_id=conversation, message="fencing"),
        {"fingerprint": "phase6"},
        1000,
        100,
        120,
    )
    claimed = await repo.claim(owner, 120, tenant)
    assert claimed is not None and claimed["id"] == submitted["id"]
    return claimed


async def _takeover(repo, tenant, owner):
    # Simulate the expired lease a takeover is allowed to recover; the epoch
    # increment itself is what this test matrix exercises.
    async with repo.engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE runtime_runs SET lease_until=now()-interval '1 second'"
                " WHERE tenant_id=:tenant AND status='running'"
            ),
            {"tenant": tenant},
        )
    row = await repo.takeover(owner, 120, tenant)
    assert row is not None
    return row


async def _denials(repo, run_id):
    async with repo.engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT operation,reason,stale_owner,stale_lease_epoch,"
                    "current_owner,current_lease_epoch FROM execution_fencing_denials"
                    " WHERE run_id=:id ORDER BY created_at"
                ),
                {"id": run_id},
            )
        ).mappings()
        return [dict(row) for row in rows]


async def _event_count(repo, run_id):
    async with repo.engine.connect() as conn:
        return await conn.scalar(
            text("SELECT count(*) FROM runtime_events WHERE run_id=:id"), {"id": run_id}
        )


async def _outbox_count(repo, run_id):
    async with repo.engine.connect() as conn:
        return await conn.scalar(
            text("SELECT count(*) FROM runtime_event_outbox WHERE run_id=:id"), {"id": run_id}
        )


async def _run_row(repo, run_id):
    async with repo.engine.connect() as conn:
        return (
            (await conn.execute(text("SELECT * FROM runtime_runs WHERE id=:id"), {"id": run_id}))
            .mappings()
            .one()
        )


async def test_claim_epoch_and_takeover_are_monotonic(repo):
    repository, tenant, _ = repo
    owner_a, owner_b = uuid4(), uuid4()

    claimed = await _claim(repository, tenant, owner_a)
    assert claimed["lease_epoch"] == 1
    assert claimed["owner"] == owner_a

    taken = await _takeover(repository, tenant, owner_b)
    assert taken["id"] == claimed["id"]
    assert taken["lease_epoch"] == 2
    assert taken["owner"] == owner_b

    # The old epoch is no longer a valid heartbeat and is audited.
    assert await repository.heartbeat(claimed["id"], owner_a, 120, lease_epoch=1) == "lost"
    denials = await _denials(repository, claimed["id"])
    assert [d["operation"] for d in denials] == ["heartbeat"]
    assert denials[0]["stale_lease_epoch"] == 1
    assert denials[0]["current_lease_epoch"] == 2
    assert denials[0]["stale_owner"] == owner_a
    assert denials[0]["current_owner"] == owner_b

    assert await repository.heartbeat(claimed["id"], owner_b, 120, lease_epoch=2) == "ok"


async def test_stale_append_rolls_back_with_zero_events_and_audits(repo):
    repository, tenant, _ = repo
    owner_a, owner_b = uuid4(), uuid4()
    claimed = await _claim(repository, tenant, owner_a)
    await _takeover(repository, tenant, owner_b)
    run_id = claimed["id"]

    before = await _event_count(repository, run_id)
    with pytest.raises(asyncio.CancelledError):
        await repository.append(run_id, owner_a, "tool.result", {"stale": True}, lease_epoch=1)
    assert await _event_count(repository, run_id) == before

    denials = await _denials(repository, run_id)
    assert denials[-1]["operation"] == "append"
    assert denials[-1]["reason"] in {"stale_epoch", "owner_mismatch"}
    assert not any(row["reason"] == "append" for row in denials)

    # The current epoch still writes.
    await repository.append(run_id, owner_b, "tool.result", {"ok": True}, lease_epoch=2)
    assert await _event_count(repository, run_id) == before + 1


async def test_stale_snapshot_and_finish_are_denied(repo):
    repository, tenant, _ = repo
    owner_a, owner_b = uuid4(), uuid4()
    claimed = await _claim(repository, tenant, owner_a)
    await _takeover(repository, tenant, owner_b)
    run_id = claimed["id"]
    payloads = make_payloads(run_id)

    stale = await repository.write_execution_snapshots(run_id, owner_a, payloads, lease_epoch=1)
    assert stale.outcome in {"lease_lost", "not_claimed"}
    row = await _run_row(repository, run_id)
    assert row["execution_config_snapshot"] is None
    denials = await _denials(repository, run_id)
    assert denials[-1]["operation"] == "snapshot"

    current = await repository.write_execution_snapshots(run_id, owner_b, payloads, lease_epoch=2)
    assert current.succeeded

    # Stale finish cannot complete the Run; the row stays running under B.
    await repository.finish(run_id, owner_a, "completed", output="stale", lease_epoch=1)
    row = await _run_row(repository, run_id)
    assert row["status"] == "running"
    denials = await _denials(repository, run_id)
    assert denials[-1]["operation"] == "finish"

    # The current epoch completes exactly once and records terminal usage.
    await repository.finish(
        run_id,
        owner_b,
        "completed",
        output="ok",
        history=[{"role": "assistant", "content": "ok"}],
        usage={"total_tokens": 7},
        lease_epoch=2,
    )
    row = await _run_row(repository, run_id)
    assert row["status"] == "completed"
    async with repository.engine.connect() as conn:
        usage = (
            await conn.execute(
                text("SELECT count(*) FROM runtime_usage_ledger WHERE run_id=:id"),
                {"id": run_id},
            )
        ).scalar()
    assert usage == 1

    # Duplicate finish is a terminal no-op; usage is never recounted.
    await repository.finish(
        run_id, owner_b, "completed", output="again", usage={"total_tokens": 7}, lease_epoch=2
    )
    async with repository.engine.connect() as conn:
        usage = (
            await conn.execute(
                text("SELECT count(*) FROM runtime_usage_ledger WHERE run_id=:id"),
                {"id": run_id},
            )
        ).scalar()
    assert usage == 1


async def test_stale_usage_is_denied_and_corrections_are_traceable(repo):
    repository, tenant, _ = repo
    owner_a, owner_b = uuid4(), uuid4()
    claimed = await _claim(repository, tenant, owner_a)
    await _takeover(repository, tenant, owner_b)
    run_id = claimed["id"]

    outbox_before = await _outbox_count(repository, run_id)
    denied = await repository.record_usage(
        run_id=run_id,
        tenant_id=tenant,
        ownership=ExecutionOwnership(run_id, owner_a, 1),
        source="engine_terminal",
        source_event_id="result",
        usage={"total_tokens": 3},
    )
    assert denied is None
    assert await _outbox_count(repository, run_id) == outbox_before
    denials = await _denials(repository, run_id)
    assert denials[-1]["operation"] == "usage"

    first = await repository.record_usage(
        run_id=run_id,
        tenant_id=tenant,
        ownership=ExecutionOwnership(run_id, owner_b, 2),
        source="engine_terminal",
        source_event_id="result",
        usage={"total_tokens": 3},
    )
    assert first is not None
    # Duplicate source returns the original row without consuming events.
    duplicate = await repository.record_usage(
        run_id=run_id,
        tenant_id=tenant,
        ownership=ExecutionOwnership(run_id, owner_b, 2),
        source="engine_terminal",
        source_event_id="result",
        usage={"total_tokens": 99},
    )
    assert duplicate is not None and duplicate["id"] == first["id"]

    correction = await repository.record_usage(
        run_id=run_id,
        tenant_id=tenant,
        ownership=ExecutionOwnership(run_id, owner_b, 2),
        source="provider_correction",
        source_event_id="correction-1",
        usage={"total_tokens": 5},
        supersedes_id=first["id"],
    )
    assert correction is not None and correction["supersedes_id"] == first["id"]
    unknown = await repository.record_usage(
        run_id=run_id,
        tenant_id=tenant,
        ownership=ExecutionOwnership(run_id, owner_b, 2),
        source="engine_native",
        source_event_id="native-1",
        usage={"status": "unknown"},
    )
    assert unknown is not None

    summary = await repository.usage_summary(run_id, tenant)
    assert summary["records"] == 3
    assert summary["effective_records"] == 2  # correction supersedes the first terminal row
    assert summary["unknown_records"] == 1  # the native unknown row, counted honestly
    assert summary["effective_total_tokens"] == 5  # correction replaces, never adds
    assert summary["effective_unknown_records"] == 1


async def test_tool_replay_is_fenced_but_internal(repo):
    repository, tenant, _ = repo
    owner_a, owner_b = uuid4(), uuid4()
    claimed = await _claim(repository, tenant, owner_a)
    await _takeover(repository, tenant, owner_b)
    run_id = claimed["id"]
    key = f"runtime:{run_id}:" + "a" * 64
    cache = DurableToolReplayCache(repository.engine)
    outbox_before = await _outbox_count(repository, run_id)

    with pytest.raises(OwnershipDenied):
        await cache.put(key, {"result": "stale"}, owner=owner_a, lease_epoch=1)
    assert not await cache.get(key)
    denials = await _denials(repository, run_id)
    assert denials[-1]["operation"] == "tool_replay"

    await cache.put(key, {"result": "current"}, owner=owner_b, lease_epoch=2)
    assert await cache.get(key) == {"result": "current"}
    # Internal replay gets identity but adds no public Outbox row.
    assert await _outbox_count(repository, run_id) == outbox_before
    async with repository.engine.connect() as conn:
        replay = (
            await conn.execute(
                text(
                    "SELECT event_id,seq FROM runtime_events"
                    " WHERE run_id=:id AND type='tool.replay'"
                ),
                {"id": run_id},
            )
        ).first()
    assert replay is not None and replay[0] is not None
    async with repository.engine.connect() as conn:
        assert not await conn.scalar(
            text("SELECT 1 FROM runtime_event_outbox WHERE run_id=:id AND seq=:seq"),
            {"id": run_id, "seq": replay[1]},
        )
    # Idempotent: a second current put does not allocate another sequence.
    count = await _event_count(repository, run_id)
    await cache.put(key, {"result": "current"}, owner=owner_b, lease_epoch=2)
    assert await _event_count(repository, run_id) == count


async def test_process_registry_fences_stale_records(repo):
    repository, tenant, url = repo
    owner_a, owner_b = uuid4(), uuid4()
    claimed = await _claim(repository, tenant, owner_a)
    await _takeover(repository, tenant, owner_b)
    run_id = claimed["id"]
    engine = create_engine(
        Settings(
            database_url=url,
            tenant_id=tenant,
            embedded_worker=False,
        )
    )
    registry = ProcessRegistry(
        engine,
        host_id="fencing-host",
        host_instance_id="boot-1",
        alert_sink=None,
    )
    managed_id = uuid4()
    try:
        with pytest.raises(OwnershipDenied):
            await registry.register_starting(
                managed_id=managed_id,
                run_id=run_id,
                tenant_id=tenant,
                command_digest="sha256:" + "0" * 64,
                ownership=ExecutionOwnership(run_id, owner_a, 1),
            )
        async with engine.connect() as conn:
            assert not await conn.scalar(
                text("SELECT 1 FROM runtime_host_processes WHERE id=:id"), {"id": managed_id}
            )
        denials = await _denials(repository, run_id)
        assert denials[-1]["operation"] == "process"

        await registry.register_starting(
            managed_id=managed_id,
            run_id=run_id,
            tenant_id=tenant,
            command_digest="sha256:" + "0" * 64,
            ownership=ExecutionOwnership(run_id, owner_b, 2),
        )
        # A stale conditional state move changes zero rows and is audited.
        assert not await registry.mark_state(
            managed_id=managed_id,
            from_states=("starting",),
            to_status="exited",
            ownership=ExecutionOwnership(run_id, owner_a, 1),
            run_id=run_id,
        )
        denials = await _denials(repository, run_id)
        assert sum(1 for d in denials if d["operation"] == "process") >= 2
        assert await registry.mark_state(
            managed_id=managed_id,
            from_states=("starting",),
            to_status="exited",
            ownership=ExecutionOwnership(run_id, owner_b, 2),
            run_id=run_id,
        )
    finally:
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM runtime_host_processes WHERE run_id=:id"), {"id": run_id}
            )
        await engine.dispose()


async def test_workspace_operations_fence_stale_ownership(repo, tmp_path: Path):
    repository, tenant, url = repo
    owner_a, owner_b = uuid4(), uuid4()
    claimed = await _claim(repository, tenant, owner_a)
    await _takeover(repository, tenant, owner_b)
    run_id = claimed["id"]
    engine = create_engine(Settings(database_url=url, tenant_id=tenant, embedded_worker=False))
    workspace = ExecutionWorkspaceManager(
        engine,
        root=tmp_path / "execution",
        quota_bytes=1_000_000,
        retention_seconds=60,
        failed_retention_seconds=60,
    )
    try:
        with pytest.raises(OwnershipDenied):
            await workspace.prepare(
                run_id=run_id,
                tenant_id=tenant,
                business_id="biz",
                workspace_id="ws",
                ownership=ExecutionOwnership(run_id, owner_a, 1),
            )
        denials = await _denials(repository, run_id)
        assert denials[-1]["operation"] == "workdir"

        record = await workspace.prepare(
            run_id=run_id,
            tenant_id=tenant,
            business_id="biz",
            workspace_id="ws",
            ownership=ExecutionOwnership(run_id, owner_b, 2),
        )
        assert record.status in {"ready", "active"}
        # A stale retain/cleanup cannot move or remove the current record.
        with pytest.raises(OwnershipDenied):
            await workspace.activate(
                workdir_id=record.workdir_id,
                run_id=run_id,
                tenant_id=tenant,
                ownership=ExecutionOwnership(run_id, owner_a, 1),
            )
        assert (await workspace.get(run_id=run_id, tenant_id=tenant)).status in {
            "ready",
            "active",
        }
        # Current epoch can retain and clean up.
        await workspace.activate(
            workdir_id=record.workdir_id,
            run_id=run_id,
            tenant_id=tenant,
            ownership=ExecutionOwnership(run_id, owner_b, 2),
        )
        await workspace.retain(
            workdir_id=record.workdir_id,
            run_id=run_id,
            tenant_id=tenant,
            outcome="success",
            ownership=ExecutionOwnership(run_id, owner_b, 2),
        )
        final = await workspace.cleanup(
            workdir_id=record.workdir_id,
            run_id=run_id,
            tenant_id=tenant,
            ownership=ExecutionOwnership(run_id, owner_b, 2),
        )
        assert final.status == "deleted"
    finally:
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM execution_workdirs WHERE run_id=:id"), {"id": run_id}
            )
        await engine.dispose()


class _FakeSandbox:
    def __init__(self):
        self.released = []

    async def release(self, reservation):
        self.released.append(reservation.reservation_id)


async def test_resource_release_honors_an_ownership_guard():
    sandbox = _FakeSandbox()
    resources = ResourceManager(sandbox, sample_interval_seconds=1.0)
    reservation = SandboxReservation(
        reservation_id=uuid4(),
        run_id=uuid4(),
        provider_id="local",
        provider_version="v1",
        resolutions=(),
        policy_digest="x",
    )
    ownership = ExecutionOwnership(reservation.run_id, uuid4(), 1)
    releases = []

    async def authorize(candidate, operation):
        releases.append((candidate, operation))
        return False

    released = await resources.release(reservation, ownership=ownership, authorize=authorize)
    assert released is False
    assert sandbox.released == []
    assert releases == [(ownership, "resource_release")]

    released = await resources.release(reservation)
    assert released is True
    assert sandbox.released == [reservation.reservation_id]


async def test_execution_context_validates_and_carries_lease_epoch():
    from agent_platform.core_platform.agent_execution.orchestration.execution_context import (
        build_execution_context,
    )

    run_id = uuid4()
    row = {"id": run_id, "tenant_id": "t", "input": "x", "config": {"fingerprint": "f"}}
    context = build_execution_context(
        row,
        history=[],
        owner=uuid4(),
        lease_epoch=1,
        execution_phase3_enabled=False,
    )
    assert context.lease_epoch == 1
    for bad in (0, -1, True, "1"):
        with pytest.raises(ConfigurationError):
            build_execution_context(row, history=[], owner=uuid4(), lease_epoch=bad)
