"""Application-scoped runtime resolution.

The release snapshot is the sole authority for a customer-facing run. It
pins the Agent version, the enabled skills, and the application-owned
connections. Agent-level global tools are deliberately not a runtime
permission source.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from agent_platform.business_capabilities.customer_service.service_apps.connections import (
    connection_headers_from_credential,
)
from agent_platform.core_platform.platform_services.persistence.store import (
    DomainError,
    execute,
    one,
)
from agent_platform.core_platform.platform_services.secrets.vault import CredentialVault
from agent_platform.core_platform.platform_services.tenant_isolation.service import (
    resolve_scope,
    scope_predicate,
)
from agent_platform.extension_contracts import BusinessScope

APPLICATION_SCHEMA_VERSION = "v2"


def _builtin_schema_names() -> dict[str, object]:
    # Imported lazily: the platform tool catalog imports CustomerService, which
    # imports this module. Module-level import would make that graph circular.
    from agent_platform.applications.platform_runtime.tool_defaults import BUILTIN_SCHEMAS

    return BUILTIN_SCHEMAS


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _items(value: object) -> list[dict[str, Any]]:
    if isinstance(value, Mapping):
        result: list[dict[str, Any]] = []
        for key, item in value.items():
            if not isinstance(item, Mapping):
                continue
            entry = {**_mapping(item)}
            entry.setdefault("key", str(key))
            result.append(entry)
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_mapping(item) for item in value if isinstance(item, Mapping)]
    return []


def _text(value: object, default: str = "") -> str:
    return str(value) if isinstance(value, (str, int, UUID)) else default


def _positive_int(value: object, code: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise DomainError(code, 422) from None
    if parsed < 1:
        raise DomainError(code, 422)
    return parsed


def _uuid(value: object, code: str) -> UUID:
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        raise DomainError(code, 422) from None


def _parameters(skill: Mapping[str, Any]) -> dict[str, Any]:
    config = _mapping(skill.get("config"))
    candidate = skill.get("parameters") or config.get("parameters")
    if not isinstance(candidate, Mapping):
        return {"type": "object", "properties": {}, "additionalProperties": False}
    result = dict(candidate)
    result.setdefault("type", "object")
    result.setdefault("properties", {})
    result.setdefault("additionalProperties", False)
    return result


def _tool_name(skill: Mapping[str, Any]) -> str:
    """Give the model a function-safe name while retaining the skill key."""

    key = _text(skill.get("key"))
    return re.sub(r"[^a-zA-Z0-9_]", "_", key)


@dataclass(frozen=True, slots=True)
class ApplicationRuntimeContext:
    """Resolved, immutable application context for one conversation turn."""

    application_id: UUID
    application_version: int
    application_key: str
    business_id: str
    workspace_id: str
    agent_snapshot: dict[str, Any]
    skills: tuple[dict[str, Any], ...]
    connections: tuple[dict[str, Any], ...]
    builtin_tools: tuple[str, ...]

    @property
    def agent_id(self) -> UUID:
        return _uuid(self.agent_snapshot.get("id"), "application_agent_invalid")

    @property
    def agent_version(self) -> int:
        return _positive_int(
            self.agent_snapshot.get("version"),
            "application_agent_version_invalid",
        )

    def snapshot(self) -> dict[str, Any]:
        """Return the JSON-safe application section persisted on a run."""

        return {
            "id": str(self.application_id),
            "key": self.application_key,
            "version": self.application_version,
            "business_id": self.business_id,
            "workspace_id": self.workspace_id,
            "skills": list(self.skills),
            "connections": list(self.connections),
            "builtin_tools": list(self.builtin_tools),
        }

    def trace_payload(self) -> dict[str, Any]:
        """Build a redacted trace payload; credentials never enter a trace."""

        return {
            "application_key": self.application_key,
            "application_version": self.application_version,
            "agent_id": str(self.agent_id),
            "agent_version": self.agent_version,
            "skills": [
                {
                    "key": skill.get("key"),
                    "type": skill.get("type"),
                    "connection_key": skill.get("connection_key"),
                }
                for skill in self.skills
            ],
            "connections": [
                {
                    "key": connection.get("key"),
                    "executor_kind": connection.get("executor_kind"),
                }
                for connection in self.connections
            ],
            "status": "submitted",
        }

    def http_tool_specs(self) -> list[dict[str, Any]]:
        """Return only executable HTTP specs authorized by this release."""

        return application_http_tool_specs(self.snapshot())


def application_http_tool_specs(application: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Build HTTP tool specs from an application run snapshot."""

    connections = {
        _text(connection.get("key")): connection
        for connection in _items(application.get("connections"))
    }
    skills = _items(application.get("skills"))
    specs: list[dict[str, Any]] = []
    for skill in skills:
        if skill.get("enabled", True) is False:
            continue
        if skill.get("type") not in {"query", "action"}:
            continue
        connection_key = _text(skill.get("connection_key"))
        connection = connections.get(connection_key)
        if not connection or connection.get("executor_kind") != "http":
            continue
        endpoint = _text(connection.get("endpoint"))
        if not endpoint:
            continue
        skill_config = _mapping(skill.get("config"))
        credential_ref = connection.get("credential_ref")
        auth_kind = _text(connection.get("auth_kind"), "none")
        credential_id = None
        if credential_ref:
            credential_id = _uuid(
                credential_ref,
                "service_application_connection_credential_invalid",
            )
        elif auth_kind != "none":
            raise DomainError(
                "service_application_connection_credential_missing",
                422,
            )
        safety = _mapping(skill.get("safety"))
        timeout = connection.get("timeout_seconds", 10)
        safety_timeout = safety.get("timeout_seconds")
        if safety_timeout is not None:
            try:
                timeout = min(float(timeout), float(safety_timeout))
            except (TypeError, ValueError):
                raise DomainError("service_application_skill_invalid", 422) from None
        specs.append(
            {
                "name": _tool_name(skill),
                "description": _text(
                    skill.get("description") or skill.get("name") or skill.get("key"),
                    _text(skill.get("key")),
                ),
                "url": endpoint,
                "method": _text(connection.get("method"), "GET").upper(),
                "parameters": _parameters(skill),
                "headers": _mapping(connection.get("public_headers") or connection.get("headers")),
                "auth_kind": auth_kind,
                "credential_id": credential_id,
                "timeout_seconds": timeout,
                "max_response_bytes": connection.get("max_response_bytes", 16000),
                "response_schema": (
                    skill.get("result_schema") or skill_config.get("result_schema") or None
                ),
            }
        )
    names = [spec["name"] for spec in specs]
    if len(names) != len(set(names)):
        raise DomainError("service_application_skill_tool_name_conflict", 422)
    return specs


class ApplicationRuntimeResolver:
    """Resolve a published application version into a run-safe context."""

    def __init__(self, engine: object, agents: object | None, settings: object) -> None:
        self.engine = engine
        self.agents = agents
        self.settings = settings
        key_file = getattr(settings, "service_app_vault_key_file", None)
        if key_file is None:
            key_file = settings.model_credential_key_file
        self.vault = CredentialVault(key_file)

    async def resolve(
        self,
        connection: object,
        tenant: str,
        application_id: UUID | str,
        application_version: int,
        conversation_id: UUID | None = None,
        *,
        scope: BusinessScope | None = None,
    ) -> ApplicationRuntimeContext:
        """Resolve one immutable application release.

        ``conversation_id`` is accepted as trace context but is intentionally
        not used as an authorization key. Scope is always checked against the
        application row before the Agent or skill snapshot is loaded.
        """

        del conversation_id  # Reserved for trace correlation in this phase.
        app_id = _uuid(application_id, "service_application_id_invalid")
        version = _positive_int(
            application_version,
            "service_application_version_invalid",
        )
        resolved_scope = resolve_scope(tenant, scope)
        scope_sql, scope_params = scope_predicate(resolved_scope, alias="a")
        row = await one(
            connection,
            f"""
            SELECT a.id,a.application_key,a.business_id,a.workspace_id,
                   v.config,v.schema_version
            FROM service_applications a
            JOIN service_application_versions v
              ON v.tenant_id=a.tenant_id
             AND v.business_id=a.business_id
             AND v.workspace_id=a.workspace_id
             AND v.application_id=a.id
            WHERE a.id=:application_id
              AND a.tenant_id=:tenant
              AND {scope_sql}
              AND v.version=:application_version
              AND NOT a.archived
            """,
            application_id=app_id,
            tenant=tenant,
            application_version=version,
            **scope_params,
        )
        if not row:
            raise DomainError("service_application_version_not_found", 404)
        if _text(row.get("schema_version"), APPLICATION_SCHEMA_VERSION) != (
            APPLICATION_SCHEMA_VERSION
        ):
            raise DomainError("service_application_schema_unsupported", 422)
        config = _mapping(row.get("config"))
        if _text(config.get("schema_version"), APPLICATION_SCHEMA_VERSION) != (
            APPLICATION_SCHEMA_VERSION
        ):
            raise DomainError("service_application_schema_unsupported", 422)
        agent_ref = _mapping(config.get("agent"))
        agent_id = _uuid(agent_ref.get("id"), "service_application_agent_required")
        agent_version = _positive_int(
            agent_ref.get("version"),
            "service_application_agent_version_required",
        )
        if self.agents is None or not hasattr(self.agents, "snapshot"):
            raise DomainError("application_runtime_agent_resolver_unavailable", 503)
        agent_snapshot = await self.agents.snapshot(
            tenant,
            agent_id,
            connection,
            agent_version,
        )

        skills = tuple(
            skill
            for skill in _items(config.get("skills"))
            if skill.get("enabled", True) is not False
        )
        skill_keys = [_text(skill.get("key")) for skill in skills]
        if any(not key for key in skill_keys) or len(set(skill_keys)) != len(skill_keys):
            raise DomainError("service_application_skill_invalid", 422)

        referenced = {
            _text(skill.get("connection_key"))
            for skill in skills
            if _text(skill.get("connection_key"))
        }
        connections = tuple(
            connection
            for connection in _items(config.get("connections"))
            if _text(connection.get("key")) in referenced
        )
        connection_keys = [_text(connection.get("key")) for connection in connections]
        if len(set(connection_keys)) != len(connection_keys):
            raise DomainError("service_application_connection_invalid", 422)
        missing = referenced - set(connection_keys)
        if missing:
            raise DomainError("service_application_connection_missing", 422)

        agent_config = _mapping(agent_snapshot.get("config"))
        agent_tools = {_text(name) for name in agent_config.get("tool_names", []) if _text(name)}
        builtin_names = _builtin_schema_names()
        builtin_tools = tuple(name for name in sorted(agent_tools) if name in builtin_names)
        tool_names = [
            _tool_name(skill) for skill in skills if skill.get("type") in {"query", "action"}
        ]
        if len(tool_names) != len(set(tool_names)) or set(tool_names) & set(builtin_tools):
            raise DomainError("service_application_skill_tool_name_conflict", 422)
        return ApplicationRuntimeContext(
            application_id=app_id,
            application_version=version,
            application_key=_text(row.get("application_key")),
            business_id=_text(row.get("business_id")),
            workspace_id=_text(row.get("workspace_id")),
            agent_snapshot=agent_snapshot,
            skills=skills,
            connections=connections,
            builtin_tools=builtin_tools,
        )

    async def resolve_conversation(
        self,
        connection: object,
        tenant: str,
        conversation: Mapping[str, Any],
    ) -> ApplicationRuntimeContext | None:
        """Resolve application context stored on a conversation, if present."""

        application_id = conversation.get("application_id")
        application_version = conversation.get("application_version")
        if not application_id or not application_version:
            return None
        return await self.resolve(
            connection,
            tenant,
            application_id,
            _positive_int(
                application_version,
                "conversation_application_version_invalid",
            ),
            _uuid(conversation.get("id"), "conversation_id_invalid"),
            scope=BusinessScope(
                tenant_id=tenant,
                business_id=_text(conversation.get("business_id")) or None,
                workspace_id=_text(conversation.get("workspace_id")) or None,
            ),
        )

    async def credential_headers(
        self,
        tenant: str,
        spec: object,
        *,
        application_id: UUID | str | None = None,
        business_id: str | None = None,
        workspace_id: str | None = None,
    ) -> dict[str, str]:
        """Resolve application credentials without exposing decrypted values."""

        credential_id = getattr(spec, "credential_id", None)
        if not credential_id:
            return {}
        endpoint = _text(getattr(spec, "url", ""))
        if not endpoint:
            raise DomainError("service_connection_credential_endpoint_missing", 503)
        async with self.engine.connect() as connection:
            row = await one(
                connection,
                """
                SELECT cc.id AS credential_id,cc.connection_id,cc.encrypted_secret,
                       c.auth_kind,c.endpoint,c.config
                FROM service_application_connection_credentials cc
                JOIN service_application_connections c
                  ON c.id=cc.connection_id
                 AND c.tenant_id=cc.tenant_id
                 AND c.business_id=cc.business_id
                 AND c.workspace_id=cc.workspace_id
                WHERE cc.tenant_id=:tenant
                  AND cc.id=:credential
                  AND c.endpoint=:endpoint
                  AND (
                    CAST(:application_id AS uuid) IS NULL
                    OR c.application_id=CAST(:application_id AS uuid)
                  )
                  AND (:business_id IS NULL OR c.business_id=:business_id)
                  AND (:workspace_id IS NULL OR c.workspace_id=:workspace_id)
                """,
                tenant=tenant,
                credential=credential_id,
                endpoint=endpoint,
                application_id=(
                    _uuid(application_id, "service_application_id_invalid")
                    if application_id
                    else None
                ),
                business_id=business_id,
                workspace_id=workspace_id,
            )
        if not row or not row.get("encrypted_secret"):
            raise DomainError("service_connection_credential_unavailable", 503)

        payload = self.vault.decrypt(
            row["encrypted_secret"],
            tenant,
            row["connection_id"],
            {
                "base_url": row["endpoint"],
                "protocol": "service_application_connection",
            },
        )
        return connection_headers_from_credential(row, payload)

    async def record_trace(
        self,
        connection: object,
        tenant: str,
        context: ApplicationRuntimeContext,
        *,
        conversation_id: UUID,
        run_id: UUID,
    ) -> None:
        """Persist the application/agent provenance for one submitted run."""

        await execute(
            connection,
            """
            INSERT INTO service_application_traces(
                id,tenant_id,business_id,workspace_id,application_id,
                application_version,conversation_id,run_id,agent_id,agent_version,trace
            ) VALUES(
                gen_random_uuid(),:tenant,:business_id,:workspace_id,:application_id,
                :application_version,:conversation_id,:run_id,:agent_id,:agent_version,
                CAST(:trace AS jsonb)
            )
            """,
            tenant=tenant,
            business_id=context.business_id,
            workspace_id=context.workspace_id,
            application_id=context.application_id,
            application_version=context.application_version,
            conversation_id=conversation_id,
            run_id=run_id,
            agent_id=context.agent_id,
            agent_version=context.agent_version,
            trace=json.dumps(context.trace_payload(), ensure_ascii=False, sort_keys=True),
        )


def authorized_tool_names(application: Mapping[str, Any]) -> list[str]:
    """Return the exact model-visible allowlist for one application run."""

    connections = {
        _text(connection.get("key")): connection
        for connection in _items(application.get("connections"))
    }
    skills = _items(application.get("skills"))
    skill_names = [
        _tool_name(skill)
        for skill in skills
        if skill.get("enabled", True) is not False
        and skill.get("type") in {"query", "action"}
        and _text(skill.get("connection_key"))
        and _text((connections.get(_text(skill.get("connection_key"))) or {}).get("executor_kind"))
        == "http"
        and _text((connections.get(_text(skill.get("connection_key"))) or {}).get("endpoint"))
    ]
    builtins = [
        _text(name)
        for name in application.get("builtin_tools", [])
        if _text(name) in _builtin_schema_names()
    ]
    return list(dict.fromkeys([*skill_names, *builtins]))


__all__ = [
    "APPLICATION_SCHEMA_VERSION",
    "ApplicationRuntimeContext",
    "ApplicationRuntimeResolver",
    "authorized_tool_names",
]
