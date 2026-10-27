"""Application-owned bindings for external capability implementations.

This module is the only supported place for wiring external capability IDs to
Python implementations. It intentionally contains no manifest-driven import
logic: deployments add explicit ``registry.register(...)`` calls here (or
replace this function from their application composition layer).
"""

from agent_platform.business_capabilities.sample_operations.sample_operations import (
    SAMPLE_OPERATIONS_CAPABILITY_ID,
    SampleOperationsLifecycle,
    sample_operations_contributions,
)
from agent_platform.core_platform.extension_platform import CapabilityImplementationRegistry


def register_trusted_external_bindings(
    registry: CapabilityImplementationRegistry,
    platform: object,
) -> None:
    """Register trusted external lifecycle/contribution factories.

    The reference sample is intentionally bound here. A deployment can replace
    this application-owned hook with its own reviewed bindings.
    """
    lifecycle = SampleOperationsLifecycle()
    platform.sample_operations_lifecycle = lifecycle
    registry.register(
        SAMPLE_OPERATIONS_CAPABILITY_ID,
        lambda: lifecycle,
        lambda bound_platform: sample_operations_contributions(bound_platform, lifecycle),
    )


__all__ = ["register_trusted_external_bindings"]
