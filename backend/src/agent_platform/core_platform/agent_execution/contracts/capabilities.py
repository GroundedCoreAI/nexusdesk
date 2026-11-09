"""Declared engine capabilities contract."""

from typing import Literal

from .base import ExecutionContractModel


class EngineCapabilities(ExecutionContractModel):
    """Independent declared capabilities with no implication rules."""

    contract_version: Literal["v1"] = "v1"
    streaming: bool = False
    persistent_session: bool = False
    session_resume: bool = False
    cancellation: bool = False
    human_approval: bool = False
    interactive_input: bool = False
    tool_calling: bool = False
    file_operations: bool = False
    terminal_execution: bool = False
    native_events: bool = False
    workspace_required: bool = False
