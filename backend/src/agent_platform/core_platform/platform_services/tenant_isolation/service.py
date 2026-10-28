"""Durable validation for tenant, business, and workspace scope."""

from collections.abc import Iterable, Mapping

from agent_platform.core_platform.platform_services.persistence.store import (
    DomainError,
    execute,
    many,
    one,
)
from agent_platform.extension_contracts import BusinessScope

from .context import current_scope

DEFAULT_BUSINESS_ID = "customer-service"
DEFAULT_WORKSPACE_ID = "default"


def resolve_scope(tenant_id: str, scope: BusinessScope | None = None) -> BusinessScope:
    """Return a complete scope for a service call.

    HTTP callers pass the scope resolved by the application boundary.  Older
    service/seed callers may omit it and are deliberately mapped to the
    customer-service/default compatibility scope.  A scope from another
    tenant is never silently accepted.
    """

    candidate = scope or current_scope()
    if candidate is not None and candidate.tenant_id != tenant_id:
        raise ScopeError("tenant_scope_mismatch", 403)
    return BusinessScope(
        tenant_id=tenant_id,
        business_id=(
            candidate.business_id if candidate and candidate.business_id else DEFAULT_BUSINESS_ID
        ),
        workspace_id=candidate.workspace_id if candidate else DEFAULT_WORKSPACE_ID,
    )


def persisted_scope(tenant_id: str, scope: BusinessScope | None = None) -> BusinessScope:
    """Return a complete scope for creating a persisted row."""

    resolved = resolve_scope(tenant_id, scope)
    return BusinessScope(
        tenant_id=resolved.tenant_id,
        business_id=resolved.business_id,
        workspace_id=resolved.workspace_id or DEFAULT_WORKSPACE_ID,
    )


def scope_predicate(scope: BusinessScope, alias: str = "") -> tuple[str, dict[str, str]]:
    """Return SQL for a scope, omitting workspace when it was not selected."""

    prefix = f"{alias}." if alias else ""
    clause = f"{prefix}business_id=:scope_business"
    params = {"scope_business": scope.business_id or DEFAULT_BUSINESS_ID}
    if scope.workspace_id is not None:
        clause += f" AND {prefix}workspace_id=:scope_workspace"
        params["scope_workspace"] = scope.workspace_id
    return clause, params


class ScopeError(DomainError):
    """A requested business scope is not available to the current tenant."""


class TenantScopeService:
    """Resolve application scopes against the tenant isolation control plane."""

    def __init__(self, engine: object) -> None:
        self.engine = engine

    async def ensure_registered(
        self,
        tenant_id: str,
        businesses: Iterable[Mapping[str, str]],
    ) -> None:
        """Register application-owned businesses and their default workspace."""

        async with self.engine.begin() as connection:
            for business in businesses:
                business_id = business["id"]
                name = business["name"]
                route_prefix = business["route_prefix"]
                await execute(
                    connection,
                    """
                    INSERT INTO tenant_businesses
                        (tenant_id,business_id,name,route_prefix)
                    VALUES (:tenant,:business,:name,:prefix)
                    ON CONFLICT (tenant_id,business_id) DO UPDATE
                    SET name=EXCLUDED.name,
                        route_prefix=EXCLUDED.route_prefix,
                        updated_at=now()
                    """,
                    tenant=tenant_id,
                    business=business_id,
                    name=name,
                    prefix=route_prefix,
                )
                await execute(
                    connection,
                    """
                    INSERT INTO tenant_workspaces
                        (tenant_id,business_id,workspace_id,name)
                    VALUES (:tenant,:business,'default','Default')
                    ON CONFLICT (tenant_id,business_id,workspace_id) DO NOTHING
                    """,
                    tenant=tenant_id,
                    business=business_id,
                )

    async def validate(
        self,
        scope: BusinessScope,
    ) -> BusinessScope:
        """Validate a resolved business and optional workspace scope."""

        if scope.business_id is None:
            return scope
        async with self.engine.connect() as connection:
            business = await one(
                connection,
                """
                SELECT enabled
                FROM tenant_businesses
                WHERE tenant_id=:tenant AND business_id=:business
                """,
                tenant=scope.tenant_id,
                business=scope.business_id,
            )
            if not business or not business["enabled"]:
                raise ScopeError("business_scope_unavailable", 403)
            if scope.workspace_id is None:
                return scope
            workspace = await one(
                connection,
                """
                SELECT enabled
                FROM tenant_workspaces
                WHERE tenant_id=:tenant
                  AND business_id=:business
                  AND workspace_id=:workspace
                """,
                tenant=scope.tenant_id,
                business=scope.business_id,
                workspace=scope.workspace_id,
            )
        if not workspace or not workspace["enabled"]:
            raise ScopeError("workspace_scope_unavailable", 403)
        return scope

    async def workspaces(self, tenant_id: str, business_id: str) -> list[dict[str, object]]:
        """List enabled workspaces belonging to one tenant business."""

        async with self.engine.connect() as connection:
            return await many(
                connection,
                """
                SELECT workspace_id,name,enabled
                FROM tenant_workspaces
                WHERE tenant_id=:tenant AND business_id=:business AND enabled
                ORDER BY workspace_id
                """,
                tenant=tenant_id,
                business=business_id,
            )


def resource_scope_clause(alias: str = "") -> tuple[str, dict[str, str]]:
    """Return SQL and parameters for business/workspace-scoped resources.

    No clause is returned for workers and legacy scripts that do not run inside
    an HTTP business scope. Their existing tenant-level behavior is preserved.
    """

    scope = current_scope()
    if scope is None or scope.business_id is None:
        return "", {}
    prefix = f"{alias}." if alias else ""
    clause = f" AND {prefix}business_id=:scope_business"
    params = {"scope_business": scope.business_id}
    if scope.workspace_id is not None:
        clause += f" AND {prefix}workspace_id=:scope_workspace"
        params["scope_workspace"] = scope.workspace_id
    return clause, params


def resource_scope_values(
    default_business: str = "customer-service",
    default_workspace: str = "default",
) -> dict[str, str]:
    """Return trusted insert values for a scoped resource."""

    scope = current_scope()
    return {
        "business_id": scope.business_id if scope and scope.business_id else default_business,
        "workspace_id": (scope.workspace_id if scope and scope.workspace_id else default_workspace),
    }


__all__ = [
    "DEFAULT_BUSINESS_ID",
    "DEFAULT_WORKSPACE_ID",
    "ScopeError",
    "TenantScopeService",
    "persisted_scope",
    "resolve_scope",
    "resource_scope_clause",
    "resource_scope_values",
    "scope_predicate",
]
