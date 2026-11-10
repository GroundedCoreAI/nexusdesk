# Phase 1 · Execution Contracts and Registries — Test Report

> Status: the locally approved test-plan scope and exit evidence are satisfied; all 23 UT/IT and 6 CM rows pass; the full suite/CI remains pending, and Phase 1 has not been formally accepted or signed off
> Created: 2026-11-08
> Basis: `04-test-plan.md` (P1-UT-01～12, P1-IT-01～11, P1-CM-01～06), `02-requirements.md` (FR/AC), `08-implementation-breakdown.md` (T2～T6, R1～R11)
> Executed by: independent T7 executor; execution coverage: 2026-11-08～2026-11-09; final current-tree rerun: 2026-11-09

## 1. Test Scope and Environment

**Scope**: execute `04-test-plan.md` as approved for the six DTOs, safe error catalog, complete Adapter lifecycle, Engine/Protocol/Adapter registries, exact version resolution, event high-water behavior, LocalTestAdapter, structurally independent second Adapter, zero production wiring, and existing regressions. The test plan was not changed. No skip, unexecuted item, or missing environment was counted as a pass.

| Environment | Configuration | Purpose |
|---|---|---|
| Local Darwin 27.0.0 x86_64 / Python 3.11.9 / uv | Focused cases are in-memory; no model or external Engine connection | All F current-tree focused/static execution in this report |
| T6 historical static and non-PG regression evidence | Baseline `4dfcfb41e9cbb799753986c2d76134514bbd19be`; retained only for initial skip/gate history, with final counts refreshed by the 2026-11-09 current-tree reruns | Historical comparison for CM01～06 and the initial environment gap |
| Independent Docker PostgreSQL | `nexusdesk-phase1-pg-838b99d6`, `pgvector/pgvector:pg17`; dedicated empty database/volume and loopback dynamic port; existing Phase 0 container neither reused nor modified | `alembic upgrade head` from an empty database, then actual execution of 28 runtime_postgres + 6 open_platform cases |
| CI (GitHub Actions + PostgreSQL service) | Not run; requires dedicated `TEST_DATABASE_URL` | Full suite and CI groups, currently PENDING |
| Model | None; LocalTest/ContractProbe are programmable scripted Adapters | Automated contract scenarios |

**Evidence directories**: the final current-tree rerun (below, **F**) is `/tmp/nexusdesk-t7-final-evidence.DynKi0`; R6 RED-first/fix evidence is `/tmp/nexusdesk-phase1-r6-fix-evidence`; original T7 is `/tmp/nexusdesk-t7-evidence.cNI1ch`; T6 is `/tmp/nexusdesk-t6-evidence.Ph3A4O`; and Docker PostgreSQL is `/tmp/nexusdesk-phase1-pg-4ph_1qsi`. F's clean-source architecture shadow is F/clean-source-shadow; the historical T6 shadow is `/tmp/nexusdesk-t6-arch-shadow.zIfW0Y`. These are unversioned local temporary logs and may be removed by the system. The appendix embeds key commands, raw output, and counts so conclusions remain auditable after the logs or container disappear. Logs contain no environment values, credentials, or database URLs. Docker credentials exist only in permission-0600 temporary env files; this rerun only sourced the file safely and did not read, print, or copy its contents. The container remained running when this report was produced for independent review reruns and will later be cleaned up by the controller; T7 does not stop or remove it.

**R6 source/test delta and documentation categories**: F compared the original T7 SHA-256 inventory for 18 source modules and 7 test helper/top-level modules against the current tree. **Exactly two of 25 entries changed**: `backend/src/agent_platform/core_platform/agent_execution/registry/adapter_registry.py` and `backend/tests/test_agent_execution_registries.py`; the other 23 match. The former claim that all 25 files were unchanged no longer applies. R11/05 and related documentation changes are listed separately as documentation-only: the 12 tracked modified paths relative to baseline remain bilingual README/01～05 material, the bilingual 08 documents are existing untracked documentation, and 06/07 are subsequently produced test/acceptance reports. The current protected-path diff remains zero, and F reran the static checks, 81 non-PG regressions, and 34 PG nodes instead of reusing old green counts.

**Initial skips and closure of the environment gap**: all F focused commands had `0 skipped`. In the initial T6 regression run, 28 `test_runtime_postgres.py` cases and 6 `test_open_platform.py` cases skipped because a migrated dedicated PostgreSQL test database was unavailable; they were not recorded as passes at that time. With the user's explicit authorization, an independent Docker empty database was then migrated and the same 34 nodes produced **34 passed, 0 skipped, 0 failed**, closing the initial environment gap. The full suite and CI have still not run.

**Environment and data determinism**: fixed execution/tenant/agent UUIDs and fixed inputs are used. LocalTest/ContractProbe event IDs derive from execution ID and ordinal, and timestamps derive from a fixed epoch. Timeouts are triggered by a manual clock/event gates rather than real waiting determining semantics. F ran the complete LocalTest file twice consecutively (58 passed each) and the complete ContractProbe file twice consecutively (45 passed each), with identical counts and pass/skip semantics. The 25 common-suite methods expand to 37 common cases for each Adapter. LocalTest 58 = 37 common + 21 specific/adversarial/static cases; ContractProbe 45 = 37 common + 8 focused cases.

## 2. Execution Overview

| Item | Result | Evidence |
|---|---|---|
| contracts + registries | **457 passed, 0 skipped** (283 + 174) | Appendix A-1; F `contracts-registries.log` |
| LocalTestAdapter run 1 | **58 passed, 0 skipped** | Appendix A-2; F `localtest-run1.log` |
| LocalTestAdapter run 2 | **58 passed, 0 skipped** | Appendix A-2; F `localtest-run2.log` |
| ContractProbe run 1 | **45 passed, 0 skipped** | Appendix A-3; F `probe-run1.log` |
| ContractProbe run 2 | **45 passed, 0 skipped** | Appendix A-3; F `probe-run2.log` |
| Combined four-file focused run | **560 passed, 0 skipped** | Appendix A-4; F `four-file.log` |
| Explicit three UT-12 nodes | **3 passed, 0 skipped** | Appendix A-5; F `ut12-three-nodes.log` |
| Separate T5 second-Adapter structural node | **1 passed, 0 skipped** | Appendix A-6; F `t5-probe-structural-node.log` |
| Four explicit R6 same-factory/custom-equality nodes | **4 passed, 170 deselected, 0 skipped** | Appendix A-12; F `r6-four-selected.log`; subset of the 174, not additional independent coverage |
| Final Docker PostgreSQL rerun | **34 passed, 0 skipped, 0 failed** (28 + 6) | Appendix A-9; F `postgres-regression-final.log` |
| Existing regression total | **115 passed, 0 skipped, 0 failed** (81 non-PG + 34 Docker PG) | Appendix A-9; CM03/AC-8 local regression pass |
| F Ruff / format / core boundaries | lint passed; 25 files formatted; 9 passed | Appendix A-8 |
| Complete local pytest suite | **PENDING: not run** | §6, §9 |
| CI Backend / Frontend | **PENDING: not run; no URL** | §9 |

F's eight original T7 pytest commands above executed **1227 test nodes: 1227 passed, 0 skipped**. This includes intentional repeat runs and does not mean 1227 unique cases. The deduplicated focused set is the four-file **560 passed** result. The separate R6 four-node run and the per-file/combined non-PG reruns are repeated confirmations and are not added as new coverage. The separate final Docker rerun executed another **34 PG nodes: 34 passed, 0 skipped**. The deduplicated existing-regression set totals 81 + 34 = **115 passed**. Row dispositions are **23 UT/IT passes and all six CM01～06 passes: 29/29 passed**. The locally approved test-plan scope and exit evidence are now satisfied; full-suite/CI, final overall package review, and human acceptance remain separate downstream items.

### 2.1 AC Traceability and Disposition

| Acceptance criterion | Covering cases | Current disposition |
|---|---|---|
| AC-1 | P1-UT-01, P1-UT-02 | PASS (focused execution) |
| AC-2 | P1-IT-01, P1-IT-02 | PASS (both Adapters executed) |
| AC-3 | P1-IT-07, P1-IT-08 | PASS (both Adapters executed) |
| AC-4 | P1-UT-05, P1-UT-06, P1-IT-03～05, P1-CM-04 | PASS (focused safe-output execution) |
| AC-5 | P1-UT-08, P1-UT-09, P1-IT-10 | PASS (including independent structural node and same-factory cross-triple rejection) |
| AC-6 | P1-UT-08～P1-UT-11 | PASS (exact failure precedence, all duplicate registration, same-factory cross-triple and factory boundaries) |
| AC-7 | P1-IT-05, P1-IT-06, P1-IT-09, P1-IT-11 | PASS (including two-run determinism/cleanup verification) |
| AC-8 | P1-CM-01～06 | **PASS (local scope)**: static protection, 81 non-PG regressions, and 34 Docker PostgreSQL regressions all pass; full CI is separately PENDING |

### 2.2 Implementation Task Traceability

| Task | Report coverage | Current evidence |
|---|---|---|
| T2 contracts and package entry | P1-UT-01～07, P1-UT-12; AC-1/4 | contracts execution, cumulative UT-12 static node, D-01 |
| T3 Registry | P1-UT-08～12; AC-5/6 | 174 registry executions, cumulative UT-12 static node, D-02/D-07 |
| T4 LocalTestAdapter | P1-IT-01～09, P1-IT-11, P1-UT-12, P1-CM-04/05 | 58×2, 37 common cases, three UT-12 nodes, D-03/D-04/D-08 |
| T5 independent ContractProbe | P1-IT-10 and reuse of common P1-IT-01～09 | 45×2; separate structural node 1 passed; D-05 |
| T6 quality/regression evidence | P1-CM-01～06, AC-8, explicit UT-12/T5 nodes | T6 historical logs + F current-tree static, 81 non-PG, and independent Docker 34-PG executions; D-06 |

## 3. Unit Test (P1-UT) Case-by-Case Results

Every row below is an independent disposition. **Every parameterization of every cited parametrized case actually ran** in the corresponding logs; coverage was not inferred merely from filenames. Except for the special UT-12 evidence, results come from F `contracts-registries.log` (457 passed) and `four-file.log` (560 passed), all in the local in-memory environment.

| ID | Case | Expected result (synchronized with 04) | Test location (file::case) | Environment | Result | Evidence | Traceability |
|---|---|---|---|---|---|---|---|
| P1-UT-01 | Strict parameterized validation of six models | Valid values are preserved verbatim; invalid values raise ValidationError; strict mode rejects coercion and input is not trimmed | `tests/test_agent_execution_contracts.py::test_execution_base_reuses_contract_model_with_explicit_strict_frozen_policy`<br>`::test_valid_models_have_exact_fields_and_reject_unknown_fields`<br>`::test_models_reject_each_missing_required_field`<br>`::test_versions_and_serialized_computed_message`<br>`::test_exact_optional_and_status_defaults`<br>`::test_engine_and_protocol_identity_grammar`<br>`::test_adapter_version_grammar`<br>`::test_adapter_version_accepts_explicit_positive_versions`<br>`::test_request_opaque_fields_are_bounded_and_never_trimmed`<br>`::test_handle_and_event_opaque_fields`<br>`::test_request_raw_input_tenant_and_strict_scalar_rules`<br>`::test_positive_integer_fields_are_strict`<br>`::test_uuid_and_datetime_are_strict_in_python_but_idiomatic_in_json`<br>`::test_nested_json_values_reject_non_json_and_non_finite_numbers`<br>`::test_effective_capabilities_require_strict_boolean_values` (subsequent `::` entries inherit the same file path) | Local in-memory | **PASS** | All 283 contracts cases; A-1/A-4 | FR-1, AC-1 |
| P1-UT-02 | Default collection instance isolation | No mutable default is shared between instances; the other instance is unaffected | `tests/test_agent_execution_contracts.py::test_default_collections_are_not_shared_and_nested_values_remain_mutable` | Local in-memory | **PASS** | A-1/A-4 | FR-1, AC-1 |
| P1-UT-03 | DTO/Adapter cross-object identity consistency | A standalone DTO validates only itself; mismatched identities are rejected at the Adapter boundary/common suite and never repaired | `tests/test_agent_execution_contracts.py::test_handle_request_identity_boundary_rejects_every_key_mismatch`<br>`tests/test_agent_execution_contracts.py::test_request_adapter_identity_boundary`<br>`tests/test_agent_execution_contracts.py::test_result_and_event_handle_identity_boundary`<br>`tests/test_agent_execution_contracts.py::test_event_session_identity_boundary_includes_none`<br>`tests/test_local_test_adapter.py::TestLocalTestAdapter::test_request_identity_mismatch_fails_before_handle`<br>`tests/test_agent_execution_contract_probe.py::TestContractProbeAdapter::test_request_identity_mismatch_fails_before_handle` | Local in-memory | **PASS** | A-1～A-4; all parameterizations ran | FR-1, FR-2 |
| P1-UT-04 | Result terminal output/error combinations | completed+error, failed without error/with output/with cancelled error, and cancelled with output or error directly raise ValidationError; valid artifacts/usage/engine_metadata are allowed for every terminal state | `tests/test_agent_execution_contracts.py::test_every_result_output_error_combination`<br>`tests/test_agent_execution_contracts.py::test_result_rejects_non_terminal_or_unknown_status`<br>`tests/test_agent_execution_contracts.py::test_terminal_metadata_and_artifact_only_results_are_valid` | Local in-memory | **PASS** | All 18 combinations and other parameters; A-1/A-4 | FR-1, FR-2 |
| P1-UT-05 | Ten error categories, static messages, and safe round-trip | Each code has one category; direct `model_validate(model_dump())`, direct `model_validate_json(model_dump_json())`, and nested mapping/JSON round-trip successfully and preserve safe model_dump; the exact catalog message is only a no-op token and is recomputed; arbitrary/mismatched/non-string messages, or messages with missing/invalid code, raise ValidationError and never overwrite the computed property; exception/input/config/provider text and stacks do not leak | `tests/test_agent_execution_contracts.py::test_error_category_and_complete_static_code_catalog`<br>`tests/test_agent_execution_contracts.py::test_execution_error_mapping_round_trip_preserves_static_message`<br>`tests/test_agent_execution_contracts.py::test_execution_error_json_round_trip_preserves_static_message`<br>`tests/test_agent_execution_contracts.py::test_failed_result_mapping_round_trip_preserves_nested_static_error`<br>`tests/test_agent_execution_contracts.py::test_failed_result_json_round_trip_preserves_nested_static_error`<br>`tests/test_agent_execution_contracts.py::test_exact_direct_message_is_noop_integrity_token`<br>`tests/test_agent_execution_contracts.py::test_error_rejects_invalid_message_integrity_tokens`<br>`tests/test_agent_execution_contracts.py::test_failed_result_rejects_nested_arbitrary_message`<br>`tests/test_agent_execution_contracts.py::test_error_rejects_category_code_mismatch`<br>`tests/test_agent_execution_contracts.py::test_retryable_is_limited_to_explicit_retry_categories`<br>`tests/test_agent_execution_contracts.py::test_non_retryable_codes_reject_retryable_true`<br>`tests/test_agent_execution_contracts.py::test_error_rejects_unknown_or_non_string_enum_values`<br>`tests/test_agent_execution_contracts.py::test_error_details_reject_arbitrary_diagnostics`<br>`tests/test_agent_execution_contracts.py::test_error_details_allow_only_bounded_identity_and_slugs`<br>`tests/test_agent_execution_contracts.py::test_adapter_exceptions_and_normalization_never_expose_raw_exception_text`<br>`tests/test_agent_execution_contracts.py::test_safe_exceptions_suppress_implicit_context_in_formatted_tracebacks` | Local in-memory | **PASS** | 30-code catalog and all parameterizations; A-1/A-4; historical fix D-01 | FR-1, FR-4, AC-4, R9 |
| P1-UT-06 | Eleven EngineCapabilities declarations | Undeclared capabilities are strictly false; declaring tool_calling does not automatically change other capabilities or authorization; non-bool values are rejected | `tests/test_agent_execution_contracts.py::test_capabilities_have_exact_strict_defaults_and_no_implications`<br>`tests/test_agent_execution_contracts.py::test_each_capability_true_declaration_is_independent` | Local in-memory | **PASS** | All 11 fields parameterized; A-1/A-4 | FR-2, FR-4, AC-4 |
| P1-UT-07 | AgentEvent fields and determinism | Fields are valid; a standalone Event imposes no cross-event ordering; wall-clock/random default factories are forbidden | `tests/test_agent_execution_contracts.py::test_event_type_valid_grammar`<br>`tests/test_agent_execution_contracts.py::test_event_type_invalid_grammar`<br>`tests/test_agent_execution_contracts.py::test_event_sequence_is_required_strict_and_positive`<br>`tests/test_agent_execution_contracts.py::test_event_source_and_version`<br>`tests/test_agent_execution_contracts.py::test_event_requires_aware_datetime`<br>`tests/test_agent_execution_contracts.py::test_event_timestamp_is_normalized_to_utc_without_supplying_defaults`<br>`tests/test_local_test_adapter.py::test_default_event_ids_and_timestamps_have_fixed_uuid5_and_epoch_derivation`<br>`tests/test_agent_execution_contract_probe.py::test_fixed_event_derivation_and_fresh_runs_are_deterministic` | Local in-memory | **PASS** | All parameterizations and UUIDv5/fixed-epoch execution; A-1～A-4 | FR-4 |
| P1-UT-08 | Independent descriptor registration, duplicates, and references | Engine/Protocol can exist independently; identical and conflicting duplicates are rejected; unknown references are rejected; disabled entries can register but cannot resolve | `tests/test_agent_execution_registries.py::test_descriptors_are_strict_frozen_execution_contracts`<br>`tests/test_agent_execution_registries.py::test_descriptors_require_strict_boolean_enabled`<br>`tests/test_agent_execution_registries.py::test_engine_and_protocol_descriptors_validate_identity`<br>`tests/test_agent_execution_registries.py::test_adapter_descriptor_validates_explicit_version`<br>`tests/test_agent_execution_registries.py::test_registry_package_exports_only_public_registries_and_descriptors`<br>`tests/test_agent_execution_registries.py::test_engine_and_protocol_registries_are_independent_and_readable`<br>`tests/test_agent_execution_registries.py::test_duplicate_engine_always_fails_even_for_identical_descriptor`<br>`tests/test_agent_execution_registries.py::test_duplicate_protocol_always_fails_even_for_identical_descriptor`<br>`tests/test_agent_execution_registries.py::test_engine_and_protocol_registration_rejects_raw_configuration_safely`<br>`tests/test_agent_execution_registries.py::test_adapter_registration_requires_existing_references_in_priority_order`<br>`tests/test_agent_execution_registries.py::test_adapter_registration_allows_disabled_engine_and_protocol_references`<br>`tests/test_agent_execution_registries.py::test_duplicate_adapter_exact_triple_always_fails`<br>`tests/test_agent_execution_registries.py::test_same_factory_cannot_register_to_multiple_exact_triples` (three parameters: engine/protocol/adapter-version)<br>`tests/test_agent_execution_registries.py::test_distinct_factories_are_not_rejected_when_custom_equality_says_equal`<br>`tests/test_agent_execution_registries.py::test_registration_does_not_invoke_factory` | Local in-memory | **PASS** | All 174 registry cases; reuse of one factory across different Engine/Protocol/version triples is identified by `is` and rejected, and identity comparison does not invoke custom `__eq__`; the first triple remains resolvable and the second does not, with no partial second registration and no factory invocation during registration; distinct factories whose custom equality returns equal register and resolve independently. A-1/A-4/A-12; D-07 | FR-3, AC-5 |
| P1-UT-09 | Exact resolution and fresh-instance/weakref boundaries | Return the exact registered factory instance with no latest fallback; each resolution invokes the factory again, and two simultaneously live results are distinguished by `is not` and do not share state; second resolution of a live singleton and the third A→B→A result are rejected with `configuration_error/adapter_contract_mismatch` before escape; a non-weak-referenceable candidate is likewise rejected before its first return; weakref/gc proves the Registry does not retain Adapters, dead references are pruned during resolution, later new objects are unaffected by address reuse, identity never uses bare `id()`, and arbitrary `__eq__` is never called | `tests/test_agent_execution_registries.py::test_resolution_returns_the_exact_registered_factory_instance`<br>`tests/test_agent_execution_registries.py::test_every_resolution_constructs_fresh_state_isolated_instances`<br>`tests/test_agent_execution_registries.py::test_live_singleton_result_is_rejected_on_second_resolution`<br>`tests/test_agent_execution_registries.py::test_live_a_b_a_cycle_is_rejected_on_third_resolution`<br>`tests/test_agent_execution_registries.py::test_non_weak_referenceable_candidate_is_rejected_before_first_return`<br>`tests/test_agent_execution_registries.py::test_freshness_never_invokes_adapter_equality`<br>`tests/test_agent_execution_registries.py::test_registry_weakrefs_do_not_retain_adapters_and_dead_refs_are_pruned`<br>`tests/test_agent_execution_registries.py::test_weakref_tracking_failures_are_safe_or_propagate` | Local in-memory | **PASS** | Includes gc/weakref and all exception parameters; A-1/A-4; D-02 | FR-3, AC-5, R10 |
| P1-UT-10 | Unknown/disabled/incompatible resolution precedence | Return stable codes strictly in the order unknown_engine→engine_disabled→unknown_protocol→protocol_disabled→incompatible_engine_protocol→unknown_adapter_version→adapter_disabled | `tests/test_agent_execution_registries.py::test_resolution_error_precedence_including_combined_invalid_cases`<br>`tests/test_agent_execution_registries.py::test_resolution_never_falls_back_to_other_version_protocol_or_engine`<br>`tests/test_agent_execution_registries.py::test_malformed_or_unhashable_resolution_inputs_fail_closed` | Local in-memory | **PASS** | Eight precedence combinations and all malformed parameters; A-1/A-4 | FR-3, FR-4, AC-6 |
| P1-UT-11 | Factory/identity/Protocol signatures, awaitables, and BaseException boundaries | The first three classes map respectively to adapter_factory_failed, adapter_identity_mismatch, and adapter_contract_mismatch; bound methods use `Signature.bind` placeholders without execution, binding zero arguments for `get_capabilities` and one for each other four methods; wrong arity is adapter_contract_mismatch; instances do not escape before checks; synchronous resolve rejects factory-returned Future/Task as adapter_contract_mismatch and cancels it for cleanup, asserting `future.cancelled()`; the Task fixture must also be awaited for cleanup with no pending task; separate boundary cases verify that `CancelledError`/other `BaseException` control flow is neither swallowed nor rewritten, separately from Future/Task cleanup; diagnostics expose neither sensitive config nor raw exception text | `tests/test_agent_execution_registries.py::test_adapter_registration_rejects_invalid_or_async_factory_without_invocation`<br>`tests/test_agent_execution_registries.py::test_adapter_registration_rejects_factories_requiring_arguments`<br>`tests/test_agent_execution_registries.py::test_adapter_registration_accepts_zero_arg_compatible_signatures`<br>`tests/test_agent_execution_registries.py::test_adapter_registration_maps_signature_inspection_failure_safely`<br>`tests/test_agent_execution_registries.py::test_synchronous_factory_returning_coroutine_is_closed_and_rejected`<br>`tests/test_agent_execution_registries.py::test_factory_failures_are_safe_and_suppress_original_traceback_context`<br>`tests/test_agent_execution_registries.py::test_factory_control_flow_base_exceptions_propagate_unchanged`<br>`tests/test_agent_execution_registries.py::test_each_identity_field_mismatch_is_rejected_before_instance_escape`<br>`tests/test_agent_execution_registries.py::test_missing_malformed_identity_values_are_rejected`<br>`tests/test_agent_execution_registries.py::test_each_missing_identity_attribute_is_rejected`<br>`tests/test_agent_execution_registries.py::test_identity_property_access_failure_is_safe`<br>`tests/test_agent_execution_registries.py::test_identity_comparison_failure_is_safe_and_suppresses_context`<br>`tests/test_agent_execution_registries.py::test_each_missing_lifecycle_method_is_rejected`<br>`tests/test_agent_execution_registries.py::test_each_noncallable_lifecycle_method_is_rejected`<br>`tests/test_agent_execution_registries.py::test_async_contract_methods_reject_regular_function_shape`<br>`tests/test_agent_execution_registries.py::test_coroutine_function_stream_events_is_rejected_without_coroutine_leak`<br>`tests/test_agent_execution_registries.py::test_compliant_resolution_does_not_execute_any_lifecycle_method`<br>`tests/test_agent_execution_registries.py::test_lifecycle_shape_inspection_failures_are_safe`<br>`tests/test_agent_execution_registries.py::test_lifecycle_signature_inspection_failure_is_safe`<br>`tests/test_agent_execution_registries.py::test_lifecycle_inspection_base_exceptions_propagate_unchanged`<br>`tests/test_agent_execution_registries.py::test_each_lifecycle_method_rejects_wrong_bound_arity`<br>`tests/test_agent_execution_registries.py::test_zero_and_one_arg_compatible_lifecycle_signatures_remain_valid`<br>`tests/test_agent_execution_registries.py::test_future_returning_factory_is_rejected_and_future_is_cancelled`<br>`tests/test_agent_execution_registries.py::test_task_returning_factory_is_rejected_and_task_is_cleaned_up` | Local in-memory | **PASS** | Future/Task cleanup, nine wrong-arity combinations, and all control-flow parameters; A-1/A-4; D-02 | FR-3, AC-6, R3/R5/R10 |
| P1-UT-12 | Static dependency direction for common contracts, Registry, LocalTest, and package entry | Contracts do not import Registry/Worker/Repository/Factory/concrete Engine; Registry does not import concrete Adapters; LocalTestAdapter does not import Registry; package entry does not eagerly import test Adapters; existing ContractModel has zero diff; missing modules covered by the current task plan must fail, never skip or pass through absence, with the complete item finishing only at T4 | `tests/test_local_test_adapter.py::test_reusable_suite_has_no_concrete_adapter_import`<br>`tests/test_local_test_adapter.py::test_reusable_suite_uses_abstract_gate_construction`<br>`tests/test_local_test_adapter.py::test_cumulative_t2_t3_t4_modules_and_dependency_direction_are_exact` | Local static AST + in-memory | **PASS** | Explicit three nodes, 3 passed; collectively cover the exact 18-module existence/set, dependency direction, no-eager-import, common-suite import independence/abstract gate, and `ExecutionContractModel.__bases__ == (ContractModel,)`; A-5. The three nodes **do not check second-Adapter structure**; separate T5 evidence is A-6 | FR-6, G1 |

## 4. Contract and Integration Test (P1-IT) Case-by-Case Results

The common locations for the two Adapters are `tests/test_local_test_adapter.py::TestLocalTestAdapter` and `tests/test_agent_execution_contract_probe.py::TestContractProbeAdapter`. The table names the concrete inherited methods row by row. The 25 common methods expand to 37 common cases in each file, and every parameterization passed in both A-2/A-3 runs and the A-4 combined run. All use the local in-memory environment without DB, network, model, or real process.

| ID | Case | Expected result (synchronized with 04) | Test location (file::case) | Environment | Result | Evidence | Traceability |
|---|---|---|---|---|---|---|---|
| P1-IT-01 | Success, concurrent/repeated collection, second start/consumer | All five methods and identity properties work, LocalTest sequence is continuous, and every collection returns an equal completed Result; second start and both second-consumer attempts return `configuration_error/invalid_adapter_state`; stream replay/restart is forbidden | `tests/test_local_test_adapter.py::TestLocalTestAdapter::test_capabilities_start_stream_collect_success`<br>`tests/test_local_test_adapter.py::TestLocalTestAdapter::test_immediate_concurrent_and_repeated_collectors_share_result`<br>`tests/test_local_test_adapter.py::TestLocalTestAdapter::test_concurrent_second_consumer_and_claim_after_aclose_are_rejected`<br>`tests/test_agent_execution_contract_probe.py::TestContractProbeAdapter::test_capabilities_start_stream_collect_success`<br>`tests/test_agent_execution_contract_probe.py::TestContractProbeAdapter::test_immediate_concurrent_and_repeated_collectors_share_result`<br>`tests/test_agent_execution_contract_probe.py::TestContractProbeAdapter::test_concurrent_second_consumer_and_claim_after_aclose_are_rejected` | Local in-memory | **PASS** | Three common cases per Adapter; A-2～A-4 | AC-2, FR-2 |
| P1-IT-02 | Multiple events and empty events | Multiple events preserve order and payload; an empty event stream can directly produce a valid terminal result without hanging | `tests/test_local_test_adapter.py::TestLocalTestAdapter::test_multiple_events_preserve_order_payload_and_empty_stream_terminates`<br>`tests/test_agent_execution_contract_probe.py::TestContractProbeAdapter::test_multiple_events_preserve_order_payload_and_empty_stream_terminates` | Local in-memory | **PASS** | A-2～A-4 | FR-2, AC-2 |
| P1-IT-03 | Pre-start identity/EngineUnavailable/ResourceExhausted | All fail before a valid Handle is produced and are correctly classified; only explicit pre-start EngineUnavailable and ResourceExhausted may be retryable; post-start failure and timeout default to False, and Phase 1 does not retry | `tests/test_local_test_adapter.py::TestLocalTestAdapter::test_request_identity_mismatch_fails_before_handle`<br>`tests/test_local_test_adapter.py::TestLocalTestAdapter::test_prestart_errors_precede_handle_and_preserve_retryability`<br>`tests/test_agent_execution_contract_probe.py::TestContractProbeAdapter::test_request_identity_mismatch_fails_before_handle`<br>`tests/test_agent_execution_contract_probe.py::TestContractProbeAdapter::test_prestart_errors_precede_handle_and_preserve_retryability` | Local in-memory | **PASS** | Four prestart parameters per Adapter; A-2～A-4 | FR-2, FR-5, AC-4 |
| P1-IT-04 | Configuration/Protocol/Authentication/PermissionDenied | Each scenario maps to stable static category/code/message/retryable; Registry/Adapter boundaries do not copy original Pydantic values or exception strings | `tests/test_local_test_adapter.py::TestLocalTestAdapter::test_stream_errors_are_safe_for_stream_and_all_collectors`, parameters `configuration_error`, `protocol_error`, `authentication_error`, `permission_denied`<br>`tests/test_agent_execution_contract_probe.py::TestContractProbeAdapter::test_stream_errors_are_safe_for_stream_and_all_collectors`, same four parameters<br>`tests/test_agent_execution_registries.py::test_engine_and_protocol_registration_rejects_raw_configuration_safely` | Local in-memory | **PASS** | Four error parameters per Adapter; A-1～A-4 | AC-4, FR-4 |
| P1-IT-05 | Workspace/Internal/unknown exception/simulated process failure | Unknown exceptions map only to internal_error/internal_error; simulated failure maps to internal_error/simulated_process_failure; process_id is None, with no real Host assertion | `tests/test_local_test_adapter.py::TestLocalTestAdapter::test_stream_errors_are_safe_for_stream_and_all_collectors`, parameters `workspace_error`, `internal_error`<br>`tests/test_local_test_adapter.py::TestLocalTestAdapter::test_unknown_exception_and_simulated_process_failure_are_distinct_and_safe`<br>`tests/test_agent_execution_contract_probe.py::TestContractProbeAdapter::test_stream_errors_are_safe_for_stream_and_all_collectors`, same two parameters<br>`tests/test_agent_execution_contract_probe.py::TestContractProbeAdapter::test_unknown_exception_and_simulated_process_failure_are_distinct_and_safe` | Local in-memory | **PASS** | A-2～A-4 | AC-4, AC-7, FR-5 |
| P1-IT-06 | Manual-clock timeout | Wake waiters without real waiting and produce failed + timeout/execution_timeout; no automatic retry, and post-start timeout is non-retryable by default | `tests/test_local_test_adapter.py::TestLocalTestAdapter::test_manual_clock_timeout_wakes_collectors_without_real_waiting`<br>`tests/test_agent_execution_contract_probe.py::TestContractProbeAdapter::test_manual_clock_timeout_wakes_collectors_without_real_waiting` | Local in-memory, manual clock | **PASS** | A-2～A-4 | AC-7, FR-4 |
| P1-IT-07 | Long-running repeated/concurrent cancel and collection | Cancel is idempotent, gates are released and streams close, all collectors receive an equal cancelled Result (error=None), and owned/test tasks are all cleaned up | `tests/test_local_test_adapter.py::TestLocalTestAdapter::test_repeated_concurrent_cancel_closes_stream_and_collectors`<br>`tests/test_agent_execution_contract_probe.py::TestContractProbeAdapter::test_repeated_concurrent_cancel_closes_stream_and_collectors` | Local in-memory, event gate | **PASS** | A-2～A-4 | AC-3, FR-2 |
| P1-IT-08 | Cancellation/success race and late events | The first terminal state wins atomically; cancel after success is a no-op, success after cancellation is suppressed; no event is visible after terminal Result visibility, and no second terminal state exists | `tests/test_local_test_adapter.py::TestLocalTestAdapter::test_cancel_wins_gate_race_and_suppresses_late_events_and_success`<br>`tests/test_local_test_adapter.py::TestLocalTestAdapter::test_success_wins_gate_race_and_is_never_retroactively_cancelled`<br>`tests/test_local_test_adapter.py::TestLocalTestAdapter::test_terminal_visibility_never_precedes_queued_or_active_stream_events`<br>`tests/test_agent_execution_contract_probe.py::TestContractProbeAdapter::test_cancel_wins_gate_race_and_suppresses_late_events_and_success`<br>`tests/test_agent_execution_contract_probe.py::TestContractProbeAdapter::test_success_wins_gate_race_and_is_never_retroactively_cancelled`<br>`tests/test_agent_execution_contract_probe.py::TestContractProbeAdapter::test_terminal_visibility_never_precedes_queued_or_active_stream_events` | Local in-memory, event gate | **PASS** | Three cases per Adapter; A-2～A-4 | AC-3, FR-2 |
| P1-IT-09 | duplicate/conflict/gap/late/aclose | Exact duplicates and late events are yielded unchanged without advancing/lowering the high-water mark; conflicting content is event_identity_conflict; gaps are legal; timestamps do not sort; iterator close leaves no pending task | `tests/test_local_test_adapter.py::TestLocalTestAdapter::test_duplicates_late_events_gaps_and_timestamps_follow_sequence_rules`<br>`tests/test_local_test_adapter.py::TestLocalTestAdapter::test_same_event_id_with_different_content_is_never_repaired`<br>`tests/test_local_test_adapter.py::TestLocalTestAdapter::test_early_aclose_cleans_owned_tasks_and_does_not_permit_replay`<br>`tests/test_agent_execution_contract_probe.py::TestContractProbeAdapter::test_duplicates_late_events_gaps_and_timestamps_follow_sequence_rules`<br>`tests/test_agent_execution_contract_probe.py::TestContractProbeAdapter::test_same_event_id_with_different_content_is_never_repaired`<br>`tests/test_agent_execution_contract_probe.py::TestContractProbeAdapter::test_early_aclose_cleans_owned_tasks_and_does_not_permit_replay` | Local in-memory | **PASS** | A-2～A-4 | AC-7, FR-4 |
| P1-IT-10 | Register independent ContractProbe and reuse the complete common contract | The second Adapter is structurally independent and not a LocalTestAdapter subclass; the suite imports no concrete LocalTest type; common contracts, Registry interface, and Worker are unchanged | `tests/test_agent_execution_contract_probe.py::TestContractProbeAdapter` (inherits all 25 common methods, expanded to 37 cases)<br>`tests/test_agent_execution_contract_probe.py::test_registry_resolves_fresh_probe_instances_with_isolated_executions`<br>`tests/test_agent_execution_contract_probe.py::test_probe_has_no_local_test_inheritance_import_or_delegation`<br>`tests/test_local_test_adapter.py::test_reusable_suite_has_no_concrete_adapter_import`<br>`tests/test_local_test_adapter.py::test_reusable_suite_uses_abstract_gate_construction` | Local in-memory + static AST | **PASS** | Probe 45×2 (37 common + 8 focused); separate structural node 1 passed; A-3～A-6. The three UT-12 nodes do not carry this structural assertion | AC-5, G1, G2 |
| P1-IT-11 | Two complete LocalTest runs, stream failure/collector cancellation/cleanup | Semantics, errors, and event scripts are deterministic with no cross-scenario state; after success/failure/cancel/timeout/iterator close all owned tasks have been awaited/are done, with no Adapter-owned or test-created pending task; completed task references may be retained and checked with `all(done)`, while the pre-execution empty-set assertion remains a separate condition | `tests/test_local_test_adapter.py` (complete file, two runs)<br>`tests/test_local_test_adapter.py::TestLocalTestAdapter::test_one_cancelled_collector_does_not_cancel_shared_execution`<br>`tests/test_local_test_adapter.py::TestLocalTestAdapter::test_lone_collector_cancellation_cleans_owned_work_before_propagation`<br>`tests/test_local_test_adapter.py::TestLocalTestAdapter::test_stream_errors_are_safe_for_stream_and_all_collectors`<br>`tests/test_local_test_adapter.py::test_close_broadcasts_to_every_pending_anext_waiter`<br>`tests/test_local_test_adapter.py::test_cancel_propagates_new_caller_cancellation_after_runner_cleanup`<br>`tests/test_local_test_adapter.py::test_aclose_propagates_new_caller_cancellation_after_finished_runner_drains` | Local in-memory | **PASS** | Two consecutive runs, both 58 passed, 0 skipped, with identical counts/semantics; all owned tasks are awaited/done with no pending task, completed references are retained and checked with `all(done)`, and pre-execution empty-set is independent; A-2. Includes 37 common + 21 LocalTest-specific/adversarial/static cases | AC-7, FR-5, R11 |

## 5. Common Check (P1-CM) Case-by-Case Results

| ID | Check | Pass criterion (synchronized with 04) | Test location/command | Environment | Result | Evidence | Traceability |
|---|---|---|---|---|---|---|---|
| P1-CM-01 | Database migrations unchanged | `alembic heads` is `0057_industry_pack_runtime`; relative to `4dfcfb41e9cbb799753986c2d76134514bbd19be`, no version file was added/modified and no downgrade is needed | `uv run alembic heads`<br>independent Docker empty-database `alembic upgrade head` and post-test `alembic current`<br>`git diff --exit-code 4dfcfb41e9cbb799753986c2d76134514bbd19be -- backend/migrations/versions/` | Local read-only + independent Docker empty-database migration | **PASS** | F `alembic-heads.log` and `protected-paths.*`; T6 `gate6-*`; initial Docker `RESULTS.txt` and `alembic-upgrade.log`, plus F `postgres-alembic-current-final.log`: initial upgrade exit 0, with current heads/current both `0057_industry_pack_runtime (head)`; A-7/A-9 | AC-8, G4 |
| P1-CM-02 | Zero production wiring and unchanged configuration | Worker/Factory/composition roots do not call the new execution path; no new runtime switch, Settings, external Engine, credentials, frontend, or deploy changes | Protected-path `git diff --exit-code` against baseline: existing ContractModel/runtime, Worker/Repository/Factory/composition, Settings, env examples, frontend, deploy, migrations, lock | Local read-only working-tree check | **PASS** | F current protected-path diff=0; exactly two expected R6 files changed among the 25 Python SHA entries, with other changes separately categorized as documentation/reports; T6 `protected-paths-zero-diff.*` and `change-allowlist-check.*` are historical comparisons only; A-7/A-11 | AC-8, FR-6 |
| P1-CM-03 | Public API/SSE/Run contract compatibility | RunRequest/RunSnapshot/RunStatus, event names, and routes are unchanged; relevant existing Runtime/API/SSE tests are all green | `tests/test_runtime_engine.py`<br>`tests/test_runtime_postgres.py`<br>`tests/test_open_platform.py`<br>`tests/test_extension_contracts.py`<br>`tests/test_runtime_baseline.py` | F local non-PG + actual execution against the migrated independent Docker PostgreSQL 17 database | **PASS** | 81 non-PG passed (17+56+8) + 34 Docker PG passed (28 runtime_postgres + 6 open_platform) = **115 passed, 0 skipped, 0 failed**; final rerun exit 0, 14.10s; A-9 | AC-8, FR-6 |
| P1-CM-04 | Sensitive information and logs | DTO/Registry/Adapter safe output contains no secret-marker, credentials, connection strings, original Pydantic values, raw exception text, original stack, or customer input | `tests/test_agent_execution_contracts.py::test_error_details_reject_arbitrary_diagnostics`<br>`tests/test_agent_execution_contracts.py::test_adapter_exceptions_and_normalization_never_expose_raw_exception_text`<br>`tests/test_agent_execution_contracts.py::test_safe_exceptions_suppress_implicit_context_in_formatted_tracebacks`<br>`tests/test_agent_execution_registries.py::test_factory_failures_are_safe_and_suppress_original_traceback_context`<br>`tests/test_local_test_adapter.py::TestLocalTestAdapter::test_pre_chained_safe_stream_error_does_not_retain_raw_exception_chain`<br>`tests/test_local_test_adapter.py::test_scenario_deepcopy_runtime_failure_is_safe_invalid_scenario`<br>`tests/test_local_test_adapter.py::test_runtime_origin_safe_error_does_not_retain_raw_exception_chain`<br>`tests/test_agent_execution_contract_probe.py::TestContractProbeAdapter::test_pre_chained_safe_stream_error_does_not_retain_raw_exception_chain` | Local in-memory; synthetic `secret-marker`, no real secret logged | **PASS (focused scope)** | 457, 58×2, 45×2, and 560 all pass; A-1～A-4; D-01/D-02/D-04 | AC-4, non-functional |
| P1-CM-05 | Multi-tenant and instance boundaries | tenant_id is not rewritten by the registry; different request/resolved instances have no observable shared state; event high-water exists only per active execution | `tests/test_agent_execution_registries.py::test_every_resolution_constructs_fresh_state_isolated_instances`<br>`tests/test_local_test_adapter.py::test_registry_resolves_exact_identity_with_two_live_isolated_instances`<br>`tests/test_local_test_adapter.py::TestLocalTestAdapter::test_deterministic_fresh_runs_have_no_cross_instance_high_water`<br>`tests/test_agent_execution_contract_probe.py::test_registry_resolves_fresh_probe_instances_with_isolated_executions`<br>`tests/test_agent_execution_contract_probe.py::TestContractProbeAdapter::test_deterministic_fresh_runs_have_no_cross_instance_high_water` | Local in-memory | **PASS (focused scope)** | Independent execution/high-water and fresh resolution pass for both Adapters; A-1～A-4 | FR-1, FR-3, non-functional |
| P1-CM-06 | Code quality and dependency boundaries | New tests plus `ruff check src tests`, affected-file `ruff format --check`, and `test_core_boundaries.py` are all green; R8 dependency direction holds and `backend/uv.lock` has zero diff | `uv run ruff check src tests`<br>`uv run ruff format --check <25 Phase 1 source/test files>`<br>`uv run pytest -q tests/test_core_boundaries.py`<br>three UT-12 nodes, clean-source architecture shadow, uv.lock/protected diff | F current-tree static, boundary, and protected-diff execution | **PASS (static/boundary scope; raw-tree issue retained)** | lint passed; 25 files formatted; 9 passed; UT-12 3 passed; new clean-shadow architecture passed; uv.lock diff=0; A-5/A-8/A-10/A-11. Raw tree still exits 1 solely for four ignored legacy roots; see R-02 and never call the raw gate green | FR-6, G1 |

## 6. Regression Scope

| Regression file | Actual result | Disposition/boundary |
|---|---|---|
| `tests/test_runtime_engine.py` | 17 passed | PASS (F current-tree rerun) |
| `tests/test_extension_contracts.py` | 56 passed | PASS (F current-tree rerun, including existing ContractModel/Extension ports) |
| `tests/test_runtime_baseline.py` | 8 passed | PASS (F current-tree rerun, Phase 0 baseline local regression) |
| `tests/test_runtime_postgres.py` | **28 passed** | PASS (F final independent Docker PG rerun; all initial 28 environment skips closed) |
| `tests/test_open_platform.py` | **6 passed** | PASS (F final independent Docker PG rerun; all initial 6 environment skips closed) |
| Total | **115 passed, 0 skipped, 0 failed** | 81 non-PG + 34 Docker PG; the separate combined non-PG command also produced 81 passed as repeated confirmation and is not added; CM03 and AC-8 local regression criteria pass |
| `tests/test_core_boundaries.py` | 9 passed | PASS (F current-tree rerun) |
| Complete `uv run pytest` | Not run | PENDING; full suite is reserved for CI by repository convention, and the selected-regression total is not represented as the full suite |

There is no production wiring or new-field empty-state behavior requiring a runtime-switch check. Protected-path zero diff and the 115 regressions above support the local compatibility conclusion. Agent snapshots, model Profiles, Memory, and other modules are only indirectly part of the unrun full suite; this report does not claim they were executed separately.

## 7. Defects Found and Fixed During the Iteration

D-01～D-06 come from historical T2～T6 implementation/spec/quality reviews and test evidence; D-07 is the R6 coverage miss found by the final overall review, and D-08 is the R11/05 documentation clarification. **This final T7 did not replay the historical RED states**, but A-12 cites independently preserved R6 RED-first raw evidence. Every fix is in the current **uncommitted working tree**, and this report invents no commit SHA. The “current regression” column records only actual F green verification, documentation-consistency checks, and locations; it does not mean the full suite/CI has passed.

| # | Severity | Defect | Found during | Fix | Current regression |
|---|---|---|---|---|---|
| D-01 | P1 | T2 safe exceptions could still expose implicit traceback context; R9 static read-only message behavior was inconsistent across direct/nested mapping/JSON round-trip boundaries | T2 implementation/security and serialization review | Uncommitted working tree: suppress implicit exception context; accept only the exact static message as a no-op integrity token and reject arbitrary/mismatched tokens | `test_safe_exceptions_suppress_implicit_context_in_formatted_tracebacks`, four direct/nested mapping/JSON round-trip cases, and invalid-message parameters all pass in 457/560; A-1/A-4 |
| D-02 | P1 | T3 lifecycle introspection/wrong bound-signature arity checks were unsafe or inaccurate; R10 singleton, A→B→A, non-weakref/dead-reference behavior could violate fresh-instance guarantees | T3 spec/quality review | Uncommitted working tree: safe bound-signature checks; weakref-identity live-instance rejection and cleanup without invoking custom equality | `test_each_lifecycle_method_rejects_wrong_bound_arity`, inspection safe/control-flow, singleton, A→B→A, weakref/gc, and `test_freshness_never_invokes_adapter_equality` all pass; A-1/A-4 |
| D-03 | P1 | T4 pending `anext` was not awakened by close; claimed-empty/fully-delivered paused collection could hang; the common suite constructed gates directly, preventing independent Adapter reuse | T4 spec review | Uncommitted working tree: close/terminal wakeup and completed-collection fixes; common suite now uses abstract `make_gate` | `test_pending_anext_is_woken_by_aclose_without_external_cancel`, `test_claimed_empty_stream_does_not_block_successful_collection`, and `test_delivered_only_event_does_not_require_an_extra_poll_before_result` pass for both Adapters; `test_reusable_suite_uses_abstract_gate_construction` passes in the three UT-12 nodes; A-2～A-5 |
| D-04 | P1 | T4 close did not broadcast to every waiter; caller-vs-runner cancellation was conflated; scenario/runtime paths could retain raw exception chains; hostile deepcopy was not safely handled | T4 quality review | Uncommitted working tree: broadcast/task cleanup, caller-cancellation repropagation, safe exception normalization; runtime gate path included in the same safe boundary | `test_close_broadcasts_to_every_pending_anext_waiter`, cancel/aclose caller cancellation, deepcopy RuntimeError/BaseException, and `test_runtime_origin_safe_error_does_not_retain_raw_exception_chain` all pass; A-2/A-4 |
| D-05 | P1 | T5 cancellation of `anext` after channel handoff lost acknowledgement and could deadlock `collect_result`/`aclose` | T5 adversarial test/quality review | Uncommitted working tree: exactly-once suppression acknowledgement for the handed-off item, cleaning outstanding/channel for both success and subsequent stream failure | `test_cancelled_anext_after_channel_handoff_does_not_strand_item[successful-completion]` and `[following-stream-failure]` pass in probe 45×2 and 560; A-3/A-4 |
| D-06 | P3 | T6 temporary manifest wording had attributed second-Adapter structural evidence to the three UT-12 nodes, making evidence attribution unclear | T6 evidence review | Temporary evidence wording outside the uncommitted working tree was corrected; UT-12 and T5 structural logs are separate, with no commit-SHA claim | F again separately executed UT-12 3 nodes and `test_probe_has_no_local_test_inheritance_import_or_delegation` 1 node; all pass; A-5/A-6 |
| D-07 | P1 | Final overall review found missing coverage for R6's rule that one no-arg factory must not register multiple exact triples; the same factory could be registered across Engine/Protocol/version triples, violating the one-to-one descriptor/factory identity boundary | 2026-11-09 final overall review; tests were added first and produced RED evidence of 3 failed + 1 custom-equality control passed before the implementation change | `adapter_registry.py` uses `is` to detect registered factory identity and reject cross-triple reuse without custom `__eq__`; `test_agent_execution_registries.py` adds three cross-triple rejection parameters and a distinct-identity/custom-equality-equal control | F explicit four nodes: 4 passed, 170 deselected; all 174 Registry, 457 contracts+registries, and 560 four-file cases pass; the first triple resolves, the second does not, no partial registration occurs, and custom equality does not determine identity; A-1/A-4/A-12 |
| D-08 | P3 | Before R11, some owned-task wording conflated “no pending task at the end” with “the Adapter-owned task set is empty at the end,” failing to distinguish retainable completed references from the pre-execution empty set; the 05 status header also needed to match the local automated evidence already formed | 2026-11-09 final documentation review | Documentation-only: 03/04/05/08 and related documents clarify that all owned tasks are awaited/done, completed references may be retained and checked with `all(done)`, and pre-execution empty-set is independent; the 05 header now states local automated evidence exists but formal acceptance is incomplete; no lifecycle code changed | F LocalTest runs both passed 58 with IT-11 expected result/traceability synchronized to R11; bilingual 06 consistency and Python SHA-delta checks confirm no additional Python change for this item; A-2/A-11 |

**Open-defect conclusion**: within the reviewed, locally executable implementation scope, D-01～D-07 have current passing regressions, D-08 has completed documentation-only clarification with current behavior/consistency checks, and no known open implementation P0/P1 remains. R-01～R-04 are downstream CI, environment, or formal-acceptance items; they neither invalidate the local test conclusion nor constitute human approval.

## 8. Residual Risks

| # | Severity | Description | Disposition (suggested owner / next evidence) |
|---|---|---|---|
| R-01 | P1 downstream testing | The complete local suite and GitHub Actions CI were not run and there is no run URL; these selected tests do not prove every other existing module or full frontend/all-suite compatibility | **Owner: subsequent commit/PR and CI maintainers**. Obtain full CI results and a run URL through a later authorized submission flow, adding any necessary regressions; this report does not initiate commit, push, or PR |
| R-02 | P2 local environment | Raw `check_architecture.py` still exits 1 and reports only the four pre-existing ignored legacy roots `modules/apps/integrations/platform`; the identical clean-source shadow gate passes. The raw command must not be called green, and ignored artifacts must not be deleted merely to obtain a green result | **Owner: repository/architecture-gate maintainers**. Recheck using a clean checkout or raw CI logs; retain both raw exit 1 and clean-shadow pass evidence before deciding on a non-destructive local ignored-artifact cleanup strategy |
| R-03 | P1 acceptance entry | The Phase 0 formal acceptance-entry risk remains open; Phase 1 implementation and testing do not constitute Phase 0 approval | **Owner: Phase 0 acceptance owner**. Provide formal acceptance/signoff evidence and confirm the entry before Phase 1 formal acceptance proceeds; satisfying the Phase 1 local test exit does not approve an earlier phase |
| R-04 | P1 formal acceptance | Bilingual `07-acceptance-report.md` / `07-acceptance-report.en.md` now exist and record local automated A1～A8 and C1～C4 engineering evidence; formal human acceptance, Adapter-representative UAT, role signatures, and final overall package review remain unapproved/incomplete. Local 29/29 passage and the existence of 07 do not automatically become business/formal acceptance | **Owner: Phase 1 acceptance owner and final package-review owner**. Use 07 as input to complete the final overall package review, human UAT, formal acceptance, and signatures with independent evidence; T7 does not perform that role |

## 9. CI Evidence

- PR: **not created (T7 explicitly performs no commit/push/PR)**.
- CI run: **PENDING; not run; no URL, head SHA, or conclusion=success claim**.
- Complete local `uv run pytest`: **PENDING; not run**.
- Local conclusion: F current-tree focused/static execution, T6 historical artifacts, and the final independent Docker PostgreSQL rerun jointly cover all 29 P1-UT/IT/CM rows. Local test evidence for AC-1～8 is reproducibly green, with 115 passed and 0 skipped across the deduplicated selected affected regressions. The locally approved scope and exit evidence in `04-test-plan.md` §7 are **satisfied**.
- Downstream boundary: the full suite and Frontend/Backend CI jobs were not verified. Bilingual 07 reports now contain local automated engineering evidence, but the final overall package review, formal Phase 1 human acceptance, UAT, and signatures remain incomplete. This report does not claim CI success, Phase 0 entry approval, final overall package approval, or formal Phase 1 acceptance.

## Appendix A Local Execution Output Snapshots (execution coverage 2026-11-08～2026-11-09; F ran on 2026-11-09)

Unless stated otherwise, pytest commands ran from `backend/`; every F focused command exited 0.

### A-1 contracts + registries (457)

```bash
uv run pytest -q tests/test_agent_execution_contracts.py tests/test_agent_execution_registries.py
```

```text
457 passed in 0.28s
```

Independent `--collect-only` confirmed 283 contracts and 174 registries, totaling 457, with no skips.

### A-2 Two consecutive LocalTestAdapter runs (58 + 58)

```bash
uv run pytest -q tests/test_local_test_adapter.py
uv run pytest -q tests/test_local_test_adapter.py
```

```text
# run 1
58 passed in 0.13s
# run 2
58 passed in 0.14s
```

Both were complete-file runs with 0 skipped. `--collect-only` collected exactly 58: 37 common-class cases, plus 9 top-level invalid-scenario parameters and 12 other LocalTest-specific/adversarial/static nodes.

### A-3 Two consecutive ContractProbe runs (45 + 45)

```bash
uv run pytest -q tests/test_agent_execution_contract_probe.py
uv run pytest -q tests/test_agent_execution_contract_probe.py
```

```text
# run 1
45 passed in 0.10s
# run 2
45 passed in 0.10s
```

Both were complete-file runs with 0 skipped. The exact composition is 25 inherited common methods expanded to 37 cases, plus 6 single-node focused cases and 2 cancelled-handoff parameters, totaling 45; the cancelled-handoff regression is included.

### A-4 Combined four-file focused run (560)

```bash
uv run pytest -q tests/test_agent_execution_contracts.py tests/test_agent_execution_registries.py tests/test_local_test_adapter.py tests/test_agent_execution_contract_probe.py
```

```text
560 passed in 0.42s
```

283 + 174 + 58 + 45 = 560, with 0 skipped and 0 failed.

### A-5 Explicit three UT-12 nodes (3)

```bash
uv run pytest -q \
  tests/test_local_test_adapter.py::test_reusable_suite_has_no_concrete_adapter_import \
  tests/test_local_test_adapter.py::test_reusable_suite_uses_abstract_gate_construction \
  tests/test_local_test_adapter.py::test_cumulative_t2_t3_t4_modules_and_dependency_direction_are_exact
```

```text
3 passed in 0.07s
```

Together the three nodes verify no concrete Adapter import in the common suite, abstract gate construction, the exact T2+T3+T4 18-module set/existence, dependency direction, no-eager-test-import, and direct `ExecutionContractModel` inheritance from `ContractModel`. They do not verify second-Adapter structure.

### A-6 Separate T5 structural node (1)

```bash
uv run pytest -q tests/test_agent_execution_contract_probe.py::test_probe_has_no_local_test_inheritance_import_or_delegation
```

```text
1 passed in 0.05s
```

This node independently verifies that ContractProbe has no LocalTest inheritance, import, or delegation; it is not one of the three A-5 nodes.

### A-7 Current read-only CM01/CM02 spot checks

```bash
uv run alembic heads
# 0057_industry_pack_runtime (head)

git diff --exit-code 4dfcfb41e9cbb799753986c2d76134514bbd19be -- <04/T6 protected paths>
# no output, exit 0
```

F `protected-paths.log` is empty with exit 0. Migrations, uv.lock, Worker/Factory/composition, Settings, env examples, and frontend/deploy all retain zero diff. `source-test-sha256-delta.log` is no longer empty: exactly the two expected R6 Python files, `adapter_registry.py` and `test_agent_execution_registries.py`, changed among 25 entries, while the other 23 match. Documentation/report deltas are categorized separately; the old zero-difference inventory does not substitute for current evidence.

### A-8 F current-tree static quality evidence

```text
uv run ruff check src tests
All checks passed!

uv run ruff format --check <25 Phase 1 files>
25 files already formatted

uv run pytest -q tests/test_core_boundaries.py
9 passed in 0.59s
```

### A-9 Existing regressions, independent Docker migration, and final 34-PG rerun

F current-tree raw non-PG results:

```text
runtime_engine:       17 passed in 0.46s
extension_contracts:  56 passed in 0.81s
runtime_baseline:      8 passed in 0.31s
Deduplicated non-PG subtotal: 81 passed, 0 skipped, 0 failed
Combined non-PG repeat check:  81 passed in 0.95s (not added to per-file results)
```

The initial T6 combined command produced `81 passed, 34 skipped in 1.44s`; at that time 28 runtime_postgres and 6 open_platform nodes had not executed because a dedicated migrated PG database was unavailable, and they were not counted as passes. `gate5-postgres-skipped-node-collection.log` preserves those exact 34 nodes and identifies the same set for the later rerun.

The user-authorized independent environment is `nexusdesk-phase1-pg-838b99d6` (`pgvector/pgvector:pg17`), using a dedicated empty database/volume and loopback dynamic port. Existing `nexusdesk-phase0-postgres` was neither reused nor modified. Credentials exist only in permission-0600 temporary env files; the following commands source them safely without displaying their contents.

```bash
set -a; . /tmp/nexusdesk-phase1-pg-4ph_1qsi/test.env; set +a
uv run --directory backend alembic upgrade head
# Initial RESULTS.txt records exit 0; heads = 0057_industry_pack_runtime (head)

uv run --directory backend pytest -q tests/test_runtime_postgres.py tests/test_open_platform.py
uv run --directory backend alembic current
```

The initial corrected rerun produced `34 passed in 14.06s`, closing the original 34 environment skips. F executed the **same 34 nodes** again on 2026-11-09; raw output and post-test migration state are:

```text
..................................                                       [100%]
34 passed in 14.10s

post-test alembic current:
0057_industry_pack_runtime (head)
```

F `postgres-regression-final.exit` is 0 with **28 + 6 = 34 passed, 0 skipped, 0 failed**. This is the current-tree rerun after the initial closure and does not turn two runs into 68 unique cases. The first historical wrapper invocation had a bookkeeping error involving zsh's read-only `status` variable, so its exit code was unreliable and it is **not formal evidence**; initial formal evidence cites only the corrected rerun using `rc` and capturing exit 0, while current formal evidence cites F's independent command/log/exit triple. This report contains no password, URL, or env-file contents. The container remains available for independent review reruns and will later be cleaned by the controller; the embedded output keeps the result auditable after cleanup.

### A-10 Raw architecture and clean-source shadow

```text
raw tree exit 1:
architecture gate failed:
 - legacy runtime root still exists: .../agent_platform/modules
 - legacy runtime root still exists: .../agent_platform/apps
 - legacy runtime root still exists: .../agent_platform/integrations
 - legacy runtime root still exists: .../agent_platform/platform

clean source-only shadow exit 0:
architecture gate passed
```

F `legacy-roots-ignored-status.log` proves all four roots are ignored, and tracked/unignored file lists are empty; there is no additional architecture failure. Both raw exit 1 and clean-shadow exit 0 come from the F current tree and are retained in R-02 without concealment.

### A-11 Evidence Inventory and Scope

F retains a same-named `.command`, `.log`, and `.exit` triple for every primary command cited in this report, including the eight original T7 focused pytest commands, the four R6 nodes, four collection commands, lint/format/core boundaries, per-file and combined non-PG regressions, Alembic heads/current, protected paths, raw/clean architecture, and the final 34-PG rerun. Key collection logs are `collect-contracts.log`, `collect-registries.log`, `collect-localtest.log`, and `collect-probe.log`. Auxiliary evidence such as SHA diffs and final bilingual/scope checks retains the files actually recorded and is not claimed to have triples for every item. One inapplicable auxiliary `check-ignore` attempt is also preserved as `legacy-roots-check-ignore-attempt.*`; formal ignored-root evidence uses `git status --short --ignored`. T6 `MANIFEST.txt` is only a historical gate and initial `81 passed, 34 skipped` comparison, while the R6 root independently preserves raw RED/fix/format evidence. Temporary logs are unversioned and may be ephemeral; the commands, counts, and key output in this appendix are the report's persistent audit summary.

### A-12 R6 Same-Factory Cross-Triple RED-First and Final Fix Evidence

The final overall review found that the original tests did not cover R6's rule that one no-arg factory belongs to only one exact triple. The independent fix-evidence root `/tmp/nexusdesk-phase1-r6-fix-evidence` preserves the test-before-implementation sequence; **F did not replay that historical RED**. Before the implementation fix, the actual `r6-red.command/.log/.exit` result was exit 1:

```bash
uv run pytest tests/test_agent_execution_registries.py -k \
  'same_factory_cannot_register_to_multiple_exact_triples or distinct_factories_are_not_rejected_when_custom_equality_says_equal'
```

```text
collected 174 items / 170 deselected / 4 selected
tests/test_agent_execution_registries.py FFF.
FAILED ...test_same_factory_cannot_register_to_multiple_exact_triples[engine]
FAILED ...test_same_factory_cannot_register_to_multiple_exact_triples[protocol]
FAILED ...test_same_factory_cannot_register_to_multiple_exact_triples[adapter-version]
3 failed, 1 passed, 170 deselected in 0.12s
```

All three RED cases showed that registering the second triple did not raise `ConfigurationError`; the passing control established that two distinct factories whose custom `__eq__` reports equality must not be falsely rejected. The implementation then uses `is` to compare identity against existing factories and rejects reuse of the same factory across Engine/Protocol/version triples, without `__eq__` or bare `id()`. Each test parameter asserts `duplicate_adapter` for the second registration, no factory invocation during registration, continued resolution of the first triple with exactly one constructed instance, expected-priority non-resolution of the second triple, and no partial registration; the custom-equality control resolves v1/v2 independently.

R6 `r6-new-post-fix.log` records `4 passed, 170 deselected in 0.06s`, `r6-registries-post-fix.log` records `174 passed in 0.16s`, and `r6-four-focused-final.log` records `560 passed in 0.45s`. F independently executed the same four-node selection on the current tree:

```text
4 passed, 170 deselected in 0.05s
457 passed in 0.28s   # contracts + registries
560 passed in 0.42s   # four-file
```

These are repeated confirmations of a passing subset and combined suite, not additions to the 560 deduplicated focused cases. Initial R6 `r6-ruff-format-check-initial.log/.exit` preserves the intermediate exit 1 and `1 file would be reformatted, 1 file already formatted`; after the formatting correction, `r6-ruff-format-check.log/.exit` is exit 0 with `2 files already formatted`. F separately ran repository-wide `ruff check src tests` (All checks passed) and the 25-file Phase 1 format check (25 files already formatted), both exit 0. The intermediate format failure was neither hidden nor deleted by the final success.
