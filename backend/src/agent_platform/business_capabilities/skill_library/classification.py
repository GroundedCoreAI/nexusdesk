"""Advisory Skill classification: weight is a fact, risk is an opinion.

The library carries two independent labels, and keeping them independent is
the whole point:

``weight_class`` describes the artefact. It answers "can this deployment run
this Skill at all", so it is derived from files that actually exist (does the
Skill ship a package, does that package execute code) and never from what the
author typed. Faking ``declarative`` on an executable package would skip the
sandbox, which is why nothing here accepts an override.

``risk_level`` describes business blast radius. It is a judgement, so the
platform only offers a computed baseline (``risk_computed``) plus the signals
behind it (``risk_reasons``) and lets the author label the Skill however they
like. Nothing is blocked, gated, or approved because of this value.

Collapsing both into one grade would let a runtime requirement masquerade as a
business risk: a prompt-only Skill that moves money is lightweight and
high-risk, while a sandboxed image-resize script is heavy and low-risk.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

WeightClass = Literal["declarative", "packaged", "executable"]
RiskLevel = Literal["r0", "r1", "r2", "r3"]

WEIGHT_CLASSES: tuple[WeightClass, ...] = ("declarative", "packaged", "executable")
RISK_LEVELS: tuple[RiskLevel, ...] = ("r0", "r1", "r2", "r3")
DATA_SCOPES: tuple[str, ...] = ("model", "kb", "tool", "handoff", "money", "code")

_RISK_RANK: dict[str, int] = {level: index for index, level in enumerate(RISK_LEVELS)}

# Baseline blast radius per Skill type. ``action`` starts at r2 because it is
# the only type that performs effects; the release gate already forces
# confirmation on it, so the label matches the existing contract.
_BASELINE_BY_TYPE: dict[str, RiskLevel] = {
    "instruction": "r0",
    "knowledge": "r0",
    "query": "r1",
    "handoff": "r1",
    "action": "r2",
}

# Business threshold, not a technical constant. At or above this amount a Skill
# is labelled r3 so operators can see the money-moving Skills at a glance. It
# is deliberately advisory: exceeding it never blocks execution.
LARGE_AMOUNT_THRESHOLD = 5000.0


@dataclass(frozen=True)
class PackageFacts:
    """What the artefact physically contains, as verified by the importer."""

    present: bool = False
    has_scripts: bool = False
    entrypoint: str | None = None


@dataclass(frozen=True)
class RiskReason:
    """One structured signal and the level it implies, for explainability."""

    code: str
    level: RiskLevel


@dataclass(frozen=True)
class Classification:
    weight_class: WeightClass
    risk_level: RiskLevel
    risk_reasons: tuple[RiskReason, ...]
    data_scope: tuple[str, ...]

    def reasons_payload(self) -> list[dict[str, str]]:
        return [{"code": reason.code, "level": reason.level} for reason in self.risk_reasons]


def weight_of(package: PackageFacts | None) -> WeightClass:
    """Derive the weight class from package facts, never from a declaration."""

    if package is None or not package.present:
        return "declarative"
    if package.has_scripts or (package.entrypoint or "").strip():
        return "executable"
    return "packaged"


def classify_skill(definition: Any, package: PackageFacts | None = None) -> Classification:
    """Classify a draft definition plus its package facts. Pure, no IO."""

    payload = as_definition_payload(definition)
    skill_type = str(payload.get("type") or "instruction")
    dependencies = payload.get("dependencies")
    runtime = payload.get("runtime")
    if not isinstance(dependencies, dict):
        dependencies = {}
    if not isinstance(runtime, dict):
        runtime = {}

    weight = weight_of(package)
    level: RiskLevel = _BASELINE_BY_TYPE.get(skill_type, "r0")
    reasons: list[RiskReason] = []
    if level != "r0":
        reasons.append(RiskReason(f"type_{skill_type}", level))

    tools = [name for name in (dependencies.get("tool_names") or []) if name]
    knowledge = [item for item in (dependencies.get("knowledge_base_ids") or []) if item]
    handoff = dependencies.get("handoff_queue")
    has_handoff = isinstance(handoff, str) and bool(handoff.strip())
    amount = _amount(runtime.get("max_amount"))

    if tools:
        level = _raise_to(level, "r1")
        reasons.append(RiskReason("tool_capability", "r1"))
    if knowledge:
        level = _raise_to(level, "r1")
        reasons.append(RiskReason("knowledge_access", "r1"))
    if has_handoff:
        level = _raise_to(level, "r1")
        reasons.append(RiskReason("human_handoff", "r1"))
    if amount > 0:
        level = _raise_to(level, "r2")
        reasons.append(RiskReason("money_action", "r2"))
        if amount >= LARGE_AMOUNT_THRESHOLD:
            level = _raise_to(level, "r3")
            reasons.append(RiskReason("large_amount", "r3"))

    scope: list[str] = []
    if dependencies.get("model_profile_id"):
        scope.append("model")
    if knowledge:
        scope.append("kb")
    if tools:
        scope.append("tool")
    if has_handoff:
        scope.append("handoff")
    if amount > 0:
        scope.append("money")
    if weight == "executable":
        scope.append("code")

    return Classification(
        weight_class=weight,
        risk_level=level,
        risk_reasons=tuple(reasons),
        data_scope=tuple(scope),
    )


def as_definition_payload(definition: Any) -> dict[str, Any]:
    """Accept a validated model, the stored canonical dict, or raw JSON text."""

    if isinstance(definition, str):
        try:
            decoded = json.loads(definition)
        except ValueError:
            return {}
        return decoded if isinstance(decoded, dict) else {}
    if isinstance(definition, dict):
        return definition
    dump = getattr(definition, "model_dump", None)
    if dump is None:
        return {}
    payload = dump(mode="json")
    return payload if isinstance(payload, dict) else {}


def is_risk_level(value: Any) -> bool:
    return isinstance(value, str) and value in _RISK_RANK


def is_weight_class(value: Any) -> bool:
    return isinstance(value, str) and value in WEIGHT_CLASSES


def ordered_scope(values: Any) -> tuple[str, ...]:
    """Return the scope names in canonical order, ignoring unknown entries."""

    if not values:
        return ()
    present = {str(item) for item in values if item}
    return tuple(name for name in DATA_SCOPES if name in present)


def effective_risk(declared: Any, computed: RiskLevel) -> RiskLevel:
    """The stored label wins when it is valid; otherwise follow the computation."""

    return declared if is_risk_level(declared) else computed


def _raise_to(current: RiskLevel, floor: RiskLevel) -> RiskLevel:
    return floor if _RISK_RANK[floor] > _RISK_RANK[current] else current


def _amount(value: Any) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


__all__ = [
    "DATA_SCOPES",
    "LARGE_AMOUNT_THRESHOLD",
    "RISK_LEVELS",
    "WEIGHT_CLASSES",
    "Classification",
    "PackageFacts",
    "RiskLevel",
    "RiskReason",
    "WeightClass",
    "as_definition_payload",
    "classify_skill",
    "effective_risk",
    "is_risk_level",
    "is_weight_class",
    "ordered_scope",
    "weight_of",
]
