"""Base validation settings for cross-layer contracts."""

from pydantic import BaseModel, ConfigDict


class ContractModel(BaseModel):
    """Immutable, strict model used at extension boundaries."""

    model_config = ConfigDict(
        allow_inf_nan=False,
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )
