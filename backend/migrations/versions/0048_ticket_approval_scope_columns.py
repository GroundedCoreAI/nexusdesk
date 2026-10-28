"""Persist business/workspace ownership for Ticket and Approval resources."""

from alembic import op

revision = "0048_ticket_approval_scope"
down_revision = "0047_runtime_scope_columns"
branch_labels = None
depends_on = None


SCOPED_TABLES = (
    "approval_requests",
    "ticket_types",
    "ticket_type_versions",
    "tickets",
    "tickets_detail",
    "ticket_process_log",
)


def upgrade():
    for table in SCOPED_TABLES:
        op.execute(
            f"ALTER TABLE {table} "
            "ADD COLUMN business_id TEXT NOT NULL DEFAULT 'customer-service', "
            "ADD COLUMN workspace_id TEXT NOT NULL DEFAULT 'default'"
        )
        op.execute(
            f"CREATE INDEX ix_{table}_scope "
            f"ON {table}(tenant_id,business_id,workspace_id)"
        )

    # 0047 added scope-aware conversation identity, but the dependent runtime
    # rows still need composite keys before ticket foreign keys can reference
    # them.
    op.execute(
        """
        ALTER TABLE pending_actions
        ADD CONSTRAINT pending_actions_scope_id_key
        UNIQUE (tenant_id,business_id,workspace_id,id)
        """
    )
    op.execute(
        """
        ALTER TABLE runtime_runs
        ADD CONSTRAINT runtime_runs_scope_id_key
        UNIQUE (tenant_id,business_id,workspace_id,id)
        """
    )

    # Approval idempotency is a scope-local concern.  Keeping the old tenant
    # unique key would prevent the same client key from being reused in
    # another business/workspace.
    op.execute(
        "ALTER TABLE approval_requests "
        "DROP CONSTRAINT IF EXISTS approval_requests_tenant_id_idempotency_key_key"
    )
    op.execute(
        """
        ALTER TABLE approval_requests
        ADD CONSTRAINT approval_requests_scope_idempotency_key
        UNIQUE (tenant_id,business_id,workspace_id,idempotency_key)
        """
    )

    # Ticket type codes and ticket numbers are also scoped.  IDs remain
    # tenant-unique for backward compatibility, while composite keys make
    # scope-aware foreign keys possible.
    op.execute(
        "ALTER TABLE ticket_types "
        "DROP CONSTRAINT IF EXISTS ticket_types_tenant_id_code_key"
    )
    op.execute(
        """
        ALTER TABLE ticket_types
        ADD CONSTRAINT ticket_types_scope_code_key
        UNIQUE (tenant_id,business_id,workspace_id,code),
        ADD CONSTRAINT ticket_types_scope_id_key
        UNIQUE (tenant_id,business_id,workspace_id,id)
        """
    )
    op.execute(
        """
        ALTER TABLE ticket_type_versions
        ADD CONSTRAINT ticket_type_versions_scope_key
        UNIQUE (tenant_id,business_id,workspace_id,type_id,version)
        """
    )
    op.execute(
        "ALTER TABLE ticket_types DROP CONSTRAINT IF EXISTS ticket_types_published_fk"
    )
    op.execute(
        """
        ALTER TABLE ticket_types
        ADD CONSTRAINT ticket_types_scope_published_fk
        FOREIGN KEY (tenant_id,business_id,workspace_id,id,published_version)
        REFERENCES ticket_type_versions
            (tenant_id,business_id,workspace_id,type_id,version)
        DEFERRABLE INITIALLY DEFERRED
        """
    )

    op.execute(
        "ALTER TABLE tickets DROP CONSTRAINT IF EXISTS tickets_number_key"
    )
    op.execute(
        """
        ALTER TABLE tickets
        ADD CONSTRAINT tickets_scope_number_key
        UNIQUE (tenant_id,business_id,workspace_id,ticket_no),
        ADD CONSTRAINT tickets_scope_id_key
        UNIQUE (tenant_id,business_id,workspace_id,id)
        """
    )
    op.execute(
        """
        ALTER TABLE tickets
        ADD CONSTRAINT tickets_scope_conversation_fk
        FOREIGN KEY (tenant_id,business_id,workspace_id,conversation_id)
        REFERENCES runtime_conversations
            (tenant_id,business_id,workspace_id,id)
        """
    )
    op.execute(
        """
        ALTER TABLE tickets
        ADD CONSTRAINT tickets_scope_action_fk
        FOREIGN KEY (tenant_id,business_id,workspace_id,action_id)
        REFERENCES pending_actions
            (tenant_id,business_id,workspace_id,id)
        """
    )
    op.execute(
        """
        ALTER TABLE tickets
        ADD CONSTRAINT tickets_scope_run_fk
        FOREIGN KEY (tenant_id,business_id,workspace_id,source_run_id)
        REFERENCES runtime_runs
            (tenant_id,business_id,workspace_id,id)
        """
    )
    op.execute(
        """
        ALTER TABLE tickets
        ADD CONSTRAINT tickets_scope_type_fk
        FOREIGN KEY (tenant_id,business_id,workspace_id,type_id,type_version)
        REFERENCES ticket_type_versions
            (tenant_id,business_id,workspace_id,type_id,version)
        """
    )
    op.execute(
        """
        ALTER TABLE tickets_detail
        ADD CONSTRAINT tickets_detail_scope_ticket_fk
        FOREIGN KEY (tenant_id,business_id,workspace_id,ticket_id)
        REFERENCES tickets
            (tenant_id,business_id,workspace_id,id)
        """
    )
    op.execute(
        """
        ALTER TABLE ticket_process_log
        ADD CONSTRAINT ticket_process_log_scope_ticket_fk
        FOREIGN KEY (tenant_id,business_id,workspace_id,ticket_id)
        REFERENCES tickets
            (tenant_id,business_id,workspace_id,id)
        """
    )
    op.execute(
        """
        ALTER TABLE ticket_process_log
        ADD CONSTRAINT ticket_process_log_scope_run_fk
        FOREIGN KEY (tenant_id,business_id,workspace_id,source_run_id)
        REFERENCES runtime_runs
            (tenant_id,business_id,workspace_id,id)
        """
    )


def downgrade():
    op.execute(
        "ALTER TABLE ticket_process_log "
        "DROP CONSTRAINT IF EXISTS ticket_process_log_scope_run_fk, "
        "DROP CONSTRAINT IF EXISTS ticket_process_log_scope_ticket_fk"
    )
    op.execute(
        "ALTER TABLE runtime_runs "
        "DROP CONSTRAINT IF EXISTS runtime_runs_scope_id_key"
    )
    op.execute(
        "ALTER TABLE pending_actions "
        "DROP CONSTRAINT IF EXISTS pending_actions_scope_id_key"
    )
    op.execute(
        "ALTER TABLE tickets_detail "
        "DROP CONSTRAINT IF EXISTS tickets_detail_scope_ticket_fk"
    )
    op.execute(
        "ALTER TABLE tickets "
        "DROP CONSTRAINT IF EXISTS tickets_scope_type_fk, "
        "DROP CONSTRAINT IF EXISTS tickets_scope_run_fk, "
        "DROP CONSTRAINT IF EXISTS tickets_scope_action_fk, "
        "DROP CONSTRAINT IF EXISTS tickets_scope_conversation_fk, "
        "DROP CONSTRAINT IF EXISTS tickets_scope_id_key, "
        "DROP CONSTRAINT IF EXISTS tickets_scope_number_key"
    )
    op.execute(
        "ALTER TABLE tickets ADD CONSTRAINT tickets_number_key "
        "UNIQUE(tenant_id,ticket_no)"
    )
    op.execute(
        "ALTER TABLE ticket_types "
        "DROP CONSTRAINT IF EXISTS ticket_types_scope_published_fk"
    )
    op.execute(
        "ALTER TABLE ticket_type_versions "
        "DROP CONSTRAINT IF EXISTS ticket_type_versions_scope_key"
    )
    op.execute(
        "ALTER TABLE ticket_types "
        "DROP CONSTRAINT IF EXISTS ticket_types_scope_code_key, "
        "DROP CONSTRAINT IF EXISTS ticket_types_scope_id_key"
    )
    op.execute(
        "ALTER TABLE ticket_types ADD CONSTRAINT ticket_types_published_fk "
        "FOREIGN KEY(tenant_id,id,published_version) "
        "REFERENCES ticket_type_versions(tenant_id,type_id,version) "
        "DEFERRABLE INITIALLY DEFERRED"
    )
    op.execute(
        "ALTER TABLE ticket_types ADD CONSTRAINT ticket_types_tenant_id_code_key "
        "UNIQUE(tenant_id,code)"
    )
    op.execute(
        "ALTER TABLE approval_requests "
        "DROP CONSTRAINT IF EXISTS approval_requests_scope_idempotency_key"
    )
    op.execute(
        "ALTER TABLE approval_requests ADD CONSTRAINT "
        "approval_requests_tenant_id_idempotency_key_key "
        "UNIQUE(tenant_id,idempotency_key)"
    )
    for table in reversed(SCOPED_TABLES):
        op.execute(f"DROP INDEX IF EXISTS ix_{table}_scope")
        op.execute(
            f"ALTER TABLE {table} DROP COLUMN workspace_id, DROP COLUMN business_id"
        )
