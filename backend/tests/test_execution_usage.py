"""Phase 6 T-06: idempotent source-unique usage, corrections, no zero-fill.

Terminal/native usage is one ledger row per stable source identity. Duplicate
delivery never recounts, corrections form a supersedes chain, unknown stays
unknown, and aggregates are rebuildable from effective leaves only.
"""

import os
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text

from agent_platform.applications.platform_runtime.runtime_hooks import (
    BusinessRuntimePersistenceHooks,
)
from agent_platform.core_platform.agent_execution.events.usage import (
    NATIVE_USAGE_SOURCE,
    TERMINAL_USAGE_EVENT_ID,
    TERMINAL_USAGE_SOURCE,
    aggregate_effective_usage,
    normalize_usage,
)
from agent_platform.core_platform.agent_execution.reliability.ownership import ExecutionOwnership
from agent_platform.core_platform.agent_runtime.repository import RunRepository
from agent_platform.core_platform.agent_runtime.schemas import RunRequest
from agent_platform.core_platform.platform_services.persistence.database import create_engine
from agent_platform.core_platform.platform_services.platform_settings.settings import Settings

pytestmark = [pytest.mark.asyncio, pytest.mark.postgres]


async def test_normalize_usage_keeps_unknown_explicit_and_never_zero_fills():
    assert normalize_usage(None) == {"status": "unknown"}
    assert normalize_usage({}) == {"status": "unknown"}
    assert normalize_usage({"input_tokens": 0, "total_tokens": 5}) == {
        "input_tokens": 0,
        "total_tokens": 5,
    }
    # A missing key is absent, never invented as zero.
    normalized = normalize_usage({"input_tokens": 3})
    assert "output_tokens" not in normalized
    assert normalized["input_tokens"] == 3


async def test_normalize_usage_accepts_only_json_scalars_and_content_is_copied():
    source = {"total_tokens": 7, "model": "m1", "nested": {"x": 1}}
    normalized = normalize_usage(source)
    assert normalized == source
    normalized["total_tokens"] = 99
    assert source["total_tokens"] == 7


async def test_aggregate_effective_usage_ignores_superseded_rows():
    first = {
        "id": "a",
        "source": "engine_terminal",
        "usage": {"total_tokens": 3},
        "supersedes_id": None,
    }
    correction = {
        "id": "b",
        "source": "provider_correction",
        "usage": {"total_tokens": 5},
        "supersedes_id": "a",
    }
    unknown = {
        "id": "c",
        "source": "engine_native",
        "usage": {"status": "unknown"},
        "supersedes_id": None,
    }
    summary = aggregate_effective_usage([first, correction, unknown])
    assert summary["records"] == 3
    assert summary["effective_records"] == 2
    assert summary["effective_total_tokens"] == 5
    assert summary["effective_unknown_records"] == 1


@pytest_asyncio.fixture
async def repo():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a migrated, dedicated PostgreSQL test database")
    tenant = "usage-" + uuid4().hex
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


async def _claim(repo, tenant, owner):
    submitted = await repo.submit(
        tenant,
        RunRequest(conversation_id="usage-" + uuid4().hex[:8], message="usage"),
        {"fingerprint": "phase6"},
        1000,
        100,
        120,
    )
    row = await repo.claim(owner, 120, tenant)
    assert row is not None and row["id"] == submitted["id"]
    return row


async def _ledger(repo, run_id):
    async with repo.engine.connect() as conn:
        return (
            (
                await conn.execute(
                    text("SELECT * FROM runtime_usage_ledger WHERE run_id=:id ORDER BY created_at"),
                    {"id": run_id},
                )
            )
            .mappings()
            .all()
        )


async def test_terminal_finish_persists_unknown_usage_without_zero_fill(repo):
    repository, tenant = repo
    owner = uuid4()
    claimed = await _claim(repository, tenant, owner)
    run_id, epoch = claimed["id"], claimed["lease_epoch"]

    await repository.finish(
        run_id,
        owner,
        "completed",
        output="done",
        history=[],
        usage={},
        lease_epoch=epoch,
    )
    rows = await _ledger(repository, run_id)
    assert len(rows) == 1
    row = dict(rows[0])
    assert row["source"] == TERMINAL_USAGE_SOURCE
    assert row["source_event_id"] == TERMINAL_USAGE_EVENT_ID
    assert row["usage"] == {"status": "unknown"}
    assert row["cost"] is None
    assert row["is_estimate"] is False

    # Duplicate finish is terminal no-op: no second ledger row.
    await repository.finish(
        run_id, owner, "completed", output="again", usage={"total_tokens": 9}, lease_epoch=epoch
    )
    assert len(await _ledger(repository, run_id)) == 1


async def test_native_usage_is_idempotent_and_corrections_form_a_chain(repo):
    repository, tenant = repo
    owner = uuid4()
    claimed = await _claim(repository, tenant, owner)
    run_id, epoch = claimed["id"], claimed["lease_epoch"]
    ownership = ExecutionOwnership(run_id, owner, epoch)

    first = await repository.record_usage(
        run_id=run_id,
        tenant_id=tenant,
        ownership=ownership,
        source=NATIVE_USAGE_SOURCE,
        source_event_id="native-1",
        usage={"total_tokens": 3},
    )
    duplicate = await repository.record_usage(
        run_id=run_id,
        tenant_id=tenant,
        ownership=ownership,
        source=NATIVE_USAGE_SOURCE,
        source_event_id="native-1",
        usage={"total_tokens": 99},
    )
    assert first is not None and duplicate is not None
    assert duplicate["id"] == first["id"]
    assert duplicate["usage"] == {"total_tokens": 3}

    correction = await repository.record_usage(
        run_id=run_id,
        tenant_id=tenant,
        ownership=ownership,
        source="provider_correction",
        source_event_id="correction-1",
        usage={"total_tokens": 5},
        supersedes_id=first["id"],
        is_estimate=True,
    )
    assert correction is not None
    assert correction["supersedes_id"] == first["id"]

    summary = await repository.usage_summary(run_id, tenant)
    assert summary["records"] == 2
    assert summary["effective_records"] == 1
    assert summary["effective_total_tokens"] == 5
    assert summary["unknown_records"] == 0

    # Rebuild from the same effective-leaf rule equals the repository result.
    rows = [dict(row) for row in await _ledger(repository, run_id)]
    rebuilt = aggregate_effective_usage(rows)
    assert rebuilt["effective_total_tokens"] == summary["effective_total_tokens"]
    assert rebuilt["effective_records"] == summary["effective_records"]


async def test_old_epoch_usage_is_denied_and_creates_no_ledger_or_outbox(repo):
    repository, tenant = repo
    owner_a, owner_b = uuid4(), uuid4()
    claimed = await _claim(repository, tenant, owner_a)
    async with repository.engine.begin() as conn:
        await conn.execute(
            text("UPDATE runtime_runs SET lease_until=now()-interval '1 second' WHERE id=:id"),
            {"id": claimed["id"]},
        )
    taken = await repository.takeover(owner_b, 120, tenant)
    run_id, epoch = claimed["id"], taken["lease_epoch"]

    async with repository.engine.connect() as conn:
        outbox_before = await conn.scalar(
            text("SELECT count(*) FROM runtime_event_outbox WHERE run_id=:id"), {"id": run_id}
        )
    denied = await repository.record_usage(
        run_id=run_id,
        tenant_id=tenant,
        ownership=ExecutionOwnership(run_id, owner_a, 1),
        source=NATIVE_USAGE_SOURCE,
        source_event_id="late-1",
        usage={"total_tokens": 4},
    )
    assert denied is None
    assert not await _ledger(repository, run_id)
    async with repository.engine.connect() as conn:
        assert (
            await conn.scalar(
                text("SELECT count(*) FROM runtime_event_outbox WHERE run_id=:id"),
                {"id": run_id},
            )
            == outbox_before
        )
        denial = (
            await conn.execute(
                text(
                    "SELECT operation FROM execution_fencing_denials"
                    " WHERE run_id=:id ORDER BY created_at DESC LIMIT 1"
                ),
                {"id": run_id},
            )
        ).first()
    assert denial[0] == "usage"

    assert (
        await repository.record_usage(
            run_id=run_id,
            tenant_id=tenant,
            ownership=ExecutionOwnership(run_id, owner_b, epoch),
            source=NATIVE_USAGE_SOURCE,
            source_event_id="late-1",
            usage={"total_tokens": 4},
        )
        is not None
    )
