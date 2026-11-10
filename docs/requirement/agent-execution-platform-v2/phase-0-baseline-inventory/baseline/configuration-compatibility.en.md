# Phase 0 Baseline · AgentConfig Configuration Compatibility Matrix

> Status: Current-state compatibility evidence and the corrected local formal Run 1/Run 2 results—310 passing nodes and successful XPASS audits in both rounds—are recorded (see `regression-baseline.en.md` §6); clean CI, authorized real samples, final commit evidence, and acceptance signoff still require their own evidence
> Created: 2026-11-08
> Basis: `02-requirements.md` (FR-3, AC-3), `04-test-plan.md` (P0-UT-05–07, P0-IT-08), `manifest.v1.json`, and current-state tests
> Current-state target commit: `c6c47dec39025ebd4d1176c1e9925bac9c99c4fd`
> Current artifact tree: uncommitted feature-branch working tree; no fictitious artifact SHA is assigned or conflated with the current-state target

## 1. Scope and Evidence Boundaries

- The fixture root is `backend/tests/fixtures/agent_execution_baseline/`. It contains **7 files**: `manifest.v1.json` plus **6 payload files**, expanding to **5 valid cases** and **16 invalid cases**.
- Every value is synthetic. Repository-history provenance describes **field shape only**; it does not indicate captured production or customer content. These fixtures must not be called real historical samples.
- Representativeness of real production published snapshots remains `pending_env` with the Agent-config and security owners, who must supply authorized samples or record a formal scope decision.
- This document freezes current behavior at the target commit and test evidence in the current uncommitted artifact tree. It invents no future Engine mapping. The unknown `engine` field is rejected because `AgentConfig` uses `extra=forbid`; no Engine configuration contract is thereby designed or approved.
- The focused tests and earlier non-formal prechecks below do not replace the formal 25-suite double run, clean CI, real-sample review, or acceptance sign-off. See `regression-baseline.en.md` for formal status.

## 2. File Inventory and Provenance

| File | Payload kind | Cases | Source category and verified boundary |
|---|---|---:|---|
| `manifest.v1.json` | Manifest; not validated directly | — | Freezes `fixture_version=v1`, target SHA, file set, synthetic-value policy, expected results, and exact error locations |
| `minimal-defaults.v1.json` | Single AgentConfig | 1 valid | Minimal synthetic input constructed against AgentConfig at the target commit; verifies current defaults |
| `legacy-core-shape.v1.json` | Single AgentConfig | 1 valid | Field set verified against `backend/src/agent_platform/modules/agent_config/service.py` at historical commit `7dce7ba473622b209329ccd058b42b74b5538bdc`; all values are synthetic |
| `legacy-memory-shape.v1.json` | Single AgentConfig | 1 valid | Field set verified against the same path at historical commit `7250aa0e83a48b7b43340b8fa0db4666eb83e7b7`; all values are synthetic |
| `valid-boundaries.v1.json` | `cases` collection | 2 valid | Synthetic numeric, collection, and runtime-truncation boundaries constructed from current constraints |
| `unknown-engine-field.v1.json` | Single AgentConfig | 1 invalid | Unsupported `engine` object added to an otherwise valid current synthetic config |
| `invalid-cases.v1.json` | `cases` collection | 15 invalid | Synthetic invalid values constructed from current enum, type, range, and model-binding constraints |

`test_runtime_baseline_fixtures.py::test_fixture_manifest_covers_exact_files_and_all_valid_configs` verifies manifest completeness and valid inputs. `test_invalid_fixtures_declare_exact_pydantic_error_locations` in the same file verifies exact invalid-input locations.

## 3. Valid-Input Compatibility Matrix

| File / case ID | Coverage | Current expectation and assertion |
|---|---|---|
| `minimal-defaults.v1.json` | Only required `system_prompt` supplied | Validation succeeds; every current default below matches `AgentConfig.model_dump(mode="json")` |
| `legacy-core-shape.v1.json` | Initial core field shape; newer memory fields default on read | Validation succeeds; publication integration retains core keys; not a production-content sample |
| `legacy-memory-shape.v1.json` | Earlier memory-switch field shape; later fields default on read | Validation succeeds; publication integration retains keys including `tool_names`; not a production-content sample |
| `valid-boundaries.v1.json` / `lower-numeric-boundaries` | Shortest prompt, numeric lower bounds, singleton collections | Validation succeeds |
| `valid-boundaries.v1.json` / `upper-numeric-and-collection-boundaries` | `max_model_rounds=30`, 30 tools, 30 KBs, memory limits of 999 | Validation succeeds; values above platform runtime memory caps may be truncated at runtime, so model validation does not equal the actual injected count |

Current defaults frozen by `minimal-defaults.v1.json`:

| Field | Default | Field | Default |
|---|---|---|---|
| `tool_names` | `[]` | `knowledge_base_ids` | `[]` |
| `max_model_rounds` | `6` | `model_profile_id` | `null` |
| `model_profile_version` | `null` | `reply_language` | `"auto"` |
| `summary_enabled` | `true` | `memory_enabled` | `true` |
| `memory_write` | `true` | `memory_read_enabled` | `true` |
| `memory_types` | `["profile","preference","event"]` | `memory_search_enabled` | `true` |
| `memory_write_mode` | `"auto"` | `memory_inject_max_items` | `null` |
| `memory_search_limit` | `null` | `memory_blacklist_auto_handoff` | `false` |

## 4. Invalid Inputs and Exact Pydantic Locations

The table reproduces the manifest's `expected_error_locations`. Each inner array is one Pydantic `loc`; `[]` unambiguously means a **root-model validation error**, not a missing assertion. Collection errors retain integer indices, such as `["memory_types",0]`. The test compares the complete normalized location sets for equality rather than checking only field names.

| File / case ID | Invalid construction | Exact `expected_error_locations` |
|---|---|---|
| `unknown-engine-field.v1.json` | Undeclared `engine` object; `extra=forbid` | `[["engine"]]` |
| `invalid-cases.v1.json` / `empty-system-prompt` | Empty prompt | `[["system_prompt"]]` |
| `invalid-cases.v1.json` / `tool-names-wrong-type` | String supplied for the tool collection | `[["tool_names"]]` |
| `invalid-cases.v1.json` / `model-rounds-wrong-type` | Non-numeric string supplied for rounds | `[["max_model_rounds"]]` |
| `invalid-cases.v1.json` / `model-rounds-below-lower-bound` | `max_model_rounds=0` | `[["max_model_rounds"]]` |
| `invalid-cases.v1.json` / `model-rounds-above-upper-bound` | `max_model_rounds=31` | `[["max_model_rounds"]]` |
| `invalid-cases.v1.json` / `model-profile-version-below-lower-bound` | `model_profile_version=0` | `[["model_profile_version"]]` |
| `invalid-cases.v1.json` / `model-profile-binding-is-incomplete` | Profile ID without version; related fields are `model_profile_id` and `model_profile_version` | `[[]]` |
| `invalid-cases.v1.json` / `invalid-reply-language-enum` | Unsupported reply language | `[["reply_language"]]` |
| `invalid-cases.v1.json` / `invalid-memory-type-enum` | Unsupported memory type at collection index 0 | `[["memory_types",0]]` |
| `invalid-cases.v1.json` / `empty-memory-types` | Empty memory-type collection | `[["memory_types"]]` |
| `invalid-cases.v1.json` / `invalid-memory-write-mode-enum` | Unsupported write mode | `[["memory_write_mode"]]` |
| `invalid-cases.v1.json` / `memory-inject-limit-below-lower-bound` | Injection limit of 0 | `[["memory_inject_max_items"]]` |
| `invalid-cases.v1.json` / `memory-search-limit-below-lower-bound` | Search limit of 0 | `[["memory_search_limit"]]` |
| `invalid-cases.v1.json` / `invalid-knowledge-base-uuid` | KB collection item 0 is not a UUID | `[["knowledge_base_ids",0]]` |
| `invalid-cases.v1.json` / `summary-enabled-wrong-type` | Array supplied for a boolean switch | `[["summary_enabled"]]` |

The total is 1 standalone invalid-file case plus 15 collection cases, or **16 invalid cases**. Two valid collection cases plus three standalone valid files give **5 valid cases**.

## 5. Reproducible Focused Commands

Run from the repository root. The static/fixture checks require neither PostgreSQL nor `TEST_DATABASE_URL`:

```bash
uv run --directory backend pytest \
  tests/test_runtime_baseline_fixtures.py \
  tests/test_agent_config_execution_compat.py::test_p0_ut_08_frozen_identities_terminology_and_worker_neutrality \
  -rA --durations=0 \
  --junitxml=/tmp/nexusdesk-phase0-config-static.xml
```

Focused PostgreSQL reproduction uses a dedicated migrated test database. Keep the environment file local and uncommitted; only variable names are referenced, never URL or credential values. Clear inherited database variables before loading; a missing/unreadable file or failed `source` must exit rather than fall back to inherited values or a default database. A migration failure also stops the subsequent test:

```bash
set -uo pipefail
env_file=/tmp/nexusdesk-phase0-postgres.env
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
uv run --directory backend alembic upgrade head || exit $?
uv run --directory backend pytest \
  tests/test_agent_config_execution_compat.py \
  -rA --durations=0 \
  --junitxml=/tmp/nexusdesk-phase0-config-postgres.xml
```

These read-only commands verify the two historical field-shape sources without reading production data:

```bash
git show 7dce7ba473622b209329ccd058b42b74b5538bdc:backend/src/agent_platform/modules/agent_config/service.py
git show 7250aa0e83a48b7b43340b8fa0db4666eb83e7b7:backend/src/agent_platform/modules/agent_config/service.py
```

These are focused reproduction commands, not the formal 25-suite double-run command. See `regression-baseline.en.md` for that command, artifact naming, coverage, and node-comparison rules.

## 6. Real PostgreSQL Publication, Snapshot, and Execution Boundaries

The following are current-state assertions against real PostgreSQL in `backend/tests/test_agent_config_execution_compat.py`. Model binding uses a real demo profile inside the tests; no real external model is called.

| Test node | Frozen current behavior | Evidence boundary |
|---|---|---|
| `test_p0_it_08_legacy_raw_draft_publishes_normalized_v1` | Both legacy raw draft fixtures are deep-copied. Only in memory, synthetic model binding is replaced with a real demo profile and tool/KB lists are emptied; bound SQL uses `CAST(:draft AS jsonb)` to simulate a raw JSONB draft. The real publish API leaves the raw draft and source fixture bytes unchanged. Stored v1 exactly equals `AgentConfig.model_validate(legacy).model_dump(mode="json")`, including every current default; explicit `snapshot(version=1)` returns stored v1 | Proves the public path for synthetic field shapes, not real-production representativeness |
| `test_later_draft_and_v2_do_not_rewrite_v1_or_cross_tenant_boundary` | A later draft/v2 rewrites neither stored nor explicitly read v1; latest snapshot without a version is v2. Cross-tenant `versions()` currently raises `DomainError(code="not_found", status=404)`, while `snapshot()` raises `DomainError(code="agent_not_found", status=404)` | These distinct actual error codes must remain separate and are not unified in prose |
| `test_queued_run_keeps_v1_snapshot_after_v2_is_published` | A Run submitted at v1 and still queued retains its complete Agent v1 snapshot after v2 publication | The test executes no model; it verifies the queued Run's persisted snapshot only |
| `test_sparse_raw_version_exposes_direct_snapshot_tool_names_limitation` | A manually inserted extremely sparse raw version is valid `AgentConfig` input, but direct `snapshot()` currently raises `KeyError("tool_names")` | This is a **storage-stage limitation**. It proves neither that public publish creates such a row nor that all valid configs are directly executable. Track it separately as P2/open; do not conflate it with a P1 failure of an authorized real historical valid sample |

These PostgreSQL behaviors are included in the current local formal Run 1/Run 2 results recorded in `regression-baseline.en.md` §6: all 310 nodes passed in each run, and both the per-run non-strict XPASS audits and their comparison-gate reruns exited 0 with `summary_entries=310` and `xpass_count=0`. Clean CI, authorized real samples, final commit evidence, and acceptance signoff remain pending. The sparse raw-version item is tracked as P0-I7 in `refactoring-checklist.en.md` and must be resolved or formally adjudicated with regression evidence before Phase 3 configuration mapping.
