"""HTTP routes for the versioned service-scenario platform."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from agent_platform.core_platform.platform_services.identity.access import Admin, Reader

from .models import ScenarioConfig, SimulationRequest

router = APIRouter(prefix="/service-scenarios", tags=["service-scenarios"])
agent_router = APIRouter(tags=["service-scenarios"])


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ScenarioCreateInput(Input):
    key: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$", max_length=64)
    config: ScenarioConfig


class ScenarioUpdateInput(Input):
    config: ScenarioConfig
    revision: int = Field(ge=1)


class StatusInput(Input):
    status: Literal["draft", "review", "offline"]
    revision: int = Field(ge=1)


class RevisionInput(Input):
    revision: int = Field(ge=1)


class RollbackInput(Input):
    version: int = Field(ge=1)
    revision: int = Field(ge=1)


def _scenarios(request: Request):
    return request.app.state.runtime.groups.business.scenarios


@router.get("")
async def list_scenarios(
    request: Request,
    user: Reader,
    status: Literal["all", "draft", "review", "published", "offline"] = "all",
    q: str = Query(default=""),
):
    return await _scenarios(request).list(
        user.tenant,
        status=status,
        q=q,
        scope=request.state.business_scope,
    )


@router.get("/overview")
async def scenario_overview(request: Request, user: Reader):
    return await _scenarios(request).overview(
        user.tenant,
        scope=request.state.business_scope,
    )


@router.post("", status_code=201)
async def create_scenario(body: ScenarioCreateInput, request: Request, user: Admin):
    return await _scenarios(request).create(
        user.tenant,
        user.actor,
        body,
        scope=request.state.business_scope,
    )


@router.post("/simulate")
async def simulate_scenario(
    body: SimulationRequest,
    request: Request,
    user: Reader,
    scenario_key: str | None = Query(default=None, max_length=64),
):
    return await _scenarios(request).simulate(
        user.tenant,
        user.actor,
        scenario_key,
        body,
        scope=request.state.business_scope,
        persist=True,
    )


@router.get("/{key}")
async def get_scenario(key: str, request: Request, user: Reader):
    return await _scenarios(request).get(
        user.tenant,
        key,
        scope=request.state.business_scope,
    )


@router.put("/{key}")
async def update_scenario(
    key: str,
    body: ScenarioUpdateInput,
    request: Request,
    user: Admin,
):
    return await _scenarios(request).update(
        user.tenant,
        user.actor,
        key,
        body,
        scope=request.state.business_scope,
    )


@router.post("/{key}/status")
async def set_scenario_status(
    key: str,
    body: StatusInput,
    request: Request,
    user: Admin,
):
    return await _scenarios(request).set_status(
        user.tenant,
        user.actor,
        key,
        body.status,
        body.revision,
        scope=request.state.business_scope,
    )


@router.post("/{key}/publish")
async def publish_scenario(
    key: str,
    body: RevisionInput,
    request: Request,
    user: Admin,
):
    return await _scenarios(request).publish(
        user.tenant,
        user.actor,
        key,
        body.revision,
        scope=request.state.business_scope,
    )


@router.get("/{key}/versions")
async def scenario_versions(key: str, request: Request, user: Reader):
    return await _scenarios(request).versions(
        user.tenant,
        key,
        scope=request.state.business_scope,
    )


@router.post("/{key}/rollback")
async def rollback_scenario(
    key: str,
    body: RollbackInput,
    request: Request,
    user: Admin,
):
    return await _scenarios(request).rollback(
        user.tenant,
        user.actor,
        key,
        body.version,
        body.revision,
        scope=request.state.business_scope,
    )


@router.post("/{key}/simulate")
async def simulate_named_scenario(
    key: str,
    body: SimulationRequest,
    request: Request,
    user: Reader,
):
    return await _scenarios(request).simulate(
        user.tenant,
        user.actor,
        key,
        body,
        scope=request.state.business_scope,
        persist=True,
    )


@router.get("/{key}/traces")
async def scenario_traces(
    key: str,
    request: Request,
    user: Reader,
    limit: int = Query(default=50, ge=1, le=200),
):
    return await _scenarios(request).traces(
        user.tenant,
        key,
        limit=limit,
        scope=request.state.business_scope,
    )


@agent_router.get("/agents/{aid}/service-scenarios")
async def agent_service_scenarios(aid: UUID, request: Request, user: Reader):
    return await _scenarios(request).agent_references(
        user.tenant,
        aid,
        scope=request.state.business_scope,
    )


__all__ = [
    "RevisionInput",
    "RollbackInput",
    "ScenarioCreateInput",
    "ScenarioUpdateInput",
    "StatusInput",
    "agent_router",
    "router",
]
