"""Bounded parsing and normalized mapping of Codex native JSON lines.

Two layers live here, deliberately separate:

* :class:`CodexEventParser` / :func:`parse_usage` own the provider-private wire
  format (newline-delimited JSON, bounded line size, explicit "unknown" usage).
* :class:`CodexEventMapper` owns the one legal projection into the public
  :class:`~...contracts.AgentEvent` envelope: ``codex.<native>`` event types,
  ``source="engine_native"``, monotone ``sequence``, a 32 KiB payload ceiling,
  and unknown native types preserved rather than dropped.

The mapper never sees raw stderr. A malformed line becomes a bounded
``PROTOCOL_ERROR`` whose message comes from the static error catalog, so an
execution's diagnostic text can never carry provider output.
"""

import json
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from ...contracts import (
    AdapterExecutionError,
    AgentEvent,
    ExecutionError,
    ExecutionErrorCategory,
    ExecutionErrorCode,
)
from .config import CodexProtocol

# The measured Stage A usage shape. All six keys are optional on the wire; a
# missing key is never zero-filled (an invented zero is fabricated evidence).
USAGE_FIELDS: tuple[str, ...] = (
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "cached_input_tokens",
    "cache_write_input_tokens",
    "reasoning_output_tokens",
)

# One public event payload is capped at 32 KiB of canonical JSON. Oversized
# payloads are truncated and marked instead of failing the execution.
EVENT_PAYLOAD_MAX_BYTES = 32 * 1024
# Prefix kept when truncating: the marker plus the partial JSON must fit too.
TRUNCATION_MARKER = "...[truncated]"

_CODEX_EVENT_PREFIX = "codex."

# D12: keys that must never reach a public ``AgentEvent.payload``. They are
# provider-private mechanics (OS identity, JSON-RPC envelope) and CM-05 forbids
# them on the public surface. Only TOP-LEVEL keys are removed: a nested
# ``item.id`` is a business identifier and stays, while a nested ``item.pid``
# would too - so the nested rule drops ``pid`` only where it identifies a
# process, never where it is ordinary item data.
_FORBIDDEN_PAYLOAD_KEYS: frozenset[str] = frozenset(
    {
        "pid",
        "process_id",
        "process_group_id",
        "pgid",
        "method",
        "jsonrpc",
        "id",
        "params",
        "stderr",
        "stdout",
        "auth",
        "token",
        "credential",
        "credential_ref",
        "environment",
        "env",
    }
)


class CodexNativeEvent(BaseModel):
    model_config = ConfigDict(extra="allow")

    event_type: str = Field(min_length=1, max_length=128)
    payload: dict[str, Any] = Field(default_factory=dict)


def parse_usage(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Extract usage without inventing zeroes when the provider omits it."""
    usage = payload.get("usage")
    if not isinstance(usage, Mapping):
        return {"status": "unknown"}
    result = {key: usage[key] for key in USAGE_FIELDS if key in usage}
    return result or {"status": "unknown"}


def normalize_event_type(native_type: str) -> str:
    """Project one native type onto the bounded ``EventType`` grammar.

    ``EventType`` requires ``^[a-z0-9]+(?:[._-][a-z0-9]+)*$``. Native names such
    as ``turn.completed`` already match; anything with a character outside the
    grammar is folded to ``_`` so an unexpected provider spelling can never make
    the public contract reject an execution.
    """
    folded = "".join(
        character
        if (character.isalnum() and character.islower())
        else ("." if character in "._-/" else "_")
        for character in native_type.strip().lower()
    )
    folded = folded.strip("._-")
    if not folded:
        folded = "unknown"
    event_type = f"{_CODEX_EVENT_PREFIX}{folded}"
    return event_type[:100].rstrip("._-")


class CodexEventParser:
    """Parse newline-delimited JSON with a strict size limit."""

    def __init__(self, *, max_line_bytes: int = 1_048_576) -> None:
        if max_line_bytes < 1:
            raise ValueError("max_line_bytes must be positive")
        self.max_line_bytes = max_line_bytes

    def parse_lines(self, lines: Iterable[bytes | str]) -> list[CodexNativeEvent]:
        events: list[CodexNativeEvent] = []
        for raw in lines:
            line = raw.encode() if isinstance(raw, str) else raw
            if len(line) > self.max_line_bytes:
                raise ValueError("Codex event exceeds size limit")
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("Malformed Codex event") from exc
            if not isinstance(value, Mapping):
                raise TypeError("Codex event must be an object")
            event_type = value.get("type") or value.get("event")
            if not isinstance(event_type, str) or not event_type:
                raise ValueError("Codex event type is missing")
            events.append(CodexNativeEvent(event_type=event_type, payload=dict(value)))
        return events


def _protocol_error() -> AdapterExecutionError:
    error = AdapterExecutionError(
        ExecutionError(
            category=ExecutionErrorCategory.PROTOCOL_ERROR,
            code=ExecutionErrorCode.PROTOCOL_ERROR,
        )
    )
    error.__cause__ = None
    error.__context__ = None
    error.__traceback__ = None
    error.__suppress_context__ = True
    return error


def _public_payload(payload: Mapping[str, Any]) -> dict[str, JsonValue]:
    """Strip provider-private keys from one payload (D12 / CM-05).

    The rule is a denylist of envelope and OS-identity keys rather than an
    allowlist, because the native event families are open ("unknown types are
    preserved, not dropped") and an allowlist would silently erase real event
    content. Only the top level is filtered, so nested ``item.id`` survives.
    """
    return {str(key): value for key, value in payload.items() if key not in _FORBIDDEN_PAYLOAD_KEYS}


def _bounded_payload(payload: Mapping[str, Any]) -> tuple[dict[str, JsonValue], bool]:
    """Sanitize, canonicalize under the 32 KiB ceiling, mark truncation."""
    sanitized = _public_payload(payload)
    try:
        encoded = json.dumps(dict(sanitized), sort_keys=True, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        raise _protocol_error() from None
    original_bytes = len(encoded.encode("utf-8"))
    if original_bytes <= EVENT_PAYLOAD_MAX_BYTES:
        return sanitized, False

    # The preview lives inside a wrapper object, so the wrapper's own JSON
    # overhead counts against the same ceiling. Shrink until the *serialized*
    # wrapper fits; the loop is bounded by the initial budget.
    budget = EVENT_PAYLOAD_MAX_BYTES - len(TRUNCATION_MARKER)
    while True:
        truncated: dict[str, JsonValue] = {
            "truncated": True,
            "original_bytes": original_bytes,
            "preview": encoded[: max(budget, 0)] + TRUNCATION_MARKER,
        }
        if len(json.dumps(truncated, separators=(",", ":")).encode("utf-8")) <= (
            EVENT_PAYLOAD_MAX_BYTES
        ):
            return truncated, True
        budget -= 256
        if budget <= 0:  # pragma: no cover - marker alone is far below the ceiling
            return {"truncated": True, "original_bytes": original_bytes}, True


class CodexEventMapper:
    """Map native events onto public ``AgentEvent`` envelopes, in order.

    The mapper is the single place that guarantees the identity invariants the
    Orchestrator's ``ensure_event_identity`` enforces: every event carries the
    request's execution key, the handle's ``provider_session_id``, a monotone
    sequence starting at 1, and a ``codex.*`` type inside the public grammar.
    """

    def __init__(
        self,
        *,
        execution_id: UUID,
        engine_id: str,
        protocol_id: str,
        adapter_version: str,
        engine_session_id: str | None,
        trace_id: str | None = None,
        clock: Any | None = None,
        id_factory: Any | None = None,
    ) -> None:
        self._execution_id = execution_id
        self._engine_id = engine_id
        self._protocol_id = protocol_id
        self._adapter_version = adapter_version
        self._engine_session_id = engine_session_id
        self._trace_id = trace_id
        self._clock = clock or (lambda: datetime.now(UTC))
        self._id_factory = id_factory or uuid4
        self._sequence = 0

    @classmethod
    def for_cli(
        cls,
        *,
        execution_id: UUID,
        engine_session_id: str | None,
        protocol: CodexProtocol = CodexProtocol.CLI_EXEC,
        trace_id: str | None = None,
    ) -> "CodexEventMapper":
        return cls(
            execution_id=execution_id,
            engine_id="codex",
            protocol_id=protocol.value,
            adapter_version="v1",
            engine_session_id=engine_session_id,
            trace_id=trace_id,
        )

    def map(self, native: CodexNativeEvent) -> AgentEvent:
        """Return one public event or raise the bounded ``PROTOCOL_ERROR``."""
        try:
            if not isinstance(native, CodexNativeEvent):
                raise TypeError
            payload, truncated = _bounded_payload(native.payload)
            if truncated:
                payload["native_type"] = native.event_type[:128]
            event = AgentEvent(
                event_id=self._id_factory(),
                execution_id=self._execution_id,
                engine_id=self._engine_id,
                protocol_id=self._protocol_id,
                adapter_version=self._adapter_version,
                engine_session_id=self._engine_session_id,
                sequence=self._sequence + 1,
                event_type=normalize_event_type(native.event_type),
                source="engine_native",
                timestamp=self._clock(),
                payload=payload,
                trace_id=self._trace_id,
            )
        except AdapterExecutionError:
            raise
        except Exception:  # noqa: BLE001 - arbitrary provider payloads fail closed.
            raise _protocol_error() from None
        self._sequence += 1
        return event

    def map_lines(self, lines: Iterable[bytes | str], *, max_line_bytes: int) -> list[AgentEvent]:
        """Parse then map; any malformed line aborts with ``PROTOCOL_ERROR``."""
        try:
            natives = CodexEventParser(max_line_bytes=max_line_bytes).parse_lines(lines)
        except (TypeError, ValueError):
            raise _protocol_error() from None
        return [self.map(native) for native in natives]
