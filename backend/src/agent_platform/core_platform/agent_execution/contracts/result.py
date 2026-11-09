"""Terminal execution result contract."""

from typing import Literal, Self

from pydantic import Field, JsonValue, model_validator

from .common import ExecutionKey
from .errors import ExecutionError, ExecutionErrorCategory


class ExecutionResult(ExecutionKey):
    """Terminal execution output with strict status-specific combinations."""

    contract_version: Literal["v1"] = "v1"
    status: Literal["completed", "failed", "cancelled"]
    output: str | None = None
    artifacts: list[dict[str, JsonValue]] = Field(default_factory=list)
    usage: dict[str, JsonValue] = Field(default_factory=dict)
    engine_metadata: dict[str, JsonValue] = Field(default_factory=dict)
    error: ExecutionError | None = None

    @model_validator(mode="after")
    def validate_terminal_combination(self) -> Self:
        if self.status == "completed" and self.error is not None:
            raise ValueError("Completed results must not contain an error.")
        if self.status == "failed":
            if self.output is not None:
                raise ValueError("Failed results must not contain output.")
            if self.error is None:
                raise ValueError("Failed results require an error.")
            if self.error.category is ExecutionErrorCategory.CANCELLED:
                raise ValueError("Failed results must not contain a cancelled error.")
        if self.status == "cancelled" and (self.output is not None or self.error is not None):
            raise ValueError("Cancelled results must not contain output or an error.")
        return self
