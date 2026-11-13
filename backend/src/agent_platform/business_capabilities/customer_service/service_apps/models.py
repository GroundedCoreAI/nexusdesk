"""Transport-neutral contracts for skill-centric service applications."""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal, Self
from urllib.parse import urlsplit
from uuid import UUID

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

APPLICATION_KEY_PATTERN = r"^[a-z][a-z0-9_-]{0,63}$"
RESOURCE_KEY_PATTERN = r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$"
HEADER_NAME_PATTERN = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
RESERVED_EXAMPLE_PREFIX = "example-"
FORBIDDEN_PUBLIC_HEADERS = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "cookie",
        "set-cookie",
        "host",
        "content-length",
        "transfer-encoding",
        "connection",
    }
)
SENSITIVE_HEADER_FRAGMENTS = ("api-key", "apikey", "token", "secret")


class ServiceApplicationModel(BaseModel):
    """Strict persisted/API configuration behavior."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ApplicationStatus(StrEnum):
    DRAFT = "draft"
    REVIEW = "review"
    PUBLISHED = "published"
    OFFLINE = "offline"


class ApplicationOrigin(StrEnum):
    USER = "user"
    EXAMPLE = "example"


class SkillType(StrEnum):
    KNOWLEDGE = "knowledge"
    QUERY = "query"
    ACTION = "action"
    HANDOFF = "handoff"


class ConnectionExecutorKind(StrEnum):
    HTTP = "http"
    INTERNAL = "internal"
    HUMAN_QUEUE = "human_queue"


class ConnectionMethod(StrEnum):
    GET = "GET"
    POST = "POST"


class AuthKind(StrEnum):
    NONE = "none"
    BEARER = "bearer"
    API_KEY = "api_key"
    CUSTOM = "custom"


class IdempotencyMode(StrEnum):
    NONE = "none"
    OPTIONAL = "optional"
    REQUIRED = "required"


class ErrorBehavior(StrEnum):
    FAIL = "fail"
    HANDOFF = "handoff"
    FALLBACK = "fallback"


def _validate_json_schema(value: dict[str, Any], *, code: str) -> dict[str, Any]:
    try:
        Draft202012Validator.check_schema(value)
    except SchemaError:
        raise ValueError(code) from None
    return value


def _validate_public_headers(value: dict[str, str]) -> dict[str, str]:
    names = list(value)
    if len({name.lower() for name in names}) != len(names):
        raise ValueError("duplicate public header")
    for name, header_value in value.items():
        lowered = name.lower()
        if not HEADER_NAME_PATTERN.fullmatch(name) or lowered in FORBIDDEN_PUBLIC_HEADERS:
            raise ValueError("invalid public header; use connection credentials")
        if any(fragment in lowered for fragment in SENSITIVE_HEADER_FRAGMENTS):
            raise ValueError("sensitive public header must be stored as a credential")
        if len(header_value) > 8192 or any(
            ord(character) < 32 or ord(character) > 126 for character in header_value
        ):
            raise ValueError("invalid public header value")
    return value


def _validate_connection_endpoint(
    executor_kind: ConnectionExecutorKind,
    endpoint: str | None,
    auth_kind: AuthKind,
    config: dict[str, Any],
) -> None:
    if executor_kind == ConnectionExecutorKind.HTTP and not endpoint:
        raise ValueError("http connection requires endpoint")
    if endpoint is not None:
        parsed = urlsplit(endpoint)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError("connection endpoint must be a fixed HTTP(S) URL")
        if parsed.query or parsed.fragment:
            raise ValueError("connection endpoint must not contain query or fragment")
    if auth_kind == AuthKind.CUSTOM and not config.get("header_name"):
        raise ValueError("custom authentication requires config.header_name")


class SkillSafety(ServiceApplicationModel):
    """Deterministic controls applied before and after a skill invocation."""

    requires_confirmation: bool = False
    max_amount: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    allowed_roles: list[str] = Field(default_factory=list, max_length=50)
    idempotency: IdempotencyMode = IdempotencyMode.NONE
    timeout_seconds: int = Field(default=10, ge=1, le=60)
    on_error: ErrorBehavior = ErrorBehavior.FAIL
    allow_confirmation_exemption: bool = False

    @field_validator("allowed_roles")
    @classmethod
    def roles_are_unique_and_nonblank(cls, value: list[str]) -> list[str]:
        if any(not role.strip() for role in value):
            raise ValueError("allowed_roles must not contain blank values")
        if len(set(value)) != len(value):
            raise ValueError("allowed_roles must be unique")
        return value


class ApplicationSkill(ServiceApplicationModel):
    """One declared action, query, knowledge path, or handoff."""

    key: str = Field(pattern=RESOURCE_KEY_PATTERN, max_length=64)
    type: SkillType
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=1000)
    enabled: bool = True
    connection_key: str | None = Field(default=None, pattern=RESOURCE_KEY_PATTERN, max_length=64)
    parameters: dict[str, Any] = Field(default_factory=dict)
    argument_mapping: dict[str, Any] = Field(default_factory=dict)
    result_mapping: dict[str, Any] = Field(default_factory=dict)
    result_schema: dict[str, Any] = Field(default_factory=dict)
    safety: SkillSafety = Field(default_factory=SkillSafety)
    write_operation: bool = False

    @field_validator("parameters", mode="before")
    @classmethod
    def default_parameters(cls, value: Any) -> Any:
        return {} if value is None else value

    @field_validator("parameters")
    @classmethod
    def parameters_are_closed_object_schema(cls, value: dict[str, Any]) -> dict[str, Any]:
        _validate_json_schema(value, code="invalid_skill_parameters_schema")
        if value.get("type") != "object" or value.get("additionalProperties") is not False:
            raise ValueError("skill parameters require type=object and additionalProperties=false")
        return value

    @field_validator("result_schema")
    @classmethod
    def result_schema_is_valid(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _validate_json_schema(value, code="invalid_skill_result_schema")

    @model_validator(mode="after")
    def safety_and_resource_references_are_consistent(self) -> Self:
        for label, mapping in (
            ("argument_mapping", self.argument_mapping),
            ("result_mapping", self.result_mapping),
        ):
            if any(not str(key).strip() for key in mapping):
                raise ValueError(f"{label} must not contain blank keys")
        if self.type in {SkillType.QUERY, SkillType.ACTION} and self.connection_key is None:
            raise ValueError(f"{self.type.value} skill requires connection_key")
        if self.write_operation and self.type != SkillType.ACTION:
            raise ValueError("only action skills may declare write_operation")
        if (
            self.type == SkillType.ACTION
            and self.write_operation
            and not self.safety.requires_confirmation
            and not self.safety.allow_confirmation_exemption
        ):
            raise ValueError(
                "write action requires requires_confirmation or allow_confirmation_exemption"
            )
        if self.safety.max_amount is not None and self.type != SkillType.ACTION:
            raise ValueError("max_amount is only valid for action skills")
        return self


class ApplicationRules(ServiceApplicationModel):
    """Application-wide fallback behavior when a skill cannot complete."""

    fallback: ErrorBehavior = ErrorBehavior.HANDOFF
    handoff_queue: str | None = Field(default=None, min_length=1, max_length=100)
    handoff_message: str = Field(default="", max_length=1000)
    require_confirmation: bool = True
    preview_write_enabled: bool = False
    validate_results: bool = True

    @field_validator("fallback", mode="before")
    @classmethod
    def normalise_legacy_fallback(cls, value: Any) -> Any:
        """Keep released payloads written with the former ``reply`` value valid."""

        if isinstance(value, str) and value.strip().lower() == "reply":
            return ErrorBehavior.FALLBACK
        return value

    @field_validator("handoff_queue", mode="before")
    @classmethod
    def normalise_blank_queue(cls, value: Any) -> Any:
        return None if isinstance(value, str) and not value.strip() else value

    @model_validator(mode="after")
    def handoff_fallback_has_queue(self) -> Self:
        if self.fallback == ErrorBehavior.HANDOFF and not self.handoff_queue:
            raise ValueError("handoff fallback requires handoff_queue")
        return self


class ConnectionMutableFields(ServiceApplicationModel):
    """Public connection fields. Secrets are never part of this contract."""

    name: str = Field(min_length=1, max_length=100)
    executor_kind: ConnectionExecutorKind
    endpoint: str | None = Field(default=None, max_length=2048)
    method: ConnectionMethod = ConnectionMethod.GET
    public_headers: dict[str, str] = Field(default_factory=dict)
    auth_kind: AuthKind = AuthKind.NONE
    timeout_seconds: int = Field(default=10, ge=1, le=60)
    max_response_bytes: int = Field(default=16000, ge=128, le=100000)
    config: dict[str, Any] = Field(default_factory=dict)

    @field_validator("public_headers")
    @classmethod
    def public_headers_are_safe(cls, value: dict[str, str]) -> dict[str, str]:
        return _validate_public_headers(value)

    @model_validator(mode="after")
    def endpoint_is_fixed(self) -> Self:
        _validate_connection_endpoint(
            self.executor_kind,
            self.endpoint,
            self.auth_kind,
            self.config,
        )
        return self


class ApplicationConnectionCreate(ConnectionMutableFields):
    key: str = Field(pattern=RESOURCE_KEY_PATTERN, max_length=64)


class ApplicationConnectionUpdate(ConnectionMutableFields):
    revision: int = Field(ge=1)


class ApplicationConnection(ApplicationConnectionCreate):
    revision: int = Field(default=1, ge=1)


ApplicationConnectionInput = ConnectionMutableFields


class ConnectionCredentialInput(ServiceApplicationModel):
    """A write-only credential payload; no value is returned by read APIs."""

    auth_kind: AuthKind
    secret: SecretStr
    header_name: str | None = Field(default=None, pattern=HEADER_NAME_PATTERN.pattern)

    @field_validator("secret")
    @classmethod
    def secret_is_nonblank(cls, value: SecretStr) -> SecretStr:
        text = value.get_secret_value()
        if not text.strip() or len(text) > 8192:
            raise ValueError("invalid connection credential")
        if any(ord(character) < 32 or ord(character) > 126 for character in text):
            raise ValueError("invalid connection credential")
        return value

    @model_validator(mode="after")
    def authentication_shape_is_valid(self) -> Self:
        if self.auth_kind == AuthKind.NONE:
            raise ValueError("credentials cannot use auth_kind=none")
        if self.auth_kind == AuthKind.CUSTOM and not self.header_name:
            raise ValueError("custom credentials require header_name")
        return self


class ConnectionCredentialStatus(ServiceApplicationModel):
    auth_kind: AuthKind
    credentials_configured: bool


class ApplicationChannelReference(ServiceApplicationModel):
    channel_id: UUID
    provider: str = Field(default="generic_webhook", min_length=1, max_length=40)


class ExperienceEntryKind(StrEnum):
    QUERY = "query"
    ACTION = "action"
    KNOWLEDGE = "knowledge"
    HANDOFF = "handoff"


class ExperienceCategoryIcon(StrEnum):
    MEMBER = "member"
    ORDER = "order"
    ACCOUNT = "account"
    SUPPORT = "support"


class ExperienceCategoryTone(StrEnum):
    VIOLET = "violet"
    BLUE = "blue"
    GREEN = "green"
    AMBER = "amber"


class ExperienceEntry(ServiceApplicationModel):
    """One customer-facing service entry backed by an application skill."""

    key: str = Field(pattern=RESOURCE_KEY_PATTERN, max_length=64)
    label: str = Field(min_length=1, max_length=40)
    kind: ExperienceEntryKind
    description: str = Field(default="", max_length=200)
    binding: str = Field(min_length=1, max_length=64)


class ExperienceCategory(ServiceApplicationModel):
    key: str = Field(pattern=RESOURCE_KEY_PATTERN, max_length=64)
    label: str = Field(min_length=1, max_length=40)
    icon: ExperienceCategoryIcon
    tone: ExperienceCategoryTone
    entries: list[ExperienceEntry] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def entry_keys_are_unique(self) -> Self:
        keys = [entry.key for entry in self.entries]
        duplicate = next((key for key in keys if keys.count(key) > 1), None)
        if duplicate is not None:
            raise ValueError(f"duplicate experience entry key: {duplicate}")
        return self


class ExperienceComponents(ServiceApplicationModel):
    """Whitelisted customer-interaction components rendered by the client."""

    quick_menu: bool = True
    suggestions: bool = True
    order_card: bool = True
    form: bool = True
    confirmation: bool = True
    receipt: bool = True
    handoff: bool = True


class ServiceExperienceConfig(ServiceApplicationModel):
    """Application-owned customer interaction configuration."""

    schema_version: Literal["v1"] = "v1"
    welcome_text: str = Field(
        default="您好，请问有什么可以帮您？",
        min_length=1,
        max_length=1000,
    )
    service_hours: str = Field(default="09:00-21:00", max_length=100)
    suggestion_sets: list[list[str]] = Field(default_factory=list, max_length=10)
    categories: list[ExperienceCategory] = Field(default_factory=list, max_length=8)
    components: ExperienceComponents = Field(default_factory=ExperienceComponents)

    @field_validator("suggestion_sets")
    @classmethod
    def suggestion_sets_are_bounded_and_nonblank(cls, value: list[list[str]]) -> list[list[str]]:
        for suggestions in value:
            if not 1 <= len(suggestions) <= 10:
                raise ValueError("each suggestion set requires 1-10 items")
            for suggestion in suggestions:
                if not suggestion.strip() or len(suggestion) > 200:
                    raise ValueError("experience suggestions must be nonblank and <=200 chars")
        return value

    @model_validator(mode="after")
    def category_and_entry_keys_are_globally_unique(self) -> Self:
        category_keys = [category.key for category in self.categories]
        duplicate_category = next(
            (key for key in category_keys if category_keys.count(key) > 1),
            None,
        )
        if duplicate_category is not None:
            raise ValueError(f"duplicate experience category key: {duplicate_category}")
        entry_keys = [entry.key for category in self.categories for entry in category.entries]
        duplicate_entry = next(
            (key for key in entry_keys if entry_keys.count(key) > 1),
            None,
        )
        if duplicate_entry is not None:
            raise ValueError(f"duplicate experience entry key: {duplicate_entry}")
        return self


class ServiceApplicationDraft(ServiceApplicationModel):
    """Editable application content stored in the JSONB draft."""

    schema_version: Literal["v2"] = "v2"
    skills: list[ApplicationSkill] = Field(default_factory=list, max_length=50)
    connections: list[ApplicationConnection] = Field(default_factory=list, max_length=20)
    rules: ApplicationRules = Field(
        default_factory=lambda: ApplicationRules(handoff_queue="customer-service")
    )
    channels: list[ApplicationChannelReference] = Field(default_factory=list, max_length=50)
    experience: ServiceExperienceConfig = Field(default_factory=ServiceExperienceConfig)

    @model_validator(mode="after")
    def keys_and_references_are_consistent(self) -> Self:
        for label, keys in (
            ("skill", [item.key for item in self.skills]),
            ("connection", [item.key for item in self.connections]),
            ("channel", [str(item.channel_id) for item in self.channels]),
        ):
            duplicate = next((key for key in keys if keys.count(key) > 1), None)
            if duplicate is not None:
                raise ValueError(f"duplicate {label} key: {duplicate}")
        connection_keys = {item.key for item in self.connections}
        for skill in self.skills:
            if skill.connection_key is not None and skill.connection_key not in connection_keys:
                raise ValueError(
                    f"skill {skill.key} references unknown connection {skill.connection_key}"
                )
        return self


class ServiceApplicationConfig(ServiceApplicationDraft):
    """Complete v2 application configuration used by create/update APIs."""

    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=1000)
    agent_id: UUID
    agent_version: int = Field(ge=1)


class ServiceApplicationCreate(ServiceApplicationConfig):
    key: str = Field(pattern=APPLICATION_KEY_PATTERN, max_length=64)

    @field_validator("key")
    @classmethod
    def user_application_key_is_not_reserved(cls, value: str) -> str:
        if value.startswith(RESERVED_EXAMPLE_PREFIX):
            raise ValueError("application key prefix example- is reserved")
        return value


class ServiceApplicationUpdate(ServiceApplicationModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=1000)
    agent_id: UUID
    agent_version: int = Field(ge=1)
    skills: list[ApplicationSkill] = Field(default_factory=list, max_length=50)
    connections: list[ApplicationConnection] = Field(default_factory=list, max_length=20)
    rules: ApplicationRules = Field(
        default_factory=lambda: ApplicationRules(handoff_queue="customer-service")
    )
    channels: list[ApplicationChannelReference] = Field(default_factory=list, max_length=50)
    experience: ServiceExperienceConfig | None = None
    revision: int = Field(ge=1)

    @model_validator(mode="after")
    def application_draft_is_valid(self) -> Self:
        ServiceApplicationDraft(
            skills=self.skills,
            connections=self.connections,
            rules=self.rules,
            channels=self.channels,
            **({"experience": self.experience} if self.experience is not None else {}),
        )
        return self


class ApplicationSkillCreate(ApplicationSkill):
    pass


class ApplicationSkillUpdate(ServiceApplicationModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=1000)
    type: SkillType
    enabled: bool = True
    connection_key: str | None = Field(default=None, pattern=RESOURCE_KEY_PATTERN, max_length=64)
    parameters: dict[str, Any] = Field(default_factory=dict)
    argument_mapping: dict[str, Any] = Field(default_factory=dict)
    result_mapping: dict[str, Any] = Field(default_factory=dict)
    result_schema: dict[str, Any] = Field(default_factory=dict)
    safety: SkillSafety = Field(default_factory=SkillSafety)
    write_operation: bool = False
    revision: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_as_skill(self) -> Self:
        ApplicationSkill(
            key="validation-key",
            **self.model_dump(exclude={"revision"}),
        )
        return self


class ReleaseAgent(ServiceApplicationModel):
    id: UUID
    version: int = Field(ge=1)


class ReleaseConnection(ConnectionMutableFields):
    key: str = Field(pattern=RESOURCE_KEY_PATTERN, max_length=64)
    credential_ref: UUID | None = None
    revision: int = Field(ge=1)
    digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")


class ReleaseSnapshot(ServiceApplicationModel):
    """The immutable, canonical payload stored in a published version."""

    schema_version: Literal["v2"] = "v2"
    agent: ReleaseAgent
    skills: list[ApplicationSkill] = Field(default_factory=list, max_length=50)
    connections: list[ReleaseConnection] = Field(default_factory=list, max_length=20)
    rules: ApplicationRules
    channels: list[ApplicationChannelReference] = Field(default_factory=list, max_length=50)
    experience: ServiceExperienceConfig = Field(default_factory=ServiceExperienceConfig)
    digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")

    @model_validator(mode="after")
    def references_are_consistent(self) -> Self:
        connection_keys = {item.key for item in self.connections}
        for skill in self.skills:
            if skill.connection_key is not None and skill.connection_key not in connection_keys:
                raise ValueError(
                    f"skill {skill.key} references unknown connection {connection_keys}"
                )
        return self


class ServiceApplicationVersion(ServiceApplicationModel):
    id: UUID
    application_id: UUID
    version: int = Field(ge=1)
    schema_version: Literal["v2"] = "v2"
    config: ReleaseSnapshot
    config_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    source_version: int | None = Field(default=None, ge=1)
    created_by: str
    created_at: datetime


class ApplicationTraceInput(ServiceApplicationModel):
    application_id: UUID
    application_version: int = Field(ge=1)
    conversation_id: UUID | None = None
    run_id: UUID | None = None
    agent_id: UUID
    agent_version: int = Field(ge=1)
    trace: dict[str, Any]


class ApplicationTrace(ApplicationTraceInput):
    id: UUID
    created_at: datetime


class PageRequest(ServiceApplicationModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=10, ge=1, le=100)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


# Descriptive aliases used by routes and frontend-facing adapters.
RuleConfig = ApplicationRules
SkillContract = ApplicationSkill
ConnectionContract = ApplicationConnection


__all__ = [
    "APPLICATION_KEY_PATTERN",
    "RESERVED_EXAMPLE_PREFIX",
    "ApplicationChannelReference",
    "ApplicationConnection",
    "ApplicationConnectionCreate",
    "ApplicationConnectionInput",
    "ApplicationConnectionUpdate",
    "ApplicationOrigin",
    "ApplicationRules",
    "ApplicationSkill",
    "ApplicationSkillCreate",
    "ApplicationSkillUpdate",
    "ApplicationStatus",
    "ApplicationTrace",
    "ApplicationTraceInput",
    "AuthKind",
    "ConnectionContract",
    "ConnectionCredentialInput",
    "ConnectionCredentialStatus",
    "ConnectionExecutorKind",
    "ConnectionMethod",
    "ErrorBehavior",
    "ExperienceCategory",
    "ExperienceCategoryIcon",
    "ExperienceCategoryTone",
    "ExperienceComponents",
    "ExperienceEntry",
    "ExperienceEntryKind",
    "IdempotencyMode",
    "PageRequest",
    "ReleaseAgent",
    "ReleaseConnection",
    "ReleaseSnapshot",
    "RuleConfig",
    "ServiceApplicationConfig",
    "ServiceApplicationCreate",
    "ServiceApplicationDraft",
    "ServiceApplicationModel",
    "ServiceApplicationUpdate",
    "ServiceApplicationVersion",
    "ServiceExperienceConfig",
    "SkillContract",
    "SkillSafety",
    "SkillType",
]
