import importlib.util
import inspect
from pathlib import Path

import pytest
from test_ticket_migrations import migrate, query
from test_ticket_migrations import migration_database as _migration_database

migration_database = _migration_database
MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "versions"
    / "0058_service_application_v2.py"
)


def _migration_module():
    spec = importlib.util.spec_from_file_location(
        "service_application_v2_migration", MIGRATION_PATH
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _upgrade_source():
    return inspect.getsource(_migration_module().upgrade).lower()


def _downgrade_source():
    return inspect.getsource(_migration_module().downgrade).lower()


def test_0058_is_a_clean_break_from_the_legacy_application_chain():
    module = _migration_module()
    assert module.revision == "0058_service_application_v2"
    assert module.down_revision == "0057_industry_pack_runtime"
    upgrade = _upgrade_source()

    for table in (
        "service_scenario_traces",
        "service_scenario_versions",
        "service_scenarios",
        "industry_pack_upgrades",
        "industry_pack_installations",
        "service_provider_registry",
    ):
        assert f"drop table if exists {table}" in upgrade

    for table in (
        "service_applications",
        "service_application_skills",
        "service_application_connections",
        "service_application_connection_credentials",
        "service_application_versions",
        "service_application_traces",
    ):
        assert f"create table {table}" in upgrade


def test_0058_enforces_agent_binding_immutability_release_and_trace_contracts():
    upgrade = _upgrade_source()

    service_applications = upgrade.split("create table service_applications", 1)[1].split(
        "create index service_applications_catalog", 1
    )[0]
    assert "agent_id uuid not null references agents(id)" in service_applications
    assert "agent_version integer not null check (agent_version > 0)" in service_applications
    assert "origin = 'example' and immutable = true" in service_applications
    assert "origin = 'user' and immutable = false" in service_applications

    versions = upgrade.split("create table service_application_versions", 1)[1].split(
        "create index service_application_versions_application", 1
    )[0]
    assert "config jsonb not null" in versions
    assert "config_digest text not null" in versions
    assert "source_version integer null" in versions
    assert "schema_version = 'v2'" in versions

    traces = upgrade.split("create table service_application_traces", 1)[1].split(
        "create index service_application_traces_application", 1
    )[0]
    assert "application_version integer not null" in traces
    assert "conversation_id uuid null references runtime_conversations" in traces
    assert "run_id uuid null references runtime_runs" in traces
    assert "agent_version integer not null" in traces


def test_0058_moves_channels_to_fixed_application_versions_and_cleans_old_rows_first():
    upgrade = _upgrade_source()
    deliveries = upgrade.index("delete from channel_deliveries")
    inbound = upgrade.index("delete from channel_inbound_events")
    conversations = upgrade.index("delete from channel_conversations")
    channels = upgrade.index("delete from channels")
    assert deliveries < inbound < conversations < channels

    assert "add column application_id uuid not null" in upgrade
    assert "add column application_version integer not null" in upgrade
    assert "channels_application_fk" in upgrade
    assert "channels_application_version_fk" in upgrade
    assert "drop column agent_id" in upgrade
    assert upgrade.count("drop column agent_id") == 1


def test_0058_downgrade_recreates_shells_but_never_claims_to_restore_data():
    downgrade = _downgrade_source()
    assert "drop table if exists service_application_traces" in downgrade
    assert "drop table if exists service_application_versions" in downgrade
    assert "drop table if exists service_applications" in downgrade
    assert "create table service_scenarios" in downgrade
    assert "create table service_scenario_versions" in downgrade
    assert "create table service_scenario_traces" in downgrade
    assert "create table service_provider_registry" in downgrade
    assert "add column agent_id" in downgrade
    assert "drop column application_version" in downgrade


@pytest.mark.postgres
def test_0058_postgres_schema_and_foreign_keys(migration_database):
    url = migration_database
    migrate(url, "0057_industry_pack_runtime")
    migrate(url, "head")

    tables = {
        row[0]
        for row in query(
            url,
            "SELECT tablename FROM pg_tables WHERE schemaname='public'",
        )
    }
    assert {
        "service_applications",
        "service_application_skills",
        "service_application_connections",
        "service_application_connection_credentials",
        "service_application_versions",
        "service_application_traces",
    }.issubset(tables)
    assert {
        "service_scenarios",
        "service_scenario_versions",
        "service_scenario_traces",
        "service_provider_registry",
        "industry_pack_installations",
        "industry_pack_upgrades",
    }.isdisjoint(tables)

    channel_columns = {
        row[0]
        for row in query(
            url,
            "SELECT column_name FROM information_schema.columns WHERE table_name='channels'",
        )
    }
    assert {"application_id", "application_version"}.issubset(channel_columns)
    assert "agent_id" not in channel_columns

    constraints = {
        row[0]
        for row in query(
            url,
            """
SELECT conname
FROM pg_constraint
WHERE conrelid='channels'::regclass
""",
        )
    }
    assert {"channels_application_fk", "channels_application_version_fk"}.issubset(constraints)

    conversation_constraint = query(
        url,
        """
SELECT pg_get_constraintdef(c.oid)
FROM pg_constraint c
WHERE c.conrelid='runtime_conversations'::regclass
  AND c.conname='runtime_conversations_application_fk'
""",
    )
    assert conversation_constraint
    definition = conversation_constraint[0][0].upper()
    assert "ON DELETE SET NULL (APPLICATION_ID)" in definition
