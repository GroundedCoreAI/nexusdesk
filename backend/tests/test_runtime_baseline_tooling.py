import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "runtime_baseline.py"
SPEC = importlib.util.spec_from_file_location("runtime_baseline", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
runtime_baseline = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime_baseline)
main = runtime_baseline.main


def write_xml(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def xml_case(
    name: str,
    *,
    classname: str = "tests.test_example",
    time: str = "0.01",
    child: str = "",
) -> str:
    return f'<testcase classname="{classname}" name="{name}" time="{time}">{child}</testcase>'


def invoke(capsys: pytest.CaptureFixture[str], *args: object) -> tuple[int, dict, str]:
    code = main([str(arg) for arg in args])
    captured = capsys.readouterr()
    assert captured.out.endswith("\n")
    return code, json.loads(captured.out), captured.err


def run_real_pytest(
    tmp_path: Path, source: str, *, report_all: bool = True
) -> tuple[subprocess.CompletedProcess, Path, Path]:
    test_file = tmp_path / "test_real_pytest.py"
    report = tmp_path / "real-pytest.xml"
    log = tmp_path / "real-pytest.log"
    test_file.write_text(source, encoding="utf-8")
    command = [
        sys.executable,
        "-m",
        "pytest",
        str(test_file),
        "-p",
        "no:cacheprovider",
        f"--junitxml={report}",
    ]
    if report_all:
        command.append("-rA")
    env = os.environ.copy()
    env.pop("PYTEST_ADDOPTS", None)
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    with log.open("w", encoding="utf-8") as output:
        completed = subprocess.run(
            command,
            cwd=tmp_path,
            env=env,
            stdout=output,
            stderr=subprocess.STDOUT,
            check=False,
        )
    return completed, report, log


def test_summary_aggregates_leaf_suites_without_double_counting(tmp_path, capsys):
    report = write_xml(
        tmp_path / "report.xml",
        """<testsuites tests="99" failures="88" errors="77" skipped="66" time="55">
          <testsuite name="one" tests="2" failures="1" errors="0" skipped="1" time="1.25">
            <testcase classname="pkg.test_a" name="test_pass" time="0.25" />
            <testcase classname="pkg.test_a" name="test_fail" time="1.0">
              <failure message="synthetic failure detail">sensitive stack text</failure>
            </testcase>
          </testsuite>
          <testsuite name="container" tests="1" failures="0" errors="0" skipped="0" time="2.5">
            <testsuite name="leaf" tests="1" failures="0" errors="0" skipped="0" time="2.5">
              <testcase classname="pkg.test_b" name="test_other" time="2.5" />
            </testsuite>
          </testsuite>
        </testsuites>""",
    )

    code, result, error = invoke(capsys, "summary", report)

    assert code == 0
    assert error == ""
    assert result["counts"] == {
        "errors": 0,
        "failures": 1,
        "skipped": 1,
        "tests": 3,
        "time": 3.75,
    }
    assert [(node["classname"], node["name"]) for node in result["nodes"]] == [
        ("pkg.test_a", "test_fail"),
        ("pkg.test_a", "test_pass"),
        ("pkg.test_b", "test_other"),
    ]
    assert result["nodes"][0]["outcome"] == "failed"
    assert "sensitive stack text" not in json.dumps(result)
    assert "synthetic failure detail" not in json.dumps(result)


def test_summary_single_suite_classifies_all_outcomes_and_skip_reasons(tmp_path, capsys):
    report = write_xml(
        tmp_path / "report.xml",
        f"""<testsuite name="suite" tests="6" failures="1" errors="1" skipped="3" time="0">
          {xml_case("test_pass")}
          {xml_case("test_error", child='<error message="hidden">hidden stack</error>')}
          {xml_case("test_skip", child='<skipped type="pytest.skip" message="not supported" />')}
          {xml_case("test_xfail", child='<skipped type="pytest.xfail" message="xfail reason: known" />')}
          {xml_case("test_xpass", child='<skipped message="[XPASS] now works" />')}
          {xml_case("test_fail", child='<failure message="hidden" />')}
        </testsuite>""",
    )

    code, result, _ = invoke(capsys, "summary", report)

    assert code == 0
    nodes = {node["name"]: node for node in result["nodes"]}
    assert {name: node["outcome"] for name, node in nodes.items()} == {
        "test_error": "error",
        "test_fail": "failed",
        "test_pass": "passed",
        "test_skip": "skipped",
        "test_xfail": "xfail",
        "test_xpass": "xpass",
    }
    assert nodes["test_pass"]["skip_reason"] is None
    assert nodes["test_skip"]["skip_reason"] == "not supported"
    assert nodes["test_xfail"]["skip_reason"] == "xfail reason: known"
    assert nodes["test_xpass"]["skip_reason"] == "[XPASS] now works"


def test_summary_classifies_pytest_strict_xpass_skipped_message(tmp_path, capsys):
    strict_xpass = xml_case(
        "test_strict_xpass",
        child='<skipped message="xfail-marked test passes unexpectedly" />',
    )
    report = write_xml(
        tmp_path / "strict-xpass.xml",
        f'<testsuite tests="1" failures="0" errors="0" skipped="1" time="0">'
        f"{strict_xpass}</testsuite>",
    )

    code, result, _ = invoke(capsys, "summary", report)

    assert code == 0
    assert result["nodes"][0]["outcome"] == "xpass"
    assert result["nodes"][0]["skip_reason"] == "xfail-marked test passes unexpectedly"


def test_summary_output_is_deterministic_and_mirrors_output_file(tmp_path, capsys):
    report = write_xml(
        tmp_path / "report.xml",
        f'<testsuite tests="1" failures="0" errors="0" skipped="0" time="0.01">'
        f"{xml_case('test_one')}</testsuite>",
    )
    output = tmp_path / "summary.json"

    code, result, _ = invoke(capsys, "summary", report, "--output", output)

    assert code == 0
    serialized = json.dumps(result, sort_keys=True) + "\n"
    assert output.read_text(encoding="utf-8") == serialized
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    "content,match",
    [
        (
            '<testsuite failures="0" errors="0" skipped="0" time="0" />',
            "missing integer count field 'tests'",
        ),
        (
            '<testsuite tests="1" failures="0" errors="0" skipped="0" time="nope" />',
            "time",
        ),
        (
            '<testsuite tests="1.5" failures="0" errors="0" skipped="0" time="0" />',
            "tests",
        ),
        (
            (
                '<testsuite tests="1" failures="0" errors="0" skipped="0" time="0">'
                '<testcase classname="" name="test_one" /></testsuite>'
            ),
            "identity",
        ),
        (
            (
                '<testsuite tests="1" failures="0" errors="0" skipped="0" time="0">'
                '<testcase classname="pkg" name="" /></testsuite>'
            ),
            "identity",
        ),
        (
            (
                '<testsuite tests="2" failures="0" errors="0" skipped="0" time="0">'
                '<testcase classname="pkg" name="test_same" />'
                '<testcase classname="pkg" name="test_same" /></testsuite>'
            ),
            "duplicate",
        ),
        (
            (
                '<testsuite tests="0" failures="0" errors="0" skipped="0" time="0">'
                '<testsuite tests="1" failures="0" errors="0" skipped="0" time="0">'
                '<testcase classname="pkg" name="test_nested" /></testsuite>'
                '<testcase classname="pkg" name="test_mixed" /></testsuite>'
            ),
            "non-leaf",
        ),
    ],
)
def test_summary_rejects_invalid_structure(tmp_path, capsys, content, match):
    report = write_xml(tmp_path / "invalid.xml", content)

    code = main(["summary", str(report)])
    captured = capsys.readouterr()

    assert code == 2
    assert captured.out == ""
    assert match.lower() in captured.err.lower()
    assert "Traceback" not in captured.err


def test_summary_rejects_malformed_xml_with_concise_error(tmp_path, capsys):
    report = write_xml(tmp_path / "invalid.xml", "<testsuite>")

    code = main(["summary", str(report)])
    captured = capsys.readouterr()

    assert code == 2
    assert captured.out == ""
    assert "XML" in captured.err
    assert "Traceback" not in captured.err


def test_real_pytest_strict_xpass_is_classified_as_xpass(tmp_path, capsys):
    completed, report, log = run_real_pytest(
        tmp_path,
        """import pytest


@pytest.mark.xfail(strict=True, reason="real strict XPASS")
def test_strict_xpass():
    assert True
""",
    )

    assert completed.returncode == 1
    code, result, error = invoke(capsys, "summary", report)

    assert code == 0
    assert error == ""
    assert result["nodes"][0]["name"] == "test_strict_xpass"
    assert result["nodes"][0]["outcome"] == "xpass"
    assert result["nodes"][0]["skip_reason"] is not None

    audit_code = main(["audit-log", str(log)])
    captured = capsys.readouterr()
    assert audit_code == 2
    assert captured.out == ""
    assert "PASSED evidence" in captured.err


def test_real_pytest_non_strict_xpass_requires_and_fails_log_audit(tmp_path, capsys):
    completed, report, log = run_real_pytest(
        tmp_path,
        """import pytest


@pytest.mark.xfail(strict=False, reason="real non-strict XPASS")
def test_non_strict_xpass():
    assert True
""",
    )
    output = tmp_path / "xpass-audit.json"

    assert completed.returncode == 0
    junit_result = runtime_baseline.summarize(report)
    assert junit_result["nodes"][0]["outcome"] == "passed"

    code, result, error = invoke(capsys, "audit-log", log, "--output", output)

    assert code == 1
    assert error == ""
    assert result["summary_entries"] == 1
    assert result["xpass_count"] == 1
    assert len(result["xpass"]) == 1
    assert result["xpass"][0].startswith("XPASS ")
    assert "::test_non_strict_xpass" in result["xpass"][0]
    assert output.read_text(encoding="utf-8") == json.dumps(result, sort_keys=True) + "\n"


def test_audit_log_cli_accepts_real_clean_pytest_log(tmp_path, capsys):
    completed, _, log = run_real_pytest(
        tmp_path,
        """def test_clean_pass():
    assert True
""",
    )

    assert completed.returncode == 0
    code, result, error = invoke(capsys, "audit-log", log)

    assert code == 0
    assert error == ""
    assert result == {"summary_entries": 1, "xpass": [], "xpass_count": 0}


def test_audit_log_accepts_pytest_long_duration_terminal_summary(tmp_path, capsys):
    passed = "\n".join(f"PASSED tests/test_formal.py::test_{index:03d}" for index in range(308))
    log = tmp_path / "long-duration.log"
    log.write_text(
        "=========================== short test summary info ============================\n"
        f"{passed}\n"
        "======================= 308 passed in 144.54s (0:02:24) ========================\n",
        encoding="utf-8",
    )
    output = tmp_path / "audit.json"

    code, result, error = invoke(capsys, "audit-log", log, "--output", output)

    assert code == 0
    assert error == ""
    assert result == {"summary_entries": 308, "xpass": [], "xpass_count": 0}
    assert output.read_text(encoding="utf-8") == json.dumps(result, sort_keys=True) + "\n"


def test_audit_log_rejects_malformed_long_duration_terminal_summary(tmp_path, capsys):
    log = tmp_path / "malformed-long-duration.log"
    log.write_text(
        "=========================== short test summary info ============================\n"
        "PASSED tests/test_formal.py::test_one\n"
        "======================== 1 passed in 144.54s (0:2:24) =========================\n",
        encoding="utf-8",
    )

    code = main(["audit-log", str(log)])
    captured = capsys.readouterr()

    assert code == 2
    assert captured.out == ""
    assert "missing its terminal summary" in captured.err
    assert "Traceback" not in captured.err


def test_audit_log_cli_rejects_real_pytest_log_without_summary_evidence(tmp_path):
    completed, _, log = run_real_pytest(
        tmp_path,
        """def test_clean_pass():
    assert True
""",
        report_all=False,
    )

    assert completed.returncode == 0
    audited = subprocess.run(
        [sys.executable, str(SCRIPT), "audit-log", str(log)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert audited.returncode == 2
    assert audited.stdout == ""
    assert "-rA" in audited.stderr
    assert "Traceback" not in audited.stderr


def comparison_reports(tmp_path: Path) -> tuple[Path, Path]:
    before = write_xml(
        tmp_path / "before.xml",
        f"""<testsuite tests="4" failures="0" errors="0" skipped="1" time="1">
          {xml_case("test_changed", time="0.1")}
          {xml_case("test_missing", time="0.2")}
          {xml_case("test_skip", child='<skipped message="old reason" />', time="0.3")}
          {xml_case("test_duration_only", time="0.4")}
        </testsuite>""",
    )
    after = write_xml(
        tmp_path / "after.xml",
        f"""<testsuite tests="4" failures="1" errors="0" skipped="1" time="9">
          {xml_case("test_changed", child='<failure message="sensitive marker">stack</failure>', time="8.1")}
          {xml_case("test_added", time="0.2")}
          {xml_case("test_skip", child='<skipped message="new reason" />', time="0.3")}
          {xml_case("test_duration_only", time="0.7")}
        </testsuite>""",
    )
    return before, after


def test_compare_reports_node_differences_and_count_metadata(tmp_path, capsys):
    before, after = comparison_reports(tmp_path)

    code, result, _ = invoke(capsys, "compare", before, after)

    assert code == 1
    assert result["added"] == [{"classname": "tests.test_example", "name": "test_added"}]
    assert result["missing"] == [{"classname": "tests.test_example", "name": "test_missing"}]
    assert result["outcome_changes"] == [
        {
            "after": "failed",
            "before": "passed",
            "classname": "tests.test_example",
            "name": "test_changed",
        }
    ]
    assert result["skip_reason_changes"] == [
        {
            "after": "new reason",
            "before": "old reason",
            "classname": "tests.test_example",
            "name": "test_skip",
        }
    ]
    assert result["before_counts"]["tests"] == 4
    assert result["after_counts"]["time"] == 9.0
    assert result["identical"] is False
    serialized = json.dumps(result)
    assert "sensitive marker" not in serialized
    assert "stack" not in serialized


def test_compare_ignores_duration_only_changes(tmp_path, capsys):
    before = write_xml(
        tmp_path / "before.xml",
        f'<testsuite tests="1" failures="0" errors="0" skipped="0" time="1">'
        f"{xml_case('test_same', time='1')}</testsuite>",
    )
    after = write_xml(
        tmp_path / "after.xml",
        f'<testsuite tests="1" failures="0" errors="0" skipped="0" time="20">'
        f"{xml_case('test_same', time='20')}</testsuite>",
    )
    output = tmp_path / "comparison.json"

    code, result, _ = invoke(capsys, "compare", before, after, "--output", output)

    assert code == 0
    assert result["identical"] is True
    assert result["added"] == result["missing"] == []
    assert result["outcome_changes"] == result["skip_reason_changes"] == []
    assert result["before_counts"]["time"] == 1.0
    assert result["after_counts"]["time"] == 20.0
    assert output.read_text(encoding="utf-8").endswith("\n")


def test_cli_subprocess_emits_json_and_node_diff_exit_code(tmp_path):
    before, after = comparison_reports(tmp_path)

    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "compare", str(before), str(after)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 1
    assert json.loads(completed.stdout)["identical"] is False
    assert completed.stdout.endswith("\n")
    assert completed.stderr == ""


@pytest.mark.parametrize("command", ["summary", "compare"])
def test_cli_unknown_xml_encoding_is_a_concise_format_error(tmp_path, command):
    report = tmp_path / "unknown-encoding.xml"
    report.write_bytes(
        b'<?xml version="1.0" encoding="x-unknown"?>'
        b'<testsuite tests="0" failures="0" errors="0" skipped="0" time="0" />'
    )
    arguments = [command, str(report)]
    if command == "compare":
        arguments.append(str(report))

    completed = subprocess.run(
        [sys.executable, str(SCRIPT), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert "encoding" in completed.stderr.lower()
    assert "Traceback" not in completed.stderr
    assert len(completed.stderr.splitlines()) == 1
