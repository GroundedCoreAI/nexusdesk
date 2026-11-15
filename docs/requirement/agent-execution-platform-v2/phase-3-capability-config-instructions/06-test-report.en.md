# Phase 3 · Capabilities, Configuration and Instructions — Test Report

> Status: completed (this round is evidence from actual execution; C11 = `not_measured`; the scoped `ruff format` check shows 3 real deviations in this phase's own files; this report issues no phase conclusion — that belongs to 07)
> Created: 2026-11-13
> Executed by: the T10 test-execution agent (independent evidence collection, no code changes, no adjudication; this report does not pre-write the 07 conclusion)
> Basis: `04-test-plan.en.md`/`04-test-plan.md` (P3-UT-01–28, P3-IT-01–22, P3-CM-01–10, the §6.1 P3-FE registry, §7 exit criteria), `05-acceptance-plan.md` (A1–A11 / C1–C11 / M1–M3 — acceptance itself is not executed here), `03-technical-design.md`, `08-implementation-breakdown.md` (§1 rules, §5, R-37/R-38/R-39)
> Numbering read timestamp: this report maps against the working-tree content of `04-test-plan.md` read at **2026-11-13 21:00 CST** (that revision already contains P3-UT-27/28 and P3-IT-21/22; file mtime `2026-11-13 21:00:20 +0800`). 04 (together with 08/03/05/README) was being revised in parallel by a separate documentation lane while this round executed; if numbers or their criteria change after that moment, the mapping stays as recorded here and the figures in this report must not be retroactively edited.
> Rule: this report only records commands and their verbatim output tails after real execution. Anything not executed, environment-missing or under-sampled is written as `pending_env` / `not_measured` and never as a pass.

## 1. Scope and environment

**Scope**: full affected evidence for T2–T9 as actually executed — migration `0058_agent_execution_metadata`, FR-9 settings, typed ExecutionConfig and canonical compatibility, the four capability layers with trusted ports/cache/warmer, the five snapshots and the write barrier, the Instruction Provider and React instruction parity, execution integration (four-state matrix and start-up barrier), the preview API with the 422 security audit, execution-config-flags, the front-end configuration page with four-locale Playwright, plus the Phase 0–2 regression surface. **This report does not perform acceptance, does not run seed/quickstart, does not run full CI, and draws no production performance conclusion.**

| Item | Measured value | Evidence |
|---|---|---|
| Branch | `feat/agent-execution-platform-v2-phase3` | `git rev-parse --abbrev-ref HEAD` |
| HEAD SHA | `37b08f8a812558b7d80e33987fd496e9145410dc` | `git rev-parse HEAD` |
| Uncommitted working-tree entries | `git status --porcelain \| wc -l` = **44** (36 modified + 8 untracked; excluding the two 06 files added by this report itself) | E21 |
| Distribution of uncommitted work | `backend/src` 18 modified, `backend/tests` 7 modified, `docs/` 10 modified, `frontend/` 1 modified; 8 untracked entries (`applications/security_audit.py`, `capability/production.py`, `contracts/instructions.py`, the `core_platform/agent_execution/instructions/` directory, `test_agent_execution_phase3_{flags,instructions,preview,wiring}.py`) | E21 |
| Operating system | Darwin 27.0.0 (macOS), timezone `+0800` CST | `date`, system info |
| Backend toolchain | Python 3.11.9, uv 0.11.3 | `uv run --directory backend python -V`, `uv --version` |
| Front-end toolchain | node v25.6.1 (Vite dev server already running on `127.0.0.1:5173`, PID 95324, Playwright `reuseExistingServer`) | `node -v`, `curl 127.0.0.1:5173` → 200 |
| PostgreSQL | container `nexusdesk-phase3-pg` (image `pgvector/pgvector:pg17`, state running, `127.0.0.1:55433->5432/tcp`, up 28 hours) | `docker ps`, `docker inspect` |
| Migration head | `alembic heads` = `0058_agent_execution_metadata (head)`; `alembic current` = the same revision | E19, E20 |
| Role attributes measured | `select rolname, rolcreatedb, rolsuper ...` → `agent\|t\|t` (i.e. `rolcreatedb=true`, `rolsuper=true`) | E22 |
| Credentials | only from the mode-0600 file `/tmp/nexusdesk-phase3-pg.env` outside the repository (4 variables); no connection string or password appears in this report, the logs, or any repository file | `ls -l`, `awk -F= '{print $1}'` |
| `AGENT_TENANT_ID` | left at the default `local`, never overridden | execution environment |
| Execution date | 2026-11-13, 20:46–21:15 CST (per-command timestamps in Appendix A) | `date` |

**Uncommitted-scope statement (a checkpoint arrangement known to the coordinator)**: the T6/T7/T8 implementation and tests, plus this round's documentation, exist only as working-tree (uncommitted) content; HEAD `37b08f8` contains commits only up to T2–T5/T9 (`4318042`, `d662a4b`). The figures below therefore describe the composite state "**HEAD + current working tree**" and **no single committed SHA is claimed to reproduce them**; 07 must cite this section whenever it references them. Committing and pushing are decided by the coordinator's checkpoint plan; this agent performed no git write operation.

**Evidence lifecycle**: raw logs of this round live in `/tmp/p3t10-logs/` (a local temporary directory, not a persistent repository evidence area). After cleanup the Appendix A log references cannot be re-verified; this file keeps only commands and verbatim output tails. No CI artifacts or other approved persistent archive was produced, and nothing here implies the evidence has been archived.

## 2. Execution overview (commands and output tails)

All commands run from the repository root; every PostgreSQL command uses this prefix (credentials exist only inside that shell environment and are never written into this report):

```bash
set -a; . /tmp/nexusdesk-phase3-pg.env; set +a
unset AGENT_API_TOKEN
export AGENT_DATABASE_URL="$TEST_DATABASE_URL"
```

| # | Command | Output tail (verbatim) | exit |
|---|---|---|---|
| E01 | `uv run --directory backend pytest -q -m "not postgres"` | `1975 passed, 528 deselected, 6 warnings in 15.39s` | 0 |
| E02 | `uv run --directory backend pytest -m postgres -q -rs` | `500 passed, 28 skipped, 1975 deselected, 3 warnings in 242.74s (0:04:02)` (the 28 skips are itemised in §5) | 0 |
| E03 | `uv run --directory backend pytest tests/test_agent_execution_phase3_migration.py -q -rs` | `2 passed, 1 warning in 3.04s` | 0 |
| E04 | `... tests/test_agent_execution_phase3_settings.py -q -rs` | `58 passed in 0.17s` | 0 |
| E05 | `... tests/test_agent_execution_phase3_config.py -q -rs` | `37 passed in 0.12s` | 0 |
| E06 | `... tests/test_agent_execution_phase3_capabilities.py -q -rs` | `59 passed in 0.31s` | 0 |
| E07 | `... tests/test_agent_execution_phase3_snapshots.py -q -rs` | `96 passed in 3.93s` | 0 |
| E08 | `... tests/test_agent_execution_phase3_instructions.py -q -rs` | `44 passed in 1.40s` | 0 |
| E09 | `... tests/test_agent_execution_phase3_wiring.py -q -rs` | `50 passed in 0.82s` | 0 |
| E10 | `... tests/test_agent_execution_phase3_preview.py -q -rs` | `52 passed, 1 warning in 5.13s` | 0 |
| E11 | `... tests/test_agent_execution_phase3_flags.py -q -rs` | `15 passed, 1 warning in 1.28s` | 0 |
| E12 | `... tests/test_agent_config_execution_compat.py -q -rs` | `19 passed in 7.03s` | 0 |
| E13 | `... tests/test_agent_model_required.py -q -rs` | `2 passed in 1.41s` | 0 |
| E14 | `... tests/test_execution_orchestrator.py -q -rs` | `160 passed in 0.76s` | 0 |
| E15 | `... tests/test_runtime_baseline.py -q -rs` | `88 passed in 3.48s` | 0 |
| E16 | `... tests/test_runtime_engine.py -q -rs` | `18 passed in 0.51s` | 0 |
| E17 | `... tests/test_react_engine_adapter.py -q -rs` | `126 passed in 0.17s` | 0 |
| E18 | `... tests/test_agent_execution_contracts.py -q -rs` | `283 passed in 0.19s` | 0 |
| E19 | `... tests/test_agent_execution_registries.py -q -rs` | `184 passed in 0.19s`; additionally `alembic heads` → `0058_agent_execution_metadata (head)` | 0 |
| E20 | `... tests/test_local_test_adapter.py -q -rs` | `58 passed in 0.19s`; `alembic current` → `0058_agent_execution_metadata (head)` | 0 |
| E21 | `... tests/test_agent_execution_contract_probe.py -q -rs` | `45 passed in 0.11s`; `git status --porcelain \| wc -l` → `44` | 0 |
| E22 | `... tests/test_runtime_postgres.py -q -rs` | `45 passed in 10.07s`; role query → `agent\|t\|t` | 0 |
| E23 | `uv run --directory backend ruff check src tests` | `All checks passed!` | 0 |
| E24 | `uv run --directory backend ruff format --check <the 35 working-tree Python files of this phase>` | `3 files would be reformatted, 32 files already formatted` (the deviating files are listed in §6.5) | 1 |
| E25 | `uv run --directory backend ruff format --check src tests` | `74 files would be reformatted, 397 files already formatted` | 1 |
| E26 | `uv run --directory backend python ../scripts/check_architecture.py` | `architecture gate passed` | 0 |
| E27 | `cd frontend && npx playwright test tests/agent-execution-config.spec.ts --reporter=line` | `37 passed (32.7s)` | 0 |
| E28 | `cd frontend && npm run typecheck` | no output (`tsc --noEmit` terminated normally) | 0 |
| E29 | `cd frontend && npm run check:i18n` | `Verified 2075 translations in zh-CN, zh-TW, en, hi` | 0 |
| E30 | `cd frontend && npm run build` | `✓ built in 3.69s` (plus the pre-existing chunk >500 kB size notice) | 0 |

E01–E02 overlap with E03–E22 and the per-suite runs overlap each other; these counts only prove that the commands actually ran and **must not be summed into an independent coverage figure**. The nine `test_agent_execution_phase3_*.py` files collect **413** nodes in total (`--collect-only -q`), of which **64** carry `@pytest.mark.postgres` across the migration/snapshot/preview/compat files.

## 3. P3 number → evidence mapping

Aliases (all paths relative to the repository root):

`CAP` = `backend/tests/test_agent_execution_phase3_capabilities.py`; `CFG` = `backend/tests/test_agent_execution_phase3_config.py`; `COMPAT` = `backend/tests/test_agent_config_execution_compat.py`; `ENGINE` = `backend/tests/test_runtime_engine.py`; `FLAGS` = `backend/tests/test_agent_execution_phase3_flags.py`; `INS` = `backend/tests/test_agent_execution_phase3_instructions.py`; `LTA` = `backend/tests/test_local_test_adapter.py`; `MIG` = `backend/tests/test_agent_execution_phase3_migration.py`; `ORCH` = `backend/tests/test_execution_orchestrator.py`; `PREV` = `backend/tests/test_agent_execution_phase3_preview.py`; `REG` = `backend/tests/test_agent_execution_registries.py`; `SET` = `backend/tests/test_agent_execution_phase3_settings.py`; `SNAP` = `backend/tests/test_agent_execution_phase3_snapshots.py`; `WIRE` = `backend/tests/test_agent_execution_phase3_wiring.py`

### 3.1 Unit tests (P3-UT-01–28)

| Number | Carrying cases (`alias::function`(expanded node count)) | Environment | Result | Boundary / follow-up |
|---|---|---|---|---|
| P3-UT-01 | `CFG::test_p3_ut_01_missing_engine_defaults_react_without_mutating_input`(1), `CFG::test_p3_ut_01_missing_react_fields_use_react_defaults`(1), `CFG::test_p3_ut_01_model_input_returns_an_equal_but_distinct_canonical_object`(1) (3 functions / 3 nodes ) | Local | Pass | — |
| P3-UT-02 | `CFG::test_p3_ut_02_equal_legacy_and_react_aliases_produce_one_canonical_value`(1) (1 functions / 1 nodes ) | Local | Pass | — |
| P3-UT-03 | `CFG::test_p3_ut_03_conflicting_aliases_name_the_stable_field_path`(3), `CFG::test_p3_ut_03_unserializable_alias_pair_fails_closed_as_validation_error`(6), `CFG::test_p3_ut_03_circular_reference_alias_pair_fails_closed_as_validation_error`(1) (3 functions / 10 nodes ) | Local | Pass | — |
| P3-UT-04 | `CFG::test_p3_ut_04_free_dict_latest_extra_and_client_policy_fields_fail_closed`(8), `CFG::test_p3_ut_04_explicit_non_react_cannot_carry_react_configuration`(1), `REG::test_p3_ut_04_metadata_unknown_triple_fails_closed_without_factory`(2), `REG::test_p3_ut_04_metadata_disabled_adapter_fails_closed_without_factory`(1), `REG::test_p3_ut_04_missing_or_free_dict_schema_is_rejected`(3), `REG::test_p3_ut_04_registration_rejects_non_strict_schema_without_calling_factory`(1), `REG::test_p3_ut_04_21_registry_validates_canonical_config_without_adapter_resolution`(1) (7 functions / 17 nodes ) | Local | Pass | — |
| P3-UT-05 | `CFG::test_p3_ut_05_profile_pairing_and_round_bounds_remain_strict`(6), `CFG::test_p3_ut_05_disabled_capabilities_deduplicate_deterministically`(1), `CFG::test_p3_ut_05_disabled_capabilities_reject_unknown_unbounded_or_wrong_types`(4) (3 functions / 11 nodes ) | Local | Pass | — |
| P3-UT-06 | `CAP::test_p3_ut06_deployed_missing_makes_available_false_without_rewriting_declared`(1), `CAP::test_p3_ut06_probe_version_mismatch_fails_closed_and_preserves_declared`(1), `CAP::test_p3_ut06_declared_lookup_rejects_disabled_or_unknown_triple`(1) (3 functions / 3 nodes ) | Local | Pass | — |
| P3-UT-07 | `CAP::test_p3_ut07_probe_timeout_is_bounded_sanitized_and_reason_stable`(1), `CAP::test_p3_ut07_probe_exception_keeps_error_status_without_raw_text`(1), `CAP::test_p3_ut07_cache_hit_within_ttl_and_declaration_change_replaces_identity_key`(1), `CAP::test_p3_ut07_probe_concurrency_is_bounded`(1) (4 functions / 4 nodes ) | Local | Pass | — |
| P3-UT-08 | `CAP::test_p3_ut08_workspace_required_without_trusted_workspace_blocks_startup`(1) (1 functions / 1 nodes ) | Local | Pass | — |
| P3-UT-09 | `CAP::test_p3_ut09_each_layer_denial_narrows_effective_monotonically`(1), `CAP::test_p3_ut09_disabled_capabilities_can_only_true_to_false`(1) (2 functions / 2 nodes ) | Local | Pass | — |
| P3-UT-10 | `CAP::test_p3_ut10_untrusted_or_stale_policy_fails_closed`(1), `CAP::test_p3_ut10_missing_policy_source_and_unknown_capability_names_fail_closed`(1), `CAP::test_p3_ut10_unknown_capability_names_are_schema_errors_not_ignored`(1) (3 functions / 3 nodes ) | Local | Pass | — |
| P3-UT-11 | `CAP::test_p3_ut11_forged_capability_layers_rejected_by_every_trusted_dto`(1), `CAP::test_p3_ut11_request_and_config_contracts_have_no_capability_authorization_input`(1), `PREV::test_forged_field_is_rejected_not_ignored`(27), `PREV::test_type_errors_are_locatable_and_do_not_echo_values`(1), `PREV::test_unknown_plain_field_is_rejected`(1), `PREV::test_missing_config_is_422`(1) (6 functions / 32 nodes ) | Local | Pass | — |
| P3-UT-12 | `CAP::test_p3_ut12_policy_context_uses_server_trusted_tenant_and_never_client_text`(1), `CAP::test_p3_ut12_cross_tenant_policy_entries_are_isolated`(1), `PREV::test_resolution_request_is_assembled_from_trusted_context`(1), `PREV::test_disabled_capabilities_travel_from_the_draft`(1) (4 functions / 4 nodes ) | Local | Pass | — |
| P3-UT-13 | `SNAP::test_p3_ut13_single_class_limit_is_per_snapshot_not_shared`(1), `SNAP::test_p3_ut13_serialization_failure_is_closed`(1), `SNAP::test_p3_ut13_deserialize_rejects_missing_fields_and_versions`(1), `SNAP::test_p3_ut13_serialization_revalidates_the_dto_completion_invariants`(1), `SNAP::test_p3_ut13_five_class_serialization_also_revalidates`(1), `SNAP::test_snapshot_size_limit_default_matches_settings`(1), `SNAP::test_serialize_enforces_one_startup_identity`(1), `SNAP::test_builders_reject_naive_datetimes`(1) (8 functions / 8 nodes ) | Local | Pass | — |
| P3-UT-14 | `SNAP::test_p3_ut14_denylist_covers_every_planned_key_category`(19), `SNAP::test_p3_ut14_camel_case_and_separator_smuggling_is_normalized`(1), `SNAP::test_p3_ut14_clean_schema_names_are_not_false_positives`(1), `SNAP::test_p3_ut14_secret_shaped_values_rejected_at_any_depth_without_echo`(1), `SNAP::test_p3_ut14_snapshot_with_smuggled_secret_fails_before_write_and_stays_quiet`(1), `SNAP::test_p3_ut14_private_key_value_shape_is_denied_under_a_benign_key_name`(2), `SNAP::test_p3_ut14_legal_identifier_shapes_are_not_false_positives`(1), `SNAP::test_p3_ut14_leading_separator_values_are_denied_by_design`(1) (8 functions / 27 nodes ) | Local | Pass | The non-slug leading-separator tenant_id batch rejection (R-33) is carried by the bidirectional negative controls listed here; the off-state direct-read gap is #130 item 1 |
| P3-UT-15 | `SNAP::test_p3_ut15_repeated_serialization_is_byte_identical`(1), `SNAP::test_p3_ut15_round_trip_reparse_is_stable`(1), `SNAP::test_p3_ut15_replay_touches_no_engine_and_does_not_mutate_snapshots`(1), `SNAP::test_p3_ut15_revalidation_does_not_change_canonical_bytes`(1), `SNAP::test_p3_ut15_replay_rejects_payloads_with_divergent_startup_identity`(1), `SNAP::test_p3_ut15_replay_rejects_missing_illegal_and_unknown_fields_without_echo`(1), `SNAP::test_p3_ut15_replay_accepts_pretty_printed_but_semantically_equal_payloads`(1), `SNAP::test_p3_ut15_replay_accepts_decoded_mapping_payloads_from_a_db_row`(1), `SNAP::test_pg_read_back_row_replays_without_re_encoding`(1) (9 functions / 9 nodes ) | Local+PG | Pass | — |
| P3-UT-16 | `INS::test_p3_ut_16_empty_summary_and_memory_produce_no_empty_messages`(1), `INS::test_p3_ut_16_summary_switch_off_keeps_the_baseline_sequence`(1), `INS::test_p3_ut_16_blank_history_rows_pass_through_but_blank_slots_still_fail`(1) (3 functions / 3 nodes ) | Local | Pass | — |
| P3-UT-17 | `INS::test_p3_ut_17_react_provider_reproduces_the_engine_message_sequence`(11), `INS::test_p3_ut_17_history_truncation_is_applied_once_by_preparation`(1), `INS::test_p3_ut_17_zero_history_turns_keeps_only_system_and_current_user`(1), `INS::test_p3_ut_17_fixed_instruction_order_is_enforced_on_both_sides`(1), `ENGINE::test_prepared_react_instructions_are_an_equivalent_input_not_a_second_assembly`(1) (5 functions / 15 nodes ) | Local | Pass | — |
| P3-UT-18 | `INS::test_p3_ut_18_test_provider_keeps_an_independent_native_format`(1), `INS::test_p3_ut_18_instruction_input_carries_rendered_values_and_never_a_memory_port`(1), `INS::test_p3_ut_18_react_provider_ignores_engine_context`(1), `INS::test_p3_ut_18_preparation_computes_the_effective_prompt_once_before_any_runner`(1) (4 functions / 4 nodes ) | Local | Pass | — |
| P3-UT-19 | `INS::test_p3_ut_19_resolve_rejects_unknown_providers_without_fallback`(6), `INS::test_p3_ut_19_resolve_rejects_hostile_provider_identity`(7), `INS::test_p3_ut_19_test_provider_is_never_production_registered`(1), `INS::test_p3_ut_19_duplicate_context_fails_the_contract`(1), `INS::test_p3_ut_19_contract_errors_fail_closed`(1), `INS::test_p3_ut_19_react_provider_refuses_foreign_engine_and_payload`(1), `INS::test_p3_ut_19_engine_never_degrades_when_the_prepared_input_is_foreign`(1), `INS::test_p3_ut_19_start_is_never_reached_when_preparation_fails`(1), `INS::test_p3_ut_19_prepared_input_that_contradicts_the_engine_arguments_fails_closed`(1), `INS::test_p3_ut_19_prepared_history_must_be_the_windows_own_kept_slice`(1), `INS::test_p3_ut_19_snapshot_fault_codes_are_pinned_to_the_triggering_condition`(1), `INS::test_p3_ut_19_preparation_refuses_a_contract_breaking_value_without_echoing_it`(1), `WIRE::test_snapshot_faults_map_onto_invalid_request_not_internal_error`(1), `WIRE::test_the_four_run_side_codes_stay_out_of_the_adapter_error_map`(1), `WIRE::test_instruction_contract_error_passes_through_without_the_fault_map`(1), `LTA::test_cumulative_t2_t3_t4_modules_and_dependency_direction_are_exact`(1) (16 functions / 27 nodes ) | Local | Pass | — |
| P3-UT-20 | `SET::test_phase3_settings_default_to_safe_rollout_values`(1), `SET::test_phase3_settings_accept_constructor_overrides`(1), `SET::test_phase3_settings_use_agent_environment_prefix`(1), `SET::test_phase3_settings_reject_values_outside_bounds`(31), `SET::test_phase3_settings_accept_inclusive_boundaries`(22), `SET::test_phase3_warm_refresh_must_stay_below_the_shortest_ttl_when_enabled`(1), `SET::test_phase3_warm_refresh_window_is_unconstrained_when_disabled`(1) (7 functions / 58 nodes ) | Local | Pass | — |
| P3-UT-21 | `CFG::test_p3_ut_21_canonical_diff_suppresses_only_default_equivalent_noise`(1), `REG::test_p3_ut_21_exact_metadata_is_complete_without_factory_or_capability_probe`(1), `REG::test_p3_ut_04_21_registry_validates_canonical_config_without_adapter_resolution`(1), `COMPAT::test_react_descriptor_metadata_matches_between_standalone_and_production_registries`(1) (4 functions / 4 nodes ) | Local | Pass | — |
| P3-UT-22 | `CAP::test_p3_ut22_cold_hot_path_never_probes_and_singleflights_refresh`(1), `CAP::test_p3_ut22_unwarmed_unavailable_then_warm_then_expired_sequence`(1), `CAP::test_p3_ut22_failed_refresh_keeps_stale_or_error_and_never_grants`(1), `CAP::test_p3_ut22_availability_and_policy_cache_key_fields_are_exact`(1), `CAP::test_p3_ut22_every_cache_key_field_change_isolates_entries`(1), `CAP::test_p3_ut22_warmer_initial_population_refresh_and_close_without_task_leak`(1), `CAP::test_p3_ut22_warmer_retries_failed_round_at_bounded_interval`(1), `CAP::test_p3_ut22_public_dto_shapes_expose_no_raw_probe_or_internal_snapshots`(1), `PREV::test_preview_response_is_the_exact_whitelist`(1), `PREV::test_preview_response_recursively_free_of_internal_evidence`(1), `PREV::test_reason_codes_pass_through_from_the_layers`(1), `PREV::test_cold_cache_previews_fail_closed_with_stable_reasons`(1), `WIRE::test_composition_constructs_nothing_while_phase3_is_off`(1) (13 functions / 13 nodes ) | Local | Pass | The no-probe-on-hot-path clause refers to resolver.resolve(); the single bounded warm() in the Run barrier does not violate it (frozen in 04) |
| P3-UT-23 | `CAP::test_review_agent_disabled_narrowing_is_not_a_missing_required_capability`(1), `CAP::test_review_policy_layer_denials_are_not_missing_required_capabilities`(1), `CAP::test_review_deployment_or_policy_trust_gaps_still_block_startup`(1), `CAP::test_review_each_infrastructure_probe_reason_enters_required_missing`(2), `CAP::test_review_observed_probe_timeout_enters_required_missing`(1), `CAP::test_review_stale_availability_with_fresh_policy_enters_required_missing`(1), `CAP::test_review_policy_unavailable_alone_enters_required_missing`(1), `CAP::test_review_each_narrowing_reason_stays_out_of_required_missing`(5) (8 functions / 13 nodes ) | Local | Pass | — |
| P3-UT-24 | `CAP::test_review_policy_revision_is_observed_from_the_provider_not_the_request`(1), `CAP::test_review_provider_revision_echo_mismatch_records_error_not_grant`(1), `CAP::test_review_revision_source_failure_raises_policy_source_unavailable`(1), `CAP::test_review_policy_revision_scope_dto_is_strict_and_frozen`(1), `CAP::test_review_trusted_policy_provider_signatures_are_sync_read_async_resolve`(1) (5 functions / 5 nodes ) | Local | Pass | — |
| P3-UT-25 | `CAP::test_review_effective_projection_functions_are_the_unique_canonical_views`(1), `CAP::test_review_execution_restriction_digest_is_canonical_with_empty_constant`(1), `SNAP::test_r22_builder_signatures_are_pinned_to_capability_resolution`(1), `SNAP::test_r22_builders_reject_layer_dto_cache_lookup_and_raw_dict`(1), `SNAP::test_capability_snapshots_copy_the_narrowed_views_verbatim`(1), `SNAP::test_policy_snapshot_requires_a_resolved_policy_and_pins_digests`(1), `SNAP::test_capability_snapshot_set_returns_all_four_layer_snapshots`(1) (7 functions / 7 nodes ) | Local | Pass | — |
| P3-UT-26 | `FLAGS::test_flags_response_is_exactly_two_bools`(1), `FLAGS::test_flags_dto_is_strict_extra_forbid_and_frozen`(1), `FLAGS::test_all_four_states_return_200_with_real_values`(4), `FLAGS::test_flags_track_settings_mutations`(1), `FLAGS::test_flags_read_only_two_setting_booleans`(1) (5 functions / 8 nodes ) | Local | Pass | — |
| P3-UT-27 | `WIRE::test_probe_answers_from_registered_declarations_only`(1), `WIRE::test_probe_echoes_the_context_identity_and_never_the_unobserved_digest`(1), `WIRE::test_probe_deployment_digest_is_stable_and_identity_bound`(1), `WIRE::test_probe_observed_at_comes_from_the_injected_wall_clock`(1), `WIRE::test_probe_reads_metadata_only_and_never_consults_an_adapter`(1), `WIRE::test_resolver_sanitizes_a_declared_false_answer_to_not_declared`(1), `WIRE::test_policy_ceiling_is_the_react_declaration_allow_list`(1), `WIRE::test_policy_agent_layer_follows_the_published_disabled_capabilities`(1), `WIRE::test_policy_provider_echoes_context_identity_with_four_complete_layers`(1), `WIRE::test_current_revision_is_scope_stable_monotonic_and_io_free`(1), `WIRE::test_policy_version_is_the_settings_value_the_descriptor_carries`(1), `WIRE::test_workspace_port_returns_none_and_never_fakes_availability`(1), `WIRE::test_null_workspace_port_still_fails_closed_for_a_requiring_engine`(1) (13 functions / 13 nodes ) | Local | Pass | — |
| P3-UT-28 | `WIRE::test_composition_constructs_nothing_while_phase3_is_off`(1), `WIRE::test_composition_maps_every_capability_setting_to_a_constructor_argument`(1), `WIRE::test_composition_descriptor_and_provider_share_one_policy_version_source`(1), `WIRE::test_composition_warm_targets_are_exactly_the_enabled_registrations`(1), `WIRE::test_a_disabled_registration_descriptor_produces_no_warm_target`(1), `WIRE::test_composition_uses_one_posix_wall_clock_for_the_subsystem`(1), `WIRE::test_trusted_ports_are_injectable_by_code_and_unselectable_by_settings`(1), `WIRE::test_composition_starts_the_warmer_after_extensions_and_closes_it_first`(1), `WIRE::test_cache_warmer_and_resolver_reject_out_of_range_bounds`(1), `WIRE::test_resolver_observations_the_workspace_generation_once_per_round`(1) (10 functions / 10 nodes ) | Local | Pass | — |

### 3.2 Integration tests (P3-IT-01–22)

| Number | Carrying cases (`alias::function`(expanded node count)) | Environment | Result | Boundary / follow-up |
|---|---|---|---|---|
| P3-IT-01 | `COMPAT::test_p3_it_01_legacy_get_is_read_only_and_default_diff_is_empty`(1) (1 functions / 1 nodes ) | PG | Pass | — |
| P3-IT-02 | `COMPAT::test_p3_it_02_new_react_publish_and_metadata_validation_never_create_adapter`(1), `COMPAT::test_p3_it_02_unknown_engine_is_rejected_before_publish_without_adapter`(1), `COMPAT::test_p3_it_02_invalid_stored_config_has_stable_publish_rejection`(1), `COMPAT::test_p3_it_02_alias_conflict_is_rejected_before_update`(1) (4 functions / 4 nodes ) | PG | Pass | — |
| P3-IT-03 | `WIRE::test_declaration_divergence_refuses_before_any_snapshot_or_start`(1), `WIRE::test_cold_policy_warms_once_and_stays_fail_closed_when_the_warm_fails`(1), `WIRE::test_barrier_writes_the_five_payloads_once_before_prepare_and_start`(1), `PREV::test_pg_preview_uses_the_same_resolver_the_run_path_owns`(1) (4 functions / 4 nodes ) | Local+PG | Pass | — |
| P3-IT-04 | `PREV::test_pg_forged_fields_are_audited_without_leaking_values`(1), `PREV::test_forged_field_is_rejected_not_ignored`(27), `PREV::test_type_errors_are_locatable_and_do_not_echo_values`(1) (3 functions / 29 nodes ) | Local+PG | Pass | — |
| P3-IT-05 | `PREV::test_foreign_agent_id_keeps_the_existing_not_found_domain_answer`(1), `PREV::test_pg_cross_tenant_agent_id_is_404_and_audits_no_foreign_data`(1), `COMPAT::test_later_draft_and_v2_do_not_rewrite_v1_or_cross_tenant_boundary`(1) (3 functions / 3 nodes ) | Local+PG | Pass | — |
| P3-IT-06 | `SNAP::test_pg_snapshots_write_once_in_a_single_statement_after_claim`(1), `SNAP::test_pg_conditional_write_identity_rules`(1), `SNAP::test_pg_write_barrier_sql_binds_payload_identity_without_entry_guard`(1), `SNAP::test_pg_write_barrier_sql_binds_payload_identity_of_every_column`(1), `SNAP::test_pg_concurrent_snapshot_writers`(1), `WIRE::test_barrier_writes_the_five_payloads_once_before_prepare_and_start`(1) (6 functions / 6 nodes ) | Local+PG | Pass | — |
| P3-IT-07 | `SNAP::test_pg_terminal_paths_never_rewrite_snapshots`(1), `SNAP::test_pg_retry_changing_one_column_decision_is_refused`(5), `SNAP::test_pg_historical_null_rows_are_never_backfilled_by_reads`(1) (3 functions / 7 nodes ) | PG | Pass | — |
| P3-IT-08 | `SNAP::test_pg_barrier_entry_clean_gate_refuses_every_payload_class_before_sql`(24), `SNAP::test_gate_case_matrix_covers_every_class_per_expressible_column`(1), `SNAP::test_p3_it08_write_entry_rejects_non_canonical_payload_strings`(1), `SNAP::test_pg_commit_failure_leaves_no_partial_snapshot_row`(1) (4 functions / 27 nodes ) | Local+PG | Pass | — |
| P3-IT-09 | `INS::test_p3_ut_17_react_provider_reproduces_the_engine_message_sequence`(11), `ENGINE::test_prepared_react_instructions_are_an_equivalent_input_not_a_second_assembly`(1), `WIRE::test_on_on_adapter_receives_prepared_input_and_no_second_rendering`(1), `WIRE::test_preparation_and_engine_share_one_effective_settings_source`(1) (4 functions / 14 nodes ) | Local | Pass | The write-back-diff/logging clause of 04 rests on the §10 regression suites (the pre-existing Phase 2 MemoryInjection cases); Phase 3 adds no dedicated PG end-to-end case; see §6.7 |
| P3-IT-10 | `INS::test_p3_ut_18_test_provider_keeps_an_independent_native_format`(1), `INS::test_p3_ut_19_test_provider_is_never_production_registered`(1), `WIRE::test_on_on_matches_the_off_on_public_event_sequence_exactly`(1), `LTA::test_cumulative_t2_t3_t4_modules_and_dependency_direction_are_exact`(1) (4 functions / 4 nodes ) | Local | Pass | — |
| P3-IT-11 | `PREV::test_preview_then_policy_change_recomputes_without_stale_grant`(1), `PREV::test_cold_cache_previews_fail_closed_with_stable_reasons`(1), `PREV::test_pg_preview_uses_the_same_resolver_the_run_path_owns`(1), `PREV::test_pg_preview_after_policy_constant_stays_conservative`(1) (4 functions / 4 nodes ) | Local+PG | Pass | The revision-advance form is carried by the non-PG real resolver plus an injected fake provider; the PG face only asserts one shared resolver instance; see §6.3 |
| P3-IT-12 | `WIRE::test_both_off_states_construct_no_phase3_side_effects`(1), `WIRE::test_flipping_the_phase3_flag_leaves_the_fingerprint_unchanged`(1), `PREV::test_pg_phase3_off_preview_domain_error_and_no_subsystem`(1), `ORCH::test_runtime_fingerprint_excludes_both_rollout_flags_and_the_phase3_tuning_family`(1) (4 functions / 4 nodes ) | Local+PG | Pass | The off-state five-column NULL claim is composite evidence with no single PG end-to-end direct read; tracked in #130 item 1; see §6.1 |
| P3-IT-13 | `WIRE::test_rollout_gate_refuses_a_non_react_triple_in_every_off_state`(1), `WIRE::test_on_with_orchestrator_off_refuses_the_legacy_path_completely`(1), `WIRE::test_rollout_gate_fails_closed_on_misconfiguration_and_unavailable_engine`(1), `WIRE::test_the_misconfigured_state_boots_and_still_refuses_runs`(1) (4 functions / 4 nodes ) | Local | Pass | — |
| P3-IT-14 | `MIG::test_0058_upgrade_old_new_concurrent_repository_and_disposable_downgrade`(1) (1 functions / 1 nodes ) | PG | Pass | — |
| P3-IT-15 | `MIG::test_0058_upgrade_old_new_concurrent_repository_and_disposable_downgrade`(1) (1 functions / 1 nodes ) | PG | Pass | Nullable columns not blocking legacy statements plus downgrade/re-upgrade are tested; the 'roll back to the Phase 2 binary' deployment shape is deferred to #128 |
| P3-IT-16 | `COMPAT::test_p3_it_16_new_react_does_not_bypass_model_capability_validation`(1), `COMPAT::test_p3_it_16_new_react_preserves_tool_resolution_and_snapshot`(1) (2 functions / 2 nodes ) | PG | Pass | — |
| P3-IT-17 | `PREV::test_pg_preview_unsaved_draft_has_zero_side_effects`(2), `PREV::test_pg_openapi_declares_strict_request_and_whitelist_response`(1), `PREV::test_preview_does_not_instantiate_adapters_or_write_snapshots`(1) (3 functions / 4 nodes ) | Local+PG | Pass | — |
| P3-IT-18 | `SNAP::test_p3_it18_entry_guard_rejects_foreign_startup_identity_before_database`(1), `SNAP::test_pg_conditional_write_identity_rules`(1), `SNAP::test_snapshot_write_result_is_content_free`(1), `WIRE::test_write_outcomes_map_onto_the_existing_run_vocabulary`(1), `WIRE::test_worker_reads_each_rollout_flag_once_and_fixes_the_path`(1), `WIRE::test_a_row_without_a_published_snapshot_keeps_the_legacy_triple`(1) (6 functions / 6 nodes ) | Local+PG | Pass | — |
| P3-IT-19 | `WIRE::test_composition_maps_every_capability_setting_to_a_constructor_argument`(1), `WIRE::test_composition_descriptor_and_provider_share_one_policy_version_source`(1), `WIRE::test_composition_warm_targets_are_exactly_the_enabled_registrations`(1), `WIRE::test_the_composition_threads_the_snapshot_ceiling_to_the_serializer`(1), `WIRE::test_projected_execution_config_equals_the_agent_config_normalizer`(1), `WIRE::test_projected_execution_config_defaults_the_triple_and_rejects_unknown_keys`(1), `WIRE::test_runtime_fingerprint_excludes_the_phase3_tuning_family_field_by_field`(1), `WIRE::test_runtime_fingerprint_still_hashes_the_runtime_assembly_inputs`(1), `PREV::test_pg_preview_uses_the_same_resolver_the_run_path_owns`(1), `ORCH::test_runtime_fingerprint_exclude_set_names_every_phase3_field`(1) (10 functions / 10 nodes ) | Local+PG | Pass | — |
| P3-IT-20 | `FLAGS::test_unauthenticated_or_bad_token_is_401_or_403`(3), `FLAGS::test_reader_operator_and_admin_can_all_read`(1), `FLAGS::test_flags_are_tenant_agnostic`(1), `FLAGS::test_openapi_contains_flags_route_with_two_property_schema`(1), `FLAGS::test_response_body_carries_no_internal_fields`(1), `FLAGS::test_flags_read_only_two_setting_booleans`(1) (6 functions / 8 nodes ) | Local | Pass | The flags face is pure ASGI over the real principal dependency with no PG-specific case; tenant invariance and OpenAPI are asserted by the listed cases |
| P3-IT-21 | `WIRE::test_probe_reads_metadata_only_and_never_consults_an_adapter`(1), `WIRE::test_policy_ceiling_is_the_react_declaration_allow_list`(1), `WIRE::test_policy_provider_echoes_context_identity_with_four_complete_layers`(1), `WIRE::test_current_revision_is_scope_stable_monotonic_and_io_free`(1), `WIRE::test_workspace_port_returns_none_and_never_fakes_availability`(1), `WIRE::test_trusted_ports_are_injectable_by_code_and_unselectable_by_settings`(1), `WIRE::test_probe_deployment_digest_is_stable_and_identity_bound`(1), `WIRE::test_probe_observed_at_comes_from_the_injected_wall_clock`(1) (8 functions / 8 nodes ) | Local | Pass | — |
| P3-IT-22 | `WIRE::test_every_barrier_refusal_keeps_its_own_run_code`(1), `WIRE::test_snapshot_faults_map_onto_invalid_request_not_internal_error`(1), `WIRE::test_the_four_run_side_codes_stay_out_of_the_adapter_error_map`(1), `WIRE::test_the_runtime_engine_protocol_and_the_engine_implementation_agree`(1), `WIRE::test_instruction_contract_error_passes_through_without_the_fault_map`(1), `WIRE::test_a_ceiling_below_the_payload_refuses_before_the_adapter_starts`(1), `WIRE::test_declaration_divergence_refuses_before_any_snapshot_or_start`(1), `WIRE::test_on_with_orchestrator_off_refuses_the_legacy_path_completely`(1), `WIRE::test_both_off_states_construct_no_phase3_side_effects`(1), `WIRE::test_on_on_matches_the_off_on_public_event_sequence_exactly`(1), `WIRE::test_the_misconfigured_state_boots_and_still_refuses_runs`(1), `PREV::test_flags_endpoint_still_answers_two_bools`(1) (12 functions / 12 nodes ) | Local | Pass | — |

### 3.3 Common check items (P3-CM-01–10)

| Number | Carrying cases (`alias::function`(expanded node count)) | Environment | Result | Boundary / follow-up |
|---|---|---|---|---|
| P3-CM-01 | `MIG::test_0058_revision_chain_and_atomic_sql_contract`(1), `MIG::test_0058_upgrade_old_new_concurrent_repository_and_disposable_downgrade`(1) (2 functions / 2 nodes ) | Local+PG | Pass | — |
| P3-CM-02 | `SET::test_phase3_settings_default_to_safe_rollout_values`(1), `SET::test_phase3_settings_reject_values_outside_bounds`(31), `SET::test_phase3_settings_accept_inclusive_boundaries`(22) (3 functions / 54 nodes ) | Local | Pass | backend/.env.example measured at 13 EXECUTION_* keys; deploy/production/.env.example carries only 1 Phase 2 key, no Phase 3 key and no secrets |
| P3-CM-03 | `PREV::test_pg_forged_fields_are_audited_without_leaking_values`(1), `PREV::test_pg_cross_tenant_agent_id_is_404_and_audits_no_foreign_data`(1), `SNAP::test_error_messages_only_carry_field_paths_and_stable_codes`(1) (3 functions / 3 nodes ) | Local+PG | Pass | The 422 audit is queried directly against the audit table by 2 PG cases; observability fields are asserted by the capability and snapshot cases; production trace/metrics not sampled |
| P3-CM-04 | `CAP::test_p3_ut12_cross_tenant_policy_entries_are_isolated`(1), `PREV::test_pg_cross_tenant_agent_id_is_404_and_audits_no_foreign_data`(1), `COMPAT::test_later_draft_and_v2_do_not_rewrite_v1_or_cross_tenant_boundary`(1), `FLAGS::test_flags_are_tenant_agnostic`(1) (4 functions / 4 nodes ) | Local+PG | Pass | — |
| P3-CM-05 | `COMPAT::test_p3_it_01_legacy_get_is_read_only_and_default_diff_is_empty`(1), `SNAP::test_pg_historical_null_rows_are_never_backfilled_by_reads`(1), `CFG::test_p3_ut_01_missing_engine_defaults_react_without_mutating_input`(1), `CFG::test_p3_ut_21_canonical_diff_suppresses_only_default_equivalent_noise`(1) (4 functions / 4 nodes ) | Local+PG | Pass | — |
| P3-CM-06 | `SNAP::test_repository_sql_is_parameterized_and_only_the_barrier_touches_snapshots`(1), `SNAP::test_pg_terminal_paths_never_rewrite_snapshots`(1), `SNAP::test_pg_snapshots_write_once_in_a_single_statement_after_claim`(1), `SNAP::test_snapshot_write_result_is_content_free`(1), `SNAP::test_pg_public_views_and_events_never_expose_snapshot_columns`(1) (5 functions / 5 nodes ) | Local+PG | Pass | — |
| P3-CM-07 | `CAP::test_p3_ut09_each_layer_denial_narrows_effective_monotonically`(1), `CAP::test_p3_ut11_forged_capability_layers_rejected_by_every_trusted_dto`(1), `CAP::test_p3_ut08_workspace_required_without_trusted_workspace_blocks_startup`(1), `PREV::test_pg_preview_after_policy_constant_stays_conservative`(1) (4 functions / 4 nodes ) | Local+PG | Pass | — |
| P3-CM-08 | See the §3.4 front-end registry | Front-end | Pass (§3.4) | Judgement mapping per 04 §6.1; real-stack UI replay rides with #128 (§6.2) |
| P3-CM-09 | `WIRE::test_both_off_states_construct_no_phase3_side_effects`(1), `WIRE::test_rollout_gate_refuses_a_non_react_triple_in_every_off_state`(1), `MIG::test_0058_upgrade_old_new_concurrent_repository_and_disposable_downgrade`(1) (3 functions / 3 nodes ) | Local+PG | Pass | The flag matrix, column nullability and downgrade-free compatibility are tested; application-level rollback/deployment shape rides with #128 (08 R-39) |
| P3-CM-10 | `LTA::test_cumulative_t2_t3_t4_modules_and_dependency_direction_are_exact`(1), `WIRE::test_trusted_ports_are_injectable_by_code_and_unselectable_by_settings`(1) (2 functions / 2 nodes ) | Local | Pass | No dedicated case; evidence is the passed architecture gate, the dependency-direction/module-list pin, and actual absence (no Host/Workdir/Sandbox/Codex implementation, only denylist keys and placeholder fields) |

### 3.4 Front-end P3-FE (taken directly from the 04 §6.1 registry; no second mapping table is created)

25 numbers (`P3-FE-01…21` plus `05b/10b/10c/16b`); `10c/12/17/18` are each parametrised over `zh-CN/zh-TW/en/hi`, expanding to **37** executed cases (E27). The line number is where that case is defined in `frontend/tests/agent-execution-config.spec.ts`.

| Number | Case (spec line — original title) | 04 §6.1 judgement group | Cases | Result |
|---|---|---|---|---|
| P3-FE-01 | `frontend/tests/agent-execution-config.spec.ts:320` — (M1) an old draft opens without default-filled fields or dirty state | M1 (04 §6.1) | 1 | Pass |
| P3-FE-02 | `frontend/tests/agent-execution-config.spec.ts:334` — a legal new execution config saves, and re-saving adds no churn | P3-CM-05 (history compatibility / dirty) | 1 | Pass |
| P3-FE-03 | `frontend/tests/agent-execution-config.spec.ts:369` — conflicting aliases are located instead of silently resolved | M2 (04 §6.1) | 1 | Pass |
| P3-FE-04 | `frontend/tests/agent-execution-config.spec.ts:381` — an unregistered engine triple is reported against the engine field | M2 | 1 | Pass |
| P3-FE-05 | `frontend/tests/agent-execution-config.spec.ts:388` — preview posts the unsaved draft and stays read-only | M2 (preview read-only) | 1 | Pass |
| P3-FE-05b | `frontend/tests/agent-execution-config.spec.ts:421` — an unsaved new draft previews with a null agent id | M2 (preview read-only) | 1 | Pass |
| P3-FE-06 | `frontend/tests/agent-execution-config.spec.ts:450` — probe unavailability and policy denial are distinguishable | M2 | 1 | Pass |
| P3-FE-07 | `frontend/tests/agent-execution-config.spec.ts:476` — disabled_capabilities can only narrow what the server allowed | M2 (disabled narrows only) | 1 | Pass |
| P3-FE-08 | `frontend/tests/agent-execution-config.spec.ts:497` — previewing never creates a run or a message | Front-end evidence that preview creates no Run (04 §6.1) | 1 | Pass |
| P3-FE-09 | `frontend/tests/agent-execution-config.spec.ts:511` — (M1) a viewer can read and preview but never write | M1 (04 §6.1) | 1 | Pass |
| P3-FE-10 | `frontend/tests/agent-execution-config.spec.ts:528` — a disabled Phase 3 keeps the panel inert | M3 | 1 | Pass |
| P3-FE-10b | `frontend/tests/agent-execution-config.spec.ts:557` — a strict schema rejection names the execution field path | Not listed in the 04 §6.1 judgement grouping (the id is registered, the group entry is missing; see §6.8) | 1 | Pass |
| P3-FE-10c | `frontend/tests/agent-execution-config.spec.ts:574` — zh-CN frames a 422 field path with its own dictionary copy | P3-CM-08 four locales | 4 | Pass |
| P3-FE-11 | `frontend/tests/agent-execution-config.spec.ts:605` — a rejected save points at the offending execution field | M2 | 1 | Pass |
| P3-FE-12 | `frontend/tests/agent-execution-config.spec.ts:613` — zh-CN covers controls, reasons and errors | P3-CM-08 four locales | 4 | Pass |
| P3-FE-13 | `frontend/tests/agent-execution-config.spec.ts:890` — every new execution key exists in all four locales | P3-CM-08 key completeness + untranslated-code whitelist (#130 item 7) | 1 | Pass |
| P3-FE-14 | `frontend/tests/agent-execution-config.spec.ts:647` — (M3) phase3 off hides the editing entries declaratively and keeps the React path intact | M3 (declarative hiding per 03 §7.4) | 1 | Pass |
| P3-FE-15 | `frontend/tests/agent-execution-config.spec.ts:676` — (M3) the on + orchestrator-off mismatch warns without any fake success | M3 (mismatch warning) | 1 | Pass |
| P3-FE-16 | `frontend/tests/agent-execution-config.spec.ts:694` — (M3) a failed flags read hides the Phase 3 entries fail-closed | M3 (fail-closed hiding) | 1 | Pass |
| P3-FE-16b | `frontend/tests/agent-execution-config.spec.ts:717` — the flags pair is read once per editor lifetime, not per preview | M3 (flags read count, R-35) | 1 | Pass |
| P3-FE-17 | `frontend/tests/agent-execution-config.spec.ts:741` — zh-CN translates the Phase 3 not-enabled hint | P3-CM-08 four locales | 4 | Pass |
| P3-FE-18 | `frontend/tests/agent-execution-config.spec.ts:750` — zh-CN translates the deployment misconfiguration hint | P3-CM-08 four locales | 4 | Pass |
| P3-FE-19 | `frontend/tests/agent-execution-config.spec.ts:772` — (M3) a save the server refuses while phase3 is off stays translated, located and non-unlocking | M3 (a server refusal never unlocks entries) | 1 | Pass |
| P3-FE-20 | `frontend/tests/agent-execution-config.spec.ts:829` — (M3) phase3 off still opens the conversation records and a past Run | M3 (history/Run stay viewable) | 1 | Pass |
| P3-FE-21 | `frontend/tests/agent-execution-config.spec.ts:844` — (M3) a failed flags read still leaves the records and Run viewable | M3 (records viewable after a failed flags read) | 1 | Pass |

### 3.5 Numbers that cannot be written as "passed"

1. **P3-CM-08**: its own criteria (typecheck, `check:i18n`, build, the 37 Playwright cases, read-only Effective) all pass as measured, but the unkeyed `model_not_configured` sentence is a **pre-existing defect outside Phase 3 scope**; per 08 R-38/§5 it is excluded from this item's pass/fail and is registered in §7.
2. **C11 (hard gate in 05 §5)**: **no carrying case at all**, `not_measured`, see §4; the `backend/tests/test_agent_execution_phase3_performance.py` required by 04 §6.2 does not exist in this working tree.
3. **P3-IT-09 / P3-IT-15 / P3-IT-20 / P3-CM-03 / P3-CM-09 / P3-CM-10**: the core criteria have carrying cases, but each has at least one sub-criterion with no dedicated case or a restricted form; this is written into the "Boundary / follow-up" column of §3.2/§3.3 and expanded in §6. These numbers must not be cited as "fully covered by their whole criterion".
4. **P3-FE-10b**: the number is in the 04 §6.1 list (one of the declared 25) but is **absent from every judgement group** (none of M1/M2/M3/P3-CM-08/P3-CM-05/"preview creates no Run" includes 10b). It passed as executed; §6.8 registers it as a grouping gap and this report does not invent an owner group for it.

## 4. C11 — `not_measured` (facts only)

| Item | Measured fact |
|---|---|
| Wording | `not_measured` (not measured — neither "passed" nor "performance failed") |
| Direct evidence | neither the working tree nor HEAD contains `backend/tests/test_agent_execution_phase3_performance.py`; no C11 sampling node exists in `ruff`/`pytest` output; `grep -rn "phase3_performance" backend` returns nothing |
| Sample volume | **0** valid interleaved paired samples (04 §6.2 requires ≥100), p95 **not computed**, no raw per-pair timings/timestamps/cache versions |
| R-18 six settings frozen for sampling | **not frozen/collected** (04 §6.2 requires recording and freezing them before sampling; only the settings defaults were read, no paired samples were taken under pinned values) |
| Reason | on 2026-11-13 the maintainer decided to prioritise the functional core (T7/T8/T10/T11) and deferred the real C11 measurement to a standalone follow-up; 08 §5 requires that unobtainable evidence stays `not_measured` and must never be written as DONE or passed |
| Follow-up | issue **#129** (OPEN): `[P3][Phase 3] C11: Real resolver/admission performance measurement (>=100 interleaved pairs, p95 <=50ms)` |
| Effect on the phase conclusion | per 05 §5, C11 is "must pass; insufficient/unmeasured = `not_measured` or `pending_env`, **must not pass**"; 05 §6 additionally lists "C11 without valid measurement" as one of the **fail** conditions, and 05 §2 states that missing environment keeps C11 failing and that merged code cannot substitute for evidence. This report registers only that fact and the criterion wording; **the phase conclusion is made by 07 under 05**, and this report draws no conclusion and uses no phase-level "passed" wording |

The Phase 2 06 used the wording "production performance sub-metric `pending_env`" in a similar situation, and its E14/Appendix E samples came from test doubles and explicitly did not claim production attainment. This Phase 3 round has not even a test-double sample, so only `not_measured` is honest; Phase 2 figures must not be borrowed as a substitute.

## 5. skip / pending_env attribution (by mechanism, not by message text)

The 28 skips in E02, counted per mechanism (`grep -E "^SKIPPED" | sed 's/.*: //' | sort \| uniq -c`, measured):

| Mechanism | Count | Skip message (verbatim) | Attribution | Wording |
|---|---:|---|---|---|
| `MIGRATION_TEST_DATABASE_URL` not provided (opt-in migration-database switch) | **24** | `Requires a test PostgreSQL role with CREATEDB` | that text **only** means the `migration_database` fixture's opt-in variable is absent (08 R-37); it does **not** mean the role lacks `CREATEDB` | `pending_env` (environment-selection gap): not a pass, not a product defect |
| Target database lacks the pgvector/embedding column | **2** | `degraded-path assertion needs a database without the embedding column`; `needs a database without the embedding column` | both require a degraded environment *without* that column, while the current pgvector:pg17 database has it | `pending_env` (alternative-environment cases), not counted as passed |
| Real Milvus explicit opt-in | **1** | `Opt-in real Milvus test` | that external-dependency switch is off (`test_knowledge_workspace.py:264`) | `pending_env`; unrelated to Phase 3 but registered as measured |
| Seeded quickstart explicit opt-in | **1** | `opt-in seeded quickstart URL and admin token are required` | seed/quickstart moved out of this phase (08 R-39); `test_execution_orchestrator_seed.py:469` | `pending_env` → deferred to **#127/#128** |

Additional facts and prohibitions:

1. **Role attributes measured**: `rolcreatedb=true`, `rolsuper=true` (E22). Writing those 24 skips as "insufficient privileges / role lacks CREATEDB" is therefore **prohibited**, and writing `pending_env` as a pass is prohibited (04 §6.3, 08 §5).
2. **The registered asymmetry** (04 §2⑤, 08 R-37, #130 item 6): `test_agent_execution_phase3_migration.py` uses its own fixture reading `TEST_DATABASE_URL` and performs no role-capability probe. In this round E03 was **2 passed** (no error, no skip), so the asymmetry **did not trigger**. Should that file ever report an error, it must not be attributed as a skip, nor used to infer role privileges.
3. E01 (`-m "not postgres"`) is `1975 passed, 528 deselected` with **0 skips**: the non-PG selection contains none of the opt-in items above.
4. Beyond the mechanisms in the table there is no other environment-error-type skip in this round, and no implicit skipping besides skip/xfail classes (none present).

## 6. Evidence boundaries (06 records facts only)

1. **The off-state five-column NULL claim is composite evidence**: carried by «barrier/probe call counts stay 0» (WIRE::`test_both_off_states_construct_no_phase3_side_effects`, PREV::`test_pg_phase3_off_preview_domain_error_and_no_subsystem`) + «the 24-case refusal matrix asserting the row's five columns remain NULL» (SNAP::`test_pg_barrier_entry_clean_gate_refuses_every_payload_class_before_sql`) + «historical NULL rows are never backfilled by reads» (SNAP::`test_pg_historical_null_rows_are_never_backfilled_by_reads`). There is **no** single `@pytest.mark.postgres` case that runs a real Worker end-to-end with flags off and then `SELECT`s the five columns. Registered in **#130 item 1**; it limits the P3-IT-12 and P3-CM-09 sub-criteria.
2. **The 37 front-end cases are mock-contract level**: Playwright mocks `/api/v1/**` via `route`, proving request shapes, DOM gating and four-locale copy; it does **not** equal a real-endpoint UI replay (the flags/preview endpoints exist server-side, so the replay is unblocked). The real-stack replay rides with **#128**. Affects 04 §6.1, the "real environment" meaning inside P3-CM-08, and 05 M1–M3.
3. **The revision-advance form of P3-IT-11**: carried by a **real resolver plus an injected fake provider** (controllable advance) in the non-PG harness (PREV::`test_preview_then_policy_change_recomputes_without_stale_grant`), because this phase's production provider always returns the scope constant (pinned by CAP::`test_review_policy_revision_is_observed_from_the_provider_not_the_request`); the PG face only asserts that preview and Run share one resolver instance (PREV::`test_pg_preview_uses_the_same_resolver_the_run_path_owns`). It must not be read as "cache invalidation on an observed revision advance over PostgreSQL". 04 records this form inside the P3-IT-11 criterion itself.
4. **The 422 first-line truncation is defence-in-depth and unfalsifiable under the current pydantic**: `_sanitized_validation_detail` in `applications/application_factory.py` truncates pydantic messages to the first line to remove nested `input_value=` echo, but pydantic v2 already emits single-line messages on every surface tested, and no case pins the truncation itself (`grep -rn "input_value" backend/tests` has no Phase 3 hit). The audit criterion is carried by the two PG cases that query the audit table directly (PREV::`test_pg_forged_fields_are_audited_without_leaking_values`, `test_pg_cross_tenant_agent_id_is_404_and_audits_no_foreign_data`). Registered in **#130 item 2**; the same issue's item 3 records that `uuid_parsing` 422 messages contain a one-character input fragment (pre-existing pydantic semantics, never audited).
5. **`ruff format` boundary (measured this round, and it differs from the previously expected reading)**: the full tree `ruff format --check src tests` = **74 files would be reformatted, 397 files already formatted** (E25, exit 1); its intersection with "the 166 Python files changed by this branch relative to main" is **10**, and with "the 35 changed/added working-tree files of this phase" is **3**: `src/agent_platform/core_platform/agent_execution/contracts/config.py`, `src/agent_platform/core_platform/agent_execution/orchestration/orchestrator.py`, `tests/test_agent_config_execution_compat.py` (E24, exit 1). Re-checking the same three files extracted with `git show HEAD:<path>` under `--config backend/pyproject.toml` gives **3 files already formatted**, so the deviation is **introduced by the uncommitted T6/T7/T8 working-tree edits**, not by HEAD content. The remaining 64 full-tree deviations are pre-existing baseline files (including the Memory seed group), untouched per 08 §1 rule 4 and not claimed as passing. **Fact: this phase's own scoped format gate is not satisfied in this round**; the fix owner is decided by the coordinator (outside T10's file scope).
6. **T12/T13 and the hardening batch are deferred**: seed → issue **#127**; fresh-quickstart wiring with off/on/rollback verification → issue **#128** (depends on #127), both moved out of this phase by 08 R-39, so this phase holds no such evidence and therefore the "deployment binary rollback" sub-criterion of P3-IT-15 and the "application rollback" sub-criterion of P3-CM-09 have **no real-stack evidence** in this round; the hardening batch (including items 1 and 4 above and the §7 whitelist item) → issue **#130**.
7. **The MemoryInjection traversal inside P3-IT-09**: this round found **no** Phase 3 dedicated PG end-to-end MemoryInjection case; that criterion's write-back/logging surface relies on the pre-existing Phase 2 cases in the §8 regression (`test_runtime_baseline.py` 88 nodes, `test_runtime_postgres.py` 45 nodes and the Memory suites), while the instruction side is carried by the INS/ENGINE/WIRE cases listed in §3.2. This gap is **not** among the 8 items already listed in #130; it is registered here as measured and its owner is left to the coordinator.
8. **The P3-FE-10b grouping gap**: the 04 §6.1 judgement groups (M1, M2, M3, P3-CM-08, P3-CM-05, "preview creates no Run") do not include `10b`, although the same section declares "25 numbers in total". This report does not assign a group on 04's behalf; it is registered as a documentation gap (belonging to the other documentation lane's revision scope).
9. **04/08 numbering synchronisation observation**: 04 (at the read timestamp in the header) already cites R-42–R-52, whereas the 08 §2 ruling table read at 21:00 this round **does not yet contain** R-42–R-52 rows (`grep -c` → 0); the R-42/R-44/R-51/R-52 references inside code comments are separately recorded in #130 item 4. This report does not adjudicate that difference, only registers the read timestamp so 07 can decide whether the number binding holds.

## 7. Known defect registry (outside Phase 3 scope, excluded from this phase's pass/fail)

| Defect | Measured facts | Ownership |
|---|---|---|
| The `model_not_configured` errorText sentence is in no locale dictionary | the Chinese sentence has lived in `frontend/src/i18n/index.ts` since the initial commit and is not a key of any of the `zh-CN/zh-TW/en/hi` dictionaries, so en/hi UIs render the whole Chinese sentence; Phase 3 never modified that file (it is not among this round's `git status` entries either). The front end pins "no second untranslated code may appear" with the explicit whitelist constant `UNTRANSLATED_ERROR_COPY` (FE P3-FE-13, passed as executed) | 08 §5 / R-38; the fix goes through an independent i18n commit/issue → **#130 item 7**. It **must not** be recorded in 06/07 as a Phase 3 defect or a Phase 3 fix |

No other P0/P1 product defect was observed in this round: E01/E02 contain no failing case, E03–E22 contain no failure or error, and E23/E26 both exit 0; the only measured gate deviation is the scoped format item of §6.5 (3 files of this phase).

## 8. Regression scope (04 §6.3)

Regression surface actually executed (node counts taken from E13–E22; the same commands as §2, not executed twice):

- Orchestration and adapters: `test_execution_orchestrator.py` (160), `test_react_engine_adapter.py` (126), `test_local_test_adapter.py` (58), `test_agent_execution_contract_probe.py` (45), `test_agent_execution_contracts.py` (283), `test_agent_execution_registries.py` (184).
- Runtime host side: `test_runtime_baseline.py` (88), `test_runtime_engine.py` (18), `test_runtime_postgres.py` (45, real PostgreSQL).
- Agent configuration and model surface: `test_agent_config_execution_compat.py` (19), `test_agent_model_required.py` (2, both nodes carry the postgres marker and ran against real PostgreSQL).
- The combined non-PG selection (E01, 1975 passed) and PG selection (E02, 500 passed) additionally cover the Memory/migration/channel suites. No historical fixture expectation was changed for the new implementation (this round modifies no code or test; the working-tree edits to test files belong to the T6/T7/T8 deliverables themselves).
- Static surface: architecture gate passed (E26), `ruff check` passed (E23), and both full selections `-m "not postgres"` / `-m postgres` had no failures.

## 9. Exit criteria against 04 §7 (item-by-item labels; no phase conclusion here)

| Exit criterion (04 §7 wording) | Label for this round | Basis and follow-up |
|---|---|---|
| All P3-UT pass | **Satisfied (at execution level)** | 28/28 numbers have carrying cases and all passed (§3.1, E01/E03–E11/E14/E16–E18); differences inside individual criteria are listed in §3.5 and §6, so this row must not be read as "no sub-criterion gap" |
| All P3-IT pass | **Satisfied (at execution level), with boundaries** | 22/22 numbers have carrying cases and passed (§3.2); the form limits of P3-IT-09/11/15/20 are in §6.3, §6.7 and the boundary column of §3.2 |
| All P3-CM pass | **Not satisfied (one item remains open)** | the "application rollback" sub-criterion of P3-CM-09 has no evidence this round (→ #128); P3-CM-10 has no dedicated case (carried by static/absence evidence); and the "this phase's files are formatted" requirement of 08 §1 rule 4 is not met (§6.5) |
| AC-1–AC-11 reproducible | **Not assessed (belongs to 07)** | 06 performs no acceptance; reproduction entry points are the carrying cases in §3 and the commands in §2 |
| No P0/P1 | **Satisfied (as observed this round)** | E01/E02 have no failures; the only out-of-scope pre-existing defect is §7, excluded per R-38 |
| Privilege escalation / cross-tenant = 0 | **Satisfied (over the tested surface)** | the forgery matrix, cross-tenant 404 and the audit's absence of body/field values/secrets are asserted by the cases listed in §3.1/§3.2/§3.3; real-stack and production surfaces are out of this round (§6.2, §10) |
| Snapshots and audit meet their criteria | **Satisfied (composite evidence) + boundary** | write-once barrier, refusal matrix, replay, immutability and the direct audit query all passed; boundaries are §6.1 (off-state direct-read gap, #130-1) and §6.4 (unfalsifiable 422 truncation, #130-2) |
| Dual-switch diff conforms | **Satisfied (over the tested surface)** | the four-state matrix and off/on field-level parity are carried by WIRE/PREV/ORCH cases (§3.2 P3-IT-12/13/22); real deployment-shaped rollback → #128 |
| C11 validly measured and met | **Not satisfied (`not_measured`)** | §4; follow-up #129; the effect of that unmeasured state on the phase conclusion is decided by 07 under 05 §5/§6 |
| Environment gaps block their go-live commitments | **Facts registered** | this round's gaps: C11 (#129), seed/quickstart (#127/#128), 24 migration opt-in skips, 2 embedding alternative-environment skips, 1 Milvus opt-in skip; their go-live meaning belongs to 07 |
| Full pytest executed by CI | **Not executed** | §10: no push/PR this round, hence no CI run or URL; E01/E02 are local selections and are not CI |

## 10. Items not executed and not inferable

1. **CI not executed**: no commit, no push and no PR this round, therefore no CI run, no CI head SHA and no URL; E01/E02/E25/E27–E30 are local executions only. Local results cannot replace CI's full unit/postgres/frontend outcome.
2. **Seed and fresh quickstart not executed**: moved out of this phase per 08 R-39 (#127/#128).
3. **No production-like performance and no real external model run**: C11 `not_measured` (§4).
4. **No human M1–M3 acceptance and no sign-off**: 05 §4 manual checks belong to 07; this round provides only equivalent automated evidence (§3.4).
5. **No code, test or other documentation was modified**: this round adds only these two bilingual 06 files; no 07 was created and no historical conclusion was rewritten.
6. **No Phase 4/5/6 evidence**: P3-CM-10 is a boundary check against scope creep, evidenced here by the architecture gate and by absence in the code; no Phase 4+ conclusion is produced.

## 11. Coordinator addendum (post-collection fix, 2026-11-13)

1. **§6.5 format deviation fixed**: after this report's evidence collection, the coordinator ran `ruff format` on exactly the three deviating files (`contracts/config.py`, `orchestration/orchestrator.py`, `tests/test_agent_config_execution_compat.py`); re-verification: scoped `ruff format --check` over the 32 remaining branch files → `32 files already formatted` (the 3 fixed files now also pass, total 35/35 clean), `ruff check src tests` → All checks passed, `pytest tests/test_agent_execution_phase3_config.py tests/test_agent_execution_phase3_wiring.py tests/test_agent_config_execution_compat.py -q` → **106 passed**, `pytest -q -m "not postgres"` → **1975 passed, 528 deselected**. The scoped-format exit criterion in §9 is therefore met as of this addendum; the whole-tree 74-file historical deviation is unchanged and remains out of scope per 08 §1 rule 4.
2. **§6.9 resolved**: 08 §2 now contains R-42–R-52 (verified by the coordinator: ruling-table row count 52 in both CN and EN, per-number counts equal); the numbering binding for 07 holds.
3. **§6.7 disposition**: the P3-IT-09 MemoryInjection PG end-to-end gap is registered as item 9 of issue **#130**.
4. **§6.8 disposition**: `P3-FE-10b` is added to the M2 group of the 04 §6.1 registry (bilingual, coordinator edit).

## Appendix A Verbatim output tails

| Evidence | Command essence | Verbatim output tail |
|---|---|---|
| A-01 | `pytest -q -m "not postgres"` | `1975 passed, 528 deselected, 6 warnings in 15.39s` |
| A-02 | `pytest -m postgres -q -rs` | `500 passed, 28 skipped, 1975 deselected, 3 warnings in 242.74s (0:04:02)` |
| A-03 | `pytest tests/test_agent_execution_phase3_migration.py -q -rs` | `2 passed, 1 warning in 3.04s` |
| A-04 | `..._settings.py -q -rs` | `58 passed in 0.17s` |
| A-05 | `..._config.py -q -rs` | `37 passed in 0.12s` |
| A-06 | `..._capabilities.py -q -rs` | `59 passed in 0.31s` |
| A-07 | `..._snapshots.py -q -rs` | `96 passed in 3.93s` |
| A-08 | `..._instructions.py -q -rs` | `44 passed in 1.40s` |
| A-09 | `..._wiring.py -q -rs` | `50 passed in 0.82s` |
| A-10 | `..._preview.py -q -rs` | `52 passed, 1 warning in 5.13s` |
| A-11 | `..._flags.py -q -rs` | `15 passed, 1 warning in 1.28s` |
| A-12 | `test_agent_config_execution_compat.py -q -rs` | `19 passed in 7.03s` |
| A-13 | `test_agent_model_required.py -q -rs` | `2 passed in 1.41s` |
| A-14 | `test_execution_orchestrator.py -q -rs` | `160 passed in 0.76s` |
| A-15 | `test_runtime_baseline.py -q -rs` | `88 passed in 3.48s` |
| A-16 | `test_runtime_engine.py -q -rs` | `18 passed in 0.51s` |
| A-17 | `test_react_engine_adapter.py -q -rs` | `126 passed in 0.17s` |
| A-18 | `test_agent_execution_contracts.py -q -rs` | `283 passed in 0.19s` |
| A-19 | `test_agent_execution_registries.py -q -rs` | `184 passed in 0.19s` |
| A-20 | `test_local_test_adapter.py -q -rs` | `58 passed in 0.19s` |
| A-21 | `test_agent_execution_contract_probe.py -q -rs` | `45 passed in 0.11s` |
| A-22 | `test_runtime_postgres.py -q -rs` | `45 passed in 10.07s` |
| A-23 | `ruff check src tests` | `All checks passed!` |
| A-24 | `ruff format --check <this phase's 35 files>` | `3 files would be reformatted, 32 files already formatted` (`contracts/config.py:160`, `orchestration/orchestrator.py:303`, `tests/test_agent_config_execution_compat.py`) |
| A-25 | `ruff format --check src tests` | `74 files would be reformatted, 397 files already formatted` |
| A-26 | `python ../scripts/check_architecture.py` | `architecture gate passed` |
| A-27 | `npx playwright test tests/agent-execution-config.spec.ts --reporter=line` | `37 passed (32.7s)` |
| A-28 | `npm run typecheck` | `> tsc --noEmit` (no diagnostics) |
| A-29 | `npm run check:i18n` | `Verified 2075 translations in zh-CN, zh-TW, en, hi` |
| A-30 | `npm run build` | `✓ built in 3.69s` (the chunk >500 kB notice is a pre-existing size hint) |
| A-31 | `alembic heads` / `alembic current` | `0058_agent_execution_metadata (head)` / `0058_agent_execution_metadata (head)` |
| A-32 | `psql -tAc "select rolname, rolcreatedb, rolsuper ..."` | `agent\|t\|t` |
| A-33 | `pytest -q --collect-only <the 9 phase3 files>` | `413 tests collected in 1.25s` |
| A-34 | `pytest -m postgres -q --collect-only <MIG/SNAP/PREV/COMPAT>` | `64` PG nodes |
| A-35 | `git rev-parse HEAD` / `git status --porcelain \| wc -l` | `37b08f8a812558b7d80e33987fd496e9145410dc` / `44` |

## Appendix B Collection method and recomputability

1. **How the number mapping was collected**: the authoritative node set is `pytest -q --collect-only` node IDs (A-33/A-34 and the per-file counts in §8 come from the same source). A script then resolved every P3 number in the test sources from three places — the function-name prefix (`test_p3_utNN_*` / `test_p3_itNN_*`), `P3-…` markers inside the function docstring, and the section banner comments (`# P3-IT-06/07/08/18 + P3-CM-06 ...`); afterwards every carrying function name of every number was verified to exist in the collected set. The numbers in brackets in §3 are **pytest-expanded node counts per function**, not function counts.
2. **Recomputation path**: any number can be recomputed through its `alias::function`, e.g. `uv run --directory backend pytest "tests/test_agent_execution_phase3_snapshots.py::test_pg_barrier_entry_clean_gate_refuses_every_payload_class_before_sql" -q -rs` (with the PG prefix of §2) must give `24 passed`, matching the node count in the P3-IT-08 row of §3.2.
3. **Do not recompute these as coverage**: one function can carry several numbers at once (for instance WIRE::`test_declaration_divergence_refuses_before_any_snapshot_or_start` appears in both the P3-IT-03 and P3-IT-22 rows), so per-row node counts **must not be summed**.
4. **No raw-data archive from this round**: C11 has no raw samples to archive (§4); Playwright traces/screenshots remain in the tool's default local output directory and, per the evidence-lifecycle statement in §1, were not persistently archived.
