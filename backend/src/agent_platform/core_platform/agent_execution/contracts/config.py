"""Versioned engine configuration and the single legacy alias normalizer."""

import json
from collections.abc import Mapping
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from .base import ExecutionContractModel
from .common import AdapterVersion, EngineId, ProtocolId

CapabilityName = Literal[
    "streaming",
    "persistent_session",
    "session_resume",
    "cancellation",
    "human_approval",
    "interactive_input",
    "tool_calling",
    "file_operations",
    "terminal_execution",
    "native_events",
    "workspace_required",
]

_LEGACY_REACT_FIELDS = ("model_profile_id", "model_profile_version", "max_model_rounds")
_DEFAULT_ENGINE = {
    "engine_id": "react",
    "protocol_id": "native",
    "adapter_version": "v1",
}


class EngineIdentity(ExecutionContractModel):
    """One exact engine, protocol, and adapter version; aliases are not identities."""

    engine_id: EngineId
    protocol_id: ProtocolId
    adapter_version: AdapterVersion


class ReactConfig(ExecutionContractModel):
    """React-only model selection and bounded model rounds."""

    model_profile_id: UUID | None = None
    model_profile_version: int | None = Field(default=None, ge=1)
    max_model_rounds: int = Field(default=6, ge=1, le=30)

    @model_validator(mode="after")
    def model_profile_is_paired(self) -> Self:
        if (self.model_profile_id is None) != (self.model_profile_version is None):
            raise ValueError("model_profile_id and model_profile_version must be set together")
        return self


class EmptyEngineConfig(ExecutionContractModel):
    """Safe no-configuration schema for legacy generic test adapter registrations."""


class ExecutionConfig(ExecutionContractModel):
    """Publishable execution configuration with no client-controlled policy fields."""

    engine: EngineIdentity = Field(default_factory=lambda: EngineIdentity(**_DEFAULT_ENGINE))
    react: ReactConfig | None = Field(default_factory=ReactConfig)
    # ``max_length`` is enforced before the ``after`` dedup validator below, so
    # an over-bound list that still contains duplicates is rejected outright;
    # deduplication is not expected to rescue oversized input.
    disabled_capabilities: tuple[CapabilityName, ...] = Field(default=(), max_length=11)

    @field_validator("disabled_capabilities", mode="after")
    @classmethod
    def deduplicate_disabled_capabilities(
        cls, value: tuple[CapabilityName, ...]
    ) -> tuple[CapabilityName, ...]:
        return tuple(dict.fromkeys(value))

    @model_validator(mode="after")
    def react_matches_engine(self) -> Self:
        is_react = self.engine.engine_id == "react"
        if is_react and self.react is None:
            raise ValueError("react configuration is required for the react engine")
        if not is_react and self.react is not None:
            raise ValueError("react configuration is only valid for the react engine")
        return self


def _validation_error(path: tuple[str, ...], message: str) -> ValidationError:
    return ValidationError.from_exception_data(
        "ExecutionConfig",
        [
            {
                "type": "value_error",
                "loc": path,
                "input": None,
                "ctx": {"error": ValueError(message)},
            }
        ],
    )


def _json_default(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, UUID):
        return str(value)
    raise TypeError("value is not JSON-compatible")


def _json_value(value: object) -> str:
    return json.dumps(value, default=_json_default, sort_keys=True, separators=(",", ":"))


def _alias_values_conflict(legacy: object, react: object) -> bool:
    """Compare two alias values on their canonical JSON form.

    A value that cannot be JSON-canonicalised cannot be proven equal, so the
    pair fails closed as a conflict. ``json.dumps`` can raise ``TypeError`` for
    unsupported types and ``ValueError`` for circular references or oversized
    ints; both mean "cannot prove equality" here, so both fail closed. This
    keeps in-process callers (scripts, seeds, tests) inside the ValidationError
    contract instead of letting a bare serialization error escape the
    normalizer.
    """

    try:
        return _json_value(legacy) != _json_value(react)
    except (TypeError, ValueError):
        return True


def normalize_execution_config(value: ExecutionConfig | Mapping[str, object]) -> ExecutionConfig:
    """Return a new canonical execution DTO without modifying the supplied object.

    The normalizer accepts the three historical root React fields as aliases. JSON
    validation is intentional: AgentConfig is persisted as JSONB, and strict UUID
    fields must accept their JSON string representation while still rejecting Python
    coercions such as a string integer for ``max_model_rounds``.
    """

    if isinstance(value, ExecutionConfig):
        value = value.model_dump(warnings=False)
    if not isinstance(value, Mapping):
        raise _validation_error((), "Execution configuration must be an object")

    supplied_react = value.get("react", {})
    supplied_engine = value.get("engine")
    if isinstance(supplied_engine, Mapping) and set(supplied_engine) - {
        "engine_id",
        "protocol_id",
        "adapter_version",
    }:
        raise _validation_error(("engine",), "Engine configuration contains unknown fields")
    explicit_non_react = (
        isinstance(supplied_engine, Mapping) and supplied_engine.get("engine_id") != "react"
    )
    non_react_defaults_only = all(
        value.get(field, default) == default
        for field, default in (
            ("model_profile_id", None),
            ("model_profile_version", None),
            ("max_model_rounds", 6),
        )
    )
    if explicit_non_react and "react" not in value and non_react_defaults_only:
        supplied_react = None
    if supplied_react is None and explicit_non_react and not non_react_defaults_only:
        raise _validation_error(
            ("react",),
            "legacy React fields are only valid for the react engine",
        )
    legacy_only_fields: set[str] = set()
    if supplied_react is None or isinstance(supplied_react, Mapping):
        react = dict(supplied_react or {}) if supplied_react is not None else None
        for field in _LEGACY_REACT_FIELDS:
            if react is None:
                break
            legacy_present = field in value
            react_present = field in react
            if (
                legacy_present
                and react_present
                and _alias_values_conflict(value[field], react[field])
            ):
                raise _validation_error(
                    ("react", field),
                    f"react.{field} conflicts with legacy {field}",
                )
            if legacy_present and not react_present:
                react[field] = value[field]
                legacy_only_fields.add(field)
    else:
        react = supplied_react

    canonical = {key: item for key, item in value.items() if key not in _LEGACY_REACT_FIELDS}
    canonical["engine"] = value.get("engine", _DEFAULT_ENGINE)
    canonical["react"] = react
    try:
        return ExecutionConfig.model_validate_json(_json_value(canonical))
    except ValidationError as exc:
        errors = []
        for error in exc.errors():
            location = tuple(error["loc"])
            if len(location) >= 2 and location[0] == "react" and location[1] in legacy_only_fields:
                error["loc"] = (location[1], *location[2:])
            elif (
                location == ("react",)
                and "react" not in value
                and any(field in value for field in _LEGACY_REACT_FIELDS)
            ):
                error["loc"] = ()
            errors.append(error)
        raise ValidationError.from_exception_data(exc.title, errors) from None
    except (TypeError, ValueError):
        raise _validation_error((), "Execution configuration is not JSON-compatible") from None
