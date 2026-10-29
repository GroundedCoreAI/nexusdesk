from fastapi.testclient import TestClient

from agent_platform.applications.business_registry import BusinessRegistry
from agent_platform.applications.customer_service.application import customer_service_application
from agent_platform.applications.group.main import create_app
from agent_platform.extension_contracts import BusinessScope, ToolExecutionContext


def test_group_entrypoint_lists_registered_businesses():
    client = TestClient(create_app())

    response = client.get("/api/v1/businesses")

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": "customer-service",
            "name": "Customer Service",
            "route_prefix": "/customer-service",
        },
        {"id": "itsm", "name": "ITSM", "route_prefix": "/itsm"},
    ]


def test_group_entrypoint_mounts_customer_service_under_business_prefix():
    client = TestClient(create_app())

    response = client.get("/api/v1/customer-service/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "0.1.0"}


def test_group_entrypoint_mounts_itsm_under_a_second_business_prefix():
    client = TestClient(create_app())

    response = client.get("/api/v1/itsm/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "business_id": "itsm"}


def test_group_entrypoint_does_not_claim_legacy_business_root():
    client = TestClient(create_app())

    response = client.get("/api/v1/health")

    assert response.status_code == 404


def test_business_registry_resolves_longest_business_prefix():
    registry = BusinessRegistry((customer_service_application("/customer-service"),))

    assert registry.resolve_business_id("/api/v1/customer-service/agents") == "customer-service"
    assert registry.resolve_business_id("/api/v1/model-gateway/profiles") is None


def test_business_scope_is_optional_beyond_the_existing_tenant_boundary():
    scope = BusinessScope(
        tenant_id="tenant-a",
        business_id="customer-service",
        workspace_id="support-default",
    )
    context = ToolExecutionContext(
        tenant_id=scope.tenant_id,
        business_id=scope.business_id,
        workspace_id=scope.workspace_id,
        source="application",
    )

    assert context.business_id == "customer-service"
    assert context.workspace_id == "support-default"
