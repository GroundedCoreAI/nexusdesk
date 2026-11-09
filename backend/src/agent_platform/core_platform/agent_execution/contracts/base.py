"""Strict base model for agent execution contracts."""

from pydantic import ConfigDict

from agent_platform.extension_contracts.base import ContractModel


class ExecutionContractModel(ContractModel):
    """Immutable execution DTO with strict, non-trimming validation."""

    model_config = ConfigDict(
        strict=True,
        str_strip_whitespace=False,
        frozen=True,
        extra="forbid",
        allow_inf_nan=False,
    )
