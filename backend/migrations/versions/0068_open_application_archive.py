"""Archive flag for open-platform applications.

Applications on the open platform previously had no removal path at all: the
management routes only offered create / update / list and the table carried no
``archived`` column. Deletion follows the house convention (agents and service
applications both archive softly), so request logs, key records and webhook
history stay auditable. Revoking keys at archive time is done by the service
layer, not here.

The partial index keeps the default "active applications" listing cheap and
leaves archived rows out of it.
"""

from alembic import op

revision = "0068_open_application_archive"
down_revision = "0067_merge_heads"
branch_labels = None
depends_on = None


def upgrade():
    statements = [
        "ALTER TABLE open_applications ADD COLUMN archived boolean NOT NULL DEFAULT false",
        """CREATE INDEX open_apps_tenant_active
        ON open_applications(tenant_id,created_at) WHERE NOT archived""",
    ]
    for statement in statements:
        op.execute(statement)


def downgrade():
    op.execute("DROP INDEX IF EXISTS open_apps_tenant_active")
    op.execute("ALTER TABLE open_applications DROP COLUMN IF EXISTS archived")
