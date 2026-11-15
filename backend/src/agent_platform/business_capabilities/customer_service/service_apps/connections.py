"""Application-scoped connection CRUD, credentials and connection testing."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

import httpx
from sqlalchemy.exc import IntegrityError

from agent_platform.core_platform.platform_services.persistence.store import (
    DomainError,
    audit,
    execute,
    many,
    one,
    required,
)
from agent_platform.core_platform.platform_services.secrets.vault import CredentialVault
from agent_platform.core_platform.platform_services.tenant_isolation.service import (
    persisted_scope,
    scope_predicate,
)
from agent_platform.core_platform.tool_gateway.egress import (
    ToolEgressPolicy,
    ToolEgressTransport,
)
from agent_platform.core_platform.tool_gateway.service import HttpTool, ToolGateway
from agent_platform.extension_contracts import BusinessScope

from .models import (
    ApplicationConnectionCreate,
    ApplicationConnectionUpdate,
    AuthKind,
    ConnectionCredentialInput,
    ConnectionCredentialStatus,
    ConnectionExecutorKind,
)


def _connection_public(row: dict[str, Any]) -> dict[str, Any]:
    item = dict(row)
    if "connection_key" in item:
        item["key"] = item.pop("connection_key")
    item["credentials_configured"] = bool(item.get("credentials_configured"))
    item.pop("encrypted_secret", None)
    item.pop("credential_id", None)
    return item


def connection_headers_from_credential(
    connection: dict[str, Any],
    payload: Any,
) -> dict[str, str]:
    """Translate a decrypted credential payload into outbound auth headers."""

    if not isinstance(payload, dict):
        raise DomainError("service_application_credential_invalid", 503)
    auth_kind = str(connection["auth_kind"])
    secret = payload.get("secret")
    if not isinstance(secret, str) or not secret:
        raise DomainError("service_application_credential_invalid", 503)
    if auth_kind == AuthKind.BEARER:
        return {"Authorization": f"Bearer {secret}"}
    header_name = payload.get("header_name") or connection.get("config", {}).get("header_name")
    if auth_kind == AuthKind.API_KEY and not header_name:
        header_name = "X-API-Key"
    if not isinstance(header_name, str) or not header_name:
        raise DomainError("service_application_credential_invalid", 503)
    return {header_name: secret}


class ApplicationConnectionService:
    """CRUD and security boundary for one application's connections."""

    def __init__(
        self,
        engine: object,
        settings: object,
        *,
        client: httpx.AsyncClient | None = None,
        network_policy: ToolEgressPolicy | None = None,
        vault: CredentialVault | None = None,
    ) -> None:
        self.engine = engine
        self.settings = settings
        self.client = client
        self.network_policy = network_policy or ToolEgressPolicy.from_settings(settings)
        key_file = getattr(settings, "service_app_vault_key_file", None)
        if key_file is None:
            key_file = getattr(settings, "service_app_credential_key_file", None)
        if key_file is None:
            key_file = settings.model_credential_key_file
        self.vault = vault or CredentialVault(key_file)

    @staticmethod
    def _body(
        value: ApplicationConnectionCreate | ApplicationConnectionUpdate | dict[str, Any],
        model: type[ApplicationConnectionCreate | ApplicationConnectionUpdate],
    ) -> ApplicationConnectionCreate | ApplicationConnectionUpdate:
        return value if isinstance(value, model) else model.model_validate(value)

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

    async def _application_by_id(
        self,
        connection: Any,
        tenant: str,
        application_id: UUID,
        scope: BusinessScope | None,
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
  AND id=:application_id
  AND NOT archived
""",
                tenant=tenant,
                application_id=application_id,
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

    async def list(
        self,
        tenant: str,
        application_key: str,
        *,
        scope: BusinessScope | None = None,
    ) -> list[dict[str, Any]]:
        async with self.engine.connect() as connection:
            application = await self._application(connection, tenant, application_key, scope)
            rows = await many(
                connection,
                """
SELECT c.*,
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
ORDER BY c.name,c.connection_key
""",
                tenant=tenant,
                business=application["scope"].business_id,
                workspace=application["scope"].workspace_id,
                application_id=application["id"],
            )
            return [_connection_public(row) for row in rows]

    async def get(
        self,
        tenant: str,
        application_id: UUID,
        connection_key: str,
        *,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        _resolved, scope_sql, scope_params = self._scope(tenant, scope)
        async with self.engine.connect() as connection:
            row = required(
                await one(
                    connection,
                    f"""
SELECT c.*,cred.id AS credential_id,
       cred.id IS NOT NULL AS credentials_configured
FROM service_application_connections c
LEFT JOIN service_application_connection_credentials cred
  ON cred.connection_id=c.id
 AND cred.tenant_id=c.tenant_id
 AND cred.business_id=c.business_id
 AND cred.workspace_id=c.workspace_id
WHERE c.tenant_id=:tenant
  AND {scope_sql}
  AND c.application_id=:application_id
  AND c.connection_key=:key
""",
                    tenant=tenant,
                    application_id=application_id,
                    key=connection_key,
                    **scope_params,
                ),
                "service_application_connection_not_found",
            )
        return _connection_public(row)

    async def create(
        self,
        tenant: str,
        actor: str,
        application_key: str,
        body: ApplicationConnectionCreate | dict[str, Any],
        *,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        validated = self._body(body, ApplicationConnectionCreate)
        if validated.timeout_seconds > getattr(
            self.settings, "service_app_connection_timeout_max", 60
        ):
            raise DomainError("service_application_connection_timeout_exceeded", 422)
        async with self.engine.begin() as connection:
            application = await self._application(
                connection, tenant, application_key, scope, lock=True
            )
            self._assert_mutable(application)
            duplicate = await one(
                connection,
                """
SELECT id FROM service_application_connections
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
                key=validated.key,
            )
            if duplicate is not None:
                raise DomainError("service_application_connection_key_conflict", 409)
            connection_id = uuid4()
            try:
                await execute(
                    connection,
                    """
INSERT INTO service_application_connections(
    id,tenant_id,business_id,workspace_id,application_id,connection_key,name,
    executor_kind,endpoint,method,public_headers,auth_kind,timeout_seconds,
    max_response_bytes,config,revision,created_by,updated_by
) VALUES(
    :id,:tenant,:business,:workspace,:application_id,:key,:name,
    :executor_kind,:endpoint,:method,CAST(:public_headers AS jsonb),:auth_kind,
    :timeout_seconds,:max_response_bytes,CAST(:config AS jsonb),1,:actor,:actor
)
""",
                    id=connection_id,
                    tenant=tenant,
                    business=application["scope"].business_id,
                    workspace=application["scope"].workspace_id,
                    application_id=application["id"],
                    key=validated.key,
                    name=validated.name,
                    executor_kind=validated.executor_kind.value,
                    endpoint=validated.endpoint,
                    method=validated.method.value,
                    public_headers=json.dumps(validated.public_headers),
                    auth_kind=validated.auth_kind.value,
                    timeout_seconds=validated.timeout_seconds,
                    max_response_bytes=validated.max_response_bytes,
                    config=json.dumps(validated.config),
                    actor=actor,
                )
            except IntegrityError:
                raise DomainError("service_application_connection_key_conflict", 409) from None
            await audit(
                connection,
                tenant,
                actor,
                "service_application.connection.created",
                connection_id,
                application_id=application["id"],
                key=validated.key,
                auth_kind=validated.auth_kind.value,
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
        return await self.get(tenant, application["id"], validated.key, scope=application["scope"])

    async def update(
        self,
        tenant: str,
        actor: str,
        application_key: str,
        connection_key: str,
        body: ApplicationConnectionUpdate | dict[str, Any],
        *,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        validated = self._body(body, ApplicationConnectionUpdate)
        if validated.timeout_seconds > getattr(
            self.settings, "service_app_connection_timeout_max", 60
        ):
            raise DomainError("service_application_connection_timeout_exceeded", 422)
        async with self.engine.begin() as connection:
            application = await self._application(
                connection, tenant, application_key, scope, lock=True
            )
            self._assert_mutable(application)
            existing = required(
                await one(
                    connection,
                    """
SELECT id,revision FROM service_application_connections
WHERE tenant_id=:tenant
  AND business_id=:business
  AND workspace_id=:workspace
  AND application_id=:application_id
  AND connection_key=:key
FOR UPDATE
""",
                    tenant=tenant,
                    business=application["scope"].business_id,
                    workspace=application["scope"].workspace_id,
                    application_id=application["id"],
                    key=connection_key,
                ),
                "service_application_connection_not_found",
            )
            if existing["revision"] != validated.revision:
                raise DomainError("service_application_connection_revision_conflict", 409)
            await execute(
                connection,
                """
UPDATE service_application_connections
SET name=:name,
    executor_kind=:executor_kind,
    endpoint=:endpoint,
    method=:method,
    public_headers=CAST(:public_headers AS jsonb),
    auth_kind=:auth_kind,
    timeout_seconds=:timeout_seconds,
    max_response_bytes=:max_response_bytes,
    config=CAST(:config AS jsonb),
    revision=revision+1,
    updated_by=:actor,
    updated_at=now()
WHERE id=:id
""",
                id=existing["id"],
                name=validated.name,
                executor_kind=validated.executor_kind.value,
                endpoint=validated.endpoint,
                method=validated.method.value,
                public_headers=json.dumps(validated.public_headers),
                auth_kind=validated.auth_kind.value,
                timeout_seconds=validated.timeout_seconds,
                max_response_bytes=validated.max_response_bytes,
                config=json.dumps(validated.config),
                actor=actor,
            )
            await audit(
                connection,
                tenant,
                actor,
                "service_application.connection.updated",
                existing["id"],
                application_id=application["id"],
                key=connection_key,
                revision=validated.revision + 1,
                auth_kind=validated.auth_kind.value,
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
        return await self.get(tenant, application["id"], connection_key, scope=application["scope"])

    async def delete(
        self,
        tenant: str,
        actor: str,
        application_key: str,
        connection_key: str,
        *,
        scope: BusinessScope | None = None,
    ) -> None:
        async with self.engine.begin() as connection:
            application = await self._application(
                connection, tenant, application_key, scope, lock=True
            )
            self._assert_mutable(application)
            row = required(
                await one(
                    connection,
                    """
SELECT id FROM service_application_connections
WHERE tenant_id=:tenant
  AND business_id=:business
  AND workspace_id=:workspace
  AND application_id=:application_id
  AND connection_key=:key
FOR UPDATE
""",
                    tenant=tenant,
                    business=application["scope"].business_id,
                    workspace=application["scope"].workspace_id,
                    application_id=application["id"],
                    key=connection_key,
                ),
                "service_application_connection_not_found",
            )
            references = await one(
                connection,
                """
SELECT count(*)::int AS count
FROM service_application_skills
WHERE tenant_id=:tenant
  AND business_id=:business
  AND workspace_id=:workspace
  AND application_id=:application_id
  AND connection_id=:connection_id
""",
                tenant=tenant,
                business=application["scope"].business_id,
                workspace=application["scope"].workspace_id,
                application_id=application["id"],
                connection_id=row["id"],
            )
            if references and references["count"]:
                raise DomainError("service_application_connection_in_use", 409)
            await execute(
                connection,
                "DELETE FROM service_application_connections WHERE id=:id",
                id=row["id"],
            )
            await audit(
                connection,
                tenant,
                actor,
                "service_application.connection.deleted",
                row["id"],
                application_id=application["id"],
                key=connection_key,
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

    async def set_credentials(
        self,
        tenant: str,
        actor: str,
        application_key: str,
        connection_key: str,
        body: ConnectionCredentialInput | dict[str, Any],
        *,
        scope: BusinessScope | None = None,
    ) -> ConnectionCredentialStatus:
        validated = (
            body
            if isinstance(body, ConnectionCredentialInput)
            else ConnectionCredentialInput.model_validate(body)
        )
        async with self.engine.begin() as connection:
            application = await self._application(
                connection, tenant, application_key, scope, lock=True
            )
            self._assert_mutable(application)
            row = required(
                await one(
                    connection,
                    """
SELECT id,auth_kind,endpoint,config
FROM service_application_connections
WHERE tenant_id=:tenant
  AND business_id=:business
  AND workspace_id=:workspace
  AND application_id=:application_id
  AND connection_key=:key
FOR UPDATE
""",
                    tenant=tenant,
                    business=application["scope"].business_id,
                    workspace=application["scope"].workspace_id,
                    application_id=application["id"],
                    key=connection_key,
                ),
                "service_application_connection_not_found",
            )
            if row["auth_kind"] != validated.auth_kind.value:
                raise DomainError("service_application_credential_auth_kind_mismatch", 422)
            custom_name = row["config"].get("header_name")
            if validated.auth_kind.value in {"api_key", "custom"}:
                resolved_name = validated.header_name or (
                    custom_name if validated.auth_kind.value == "custom" else "X-API-Key"
                )
                if not resolved_name:
                    raise DomainError("service_application_credential_header_required", 422)
                if validated.auth_kind.value == "custom" and resolved_name != custom_name:
                    raise DomainError("service_application_credential_header_mismatch", 422)
            else:
                resolved_name = None
            payload = {
                "auth_kind": validated.auth_kind.value,
                "secret": validated.secret.get_secret_value(),
                "header_name": resolved_name,
            }
            spec = {
                "base_url": f"service-app://{row['id']}",
                "protocol": "service_application_connection",
            }
            encrypted = self.vault.encrypt(
                payload,
                tenant,
                row["id"],
                spec,
                create=True,
            )
            credential_id = uuid4()
            await execute(
                connection,
                """
INSERT INTO service_application_connection_credentials(
    id,tenant_id,business_id,workspace_id,connection_id,encrypted_secret,key_version
) VALUES(
    :id,:tenant,:business,:workspace,:connection_id,:encrypted_secret,1
)
ON CONFLICT (connection_id) DO UPDATE SET
    encrypted_secret=EXCLUDED.encrypted_secret,
    key_version=service_application_connection_credentials.key_version+1,
    updated_at=now()
""",
                id=credential_id,
                tenant=tenant,
                business=application["scope"].business_id,
                workspace=application["scope"].workspace_id,
                connection_id=row["id"],
                encrypted_secret=encrypted,
            )
            await audit(
                connection,
                tenant,
                actor,
                "service_application.connection.credential_configured",
                row["id"],
                application_id=application["id"],
                key=connection_key,
                auth_kind=validated.auth_kind.value,
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
        return ConnectionCredentialStatus(
            auth_kind=validated.auth_kind,
            credentials_configured=True,
        )

    async def clear_credentials(
        self,
        tenant: str,
        actor: str,
        application_key: str,
        connection_key: str,
        *,
        scope: BusinessScope | None = None,
    ) -> ConnectionCredentialStatus:
        async with self.engine.begin() as connection:
            application = await self._application(
                connection, tenant, application_key, scope, lock=True
            )
            self._assert_mutable(application)
            row = required(
                await one(
                    connection,
                    """
SELECT id,auth_kind FROM service_application_connections
WHERE tenant_id=:tenant
  AND business_id=:business
  AND workspace_id=:workspace
  AND application_id=:application_id
  AND connection_key=:key
FOR UPDATE
""",
                    tenant=tenant,
                    business=application["scope"].business_id,
                    workspace=application["scope"].workspace_id,
                    application_id=application["id"],
                    key=connection_key,
                ),
                "service_application_connection_not_found",
            )
            await execute(
                connection,
                "DELETE FROM service_application_connection_credentials "
                "WHERE connection_id=:connection_id",
                connection_id=row["id"],
            )
            await audit(
                connection,
                tenant,
                actor,
                "service_application.connection.credential_cleared",
                row["id"],
                application_id=application["id"],
                key=connection_key,
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
        return ConnectionCredentialStatus(
            auth_kind=AuthKind(row["auth_kind"]),
            credentials_configured=False,
        )

    async def credentials_status(
        self,
        tenant: str,
        application_id: UUID,
        connection_key: str,
        *,
        scope: BusinessScope | None = None,
    ) -> ConnectionCredentialStatus:
        row = await self.get(tenant, application_id, connection_key, scope=scope)
        return ConnectionCredentialStatus(
            auth_kind=AuthKind(row["auth_kind"]),
            credentials_configured=row["credentials_configured"],
        )

    async def _decrypted_credential(
        self,
        connection_id: UUID,
        tenant: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        async with self.engine.connect() as connection:
            row = required(
                await one(
                    connection,
                    """
SELECT c.id,c.auth_kind,c.endpoint,c.config,
       cred.encrypted_secret
FROM service_application_connections c
JOIN service_application_connection_credentials cred
  ON cred.connection_id=c.id
 AND cred.tenant_id=c.tenant_id
 AND cred.business_id=c.business_id
 AND cred.workspace_id=c.workspace_id
WHERE c.tenant_id=:tenant
  AND c.id=:connection_id
""",
                    tenant=tenant,
                    connection_id=connection_id,
                ),
                "service_application_credentials_not_configured",
            )
        spec = {
            "base_url": f"service-app://{row['id']}",
            "protocol": "service_application_connection",
        }
        payload = self.vault.decrypt(
            row["encrypted_secret"],
            tenant,
            row["id"],
            spec,
        )
        return row, connection_headers_from_credential(row, payload)

    async def test(
        self,
        tenant: str,
        application_key: str,
        connection_key: str,
        *,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        async with self.engine.connect() as connection:
            application = await self._application(connection, tenant, application_key, scope)
            row = required(
                await one(
                    connection,
                    """
SELECT c.*,cred.id AS credential_id
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
        if row["executor_kind"] != ConnectionExecutorKind.HTTP.value:
            return {
                "ok": True,
                "executor_kind": row["executor_kind"],
                "status": "configured",
            }
        if row["auth_kind"] != AuthKind.NONE.value and not row["credential_id"]:
            raise DomainError("service_application_credentials_not_configured", 409)
        credential_headers: dict[str, str] = {}
        if row["credential_id"]:
            _, credential_headers = await self._decrypted_credential(row["id"], tenant)
        response_schema = row["config"].get("response_schema")
        tool = HttpTool(
            name="connection_test",
            description=f"Test connection {connection_key}",
            url=row["endpoint"],
            method=row["method"],
            parameters={
                "type": "object",
                "additionalProperties": False,
                "properties": {},
            },
            headers=row["public_headers"],
            auth_kind=row["auth_kind"],
            credential_id=row["credential_id"],
            timeout_seconds=row["timeout_seconds"],
            max_response_bytes=row["max_response_bytes"],
            response_schema=response_schema if isinstance(response_schema, dict) else None,
        )

        async def resolver(_: HttpTool) -> dict[str, str]:
            return credential_headers

        owns_client = self.client is None
        client = self.client
        if client is None:
            transport = ToolEgressTransport(
                self.network_policy,
                trust_env=False,
                limits=httpx.Limits(max_connections=4),
            )
            client = httpx.AsyncClient(
                transport=transport,
                trust_env=False,
                follow_redirects=False,
            )
        gateway = ToolGateway(
            client,
            [tool],
            concurrency=1,
            credential_resolver=resolver,
            network_policy=self.network_policy,
        )
        try:
            result = await gateway.execute("connection_test", {})
        finally:
            if owns_client:
                await client.aclose()
        return result

    async def resolve(
        self,
        tenant: str,
        application_id: UUID,
        connection_key: str,
        *,
        revision: int | None = None,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        _, scope_sql, scope_params = self._scope(tenant, scope)
        async with self.engine.connect() as connection:
            row = required(
                await one(
                    connection,
                    f"""
SELECT c.*,cred.id AS credential_ref
FROM service_application_connections c
LEFT JOIN service_application_connection_credentials cred
  ON cred.connection_id=c.id
 AND cred.tenant_id=c.tenant_id
 AND cred.business_id=c.business_id
 AND cred.workspace_id=c.workspace_id
WHERE c.tenant_id=:tenant
  AND {scope_sql}
  AND c.application_id=:application_id
  AND c.connection_key=:key
  AND (:revision IS NULL OR c.revision=:revision)
""",
                    tenant=tenant,
                    application_id=application_id,
                    key=connection_key,
                    revision=revision,
                    **scope_params,
                ),
                "service_application_connection_not_found",
            )
        if row["auth_kind"] != AuthKind.NONE.value and not row["credential_ref"]:
            raise DomainError("service_application_credentials_not_configured", 409)
        return _connection_public(row)


ServiceApplicationConnectionService = ApplicationConnectionService


__all__ = [
    "ApplicationConnectionService",
    "ServiceApplicationConnectionService",
    "connection_headers_from_credential",
]
