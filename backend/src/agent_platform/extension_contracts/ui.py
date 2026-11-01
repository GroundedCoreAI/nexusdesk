"""Serializable UI extension contracts.

These types describe contributions; they do not load React components or make
routing decisions. The application shell remains responsible for resolving a
registered contribution to a local feature implementation.
"""

import re

from pydantic import Field, model_validator

from .base import ContractModel


class UiNavigationItem(ContractModel):
    """One navigation entry contributed by an extension."""

    id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,63}$")
    label_key: str = Field(min_length=1, max_length=200)
    path: str = Field(pattern=r"^/[a-z0-9][a-z0-9/_-]*$")
    icon: str = Field(min_length=1, max_length=100)
    group: str = Field(min_length=1, max_length=100)
    required_permissions: tuple[str, ...] = ()
    required_capability: str | None = Field(default=None, min_length=1, max_length=100)
    order: int = Field(default=0, ge=-10_000, le=10_000)

    @model_validator(mode="after")
    def validate_permissions(self) -> "UiNavigationItem":
        _validate_permission_codes(self.required_permissions)
        return self


class UiRouteContribution(ContractModel):
    """A route declaration resolved by the application shell."""

    id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,63}$")
    path: str = Field(pattern=r"^/[a-z0-9][a-z0-9/_-]*$")
    feature: str = Field(min_length=1, max_length=200)
    required_permissions: tuple[str, ...] = ()
    required_capability: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_permissions(self) -> "UiRouteContribution":
        _validate_permission_codes(self.required_permissions)
        return self


class UiExtensionManifest(ContractModel):
    """UI contributions exposed by one business capability."""

    extension_id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,63}$")
    version: str = Field(pattern=r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
    api_version: str = Field(default="v1", pattern=r"^v\d+$")
    requires_platform: str | None = Field(default=None, min_length=1, max_length=100)
    navigation: tuple[UiNavigationItem, ...] = ()
    routes: tuple[UiRouteContribution, ...] = ()


def _validate_permission_codes(permissions: tuple[str, ...]) -> None:
    invalid = sorted(
        permission
        for permission in permissions
        if not re.fullmatch(r"[a-z][a-z0-9-]*(?:\.[a-z][a-z0-9-]*)+", permission)
    )
    if invalid:
        raise ValueError(
            "UI permissions must use dotted lowercase identifiers: " + ",".join(invalid)
        )
