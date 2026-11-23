"""Phase 6-2 T-7 / SIG-5: bounded SSE replay-gap audit events.

Revalidated head before implementation: ``0071_execution_credential`` is the
single integration head, so this revision appends to it (08 R-5). The revision
identifier stays within ``alembic_version.version_num`` VARCHAR(32); the
filename keeps the descriptive task name. The table stores only stable codes
and integers copied from an authorized SSE 409 request: no SSE payload, no
raw sample, no Secret. The 409 write point is best-effort and never changes
the public SSE status, body, or headers. The downgrade refuses populated data.
"""

from alembic import op

revision = "0072_execution_replay_gap"
down_revision = "0071_execution_credential"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE execution_replay_gap_events (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            run_id UUID NOT NULL REFERENCES runtime_runs(id) ON DELETE CASCADE,
            tenant_id TEXT NOT NULL,
            requested_cursor_seq INTEGER NOT NULL,
            retention_floor_seq INTEGER NOT NULL,
            reason_code TEXT NOT NULL
                CHECK (reason_code IN ('cursor_below_floor')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX execution_replay_gap_events_tenant"
        " ON execution_replay_gap_events (tenant_id, created_at)"
    )
    op.execute(
        "CREATE INDEX execution_replay_gap_events_run"
        " ON execution_replay_gap_events (run_id, created_at)"
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM execution_replay_gap_events) THEN
                RAISE EXCEPTION 'execution 0072 downgrade refused: export replay gap data first';
            END IF;
        END
        $$
        """
    )
    op.execute("DROP INDEX IF EXISTS execution_replay_gap_events_run")
    op.execute("DROP INDEX IF EXISTS execution_replay_gap_events_tenant")
    op.execute("DROP TABLE execution_replay_gap_events")
