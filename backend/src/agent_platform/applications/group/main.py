"""Uvicorn entrypoint for the unified group application."""

from fastapi import FastAPI

from agent_platform.core_platform.platform_services.platform_settings.settings import Settings

from .application import create_group_app


def create_app(settings: Settings | None = None) -> FastAPI:
    return create_group_app(settings)


app = create_app()

__all__ = ["app", "create_app"]
