"""Stable business-scope context shared by applications and platform ports."""

from pydantic import Field

from .base import ContractModel


class BusinessScope(ContractModel):
    """Trusted request scope resolved by the application boundary.

    ``tenant_id`` remains the existing storage partition. ``business_id`` and
    ``workspace_id`` are introduced as optional context dimensions so current
    single-business data and callers remain compatible while later phases add
    durable scope enforcement.
    """

    tenant_id: str = Field(min_length=1, max_length=200)
    business_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$",
    )
    workspace_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$",
    )


__all__ = ["BusinessScope"]
