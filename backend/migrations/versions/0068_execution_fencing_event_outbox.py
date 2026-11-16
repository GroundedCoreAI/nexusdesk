"""Phase 6 reliability/event foundation: fencing, event identity, Outbox, usage.

Revalidated head before implementation: ``0067_merge_heads`` is the only head
(08 R-1), so this revision joins that merge point. The revision identifier is
``0068_execution_fencing`` because ``alembic_version.version_num`` is
``VARCHAR(32)`` (08 R-16); the filename keeps the descriptive task name. The upgrade is expand ->
deterministic backfill -> validate -> read/write switch:

- ``runtime_runs`` gains the database-owned monotonic ``lease_epoch``, split
  cancellation intent/confirmation, cleanup status, retry correlation, a
  server-owned side-effect snapshot, and the per-Run event retention floor.
- ``runtime_events`` gains a deterministic identity (UUID derived from
  ``run_id:seq``), schema/source metadata, producer dedup keys, and Session/
  trace columns. Historical sequence is never renumbered and historical rows
  are never enqueued into the public Outbox.
- ``runtime_event_outbox`` receives one publishable row per new event through an
  AFTER INSERT trigger, so old binaries and direct production writers cannot
  bypass publication. Internal ``tool.replay`` is identity-bearing but excluded.
- ``runtime_usage_ledger`` is source-unique with a correction chain; it never
  copies or sums the separate model-gateway ``gateway_costs`` ledger.
- ``execution_fencing_denials`` is a bounded, payload-free audit landing point
  written in a separate transaction after a stale write rolled back (R-14).

The downgrade is data-preserving: it refuses to delete populated event, usage,
Outbox, or denial data. A populated rollback requires an explicit export and is
not routine rollback (03 §4.5/§10.6).
"""

from alembic import op

revision = "0068_execution_fencing"
down_revision = "0067_merge_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- runtime_runs expansion ------------------------------------------
    op.execute(
        """
        ALTER TABLE runtime_runs
        ADD COLUMN lease_epoch BIGINT NOT NULL DEFAULT 0,
        ADD COLUMN cancel_requested_at TIMESTAMPTZ NULL,
        ADD COLUMN cancel_confirmed_at TIMESTAMPTZ NULL,
        ADD COLUMN cleanup_status TEXT NOT NULL DEFAULT 'not_started',
        ADD COLUMN cleanup_updated_at TIMESTAMPTZ NULL,
        ADD COLUMN retry_of_run_id UUID NULL REFERENCES runtime_runs(id) ON DELETE SET NULL,
        ADD COLUMN attempt_no INTEGER NOT NULL DEFAULT 1,
        ADD COLUMN side_effect_policy JSONB NULL,
        ADD COLUMN event_retention_floor_seq INTEGER NOT NULL DEFAULT 0
        """
    )
    op.execute(
        """
        ALTER TABLE runtime_runs
        ADD CONSTRAINT runtime_runs_cleanup_status_check
        CHECK (cleanup_status IN ('not_started','in_progress','completed','failed')),
        ADD CONSTRAINT runtime_runs_attempt_no_check CHECK (attempt_no >= 1)
        """
    )
    # Terminal historical rows already completed their observable cleanup
    # bookkeeping decision; anything still open starts at not_started.
    op.execute(
        """
        UPDATE runtime_runs
        SET cleanup_status='completed',
            cleanup_updated_at=COALESCE(finished_at, now())
        WHERE status IN ('completed','failed','cancelled')
          AND cleanup_status='not_started'
        """
    )

    # ---- runtime_events identity expansion -------------------------------
    op.execute(
        """
        ALTER TABLE runtime_events
        ADD COLUMN event_id UUID NULL,
        ADD COLUMN schema_version TEXT NOT NULL DEFAULT 'v1',
        ADD COLUMN source TEXT NOT NULL DEFAULT 'platform',
        ADD COLUMN producer_id TEXT NULL,
        ADD COLUMN producer_event_id TEXT NULL,
        ADD COLUMN engine_session_id TEXT NULL,
        ADD COLUMN trace_id TEXT NULL
        """
    )
    op.execute(
        """
        ALTER TABLE runtime_events
        ADD CONSTRAINT runtime_events_source_check
        CHECK (source IN ('platform','engine_native'))
        """
    )
    # Deterministic UUID derived from run_id:seq (not random per rerun). The
    # same populated database re-run produces exactly the same identity.
    op.execute(
        """
        UPDATE runtime_events
        SET event_id = (
            substr(md5(run_id::text || ':' || seq::text), 1, 8) || '-' ||
            substr(md5(run_id::text || ':' || seq::text), 9, 4) || '-' ||
            substr(md5(run_id::text || ':' || seq::text), 13, 4) || '-' ||
            substr(md5(run_id::text || ':' || seq::text), 17, 4) || '-' ||
            substr(md5(run_id::text || ':' || seq::text), 21, 12)
        )::uuid
        WHERE event_id IS NULL
        """
    )
    op.execute("ALTER TABLE runtime_events ALTER COLUMN event_id SET NOT NULL")
    op.execute("ALTER TABLE runtime_events ALTER COLUMN event_id SET DEFAULT gen_random_uuid()")
    op.execute("CREATE UNIQUE INDEX runtime_events_event_id_key ON runtime_events(event_id)")
    op.execute(
        """
        CREATE UNIQUE INDEX runtime_events_producer_dedup
        ON runtime_events(run_id, producer_id, producer_event_id)
        WHERE producer_id IS NOT NULL AND producer_event_id IS NOT NULL
        """
    )

    # ---- transactional Outbox --------------------------------------------
    op.execute(
        """
        CREATE TABLE runtime_event_outbox (
            run_id UUID NOT NULL,
            seq INTEGER NOT NULL,
            event_id UUID NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending','published')),
            attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
            available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            published_at TIMESTAMPTZ NULL,
            last_error TEXT NULL,
            PRIMARY KEY (run_id, seq),
            FOREIGN KEY (run_id, seq)
                REFERENCES runtime_events(run_id, seq) ON DELETE CASCADE
        )
        """
    )
    op.execute(
        "CREATE INDEX runtime_event_outbox_pending ON runtime_event_outbox (status, available_at)"
    )
    op.execute(
        """
        CREATE TABLE runtime_event_outbox_watermark (
            id TEXT PRIMARY KEY,
            created_after TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    # Rollout watermark: reconciliation only considers events created at/after
    # it, so the migration cannot flood the Outbox with historical rows.
    op.execute(
        "INSERT INTO runtime_event_outbox_watermark(id, created_after) VALUES ('default', now())"
    )
    op.execute(
        """
        CREATE FUNCTION runtime_event_outbox_enqueue() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.type <> 'tool.replay' THEN
                INSERT INTO runtime_event_outbox(run_id, seq, event_id, status)
                VALUES (NEW.run_id, NEW.seq, NEW.event_id, 'pending')
                ON CONFLICT DO NOTHING;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER runtime_events_outbox_trigger
        AFTER INSERT ON runtime_events
        FOR EACH ROW EXECUTE FUNCTION runtime_event_outbox_enqueue()
        """
    )

    # ---- usage ledger ------------------------------------------------------
    op.execute(
        """
        CREATE TABLE runtime_usage_ledger (
            id UUID PRIMARY KEY,
            run_id UUID NOT NULL REFERENCES runtime_runs(id) ON DELETE CASCADE,
            tenant_id TEXT NOT NULL,
            lease_epoch BIGINT NOT NULL,
            source TEXT NOT NULL,
            source_event_id TEXT NOT NULL,
            usage_schema_version TEXT NOT NULL DEFAULT 'v1',
            usage JSONB NOT NULL,
            cost NUMERIC NULL,
            is_estimate BOOLEAN NOT NULL DEFAULT false,
            supersedes_id UUID NULL
                REFERENCES runtime_usage_ledger(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (run_id, source, source_event_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX runtime_usage_ledger_tenant ON runtime_usage_ledger (tenant_id, created_at)"
    )
    op.execute(
        "CREATE INDEX runtime_usage_ledger_supersedes"
        " ON runtime_usage_ledger (supersedes_id)"
        " WHERE supersedes_id IS NOT NULL"
    )

    # ---- fencing denial audit (separate transaction, no payload) ----------
    op.execute(
        """
        CREATE TABLE execution_fencing_denials (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            run_id UUID NOT NULL,
            operation TEXT NOT NULL CHECK (operation IN
                ('snapshot','append','finish','heartbeat','usage','tool_replay',
                 'process','workdir','resource_release')),
            reason TEXT NOT NULL CHECK (reason IN
                ('owner_mismatch','stale_epoch','lease_lost','run_terminal','run_missing')),
            stale_owner UUID NULL,
            stale_lease_epoch BIGINT NULL,
            current_owner UUID NULL,
            current_lease_epoch BIGINT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX execution_fencing_denials_run"
        " ON execution_fencing_denials (run_id, created_at)"
    )


def downgrade() -> None:
    # Data-preserving guard: populated event/usage/outbox/denial data must be
    # exported or protected first; routine rollback never deletes it.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM runtime_events)
               OR EXISTS (SELECT 1 FROM runtime_usage_ledger)
               OR EXISTS (SELECT 1 FROM runtime_event_outbox)
               OR EXISTS (SELECT 1 FROM execution_fencing_denials) THEN
                RAISE EXCEPTION 'execution 0068 downgrade refused:'
                    ' export event, usage, outbox and fencing data first';
            END IF;
        END
        $$
        """
    )
    op.execute("DROP TRIGGER IF EXISTS runtime_events_outbox_trigger ON runtime_events")
    op.execute("DROP FUNCTION IF EXISTS runtime_event_outbox_enqueue()")
    op.execute("DROP TABLE execution_fencing_denials")
    op.execute("DROP TABLE runtime_usage_ledger")
    op.execute("DROP TABLE runtime_event_outbox_watermark")
    op.execute("DROP TABLE runtime_event_outbox")
    op.execute("DROP INDEX IF EXISTS runtime_events_producer_dedup")
    op.execute("DROP INDEX IF EXISTS runtime_events_event_id_key")
    op.execute(
        """
        ALTER TABLE runtime_events
        DROP CONSTRAINT IF EXISTS runtime_events_source_check,
        DROP COLUMN event_id,
        DROP COLUMN schema_version,
        DROP COLUMN source,
        DROP COLUMN producer_id,
        DROP COLUMN producer_event_id,
        DROP COLUMN engine_session_id,
        DROP COLUMN trace_id
        """
    )
    op.execute(
        """
        ALTER TABLE runtime_runs
        DROP CONSTRAINT IF EXISTS runtime_runs_cleanup_status_check,
        DROP CONSTRAINT IF EXISTS runtime_runs_attempt_no_check
        """
    )
    op.execute(
        """
        ALTER TABLE runtime_runs
        DROP COLUMN lease_epoch,
        DROP COLUMN cancel_requested_at,
        DROP COLUMN cancel_confirmed_at,
        DROP COLUMN cleanup_status,
        DROP COLUMN cleanup_updated_at,
        DROP COLUMN retry_of_run_id,
        DROP COLUMN attempt_no,
        DROP COLUMN side_effect_policy,
        DROP COLUMN event_retention_floor_seq
        """
    )
