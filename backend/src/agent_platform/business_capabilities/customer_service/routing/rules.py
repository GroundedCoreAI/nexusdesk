"""Text normalization and exact handoff-request matching."""

import unicodedata
from collections.abc import Iterable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .settings import CustomerServiceRoutingSettings, RoutingRule


def normalize_text(text: str) -> str:
    """Normalize text for deterministic exact matching.

    The final punctuation is deliberately removed one character at a time.
    Requiring a single trailing mark keeps ``human!`` matchable while avoiding
    accidental fuzzy matching for prose such as ``human being...``.
    """

    if not isinstance(text, str):
        raise TypeError("text must be a string")

    normalized = unicodedata.normalize("NFKC", text.strip()).casefold().strip()
    if normalized and unicodedata.category(normalized[-1]).startswith("P"):
        normalized = normalized[:-1].strip()
    return normalized


def match_handoff(
    message: str,
    routing_settings: "CustomerServiceRoutingSettings | Iterable[RoutingRule]",
) -> str | None:
    """Return the explicit rule id when the whole message matches a phrase.

    Matching is locale-agnostic: every configured rule participates. The
    settings validator guarantees normalized phrase uniqueness, so the return
    value does not depend on rule-list order.
    """

    rules = getattr(routing_settings, "handoff_rules", routing_settings)
    normalized = normalize_text(message)
    if not normalized:
        return None
    for rule in rules:
        if any(normalized == normalize_text(phrase) for phrase in rule.phrases):
            return rule.id
    return None


__all__ = ["match_handoff", "normalize_text"]
