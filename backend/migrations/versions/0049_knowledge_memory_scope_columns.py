"""Persist business/workspace scope for knowledge and memory data planes.

The resource tables received scope columns in 0046, but their asynchronous
queues and derived stores still carried tenant-only ownership.  This
migration makes the queue payload durable and gives every worker-owned
knowledge/memory row an explicit three-dimensional scope.

Existing rows are assigned to the compatibility scope
``customer-service/default``.  The defaults keep old seed scripts and direct
service callers working while new writes use the request scope.
"""

from alembic import op

revision = "0049_knowledge_memory_scope"
down_revision = "0048_ticket_approval_scope"
branch_labels = None
depends_on = None


KNOWLEDGE_TABLES = (
    "knowledge_jobs",
    "knowledge_tasks",
    "knowledge_vector_indexes",
    "knowledge_collection_cleanup",
)

MEMORY_TABLES = (
    "memory_customers",
    "memory_identities",
    "memory_items",
    "memory_tasks",
    "memory_injection_log",
)


def _add_scope(table: str) -> None:
    op.execute(
        f"""ALTER TABLE {table}
        ADD COLUMN business_id TEXT NOT NULL DEFAULT 'customer-service',
        ADD COLUMN workspace_id TEXT NOT NULL DEFAULT 'default'"""
    )
    op.execute(
        f"CREATE INDEX ix_{table}_scope "
        f"ON {table}(tenant_id,business_id,workspace_id)"
    )


def upgrade():
    # Some of the early knowledge job tables are retained for compatibility
    # even though current ingestion uses knowledge_tasks.
    for table in KNOWLEDGE_TABLES:
        _add_scope(table)

    op.execute(
        "ALTER TABLE knowledge_jobs "
        "DROP CONSTRAINT IF EXISTS knowledge_jobs_tenant_id_kb_id_content_hash_key"
    )
    op.execute(
        """
        ALTER TABLE knowledge_jobs
        ADD CONSTRAINT knowledge_jobs_scope_upload_key
        UNIQUE (tenant_id,business_id,workspace_id,kb_id,content_hash)
        """
    )

    op.execute(
        "ALTER TABLE knowledge_collection_cleanup "
        "DROP CONSTRAINT IF EXISTS knowledge_collection_cleanup_pkey"
    )
    op.execute(
        """
        ALTER TABLE knowledge_collection_cleanup
        ADD CONSTRAINT knowledge_collection_cleanup_scope_pkey
        PRIMARY KEY (tenant_id,business_id,workspace_id,collection_name)
        """
    )

    op.execute(
        """ALTER TABLE knowledge_semantic_cache
        ADD COLUMN tenant_id TEXT,
        ADD COLUMN business_id TEXT NOT NULL DEFAULT 'customer-service',
        ADD COLUMN workspace_id TEXT NOT NULL DEFAULT 'default'"""
    )
    op.execute(
        """UPDATE knowledge_semantic_cache c
           SET tenant_id=d.tenant_id,
               business_id=d.business_id,
               workspace_id=d.workspace_id
          FROM knowledge_documents d
         WHERE d.id=c.document_id"""
    )
    op.execute("ALTER TABLE knowledge_semantic_cache ALTER COLUMN tenant_id SET NOT NULL")
    op.execute("DROP INDEX IF EXISTS knowledge_active_task")
    op.execute(
        "CREATE UNIQUE INDEX knowledge_active_task_scope "
        "ON knowledge_tasks(tenant_id,business_id,workspace_id,kind,resource_id) "
        "WHERE status IN ('queued','running')"
    )

    op.execute(
        "CREATE UNIQUE INDEX knowledge_upload_cleanup_scope "
        "ON knowledge_collection_cleanup(tenant_id,business_id,workspace_id,collection_name)"
    )
    op.execute(
        "CREATE UNIQUE INDEX knowledge_semantic_cache_scope "
        "ON knowledge_semantic_cache(tenant_id,business_id,workspace_id,document_id,cache_key)"
    )

    for table in MEMORY_TABLES:
        _add_scope(table)

    # Keep the historical index name for compatibility with existing
    # migrations, maintenance scripts, and clients that inspect this index.
    # The index definition itself now includes the full three-dimensional
    # scope, so retaining the name does not weaken isolation.
    op.execute("DROP INDEX IF EXISTS memory_items_lookup")
    op.execute(
        "CREATE INDEX memory_items_lookup "
        "ON memory_items(tenant_id,business_id,workspace_id,customer_id,type,status)"
    )

    op.execute(
        "ALTER TABLE memory_customers "
        "ADD CONSTRAINT memory_customers_scope_id_key "
        "UNIQUE(tenant_id,business_id,workspace_id,id)"
    )
    op.execute(
        "ALTER TABLE memory_identities "
        "DROP CONSTRAINT IF EXISTS memory_identities_tenant_id_source_external_key_key"
    )
    op.execute(
        "ALTER TABLE memory_identities "
        "ADD CONSTRAINT memory_identities_scope_identity_key "
        "UNIQUE(tenant_id,business_id,workspace_id,source,external_key)"
    )
    op.execute(
        "ALTER TABLE memory_items "
        "DROP CONSTRAINT IF EXISTS memory_items_tenant_id_customer_id_type_key_key"
    )
    op.execute(
        "ALTER TABLE memory_items "
        "ADD CONSTRAINT memory_items_scope_key "
        "UNIQUE(tenant_id,business_id,workspace_id,customer_id,type,key)"
    )
    # Keep the original customer_id foreign keys as the database-level
    # lifecycle guard.  A composite FK cannot be added safely here because
    # historical test/import databases may contain tenant-scoped orphan rows
    # that were already tolerated by the pre-scope schema.  All runtime
    # reads/writes still enforce the complete scope predicate.

    # RuntimeRepository predates this migration and inserts injection-log rows
    # with tenant/run/item only.  Fill the durable scope from the run (or,
    # for historical runs, from the memory item) at the database boundary.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fill_memory_injection_scope()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            SELECT r.business_id, r.workspace_id
              INTO NEW.business_id, NEW.workspace_id
              FROM runtime_runs r
             WHERE r.id = NEW.run_id
               AND r.tenant_id = NEW.tenant_id;
            IF NEW.business_id IS NULL THEN
                SELECT i.business_id, i.workspace_id
                  INTO NEW.business_id, NEW.workspace_id
                  FROM memory_items i
                 WHERE i.id = NEW.item_id
                   AND i.tenant_id = NEW.tenant_id;
            END IF;
            NEW.business_id := COALESCE(NEW.business_id, 'customer-service');
            NEW.workspace_id := COALESCE(NEW.workspace_id, 'default');
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER memory_injection_scope_trigger
        BEFORE INSERT ON memory_injection_log
        FOR EACH ROW EXECUTE FUNCTION fill_memory_injection_scope()
        """
    )


def downgrade():
    op.execute("DROP TRIGGER IF EXISTS memory_injection_scope_trigger ON memory_injection_log")
    op.execute("DROP FUNCTION IF EXISTS fill_memory_injection_scope()")
    op.execute(
        "ALTER TABLE memory_items DROP CONSTRAINT IF EXISTS memory_items_scope_customer_fk"
    )
    op.execute(
        "ALTER TABLE memory_identities DROP CONSTRAINT IF EXISTS memory_identities_scope_customer_fk"
    )
    op.execute("ALTER TABLE memory_items DROP CONSTRAINT memory_items_scope_key")
    op.execute(
        "ALTER TABLE memory_items ADD CONSTRAINT memory_items_tenant_id_customer_id_type_key_key "
        "UNIQUE(tenant_id,customer_id,type,key)"
    )
    op.execute("ALTER TABLE memory_identities DROP CONSTRAINT memory_identities_scope_identity_key")
    op.execute(
        "ALTER TABLE memory_identities ADD CONSTRAINT memory_identities_tenant_id_source_external_key_key "
        "UNIQUE(tenant_id,source,external_key)"
    )
    op.execute("ALTER TABLE memory_customers DROP CONSTRAINT memory_customers_scope_id_key")
    op.execute("DROP INDEX memory_items_lookup")
    op.execute(
        "CREATE INDEX memory_items_lookup ON memory_items (tenant_id, customer_id, type, status)"
    )
    op.execute("DROP INDEX knowledge_semantic_cache_scope")
    op.execute("DROP INDEX knowledge_upload_cleanup_scope")
    op.execute("DROP INDEX knowledge_active_task_scope")
    op.execute(
        "CREATE UNIQUE INDEX knowledge_active_task "
        "ON knowledge_tasks(tenant_id,kind,resource_id) WHERE status IN ('queued','running')"
    )
    for table in reversed(MEMORY_TABLES):
        op.execute(f"DROP INDEX ix_{table}_scope")
        op.execute(f"ALTER TABLE {table} DROP COLUMN workspace_id, DROP COLUMN business_id")
    op.execute(
        "ALTER TABLE knowledge_collection_cleanup "
        "DROP CONSTRAINT IF EXISTS knowledge_collection_cleanup_scope_pkey"
    )
    op.execute(
        "ALTER TABLE knowledge_collection_cleanup "
        "ADD CONSTRAINT knowledge_collection_cleanup_pkey PRIMARY KEY (collection_name)"
    )
    op.execute(
        "ALTER TABLE knowledge_jobs "
        "DROP CONSTRAINT IF EXISTS knowledge_jobs_scope_upload_key"
    )
    op.execute(
        "ALTER TABLE knowledge_jobs "
        "ADD CONSTRAINT knowledge_jobs_tenant_id_kb_id_content_hash_key "
        "UNIQUE (tenant_id,kb_id,content_hash)"
    )
    op.execute(
        "ALTER TABLE knowledge_semantic_cache "
        "DROP COLUMN workspace_id, DROP COLUMN business_id, DROP COLUMN tenant_id"
    )
    for table in reversed(KNOWLEDGE_TABLES):
        op.execute(f"DROP INDEX ix_{table}_scope")
        op.execute(f"ALTER TABLE {table} DROP COLUMN workspace_id, DROP COLUMN business_id")
