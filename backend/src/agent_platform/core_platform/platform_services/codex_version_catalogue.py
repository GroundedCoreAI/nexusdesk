"""Read-only, TTL-cached view of the Codex version catalogue (issue #162).

The catalogue snapshot is produced offline by ``scripts/codex_versions.py``
(npm registry + installed CLI) and written to a local JSON file. This module
only reads that file; it never performs network I/O and never touches the
deployment allowlist, execution gate, credentials or tenant data. The catalogue
is informational — the allowlist in ``settings.codex_allowed_versions`` remains
the authoritative, fail-closed runtime gate.
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CATALOGUE_PATH = Path("data/codex_versions.json")
CACHE_TTL_SECONDS = 3600.0
MAX_ENTRIES = 50
_STABLE_VERSION = re.compile(r"^\d{1,5}\.\d{1,5}\.\d{1,5}$")
_SAFE_SOURCE = re.compile(r"^[a-z0-9][a-z0-9+._-]{0,39}$")


@dataclass(frozen=True)
class CatalogueEntry:
    """One non-sensitive catalogue row exposed by the flags endpoint."""

    version: str
    source: str
    verified: bool


@dataclass(frozen=True)
class _Cache:
    loaded_at: float
    entries: tuple[CatalogueEntry, ...]


_catalogue_path = DEFAULT_CATALOGUE_PATH
_cache: _Cache | None = None
_lock = threading.Lock()


def configure_catalogue_path(path: Path | str | None) -> None:
    """Point the reader at a snapshot file and invalidate any cached view.

    ``None`` restores the default path. Intended for deployment wiring and
    tests; it has no effect on the runtime allowlist or execution gate.
    """
    global _catalogue_path, _cache
    with _lock:
        _catalogue_path = Path(path) if path is not None else DEFAULT_CATALOGUE_PATH
        _cache = None


def clear_cache() -> None:
    """Force the next :func:`get_catalogue` to re-read the snapshot file."""
    global _cache
    with _lock:
        _cache = None


def _version_key(version: str) -> tuple[int, int, int]:
    return tuple(int(part) for part in version.split("."))  # type: ignore[return-value]


def _parse_document(document: object) -> tuple[CatalogueEntry, ...]:
    """Project a raw JSON document onto the safe, bounded entry shape.

    Unknown keys in the snapshot are ignored (never forwarded), malformed
    entries are dropped, and the result is de-duplicated and sorted so the API
    response is deterministic regardless of how the script ordered its output.
    """
    if not isinstance(document, dict):
        return ()
    raw_versions = document.get("versions")
    if not isinstance(raw_versions, list):
        return ()

    by_version: dict[str, CatalogueEntry] = {}
    for raw in raw_versions:
        if not isinstance(raw, dict):
            continue
        version = raw.get("version")
        source = raw.get("source")
        verified = raw.get("verified", False)
        if not isinstance(version, str) or not _STABLE_VERSION.fullmatch(version):
            continue
        if not isinstance(source, str) or not _SAFE_SOURCE.fullmatch(source):
            continue
        if not isinstance(verified, bool):
            continue
        by_version.setdefault(version, CatalogueEntry(version, source, verified))

    ordered = sorted(by_version.values(), key=lambda entry: _version_key(entry.version), reverse=True)
    return tuple(ordered[:MAX_ENTRIES])


def _load(path: Path) -> tuple[CatalogueEntry, ...]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ()
    return _parse_document(document)


def get_catalogue() -> Sequence[CatalogueEntry]:
    """Return the cached catalogue, reloading at most once per TTL window.

    A missing, malformed or unreadable snapshot degrades to an empty catalogue;
    this is informational metadata, so failing closed here cannot grant any
    execution permission.
    """
    global _cache
    now = time.monotonic()
    cached = _cache
    if cached is not None and now - cached.loaded_at < CACHE_TTL_SECONDS:
        return cached.entries
    with _lock:
        now = time.monotonic()
        cached = _cache
        if cached is None or now - cached.loaded_at >= CACHE_TTL_SECONDS:
            cached = _Cache(now, _load(_catalogue_path))
            _cache = cached
        return cached.entries


__all__ = [
    "CACHE_TTL_SECONDS",
    "DEFAULT_CATALOGUE_PATH",
    "MAX_ENTRIES",
    "CatalogueEntry",
    "clear_cache",
    "configure_catalogue_path",
    "get_catalogue",
]
