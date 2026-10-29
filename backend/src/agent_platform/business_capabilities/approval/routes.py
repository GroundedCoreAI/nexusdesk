"""HTTP API for the independent Approval capability."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from agent_platform.core_platform.platform_services.identity.access import Operator, Reader
from agent_platform.core_platform.platform_services.persistence.store import DomainError

router = APIRouter(prefix="/approvals", tags=["approval"])


def _require_enabled(request: Request) -> None:
    if not request.app.state.runtime.extensions.is_enabled("approval"):
        raise DomainError("capability_disabled", 409)


class ApprovalInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4_000)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=200)


class ApprovalDecisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "reject"]
    revision: int = Field(ge=1)


class ApprovalCancelInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: int = Field(ge=1)


@router.get("")
async def list_approvals(
    request: Request,
    user: Reader,
    status: Literal["all", "draft", "pending", "approved", "rejected", "cancelled"] = "all",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
):
    _require_enabled(request)
    return await request.app.state.runtime.groups.business.approval.list(
        user.tenant,
        status,
        page,
        page_size,
        scope=request.state.business_scope,
    )


@router.get("/{approval_id}")
async def approval_detail(approval_id: UUID, request: Request, user: Reader):
    _require_enabled(request)
    return await request.app.state.runtime.groups.business.approval.get(
        user.tenant,
        approval_id,
        scope=request.state.business_scope,
    )


@router.get("/{approval_id}/audit")
async def approval_audit(
    approval_id: UUID,
    request: Request,
    user: Reader,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
):
    _require_enabled(request)
    return await request.app.state.runtime.groups.business.approval.audit(
        user.tenant,
        approval_id,
        limit,
        scope=request.state.business_scope,
    )


@router.post("", status_code=201)
async def create_approval(body: ApprovalInput, request: Request, user: Operator):
    _require_enabled(request)
    return await request.app.state.runtime.groups.business.approval.create(
        user.tenant,
        user.actor,
        body.title,
        body.description,
        body.idempotency_key,
        scope=request.state.business_scope,
    )


@router.post("/{approval_id}/decision")
async def decide_approval(
    approval_id: UUID,
    body: ApprovalDecisionInput,
    request: Request,
    user: Operator,
):
    _require_enabled(request)
    return await request.app.state.runtime.groups.business.approval.decide(
        user.tenant,
        user.actor,
        approval_id,
        body.decision,
        body.revision,
        scope=request.state.business_scope,
    )


@router.post("/{approval_id}/cancel")
async def cancel_approval(
    approval_id: UUID,
    body: ApprovalCancelInput,
    request: Request,
    user: Operator,
):
    _require_enabled(request)
    return await request.app.state.runtime.groups.business.approval.cancel(
        user.tenant,
        user.actor,
        approval_id,
        body.revision,
        scope=request.state.business_scope,
    )
