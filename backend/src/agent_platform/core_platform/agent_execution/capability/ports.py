"""Trusted capability ports: deployment probe, policy provider, workspace.

The three protocols here are injected by composition with trusted
implementations. Request DTOs can never select, construct, or carry these
contexts; the resolver builds every context from registry metadata and the
authenticated server-side scope only.
"""

from datetime import datetime
from typing import Literal, Protocol, Self, runtime_checkable
from uuid import UUID

from pydantic import Field, model_validator

from ..contracts.base import ExecutionContractModel
from ..contracts.capabilities import (
    CAPABILITY_ORDER,
    CapabilityDecision,
    DigestString,
    PolicyDecisionSet,
)
from ..contracts.common import AdapterVersion, EngineId, OpaqueString, ProtocolId, Slug
from ..contracts.config import CapabilityName


class ProbeContext(ExecutionContractModel):
    """Deployment identity for one bounded, version-exact probe.

    ``workspace_generation`` is either ``None`` (no trusted workspace exists)
    or a non-negative generation number from the trusted workspace port.
    """

    contract_version: Literal["v1"] = "v1"
    deployment_identity: OpaqueString
    engine_id: EngineId
    protocol_id: ProtocolId
    adapter_version: AdapterVersion
    config_schema_version: AdapterVersion
    probe_id: Slug
    probe_version: AdapterVersion
    declaration_digest: DigestString
    workspace_generation: int | None = Field(default=None, ge=0)


class ProbeResult(ExecutionContractModel):
    """Raw probe answer, still unsanitized; never surfaces on a public DTO."""

    contract_version: Literal["v1"] = "v1"
    engine_id: EngineId
    protocol_id: ProtocolId
    adapter_version: AdapterVersion
    probe_id: Slug
    probe_version: AdapterVersion
    observed_at: datetime
    deployment_digest: DigestString
    items: tuple[CapabilityDecision, ...]

    @model_validator(mode="after")
    def items_are_complete(self) -> Self:
        names = tuple(item.name for item in self.items)
        if names != CAPABILITY_ORDER:
            raise ValueError("Probe items must cover every capability exactly once in order")
        return self


@runtime_checkable
class TrustedDeploymentProbe(Protocol):
    """Server-owned deployment probe with a bounded timeout and concurrency."""

    async def probe(self, context: ProbeContext) -> ProbeResult: ...


class WorkspaceScope(ExecutionContractModel):
    """Trusted business/workspace scope; never client-selected content."""

    business_scope: OpaqueString
    workspace_id: OpaqueString


class AvailabilityGeneration(ExecutionContractModel):
    """Monotonic workspace availability generation observed by the platform."""

    generation: int = Field(ge=0)
    available: bool


@runtime_checkable
class WorkspaceAvailabilityPort(Protocol):
    """Synchronous, locally-cached trusted view of workspace availability."""

    def current(self, scope: WorkspaceScope) -> AvailabilityGeneration | None: ...


class PolicyContext(ExecutionContractModel):
    """Fully trusted inputs for one policy resolution.

    ``disabled_capabilities`` originates from the published agent configuration
    extracted server-side; it is not accepted from run requests.
    ``policy_revision`` is the revision the resolver just observed from the
    trusted provider's ``current_revision`` for this round; it is never taken
    from a request DTO.
    """

    contract_version: Literal["v1"] = "v1"
    engine_id: EngineId
    protocol_id: ProtocolId
    adapter_version: AdapterVersion
    config_schema_version: AdapterVersion
    deployment_identity: OpaqueString
    declaration_digest: DigestString
    probe_id: Slug
    probe_version: AdapterVersion
    workspace_generation: int | None = Field(default=None, ge=0)
    tenant_id: str = Field(min_length=1, max_length=200)
    business_scope: OpaqueString | None = None
    workspace_id: OpaqueString | None = None
    agent_id: UUID | None = None
    agent_published_version: int | None = Field(default=None, ge=0)
    policy_provider_id: Slug
    policy_version: AdapterVersion
    policy_revision: int = Field(ge=0)
    disabled_capabilities: tuple[CapabilityName, ...] = ()
    execution_restriction_digest: DigestString


class PolicyRevisionScope(ExecutionContractModel):
    """Trusted scope for one live policy-revision observation.

    Mirrors the scope half of :class:`PolicyContext` without any engine or
    provider identity: the revision is a property of the tenant/agent scope
    and is read synchronously from the trusted source, never carried by a
    request DTO.
    """

    contract_version: Literal["v1"] = "v1"
    tenant_id: str = Field(min_length=1, max_length=200)
    business_scope: OpaqueString | None = None
    workspace_id: OpaqueString | None = None
    agent_id: UUID | None = None
    agent_published_version: int | None = Field(default=None, ge=0)


class TrustedPolicyProvider(Protocol):
    """Server-owned policy source; results are validated before use."""

    def current_revision(self, scope: PolicyRevisionScope) -> int:
        """Live policy revision for one trusted scope.

        Synchronous, local, no remote I/O: implementations must answer from
        an in-process view so the read is allowed on the synchronous hot
        path. A failing source must raise; the resolver surfaces the failure
        and never substitutes a default revision.
        """
        ...

    async def resolve(self, context: PolicyContext) -> PolicyDecisionSet: ...
