"""T7 wiring: production trusted ports, the composition seam, the four-state matrix.

Judgement map (04 P3-IT-21/22, P3-UT-27/28, remapped rulings R-42..R-52):

* D1 - the declaration-derived production probe (never an Adapter call);
* D2 - the platform allow-list policy source with a scope-stable revision;
* D3 - the honest always-empty trusted workspace port;
* D4 - the settings-to-constructor mapping, the single POSIX clock, the warm
  target guard and the "construct nothing while off" rule;
* R-48 - the runtime fingerprint exclude set (a real defect repair);
* R-50/R-48 - the Worker rollout gate and its read-once discipline;
* R-52 - the six-key ExecutionConfig projection parity;
* T4 carry-over - constructor bounds and one port observation per round.
"""

import ast
import asyncio
import json
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from agent_platform.applications.platform_runtime import runtime_composition
from agent_platform.core_platform.agent_execution.capability import production as ports_production
from agent_platform.core_platform.agent_execution.capability.ports import (
    PolicyRevisionScope,
    ProbeContext,
    WorkspaceScope,
)
from agent_platform.core_platform.agent_execution.capability.resolver import (
    CapabilityResolution,
    CapabilityResolutionRequest,
    CapabilityResolver,
)
from agent_platform.core_platform.agent_execution.contracts.capabilities import (
    CAPABILITY_ORDER,
    NO_EXECUTION_RESTRICTIONS,
    UNOBSERVED_DIGEST,
    AvailableCapabilities,
    CapabilityDecision,
    CapabilityPolicy,
    DeclaredCapabilities,
    EffectiveCapabilities,
    EffectiveCapabilityDecision,
    EngineCapabilities,
    PolicyDecisionSet,
    PolicyLayerDecision,
    PolicyLayerVersion,
    canonical_digest,
)
from agent_platform.core_platform.agent_execution.contracts.config import (
    EngineIdentity,
    ExecutionConfig,
    ReactConfig,
    execution_config_from_agent_config,
)
from agent_platform.core_platform.agent_execution.contracts.handle import ExecutionHandle
from agent_platform.core_platform.agent_execution.contracts.instructions import (
    REACT_INSTRUCTION_PROVIDER_ID,
    REACT_INSTRUCTION_PROVIDER_VERSION,
    InstructionInput,
    PreparedInstructions,
)
from agent_platform.core_platform.agent_execution.contracts.request import ExecutionRequest
from agent_platform.core_platform.agent_execution.contracts.result import ExecutionResult
from agent_platform.core_platform.agent_execution.contracts.snapshots import SNAPSHOT_COLUMNS
from agent_platform.core_platform.agent_execution.orchestration import execution_context
from agent_platform.core_platform.agent_execution.orchestration.execution_context import (
    PRODUCTION_ADAPTER_SELECTOR,
    ExecutionContext,
    build_execution_context,
    enforce_execution_rollout,
    execution_config_from_context,
    execution_rollout_fault,
)
from agent_platform.core_platform.agent_execution.orchestration.orchestrator import (
    ExecutionOrchestrator,
)
from agent_platform.core_platform.agent_execution.registry import (
    AdapterDescriptor,
    AdapterRegistry,
    EngineDescriptor,
    EngineRegistry,
    ProtocolDescriptor,
    ProtocolRegistry,
)
from agent_platform.core_platform.agent_runtime.schemas import RuntimeFault
from agent_platform.core_platform.agent_runtime.worker import RuntimeWorker
from agent_platform.core_platform.platform_services.platform_settings.settings import Settings
from agent_platform.extension_contracts import (
    DEFAULT_BUSINESS_ID,
    DEFAULT_WORKSPACE_ID,
    BusinessScope,
)

RUN_ID = UUID("70000000-0000-4000-8000-000000000001")
AGENT_ID = UUID("70000000-0000-4000-8000-000000000002")
OWNER = UUID("70000000-0000-4000-8000-000000000003")
TENANT_ID = "local"

REACT_DECLARED = EngineCapabilities(
    streaming=True,
    cancellation=True,
    tool_calling=True,
    native_events=True,
)

_SRC = Path(__file__).parents[1] / "src" / "agent_platform"


def run(coroutine):
    return asyncio.run(coroutine)


def build_registry(factory=None, **descriptor_updates) -> AdapterRegistry:
    """Production React registration whose factory never runs a Run.

    The default factory raises: a trusted port must never construct an Adapter
    (R-42), and a composition that resolved one would be a defect rather than a
    test artifact. Matrix tests pass an adapter factory explicitly.
    """
    engines = EngineRegistry()
    engines.register(EngineDescriptor(engine_id="react"))
    protocols = ProtocolRegistry()
    protocols.register(ProtocolDescriptor(protocol_id="native"))
    registry = AdapterRegistry(engines, protocols)
    registry.register(react_descriptor(**descriptor_updates), factory or _never_resolve)
    return registry


def react_descriptor(**updates) -> AdapterDescriptor:
    values = {
        "engine_id": "react",
        "protocol_id": "native",
        "adapter_version": "v1",
        "config_schema": ReactConfig,
        "config_schema_version": "v1",
        "declared": REACT_DECLARED,
        "declared_schema_version": "v1",
        "probe_id": "react-probe",
        "probe_version": "v1",
        "policy_provider_id": "react-policy",
        "policy_version": "v1",
        "instruction_provider_id": REACT_INSTRUCTION_PROVIDER_ID,
        "provider_version": REACT_INSTRUCTION_PROVIDER_VERSION,
    }
    values.update(updates)
    return AdapterDescriptor(**values)


def _never_resolve():
    raise AssertionError("a production trusted port must never construct an Adapter")


def probe_context(**updates) -> ProbeContext:
    values = {
        "deployment_identity": "default",
        "engine_id": "react",
        "protocol_id": "native",
        "adapter_version": "v1",
        "config_schema_version": "v1",
        "probe_id": "react-probe",
        "probe_version": "v1",
        "declaration_digest": canonical_digest(REACT_DECLARED),
        "workspace_generation": None,
    }
    values.update(updates)
    return ProbeContext(**values)


def policy_context(**updates):
    from agent_platform.core_platform.agent_execution.capability.ports import PolicyContext

    values = {
        "engine_id": "react",
        "protocol_id": "native",
        "adapter_version": "v1",
        "config_schema_version": "v1",
        "deployment_identity": "default",
        "declaration_digest": canonical_digest(REACT_DECLARED),
        "probe_id": "react-probe",
        "probe_version": "v1",
        "workspace_generation": None,
        "tenant_id": TENANT_ID,
        "business_scope": DEFAULT_BUSINESS_ID,
        "workspace_id": DEFAULT_WORKSPACE_ID,
        "agent_id": AGENT_ID,
        "agent_published_version": 3,
        "policy_provider_id": "react-policy",
        "policy_version": "v1",
        "policy_revision": 0,
        "disabled_capabilities": (),
        "execution_restriction_digest": NO_EXECUTION_RESTRICTIONS,
    }
    values.update(updates)
    return PolicyContext(**values)


def resolution_request(**updates) -> CapabilityResolutionRequest:
    values = {
        "engine_id": "react",
        "protocol_id": "native",
        "adapter_version": "v1",
        "tenant_id": TENANT_ID,
        "business_scope": DEFAULT_BUSINESS_ID,
        "workspace_id": DEFAULT_WORKSPACE_ID,
        "execution_restriction_digest": NO_EXECUTION_RESTRICTIONS,
    }
    values.update(updates)
    return CapabilityResolutionRequest(**values)


# --------------------------------------------------------------------------- #
# D1: the declaration-derived production probe (R-42)                           #
# --------------------------------------------------------------------------- #


def test_probe_answers_from_registered_declarations_only():
    probe = ports_production.DeclarationDerivedDeploymentProbe(
        registry=build_registry(), clock=time.time
    )

    result = run(probe.probe(probe_context()))

    by_name = {item.name: item for item in result.items}
    assert tuple(by_name) == CAPABILITY_ORDER
    for name in CAPABILITY_ORDER:
        declared = bool(getattr(REACT_DECLARED, name))
        assert by_name[name].available is declared
        assert by_name[name].reason_code == ("allowed" if declared else "probe_unavailable")


def test_probe_echoes_the_context_identity_and_never_the_unobserved_digest():
    context = probe_context(
        probe_id="other-probe",
        probe_version="v2",
        deployment_identity="other-deployment",
    )
    probe = ports_production.DeclarationDerivedDeploymentProbe(
        registry=build_registry(), clock=time.time
    )

    result = run(probe.probe(context))

    assert result.probe_id == context.probe_id
    assert result.probe_version == context.probe_version
    assert (result.engine_id, result.protocol_id, result.adapter_version) == (
        context.engine_id,
        context.protocol_id,
        context.adapter_version,
    )
    assert result.deployment_digest != UNOBSERVED_DIGEST
    assert len(result.deployment_digest) == 64
    int(result.deployment_digest, 16)


def test_probe_deployment_digest_is_stable_and_identity_bound():
    probe = ports_production.DeclarationDerivedDeploymentProbe(
        registry=build_registry(), clock=time.time
    )

    first = run(probe.probe(probe_context()))
    second = run(probe.probe(probe_context()))
    other = run(probe.probe(probe_context(deployment_identity="other-deployment")))

    assert first.deployment_digest == second.deployment_digest
    assert first.deployment_digest != other.deployment_digest


def test_probe_observed_at_comes_from_the_injected_wall_clock():
    epoch_seconds = 1_800_000_000.0
    probe = ports_production.DeclarationDerivedDeploymentProbe(
        registry=build_registry(), clock=lambda: epoch_seconds
    )

    result = run(probe.probe(probe_context()))

    assert result.observed_at == datetime.fromtimestamp(epoch_seconds, UTC)


def test_probe_reads_metadata_only_and_never_consults_an_adapter():
    """R-42: 03 §4.2 forbids a probe that creates or consults an Adapter."""
    touched: list[str] = []

    class MetadataOnlyRegistry:
        def metadata(self, engine_id, protocol_id, adapter_version):
            touched.append("metadata")
            return react_descriptor()

        def __getattr__(self, name):
            touched.append(name)
            raise AssertionError(f"the probe must never reach registry.{name}")

    probe = ports_production.DeclarationDerivedDeploymentProbe(
        registry=MetadataOnlyRegistry(), clock=time.time
    )

    result = run(probe.probe(probe_context()))

    assert set(touched) == {"metadata"}
    assert len(touched) == 2
    assert result.deployment_digest != UNOBSERVED_DIGEST


def test_resolver_sanitizes_a_declared_false_answer_to_not_declared():
    """The probe answers ``probe_unavailable``; the clamp is what reaches evidence."""
    from agent_platform.core_platform.agent_execution.capability.resolver import CapabilityResolver

    registry = build_registry()
    probe = ports_production.DeclarationDerivedDeploymentProbe(registry=registry, clock=time.time)
    resolver = CapabilityResolver(
        registry=registry,
        probe=probe,
        policy_provider=ports_production.PlatformDefaultPolicyProvider(
            policy_provider_id="react-policy", policy_version="v1", clock=time.time
        ),
        workspace_port=ports_production.NoTrustedWorkspaceGeneration(),
        availability_cache=_cache(30),
        policy_cache=_cache(30),
        deployment_identity="default",
        probe_timeout_seconds=1,
        policy_timeout_seconds=1,
        probe_max_concurrency=1,
        clock=time.time,
    )

    async def scenario():
        await resolver.warm(resolution_request())
        resolution = await resolver.resolve(resolution_request())
        return {item.name: item for item in resolution.available.items}

    by_name = run(scenario())
    for name in CAPABILITY_ORDER:
        if name in ports_production.PHASE3_PLATFORM_CAPABILITY_ALLOWLIST:
            assert by_name[name].available is True
            assert by_name[name].reason_code == "allowed"
        else:
            assert by_name[name].available is False
            assert by_name[name].reason_code == "not_declared"


# --------------------------------------------------------------------------- #
# D2: the platform allow-list policy source (R-44)                              #
# --------------------------------------------------------------------------- #


def test_policy_ceiling_is_the_react_declaration_allow_list():
    provider = ports_production.PlatformDefaultPolicyProvider(
        policy_provider_id="react-policy", policy_version="v1", clock=time.time
    )

    decisions = run(provider.resolve(policy_context()))

    by_name = {
        decision.name: {layer.layer: layer for layer in decision.layers}
        for decision in decisions.decisions
    }
    assert tuple(by_name) == CAPABILITY_ORDER
    assert ports_production.PHASE3_PLATFORM_CAPABILITY_ALLOWLIST == frozenset(
        {"streaming", "cancellation", "tool_calling", "native_events"}
    )
    assert ports_production.PHASE3_PLATFORM_CAPABILITY_ALLOWLIST == {
        name for name in CAPABILITY_ORDER if getattr(REACT_DECLARED, name)
    }
    for name in CAPABILITY_ORDER:
        platform = by_name[name]["platform"]
        assert platform.allowed is (name in ports_production.PHASE3_PLATFORM_CAPABILITY_ALLOWLIST)
        assert platform.reason_code == (
            "allowed"
            if name in ports_production.PHASE3_PLATFORM_CAPABILITY_ALLOWLIST
            else "platform_denied"
        )
        assert by_name[name]["tenant"].allowed is True
        assert by_name[name]["tenant"].reason_code == "allowed"
        assert by_name[name]["execution"].allowed is True
        assert by_name[name]["execution"].reason_code == "allowed"


def test_policy_agent_layer_follows_the_published_disabled_capabilities():
    provider = ports_production.PlatformDefaultPolicyProvider(
        policy_provider_id="react-policy", policy_version="v1", clock=time.time
    )

    decisions = run(provider.resolve(policy_context(disabled_capabilities=("tool_calling",))))

    by_name = {
        decision.name: {layer.layer: layer for layer in decision.layers}
        for decision in decisions.decisions
    }
    assert by_name["tool_calling"]["agent"].allowed is False
    assert by_name["tool_calling"]["agent"].reason_code == "agent_disabled"
    assert by_name["streaming"]["agent"].allowed is True
    assert by_name["streaming"]["agent"].reason_code == "allowed"


def test_policy_provider_echoes_context_identity_with_four_complete_layers():
    provider = ports_production.PlatformDefaultPolicyProvider(
        policy_provider_id="react-policy", policy_version="v1", clock=time.time
    )
    context = policy_context(policy_provider_id="echo-policy", policy_version="v2")

    decisions = run(provider.resolve(context))

    assert decisions.policy_provider_id == context.policy_provider_id
    assert decisions.policy_version == context.policy_version
    assert decisions.policy_revision == context.policy_revision
    assert tuple(entry.layer for entry in decisions.layer_versions) == (
        "platform",
        "tenant",
        "agent",
        "execution",
    )
    assert all(isinstance(entry, PolicyLayerVersion) for entry in decisions.layer_versions)
    assert decisions.resolved_at.tzinfo is not None
    assert decisions.resolved_at.year >= 2024


def test_current_revision_is_scope_stable_monotonic_and_io_free():
    """R-44: an advancing revision makes every Phase 3 Run fail closed, silently.

    The policy key embeds the live revision, so a per-call value would turn
    every hot read into a cold miss, every declared capability into
    ``policy_unavailable``, and every Run and preview into a permanent outage.
    """
    provider = ports_production.PlatformDefaultPolicyProvider(
        policy_provider_id="react-policy", policy_version="v1", clock=time.time
    )
    scope = PolicyRevisionScope(
        tenant_id=TENANT_ID,
        business_scope=DEFAULT_BUSINESS_ID,
        workspace_id=DEFAULT_WORKSPACE_ID,
        agent_id=AGENT_ID,
        agent_published_version=3,
    )
    other = PolicyRevisionScope(
        tenant_id="tenant-b",
        business_scope=DEFAULT_BUSINESS_ID,
        workspace_id=DEFAULT_WORKSPACE_ID,
        agent_id=uuid4(),
        agent_published_version=9,
    )

    readings = [provider.current_revision(scope) for _ in range(8)]

    assert readings == sorted(readings)
    assert readings[0] == ports_production.NO_TENANT_POLICY_REVISION
    assert provider.current_revision(other) == ports_production.NO_TENANT_POLICY_REVISION
    assert provider.current_revision(PolicyRevisionScope(tenant_id=TENANT_ID)) == readings[0]


def test_policy_version_is_the_settings_value_the_descriptor_carries():
    """R-44 (C2 veto face): a self-invented provider version passes every check."""
    settings = phase3_settings(execution_capability_policy_version="v7")
    registry = build_registry(policy_version="v7")
    subsystem = runtime_composition._build_execution_capability_subsystem(settings, registry)

    assert subsystem.policy_version == settings.execution_capability_policy_version
    assert (
        subsystem.policy_provider.policy_version
        == registry.metadata(*PRODUCTION_ADAPTER_SELECTOR).policy_version
    )


# --------------------------------------------------------------------------- #
# D3: the honest always-empty workspace port (R-42)                              #
# --------------------------------------------------------------------------- #


def test_workspace_port_returns_none_and_never_fakes_availability():
    port = ports_production.NoTrustedWorkspaceGeneration()

    assert (
        port.current(
            WorkspaceScope(business_scope=DEFAULT_BUSINESS_ID, workspace_id=DEFAULT_WORKSPACE_ID)
        )
        is None
    )
    assert port.current(WorkspaceScope(business_scope="other", workspace_id="ws-2")) is None


def test_null_workspace_port_still_fails_closed_for_a_requiring_engine():
    """03 §4.1: a declared-required workspace with no trusted generation cannot run."""
    declared = REACT_DECLARED.model_copy(update={"workspace_required": True})
    resolver = _minimal_resolver(
        registry=build_registry(declared=declared),
        probe=_AllowAllProbe(),
        policy_provider=_AllowAllPolicyProvider(),
    )

    request = resolution_request(
        business_scope=DEFAULT_BUSINESS_ID, workspace_id=DEFAULT_WORKSPACE_ID
    )

    async def scenario():
        # The hot read is cold by design; the Run barrier warms once and re-reads.
        await resolver.warm(request)
        return await resolver.resolve(request)

    resolution = run(scenario())

    by_name = {item.name: item for item in resolution.effective.items}
    assert by_name["workspace_required"].effective is False
    assert by_name["workspace_required"].reason_code == "workspace_unavailable"
    assert "workspace_required" in resolution.effective.required_capabilities_missing
    assert resolution.startup_allowed is False


# --------------------------------------------------------------------------- #
# D4: the composition seam (R-44/R-46/R-49)                                      #
# --------------------------------------------------------------------------- #

_SETTINGS_VALUES = {
    "execution_phase3_enabled": True,
    "execution_capability_probe_timeout_seconds": 3.5,
    "execution_capability_policy_timeout_seconds": 4.5,
    "execution_capability_probe_max_concurrency": 7,
    "execution_capability_deployment_identity": "staging",
    "execution_capability_probe_cache_seconds": 21,
    "execution_capability_policy_cache_seconds": 22,
    "execution_capability_cache_capacity": 64,
    "execution_capability_cache_retry_seconds": 6.5,
    "execution_capability_warm_refresh_seconds": 5.5,
    "execution_capability_policy_version": "v3",
    "execution_snapshot_max_bytes": 8192,
}


def phase3_settings(**overrides) -> Settings:
    return Settings(_env_file=None, **{**_SETTINGS_VALUES, **overrides})


def test_composition_constructs_nothing_while_phase3_is_off():
    off = Settings(_env_file=None, execution_phase3_enabled=False)

    assert runtime_composition._build_execution_capability_subsystem(off, build_registry()) is None


def test_composition_maps_every_capability_setting_to_a_constructor_argument():
    settings = phase3_settings()
    subsystem = runtime_composition._build_execution_capability_subsystem(
        settings, build_registry(policy_version=settings.execution_capability_policy_version)
    )
    resolver = subsystem.resolver
    warmer = subsystem.warmer

    assert subsystem.snapshot_max_bytes == settings.execution_snapshot_max_bytes
    assert subsystem.policy_version == settings.execution_capability_policy_version
    assert resolver._deployment_identity == settings.execution_capability_deployment_identity
    assert resolver._probe_timeout == settings.execution_capability_probe_timeout_seconds
    assert resolver._policy_timeout == settings.execution_capability_policy_timeout_seconds
    assert resolver._probe_semaphore._value == settings.execution_capability_probe_max_concurrency
    for cache in (resolver._availability_cache, resolver._policy_cache):
        assert cache._capacity == settings.execution_capability_cache_capacity
        assert cache._retry_interval == settings.execution_capability_cache_retry_seconds
    assert resolver._availability_cache._ttl == settings.execution_capability_probe_cache_seconds
    assert resolver._policy_cache._ttl == settings.execution_capability_policy_cache_seconds
    assert warmer._refresh_interval == settings.execution_capability_warm_refresh_seconds
    assert warmer._retry_interval == settings.execution_capability_cache_retry_seconds


def test_composition_descriptor_and_provider_share_one_policy_version_source():
    """R-44: the R-20 loop is closed at construction, not by a lucky default."""
    settings = phase3_settings(execution_capability_policy_version="v6")
    registry = build_registry(policy_version="v6")
    subsystem = runtime_composition._build_execution_capability_subsystem(settings, registry)

    assert subsystem.policy_version == settings.execution_capability_policy_version
    assert registry.metadata(*PRODUCTION_ADAPTER_SELECTOR).policy_version == (
        settings.execution_capability_policy_version
    )
    assert subsystem.policy_provider.policy_version == (
        settings.execution_capability_policy_version
    )


def test_composition_warm_targets_are_exactly_the_enabled_registrations():
    """R-46 guard: a second enabled registration may never escape warming silently."""
    settings = phase3_settings()
    registry = build_registry(policy_version=settings.execution_capability_policy_version)
    subsystem = runtime_composition._build_execution_capability_subsystem(settings, registry)
    targets = tuple(subsystem.warm_targets)

    enabled_registrations = 1
    assert len(targets) == enabled_registrations
    for target in targets:
        descriptor = registry.metadata(target.engine_id, target.protocol_id, target.adapter_version)
        assert descriptor.enabled is True
        assert target.tenant_id == settings.tenant_id
        assert target.agent_id is None
        assert target.agent_published_version is None
        assert target.disabled_capabilities == ()
        assert target.business_scope == DEFAULT_BUSINESS_ID
        assert target.workspace_id == DEFAULT_WORKSPACE_ID
        assert target.execution_restriction_digest == NO_EXECUTION_RESTRICTIONS


def test_a_disabled_registration_descriptor_produces_no_warm_target():
    """03 §4.2: warming is only for registered *and enabled* exact triples."""
    settings = phase3_settings()
    registry = build_registry()

    assert runtime_composition.warm_targets(settings, react_descriptor(enabled=False)) == ()
    targets = runtime_composition.warm_targets(settings, react_descriptor())
    assert len(targets) == 1
    assert (
        registry.metadata(
            targets[0].engine_id, targets[0].protocol_id, targets[0].adapter_version
        ).enabled
        is True
    )


def test_composition_uses_one_posix_wall_clock_for_the_subsystem():
    """R-49: time.monotonic would make observed_at resolve near 1970."""
    settings = phase3_settings()
    subsystem = runtime_composition._build_execution_capability_subsystem(
        settings, build_registry(policy_version=settings.execution_capability_policy_version)
    )
    before = time.time()
    observation = run(subsystem.probe.probe(probe_context()))

    assert before <= observation.observed_at.timestamp() <= time.time() + 1
    assert observation.observed_at.year >= 2024
    assert subsystem.clock() > 1_000_000_000
    assert callable(subsystem.clock)
    composition_source = (
        _SRC / "applications" / "platform_runtime" / "runtime_composition.py"
    ).read_text(encoding="utf-8")
    monotonic_calls = [
        node
        for node in ast.walk(ast.parse(composition_source))
        if isinstance(node, ast.Attribute) and node.attr == "monotonic"
    ]
    assert monotonic_calls == []


def test_trusted_ports_are_injectable_by_code_and_unselectable_by_settings():
    """R-44: ports arrive only through the code seam; settings/env choose nothing."""

    class SpyProbe:
        async def probe(self, context):
            raise AssertionError("unused")

    class SpyPolicy:
        def current_revision(self, scope):
            return 0

        async def resolve(self, context):
            raise AssertionError("unused")

    class SpyWorkspace:
        def current(self, scope):
            return None

    settings = phase3_settings()
    registry = build_registry(policy_version=settings.execution_capability_policy_version)
    ports = runtime_composition.ExecutionCapabilityPorts(
        probe=SpyProbe(), policy_provider=SpyPolicy(), workspace_port=SpyWorkspace()
    )
    subsystem = runtime_composition._build_execution_capability_subsystem(
        settings, registry, ports=ports
    )

    assert subsystem.probe is ports.probe
    assert subsystem.policy_provider is ports.policy_provider
    assert subsystem.workspace_port is ports.workspace_port
    selectable = {
        name
        for name in Settings.model_fields
        if "probe" in name
        and "probe_" not in name
        or name in {"execution_capability_probe_port", "execution_policy_provider"}
    }
    assert selectable == set()
    composition_source = (
        _SRC / "applications" / "platform_runtime" / "runtime_composition.py"
    ).read_text(encoding="utf-8")
    assert "os.environ" not in composition_source


class SpyPolicy:
    def current_revision(self, scope):
        return 0

    async def resolve(self, context):
        raise AssertionError("unused")


class SpyWorkspace:
    def current(self, scope):
        return None


# --------------------------------------------------------------------------- #
# R-48: the runtime fingerprint exclude set (defect repair)                     #
# --------------------------------------------------------------------------- #

_TUNING_FIELDS = (
    "execution_phase3_enabled",
    "execution_capability_policy_version",
    "execution_capability_probe_timeout_seconds",
    "execution_capability_policy_timeout_seconds",
    "execution_capability_probe_cache_seconds",
    "execution_capability_policy_cache_seconds",
    "execution_capability_probe_max_concurrency",
    "execution_capability_cache_capacity",
    "execution_capability_cache_retry_seconds",
    "execution_capability_warm_refresh_seconds",
    "execution_capability_deployment_identity",
    "execution_snapshot_max_bytes",
)


def _distinct(field: str, value):
    """One valid-but-different value per settings field.

    Every knob has a grammar, so a generic mutation would be rejected by
    ``Settings`` itself rather than reaching the fingerprint: the policy version
    must stay ``v[1-9][0-9]*``, and the deployment identity stays a Slug.
    """
    if isinstance(value, bool):
        return not value
    if field == "execution_capability_policy_version":
        return "v2"
    if field == "execution_capability_deployment_identity":
        return "other-deployment"
    if field == "model_backend":
        # A Literal only accepts its own vocabulary, so the alternation has to
        # come from the field rather than from a generic mutation.
        return "demo" if value != "demo" else "openai"
    if field == "model_name":
        return "another-model-name"
    if field == "model_timeout_seconds":
        return 41.5
    if isinstance(value, str):
        return f"{value}-tuned"
    return value + 1


def test_flipping_the_phase3_flag_leaves_the_fingerprint_unchanged():
    """RED-turned-GREEN: this is the 03 §4.3 defect R-48 repairs.

    A queued Run carries the composition fingerprint it was admitted with; if
    flipping ``execution_phase3_enabled`` hashed into that fingerprint, every
    already-queued Run would report ``configuration_changed`` after the operator
    flipped the switch.
    """
    base = Settings(_env_file=None)

    assert runtime_composition._runtime_fingerprint(
        base, []
    ) == runtime_composition._runtime_fingerprint(
        Settings(_env_file=None, execution_phase3_enabled=not base.execution_phase3_enabled), []
    )


def test_runtime_fingerprint_excludes_the_phase3_tuning_family_field_by_field():
    base = Settings(_env_file=None)

    for field in _TUNING_FIELDS:
        tuned = Settings(_env_file=None, **{field: _distinct(field, getattr(base, field))})
        assert runtime_composition._runtime_fingerprint(base, []) == (
            runtime_composition._runtime_fingerprint(tuned, [])
        ), field
    everything = Settings(
        _env_file=None,
        **{field: _distinct(field, getattr(base, field)) for field in _TUNING_FIELDS},
        execution_orchestrator_enabled=not base.execution_orchestrator_enabled,
    )
    assert runtime_composition._runtime_fingerprint(base, []) == (
        runtime_composition._runtime_fingerprint(everything, [])
    )


def test_runtime_fingerprint_still_hashes_the_runtime_assembly_inputs():
    base = Settings(_env_file=None)

    # The assembly inputs the Runtime is really built from: the model identity,
    # the retained window and the round budget. A Phase 3 knob is not one of them,
    # which is why excluding it is safe while excluding these would be a hole.
    for field in ("model_name", "history_turns", "max_model_rounds", "model_timeout_seconds"):
        changed = Settings(_env_file=None, **{field: _distinct(field, getattr(base, field))})
        assert runtime_composition._runtime_fingerprint(base, []) != (
            runtime_composition._runtime_fingerprint(changed, [])
        ), field


# --------------------------------------------------------------------------- #
# R-50/R-48/D4(d): the Worker rollout gate and the read-once path                    #
# --------------------------------------------------------------------------- #


def published_row(*, engine: dict | None = None, **updates) -> dict:
    """One claimed row whose published snapshot names a configurable Engine triple.

    ``engine`` replaces the published triple inside the Agent snapshot; the
    publish path refuses an unknown triple, so reaching a Run with one takes a
    test that writes ``agent_versions`` directly (04 P3-IT-13, 08 R-50).
    """
    row = {
        "id": RUN_ID,
        "tenant_id": TENANT_ID,
        "business_id": DEFAULT_BUSINESS_ID,
        "workspace_id": DEFAULT_WORKSPACE_ID,
        "conversation_id": uuid4(),
        "input": "question",
        "history": [],
        "summary": None,
        "config": {
            "fingerprint": "wiring-fingerprint",
            "agent": {
                "id": str(AGENT_ID),
                "version": 3,
                "config": {
                    "engine": {
                        "engine_id": "react",
                        "protocol_id": "native",
                        "adapter_version": "v1",
                    }
                },
            },
        },
    }
    if engine is not None:
        row["config"]["agent"]["config"]["engine"] = engine
    row.update(updates)
    return row


def _fault(code: str) -> RuntimeFault:
    return RuntimeFault(code)


def test_rollout_gate_refuses_a_non_react_triple_in_every_off_state():
    with pytest.raises(RuntimeFault) as off_off:
        enforce_execution_rollout(
            published_row(
                engine={"engine_id": "codex", "protocol_id": "native", "adapter_version": "v1"}
            ),
            phase3_enabled=False,
            orchestrator_enabled=False,
            selector=PRODUCTION_ADAPTER_SELECTOR,
            fault=_fault,
        )
    assert off_off.value.code == "execution_phase3_disabled"
    with pytest.raises(RuntimeFault) as off_on:
        enforce_execution_rollout(
            published_row(
                engine={"engine_id": "codex", "protocol_id": "native", "adapter_version": "v1"}
            ),
            phase3_enabled=False,
            orchestrator_enabled=True,
            selector=PRODUCTION_ADAPTER_SELECTOR,
            fault=_fault,
        )
    assert off_on.value.code == "execution_phase3_disabled"


def test_rollout_gate_fails_closed_on_misconfiguration_and_unavailable_engine():
    with pytest.raises(RuntimeFault) as mismatch:
        enforce_execution_rollout(
            published_row(),
            phase3_enabled=True,
            orchestrator_enabled=False,
            selector=PRODUCTION_ADAPTER_SELECTOR,
            fault=_fault,
        )
    assert mismatch.value.code == "execution_configuration_invalid"
    with pytest.raises(RuntimeFault) as unavailable:
        enforce_execution_rollout(
            published_row(
                engine={"engine_id": "codex", "protocol_id": "native", "adapter_version": "v1"}
            ),
            phase3_enabled=True,
            orchestrator_enabled=True,
            selector=PRODUCTION_ADAPTER_SELECTOR,
            fault=_fault,
        )
    assert unavailable.value.code == "execution_engine_unavailable"


def test_rollout_gate_lets_the_two_running_states_pass():
    enforce_execution_rollout(
        published_row(),
        phase3_enabled=False,
        orchestrator_enabled=True,
        selector=PRODUCTION_ADAPTER_SELECTOR,
        fault=_fault,
    )
    enforce_execution_rollout(
        published_row(),
        phase3_enabled=True,
        orchestrator_enabled=True,
        selector=PRODUCTION_ADAPTER_SELECTOR,
        fault=_fault,
    )


def test_a_row_without_a_published_snapshot_keeps_the_legacy_triple():
    """03 §6: a legacy base_runtime row is not an engine mismatch (R-50).

    Both halves of this judgement matter. The gate must not refuse the row that
    has no published Agent snapshot - the RuntimeFactory no-snapshot path is the
    Phase 2 shape AC-1/US-1 depends on, and its fixed React triple *is* the
    production selector - while the Phase 3 barrier still has to refuse it,
    because with no published configuration there is no canonical ExecutionConfig
    to pin into the startup snapshot, and defaulting one into evidence is the
    "默认补齐污染证据" defect R-52 names (04 P3-IT-13 half, 05 A10).
    """
    from agent_platform.core_platform.agent_execution.contracts import ConfigurationError
    from agent_platform.extension_contracts import BusinessScope

    row = published_row()
    del row["config"]["agent"]

    assert execution_rollout_fault(row, phase3_enabled=False, orchestrator_enabled=False) is None
    assert execution_rollout_fault(row, phase3_enabled=True, orchestrator_enabled=True) is None

    context = build_execution_context(
        row,
        history=[],
        owner=OWNER,
        scope=BusinessScope(
            tenant_id=row["tenant_id"],
            business_id=row["business_id"],
            workspace_id=row["workspace_id"],
        ),
        execution_phase3_enabled=True,
    )

    with pytest.raises(ConfigurationError):
        execution_config_from_context(context)


def test_worker_reads_each_rollout_flag_once_and_fixes_the_path():
    """R-48: the six former ``self.settings`` re-reads become local variables."""
    execute = _function(
        (_SRC / "core_platform" / "agent_runtime" / "worker.py").read_text(encoding="utf-8"),
        "_execute",
    )
    reads = [
        (node.value.attr, node.attr)
        for node in ast.walk(execute)
        if isinstance(node, ast.Attribute)
        and node.attr in {"execution_orchestrator_enabled", "execution_phase3_enabled"}
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "settings"
    ]
    # Exactly the two per-claim initializations remain; every later decision
    # point reads the locals, so a settings object flipped mid-Run cannot
    # re-decide a claimed row (03 §4.3, R-11/R-48).
    assert sorted(reads) == [
        ("settings", "execution_orchestrator_enabled"),
        ("settings", "execution_phase3_enabled"),
    ]
    locals_ = [
        node
        for node in ast.walk(execute)
        if isinstance(node, ast.Name) and node.id in {"orchestrator_enabled", "phase3_enabled"}
    ]
    assert len([node for node in locals_ if node.id == "orchestrator_enabled"]) >= 6
    gate = [
        node
        for node in ast.walk(execute)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "enforce_execution_rollout"
    ]
    assert len(gate) == 1
    local_reads = [
        node
        for node in ast.walk(execute)
        if isinstance(node, ast.Name) and node.id == "orchestrator_enabled"
    ]
    assert len(local_reads) >= 6


# --------------------------------------------------------------------------- #
# R-52: the six-key ExecutionConfig projection                                  #
# --------------------------------------------------------------------------- #


def test_projected_execution_config_equals_the_agent_config_normalizer():
    from agent_platform.business_capabilities.agent_config.service import AgentConfig

    legacy = {
        "model_profile_id": str(uuid4()),
        "model_profile_version": 2,
        "max_model_rounds": 9,
        "disabled_capabilities": ["tool_calling"],
        "system_prompt": "stays out of the projection",
        "reply_language": "en",
    }
    react = {
        "engine": {"engine_id": "react", "protocol_id": "native", "adapter_version": "v1"},
        "react": {"model_profile_id": str(uuid4()), "model_profile_version": 1},
        "disabled_capabilities": ["terminal_execution", "terminal_execution"],
        "summary_enabled": False,
        "system_prompt": "required by the Agent contract",
    }

    for mapping in (legacy, react):
        assert execution_config_from_agent_config(mapping) == (
            AgentConfig.model_validate(mapping).execution_config()
        )


def test_projected_execution_config_defaults_the_triple_and_rejects_unknown_keys():
    assert execution_config_from_agent_config({}) == ExecutionConfig(
        engine=EngineIdentity(engine_id="react", protocol_id="native", adapter_version="v1"),
        react=ReactConfig(),
    )
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        execution_config_from_agent_config({"engine": {"engine_id": "react", "bogus": 1}})


# --------------------------------------------------------------------------- #
# T4 carry-over: constructor bounds, one observation per round                  #
# --------------------------------------------------------------------------- #


def test_cache_warmer_and_resolver_reject_out_of_range_bounds():
    from agent_platform.core_platform.agent_execution.capability.cache import CapabilityCache
    from agent_platform.core_platform.agent_execution.capability.warmer import CapabilityWarmer

    for ttl in (0, -1):
        with pytest.raises(ValueError):
            CapabilityCache(ttl_seconds=ttl, capacity=16, clock=time.time, retry_interval_seconds=1)
    with pytest.raises(ValueError):
        CapabilityCache(ttl_seconds=1, capacity=0, clock=time.time, retry_interval_seconds=1)
    for interval in (0, -1):
        with pytest.raises(ValueError):
            CapabilityWarmer(
                resolver=_minimal_resolver(),
                targets=(),
                refresh_interval_seconds=interval,
                retry_interval_seconds=1,
            )
        with pytest.raises(ValueError):
            CapabilityWarmer(
                resolver=_minimal_resolver(),
                targets=(),
                refresh_interval_seconds=1,
                retry_interval_seconds=interval,
            )
    for bad in (0, -0.5):
        with pytest.raises(ValueError):
            _minimal_resolver(probe_timeout_seconds=bad)


def test_resolver_observations_the_workspace_generation_once_per_round():
    """T4 carry-over: the key and the loader must share one observation."""
    calls: list[object] = []

    class CountingWorkspacePort:
        def current(self, scope):
            calls.append(scope)

    resolver = _minimal_resolver(workspace_port=CountingWorkspacePort())

    async def scenario():
        await resolver.resolve(resolution_request())
        before = len(calls)
        await resolver.warm(resolution_request())
        return len(calls) - before

    assert run(scenario()) == 1


# --------------------------------------------------------------------------- #
# shared helpers                                                                #
# --------------------------------------------------------------------------- #


def _cache(ttl: float):
    from agent_platform.core_platform.agent_execution.capability.cache import CapabilityCache

    return CapabilityCache(ttl_seconds=ttl, capacity=16, clock=time.time, retry_interval_seconds=1)


def _minimal_resolver(**overrides):
    values = {
        "registry": build_registry(),
        "probe": _UnusedProbe(),
        "policy_provider": _UnusedPolicyProvider(),
        "workspace_port": _NoWorkspacePort(),
        "availability_cache": _cache(30),
        "policy_cache": _cache(30),
        "deployment_identity": "default",
        "probe_timeout_seconds": 1,
        "policy_timeout_seconds": 1,
        "probe_max_concurrency": 1,
        "clock": time.time,
    }
    values.update(overrides)
    return CapabilityResolver(**values)


class _AllowAllProbe:
    async def probe(self, context):
        return _probe_result(context, available=True)


class _NoWorkspacePort:
    def current(self, scope):
        return None


class _AllowAllPolicyProvider:
    def current_revision(self, scope):
        return 0

    async def resolve(self, context):
        return PolicyDecisionSet(
            policy_provider_id=context.policy_provider_id,
            policy_version=context.policy_version,
            policy_revision=context.policy_revision,
            resolved_at=datetime.now(UTC),
            layer_versions=tuple(
                PolicyLayerVersion(layer=layer, version="v1", revision=0)
                for layer in ("platform", "tenant", "agent", "execution")
            ),
            decisions=tuple(
                CapabilityPolicy(
                    name=name,
                    layers=tuple(
                        PolicyLayerDecision(
                            layer=layer,
                            allowed=True,
                            source="probe-all",
                            reason_code="allowed",
                        )
                        for layer in ("platform", "tenant", "agent", "execution")
                    ),
                )
                for name in CAPABILITY_ORDER
            ),
        )


class _UnusedProbe:
    async def probe(self, context):
        raise AssertionError("unused")


class _UnusedPolicyProvider:
    def current_revision(self, scope):
        return 0

    async def resolve(self, context):
        raise AssertionError("unused")


def _probe_result(context, *, available: bool):
    return _ProbeResult(
        engine_id=context.engine_id,
        protocol_id=context.protocol_id,
        adapter_version=context.adapter_version,
        probe_id=context.probe_id,
        probe_version=context.probe_version,
        observed_at=datetime.now(UTC),
        deployment_digest=UNOBSERVED_DIGEST,
        items=tuple(
            CapabilityDecision(
                name=name,
                available=available,
                reason_code="allowed" if available else "probe_unavailable",
            )
            for name in CAPABILITY_ORDER
        ),
    )


def _ProbeResult(**values):
    from agent_platform.core_platform.agent_execution.capability.ports import ProbeResult

    return ProbeResult(**values)


def _function(source_text: str, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    tree = ast.parse(source_text)
    return next(
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    )


# --------------------------------------------------------------------------- #
# R-51/D6: the snapshot data flow and the write-once barrier                    #
# --------------------------------------------------------------------------- #


class RecordingBarrier:
    """Records every barrier call and replays one controlled outcome."""

    def __init__(self, outcome: str = "written") -> None:
        self.outcome = outcome
        self.calls: list[dict] = []

    async def write(
        self,
        *,
        run_id: UUID,
        owner: UUID | None,
        execution_id: UUID,
        payloads: Mapping,
    ) -> str:
        self.calls.append(
            {
                "run_id": run_id,
                "owner": owner,
                "execution_id": execution_id,
                "payloads": dict(payloads),
            }
        )
        return self.outcome


class StubPreparer:
    """Counts preparation calls and hands back one provider payload."""

    def __init__(self, prepared: PreparedInstructions | None = None) -> None:
        self.calls: list[dict] = []
        self.prepared = prepared or PreparedInstructions(
            provider_id=REACT_INSTRUCTION_PROVIDER_ID,
            provider_version=REACT_INSTRUCTION_PROVIDER_VERSION,
            payload=[{"role": "user", "content": "question"}],
        )

    def prepare_instructions(
        self,
        row: Mapping,
        *,
        history: object = (),
        summary_message: str | None = None,
        customer_memory: str | None = None,
        engine_context: Mapping | None = None,
    ) -> InstructionInput:
        self.calls.append(
            {
                "row": row,
                "history": history,
                "summary_message": summary_message,
                "customer_memory": customer_memory,
            }
        )
        return InstructionInput(
            engine=EngineIdentity(engine_id="react", protocol_id="native", adapter_version="v1"),
            agent_id=AGENT_ID,
            agent_version=3,
            system_prompt="computed once",
            history=tuple(dict(item) for item in history or ()),
            current_user_input=row["input"],
            summary_message=summary_message,
            customer_memory=customer_memory,
        )


async def build_resolution(*, fresh: bool = True, policy_missing: bool = False):
    """A resolution whose layers are fresh or cold, with stable reason codes.

    ``policy_missing`` keeps the cold shape but attributes the gap to the policy
    layer, which is how a warm that stayed cold is classified: policy, never
    engine (R-50/D5).
    """
    reason = "allowed" if fresh else ("policy_unavailable" if policy_missing else "probe_stale")
    digest = canonical_digest(REACT_DECLARED)
    declared = DeclaredCapabilities(
        engine_id="react",
        protocol_id="native",
        adapter_version="v1",
        declaration_schema_version="v1",
        declaration_digest=digest,
        capabilities=REACT_DECLARED,
    )
    available = AvailableCapabilities(
        engine_id="react",
        protocol_id="native",
        adapter_version="v1",
        probe_id="react-probe",
        probe_version="v1",
        observed_at=datetime.now(UTC),
        declaration_digest=digest,
        deployment_digest=digest,
        items=tuple(
            CapabilityDecision(name=name, available=fresh, reason_code=reason)
            for name in CAPABILITY_ORDER
        ),
    )
    provider = ports_production.PlatformDefaultPolicyProvider(
        policy_provider_id="react-policy", policy_version="v1", clock=time.time
    )
    policy = await provider.resolve(policy_context()) if fresh else None
    effective = EffectiveCapabilities(
        engine_id="react",
        protocol_id="native",
        adapter_version="v1",
        tenant_id=TENANT_ID,
        declaration_digest=digest,
        probe_id="react-probe",
        probe_version="v1",
        policy_provider_id="react-policy",
        policy_version="v1",
        policy_revision=0,
        items=tuple(
            EffectiveCapabilityDecision(name=name, effective=fresh, reason_code=reason)
            for name in CAPABILITY_ORDER
        ),
        required_capabilities_missing=() if fresh else CAPABILITY_ORDER,
    )
    return CapabilityResolution(
        declared=declared,
        available=available,
        policy=policy,
        effective=effective,
        availability_status="fresh" if fresh else "cold",
        policy_status="fresh" if fresh else "cold",
    )


class ColdResolver:
    """One bounded awaited warm turns the cold entry fresh (R-47)."""

    def __init__(self, *, warm_works: bool = True) -> None:
        self.resolve_calls = 0
        self.warm_calls = 0
        self._warm_works = warm_works

    async def resolve(self, request):
        self.resolve_calls += 1
        fresh = self.warm_calls > 0 and self._warm_works
        # A warm that stayed cold leaves the policy layer missing, which is the
        # only reason a Run may report ``execution_policy_unavailable``.
        return await build_resolution(fresh=fresh, policy_missing=not self._warm_works)

    async def warm(self, request) -> bool:
        self.warm_calls += 1
        return self._warm_works


def seams(barrier=None, preparer=None, resolver=None, max_bytes=None) -> dict:
    return {
        "capabilities": resolver if resolver is not None else ColdResolver(),
        "snapshot_barrier": barrier if barrier is not None else RecordingBarrier(),
        "snapshot_max_bytes": max_bytes if max_bytes is not None else 65536,
        "instruction_preparer": preparer if preparer is not None else StubPreparer(),
    }


def phase3_context(**updates) -> ExecutionContext:
    values = {
        "row": published_row(),
        "execution_id": RUN_ID,
        "history": [],
        "summary_message": "rendered summary",
        "customer_memory": "rendered memory",
        "owner": OWNER,
        "scope": BusinessScope(
            tenant_id=TENANT_ID,
            business_id=DEFAULT_BUSINESS_ID,
            workspace_id=DEFAULT_WORKSPACE_ID,
        ),
        "execution_phase3_enabled": True,
    }
    values.update(updates)
    return ExecutionContext(**values)


async def _discard_emit(kind, payload):
    return None


class RecordingAdapter:
    """A React-identity Adapter that records the requests it was started with.

    The identity triple must match the registration or the Registry refuses the
    instance before the Run ever reaches ``start``, and the declaration the
    divergence gate compares has to be the registered one, so an answer that
    differs from ``REACT_DECLARED`` is how a mismatch is injected elsewhere.
    """

    def __init__(self, started: list) -> None:
        self.started = started
        self.engine_id = "react"
        self.protocol_id = "native"
        self.adapter_version = "v1"

    async def get_capabilities(self) -> EngineCapabilities:
        return REACT_DECLARED

    async def start(self, request: ExecutionRequest) -> ExecutionHandle:
        self.started.append(request)
        return ExecutionHandle(
            execution_id=request.execution_id,
            engine_id=self.engine_id,
            protocol_id=self.protocol_id,
            adapter_version=self.adapter_version,
        )

    def stream_events(self, handle: ExecutionHandle):
        return _no_events()

    async def cancel(self, handle: ExecutionHandle) -> None:
        return None

    async def collect_result(self, handle: ExecutionHandle) -> ExecutionResult:
        return ExecutionResult(
            execution_id=handle.execution_id,
            engine_id=self.engine_id,
            protocol_id=self.protocol_id,
            adapter_version=self.adapter_version,
            status="completed",
            output="answered",
        )


def wired_orchestrator(adapter_factory=None, **overrides) -> ExecutionOrchestrator:
    """One Phase-3-wired orchestrator over a production React registry.

    The Adapter factory defaults to a scriptable React adapter that starts and
    completes, because the divergence gate has to resolve a real instance; the
    ``build_registry`` default factory raises by design for the trusted-port tests.
    """
    rename = {
        "barrier": "snapshot_barrier",
        "preparer": "instruction_preparer",
        "resolver": "capabilities",
        "max_bytes": "snapshot_max_bytes",
    }
    wired = seams()
    wired.update({rename.get(key, key): value for key, value in overrides.items()})
    return ExecutionOrchestrator(
        build_registry(factory=adapter_factory or (lambda: RecordingAdapter([]))),
        selector=PRODUCTION_ADAPTER_SELECTOR,
        **wired,
    )


def test_barrier_writes_the_five_payloads_once_before_prepare_and_start():
    """D6 order: resolve → gate → five DTOs → serialize → write → prepare → start."""
    barrier = RecordingBarrier()
    preparer = StubPreparer()
    started: list[ExecutionRequest] = []

    def adapter_factory():
        return RecordingAdapter(started)

    orchestrator = wired_orchestrator(
        barrier=barrier, preparer=preparer, adapter_factory=adapter_factory
    )

    outcome = run(orchestrator.execute(phase3_context(), _discard_emit))

    assert outcome.status == "completed"
    # One resolve for the declaration-divergence comparison and one for the
    # prepared context: the Adapter the Run starts has to carry the provider
    # output, so the second resolve is required and neither may start early.
    assert len(started) == 1
    assert len(barrier.calls) == 1
    call = barrier.calls[0]
    assert call["run_id"] == RUN_ID
    assert call["owner"] == OWNER
    assert call["execution_id"] == RUN_ID
    assert set(call["payloads"]) == set(SNAPSHOT_COLUMNS)
    # R-9: the startup identity lives inside every payload body, not only in the
    # guard parameter, so a foreign identity can never be parked in this row.
    for payload in call["payloads"].values():
        assert json.loads(payload)["execution_id"] == str(RUN_ID)
    assert len(preparer.calls) == 1
    # The prepared context is the one the Adapter was resolved with, so the Engine
    # really consumed the provider output rather than re-rendering (R-41).
    assert started[0].execution_id == RUN_ID


class RecordingAdapterFactory:
    """The real React Adapter, with the start calls it was asked to make.

    A scripted double would hide the Phase 2 call shape, and the off/on state has
    to prove the *same* adapter path stays byte-identical while the on/on state
    proves ``for_run`` is never reached; only the production Adapter can show both.

    The context is captured from the execution scope exactly like the production
    ``ReactAdapterFactory``: the Worker builds its own context per claim, and an
    Adapter assembled from a second hand-made one would fail the identity check
    for reasons no deployment can produce. Capturing is also what makes the on/on
    judgement real - the prepared instructions the barrier put into the context are
    the ones the Adapter then consumes.
    """

    def __init__(self, started: list, calls: list) -> None:
        self.started = started
        self.calls = calls

    def __call__(self) -> object:
        from agent_platform.core_platform.agent_execution.adapters.react.adapter import (
            ReactAdapter,
        )

        adapter = ReactAdapter(
            execution_context.capture_execution_context(), _MatrixAdapterBridge(self.calls)
        )
        original = adapter.start

        async def start(request):
            self.started.append(request)
            return await original(request)

        adapter.start = start
        return adapter


class _MatrixAdapterBridge:
    """A RuntimeFactory double that records the exact ``run`` arguments."""

    def __init__(self, calls: list) -> None:
        self.calls = calls

    async def for_run(self, row, emit):
        return _MatrixRuntime(self.calls)


class _MatrixRuntime:
    """Passes the run arguments through so the call shape is observable."""

    def __init__(self, calls: list) -> None:
        self.calls = calls

    async def run(
        self,
        message,
        history,
        emit,
        summary_message=None,
        customer_memory=None,
        prepared_instructions=None,
    ):
        self.calls.append(
            {
                "message": message,
                "history": list(history),
                "summary_message": summary_message,
                "customer_memory": customer_memory,
                "prepared_instructions": prepared_instructions,
            }
        )
        return "answered", [{"role": "user", "content": message}], []


def test_cold_policy_warms_once_and_stays_fail_closed_when_the_warm_fails():
    """R-47: the Run barrier awaits exactly one bounded refresh."""
    resolver = ColdResolver()
    orchestrator = wired_orchestrator(resolver=resolver)

    outcome = run(orchestrator.execute(phase3_context(), _discard_emit))

    assert outcome.status == "completed"
    assert resolver.warm_calls == 1
    assert resolver.resolve_calls == 2

    failing = ColdResolver(warm_works=False)
    blocked = wired_orchestrator(resolver=failing)

    refusal = run(blocked.execute(phase3_context(), _discard_emit))

    assert refusal.status == "failed"
    assert refusal.legacy_error_code == "execution_policy_unavailable"
    assert failing.warm_calls == 1


def test_write_outcomes_map_onto_the_existing_run_vocabulary():
    """R-50/D5: written/reused continue; audit_conflict refuses; lease stays lease."""
    for outcome, expected in (
        ("written", "completed"),
        ("reused", "completed"),
        ("audit_conflict", "execution_configuration_invalid"),
        ("not_claimed", "worker_lost"),
        ("lease_lost", "worker_lost"),
    ):
        barrier = RecordingBarrier(outcome)
        orchestrator = wired_orchestrator(barrier=barrier)

        result = run(orchestrator.execute(phase3_context(), _discard_emit))

        if expected == "completed":
            assert result.status == "completed", outcome
        else:
            assert result.status == "failed"
            assert result.legacy_error_code == expected, outcome


async def _no_events():
    """An empty public event stream: the terminal frame is the adapter's result."""
    return
    yield


# --------------------------------------------------------------------------- #
# R-50/D5: the four-state matrix through the real Worker                        #
# --------------------------------------------------------------------------- #


class CountingRuntimeFactory:
    """Counts ``for_run`` so a silent legacy fallback becomes observable."""

    def __init__(self) -> None:
        self.calls = 0
        self.runtimes: list[Phase2Runtime] = []

    async def for_run(self, row, emit):
        self.calls += 1
        runtime = Phase2Runtime()
        self.runtimes.append(runtime)
        return runtime


class Phase2Runtime:
    """The Phase 2 five-argument call shape, kept byte-compatible."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def run(self, message, history, emit, summary_message=None, customer_memory=None):
        self.calls.append(
            {
                "message": message,
                "history": list(history),
                "summary_message": summary_message,
                "customer_memory": customer_memory,
            }
        )
        return "answered", [{"role": "user", "content": message}], []


class MatrixRepository:
    """The durable Run log one Worker writes, plus the five snapshot columns."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []
        self.finishes: list[dict] = []
        self.row = {
            "id": RUN_ID,
            "tenant_id": TENANT_ID,
            "business_id": DEFAULT_BUSINESS_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "conversation_id": uuid4(),
            "input": "question",
            "history": [],
            "summary": None,
            "config": {
                "fingerprint": "matrix-fingerprint",
                "agent": {
                    "id": str(AGENT_ID),
                    "version": 3,
                    "config": {
                        "engine": {
                            "engine_id": "react",
                            "protocol_id": "native",
                            "adapter_version": "v1",
                        }
                    },
                },
            },
        }

    async def claim(self, owner, lease, tenant):
        return dict(self.row)

    async def append(self, run_id, owner, kind, data):
        self.events.append((kind, data))

    async def finish(self, run_id, owner, status, **details):
        self.finishes.append({"status": status, **details})
        self.events.append(
            (
                f"run.{status}",
                {"output": details.get("output"), "error_code": details.get("error")},
            )
        )

    async def heartbeat(self, run_id, owner, lease_seconds):
        return "ok"


class MatrixMemory:
    """Renders the two business values the Phase 2 call shape still carries.

    Without a memory port the Worker hands ``None`` for both, and the off/on
    judgement "the Phase 2 call shape is unchanged" would have nothing to
    compare: the point is that both rendered values still arrive on the off path
    and that no prepared input arrives with them (R-41).
    """

    def render_summary(self, summary):
        return "rendered summary"

    async def customer_memory(self, row, settings):
        return "rendered memory"

    def memory_context(self, row, dropped, settings):
        return {"dropped": list(dropped)}


def matrix_state(*, phase3: bool, orchestrator: bool) -> dict:
    """Run one real Worker claim through one exact rollout state.

    Everything the matrix judges is counted here rather than asserted from a
    comment: the production Adapter factory, the production Registry, the real
    ``ExecutionOrchestrator`` and the real ``RuntimeWorker``. The snapshot seam is
    a recorder because the five columns themselves are the PG suite's face.

    Two factories count separately on purpose: the Worker's own ``for_run`` is the
    legacy path the on+orchestrator-off state must never reach (C9), while the
    Adapter's internal runtime factory is where the orchestrator path lands.
    """
    started: list[ExecutionRequest] = []
    calls: list[dict] = []
    factory = CountingRuntimeFactory()
    barrier = RecordingBarrier()
    preparer = StubPreparer()
    resolver = ColdResolver()
    registry = build_registry(factory=RecordingAdapterFactory(started, calls))
    if phase3:
        orchestrator_instance = ExecutionOrchestrator(
            registry,
            selector=PRODUCTION_ADAPTER_SELECTOR,
            **seams(barrier=barrier, preparer=preparer, resolver=resolver),
        )
    else:
        orchestrator_instance = ExecutionOrchestrator(
            registry, selector=PRODUCTION_ADAPTER_SELECTOR
        )
    repository = MatrixRepository()
    worker = RuntimeWorker(
        repository,
        factory,
        Settings(_env_file=None),
        "matrix-fingerprint",
        memory=MatrixMemory(),
        orchestrator=orchestrator_instance if orchestrator else None,
    )
    worker.settings.execution_phase3_enabled = phase3
    worker.settings.execution_orchestrator_enabled = orchestrator
    run(worker._execute(repository.row))
    return {
        "events": list(repository.events),
        "finishes": list(repository.finishes),
        "calls": calls,
        "starts": len(started),
        "requests": list(started),
        "for_run": factory.calls,
        "barrier": barrier.calls,
        "orchestrator": orchestrator_instance,
    }


def test_both_off_states_construct_no_phase3_side_effects():
    """P3-IT-12/22: off/off and off/on keep the Phase 2 path exactly.

    ``ExecutionRequest.config``/``effective_capabilities`` staying empty is the
    Phase 3 behaviour test: writing either one would already be Phase 3 evidence,
    so the off path must not (04 P3-IT-22).

    The seam itself is checked too, because "probe call count always 0" is only
    provable by there being no probe to call: a Phase-3-wired orchestrator with an
    unused resolver would satisfy the event assertions while still constructing the
    subsystem.
    """
    for orchestrator in (False, True):
        state = matrix_state(phase3=False, orchestrator=orchestrator)

        assert state["barrier"] == [], f"orchestrator={orchestrator}"
        wired = state["orchestrator"]
        assert wired.phase3_enabled is False, f"orchestrator={orchestrator}"
        assert wired._capabilities is None, f"orchestrator={orchestrator}"
        assert wired._snapshot_barrier is None, f"orchestrator={orchestrator}"
        assert wired._instruction_preparer is None, f"orchestrator={orchestrator}"
        # The orchestrator path starts a fresh Adapter; the legacy path builds the
        # Runtime inside the Worker instead. Exactly one of the two is entered per
        # claim, never both (R-11 four-state matrix).
        assert state["starts"] == (1 if orchestrator else 0)
        assert state["for_run"] == (0 if orchestrator else 1)
        if orchestrator:
            request = state["requests"][0]
            assert request.config == {}
            assert request.effective_capabilities == {}
            # The Phase 2 call shape is unchanged: both rendered values still
            # arrive and no prepared input is passed at all.
            call = state["calls"][0]
            assert call["summary_message"] is not None
            assert call["customer_memory"] is not None
            assert call["prepared_instructions"] is None


def test_on_with_orchestrator_off_refuses_the_legacy_path_completely():
    """C9 veto face: ``runtime.for_run`` at zero is the only real judgement."""
    state = matrix_state(phase3=True, orchestrator=False)

    assert state["for_run"] == 0
    assert state["starts"] == 0
    assert state["barrier"] == []
    assert [finish["status"] for finish in state["finishes"]] == ["failed"]
    assert state["finishes"][0]["error"] == "execution_configuration_invalid"


def test_on_on_matches_the_off_on_public_event_sequence_exactly():
    """R-8: claim events and the terminal frame keep their Phase 2 order."""
    off_on = matrix_state(phase3=False, orchestrator=True)
    on_on = matrix_state(phase3=True, orchestrator=True)

    assert [kind for kind, _ in off_on["events"]] == [kind for kind, _ in on_on["events"]]
    assert off_on["finishes"][-1]["status"] == on_on["finishes"][-1]["status"]
    assert on_on["starts"] == 1
    assert len(on_on["barrier"]) == 1
    # R-21: the flags projection is the only legal one, so the Run request carries
    # exactly eleven keys in canonical order rather than a narrowed subset.
    request = on_on["requests"][0]
    assert set(request.effective_capabilities) == set(CAPABILITY_ORDER)
    from agent_platform.core_platform.agent_execution.contracts.snapshots import (
        EffectiveCapabilitiesSnapshot,
    )

    stored = EffectiveCapabilitiesSnapshot.model_validate_json(
        on_on["barrier"][0]["payloads"]["effective_capabilities_snapshot"]
    )
    # R-21/R-22: the request view and the stored snapshot are one projection of
    # one and the same resolution, never two derivations.
    assert request.effective_capabilities == {item.name: item.effective for item in stored.items}
    assert list(request.effective_capabilities) == list(CAPABILITY_ORDER)


# --------------------------------------------------------------------------- #
# R-52/D6: the byte ceiling travels from settings to the serializer            #
# --------------------------------------------------------------------------- #


def test_the_composition_threads_the_snapshot_ceiling_to_the_serializer():
    """P3-IT-19: no call site may fall back to the module default.

    ``serialize_execution_snapshots`` keeps a 64 KiB module constant, while
    ``execution_snapshot_max_bytes`` allows 4096..262144: a deployment that lowers
    the bound and silently stores a 60 KiB payload produces no error at all, so the
    only usable evidence is that one settings value reaches the serializer call.
    """
    settings = phase3_settings(execution_snapshot_max_bytes=4096)
    orchestrator = runtime_composition._build_execution_orchestrator(
        None,
        runtime_composition._execution_adapter_registry(),
        settings=settings,
        barrier=RecordingBarrier(),
    )

    assert settings.execution_snapshot_max_bytes == 4096
    assert orchestrator._snapshot_max_bytes == settings.execution_snapshot_max_bytes


def test_a_ceiling_below_the_payload_refuses_before_the_adapter_starts():
    """The negative control that proves the ceiling above is load-bearing."""
    barrier = RecordingBarrier()
    started: list[ExecutionRequest] = []

    orchestrator = wired_orchestrator(
        barrier=barrier, max_bytes=1, adapter_factory=lambda: RecordingAdapter(started)
    )

    outcome = run(orchestrator.execute(phase3_context(), _discard_emit))

    assert outcome.status == "failed"
    assert outcome.legacy_error_code == "execution_configuration_invalid"
    assert barrier.calls == []
    assert started == []


# --------------------------------------------------------------------------- #
# R-50/D5: the barrier classifies inside itself, the wide except never decides  #
# --------------------------------------------------------------------------- #


class _ProbeMissingResolver:
    """A warm that stayed cold on the *deployment* layer, not the policy layer."""

    def __init__(self) -> None:
        self.warm_calls = 0

    async def resolve(self, request):
        return await build_resolution(fresh=False, policy_missing=False)

    async def warm(self, request) -> bool:
        self.warm_calls += 1
        return False


def test_every_barrier_refusal_keeps_its_own_run_code():
    """No classified barrier failure may degrade to ``execution_error``.

    ``ExecutionOrchestrator.execute`` keeps two wide ``except Exception`` boundaries
    (assembly and start). They are correct for everything they were written for, but
    a Phase 3 barrier code that passed through them would come out as
    ``execution_error`` and P3-IT-22/A6 would be unprovable - so this table is the
    guard, and each row names the condition that produced it.
    """
    cases: list[tuple[str, ExecutionOrchestrator, ExecutionContext, str]] = [
        (
            "required capability missing after a bounded warm",
            wired_orchestrator(resolver=_ProbeMissingResolver()),
            phase3_context(),
            "execution_engine_unavailable",
        ),
        (
            "policy layer still cold after a bounded warm",
            wired_orchestrator(resolver=ColdResolver(warm_works=False)),
            phase3_context(),
            "execution_policy_unavailable",
        ),
        (
            "stored audit disagrees with this startup",
            wired_orchestrator(barrier=RecordingBarrier("audit_conflict")),
            phase3_context(),
            "execution_configuration_invalid",
        ),
        (
            "the write-once claim is gone",
            wired_orchestrator(barrier=RecordingBarrier("not_claimed")),
            phase3_context(),
            "worker_lost",
        ),
        (
            "the lease was lost during the barrier",
            wired_orchestrator(barrier=RecordingBarrier("lease_lost")),
            phase3_context(),
            "worker_lost",
        ),
        (
            "a published triple this deployment never registered",
            wired_orchestrator(),
            phase3_context(
                row=published_row(
                    engine={"engine_id": "other", "protocol_id": "native", "adapter_version": "v1"}
                )
            ),
            "execution_engine_unavailable",
        ),
        (
            "a published engine block that cannot be read at all",
            wired_orchestrator(),
            phase3_context(row=published_row(engine={})),
            "execution_engine_unavailable",
        ),
        (
            "a published configuration whose canonical form does not add up",
            wired_orchestrator(),
            phase3_context(row=_conflicting_alias_row()),
            "execution_configuration_invalid",
        ),
        (
            "a payload above the deployment byte ceiling",
            wired_orchestrator(max_bytes=1),
            phase3_context(),
            "execution_configuration_invalid",
        ),
        (
            "instance declaration diverges from the registration",
            wired_orchestrator(adapter_factory=lambda: _DivergentAdapter()),
            phase3_context(),
            "execution_configuration_invalid",
        ),
    ]

    for label, orchestrator, context, expected in cases:
        outcome = run(orchestrator.execute(context, _discard_emit))

        assert outcome.status == "failed", label
        assert outcome.legacy_error_code == expected, label
        assert outcome.legacy_error_code != "execution_error", label


class _DivergentAdapter(RecordingAdapter):
    """Answers with a declaration the Registry did not register (R-43)."""

    async def get_capabilities(self) -> EngineCapabilities:
        return EngineCapabilities(streaming=True)


def test_declaration_divergence_refuses_before_any_snapshot_or_start():
    """R-43/P3-IT-03: the one production-observable deployment-divergence signal.

    Phase 3 has no external deployment, so "missing deployment / incompatible
    version / probe timeout" are reachable only through injected doubles, while this
    comparison - a fresh Adapter's own declaration against what the Registry
    registered - is a real production signal. The judgement is not just the code:
    nothing may have been written and the Run must never have been started, because
    a diverging Engine that was already started would have consumed the Run.
    """
    barrier = RecordingBarrier()
    started: list[ExecutionRequest] = []
    preparer = StubPreparer()

    orchestrator = wired_orchestrator(
        barrier=barrier,
        preparer=preparer,
        adapter_factory=lambda: _DivergentAdapter(started),
    )

    outcome = run(orchestrator.execute(phase3_context(), _discard_emit))

    assert outcome.status == "failed"
    assert outcome.legacy_error_code == "execution_configuration_invalid"
    assert barrier.calls == []
    assert started == []
    assert preparer.calls == []


def _conflicting_alias_row() -> dict:
    """A React-named published config whose canonical form does not add up.

    The engine block stays readable, so the rollout gate has nothing to refuse -
    the triple is the registered one - and it is the barrier's own
    ``ExecutionConfig`` normalization step that has to report the contradiction,
    which is the D5 row that distinguishes ``execution_configuration_invalid``
    from an availability answer (03 §5.3).
    """
    row = published_row()
    row["config"]["agent"]["config"].update(
        {"react": {"max_model_rounds": 3}, "max_model_rounds": 5}
    )
    return row


# --------------------------------------------------------------------------- #
# R-30/R-50: the adapter error map gains the two snapshot faults and nothing else #
# --------------------------------------------------------------------------- #

_RUN_SIDE_CODES = (
    "execution_phase3_disabled",
    "execution_configuration_invalid",
    "execution_engine_unavailable",
    "execution_policy_unavailable",
)


def test_snapshot_faults_map_onto_invalid_request_not_internal_error():
    """R-30: the registration is the gate, and it is proven by contrast.

    ``_ERROR_MAP.get(code, _INTERNAL_ERROR)`` is a default-deny lookup: an
    unregistered Run fault silently becomes an internal error, which is exactly how
    "this deployment has no published Agent snapshot" would stop being
    distinguishable from a crash. The same assertion for an unregistered code is the
    RED half of this judgement.
    """
    from agent_platform.core_platform.agent_execution.adapters.react.error_mapper import (
        _ERROR_MAP,
        map_execution_error,
    )

    for code in ("agent_snapshot_required", "agent_snapshot_invalid"):
        assert code in _ERROR_MAP, code
        mapping = map_execution_error(RuntimeFault(code))

        assert mapping.error.code.value == "invalid_request", code
        assert mapping.error.category.value == "configuration_error", code
        assert mapping.legacy_error_code == code

    unregistered = map_execution_error(RuntimeFault("snapshot_fault_not_registered"))

    assert unregistered.error.code.value == "internal_error"


def test_instruction_contract_error_passes_through_without_the_fault_map():
    """A ConfigurationError is already a typed adapter error: never internal_error.

    Preparation raises the instruction layer's own error both for a value the
    contract cannot carry and for a prepared payload the Engine refuses to consume.
    Those reach ``map_execution_error`` as ``AdapterExecutionError`` instances, take
    the transparent branch and keep their own public error - the fault map is not
    consulted at all, so a contract break cannot be re-labelled as an internal one.
    """
    from agent_platform.core_platform.agent_execution.adapters.react.error_mapper import (
        map_execution_error,
    )
    from agent_platform.core_platform.agent_execution.contracts.instructions import (
        instruction_contract_error,
    )

    failure = instruction_contract_error("instruction_prepare", "current_user_input")

    mapping = map_execution_error(failure)

    assert mapping.error is failure.error
    assert mapping.error.code.value == "invalid_request"
    assert mapping.error.details.operation == "instruction_prepare"
    assert mapping.error.details.field == "current_user_input"


def test_the_four_run_side_codes_stay_out_of_the_adapter_error_map():
    """R-50: they are Run terminal codes, not HTTP RuntimeFault translations.

    Registering them would push the Run vocabulary into the adapter's public error
    catalog (and imply a frontend/i18n change that has not been made); the four
    sentences already exist, so the correct move is to add none.
    """
    from agent_platform.core_platform.agent_execution.adapters.react.error_mapper import (
        _ERROR_MAP,
    )

    assert not set(_RUN_SIDE_CODES) & set(_ERROR_MAP)


# --------------------------------------------------------------------------- #
# R-32/R-41: the adapter-to-engine seam really carries the prepared input       #
# --------------------------------------------------------------------------- #


def test_the_runtime_engine_protocol_and_the_engine_implementation_agree():
    """A six-parameter Protocol with a five-parameter implementation drops evidence.

    The Protocol is structural, so nothing at runtime would notice a target that
    cannot accept ``prepared_instructions``: the call would simply fail, or worse,
    a widened Protocol would be satisfied while the Engine kept assembling its own
    messages. The parameter lists are therefore pinned against each other, and the
    five-argument shape is asserted gone.
    """
    import inspect

    from agent_platform.core_platform.agent_execution.adapters.react.adapter import (
        RuntimeEngine as RuntimeEngineProtocol,
    )
    from agent_platform.core_platform.agent_runtime.engine import (
        RuntimeEngine as RuntimeEngineImplementation,
    )

    protocol = list(inspect.signature(RuntimeEngineProtocol.run).parameters)
    implementation = list(inspect.signature(RuntimeEngineImplementation.run).parameters)

    assert protocol == implementation
    assert protocol == [
        "self",
        "message",
        "history",
        "emit",
        "summary_message",
        "customer_memory",
        "prepared_instructions",
    ]
    assert len(implementation) == 7


def test_on_on_adapter_receives_prepared_input_and_no_second_rendering():
    """R-41: the prepared path must not re-supply the two rendered values.

    The Engine fails closed on a second copy of either one, and the settings the
    retained window came from would then be two different objects: preparation
    derives it from ``RuntimeFactory.effective``, the same source the Engine slices
    its own ``kept`` window from, so the invariant is one source rather than a
    coincidence of equal numbers.
    """
    state = matrix_state(phase3=True, orchestrator=True)

    assert state["starts"] == 1
    call = state["calls"][0]
    assert call["prepared_instructions"] is not None
    assert call["summary_message"] is None
    assert call["customer_memory"] is None
    # The payload is the provider output the barrier put into the context, not a
    # second rendering produced inside the adapter: the provider's own sequence,
    # system rule first and the current input last.
    prepared = call["prepared_instructions"]
    assert prepared.provider_id == REACT_INSTRUCTION_PROVIDER_ID
    assert prepared.provider_version == REACT_INSTRUCTION_PROVIDER_VERSION
    assert prepared.payload[0] == {"role": "system", "content": "computed once"}
    assert prepared.payload[-1] == {"role": "user", "content": "question"}


class _RecordingPreparedModel:
    """The minimal chat-model seam the Engine needs; records what it was sent."""

    def __init__(self) -> None:
        self.seen: list[list[object]] = []

    async def ainvoke(self, messages):
        from langchain_core.messages import AIMessage

        self.seen.append(list(messages))
        return AIMessage(content="answered")


def test_preparation_and_engine_share_one_effective_settings_source():
    """R-41 on the production seam: one ``effective()`` call, one kept slice.

    The matrix above runs the Adapter against a runtime double, so it can only show
    that the provider output arrives. What makes the invariant real is that the
    preparation slice and the Engine slice come from the same computed settings:
    with them the Engine consumes the payload, with a second settings object whose
    window differs the same payload fails closed before the model is called.
    """
    import httpx

    from agent_platform.applications.platform_runtime.runtime_factory import RuntimeFactory
    from agent_platform.core_platform.agent_execution.instructions import (
        resolve_instruction_provider,
    )
    from agent_platform.core_platform.agent_runtime.engine import RuntimeEngine
    from agent_platform.core_platform.tool_gateway.service import ToolGateway
    from agent_platform.extension_contracts import RuntimeBindings

    class Policy:
        def check_rounds(self, rounds, settings):
            return rounds

    history = [
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "q2"},
        {"role": "assistant", "content": "a2"},
    ]
    snapshot = {
        "id": AGENT_ID,
        "version": 3,
        "config": {
            "system_prompt": "Answer briefly.",
            "reply_language": "auto",
            "max_model_rounds": 6,
            "engine": {
                "engine_id": "react",
                "protocol_id": "native",
                "adapter_version": "v1",
            },
        },
        "tools": [],
    }
    settings = Settings(_env_file=None, history_turns=3)
    factory = RuntimeFactory(None, RuntimeBindings(policy=Policy()), None, settings, 10)

    async def scenario() -> tuple:
        async with httpx.AsyncClient() as client:
            instruction = factory.prepare_instructions(
                {"input": "q3", "config": {"agent": snapshot}},
                history=history,
                summary_message=None,
                customer_memory=None,
            )
            prepared = resolve_instruction_provider(
                REACT_INSTRUCTION_PROVIDER_ID, REACT_INSTRUCTION_PROVIDER_VERSION
            ).prepare(instruction)
            shared = factory.effective(snapshot)
            model = _RecordingPreparedModel()
            output, kept, dropped = await RuntimeEngine(model, ToolGateway(client, []), shared).run(
                "q3", history, _discard_emit, prepared_instructions=prepared
            )
            narrower_model = _RecordingPreparedModel()
            narrower = shared.model_copy(update={"history_turns": 1})
            with pytest.raises(Exception) as refused:
                await RuntimeEngine(narrower_model, ToolGateway(client, []), narrower).run(
                    "q3", history, _discard_emit, prepared_instructions=prepared
                )
            return (
                output,
                kept,
                dropped,
                model.seen,
                prepared.payload,
                type(refused.value).__name__,
                narrower_model,
            )

    output, kept, dropped, seen, payload, refused_name, narrower_model = run(scenario())

    assert output == "answered"
    assert dropped == []
    assert [item["content"] for item in kept] == ["q1", "a1", "q2", "a2", "q3", "answered"]
    # The Engine assembled nothing: one provider entry became one message, in the
    # provider's order, with no second rendering of the window.
    assert [(message.type, message.content) for message in seen[0]] == [
        ({"system": "system", "user": "human", "assistant": "ai"}[item["role"]], item["content"])
        for item in payload
    ]
    assert refused_name == "ConfigurationError"
    # Fail-closed happens before the model is called: a second settings object with
    # a different window cannot quietly send a different conversation to the model.
    assert narrower_model.seen == []


# --------------------------------------------------------------------------- #
# R-50/R-46: the misconfigured state boots, and the subsystem lifecycle order   #
# --------------------------------------------------------------------------- #


def test_the_misconfigured_state_boots_and_still_refuses_runs():
    """R-50/03 §9.2: on + orchestrator-off is a Run answer, not a boot failure.

    Refusing to start the process would make the flags face and the misconfiguration
    hint unobservable in exactly the state they exist for, and readiness has no rule
    that would let it report this pairing yet (04/05 carry no such criterion). So the
    subsystem is really constructed here - it warms, it answers preview - while the
    Run path refuses, and ``/ready`` reads neither switch.
    """
    settings = phase3_settings(execution_orchestrator_enabled=False)
    registry = runtime_composition._execution_adapter_registry()

    subsystem = runtime_composition._build_execution_capability_subsystem(settings, registry)
    orchestrator = runtime_composition._build_execution_orchestrator(
        None, registry, settings=settings, barrier=RecordingBarrier()
    )

    assert subsystem is not None
    assert subsystem.warmer is not None
    # The Run side still refuses, with the misconfiguration code and no legacy path.
    state = matrix_state(phase3=True, orchestrator=False)
    assert state["finishes"][0]["error"] == "execution_configuration_invalid"
    assert state["for_run"] == 0

    routes_source = (_SRC / "applications" / "customer_service" / "runtime_routes.py").read_text(
        encoding="utf-8"
    )
    assert "execution_phase3_enabled" not in routes_source
    assert "execution_orchestrator_enabled" not in routes_source
    assert orchestrator.phase3_enabled is True


def test_composition_starts_the_warmer_after_extensions_and_closes_it_first():
    """R-46 lifecycle order, pinned on the one composition root.

    The warmer is started only once the extension lifecycles are up (the same rule
    the contribution attachments follow), and it is closed before anything it can
    touch: a warm round may still be awaiting a port that reads the database or the
    HTTP client, so releasing those first would turn shutdown into an exception
    storm. ``ready`` not waiting on a probe is the other half of the same order:
    ``start()`` only spawns the loop.
    """
    source = (_SRC / "applications" / "platform_runtime" / "runtime_composition.py").read_text(
        encoding="utf-8"
    )

    started_after_extensions = source.index("await extensions.start_all()") < source.index(
        "subsystem.warmer.start()"
    )
    closing = source[source.index("    finally:") :]
    order = [
        closing.index("await subsystem.warmer.aclose()"),
        closing.index("await subsystem.resolver.aclose()"),
        closing.index("contributions.detach_events()"),
        closing.index("await extensions.stop_all()"),
        closing.index("await engine.dispose()"),
        closing.index("await listener.close()"),
        closing.index("await notifier.close()"),
    ]

    assert started_after_extensions
    assert order == sorted(order)
