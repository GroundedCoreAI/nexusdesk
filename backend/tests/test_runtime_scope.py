from agent_platform.core_platform.platform_services.tenant_isolation.service import (
    persisted_scope,
    resolve_scope,
    scope_predicate,
)
from agent_platform.extension_contracts import BusinessScope


def test_scope_without_workspace_filters_by_business_only():
    scope = resolve_scope(
        "tenant-a",
        BusinessScope(tenant_id="tenant-a", business_id="itsm", workspace_id=None),
    )

    clause, params = scope_predicate(scope, "r")

    assert clause == "r.business_id=:scope_business"
    assert params == {"scope_business": "itsm"}


def test_persisted_scope_defaults_workspace_for_writes():
    scope = persisted_scope(
        "tenant-a",
        BusinessScope(tenant_id="tenant-a", business_id="itsm", workspace_id=None),
    )

    assert scope == BusinessScope(
        tenant_id="tenant-a",
        business_id="itsm",
        workspace_id="default",
    )


def test_legacy_scope_defaults_to_customer_service_default():
    assert resolve_scope("tenant-a") == BusinessScope(
        tenant_id="tenant-a",
        business_id="customer-service",
        workspace_id="default",
    )
