"""Backward-compatible customer-service application entrypoint."""

from fastapi import FastAPI

from agent_platform.applications.application_factory import create_app as _create_app
from agent_platform.applications.business_registry import BusinessRegistry
from agent_platform.core_platform.platform_services.platform_settings.settings import Settings

from .application import customer_service_application


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the historical single-business API without changing its paths."""

    return _create_app(
        settings,
        business_registry=BusinessRegistry((customer_service_application(),)),
    )


app = create_app()

__all__ = ["app", "create_app"]
