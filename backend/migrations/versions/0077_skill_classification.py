"""Add the advisory Skill weight and risk labels.

Three columns, all additive and defaulted, so existing rows stay valid:

* ``weight_class`` - derived fact about the artefact (declarative / packaged /
  executable). Read only at the API surface.
* ``risk_level`` - the author-facing label. Seeded from the computed baseline
  and freely editable afterwards.
* ``data_scope`` - derived set of data planes the Skill touches.

The backfill below is a frozen copy of the baseline rules in
``skill_library.classification``. It intentionally only reproduces the type and
amount precedence: factor-level differences are recomputed on the next save, and
the API always reports the live computed value next to the stored label.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0077_skill_classification"
down_revision = "0076_skill_library"
branch_labels = None
depends_on = None

_BACKFILL_RISK = """
UPDATE skills
SET risk_level = CASE
    WHEN COALESCE((draft_definition->'runtime'->>'max_amount')::numeric, 0) >= 5000 THEN 'r3'
    WHEN draft_definition->>'type' = 'action' THEN 'r2'
    WHEN COALESCE((draft_definition->'runtime'->>'max_amount')::numeric, 0) > 0 THEN 'r2'
    WHEN draft_definition->>'type' IN ('query', 'handoff') THEN 'r1'
    WHEN jsonb_array_length(
        COALESCE(draft_definition->'dependencies'->'tool_names', '[]'::jsonb)
    ) > 0 THEN 'r1'
    WHEN jsonb_array_length(
        COALESCE(draft_definition->'dependencies'->'knowledge_base_ids', '[]'::jsonb)
    ) > 0 THEN 'r1'
    WHEN COALESCE(draft_definition->'dependencies'->>'handoff_queue', '') <> '' THEN 'r1'
    ELSE 'r0'
END
"""

_BACKFILL_SCOPE = """
UPDATE skills s
SET data_scope = COALESCE(
    (
        SELECT array_agg(scope ORDER BY scope)
        FROM (
            SELECT 'model' AS scope
            WHERE s.draft_definition->'dependencies'->>'model_profile_id' IS NOT NULL
            UNION ALL
            SELECT 'kb'
            WHERE jsonb_array_length(
                COALESCE(s.draft_definition->'dependencies'->'knowledge_base_ids', '[]'::jsonb)
            ) > 0
            UNION ALL
            SELECT 'tool'
            WHERE jsonb_array_length(
                COALESCE(s.draft_definition->'dependencies'->'tool_names', '[]'::jsonb)
            ) > 0
            UNION ALL
            SELECT 'handoff'
            WHERE COALESCE(s.draft_definition->'dependencies'->>'handoff_queue', '') <> ''
            UNION ALL
            SELECT 'money'
            WHERE COALESCE((s.draft_definition->'runtime'->>'max_amount')::numeric, 0) > 0
        ) AS derived
    ),
    '{}'::text[]
)
"""


def upgrade() -> None:
    op.add_column(
        "skills",
        sa.Column(
            "weight_class",
            sa.Text(),
            nullable=False,
            server_default="declarative",
        ),
    )
    op.add_column(
        "skills",
        sa.Column("risk_level", sa.Text(), nullable=False, server_default="r0"),
    )
    op.add_column(
        "skills",
        sa.Column(
            "data_scope",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
    )
    op.create_check_constraint(
        "skills_weight_class_ck",
        "skills",
        "weight_class IN ('declarative', 'packaged', 'executable')",
    )
    op.create_check_constraint(
        "skills_risk_level_ck",
        "skills",
        "risk_level IN ('r0', 'r1', 'r2', 'r3')",
    )
    op.create_index(
        "ix_skills_risk",
        "skills",
        ["tenant_id", "business_id", "workspace_id", "risk_level"],
    )
    op.execute(_BACKFILL_RISK)
    op.execute(_BACKFILL_SCOPE)


def downgrade() -> None:
    op.drop_index("ix_skills_risk", table_name="skills")
    op.drop_constraint("skills_risk_level_ck", "skills", type_="check")
    op.drop_constraint("skills_weight_class_ck", "skills", type_="check")
    op.drop_column("skills", "data_scope")
    op.drop_column("skills", "risk_level")
    op.drop_column("skills", "weight_class")
