"""Agent-facing tool definitions owned by the Approval capability."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from pydantic import ConfigDict, Field

from agent_platform.core_platform.platform_services.persistence.store import DomainError
from agent_platform.extension_contracts import (
    ToolDefinition,
    ToolExecutionRequest,
    ToolExecutionResult,
)
from agent_platform.extension_contracts.base import ContractModel


class ApprovalLookupInput(ContractModel):
    """Arguments for reading one approval request."""

    model_config = ConfigDict(extra="forbid")

    request_id: UUID


class SubmitApprovalInput(ContractModel):
    """Arguments for creating an approval proposal."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4_000)


class DecideApprovalInput(ContractModel):
    """Arguments for recording an approval decision."""

    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    decision: Literal["approve", "reject"]


APPROVAL_TOOL_DEFINITIONS: dict[str, ToolDefinition] = {
    "approval_lookup": ToolDefinition(
        name="approval_lookup",
        description="查询审批申请状态，不执行审批决策。",
        parameters=ApprovalLookupInput.model_json_schema(),
        capability="approval",
        risk="read",
        required_permissions=frozenset({"approval.read"}),
    ),
    "submit_approval": ToolDefinition(
        name="submit_approval",
        description="提交审批申请，返回待处理的审批提案。",
        parameters=SubmitApprovalInput.model_json_schema(),
        capability="approval",
        risk="proposal",
        required_permissions=frozenset({"approval.manage"}),
    ),
    "decide_approval": ToolDefinition(
        name="decide_approval",
        description="批准或驳回一项待处理审批申请。",
        parameters=DecideApprovalInput.model_json_schema(),
        capability="approval",
        risk="write",
        idempotent=True,
        required_permissions=frozenset({"approval.manage"}),
    ),
}


@dataclass(frozen=True)
class ApprovalToolHandler:
    """Minimal handler adapter kept inside the Approval capability."""

    definition: ToolDefinition
    callback: Callable[[ToolExecutionRequest], Awaitable[ToolExecutionResult]]

    async def execute(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        return await self.callback(request)


class ApprovalToolContribution:
    """Bind Approval handlers to a run without adding Approval branches to Runtime."""

    def __init__(self, service) -> None:
        self.service = service

    def handlers(self, row: dict[str, object], emit) -> tuple[ApprovalToolHandler, ...]:
        return (
            ApprovalToolHandler(
                definition=APPROVAL_TOOL_DEFINITIONS["approval_lookup"],
                callback=self._lookup,
            ),
            ApprovalToolHandler(
                definition=APPROVAL_TOOL_DEFINITIONS["submit_approval"],
                callback=self._submit,
            ),
            ApprovalToolHandler(
                definition=APPROVAL_TOOL_DEFINITIONS["decide_approval"],
                callback=self._decide,
            ),
        )

    @staticmethod
    def _actor(request: ToolExecutionRequest) -> str:
        return request.context.actor_id or f"runtime:{request.context.run_id}"

    @staticmethod
    def _public(row: dict[str, object]) -> dict[str, object]:
        return {
            key: value
            for key, value in row.items()
            if key not in {"request_fingerprint", "idempotency_key"}
        }

    async def _lookup(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        params = ApprovalLookupInput.model_validate(request.arguments)
        row = await self.service.get(request.context.tenant_id, params.request_id)
        return ToolExecutionResult(status="succeeded", data=self._public(row))

    async def _submit(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        params = SubmitApprovalInput.model_validate(request.arguments)
        row = await self.service.create(
            request.context.tenant_id,
            self._actor(request),
            params.title,
            params.description,
            request.idempotency_key,
        )
        return ToolExecutionResult(status="succeeded", data=self._public(row))

    async def _decide(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        params = DecideApprovalInput.model_validate(request.arguments)
        actor = request.context.actor_id
        if not actor:
            raise DomainError("approval_actor_required", 403)
        row = await self.service.decide(
            request.context.tenant_id,
            actor,
            params.request_id,
            params.decision,
            params.revision,
        )
        return ToolExecutionResult(status="succeeded", data=self._public(row))
