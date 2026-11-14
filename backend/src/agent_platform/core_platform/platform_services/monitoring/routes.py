"""Notification centre HTTP surface.

The checklist endpoint only reads persisted snapshots; probes are the scanner's
job. Manual runs are rate-limited because a forced scan hits every dependency.
"""

import time
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from agent_platform.core_platform.platform_services.identity.access import Admin, Reader

router = APIRouter(tags=["notifications"])

MANUAL_SCAN_COOLDOWN_SECONDS = 60
_last_manual_scan = 0.0


class SuppressInput(BaseModel):
    minutes: int = Field(default=60, ge=1, le=10080)


def monitoring(request: Request):
    return request.app.state.runtime.groups.application.monitoring


@router.get("/notifications/checklist")
async def checklist(request: Request, user: Reader):
    return await monitoring(request).checklist(user.tenant)


@router.get("/notifications/unread-count")
async def unread_count(request: Request, user: Reader):
    # Badge semantics: "how many checks need attention", not "how many alert
    # rows are unopened". Same source and predicate as the checklist counters,
    # so the bell number always matches the panel and never drops to zero just
    # because the operator read the feed.
    return {"count": await monitoring(request).unread_count(user.tenant)}


@router.get("/notifications")
async def list_notifications(
    request: Request,
    user: Reader,
    status: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    unread: bool | None = Query(default=None),
    limit: int = Query(default=30, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    return await monitoring(request).notifications(
        user.tenant,
        status=status,
        severity=severity,
        unread=unread,
        limit=limit,
        offset=offset,
    )


@router.post("/notifications/read-all")
async def read_all(request: Request, user: Reader):
    return await monitoring(request).mark_all_read(user.tenant)


@router.post("/notifications/{notification_id}/read")
async def read_one(notification_id: UUID, request: Request, user: Reader):
    try:
        return await monitoring(request).mark_read(user.tenant, notification_id)
    except LookupError:
        raise HTTPException(404, "notification_not_found") from None


@router.post("/notifications/{notification_id}/acknowledge")
async def acknowledge(notification_id: UUID, request: Request, user: Admin):
    try:
        return await monitoring(request).acknowledge(user.tenant, notification_id, user.actor)
    except LookupError:
        raise HTTPException(404, "notification_not_found") from None


@router.post("/notifications/{notification_id}/suppress")
async def suppress(notification_id: UUID, body: SuppressInput, request: Request, user: Admin):
    try:
        return await monitoring(request).suppress(
            user.tenant, notification_id, body.minutes, user.actor
        )
    except LookupError:
        raise HTTPException(404, "notification_not_found") from None


@router.post("/notifications/checks/run")
async def run_checks(request: Request, user: Admin):
    global _last_manual_scan
    now = time.monotonic()
    if now - _last_manual_scan < MANUAL_SCAN_COOLDOWN_SECONDS:
        raise HTTPException(429, "scan_cooldown")
    _last_manual_scan = now
    service = monitoring(request)
    return await service.scan(force=True, tenant=user.tenant)
