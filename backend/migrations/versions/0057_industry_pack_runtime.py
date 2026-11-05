"""Tenant-scoped provider registry and industry-pack installation state."""

from alembic import op

revision = "0057_industry_pack_runtime"
down_revision = "0056_scenario_trace_conversation"
branch_labels = None
depends_on = None


def upgrade():
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
            CONSTRAINT service_provider_registry_identity_unique
                UNIQUE (
                    tenant_id,
                    business_id,
                    workspace_id,
                    kind,
                    provider_key
                ),
            CONSTRAINT service_provider_registry_kind_known
                CHECK (kind IN ('object', 'tool', 'human_queue')),
            CONSTRAINT service_provider_registry_revision_positive
                CHECK (revision > 0)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX service_provider_registry_scope_kind_enabled
        ON service_provider_registry (
            tenant_id,
            business_id,
            workspace_id,
            kind,
            enabled
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
            CONSTRAINT industry_pack_installations_identity_unique
                UNIQUE (
                    tenant_id,
                    business_id,
                    workspace_id,
                    pack_key,
                    application_key
                ),
            CONSTRAINT industry_pack_installations_scope_id_unique
                UNIQUE (
                    tenant_id,
                    business_id,
                    workspace_id,
                    id
                ),
            CONSTRAINT industry_pack_installations_status_known
                CHECK (status IN ('installed', 'upgrading', 'conflicted', 'blocked')),
            CONSTRAINT industry_pack_installations_maturity_known
                CHECK (maturity IN ('alpha', 'beta', 'ga')),
            CONSTRAINT industry_pack_installations_revision_positive
                CHECK (revision > 0)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX industry_pack_installations_scope_pack
        ON industry_pack_installations (
            tenant_id,
            business_id,
            workspace_id,
            pack_key,
            created_at DESC
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
            CONSTRAINT industry_pack_upgrades_installation_fk
                FOREIGN KEY (
                    tenant_id,
                    business_id,
                    workspace_id,
                    installation_id
                )
                REFERENCES industry_pack_installations (
                    tenant_id,
                    business_id,
                    workspace_id,
                    id
                )
                ON DELETE CASCADE,
            CONSTRAINT industry_pack_upgrades_status_known
                CHECK (status IN ('preview', 'clean', 'conflicted', 'applied', 'failed'))
        )
        """
    )
    op.execute(
        """
        CREATE INDEX industry_pack_upgrades_scope_installation
        ON industry_pack_upgrades (
            tenant_id,
            business_id,
            workspace_id,
            installation_id,
            created_at DESC
        )
        """
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS industry_pack_upgrades_scope_installation")
    op.execute("DROP TABLE IF EXISTS industry_pack_upgrades")
    op.execute("DROP INDEX IF EXISTS industry_pack_installations_scope_pack")
    op.execute("DROP TABLE IF EXISTS industry_pack_installations")
    op.execute("DROP INDEX IF EXISTS service_provider_registry_scope_kind_enabled")
    op.execute("DROP TABLE IF EXISTS service_provider_registry")
