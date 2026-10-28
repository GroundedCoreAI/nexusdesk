"""Minimal ITSM business application registration.

The ITSM domain is intentionally only a runnable application skeleton in
Phase 2. Its purpose is to prove that a second business can share the group
Runtime without importing or copying the customer-service composition root.
"""

from fastapi import APIRouter, FastAPI
from pydantic import BaseModel

from agent_platform.applications.business_registry import BusinessApplication

router = APIRouter(tags=["itsm"])


class HealthResponse(BaseModel):
    status: str
    business_id: str


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", business_id="itsm")


@router.get("/modules")
def modules() -> list[dict[str, str]]:
    return [
        {
            "id": "itsm",
            "name": "IT Service Management",
            "status": "skeleton",
        }
    ]


def register_itsm_routes(app: FastAPI, api_prefix: str, openapi_prefix: str) -> None:
    """Mount the ITSM API under the registered business prefix."""

    del openapi_prefix
    app.include_router(router, prefix=api_prefix)


def itsm_application(route_prefix: str = "/itsm") -> BusinessApplication:
    """Return the minimal ITSM business definition."""

    return BusinessApplication(
        business_id="itsm",
        name="ITSM",
        route_prefix=route_prefix,
        register_routes=register_itsm_routes,
    )


__all__ = ["itsm_application", "register_itsm_routes"]
