"""Phase 6 T-07: Execution credential versions, grants, and Secret-free audit.

Revision id stays within ``alembic_version.version_num`` VARCHAR(32) (08 R-16).
A credential is an immutable version row; rotation inserts version N+1, marks
the prior row superseded, and revocation applies to every version. Grants pin
the exact credential version and bind Run/engine/protocol/workspace/scope/TTL.
No plaintext secret column exists; the audit table carries stable codes only.
The downgrade refuses populated security data and never touches Run history.
"""

from alembic import op

revision = "0069_execution_credential"
down_revision = "0068_execution_fencing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE execution_credentials (
            id UUID PRIMARY KEY,
            credential_ref UUID NOT NULL,
            tenant_id TEXT NOT NULL,
            name TEXT NOT NULL,
            credential_type TEXT NOT NULL CHECK (credential_type IN
                ('token','api_key','oauth_client','mtls_certificate')),
            encrypted_secret TEXT NOT NULL,
            key_version TEXT NOT NULL,
            version INTEGER NOT NULL CHECK (version >= 1),
            status TEXT NOT NULL CHECK (status IN
                ('active','superseded','revoked')),
            allowed_engines JSONB NOT NULL DEFAULT '[]'::jsonb,
            allowed_workspaces JSONB NOT NULL DEFAULT '[]'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            rotated_at TIMESTAMPTZ NULL,
            revoked_at TIMESTAMPTZ NULL,
            UNIQUE (credential_ref, version)
        )
        """
    )
    op.execute(
        "CREATE INDEX execution_credentials_tenant"
        " ON execution_credentials (tenant_id, credential_ref)"
    )
    op.execute(
        "CREATE UNIQUE INDEX execution_credentials_one_active"
        " ON execution_credentials (credential_ref) WHERE status='active'"
    )
    op.execute(
        """
        CREATE TABLE execution_credential_grants (
            id UUID PRIMARY KEY,
            grant_hash TEXT NOT NULL UNIQUE,
            credential_id UUID NOT NULL
                REFERENCES execution_credentials(id) ON DELETE RESTRICT,
            credential_version INTEGER NOT NULL CHECK (credential_version >= 1),
            run_id UUID NOT NULL REFERENCES runtime_runs(id) ON DELETE CASCADE,
            tenant_id TEXT NOT NULL,
            engine_id TEXT NOT NULL,
            protocol_id TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            scopes JSONB NOT NULL,
            issued_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at TIMESTAMPTZ NOT NULL,
            revoked_at TIMESTAMPTZ NULL,
            last_used_at TIMESTAMPTZ NULL,
            CHECK (expires_at > issued_at)
        )
        """
    )
    op.execute(
        "CREATE INDEX execution_credential_grants_run ON execution_credential_grants (run_id)"
    )
    op.execute(
        "CREATE INDEX execution_credential_grants_tenant"
        " ON execution_credential_grants (tenant_id, issued_at)"
    )
    op.execute(
        "CREATE INDEX execution_credential_grants_credential"
        " ON execution_credential_grants (credential_id, credential_version)"
    )
    op.execute(
        """
        CREATE TABLE execution_credential_audit (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id TEXT NOT NULL,
            credential_ref UUID NULL,
            credential_id UUID NULL,
            grant_id UUID NULL,
            action TEXT NOT NULL CHECK (action IN
                ('created','rotated','revoked','grant_issued','grant_denied',
                 'grant_used')),
            outcome TEXT NOT NULL DEFAULT 'success'
                CHECK (outcome IN ('success','denied')),
            reason_code TEXT NULL,
            actor TEXT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX execution_credential_audit_tenant"
        " ON execution_credential_audit (tenant_id, created_at)"
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM execution_credentials)
               OR EXISTS (SELECT 1 FROM execution_credential_grants)
               OR EXISTS (SELECT 1 FROM execution_credential_audit) THEN
                RAISE EXCEPTION 'execution credential 0069 downgrade refused:'
                    ' export credential, grant and audit data first';
            END IF;
        END
        $$
        """
    )
    op.execute("DROP TABLE execution_credential_audit")
    op.execute("DROP TABLE execution_credential_grants")
    op.execute("DROP TABLE execution_credentials")
