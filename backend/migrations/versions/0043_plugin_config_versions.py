"""Durable platform capability configuration history."""

from alembic import op

revision = "0043_plugin_config_versions"
down_revision = "0042_approval_requests"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        CREATE TABLE plugin_config_versions (
            id BIGSERIAL PRIMARY KEY,
            capability_id VARCHAR(64) NOT NULL,
            version INTEGER NOT NULL CHECK (version >= 1),
            schema_version VARCHAR(100) NOT NULL,
            config JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_by TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            rollback_of INTEGER,
            CONSTRAINT plugin_config_versions_capability_version_key
                UNIQUE (capability_id, version),
            CONSTRAINT plugin_config_versions_rollback_version_check
                CHECK (rollback_of IS NULL OR rollback_of >= 1)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_plugin_config_versions_capability_created
        ON plugin_config_versions (capability_id, created_at DESC, version DESC)
        """
    )


def downgrade():
    op.execute("DROP INDEX ix_plugin_config_versions_capability_created")
    op.execute("DROP TABLE plugin_config_versions")
