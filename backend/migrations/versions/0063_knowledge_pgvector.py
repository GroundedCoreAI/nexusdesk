"""Add the pgvector side of the knowledge vector store.

``knowledge_vector_indexes`` already models one immutable snapshot per library
(``collection_name`` + ``profile_id``/``profile_version`` + ``dimension``), a
shape Milvus needs because a collection is the unit of atomic swap. pgvector can
reuse the same contract: ``collection_name`` becomes a plain column, so a
publication still builds a brand-new snapshot and flips the pointer, and the old
snapshot is dropped by the existing cleanup queue.

``embedding`` is declared without a typmod on purpose. Memory fixes its column at
``vector(1536)`` because one profile serves all rows; a knowledge library stores
whatever dimension its published embedding profile declares, and different
libraries may legitimately use different models. A ``dimension`` column carries
the width so rows from different spaces never meet, and the HNSW index is built
per dimension by the application (see ``knowledge/vector_backends.py``).

No-op when the server has no pgvector extension: the table simply stays absent
and the backend reports ``pgvector_not_installed`` with a pointer to the milvus
alternative instead of failing the migration.
"""

from alembic import op

revision = "0063_knowledge_pgvector"
down_revision = "0062_memory_embedding_backfill"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_available_extensions WHERE name='vector') THEN
                CREATE EXTENSION IF NOT EXISTS vector;
                CREATE TABLE IF NOT EXISTS knowledge_chunk_vectors(
                    collection_name text NOT NULL,
                    chunk_id uuid NOT NULL,
                    tenant_id text NOT NULL,
                    business_id text NOT NULL,
                    workspace_id text NOT NULL,
                    kb_id uuid NOT NULL,
                    dimension integer NOT NULL,
                    embedding vector NOT NULL,
                    PRIMARY KEY(collection_name, chunk_id)
                );
                CREATE INDEX IF NOT EXISTS knowledge_chunk_vectors_scope
                    ON knowledge_chunk_vectors(collection_name, tenant_id, kb_id, dimension);
            END IF;
        END $$;
    """)
    # A published index belongs to one store: its collection name only means
    # something to the backend that created it. Without this column, switching
    # ``knowledge_vector_backend`` would leave retrieval searching the new store
    # for a name that only exists in the old one and silently return nothing.
    # Existing rows predate the switch point, so they are all Milvus.
    op.execute("""
        ALTER TABLE knowledge_vector_indexes
        ADD COLUMN IF NOT EXISTS backend text NOT NULL DEFAULT 'milvus'
    """)


def downgrade():
    op.execute("ALTER TABLE knowledge_vector_indexes DROP COLUMN IF EXISTS backend")
    op.execute("DROP TABLE IF EXISTS knowledge_chunk_vectors")
