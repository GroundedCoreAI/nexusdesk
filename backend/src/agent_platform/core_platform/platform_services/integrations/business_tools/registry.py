"""Business tool handlers registered behind the Tool Gateway contract."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from agent_platform.core_platform.tool_gateway.service import HttpTool, ToolGateway
from agent_platform.extension_contracts import (
    ToolDefinition,
    ToolExecutionRequest,
    ToolExecutionResult,
)


@dataclass(frozen=True)
class BuiltinToolHandler:
    """A capability-owned handler bound to one immutable tool definition."""

    definition: ToolDefinition
    callback: Callable[[ToolExecutionRequest], Awaitable[ToolExecutionResult]]

    async def execute(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        return await self.callback(request)


class BuiltinToolRegistry:
    """Resolve business handlers without dispatching on tool names at runtime."""

    def __init__(self, handlers: tuple[BuiltinToolHandler, ...]):
        self._handlers = {handler.definition.name: handler for handler in handlers}
        if len(self._handlers) != len(handlers):
            raise ValueError("Duplicate builtin tool names")

    def resolve(self, name: str) -> BuiltinToolHandler | None:
        return self._handlers.get(name)

    def definitions(self, allowed: list[str]) -> tuple[ToolDefinition, ...]:
        return tuple(
            handler.definition for name, handler in self._handlers.items() if name in allowed
        )


class HttpToolHandler:
    """Adapt one configured HTTP tool to the common ToolHandler contract."""

    def __init__(self, gateway: ToolGateway, spec: HttpTool):
        self.gateway = gateway
        self.definition = ToolDefinition(
            name=spec.name,
            description=spec.description,
            parameters=spec.parameters,
            capability="external-tool",
            risk=spec.effect,
            idempotent=spec.method == "GET",
        )

    async def execute(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        result = await self.gateway.execute(request.definition.name, request.arguments)
        if result.get("ok"):
            return ToolExecutionResult(
                status="succeeded",
                data=result.get("data"),
                metadata={key: value for key, value in result.items() if key not in {"ok", "data"}},
            )
        return ToolExecutionResult(
            status="failed",
            error_code=result.get("error", "tool_failed"),
            metadata={key: value for key, value in result.items() if key not in {"ok", "error"}},
        )


class ToolHandlerRegistry:
    """Composite registry for capability-owned and configured HTTP handlers."""

    def __init__(self, handlers: tuple[BuiltinToolHandler | HttpToolHandler, ...]):
        self._handlers = {handler.definition.name: handler for handler in handlers}
        if len(self._handlers) != len(handlers):
            raise ValueError("Duplicate tool names")

    def resolve(self, name: str):
        return self._handlers.get(name)

    def definitions(self, allowed: list[str]) -> tuple[ToolDefinition, ...]:
        return tuple(
            handler.definition for name, handler in self._handlers.items() if name in allowed
        )
