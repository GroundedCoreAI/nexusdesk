"""Persist tenant, business, and workspace ownership for runtime data."""

from alembic import op

revision = "0047_runtime_scope_columns"
down_revision = "0046_resource_scope_columns"
branch_labels = None
depends_on = None


TABLES = (
    "runtime_conversations",
    "runtime_runs",
    "handoffs",
    "pending_actions",
)


def upgrade():
    # The old tenant-only key prevented the same external conversation id
    # from existing in two business workspaces.  Scope is now part of the
    # identity.
    op.execute(
        "ALTER TABLE runtime_conversations "
        "DROP CONSTRAINT IF EXISTS runtime_conversations_tenant_id_external_id_key"
    )
    op.execute(
        "ALTER TABLE pending_actions DROP CONSTRAINT IF EXISTS pending_actions_tenant_id_dedup_key"
    )
    for table in TABLES:
        op.execute(
            f"ALTER TABLE {table} "
            "ADD COLUMN business_id TEXT NOT NULL DEFAULT 'customer-service', "
            "ADD COLUMN workspace_id TEXT NOT NULL DEFAULT 'default'"
        )
        op.execute(f"CREATE INDEX ix_{table}_scope ON {table}(tenant_id,business_id,workspace_id)")

    # A run, handoff, or pending action must not be attachable to a
    # conversation from another business/workspace.  The existing id-only
    # foreign keys remain for compatibility with older migrations; these
    # composite keys make the new invariant durable.
    op.execute(
        """
        ALTER TABLE runtime_conversations
        ADD CONSTRAINT runtime_conversations_scope_external_key
        UNIQUE (tenant_id,business_id,workspace_id,external_id)
        """
    )
    op.execute(
        """
        ALTER TABLE pending_actions
        ADD CONSTRAINT pending_actions_scope_dedup_key
        UNIQUE (tenant_id,business_id,workspace_id,dedup_key)
        """
    )
    op.execute(
        """
        ALTER TABLE runtime_conversations
        ADD CONSTRAINT runtime_conversations_scope_id_key
        UNIQUE (tenant_id,business_id,workspace_id,id)
        """
    )
    op.execute(
        """
        ALTER TABLE runtime_runs
        ADD CONSTRAINT runtime_runs_conversation_scope_fk
        FOREIGN KEY (tenant_id,business_id,workspace_id,conversation_id)
        REFERENCES runtime_conversations(tenant_id,business_id,workspace_id,id)
        """
    )
    op.execute(
        """
        ALTER TABLE handoffs
        ADD CONSTRAINT handoffs_conversation_scope_fk
        FOREIGN KEY (tenant_id,business_id,workspace_id,conversation_id)
        REFERENCES runtime_conversations(tenant_id,business_id,workspace_id,id)
        """
    )
    op.execute(
        """
        ALTER TABLE pending_actions
        ADD CONSTRAINT pending_actions_conversation_scope_fk
        FOREIGN KEY (tenant_id,business_id,workspace_id,conversation_id)
        REFERENCES runtime_conversations(tenant_id,business_id,workspace_id,id)
        """
    )


def downgrade():
    op.execute("ALTER TABLE pending_actions DROP CONSTRAINT pending_actions_conversation_scope_fk")
    op.execute("ALTER TABLE handoffs DROP CONSTRAINT handoffs_conversation_scope_fk")
    op.execute("ALTER TABLE runtime_runs DROP CONSTRAINT runtime_runs_conversation_scope_fk")
    op.execute(
        "ALTER TABLE runtime_conversations DROP CONSTRAINT runtime_conversations_scope_id_key"
    )
    op.execute(
        "ALTER TABLE runtime_conversations DROP CONSTRAINT runtime_conversations_scope_external_key"
    )
    op.execute(
        "ALTER TABLE runtime_conversations "
        "ADD CONSTRAINT runtime_conversations_tenant_id_external_id_key "
        "UNIQUE (tenant_id,external_id)"
    )
    op.execute("ALTER TABLE pending_actions DROP CONSTRAINT pending_actions_scope_dedup_key")
    op.execute(
        "ALTER TABLE pending_actions "
        "ADD CONSTRAINT pending_actions_tenant_id_dedup_key "
        "UNIQUE (tenant_id,dedup_key)"
    )
    for table in reversed(TABLES):
        op.execute(f"DROP INDEX ix_{table}_scope")
        op.execute(f"ALTER TABLE {table} DROP COLUMN workspace_id, DROP COLUMN business_id")
