import pytest
from test_ticket_migrations import migrate, query
from test_ticket_migrations import migration_database as _migration_database

migration_database = _migration_database
pytestmark = pytest.mark.postgres


def test_plugin_runtime_state_migration_is_reversible(migration_database):
    url = migration_database
    migrate(url, "0043_plugin_config_versions")
    migrate(url, "0044_plugin_runtime_state")

    query(
        url,
        """
        INSERT INTO plugin_runtime_state(
            capability_id, manifest_version, enabled, status, updated_by
        ) VALUES('sample-operations', '1.0.0', true, 'ready', 'migration-test')
        """,
    )
    assert query(
        url,
        "SELECT capability_id,status FROM plugin_runtime_state",
    ) == [("sample-operations", "ready")]

    migrate(url, "0043_plugin_config_versions", "downgrade")
    assert not query(
        url,
        "SELECT tablename FROM pg_tables "
        "WHERE schemaname='public' AND tablename='plugin_runtime_state'",
    )
    migrate(url, "head")
