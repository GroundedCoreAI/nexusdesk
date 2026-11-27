"""Strict Skill definition and request contracts for Phase 2."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Literal
from uuid import UUID

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .classification import RiskLevel

SkillCategory = Literal["service", "finance", "sales", "general"]
SkillType = Literal["instruction", "knowledge", "query", "action", "handoff"]
SkillTrigger = Literal["agent_auto", "manual"]
SkillOutputFormat = Literal["text", "json"]
SkillParameterType = Literal["string", "number", "integer", "boolean", "object", "array"]
SkillRetryPolicy = Literal["none", "one", "two"]
SkillIdempotency = Literal["none", "optional", "required"]
SkillErrorBehavior = Literal["fail", "fallback", "handoff"]
# Modes a caller may *request* over ``POST /skills``. ``package`` is excluded on
# purpose: importing an archive creates the Skill and its package together, so it
# has its own endpoint and must not be reachable through the generic create body.
SkillCreateMode = Literal["ai", "template", "professional"]
# Modes a *stored* definition may carry, including provenance for imported Skills.
SkillCreationMode = Literal["ai", "template", "professional", "package"]
SkillStatus = Literal["draft", "published", "archived"]
SkillReleaseKind = Literal["initial", "major", "minor", "patch", "rollback"]
SkillVersionBump = Literal["major", "minor", "patch"]

SKILL_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
PARAMETER_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
SEMVER_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
DIGEST_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")


class Contract(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        populate_by_name=True,
        serialize_by_alias=True,
    )


class SkillParameter(Contract):
    name: str = Field(min_length=1, max_length=64)
    type: SkillParameterType
    required: bool = False
    default: Any = None
    description: str = Field(default="", max_length=500)

    @field_validator("name")
    @classmethod
    def name_is_machine_safe(cls, value: str) -> str:
        if not PARAMETER_NAME_PATTERN.fullmatch(value):
            raise ValueError(
                "parameter name must start with a letter and contain only letters, digits, or underscores"
            )
        return value


class SkillDependencies(Contract):
    model_profile_id: UUID | None = None
    model_profile_version: int | None = Field(default=None, ge=1)
    knowledge_base_ids: list[UUID] = Field(default_factory=list, max_length=20)
    tool_names: list[str] = Field(default_factory=list, max_length=20)
    handoff_queue: str | None = Field(default=None, min_length=1, max_length=100)

    @field_validator("tool_names")
    @classmethod
    def unique_tool_names(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("tool names must be unique")
        if any(not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", name) for name in value):
            raise ValueError("tool name is invalid")
        return value


class SkillOutput(Contract):
    format: SkillOutputFormat = "text"
    json_schema: dict[str, Any] | None = Field(default=None, alias="schema")


class SkillRuntime(Contract):
    timeout_seconds: int = Field(default=30, ge=1, le=60)
    retry_policy: SkillRetryPolicy = "none"
    confirmation_required: bool = False
    idempotency: SkillIdempotency = "none"
    error_behavior: SkillErrorBehavior = "fail"
    max_amount: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class SkillDefinition(Contract):
    schema_version: Literal["v1"] = "v1"
    creation_mode: SkillCreationMode = "professional"
    type: SkillType = "instruction"
    trigger: SkillTrigger = "agent_auto"
    instructions: str = Field(default="", max_length=20_000)
    parameters: list[SkillParameter] = Field(default_factory=list, max_length=50)
    output: SkillOutput = Field(default_factory=SkillOutput)
    dependencies: SkillDependencies = Field(default_factory=SkillDependencies)
    runtime: SkillRuntime = Field(default_factory=SkillRuntime)
    permission_scope: Literal["workspace"] = "workspace"

    @model_validator(mode="after")
    def validate_definition(self):
        names = [parameter.name for parameter in self.parameters]
        if len(names) != len(set(names)):
            raise ValueError("parameter names must be unique")
        for parameter in self.parameters:
            if parameter.default is not None and not Draft202012Validator(
                {"type": parameter.type}
            ).is_valid(parameter.default):
                raise ValueError(
                    f"default for parameter {parameter.name} does not match {parameter.type}"
                )
        if self.output.json_schema is not None:
            try:
                Draft202012Validator.check_schema(self.output.json_schema)
            except SchemaError as exc:
                raise ValueError(f"output schema is invalid: {exc.message}") from None
        if self.output.format == "json" and self.output.json_schema is None:
            raise ValueError("json output requires a schema")
        if (
            self.dependencies.model_profile_id is None
            and self.dependencies.model_profile_version is not None
        ):
            raise ValueError("model profile version requires a profile id")
        if self.runtime.error_behavior == "handoff" and not self.dependencies.handoff_queue:
            raise ValueError("handoff error behavior requires a handoff queue")
        return self

    def validate_for_release(self) -> SkillDefinition:
        """Apply the type-specific release gate without blocking partial drafts."""

        if self.type == "instruction":
            if not self.instructions.strip():
                raise ValueError("instruction skills require instructions")
            if self.dependencies.model_profile_id is None:
                raise ValueError("instruction skills require a model profile")
            if self.dependencies.model_profile_version is None:
                raise ValueError("instruction skills require a model profile version")
        if self.type == "knowledge" and not self.dependencies.knowledge_base_ids:
            raise ValueError("knowledge skills require at least one knowledge base")
        if self.type in {"query", "action"} and not self.dependencies.tool_names:
            raise ValueError(f"{self.type} skills require at least one tool")
        if self.type == "action" and not self.runtime.confirmation_required:
            raise ValueError("action skills require confirmation")
        if self.type == "handoff" and not self.dependencies.handoff_queue:
            raise ValueError("handoff skills require a handoff queue")
        return self

    def parameter_schema(self) -> dict[str, Any]:
        properties: dict[str, Any] = {}
        required: list[str] = []
        for parameter in self.parameters:
            value: dict[str, Any] = {
                "type": parameter.type,
                "description": parameter.description,
            }
            if parameter.default is not None:
                value["default"] = parameter.default
            properties[parameter.name] = value
            if parameter.required:
                required.append(parameter.name)
        return {
            "type": "object",
            "properties": properties,
            **({"required": required} if required else {}),
            "additionalProperties": False,
        }


class SkillCreateRequest(Contract):
    mode: SkillCreateMode
    prompt: str | None = Field(default=None, max_length=4000)
    template_key: str | None = Field(default=None, max_length=64)
    definition: dict[str, Any] | None = None

    @model_validator(mode="after")
    def mode_fields(self):
        if self.mode == "ai" and not (self.prompt or "").strip():
            raise ValueError("ai creation requires a prompt")
        if self.mode == "template" and not self.template_key:
            raise ValueError("template creation requires a template key")
        return self


class SkillDraftUpdate(Contract):
    revision: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=1000)
    category: SkillCategory
    tags: list[str] = Field(default_factory=list, max_length=10)
    visibility: Literal["workspace"] = "workspace"
    # Author-facing label only. Omitted means "follow the computed baseline".
    risk_level: RiskLevel | None = None
    definition: dict[str, Any]

    @field_validator("tags")
    @classmethod
    def valid_tags(cls, value: list[str]) -> list[str]:
        unique = list(dict.fromkeys(tag.strip() for tag in value if tag.strip()))
        if len(unique) != len(value):
            raise ValueError("tags must be nonempty and unique")
        if any(len(tag) > 32 for tag in unique):
            raise ValueError("tag exceeds 32 characters")
        return unique


class SkillTestRequest(Contract):
    draft_revision: int = Field(ge=1)
    input: dict[str, Any]
    scenario: str = Field(default="", max_length=1000)
    client_request_id: str | None = Field(default=None, max_length=128)

    @field_validator("client_request_id")
    @classmethod
    def request_id_is_bounded(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class SkillPublishRequest(Contract):
    revision: int = Field(ge=1)
    bump: SkillVersionBump
    release_notes: str = Field(min_length=1, max_length=2000)


class SkillRollbackRequest(Contract):
    revision: int = Field(ge=1)
    target_version: int = Field(ge=1)
    release_notes: str = Field(min_length=1, max_length=2000)


class SkillDuplicateRequest(Contract):
    revision: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=100)


def validate_parameter_input(definition: SkillDefinition, payload: dict[str, Any]) -> None:
    errors = sorted(
        Draft202012Validator(definition.parameter_schema()).iter_errors(payload),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        raise ValueError(_validation_error(errors[0]))


def validate_output(definition: SkillDefinition, value: Any) -> None:
    if definition.output.format == "json":
        if definition.output.json_schema is None:
            raise ValueError("json output schema is required")
        errors = sorted(
            Draft202012Validator(definition.output.json_schema).iter_errors(value),
            key=lambda error: list(error.absolute_path),
        )
        if errors:
            raise ValueError(_validation_error(errors[0]))
        return
    if not isinstance(value, str) or not value.strip():
        raise ValueError("text output must be nonempty")


def _validation_error(error: ValidationError) -> str:
    path = ".".join(str(item) for item in error.absolute_path)
    return f"{path or 'input'}: {error.message}"


def canonical_definition(definition: SkillDefinition) -> str:
    return json.dumps(
        definition.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def definition_digest(definition: SkillDefinition | dict[str, Any]) -> str:
    payload = (
        definition.model_dump(mode="json")
        if isinstance(definition, SkillDefinition)
        else definition
    )
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def next_semver(current: str | None, bump: SkillVersionBump) -> str:
    if current is None or not SEMVER_PATTERN.fullmatch(current):
        return "1.0.0"
    major, minor, patch = (int(part) for part in current.split("."))
    if bump == "major":
        return f"{major + 1}.0.0"
    if bump == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def patch_semver(current: str | None) -> str:
    return next_semver(current, "patch")


__all__ = [
    "DIGEST_PATTERN",
    "SKILL_KEY_PATTERN",
    "SkillCreateRequest",
    "SkillDefinition",
    "SkillDraftUpdate",
    "SkillDuplicateRequest",
    "SkillPublishRequest",
    "SkillRollbackRequest",
    "SkillTestRequest",
    "canonical_definition",
    "definition_digest",
    "next_semver",
    "patch_semver",
    "validate_output",
    "validate_parameter_input",
]
