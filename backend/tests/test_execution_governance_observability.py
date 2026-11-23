"""Phase 6-2 T-12 · UT-1~UT-14: governance route units (no PostgreSQL).

Covers Admin-only gating, unified error codes, tenant fail-closed, scope SQL,
pagination, query shapes, RunView/SSE-zero-diff guards and the Secret canary.
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from agent_platform.applications.customer_service import platform_routes as pr
from agent_platform.core_platform.agent_execution.events.diagnostics import (
    ParserDiagnostic,
    ParserDiagnosticSink,
)
from agent_platform.core_platform.agent_runtime.schemas import RunView
from agent_platform.core_platform.platform_services.identity.access import (
    Principal,
    principal,
)
from agent_platform.extension_contracts import BusinessScope

pytestmark = pytest.mark.asyncio

GOV_PATHS = [
    "/observability/execution/fencing-denials",
    "/observability/execution/cleanup-failures",
    "/observability/execution/outbox",
    "/observability/execution/usage-conflicts",
    "/observability/execution/replay-gaps",
    "/observability/execution/parser-diagnostics",
    "/observability/execution/credential-audit",
]
CANARY = "CANARY-SECRET-DO-NOT-LEAK-9f8a7b"


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class _FakeConn:
    def __init__(self, scalars=(), rows=()):
        self._scalars = list(scalars)
        self._rows = list(rows)
        self.calls: list[tuple[str, dict]] = []

    async def scalar(self, statement, params=None):
        self.calls.append((str(statement), dict(params or {})))
        return self._scalars.pop(0) if self._scalars else 0

    async def execute(self, statement, params=None):
        self.calls.append((str(statement), dict(params or {})))
        return _FakeResult(self._rows)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class _FakeEngine:
    def __init__(self, conn: _FakeConn):
        self.conn = conn

    def connect(self):
        return self.conn


def _build_app(monkeypatch, conn: _FakeConn, role: str = "admin", tenant: str = "tenant-a"):
    monkeypatch.setattr(pr, "runtime", lambda request: SimpleNamespace(engine=_FakeEngine(conn)))
    app = FastAPI()
    app.include_router(pr.router)

    async def fake_principal():
        return Principal(tenant, role, "tester", business_id="customer-service", workspace_id="w1")

    app.dependency_overrides[principal] = fake_principal

    @app.middleware("http")
    async def bind_scope(request, call_next):
        request.state.business_scope = BusinessScope(
            tenant_id=tenant, business_id="customer-service", workspace_id="w1"
        )
        return await call_next(request)

    return app


async def _get(app, path, **params):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.get(path, params=params)


# --- UT-1 / UT-2: route registration and Admin-only gating ------------------


async def test_ut1_all_governance_routes_registered():
    paths = {route.path for route in pr.router.routes if route.path in GOV_PATHS}
    assert paths == set(GOV_PATHS)
    assert all(
        "GET" in next(r for r in pr.router.routes if r.path == path).methods for path in GOV_PATHS
    )


async def test_ut2_non_admin_is_denied_on_every_endpoint(monkeypatch):
    app = _build_app(monkeypatch, _FakeConn(), role="reader")
    for path in GOV_PATHS:
        response = await _get(app, path)
        assert response.status_code == 403, path
        assert response.json()["detail"] == "insufficient_role"


# --- UT-3 ~ UT-5: unified 400 error codes ----------------------------------


async def test_ut3_invalid_pagination_returns_400():
    for page, size in (("0", None), ("abc", None), (None, "0"), (None, "101")):
        with pytest.raises(HTTPException) as exc:
            pr._gov_pagination(page, size)
        assert exc.value.status_code == 400
        assert exc.value.detail == "invalid_pagination"
    assert pr._gov_pagination(None, None) == (1, 20, 0)
    assert pr._gov_pagination("3", "5") == (3, 5, 10)


async def test_ut4_invalid_time_filter_returns_400():
    with pytest.raises(HTTPException) as exc:
        pr._gov_time("not-a-date")
    assert exc.value.status_code == 400 and exc.value.detail == "invalid_time_range"
    parsed = pr._gov_time("2026-01-02T03:04:05Z")
    assert parsed is not None and parsed.tzinfo is not None


async def test_ut5_invalid_enum_filter_returns_400(monkeypatch):
    with pytest.raises(HTTPException) as exc:
        pr._gov_choice("bogus", pr._GOV_PARSER_CATEGORIES)
    assert exc.value.status_code == 400 and exc.value.detail == "invalid_filter"
    app = _build_app(monkeypatch, _FakeConn())
    response = await _get(app, "/observability/execution/parser-diagnostics", category="bogus")
    assert response.status_code == 400


# --- UT-6 ~ UT-8: tenant/scope predicates ----------------------------------


async def test_ut6_cross_tenant_request_fails_closed():
    clause, params = pr._gov_tenant_clause("tenant-a", "tenant-b", "r")
    assert clause == "1=0" and params == {}
    clause, params = pr._gov_tenant_clause("tenant-a", "tenant-a", "r")
    assert "r.tenant_id=:gov_tenant" in clause and params["gov_tenant"] == "tenant-a"


async def test_ut7_orphan_tenant_clause_allows_deployment_level():
    clause, params = pr._gov_tenant_clause("tenant-a", None, "r", allow_null=True)
    assert "r.id IS NULL" in clause and "r.tenant_id=:gov_tenant" in clause
    assert params["gov_tenant"] == "tenant-a"


async def test_ut8_scope_clause_uses_resolve_scope_and_scope_predicate():
    request = SimpleNamespace(
        state=SimpleNamespace(
            business_scope=BusinessScope(
                tenant_id="tenant-a", business_id="customer-service", workspace_id="w1"
            )
        )
    )
    clause, params = pr._gov_scope_clause(request, "tenant-a")
    assert "r.business_id=:scope_business" in clause
    assert "r.workspace_id=:scope_workspace" in clause
    assert params["scope_business"] == "customer-service"
    assert params["scope_workspace"] == "w1"


# --- UT-9 ~ UT-13: endpoint query shapes and response mapping --------------


async def test_ut9_fencing_denials_join_and_orphan_label(monkeypatch):
    run_id = uuid4()
    row = {
        "run_id": run_id,
        "operation": "append",
        "reason": "stale_epoch",
        "stale_owner": uuid4(),
        "stale_lease_epoch": 2,
        "current_owner": uuid4(),
        "current_lease_epoch": 3,
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
        "tenant_id": None,
        "business_id": None,
        "workspace_id": None,
    }
    conn = _FakeConn(scalars=[1], rows=[row])
    app = _build_app(monkeypatch, conn)
    response = await _get(app, GOV_PATHS[0], reason="stale_epoch")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1 and body["page"] == 1 and body["page_size"] == 20
    assert body["items"][0]["deployment_level"] is True
    assert body["items"][0]["scope"] is None
    joined = any("LEFT JOIN runtime_runs" in sql for sql, _ in conn.calls)
    assert joined
    assert not any(CANARY in sql for sql, _ in conn.calls)


async def test_ut10_cleanup_failures_two_categories_and_runview_zero_diff(monkeypatch):
    before = set(RunView.model_fields)
    row = {
        "id": uuid4(),
        "cleanup_status": "failed",
        "cleanup_updated_at": datetime(2026, 1, 1, tzinfo=UTC),
        "cancel_requested_at": datetime(2026, 1, 1, tzinfo=UTC),
        "cancel_confirmed_at": None,
        "tenant_id": "tenant-a",
        "business_id": "customer-service",
        "workspace_id": "w1",
    }
    conn = _FakeConn(scalars=[1], rows=[row])
    app = _build_app(monkeypatch, conn)
    response = await _get(app, GOV_PATHS[1])
    assert response.status_code == 200
    assert response.json()["items"][0]["category"] in {"failed", "unconfirmed_cancel"}
    assert set(RunView.model_fields) == before
    assert "cleanup_status" not in RunView.model_fields
    assert "cancel_confirmed_at" not in RunView.model_fields


async def test_ut11_outbox_metrics_without_publish_side_effect(monkeypatch):
    conn = _FakeConn(
        scalars=[2, datetime(2026, 1, 1, tzinfo=UTC), 3600.0, 3, 1],
        rows=[
            {
                "run_id": uuid4(),
                "seq": 1,
                "attempts": 2,
                "available_at": datetime(2026, 1, 1, tzinfo=UTC),
                "last_error": "publisher_rejected",
            }
        ],
    )
    app = _build_app(monkeypatch, conn)
    response = await _get(app, GOV_PATHS[2])
    assert response.status_code == 200
    body = response.json()
    assert body["pending_count"] == 2
    assert body["stall_seconds"] == 3600.0
    assert body["published_24h"] == 3
    assert body["total"] == 1
    assert body["last_errors"][0]["last_error"] == "publisher_rejected"
    assert not any("UPDATE runtime_event_outbox" in sql for sql, _ in conn.calls)


async def test_ut12_usage_conflicts_kind_and_tenant_filter(monkeypatch):
    row = {
        "run_id": uuid4(),
        "tenant_id": "tenant-a",
        "source": "engine_native",
        "source_event_id": "evt-1",
        "supersedes_id": uuid4(),
        "usage": {"tokens": 12},
        "cost": "0.5",
        "is_estimate": False,
        "kind": "chain",
    }
    conn = _FakeConn(scalars=[1], rows=[row])
    app = _build_app(monkeypatch, conn)
    response = await _get(app, GOV_PATHS[3], kind="chain")
    assert response.status_code == 200
    body = response.json()
    assert body["items"][0]["kind"] == "chain"
    assert all("u.tenant_id=:gov_tenant" in sql for sql, _ in conn.calls)


async def test_ut13_credential_audit_secret_free(monkeypatch):
    row = {
        "id": uuid4(),
        "credential_ref": uuid4(),
        "action": "revoked",
        "outcome": "success",
        "reason_code": "operator_revoke",
        "actor": "admin",
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
        "tenant_id": "tenant-a",
    }
    conn = _FakeConn(scalars=[1], rows=[row])
    app = _build_app(monkeypatch, conn)
    response = await _get(app, GOV_PATHS[6], action="revoked")
    assert response.status_code == 200
    text = response.text
    assert CANARY not in text and "encrypted_secret" not in text and "secret" not in text.lower()
    assert response.json()["items"][0]["action"] == "revoked"


# --- UT-14: parser/replay allowlisted columns and canary -------------------


async def test_ut14_replay_and_parser_are_allowlisted_and_canary_free(monkeypatch):
    replay = {
        "id": uuid4(),
        "run_id": uuid4(),
        "requested_cursor_seq": 1,
        "retention_floor_seq": 5,
        "reason_code": "cursor_below_floor",
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
        "tenant_id": "tenant-a",
        "business_id": "customer-service",
        "workspace_id": "w1",
    }
    conn = _FakeConn(scalars=[1], rows=[replay])
    app = _build_app(monkeypatch, conn)
    response = await _get(app, GOV_PATHS[4])
    assert response.status_code == 200
    assert response.json()["items"][0]["reason_code"] == "cursor_below_floor"

    parser_row = {
        "bucket_start": datetime(2026, 1, 1, tzinfo=UTC),
        "category": "malformed",
        "reason_code": "malformed:codex:v1",
        "count": 2,
        "tenant_id": "tenant-a",
        "run_id": uuid4(),
        "sample": CANARY,
    }
    conn2 = _FakeConn(scalars=[1], rows=[parser_row])
    app2 = _build_app(monkeypatch, conn2)
    response2 = await _get(app2, GOV_PATHS[5])
    assert response2.status_code == 200
    assert CANARY not in response2.text
    assert set(response2.json()["items"][0]) == {
        "bucket_start",
        "category",
        "reason_code",
        "count",
        "tenant_id",
        "run_id",
    }
    assert not any("sample" in sql.lower() for sql, _ in conn2.calls)


async def test_ut14b_sink_never_retains_raw_sample():
    sink = ParserDiagnosticSink(clock=lambda: 1000.0)
    diagnostic = ParserDiagnostic(
        category="unknown_type",
        engine_id="codex",
        protocol_id="v1",
        adapter_version=None,
        run_id=None,
        native_event_id="evt-1",
        location=None,
        sample=CANARY,
        created_at_posix=1000.0,
    )
    sink.accept(diagnostic, tenant_id="tenant-a")
    rows = sink.drain()
    assert len(rows) == 1
    assert CANARY not in str(rows)
    assert rows[0].reason_code == "unknown_type:codex:v1"
