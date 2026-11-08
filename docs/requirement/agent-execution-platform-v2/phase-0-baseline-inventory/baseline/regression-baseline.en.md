# Phase 0 Baseline · Regression Environment, Results, and Reproduction Commands

> Status: The corrected local formal double run passed 310-node comparison and both XPASS log audits; clean CI, real samples, final commit evidence, and acceptance are not preclaimed as passed
> Current-state target commit: `c6c47dec39025ebd4d1176c1e9925bac9c99c4fd`
> Baseline artifacts: formally tested **uncommitted** feature-branch working tree, identified by base metadata and deterministic tree hash; no fictitious artifact SHA is assigned, and final committed-artifact evidence remains `pending_commit`
> Initial record: 2026-11-07; T8 expansion: 2026-11-08; T9 formal-result and corrected-double-run update: 2026-11-08
> Basis: `02-requirements.md` (FR-1–FR-6, AC-1–AC-6) and `04-test-plan.md`
> Evidence directory: local `/tmp/nexusdesk-phase0-*` (secrets, database connection strings, and large temporary logs are not committed)

## 1. Environment Fingerprint

| Item | Verified value |
|---|---|
| Branch | `feat/agent-execution-platform-v2-phase0` |
| Python | 3.11.9 |
| uv | 0.11.3 (`45da18ac3`) |
| Container image | `pgvector/pgvector:pg17` |
| PostgreSQL | 17.11 (Debian 17.11-1.pgdg12+2) |
| Database isolation | Dedicated Phase 0 container/databases; each formal run starts with its own empty database migrated to head |
| Migration head | `0057_industry_pack_runtime` |
| Formal-database preparation and use | Run 1 and Run 2 each used a separate local empty database, migrated and verified at `0057_industry_pack_runtime` before its tests and then actually used by the formal run |
| External models | Not on the deterministic mandatory path |
| Connection information | Stored only in a permission-restricted local environment file; commands reference variable names without recording values |

The complete dependency lock is `backend/uv.lock`. `pytest-cov` belongs only to the dev group and is not a production runtime dependency. Local database names are non-secret identifiers but need not be recorded here; no URL, username, or password enters the documents, log summaries, or command output.

## 2. Existing-Target Calibration Results

These checks preceded the new Phase 0 tests/tools and establish existing behavior and environment-calibration evidence only.

| Run/check | Actual command or scope | Result | Decision |
|---|---|---|---|
| Empty-database calibration | Existing `test_runtime_engine.py`, `test_runtime_postgres.py`, `test_runtime_availability.py`, `test_runtime_scope.py` | 21 passed, 10 failed, 10 errors in 7.22s | Unmigrated empty database lacked `runtime_runs`; **excluded from the formal double run**, raw log retained as `/tmp/nexusdesk-phase0-existing-run0.log` |
| Alembic calibration | Set only `TEST_DATABASE_URL` | Connection to default `127.0.0.1:5432` failed | Confirmed Alembic reads `AGENT_DATABASE_URL` through Settings; no connection string recorded |
| Corrected migration environment | Set `AGENT_DATABASE_URL` for the dedicated empty database, then `alembic upgrade head` | Migration succeeded | Pytest separately receives the same dedicated database as `TEST_DATABASE_URL` |
| Existing Runtime baseline | Same four existing suites against the migrated database | **31 passed in 4.95s** | `/tmp/nexusdesk-phase0-existing-run1.log` and corresponding JUnit XML |
| Ruff lint | `uv run --directory backend ruff check src tests` | Passed | Target current-state code |
| Ruff format | `uv run --directory backend ruff format --check src` | Existing `seed_memory_*` and similar files fail formatting | Recorded P3; no bulk formatting of unrelated production scripts in Phase 0 |
| Architecture gate | Root `scripts/check_architecture.py` in a clean temporary worktree of the target commit | Passed | Ignored legacy directories/`__pycache__` in the current working directory cause false positives; no user files were deleted |

## 3. Non-Formal Evidence for the Current Artifact Tree

The following are focused prechecks, tooling validation, or scoped rehearsals before the formal double run. They establish that the stated commands/tests produced the stated results; they **do not constitute the required formal double run of one 25-suite list on one tree against two independent empty databases**, nor CI or acceptance evidence.

| Check | Actual result | Artifacts and boundary |
|---|---|---|
| Earlier combined precheck without T6 | 23 suites, **261 passed in 84.78s** | Overlaps focused runs and other prechecks; counts cannot be added to those below as unique nodes |
| Combined precheck with T6 | 24 suites, **267 passed in 87.32s** | Overlaps focused runs and the preceding scope; neither a unique-node increment nor a formal 25-suite run |
| Full-artifact rehearsal on the old 24-suite list | JUnit `tests=267, failures=0, errors=0, skipped=0, time=126.343s`; coverage JSON `9799 / 18534 = 52.87%` | `/tmp/nexusdesk-phase0-preflight.log`, `.xml`, `.summary.json`, `.coverage.json`; old list omits the newly included memory-injection suite and is excluded from formal results |
| Rehearsal artifact self-comparison | Self-compare JSON has `identical=true` with no node differences | Comparing a file with itself validates only the comparator path; it is **not the required two-run baseline** |
| Rehearsal wrapper defect | The pytest process completed and generated the complete artifacts above, after which its zsh wrapper failed with `read-only variable: status` | Defect retained honestly; that wrapper is not a successful formal command. The formal template below uses `test_rc` and preserves the actual pytest exit code |
| T7 plus newly included memory-injection scoped run | **46 passed in 16.43s**, pytest exit 0 | `/tmp/nexusdesk-phase0-t7-memory.log` and `/tmp/nexusdesk-phase0-t7-memory.xml`; combines 28 Runtime PostgreSQL tests and 18 memory-injection tests, and is scoped evidence rather than the formal 25-suite run |
| Independent T7 reviews | Independent spec and quality reviews passed after an independent five-second outer timeout was added around direct worker execution | Review conclusions are not formal-run artifacts and do not replace raw logs, JUnit, the double run, or acceptance |

The earlier 873/18534 (4.71%) coverage figure was only a tooling smoke, not the formal coverage baseline, and is not presented as current-artifact coverage.

## 4. Formal Ordered 25-Suite Scope

Both runs must use the **identical order and test list** below. Neither side may add/remove suites, rename tests, or receive only a supplemental diff run before equivalence is claimed.

1. `tests/test_runtime_engine.py`
2. `tests/test_runtime_baseline.py`
3. `tests/test_runtime_baseline_tooling.py`
4. `tests/test_runtime_baseline_fixtures.py`
5. `tests/test_agent_config_execution_compat.py`
6. `tests/test_runtime_postgres.py`
7. `tests/test_runtime_availability.py`
8. `tests/test_runtime_scope.py`
9. `tests/test_tool_replay_postgres.py`
10. `tests/test_agent_languages.py`
11. `tests/test_agent_language_publishing.py`
12. `tests/test_agent_model_required.py`
13. `tests/test_platform_postgres.py`
14. `tests/test_open_platform.py`
15. `tests/test_memory_config.py`
16. `tests/test_memory_postgres.py`
17. `tests/test_memory_customers_postgres.py`
18. `tests/test_memory_config_postgres.py`
19. `tests/test_memory_injection_postgres.py`
20. `tests/test_model_gateway.py`
21. `tests/test_model_discovery.py`
22. `tests/test_tool_egress.py`
23. `tests/test_tool_post.py`
24. `tests/test_tool_credentials.py`
25. `tests/test_tool_workspace.py`

The scope includes Runtime core and PostgreSQL/SSE/replay, baseline summary/comparison tooling, fixtures, AgentConfig compatibility, Agent/API/language/model constraints, memory config/customer/PostgreSQL/injection, and model/tool gateway, egress, credential, and workspace regressions. Later phases still select suites relevant to their changes rather than blindly running every suite for an unrelated edit; the formal Phase 0 double run may not reduce this list.

## 5. Reproducible Formal Double-Run Command Template

**The current 310-node Run 1 / Run 2 in §6 completed under the corrected template, with successful audits and comparison gates in both rounds; the old 303-node results are listed separately as superseded history. The template below remains mandatory verbatim for later formal reproduction.** From the repository root, start a separate shell for Run 1 and Run 2 and set `run_id` to `run1` or `run2`, respectively. Each run uses its own environment file and independent empty database. Keep both files outside the repository, each containing its own `TEST_DATABASE_URL`, readable/writable only by the current user. Do not reuse the calibration database, a precheck database, or the other run's database, and do not print the environment files. Clear inherited variables before loading; a missing/unreadable file, failed load, or absent `TEST_DATABASE_URL` must fail before Alembic/pytest rather than use a default.

```bash
set -uo pipefail
run_id=run1  # Change only to run2 for round two; never modify the tree between rounds
case "$run_id" in
  run1|run2) ;;
  *) printf 'run_id must be run1 or run2\n' >&2; exit 2 ;;
esac
artifact_prefix="/tmp/nexusdesk-phase0-${run_id}"
env_file="/tmp/nexusdesk-phase0-${run_id}.env"
unset TEST_DATABASE_URL AGENT_DATABASE_URL
if [[ ! -f "$env_file" || ! -r "$env_file" ]]; then
  printf 'Environment file is missing or unreadable: %s\n' "$env_file" >&2
  exit 2
fi
set -a
source "$env_file" || exit $?
set +a
: "${TEST_DATABASE_URL:?run-specific TEST_DATABASE_URL is required}"
export AGENT_DATABASE_URL="$TEST_DATABASE_URL"
export COVERAGE_FILE="${artifact_prefix}.coverage"

# Hash tracked and untracked nonignored files without reading ignored files.
tree_identity() {
  python3 -I - "$1" <<'PY'
from pathlib import Path
import hashlib
import os
import struct
import subprocess
import sys

output = Path(sys.argv[1])
raw = subprocess.check_output(["git", "ls-files", "-co", "--exclude-standard", "-z"])
paths = sorted(path for path in raw.split(b"\0") if path)
digest = hashlib.sha256()
for raw_path in paths:
    path = Path(os.fsdecode(raw_path))
    data = os.fsencode(os.readlink(path)) if path.is_symlink() else path.read_bytes()
    digest.update(struct.pack(">Q", len(raw_path)))
    digest.update(raw_path)
    digest.update(struct.pack(">Q", len(data)))
    digest.update(data)
output.write_text(f"sha256={digest.hexdigest()} files={len(paths)}\n", encoding="ascii")
PY
}

# base_commit is metadata only, never the SHA of this uncommitted tree.
base_commit=$(git rev-parse HEAD) || exit $?
printf '%s\n' "$base_commit" >"${artifact_prefix}.base-commit.txt" || exit $?
tree_identity "${artifact_prefix}.tree-before.txt" || exit $?

# Migrate each run-specific empty database; both variables identify that round's database.
uv run --directory backend alembic upgrade head || exit $?

pytest_start_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)
uv run --directory backend pytest \
  tests/test_runtime_engine.py \
  tests/test_runtime_baseline.py \
  tests/test_runtime_baseline_tooling.py \
  tests/test_runtime_baseline_fixtures.py \
  tests/test_agent_config_execution_compat.py \
  tests/test_runtime_postgres.py \
  tests/test_runtime_availability.py \
  tests/test_runtime_scope.py \
  tests/test_tool_replay_postgres.py \
  tests/test_agent_languages.py \
  tests/test_agent_language_publishing.py \
  tests/test_agent_model_required.py \
  tests/test_platform_postgres.py \
  tests/test_open_platform.py \
  tests/test_memory_config.py \
  tests/test_memory_postgres.py \
  tests/test_memory_customers_postgres.py \
  tests/test_memory_config_postgres.py \
  tests/test_memory_injection_postgres.py \
  tests/test_model_gateway.py \
  tests/test_model_discovery.py \
  tests/test_tool_egress.py \
  tests/test_tool_post.py \
  tests/test_tool_credentials.py \
  tests/test_tool_workspace.py \
  -rA --durations=0 \
  --junitxml="${artifact_prefix}.xml" \
  --cov=agent_platform \
  --cov-report=term \
  --cov-report="json:${artifact_prefix}.coverage.json" \
  >"${artifact_prefix}.log" 2>&1
test_rc=$?
pytest_end_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)

tree_identity "${artifact_prefix}.tree-after.txt"
tree_after_rc=$?
cmp -s "${artifact_prefix}.tree-before.txt" "${artifact_prefix}.tree-after.txt"
tree_compare_rc=$?
{
  printf 'run_id=%s\n' "$run_id"
  printf 'base_commit=%s\n' "$base_commit"
  printf 'pytest_start_utc=%s\n' "$pytest_start_utc"
  printf 'pytest_end_utc=%s\n' "$pytest_end_utc"
  printf 'pytest_exit=%s\n' "$test_rc"
  printf 'tree_after_exit=%s\n' "$tree_after_rc"
  printf 'tree_within_run_cmp_exit=%s\n' "$tree_compare_rc"
} >"${artifact_prefix}.metadata.txt"
metadata_rc=$?

# Preserve the real pytest exit; summary/audit/identity failures are separate.
uv run --directory backend python scripts/runtime_baseline.py \
  summary "${artifact_prefix}.xml" \
  --output "${artifact_prefix}.summary.json"
summary_rc=$?
uv run --directory backend python scripts/runtime_baseline.py \
  audit-log "${artifact_prefix}.log" \
  --output "${artifact_prefix}.xpass-audit.json"
xpass_audit_rc=$?
printf 'pytest exit=%s; summary exit=%s; xpass-audit exit=%s; tree-after exit=%s; tree cmp exit=%s\n' \
  "$test_rc" "$summary_rc" "$xpass_audit_rc" "$tree_after_rc" "$tree_compare_rc"
if (( test_rc != 0 )); then
  exit "$test_rc"
fi
if (( tree_after_rc != 0 )); then
  exit "$tree_after_rc"
fi
if (( tree_compare_rc != 0 )); then
  exit "$tree_compare_rc"
fi
if (( metadata_rc != 0 )); then
  exit "$metadata_rc"
fi
if (( summary_rc != 0 )); then
  exit "$summary_rc"
fi
exit "$xpass_audit_rc"
```

Raw logs, JUnit, summaries, `xpass-audit.json`, coverage, and base/tree/metadata files are separated by `run1`/`run2` and stored outside the repository. `base_commit` records only `git rev-parse HEAD` baseline metadata; it is **not the uncommitted working-tree SHA**. The actual artifact identity is the tree hash: sort raw path bytes from `git ls-files -co --exclude-standard -z`, then update SHA-256 for each path with an 8-byte big-endian path length, raw path, 8-byte big-endian data length, and file bytes; hash symlink-target bytes for symlinks. Output is `sha256=... files=...`; ignored files, including ignored env files, are never read.

Capture `pytest_start_utc`/`pytest_end_utc` immediately around pytest and save its real exit in `test_rc` first; summary/audit/identity failures must not overwrite it. Compare tree-before/tree-after within each run, then compare tree-before and base-commit across runs. If a tree changes within a run, the two tree hashes/file counts differ, or bases differ, do not accept node comparison; adjudicate and rerun the same artifact tree. Node comparison may run only after all the following identity gates and both log audits succeed. The comparison gate reruns each audit and overwrites its output with identical deterministic JSON; an audit that cannot run (exit 2) or finds XPASS (exit 1) blocks immediately:

```bash
set -uo pipefail
for run_id in run1 run2; do
  artifact_prefix="/tmp/nexusdesk-phase0-${run_id}"
  cmp -s "${artifact_prefix}.tree-before.txt" "${artifact_prefix}.tree-after.txt" || {
    printf 'Tree identity mismatch within %s; node comparison is not allowed\n' "$run_id" >&2
    exit 1
  }
  uv run --directory backend python scripts/runtime_baseline.py \
    audit-log "${artifact_prefix}.log" \
    --output "${artifact_prefix}.xpass-audit.json" || {
    audit_rc=$?
    printf 'XPASS log audit failed for %s; node comparison is not allowed\n' "$run_id" >&2
    exit "$audit_rc"
  }
done
cmp -s /tmp/nexusdesk-phase0-run1.tree-before.txt /tmp/nexusdesk-phase0-run2.tree-before.txt || {
  printf 'Run 1/Run 2 tree identities differ; node comparison is not allowed\n' >&2
  exit 1
}
cmp -s /tmp/nexusdesk-phase0-run1.base-commit.txt /tmp/nexusdesk-phase0-run2.base-commit.txt || {
  printf 'Run 1/Run 2 base commits differ; node comparison is not allowed\n' >&2
  exit 1
}
uv run --directory backend python scripts/runtime_baseline.py \
  compare /tmp/nexusdesk-phase0-run1.xml /tmp/nexusdesk-phase0-run2.xml \
  --output /tmp/nexusdesk-phase0-compare.json
```

XPASS evidence has two non-interchangeable layers. JUnit `summary` classifies pytest strict XPASS as `xpass`, covering both `<failure message="[XPASS(strict)] …">` and the compatible `<skipped message="xfail-marked test passes unexpectedly">` representation; an ordinary `<failure>` remains `failed`. A non-strict XPASS, however, is an ordinary passing JUnit testcase with no marker, so **JUnit alone cannot establish zero XPASS**. Every run must therefore retain its pytest `-rA` raw log and run `audit-log`. The command requires exactly one short-test-summary section, at least one test-status entry, and a complete terminal summary. It emits deterministic `summary_entries`, `xpass`, and `xpass_count` JSON. Exit 0 requires no XPASS line and at least one `PASSED` entry as evidence of `-rA` full-status output, exit 1 means non-strict XPASS was found, and exit 2 means the log is missing, not UTF-8, structurally incomplete, or lacks `PASSED` evidence for a clean conclusion. It audits only `XPASS` status lines in the short summary and does not claim generic XPASS detection from JUnit or arbitrary text; strict XPASS independently makes pytest's authoritative `test_rc` nonzero, which remains a blocking gate.

The comparator identifies every JUnit testcase by its exact **`(classname,name)`** pair. Added/missing nodes, changes among `passed/failed/error/skipped/xfail/xpass` outcomes, and changes in skip/xfail/xpass reasons are all differences. Durations are retained for observation but excluded from equivalence. `identical=true` means only that these node fields match; it neither hides failures nor proves business acceptance. Comparator exit 0 means no such differences, 1 means node differences, and 2 means bad input; never coerce the exit code to success. Preserve and adjudicate every failure, skip, or difference rather than deleting nodes, renaming tests, or comparing only totals. The actual report must record UTC start/end, base/tree/metadata files, real pytest and summary/audit exit codes, and identity-comparison results for each run.

## 6. Formal Double Run and Coverage

The corrected local formal double run is complete and has been checked item by item. Each run actually used its own independent empty database migrated to `0057_industry_pack_runtime`, with the exact ordered 25 suites in §4 and the corrected §5 template. Pytest, summary, log audit, tree identity, and wrapper succeeded in each run; the comparison gate reran both log audits before comparing nodes. Full per-case traceability is in `../06-test-report.en.md`.

| Item | Run 1 | Run 2 | Comparison/note |
|---|---|---|---|
| Artifact identity | base `c6c47dec39025ebd4d1176c1e9925bac9c99c4fd`; tree `sha256=f7d3ae857427b5d0173c080f4e6678755f4562730629d3155c2b7d2c44c0d2b1 files=1018` | Same | Base is metadata only, not the uncommitted-tree SHA; `run1_within/run2_within/cross_run_tree/cross_run_base` are all `true`, and no repository files changed between rounds |
| UTC start/end | 2026-11-07T21:37:50Z–2026-11-07T21:40:16Z | 2026-11-07T21:41:09Z–2026-11-07T21:43:36Z | Raw logs and run-specific metadata retained |
| tests/failures/errors/skipped | 310 / 0 / 0 / 0 | 310 / 0 / 0 / 0 | Each JUnit contains 310 unique nodes, all passed |
| JUnit xfail/xpass | 0 / 0 | 0 / 0 | All 310 nodes passed with no skip/xfail/xpass reasons; non-strict XPASS is separately determined by log audit |
| `-rA` log audit | exit 0; `summary_entries=310`, `xpass=[]`, `xpass_count=0` | exit 0; `summary_entries=310`, `xpass=[]`, `xpass_count=0` | Both the formal per-run audits and the comparison-gate reruns succeeded |
| Duration | 145.281s | 145.353s | Observational only, excluded from equivalence; numeric variation alone is not flaky |
| Coverage | 9886/18534 = 53.339807920578394% (53.34%) | 9900/18534 = 53.4153447717708% (53.42%) | Actual totals from each coverage JSON; line-by-line equivalence is not claimed |
| pytest/summary/audit exit codes | 0 / 0 / 0 | 0 / 0 / 0 | Recorded separately; wrapper status did not overwrite pytest status |
| tree-after/within-run cmp/wrapper exit codes | 0 / 0 / 0 | 0 / 0 / 0 | Before/after identity matched within each run and each wrapper succeeded |
| Node comparison | — | — | Comparison-gate audit reruns succeeded before compare exit 0; `/tmp/nexusdesk-phase0-compare.json`: `identical=true`; `added=[]`, `missing=[]`, `outcome_changes=[]`, `skip_reason_changes=[]` |

Each run retains `.log`, `.xml`, `.summary.json`, `.xpass-audit.json`, `.coverage.json`, `.coverage`, `.base-commit.txt`, `.tree-before.txt`, `.tree-after.txt`, and `.metadata.txt`; exact per-file paths are in `../06-test-report.en.md` Appendix A. The shared identity check is `/tmp/nexusdesk-phase0-identity-checks.json`, the environment fingerprint is `/tmp/nexusdesk-phase0-environment.log`, and the comparison-gate log is `/tmp/nexusdesk-phase0-compare-gate.log`.

`/tmp/nexusdesk-phase0-coverage-diff.json` reports executed-line-set differences in eight files, with a net 14 more covered lines in Run 2; per-file run1-only/run2-only line numbers are retained. Node outcomes remain identical. This is a coverage observation, not proof of flaky tests, and must not be hidden by two-decimal coverage displays or green aggregate counts. The tested tree was uncommitted, so final committed-artifact SHA evidence remains `pending_commit`; local double-run success does not replace the clean-CI `pending_env` in §7, authorized-real-sample `pending_env`, or human acceptance.

**Superseded pre-fix 303-node history** is preserved in `/tmp/nexusdesk-phase0-superseded-20261107-3d4f9b06/`: the same base, tree `sha256=3d4f9b06cbdd5de89250d888c0ea695d145e6051d4cc995c64107947fc14e729 files=1014`; UTC ranges 2026-11-07T18:28:35Z–18:30:58Z and 18:31:55Z–18:34:25Z; 303 passed with zero failures/errors/skips in each run; JUnit times 142.851s/148.877s; coverage 9886/18534 (53.34%)/9881/18534 (53.31%); and identical node comparison at that time. The selected sources had no actual xfail markers, but this run had no `audit-log` artifacts. **It is not evidence that the corrected XPASS gate passed, and its tree hash or counts must not be presented as current.**

**A separate rejected Run 1 attempt** is preserved in `/tmp/nexusdesk-phase0-rejected-run1-20261107-19548c1d/`: tree `sha256=19548c1df1591a9fb084e4bb178694d782a50c74c870d0ab4c936975e42d11b9 files=1018`, UTC 2026-11-07T21:20:28Z–21:22:53Z; pytest exit 0, all 308 JUnit nodes passed, time 144.515s, and stable within-run tree. The audit exited 2 because it did not accept the real terminal suffix `(0:02:24)`; no formal audit JSON was produced, and Run 2/compare were not started. It was neither a test failure nor a passing formal run. A separate post-fix diagnosis of its log returned exit 0 with 308 entries and zero XPASS, but the attempt was not promoted; the current 310-node double run above was subsequently restarted with a fresh Run 1 database.

The current 310 nodes equal the superseded 303 nodes plus five strict/non-strict XPASS tooling regressions and two long-duration terminal-format regressions. This document and the reports were backfilled after the tested tree and changed documentation only. The tree hash above identifies neither a newer working tree containing those subsequent documentation edits nor a final committed tree.

## 7. CI Supporting Evidence and Boundary

Existing CI run: <https://github.com/GroundedCoreAI/nexusdesk/actions/runs/42227604191>. All jobs succeeded on 2026-11-06 at head `16aed12eb095f29bed5c536b5fcbf68e510136c4`. Target `c6c47de` is a later documentation merge with the same backend tree; the previously collected total was 949 passed and 17 skipped.

This is **single-run full-CI supporting evidence for the current backend only**. It contains neither the new Phase 0 tests nor coverage, JUnit artifacts, or double-run comparison. No commit containing the Phase 0 artifacts has been pushed/run in CI, so formal CI double-run evidence and links remain `pending_env`; this run is not Phase 0 acceptance evidence.

## 8. Defect and Determinism Handling

- Keep environment-calibration failures separate; neither mix them into the formal failure rate nor delete the record.
- If a new test differs across rounds, investigate isolation, clocks, task cleanup, or database cleanup first; do not simply rerun until green.
- When existing behavior differs from a document, record an R item/defect and freeze reality. Phase 0 does not manufacture green results through production changes or weakened assertions.
- A missing/unreadable `audit-log` result or any XPASS finding blocks that run and node comparison. JUnit passes, summary success, or an identical comparison cannot substitute for the log audit.
- The P2 post-terminal `tool.replay` seq-consumption boundary now has dedicated SSE test evidence but is not claimed security-fixed; the sparse manual raw-version `KeyError("tool_names")` is tracked separately as P0-I7. Neither may disappear behind green aggregate counts.
- Missing CI, real-sample, or human-signoff evidence prevents full Phase 1 entry even when all local tests pass. Final open P0/P1 counts can only be established by the later actual test/acceptance reports.
