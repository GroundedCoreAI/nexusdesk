"""Tool contributions owned by the Customer Service capability."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from agent_platform.core_platform.platform_services.persistence.store import DomainError
from agent_platform.extension_contracts import (
    BusinessScope,
    ToolDefinition,
    ToolExecutionRequest,
    ToolExecutionResult,
)

from .service import TicketProposal


class TicketLookupInput(BaseModel):
    """Arguments accepted by the conversation-scoped ticket lookup tool."""

    model_config = ConfigDict(extra="forbid")

    ticket_id: UUID


CUSTOMER_SERVICE_TOOL_DEFINITIONS: dict[str, ToolDefinition] = {
    "ticket_lookup": ToolDefinition(
        name="ticket_lookup",
        description="查询当前会话内已创建工单的实际状态，不执行办理。",
        parameters=TicketLookupInput.model_json_schema(),
        capability="customer-service",
        risk="read",
        required_permissions=frozenset({"ticket.read"}),
    ),
    "propose_ticket": ToolDefinition(
        name="propose_ticket",
        description="拟定工单，返回待确认操作。需要人工确认后才能创建，不能声称已创建。",
        parameters=TicketProposal.model_json_schema(),
        capability="customer-service",
        risk="proposal",
        required_permissions=frozenset({"ticket.manage"}),
    ),
}


@dataclass(frozen=True)
class _CustomerServiceToolHandler:
    definition: ToolDefinition
    callback: Callable[[ToolExecutionRequest], Awaitable[ToolExecutionResult]]

    async def execute(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        return await self.callback(request)


class CustomerServiceToolContribution:
    """Bind customer-service tools without exposing them to Runtime."""

    def __init__(self, service) -> None:
        self.service = service

    def handlers(self, row, emit) -> tuple[_CustomerServiceToolHandler, ...]:
        return (
            _CustomerServiceToolHandler(
                CUSTOMER_SERVICE_TOOL_DEFINITIONS["ticket_lookup"],
                lambda request: self._lookup(request, row),
            ),
            _CustomerServiceToolHandler(
                CUSTOMER_SERVICE_TOOL_DEFINITIONS["propose_ticket"],
                lambda request: self._propose(request, row),
            ),
        )

    async def _lookup(self, request: ToolExecutionRequest, row) -> ToolExecutionResult:
        params = TicketLookupInput.model_validate(request.arguments)
        conversation_id = request.context.conversation_id
        if conversation_id is None:
            raise DomainError("conversation_context_required", 400)
        result = await self.service.lookup(
            request.context.tenant_id,
            conversation_id,
            params.ticket_id,
            scope=BusinessScope(
                tenant_id=request.context.tenant_id,
                business_id=request.context.business_id,
                workspace_id=request.context.workspace_id,
            ),
        )
        return ToolExecutionResult(status="succeeded", data=result)

    async def _propose(self, request: ToolExecutionRequest, row) -> ToolExecutionResult:
        proposal = TicketProposal.model_validate(request.arguments)
        conversation_id = request.context.conversation_id
        run_id = request.context.run_id
        if conversation_id is None or run_id is None:
            raise DomainError("runtime_context_required", 400)
        result = await self.service.propose(
            request.context.tenant_id,
            conversation_id,
            run_id,
            proposal,
            scope=BusinessScope(
                tenant_id=request.context.tenant_id,
                business_id=request.context.business_id,
                workspace_id=request.context.workspace_id,
            ),
        )
        confirmation_ref = UUID(str(result["action_id"])) if result.get("action_id") else None
        return ToolExecutionResult(
            status="succeeded",
            data=result,
            confirmation_ref=confirmation_ref,
        )
