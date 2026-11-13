"""Snapshot builders whose only input is a complete ``CapabilityResolution``.

R-22 makes the type the gate: the four capability-class snapshots are derived
from :class:`CapabilityResolution` — whose ``available``/``effective`` layers
already carry the trusted workspace narrowing — and never from
``AvailableCapabilities``, ``CacheLookup``, or raw dicts. Bypassing this
module to read cache values directly would produce contradictory evidence and
is a P1 defect. This module lives in the capability package so the execution
contracts layer keeps its one-directional dependency on nothing above it.
"""

from dataclasses import dataclass
from uuid import UUID

from ..contracts.config import EngineIdentity
from ..contracts.snapshots import (
    AvailableCapabilitiesSnapshot,
    DeclaredCapabilitiesSnapshot,
    EffectiveCapabilitiesSnapshot,
    ExecutionPolicySnapshot,
    ExecutionSnapshotError,
    _available_snapshot_from,
    _declared_snapshot_from,
    _effective_snapshot_from,
    _policy_snapshot_from,
)
from .resolver import CapabilityResolution


@dataclass(frozen=True, slots=True)
class CapabilitySnapshotSet:
    """The four capability-class snapshots sharing one startup identity."""

    declared: DeclaredCapabilitiesSnapshot
    available: AvailableCapabilitiesSnapshot
    policy: ExecutionPolicySnapshot
    effective: EffectiveCapabilitiesSnapshot


def _require_inputs(execution_id: UUID, resolution: CapabilityResolution) -> None:
    if not isinstance(execution_id, UUID):
        raise ExecutionSnapshotError("snapshot_field_invalid", ("execution_id",)) from None
    # isinstance on the frozen dataclass is exact enough here: the layers are
    # dataclass fields, so anything duck-typed without the class fails closed.
    if not isinstance(resolution, CapabilityResolution):
        raise ExecutionSnapshotError("snapshot_resolution_required") from None


def _engine(resolution: CapabilityResolution) -> EngineIdentity:
    declared = resolution.declared
    return EngineIdentity(
        engine_id=declared.engine_id,
        protocol_id=declared.protocol_id,
        adapter_version=declared.adapter_version,
    )


def _require_same_engine(resolution: CapabilityResolution) -> None:
    engine = (
        resolution.declared.engine_id,
        resolution.declared.protocol_id,
        resolution.declared.adapter_version,
    )
    for layer in (resolution.available, resolution.effective):
        if (layer.engine_id, layer.protocol_id, layer.adapter_version) != engine:
            raise ExecutionSnapshotError("snapshot_identity_mismatch") from None


def build_declared_capabilities_snapshot(
    execution_id: UUID, resolution: CapabilityResolution
) -> DeclaredCapabilitiesSnapshot:
    """Declared layer straight from the resolved identity."""

    _require_inputs(execution_id, resolution)
    _require_same_engine(resolution)
    return _declared_snapshot_from(execution_id, resolution.declared)


def build_available_capabilities_snapshot(
    execution_id: UUID, resolution: CapabilityResolution
) -> AvailableCapabilitiesSnapshot:
    """Available layer including the workspace narrowing applied on read (R-22)."""

    _require_inputs(execution_id, resolution)
    _require_same_engine(resolution)
    return _available_snapshot_from(execution_id, resolution.available)


def build_execution_policy_snapshot(
    execution_id: UUID,
    resolution: CapabilityResolution,
    *,
    disabled_capabilities_digest: str,
    execution_restriction_digest: str,
) -> ExecutionPolicySnapshot:
    """Policy layer; a resolution without trusted policy cannot be snapshotted.

    ``disabled_capabilities_digest`` and ``execution_restriction_digest`` are
    the server-computed narrowing summaries for this startup (canonical
    digests, never raw lists or restriction content).
    """

    _require_inputs(execution_id, resolution)
    _require_same_engine(resolution)
    if resolution.policy is None:
        raise ExecutionSnapshotError("snapshot_policy_unavailable") from None
    return _policy_snapshot_from(
        execution_id,
        _engine(resolution),
        resolution.policy,
        disabled_capabilities_digest=disabled_capabilities_digest,
        execution_restriction_digest=execution_restriction_digest,
    )


def build_effective_capabilities_snapshot(
    execution_id: UUID, resolution: CapabilityResolution
) -> EffectiveCapabilitiesSnapshot:
    """Effective layer with resolved declaration/probe/policy provenance."""

    _require_inputs(execution_id, resolution)
    _require_same_engine(resolution)
    return _effective_snapshot_from(execution_id, resolution.effective)


def build_capability_snapshots(
    execution_id: UUID,
    resolution: CapabilityResolution,
    *,
    disabled_capabilities_digest: str,
    execution_restriction_digest: str,
) -> CapabilitySnapshotSet:
    """Build all four capability-class snapshots from one resolution."""

    return CapabilitySnapshotSet(
        declared=build_declared_capabilities_snapshot(execution_id, resolution),
        available=build_available_capabilities_snapshot(execution_id, resolution),
        policy=build_execution_policy_snapshot(
            execution_id,
            resolution,
            disabled_capabilities_digest=disabled_capabilities_digest,
            execution_restriction_digest=execution_restriction_digest,
        ),
        effective=build_effective_capabilities_snapshot(execution_id, resolution),
    )
