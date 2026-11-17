"""Unique open-platform application names per tenant.

Application names were free-form, so tenants could create several apps with
the same name and only tell them apart by UUID. The name is the human handle
for keys, logs and the impact dialogs, so it must identify exactly one
application. The uniqueness scope is the whole tenant including archived rows
(an archived application still occupies its name because it can be restored;
purging releases it).

Historical data may already contain duplicates (dev databases accumulated
probe applications with identical names), so this migration renames every
occurrence after the first per (tenant_id, name) with a numeric suffix before
adding the constraint.
"""

import sqlalchemy as sa
from alembic import op

revision = "0069_open_app_unique_name"
down_revision = "0068_open_application_archive"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "SELECT id,tenant_id,name FROM open_applications ORDER BY tenant_id,name,created_at,id"
        )
    ).mappings().all()
    seen: dict[tuple[str, str], int] = {}
    occupied: set[tuple[str, str]] = {(r["tenant_id"], r["name"]) for r in rows}
    for row in rows:
        key = (row["tenant_id"], row["name"])
        taken = seen.get(key, 0)
        if not taken:
            seen[key] = 1
            continue
        seen[key] = taken + 1
        candidate = f"{row['name']}-{seen[key]}"
        while (row["tenant_id"], candidate) in occupied:
            seen[key] += 1
            candidate = f"{row['name']}-{seen[key]}"
        occupied.add((row["tenant_id"], candidate))
        conn.execute(
            sa.text("UPDATE open_applications SET name=:n WHERE id=:id"),
            {"n": candidate, "id": row["id"]},
        )
    op.create_unique_constraint(
        "uq_open_applications_tenant_name", "open_applications", ["tenant_id", "name"]
    )


def downgrade():
    op.drop_constraint(
        "uq_open_applications_tenant_name", "open_applications", type_="unique"
    )
