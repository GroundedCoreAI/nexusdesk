"""Bind open-platform applications to a delivery subject.

The open platform started as an agent gateway: one application key authorised a
list of agents (``open_applications.agent_ids``). Delivery now needs a second
subject kind — a published Service Application, which carries its own skills,
connections, rules and knowledge. The two semantics are kept apart instead of
overloading ``agent_ids``:

- ``open_application_targets`` holds the delivery subject rows. An application
  may list agents (legacy, an authorisation list) or exactly one service
  application (new, the delivery subject), enforced by a partial unique index.
- Existing ``agent_ids`` are backfilled as ``target_kind='agent'`` rows so the
  delivery view is complete for legacy applications too; ``agent_ids`` stays
  authoritative for the legacy execution path.

Two constraints must widen for open-platform conversations that run an
application:

- ``runtime_conversations.source`` gains ``'open_platform'`` so workbench
  counts can tell external traffic apart from business/debug/playground.
- ``open_sessions.agent_id`` becomes nullable: an application session is pinned
  to an application release, not to a single agent.
"""

from alembic import op

revision = "0065_open_platform_targets"
down_revision = "0064_application_debug_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE open_application_targets (
          app_id      uuid NOT NULL REFERENCES open_applications(id) ON DELETE CASCADE,
          target_kind text NOT NULL,
          target_id   uuid NOT NULL,
          version_pin integer,
          created_at  timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (app_id, target_kind, target_id),
          CONSTRAINT open_application_targets_kind_check
            CHECK (target_kind IN ('agent', 'service_application')),
          CONSTRAINT open_application_targets_version_check
            CHECK (version_pin IS NULL OR version_pin > 0)
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX open_targets_single_application
          ON open_application_targets(app_id)
          WHERE target_kind = 'service_application'
        """
    )
    op.execute(
        """
        CREATE INDEX open_targets_target
          ON open_application_targets(target_kind, target_id)
        """
    )
    # Backfill the legacy authorisation list so every application has an
    # explicit delivery view. A missing pin means "follow the published version".
    op.execute(
        """
        INSERT INTO open_application_targets(app_id, target_kind, target_id, version_pin)
        SELECT a.id,
               'agent',
               t.agent_id,
               NULLIF((a.agent_versions ->> t.agent_id::text)::int, 0)
        FROM open_applications a
        CROSS JOIN LATERAL unnest(a.agent_ids) AS t(agent_id)
        ON CONFLICT DO NOTHING
        """
    )
    op.execute(
        "ALTER TABLE runtime_conversations DROP CONSTRAINT "
        "runtime_conversations_source_check",
    )
    op.execute(
        "ALTER TABLE runtime_conversations ADD CONSTRAINT "
        "runtime_conversations_source_check CHECK "
        "(source IN ('business', 'playground', 'debug', 'open_platform'))",
    )
    op.execute("ALTER TABLE open_sessions ALTER COLUMN agent_id DROP NOT NULL")


def downgrade() -> None:
    # Application-mode sessions have no agent and no legacy reader; remove them
    # before the column becomes NOT NULL again. Run-level rows reference the
    # conversation without ON DELETE CASCADE, so they go first, in dependency
    # order.
    op.execute("DELETE FROM open_sessions WHERE agent_id IS NULL")
    op.execute(
        """
        DELETE FROM runtime_events WHERE run_id IN (
          SELECT id FROM runtime_runs
          WHERE conversation_id IN (
            SELECT id FROM runtime_conversations WHERE source='open_platform'
          )
        )
        """
    )
    op.execute(
        """
        DELETE FROM runtime_runs WHERE conversation_id IN (
          SELECT id FROM runtime_conversations WHERE source='open_platform'
        )
        """
    )
    op.execute(
        """
        DELETE FROM conversation_messages WHERE conversation_id IN (
          SELECT id FROM runtime_conversations WHERE source='open_platform'
        )
        """
    )
    op.execute("DELETE FROM runtime_conversations WHERE source='open_platform'")
    op.execute(
        "ALTER TABLE runtime_conversations DROP CONSTRAINT "
        "runtime_conversations_source_check",
    )
    op.execute(
        "ALTER TABLE runtime_conversations ADD CONSTRAINT "
        "runtime_conversations_source_check CHECK "
        "(source IN ('business', 'playground', 'debug'))",
    )
    op.execute("ALTER TABLE open_sessions ALTER COLUMN agent_id SET NOT NULL")
    op.execute("DROP INDEX IF EXISTS open_targets_target")
    op.execute("DROP INDEX IF EXISTS open_targets_single_application")
    op.execute("DROP TABLE IF EXISTS open_application_targets")
