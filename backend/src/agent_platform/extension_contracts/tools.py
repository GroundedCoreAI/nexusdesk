"""Tool contracts shared by Runtime, Tool Gateway, and capabilities."""

import re
from collections.abc import Awaitable, Callable
from typing import Literal, Protocol
from uuid import UUID

from pydantic import Field, model_validator

from .base import ContractModel

ToolRisk = Literal["read", "proposal", "write", "irreversible"]


class ToolDefinition(ContractModel):
    """Model-facing description of one executable tool."""

    name: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_]{0,63}$")
    description: str = Field(min_length=1, max_length=1_000)
    parameters: dict[str, object]
    capability: str = Field(min_length=1, max_length=100)
    risk: ToolRisk = "read"
    version: str = Field(default="1", min_length=1, max_length=50)
    idempotent: bool = False
    required_permissions: frozenset[str] = Field(default_factory=frozenset)

    @model_validator(mode="after")
    def validate_permissions(self) -> "ToolDefinition":
        invalid = sorted(
            permission
            for permission in self.required_permissions
            if not re.fullmatch(
                r"[a-z][a-z0-9-]*(?:\.[a-z][a-z0-9-]*)+",
                permission,
            )
        )
        if invalid:
            raise ValueError(
                "tool permissions must use dotted lowercase identifiers: " + ",".join(invalid)
            )
        return self

    def model_schema(self) -> dict[str, object]:
        """Return the model-facing function schema."""

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolExecutionContext(ContractModel):
    """Trusted context attached by the platform, never supplied by the model."""

    tenant_id: str = Field(min_length=1, max_length=200)
    run_id: UUID | None = None
    conversation_id: UUID | None = None
    actor_id: str | None = Field(default=None, min_length=1, max_length=200)
    source: Literal["runtime", "application", "worker", "system"]
    business_id: str | None = Field(default=None, min_length=1, max_length=100)
    workspace_id: str | None = Field(default=None, min_length=1, max_length=100)


class ToolExecutionRequest(ContractModel):
    """Validated request passed from the gateway to a tool handler."""

    definition: ToolDefinition
    context: ToolExecutionContext
    arguments: dict[str, object] = Field(default_factory=dict)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=200)


class ToolExecutionResult(ContractModel):
    """Stable result shape returned by every tool handler."""

    status: Literal["succeeded", "failed", "requires_confirmation", "cancelled"]
    data: object | None = None
    message: str | None = Field(default=None, max_length=2_000)
    metadata: dict[str, object] = Field(default_factory=dict)
    error_code: str | None = Field(default=None, max_length=200)
    operation_id: UUID | None = None
    confirmation_ref: UUID | None = None
    retryable: bool = False


class OperationRecord(ContractModel):
    """Stable audit record for one tool operation.

    The legacy ``tool_calls`` table remains the storage adapter for now.  The
    contract prevents Runtime and capabilities from depending on that table's
    column layout.
    """

    id: UUID
    tenant_id: str = Field(min_length=1, max_length=200)
    run_id: UUID
    tool_name: str = Field(min_length=1, max_length=100)
    tool_version: str | None = Field(default=None, max_length=50)
    adapter_type: Literal["builtin", "http"] = "builtin"
    effect: ToolRisk = "read"
    status: Literal["succeeded", "failed", "requires_confirmation", "cancelled"]
    error_code: str | None = Field(default=None, max_length=200)
    duration_ms: int = Field(ge=0)


class OperationLedgerPort(Protocol):
    """Persistence boundary for idempotent tool-operation records."""

    async def get(self, operation_id: UUID) -> "OperationRecord | None":
        """Read a previously recorded operation by its stable identifier."""

    async def record(self, operation: OperationRecord) -> None:
        """Persist one normalized operation record."""


class ToolReplayPort(Protocol):
    """Short-lived replay boundary for completed idempotent tool results."""

    async def get(self, idempotency_key: str) -> dict[str, object] | None:
        """Return a previously completed result, if available."""

    async def put(self, idempotency_key: str, result: dict[str, object]) -> None:
        """Store a completed result for deterministic replay."""


class ToolHandler(Protocol):
    """Executable implementation contributed by a capability."""

    @property
    def definition(self) -> ToolDefinition:
        """Return the immutable tool definition."""

    async def execute(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        """Execute one validated request."""


class ToolContribution(Protocol):
    """Factory for capability-owned handlers bound to one Runtime run."""

    def handlers(
        self,
        row: dict[str, object],
        emit: Callable[[str, dict[str, object]], Awaitable[object]] | None,
    ) -> tuple[ToolHandler, ...]:
        """Return handlers without exposing the capability to Runtime."""


class ToolRegistryPort(Protocol):
    """Registry interface consumed by Runtime and Policy."""

    def definitions(self) -> tuple[ToolDefinition, ...]:
        """Return all registered definitions visible to the caller."""

    def resolve(self, name: str) -> ToolHandler | None:
        """Resolve a handler without knowing its implementation module."""
