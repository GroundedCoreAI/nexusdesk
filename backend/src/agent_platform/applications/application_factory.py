"""FastAPI application assembly shared by all business entrypoints."""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any

from asyncpg import PostgresError
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from agent_platform.applications.business_registry import BusinessRegistry
from agent_platform.applications.platform_runtime.runtime_composition import runtime_services
from agent_platform.business_capabilities.memory.bootstrap import embedded_memory_worker
from agent_platform.core_platform.agent_runtime.schemas import BusyError, CapacityError
from agent_platform.core_platform.platform_services.access_control.routes import (
    router as access_control_router,
)
from agent_platform.core_platform.platform_services.identity.local_routes import (
    router as local_auth_router,
)
from agent_platform.core_platform.platform_services.model_gateway.management_routes import (
    router as gateway_management_router,
)
from agent_platform.core_platform.platform_services.model_gateway.routes import (
    router as model_router,
)
from agent_platform.core_platform.platform_services.persistence.audit_context import (
    AuditContextMiddleware,
)
from agent_platform.core_platform.platform_services.persistence.store import DomainError
from agent_platform.core_platform.platform_services.platform_settings.settings import Settings
from agent_platform.core_platform.platform_services.tenant_isolation.context import (
    bind_scope,
    reset_scope,
)
from agent_platform.core_platform.platform_services.tenant_isolation.service import ScopeError
from agent_platform.core_platform.tool_gateway.routes import router as tool_workspace_router
from agent_platform.extension_contracts import BusinessScope

logger = logging.getLogger(__name__)


def _private_identity_path(path: str) -> bool:
    return (
        path.startswith(
            (
                "/api/v1/auth/local/",
                "/api/v1/sso/",
                "/api/v1/open-platform/identity/",
                "/api/v1/members/",
                "/api/v1/sessions",
                "/api/v1/roles",
                "/api/v1/permissions",
                "/openapi/v1/chat/",
            )
        )
        or "/auth/local/" in path
        or "/open-platform/identity/" in path
    )


def create_app(
    settings: Settings | None = None,
    *,
    business_registry: BusinessRegistry,
    title: str | None = None,
) -> FastAPI:
    """Create an application using one shared Runtime and registered businesses."""

    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with runtime_services(
            settings,
            trusted_extension_binder=business_registry.bind_extensions,
        ) as services:
            app.state.runtime = services
            app.state.business_registry = business_registry
            app.state.scope_catalog = services.scope
            try:
                await services.scope.ensure_registered(
                    settings.tenant_id,
                    business_registry.catalog(),
                )
            except (SQLAlchemyError, PostgresError, OSError, TimeoutError) as exc:
                logger.warning(
                    "Tenant business scope hydration unavailable during startup (%s)",
                    type(exc).__name__,
                )
            application = services.groups.application
            business = services.groups.business
            task = (
                asyncio.create_task(services.worker.serve()) if settings.embedded_worker else None
            )
            memory_worker = embedded_memory_worker(services.groups, settings)
            memory_task = asyncio.create_task(memory_worker.serve()) if memory_worker else None
            webhook_task = asyncio.create_task(application.open_platform.webhooks.serve())
            channel_task = (
                asyncio.create_task(business.channels.serve_deliveries())
                if settings.channel_worker_embedded
                else None
            )
            channel_inbound_task = (
                asyncio.create_task(business.channels.serve_inbound())
                if settings.channel_worker_embedded
                else None
            )
            try:
                yield
            finally:
                application.open_platform.webhooks.stopping.set()
                webhook_task.cancel()
                await asyncio.gather(webhook_task, return_exceptions=True)
                if channel_task is not None:
                    channel_task.cancel()
                    await asyncio.gather(channel_task, return_exceptions=True)
                if channel_inbound_task is not None:
                    channel_inbound_task.cancel()
                    await asyncio.gather(channel_inbound_task, return_exceptions=True)
                await business.channels.stop()
                services.worker.stop()
                if memory_worker:
                    memory_worker.stop()
                if memory_task:
                    await memory_task
                if task:
                    await task

    app = FastAPI(title=title or settings.app_name, version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.business_registry = business_registry
    app.add_middleware(AuditContextMiddleware)

    @app.middleware("http")
    async def private_identity_responses(request: Request, call_next: Any):
        try:
            scope = BusinessScope(
                tenant_id=settings.tenant_id,
                business_id=business_registry.resolve_business_id(request.url.path),
                workspace_id=request.headers.get("X-Workspace-ID"),
            )
        except ValidationError:
            return JSONResponse(status_code=422, content={"detail": "invalid_business_scope"})
        catalog = getattr(request.app.state, "scope_catalog", None)
        if catalog is not None and scope.business_id is not None:
            try:
                scope = await catalog.validate(scope)
            except ScopeError as exc:
                return JSONResponse(status_code=exc.status, content={"detail": exc.code})
            except (SQLAlchemyError, PostgresError, OSError, TimeoutError):
                return JSONResponse(status_code=503, content={"detail": "scope_unavailable"})
        request.state.business_scope = scope
        token = bind_scope(scope)
        try:
            response = await call_next(request)
        finally:
            reset_scope(token)
        if _private_identity_path(request.url.path):
            response.headers["Cache-Control"] = "no-store"
            response.headers["Pragma"] = "no-cache"
            response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.get("/api/v1/businesses", tags=["platform"])
    async def list_businesses() -> list[dict[str, str]]:
        return business_registry.catalog()

    # These routers are platform-wide. Business-owned routes are mounted by
    # BusinessRegistry below, which lets the group entrypoint add a second
    # business without copying Runtime lifecycle code.
    app.include_router(local_auth_router, prefix="/api/v1")
    app.include_router(tool_workspace_router, prefix="/api/v1")
    app.include_router(access_control_router, prefix="/api/v1")
    app.include_router(gateway_management_router, prefix="/api/v1")
    app.include_router(model_router, prefix="/api/v1")
    business_registry.register_routes(app)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={
                "detail": [
                    {key: error[key] for key in ("type", "loc", "msg")} for error in exc.errors()
                ]
            },
        )

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, exc: SQLAlchemyError):
        return JSONResponse(status_code=503, content={"detail": "database_unavailable"})

    app.add_exception_handler(PostgresError, database_error)
    app.add_exception_handler(OSError, database_error)
    app.add_exception_handler(TimeoutError, database_error)

    @app.exception_handler(DomainError)
    async def domain_error(request: Request, exc: DomainError):
        return JSONResponse(status_code=exc.status, content={"detail": exc.code})

    @app.exception_handler(BusyError)
    async def busy_error(request: Request, exc: BusyError):
        return JSONResponse(status_code=409, content={"detail": "conversation_busy"})

    @app.exception_handler(CapacityError)
    async def capacity_error(request: Request, exc: CapacityError):
        return JSONResponse(
            status_code=429,
            content={"detail": "runtime_capacity_exceeded"},
            headers={"Retry-After": "2"},
        )

    return app


__all__ = ["create_app"]
