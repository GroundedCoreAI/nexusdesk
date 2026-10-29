"""Group-level application factory."""

from fastapi import FastAPI

from agent_platform.applications.application_factory import create_app
from agent_platform.applications.business_registry import BusinessRegistry
from agent_platform.core_platform.platform_services.platform_settings.settings import Settings

from .business_registry import default_business_registry


def create_group_app(
    settings: Settings | None = None,
    *,
    business_registry: BusinessRegistry | None = None,
) -> FastAPI:
    return create_app(
        settings,
        business_registry=business_registry or default_business_registry(),
        title="NexusDesk Group Platform",
    )


__all__ = ["create_group_app"]
