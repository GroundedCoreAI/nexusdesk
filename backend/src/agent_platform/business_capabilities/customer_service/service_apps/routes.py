"""HTTP routes for versioned service applications."""

from typing import Literal

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from agent_platform.core_platform.platform_services.identity.access import Admin, Reader

from .models import (
    ApplicationSimulationRequest,
    ServiceApplicationConfig,
    ServiceCatalogUpdateRequest,
)

router = APIRouter(prefix="/service-apps", tags=["service-apps"])


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ApplicationCreateInput(Input):
    key: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$", max_length=64)
    config: ServiceApplicationConfig


class ApplicationUpdateInput(Input):
    config: ServiceApplicationConfig
    revision: int = Field(ge=1)


class StatusInput(Input):
    status: Literal["draft", "review", "offline"]
    revision: int = Field(ge=1)


class RevisionInput(Input):
    revision: int = Field(ge=1)


class RollbackInput(Input):
    version: int = Field(ge=1)
    revision: int = Field(ge=1)


def _applications(request: Request):
    return request.app.state.runtime.groups.business.service_apps


@router.get("")
async def list_applications(
    request: Request,
    user: Reader,
    status: Literal["all", "draft", "review", "published", "offline"] = "all",
    q: str = Query(default=""),
):
    return await _applications(request).list(
        user.tenant,
        status=status,
        q=q,
        scope=request.state.business_scope,
    )


@router.get("/overview")
async def application_overview(request: Request, user: Reader):
    return await _applications(request).overview(
        user.tenant,
        scope=request.state.business_scope,
    )


@router.post("", status_code=201)
async def create_application(
    body: ApplicationCreateInput,
    request: Request,
    user: Admin,
):
    return await _applications(request).create(
        user.tenant,
        user.actor,
        body.key,
        body,
        scope=request.state.business_scope,
    )


@router.get("/{key}")
async def get_application(key: str, request: Request, user: Reader):
    return await _applications(request).get(
        user.tenant,
        key,
        scope=request.state.business_scope,
    )


@router.get("/{key}/readiness")
async def application_readiness(key: str, request: Request, user: Reader):
    return await _applications(request).readiness(
        user.tenant,
        key,
        scope=request.state.business_scope,
    )


@router.put("/{key}")
async def update_application(
    key: str,
    body: ApplicationUpdateInput,
    request: Request,
    user: Admin,
):
    return await _applications(request).update(
        user.tenant,
        user.actor,
        key,
        body,
        scope=request.state.business_scope,
    )


@router.put("/{key}/service-catalog")
async def update_service_catalog(
    key: str,
    body: ServiceCatalogUpdateRequest,
    request: Request,
    user: Admin,
):
    return await _applications(request).update_service_catalog(
        user.tenant,
        user.actor,
        key,
        body,
        scope=request.state.business_scope,
    )


@router.post("/{key}/status")
async def set_application_status(
    key: str,
    body: StatusInput,
    request: Request,
    user: Admin,
):
    return await _applications(request).set_status(
        user.tenant,
        user.actor,
        key,
        body.status,
        body.revision,
        scope=request.state.business_scope,
    )


@router.post("/{key}/publish")
async def publish_application(
    key: str,
    body: RevisionInput,
    request: Request,
    user: Admin,
):
    return await _applications(request).publish(
        user.tenant,
        user.actor,
        key,
        body.revision,
        scope=request.state.business_scope,
    )


@router.get("/{key}/versions")
async def application_versions(key: str, request: Request, user: Reader):
    return await _applications(request).versions(
        user.tenant,
        key,
        scope=request.state.business_scope,
    )


@router.post("/{key}/rollback")
async def rollback_application(
    key: str,
    body: RollbackInput,
    request: Request,
    user: Admin,
):
    return await _applications(request).rollback(
        user.tenant,
        user.actor,
        key,
        body.version,
        body.revision,
        scope=request.state.business_scope,
    )


@router.post("/{key}/simulate")
async def simulate_application(
    key: str,
    body: ApplicationSimulationRequest,
    request: Request,
    user: Reader,
):
    return await _applications(request).simulate(
        user.tenant,
        user.actor,
        key,
        body,
        scope=request.state.business_scope,
    )


@router.get("/{key}/traces")
async def application_traces(
    key: str,
    request: Request,
    user: Reader,
    limit: int = Query(default=50, ge=1, le=200),
):
    return await _applications(request).traces(
        user.tenant,
        key,
        limit=limit,
        scope=request.state.business_scope,
    )


__all__ = [
    "ApplicationCreateInput",
    "ApplicationUpdateInput",
    "RevisionInput",
    "RollbackInput",
    "StatusInput",
    "router",
]
