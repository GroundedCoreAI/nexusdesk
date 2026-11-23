"""Phase 6-2 T-8 / SIG-7: classified, Secret-free parser diagnostics buckets.

Revalidated head before implementation: ``0072_execution_replay_gap`` is the
single head after 0072, so this revision appends to it (08 R-5). The revision
identifier stays within ``alembic_version.version_num`` VARCHAR(32). This
table holds only bounded category counts and a redacted reason code; the raw
parser sample and any Secret stay out of the database and the admin UI (R-4).
``execution_parser_raw_sample_enabled`` remains false and no new switch is
introduced. The downgrade refuses populated data.
"""

from alembic import op

revision = "0073_execution_parser_diag"
down_revision = "0072_execution_replay_gap"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE execution_parser_diagnostics (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id TEXT NULL,
            run_id UUID NULL REFERENCES runtime_runs(id) ON DELETE SET NULL,
            category TEXT NOT NULL CHECK (category IN
                ('malformed','unknown_schema','unknown_type','size_limit',
                 'critical_terminal')),
            reason_code TEXT NULL
                CHECK (reason_code IS NULL OR length(reason_code)<=200),
            count INTEGER NOT NULL CHECK (count > 0),
            bucket_start TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX execution_parser_diagnostics_tenant"
        " ON execution_parser_diagnostics (tenant_id, bucket_start)"
    )
    op.execute(
        "CREATE INDEX execution_parser_diagnostics_bucket"
        " ON execution_parser_diagnostics (bucket_start, category)"
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM execution_parser_diagnostics) THEN
                RAISE EXCEPTION 'execution 0073 downgrade refused: export parser diagnostics first';
            END IF;
        END
        $$
        """
    )
    op.execute("DROP INDEX IF EXISTS execution_parser_diagnostics_bucket")
    op.execute("DROP INDEX IF EXISTS execution_parser_diagnostics_tenant")
    op.execute("DROP TABLE execution_parser_diagnostics")
