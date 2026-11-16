"""Admin-only Execution credential lifecycle API; no Secret read endpoint (T-07)."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from agent_platform.core_platform.agent_execution.credentials.repository import (
    CredentialLifecycleError,
)
from agent_platform.core_platform.agent_execution.credentials.vault import (
    ExecutionCredentialKeyError,
)
from agent_platform.core_platform.platform_services.identity.access import Reader, require


def authorize(user: Reader):
    return user.tenant


router = APIRouter(tags=["execution-credentials"], dependencies=[Depends(authorize)])

CredentialType = Literal["token", "api_key", "oauth_client", "mtls_certificate"]


class CredentialCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    credential_type: CredentialType
    secret: SecretStr
    allowed_engines: list[str] = Field(min_length=1, max_length=50)
    allowed_workspaces: list[str] = Field(min_length=1, max_length=50)


class CredentialRotateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    secret: SecretStr


def _repository(request: Request):
    runtime = request.app.state.runtime
    repository = getattr(runtime, "execution_credentials", None)
    if repository is None:
        raise HTTPException(503, "execution_credentials_unavailable")
    return repository


def _stable_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ExecutionCredentialKeyError):
        return HTTPException(503, "execution_credential_key_unavailable")
    if isinstance(exc, CredentialLifecycleError):
        return HTTPException(409, exc.code)
    raise exc


@router.post(
    "/execution-credentials",
    status_code=201,
    dependencies=[Depends(require("admin"))],
)
async def create_credential(
    body: CredentialCreateRequest,
    request: Request,
    tenant: Annotated[str, Depends(authorize)],
):
    repository = _repository(request)
    try:
        record = await repository.create(
            tenant_id=tenant,
            name=body.name,
            credential_type=body.credential_type,
            secret=body.secret.get_secret_value(),
            allowed_engines=tuple(body.allowed_engines),
            allowed_workspaces=tuple(body.allowed_workspaces),
            actor="admin",
        )
    except (ExecutionCredentialKeyError, CredentialLifecycleError) as exc:
        raise _stable_error(exc) from None
    return record.public_metadata()


@router.get("/execution-credentials", dependencies=[Depends(require("admin"))])
async def list_credentials(
    request: Request,
    tenant: Annotated[str, Depends(authorize)],
):
    repository = _repository(request)
    items = [record.public_metadata() for record in await repository.list(tenant_id=tenant)]
    return {"items": items}


@router.get(
    "/execution-credentials/{credential_ref}",
    dependencies=[Depends(require("admin"))],
)
async def get_credential(
    credential_ref: UUID,
    request: Request,
    tenant: Annotated[str, Depends(authorize)],
):
    record = await _repository(request).get(credential_ref=credential_ref, tenant_id=tenant)
    if record is None:
        raise HTTPException(404, "execution_credential_not_found")
    return record.public_metadata()


@router.post(
    "/execution-credentials/{credential_ref}/rotate",
    dependencies=[Depends(require("admin"))],
)
async def rotate_credential(
    credential_ref: UUID,
    body: CredentialRotateRequest,
    request: Request,
    tenant: Annotated[str, Depends(authorize)],
):
    repository = _repository(request)
    try:
        record = await repository.rotate(
            credential_ref=credential_ref,
            tenant_id=tenant,
            secret=body.secret.get_secret_value(),
            actor="admin",
        )
    except (ExecutionCredentialKeyError, CredentialLifecycleError) as exc:
        raise _stable_error(exc) from None
    if record is None:
        raise HTTPException(404, "execution_credential_not_found")
    return record.public_metadata()


@router.post(
    "/execution-credentials/{credential_ref}/revoke",
    dependencies=[Depends(require("admin"))],
)
async def revoke_credential(
    credential_ref: UUID,
    request: Request,
    tenant: Annotated[str, Depends(authorize)],
):
    record = await _repository(request).revoke(
        credential_ref=credential_ref, tenant_id=tenant, actor="admin"
    )
    if record is None:
        raise HTTPException(404, "execution_credential_not_found")
    return record.public_metadata()
