"""Install and upgrade built-in industry packs as tenant-owned drafts."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any
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

from ..providers.models import ProviderKind, ProviderRequirement
from ..providers.service import ServiceProviderRegistry
from ..scenarios.models import HandlerType, ScenarioConfig
from ..service_apps.models import ServiceApplicationConfig
from .compiler import (
    IndustryPackCompileError,
    IndustryPackCompiler,
    stable_digest,
)
from .creator import build_creator_pack
from .gaming import build_gaming_pack
from .merge import MergeResult, three_way_merge
from .mobility import build_mobility_pack
from .models import IndustryPackManifest
from .runtime_models import (
    IndustryPackCatalog,
    IndustryPackDetail,
    IndustryPackInstallation,
    IndustryPackInstallationPage,
    IndustryPackInstallInput,
    IndustryPackInstallResult,
    IndustryPackSummary,
    IndustryPackUpgradeInput,
    IndustryPackUpgradePreview,
    IndustryPackUpgradePreviewRequest,
    IndustryPackUpgradeResult,
    MergeConflictView,
    ScenarioUpgradePreview,
)
from .shopping import build_shopping_pack


def _default_packs() -> dict[str, IndustryPackManifest]:
    packs = (
        build_shopping_pack(),
        build_gaming_pack(),
        build_creator_pack(),
        build_mobility_pack(),
    )
    return {pack.pack_key: pack for pack in packs}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _summary(compiler: IndustryPackCompiler) -> IndustryPackSummary:
    manifest = compiler.manifest
    return IndustryPackSummary(
        pack_key=manifest.pack_key,
        name=manifest.name,
        description=manifest.description,
        pack_version=manifest.pack_version,
        maturity=manifest.maturity.value,
        digest=compiler.digest,
        object_count=len(manifest.object_templates),
        scenario_count=len(manifest.scenario_templates),
        application_key=(
            manifest.application_blueprint.application_key or f"{manifest.pack_key}-service"
            if manifest.application_blueprint is not None
            else None
        ),
    )


def _installation(row: dict[str, Any]) -> IndustryPackInstallation:
    return IndustryPackInstallation.model_validate(
        {
            key: row.get(key)
            for key in (
                "id",
                "pack_key",
                "pack_version",
                "pack_digest",
                "maturity",
                "application_key",
                "status",
                "scenario_template_versions",
                "scenario_template_digests",
                "installed_scenarios",
                "revision",
                "installed_by",
                "created_at",
                "updated_at",
            )
        }
    )


def _conflict_view(conflict: Any) -> MergeConflictView:
    if isinstance(conflict, dict):
        return MergeConflictView(
            path=str(conflict.get("path", "")),
            base=conflict.get("base"),
            local=conflict.get("local"),
            incoming=conflict.get("incoming"),
        )
    return MergeConflictView(
        path=str(getattr(conflict, "path", "")),
        base=getattr(conflict, "base", None),
        local=getattr(conflict, "local", None),
        incoming=getattr(conflict, "incoming", None),
    )


_MISSING = object()


def _same(left: Any, right: Any) -> bool:
    return left == right


def _merge_application_value(
    base: Any,
    local: Any,
    incoming: Any,
    *,
    path: str,
    conflicts: list[MergeConflictView],
    auto_merged_fields: list[str],
    kept_local_fields: list[str],
    incoming_fields: list[str],
) -> Any:
    if local is _MISSING and incoming is _MISSING:
        return _MISSING
    if _same(local, incoming):
        return deepcopy(local)
    if _same(base, local):
        if incoming is _MISSING:
            return _MISSING
        incoming_fields.append(path)
        return deepcopy(incoming)
    if _same(base, incoming):
        if local is _MISSING:
            return _MISSING
        kept_local_fields.append(path)
        return deepcopy(local)
    if isinstance(base, dict) and isinstance(local, dict) and isinstance(incoming, dict):
        merged: dict[str, Any] = {}
        for key in dict.fromkeys([*base, *local, *incoming]):
            child = f"{path}.{key}" if path else key
            value = _merge_application_value(
                base.get(key, _MISSING),
                local.get(key, _MISSING),
                incoming.get(key, _MISSING),
                path=child,
                conflicts=conflicts,
                auto_merged_fields=auto_merged_fields,
                kept_local_fields=kept_local_fields,
                incoming_fields=incoming_fields,
            )
            if value is not _MISSING:
                merged[key] = value
        return merged
    if isinstance(base, list) and isinstance(local, list) and isinstance(incoming, list):
        keyed = any(isinstance(item, dict) and "key" in item for item in [*base, *local, *incoming])
        if keyed:

            def item_key(item: Any) -> str:
                if isinstance(item, dict) and isinstance(item.get("key"), str):
                    return item["key"]
                return stable_digest(item)

            base_by_key = {item_key(item): item for item in base}
            local_by_key = {item_key(item): item for item in local}
            incoming_by_key = {item_key(item): item for item in incoming}
            order = list(
                dict.fromkeys(
                    [
                        *base_by_key,
                        *local_by_key,
                        *incoming_by_key,
                    ]
                )
            )
            merged_items: list[Any] = []
            for item_key_value in order:
                child = f"{path}[{item_key_value}]"
                value = _merge_application_value(
                    base_by_key.get(item_key_value, _MISSING),
                    local_by_key.get(item_key_value, _MISSING),
                    incoming_by_key.get(item_key_value, _MISSING),
                    path=child,
                    conflicts=conflicts,
                    auto_merged_fields=auto_merged_fields,
                    kept_local_fields=kept_local_fields,
                    incoming_fields=incoming_fields,
                )
                if value is not _MISSING:
                    merged_items.append(value)
            return merged_items
        if _same(base, local):
            incoming_fields.append(path)
            return deepcopy(incoming)
        if _same(base, incoming):
            kept_local_fields.append(path)
            return deepcopy(local)
    conflicts.append(
        MergeConflictView(
            path=path,
            base=None if base is _MISSING else base,
            local=None if local is _MISSING else local,
            incoming=None if incoming is _MISSING else incoming,
        )
    )
    return None if local is _MISSING else deepcopy(local)


def _merge_application_config(
    base: ServiceApplicationConfig,
    local: ServiceApplicationConfig,
    incoming: ServiceApplicationConfig,
) -> tuple[ServiceApplicationConfig, list[MergeConflictView]]:
    conflicts: list[MergeConflictView] = []
    merged = _merge_application_value(
        base.model_dump(mode="json"),
        local.model_dump(mode="json"),
        incoming.model_dump(mode="json"),
        path="",
        conflicts=conflicts,
        auto_merged_fields=[],
        kept_local_fields=[],
        incoming_fields=[],
    )
    try:
        return ServiceApplicationConfig.model_validate(merged), conflicts
    except ValidationError:
        conflicts.append(
            MergeConflictView(
                path="application",
                base=base.model_dump(mode="json"),
                local=local.model_dump(mode="json"),
                incoming=incoming.model_dump(mode="json"),
            )
        )
        return local, conflicts


class IndustryPackService:
    """Installable pack catalog backed by the built-in compiler registry."""

    def __init__(
        self,
        engine: object,
        providers: ServiceProviderRegistry,
        *,
        packs: dict[str, IndustryPackManifest] | None = None,
    ) -> None:
        self.engine = engine
        self.providers = providers
        self.packs = packs or _default_packs()

    def _compiler(self, pack_key: str) -> IndustryPackCompiler:
        manifest = self.packs.get(pack_key)
        if manifest is None:
            raise DomainError("industry_pack_not_found", 404)
        return IndustryPackCompiler(manifest)

    async def list_packs(
        self,
        tenant: str,
        *,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        resolved = persisted_scope(tenant, scope)
        scope_sql, scope_params = scope_predicate(resolved, alias="i")
        async with self.engine.connect() as connection:
            installations = await many(
                connection,
                f"""
SELECT i.pack_key,count(*)::int AS installation_count
FROM industry_pack_installations i
WHERE i.tenant_id=:tenant AND {scope_sql}
GROUP BY i.pack_key
""",
                tenant=tenant,
                **scope_params,
            )
        counts = {row["pack_key"]: row["installation_count"] for row in installations}
        items = []
        for pack_key in sorted(self.packs):
            item = _summary(IndustryPackCompiler(self.packs[pack_key])).model_dump(mode="json")
            item["installation_count"] = counts.get(pack_key, 0)
            items.append(item)
        return IndustryPackCatalog(
            items=[IndustryPackSummary.model_validate(item) for item in items],
            total=len(items),
        ).model_dump(mode="json")

    async def get_pack(
        self,
        tenant: str,
        pack_key: str,
        *,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        compiler = self._compiler(pack_key)
        resolved = persisted_scope(tenant, scope)
        scope_sql, scope_params = scope_predicate(resolved, alias="i")
        async with self.engine.connect() as connection:
            rows = await many(
                connection,
                f"""
SELECT i.* FROM industry_pack_installations i
WHERE i.tenant_id=:tenant AND {scope_sql} AND i.pack_key=:pack_key
ORDER BY i.created_at DESC,i.id
""",
                tenant=tenant,
                pack_key=pack_key,
                **scope_params,
            )
        summary = _summary(compiler)
        compiled_application: dict[str, Any] | None = None
        if compiler.manifest.application_blueprint is not None:
            compiled_application = compiler.compile_application_dict()
        return IndustryPackDetail(
            **summary.model_dump(mode="json"),
            manifest=compiler.manifest.model_dump(mode="json"),
            compiled_application=compiled_application,
            installations=[_installation(row).model_dump(mode="json") for row in rows],
        ).model_dump(mode="json")

    async def list_installations(
        self,
        tenant: str,
        *,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        resolved = persisted_scope(tenant, scope)
        scope_sql, scope_params = scope_predicate(resolved, alias="i")
        async with self.engine.connect() as connection:
            rows = await many(
                connection,
                f"""
SELECT i.* FROM industry_pack_installations i
WHERE i.tenant_id=:tenant AND {scope_sql}
ORDER BY i.updated_at DESC,i.id
""",
                tenant=tenant,
                **scope_params,
            )
        return IndustryPackInstallationPage(
            items=[_installation(row) for row in rows],
            total=len(rows),
        ).model_dump(mode="json")

    async def install(
        self,
        tenant: str,
        actor: str,
        pack_key: str,
        body: IndustryPackInstallInput,
        *,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        resolved = persisted_scope(tenant, scope)
        compiler = self._compiler(pack_key)
        manifest = compiler.manifest
        if body.pack_version is not None and body.pack_version != manifest.pack_version:
            raise DomainError("industry_pack_version_not_found", 404)
        compiled = compiler.compile_application()
        application_key = body.application_key or compiled.application_key
        blueprint_keys = {item.key for item in compiled.application.scenarios}
        target_templates = [
            template
            for template in manifest.scenario_templates
            if body.install_scenarios or template.template_key in blueprint_keys
        ]
        target_keys = {template.template_key for template in target_templates}

        scope_sql, scope_params = scope_predicate(resolved, alias="i")
        async with self.engine.begin() as connection:
            existing = await one(
                connection,
                f"""
SELECT i.* FROM industry_pack_installations i
WHERE i.tenant_id=:tenant AND {scope_sql}
  AND i.pack_key=:pack_key AND i.application_key=:application_key
FOR UPDATE
""",
                tenant=tenant,
                pack_key=pack_key,
                application_key=application_key,
                **scope_params,
            )
            if existing is not None:
                if existing["pack_digest"] == compiler.digest:
                    return IndustryPackInstallResult(
                        created=False,
                        installation=_installation(existing),
                    ).model_dump(mode="json")
                raise DomainError("industry_pack_installation_conflict", 409)

            installed_scenarios: dict[str, str] = {}
            base_scenarios: dict[str, Any] = {}
            for template in target_templates:
                config = compiler.compile_scenario(template.template_key)
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
                    key=template.template_key,
                    name=config.name,
                    description=config.description,
                    domain=config.domain,
                    template=config.template.value,
                    config=config.model_dump_json(),
                    actor=actor,
                    **scope_params,
                )
                if row is None:
                    row = required(
                        await one(
                            connection,
                            """
SELECT * FROM service_scenarios
WHERE tenant_id=:tenant AND business_id=:scope_business
  AND workspace_id=:scope_workspace AND scenario_key=:key
  AND NOT archived
""",
                            tenant=tenant,
                            key=template.template_key,
                            **scope_params,
                        ),
                        "industry_pack_scenario_collision",
                    )
                    existing_config = ScenarioConfig.model_validate(row["draft"])
                    source = existing_config.config.get("industry_pack")
                    if not (
                        isinstance(source, dict)
                        and source.get("pack_key") == pack_key
                        and source.get("template_key") == template.template_key
                    ):
                        raise DomainError("industry_pack_scenario_collision", 409)
                installed_scenarios[template.template_key] = template.template_key
                base_scenarios[template.template_key] = config.model_dump(mode="json")

            application_config = compiled.application.model_copy(
                update={
                    "scenarios": [
                        item for item in compiled.application.scenarios if item.key in target_keys
                    ]
                }
            )
            application_row = await one(
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
                key=application_key,
                name=application_config.name,
                description=application_config.description,
                config=application_config.model_dump_json(),
                actor=actor,
                **scope_params,
            )
            if application_row is None:
                raise DomainError("industry_pack_application_conflict", 409)

            requirements = self._requirements(
                compiler,
                [compiler.compile_scenario(key) for key in sorted(target_keys)],
            )
            await self.providers.ensure_requirements(
                connection,
                tenant,
                actor,
                resolved,
                requirements,
            )

            versions = {
                template.template_key: template.template_version for template in target_templates
            }
            digests = {
                template.template_key: compiler.digest_scenario_template(template)
                for template in target_templates
            }
            source_snapshot = {
                "application_config": application_config.model_dump(mode="json"),
                "scenario_configs": base_scenarios,
            }
            row = await one(
                connection,
                """
INSERT INTO industry_pack_installations(
    tenant_id,business_id,workspace_id,pack_key,pack_version,pack_digest,
    maturity,application_key,status,scenario_template_versions,
    scenario_template_digests,installed_scenarios,source_snapshot,
    revision,installed_by
) VALUES(
    :tenant,:scope_business,:scope_workspace,:pack_key,:pack_version,:pack_digest,
    :maturity,:application_key,'installed',CAST(:versions AS jsonb),
    CAST(:digests AS jsonb),CAST(:scenarios AS jsonb),
    CAST(:snapshot AS jsonb),1,:actor
)
RETURNING *
""",
                tenant=tenant,
                pack_key=pack_key,
                pack_version=manifest.pack_version,
                pack_digest=compiler.digest,
                maturity=manifest.maturity.value,
                application_key=application_key,
                versions=_json(versions),
                digests=_json(digests),
                scenarios=_json(installed_scenarios),
                snapshot=_json(source_snapshot),
                actor=actor,
                **scope_params,
            )
            await audit(
                connection,
                tenant,
                actor,
                "industry_pack.installed",
                row["id"],
                pack_key=pack_key,
                pack_version=manifest.pack_version,
                application_key=application_key,
                scenarios=sorted(installed_scenarios),
            )
        return IndustryPackInstallResult(
            created=True,
            installation=_installation(row),
        ).model_dump(mode="json")

    def _requirements(
        self,
        compiler: IndustryPackCompiler,
        scenarios: list[ScenarioConfig],
    ) -> list[ProviderRequirement]:
        requirements: dict[tuple[str, str], ProviderRequirement] = {}
        object_names = {item.provider_key: item.name for item in compiler.manifest.object_templates}
        for scenario in scenarios:
            if scenario.object is not None and scenario.object.provider:
                key = scenario.object.provider
                requirements[(ProviderKind.OBJECT.value, key)] = ProviderRequirement(
                    key=key,
                    kind=ProviderKind.OBJECT,
                    name=object_names.get(key, "业务数据"),
                    source="industry_pack",
                    source_ref=compiler.manifest.pack_key,
                )
            for handler in scenario.handlers:
                if not handler.enabled:
                    continue
                if handler.tool:
                    requirements[(ProviderKind.TOOL.value, handler.tool)] = ProviderRequirement(
                        key=handler.tool,
                        kind=ProviderKind.TOOL,
                        name=handler.label,
                        source="industry_pack",
                        source_ref=compiler.manifest.pack_key,
                    )
                if handler.type == HandlerType.HUMAN and handler.queue:
                    requirements[(ProviderKind.HUMAN_QUEUE.value, handler.queue)] = (
                        ProviderRequirement(
                            key=handler.queue,
                            kind=ProviderKind.HUMAN_QUEUE,
                            name=handler.label,
                            source="industry_pack",
                            source_ref=compiler.manifest.pack_key,
                        )
                    )
        for capability in (
            compiler.manifest.application_blueprint.capabilities
            if (compiler.manifest.application_blueprint is not None)
            else []
        ):
            if not capability.enabled:
                continue
            if capability.tool:
                requirements[(ProviderKind.TOOL.value, capability.tool)] = ProviderRequirement(
                    key=capability.tool,
                    kind=ProviderKind.TOOL,
                    name=capability.label,
                    source="industry_pack",
                    source_ref=compiler.manifest.pack_key,
                )
            if capability.type.value == "human" and capability.queue:
                requirements[(ProviderKind.HUMAN_QUEUE.value, capability.queue)] = (
                    ProviderRequirement(
                        key=capability.queue,
                        kind=ProviderKind.HUMAN_QUEUE,
                        name=capability.label,
                        source="industry_pack",
                        source_ref=compiler.manifest.pack_key,
                    )
                )
        return list(requirements.values())

    async def _installation_row(
        self,
        connection: Any,
        tenant: str,
        scope: BusinessScope,
        installation_id: UUID,
        *,
        lock: bool = False,
    ) -> dict[str, Any]:
        scope_sql, scope_params = scope_predicate(scope, alias="i")
        return required(
            await one(
                connection,
                f"""
SELECT i.* FROM industry_pack_installations i
WHERE i.tenant_id=:tenant AND {scope_sql} AND i.id=:id
{"FOR UPDATE" if lock else ""}
""",
                tenant=tenant,
                id=str(installation_id),
                **scope_params,
            ),
            "industry_pack_installation_not_found",
        )

    async def preview_upgrade(
        self,
        tenant: str,
        actor: str,
        installation_id: UUID,
        body: IndustryPackUpgradePreviewRequest,
        *,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        resolved = persisted_scope(tenant, scope)
        scenario_scope_sql, scenario_scope_params = scope_predicate(
            resolved,
            alias="s",
        )
        application_scope_sql, application_scope_params = scope_predicate(
            resolved,
            alias="a",
        )
        async with self.engine.connect() as connection:
            installation = await self._installation_row(
                connection,
                tenant,
                resolved,
                installation_id,
            )
        compiler = self._compiler(installation["pack_key"])
        target_version = body.target_version or compiler.manifest.pack_version
        if target_version == installation["pack_version"]:
            raise DomainError("industry_pack_upgrade_not_available", 409)
        if target_version != compiler.manifest.pack_version:
            raise DomainError("industry_pack_version_not_found", 404)
        compiled_application = compiler.compile_application()
        source = installation["source_snapshot"] or {}
        base_scenarios = source.get("scenario_configs") or {}
        installed_scenarios = installation["installed_scenarios"] or {}
        scenario_plans: list[ScenarioUpgradePreview] = []
        target_snapshot: dict[str, Any] = {}

        async with self.engine.connect() as connection:
            for template_key, scenario_key in installed_scenarios.items():
                base_payload = base_scenarios.get(template_key)
                row = await one(
                    connection,
                    f"""
SELECT s.id,s.draft,s.draft_revision FROM service_scenarios s
WHERE s.tenant_id=:tenant AND {scenario_scope_sql} AND s.scenario_key=:key
  AND NOT archived
""",
                    tenant=tenant,
                    key=scenario_key,
                    **scenario_scope_params,
                )
                if base_payload is None or row is None:
                    scenario_plans.append(
                        ScenarioUpgradePreview(
                            template_key=template_key,
                            scenario_key=scenario_key,
                            status="blocked",
                            detail="当前场景或安装基线已不存在，无法安全升级。",
                        )
                    )
                    continue
                try:
                    target_config = compiler.compile_scenario(template_key)
                except IndustryPackCompileError:
                    scenario_plans.append(
                        ScenarioUpgradePreview(
                            template_key=template_key,
                            scenario_key=scenario_key,
                            status="blocked",
                            detail="目标版本已移除该场景模板，请先处理本地场景。",
                        )
                    )
                    continue
                base = ScenarioConfig.model_validate(base_payload)
                local = ScenarioConfig.model_validate(row["draft"])
                result: MergeResult = three_way_merge(base, local, target_config)
                status = result.status
                scenario_plans.append(
                    ScenarioUpgradePreview(
                        template_key=template_key,
                        scenario_key=scenario_key,
                        status=status,
                        conflicts=[_conflict_view(item) for item in result.conflicts],
                        auto_merged_fields=result.auto_merged_fields,
                        kept_local_fields=result.kept_local_fields,
                        incoming_fields=result.incoming_fields,
                        current_revision=row["draft_revision"],
                        merged_config=result.merged_config.model_dump(mode="json"),
                        detail=(
                            "可以安全合并。"
                            if status == "clean"
                            else "模板和本地配置修改了同一位置，需要人工选择。"
                        ),
                    )
                )
                target_snapshot[template_key] = target_config.model_dump(mode="json")

            target_application = compiled_application.application.model_copy(
                update={
                    "scenarios": [
                        item
                        for item in compiled_application.application.scenarios
                        if item.key in installed_scenarios
                    ]
                }
            )
            current_application = required(
                await one(
                    connection,
                    f"""
SELECT a.id,a.draft,a.draft_revision FROM service_applications a
WHERE a.tenant_id=:tenant AND {application_scope_sql} AND a.application_key=:key
  AND NOT archived
""",
                    tenant=tenant,
                    key=installation["application_key"],
                    **application_scope_params,
                ),
                "service_application_not_found",
            )

        app_conflicts: list[MergeConflictView] = []
        app_revision = current_application["draft_revision"]
        if source.get("application_config") is not None:
            merged_application, app_conflicts = _merge_application_config(
                ServiceApplicationConfig.model_validate(source["application_config"]),
                ServiceApplicationConfig.model_validate(current_application["draft"]),
                target_application,
            )
        else:
            merged_application = ServiceApplicationConfig.model_validate(
                current_application["draft"]
            )
            app_conflicts = [
                MergeConflictView(
                    path="application",
                    local=current_application["draft"],
                    incoming=target_application.model_dump(mode="json"),
                )
            ]

        status = "clean"
        if any(item.status == "blocked" for item in scenario_plans):
            status = "blocked"
        elif app_conflicts or any(item.status == "conflicted" for item in scenario_plans):
            status = "conflicted"
        plan = {
            "scenarios": [item.model_dump(mode="json") for item in scenario_plans],
            "application": merged_application.model_dump(mode="json"),
            "application_conflicts": [item.model_dump(mode="json") for item in app_conflicts],
            "application_revision": app_revision,
            "target_scenario_configs": target_snapshot,
            "target_application": target_application.model_dump(mode="json"),
        }
        _, scope_params = scope_predicate(resolved, alias="u")
        async with self.engine.begin() as connection:
            row = await one(
                connection,
                """
INSERT INTO industry_pack_upgrades(
    tenant_id,business_id,workspace_id,installation_id,from_version,
    to_version,status,base_digest,target_digest,plan,created_by
) VALUES(
    :tenant,:scope_business,:scope_workspace,:installation,:from_version,
    :to_version,:status,:base_digest,:target_digest,CAST(:plan AS jsonb),:actor
)
RETURNING *
""",
                tenant=tenant,
                installation=str(installation_id),
                from_version=installation["pack_version"],
                to_version=target_version,
                status=status,
                base_digest=installation["pack_digest"],
                target_digest=compiler.digest,
                plan=_json(plan),
                actor=actor,
                **scope_params,
            )
            await audit(
                connection,
                tenant,
                actor,
                "industry_pack.upgrade_previewed",
                row["id"],
                installation_id=str(installation_id),
                status=status,
                to_version=target_version,
            )
        return IndustryPackUpgradePreview(
            id=row["id"],
            installation_id=installation_id,
            from_version=installation["pack_version"],
            to_version=target_version,
            status=status,
            scenarios=scenario_plans,
            application=merged_application.model_dump(mode="json"),
            application_conflicts=app_conflicts,
            created_at=row["created_at"],
        ).model_dump(mode="json")

    async def apply_upgrade(
        self,
        tenant: str,
        actor: str,
        installation_id: UUID,
        body: IndustryPackUpgradeInput,
        *,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        resolved = persisted_scope(tenant, scope)
        scope_sql, scope_params = scope_predicate(resolved, alias="i")
        async with self.engine.begin() as connection:
            installation = await self._installation_row(
                connection,
                tenant,
                resolved,
                installation_id,
                lock=True,
            )
            preview = required(
                await one(
                    connection,
                    """
SELECT * FROM industry_pack_upgrades
WHERE tenant_id=:tenant AND business_id=:scope_business
  AND workspace_id=:scope_workspace AND id=:id
  AND installation_id=:installation
FOR UPDATE
""",
                    tenant=tenant,
                    id=str(body.preview_id),
                    installation=str(installation_id),
                    **scope_params,
                ),
                "industry_pack_upgrade_preview_not_found",
            )
            if preview["status"] != "clean":
                raise DomainError("industry_pack_upgrade_conflicted", 409)
            if body.target_version is not None and body.target_version != preview["to_version"]:
                raise DomainError("industry_pack_upgrade_target_mismatch", 409)
            if preview["from_version"] != installation["pack_version"]:
                raise DomainError("industry_pack_upgrade_preview_stale", 409)
            plan = preview["plan"]
            upgraded: list[str] = []
            for item in plan.get("scenarios", []):
                if item.get("status") != "clean":
                    raise DomainError("industry_pack_upgrade_conflicted", 409)
                merged_config = ScenarioConfig.model_validate(item["merged_config"])
                current = await one(
                    connection,
                    """
SELECT id,draft_revision FROM service_scenarios
WHERE tenant_id=:tenant AND business_id=:scope_business
  AND workspace_id=:scope_workspace AND scenario_key=:key
  AND NOT archived
FOR UPDATE
""",
                    tenant=tenant,
                    key=item["scenario_key"],
                    **scope_params,
                )
                if current is None or current["draft_revision"] != item["current_revision"]:
                    raise DomainError("industry_pack_upgrade_preview_stale", 409)
                await execute(
                    connection,
                    """
UPDATE service_scenarios
SET name=:name,description=:description,domain=:domain,template=:template,
    draft=CAST(:config AS jsonb),draft_revision=draft_revision+1,
    updated_by=:actor,updated_at=now()
WHERE id=:id AND tenant_id=:tenant
""",
                    id=current["id"],
                    tenant=tenant,
                    name=merged_config.name,
                    description=merged_config.description,
                    domain=merged_config.domain,
                    template=merged_config.template,
                    config=merged_config.model_dump_json(),
                    actor=actor,
                )
                upgraded.append(item["scenario_key"])

            merged_application = ServiceApplicationConfig.model_validate(plan["application"])
            app = await one(
                connection,
                """
SELECT id,draft_revision FROM service_applications
WHERE tenant_id=:tenant AND business_id=:scope_business
  AND workspace_id=:scope_workspace AND application_key=:key
  AND NOT archived
FOR UPDATE
""",
                tenant=tenant,
                key=installation["application_key"],
                **scope_params,
            )
            if app is None or app["draft_revision"] != plan.get("application_revision"):
                raise DomainError("industry_pack_upgrade_preview_stale", 409)
            await execute(
                connection,
                """
UPDATE service_applications
SET name=:name,description=:description,draft=CAST(:config AS jsonb),
    draft_revision=draft_revision+1,
    updated_by=:actor,updated_at=now()
WHERE id=:id AND tenant_id=:tenant
""",
                id=app["id"],
                tenant=tenant,
                name=merged_application.name,
                description=merged_application.description,
                config=merged_application.model_dump_json(),
                actor=actor,
            )
            compiler = self._compiler(installation["pack_key"])
            manifest = compiler.manifest
            if preview["to_version"] != manifest.pack_version:
                raise DomainError("industry_pack_version_not_found", 404)
            target_configs = plan.get("target_scenario_configs") or {}
            await self.providers.ensure_requirements(
                connection,
                tenant,
                actor,
                resolved,
                self._requirements(
                    compiler,
                    [ScenarioConfig.model_validate(item) for item in target_configs.values()],
                ),
            )
            versions = {
                template.template_key: template.template_version
                for template in manifest.scenario_templates
                if template.template_key in target_configs
            }
            digests = {
                template.template_key: compiler.digest_scenario_template(template)
                for template in manifest.scenario_templates
                if template.template_key in target_configs
            }
            updated_installation = await one(
                connection,
                f"""
UPDATE industry_pack_installations i
SET pack_version=:pack_version,pack_digest=:pack_digest,
    maturity=:maturity,status='installed',
    scenario_template_versions=CAST(:versions AS jsonb),
    scenario_template_digests=CAST(:digests AS jsonb),
    source_snapshot=CAST(:snapshot AS jsonb),
    revision=revision+1,updated_at=now()
WHERE i.id=:id AND i.tenant_id=:tenant AND {scope_sql}
RETURNING i.*
""",
                id=str(installation_id),
                tenant=tenant,
                pack_version=preview["to_version"],
                pack_digest=preview["target_digest"],
                maturity=manifest.maturity.value,
                versions=_json(versions),
                digests=_json(digests),
                snapshot=_json(
                    {
                        "application_config": plan.get("target_application"),
                        "scenario_configs": target_configs,
                    }
                ),
                **scope_params,
            )
            await execute(
                connection,
                """
UPDATE industry_pack_upgrades
SET status='applied',applied_by=:actor,applied_at=now()
WHERE id=:id AND tenant_id=:tenant
""",
                id=str(body.preview_id),
                tenant=tenant,
                actor=actor,
            )
            await audit(
                connection,
                tenant,
                actor,
                "industry_pack.upgraded",
                installation_id,
                preview_id=str(body.preview_id),
                from_version=preview["from_version"],
                to_version=preview["to_version"],
                scenarios=upgraded,
            )
        return IndustryPackUpgradeResult(
            applied=True,
            installation=_installation(updated_installation),
            preview_id=body.preview_id,
            upgraded_scenarios=upgraded,
            application_key=installation["application_key"],
        ).model_dump(mode="json")


__all__ = ["IndustryPackService"]
