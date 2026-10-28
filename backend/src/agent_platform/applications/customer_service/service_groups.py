"""Backward-compatible imports for shared service groups."""

from agent_platform.applications.platform_runtime.service_groups import (
    ApplicationOnlyServices,
    BusinessCapabilityServices,
    PlatformServiceGroups,
    RuntimePlatformServices,
    ToolPolicyServices,
    build_runtime_bindings,
    build_service_groups,
)

__all__ = [
    "ApplicationOnlyServices",
    "BusinessCapabilityServices",
    "PlatformServiceGroups",
    "RuntimePlatformServices",
    "ToolPolicyServices",
    "build_runtime_bindings",
    "build_service_groups",
]
