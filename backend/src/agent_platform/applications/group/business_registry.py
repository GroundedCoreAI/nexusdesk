"""Default business registry for the group entrypoint."""

from agent_platform.applications.business_registry import BusinessRegistry
from agent_platform.applications.customer_service.application import customer_service_application
from agent_platform.applications.itsm.application import itsm_application


def default_business_registry() -> BusinessRegistry:
    """Build the current group registry.

    The second business can be added here later without changing the shared
    Runtime or the group application lifecycle.
    """

    return BusinessRegistry(
        (
            customer_service_application("/customer-service"),
            itsm_application("/itsm"),
        )
    )


__all__ = ["default_business_registry"]
