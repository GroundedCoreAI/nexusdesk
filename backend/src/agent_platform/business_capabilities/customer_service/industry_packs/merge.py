"""Deterministic three-way merging for compiled industry-pack scenarios.

The merge operates on the serialized :class:`ScenarioConfig` contract rather
than on model internals.  It is intentionally transport- and persistence-free:
callers can preview a merge, persist its plan, and apply the result later
without this module depending on database state.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Literal, TypeAlias

from pydantic import ValidationError

from ..scenarios.models import ScenarioConfig

MergeStatus: TypeAlias = Literal["clean", "conflicted", "blocked"]

_MISSING = object()
_KEYED_COLLECTIONS = frozenset({"entries", "facts", "decisions", "recommendations", "handlers"})


@dataclass(slots=True)
class MergeConflict:
    """One field or collection entry that could not be merged automatically."""

    path: str
    base: Any = None
    local: Any = None
    incoming: Any = None
    reason: str = "concurrent_change"

    @property
    def field(self) -> str:
        """Compatibility alias for callers that refer to conflicts by field."""

        return self.path


@dataclass(slots=True)
class MergeResult:
    """A validated merge result and the provenance needed for a preview UI."""

    merged_config: ScenarioConfig
    conflicts: list[MergeConflict] = field(default_factory=list)
    auto_merged_fields: list[str] = field(default_factory=list)
    kept_local_fields: list[str] = field(default_factory=list)
    incoming_fields: list[str] = field(default_factory=list)
    status: MergeStatus = "clean"


@dataclass(slots=True)
class _MergeState:
    conflicts: list[MergeConflict] = field(default_factory=list)
    auto_merged_fields: list[str] = field(default_factory=list)
    kept_local_fields: list[str] = field(default_factory=list)
    incoming_fields: list[str] = field(default_factory=list)

    def keep_local(self, path: str) -> None:
        _append_unique(self.kept_local_fields, path)
        _append_unique(self.auto_merged_fields, path)

    def take_incoming(self, path: str) -> None:
        _append_unique(self.incoming_fields, path)
        _append_unique(self.auto_merged_fields, path)


def three_way_merge(
    base: ScenarioConfig,
    local: ScenarioConfig,
    incoming: ScenarioConfig,
) -> MergeResult:
    """Merge an installed local scenario with a newer pack template.

    ``base`` is the template snapshot used by the current installation,
    ``local`` is the tenant-edited scenario, and ``incoming`` is the newly
    compiled template.  Changes that do not overlap merge automatically.
    Concurrent changes to the same field are reported as conflicts while the
    local value is retained.

    The returned configuration is always a validated ``ScenarioConfig``.  If a
    field-level merge produces an inconsistent cross-field configuration, the
    original local configuration is returned unchanged and the result is
    marked ``blocked`` for operator review.
    """

    if not (base.schema_version == local.schema_version == incoming.schema_version):
        conflict = MergeConflict(
            path="schema_version",
            base=base.schema_version,
            local=local.schema_version,
            incoming=incoming.schema_version,
            reason="schema_version_conflict",
        )
        return _blocked_result(local, conflict)

    state = _MergeState()
    merged_payload = _merge_value(
        base.model_dump(mode="json"),
        local.model_dump(mode="json"),
        incoming.model_dump(mode="json"),
        path="",
        field_name=None,
        state=state,
    )
    if not isinstance(merged_payload, dict):
        conflict = MergeConflict(
            path="$root",
            base=None,
            local=local.model_dump(mode="json"),
            incoming=incoming.model_dump(mode="json"),
            reason="merged_config_must_be_an_object",
        )
        return _blocked_result(local, conflict, state=state)

    try:
        merged_config = ScenarioConfig.model_validate(merged_payload)
    except ValidationError as exc:
        conflict = MergeConflict(
            path="$schema",
            base=None,
            local=local.model_dump(mode="json"),
            incoming=incoming.model_dump(mode="json"),
            reason=f"merged_config_invalid: {exc}",
        )
        return _blocked_result(local, conflict, state=state)

    return MergeResult(
        merged_config=merged_config,
        conflicts=state.conflicts,
        auto_merged_fields=state.auto_merged_fields,
        kept_local_fields=state.kept_local_fields,
        incoming_fields=state.incoming_fields,
        status="conflicted" if state.conflicts else "clean",
    )


def _blocked_result(
    local: ScenarioConfig,
    conflict: MergeConflict,
    *,
    state: _MergeState | None = None,
) -> MergeResult:
    state = state or _MergeState()
    return MergeResult(
        merged_config=local.model_copy(deep=True),
        conflicts=[*state.conflicts, conflict],
        auto_merged_fields=state.auto_merged_fields,
        kept_local_fields=state.kept_local_fields,
        incoming_fields=state.incoming_fields,
        status="blocked",
    )


def _merge_value(
    base: Any,
    local: Any,
    incoming: Any,
    *,
    path: str,
    field_name: str | None,
    state: _MergeState,
) -> Any:
    if _same(local, base):
        if not _same(incoming, base):
            state.take_incoming(path)
        return _copy(incoming)

    if _same(incoming, base):
        state.keep_local(path)
        return _copy(local)

    # Both sides made the same change.  Keep one copy rather than treating the
    # agreement as a conflict.
    if _same(local, incoming):
        return _copy(local)

    if all(_is_mapping(value) for value in (base, local, incoming)):
        return _merge_mapping(
            base,
            local,
            incoming,
            path=path,
            state=state,
        )

    if all(_is_sequence(value) for value in (base, local, incoming)):
        return _merge_sequence(
            base,
            local,
            incoming,
            path=path,
            field_name=field_name,
            state=state,
        )

    state.conflicts.append(
        MergeConflict(
            path=path,
            base=_conflict_value(base),
            local=_conflict_value(local),
            incoming=_conflict_value(incoming),
            reason="concurrent_change",
        )
    )
    return _copy(local)


def _merge_mapping(
    base: Mapping[str, Any],
    local: Mapping[str, Any],
    incoming: Mapping[str, Any],
    *,
    path: str,
    state: _MergeState,
) -> dict[str, Any]:
    ordered_keys: list[str] = []
    for mapping in (local, incoming, base):
        for key in mapping:
            if key not in ordered_keys:
                ordered_keys.append(key)

    merged: dict[str, Any] = {}
    for key in ordered_keys:
        child_path = _field_path(path, key)
        value = _merge_value(
            base.get(key, _MISSING),
            local.get(key, _MISSING),
            incoming.get(key, _MISSING),
            path=child_path,
            field_name=key,
            state=state,
        )
        if value is not _MISSING:
            merged[key] = value
    return merged


def _merge_sequence(
    base: Sequence[Any],
    local: Sequence[Any],
    incoming: Sequence[Any],
    *,
    path: str,
    field_name: str | None,
    state: _MergeState,
) -> list[Any]:
    base_items, base_labels = _index_sequence(base, field_name)
    local_items, local_labels = _index_sequence(local, field_name)
    incoming_items, incoming_labels = _index_sequence(incoming, field_name)

    ordered_identities: list[str] = []
    for identities in (local_items, incoming_items, base_items):
        for identity in identities:
            if identity not in ordered_identities:
                ordered_identities.append(identity)

    labels = {**base_labels, **local_labels, **incoming_labels}
    merged: list[Any] = []
    for identity in ordered_identities:
        item_path = _item_path(path, labels[identity])
        value = _merge_value(
            base_items.get(identity, _MISSING),
            local_items.get(identity, _MISSING),
            incoming_items.get(identity, _MISSING),
            path=item_path,
            field_name=field_name,
            state=state,
        )
        if value is not _MISSING:
            merged.append(value)
    return merged


def _index_sequence(
    items: Sequence[Any],
    field_name: str | None,
) -> tuple[dict[str, Any], dict[str, str]]:
    indexed: dict[str, Any] = {}
    labels: dict[str, str] = {}
    for item in items:
        identity, label = _item_identity(item, field_name)
        if identity not in indexed:
            indexed[identity] = item
            labels[identity] = label
    return indexed, labels


def _item_identity(item: Any, field_name: str | None) -> tuple[str, str]:
    if field_name in _KEYED_COLLECTIONS and _is_mapping(item):
        key = item.get("key")
        if key is not None:
            return f"key:{key}", str(key)

    if field_name == "options" and _is_mapping(item):
        value = item.get("value")
        if value is not None:
            return f"value:{value}", str(value)

    canonical = _stable_json(item)
    return f"value:{canonical}", _short_identity(canonical)


def _same(left: Any, right: Any) -> bool:
    if left is _MISSING or right is _MISSING:
        return left is right
    return _stable_json(left) == _stable_json(right)


def _stable_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    )


def _copy(value: Any) -> Any:
    return _MISSING if value is _MISSING else deepcopy(value)


def _conflict_value(value: Any) -> Any:
    return None if value is _MISSING else deepcopy(value)


def _is_mapping(value: Any) -> bool:
    return isinstance(value, Mapping)


def _is_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


def _field_path(parent: str, key: str) -> str:
    if not parent:
        return key
    if key.isidentifier():
        return f"{parent}.{key}"
    return f"{parent}[{json.dumps(key, ensure_ascii=False)}]"


def _item_path(parent: str, label: str) -> str:
    return f"{parent}[{label}]" if parent else f"[{label}]"


def _short_identity(value: str, limit: int = 80) -> str:
    if len(value) <= limit:
        return value
    return f"{value[: limit - 3]}..."


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


__all__ = [
    "MergeConflict",
    "MergeResult",
    "MergeStatus",
    "three_way_merge",
]
