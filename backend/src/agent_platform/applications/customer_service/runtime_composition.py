"""Customer-service composition compatibility layer.

The shared platform runtime is assembled in
``agent_platform.applications.platform_runtime``. This module keeps the
customer-service entrypoint responsible for its reviewed external bindings
while preserving the historical import path for scripts and deployments.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from agent_platform.applications.platform_runtime.runtime_composition import (
    RuntimeServices,
)
from agent_platform.applications.platform_runtime.runtime_composition import (
    runtime_services as _runtime_services,
)
from agent_platform.core_platform.platform_services.platform_settings.settings import Settings

from .trusted_extensions import register_trusted_external_bindings


@asynccontextmanager
async def runtime_services(settings: Settings) -> AsyncIterator[RuntimeServices]:
    """Build shared services with customer-service trusted extensions."""

    async with _runtime_services(
        settings,
        trusted_extension_binder=register_trusted_external_bindings,
    ) as services:
        yield services


__all__ = ["RuntimeServices", "runtime_services"]
