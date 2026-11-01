"""Tenant business and workspace scope catalog."""

from alembic import op

revision = "0045_tenant_business_scopes"
down_revision = "0044_plugin_runtime_state"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        CREATE TABLE tenant_businesses (
            tenant_id TEXT NOT NULL,
            business_id TEXT NOT NULL,
            name TEXT NOT NULL,
            route_prefix TEXT NOT NULL,
            enabled BOOLEAN NOT NULL DEFAULT true,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id,business_id),
            CHECK (length(business_id) BETWEEN 1 AND 100),
            CHECK (route_prefix ~ '^/[a-z0-9][a-z0-9/-]*$' OR route_prefix = '/')
        )
        """
    )
    op.execute(
        """
        CREATE TABLE tenant_workspaces (
            tenant_id TEXT NOT NULL,
            business_id TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            name TEXT NOT NULL,
            enabled BOOLEAN NOT NULL DEFAULT true,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id,business_id,workspace_id),
            FOREIGN KEY (tenant_id,business_id)
                REFERENCES tenant_businesses(tenant_id,business_id)
                ON DELETE CASCADE,
            CHECK (length(workspace_id) BETWEEN 1 AND 100)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_tenant_businesses_enabled "
        "ON tenant_businesses(tenant_id,enabled,business_id)"
    )
    op.execute(
        "CREATE INDEX ix_tenant_workspaces_enabled "
        "ON tenant_workspaces(tenant_id,business_id,enabled,workspace_id)"
    )


def downgrade():
    op.execute("DROP INDEX ix_tenant_workspaces_enabled")
    op.execute("DROP INDEX ix_tenant_businesses_enabled")
    op.execute("DROP TABLE tenant_workspaces")
    op.execute("DROP TABLE tenant_businesses")
