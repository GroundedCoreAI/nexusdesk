"""Backfill ``memory_items.embedding`` for databases that added pgvector later.

Migration 0036 created the column inside a ``pg_available_extensions`` probe, so
any deployment whose server had no pgvector at that moment migrated cleanly and
simply kept the TSVECTOR fallback. Installing the extension afterwards left the
column missing, which keeps ``memory_vector_enabled=auto`` on keyword mode
forever — the store probe sees "extension installed, column absent" and refuses
to pick vector mode because every query would fail at runtime.

This migration is the documented follow-up step: idempotent, no-op when the
extension is still unavailable or the column already exists.
"""

from alembic import op

revision = "0062_memory_embedding_backfill"
down_revision = "0061_notification_read_state"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_available_extensions WHERE name='vector')
               AND NOT EXISTS (
                   SELECT 1 FROM information_schema.columns
                   WHERE table_name='memory_items' AND column_name='embedding'
               ) THEN
                CREATE EXTENSION IF NOT EXISTS vector;
                ALTER TABLE memory_items ADD COLUMN embedding vector(1536);
                CREATE INDEX IF NOT EXISTS memory_items_embedding ON memory_items
                    USING hnsw (embedding vector_cosine_ops);
            END IF;
        END $$;
    """)


def downgrade():
    # The embedding column predates this migration on servers that had pgvector
    # at 0036 time, so dropping it here could delete live vectors. Leave it.
    pass
