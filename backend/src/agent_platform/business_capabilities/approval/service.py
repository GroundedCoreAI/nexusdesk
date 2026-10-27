"""Tenant-scoped persistence and application operations for approvals."""

import hashlib
import json
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from agent_platform.core_platform.platform_services.persistence.store import (
    DomainError,
    audit,
    many,
    one,
    required,
)
from agent_platform.extension_contracts import EventEnvelope, EventPublisher


class ApprovalService:
    """Persist approval requests while keeping domain rules explicit."""

    def __init__(self, engine, events: EventPublisher | None = None) -> None:
        self.engine = engine
        self.events = events

    @staticmethod
    def _fingerprint(title: str, description: str) -> str:
        payload = json.dumps(
            {"description": description, "title": title},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    async def create(
        self,
        tenant: str,
        actor: str,
        title: str,
        description: str,
        idempotency_key: str | None = None,
    ) -> dict[str, object]:
        fingerprint = self._fingerprint(title, description)
        async with self.engine.begin() as connection:
            existing = None
            if idempotency_key:
                existing = await one(
                    connection,
                    "SELECT * FROM approval_requests "
                    "WHERE tenant_id=:tenant AND idempotency_key=:key",
                    tenant=tenant,
                    key=idempotency_key,
                )
                if existing is not None:
                    if existing["request_fingerprint"] != fingerprint:
                        raise DomainError("approval_idempotency_conflict", 409)
                    return existing

            row = await one(
                connection,
                """
                INSERT INTO approval_requests
                    (tenant_id,title,description,requested_by,status,revision,
                     idempotency_key,request_fingerprint)
                VALUES
                    (:tenant,:title,:description,:actor,'pending',1,
                     :idempotency_key,:fingerprint)
                ON CONFLICT (tenant_id,idempotency_key) DO NOTHING
                RETURNING *
                """,
                tenant=tenant,
                title=title,
                description=description,
                actor=actor,
                idempotency_key=idempotency_key,
                fingerprint=fingerprint,
            )
            if row is None and idempotency_key:
                row = await one(
                    connection,
                    "SELECT * FROM approval_requests "
                    "WHERE tenant_id=:tenant AND idempotency_key=:key",
                    tenant=tenant,
                    key=idempotency_key,
                )
                if row is None:
                    raise DomainError("approval_create_failed", 503)
                if row["request_fingerprint"] != fingerprint:
                    raise DomainError("approval_idempotency_conflict", 409)
            if row is None:
                raise DomainError("approval_create_failed", 503)
            await audit(
                connection,
                tenant,
                actor,
                "approval.requested",
                row["id"],
                status=row["status"],
                revision=row["revision"],
            )

        await self._publish(
            "approval.requested",
            tenant,
            row,
            {"requested_by": actor, "revision": row["revision"]},
        )
        return row

    async def get(self, tenant: str, approval_id: UUID) -> dict[str, object]:
        async with self.engine.connect() as connection:
            return required(
                await one(
                    connection,
                    "SELECT * FROM approval_requests WHERE id=:id AND tenant_id=:tenant",
                    id=approval_id,
                    tenant=tenant,
                )
            )

    async def list(
        self,
        tenant: str,
        status: Literal["all", "draft", "pending", "approved", "rejected", "cancelled"] = "all",
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, object]:
        where = "tenant_id=:tenant"
        params: dict[str, object] = {"tenant": tenant}
        if status != "all":
            where += " AND status=:status"
            params["status"] = status
        async with self.engine.connect() as connection:
            total = await one(
                connection,
                f"SELECT count(*)::int AS total FROM approval_requests WHERE {where}",
                **params,
            )
            items = await many(
                connection,
                f"""
                SELECT * FROM approval_requests
                WHERE {where}
                ORDER BY created_at DESC,id DESC
                LIMIT :limit OFFSET :offset
                """,
                **params,
                limit=page_size,
                offset=(page - 1) * page_size,
            )
        return {"items": items, "total": total["total"], "page": page, "page_size": page_size}

    async def audit(
        self,
        tenant: str,
        approval_id: UUID,
        limit: int = 100,
    ) -> dict[str, object]:
        """Return the tenant-scoped operation history for one approval."""

        await self.get(tenant, approval_id)
        async with self.engine.connect() as connection:
            items = await many(
                connection,
                """
                SELECT id,actor,action,resource,details,ip,created_at
                FROM audit_records
                WHERE tenant_id=:tenant AND resource=:resource
                  AND action LIKE 'approval.%'
                ORDER BY id ASC
                LIMIT :limit
                """,
                tenant=tenant,
                resource=str(approval_id),
                limit=limit,
            )
        return {"items": items, "approval_id": str(approval_id)}

    async def decide(
        self,
        tenant: str,
        actor: str,
        approval_id: UUID,
        decision: Literal["approve", "reject"],
        revision: int,
    ) -> dict[str, object]:
        next_status = "approved" if decision == "approve" else "rejected"
        now = datetime.now(UTC)
        async with self.engine.begin() as connection:
            row = required(
                await one(
                    connection,
                    "SELECT * FROM approval_requests WHERE id=:id AND tenant_id=:tenant FOR UPDATE",
                    id=approval_id,
                    tenant=tenant,
                )
            )
            if row["revision"] != revision:
                raise DomainError("approval_revision_conflict", 409)
            if row["status"] != "pending":
                raise DomainError("approval_not_pending", 409)
            if row["requested_by"] == actor:
                raise DomainError("approval_separation_of_duties", 403)
            result = await one(
                connection,
                """
                UPDATE approval_requests
                SET status=:status,revision=revision+1,decision_by=:actor,
                    decided_at=:now,updated_at=:now
                WHERE id=:id AND tenant_id=:tenant AND status='pending'
                  AND revision=:revision
                RETURNING *
                """,
                status=next_status,
                actor=actor,
                now=now,
                id=approval_id,
                tenant=tenant,
                revision=revision,
            )
            if result is None:
                raise DomainError("approval_revision_conflict", 409)
            await audit(
                connection,
                tenant,
                actor,
                f"approval.{next_status}",
                approval_id,
                status=next_status,
                revision=result["revision"],
            )

        await self._publish(
            f"approval.{next_status}",
            tenant,
            result,
            {"decision_by": actor, "revision": result["revision"]},
        )
        return result

    async def cancel(
        self,
        tenant: str,
        actor: str,
        approval_id: UUID,
        revision: int,
    ) -> dict[str, object]:
        async with self.engine.begin() as connection:
            row = required(
                await one(
                    connection,
                    "SELECT * FROM approval_requests WHERE id=:id AND tenant_id=:tenant FOR UPDATE",
                    id=approval_id,
                    tenant=tenant,
                )
            )
            if row["revision"] != revision:
                raise DomainError("approval_revision_conflict", 409)
            if row["status"] not in {"draft", "pending"}:
                raise DomainError("approval_not_cancellable", 409)
            if row["requested_by"] != actor:
                raise DomainError("approval_cancel_forbidden", 403)
            result = await one(
                connection,
                """
                UPDATE approval_requests
                SET status='cancelled',revision=revision+1,updated_at=now()
                WHERE id=:id AND tenant_id=:tenant AND revision=:revision
                RETURNING *
                """,
                id=approval_id,
                tenant=tenant,
                revision=revision,
            )
            if result is None:
                raise DomainError("approval_revision_conflict", 409)
            await audit(
                connection,
                tenant,
                actor,
                "approval.cancelled",
                approval_id,
                status="cancelled",
                revision=result["revision"],
            )

        await self._publish(
            "approval.cancelled",
            tenant,
            result,
            {"cancelled_by": actor, "revision": result["revision"]},
        )
        return result

    async def _publish(
        self,
        event_type: str,
        tenant: str,
        row: dict[str, object],
        payload: dict[str, object],
    ) -> None:
        if self.events is None:
            return
        await self.events.publish(
            EventEnvelope(
                event_type=event_type,
                tenant_id=tenant,
                aggregate_type="approval",
                aggregate_id=str(row["id"]),
                payload=payload,
                idempotency_key=f"{event_type}:{tenant}:{row['id']}:{row['revision']}",
            )
        )
