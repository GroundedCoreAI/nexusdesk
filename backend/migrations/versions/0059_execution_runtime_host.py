"""Persist Phase 4 runtime host process and execution workdir records.

Adds the two durable tables the Runtime Host and the Workspace manager need to
survive a Worker restart (03 §3.2): one Workdir row and one main process-group
row per Run. No columns are added to runtime_runs, no RuntimeHost service table
is created, and host identity comes from deployment settings plus boot
instances. The downgrade drops runtime_host_processes before execution_workdirs
because the process rows reference the Workdir rows (03 §8 data rollback).

Renumbered from the planned 0054 after revalidating the actual head
0058_agent_execution_metadata (08 R-1).
"""

from alembic import op

revision = "0059_execution_runtime_host"
down_revision = "0058_agent_execution_metadata"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        CREATE TABLE execution_workdirs (
            id UUID PRIMARY KEY,
            run_id UUID NOT NULL UNIQUE REFERENCES runtime_runs(id) ON DELETE CASCADE,
            tenant_id TEXT NOT NULL,
            business_id TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            relative_path TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL CHECK (status IN
                ('preparing','ready','active','retained','cleaning','deleted','cleanup_failed')),
            quota_bytes BIGINT NOT NULL,
            size_bytes BIGINT NOT NULL DEFAULT 0,
            file_count INTEGER NOT NULL DEFAULT 0,
            expires_at TIMESTAMPTZ,
            last_error_code TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            cleaned_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        "CREATE INDEX execution_workdirs_status_expires ON execution_workdirs (status, expires_at)"
    )
    op.execute(
        "CREATE INDEX execution_workdirs_tenant_status ON execution_workdirs (tenant_id, status)"
    )
    op.execute(
        """
        CREATE TABLE runtime_host_processes (
            id UUID PRIMARY KEY,
            run_id UUID NOT NULL UNIQUE REFERENCES runtime_runs(id) ON DELETE CASCADE,
            workdir_id UUID REFERENCES execution_workdirs(id) ON DELETE SET NULL,
            tenant_id TEXT NOT NULL,
            host_id TEXT NOT NULL,
            host_instance_id TEXT NOT NULL,
            sandbox_provider TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN
                ('starting','running','terminating','exited','orphaned','cleanup_failed')),
            pid INTEGER,
            process_group_id INTEGER,
            process_start_token TEXT,
            command_digest TEXT NOT NULL,
            cancel_requested_at TIMESTAMPTZ,
            cleanup_deadline_at TIMESTAMPTZ,
            exit_code INTEGER,
            last_observed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_error_code TEXT,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            started_at TIMESTAMPTZ,
            exited_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        "CREATE INDEX runtime_host_processes_host_status"
        " ON runtime_host_processes (host_id, status)"
    )
    op.execute(
        "CREATE INDEX runtime_host_processes_observed"
        " ON runtime_host_processes (status, last_observed_at)"
    )
    op.execute(
        "CREATE INDEX runtime_host_processes_tenant_status"
        " ON runtime_host_processes (tenant_id, status)"
    )


def downgrade():
    op.execute("DROP TABLE runtime_host_processes")
    op.execute("DROP TABLE execution_workdirs")
