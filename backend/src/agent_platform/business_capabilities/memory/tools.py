"""Tool contributions owned by the Memory capability."""

import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from agent_platform.business_capabilities.agent_config.memory import resolve_agent_memory
from agent_platform.core_platform.platform_services.platform_settings.settings import Settings
from agent_platform.extension_contracts import (
    EventEnvelope,
    ToolDefinition,
    ToolExecutionRequest,
    ToolExecutionResult,
)


class MemorySearchInput(BaseModel):
    """Arguments accepted by the customer-memory search tool."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=5, ge=1, le=50)


MEMORY_SEARCH_TOOL = ToolDefinition(
    name="memory_search",
    description="检索当前客户的历史服务记录与过往事项（工单事件、待办承诺）。",
    parameters=MemorySearchInput.model_json_schema(),
    capability="memory",
    risk="read",
    required_permissions=frozenset({"memory.read"}),
)


@dataclass(frozen=True)
class _MemoryToolHandler:
    definition: ToolDefinition
    callback: Callable[[ToolExecutionRequest], Awaitable[ToolExecutionResult]]

    async def execute(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        return await self.callback(request)


class MemoryToolContribution:
    """Expose customer memory search only when the run is eligible."""

    def __init__(self, memory_store, settings: Settings, events=None) -> None:
        self.memory_store = memory_store
        self.settings = settings
        self.events = events

    def visible(self, row) -> bool:
        customer_id = row.get("customer_id")
        agent = (row.get("config", {}).get("agent", {}) or {}).get("config", {}) or {}
        config = resolve_agent_memory(agent, self.settings)
        return bool(customer_id and config.search)

    def handlers(self, row, emit) -> tuple[_MemoryToolHandler, ...]:
        agent = (row.get("config", {}).get("agent", {}) or {}).get("config", {}) or {}
        config = resolve_agent_memory(agent, self.settings)
        return (
            _MemoryToolHandler(
                MEMORY_SEARCH_TOOL,
                lambda request: self._search(request, row, emit, config.search_limit),
            ),
        )

    async def _search(self, request, row, emit, search_limit) -> ToolExecutionResult:
        if not self.visible(row):
            return ToolExecutionResult(status="failed", error_code="memory_search_unavailable")
        params = MemorySearchInput.model_validate(request.arguments)
        customer_id = UUID(str(row["customer_id"]))
        hits = await self.memory_store.search(
            request.context.tenant_id,
            customer_id,
            params.query,
            min(params.limit, search_limit),
        )
        reinforce = row.setdefault("_memory_reinforce", {})
        for hit in hits:
            if hit.get("id"):
                hit_id = str(hit["id"])
                reinforce[hit_id] = reinforce.get(hit_id, 0) + 1
        if emit is not None:
            await emit("memory_search.completed", {"hits": len(hits)})
        if self.events is not None:
            await self.events.publish(
                EventEnvelope(
                    event_type="memory.search.completed",
                    tenant_id=request.context.tenant_id,
                    aggregate_type="customer-memory",
                    aggregate_id=str(customer_id),
                    payload={"query": params.query, "hits": len(hits)},
                    idempotency_key=(
                        f"memory.search.completed:{request.context.run_id}:"
                        f"{hashlib.sha256(params.query.encode()).hexdigest()}"
                    ),
                )
            )
        data = [
            {
                "content": hit["content"],
                "key": hit["key"],
                "updated_at": str(hit["updated_at"]),
                "score": round(hit["score"], 6),
            }
            for hit in hits
        ]
        return ToolExecutionResult(
            status="succeeded",
            data=data,
            message="未找到相关历史记录" if not data else None,
        )
