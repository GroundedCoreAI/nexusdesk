"""Service applications compose scenarios and execution capabilities."""

from alembic import op

revision = "0055_service_applications"
down_revision = "0054_service_scenarios"
branch_labels = None
depends_on = None


def upgrade():
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
            CONSTRAINT service_applications_key_unique
                UNIQUE (tenant_id, business_id, workspace_id, application_key),
            CONSTRAINT service_applications_scope_id_unique
                UNIQUE (tenant_id, business_id, workspace_id, id),
            CONSTRAINT service_applications_status_known
                CHECK (status IN ('draft', 'review', 'published', 'offline')),
            CONSTRAINT service_applications_draft_revision_positive
                CHECK (draft_revision > 0),
            CONSTRAINT service_applications_published_version_positive
                CHECK (published_version IS NULL OR published_version > 0)
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
            CONSTRAINT service_application_versions_scope_version_unique
                UNIQUE (tenant_id, business_id, workspace_id, application_id, version),
            CONSTRAINT service_application_versions_application_fk
                FOREIGN KEY (tenant_id, business_id, workspace_id, application_id)
                REFERENCES service_applications (tenant_id, business_id, workspace_id, id)
                ON DELETE CASCADE,
            CONSTRAINT service_application_versions_version_positive
                CHECK (version > 0),
            CONSTRAINT service_application_versions_source_version_positive
                CHECK (source_version IS NULL OR source_version > 0)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX service_applications_scope_status_updated
        ON service_applications (
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
        CREATE INDEX service_application_versions_scope_application
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
        CREATE INDEX service_scenario_traces_application
        ON service_scenario_traces (
            (trace->'application'->>'key'),
            created_at DESC
        )
        """
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS service_scenario_traces_application")
    op.execute("DROP INDEX IF EXISTS service_application_versions_scope_application")
    op.execute("DROP INDEX IF EXISTS service_applications_scope_status_updated")
    op.execute("DROP TABLE IF EXISTS service_application_versions")
    op.execute("DROP TABLE IF EXISTS service_applications")
