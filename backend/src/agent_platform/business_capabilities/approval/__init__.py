"""Approval capability: a second domain proving the extension boundary."""

from .capability import ApprovalCapability
from .domain import (
    ApprovalOperation,
    ApprovalRequest,
    ApprovalState,
    ApprovalTransitionEngine,
    ApprovalTransitionError,
)
from .service import ApprovalService
from .tools import APPROVAL_TOOL_DEFINITIONS

__all__ = [
    "APPROVAL_TOOL_DEFINITIONS",
    "ApprovalCapability",
    "ApprovalOperation",
    "ApprovalRequest",
    "ApprovalService",
    "ApprovalState",
    "ApprovalTransitionEngine",
    "ApprovalTransitionError",
]
