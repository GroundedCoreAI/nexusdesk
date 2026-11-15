"""Phase 3 additive runtime metadata migration and rollback compatibility."""

import asyncio
import json
import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import asyncpg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from test_ticket_migrations import migrate, query

from agent_platform.applications.platform_runtime.runtime_hooks import (
    BusinessRuntimePersistenceHooks,
)
from agent_platform.core_platform.agent_runtime.repository import RunRepository
from agent_platform.core_platform.agent_runtime.schemas import RunRequest
from agent_platform.core_platform.platform_services.persistence.database import create_engine
from agent_platform.core_platform.platform_services.platform_settings.settings import Settings

BACKEND = Path(__file__).resolve().parents[1]
REVISION = "0058_agent_execution_metadata"
PREVIOUS_REVISION = "0057_industry_pack_runtime"
SNAPSHOT_COLUMNS = (
    "execution_config_snapshot",
    "declared_capabilities_snapshot",
    "available_capabilities_snapshot",
    "effective_capabilities_snapshot",
    "execution_policy_snapshot",
)


@pytest.fixture
def migration_database():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a PostgreSQL role with CREATEDB")
    url = url.replace("postgresql+asyncpg://", "postgresql://")
    parts = urlsplit(url)
    name = "phase3_migration_" + uuid4().hex

    async def admin(statement):
        conn = await asyncpg.connect(url)
        try:
            await conn.execute(statement)
        finally:
            await conn.close()

    asyncio.run(admin(f'CREATE DATABASE "{name}"'))
    target = urlunsplit(parts._replace(path="/" + name))
    try:
        yield target
    finally:
        asyncio.run(admin(f'DROP DATABASE "{name}" WITH (FORCE)'))


class _OperationRecorder:
    def __init__(self):
        self.statements = []

    def execute(self, statement):
        self.statements.append(" ".join(statement.split()))


def _migration_module():
    config = Config(str(BACKEND / "alembic.ini"))
    return ScriptDirectory.from_config(config).get_revision(REVISION).module


def _runtime_columns(url):
    return {
        row[0]: (row[1], row[2], row[3])
        for row in query(
            url,
            "SELECT column_name,data_type,is_nullable,column_default"
            " FROM information_schema.columns WHERE table_name='runtime_runs'",
        )
    }


def _repository(url):
    settings = Settings(
        _env_file=None,
        database_url=url.replace("postgresql://", "postgresql+asyncpg://"),
        tenant_id="phase3-migration",
        embedded_worker=False,
    )
    engine = create_engine(settings)
    return engine, RunRepository(engine, BusinessRuntimePersistenceHooks())


async def _submit(repo, conversation_id):
    return await repo.submit(
        "phase3-migration",
        RunRequest(conversation_id=conversation_id, message="migration compatibility"),
        {"fingerprint": "phase2"},
        100,
        100,
        120,
    )


def test_0058_revision_chain_and_atomic_sql_contract(monkeypatch):
    migration = _migration_module()

    assert migration.revision == REVISION
    assert migration.down_revision == PREVIOUS_REVISION
    assert migration.branch_labels is None
    assert migration.depends_on is None

    recorder = _OperationRecorder()
    monkeypatch.setattr(migration, "op", recorder)
    migration.upgrade()

    assert len(recorder.statements) == 1
    upgrade = recorder.statements[0]
    assert upgrade.startswith("ALTER TABLE runtime_runs")
    assert upgrade.count("ADD COLUMN") == len(SNAPSHOT_COLUMNS)
    assert "DEFAULT" not in upgrade.upper()
    assert "UPDATE" not in upgrade.upper()
    for column in SNAPSHOT_COLUMNS:
        assert f"ADD COLUMN {column} JSONB NULL" in upgrade

    recorder.statements.clear()
    migration.downgrade()

    assert len(recorder.statements) == 1
    downgrade = recorder.statements[0]
    assert downgrade.startswith("ALTER TABLE runtime_runs")
    assert downgrade.count("DROP COLUMN") == len(SNAPSHOT_COLUMNS)
    assert "DROP COLUMN IF EXISTS" not in downgrade
    for column in SNAPSHOT_COLUMNS:
        assert f"DROP COLUMN {column}" in downgrade


@pytest.mark.postgres
def test_0058_upgrade_old_new_concurrent_repository_and_disposable_downgrade(
    migration_database,
):
    url = migration_database
    migrate(url, PREVIOUS_REVISION)
    columns_before = _runtime_columns(url)

    async def create_old_row():
        engine, repo = _repository(url)
        try:
            return (await _submit(repo, "legacy"))["id"]
        finally:
            await engine.dispose()

    old_run_id = asyncio.run(create_old_row())
    # Phase 4 (08 R-1) added migration 0059 behind this chain; the drift fix
    # targets the pinned 0058 revision explicitly instead of "head" so the
    # semantics ("upgrade to the revision under test adds exactly these
    # columns") survive any future migration, assertions unchanged.
    migrate(url, REVISION)

    columns_after = _runtime_columns(url)
    added_columns = set(columns_after) - set(columns_before)
    assert added_columns == set(SNAPSHOT_COLUMNS)
    assert query(url, "SELECT version_num FROM alembic_version")[0][0] == REVISION
    for column in SNAPSHOT_COLUMNS:
        data_type, nullable, default = columns_after[column]
        assert data_type == "jsonb"
        assert nullable == "YES"
        assert default is None

    old_snapshots = query(
        url,
        "SELECT execution_config_snapshot,declared_capabilities_snapshot,"
        "available_capabilities_snapshot,effective_capabilities_snapshot,"
        "execution_policy_snapshot FROM runtime_runs WHERE id=$1",
        old_run_id,
    )[0]
    assert list(old_snapshots) == [None] * len(SNAPSHOT_COLUMNS)

    snapshots = {
        column: {"schema_version": "v1", "execution_id": str(uuid4()), "column": column}
        for column in SNAPSHOT_COLUMNS
    }

    async def exercise_existing_repository():
        engine, repo = _repository(url)
        try:
            new_run = await _submit(repo, "current")

            async def write_new_run_snapshots():
                async with engine.begin() as conn:
                    await conn.execute(
                        text(
                            "UPDATE runtime_runs SET"
                            " execution_config_snapshot=CAST(:execution_config AS jsonb),"
                            " declared_capabilities_snapshot=CAST(:declared AS jsonb),"
                            " available_capabilities_snapshot=CAST(:available AS jsonb),"
                            " effective_capabilities_snapshot=CAST(:effective AS jsonb),"
                            " execution_policy_snapshot=CAST(:policy AS jsonb)"
                            " WHERE id=:id"
                        ),
                        {
                            "id": new_run["id"],
                            "execution_config": json.dumps(snapshots["execution_config_snapshot"]),
                            "declared": json.dumps(snapshots["declared_capabilities_snapshot"]),
                            "available": json.dumps(snapshots["available_capabilities_snapshot"]),
                            "effective": json.dumps(snapshots["effective_capabilities_snapshot"]),
                            "policy": json.dumps(snapshots["execution_policy_snapshot"]),
                        },
                    )

            reads = [repo.get(old_run_id, "phase3-migration") for _ in range(4)]
            reads.extend(repo.get(new_run["id"], "phase3-migration") for _ in range(4))
            results = await asyncio.gather(
                *reads,
                write_new_run_snapshots(),
                _submit(repo, "concurrent"),
            )
            assert all(row is not None for row in results[:8])
            assert results[-1]["status"] == "queued"
            return new_run["id"], results[-1]["id"]
        finally:
            await engine.dispose()

    new_run_id, concurrent_run_id = asyncio.run(exercise_existing_repository())
    stored = query(
        url,
        "SELECT execution_config_snapshot,declared_capabilities_snapshot,"
        "available_capabilities_snapshot,effective_capabilities_snapshot,"
        "execution_policy_snapshot FROM runtime_runs WHERE id=$1",
        new_run_id,
    )[0]
    assert {column: json.loads(stored[column]) for column in SNAPSHOT_COLUMNS} == snapshots
    assert (
        query(url, "SELECT status FROM runtime_runs WHERE id=$1", concurrent_run_id)[0][0]
        == "queued"
    )

    migrate(url, PREVIOUS_REVISION, "downgrade")
    assert _runtime_columns(url) == columns_before
    assert query(url, "SELECT count(*) FROM runtime_runs")[0][0] == 3
    assert query(url, "SELECT input FROM runtime_runs WHERE id=$1", old_run_id)[0][0] == (
        "migration compatibility"
    )

    migrate(url, REVISION)
    assert query(url, "SELECT version_num FROM alembic_version")[0][0] == REVISION
    assert set(_runtime_columns(url)) - set(columns_before) == set(SNAPSHOT_COLUMNS)
