"""Persisted global Skill authoring, testing, and release lifecycle."""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from agent_platform.core_platform.platform_services.persistence.store import (
    DomainError,
    audit,
    execute,
    many,
    one,
)
from agent_platform.core_platform.platform_services.storage.objects import S3Archive
from agent_platform.core_platform.platform_services.tenant_isolation.service import (
    persisted_scope,
    scope_predicate,
)
from agent_platform.extension_contracts import BusinessScope

from .assistant import generate_skill
from .classification import (
    Classification,
    PackageFacts,
    classify_skill,
    effective_risk,
    ordered_scope,
)
from .importing import InspectedPackage, PackageRejected, inspect_package
from .models import (
    SkillCreateRequest,
    SkillDefinition,
    SkillDraftUpdate,
    SkillDuplicateRequest,
    SkillPublishRequest,
    SkillRollbackRequest,
    SkillTestRequest,
    canonical_definition,
    definition_digest,
    next_semver,
    patch_semver,
    validate_parameter_input,
)
from .templates import get_template, template_catalog
from .testing import SkillTestExecutor

SCHEMA_VERSION = "v1"

_DEFINITION_VALUE_ERROR_MESSAGES = frozenset(
    {
        "parameter name must start with a letter and contain only letters, digits, or underscores",
        "tool names must be unique",
        "tool name is invalid",
        "parameter names must be unique",
        "json output requires a schema",
        "model profile version requires a profile id",
        "handoff error behavior requires a handoff queue",
        "instruction skills require instructions",
        "instruction skills require a model profile",
        "instruction skills require a model profile version",
        "knowledge skills require at least one knowledge base",
        "action skills require confirmation",
        "handoff skills require a handoff queue",
    }
)
_DEFINITION_TOOL_REQUIRED = re.compile(
    r"^(?:instruction|knowledge|query|action|handoff) skills require at least one tool$"
)


class SkillDefinitionInvalidError(DomainError):
    """Carry safe field/check details while preserving the stable error code."""

    def __init__(self, errors: list[dict[str, Any]]):
        super().__init__("skill_definition_invalid", 422)
        self.detail = {"code": self.code, "errors": errors}


class SkillLibraryService:
    def __init__(
        self,
        engine: Any,
        settings: Any,
        *,
        gateway: Any,
        retrieval: Any,
        tools: Any,
        tool_workspace: Any,
    ):
        self.engine = engine
        self.settings = settings
        self.gateway = gateway
        self.retrieval = retrieval
        self.tools = tools
        self.executor = SkillTestExecutor(
            settings,
            gateway,
            retrieval,
            tools,
            tool_workspace,
        )

    def templates(self) -> dict[str, Any]:
        enabled = bool(
            self.settings.skill_ai_generation_enabled and self.settings.skill_ai_profile_id
        )
        reason = None
        if not self.settings.skill_ai_generation_enabled:
            reason = "skill_ai_generation_disabled"
        elif self.settings.skill_ai_profile_id is None:
            reason = "skill_ai_profile_not_configured"
        return template_catalog(enabled, reason)

    async def list(
        self,
        tenant: str,
        *,
        scope: BusinessScope | None,
        q: str = "",
        category: str = "all",
        status: str = "all",
        risk: str = "all",
        weight: str = "all",
        sort: str = "latest",
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        resolved = persisted_scope(tenant, scope)
        base, base_params = _scope_sql(resolved, "s")
        params: dict[str, Any] = {**base_params, "tenant": tenant}
        clauses = [base]
        if q.strip():
            clauses.append(
                "(s.name ILIKE :query OR s.description ILIKE :query "
                "OR s.skill_key ILIKE :query OR :query_text = ANY(s.tags))"
            )
            params["query"] = f"%{q.strip()}%"
            params["query_text"] = q.strip()
        if category != "all":
            clauses.append("s.category=:category")
            params["category"] = category
        if status != "all":
            clauses.append("s.status=:status")
            params["status"] = status
        if risk != "all":
            clauses.append("s.risk_level=:risk")
            params["risk"] = risk
        if weight != "all":
            clauses.append("s.weight_class=:weight")
            params["weight"] = weight
        where = " AND ".join(clauses)
        async with self.engine.connect() as connection:
            total = (
                await one(
                    connection,
                    "SELECT count(*) n FROM skills s WHERE " + where,
                    **params,
                )
            )["n"]
            rows = await many(
                connection,
                """
                SELECT s.*,v.semver AS current_semver,v.created_at AS published_at,
                       usage.usage_total,usage.usage_succeeded,
                       rating.rating_count,rating.rating_avg
                FROM skills s
                LEFT JOIN skill_versions v
                  ON v.tenant_id=s.tenant_id
                 AND v.business_id=s.business_id
                 AND v.workspace_id=s.workspace_id
                 AND v.skill_id=s.id
                 AND v.version=s.published_version
                """
                + USAGE_RATING_JOIN
                + """
                WHERE """
                + where
                + " ORDER BY "
                + _list_order(sort)
                + " LIMIT :limit OFFSET :offset",
                **params,
                limit=page_size,
                offset=(page - 1) * page_size,
            )
            status_rows = await many(
                connection,
                "SELECT s.status value,count(*) count FROM skills s WHERE "
                + _facet_where(base, q, category=category, risk=risk, weight=weight)
                + " GROUP BY s.status ORDER BY s.status",
                **params,
            )
            category_rows = await many(
                connection,
                "SELECT s.category value,count(*) count FROM skills s WHERE "
                + _facet_where(base, q, status=status, risk=risk, weight=weight)
                + " GROUP BY s.category ORDER BY s.category",
                **params,
            )
            risk_rows = await many(
                connection,
                "SELECT s.risk_level value,count(*) count FROM skills s WHERE "
                + _facet_where(base, q, category=category, status=status, weight=weight)
                + " GROUP BY s.risk_level ORDER BY s.risk_level",
                **params,
            )
            weight_rows = await many(
                connection,
                "SELECT s.weight_class value,count(*) count FROM skills s WHERE "
                + _facet_where(base, q, category=category, status=status, risk=risk)
                + " GROUP BY s.weight_class ORDER BY s.weight_class",
                **params,
            )
        return {
            "items": [_summary(row) for row in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "status_facets": status_rows,
            "category_facets": category_rows,
            "risk_facets": risk_rows,
            "weight_facets": weight_rows,
        }

    async def overview(
        self,
        tenant: str,
        *,
        scope: BusinessScope | None,
        popular_limit: int = 5,
    ) -> dict[str, Any]:
        """Catalogue headline numbers plus the popular rail.

        Every figure is derived from rows that already exist, so none of them
        can drift from the list: totals from ``skills``, usage from
        ``skill_usage_daily``, ratings from ``skill_ratings``. Trends compare
        the last 30 days against the 30 before it and are ``None`` when there
        is no prior window to compare with.
        """

        resolved = persisted_scope(tenant, scope)
        base, base_params = _scope_sql(resolved, "s")
        params: dict[str, Any] = {**base_params, "tenant": tenant}
        async with self.engine.connect() as connection:
            totals = await one(
                connection,
                f"""
                SELECT
                  (SELECT count(*) FROM skills s WHERE {base}) AS total,
                  (SELECT count(*) FROM skills s WHERE {base} AND s.status='published')
                    AS published,
                  (SELECT count(DISTINCT u.skill_id)
                     FROM skill_usage_daily u JOIN skills s ON s.tenant_id=u.tenant_id
                       AND s.business_id=u.business_id AND s.workspace_id=u.workspace_id
                       AND s.id=u.skill_id
                    WHERE {base} AND u.day >= current_date - 29) AS in_use,
                  (SELECT avg(r.score)
                     FROM skill_ratings r JOIN skills s ON s.tenant_id=r.tenant_id
                       AND s.business_id=r.business_id AND s.workspace_id=r.workspace_id
                       AND s.id=r.skill_id
                    WHERE {base}) AS rating_avg
                """,
                **params,
            )
            window = await one(
                connection,
                f"""
                SELECT
                  (SELECT count(*) FROM skills s
                    WHERE {base} AND s.created_at > now() - interval '30 days') AS total_now,
                  (SELECT count(*) FROM skills s
                    WHERE {base} AND s.created_at > now() - interval '60 days'
                      AND s.created_at <= now() - interval '30 days') AS total_prev,
                  (SELECT count(*) FROM skill_versions v JOIN skills s
                       ON s.tenant_id=v.tenant_id AND s.business_id=v.business_id
                      AND s.workspace_id=v.workspace_id AND s.id=v.skill_id
                    WHERE {base} AND v.created_at > now() - interval '30 days') AS published_now,
                  (SELECT count(*) FROM skill_versions v JOIN skills s
                       ON s.tenant_id=v.tenant_id AND s.business_id=v.business_id
                      AND s.workspace_id=v.workspace_id AND s.id=v.skill_id
                    WHERE {base} AND v.created_at > now() - interval '60 days'
                      AND v.created_at <= now() - interval '30 days') AS published_prev,
                  (SELECT COALESCE(sum(u.runs),0)
                     FROM skill_usage_daily u JOIN skills s ON s.tenant_id=u.tenant_id
                       AND s.business_id=u.business_id AND s.workspace_id=u.workspace_id
                       AND s.id=u.skill_id
                    WHERE {base} AND u.day >= current_date - 29) AS usage_now,
                  (SELECT COALESCE(sum(u.runs),0)
                     FROM skill_usage_daily u JOIN skills s ON s.tenant_id=u.tenant_id
                       AND s.business_id=u.business_id AND s.workspace_id=u.workspace_id
                       AND s.id=u.skill_id
                    WHERE {base} AND u.day >= current_date - 59
                      AND u.day <= current_date - 30) AS usage_prev,
                  (SELECT avg(r.score) FROM skill_ratings r JOIN skills s
                       ON s.tenant_id=r.tenant_id AND s.business_id=r.business_id
                      AND s.workspace_id=r.workspace_id AND s.id=r.skill_id
                    WHERE {base} AND r.created_at > now() - interval '30 days') AS rating_now,
                  (SELECT avg(r.score) FROM skill_ratings r JOIN skills s
                       ON s.tenant_id=r.tenant_id AND s.business_id=r.business_id
                      AND s.workspace_id=r.workspace_id AND s.id=r.skill_id
                    WHERE {base} AND r.created_at > now() - interval '60 days'
                      AND r.created_at <= now() - interval '30 days') AS rating_prev
                """,
                **params,
            )
            popular_rows = await many(
                connection,
                f"""
                SELECT s.skill_key AS key,s.name,s.category,s.status,
                       sum(u.runs)::int AS runs,sum(u.succeeded)::int AS succeeded
                FROM skills s JOIN skill_usage_daily u
                  ON s.tenant_id=u.tenant_id AND s.business_id=u.business_id
                 AND s.workspace_id=u.workspace_id AND s.id=u.skill_id
                WHERE {base} AND u.day >= current_date - 29
                GROUP BY s.id,s.skill_key,s.name,s.category,s.status
                ORDER BY runs DESC,s.name
                LIMIT :limit
                """,
                **params,
                limit=popular_limit,
            )
        rating_now = window["rating_now"]
        rating_prev = window["rating_prev"]
        return {
            "stats": {
                "total": {
                    "value": int(totals["total"]),
                    "change": _pct_change(window["total_now"], window["total_prev"]),
                },
                "published": {
                    "value": int(totals["published"]),
                    "change": _pct_change(window["published_now"], window["published_prev"]),
                },
                "in_use": {
                    "value": int(totals["in_use"]),
                    "change": _pct_change(window["usage_now"], window["usage_prev"]),
                },
                "rating": {
                    "value": (
                        round(float(totals["rating_avg"]), 1)
                        if totals["rating_avg"] is not None
                        else None
                    ),
                    "change": (
                        round(float(rating_now) - float(rating_prev), 1)
                        if rating_now is not None and rating_prev is not None
                        else None
                    ),
                },
            },
            "popular": [
                {
                    "key": row["key"],
                    "name": row["name"],
                    "category": row["category"],
                    "status": row["status"],
                    "runs": int(row["runs"]),
                    "success_rate": (
                        round(int(row["succeeded"]) / int(row["runs"]), 4)
                        if row["runs"]
                        else None
                    ),
                }
                for row in popular_rows
            ],
        }

    async def get(
        self,
        tenant: str,
        skill_key: str,
        *,
        scope: BusinessScope | None,
    ) -> dict[str, Any]:
        resolved = persisted_scope(tenant, scope)
        async with self.engine.connect() as connection:
            row = await _fetch_skill(connection, tenant, resolved, skill_key)
        return _record(row)

    async def create(
        self,
        tenant: str,
        actor: str,
        body: SkillCreateRequest,
        *,
        scope: BusinessScope | None,
    ) -> dict[str, Any]:
        resolved = persisted_scope(tenant, scope)
        name: str
        description: str
        category: str
        tags: list[str]
        raw_definition: dict[str, Any]
        if body.mode == "ai":
            generated = await generate_skill(
                tenant=tenant,
                actor=actor,
                prompt=body.prompt or "",
                settings=self.settings,
                gateway=self.gateway,
            )
            name = generated["name"]
            description = generated["description"]
            category = generated["category"]
            tags = generated["tags"]
            raw_definition = generated["definition"]
        elif body.mode == "template":
            template = get_template(body.template_key or "")
            if template is None or template.definition is None:
                raise DomainError("skill_definition_invalid", 422)
            name = template.name
            description = template.description
            category = template.category
            tags = list(template.tags)
            raw_definition = template.definition.model_dump(mode="json", by_alias=True)
            raw_definition["creation_mode"] = "template"
        else:
            raw_definition = body.definition or SkillDefinition().model_dump(
                mode="json",
                by_alias=True,
            )
            raw_definition["creation_mode"] = "professional"
            name = _default_skill_name(raw_definition)
            description = ""
            category = "general"
            tags = []
        definition = _validated_definition(raw_definition)
        definition.creation_mode = body.mode
        classification = classify_skill(definition)
        async with self.engine.begin() as connection:
            row = await self._insert_unique_skill(
                connection,
                tenant,
                resolved,
                actor,
                skill_key=_base_key(name),
                name=name,
                description=description,
                category=category,
                tags=tags,
                definition=definition,
                classification=classification,
            )
            await audit(
                connection,
                tenant,
                actor,
                "skill.created",
                row["id"],
                key=row["skill_key"],
                revision=row["draft_revision"],
                creation_mode=definition.creation_mode,
                weight_class=classification.weight_class,
                risk_level=classification.risk_level,
            )
            row = await _fetch_skill(
                connection,
                tenant,
                resolved,
                row["skill_key"],
                aliases=True,
            )
        return _record(row)

    async def save_draft(
        self,
        tenant: str,
        actor: str,
        skill_key: str,
        body: SkillDraftUpdate,
        *,
        scope: BusinessScope | None,
    ) -> dict[str, Any]:
        resolved = persisted_scope(tenant, scope)
        # A draft may be incomplete. Structural validation protects storage;
        # type-specific mandatory fields are enforced before test/release.
        definition = _validated_definition(body.definition, require_release=False)
        async with self.engine.begin() as connection:
            row = await _fetch_skill(
                connection,
                tenant,
                resolved,
                skill_key,
                lock=True,
            )
            if row["draft_revision"] != body.revision:
                raise DomainError("skill_revision_conflict", 409)
            if row["status"] == "archived":
                raise DomainError("skill_revision_conflict", 409)
            # ``weight_class`` is never taken from input: it follows the
            # artefact. The attached package, not the form, decides whether the
            # Skill is executable -- otherwise saving a draft would silently
            # downgrade a packaged Skill and skip the sandbox at run time.
            # ``risk_level`` is an author label, so an explicit value wins over
            # the computed baseline. Nothing is enforced from it.
            computed = classify_skill(definition, _package_facts(row))
            risk_label = body.risk_level or computed.risk_level
            updated = await one(
                connection,
                """
                UPDATE skills
                SET name=:name,description=:description,category=:category,
                    tags=CAST(:tags AS text[]),visibility=:visibility,
                    weight_class=:weight_class,risk_level=:risk_level,
                    data_scope=CAST(:data_scope AS text[]),
                    draft_definition=CAST(:definition AS jsonb),
                    draft_revision=draft_revision+1,updated_by=:actor,updated_at=now()
                WHERE tenant_id=:tenant AND business_id=:business
                  AND workspace_id=:workspace AND id=:id AND draft_revision=:revision
                RETURNING id
                """,
                name=body.name,
                description=body.description,
                category=body.category,
                tags=body.tags,
                visibility=body.visibility,
                weight_class=computed.weight_class,
                risk_level=risk_label,
                data_scope=list(computed.data_scope),
                definition=canonical_definition(definition),
                actor=actor,
                tenant=tenant,
                business=resolved.business_id,
                workspace=resolved.workspace_id,
                id=row["id"],
                revision=body.revision,
            )
            if not updated:
                raise DomainError("skill_revision_conflict", 409)
            await audit(
                connection,
                tenant,
                actor,
                "skill.draft_saved",
                row["id"],
                key=skill_key,
                revision=body.revision + 1,
                weight_class=computed.weight_class,
                risk_level=risk_label,
                risk_computed=computed.risk_level,
            )
            row = await _fetch_skill(connection, tenant, resolved, skill_key)
        return _record(row)

    async def duplicate(
        self,
        tenant: str,
        actor: str,
        skill_key: str,
        body: SkillDuplicateRequest,
        *,
        scope: BusinessScope | None,
    ) -> dict[str, Any]:
        resolved = persisted_scope(tenant, scope)
        async with self.engine.begin() as connection:
            source = await _fetch_skill(
                connection,
                tenant,
                resolved,
                skill_key,
                lock=True,
            )
            if source["draft_revision"] != body.revision:
                raise DomainError("skill_revision_conflict", 409)
            name = body.name or f"{source['name']} copy"
            copied = SkillDefinition.model_validate(source["draft_definition"])
            classification = classify_skill(copied)
            duplicate = await self._insert_unique_skill(
                connection,
                tenant,
                resolved,
                actor,
                skill_key=_base_key(name),
                name=name,
                description=source["description"],
                category=source["category"],
                tags=list(source["tags"] or []),
                definition=copied,
                classification=classification,
            )
            await audit(
                connection,
                tenant,
                actor,
                "skill.duplicated",
                duplicate["id"],
                source_skill_id=str(source["id"]),
                revision=source["draft_revision"],
            )
            row = await _fetch_skill(
                connection,
                tenant,
                resolved,
                duplicate["skill_key"],
            )
        return _record(row)

    async def run_test(
        self,
        tenant: str,
        actor: str,
        skill_key: str,
        body: SkillTestRequest,
        *,
        scope: BusinessScope | None,
    ) -> dict[str, Any]:
        resolved = persisted_scope(tenant, scope)
        async with self.engine.connect() as connection:
            skill = await _fetch_skill(connection, tenant, resolved, skill_key)
            if skill["draft_revision"] != body.draft_revision:
                raise DomainError("skill_revision_conflict", 409)
            if body.client_request_id:
                existing = await one(
                    connection,
                    """
                    SELECT * FROM skill_test_runs
                    WHERE tenant_id=:tenant AND business_id=:business
                      AND workspace_id=:workspace AND skill_id=:skill
                      AND client_request_id=:request_id
                    """,
                    tenant=tenant,
                    business=resolved.business_id,
                    workspace=resolved.workspace_id,
                    skill=skill["id"],
                    request_id=body.client_request_id,
                )
                if existing:
                    return _run(existing)
        definition = _validated_definition(skill["draft_definition"])
        input_chars = len(json.dumps(body.input, ensure_ascii=False, sort_keys=True))
        if input_chars > self.settings.skill_test_max_input_chars:
            raise DomainError("skill_test_input_invalid", 422)
        try:
            validate_parameter_input(definition, body.input)
        except ValueError:
            raise DomainError("skill_test_input_invalid", 422) from None
        outcome = await self.executor.execute(
            tenant=tenant,
            actor=actor,
            definition=definition,
            payload=body.input,
            scenario=body.scenario,
        )
        async with self.engine.begin() as connection:
            inserted = await one(
                connection,
                """
                INSERT INTO skill_test_runs(
                    id,tenant_id,business_id,workspace_id,skill_id,draft_revision,
                    status,execution_kind,input,input_summary,output,diagnostics,
                    reason_code,duration_ms,client_request_id,executed_by
                )
                SELECT :id,s.tenant_id,s.business_id,s.workspace_id,s.id,:revision,
                       :status,:kind,CAST(:input AS jsonb),:summary,
                       CAST(:output AS jsonb),CAST(:diagnostics AS jsonb),
                       :reason,:duration,:request_id,:actor
                FROM skills s
                WHERE s.tenant_id=:tenant AND s.business_id=:business
                  AND s.workspace_id=:workspace AND s.id=:skill
                  AND s.draft_revision=:revision
                ON CONFLICT DO NOTHING
                RETURNING *
                """,
                id=uuid4(),
                tenant=tenant,
                business=resolved.business_id,
                workspace=resolved.workspace_id,
                skill=skill["id"],
                revision=body.draft_revision,
                status=outcome.status,
                kind=outcome.execution_kind,
                input=json.dumps(body.input, ensure_ascii=False, default=str),
                summary=_input_summary(body.input),
                output=(
                    json.dumps(outcome.output, ensure_ascii=False, default=str)
                    if outcome.output is not None
                    else None
                ),
                diagnostics=json.dumps(
                    outcome.diagnostics,
                    ensure_ascii=False,
                    default=str,
                ),
                reason=outcome.reason_code,
                duration=outcome.duration_ms,
                request_id=body.client_request_id,
                actor=actor,
            )
            if not inserted:
                if body.client_request_id:
                    existing = await one(
                        connection,
                        """
                        SELECT * FROM skill_test_runs
                        WHERE tenant_id=:tenant AND business_id=:business
                          AND workspace_id=:workspace AND skill_id=:skill
                          AND client_request_id=:request_id
                        """,
                        tenant=tenant,
                        business=resolved.business_id,
                        workspace=resolved.workspace_id,
                        skill=skill["id"],
                        request_id=body.client_request_id,
                    )
                    if existing:
                        return _run(existing)
                raise DomainError("skill_revision_conflict", 409)
            await audit(
                connection,
                tenant,
                actor,
                "skill.tested",
                inserted["id"],
                skill_id=str(skill["id"]),
                revision=body.draft_revision,
                status=outcome.status,
                execution_kind=outcome.execution_kind,
                duration_ms=outcome.duration_ms,
                reason_code=outcome.reason_code,
            )
        return _run(inserted)

    async def test_runs(
        self,
        tenant: str,
        skill_key: str,
        *,
        scope: BusinessScope | None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        resolved = persisted_scope(tenant, scope)
        async with self.engine.connect() as connection:
            skill = await _fetch_skill(connection, tenant, resolved, skill_key)
            where = (
                "tenant_id=:tenant AND business_id=:business "
                "AND workspace_id=:workspace AND skill_id=:skill"
            )
            params = {
                "tenant": tenant,
                "business": resolved.business_id,
                "workspace": resolved.workspace_id,
                "skill": skill["id"],
            }
            total = (
                await one(
                    connection,
                    "SELECT count(*) n FROM skill_test_runs WHERE " + where,
                    **params,
                )
            )["n"]
            rows = await many(
                connection,
                "SELECT * FROM skill_test_runs WHERE "
                + where
                + " ORDER BY created_at DESC,id DESC LIMIT :limit OFFSET :offset",
                **params,
                limit=page_size,
                offset=(page - 1) * page_size,
            )
        return {
            "items": [_run(row) for row in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def test_run(
        self,
        tenant: str,
        skill_key: str,
        run_id: UUID,
        *,
        scope: BusinessScope | None,
    ) -> dict[str, Any]:
        resolved = persisted_scope(tenant, scope)
        async with self.engine.connect() as connection:
            skill = await _fetch_skill(connection, tenant, resolved, skill_key)
            row = await one(
                connection,
                """
                SELECT * FROM skill_test_runs
                WHERE tenant_id=:tenant AND business_id=:business
                  AND workspace_id=:workspace AND skill_id=:skill AND id=:run
                """,
                tenant=tenant,
                business=resolved.business_id,
                workspace=resolved.workspace_id,
                skill=skill["id"],
                run=run_id,
            )
        if row is None:
            raise DomainError("skill_not_found", 404)
        return _run(row)

    async def readiness(
        self,
        tenant: str,
        skill_key: str,
        *,
        scope: BusinessScope | None,
        can_publish: bool,
    ) -> dict[str, Any]:
        resolved = persisted_scope(tenant, scope)
        async with self.engine.connect() as connection:
            skill = await _fetch_skill(connection, tenant, resolved, skill_key)
            return await self._readiness(connection, tenant, resolved, skill, can_publish)

    async def versions(
        self,
        tenant: str,
        skill_key: str,
        *,
        scope: BusinessScope | None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        resolved = persisted_scope(tenant, scope)
        async with self.engine.connect() as connection:
            skill = await _fetch_skill(connection, tenant, resolved, skill_key)
            where = (
                "tenant_id=:tenant AND business_id=:business "
                "AND workspace_id=:workspace AND skill_id=:skill"
            )
            params = {
                "tenant": tenant,
                "business": resolved.business_id,
                "workspace": resolved.workspace_id,
                "skill": skill["id"],
            }
            total = (
                await one(
                    connection,
                    "SELECT count(*) n FROM skill_versions WHERE " + where,
                    **params,
                )
            )["n"]
            rows = await many(
                connection,
                "SELECT * FROM skill_versions WHERE "
                + where
                + " ORDER BY version DESC LIMIT :limit OFFSET :offset",
                **params,
                limit=page_size,
                offset=(page - 1) * page_size,
            )
        return {
            "items": [_version(row) for row in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def version(
        self,
        tenant: str,
        skill_key: str,
        version: int,
        *,
        scope: BusinessScope | None,
    ) -> dict[str, Any]:
        resolved = persisted_scope(tenant, scope)
        async with self.engine.connect() as connection:
            skill = await _fetch_skill(connection, tenant, resolved, skill_key)
            row = await one(
                connection,
                """
                SELECT * FROM skill_versions
                WHERE tenant_id=:tenant AND business_id=:business
                  AND workspace_id=:workspace AND skill_id=:skill AND version=:version
                """,
                tenant=tenant,
                business=resolved.business_id,
                workspace=resolved.workspace_id,
                skill=skill["id"],
                version=version,
            )
        if row is None:
            raise DomainError("skill_version_not_found", 404)
        return _version(row)

    async def publish(
        self,
        tenant: str,
        actor: str,
        skill_key: str,
        body: SkillPublishRequest,
        *,
        scope: BusinessScope | None,
    ) -> dict[str, Any]:
        resolved = persisted_scope(tenant, scope)
        async with self.engine.begin() as connection:
            locked = await self._lock_skill(connection, tenant, resolved, skill_key)
            if locked["draft_revision"] != body.revision:
                raise DomainError("skill_revision_conflict", 409)
            if locked["status"] == "archived":
                raise DomainError("skill_readiness_blocked", 409)
            definition = _validated_definition(
                locked["draft_definition"],
                require_release=True,
            )
            readiness = await self._readiness(
                connection,
                tenant,
                resolved,
                locked,
                can_publish=True,
            )
            if not readiness["ready"]:
                raise DomainError("skill_readiness_blocked", 409)
            latest = await one(
                connection,
                """
                SELECT * FROM skill_test_runs
                WHERE tenant_id=:tenant AND business_id=:business
                  AND workspace_id=:workspace AND skill_id=:skill
                  AND draft_revision=:revision AND status='passed'
                ORDER BY created_at DESC,id DESC LIMIT 1
                """,
                tenant=tenant,
                business=resolved.business_id,
                workspace=resolved.workspace_id,
                skill=locked["id"],
                revision=body.revision,
            )
            if latest is None:
                raise DomainError("skill_readiness_blocked", 409)
            digest = definition_digest(definition)
            duplicate = await one(
                connection,
                """
                SELECT id FROM skill_versions
                WHERE tenant_id=:tenant AND business_id=:business
                  AND workspace_id=:workspace AND skill_id=:skill
                  AND source_draft_revision=:revision
                  AND definition_digest=:digest
                LIMIT 1
                """,
                tenant=tenant,
                business=resolved.business_id,
                workspace=resolved.workspace_id,
                skill=locked["id"],
                revision=body.revision,
                digest=digest,
            )
            if duplicate:
                raise DomainError("skill_publish_in_progress", 409)
            next_version = (
                await one(
                    connection,
                    """
                    SELECT COALESCE(max(version),0)+1 version
                    FROM skill_versions
                    WHERE tenant_id=:tenant AND business_id=:business
                      AND workspace_id=:workspace AND skill_id=:skill
                    """,
                    tenant=tenant,
                    business=resolved.business_id,
                    workspace=resolved.workspace_id,
                    skill=locked["id"],
                )
            )["version"]
            current_semver = locked.get("current_semver")
            if current_semver is None:
                semver, release_kind = "1.0.0", "initial"
            else:
                semver, release_kind = next_semver(current_semver, body.bump), body.bump
            inserted = await one(
                connection,
                """
                INSERT INTO skill_versions(
                    id,tenant_id,business_id,workspace_id,skill_id,version,semver,
                    release_kind,definition_schema_version,definition,
                    definition_digest,release_notes,source_draft_revision,
                    test_run_id,rollback_from,created_by,package_id
                ) VALUES(
                    :id,:tenant,:business,:workspace,:skill,:version,:semver,
                    :kind,:schema,CAST(:definition AS jsonb),:digest,:notes,
                    :source_revision,:test_run,NULL,:actor,:package
                )
                RETURNING *
                """,
                id=uuid4(),
                tenant=tenant,
                business=resolved.business_id,
                workspace=resolved.workspace_id,
                skill=locked["id"],
                version=next_version,
                semver=semver,
                kind=release_kind,
                schema=SCHEMA_VERSION,
                package=locked.get("draft_package_id"),
                definition=canonical_definition(definition),
                digest=digest,
                notes=body.release_notes,
                source_revision=body.revision,
                test_run=latest["id"],
                actor=actor,
            )
            await execute(
                connection,
                """
                UPDATE skills
                SET published_version=:version,published_revision=:revision,
                    status='published',updated_by=:actor,updated_at=now()
                WHERE tenant_id=:tenant AND business_id=:business
                  AND workspace_id=:workspace AND id=:id
                """,
                version=next_version,
                revision=body.revision,
                actor=actor,
                tenant=tenant,
                business=resolved.business_id,
                workspace=resolved.workspace_id,
                id=locked["id"],
            )
            await audit(
                connection,
                tenant,
                actor,
                "skill.published",
                inserted["id"],
                skill_id=str(locked["id"]),
                version=next_version,
                semver=semver,
                release_kind=release_kind,
                source_draft_revision=body.revision,
                definition_digest=digest,
            )
        return _version(inserted)

    async def rollback(
        self,
        tenant: str,
        actor: str,
        skill_key: str,
        body: SkillRollbackRequest,
        *,
        scope: BusinessScope | None,
    ) -> dict[str, Any]:
        resolved = persisted_scope(tenant, scope)
        async with self.engine.begin() as connection:
            locked = await self._lock_skill(connection, tenant, resolved, skill_key)
            if locked["draft_revision"] != body.revision:
                raise DomainError("skill_revision_conflict", 409)
            current_version = locked.get("published_version")
            if current_version is None or body.target_version >= current_version:
                raise DomainError("skill_version_not_found", 404)
            target = await one(
                connection,
                """
                SELECT * FROM skill_versions
                WHERE tenant_id=:tenant AND business_id=:business
                  AND workspace_id=:workspace AND skill_id=:skill AND version=:version
                """,
                tenant=tenant,
                business=resolved.business_id,
                workspace=resolved.workspace_id,
                skill=locked["id"],
                version=body.target_version,
            )
            if target is None:
                raise DomainError("skill_version_not_found", 404)
            definition = _validated_definition(target["definition"], require_release=True)
            available, reason = await self._dependencies_available(
                connection,
                tenant,
                resolved,
                definition,
            )
            if not available:
                raise DomainError("skill_dependency_unavailable", 409)
            next_version = (
                await one(
                    connection,
                    """
                    SELECT COALESCE(max(version),0)+1 version
                    FROM skill_versions
                    WHERE tenant_id=:tenant AND business_id=:business
                      AND workspace_id=:workspace AND skill_id=:skill
                    """,
                    tenant=tenant,
                    business=resolved.business_id,
                    workspace=resolved.workspace_id,
                    skill=locked["id"],
                )
            )["version"]
            semver = patch_semver(locked.get("current_semver"))
            inserted = await one(
                connection,
                """
                INSERT INTO skill_versions(
                    id,tenant_id,business_id,workspace_id,skill_id,version,semver,
                    release_kind,definition_schema_version,definition,
                    definition_digest,release_notes,source_draft_revision,
                    test_run_id,rollback_from,created_by,package_id
                ) VALUES(
                    :id,:tenant,:business,:workspace,:skill,:version,:semver,
                    'rollback',:schema,CAST(:definition AS jsonb),:digest,:notes,
                    :source_revision,NULL,:rollback_from,:actor,:package
                )
                RETURNING *
                """,
                id=uuid4(),
                tenant=tenant,
                business=resolved.business_id,
                workspace=resolved.workspace_id,
                skill=locked["id"],
                version=next_version,
                semver=semver,
                schema=SCHEMA_VERSION,
                # Rollback restores the release pointer, not the draft, so the
                # package recorded here is whatever that version shipped with.
                package=target.get("package_id"),
                definition=json.dumps(target["definition"], ensure_ascii=False),
                digest=target["definition_digest"],
                notes=body.release_notes,
                source_revision=target["source_draft_revision"],
                rollback_from=body.target_version,
                actor=actor,
            )
            await execute(
                connection,
                """
                UPDATE skills
                SET published_version=:version,published_revision=:revision,
                    status='published',updated_by=:actor,updated_at=now()
                WHERE tenant_id=:tenant AND business_id=:business
                  AND workspace_id=:workspace AND id=:id
                """,
                version=next_version,
                revision=target["source_draft_revision"],
                actor=actor,
                tenant=tenant,
                business=resolved.business_id,
                workspace=resolved.workspace_id,
                id=locked["id"],
            )
            await audit(
                connection,
                tenant,
                actor,
                "skill.rolled_back",
                inserted["id"],
                skill_id=str(locked["id"]),
                version=next_version,
                semver=semver,
                rollback_from=body.target_version,
                definition_digest=target["definition_digest"],
                dependency_reason=reason,
            )
        return _version(inserted)

    async def package(
        self,
        tenant: str,
        skill_key: str,
        *,
        scope: BusinessScope | None,
    ) -> dict[str, Any]:
        """Return the working package's manifest. Reads Postgres, never S3."""

        resolved = persisted_scope(tenant, scope)
        async with self.engine.connect() as connection:
            row = await _fetch_skill(connection, tenant, resolved, skill_key)
            if not row.get("package_digest"):
                raise DomainError("skill_package_not_found", 404)
            stored = await one(
                connection,
                """
                SELECT * FROM skill_packages
                WHERE tenant_id=:tenant AND business_id=:business
                  AND workspace_id=:workspace AND id=:id
                """,
                tenant=tenant,
                business=resolved.business_id,
                workspace=resolved.workspace_id,
                id=row["draft_package_id"],
            )
        if stored is None:
            raise DomainError("skill_package_not_found", 404)
        return _package_record(stored)

    async def attach_package(
        self,
        tenant: str,
        actor: str,
        skill_key: str,
        filename: str,
        content: bytes,
        *,
        scope: BusinessScope | None,
    ) -> dict[str, Any]:
        """Verify an uploaded archive, store it, and bind it to the draft.

        The bytes reach object storage *before* the transaction opens: a slow
        upload must not hold a row lock, and a leftover object after a
        rolled-back insert is garbage rather than a correctness problem.
        """

        resolved = persisted_scope(tenant, scope)
        if len(content) > self.settings.skill_package_bytes:
            raise DomainError("skill_package_too_large", 413)
        try:
            inspected = inspect_package(content)
        except PackageRejected as exc:
            raise DomainError(exc.code, exc.status) from None

        archive = S3Archive(self.settings, profile="skill")
        if not archive.configured():
            raise DomainError("skill_package_storage_unavailable", 503)

        key = _package_key(tenant, resolved, skill_key, inspected.digest)
        placed = await archive.put(key, content, "application/zip")
        superseded: list[str] = []
        try:
            await self._bind_package(
                tenant,
                actor,
                resolved,
                skill_key,
                _package_filename(filename),
                inspected,
                key,
                placed.get("bucket") or "unknown",
                superseded,
            )
        except DomainError:
            # The insert never committed, so the object has no referent.
            await archive.delete(key)
            raise
        for stale in superseded:
            await archive.delete(stale)
        async with self.engine.connect() as connection:
            row = await _fetch_skill(connection, tenant, resolved, skill_key)
        return _record(row)

    async def import_package(
        self,
        tenant: str,
        actor: str,
        filename: str,
        content: bytes,
        *,
        scope: BusinessScope | None,
    ) -> dict[str, Any]:
        """Create a new Skill from a verified archive, package included.

        Unlike :meth:`attach_package` this cannot store the object before the
        transaction: the storage key embeds the Skill key, and the key is only
        known once the row exists (collisions get a numeric suffix). The trade is
        acceptable because the row is brand new and invisible to everyone else,
        so holding its transaction open competes with no reader or writer.

        Everything the caller did not supply -- name, description, instructions --
        comes from the package's ``SKILL.md`` rather than from a form, which is
        the whole point of importing: the archive is the source of truth.
        """

        resolved = persisted_scope(tenant, scope)
        if len(content) > self.settings.skill_package_bytes:
            raise DomainError("skill_package_too_large", 413)
        try:
            inspected = inspect_package(content)
        except PackageRejected as exc:
            raise DomainError(exc.code, exc.status) from None

        archive = S3Archive(self.settings, profile="skill")
        if not archive.configured():
            raise DomainError("skill_package_storage_unavailable", 503)

        definition = _definition_from_package(inspected)
        classification = classify_skill(
            definition,
            PackageFacts(
                present=True,
                has_scripts=inspected.has_scripts,
                entrypoint=inspected.entrypoint,
            ),
        )
        name = inspected.skill_name.strip()[:100] or "Imported Skill"
        s3_key = ""
        placed: dict[str, Any] | None = None
        try:
            async with self.engine.begin() as connection:
                row = await self._insert_unique_skill(
                    connection,
                    tenant,
                    resolved,
                    actor,
                    skill_key=_base_key(name),
                    name=name,
                    description=inspected.skill_description.strip()[:1000],
                    category="general",
                    tags=_package_tags(inspected),
                    definition=definition,
                    classification=classification,
                )
                s3_key = _package_key(tenant, resolved, row["skill_key"], inspected.digest)
                placed = await archive.put(s3_key, content, "application/zip")
                package_id = await _insert_package_row(
                    connection,
                    tenant,
                    resolved,
                    row["id"],
                    _package_filename(filename),
                    inspected,
                    s3_key,
                    placed.get("bucket") or "unknown",
                    actor,
                )
                # The revision stays at 1: this is one creation event, not a
                # create followed by an attach. Readers still see a draft, so
                # nothing is published by importing.
                await execute(
                    connection,
                    """
                    UPDATE skills
                    SET draft_package_id=:package
                    WHERE tenant_id=:tenant AND business_id=:business
                      AND workspace_id=:workspace AND id=:id
                    """,
                    package=package_id,
                    tenant=tenant,
                    business=resolved.business_id,
                    workspace=resolved.workspace_id,
                    id=row["id"],
                )
                await audit(
                    connection,
                    tenant,
                    actor,
                    "skill.imported",
                    row["id"],
                    key=row["skill_key"],
                    filename=_package_filename(filename),
                    digest=inspected.digest,
                    size_bytes=inspected.size_bytes,
                    file_count=inspected.file_count,
                    has_scripts=inspected.has_scripts,
                    entrypoint=inspected.entrypoint,
                    weight_class=classification.weight_class,
                    risk_level=classification.risk_level,
                )
                row = await _fetch_skill(
                    connection,
                    tenant,
                    resolved,
                    row["skill_key"],
                    aliases=True,
                )
        except BaseException:
            # The transaction rolled back, so the object has no referent.
            if placed is not None:
                await archive.delete(s3_key)
            raise
        return _record(row)

    async def detach_package(
        self,
        tenant: str,
        actor: str,
        skill_key: str,
        *,
        scope: BusinessScope | None,
    ) -> dict[str, Any]:
        resolved = persisted_scope(tenant, scope)
        async with self.engine.begin() as connection:
            row = await _fetch_skill(
                connection,
                tenant,
                resolved,
                skill_key,
                lock=True,
            )
            if row["status"] == "archived":
                raise DomainError("skill_revision_conflict", 409)
            package_id = row.get("draft_package_id")
            if not package_id:
                raise DomainError("skill_package_not_found", 404)
            definition = SkillDefinition.model_validate(row["draft_definition"])
            computed = classify_skill(definition, PackageFacts())
            await execute(
                connection,
                """
                UPDATE skills
                SET draft_package_id=NULL,weight_class=:weight_class,
                    data_scope=CAST(:data_scope AS text[]),
                    draft_revision=draft_revision+1,updated_by=:actor,updated_at=now()
                WHERE tenant_id=:tenant AND business_id=:business
                  AND workspace_id=:workspace AND id=:id
                """,
                weight_class=computed.weight_class,
                data_scope=list(computed.data_scope),
                actor=actor,
                tenant=tenant,
                business=resolved.business_id,
                workspace=resolved.workspace_id,
                id=row["id"],
            )
            await execute(
                connection,
                "DELETE FROM skill_packages WHERE id=:id",
                id=package_id,
            )
            await audit(
                connection,
                tenant,
                actor,
                "skill.package_detached",
                row["id"],
                key=skill_key,
                digest=row.get("package_digest"),
                weight_class=computed.weight_class,
            )
            stale_key = row.get("package_s3_key")
        archive = S3Archive(self.settings, profile="skill")
        if stale_key and archive.configured():
            await archive.delete(stale_key)
        async with self.engine.connect() as connection:
            row = await _fetch_skill(connection, tenant, resolved, skill_key)
        return _record(row)

    async def _bind_package(
        self,
        tenant: str,
        actor: str,
        resolved: BusinessScope,
        skill_key: str,
        filename: str,
        inspected: InspectedPackage,
        s3_key: str,
        s3_bucket: str,
        superseded: list[str],
    ) -> None:
        async with self.engine.begin() as connection:
            row = await _fetch_skill(
                connection,
                tenant,
                resolved,
                skill_key,
                lock=True,
            )
            if row["status"] == "archived":
                raise DomainError("skill_revision_conflict", 409)
            definition = SkillDefinition.model_validate(row["draft_definition"])
            facts = PackageFacts(
                present=True,
                has_scripts=inspected.has_scripts,
                entrypoint=inspected.entrypoint,
            )
            computed = classify_skill(definition, facts)
            package_id = await _insert_package_row(
                connection,
                tenant,
                resolved,
                row["id"],
                filename,
                inspected,
                s3_key,
                s3_bucket,
                actor,
            )
            # A Skill carries exactly one working package, so the previous row
            # is replaced rather than accumulated. Its object is deleted by the
            # caller once this transaction commits.
            if row.get("draft_package_id"):
                if row.get("package_s3_key"):
                    superseded.append(row["package_s3_key"])
                await execute(
                    connection,
                    "DELETE FROM skill_packages WHERE id=:id",
                    id=row["draft_package_id"],
                )
            await execute(
                connection,
                """
                UPDATE skills
                SET draft_package_id=:package,weight_class=:weight_class,
                    data_scope=CAST(:data_scope AS text[]),
                    draft_revision=draft_revision+1,updated_by=:actor,updated_at=now()
                WHERE tenant_id=:tenant AND business_id=:business
                  AND workspace_id=:workspace AND id=:id
                """,
                package=package_id,
                weight_class=computed.weight_class,
                data_scope=list(computed.data_scope),
                actor=actor,
                tenant=tenant,
                business=resolved.business_id,
                workspace=resolved.workspace_id,
                id=row["id"],
            )
            await audit(
                connection,
                tenant,
                actor,
                "skill.package_attached",
                row["id"],
                key=skill_key,
                filename=filename[:255],
                digest=inspected.digest,
                size_bytes=inspected.size_bytes,
                file_count=inspected.file_count,
                has_scripts=inspected.has_scripts,
                entrypoint=inspected.entrypoint,
                weight_class=computed.weight_class,
            )

    async def _insert_unique_skill(
        self,
        connection,
        tenant: str,
        scope: BusinessScope,
        actor: str,
        *,
        skill_key: str,
        name: str,
        description: str,
        category: str,
        tags: list[str],
        definition: SkillDefinition,
        classification: Classification,
    ) -> dict[str, Any]:
        base = skill_key[:56].rstrip("_-") or "skill"
        for attempt in range(100):
            candidate = base if attempt == 0 else f"{base}-{attempt + 1}"
            candidate = candidate[:64].rstrip("_-")
            try:
                row = await one(
                    connection,
                    """
                    INSERT INTO skills(
                        id,tenant_id,business_id,workspace_id,skill_key,name,
                        description,category,tags,visibility,status,
                        definition_schema_version,draft_definition,draft_revision,
                        weight_class,risk_level,data_scope,
                        created_by,updated_by
                    ) VALUES(
                        :id,:tenant,:business,:workspace,:key,:name,:description,
                        :category,CAST(:tags AS text[]),'workspace','draft',:schema,
                        CAST(:definition AS jsonb),1,
                        :weight_class,:risk_level,CAST(:data_scope AS text[]),
                        :actor,:actor
                    )
                    ON CONFLICT (tenant_id,business_id,workspace_id,skill_key)
                    DO NOTHING
                    RETURNING *
                    """,
                    id=uuid4(),
                    tenant=tenant,
                    business=scope.business_id,
                    workspace=scope.workspace_id,
                    key=candidate,
                    name=name[:100],
                    description=description[:1000],
                    category=category,
                    tags=tags,
                    schema=SCHEMA_VERSION,
                    definition=canonical_definition(definition),
                    weight_class=classification.weight_class,
                    risk_level=classification.risk_level,
                    data_scope=list(classification.data_scope),
                    actor=actor,
                )
            except IntegrityError:
                raise DomainError("skill_definition_invalid", 422) from None
            if row:
                return row
        raise DomainError("skill_key_conflict", 409)

    async def _lock_skill(
        self,
        connection,
        tenant: str,
        scope: BusinessScope,
        skill_key: str,
    ) -> dict[str, Any]:
        initial = await _fetch_skill(connection, tenant, scope, skill_key)
        lock_key = f"{tenant}:{scope.business_id}:{scope.workspace_id}:{initial['id']}"
        acquired = (
            await one(
                connection,
                "SELECT pg_try_advisory_xact_lock(hashtextextended(:key,760)) acquired",
                key=lock_key,
            )
        )["acquired"]
        if not acquired:
            raise DomainError("skill_publish_in_progress", 409)
        row = await _fetch_skill(connection, tenant, scope, skill_key, lock=True)
        if row["id"] != initial["id"]:
            raise DomainError("skill_not_found", 404)
        return row

    async def _readiness(
        self,
        connection,
        tenant: str,
        scope: BusinessScope,
        skill: dict[str, Any],
        can_publish: bool,
    ) -> dict[str, Any]:
        revision = skill["draft_revision"]
        checks: list[dict[str, Any]] = []
        checks.append(_check("draft_saved", "pass", "The current draft is persisted.", "editor"))
        try:
            definition = _validated_definition(
                skill["draft_definition"],
                require_release=True,
            )
            checks.append(
                _check(
                    "required_fields_valid",
                    "pass",
                    "Required definition fields are valid.",
                    "capability",
                )
            )
            valid = True
        except (DomainError, ValueError) as exc:
            definition = None
            valid = False
            checks.append(
                _check(
                    "required_fields_valid",
                    "fail",
                    str(getattr(exc, "code", None) or exc)[:200],
                    "capability",
                )
            )
        latest = await one(
            connection,
            """
            SELECT * FROM skill_test_runs
            WHERE tenant_id=:tenant AND business_id=:business
              AND workspace_id=:workspace AND skill_id=:skill
              AND draft_revision=:revision
            ORDER BY created_at DESC,id DESC LIMIT 1
            """,
            tenant=tenant,
            business=scope.business_id,
            workspace=scope.workspace_id,
            skill=skill["id"],
            revision=revision,
        )
        if latest is None:
            checks.append(
                _check(
                    "latest_test_passed",
                    "fail",
                    "No test run exists for the current draft revision.",
                    "tests",
                )
            )
        elif latest["status"] != "passed":
            checks.append(
                _check(
                    "latest_test_passed",
                    "fail",
                    f"The latest test for draft r{revision} is {latest['status']}.",
                    "tests",
                )
            )
        else:
            checks.append(
                _check(
                    "latest_test_passed",
                    "pass",
                    "The latest test for the current draft passed.",
                    "tests",
                )
            )
        if definition is not None:
            available, reason = await self._dependencies_available(
                connection,
                tenant,
                scope,
                definition,
            )
        else:
            available, reason = False, "definition_invalid"
        checks.append(
            _check(
                "dependencies_available",
                "pass" if available else "fail",
                "All declared dependencies are available."
                if available
                else f"Dependency unavailable: {reason}",
                "dependencies",
            )
        )
        checks.append(
            _check(
                "permission_granted",
                "pass" if can_publish else "fail",
                "The caller can publish Skills."
                if can_publish
                else "The caller lacks skill.publish permission.",
                None if can_publish else "permission",
            )
        )
        publish_available = skill["status"] != "archived"
        checks.append(
            _check(
                "publish_available",
                "pass" if publish_available else "fail",
                "A new version can be published."
                if publish_available
                else "Archived Skills cannot be published.",
                "versions",
            )
        )
        ready = (
            valid
            and available
            and can_publish
            and publish_available
            and (latest is not None and latest["status"] == "passed")
        )
        return {
            "skill_id": str(skill["id"]),
            "draft_revision": revision,
            "ready": ready,
            "checks": checks,
            "next_semver": (
                "1.0.0"
                if skill.get("current_semver") is None
                else patch_semver(skill.get("current_semver"))
            ),
        }

    async def _dependencies_available(
        self,
        connection,
        tenant: str,
        scope: BusinessScope,
        definition: SkillDefinition,
    ) -> tuple[bool, str]:
        dependencies = definition.dependencies
        if dependencies.model_profile_id is not None:
            if dependencies.model_profile_version is None:
                return False, "model_profile_version"
            try:
                await self.gateway.catalog.resolve(
                    tenant,
                    dependencies.model_profile_id,
                    dependencies.model_profile_version,
                    connection,
                )
            except DomainError as exc:
                return False, exc.code
        if dependencies.knowledge_base_ids:
            rows = await many(
                connection,
                """
                SELECT id FROM knowledge_bases k
                WHERE tenant_id=:tenant AND business_id=:business
                  AND workspace_id=:workspace AND enabled
                  AND id=ANY(CAST(:ids AS uuid[]))
                """,
                tenant=tenant,
                business=scope.business_id,
                workspace=scope.workspace_id,
                ids=dependencies.knowledge_base_ids,
            )
            if {row["id"] for row in rows} != set(dependencies.knowledge_base_ids):
                return False, "knowledge_base_unavailable"
        if dependencies.tool_names:
            try:
                rows = await self.tools.resolve(
                    tenant,
                    dependencies.tool_names,
                    connection=connection,
                )
            except DomainError as exc:
                return False, exc.code
            effects = {str(row.get("spec", {}).get("effect", "unknown")) for row in rows}
            if definition.type == "query" and "read" not in effects:
                return False, "read_tool_required"
            if definition.type == "action" and "write" not in effects:
                return False, "write_tool_required"
        if (
            definition.type == "handoff" or definition.runtime.error_behavior == "handoff"
        ) and not dependencies.handoff_queue:
            return False, "handoff_queue_unavailable"
        return True, "available"


def _validated_definition(
    raw: dict[str, Any] | SkillDefinition,
    *,
    require_release: bool = False,
) -> SkillDefinition:
    try:
        definition = (
            raw if isinstance(raw, SkillDefinition) else SkillDefinition.model_validate(raw)
        )
        if require_release:
            definition.validate_for_release()
    except ValueError as exc:
        raise SkillDefinitionInvalidError(_sanitized_definition_errors(exc)) from exc
    return definition


def _sanitized_definition_errors(exc: ValueError) -> list[dict[str, Any]]:
    """Expose only pydantic field locations, safe types, and safe messages."""

    if isinstance(exc, ValidationError):
        errors = []
        for item in exc.errors(include_input=False, include_context=False):
            location = ["definition"]
            location.extend(
                str(part) for part in item.get("loc", ()) if isinstance(part, (str, int))
            )
            error_type = str(item.get("type", "validation_error"))
            errors.append(
                {
                    "loc": location,
                    "type": error_type,
                    "msg": _safe_definition_error_message(error_type, item.get("msg")),
                }
            )
        if errors:
            return errors
    return [
        {
            "loc": ["definition"],
            "type": "value_error",
            "msg": _safe_definition_error_message("value_error", str(exc)),
        }
    ]


def _safe_definition_error_message(error_type: str, message: Any) -> str:
    """Return a bounded static message; unknown value errors degrade safely."""

    first_line = str(message or "").splitlines()[0].strip()[:300]
    if error_type != "value_error":
        return first_line or "definition validation failed"
    body = first_line.removeprefix("Value error, ")
    if body.startswith("default for parameter ") and body.endswith(
        " does not match the declared type"
    ):
        return "parameter default does not match the declared type"
    if body.startswith("output schema is invalid:"):
        return "output schema is invalid"
    if body in _DEFINITION_VALUE_ERROR_MESSAGES or _DEFINITION_TOOL_REQUIRED.fullmatch(body):
        return first_line
    return "definition validation failed"


def _scope_sql(scope: BusinessScope, alias: str) -> tuple[str, dict[str, str]]:
    clause, params = scope_predicate(scope, alias)
    prefix = f"{alias}." if alias else ""
    return f"{prefix}tenant_id=:tenant AND {clause}", params


# Usage and rating are derived, never stored on ``skills``: a row here is a
# fact about behaviour, so the catalogue reads it back through a lateral
# aggregate. LATERAL keeps this a single round-trip for a page of cards, and
# an empty aggregate still yields one row, so ``COALESCE``/``count`` give a
# clean zero rather than dropping the Skill from the result.
USAGE_RATING_JOIN = """
LEFT JOIN LATERAL (
    SELECT COALESCE(sum(u.runs),0)::int AS usage_total,
           COALESCE(sum(u.succeeded),0)::int AS usage_succeeded
    FROM skill_usage_daily u
    WHERE u.tenant_id=s.tenant_id AND u.business_id=s.business_id
      AND u.workspace_id=s.workspace_id AND u.skill_id=s.id
) usage ON true
LEFT JOIN LATERAL (
    SELECT count(*)::int AS rating_count, avg(r.score)::float AS rating_avg
    FROM skill_ratings r
    WHERE r.tenant_id=s.tenant_id AND r.business_id=s.business_id
      AND r.workspace_id=s.workspace_id AND r.skill_id=s.id
) rating ON true
"""


# Sort keys the catalogue accepts. Ordering happens in SQL because the list is
# paginated there as well: sorting the rows of a single page would only shuffle
# that page and leave the sequence across pages wrong.
_LIST_ORDERS = {
    "latest": "s.updated_at DESC,s.id",
    "name": "s.name,s.id",
    "usage": "usage.usage_total DESC,s.name,s.id",
}


def _list_order(sort: str) -> str:
    # An unknown key falls back rather than erroring: a stale client or an old
    # bookmarked URL should still get a list instead of a 422.
    return _LIST_ORDERS.get(sort, _LIST_ORDERS["latest"])


def _pct_change(current: float | None, previous: float | None) -> float | None:
    """Percent change versus the prior window, or None when there is no base.

    Returning None instead of 0 matters: "no history" and "flat" are different
    statements, and the arrow must not claim the second when it means the first.
    """

    if current is None or previous in (None, 0):
        return None
    return round((current - previous) / previous * 100, 1)


def _facet_where(
    base: str,
    q: str,
    *,
    category: str = "all",
    status: str = "all",
    risk: str = "all",
    weight: str = "all",
) -> str:
    clauses = [base]
    if q.strip():
        clauses.append(
            "(s.name ILIKE :query OR s.description ILIKE :query "
            "OR s.skill_key ILIKE :query OR :query_text = ANY(s.tags))"
        )
    if category != "all":
        clauses.append("s.category=:category")
    if status != "all":
        clauses.append("s.status=:status")
    if risk != "all":
        clauses.append("s.risk_level=:risk")
    if weight != "all":
        clauses.append("s.weight_class=:weight")
    return " AND ".join(clauses)


async def _fetch_skill(
    connection,
    tenant: str,
    scope: BusinessScope,
    skill_key: str,
    *,
    lock: bool = False,
    aliases: bool = False,
) -> dict[str, Any]:
    base, params = _scope_sql(scope, "s")
    row = await one(
        connection,
        """
        SELECT s.*,v.semver AS current_semver,v.created_at AS published_at,
               pkg.digest AS package_digest,pkg.size_bytes AS package_size,
               pkg.file_count AS package_file_count,
               pkg.has_scripts AS package_has_scripts,
               pkg.entrypoint AS package_entrypoint,
               pkg.s3_key AS package_s3_key,pkg.s3_bucket AS package_s3_bucket,
               pkg.filename AS package_filename,
               pkg.created_at AS package_created_at,
               usage.usage_total,usage.usage_succeeded,
               rating.rating_count,rating.rating_avg
        FROM skills s
        LEFT JOIN skill_versions v
          ON v.tenant_id=s.tenant_id
         AND v.business_id=s.business_id
         AND v.workspace_id=s.workspace_id
         AND v.skill_id=s.id
         AND v.version=s.published_version
        LEFT JOIN skill_packages pkg ON pkg.id=s.draft_package_id
        """
        + USAGE_RATING_JOIN
        + """
        WHERE """
        + base
        + " AND s.skill_key=:skill_key"
        + (" FOR UPDATE OF s" if lock else ""),
        tenant=tenant,
        skill_key=skill_key,
        **params,
    )
    if row is None:
        raise DomainError("skill_not_found", 404)
    return row


def _summary(row: dict[str, Any]) -> dict[str, Any]:
    draft_revision = int(row["draft_revision"])
    published_revision = row.get("published_revision")
    computed = classify_skill(row.get("draft_definition") or {})
    return {
        "id": str(row["id"]),
        "key": row["skill_key"],
        "name": row["name"],
        "description": row["description"],
        "category": row["category"],
        "tags": list(row.get("tags") or []),
        "visibility": "workspace",
        "status": row["status"],
        "weight_class": row.get("weight_class") or computed.weight_class,
        "risk_level": effective_risk(row.get("risk_level"), computed.risk_level),
        "risk_computed": computed.risk_level,
        "risk_reasons": computed.reasons_payload(),
        "data_scope": list(ordered_scope(row.get("data_scope") or computed.data_scope)),
        "draft_revision": draft_revision,
        "published_version": row.get("published_version"),
        "published_revision": published_revision,
        "current_semver": row.get("current_semver"),
        "has_unpublished_changes": (
            published_revision is not None and draft_revision != published_revision
        ),
        "created_by": row["created_by"],
        "updated_by": row["updated_by"],
        "created_at": _iso(row["created_at"]),
        "updated_at": _iso(row["updated_at"]),
        "published_at": _iso(row.get("published_at")),
        **_usage_rating(row),
    }


def _usage_rating(row: dict[str, Any]) -> dict[str, Any]:
    """Behavioural facts, absent on rows that were not read with the aggregates.

    Rows produced by writes (create, save_draft) do not join the aggregate
    tables, so they fall back to "not measured yet" instead of inventing zero,
    which would read as "used zero times" on a freshly created Skill.
    """

    total = row.get("usage_total")
    succeeded = row.get("usage_succeeded")
    count = row.get("rating_count")
    return {
        "usage_count": int(total) if total is not None else None,
        "success_rate": (
            round(int(succeeded) / int(total), 4)
            if total not in (None, 0) and succeeded is not None
            else None
        ),
        "rating_avg": (
            round(float(row["rating_avg"]), 2) if row.get("rating_avg") is not None else None
        ),
        "rating_count": int(count) if count is not None else None,
    }


def _record(row: dict[str, Any]) -> dict[str, Any]:
    return {
        **_summary(row),
        "definition": row["draft_definition"],
        "package": _package_brief(row),
    }


def _package_brief(row: dict[str, Any]) -> dict[str, Any] | None:
    """Describe the attached archive without dragging its manifest along.

    The manifest can hold hundreds of entries; the editor only needs to show
    what is attached. Callers that want the file list hit the package endpoint.
    """

    if not row.get("package_digest"):
        return None
    return {
        "digest": row["package_digest"],
        "filename": row.get("package_filename"),
        "size_bytes": row.get("package_size"),
        "file_count": row.get("package_file_count"),
        "has_scripts": bool(row.get("package_has_scripts")),
        "entrypoint": row.get("package_entrypoint"),
        "created_at": _iso(row.get("package_created_at")),
    }


def _package_facts(row: dict[str, Any]) -> PackageFacts:
    """Facts about the attached archive, as later decisions must see them."""

    if not row.get("package_digest"):
        return PackageFacts()
    return PackageFacts(
        present=True,
        has_scripts=bool(row.get("package_has_scripts")),
        entrypoint=row.get("package_entrypoint"),
    )


def _definition_from_package(inspected: InspectedPackage) -> SkillDefinition:
    """Map a ``SKILL.md`` document onto the platform's definition model.

    The body is the instruction text. Frontmatter fields the platform does not
    model (``allowed-tools``, ``license``, ...) stay in the package manifest on
    purpose: guessing them into ``dependencies`` would silently widen what the
    Skill claims to be allowed to touch.
    """

    instructions = inspected.body.strip() or inspected.skill_description.strip()
    if len(instructions) > 20_000:
        # The column caps at 20k. Truncating would quietly drop part of a third
        # party's instructions, which changes behaviour rather than just looks.
        raise DomainError("skill_package_instructions_too_long", 422)
    return _validated_definition(
        {
            "schema_version": "v1",
            "creation_mode": "package",
            "type": "instruction",
            "trigger": "agent_auto",
            "instructions": instructions,
            "permission_scope": "workspace",
        }
    )


def _package_tags(inspected: InspectedPackage) -> list[str]:
    """Carry the archive's own tags across, bounded so a zip cannot spam facets."""

    raw = inspected.frontmatter.get("tags")
    values = raw if isinstance(raw, list) else [raw] if isinstance(raw, str) else []
    tags: list[str] = []
    for value in values:
        text = str(value).strip()[:32]
        if text and text not in tags:
            tags.append(text)
        if len(tags) >= 8:
            break
    return tags


async def _insert_package_row(
    connection: Any,
    tenant: str,
    scope: BusinessScope,
    skill_id: Any,
    filename: str,
    inspected: InspectedPackage,
    s3_key: str,
    s3_bucket: str,
    actor: str,
) -> UUID:
    """Write one ``skill_packages`` row on an existing transaction."""

    package_id = uuid4()
    await execute(
        connection,
        """
        INSERT INTO skill_packages(
            id,tenant_id,business_id,workspace_id,skill_id,
            s3_bucket,s3_key,digest,size_bytes,file_count,manifest,
            entrypoint,has_scripts,created_by,filename
        ) VALUES(
            :id,:tenant,:business,:workspace,:skill,
            :bucket,:key,:digest,:size,:files,CAST(:manifest AS jsonb),
            :entrypoint,:has_scripts,:actor,:filename
        )
        """,
        id=package_id,
        tenant=tenant,
        business=scope.business_id,
        workspace=scope.workspace_id,
        skill=skill_id,
        bucket=s3_bucket,
        key=s3_key,
        digest=inspected.digest,
        size=inspected.size_bytes,
        files=inspected.file_count,
        manifest=json.dumps(inspected.manifest(), ensure_ascii=False),
        entrypoint=inspected.entrypoint,
        has_scripts=inspected.has_scripts,
        actor=actor,
        filename=filename,
    )
    return package_id


def _package_key(tenant: str, scope: BusinessScope, skill_key: str, digest: str) -> str:
    """Digest addressed, never overwritten: same key always means same bytes."""

    hexdigest = digest.split(":", 1)[-1]
    return (
        f"skills/{tenant}/{scope.business_id}/{scope.workspace_id}/{skill_key}/{hexdigest}.zip"
    )


def _package_filename(raw: str) -> str:
    """Reduce a caller-supplied name to a displayable label.

    The name is never trusted for anything but display, so this strips rather
    than rejects: browsers on some platforms send full paths, and a client that
    sends control characters should get a sane label, not an error after its
    bytes are already in object storage.
    """

    name = raw.replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(ch for ch in name if ch.isprintable()).strip()
    return name[:255] or "package.zip"


def _package_record(stored: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(stored["id"]),
        "digest": stored["digest"],
        "filename": stored.get("filename"),
        "size_bytes": stored["size_bytes"],
        "file_count": stored["file_count"],
        "entrypoint": stored.get("entrypoint"),
        "has_scripts": bool(stored.get("has_scripts")),
        "created_by": stored["created_by"],
        "created_at": _iso(stored["created_at"]),
        "manifest": stored["manifest"],
    }


def _run(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "skill_id": str(row["skill_id"]),
        "draft_revision": row["draft_revision"],
        "status": row["status"],
        "execution_kind": row["execution_kind"],
        "input": row["input"],
        "input_summary": row["input_summary"],
        "output": row.get("output"),
        "diagnostics": row["diagnostics"],
        "reason_code": row.get("reason_code"),
        "duration_ms": row["duration_ms"],
        "executed_by": row["executed_by"],
        "created_at": _iso(row["created_at"]),
    }


def _version(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "skill_id": str(row["skill_id"]),
        "version": row["version"],
        "semver": row["semver"],
        "release_kind": row["release_kind"],
        "definition": row["definition"],
        "definition_digest": row["definition_digest"],
        "release_notes": row["release_notes"],
        "source_draft_revision": row["source_draft_revision"],
        "test_run_id": str(row["test_run_id"]) if row.get("test_run_id") else None,
        "rollback_from": row.get("rollback_from"),
        "created_by": row["created_by"],
        "created_at": _iso(row["created_at"]),
    }


def _check(
    code: str,
    status: str,
    reason: str,
    destination: str | None,
) -> dict[str, Any]:
    return {
        "code": code,
        "status": status,
        "reason": reason,
        "destination": destination,
    }


def _base_key(name: str) -> str:
    value = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    value = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if not value:
        return "skill-" + uuid4().hex[:8]
    if not value[0].isalpha():
        value = "skill-" + value
    return value[:64].rstrip("_-")


def _default_skill_name(definition: dict[str, Any]) -> str:
    instructions = str(definition.get("instructions", "")).strip()
    if instructions:
        return instructions.splitlines()[0][:100]
    skill_type = str(definition.get("type", "skill"))
    return "New " + skill_type.title() + " Skill"


def _input_summary(value: dict[str, Any]) -> str:
    try:
        compact = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        return ""
    return compact if len(compact) <= 500 else compact[:497] + "..."


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


__all__ = ["SkillLibraryService"]
