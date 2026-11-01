"""Migration 0053: routing_decisions schema and reversibility."""

from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from test_ticket_migrations import migrate, query
from test_ticket_migrations import migration_database as _migration_database

BACKEND = Path(__file__).resolve().parents[1]
migration_database = _migration_database


class _OperationRecorder:
    def __init__(self):
        self.statements = []

    def execute(self, statement):
        self.statements.append(" ".join(statement.split()))


def _migration_module():
    config = Config(str(BACKEND / "alembic.ini"))
    return ScriptDirectory.from_config(config).get_revision("0053_routing_decisions").module


def test_0053_revision_chain_and_sql_contract(monkeypatch):
    migration = _migration_module()
    assert migration.revision == "0053_routing_decisions"
    assert migration.down_revision == "0052_memory_tasks_tenant_index"

    recorder = _OperationRecorder()
    monkeypatch.setattr(migration, "op", recorder)

    migration.upgrade()
    assert len(recorder.statements) == 4
    create_table, *indexes = recorder.statements
    for definition in (
        "id UUID PRIMARY KEY DEFAULT gen_random_uuid()",
        "tenant_id TEXT NOT NULL",
        "business_id TEXT NOT NULL",
        "workspace_id TEXT NOT NULL",
        "conversation_id UUID NOT NULL",
        "request_id UUID NOT NULL",
        "disposition TEXT NOT NULL",
        "execution_tier TEXT NULL",
        "action TEXT NOT NULL",
        "reason_code TEXT NOT NULL",
        "matched_rule_id TEXT NULL",
        "decider TEXT NOT NULL",
        "message_length INTEGER NOT NULL",
        "created_at TIMESTAMPTZ NOT NULL DEFAULT now()",
        (
            "CONSTRAINT routing_decisions_request_unique "
            "UNIQUE (tenant_id, business_id, workspace_id, request_id)"
        ),
        (
            "CONSTRAINT routing_decisions_tier_requires_continue "
            "CHECK (execution_tier IS NULL OR disposition = 'continue')"
        ),
        (
            "CONSTRAINT routing_decisions_tier_known "
            "CHECK (execution_tier IS NULL OR execution_tier = 'agent')"
        ),
        "CONSTRAINT routing_decisions_length_non_negative CHECK (message_length >= 0)",
    ):
        assert definition in create_table

    assert indexes == [
        (
            "CREATE INDEX routing_decisions_conversation ON routing_decisions( "
            "tenant_id, business_id, workspace_id, conversation_id, "
            "created_at DESC, id DESC )"
        ),
        (
            "CREATE INDEX routing_decisions_disposition ON routing_decisions( "
            "tenant_id, business_id, workspace_id, disposition, created_at DESC )"
        ),
        (
            "CREATE INDEX routing_decisions_reason ON routing_decisions( "
            "tenant_id, business_id, workspace_id, reason_code, created_at DESC )"
        ),
    ]

    recorder.statements.clear()
    migration.downgrade()
    assert recorder.statements == [
        "DROP INDEX IF EXISTS routing_decisions_reason",
        "DROP INDEX IF EXISTS routing_decisions_disposition",
        "DROP INDEX IF EXISTS routing_decisions_conversation",
        "DROP TABLE IF EXISTS routing_decisions",
    ]


@pytest.mark.postgres
def test_0053_creates_schema_constraints_and_indexes(migration_database):
    url = migration_database
    migrate(url, "0052_memory_tasks_tenant_index")
    assert not query(
        url,
        "SELECT tablename FROM pg_tables"
        " WHERE schemaname='public' AND tablename='routing_decisions'",
    )

    migrate(url, "0053_routing_decisions")
    columns = query(
        url,
        "SELECT column_name,data_type,is_nullable,column_default"
        " FROM information_schema.columns"
        " WHERE table_name='routing_decisions'"
        " ORDER BY ordinal_position",
    )
    assert [(row[0], row[1], row[2]) for row in columns] == [
        ("id", "uuid", "NO"),
        ("tenant_id", "text", "NO"),
        ("business_id", "text", "NO"),
        ("workspace_id", "text", "NO"),
        ("conversation_id", "uuid", "NO"),
        ("request_id", "uuid", "NO"),
        ("disposition", "text", "NO"),
        ("execution_tier", "text", "YES"),
        ("action", "text", "NO"),
        ("reason_code", "text", "NO"),
        ("matched_rule_id", "text", "YES"),
        ("decider", "text", "NO"),
        ("message_length", "integer", "NO"),
        ("created_at", "timestamp with time zone", "NO"),
    ]
    assert columns[0][3].startswith("gen_random_uuid()")
    assert columns[-1][3].startswith("now()")

    constraints = {
        row[0]: row[1]
        for row in query(
            url,
            "SELECT conname,contype::text FROM pg_constraint"
            " WHERE conrelid='routing_decisions'::regclass"
            " AND contype IN ('p','u','c')",
        )
    }
    assert constraints == {
        "routing_decisions_pkey": "p",
        "routing_decisions_request_unique": "u",
        "routing_decisions_tier_requires_continue": "c",
        "routing_decisions_tier_known": "c",
        "routing_decisions_length_non_negative": "c",
    }

    indexes = {
        row[0]: row[1]
        for row in query(
            url,
            "SELECT indexname,indexdef FROM pg_indexes"
            " WHERE schemaname='public' AND tablename='routing_decisions'",
        )
    }
    assert set(indexes) == {
        "routing_decisions_pkey",
        "routing_decisions_request_unique",
        "routing_decisions_conversation",
        "routing_decisions_disposition",
        "routing_decisions_reason",
    }
    assert (
        "tenant_id, business_id, workspace_id, conversation_id, created_at DESC, id DESC"
    ) in indexes["routing_decisions_conversation"]
    assert ("tenant_id, business_id, workspace_id, disposition, created_at DESC") in indexes[
        "routing_decisions_disposition"
    ]
    assert ("tenant_id, business_id, workspace_id, reason_code, created_at DESC") in indexes[
        "routing_decisions_reason"
    ]

    migrate(url, "0052_memory_tasks_tenant_index", "downgrade")
    assert not query(
        url,
        "SELECT tablename FROM pg_tables"
        " WHERE schemaname='public' AND tablename='routing_decisions'",
    )
    assert not query(
        url,
        "SELECT indexname FROM pg_indexes"
        " WHERE schemaname='public' AND tablename='routing_decisions'",
    )
    migrate(url, "head")
