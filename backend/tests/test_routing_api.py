from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from agent_platform.applications.customer_service.platform_routes import router
from agent_platform.core_platform.platform_services.identity.access import Principal, principal
from agent_platform.core_platform.platform_services.persistence.store import DomainError
from agent_platform.extension_contracts import BusinessScope

TENANT = "tenant-routing"
CID = UUID("11111111-1111-1111-1111-111111111111")
SCOPE = BusinessScope(
    tenant_id=TENANT,
    business_id="customer-service",
    workspace_id="support-default",
)
READER_PRINCIPAL = Principal(TENANT, "viewer", "viewer")
OPERATOR_PRINCIPAL = Principal(TENANT, "operator", "operator")


class FakeCustomer:
    def __init__(self) -> None:
        self.list_calls: list[dict[str, Any]] = []
        self.summary_calls: list[dict[str, Any]] = []
        self.send_calls: list[dict[str, Any]] = []
        self.send_result: dict[str, Any] = {}

    async def list_routing_decisions(
        self,
        tenant: str,
        cid: UUID,
        *,
        before: str | None,
        limit: int,
        scope: BusinessScope,
    ) -> dict[str, Any]:
        self.list_calls.append(
            {
                "tenant": tenant,
                "cid": cid,
                "before": before,
                "limit": limit,
                "scope": scope,
            }
        )
        return {"items": [], "next_before": None}

    async def routing_summary(
        self,
        tenant: str,
        *,
        since: datetime | None,
        until: datetime | None,
        scope: BusinessScope,
    ) -> dict[str, Any]:
        self.summary_calls.append(
            {
                "tenant": tenant,
                "since": since,
                "until": until,
                "scope": scope,
            }
        )
        return {"disposition": {}, "reason_code": {}}

    async def send(
        self,
        tenant: str,
        actor: str,
        cid: UUID,
        content: str,
        *,
        scope: BusinessScope,
    ) -> dict[str, Any]:
        self.send_calls.append(
            {
                "tenant": tenant,
                "actor": actor,
                "cid": cid,
                "content": content,
                "scope": scope,
            }
        )
        return self.send_result


def _client(
    customer: FakeCustomer,
    user: Principal | None = None,
) -> TestClient:
    user = user or READER_PRINCIPAL
    app = FastAPI()
    app.state.runtime = SimpleNamespace(
        groups=SimpleNamespace(business=SimpleNamespace(customer=customer))
    )

    @app.middleware("http")
    async def attach_business_scope(request: Request, call_next: Any):
        request.state.business_scope = SCOPE
        return await call_next(request)

    @app.exception_handler(DomainError)
    async def domain_error(request: Request, exc: DomainError):
        return JSONResponse(status_code=exc.status, content={"detail": exc.code})

    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[principal] = lambda: user
    return TestClient(app)


def test_routing_routes_are_mounted_with_reader_permission():
    customer = FakeCustomer()
    with _client(customer) as client:
        listed = client.get(f"/api/v1/conversations/{CID}/routing-decisions")
        summarized = client.get("/api/v1/routing-decisions/summary")

    assert listed.status_code == 200
    assert summarized.status_code == 200
    assert customer.list_calls[0]["tenant"] == TENANT
    assert customer.list_calls[0]["scope"] == SCOPE
    assert customer.summary_calls[0]["scope"] == SCOPE


def test_list_routing_decisions_forwards_cursor_limit_and_default():
    customer = FakeCustomer()
    with _client(customer) as client:
        first = client.get(f"/api/v1/conversations/{CID}/routing-decisions")
        second = client.get(
            f"/api/v1/conversations/{CID}/routing-decisions",
            params={"before": "opaque-cursor", "limit": 25},
        )
        maximum = client.get(
            f"/api/v1/conversations/{CID}/routing-decisions",
            params={"limit": 200},
        )
        too_large = client.get(
            f"/api/v1/conversations/{CID}/routing-decisions",
            params={"limit": 201},
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert maximum.status_code == 200
    assert too_large.status_code == 422
    assert customer.list_calls[0]["limit"] == 50
    assert customer.list_calls[0]["before"] is None
    assert customer.list_calls[1]["limit"] == 25
    assert customer.list_calls[1]["before"] == "opaque-cursor"
    assert customer.list_calls[1]["cid"] == CID
    assert customer.list_calls[2]["limit"] == 200


def test_summary_defaults_to_last_seven_days():
    customer = FakeCustomer()
    with _client(customer) as client:
        response = client.get("/api/v1/routing-decisions/summary")

    assert response.status_code == 200
    call = customer.summary_calls[0]
    assert call["since"].tzinfo == UTC
    assert call["until"].tzinfo == UTC
    assert call["until"] - call["since"] == timedelta(days=7)


def test_summary_forwards_explicit_range_in_utc():
    customer = FakeCustomer()
    with _client(customer) as client:
        response = client.get(
            "/api/v1/routing-decisions/summary",
            params={
                "since": "2026-10-01T00:00:00+08:00",
                "until": "2026-10-08T00:00:00+08:00",
            },
        )

    assert response.status_code == 200
    call = customer.summary_calls[0]
    assert call["since"] == datetime(2026, 9, 30, 16, tzinfo=UTC)
    assert call["until"] == datetime(2026, 10, 7, 16, tzinfo=UTC)


@pytest.mark.parametrize(
    ("since", "until"),
    [
        ("2026-10-08T00:00:00Z", "2026-10-08T00:00:00Z"),
        ("2026-10-09T00:00:00Z", "2026-10-08T00:00:00Z"),
        ("2026-09-01T00:00:00Z", "2026-10-08T00:00:00Z"),
    ],
)
def test_summary_rejects_invalid_time_windows(since: str, until: str):
    customer = FakeCustomer()
    with _client(customer) as client:
        response = client.get(
            "/api/v1/routing-decisions/summary",
            params={"since": since, "until": until},
        )

    assert response.status_code == 422
    assert response.json() == {"detail": "invalid_time_range"}
    assert customer.summary_calls == []


def test_messages_maps_non_empty_rejected_to_409():
    customer = FakeCustomer()
    customer.send_result = {
        "conversation_id": str(CID),
        "run": None,
        "rejected": "conversation_closed",
    }
    with _client(customer, OPERATOR_PRINCIPAL) as client:
        response = client.post(
            f"/api/v1/conversations/{CID}/messages",
            json={"content": "hello"},
        )

    assert response.status_code == 409
    assert response.json() == {"detail": "conversation_closed"}
    assert customer.send_calls[0]["content"] == "hello"
    assert customer.send_calls[0]["scope"] == SCOPE


def test_messages_passes_through_normal_result():
    customer = FakeCustomer()
    customer.send_result = {
        "conversation_id": str(CID),
        "run": {"id": "run-1", "status": "queued"},
    }
    with _client(customer, OPERATOR_PRINCIPAL) as client:
        response = client.post(
            f"/api/v1/conversations/{CID}/messages",
            json={"content": "hello"},
        )

    assert response.status_code == 202
    assert response.json() == customer.send_result
