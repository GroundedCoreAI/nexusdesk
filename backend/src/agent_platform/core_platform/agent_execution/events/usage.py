"""Execution usage normalization, stable source identities, and rebuild math.

The Execution usage ledger is separate from the model-gateway ``gateway_costs``
ledger. Missing data stays explicitly unknown; values are never zero-filled.
Corrections are ordinary source rows linked by ``supersedes_id``, so the
effective set is always rebuildable (02 FR-14, 03 §6.7).
"""

from collections.abc import Iterable, Mapping
from copy import deepcopy
from decimal import Decimal

from pydantic import JsonValue

TERMINAL_USAGE_SOURCE = "engine_terminal"
TERMINAL_USAGE_EVENT_ID = "result"
NATIVE_USAGE_SOURCE = "engine_native"
USAGE_SCHEMA_VERSION = "v1"
UNKNOWN_USAGE: dict[str, JsonValue] = {"status": "unknown"}


def normalize_usage(usage: Mapping[str, JsonValue] | None) -> dict[str, JsonValue]:
    """Return a defensive JSON copy; empty/absent becomes explicit unknown."""
    if usage is None:
        return dict(UNKNOWN_USAGE)
    if not isinstance(usage, Mapping):
        raise TypeError("usage must be a mapping")
    payload = deepcopy(dict(usage))
    if not payload:
        return dict(UNKNOWN_USAGE)
    return payload


def _is_unknown(usage: object) -> bool:
    return isinstance(usage, Mapping) and usage.get("status") == "unknown"


def _token_total(usage: object) -> int | float:
    if not isinstance(usage, Mapping):
        return 0
    value = usage.get("total_tokens")
    if isinstance(value, bool) or not isinstance(value, int | float | Decimal):
        return 0
    return value


def aggregate_effective_usage(records: Iterable[Mapping[str, object]]) -> dict[str, int | float]:
    """Rebuild the aggregate from effective leaves (rows never superseded).

    Superseded rows remain in the ledger for audit but never count twice.
    Unknown leaves are counted and contribute no invented zero quantity.
    """
    materialized = [dict(record) for record in records]
    superseded = {
        str(record["supersedes_id"])
        for record in materialized
        if record.get("supersedes_id") is not None
    }
    leaves = [record for record in materialized if str(record.get("id")) not in superseded]
    return {
        "records": len(materialized),
        "effective_records": len(leaves),
        "effective_total_tokens": sum(_token_total(record.get("usage")) for record in leaves),
        "effective_unknown_records": sum(
            1 for record in leaves if _is_unknown(record.get("usage"))
        ),
    }
