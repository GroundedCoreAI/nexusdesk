"""Phase 3 T4: layered capability resolution, trusted ports, cache, and warmer.

Covers P3-UT-06..12 and P3-UT-22 from the phase 3 test plan. All probes,
policy providers, workspace ports, clocks, and sleepers are deterministic
fakes; no test waits on wall-clock time beyond bounded event gates.
"""

import asyncio
import inspect
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from agent_platform.core_platform.agent_execution.capability import (
    AvailabilityCacheKey,
    AvailabilityGeneration,
    CapabilityCache,
    CapabilityResolutionRequest,
    CapabilityResolver,
    CapabilityWarmer,
    PolicyCacheKey,
    PolicyContext,
    PolicyRevisionScope,
    PolicySourceUnavailableError,
    ProbeContext,
    ProbeResult,
    TrustedPolicyProvider,
    WorkspaceScope,
)
from agent_platform.core_platform.agent_execution.contracts import (
    CAPABILITY_ORDER,
    NO_EXECUTION_RESTRICTIONS,
    AvailableCapabilities,
    CapabilityDecision,
    CapabilityPolicy,
    ConfigurationError,
    DeclaredCapabilities,
    EffectiveCapabilities,
    EffectiveCapabilityDecision,
    EngineCapabilities,
    PolicyDecisionSet,
    PolicyLayerDecision,
    PolicyLayerVersion,
    ReactConfig,
    canonical_digest,
    disabled_capabilities_digest,
    effective_capability_flags,
    effective_capability_views,
    execution_restriction_digest,
    normalize_execution_config,
)
from agent_platform.core_platform.agent_execution.contracts.config import EmptyEngineConfig
from agent_platform.core_platform.agent_execution.registry import (
    AdapterDescriptor,
    AdapterRegistry,
    EngineDescriptor,
    EngineRegistry,
    ProtocolDescriptor,
    ProtocolRegistry,
)

FIXED = datetime(2026, 11, 12, tzinfo=UTC)
ZERO64 = "0" * 64
ONE64 = "1" * 64
DEPLOYMENT_A = "deployment-a"
DEPLOYMENT_DIGEST = "d" * 64
TENANT_A = "tenant-a"
TENANT_B = "tenant-b"
AGENT_ID = UUID("7b8f0000-0000-0000-0000-000000000001")
LAYER_ORDER = ("platform", "tenant", "agent", "execution")
REACT_DECLARED = EngineCapabilities(
    streaming=True,
    cancellation=True,
    tool_calling=True,
    native_events=True,
)
SECRET_MARKER = "raw-" + "secret-token-marker"


class FakeClock:
    def __init__(self, start: float = 1_800_000_000.0) -> None:
        self.value = start

    def now(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class GatedSleeper:
    """Records warmer round intervals and blocks until the test releases.

    Queue-based one-shot handshake: each round the sleeper publishes a parked
    token and then waits for a release token. ``wait_parked`` consumes exactly
    one token, so a stale "already parked" state can never satisfy the next
    wait. The previous Event-polarity protocol relied on ``asyncio.wait_for``
    yielding before an already-set Event returns; that is true on Python 3.11
    but not 3.12+, which raced the second warmer round and failed CI with
    assert 1 == 2 (probe calls / warm_calls / intervals).
    """

    def __init__(self) -> None:
        self.intervals: list[float] = []
        self._parked: asyncio.Queue[None] = asyncio.Queue()
        self._released: asyncio.Queue[None] = asyncio.Queue()

    async def __call__(self, seconds: float) -> None:
        self.intervals.append(seconds)
        self._parked.put_nowait(None)
        await self._released.get()

    async def wait_parked(self, timeout: float = 1.0) -> None:
        """Block until the warmer loop has entered its next sleep round."""
        await asyncio.wait_for(self._parked.get(), timeout=timeout)

    def release(self) -> None:
        """Let the currently parked sleep round return."""
        self._released.put_nowait(None)


@dataclass
class FakeProbe:
    handler: object = None
    calls: list[ProbeContext] = field(default_factory=list)
    active: int = 0
    max_active: int = 0

    async def probe(self, context: ProbeContext) -> ProbeResult:
        self.calls.append(context)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if self.handler is None:
                return allow_all_probe_result(context)
            return await self.handler(context)
        finally:
            self.active -= 1


@dataclass
class FakePolicyProvider:
    handler: object = None
    calls: list[PolicyContext] = field(default_factory=list)
    revision_calls: list[PolicyRevisionScope] = field(default_factory=list)
    revision: int = 1
    revision_error: Exception | None = None

    def current_revision(self, scope: PolicyRevisionScope) -> int:
        """Synchronous trusted revision read, mirroring the R-17 port contract."""
        self.revision_calls.append(scope)
        if self.revision_error is not None:
            raise self.revision_error
        return self.revision

    async def resolve(self, context: PolicyContext) -> PolicyDecisionSet:
        self.calls.append(context)
        if self.handler is None:
            return allow_all_policy(context)
        return await self.handler(context)


@dataclass
class FakeWorkspacePort:
    generations: dict[tuple[str, str], AvailabilityGeneration] = field(default_factory=dict)

    def current(self, scope: WorkspaceScope) -> AvailabilityGeneration | None:
        return self.generations.get((scope.business_scope, scope.workspace_id))


def make_descriptor(
    *,
    engine_id: str = "react",
    protocol_id: str = "native",
    adapter_version: str = "v1",
    declared: EngineCapabilities = REACT_DECLARED,
    enabled: bool = True,
    probe_version: str = "v1",
    config_schema_version: str = "v1",
    policy_provider_id: str = "react-policy",
) -> AdapterDescriptor:
    return AdapterDescriptor(
        engine_id=engine_id,
        protocol_id=protocol_id,
        adapter_version=adapter_version,
        enabled=enabled,
        config_schema=ReactConfig if engine_id == "react" else EmptyEngineConfig,
        config_schema_version=config_schema_version,
        declared=declared,
        declared_schema_version="v1",
        probe_id=f"{engine_id}-probe",
        probe_version=probe_version,
        policy_provider_id=policy_provider_id,
        policy_version="v1",
        instruction_provider_id="react-native",
        provider_version="v1",
    )


def capability_item(name: str, available: bool, reason: str) -> CapabilityDecision:
    return CapabilityDecision(name=name, available=available, reason_code=reason)


def probe_items(available: set[str], reason: str = "probe_unavailable") -> tuple:
    return tuple(
        capability_item(
            name,
            name in available,
            "allowed" if name in available else reason,
        )
        for name in CAPABILITY_ORDER
    )


def deny_one_probe_answer(denied: str, reason: str):
    """Probe handler factory: one capability denied with ``reason``, rest allowed."""

    async def handler(context: ProbeContext) -> ProbeResult:
        return ProbeResult(
            engine_id=context.engine_id,
            protocol_id=context.protocol_id,
            adapter_version=context.adapter_version,
            probe_id=context.probe_id,
            probe_version=context.probe_version,
            observed_at=FIXED,
            deployment_digest=DEPLOYMENT_DIGEST,
            items=tuple(
                capability_item(name, False, reason)
                if name == denied
                else capability_item(name, True, "allowed")
                for name in CAPABILITY_ORDER
            ),
        )

    return handler


def allow_all_probe_result(
    context: ProbeContext,
    *,
    probe_version: str | None = None,
    deployment_digest: str = DEPLOYMENT_DIGEST,
    observed_at: datetime = FIXED,
    reason_for_missing: str = "probe_unavailable",
) -> ProbeResult:
    # A deployed-in-full probe answers every declared capability. The
    # registry-declared set for these tests is fixed; non-declared names
    # answer unavailable so the clamp rule is exercised implicitly.
    available = {
        name
        for name in (
            "streaming",
            "cancellation",
            "tool_calling",
            "native_events",
            "workspace_required",
        )
    }
    return ProbeResult(
        engine_id=context.engine_id,
        protocol_id=context.protocol_id,
        adapter_version=context.adapter_version,
        probe_id=context.probe_id,
        probe_version=probe_version or context.probe_version,
        observed_at=observed_at,
        deployment_digest=deployment_digest,
        items=probe_items(available, reason_for_missing),
    )


def policy_layers(
    name: str,
    denials: dict[tuple[str, str], str],
) -> tuple[PolicyLayerDecision, ...]:
    return tuple(
        PolicyLayerDecision(
            layer=layer,
            allowed=(name, layer) not in denials,
            source="trusted-source",
            reason_code=denials.get((name, layer), "allowed"),
        )
        for layer in LAYER_ORDER
    )


def make_policy(
    context: PolicyContext,
    denials: dict[tuple[str, str], str] | None = None,
) -> PolicyDecisionSet:
    denials = denials or {}
    return PolicyDecisionSet(
        policy_provider_id=context.policy_provider_id,
        policy_version=context.policy_version,
        policy_revision=context.policy_revision,
        resolved_at=FIXED,
        layer_versions=tuple(
            PolicyLayerVersion(layer=layer, version="v1", revision=1) for layer in LAYER_ORDER
        ),
        decisions=tuple(
            CapabilityPolicy(name=name, layers=policy_layers(name, denials))
            for name in CAPABILITY_ORDER
        ),
    )


def allow_all_policy(context: PolicyContext) -> PolicyDecisionSet:
    return make_policy(context)


def build_registry(descriptors: tuple[AdapterDescriptor, ...]) -> tuple[AdapterRegistry, list]:
    engines = EngineRegistry()
    engines.register(EngineDescriptor(engine_id="react", enabled=True))
    engines.register(EngineDescriptor(engine_id="toolkit", enabled=True))
    protocols = ProtocolRegistry()
    protocols.register(ProtocolDescriptor(protocol_id="native", enabled=True))
    adapters = AdapterRegistry(engines, protocols)
    created: list = []

    def factory_for(descriptor: AdapterDescriptor):
        def create() -> object:
            created.append(descriptor)
            return object()

        return create

    for descriptor in descriptors:
        adapters.register(descriptor, factory_for(descriptor))
    return adapters, created


@dataclass
class _Env:
    resolver: CapabilityResolver
    request: CapabilityResolutionRequest
    probe: FakeProbe
    policy: FakePolicyProvider
    workspace: FakeWorkspacePort
    clock: FakeClock
    created: list
    availability_cache: CapabilityCache
    policy_cache: CapabilityCache
    request_b: CapabilityResolutionRequest


def make_request(
    *,
    engine_id: str = "react",
    tenant_id: str = TENANT_A,
    disabled: tuple = (),
) -> CapabilityResolutionRequest:
    return CapabilityResolutionRequest(
        engine_id=engine_id,
        protocol_id="native",
        adapter_version="v1",
        tenant_id=tenant_id,
        business_scope="biz-1",
        workspace_id="ws-1",
        agent_id=AGENT_ID,
        agent_published_version=3,
        disabled_capabilities=disabled,
        execution_restriction_digest=ZERO64,
    )


def build_env(
    *,
    descriptors: tuple[AdapterDescriptor, ...] | None = None,
    probe_handler=None,
    policy_handler=None,
    workspace_generations: dict | None = None,
    probe_timeout_seconds: float = 30.0,
    policy_timeout_seconds: float = 30.0,
    probe_max_concurrency: int = 4,
    ttl_seconds: float = 30.0,
    policy_ttl_seconds: float | None = None,
    capacity: int = 8,
    retry_interval_seconds: float = 5.0,
) -> _Env:
    descriptors = descriptors or (make_descriptor(),)
    adapters, created = build_registry(descriptors)
    clock = FakeClock()
    probe = FakeProbe(handler=probe_handler)
    policy = FakePolicyProvider(handler=policy_handler)
    workspace = FakeWorkspacePort(generations=dict(workspace_generations or {}))
    availability_cache = CapabilityCache(
        ttl_seconds=ttl_seconds,
        capacity=capacity,
        clock=clock.now,
        retry_interval_seconds=retry_interval_seconds,
    )
    policy_cache = CapabilityCache(
        ttl_seconds=policy_ttl_seconds if policy_ttl_seconds is not None else ttl_seconds,
        capacity=capacity,
        clock=clock.now,
        retry_interval_seconds=retry_interval_seconds,
    )
    resolver = CapabilityResolver(
        registry=adapters,
        probe=probe,
        policy_provider=policy,
        workspace_port=workspace,
        availability_cache=availability_cache,
        policy_cache=policy_cache,
        deployment_identity=DEPLOYMENT_A,
        probe_timeout_seconds=probe_timeout_seconds,
        policy_timeout_seconds=policy_timeout_seconds,
        probe_max_concurrency=probe_max_concurrency,
        clock=clock.now,
    )
    return _Env(
        resolver=resolver,
        request=make_request(),
        probe=probe,
        policy=policy,
        workspace=workspace,
        clock=clock,
        created=created,
        availability_cache=availability_cache,
        policy_cache=policy_cache,
        request_b=make_request(tenant_id=TENANT_B),
    )


def item_map(items) -> dict:
    return {item.name: item for item in items}


def availability_key_for(index: int) -> AvailabilityCacheKey:
    """One exact-shape availability key whose digest is unique per index."""
    return AvailabilityCacheKey(
        deployment_identity=DEPLOYMENT_A,
        engine_id="react",
        protocol_id="native",
        adapter_version="v1",
        config_schema_version="v1",
        probe_id="react-probe",
        probe_version="v1",
        declaration_digest=f"{index}" * 64,
        workspace_generation=None,
    )


_LOG_RECORD_STANDARD_ATTRS = frozenset(
    vars(logging.LogRecord("probe", logging.WARNING, "probe.py", 1, "probe", (), None))
)


def rendered_log_text(record: logging.LogRecord) -> str:
    """Everything a formatted log line could carry for one captured record.

    Covers the rendered message (``getMessage()``), the raw ``args`` tuple,
    every non-standard attribute (i.e. every ``extra`` field, present or added
    in the future), and ``exc_info``. Leak scans must go through this helper
    instead of a fixed key list so a new extra field cannot bypass them.
    """
    extras = {k: v for k, v in vars(record).items() if k not in _LOG_RECORD_STANDARD_ATTRS}
    return " | ".join([record.getMessage(), repr(record.args), repr(extras), repr(record.exc_info)])


def _marker_validation_error() -> ValidationError:
    """A pydantic ValidationError whose raw text carries SECRET_MARKER."""
    try:
        AvailabilityGeneration.model_validate({"generation": SECRET_MARKER, "available": True})
    except ValidationError as exc:
        return exc
    raise AssertionError("expected a ValidationError for a non-integer generation")


# ---------------------------------------------------------------------------
# P3-UT-06  Declared vs Available
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_p3_ut06_deployed_missing_makes_available_false_without_rewriting_declared():
    env = build_env()
    declared_before = env.resolver.declared("react", "native", "v1")
    assert isinstance(declared_before, DeclaredCapabilities)
    assert declared_before.capabilities == REACT_DECLARED

    async def deployment_missing(context: ProbeContext) -> ProbeResult:
        # Deployment lacks the engine: probe answers nothing available.
        return ProbeResult(
            engine_id=context.engine_id,
            protocol_id=context.protocol_id,
            adapter_version=context.adapter_version,
            probe_id=context.probe_id,
            probe_version=context.probe_version,
            observed_at=FIXED,
            deployment_digest=ZERO64,
            items=probe_items(set()),
        )

    env.probe.handler = deployment_missing
    assert await env.resolver.warm(env.request) is True
    resolution = await env.resolver.resolve(env.request)
    available = item_map(resolution.available.items)
    for name in ("streaming", "cancellation", "tool_calling", "native_events"):
        assert available[name].available is False
        assert available[name].reason_code == "probe_unavailable"
    # Declared is read-only registry metadata and was not rewritten.
    declared_after = env.resolver.declared("react", "native", "v1")
    assert declared_after == declared_before
    # available implies declared: non-declared names can never be available.
    for name, decision in available.items():
        if not getattr(REACT_DECLARED, name):
            assert decision.available is False


@pytest.mark.asyncio
async def test_p3_ut06_probe_version_mismatch_fails_closed_and_preserves_declared():
    async def mismatched(context: ProbeContext) -> ProbeResult:
        return allow_all_probe_result(context, probe_version="v2")

    env = build_env(probe_handler=mismatched)
    assert await env.resolver.warm(env.request) is False
    assert env.resolver.availability_cache_status(env.request) == "error"
    resolution = await env.resolver.resolve(env.request)
    available = item_map(resolution.available.items)
    assert available["streaming"].available is False
    assert available["streaming"].reason_code == "probe_unavailable"
    assert resolution.declared.capabilities == REACT_DECLARED


def test_p3_ut06_declared_lookup_rejects_disabled_or_unknown_triple():
    env = build_env(
        descriptors=(
            make_descriptor(enabled=False),
            make_descriptor(engine_id="toolkit"),
        )
    )
    with pytest.raises(ConfigurationError):
        env.resolver.declared("react", "native", "v1")
    with pytest.raises(ConfigurationError):
        env.resolver.declared("toolkit", "native", "v9")


# ---------------------------------------------------------------------------
# P3-UT-07  probe timeout / failure / cache semantics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_p3_ut07_probe_timeout_is_bounded_sanitized_and_reason_stable():
    started = asyncio.Event()

    async def hanging(context: ProbeContext) -> ProbeResult:
        started.set()
        await asyncio.Event().wait()  # never completes; timeout wrapper must fire
        raise AssertionError("unreachable")

    env = build_env(probe_handler=hanging, probe_timeout_seconds=0.05)
    assert await env.resolver.warm(env.request) is True
    resolution = await env.resolver.resolve(env.request)
    available = item_map(resolution.available.items)
    assert available["streaming"].available is False
    assert available["streaming"].reason_code == "probe_timeout"
    effective = item_map(resolution.effective.items)
    assert effective["streaming"].effective is False
    assert started.is_set()


@pytest.mark.asyncio
async def test_p3_ut07_probe_exception_keeps_error_status_without_raw_text():
    async def explode(context: ProbeContext) -> ProbeResult:
        raise RuntimeError(f"upstream {SECRET_MARKER} at host /srv/secret/path")

    env = build_env(probe_handler=explode)
    assert await env.resolver.warm(env.request) is False
    assert env.resolver.availability_cache_status(env.request) == "error"
    resolution = await env.resolver.resolve(env.request)
    dump = resolution.available.model_dump_json() + resolution.effective.model_dump_json()
    assert SECRET_MARKER not in dump
    assert "/srv" not in dump
    available = item_map(resolution.available.items)
    assert available["streaming"].reason_code == "probe_unavailable"


@pytest.mark.asyncio
async def test_p3_ut07_cache_hit_within_ttl_and_declaration_change_replaces_identity_key():
    toolkit_declared = EngineCapabilities(streaming=True, persistent_session=True)
    env = build_env(
        descriptors=(
            make_descriptor(),
            make_descriptor(engine_id="toolkit", declared=toolkit_declared),
        )
    )
    assert await env.resolver.warm(env.request) is True
    calls_after_warm = len(env.probe.calls)
    # Hot reads within TTL hit the cache without any new probe.
    await env.resolver.resolve(env.request)
    await env.resolver.resolve(env.request)
    assert len(env.probe.calls) == calls_after_warm

    # A different registration with a different declaration occupies its own
    # identity key; the old entry is not reused or rewritten.
    request2 = make_request(engine_id="toolkit")
    digest1 = env.resolver.declared("react", "native", "v1").declaration_digest
    digest2 = env.resolver.declared("toolkit", "native", "v1").declaration_digest
    assert digest1 != digest2
    assert await env.resolver.warm(request2) is True
    assert len(env.probe.calls) == calls_after_warm + 1
    assert env.availability_cache.size == 2
    resolution1 = await env.resolver.resolve(env.request)
    assert resolution1.available.declaration_digest == digest1


@pytest.mark.asyncio
async def test_p3_ut07_probe_concurrency_is_bounded():
    gate = asyncio.Event()

    async def gated(context: ProbeContext) -> ProbeResult:
        await gate.wait()
        return allow_all_probe_result(context)

    env = build_env(
        descriptors=(
            make_descriptor(),
            make_descriptor(engine_id="toolkit"),
        ),
        probe_handler=gated,
        probe_max_concurrency=1,
    )
    # Two cold keys are read on the hot path; scheduled probes must serialize.
    await env.resolver.resolve(env.request)
    await env.resolver.resolve(make_request(engine_id="toolkit"))
    await asyncio.sleep(0)
    assert env.probe.max_active <= 1
    gate.set()
    await env.resolver.wait_idle()
    assert len(env.probe.calls) == 2
    assert env.probe.max_active == 1


# ---------------------------------------------------------------------------
# P3-UT-08  workspace_required
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_p3_ut08_workspace_required_without_trusted_workspace_blocks_startup():
    declared = EngineCapabilities(streaming=True, tool_calling=True, workspace_required=True)
    env = build_env(descriptors=(make_descriptor(declared=declared),))
    assert await env.resolver.warm(env.request) is True
    resolution = await env.resolver.resolve(env.request)
    available = item_map(resolution.available.items)
    assert available["workspace_required"].available is False
    assert available["workspace_required"].reason_code == "workspace_unavailable"
    # The probe itself still answered available for every deployed capability.
    assert len(env.probe.calls) == 1
    assert env.probe.calls[0].workspace_generation is None
    effective = item_map(resolution.effective.items)
    assert effective["workspace_required"].effective is False
    assert resolution.effective.required_capabilities_missing == ("workspace_required",)
    assert resolution.startup_allowed is False
    # Non-required capabilities stay usable; only startup is blocked.
    assert effective["streaming"].effective is True

    # A trusted workspace generation appears: the availability key changes and
    # after refresh the required capability resolves available again.
    env.workspace.generations = {
        ("biz-1", "ws-1"): AvailabilityGeneration(generation=7, available=True)
    }
    before = await env.resolver.resolve(env.request)
    assert env.probe.calls[-1].workspace_generation is None  # cold read is fail-closed
    assert item_map(before.available.items)["workspace_required"].available is False
    await env.resolver.wait_idle()
    after = await env.resolver.resolve(env.request)
    available_after = item_map(after.available.items)
    assert available_after["workspace_required"].available is True
    assert available_after["workspace_required"].reason_code == "allowed"
    assert after.effective.required_capabilities_missing == ()
    assert after.startup_allowed is True
    assert env.probe.calls[-1].workspace_generation == 7

    # A workspace that reports itself unavailable narrows again.
    env.workspace.generations = {
        ("biz-1", "ws-1"): AvailabilityGeneration(generation=8, available=False)
    }
    await env.resolver.resolve(env.request)
    await env.resolver.wait_idle()
    blocked = await env.resolver.resolve(env.request)
    blocked_map = item_map(blocked.available.items)
    assert blocked_map["workspace_required"].available is False
    assert blocked_map["workspace_required"].reason_code == "workspace_unavailable"
    assert blocked.startup_allowed is False


# ---------------------------------------------------------------------------
# P3-UT-09  monotonic narrowing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_p3_ut09_each_layer_denial_narrows_effective_monotonically():
    denials = {
        ("streaming", "platform"): "platform_denied",
        ("cancellation", "tenant"): "tenant_denied",
        ("tool_calling", "agent"): "agent_disabled",
        ("native_events", "execution"): "execution_denied",
    }

    async def denying(context: PolicyContext) -> PolicyDecisionSet:
        return make_policy(context, denials)

    env = build_env(policy_handler=denying)
    assert await env.resolver.warm(env.request) is True
    resolution = await env.resolver.resolve(env.request)
    effective = item_map(resolution.effective.items)
    # Probe says everything deployed; lower layers allowing cannot recover.
    for name, reason in (
        ("streaming", "platform_denied"),
        ("cancellation", "tenant_denied"),
        ("tool_calling", "agent_disabled"),
        ("native_events", "execution_denied"),
        ("persistent_session", "not_declared"),
    ):
        assert effective[name].effective is False
        assert effective[name].reason_code == reason
    # Every layer decision is recorded for auditability.
    streaming_policy = next(
        decision for decision in resolution.policy.decisions if decision.name == "streaming"
    )
    by_layer = {layer.layer: layer for layer in streaming_policy.layers}
    assert by_layer["platform"].allowed is False
    assert by_layer["platform"].reason_code == "platform_denied"
    assert by_layer["tenant"].allowed is True


@pytest.mark.asyncio
async def test_p3_ut09_disabled_capabilities_can_only_true_to_false():
    env = build_env()
    request = make_request(disabled=("streaming", "persistent_session"))
    assert await env.resolver.warm(request) is True
    resolution = await env.resolver.resolve(request)
    effective = item_map(resolution.effective.items)
    # Declared+available item is narrowed by the disable list.
    assert effective["streaming"].effective is False
    assert effective["streaming"].reason_code == "agent_disabled"
    # A disabled item that was never declared cannot be switched on.
    assert effective["persistent_session"].effective is False
    assert effective["persistent_session"].reason_code == "not_declared"
    # Nothing outside the disable list that is declared/available is false.
    assert effective["cancellation"].effective is True
    assert effective["tool_calling"].effective is True
    for name in CAPABILITY_ORDER:
        if not getattr(REACT_DECLARED, name):
            assert effective[name].effective is False


# ---------------------------------------------------------------------------
# P3-UT-10  unknown capability / policy failure modes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_p3_ut10_untrusted_or_stale_policy_fails_closed():
    async def rogue_provider_id(context: PolicyContext) -> PolicyDecisionSet:
        return allow_all_policy(context).model_copy(update={"policy_provider_id": "rogue"})

    env = build_env(policy_handler=rogue_provider_id)
    assert await env.resolver.warm(env.request) is False
    assert env.resolver.policy_cache_status(env.request) == "error"
    resolution = await env.resolver.resolve(env.request)
    effective = item_map(resolution.effective.items)
    assert effective["streaming"].effective is False
    assert effective["streaming"].reason_code == "policy_unavailable"
    assert resolution.policy is None  # never surfaced when untrusted

    async def stale_revision(context: PolicyContext) -> PolicyDecisionSet:
        return allow_all_policy(context).model_copy(update={"policy_revision": 999})

    env2 = build_env(policy_handler=stale_revision)
    assert await env2.resolver.warm(env2.request) is False
    resolution2 = await env2.resolver.resolve(env2.request)
    effective2 = item_map(resolution2.effective.items)
    assert effective2["streaming"].effective is False
    assert effective2["streaming"].reason_code == "policy_unavailable"


@pytest.mark.asyncio
async def test_p3_ut10_missing_policy_source_and_unknown_capability_names_fail_closed():
    async def broken(context: PolicyContext) -> PolicyDecisionSet:
        raise RuntimeError(f"policy backend {SECRET_MARKER} down")

    env = build_env(policy_handler=broken)
    assert await env.resolver.warm(env.request) is False
    resolution = await env.resolver.resolve(env.request)
    dump = resolution.effective.model_dump_json()
    assert SECRET_MARKER not in dump
    effective = item_map(resolution.effective.items)
    assert effective["streaming"].effective is False
    assert effective["streaming"].reason_code == "policy_unavailable"


def test_p3_ut10_unknown_capability_names_are_schema_errors_not_ignored():
    with pytest.raises(ValidationError):
        CapabilityDecision(name="not_a_capability", available=True, reason_code="allowed")
    partial = tuple(CapabilityDecision(name="streaming", available=True, reason_code="allowed"))
    with pytest.raises(ValidationError):
        AvailableCapabilities(
            engine_id="react",
            protocol_id="native",
            adapter_version="v1",
            probe_id="react-probe",
            probe_version="v1",
            observed_at=FIXED,
            declaration_digest=ZERO64,
            deployment_digest=ONE64,
            items=partial,
        )
    with pytest.raises(ValidationError):
        # available=True must carry reason "allowed" only.
        probe_items_inconsistent = tuple(
            CapabilityDecision(
                name=name,
                available=True,
                reason_code="probe_stale" if name == "streaming" else "allowed",
            )
            for name in CAPABILITY_ORDER
        )
        AvailableCapabilities(
            engine_id="react",
            protocol_id="native",
            adapter_version="v1",
            probe_id="react-probe",
            probe_version="v1",
            observed_at=FIXED,
            declaration_digest=ZERO64,
            deployment_digest=ONE64,
            items=probe_items_inconsistent,
        )
    with pytest.raises(ValidationError):
        # A policy for one capability must carry all four layers.
        CapabilityPolicy(
            name="streaming",
            layers=(
                PolicyLayerDecision(
                    layer="platform", allowed=True, source="trusted", reason_code="allowed"
                ),
            ),
        )


# ---------------------------------------------------------------------------
# P3-UT-11  forged client input
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_p3_ut11_forged_capability_layers_rejected_by_every_trusted_dto():
    env = build_env()
    await env.resolver.resolve(env.request)
    await env.resolver.wait_idle()
    forged_keys = {
        "declared",
        "available",
        "effective",
        "effective_capabilities",
        "policy_decisions",
        "probe_result",
        "client_grant",
    }
    for instance in (
        env.probe.calls[0],
        env.policy.calls[0],
    ):
        payload = json.loads(instance.model_dump_json())
        for key in forged_keys:
            with pytest.raises(ValidationError):
                type(instance).model_validate_json(json.dumps({**payload, key: "forged"}))
    # Layer DTOs themselves never accept a client-shaped capability override.
    for model in (DeclaredCapabilities, AvailableCapabilities, PolicyDecisionSet):
        for key in ("effective_capabilities", "policy", "probe"):
            assert key not in model.model_fields


def test_p3_ut11_request_and_config_contracts_have_no_capability_authorization_input():
    from agent_platform.core_platform.agent_runtime.schemas import RunRequest

    with pytest.raises(ValidationError):
        RunRequest.model_validate(
            {
                "conversation_id": "conv-1",
                "message": "hi",
                "effective_capabilities": {"terminal_execution": True},
            }
        )
    with pytest.raises(ValidationError):
        normalize_execution_config(
            {
                "engine": {"engine_id": "react", "protocol_id": "native", "adapter_version": "v1"},
                "declared": {"streaming": True},
            }
        )
    with pytest.raises(ValidationError):
        normalize_execution_config(
            {"max_model_rounds": 6, "policy_version": "v2", "actor": "someone"}
        )
    # The resolver input is closed to a trusted scope; no client fields exist.
    # R-17: policy_revision is no longer request-carried at all -- the resolver
    # observes it live from the trusted provider, so a stale client-adjacent
    # value cannot be pinned into a DTO.
    assert set(CapabilityResolutionRequest.model_fields) == {
        "contract_version",
        "engine_id",
        "protocol_id",
        "adapter_version",
        "tenant_id",
        "business_scope",
        "workspace_id",
        "agent_id",
        "agent_published_version",
        "disabled_capabilities",
        "execution_restriction_digest",
    }
    with pytest.raises(ValidationError):
        CapabilityResolutionRequest.model_validate(
            {
                **make_request().model_dump(),
                "effective_capabilities": {"streaming": True},
            }
        )


# ---------------------------------------------------------------------------
# P3-UT-12  trusted tenant/actor context
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_p3_ut12_policy_context_uses_server_trusted_tenant_and_never_client_text():
    env = build_env()
    assert await env.resolver.warm(env.request) is True
    context = env.policy.calls[0]
    assert context.tenant_id == TENANT_A
    assert context.business_scope == "biz-1"
    assert context.workspace_id == "ws-1"
    assert context.agent_id == AGENT_ID
    # Probe/policy contexts carry no client-controllable message/config fields.
    assert not {"input", "message", "config", "actor", "trace_id", "conversation_id"} & set(
        type(context).model_fields
    )
    assert not {"tenant_id", "actor", "trace_id", "conversation_id"} & set(
        ProbeContext.model_fields
    )


@pytest.mark.asyncio
async def test_p3_ut12_cross_tenant_policy_entries_are_isolated():
    env = build_env()
    assert await env.resolver.warm(env.request) is True
    probe_calls = len(env.probe.calls)
    # A read for tenant B must not synchronously re-probe and must not reuse
    # tenant A's cached policy: the policy key differs so it fails closed until
    # its own background refresh runs.
    resolution_b_cold = await env.resolver.resolve(env.request_b)
    assert len(env.probe.calls) == probe_calls
    assert resolution_b_cold.policy is None
    assert item_map(resolution_b_cold.effective.items)["streaming"].reason_code == (
        "policy_unavailable"
    )
    await env.resolver.wait_idle()
    assert len(env.policy.calls) == 2
    assert env.policy.calls[1].tenant_id == TENANT_B
    resolution_b = await env.resolver.resolve(env.request_b)
    assert resolution_b.policy is not None
    assert item_map(resolution_b.effective.items)["streaming"].effective is True


# ---------------------------------------------------------------------------
# P3-UT-22  cache keys, hot-path discipline, warmer lifecycle, DTO whitelist
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_p3_ut22_cold_hot_path_never_probes_and_singleflights_refresh():
    env = build_env()
    assert env.resolver.availability_cache_status(env.request) == "cold"
    resolution = await env.resolver.resolve(env.request)
    # Synchronous hot path performs no remote calls at all.
    assert env.probe.calls == []
    assert env.policy.calls == []
    available = item_map(resolution.available.items)
    assert available["streaming"].available is False
    assert available["streaming"].reason_code == "probe_unavailable"
    effective = item_map(resolution.effective.items)
    assert effective["streaming"].effective is False
    assert effective["streaming"].reason_code == "policy_unavailable"
    assert resolution.startup_allowed is False

    # A second concurrent read dedupes into one background refresh each.
    await env.resolver.resolve(env.request)
    await env.resolver.wait_idle()
    assert len(env.probe.calls) == 1
    assert len(env.policy.calls) == 1
    warmed = await env.resolver.resolve(env.request)
    assert item_map(warmed.effective.items)["streaming"].effective is True
    assert len(env.probe.calls) == 1


@pytest.mark.asyncio
async def test_p3_ut22_unwarmed_unavailable_then_warm_then_expired_sequence():
    env = build_env(ttl_seconds=30.0)

    # 1) Not pre-warmed: unavailable.
    cold = await env.resolver.resolve(env.request)
    assert item_map(cold.available.items)["streaming"].available is False
    await env.resolver.wait_idle()

    # 2) Background warmer round succeeded: available.
    sleeper = GatedSleeper()
    warmer = CapabilityWarmer(
        resolver=env.resolver,
        targets=(env.request,),
        refresh_interval_seconds=10.0,
        retry_interval_seconds=2.0,
        sleeper=sleeper,
    )
    await warmer.run_once()
    warm_read = await env.resolver.resolve(env.request)
    assert item_map(warm_read.available.items)["streaming"].available is True
    assert item_map(warm_read.effective.items)["streaming"].effective is True

    # 3) TTL expired: unavailable again (never treated as fresh authorization).
    env.clock.advance(31.0)
    expired = await env.resolver.resolve(env.request)
    assert item_map(expired.available.items)["streaming"].available is False
    assert item_map(expired.available.items)["streaming"].reason_code == "probe_stale"
    assert item_map(expired.effective.items)["streaming"].effective is False
    assert env.resolver.availability_cache_status(env.request) == "stale"

    # 4) Background refresh succeeds again: available.
    await env.resolver.wait_idle()
    revived = await env.resolver.resolve(env.request)
    assert item_map(revived.available.items)["streaming"].available is True
    # calls: cold hot-read refresh, warmer first round, stale hot-read refresh
    assert len(env.probe.calls) == 3
    await warmer.aclose()


@pytest.mark.asyncio
async def test_p3_ut22_failed_refresh_keeps_stale_or_error_and_never_grants():
    env = build_env(ttl_seconds=30.0)
    assert await env.resolver.warm(env.request) is True

    async def explode(context: ProbeContext) -> ProbeResult:
        raise RuntimeError(SECRET_MARKER)

    env.probe.handler = explode
    env.clock.advance(31.0)
    failed = await env.resolver.warm(env.request)
    assert failed is False
    assert env.resolver.availability_cache_status(env.request) == "stale"
    # The previous observation is retained but never served as authorization.
    lookup_value = env.availability_cache.lookup(env.resolver.availability_key(env.request))
    assert lookup_value.value is not None
    resolution = await env.resolver.resolve(env.request)
    assert item_map(resolution.available.items)["streaming"].available is False
    assert "stale" in item_map(resolution.available.items)["streaming"].reason_code


@pytest.mark.asyncio
async def test_p3_ut22_availability_and_policy_cache_key_fields_are_exact():
    assert set(AvailabilityCacheKey.model_fields) == {
        "deployment_identity",
        "engine_id",
        "protocol_id",
        "adapter_version",
        "config_schema_version",
        "probe_id",
        "probe_version",
        "declaration_digest",
        "workspace_generation",
    }
    expected_policy_fields = set(AvailabilityCacheKey.model_fields) | {
        "tenant_id",
        "business_scope",
        "workspace_id",
        "agent_id",
        "agent_published_version",
        "policy_provider_id",
        "policy_version",
        "policy_revision",
        "disabled_capabilities_digest",
        "execution_restriction_digest",
    }
    assert set(PolicyCacheKey.model_fields) == expected_policy_fields

    env = build_env()
    availability_key = env.resolver.availability_key(env.request)
    policy_key = env.resolver.policy_key(env.request)
    assert availability_key.deployment_identity == DEPLOYMENT_A
    assert (
        availability_key.declaration_digest
        == env.resolver.declared("react", "native", "v1").declaration_digest
    )
    assert policy_key.disabled_capabilities_digest == disabled_capabilities_digest(())
    # Digest helpers are canonical: order-insensitive and deduplicating.
    assert disabled_capabilities_digest(("streaming", "cancellation", "streaming")) == (
        disabled_capabilities_digest(("cancellation", "streaming"))
    )
    assert (
        canonical_digest(REACT_DECLARED)
        == env.resolver.declared("react", "native", "v1").declaration_digest
    )


@pytest.mark.asyncio
async def test_p3_ut22_every_cache_key_field_change_isolates_entries():
    clock = FakeClock()
    cache: CapabilityCache = CapabilityCache(
        ttl_seconds=30, capacity=8, clock=clock.now, retry_interval_seconds=1
    )

    async def loader() -> str:
        return "value"

    availability_key = AvailabilityCacheKey(
        deployment_identity="node",
        engine_id="react",
        protocol_id="native",
        adapter_version="v1",
        config_schema_version="v1",
        probe_id="probe",
        probe_version="v1",
        declaration_digest=ZERO64,
        workspace_generation=None,
    )
    assert await cache.refresh(availability_key, loader) == "value"
    availability_alternatives = {
        "deployment_identity": "node-b",
        "engine_id": "toolkit",
        "protocol_id": "native-b",
        "adapter_version": "v2",
        "config_schema_version": "v2",
        "probe_id": "probe-b",
        "probe_version": "v2",
        "declaration_digest": ONE64,
        "workspace_generation": 42,
    }
    for name, alternative in availability_alternatives.items():
        mutated = availability_key.model_copy(update={name: alternative})
        assert mutated != availability_key
        assert cache.lookup(mutated).status == "cold", name

    policy_key = PolicyCacheKey(
        deployment_identity="node",
        engine_id="react",
        protocol_id="native",
        adapter_version="v1",
        config_schema_version="v1",
        probe_id="probe",
        probe_version="v1",
        declaration_digest=ZERO64,
        workspace_generation=None,
        tenant_id=TENANT_A,
        business_scope="biz-1",
        workspace_id="ws-1",
        agent_id=AGENT_ID,
        agent_published_version=3,
        policy_provider_id="react-policy",
        policy_version="v1",
        policy_revision=1,
        disabled_capabilities_digest=disabled_capabilities_digest(()),
        execution_restriction_digest=ZERO64,
    )
    assert await cache.refresh(policy_key, loader) == "value"
    policy_alternatives = {
        **availability_alternatives,
        "tenant_id": TENANT_B,
        "business_scope": "biz-2",
        "workspace_id": "ws-2",
        "agent_id": uuid4(),
        "agent_published_version": 4,
        "policy_provider_id": "policy-b",
        "policy_version": "v2",
        "policy_revision": 2,
        "disabled_capabilities_digest": ONE64,
        "execution_restriction_digest": ONE64,
    }
    for name, alternative in policy_alternatives.items():
        mutated = policy_key.model_copy(update={name: alternative})
        assert mutated != policy_key
        assert cache.lookup(mutated).status == "cold", name

    # Capacity bound evicts oldest entries instead of growing without limit.
    small: CapabilityCache = CapabilityCache(
        ttl_seconds=30, capacity=2, clock=clock.now, retry_interval_seconds=1
    )

    async def other_loader() -> str:
        return "x"

    for index in range(3):
        await small.refresh(
            availability_key.model_copy(update={"declaration_digest": f"{index}" * 64}),
            other_loader,
        )
    assert small.size == 2


@pytest.mark.asyncio
async def test_p3_ut22_warmer_initial_population_refresh_and_close_without_task_leak():
    env = build_env(ttl_seconds=30.0)
    sleeper = GatedSleeper()
    warmer = CapabilityWarmer(
        resolver=env.resolver,
        targets=(env.request,),
        refresh_interval_seconds=10.0,
        retry_interval_seconds=2.0,
        sleeper=sleeper,
    )
    # Before start: nothing was probed and the view is unavailable.
    assert env.probe.calls == []
    assert env.resolver.availability_cache_status(env.request) == "cold"
    assert env.created == []  # no adapter factory ran for metadata or warming

    warmer.start()
    await sleeper.wait_parked()
    assert len(env.probe.calls) == 1  # initial round populated the cache
    assert env.created == []  # warmer must not create Adapter/Run objects
    warmed = await env.resolver.resolve(env.request)
    assert item_map(warmed.effective.items)["streaming"].effective is True

    # Before TTL expiry the warmer refreshes again (interval < ttl).
    sleeper.release()
    await sleeper.wait_parked()
    assert len(env.probe.calls) == 2
    assert sleeper.intervals == [10.0, 10.0]

    await warmer.aclose()
    await env.resolver.aclose()
    leftover = {task for task in asyncio.all_tasks() if task is not asyncio.current_task()}
    assert leftover == set()


@pytest.mark.asyncio
async def test_p3_ut22_warmer_retries_failed_round_at_bounded_interval():
    async def explode(context: ProbeContext) -> ProbeResult:
        raise RuntimeError(SECRET_MARKER)

    env = build_env(probe_handler=explode)
    warmer = CapabilityWarmer(
        resolver=env.resolver,
        targets=(env.request,),
        refresh_interval_seconds=10.0,
        retry_interval_seconds=2.0,
        sleeper=asyncio.sleep,
    )
    assert await warmer.run_once() is False
    assert warmer.next_refresh_delay == 2.0
    assert env.resolver.availability_cache_status(env.request) == "error"

    env.probe.handler = None  # deterministic success again
    assert await warmer.run_once() is True
    assert warmer.next_refresh_delay == 10.0
    resolution = await env.resolver.resolve(env.request)
    assert item_map(resolution.effective.items)["streaming"].effective is True
    await warmer.aclose()
    await env.resolver.aclose()


@pytest.mark.asyncio
async def test_p3_ut22_public_dto_shapes_expose_no_raw_probe_or_internal_snapshots():
    env = build_env()
    assert await env.resolver.warm(env.request) is True
    resolution = await env.resolver.resolve(env.request)
    assert set(AvailableCapabilities.model_fields) == {
        "contract_version",
        "engine_id",
        "protocol_id",
        "adapter_version",
        "probe_id",
        "probe_version",
        "observed_at",
        "declaration_digest",
        "deployment_digest",
        "items",
    }
    assert set(EffectiveCapabilities.model_fields) == {
        "contract_version",
        "engine_id",
        "protocol_id",
        "adapter_version",
        "tenant_id",
        "declaration_digest",
        "probe_id",
        "probe_version",
        "policy_provider_id",
        "policy_version",
        "policy_revision",
        "items",
        "required_capabilities_missing",
    }
    # No raw-payload/exception/path fields exist anywhere in the DTO tree.
    dump = json.dumps(json.loads(resolution.available.model_dump_json()))
    for forbidden_key in ("raw", "payload", "message", "stderr", "path", "url", "exception"):
        assert forbidden_key not in dump
    assert isinstance(resolution.declared, DeclaredCapabilities)


# ---------------------------------------------------------------------------
# Review regressions: cache eviction race, warmer resilience, diagnostics,
# policy timeout, and the required-capability-missing startup gate semantics.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_review_cache_load_finishing_after_eviction_returns_its_value():
    """Important-1: a slow load must not die on eviction by a concurrent key."""
    clock = FakeClock()
    cache: CapabilityCache = CapabilityCache(
        ttl_seconds=30, capacity=1, clock=clock.now, retry_interval_seconds=0
    )
    key_a = availability_key_for(1)
    key_b = availability_key_for(2)
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_loader() -> str:
        started.set()
        await release.wait()
        return "value-a"

    async def fast_loader() -> str:
        return "value-b"

    pending = asyncio.create_task(cache.refresh(key_a, slow_loader))
    await asyncio.wait_for(started.wait(), timeout=1.0)
    # Completing key B under capacity 1 evicts the in-flight key A entry.
    assert await cache.refresh(key_b, fast_loader) == "value-b"
    release.set()
    assert await asyncio.wait_for(pending, timeout=1.0) == "value-a"


@pytest.mark.asyncio
async def test_review_concurrent_refreshes_under_capacity_pressure_keep_results():
    """Important-1: no success may be reported as a failure under eviction."""
    clock = FakeClock()
    capacity = 2
    keys = [availability_key_for(index) for index in range(1, 5)]
    cache: CapabilityCache = CapabilityCache(
        ttl_seconds=30, capacity=capacity, clock=clock.now, retry_interval_seconds=0
    )
    release = asyncio.Event()
    state = {"started": 0}
    all_started = asyncio.Event()

    def gated_loader(index: int):
        async def load() -> str:
            state["started"] += 1
            if state["started"] == len(keys):
                all_started.set()
            await release.wait()
            return f"value-{index}"

        return load

    tasks = [
        asyncio.create_task(cache.refresh(key, gated_loader(index)))
        for index, key in enumerate(keys, start=1)
    ]
    await asyncio.wait_for(all_started.wait(), timeout=1.0)
    release.set()
    results = await asyncio.wait_for(asyncio.gather(*tasks), timeout=1.0)
    assert results == [f"value-{index}" for index in range(1, 5)]
    assert cache.size <= capacity


@pytest.mark.asyncio
async def test_review_cache_load_failure_emits_sanitized_warning(caplog):
    """Important-3: swallowed port failures must still leave a diagnosis."""

    class ExplodingLoaderError(RuntimeError):
        pass

    clock = FakeClock()
    cache: CapabilityCache = CapabilityCache(
        ttl_seconds=30, capacity=4, clock=clock.now, retry_interval_seconds=0
    )

    async def explode() -> str:
        raise ExplodingLoaderError(f"upstream {SECRET_MARKER} at /srv/secret/path")

    with caplog.at_level(logging.WARNING):
        assert await cache.refresh(availability_key_for(1), explode) is None
    records = [
        record for record in caplog.records if "capability cache load failed" in record.getMessage()
    ]
    assert records, caplog.text
    assert records[0].error_type == "ExplodingLoaderError"
    # T-strength-3: scan every rendered channel of the record (message, args,
    # and every non-standard attribute), not a fixed key whitelist, so a new
    # extra field such as "detail" can never bypass the leak scan.
    diagnostics = " | ".join(rendered_log_text(record) for record in records)
    assert SECRET_MARKER not in diagnostics
    assert "/srv" not in diagnostics


@pytest.mark.asyncio
async def test_review_warmer_round_exception_keeps_loop_alive_with_backoff(caplog):
    """Important-2: one raising round may not end the freshness loop."""
    env = build_env()
    sleeper = GatedSleeper()
    warmer = CapabilityWarmer(
        resolver=env.resolver,
        # An unregistered triple raises ConfigurationError out of warm().
        targets=(make_request(engine_id="ghost"),),
        refresh_interval_seconds=10.0,
        retry_interval_seconds=2.0,
        sleeper=sleeper,
    )
    try:
        with caplog.at_level(logging.WARNING):
            warmer.start()
            await sleeper.wait_parked()
        assert sleeper.intervals == [2.0]
        assert warmer.next_refresh_delay == 2.0
        warnings = [
            record
            for record in caplog.records
            if "capability warm round failed" in record.getMessage()
        ]
        assert warnings, caplog.text
        assert warnings[0].error_type == "ConfigurationError"

        sleeper.release()
        await sleeper.wait_parked()
        assert sleeper.intervals == [2.0, 2.0]

        # T-strength-2: a declared round error whose raw text carries
        # SECRET_MARKER proves the warning never renders exception text. An
        # implementation changed to logger.warning(f"failed: {exc}") would put
        # the marker into the rendered message; an extra={"detail": ...} leak
        # would land in the full-attribute scan. Both are forbidden.
        marker_sleeper = GatedSleeper()
        marker_resolver = _FailingWarmResolver(_marker_validation_error)
        marker_warmer = CapabilityWarmer(
            resolver=marker_resolver,
            targets=(env.request,),
            refresh_interval_seconds=10.0,
            retry_interval_seconds=2.0,
            sleeper=marker_sleeper,
        )
        try:
            records_before = len(caplog.records)
            with caplog.at_level(logging.WARNING):
                marker_warmer.start()
                await marker_sleeper.wait_parked()
            assert marker_resolver.warm_calls == 1
            assert marker_sleeper.intervals == [2.0]
            marker_warnings = [
                record
                for record in caplog.records[records_before:]
                if "capability warm round failed" in record.getMessage()
            ]
            assert marker_warnings, caplog.text
            assert marker_warnings[0].error_type == "ValidationError"
            diagnostics = " | ".join(
                rendered_log_text(record) for record in caplog.records[records_before:]
            )
            assert SECRET_MARKER not in diagnostics
            assert "/srv" not in diagnostics
        finally:
            await marker_warmer.aclose()
    finally:
        await warmer.aclose()
        await env.resolver.aclose()


@pytest.mark.asyncio
async def test_review_policy_provider_timeout_is_bounded_and_releases_inflight():
    """Important-4: a hanging policy source must fail closed, not wedge."""
    started = asyncio.Event()
    release = asyncio.Event()

    async def hanging(context: PolicyContext) -> PolicyDecisionSet:
        started.set()
        await release.wait()
        return allow_all_policy(context)

    env = build_env(policy_handler=hanging, policy_timeout_seconds=0.05)
    try:
        assert await asyncio.wait_for(env.resolver.warm(env.request), timeout=1.0) is False
        assert started.is_set()
        await asyncio.wait_for(env.resolver.wait_idle(), timeout=1.0)
        assert env.resolver.policy_cache_status(env.request) == "error"
        resolution = await env.resolver.resolve(env.request)
        assert resolution.policy is None
        assert item_map(resolution.effective.items)["streaming"].reason_code == (
            "policy_unavailable"
        )
        assert resolution.startup_allowed is False
        dump = resolution.effective.model_dump_json()
        assert SECRET_MARKER not in dump
    finally:
        release.set()
        await env.resolver.aclose()


def test_review_resolver_requires_positive_policy_timeout():
    env_kwargs = {
        "ttl_seconds": 30.0,
        "capacity": 8,
        "clock": FakeClock().now,
        "retry_interval_seconds": 5.0,
    }
    adapters, _ = build_registry((make_descriptor(),))
    with pytest.raises(ValueError):
        CapabilityResolver(
            registry=adapters,
            probe=FakeProbe(),
            policy_provider=FakePolicyProvider(),
            workspace_port=FakeWorkspacePort(),
            availability_cache=CapabilityCache(**env_kwargs),
            policy_cache=CapabilityCache(**env_kwargs),
            deployment_identity=DEPLOYMENT_A,
            probe_timeout_seconds=30.0,
            policy_timeout_seconds=0.0,
            probe_max_concurrency=4,
            clock=FakeClock().now,
        )


@pytest.mark.asyncio
async def test_review_agent_disabled_narrowing_is_not_a_missing_required_capability():
    """Spec (a): supported configuration narrowing must not block startup."""
    env = build_env()
    request = make_request(disabled=("streaming",))
    assert await env.resolver.warm(request) is True
    resolution = await env.resolver.resolve(request)
    effective = item_map(resolution.effective.items)
    assert effective["streaming"].effective is False
    assert effective["streaming"].reason_code == "agent_disabled"
    assert resolution.effective.required_capabilities_missing == ()
    assert resolution.startup_allowed is True


@pytest.mark.asyncio
async def test_review_policy_layer_denials_are_not_missing_required_capabilities():
    env = build_env()
    denials = {
        ("streaming", "platform"): "platform_denied",
        ("cancellation", "tenant"): "tenant_denied",
        ("tool_calling", "agent"): "agent_disabled",
        ("native_events", "execution"): "execution_denied",
    }

    async def denying(context: PolicyContext) -> PolicyDecisionSet:
        return make_policy(context, denials)

    env.policy.handler = denying
    assert await env.resolver.warm(env.request) is True
    resolution = await env.resolver.resolve(env.request)
    effective = item_map(resolution.effective.items)
    for name, reason in denials.items():
        assert effective[name[0]].effective is False
        assert effective[name[0]].reason_code == reason
    assert resolution.effective.required_capabilities_missing == ()
    assert resolution.startup_allowed is True


@pytest.mark.asyncio
async def test_review_deployment_or_policy_trust_gaps_still_block_startup():
    """Spec (a) guard: deployment and trust gaps keep blocking startup."""

    async def nothing_deployed(context: ProbeContext) -> ProbeResult:
        return ProbeResult(
            engine_id=context.engine_id,
            protocol_id=context.protocol_id,
            adapter_version=context.adapter_version,
            probe_id=context.probe_id,
            probe_version=context.probe_version,
            observed_at=FIXED,
            deployment_digest=ZERO64,
            items=probe_items(set()),
        )

    env = build_env(probe_handler=nothing_deployed)
    try:
        assert await env.resolver.warm(env.request) is True
        blocked = await env.resolver.resolve(env.request)
        assert "streaming" in blocked.effective.required_capabilities_missing
        assert blocked.startup_allowed is False
    finally:
        await env.resolver.aclose()

    # An expired observation is likewise an infrastructure gap, not narrowing.
    stale_env = build_env(ttl_seconds=30.0)
    try:
        assert await stale_env.resolver.warm(stale_env.request) is True
        stale_env.clock.advance(31.0)
        stale = await stale_env.resolver.resolve(stale_env.request)
        assert item_map(stale.available.items)["streaming"].reason_code == "probe_stale"
        assert "streaming" in stale.effective.required_capabilities_missing
        assert stale.startup_allowed is False
    finally:
        await stale_env.resolver.aclose()

    # A cold policy source fails closed the same way.
    cold_env = build_env()
    try:
        cold = await cold_env.resolver.resolve(cold_env.request)
        assert "streaming" in cold.effective.required_capabilities_missing
        assert cold.startup_allowed is False
    finally:
        await cold_env.resolver.aclose()


# ---------------------------------------------------------------------------
# Acceptance regressions: startup-gate bypass via contradictory probe
# observations, warmer fault tolerance beyond the declared error surface,
# the Available => Declared clamp, and per-reason startup-gate coverage.
# ---------------------------------------------------------------------------


class _FailingWarmResolver:
    """Stub resolver whose awaited warm() raises a caller-chosen error."""

    def __init__(self, error_factory) -> None:
        self._error_factory = error_factory
        self.warm_calls = 0

    async def warm(self, request: CapabilityResolutionRequest) -> bool:
        self.warm_calls += 1
        raise self._error_factory()


def _marker_runtime_error() -> RuntimeError:
    return RuntimeError(f"unexpected warmer failure {SECRET_MARKER} at /srv/secret/path")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "illegal_reason",
    [
        "not_declared",
        "policy_unavailable",
        "platform_denied",
        "tenant_denied",
        "agent_disabled",
        "execution_denied",
    ],
)
async def test_review_declared_true_illegal_probe_reason_degrades_to_infra_code(illegal_reason):
    """W1: a denial for a declared capability can only carry infrastructure codes.

    A probe that answers available=false for a *declared* capability with
    ``not_declared`` or any policy-layer reason is self-contradictory: the
    sanitizer must degrade it to ``probe_unavailable`` so the startup gate
    counts it as an infrastructure gap, never pass the contradictory code
    through as if it were benign narrowing.
    """
    env = build_env(probe_handler=deny_one_probe_answer("streaming", illegal_reason))
    try:
        assert await env.resolver.warm(env.request) is True
        resolution = await env.resolver.resolve(env.request)
        available = item_map(resolution.available.items)
        assert available["streaming"].available is False
        assert available["streaming"].reason_code == "probe_unavailable"
        effective = item_map(resolution.effective.items)
        assert effective["streaming"].effective is False
        assert effective["streaming"].reason_code == "probe_unavailable"
        assert "streaming" in resolution.effective.required_capabilities_missing
        assert resolution.startup_allowed is False
    finally:
        await env.resolver.aclose()


@pytest.mark.asyncio
async def test_review_probe_claim_on_undeclared_capability_is_clamped():
    """W3: the Available => Declared clamp holds even when the probe lies.

    The probe answers available=true for capabilities the registry never
    declared; the Available layer itself (not just Effective) must carry
    them as ``available=false, reason="not_declared"``.
    """
    env = build_env()

    async def claims_everything(context: ProbeContext) -> ProbeResult:
        return ProbeResult(
            engine_id=context.engine_id,
            protocol_id=context.protocol_id,
            adapter_version=context.adapter_version,
            probe_id=context.probe_id,
            probe_version=context.probe_version,
            observed_at=FIXED,
            deployment_digest=DEPLOYMENT_DIGEST,
            items=tuple(capability_item(name, True, "allowed") for name in CAPABILITY_ORDER),
        )

    env.probe.handler = claims_everything
    try:
        assert await env.resolver.warm(env.request) is True
        resolution = await env.resolver.resolve(env.request)
        available = item_map(resolution.available.items)
        undeclared = [name for name in CAPABILITY_ORDER if not getattr(REACT_DECLARED, name)]
        assert undeclared  # persistent_session, session_resume, workspace_required, ...
        for name in undeclared:
            assert available[name].available is False
            assert available[name].reason_code == "not_declared"
        for name in ("streaming", "cancellation", "tool_calling", "native_events"):
            assert available[name].available is True
        # A lying probe widens nothing, so the gate stays unblocked.
        assert resolution.effective.required_capabilities_missing == ()
        assert resolution.startup_allowed is True
    finally:
        await env.resolver.aclose()


@pytest.mark.asyncio
async def test_review_warmer_undocumented_round_exception_keeps_loop_alive(caplog):
    """W2: any round exception retries at the bounded interval; the loop survives.

    RuntimeError is outside the historically declared round-error tuple; the
    loop must log a sanitized warning and keep rescheduling instead of dying
    silently and re-raising the original error out of aclose().
    """
    sleeper = GatedSleeper()
    resolver = _FailingWarmResolver(_marker_runtime_error)
    warmer = CapabilityWarmer(
        resolver=resolver,
        targets=(make_request(),),
        refresh_interval_seconds=10.0,
        retry_interval_seconds=2.0,
        sleeper=sleeper,
    )
    try:
        with caplog.at_level(logging.WARNING):
            warmer.start()
            await sleeper.wait_parked()
        assert resolver.warm_calls == 1
        assert sleeper.intervals == [2.0]
        assert warmer.next_refresh_delay == 2.0
        warnings = [
            record
            for record in caplog.records
            if "capability warm round failed" in record.getMessage()
        ]
        assert warnings, caplog.text
        assert warnings[0].error_type == "RuntimeError"
        # Only the exception type name may be rendered, never the raw text.
        diagnostics = " | ".join(rendered_log_text(record) for record in warnings)
        assert SECRET_MARKER not in diagnostics
        assert "/srv" not in diagnostics

        # The loop must reach and survive a second failing round.
        sleeper.release()
        await sleeper.wait_parked()
        assert resolver.warm_calls == 2
        assert sleeper.intervals == [2.0, 2.0]
    finally:
        await warmer.aclose()


def _gate_env(**overrides):
    """Env with a fully declared profile and a trusted available workspace.

    Kept separate from the narrowing cases so a required-missing assertion can
    demand an exact one-element ``required_capabilities_missing`` tuple without
    the workspace narrowing path adding a second entry.
    """
    declared = EngineCapabilities(
        streaming=True,
        cancellation=True,
        tool_calling=True,
        native_events=True,
        workspace_required=True,
    )
    overrides.setdefault("descriptors", (make_descriptor(declared=declared),))
    overrides.setdefault(
        "workspace_generations",
        {("biz-1", "ws-1"): AvailabilityGeneration(generation=7, available=True)},
    )
    return build_env(**overrides)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("reason", "target"),
    [
        ("probe_unavailable", "streaming"),
        ("workspace_unavailable", "workspace_required"),
    ],
)
async def test_review_each_infrastructure_probe_reason_enters_required_missing(reason, target):
    """T-strength-1a: infrastructure denial codes on a declared item arm the gate."""
    env = _gate_env(probe_handler=deny_one_probe_answer(target, reason))
    try:
        assert await env.resolver.warm(env.request) is True
        resolution = await env.resolver.resolve(env.request)
        available = item_map(resolution.available.items)
        assert available[target].available is False
        assert available[target].reason_code == reason
        effective = item_map(resolution.effective.items)
        assert effective[target].effective is False
        assert effective[target].reason_code == reason
        assert resolution.effective.required_capabilities_missing == (target,)
        assert resolution.startup_allowed is False
    finally:
        await env.resolver.aclose()


@pytest.mark.asyncio
async def test_review_observed_probe_timeout_enters_required_missing():
    """T-strength-1a: probe_timeout (the never-directly-gated blocking code).

    P3-UT-07 covers the Available layer here; this pins the full gate path: a
    timed-out probe observation must land in required_capabilities_missing and
    hold startup closed.
    """

    async def hanging(context: ProbeContext) -> ProbeResult:
        await asyncio.Event().wait()  # never completes; the bounded wait fires
        raise AssertionError("unreachable")

    env = _gate_env(probe_handler=hanging, probe_timeout_seconds=0.05)
    try:
        assert await env.resolver.warm(env.request) is True
        resolution = await env.resolver.resolve(env.request)
        effective = item_map(resolution.effective.items)
        assert effective["streaming"].effective is False
        assert effective["streaming"].reason_code == "probe_timeout"
        assert "streaming" in resolution.effective.required_capabilities_missing
        assert resolution.startup_allowed is False
    finally:
        await env.resolver.aclose()


@pytest.mark.asyncio
async def test_review_stale_availability_with_fresh_policy_enters_required_missing():
    """T-strength-1a: probe_stale blocks via the synthesized stale observation.

    The policy entry keeps a longer TTL so probe_stale -- not a concurrent
    policy gap -- is the sole blocking reason reaching the gate.
    """
    env = _gate_env(ttl_seconds=30.0, policy_ttl_seconds=300.0)
    try:
        assert await env.resolver.warm(env.request) is True
        env.clock.advance(31.0)
        resolution = await env.resolver.resolve(env.request)
        assert resolution.availability_status == "stale"
        assert resolution.policy_status == "fresh"
        effective = item_map(resolution.effective.items)
        assert effective["streaming"].effective is False
        assert effective["streaming"].reason_code == "probe_stale"
        assert "streaming" in resolution.effective.required_capabilities_missing
        assert resolution.startup_allowed is False
    finally:
        await env.resolver.aclose()


@pytest.mark.asyncio
async def test_review_policy_unavailable_alone_enters_required_missing():
    """T-strength-1a: the fifth blocking code (policy) arms the gate on its own.

    Availability is fresh and fully allowed; only the policy source is
    untrusted, so every declared capability becomes ``policy_unavailable``
    and blocks startup.
    """

    async def rogue(context: PolicyContext) -> PolicyDecisionSet:
        return allow_all_policy(context).model_copy(update={"policy_provider_id": "rogue"})

    env = _gate_env(policy_handler=rogue)
    try:
        # warm() refreshes availability first (succeeds), then policy (fails):
        # the gate input is exactly a fresh availability plus no policy source.
        assert await env.resolver.warm(env.request) is False
        resolution = await env.resolver.resolve(env.request)
        assert resolution.availability_status == "fresh"
        effective = item_map(resolution.effective.items)
        for name in ("streaming", "cancellation", "tool_calling", "native_events"):
            assert effective[name].effective is False
            assert effective[name].reason_code == "policy_unavailable"
            assert name in resolution.effective.required_capabilities_missing
        assert resolution.startup_allowed is False
    finally:
        await env.resolver.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("reason", "target", "layer"),
    [
        ("not_declared", "persistent_session", None),
        ("platform_denied", "streaming", "platform"),
        ("tenant_denied", "cancellation", "tenant"),
        ("agent_disabled", "tool_calling", "agent"),
        ("execution_denied", "native_events", "execution"),
    ],
)
async def test_review_each_narrowing_reason_stays_out_of_required_missing(reason, target, layer):
    """T-strength-1b: supported narrowing never arms the required-missing gate."""
    env = build_env()
    if layer is not None:
        denials = {(target, layer): reason}

        async def denying(context: PolicyContext) -> PolicyDecisionSet:
            return make_policy(context, denials)

        env.policy.handler = denying
    try:
        assert await env.resolver.warm(env.request) is True
        resolution = await env.resolver.resolve(env.request)
        effective = item_map(resolution.effective.items)
        assert effective[target].effective is False
        assert effective[target].reason_code == reason
        assert target not in resolution.effective.required_capabilities_missing
        assert resolution.effective.required_capabilities_missing == ()
        assert resolution.startup_allowed is True
    finally:
        await env.resolver.aclose()


# ---------------------------------------------------------------------------
# R-17 / R-21 adjudication regressions: trusted revision reads, live-key
# rotation, echo validation, source-failure surfacing, and the unique
# Effective projections.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_review_policy_revision_is_observed_from_the_provider_not_the_request():
    """R-17: policy revision is a live provider observation, never DTO input."""
    env = build_env()
    assert await env.resolver.warm(env.request) is True
    assert env.resolver.policy_key(env.request).policy_revision == env.policy.revision
    resolution = await env.resolver.resolve(env.request)
    assert resolution.effective.policy_revision == env.policy.revision
    # The provider receives exactly the trusted scope fields of the request.
    scope = env.policy.revision_calls[0]
    assert isinstance(scope, PolicyRevisionScope)
    assert scope.tenant_id == TENANT_A
    assert scope.business_scope == "biz-1"
    assert scope.workspace_id == "ws-1"
    assert scope.agent_id == AGENT_ID
    assert scope.agent_published_version == 3
    # And the PolicyContext built for the load round carries the observed value.
    assert env.policy.calls[0].policy_revision == env.policy.revision

    # A provider-side revision advance rotates the policy key immediately: the
    # old fresh entry no longer answers, the hot read fails closed until the
    # refresh for the new revision completes, and Effective reports the new
    # observed revision throughout.
    env.policy.revision = 2
    assert env.resolver.policy_key(env.request).policy_revision == 2
    assert env.resolver.policy_cache_status(env.request) == "cold"
    cold = await env.resolver.resolve(env.request)
    assert cold.effective.policy_revision == 2
    assert cold.policy is None
    assert item_map(cold.effective.items)["streaming"].reason_code == "policy_unavailable"
    await env.resolver.wait_idle()
    refreshed = await env.resolver.resolve(env.request)
    assert refreshed.effective.policy_revision == 2
    assert item_map(refreshed.effective.items)["streaming"].effective is True
    await env.resolver.aclose()


@pytest.mark.asyncio
async def test_review_provider_revision_echo_mismatch_records_error_not_grant():
    """R-17: a resolve() result echoing a stale revision takes the mismatch path."""

    async def lagging(context: PolicyContext) -> PolicyDecisionSet:
        # Echoes one revision behind the value the resolver just observed.
        return allow_all_policy(context).model_copy(
            update={"policy_revision": context.policy_revision - 1}
        )

    env = build_env(policy_handler=lagging)
    assert await env.resolver.warm(env.request) is False
    assert env.resolver.policy_cache_status(env.request) == "error"
    resolution = await env.resolver.resolve(env.request)
    effective = item_map(resolution.effective.items)
    assert effective["streaming"].effective is False
    assert effective["streaming"].reason_code == "policy_unavailable"
    assert "streaming" in resolution.effective.required_capabilities_missing
    assert resolution.startup_allowed is False
    # Fail-closed Effective still reports the live observation, never the echo.
    assert resolution.effective.policy_revision == env.policy.revision
    await env.resolver.aclose()


@pytest.mark.asyncio
async def test_review_revision_source_failure_raises_policy_source_unavailable():
    """R-17: a raising current_revision() surfaces, is never swallowed or zeroed."""
    env = build_env()
    env.policy.revision_error = RuntimeError(f"revision store {SECRET_MARKER} down")
    try:
        with pytest.raises(PolicySourceUnavailableError):
            await env.resolver.resolve(env.request)
        with pytest.raises(PolicySourceUnavailableError):
            await env.resolver.warm(env.request)
        with pytest.raises(PolicySourceUnavailableError):
            env.resolver.policy_key(env.request)
        # _key_inputs reads both generations, so even the availability key path
        # surfaces the failure instead of defaulting anything.
        with pytest.raises(PolicySourceUnavailableError):
            env.resolver.availability_key(env.request)
        assert env.policy.calls == []  # no resolve round ever started
    finally:
        await env.resolver.aclose()


def test_review_policy_revision_scope_dto_is_strict_and_frozen():
    """R-17: PolicyRevisionScope keeps the shared strict/frozen/forbid contract."""
    scope = PolicyRevisionScope(tenant_id=TENANT_A)
    assert scope.contract_version == "v1"
    assert scope.business_scope is None
    assert scope.workspace_id is None
    assert scope.agent_id is None
    assert scope.agent_published_version is None
    # R-17: this DTO defines the entire trusted face of the synchronous
    # revision read. The field set is closed to exactly these six keys -- a
    # silently added 7th field (even optional) would widen what composition
    # may inject into current_revision() and must fail here, not in review.
    assert set(PolicyRevisionScope.model_fields) == {
        "contract_version",
        "tenant_id",
        "business_scope",
        "workspace_id",
        "agent_id",
        "agent_published_version",
    }
    with pytest.raises(ValidationError):
        PolicyRevisionScope.model_validate({"tenant_id": TENANT_A, "policy_revision": 4})
    with pytest.raises(ValidationError):
        PolicyRevisionScope(tenant_id="")
    with pytest.raises(ValidationError):
        PolicyRevisionScope(tenant_id=TENANT_A, agent_published_version=-1)
    with pytest.raises(ValidationError):
        # Frozen contracts reject mutation.
        scope.tenant_id = "other"


def test_review_trusted_policy_provider_signatures_are_sync_read_async_resolve():
    """03 §4.2: current_revision is synchronous/local; resolve is asynchronous.

    The "sync, no remote I/O, hot-path allowed" contract on current_revision
    is part of the trusted-port ruling, yet a runtime_checkable protocol can
    only test member existence and never distinguishes a sync def from an
    async def -- an isinstance() check would pass a coroutine current_revision
    unchanged. TrustedPolicyProvider is therefore deliberately left
    non-runtime_checkable, and the signatures are pinned directly on the
    protocol class attributes via inspect (same precedent as
    test_agent_execution_contract_probe.py).
    """
    assert not inspect.iscoroutinefunction(TrustedPolicyProvider.current_revision)
    assert inspect.iscoroutinefunction(TrustedPolicyProvider.resolve)


@pytest.mark.asyncio
async def test_review_effective_projection_functions_are_the_unique_canonical_views():
    """R-21: flags and views are complete, ordered, and never omit False items."""
    env = build_env()
    denials = {("tool_calling", "agent"): "agent_disabled"}

    async def denying(context: PolicyContext) -> PolicyDecisionSet:
        return make_policy(context, denials)

    env.policy.handler = denying
    assert await env.resolver.warm(env.request) is True
    resolution = await env.resolver.resolve(env.request)
    effective = resolution.effective

    flags = effective_capability_flags(effective)
    assert list(flags) == list(CAPABILITY_ORDER)  # 11 keys, canonical order
    assert len(flags) == 11
    # Declared-and-allowed stays True; denials and non-declared stay explicit.
    assert flags["streaming"] is True
    assert flags["tool_calling"] is False
    assert flags["persistent_session"] is False  # not declared: never omitted

    views = effective_capability_views(effective)
    assert isinstance(views, tuple)
    assert [view.name for view in views] == list(CAPABILITY_ORDER)
    assert all(isinstance(view, EffectiveCapabilityDecision) for view in views)
    # The two projections describe one and the same semantics.
    assert {view.name: view.effective for view in views} == flags
    by_name = {item.name: item for item in effective.items}
    for view in views:
        assert view == by_name[view.name]  # name/effective/reason triple preserved
    await env.resolver.aclose()


def test_review_execution_restriction_digest_is_canonical_with_empty_constant():
    """R-17 addendum: one canonical digest shape shared with disabled capabilities."""
    assert execution_restriction_digest(()) == NO_EXECUTION_RESTRICTIONS
    assert NO_EXECUTION_RESTRICTIONS == (
        "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"
    )
    # Order- and duplicate-insensitive, identical canonical form to the
    # disabled-capabilities digest for the same string set.
    assert execution_restriction_digest(("b", "a", "b")) == execution_restriction_digest(("a", "b"))
    assert execution_restriction_digest(("streaming",)) == disabled_capabilities_digest(
        ("streaming",)
    )
    assert execution_restriction_digest(()) != execution_restriction_digest(("x",))
