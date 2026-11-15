"""Health checklist snapshots, notification events and worker heartbeats.

Four tables back the monitoring centre:

* ``monitor_checks`` — the latest outcome per check, one row per
  ``(check_id, scope, object_id, tenant)``. The checklist endpoint only reads
  this table; probes never run on a request path.
* ``notifications`` — state transitions (opened / recovered / reminder) with
  acknowledgement and suppression state.
* ``monitor_scans`` — the scanner's own heartbeat, so a dead scanner cannot
  look like an all-green system.
* ``worker_heartbeats`` — process-level liveness for the embedded workers;
  ``runtime_runs.lease_until`` only proves that one run was renewed.
"""

from alembic import op

revision = "0060_monitoring"
down_revision = "0059_service_app_conversation"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """CREATE TABLE monitor_checks (
        check_id TEXT NOT NULL, tenant_id TEXT NOT NULL DEFAULT '',
        scope TEXT NOT NULL DEFAULT 'global', object_id TEXT NOT NULL DEFAULT '',
        check_type TEXT NOT NULL, severity TEXT NOT NULL, status TEXT NOT NULL,
        summary TEXT NOT NULL DEFAULT '', evidence JSONB NOT NULL DEFAULT '{}',
        action_label TEXT, action_route TEXT, streak INTEGER NOT NULL DEFAULT 0,
        first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        changed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        checked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (check_id, scope, object_id, tenant_id))"""
    )
    op.execute("CREATE INDEX monitor_checks_tenant ON monitor_checks(tenant_id, status, severity)")
    op.execute("CREATE INDEX monitor_checks_status ON monitor_checks(status, checked_at)")
    op.execute(
        """CREATE TABLE notifications (
        id UUID PRIMARY KEY, tenant_id TEXT NOT NULL, check_id TEXT NOT NULL,
        scope TEXT NOT NULL DEFAULT 'global', object_id TEXT NOT NULL DEFAULT '',
        fingerprint TEXT NOT NULL, kind TEXT NOT NULL, severity TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'active', title TEXT NOT NULL,
        impact TEXT NOT NULL DEFAULT '', evidence JSONB NOT NULL DEFAULT '{}',
        source TEXT NOT NULL DEFAULT 'monitor', action_label TEXT, action_route TEXT,
        first_seen_at TIMESTAMPTZ NOT NULL, last_seen_at TIMESTAMPTZ NOT NULL,
        resolved_at TIMESTAMPTZ, acknowledged_by TEXT, acknowledged_at TIMESTAMPTZ,
        suppressed_until TIMESTAMPTZ, reminder_sent_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        UNIQUE (fingerprint, kind, first_seen_at))"""
    )
    op.execute(
        "CREATE INDEX notifications_unread ON notifications(tenant_id, status, created_at DESC)"
    )
    op.execute("CREATE INDEX notifications_feed ON notifications(tenant_id, created_at DESC)")
    op.execute(
        """CREATE TABLE monitor_scans (
        id BIGSERIAL PRIMARY KEY, tenant_id TEXT NOT NULL DEFAULT '',
        started_at TIMESTAMPTZ NOT NULL, finished_at TIMESTAMPTZ,
        duration_ms INTEGER, checks_total INTEGER NOT NULL DEFAULT 0,
        checks_failed INTEGER NOT NULL DEFAULT 0, error_code TEXT)"""
    )
    op.execute("CREATE INDEX monitor_scans_recent ON monitor_scans(started_at DESC)")
    op.execute(
        """CREATE TABLE worker_heartbeats (
        worker_id TEXT PRIMARY KEY, host TEXT NOT NULL,
        started_at TIMESTAMPTZ NOT NULL, beat_at TIMESTAMPTZ NOT NULL,
        detail JSONB NOT NULL DEFAULT '{}')"""
    )
    op.execute("CREATE INDEX worker_heartbeats_beat ON worker_heartbeats(beat_at DESC)")


def downgrade():
    op.execute("DROP TABLE worker_heartbeats")
    op.execute("DROP TABLE monitor_scans")
    op.execute("DROP TABLE notifications")
    op.execute("DROP TABLE monitor_checks")
