#!/usr/bin/env python3
"""Build a bounded Codex version catalogue from official npm metadata.

The catalogue is INFORMATIONAL. It tells the operator which Codex CLI versions
exist (npm ``@openai/codex``) and which one is installed in this container. It
never grants execution permission: the runtime allowlist
(``settings.codex_allowed_versions``) stays the authoritative, fail-closed gate
and is deliberately not read or weakened here.

Design constraints (issue #162):

* All network access happens in this script, never on an API request path. The
  backend reads the resulting JSON snapshot from a file with a TTL cache.
* Every network call has a hard timeout and any failure degrades to
  ``installed version only`` (or an empty catalogue when nothing is installed).
* The output is bounded, deterministic (newest stable version first) and
  carries a source label plus a generation timestamp. Only version strings and
  source labels are emitted — no paths, credentials, tenants or host details.

Usage::

    python scripts/codex_versions.py --output data/codex_versions.json
    python scripts/codex_versions.py --no-network            # offline fallback
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

PACKAGE = "@openai/codex"
DEFAULT_OUTPUT = Path("data/codex_versions.json")
DEFAULT_MAX_ENTRIES = 25
DEFAULT_TIMEOUT_SECONDS = 8.0
SOURCE_NPM = "npm-registry"
SOURCE_INSTALLED = "installed-cli"
SOURCE_NONE = "none"
SCHEMA_VERSION = 1

# Only plain stable semver entries enter the catalogue. npm publishes hundreds
# of platform-suffixed prereleases (``0.173.0-alpha.4-darwin-arm64``) that are
# not usable as a deployment version string; filtering them keeps the catalogue
# bounded and deterministic.
STABLE_VERSION = re.compile(r"^\d{1,5}\.\d{1,5}\.\d{1,5}$")
_ANY_VERSION = re.compile(r"\d{1,5}\.\d{1,5}\.\d{1,5}")

# Minimal runner contract: argv, timeout -> stdout. Anything else (non-zero
# exit, timeout, missing binary) is treated as "source unavailable".
Runner = Callable[[list[str], float], str]


def _default_runner(argv: Sequence[str], timeout: float) -> str:
    completed = subprocess.run(
        list(argv),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=True,
    )
    return completed.stdout


def _version_key(version: str) -> tuple[int, int, int]:
    return tuple(int(part) for part in version.split("."))  # type: ignore[return-value]


def parse_versions(raw: str) -> tuple[str, ...]:
    """Parse ``npm view <pkg> versions --json`` into stable versions, newest first.

    Accepts both the bare-array form and ``{"versions": [...]}``. Invalid JSON,
    unexpected shapes and platform-suffixed/prerelease strings are dropped
    rather than raising, so one bad upstream response can never take down a
    catalogue build.
    """
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return ()
    if isinstance(data, dict):
        items = data.get("versions")
        if not isinstance(items, list):
            return ()
    elif isinstance(data, list):
        items = data
    else:
        return ()
    versions = {
        value
        for value in items
        if isinstance(value, str) and STABLE_VERSION.fullmatch(value)
    }
    return tuple(sorted(versions, key=_version_key, reverse=True))


def parse_dist_tags(raw: str) -> dict[str, str]:
    """Parse ``npm view <pkg> dist-tags --json``; keep only stable tag targets."""
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        str(tag): value
        for tag, value in data.items()
        if isinstance(value, str) and STABLE_VERSION.fullmatch(value)
    }


def detect_installed_version(
    runner: Runner = _default_runner,
    *,
    codex_bin: str = "codex",
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> str | None:
    """Read the installed CLI version via ``<codex_bin> --version``.

    Returns ``None`` on any failure. Only the version string is used; the
    binary path is never written to the catalogue.
    """
    try:
        output = runner([codex_bin, "--version"], timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    for match in _ANY_VERSION.finditer(output or ""):
        token = match.group(0)
        if STABLE_VERSION.fullmatch(token):
            return token
    return None


def fetch_official_versions(
    runner: Runner = _default_runner,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> tuple[tuple[str, ...], str | None]:
    """Fetch npm versions and the ``latest`` dist-tag; each call fails soft."""
    versions: tuple[str, ...] = ()
    latest: str | None = None
    try:
        versions = parse_versions(runner(["npm", "view", PACKAGE, "versions", "--json"], timeout))
    except (OSError, subprocess.SubprocessError):
        versions = ()
    try:
        latest = parse_dist_tags(runner(["npm", "view", PACKAGE, "dist-tags", "--json"], timeout)).get("latest")
    except (OSError, subprocess.SubprocessError):
        latest = None
    return versions, latest


def build_catalogue(
    official_versions: Sequence[str],
    latest: str | None,
    installed_version: str | None,
    *,
    generated_at: datetime | None = None,
    max_entries: int = DEFAULT_MAX_ENTRIES,
) -> dict:
    """Assemble the bounded, deterministic catalogue document.

    npm-sourced entries are ``verified=True`` (confirmed to exist officially).
    An installed version that npm did not confirm is kept as ``verified=False``
    so the offline fallback is visible as such. De-duplication prefers the
    npm-confirmed entry.
    """
    moment = (generated_at or datetime.now(UTC)).astimezone(UTC)
    limit = max(1, min(int(max_entries), 200))

    official = list(dict.fromkeys(v for v in official_versions if STABLE_VERSION.fullmatch(v)))
    if latest and STABLE_VERSION.fullmatch(latest) and latest not in official:
        official.insert(0, latest)
    official = official[:limit]

    entries: list[dict] = [
        {"version": version, "source": SOURCE_NPM, "verified": True}
        for version in official
    ]
    installed = installed_version if installed_version and STABLE_VERSION.fullmatch(installed_version) else None
    if installed and not any(entry["version"] == installed for entry in entries):
        entries.append({"version": installed, "source": SOURCE_INSTALLED, "verified": False})

    entries.sort(key=lambda entry: _version_key(entry["version"]), reverse=True)
    entries = entries[:limit]

    if official:
        source = SOURCE_NPM + (f"+{SOURCE_INSTALLED}" if installed else "")
    elif installed:
        source = SOURCE_INSTALLED
    else:
        source = SOURCE_NONE

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": moment.isoformat().replace("+00:00", "Z"),
        "source": source,
        "latest": latest if latest and STABLE_VERSION.fullmatch(latest) else None,
        "versions": entries,
    }


def main(argv: Sequence[str] | None = None, runner: Runner | None = None) -> int:
    """CLI entry point. ``runner`` is injectable so tests never need the network."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="where to write the JSON catalogue")
    parser.add_argument("--max-entries", type=int, default=DEFAULT_MAX_ENTRIES)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--codex-bin", default="codex", help="installed CLI executable to probe")
    parser.add_argument("--no-network", action="store_true", help="skip npm; emit installed version only")
    args = parser.parse_args(argv)

    active_runner = runner or _default_runner
    if args.no_network:
        versions: tuple[str, ...] = ()
        latest = None
    else:
        versions, latest = fetch_official_versions(active_runner, timeout=args.timeout)
    installed = detect_installed_version(active_runner, codex_bin=args.codex_bin, timeout=args.timeout)
    catalogue = build_catalogue(
        versions,
        latest,
        installed,
        max_entries=args.max_entries,
    )

    payload = json.dumps(catalogue, ensure_ascii=False, indent=2, sort_keys=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
