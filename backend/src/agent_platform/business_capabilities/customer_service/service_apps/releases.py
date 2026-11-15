"""Immutable v2 application releases, readiness, rollback and traces."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import Field

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
    ApplicationChannelReference,
    ApplicationConnectionCreate,
    ApplicationRules,
    ApplicationSkill,
    ApplicationTrace,
    ApplicationTraceInput,
    AuthKind,
    PageRequest,
    ReleaseAgent,
    ReleaseConnection,
    ReleaseSnapshot,
    ServiceApplicationModel,
    ServiceApplicationVersion,
    ServiceExperienceConfig,
    SkillType,
)
from .skills import ApplicationSkillService


class ReadinessStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    WARNING = "warning"


class ReadinessCheck(ServiceApplicationModel):
    code: str = Field(min_length=1, max_length=100)
    status: ReadinessStatus
    message: str = Field(min_length=1, max_length=500)
    resource: str | None = Field(default=None, max_length=200)


class ReleaseReadiness(ServiceApplicationModel):
    ready: bool
    checks: list[ReadinessCheck] = Field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        return {
            status.value: sum(check.status == status for check in self.checks)
            for status in ReadinessStatus
        }


def canonical_json(value: Any) -> str:
    """Serialize semantically identical JSON objects to the same byte string."""

    if isinstance(value, ServiceApplicationModel):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def canonical_digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode()).hexdigest()


def snapshot_digest(snapshot: ReleaseSnapshot | dict[str, Any]) -> str:
    payload = (
        snapshot.model_dump(mode="json")
        if isinstance(snapshot, ReleaseSnapshot)
        else dict(snapshot)
    )
    payload.pop("digest", None)
    return canonical_digest(payload)


class ApplicationReleaseService:
    """Readiness, append-only publication history and rollback."""

    def __init__(self, engine: object, skills: ApplicationSkillService) -> None:
        self.engine = engine
        self.skills = skills

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
SELECT a.id,a.application_key,a.name,a.description,a.agent_id,
       a.agent_version,a.origin,a.immutable,a.status,a.draft,
       a.draft_revision,a.published_version,a.archived
FROM service_applications a
WHERE a.tenant_id=:tenant
  AND {scope_sql}
  AND a.application_key=:key
  AND NOT a.archived
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

    async def _validate_agent(
        self,
        connection: Any,
        tenant: str,
        application: dict[str, Any],
        agent_id: UUID,
        agent_version: int,
    ) -> tuple[bool, str]:
        row = await one(
            connection,
            """
SELECT a.archived,v.version
FROM agents a
LEFT JOIN agent_versions v
  ON v.agent_id=a.id
 AND v.version=:version
WHERE a.id=:agent_id
  AND a.tenant_id=:tenant
  AND a.business_id=:business
  AND a.workspace_id=:workspace
""",
            tenant=tenant,
            business=application["scope"].business_id,
            workspace=application["scope"].workspace_id,
            agent_id=agent_id,
            version=agent_version,
        )
        if not row:
            return False, "agent_not_found"
        if row["archived"]:
            return False, "agent_archived"
        if row["version"] is None:
            return False, "agent_version_not_found"
        return True, "pass"

    @staticmethod
    def _rules(application: dict[str, Any]) -> ApplicationRules:
        draft = application.get("draft") or {}
        raw = draft.get("rules") if isinstance(draft, dict) else None
        if raw is None:
            return ApplicationRules(handoff_queue="customer-service")
        return ApplicationRules.model_validate(raw)

    @staticmethod
    def _experience(application: dict[str, Any]) -> ServiceExperienceConfig:
        draft = application.get("draft") or {}
        raw = draft.get("experience") if isinstance(draft, dict) else None
        return ServiceExperienceConfig.model_validate(raw or {})

    async def _skill_rows(
        self,
        connection: Any,
        tenant: str,
        application: dict[str, Any],
    ) -> list[dict[str, Any]]:
        return await self.skills.release_metadata(
            connection,
            tenant,
            application["id"],
            application["scope"].business_id,
            application["scope"].workspace_id,
        )

    @staticmethod
    def _skill_from_row(row: dict[str, Any]) -> ApplicationSkill:
        payload = {
            "key": row["skill_key"],
            "type": row["type"],
            "name": row["name"],
            "description": row["description"],
            "enabled": row["enabled"],
            "connection_key": row.get("connection_key"),
            **(row.get("config") or {}),
        }
        return ApplicationSkill.model_validate(payload)

    async def _connection_rows(
        self,
        connection: Any,
        tenant: str,
        application: dict[str, Any],
    ) -> list[dict[str, Any]]:
        return await many(
            connection,
            """
SELECT c.*,cred.id AS credential_ref
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
ORDER BY c.connection_key
""",
            tenant=tenant,
            business=application["scope"].business_id,
            workspace=application["scope"].workspace_id,
            application_id=application["id"],
        )

    @staticmethod
    def _connection_from_row(row: dict[str, Any]) -> dict[str, Any]:
        public = {
            "key": row["connection_key"],
            "name": row["name"],
            "executor_kind": row["executor_kind"],
            "endpoint": row["endpoint"],
            "method": row["method"],
            "public_headers": row["public_headers"],
            "auth_kind": row["auth_kind"],
            "timeout_seconds": row["timeout_seconds"],
            "max_response_bytes": row["max_response_bytes"],
            "config": row["config"],
        }
        ApplicationConnectionCreate.model_validate(public)
        digest_payload = {
            **public,
            "revision": row["revision"],
        }
        return {
            **public,
            "credential_ref": row.get("credential_ref"),
            "revision": row["revision"],
            "digest": canonical_digest(digest_payload),
        }

    async def _channels(
        self,
        connection: Any,
        tenant: str,
        application: dict[str, Any],
    ) -> list[ApplicationChannelReference]:
        rows = await many(
            connection,
            """
SELECT id,provider
FROM channels
WHERE tenant_id=:tenant
  AND business_id=:business
  AND workspace_id=:workspace
  AND application_id=:application_id
ORDER BY id
""",
            tenant=tenant,
            business=application["scope"].business_id,
            workspace=application["scope"].workspace_id,
            application_id=application["id"],
        )
        return [
            ApplicationChannelReference(channel_id=row["id"], provider=row["provider"])
            for row in rows
        ]

    async def readiness(
        self,
        tenant: str,
        application_key: str,
        *,
        scope: BusinessScope | None = None,
        connection: Any | None = None,
    ) -> ReleaseReadiness:
        async def evaluate(conn: Any) -> ReleaseReadiness:
            application = await self._application(conn, tenant, application_key, scope)
            checks: list[ReadinessCheck] = []
            agent_ok, agent_code = await self._validate_agent(
                conn,
                tenant,
                application,
                application["agent_id"],
                application["agent_version"],
            )
            checks.append(
                ReadinessCheck(
                    code="agent_release_available",
                    status=ReadinessStatus.PASS if agent_ok else ReadinessStatus.FAIL,
                    message=(
                        "Bound Agent version is available"
                        if agent_ok
                        else f"Bound Agent/version is unavailable: {agent_code}"
                    ),
                    resource=str(application["agent_id"]),
                )
            )
            try:
                rules = self._rules(application)
                checks.append(
                    ReadinessCheck(
                        code="application_rules_valid",
                        status=ReadinessStatus.PASS,
                        message="Application fallback rules are valid",
                    )
                )
            except (ValueError, TypeError):
                checks.append(
                    ReadinessCheck(
                        code="application_rules_valid",
                        status=ReadinessStatus.FAIL,
                        message="Application fallback rules are invalid",
                    )
                )
                rules = None
            try:
                self._experience(application)
                checks.append(
                    ReadinessCheck(
                        code="application_experience_valid",
                        status=ReadinessStatus.PASS,
                        message="Customer experience configuration is valid",
                    )
                )
            except (ValueError, TypeError):
                checks.append(
                    ReadinessCheck(
                        code="application_experience_valid",
                        status=ReadinessStatus.FAIL,
                        message="Customer experience configuration is invalid",
                    )
                )
            skill_rows = await self._skill_rows(conn, tenant, application)
            for row in skill_rows:
                try:
                    skill = self._skill_from_row(row)
                except (ValueError, TypeError):
                    checks.append(
                        ReadinessCheck(
                            code="skill_contract_valid",
                            status=ReadinessStatus.FAIL,
                            message=f"Skill {row['skill_key']} has an invalid contract",
                            resource=row["skill_key"],
                        )
                    )
                    continue
                if not skill.enabled:
                    continue
                if skill.type in {SkillType.QUERY, SkillType.ACTION} and not row.get(
                    "connection_key"
                ):
                    checks.append(
                        ReadinessCheck(
                            code="skill_connection_available",
                            status=ReadinessStatus.FAIL,
                            message=(f"Skill {skill.key} requires an application connection"),
                            resource=skill.key,
                        )
                    )
                    continue
                if (
                    row.get("connection_auth_kind")
                    and row["connection_auth_kind"] != AuthKind.NONE.value
                    and not row.get("credentials_configured")
                ):
                    checks.append(
                        ReadinessCheck(
                            code="connection_credentials_configured",
                            status=ReadinessStatus.FAIL,
                            message=(f"Connection {row['connection_key']} has no credentials"),
                            resource=row["connection_key"],
                        )
                    )
                checks.append(
                    ReadinessCheck(
                        code="skill_contract_valid",
                        status=ReadinessStatus.PASS,
                        message=f"Skill {skill.key} is valid",
                        resource=skill.key,
                    )
                )
            if rules is not None:
                for row in skill_rows:
                    if (
                        row["enabled"]
                        and row["type"] == SkillType.HANDOFF.value
                        and rules.fallback == "handoff"
                        and not rules.handoff_queue
                    ):
                        checks.append(
                            ReadinessCheck(
                                code="handoff_queue_configured",
                                status=ReadinessStatus.FAIL,
                                message="Handoff fallback requires a queue",
                                resource=row["skill_key"],
                            )
                        )
            connection_rows = await self._connection_rows(conn, tenant, application)
            for row in connection_rows:
                try:
                    self._connection_from_row(row)
                except (ValueError, TypeError):
                    checks.append(
                        ReadinessCheck(
                            code="connection_contract_valid",
                            status=ReadinessStatus.FAIL,
                            message=(f"Connection {row['connection_key']} has an invalid contract"),
                            resource=row["connection_key"],
                        )
                    )
            ready = not any(check.status == ReadinessStatus.FAIL for check in checks)
            return ReleaseReadiness(ready=ready, checks=checks)

        if connection is not None:
            return await evaluate(connection)
        async with self.engine.connect() as conn:
            return await evaluate(conn)

    async def build_snapshot(
        self,
        connection: Any,
        tenant: str,
        application_key: str,
        *,
        scope: BusinessScope | None = None,
    ) -> ReleaseSnapshot:
        """Build one canonical immutable snapshot inside a caller transaction."""

        application = await self._application(
            connection,
            tenant,
            application_key,
            scope,
        )
        return await self._snapshot(connection, tenant, application)

    async def _snapshot(
        self,
        connection: Any,
        tenant: str,
        application: dict[str, Any],
        *,
        agent_id: UUID | None = None,
        agent_version: int | None = None,
    ) -> ReleaseSnapshot:
        release_agent = ReleaseAgent(
            id=agent_id or application["agent_id"],
            version=agent_version or application["agent_version"],
        )
        skills = [
            self._skill_from_row(row)
            for row in await self._skill_rows(connection, tenant, application)
        ]
        connections = [
            ReleaseConnection.model_validate(self._connection_from_row(row))
            for row in await self._connection_rows(connection, tenant, application)
        ]
        snapshot = ReleaseSnapshot(
            agent=release_agent,
            skills=skills,
            connections=connections,
            rules=self._rules(application),
            channels=await self._channels(connection, tenant, application),
            experience=self._experience(application),
            digest="sha256:" + "0" * 64,
        )
        digest = snapshot_digest(snapshot)
        return ReleaseSnapshot.model_validate(snapshot.model_dump(mode="json") | {"digest": digest})

    @staticmethod
    def _version_public(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "application_id": row["application_id"],
            "version": row["version"],
            "schema_version": row["schema_version"],
            "config": row["config"],
            "config_digest": row["config_digest"],
            "source_version": row["source_version"],
            "created_by": row["created_by"],
            "created_at": row["created_at"],
        }

    async def get_version(
        self,
        tenant: str,
        application_key: str,
        version: int,
        *,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        async with self.engine.connect() as connection:
            application = await self._application(connection, tenant, application_key, scope)
            row = required(
                await one(
                    connection,
                    """
SELECT id,application_id,version,schema_version,config,config_digest,
       source_version,created_by,created_at
FROM service_application_versions
WHERE tenant_id=:tenant
  AND business_id=:business
  AND workspace_id=:workspace
  AND application_id=:application_id
  AND version=:version
""",
                    tenant=tenant,
                    business=application["scope"].business_id,
                    workspace=application["scope"].workspace_id,
                    application_id=application["id"],
                    version=version,
                ),
                "service_application_version_not_found",
            )
        ServiceApplicationVersion.model_validate(row)
        return self._version_public(row)

    async def versions(
        self,
        tenant: str,
        application_key: str,
        *,
        page: int = 1,
        page_size: int = 10,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        request = PageRequest(page=page, page_size=page_size)
        async with self.engine.connect() as connection:
            application = await self._application(connection, tenant, application_key, scope)
            total = await one(
                connection,
                """
SELECT count(*)::int AS count
FROM service_application_versions
WHERE tenant_id=:tenant
  AND business_id=:business
  AND workspace_id=:workspace
  AND application_id=:application_id
""",
                tenant=tenant,
                business=application["scope"].business_id,
                workspace=application["scope"].workspace_id,
                application_id=application["id"],
            )
            rows = await many(
                connection,
                """
SELECT * FROM service_application_versions
WHERE tenant_id=:tenant
  AND business_id=:business
  AND workspace_id=:workspace
  AND application_id=:application_id
ORDER BY version DESC
LIMIT :limit OFFSET :offset
""",
                tenant=tenant,
                business=application["scope"].business_id,
                workspace=application["scope"].workspace_id,
                application_id=application["id"],
                limit=request.page_size,
                offset=request.offset,
            )
        return {
            "items": [self._version_public(row) for row in rows],
            "total": total["count"] if total else 0,
            "page": request.page,
            "page_size": request.page_size,
            "published_version": application["published_version"],
        }

    async def publish(
        self,
        tenant: str,
        actor: str,
        application_key: str,
        revision: int,
        *,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        async with self.engine.begin() as connection:
            application = await self._application(
                connection, tenant, application_key, scope, lock=True
            )
            self._assert_mutable(application)
            if application["draft_revision"] != revision:
                raise DomainError("service_application_revision_conflict", 409)
            readiness = await self.readiness(
                tenant,
                application_key,
                scope=application["scope"],
                connection=connection,
            )
            if not readiness.ready:
                raise DomainError("service_application_readiness_blocked", 409)
            snapshot = await self._snapshot(connection, tenant, application)
            next_version = (
                await one(
                    connection,
                    """
SELECT COALESCE(max(version),0)+1 AS version
FROM service_application_versions
WHERE tenant_id=:tenant
  AND business_id=:business
  AND workspace_id=:workspace
  AND application_id=:application_id
""",
                    tenant=tenant,
                    business=application["scope"].business_id,
                    workspace=application["scope"].workspace_id,
                    application_id=application["id"],
                )
            )["version"]
            version_id = uuid4()
            await execute(
                connection,
                """
INSERT INTO service_application_versions(
    id,tenant_id,business_id,workspace_id,application_id,version,schema_version,
    config,config_digest,source_version,created_by
) VALUES(
    :id,:tenant,:business,:workspace,:application_id,:version,'v2',
    CAST(:config AS jsonb),:digest,NULL,:actor
)
""",
                id=version_id,
                tenant=tenant,
                business=application["scope"].business_id,
                workspace=application["scope"].workspace_id,
                application_id=application["id"],
                version=next_version,
                config=json.dumps(snapshot.model_dump(mode="json"), ensure_ascii=False),
                digest=snapshot.digest,
                actor=actor,
            )
            await execute(
                connection,
                """
UPDATE service_applications
SET status='published',
    published_version=:version,
    updated_by=:actor,
    updated_at=now()
WHERE id=:application_id
""",
                version=next_version,
                actor=actor,
                application_id=application["id"],
            )
            await audit(
                connection,
                tenant,
                actor,
                "service_application.published",
                application["id"],
                key=application_key,
                version=next_version,
                config_digest=snapshot.digest,
            )
        return {
            "application_id": application["id"],
            "version": next_version,
            "config": snapshot.model_dump(mode="json"),
            "config_digest": snapshot.digest,
            "source_version": None,
            "revision": revision,
        }

    async def rollback(
        self,
        tenant: str,
        actor: str,
        application_key: str,
        target_version: int,
        revision: int,
        *,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        async with self.engine.begin() as connection:
            application = await self._application(
                connection, tenant, application_key, scope, lock=True
            )
            self._assert_mutable(application)
            if application["draft_revision"] != revision:
                raise DomainError("service_application_revision_conflict", 409)
            target = required(
                await one(
                    connection,
                    """
SELECT * FROM service_application_versions
WHERE tenant_id=:tenant
  AND business_id=:business
  AND workspace_id=:workspace
  AND application_id=:application_id
  AND version=:version
""",
                    tenant=tenant,
                    business=application["scope"].business_id,
                    workspace=application["scope"].workspace_id,
                    application_id=application["id"],
                    version=target_version,
                ),
                "service_application_version_not_found",
            )
            target_snapshot = ReleaseSnapshot.model_validate(target["config"])
            agent_ok, agent_code = await self._validate_agent(
                connection,
                tenant,
                application,
                target_snapshot.agent.id,
                target_snapshot.agent.version,
            )
            if not agent_ok:
                raise DomainError(f"service_application_rollback_{agent_code}", 409)
            connection_keys = {item.key: item for item in target_snapshot.connections}
            for skill in target_snapshot.skills:
                if not skill.enabled or skill.connection_key is None:
                    continue
                target_connection = connection_keys.get(skill.connection_key)
                if target_connection is None:
                    raise DomainError(
                        "service_application_rollback_connection_unavailable",
                        409,
                    )
                current = await one(
                    connection,
                    """
SELECT id,auth_kind FROM service_application_connections
WHERE tenant_id=:tenant
  AND business_id=:business
  AND workspace_id=:workspace
  AND application_id=:application_id
  AND connection_key=:key
""",
                    tenant=tenant,
                    business=application["scope"].business_id,
                    workspace=application["scope"].workspace_id,
                    application_id=application["id"],
                    key=skill.connection_key,
                )
                if not current:
                    raise DomainError(
                        "service_application_rollback_connection_unavailable",
                        409,
                    )
                if (
                    target_connection.auth_kind != AuthKind.NONE
                    and target_connection.credential_ref is None
                ):
                    raise DomainError(
                        "service_application_rollback_credentials_unavailable",
                        409,
                    )
                if target_connection.credential_ref is not None:
                    credential = await one(
                        connection,
                        """
SELECT id FROM service_application_connection_credentials
WHERE tenant_id=:tenant
  AND business_id=:business
  AND workspace_id=:workspace
  AND connection_id=:connection_id
""",
                        tenant=tenant,
                        business=application["scope"].business_id,
                        workspace=application["scope"].workspace_id,
                        connection_id=current["id"],
                    )
                    if not credential:
                        raise DomainError(
                            "service_application_rollback_credentials_unavailable",
                            409,
                        )
            next_version = (
                await one(
                    connection,
                    """
SELECT COALESCE(max(version),0)+1 AS version
FROM service_application_versions
WHERE tenant_id=:tenant
  AND business_id=:business
  AND workspace_id=:workspace
  AND application_id=:application_id
""",
                    tenant=tenant,
                    business=application["scope"].business_id,
                    workspace=application["scope"].workspace_id,
                    application_id=application["id"],
                )
            )["version"]
            version_id = uuid4()
            await execute(
                connection,
                """
INSERT INTO service_application_versions(
    id,tenant_id,business_id,workspace_id,application_id,version,schema_version,
    config,config_digest,source_version,created_by
) VALUES(
    :id,:tenant,:business,:workspace,:application_id,:version,'v2',
    CAST(:config AS jsonb),:digest,:source_version,:actor
)
""",
                id=version_id,
                tenant=tenant,
                business=application["scope"].business_id,
                workspace=application["scope"].workspace_id,
                application_id=application["id"],
                version=next_version,
                config=json.dumps(target["config"], ensure_ascii=False),
                digest=target["config_digest"],
                source_version=target_version,
                actor=actor,
            )
            await execute(
                connection,
                """
UPDATE service_applications
SET status='published',
    published_version=:version,
    updated_by=:actor,
    updated_at=now()
WHERE id=:application_id
""",
                version=next_version,
                actor=actor,
                application_id=application["id"],
            )
            await audit(
                connection,
                tenant,
                actor,
                "service_application.rolled_back",
                application["id"],
                key=application_key,
                version=next_version,
                source_version=target_version,
            )
        return {
            "application_id": application["id"],
            "version": next_version,
            "source_version": target_version,
            "config": target_snapshot.model_dump(mode="json"),
            "config_digest": target["config_digest"],
            "revision": revision,
        }

    async def diff(
        self,
        tenant: str,
        application_key: str,
        from_version: int,
        to_version: int,
        *,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        source = await self.get_version(tenant, application_key, from_version, scope=scope)
        target = await self.get_version(tenant, application_key, to_version, scope=scope)
        changes: dict[str, Any] = {}
        source_config = source["config"]
        target_config = target["config"]
        for key in ("agent", "skills", "connections", "rules", "channels", "experience"):
            if canonical_json(source_config.get(key)) != canonical_json(target_config.get(key)):
                changes[key] = {
                    "from_digest": canonical_digest(source_config.get(key)),
                    "to_digest": canonical_digest(target_config.get(key)),
                }
        return {
            "from_version": from_version,
            "to_version": to_version,
            "from_digest": source["config_digest"],
            "to_digest": target["config_digest"],
            "changed_sections": changes,
        }

    async def record_trace(
        self,
        tenant: str,
        trace: ApplicationTraceInput | dict[str, Any],
        *,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        validated = (
            trace
            if isinstance(trace, ApplicationTraceInput)
            else ApplicationTraceInput.model_validate(trace)
        )
        resolved, scope_sql, scope_params = self._scope(tenant, scope)
        async with self.engine.begin() as connection:
            application = required(
                await one(
                    connection,
                    f"""
SELECT id FROM service_applications
WHERE tenant_id=:tenant
  AND {scope_sql}
  AND id=:application_id
""",
                    tenant=tenant,
                    application_id=validated.application_id,
                    **scope_params,
                ),
                "service_application_not_found",
            )
            version = await one(
                connection,
                """
SELECT version FROM service_application_versions
WHERE tenant_id=:tenant
  AND business_id=:business
  AND workspace_id=:workspace
  AND application_id=:application_id
  AND version=:version
""",
                tenant=tenant,
                business=resolved.business_id,
                workspace=resolved.workspace_id,
                application_id=application["id"],
                version=validated.application_version,
            )
            if not version:
                raise DomainError("service_application_version_not_found", 404)
            trace_id = uuid4()
            await execute(
                connection,
                """
INSERT INTO service_application_traces(
    id,tenant_id,business_id,workspace_id,application_id,application_version,
    conversation_id,run_id,agent_id,agent_version,trace
) VALUES(
    :id,:tenant,:business,:workspace,:application_id,:application_version,
    :conversation_id,:run_id,:agent_id,:agent_version,CAST(:trace AS jsonb)
)
""",
                id=trace_id,
                tenant=tenant,
                business=resolved.business_id,
                workspace=resolved.workspace_id,
                application_id=application["id"],
                application_version=validated.application_version,
                conversation_id=validated.conversation_id,
                run_id=validated.run_id,
                agent_id=validated.agent_id,
                agent_version=validated.agent_version,
                trace=json.dumps(validated.trace, ensure_ascii=False, default=str),
            )
            row = await one(
                connection,
                """
SELECT id,application_id,application_version,conversation_id,run_id,
       agent_id,agent_version,trace,created_at
FROM service_application_traces
WHERE id=:id
""",
                id=trace_id,
            )
        ApplicationTrace.model_validate(row)
        return row

    async def traces(
        self,
        tenant: str,
        application_key: str,
        *,
        page: int = 1,
        page_size: int = 10,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        if page < 1 or page_size < 1 or page_size > 200:
            raise DomainError("service_application_trace_page_invalid", 422)
        offset = (page - 1) * page_size
        async with self.engine.connect() as connection:
            application = await self._application(connection, tenant, application_key, scope)
            total = await one(
                connection,
                """
SELECT count(*)::int AS count
FROM service_application_traces
WHERE tenant_id=:tenant
  AND business_id=:business
  AND workspace_id=:workspace
  AND application_id=:application_id
""",
                tenant=tenant,
                business=application["scope"].business_id,
                workspace=application["scope"].workspace_id,
                application_id=application["id"],
            )
            rows = await many(
                connection,
                """
SELECT * FROM service_application_traces
WHERE tenant_id=:tenant
  AND business_id=:business
  AND workspace_id=:workspace
  AND application_id=:application_id
ORDER BY created_at DESC,id
LIMIT :limit OFFSET :offset
""",
                tenant=tenant,
                business=application["scope"].business_id,
                workspace=application["scope"].workspace_id,
                application_id=application["id"],
                limit=page_size,
                offset=offset,
            )
        return {
            "items": rows,
            "total": total["count"] if total else 0,
            "page": page,
            "page_size": page_size,
        }


ServiceApplicationReleaseService = ApplicationReleaseService


__all__ = [
    "ApplicationReleaseService",
    "ReadinessCheck",
    "ReadinessStatus",
    "ReleaseReadiness",
    "ServiceApplicationReleaseService",
    "canonical_digest",
    "canonical_json",
    "snapshot_digest",
]
