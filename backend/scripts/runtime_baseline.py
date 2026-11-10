"""Summarize/compare JUnit XML and audit pytest -rA logs for non-strict XPASS."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from pathlib import Path
from typing import Any


class BaselineFormatError(ValueError):
    """Report malformed or ambiguous JUnit input concisely."""


def _tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _integer(suite: ET.Element, field: str) -> int:
    raw = suite.get(field)
    if raw is None:
        raise BaselineFormatError(f"testsuite is missing integer count field {field!r}")
    try:
        return int(raw)
    except ValueError as exc:
        raise BaselineFormatError(
            f"testsuite field {field!r} must be an integer, got {raw!r}"
        ) from exc


def _time(suite: ET.Element) -> float:
    raw = suite.get("time")
    if raw is None:
        raise BaselineFormatError("testsuite is missing numeric field 'time'")
    try:
        value = float(raw)
    except ValueError as exc:
        raise BaselineFormatError(f"testsuite time must be numeric, got {raw!r}") from exc
    if not math.isfinite(value):
        raise BaselineFormatError("testsuite time must be finite")
    return value


def _leaf_suites(root: ET.Element) -> list[ET.Element]:
    if _tag(root) == "testsuite":
        suites = [root]
    elif _tag(root) == "testsuites":
        suites = [child for child in root if _tag(child) == "testsuite"]
    else:
        raise BaselineFormatError("JUnit root must be <testsuites> or <testsuite>")

    leaves = []

    def visit(suite: ET.Element) -> None:
        children = [child for child in suite if _tag(child) == "testsuite"]
        direct_cases = [child for child in suite if _tag(child) == "testcase"]
        if children:
            if direct_cases:
                raise BaselineFormatError(
                    "non-leaf testsuite cannot contain both testcase and testsuite children"
                )
            for child in children:
                visit(child)
        else:
            leaves.append(suite)

    for suite in suites:
        visit(suite)
    return leaves


def _skip_outcome(skipped: ET.Element) -> str:
    skip_type = skipped.get("type", "").strip().lower()
    message = skipped.get("message", "").strip().lower()
    if (
        skip_type == "pytest.xpass"
        or message == "xfail-marked test passes unexpectedly"
        or message.startswith("[xpass")
    ):
        return "xpass"
    if skip_type == "pytest.xfail" or message.startswith(("xfail", "[xfail]")):
        return "xfail"
    return "skipped"


def _testcase(case: ET.Element) -> dict[str, Any]:
    classname = case.get("classname")
    name = case.get("name")
    if classname is None or name is None or not classname.strip() or not name.strip():
        raise BaselineFormatError("every testcase requires a non-empty classname/name identity")

    outcomes = [child for child in case if _tag(child) in {"failure", "error", "skipped"}]
    if len(outcomes) > 1:
        raise BaselineFormatError(f"testcase {classname}.{name} has multiple outcome elements")

    outcome = "passed"
    skip_reason = None
    if outcomes:
        child = outcomes[0]
        kind = _tag(child)
        if kind == "failure":
            message = child.get("message", "")
            if message.strip().lower().startswith("[xpass(strict)]"):
                outcome = "xpass"
                skip_reason = message
            else:
                outcome = "failed"
        elif kind == "error":
            outcome = "error"
        else:
            outcome = _skip_outcome(child)
            skip_reason = child.get("message")

    raw_time = case.get("time", "0")
    try:
        duration = float(raw_time)
    except ValueError as exc:
        raise BaselineFormatError(f"testcase {classname}.{name} time must be numeric") from exc
    if not math.isfinite(duration):
        raise BaselineFormatError(f"testcase {classname}.{name} time must be finite")

    return {
        "classname": classname,
        "name": name,
        "outcome": outcome,
        "skip_reason": skip_reason,
        "time": duration,
    }


def summarize(path: str | Path) -> dict[str, Any]:
    """Parse one JUnit report into aggregate counts and sanitized test nodes."""

    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise BaselineFormatError(f"invalid JUnit XML: {exc.msg}") from exc
    except LookupError as exc:
        raise BaselineFormatError(f"invalid JUnit XML encoding: {exc}") from exc
    except OSError as exc:
        raise BaselineFormatError(f"cannot read JUnit XML: {exc.strerror or exc}") from exc

    leaves = _leaf_suites(root)
    counts = {
        "tests": sum(_integer(suite, "tests") for suite in leaves),
        "failures": sum(_integer(suite, "failures") for suite in leaves),
        "errors": sum(_integer(suite, "errors") for suite in leaves),
        "skipped": sum(_integer(suite, "skipped") for suite in leaves),
        "time": math.fsum(_time(suite) for suite in leaves),
    }

    nodes = []
    identities = set()
    for suite in leaves:
        for case in suite:
            if _tag(case) != "testcase":
                continue
            node = _testcase(case)
            identity = (node["classname"], node["name"])
            if identity in identities:
                raise BaselineFormatError(
                    f"duplicate testcase identity {identity[0]}.{identity[1]}"
                )
            identities.add(identity)
            nodes.append(node)
    nodes.sort(key=lambda node: (node["classname"], node["name"]))
    return {"counts": counts, "nodes": nodes}


_SHORT_SUMMARY_ENTRY = re.compile(r"^(PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)\s+")
_TERMINAL_SUMMARY = re.compile(r"^=+ .+ in \d+(?:\.\d+)?s(?: \(\d+:[0-5]\d:[0-5]\d\))? =+$")


def audit_log(path: str | Path) -> dict[str, Any]:
    """Find non-strict XPASS entries in a pytest log containing -rA evidence."""

    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise BaselineFormatError(f"cannot read pytest log: {exc.strerror or exc}") from exc
    except UnicodeError as exc:
        raise BaselineFormatError("pytest log must be valid UTF-8") from exc

    headers = [
        index for index, line in enumerate(lines) if line.strip("= ") == "short test summary info"
    ]
    if len(headers) != 1:
        raise BaselineFormatError("pytest log requires exactly one -rA short test summary section")

    entries = []
    terminal_summary_found = False
    for line in lines[headers[0] + 1 :]:
        if _TERMINAL_SUMMARY.fullmatch(line):
            terminal_summary_found = True
            break
        if _SHORT_SUMMARY_ENTRY.match(line):
            entries.append(line)
    if not terminal_summary_found:
        raise BaselineFormatError("pytest log is missing its terminal summary")
    if not entries:
        raise BaselineFormatError("pytest log has no -rA short-summary test entries")

    xpass = [line for line in entries if line.startswith("XPASS ")]
    if not xpass and not any(line.startswith("PASSED ") for line in entries):
        raise BaselineFormatError("clean XPASS audit requires -rA PASSED evidence")
    return {"summary_entries": len(entries), "xpass": xpass, "xpass_count": len(xpass)}


def _identity(node: dict[str, Any]) -> dict[str, str]:
    return {"classname": node["classname"], "name": node["name"]}


def compare(before_path: str | Path, after_path: str | Path) -> dict[str, Any]:
    """Compare test identities, outcomes, and skip reasons from two JUnit reports."""

    before = summarize(before_path)
    after = summarize(after_path)
    before_nodes = {(node["classname"], node["name"]): node for node in before["nodes"]}
    after_nodes = {(node["classname"], node["name"]): node for node in after["nodes"]}

    added = [
        _identity(after_nodes[key]) for key in sorted(after_nodes.keys() - before_nodes.keys())
    ]
    missing = [
        _identity(before_nodes[key]) for key in sorted(before_nodes.keys() - after_nodes.keys())
    ]
    outcome_changes = []
    skip_reason_changes = []
    for key in sorted(before_nodes.keys() & after_nodes.keys()):
        old = before_nodes[key]
        new = after_nodes[key]
        if old["outcome"] != new["outcome"]:
            outcome_changes.append(
                {**_identity(new), "before": old["outcome"], "after": new["outcome"]}
            )
        if old["skip_reason"] != new["skip_reason"]:
            skip_reason_changes.append(
                {**_identity(new), "before": old["skip_reason"], "after": new["skip_reason"]}
            )

    return {
        "before_counts": before["counts"],
        "after_counts": after["counts"],
        "added": added,
        "missing": missing,
        "outcome_changes": outcome_changes,
        "skip_reason_changes": skip_reason_changes,
        "identical": not (added or missing or outcome_changes or skip_reason_changes),
    }


def _write_result(result: dict[str, Any], output: str | None) -> None:
    serialized = json.dumps(result, sort_keys=True, allow_nan=False) + "\n"
    if output is not None:
        Path(output).write_text(serialized, encoding="utf-8")
    sys.stdout.write(serialized)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    for command in ("summary", "compare", "audit-log"):
        subcommand = subcommands.add_parser(command)
        if command == "summary":
            subcommand.add_argument("xml")
        elif command == "compare":
            subcommand.add_argument("before")
            subcommand.add_argument("after")
        else:
            subcommand.add_argument("log")
        subcommand.add_argument("--output")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Return 0 for clean input, 1 for differences/XPASS, and 2 for bad input."""

    args = _parser().parse_args(argv)
    try:
        if args.command == "summary":
            result = summarize(args.xml)
        elif args.command == "compare":
            result = compare(args.before, args.after)
        else:
            result = audit_log(args.log)
        _write_result(result, args.output)
    except (BaselineFormatError, OSError) as exc:
        sys.stderr.write(f"runtime_baseline: {exc}\n")
        return 2
    if args.command == "compare" and not result["identical"]:
        return 1
    if args.command == "audit-log" and result["xpass_count"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
