"""Business and workspace ownership for primary business resources."""

from alembic import op

revision = "0046_resource_scope_columns"
down_revision = "0045_tenant_business_scopes"
branch_labels = None
depends_on = None

TABLES = ("agents", "knowledge_bases", "knowledge_documents", "knowledge_folders", "channels")


def upgrade():
    for table in TABLES:
        op.execute(
            f"ALTER TABLE {table} "
            "ADD COLUMN business_id TEXT NOT NULL DEFAULT 'customer-service', "
            "ADD COLUMN workspace_id TEXT NOT NULL DEFAULT 'default'"
        )
        op.execute(
            f"CREATE INDEX ix_{table}_scope "
            f"ON {table}(tenant_id,business_id,workspace_id)"
        )


def downgrade():
    for table in reversed(TABLES):
        op.execute(f"DROP INDEX ix_{table}_scope")
        op.execute(f"ALTER TABLE {table} DROP COLUMN workspace_id, DROP COLUMN business_id")
