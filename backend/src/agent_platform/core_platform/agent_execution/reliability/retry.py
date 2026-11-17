"""Side-effect-aware retry classification (T-09, FR-10)."""

from dataclasses import dataclass
from typing import Literal

RetryPhase = Literal["pre_launch", "post_launch", "ambiguous", "outbox"]
RetryAction = Literal["retry", "manual", "forbid"]
_PHASES = frozenset({"pre_launch", "post_launch", "ambiguous", "outbox"})


@dataclass(frozen=True, slots=True)
class RetryInput:
    phase: RetryPhase
    side_effects: bool = False
    idempotency_key: str | None = None

    def __post_init__(self) -> None:
        if self.phase not in _PHASES:
            raise ValueError("retry phase is outside the closed vocabulary")
        if type(self.side_effects) is not bool:
            raise TypeError("side_effects must be boolean")


@dataclass(frozen=True, slots=True)
class RetryDecision:
    action: RetryAction
    reason: str


def classify_retry(value: RetryInput) -> RetryDecision:
    """Only proven pre-launch, side-effect-free work may auto-retry."""
    if value.phase == "pre_launch" and not value.side_effects:
        return RetryDecision("retry", "side_effect_free_pre_launch")
    if value.phase == "outbox":
        if value.idempotency_key and not value.side_effects:
            return RetryDecision("retry", "idempotent_outbox")
        return RetryDecision("forbid", "outbox_side_effect_unknown")
    if value.phase == "ambiguous":
        return RetryDecision("manual", "ambiguous_outcome")
    return RetryDecision("forbid", "side_effects_may_have_occurred")
