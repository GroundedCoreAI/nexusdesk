"""Check catalogue, collector registration and shared value types.

The monitoring centre keeps three things apart on purpose:

* collectors only fetch raw data (``Collector``),
* judges only turn data into a status (``Judge``, pure functions in ``rules``),
* the service persists snapshots and compares them between rounds.

Registration is explicit: ``core_platform`` ships the platform-level checks and
the application composition root adds capability-level ones, mirroring the
contribution pattern used by tool defaults.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Literal

Status = Literal["pass", "warn", "fail", "not_configured", "unknown", "stale"]
Severity = Literal["P0", "P1", "P2", "P3"]
CheckKind = Literal["required", "conditional", "optional"]
Cadence = Literal["fast", "business", "integration", "probe", "daily"]

NON_PASS = ("warn", "fail")
NOTIFICATION_SEVERITIES = ("P0", "P1", "P2")


class CollectorError(Exception):
    """A collector could not produce data. Always becomes ``unknown``, never ``pass``."""

    def __init__(self, code: str, **evidence: object) -> None:
        self.code, self.evidence = code, evidence
        super().__init__(code)


@dataclass(frozen=True)
class Action:
    """Where an operator goes to act on a failing check."""

    label: str
    route: str


@dataclass(frozen=True)
class Check:
    id: str
    group: str
    kind: CheckKind
    severity: Severity
    cadence: Cadence
    action: Action
    # True: one row per tenant. False: a single deployment-wide row.
    scoped: bool = True
    # Short human label; the console translates it, the backend only supplies it.
    title: str = ""


@dataclass(frozen=True)
class CollectorContext:
    engine: object
    settings: object
    tenant: str


@dataclass(frozen=True)
class Judgment:
    status: Status
    summary: str
    evidence: dict = field(default_factory=dict)


Collector = Callable[[CollectorContext], Awaitable[dict]]
Judge = Callable[[dict, object], Judgment]


@dataclass(frozen=True)
class Registration:
    check: Check
    collect: Collector
    judge: Judge


class CheckRegistry:
    """Ordered, duplicate-rejecting catalogue owned by the composition root."""

    def __init__(self) -> None:
        self._registrations: list[Registration] = []
        self._by_id: dict[str, Registration] = {}

    def register(self, registration: Registration) -> None:
        check_id = registration.check.id
        if check_id in self._by_id:
            raise ValueError(f"duplicate check id: {check_id}")
        self._by_id[check_id] = registration
        self._registrations.append(registration)

    def register_all(self, registrations: tuple[Registration, ...]) -> None:
        for registration in registrations:
            self.register(registration)

    def get(self, check_id: str) -> Registration | None:
        return self._by_id.get(check_id)

    @property
    def registrations(self) -> tuple[Registration, ...]:
        return tuple(self._registrations)

    @property
    def checks(self) -> tuple[Check, ...]:
        return tuple(item.check for item in self._registrations)


def allowed_evidence(evidence: dict) -> dict:
    """Drop anything that is not a scalar metric.

    Secrets, prompts and stack traces must never reach a checklist response; the
    allow-list is by value type rather than by key so a new collector cannot leak
    a nested object by accident.
    """

    return {
        key: value
        for key, value in evidence.items()
        if isinstance(value, (str, int, float, bool)) or value is None
    }
