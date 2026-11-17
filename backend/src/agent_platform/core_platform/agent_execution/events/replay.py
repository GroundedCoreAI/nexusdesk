"""SSE replay cursor, retention-gap, and reserved envelope helpers (T-05).

The durable Event Store remains the replay source; ``runtime_events.seq`` stays
the SSE ``id``. This module adds only the explicitly reviewed wire addition:
the reserved ``_execution`` object was inserted beside every existing data key.
Nothing here reorders history, resets cursors silently, or turns transient
``model.delta`` frames into replayable events.
"""

from collections.abc import Mapping
from copy import deepcopy

from pydantic import JsonValue

MAX_CURSOR = 2147483647


def resolve_cursor(after: int, last_event_id: str | None) -> int:
    """Merge ``after`` and ``Last-Event-ID`` by the strict maximum.

    Raises ``ValueError`` for any malformed or out-of-range cursor; the route
    maps it to the existing 400 ``invalid_last_event_id`` contract.
    """
    if type(after) is not int or after < 0 or after > MAX_CURSOR:
        raise ValueError("invalid_after")
    if last_event_id is None:
        return after
    if not isinstance(last_event_id, str):
        raise TypeError("invalid_last_event_id")
    try:
        header = int(last_event_id)
    except (TypeError, ValueError):
        raise ValueError("invalid_last_event_id") from None
    if header < 0 or header > MAX_CURSOR:
        raise ValueError("invalid_last_event_id")
    return max(after, header)


def retention_gap(cursor: int, floor: int) -> bool:
    """True only when a positive floor proves events were removed."""
    if type(cursor) is not int or type(floor) is not int:
        raise TypeError("cursor and retention floor must be integers")
    return floor > 0 and cursor < floor


def sse_payload(row: Mapping[str, object], *, redactor=None) -> dict[str, JsonValue]:
    """Keep every stored business key and append only reserved metadata.

    A stored ``_execution`` key (untrusted or historical) is replaced by the
    trusted identity derived from the durable columns, so a client cannot
    forge the reserved object through event payload content.
    """
    data = row.get("data")
    if redactor is not None:
        # R-18(b): redact at the real SSE emission seam, not just the helper.
        payload: dict[str, JsonValue] = (
            redactor.redact_structure(data) if isinstance(data, dict) else {}
        )
    else:
        payload = deepcopy(data) if isinstance(data, dict) else {}
    event_id = row.get("event_id")
    payload["_execution"] = {
        "event_id": None if event_id is None else str(event_id),
        "schema_version": row.get("schema_version") or "v1",
        "source": row.get("source") or "platform",
        "trace_id": row.get("trace_id"),
    }
    return payload
