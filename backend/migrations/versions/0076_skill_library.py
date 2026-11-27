"""Add the global Skill library, immutable versions, and test evidence."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0076_skill_library"
down_revision = "0075_gateway_allowed_hosts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "skills",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("business_id", sa.Text(), nullable=False),
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("skill_key", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column(
            "tags",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column("visibility", sa.Text(), nullable=False, server_default="workspace"),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column(
            "definition_schema_version",
            sa.Text(),
            nullable=False,
            server_default="v1",
        ),
        sa.Column("draft_definition", postgresql.JSONB(), nullable=False),
        sa.Column("draft_revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("published_version", sa.Integer(), nullable=True),
        sa.Column("published_revision", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("updated_by", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "skill_key ~ '^[a-z][a-z0-9_-]{0,63}$'",
            name="skills_skill_key_format",
        ),
        sa.CheckConstraint(
            "char_length(name) BETWEEN 1 AND 100",
            name="skills_name_length",
        ),
        sa.CheckConstraint(
            "char_length(description) <= 1000",
            name="skills_description_length",
        ),
        sa.CheckConstraint(
            "category IN ('service', 'finance', 'sales', 'general')",
            name="skills_category",
        ),
        sa.CheckConstraint("visibility = 'workspace'", name="skills_visibility"),
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'archived')",
            name="skills_status",
        ),
        sa.CheckConstraint(
            "definition_schema_version = 'v1'",
            name="skills_definition_schema_version",
        ),
        sa.CheckConstraint("draft_revision > 0", name="skills_draft_revision_positive"),
        sa.CheckConstraint(
            "published_version IS NULL OR published_version > 0",
            name="skills_published_version_positive",
        ),
        sa.CheckConstraint(
            "published_revision IS NULL OR published_revision > 0",
            name="skills_published_revision_positive",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "business_id",
            "workspace_id",
            "skill_key",
            name="skills_identity_unique",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "business_id",
            "workspace_id",
            "id",
            name="skills_scope_id_unique",
        ),
    )
    op.create_index(
        "skills_catalog",
        "skills",
        ["tenant_id", "business_id", "workspace_id", "status", "category", "updated_at"],
        postgresql_ops={"updated_at": "DESC"},
    )

    op.create_table(
        "skill_test_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("business_id", sa.Text(), nullable=False),
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("skill_id", sa.Uuid(), nullable=False),
        sa.Column("draft_revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("execution_kind", sa.Text(), nullable=False),
        sa.Column("input", postgresql.JSONB(), nullable=False),
        sa.Column("input_summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("output", postgresql.JSONB(), nullable=True),
        sa.Column(
            "diagnostics",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("reason_code", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("client_request_id", sa.Text(), nullable=True),
        sa.Column("executed_by", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("draft_revision > 0", name="skill_test_runs_revision_positive"),
        sa.CheckConstraint(
            "status IN ('passed', 'failed', 'error', 'blocked')",
            name="skill_test_runs_status",
        ),
        sa.CheckConstraint(
            "execution_kind IN ('live', 'contract')",
            name="skill_test_runs_execution_kind",
        ),
        sa.CheckConstraint(
            "char_length(input_summary) <= 500",
            name="skill_test_runs_input_summary_length",
        ),
        sa.CheckConstraint(
            "reason_code IS NULL OR char_length(reason_code) <= 200",
            name="skill_test_runs_reason_code_length",
        ),
        sa.CheckConstraint("duration_ms >= 0", name="skill_test_runs_duration"),
        sa.CheckConstraint(
            "client_request_id IS NULL OR char_length(client_request_id) <= 128",
            name="skill_test_runs_client_request_id_length",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "business_id", "workspace_id", "skill_id"],
            ["skills.tenant_id", "skills.business_id", "skills.workspace_id", "skills.id"],
            name="skill_test_runs_skill_fk",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "business_id",
            "workspace_id",
            "skill_id",
            "id",
            name="skill_test_runs_scope_run_unique",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "business_id",
            "workspace_id",
            "skill_id",
            "client_request_id",
            name="skill_test_runs_request_unique",
        ),
    )
    op.create_index(
        "skill_test_runs_revision",
        "skill_test_runs",
        [
            "tenant_id",
            "business_id",
            "workspace_id",
            "skill_id",
            "draft_revision",
            "status",
            "created_at",
        ],
        postgresql_ops={"created_at": "DESC"},
    )

    op.create_table(
        "skill_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("business_id", sa.Text(), nullable=False),
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("skill_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("semver", sa.Text(), nullable=False),
        sa.Column("release_kind", sa.Text(), nullable=False),
        sa.Column(
            "definition_schema_version",
            sa.Text(),
            nullable=False,
            server_default="v1",
        ),
        sa.Column("definition", postgresql.JSONB(), nullable=False),
        sa.Column("definition_digest", sa.Text(), nullable=False),
        sa.Column("release_notes", sa.Text(), nullable=False),
        sa.Column("source_draft_revision", sa.Integer(), nullable=False),
        sa.Column("test_run_id", sa.Uuid(), nullable=True),
        sa.Column("rollback_from", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("version > 0", name="skill_versions_version_positive"),
        sa.CheckConstraint(
            "semver ~ '^[0-9]+\\.[0-9]+\\.[0-9]+$'",
            name="skill_versions_semver",
        ),
        sa.CheckConstraint(
            "release_kind IN ('initial', 'major', 'minor', 'patch', 'rollback')",
            name="skill_versions_release_kind",
        ),
        sa.CheckConstraint(
            "definition_schema_version = 'v1'",
            name="skill_versions_definition_schema_version",
        ),
        sa.CheckConstraint(
            "definition_digest ~ '^sha256:[a-f0-9]{64}$'",
            name="skill_versions_definition_digest",
        ),
        sa.CheckConstraint(
            "char_length(release_notes) BETWEEN 1 AND 2000",
            name="skill_versions_release_notes_length",
        ),
        sa.CheckConstraint(
            "source_draft_revision > 0",
            name="skill_versions_source_revision_positive",
        ),
        sa.CheckConstraint(
            "rollback_from IS NULL OR rollback_from > 0",
            name="skill_versions_rollback_from_positive",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "business_id", "workspace_id", "skill_id"],
            ["skills.tenant_id", "skills.business_id", "skills.workspace_id", "skills.id"],
            name="skill_versions_skill_fk",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "business_id", "workspace_id", "skill_id", "test_run_id"],
            [
                "skill_test_runs.tenant_id",
                "skill_test_runs.business_id",
                "skill_test_runs.workspace_id",
                "skill_test_runs.skill_id",
                "skill_test_runs.id",
            ],
            name="skill_versions_test_run_fk",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "business_id", "workspace_id", "skill_id", "rollback_from"],
            [
                "skill_versions.tenant_id",
                "skill_versions.business_id",
                "skill_versions.workspace_id",
                "skill_versions.skill_id",
                "skill_versions.version",
            ],
            name="skill_versions_rollback_fk",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "business_id",
            "workspace_id",
            "skill_id",
            "version",
            name="skill_versions_scope_version_unique",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "business_id",
            "workspace_id",
            "skill_id",
            "semver",
            name="skill_versions_scope_semver_unique",
        ),
    )
    op.create_index(
        "skill_versions_history",
        "skill_versions",
        ["tenant_id", "business_id", "workspace_id", "skill_id", "version"],
        postgresql_ops={"version": "DESC"},
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM skills)
             OR EXISTS (SELECT 1 FROM skill_test_runs)
             OR EXISTS (SELECT 1 FROM skill_versions) THEN
            RAISE EXCEPTION 'refusing to drop populated Skill library tables';
          END IF;
        END $$;
        """
    )
    op.drop_index("skill_versions_history", table_name="skill_versions")
    op.drop_table("skill_versions")
    op.drop_index("skill_test_runs_revision", table_name="skill_test_runs")
    op.drop_table("skill_test_runs")
    op.drop_index("skills_catalog", table_name="skills")
    op.drop_table("skills")
