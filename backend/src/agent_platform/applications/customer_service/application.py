"""Customer-service business registration for unified platform entrypoints."""

from fastapi import FastAPI

from agent_platform.applications.business_registry import BusinessApplication
from agent_platform.business_capabilities.approval.routes import router as approval_router
from agent_platform.business_capabilities.knowledge.routes import router as knowledge_router
from agent_platform.business_capabilities.memory.routes import router as memory_router
from agent_platform.business_capabilities.open_platform.routes import management as open_management
from agent_platform.business_capabilities.open_platform.routes import public as open_public

from .platform_routes import ingress
from .platform_routes import router as platform_router
from .routes import router
from .runtime_routes import router as runtime_router
from .trusted_extensions import register_trusted_external_bindings


def register_customer_service_routes(
    app: FastAPI,
    api_prefix: str,
    openapi_prefix: str,
) -> None:
    """Mount the customer-service API under the supplied business prefixes."""

    app.include_router(router, prefix=api_prefix)
    app.include_router(platform_router, prefix=api_prefix)
    app.include_router(knowledge_router, prefix=api_prefix)
    app.include_router(runtime_router, prefix=api_prefix)
    app.include_router(memory_router, prefix=api_prefix)
    app.include_router(approval_router, prefix=api_prefix)
    app.include_router(ingress, prefix=api_prefix)
    app.include_router(open_management, prefix=api_prefix)
    app.include_router(open_public, prefix=openapi_prefix)

    from agent_platform.business_capabilities.open_platform.enterprise_routes import (
        management as enterprise_management,
    )
    from agent_platform.business_capabilities.open_platform.enterprise_routes import (
        public as sso_public,
    )
    from agent_platform.business_capabilities.open_platform.enterprise_routes import (
        tokens as chat_tokens,
    )

    app.include_router(enterprise_management, prefix=api_prefix)
    app.include_router(sso_public, prefix=api_prefix)
    app.include_router(chat_tokens, prefix=openapi_prefix)


def customer_service_application(route_prefix: str = "") -> BusinessApplication:
    """Return the customer-service definition for a legacy or group entrypoint."""

    return BusinessApplication(
        business_id="customer-service",
        name="Customer Service",
        route_prefix=route_prefix,
        register_routes=register_customer_service_routes,
        trusted_extension_binder=register_trusted_external_bindings,
    )


__all__ = [
    "customer_service_application",
    "register_customer_service_routes",
]
