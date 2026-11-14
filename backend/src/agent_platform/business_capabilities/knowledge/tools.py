"""Tool contributions owned by the Knowledge capability."""

import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from agent_platform.extension_contracts import (
    EventEnvelope,
    ToolDefinition,
    ToolExecutionRequest,
    ToolExecutionResult,
)


class KnowledgeSearchInput(BaseModel):
    """Arguments accepted by the Agent-facing knowledge search tool."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=500)


def trace_sources(results) -> list[dict]:
    """Shape retrieval hits for a trace payload.

    Shared by the real tool and the application preview so both traces read the
    same. The excerpt keeps the whole chunk — chunk size is already bounded by
    the chunking policy, and a window that stops at the repeated table header
    shows a reviewer nothing. ``score`` is the RRF fusion score (1/(60+rank)
    summed over channels), not a cosine similarity, so the per-channel scores
    travel with it: without them a reviewer reads 0.03 as "3% relevant" when it
    means "ranked first in both channels".
    """

    return [
        {
            "document_id": str(result["document_id"]),
            "title": result["title"],
            "version": result["version"],
            "chunk_id": str(result["chunk_id"]),
            "score": result.get("score"),
            "channels": result.get("channels"),
            "scores": result.get("scores"),
            "rerank_score": result.get("rerank_score"),
            "excerpt": (result.get("excerpt") or "").strip(),
        }
        for result in results
    ]


KNOWLEDGE_SEARCH_TOOL = ToolDefinition(
    name="knowledge_search",
    description="搜索授权知识库，返回标题、版本、片段和来源。回答请引用标题及版本。",
    parameters=KnowledgeSearchInput.model_json_schema(),
    capability="knowledge",
    risk="read",
    required_permissions=frozenset({"knowledge.read"}),
)


@dataclass(frozen=True)
class _KnowledgeToolHandler:
    definition: ToolDefinition
    callback: Callable[[ToolExecutionRequest], Awaitable[ToolExecutionResult]]

    async def execute(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        return await self.callback(request)


class KnowledgeToolContribution:
    """Bind knowledge retrieval to the shared Tool Gateway contract."""

    def __init__(self, retrieval, events=None) -> None:
        self.retrieval = retrieval
        self.events = events

    def handlers(self, row, emit) -> tuple[_KnowledgeToolHandler, ...]:
        return (
            _KnowledgeToolHandler(
                KNOWLEDGE_SEARCH_TOOL,
                lambda request: self._search(request, row, emit),
            ),
        )

    async def _search(self, request, row, emit) -> ToolExecutionResult:
        params = KnowledgeSearchInput.model_validate(request.arguments)
        config = (row.get("config", {}).get("agent", {}) or {}).get("config", {}) or {}
        knowledge_base_ids = [UUID(str(item)) for item in config.get("knowledge_base_ids", ())]
        results = await self.retrieval.for_agent(
            request.context.tenant_id,
            params.query,
            knowledge_base_ids,
        )
        results = json.loads(json.dumps(results, default=str))
        # The trace needs to answer "what did the model ask, what came back". Title and
        # ids alone only prove a call happened; the excerpt and score are the evidence.
        sources = trace_sources(results)
        if emit is not None:
            await emit("knowledge.retrieved", {"query": params.query, "sources": sources})
        # The bus is keyed by run: without one (an application preview runs with
        # no persisted run) the envelope has no aggregate to attach to and every
        # query would collide on "None". The local emit above still feeds the
        # preview's diagnosis, so nothing is lost.
        if self.events is not None and request.context.run_id is not None:
            await self.events.publish(
                EventEnvelope(
                    event_type="knowledge.retrieved",
                    tenant_id=request.context.tenant_id,
                    aggregate_type="knowledge-search",
                    aggregate_id=str(request.context.run_id),
                    payload={"query": params.query, "sources": sources},
                    idempotency_key=(
                        f"knowledge.retrieved:{request.context.run_id}:"
                        f"{hashlib.sha256(params.query.encode()).hexdigest()}"
                    ),
                )
            )
        return ToolExecutionResult(status="succeeded", data=results)
