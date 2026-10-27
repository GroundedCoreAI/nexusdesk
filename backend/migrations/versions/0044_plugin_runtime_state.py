"""Durable external capability lifecycle state."""

from alembic import op

revision = "0044_plugin_runtime_state"
down_revision = "0043_plugin_config_versions"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        CREATE TABLE plugin_runtime_state (
            capability_id VARCHAR(64) PRIMARY KEY,
            manifest_version VARCHAR(100) NOT NULL,
            enabled BOOLEAN NOT NULL,
            status VARCHAR(20) NOT NULL
                CHECK (status IN ('registered', 'starting', 'ready', 'degraded', 'stopped')),
            reason TEXT,
            failure_count INTEGER NOT NULL DEFAULT 0 CHECK (failure_count >= 0),
            last_started_at TIMESTAMPTZ,
            last_stopped_at TIMESTAMPTZ,
            last_failure_at TIMESTAMPTZ,
            updated_by TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_plugin_runtime_state_status "
        "ON plugin_runtime_state (status, enabled)"
    )


def downgrade():
    op.execute("DROP INDEX ix_plugin_runtime_state_status")
    op.execute("DROP TABLE plugin_runtime_state")
