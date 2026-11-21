"""Unit tests for the Codex version catalogue builder (issue #162).

The script is the only component allowed to touch npm at build time. These
tests inject a fake runner so they cover parsing, deterministic bounding and
offline degradation without any network or installed CLI.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "codex_versions.py"
SPEC = importlib.util.spec_from_file_location("codex_versions", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
codex_versions = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(codex_versions)

NOW = datetime(2026, 11, 21, 12, 0, tzinfo=UTC)


@pytest.fixture
def out_dir() -> Path:
    """A throwaway directory under the gitignored ``backend/work`` tree.

    pytest's ``tmp_path`` fixture cannot create its base directory under the
    sandboxed host here, so use the repository's ignored work area instead.
    """
    path = Path(__file__).parents[1] / "work" / "issue162-catalogue"
    path.mkdir(parents=True, exist_ok=True)
    return path


def runner_map(responses: dict[str, str]):
    """Build a fake runner keyed by the first two argv tokens."""

    def run(argv: list[str], timeout: float) -> str:
        if argv[:2] == ["npm", "view"]:
            return responses.get(" ".join(argv[3:]), "")
        if argv[-1:] == ["--version"]:
            return responses.get("codex", "")
        raise AssertionError(f"unexpected runner call: {argv}")

    return run


def test_parse_versions_filters_platform_suffixes_and_sorts_newest_first() -> None:
    raw = json.dumps(
        [
            "0.169.0",
            "0.171.0",
            "0.173.0-alpha.4-darwin-arm64",
            "0.168.0",
            "0.169.0",
            "not-a-version",
        ]
    )
    assert codex_versions.parse_versions(raw) == ("0.171.0", "0.169.0", "0.168.0")


def test_parse_versions_accepts_wrapped_shape_and_rejects_bad_shapes() -> None:
    assert codex_versions.parse_versions('{"versions":["0.170.0","0.169.1"]}') == (
        "0.170.0",
        "0.169.1",
    )
    assert codex_versions.parse_versions("not json") == ()
    assert codex_versions.parse_versions("{}") == ()
    assert codex_versions.parse_versions('{"versions":"0.169.0"}') == ()


def test_parse_dist_tags_keeps_only_stable_targets() -> None:
    raw = json.dumps({"latest": "0.171.0", "beta": "0.172.0-alpha.1", "stable": "0.169.0"})
    assert codex_versions.parse_dist_tags(raw) == {"latest": "0.171.0", "stable": "0.169.0"}


def test_detect_installed_version_reads_semver_and_fails_soft() -> None:
    assert codex_versions.detect_installed_version(lambda argv, timeout: "Codex CLI 0.169.0\n") == "0.169.0"
    assert codex_versions.detect_installed_version(lambda argv, timeout: "no version here") is None

    def broken(argv: list[str], timeout: float) -> str:
        raise subprocess.TimeoutExpired(argv, timeout)

    assert codex_versions.detect_installed_version(broken) is None


def test_fetch_official_versions_degrades_when_npm_fails() -> None:
    def broken(argv: list[str], timeout: float) -> str:
        raise subprocess.CalledProcessError(1, argv)

    versions, latest = codex_versions.fetch_official_versions(broken)
    assert versions == ()
    assert latest is None


def test_fetch_official_versions_uses_versions_and_latest_tag() -> None:
    run = runner_map(
        {
            "versions --json": json.dumps(["0.169.0", "0.171.0"]),
            "dist-tags --json": json.dumps({"latest": "0.171.0"}),
        }
    )
    versions, latest = codex_versions.fetch_official_versions(run)
    assert versions == ("0.171.0", "0.169.0")
    assert latest == "0.171.0"


def test_build_catalogue_offline_fallback_is_installed_only_unverified() -> None:
    catalogue = codex_versions.build_catalogue((), None, "0.169.0", generated_at=NOW)
    assert catalogue["source"] == "installed-cli"
    assert catalogue["latest"] is None
    assert catalogue["generated_at"] == "2026-11-21T12:00:00Z"
    assert catalogue["versions"] == [
        {"version": "0.169.0", "source": "installed-cli", "verified": False}
    ]


def test_build_catalogue_empty_when_offline_and_nothing_installed() -> None:
    catalogue = codex_versions.build_catalogue((), None, None, generated_at=NOW)
    assert catalogue["source"] == "none"
    assert catalogue["versions"] == []


def test_build_catalogue_is_bounded_deterministic_and_deduplicates() -> None:
    official = tuple(f"0.{100 - index}.0" for index in range(30)) + ("0.169.0",)
    catalogue = codex_versions.build_catalogue(
        official,
        "0.171.0",
        "0.169.0",
        generated_at=NOW,
        max_entries=5,
    )
    versions = catalogue["versions"]
    assert len(versions) == 5
    # The installed 0.169.0 is kept even when the npm window is capped, and the
    # final sort is by numeric version so the result is deterministic.
    assert [entry["version"] for entry in versions] == [
        "0.171.0",
        "0.169.0",
        "0.100.0",
        "0.99.0",
        "0.98.0",
    ]
    # The npm-confirmed window entries are verified; the installed 0.169.0 was
    # pushed out of that window and is therefore carried as an unverified
    # installed entry. This is why the frontend must treat the allowlist (not
    # this informational flag) as the authoritative runtime gate.
    by_version = {entry["version"]: entry for entry in versions}
    assert by_version["0.169.0"]["verified"] is False
    assert by_version["0.169.0"]["source"] == "installed-cli"
    assert all(
        entry["verified"] is True and entry["source"] == "npm-registry"
        for version, entry in by_version.items()
        if version != "0.169.0"
    )
    # Re-running with the same inputs yields byte-identical output.
    assert codex_versions.build_catalogue(
        official, "0.171.0", "0.169.0", generated_at=NOW, max_entries=5
    ) == catalogue


def test_build_catalogue_marks_installed_only_version_unverified() -> None:
    catalogue = codex_versions.build_catalogue(
        ("0.169.0",), None, "0.999.0", generated_at=NOW
    )
    by_version = {entry["version"]: entry for entry in catalogue["versions"]}
    assert by_version["0.169.0"]["verified"] is True
    assert by_version["0.999.0"] == {
        "version": "0.999.0",
        "source": "installed-cli",
        "verified": False,
    }
    assert catalogue["source"] == "npm-registry+installed-cli"


def test_main_no_network_writes_bounded_catalogue_without_secrets(out_dir: Path) -> None:
    output = out_dir / "nested" / "catalogue-no-network.json"
    run = runner_map({"codex": "Codex CLI 0.169.0\n"})

    code = codex_versions.main(
        ["--no-network", "--output", str(output), "--max-entries", "3"],
        runner=run,
    )
    assert code == 0
    document = json.loads(output.read_text(encoding="utf-8"))
    assert set(document) == {"schema_version", "generated_at", "source", "latest", "versions"}
    assert document["versions"] == [
        {"version": "0.169.0", "source": "installed-cli", "verified": False}
    ]
    serialized = output.read_text(encoding="utf-8").lower()
    for marker in ("token", "secret", "tenant", "/opt", "/usr", "credential"):
        assert marker not in serialized


def test_main_skips_npm_entirely_when_no_network_flag(out_dir: Path) -> None:
    def forbid_network(argv: list[str], timeout: float) -> str:
        if argv[:2] == ["npm", "view"]:
            raise AssertionError("--no-network must not call npm")
        return "codex 0.169.0"

    code = codex_versions.main(
        ["--no-network", "--output", str(out_dir / "catalogue-offline.json")],
        runner=forbid_network,
    )
    assert code == 0
