"""Runtime and conversation ports exposed to business capabilities."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from pydantic import Field

from .base import ContractModel
from .events import EventPublisher
from .policy import PolicyDecision
from .tools import (
    OperationLedgerPort,
    ToolContribution,
    ToolExecutionContext,
    ToolReplayPort,
    ToolRisk,
)

RunStatus = Literal["queued", "running", "completed", "failed", "cancelled"]


class RunRequest(ContractModel):
    """A capability-neutral request to start one agent run."""

    tenant_id: str = Field(min_length=1, max_length=200)
    conversation_id: UUID
    input: str = Field(min_length=1, max_length=200_000)
    config: dict[str, object] = Field(default_factory=dict)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=200)


class RunSnapshot(ContractModel):
    """A read-only view of a run returned by the Runtime port."""

    id: UUID
    tenant_id: str = Field(min_length=1, max_length=200)
    conversation_id: UUID
    status: RunStatus
    output: str | None = None
    error_code: str | None = Field(default=None, max_length=200)
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class RunEvent(ContractModel):
    """An ordered event emitted while a run is executing."""

    run_id: UUID
    sequence: int = Field(ge=0)
    type: str = Field(min_length=1, max_length=100)
    data: dict[str, object] = Field(default_factory=dict)
    created_at: datetime


class RuntimeToolPort(Protocol):
    """Tool-registry operations needed while assembling one run."""

    async def credential_headers(
        self,
        tenant_id: str,
        spec: object,
        connection: object | None = None,
    ) -> dict[str, str]:
        """Resolve tool credentials without exposing the credential store."""


class RuntimePolicyPort(Protocol):
    """Policy operations needed by the runtime harness."""

    async def evaluate_tool(
        self,
        context: ToolExecutionContext,
        name: str,
        allowed: list[str],
        risk: ToolRisk = "read",
    ) -> PolicyDecision:
        """Evaluate a tool call using trusted execution context."""

    def check_rounds(self, requested: int, settings: object) -> int:
        """Clamp a requested model-round budget."""

    async def check(self, tenant_id: str, name: str, allowed: list[str]) -> object:
        """Authorize one model-requested tool call."""


class RuntimeRetrievalPort(Protocol):
    """Knowledge retrieval operation exposed to built-in tools."""

    async def for_agent(
        self,
        tenant_id: str,
        query: str,
        knowledge_base_ids: list[UUID],
    ) -> list[dict[str, object]]:
        """Search only the knowledge bases granted to the current run."""


class RuntimeCustomerPort(Protocol):
    """Customer-service operations exposed to built-in tools."""

    async def propose(
        self,
        tenant_id: str,
        conversation_id: UUID,
        run_id: UUID,
        proposal: object,
    ) -> object:
        """Create a pending business proposal."""

    async def lookup(
        self,
        tenant_id: str,
        conversation_id: UUID,
        ticket_id: UUID,
    ) -> object | None:
        """Read a ticket visible to the current conversation."""


class RuntimeConfirmationPort(Protocol):
    """Confirmation lifecycle over the existing pending-action boundary."""

    async def get(self, tenant_id: str, confirmation_id: UUID) -> object | None:
        """Read a tenant-scoped pending confirmation."""

    async def decide(
        self,
        tenant_id: str,
        actor_id: str,
        confirmation_id: UUID,
        approve: bool,
    ) -> object:
        """Approve or reject a pending confirmation."""


class RuntimeMemoryPort(Protocol):
    """Memory search operation exposed to built-in tools."""

    async def search(
        self,
        tenant_id: str,
        customer_id: UUID,
        query: str,
        limit: int,
    ) -> list[dict[str, object]]:
        """Search customer memory within platform limits."""


class MemoryInjectionPort(Protocol):
    """Render the memory context injected into one run.

    The Runtime decides *whether* to inject (its own ``summary_enabled`` switch);
    the memory capability decides *what* the text is. Implementations live with
    the capability, never in ``core_platform``, so no memory vocabulary enters
    the Runtime.

    ``settings`` is passed per call rather than captured at construction: the
    worker owns the effective settings of the run it is executing, and an adapter
    holding a snapshot would silently ignore later changes (including per-run
    overrides, which are the only way to test the gates).
    """

    def render_summary(self, summary: str | None) -> str | None:
        """Render a rolling summary as the body of an injected system message."""

    async def customer_memory(self, row: dict[str, object], settings: object) -> str | None:
        """Render customer profile, preference and event memory for one run."""

    def memory_context(
        self, row: dict[str, object], dropped: object, settings: object
    ) -> dict[str, object] | None:
        """Describe the memory side effects of a completed run."""


@dataclass(frozen=True)
class RuntimeBindings:
    """Small port bundle passed to Runtime-specific adapters.

    Application composition assembles this bundle explicitly; Runtime and
    integrations never receive the aggregate ``PlatformServices`` object.
    """

    engine: object | None = None
    settings: object | None = None
    snapshot: dict[str, object] | None = None
    tools: RuntimeToolPort | None = None
    policy: RuntimePolicyPort | None = None
    retrieval: RuntimeRetrievalPort | None = None
    customer: RuntimeCustomerPort | None = None
    confirmation: RuntimeConfirmationPort | None = None
    memory_store: RuntimeMemoryPort | None = None
    gateway: object | None = None
    ledger: OperationLedgerPort | None = None
    replay: ToolReplayPort | None = None
    events: EventPublisher | None = None
    tool_contributions: tuple[ToolContribution, ...] = ()
    contributions: object | None = None
    extensions: object | None = None


class RunPort(Protocol):
    """The minimal Runtime interface visible to extensions."""

    async def submit(self, request: RunRequest) -> RunSnapshot:
        """Submit a run without exposing the runtime persistence model."""

    async def get(self, tenant_id: str, run_id: UUID) -> RunSnapshot | None:
        """Read a tenant-scoped run snapshot."""

    async def cancel(self, tenant_id: str, run_id: UUID) -> RunSnapshot:
        """Request cancellation and return the resulting snapshot."""


class ConversationPort(Protocol):
    """The minimal conversation interface visible to extensions."""

    async def exists(self, tenant_id: str, conversation_id: UUID) -> bool:
        """Check conversation ownership without exposing SQL rows."""

    async def append_message(
        self,
        tenant_id: str,
        conversation_id: UUID,
        role: Literal["user", "assistant", "human", "system"],
        content: str,
        run_id: UUID | None = None,
    ) -> None:
        """Append a message through the conversation boundary."""
