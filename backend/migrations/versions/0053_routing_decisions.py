"""Phase 1 routing decision trace: persist deterministic ingress decisions."""

from alembic import op

revision = "0053_routing_decisions"
down_revision = "0052_memory_tasks_tenant_index"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        CREATE TABLE routing_decisions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id TEXT NOT NULL,
            business_id TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            conversation_id UUID NOT NULL,
            request_id UUID NOT NULL,
            disposition TEXT NOT NULL,
            execution_tier TEXT NULL,
            action TEXT NOT NULL,
            reason_code TEXT NOT NULL,
            matched_rule_id TEXT NULL,
            decider TEXT NOT NULL,
            message_length INTEGER NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT routing_decisions_request_unique
                UNIQUE (tenant_id, business_id, workspace_id, request_id),
            CONSTRAINT routing_decisions_tier_requires_continue
                CHECK (execution_tier IS NULL OR disposition = 'continue'),
            CONSTRAINT routing_decisions_tier_known
                CHECK (execution_tier IS NULL OR execution_tier = 'agent'),
            CONSTRAINT routing_decisions_length_non_negative
                CHECK (message_length >= 0)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX routing_decisions_conversation
        ON routing_decisions(
            tenant_id,
            business_id,
            workspace_id,
            conversation_id,
            created_at DESC,
            id DESC
        )
        """
    )
    op.execute(
        """
        CREATE INDEX routing_decisions_disposition
        ON routing_decisions(
            tenant_id,
            business_id,
            workspace_id,
            disposition,
            created_at DESC
        )
        """
    )
    op.execute(
        """
        CREATE INDEX routing_decisions_reason
        ON routing_decisions(
            tenant_id,
            business_id,
            workspace_id,
            reason_code,
            created_at DESC
        )
        """
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS routing_decisions_reason")
    op.execute("DROP INDEX IF EXISTS routing_decisions_disposition")
    op.execute("DROP INDEX IF EXISTS routing_decisions_conversation")
    op.execute("DROP TABLE IF EXISTS routing_decisions")
