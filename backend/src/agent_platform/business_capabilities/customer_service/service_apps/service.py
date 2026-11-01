"""Versioned service applications composed from scenarios and capabilities."""

from __future__ import annotations

from typing import Any

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

from ..scenarios.models import ScenarioConfig, SimulationRequest
from ..scenarios.service import ScenarioService
from .models import (
    ApplicationCapability,
    ApplicationScenarioReference,
    ApplicationServiceCategory,
    ApplicationSimulationRequest,
    ApplicationStatus,
    CapabilityType,
    ServiceApplicationConfig,
    ServiceCatalogUpdateRequest,
)

MAX_TRACE_LIMIT = 200


def _public_row(row: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    if "application_key" in result:
        result["key"] = result.pop("application_key")
    if "draft_revision" in result:
        result["revision"] = result.pop("draft_revision")
    if result.get("draft") is not None:
        result["config"] = result["draft"]
    return result


class ServiceApplicationService:
    """Application catalog, immutable releases and application-level simulation."""

    def __init__(
        self,
        engine: object,
        agents: object,
        scenarios: ScenarioService,
    ) -> None:
        self.engine = engine
        self.agents = agents
        self.scenarios = scenarios

    @staticmethod
    def _config(value: ServiceApplicationConfig | dict[str, Any]) -> ServiceApplicationConfig:
        return (
            value
            if isinstance(value, ServiceApplicationConfig)
            else ServiceApplicationConfig.model_validate(value)
        )

    @staticmethod
    def _row_config(row: dict[str, Any]) -> ServiceApplicationConfig:
        return ServiceApplicationConfig.model_validate(row["draft"])

    @staticmethod
    def _verify_status(value: str) -> str:
        allowed = {item.value for item in ApplicationStatus}
        if value not in allowed:
            raise DomainError("service_application_status_invalid", 422)
        return value

    @staticmethod
    def _summary(row: dict[str, Any]) -> dict[str, Any]:
        item = _public_row(row)
        config = ServiceApplicationConfig.model_validate(row["draft"])
        item["config"] = config.model_dump(mode="json")
        item.update(
            {
                "scenario_count": len(config.scenarios),
                "capability_count": len(config.capabilities),
                "channel_count": len(config.channels),
            }
        )
        item["has_unpublished_changes"] = (
            row["published_version"] is None
            or row.get("published_config") != row["draft"]
        )
        return item

    async def list(
        self,
        tenant: str,
        *,
        status: str = "all",
        q: str = "",
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        resolved = persisted_scope(tenant, scope)
        scope_sql, scope_params = scope_predicate(resolved, alias="a")
        status = status if status == "all" else self._verify_status(status)
        async with self.engine.connect() as connection:
            rows = await many(
                connection,
                f"""
SELECT a.*
FROM service_applications a
WHERE a.tenant_id=:tenant
  AND {scope_sql}
  AND NOT a.archived
  AND (:status='all' OR a.status=:status)
  AND (
      :q=''
      OR a.name ILIKE :pattern
      OR a.description ILIKE :pattern
      OR a.application_key ILIKE :pattern
  )
ORDER BY a.updated_at DESC,a.name,a.id
""",
                tenant=tenant,
                status=status,
                q=q,
                pattern=f"%{q}%",
                **scope_params,
            )
        items = [self._summary(row) for row in rows]
        return {"items": items, "total": len(items)}

    async def get(
        self,
        tenant: str,
        key: str,
        *,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        resolved = persisted_scope(tenant, scope)
        scope_sql, scope_params = scope_predicate(resolved, alias="a")
        async with self.engine.connect() as connection:
            row = required(
                await one(
                    connection,
                    f"""
SELECT a.*,v.config AS published_config
FROM service_applications a
LEFT JOIN service_application_versions v
  ON v.tenant_id=a.tenant_id
 AND v.business_id=a.business_id
 AND v.workspace_id=a.workspace_id
 AND v.application_id=a.id
 AND v.version=a.published_version
WHERE a.tenant_id=:tenant
  AND {scope_sql}
  AND a.application_key=:key
  AND NOT a.archived
""",
                    tenant=tenant,
                    key=key,
                    **scope_params,
                ),
                "service_application_not_found",
            )
        return self._summary(row)

    async def overview(
        self,
        tenant: str,
        *,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        resolved = persisted_scope(tenant, scope)
        scope_sql, scope_params = scope_predicate(resolved, alias="a")
        async with self.engine.connect() as connection:
            rows = await many(
                connection,
                f"""
SELECT a.status,a.draft,a.published_version
FROM service_applications a
WHERE a.tenant_id=:tenant AND {scope_sql} AND NOT a.archived
""",
                tenant=tenant,
                **scope_params,
            )
            trace_count = await one(
                connection,
                """
SELECT count(*)::int AS count
FROM service_scenario_traces
WHERE tenant_id=:tenant
  AND business_id=:scope_business
  AND workspace_id=:scope_workspace
  AND trace ? 'application'
""",
                tenant=tenant,
                **scope_params,
            )
        by_status = {item.value: 0 for item in ApplicationStatus}
        scenarios = 0
        capabilities = 0
        channels = 0
        for row in rows:
            by_status[row["status"]] = by_status.get(row["status"], 0) + 1
            config = ServiceApplicationConfig.model_validate(row["draft"])
            scenarios += len(config.scenarios)
            capabilities += len(config.capabilities)
            channels += len(config.channels)
        return {
            "applications": len(rows),
            "by_status": by_status,
            "scenarios": scenarios,
            "capabilities": capabilities,
            "channels": channels,
            "simulations": trace_count["count"] if trace_count else 0,
        }

    async def create(
        self,
        tenant: str,
        actor: str,
        key: str,
        body: Any,
        *,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        resolved = persisted_scope(tenant, scope)
        _, scope_params = scope_predicate(resolved, alias="a")
        config = self._config(body.config)
        async with self.engine.begin() as connection:
            row = await one(
                connection,
                """
INSERT INTO service_applications(
    tenant_id,business_id,workspace_id,application_key,name,description,
    status,draft,draft_revision,created_by,updated_by
) VALUES(
    :tenant,:scope_business,:scope_workspace,:key,:name,:description,
    'draft',CAST(:config AS jsonb),1,:actor,:actor
)
ON CONFLICT(tenant_id,business_id,workspace_id,application_key) DO NOTHING
RETURNING *
""",
                tenant=tenant,
                key=key,
                name=config.name,
                description=config.description,
                config=config.model_dump_json(),
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
            )
        return self._summary(row)

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
        scope_sql, scope_params = scope_predicate(resolved, alias="a")
        config = self._config(body.config)
        async with self.engine.begin() as connection:
            current = required(
                await one(
                    connection,
                    f"""
SELECT a.* FROM service_applications a
WHERE a.tenant_id=:tenant AND {scope_sql} AND a.application_key=:key
  AND NOT a.archived
FOR UPDATE
""",
                    tenant=tenant,
                    key=key,
                    **scope_params,
                ),
                "service_application_not_found",
            )
            if current["draft_revision"] != body.revision:
                raise DomainError("service_application_revision_conflict", 409)
            row = await one(
                connection,
                f"""
UPDATE service_applications a
SET name=:name,description=:description,draft=CAST(:config AS jsonb),
    draft_revision=draft_revision+1,updated_by=:actor,updated_at=now()
WHERE a.id=:id AND a.tenant_id=:tenant AND {scope_sql}
RETURNING a.*
""",
                id=current["id"],
                tenant=tenant,
                name=config.name,
                description=config.description,
                config=config.model_dump_json(),
                actor=actor,
                **scope_params,
            )
            await audit(
                connection,
                tenant,
                actor,
                "service_application.updated",
                current["id"],
                key=key,
                revision=row["draft_revision"],
            )
        return self._summary(row)

    async def update_service_catalog(
        self,
        tenant: str,
        actor: str,
        key: str,
        body: ServiceCatalogUpdateRequest,
        *,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        """Reorder, rename, merge or extend the application-owned catalog.

        Category references live in scenario drafts. Renames and merges update
        every referenced scenario in the same transaction, so the catalog and
        its scenarios cannot drift apart.
        """

        resolved = persisted_scope(tenant, scope)
        app_scope_sql, scope_params = scope_predicate(resolved, alias="a")
        scenario_scope_sql, _ = scope_predicate(resolved, alias="s")
        async with self.engine.begin() as connection:
            current = required(
                await one(
                    connection,
                    f"""
SELECT a.* FROM service_applications a
WHERE a.tenant_id=:tenant AND {app_scope_sql} AND a.application_key=:key
  AND NOT a.archived
FOR UPDATE
""",
                    tenant=tenant,
                    key=key,
                    **scope_params,
                ),
                "service_application_not_found",
            )
            if current["draft_revision"] != body.revision:
                raise DomainError("service_application_revision_conflict", 409)

            # The submitted list is the canonical display order. Normalizing
            # the order here keeps old clients and hand-written API calls from
            # persisting duplicate or sparse ordering values.
            categories = [
                ApplicationServiceCategory(
                    name=item.name,
                    order=(index + 1) * 10,
                )
                for index, item in enumerate(body.categories)
            ]
            category_names = {item.name for item in categories}
            changes = dict(body.category_changes)

            def resolve_category(name: str) -> str:
                visited: set[str] = set()
                while name in changes:
                    if name in visited:
                        raise DomainError("service_catalog_category_cycle", 422)
                    visited.add(name)
                    name = changes[name]
                return name

            raw_config = dict(current["draft"])
            raw_config["service_categories"] = [
                item.model_dump(mode="json") for item in categories
            ]
            config = ServiceApplicationConfig.model_validate(raw_config)

            reference_keys = [item.key for item in config.scenarios]
            if reference_keys:
                key_params = {
                    f"scenario_key_{index}": value
                    for index, value in enumerate(reference_keys)
                }
                placeholders = ",".join(f":{name}" for name in key_params)
                scenario_rows = await many(
                    connection,
                    f"""
SELECT s.id,s.scenario_key,s.draft
FROM service_scenarios s
WHERE s.tenant_id=:tenant AND {scenario_scope_sql}
  AND s.scenario_key IN ({placeholders})
  AND NOT s.archived
FOR UPDATE
""",
                    tenant=tenant,
                    **scope_params,
                    **key_params,
                )
            else:
                scenario_rows = []

            changed_scenarios: list[str] = []
            for scenario_row in scenario_rows:
                scenario_config = ScenarioConfig.model_validate(scenario_row["draft"])
                next_category = resolve_category(scenario_config.category)
                if next_category not in category_names:
                    raise DomainError(
                        "service_catalog_category_required",
                        422,
                    )
                if next_category != scenario_config.category:
                    updated_scenario = scenario_config.model_copy(
                        update={"category": next_category}
                    )
                    await execute(
                        connection,
                        """
UPDATE service_scenarios s
SET draft=CAST(:config AS jsonb),draft_revision=draft_revision+1,
    updated_by=:actor,updated_at=now()
WHERE s.id=:id AND s.tenant_id=:tenant
""",
                        id=scenario_row["id"],
                        tenant=tenant,
                        config=updated_scenario.model_dump_json(),
                        actor=actor,
                    )
                    changed_scenarios.append(scenario_row["scenario_key"])

            row = await one(
                connection,
                f"""
UPDATE service_applications a
SET draft=CAST(:config AS jsonb),draft_revision=draft_revision+1,
    updated_by=:actor,updated_at=now()
WHERE a.id=:id AND a.tenant_id=:tenant AND {app_scope_sql}
RETURNING a.*
""",
                id=current["id"],
                tenant=tenant,
                config=config.model_dump_json(),
                actor=actor,
                **scope_params,
            )
            await audit(
                connection,
                tenant,
                actor,
                "service_application.service_catalog_updated",
                current["id"],
                key=key,
                revision=row["draft_revision"],
                categories=[item.model_dump(mode="json") for item in categories],
                category_changes=changes,
                scenarios=changed_scenarios,
            )
        return self._summary(row)

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
            row = await one(
                connection,
                f"""
UPDATE service_applications a
SET status=:status,draft_revision=draft_revision+1,
    updated_by=:actor,updated_at=now()
WHERE a.tenant_id=:tenant AND {scope_sql} AND a.application_key=:key
  AND a.draft_revision=:revision AND NOT a.archived
RETURNING a.*
""",
                tenant=tenant,
                status=status,
                actor=actor,
                key=key,
                revision=revision,
                **scope_params,
            )
            if row is None:
                raise DomainError("service_application_missing_or_revision_conflict", 409)
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
        return self._summary(row)

    async def _scenario_row(
        self,
        connection: Any,
        tenant: str,
        scope: BusinessScope,
        reference: ApplicationScenarioReference,
    ) -> dict[str, Any]:
        scope_sql, scope_params = scope_predicate(scope, alias="s")
        row = required(
            await one(
                connection,
                f"""
SELECT s.id,s.scenario_key,s.name,s.status,s.published_version,
       s.draft_revision,s.draft,v.config AS version_config
FROM service_scenarios s
LEFT JOIN service_scenario_versions v
  ON v.tenant_id=s.tenant_id
 AND v.business_id=s.business_id
 AND v.workspace_id=s.workspace_id
 AND v.scenario_id=s.id
 AND v.version=COALESCE(CAST(:version AS integer),s.published_version)
WHERE s.tenant_id=:tenant AND {scope_sql}
  AND s.scenario_key=:key AND NOT s.archived
""",
                tenant=tenant,
                key=reference.key,
                version=reference.version,
                **scope_params,
            ),
            "service_application_scenario_not_found",
        )
        if reference.version is not None and row["version_config"] is None:
            raise DomainError("service_application_scenario_version_not_found", 404)
        return row

    async def _resolve_agent(
        self,
        connection: Any,
        tenant: str,
        scope: BusinessScope,
        capability: ApplicationCapability,
    ) -> ApplicationCapability:
        if capability.agent_id is None:
            raise DomainError("service_application_agent_required", 422)
        snapshot = await self.agents.snapshot(
            tenant,
            capability.agent_id,
            connection,
            capability.agent_version,
        )
        scope_sql, scope_params = scope_predicate(scope, alias="a")
        agent = required(
            await one(
                connection,
                f"""
SELECT a.name FROM agents a
WHERE a.id=:id AND a.tenant_id=:tenant AND {scope_sql}
  AND NOT a.archived
""",
                id=capability.agent_id,
                tenant=tenant,
                **scope_params,
            ),
            "service_application_agent_not_found",
        )
        return ApplicationCapability.model_validate(
            {
                **capability.model_dump(mode="json"),
                "agent_version": int(snapshot["version"]),
                "agent_name": agent["name"],
            }
        )

    async def _resolve_for_publish(
        self,
        connection: Any,
        tenant: str,
        scope: BusinessScope,
        config: ServiceApplicationConfig,
    ) -> ServiceApplicationConfig:
        enabled = [item for item in config.scenarios if item.enabled]
        if not enabled:
            raise DomainError("service_application_scenario_required", 422)
        scenarios: list[ApplicationScenarioReference] = []
        for reference in config.scenarios:
            if not reference.enabled:
                scenarios.append(reference)
                continue
            row = await self._scenario_row(connection, tenant, scope, reference)
            version = reference.version
            if version is None:
                if row["status"] != ApplicationStatus.PUBLISHED.value:
                    raise DomainError("service_application_scenario_not_published", 409)
                version = row["published_version"]
            if version is None:
                raise DomainError("service_application_scenario_not_published", 409)
            if row["version_config"] is None:
                raise DomainError("service_application_scenario_version_not_found", 404)
            scenarios.append(
                ApplicationScenarioReference(
                    key=reference.key,
                    version=int(version),
                    enabled=True,
                )
            )

        capabilities: list[ApplicationCapability] = []
        for capability in config.capabilities:
            if capability.enabled and capability.type == CapabilityType.AGENT:
                capabilities.append(
                    await self._resolve_agent(connection, tenant, scope, capability)
                )
            else:
                capabilities.append(capability)
        return config.model_copy(
            update={
                "scenarios": scenarios,
                "capabilities": capabilities,
            }
        )

    async def publish(
        self,
        tenant: str,
        actor: str,
        key: str,
        revision: int,
        *,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        resolved = persisted_scope(tenant, scope)
        scope_sql, scope_params = scope_predicate(resolved, alias="a")
        async with self.engine.begin() as connection:
            current = required(
                await one(
                    connection,
                    f"""
SELECT a.* FROM service_applications a
WHERE a.tenant_id=:tenant AND {scope_sql} AND a.application_key=:key
  AND NOT a.archived
FOR UPDATE
""",
                    tenant=tenant,
                    key=key,
                    **scope_params,
                ),
                "service_application_not_found",
            )
            if current["draft_revision"] != revision:
                raise DomainError("service_application_revision_conflict", 409)
            config = await self._resolve_for_publish(
                connection,
                tenant,
                resolved,
                self._row_config(current),
            )
            version = (
                await one(
                    connection,
                    """
SELECT COALESCE(max(version),0)+1 AS version
FROM service_application_versions
WHERE tenant_id=:tenant AND business_id=:scope_business
  AND workspace_id=:scope_workspace AND application_id=:application
""",
                    tenant=tenant,
                    application=current["id"],
                    **scope_params,
                )
            )["version"]
            await execute(
                connection,
                """
INSERT INTO service_application_versions(
    tenant_id,business_id,workspace_id,application_id,version,config,created_by
) VALUES(
    :tenant,:scope_business,:scope_workspace,:application,:version,
    CAST(:config AS jsonb),:actor
)
""",
                tenant=tenant,
                application=current["id"],
                version=version,
                config=config.model_dump_json(),
                actor=actor,
                **scope_params,
            )
            row = await one(
                connection,
                f"""
UPDATE service_applications a
SET name=:name,description=:description,draft=CAST(:config AS jsonb),
    status='published',published_version=:version,
    draft_revision=draft_revision+1,updated_by=:actor,updated_at=now()
WHERE a.id=:id AND a.tenant_id=:tenant AND {scope_sql}
RETURNING a.*
""",
                id=current["id"],
                tenant=tenant,
                name=config.name,
                description=config.description,
                config=config.model_dump_json(),
                version=version,
                actor=actor,
                **scope_params,
            )
            await audit(
                connection,
                tenant,
                actor,
                "service_application.published",
                current["id"],
                key=key,
                version=version,
                revision=row["draft_revision"],
            )
        result = self._summary(row)
        result["version"] = version
        return result

    async def versions(
        self,
        tenant: str,
        key: str,
        *,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        resolved = persisted_scope(tenant, scope)
        scope_sql, scope_params = scope_predicate(resolved, alias="a")
        async with self.engine.connect() as connection:
            application = required(
                await one(
                    connection,
                    f"""
SELECT a.id,a.published_version FROM service_applications a
WHERE a.tenant_id=:tenant AND {scope_sql} AND a.application_key=:key
  AND NOT a.archived
""",
                    tenant=tenant,
                    key=key,
                    **scope_params,
                ),
                "service_application_not_found",
            )
            rows = await many(
                connection,
                """
SELECT id,version,config,source_version,created_by,created_at
FROM service_application_versions
WHERE tenant_id=:tenant AND business_id=:scope_business
  AND workspace_id=:scope_workspace AND application_id=:application
ORDER BY version DESC
""",
                tenant=tenant,
                application=application["id"],
                **scope_params,
            )
        for row in rows:
            row["published"] = row["version"] == application["published_version"]
        return {"items": rows, "published_version": application["published_version"]}

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
        resolved = persisted_scope(tenant, scope)
        scope_sql, scope_params = scope_predicate(resolved, alias="a")
        async with self.engine.begin() as connection:
            current = required(
                await one(
                    connection,
                    f"""
SELECT a.* FROM service_applications a
WHERE a.tenant_id=:tenant AND {scope_sql} AND a.application_key=:key
  AND NOT a.archived
FOR UPDATE
""",
                    tenant=tenant,
                    key=key,
                    **scope_params,
                ),
                "service_application_not_found",
            )
            if current["draft_revision"] != revision:
                raise DomainError("service_application_revision_conflict", 409)
            target = required(
                await one(
                    connection,
                    """
SELECT version,config FROM service_application_versions
WHERE tenant_id=:tenant AND business_id=:scope_business
  AND workspace_id=:scope_workspace AND application_id=:application
  AND version=:version
""",
                    tenant=tenant,
                    application=current["id"],
                    version=version,
                    **scope_params,
                ),
                "service_application_version_not_found",
            )
            config = self._config(target["config"])
            row = await one(
                connection,
                f"""
UPDATE service_applications a
SET name=:name,description=:description,draft=CAST(:config AS jsonb),
    status='published',published_version=:version,
    draft_revision=draft_revision+1,updated_by=:actor,updated_at=now()
WHERE a.id=:id AND a.tenant_id=:tenant AND {scope_sql}
RETURNING a.*
""",
                id=current["id"],
                tenant=tenant,
                name=config.name,
                description=config.description,
                config=config.model_dump_json(),
                version=version,
                actor=actor,
                **scope_params,
            )
            await audit(
                connection,
                tenant,
                actor,
                "service_application.rolled_back",
                current["id"],
                key=key,
                version=version,
                revision=row["draft_revision"],
            )
        result = self._summary(row)
        result["rollback_version"] = version
        return result

    async def _application_config_for_simulation(
        self,
        connection: Any,
        tenant: str,
        scope: BusinessScope,
        key: str,
        version: int | None,
    ) -> tuple[dict[str, Any], ServiceApplicationConfig, str]:
        scope_sql, scope_params = scope_predicate(scope, alias="a")
        if version is None:
            row = required(
                await one(
                    connection,
                    f"""
SELECT a.* FROM service_applications a
WHERE a.tenant_id=:tenant AND {scope_sql} AND a.application_key=:key
  AND NOT a.archived
""",
                    tenant=tenant,
                    key=key,
                    **scope_params,
                ),
                "service_application_not_found",
            )
            return row, self._row_config(row), "draft"
        row = required(
            await one(
                connection,
                f"""
SELECT a.*,v.id AS application_version_id,v.config AS version_config
FROM service_applications a
JOIN service_application_versions v
  ON v.tenant_id=a.tenant_id
 AND v.business_id=a.business_id
 AND v.workspace_id=a.workspace_id
 AND v.application_id=a.id
 AND v.version=:version
WHERE a.tenant_id=:tenant AND {scope_sql} AND a.application_key=:key
  AND NOT a.archived
""",
                tenant=tenant,
                key=key,
                version=version,
                **scope_params,
            ),
            "service_application_version_not_found",
        )
        return row, self._config(row["version_config"]), "version"

    @staticmethod
    def _best_scenario(
        candidates: list[dict[str, Any]],
        message: str,
    ) -> dict[str, Any]:
        normalized = message.casefold()
        best = candidates[0]
        best_score = -1
        for candidate in candidates:
            config: ScenarioConfig = candidate["config"]
            if any(
                term.casefold() in normalized
                for term in config.matching.negative_keywords
            ):
                continue
            score = sum(
                max(1, len(term))
                for term in [*config.matching.keywords, *config.matching.intents]
                if term.casefold() in normalized
            )
            if score > best_score:
                best, best_score = candidate, score
        return best

    async def _scenario_candidates(
        self,
        connection: Any,
        tenant: str,
        scope: BusinessScope,
        config: ServiceApplicationConfig,
    ) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        for reference in config.scenarios:
            if not reference.enabled:
                continue
            row = await self._scenario_row(connection, tenant, scope, reference)
            scenario_config = ScenarioConfig.model_validate(
                row["version_config"] or row["draft"]
            )
            candidates.append(
                {
                    "key": reference.key,
                    "version": reference.version or row["published_version"],
                    "config": scenario_config,
                }
            )
        if not candidates:
            raise DomainError("service_application_scenario_required", 422)
        return candidates

    async def simulate(
        self,
        tenant: str,
        actor: str,
        key: str,
        body: ApplicationSimulationRequest,
        *,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        resolved = persisted_scope(tenant, scope)
        async with self.engine.connect() as connection:
            application, config, source = await self._application_config_for_simulation(
                connection,
                tenant,
                resolved,
                key,
                body.application_version,
            )
            candidates = await self._scenario_candidates(
                connection,
                tenant,
                resolved,
                config,
            )
        if body.scenario_key:
            target = next(
                (item for item in candidates if item["key"] == body.scenario_key),
                None,
            )
            if target is None:
                raise DomainError("service_application_scenario_not_in_app", 404)
        else:
            target = self._best_scenario(candidates, body.message)
        trace_context = {
            "key": key,
            "name": config.name,
            "version": body.application_version,
            "source": source,
            "draft_revision": application["draft_revision"],
        }
        scenario_body = SimulationRequest.model_validate(
            body.model_dump(
                exclude={
                    "scenario_key",
                    "application_version",
                }
            )
        )
        trace = await self.scenarios.simulate(
            tenant,
            actor,
            target["key"],
            scenario_body,
            scope=scope,
            persist=True,
            version=target["version"],
            trace_context=trace_context,
        )
        trace.update(
            {
                "application_key": key,
                "application_version": body.application_version,
                "application_revision": application["draft_revision"],
                "application_source": source,
                "scenario_key": target["key"],
                "scenario_version": target["version"],
            }
        )
        return trace

    async def traces(
        self,
        tenant: str,
        key: str,
        *,
        limit: int = 50,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        if limit < 1 or limit > MAX_TRACE_LIMIT:
            raise DomainError("service_application_trace_limit_invalid", 422)
        resolved = persisted_scope(tenant, scope)
        scope_sql, scope_params = scope_predicate(resolved, alias="a")
        async with self.engine.connect() as connection:
            required(
                await one(
                    connection,
                    f"""
SELECT a.id FROM service_applications a
WHERE a.tenant_id=:tenant AND {scope_sql} AND a.application_key=:key
  AND NOT a.archived
""",
                    tenant=tenant,
                    key=key,
                    **scope_params,
                ),
                "service_application_not_found",
            )
            items = await many(
                connection,
                """
SELECT id,scenario_key,scenario_version,simulation,entry,message_length,
       message_excerpt,object_ref,facts,decisions,handler_type,outcome,
       reason_code,result_summary,trace,created_by,created_at
FROM service_scenario_traces
WHERE tenant_id=:tenant AND business_id=:scope_business
  AND workspace_id=:scope_workspace
  AND trace->'application'->>'key'=:key
ORDER BY created_at DESC,id DESC
LIMIT :limit
""",
                tenant=tenant,
                key=key,
                limit=limit,
                **scope_params,
            )
        return {"items": items}

    async def seed_defaults(
        self,
        tenant: str,
        actor: str = "seed-service-apps",
        *,
        scope: BusinessScope | None = None,
    ) -> dict[str, int]:
        """Idempotently install the consumer-service application shell."""

        from .seed import default_application

        resolved = persisted_scope(tenant, scope)
        async with self.engine.begin() as connection:
            scope_sql, scope_params = scope_predicate(resolved, alias="s")
            scenario_rows = await many(
                connection,
                f"""
SELECT s.scenario_key,s.published_version,s.draft->>'category' AS category
FROM service_scenarios s
WHERE s.tenant_id=:tenant AND {scope_sql} AND NOT s.archived
ORDER BY s.domain,s.name,s.id
""",
                tenant=tenant,
                **scope_params,
            )
            agent_scope_sql, agent_scope_params = scope_predicate(resolved, alias="a")
            agent = await one(
                connection,
                f"""
SELECT a.id,a.name,a.published_version AS version
FROM agents a
WHERE a.tenant_id=:tenant AND {agent_scope_sql}
  AND NOT a.archived AND a.published_version IS NOT NULL
ORDER BY (a.name='示例客服 Agent') DESC,a.created_at,a.id
LIMIT 1
""",
                tenant=tenant,
                **agent_scope_params,
            )
            config = ServiceApplicationConfig.model_validate(
                default_application(scenarios=scenario_rows, agent=agent)
            )
            row = await one(
                connection,
                """
INSERT INTO service_applications(
    tenant_id,business_id,workspace_id,application_key,name,description,
    status,draft,draft_revision,created_by,updated_by
) VALUES(
    :tenant,:scope_business,:scope_workspace,'consumer-service',
    :name,:description,'draft',CAST(:config AS jsonb),1,:actor,:actor
)
ON CONFLICT(tenant_id,business_id,workspace_id,application_key) DO NOTHING
RETURNING id
""",
                tenant=tenant,
                name=config.name,
                description=config.description,
                config=config.model_dump_json(),
                actor=actor,
                **scope_params,
            )
            if row is None:
                return {"applications": 0}
            await audit(
                connection,
                tenant,
                actor,
                "service_application.seeded",
                row["id"],
                key="consumer-service",
                batch="service-application-v1",
            )
        return {"applications": 1}


__all__ = ["MAX_TRACE_LIMIT", "ServiceApplicationService"]
