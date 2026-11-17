"""Durable Execution credential lifecycle (T-07).

Version rows are immutable: creation inserts version 1, rotation inserts
version N+1 and marks the prior active row superseded, and revocation applies
to every version plus its outstanding grants. Every administrative action
writes a Secret-free audit row. Runtime key material is never read here.
"""

import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import text

from .models import ExecutionCredentialRecord
from .vault import ExecutionCredentialVault


class CredentialNotFound(LookupError):
    pass


class CredentialLifecycleError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _aware(value) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class ExecutionCredentialRepository:
    def __init__(self, engine, vault: ExecutionCredentialVault) -> None:
        self._engine = engine
        self._vault = vault

    async def audit(
        self,
        *,
        tenant_id: str,
        action: str,
        outcome: str = "success",
        reason_code: str | None = None,
        credential_ref: UUID | None = None,
        credential_id: UUID | None = None,
        grant_id: UUID | None = None,
        actor: str | None = None,
    ) -> None:
        """Stable-code audit; no secret, payload, or exception text."""
        async with self._engine.begin() as conn:
            await conn.execute(
                text("""INSERT INTO execution_credential_audit
                (tenant_id,credential_ref,credential_id,grant_id,action,outcome,
                 reason_code,actor)
                VALUES (:tenant,:credential_ref,:credential_id,:grant_id,:action,
                :outcome,:reason_code,:actor)"""),
                {
                    "tenant": tenant_id,
                    "credential_ref": credential_ref,
                    "credential_id": credential_id,
                    "grant_id": grant_id,
                    "action": action,
                    "outcome": outcome,
                    "reason_code": reason_code,
                    "actor": actor,
                },
            )

    async def create(
        self,
        *,
        tenant_id: str,
        name: str,
        credential_type: str,
        secret: str,
        allowed_engines: tuple[str, ...],
        allowed_workspaces: tuple[str, ...],
        actor: str | None = None,
    ) -> ExecutionCredentialRecord:
        if not allowed_engines or not allowed_workspaces:
            raise ValueError("execution credential scope must be explicit")
        credential_ref, credential_id = uuid4(), uuid4()
        encrypted, key_version = self._vault.encrypt(
            secret, credential_id=credential_id, tenant_id=tenant_id, version=1
        )
        record = ExecutionCredentialRecord(
            credential_id=credential_id,
            credential_ref=credential_ref,
            tenant_id=tenant_id,
            name=name,
            credential_type=credential_type,  # type: ignore[arg-type]
            encrypted_secret=encrypted,
            key_version=key_version,
            version=1,
            status="active",
            allowed_engines=allowed_engines,
            allowed_workspaces=allowed_workspaces,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        async with self._engine.begin() as conn:
            await conn.execute(
                text("""INSERT INTO execution_credentials
                (id,credential_ref,tenant_id,name,credential_type,encrypted_secret,
                 key_version,version,status,allowed_engines,allowed_workspaces,
                 created_at,updated_at)
                VALUES (:id,:ref,:tenant,:name,:type,:secret,:key_version,:version,
                :status,CAST(:engines AS jsonb),CAST(:workspaces AS jsonb),
                :created_at,:updated_at)"""),
                {
                    "id": credential_id,
                    "ref": credential_ref,
                    "tenant": tenant_id,
                    "name": name,
                    "type": credential_type,
                    "secret": encrypted,
                    "key_version": key_version,
                    "version": 1,
                    "status": "active",
                    "engines": json.dumps(list(allowed_engines)),
                    "workspaces": json.dumps(list(allowed_workspaces)),
                    "created_at": record.created_at,
                    "updated_at": record.updated_at,
                },
            )
        await self.audit(
            tenant_id=tenant_id,
            action="created",
            credential_ref=credential_ref,
            credential_id=credential_id,
            actor=actor,
        )
        return record

    async def rotate(
        self,
        *,
        credential_ref: UUID,
        tenant_id: str,
        secret: str,
        actor: str | None = None,
    ) -> ExecutionCredentialRecord | None:
        async with self._engine.begin() as conn:
            latest = (
                (
                    await conn.execute(
                        text("""SELECT * FROM execution_credentials
                        WHERE credential_ref=:ref AND tenant_id=:tenant
                        ORDER BY version DESC LIMIT 1 FOR UPDATE"""),
                        {"ref": credential_ref, "tenant": tenant_id},
                    )
                )
                .mappings()
                .first()
            )
            if latest is None:
                return None
            if latest["status"] == "revoked":
                raise CredentialLifecycleError("credential_revoked")
            new_version = int(latest["version"]) + 1
            credential_id = uuid4()
            encrypted, key_version = self._vault.encrypt(
                secret,
                credential_id=credential_id,
                tenant_id=tenant_id,
                version=new_version,
            )
            now = datetime.now(UTC)
            await conn.execute(
                text("""UPDATE execution_credentials
                SET status='superseded',updated_at=:now,rotated_at=:now
                WHERE id=:id AND status='active'"""),
                {"id": latest["id"], "now": now},
            )
            await conn.execute(
                text("""INSERT INTO execution_credentials
                (id,credential_ref,tenant_id,name,credential_type,encrypted_secret,
                 key_version,version,status,allowed_engines,allowed_workspaces)
                VALUES (:id,:ref,:tenant,:name,:type,:secret,:key_version,:version,
                'active',CAST(:engines AS jsonb),CAST(:workspaces AS jsonb))"""),
                {
                    "id": credential_id,
                    "ref": credential_ref,
                    "tenant": tenant_id,
                    "name": latest["name"],
                    "type": latest["credential_type"],
                    "secret": encrypted,
                    "key_version": key_version,
                    "version": new_version,
                    "engines": json.dumps(latest["allowed_engines"]),
                    "workspaces": json.dumps(latest["allowed_workspaces"]),
                },
            )
            rotated = await self._fetch_conn(conn, credential_id)
        await self.audit(
            tenant_id=tenant_id,
            action="rotated",
            credential_ref=credential_ref,
            credential_id=credential_id,
            actor=actor,
        )
        assert rotated is not None
        return rotated

    async def revoke(
        self, *, credential_ref: UUID, tenant_id: str, actor: str | None = None
    ) -> ExecutionCredentialRecord | None:
        async with self._engine.begin() as conn:
            latest = (
                (
                    await conn.execute(
                        text("""SELECT * FROM execution_credentials
                        WHERE credential_ref=:ref AND tenant_id=:tenant
                        ORDER BY version DESC LIMIT 1 FOR UPDATE"""),
                        {"ref": credential_ref, "tenant": tenant_id},
                    )
                )
                .mappings()
                .first()
            )
            if latest is None:
                return None
            now = datetime.now(UTC)
            await conn.execute(
                text("""UPDATE execution_credentials
                SET status='revoked',revoked_at=:now,updated_at=:now
                WHERE credential_ref=:ref AND tenant_id=:tenant"""),
                {"ref": credential_ref, "tenant": tenant_id, "now": now},
            )
            await conn.execute(
                text("""UPDATE execution_credential_grants SET revoked_at=:now
                WHERE tenant_id=:tenant AND revoked_at IS NULL
                  AND credential_id IN (
                    SELECT id FROM execution_credentials
                    WHERE credential_ref=:ref AND tenant_id=:tenant)"""),
                {"ref": credential_ref, "tenant": tenant_id, "now": now},
            )
            record = await self._fetch_conn(conn, latest["id"])
        await self.audit(
            tenant_id=tenant_id,
            action="revoked",
            credential_ref=credential_ref,
            credential_id=latest["id"],
            actor=actor,
        )
        return record

    async def get(
        self, *, credential_ref: UUID, tenant_id: str, version: int | None = None
    ) -> ExecutionCredentialRecord | None:
        condition = "credential_ref=:ref AND tenant_id=:tenant"
        params: dict[str, object] = {"ref": credential_ref, "tenant": tenant_id}
        if version is not None:
            condition += " AND version=:version"
            params["version"] = version
        async with self._engine.connect() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            "SELECT * FROM execution_credentials WHERE "
                            + condition
                            + " ORDER BY version DESC LIMIT 1"
                        ),
                        params,
                    )
                )
                .mappings()
                .first()
            )
        return None if row is None else self._to_record(row)

    async def list(self, *, tenant_id: str) -> list[ExecutionCredentialRecord]:
        async with self._engine.connect() as conn:
            rows = (
                (
                    await conn.execute(
                        text("""SELECT * FROM execution_credentials
                        WHERE tenant_id=:tenant ORDER BY created_at,version"""),
                        {"tenant": tenant_id},
                    )
                )
                .mappings()
                .all()
            )
        return [self._to_record(row) for row in rows]

    async def _fetch_conn(self, conn, credential_id: UUID):
        row = (
            (
                await conn.execute(
                    text("SELECT * FROM execution_credentials WHERE id=:id"),
                    {"id": credential_id},
                )
            )
            .mappings()
            .first()
        )
        return None if row is None else self._to_record(row)

    @staticmethod
    def _to_record(row) -> ExecutionCredentialRecord:
        return ExecutionCredentialRecord(
            credential_id=row["id"],
            credential_ref=row["credential_ref"],
            tenant_id=row["tenant_id"],
            name=row["name"],
            credential_type=row["credential_type"],
            encrypted_secret=row["encrypted_secret"],
            key_version=row["key_version"],
            version=row["version"],
            status=row["status"],
            allowed_engines=tuple(row["allowed_engines"] or ()),
            allowed_workspaces=tuple(row["allowed_workspaces"] or ()),
            created_at=_aware(row["created_at"]),
            updated_at=_aware(row["updated_at"]),
            rotated_at=None if row["rotated_at"] is None else _aware(row["rotated_at"]),
            revoked_at=None if row["revoked_at"] is None else _aware(row["revoked_at"]),
        )
