"""HTTP routes for provider descriptors."""

from typing import Annotated

from fastapi import APIRouter, Query, Request

from agent_platform.core_platform.platform_services.identity.access import Admin, Reader

from .models import ProviderInput, ProviderKind, ProviderUpdateInput

router = APIRouter(prefix="/service-providers", tags=["service-providers"])


def _providers(request: Request):
    return request.app.state.runtime.groups.business.providers


@router.get("")
async def list_providers(
    request: Request,
    user: Reader,
    kind: Annotated[ProviderKind | None, Query()] = None,
    q: Annotated[str, Query(max_length=200)] = "",
):
    return await _providers(request).list(
        user.tenant,
        kind=kind,
        q=q,
        scope=request.state.business_scope,
    )


@router.get("/{kind}/{key}")
async def get_provider(
    kind: ProviderKind,
    key: str,
    request: Request,
    user: Reader,
):
    return await _providers(request).get(
        user.tenant,
        kind,
        key,
        scope=request.state.business_scope,
    )


@router.post("", status_code=201)
async def create_provider(body: ProviderInput, request: Request, user: Admin):
    return await _providers(request).create(
        user.tenant,
        user.actor,
        body,
        scope=request.state.business_scope,
    )


@router.put("/{kind}/{key}")
async def update_provider(
    kind: ProviderKind,
    key: str,
    body: ProviderUpdateInput,
    request: Request,
    user: Admin,
):
    return await _providers(request).update(
        user.tenant,
        user.actor,
        kind,
        key,
        body,
        scope=request.state.business_scope,
    )


__all__ = ["router"]
