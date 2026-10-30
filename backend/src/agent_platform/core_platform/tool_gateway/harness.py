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

    # Risks whose handler performs the real business effect. A confirmation must
    # therefore gate the call, not annotate its result: relabelling after the
    # fact would report "awaiting confirmation" for work already done.
    # ``proposal`` is different by contract — its handler only records a pending
    # intent, so running it before the decision is the proposal itself.
    _EFFECTFUL_RISKS = frozenset({"write", "irreversible"})

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
        if decision.confirmation.required and decision.risk in self._EFFECTFUL_RISKS:
            return ToolExecutionResult(status="requires_confirmation")
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
