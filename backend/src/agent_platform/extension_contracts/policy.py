"""Policy and execution-harness contracts."""

from typing import Literal, Protocol
from uuid import UUID

from pydantic import Field

from .base import ContractModel
from .tools import ToolRisk

RiskLevel = ToolRisk


class PolicyContext(ContractModel):
    """Trusted context used for authorization and execution constraints."""

    tenant_id: str = Field(min_length=1, max_length=200)
    actor_id: str | None = Field(default=None, min_length=1, max_length=200)
    roles: frozenset[str] = frozenset()
    run_id: UUID | None = None
    conversation_id: UUID | None = None
    source: Literal["runtime", "application", "worker", "system"]
    business_id: str | None = Field(default=None, min_length=1, max_length=100)
    workspace_id: str | None = Field(default=None, min_length=1, max_length=100)


class ConfirmationRequirement(ContractModel):
    """Describes whether a proposed operation needs a human decision."""

    required: bool = False
    action: str | None = Field(default=None, min_length=1, max_length=100)
    expires_seconds: int | None = Field(default=None, ge=1, le=86_400)


class ExecutionConstraint(ContractModel):
    """Limits applied after authorization and before execution."""

    max_attempts: int = Field(default=1, ge=1, le=10)
    timeout_seconds: float = Field(default=30, gt=0, le=600)
    concurrency_key: str | None = Field(default=None, min_length=1, max_length=200)
    idempotency_required: bool = False


class PolicyDecision(ContractModel):
    """Normalized policy outcome understood by the Tool Gateway."""

    effect: Literal["allow", "deny"]
    reason_code: str = Field(min_length=1, max_length=200)
    risk: RiskLevel = "read"
    confirmation: ConfirmationRequirement = Field(default_factory=ConfirmationRequirement)
    constraint: ExecutionConstraint = Field(default_factory=ExecutionConstraint)
    policy_version: str = Field(default="baseline-v1", min_length=1, max_length=100)

    @property
    def allowed(self) -> bool:
        """Whether the operation may proceed to the next harness stage."""

        return self.effect == "allow"


class PolicyProvider(Protocol):
    """Policy extension point implemented by the platform and capabilities.

    Scope — this hook answers *who may act, on which tenant, with which capability
    granted*, plus the risk/confirmation/constraint shape of the operation. It is
    deliberately given no resource identifier and no call arguments.

    Resource-level rules therefore belong to the capability that owns the
    resource, not here: "only the assignee may resolve this ticket", "amounts over
    X need a second approver", "the order must be in state Y". Those checks run
    inside the capability's handler, which can load and lock the row. Trying to
    express them in this hook would silently authorize by name alone.
    """

    async def evaluate(
        self,
        context: PolicyContext,
        capability: str,
        action: str,
        risk: RiskLevel,
    ) -> PolicyDecision:
        """Return a decision without executing the requested operation."""
