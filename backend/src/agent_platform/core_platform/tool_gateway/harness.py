"""Policy-aware execution harness for Tool Gateway handlers."""

import asyncio

from agent_platform.extension_contracts import (
    PolicyDecision,
    ToolExecutionRequest,
    ToolExecutionResult,
    ToolHandler,
)


class ToolExecutionHarness:
    """Apply confirmation, idempotency, and timeout constraints consistently."""

    async def execute(
        self,
        handler: ToolHandler,
        request: ToolExecutionRequest,
        decision: PolicyDecision,
    ) -> ToolExecutionResult:
        if not decision.allowed:
            return ToolExecutionResult(
                status="failed",
                error_code="tool_not_allowed",
            )
        if decision.constraint.idempotency_required and not request.idempotency_key:
            return ToolExecutionResult(
                status="failed",
                error_code="idempotency_key_required",
            )
        try:
            async with asyncio.timeout(decision.constraint.timeout_seconds):
                result = await handler.execute(request)
        except TimeoutError:
            return ToolExecutionResult(
                status="failed",
                error_code="tool_timeout",
                retryable=False,
            )
        if decision.confirmation.required and result.status == "succeeded":
            return result.model_copy(update={"status": "requires_confirmation"})
        return result
