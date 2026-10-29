"""Phase 7 follow-up: tenant-scoped indexes for memory observability aggregates.

The Phase 7 observability endpoints (memory summary / alerts) and the alert
scanner aggregate ``memory_tasks`` and ``runtime_events`` by tenant + time
window, but neither table had an index matching those predicates:
``memory_tasks`` carried only its PK and the partial pending-claim index,
``runtime_events`` only its (run_id, seq) PK. At 万级 rows the planner fell
back to sequential scans (P7-IT-13 EXPLAIN leg).

- D1: ``memory_tasks (tenant_id, created_at)`` serves the tenant + window
  predicates of the tasks summary, the by-kind duration aggregates, the
  reinforce section and the 24h-activity probe. Verified via EXPLAIN at
  12k-target/30k-decoy scale: all three aggregates switch to bitmap scans.
- D2: ``memory_tasks (tenant_id, status)`` serves the status-based probes —
  R1 failed-in-15m, R2 oldest-pending, and the pending/running arm of the
  memory-activity check (that check is rewritten as two EXISTS clauses so
  each arm is index-served; a single EXISTS over an OR of two columns cannot
  use either index and kept seq-scanning even with D1+D2 present).
- D3: ``runtime_events (type, created_at)`` matches the event predicates
  (memory_search.completed / memory.injected / tool.completed /
  model.completed, each + a window). Tenant scoping still flows through the
  runtime_runs join; when the window covers most of the table the planner
  may still prefer a hash join over a sequential scan, but the index wins
  decisively once the window is selective against a production-scale event
  horizon.

Plain CREATE INDEX per repo convention (alembic wraps each migration in a
transaction, so CONCURRENTLY is unavailable; these tables are small in
practice). Paired downgrade drops exactly what upgrade creates.
"""

from alembic import op

revision = "0052_memory_tasks_tenant_index"
down_revision = "0051_memory_observability"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "CREATE INDEX IF NOT EXISTS memory_tasks_tenant_created"
        " ON memory_tasks (tenant_id, created_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS memory_tasks_tenant_status"
        " ON memory_tasks (tenant_id, status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS runtime_events_type_created"
        " ON runtime_events (type, created_at)"
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS runtime_events_type_created")
    op.execute("DROP INDEX IF EXISTS memory_tasks_tenant_status")
    op.execute("DROP INDEX IF EXISTS memory_tasks_tenant_created")
