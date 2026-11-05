from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from agent_platform.business_capabilities.customer_service.scenarios.routes import (
    agent_router,
    router,
)
from agent_platform.core_platform.platform_services.identity.access import Principal, principal
from agent_platform.extension_contracts import BusinessScope

TENANT = "tenant-scenario"
AGENT_ID = UUID("22222222-2222-2222-2222-222222222222")
SCOPE = BusinessScope(
    tenant_id=TENANT,
    business_id="customer-service",
    workspace_id="support-default",
)
READER_PRINCIPAL = Principal(TENANT, "viewer", "viewer")
ADMIN_PRINCIPAL = Principal(TENANT, "admin", "admin")


def _scenario_config() -> dict[str, Any]:
    return {
        "name": "查询我的订单",
        "description": "找到并确认一笔订单",
        "domain": "购物消费",
        "template": "query",
        "handlers": [
            {
                "key": "direct-reply",
                "type": "direct",
                "label": "固定回复",
                "reply": "请提供订单号。",
            }
        ],
        "fallback_order": ["direct-reply"],
    }


class FakeScenarioService:
    def __init__(self) -> None:
        self.calls: dict[str, list[dict[str, Any]]] = {}

    def _record(self, name: str, **values: Any) -> None:
        self.calls.setdefault(name, []).append(values)

    async def list(
        self,
        tenant: str,
        *,
        status: str,
        q: str,
        scope: BusinessScope,
    ) -> dict[str, Any]:
        self._record("list", tenant=tenant, status=status, q=q, scope=scope)
        return {"items": [], "total": 0}

    async def get(
        self,
        tenant: str,
        key: str,
        *,
        scope: BusinessScope,
    ) -> dict[str, Any]:
        self._record("get", tenant=tenant, key=key, scope=scope)
        return {"key": key}

    async def create(
        self,
        tenant: str,
        actor: str,
        body: Any,
        *,
        scope: BusinessScope,
    ) -> dict[str, Any]:
        self._record("create", tenant=tenant, actor=actor, body=body, scope=scope)
        return {"key": body.key, "revision": 1}

    async def update(
        self,
        tenant: str,
        actor: str,
        key: str,
        body: Any,
        *,
        scope: BusinessScope,
    ) -> dict[str, Any]:
        self._record(
            "update",
            tenant=tenant,
            actor=actor,
            key=key,
            body=body,
            scope=scope,
        )
        return {"key": key, "revision": body.revision + 1}

    async def set_status(
        self,
        tenant: str,
        actor: str,
        key: str,
        status: str,
        revision: int,
        *,
        scope: BusinessScope,
    ) -> dict[str, Any]:
        self._record(
            "set_status",
            tenant=tenant,
            actor=actor,
            key=key,
            status=status,
            revision=revision,
            scope=scope,
        )
        return {"key": key, "status": status}

    async def publish(
        self,
        tenant: str,
        actor: str,
        key: str,
        revision: int,
        *,
        scope: BusinessScope,
    ) -> dict[str, Any]:
        self._record(
            "publish",
            tenant=tenant,
            actor=actor,
            key=key,
            revision=revision,
            scope=scope,
        )
        return {"key": key, "version": 2}

    async def versions(
        self,
        tenant: str,
        key: str,
        *,
        scope: BusinessScope,
    ) -> dict[str, Any]:
        self._record("versions", tenant=tenant, key=key, scope=scope)
        return {"items": []}

    async def rollback(
        self,
        tenant: str,
        actor: str,
        key: str,
        version: int,
        revision: int,
        *,
        scope: BusinessScope,
    ) -> dict[str, Any]:
        self._record(
            "rollback",
            tenant=tenant,
            actor=actor,
            key=key,
            version=version,
            revision=revision,
            scope=scope,
        )
        return {"key": key, "rollback_version": version}

    async def simulate(
        self,
        tenant: str,
        actor: str,
        key: str | None,
        body: Any,
        *,
        scope: BusinessScope,
        persist: bool,
    ) -> dict[str, Any]:
        self._record(
            "simulate",
            tenant=tenant,
            actor=actor,
            key=key,
            body=body,
            scope=scope,
            persist=persist,
        )
        return {"scenario_key": key or "matched-scenario", "trace_id": "trace-1"}

    async def traces(
        self,
        tenant: str,
        key: str,
        *,
        limit: int,
        scope: BusinessScope,
    ) -> dict[str, Any]:
        self._record("traces", tenant=tenant, key=key, limit=limit, scope=scope)
        return {"items": []}

    async def overview(
        self,
        tenant: str,
        *,
        scope: BusinessScope,
    ) -> dict[str, Any]:
        self._record("overview", tenant=tenant, scope=scope)
        return {"scenarios": 0}

    async def agent_references(
        self,
        tenant: str,
        agent_id: UUID,
        *,
        scope: BusinessScope,
    ) -> dict[str, Any]:
        self._record(
            "agent_references",
            tenant=tenant,
            agent_id=agent_id,
            scope=scope,
        )
        return {"items": []}


def _client(
    scenarios: FakeScenarioService,
    user: Principal = READER_PRINCIPAL,
) -> TestClient:
    app = FastAPI()
    app.state.runtime = SimpleNamespace(
        groups=SimpleNamespace(business=SimpleNamespace(scenarios=scenarios))
    )

    @app.middleware("http")
    async def attach_business_scope(request: Request, call_next: Any):
        request.state.business_scope = SCOPE
        return await call_next(request)

    app.include_router(router, prefix="/api/v1")
    app.include_router(agent_router, prefix="/api/v1")
    app.dependency_overrides[principal] = lambda: user
    return TestClient(app)


def test_list_uses_defaults_filters_and_reader_scope():
    scenarios = FakeScenarioService()
    with _client(scenarios) as client:
        default = client.get("/api/v1/service-scenarios")
        filtered = client.get(
            "/api/v1/service-scenarios",
            params={"status": "review", "q": "订单"},
        )

    assert default.status_code == 200
    assert filtered.status_code == 200
    assert scenarios.calls["list"][0] == {
        "tenant": TENANT,
        "status": "all",
        "q": "",
        "scope": SCOPE,
    }
    assert scenarios.calls["list"][1]["status"] == "review"
    assert scenarios.calls["list"][1]["q"] == "订单"
    assert scenarios.calls["list"][1]["scope"] == SCOPE


def test_list_rejects_unknown_status():
    scenarios = FakeScenarioService()
    with _client(scenarios) as client:
        response = client.get(
            "/api/v1/service-scenarios",
            params={"status": "published-typo"},
        )

    assert response.status_code == 422
    assert "list" not in scenarios.calls


def test_overview_route_precedes_key_route():
    scenarios = FakeScenarioService()
    with _client(scenarios) as client:
        response = client.get("/api/v1/service-scenarios/overview")

    assert response.status_code == 200
    assert response.json() == {"scenarios": 0}
    assert "overview" in scenarios.calls
    assert "get" not in scenarios.calls


def test_create_requires_admin_and_returns_201():
    scenarios = FakeScenarioService()
    payload = {"key": "query-orders", "config": _scenario_config()}
    with _client(scenarios, READER_PRINCIPAL) as client:
        denied = client.post("/api/v1/service-scenarios", json=payload)
    with _client(scenarios, ADMIN_PRINCIPAL) as client:
        created = client.post("/api/v1/service-scenarios", json=payload)

    assert denied.status_code == 403
    assert created.status_code == 201
    call = scenarios.calls["create"][0]
    assert call["tenant"] == TENANT
    assert call["actor"] == "admin"
    assert call["body"].key == "query-orders"
    assert call["body"].config.name == "查询我的订单"
    assert call["scope"] == SCOPE


@pytest.mark.parametrize(
    "key",
    [
        "",
        "Query-Orders",
        "1-orders",
        "a" * 65,
    ],
)
def test_create_rejects_invalid_keys(key: str):
    scenarios = FakeScenarioService()
    with _client(scenarios, ADMIN_PRINCIPAL) as client:
        response = client.post(
            "/api/v1/service-scenarios",
            json={"key": key, "config": _scenario_config()},
        )

    assert response.status_code == 422
    assert "create" not in scenarios.calls


def test_update_status_publish_and_rollback_forward_revisions():
    scenarios = FakeScenarioService()
    config = _scenario_config()
    with _client(scenarios, ADMIN_PRINCIPAL) as client:
        updated = client.put(
            "/api/v1/service-scenarios/query-orders",
            json={"config": config, "revision": 3},
        )
        status = client.post(
            "/api/v1/service-scenarios/query-orders/status",
            json={"status": "review", "revision": 4},
        )
        published = client.post(
            "/api/v1/service-scenarios/query-orders/publish",
            json={"revision": 5},
        )
        rolled_back = client.post(
            "/api/v1/service-scenarios/query-orders/rollback",
            json={"version": 2, "revision": 6},
        )

    assert updated.status_code == 200
    assert status.status_code == 200
    assert published.status_code == 200
    assert rolled_back.status_code == 200
    assert scenarios.calls["update"][0]["body"].revision == 3
    assert scenarios.calls["set_status"][0]["status"] == "review"
    assert scenarios.calls["set_status"][0]["revision"] == 4
    assert scenarios.calls["publish"][0]["revision"] == 5
    assert scenarios.calls["rollback"][0]["version"] == 2
    assert scenarios.calls["rollback"][0]["revision"] == 6
    for name in ("update", "set_status", "publish", "rollback"):
        assert scenarios.calls[name][0]["scope"] == SCOPE


@pytest.mark.parametrize(
    "method,path,payload",
    [
        ("PUT", "/query-orders", {"config": _scenario_config(), "revision": 0}),
        (
            "POST",
            "/query-orders/status",
            {"status": "published", "revision": 1},
        ),
        ("POST", "/query-orders/status", {"status": "draft", "revision": 0}),
        ("POST", "/query-orders/publish", {"revision": 0}),
        ("POST", "/query-orders/rollback", {"version": 0, "revision": 1}),
        ("POST", "/query-orders/rollback", {"version": 1, "revision": 0}),
    ],
)
def test_write_input_boundaries_are_validated(
    method: str,
    path: str,
    payload: dict[str, Any],
):
    scenarios = FakeScenarioService()
    with _client(scenarios, ADMIN_PRINCIPAL) as client:
        response = client.request(
            method,
            f"/api/v1/service-scenarios{path}",
            json=payload,
        )

    assert response.status_code == 422
    assert scenarios.calls == {}


def test_get_versions_and_traces_forward_defaults_and_scope():
    scenarios = FakeScenarioService()
    with _client(scenarios) as client:
        detail = client.get("/api/v1/service-scenarios/query-orders")
        versions = client.get("/api/v1/service-scenarios/query-orders/versions")
        traces = client.get("/api/v1/service-scenarios/query-orders/traces")
        maximum = client.get(
            "/api/v1/service-scenarios/query-orders/traces",
            params={"limit": 200},
        )

    assert detail.status_code == 200
    assert versions.status_code == 200
    assert traces.status_code == 200
    assert maximum.status_code == 200
    assert scenarios.calls["get"][0] == {
        "tenant": TENANT,
        "key": "query-orders",
        "scope": SCOPE,
    }
    assert scenarios.calls["versions"][0]["scope"] == SCOPE
    assert scenarios.calls["traces"][0]["limit"] == 50
    assert scenarios.calls["traces"][1]["limit"] == 200


@pytest.mark.parametrize("limit", [0, 201])
def test_trace_limit_boundaries(limit: int):
    scenarios = FakeScenarioService()
    with _client(scenarios) as client:
        response = client.get(
            "/api/v1/service-scenarios/query-orders/traces",
            params={"limit": limit},
        )

    assert response.status_code == 422
    assert "traces" not in scenarios.calls


def test_simulate_detects_scenario_and_forces_persistence():
    scenarios = FakeScenarioService()
    body = {"message": "我的订单到哪了？"}
    with _client(scenarios) as client:
        matched = client.post("/api/v1/service-scenarios/simulate", json=body)
        named = client.post(
            "/api/v1/service-scenarios/simulate",
            params={"scenario_key": "query-orders"},
            json=body,
        )
        direct = client.post(
            "/api/v1/service-scenarios/query-orders/simulate",
            json=body,
        )

    assert matched.status_code == 200
    assert named.status_code == 200
    assert direct.status_code == 200
    calls = scenarios.calls["simulate"]
    assert calls[0]["key"] is None
    assert calls[0]["persist"] is True
    assert calls[1]["key"] == "query-orders"
    assert calls[1]["persist"] is True
    assert calls[2]["key"] == "query-orders"
    assert calls[2]["persist"] is True
    assert all(call["actor"] == "viewer" for call in calls)
    assert all(call["scope"] == SCOPE for call in calls)


def test_agent_service_scenario_references_are_mounted():
    scenarios = FakeScenarioService()
    with _client(scenarios) as client:
        response = client.get(f"/api/v1/agents/{AGENT_ID}/service-scenarios")

    assert response.status_code == 200
    assert response.json() == {"items": []}
    assert scenarios.calls["agent_references"][0] == {
        "tenant": TENANT,
        "agent_id": AGENT_ID,
        "scope": SCOPE,
    }
