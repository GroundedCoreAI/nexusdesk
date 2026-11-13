"""Application-scoped skill CRUD and deterministic safety evaluation."""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError

from agent_platform.core_platform.platform_services.persistence.store import (
    DomainError,
    audit,
    execute,
    many,
    one,
    required,
)
from agent_platform.core_platform.platform_services.tenant_isolation.service import (
    persisted_scope,
    scope_predicate,
)
from agent_platform.extension_contracts import BusinessScope

from .models import (
    ApplicationSkill,
    ApplicationSkillCreate,
    ApplicationSkillUpdate,
    IdempotencyMode,
    SkillType,
)


def _skill_public(row: dict[str, Any]) -> dict[str, Any]:
    config = row.get("config") or {}
    result = {
        "id": row["id"],
        "application_id": row["application_id"],
        "key": row["skill_key"],
        "type": row["type"],
        "name": row["name"],
        "description": row["description"],
        "enabled": row["enabled"],
        "connection_id": row.get("connection_id"),
        "connection_key": row.get("connection_key"),
        "revision": row["revision"],
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }
    result.update(config)
    return result


def _skill_config(
    body: ApplicationSkillCreate | ApplicationSkillUpdate,
) -> dict[str, Any]:
    return body.model_dump(
        mode="json",
        exclude={
            "key",
            "type",
            "name",
            "description",
            "enabled",
            "connection_key",
            "revision",
        },
    )


class SkillSafetyDecision(dict):
    """Small serializable result returned by deterministic skill evaluation."""


def evaluate_skill_safety(
    skill: ApplicationSkill | dict[str, Any],
    *,
    arguments: dict[str, Any] | None = None,
    actor_role: str | None = None,
    amount: Decimal | str | float | None = None,
    idempotency_key: str | None = None,
    confirmed: bool = False,
) -> SkillSafetyDecision:
    """Evaluate the non-negotiable safety fields before external execution.

    A malformed amount or an impossible rule evaluation yields
    ``rule_evaluation_failed`` rather than allowing the call.
    """

    current = (
        skill if isinstance(skill, ApplicationSkill) else ApplicationSkill.model_validate(skill)
    )
    safety = current.safety
    data = arguments or {}
    if safety.allowed_roles and (not actor_role or actor_role not in safety.allowed_roles):
        return SkillSafetyDecision(
            allowed=False,
            disposition="deny",
            code="rule_role_denied",
        )
    if safety.max_amount is not None:
        candidate = amount
        if candidate is None:
            candidate = data.get("amount")
        if candidate is None:
            return SkillSafetyDecision(
                allowed=False,
                disposition="deny",
                code="rule_amount_required",
            )
        try:
            amount_value = Decimal(str(candidate))
        except (InvalidOperation, ValueError):
            return SkillSafetyDecision(
                allowed=False,
                disposition="deny",
                code="rule_evaluation_failed",
            )
        if not amount_value.is_finite() or amount_value > safety.max_amount:
            return SkillSafetyDecision(
                allowed=False,
                disposition="deny",
                code="rule_amount_exceeded",
            )
    if safety.idempotency == IdempotencyMode.REQUIRED and not idempotency_key:
        return SkillSafetyDecision(
            allowed=False,
            disposition="deny",
            code="rule_idempotency_key_required",
        )
    if (
        current.type == SkillType.ACTION
        and current.write_operation
        and safety.requires_confirmation
        and not confirmed
    ):
        return SkillSafetyDecision(
            allowed=False,
            disposition="require_confirmation",
            code="rule_confirmation_required",
        )
    return SkillSafetyDecision(
        allowed=True,
        disposition="allow",
        code="rule_allow",
        timeout_seconds=min(safety.timeout_seconds, 60),
        on_error=safety.on_error.value,
    )


class ApplicationSkillService:
    """CRUD and release-readiness metadata for application skills."""

    def __init__(self, engine: object) -> None:
        self.engine = engine

    @staticmethod
    def _scope(
        tenant: str, scope: BusinessScope | None
    ) -> tuple[BusinessScope, str, dict[str, str]]:
        resolved = persisted_scope(tenant, scope)
        scope_sql, scope_params = scope_predicate(resolved)
        return resolved, scope_sql, scope_params

    async def _application(
        self,
        connection: Any,
        tenant: str,
        key: str,
        scope: BusinessScope | None,
        *,
        lock: bool = False,
    ) -> dict[str, Any]:
        resolved, scope_sql, scope_params = self._scope(tenant, scope)
        row = required(
            await one(
                connection,
                f"""
SELECT id,application_key,immutable,origin,draft_revision,published_version
FROM service_applications
WHERE tenant_id=:tenant
  AND {scope_sql}
  AND application_key=:key
  AND NOT archived
{"FOR UPDATE" if lock else ""}
""",
                tenant=tenant,
                key=key,
                **scope_params,
            ),
            "service_application_not_found",
        )
        row["scope"] = resolved
        return row

    @staticmethod
    def _assert_mutable(application: dict[str, Any]) -> None:
        if application["immutable"] or application["origin"] == "example":
            raise DomainError("service_application_example_immutable", 403)

    async def _connection(
        self,
        connection: Any,
        tenant: str,
        application: dict[str, Any],
        connection_key: str,
    ) -> dict[str, Any]:
        row = required(
            await one(
                connection,
                """
SELECT c.id,c.connection_key,c.auth_kind,c.revision,
       cred.id IS NOT NULL AS credentials_configured
FROM service_application_connections c
LEFT JOIN service_application_connection_credentials cred
  ON cred.connection_id=c.id
 AND cred.tenant_id=c.tenant_id
 AND cred.business_id=c.business_id
 AND cred.workspace_id=c.workspace_id
WHERE c.tenant_id=:tenant
  AND c.business_id=:business
  AND c.workspace_id=:workspace
  AND c.application_id=:application_id
  AND c.connection_key=:key
""",
                tenant=tenant,
                business=application["scope"].business_id,
                workspace=application["scope"].workspace_id,
                application_id=application["id"],
                key=connection_key,
            ),
            "service_application_connection_not_found",
        )
        return row

    async def _get_row(
        self,
        connection: Any,
        tenant: str,
        application: dict[str, Any],
        skill_key: str,
        *,
        lock: bool = False,
    ) -> dict[str, Any]:
        return required(
            await one(
                connection,
                f"""
SELECT s.*,c.connection_key
FROM service_application_skills s
LEFT JOIN service_application_connections c
  ON c.id=s.connection_id
 AND c.tenant_id=s.tenant_id
 AND c.business_id=s.business_id
 AND c.workspace_id=s.workspace_id
WHERE s.tenant_id=:tenant
  AND s.business_id=:business
  AND s.workspace_id=:workspace
  AND s.application_id=:application_id
  AND s.skill_key=:key
{"FOR UPDATE" if lock else ""}
""",
                tenant=tenant,
                business=application["scope"].business_id,
                workspace=application["scope"].workspace_id,
                application_id=application["id"],
                key=skill_key,
            ),
            "service_application_skill_not_found",
        )

    async def list(
        self,
        tenant: str,
        application_key: str,
        *,
        q: str = "",
        scope: BusinessScope | None = None,
    ) -> list[dict[str, Any]]:
        async with self.engine.connect() as connection:
            application = await self._application(connection, tenant, application_key, scope)
            rows = await many(
                connection,
                """
SELECT s.*,c.connection_key
FROM service_application_skills s
LEFT JOIN service_application_connections c
  ON c.id=s.connection_id
 AND c.tenant_id=s.tenant_id
 AND c.business_id=s.business_id
 AND c.workspace_id=s.workspace_id
WHERE s.tenant_id=:tenant
  AND s.business_id=:business
  AND s.workspace_id=:workspace
  AND s.application_id=:application_id
  AND (
      :q=''
      OR s.name ILIKE :pattern
      OR s.skill_key ILIKE :pattern
      OR s.description ILIKE :pattern
  )
ORDER BY s.type,s.name,s.skill_key
""",
                tenant=tenant,
                business=application["scope"].business_id,
                workspace=application["scope"].workspace_id,
                application_id=application["id"],
                q=q,
                pattern=f"%{q}%",
            )
            return [_skill_public(row) for row in rows]

    async def get(
        self,
        tenant: str,
        application_key: str,
        skill_key: str,
        *,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        async with self.engine.connect() as connection:
            application = await self._application(connection, tenant, application_key, scope)
            row = await self._get_row(connection, tenant, application, skill_key)
        return _skill_public(row)

    async def create(
        self,
        tenant: str,
        actor: str,
        application_key: str,
        body: ApplicationSkillCreate | dict[str, Any],
        *,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        validated = (
            body
            if isinstance(body, ApplicationSkillCreate)
            else ApplicationSkillCreate.model_validate(body)
        )
        async with self.engine.begin() as connection:
            application = await self._application(
                connection, tenant, application_key, scope, lock=True
            )
            self._assert_mutable(application)
            connection_row = None
            if validated.connection_key is not None:
                connection_row = await self._connection(
                    connection,
                    tenant,
                    application,
                    validated.connection_key,
                )
            duplicate = await one(
                connection,
                """
SELECT id FROM service_application_skills
WHERE tenant_id=:tenant
  AND business_id=:business
  AND workspace_id=:workspace
  AND application_id=:application_id
  AND skill_key=:key
""",
                tenant=tenant,
                business=application["scope"].business_id,
                workspace=application["scope"].workspace_id,
                application_id=application["id"],
                key=validated.key,
            )
            if duplicate is not None:
                raise DomainError("service_application_skill_key_conflict", 409)
            skill_id = uuid4()
            try:
                await execute(
                    connection,
                    """
INSERT INTO service_application_skills(
    id,tenant_id,business_id,workspace_id,application_id,skill_key,type,name,
    description,enabled,connection_id,config,revision,created_by,updated_by
) VALUES(
    :id,:tenant,:business,:workspace,:application_id,:key,:type,:name,
    :description,:enabled,:connection_id,CAST(:config AS jsonb),1,:actor,:actor
)
""",
                    id=skill_id,
                    tenant=tenant,
                    business=application["scope"].business_id,
                    workspace=application["scope"].workspace_id,
                    application_id=application["id"],
                    key=validated.key,
                    type=validated.type.value,
                    name=validated.name,
                    description=validated.description,
                    enabled=validated.enabled,
                    connection_id=connection_row["id"] if connection_row else None,
                    config=json.dumps(_skill_config(validated)),
                    actor=actor,
                )
            except IntegrityError:
                raise DomainError("service_application_skill_key_conflict", 409) from None
            await audit(
                connection,
                tenant,
                actor,
                "service_application.skill.created",
                skill_id,
                application_id=application["id"],
                key=validated.key,
                type=validated.type.value,
                connection_key=validated.connection_key,
                write_operation=validated.write_operation,
            )
            await execute(
                connection,
                """
UPDATE service_applications
SET draft_revision=draft_revision+1,
    updated_by=:actor,
    updated_at=now()
WHERE id=:application_id
""",
                actor=actor,
                application_id=application["id"],
            )
        return await self.get(tenant, application_key, validated.key, scope=application["scope"])

    async def update(
        self,
        tenant: str,
        actor: str,
        application_key: str,
        skill_key: str,
        body: ApplicationSkillUpdate | dict[str, Any],
        *,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        validated = (
            body
            if isinstance(body, ApplicationSkillUpdate)
            else ApplicationSkillUpdate.model_validate(body)
        )
        async with self.engine.begin() as connection:
            application = await self._application(
                connection, tenant, application_key, scope, lock=True
            )
            self._assert_mutable(application)
            existing = await self._get_row(connection, tenant, application, skill_key, lock=True)
            if existing["revision"] != validated.revision:
                raise DomainError("service_application_skill_revision_conflict", 409)
            connection_row = None
            if validated.connection_key is not None:
                connection_row = await self._connection(
                    connection,
                    tenant,
                    application,
                    validated.connection_key,
                )
            await execute(
                connection,
                """
UPDATE service_application_skills
SET type=:type,
    name=:name,
    description=:description,
    enabled=:enabled,
    connection_id=:connection_id,
    config=CAST(:config AS jsonb),
    revision=revision+1,
    updated_by=:actor,
    updated_at=now()
WHERE id=:id
""",
                id=existing["id"],
                type=validated.type.value,
                name=validated.name,
                description=validated.description,
                enabled=validated.enabled,
                connection_id=connection_row["id"] if connection_row else None,
                config=json.dumps(_skill_config(validated)),
                actor=actor,
            )
            await audit(
                connection,
                tenant,
                actor,
                "service_application.skill.updated",
                existing["id"],
                application_id=application["id"],
                key=skill_key,
                type=validated.type.value,
                revision=validated.revision + 1,
                connection_key=validated.connection_key,
            )
            await execute(
                connection,
                """
UPDATE service_applications
SET draft_revision=draft_revision+1,
    updated_by=:actor,
    updated_at=now()
WHERE id=:application_id
""",
                actor=actor,
                application_id=application["id"],
            )
        return await self.get(tenant, application_key, skill_key, scope=application["scope"])

    async def set_enabled(
        self,
        tenant: str,
        actor: str,
        application_key: str,
        skill_key: str,
        enabled: bool,
        revision: int,
        *,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        async with self.engine.begin() as connection:
            application = await self._application(
                connection, tenant, application_key, scope, lock=True
            )
            self._assert_mutable(application)
            existing = await self._get_row(connection, tenant, application, skill_key, lock=True)
            if existing["revision"] != revision:
                raise DomainError("service_application_skill_revision_conflict", 409)
            await execute(
                connection,
                """
UPDATE service_application_skills
SET enabled=:enabled,
    revision=revision+1,
    updated_by=:actor,
    updated_at=now()
WHERE id=:id
""",
                id=existing["id"],
                enabled=enabled,
                actor=actor,
            )
            await audit(
                connection,
                tenant,
                actor,
                "service_application.skill.enabled_changed",
                existing["id"],
                application_id=application["id"],
                key=skill_key,
                enabled=enabled,
                revision=revision + 1,
            )
            await execute(
                connection,
                """
UPDATE service_applications
SET draft_revision=draft_revision+1,
    updated_by=:actor,
    updated_at=now()
WHERE id=:application_id
""",
                actor=actor,
                application_id=application["id"],
            )
        return await self.get(tenant, application_key, skill_key, scope=application["scope"])

    async def delete(
        self,
        tenant: str,
        actor: str,
        application_key: str,
        skill_key: str,
        *,
        scope: BusinessScope | None = None,
    ) -> None:
        async with self.engine.begin() as connection:
            application = await self._application(
                connection, tenant, application_key, scope, lock=True
            )
            self._assert_mutable(application)
            existing = await self._get_row(connection, tenant, application, skill_key, lock=True)
            await execute(
                connection,
                "DELETE FROM service_application_skills WHERE id=:id",
                id=existing["id"],
            )
            await audit(
                connection,
                tenant,
                actor,
                "service_application.skill.deleted",
                existing["id"],
                application_id=application["id"],
                key=skill_key,
            )
            await execute(
                connection,
                """
UPDATE service_applications
SET draft_revision=draft_revision+1,
    updated_by=:actor,
    updated_at=now()
WHERE id=:application_id
""",
                actor=actor,
                application_id=application["id"],
            )

    async def release_metadata(
        self,
        connection: Any,
        tenant: str,
        application_id: UUID,
        business_id: str,
        workspace_id: str,
    ) -> list[dict[str, Any]]:
        """Return skills plus connection/auth facts for pure release checks."""

        rows = await many(
            connection,
            """
SELECT s.*,c.connection_key,c.auth_kind AS connection_auth_kind,
       cred.id IS NOT NULL AS credentials_configured
FROM service_application_skills s
LEFT JOIN service_application_connections c
  ON c.id=s.connection_id
 AND c.tenant_id=s.tenant_id
 AND c.business_id=s.business_id
 AND c.workspace_id=s.workspace_id
LEFT JOIN service_application_connection_credentials cred
  ON cred.connection_id=c.id
 AND cred.tenant_id=c.tenant_id
 AND cred.business_id=c.business_id
 AND cred.workspace_id=c.workspace_id
WHERE s.tenant_id=:tenant
  AND s.business_id=:business
  AND s.workspace_id=:workspace
  AND s.application_id=:application_id
ORDER BY s.skill_key
""",
            tenant=tenant,
            business=business_id,
            workspace=workspace_id,
            application_id=application_id,
        )
        return rows


ServiceApplicationSkillService = ApplicationSkillService


__all__ = [
    "ApplicationSkillService",
    "ServiceApplicationSkillService",
    "SkillSafetyDecision",
    "evaluate_skill_safety",
]
