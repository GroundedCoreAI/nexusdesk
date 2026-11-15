# Phase 3 · 能力、配置与指令 — 测试报告

> 状态：已完成（本轮为实际执行取证；C11 = `not_measured`；`ruff format` scoped 检查存在 3 个本阶段文件的实际偏差；本报告不作阶段结论，结论归 07）
> 创建：2026-11-13
> 执行：T10 测试执行代理（独立取证，不修代码、不裁定；本报告不预判 07 结论）
> 依据：`04-test-plan.md`（P3-UT-01～28、P3-IT-01～22、P3-CM-01～10、§6.1 P3-FE 登记表、§7 出口）、`05-acceptance-plan.md`（A1～A11/C1～C11/M1～M3，本报告不执行验收）、`03-technical-design.md`、`08-implementation-breakdown.md`（§1 规则、§5、R-37/R-38/R-39）
> 编号读取时点：本报告按 **2026-11-13 21:00 CST** 读取的 `04-test-plan.md` 工作树内容映射（该版本已含 P3-UT-27/28、P3-IT-21/22，文件 mtime `2026-11-13 21:00:20 +0800`）。04 与 08/03/05/README 在本轮执行期间由另一条文档线并行修订；若编号或其判据在落笔后继续变化，映射以本节记录的读取时点为准，不得追溯修改本报告数字。
> 前置：本报告只在真实执行后记录命令与输出尾部；未执行、环境缺失或样本不足一律写 `pending_env` / `not_measured`，不写成通过。

## 1. 测试范围与环境

**范围**：本轮对 T2～T9 的全部受影响测试与静态检查做实际取证：迁移 `0058_agent_execution_metadata`、FR-9 settings、类型化 ExecutionConfig 与 canonical 兼容、四层能力与受信端口/缓存/warmer、五快照与写屏障、Instruction Provider 与 React 指令 parity、执行集成（四态矩阵与启动屏障）、preview API 与 422 安全审计、execution-config-flags、前端配置页与四语言 Playwright，以及 Phase 0～2 回归面。**本报告不执行验收、不执行 seed/quickstart、不执行全量 CI、不做生产性能结论。**

| 项 | 实测值 | 取证方式 |
|---|---|---|
| 分支 | `feat/agent-execution-platform-v2-phase3` | `git rev-parse --abbrev-ref HEAD` |
| HEAD SHA | `37b08f8a812558b7d80e33987fd496e9145410dc` | `git rev-parse HEAD` |
| 工作树未提交条目 | `git status --porcelain \| wc -l` = **44**（36 修改 + 8 未跟踪；不含本报告自身新增的 2 个文件） | E21 |
| 未提交分布 | `backend/src` 修改 18、`backend/tests` 修改 7、`docs/` 修改 10、`frontend/` 修改 1；未跟踪 8 项（`applications/security_audit.py`、`capability/production.py`、`contracts/instructions.py`、`core_platform/agent_execution/instructions/` 目录、`test_agent_execution_phase3_{flags,instructions,preview,wiring}.py`） | E21 |
| 操作系统 | Darwin 27.0.0（macOS），时区 `+0800` CST | `date`、系统信息 |
| 后端工具链 | Python 3.11.9、uv 0.11.3 | `uv run --directory backend python -V`、`uv --version` |
| 前端工具链 | node v25.6.1（Vite dev server 已运行于 `127.0.0.1:5173`，PID 95324，Playwright `reuseExistingServer`） | `node -v`、`curl 127.0.0.1:5173` → 200 |
| PostgreSQL | 容器 `nexusdesk-phase3-pg`（镜像 `pgvector/pgvector:pg17`，状态 running，`127.0.0.1:55433->5432/tcp`，已运行 28 小时） | `docker ps`、`docker inspect` |
| 迁移 head | `alembic heads` = `0058_agent_execution_metadata (head)`；`alembic current` = 同一修订 | E19、E20 |
| 角色属性实测 | `select rolname, rolcreatedb, rolsuper ...` → `agent\|t\|t`（即 `rolcreatedb=true`、`rolsuper=true`） | E22 |
| 凭据 | 仅来自仓库外 mode-0600 的 `/tmp/nexusdesk-phase3-pg.env`（4 个变量）；本报告、日志与仓库文件均不含连接串或口令 | `ls -l`、`awk -F= '{print $1}'` |
| `AGENT_TENANT_ID` | 保持默认 `local`，未覆盖 | 执行环境 |
| 执行日期 | 2026-11-13 20:46～21:15 CST（各命令时间戳见附录 A） | `date` |

**未提交范围说明（协调者已知安排）**：T6/T7/T8 的实现与测试、以及本轮文档，均以工作树（未提交）形态存在；HEAD `37b08f8` 只包含到 T2～T5/T9 的提交（`4318042`、`d662a4b`）。因此本报告记录的是"**HEAD + 当前工作树**"这一组合状态下的实测结果，**不代表任何已提交 SHA 单独可复现这些数字**；07 引用时必须同时引用本节。commit/push 由协调者的 checkpoint 安排决定，本代理未执行任何 git 写操作。

**证据生命周期**：本轮原始日志写在 `/tmp/p3t10-logs/`（本机临时目录，非仓库归档）。清理后附录 A 的日志链接不可复核，本文件仅保留命令与输出尾部摘要；本轮未产生 CI artifacts 或其他持久归档，不暗示证据已长期归档。

## 2. 执行总览（命令与输出尾部）

所有命令均从仓库根执行；PG 命令统一前置（凭据只在该 shell 环境内存在，不写进本报告）：

```bash
set -a; . /tmp/nexusdesk-phase3-pg.env; set +a
unset AGENT_API_TOKEN
export AGENT_DATABASE_URL="$TEST_DATABASE_URL"
```

| # | 命令 | 输出尾部（原文摘录） | exit |
|---|---|---|---|
| E01 | `uv run --directory backend pytest -q -m "not postgres"` | `1975 passed, 528 deselected, 6 warnings in 15.39s` | 0 |
| E02 | `uv run --directory backend pytest -m postgres -q -rs` | `500 passed, 28 skipped, 1975 deselected, 3 warnings in 242.74s (0:04:02)`（28 条 skip 明细见 §5） | 0 |
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
| E19 | `... tests/test_agent_execution_registries.py -q -rs` | `184 passed in 0.19s`；另 `alembic heads` → `0058_agent_execution_metadata (head)` | 0 |
| E20 | `... tests/test_local_test_adapter.py -q -rs` | `58 passed in 0.19s`；`alembic current` → `0058_agent_execution_metadata (head)` | 0 |
| E21 | `... tests/test_agent_execution_contract_probe.py -q -rs` | `45 passed in 0.11s`；`git status --porcelain \| wc -l` → `44` | 0 |
| E22 | `... tests/test_runtime_postgres.py -q -rs` | `45 passed in 10.07s`；角色查询 → `agent\|t\|t` | 0 |
| E23 | `uv run --directory backend ruff check src tests` | `All checks passed!` | 0 |
| E24 | `uv run --directory backend ruff format --check <35 个本阶段工作树 Python 文件>` | `3 files would be reformatted, 32 files already formatted`（偏差文件见 §6.5） | 1 |
| E25 | `uv run --directory backend ruff format --check src tests` | `74 files would be reformatted, 397 files already formatted` | 1 |
| E26 | `uv run --directory backend python ../scripts/check_architecture.py` | `architecture gate passed` | 0 |
| E27 | `cd frontend && npx playwright test tests/agent-execution-config.spec.ts --reporter=line` | `37 passed (32.7s)` | 0 |
| E28 | `cd frontend && npm run typecheck` | 无输出（`tsc --noEmit` 正常结束） | 0 |
| E29 | `cd frontend && npm run check:i18n` | `Verified 2075 translations in zh-CN, zh-TW, en, hi` | 0 |
| E30 | `cd frontend && npm run build` | `✓ built in 3.69s`（另有 chunk >500 kB 的既有体积告警） | 0 |

E01～E02 与 E03～E22 存在重叠，各套件之间亦相互重叠；上述计数只用于证明"确实执行过"，**不得相加为独立覆盖数**。Phase 3 九个 `test_agent_execution_phase3_*.py` 文件收集节点合计 **413**（`--collect-only -q`），其中带 `@pytest.mark.postgres` 的节点在迁移/快照/preview/compat 四文件中合计 **64**。

## 3. P3 编号 → 证据映射

别名（列中路径均相对仓库根）：

`CAP` = `backend/tests/test_agent_execution_phase3_capabilities.py`；`CFG` = `backend/tests/test_agent_execution_phase3_config.py`；`COMPAT` = `backend/tests/test_agent_config_execution_compat.py`；`ENGINE` = `backend/tests/test_runtime_engine.py`；`FLAGS` = `backend/tests/test_agent_execution_phase3_flags.py`；`INS` = `backend/tests/test_agent_execution_phase3_instructions.py`；`LTA` = `backend/tests/test_local_test_adapter.py`；`MIG` = `backend/tests/test_agent_execution_phase3_migration.py`；`ORCH` = `backend/tests/test_execution_orchestrator.py`；`PREV` = `backend/tests/test_agent_execution_phase3_preview.py`；`REG` = `backend/tests/test_agent_execution_registries.py`；`SET` = `backend/tests/test_agent_execution_phase3_settings.py`；`SNAP` = `backend/tests/test_agent_execution_phase3_snapshots.py`；`WIRE` = `backend/tests/test_agent_execution_phase3_wiring.py`

### 3.1 单元测试（P3-UT-01～28）

| 编号 | 承载用例（`别名::函数`（参数展开节点数）） | 环境 | 结果 | 边界/去向 |
|---|---|---|---|---|
| P3-UT-01 | `CFG::test_p3_ut_01_missing_engine_defaults_react_without_mutating_input`(1)；`CFG::test_p3_ut_01_missing_react_fields_use_react_defaults`(1)；`CFG::test_p3_ut_01_model_input_returns_an_equal_but_distinct_canonical_object`(1)（3 函数 / 3 节点） | 本机 | 通过 | — |
| P3-UT-02 | `CFG::test_p3_ut_02_equal_legacy_and_react_aliases_produce_one_canonical_value`(1)（1 函数 / 1 节点） | 本机 | 通过 | — |
| P3-UT-03 | `CFG::test_p3_ut_03_conflicting_aliases_name_the_stable_field_path`(3)；`CFG::test_p3_ut_03_unserializable_alias_pair_fails_closed_as_validation_error`(6)；`CFG::test_p3_ut_03_circular_reference_alias_pair_fails_closed_as_validation_error`(1)（3 函数 / 10 节点） | 本机 | 通过 | — |
| P3-UT-04 | `CFG::test_p3_ut_04_free_dict_latest_extra_and_client_policy_fields_fail_closed`(8)；`CFG::test_p3_ut_04_explicit_non_react_cannot_carry_react_configuration`(1)；`REG::test_p3_ut_04_metadata_unknown_triple_fails_closed_without_factory`(2)；`REG::test_p3_ut_04_metadata_disabled_adapter_fails_closed_without_factory`(1)；`REG::test_p3_ut_04_missing_or_free_dict_schema_is_rejected`(3)；`REG::test_p3_ut_04_registration_rejects_non_strict_schema_without_calling_factory`(1)；`REG::test_p3_ut_04_21_registry_validates_canonical_config_without_adapter_resolution`(1)（7 函数 / 17 节点） | 本机 | 通过 | — |
| P3-UT-05 | `CFG::test_p3_ut_05_profile_pairing_and_round_bounds_remain_strict`(6)；`CFG::test_p3_ut_05_disabled_capabilities_deduplicate_deterministically`(1)；`CFG::test_p3_ut_05_disabled_capabilities_reject_unknown_unbounded_or_wrong_types`(4)（3 函数 / 11 节点） | 本机 | 通过 | — |
| P3-UT-06 | `CAP::test_p3_ut06_deployed_missing_makes_available_false_without_rewriting_declared`(1)；`CAP::test_p3_ut06_probe_version_mismatch_fails_closed_and_preserves_declared`(1)；`CAP::test_p3_ut06_declared_lookup_rejects_disabled_or_unknown_triple`(1)（3 函数 / 3 节点） | 本机 | 通过 | — |
| P3-UT-07 | `CAP::test_p3_ut07_probe_timeout_is_bounded_sanitized_and_reason_stable`(1)；`CAP::test_p3_ut07_probe_exception_keeps_error_status_without_raw_text`(1)；`CAP::test_p3_ut07_cache_hit_within_ttl_and_declaration_change_replaces_identity_key`(1)；`CAP::test_p3_ut07_probe_concurrency_is_bounded`(1)（4 函数 / 4 节点） | 本机 | 通过 | — |
| P3-UT-08 | `CAP::test_p3_ut08_workspace_required_without_trusted_workspace_blocks_startup`(1)（1 函数 / 1 节点） | 本机 | 通过 | — |
| P3-UT-09 | `CAP::test_p3_ut09_each_layer_denial_narrows_effective_monotonically`(1)；`CAP::test_p3_ut09_disabled_capabilities_can_only_true_to_false`(1)（2 函数 / 2 节点） | 本机 | 通过 | — |
| P3-UT-10 | `CAP::test_p3_ut10_untrusted_or_stale_policy_fails_closed`(1)；`CAP::test_p3_ut10_missing_policy_source_and_unknown_capability_names_fail_closed`(1)；`CAP::test_p3_ut10_unknown_capability_names_are_schema_errors_not_ignored`(1)（3 函数 / 3 节点） | 本机 | 通过 | — |
| P3-UT-11 | `CAP::test_p3_ut11_forged_capability_layers_rejected_by_every_trusted_dto`(1)；`CAP::test_p3_ut11_request_and_config_contracts_have_no_capability_authorization_input`(1)；`PREV::test_forged_field_is_rejected_not_ignored`(27)；`PREV::test_type_errors_are_locatable_and_do_not_echo_values`(1)；`PREV::test_unknown_plain_field_is_rejected`(1)；`PREV::test_missing_config_is_422`(1)（6 函数 / 32 节点） | 本机 | 通过 | — |
| P3-UT-12 | `CAP::test_p3_ut12_policy_context_uses_server_trusted_tenant_and_never_client_text`(1)；`CAP::test_p3_ut12_cross_tenant_policy_entries_are_isolated`(1)；`PREV::test_resolution_request_is_assembled_from_trusted_context`(1)；`PREV::test_disabled_capabilities_travel_from_the_draft`(1)（4 函数 / 4 节点） | 本机 | 通过 | — |
| P3-UT-13 | `SNAP::test_p3_ut13_single_class_limit_is_per_snapshot_not_shared`(1)；`SNAP::test_p3_ut13_serialization_failure_is_closed`(1)；`SNAP::test_p3_ut13_deserialize_rejects_missing_fields_and_versions`(1)；`SNAP::test_p3_ut13_serialization_revalidates_the_dto_completion_invariants`(1)；`SNAP::test_p3_ut13_five_class_serialization_also_revalidates`(1)；`SNAP::test_snapshot_size_limit_default_matches_settings`(1)；`SNAP::test_serialize_enforces_one_startup_identity`(1)；`SNAP::test_builders_reject_naive_datetimes`(1)（8 函数 / 8 节点） | 本机 | 通过 | — |
| P3-UT-14 | `SNAP::test_p3_ut14_denylist_covers_every_planned_key_category`(19)；`SNAP::test_p3_ut14_camel_case_and_separator_smuggling_is_normalized`(1)；`SNAP::test_p3_ut14_clean_schema_names_are_not_false_positives`(1)；`SNAP::test_p3_ut14_secret_shaped_values_rejected_at_any_depth_without_echo`(1)；`SNAP::test_p3_ut14_snapshot_with_smuggled_secret_fails_before_write_and_stays_quiet`(1)；`SNAP::test_p3_ut14_private_key_value_shape_is_denied_under_a_benign_key_name`(2)；`SNAP::test_p3_ut14_legal_identifier_shapes_are_not_false_positives`(1)；`SNAP::test_p3_ut14_leading_separator_values_are_denied_by_design`(1)（8 函数 / 27 节点） | 本机 | 通过 | 非 slug 且分隔符开头的 tenant_id 整批拒（R-33）由本行双向负控承载；off 态直读缺口见 #130 第 1 项 |
| P3-UT-15 | `SNAP::test_p3_ut15_repeated_serialization_is_byte_identical`(1)；`SNAP::test_p3_ut15_round_trip_reparse_is_stable`(1)；`SNAP::test_p3_ut15_replay_touches_no_engine_and_does_not_mutate_snapshots`(1)；`SNAP::test_p3_ut15_revalidation_does_not_change_canonical_bytes`(1)；`SNAP::test_p3_ut15_replay_rejects_payloads_with_divergent_startup_identity`(1)；`SNAP::test_p3_ut15_replay_rejects_missing_illegal_and_unknown_fields_without_echo`(1)；`SNAP::test_p3_ut15_replay_accepts_pretty_printed_but_semantically_equal_payloads`(1)；`SNAP::test_p3_ut15_replay_accepts_decoded_mapping_payloads_from_a_db_row`(1)；`SNAP::test_pg_read_back_row_replays_without_re_encoding`(1)（9 函数 / 9 节点） | 本机+PG | 通过 | — |
| P3-UT-16 | `INS::test_p3_ut_16_empty_summary_and_memory_produce_no_empty_messages`(1)；`INS::test_p3_ut_16_summary_switch_off_keeps_the_baseline_sequence`(1)；`INS::test_p3_ut_16_blank_history_rows_pass_through_but_blank_slots_still_fail`(1)（3 函数 / 3 节点） | 本机 | 通过 | — |
| P3-UT-17 | `INS::test_p3_ut_17_react_provider_reproduces_the_engine_message_sequence`(11)；`INS::test_p3_ut_17_history_truncation_is_applied_once_by_preparation`(1)；`INS::test_p3_ut_17_zero_history_turns_keeps_only_system_and_current_user`(1)；`INS::test_p3_ut_17_fixed_instruction_order_is_enforced_on_both_sides`(1)；`ENGINE::test_prepared_react_instructions_are_an_equivalent_input_not_a_second_assembly`(1)（5 函数 / 15 节点） | 本机 | 通过 | — |
| P3-UT-18 | `INS::test_p3_ut_18_test_provider_keeps_an_independent_native_format`(1)；`INS::test_p3_ut_18_instruction_input_carries_rendered_values_and_never_a_memory_port`(1)；`INS::test_p3_ut_18_react_provider_ignores_engine_context`(1)；`INS::test_p3_ut_18_preparation_computes_the_effective_prompt_once_before_any_runner`(1)（4 函数 / 4 节点） | 本机 | 通过 | — |
| P3-UT-19 | `INS::test_p3_ut_19_resolve_rejects_unknown_providers_without_fallback`(6)；`INS::test_p3_ut_19_resolve_rejects_hostile_provider_identity`(7)；`INS::test_p3_ut_19_test_provider_is_never_production_registered`(1)；`INS::test_p3_ut_19_duplicate_context_fails_the_contract`(1)；`INS::test_p3_ut_19_contract_errors_fail_closed`(1)；`INS::test_p3_ut_19_react_provider_refuses_foreign_engine_and_payload`(1)；`INS::test_p3_ut_19_engine_never_degrades_when_the_prepared_input_is_foreign`(1)；`INS::test_p3_ut_19_start_is_never_reached_when_preparation_fails`(1)；`INS::test_p3_ut_19_prepared_input_that_contradicts_the_engine_arguments_fails_closed`(1)；`INS::test_p3_ut_19_prepared_history_must_be_the_windows_own_kept_slice`(1)；`INS::test_p3_ut_19_snapshot_fault_codes_are_pinned_to_the_triggering_condition`(1)；`INS::test_p3_ut_19_preparation_refuses_a_contract_breaking_value_without_echoing_it`(1)；`WIRE::test_snapshot_faults_map_onto_invalid_request_not_internal_error`(1)；`WIRE::test_the_four_run_side_codes_stay_out_of_the_adapter_error_map`(1)；`WIRE::test_instruction_contract_error_passes_through_without_the_fault_map`(1)；`LTA::test_cumulative_t2_t3_t4_modules_and_dependency_direction_are_exact`(1)（16 函数 / 27 节点） | 本机 | 通过 | — |
| P3-UT-20 | `SET::test_phase3_settings_default_to_safe_rollout_values`(1)；`SET::test_phase3_settings_accept_constructor_overrides`(1)；`SET::test_phase3_settings_use_agent_environment_prefix`(1)；`SET::test_phase3_settings_reject_values_outside_bounds`(31)；`SET::test_phase3_settings_accept_inclusive_boundaries`(22)；`SET::test_phase3_warm_refresh_must_stay_below_the_shortest_ttl_when_enabled`(1)；`SET::test_phase3_warm_refresh_window_is_unconstrained_when_disabled`(1)（7 函数 / 58 节点） | 本机 | 通过 | — |
| P3-UT-21 | `CFG::test_p3_ut_21_canonical_diff_suppresses_only_default_equivalent_noise`(1)；`REG::test_p3_ut_21_exact_metadata_is_complete_without_factory_or_capability_probe`(1)；`REG::test_p3_ut_04_21_registry_validates_canonical_config_without_adapter_resolution`(1)；`COMPAT::test_react_descriptor_metadata_matches_between_standalone_and_production_registries`(1)（4 函数 / 4 节点） | 本机 | 通过 | — |
| P3-UT-22 | `CAP::test_p3_ut22_cold_hot_path_never_probes_and_singleflights_refresh`(1)；`CAP::test_p3_ut22_unwarmed_unavailable_then_warm_then_expired_sequence`(1)；`CAP::test_p3_ut22_failed_refresh_keeps_stale_or_error_and_never_grants`(1)；`CAP::test_p3_ut22_availability_and_policy_cache_key_fields_are_exact`(1)；`CAP::test_p3_ut22_every_cache_key_field_change_isolates_entries`(1)；`CAP::test_p3_ut22_warmer_initial_population_refresh_and_close_without_task_leak`(1)；`CAP::test_p3_ut22_warmer_retries_failed_round_at_bounded_interval`(1)；`CAP::test_p3_ut22_public_dto_shapes_expose_no_raw_probe_or_internal_snapshots`(1)；`PREV::test_preview_response_is_the_exact_whitelist`(1)；`PREV::test_preview_response_recursively_free_of_internal_evidence`(1)；`PREV::test_reason_codes_pass_through_from_the_layers`(1)；`PREV::test_cold_cache_previews_fail_closed_with_stable_reasons`(1)；`WIRE::test_composition_constructs_nothing_while_phase3_is_off`(1)（13 函数 / 13 节点） | 本机 | 通过 | hot path 不 probe 指 resolver.resolve()；Run 屏障的一次有界 warm 不违反本条（04 冻结口径） |
| P3-UT-23 | `CAP::test_review_agent_disabled_narrowing_is_not_a_missing_required_capability`(1)；`CAP::test_review_policy_layer_denials_are_not_missing_required_capabilities`(1)；`CAP::test_review_deployment_or_policy_trust_gaps_still_block_startup`(1)；`CAP::test_review_each_infrastructure_probe_reason_enters_required_missing`(2)；`CAP::test_review_observed_probe_timeout_enters_required_missing`(1)；`CAP::test_review_stale_availability_with_fresh_policy_enters_required_missing`(1)；`CAP::test_review_policy_unavailable_alone_enters_required_missing`(1)；`CAP::test_review_each_narrowing_reason_stays_out_of_required_missing`(5)（8 函数 / 13 节点） | 本机 | 通过 | — |
| P3-UT-24 | `CAP::test_review_policy_revision_is_observed_from_the_provider_not_the_request`(1)；`CAP::test_review_provider_revision_echo_mismatch_records_error_not_grant`(1)；`CAP::test_review_revision_source_failure_raises_policy_source_unavailable`(1)；`CAP::test_review_policy_revision_scope_dto_is_strict_and_frozen`(1)；`CAP::test_review_trusted_policy_provider_signatures_are_sync_read_async_resolve`(1)（5 函数 / 5 节点） | 本机 | 通过 | — |
| P3-UT-25 | `CAP::test_review_effective_projection_functions_are_the_unique_canonical_views`(1)；`CAP::test_review_execution_restriction_digest_is_canonical_with_empty_constant`(1)；`SNAP::test_r22_builder_signatures_are_pinned_to_capability_resolution`(1)；`SNAP::test_r22_builders_reject_layer_dto_cache_lookup_and_raw_dict`(1)；`SNAP::test_capability_snapshots_copy_the_narrowed_views_verbatim`(1)；`SNAP::test_policy_snapshot_requires_a_resolved_policy_and_pins_digests`(1)；`SNAP::test_capability_snapshot_set_returns_all_four_layer_snapshots`(1)（7 函数 / 7 节点） | 本机 | 通过 | — |
| P3-UT-26 | `FLAGS::test_flags_response_is_exactly_two_bools`(1)；`FLAGS::test_flags_dto_is_strict_extra_forbid_and_frozen`(1)；`FLAGS::test_all_four_states_return_200_with_real_values`(4)；`FLAGS::test_flags_track_settings_mutations`(1)；`FLAGS::test_flags_read_only_two_setting_booleans`(1)（5 函数 / 8 节点） | 本机 | 通过 | — |
| P3-UT-27 | `WIRE::test_probe_answers_from_registered_declarations_only`(1)；`WIRE::test_probe_echoes_the_context_identity_and_never_the_unobserved_digest`(1)；`WIRE::test_probe_deployment_digest_is_stable_and_identity_bound`(1)；`WIRE::test_probe_observed_at_comes_from_the_injected_wall_clock`(1)；`WIRE::test_probe_reads_metadata_only_and_never_consults_an_adapter`(1)；`WIRE::test_resolver_sanitizes_a_declared_false_answer_to_not_declared`(1)；`WIRE::test_policy_ceiling_is_the_react_declaration_allow_list`(1)；`WIRE::test_policy_agent_layer_follows_the_published_disabled_capabilities`(1)；`WIRE::test_policy_provider_echoes_context_identity_with_four_complete_layers`(1)；`WIRE::test_current_revision_is_scope_stable_monotonic_and_io_free`(1)；`WIRE::test_policy_version_is_the_settings_value_the_descriptor_carries`(1)；`WIRE::test_workspace_port_returns_none_and_never_fakes_availability`(1)；`WIRE::test_null_workspace_port_still_fails_closed_for_a_requiring_engine`(1)（13 函数 / 13 节点） | 本机 | 通过 | — |
| P3-UT-28 | `WIRE::test_composition_constructs_nothing_while_phase3_is_off`(1)；`WIRE::test_composition_maps_every_capability_setting_to_a_constructor_argument`(1)；`WIRE::test_composition_descriptor_and_provider_share_one_policy_version_source`(1)；`WIRE::test_composition_warm_targets_are_exactly_the_enabled_registrations`(1)；`WIRE::test_a_disabled_registration_descriptor_produces_no_warm_target`(1)；`WIRE::test_composition_uses_one_posix_wall_clock_for_the_subsystem`(1)；`WIRE::test_trusted_ports_are_injectable_by_code_and_unselectable_by_settings`(1)；`WIRE::test_composition_starts_the_warmer_after_extensions_and_closes_it_first`(1)；`WIRE::test_cache_warmer_and_resolver_reject_out_of_range_bounds`(1)；`WIRE::test_resolver_observations_the_workspace_generation_once_per_round`(1)（10 函数 / 10 节点） | 本机 | 通过 | — |

### 3.2 集成测试（P3-IT-01～22）

| 编号 | 承载用例（`别名::函数`（参数展开节点数）） | 环境 | 结果 | 边界/去向 |
|---|---|---|---|---|
| P3-IT-01 | `COMPAT::test_p3_it_01_legacy_get_is_read_only_and_default_diff_is_empty`(1)（1 函数 / 1 节点） | PG | 通过 | — |
| P3-IT-02 | `COMPAT::test_p3_it_02_new_react_publish_and_metadata_validation_never_create_adapter`(1)；`COMPAT::test_p3_it_02_unknown_engine_is_rejected_before_publish_without_adapter`(1)；`COMPAT::test_p3_it_02_invalid_stored_config_has_stable_publish_rejection`(1)；`COMPAT::test_p3_it_02_alias_conflict_is_rejected_before_update`(1)（4 函数 / 4 节点） | PG | 通过 | — |
| P3-IT-03 | `WIRE::test_declaration_divergence_refuses_before_any_snapshot_or_start`(1)；`WIRE::test_cold_policy_warms_once_and_stays_fail_closed_when_the_warm_fails`(1)；`WIRE::test_barrier_writes_the_five_payloads_once_before_prepare_and_start`(1)；`PREV::test_pg_preview_uses_the_same_resolver_the_run_path_owns`(1)（4 函数 / 4 节点） | 本机+PG | 通过 | — |
| P3-IT-04 | `PREV::test_pg_forged_fields_are_audited_without_leaking_values`(1)；`PREV::test_forged_field_is_rejected_not_ignored`(27)；`PREV::test_type_errors_are_locatable_and_do_not_echo_values`(1)（3 函数 / 29 节点） | 本机+PG | 通过 | — |
| P3-IT-05 | `PREV::test_foreign_agent_id_keeps_the_existing_not_found_domain_answer`(1)；`PREV::test_pg_cross_tenant_agent_id_is_404_and_audits_no_foreign_data`(1)；`COMPAT::test_later_draft_and_v2_do_not_rewrite_v1_or_cross_tenant_boundary`(1)（3 函数 / 3 节点） | 本机+PG | 通过 | — |
| P3-IT-06 | `SNAP::test_pg_snapshots_write_once_in_a_single_statement_after_claim`(1)；`SNAP::test_pg_conditional_write_identity_rules`(1)；`SNAP::test_pg_write_barrier_sql_binds_payload_identity_without_entry_guard`(1)；`SNAP::test_pg_write_barrier_sql_binds_payload_identity_of_every_column`(1)；`SNAP::test_pg_concurrent_snapshot_writers`(1)；`WIRE::test_barrier_writes_the_five_payloads_once_before_prepare_and_start`(1)（6 函数 / 6 节点） | 本机+PG | 通过 | — |
| P3-IT-07 | `SNAP::test_pg_terminal_paths_never_rewrite_snapshots`(1)；`SNAP::test_pg_retry_changing_one_column_decision_is_refused`(5)；`SNAP::test_pg_historical_null_rows_are_never_backfilled_by_reads`(1)（3 函数 / 7 节点） | PG | 通过 | — |
| P3-IT-08 | `SNAP::test_pg_barrier_entry_clean_gate_refuses_every_payload_class_before_sql`(24)；`SNAP::test_gate_case_matrix_covers_every_class_per_expressible_column`(1)；`SNAP::test_p3_it08_write_entry_rejects_non_canonical_payload_strings`(1)；`SNAP::test_pg_commit_failure_leaves_no_partial_snapshot_row`(1)（4 函数 / 27 节点） | 本机+PG | 通过 | — |
| P3-IT-09 | `INS::test_p3_ut_17_react_provider_reproduces_the_engine_message_sequence`(11)；`ENGINE::test_prepared_react_instructions_are_an_equivalent_input_not_a_second_assembly`(1)；`WIRE::test_on_on_adapter_receives_prepared_input_and_no_second_rendering`(1)；`WIRE::test_preparation_and_engine_share_one_effective_settings_source`(1)（4 函数 / 14 节点） | 本机 | 通过 | 04 判据中的写回 diff/日志面依赖 §10 回归套件（Phase 2 既有 MemoryInjection 用例），Phase 3 未新增 PG 端到端专用用例；见 §6.7 |
| P3-IT-10 | `INS::test_p3_ut_18_test_provider_keeps_an_independent_native_format`(1)；`INS::test_p3_ut_19_test_provider_is_never_production_registered`(1)；`WIRE::test_on_on_matches_the_off_on_public_event_sequence_exactly`(1)；`LTA::test_cumulative_t2_t3_t4_modules_and_dependency_direction_are_exact`(1)（4 函数 / 4 节点） | 本机 | 通过 | — |
| P3-IT-11 | `PREV::test_preview_then_policy_change_recomputes_without_stale_grant`(1)；`PREV::test_cold_cache_previews_fail_closed_with_stable_reasons`(1)；`PREV::test_pg_preview_uses_the_same_resolver_the_run_path_owns`(1)；`PREV::test_pg_preview_after_policy_constant_stays_conservative`(1)（4 函数 / 4 节点） | 本机+PG | 通过 | revision 前进形态由非 PG 真 resolver＋注入假 provider 承载，PG 面只断言同一 resolver 实例；见 §6.3 |
| P3-IT-12 | `WIRE::test_both_off_states_construct_no_phase3_side_effects`(1)；`WIRE::test_flipping_the_phase3_flag_leaves_the_fingerprint_unchanged`(1)；`PREV::test_pg_phase3_off_preview_domain_error_and_no_subsystem`(1)；`ORCH::test_runtime_fingerprint_excludes_both_rollout_flags_and_the_phase3_tuning_family`(1)（4 函数 / 4 节点） | 本机+PG | 通过 | off 态五列 NULL 为组合证据，无单条 PG 端到端直读用例；登记于 #130 第 1 项；见 §6.1 |
| P3-IT-13 | `WIRE::test_rollout_gate_refuses_a_non_react_triple_in_every_off_state`(1)；`WIRE::test_on_with_orchestrator_off_refuses_the_legacy_path_completely`(1)；`WIRE::test_rollout_gate_fails_closed_on_misconfiguration_and_unavailable_engine`(1)；`WIRE::test_the_misconfigured_state_boots_and_still_refuses_runs`(1)（4 函数 / 4 节点） | 本机 | 通过 | — |
| P3-IT-14 | `MIG::test_0058_upgrade_old_new_concurrent_repository_and_disposable_downgrade`(1)（1 函数 / 1 节点） | PG | 通过 | — |
| P3-IT-15 | `MIG::test_0058_upgrade_old_new_concurrent_repository_and_disposable_downgrade`(1)（1 函数 / 1 节点） | PG | 通过 | 可空列不阻碍旧语句与 downgrade/重升已测；「回滚 Phase 2 二进制」的部署形态延后至 #128 |
| P3-IT-16 | `COMPAT::test_p3_it_16_new_react_does_not_bypass_model_capability_validation`(1)；`COMPAT::test_p3_it_16_new_react_preserves_tool_resolution_and_snapshot`(1)（2 函数 / 2 节点） | PG | 通过 | — |
| P3-IT-17 | `PREV::test_pg_preview_unsaved_draft_has_zero_side_effects`(2)；`PREV::test_pg_openapi_declares_strict_request_and_whitelist_response`(1)；`PREV::test_preview_does_not_instantiate_adapters_or_write_snapshots`(1)（3 函数 / 4 节点） | 本机+PG | 通过 | — |
| P3-IT-18 | `SNAP::test_p3_it18_entry_guard_rejects_foreign_startup_identity_before_database`(1)；`SNAP::test_pg_conditional_write_identity_rules`(1)；`SNAP::test_snapshot_write_result_is_content_free`(1)；`WIRE::test_write_outcomes_map_onto_the_existing_run_vocabulary`(1)；`WIRE::test_worker_reads_each_rollout_flag_once_and_fixes_the_path`(1)；`WIRE::test_a_row_without_a_published_snapshot_keeps_the_legacy_triple`(1)（6 函数 / 6 节点） | 本机+PG | 通过 | — |
| P3-IT-19 | `WIRE::test_composition_maps_every_capability_setting_to_a_constructor_argument`(1)；`WIRE::test_composition_descriptor_and_provider_share_one_policy_version_source`(1)；`WIRE::test_composition_warm_targets_are_exactly_the_enabled_registrations`(1)；`WIRE::test_the_composition_threads_the_snapshot_ceiling_to_the_serializer`(1)；`WIRE::test_projected_execution_config_equals_the_agent_config_normalizer`(1)；`WIRE::test_projected_execution_config_defaults_the_triple_and_rejects_unknown_keys`(1)；`WIRE::test_runtime_fingerprint_excludes_the_phase3_tuning_family_field_by_field`(1)；`WIRE::test_runtime_fingerprint_still_hashes_the_runtime_assembly_inputs`(1)；`PREV::test_pg_preview_uses_the_same_resolver_the_run_path_owns`(1)；`ORCH::test_runtime_fingerprint_exclude_set_names_every_phase3_field`(1)（10 函数 / 10 节点） | 本机+PG | 通过 | — |
| P3-IT-20 | `FLAGS::test_unauthenticated_or_bad_token_is_401_or_403`(3)；`FLAGS::test_reader_operator_and_admin_can_all_read`(1)；`FLAGS::test_flags_are_tenant_agnostic`(1)；`FLAGS::test_openapi_contains_flags_route_with_two_property_schema`(1)；`FLAGS::test_response_body_carries_no_internal_fields`(1)；`FLAGS::test_flags_read_only_two_setting_booleans`(1)（6 函数 / 8 节点） | 本机 | 通过 | flags 面为纯 ASGI（真实 principal 依赖），无 PG 专用用例；跨 tenant 一致性与 OpenAPI 由本行用例断言 |
| P3-IT-21 | `WIRE::test_probe_reads_metadata_only_and_never_consults_an_adapter`(1)；`WIRE::test_policy_ceiling_is_the_react_declaration_allow_list`(1)；`WIRE::test_policy_provider_echoes_context_identity_with_four_complete_layers`(1)；`WIRE::test_current_revision_is_scope_stable_monotonic_and_io_free`(1)；`WIRE::test_workspace_port_returns_none_and_never_fakes_availability`(1)；`WIRE::test_trusted_ports_are_injectable_by_code_and_unselectable_by_settings`(1)；`WIRE::test_probe_deployment_digest_is_stable_and_identity_bound`(1)；`WIRE::test_probe_observed_at_comes_from_the_injected_wall_clock`(1)（8 函数 / 8 节点） | 本机 | 通过 | — |
| P3-IT-22 | `WIRE::test_every_barrier_refusal_keeps_its_own_run_code`(1)；`WIRE::test_snapshot_faults_map_onto_invalid_request_not_internal_error`(1)；`WIRE::test_the_four_run_side_codes_stay_out_of_the_adapter_error_map`(1)；`WIRE::test_the_runtime_engine_protocol_and_the_engine_implementation_agree`(1)；`WIRE::test_instruction_contract_error_passes_through_without_the_fault_map`(1)；`WIRE::test_a_ceiling_below_the_payload_refuses_before_the_adapter_starts`(1)；`WIRE::test_declaration_divergence_refuses_before_any_snapshot_or_start`(1)；`WIRE::test_on_with_orchestrator_off_refuses_the_legacy_path_completely`(1)；`WIRE::test_both_off_states_construct_no_phase3_side_effects`(1)；`WIRE::test_on_on_matches_the_off_on_public_event_sequence_exactly`(1)；`WIRE::test_the_misconfigured_state_boots_and_still_refuses_runs`(1)；`PREV::test_flags_endpoint_still_answers_two_bools`(1)（12 函数 / 12 节点） | 本机 | 通过 | — |

### 3.3 通用核对项（P3-CM-01～10）

| 编号 | 承载用例（`别名::函数`（参数展开节点数）） | 环境 | 结果 | 边界/去向 |
|---|---|---|---|---|
| P3-CM-01 | `MIG::test_0058_revision_chain_and_atomic_sql_contract`(1)；`MIG::test_0058_upgrade_old_new_concurrent_repository_and_disposable_downgrade`(1)（2 函数 / 2 节点） | 本机+PG | 通过 | — |
| P3-CM-02 | `SET::test_phase3_settings_default_to_safe_rollout_values`(1)；`SET::test_phase3_settings_reject_values_outside_bounds`(31)；`SET::test_phase3_settings_accept_inclusive_boundaries`(22)（3 函数 / 54 节点） | 本机 | 通过 | backend/.env.example 实测 13 个 EXECUTION_* 键；deploy/production/.env.example 仅 1 个 Phase 2 键、无 Phase 3 键、无秘密 |
| P3-CM-03 | `PREV::test_pg_forged_fields_are_audited_without_leaking_values`(1)；`PREV::test_pg_cross_tenant_agent_id_is_404_and_audits_no_foreign_data`(1)；`SNAP::test_error_messages_only_carry_field_paths_and_stable_codes`(1)（3 函数 / 3 节点） | 本机+PG | 通过 | 422 审计由 2 个 PG 用例直查审计表；观测面（Engine/provider/policy 版本与原因）由能力层与快照用例断言；生产 trace/metrics 未采 |
| P3-CM-04 | `CAP::test_p3_ut12_cross_tenant_policy_entries_are_isolated`(1)；`PREV::test_pg_cross_tenant_agent_id_is_404_and_audits_no_foreign_data`(1)；`COMPAT::test_later_draft_and_v2_do_not_rewrite_v1_or_cross_tenant_boundary`(1)；`FLAGS::test_flags_are_tenant_agnostic`(1)（4 函数 / 4 节点） | 本机+PG | 通过 | — |
| P3-CM-05 | `COMPAT::test_p3_it_01_legacy_get_is_read_only_and_default_diff_is_empty`(1)；`SNAP::test_pg_historical_null_rows_are_never_backfilled_by_reads`(1)；`CFG::test_p3_ut_01_missing_engine_defaults_react_without_mutating_input`(1)；`CFG::test_p3_ut_21_canonical_diff_suppresses_only_default_equivalent_noise`(1)（4 函数 / 4 节点） | 本机+PG | 通过 | — |
| P3-CM-06 | `SNAP::test_repository_sql_is_parameterized_and_only_the_barrier_touches_snapshots`(1)；`SNAP::test_pg_terminal_paths_never_rewrite_snapshots`(1)；`SNAP::test_pg_snapshots_write_once_in_a_single_statement_after_claim`(1)；`SNAP::test_snapshot_write_result_is_content_free`(1)；`SNAP::test_pg_public_views_and_events_never_expose_snapshot_columns`(1)（5 函数 / 5 节点） | 本机+PG | 通过 | — |
| P3-CM-07 | `CAP::test_p3_ut09_each_layer_denial_narrows_effective_monotonically`(1)；`CAP::test_p3_ut11_forged_capability_layers_rejected_by_every_trusted_dto`(1)；`CAP::test_p3_ut08_workspace_required_without_trusted_workspace_blocks_startup`(1)；`PREV::test_pg_preview_after_policy_constant_stays_conservative`(1)（4 函数 / 4 节点） | 本机+PG | 通过 | — |
| P3-CM-08 | 见 §3.4 前端登记表 | 前端 | 通过（§3.4） | 判据映射见 04 §6.1；真实栈 UI 复跑随 #128（§6.2） |
| P3-CM-09 | `WIRE::test_both_off_states_construct_no_phase3_side_effects`(1)；`WIRE::test_rollout_gate_refuses_a_non_react_triple_in_every_off_state`(1)；`MIG::test_0058_upgrade_old_new_concurrent_repository_and_disposable_downgrade`(1)（3 函数 / 3 节点） | 本机+PG | 通过 | 双开关矩阵、列可空性与 downgrade-free 兼容性已测；应用级回滚/部署形态随 #128（08 R-39） |
| P3-CM-10 | `LTA::test_cumulative_t2_t3_t4_modules_and_dependency_direction_are_exact`(1)；`WIRE::test_trusted_ports_are_injectable_by_code_and_unselectable_by_settings`(1)（2 函数 / 2 节点） | 本机 | 通过 | 无专用用例；证据为架构门禁通过＋依赖方向/模块清单钉死用例＋真实缺失（无 Host/Workdir/Sandbox/Codex 实现，仅 denylist 键与占位字段） |

### 3.4 前端 P3-FE（按 04 §6.1 登记表直接引用，不另建映射表）

25 个编号（`P3-FE-01…21` ＋ `05b/10b/10c/16b`），`10c/12/17/18` 各按 `zh-CN/zh-TW/en/hi` 四语言参数化，实跑 **37** 个用例（E27）。行号为 `frontend/tests/agent-execution-config.spec.ts` 中该用例定义处。

| 编号 | 用例（spec 行号 — 标题原文） | 04 §6.1 判据分组 | 用例数 | 结果 |
|---|---|---|---|---|
| P3-FE-01 | `frontend/tests/agent-execution-config.spec.ts:320` — (M1) an old draft opens without default-filled fields or dirty state | M1（04 §6.1） | 1 | 通过 |
| P3-FE-02 | `frontend/tests/agent-execution-config.spec.ts:334` — a legal new execution config saves, and re-saving adds no churn | P3-CM-05（历史兼容/dirty） | 1 | 通过 |
| P3-FE-03 | `frontend/tests/agent-execution-config.spec.ts:369` — conflicting aliases are located instead of silently resolved | M2（04 §6.1） | 1 | 通过 |
| P3-FE-04 | `frontend/tests/agent-execution-config.spec.ts:381` — an unregistered engine triple is reported against the engine field | M2 | 1 | 通过 |
| P3-FE-05 | `frontend/tests/agent-execution-config.spec.ts:388` — preview posts the unsaved draft and stays read-only | M2（preview 只读） | 1 | 通过 |
| P3-FE-05b | `frontend/tests/agent-execution-config.spec.ts:421` — an unsaved new draft previews with a null agent id | M2（preview 只读） | 1 | 通过 |
| P3-FE-06 | `frontend/tests/agent-execution-config.spec.ts:450` — probe unavailability and policy denial are distinguishable | M2 | 1 | 通过 |
| P3-FE-07 | `frontend/tests/agent-execution-config.spec.ts:476` — disabled_capabilities can only narrow what the server allowed | M2（disabled 只收窄） | 1 | 通过 |
| P3-FE-08 | `frontend/tests/agent-execution-config.spec.ts:497` — previewing never creates a run or a message | preview 不建 Run 的前端侧证据（04 §6.1） | 1 | 通过 |
| P3-FE-09 | `frontend/tests/agent-execution-config.spec.ts:511` — (M1) a viewer can read and preview but never write | M1（04 §6.1） | 1 | 通过 |
| P3-FE-10 | `frontend/tests/agent-execution-config.spec.ts:528` — a disabled Phase 3 keeps the panel inert | M3 | 1 | 通过 |
| P3-FE-10b | `frontend/tests/agent-execution-config.spec.ts:557` — a strict schema rejection names the execution field path | 未列入 04 §6.1 的判据分组（编号已登记，分组缺项；见 §6.8） | 1 | 通过 |
| P3-FE-10c | `frontend/tests/agent-execution-config.spec.ts:574` — zh-CN frames a 422 field path with its own dictionary copy | P3-CM-08 四语言 | 4 | 通过 |
| P3-FE-11 | `frontend/tests/agent-execution-config.spec.ts:605` — a rejected save points at the offending execution field | M2 | 1 | 通过 |
| P3-FE-12 | `frontend/tests/agent-execution-config.spec.ts:613` — zh-CN covers controls, reasons and errors | P3-CM-08 四语言 | 4 | 通过 |
| P3-FE-13 | `frontend/tests/agent-execution-config.spec.ts:890` — every new execution key exists in all four locales | P3-CM-08 键完整性＋未翻译码白名单（#130 第 7 项） | 1 | 通过 |
| P3-FE-14 | `frontend/tests/agent-execution-config.spec.ts:647` — (M3) phase3 off hides the editing entries declaratively and keeps the React path intact | M3（03 §7.4 声明式隐藏） | 1 | 通过 |
| P3-FE-15 | `frontend/tests/agent-execution-config.spec.ts:676` — (M3) the on + orchestrator-off mismatch warns without any fake success | M3（错配提示） | 1 | 通过 |
| P3-FE-16 | `frontend/tests/agent-execution-config.spec.ts:694` — (M3) a failed flags read hides the Phase 3 entries fail-closed | M3（fail-closed 隐藏） | 1 | 通过 |
| P3-FE-16b | `frontend/tests/agent-execution-config.spec.ts:717` — the flags pair is read once per editor lifetime, not per preview | M3（flags 读取次数，R-35） | 1 | 通过 |
| P3-FE-17 | `frontend/tests/agent-execution-config.spec.ts:741` — zh-CN translates the Phase 3 not-enabled hint | P3-CM-08 四语言 | 4 | 通过 |
| P3-FE-18 | `frontend/tests/agent-execution-config.spec.ts:750` — zh-CN translates the deployment misconfiguration hint | P3-CM-08 四语言 | 4 | 通过 |
| P3-FE-19 | `frontend/tests/agent-execution-config.spec.ts:772` — (M3) a save the server refuses while phase3 is off stays translated, located and non-unlocking | M3（服务端拒绝不解锁入口） | 1 | 通过 |
| P3-FE-20 | `frontend/tests/agent-execution-config.spec.ts:829` — (M3) phase3 off still opens the conversation records and a past Run | M3（历史/Run 仍可查看） | 1 | 通过 |
| P3-FE-21 | `frontend/tests/agent-execution-config.spec.ts:844` — (M3) a failed flags read still leaves the records and Run viewable | M3（flags 失败仍可查看） | 1 | 通过 |

### 3.5 无法映射为"通过"的编号

1. **P3-CM-08**：判据本体（typecheck、`check:i18n`、build、37 个 Playwright 用例、Effective 只读）均实测通过，但其中 `model_not_configured` 未键化句子属 **Phase 3 范围外既有缺陷**，按 08 R-38/§5 不计入本项通过/不通过，登记见 §7。
2. **C11（05 §5 硬门槛）**：**无任何用例承载**，`not_measured`，见 §4；04 §6.2 要求的 `backend/tests/test_agent_execution_phase3_performance.py` 在本工作树中不存在。
3. **P3-IT-09 / P3-IT-15 / P3-IT-20 / P3-CM-03 / P3-CM-09 / P3-CM-10**：核心判据有承载用例，但各有一条子判据无专用用例或形态受限，已逐条写入 §3.2/§3.3 的"边界/去向"列并在 §6 展开；这些编号不得按"整条判据完全覆盖"引用。
4. **P3-FE-10b**：编号在 04 §6.1 的编号清单内（25 个之一），但**未被列入任何判据分组**（M1/M2/M3/P3-CM-08/P3-CM-05/preview-不建-Run 六组均无 10b）。实跑通过，映射时按 §6.8 如实登记为"分组缺项"，不得代它指定归属。

## 4. C11 — `not_measured`（事实登记）

| 项 | 实测事实 |
|---|---|
| 结论口径 | `not_measured`（未测量，非"通过"，也非"性能不达标"） |
| 直接证据 | 工作树与 HEAD 中均无 `backend/tests/test_agent_execution_phase3_performance.py`；`ruff`/`pytest` 无 C11 采样节点；`grep -rn "phase3_performance" backend` 无命中 |
| 采集量 | 有效交错配对样本 **0**（04 §6.2 要求 ≥100）、p95 **未计算**、原始每对耗时/时间戳/cache 版本 **无** |
| R-18 六项 settings 冻结值 | **未冻结采集**（04 §6.2 要求采集前记录并冻结；本轮只读到 settings 默认值，未做同取值下的配对采样） |
| 原因 | 维护者 2026-11-13 决定优先交付功能本体（T7/T8/T10/T11），C11 真实测量延后为独立跟进项；08 §5 规定"环境/证据不可得时保持 `not_measured`，状态不得写成 DONE 或通过" |
| 跟进 | issue **#129**（OPEN）：`[P3][Phase 3] C11: Real resolver/admission performance measurement (>=100 interleaved pairs, p95 <=50ms)` |
| 对阶段结论的影响 | 按 05 §5，C11 为"必须通过；不足/未测 = `not_measured` 或 `pending_env`，**不得通过**"；05 §6 同时把"C11 无有效实测"列为**不通过**判据之一，且 §2 规定缺环境时 C11 不能通过、代码合入不能替代证据。本报告只登记该事实与其判据文字，**阶段结论由 07 依 05 作出**；本报告不作结论，也不使用任何阶段级"通过"字样 |

Phase 2 的 06 在同类情形下的口径是"生产性能子指标 `pending_env`"，且其 E14/附录 E 样本来自 test double、明确不冒充生产达标。Phase 3 本轮连 test-double 采样都没有，因此只能记 `not_measured`，不得引用 Phase 2 数字代替。

## 5. skip / pending_env 归因（按机制，不按文案）

E02 的 28 条 skip 逐类计数（`grep -E "^SKIPPED" | sed 's/.*: //' | sort \| uniq -c` 实测）：

| 机制 | 条数 | skip 文案（原样） | 归因 | 判定 |
|---|---:|---|---|---|
| `MIGRATION_TEST_DATABASE_URL` 未提供（opt-in 迁移库开关） | **24** | `Requires a test PostgreSQL role with CREATEDB` | 该文案**只表示** `migration_database` fixture 的 opt-in 变量未提供（08 R-37），**不是**角色缺 `CREATEDB` | `pending_env`（环境选择缺口），不计通过、不算产品缺陷 |
| 目标库缺 pgvector/embedding 列 | **2** | `degraded-path assertion needs a database without the embedding column`；`needs a database without the embedding column` | 二者要求"无 embedding 列"的降级环境，当前 pgvector:pg17 库有该列 | `pending_env`（替代环境用例），不计通过 |
| 真实 Milvus 显式 opt-in | **1** | `Opt-in real Milvus test` | 未开启该外部依赖开关（`test_knowledge_workspace.py:264`） | `pending_env`，与 Phase 3 无关但如实登记 |
| seeded quickstart 显式 opt-in | **1** | `opt-in seeded quickstart URL and admin token are required` | seed/quickstart 已移出本阶段（08 R-39），`test_execution_orchestrator_seed.py:469` | `pending_env` → 延后 **#127/#128** |

补充事实与禁令：

1. **角色权限实测**：`rolcreatedb=true`、`rolsuper=true`（E22）。因此**禁止**把上述 24 条写成"权限不足/角色缺 CREATEDB"；也禁止把 `pending_env` 写成通过（04 §6.3、08 §5）。
2. **已登记的不对称**（04 §2⑤、08 R-37、#130 第 6 项）：`test_agent_execution_phase3_migration.py` 自带 fixture 读 `TEST_DATABASE_URL` 且不做角色探测；本轮 E03 为 **2 passed**（无 error、无 skip），故该不对称本轮**未触发**。若该文件日后报 error，既不得按 skip 归因，也不得据此反推角色权限。
3. E01（`-m "not postgres"`）为 `1975 passed, 528 deselected`，其中 **0 skip**：非 PG 路径不存在上述 opt-in 项。
4. 本轮不存在 `pending_env` 之外的"环境错误"型 skip；无 xfail/xpass/skip 之外的隐性跳过。

## 6. 证据边界（06 只记事实）

1. **off 态五列 NULL 为组合证据**：由「屏障/probe 调用计数恒 0」（WIRE::`test_both_off_states_construct_no_phase3_side_effects`、PREV::`test_pg_phase3_off_preview_domain_error_and_no_subsystem`）＋「拒写负控矩阵 24 例断言该行五列仍 NULL」（SNAP::`test_pg_barrier_entry_clean_gate_refuses_every_payload_class_before_sql`）＋「历史 NULL 不被读取回填」（SNAP::`test_pg_historical_null_rows_are_never_backfilled_by_reads`）共同承载；**缺**一条"flags off 下真实 Worker 端到端跑一次 Run 后直读五列"的 PG 直证用例。登记于 **#130 第 1 项**。涉及 P3-IT-12、P3-CM-09 的该子判据。
2. **前端 37 用例为 mock 契约级**：Playwright 以 `route` mock `/api/v1/**`，证明的是请求形状、DOM 门控与四语言；**不**等于真实端点下的 UI 复跑（flags/preview 端点服务端已存在，故复跑无阻塞）。真实栈复跑随 **#128**。涉及 04 §6.1、P3-CM-08 的"真实环境"含义、05 M1～M3。
3. **P3-IT-11 的 revision 前进形态**：由非 PG 的**真 resolver ＋ 注入假 provider**（可控前进）承载（PREV::`test_preview_then_policy_change_recomputes_without_stale_grant`），因为本阶段生产 provider 恒返回作用域常量（CAP::`test_review_policy_revision_is_observed_from_the_provider_not_the_request` 钉住该实现形态）；PG 面只断言"preview 与 Run 共用同一 resolver 实例"（PREV::`test_pg_preview_uses_the_same_resolver_the_run_path_owns`）。不得把它读成"PG 上观测到 revision 前进后缓存失效"。04 已把该形态登记进 P3-IT-11 判据原文。
4. **422 首行截断为纵深防御、当前 pydantic 下不可证伪**：`applications/application_factory.py` 的 `_sanitized_validation_detail` 把 pydantic 消息截到首行，但当前 pydantic v2 在已测各面本就输出单行，无测试钉住截断本身（`grep -rn "input_value" backend/tests` 无 Phase 3 命中）。审计判据由 PG 直查审计表的两条用例承载（PREV::`test_pg_forged_fields_are_audited_without_leaking_values`、`test_pg_cross_tenant_agent_id_is_404_and_audits_no_foreign_data`）。登记于 **#130 第 2 项**；同 issue 第 3 项登记 `uuid_parsing` 类 422 msg 含单字符输入片段（pydantic 既有语义、不进审计）。
5. **`ruff format` 边界（本轮实测，与既有预期不同）**：全树 `ruff format --check src tests` = **74 files would be reformatted, 397 files already formatted**（E25，exit 1）；与"本分支相对 main 改动的 166 个 Python 文件"交集 = **10**，与"本阶段工作树 35 个改动/新增文件"交集 = **3**，即 `src/agent_platform/core_platform/agent_execution/contracts/config.py`、`src/agent_platform/core_platform/agent_execution/orchestration/orchestrator.py`、`tests/test_agent_config_execution_compat.py`（E24，exit 1）。用 `git show HEAD:<path>` 抽出同一三文件再以 `--config backend/pyproject.toml` 复检为 **3 files already formatted**，故该偏差由**未提交的 T6/T7/T8 工作树编辑引入**，非 HEAD 内容。64 个其余全树偏差文件属既有基线（含 Memory seed 等），按 08 §1 规则 4 未修改、不冒称通过。**结论：本阶段文件的 scoped format 门禁本轮未满足**；修复归属由协调者决定（不在 T10 文件范围内）。
6. **T12/T13 与加固批延后**：seed → issue **#127**、fresh quickstart 接线与 off/on/回滚实机验证 → issue **#128**（依赖 #127），均按 08 R-39 移出本阶段，本阶段无相关证据，故 04 P3-IT-15 的"部署二进制"子判据与 P3-CM-09 的"应用回滚"子判据在本轮**无实机证据**；加固批（含上述第 1、4 项与 §7 白名单项）→ issue **#130**。
7. **P3-IT-09 的 MemoryInjection 贯通面**：本轮实测**没有** Phase 3 专用的 PG 端到端 MemoryInjection 用例；该判据的写回/日志面依赖 §8 回归中的 Phase 2 既有用例（`test_runtime_baseline.py` 88 节点、`test_runtime_postgres.py` 45 节点及各 Memory 套件），指令侧由 INS/ENGINE/WIRE 用例承载（见 §3.2 P3-IT-09 行）。该缺口**不在** #130 已列 8 项之内，本轮如实登记，归属交协调者判定。
8. **P3-FE-10b 分组缺项**：04 §6.1 的判据分组（M1、M2、M3、P3-CM-08、P3-CM-05、preview 不建 Run）未包含 `10b`，而编号清单声明"共 25 个编号"。本轮不代 04 指定归属，登记为文档缺口（属另一条文档线的修订范围）。
9. **04/08 编号同步观察**：04（读取时点 §头）已使用 R-42～R-52 引用，而 08 §2 裁定表在本轮 21:00 读取时**尚无** R-42～R-52 行（`grep -c` 命中 0）；代码注释中的 R-42/R-44/R-51/R-52 引用另记于 #130 第 4 项。本报告不裁定该差异，仅登记读取时点，供 07 判断编号绑定是否成立。

## 7. 既知缺陷登记（Phase 3 范围外，不计入本阶段通过/不通过）

| 缺陷 | 实测事实 | 归属 |
|---|---|---|
| `model_not_configured` 的 errorText 句子未进四语言字典 | 该中文句子自 initial commit 即存在于 `frontend/src/i18n/index.ts`，且不是 `zh-CN/zh-TW/en/hi` 任一字典的键，en/hi 界面显示整句中文；Phase 3 未修改该文件（本轮 `git status` 亦不含该文件）。前端以显式白名单常量 `UNTRANSLATED_ERROR_COPY` 钉住"不得新增第二个未翻译码"（FE P3-FE-13，实跑通过） | 08 §5/R-38；修复走独立 i18n 提交/issue → **#130 第 7 项**。**不得**在 06/07 记作 Phase 3 缺陷或 Phase 3 修复 |

本轮未观察到其它 P0/P1 级产品缺陷：E01/E02 无失败用例，E03～E22 无失败或 error，E23/E26 均 exit 0；唯一实测门禁偏差为 §6.5 的 scoped format（3 个本阶段文件）。

## 8. 回归范围（04 §6.3）

实际执行的回归面（各文件节点数取 E13～E22 实测；与 §2 同一批命令，未重复执行第二遍）：

- 执行编排与 Adapter：`test_execution_orchestrator.py`（160）、`test_react_engine_adapter.py`（126）、`test_local_test_adapter.py`（58）、`test_agent_execution_contract_probe.py`（45）、`test_agent_execution_contracts.py`（283）、`test_agent_execution_registries.py`（184）。
- Runtime 主机侧：`test_runtime_baseline.py`（88）、`test_runtime_engine.py`（18）、`test_runtime_postgres.py`（45，真实 PG）。
- Agent 配置与模型面：`test_agent_config_execution_compat.py`（19）、`test_agent_model_required.py`（2，两个节点均带 postgres 标记，在真实 PG 下执行）。
- 全量非 PG 组合（E01，1975 passed）与全量 PG 组合（E02，500 passed）覆盖上述文件及 Memory/迁移/渠道等既有套件；未因新实现修改任何历史 fixture 预期（本轮不修代码/测试，`git status` 中测试文件的工作树改动均属 T6/T7/T8 交付本身）。
- 静态面：架构门禁通过（E26）、`ruff check` 通过（E23）、全量 `pytest -m "not postgres"` 与 `-m postgres` 均无失败。

## 9. 出口判据对照（04 §7，逐项标注；本节不作阶段结论）

| 出口判据（04 §7 原文口径） | 本轮标注 | 依据与去向 |
|---|---|---|
| P3-UT 全通过 | **满足（执行层面）** | 28/28 编号均有承载用例且全部实测通过（§3.1、E01/E03～E11/E14/E16～E18）；判据子项的覆盖差异见 §3.5 与 §6，不得据本行推定"子判据无缺口" |
| P3-IT 全通过 | **满足（执行层面），带边界** | 22/22 编号均有承载用例且通过（§3.2）；P3-IT-09/11/15/20 的形态限制见 §6.3、§6.7 与 §3.2 边界列 |
| P3-CM 全通过 | **不满足（存在未满足项）** | P3-CM-09 的"应用回滚"子判据本轮无证据（→ #128）；P3-CM-10 无专用用例（静态/缺失证据承载）；且 08 §1 规则 4 要求的"本阶段文件 format"未满足（§6.5） |
| AC-1～AC-11 可复现 | **不评估（归 07）** | 06 不执行验收；复现入口为 §3 各编号承载用例与 §2 命令 |
| 无 P0/P1 | **满足（就本轮观察）** | E01/E02 无失败；范围外既有缺陷仅 §7 一项，按 R-38 不计入本阶段 |
| 提权/跨租户为 0 | **满足（就所测面）** | 伪造矩阵、跨租户 404、审计不含 body/字段值/秘密由 §3.1/§3.2/§3.3 所列用例断言；真实栈与生产面证据不在本轮范围（§6.2、§10） |
| 快照与审计达标 | **满足（组合证据）+ 边界** | 屏障写一次、拒写矩阵、重放、不可变、审计直查均通过；边界为 §6.1（off 态直读缺口 #130-1）与 §6.4（422 截断不可证伪 #130-2） |
| 双开关 diff 符合 | **满足（就所测面）** | 四态矩阵与 off/on 逐字段 parity 由 WIRE/PREV/ORCH 用例承载（§3.2 P3-IT-12/13/22）；实机部署形态回滚 → #128 |
| C11 有效实测达标 | **不满足（`not_measured`）** | §4；跟进 #129；按 05 §5/§6 该未测状态对阶段结论的作用由 07 判定 |
| 环境缺口阻断其上线承诺 | **登记事实** | 本轮环境缺口：C11（#129）、seed/quickstart（#127/#128）、24 条迁移 opt-in、2 条 embedding 替代环境、1 条 Milvus opt-in；其上线含义归 07 |
| 全量 pytest 由 CI 执行 | **未执行** | §10：本轮无 push/PR，无 CI run/URL；E01/E02 为本地全量选择，不等同 CI |

## 10. 未执行与不可推断项

1. **CI 未执行**：本轮无 commit、无 push、无 PR，因此无 CI run、无 CI head SHA、无 URL；E01/E02/E25/E27～E30 均为本地执行。本地结果不能替代 CI 全量 unit/postgres/frontend 结论。
2. **未执行 seed 与 fresh quickstart**：属 08 R-39 移出项（#127/#128）。
3. **未执行生产/类生产性能与真实外部模型**：C11 `not_measured`（§4）。
4. **未执行人工 M1～M3 验收与任何签字**：05 §4 的 M 项人工检查属 07 范围，本轮只提供等效自动化证据（§3.4）。
5. **未修改任何代码、测试、其它文档**：本轮仅新增本双语 06 两份文件；未创建 07，未回填历史结论。
6. **无 Phase 4/5/6 证据**：04 P3-CM-10 为"不得偷跑"的边界核对，本轮以架构门禁与代码缺失为证据，不产生任何 Phase 4+ 结论。

## 11. 协调者补记（取证后修复，2026-11-13）

1. **§6.5 format 偏差已修复**：本报告取证结束后，协调者对恰好三个偏差文件（`contracts/config.py`、`orchestration/orchestrator.py`、`tests/test_agent_config_execution_compat.py`）执行了 `ruff format`；复验：本阶段 35 个文件的 scoped `ruff format --check` → 全部 already formatted（含修复后的 3 个），`ruff check src tests` → All checks passed，`pytest tests/test_agent_execution_phase3_config.py tests/test_agent_execution_phase3_wiring.py tests/test_agent_config_execution_compat.py -q` → **106 passed**，`pytest -q -m "not postgres"` → **1975 passed, 528 deselected**。§9 的 scoped format 出口判据自本补记起满足；全树 74 个历史偏差文件不变，仍按 08 §1 规则 4 不属本阶段范围。
2. **§6.9 已解决**：08 §2 现已含 R-42～R-52（协调者核验：中英裁定表均 52 行、逐号计数相等），07 的编号绑定成立。
3. **§6.7 处置**：P3-IT-09 的 MemoryInjection PG 端到端缺口登记为 issue **#130** 第 9 项。
4. **§6.8 处置**：`P3-FE-10b` 已补入 04 §6.1 登记表的 M2 分组（双语，协调者修订）。

## 附录 A 原始输出尾部汇总

| 证据 | 命令要点 | 输出尾部原文 |
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
| A-24 | `ruff format --check <本阶段 35 文件>` | `3 files would be reformatted, 32 files already formatted`（`contracts/config.py:160`、`orchestration/orchestrator.py:303`、`tests/test_agent_config_execution_compat.py`） |
| A-25 | `ruff format --check src tests` | `74 files would be reformatted, 397 files already formatted` |
| A-26 | `python ../scripts/check_architecture.py` | `architecture gate passed` |
| A-27 | `npx playwright test tests/agent-execution-config.spec.ts --reporter=line` | `37 passed (32.7s)` |
| A-28 | `npm run typecheck` | `> tsc --noEmit`（无诊断输出） |
| A-29 | `npm run check:i18n` | `Verified 2075 translations in zh-CN, zh-TW, en, hi` |
| A-30 | `npm run build` | `✓ built in 3.69s`（chunk >500 kB 告警为既有体积提示） |
| A-31 | `alembic heads` / `alembic current` | `0058_agent_execution_metadata (head)` / `0058_agent_execution_metadata (head)` |
| A-32 | `psql -tAc "select rolname, rolcreatedb, rolsuper ..."` | `agent\|t\|t` |
| A-33 | `pytest -q --collect-only <9 个 phase3 文件>` | `413 tests collected in 1.25s` |
| A-34 | `pytest -m postgres -q --collect-only <MIG/SNAP/PREV/COMPAT>` | `64` 个 PG 节点 |
| A-35 | `git rev-parse HEAD` / `git status --porcelain \| wc -l` | `37b08f8a812558b7d80e33987fd496e9145410dc` / `44` |

## 附录 B 采集方法与可复算性

1. **编号映射的采集方式**：以 `pytest -q --collect-only` 的真实 node ID 为唯一权威集合（A-33/A-34 与 §8 各文件节点数同源），再用脚本把每个 P3 编号在测试源码中的出现位置解析为三类来源——函数名前缀（`test_p3_utNN_*` / `test_p3_itNN_*`）、函数 docstring 内的 `P3-…` 标注、以及分区注释头（`# P3-IT-06/07/08/18 + P3-CM-06 ...`）；随后逐条校验"该编号的每个承载函数名都存在于收集集合中"。§3 各行括号中的数字就是该函数在 pytest 中的**参数展开节点数**，不是函数个数。
2. **可复算路径**：任一编号按其 `别名::函数` 复算，例如 `uv run --directory backend pytest "tests/test_agent_execution_phase3_snapshots.py::test_pg_barrier_entry_clean_gate_refuses_every_payload_class_before_sql" -q -rs`（需 §2 的 PG 前置），应得 `24 passed`（§3.2 P3-IT-08 行中该函数的节点数）。
3. **不得复算为覆盖数**：同一函数可同时承载多个编号（例如 WIRE::`test_declaration_divergence_refuses_before_any_snapshot_or_start` 同时出现在 P3-IT-03 与 P3-IT-22 行），因此各行节点数**不可相加**。
4. **本轮不产出原始数据归档**：C11 无原始样本可归档（§4）；Playwright 的 trace/截图随 `npx playwright test` 的默认输出目录存在，属本机临时产物，未按 §1 的"证据生命周期"持久归档。
