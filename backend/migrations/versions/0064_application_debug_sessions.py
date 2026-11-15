"""Allow application debug sessions in the Runtime and ledger tables.

Debug previews now run through the real customer chain instead of a mock
executor. A debug session is a real Runtime conversation and a real ledger
conversation, marked so it never mixes into customer statistics:

- ``runtime_conversations.source`` gains ``'debug'`` (workbench lists and
  counts exclude it);
- ``application_version = 0`` marks a draft debug session on both
  ``runtime_conversations`` and ``service_application_turns`` (a draft has no
  release version yet), so the ``> 0`` checks become ``>= 0``.

The ledger ``kind`` check already reserved ``'debug'``.
"""

from alembic import op

revision = "0064_application_debug_sessions"
down_revision = "0063_knowledge_pgvector"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE runtime_conversations DROP CONSTRAINT "
        "runtime_conversations_source_check",
    )
    op.execute(
        "ALTER TABLE runtime_conversations ADD CONSTRAINT "
        "runtime_conversations_source_check CHECK "
        "(source IN ('business', 'playground', 'debug'))",
    )
    for table in ("runtime_conversations", "service_application_turns",
                  "service_application_traces"):
        op.execute(
            f"ALTER TABLE {table} DROP CONSTRAINT {table}_application_version_check",
        )
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT "
            f"{table}_application_version_check CHECK (application_version >= 0)",
        )


def downgrade() -> None:
    op.execute(
        "DELETE FROM runtime_conversations WHERE source = 'debug'",
    )
    op.execute(
        "ALTER TABLE runtime_conversations DROP CONSTRAINT "
        "runtime_conversations_source_check",
    )
    op.execute(
        "ALTER TABLE runtime_conversations ADD CONSTRAINT "
        "runtime_conversations_source_check CHECK "
        "(source IN ('business', 'playground'))",
    )
    for table in ("runtime_conversations", "service_application_turns",
                  "service_application_traces"):
        op.execute(
            f"ALTER TABLE {table} DROP CONSTRAINT {table}_application_version_check",
        )
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT "
            f"{table}_application_version_check CHECK (application_version > 0)",
        )
