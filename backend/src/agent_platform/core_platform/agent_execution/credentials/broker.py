"""Short-lived Execution grant Broker over the credential repository (T-07).

Grants bind one credential version to one Run/engine/protocol/workspace and a
minimal scope set. The plaintext token exists only in the returned internal
object and in the controlled launch channel; the database stores an
irreversible hash. Consumption is one-time, so replay after a successful use is
denied. Every denial is audited with a stable code and no secret material.
"""

import hashlib
import json
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import text

from .models import ExecutionCredentialGrant
from .repository import ExecutionCredentialRepository
from .vault import ExecutionCredentialKeyError, ExecutionCredentialVault

MIN_GRANT_TTL_SECONDS = 30
MAX_GRANT_TTL_SECONDS = 3600


class CredentialGrantDenied(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class IssuedGrant:
    grant: ExecutionCredentialGrant
    token: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class ConsumedGrant:
    credential_ref: UUID
    credential_id: UUID
    credential_version: int
    scopes: tuple[str, ...]
    secret: str = field(repr=False)


class ExecutionCredentialBroker:
    def __init__(
        self,
        engine,
        vault: ExecutionCredentialVault,
        *,
        repository: ExecutionCredentialRepository | None = None,
        grant_ttl_seconds: int = 300,
    ) -> None:
        if not MIN_GRANT_TTL_SECONDS <= grant_ttl_seconds <= MAX_GRANT_TTL_SECONDS:
            raise ValueError("execution grant TTL must be within 30-3600 seconds")
        self._engine = engine
        self._vault = vault
        self._repository = repository or ExecutionCredentialRepository(engine, vault)
        self._ttl = grant_ttl_seconds

    async def issue(
        self,
        *,
        credential_ref: UUID,
        tenant_id: str,
        run_id: UUID,
        engine_id: str,
        protocol_id: str,
        workspace_id: str,
        scopes: tuple[str, ...],
        ttl_seconds: int | None = None,
        lease_epoch: int | None = None,
        actor: str | None = "runtime",
    ) -> IssuedGrant:
        ttl = self._ttl if ttl_seconds is None else ttl_seconds
        if not MIN_GRANT_TTL_SECONDS <= ttl <= MAX_GRANT_TTL_SECONDS:
            raise ValueError("execution grant TTL must be within 30-3600 seconds")
        credential = await self._repository.get(credential_ref=credential_ref, tenant_id=tenant_id)
        if credential is None:
            await self._deny(tenant_id, credential_ref, None, "credential_not_found", actor)
        if credential.status == "revoked" or credential.revoked_at is not None:
            await self._deny(
                tenant_id, credential_ref, credential.credential_id, "credential_revoked", actor
            )
        if credential.status != "active":
            await self._deny(
                tenant_id, credential_ref, credential.credential_id, "credential_superseded", actor
            )
        if engine_id not in credential.allowed_engines:
            await self._deny(
                tenant_id, credential_ref, credential.credential_id, "engine_denied", actor
            )
        if workspace_id not in credential.allowed_workspaces:
            await self._deny(
                tenant_id, credential_ref, credential.credential_id, "workspace_denied", actor
            )
        if not scopes:
            await self._deny(
                tenant_id, credential_ref, credential.credential_id, "scope_denied", actor
            )

        run_valid = await self._run_binding_valid(
            run_id=run_id, tenant_id=tenant_id, lease_epoch=lease_epoch
        )
        if not run_valid:
            await self._deny(
                tenant_id, credential_ref, credential.credential_id, "run_binding_mismatch", actor
            )

        token = secrets.token_urlsafe(32)
        grant_hash = hashlib.sha256(token.encode()).hexdigest()
        issued, expires = datetime.now(UTC), datetime.now(UTC) + timedelta(seconds=ttl)
        grant = ExecutionCredentialGrant(
            grant_id=uuid4(),
            grant_hash=grant_hash,
            credential_id=credential.credential_id,
            credential_version=credential.version,
            run_id=run_id,
            tenant_id=tenant_id,
            engine_id=engine_id,
            protocol_id=protocol_id,
            workspace_id=workspace_id,
            scopes=scopes,
            issued_at=issued,
            expires_at=expires,
        )
        async with self._engine.begin() as conn:
            await conn.execute(
                text("""INSERT INTO execution_credential_grants
                (id,grant_hash,credential_id,credential_version,run_id,tenant_id,
                 engine_id,protocol_id,workspace_id,scopes,issued_at,expires_at)
                VALUES (:id,:hash,:credential_id,:version,:run_id,:tenant,:engine,
                :protocol,:workspace,CAST(:scopes AS jsonb),:issued,:expires)"""),
                {
                    "id": grant.grant_id,
                    "hash": grant_hash,
                    "credential_id": credential.credential_id,
                    "version": credential.version,
                    "run_id": run_id,
                    "tenant": tenant_id,
                    "engine": engine_id,
                    "protocol": protocol_id,
                    "workspace": workspace_id,
                    "scopes": json.dumps(list(scopes)),
                    "issued": issued,
                    "expires": expires,
                },
            )
        await self._repository.audit(
            tenant_id=tenant_id,
            action="grant_issued",
            credential_ref=credential_ref,
            credential_id=credential.credential_id,
            grant_id=grant.grant_id,
            actor=actor,
        )
        return IssuedGrant(grant=grant, token=token)

    async def consume(
        self,
        *,
        token: str,
        run_id: UUID,
        tenant_id: str,
        engine_id: str,
        protocol_id: str,
        workspace_id: str,
        required_scopes: tuple[str, ...] = (),
        actor: str | None = "runtime",
    ) -> ConsumedGrant:
        if not token:
            await self._deny(None, None, None, "grant_not_found", actor)
        grant_hash = hashlib.sha256(token.encode()).hexdigest()
        async with self._engine.connect() as conn:
            row = (
                (
                    await conn.execute(
                        text("""SELECT * FROM execution_credential_grants
                        WHERE grant_hash=:hash"""),
                        {"hash": grant_hash},
                    )
                )
                .mappings()
                .first()
            )
        if row is None:
            await self._deny(tenant_id, None, None, "grant_not_found", actor)
        if (
            row["run_id"] != run_id
            or row["tenant_id"] != tenant_id
            or row["engine_id"] != engine_id
            or row["protocol_id"] != protocol_id
            or row["workspace_id"] != workspace_id
        ):
            await self._deny(
                row["tenant_id"], None, row["credential_id"], "grant_binding_mismatch", actor
            )
        now = datetime.now(UTC)
        expires = row["expires_at"]
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        if expires <= now:
            await self._deny(row["tenant_id"], None, row["credential_id"], "grant_expired", actor)
        if row["revoked_at"] is not None:
            await self._deny(row["tenant_id"], None, row["credential_id"], "grant_revoked", actor)
        credential = await self._repository.get(
            credential_ref=await self._credential_ref(row["credential_id"], tenant_id),
            tenant_id=tenant_id,
            version=row["credential_version"],
        )
        if (
            credential is None
            or credential.status == "revoked"
            or credential.revoked_at is not None
        ):
            await self._deny(
                row["tenant_id"], None, row["credential_id"], "credential_revoked", actor
            )
        scopes = tuple(row["scopes"] or ())
        if not set(required_scopes) <= set(scopes):
            await self._deny(
                row["tenant_id"], None, row["credential_id"], "grant_scope_denied", actor
            )

        async with self._engine.begin() as conn:
            consumed = await conn.scalar(
                text("""UPDATE execution_credential_grants SET last_used_at=now()
                WHERE id=:id AND last_used_at IS NULL AND revoked_at IS NULL
                  AND expires_at>now() RETURNING id"""),
                {"id": row["id"]},
            )
        if consumed is None:
            await self._deny(row["tenant_id"], None, row["credential_id"], "grant_replayed", actor)
        try:
            secret = self._vault.decrypt(
                credential.encrypted_secret,
                credential_id=credential.credential_id,
                tenant_id=tenant_id,
                version=credential.version,
            )
        except ExecutionCredentialKeyError:
            await self._deny(
                row["tenant_id"], None, row["credential_id"], "credential_key_unavailable", actor
            )
        await self._repository.audit(
            tenant_id=tenant_id,
            action="grant_used",
            credential_ref=credential.credential_ref,
            credential_id=credential.credential_id,
            grant_id=row["id"],
            actor=actor,
        )
        return ConsumedGrant(
            credential_ref=credential.credential_ref,
            credential_id=credential.credential_id,
            credential_version=credential.version,
            scopes=scopes,
            secret=secret,
        )

    async def _credential_ref(self, credential_id: UUID, tenant_id: str) -> UUID:
        async with self._engine.connect() as conn:
            value = await conn.scalar(
                text("""SELECT credential_ref FROM execution_credentials
                WHERE id=:id AND tenant_id=:tenant"""),
                {"id": credential_id, "tenant": tenant_id},
            )
        return value if value is not None else uuid4()

    async def _run_binding_valid(
        self, *, run_id: UUID, tenant_id: str, lease_epoch: int | None
    ) -> bool:
        async with self._engine.connect() as conn:
            row = (
                (
                    await conn.execute(
                        text("""SELECT tenant_id,lease_epoch FROM runtime_runs
                        WHERE id=:id"""),
                        {"id": run_id},
                    )
                )
                .mappings()
                .first()
            )
        if row is None or row["tenant_id"] != tenant_id:
            return False
        return lease_epoch is None or row["lease_epoch"] == lease_epoch

    async def _deny(
        self,
        tenant_id: str | None,
        credential_ref: UUID | None,
        credential_id: UUID | None,
        reason: str,
        actor: str | None,
    ) -> None:
        if tenant_id is not None:
            await self._repository.audit(
                tenant_id=tenant_id,
                action="grant_denied",
                outcome="denied",
                reason_code=reason,
                credential_ref=credential_ref,
                credential_id=credential_id,
                actor=actor,
            )
        raise CredentialGrantDenied(reason)
