"""Clean-break service application v2 data and configuration foundation.

This migration intentionally does not migrate v1 scenario/provider data. The
platform has not shipped a production data contract for v1, so the upgrade
drops the old empty/sample tables and rebuilds service applications around one
Agent binding, application-owned skills/connections, immutable releases and
application-scoped traces.

``downgrade`` recreates the pre-0058 table shells but cannot recover deleted
data.
"""

from alembic import op

revision = "0058_service_application_v2"
down_revision = "0057_industry_pack_runtime"
branch_labels = None
depends_on = None


def upgrade():
    # Drop the entire v1 service-scenario/provider/industry installation chain.
    op.execute("DROP TABLE IF EXISTS service_scenario_traces")
    op.execute("DROP TABLE IF EXISTS service_scenario_versions")
    op.execute("DROP TABLE IF EXISTS service_scenarios")
    op.execute("DROP TABLE IF EXISTS industry_pack_upgrades")
    op.execute("DROP TABLE IF EXISTS industry_pack_installations")
    op.execute("DROP TABLE IF EXISTS service_provider_registry")
    op.execute("DROP TABLE IF EXISTS service_application_versions")
    op.execute("DROP TABLE IF EXISTS service_applications")

    op.execute(
        """
        CREATE TABLE service_applications (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id TEXT NOT NULL,
            business_id TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            application_key TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            agent_id UUID NOT NULL REFERENCES agents(id),
            agent_version INTEGER NOT NULL CHECK (agent_version > 0),
            origin TEXT NOT NULL DEFAULT 'user'
                CHECK (origin IN ('user', 'example')),
            template_key TEXT NULL,
            template_version TEXT NULL,
            immutable BOOLEAN NOT NULL DEFAULT false,
            status TEXT NOT NULL DEFAULT 'draft'
                CHECK (status IN ('draft', 'review', 'published', 'offline')),
            draft JSONB NOT NULL,
            draft_revision INTEGER NOT NULL DEFAULT 1 CHECK (draft_revision > 0),
            published_version INTEGER NULL CHECK (published_version > 0),
            archived BOOLEAN NOT NULL DEFAULT false,
            created_by TEXT NOT NULL,
            updated_by TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT service_applications_identity_unique
                UNIQUE (tenant_id, business_id, workspace_id, application_key),
            CONSTRAINT service_applications_scope_id_unique
                UNIQUE (tenant_id, business_id, workspace_id, id),
            CONSTRAINT service_applications_origin_immutability
                CHECK (
                    (origin = 'example' AND immutable = true)
                    OR (origin = 'user' AND immutable = false)
                )
        )
        """
    )
    op.execute(
        """
        CREATE INDEX service_applications_catalog
        ON service_applications (
            tenant_id,
            business_id,
            workspace_id,
            archived,
            origin,
            status,
            updated_at DESC
        )
        """
    )

    op.execute(
        """
        CREATE TABLE service_application_skills (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id TEXT NOT NULL,
            business_id TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            application_id UUID NOT NULL,
            skill_key TEXT NOT NULL,
            type TEXT NOT NULL
                CHECK (type IN ('knowledge', 'query', 'action', 'handoff')),
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            enabled BOOLEAN NOT NULL DEFAULT true,
            connection_id UUID NULL,
            config JSONB NOT NULL DEFAULT '{}'::jsonb,
            revision INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0),
            created_by TEXT NOT NULL,
            updated_by TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT service_application_skills_identity_unique
                UNIQUE (
                    tenant_id,
                    business_id,
                    workspace_id,
                    application_id,
                    skill_key
                ),
            CONSTRAINT service_application_skills_application_fk
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
        CREATE INDEX service_application_skills_application
        ON service_application_skills (
            tenant_id,
            business_id,
            workspace_id,
            application_id,
            enabled,
            skill_key
        )
        """
    )

    op.execute(
        """
        CREATE TABLE service_application_connections (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id TEXT NOT NULL,
            business_id TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            application_id UUID NOT NULL,
            connection_key TEXT NOT NULL,
            name TEXT NOT NULL,
            executor_kind TEXT NOT NULL
                CHECK (executor_kind IN ('http', 'internal', 'human_queue')),
            endpoint TEXT NULL,
            method TEXT NOT NULL DEFAULT 'GET'
                CHECK (method IN ('GET', 'POST')),
            public_headers JSONB NOT NULL DEFAULT '{}'::jsonb,
            auth_kind TEXT NOT NULL DEFAULT 'none'
                CHECK (auth_kind IN ('none', 'bearer', 'api_key', 'custom')),
            timeout_seconds INTEGER NOT NULL DEFAULT 10
                CHECK (timeout_seconds BETWEEN 1 AND 60),
            max_response_bytes INTEGER NOT NULL DEFAULT 16000
                CHECK (max_response_bytes BETWEEN 128 AND 100000),
            config JSONB NOT NULL DEFAULT '{}'::jsonb,
            revision INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0),
            created_by TEXT NOT NULL,
            updated_by TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT service_application_connections_identity_unique
                UNIQUE (
                    tenant_id,
                    business_id,
                    workspace_id,
                    application_id,
                    connection_key
                ),
            CONSTRAINT service_application_connections_scope_id_unique
                UNIQUE (
                    tenant_id,
                    business_id,
                    workspace_id,
                    id
                ),
            CONSTRAINT service_application_connections_application_fk
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
        CREATE INDEX service_application_connections_application
        ON service_application_connections (
            tenant_id,
            business_id,
            workspace_id,
            application_id,
            connection_key
        )
        """
    )

    op.execute(
        """
        CREATE TABLE service_application_connection_credentials (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id TEXT NOT NULL,
            business_id TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            connection_id UUID NOT NULL UNIQUE,
            encrypted_secret TEXT NOT NULL,
            key_version INTEGER NOT NULL DEFAULT 1 CHECK (key_version > 0),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT service_application_connection_credentials_connection_fk
                FOREIGN KEY (
                    tenant_id,
                    business_id,
                    workspace_id,
                    connection_id
                )
                REFERENCES service_application_connections (
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
        CREATE INDEX service_application_connection_credentials_scope
        ON service_application_connection_credentials (
            tenant_id,
            business_id,
            workspace_id,
            connection_id
        )
        """
    )

    op.execute(
        """
        CREATE TABLE service_application_versions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id TEXT NOT NULL,
            business_id TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            application_id UUID NOT NULL,
            version INTEGER NOT NULL CHECK (version > 0),
            schema_version TEXT NOT NULL CHECK (schema_version = 'v2'),
            config JSONB NOT NULL,
            config_digest TEXT NOT NULL
                CHECK (config_digest ~ '^sha256:[a-f0-9]{64}$'),
            source_version INTEGER NULL CHECK (source_version > 0),
            created_by TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT service_application_versions_scope_version_unique
                UNIQUE (
                    tenant_id,
                    business_id,
                    workspace_id,
                    application_id,
                    version
                ),
            CONSTRAINT service_application_versions_application_fk
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
        CREATE INDEX service_application_versions_application
        ON service_application_versions (
            tenant_id,
            business_id,
            workspace_id,
            application_id,
            version DESC
        )
        """
    )

    op.execute(
        """
        CREATE TABLE service_application_traces (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id TEXT NOT NULL,
            business_id TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            application_id UUID NOT NULL,
            application_version INTEGER NOT NULL CHECK (application_version > 0),
            conversation_id UUID NULL REFERENCES runtime_conversations(id) ON DELETE SET NULL,
            run_id UUID NULL REFERENCES runtime_runs(id) ON DELETE SET NULL,
            agent_id UUID NOT NULL,
            agent_version INTEGER NOT NULL CHECK (agent_version > 0),
            trace JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT service_application_traces_application_fk
                FOREIGN KEY (
                    tenant_id,
                    business_id,
                    workspace_id,
                    application_id
                )
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
        CREATE INDEX service_application_traces_application
        ON service_application_traces (
            tenant_id,
            business_id,
            workspace_id,
            application_id,
            application_version,
            created_at DESC
        )
        """
    )
    op.execute(
        """
        CREATE INDEX service_application_traces_conversation
        ON service_application_traces (
            tenant_id,
            business_id,
            workspace_id,
            conversation_id,
            created_at DESC
        )
        """
    )

    # Old channels cannot be mapped to an application/version without guessing.
    # The product is pre-release, so channel bindings and their outbox rows are
    # deliberately discarded with the old application configuration.
    op.execute("DELETE FROM channel_deliveries")
    op.execute("DELETE FROM channel_inbound_events")
    op.execute("DELETE FROM channel_conversations")
    op.execute("DELETE FROM channels")

    op.execute(
        """
        ALTER TABLE channels
        ADD COLUMN application_id UUID NOT NULL,
        ADD COLUMN application_version INTEGER NOT NULL CHECK (application_version > 0)
        """
    )
    op.execute(
        """
        ALTER TABLE channels
        ADD CONSTRAINT channels_application_fk
        FOREIGN KEY (tenant_id, business_id, workspace_id, application_id)
        REFERENCES service_applications (tenant_id, business_id, workspace_id, id)
        ON DELETE RESTRICT
        """
    )
    op.execute(
        """
        ALTER TABLE channels
        ADD CONSTRAINT channels_application_version_fk
        FOREIGN KEY (
            tenant_id,
            business_id,
            workspace_id,
            application_id,
            application_version
        )
        REFERENCES service_application_versions (
            tenant_id,
            business_id,
            workspace_id,
            application_id,
            version
        )
        ON DELETE RESTRICT
        """
    )
    op.execute(
        """
        ALTER TABLE channels
        DROP CONSTRAINT channels_agent_id_fkey,
        DROP COLUMN agent_id
        """
    )
    op.execute(
        """
        CREATE INDEX channels_application
        ON channels (
            tenant_id,
            business_id,
            workspace_id,
            application_id,
            application_version
        )
        """
    )

    op.execute(
        """
        ALTER TABLE channel_inbound_events
        ADD COLUMN application_id UUID NOT NULL,
        ADD COLUMN application_version INTEGER NOT NULL
            CHECK (application_version > 0)
        """
    )
    op.execute(
        """
        CREATE INDEX channel_inbound_events_application
        ON channel_inbound_events (
            application_id,
            application_version,
            created_at DESC
        )
        """
    )

    op.execute(
        """
        ALTER TABLE runtime_conversations
        ADD COLUMN application_id UUID NULL,
        ADD COLUMN application_version INTEGER NULL
            CHECK (application_version > 0),
        ADD COLUMN agent_version INTEGER NULL CHECK (agent_version > 0)
        """
    )
    op.execute(
        """
        ALTER TABLE runtime_conversations
        ADD CONSTRAINT runtime_conversations_application_fk
        FOREIGN KEY (tenant_id, business_id, workspace_id, application_id)
        REFERENCES service_applications (tenant_id, business_id, workspace_id, id)
                ON DELETE SET NULL (application_id)
        """
    )
    op.execute(
        """
        CREATE INDEX runtime_conversations_application
        ON runtime_conversations (
            tenant_id,
            business_id,
            workspace_id,
            application_id,
            application_version
        )
        """
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS runtime_conversations_application")
    op.execute(
        "ALTER TABLE runtime_conversations DROP CONSTRAINT IF EXISTS "
        "runtime_conversations_application_fk"
    )
    op.execute(
        """
        ALTER TABLE runtime_conversations
        DROP COLUMN IF EXISTS agent_version,
        DROP COLUMN IF EXISTS application_version,
        DROP COLUMN IF EXISTS application_id
        """
    )
    op.execute("DROP INDEX IF EXISTS channel_inbound_events_application")
    op.execute(
        """
        ALTER TABLE channel_inbound_events
        DROP COLUMN IF EXISTS application_version,
        DROP COLUMN IF EXISTS application_id
        """
    )
    op.execute("DROP INDEX IF EXISTS channels_application")
    op.execute("DELETE FROM channel_deliveries")
    op.execute("DELETE FROM channel_inbound_events")
    op.execute("DELETE FROM channel_conversations")
    op.execute("DELETE FROM channels")
    op.execute("ALTER TABLE channels DROP CONSTRAINT IF EXISTS channels_application_version_fk")
    op.execute("ALTER TABLE channels DROP CONSTRAINT IF EXISTS channels_application_fk")
    op.execute(
        """
        ALTER TABLE channels
        ADD COLUMN agent_id UUID NOT NULL REFERENCES agents(id),
        DROP COLUMN application_version,
        DROP COLUMN application_id
        """
    )

    op.execute("DROP INDEX IF EXISTS service_application_traces_conversation")
    op.execute("DROP INDEX IF EXISTS service_application_traces_application")
    op.execute("DROP TABLE IF EXISTS service_application_traces")
    op.execute("DROP INDEX IF EXISTS service_application_versions_application")
    op.execute("DROP TABLE IF EXISTS service_application_versions")
    op.execute("DROP INDEX IF EXISTS service_application_connection_credentials_scope")
    op.execute("DROP TABLE IF EXISTS service_application_connection_credentials")
    op.execute("DROP INDEX IF EXISTS service_application_connections_application")
    op.execute("DROP TABLE IF EXISTS service_application_connections")
    op.execute("DROP INDEX IF EXISTS service_application_skills_application")
    op.execute("DROP TABLE IF EXISTS service_application_skills")
    op.execute("DROP INDEX IF EXISTS service_applications_catalog")
    op.execute("DROP TABLE IF EXISTS service_applications")

    # Restore the pre-0058 empty table shells for a reversible development
    # downgrade. v1 sample data is intentionally not restored.
    op.execute(
        """
        CREATE TABLE service_scenarios (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id TEXT NOT NULL,
            business_id TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            scenario_key TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            domain TEXT NOT NULL,
            template TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft',
            draft JSONB NOT NULL,
            draft_revision INTEGER NOT NULL DEFAULT 1,
            published_version INTEGER NULL,
            created_by TEXT NOT NULL,
            updated_by TEXT NOT NULL,
            archived BOOLEAN NOT NULL DEFAULT false,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, business_id, workspace_id, scenario_key),
            UNIQUE (tenant_id, business_id, workspace_id, id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE service_scenario_versions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id TEXT NOT NULL,
            business_id TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            scenario_id UUID NOT NULL,
            version INTEGER NOT NULL,
            config JSONB NOT NULL,
            source_version INTEGER NULL,
            created_by TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, business_id, workspace_id, scenario_id, version),
            FOREIGN KEY (tenant_id, business_id, workspace_id, scenario_id)
                REFERENCES service_scenarios (tenant_id, business_id, workspace_id, id)
                ON DELETE CASCADE
        )
        """
    )
    op.execute(
        """
        CREATE TABLE service_scenario_traces (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id TEXT NOT NULL,
            business_id TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            scenario_id UUID NULL REFERENCES service_scenarios(id) ON DELETE SET NULL,
            scenario_key TEXT NOT NULL,
            scenario_version INTEGER NULL,
            simulation BOOLEAN NOT NULL DEFAULT true,
            entry TEXT NOT NULL,
            message_length INTEGER NOT NULL,
            message_excerpt TEXT NOT NULL DEFAULT '',
            object_ref JSONB NOT NULL DEFAULT '{}'::jsonb,
            facts JSONB NOT NULL DEFAULT '[]'::jsonb,
            decisions JSONB NOT NULL DEFAULT '[]'::jsonb,
            handler_type TEXT NULL,
            outcome TEXT NOT NULL,
            reason_code TEXT NOT NULL,
            result_summary TEXT NOT NULL DEFAULT '',
            trace JSONB NOT NULL,
            created_by TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            conversation_id UUID NULL REFERENCES runtime_conversations(id) ON DELETE SET NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE service_provider_registry (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id TEXT NOT NULL,
            business_id TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            provider_key TEXT NOT NULL,
            kind TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            enabled BOOLEAN NOT NULL DEFAULT false,
            config JSONB NOT NULL DEFAULT '{}'::jsonb,
            source TEXT NOT NULL DEFAULT 'manual',
            source_ref TEXT NULL,
            revision INTEGER NOT NULL DEFAULT 1,
            created_by TEXT NOT NULL,
            updated_by TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, business_id, workspace_id, kind, provider_key)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE industry_pack_installations (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id TEXT NOT NULL,
            business_id TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            pack_key TEXT NOT NULL,
            pack_version TEXT NOT NULL,
            pack_digest TEXT NOT NULL,
            maturity TEXT NOT NULL,
            application_key TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'installed',
            scenario_template_versions JSONB NOT NULL DEFAULT '{}'::jsonb,
            scenario_template_digests JSONB NOT NULL DEFAULT '{}'::jsonb,
            installed_scenarios JSONB NOT NULL DEFAULT '{}'::jsonb,
            source_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
            revision INTEGER NOT NULL DEFAULT 1,
            installed_by TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, business_id, workspace_id, pack_key, application_key),
            UNIQUE (tenant_id, business_id, workspace_id, id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE industry_pack_upgrades (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id TEXT NOT NULL,
            business_id TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            installation_id UUID NOT NULL,
            from_version TEXT NOT NULL,
            to_version TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'preview',
            base_digest TEXT NOT NULL,
            target_digest TEXT NOT NULL,
            plan JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_by TEXT NOT NULL,
            applied_by TEXT NULL,
            applied_at TIMESTAMPTZ NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            FOREIGN KEY (tenant_id, business_id, workspace_id, installation_id)
                REFERENCES industry_pack_installations (
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
        CREATE TABLE service_applications (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id TEXT NOT NULL,
            business_id TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            application_key TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'draft',
            draft JSONB NOT NULL,
            draft_revision INTEGER NOT NULL DEFAULT 1,
            published_version INTEGER NULL,
            created_by TEXT NOT NULL,
            updated_by TEXT NOT NULL,
            archived BOOLEAN NOT NULL DEFAULT false,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, business_id, workspace_id, application_key),
            UNIQUE (tenant_id, business_id, workspace_id, id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE service_application_versions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id TEXT NOT NULL,
            business_id TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            application_id UUID NOT NULL,
            version INTEGER NOT NULL,
            config JSONB NOT NULL,
            source_version INTEGER NULL,
            created_by TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, business_id, workspace_id, application_id, version),
            FOREIGN KEY (tenant_id, business_id, workspace_id, application_id)
                REFERENCES service_applications (tenant_id, business_id, workspace_id, id)
                ON DELETE CASCADE
        )
        """
    )
