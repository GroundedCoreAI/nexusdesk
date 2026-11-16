"""Phase 6 T-02: migration 0068 expansion, backfill, Outbox, usage, downgrade.

The static tests pin the actual single head (0067_merge_heads), the additive
schema contract, the deterministic event identity formula, and a downgrade that
refuses to delete populated event/usage/outbox/audit data. The PostgreSQL test
runs the real chain on a disposable database: populated upgrade, no historical
republish, old-shaped direct writer coverage, internal replay exclusion,
deterministic IDs, usage uniqueness, retention floor and cleanup backfill.
"""

import asyncio
import hashlib
import os
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import asyncpg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from test_ticket_migrations import migrate, query

BACKEND = Path(__file__).resolve().parents[1]
REVISION = "0068_execution_fencing"
PREVIOUS_REVISION = "0067_merge_heads"

OWNERSHIP_OPERATIONS = (
    "snapshot",
    "append",
    "finish",
    "heartbeat",
    "usage",
    "tool_replay",
    "process",
    "workdir",
    "resource_release",
)
DENIAL_REASONS = ("owner_mismatch", "stale_epoch", "lease_lost", "run_terminal", "run_missing")


@pytest.fixture
def migration_database():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a PostgreSQL role with CREATEDB")
    url = url.replace("postgresql+asyncpg://", "postgresql://")
    parts = urlsplit(url)
    name = "phase6_migration_" + uuid4().hex

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


def deterministic_event_id(run_id, seq):
    """The documented ``run_id:seq`` UUID backfill, reproduced in Python."""
    digest = hashlib.md5(f"{run_id}:{seq}".encode()).hexdigest()
    return f"{digest[:8]}-{digest[8:12]}-{digest[12:16]}-{digest[16:20]}-{digest[20:32]}"


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


def _execute(url, sql, *params):
    async def run():
        conn = await asyncpg.connect(url)
        try:
            return await conn.execute(sql, *params)
        finally:
            await conn.close()

    return asyncio.run(run())


def _fetch(url, sql, *params):
    async def run():
        conn = await asyncpg.connect(url)
        try:
            return await conn.fetch(sql, *params)
        finally:
            await conn.close()

    return asyncio.run(run())


def _seed_run(url, tenant="phase6-migration", conversation="phase6"):
    run_id, conversation_id = str(uuid4()), str(uuid4())
    _execute(
        url,
        "INSERT INTO runtime_conversations(id,tenant_id,external_id) VALUES ($1,$2,$3)",
        conversation_id,
        tenant,
        conversation,
    )
    _execute(
        url,
        "INSERT INTO runtime_runs(id,conversation_id,tenant_id,input,config,status,queue_expires_at)"
        " VALUES ($1,$2,$3,'x','{}'::jsonb,'queued',now()+interval '1 hour')",
        run_id,
        conversation_id,
        tenant,
    )
    return run_id


def _seed_legacy_event(url, run_id, seq, event_type="run.started", data="{}"):
    _execute(
        url,
        "INSERT INTO runtime_events(run_id,seq,type,data) VALUES ($1,$2,$3,$4::jsonb)",
        run_id,
        seq,
        event_type,
        data,
    )


def test_0068_revision_chain_is_a_single_head_on_0067():
    migration = _migration_module()
    scripts = ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini")))

    assert migration.revision == REVISION
    assert migration.down_revision == PREVIOUS_REVISION
    assert migration.branch_labels is None
    assert migration.depends_on is None
    assert len(scripts.get_heads()) == 1, scripts.get_heads()


def test_0068_upgrade_contract_is_additive_expand_only(monkeypatch):
    migration = _migration_module()
    recorder = _OperationRecorder()
    monkeypatch.setattr(migration, "op", recorder)

    migration.upgrade()

    joined = "\n".join(recorder.statements)
    # No historical migration is edited: this revision only alters 0001 tables
    # and creates the Phase 6 tables.
    assert "DROP TABLE runtime_runs" not in joined
    assert "ALTER TABLE runtime_runs" in joined
    assert "ALTER TABLE runtime_events" in joined
    for column in (
        "lease_epoch",
        "cancel_requested_at",
        "cancel_confirmed_at",
        "cleanup_status",
        "cleanup_updated_at",
        "retry_of_run_id",
        "attempt_no",
        "side_effect_policy",
        "event_retention_floor_seq",
    ):
        assert column in joined
    for column in (
        "event_id",
        "schema_version",
        "source",
        "producer_id",
        "producer_event_id",
        "engine_session_id",
        "trace_id",
    ):
        assert column in joined
    for table in (
        "runtime_event_outbox",
        "runtime_event_outbox_watermark",
        "runtime_usage_ledger",
        "execution_fencing_denials",
    ):
        assert f"CREATE TABLE {table}" in joined
    assert "CREATE TRIGGER runtime_events_outbox_trigger" in joined
    assert "tool.replay" in joined
    # Historical rows are backfilled but never enqueued for republication:
    # only the trigger function may contain an Outbox INSERT.
    assert not any(
        statement.startswith("INSERT INTO runtime_event_outbox(")
        for statement in recorder.statements
    )
    assert "runtime_event_outbox_watermark" in joined and "now()" in joined


def test_0068_downgrade_refuses_populated_data_before_dropping(monkeypatch):
    migration = _migration_module()
    recorder = _OperationRecorder()
    monkeypatch.setattr(migration, "op", recorder)

    migration.downgrade()

    joined = "\n".join(recorder.statements)
    assert "RAISE EXCEPTION" in joined
    assert "runtime_usage_ledger" in joined
    # The guard runs before any destructive statement.
    guard_index = next(
        index
        for index, statement in enumerate(recorder.statements)
        if "RAISE EXCEPTION" in statement
    )
    drop_index = next(
        index
        for index, statement in enumerate(recorder.statements)
        if statement.startswith("DROP TABLE")
    )
    assert guard_index < drop_index
    assert "DROP TRIGGER" in joined
    assert "DROP FUNCTION" in joined
    assert recorder.statements[-1].startswith("ALTER TABLE runtime_runs DROP COLUMN")


@pytest.mark.postgres
def test_0068_chain_backfill_outbox_usage_and_data_preserving_downgrade(migration_database):
    url = migration_database
    migrate(url, PREVIOUS_REVISION)

    run_id = _seed_run(url)
    # Pre-migration history: publishable platform events at seq 1/2 plus an
    # internal replay event. The upgrade must never republish these.
    _seed_legacy_event(url, run_id, 1, "run.started")
    _seed_legacy_event(url, run_id, 2, "run.completed", '{"output":"ok"}')
    _seed_legacy_event(url, run_id, 3, "tool.replay", '{"idempotency_key":"runtime:x"}')

    started = datetime.now(UTC)
    result = migrate(url, "head")
    elapsed = (datetime.now(UTC) - started).total_seconds()
    assert result.returncode == 0
    # Repeat upgrade is a no-op and does not duplicate identity or sequence.
    assert migrate(url, "head").returncode == 0
    assert elapsed < 60, f"0068 upgrade exceeded the lock/duration budget: {elapsed:.2f}s"
    print(f"0068 populated upgrade duration: {elapsed:.3f}s")

    head = ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini"))).get_heads()[0]
    assert query(url, "SELECT version_num FROM alembic_version")[0][0] == head

    runs_columns = _columns(url, "runtime_runs")
    for column, kind in (
        ("lease_epoch", "bigint"),
        ("cleanup_status", "text"),
        ("attempt_no", "integer"),
        ("event_retention_floor_seq", "integer"),
    ):
        assert column in runs_columns and runs_columns[column][0] == kind
    assert runs_columns["lease_epoch"][2] == "0"
    assert runs_columns["attempt_no"][2] == "1"
    assert runs_columns["event_retention_floor_seq"][2] == "0"

    events_columns = _columns(url, "runtime_events")
    assert events_columns["event_id"][1] == "NO"
    assert events_columns["event_id"][2] == "gen_random_uuid()"
    assert events_columns["schema_version"] == ("text", "NO", "'v1'::text")
    assert events_columns["source"] == ("text", "NO", "'platform'::text")
    assert events_columns["producer_id"][1] == "YES"
    assert events_columns["trace_id"][1] == "YES"

    event_rows = {
        row["seq"]: dict(row)
        for row in _fetch(
            url, "SELECT seq,event_id,type FROM runtime_events WHERE run_id=$1", run_id
        )
    }
    for seq in (1, 2, 3):
        expected = deterministic_event_id(run_id, seq)
        assert str(event_rows[seq]["event_id"]) == expected
    # No Outbox row was created for historical rows: no silent republication.
    assert _fetch(url, "SELECT count(*) AS n FROM runtime_event_outbox")[0]["n"] == 0
    # Terminal cleanup backfill: queued historical stays not_started.
    assert query(url, "SELECT cleanup_status FROM runtime_runs WHERE id=$1", run_id)[0][0] == (
        "not_started"
    )

    # An old-shaped direct writer (no event_id/source/producer columns) gets
    # database identity and a same-transaction Outbox row.
    _seed_legacy_event(url, run_id, 4, "run.cancelled")
    direct = _fetch(
        url,
        "SELECT e.event_id,o.status FROM runtime_events e"
        " JOIN runtime_event_outbox o ON o.run_id=e.run_id AND o.seq=e.seq"
        " WHERE e.run_id=$1 AND e.seq=4",
        run_id,
    )
    assert len(direct) == 1
    assert direct[0]["status"] == "pending"
    assert str(direct[0]["event_id"])

    # Internal replay receives identity but no public Outbox row.
    _seed_legacy_event(url, run_id, 5, "tool.replay", '{"idempotency_key":"runtime:y"}')
    replay = query(
        url,
        "SELECT event_id FROM runtime_events WHERE run_id=$1 AND seq=5",
        run_id,
    )
    assert str(replay[0][0])
    assert not query(
        url,
        "SELECT 1 FROM runtime_event_outbox WHERE run_id=$1 AND seq=5",
        run_id,
    )

    outbox_columns = _columns(url, "runtime_event_outbox")
    assert outbox_columns["status"] == ("text", "NO", "'pending'::text")
    assert outbox_columns["attempts"][2] == "0"
    assert "runtime_event_outbox_pending" in _indexes(url, "runtime_event_outbox")

    ledger_columns = _columns(url, "runtime_usage_ledger")
    for column in (
        "id",
        "run_id",
        "tenant_id",
        "lease_epoch",
        "source",
        "source_event_id",
        "usage_schema_version",
        "usage",
        "cost",
        "is_estimate",
        "supersedes_id",
    ):
        assert column in ledger_columns
    assert ledger_columns["cost"][1] == "YES"
    assert ledger_columns["usage"][0] == "jsonb"

    # Source uniqueness: one source counts once.
    usage_id = str(uuid4())
    insert_usage = (
        "INSERT INTO runtime_usage_ledger(id,run_id,tenant_id,lease_epoch,source,"
        "source_event_id,usage) VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb)"
    )
    _execute(
        url,
        insert_usage,
        usage_id,
        run_id,
        "phase6-migration",
        1,
        "engine_terminal",
        "result",
        '{"total_tokens":3}',
    )
    with pytest.raises(asyncpg.UniqueViolationError):
        _execute(
            url,
            insert_usage,
            str(uuid4()),
            run_id,
            "phase6-migration",
            1,
            "engine_terminal",
            "result",
            '{"total_tokens":3}',
        )
    assert not query(url, "SELECT 1 FROM runtime_usage_ledger WHERE supersedes_id IS NOT NULL")

    denials_columns = _columns(url, "execution_fencing_denials")
    assert denials_columns["operation"][1] == "NO"
    assert denials_columns["stale_lease_epoch"][1] == "YES"
    denial_id = str(uuid4())
    _execute(
        url,
        "INSERT INTO execution_fencing_denials(id,run_id,operation,reason,stale_lease_epoch)"
        " VALUES ($1,$2,'append','stale_epoch',1)",
        denial_id,
        run_id,
    )

    # Terminal cleanup backfill after a terminal transition.
    _execute(
        url,
        "UPDATE runtime_runs SET status='completed',finished_at=now() WHERE id=$1",
        run_id,
    )
    _execute(
        url,
        "UPDATE runtime_runs SET cleanup_status='completed' WHERE status IN"
        " ('completed','failed','cancelled') AND cleanup_status='not_started'",
    )
    assert query(url, "SELECT cleanup_status FROM runtime_runs WHERE id=$1", run_id)[0][0] == (
        "completed"
    )

    # Data-preserving downgrade: populated Phase 6 data refuses deletion.
    refused = migrate(url, PREVIOUS_REVISION, "downgrade", success=False)
    assert "export" in (refused.stderr + refused.stdout).lower()
    # Business rows survive the refused rollback attempt.
    assert query(url, "SELECT id FROM runtime_runs WHERE id=$1", run_id)
    assert query(url, "SELECT count(*) FROM runtime_events WHERE run_id=$1", run_id)[0][0] == 5
