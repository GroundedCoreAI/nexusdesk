"""Customer-visible service application conversation ledger.

Runtime tables remain the source of truth for context, tools, events, and
diagnostics. This migration adds the business-facing conversation, message,
and turn ledger used by channels and customer-service reads. Customer and
debug traffic intentionally share the same tables and are separated by
``kind``.
"""

from alembic import op

revision = "0059_service_app_conversation"
down_revision = "0058_service_application_v2"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        CREATE TABLE service_application_conversations (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id TEXT NOT NULL,
            business_id TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            application_id UUID NOT NULL,
            kind TEXT NOT NULL DEFAULT 'customer'
                CHECK (kind IN ('customer', 'debug')),
            status TEXT NOT NULL DEFAULT 'open'
                CHECK (status IN ('open', 'waiting', 'human', 'closed')),
            channel_id UUID NULL REFERENCES channels(id) ON DELETE SET NULL,
            external_conversation_id TEXT NULL,
            customer_id UUID NULL REFERENCES memory_customers(id) ON DELETE SET NULL,
            external_user_id TEXT NULL,
            user_name TEXT NULL,
            assigned_to TEXT NULL,
            agent_id UUID NULL REFERENCES agents(id) ON DELETE SET NULL,
            agent_version INTEGER NULL CHECK (agent_version > 0),
            last_message_at TIMESTAMPTZ NULL,
            created_by TEXT NOT NULL,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT service_application_conversations_scope_id_unique
                UNIQUE (tenant_id, business_id, workspace_id, id),
            CONSTRAINT service_application_conversations_application_fk
                FOREIGN KEY (tenant_id, business_id, workspace_id, application_id)
                REFERENCES service_applications (
                    tenant_id,
                    business_id,
                    workspace_id,
                    id
                )
                ON DELETE CASCADE
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX service_application_conversations_external_unique
        ON service_application_conversations (
            tenant_id,
            business_id,
            workspace_id,
            application_id,
            kind,
            channel_id,
            external_conversation_id
        )
        WHERE channel_id IS NOT NULL AND external_conversation_id IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE INDEX service_application_conversations_activity
        ON service_application_conversations (
            tenant_id,
            business_id,
            workspace_id,
            application_id,
            kind,
            last_message_at DESC,
            updated_at DESC,
            id DESC
        )
        """
    )
    op.execute(
        """
        CREATE INDEX service_application_conversations_status
        ON service_application_conversations (
            tenant_id,
            business_id,
            workspace_id,
            kind,
            status,
            updated_at DESC
        )
        """
    )

    op.execute(
        """
        CREATE TABLE service_application_messages (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id TEXT NOT NULL,
            business_id TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            conversation_id UUID NOT NULL,
            seq BIGINT NOT NULL CHECK (seq > 0),
            role TEXT NOT NULL
                CHECK (role IN ('customer', 'assistant', 'human', 'system')),
            content TEXT NOT NULL,
            content_type TEXT NOT NULL DEFAULT 'text',
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            runtime_message_id UUID NULL
                REFERENCES conversation_messages(id) ON DELETE SET NULL,
            idempotency_key TEXT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT service_application_messages_sequence_unique
                UNIQUE (
                    tenant_id,
                    business_id,
                    workspace_id,
                    conversation_id,
                    seq
                ),
            CONSTRAINT service_application_messages_conversation_fk
                FOREIGN KEY (tenant_id, business_id, workspace_id, conversation_id)
                REFERENCES service_application_conversations (
                    tenant_id,
                    business_id,
                    workspace_id,
                    id
                )
                ON DELETE CASCADE
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX service_application_messages_idempotency_unique
        ON service_application_messages (
            tenant_id,
            business_id,
            workspace_id,
            conversation_id,
            idempotency_key
        )
        WHERE idempotency_key IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX service_application_messages_runtime_unique
        ON service_application_messages (runtime_message_id)
        WHERE runtime_message_id IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE INDEX service_application_messages_order
        ON service_application_messages (
            tenant_id,
            business_id,
            workspace_id,
            conversation_id,
            seq
        )
        """
    )

    op.execute(
        """
        CREATE TABLE service_application_turns (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id TEXT NOT NULL,
            business_id TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            conversation_id UUID NOT NULL,
            customer_message_id UUID NOT NULL,
            assistant_message_id UUID NULL,
            runtime_conversation_id UUID NULL
                REFERENCES runtime_conversations(id) ON DELETE SET NULL,
            runtime_run_id UUID NULL UNIQUE
                REFERENCES runtime_runs(id) ON DELETE SET NULL,
            application_version INTEGER NOT NULL CHECK (application_version > 0),
            agent_id UUID NOT NULL REFERENCES agents(id),
            agent_version INTEGER NOT NULL CHECK (agent_version > 0),
            status TEXT NOT NULL DEFAULT 'queued'
                CHECK (status IN ('queued', 'running', 'completed', 'failed', 'cancelled')),
            error_code TEXT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            finished_at TIMESTAMPTZ NULL,
            CONSTRAINT service_application_turns_customer_message_unique
                UNIQUE (customer_message_id),
            CONSTRAINT service_application_turns_conversation_fk
                FOREIGN KEY (tenant_id, business_id, workspace_id, conversation_id)
                REFERENCES service_application_conversations (
                    tenant_id,
                    business_id,
                    workspace_id,
                    id
                )
                ON DELETE CASCADE,
            CONSTRAINT service_application_turns_customer_message_fk
                FOREIGN KEY (customer_message_id)
                REFERENCES service_application_messages(id) ON DELETE CASCADE,
            CONSTRAINT service_application_turns_assistant_message_fk
                FOREIGN KEY (assistant_message_id)
                REFERENCES service_application_messages(id) ON DELETE SET NULL
        )
        """
    )
    op.execute(
        """
        CREATE INDEX service_application_turns_conversation
        ON service_application_turns (
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
        CREATE INDEX service_application_turns_runtime_conversation
        ON service_application_turns (
            tenant_id,
            business_id,
            workspace_id,
            runtime_conversation_id
        )
        """
    )

    # Backfill only formal channel traffic. Runtime-backed playground and
    # preview conversations do not have channel mappings and are excluded.
    op.execute(
        """
        INSERT INTO service_application_conversations (
            id,
            tenant_id,
            business_id,
            workspace_id,
            application_id,
            kind,
            status,
            channel_id,
            external_conversation_id,
            customer_id,
            external_user_id,
            user_name,
            assigned_to,
            agent_id,
            agent_version,
            last_message_at,
            created_by,
            metadata,
            created_at,
            updated_at
        )
        SELECT
            gen_random_uuid(),
            r.tenant_id,
            r.business_id,
            r.workspace_id,
            r.application_id,
            'customer',
            CASE r.mode
                WHEN 'open' THEN 'open'
                WHEN 'bot' THEN 'open'
                WHEN 'waiting' THEN 'waiting'
                WHEN 'human' THEN 'human'
                WHEN 'closed' THEN 'closed'
                ELSE 'open'
            END,
            cc.channel_id,
            cc.external_conversation_id,
            r.customer_id,
            cc.external_user_id,
            COALESCE(
                NULLIF(cc.target->>'user_name', ''),
                NULLIF(cc.target->>'display_name', ''),
                NULLIF(cc.target->>'nickname', ''),
                NULLIF(cc.target->>'name', '')
            ),
            r.assigned_to,
            r.agent_id,
            r.agent_version,
            (
                SELECT max(m.created_at)
                FROM conversation_messages m
                WHERE m.conversation_id=r.id
            ),
            'migration:0059',
            jsonb_build_object(
                'backfilled', true,
                'runtime_conversation_id', r.id,
                'provider', ch.provider,
                'channel_name', ch.name
            ),
            r.created_at,
            COALESCE(r.updated_at, r.created_at)
        FROM runtime_conversations r
        JOIN LATERAL (
            SELECT cc.channel_id,
                   cc.external_conversation_id,
                   cc.external_user_id,
                   cc.target
            FROM channel_conversations cc
            WHERE cc.conversation_id=r.id
            ORDER BY cc.updated_at DESC, cc.created_at DESC
            LIMIT 1
        ) cc ON TRUE
        JOIN channels ch
          ON ch.id=cc.channel_id
         AND ch.tenant_id=r.tenant_id
         AND ch.business_id=r.business_id
         AND ch.workspace_id=r.workspace_id
         AND ch.application_id=r.application_id
        WHERE r.source='business'
          AND r.application_id IS NOT NULL
        ON CONFLICT DO NOTHING
        """
    )

    op.execute(
        """
        INSERT INTO service_application_messages (
            id,
            tenant_id,
            business_id,
            workspace_id,
            conversation_id,
            seq,
            role,
            content,
            content_type,
            payload,
            runtime_message_id,
            idempotency_key,
            created_at
        )
        SELECT
            gen_random_uuid(),
            c.tenant_id,
            c.business_id,
            c.workspace_id,
            c.id,
            row_number() OVER (
                PARTITION BY c.id
                ORDER BY m.seq, m.id
            ),
            CASE m.role WHEN 'user' THEN 'customer' ELSE m.role END,
            m.content,
            'text',
            jsonb_build_object('backfilled', true),
            m.id,
            'runtime-message:' || m.id::text,
            m.created_at
        FROM service_application_conversations c
        JOIN runtime_conversations r
          ON r.id::text=c.metadata->>'runtime_conversation_id'
         AND r.tenant_id=c.tenant_id
         AND r.business_id=c.business_id
         AND r.workspace_id=c.workspace_id
        JOIN conversation_messages m ON m.conversation_id=r.id
        WHERE c.kind='customer'
          AND c.created_by='migration:0059'
        ON CONFLICT DO NOTHING
        """
    )

    op.execute(
        """
        INSERT INTO service_application_turns (
            id,
            tenant_id,
            business_id,
            workspace_id,
            conversation_id,
            customer_message_id,
            assistant_message_id,
            runtime_conversation_id,
            runtime_run_id,
            application_version,
            agent_id,
            agent_version,
            status,
            error_code,
            created_at,
            finished_at
        )
        SELECT
            gen_random_uuid(),
            c.tenant_id,
            c.business_id,
            c.workspace_id,
            c.id,
            customer_message.id,
            assistant_message.id,
            rr.conversation_id,
            rr.id,
            COALESCE(r.application_version, ch.application_version, 1),
            COALESCE(r.agent_id, a.agent_id),
            COALESCE(r.agent_version, a.agent_version),
            CASE rr.status
                WHEN 'queued' THEN 'queued'
                WHEN 'running' THEN 'running'
                WHEN 'completed' THEN 'completed'
                WHEN 'failed' THEN 'failed'
                WHEN 'cancelled' THEN 'cancelled'
                ELSE 'failed'
            END,
            rr.error_code,
            rr.created_at,
            rr.finished_at
        FROM runtime_runs rr
        JOIN runtime_conversations r
          ON r.id=rr.conversation_id
         AND r.tenant_id=rr.tenant_id
         AND r.business_id=rr.business_id
         AND r.workspace_id=rr.workspace_id
        JOIN service_application_conversations c
          ON c.metadata->>'runtime_conversation_id'=r.id::text
         AND c.tenant_id=r.tenant_id
         AND c.business_id=r.business_id
         AND c.workspace_id=r.workspace_id
         AND c.kind='customer'
        JOIN channels ch
          ON ch.id=c.channel_id
         AND ch.tenant_id=c.tenant_id
         AND ch.business_id=c.business_id
         AND ch.workspace_id=c.workspace_id
        JOIN service_applications a
          ON a.id=c.application_id
         AND a.tenant_id=c.tenant_id
         AND a.business_id=c.business_id
         AND a.workspace_id=c.workspace_id
        JOIN LATERAL (
            SELECT bm.id
            FROM service_application_messages bm
            JOIN conversation_messages rm ON rm.id=bm.runtime_message_id
            WHERE bm.conversation_id=c.id
              AND bm.role='customer'
              AND rm.run_id=rr.id
              AND rm.role='user'
            ORDER BY rm.seq
            LIMIT 1
        ) customer_message ON TRUE
        LEFT JOIN LATERAL (
            SELECT bm.id
            FROM service_application_messages bm
            JOIN conversation_messages rm ON rm.id=bm.runtime_message_id
            WHERE bm.conversation_id=c.id
              AND bm.role='assistant'
              AND rm.run_id=rr.id
              AND rm.role='assistant'
            ORDER BY rm.seq DESC
            LIMIT 1
        ) assistant_message ON TRUE
        WHERE c.created_by='migration:0059'
          AND COALESCE(r.agent_id, a.agent_id) IS NOT NULL
          AND COALESCE(r.agent_version, a.agent_version) > 0
        ON CONFLICT DO NOTHING
        """
    )


def downgrade():
    op.execute("DROP TABLE IF EXISTS service_application_turns")
    op.execute("DROP TABLE IF EXISTS service_application_messages")
    op.execute("DROP TABLE IF EXISTS service_application_conversations")
