"""Persistence and availability checks for provider descriptors."""

from __future__ import annotations

import json
from typing import Any

from agent_platform.core_platform.platform_services.persistence.store import (
    DomainError,
    audit,
    many,
    one,
    required,
)
from agent_platform.core_platform.platform_services.tenant_isolation.service import (
    persisted_scope,
    scope_predicate,
)
from agent_platform.extension_contracts import BusinessScope

from .executors import validate_executors
from .models import (
    ProviderInput,
    ProviderKind,
    ProviderRecord,
    ProviderRequirement,
    ProviderUpdateInput,
    provider_identity,
)


def _public(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "key": row["provider_key"],
        "kind": row["kind"],
        "name": row["name"],
        "description": row["description"],
        "enabled": row["enabled"],
        "config": row["config"],
        "source": row["source"],
        "source_ref": row.get("source_ref"),
        "revision": row["revision"],
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


class ServiceProviderRegistry:
    """Tenant-scoped catalog of object, tool and human-queue descriptors."""

    def __init__(self, engine: object) -> None:
        self.engine = engine

    async def list(
        self,
        tenant: str,
        *,
        kind: ProviderKind | None = None,
        q: str = "",
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        resolved = persisted_scope(tenant, scope)
        scope_sql, scope_params = scope_predicate(resolved, alias="p")
        async with self.engine.connect() as connection:
            rows = await many(
                connection,
                f"""
SELECT p.*
FROM service_provider_registry p
WHERE p.tenant_id=:tenant
  AND {scope_sql}
  AND (CAST(:kind AS text) IS NULL OR p.kind=CAST(:kind AS text))
  AND (
      CAST(:q AS text)=''
      OR p.provider_key ILIKE CAST(:pattern AS text)
      OR p.name ILIKE CAST(:pattern AS text)
      OR p.description ILIKE CAST(:pattern AS text)
  )
ORDER BY p.kind,p.name,p.provider_key
""",
                tenant=tenant,
                kind=kind.value if kind else None,
                q=q,
                pattern=f"%{q}%",
                **scope_params,
            )
        items = [ProviderRecord.model_validate(_public(row)) for row in rows]
        return {"items": [item.model_dump(mode="json") for item in items], "total": len(items)}

    async def get(
        self,
        tenant: str,
        kind: ProviderKind,
        key: str,
        *,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        resolved = persisted_scope(tenant, scope)
        scope_sql, scope_params = scope_predicate(resolved, alias="p")
        async with self.engine.connect() as connection:
            row = required(
                await one(
                    connection,
                    f"""
SELECT p.* FROM service_provider_registry p
WHERE p.tenant_id=:tenant AND {scope_sql}
  AND p.kind=:kind AND p.provider_key=:key
""",
                    tenant=tenant,
                    kind=kind.value,
                    key=key,
                    **scope_params,
                ),
                "service_provider_not_found",
            )
        return ProviderRecord.model_validate(_public(row)).model_dump(mode="json")

    async def create(
        self,
        tenant: str,
        actor: str,
        body: ProviderInput,
        *,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        if body.kind in {ProviderKind.OBJECT, ProviderKind.TOOL}:
            validate_executors(body.config)
        resolved = persisted_scope(tenant, scope)
        _, scope_params = scope_predicate(resolved, alias="p")
        async with self.engine.begin() as connection:
            row = await one(
                connection,
                """
INSERT INTO service_provider_registry(
    tenant_id,business_id,workspace_id,provider_key,kind,name,description,
    enabled,config,source,source_ref,revision,created_by,updated_by
) VALUES(
    :tenant,:scope_business,:scope_workspace,:key,:kind,:name,:description,
    :enabled,CAST(:config AS jsonb),'manual',NULL,1,:actor,:actor
)
ON CONFLICT(tenant_id,business_id,workspace_id,kind,provider_key) DO NOTHING
RETURNING *
""",
                tenant=tenant,
                key=body.key,
                kind=body.kind.value,
                name=body.name,
                description=body.description,
                enabled=body.enabled,
                config=_json(body.config),
                actor=actor,
                **scope_params,
            )
            if row is None:
                raise DomainError("service_provider_conflict", 409)
            await audit(
                connection,
                tenant,
                actor,
                "service_provider.created",
                row["id"],
                key=body.key,
                kind=body.kind.value,
                revision=row["revision"],
            )
        return ProviderRecord.model_validate(_public(row)).model_dump(mode="json")

    async def update(
        self,
        tenant: str,
        actor: str,
        kind: ProviderKind,
        key: str,
        body: ProviderUpdateInput,
        *,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        if body.kind != kind or body.key != key:
            raise DomainError("service_provider_identity_immutable", 422)
        if kind in {ProviderKind.OBJECT, ProviderKind.TOOL}:
            validate_executors(body.config)
        resolved = persisted_scope(tenant, scope)
        scope_sql, scope_params = scope_predicate(resolved, alias="p")
        async with self.engine.begin() as connection:
            row = await one(
                connection,
                f"""
UPDATE service_provider_registry p
SET name=:name,description=:description,enabled=:enabled,
    config=CAST(:config AS jsonb),revision=p.revision+1,
    updated_by=:actor,updated_at=now()
WHERE p.tenant_id=:tenant AND {scope_sql}
  AND p.kind=:kind AND p.provider_key=:key AND p.revision=:revision
RETURNING p.*
""",
                tenant=tenant,
                kind=kind.value,
                key=key,
                name=body.name,
                description=body.description,
                enabled=body.enabled,
                config=_json(body.config),
                revision=body.revision,
                actor=actor,
                **scope_params,
            )
            if row is None:
                raise DomainError("service_provider_missing_or_revision_conflict", 409)
            await audit(
                connection,
                tenant,
                actor,
                "service_provider.updated",
                row["id"],
                key=key,
                kind=kind.value,
                revision=row["revision"],
            )
        return ProviderRecord.model_validate(_public(row)).model_dump(mode="json")

    async def available_identities(
        self,
        connection: Any,
        tenant: str,
        scope: BusinessScope,
    ) -> set[str]:
        scope_sql, scope_params = scope_predicate(scope, alias="p")
        rows = await many(
            connection,
            f"""
SELECT p.kind,p.provider_key
FROM service_provider_registry p
WHERE p.tenant_id=:tenant AND {scope_sql} AND p.enabled
""",
            tenant=tenant,
            **scope_params,
        )
        return {provider_identity(row["kind"], row["provider_key"]) for row in rows}

    async def ensure_requirements(
        self,
        connection: Any,
        tenant: str,
        actor: str,
        scope: BusinessScope,
        requirements: list[ProviderRequirement],
    ) -> None:
        """Create disabled placeholders without overwriting an operator's entry."""

        _, scope_params = scope_predicate(scope, alias="p")
        for requirement in requirements:
            await one(
                connection,
                """
INSERT INTO service_provider_registry(
    tenant_id,business_id,workspace_id,provider_key,kind,name,description,
    enabled,config,source,source_ref,revision,created_by,updated_by
) VALUES(
    :tenant,:scope_business,:scope_workspace,:key,:kind,:name,'',
    false,'{}'::jsonb,:source,:source_ref,1,:actor,:actor
)
ON CONFLICT(tenant_id,business_id,workspace_id,kind,provider_key) DO NOTHING
RETURNING id
""",
                tenant=tenant,
                key=requirement.key,
                kind=requirement.kind.value,
                name=requirement.name,
                source=requirement.source,
                source_ref=requirement.source_ref,
                actor=actor,
                **scope_params,
            )


def _json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


__all__ = ["ServiceProviderRegistry"]
