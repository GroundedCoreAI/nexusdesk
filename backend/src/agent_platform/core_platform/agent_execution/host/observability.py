"""FR-9 observability records and alert sink (08 T15, 02 FR-9, 04 P4-UT-22).

One internal, structured alert surface spans the Supervisor, Registry,
RuntimeHost and the workspace sweeper: every anomaly (cleanup failure,
identity refusal, start failure, recovery batch, resource pressure, stalled
reconcile, over-quota Workdir) lands on an :class:`ObservabilityRecord` and is
delivered to an :class:`AlertSink`. Records carry only low-cardinality,
secret-free values: stable event names, reason codes from the frozen
``runtime_host_*`` / ``workdir_*`` vocabularies, correlation ids (Run, managed,
workdir, host) and scalar facts. Non-scalar payloads and free exception text
are rejected by construction (02 FR-9 failure row, C7).

Records are platform-internal like every other host DTO: they never join the
public contracts surface and never serialize into events or Run metadata.
"""

import logging
import time
from collections.abc import Callable
from typing import Annotated, Literal, Protocol, runtime_checkable
from uuid import UUID

from pydantic import Field, StringConstraints

from agent_platform.core_platform.agent_execution.contracts.base import ExecutionContractModel

# ---------------------------------------------------------------------------
# Stable event names (frozen for dashboards and grep; 04 P4-UT-22).
# ---------------------------------------------------------------------------

EVENT_START_REFUSED = "host.start.refused"
EVENT_START_FAILED = "host.start.failed"
EVENT_PROCESS_EXITED = "host.process.exited"
EVENT_CLEANUP_FAILED = "host.cleanup.failed"
EVENT_MANUAL_REMEDIATION = "host.recovery.manual_remediation"
EVENT_RECOVERY_BATCH = "host.recovery.batch"
EVENT_RECONCILE_DEFERRED = "host.reconcile.deferred"
EVENT_RECONCILE_STALLED = "host.reconcile.stalled"
EVENT_RESOURCE_PRESSURE = "host.resource.pressure"
EVENT_WORKDIR_OVER_QUOTA = "workspace.workdir.over_quota"
EVENT_WORKDIR_CLEANUP_FAILED = "workspace.workdir.cleanup_failed"
EVENT_SWEEP_BATCH = "workspace.sweep.batch"

OBSERVABILITY_EVENTS: frozenset[str] = frozenset(
    {
        EVENT_START_REFUSED,
        EVENT_START_FAILED,
        EVENT_PROCESS_EXITED,
        EVENT_CLEANUP_FAILED,
        EVENT_MANUAL_REMEDIATION,
        EVENT_RECOVERY_BATCH,
        EVENT_RECONCILE_DEFERRED,
        EVENT_RECONCILE_STALLED,
        EVENT_RESOURCE_PRESSURE,
        EVENT_WORKDIR_OVER_QUOTA,
        EVENT_WORKDIR_CLEANUP_FAILED,
        EVENT_SWEEP_BATCH,
    }
)

# Stable codes only: the host reason vocabulary or the workdir error
# vocabulary. Both are path-free, PID-free and secret-free by construction.
ObservabilityCode = Annotated[
    str,
    StringConstraints(pattern=r"^(?:runtime_host_[a-z0-9_]+|workdir_[a-z0-9_]+)$"),
]
ObservabilityEvent = Annotated[
    str,
    StringConstraints(min_length=4, max_length=80, pattern=r"^[a-z][a-z0-9_.]+$"),
]
# Scalar facts only; bounded strings keep exception text and payloads out of
# the alert surface (C7: the type cannot represent a leak).
FactValue = Annotated[str, StringConstraints(max_length=128)] | int | float
ScalarFacts = Annotated[
    dict[str, FactValue],
    Field(max_length=16),
]


class ObservabilityRecord(ExecutionContractModel):
    """One structured correlation/alert point (02 FR-9 output row).

    ``fields`` is a bounded map of scalar facts - the type system itself is
    the low-cardinality and no-object guard: bytes, paths, argv/env payloads
    or nested DTOs cannot be constructed into a record.
    """

    event: ObservabilityEvent
    severity: Literal["info", "warning", "error"]
    code: ObservabilityCode | None = None
    host_id: str | None = Field(default=None, max_length=200)
    run_id: UUID | None = None
    managed_id: UUID | None = None
    workdir_id: UUID | None = None
    fields: ScalarFacts = Field(default_factory=dict)


@runtime_checkable
class AlertSink(Protocol):
    """Non-blocking structured alert delivery (FR-9 failure row).

    ``emit`` must never raise into the supervision path and never performs
    I/O on the event loop; the logging sink is the production default and a
    recording sink serves tests and future alert routing (08 §6 defers
    routing/dashboards, not this seam).
    """

    def emit(self, record: ObservabilityRecord) -> None: ...


class LoggingAlertSink:
    """Production sink: one structured line per record, %-format, no f-strings."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger(
            "agent_platform.core_platform.agent_execution.host.observability"
        )

    def emit(self, record: ObservabilityRecord) -> None:
        parts = [
            f"event={record.event}",
            f"code={record.code if record.code is not None else '-'}",
            f"host_id={record.host_id or '-'}",
            f"run_id={record.run_id or '-'}",
            f"managed_id={record.managed_id or '-'}",
            f"workdir_id={record.workdir_id or '-'}",
        ]
        parts.extend(f"{key}={value}" for key, value in sorted(record.fields.items()))
        line = " ".join(parts)
        if record.severity == "error":
            self._logger.error("runtime host alert %s", line)
        elif record.severity == "warning":
            self._logger.warning("runtime host alert %s", line)
        else:
            self._logger.info("runtime host alert %s", line)


class RecordingAlertSink:
    """Test/audit sink: retains every emitted record in arrival order.

    Lives in the production module (not only tests) because the same recording
    contract pins the vocabulary in more than one Phase 4 suite; it performs
    no I/O and its memory is bounded by the caller's lifetime.
    """

    def __init__(self) -> None:
        self.records: list[ObservabilityRecord] = []

    def emit(self, record: ObservabilityRecord) -> None:
        self.records.append(record)

    def events(self) -> list[str]:
        return [record.event for record in self.records]


class ReconcileStallWatch:
    """Stalled-reconcile episode detection (04 P4-UT-22, 02 FR-9 failure row).

    The watch owns the monotonic deadline arithmetic so the composition
    module keeps its Phase 3 R-49 single-POSIX-wall-clock discipline (an
    AST pin forbids ``.monotonic`` there): callers report successes and
    failures, and exactly one error alert is emitted per stall episode once
    the grace factor times the interval has passed since the last success.
    """

    def __init__(
        self,
        *,
        interval_seconds: float,
        alert_sink: AlertSink | None = None,
        host_id: str | None = None,
        grace_factor: float = 3.0,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval must be positive")
        if grace_factor <= 0:
            raise ValueError("grace factor must be positive")
        self._interval = interval_seconds
        self._grace_factor = grace_factor
        self._alert_sink = alert_sink
        self._host_id = host_id
        self._monotonic = monotonic or time.monotonic
        self._last_success = self._monotonic()
        self._stalled = False

    def succeeded(self) -> None:
        self._last_success = self._monotonic()
        self._stalled = False

    def failed(self) -> None:
        if self._stalled:
            return  # one alert per episode, not per tick
        stale_seconds = self._monotonic() - self._last_success
        if stale_seconds <= self._grace_factor * self._interval:
            return
        self._stalled = True
        if self._alert_sink is not None:
            self._alert_sink.emit(
                ObservabilityRecord(
                    event=EVENT_RECONCILE_STALLED,
                    severity="error",
                    host_id=self._host_id,
                    fields={
                        "stale_seconds": round(stale_seconds, 3),
                        "interval_seconds": self._interval,
                    },
                )
            )
