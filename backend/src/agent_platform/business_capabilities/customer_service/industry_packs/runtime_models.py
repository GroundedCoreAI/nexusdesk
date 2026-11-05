"""Runtime contracts for installing and upgrading industry packs."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from ..scenarios.models import ScenarioModel

PACK_KEY_PATTERN = r"^[a-z][a-z0-9_-]{0,63}$"
SEMVER_PATTERN = r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"


class IndustryPackSummary(ScenarioModel):
    pack_key: str
    name: str
    description: str
    pack_version: str
    maturity: Literal["alpha", "beta", "ga"]
    digest: str
    object_count: int
    scenario_count: int
    application_key: str | None = None
    installation_count: int = 0


class IndustryPackCatalog(ScenarioModel):
    items: list[IndustryPackSummary]
    total: int


class IndustryPackDetail(IndustryPackSummary):
    manifest: dict[str, Any]
    compiled_application: dict[str, Any] | None = None
    installations: list[dict[str, Any]] = Field(default_factory=list)


class IndustryPackInstallInput(ScenarioModel):
    pack_version: str | None = Field(default=None, pattern=SEMVER_PATTERN, max_length=64)
    application_key: str | None = Field(
        default=None,
        pattern=PACK_KEY_PATTERN,
        max_length=64,
    )
    install_scenarios: bool = True


class IndustryPackInstallation(ScenarioModel):
    id: UUID
    pack_key: str
    pack_version: str
    pack_digest: str
    maturity: Literal["alpha", "beta", "ga"]
    application_key: str
    status: Literal["installed", "upgrading", "conflicted", "blocked"]
    scenario_template_versions: dict[str, str] = Field(default_factory=dict)
    scenario_template_digests: dict[str, str] = Field(default_factory=dict)
    installed_scenarios: dict[str, str] = Field(default_factory=dict)
    revision: int
    installed_by: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class IndustryPackInstallationPage(ScenarioModel):
    items: list[IndustryPackInstallation]
    total: int


class IndustryPackInstallResult(ScenarioModel):
    created: bool
    installation: IndustryPackInstallation


class MergeConflictView(ScenarioModel):
    path: str
    base: Any = None
    local: Any = None
    incoming: Any = None


class ScenarioUpgradePreview(ScenarioModel):
    template_key: str
    scenario_key: str
    status: Literal["clean", "conflicted", "blocked"]
    conflicts: list[MergeConflictView] = Field(default_factory=list)
    auto_merged_fields: list[str] = Field(default_factory=list)
    kept_local_fields: list[str] = Field(default_factory=list)
    incoming_fields: list[str] = Field(default_factory=list)
    current_revision: int | None = None
    merged_config: dict[str, Any] | None = None
    detail: str = ""


class IndustryPackUpgradePreviewRequest(ScenarioModel):
    target_version: str | None = Field(
        default=None,
        pattern=SEMVER_PATTERN,
        max_length=64,
    )


class IndustryPackUpgradePreview(ScenarioModel):
    id: UUID
    installation_id: UUID
    from_version: str
    to_version: str
    status: Literal["clean", "conflicted", "blocked"]
    scenarios: list[ScenarioUpgradePreview] = Field(default_factory=list)
    application: dict[str, Any] | None = None
    application_conflicts: list[MergeConflictView] = Field(default_factory=list)
    created_at: datetime | None = None


class IndustryPackUpgradeInput(IndustryPackUpgradePreviewRequest):
    preview_id: UUID


class IndustryPackUpgradeResult(ScenarioModel):
    applied: bool
    installation: IndustryPackInstallation
    preview_id: UUID
    upgraded_scenarios: list[str] = Field(default_factory=list)
    application_key: str


__all__ = [
    "IndustryPackCatalog",
    "IndustryPackDetail",
    "IndustryPackInstallInput",
    "IndustryPackInstallResult",
    "IndustryPackInstallation",
    "IndustryPackInstallationPage",
    "IndustryPackSummary",
    "IndustryPackUpgradeInput",
    "IndustryPackUpgradePreview",
    "IndustryPackUpgradePreviewRequest",
    "IndustryPackUpgradeResult",
    "MergeConflictView",
    "ScenarioUpgradePreview",
]
