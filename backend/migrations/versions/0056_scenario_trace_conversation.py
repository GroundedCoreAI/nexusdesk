"""Bind service-scenario execution traces to runtime conversations.

Handoff context inheritance reads traces by ``conversation_id``; the column is
nullable so existing simulator-only evidence keeps working unchanged.
"""

from alembic import op

revision = "0056_scenario_trace_conversation"
down_revision = "0055_service_applications"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        ALTER TABLE service_scenario_traces
        ADD COLUMN conversation_id UUID NULL
        """
    )
    op.execute(
        """
        ALTER TABLE service_scenario_traces
        ADD CONSTRAINT service_scenario_traces_conversation_fk
        FOREIGN KEY (conversation_id)
        REFERENCES runtime_conversations (id)
        ON DELETE SET NULL
        """
    )
    op.execute(
        """
        CREATE INDEX service_scenario_traces_scope_conversation
        ON service_scenario_traces (
            tenant_id,
            business_id,
            workspace_id,
            conversation_id,
            created_at DESC
        )
        """
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS service_scenario_traces_scope_conversation")
    op.execute(
        """
        ALTER TABLE service_scenario_traces
        DROP CONSTRAINT IF EXISTS service_scenario_traces_conversation_fk
        """
    )
    op.execute(
        """
        ALTER TABLE service_scenario_traces
        DROP COLUMN IF EXISTS conversation_id
        """
    )
