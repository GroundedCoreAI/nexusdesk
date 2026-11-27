"""Store Skill packages as immutable archives addressed by digest.

A package is deliberately kept out of ``skills``. The archive is an artefact:
it never changes once written, it is large, and it lives in object storage
while the Skill row is a small mutable record in Postgres. Splitting them means
a draft edit never rewrites bytes, and a future publish can pin one package row
per version without copying anything.

``skills.draft_package_id`` is the working attachment; ``skill_versions.
package_id`` is the frozen one. Both are nullable so declarative Skills keep
working exactly as before -- absence of a package is a valid state, not a
missing value.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0078_skill_packages"
down_revision = "0077_skill_classification"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "skill_packages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("business_id", sa.Text(), nullable=False),
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("skill_id", sa.Uuid(), nullable=False),
        sa.Column("s3_bucket", sa.Text(), nullable=False),
        sa.Column("s3_key", sa.Text(), nullable=False),
        sa.Column("digest", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("file_count", sa.Integer(), nullable=False),
        sa.Column("manifest", postgresql.JSONB(), nullable=False),
        sa.Column("entrypoint", sa.Text(), nullable=True),
        sa.Column("has_scripts", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "digest ~ '^sha256:[a-f0-9]{64}$'",
            name="skill_packages_digest",
        ),
        sa.CheckConstraint("size_bytes > 0", name="skill_packages_size_positive"),
        sa.CheckConstraint("file_count > 0", name="skill_packages_file_count_positive"),
        sa.CheckConstraint(
            "entrypoint IS NULL OR char_length(entrypoint) <= 500",
            name="skill_packages_entrypoint_length",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "business_id", "workspace_id", "skill_id"],
            ["skills.tenant_id", "skills.business_id", "skills.workspace_id", "skills.id"],
            name="skill_packages_skill_fk",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "skill_packages_skill",
        "skill_packages",
        ["tenant_id", "business_id", "workspace_id", "skill_id", "created_at"],
        postgresql_ops={"created_at": "DESC"},
    )
    op.create_index(
        "skill_packages_digest",
        "skill_packages",
        ["tenant_id", "business_id", "workspace_id", "digest"],
    )

    op.add_column("skills", sa.Column("draft_package_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "skills_draft_package_fk",
        "skills",
        "skill_packages",
        ["draft_package_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column("skill_versions", sa.Column("package_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "skill_versions_package_fk",
        "skill_versions",
        "skill_packages",
        ["package_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("skill_versions_package_fk", "skill_versions", type_="foreignkey")
    op.drop_column("skill_versions", "package_id")
    op.drop_constraint("skills_draft_package_fk", "skills", type_="foreignkey")
    op.drop_column("skills", "draft_package_id")
    op.drop_index("skill_packages_digest", table_name="skill_packages")
    op.drop_index("skill_packages_skill", table_name="skill_packages")
    op.drop_table("skill_packages")
