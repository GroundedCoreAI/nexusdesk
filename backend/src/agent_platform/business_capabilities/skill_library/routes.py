"""HTTP surface for the global Skill library."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from agent_platform.core_platform.platform_services.identity.access import (
    Principal,
    require_permission,
)
from agent_platform.core_platform.platform_services.persistence.store import DomainError

from .models import (
    SkillCreateRequest,
    SkillDraftUpdate,
    SkillDuplicateRequest,
    SkillPublishRequest,
    SkillRollbackRequest,
    SkillTestRequest,
)

router = APIRouter(prefix="/skills", tags=["skills"])
templates_router = APIRouter(prefix="/skill-templates", tags=["skills"])

SkillRead = Annotated[Principal, Depends(require_permission("skill.read"))]
SkillManage = Annotated[Principal, Depends(require_permission("skill.manage"))]
SkillTest = Annotated[Principal, Depends(require_permission("skill.test"))]
SkillPublish = Annotated[Principal, Depends(require_permission("skill.publish"))]


def _service(request: Request):
    return request.app.state.runtime.groups.business.skill_library


@router.get("")
async def list_skills(
    request: Request,
    user: SkillRead,
    q: str = Query(default="", max_length=200),
    category: str = Query(default="all", max_length=20),
    status: str = Query(default="all", max_length=20),
    risk: str = Query(default="all", max_length=20),
    weight: str = Query(default="all", max_length=20),
    sort: str = Query(default="latest", max_length=20),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    return await _service(request).list(
        user.tenant,
        scope=request.state.business_scope,
        q=q,
        category=category,
        status=status,
        risk=risk,
        weight=weight,
        sort=sort,
        page=page,
        page_size=page_size,
    )


@router.get("/overview")
async def skill_overview(
    request: Request,
    user: SkillRead,
    popular_limit: int = Query(default=5, ge=1, le=20),
):
    """Headline catalogue numbers and the popular rail.

    Declared before ``/{skill_key}`` so the literal path wins the match.
    """

    return await _service(request).overview(
        user.tenant,
        scope=request.state.business_scope,
        popular_limit=popular_limit,
    )


@router.post("", status_code=201)
async def create_skill(
    body: SkillCreateRequest,
    request: Request,
    user: SkillManage,
):
    return await _service(request).create(
        user.tenant,
        user.actor,
        body,
        scope=request.state.business_scope,
    )


@router.post("/import", status_code=201)
async def import_skill(
    request: Request,
    user: SkillManage,
    filename: str = Query(default="package.zip", min_length=1, max_length=255),
):
    """Create a Skill from a zip. Declared before ``/{skill_key}`` so the literal
    path is never parsed as a key."""

    limit = _service(request).settings.skill_package_bytes
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > limit:
            raise DomainError("skill_package_too_large", 413)
    return await _service(request).import_package(
        user.tenant,
        user.actor,
        filename,
        bytes(content),
        scope=request.state.business_scope,
    )


@router.get("/{skill_key}")
async def get_skill(skill_key: str, request: Request, user: SkillRead):
    return await _service(request).get(
        user.tenant,
        skill_key,
        scope=request.state.business_scope,
    )


@router.put("/{skill_key}/draft")
async def save_draft(
    skill_key: str,
    body: SkillDraftUpdate,
    request: Request,
    user: SkillManage,
):
    return await _service(request).save_draft(
        user.tenant,
        user.actor,
        skill_key,
        body,
        scope=request.state.business_scope,
    )


@router.post("/{skill_key}/duplicate", status_code=201)
async def duplicate_skill(
    skill_key: str,
    body: SkillDuplicateRequest,
    request: Request,
    user: SkillManage,
):
    return await _service(request).duplicate(
        user.tenant,
        user.actor,
        skill_key,
        body,
        scope=request.state.business_scope,
    )


@router.get("/{skill_key}/test-runs")
async def list_test_runs(
    skill_key: str,
    request: Request,
    user: SkillRead,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    return await _service(request).test_runs(
        user.tenant,
        skill_key,
        scope=request.state.business_scope,
        page=page,
        page_size=page_size,
    )


@router.post("/{skill_key}/test-runs", status_code=201)
async def run_test(
    skill_key: str,
    body: SkillTestRequest,
    request: Request,
    user: SkillTest,
):
    return await _service(request).run_test(
        user.tenant,
        user.actor,
        skill_key,
        body,
        scope=request.state.business_scope,
    )


@router.get("/{skill_key}/test-runs/{run_id}")
async def get_test_run(
    skill_key: str,
    run_id: UUID,
    request: Request,
    user: SkillRead,
):
    return await _service(request).test_run(
        user.tenant,
        skill_key,
        run_id,
        scope=request.state.business_scope,
    )


@router.get("/{skill_key}/readiness")
async def get_readiness(skill_key: str, request: Request, user: SkillRead):
    return await _service(request).readiness(
        user.tenant,
        skill_key,
        scope=request.state.business_scope,
        can_publish=user.can("skill.publish"),
    )


@router.get("/{skill_key}/versions")
async def list_versions(
    skill_key: str,
    request: Request,
    user: SkillRead,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    return await _service(request).versions(
        user.tenant,
        skill_key,
        scope=request.state.business_scope,
        page=page,
        page_size=page_size,
    )


@router.get("/{skill_key}/versions/{version}")
async def get_version(
    skill_key: str,
    version: int,
    request: Request,
    user: SkillRead,
):
    return await _service(request).version(
        user.tenant,
        skill_key,
        version,
        scope=request.state.business_scope,
    )


@router.post("/{skill_key}/publish")
async def publish_skill(
    skill_key: str,
    body: SkillPublishRequest,
    request: Request,
    user: SkillPublish,
):
    return await _service(request).publish(
        user.tenant,
        user.actor,
        skill_key,
        body,
        scope=request.state.business_scope,
    )


@router.post("/{skill_key}/rollback")
async def rollback_skill(
    skill_key: str,
    body: SkillRollbackRequest,
    request: Request,
    user: SkillPublish,
):
    return await _service(request).rollback(
        user.tenant,
        user.actor,
        skill_key,
        body,
        scope=request.state.business_scope,
    )


@router.get("/{skill_key}/package")
async def get_package(skill_key: str, request: Request, user: SkillRead):
    return await _service(request).package(
        user.tenant,
        skill_key,
        scope=request.state.business_scope,
    )


@router.post("/{skill_key}/package")
async def upload_package(
    skill_key: str,
    request: Request,
    user: SkillManage,
    filename: str = Query(default="package.zip", min_length=1, max_length=255),
):
    # The archive is read as a raw body rather than multipart: the Skill package
    # endpoint takes exactly one artefact, and streaming lets the size ceiling
    # fire before the bytes are buffered.
    limit = _service(request).settings.skill_package_bytes
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > limit:
            raise DomainError("skill_package_too_large", 413)
    return await _service(request).attach_package(
        user.tenant,
        user.actor,
        skill_key,
        filename,
        bytes(content),
        scope=request.state.business_scope,
    )


@router.delete("/{skill_key}/package")
async def delete_package(skill_key: str, request: Request, user: SkillManage):
    return await _service(request).detach_package(
        user.tenant,
        user.actor,
        skill_key,
        scope=request.state.business_scope,
    )


@templates_router.get("")
async def list_templates(request: Request, user: SkillRead):
    return _service(request).templates()


__all__ = ["router", "templates_router"]
