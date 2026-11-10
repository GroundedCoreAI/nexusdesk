"""Versioned service-scenario configuration and deterministic simulation."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

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

from .models import ScenarioConfig, ScenarioStatus, SimulationRequest
from .simulation import simulate as simulate_config
from .tool_bridge import ObjectResolution, ScenarioToolBridge

MAX_TRACE_LIMIT = 200

_TRACE_OUTCOMES = {
    "succeeded": "succeeded",
    "failed": "failed",
    "needs_input": "needs_input",
    "denied": "denied",
    "handoff": "delegated",
    "tracking": "succeeded",
    "simulated": "simulated",
}


def _public_row(row: dict[str, Any]) -> dict[str, Any]:
    """Keep the stable API shape independent of physical column names."""

    result = dict(row)
    result["key"] = result.pop("scenario_key")
    result["revision"] = result.pop("draft_revision")
    result["config"] = result.get("draft")
    if "published_config" in result:
        result["published_config"] = result["published_config"]
    return result


def _metrics(volume: int, succeeded: int, handoffs: int) -> dict[str, Any]:
    return {
        "volume": volume,
        "auto_resolved": succeeded,
        "handoffs": handoffs,
        "auto_resolve_rate": round(succeeded / volume, 4) if volume else 0.0,
        "handoff_rate": round(handoffs / volume, 4) if volume else 0.0,
    }


def _trace_outcome(value: Any) -> str:
    """Normalize simulator result states to the persisted trace vocabulary."""

    return _TRACE_OUTCOMES.get(str(value or ""), "simulated")


def _condition_label(condition: dict[str, Any]) -> str:
    """Return a human-readable binding condition for the agent usage view."""

    parts: list[str] = []
    statuses = condition.get("object_statuses") or []
    terms = condition.get("message_terms") or []
    decisions = condition.get("decision_keys") or []
    if statuses:
        parts.append("对象状态：" + " / ".join(str(item) for item in statuses))
    if terms:
        parts.append("消息包含：" + " / ".join(str(item) for item in terms))
    if decisions:
        parts.append("用户决策：" + " / ".join(str(item) for item in decisions))
    if condition.get("requires_object") is True:
        parts.append("已绑定业务对象")
    return "；".join(parts) or "复杂问题或默认兜底"


class ScenarioService:
    """Tenant-scoped scene catalog, draft/publish lifecycle and evidence."""

    def __init__(
        self,
        engine: object,
        agents: object,
        bridge: ScenarioToolBridge | None = None,
    ) -> None:
        self.engine = engine
        self.agents = agents
        # Absent bridge means every provider stays a placeholder, which is what
        # the bundled demo packs and the unit tests rely on.
        self.bridge = bridge

    @staticmethod
    def _verify_status(value: str) -> str:
        allowed = {item.value for item in ScenarioStatus}
        if value not in allowed:
            raise DomainError("scenario_status_invalid", 422)
        return value

    @staticmethod
    def _config(value: ScenarioConfig | dict[str, Any]) -> ScenarioConfig:
        return value if isinstance(value, ScenarioConfig) else ScenarioConfig.model_validate(value)

    @staticmethod
    def _row_config(row: dict[str, Any]) -> ScenarioConfig:
        return ScenarioConfig.model_validate(row["draft"])

    @staticmethod
    def _reject_pack_metadata_injection(config: ScenarioConfig) -> None:
        """Pack lineage is owned by the installer and cannot be forged by CRUD."""

        if "industry_pack" in config.config:
            raise DomainError("scenario_industry_pack_metadata_reserved", 422)

    @staticmethod
    def _preserve_pack_metadata(
        current: ScenarioConfig,
        incoming: ScenarioConfig,
    ) -> None:
        """Keep pack lineage immutable while allowing normal draft edits."""

        if current.config.get("industry_pack") != incoming.config.get("industry_pack"):
            raise DomainError("scenario_industry_pack_metadata_immutable", 409)

    async def list(
        self,
        tenant: str,
        *,
        status: str = "all",
        q: str = "",
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        resolved = persisted_scope(tenant, scope)
        scope_sql, scope_params = scope_predicate(resolved, alias="s")
        status = status if status == "all" else self._verify_status(status)
        async with self.engine.connect() as connection:
            rows = await many(
                connection,
                f"""
WITH metrics AS (
    SELECT scenario_id,
           count(*)::int AS volume,
           count(*) FILTER (WHERE outcome='succeeded')::int AS succeeded,
           count(*) FILTER (WHERE handler_type='human')::int AS handoffs
    FROM service_scenario_traces
    WHERE tenant_id=:tenant
      AND business_id=:scope_business
      AND workspace_id=:scope_workspace
      AND NOT simulation
      AND created_at>=now()-interval '7 days'
    GROUP BY scenario_id
)
SELECT s.*,
       COALESCE(m.volume,0)::int AS metric_volume,
       COALESCE(m.succeeded,0)::int AS metric_succeeded,
       COALESCE(m.handoffs,0)::int AS metric_handoffs
FROM service_scenarios s
LEFT JOIN metrics m ON m.scenario_id=s.id
WHERE s.tenant_id=:tenant
  AND {scope_sql}
  AND NOT s.archived
  AND (:status='all' OR s.status=:status)
  AND (
      :q=''
      OR s.name ILIKE :pattern
      OR s.description ILIKE :pattern
      OR s.scenario_key ILIKE :pattern
  )
ORDER BY s.domain,s.name,s.id
""",
                tenant=tenant,
                status=status,
                q=q,
                pattern=f"%{q}%",
                **scope_params,
            )
        items = []
        for row in rows:
            volume = row.pop("metric_volume", 0)
            succeeded = row.pop("metric_succeeded", 0)
            handoffs = row.pop("metric_handoffs", 0)
            item = _public_row(row)
            item["metrics"] = _metrics(volume, succeeded, handoffs)
            items.append(item)
        return {"items": items, "total": len(items)}

    async def get(
        self,
        tenant: str,
        key: str,
        *,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        resolved = persisted_scope(tenant, scope)
        scope_sql, scope_params = scope_predicate(resolved, alias="s")
        async with self.engine.connect() as connection:
            row = required(
                await one(
                    connection,
                    f"""
SELECT s.*,v.config AS published_config
FROM service_scenarios s
LEFT JOIN service_scenario_versions v
  ON v.tenant_id=s.tenant_id
 AND v.business_id=s.business_id
 AND v.workspace_id=s.workspace_id
 AND v.scenario_id=s.id
 AND v.version=s.published_version
WHERE s.tenant_id=:tenant
  AND {scope_sql}
  AND s.scenario_key=:key
  AND NOT s.archived
""",
                    tenant=tenant,
                    key=key,
                    **scope_params,
                ),
                "scenario_not_found",
            )
        item = _public_row(row)
        item["has_unpublished_changes"] = (
            row["published_version"] is None or row.get("published_config") != row["draft"]
        )
        return item

    async def create(
        self,
        tenant: str,
        actor: str,
        body: Any,
        *,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        resolved = persisted_scope(tenant, scope)
        _, scope_params = scope_predicate(resolved, alias="s")
        config = self._config(body.config)
        self._reject_pack_metadata_injection(config)
        async with self.engine.begin() as connection:
            row = await one(
                connection,
                """
INSERT INTO service_scenarios(
    tenant_id,business_id,workspace_id,scenario_key,name,description,domain,
    template,status,draft,draft_revision,created_by,updated_by
) VALUES(
    :tenant,:scope_business,:scope_workspace,:key,:name,:description,:domain,
    :template,'draft',CAST(:config AS jsonb),1,:actor,:actor
)
ON CONFLICT(tenant_id,business_id,workspace_id,scenario_key) DO NOTHING
RETURNING *
""",
                tenant=tenant,
                key=body.key,
                name=config.name,
                description=config.description,
                domain=config.domain,
                template=config.template,
                config=config.model_dump_json(),
                actor=actor,
                **scope_params,
            )
            if row is None:
                raise DomainError("scenario_key_conflict", 409)
            await audit(
                connection,
                tenant,
                actor,
                "service_scenario.created",
                row["id"],
                key=body.key,
                revision=row["draft_revision"],
            )
        return _public_row(row)

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
        scope_sql, scope_params = scope_predicate(resolved, alias="s")
        config = self._config(body.config)
        async with self.engine.begin() as connection:
            current = required(
                await one(
                    connection,
                    f"""
SELECT s.* FROM service_scenarios s
WHERE s.tenant_id=:tenant AND {scope_sql} AND s.scenario_key=:key
  AND NOT s.archived
FOR UPDATE
""",
                    tenant=tenant,
                    key=key,
                    **scope_params,
                ),
                "scenario_not_found",
            )
            if current["draft_revision"] != body.revision:
                raise DomainError("scenario_revision_conflict", 409)
            self._preserve_pack_metadata(self._row_config(current), config)
            row = await one(
                connection,
                f"""
UPDATE service_scenarios s
SET name=:name,description=:description,domain=:domain,template=:template,
    draft=CAST(:config AS jsonb),draft_revision=draft_revision+1,
    updated_by=:actor,updated_at=now()
WHERE s.id=:id AND s.tenant_id=:tenant AND {scope_sql}
RETURNING s.*
""",
                id=current["id"],
                tenant=tenant,
                name=config.name,
                description=config.description,
                domain=config.domain,
                template=config.template,
                config=config.model_dump_json(),
                actor=actor,
                **scope_params,
            )
            await audit(
                connection,
                tenant,
                actor,
                "service_scenario.updated",
                current["id"],
                key=key,
                revision=row["draft_revision"],
            )
        return _public_row(row)

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
            raise DomainError("scenario_status_invalid", 422)
        resolved = persisted_scope(tenant, scope)
        scope_sql, scope_params = scope_predicate(resolved, alias="s")
        async with self.engine.begin() as connection:
            row = await one(
                connection,
                f"""
UPDATE service_scenarios s
SET status=:status,draft_revision=draft_revision+1,
    updated_by=:actor,updated_at=now()
WHERE s.tenant_id=:tenant AND {scope_sql} AND s.scenario_key=:key
  AND s.draft_revision=:revision AND NOT s.archived
RETURNING s.*
""",
                tenant=tenant,
                status=status,
                actor=actor,
                key=key,
                revision=revision,
                **scope_params,
            )
            if row is None:
                raise DomainError("scenario_missing_or_revision_conflict", 409)
            await audit(
                connection,
                tenant,
                actor,
                "service_scenario.status_changed",
                row["id"],
                key=key,
                status=status,
                revision=row["draft_revision"],
            )
        return _public_row(row)

    async def _resolve_agent_handlers(
        self,
        connection: Any,
        tenant: str,
        scope: BusinessScope,
        config: ScenarioConfig,
    ) -> ScenarioConfig:
        scope_sql, scope_params = scope_predicate(scope, alias="a")
        for handler in config.handlers:
            if handler.type != "agent":
                continue
            if handler.agent_id is None:
                raise DomainError("scenario_agent_required", 422)
            snapshot = await self.agents.snapshot(
                tenant,
                handler.agent_id,
                connection,
                handler.agent_version,
            )
            agent = required(
                await one(
                    connection,
                    f"""
SELECT a.name FROM agents a
WHERE a.id=:id AND a.tenant_id=:tenant AND {scope_sql}
  AND NOT a.archived
""",
                    id=handler.agent_id,
                    tenant=tenant,
                    **scope_params,
                ),
                "scenario_agent_not_found",
            )
            # Publication pins the exact Agent version; a later Agent release
            # never changes an already-published scene implicitly.
            handler.agent_version = int(snapshot["version"])
            handler.agent_name = agent["name"]
        return config

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
        scope_sql, scope_params = scope_predicate(resolved, alias="s")
        async with self.engine.begin() as connection:
            current = required(
                await one(
                    connection,
                    f"""
SELECT s.* FROM service_scenarios s
WHERE s.tenant_id=:tenant AND {scope_sql} AND s.scenario_key=:key
  AND NOT s.archived
FOR UPDATE
""",
                    tenant=tenant,
                    key=key,
                    **scope_params,
                ),
                "scenario_not_found",
            )
            if current["draft_revision"] != revision:
                raise DomainError("scenario_revision_conflict", 409)
            industry_pack = self._row_config(current).config.get("industry_pack")
            if (
                isinstance(industry_pack, dict)
                and str(industry_pack.get("maturity", "")).casefold() == "alpha"
            ):
                raise DomainError("scenario_alpha_publish_forbidden", 409)
            config = await self._resolve_agent_handlers(
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
FROM service_scenario_versions
WHERE tenant_id=:tenant AND business_id=:scope_business
  AND workspace_id=:scope_workspace AND scenario_id=:scenario
""",
                    tenant=tenant,
                    scenario=current["id"],
                    **scope_params,
                )
            )["version"]
            await execute(
                connection,
                """
INSERT INTO service_scenario_versions(
    tenant_id,business_id,workspace_id,scenario_id,version,config,created_by
) VALUES(
    :tenant,:scope_business,:scope_workspace,:scenario,:version,
    CAST(:config AS jsonb),:actor
)
""",
                tenant=tenant,
                scenario=current["id"],
                version=version,
                config=config.model_dump_json(),
                actor=actor,
                **scope_params,
            )
            row = await one(
                connection,
                f"""
UPDATE service_scenarios s
SET draft=CAST(:config AS jsonb),name=:name,description=:description,
    domain=:domain,template=:template,status='published',
    published_version=:version,draft_revision=draft_revision+1,
    updated_by=:actor,updated_at=now()
WHERE s.id=:id AND s.tenant_id=:tenant AND {scope_sql}
RETURNING s.*
""",
                id=current["id"],
                tenant=tenant,
                config=config.model_dump_json(),
                name=config.name,
                description=config.description,
                domain=config.domain,
                template=config.template,
                version=version,
                actor=actor,
                **scope_params,
            )
            await audit(
                connection,
                tenant,
                actor,
                "service_scenario.published",
                current["id"],
                key=key,
                version=version,
                revision=row["draft_revision"],
            )
        result = _public_row(row)
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
        scope_sql, scope_params = scope_predicate(resolved, alias="s")
        async with self.engine.connect() as connection:
            scenario = required(
                await one(
                    connection,
                    f"""
SELECT s.id,s.published_version FROM service_scenarios s
WHERE s.tenant_id=:tenant AND {scope_sql} AND s.scenario_key=:key
  AND NOT s.archived
""",
                    tenant=tenant,
                    key=key,
                    **scope_params,
                ),
                "scenario_not_found",
            )
            rows = await many(
                connection,
                """
SELECT id,version,config,source_version,created_by,created_at
FROM service_scenario_versions
WHERE tenant_id=:tenant AND business_id=:scope_business
  AND workspace_id=:scope_workspace AND scenario_id=:scenario
ORDER BY version DESC
""",
                tenant=tenant,
                scenario=scenario["id"],
                **scope_params,
            )
        for row in rows:
            row["published"] = row["version"] == scenario["published_version"]
        return {"items": rows, "published_version": scenario["published_version"]}

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
        scope_sql, scope_params = scope_predicate(resolved, alias="s")
        async with self.engine.begin() as connection:
            current = required(
                await one(
                    connection,
                    f"""
SELECT s.* FROM service_scenarios s
WHERE s.tenant_id=:tenant AND {scope_sql} AND s.scenario_key=:key
  AND NOT s.archived
FOR UPDATE
""",
                    tenant=tenant,
                    key=key,
                    **scope_params,
                ),
                "scenario_not_found",
            )
            if current["draft_revision"] != revision:
                raise DomainError("scenario_revision_conflict", 409)
            target = required(
                await one(
                    connection,
                    """
SELECT version,config FROM service_scenario_versions
WHERE tenant_id=:tenant AND business_id=:scope_business
  AND workspace_id=:scope_workspace AND scenario_id=:scenario
  AND version=:version
""",
                    tenant=tenant,
                    scenario=current["id"],
                    version=version,
                    **scope_params,
                ),
                "scenario_version_not_found",
            )
            config = self._config(target["config"])
            row = await one(
                connection,
                f"""
UPDATE service_scenarios s
SET draft=CAST(:config AS jsonb),name=:name,description=:description,
    domain=:domain,template=:template,status='published',
    published_version=:version,draft_revision=draft_revision+1,
    updated_by=:actor,updated_at=now()
WHERE s.id=:id AND s.tenant_id=:tenant AND {scope_sql}
RETURNING s.*
""",
                id=current["id"],
                tenant=tenant,
                config=config.model_dump_json(),
                name=config.name,
                description=config.description,
                domain=config.domain,
                template=config.template,
                version=version,
                actor=actor,
                **scope_params,
            )
            await audit(
                connection,
                tenant,
                actor,
                "service_scenario.rolled_back",
                current["id"],
                key=key,
                version=version,
                revision=row["draft_revision"],
            )
        result = _public_row(row)
        result["rollback_version"] = version
        return result

    async def _trace(
        self,
        connection: Any,
        tenant: str,
        scope: BusinessScope,
        *,
        scenario_id: UUID | None,
        scenario_key: str,
        scenario_version: int | None,
        entry: str,
        message: str,
        trace_data: dict[str, Any],
        actor: str,
        simulation: bool = True,
        conversation_id: UUID | None = None,
    ) -> UUID:
        trace_id = uuid4()
        _, scope_params = scope_predicate(scope)
        result = trace_data.get("result") or {}
        handler = trace_data.get("handler") or {}
        await execute(
            connection,
            """
INSERT INTO service_scenario_traces(
    id,tenant_id,business_id,workspace_id,conversation_id,scenario_id,scenario_key,
    scenario_version,simulation,entry,message_length,message_excerpt,
    object_ref,facts,decisions,handler_type,outcome,reason_code,
    result_summary,trace,created_by
) VALUES(
    :id,:tenant,:scope_business,:scope_workspace,:conversation,:scenario,:key,
    :version,:simulation,:entry,:length,:excerpt,
    CAST(:object_ref AS jsonb),CAST(:facts AS jsonb),CAST(:decisions AS jsonb),
    :handler_type,:outcome,:reason,:summary,CAST(:trace AS jsonb),:actor
)
""",
            id=trace_id,
            tenant=tenant,
            conversation=conversation_id,
            scenario=scenario_id,
            key=scenario_key,
            version=scenario_version,
            simulation=simulation,
            entry=entry,
            length=len(message),
            excerpt=message[:240],
            object_ref=json.dumps(trace_data.get("object_ref") or {}),
            facts=json.dumps(trace_data.get("facts") or []),
            decisions=json.dumps(trace_data.get("decisions") or []),
            handler_type=handler.get("type"),
            outcome=_trace_outcome(result.get("status")),
            reason=result.get("reason_code") or trace_data.get("reason_code") or "simulated",
            summary=str(result.get("content") or "")[:1000],
            trace=json.dumps(trace_data),
            actor=actor,
            **scope_params,
        )
        return trace_id

    async def simulate(
        self,
        tenant: str,
        actor: str,
        key: str | None,
        body: SimulationRequest,
        *,
        scope: BusinessScope | None = None,
        persist: bool = True,
        version: int | None = None,
        trace_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if version is not None and key is None:
            raise DomainError("scenario_key_required_for_version", 422)
        resolved = persisted_scope(tenant, scope)
        scope_sql, scope_params = scope_predicate(resolved, alias="s")
        async with self.engine.connect() as connection:
            rows = await many(
                connection,
                f"""
SELECT s.*,v.config AS published_config
FROM service_scenarios s
LEFT JOIN service_scenario_versions v
  ON v.tenant_id=s.tenant_id
 AND v.business_id=s.business_id
 AND v.workspace_id=s.workspace_id
 AND v.scenario_id=s.id
 AND v.version=COALESCE(CAST(:version AS integer),s.published_version)
WHERE s.tenant_id=:tenant AND {scope_sql} AND NOT s.archived
  AND (CAST(:key AS text) IS NULL OR s.scenario_key=CAST(:key AS text))
  AND (CAST(:key AS text) IS NOT NULL OR s.status='published')
ORDER BY s.domain,s.name,s.id
""",
                tenant=tenant,
                key=key,
                version=version,
                **scope_params,
            )
        if not rows:
            raise DomainError("scenario_not_found", 404)

        target = rows[0]
        if version is not None and target.get("published_config") is None:
            raise DomainError("scenario_version_not_found", 404)
        if key is None:
            target = self._best_scenario(rows, body.message)
        config = ScenarioConfig.model_validate(target.get("published_config") or target["draft"])
        all_scenarios = (
            [
                {
                    "key": row["scenario_key"],
                    "name": row["name"],
                    "config": row.get("published_config") or row["draft"],
                }
                for row in rows
            ]
            if key is None
            else None
        )
        # Facts are resolved outside the transaction: a slow upstream must never
        # hold a pooled connection or a row lock open.
        resolution = await self._resolve_object(tenant, config, body, resolved)
        if resolution is not None and resolution.object is not None:
            body = body.model_copy(update={"object": resolution.object})
        trace = simulate_config(
            target["scenario_key"],
            target["name"],
            target["published_version"],
            target["status"],
            config,
            body,
            all_scenarios=all_scenarios,
        )
        trace_data = trace.model_dump(mode="json")
        self._record_provider(trace_data, resolution)
        if trace_context:
            trace_data["application"] = trace_context
        conversation_id = body.conversation_id
        async with self.engine.begin() as connection:
            if conversation_id is not None:
                # A trace may only be bound to a conversation the caller can
                # already see; the scope check keeps tenants and workspaces apart.
                conversation_scope_sql, conversation_params = scope_predicate(resolved)
                required(
                    await one(
                        connection,
                        f"""SELECT id FROM runtime_conversations
                        WHERE id=:cid AND tenant_id=:tenant
                          AND {conversation_scope_sql}""",
                        cid=conversation_id,
                        tenant=tenant,
                        **conversation_params,
                    ),
                    "conversation_not_found",
                )
                trace_data["conversation_id"] = str(conversation_id)
            trace_id = None
            if persist:
                trace_id = await self._trace(
                    connection,
                    tenant,
                    resolved,
                    scenario_id=target["id"],
                    scenario_key=target["scenario_key"],
                    scenario_version=version or target["published_version"],
                    entry=body.entry,
                    message=body.message,
                    trace_data=trace_data,
                    actor=actor,
                    conversation_id=conversation_id,
                )
        trace_data["trace_id"] = str(trace_id) if trace_id else None
        return trace_data

    async def _resolve_object(
        self,
        tenant: str,
        config: ScenarioConfig,
        body: SimulationRequest,
        scope: Any,
    ) -> ObjectResolution | None:
        if self.bridge is None:
            return None
        return await self.bridge.resolve_object(tenant, config, body, scope=scope)

    @staticmethod
    def _record_provider(
        trace_data: dict[str, Any],
        resolution: ObjectResolution | None,
    ) -> None:
        """Attach provider evidence and apply the declared failure policy."""

        if resolution is None:
            return
        outcome = resolution.outcome
        if outcome is None and not resolution.candidates:
            return
        trace_data["provider"] = {
            "object_source": resolution.source,
            "candidates": resolution.candidates,
            "execution": outcome.public() if outcome is not None else None,
            "error_policy": resolution.on_error,
        }
        if outcome is None or outcome.ok:
            return
        # A 404/403 is a business fact about the object, not a broken provider,
        # so the failure policy only governs genuine transport or upstream
        # errors. The deterministic path already reports the missing object.
        if outcome.missing or outcome.denied or resolution.on_error != "fail":
            return
        content = "业务数据暂时无法读取，请稍后重试或转人工。"
        trace_data["result"] = {
            **(trace_data.get("result") or {}),
            "status": "failed",
            "reason": "provider_unavailable",
            "reason_code": "provider_unavailable",
            "content": content,
        }
        for step in trace_data.get("steps") or []:
            if step.get("step") == "result":
                step.update(
                    {
                        "status": "failed",
                        "reason": "provider_unavailable",
                        "content": content,
                    }
                )

    @staticmethod
    def _best_scenario(rows: list[dict[str, Any]], message: str) -> dict[str, Any]:
        normalized = message.casefold()
        best = rows[0]
        best_score = -1
        for row in rows:
            config = ScenarioConfig.model_validate(row.get("published_config") or row["draft"])
            if any(term.casefold() in normalized for term in config.matching.negative_keywords):
                continue
            score = sum(
                max(1, len(term))
                for term in [*config.matching.keywords, *config.matching.intents]
                if term.casefold() in normalized
            )
            if score > best_score:
                best, best_score = row, score
        return best

    async def traces(
        self,
        tenant: str,
        key: str,
        *,
        limit: int = 50,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        if limit < 1 or limit > MAX_TRACE_LIMIT:
            raise DomainError("scenario_trace_limit_invalid", 422)
        resolved = persisted_scope(tenant, scope)
        scope_sql, scope_params = scope_predicate(resolved, alias="s")
        async with self.engine.connect() as connection:
            scenario = required(
                await one(
                    connection,
                    f"""
SELECT s.id FROM service_scenarios s
WHERE s.tenant_id=:tenant AND {scope_sql} AND s.scenario_key=:key
  AND NOT s.archived
""",
                    tenant=tenant,
                    key=key,
                    **scope_params,
                ),
                "scenario_not_found",
            )
            items = await many(
                connection,
                """
SELECT id,conversation_id,scenario_key,scenario_version,simulation,entry,message_length,
       message_excerpt,object_ref,facts,decisions,handler_type,outcome,
       reason_code,result_summary,trace,created_by,created_at
FROM service_scenario_traces
WHERE tenant_id=:tenant AND business_id=:scope_business
  AND workspace_id=:scope_workspace AND scenario_id=:scenario
ORDER BY created_at DESC,id DESC
LIMIT :limit
""",
                tenant=tenant,
                scenario=scenario["id"],
                limit=limit,
                **scope_params,
            )
        return {"items": items}

    async def overview(
        self,
        tenant: str,
        *,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        resolved = persisted_scope(tenant, scope)
        scope_sql, scope_params = scope_predicate(resolved, alias="s")
        since = datetime.now(UTC) - timedelta(days=7)
        async with self.engine.connect() as connection:
            statuses = await many(
                connection,
                f"""
SELECT s.status,count(*)::int AS count
FROM service_scenarios s
WHERE s.tenant_id=:tenant AND {scope_sql} AND NOT s.archived
GROUP BY s.status
""",
                tenant=tenant,
                **scope_params,
            )
            usage = await one(
                connection,
                """
SELECT count(*)::int AS volume,
       count(*) FILTER (WHERE outcome='succeeded')::int AS auto_resolved,
       count(*) FILTER (WHERE handler_type='human')::int AS handoffs
FROM service_scenario_traces
WHERE tenant_id=:tenant AND business_id=:scope_business
  AND workspace_id=:scope_workspace AND NOT simulation
  AND created_at>=:since
""",
                tenant=tenant,
                since=since,
                **scope_params,
            )
            handlers = await many(
                connection,
                """
SELECT handler_type AS key,count(*)::int AS count
FROM service_scenario_traces
WHERE tenant_id=:tenant AND business_id=:scope_business
  AND workspace_id=:scope_workspace AND NOT simulation
  AND created_at>=:since
GROUP BY handler_type
ORDER BY count DESC,handler_type
""",
                tenant=tenant,
                since=since,
                **scope_params,
            )
        by_status = {item["status"]: item["count"] for item in statuses}
        volume = usage["volume"]
        return {
            "scenarios": sum(by_status.values()),
            "by_status": {
                "draft": by_status.get("draft", 0),
                "review": by_status.get("review", 0),
                "published": by_status.get("published", 0),
                "offline": by_status.get("offline", 0),
            },
            "window_days": 7,
            "metrics": _metrics(
                volume,
                usage["auto_resolved"],
                usage["handoffs"],
            ),
            "by_handler": handlers,
        }

    async def agent_references(
        self,
        tenant: str,
        agent_id: UUID,
        *,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        resolved = persisted_scope(tenant, scope)
        scope_sql, scope_params = scope_predicate(resolved, alias="s")
        async with self.engine.connect() as connection:
            rows = await many(
                connection,
                f"""
WITH metrics AS (
    SELECT scenario_id,
           count(*)::int AS volume,
           count(*) FILTER (WHERE outcome='succeeded')::int AS succeeded,
           count(*) FILTER (WHERE handler_type='human')::int AS handoffs
    FROM service_scenario_traces
    WHERE tenant_id=:tenant
      AND business_id=:scope_business
      AND workspace_id=:scope_workspace
      AND NOT simulation
      AND created_at>=now()-interval '7 days'
    GROUP BY scenario_id
)
SELECT s.*,v.config AS published_config,
       COALESCE(m.volume,0)::int AS metric_volume,
       COALESCE(m.succeeded,0)::int AS metric_succeeded,
       COALESCE(m.handoffs,0)::int AS metric_handoffs
FROM service_scenarios s
LEFT JOIN service_scenario_versions v
  ON v.tenant_id=s.tenant_id
 AND v.business_id=s.business_id
 AND v.workspace_id=s.workspace_id
 AND v.scenario_id=s.id
 AND v.version=s.published_version
LEFT JOIN metrics m ON m.scenario_id=s.id
WHERE s.tenant_id=:tenant AND {scope_sql} AND NOT s.archived
ORDER BY s.domain,s.name,s.id
""",
                tenant=tenant,
                **scope_params,
            )
        items: list[dict[str, Any]] = []
        for row in rows:
            raw = row.get("published_config") or row["draft"]
            config = ScenarioConfig.model_validate(raw)
            for handler in config.handlers:
                if handler.type != "agent" or handler.agent_id != agent_id:
                    continue
                condition = handler.when.model_dump(mode="json")
                items.append(
                    {
                        "key": row["scenario_key"],
                        "name": row["name"],
                        "domain": row["domain"],
                        "status": row["status"],
                        "version": row["published_version"],
                        "handler_key": handler.key,
                        "handler_label": handler.label,
                        "binding": _condition_label(condition),
                        "agent_version": handler.agent_version,
                        "configured_version": handler.agent_version,
                        "metrics": _metrics(
                            row.get("metric_volume", 0),
                            row.get("metric_succeeded", 0),
                            row.get("metric_handoffs", 0),
                        ),
                        "volume": row.get("metric_volume", 0),
                    }
                )
        return {"items": items}

    async def seed_defaults(
        self,
        tenant: str,
        actor: str = "seed-service-scenarios",
        *,
        scope: BusinessScope | None = None,
    ) -> dict[str, int]:
        """Idempotently install the six review scenes without overwriting edits."""

        from .seed import default_scenarios

        resolved = persisted_scope(tenant, scope)
        inserted = 0
        versions = 0
        async with self.engine.begin() as connection:
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
            for spec in default_scenarios(agent=agent):
                config = self._config(spec["config"])
                row = await one(
                    connection,
                    """
INSERT INTO service_scenarios(
    tenant_id,business_id,workspace_id,scenario_key,name,description,domain,
    template,status,draft,draft_revision,published_version,created_by,updated_by
) VALUES(
    :tenant,:business,:workspace,:key,:name,:description,:domain,:template,
    :status,CAST(:config AS jsonb),1,:published_version,:actor,:actor
)
ON CONFLICT(tenant_id,business_id,workspace_id,scenario_key) DO NOTHING
RETURNING id
""",
                    tenant=tenant,
                    business=resolved.business_id,
                    workspace=resolved.workspace_id,
                    key=spec["key"],
                    name=config.name,
                    description=config.description,
                    domain=config.domain,
                    template=config.template,
                    status=spec["status"],
                    config=config.model_dump_json(),
                    published_version=spec.get("published_version"),
                    actor=actor,
                )
                if row is None:
                    continue
                inserted += 1
                for version in range(1, (spec.get("published_version") or 0) + 1):
                    await execute(
                        connection,
                        """
INSERT INTO service_scenario_versions(
    tenant_id,business_id,workspace_id,scenario_id,version,config,created_by
) VALUES(
    :tenant,:business,:workspace,:scenario,:version,
    CAST(:config AS jsonb),:actor
)
""",
                        tenant=tenant,
                        business=resolved.business_id,
                        workspace=resolved.workspace_id,
                        scenario=row["id"],
                        version=version,
                        config=config.model_dump_json(),
                        actor=actor,
                    )
                    versions += 1
                await audit(
                    connection,
                    tenant,
                    actor,
                    "service_scenario.seeded",
                    row["id"],
                    key=spec["key"],
                    batch="service-scenario-v1",
                )
        return {"scenarios": inserted, "versions": versions}


__all__ = ["MAX_TRACE_LIMIT", "ScenarioService"]
