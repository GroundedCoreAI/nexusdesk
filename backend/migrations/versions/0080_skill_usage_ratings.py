"""Record how often a Skill is used and how it is rated.

Both tables exist because the catalogue's headline numbers ("使用 12.5k 次",
"★4.8", "使用中 228") are facts about behaviour, not fields an author types
in. Keeping them as append-only facts rather than a counter column on
``skills`` means:

* the trend arrows ("↑12.5%") are a period-over-period query, not a value
  somebody has to remember to update;
* a bad import or a buggy run can be deleted without corrupting a counter;
* the same rows will feed the detail page's analytics tab later, which is
  why they are keyed by day and carry the success count as well.

``skill_usage_daily`` is aggregated per (skill, day) rather than per call: a
Skill that runs 100k times a day must not create 100k rows. Roll-up happens
in the writer, so a day's row is updated in place.
"""

import sqlalchemy as sa
from alembic import op

revision = "0080_skill_usage_ratings"
down_revision = "0079_skill_package_filename"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "skill_usage_daily",
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("business_id", sa.Text(), nullable=False),
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("skill_id", sa.Uuid(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("runs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("succeeded", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint(
            "tenant_id",
            "business_id",
            "workspace_id",
            "skill_id",
            "day",
            name="skill_usage_daily_pk",
        ),
        sa.CheckConstraint("runs >= 0", name="skill_usage_daily_runs_non_negative"),
        sa.CheckConstraint(
            "succeeded >= 0 AND succeeded <= runs",
            name="skill_usage_daily_succeeded_within_runs",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "business_id", "workspace_id", "skill_id"],
            ["skills.tenant_id", "skills.business_id", "skills.workspace_id", "skills.id"],
            name="skill_usage_daily_skill_fk",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "skill_usage_daily_day",
        "skill_usage_daily",
        ["tenant_id", "business_id", "workspace_id", "day"],
    )

    op.create_table(
        "skill_ratings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("business_id", sa.Text(), nullable=False),
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("skill_id", sa.Uuid(), nullable=False),
        sa.Column("rater", sa.Text(), nullable=False),
        sa.Column("score", sa.SmallInteger(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("score BETWEEN 1 AND 5", name="skill_ratings_score_range"),
        sa.CheckConstraint(
            "comment IS NULL OR char_length(comment) <= 1000",
            name="skill_ratings_comment_length",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "business_id", "workspace_id", "skill_id"],
            ["skills.tenant_id", "skills.business_id", "skills.workspace_id", "skills.id"],
            name="skill_ratings_skill_fk",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "business_id",
            "workspace_id",
            "skill_id",
            "rater",
            name="skill_ratings_one_per_rater",
        ),
    )
    op.create_index(
        "skill_ratings_skill",
        "skill_ratings",
        ["tenant_id", "business_id", "workspace_id", "skill_id", "created_at"],
        postgresql_ops={"created_at": "DESC"},
    )

    # The catalogue sorts by "latest" today; once usage exists, "most used"
    # becomes the default ordering for the popular rail.
    op.execute(
        "COMMENT ON TABLE skill_usage_daily IS "
        "'Daily roll-up of Skill invocations; feeds catalogue usage stats'"
    )


def downgrade() -> None:
    op.drop_index("skill_ratings_skill", table_name="skill_ratings")
    op.drop_table("skill_ratings")
    op.drop_index("skill_usage_daily_day", table_name="skill_usage_daily")
    op.drop_table("skill_usage_daily")
