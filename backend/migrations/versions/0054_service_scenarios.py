"""Service scenario configurations, immutable versions, and execution traces."""

from alembic import op

revision = "0054_service_scenarios"
down_revision = "0053_routing_decisions"
branch_labels = None
depends_on = None


def upgrade():
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
            CONSTRAINT service_scenarios_key_unique
                UNIQUE (tenant_id, business_id, workspace_id, scenario_key),
            CONSTRAINT service_scenarios_scope_id_unique
                UNIQUE (tenant_id, business_id, workspace_id, id),
            CONSTRAINT service_scenarios_status_known
                CHECK (status IN ('draft', 'review', 'published', 'offline')),
            CONSTRAINT service_scenarios_draft_revision_positive
                CHECK (draft_revision > 0),
            CONSTRAINT service_scenarios_published_version_positive
                CHECK (published_version IS NULL OR published_version > 0)
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
            CONSTRAINT service_scenario_versions_scope_version_unique
                UNIQUE (tenant_id, business_id, workspace_id, scenario_id, version),
            CONSTRAINT service_scenario_versions_scenario_fk
                FOREIGN KEY (tenant_id, business_id, workspace_id, scenario_id)
                REFERENCES service_scenarios (tenant_id, business_id, workspace_id, id)
                ON DELETE CASCADE,
            CONSTRAINT service_scenario_versions_version_positive
                CHECK (version > 0),
            CONSTRAINT service_scenario_versions_source_version_positive
                CHECK (source_version IS NULL OR source_version > 0)
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
            scenario_id UUID NULL,
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
            CONSTRAINT service_scenario_traces_scenario_fk
                FOREIGN KEY (scenario_id)
                REFERENCES service_scenarios (id)
                ON DELETE SET NULL,
            CONSTRAINT service_scenario_traces_message_length_non_negative
                CHECK (message_length >= 0),
            CONSTRAINT service_scenario_traces_handler_type_known
                CHECK (
                    handler_type IS NULL
                    OR handler_type IN (
                        'direct',
                        'knowledge',
                        'query',
                        'action',
                        'agent',
                        'human',
                        'tracking'
                    )
                ),
            CONSTRAINT service_scenario_traces_outcome_known
                CHECK (
                    outcome IN (
                        'succeeded',
                        'failed',
                        'needs_input',
                        'denied',
                        'simulated',
                        'delegated'
                    )
                )
        )
        """
    )
    op.execute(
        """
        CREATE INDEX service_scenarios_scope_status_updated
        ON service_scenarios (
            tenant_id,
            business_id,
            workspace_id,
            status,
            updated_at DESC
        )
        """
    )
    op.execute(
        """
        CREATE INDEX service_scenario_versions_scope_scenario
        ON service_scenario_versions (
            tenant_id,
            business_id,
            workspace_id,
            scenario_id,
            version DESC
        )
        """
    )
    op.execute(
        """
        CREATE INDEX service_scenario_traces_scope_scenario
        ON service_scenario_traces (
            tenant_id,
            business_id,
            workspace_id,
            scenario_id,
            created_at DESC
        )
        """
    )
    op.execute(
        """
        CREATE INDEX service_scenario_traces_scope_handler
        ON service_scenario_traces (
            tenant_id,
            business_id,
            workspace_id,
            handler_type,
            created_at DESC
        )
        """
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS service_scenario_traces_scope_handler")
    op.execute("DROP INDEX IF EXISTS service_scenario_traces_scope_scenario")
    op.execute("DROP INDEX IF EXISTS service_scenario_versions_scope_scenario")
    op.execute("DROP INDEX IF EXISTS service_scenarios_scope_status_updated")
    op.execute("DROP TABLE IF EXISTS service_scenario_traces")
    op.execute("DROP TABLE IF EXISTS service_scenario_versions")
    op.execute("DROP TABLE IF EXISTS service_scenarios")
