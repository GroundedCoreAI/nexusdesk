"""Versioned service-scenario configuration contracts.

The models in this module are deliberately transport-neutral.  They describe
what an operator can configure and what the deterministic simulator returns;
persistence, routes, provider calls and Agent resolution stay outside this
package.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ScenarioStatus(StrEnum):
    DRAFT = "draft"
    REVIEW = "review"
    PUBLISHED = "published"
    OFFLINE = "offline"


class EntryType(StrEnum):
    NATURAL_LANGUAGE = "natural_language"
    SERVICE_CATALOG = "service_catalog"
    OBJECT_CARD = "object_card"
    EXTERNAL_LINK = "external_link"


class ObjectMode(StrEnum):
    NONE = "none"
    IMPLICIT = "implicit"
    OPTIONAL = "optional"
    REQUIRED = "required"
    MULTIPLE = "multiple"


class HandlerType(StrEnum):
    DIRECT = "direct"
    KNOWLEDGE = "knowledge"
    QUERY = "query"
    ACTION = "action"
    AGENT = "agent"
    HUMAN = "human"
    TRACKING = "tracking"


class UserDecisionKind(StrEnum):
    SELECT_OBJECT = "select_object"
    CONFIRM_OBJECT = "confirm_object"
    SELECT_INTENT = "select_intent"
    CONFIRM_ACTION = "confirm_action"
    HANDOFF = "handoff"


class ScenarioTemplate(StrEnum):
    CONSULT = "consult"
    QUERY = "query"
    ACTION = "action"


class ScenarioModel(BaseModel):
    """Shared strict configuration behavior."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @field_validator("*", mode="before")
    @classmethod
    def strip_string_values(cls, value: Any) -> Any:
        # Pydantic's str_strip_whitespace does not strip enum inputs before
        # enum lookup, so do it once for every top-level string field.
        return value.strip() if isinstance(value, str) else value


class ScenarioEntry(ScenarioModel):
    key: str
    type: EntryType
    label: str
    description: str = ""
    enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)


class CandidateStrategy(ScenarioModel):
    sort: str = "recent_desc"
    limit: int = Field(default=5, ge=1, le=50)
    filters: list[str] = Field(default_factory=list)
    empty_state: str
    unavailable_state: str


class BusinessObjectConfig(ScenarioModel):
    type: str
    provider: str
    required: bool
    mode: ObjectMode
    candidate_strategy: CandidateStrategy
    permission_policy: str = "customer_scope"
    config: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def required_mode_is_consistent(self) -> Self:
        if not self.required and self.mode == ObjectMode.REQUIRED:
            raise ValueError("required=false cannot use object mode 'required'")
        return self


class FactField(ScenarioModel):
    key: str
    label: str
    source: str
    format: str = "text"
    order: int = Field(default=0, ge=0)
    masked: bool = False
    audiences: list[str] = Field(default_factory=lambda: ["customer", "agent", "human"])
    refresh: str = "on_open"
    config: dict[str, Any] = Field(default_factory=dict)

    @field_validator("audiences")
    @classmethod
    def audiences_must_not_be_empty(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("audiences must not be empty")
        if any(not audience for audience in value):
            raise ValueError("audiences must not contain blank values")
        return value


class DecisionOption(ScenarioModel):
    value: str
    label: str
    description: str = ""
    next: str | None = None


class UserDecision(ScenarioModel):
    key: str
    kind: UserDecisionKind
    label: str
    required: bool = True
    options: list[DecisionOption] = Field(default_factory=list)
    allow_free_text: bool = False
    allow_skip: bool = False
    confirm: bool = False
    correctable: bool = True
    when: dict[str, Any] = Field(default_factory=dict)


class Recommendation(ScenarioModel):
    key: str
    label: str
    message: str
    when: dict[str, Any] = Field(default_factory=dict)


class HandlerCondition(ScenarioModel):
    object_statuses: list[str] = Field(default_factory=list)
    message_terms: list[str] = Field(default_factory=list)
    decision_keys: list[str] = Field(default_factory=list)
    requires_object: bool | None = None


class HandlerDefinition(ScenarioModel):
    key: str
    type: HandlerType
    label: str
    priority: int = Field(default=0, ge=0)
    enabled: bool = True
    when: HandlerCondition = Field(default_factory=HandlerCondition)
    agent_id: UUID | None = None
    agent_version: int | None = None
    agent_name: str | None = None
    queue: str | None = None
    tool: str | None = None
    reply: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def agent_handler_has_agent(self) -> Self:
        if self.type == HandlerType.AGENT and self.agent_id is None:
            raise ValueError("agent handler requires agent_id")
        if self.type == HandlerType.DIRECT and not self.reply:
            raise ValueError("direct handler requires a reply")
        return self


class ScenarioMatching(ScenarioModel):
    keywords: list[str] = Field(default_factory=list)
    intents: list[str] = Field(default_factory=list)
    negative_keywords: list[str] = Field(default_factory=list)


class ScenarioConfig(ScenarioModel):
    schema_version: Literal["v1"] = "v1"
    name: str
    description: str
    domain: str
    category: str = "order_service"
    template: ScenarioTemplate
    channels: list[str] = Field(default_factory=list)
    entries: list[ScenarioEntry] = Field(default_factory=list)
    facts: list[FactField] = Field(default_factory=list)
    object: BusinessObjectConfig | None = None
    decisions: list[UserDecision] = Field(default_factory=list)
    recommendations: list[Recommendation] = Field(default_factory=list)
    handlers: list[HandlerDefinition] = Field(default_factory=list)
    fallback_order: list[str] = Field(default_factory=list)
    matching: ScenarioMatching = Field(default_factory=ScenarioMatching)
    config: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def configuration_is_consistent(self) -> Self:
        collections = (
            ("entry", self.entries),
            ("fact", self.facts),
            ("decision", self.decisions),
            ("recommendation", self.recommendations),
            ("handler", self.handlers),
        )
        for label, items in collections:
            keys = [item.key for item in items]
            duplicate = next((key for key in keys if keys.count(key) > 1), None)
            if duplicate is not None:
                raise ValueError(f"duplicate {label} key: {duplicate}")

        handler_keys = {handler.key for handler in self.handlers}
        fallback_duplicate = next(
            (key for key in self.fallback_order if self.fallback_order.count(key) > 1),
            None,
        )
        if fallback_duplicate is not None:
            raise ValueError(f"duplicate fallback_order handler key: {fallback_duplicate}")
        unknown_fallback = next(
            (key for key in self.fallback_order if key not in handler_keys),
            None,
        )
        if unknown_fallback is not None:
            raise ValueError(f"fallback_order references unknown handler key: {unknown_fallback}")

        if not any(handler.enabled for handler in self.handlers):
            raise ValueError("at least one enabled handler is required")

        if self.object is not None and self.object.mode == ObjectMode.NONE and self.object.required:
            raise ValueError("object mode 'none' cannot be required")

        confirmation_keys = {
            decision.key
            for decision in self.decisions
            if decision.kind == UserDecisionKind.CONFIRM_ACTION
        }
        for handler in self.handlers:
            if handler.type == HandlerType.DIRECT and not handler.reply:
                raise ValueError(f"direct handler '{handler.key}' requires a reply")
            if handler.type == HandlerType.AGENT and handler.agent_id is None:
                raise ValueError(f"agent handler '{handler.key}' requires agent_id")
            if handler.type == HandlerType.ACTION:
                requires_confirmation = handler.config.get("requires_confirmation", True)
                if requires_confirmation is not False and not confirmation_keys:
                    raise ValueError(
                        f"action handler '{handler.key}' requires a confirm_action decision"
                    )
        return self


class SimulatedObject(ScenarioModel):
    id: str
    type: str
    status: str = ""
    facts: dict[str, Any] = Field(default_factory=dict)
    accessible: bool = True
    exists: bool = True


class SimulationRequest(ScenarioModel):
    message: str = Field(min_length=1, max_length=8000)
    entry: EntryType = EntryType.NATURAL_LANGUAGE
    object: SimulatedObject | None = None
    selected_decision: str | None = None
    selected_handler: str | None = None


class SimulationTrace(ScenarioModel):
    schema_version: Literal["v1"] = "v1"
    scenario_key: str
    scenario_name: str
    scenario_version: int | None
    scenario_status: ScenarioStatus
    resolved_by: Literal["target", "keyword", "none"]
    steps: list[dict[str, Any]]
    object_ref: dict[str, Any] | None = None
    facts: list[dict[str, Any]] = Field(default_factory=list)
    decisions: list[dict[str, Any]] = Field(default_factory=list)
    recommendations: list[dict[str, Any]] = Field(default_factory=list)
    handler: dict[str, Any] | None = None
    result: dict[str, Any]
    fallback_path: list[str] = Field(default_factory=list)
    explanation: list[str] = Field(default_factory=list)
    simulated: bool = True


__all__ = [
    "BusinessObjectConfig",
    "CandidateStrategy",
    "DecisionOption",
    "EntryType",
    "FactField",
    "HandlerCondition",
    "HandlerDefinition",
    "HandlerType",
    "ObjectMode",
    "Recommendation",
    "ScenarioConfig",
    "ScenarioEntry",
    "ScenarioMatching",
    "ScenarioModel",
    "ScenarioStatus",
    "ScenarioTemplate",
    "SimulatedObject",
    "SimulationRequest",
    "SimulationTrace",
    "UserDecision",
    "UserDecisionKind",
]
