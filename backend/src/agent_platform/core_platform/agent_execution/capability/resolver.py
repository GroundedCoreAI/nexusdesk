"""Four-layer capability resolver: Declared, Available, Policy, Effective.

The resolver consumes exact Registry metadata (Declared) plus trusted port
observations (Available via probe, Policy via provider, Workspace via port) and
computes Effective capabilities. Policy revisions are observed live from the
trusted provider's synchronous ``current_revision`` every round (R-17); a
failing revision source raises :class:`PolicySourceUnavailableError` instead
of defaulting. Synchronous hot reads never call a remote port: they read the
sanitized cache and schedule a deduplicated background refresh when
cold/stale/error, returning a fail-closed view. Narrowing is monotonic and a
missing or untrusted Policy source fails closed.
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from ..contracts.base import ExecutionContractModel
from ..contracts.capabilities import (
    CAPABILITY_ORDER,
    UNOBSERVED_DIGEST,
    AvailableCapabilities,
    CapabilityDecision,
    DeclaredCapabilities,
    DigestString,
    EffectiveCapabilities,
    EffectiveCapabilityDecision,
    PolicyDecisionSet,
    canonical_digest,
    disabled_capabilities_digest,
)
from ..contracts.common import AdapterVersion, EngineId, OpaqueString, ProtocolId
from ..contracts.config import CapabilityName
from ..registry.adapter_registry import AdapterDescriptor, AdapterRegistry
from .cache import (
    AvailabilityCacheKey,
    CacheStatus,
    CapabilityCache,
    PolicyCacheKey,
)
from .ports import (
    AvailabilityGeneration,
    PolicyContext,
    PolicyRevisionScope,
    ProbeContext,
    ProbeResult,
    TrustedDeploymentProbe,
    TrustedPolicyProvider,
    WorkspaceAvailabilityPort,
    WorkspaceScope,
)

# A denial observation for a declared capability can only be produced by
# infrastructure: an unusable or failed probe, a timed-out or stale
# observation, or an unavailable required workspace. ``not_declared`` belongs
# exclusively to items the registry declares false (written by the sanitize
# clamp and the synthesized fail-closed view); policy reason codes are not
# availability observations at all. A probe echoing either for a declared
# capability is self-contradictory and degrades to ``probe_unavailable`` so
# the startup gate counts it instead of mistaking it for benign narrowing.
_AVAILABILITY_DENIAL_REASONS = frozenset(
    {
        "probe_unavailable",
        "probe_timeout",
        "probe_stale",
        "workspace_unavailable",
    }
)

# FR-3 / AC-3 "required capability missing" is strictly a deployment or trust
# gap. Platform/tenant/agent/execution denials (FR-4, AC-4) and non-declared
# names are supported monotonic narrowing and must never block startup.
_REQUIRED_MISSING_REASONS = frozenset(
    {
        "probe_unavailable",
        "probe_timeout",
        "probe_stale",
        "workspace_unavailable",
        "policy_unavailable",
    }
)


class _ProbeMismatchError(Exception):
    """Raised when a probe response does not echo its request identity."""


class _PolicyMismatchError(Exception):
    """Raised when a policy result does not match the expected trusted source."""


class _PolicyTimeoutError(Exception):
    """Raised when the policy source outlived its bounded wait."""


class PolicySourceUnavailableError(Exception):
    """The live policy-revision observation from the trusted provider failed.

    The resolver surfaces this instead of swallowing the provider error or
    substituting a default revision: a revision that cannot be observed
    cannot be pinned into a cache key, so no resolution may proceed.
    """


class CapabilityResolutionRequest(ExecutionContractModel):
    """Server-assembled trusted scope for one resolution; never client input.

    Every field is extracted from the authenticated context and the published
    agent configuration by composition. Clients cannot contribute any field,
    and the DTO rejects all unknown keys. The policy revision is not carried
    here (R-17): the resolver observes it live from the trusted provider on
    every resolution round.
    """

    contract_version: Literal["v1"] = "v1"
    engine_id: EngineId
    protocol_id: ProtocolId
    adapter_version: AdapterVersion
    tenant_id: str = Field(min_length=1, max_length=200)
    business_scope: OpaqueString | None = None
    workspace_id: OpaqueString | None = None
    agent_id: UUID | None = None
    agent_published_version: int | None = Field(default=None, ge=0)
    disabled_capabilities: tuple[CapabilityName, ...] = ()
    execution_restriction_digest: DigestString


@dataclass(frozen=True, slots=True)
class CapabilityResolution:
    """The four computed layers plus the required-capability startup gate."""

    declared: DeclaredCapabilities
    available: AvailableCapabilities
    policy: PolicyDecisionSet | None
    effective: EffectiveCapabilities
    availability_status: CacheStatus
    policy_status: CacheStatus

    @property
    def startup_allowed(self) -> bool:
        """False only when a required capability is missing, never merely denied.

        "Required capability missing" (FR-3 / AC-3) means a deployment or trust
        gap: no/failed/timed-out/stale probe, an unavailable required workspace,
        or a missing or untrusted policy source. Denials produced by the policy
        layers or by the published agent's ``disabled_capabilities`` (FR-4 /
        AC-4) are supported monotonic narrowing, so they keep startup allowed.
        Callers such as T7 admission use this gate; the resolver starts nothing.
        """
        return not self.effective.required_capabilities_missing


class CapabilityResolver:
    """Resolve capability layers from Registry metadata and trusted caches.

    Every remote wait is bounded: a probe that outlives ``probe_timeout_seconds``
    becomes a ``probe_timeout`` observation, and a policy source that outlives
    ``policy_timeout_seconds`` ends its in-flight round as a failed observation.
    Neither can wedge a cache refresh, and neither ever grants anything.
    """

    def __init__(
        self,
        *,
        registry: AdapterRegistry,
        probe: TrustedDeploymentProbe,
        policy_provider: TrustedPolicyProvider,
        workspace_port: WorkspaceAvailabilityPort,
        availability_cache: CapabilityCache[AvailabilityCacheKey, AvailableCapabilities],
        policy_cache: CapabilityCache[PolicyCacheKey, PolicyDecisionSet],
        deployment_identity: str,
        probe_timeout_seconds: float,
        policy_timeout_seconds: float,
        probe_max_concurrency: int,
        clock: Callable[[], float],
    ) -> None:
        if probe_timeout_seconds <= 0:
            raise ValueError("probe timeout must be positive")
        if policy_timeout_seconds <= 0:
            raise ValueError("policy timeout must be positive")
        self._registry = registry
        self._probe = probe
        self._policy_provider = policy_provider
        self._workspace_port = workspace_port
        self._availability_cache = availability_cache
        self._policy_cache = policy_cache
        self._deployment_identity = deployment_identity
        self._probe_timeout = probe_timeout_seconds
        self._policy_timeout = policy_timeout_seconds
        self._probe_semaphore = asyncio.Semaphore(max(1, probe_max_concurrency))
        self._clock = clock

    async def wait_idle(self) -> None:
        await self._availability_cache.wait_idle()
        await self._policy_cache.wait_idle()

    async def aclose(self) -> None:
        await self._availability_cache.aclose()
        await self._policy_cache.aclose()

    # ------------------------------------------------------------------ #
    # Declared layer                                                      #
    # ------------------------------------------------------------------ #

    def declared(
        self,
        engine_id: str,
        protocol_id: str,
        adapter_version: str,
    ) -> DeclaredCapabilities:
        """Read-only registry metadata; disabled/unknown triples fail closed."""
        descriptor = self._descriptor(engine_id, protocol_id, adapter_version)
        return self._declared_from(descriptor)

    def _declared_from(self, descriptor: AdapterDescriptor) -> DeclaredCapabilities:
        return DeclaredCapabilities(
            engine_id=descriptor.engine_id,
            protocol_id=descriptor.protocol_id,
            adapter_version=descriptor.adapter_version,
            declaration_schema_version=descriptor.declared_schema_version,
            declaration_digest=canonical_digest(descriptor.declared),
            capabilities=descriptor.declared,
        )

    def _descriptor(
        self,
        engine_id: str,
        protocol_id: str,
        adapter_version: str,
    ) -> AdapterDescriptor:
        return self._registry.metadata(engine_id, protocol_id, adapter_version)

    # ------------------------------------------------------------------ #
    # Cache keys (03 §4.3)                                                #
    # ------------------------------------------------------------------ #

    def availability_key(self, request: CapabilityResolutionRequest) -> AvailabilityCacheKey:
        descriptor, generation, _revision = self._key_inputs(request)
        return self._availability_key(descriptor, generation)

    def policy_key(self, request: CapabilityResolutionRequest) -> PolicyCacheKey:
        descriptor, generation, revision = self._key_inputs(request)
        return self._policy_key(descriptor, generation, request, revision)

    def availability_cache_status(self, request: CapabilityResolutionRequest) -> CacheStatus:
        return self._availability_cache.status(self.availability_key(request))

    def policy_cache_status(self, request: CapabilityResolutionRequest) -> CacheStatus:
        return self._policy_cache.status(self.policy_key(request))

    def _key_inputs(
        self,
        request: CapabilityResolutionRequest,
    ) -> tuple[AdapterDescriptor, AvailabilityGeneration | None, int]:
        """Descriptor, workspace generation, and the live policy revision.

        The revision is observed from the trusted provider on every round
        (R-17); it is never carried by the request DTO.
        """
        descriptor = self._descriptor(
            request.engine_id,
            request.protocol_id,
            request.adapter_version,
        )
        return descriptor, self._workspace_generation(request), self._current_revision(request)

    def _current_revision(self, request: CapabilityResolutionRequest) -> int:
        scope = PolicyRevisionScope(
            tenant_id=request.tenant_id,
            business_scope=request.business_scope,
            workspace_id=request.workspace_id,
            agent_id=request.agent_id,
            agent_published_version=request.agent_published_version,
        )
        try:
            return self._policy_provider.current_revision(scope)
        except Exception as exc:
            # Any provider failure surfaces (BLE001 suppression is not needed:
            # the error is re-raised, never swallowed, and never defaulted to).
            raise PolicySourceUnavailableError from exc

    def _availability_key(
        self,
        descriptor: AdapterDescriptor,
        generation: AvailabilityGeneration | None,
    ) -> AvailabilityCacheKey:
        return AvailabilityCacheKey(
            deployment_identity=self._deployment_identity,
            engine_id=descriptor.engine_id,
            protocol_id=descriptor.protocol_id,
            adapter_version=descriptor.adapter_version,
            config_schema_version=descriptor.config_schema_version,
            probe_id=descriptor.probe_id,
            probe_version=descriptor.probe_version,
            declaration_digest=canonical_digest(descriptor.declared),
            workspace_generation=generation.generation if generation is not None else None,
        )

    def _policy_key(
        self,
        descriptor: AdapterDescriptor,
        generation: AvailabilityGeneration | None,
        request: CapabilityResolutionRequest,
        revision: int,
    ) -> PolicyCacheKey:
        return PolicyCacheKey(
            deployment_identity=self._deployment_identity,
            engine_id=descriptor.engine_id,
            protocol_id=descriptor.protocol_id,
            adapter_version=descriptor.adapter_version,
            config_schema_version=descriptor.config_schema_version,
            probe_id=descriptor.probe_id,
            probe_version=descriptor.probe_version,
            declaration_digest=canonical_digest(descriptor.declared),
            workspace_generation=generation.generation if generation is not None else None,
            tenant_id=request.tenant_id,
            business_scope=request.business_scope,
            workspace_id=request.workspace_id,
            agent_id=request.agent_id,
            agent_published_version=request.agent_published_version,
            policy_provider_id=descriptor.policy_provider_id,
            policy_version=descriptor.policy_version,
            policy_revision=revision,
            disabled_capabilities_digest=disabled_capabilities_digest(
                request.disabled_capabilities
            ),
            execution_restriction_digest=request.execution_restriction_digest,
        )

    def _workspace_generation(
        self,
        request: CapabilityResolutionRequest,
    ) -> AvailabilityGeneration | None:
        if request.business_scope is None or request.workspace_id is None:
            return None
        scope = WorkspaceScope(
            business_scope=request.business_scope,
            workspace_id=request.workspace_id,
        )
        return self._workspace_port.current(scope)

    # ------------------------------------------------------------------ #
    # Hot path: cache reads only                                          #
    # ------------------------------------------------------------------ #

    async def resolve(self, request: CapabilityResolutionRequest) -> CapabilityResolution:
        descriptor, generation, revision = self._key_inputs(request)
        availability_key = self._availability_key(descriptor, generation)
        policy_key = self._policy_key(descriptor, generation, request, revision)
        availability_status = self._availability_cache.status(availability_key)
        policy_status = self._policy_cache.status(policy_key)

        available = self._read_availability(
            descriptor,
            generation,
            availability_key,
            availability_status,
        )
        if availability_status != "fresh":
            self._availability_cache.schedule(
                availability_key,
                lambda: self._load_available(request, generation),
            )

        policy = self._read_policy(policy_key, policy_status)
        if policy_status != "fresh":
            self._policy_cache.schedule(
                policy_key,
                lambda: self._load_policy(request, revision, generation),
            )

        return CapabilityResolution(
            declared=self._declared_from(descriptor),
            available=available,
            policy=policy,
            effective=self._combine(descriptor, available, policy, request, revision),
            availability_status=availability_status,
            policy_status=policy_status,
        )

    def _read_availability(
        self,
        descriptor: AdapterDescriptor,
        generation: AvailabilityGeneration | None,
        availability_key: AvailabilityCacheKey,
        status: CacheStatus,
    ) -> AvailableCapabilities:
        if status == "fresh":
            cached = self._availability_cache.lookup(availability_key).value
            if isinstance(cached, AvailableCapabilities):
                return self._narrow_workspace(cached, descriptor, generation)
        reason = "probe_stale" if status == "stale" else "probe_unavailable"
        return self._synthesize_unavailable(descriptor, reason)

    def _read_policy(
        self,
        policy_key: PolicyCacheKey,
        status: CacheStatus,
    ) -> PolicyDecisionSet | None:
        if status != "fresh":
            return None
        cached = self._policy_cache.lookup(policy_key).value
        return cached if isinstance(cached, PolicyDecisionSet) else None

    # ------------------------------------------------------------------ #
    # Controlled refresh (composition warmer and explicit warm)           #
    # ------------------------------------------------------------------ #

    async def warm(self, request: CapabilityResolutionRequest) -> bool:
        """Awaited refresh of both caches for one target; never builds adapters.

        The in-round observations taken by ``_key_inputs`` are passed down to the
        loaders, so the loader can never re-read a port and land on a different
        workspace generation than the one the cache key was built from (T4
        carry-over: the same skew class as the R-17 revision fix).
        """
        descriptor, generation, revision = self._key_inputs(request)
        availability_ok = (
            await self._availability_cache.refresh(
                self._availability_key(descriptor, generation),
                lambda: self._load_available(request, generation),
            )
            is not None
        )
        policy_ok = (
            await self._policy_cache.refresh(
                self._policy_key(descriptor, generation, request, revision),
                lambda: self._load_policy(request, revision, generation),
            )
            is not None
        )
        return availability_ok and policy_ok

    async def _load_available(
        self,
        request: CapabilityResolutionRequest,
        generation: AvailabilityGeneration | None,
    ) -> AvailableCapabilities:
        descriptor = self._descriptor(
            request.engine_id,
            request.protocol_id,
            request.adapter_version,
        )
        context = ProbeContext(
            deployment_identity=self._deployment_identity,
            engine_id=descriptor.engine_id,
            protocol_id=descriptor.protocol_id,
            adapter_version=descriptor.adapter_version,
            config_schema_version=descriptor.config_schema_version,
            probe_id=descriptor.probe_id,
            probe_version=descriptor.probe_version,
            declaration_digest=canonical_digest(descriptor.declared),
            workspace_generation=(generation.generation if generation is not None else None),
        )
        async with self._probe_semaphore:
            try:
                result = await asyncio.wait_for(
                    self._probe.probe(context),
                    self._probe_timeout,
                )
            except TimeoutError:
                return self._synthesize_unavailable(descriptor, "probe_timeout")
        if (
            result.probe_id != context.probe_id
            or result.probe_version != context.probe_version
            or (result.engine_id, result.protocol_id, result.adapter_version)
            != (context.engine_id, context.protocol_id, context.adapter_version)
        ):
            raise _ProbeMismatchError
        return self._sanitize(descriptor, result, context.declaration_digest)

    def _sanitize(
        self,
        descriptor: AdapterDescriptor,
        result: ProbeResult,
        declaration_digest: str,
    ) -> AvailableCapabilities:
        probe_answers = {item.name: item for item in result.items}
        ordered: list[CapabilityDecision] = []
        for name in CAPABILITY_ORDER:
            declared = bool(getattr(descriptor.declared, name))
            answer = probe_answers[name]
            if not declared:
                ordered.append(_decision(name, False, "not_declared"))
            elif answer.available:
                ordered.append(_decision(name, True, "allowed"))
            else:
                reason = (
                    answer.reason_code
                    if answer.reason_code in _AVAILABILITY_DENIAL_REASONS
                    else "probe_unavailable"
                )
                ordered.append(_decision(name, False, reason))
        return AvailableCapabilities(
            engine_id=descriptor.engine_id,
            protocol_id=descriptor.protocol_id,
            adapter_version=descriptor.adapter_version,
            probe_id=descriptor.probe_id,
            probe_version=descriptor.probe_version,
            observed_at=result.observed_at,
            declaration_digest=declaration_digest,
            deployment_digest=result.deployment_digest,
            items=tuple(ordered),
        )

    def _narrow_workspace(
        self,
        available: AvailableCapabilities,
        descriptor: AdapterDescriptor,
        generation: AvailabilityGeneration | None,
    ) -> AvailableCapabilities:
        """A declared-required workspace with no trusted availability narrows.

        The cached probe answer is deployment truth; the trusted port can only
        narrow the ``workspace_required`` item further, never widen anything.
        """
        if not descriptor.declared.workspace_required:
            return available
        if generation is not None and generation.available:
            return available
        items = tuple(
            _decision(item.name, False, "workspace_unavailable")
            if item.name == "workspace_required"
            else item
            for item in available.items
        )
        return available.model_copy(update={"items": items})

    def _synthesize_unavailable(
        self,
        descriptor: AdapterDescriptor,
        reason: str,
    ) -> AvailableCapabilities:
        items = tuple(
            _decision(
                name,
                False,
                reason if bool(getattr(descriptor.declared, name)) else "not_declared",
            )
            for name in CAPABILITY_ORDER
        )
        return AvailableCapabilities(
            engine_id=descriptor.engine_id,
            protocol_id=descriptor.protocol_id,
            adapter_version=descriptor.adapter_version,
            probe_id=descriptor.probe_id,
            probe_version=descriptor.probe_version,
            observed_at=datetime.fromtimestamp(self._clock(), UTC),
            declaration_digest=canonical_digest(descriptor.declared),
            deployment_digest=UNOBSERVED_DIGEST,
            items=items,
        )

    async def _load_policy(
        self,
        request: CapabilityResolutionRequest,
        revision: int,
        generation: AvailabilityGeneration | None,
    ) -> PolicyDecisionSet:
        descriptor = self._descriptor(
            request.engine_id,
            request.protocol_id,
            request.adapter_version,
        )
        context = PolicyContext(
            engine_id=descriptor.engine_id,
            protocol_id=descriptor.protocol_id,
            adapter_version=descriptor.adapter_version,
            config_schema_version=descriptor.config_schema_version,
            deployment_identity=self._deployment_identity,
            declaration_digest=canonical_digest(descriptor.declared),
            probe_id=descriptor.probe_id,
            probe_version=descriptor.probe_version,
            workspace_generation=(generation.generation if generation is not None else None),
            tenant_id=request.tenant_id,
            business_scope=request.business_scope,
            workspace_id=request.workspace_id,
            agent_id=request.agent_id,
            agent_published_version=request.agent_published_version,
            policy_provider_id=descriptor.policy_provider_id,
            policy_version=descriptor.policy_version,
            policy_revision=revision,
            disabled_capabilities=request.disabled_capabilities,
            execution_restriction_digest=request.execution_restriction_digest,
        )
        try:
            result = await asyncio.wait_for(
                self._policy_provider.resolve(context),
                self._policy_timeout,
            )
        except TimeoutError as exc:
            # Bounded like the probe: the inflight round must end so warm() and
            # wait_idle() return. The cache records the error state, so every
            # later hot read synthesizes the sanitized policy_unavailable view
            # instead of granting anything.
            raise _PolicyTimeoutError from exc
        # The echo check compares against the live round observation, not a
        # request-carried value (R-17): a result for any other revision is a
        # mismatch and takes the error path, never the grant path.
        if (
            result.policy_provider_id != context.policy_provider_id
            or result.policy_version != context.policy_version
            or result.policy_revision != revision
        ):
            raise _PolicyMismatchError
        return result

    # ------------------------------------------------------------------ #
    # Effective combine                                                   #
    # ------------------------------------------------------------------ #

    def _combine(
        self,
        descriptor: AdapterDescriptor,
        available: AvailableCapabilities,
        policy: PolicyDecisionSet | None,
        request: CapabilityResolutionRequest,
        revision: int,
    ) -> EffectiveCapabilities:
        available_map = {item.name: item for item in available.items}
        policy_map = _policy_layers(policy) if policy is not None else None
        disabled = set(request.disabled_capabilities)
        items: list[EffectiveCapabilityDecision] = []
        missing: list[CapabilityName] = []
        for name in CAPABILITY_ORDER:
            if not bool(getattr(descriptor.declared, name)):
                items.append(_ineffective(name, "not_declared"))
                continue
            if policy_map is None:
                # Missing or untrusted policy fails closed before anything else.
                items.append(_ineffective(name, "policy_unavailable"))
                missing.append(name)
                continue
            effective, reason = _effective_one(
                name,
                available_map[name],
                policy_map[name],
                disabled,
            )
            items.append(_effective_item(name, effective, "allowed" if effective else reason))
            if not effective and reason in _REQUIRED_MISSING_REASONS:
                missing.append(name)
        return EffectiveCapabilities(
            engine_id=descriptor.engine_id,
            protocol_id=descriptor.protocol_id,
            adapter_version=descriptor.adapter_version,
            tenant_id=request.tenant_id,
            declaration_digest=available.declaration_digest,
            probe_id=descriptor.probe_id,
            probe_version=descriptor.probe_version,
            policy_provider_id=descriptor.policy_provider_id,
            policy_version=descriptor.policy_version,
            # Always the live observation for this round (R-17): a cached or
            # request-carried revision can never pin Effective provenance.
            policy_revision=revision,
            items=tuple(items),
            required_capabilities_missing=tuple(missing),
        )


# ---------------------------------------------------------------------- #
# Module helpers                                                          #
# ---------------------------------------------------------------------- #


def _decision(name: str, available: bool, reason: str) -> CapabilityDecision:
    return CapabilityDecision(name=name, available=available, reason_code=reason)


def _ineffective(name: str, reason: str) -> EffectiveCapabilityDecision:
    return _effective_item(name, False, reason)


def _effective_item(name: str, effective: bool, reason: str) -> EffectiveCapabilityDecision:
    return EffectiveCapabilityDecision(name=name, effective=effective, reason_code=reason)


def _policy_layers(policy: PolicyDecisionSet) -> dict[str, dict[str, object]]:
    layers: dict[str, dict[str, object]] = {}
    for decision in policy.decisions:
        by_layer = {layer.layer: layer for layer in decision.layers}
        if any(layer not in by_layer for layer in ("platform", "tenant", "agent", "execution")):
            raise _PolicyMismatchError
        layers[decision.name] = by_layer
    if any(name not in layers for name in CAPABILITY_ORDER):
        raise _PolicyMismatchError
    return layers


def _effective_one(
    name: str,
    availability: CapabilityDecision,
    layers: dict[str, object],
    disabled: set[str],
) -> tuple[bool, str]:
    platform = layers["platform"]
    tenant = layers["tenant"]
    agent = layers["agent"]
    execution = layers["execution"]
    if not availability.available:
        reason = availability.reason_code
        # The contract forbids available=False with reason "allowed", so any
        # reason outside the availability denial set is a degraded observation.
        if reason not in _AVAILABILITY_DENIAL_REASONS:
            reason = "probe_unavailable"
        return False, reason
    if not platform.allowed:
        return False, "platform_denied"
    if not tenant.allowed:
        return False, "tenant_denied"
    if name in disabled or not agent.allowed:
        return False, "agent_disabled"
    if not execution.allowed:
        return False, "execution_denied"
    return True, "allowed"
