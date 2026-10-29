"""Pure approval-domain rules used by the cross-domain extension proof."""

from datetime import UTC, datetime
from typing import ClassVar, Literal
from uuid import UUID, uuid4

from pydantic import Field

from agent_platform.extension_contracts.base import ContractModel

ApprovalState = Literal["draft", "pending", "approved", "rejected", "cancelled"]
ApprovalOperation = Literal["submit", "approve", "reject", "cancel"]


class ApprovalRequest(ContractModel):
    """Domain state independent of persistence and application composition."""

    id: UUID = Field(default_factory=uuid4)
    tenant_id: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4_000)
    requested_by: str = Field(min_length=1, max_length=200)
    status: ApprovalState = "draft"
    revision: int = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ApprovalTransitionError(ValueError):
    """Raised when an approval operation violates a domain invariant."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class ApprovalTransitionEngine:
    """Evaluate approval transitions without reading or writing a database."""

    _allowed: ClassVar[dict[ApprovalState, frozenset[ApprovalOperation]]] = {
        "draft": frozenset({"submit", "cancel"}),
        "pending": frozenset({"approve", "reject", "cancel"}),
        "approved": frozenset(),
        "rejected": frozenset(),
        "cancelled": frozenset(),
    }

    def transition(
        self,
        request: ApprovalRequest,
        operation: ApprovalOperation,
        actor_id: str,
    ) -> ApprovalRequest:
        """Return the next immutable state after validating one operation."""

        if not actor_id:
            raise ApprovalTransitionError("actor_required")
        if operation not in self._allowed[request.status]:
            raise ApprovalTransitionError(f"invalid_transition:{request.status}:{operation}")
        if operation in {"approve", "reject"} and actor_id == request.requested_by:
            raise ApprovalTransitionError("approval_separation_of_duties")

        next_status: ApprovalState = {
            "submit": "pending",
            "approve": "approved",
            "reject": "rejected",
            "cancel": "cancelled",
        }[operation]
        return request.model_copy(
            update={
                "status": next_status,
                "revision": request.revision + 1,
                "updated_at": datetime.now(UTC),
            }
        )
