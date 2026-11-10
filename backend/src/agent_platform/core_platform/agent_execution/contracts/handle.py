"""Running execution handle contract."""

from typing import Literal

from pydantic import Field, JsonValue

from .common import ExecutionKey, OpaqueString


class ExecutionHandle(ExecutionKey):
    """Provider-owned handle; terminal state is represented only by results."""

    contract_version: Literal["v1"] = "v1"
    provider_session_id: OpaqueString | None = None
    process_id: int | None = Field(default=None, gt=0)
    status: Literal["running"] = "running"
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
