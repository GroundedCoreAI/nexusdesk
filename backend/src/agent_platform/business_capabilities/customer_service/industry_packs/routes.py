"""HTTP routes for industry-pack installation and upgrades."""

from uuid import UUID

from fastapi import APIRouter, Request

from agent_platform.core_platform.platform_services.identity.access import Admin, Reader

from .runtime_models import (
    IndustryPackInstallInput,
    IndustryPackUpgradeInput,
    IndustryPackUpgradePreviewRequest,
)

router = APIRouter(prefix="/industry-packs", tags=["industry-packs"])


def _packs(request: Request):
    return request.app.state.runtime.groups.business.industry_packs


@router.get("")
async def list_industry_packs(request: Request, user: Reader):
    return await _packs(request).list_packs(
        user.tenant,
        scope=request.state.business_scope,
    )


@router.get("/installations")
async def list_industry_pack_installations(request: Request, user: Reader):
    return await _packs(request).list_installations(
        user.tenant,
        scope=request.state.business_scope,
    )


@router.post("/installations/{installation_id}/upgrade-preview")
async def preview_industry_pack_upgrade(
    installation_id: UUID,
    body: IndustryPackUpgradePreviewRequest,
    request: Request,
    user: Admin,
):
    return await _packs(request).preview_upgrade(
        user.tenant,
        user.actor,
        installation_id,
        body,
        scope=request.state.business_scope,
    )


@router.post("/installations/{installation_id}/upgrade")
async def apply_industry_pack_upgrade(
    installation_id: UUID,
    body: IndustryPackUpgradeInput,
    request: Request,
    user: Admin,
):
    return await _packs(request).apply_upgrade(
        user.tenant,
        user.actor,
        installation_id,
        body,
        scope=request.state.business_scope,
    )


@router.get("/{pack_key}")
async def get_industry_pack(pack_key: str, request: Request, user: Reader):
    return await _packs(request).get_pack(
        user.tenant,
        pack_key,
        scope=request.state.business_scope,
    )


@router.post("/{pack_key}/install", status_code=201)
async def install_industry_pack(
    pack_key: str,
    body: IndustryPackInstallInput,
    request: Request,
    user: Admin,
):
    return await _packs(request).install(
        user.tenant,
        user.actor,
        pack_key,
        body,
        scope=request.state.business_scope,
    )


__all__ = ["router"]
