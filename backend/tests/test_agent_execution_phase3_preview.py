"""Phase 3 T8: ``POST /agents/execution-preview`` and forged-field security audit.

Case IDs (04): P3-UT-11/12/22 (preview half), P3-IT-04/05/11/17,
05 A5/A9 + C1/C3/C4, 08 R-12/R-13/R-21/R-25, 03 §7.1-§7.3.

Two harnesses, matching the judgement each one can actually make:

* the non-PostgreSQL harness mounts the real ``platform_routes.router`` and the
  real ``principal`` dependency over an in-memory composition built by
  ``runtime_composition._build_execution_capability_subsystem`` with scripted
  trusted ports (R-17 live revision reads, probe/policy failures, denial
  narrowing). This is where per-field forged rejection, trusted-context
  extraction, reason-code passthrough, the response whitelist and the
  preview-then-policy-change sequence live: none of them needs a database, and
  the policy-revision story requires fake providers that production forbids;
* the PostgreSQL harness runs the real ``create_app`` (production ports, real
  warmer, real AgentService, real audit table). This is where P3-IT-04/05 prove
  the audit rows are written and leak nothing, where preview provably creates
  no Run/Conversation/snapshot, and where the OpenAPI surface is asserted.

Discipline under test (03 §7.1-§7.3, R-12): preview is read-only (no
factory/Adapter, no Run/Conversation, no snapshot, no decision cached as Run
authorization), shares the T7-wired resolver instance with the Run path
(P3-IT-19 preview half), and tenant/actor/business/workspace come only from
the authenticated context (P3-UT-12).
"""

import dataclasses
import json
import os
import re
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from pydantic import SecretStr
from test_agent_execution_phase3_wiring import (
    REACT_DECLARED,
    build_registry,
)

from agent_platform.applications.customer_service.platform_routes import router
from agent_platform.applications.platform_runtime import runtime_composition
from agent_platform.applications.platform_runtime.react_adapter_factory import ReactAdapterFactory
from agent_platform.core_platform.agent_execution.capability.ports import (
    PolicyRevisionScope,
    ProbeContext,
)
from agent_platform.core_platform.agent_execution.capability.production import (
    DeclarationDerivedDeploymentProbe,
    NoTrustedWorkspaceGeneration,
)
from agent_platform.core_platform.agent_execution.capability.resolver import (
    CapabilityResolution,
    CapabilityResolutionRequest,
)
from agent_platform.core_platform.agent_execution.contracts.capabilities import (
    CAPABILITY_ORDER,
    NO_EXECUTION_RESTRICTIONS,
    EffectiveCapabilities,
    EffectiveCapabilityDecision,
    PolicyDecisionSet,
    PolicyLayerDecision,
    PolicyLayerVersion,
    effective_capability_views,
)
from agent_platform.core_platform.agent_execution.contracts.config import ReactConfig
from agent_platform.core_platform.platform_services.persistence.store import DomainError
from agent_platform.core_platform.platform_services.platform_settings.settings import Settings
from agent_platform.extension_contracts import DEFAULT_BUSINESS_ID, DEFAULT_WORKSPACE_ID

PREVIEW_PATH = "/api/v1/agents/execution-preview"
FLAGS_PATH = "/api/v1/agents/execution-config-flags"
ADMIN_TOKEN = "preview-admin"
OPERATOR_TOKEN = "preview-operator"
VIEWER_TOKEN = "preview-viewer"

# A planted marker used as a *value* of rejected fields. It must never appear in
# the 422 response, in an audit row, or in captured logs (P3-IT-04 / C3).
SECRET_MARKER = "PLANTED-SECRET-MARKER-9d1c"

VALID_CONFIG: dict[str, Any] = {
    "system_prompt": "Answer briefly.",
    "engine": {"engine_id": "react", "protocol_id": "native", "adapter_version": "v1"},
    "react": {"model_profile_id": None, "model_profile_version": None, "max_model_rounds": 6},
    "disabled_capabilities": [],
}

# --------------------------------------------------------------------------- #
# non-PostgreSQL harness: real router + in-memory composition                  #
# --------------------------------------------------------------------------- #


class _RecordingResolver:
    """Stand-in that records the trusted DTO the route assembled."""

    def __init__(self, resolution: CapabilityResolution) -> None:
        self.calls: list[CapabilityResolutionRequest] = []
        self._resolution = resolution

    async def resolve(self, request: CapabilityResolutionRequest) -> CapabilityResolution:
        self.calls.append(request)
        return self._resolution

    async def warm(self, request: CapabilityResolutionRequest) -> bool:
        self.calls.append(request)
        return True


class _CountingProbe:
    """Wraps the production probe and counts port invocations."""

    def __init__(self, inner: DeclarationDerivedDeploymentProbe) -> None:
        self.inner = inner
        self.calls = 0

    async def probe(self, context: ProbeContext):
        self.calls += 1
        return await self.inner.probe(context)

    def deployment_digest(self, context):
        return self.inner.deployment_digest(context)


class _ScriptedPolicyProvider:
    """Fake tenant policy source with a live, controllable revision (R-17)."""

    def __init__(self, *, policy_version: str = "v1") -> None:
        self.revision = 0
        self.denied_platform: set[str] = set()
        self.fail_revision = False
        self.policy_version = policy_version
        self.resolve_calls = 0

    def current_revision(self, scope: PolicyRevisionScope) -> int:
        if self.fail_revision:
            raise RuntimeError("policy source outage")
        return self.revision

    async def resolve(self, context):
        from agent_platform.core_platform.agent_execution.capability.production import (
            PHASE3_PLATFORM_CAPABILITY_ALLOWLIST,
        )
        from agent_platform.core_platform.agent_execution.contracts.capabilities import (
            CapabilityPolicy,
        )

        self.resolve_calls += 1
        disabled = set(context.disabled_capabilities)
        decisions = []
        for name in CAPABILITY_ORDER:
            platform_allowed = name in PHASE3_PLATFORM_CAPABILITY_ALLOWLIST and (
                name not in self.denied_platform
            )
            agent_allowed = name not in disabled
            decisions.append(
                CapabilityPolicy(
                    name=name,
                    layers=(
                        PolicyLayerDecision(
                            layer="platform",
                            allowed=platform_allowed,
                            source="scripted-test",
                            reason_code="allowed" if platform_allowed else "platform_denied",
                        ),
                        PolicyLayerDecision(
                            layer="tenant",
                            allowed=True,
                            source="scripted-test",
                            reason_code="allowed",
                        ),
                        PolicyLayerDecision(
                            layer="agent",
                            allowed=agent_allowed,
                            source="scripted-test",
                            reason_code="allowed" if agent_allowed else "agent_disabled",
                        ),
                        PolicyLayerDecision(
                            layer="execution",
                            allowed=True,
                            source="scripted-test",
                            reason_code="allowed",
                        ),
                    ),
                )
            )
        return PolicyDecisionSet(
            policy_provider_id=context.policy_provider_id,
            policy_version=context.policy_version,
            policy_revision=context.policy_revision,
            resolved_at=datetime.now(UTC),
            layer_versions=tuple(
                PolicyLayerVersion(
                    layer=layer,
                    version="v1",
                    revision=context.policy_revision,
                )
                for layer in ("platform", "tenant", "agent", "execution")
            ),
            decisions=tuple(decisions),
        )


class _FakeAgentService:
    """AgentService seam: returns one canned row or raises the domain 404."""

    def __init__(self, row: dict | None = None) -> None:
        self.row = row
        self.calls: list[tuple[str, Any]] = []

    async def get(self, tenant, aid):
        self.calls.append((tenant, aid))
        if self.row is None:
            raise DomainError("agent_not_found", 404)
        return dict(self.row)


def _fresh_resolution(**updates) -> CapabilityResolution:
    """A cold fail-closed resolution shaped like the resolver's own output."""
    declared_true = tuple(name for name in CAPABILITY_ORDER if getattr(REACT_DECLARED, name))
    items = tuple(
        EffectiveCapabilityDecision(name=name, effective=False, reason_code="probe_unavailable")
        for name in CAPABILITY_ORDER
    )
    effective = EffectiveCapabilities(
        engine_id="react",
        protocol_id="native",
        adapter_version="v1",
        tenant_id="local",
        declaration_digest="0" * 64,
        probe_id="react-probe",
        probe_version="v1",
        policy_provider_id="react-policy",
        policy_version="v1",
        policy_revision=0,
        items=items,
        required_capabilities_missing=declared_true,
    ).model_copy(update=updates)
    from agent_platform.core_platform.agent_execution.contracts.capabilities import (
        DeclaredCapabilities,
    )

    return CapabilityResolution(
        declared=DeclaredCapabilities(
            engine_id="react",
            protocol_id="native",
            adapter_version="v1",
            declaration_schema_version="v1",
            declaration_digest="0" * 64,
            capabilities=REACT_DECLARED,
        ),
        available=None,
        policy=None,
        effective=effective,
        availability_status="cold",
        policy_status="cold",
    )


def preview_settings(**overrides) -> Settings:
    base: dict[str, Any] = {
        "tenant_id": "tenant-A-" + str(uuid4()),
        "embedded_worker": False,
        "embedded_channel_worker": False,
        "model_backend": "demo",
        "api_token": SecretStr(ADMIN_TOKEN),
        "operator_api_token": SecretStr(OPERATOR_TOKEN),
        "viewer_api_token": SecretStr(VIEWER_TOKEN),
        "execution_phase3_enabled": True,
        "execution_orchestrator_enabled": True,
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)


def _client(
    app,
    token: str = ADMIN_TOKEN,
):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": "Bearer " + token},
    )


class Harness:
    """One in-memory composition behind the real router (no DB)."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        resolution: CapabilityResolution | None = None,
        agent_row: dict | None = None,
        policy_provider: _ScriptedPolicyProvider | None = None,
        real_resolver: bool = False,
        workspace_scope: tuple[str, str] = (DEFAULT_BUSINESS_ID, DEFAULT_WORKSPACE_ID),
    ) -> None:
        self.settings = settings or preview_settings()
        self.registry = build_registry()
        self.probe_inner = DeclarationDerivedDeploymentProbe(
            registry=self.registry, clock=lambda: 1_800_000_000.0
        )
        self.probe = _CountingProbe(self.probe_inner)
        self.policy_provider = policy_provider or _ScriptedPolicyProvider()
        ports = runtime_composition.ExecutionCapabilityPorts(
            probe=self.probe,
            policy_provider=self.policy_provider,
            workspace_port=NoTrustedWorkspaceGeneration(),
        )
        self.subsystem = runtime_composition._build_execution_capability_subsystem(
            self.settings,
            self.registry,
            ports=ports,
            barrier=_NoBarrier(),
        )
        self.agents = _FakeAgentService(agent_row)
        self.workspace_scope = workspace_scope
        if self.subsystem is None:
            # Phase 3 off: composition constructs no subsystem at all, which is
            # itself the assertion the off-state test makes.
            self.resolver = None
        elif resolution is not None or not real_resolver:
            recorder = _RecordingResolver(resolution or _fresh_resolution())
            self.resolver = recorder
            self.subsystem = dataclasses.replace(self.subsystem, resolver=recorder)
        else:
            self.resolver = self.subsystem.resolver
        self.app = _build_asgi_app(self.settings, self.subsystem, self.agents, workspace_scope)

    def request_for(
        self,
        *,
        agent_id: UUID | None = None,
        published_version: int | None = None,
        disabled: tuple[str, ...] = (),
    ) -> CapabilityResolutionRequest:
        business_id, workspace_id = self.workspace_scope
        return CapabilityResolutionRequest(
            engine_id="react",
            protocol_id="native",
            adapter_version="v1",
            tenant_id=self.settings.tenant_id,
            business_scope=business_id,
            workspace_id=workspace_id,
            agent_id=agent_id,
            agent_published_version=published_version,
            disabled_capabilities=disabled,
            execution_restriction_digest=NO_EXECUTION_RESTRICTIONS,
        )

    async def warm_for(self, **kwargs) -> None:
        await self.subsystem.resolver.warm(self.request_for(**kwargs))

    async def wait_idle(self) -> None:
        await self.subsystem.resolver.wait_idle()


class _NoBarrier:
    async def write(self, **kwargs):  # pragma: no cover - preview must not call
        raise AssertionError("preview must never touch a snapshot barrier")


def _build_asgi_app(
    settings: Settings,
    subsystem,
    agents: _FakeAgentService,
    workspace_scope: tuple[str, str],
):
    from fastapi import FastAPI, Request
    from fastapi.exceptions import RequestValidationError
    from fastapi.responses import JSONResponse

    from agent_platform.applications.application_factory import request_validation_handler
    from agent_platform.core_platform.platform_services.persistence.store import DomainError
    from agent_platform.extension_contracts import BusinessScope

    app = FastAPI()
    # The production 422 face, sanitization and all (03 §7.3): a bare FastAPI
    # default handler would echo ``input`` values, which is exactly what C3
    # forbids, so the tests must run through the real handler.
    app.exception_handler(RequestValidationError)(request_validation_handler)

    @app.exception_handler(DomainError)
    async def _domain_error(request: Request, exc: DomainError):
        # Mirrors the production handler so stable domain codes answer here.
        return JSONResponse(status_code=exc.status, content={"detail": exc.code})

    @app.middleware("http")
    async def _bind_scope(request: Request, call_next):
        request.state.business_scope = BusinessScope(
            tenant_id=settings.tenant_id,
            business_id=workspace_scope[0],
            workspace_id=workspace_scope[1],
        )
        return await call_next(request)

    app.state.settings = settings
    app.state.runtime = SimpleNamespace(
        groups=SimpleNamespace(
            runtime=SimpleNamespace(settings=settings, engine=None),
            business=SimpleNamespace(agents=agents),
            tools=None,
            application=None,
        ),
        execution_subsystem=subsystem,
    )
    app.include_router(router, prefix="/api/v1")
    return app


async def _post(client, payload: dict, path: str = PREVIEW_PATH):
    return await client.post(path, json=payload)


# --------------------------------------------------------------------------- #
# P3-UT-11/12: forged fields rejected, never ignored (03 §7.1)                  #
# --------------------------------------------------------------------------- #

# (where to plant the forged key, key name) — every name listed by 03 §7.1 and
# FR-5, plus unknown fields and the trusted-context names.
FORGED_PLANTINGS: list[tuple[str, str]] = [
    ("root", "declared"),
    ("root", "available"),
    ("root", "effective"),
    ("root", "effective_capabilities"),
    ("root", "policy"),
    ("root", "policy_version"),
    ("root", "policy_revision"),
    ("root", "probe"),
    ("root", "probe_id"),
    ("root", "tenant_id"),
    ("root", "actor"),
    ("root", "business_id"),
    ("root", "workspace_id"),
    ("root", "engine_capabilities"),
    ("root", "snapshot"),
    ("config", "declared"),
    ("config", "available"),
    ("config", "effective"),
    ("config", "effective_capabilities"),
    ("config", "policy"),
    ("config", "policy_version"),
    ("config", "probe"),
    ("config", "tenant_id"),
    ("config", "actor"),
    ("config.engine", "deployment_identity"),
    ("config.engine", "probe"),
    ("config.react", "policy"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("place", "key"), FORGED_PLANTINGS)
async def test_forged_field_is_rejected_not_ignored(place: str, key: str) -> None:
    """422 with a locatable field path; the request never reaches the resolver."""
    harness = Harness()
    payload: dict[str, Any] = {"agent_id": None, "config": json.loads(json.dumps(VALID_CONFIG))}
    if place == "root":
        payload[key] = SECRET_MARKER
    elif place == "config":
        payload["config"][key] = SECRET_MARKER
    elif place == "config.engine":
        payload["config"]["engine"][key] = SECRET_MARKER
    elif place == "config.react":
        payload["config"]["react"][key] = SECRET_MARKER

    async with _client(harness.app) as client:
        response = await _post(client, payload)

    assert response.status_code == 422, (place, key, response.text)
    errors = response.json()["detail"]
    if place in ("root", "config"):
        # Direct extra=forbid rejection: the key itself is a loc segment.
        assert any(key in str(error["loc"]) for error in errors), f"{key} not locatable: {errors}"
        assert any(error["type"] == "extra_forbidden" for error in errors)
    else:
        # Inside the engine/react blocks the shared T3 normalizer wraps the
        # nested rejection at ``body.config``: still 422, still rejected (not
        # ignored), and the sanitized first-line message carries no values.
        assert any(list(error["loc"])[:2] == ["body", "config"] for error in errors), (
            f"nested rejection not at body.config: {errors}"
        )
    # Rejected, not ignored: no resolution happened.
    assert harness.resolver.calls == []
    assert harness.probe.calls == 0
    # No value echo anywhere in the response (C3).
    assert SECRET_MARKER not in response.text


@pytest.mark.asyncio
async def test_type_errors_are_locatable_and_do_not_echo_values() -> None:
    harness = Harness()
    payload = {
        "agent_id": "not-a-uuid-" + SECRET_MARKER,
        "config": {**VALID_CONFIG, "max_model_rounds": "many"},
    }
    async with _client(harness.app) as client:
        response = await _post(client, payload)
    assert response.status_code == 422, response.text
    locs = [str(error["loc"]) for error in response.json()["detail"]]
    assert any("agent_id" in loc for loc in locs), locs
    assert any("max_model_rounds" in loc for loc in locs), locs
    assert SECRET_MARKER not in response.text
    assert harness.resolver.calls == []


@pytest.mark.asyncio
async def test_unknown_plain_field_is_rejected() -> None:
    harness = Harness()
    async with _client(harness.app) as client:
        response = await _post(client, {"agent_id": None, "config": VALID_CONFIG, "bogus": 1})
    assert response.status_code == 422, response.text
    assert harness.resolver.calls == []


@pytest.mark.asyncio
async def test_missing_config_is_422() -> None:
    harness = Harness()
    async with _client(harness.app) as client:
        response = await _post(client, {"agent_id": None})
    assert response.status_code == 422, response.text
    assert harness.resolver.calls == []


# --------------------------------------------------------------------------- #
# P3-UT-12: tenant/actor/business/workspace come from the authenticated face   #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_resolution_request_is_assembled_from_trusted_context() -> None:
    """The token identifies tenant A; the DTO must carry A's trusted scope."""
    agent_id = uuid4()
    harness = Harness(
        resolution=_fresh_resolution(),
        agent_row={"id": str(agent_id), "published_version": 7},
        workspace_scope=("customer-service", "ws-a"),
    )
    payload = {"agent_id": str(agent_id), "config": VALID_CONFIG}
    async with _client(harness.app) as client:
        response = await _post(client, payload)

    assert response.status_code == 200, response.text
    assert len(harness.resolver.calls) == 1
    request = harness.resolver.calls[0]
    assert request.tenant_id == harness.settings.tenant_id
    assert request.business_scope == "customer-service"
    assert request.workspace_id == "ws-a"
    assert request.agent_id == agent_id
    assert request.agent_published_version == 7
    assert request.disabled_capabilities == ()
    # R-17: the restriction digest is the frozen server constant.
    assert request.execution_restriction_digest == NO_EXECUTION_RESTRICTIONS
    # The agent lookup ran under the authenticated tenant, never a body value.
    assert harness.agents.calls == [(harness.settings.tenant_id, agent_id)]


@pytest.mark.asyncio
async def test_disabled_capabilities_travel_from_the_draft() -> None:
    harness = Harness(resolution=_fresh_resolution())
    payload = {
        "agent_id": None,
        "config": {**VALID_CONFIG, "disabled_capabilities": ["terminal_execution"]},
    }
    async with _client(harness.app) as client:
        response = await _post(client, payload)
    assert response.status_code == 200, response.text
    assert harness.resolver.calls[0].disabled_capabilities == ("terminal_execution",)


# --------------------------------------------------------------------------- #
# Rollout states (03 §7.3)                                                     #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_phase3_off_returns_stable_domain_error_and_probes_nothing() -> None:
    """``execution_phase3_disabled``: the endpoint's first raise site."""
    settings = preview_settings(execution_phase3_enabled=False)
    harness = Harness(settings=settings)
    assert harness.subsystem is None
    async with _client(harness.app) as client:
        response = await _post(client, {"agent_id": None, "config": VALID_CONFIG})
    assert response.status_code == 409, response.text
    assert response.json() == {"detail": "execution_phase3_disabled"}
    assert harness.probe.calls == 0


@pytest.mark.asyncio
async def test_on_plus_orchestrator_off_still_answers_preview() -> None:
    """03 §9.2/§7.4: the misconfiguration fails Runs closed, not the read-only
    preview face; the subsystem exists and answers while orchestrator is off."""
    settings = preview_settings(execution_orchestrator_enabled=False)
    harness = Harness(settings=settings, resolution=_fresh_resolution())
    assert harness.subsystem is not None
    async with _client(harness.app) as client:
        response = await _post(client, {"agent_id": None, "config": VALID_CONFIG})
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_unregistered_triple_maps_to_engine_unavailable_without_resolution() -> None:
    harness = Harness()
    payload = {
        "agent_id": None,
        "config": {
            **VALID_CONFIG,
            "engine": {"engine_id": "codex", "protocol_id": "native", "adapter_version": "v1"},
            "react": None,
        },
    }
    async with _client(harness.app) as client:
        response = await _post(client, payload)
    assert response.status_code == 409, response.text
    assert response.json() == {"detail": "execution_engine_unavailable"}
    assert harness.resolver.calls == []
    assert harness.probe.calls == 0


@pytest.mark.asyncio
async def test_policy_source_outage_maps_to_policy_unavailable() -> None:
    """R-17: a failing ``current_revision`` never defaults to 0."""
    provider = _ScriptedPolicyProvider()
    harness = Harness(policy_provider=provider, real_resolver=True)
    provider.fail_revision = True
    async with _client(harness.app) as client:
        response = await _post(client, {"agent_id": None, "config": VALID_CONFIG})
    assert response.status_code == 409, response.text
    assert response.json() == {"detail": "execution_policy_unavailable"}


# --------------------------------------------------------------------------- #
# P3-UT-22 (preview half): response whitelist, projection, reason passthrough   #
# --------------------------------------------------------------------------- #


def _walk(node: Any):
    if isinstance(node, dict):
        for key, value in node.items():
            yield str(key), value
            yield from _walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


FORBIDDEN_KEY_MARKERS = (
    "declared",
    "available",
    "policy",
    "probe",
    "digest",
    "snapshot",
    "revision",
    "observed_at",
    "resolved_at",
    "deployment",
    "tenant",
    "actor",
    "source",
    "layer",
    "workspace_generation",
    "path",
    "secret",
    "token",
    "host",
)


@pytest.mark.asyncio
async def test_preview_response_is_the_exact_whitelist() -> None:
    """Engine + safe config schema + effective_capability_views projection and
    nothing else (03 §7.2, R-21)."""
    resolution = _fresh_resolution()
    expected_views = [
        {
            "name": item.name,
            "effective": item.effective,
            "reason_code": item.reason_code,
        }
        for item in effective_capability_views(resolution.effective)
    ]
    harness = Harness(resolution=resolution)
    async with _client(harness.app) as client:
        response = await _post(client, {"agent_id": None, "config": VALID_CONFIG})
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"engine", "config_schema", "capabilities"}
    assert body["engine"] == {
        "engine_id": "react",
        "protocol_id": "native",
        "adapter_version": "v1",
    }
    # The capabilities array IS the unique projection: 11 items, canonical
    # order, exactly three fields each.
    assert body["capabilities"] == expected_views
    assert [item["name"] for item in body["capabilities"]] == list(CAPABILITY_ORDER)
    for item in body["capabilities"]:
        assert set(item) == {"name", "effective", "reason_code"}
    # config_schema carries only name/type/required/safety-bound fields.
    schema = body["config_schema"]
    assert set(schema) == {"schema_version", "fields"}
    for field in schema["fields"]:
        assert set(field) <= {"name", "type", "required", "nullable", "minimum", "maximum"}
    names = {field["name"] for field in schema["fields"]}
    assert names <= set(ReactConfig.model_fields)


@pytest.mark.asyncio
async def test_preview_response_recursively_free_of_internal_evidence() -> None:
    """P3-UT-22 preview half + C3: no probe/policy/digest/snapshot/internal-id
    keys or values anywhere in the payload."""
    harness = Harness(real_resolver=True)
    await harness.warm_for()
    async with _client(harness.app) as client:
        response = await _post(client, {"agent_id": None, "config": VALID_CONFIG})
    assert response.status_code == 200, response.text
    body = response.json()
    leaked = {key for key, _ in _walk(body) if any(m in key for m in FORBIDDEN_KEY_MARKERS)}
    assert not leaked, f"whitelist leaked keys: {leaked}"
    text = json.dumps(body)
    # The fake ports' identifiers/provenance must not surface.
    for value in ("react-probe", "react-policy", "scripted-test", "platform-allowlist"):
        assert value not in text
    # No 64-hex digest strings anywhere.

    assert not re.search(r"\b[0-9a-f]{64}\b", text)


@pytest.mark.asyncio
async def test_reason_codes_pass_through_from_the_layers() -> None:
    """probe-unavailable, agent_disabled and platform_denied arrive verbatim,
    raw probe/policy evidence never does (03 §7.2/§7.3)."""
    harness = Harness(real_resolver=True, policy_provider=_ScriptedPolicyProvider())
    harness.policy_provider.denied_platform.add("native_events")
    payload = {
        "agent_id": None,
        "config": {**VALID_CONFIG, "disabled_capabilities": ["tool_calling"]},
    }
    await harness.warm_for(disabled=("tool_calling",))
    async with _client(harness.app) as client:
        response = await _post(client, payload)
    assert response.status_code == 200, response.text
    by_name = {item["name"]: item for item in response.json()["capabilities"]}
    assert by_name["native_events"] == {
        "name": "native_events",
        "effective": False,
        "reason_code": "platform_denied",
    }
    assert by_name["tool_calling"] == {
        "name": "tool_calling",
        "effective": False,
        "reason_code": "agent_disabled",
    }
    assert by_name["streaming"]["effective"] is True
    assert by_name["streaming"]["reason_code"] == "allowed"
    # Undeclared names are narrowed, never granted.
    assert by_name["terminal_execution"]["effective"] is False
    assert by_name["terminal_execution"]["reason_code"] == "not_declared"


@pytest.mark.asyncio
async def test_cold_cache_previews_fail_closed_with_stable_reasons() -> None:
    """03 §4.2: the preview hot path reads caches only; cold => unavailable
    reasons, still HTTP 200, and it still never warms inline (schedule only)."""
    harness = Harness(real_resolver=True)
    async with _client(harness.app) as client:
        response = await _post(client, {"agent_id": None, "config": VALID_CONFIG})
    assert response.status_code == 200, response.text
    by_name = {item["name"]: item for item in response.json()["capabilities"]}
    assert by_name["streaming"]["effective"] is False
    assert by_name["streaming"]["reason_code"] in ("probe_unavailable", "policy_unavailable")
    # Only the background schedule may have touched ports, never an inline warm
    # await: the response is produced without the resolver having warmed.
    await harness.wait_idle()
    again = None
    async with _client(harness.app) as client:
        again = await _post(client, {"agent_id": None, "config": VALID_CONFIG})
    assert again.status_code == 200
    after = {item["name"]: item for item in again.json()["capabilities"]}
    assert after["streaming"]["effective"] is True


# --------------------------------------------------------------------------- #
# P3-IT-11: preview never pins authorization across a policy change            #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_preview_then_policy_change_recomputes_without_stale_grant() -> None:
    """revision advance -> key change -> fresh policy, no old grant reused."""
    harness = Harness(real_resolver=True)
    await harness.warm_for()
    async with _client(harness.app) as client:
        first = await _post(client, {"agent_id": None, "config": VALID_CONFIG})
    assert first.status_code == 200, first.text
    before = {item["name"]: item["effective"] for item in first.json()["capabilities"]}
    assert before["streaming"] is True

    # The trusted source moves: same scope, new revision, streaming denied.
    harness.policy_provider.revision = 1
    harness.policy_provider.denied_platform.add("streaming")

    async with _client(harness.app) as client:
        second = await _post(client, {"agent_id": None, "config": VALID_CONFIG})
    assert second.status_code == 200, second.text
    mid = {item["name"]: item for item in second.json()["capabilities"]}
    # The revision-1 key was never observed: the old revision-0 grant must not
    # be reused to answer "true" here.
    assert mid["streaming"]["effective"] is False
    assert mid["streaming"]["reason_code"] in ("policy_unavailable", "platform_denied")

    await harness.wait_idle()
    async with _client(harness.app) as client:
        third = await _post(client, {"agent_id": None, "config": VALID_CONFIG})
    assert third.status_code == 200, third.text
    after = {item["name"]: item for item in third.json()["capabilities"]}
    assert after["streaming"]["effective"] is False
    assert after["streaming"]["reason_code"] == "platform_denied"


@pytest.mark.asyncio
async def test_preview_does_not_instantiate_adapters_or_write_snapshots() -> None:
    """Read-only contract (03 §7.3): the registry factory must never run."""
    harness = Harness(real_resolver=True)
    await harness.warm_for()
    # The harness registry's factory raises on resolve: reaching it fails loud.
    async with _client(harness.app) as client:
        response = await _post(client, {"agent_id": None, "config": VALID_CONFIG})
    assert response.status_code == 200, response.text


# --------------------------------------------------------------------------- #
# P3-IT-05 (HTTP-shape half): scoped lookup reuses the existing 404 behavior   #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_foreign_agent_id_keeps_the_existing_not_found_domain_answer() -> None:
    harness = Harness(agent_row=None)  # _FakeAgentService raises agent_not_found
    async with _client(harness.app) as client:
        response = await _post(client, {"agent_id": str(uuid4()), "config": VALID_CONFIG})
    assert response.status_code == 404, response.text
    assert response.json() == {"detail": "agent_not_found"}
    assert harness.resolver.calls == []


# --------------------------------------------------------------------------- #
# flags endpoint stays untouched (other line's green light)                    #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_flags_endpoint_still_answers_two_bools() -> None:
    harness = Harness(settings=preview_settings(execution_phase3_enabled=False))
    async with _client(harness.app, VIEWER_TOKEN) as client:
        response = await client.get(FLAGS_PATH)
    assert response.status_code == 200, response.text
    assert set(response.json()) == {
        "execution_phase3_enabled",
        "execution_orchestrator_enabled",
    }


# --------------------------------------------------------------------------- #
# PostgreSQL harness: real create_app, real production ports, real audit table #
# --------------------------------------------------------------------------- #


def _pg_phase3_settings(url: str, *, phase3: bool, orchestrator: bool) -> Settings:
    return Settings(
        database_url=url,
        tenant_id="t-preview-" + str(uuid4()),
        embedded_worker=False,
        embedded_channel_worker=False,
        model_backend="demo",
        tools_file=None,
        api_token=SecretStr(ADMIN_TOKEN),
        operator_api_token=SecretStr(OPERATOR_TOKEN),
        viewer_api_token=SecretStr(VIEWER_TOKEN),
        execution_phase3_enabled=phase3,
        execution_orchestrator_enabled=orchestrator,
        milvus_url=None,
        milvus_token=None,
        knowledge_parser_url=None,
        knowledge_s3_endpoint=None,
        knowledge_s3_bucket=None,
        knowledge_s3_access_key=None,
        knowledge_s3_secret_key=None,
    )


@pytest_asyncio.fixture
async def pg_app(request):
    """One real application per rollout state, with row cleanup."""
    from sqlalchemy import text

    from agent_platform.applications.customer_service.main import create_app
    from agent_platform.core_platform.platform_services.persistence.database import create_engine

    phase3, orchestrator = getattr(request, "param", (True, True))
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to run PostgreSQL preview integration tests")
    settings = _pg_phase3_settings(url, phase3=phase3, orchestrator=orchestrator)
    app = create_app(settings)
    client_engine = create_engine(settings)
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={
            "Authorization": "Bearer " + ADMIN_TOKEN,
            # Matches the deployment-level warm scope so preview keys hit the
            # warmed entries deterministically.
            "X-Workspace-ID": DEFAULT_WORKSPACE_ID,
        },
    )
    try:
        async with app.router.lifespan_context(app):
            yield SimpleNamespace(
                client=client,
                services=app.state.runtime,
                settings=settings,
                engine=client_engine,
            )
    finally:
        await client.aclose()
        async with client_engine.begin() as conn:
            await conn.execute(
                text(
                    "DELETE FROM runtime_events WHERE run_id IN "
                    "(SELECT id FROM runtime_runs WHERE tenant_id=:t)"
                ),
                {"t": settings.tenant_id},
            )
            await conn.execute(
                text(
                    "DELETE FROM agent_versions WHERE agent_id IN "
                    "(SELECT id FROM agents WHERE tenant_id=:t)"
                ),
                {"t": settings.tenant_id},
            )
            for table in ("runtime_runs", "runtime_conversations", "agents", "audit_records"):
                await conn.execute(
                    text(f"DELETE FROM {table} WHERE tenant_id=:t"),
                    {"t": settings.tenant_id},
                )
        await client_engine.dispose()


async def _audit_rows(engine, tenant, action="security.request_rejected"):
    from sqlalchemy import text

    async with engine.connect() as conn:
        rows = (
            (
                await conn.execute(
                    text(
                        "SELECT * FROM audit_records WHERE tenant_id=:t AND action=:a "
                        "ORDER BY created_at"
                    ),
                    {"t": tenant, "a": action},
                )
            )
            .mappings()
            .all()
        )
    return [dict(row) for row in rows]


def _details_of(row):
    return row["details"] if isinstance(row["details"], dict) else json.loads(row["details"])


async def _count(engine, table, tenant):
    from sqlalchemy import text

    async with engine.connect() as conn:
        return await conn.scalar(
            text(f"SELECT count(*) FROM {table} WHERE tenant_id=:t"), {"t": tenant}
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "pg_app", [(True, True), (True, False)], indirect=True, ids=["on+on", "on+orchestrator-off"]
)
@pytest.mark.postgres
async def test_pg_preview_unsaved_draft_has_zero_side_effects(pg_app) -> None:
    """P3-IT-17: agent_id=null previews, and nothing else happens: no Run, no
    Conversation, no Adapter instantiation, no snapshot columns."""
    from sqlalchemy import text

    services = pg_app.services
    # Deterministically warm the deployment-level target the same scope hits:
    # the route's hot read for this very draft must find fresh layers.
    subsystem = services.execution_subsystem
    assert subsystem is not None
    await subsystem.resolver.warm(subsystem.warm_targets[0])

    adapter_calls: list[int] = []
    original_factory_call = ReactAdapterFactory.__call__

    def counting_call(self):
        adapter_calls.append(1)
        return original_factory_call(self)

    ReactAdapterFactory.__call__ = counting_call
    try:
        before_runs = await _count(pg_app.engine, "runtime_runs", pg_app.settings.tenant_id)
        response = await pg_app.client.post(
            PREVIEW_PATH, json={"agent_id": None, "config": VALID_CONFIG}
        )
    finally:
        ReactAdapterFactory.__call__ = original_factory_call

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"engine", "config_schema", "capabilities"}
    assert [item["name"] for item in body["capabilities"]] == list(CAPABILITY_ORDER)
    # Production declaration-derived answers: React's four true capabilities.
    by_name = {item["name"]: item for item in body["capabilities"]}
    assert by_name["streaming"]["effective"] is True
    assert by_name["terminal_execution"]["effective"] is False
    assert by_name["terminal_execution"]["reason_code"] == "not_declared"

    assert adapter_calls == [], "preview must never resolve an Adapter"
    after_runs = await _count(pg_app.engine, "runtime_runs", pg_app.settings.tenant_id)
    conversations = await _count(pg_app.engine, "runtime_conversations", pg_app.settings.tenant_id)
    assert after_runs == before_runs == 0
    assert conversations == 0
    # No Run-authorization entry exists in the shared policy cache either:
    # every observed key is the deployment/draft shape (agent_id null), so the
    # preview left behind nothing a published Run could inherit (03 §4.3).
    policy_keys = list(subsystem.resolver._policy_cache._entries)
    assert policy_keys, "the preview round must have observed its own key"
    assert all(key.agent_id is None and key.agent_published_version is None for key in policy_keys)
    async with pg_app.engine.connect() as conn:
        snapshotted = await conn.scalar(
            text(
                "SELECT count(*) FROM runtime_runs WHERE tenant_id=:t AND ("
                "execution_config_snapshot IS NOT NULL OR "
                "declared_capabilities_snapshot IS NOT NULL OR "
                "available_capabilities_snapshot IS NOT NULL OR "
                "effective_capabilities_snapshot IS NOT NULL OR "
                "execution_policy_snapshot IS NOT NULL)"
            ),
            {"t": pg_app.settings.tenant_id},
        )
    assert snapshotted == 0


@pytest.mark.asyncio
@pytest.mark.postgres
async def test_pg_preview_uses_the_same_resolver_the_run_path_owns(pg_app) -> None:
    """P3-IT-19 preview half / R-21: one instance, one projection."""
    services = pg_app.services
    subsystem = services.execution_subsystem
    assert subsystem is not None
    orchestrator = services.worker.orchestrator
    assert orchestrator is not None
    assert orchestrator._capabilities is subsystem.resolver

    await subsystem.resolver.warm(subsystem.warm_targets[0])
    response = await pg_app.client.post(
        PREVIEW_PATH, json={"agent_id": None, "config": VALID_CONFIG}
    )
    assert response.status_code == 200, response.text
    # The projection is byte-identical to ``effective_capability_views`` over a
    # direct resolve of the same request (same instance, same round semantics).
    request = subsystem.warm_targets[0]
    resolution = await subsystem.resolver.resolve(request)
    expected = [
        {
            "name": item.name,
            "effective": item.effective,
            "reason_code": item.reason_code,
        }
        for item in effective_capability_views(resolution.effective)
    ]
    assert response.json()["capabilities"] == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("pg_app", [(False, True)], indirect=True, ids=["off+orchestrator-on"])
@pytest.mark.postgres
async def test_pg_phase3_off_preview_domain_error_and_no_subsystem(pg_app) -> None:
    services = pg_app.services
    assert services.execution_subsystem is None
    response = await pg_app.client.post(
        PREVIEW_PATH, json={"agent_id": None, "config": VALID_CONFIG}
    )
    assert response.status_code == 409, response.text
    assert response.json() == {"detail": "execution_phase3_disabled"}


@pytest.mark.asyncio
@pytest.mark.postgres
async def test_pg_forged_fields_are_audited_without_leaking_values(pg_app, caplog) -> None:
    """P3-IT-04 / R-13: the 422 face writes a real audit row for preview, Run
    and Agent bodies, and the planted secret appears nowhere."""
    forged_preview = await pg_app.client.post(
        PREVIEW_PATH,
        json={
            "agent_id": None,
            "config": {**VALID_CONFIG, "effective_capabilities": {"streaming": SECRET_MARKER}},
        },
    )
    forged_run = await pg_app.client.post(
        "/api/v1/runs",
        json={
            "conversation_id": "c-1",
            "message": "hello",
            "policy": SECRET_MARKER,
        },
    )
    forged_agent = await pg_app.client.post(
        "/api/v1/agents",
        json={
            "name": "forged-target",
            "description": "",
            "config": {**VALID_CONFIG, "declared": SECRET_MARKER},
        },
    )
    assert forged_preview.status_code == 422, forged_preview.text
    assert forged_run.status_code == 422, forged_run.text
    assert forged_agent.status_code == 422, forged_agent.text

    rows = await _audit_rows(pg_app.engine, pg_app.settings.tenant_id)
    resources = {row["resource"] for row in rows}
    assert PREVIEW_PATH in resources, rows
    assert "/api/v1/runs" in resources, rows
    assert "/api/v1/agents" in resources, rows

    for row in rows:
        # Trusted subject, never a body-supplied one.
        assert row["tenant_id"] == pg_app.settings.tenant_id
        assert row["actor"] == "admin"
        assert row["business_id"]
        assert row["workspace_id"]
        details = _details_of(row)
        assert details["request_id"]
        assert details["category"]
        paths = " ".join(details["field_paths"])
        # Field paths are locatable, values are absent.
        assert SECRET_MARKER not in paths
        assert SECRET_MARKER not in str(row)
    joined = " ".join(str(row) for row in rows) + caplog.text
    assert SECRET_MARKER not in joined


@pytest.mark.asyncio
@pytest.mark.postgres
async def test_pg_cross_tenant_agent_id_is_404_and_audits_no_foreign_data(pg_app) -> None:
    """P3-IT-05: a row owned by another tenant answers the existing 404; the
    audit record for the attempt carries no foreign agent data."""
    from sqlalchemy import text

    foreign_name = "FOREIGN-AGENT-" + SECRET_MARKER
    foreign_id = uuid4()
    other_tenant = "t-other-" + str(uuid4())
    async with pg_app.engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO agents(id,tenant_id,name,description,draft,published_version) "
                "VALUES(:id,:t,:n,'','{}'::jsonb,1)"
            ),
            {"id": str(foreign_id), "t": other_tenant, "n": foreign_name},
        )
    try:
        response = await pg_app.client.post(
            PREVIEW_PATH,
            json={"agent_id": str(foreign_id), "config": VALID_CONFIG},
        )
        assert response.status_code == 404, response.text
        # Same answer as a non-existent id: existence never leaks.
        missing = await pg_app.client.post(
            PREVIEW_PATH,
            json={"agent_id": str(uuid4()), "config": VALID_CONFIG},
        )
        assert missing.status_code == 404, missing.text
        assert response.json() == missing.json() == {"detail": "agent_not_found"}
        rows = await _audit_rows(pg_app.engine, pg_app.settings.tenant_id)
        joined = " ".join(str(r) for r in rows)
        assert SECRET_MARKER not in joined
        assert str(foreign_id) not in joined
        assert foreign_name not in joined
        # The audit rows that exist describe the attempt, not the data:
        # a sanitized body path only.
        assert rows, "the scope-denied attempt must be audited"
        assert any(_details_of(r)["category"] == "agent_scope_not_found" for r in rows), rows
        # The foreign tenant's audit space stays empty for our writes.
        foreign_rows = await _audit_rows(pg_app.engine, other_tenant)
        assert foreign_rows == []
    finally:
        async with pg_app.engine.begin() as conn:
            await conn.execute(text("DELETE FROM agents WHERE tenant_id=:t"), {"t": other_tenant})


@pytest.mark.asyncio
@pytest.mark.postgres
async def test_pg_openapi_declares_strict_request_and_whitelist_response(pg_app) -> None:
    """P3-IT-17: OpenAPI is consistent with the whitelist contract."""
    schema = (await pg_app.client.get("/openapi.json")).json()
    operation = schema["paths"][PREVIEW_PATH]["post"]
    responses = operation["responses"]["200"]["content"]["application/json"]["schema"]

    def deref(node):
        while "$ref" in node:
            name = node["$ref"].split("/")[-1]
            node = schema["components"]["schemas"][name]
        return node

    output = deref(responses)
    assert set(output["properties"]) == {"engine", "config_schema", "capabilities"}
    request_ref = operation["requestBody"]["content"]["application/json"]["schema"]
    request_schema = deref(request_ref)
    assert request_schema.get("additionalProperties") is False
    assert set(request_schema["properties"]) == {"agent_id", "config"}


@pytest.mark.asyncio
@pytest.mark.postgres
async def test_pg_preview_after_policy_constant_stays_conservative(pg_app) -> None:
    """Production face sanity: undeclared capabilities never preview as true."""
    subsystem = pg_app.services.execution_subsystem
    await subsystem.resolver.warm(subsystem.warm_targets[0])
    response = await pg_app.client.post(
        PREVIEW_PATH,
        json={"agent_id": None, "config": VALID_CONFIG},
    )
    assert response.status_code == 200, response.text
    for item in response.json()["capabilities"]:
        if item["name"] not in ("streaming", "cancellation", "tool_calling", "native_events"):
            assert item["effective"] is False, item
