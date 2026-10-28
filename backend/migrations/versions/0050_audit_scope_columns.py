"""Persist business/workspace scope for platform audit records."""

from alembic import op


revision = "0050_audit_scope_columns"
down_revision = "0049_knowledge_memory_scope"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TABLE audit_records "
        "ADD COLUMN business_id TEXT NOT NULL DEFAULT 'customer-service', "
        "ADD COLUMN workspace_id TEXT NOT NULL DEFAULT 'default'"
    )
    op.execute(
        "CREATE INDEX ix_audit_records_scope "
        "ON audit_records(tenant_id,business_id,workspace_id)"
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_audit_records_scope")
    op.execute("ALTER TABLE audit_records DROP COLUMN workspace_id, DROP COLUMN business_id")
