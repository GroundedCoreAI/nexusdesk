"""Execution request contract."""

from typing import Literal
from uuid import UUID

from pydantic import Field, JsonValue

from .common import ExecutionKey, OpaqueString


class ExecutionRequest(ExecutionKey):
    """Verbatim input and identity for one engine execution."""

    contract_version: Literal["v1"] = "v1"
    tenant_id: str = Field(min_length=1, max_length=200)
    agent_id: UUID
    conversation_id: UUID | None = None
    input: str = Field(min_length=1, max_length=200000)
    config: dict[str, JsonValue] = Field(default_factory=dict)
    effective_capabilities: dict[str, bool] = Field(default_factory=dict)
    engine_session_id: OpaqueString | None = None
    workspace_id: OpaqueString | None = None
    trace_id: OpaqueString | None = None
    execution_workdir: OpaqueString | None = None
    timeout_seconds: int | None = Field(default=None, gt=0)
