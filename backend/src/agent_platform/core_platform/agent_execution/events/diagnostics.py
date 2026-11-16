"""Bounded, classified, rate-limited native-event parser diagnostics (T-06).

Diagnostics are additive records: the existing Codex parser still raises its
static protocol error and the React mapper still fails closed. Raw samples are
private and off by default; when temporarily enabled they are redacted and
byte-bounded. Continuous failures are rate-limited per Run/category, and this
module has no path that reports a diagnostic *about* a diagnostic, so failures
cannot recursively create an event storm (02 FR-15).
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

logger = logging.getLogger(__name__)

DIAGNOSTIC_CATEGORIES: frozenset[str] = frozenset(
    {"malformed", "unknown_schema", "unknown_type", "size_limit", "critical_terminal"}
)

_WINDOW_SECONDS = 60.0


@dataclass(frozen=True, slots=True)
class ParserDiagnostic:
    """One content-bounded diagnostic; no Secret, path, or raw stream."""

    category: str
    engine_id: str
    protocol_id: str
    adapter_version: str | None
    run_id: UUID | None
    native_event_id: str | None
    location: str | None
    sample: str | None
    created_at_posix: float

    def __post_init__(self) -> None:
        if self.category not in DIAGNOSTIC_CATEGORIES:
            raise ValueError("diagnostic category is outside the closed vocabulary")
        if not self.engine_id or not self.protocol_id:
            raise ValueError("diagnostic engine and protocol must be nonempty")
        if self.run_id is not None and not isinstance(self.run_id, UUID):
            raise ValueError("diagnostic run identity must be a UUID or None")
        if self.sample is not None and not isinstance(self.sample, str):
            raise ValueError("diagnostic sample must be a string or None")


class ParserDiagnosticCollector:
    """Classify, redact, bound, and rate-limit diagnostics for adapters."""

    def __init__(
        self,
        *,
        sink: Callable[[ParserDiagnostic], object] | None = None,
        redact: Callable[[str], str] | None = None,
        raw_samples_enabled: bool = False,
        max_sample_bytes: int = 1024,
        max_per_minute: int = 10,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if max_sample_bytes < 1:
            raise ValueError("max_sample_bytes must be positive")
        if max_per_minute < 1:
            raise ValueError("max_per_minute must be positive")
        self._sink = sink
        self._redact = redact
        self._raw_samples_enabled = raw_samples_enabled
        self._max_sample_bytes = max_sample_bytes
        self._max_per_minute = max_per_minute
        self._clock = clock or time.monotonic
        self._counts: dict[str, int] = {category: 0 for category in DIAGNOSTIC_CATEGORIES}
        self._suppressed = 0
        self._windows: dict[tuple[str, str], tuple[int, int]] = {}

    def report(
        self,
        category: str,
        *,
        engine_id: str,
        protocol_id: str,
        adapter_version: str | None = None,
        run_id: UUID | None = None,
        native_event_id: str | None = None,
        location: str | None = None,
        sample: str | None = None,
    ) -> ParserDiagnostic | None:
        """Emit one diagnostic unless the per-Run/category window is exhausted.

        A malformed category is rejected on construction; the caller's existing
        error path continues unchanged. Sink failure is swallowed and never
        produces another diagnostic.
        """
        if category not in DIAGNOSTIC_CATEGORIES:
            raise ValueError("diagnostic category is outside the closed vocabulary")
        window_key = (str(run_id), category)
        window = int(self._clock() // _WINDOW_SECONDS)
        previous = self._windows.get(window_key)
        if previous is not None and previous[0] == window:
            if previous[1] >= self._max_per_minute:
                self._suppressed += 1
                return None
            count = previous[1]
        else:
            count = 0
        self._windows[window_key] = (window, count + 1)

        diagnostic = ParserDiagnostic(
            category=category,
            engine_id=engine_id,
            protocol_id=protocol_id,
            adapter_version=adapter_version,
            run_id=run_id,
            native_event_id=native_event_id,
            location=location,
            sample=self._bounded_sample(sample),
            created_at_posix=self._clock(),
        )
        self._counts[category] += 1
        if self._sink is not None:
            try:
                self._sink(diagnostic)
            except Exception:  # noqa: BLE001 - sink isolation; no recursive report.
                logger.warning("parser diagnostic sink failed category=%s", category)
        return diagnostic

    def counters(self) -> dict[str, int]:
        """Low-cardinality counters for metrics/alerting."""
        return {**self._counts, "suppressed": self._suppressed}

    def _bounded_sample(self, sample: str | None) -> str | None:
        if sample is None or not self._raw_samples_enabled:
            return None
        # R-18(b): an enabled raw sample without a redactor fails closed — the
        # raw value is never retained verbatim (no canary may survive).
        if self._redact is None:
            return None
        try:
            text = self._redact(sample)
            encoded = text.encode("utf-8")[: self._max_sample_bytes]
            return encoded.decode("utf-8", "ignore")
        except Exception:  # noqa: BLE001 - unsafe diagnostics stay private.
            return None
