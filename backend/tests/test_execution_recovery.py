"""Phase 6 T-09: confirmed cancellation, takeover recovery, retry, quota release."""
import os
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text

from agent_platform.applications.platform_runtime.runtime_hooks import (
    BusinessRuntimePersistenceHooks,
)
from agent_platform.core_platform.agent_execution.reliability.recovery import (
    RecoveryCoordinator,
    terminal_decision,
)
from agent_platform.core_platform.agent_execution.reliability.retry import (
    RetryInput,
    classify_retry,
)
from agent_platform.core_platform.agent_runtime.repository import RunRepository
from agent_platform.core_platform.agent_runtime.schemas import RunRequest
from agent_platform.core_platform.platform_services.persistence.database import create_engine
from agent_platform.core_platform.platform_services.platform_settings.settings import Settings

pytestmark = [pytest.mark.asyncio, pytest.mark.postgres]


async def test_retry_matrix_only_retries_proven_safe_cases():
    assert classify_retry(RetryInput("pre_launch", side_effects=False)).action == "retry"
    ambiguous = classify_retry(RetryInput("ambiguous", side_effects=False))
    assert ambiguous.action == "manual"
    assert classify_retry(RetryInput("post_launch", side_effects=True)).action == "forbid"
    outbox = classify_retry(RetryInput("outbox", side_effects=False, idempotency_key="k"))
    assert outbox.action == "retry"
    outbox_unsafe = classify_retry(RetryInput("outbox", side_effects=True, idempotency_key=None))
    assert outbox_unsafe.action == "forbid"


async def test_terminal_decision_never_confirms_cancelled_without_cleanup():
    assert terminal_decision(cancel_requested=True, cleanup_confirmed=True) == (
        "cancelled",
        "completed",
    )
    assert terminal_decision(cancel_requested=True, cleanup_confirmed=False) == (
        "failed",
        "failed",
    )
    assert terminal_decision(cancel_requested=False, cleanup_confirmed=False) == (
        "failed",
        "failed",
    )


@pytest_asyncio.fixture
async def repo():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a migrated, dedicated PostgreSQL test database")
    tenant = "recovery-" + uuid4().hex
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


async def _claim(repo, tenant, owner, conversation="rec"):
    run = await repo.submit(
        tenant, RunRequest(conversation_id=conversation + "-" + uuid4().hex[:6], message="m"),
        {"fingerprint": "rec"}, 1000, 100, 120,
    )
    claimed = await repo.claim(owner, 120, tenant)
    assert claimed is not None and claimed["id"] == run["id"]
    return claimed


async def _row(engine, run_id):
    async with engine.connect() as conn:
        return (
            (await conn.execute(text("SELECT * FROM runtime_runs WHERE id=:id"), {"id": run_id}))
            .mappings().one()
        )


async def test_unconfirmed_cancellation_is_failed_never_cancelled(repo):
    repository, tenant, engine = repo
    owner = uuid4()
    claimed = await _claim(repository, tenant, owner)
    run_id = claimed["id"]
    await repository.cancel(run_id, tenant)
    row = await _row(engine, run_id)
    assert row["cancel_requested"] is True and row["cancel_requested_at"] is not None

    await repository.finish(
        run_id, owner, "cancelled", lease_epoch=claimed["lease_epoch"],
        cleanup_confirmed=False,
    )
    row = await _row(engine, run_id)
    assert row["status"] == "failed"
    assert row["error_code"] == "cancellation_unconfirmed"
    assert row["cleanup_status"] == "failed"
    assert row["cancel_confirmed_at"] is None


async def test_confirmed_cancellation_reports_cancelled_once(repo):
    repository, tenant, engine = repo
    owner = uuid4()
    claimed = await _claim(repository, tenant, owner)
    run_id = claimed["id"]
    await repository.cancel(run_id, tenant)
    await repository.finish(
        run_id, owner, "cancelled", lease_epoch=claimed["lease_epoch"],
        cleanup_confirmed=True,
    )
    row = await _row(engine, run_id)
    assert row["status"] == "cancelled"
    assert row["cleanup_status"] == "completed"
    assert row["cancel_confirmed_at"] is not None
    # Duplicate confirmation cannot create a second terminal event.
    before = await repository.events(run_id, tenant)
    await repository.finish(
        run_id, owner, "cancelled", lease_epoch=claimed["lease_epoch"],
        cleanup_confirmed=True,
    )
    assert await repository.events(run_id, tenant) == before


async def test_reap_confirms_cleanup_before_terminal_and_fences_old_worker(repo):
    repository, tenant, engine = repo
    owner_a = uuid4()
    claimed = await _claim(repository, tenant, owner_a)
    run_id = claimed["id"]
    await repository.cancel(run_id, tenant)
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE runtime_runs SET lease_until=now()-interval '1 second' WHERE id=:id"),
            {"id": run_id},
        )
    calls = []

    async def cleanup(row):
        calls.append(row["id"])
        return True

    coordinator = RecoveryCoordinator(repository, cleanup)
    assert await coordinator.recover_expired(tenant, new_owner=uuid4()) == 1
    row = await _row(engine, run_id)
    assert calls == [run_id]
    assert row["status"] == "cancelled"
    assert row["cleanup_status"] == "completed"
    assert row["cancel_confirmed_at"] is not None
    assert row["lease_epoch"] >= 2

    # Old epoch is fenced after takeover/terminal.
    assert await repository.heartbeat(run_id, owner_a, 120, lease_epoch=1) == "lost"


async def test_reap_cleanup_failure_is_failed_and_alertable(repo):
    repository, tenant, engine = repo
    owner = uuid4()
    claimed = await _claim(repository, tenant, owner)
    run_id = claimed["id"]
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE runtime_runs SET lease_until=now()-interval '1 second' WHERE id=:id"),
            {"id": run_id},
        )

    async def cleanup(_row):
        return False

    coordinator = RecoveryCoordinator(repository, cleanup)
    await coordinator.recover_expired(tenant, new_owner=uuid4())
    row = await _row(engine, run_id)
    assert row["status"] == "failed"
    assert row["error_code"] == "cleanup_failed"
    assert row["cleanup_status"] == "failed"


async def test_safe_retry_correlates_without_duplicate_attempts(repo):
    repository, tenant, engine = repo
    owner = uuid4()
    claimed = await _claim(repository, tenant, owner, conversation="retry")
    run_id = claimed["id"]
    await repository.finish(
        run_id, owner, "failed", error="pre_launch_failure",
        lease_epoch=claimed["lease_epoch"],
    )
    retried = await repository.prepare_retry(run_id, tenant)
    assert retried is not None
    assert retried["retry_of_run_id"] == run_id
    assert retried["attempt_no"] == 2
    # A second automatic retry of the same attempt is refused.
    assert await repository.prepare_retry(run_id, tenant) is None
    # Unsafe retry input is refused by the matrix before any row.
    assert classify_retry(RetryInput("ambiguous", side_effects=False)).action != "retry"
