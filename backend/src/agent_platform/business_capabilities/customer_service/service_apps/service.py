"""Application-v2 CRUD, skills, connections and runtime trace services.

Skills and connections are application-owned resources. Release readiness,
publication and rollback are delegated to ``ApplicationReleaseService`` so the
API and runtime share one immutable-snapshot implementation.
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

from pydantic import ValidationError

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
    ConnectionCredentialInput,
    ReleaseSnapshot,
    ServiceExperienceConfig,
)

DEFAULT_PAGE_SIZE = 10
MAX_PAGE_SIZE = 100
MAX_TRACE_LIMIT = 200
EXAMPLE_KEY_PREFIX = "example-"
APPLICATION_STATUSES = {"draft", "review", "published", "offline"}
SKILL_TYPES = {"knowledge", "query", "action", "handoff"}
CONNECTION_KINDS = {"http", "internal", "human_queue"}
AUTH_KINDS = {"none", "bearer", "api_key", "custom"}
HTTP_METHODS = {"GET", "POST"}
_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_HEADER_NAME_PATTERN = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
_SENSITIVE_HEADERS = {
    "authorization",
    "cookie",
    "proxy-authorization",
    "x-api-key",
    "api-key",
    "token",
    "x-token",
    "set-cookie",
    "host",
    "content-length",
    "transfer-encoding",
}
_SENSITIVE_CONFIG_KEYS = {
    "authorization",
    "cookie",
    "password",
    "secret",
    "token",
}
_SKILL_CONFIG_FIELDS = {
    "parameters",
    "argument_mapping",
    "result_mapping",
    "result_schema",
    "safety",
    "write_operation",
    "knowledge_base_ids",
}
_V1_FIELDS = {
    "scenarios",
    "capabilities",
    "default_execution_order",
    "service_categories",
    "providers",
}
_MISSING = object()


def _json(value: object) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="json")
        return dict(dumped) if isinstance(dumped, dict) else {}
    if isinstance(value, dict):
        return dict(value)
    return {}


def _field(value: object, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _provided(value: object, name: str, default: Any = _MISSING) -> Any:
    """Return only an explicitly submitted field, falling back for PATCH/PUT."""

    if isinstance(value, dict):
        return value.get(name, default)
    fields_set = getattr(value, "model_fields_set", None)
    if fields_set is not None and name not in fields_set:
        return default
    candidate = getattr(value, name, _MISSING)
    return candidate if candidate is not _MISSING else default


def _redacted(value: Any, *, parent: str = "") -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(
                token in lowered
                for token in (
                    "secret",
                    "password",
                    "authorization",
                    "cookie",
                    "token",
                    "api_key",
                    "credential",
                )
            ):
                result[key] = "[redacted]"
            else:
                result[key] = _redacted(item, parent=str(key))
        return result
    if isinstance(value, list):
        return [_redacted(item, parent=parent) for item in value]
    return value


def _uuid(value: object, code: str) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError):
        raise DomainError(code, 422) from None


def _key(value: object, code: str) -> str:
    key = str(value or "").strip()
    if not _KEY_PATTERN.fullmatch(key):
        raise DomainError(code, 422)
    return key


def _page_args(page: int, page_size: int) -> tuple[int, int]:
    if page < 1 or page_size < 1 or page_size > MAX_PAGE_SIZE:
        raise DomainError("service_application_page_invalid", 422)
    return page, page_size


def _contains_secret(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            lowered = str(key).lower()
            if any(fragment in lowered for fragment in _SENSITIVE_CONFIG_KEYS) and item not in (
                None,
                "",
                {},
                [],
            ):
                return True
            if _contains_secret(item):
                return True
    elif isinstance(value, list):
        return any(_contains_secret(item) for item in value)
    return False


class ServiceApplicationService:
    """Application CRUD plus immutable release and trace operations."""

    def __init__(
        self,
        engine: object,
        agents: object,
        *,
        skills: object | None = None,
        connections: object | None = None,
        releases: object | None = None,
        examples: object | None = None,
        preview_runner: object | None = None,
        conversations: object | None = None,
        sessions: object | None = None,
    ) -> None:
        self.engine = engine
        self.agents = agents
        self.skills = skills
        self.connections = connections
        self.releases = releases
        self.examples = examples
        self.preview_runner = preview_runner
        self.conversations = conversations
        self.sessions = sessions

    def bind_sessions(
        self,
        *,
        conversations: object,
        customer: object,
        application_runtime: object,
    ) -> None:
        """Attach the customer-session entry once the container is assembled.

        Kept out of ``__init__`` because the Runtime conversation service and
        ``CustomerService`` are constructed after this service in the container.
        """

        from .sessions import ApplicationSessionService

        self.sessions = ApplicationSessionService(
            self.engine,
            conversations=conversations,
            customer=customer,
            application_runtime=application_runtime,
        )

    def _session_service(self) -> object:
        if self.sessions is None:
            # Only reachable when the container never bound the runtime
            # dependencies (tests, partial assemblies).
            raise DomainError("application_runtime_unavailable", 503)
        return self.sessions

    def _connection_service(self) -> object:
        if self.connections is None:
            from agent_platform.core_platform.platform_services.platform_settings.settings import (
                Settings,
            )

            from .connections import ApplicationConnectionService

            self.connections = ApplicationConnectionService(self.engine, Settings())
        return self.connections

    def _skill_service(self) -> object:
        if self.skills is None:
            from .skills import ApplicationSkillService

            self.skills = ApplicationSkillService(self.engine)
        return self.skills

    def _release_service(self) -> object:
        if self.releases is None:
            from .releases import ApplicationReleaseService

            self.releases = ApplicationReleaseService(
                self.engine,
                self._skill_service(),
            )
        return self.releases

    def _conversation_service(self) -> object:
        if self.conversations is None:
            from .conversations import ApplicationConversationService

            self.conversations = ApplicationConversationService(self.engine)
        return self.conversations

    @staticmethod
    def _normalise_rules(value: Any, *, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
        current = fallback or {
            "fallback": "handoff",
            "handoff_queue": "customer-service",
        }
        source = value if isinstance(value, dict) else current
        if not isinstance(source, dict):
            raise DomainError("service_application_rules_invalid", 422)
        resolved_fallback = str(source.get("fallback", current.get("fallback", "handoff"))).strip()
        if resolved_fallback not in {"handoff", "reply", "fail", "fallback"}:
            raise DomainError("service_application_rules_invalid", 422)
        handoff_queue = str(source.get("handoff_queue", current.get("handoff_queue", ""))).strip()
        if resolved_fallback == "handoff" and not handoff_queue:
            raise DomainError("service_application_handoff_queue_required", 422)
        if len(handoff_queue) > 100:
            raise DomainError("service_application_handoff_queue_invalid", 422)
        handoff_message = str(
            source.get("handoff_message", current.get("handoff_message", ""))
        ).strip()
        if len(handoff_message) > 1000:
            raise DomainError("service_application_handoff_message_invalid", 422)
        return {
            "fallback": resolved_fallback,
            "handoff_queue": handoff_queue,
            "handoff_message": handoff_message,
            "require_confirmation": bool(
                source.get(
                    "require_confirmation",
                    current.get("require_confirmation", True),
                )
            ),
            "preview_write_enabled": bool(
                source.get(
                    "preview_write_enabled",
                    current.get("preview_write_enabled", False),
                )
            ),
            "validate_results": bool(
                source.get("validate_results", current.get("validate_results", True))
            ),
        }

    @staticmethod
    def _normalise_draft(
        value: object,
        *,
        body: object | None = None,
        existing: dict[str, Any] | None = None,
        require_name: bool = True,
    ) -> tuple[dict[str, Any], str, int]:
        current = (
            ServiceApplicationService._config_from_row(existing) if existing is not None else {}
        )
        incoming = _json(value)
        raw = {**current, **incoming}
        old = sorted(field for field in _V1_FIELDS if field in raw)
        if old:
            raise DomainError(
                f"service_application_v1_fields_unsupported:{','.join(old)}",
                422,
            )
        schema_version = str(raw.get("schema_version") or "v2")
        if schema_version != "v2":
            raise DomainError("service_application_schema_version_invalid", 422)

        name_override = _provided(body, "name") if body is not None else _MISSING
        description_override = _provided(body, "description") if body is not None else _MISSING
        name_value = name_override if name_override is not _MISSING else raw.get("name")
        description_value = (
            description_override if description_override is not _MISSING else raw.get("description")
        )
        name = str(name_value or "").strip()
        description = str(description_value or "").strip()
        if require_name and not name:
            raise DomainError("service_application_name_required", 422)
        if len(name) > 100:
            raise DomainError("service_application_name_invalid", 422)
        if len(description) > 1000:
            raise DomainError("service_application_description_invalid", 422)

        agent = raw.get("agent") if isinstance(raw.get("agent"), dict) else {}
        agent_id_override = _provided(body, "agent_id") if body is not None else _MISSING
        version_override = _provided(body, "agent_version") if body is not None else _MISSING
        agent_id_value = (
            agent_id_override
            if agent_id_override is not _MISSING
            else raw.get("agent_id") or agent.get("id") or agent.get("agent_id")
        )
        agent_version_value = (
            version_override
            if version_override is not _MISSING
            else raw.get("agent_version") or agent.get("version") or agent.get("agent_version")
        )
        if agent_id_value is None:
            raise DomainError("service_application_agent_required", 422)
        if agent_version_value is None:
            raise DomainError("service_application_agent_version_required", 422)
        agent_id = _uuid(agent_id_value, "service_application_agent_invalid")
        try:
            agent_version = int(agent_version_value)
        except (TypeError, ValueError):
            raise DomainError("service_application_agent_version_invalid", 422) from None
        if agent_version < 1:
            raise DomainError("service_application_agent_version_invalid", 422)

        rules_override = _provided(body, "rules") if body is not None else _MISSING
        rules = ServiceApplicationService._normalise_rules(
            rules_override if rules_override is not _MISSING else raw.get("rules"),
            fallback=current.get("rules") if isinstance(current.get("rules"), dict) else None,
        )
        channels_override = _provided(body, "channels") if body is not None else _MISSING
        channels = (
            channels_override if channels_override is not _MISSING else raw.get("channels", [])
        )
        if not isinstance(channels, list):
            raise DomainError("service_application_channels_invalid", 422)
        for channel in channels:
            if not isinstance(channel, dict):
                raise DomainError("service_application_channels_invalid", 422)
        if raw.get("skills") not in (None, []):
            raise DomainError("service_application_embedded_skills_unsupported", 422)
        if raw.get("connections") not in (None, []):
            raise DomainError("service_application_embedded_connections_unsupported", 422)

        experience_override = _provided(body, "experience") if body is not None else _MISSING
        experience_value = (
            experience_override if experience_override is not _MISSING else raw.get("experience")
        )
        try:
            experience = ServiceExperienceConfig.model_validate(experience_value or {}).model_dump(
                mode="json"
            )
        except ValidationError as exc:
            raise DomainError("service_application_experience_invalid", 422) from exc

        draft = {
            "schema_version": "v2",
            "name": name,
            "description": description,
            "agent": {
                "id": agent_id,
                "version": agent_version,
                **(
                    {"name": str(agent["name"])}
                    if agent.get("name") and len(str(agent["name"])) <= 100
                    else {}
                ),
            },
            "rules": rules,
            "channels": channels,
            "skills": [],
            "connections": [],
            "experience": experience,
        }
        metadata = raw.get("metadata")
        if isinstance(metadata, dict):
            draft["metadata"] = metadata
        return draft, agent_id, agent_version

    @staticmethod
    def _config_from_row(row: dict[str, Any]) -> dict[str, Any]:
        draft = dict(row.get("draft") or {})
        draft["schema_version"] = "v2"
        draft["name"] = row.get("name") or draft.get("name") or ""
        draft["description"] = row.get("description") or ""
        draft["agent"] = {
            "id": str(row["agent_id"]),
            "version": row["agent_version"],
            **({"name": row["agent_name"]} if row.get("agent_name") else {}),
        }
        draft["rules"] = draft.get("rules") if isinstance(draft.get("rules"), dict) else {}
        draft["channels"] = draft.get("channels") if isinstance(draft.get("channels"), list) else []
        try:
            draft["experience"] = ServiceExperienceConfig.model_validate(
                draft.get("experience") or {}
            ).model_dump(mode="json")
        except ValidationError as exc:
            raise DomainError("service_application_experience_invalid", 422) from exc
        for old in _V1_FIELDS:
            draft.pop(old, None)
        draft.pop("agent_id", None)
        draft.pop("agent_version", None)
        draft.pop("skills", None)
        draft.pop("connections", None)
        return draft

    @staticmethod
    def _summary(row: dict[str, Any]) -> dict[str, Any]:
        config = ServiceApplicationService._config_from_row(row)
        published_at = row.get("published_at")
        updated_at = row.get("updated_at")
        try:
            changed_since_publish = (
                bool(updated_at > published_at)
                if published_at is not None and updated_at is not None
                else True
            )
        except TypeError:
            changed_since_publish = True
        has_unpublished = row.get("published_version") is None or changed_since_publish
        return {
            "id": str(row["id"]),
            "key": row["application_key"],
            "name": row["name"],
            "description": row["description"],
            "status": row["status"],
            "origin": row["origin"],
            "immutable": bool(row["immutable"]),
            "is_example": row["origin"] == "example",
            "template_key": row.get("template_key"),
            "template_version": row.get("template_version"),
            "agent_id": str(row["agent_id"]),
            "agent_version": row["agent_version"],
            "agent_name": row.get("agent_name"),
            "agent": {
                "id": str(row["agent_id"]),
                "name": row.get("agent_name"),
                "version": row["agent_version"],
                "published_version": row.get("agent_published_version"),
            },
            "draft_revision": row["draft_revision"],
            "revision": row["draft_revision"],
            "published_version": row.get("published_version"),
            "published_at": published_at,
            "archived": bool(row["archived"]),
            "config": config,
            "rules": config.get("rules", {}),
            "skill_count": row.get("skill_count", 0),
            "connection_count": row.get("connection_count", 0),
            "channel_count": row.get("channel_count", 0),
            "has_unpublished_changes": has_unpublished,
            "created_by": row.get("created_by"),
            "updated_by": row.get("updated_by"),
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
        }

    @staticmethod
    def _select_application_sql() -> str:
        return """
SELECT a.*,
       ag.name AS agent_name,
       ag.published_version AS agent_published_version,
       av.config AS published_config,
       av.created_at AS published_at,
       (
         SELECT count(*)::int
         FROM service_application_skills s
         WHERE s.tenant_id=a.tenant_id
           AND s.business_id=a.business_id
           AND s.workspace_id=a.workspace_id
           AND s.application_id=a.id
       ) AS skill_count,
       (
         SELECT count(*)::int
         FROM service_application_connections c
         WHERE c.tenant_id=a.tenant_id
           AND c.business_id=a.business_id
           AND c.workspace_id=a.workspace_id
           AND c.application_id=a.id
       ) AS connection_count
       ,
       (
         SELECT count(*)::int
         FROM channels ch
         WHERE ch.tenant_id=a.tenant_id
           AND ch.business_id=a.business_id
           AND ch.workspace_id=a.workspace_id
           AND ch.application_id=a.id
       ) AS channel_count
FROM service_applications a
LEFT JOIN agents ag
  ON ag.id=a.agent_id AND ag.tenant_id=a.tenant_id
LEFT JOIN service_application_versions av
  ON av.tenant_id=a.tenant_id
 AND av.business_id=a.business_id
 AND av.workspace_id=a.workspace_id
 AND av.application_id=a.id
 AND av.version=a.published_version
WHERE a.tenant_id=:tenant
  AND {scope_sql}
  {archived_sql}
"""

    @staticmethod
    def _skill_public(row: dict[str, Any]) -> dict[str, Any]:
        config = row.get("config") if isinstance(row.get("config"), dict) else {}
        item = {key: value for key, value in row.items() if key not in {"skill_key", "config"}}
        item["key"] = row.get("skill_key", row.get("key", item.get("id")))
        item["parameters"] = config.get("parameters", {})
        item["argument_mapping"] = config.get("argument_mapping", {})
        item["result_mapping"] = config.get("result_mapping", {})
        item["result_schema"] = config.get("result_schema", {})
        item["safety"] = config.get(
            "safety",
            {
                "requires_confirmation": False,
                "max_amount": None,
                "allowed_roles": [],
                "idempotency": "none",
                "timeout_seconds": 10,
                "on_error": "fail",
            },
        )
        item["write_operation"] = bool(config.get("write_operation", False))
        # Knowledge scope lives beside the mappings rather than inside them, so the
        # UI can read it without parsing ``config``. Empty means inherited.
        item["knowledge_base_ids"] = config.get("knowledge_base_ids") or []
        item["config"] = config
        item["last_test"] = row.get("last_test")
        return item

    @staticmethod
    def _connection_public(row: dict[str, Any]) -> dict[str, Any]:
        item = dict(row)
        if "connection_key" in item:
            item["key"] = item.pop("connection_key")
        item["credentials_configured"] = bool(item.get("credentials_configured"))
        item.pop("encrypted_secret", None)
        return item

    async def _row(
        self,
        connection: Any,
        tenant: str,
        scope: BusinessScope,
        *,
        key: str | None = None,
        application_id: str | None = None,
        include_archived: bool = False,
        for_update: bool = False,
        missing_code: str = "service_application_not_found",
    ) -> dict[str, Any]:
        scope_sql, scope_params = scope_predicate(scope, alias="a")
        predicate = "a.application_key=:key" if key is not None else "a.id=:application_id"
        sql = self._select_application_sql().format(
            scope_sql=scope_sql,
            archived_sql="" if include_archived else "AND NOT a.archived",
        )
        sql += f" AND {predicate}"
        if for_update:
            sql += " FOR UPDATE OF a"
        row = await one(
            connection,
            sql,
            tenant=tenant,
            key=key,
            application_id=application_id,
            **scope_params,
        )
        return required(row, missing_code)

    async def list(
        self,
        tenant: str,
        *,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
        status: str = "all",
        origin: str = "all",
        q: str = "",
        scope: BusinessScope | None = None,
        archived: bool = False,
    ) -> dict[str, Any]:
        page, page_size = _page_args(page, page_size)
        if status != "all" and status not in APPLICATION_STATUSES:
            raise DomainError("service_application_status_invalid", 422)
        if origin not in {"all", "user", "example"}:
            raise DomainError("service_application_origin_invalid", 422)
        resolved = persisted_scope(tenant, scope)
        scope_sql, scope_params = scope_predicate(resolved, alias="a")
        async with self.engine.connect() as connection:
            total_row = await one(
                connection,
                f"""
SELECT count(*)::int AS total
FROM service_applications a
WHERE a.tenant_id=:tenant AND {scope_sql}
  AND a.archived=:archived
  AND (:status='all' OR a.status=:status)
  AND (:origin='all' OR a.origin=:origin)
  AND (
    :q=''
    OR a.name ILIKE :pattern
    OR a.description ILIKE :pattern
    OR a.application_key ILIKE :pattern
  )
""",
                tenant=tenant,
                status=status,
                origin=origin,
                q=q,
                pattern=f"%{q}%",
                archived=archived,
                **scope_params,
            )
            rows = await many(
                connection,
                f"""
{
                    self._select_application_sql().format(
                        scope_sql=scope_sql,
                        archived_sql="AND a.archived=:archived",
                    )
                }
  AND (:status='all' OR a.status=:status)
  AND (:origin='all' OR a.origin=:origin)
  AND (
    :q=''
    OR a.name ILIKE :pattern
    OR a.description ILIKE :pattern
    OR a.application_key ILIKE :pattern
  )
ORDER BY a.updated_at DESC,a.name,a.id
LIMIT :limit OFFSET :offset
""",
                tenant=tenant,
                status=status,
                origin=origin,
                q=q,
                pattern=f"%{q}%",
                archived=archived,
                limit=page_size,
                offset=(page - 1) * page_size,
                **scope_params,
            )
        total = int((total_row or {}).get("total", 0))
        return {
            "items": [self._summary(row) for row in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size,
        }

    async def get(
        self,
        tenant: str,
        key: str,
        *,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        resolved = persisted_scope(tenant, scope)
        async with self.engine.connect() as connection:
            row = await self._row(connection, tenant, resolved, key=key)
            skill_rows = await many(
                connection,
                """
SELECT s.id,s.skill_key,s.type,s.name,s.description,s.enabled,s.config,
       s.revision,s.created_by,s.updated_by,s.created_at,s.updated_at,
       c.connection_key,c.name AS connection_name
FROM service_application_skills s
LEFT JOIN service_application_connections c
  ON c.id=s.connection_id
 AND c.application_id=s.application_id
 AND c.tenant_id=s.tenant_id
 AND c.business_id=s.business_id
 AND c.workspace_id=s.workspace_id
WHERE s.tenant_id=:tenant AND s.business_id=:scope_business
  AND s.workspace_id=:scope_workspace AND s.application_id=:application
ORDER BY s.skill_key
""",
                tenant=tenant,
                application=row["id"],
                scope_business=resolved.business_id,
                scope_workspace=resolved.workspace_id,
            )
            connection_rows = await many(
                connection,
                """
SELECT c.id,c.connection_key,c.name,c.executor_kind,c.endpoint,c.method,
       c.public_headers,c.auth_kind,c.timeout_seconds,c.max_response_bytes,
       c.config,c.revision,c.created_by,c.updated_by,c.created_at,c.updated_at,
       EXISTS(
         SELECT 1 FROM service_application_connection_credentials cc
         WHERE cc.connection_id=c.id
           AND cc.tenant_id=c.tenant_id
           AND cc.business_id=c.business_id
           AND cc.workspace_id=c.workspace_id
       ) AS credentials_configured
FROM service_application_connections c
WHERE c.tenant_id=:tenant AND c.business_id=:scope_business
  AND c.workspace_id=:scope_workspace AND c.application_id=:application
ORDER BY c.connection_key
""",
                tenant=tenant,
                application=row["id"],
                scope_business=resolved.business_id,
                scope_workspace=resolved.workspace_id,
            )
            channel_rows = await many(
                connection,
                """
SELECT id,name,provider,enabled,application_id,application_version,
       encrypted_credentials IS NOT NULL AS credentials_configured
FROM channels
WHERE tenant_id=:tenant AND business_id=:scope_business
  AND workspace_id=:scope_workspace AND application_id=:application
ORDER BY created_at DESC,id
""",
                tenant=tenant,
                application=row["id"],
                scope_business=resolved.business_id,
                scope_workspace=resolved.workspace_id,
            )
        result = self._summary(row)
        connections = [self._connection_public(item) for item in connection_rows]
        result.update(
            {
                "skills": [self._skill_public(item) for item in skill_rows],
                "connections": connections,
                "channels": channel_rows,
                "credential_health": {
                    "configured": sum(1 for item in connections if item["credentials_configured"]),
                    "missing": sum(
                        1
                        for item in connections
                        if item["auth_kind"] != "none" and not item["credentials_configured"]
                    ),
                },
            }
        )
        return result

    async def get_experience(
        self,
        tenant: str,
        key: str,
        *,
        version: int | None = None,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        resolved = persisted_scope(tenant, scope)
        async with self.engine.connect() as connection:
            row = await self._row(connection, tenant, resolved, key=key)
        config = self._config_from_row(row)
        if version is not None:
            released = await self._release_service().get_version(
                tenant,
                key,
                version,
                scope=resolved,
            )
            experience = ReleaseSnapshot.model_validate(released["config"]).experience
            return {
                "experience": experience.model_dump(mode="json"),
                "revision": row["draft_revision"],
                "immutable": True,
                "version": version,
            }
        return {
            "experience": config["experience"],
            "revision": row["draft_revision"],
            "immutable": bool(row["immutable"] or row["origin"] == "example"),
        }

    async def update_experience(
        self,
        tenant: str,
        actor: str,
        key: str,
        body: object,
        *,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        resolved = persisted_scope(tenant, scope)
        revision = int(_field(body, "revision", 0))
        if revision < 1:
            raise DomainError("service_application_revision_required", 422)
        try:
            experience = ServiceExperienceConfig.model_validate(
                _field(body, "experience")
            ).model_dump(mode="json")
        except ValidationError as exc:
            raise DomainError("service_application_experience_invalid", 422) from exc

        async with self.engine.begin() as connection:
            current = await self._row(
                connection,
                tenant,
                resolved,
                key=key,
                for_update=True,
            )
            if current["immutable"] or current["origin"] == "example":
                raise DomainError("service_application_example_immutable", 403)
            if current["draft_revision"] != revision:
                raise DomainError("service_application_revision_conflict", 409)
            draft = self._config_from_row(current)
            draft["experience"] = experience
            row = await one(
                connection,
                """
UPDATE service_applications
SET draft=CAST(:draft AS jsonb),
    draft_revision=draft_revision+1,
    updated_by=:actor,
    updated_at=now()
WHERE id=:id AND tenant_id=:tenant
RETURNING draft_revision
""",
                id=current["id"],
                tenant=tenant,
                draft=json.dumps(draft, ensure_ascii=False),
                actor=actor,
            )
            await audit(
                connection,
                tenant,
                actor,
                "service_application.experience_updated",
                current["id"],
                key=key,
                revision=row["draft_revision"],
                category_count=len(experience["categories"]),
                entry_count=sum(len(category["entries"]) for category in experience["categories"]),
            )
        return await self.get_experience(tenant, key, scope=scope)

    async def overview(
        self,
        tenant: str,
        *,
        origin: str = "all",
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        if origin not in {"all", "user", "example"}:
            raise DomainError("service_application_origin_invalid", 422)
        resolved = persisted_scope(tenant, scope)
        scope_sql, scope_params = scope_predicate(resolved, alias="a")
        async with self.engine.connect() as connection:
            rows = await many(
                connection,
                f"""
SELECT a.status,a.origin,count(*)::int AS count
FROM service_applications a
WHERE a.tenant_id=:tenant AND {scope_sql} AND NOT a.archived
  AND (:origin='all' OR a.origin=:origin)
GROUP BY a.status,a.origin
""",
                tenant=tenant,
                origin=origin,
                **scope_params,
            )
            counts = await one(
                connection,
                f"""
SELECT
  (SELECT count(*)::int FROM service_application_skills s
   JOIN service_applications sa ON sa.id=s.application_id AND sa.tenant_id=s.tenant_id
   WHERE s.tenant_id=:tenant AND {scope_predicate(resolved, alias="s")[0]}
     AND NOT sa.archived AND (:origin='all' OR sa.origin=:origin)) AS skills,
  (SELECT count(*)::int FROM service_application_connections c
   JOIN service_applications ca ON ca.id=c.application_id AND ca.tenant_id=c.tenant_id
   WHERE c.tenant_id=:tenant AND {scope_predicate(resolved, alias="c")[0]}
     AND NOT ca.archived AND (:origin='all' OR ca.origin=:origin)) AS connections,
  (SELECT count(*)::int FROM service_application_traces t
   JOIN service_applications ta ON ta.id=t.application_id AND ta.tenant_id=t.tenant_id
   WHERE t.tenant_id=:tenant AND {scope_predicate(resolved, alias="t")[0]}
     AND NOT ta.archived AND (:origin='all' OR ta.origin=:origin)) AS traces
""",
                tenant=tenant,
                origin=origin,
                **scope_params,
            )
        by_status = {status: 0 for status in APPLICATION_STATUSES}
        for row in rows:
            by_status[row["status"]] = row["count"]
        return {
            "applications": sum(by_status.values()),
            "by_status": by_status,
            "examples": sum(row["count"] for row in rows if row["origin"] == "example"),
            "published": by_status.get("published", 0),
            "skills": int((counts or {}).get("skills", 0)),
            "connections": int((counts or {}).get("connections", 0)),
            "traces": int((counts or {}).get("traces", 0)),
        }

    async def _validate_agent(
        self,
        connection: Any,
        tenant: str,
        scope: BusinessScope,
        agent_id: str,
        agent_version: int,
    ) -> dict[str, Any]:
        scope_sql, scope_params = scope_predicate(scope, alias="a")
        row = await one(
            connection,
            f"""
SELECT a.id,a.name,a.archived,a.published_version,av.version
FROM agents a
LEFT JOIN agent_versions av ON av.agent_id=a.id AND av.version=:agent_version
WHERE a.tenant_id=:tenant AND {scope_sql} AND a.id=:agent_id
""",
            tenant=tenant,
            agent_id=agent_id,
            agent_version=agent_version,
            **scope_params,
        )
        if row is None:
            raise DomainError("service_application_agent_not_found", 404)
        if row["archived"]:
            raise DomainError("service_application_agent_archived", 409)
        if row["version"] is None:
            raise DomainError("service_application_agent_version_not_found", 404)
        if row["published_version"] is None:
            raise DomainError("service_application_agent_not_published", 409)
        return row

    async def create(
        self,
        tenant: str,
        actor: str,
        key: str,
        body: Any,
        *,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        key = _key(key, "service_application_key_invalid")
        if key.startswith(EXAMPLE_KEY_PREFIX):
            raise DomainError("service_application_key_reserved", 422)
        resolved = persisted_scope(tenant, scope)
        draft, agent_id, agent_version = self._normalise_draft(body.config, body=body)
        _, scope_params = scope_predicate(resolved, alias="a")
        async with self.engine.begin() as connection:
            agent = await self._validate_agent(
                connection,
                tenant,
                resolved,
                agent_id,
                agent_version,
            )
            draft["agent"]["name"] = agent["name"]
            row = await one(
                connection,
                """
INSERT INTO service_applications(
    tenant_id,business_id,workspace_id,application_key,name,description,
    agent_id,agent_version,origin,immutable,status,draft,draft_revision,
    created_by,updated_by
) VALUES(
    :tenant,:scope_business,:scope_workspace,:key,:name,:description,
    :agent_id,:agent_version,'user',false,'draft',CAST(:draft AS jsonb),1,
    :actor,:actor
)
ON CONFLICT(tenant_id,business_id,workspace_id,application_key) DO NOTHING
RETURNING *
""",
                tenant=tenant,
                key=key,
                name=draft["name"],
                description=draft["description"],
                agent_id=agent_id,
                agent_version=agent_version,
                draft=json.dumps(draft, ensure_ascii=False),
                actor=actor,
                **scope_params,
            )
            if row is None:
                raise DomainError("service_application_key_conflict", 409)
            await audit(
                connection,
                tenant,
                actor,
                "service_application.created",
                row["id"],
                key=key,
                revision=row["draft_revision"],
                agent_id=agent_id,
                agent_version=agent_version,
            )
        return await self.get(tenant, key, scope=scope)

    async def update(
        self,
        tenant: str,
        actor: str,
        key: str,
        body: Any,
        *,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        resolved = persisted_scope(tenant, scope)
        revision = int(_field(body, "revision", 0))
        if revision < 1:
            raise DomainError("service_application_revision_required", 422)
        async with self.engine.begin() as connection:
            current = await self._row(
                connection,
                tenant,
                resolved,
                key=key,
                for_update=True,
            )
            if current["immutable"] or current["origin"] == "example":
                raise DomainError("service_application_example_immutable", 403)
            if current["draft_revision"] != revision:
                raise DomainError("service_application_revision_conflict", 409)
            draft, agent_id, agent_version = self._normalise_draft(
                body.config,
                body=body,
                existing=current,
            )
            agent = await self._validate_agent(
                connection,
                tenant,
                resolved,
                agent_id,
                agent_version,
            )
            draft["agent"]["name"] = agent["name"]
            row = await one(
                connection,
                """
UPDATE service_applications a
SET name=:name,description=:description,agent_id=:agent_id,
    agent_version=:agent_version,draft=CAST(:draft AS jsonb),
    draft_revision=draft_revision+1,updated_by=:actor,updated_at=now()
WHERE a.id=:id AND a.tenant_id=:tenant
RETURNING a.*
""",
                id=current["id"],
                tenant=tenant,
                name=draft["name"],
                description=draft["description"],
                agent_id=agent_id,
                agent_version=agent_version,
                draft=json.dumps(draft, ensure_ascii=False),
                actor=actor,
            )
            await audit(
                connection,
                tenant,
                actor,
                "service_application.updated",
                current["id"],
                key=key,
                revision=row["draft_revision"],
                agent_id=agent_id,
                agent_version=agent_version,
            )
        return await self.get(tenant, key, scope=scope)

    async def set_status(
        self,
        tenant: str,
        actor: str,
        key: str,
        status: str,
        revision: int,
        *,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        if status not in {"draft", "review", "offline"}:
            raise DomainError("service_application_status_invalid", 422)
        resolved = persisted_scope(tenant, scope)
        scope_sql, scope_params = scope_predicate(resolved, alias="a")
        async with self.engine.begin() as connection:
            current = await self._row(connection, tenant, resolved, key=key)
            if current["immutable"] or current["origin"] == "example":
                raise DomainError("service_application_example_immutable", 403)
            row = await one(
                connection,
                f"""
UPDATE service_applications a
SET status=:status,draft_revision=draft_revision+1,
    updated_by=:actor,updated_at=now()
WHERE a.id=:id AND a.tenant_id=:tenant AND {scope_sql}
  AND a.draft_revision=:revision AND NOT a.archived
RETURNING a.*
""",
                id=current["id"],
                tenant=tenant,
                status=status,
                actor=actor,
                revision=revision,
                **scope_params,
            )
            if row is None:
                raise DomainError("service_application_revision_conflict", 409)
            await audit(
                connection,
                tenant,
                actor,
                "service_application.status_changed",
                row["id"],
                key=key,
                status=status,
                revision=row["draft_revision"],
            )
        return await self.get(tenant, key, scope=scope)

    async def archive(
        self,
        tenant: str,
        actor: str,
        key: str,
        revision: int,
        *,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        resolved = persisted_scope(tenant, scope)
        async with self.engine.begin() as connection:
            current = await self._row(
                connection,
                tenant,
                resolved,
                key=key,
                for_update=True,
            )
            if current["immutable"] or current["origin"] == "example":
                raise DomainError("service_application_example_immutable", 403)
            if current["draft_revision"] != revision:
                raise DomainError("service_application_revision_conflict", 409)
            if current["published_version"] is not None and current["status"] != "offline":
                raise DomainError("service_application_must_be_offline", 409)
            row = await one(
                connection,
                """
UPDATE service_applications
SET archived=true,draft_revision=draft_revision+1,
    updated_by=:actor,updated_at=now()
WHERE id=:id AND tenant_id=:tenant
RETURNING *
""",
                id=current["id"],
                tenant=tenant,
                actor=actor,
            )
            await audit(
                connection,
                tenant,
                actor,
                "service_application.archived",
                current["id"],
                key=key,
                revision=row["draft_revision"],
            )
        row.update(
            {
                "agent_name": current.get("agent_name"),
                "published_config": current.get("published_config"),
                "skill_count": current.get("skill_count", 0),
                "connection_count": current.get("connection_count", 0),
            }
        )
        return self._summary(row)

    async def restore(
        self,
        tenant: str,
        actor: str,
        key: str,
        *,
        revision: int | None = None,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        resolved = persisted_scope(tenant, scope)
        async with self.engine.begin() as connection:
            row = await one(
                connection,
                """
SELECT * FROM service_applications
WHERE tenant_id=:tenant AND business_id=:scope_business
  AND workspace_id=:scope_workspace AND application_key=:key
  AND archived=true
FOR UPDATE
""",
                tenant=tenant,
                key=key,
                scope_business=resolved.business_id,
                scope_workspace=resolved.workspace_id,
            )
            if row is None:
                raise DomainError("service_application_archived_not_found", 404)
            if revision is not None and row["draft_revision"] != revision:
                raise DomainError("service_application_revision_conflict", 409)
            await execute(
                connection,
                """
UPDATE service_applications
SET archived=false,draft_revision=draft_revision+1,
    updated_by=:actor,updated_at=now()
WHERE id=:id
""",
                id=row["id"],
                actor=actor,
            )
            await audit(
                connection,
                tenant,
                actor,
                "service_application.restored",
                row["id"],
                key=key,
                revision=row["draft_revision"] + 1,
            )
        return await self.get(tenant, key, scope=scope)

    async def purge(
        self,
        tenant: str,
        actor: str,
        key: str,
        *,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        resolved = persisted_scope(tenant, scope)
        async with self.engine.begin() as connection:
            row = await one(
                connection,
                """
SELECT id,archived,origin,immutable FROM service_applications
WHERE tenant_id=:tenant AND business_id=:scope_business
  AND workspace_id=:scope_workspace AND application_key=:key
FOR UPDATE
""",
                tenant=tenant,
                key=key,
                scope_business=resolved.business_id,
                scope_workspace=resolved.workspace_id,
            )
            if row is None or not row["archived"]:
                raise DomainError("service_application_archived_not_found", 404)
            if row["origin"] == "example" or row["immutable"]:
                raise DomainError("service_application_example_immutable", 403)
            await execute(
                connection,
                "DELETE FROM service_applications WHERE id=:id AND tenant_id=:tenant",
                id=row["id"],
                tenant=tenant,
            )
            await audit(
                connection,
                tenant,
                actor,
                "service_application.purged",
                row["id"],
                key=key,
            )
        return {"key": key, "deleted": True}

    @staticmethod
    def _normalise_skill_config(
        body: object,
        *,
        current: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        base = dict(current or {})
        incoming = _json(_field(body, "config", {}))
        config = {
            key: incoming.get(key, base.get(key))
            for key in _SKILL_CONFIG_FIELDS
            if incoming.get(key, base.get(key)) is not None
        }
        for field_name in (
            "parameters",
            "argument_mapping",
            "result_mapping",
            "result_schema",
            "safety",
            "knowledge_base_ids",
        ):
            value = _provided(body, field_name)
            if value is not _MISSING:
                config[field_name] = value
        write_operation = _provided(body, "write_operation")
        if write_operation is _MISSING:
            write_operation = base.get("write_operation", False)
        if not isinstance(write_operation, bool):
            raise DomainError("service_application_skill_write_operation_invalid", 422)
        config["write_operation"] = write_operation

        parameters = config.get("parameters")
        if parameters in (None, {}):
            parameters = {
                "type": "object",
                "additionalProperties": False,
                "properties": {},
            }
        config["parameters"] = parameters
        config.setdefault("argument_mapping", {})
        config.setdefault("result_mapping", {})
        config.setdefault("result_schema", {})
        safety = config.get("safety")
        if safety is None:
            safety = {}
        if not isinstance(safety, dict):
            raise DomainError("service_application_skill_safety_invalid", 422)
        safety = dict(safety)
        if write_operation is False and safety.get("write_operation") is True:
            config["write_operation"] = True
            write_operation = True
        safety.pop("write_operation", None)
        safety.setdefault("requires_confirmation", False)
        safety.setdefault("max_amount", None)
        safety.setdefault("allowed_roles", [])
        safety.setdefault("idempotency", "none")
        safety.setdefault("timeout_seconds", 10)
        safety.setdefault("on_error", "fail")
        safety.setdefault("allow_confirmation_exemption", False)
        config["safety"] = safety
        return config

    @staticmethod
    def _skill_contract(
        *,
        key: str,
        skill_type: str,
        name: str,
        description: str,
        enabled: bool,
        connection_key: str | None,
        config: dict[str, Any],
    ) -> ApplicationSkill:
        try:
            return ApplicationSkill.model_validate(
                {
                    "key": key,
                    "type": skill_type,
                    "name": name,
                    "description": description,
                    "enabled": enabled,
                    "connection_key": connection_key,
                    **{
                        field: config.get(field)
                        for field in _SKILL_CONFIG_FIELDS
                        if field in config
                    },
                }
            )
        except ValidationError as exc:
            raise DomainError("service_application_skill_contract_invalid", 422) from exc

    async def readiness(
        self,
        tenant: str,
        key: str,
        *,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        release_readiness = await self._release_service().readiness(
            tenant,
            key,
            scope=scope,
        )
        application = await self.get(tenant, key, scope=scope)
        checks = []
        for check in release_readiness.checks:
            status = {
                "pass": "pass",
                "warning": "warning",
                "fail": "blocked",
            }[check.status.value]
            checks.append(
                {
                    "key": (f"{check.resource}:{check.code}" if check.resource else check.code),
                    "title": check.code,
                    "detail": check.message,
                    "status": status,
                    "severity": (
                        "blocking"
                        if status == "blocked"
                        else "warning"
                        if status == "warning"
                        else "info"
                    ),
                    "resource": check.resource,
                }
            )
        blocked = sum(1 for check in checks if check["status"] == "blocked")
        return {
            "status": "blocked" if blocked else "pass",
            "state": "blocked" if blocked else "ready",
            "can_publish": release_readiness.ready,
            "key": key,
            "application_key": key,
            "revision": application["draft_revision"],
            "checks": checks,
            "counts": {
                "pass": sum(1 for check in checks if check["status"] == "pass"),
                "warning": sum(1 for check in checks if check["status"] == "warning"),
                "blocked": blocked,
                "skills": application.get("skill_count", 0),
                "connections": application.get("connection_count", 0),
            },
        }

    async def publish(
        self,
        tenant: str,
        actor: str,
        key: str,
        revision: int,
        *,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        published = await self._release_service().publish(
            tenant,
            actor,
            key,
            revision,
            scope=scope,
        )
        result = await self.get(tenant, key, scope=scope)
        result["version"] = published["version"]
        result["config_digest"] = published["config_digest"]
        return result

    async def versions(
        self,
        tenant: str,
        key: str,
        *,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        result = await self._release_service().versions(
            tenant,
            key,
            page=page,
            page_size=page_size,
            scope=scope,
        )
        published_version = result.get("published_version")
        for item in result["items"]:
            item["published"] = item["version"] == published_version
            item["current"] = item["published"]
        total = int(result.get("total", 0))
        result["total_pages"] = (total + page_size - 1) // page_size
        return result

    async def rollback(
        self,
        tenant: str,
        actor: str,
        key: str,
        version: int,
        revision: int,
        *,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        rolled_back = await self._release_service().rollback(
            tenant,
            actor,
            key,
            version,
            revision,
            scope=scope,
        )
        result = await self.get(tenant, key, scope=scope)
        result["rollback_version"] = rolled_back["version"]
        result["source_version"] = rolled_back["source_version"]
        return result

    async def copy(
        self,
        tenant: str,
        actor: str,
        key: str,
        *,
        target_key: str | None = None,
        name: str | None = None,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        resolved = persisted_scope(tenant, scope)
        async with self.engine.begin() as connection:
            source = await self._row(
                connection,
                tenant,
                resolved,
                key=key,
                for_update=True,
            )
            if source["origin"] != "example" or not source["immutable"]:
                raise DomainError("service_application_copy_source_invalid", 422)
            default_key = key.removeprefix(EXAMPLE_KEY_PREFIX)
            new_key = target_key or f"{default_key}-copy"
            new_key = _key(new_key, "service_application_key_invalid")
            if new_key.startswith(EXAMPLE_KEY_PREFIX):
                raise DomainError("service_application_key_reserved", 422)
            new_name = (name or f"{source['name']} 副本").strip()
            if not new_name or len(new_name) > 100:
                raise DomainError("service_application_name_invalid", 422)
            draft = self._config_from_row(source)
            draft["name"] = new_name
            row = await one(
                connection,
                """
INSERT INTO service_applications(
    tenant_id,business_id,workspace_id,application_key,name,description,
    agent_id,agent_version,origin,immutable,status,draft,draft_revision,
    created_by,updated_by,template_key,template_version
) VALUES(
    :tenant,:scope_business,:scope_workspace,:key,:name,:description,
    :agent_id,:agent_version,'user',false,'draft',CAST(:draft AS jsonb),1,
    :actor,:actor,:template_key,:template_version
)
ON CONFLICT(tenant_id,business_id,workspace_id,application_key) DO NOTHING
RETURNING *
""",
                tenant=tenant,
                key=new_key,
                name=new_name,
                description=source["description"],
                agent_id=str(source["agent_id"]),
                agent_version=source["agent_version"],
                draft=json.dumps(draft, ensure_ascii=False),
                actor=actor,
                template_key=source.get("template_key") or key,
                template_version=source.get("template_version"),
                scope_business=resolved.business_id,
                scope_workspace=resolved.workspace_id,
            )
            if row is None:
                raise DomainError("service_application_key_conflict", 409)
            source_connections = await many(
                connection,
                """
SELECT * FROM service_application_connections
WHERE tenant_id=:tenant AND business_id=:scope_business
  AND workspace_id=:scope_workspace AND application_id=:application
ORDER BY connection_key
""",
                tenant=tenant,
                application=source["id"],
                scope_business=resolved.business_id,
                scope_workspace=resolved.workspace_id,
            )
            connection_map: dict[str, str] = {}
            for item in source_connections:
                copied = await one(
                    connection,
                    """
INSERT INTO service_application_connections(
    tenant_id,business_id,workspace_id,application_id,connection_key,
    name,executor_kind,endpoint,method,public_headers,auth_kind,
    timeout_seconds,max_response_bytes,config,revision,created_by,updated_by
) VALUES(
    :tenant,:scope_business,:scope_workspace,:application,:key,
    :name,:executor_kind,:endpoint,:method,CAST(:headers AS jsonb),:auth_kind,
    :timeout,:max_response,CAST(:config AS jsonb),1,:actor,:actor
)
RETURNING id
""",
                    tenant=tenant,
                    application=row["id"],
                    key=item["connection_key"],
                    name=item["name"],
                    executor_kind=item["executor_kind"],
                    endpoint=item["endpoint"],
                    method=item["method"],
                    headers=json.dumps(item["public_headers"]),
                    auth_kind=item["auth_kind"],
                    timeout=item["timeout_seconds"],
                    max_response=item["max_response_bytes"],
                    config=json.dumps(item["config"]),
                    actor=actor,
                    scope_business=resolved.business_id,
                    scope_workspace=resolved.workspace_id,
                )
                connection_map[str(item["id"])] = str(copied["id"])
            source_skills = await many(
                connection,
                """
SELECT * FROM service_application_skills
WHERE tenant_id=:tenant AND business_id=:scope_business
  AND workspace_id=:scope_workspace AND application_id=:application
ORDER BY skill_key
""",
                tenant=tenant,
                application=source["id"],
                scope_business=resolved.business_id,
                scope_workspace=resolved.workspace_id,
            )
            for item in source_skills:
                await execute(
                    connection,
                    """
INSERT INTO service_application_skills(
    tenant_id,business_id,workspace_id,application_id,skill_key,type,
    name,description,enabled,connection_id,config,revision,created_by,updated_by
) VALUES(
    :tenant,:scope_business,:scope_workspace,:application,:key,:type,
    :name,:description,:enabled,:connection_id,CAST(:config AS jsonb),1,
    :actor,:actor
)
""",
                    tenant=tenant,
                    application=row["id"],
                    key=item["skill_key"],
                    type=item["type"],
                    name=item["name"],
                    description=item["description"],
                    enabled=item["enabled"],
                    connection_id=connection_map.get(str(item["connection_id"])),
                    config=json.dumps(item["config"]),
                    actor=actor,
                    scope_business=resolved.business_id,
                    scope_workspace=resolved.workspace_id,
                )
            await audit(
                connection,
                tenant,
                actor,
                "service_application.copied_from_example",
                row["id"],
                source_key=key,
                key=new_key,
                template_key=source.get("template_key"),
                template_version=source.get("template_version"),
            )
        return await self.get(tenant, new_key, scope=scope)

    async def resolve_release(
        self,
        tenant: str,
        application_id: str,
        application_version: int | None,
        *,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        """Return an immutable release context for channel/runtime callers."""

        resolved = persisted_scope(tenant, scope)
        async with self.engine.connect() as connection:
            application = await self._row(
                connection,
                tenant,
                resolved,
                application_id=application_id,
            )
            version = application_version or application.get("published_version")
            if version is None:
                raise DomainError("service_application_not_published", 409)
            release = required(
                await one(
                    connection,
                    """
SELECT version,schema_version,config,config_digest,source_version,created_at
FROM service_application_versions
WHERE tenant_id=:tenant AND business_id=:scope_business
  AND workspace_id=:scope_workspace AND application_id=:application
  AND version=:version
""",
                    tenant=tenant,
                    application=application["id"],
                    version=version,
                    scope_business=resolved.business_id,
                    scope_workspace=resolved.workspace_id,
                ),
                "service_application_version_not_found",
            )
        return {
            "application": self._summary(application),
            "release": release,
        }

    async def traces(
        self,
        tenant: str,
        key: str,
        *,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
        limit: int | None = None,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        if limit is not None:
            if limit < 1 or limit > MAX_TRACE_LIMIT:
                raise DomainError("service_application_trace_limit_invalid", 422)
            page_size = limit
        result = await self._release_service().traces(
            tenant,
            key,
            page=page,
            page_size=page_size,
            scope=scope,
        )
        public_items: list[dict[str, Any]] = []
        for row in result["items"]:
            trace = row.get("trace") if isinstance(row.get("trace"), dict) else {}
            skill = trace.get("skill") if isinstance(trace.get("skill"), dict) else {}
            connection = (
                trace.get("connection") if isinstance(trace.get("connection"), dict) else {}
            )
            public_items.append(
                {
                    **row,
                    "skill_key": skill.get("key") or trace.get("skill_key"),
                    "connection_key": (connection.get("key") or trace.get("connection_key")),
                    "outcome": trace.get("outcome") or trace.get("status", "unknown"),
                    "reason_code": trace.get("reason_code"),
                    "duration_ms": trace.get("duration_ms"),
                }
            )
        result["items"] = public_items
        total = int(result.get("total", 0))
        result["total_pages"] = (total + page_size - 1) // page_size
        return result

    async def list_conversations(
        self,
        tenant: str,
        key: str,
        *,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
        q: str = "",
        channel_id: UUID | str | None = None,
        status: str = "all",
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        return await self._conversation_service().list(
            tenant,
            key,
            page=page,
            page_size=page_size,
            q=q,
            channel_id=channel_id,
            status=status,
            scope=scope,
        )

    async def get_conversation(
        self,
        tenant: str,
        key: str,
        conversation_id: UUID | str,
        *,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        return await self._conversation_service().get(
            tenant,
            key,
            conversation_id,
            scope=scope,
        )

    async def open_session(
        self,
        tenant: str,
        key: str,
        *,
        actor: str,
        scope: BusinessScope | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return await self._session_service().open_session(
            tenant,
            key,
            actor=actor,
            scope=scope,
            **kwargs,
        )

    async def send_session_message(
        self,
        tenant: str,
        key: str,
        conversation_id: UUID | str,
        content: str,
        *,
        actor: str,
        scope: BusinessScope | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return await self._session_service().send_message(
            tenant,
            key,
            conversation_id,
            content,
            actor=actor,
            scope=scope,
            **kwargs,
        )

    async def record_trace(
        self,
        tenant: str,
        *,
        application_id: str,
        application_version: int,
        agent_id: str,
        agent_version: int,
        trace: dict[str, Any],
        conversation_id: str | None = None,
        run_id: str | None = None,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        recorded = await self._release_service().record_trace(
            tenant,
            {
                "application_id": application_id,
                "application_version": application_version,
                "conversation_id": conversation_id,
                "run_id": run_id,
                "agent_id": agent_id,
                "agent_version": agent_version,
                "trace": _redacted(trace),
            },
            scope=scope,
        )
        return {
            "trace_id": str(recorded["id"]),
            "created_at": recorded["created_at"],
        }

    async def list_skills(
        self,
        tenant: str,
        key: str,
        *,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
        q: str = "",
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        page, page_size = _page_args(page, page_size)
        resolved = persisted_scope(tenant, scope)
        async with self.engine.connect() as connection:
            application = await self._row(connection, tenant, resolved, key=key)
            total_row = await one(
                connection,
                """
SELECT count(*)::int AS total
FROM service_application_skills s
WHERE s.tenant_id=:tenant AND s.business_id=:scope_business
  AND s.workspace_id=:scope_workspace AND s.application_id=:application
  AND (:q='' OR s.skill_key ILIKE :pattern OR s.name ILIKE :pattern)
""",
                tenant=tenant,
                application=application["id"],
                q=q,
                pattern=f"%{q}%",
                scope_business=resolved.business_id,
                scope_workspace=resolved.workspace_id,
            )
            rows = await many(
                connection,
                """
SELECT s.id,s.skill_key,s.type,s.name,s.description,s.enabled,s.config,
       s.revision,s.created_by,s.updated_by,s.created_at,s.updated_at,
       c.connection_key
FROM service_application_skills s
LEFT JOIN service_application_connections c
  ON c.id=s.connection_id
 AND c.application_id=s.application_id
 AND c.tenant_id=s.tenant_id
 AND c.business_id=s.business_id
 AND c.workspace_id=s.workspace_id
WHERE s.tenant_id=:tenant AND s.business_id=:scope_business
  AND s.workspace_id=:scope_workspace AND s.application_id=:application
  AND (:q='' OR s.skill_key ILIKE :pattern OR s.name ILIKE :pattern)
ORDER BY s.skill_key,s.id
LIMIT :limit OFFSET :offset
""",
                tenant=tenant,
                application=application["id"],
                q=q,
                pattern=f"%{q}%",
                limit=page_size,
                offset=(page - 1) * page_size,
                scope_business=resolved.business_id,
                scope_workspace=resolved.workspace_id,
            )
        rows = [self._skill_public(row) for row in rows]
        total = int((total_row or {}).get("total", 0))
        return {
            "items": rows,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size,
        }

    async def _skill_connection(
        self,
        connection: Any,
        tenant: str,
        scope: BusinessScope,
        application_id: str,
        body: object,
        *,
        fallback_id: object | None = None,
    ) -> tuple[str | None, str | None]:
        submitted_key = _provided(body, "connection_key")
        submitted_id = _provided(body, "connection_id")
        if submitted_key is _MISSING and submitted_id is _MISSING:
            submitted_id = fallback_id
        connection_key = (
            _key(submitted_key, "service_application_skill_connection_key_invalid")
            if submitted_key not in (_MISSING, None)
            else None
        )
        connection_id = (
            _uuid(submitted_id, "service_application_skill_connection_id_invalid")
            if submitted_id not in (_MISSING, None)
            else None
        )
        if connection_key is None and connection_id is None:
            return None, None
        conditions = []
        if connection_key is not None:
            conditions.append("connection_key=:connection_key")
        if connection_id is not None:
            conditions.append("id=:connection_id")
        row = await one(
            connection,
            f"""
SELECT id,connection_key FROM service_application_connections
WHERE tenant_id=:tenant AND business_id=:scope_business
  AND workspace_id=:scope_workspace AND application_id=:application
  AND {" AND ".join(conditions)}
""",
            tenant=tenant,
            application=application_id,
            connection_key=connection_key,
            connection_id=connection_id,
            scope_business=scope.business_id,
            scope_workspace=scope.workspace_id,
        )
        if row is None:
            raise DomainError("service_application_skill_connection_not_found", 422)
        return str(row["id"]), str(row["connection_key"])

    async def _skill_knowledge_bases(
        self,
        connection: Any,
        tenant: str,
        scope: BusinessScope,
        body: object,
    ) -> None:
        """Reject knowledge bases this release could never search.

        Retrieval fails the whole tool call with ``knowledge_base_not_found`` when a
        single id is missing or disabled, so a stale id would surface as a broken
        assistant in a preview rather than as a validation error at save time.
        """

        submitted = _provided(body, "knowledge_base_ids")
        if submitted in (_MISSING, None):
            return
        ids = [str(item) for item in submitted if str(item)]
        if not ids:
            return
        rows = await many(
            connection,
            """
SELECT k.id FROM knowledge_bases k
WHERE k.tenant_id=:tenant
  AND k.business_id=:scope_business
  AND k.workspace_id=:scope_workspace
  AND k.enabled
  AND k.id=ANY(CAST(:ids AS uuid[]))
""",
            tenant=tenant,
            scope_business=scope.business_id,
            scope_workspace=scope.workspace_id,
            ids=ids,
        )
        if {str(row["id"]) for row in rows} != set(ids):
            raise DomainError("service_application_knowledge_base_not_found", 422)

    async def create_skill(
        self,
        tenant: str,
        actor: str,
        key: str,
        body: object,
        *,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        resolved = persisted_scope(tenant, scope)
        skill_key = _key(_field(body, "key"), "service_application_skill_key_invalid")
        skill_type = str(_field(body, "type", ""))
        if skill_type not in SKILL_TYPES:
            raise DomainError("service_application_skill_type_invalid", 422)
        name = str(_field(body, "name", "")).strip()
        if not name or len(name) > 100:
            raise DomainError("service_application_skill_name_invalid", 422)
        description = str(_field(body, "description", "")).strip()
        if len(description) > 1000:
            raise DomainError("service_application_skill_description_invalid", 422)
        enabled = bool(_field(body, "enabled", True))
        async with self.engine.begin() as connection:
            application = await self._row(
                connection,
                tenant,
                resolved,
                key=key,
                for_update=True,
            )
            if application["immutable"] or application["origin"] == "example":
                raise DomainError("service_application_example_immutable", 403)
            connection_id, connection_key = await self._skill_connection(
                connection,
                tenant,
                resolved,
                application["id"],
                body,
            )
            await self._skill_knowledge_bases(connection, tenant, resolved, body)
            config = self._normalise_skill_config(body)
            contract = self._skill_contract(
                key=skill_key,
                skill_type=skill_type,
                name=name,
                description=description,
                enabled=enabled,
                connection_key=connection_key,
                config=config,
            )
            config = contract.model_dump(
                mode="json",
                exclude={
                    "key",
                    "type",
                    "name",
                    "description",
                    "enabled",
                    "connection_key",
                },
            )
            row = await one(
                connection,
                """
INSERT INTO service_application_skills(
    tenant_id,business_id,workspace_id,application_id,skill_key,type,
    name,description,enabled,connection_id,config,revision,created_by,updated_by
) VALUES(
    :tenant,:scope_business,:scope_workspace,:application,:key,:type,
    :name,:description,:enabled,:connection_id,CAST(:config AS jsonb),1,:actor,:actor
)
ON CONFLICT(tenant_id,business_id,workspace_id,application_id,skill_key) DO NOTHING
RETURNING *
""",
                tenant=tenant,
                application=application["id"],
                key=skill_key,
                type=skill_type,
                name=name,
                description=description,
                enabled=enabled,
                connection_id=connection_id,
                config=json.dumps(config, ensure_ascii=False),
                actor=actor,
                scope_business=resolved.business_id,
                scope_workspace=resolved.workspace_id,
            )
            if row is None:
                raise DomainError("service_application_skill_key_conflict", 409)
            await self._bump_application_revision(connection, tenant, application["id"], actor)
            await audit(
                connection,
                tenant,
                actor,
                "service_application.skill_created",
                row["id"],
                application_key=key,
                skill_key=skill_key,
                skill_type=skill_type,
                confirmed=bool(contract.safety.requires_confirmation),
            )
        result = await self.list_skills(
            tenant,
            key,
            page_size=MAX_PAGE_SIZE,
            q=skill_key,
            scope=scope,
        )
        return next(item for item in result["items"] if item["key"] == skill_key)

    async def update_skill(
        self,
        tenant: str,
        actor: str,
        key: str,
        skill_key: str,
        body: object,
        *,
        enabled_only: bool = False,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        resolved = persisted_scope(tenant, scope)
        revision = int(_field(body, "revision", 0))
        if revision < 1:
            raise DomainError("service_application_skill_revision_required", 422)
        async with self.engine.begin() as connection:
            application = await self._row(
                connection,
                tenant,
                resolved,
                key=key,
                for_update=True,
            )
            if application["immutable"] or application["origin"] == "example":
                raise DomainError("service_application_example_immutable", 403)
            current = required(
                await one(
                    connection,
                    """
SELECT s.*,c.connection_key
FROM service_application_skills s
LEFT JOIN service_application_connections c
  ON c.id=s.connection_id
 AND c.tenant_id=s.tenant_id
 AND c.business_id=s.business_id
 AND c.workspace_id=s.workspace_id
WHERE s.tenant_id=:tenant AND s.business_id=:scope_business
  AND s.workspace_id=:scope_workspace AND s.application_id=:application
  AND s.skill_key=:skill_key
FOR UPDATE OF s
""",
                    tenant=tenant,
                    application=application["id"],
                    skill_key=skill_key,
                    scope_business=resolved.business_id,
                    scope_workspace=resolved.workspace_id,
                ),
                "service_application_skill_not_found",
            )
            if current["revision"] != revision:
                raise DomainError("service_application_skill_revision_conflict", 409)
            if enabled_only:
                await execute(
                    connection,
                    """
UPDATE service_application_skills
SET enabled=:enabled,revision=revision+1,
    updated_by=:actor,updated_at=now()
WHERE id=:id
""",
                    id=current["id"],
                    enabled=bool(_field(body, "enabled", not current["enabled"])),
                    actor=actor,
                )
            else:
                skill_type = str(_provided(body, "type", current["type"]))
                if skill_type not in SKILL_TYPES:
                    raise DomainError("service_application_skill_type_invalid", 422)
                name = str(_provided(body, "name", current["name"])).strip()
                if not name or len(name) > 100:
                    raise DomainError("service_application_skill_name_invalid", 422)
                description = str(_provided(body, "description", current["description"])).strip()
                if len(description) > 1000:
                    raise DomainError(
                        "service_application_skill_description_invalid",
                        422,
                    )
                enabled = bool(_provided(body, "enabled", current["enabled"]))
                connection_id, connection_key = await self._skill_connection(
                    connection,
                    tenant,
                    resolved,
                    application["id"],
                    body,
                    fallback_id=current["connection_id"],
                )
                await self._skill_knowledge_bases(connection, tenant, resolved, body)
                config = self._normalise_skill_config(
                    body,
                    current=(current["config"] if isinstance(current["config"], dict) else {}),
                )
                contract = self._skill_contract(
                    key=skill_key,
                    skill_type=skill_type,
                    name=name,
                    description=description,
                    enabled=enabled,
                    connection_key=connection_key,
                    config=config,
                )
                config = contract.model_dump(
                    mode="json",
                    exclude={
                        "key",
                        "type",
                        "name",
                        "description",
                        "enabled",
                        "connection_key",
                    },
                )
                await execute(
                    connection,
                    """
UPDATE service_application_skills
SET type=:type,name=:name,description=:description,
    enabled=:enabled,connection_id=:connection_id,
    config=CAST(:config AS jsonb),revision=revision+1,
    updated_by=:actor,updated_at=now()
WHERE id=:id
""",
                    id=current["id"],
                    type=skill_type,
                    name=name,
                    description=description,
                    enabled=enabled,
                    connection_id=connection_id,
                    config=json.dumps(config, ensure_ascii=False),
                    actor=actor,
                )
            await self._bump_application_revision(connection, tenant, application["id"], actor)
            await audit(
                connection,
                tenant,
                actor,
                "service_application.skill_updated",
                current["id"],
                application_key=key,
                skill_key=skill_key,
                enabled_only=enabled_only,
            )
        result = await self.list_skills(
            tenant,
            key,
            page_size=MAX_PAGE_SIZE,
            q=skill_key,
            scope=scope,
        )
        return next(item for item in result["items"] if item["key"] == skill_key)

    async def delete_skill(
        self,
        tenant: str,
        actor: str,
        key: str,
        skill_key: str,
        *,
        revision: int | None = None,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        resolved = persisted_scope(tenant, scope)
        async with self.engine.begin() as connection:
            application = await self._row(
                connection,
                tenant,
                resolved,
                key=key,
                for_update=True,
            )
            if application["immutable"] or application["origin"] == "example":
                raise DomainError("service_application_example_immutable", 403)
            if revision is not None:
                current = await one(
                    connection,
                    """
SELECT revision FROM service_application_skills
WHERE tenant_id=:tenant AND business_id=:scope_business
  AND workspace_id=:scope_workspace AND application_id=:application
  AND skill_key=:skill_key
FOR UPDATE
""",
                    tenant=tenant,
                    application=application["id"],
                    skill_key=skill_key,
                    scope_business=resolved.business_id,
                    scope_workspace=resolved.workspace_id,
                )
                if current is None:
                    raise DomainError("service_application_skill_not_found", 404)
                if current["revision"] != revision:
                    raise DomainError(
                        "service_application_skill_revision_conflict",
                        409,
                    )
            result = await execute(
                connection,
                """
DELETE FROM service_application_skills
WHERE tenant_id=:tenant AND business_id=:scope_business
  AND workspace_id=:scope_workspace AND application_id=:application
  AND skill_key=:skill_key
""",
                tenant=tenant,
                application=application["id"],
                skill_key=skill_key,
                scope_business=resolved.business_id,
                scope_workspace=resolved.workspace_id,
            )
            if not result.rowcount:
                raise DomainError("service_application_skill_not_found", 404)
            await self._bump_application_revision(connection, tenant, application["id"], actor)
            await audit(
                connection,
                tenant,
                actor,
                "service_application.skill_deleted",
                application["id"],
                application_key=key,
                skill_key=skill_key,
            )
        return {"key": skill_key, "deleted": True}

    async def list_connections(
        self,
        tenant: str,
        key: str,
        *,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
        q: str = "",
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        page, page_size = _page_args(page, page_size)
        resolved = persisted_scope(tenant, scope)
        async with self.engine.connect() as connection:
            application = await self._row(connection, tenant, resolved, key=key)
            total_row = await one(
                connection,
                """
SELECT count(*)::int AS total
FROM service_application_connections c
WHERE c.tenant_id=:tenant AND c.business_id=:scope_business
  AND c.workspace_id=:scope_workspace AND c.application_id=:application
  AND (:q='' OR c.connection_key ILIKE :pattern OR c.name ILIKE :pattern)
""",
                tenant=tenant,
                application=application["id"],
                q=q,
                pattern=f"%{q}%",
                scope_business=resolved.business_id,
                scope_workspace=resolved.workspace_id,
            )
            rows = await many(
                connection,
                """
SELECT c.id,c.connection_key,c.name,c.executor_kind,c.endpoint,c.method,
       c.public_headers,c.auth_kind,c.timeout_seconds,c.max_response_bytes,
       c.config,c.revision,c.created_by,c.updated_by,c.created_at,c.updated_at,
       EXISTS(
         SELECT 1 FROM service_application_connection_credentials cc
         WHERE cc.connection_id=c.id
           AND cc.tenant_id=c.tenant_id
           AND cc.business_id=c.business_id
           AND cc.workspace_id=c.workspace_id
       ) AS credentials_configured
FROM service_application_connections c
WHERE c.tenant_id=:tenant AND c.business_id=:scope_business
  AND c.workspace_id=:scope_workspace AND c.application_id=:application
  AND (:q='' OR c.connection_key ILIKE :pattern OR c.name ILIKE :pattern)
ORDER BY c.connection_key,c.id
LIMIT :limit OFFSET :offset
""",
                tenant=tenant,
                application=application["id"],
                q=q,
                pattern=f"%{q}%",
                limit=page_size,
                offset=(page - 1) * page_size,
                scope_business=resolved.business_id,
                scope_workspace=resolved.workspace_id,
            )
        for row in rows:
            row["key"] = row.pop("connection_key")
        total = int((total_row or {}).get("total", 0))
        return {
            "items": rows,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size,
        }

    @staticmethod
    def _validate_connection(
        body: object,
        *,
        fallback: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        current = fallback or {}
        executor_kind = str(_provided(body, "executor_kind", current.get("executor_kind", "http")))
        if executor_kind not in CONNECTION_KINDS:
            raise DomainError("service_application_connection_kind_invalid", 422)
        method = str(_provided(body, "method", current.get("method", "POST"))).upper()
        if method not in HTTP_METHODS:
            raise DomainError("service_application_connection_method_invalid", 422)
        auth_kind = str(_provided(body, "auth_kind", current.get("auth_kind", "none")))
        if auth_kind not in AUTH_KINDS:
            raise DomainError("service_application_connection_auth_invalid", 422)
        endpoint = _provided(body, "endpoint", current.get("endpoint"))
        if endpoint is not None:
            endpoint = str(endpoint).strip()
        if executor_kind == "http":
            if not endpoint:
                raise DomainError("service_application_connection_endpoint_required", 422)
            parsed = urlparse(endpoint)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise DomainError("service_application_connection_endpoint_invalid", 422)
            if parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise DomainError("service_application_connection_endpoint_invalid", 422)
        headers = _provided(
            body,
            "public_headers",
            current.get("public_headers", {}),
        )
        if not isinstance(headers, dict):
            raise DomainError("service_application_connection_headers_invalid", 422)
        normalized_headers: dict[str, str] = {}
        normalized_header_names: set[str] = set()
        for header, value in headers.items():
            header_name = str(header).strip()
            lowered = header_name.lower()
            if not _HEADER_NAME_PATTERN.fullmatch(header_name):
                raise DomainError("service_application_connection_header_invalid", 422)
            if lowered in normalized_header_names:
                raise DomainError("service_application_connection_header_duplicate", 422)
            if lowered in _SENSITIVE_HEADERS or "token" in lowered or "secret" in lowered:
                raise DomainError("service_application_connection_header_sensitive", 422)
            if not isinstance(value, str):
                raise DomainError("service_application_connection_headers_invalid", 422)
            normalized_header_names.add(lowered)
            normalized_headers[header_name] = value
        try:
            timeout_seconds = int(
                _provided(
                    body,
                    "timeout_seconds",
                    current.get("timeout_seconds", 10),
                )
            )
            max_response_bytes = int(
                _provided(
                    body,
                    "max_response_bytes",
                    current.get("max_response_bytes", 16000),
                )
            )
        except (TypeError, ValueError):
            raise DomainError("service_application_connection_limits_invalid", 422) from None
        if not 1 <= timeout_seconds <= 60:
            raise DomainError("service_application_connection_timeout_invalid", 422)
        if not 128 <= max_response_bytes <= 100000:
            raise DomainError("service_application_connection_response_limit_invalid", 422)
        config_value = _provided(body, "config", current.get("config", {}))
        config = _json(config_value)
        if not isinstance(config_value, dict) and not hasattr(config_value, "model_dump"):
            raise DomainError("service_application_connection_config_invalid", 422)
        if _contains_secret(config):
            raise DomainError(
                "service_application_connection_config_secret_forbidden",
                422,
            )
        header_name = config.get("header_name")
        if auth_kind == "custom":
            if not isinstance(header_name, str) or not _HEADER_NAME_PATTERN.fullmatch(header_name):
                raise DomainError(
                    "service_application_connection_custom_header_required",
                    422,
                )
            if (
                header_name.lower() in _SENSITIVE_HEADERS
                or "token" in header_name.lower()
                or "secret" in header_name.lower()
            ):
                raise DomainError("service_application_connection_header_sensitive", 422)
        return {
            "executor_kind": executor_kind,
            "endpoint": endpoint,
            "method": method,
            "public_headers": normalized_headers,
            "auth_kind": auth_kind,
            "timeout_seconds": timeout_seconds,
            "max_response_bytes": max_response_bytes,
            "config": config,
        }

    async def create_connection(
        self,
        tenant: str,
        actor: str,
        key: str,
        body: object,
        *,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        resolved = persisted_scope(tenant, scope)
        connection_key = _key(
            _field(body, "key"),
            "service_application_connection_key_invalid",
        )
        name = str(_field(body, "name", "")).strip()
        if not name or len(name) > 100:
            raise DomainError("service_application_connection_name_invalid", 422)
        values = self._validate_connection(body)
        async with self.engine.begin() as connection:
            application = await self._row(
                connection,
                tenant,
                resolved,
                key=key,
                for_update=True,
            )
            if application["immutable"] or application["origin"] == "example":
                raise DomainError("service_application_example_immutable", 403)
            row = await one(
                connection,
                """
INSERT INTO service_application_connections(
    tenant_id,business_id,workspace_id,application_id,connection_key,
    name,executor_kind,endpoint,method,public_headers,auth_kind,
    timeout_seconds,max_response_bytes,config,revision,created_by,updated_by
) VALUES(
    :tenant,:scope_business,:scope_workspace,:application,:key,
    :name,:executor_kind,:endpoint,:method,CAST(:headers AS jsonb),:auth_kind,
    :timeout,:max_response,CAST(:config AS jsonb),1,:actor,:actor
)
ON CONFLICT(tenant_id,business_id,workspace_id,application_id,connection_key)
DO NOTHING
RETURNING *
""",
                tenant=tenant,
                application=application["id"],
                key=connection_key,
                name=name,
                executor_kind=values["executor_kind"],
                endpoint=values["endpoint"],
                method=values["method"],
                headers=json.dumps(values["public_headers"], ensure_ascii=False),
                auth_kind=values["auth_kind"],
                timeout=values["timeout_seconds"],
                max_response=values["max_response_bytes"],
                config=json.dumps(values["config"], ensure_ascii=False),
                actor=actor,
                scope_business=resolved.business_id,
                scope_workspace=resolved.workspace_id,
            )
            if row is None:
                raise DomainError("service_application_connection_key_conflict", 409)
            await self._bump_application_revision(connection, tenant, application["id"], actor)
            await audit(
                connection,
                tenant,
                actor,
                "service_application.connection_created",
                row["id"],
                application_key=key,
                connection_key=connection_key,
                auth_kind=values["auth_kind"],
            )
        result = await self.list_connections(
            tenant,
            key,
            page_size=MAX_PAGE_SIZE,
            q=connection_key,
            scope=scope,
        )
        return next(item for item in result["items"] if item["key"] == connection_key)

    async def update_connection(
        self,
        tenant: str,
        actor: str,
        key: str,
        connection_key: str,
        body: object,
        *,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        resolved = persisted_scope(tenant, scope)
        revision = int(_field(body, "revision", 0))
        if revision < 1:
            raise DomainError("service_application_connection_revision_required", 422)
        async with self.engine.begin() as connection:
            application = await self._row(
                connection,
                tenant,
                resolved,
                key=key,
                for_update=True,
            )
            if application["immutable"] or application["origin"] == "example":
                raise DomainError("service_application_example_immutable", 403)
            current = required(
                await one(
                    connection,
                    """
SELECT * FROM service_application_connections
WHERE tenant_id=:tenant AND business_id=:scope_business
  AND workspace_id=:scope_workspace AND application_id=:application
  AND connection_key=:connection_key
FOR UPDATE
""",
                    tenant=tenant,
                    application=application["id"],
                    connection_key=connection_key,
                    scope_business=resolved.business_id,
                    scope_workspace=resolved.workspace_id,
                ),
                "service_application_connection_not_found",
            )
            if current["revision"] != revision:
                raise DomainError("service_application_connection_revision_conflict", 409)
            values = self._validate_connection(body, fallback=current)
            name = str(_provided(body, "name", current["name"])).strip()
            if not name or len(name) > 100:
                raise DomainError("service_application_connection_name_invalid", 422)
            await execute(
                connection,
                """
UPDATE service_application_connections
SET name=:name,executor_kind=:executor_kind,endpoint=:endpoint,
    method=:method,public_headers=CAST(:headers AS jsonb),
    auth_kind=:auth_kind,timeout_seconds=:timeout,
    max_response_bytes=:max_response,config=CAST(:config AS jsonb),
    revision=revision+1,updated_by=:actor,updated_at=now()
WHERE id=:id
""",
                id=current["id"],
                name=name,
                executor_kind=values["executor_kind"],
                endpoint=values["endpoint"],
                method=values["method"],
                headers=json.dumps(values["public_headers"], ensure_ascii=False),
                auth_kind=values["auth_kind"],
                timeout=values["timeout_seconds"],
                max_response=values["max_response_bytes"],
                config=json.dumps(values["config"], ensure_ascii=False),
                actor=actor,
            )
            await self._bump_application_revision(connection, tenant, application["id"], actor)
            await audit(
                connection,
                tenant,
                actor,
                "service_application.connection_updated",
                current["id"],
                application_key=key,
                connection_key=connection_key,
                auth_kind=values["auth_kind"],
            )
        result = await self.list_connections(
            tenant,
            key,
            page_size=MAX_PAGE_SIZE,
            q=connection_key,
            scope=scope,
        )
        return next(item for item in result["items"] if item["key"] == connection_key)

    async def delete_connection(
        self,
        tenant: str,
        actor: str,
        key: str,
        connection_key: str,
        *,
        revision: int | None = None,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        resolved = persisted_scope(tenant, scope)
        async with self.engine.begin() as connection:
            application = await self._row(
                connection,
                tenant,
                resolved,
                key=key,
                for_update=True,
            )
            if application["immutable"] or application["origin"] == "example":
                raise DomainError("service_application_example_immutable", 403)
            target = required(
                await one(
                    connection,
                    """
SELECT id,revision FROM service_application_connections
WHERE tenant_id=:tenant AND business_id=:scope_business
  AND workspace_id=:scope_workspace AND application_id=:application
  AND connection_key=:connection_key
FOR UPDATE
""",
                    tenant=tenant,
                    application=application["id"],
                    connection_key=connection_key,
                    scope_business=resolved.business_id,
                    scope_workspace=resolved.workspace_id,
                ),
                "service_application_connection_not_found",
            )
            if revision is not None and target["revision"] != revision:
                raise DomainError(
                    "service_application_connection_revision_conflict",
                    409,
                )
            referenced = await one(
                connection,
                """
SELECT count(*)::int AS count
FROM service_application_skills
WHERE tenant_id=:tenant AND business_id=:scope_business
  AND workspace_id=:scope_workspace AND application_id=:application
  AND connection_id=:connection_id
""",
                tenant=tenant,
                application=application["id"],
                connection_id=target["id"],
                scope_business=resolved.business_id,
                scope_workspace=resolved.workspace_id,
            )
            if int((referenced or {}).get("count", 0)) > 0:
                raise DomainError("service_application_connection_in_use", 409)
            await execute(
                connection,
                "DELETE FROM service_application_connections WHERE id=:id",
                id=target["id"],
            )
            await self._bump_application_revision(connection, tenant, application["id"], actor)
            await audit(
                connection,
                tenant,
                actor,
                "service_application.connection_deleted",
                application["id"],
                application_key=key,
                connection_key=connection_key,
            )
        return {"key": connection_key, "deleted": True}

    async def save_credentials(
        self,
        tenant: str,
        actor: str,
        key: str,
        connection_key: str,
        body: object,
        *,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        method = getattr(self._connection_service(), "set_credentials", None)
        if method is None:
            raise DomainError("service_application_credentials_service_unavailable", 503)
        credential_input = _field(body, "credentials")
        if not isinstance(credential_input, dict):
            raise DomainError("service_application_credentials_invalid", 422)
        credential_type = str(credential_input.get("type") or "").strip()
        if credential_type == "none":
            raise DomainError(
                "service_application_credentials_not_applicable",
                422,
            )
        if credential_type == "bearer":
            token = str(credential_input.get("token") or "").strip()
            if not token:
                raise DomainError("service_application_credential_token_required", 422)
            payload = {
                "auth_kind": "bearer",
                "secret": token,
            }
        elif credential_type == "api_key":
            token = str(credential_input.get("token") or "").strip()
            header_name = str(credential_input.get("header_name") or "").strip()
            if not token or not header_name:
                raise DomainError(
                    "service_application_credential_api_key_invalid",
                    422,
                )
            payload = {
                "auth_kind": "api_key",
                "secret": token,
                "header_name": header_name,
            }
        elif credential_type == "custom":
            headers = credential_input.get("headers")
            if not isinstance(headers, dict) or len(headers) != 1:
                raise DomainError(
                    "service_application_credential_custom_header_count_invalid",
                    422,
                )
            header_name, token = next(iter(headers.items()))
            if not str(token).strip():
                raise DomainError("service_application_credential_token_required", 422)
            payload = {
                "auth_kind": "custom",
                "secret": str(token),
                "header_name": str(header_name).strip(),
            }
        else:
            raise DomainError("service_application_credentials_type_invalid", 422)
        try:
            validated = ConnectionCredentialInput.model_validate(payload)
        except ValidationError:
            raise DomainError(
                "service_application_credentials_contract_invalid",
                422,
            ) from None
        result = await method(
            tenant,
            actor,
            key,
            connection_key,
            validated,
            scope=scope,
        )
        if hasattr(result, "model_dump"):
            return result.model_dump(mode="json")
        return dict(result)

    async def test_connection(
        self,
        tenant: str,
        actor: str,
        key: str,
        connection_key: str,
        *,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        method = getattr(self._connection_service(), "test", None)
        if method is None:
            raise DomainError("service_application_connection_test_unavailable", 503)
        return await method(
            tenant,
            key,
            connection_key,
            scope=scope,
        )

    async def preview(
        self,
        tenant: str,
        actor: str,
        key: str,
        body: object,
        *,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        """Run a side-effect-free preview of the draft or a frozen release."""

        del actor
        runner = self.preview_runner
        if runner is None or not hasattr(runner, "preview_application"):
            raise DomainError("service_application_preview_unavailable", 503)
        message = str(_field(body, "message", "")).strip()
        if not message:
            raise DomainError("service_application_preview_message_required", 422)
        if len(message) > 2000:
            raise DomainError("service_application_preview_message_invalid", 422)
        requested_version = _provided(body, "version", None)
        requested_skill = _provided(body, "skill_key", None)
        allow_write = bool(_provided(body, "allow_write", False))
        resolved = persisted_scope(tenant, scope)
        async with self.engine.connect() as connection:
            application = await self._row(connection, tenant, resolved, key=key)
            if requested_version is None:
                release = await self._release_service().build_snapshot(
                    connection,
                    tenant,
                    key,
                    scope=resolved,
                )
                preview_version = None
            else:
                try:
                    preview_version = int(requested_version)
                except (TypeError, ValueError):
                    raise DomainError("service_application_version_invalid", 422) from None
                if preview_version < 1:
                    raise DomainError("service_application_version_invalid", 422)
                version_row = await self._release_service().get_version(
                    tenant,
                    key,
                    preview_version,
                    scope=resolved,
                )
                release = ReleaseSnapshot.model_validate(version_row["config"])
            agent_snapshot = await self.agents.snapshot(
                tenant,
                release.agent.id,
                connection,
                release.agent.version,
            )

        rule_write_enabled = release.rules.preview_write_enabled
        setting_write_enabled = bool(
            getattr(
                getattr(runner, "settings", None),
                "service_app_preview_write_enabled",
                False,
            )
        )
        if allow_write and not (rule_write_enabled and setting_write_enabled):
            raise DomainError("service_application_preview_write_disabled", 403)

        skills = list(release.skills)
        if requested_skill is not None:
            selected = next(
                (skill for skill in skills if skill.key == str(requested_skill)),
                None,
            )
            if selected is None:
                raise DomainError("service_application_skill_not_found", 404)
            skills = [selected]
        if not allow_write:
            skills = [skill for skill in skills if not skill.write_operation]

        connection_keys = {
            skill.connection_key for skill in skills if skill.connection_key is not None
        }
        connections = [item for item in release.connections if item.key in connection_keys]
        from agent_platform.business_capabilities.customer_service.service_apps.runtime import (
            ApplicationRuntimeContext,
            declared_builtin_tools,
        )

        skill_payloads = tuple(skill.model_dump(mode="json") for skill in skills)
        context = ApplicationRuntimeContext(
            application_id=application["id"],
            application_version=preview_version or 0,
            application_key=application["application_key"],
            business_id=resolved.business_id,
            workspace_id=resolved.workspace_id,
            agent_snapshot=agent_snapshot,
            skills=skill_payloads,
            connections=tuple(item.model_dump(mode="json") for item in connections),
            # The preview authorises exactly what a customer run authorises: the
            # release's own skills. Copying the Agent's ``tool_names`` here made a
            # preview retrieve while the released application, with the skill
            # switched off, could not — the drawer then showed a trace the customer
            # would never get.
            builtin_tools=declared_builtin_tools(skill_payloads),
        )
        try:
            result = await runner.preview_application(
                context,
                message,
                allow_write=allow_write,
            )
        except Exception as exc:  # noqa: BLE001 - preview must not leak provider errors
            return {
                "status": "failed",
                "reply": "",
                "application_version": preview_version,
                "draft": preview_version is None,
                "skills": [],
                "trace": {
                    **context.trace_payload(),
                    "simulation": True,
                    "upstream_called": False,
                    "error_code": getattr(exc, "code", "preview_execution_error"),
                },
            }

        calls = result.get("tools", [])
        skill_keys = {
            re.sub(r"[^a-zA-Z0-9_]", "_", skill.key): skill.key
            for skill in skills
            if skill.type in {"query", "action"}
        }
        return {
            "status": "completed",
            "reply": str(result.get("reply", "")),
            "application_version": preview_version,
            "draft": preview_version is None,
            "skills": [
                {
                    "key": skill_keys.get(str(name), str(name)),
                    "status": "completed",
                    "duration_ms": None,
                }
                for name in calls
                # Built-in capabilities are not application skills; retrieval has
                # its own section in the trace.
                if str(name) not in context.builtin_tools
            ],
            "trace": {
                **context.trace_payload(),
                "simulation": True,
                "upstream_called": False,
                "tool_calls": calls,
                "tool_violations": result.get("violations", []),
                "retrieval": result.get("retrieval", []),
            },
        }

    async def test_skill(
        self,
        tenant: str,
        actor: str,
        key: str,
        skill_key: str,
        body: object,
        *,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        del actor
        resolved = persisted_scope(tenant, scope)
        requested_version = _provided(body, "application_version") if body else _MISSING
        async with self.engine.connect() as connection:
            application = await self._row(connection, tenant, resolved, key=key)
            if requested_version not in (_MISSING, None):
                release = required(
                    await one(
                        connection,
                        """
SELECT config
FROM service_application_versions
WHERE tenant_id=:tenant AND business_id=:scope_business
  AND workspace_id=:scope_workspace AND application_id=:application
  AND version=:version
""",
                        tenant=tenant,
                        application=application["id"],
                        version=int(requested_version),
                        scope_business=resolved.business_id,
                        scope_workspace=resolved.workspace_id,
                    ),
                    "service_application_version_not_found",
                )
                release_skill = next(
                    (
                        item
                        for item in release["config"].get("skills", [])
                        if item.get("key") == skill_key
                    ),
                    None,
                )
                if release_skill is None:
                    raise DomainError("service_application_skill_not_found", 404)
                skill = release_skill
                config = dict(skill.get("config") or {})
                for field_name in _SKILL_CONFIG_FIELDS:
                    if field_name in skill and field_name != "config":
                        config[field_name] = skill[field_name]
                skill_type = str(skill.get("type") or "")
                name = str(skill.get("name") or "")
                description = str(skill.get("description") or "")
                enabled = bool(skill.get("enabled", True))
                connection_key = skill.get("connection_key")
            else:
                skill = required(
                    await one(
                        connection,
                        """
SELECT s.*,c.connection_key
FROM service_application_skills s
LEFT JOIN service_application_connections c
  ON c.id=s.connection_id
 AND c.tenant_id=s.tenant_id
 AND c.business_id=s.business_id
 AND c.workspace_id=s.workspace_id
WHERE s.tenant_id=:tenant AND s.business_id=:scope_business
  AND s.workspace_id=:scope_workspace AND s.application_id=:application
  AND s.skill_key=:skill_key
""",
                        tenant=tenant,
                        application=application["id"],
                        skill_key=skill_key,
                        scope_business=resolved.business_id,
                        scope_workspace=resolved.workspace_id,
                    ),
                    "service_application_skill_not_found",
                )
                skill_type = str(skill["type"])
                name = str(skill["name"])
                description = str(skill["description"])
                enabled = bool(skill["enabled"])
                connection_key = skill.get("connection_key")
                config = self._normalise_skill_config(
                    {"config": skill.get("config") or {}},
                    current=(skill["config"] if isinstance(skill.get("config"), dict) else {}),
                )
        if skill_type not in SKILL_TYPES:
            raise DomainError("service_application_skill_type_invalid", 422)
        contract = self._skill_contract(
            key=skill_key,
            skill_type=skill_type,
            name=name,
            description=description,
            enabled=enabled,
            connection_key=connection_key,
            config=config,
        )
        if contract.type in {"query", "action"} and connection_key is not None:
            result = await self.test_connection(
                tenant,
                "skill-test",
                key,
                connection_key,
                scope=scope,
            )
            ok = bool(
                result.get(
                    "ok",
                    result.get("status") in {"configured", "completed", "ok", "passed"},
                )
            )
            return {
                "status": "passed" if ok else "failed",
                "message": result.get("error")
                or result.get("message")
                or "service_application_skill_connection_tested",
                "duration_ms": result.get("duration_ms"),
                "connection_key": connection_key,
            }
        return {
            "status": "passed",
            "message": "service_application_skill_contract_valid",
            "duration_ms": 0,
            "connection_key": connection_key,
        }

    @staticmethod
    async def _bump_application_revision(
        connection: Any,
        tenant: str,
        application_id: str,
        actor: str,
    ) -> None:
        await execute(
            connection,
            """
UPDATE service_applications
SET draft_revision=draft_revision+1,updated_by=:actor,updated_at=now()
WHERE id=:id AND tenant_id=:tenant
""",
            id=application_id,
            tenant=tenant,
            actor=actor,
        )

    async def seed_defaults(
        self,
        tenant: str,
        actor: str = "seed-service-apps",
        *,
        scope: BusinessScope | None = None,
    ) -> dict[str, int]:
        """Install or refresh code-owned examples without touching user copies."""

        from .seed import example_applications

        resolved = persisted_scope(tenant, scope)
        scope_sql, scope_params = scope_predicate(resolved, alias="a")
        async with self.engine.begin() as connection:
            agent = await one(
                connection,
                f"""
SELECT a.id,a.name,a.published_version AS version
FROM agents a
WHERE a.tenant_id=:tenant AND {scope_sql}
  AND NOT a.archived AND a.published_version IS NOT NULL
ORDER BY a.created_at,a.id
LIMIT 1
""",
                tenant=tenant,
                **scope_params,
            )
            if agent is None:
                return {"applications": 0, "updated": 0}
            installed = 0
            updated = 0
            for template in example_applications(
                {
                    "id": str(agent["id"]),
                    "name": agent["name"],
                    "version": int(agent["version"]),
                }
            ):
                draft = dict(template["config"])
                existing = await one(
                    connection,
                    """
SELECT * FROM service_applications
WHERE tenant_id=:tenant AND business_id=:scope_business
  AND workspace_id=:scope_workspace AND application_key=:key
FOR UPDATE
""",
                    tenant=tenant,
                    key=template["key"],
                    scope_business=resolved.business_id,
                    scope_workspace=resolved.workspace_id,
                )
                if existing is not None:
                    if existing["origin"] != "example" or not existing["immutable"]:
                        raise DomainError("service_application_example_conflict", 409)
                    if existing.get("template_version") == template["template_version"]:
                        continue
                    row = await one(
                        connection,
                        """
UPDATE service_applications
SET name=:name,description=:description,agent_id=:agent_id,
    agent_version=:agent_version,template_key=:template_key,
    template_version=:template_version,draft=CAST(:draft AS jsonb),
    draft_revision=draft_revision+1,updated_by=:actor,updated_at=now()
WHERE id=:id AND tenant_id=:tenant
RETURNING *
""",
                        id=existing["id"],
                        tenant=tenant,
                        name=draft["name"],
                        description=draft["description"],
                        agent_id=str(agent["id"]),
                        agent_version=int(agent["version"]),
                        template_key=template["template_key"],
                        template_version=template["template_version"],
                        draft=json.dumps(draft, ensure_ascii=False),
                        actor=actor,
                    )
                    await self._sync_example_resources(
                        connection,
                        tenant,
                        resolved,
                        row["id"],
                        template,
                        actor,
                    )
                    await self._publish_example(
                        connection,
                        tenant,
                        actor,
                        resolved,
                        row,
                        refreshed=True,
                    )
                    updated += 1
                    continue
                row = await one(
                    connection,
                    """
INSERT INTO service_applications(
    tenant_id,business_id,workspace_id,application_key,name,description,
    agent_id,agent_version,origin,template_key,template_version,immutable,
    status,draft,draft_revision,created_by,updated_by
) VALUES(
    :tenant,:scope_business,:scope_workspace,:key,:name,:description,
    :agent_id,:agent_version,'example',:template_key,:template_version,true,
    'draft',CAST(:draft AS jsonb),1,:actor,:actor
)
ON CONFLICT(tenant_id,business_id,workspace_id,application_key) DO NOTHING
RETURNING *
""",
                    tenant=tenant,
                    key=template["key"],
                    name=draft["name"],
                    description=draft["description"],
                    agent_id=str(agent["id"]),
                    agent_version=int(agent["version"]),
                    template_key=template["template_key"],
                    template_version=template["template_version"],
                    draft=json.dumps(draft, ensure_ascii=False),
                    actor=actor,
                    scope_business=resolved.business_id,
                    scope_workspace=resolved.workspace_id,
                )
                if row is None:
                    continue
                await self._sync_example_resources(
                    connection,
                    tenant,
                    resolved,
                    row["id"],
                    template,
                    actor,
                )
                await self._publish_example(
                    connection,
                    tenant,
                    actor,
                    resolved,
                    row,
                )
                installed += 1
        return {"applications": installed, "updated": updated}

    @staticmethod
    async def _sync_example_resources(
        connection: Any,
        tenant: str,
        scope: BusinessScope,
        application_id: str,
        template: dict[str, Any],
        actor: str,
    ) -> None:
        await execute(
            connection,
            """
DELETE FROM service_application_skills
WHERE tenant_id=:tenant AND business_id=:scope_business
  AND workspace_id=:scope_workspace AND application_id=:application
""",
            tenant=tenant,
            application=application_id,
            scope_business=scope.business_id,
            scope_workspace=scope.workspace_id,
        )
        await execute(
            connection,
            """
DELETE FROM service_application_connections
WHERE tenant_id=:tenant AND business_id=:scope_business
  AND workspace_id=:scope_workspace AND application_id=:application
""",
            tenant=tenant,
            application=application_id,
            scope_business=scope.business_id,
            scope_workspace=scope.workspace_id,
        )
        connection_map: dict[str, str] = {}
        for item in template["connections"]:
            copied = await one(
                connection,
                """
INSERT INTO service_application_connections(
    tenant_id,business_id,workspace_id,application_id,connection_key,
    name,executor_kind,endpoint,method,public_headers,auth_kind,
    timeout_seconds,max_response_bytes,config,revision,created_by,updated_by
) VALUES(
    :tenant,:scope_business,:scope_workspace,:application,:key,
    :name,:executor_kind,:endpoint,:method,CAST(:headers AS jsonb),:auth_kind,
    :timeout,:max_response,CAST(:config AS jsonb),1,:actor,:actor
)
RETURNING id
""",
                tenant=tenant,
                application=application_id,
                key=item["key"],
                name=item["name"],
                executor_kind=item["executor_kind"],
                endpoint=item["endpoint"],
                method=item["method"],
                headers=json.dumps(item["public_headers"]),
                auth_kind=item["auth_kind"],
                timeout=item["timeout_seconds"],
                max_response=item["max_response_bytes"],
                config=json.dumps(item["config"]),
                actor=actor,
                scope_business=scope.business_id,
                scope_workspace=scope.workspace_id,
            )
            connection_map[item["key"]] = str(copied["id"])
        for item in template["skills"]:
            await execute(
                connection,
                """
INSERT INTO service_application_skills(
    tenant_id,business_id,workspace_id,application_id,skill_key,type,
    name,description,enabled,connection_id,config,revision,created_by,updated_by
) VALUES(
    :tenant,:scope_business,:scope_workspace,:application,:key,:type,
    :name,:description,:enabled,:connection_id,CAST(:config AS jsonb),1,
    :actor,:actor
)
""",
                tenant=tenant,
                application=application_id,
                key=item["key"],
                type=item["type"],
                name=item["name"],
                description=item["description"],
                enabled=item["enabled"],
                connection_id=connection_map.get(item["connection_key"]),
                config=json.dumps(item["config"], ensure_ascii=False),
                actor=actor,
                scope_business=scope.business_id,
                scope_workspace=scope.workspace_id,
            )

    async def _publish_example(
        self,
        connection: Any,
        tenant: str,
        actor: str,
        scope: BusinessScope,
        application: dict[str, Any],
        *,
        refreshed: bool = False,
    ) -> None:
        snapshot = await self._release_service().build_snapshot(
            connection,
            tenant,
            application["application_key"],
            scope=scope,
        )
        config = snapshot.model_dump(mode="json")
        digest = snapshot.digest
        next_version = (
            await one(
                connection,
                """
SELECT COALESCE(max(version),0)+1 AS version
FROM service_application_versions
WHERE tenant_id=:tenant AND business_id=:scope_business
  AND workspace_id=:scope_workspace AND application_id=:application
""",
                tenant=tenant,
                application=application["id"],
                scope_business=scope.business_id,
                scope_workspace=scope.workspace_id,
            )
        )["version"]
        version_row = await one(
            connection,
            """
INSERT INTO service_application_versions(
    tenant_id,business_id,workspace_id,application_id,version,
    schema_version,config,config_digest,source_version,created_by
) VALUES(
    :tenant,:scope_business,:scope_workspace,:application,:version,
    'v2',CAST(:config AS jsonb),:digest,NULL,:actor
)
RETURNING created_at
""",
            tenant=tenant,
            application=application["id"],
            version=next_version,
            config=json.dumps(config, ensure_ascii=False),
            digest=digest,
            actor=actor,
            scope_business=scope.business_id,
            scope_workspace=scope.workspace_id,
        )
        published_at = required(
            version_row,
            "service_application_example_publish_failed",
        )["created_at"]
        await execute(
            connection,
            """
UPDATE service_applications
SET status='published',published_version=:version,updated_at=:published_at
WHERE id=:id AND tenant_id=:tenant
""",
            id=application["id"],
            tenant=tenant,
            version=next_version,
            published_at=published_at,
        )
        await audit(
            connection,
            tenant,
            actor,
            (
                "service_application.example_refreshed"
                if refreshed
                else "service_application.example_seeded"
            ),
            application["id"],
            key=application["application_key"],
            version=next_version,
            template_version=application.get("template_version"),
            digest=digest,
        )


__all__ = [
    "DEFAULT_PAGE_SIZE",
    "EXAMPLE_KEY_PREFIX",
    "MAX_PAGE_SIZE",
    "MAX_TRACE_LIMIT",
    "ServiceApplicationService",
]
