"""Phase 7 of agent memory: production observability — task duration column.

Purely additive: one nullable ``duration_ms`` column on ``memory_tasks``,
written by the memory worker's ``_finish`` when a claimed task reaches a
final state (done/failed, and retry requeues — every executed attempt is
timed).

- D1 (as adjusted at implementation time): the Phase 7 design doc assumed
  ``memory_tasks`` lacked ``created_at`` and planned a ``run_after``
  backfill; reconnaissance found ``created_at`` present since migration
  0030, so only ``duration_ms`` is added and no backfill is needed.
  Existing rows stay NULL and duration aggregations exclude NULL.
- Nullable by design: rows never executed (pending, or reaped before any
  attempt finished) keep NULL rather than a misleading 0.
"""

from alembic import op

revision = "0042_memory_observability"
down_revision = "0041_memory_injection_log"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE memory_tasks ADD COLUMN duration_ms INTEGER")


def downgrade():
    op.execute("ALTER TABLE memory_tasks DROP COLUMN duration_ms")
