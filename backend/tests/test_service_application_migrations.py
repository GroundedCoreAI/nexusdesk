"""Migration 0055: service application schema and reversibility."""

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
    return ScriptDirectory.from_config(config).get_revision(
        "0055_service_applications"
    ).module


def test_0055_revision_chain_and_sql_contract(monkeypatch):
    migration = _migration_module()
    assert migration.revision == "0055_service_applications"
    assert migration.down_revision == "0054_service_scenarios"

    recorder = _OperationRecorder()
    monkeypatch.setattr(migration, "op", recorder)

    migration.upgrade()
    assert len(recorder.statements) == 5
    applications, versions, *indexes = recorder.statements

    for definition in (
        "CREATE TABLE service_applications",
        "id UUID PRIMARY KEY DEFAULT gen_random_uuid()",
        "application_key TEXT NOT NULL",
        "status TEXT NOT NULL DEFAULT 'draft'",
        "draft JSONB NOT NULL",
        "draft_revision INTEGER NOT NULL DEFAULT 1",
        "published_version INTEGER NULL",
        "archived BOOLEAN NOT NULL DEFAULT false",
        "CONSTRAINT service_applications_key_unique",
        "UNIQUE (tenant_id, business_id, workspace_id, application_key)",
        "CONSTRAINT service_applications_status_known",
        "CHECK (status IN ('draft', 'review', 'published', 'offline'))",
        "CONSTRAINT service_applications_draft_revision_positive",
        "CHECK (draft_revision > 0)",
    ):
        assert definition in applications

    for definition in (
        "CREATE TABLE service_application_versions",
        "application_id UUID NOT NULL",
        "version INTEGER NOT NULL",
        "config JSONB NOT NULL",
        "source_version INTEGER NULL",
        "CONSTRAINT service_application_versions_scope_version_unique",
        "UNIQUE (tenant_id, business_id, workspace_id, application_id, version)",
        "CONSTRAINT service_application_versions_application_fk",
        "FOREIGN KEY (tenant_id, business_id, workspace_id, application_id)",
        "REFERENCES service_applications (tenant_id, business_id, workspace_id, id)",
        "ON DELETE CASCADE",
        "CHECK (version > 0)",
    ):
        assert definition in versions

    assert indexes == [
        (
            "CREATE INDEX service_applications_scope_status_updated"
            " ON service_applications ( tenant_id, business_id, workspace_id,"
            " status, updated_at DESC )"
        ),
        (
            "CREATE INDEX service_application_versions_scope_application"
            " ON service_application_versions ( tenant_id, business_id,"
            " workspace_id, application_id, version DESC )"
        ),
        (
            "CREATE INDEX service_scenario_traces_application"
            " ON service_scenario_traces ( (trace->'application'->>'key'),"
            " created_at DESC )"
        ),
    ]

    recorder.statements.clear()
    migration.downgrade()
    assert recorder.statements == [
        "DROP INDEX IF EXISTS service_scenario_traces_application",
        "DROP INDEX IF EXISTS service_application_versions_scope_application",
        "DROP INDEX IF EXISTS service_applications_scope_status_updated",
        "DROP TABLE IF EXISTS service_application_versions",
        "DROP TABLE IF EXISTS service_applications",
    ]


@pytest.mark.postgres
def test_0055_creates_schema_constraints_indexes_and_is_reversible(migration_database):
    url = migration_database
    migrate(url, "0054_service_scenarios")
    assert not query(
        url,
        "SELECT tablename FROM pg_tables"
        " WHERE schemaname='public' AND tablename LIKE 'service_application%'",
    )

    migrate(url, "0055_service_applications")
    tables = {
        row[0]
        for row in query(
            url,
            "SELECT tablename FROM pg_tables"
            " WHERE schemaname='public' AND tablename LIKE 'service_application%'",
        )
    }
    assert tables == {"service_applications", "service_application_versions"}

    columns = {
        row[0]: (row[1], row[2], row[3])
        for row in query(
            url,
            "SELECT column_name,data_type,is_nullable,column_default"
            " FROM information_schema.columns"
            " WHERE table_name='service_applications'"
            " ORDER BY ordinal_position",
        )
    }
    assert columns["id"][0] == "uuid"
    assert columns["id"][2].startswith("gen_random_uuid()")
    for column in (
        "tenant_id",
        "business_id",
        "workspace_id",
        "application_key",
        "name",
        "draft",
        "created_by",
        "updated_by",
    ):
        assert columns[column][1] == "NO"
    assert columns["status"][2].startswith("'draft'")
    assert columns["published_version"][1] == "YES"

    constraints = {
        row[0]
        for row in query(
            url,
            "SELECT conname FROM pg_constraint"
            " WHERE conrelid='service_applications'::regclass"
            " AND contype IN ('p','u','c')",
        )
    }
    assert {
        "service_applications_pkey",
        "service_applications_key_unique",
        "service_applications_scope_id_unique",
        "service_applications_status_known",
        "service_applications_draft_revision_positive",
        "service_applications_published_version_positive",
    } <= constraints

    indexes = {
        row[0]
        for row in query(
            url,
            "SELECT indexname FROM pg_indexes"
            " WHERE schemaname='public'"
            " AND tablename IN ('service_applications','service_application_versions',"
            "'service_scenario_traces')",
        )
    }
    assert {
        "service_applications_scope_status_updated",
        "service_application_versions_scope_application",
        "service_scenario_traces_application",
    } <= indexes

    migrate(url, "0054_service_scenarios", "downgrade")
    assert not query(
        url,
        "SELECT tablename FROM pg_tables"
        " WHERE schemaname='public' AND tablename LIKE 'service_application%'",
    )
