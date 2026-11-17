"""Phase 4 migration 0059: two durable tables, indexes, FK semantics, rollback order.

RED/GREEN per 08 T2: the static tests pin the revision chain (08 R-1: head
0058_agent_execution_metadata), the additive two-table contract (no runtime_runs
columns, no RuntimeHost service table) and the disposable downgrade order
(processes before workdirs). The postgres-marked tests run the full chain on a
dedicated pgvector container via TEST_DATABASE_URL and exercise FK cascade /
SET NULL / uniqueness plus old React reads and writes across the upgrade.
"""

import asyncio
import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import asyncpg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from test_ticket_migrations import migrate, query

from agent_platform.applications.platform_runtime.runtime_hooks import (
    BusinessRuntimePersistenceHooks,
)
from agent_platform.core_platform.agent_runtime.repository import RunRepository
from agent_platform.core_platform.agent_runtime.schemas import RunRequest
from agent_platform.core_platform.platform_services.persistence.database import create_engine
from agent_platform.core_platform.platform_services.platform_settings.settings import Settings

BACKEND = Path(__file__).resolve().parents[1]
REVISION = "0059_execution_runtime_host"
PREVIOUS_REVISION = "0058_agent_execution_metadata"

WORKDIR_STATUSES = (
    "preparing",
    "ready",
    "active",
    "retained",
    "cleaning",
    "deleted",
    "cleanup_failed",
)
PROCESS_STATUSES = ("starting", "running", "terminating", "exited", "orphaned", "cleanup_failed")


@pytest.fixture
def migration_database():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a PostgreSQL role with CREATEDB")
    url = url.replace("postgresql+asyncpg://", "postgresql://")
    parts = urlsplit(url)
    name = "phase4_migration_" + uuid4().hex

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
        row[0]
        for row in query(
            url,
            "SELECT column_name FROM information_schema.columns WHERE table_name='runtime_runs'",
        )
    }


def _tables(url):
    return {
        row[0]
        for row in query(
            url,
            "SELECT table_name FROM information_schema.tables WHERE table_schema='public'",
        )
    }


def _columns(url, table):
    return {
        row[0]: (row[1], row[2], row[3])
        for row in query(
            url,
            "SELECT column_name,data_type,is_nullable,column_default"
            " FROM information_schema.columns WHERE table_name=$1",
            table,
        )
    }


def _indexes(url, table):
    return {
        row[0]: " ".join(row[1].split())
        for row in query(url, "SELECT indexname,indexdef FROM pg_indexes WHERE tablename=$1", table)
    }


def _constraint_defs(url, table, kind):
    # kind is inlined as a literal: pg_constraint.contype is the internal
    # "char" type and asyncpg cannot bind it as a text parameter.
    assert kind in {"c", "f"}
    return [
        " ".join(row[0].split())
        for row in query(
            url,
            f"SELECT pg_get_constraintdef(oid) FROM pg_constraint"
            f" WHERE conrelid=$1::regclass AND contype='{kind}'",
            table,
        )
    ]


def _execute(url, sql, *params):
    async def run():
        conn = await asyncpg.connect(url)
        try:
            return await conn.execute(sql, *params)
        finally:
            await conn.close()

    return asyncio.run(run())


def _repository(url, tenant):
    settings = Settings(
        _env_file=None,
        database_url=url.replace("postgresql://", "postgresql+asyncpg://"),
        tenant_id=tenant,
        embedded_worker=False,
    )
    engine = create_engine(settings)
    return engine, RunRepository(engine, BusinessRuntimePersistenceHooks())


def _clear_phase6_event_data(url):
    async def run():
        connection = await asyncpg.connect(url)
        try:
            for statement in (
                "DELETE FROM runtime_event_outbox",
                "DELETE FROM runtime_usage_ledger",
                "DELETE FROM execution_fencing_denials",
                "DELETE FROM runtime_events",
            ):
                await connection.execute(statement)
        finally:
            await connection.close()

    return asyncio.run(run())


def _submit_run(url, tenant, conversation_id):
    async def run():
        engine, repo = _repository(url, tenant)
        try:
            return (
                await repo.submit(
                    tenant,
                    RunRequest(conversation_id=conversation_id, message="phase4 migration"),
                    {"fingerprint": "phase4"},
                    100,
                    100,
                    120,
                )
            )["id"]
        finally:
            await engine.dispose()

    return asyncio.run(run())


_WORKDIR_INSERT = (
    "INSERT INTO execution_workdirs(id,run_id,tenant_id,business_id,workspace_id,"
    "relative_path,status,quota_bytes) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)"
)
_PROCESS_INSERT = (
    "INSERT INTO runtime_host_processes(id,run_id,workdir_id,tenant_id,host_id,"
    "host_instance_id,sandbox_provider,status,command_digest) "
    "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)"
)


def test_0059_revision_chain_is_a_single_head_on_0058():
    migration = _migration_module()
    config = Config(str(BACKEND / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)

    assert migration.revision == REVISION
    assert migration.down_revision == PREVIOUS_REVISION
    assert migration.branch_labels is None
    assert migration.depends_on is None
    # 08 R-1: 0059 must stay on the single linear chain; a divergent chain is a
    # planning defect. A later feature branch may merge two heads on top of it
    # (0067_merge_heads does), so the invariant is "exactly one head, and 0059
    # is an ancestor of that head".
    heads = scripts.get_heads()
    assert len(heads) == 1, heads
    # Walk every down_revision edge: the head may be a merge revision, so a
    # single-parent walk would only ever see one side of the graph.
    lineage: set[str] = set()
    pending = [heads[0]]
    while pending:
        revision_id = pending.pop()
        if revision_id in lineage:
            continue
        lineage.add(revision_id)
        down = scripts.get_revision(revision_id).down_revision
        if down is None:
            continue
        pending.extend(down if isinstance(down, tuple) else (down,))
    assert REVISION in lineage, sorted(lineage)


def test_0059_upgrade_sql_contract_is_two_tables_and_five_indexes(monkeypatch):
    migration = _migration_module()
    recorder = _OperationRecorder()
    monkeypatch.setattr(migration, "op", recorder)

    migration.upgrade()

    joined = "\n".join(recorder.statements)
    assert len(recorder.statements) == 7
    assert sum("CREATE TABLE" in statement for statement in recorder.statements) == 2
    assert sum("CREATE INDEX" in statement for statement in recorder.statements) == 5
    # Additive only: no rewrite of runtime_runs and no RuntimeHost service table.
    assert "ALTER TABLE" not in joined
    assert "UPDATE " not in joined.upper()
    assert "runtime_hosts" not in joined.lower().replace("runtime_host_processes", "")

    workdirs = next(s for s in recorder.statements if "CREATE TABLE execution_workdirs" in s)
    processes = next(s for s in recorder.statements if "CREATE TABLE runtime_host_processes" in s)

    for status in WORKDIR_STATUSES:
        assert f"'{status}'" in workdirs
    for status in PROCESS_STATUSES:
        assert f"'{status}'" in processes

    # One directory / one process group per Run, cascading with the Run row;
    # the Workdir association is SET NULL so Tombstones never erase process audit.
    cascade = "run_id UUID NOT NULL UNIQUE REFERENCES runtime_runs(id) ON DELETE CASCADE"
    assert cascade in workdirs
    assert cascade in processes
    assert "workdir_id UUID REFERENCES execution_workdirs(id) ON DELETE SET NULL" in processes
    assert "relative_path TEXT NOT NULL UNIQUE" in workdirs
    assert "quota_bytes BIGINT NOT NULL" in workdirs
    assert "size_bytes BIGINT NOT NULL DEFAULT 0" in workdirs
    assert "file_count INTEGER NOT NULL DEFAULT 0" in workdirs
    assert "metadata JSONB NOT NULL DEFAULT '{}'::jsonb" in processes
    assert "command_digest TEXT NOT NULL" in processes
    assert "last_observed_at TIMESTAMPTZ NOT NULL" in processes

    for name, table, columns in [
        ("execution_workdirs_status_expires", "execution_workdirs", "(status, expires_at)"),
        ("execution_workdirs_tenant_status", "execution_workdirs", "(tenant_id, status)"),
        ("runtime_host_processes_host_status", "runtime_host_processes", "(host_id, status)"),
        ("runtime_host_processes_observed", "runtime_host_processes", "(status, last_observed_at)"),
        ("runtime_host_processes_tenant_status", "runtime_host_processes", "(tenant_id, status)"),
    ]:
        assert f"CREATE INDEX {name} ON {table} {columns}" in joined


def test_0059_downgrade_drops_processes_before_workdirs(monkeypatch):
    migration = _migration_module()
    recorder = _OperationRecorder()
    monkeypatch.setattr(migration, "op", recorder)

    migration.downgrade()

    assert len(recorder.statements) == 2
    assert recorder.statements[0] == "DROP TABLE runtime_host_processes"
    assert recorder.statements[1] == "DROP TABLE execution_workdirs"


@pytest.mark.postgres
def test_0059_chain_fk_semantics_and_reacts_across_upgrade(migration_database):
    url = migration_database
    migrate(url, PREVIOUS_REVISION)
    columns_before = _runtime_columns(url)
    legacy_run_id = _submit_run(url, "phase4-migration", "legacy")

    result = migrate(url, "head")
    assert result.returncode == 0
    # Idempotent chain: a second upgrade to head is a no-op, not an error.
    assert migrate(url, "head").returncode == 0

    head = ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini"))).get_heads()[0]
    assert query(url, "SELECT version_num FROM alembic_version")[0][0] == head
    assert _tables(url) >= {"execution_workdirs", "runtime_host_processes"}
    # Phase 4's 0059 migration itself is additive. Later Phase 6 migrations
    # (0070) extend runtime_runs, so the head schema must be exactly the
    # pre-0059 columns plus that reviewed additive set -- never a rewrite or a
    # dropped legacy column.
    phase6_runtime_columns = {
        "lease_epoch",
        "cancel_requested_at",
        "cancel_confirmed_at",
        "cleanup_status",
        "cleanup_updated_at",
        "retry_of_run_id",
        "attempt_no",
        "side_effect_policy",
        "event_retention_floor_seq",
    }
    columns_at_head = _runtime_columns(url)
    assert set(columns_before) <= set(columns_at_head)
    assert set(columns_at_head) - set(columns_before) == phase6_runtime_columns

    workdir_columns = _columns(url, "execution_workdirs")
    assert set(workdir_columns) == {
        "id",
        "run_id",
        "tenant_id",
        "business_id",
        "workspace_id",
        "relative_path",
        "status",
        "quota_bytes",
        "size_bytes",
        "file_count",
        "expires_at",
        "last_error_code",
        "created_at",
        "updated_at",
        "cleaned_at",
    }
    assert workdir_columns["run_id"][:2] == ("uuid", "NO")
    assert workdir_columns["relative_path"][:2] == ("text", "NO")
    assert workdir_columns["quota_bytes"][0] == "bigint"
    assert workdir_columns["size_bytes"] == ("bigint", "NO", "0")
    assert workdir_columns["file_count"] == ("integer", "NO", "0")
    assert workdir_columns["expires_at"][1] == "YES"
    assert workdir_columns["cleaned_at"][1] == "YES"

    process_columns = _columns(url, "runtime_host_processes")
    assert set(process_columns) == {
        "id",
        "run_id",
        "workdir_id",
        "tenant_id",
        "host_id",
        "host_instance_id",
        "sandbox_provider",
        "status",
        "pid",
        "process_group_id",
        "process_start_token",
        "command_digest",
        "cancel_requested_at",
        "cleanup_deadline_at",
        "exit_code",
        "last_observed_at",
        "last_error_code",
        "metadata",
        "created_at",
        "updated_at",
        "started_at",
        "exited_at",
    }
    assert process_columns["command_digest"][:2] == ("text", "NO")
    assert process_columns["pid"] == ("integer", "YES", None)
    assert process_columns["workdir_id"][1] == "YES"
    assert process_columns["last_observed_at"][:2] == ("timestamp with time zone", "NO")
    assert "jsonb" == process_columns["metadata"][0]

    workdir_indexes = _indexes(url, "execution_workdirs")
    assert "execution_workdirs_status_expires" in workdir_indexes
    assert "execution_workdirs_tenant_status" in workdir_indexes
    assert workdir_indexes["execution_workdirs_status_expires"].endswith("(status, expires_at)")
    process_indexes = _indexes(url, "runtime_host_processes")
    assert "runtime_host_processes_host_status" in process_indexes
    assert "runtime_host_processes_observed" in process_indexes
    assert "runtime_host_processes_tenant_status" in process_indexes

    workdir_checks = _constraint_defs(url, "execution_workdirs", "c")
    assert any(
        all(f"'{status}'" in check for status in WORKDIR_STATUSES) for check in workdir_checks
    )
    process_checks = _constraint_defs(url, "runtime_host_processes", "c")
    assert any(
        all(f"'{status}'" in check for status in PROCESS_STATUSES) for check in process_checks
    )

    workdir_fks = _constraint_defs(url, "execution_workdirs", "f")
    assert "FOREIGN KEY (run_id) REFERENCES runtime_runs(id) ON DELETE CASCADE" in workdir_fks
    process_fks = _constraint_defs(url, "runtime_host_processes", "f")
    assert "FOREIGN KEY (run_id) REFERENCES runtime_runs(id) ON DELETE CASCADE" in process_fks
    assert "FOREIGN KEY (workdir_id) REFERENCES execution_workdirs(id) ON DELETE SET NULL" in (
        process_fks
    )

    run_uuid = str(legacy_run_id)
    workdir_id, process_id = str(uuid4()), str(uuid4())
    _execute(
        url,
        _WORKDIR_INSERT,
        workdir_id,
        run_uuid,
        "phase4-migration",
        "biz-a",
        "ws-a",
        "aa11/550e8400-e29b-41d4-a716-446655440000",
        "preparing",
        1073741824,
    )
    _execute(
        url,
        _PROCESS_INSERT,
        process_id,
        run_uuid,
        workdir_id,
        "phase4-migration",
        "runtime-worker.01",
        "boot-instance-1",
        "local",
        "starting",
        "sha256:" + "0" * 64,
    )

    # run_id UNIQUE: a second Workdir for the same Run is rejected.
    with pytest.raises(asyncpg.UniqueViolationError):
        _execute(
            url,
            _WORKDIR_INSERT,
            str(uuid4()),
            run_uuid,
            "phase4-migration",
            "biz-a",
            "ws-a",
            "bb22/550e8400-e29b-41d4-a716-446655440001",
            "preparing",
            1073741824,
        )
    # Unknown Run identity is rejected by the FK before anything is orphaned.
    with pytest.raises(asyncpg.ForeignKeyViolationError):
        _execute(
            url,
            _WORKDIR_INSERT,
            str(uuid4()),
            str(uuid4()),
            "phase4-migration",
            "biz-a",
            "ws-a",
            "cc33/550e8400-e29b-41d4-a716-446655440002",
            "preparing",
            1073741824,
        )

    # Old React writes and reads still work at head (AC-12 regression face).
    fresh_run_id = _submit_run(url, "phase4-migration", "current")
    assert fresh_run_id != legacy_run_id
    legacy_status = query(url, "SELECT status FROM runtime_runs WHERE id=$1", legacy_run_id)[0][0]
    assert legacy_status == "queued"

    # Workdir deletion SET NULLs the process association; the audit row survives.
    _execute(url, "DELETE FROM execution_workdirs WHERE id=$1", workdir_id)
    still_there = query(
        url, "SELECT workdir_id FROM runtime_host_processes WHERE id=$1", process_id
    )
    assert still_there[0][0] is None

    # Run deletion cascades the process row away with the Run.
    _execute(url, "DELETE FROM runtime_runs WHERE id=$1", legacy_run_id)
    assert not query(url, "SELECT 1 FROM runtime_host_processes WHERE id=$1", process_id)

    # 0070 refuses a populated downgrade by design (export-first policy). This
    # disposable fixture simulates that export by clearing the Phase 6 event,
    # usage, Outbox and denial rows the fresh submit created; the runtime_runs
    # rows the rollback assertion cares about stay in place.
    _clear_phase6_event_data(url)
    migrate(url, PREVIOUS_REVISION, "downgrade")
    assert not _tables(url) & {"execution_workdirs", "runtime_host_processes"}
    assert _runtime_columns(url) == columns_before
    surviving = query(url, "SELECT id FROM runtime_runs")
    assert str(fresh_run_id) in {str(row[0]) for row in surviving}

    migrate(url, "head")
    assert _tables(url) >= {"execution_workdirs", "runtime_host_processes"}
    assert not query(url, "SELECT 1 FROM runtime_host_processes")
