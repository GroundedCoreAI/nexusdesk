from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from agent_platform.business_capabilities.customer_service.service_apps.routes import router
from agent_platform.core_platform.platform_services.identity.access import Principal, principal
from agent_platform.extension_contracts import BusinessScope

TENANT = "tenant-service-apps"
SCOPE = BusinessScope(
    tenant_id=TENANT,
    business_id="customer-service",
    workspace_id="support-default",
)
READER = Principal(TENANT, "viewer", "viewer")
ADMIN = Principal(TENANT, "admin", "admin")


def _application_config() -> dict[str, Any]:
    return {
        "name": "购物消费服务应用",
        "description": "订单服务",
        "scenarios": [{"key": "query-orders"}],
        "capabilities": [
            {
                "key": "direct",
                "type": "direct",
                "label": "Direct",
                "config": {"reply": "请提供订单号。"},
            }
        ],
        "channels": [{"key": "web", "name": "官网", "type": "web"}],
    }


class FakeApplicationService:
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
        archived: bool = False,
    ):
        self._record(
            "list",
            tenant=tenant,
            status=status,
            q=q,
            scope=scope,
            archived=archived,
        )
        return {"items": [], "total": 0}

    async def overview(self, tenant: str, *, scope: BusinessScope):
        self._record("overview", tenant=tenant, scope=scope)
        return {"applications": 0}

    async def get(self, tenant: str, key: str, *, scope: BusinessScope):
        self._record("get", tenant=tenant, key=key, scope=scope)
        return {"key": key}

    async def readiness(self, tenant: str, key: str, *, scope: BusinessScope):
        self._record("readiness", tenant=tenant, key=key, scope=scope)
        return {"key": key, "status": "ready", "scenarios": []}

    async def create(self, tenant: str, actor: str, key: str, body: Any, *, scope):
        self._record("create", tenant=tenant, actor=actor, key=key, body=body, scope=scope)
        return {"key": key, "revision": 1}

    async def update(self, tenant: str, actor: str, key: str, body: Any, *, scope):
        self._record("update", tenant=tenant, actor=actor, key=key, body=body, scope=scope)
        return {"key": key, "revision": body.revision + 1}

    async def update_service_catalog(
        self, tenant: str, actor: str, key: str, body: Any, *, scope
    ):
        self._record(
            "update_service_catalog",
            tenant=tenant,
            actor=actor,
            key=key,
            body=body,
            scope=scope,
        )
        return {"key": key, "revision": body.revision + 1}

    async def set_status(self, tenant, actor, key, status, revision, *, scope):
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

    async def archive(self, tenant, actor, key, revision, *, scope):
        self._record(
            "archive",
            tenant=tenant,
            actor=actor,
            key=key,
            revision=revision,
            scope=scope,
        )
        return {"key": key, "archived": True}

    async def restore(self, tenant, actor, key, *, scope):
        self._record("restore", tenant=tenant, actor=actor, key=key, scope=scope)
        return {"key": key, "archived": False}

    async def purge(self, tenant, actor, key, *, scope):
        self._record("purge", tenant=tenant, actor=actor, key=key, scope=scope)
        return {"key": key, "deleted": True}

    async def publish(self, tenant, actor, key, revision, *, scope):
        self._record(
            "publish",
            tenant=tenant,
            actor=actor,
            key=key,
            revision=revision,
            scope=scope,
        )
        return {"key": key, "version": 1}

    async def versions(self, tenant, key, *, scope):
        self._record("versions", tenant=tenant, key=key, scope=scope)
        return {"items": []}

    async def rollback(self, tenant, actor, key, version, revision, *, scope):
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

    async def simulate(self, tenant, actor, key, body, *, scope):
        self._record(
            "simulate",
            tenant=tenant,
            actor=actor,
            key=key,
            body=body,
            scope=scope,
        )
        return {
            "application_key": key,
            "scenario_key": body.scenario_key,
            "trace_id": "trace-1",
        }

    async def traces(self, tenant, key, *, limit, scope):
        self._record("traces", tenant=tenant, key=key, limit=limit, scope=scope)
        return {"items": []}


def _client(applications: FakeApplicationService, user: Principal = READER) -> TestClient:
    app = FastAPI()
    app.state.runtime = SimpleNamespace(
        groups=SimpleNamespace(business=SimpleNamespace(service_apps=applications))
    )

    @app.middleware("http")
    async def attach_scope(request: Request, call_next: Any):
        request.state.business_scope = SCOPE
        return await call_next(request)

    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[principal] = lambda: user
    return TestClient(app)


def test_list_overview_and_get_forward_scope_filters_and_key():
    applications = FakeApplicationService()
    with _client(applications) as client:
        listed = client.get("/api/v1/service-apps", params={"status": "review", "q": "消费"})
        overview = client.get("/api/v1/service-apps/overview")
        detail = client.get("/api/v1/service-apps/consumer-service")
        readiness = client.get("/api/v1/service-apps/consumer-service/readiness")

    assert listed.status_code == 200
    assert overview.status_code == 200
    assert detail.status_code == 200
    assert readiness.status_code == 200
    assert applications.calls["list"][0] == {
        "tenant": TENANT,
        "status": "review",
        "q": "消费",
        "scope": SCOPE,
        "archived": False,
    }
    assert applications.calls["overview"][0]["scope"] == SCOPE
    assert applications.calls["get"][0]["key"] == "consumer-service"
    assert "overview" not in applications.calls.get("get", [{}])[0]
    assert applications.calls["readiness"][0] == {
        "tenant": TENANT,
        "key": "consumer-service",
        "scope": SCOPE,
    }


def test_write_routes_require_admin_and_forward_revisions():
    applications = FakeApplicationService()
    payload = {"key": "consumer-service", "config": _application_config()}
    with _client(applications, READER) as client:
        denied = client.post("/api/v1/service-apps", json=payload)
        denied_archive = client.post(
            "/api/v1/service-apps/consumer-service/archive", json={"revision": 1}
        )
        denied_restore = client.post("/api/v1/service-apps/consumer-service/restore")
        denied_purge = client.delete("/api/v1/service-apps/consumer-service")
    with _client(applications, ADMIN) as client:
        created = client.post("/api/v1/service-apps", json=payload)
        updated = client.put(
            "/api/v1/service-apps/consumer-service",
            json={"config": _application_config(), "revision": 2},
        )
        review = client.post(
            "/api/v1/service-apps/consumer-service/status",
            json={"status": "review", "revision": 3},
        )
        published = client.post(
            "/api/v1/service-apps/consumer-service/publish",
            json={"revision": 4},
        )
        rolled_back = client.post(
            "/api/v1/service-apps/consumer-service/rollback",
            json={"version": 1, "revision": 5},
        )
        archived = client.post(
            "/api/v1/service-apps/consumer-service/archive",
            json={"revision": 7},
        )
        restored = client.post("/api/v1/service-apps/consumer-service/restore")
        purged = client.delete("/api/v1/service-apps/consumer-service")
        catalog = client.put(
            "/api/v1/service-apps/consumer-service/service-catalog",
            json={
                "revision": 6,
                "categories": [
                    {"name": "交易服务", "order": 10},
                    {"name": "售后服务", "order": 20},
                ],
                "category_changes": {"订单服务": "交易服务"},
            },
        )

    assert denied.status_code == 403
    assert denied_archive.status_code == 403
    assert denied_restore.status_code == 403
    assert denied_purge.status_code == 403
    assert created.status_code == 201
    assert updated.status_code == 200
    assert review.status_code == 200
    assert published.status_code == 200
    assert rolled_back.status_code == 200
    assert archived.status_code == 200
    assert restored.status_code == 200
    assert purged.status_code == 200
    assert catalog.status_code == 200
    assert applications.calls["create"][0]["body"].key == "consumer-service"
    assert applications.calls["update"][0]["body"].revision == 2
    assert applications.calls["set_status"][0]["revision"] == 3
    assert applications.calls["publish"][0]["revision"] == 4
    assert applications.calls["rollback"][0] == {
        "tenant": TENANT,
        "actor": "admin",
        "key": "consumer-service",
        "version": 1,
        "revision": 5,
        "scope": SCOPE,
    }
    catalog_call = applications.calls["update_service_catalog"][0]
    assert catalog_call["body"].revision == 6
    assert catalog_call["body"].category_changes == {"订单服务": "交易服务"}
    assert catalog_call["scope"] == SCOPE
    assert applications.calls["archive"][0] == {
        "tenant": TENANT,
        "actor": "admin",
        "key": "consumer-service",
        "revision": 7,
        "scope": SCOPE,
    }
    assert applications.calls["restore"][0] == {
        "tenant": TENANT,
        "actor": "admin",
        "key": "consumer-service",
        "scope": SCOPE,
    }
    assert applications.calls["purge"][0] == {
        "tenant": TENANT,
        "actor": "admin",
        "key": "consumer-service",
        "scope": SCOPE,
    }


def test_service_catalog_write_requires_admin():
    applications = FakeApplicationService()
    payload = {
        "revision": 2,
        "categories": [{"name": "订单服务", "order": 10}],
        "category_changes": {},
    }
    with _client(applications, READER) as client:
        response = client.put(
            "/api/v1/service-apps/consumer-service/service-catalog",
            json=payload,
        )

    assert response.status_code == 403
    assert "update_service_catalog" not in applications.calls


def test_simulate_and_traces_use_application_key_and_snapshot_options():
    applications = FakeApplicationService()
    with _client(applications) as client:
        simulated = client.post(
            "/api/v1/service-apps/consumer-service/simulate",
            json={
                "message": "我的包裹到哪了？",
                "scenario_key": "track-logistics",
                "application_version": 8,
            },
        )
        traces = client.get(
            "/api/v1/service-apps/consumer-service/traces",
            params={"limit": 200},
        )

    assert simulated.status_code == 200
    assert traces.status_code == 200
    call = applications.calls["simulate"][0]
    assert call["key"] == "consumer-service"
    assert call["body"].scenario_key == "track-logistics"
    assert call["body"].application_version == 8
    assert call["scope"] == SCOPE
    assert applications.calls["traces"][0]["limit"] == 200


@pytest.mark.parametrize("status", ["published-typo", "unknown"])
def test_list_rejects_unknown_status(status: str):
    applications = FakeApplicationService()
    with _client(applications) as client:
        response = client.get("/api/v1/service-apps", params={"status": status})

    assert response.status_code == 422
    assert "list" not in applications.calls
