"""Migration 0057: industry-pack runtime schema and reversibility."""

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
    return ScriptDirectory.from_config(config).get_revision("0057_industry_pack_runtime").module


def test_0057_revision_chain_and_reversible_sql(monkeypatch):
    migration = _migration_module()
    assert migration.revision == "0057_industry_pack_runtime"
    assert migration.down_revision == "0056_scenario_trace_conversation"

    recorder = _OperationRecorder()
    monkeypatch.setattr(migration, "op", recorder)
    migration.upgrade()
    statements = recorder.statements
    assert any("CREATE TABLE service_provider_registry" in item for item in statements)
    assert any("CREATE TABLE industry_pack_installations" in item for item in statements)
    assert any("CREATE TABLE industry_pack_upgrades" in item for item in statements)
    assert any("industry_pack_installations_scope_id_unique" in item for item in statements)
    assert any(
        "industry_pack_upgrades_installation_fk" in item and "ON DELETE CASCADE" in item
        for item in statements
    )

    recorder.statements.clear()
    migration.downgrade()
    assert recorder.statements == [
        "DROP INDEX IF EXISTS industry_pack_upgrades_scope_installation",
        "DROP TABLE IF EXISTS industry_pack_upgrades",
        "DROP INDEX IF EXISTS industry_pack_installations_scope_pack",
        "DROP TABLE IF EXISTS industry_pack_installations",
        "DROP INDEX IF EXISTS service_provider_registry_scope_kind_enabled",
        "DROP TABLE IF EXISTS service_provider_registry",
    ]


@pytest.mark.postgres
def test_0057_creates_runtime_tables_and_downgrades(migration_database):
    url = migration_database
    migrate(url, "0056_scenario_trace_conversation")
    assert not query(
        url,
        "SELECT tablename FROM pg_tables"
        " WHERE schemaname='public'"
        " AND tablename IN ("
        "   'service_provider_registry',"
        "   'industry_pack_installations',"
        "   'industry_pack_upgrades'"
        " )",
    )

    migrate(url, "0057_industry_pack_runtime")
    tables = {
        row[0]
        for row in query(
            url,
            "SELECT tablename FROM pg_tables"
            " WHERE schemaname='public'"
            " AND tablename IN ("
            "   'service_provider_registry',"
            "   'industry_pack_installations',"
            "   'industry_pack_upgrades'"
            " )",
        )
    }
    assert tables == {
        "service_provider_registry",
        "industry_pack_installations",
        "industry_pack_upgrades",
    }

    constraints = {
        row[0]
        for row in query(
            url,
            "SELECT conname FROM pg_constraint"
            " WHERE conrelid IN ("
            "   'service_provider_registry'::regclass,"
            "   'industry_pack_installations'::regclass,"
            "   'industry_pack_upgrades'::regclass"
            " )",
        )
    }
    assert {
        "service_provider_registry_identity_unique",
        "service_provider_registry_kind_known",
        "industry_pack_installations_identity_unique",
        "industry_pack_installations_scope_id_unique",
        "industry_pack_installations_status_known",
        "industry_pack_upgrades_installation_fk",
        "industry_pack_upgrades_status_known",
    } <= constraints

    indexes = {
        row[0]
        for row in query(
            url,
            "SELECT indexname FROM pg_indexes"
            " WHERE schemaname='public'"
            " AND tablename IN ("
            "   'service_provider_registry',"
            "   'industry_pack_installations',"
            "   'industry_pack_upgrades'"
            " )",
        )
    }
    assert {
        "service_provider_registry_scope_kind_enabled",
        "industry_pack_installations_scope_pack",
        "industry_pack_upgrades_scope_installation",
    } <= indexes

    migrate(url, "0056_scenario_trace_conversation", "downgrade")
    assert not query(
        url,
        "SELECT tablename FROM pg_tables"
        " WHERE schemaname='public'"
        " AND tablename IN ("
        "   'service_provider_registry',"
        "   'industry_pack_installations',"
        "   'industry_pack_upgrades'"
        " )",
    )
