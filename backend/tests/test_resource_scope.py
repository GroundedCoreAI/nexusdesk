from agent_platform.core_platform.platform_services.tenant_isolation.context import (
    bind_scope,
    reset_scope,
)
from agent_platform.core_platform.platform_services.tenant_isolation.service import (
    resource_scope_clause,
    resource_scope_values,
)
from agent_platform.extension_contracts import BusinessScope


def test_resource_scope_is_legacy_compatible_without_request_context():
    assert resource_scope_clause() == ("", {})
    assert resource_scope_values() == {
        "business_id": "customer-service",
        "workspace_id": "default",
    }


def test_resource_scope_generates_trusted_business_and_workspace_predicates():
    token = bind_scope(
        BusinessScope(
            tenant_id="tenant-1",
            business_id="itsm",
            workspace_id="service-desk",
        )
    )
    try:
        assert resource_scope_clause("resource") == (
            " AND resource.business_id=:scope_business AND resource.workspace_id=:scope_workspace",
            {"scope_business": "itsm", "scope_workspace": "service-desk"},
        )
        assert resource_scope_values() == {
            "business_id": "itsm",
            "workspace_id": "service-desk",
        }
    finally:
        reset_scope(token)


def test_business_scope_without_workspace_keeps_workspace_manager_compatibility():
    token = bind_scope(BusinessScope(tenant_id="tenant-1", business_id="customer-service"))
    try:
        assert resource_scope_clause() == (
            " AND business_id=:scope_business",
            {"scope_business": "customer-service"},
        )
        assert resource_scope_values() == {
            "business_id": "customer-service",
            "workspace_id": "default",
        }
    finally:
        reset_scope(token)
