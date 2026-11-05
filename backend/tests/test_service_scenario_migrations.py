"""Migration 0054: service scenario schema and reversibility."""

from pathlib import Path

import asyncpg
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
    return ScriptDirectory.from_config(config).get_revision("0054_service_scenarios").module


def test_0054_revision_chain_and_sql_contract(monkeypatch):
    migration = _migration_module()
    assert migration.revision == "0054_service_scenarios"
    assert migration.down_revision == "0053_routing_decisions"

    recorder = _OperationRecorder()
    monkeypatch.setattr(migration, "op", recorder)

    migration.upgrade()
    assert len(recorder.statements) == 7
    scenarios, versions, traces, *indexes = recorder.statements

    for definition in (
        "CREATE TABLE service_scenarios",
        "id UUID PRIMARY KEY DEFAULT gen_random_uuid()",
        "scenario_key TEXT NOT NULL",
        "description TEXT NOT NULL DEFAULT ''",
        "status TEXT NOT NULL DEFAULT 'draft'",
        "draft JSONB NOT NULL",
        "draft_revision INTEGER NOT NULL DEFAULT 1",
        "published_version INTEGER NULL",
        "created_by TEXT NOT NULL",
        "updated_by TEXT NOT NULL",
        "archived BOOLEAN NOT NULL DEFAULT false",
        "created_at TIMESTAMPTZ NOT NULL DEFAULT now()",
        "updated_at TIMESTAMPTZ NOT NULL DEFAULT now()",
        "CONSTRAINT service_scenarios_key_unique",
        "UNIQUE (tenant_id, business_id, workspace_id, scenario_key)",
        "CONSTRAINT service_scenarios_scope_id_unique",
        "UNIQUE (tenant_id, business_id, workspace_id, id)",
        "CONSTRAINT service_scenarios_status_known",
        "CHECK (status IN ('draft', 'review', 'published', 'offline'))",
        "CONSTRAINT service_scenarios_draft_revision_positive",
        "CHECK (draft_revision > 0)",
        "CONSTRAINT service_scenarios_published_version_positive",
        "CHECK (published_version IS NULL OR published_version > 0)",
    ):
        assert definition in scenarios

    for definition in (
        "CREATE TABLE service_scenario_versions",
        "scenario_id UUID NOT NULL",
        "version INTEGER NOT NULL",
        "config JSONB NOT NULL",
        "source_version INTEGER NULL",
        "created_by TEXT",
        "created_at TIMESTAMPTZ NOT NULL DEFAULT now()",
        ("UNIQUE (tenant_id, business_id, workspace_id, scenario_id, version)"),
        (
            "FOREIGN KEY (tenant_id, business_id, workspace_id, scenario_id)"
            " REFERENCES service_scenarios (tenant_id, business_id, workspace_id, id)"
            " ON DELETE CASCADE"
        ),
        "CHECK (version > 0)",
        "CHECK (source_version IS NULL OR source_version > 0)",
    ):
        assert definition in versions

    for definition in (
        "CREATE TABLE service_scenario_traces",
        "scenario_id UUID NULL",
        "scenario_key TEXT NOT NULL",
        "scenario_version INTEGER NULL",
        "simulation BOOLEAN NOT NULL DEFAULT true",
        "message_length INTEGER NOT NULL",
        "message_excerpt TEXT NOT NULL DEFAULT ''",
        "object_ref JSONB NOT NULL DEFAULT '{}'::jsonb",
        "facts JSONB NOT NULL DEFAULT '[]'::jsonb",
        "decisions JSONB NOT NULL DEFAULT '[]'::jsonb",
        "handler_type TEXT NULL",
        "outcome TEXT NOT NULL",
        "reason_code TEXT NOT NULL",
        "result_summary TEXT NOT NULL DEFAULT ''",
        "trace JSONB NOT NULL",
        "created_by TEXT NOT NULL",
        "created_at TIMESTAMPTZ NOT NULL DEFAULT now()",
        ("FOREIGN KEY (scenario_id) REFERENCES service_scenarios (id) ON DELETE SET NULL"),
        "CHECK (message_length >= 0)",
        "'direct', 'knowledge', 'query', 'action', 'agent', 'human', 'tracking'",
        "'succeeded', 'failed', 'needs_input', 'denied', 'simulated', 'delegated'",
    ):
        assert definition in traces

    assert indexes == [
        (
            "CREATE INDEX service_scenarios_scope_status_updated"
            " ON service_scenarios ( tenant_id, business_id, workspace_id, status,"
            " updated_at DESC )"
        ),
        (
            "CREATE INDEX service_scenario_versions_scope_scenario"
            " ON service_scenario_versions ( tenant_id, business_id, workspace_id,"
            " scenario_id, version DESC )"
        ),
        (
            "CREATE INDEX service_scenario_traces_scope_scenario"
            " ON service_scenario_traces ( tenant_id, business_id, workspace_id,"
            " scenario_id, created_at DESC )"
        ),
        (
            "CREATE INDEX service_scenario_traces_scope_handler"
            " ON service_scenario_traces ( tenant_id, business_id, workspace_id,"
            " handler_type, created_at DESC )"
        ),
    ]

    recorder.statements.clear()
    migration.downgrade()
    assert recorder.statements == [
        "DROP INDEX IF EXISTS service_scenario_traces_scope_handler",
        "DROP INDEX IF EXISTS service_scenario_traces_scope_scenario",
        "DROP INDEX IF EXISTS service_scenario_versions_scope_scenario",
        "DROP INDEX IF EXISTS service_scenarios_scope_status_updated",
        "DROP TABLE IF EXISTS service_scenario_traces",
        "DROP TABLE IF EXISTS service_scenario_versions",
        "DROP TABLE IF EXISTS service_scenarios",
    ]


@pytest.mark.postgres
def test_0054_creates_schema_constraints_indexes_and_is_reversible(migration_database):
    url = migration_database
    migrate(url, "0053_routing_decisions")
    assert not query(
        url,
        "SELECT tablename FROM pg_tables"
        " WHERE schemaname='public' AND tablename LIKE 'service_scenario%'",
    )

    migrate(url, "0054_service_scenarios")
    tables = {
        row[0]
        for row in query(
            url,
            "SELECT tablename FROM pg_tables"
            " WHERE schemaname='public' AND tablename LIKE 'service_scenario%'",
        )
    }
    assert tables == {
        "service_scenarios",
        "service_scenario_versions",
        "service_scenario_traces",
    }

    columns = {}
    for table_name in tables:
        columns[table_name] = {
            row[0]: (row[1], row[2], row[3])
            for row in query(
                url,
                "SELECT column_name,data_type,is_nullable,column_default"
                " FROM information_schema.columns"
                " WHERE table_name=$1 ORDER BY ordinal_position",
                table_name,
            )
        }

    assert columns["service_scenarios"]["id"][0] == "uuid"
    assert columns["service_scenarios"]["id"][2].startswith("gen_random_uuid()")
    for column in (
        "tenant_id",
        "business_id",
        "workspace_id",
        "scenario_key",
        "name",
        "domain",
        "template",
        "draft",
        "created_by",
        "updated_by",
    ):
        assert columns["service_scenarios"][column][1] == "NO"
    assert columns["service_scenarios"]["status"][2].startswith("'draft'")
    assert columns["service_scenarios"]["draft_revision"][2].startswith("1")
    assert columns["service_scenarios"]["published_version"][1] == "YES"

    for column in (
        "tenant_id",
        "business_id",
        "workspace_id",
        "scenario_id",
        "version",
        "config",
    ):
        assert columns["service_scenario_versions"][column][1] == "NO"
    assert columns["service_scenario_versions"]["source_version"][1] == "YES"
    assert columns["service_scenario_versions"]["created_at"][2].startswith("now()")

    for column in (
        "tenant_id",
        "business_id",
        "workspace_id",
        "scenario_key",
        "entry",
        "message_length",
        "outcome",
        "reason_code",
        "trace",
        "created_by",
    ):
        assert columns["service_scenario_traces"][column][1] == "NO"
    assert columns["service_scenario_traces"]["scenario_id"][1] == "YES"
    assert columns["service_scenario_traces"]["handler_type"][1] == "YES"
    assert columns["service_scenario_traces"]["simulation"][2].startswith("true")

    constraints = {}
    for row in query(
        url,
        "SELECT conname,contype::text,pg_get_constraintdef(oid)"
        " FROM pg_constraint"
        " WHERE conrelid IN ("
        "   'service_scenarios'::regclass,"
        "   'service_scenario_versions'::regclass,"
        "   'service_scenario_traces'::regclass"
        " )",
    ):
        constraints[row[0]] = (row[1], row[2])

    assert constraints["service_scenarios_key_unique"][0] == "u"
    assert constraints["service_scenarios_scope_id_unique"][0] == "u"
    assert constraints["service_scenarios_status_known"][0] == "c"
    assert constraints["service_scenarios_draft_revision_positive"][0] == "c"
    assert constraints["service_scenarios_published_version_positive"][0] == "c"
    assert constraints["service_scenario_versions_scope_version_unique"][0] == "u"
    assert constraints["service_scenario_versions_scenario_fk"][0] == "f"
    assert "ON DELETE CASCADE" in constraints["service_scenario_versions_scenario_fk"][1]
    assert constraints["service_scenario_versions_version_positive"][0] == "c"
    assert constraints["service_scenario_versions_source_version_positive"][0] == "c"
    assert constraints["service_scenario_traces_scenario_fk"][0] == "f"
    assert "ON DELETE SET NULL" in constraints["service_scenario_traces_scenario_fk"][1]
    assert "FOREIGN KEY (scenario_id)" in constraints["service_scenario_traces_scenario_fk"][1]
    assert constraints["service_scenario_traces_message_length_non_negative"][0] == "c"
    assert constraints["service_scenario_traces_handler_type_known"][0] == "c"
    assert constraints["service_scenario_traces_outcome_known"][0] == "c"

    indexes = {
        row[0]: row[1]
        for row in query(
            url,
            "SELECT indexname,indexdef FROM pg_indexes"
            " WHERE schemaname='public' AND tablename LIKE 'service_scenario%'",
        )
    }
    for index_name in (
        "service_scenarios_scope_status_updated",
        "service_scenario_versions_scope_scenario",
        "service_scenario_traces_scope_scenario",
        "service_scenario_traces_scope_handler",
    ):
        assert index_name in indexes
    assert (
        "tenant_id, business_id, workspace_id, status, updated_at DESC"
        in indexes["service_scenarios_scope_status_updated"]
    )
    assert (
        "tenant_id, business_id, workspace_id, scenario_id, version DESC"
        in indexes["service_scenario_versions_scope_scenario"]
    )
    assert (
        "tenant_id, business_id, workspace_id, scenario_id, created_at DESC"
        in indexes["service_scenario_traces_scope_scenario"]
    )
    assert (
        "tenant_id, business_id, workspace_id, handler_type, created_at DESC"
        in indexes["service_scenario_traces_scope_handler"]
    )

    scenario_id = query(
        url,
        "INSERT INTO service_scenarios"
        " (tenant_id,business_id,workspace_id,scenario_key,name,domain,template,draft,"
        "  created_by,updated_by)"
        " VALUES ('tenant','business','workspace','query-orders','Query orders',"
        "         'orders','direct','{}'::jsonb,'tester','tester')"
        " RETURNING id,status,draft_revision,published_version",
    )[0]
    assert scenario_id[1:] == ("draft", 1, None)

    query(
        url,
        "INSERT INTO service_scenario_versions"
        " (tenant_id,business_id,workspace_id,scenario_id,version,config,created_by)"
        " VALUES ('tenant','business','workspace',$1,1,'{}'::jsonb,'tester')",
        scenario_id[0],
    )
    trace_id = query(
        url,
        "INSERT INTO service_scenario_traces"
        " (tenant_id,business_id,workspace_id,scenario_id,scenario_key,entry,"
        "  message_length,trace,outcome,reason_code,created_by)"
        " VALUES ('tenant','business','workspace',$1,'query-orders','simulator',8,"
        "         '{}'::jsonb,'simulated','matched','tester')"
        " RETURNING id",
        scenario_id[0],
    )[0][0]

    with pytest.raises(asyncpg.CheckViolationError):
        query(
            url,
            "UPDATE service_scenarios SET status='unknown' WHERE id=$1",
            scenario_id[0],
        )
    with pytest.raises(asyncpg.CheckViolationError):
        query(
            url,
            "INSERT INTO service_scenario_traces"
            " (tenant_id,business_id,workspace_id,scenario_key,entry,message_length,"
            "  outcome,reason_code,trace,created_by)"
            " VALUES ('tenant','business','workspace','query-orders','simulator',-1,"
            "         'simulated','matched','{}'::jsonb,'tester')",
        )

    query(url, "DELETE FROM service_scenarios WHERE id=$1", scenario_id[0])
    assert (
        query(
            url,
            "SELECT count(*) FROM service_scenario_versions WHERE scenario_id=$1",
            scenario_id[0],
        )[0][0]
        == 0
    )
    assert (
        query(
            url,
            "SELECT scenario_id FROM service_scenario_traces WHERE id=$1",
            trace_id,
        )[0][0]
        is None
    )

    migrate(url, "0053_routing_decisions", "downgrade")
    assert not query(
        url,
        "SELECT tablename FROM pg_tables"
        " WHERE schemaname='public' AND tablename LIKE 'service_scenario%'",
    )
    assert not query(
        url,
        "SELECT indexname FROM pg_indexes"
        " WHERE schemaname='public' AND tablename LIKE 'service_scenario%'",
    )
    migrate(url, "head")
