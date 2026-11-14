"""Per-operator read state for the notification centre.

``status`` already carries the alert's lifecycle (active / acknowledged /
resolved / suppressed) and the scanner owns it. "Read" is a different axis: an
operator looking at a still-failing alert should clear the bell without
silencing the alert, otherwise acknowledging a real incident also kills every
later reminder. ``read_at`` keeps the two independent — unread counts filter on
it, reminders keep filtering on ``status = 'active'``.
"""

from alembic import op

revision = "0061_notification_read_state"
down_revision = "0060_monitoring"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE notifications ADD COLUMN IF NOT EXISTS read_at TIMESTAMPTZ")
    # Unread badge and the unread tab both filter (tenant, status, read_at).
    op.execute(
        """CREATE INDEX IF NOT EXISTS notifications_unread_state
        ON notifications(tenant_id, status, read_at, created_at DESC)"""
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS notifications_unread_state")
    op.execute("ALTER TABLE notifications DROP COLUMN IF EXISTS read_at")
