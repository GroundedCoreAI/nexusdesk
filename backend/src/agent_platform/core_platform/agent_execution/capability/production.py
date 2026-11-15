"""Phase 3 production trusted ports: declaration-derived probe, allow-list policy.

03 §4.2 states the warmer never constructs an Adapter, so a probe that consulted
``adapter.get_capabilities()`` would both contradict that discipline and couple
the probe lifetime to Adapter identity/contract tracking. Phase 3 has no external
deployment to observe either: ``probe_id``/``probe_version`` share one source with
the registered descriptor and the cache keys, so "missing deployment",
"incompatible version" and "probe timeout" are structurally unreachable here
(R-42, 04 P3-IT-21 evidence boundary). The honest production answers are therefore:

* Available is declaration-derived — exactly what the Registry declares is
  available, and nothing more. ``_sanitize`` re-clamps any widened answer, so
  ``Available <= Declared`` is structural rather than a property of this class.
* the platform ceiling is a code allow-list that equals React's four true
  declarations; the seven denied names are ``not_declared`` short-circuited by
  ``_combine``, so ``platform_denied`` becomes observable only once a later phase
  registers an engine that declares one of them (R-44, 05 A4);
* the policy revision is a scope-stable constant. It must never advance per call:
  the policy key embeds the live revision, so a clock- or DB-derived value would
  make every hot read cold, every declared capability ``policy_unavailable``, and
  every Run and preview fail closed forever, silently (R-44, C1 veto face).

Composition injects these implementations through a code-level ``ports=`` seam
only; settings and environment variables must never select a trusted port.

Phase 4/5 replacement point: register a real Host/Workdir probe through that same
``TrustedDeploymentProbe`` protocol and a real generation source through
``WorkspaceAvailabilityPort``, replacing this module's classes rather than adding
a second abstraction. Until a trusted Workdir generation exists, the workspace
port must keep returning ``None``: reporting ``generation=N, available=False``
would split the Available cache key into one entry per fabricated generation for
no authorization benefit.
"""

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime

from ..contracts.capabilities import (
    CAPABILITY_ORDER,
    POLICY_LAYER_ORDER,
    CapabilityDecision,
    CapabilityPolicy,
    EngineCapabilities,
    PolicyDecisionSet,
    PolicyLayerDecision,
    PolicyLayerVersion,
)
from ..contracts.config import CapabilityName
from ..registry.adapter_registry import AdapterDescriptor, AdapterRegistry
from .ports import (
    AvailabilityGeneration,
    PolicyContext,
    PolicyRevisionScope,
    ProbeContext,
    ProbeResult,
    WorkspaceScope,
)

# Phase 3 platform ceiling: a default-deny allow-list that is exactly the set of
# capabilities the production React Engine declares. Denying anything React does
# not declare would fabricate evidence, and declaring more than the ceiling allows
# would silently grant it (R-44).
PHASE3_PLATFORM_CAPABILITY_ALLOWLIST: frozenset[CapabilityName] = frozenset(
    {"streaming", "cancellation", "tool_calling", "native_events"}
)

# No versioned tenant capability store exists in Phase 3, so the revision is a
# scope-stable constant. A constant is trivially monotonic, which is what 03 §4.2
# requires of a compliant implementation; R-17's "never default to 0" binds only
# the raising read path, where the resolver surfaces
# ``PolicySourceUnavailableError`` instead of substituting this value.
NO_TENANT_POLICY_REVISION: int = 0

# Constant provenance version for every policy layer. ``layer_versions`` must be
# complete (``PolicyDecisionSet.coverage_is_complete``), and there is no per-layer
# store to consult in Phase 3.
POLICY_LAYER_PROVENANCE_VERSION: str = "v1"

# Sources recorded on a layer decision. They name the trusted in-process source,
# never a tenant-supplied value: a policy source must not be able to echo an
# ``allowed`` decision with a denial reason or the reverse.
_PLATFORM_SOURCE: str = "platform-allowlist"
_TENANT_SOURCE: str = "tenant-default"
_AGENT_SOURCE: str = "agent-published"
_EXECUTION_SOURCE: str = "execution-default"


class DeclarationDerivedDeploymentProbe:
    """Answer a probe from the Registry's declarations and nothing else.

    The probe is synchronous-metadata only: it never resolves, constructs, or
    consults an Adapter, so a warm round cannot instantiate an Engine and a probe
    cannot become a second, later-diverging declaration source (03 §4.2, R-42).
    """

    def __init__(self, *, registry: AdapterRegistry, clock: Callable[[], float]) -> None:
        self._registry = registry
        self._clock = clock

    async def probe(self, context: ProbeContext) -> ProbeResult:
        declared = self._declared(context)
        items = tuple(
            CapabilityDecision(
                name=name,
                available=bool(getattr(declared, name)),
                reason_code="allowed" if getattr(declared, name) else "probe_unavailable",
            )
            for name in CAPABILITY_ORDER
        )
        return ProbeResult(
            engine_id=context.engine_id,
            protocol_id=context.protocol_id,
            adapter_version=context.adapter_version,
            probe_id=context.probe_id,
            probe_version=context.probe_version,
            observed_at=datetime.fromtimestamp(self._clock(), UTC),
            deployment_digest=self.deployment_digest(context),
            items=items,
        )

    def deployment_digest(self, context: ProbeContext) -> str:
        """Stable SHA-256 over the observed deployment identity, never a placeholder.

        ``UNOBSERVED_DIGEST`` belongs exclusively to "no observation yet" (the
        resolver's synthesized fail-closed view). A probe that has answered must
        carry a real digest, otherwise the Available snapshot stops being
        evidence that this deployment was observed (R-42).
        """
        declared = self._declared(context)
        material = {
            "deployment_identity": context.deployment_identity,
            "engine_id": context.engine_id,
            "protocol_id": context.protocol_id,
            "adapter_version": context.adapter_version,
            "config_schema_version": context.config_schema_version,
            "probe_id": context.probe_id,
            "probe_version": context.probe_version,
            "declaration_digest": context.declaration_digest,
            "declared": declared.model_dump(mode="json"),
        }
        canonical = json.dumps(material, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _declared(self, context: ProbeContext) -> EngineCapabilities:
        # The Registry descriptor is the only declaration source: the digest is
        # already part of the cache key and the probe context, so an answer for
        # another declaration could never be mistaken for a grant here.
        return self._descriptor(context).declared

    def _descriptor(self, context: ProbeContext) -> AdapterDescriptor:
        return self._registry.metadata(
            context.engine_id,
            context.protocol_id,
            context.adapter_version,
        )


class PlatformDefaultPolicyProvider:
    """Minimal-privilege policy layers from code constants and published config.

    The provider never receives client input: the only narrowing it applies comes
    from the published Agent configuration already carried in the trusted
    ``PolicyContext`` (R-44). Tenant and execution layers have no Phase 3 source,
    so they are uniformly ``allowed`` — an information absence that cannot widen
    the ceiling, because Effective is a six-term AND and ``_effective_one``
    short-circuits (05 A4 completeness gap, registered honestly).
    """

    def __init__(
        self,
        *,
        policy_provider_id: str,
        policy_version: str,
        clock: Callable[[], float],
    ) -> None:
        self.policy_provider_id = policy_provider_id
        self.policy_version = policy_version
        self._clock = clock

    def current_revision(self, scope: PolicyRevisionScope) -> int:
        """Scope-stable constant: synchronous, local, and no I/O (03 §4.2, R-44).

        Forbidden here is any per-call advance (a clock reading or a
        ``max(updated_at)`` query): the policy key embeds this revision, so an
        advancing value makes every hot read cold and every Run fail closed
        permanently and silently.
        """
        return NO_TENANT_POLICY_REVISION

    async def resolve(self, context: PolicyContext) -> PolicyDecisionSet:
        disabled = set(context.disabled_capabilities)
        decisions = tuple(
            CapabilityPolicy(
                name=name,
                layers=(
                    _platform_layer(name),
                    _tenant_layer(),
                    _agent_layer(name, disabled),
                    _execution_layer(),
                ),
            )
            for name in CAPABILITY_ORDER
        )
        return PolicyDecisionSet(
            policy_provider_id=context.policy_provider_id,
            policy_version=context.policy_version,
            # The echo is the live observation the resolver just read for this
            # round (R-17); a self-computed value would be a _PolicyMismatchError.
            policy_revision=context.policy_revision,
            resolved_at=datetime.fromtimestamp(self._clock(), UTC),
            layer_versions=tuple(
                PolicyLayerVersion(
                    layer=layer,
                    version=POLICY_LAYER_PROVENANCE_VERSION,
                    revision=context.policy_revision,
                )
                for layer in POLICY_LAYER_ORDER
            ),
            decisions=decisions,
        )


class NoTrustedWorkspaceGeneration:
    """No trusted Workdir availability exists in Phase 3, and None says so.

    This is the fail-closed honest answer, not an unimplemented stub: claiming
    ``AvailabilityGeneration(available=True)`` would fabricate availability (03
    §4.1 forbids pseudo-reporting a Workspace as available), and claiming
    ``available=False`` at some generation number would split the Available cache
    key into one entry per fabricated generation while granting nothing.

    Phase 4/5 replacement point: register a real source behind the same
    ``WorkspaceAvailabilityPort`` protocol and keep returning ``None`` until a
    trusted Workdir generation actually exists.
    """

    def current(self, scope: WorkspaceScope) -> AvailabilityGeneration | None:
        return None


def _platform_layer(name: CapabilityName) -> PolicyLayerDecision:
    allowed = name in PHASE3_PLATFORM_CAPABILITY_ALLOWLIST
    return PolicyLayerDecision(
        layer="platform",
        allowed=allowed,
        source=_PLATFORM_SOURCE,
        reason_code="allowed" if allowed else "platform_denied",
    )


def _tenant_layer() -> PolicyLayerDecision:
    return PolicyLayerDecision(
        layer="tenant",
        allowed=True,
        source=_TENANT_SOURCE,
        reason_code="allowed",
    )


def _agent_layer(name: CapabilityName, disabled: set[str]) -> PolicyLayerDecision:
    denied = name in disabled
    return PolicyLayerDecision(
        layer="agent",
        allowed=not denied,
        source=_AGENT_SOURCE,
        reason_code="agent_disabled" if denied else "allowed",
    )


def _execution_layer() -> PolicyLayerDecision:
    # Phase 3 has no execution-restriction source; R-17 froze the digest to
    # ``NO_EXECUTION_RESTRICTIONS``, so this layer can only be a no-op.
    return PolicyLayerDecision(
        layer="execution",
        allowed=True,
        source=_EXECUTION_SOURCE,
        reason_code="allowed",
    )


__all__ = [
    "NO_TENANT_POLICY_REVISION",
    "PHASE3_PLATFORM_CAPABILITY_ALLOWLIST",
    "POLICY_LAYER_PROVENANCE_VERSION",
    "DeclarationDerivedDeploymentProbe",
    "NoTrustedWorkspaceGeneration",
    "PlatformDefaultPolicyProvider",
]
