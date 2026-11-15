"""Phase 3 execution-config-flags endpoint tests (03 §7.4, 08 R-25).

Case IDs: P3-UT-26 (strict DTO + zero side effects) and the backend-decodable
part of P3-IT-20 (auth surface, tenant invariance, OpenAPI, no leak fields).

These run at the pure ASGI level: the endpoint must only read ``settings``, so
no PostgreSQL, no composition root and no Phase 3 subsystem are required. The
harness mounts the real ``platform_routes.router`` and the real ``principal``
dependency, but wires a tripwire runtime that explodes on anything the handler
is not allowed to touch.
"""

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from agent_platform.applications.customer_service.platform_routes import router
from agent_platform.core_platform.agent_execution.adapters.react.adapter import ReactAdapter
from agent_platform.core_platform.agent_execution.capability.resolver import CapabilityResolver
from agent_platform.core_platform.agent_execution.orchestration.orchestrator import (
    ExecutionOrchestrator,
)
from agent_platform.core_platform.platform_services.platform_settings.settings import Settings

FLAG_FIELDS = ("execution_phase3_enabled", "execution_orchestrator_enabled")
ADMIN_TOKEN = "flags-admin"
OPERATOR_TOKEN = "flags-operator"
VIEWER_TOKEN = "flags-viewer"

# Field names the flags response must never carry (03 §7.4 security boundary).
FORBIDDEN_KEY_MARKERS = (
    "id",
    "digest",
    "policy",
    "probe",
    "schema_version",
    "snapshot",
    "cache",
    "reason",
    "effective",
    "tenant",
    "actor",
)


def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "_env_file": None,
        "tenant_id": "tenant-flags-" + str(uuid4()),
        "embedded_worker": False,
        "embedded_channel_worker": False,
        "model_backend": "demo",
        "api_token": SecretStr(ADMIN_TOKEN),
        "operator_api_token": SecretStr(OPERATOR_TOKEN),
        "viewer_api_token": SecretStr(VIEWER_TOKEN),
        "execution_phase3_enabled": False,
        "execution_orchestrator_enabled": False,
    }
    base.update(overrides)
    return Settings(**base)


class _RecordingSettings:
    """Delegates every attribute read to a real Settings, recording the names."""

    def __init__(self, target: Settings, log: list[str]) -> None:
        object.__setattr__(self, "_target", target)
        object.__setattr__(self, "_log", log)

    def __getattr__(self, name: str) -> Any:
        self._log.append(name)
        return getattr(self._target, name)


class _TripwireRuntime:
    """Runtime facade where only ``.settings`` may be touched.

    P3-UT-26's zero-side-effect clause: the handler must read exactly the two
    deployment booleans and nothing else — no capability caches, probes,
    adapters, stores or audit ports. Any attribute other than ``settings``
    exploding here is the assertion.
    """

    def __init__(self, settings: Settings, settings_reads: list[str]) -> None:
        object.__setattr__(self, "_settings", _RecordingSettings(settings, settings_reads))

    def __getattr__(self, name: str) -> Any:
        if name == "settings":
            return self._settings
        raise AssertionError(f"execution-config-flags touched runtime.{name!r} (zero-side-effect)")


class _TripwireGroups:
    """Only ``.runtime`` may be reached; ``.business``/``.tools`` must not."""

    def __init__(self, runtime: _TripwireRuntime) -> None:
        object.__setattr__(self, "_runtime", runtime)

    def __getattr__(self, name: str) -> Any:
        if name == "runtime":
            return self._runtime
        raise AssertionError(f"execution-config-flags touched groups.{name!r} (zero-side-effect)")


class _Calls:
    """Counts Phase 3 subsystem instantiations; any hit violates P3-UT-26."""

    def __init__(self) -> None:
        self.adapters = 0
        self.resolvers = 0
        self.orchestrators = 0


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> _Calls:
    counters = _Calls()

    def _wrap(cls: type, attribute: str, bump) -> None:
        original = getattr(cls, attribute)

        def patched(self, *args, **kwargs):
            bump(counters)
            return original(self, *args, **kwargs)

        monkeypatch.setattr(cls, attribute, patched)

    _wrap(ReactAdapter, "__init__", lambda c: setattr(c, "adapters", c.adapters + 1))
    _wrap(CapabilityResolver, "__init__", lambda c: setattr(c, "resolvers", c.resolvers + 1))
    _wrap(
        ExecutionOrchestrator,
        "__init__",
        lambda c: setattr(c, "orchestrators", c.orchestrators + 1),
    )
    return counters


def _client(settings: Settings) -> tuple[TestClient, list[str]]:
    """Mount the real router with the real auth dependency; no DB, no runtime."""
    reads: list[str] = []
    app = FastAPI()
    app.state.settings = settings
    app.state.runtime = SimpleNamespace(groups=_TripwireGroups(_TripwireRuntime(settings, reads)))
    app.include_router(router, prefix="/api/v1")
    return TestClient(app), reads


def _get(client: TestClient, token: str | None = None) -> Any:
    headers = {"Authorization": "Bearer " + token} if token else {}
    return client.get("/api/v1/agents/execution-config-flags", headers=headers)


# ---------------------------------------------------------------------------
# P3-UT-26: strict DTO shape
# ---------------------------------------------------------------------------


def test_flags_response_is_exactly_two_bools() -> None:
    client, _ = _client(_settings())
    response = _get(client, ADMIN_TOKEN)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == set(FLAG_FIELDS)
    assert isinstance(body["execution_phase3_enabled"], bool)
    assert isinstance(body["execution_orchestrator_enabled"], bool)


def test_flags_dto_is_strict_extra_forbid_and_frozen() -> None:
    """The response is a strict DTO: extra=forbid rejects unknown fields and
    frozen rejects mutation (03 §7.4). Discovered through the registered route
    so an unregistered endpoint fails as "route missing", not as an import error."""
    route = next(
        (r for r in router.routes if getattr(r, "path", None) == "/agents/execution-config-flags"),
        None,
    )
    assert route is not None, (
        "GET /agents/execution-config-flags is not registered on platform_routes"
    )
    model = route.response_model
    assert model is not None, "flags route must declare a strict response_model, not a bare dict"
    with pytest.raises(ValidationError):
        model.model_validate(
            {"execution_phase3_enabled": False, "execution_orchestrator_enabled": False, "extra": 1}
        )
    instance = model.model_validate(
        {"execution_phase3_enabled": False, "execution_orchestrator_enabled": False}
    )
    with pytest.raises(ValidationError):
        instance.execution_phase3_enabled = True


# ---------------------------------------------------------------------------
# P3-UT-26: FR-9 four-state matrix, verbatim values, never a domain error
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("phase3", "orchestrator"),
    [(False, False), (False, True), (True, False), (True, True)],
)
def test_all_four_states_return_200_with_real_values(phase3: bool, orchestrator: bool) -> None:
    """All four FR-9 states answer with the deployed values — including the
    on+orchestrator-off misconfiguration and the all-off rollback state that
    motivated the endpoint. The contract never answers execution_* domain
    errors here."""
    settings = _settings(
        execution_phase3_enabled=phase3, execution_orchestrator_enabled=orchestrator
    )
    client, _ = _client(settings)
    response = _get(client, ADMIN_TOKEN)
    assert response.status_code == 200, response.text
    assert response.json() == {
        "execution_phase3_enabled": phase3,
        "execution_orchestrator_enabled": orchestrator,
    }


def test_flags_track_settings_mutations() -> None:
    """Values are read per-request and match settings verbatim."""
    settings = _settings()
    client, _ = _client(settings)
    assert _get(client, ADMIN_TOKEN).json() == {
        "execution_phase3_enabled": False,
        "execution_orchestrator_enabled": False,
    }
    settings.execution_phase3_enabled = True
    settings.execution_orchestrator_enabled = True
    assert _get(client, ADMIN_TOKEN).json() == {
        "execution_phase3_enabled": True,
        "execution_orchestrator_enabled": True,
    }


# ---------------------------------------------------------------------------
# P3-UT-26: zero side effects
# ---------------------------------------------------------------------------


def test_flags_read_only_two_setting_booleans(calls: _Calls) -> None:
    settings = _settings(execution_phase3_enabled=True, execution_orchestrator_enabled=False)
    client, reads = _client(settings)
    response = _get(client, VIEWER_TOKEN)
    assert response.status_code == 200, response.text
    # Only the two flag names may be read off settings (no TTLs, no tokens,
    # no execution_capability_* tuning, no tenant_id).
    assert set(reads) == set(FLAG_FIELDS)
    # No Phase 3 subsystem instantiation, probe or cache construction.
    assert (calls.adapters, calls.resolvers, calls.orchestrators) == (0, 0, 0)


# ---------------------------------------------------------------------------
# P3-IT-20: authentication surface (same internal management plane as preview)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("authorization", [None, "Bearer bad", "Basic cm9vdA=="])
def test_unauthenticated_or_bad_token_is_401_or_403(authorization: str | None) -> None:
    client, _ = _client(_settings())
    headers = {"Authorization": authorization} if authorization else {}
    response = client.get("/api/v1/agents/execution-config-flags", headers=headers)
    assert response.status_code in (401, 403), response.text


def test_reader_operator_and_admin_can_all_read() -> None:
    settings = _settings(execution_phase3_enabled=True, execution_orchestrator_enabled=True)
    client, _ = _client(settings)
    expected = {"execution_phase3_enabled": True, "execution_orchestrator_enabled": True}
    # Reader (viewer) must be able to read: the UI gates on it for viewers too.
    for token in (VIEWER_TOKEN, OPERATOR_TOKEN, ADMIN_TOKEN):
        response = _get(client, token)
        assert response.status_code == 200, response.text
        assert response.json() == expected


def test_flags_are_tenant_agnostic() -> None:
    """No per-tenant data plane: the same deployment answers identically for
    every tenant and every role."""
    a, _ = _client(_settings(execution_phase3_enabled=True, execution_orchestrator_enabled=False))
    b, _ = _client(_settings(execution_phase3_enabled=True, execution_orchestrator_enabled=False))
    assert a.app.state.settings.tenant_id != b.app.state.settings.tenant_id
    assert _get(a, ADMIN_TOKEN).json() == _get(b, VIEWER_TOKEN).json()


# ---------------------------------------------------------------------------
# P3-IT-20: OpenAPI inclusion and leak-free whitelist
# ---------------------------------------------------------------------------


def test_openapi_contains_flags_route_with_two_property_schema() -> None:
    client, _ = _client(_settings())
    schema = client.get("/openapi.json").json()
    operation = schema["paths"]["/api/v1/agents/execution-config-flags"]["get"]
    responses = operation["responses"]["200"]["content"]["application/json"]["schema"]
    while "$ref" in responses:
        name = responses["$ref"].split("/")[-1]
        responses = schema["components"]["schemas"][name]
    assert responses["type"] == "object"
    assert set(responses["properties"]) == set(FLAG_FIELDS)
    assert all(p["type"] == "boolean" for p in responses["properties"].values())


def _walk_keys(node: Any) -> set[str]:
    if isinstance(node, dict):
        return {str(k) for k in node} | set().union(*(_walk_keys(v) for v in node.values()))
    if isinstance(node, list):
        return set().union(*(_walk_keys(v) for v in node)) if node else set()
    return set()


def test_response_body_carries_no_internal_fields() -> None:
    settings = _settings(execution_phase3_enabled=True, execution_orchestrator_enabled=True)
    client, _ = _client(settings)
    body = _get(client, ADMIN_TOKEN).json()
    leaked = {k for k in _walk_keys(body) if k not in FLAG_FIELDS}
    assert not leaked, f"flags response leaked non-whitelist keys: {leaked}"
    text = str(body).lower()
    for marker in ("secret", "token", "host", "path", "tenant"):
        assert marker not in text
