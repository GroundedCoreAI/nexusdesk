"""Persist private Phase 3 execution metadata on runtime runs.

All columns are nullable and have no defaults: rows written before Phase 3 retain
NULL snapshots, and existing runtime statements remain valid during rollout.
"""

from alembic import op

revision = "0058_agent_execution_metadata"
down_revision = "0057_industry_pack_runtime"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        ALTER TABLE runtime_runs
        ADD COLUMN execution_config_snapshot JSONB NULL,
        ADD COLUMN declared_capabilities_snapshot JSONB NULL,
        ADD COLUMN available_capabilities_snapshot JSONB NULL,
        ADD COLUMN effective_capabilities_snapshot JSONB NULL,
        ADD COLUMN execution_policy_snapshot JSONB NULL
        """
    )


def downgrade():
    op.execute(
        """
        ALTER TABLE runtime_runs
        DROP COLUMN execution_config_snapshot,
        DROP COLUMN declared_capabilities_snapshot,
        DROP COLUMN available_capabilities_snapshot,
        DROP COLUMN effective_capabilities_snapshot,
        DROP COLUMN execution_policy_snapshot
        """
    )
