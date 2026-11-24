"""Add tenant-scoped egress hosts managed from the model gateway console.

The deployment environment list stays authoritative. This table is an additive
extension used only while ``AGENT_MODEL_GATEWAY_UI_ALLOWED_HOSTS`` is enabled;
rows are public HTTPS DNS names (lowercased) with an audit trail. No secret
material is stored here.
"""

import sqlalchemy as sa
from alembic import op

revision = "0075_gateway_allowed_hosts"
down_revision = "0074_codex_wire_api_backfill"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gateway_allowed_hosts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("host", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("host = lower(host)", name="gateway_allowed_hosts_host_lower"),
        sa.UniqueConstraint("tenant_id", "host", name="gateway_allowed_hosts_unique"),
    )
    op.create_index(
        "gateway_allowed_hosts_tenant",
        "gateway_allowed_hosts",
        ["tenant_id"],
    )


def downgrade() -> None:
    op.drop_index("gateway_allowed_hosts_tenant", table_name="gateway_allowed_hosts")
    op.drop_table("gateway_allowed_hosts")
