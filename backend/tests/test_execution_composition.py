"""Phase 6 T-10: startup recovery, Outbox/retention loops, deployment wiring."""

import os
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text

from agent_platform.applications.platform_runtime import runtime_composition
from agent_platform.applications.platform_runtime.runtime_hooks import (
    BusinessRuntimePersistenceHooks,
)
from agent_platform.core_platform.agent_execution.contracts import AgentEvent
from agent_platform.core_platform.agent_execution.events.envelope import from_agent_event
from agent_platform.core_platform.agent_runtime.repository import RunRepository
from agent_platform.core_platform.agent_runtime.schemas import RunRequest
from agent_platform.core_platform.platform_services.persistence.database import create_engine
from agent_platform.core_platform.platform_services.platform_settings.settings import Settings

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent


@pytest_asyncio.fixture
async def repo():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a migrated, dedicated PostgreSQL test database")
    tenant = "composition-" + uuid4().hex
    settings = Settings(database_url=url, tenant_id=tenant, embedded_worker=False)
    engine = create_engine(settings)
    repository = RunRepository(engine, BusinessRuntimePersistenceHooks())
    try:
        yield repository, tenant, engine
    finally:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "DELETE FROM execution_fencing_denials WHERE run_id IN "
                    "(SELECT id FROM runtime_runs WHERE tenant_id=:t)"
                ),
                {"t": tenant},
            )
            await conn.execute(text("DELETE FROM runtime_runs WHERE tenant_id=:t"), {"t": tenant})
            await conn.execute(
                text("DELETE FROM runtime_conversations WHERE tenant_id=:t"), {"t": tenant}
            )
        await engine.dispose()


async def _append(repository, run_id, owner, epoch, index):
    event = AgentEvent(
        event_id=uuid4(),
        execution_id=run_id,
        engine_id="react",
        protocol_id="native",
        adapter_version="v1",
        sequence=index,
        event_type="extension.note",
        source="engine_native",
        timestamp=__import__("datetime").datetime.now(__import__("datetime").UTC),
        payload={"note": index},
    )
    return await repository.append_event(run_id, owner, from_agent_event(event), lease_epoch=epoch)


@pytest.mark.asyncio
async def test_retention_cleanup_advances_floor_and_never_deletes_pending_outbox(repo):
    repository, tenant, engine = repo
    run = await repository.submit(
        tenant,
        RunRequest(conversation_id="ret-" + uuid4().hex[:8], message="retention"),
        {"fingerprint": "ret"},
        1000,
        100,
        120,
    )
    owner = uuid4()
    claimed = await repository.claim(owner, 120, tenant)
    epoch = claimed["lease_epoch"]
    first = await _append(repository, run["id"], owner, epoch, 1)
    pending = await _append(repository, run["id"], owner, epoch, 2)

    # Publish one Outbox row; leave the second pending and make all events old.
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE runtime_event_outbox SET status='published',published_at=now()"
                " WHERE run_id=:id AND seq=:seq"
            ),
            {"id": run["id"], "seq": first.seq},
        )
        await conn.execute(
            text("UPDATE runtime_events SET created_at=now()-interval '40 days' WHERE run_id=:id"),
            {"id": run["id"]},
        )
        await conn.execute(
            text(
                "INSERT INTO execution_credential_audit(tenant_id,action) "
                "VALUES (:t,'grant_denied')"
            ),
            {"t": tenant},
        )
    removed = await repository.cleanup_retention(30)
    assert removed >= 1
    async with engine.connect() as conn:
        remaining = (
            (
                await conn.execute(
                    text("SELECT seq FROM runtime_events WHERE run_id=:id ORDER BY seq"),
                    {"id": run["id"]},
                )
            )
            .scalars()
            .all()
        )
        floor = await conn.scalar(
            text("SELECT event_retention_floor_seq FROM runtime_runs WHERE id=:id"),
            {"id": run["id"]},
        )
        audit = await conn.scalar(
            text("SELECT count(*) FROM execution_credential_audit WHERE tenant_id=:t"),
            {"t": tenant},
        )
    assert pending.seq in remaining  # unpublished Outbox event is never deleted
    assert first.seq not in remaining
    assert floor > 0
    assert audit == 1  # accounting/audit rows are never retention candidates


@pytest.mark.asyncio
async def test_outbox_pending_count_is_tenant_scoped(repo):
    repository, tenant, engine = repo
    run = await repository.submit(
        tenant,
        RunRequest(conversation_id="count-" + uuid4().hex[:8], message="c"),
        {"fingerprint": "c"},
        1000,
        100,
        120,
    )
    claimed = await repository.claim(uuid4(), 120, tenant)
    await _append(repository, run["id"], claimed["owner"], claimed["lease_epoch"], 1)
    from agent_platform.core_platform.agent_execution.events.outbox import OutboxDispatcher

    class Publisher:
        async def enqueue(self, event):
            return False  # keep pending

    dispatcher = OutboxDispatcher(engine, Publisher(), tenant_id=tenant)
    assert await dispatcher.pending_count() >= 3
    assert await OutboxDispatcher(engine, Publisher(), tenant_id="other").pending_count() == 0


@pytest.mark.asyncio
async def test_subsystem_starts_and_stops_outbox_and_retention_loops():
    class Outbox:
        async def dispatch_once(self):
            return 0

        async def reconcile(self):
            return 0

        async def pending_count(self):
            return 4

    class Host:
        async def reconcile(self):
            return None

        async def close(self):
            return 0

    class Repo:
        async def cleanup_retention(self, days):
            return 0

        async def expired_running(self, tenant, batch=100):
            return []

        async def apply_recovery(self, items, *, new_owner):
            return 0

    class Registry:
        host_id = "host"

    class Workspace:
        async def sweep_expired(self):
            return []

    subsystem = runtime_composition.ExecutionRuntimeSubsystem(
        host=Host(),
        workspace=Workspace(),
        registry=Registry(),
        resources=object(),
        reconcile_interval_seconds=0.01,
        cleanup_interval_seconds=0.01,
        repository=Repo(),
        tenant_id="t",
        outbox=Outbox(),
        outbox_poll_seconds=0.01,
        retention_days=30,
        retention_cleanup_enabled=True,
        retention_interval_seconds=0.01,
    )
    await subsystem.recover_on_startup()
    subsystem.start()
    assert len(subsystem._tasks) == 4
    assert await subsystem.operational_stats() == {"outbox_pending": 4, "retention_enabled": 1}
    await subsystem.aclose()
    assert subsystem._tasks == []


def test_off_state_builds_no_execution_runtime():
    settings = Settings(_env_file=None)
    assert runtime_composition._build_execution_runtime_subsystem(settings, object()) is None


def test_docker_settings_select_the_docker_provider():
    settings = Settings(
        _env_file=None,
        execution_runtime_host_id="runtime-01",
        execution_sandbox_provider="docker",
        execution_sandbox_docker_image="alpine:latest",
    )
    subsystem = runtime_composition._build_execution_runtime_subsystem(settings, object())
    assert subsystem is not None
    assert subsystem.resources.sandbox_provider.provider_id == "docker"


def test_env_and_compose_are_secret_free_and_carry_phase6_switches():
    env = (BACKEND / ".env.example").read_text()
    for key in (
        "AGENT_EXECUTION_UNTRUSTED_TENANTS_ENABLED",
        "AGENT_EXECUTION_SANDBOX_PROVIDER",
        "AGENT_EXECUTION_SANDBOX_DOCKER_IMAGE",
        "AGENT_EXECUTION_OUTBOX_ENABLED",
        "AGENT_EXECUTION_EVENT_RETENTION_DAYS",
        "AGENT_EXECUTION_EVENT_CLEANUP_ENABLED",
        "AGENT_EXECUTION_CREDENTIAL_KEY_FILE",
        "AGENT_EXECUTION_PARSER_RAW_SAMPLE_ENABLED",
    ):
        assert key in env
    production_env = (REPO / "deploy/production/.env.example").read_text()
    for key in (
        "AGENT_EXECUTION_UNTRUSTED_TENANTS_ENABLED",
        "AGENT_EXECUTION_SANDBOX_DOCKER_IMAGE",
        "AGENT_EXECUTION_OUTBOX_ENABLED",
        "AGENT_EXECUTION_EVENT_CLEANUP_ENABLED",
        "AGENT_EXECUTION_CREDENTIAL_KEY_FILE",
    ):
        assert key in production_env
    for compose in (
        REPO / "deploy/quickstart/compose.yaml",
        REPO / "deploy/production/compose.yaml",
    ):
        text = compose.read_text()
        assert "AGENT_EXECUTION_UNTRUSTED_TENANTS_ENABLED" in text
        assert "AGENT_EXECUTION_OUTBOX_ENABLED" in text
    for text in (env, production_env):
        assert "BEGIN PRIVATE KEY" not in text
        assert "fernet:" not in text
