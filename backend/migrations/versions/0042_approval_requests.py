"""Phase 7: independent approval capability persistence."""

from alembic import op

revision = "0042_approval_requests"
down_revision = "0041_memory_injection_log"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        CREATE TABLE approval_requests (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            requested_by TEXT NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'pending'
                CHECK (status IN ('draft', 'pending', 'approved', 'rejected', 'cancelled')),
            revision INT NOT NULL DEFAULT 1 CHECK (revision >= 1),
            idempotency_key VARCHAR(200),
            request_fingerprint VARCHAR(64) NOT NULL,
            decision_by TEXT,
            decided_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, idempotency_key)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_approval_requests_tenant_status "
        "ON approval_requests (tenant_id, status, created_at DESC)"
    )


def downgrade():
    op.execute("DROP TABLE approval_requests")
