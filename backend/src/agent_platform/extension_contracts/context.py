"""Stable business-scope context shared by applications and platform ports."""

from typing import Final

from pydantic import Field

from .base import ContractModel

# The single business/workspace fallback pair a Run uses when its row carries
# neither dimension. It is shared deliberately: the Worker binds one scope for
# the persisted history lookup and the same composition derives deployment-level
# warm targets from it, so a drift between the two would warm entries no Run ever
# reads (08 R-46).
DEFAULT_BUSINESS_ID: Final[str] = "customer-service"
DEFAULT_WORKSPACE_ID: Final[str] = "default"


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
