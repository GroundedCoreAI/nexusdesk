"""Auto-provision the Codex execution credential when a gateway channel is saved.

An administrator who creates an OpenAI-compatible channel only thinks in terms
of "name / address / API key". The Codex CLI, however, reads its key from the
separate ``execution_credentials`` vault via ``execution_credential_ref`` on the
connection spec. Without that reference the model profile never appears in the
Agent's Codex profile picker.

This module bridges the two credential stores at the moment a connection is
saved: the already-submitted API Key is registered as a codex-scoped execution
credential (or rotated in place when the key changes) and the resulting UUID is
written back into the connection spec. All writes use the caller's transaction
so the connection and its credential are committed atomically.

Only ``direct`` API Keys are eligible. An ``environment`` credential_ref names
an env var on the outbound Gateway client and has no secret to copy, so it is
left untouched (the operator must bind a codex credential explicitly).
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import text

from agent_platform.core_platform.agent_execution.credentials.vault import (
    ExecutionCredentialVault,
)

# Codex is the only engine this auto-provision targets, and ``default`` is the
# workspace an Agent gets unless explicitly assigned. The publish validator
# (agent_config.service.validate_codex_credential) requires the credential's
# allowed_workspaces to include the Agent workspace, so the default must be here.
_CODEX_ENGINES = ("codex",)
_DEFAULT_WORKSPACES = ("default",)


async def _write_audit(conn, tenant: str, actor: str | None, action: str, credential_ref: UUID, credential_id: UUID) -> None:
    await conn.execute(
        text("""INSERT INTO execution_credential_audit
        (tenant_id,credential_ref,credential_id,action,outcome,actor)
        VALUES (:tenant,:ref,:id,:action,'success',:actor)"""),
        {
            "tenant": tenant,
            "ref": credential_ref,
            "id": credential_id,
            "action": action,
            "actor": actor,
        },
    )


async def ensure_codex_credential(
    conn,
    *,
    tenant: str,
    actor: str | None,
    key_file: Path,
    name: str,
    secret: str,
    existing_ref: UUID | None,
) -> UUID:
    """Create or rotate a codex-scoped execution credential in ``conn``.

    Returns the credential_ref to store on the connection spec. When
    ``existing_ref`` points at a live credential it is rotated (version N+1),
    keeping the ref stable for already-published Agent snapshots. Otherwise a
    new credential is created.
    """
    vault = ExecutionCredentialVault(key_file)
    now = datetime.now(UTC)

    if existing_ref is not None:
        latest = (
            (
                await conn.execute(
                    text("""SELECT id,version,status FROM execution_credentials
                    WHERE credential_ref=:ref AND tenant_id=:t
                    ORDER BY version DESC LIMIT 1 FOR UPDATE"""),
                    {"ref": existing_ref, "t": tenant},
                )
            )
            .mappings()
            .first()
        )
        if latest is not None and latest["status"] != "revoked":
            new_version = int(latest["version"]) + 1
            credential_id = uuid4()
            encrypted, key_version = vault.encrypt(
                secret,
                credential_id=credential_id,
                tenant_id=tenant,
                version=new_version,
            )
            await conn.execute(
                text("""UPDATE execution_credentials
                SET status='superseded',updated_at=:now,rotated_at=:now
                WHERE id=:id AND status='active'"""),
                {"id": latest["id"], "now": now},
            )
            await conn.execute(
                text("""INSERT INTO execution_credentials
                (id,credential_ref,tenant_id,name,credential_type,encrypted_secret,
                 key_version,version,status,allowed_engines,allowed_workspaces,
                 created_at,updated_at)
                VALUES (:id,:ref,:t,:name,'api_key',:secret,:key_version,:version,
                'active',CAST(:engines AS jsonb),CAST(:workspaces AS jsonb),
                :created_at,:updated_at)"""),
                {
                    "id": credential_id,
                    "ref": existing_ref,
                    "t": tenant,
                    "name": name,
                    "secret": encrypted,
                    "key_version": key_version,
                    "version": new_version,
                    "engines": json.dumps(list(_CODEX_ENGINES)),
                    "workspaces": json.dumps(list(_DEFAULT_WORKSPACES)),
                    "created_at": now,
                    "updated_at": now,
                },
            )
            await _write_audit(conn, tenant, actor, "rotated", existing_ref, credential_id)
            return existing_ref

    credential_ref, credential_id = uuid4(), uuid4()
    encrypted, key_version = vault.encrypt(
        secret, credential_id=credential_id, tenant_id=tenant, version=1
    )
    await conn.execute(
        text("""INSERT INTO execution_credentials
        (id,credential_ref,tenant_id,name,credential_type,encrypted_secret,
         key_version,version,status,allowed_engines,allowed_workspaces,
         created_at,updated_at)
        VALUES (:id,:ref,:t,:name,'api_key',:secret,:key_version,1,
        'active',CAST(:engines AS jsonb),CAST(:workspaces AS jsonb),
        :created_at,:updated_at)"""),
        {
            "id": credential_id,
            "ref": credential_ref,
            "t": tenant,
            "name": name,
            "secret": encrypted,
            "key_version": key_version,
            "engines": json.dumps(list(_CODEX_ENGINES)),
            "workspaces": json.dumps(list(_DEFAULT_WORKSPACES)),
            "created_at": now,
            "updated_at": now,
        },
    )
    await _write_audit(conn, tenant, actor, "created", credential_ref, credential_id)
    return credential_ref
