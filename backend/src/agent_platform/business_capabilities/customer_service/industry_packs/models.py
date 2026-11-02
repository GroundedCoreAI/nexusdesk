"""Strict manifests for versioned customer-service industry packs.

The models describe deployable pack assets.  They deliberately do not
duplicate runtime scenario entities: the compiler converts each scenario
template into the existing :class:`ScenarioConfig`.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..scenarios.models import (
    CandidateStrategy,
    EntryType,
    FactField,
    HandlerType,
    ObjectMode,
    SimulatedObject,
    SimulationRequest,
)
from ..scenarios.models import ScenarioTemplate as ExecutionTemplate
from ..service_apps.models import ApplicationCapability, ApplicationChannel

KEY_PATTERN = r"^[a-z][a-z0-9_-]{0,63}$"
SEMVER_PATTERN = r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
OBJECT_TYPE_PATTERN = r"^[a-z][a-z0-9_.-]{0,99}$"


def key_is_invalid(value: str) -> bool:
    """Return whether a value violates the shared pack key grammar."""

    return not isinstance(value, str) or re.fullmatch(KEY_PATTERN, value) is None


def version_is_invalid(value: str) -> bool:
    """Return whether a value violates the pack SemVer grammar."""

    return not isinstance(value, str) or re.fullmatch(SEMVER_PATTERN, value) is None


class IndustryPackMaturity(StrEnum):
    """Template maturity, independent from persisted scenario status."""

    ALPHA = "alpha"
    BETA = "beta"
    GA = "ga"


class ScenarioKind(StrEnum):
    """Product-level task type; execution still uses ``ExecutionTemplate``."""

    QUERY = "query"
    ACTION = "action"
    DIAGNOSIS = "diagnosis"
    SERVICE = "service"


class IndustryPackModel(BaseModel):
    """Shared strict validation behavior for pack assets."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @field_validator("*", mode="before")
    @classmethod
    def strip_string_values(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value


def _default_candidate_strategy() -> CandidateStrategy:
    return CandidateStrategy(
        empty_state="没有找到可选择的对象，请稍后重试或转人工。",
        unavailable_state="对象服务暂时不可用，请稍后重试或转人工。",
    )


class CatalogCategoryTemplate(IndustryPackModel):
    """A suggested application catalog category."""

    key: str = Field(pattern=KEY_PATTERN, max_length=64)
    name: str = Field(min_length=1, max_length=100)
    order: int = Field(default=0, ge=0)


class ObjectTemplate(IndustryPackModel):
    """Reusable business-object and fact projection blueprint."""

    object_template_key: str = Field(pattern=KEY_PATTERN, max_length=64)
    object_type: str = Field(pattern=OBJECT_TYPE_PATTERN, max_length=100)
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=1000)
    provider_key: str = Field(min_length=1, max_length=100)
    default_mode: ObjectMode = ObjectMode.REQUIRED
    permission_scope: str = Field(default="customer_scope", min_length=1, max_length=100)
    fact_fields: list[FactField] = Field(default_factory=list, max_length=100)
    sensitive_fields: list[str] = Field(default_factory=list, max_length=100)
    candidate_strategy: CandidateStrategy = Field(default_factory=_default_candidate_strategy)
    sample_refs: list[str] = Field(default_factory=list, max_length=100)
    config: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def object_template_is_consistent(self) -> Self:
        fact_keys = [field.key for field in self.fact_fields]
        duplicate = next((key for key in fact_keys if fact_keys.count(key) > 1), None)
        if duplicate is not None:
            raise ValueError(f"duplicate object fact key: {duplicate}")
        if len(set(self.sensitive_fields)) != len(self.sensitive_fields):
            raise ValueError("sensitive_fields must not contain duplicates")
        if any(not key for key in self.sensitive_fields):
            raise ValueError("sensitive_fields must not contain blank values")
        return self


class ScenarioTemplate(IndustryPackModel):
    """A complete, versioned scenario blueprint.

    ``config`` contains the task-specific part of an existing
    ``ScenarioConfig`` payload.  Fields owned by the pack/template
    (name, description, execution template, object and facts) are applied by
    the compiler.
    """

    template_key: str = Field(pattern=KEY_PATTERN, max_length=64)
    template_version: str = Field(pattern=SEMVER_PATTERN, max_length=64)
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=1000)
    scenario_kind: ScenarioKind
    execution_template: ExecutionTemplate
    maturity: IndustryPackMaturity
    catalog_category_key: str | None = Field(
        default=None,
        pattern=KEY_PATTERN,
        max_length=64,
    )
    object_template_key: str | None = Field(
        default=None,
        pattern=KEY_PATTERN,
        max_length=64,
    )
    config: dict[str, Any] = Field(default_factory=dict)
    channels: list[str] = Field(default_factory=list, max_length=50)
    sample_refs: list[str] = Field(default_factory=list, max_length=100)
    acceptance_case_refs: list[str] = Field(default_factory=list, max_length=100)
    deprecated: bool = False

    @model_validator(mode="after")
    def scenario_template_is_consistent(self) -> Self:
        if len(set(self.channels)) != len(self.channels):
            raise ValueError("channels must not contain duplicates")
        if any(not channel for channel in self.channels):
            raise ValueError("channels must not contain blank values")
        if "industry_pack" in (self.config.get("config") or {}):
            raise ValueError("scenario config must not define reserved key 'industry_pack'")
        blueprint_template = self.config.get("template")
        if blueprint_template is not None and blueprint_template != self.execution_template.value:
            raise ValueError(
                "scenario config.template must match scenario template execution_template"
            )
        return self


class PackSample(IndustryPackModel):
    """A lightweight, deterministic simulation sample owned by the pack."""

    sample_id: str = Field(pattern=KEY_PATTERN, max_length=64)
    scenario_template_key: str = Field(pattern=KEY_PATTERN, max_length=64)
    name: str = Field(default="", max_length=100)
    message: str = Field(min_length=1, max_length=8000)
    entry: EntryType = EntryType.NATURAL_LANGUAGE
    object: SimulatedObject | None = None
    selected_decision: str | None = Field(default=None, max_length=100)
    selected_handler: str | None = Field(default=None, max_length=100)
    description: str = Field(default="", max_length=1000)

    def as_simulation_request(self) -> SimulationRequest:
        """Convert the sample into the existing simulation request contract."""

        return SimulationRequest(
            message=self.message,
            entry=self.entry,
            object=self.object,
            selected_decision=self.selected_decision,
            selected_handler=self.selected_handler,
        )


class AcceptanceExpectation(IndustryPackModel):
    """Expected observable outcome for one pack acceptance case."""

    result_status: str = Field(min_length=1, max_length=50)
    handler_type: HandlerType | None = None
    must_include_facts: list[str] = Field(default_factory=list, max_length=100)
    must_not_include: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def expectation_lists_are_unique(self) -> Self:
        for label, values in (
            ("must_include_facts", self.must_include_facts),
            ("must_not_include", self.must_not_include),
        ):
            duplicate = next((value for value in values if values.count(value) > 1), None)
            if duplicate is not None:
                raise ValueError(f"duplicate {label}: {duplicate}")
            if any(not value for value in values):
                raise ValueError(f"{label} must not contain blank values")
        return self


class AcceptanceCase(IndustryPackModel):
    """A declarative acceptance scenario compiled into existing simulations."""

    case_id: str = Field(pattern=KEY_PATTERN, max_length=64)
    scenario_template_key: str = Field(pattern=KEY_PATTERN, max_length=64)
    required: bool = True
    given: str = Field(default="", max_length=2000)
    when: str = Field(default="", max_length=2000)
    then: AcceptanceExpectation


class ApplicationBlueprint(IndustryPackModel):
    """Suggested application composition generated from one pack."""

    application_key: str | None = Field(default=None, pattern=KEY_PATTERN, max_length=64)
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=1000)
    catalog_category_keys: list[str] = Field(default_factory=list, max_length=100)
    scenario_template_keys: list[str] = Field(default_factory=list, max_length=100)
    scenario_template_versions: dict[str, str] = Field(default_factory=dict)
    capabilities: list[ApplicationCapability] = Field(default_factory=list, max_length=100)
    default_execution_order: list[str] = Field(
        default_factory=lambda: ["deterministic", "action", "agent", "human"],
        max_length=20,
    )
    channels: list[ApplicationChannel] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def application_blueprint_is_consistent(self) -> Self:
        for label, values in (
            ("catalog category", self.catalog_category_keys),
            ("scenario template", self.scenario_template_keys),
            ("default execution stage", self.default_execution_order),
        ):
            duplicate = next((value for value in values if values.count(value) > 1), None)
            if duplicate is not None:
                raise ValueError(f"duplicate {label}: {duplicate}")
        if any(not value for value in self.default_execution_order):
            raise ValueError("default_execution_order must not contain blank values")
        for template_key, version in self.scenario_template_versions.items():
            if key_is_invalid(template_key):
                raise ValueError(f"invalid scenario template version key: {template_key!r}")
            if version_is_invalid(version):
                raise ValueError(
                    f"invalid version for scenario template '{template_key}': {version!r}"
                )
        return self


class IndustryPackManifest(IndustryPackModel):
    """Top-level deployable industry pack manifest."""

    schema_version: Literal["v1"] = "v1"
    pack_key: str = Field(pattern=KEY_PATTERN, max_length=64)
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=2000)
    pack_version: str = Field(pattern=SEMVER_PATTERN, max_length=64)
    maturity: IndustryPackMaturity
    supported_channels: list[str] = Field(default_factory=list, max_length=50)
    catalog_categories: list[CatalogCategoryTemplate] = Field(
        default_factory=list,
        max_length=100,
    )
    object_templates: list[ObjectTemplate] = Field(default_factory=list, max_length=100)
    scenario_templates: list[ScenarioTemplate] = Field(default_factory=list, max_length=200)
    sample_data: list[PackSample] = Field(default_factory=list, max_length=500)
    acceptance_cases: list[AcceptanceCase] = Field(default_factory=list, max_length=500)
    application_blueprint: ApplicationBlueprint | None = None

    @model_validator(mode="after")
    def manifest_shape_is_consistent(self) -> Self:
        if len(set(self.supported_channels)) != len(self.supported_channels):
            raise ValueError("supported_channels must not contain duplicates")
        if any(not channel for channel in self.supported_channels):
            raise ValueError("supported_channels must not contain blank values")
        return self


__all__ = [
    "AcceptanceCase",
    "AcceptanceExpectation",
    "ApplicationBlueprint",
    "CatalogCategoryTemplate",
    "IndustryPackManifest",
    "IndustryPackMaturity",
    "ObjectTemplate",
    "PackSample",
    "ScenarioKind",
    "ScenarioTemplate",
]
