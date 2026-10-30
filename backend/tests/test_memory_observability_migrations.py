"""Phase 7 (D1 adjusted): migration 0051 adds memory_tasks.duration_ms.

Online-safe single-column add; existing rows keep NULL (no backfill —
``created_at`` turned out to exist since 0030, contradicting the design
doc's original D1 assumption). Renumbered 0042->0051 at the integration
merge: the platform layering refactor landed migrations 0042..0050 first.
"""

import pytest
from test_ticket_migrations import migrate, query
from test_ticket_migrations import migration_database as _migration_database

migration_database = _migration_database
pytestmark = pytest.mark.postgres


def test_0051_adds_duration_ms_and_downgrade_drops_it(migration_database):
    url = migration_database
    migrate(url, "0050_audit_scope_columns")
    query(
        url,
        "INSERT INTO memory_tasks(tenant_id,kind,payload) VALUES('t','conversation_summary','{}')",
    )
    migrate(url, "head")
    assert query(
        url,
        "SELECT is_nullable FROM information_schema.columns"
        " WHERE table_name='memory_tasks' AND column_name='duration_ms'",
    ) == [("YES",)]
    # No backfill (D1 adjusted): the pre-existing row stays NULL and
    # duration aggregations exclude NULL.
    assert query(url, "SELECT duration_ms FROM memory_tasks") == [(None,)]
    # A worker-finished row carries a measurable duration.
    query(url, "UPDATE memory_tasks SET status='done', duration_ms=12")
    assert query(url, "SELECT status,duration_ms FROM memory_tasks") == [("done", 12)]
    migrate(url, "0050_audit_scope_columns", "downgrade")
    assert not query(
        url,
        "SELECT column_name FROM information_schema.columns"
        " WHERE table_name='memory_tasks' AND column_name='duration_ms'",
    )
    migrate(url, "head")


NEW_0052_INDEXES = (
    "memory_tasks_tenant_created",
    "memory_tasks_tenant_status",
    "runtime_events_type_created",
)


def test_0052_adds_tenant_indexes_and_downgrade_drops_them(migration_database):
    url = migration_database
    migrate(url, "0051_memory_observability")
    assert not query(
        url,
        "SELECT indexname FROM pg_indexes WHERE indexname IN"
        " ('memory_tasks_tenant_created','memory_tasks_tenant_status',"
        " 'runtime_events_type_created')",
    )
    migrate(url, "head")
    found = {
        row[0]
        for row in query(
            url,
            "SELECT indexname FROM pg_indexes WHERE tablename IN"
            " ('memory_tasks','runtime_events')",
        )
    }
    assert set(NEW_0052_INDEXES) <= found
    migrate(url, "0051_memory_observability", "downgrade")
    assert not query(
        url,
        "SELECT indexname FROM pg_indexes WHERE indexname IN"
        " ('memory_tasks_tenant_created','memory_tasks_tenant_status',"
        " 'runtime_events_type_created')",
    )
    migrate(url, "head")
