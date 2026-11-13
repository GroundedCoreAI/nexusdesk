"""Trusted capability resolution: ports, caches, resolver, and warmer."""

from .cache import (
    AvailabilityCacheKey,
    CacheLookup,
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
from .resolver import (
    CapabilityResolution,
    CapabilityResolutionRequest,
    CapabilityResolver,
    PolicySourceUnavailableError,
)
from .snapshots import (
    CapabilitySnapshotSet,
    build_available_capabilities_snapshot,
    build_capability_snapshots,
    build_declared_capabilities_snapshot,
    build_effective_capabilities_snapshot,
    build_execution_policy_snapshot,
)
from .warmer import CapabilityWarmer

__all__ = [
    "AvailabilityCacheKey",
    "AvailabilityGeneration",
    "CacheLookup",
    "CacheStatus",
    "CapabilityCache",
    "CapabilityResolution",
    "CapabilityResolutionRequest",
    "CapabilityResolver",
    "CapabilitySnapshotSet",
    "CapabilityWarmer",
    "PolicyCacheKey",
    "PolicyContext",
    "PolicyRevisionScope",
    "PolicySourceUnavailableError",
    "ProbeContext",
    "ProbeResult",
    "TrustedDeploymentProbe",
    "TrustedPolicyProvider",
    "WorkspaceAvailabilityPort",
    "WorkspaceScope",
    "build_available_capabilities_snapshot",
    "build_capability_snapshots",
    "build_declared_capabilities_snapshot",
    "build_effective_capabilities_snapshot",
    "build_execution_policy_snapshot",
]
