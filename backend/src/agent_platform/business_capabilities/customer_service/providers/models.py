"""Contracts for the customer-service provider registry."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

PROVIDER_KEY_PATTERN = r"^[a-z][a-z0-9_.:-]{0,99}$"


class ProviderKind(StrEnum):
    OBJECT = "object"
    TOOL = "tool"
    HUMAN_QUEUE = "human_queue"


class ProviderModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ProviderInput(ProviderModel):
    key: str = Field(pattern=PROVIDER_KEY_PATTERN, max_length=100)
    kind: ProviderKind
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=1000)
    enabled: bool = False
    config: dict[str, Any] = Field(default_factory=dict)


class ProviderUpdateInput(ProviderInput):
    revision: int = Field(ge=1)


class ProviderRecord(ProviderInput):
    id: UUID
    revision: int
    source: str = "manual"
    source_ref: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ProviderRequirement(ProviderModel):
    key: str = Field(pattern=PROVIDER_KEY_PATTERN, max_length=100)
    kind: ProviderKind
    name: str = Field(min_length=1, max_length=100)
    source: str = Field(default="industry_pack", max_length=100)
    source_ref: str | None = Field(default=None, max_length=200)
    enabled: bool = False


class ProviderPage(ProviderModel):
    items: list[ProviderRecord]
    total: int


def provider_identity(kind: ProviderKind | str, key: str) -> str:
    """Return the stable identity used by readiness snapshots."""

    value = kind.value if isinstance(kind, ProviderKind) else str(kind)
    return f"{value}:{key}"


__all__ = [
    "PROVIDER_KEY_PATTERN",
    "ProviderInput",
    "ProviderKind",
    "ProviderPage",
    "ProviderRecord",
    "ProviderRequirement",
    "ProviderUpdateInput",
    "provider_identity",
]
