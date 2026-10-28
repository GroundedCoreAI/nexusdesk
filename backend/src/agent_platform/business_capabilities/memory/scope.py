"""Three-dimensional scope helpers for the memory data plane."""

from agent_platform.core_platform.platform_services.tenant_isolation.service import (
    resource_scope_clause,
    resource_scope_values,
)


def clause(alias: str = "") -> tuple[str, dict[str, str]]:
    """Return the current request scope as a SQL ``AND`` fragment.

    A missing request scope intentionally keeps legacy worker/seed callers
    tenant-compatible.  Workers bind the scope persisted on their task before
    executing a task, so asynchronous writes still use the complete scope.
    """

    return resource_scope_clause(alias=alias)


def values() -> dict[str, str]:
    """Return trusted scope values for a new memory row."""

    return resource_scope_values()
