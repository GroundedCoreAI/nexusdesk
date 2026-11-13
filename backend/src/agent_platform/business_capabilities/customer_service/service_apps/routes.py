"""HTTP routes for the application-v2 service-application runtime."""

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from agent_platform.business_capabilities.customer_service.service_apps.models import (
    ServiceExperienceConfig,
)
from agent_platform.core_platform.platform_services.identity.access import Admin, Operator, Reader

router = APIRouter(prefix="/service-apps", tags=["service-apps"])


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ApplicationCreateInput(Input):
    key: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$", max_length=64)
    config: dict[str, Any] = Field(default_factory=dict)
    name: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=1000)
    agent_id: UUID | None = None
    agent_version: int | None = Field(default=None, ge=1)
    rules: dict[str, Any] | None = None
    channels: list[dict[str, Any]] | None = None


class ApplicationUpdateInput(Input):
    config: dict[str, Any] = Field(default_factory=dict)
    name: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=1000)
    agent_id: UUID | None = None
    agent_version: int | None = Field(default=None, ge=1)
    rules: dict[str, Any] | None = None
    channels: list[dict[str, Any]] | None = None
    revision: int = Field(ge=1)


class StatusInput(Input):
    status: Literal["draft", "review", "offline"]
    revision: int = Field(ge=1)


class RevisionInput(Input):
    revision: int = Field(ge=1)


class ExperienceUpdateInput(Input):
    experience: ServiceExperienceConfig
    revision: int = Field(ge=1)


class RollbackInput(Input):
    version: int = Field(ge=1)
    revision: int = Field(ge=1)


class CopyInput(Input):
    key: str | None = Field(
        default=None,
        pattern=r"^[a-z][a-z0-9_-]{0,63}$",
        max_length=64,
    )
    target_key: str | None = Field(
        default=None,
        pattern=r"^[a-z][a-z0-9_-]{0,63}$",
        max_length=64,
    )
    name: str | None = Field(default=None, max_length=100)


class SkillInput(Input):
    key: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$", max_length=64)
    name: str = Field(min_length=1, max_length=100)
    type: Literal["knowledge", "query", "action", "handoff"]
    description: str = Field(default="", max_length=1000)
    enabled: bool = True
    connection_key: str | None = Field(
        default=None,
        pattern=r"^[a-z][a-z0-9_-]{0,63}$",
        max_length=64,
    )
    connection_id: UUID | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    argument_mapping: dict[str, Any] = Field(default_factory=dict)
    result_mapping: dict[str, Any] = Field(default_factory=dict)
    result_schema: dict[str, Any] = Field(default_factory=dict)
    safety: dict[str, Any] = Field(default_factory=dict)
    write_operation: bool | None = None
    config: dict[str, Any] = Field(default_factory=dict)


class SkillUpdateInput(SkillInput):
    revision: int = Field(ge=1)


class SkillPatchInput(Input):
    enabled: bool
    revision: int = Field(ge=1)


class SkillTestInput(Input):
    application_version: int | None = Field(default=None, ge=1)
    arguments: dict[str, Any] = Field(default_factory=dict)


class ApplicationPreviewInput(Input):
    message: str = Field(min_length=1, max_length=2000)
    skill_key: str | None = Field(default=None, max_length=64)
    version: int | None = Field(default=None, ge=1)
    allow_write: bool = False


class ConnectionInput(Input):
    key: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$", max_length=64)
    name: str = Field(min_length=1, max_length=100)
    executor_kind: Literal["http", "internal", "human_queue"] = "http"
    endpoint: str | None = Field(default=None, max_length=2048)
    method: Literal["GET", "POST"] = "POST"
    public_headers: dict[str, str] = Field(default_factory=dict)
    auth_kind: Literal["none", "bearer", "api_key", "custom"] = "none"
    timeout_seconds: int = Field(default=10, ge=1, le=60)
    max_response_bytes: int = Field(default=16000, ge=128, le=100000)
    config: dict[str, Any] = Field(default_factory=dict)


class ConnectionUpdateInput(Input):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    executor_kind: Literal["http", "internal", "human_queue"] | None = None
    endpoint: str | None = Field(default=None, max_length=2048)
    method: Literal["GET", "POST"] | None = None
    public_headers: dict[str, str] | None = None
    auth_kind: Literal["none", "bearer", "api_key", "custom"] | None = None
    timeout_seconds: int | None = Field(default=None, ge=1, le=60)
    max_response_bytes: int | None = Field(default=None, ge=128, le=100000)
    config: dict[str, Any] | None = None
    revision: int = Field(ge=1)


class CredentialsInput(Input):
    credentials: dict[str, Any] = Field(default_factory=dict, min_length=1)


def _applications(request: Request):
    return request.app.state.runtime.groups.business.service_apps


@router.get("")
async def list_applications(
    request: Request,
    user: Reader,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    status: Literal["all", "draft", "review", "published", "offline"] = "all",
    origin: Literal["all", "user", "example"] = "all",
    q: str = Query(default="", max_length=200),
    archived: bool = Query(default=False),
):
    return await _applications(request).list(
        user.tenant,
        page=page,
        page_size=page_size,
        status=status,
        origin=origin,
        q=q,
        scope=request.state.business_scope,
        archived=archived,
    )


@router.get("/overview")
async def application_overview(
    request: Request,
    user: Reader,
    origin: Literal["all", "user", "example"] = "all",
):
    return await _applications(request).overview(
        user.tenant,
        origin=origin,
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


@router.get("/{key}/experience")
async def get_application_experience(
    key: str,
    request: Request,
    user: Reader,
    version: int | None = Query(default=None, ge=1),
):
    return await _applications(request).get_experience(
        user.tenant,
        key,
        version=version,
        scope=request.state.business_scope,
    )


@router.put("/{key}/experience")
async def update_application_experience(
    key: str,
    body: ExperienceUpdateInput,
    request: Request,
    user: Admin,
):
    return await _applications(request).update_experience(
        user.tenant,
        user.actor,
        key,
        body,
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


@router.post("/{key}/copy", status_code=201)
async def copy_application(
    key: str,
    body: CopyInput,
    request: Request,
    user: Admin,
):
    return await _applications(request).copy(
        user.tenant,
        user.actor,
        key,
        target_key=body.key or body.target_key,
        name=body.name,
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


@router.post("/{key}/archive")
async def archive_application(
    key: str,
    body: RevisionInput,
    request: Request,
    user: Admin,
):
    return await _applications(request).archive(
        user.tenant,
        user.actor,
        key,
        body.revision,
        scope=request.state.business_scope,
    )


@router.post("/{key}/restore")
async def restore_application(
    key: str,
    request: Request,
    user: Admin,
    body: RevisionInput | None = None,
):
    return await _applications(request).restore(
        user.tenant,
        user.actor,
        key,
        revision=body.revision if body else None,
        scope=request.state.business_scope,
    )


@router.delete("/{key}")
async def purge_application(key: str, request: Request, user: Admin):
    """Permanently delete an archived application. Not reversible."""

    return await _applications(request).purge(
        user.tenant,
        user.actor,
        key,
        scope=request.state.business_scope,
    )


@router.get("/{key}/versions")
async def application_versions(
    key: str,
    request: Request,
    user: Reader,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
):
    return await _applications(request).versions(
        user.tenant,
        key,
        page=page,
        page_size=page_size,
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


@router.get("/{key}/traces")
async def application_traces(
    key: str,
    request: Request,
    user: Reader,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=200),
    limit: int | None = Query(default=None, ge=1, le=200),
):
    return await _applications(request).traces(
        user.tenant,
        key,
        page=page,
        page_size=page_size,
        limit=limit,
        scope=request.state.business_scope,
    )


@router.get("/{key}/conversations")
async def application_conversations(
    key: str,
    request: Request,
    user: Reader,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    q: str = Query(default="", max_length=200),
    channel_id: Annotated[UUID | None, Query()] = None,
    status: Literal[
        "all",
        "completed",
        "failed",
        "queued",
        "running",
        "cancelled",
        "bot",
        "waiting",
        "human",
        "closed",
    ] = "all",
):
    return await _applications(request).list_conversations(
        user.tenant,
        key,
        page=page,
        page_size=page_size,
        q=q,
        channel_id=channel_id,
        status=status,
        scope=request.state.business_scope,
    )


@router.get("/{key}/conversations/{conversation_id}")
async def application_conversation(
    key: str,
    conversation_id: UUID,
    request: Request,
    user: Reader,
):
    return await _applications(request).get_conversation(
        user.tenant,
        key,
        conversation_id,
        scope=request.state.business_scope,
    )


@router.get("/{key}/skills")
async def list_skills(
    key: str,
    request: Request,
    user: Reader,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    q: str = Query(default="", max_length=200),
):
    return await _applications(request).list_skills(
        user.tenant,
        key,
        page=page,
        page_size=page_size,
        q=q,
        scope=request.state.business_scope,
    )


@router.post("/{key}/skills", status_code=201)
async def create_skill(
    key: str,
    body: SkillInput,
    request: Request,
    user: Admin,
):
    return await _applications(request).create_skill(
        user.tenant,
        user.actor,
        key,
        body,
        scope=request.state.business_scope,
    )


@router.put("/{key}/skills/{skill_key}")
async def update_skill(
    key: str,
    skill_key: str,
    body: SkillUpdateInput,
    request: Request,
    user: Admin,
):
    return await _applications(request).update_skill(
        user.tenant,
        user.actor,
        key,
        skill_key,
        body,
        scope=request.state.business_scope,
    )


@router.patch("/{key}/skills/{skill_key}")
async def patch_skill(
    key: str,
    skill_key: str,
    body: SkillPatchInput,
    request: Request,
    user: Admin,
):
    return await _applications(request).update_skill(
        user.tenant,
        user.actor,
        key,
        skill_key,
        body,
        enabled_only=True,
        scope=request.state.business_scope,
    )


@router.delete("/{key}/skills/{skill_key}")
async def delete_skill(
    key: str,
    skill_key: str,
    request: Request,
    user: Admin,
    revision: int = Query(ge=1),
):
    return await _applications(request).delete_skill(
        user.tenant,
        user.actor,
        key,
        skill_key,
        revision=revision,
        scope=request.state.business_scope,
    )


@router.post("/{key}/skills/{skill_key}/test")
async def test_skill(
    key: str,
    skill_key: str,
    request: Request,
    user: Admin,
    body: SkillTestInput | None = None,
):
    return await _applications(request).test_skill(
        user.tenant,
        user.actor,
        key,
        skill_key,
        body,
        scope=request.state.business_scope,
    )


@router.post("/{key}/preview")
async def preview_application(
    key: str,
    body: ApplicationPreviewInput,
    request: Request,
    user: Operator,
):
    return await _applications(request).preview(
        user.tenant,
        user.actor,
        key,
        body,
        scope=request.state.business_scope,
    )


@router.get("/{key}/connections")
async def list_connections(
    key: str,
    request: Request,
    user: Reader,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    q: str = Query(default="", max_length=200),
):
    return await _applications(request).list_connections(
        user.tenant,
        key,
        page=page,
        page_size=page_size,
        q=q,
        scope=request.state.business_scope,
    )


@router.post("/{key}/connections", status_code=201)
async def create_connection(
    key: str,
    body: ConnectionInput,
    request: Request,
    user: Admin,
):
    return await _applications(request).create_connection(
        user.tenant,
        user.actor,
        key,
        body,
        scope=request.state.business_scope,
    )


@router.put("/{key}/connections/{connection_key}")
async def update_connection(
    key: str,
    connection_key: str,
    body: ConnectionUpdateInput,
    request: Request,
    user: Admin,
):
    return await _applications(request).update_connection(
        user.tenant,
        user.actor,
        key,
        connection_key,
        body,
        scope=request.state.business_scope,
    )


@router.put("/{key}/connections/{connection_key}/credentials")
async def save_connection_credentials(
    key: str,
    connection_key: str,
    body: CredentialsInput,
    request: Request,
    user: Admin,
):
    return await _applications(request).save_credentials(
        user.tenant,
        user.actor,
        key,
        connection_key,
        body,
        scope=request.state.business_scope,
    )


@router.post("/{key}/connections/{connection_key}/test")
async def test_connection(
    key: str,
    connection_key: str,
    request: Request,
    user: Admin,
):
    return await _applications(request).test_connection(
        user.tenant,
        user.actor,
        key,
        connection_key,
        scope=request.state.business_scope,
    )


@router.delete("/{key}/connections/{connection_key}")
async def delete_connection(
    key: str,
    connection_key: str,
    request: Request,
    user: Admin,
    revision: int = Query(ge=1),
):
    return await _applications(request).delete_connection(
        user.tenant,
        user.actor,
        key,
        connection_key,
        revision=revision,
        scope=request.state.business_scope,
    )


__all__ = [
    "ApplicationCreateInput",
    "ApplicationPreviewInput",
    "ApplicationUpdateInput",
    "ConnectionInput",
    "ConnectionUpdateInput",
    "CopyInput",
    "CredentialsInput",
    "ExperienceUpdateInput",
    "RevisionInput",
    "RollbackInput",
    "SkillInput",
    "SkillPatchInput",
    "SkillTestInput",
    "SkillUpdateInput",
    "StatusInput",
    "router",
]
