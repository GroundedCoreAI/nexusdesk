"""Layered engine capability contracts: declared, available, policy, effective."""

import hashlib
import json
from collections.abc import Iterable
from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from .base import ExecutionContractModel
from .common import AdapterVersion, EngineId, ProtocolId, Slug
from .config import CapabilityName


class EngineCapabilities(ExecutionContractModel):
    """Independent declared capabilities with no implication rules."""

    contract_version: Literal["v1"] = "v1"
    streaming: bool = False
    persistent_session: bool = False
    session_resume: bool = False
    cancellation: bool = False
    human_approval: bool = False
    interactive_input: bool = False
    tool_calling: bool = False
    file_operations: bool = False
    terminal_execution: bool = False
    native_events: bool = False
    workspace_required: bool = False


CapabilityReasonCode = Literal[
    "allowed",
    "not_declared",
    "probe_unavailable",
    "probe_timeout",
    "probe_stale",
    "workspace_unavailable",
    "platform_denied",
    "tenant_denied",
    "agent_disabled",
    "execution_denied",
    "policy_unavailable",
]
PolicyLayerName = Literal["platform", "tenant", "agent", "execution"]

CAPABILITY_ORDER: tuple[CapabilityName, ...] = (
    "streaming",
    "persistent_session",
    "session_resume",
    "cancellation",
    "human_approval",
    "interactive_input",
    "tool_calling",
    "file_operations",
    "terminal_execution",
    "native_events",
    "workspace_required",
)
POLICY_LAYER_ORDER: tuple[PolicyLayerName, ...] = ("platform", "tenant", "agent", "execution")

DigestString = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
# Stable digest used whenever no observation exists yet; never an authorization.
UNOBSERVED_DIGEST: str = hashlib.sha256(b"nexusdesk:capability:unobserved").hexdigest()


def canonical_digest(value: ExecutionContractModel) -> str:
    """SHA-256 of the canonical JSON form; order-stable and collision-free."""

    payload = json.dumps(value.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def disabled_capabilities_digest(names: Iterable[CapabilityName]) -> str:
    """Order- and duplicate-insensitive digest of the server-trusted disable list."""

    ordered = sorted({str(name) for name in names})
    payload = json.dumps(ordered, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def execution_restriction_digest(values: Iterable[str]) -> str:
    """Digest of server-trusted execution restrictions.

    Shares the exact canonical shape of ``disabled_capabilities_digest``:
    sorted, de-duplicated string set serialized as a compact JSON array and
    hashed with SHA-256. The empty restriction set always projects to
    ``NO_EXECUTION_RESTRICTIONS``.
    """

    ordered = sorted({str(value) for value in values})
    payload = json.dumps(ordered, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# Canonical projection of "this execution carries no server-trusted
# restrictions"; equals execution_restriction_digest(()) by construction.
NO_EXECUTION_RESTRICTIONS: str = execution_restriction_digest(())


def _require_unique_order(
    names: tuple[str, ...],
    expected: tuple[str, ...],
    label: str,
) -> None:
    if tuple(names) != tuple(expected):
        raise ValueError(f"{label} must cover every entry exactly once in canonical order")


class CapabilityDecision(ExecutionContractModel):
    """One sanitized per-capability availability observation."""

    name: CapabilityName
    available: bool
    reason_code: CapabilityReasonCode

    @model_validator(mode="after")
    def reason_matches_availability(self) -> Self:
        if self.available and self.reason_code != "allowed":
            raise ValueError("available capabilities must carry the allowed reason")
        if not self.available and self.reason_code == "allowed":
            raise ValueError("unavailable capabilities must carry a stable denial reason")
        return self


class DeclaredCapabilities(ExecutionContractModel):
    """Read-only registry metadata; client input can never override it."""

    contract_version: Literal["v1"] = "v1"
    engine_id: EngineId
    protocol_id: ProtocolId
    adapter_version: AdapterVersion
    declaration_schema_version: AdapterVersion
    declaration_digest: DigestString
    capabilities: EngineCapabilities


class AvailableCapabilities(ExecutionContractModel):
    """Deployment observation with no raw probe response content."""

    contract_version: Literal["v1"] = "v1"
    engine_id: EngineId
    protocol_id: ProtocolId
    adapter_version: AdapterVersion
    probe_id: Slug
    probe_version: AdapterVersion
    observed_at: datetime
    declaration_digest: DigestString
    deployment_digest: DigestString
    items: tuple[CapabilityDecision, ...]

    @model_validator(mode="after")
    def items_are_complete(self) -> Self:
        _require_unique_order(
            tuple(item.name for item in self.items),
            CAPABILITY_ORDER,
            "Availability items",
        )
        return self


class PolicyLayerDecision(ExecutionContractModel):
    """One trusted-layer decision for one capability."""

    layer: PolicyLayerName
    allowed: bool
    source: Slug
    reason_code: CapabilityReasonCode

    @model_validator(mode="after")
    def reason_matches_decision(self) -> Self:
        if self.allowed and self.reason_code != "allowed":
            raise ValueError("allowed layer decisions must carry the allowed reason")
        if not self.allowed and self.reason_code == "allowed":
            raise ValueError("denied layer decisions must carry a stable denial reason")
        return self


class CapabilityPolicy(ExecutionContractModel):
    """All four trusted layers for one capability; none may be omitted."""

    name: CapabilityName
    layers: tuple[PolicyLayerDecision, ...]

    @model_validator(mode="after")
    def layers_are_complete(self) -> Self:
        _require_unique_order(
            tuple(layer.layer for layer in self.layers),
            POLICY_LAYER_ORDER,
            "Policy layers",
        )
        return self


class PolicyLayerVersion(ExecutionContractModel):
    """Version/revision provenance for one policy layer."""

    layer: PolicyLayerName
    version: Slug
    revision: int = Field(ge=0)


class PolicyDecisionSet(ExecutionContractModel):
    """Trusted policy output; every layer may only narrow, never grant."""

    contract_version: Literal["v1"] = "v1"
    policy_provider_id: Slug
    policy_version: AdapterVersion
    policy_revision: int = Field(ge=0)
    resolved_at: datetime
    layer_versions: tuple[PolicyLayerVersion, ...]
    decisions: tuple[CapabilityPolicy, ...]

    @model_validator(mode="after")
    def coverage_is_complete(self) -> Self:
        _require_unique_order(
            tuple(entry.layer for entry in self.layer_versions),
            POLICY_LAYER_ORDER,
            "Policy layer versions",
        )
        _require_unique_order(
            tuple(decision.name for decision in self.decisions),
            CAPABILITY_ORDER,
            "Policy decisions",
        )
        return self


class EffectiveCapabilityDecision(ExecutionContractModel):
    """Final server-computed capability decision for one capability."""

    name: CapabilityName
    effective: bool
    reason_code: CapabilityReasonCode

    @model_validator(mode="after")
    def reason_matches_effective(self) -> Self:
        if self.effective and self.reason_code != "allowed":
            raise ValueError("effective capabilities must carry the allowed reason")
        if not self.effective and self.reason_code == "allowed":
            raise ValueError("ineffective capabilities must carry a stable denial reason")
        return self


class EffectiveCapabilities(ExecutionContractModel):
    """Monotonically narrowed result with resolved version summaries only."""

    contract_version: Literal["v1"] = "v1"
    engine_id: EngineId
    protocol_id: ProtocolId
    adapter_version: AdapterVersion
    tenant_id: str = Field(min_length=1, max_length=200)
    declaration_digest: DigestString
    probe_id: Slug
    probe_version: AdapterVersion
    policy_provider_id: Slug
    policy_version: AdapterVersion
    policy_revision: int = Field(ge=0)
    items: tuple[EffectiveCapabilityDecision, ...]
    required_capabilities_missing: tuple[CapabilityName, ...] = ()

    @model_validator(mode="after")
    def items_are_complete(self) -> Self:
        _require_unique_order(
            tuple(item.name for item in self.items),
            CAPABILITY_ORDER,
            "Effective items",
        )
        false_names = {item.name for item in self.items if not item.effective}
        if len(set(self.required_capabilities_missing)) != len(self.required_capabilities_missing):
            raise ValueError("Required capability names must be unique")
        if not set(self.required_capabilities_missing) <= false_names:
            raise ValueError("Required capability missing entries must be ineffective")
        return self


def effective_capability_flags(effective: EffectiveCapabilities) -> dict[str, bool]:
    """The only legal projection into ``ExecutionRequest.effective_capabilities``.

    Always exactly 11 entries in :data:`CAPABILITY_ORDER` order; denied and
    non-declared capabilities stay explicit ``False`` and are never omitted,
    so a consumer can never mistake an absent key for a grant.
    """

    by_name = {item.name: item.effective for item in effective.items}
    return {name: by_name[name] for name in CAPABILITY_ORDER}


def effective_capability_views(
    effective: EffectiveCapabilities,
) -> tuple[EffectiveCapabilityDecision, ...]:
    """Preview/audit projection: the name/effective/reason triple per capability.

    Canonical :data:`CAPABILITY_ORDER` order, reusing the existing
    :class:`EffectiveCapabilityDecision` model; the flags projection and this
    view describe one and the same semantics for the same instance.
    """

    by_name = {item.name: item for item in effective.items}
    return tuple(by_name[name] for name in CAPABILITY_ORDER)
