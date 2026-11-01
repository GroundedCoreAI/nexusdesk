"""Configuration contracts for versioned service applications."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from ..scenarios.models import EntryType, ScenarioModel, SimulatedObject


class ApplicationStatus(StrEnum):
    DRAFT = "draft"
    REVIEW = "review"
    PUBLISHED = "published"
    OFFLINE = "offline"


class CapabilityType(StrEnum):
    DIRECT = "direct"
    KNOWLEDGE = "knowledge"
    QUERY = "query"
    ACTION = "action"
    AGENT = "agent"
    HUMAN = "human"
    TRACKING = "tracking"


class ChannelStatus(StrEnum):
    ACTIVE = "active"
    CANARY = "canary"
    DISABLED = "disabled"


class ApplicationScenarioReference(ScenarioModel):
    """A reference, not a copy, to a versioned service scenario."""

    key: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$", max_length=64)
    version: int | None = Field(default=None, ge=1)
    enabled: bool = True


class ApplicationCapability(ScenarioModel):
    """An execution capability declaration owned by an application.

    Resource-backed capabilities only carry references. Agent prompts, models
    and tools remain in Agent management and are never copied into an app.
    """

    key: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$", max_length=64)
    type: CapabilityType
    label: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=1000)
    enabled: bool = True
    priority: int = Field(default=0, ge=0)
    when: dict[str, Any] = Field(default_factory=dict)
    agent_id: UUID | None = None
    agent_version: int | None = Field(default=None, ge=1)
    agent_name: str | None = Field(default=None, max_length=100)
    queue: str | None = Field(default=None, max_length=100)
    tool: str | None = Field(default=None, max_length=100)
    config: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def capability_references_are_consistent(self) -> Self:
        if self.type == CapabilityType.AGENT and self.agent_id is None:
            raise ValueError("agent capability requires agent_id")
        if self.type != CapabilityType.AGENT and (
            self.agent_id is not None
            or self.agent_version is not None
            or self.agent_name is not None
        ):
            raise ValueError("only agent capabilities may reference an agent")
        if self.agent_version is not None and self.agent_id is None:
            raise ValueError("agent_version requires agent_id")
        return self


class ApplicationChannel(ScenarioModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$", max_length=64)
    name: str = Field(min_length=1, max_length=100)
    type: str = Field(default="web", pattern=r"^[a-z][a-z0-9_-]{0,39}$")
    status: ChannelStatus = ChannelStatus.ACTIVE
    config: dict[str, Any] = Field(default_factory=dict)


class ApplicationServiceCategory(ScenarioModel):
    """An application-owned service catalog category.

    Scenario configs reference the category by name. Catalog updates that
    rename or merge categories are applied to the referenced scenario drafts
    in the same transaction.
    """

    name: str = Field(min_length=1, max_length=100)
    order: int = Field(default=0, ge=0)


class ServiceApplicationConfig(ScenarioModel):
    schema_version: Literal["v1"] = "v1"
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=1000)
    service_categories: list[ApplicationServiceCategory] = Field(
        default_factory=list,
        max_length=100,
    )
    scenarios: list[ApplicationScenarioReference] = Field(default_factory=list, max_length=100)
    capabilities: list[ApplicationCapability] = Field(default_factory=list, max_length=100)
    default_execution_order: list[str] = Field(
        default_factory=lambda: ["deterministic", "action", "agent", "human"],
        max_length=20,
    )
    channels: list[ApplicationChannel] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def application_configuration_is_consistent(self) -> Self:
        for label, keys in (
            ("scenario", [item.key for item in self.scenarios]),
            ("capability", [item.key for item in self.capabilities]),
            ("channel", [item.key for item in self.channels]),
        ):
            duplicate = next((key for key in keys if keys.count(key) > 1), None)
            if duplicate is not None:
                raise ValueError(f"duplicate {label} key: {duplicate}")
        if any(not item for item in self.default_execution_order):
            raise ValueError("default_execution_order must not contain blank values")
        duplicate_stage = next(
            (
                key
                for key in self.default_execution_order
                if self.default_execution_order.count(key) > 1
            ),
            None,
        )
        if duplicate_stage is not None:
            raise ValueError(f"duplicate execution stage: {duplicate_stage}")
        category_names = [item.name for item in self.service_categories]
        duplicate_category = next(
            (name for name in category_names if category_names.count(name) > 1),
            None,
        )
        if duplicate_category is not None:
            raise ValueError(f"duplicate service category: {duplicate_category}")
        return self


class ServiceCatalogUpdateRequest(ScenarioModel):
    revision: int = Field(ge=1)
    categories: list[ApplicationServiceCategory] = Field(default_factory=list, max_length=100)
    category_changes: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def catalog_update_is_consistent(self) -> Self:
        names = [item.name for item in self.categories]
        duplicate = next((name for name in names if names.count(name) > 1), None)
        if duplicate is not None:
            raise ValueError(f"duplicate service category: {duplicate}")
        for source, target in self.category_changes.items():
            if not source.strip() or not target.strip():
                raise ValueError("category changes must not contain blank names")
            if source == target:
                raise ValueError("category changes cannot map a category to itself")
            if target not in names:
                raise ValueError(f"category change target is not in the catalog: {target}")
        return self


class ApplicationSimulationRequest(ScenarioModel):
    message: str = Field(min_length=1, max_length=8000)
    entry: EntryType = EntryType.NATURAL_LANGUAGE
    object: SimulatedObject | None = None
    selected_decision: str | None = None
    selected_handler: str | None = None
    scenario_key: str | None = Field(
        default=None,
        pattern=r"^[a-z][a-z0-9_-]{0,63}$",
        max_length=64,
    )
    application_version: int | None = Field(default=None, ge=1)


__all__ = [
    "ApplicationCapability",
    "ApplicationChannel",
    "ApplicationScenarioReference",
    "ApplicationServiceCategory",
    "ApplicationSimulationRequest",
    "ApplicationStatus",
    "CapabilityType",
    "ChannelStatus",
    "ServiceApplicationConfig",
    "ServiceCatalogUpdateRequest",
]
