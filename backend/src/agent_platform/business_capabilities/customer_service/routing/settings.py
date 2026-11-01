"""Customer-service routing configuration.

These rules are business vocabulary, so they belong to the customer-service
capability rather than the platform-wide settings tree.
"""

import json
import logging
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .rules import normalize_text

logger = logging.getLogger(__name__)


class RoutingRule(BaseModel):
    """One explicit human-handoff rule."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(min_length=1)
    locale: str = Field(min_length=1)
    phrases: list[str] = Field(min_length=1)

    @field_validator("phrases", mode="before")
    @classmethod
    def decode_phrases(cls, value: object) -> object:
        """Accept a JSON array when the model is constructed directly."""

        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
        return value

    @field_validator("phrases")
    @classmethod
    def require_nonempty_normalized_phrases(cls, value: list[str]) -> list[str]:
        if any(not normalize_text(phrase) for phrase in value):
            raise ValueError("handoff phrases must not normalize to an empty string")
        return value


def default_handoff_rules() -> list[RoutingRule]:
    """Return a fresh copy of the Phase 1 default rules."""

    return [
        RoutingRule(
            id="zh_human_request_001",
            locale="zh-CN",
            phrases=["转人工", "人工客服", "客服"],
        ),
        RoutingRule(
            id="zhtw_human_request_001",
            locale="zh-TW",
            phrases=["轉人工"],
        ),
        RoutingRule(
            id="en_human_request_001",
            locale="en",
            phrases=["human", "real person", "representative", "human agent"],
        ),
        RoutingRule(
            id="hi_human_request_001",
            locale="hi",
            phrases=["मानव", "एजेंट"],
        ),
    ]


class CustomerServiceRoutingSettings(BaseSettings):
    """Environment-backed routing settings for the customer-service capability."""

    model_config = SettingsConfigDict(
        env_prefix="AGENT_CS_ROUTING_",
        extra="ignore",
    )

    trace_enabled: bool = False
    handoff_rules: list[RoutingRule] = Field(default_factory=default_handoff_rules)

    @field_validator("handoff_rules", mode="before")
    @classmethod
    def decode_handoff_rules(cls, value: object) -> object:
        """Allow direct construction from the same JSON form used by env vars."""

        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
        return value

    @model_validator(mode="after")
    def validate_unique_rules(self) -> Self:
        rule_ids: set[str] = set()
        phrases: dict[str, str] = {}
        for rule in self.handoff_rules:
            if rule.id in rule_ids:
                raise ValueError(f"duplicate routing rule id: {rule.id}")
            rule_ids.add(rule.id)
            for phrase in rule.phrases:
                normalized = normalize_text(phrase)
                prior = phrases.get(normalized)
                if prior is not None:
                    raise ValueError(
                        "normalized handoff phrase must be globally unique: "
                        f"{normalized!r} in {prior!r} and {rule.id!r}"
                    )
                phrases[normalized] = rule.id
        return self


def _default_settings() -> CustomerServiceRoutingSettings:
    # BaseSettings sources are evaluated before normal validation, so even
    # ``model_validate`` still tries to decode the malformed environment value.
    # The defaults here are already validated as RoutingRule instances.
    return CustomerServiceRoutingSettings.model_construct(
        trace_enabled=False,
        handoff_rules=default_handoff_rules(),
    )


def load_customer_service_routing_settings() -> CustomerServiceRoutingSettings:
    """Load settings, falling back to safe defaults on invalid configuration.

    A malformed environment variable must not prevent the service from
    starting. The fallback bypasses settings sources so the same invalid value
    cannot fail a second time.
    """

    try:
        return CustomerServiceRoutingSettings()
    except Exception as exc:  # noqa: BLE001 - startup must degrade to safe defaults
        logger.warning("Invalid customer-service routing settings; using defaults: %s", exc)
        return _default_settings()


__all__ = [
    "CustomerServiceRoutingSettings",
    "RoutingRule",
    "default_handoff_rules",
    "load_customer_service_routing_settings",
]
