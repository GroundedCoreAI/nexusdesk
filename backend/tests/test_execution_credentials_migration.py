"""Phase 6 T-07: migration 0071 credential/version/grant/audit schema."""

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

BACKEND = Path(__file__).resolve().parents[1]
REVISION = "0071_execution_credential"
PREVIOUS_REVISION = "0070_execution_fencing"


@pytest.fixture
def migration_database():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a PostgreSQL role with CREATEDB")
    url = url.replace("postgresql+asyncpg://", "postgresql://")
    parts = urlsplit(url)
    name = "phase6_credentials_" + uuid4().hex

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


class _Recorder:
    def __init__(self):
        self.statements = []

    def execute(self, statement):
        self.statements.append(" ".join(statement.split()))


def _migration():
    config = Config(str(BACKEND / "alembic.ini"))
    return ScriptDirectory.from_config(config).get_revision(REVISION).module


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


def _execute(url, sql, *params):
    async def run():
        conn = await asyncpg.connect(url)
        try:
            return await conn.execute(sql, *params)
        finally:
            await conn.close()

    return asyncio.run(run())


def test_0071_revision_chain_is_a_single_head_on_0070():
    migration = _migration()
    scripts = ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini")))
    assert migration.revision == REVISION
    assert migration.down_revision == PREVIOUS_REVISION
    assert migration.branch_labels is None and migration.depends_on is None
    # Phase 6-2 adds 0072/0073, the Codex backfill 0074 and the UI-managed
    # egress-host table 0075 on top of this 0071 baseline (still one head).
    assert scripts.get_heads() == ["0075_gateway_allowed_hosts"]
    assert len(REVISION) <= 32


def test_0071_upgrade_contract_is_additive_credential_schema(monkeypatch):
    migration = _migration()
    recorder = _Recorder()
    monkeypatch.setattr(migration, "op", recorder)
    migration.upgrade()
    joined = "\n".join(recorder.statements)
    for table in (
        "execution_credentials",
        "execution_credential_grants",
        "execution_credential_audit",
    ):
        assert f"CREATE TABLE {table}" in joined
    assert "UNIQUE (credential_ref, version)" in joined
    assert "grant_hash TEXT NOT NULL UNIQUE" in joined
    assert "REFERENCES execution_credentials(id)" in joined
    assert "REFERENCES runtime_runs(id)" in joined
    for value in ("active", "superseded", "revoked", "token", "api_key", "mtls_certificate"):
        assert f"'{value}'" in joined
    assert "encrypted_secret TEXT NOT NULL" in joined
    assert "plaintext" not in joined.lower()
    assert "DROP TABLE runtime_events" not in joined


def test_0071_downgrade_refuses_populated_credentials_before_dropping(monkeypatch):
    migration = _migration()
    recorder = _Recorder()
    monkeypatch.setattr(migration, "op", recorder)
    migration.downgrade()
    assert "RAISE EXCEPTION" in "\n".join(recorder.statements)
    guard = next(i for i, s in enumerate(recorder.statements) if "RAISE EXCEPTION" in s)
    drops = [s for s in recorder.statements if s.startswith("DROP TABLE")]
    assert drops == [
        "DROP TABLE execution_credential_audit",
        "DROP TABLE execution_credential_grants",
        "DROP TABLE execution_credentials",
    ]
    drop_index = next(i for i, s in enumerate(recorder.statements) if s.startswith("DROP TABLE"))
    assert guard < drop_index


@pytest.mark.postgres
def test_0071_chain_versions_grants_and_data_preserving_downgrade(migration_database):
    url = migration_database
    migrate(url, PREVIOUS_REVISION)
    # Stay on the 0071 revision here: the assertion below validates this test's
    # own 0071 contract in isolation, while 0072/0073 now sit beyond it.
    assert migrate(url, REVISION).returncode == 0
    assert query(url, "SELECT version_num FROM alembic_version")[0][0] == REVISION
    assert migrate(url, "head").returncode == 0

    credential_columns = _columns(url, "execution_credentials")
    assert credential_columns["encrypted_secret"] == ("text", "NO", None)
    assert credential_columns["allowed_engines"][0] == "jsonb"
    assert credential_columns["version"][0] == "integer"
    grant_columns = _columns(url, "execution_credential_grants")
    assert grant_columns["grant_hash"] == ("text", "NO", None)
    assert grant_columns["scopes"][0] == "jsonb"
    audit_columns = _columns(url, "execution_credential_audit")
    assert {"action", "reason_code"} <= set(audit_columns)
    assert "encrypted_secret" not in audit_columns

    tenant = "credential-migration-" + uuid4().hex
    credential_ref, credential_id = str(uuid4()), str(uuid4())
    insert = (
        "INSERT INTO execution_credentials(id,credential_ref,tenant_id,name,credential_type,"
        "encrypted_secret,key_version,version,status,allowed_engines,allowed_workspaces)"
        " VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb,$11::jsonb)"
    )
    _execute(
        url,
        insert,
        credential_id,
        credential_ref,
        tenant,
        "engine",
        "api_key",
        "fernet:cipher",
        "v1",
        1,
        "active",
        '["react","codex"]',
        '["default"]',
    )
    with pytest.raises(asyncpg.UniqueViolationError):
        _execute(
            url,
            insert,
            str(uuid4()),
            credential_ref,
            tenant,
            "engine-2",
            "api_key",
            "fernet:cipher2",
            "v1",
            1,
            "active",
            '["react"]',
            '["default"]',
        )

    run_id, conversation_id = str(uuid4()), str(uuid4())
    _execute(
        url,
        "INSERT INTO runtime_conversations(id,tenant_id,external_id) VALUES ($1,$2,$3)",
        conversation_id,
        tenant,
        "cred-mig",
    )
    _execute(
        url,
        "INSERT INTO runtime_runs(id,conversation_id,tenant_id,input,config,status,"
        "queue_expires_at) VALUES ($1,$2,$3,'x','{}'::jsonb,'queued',"
        "now()+interval '1 hour')",
        run_id,
        conversation_id,
        tenant,
    )
    grant_id, grant_hash = str(uuid4()), "a" * 64
    grant_insert = (
        "INSERT INTO execution_credential_grants(id,grant_hash,credential_id,credential_version,"
        "run_id,tenant_id,engine_id,protocol_id,workspace_id,scopes,expires_at)"
        " VALUES ($1,$2,$3,$4,$5,$6,'react','native','default','[\"read\"]'::jsonb,"
        " now()+interval '5 minutes')"
    )
    _execute(url, grant_insert, grant_id, grant_hash, credential_id, 1, run_id, tenant)
    with pytest.raises(asyncpg.ForeignKeyViolationError):
        _execute(url, grant_insert, str(uuid4()), "b" * 64, str(uuid4()), 1, run_id, tenant)

    _execute(
        url,
        "UPDATE execution_credentials SET status='revoked',revoked_at=now()"
        " WHERE credential_ref=$1 AND tenant_id=$2",
        credential_ref,
        tenant,
    )
    assert (
        query(
            url, "SELECT status FROM execution_credentials WHERE credential_ref=$1", credential_ref
        )[0][0]
        == "revoked"
    )
    _execute(url, "DELETE FROM runtime_runs WHERE id=$1", run_id)
    assert not query(url, "SELECT 1 FROM execution_credential_grants WHERE id=$1", grant_id)
    assert query(url, "SELECT 1 FROM execution_credentials WHERE credential_ref=$1", credential_ref)

    refused = migrate(url, PREVIOUS_REVISION, "downgrade", success=False)
    assert "export" in (refused.stderr + refused.stdout).lower()


@pytest.mark.postgres
def test_0071_empty_downgrade_succeeds(migration_database):
    url = migration_database
    migrate(url, PREVIOUS_REVISION)
    migrate(url, "head")
    assert migrate(url, PREVIOUS_REVISION, "downgrade").returncode == 0
    assert query(url, "SELECT version_num FROM alembic_version")[0][0] == PREVIOUS_REVISION
