# Phase 1 · 执行契约与注册中心 — 测试报告

> 状态：本地批准的测试方案范围与出口证据已满足；23 条 UT/IT 与 6 条 CM 全部通过；完整套件/CI 待后续执行，Phase 1 尚未正式验收或取得人工签字
> 创建：2026-11-08
> 依据：`04-test-plan.md`（P1-UT-01～12、P1-IT-01～11、P1-CM-01～06）、`02-requirements.md`（FR/AC）、`08-implementation-breakdown.md`（T2～T6、R1～R11）
> 执行：T7 独立执行者；执行覆盖：2026-11-08～2026-11-09；最终当前树复跑：2026-11-09

## 1. 测试范围与环境

**范围**：严格按 `04-test-plan.md` 执行六类 DTO、安全错误目录、Adapter 全生命周期、Engine/Protocol/Adapter 注册中心、精确版本解析、事件 high-water、LocalTestAdapter、结构独立第二 Adapter、生产零接线与既有回归。未修改测试方案，未把任何 skip、未执行项或环境缺失记为通过。

| 环境 | 配置 | 用途 |
|---|---|---|
| 本机 Darwin 27.0.0 x86_64 / Python 3.11.9 / uv | focused 用例为纯内存；未连接模型或外部 Engine | 本报告全部 F 当前树 focused/static 执行 |
| T6 历史静态与非 PG 回归证据 | 基线 `4dfcfb41e9cbb799753986c2d76134514bbd19be`；仅作初始 skip/门禁历史，最终计数已由 2026-11-09 当前树复跑更新 | CM01～06 的历史对照与初始环境缺口 |
| 独立 Docker PostgreSQL | `nexusdesk-phase1-pg-838b99d6`，`pgvector/pgvector:pg17`；专用空数据库/卷、loopback 动态端口；既有 Phase 0 容器未复用或修改 | 从空库 `alembic upgrade head`，随后实际执行 28 个 runtime_postgres + 6 个 open_platform 用例 |
| CI（GitHub Actions + PostgreSQL service） | 未执行；需要专用 `TEST_DATABASE_URL` | 全量套件与 CI 分组，当前 PENDING |
| 模型 | 未使用；LocalTest/ContractProbe 为可编程 scripted Adapter | 自动化契约场景 |

**证据目录**：本次最终当前树复跑（下文 **F**）为 `/tmp/nexusdesk-t7-final-evidence.DynKi0`，R6 RED-first/修复证据为 `/tmp/nexusdesk-phase1-r6-fix-evidence`，原 T7 为 `/tmp/nexusdesk-t7-evidence.cNI1ch`，T6 为 `/tmp/nexusdesk-t6-evidence.Ph3A4O`，Docker PostgreSQL 为 `/tmp/nexusdesk-phase1-pg-4ph_1qsi`。F 的 clean-source 架构 shadow 位于 F/clean-source-shadow；T6 历史 shadow 为 `/tmp/nexusdesk-t6-arch-shadow.zIfW0Y`。这些是未版本化的本地临时日志，可能随系统清理而消失；附录嵌入关键命令、原始输出和计数，使结论不依赖日志或容器长期存在。日志未记录环境变量值、凭据或数据库 URL；Docker 凭据仅存在于权限 0600 的临时 env 文件，本次仅安全 source，未读取、打印或复制其内容。容器在报告形成时仍运行以供独立 review 复跑，由 controller 后续清理；T7 不停止或删除它。

**R6 源码/测试差量与文档分类**：F 将原 T7 的 18 个源码模块及 7 个测试辅助/顶层模块 SHA-256 清单与当前树逐项比较。25 项中**恰好两项**改变：`backend/src/agent_platform/core_platform/agent_execution/registry/adapter_registry.py` 与 `backend/tests/test_agent_execution_registries.py`；其余 23 项一致。旧“25 文件全部未变”的主张不再适用于当前树。R11/05 等文档变化单列为 documentation-only：相对基线的 12 个 tracked modified 路径仍全为 README/01～05 双语资料，08 双语资料为既有 untracked 文档；06/07 是后续形成的测试/验收报告。当前 protected-path diff 仍为零，且 F 已重新执行静态检查、81 个非 PG 回归及 34 个 PG 节点，而非复用旧绿色计数。

**初始 skip 与环境缺口闭环**：F focused 命令全部 `0 skipped`。T6 初次回归中，`test_runtime_postgres.py` 的 28 项与 `test_open_platform.py` 的 6 项因缺少已迁移专用 PostgreSQL 测试库而 skip，当时未记为通过。随后经用户明确授权，使用独立 Docker 空库完成迁移并在同一批 34 个节点上取得 **34 passed、0 skipped、0 failed**，初始环境缺口已闭环。完整套件与 CI 仍未运行。

**环境与数据确定性**：使用固定 execution/tenant/agent UUID 和固定输入；LocalTest/ContractProbe 事件 ID 由 execution ID 与 ordinal 派生，时间戳由固定 epoch 派生；超时由手动时钟/事件闸门触发，而非靠真实等待决定语义。F 分别连续完整运行 LocalTest 文件两轮（均 58 passed）和 ContractProbe 文件两轮（均 45 passed），计数及通过/跳过语义一致。公共套件的 25 个方法在两个 Adapter 上均展开为 37 个 common cases；LocalTest 58 = 37 common + 21 个专属/对抗/静态 cases，ContractProbe 45 = 37 common + 8 个 focused cases。

## 2. 执行总览

| 项 | 结果 | 证据 |
|---|---|---|
| contracts + registries | **457 passed, 0 skipped**（283 + 174） | 附录 A-1；F `contracts-registries.log` |
| LocalTestAdapter 第 1 轮 | **58 passed, 0 skipped** | 附录 A-2；F `localtest-run1.log` |
| LocalTestAdapter 第 2 轮 | **58 passed, 0 skipped** | 附录 A-2；F `localtest-run2.log` |
| ContractProbe 第 1 轮 | **45 passed, 0 skipped** | 附录 A-3；F `probe-run1.log` |
| ContractProbe 第 2 轮 | **45 passed, 0 skipped** | 附录 A-3；F `probe-run2.log` |
| 四文件 focused 合并 | **560 passed, 0 skipped** | 附录 A-4；F `four-file.log` |
| 显式 UT-12 三节点 | **3 passed, 0 skipped** | 附录 A-5；F `ut12-three-nodes.log` |
| 独立 T5 第二 Adapter 结构节点 | **1 passed, 0 skipped** | 附录 A-6；F `t5-probe-structural-node.log` |
| R6 同工厂/自定义相等四个显式节点 | **4 passed, 170 deselected, 0 skipped** | 附录 A-12；F `r6-four-selected.log`；是 174 项的子集，不增加独立覆盖 |
| Docker PostgreSQL 最终复跑 | **34 passed, 0 skipped, 0 failed**（28 + 6） | 附录 A-9；F `postgres-regression-final.log` |
| 既有回归合计 | **115 passed, 0 skipped, 0 failed**（81 非 PG + 34 Docker PG） | 附录 A-9；CM03/AC-8 本地回归通过 |
| F Ruff / format / core boundaries | lint 通过；25 files formatted；9 passed | 附录 A-8 |
| 完整本地 pytest 套件 | **PENDING：未运行** | §6、§9 |
| CI Backend / Frontend | **PENDING：未运行，无 URL** | §9 |

F 的上述八条原 T7 pytest 命令合计执行 **1227 个测试节点，1227 passed，0 skipped**；该数包含有意的重复执行，不能解释为 1227 个独立用例。去重 focused 集合以四文件的 **560 passed** 为准；R6 四节点另跑与三项非 PG 分文件/合并复跑均只是重复确认，不叠加为新的覆盖数。独立 Docker 最终复跑另执行 **34 个 PG 节点，34 passed，0 skipped**；既有回归去重集合总计 81 + 34 = **115 passed**。报告行处置为：**UT/IT 23 条通过，CM01～06 六条通过，共 29/29 通过**。本地批准的测试方案范围及出口证据现已满足；完整套件/CI、最终总体包评审与人工验收仍是独立下游事项。

### 2.1 AC 溯源与判定

| 验收标准 | 覆盖用例 | 当前判定 |
|---|---|---|
| AC-1 | P1-UT-01、P1-UT-02 | 通过（focused 实测） |
| AC-2 | P1-IT-01、P1-IT-02 | 通过（两个 Adapter 实测） |
| AC-3 | P1-IT-07、P1-IT-08 | 通过（两个 Adapter 实测） |
| AC-4 | P1-UT-05、P1-UT-06、P1-IT-03～05、P1-CM-04 | 通过（focused 安全输出实测） |
| AC-5 | P1-UT-08、P1-UT-09、P1-IT-10 | 通过（含独立结构节点与同工厂跨三元组拒绝） |
| AC-6 | P1-UT-08～P1-UT-11 | 通过（精确失败顺序、任何重复注册、同工厂跨三元组与工厂边界实测） |
| AC-7 | P1-IT-05、P1-IT-06、P1-IT-09、P1-IT-11 | 通过（含两轮确定性/清理验证） |
| AC-8 | P1-CM-01～06 | **通过（本地范围）**：静态保护、81 个非 PG 回归及 34 个 Docker PostgreSQL 回归全部通过；完整 CI 另列 PENDING |

### 2.2 实施任务溯源

| 任务 | 本报告覆盖 | 当前证据 |
|---|---|---|
| T2 契约与包入口 | P1-UT-01～07、P1-UT-12；AC-1/4 | contracts 实测、UT-12 累计静态节点、D-01 |
| T3 Registry | P1-UT-08～12；AC-5/6 | 174 个 registries 实测、UT-12 累计静态节点、D-02/D-07 |
| T4 LocalTestAdapter | P1-IT-01～09、P1-IT-11、P1-UT-12、P1-CM-04/05 | 58×2、公共 37 cases、UT-12 三节点、D-03/D-04/D-08 |
| T5 独立 ContractProbe | P1-IT-10 及公共 P1-IT-01～09 复用 | 45×2；独立结构节点 1 passed；D-05 |
| T6 质量/回归证据 | P1-CM-01～06、AC-8、UT-12/T5 显式节点 | T6 历史 logs + F 当前树静态/81 非 PG/独立 Docker 34 PG 实测；D-06 |

## 3. 单元测试（P1-UT）逐条结果

以下每行均为独立判定。表内列出的参数化用例在对应日志中**所有参数组合均实际运行**，不是仅按文件名推断。除 UT-12 的特别说明外，证据为 F `contracts-registries.log`（457 passed）及 `four-file.log`（560 passed），执行环境均为本机纯内存。

| 编号 | 用例 | 预期（保持 04 原文） | 测试位置（file::case） | 执行环境 | 结果 | 证据 | 溯源 |
|---|---|---|---|---|---|---|---|
| P1-UT-01 | 六类模型严格参数化校验 | 合法值逐字保留；非法值均 ValidationError；strict 模式拒绝 coercion，input 不 trim | `tests/test_agent_execution_contracts.py::test_execution_base_reuses_contract_model_with_explicit_strict_frozen_policy`<br>`::test_valid_models_have_exact_fields_and_reject_unknown_fields`<br>`::test_models_reject_each_missing_required_field`<br>`::test_versions_and_serialized_computed_message`<br>`::test_exact_optional_and_status_defaults`<br>`::test_engine_and_protocol_identity_grammar`<br>`::test_adapter_version_grammar`<br>`::test_adapter_version_accepts_explicit_positive_versions`<br>`::test_request_opaque_fields_are_bounded_and_never_trimmed`<br>`::test_handle_and_event_opaque_fields`<br>`::test_request_raw_input_tenant_and_strict_scalar_rules`<br>`::test_positive_integer_fields_are_strict`<br>`::test_uuid_and_datetime_are_strict_in_python_but_idiomatic_in_json`<br>`::test_nested_json_values_reject_non_json_and_non_finite_numbers`<br>`::test_effective_capabilities_require_strict_boolean_values`（后续 `::` 均承接同一路径） | 本机纯内存 | **通过** | 283 contracts cases 全过；A-1/A-4 | FR-1、AC-1 |
| P1-UT-02 | 默认集合实例隔离 | 实例间无可变默认共享，原实例不受影响 | `tests/test_agent_execution_contracts.py::test_default_collections_are_not_shared_and_nested_values_remain_mutable` | 本机纯内存 | **通过** | A-1/A-4 | FR-1、AC-1 |
| P1-UT-03 | DTO/Adapter 跨对象身份一致性 | 独立 DTO 仅校验自身；不匹配身份在 Adapter 边界/公共套件被拒绝，绝不修补 | `tests/test_agent_execution_contracts.py::test_handle_request_identity_boundary_rejects_every_key_mismatch`<br>`tests/test_agent_execution_contracts.py::test_request_adapter_identity_boundary`<br>`tests/test_agent_execution_contracts.py::test_result_and_event_handle_identity_boundary`<br>`tests/test_agent_execution_contracts.py::test_event_session_identity_boundary_includes_none`<br>`tests/test_local_test_adapter.py::TestLocalTestAdapter::test_request_identity_mismatch_fails_before_handle`<br>`tests/test_agent_execution_contract_probe.py::TestContractProbeAdapter::test_request_identity_mismatch_fails_before_handle` | 本机纯内存 | **通过** | A-1～A-4；所有参数组合运行 | FR-1、FR-2 |
| P1-UT-04 | Result 终态 output/error 组合 | completed+error、failed 无 error/带 output/带 cancelled error、cancelled 带 output 或 error 均直接 ValidationError；合法 artifacts/usage/engine_metadata 各终态均允许 | `tests/test_agent_execution_contracts.py::test_every_result_output_error_combination`<br>`tests/test_agent_execution_contracts.py::test_result_rejects_non_terminal_or_unknown_status`<br>`tests/test_agent_execution_contracts.py::test_terminal_metadata_and_artifact_only_results_are_valid` | 本机纯内存 | **通过** | 18 个组合及其他参数全过；A-1/A-4 | FR-1、FR-2 |
| P1-UT-05 | 十类错误目录、静态 message 与安全 round-trip | code 唯一归属；直接 `model_validate(model_dump())`、直接 `model_validate_json(model_dump_json())` 及 nested mapping/JSON 成功往返并保留安全 model_dump；精确目录 message 仅作 no-op token 且重算；任意/不匹配/非 string message 及 code 缺失/非法时的 message 均 ValidationError，绝不覆盖 computed property；异常/input/config/provider 文本和堆栈不泄露 | `tests/test_agent_execution_contracts.py::test_error_category_and_complete_static_code_catalog`<br>`tests/test_agent_execution_contracts.py::test_execution_error_mapping_round_trip_preserves_static_message`<br>`tests/test_agent_execution_contracts.py::test_execution_error_json_round_trip_preserves_static_message`<br>`tests/test_agent_execution_contracts.py::test_failed_result_mapping_round_trip_preserves_nested_static_error`<br>`tests/test_agent_execution_contracts.py::test_failed_result_json_round_trip_preserves_nested_static_error`<br>`tests/test_agent_execution_contracts.py::test_exact_direct_message_is_noop_integrity_token`<br>`tests/test_agent_execution_contracts.py::test_error_rejects_invalid_message_integrity_tokens`<br>`tests/test_agent_execution_contracts.py::test_failed_result_rejects_nested_arbitrary_message`<br>`tests/test_agent_execution_contracts.py::test_error_rejects_category_code_mismatch`<br>`tests/test_agent_execution_contracts.py::test_retryable_is_limited_to_explicit_retry_categories`<br>`tests/test_agent_execution_contracts.py::test_non_retryable_codes_reject_retryable_true`<br>`tests/test_agent_execution_contracts.py::test_error_rejects_unknown_or_non_string_enum_values`<br>`tests/test_agent_execution_contracts.py::test_error_details_reject_arbitrary_diagnostics`<br>`tests/test_agent_execution_contracts.py::test_error_details_allow_only_bounded_identity_and_slugs`<br>`tests/test_agent_execution_contracts.py::test_adapter_exceptions_and_normalization_never_expose_raw_exception_text`<br>`tests/test_agent_execution_contracts.py::test_safe_exceptions_suppress_implicit_context_in_formatted_tracebacks` | 本机纯内存 | **通过** | 30-code 目录及全部参数组合；A-1/A-4；历史修复见 D-01 | FR-1、FR-4、AC-4、R9 |
| P1-UT-06 | EngineCapabilities 11 项声明 | 未声明项均严格 false；声明 tool_calling 不自动改变其他能力或授权，非 bool 被拒绝 | `tests/test_agent_execution_contracts.py::test_capabilities_have_exact_strict_defaults_and_no_implications`<br>`tests/test_agent_execution_contracts.py::test_each_capability_true_declaration_is_independent` | 本机纯内存 | **通过** | 11 项逐一参数化；A-1/A-4 | FR-2、FR-4、AC-4 |
| P1-UT-07 | AgentEvent 字段与确定性 | 字段合法；独立 Event 不施加跨事件排序，禁止 wall-clock/random 默认工厂 | `tests/test_agent_execution_contracts.py::test_event_type_valid_grammar`<br>`tests/test_agent_execution_contracts.py::test_event_type_invalid_grammar`<br>`tests/test_agent_execution_contracts.py::test_event_sequence_is_required_strict_and_positive`<br>`tests/test_agent_execution_contracts.py::test_event_source_and_version`<br>`tests/test_agent_execution_contracts.py::test_event_requires_aware_datetime`<br>`tests/test_agent_execution_contracts.py::test_event_timestamp_is_normalized_to_utc_without_supplying_defaults`<br>`tests/test_local_test_adapter.py::test_default_event_ids_and_timestamps_have_fixed_uuid5_and_epoch_derivation`<br>`tests/test_agent_execution_contract_probe.py::test_fixed_event_derivation_and_fresh_runs_are_deterministic` | 本机纯内存 | **通过** | 全部参数化及 UUIDv5/fixed-epoch 实测；A-1～A-4 | FR-4 |
| P1-UT-08 | 描述符独立注册、重复与引用校验 | Engine/Protocol 可独立存在；完全相同或冲突重复均拒绝；未知引用拒绝；disabled 可注册不可解析 | `tests/test_agent_execution_registries.py::test_descriptors_are_strict_frozen_execution_contracts`<br>`tests/test_agent_execution_registries.py::test_descriptors_require_strict_boolean_enabled`<br>`tests/test_agent_execution_registries.py::test_engine_and_protocol_descriptors_validate_identity`<br>`tests/test_agent_execution_registries.py::test_adapter_descriptor_validates_explicit_version`<br>`tests/test_agent_execution_registries.py::test_registry_package_exports_only_public_registries_and_descriptors`<br>`tests/test_agent_execution_registries.py::test_engine_and_protocol_registries_are_independent_and_readable`<br>`tests/test_agent_execution_registries.py::test_duplicate_engine_always_fails_even_for_identical_descriptor`<br>`tests/test_agent_execution_registries.py::test_duplicate_protocol_always_fails_even_for_identical_descriptor`<br>`tests/test_agent_execution_registries.py::test_engine_and_protocol_registration_rejects_raw_configuration_safely`<br>`tests/test_agent_execution_registries.py::test_adapter_registration_requires_existing_references_in_priority_order`<br>`tests/test_agent_execution_registries.py::test_adapter_registration_allows_disabled_engine_and_protocol_references`<br>`tests/test_agent_execution_registries.py::test_duplicate_adapter_exact_triple_always_fails`<br>`tests/test_agent_execution_registries.py::test_same_factory_cannot_register_to_multiple_exact_triples`（engine/protocol/adapter-version 三参数）<br>`tests/test_agent_execution_registries.py::test_distinct_factories_are_not_rejected_when_custom_equality_says_equal`<br>`tests/test_agent_execution_registries.py::test_registration_does_not_invoke_factory` | 本机纯内存 | **通过** | 174 registry cases 全过；同一 factory 复用到不同 Engine/Protocol/version 三元组时以 `is` 身份识别并拒绝，身份比较不调用自定义 `__eq__`；第一三元组仍可解析，第二三元组不可解析，第二注册无 partial registration 且 factory 未因注册执行；自定义相等但身份不同的 factories 可分别注册解析。A-1/A-4/A-12；D-07 | FR-3、AC-5 |
| P1-UT-09 | 精确解析与 fresh-instance/weakref 边界 | 精确返回对应工厂实例，无 latest；每次解析重新调用工厂，两个同时存活结果以 `is not` 区分且状态不共享；同一存活 singleton 第二次及 A→B→A 第三次复用均以 `configuration_error/adapter_contract_mismatch` 拒绝且对象不逃逸；不可 weakref 候选首次返回前同样拒绝；weakref/gc 证明 Registry 不强留 Adapter，死亡引用在解析时清理，后续新对象不受地址复用影响且身份绝不使用 bare `id()`；任意 `__eq__` 不被调用 | `tests/test_agent_execution_registries.py::test_resolution_returns_the_exact_registered_factory_instance`<br>`tests/test_agent_execution_registries.py::test_every_resolution_constructs_fresh_state_isolated_instances`<br>`tests/test_agent_execution_registries.py::test_live_singleton_result_is_rejected_on_second_resolution`<br>`tests/test_agent_execution_registries.py::test_live_a_b_a_cycle_is_rejected_on_third_resolution`<br>`tests/test_agent_execution_registries.py::test_non_weak_referenceable_candidate_is_rejected_before_first_return`<br>`tests/test_agent_execution_registries.py::test_freshness_never_invokes_adapter_equality`<br>`tests/test_agent_execution_registries.py::test_registry_weakrefs_do_not_retain_adapters_and_dead_refs_are_pruned`<br>`tests/test_agent_execution_registries.py::test_weakref_tracking_failures_are_safe_or_propagate` | 本机纯内存 | **通过** | 含 gc/weakref 与所有异常参数；A-1/A-4；D-02 | FR-3、AC-5、R10 |
| P1-UT-10 | 未知/禁用/不兼容解析优先级 | 严格按 unknown_engine→engine_disabled→unknown_protocol→protocol_disabled→incompatible_engine_protocol→unknown_adapter_version→adapter_disabled 返回稳定 code | `tests/test_agent_execution_registries.py::test_resolution_error_precedence_including_combined_invalid_cases`<br>`tests/test_agent_execution_registries.py::test_resolution_never_falls_back_to_other_version_protocol_or_engine`<br>`tests/test_agent_execution_registries.py::test_malformed_or_unhashable_resolution_inputs_fail_closed` | 本机纯内存 | **通过** | 优先级的 8 个组合及 malformed 参数全过；A-1/A-4 | FR-3、FR-4、AC-6 |
| P1-UT-11 | 工厂/身份/Protocol 签名、awaitable 与 BaseException 边界 | 前三类分别映射 adapter_factory_failed、adapter_identity_mismatch、adapter_contract_mismatch；对 bound method 以 `Signature.bind` 占位而不执行，`get_capabilities` 绑定 0 参，其余四方法各绑定 1 参，错误 arity 为 adapter_contract_mismatch；实例在检查前不逃逸；同步 resolve 对 factory 返回的 Future/Task 以 adapter_contract_mismatch 拒绝，并 cancel 返回的 Future/Task 作为 cleanup，断言 `future.cancelled()`，Task fixture 还须 await 完成清理且无 pending task；独立边界用例验证 `CancelledError`/其他 `BaseException` 控制流不被吞掉或改写，与 Future/Task cleanup 分开断言；诊断无敏感 config 或原始异常文本 | `tests/test_agent_execution_registries.py::test_adapter_registration_rejects_invalid_or_async_factory_without_invocation`<br>`tests/test_agent_execution_registries.py::test_adapter_registration_rejects_factories_requiring_arguments`<br>`tests/test_agent_execution_registries.py::test_adapter_registration_accepts_zero_arg_compatible_signatures`<br>`tests/test_agent_execution_registries.py::test_adapter_registration_maps_signature_inspection_failure_safely`<br>`tests/test_agent_execution_registries.py::test_synchronous_factory_returning_coroutine_is_closed_and_rejected`<br>`tests/test_agent_execution_registries.py::test_factory_failures_are_safe_and_suppress_original_traceback_context`<br>`tests/test_agent_execution_registries.py::test_factory_control_flow_base_exceptions_propagate_unchanged`<br>`tests/test_agent_execution_registries.py::test_each_identity_field_mismatch_is_rejected_before_instance_escape`<br>`tests/test_agent_execution_registries.py::test_missing_malformed_identity_values_are_rejected`<br>`tests/test_agent_execution_registries.py::test_each_missing_identity_attribute_is_rejected`<br>`tests/test_agent_execution_registries.py::test_identity_property_access_failure_is_safe`<br>`tests/test_agent_execution_registries.py::test_identity_comparison_failure_is_safe_and_suppresses_context`<br>`tests/test_agent_execution_registries.py::test_each_missing_lifecycle_method_is_rejected`<br>`tests/test_agent_execution_registries.py::test_each_noncallable_lifecycle_method_is_rejected`<br>`tests/test_agent_execution_registries.py::test_async_contract_methods_reject_regular_function_shape`<br>`tests/test_agent_execution_registries.py::test_coroutine_function_stream_events_is_rejected_without_coroutine_leak`<br>`tests/test_agent_execution_registries.py::test_compliant_resolution_does_not_execute_any_lifecycle_method`<br>`tests/test_agent_execution_registries.py::test_lifecycle_shape_inspection_failures_are_safe`<br>`tests/test_agent_execution_registries.py::test_lifecycle_signature_inspection_failure_is_safe`<br>`tests/test_agent_execution_registries.py::test_lifecycle_inspection_base_exceptions_propagate_unchanged`<br>`tests/test_agent_execution_registries.py::test_each_lifecycle_method_rejects_wrong_bound_arity`<br>`tests/test_agent_execution_registries.py::test_zero_and_one_arg_compatible_lifecycle_signatures_remain_valid`<br>`tests/test_agent_execution_registries.py::test_future_returning_factory_is_rejected_and_future_is_cancelled`<br>`tests/test_agent_execution_registries.py::test_task_returning_factory_is_rejected_and_task_is_cleaned_up` | 本机纯内存 | **通过** | Future/Task 清理、9 个 wrong-arity 组合及控制流参数全过；A-1/A-4；D-02 | FR-3、AC-6、R3/R5/R10 |
| P1-UT-12 | 公共契约、Registry、LocalTest 与包入口静态依赖方向 | Contracts 不 import Registry/Worker/Repository/Factory/具体 Engine；Registry 不 import 具体 Adapter；LocalTestAdapter 不 import Registry；包入口不 eager import 测试 Adapter；既有 ContractModel 零 diff；当前任务计划覆盖的模块缺失必须失败，不得 skip 或因 absent 而通过，T4 才完成整项 | `tests/test_local_test_adapter.py::test_reusable_suite_has_no_concrete_adapter_import`<br>`tests/test_local_test_adapter.py::test_reusable_suite_uses_abstract_gate_construction`<br>`tests/test_local_test_adapter.py::test_cumulative_t2_t3_t4_modules_and_dependency_direction_are_exact` | 本机静态 AST + 纯内存 | **通过** | 显式三节点 3 passed；共同覆盖精确 18 模块存在/集合、依赖方向、no-eager-import、公共套件 import 独立/抽象 gate、`ExecutionContractModel.__bases__ == (ContractModel,)`；A-5。三节点**不检查第二 Adapter 结构**，T5 证据另见 A-6 | FR-6、G1 |

## 4. 契约与集成测试（P1-IT）逐条结果

两个 Adapter 的公共位置分别为 `tests/test_local_test_adapter.py::TestLocalTestAdapter` 与 `tests/test_agent_execution_contract_probe.py::TestContractProbeAdapter`。下表逐行给出具体继承方法；25 个公共方法在各自文件展开为 37 个 common cases，所有参数组合均在 A-2/A-3 的两轮及 A-4 的合并运行中通过。环境均为本机纯内存，无 DB、网络、模型或真实进程。

| 编号 | 用例 | 预期（保持 04 原文） | 测试位置（file::case） | 执行环境 | 结果 | 证据 | 溯源 |
|---|---|---|---|---|---|---|---|
| P1-IT-01 | 成功、并发/重复收集、第二次 start/consumer | 五方法与身份属性正常，LocalTest 序号连续，所有收集返回相等 completed Result；第二次 start 和两种第二次 consumer 尝试均为 `configuration_error/invalid_adapter_state`，不允许 stream replay/restart | `tests/test_local_test_adapter.py::TestLocalTestAdapter::test_capabilities_start_stream_collect_success`<br>`tests/test_local_test_adapter.py::TestLocalTestAdapter::test_immediate_concurrent_and_repeated_collectors_share_result`<br>`tests/test_local_test_adapter.py::TestLocalTestAdapter::test_concurrent_second_consumer_and_claim_after_aclose_are_rejected`<br>`tests/test_agent_execution_contract_probe.py::TestContractProbeAdapter::test_capabilities_start_stream_collect_success`<br>`tests/test_agent_execution_contract_probe.py::TestContractProbeAdapter::test_immediate_concurrent_and_repeated_collectors_share_result`<br>`tests/test_agent_execution_contract_probe.py::TestContractProbeAdapter::test_concurrent_second_consumer_and_claim_after_aclose_are_rejected` | 本机纯内存 | **通过** | 两个 Adapter 各 3 common cases；A-2～A-4 | AC-2、FR-2 |
| P1-IT-02 | 多事件与空事件 | 多事件保持顺序和 payload；空事件可直接得到有效终态，stream 不悬挂 | `tests/test_local_test_adapter.py::TestLocalTestAdapter::test_multiple_events_preserve_order_payload_and_empty_stream_terminates`<br>`tests/test_agent_execution_contract_probe.py::TestContractProbeAdapter::test_multiple_events_preserve_order_payload_and_empty_stream_terminates` | 本机纯内存 | **通过** | A-2～A-4 | FR-2、AC-2 |
| P1-IT-03 | start 前身份/EngineUnavailable/ResourceExhausted | 均在有效 Handle 产生前失败，分类正确；仅明确启动前 EngineUnavailable 与 ResourceExhausted 可 retryable，启动后失败及 timeout 默认 False，Phase 1 不重试 | `tests/test_local_test_adapter.py::TestLocalTestAdapter::test_request_identity_mismatch_fails_before_handle`<br>`tests/test_local_test_adapter.py::TestLocalTestAdapter::test_prestart_errors_precede_handle_and_preserve_retryability`<br>`tests/test_agent_execution_contract_probe.py::TestContractProbeAdapter::test_request_identity_mismatch_fails_before_handle`<br>`tests/test_agent_execution_contract_probe.py::TestContractProbeAdapter::test_prestart_errors_precede_handle_and_preserve_retryability` | 本机纯内存 | **通过** | 每个 Adapter 均含 prestart 4 参数；A-2～A-4 | FR-2、FR-5、AC-4 |
| P1-IT-04 | Configuration/Protocol/Authentication/PermissionDenied | 各场景稳定映射静态 category/code/message/retryable；Registry/Adapter 边界不复制 Pydantic 原值或异常字符串 | `tests/test_local_test_adapter.py::TestLocalTestAdapter::test_stream_errors_are_safe_for_stream_and_all_collectors` 的 `configuration_error`、`protocol_error`、`authentication_error`、`permission_denied` 参数<br>`tests/test_agent_execution_contract_probe.py::TestContractProbeAdapter::test_stream_errors_are_safe_for_stream_and_all_collectors` 的同名四参数<br>`tests/test_agent_execution_registries.py::test_engine_and_protocol_registration_rejects_raw_configuration_safely` | 本机纯内存 | **通过** | 两个 Adapter 各 4 个错误参数；A-1～A-4 | AC-4、FR-4 |
| P1-IT-05 | Workspace/Internal/未知异常/模拟进程故障 | 未知异常仅映射 internal_error/internal_error；模拟故障为 internal_error/simulated_process_failure；process_id 为 None，无真实 Host 断言 | `tests/test_local_test_adapter.py::TestLocalTestAdapter::test_stream_errors_are_safe_for_stream_and_all_collectors` 的 `workspace_error`、`internal_error` 参数<br>`tests/test_local_test_adapter.py::TestLocalTestAdapter::test_unknown_exception_and_simulated_process_failure_are_distinct_and_safe`<br>`tests/test_agent_execution_contract_probe.py::TestContractProbeAdapter::test_stream_errors_are_safe_for_stream_and_all_collectors` 的同名两参数<br>`tests/test_agent_execution_contract_probe.py::TestContractProbeAdapter::test_unknown_exception_and_simulated_process_failure_are_distinct_and_safe` | 本机纯内存 | **通过** | A-2～A-4 | AC-4、AC-7、FR-5 |
| P1-IT-06 | 手动时钟 timeout | 不实际等待即唤醒等待者，得到 failed + timeout/execution_timeout；不自动重试，启动后 timeout 默认不可重试 | `tests/test_local_test_adapter.py::TestLocalTestAdapter::test_manual_clock_timeout_wakes_collectors_without_real_waiting`<br>`tests/test_agent_execution_contract_probe.py::TestContractProbeAdapter::test_manual_clock_timeout_wakes_collectors_without_real_waiting` | 本机纯内存、手动时钟 | **通过** | A-2～A-4 | AC-7、FR-4 |
| P1-IT-07 | 长运行重复/并发 cancel 与收集 | cancel 幂等，闸门释放且流关闭，所有收集得到相等 cancelled Result（error=None），owned/test 任务全部清理 | `tests/test_local_test_adapter.py::TestLocalTestAdapter::test_repeated_concurrent_cancel_closes_stream_and_collectors`<br>`tests/test_agent_execution_contract_probe.py::TestContractProbeAdapter::test_repeated_concurrent_cancel_closes_stream_and_collectors` | 本机纯内存、事件闸门 | **通过** | A-2～A-4 | AC-3、FR-2 |
| P1-IT-08 | 取消/成功竞争与迟到事件 | 首个终态原子获胜；已成功时 cancel 为 no-op，已取消时成功被抑制；终态 Result 可见后无事件可见，无第二终态 | `tests/test_local_test_adapter.py::TestLocalTestAdapter::test_cancel_wins_gate_race_and_suppresses_late_events_and_success`<br>`tests/test_local_test_adapter.py::TestLocalTestAdapter::test_success_wins_gate_race_and_is_never_retroactively_cancelled`<br>`tests/test_local_test_adapter.py::TestLocalTestAdapter::test_terminal_visibility_never_precedes_queued_or_active_stream_events`<br>`tests/test_agent_execution_contract_probe.py::TestContractProbeAdapter::test_cancel_wins_gate_race_and_suppresses_late_events_and_success`<br>`tests/test_agent_execution_contract_probe.py::TestContractProbeAdapter::test_success_wins_gate_race_and_is_never_retroactively_cancelled`<br>`tests/test_agent_execution_contract_probe.py::TestContractProbeAdapter::test_terminal_visibility_never_precedes_queued_or_active_stream_events` | 本机纯内存、事件闸门 | **通过** | 两个 Adapter 各 3 cases；A-2～A-4 | AC-3、FR-2 |
| P1-IT-09 | duplicate/conflict/gap/迟到/aclose | 完整重复和迟到事件原样 yield 且不推进/降低水位；内容冲突为 event_identity_conflict；gap 合法；timestamp 不排序；迭代关闭无 pending task | `tests/test_local_test_adapter.py::TestLocalTestAdapter::test_duplicates_late_events_gaps_and_timestamps_follow_sequence_rules`<br>`tests/test_local_test_adapter.py::TestLocalTestAdapter::test_same_event_id_with_different_content_is_never_repaired`<br>`tests/test_local_test_adapter.py::TestLocalTestAdapter::test_early_aclose_cleans_owned_tasks_and_does_not_permit_replay`<br>`tests/test_agent_execution_contract_probe.py::TestContractProbeAdapter::test_duplicates_late_events_gaps_and_timestamps_follow_sequence_rules`<br>`tests/test_agent_execution_contract_probe.py::TestContractProbeAdapter::test_same_event_id_with_different_content_is_never_repaired`<br>`tests/test_agent_execution_contract_probe.py::TestContractProbeAdapter::test_early_aclose_cleans_owned_tasks_and_does_not_permit_replay` | 本机纯内存 | **通过** | A-2～A-4 | AC-7、FR-4 |
| P1-IT-10 | 注册独立 ContractProbe 并复用整套公共契约 | 第二 Adapter 结构独立且非 LocalTestAdapter 子类；套件不 import LocalTest 具体类型；不修改公共契约、Registry 接口或 Worker | `tests/test_agent_execution_contract_probe.py::TestContractProbeAdapter`（继承全部 25 个公共方法，展开 37 cases）<br>`tests/test_agent_execution_contract_probe.py::test_registry_resolves_fresh_probe_instances_with_isolated_executions`<br>`tests/test_agent_execution_contract_probe.py::test_probe_has_no_local_test_inheritance_import_or_delegation`<br>`tests/test_local_test_adapter.py::test_reusable_suite_has_no_concrete_adapter_import`<br>`tests/test_local_test_adapter.py::test_reusable_suite_uses_abstract_gate_construction` | 本机纯内存 + 静态 AST | **通过** | probe 45×2（37 common + 8 focused）；独立结构节点另跑 1 passed；A-3～A-6。UT-12 三节点不承担此结构断言 | AC-5、G1、G2 |
| P1-IT-11 | LocalTest 全场景两轮、stream failure/collector cancellation/清理 | 语义、错误和事件脚本确定，无跨场景状态；success/failure/cancel/timeout/iterator close 后所有 owned tasks 已 await/done，无 Adapter-owned 或 test-created pending task；completed task 引用可保留并以 `all(done)` 检查，执行前 empty-set 断言另行保留 | `tests/test_local_test_adapter.py`（完整文件两轮）<br>`tests/test_local_test_adapter.py::TestLocalTestAdapter::test_one_cancelled_collector_does_not_cancel_shared_execution`<br>`tests/test_local_test_adapter.py::TestLocalTestAdapter::test_lone_collector_cancellation_cleans_owned_work_before_propagation`<br>`tests/test_local_test_adapter.py::TestLocalTestAdapter::test_stream_errors_are_safe_for_stream_and_all_collectors`<br>`tests/test_local_test_adapter.py::test_close_broadcasts_to_every_pending_anext_waiter`<br>`tests/test_local_test_adapter.py::test_cancel_propagates_new_caller_cancellation_after_runner_cleanup`<br>`tests/test_local_test_adapter.py::test_aclose_propagates_new_caller_cancellation_after_finished_runner_drains` | 本机纯内存 | **通过** | 连续两轮均 58 passed、0 skipped；计数/语义一致；所有 owned tasks 已 await/done、无 pending task，保留 completed 引用并以 `all(done)` 核对，执行前 empty-set 为独立条件；A-2。含 37 common + 21 LocalTest 专属/对抗/静态 cases | AC-7、FR-5、R11 |

## 5. 通用核对项（P1-CM）逐条结果

| 编号 | 核对项 | 通过标准（保持 04 原文） | 测试位置/命令 | 执行环境 | 结果 | 证据 | 溯源 |
|---|---|---|---|---|---|---|---|
| P1-CM-01 | 数据库迁移不变 | `alembic heads` 为 `0057_industry_pack_runtime`；相对 `4dfcfb41e9cbb799753986c2d76134514bbd19be` 无版本文件新增/修改，无 downgrade 需求 | `uv run alembic heads`<br>独立 Docker 空库 `alembic upgrade head` 与 post-test `alembic current`<br>`git diff --exit-code 4dfcfb41e9cbb799753986c2d76134514bbd19be -- backend/migrations/versions/` | 本机只读 + 独立 Docker 空库迁移 | **通过** | F `alembic-heads.log` 与 `protected-paths.*`；T6 `gate6-*`；Docker 初始 `RESULTS.txt`、`alembic-upgrade.log` 及 F `postgres-alembic-current-final.log`：初始 upgrade exit 0，当前 heads/current 均为 `0057_industry_pack_runtime (head)`；A-7/A-9 | AC-8、G4 |
| P1-CM-02 | 生产零接线与配置不变 | Worker/Factory/组合根未调用新执行路径，无新运行时开关、Settings、外部 Engine、凭据、前端或 deploy 变更 | 相对基线的 protected-path `git diff --exit-code`：既有 ContractModel/runtime、Worker/Repository/Factory/composition、Settings、env examples、frontend、deploy、migrations、lock | 本机只读工作树检查 | **通过** | F 当前 protected-path diff=0；25 项 Python SHA 仅两个预期 R6 文件改变，其余变化按文档/报告类别单列；T6 `protected-paths-zero-diff.*`、`change-allowlist-check.*` 仅作历史对照；A-7/A-11 | AC-8、FR-6 |
| P1-CM-03 | 公共 API/SSE/Run 契约兼容 | RunRequest/RunSnapshot/RunStatus、事件名和路由未改；相关既有 Runtime/API/SSE 测试全绿 | `tests/test_runtime_engine.py`<br>`tests/test_runtime_postgres.py`<br>`tests/test_open_platform.py`<br>`tests/test_extension_contracts.py`<br>`tests/test_runtime_baseline.py` | F 本机非 PG + 独立 Docker PostgreSQL 17 已迁移库实测 | **通过** | 81 non-PG passed（17+56+8）+ 34 Docker PG passed（28 runtime_postgres + 6 open_platform）= **115 passed, 0 skipped, 0 failed**；最终复跑 exit 0，14.10s；A-9 | AC-8、FR-6 |
| P1-CM-04 | 敏感信息与日志 | DTO/注册/Adapter 安全输出不含 secret-marker、凭据、连接串、Pydantic 原值、异常原文、原始堆栈或客户输入 | `tests/test_agent_execution_contracts.py::test_error_details_reject_arbitrary_diagnostics`<br>`tests/test_agent_execution_contracts.py::test_adapter_exceptions_and_normalization_never_expose_raw_exception_text`<br>`tests/test_agent_execution_contracts.py::test_safe_exceptions_suppress_implicit_context_in_formatted_tracebacks`<br>`tests/test_agent_execution_registries.py::test_factory_failures_are_safe_and_suppress_original_traceback_context`<br>`tests/test_local_test_adapter.py::TestLocalTestAdapter::test_pre_chained_safe_stream_error_does_not_retain_raw_exception_chain`<br>`tests/test_local_test_adapter.py::test_scenario_deepcopy_runtime_failure_is_safe_invalid_scenario`<br>`tests/test_local_test_adapter.py::test_runtime_origin_safe_error_does_not_retain_raw_exception_chain`<br>`tests/test_agent_execution_contract_probe.py::TestContractProbeAdapter::test_pre_chained_safe_stream_error_does_not_retain_raw_exception_chain` | 本机纯内存；合成 `secret-marker`，未记录真实秘密 | **通过（focused 范围）** | 457、58×2、45×2、560 全过；A-1～A-4；D-01/D-02/D-04 | AC-4、非功能 |
| P1-CM-05 | 多租户与实例边界 | tenant_id 不被注册中心改写；不同 request/解析实例无可观察状态串用；事件 high-water 仅存在每 active execution | `tests/test_agent_execution_registries.py::test_every_resolution_constructs_fresh_state_isolated_instances`<br>`tests/test_local_test_adapter.py::test_registry_resolves_exact_identity_with_two_live_isolated_instances`<br>`tests/test_local_test_adapter.py::TestLocalTestAdapter::test_deterministic_fresh_runs_have_no_cross_instance_high_water`<br>`tests/test_agent_execution_contract_probe.py::test_registry_resolves_fresh_probe_instances_with_isolated_executions`<br>`tests/test_agent_execution_contract_probe.py::TestContractProbeAdapter::test_deterministic_fresh_runs_have_no_cross_instance_high_water` | 本机纯内存 | **通过（focused 范围）** | 两个 Adapter 的独立 execution/high-water 与 fresh resolution 全过；A-1～A-4 | FR-1、FR-3、非功能 |
| P1-CM-06 | 代码质量与依赖边界 | 新增测试及 `ruff check src tests`、受影响文件 `ruff format --check`、`test_core_boundaries.py` 全绿；R8 依赖方向满足，`backend/uv.lock` 零 diff | `uv run ruff check src tests`<br>`uv run ruff format --check <25 个 Phase 1 源码/测试文件>`<br>`uv run pytest -q tests/test_core_boundaries.py`<br>UT-12 三节点、clean-source architecture shadow、uv.lock/protected diff | F 当前树静态、boundary 与 protected diff 实测 | **通过（静态/boundary 范围；原始树问题保留）** | lint 全过；25 files formatted；9 passed；UT-12 3 passed；新 clean shadow architecture passed；uv.lock diff=0；A-5/A-8/A-10/A-11。raw tree 仍仅因四个 ignored legacy roots exit 1，见 R-02，绝不称为 raw gate 绿色 | FR-6、G1 |

## 6. 回归范围

| 回归文件 | 实际结果 | 判定/边界 |
|---|---|---|
| `tests/test_runtime_engine.py` | 17 passed | 通过（F 当前树复跑） |
| `tests/test_extension_contracts.py` | 56 passed | 通过（F 当前树复跑，含既有 ContractModel/Extension 端口） |
| `tests/test_runtime_baseline.py` | 8 passed | 通过（F 当前树复跑，Phase 0 基线本地回归） |
| `tests/test_runtime_postgres.py` | **28 passed** | 通过（F 独立 Docker PG 最终复跑，原先 28 个环境 skip 已全部闭环） |
| `tests/test_open_platform.py` | **6 passed** | 通过（F 独立 Docker PG 最终复跑，原先 6 个环境 skip 已全部闭环） |
| 合计 | **115 passed, 0 skipped, 0 failed** | 81 非 PG + 34 Docker PG；非 PG 合并命令另得 81 passed 属重复确认，不累加；CM03 与 AC-8 本地回归准则通过 |
| `tests/test_core_boundaries.py` | 9 passed | 通过（F 当前树复跑） |
| 完整 `uv run pytest` | 未运行 | PENDING；按仓库约定由 CI 执行全量，不把选定回归合计伪称完整套件 |

没有生产路径接线或新增字段空态行为需要运行时切换验证；protected-path 零 diff 与上述 115 个回归共同支持本次本地兼容性结论。Agent 快照、模型 Profile、Memory 等仅在未运行的完整套件中间接覆盖，本报告不声称这些模块已单独执行。

## 7. 迭代中发现并修复的缺陷

D-01～D-06 来自 T2～T6 的历史实施/spec/quality review 与测试证据；D-07 来自最终总体 review 的 R6 覆盖遗漏，D-08 是 R11/05 文档澄清。**本次最终 T7 未重放历史 RED**，但 A-12 引用了独立保留的 R6 RED-first 原始证据；所有修复均存在于当前**未提交工作树**，本报告不编造 commit SHA。当前“回归”列只记录 F 实际绿色验证、文档一致性核对与对应位置；这不等于完整套件/CI 已通过。

| # | 级别 | 缺陷 | 发现环节 | 修复 | 当前回归 |
|---|---|---|---|---|---|
| D-01 | P1 | T2 安全异常仍可能显示隐式 traceback context；R9 静态只读 message 在 direct/nested mapping/JSON round-trip 边界不一致 | T2 实施/安全与序列化评审 | 未提交工作树：抑制隐式异常上下文；只接受精确静态 message 作为 no-op integrity token 并拒绝任意/不匹配 token | `test_safe_exceptions_suppress_implicit_context_in_formatted_tracebacks`、四个 direct/nested mapping/JSON round-trip 用例及 invalid-message 参数均在 457/560 中通过；A-1/A-4 |
| D-02 | P1 | T3 生命周期 introspection/wrong bound-signature arity 检查不安全或失真；R10 singleton、A→B→A、不可 weakref/死亡引用可能破坏 fresh-instance 保证 | T3 spec/quality review | 未提交工作树：安全绑定签名检查；基于 weakref 身份的存活实例拒绝与清理，不调用自定义相等比较 | `test_each_lifecycle_method_rejects_wrong_bound_arity`、inspection safe/control-flow、singleton、A→B→A、weakref/gc、`test_freshness_never_invokes_adapter_equality` 全过；A-1/A-4 |
| D-03 | P1 | T4 pending `anext` close 无法唤醒；claimed-empty/fully-delivered paused collection 可能悬挂；公共套件直接构造 gate，妨碍独立 Adapter 复用 | T4 spec review | 未提交工作树：close/终态唤醒与已完成收集修正；公共套件改为抽象 `make_gate` | `test_pending_anext_is_woken_by_aclose_without_external_cancel`、`test_claimed_empty_stream_does_not_block_successful_collection`、`test_delivered_only_event_does_not_require_an_extra_poll_before_result` 在两个 Adapter 全过；`test_reusable_suite_uses_abstract_gate_construction` 在 UT-12 三节点通过；A-2～A-5 |
| D-04 | P1 | T4 多 waiter close 未完整广播；caller-vs-runner cancellation 被混淆；scenario/runtime 路径可保留原始异常链；hostile deepcopy 未安全处理 | T4 quality review | 未提交工作树：广播与任务清理、调用方取消再传播、安全异常归一化；runtime gate 路径纳入同一安全边界 | `test_close_broadcasts_to_every_pending_anext_waiter`、cancel/aclose caller cancellation、deepcopy RuntimeError/BaseException、`test_runtime_origin_safe_error_does_not_retain_raw_exception_chain` 全过；A-2/A-4 |
| D-05 | P1 | T5 channel handoff 后取消 `anext` 会丢失 acknowledgement，导致 `collect_result`/`aclose` 死锁 | T5 对抗测试/quality review | 未提交工作树：handoff 项目使用 exactly-once suppression acknowledgement，成功与后续 stream failure 均清理 outstanding/channel | `test_cancelled_anext_after_channel_handoff_does_not_strand_item[successful-completion]` 与 `[following-stream-failure]` 在 probe 45×2 和 560 中通过；A-3/A-4 |
| D-06 | P3 | T6 临时 manifest 曾把第二 Adapter 结构证据误归入 UT-12 三节点，证据归因不清 | T6 evidence review | 未提交工作树之外的临时证据说明已纠正；UT-12 与 T5 结构日志分离，无 commit SHA 主张 | F 再次分别执行 UT-12 3 nodes 与 `test_probe_has_no_local_test_inheritance_import_or_delegation` 1 node，均通过；A-5/A-6 |
| D-07 | P1 | 最终总体 review 发现 R6“一个 no-arg factory 不得注册多个精确三元组”缺少覆盖；同一 factory 可跨 Engine/Protocol/version 三元组重复注册，破坏描述符与 factory 的一对一身份边界 | 2026-11-09 最终总体 review；先新增测试并取得 3 failed + 1 custom-equality control passed 的 RED 证据，再改实现 | `adapter_registry.py` 以 `is` 检查已注册 factory 身份并拒绝跨三元组复用，不使用自定义 `__eq__`；`test_agent_execution_registries.py` 增加三参数跨三元组拒绝和不同身份/custom-eq 相等控制 | F 显式四节点 4 passed、170 deselected；Registry 174、contracts+registries 457、四文件 560 全过；首三元组可解析、第二不可解析、无 partial registration，custom-eq 不决定身份；A-1/A-4/A-12 |
| D-08 | P3 | R11 前部分 owned-task 文档把“最终无 pending task”误写为“Adapter-owned task 集合最终为空”，未区分可保留的 completed 引用与执行前 empty-set；05 状态头也需与已形成的本地自动化证据一致 | 2026-11-09 最终文档 review | documentation-only：03/04/05/08 等澄清所有 owned tasks 已 await/done、completed 引用可保留并 `all(done)`、执行前 empty-set 独立；05 状态头改为本地自动化证据已形成但正式验收未完成；无生命周期代码变更 | F LocalTest 两轮均 58 passed 且 IT-11 预期/溯源已同步 R11；双语 06 一致性与 Python SHA 差量核对确认此项不引入额外 Python 改动；A-2/A-11 |

**开放缺陷结论**：在已审阅、本地可执行的实现范围内，D-01～D-07 均有当前通过回归，D-08 已完成 documentation-only 澄清并有当前行为/一致性核对，无已知开放实现 P0/P1。R-01～R-04 是 CI、环境或正式验收的下游事项，不抵销本地测试结论，也不构成人工批准。

## 8. 残留风险

| # | 级别 | 描述 | 处置（建议 owner / 下一份证据） |
|---|---|---|---|
| R-01 | P1 下游测试 | 完整本地套件和 GitHub Actions CI 均未执行，无 run URL；其他既有模块与前端/全量兼容性未由本次选定测试证明 | **Owner：后续提交/PR 与 CI 维护者**。在后续合法提交流程中取得全量 CI 结果及 run URL，并补充必要回归；本报告不启动提交、push 或 PR |
| R-02 | P2 本地环境 | raw `check_architecture.py` 仍 exit 1，仅报告 `modules/apps/integrations/platform` 四个预先存在且被 ignore 的 legacy roots；clean-source identical shadow gate 通过。raw 命令不能写成绿色，也不能为求绿删除这些 ignored artifacts | **Owner：仓库/架构门禁维护者**。以干净 checkout 或 CI 原始日志复核；保留 raw exit 1 与 clean-shadow pass 两份证据，再决定本地 ignored artifacts 的无损清理策略 |
| R-03 | P1 验收入口 | Phase 0 正式验收入口风险仍开放；Phase 1 的实现与测试工作不构成 Phase 0 批准 | **Owner：Phase 0 验收负责人**。提供正式验收记录/签署证据并确认入口后再推进 Phase 1 正式验收；Phase 1 本地测试出口已满足不等于此前阶段获批准 |
| R-04 | P1 正式验收 | 双语 `07-acceptance-report.md` / `07-acceptance-report.en.md` 已形成，记录本地自动化 A1～A8 与 C1～C4 工程证据；但正式人工验收、Adapter 代表 UAT、各角色签字及最终总体包评审仍未批准/未完成。本地 29/29 与 07 的存在不自动转化为业务/正式验收通过 | **Owner：Phase 1 验收负责人与最终包评审负责人**。以 07 为输入完成最终总体包评审、人工 UAT、正式验收和签字，并保留独立证据；T7 不代行该职责 |

## 9. CI 证据

- PR：**未创建（T7 明确不执行 commit/push/PR）**。
- CI run：**PENDING；未执行，无 URL、无 head SHA、无 conclusion=success 主张**。
- 本地完整 `uv run pytest`：**PENDING；未执行**。
- 本地结论：F 当前树 focused/static 实测、T6 历史 artifacts 与独立 Docker PostgreSQL 最终复跑共同覆盖全部 29 个 P1-UT/IT/CM，AC-1～8 的本地测试证据均可复现通过，受影响选定去重回归 115 passed、0 skipped；`04-test-plan.md` §7 的本地批准范围与出口证据**已满足**。
- 下游边界：完整套件、Frontend/Backend CI job 未验证；双语 07 已形成本地自动化工程证据，但最终总体包评审、正式 Phase 1 人工验收、UAT 与签字未完成。本报告不声称 CI 成功、Phase 0 入口已批准、最终总体包已获批准或 Phase 1 已正式接受。

## 附录 A 本地执行输出快照（执行覆盖 2026-11-08～2026-11-09；F 为 2026-11-09）

除特别注明外，pytest 命令工作目录为 `backend/`；所有 F focused 命令 exit code 均为 0。

### A-1 contracts + registries（457）

```bash
uv run pytest -q tests/test_agent_execution_contracts.py tests/test_agent_execution_registries.py
```

```text
457 passed in 0.28s
```

`--collect-only` 独立确认 contracts 为 283、registries 为 174，总计 457；没有 skip。

### A-2 LocalTestAdapter 连续两轮（58 + 58）

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

两轮均为完整文件、0 skipped。`--collect-only` 精确收集 58 项：公共类 37 项，加 LocalTest 顶层 invalid scenario 9 参数与 12 个其他专属/对抗/静态节点，共 58。

### A-3 ContractProbe 连续两轮（45 + 45）

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

两轮均为完整文件、0 skipped。精确构成为 25 个继承公共方法展开 37 cases，加 6 个单节点 focused 用例与 cancelled-handoff 的 2 个参数，共 45；cancelled-handoff 回归已包含在内。

### A-4 四文件 focused 合并（560）

```bash
uv run pytest -q tests/test_agent_execution_contracts.py tests/test_agent_execution_registries.py tests/test_local_test_adapter.py tests/test_agent_execution_contract_probe.py
```

```text
560 passed in 0.42s
```

283 + 174 + 58 + 45 = 560，0 skipped、0 failed。

### A-5 显式 UT-12 三节点（3）

```bash
uv run pytest -q \
  tests/test_local_test_adapter.py::test_reusable_suite_has_no_concrete_adapter_import \
  tests/test_local_test_adapter.py::test_reusable_suite_uses_abstract_gate_construction \
  tests/test_local_test_adapter.py::test_cumulative_t2_t3_t4_modules_and_dependency_direction_are_exact
```

```text
3 passed in 0.07s
```

三节点共同验证公共套件无具体 Adapter import、抽象 gate 构造，以及 T2+T3+T4 精确 18 模块集合/存在性、依赖方向、no-eager-test-import、`ExecutionContractModel` 直接继承 `ContractModel`。它们不验证第二 Adapter 结构。

### A-6 独立 T5 结构节点（1）

```bash
uv run pytest -q tests/test_agent_execution_contract_probe.py::test_probe_has_no_local_test_inheritance_import_or_delegation
```

```text
1 passed in 0.05s
```

此节点独立验证 ContractProbe 无 LocalTest 继承、import 或 delegation，不属于 A-5 三节点。

### A-7 CM01/CM02 当前只读 spot checks

```bash
uv run alembic heads
# 0057_industry_pack_runtime (head)

git diff --exit-code 4dfcfb41e9cbb799753986c2d76134514bbd19be -- <04/T6 protected paths>
# 无输出，exit 0
```

F `protected-paths.log` 为空、exit 0；migration、uv.lock、Worker/Factory/composition、Settings、env examples、frontend/deploy 均保持零 diff。`source-test-sha256-delta.log` 不再为空：25 项中仅 `adapter_registry.py` 与 `test_agent_execution_registries.py` 两个预期 R6 Python 文件改变，其余 23 项不变；文档/报告差量单列，不用旧库存“零差异”替代当前证据。

### A-8 F 当前树静态质量证据

```text
uv run ruff check src tests
All checks passed!

uv run ruff format --check <25 个 Phase 1 文件>
25 files already formatted

uv run pytest -q tests/test_core_boundaries.py
9 passed in 0.59s
```

### A-9 既有回归、独立 Docker 迁移与 34 个 PG 最终复跑

F 当前树非 PG 原始结果：

```text
runtime_engine:       17 passed in 0.46s
extension_contracts:  56 passed in 0.81s
runtime_baseline:      8 passed in 0.31s
非 PG 去重小计:       81 passed, 0 skipped, 0 failed
非 PG 合并重复确认:   81 passed in 0.95s（不与分文件结果累加）
```

T6 初次合并命令曾产生 `81 passed, 34 skipped in 1.44s`；当时 28 个 runtime_postgres 与 6 个 open_platform 节点因缺少专用已迁移 PG 而未执行，未被记为通过。`gate5-postgres-skipped-node-collection.log` 保存了这 34 个精确节点，作为后续补跑的同一集合依据。

用户授权后的独立环境为 `nexusdesk-phase1-pg-838b99d6`（`pgvector/pgvector:pg17`），使用专用空数据库/卷和 loopback 动态端口；既有 `nexusdesk-phase0-postgres` 未复用或修改。凭据仅保存在权限 0600 的临时 env 文件中，以下命令以安全 source 方式注入但不显示其内容。

```bash
set -a; . /tmp/nexusdesk-phase1-pg-4ph_1qsi/test.env; set +a
uv run --directory backend alembic upgrade head
# 初始 RESULTS.txt 记录 exit 0；heads = 0057_industry_pack_runtime (head)

uv run --directory backend pytest -q tests/test_runtime_postgres.py tests/test_open_platform.py
uv run --directory backend alembic current
```

初始 corrected rerun 已取得 `34 passed in 14.06s`，关闭原 34 个环境 skip；F 于 2026-11-09 在**同一批 34 个节点**再次实跑，原始输出与 post-test migration 状态为：

```text
..................................                                       [100%]
34 passed in 14.10s

post-test alembic current:
0057_industry_pack_runtime (head)
```

F `postgres-regression-final.exit` 为 0，结果为 **28 + 6 = 34 passed，0 skipped，0 failed**；它是初始 34 项闭环后的当前树复跑，不把两轮累加为 68 个独立用例。首次历史 wrapper 调用因 zsh 只读 `status` 变量造成记账错误，退出码不可靠，**不作为正式证据**；初始正式证据只引用使用 `rc` 捕获 exit 0 的 corrected rerun，本次正式证据则引用 F 的独立三件套。报告不包含密码、URL 或 env 文件内容。容器留给独立 review 复跑，后续由 controller 清理；嵌入输出保证清理后仍可审计。

### A-10 架构 raw 与 clean-source shadow

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

四个 roots 均由 F `legacy-roots-ignored-status.log` 证明为 ignored，tracked/unignored 文件清单为空；没有新增架构失败。raw exit 1 与 clean shadow exit 0 均来自 F 当前树，保留在 R-02，未粉饰。

### A-11 证据清单与范围

F 为本报告引用的每条主命令保留同名 `.command`、`.log`、`.exit` 三件套，包括八条原 T7 focused pytest、R6 四节点、四条 collect、lint/format/core boundaries、非 PG 分文件与合并回归、Alembic heads/current、protected paths、raw/clean architecture 与 34 个 PG 最终复跑；关键 collect logs 为 `collect-contracts.log`、`collect-registries.log`、`collect-localtest.log`、`collect-probe.log`。SHA diff、最终双语/范围检查等辅助证据按实际文件保留，不宣称辅助项都有三件套；一次不适用的 `check-ignore` 辅助尝试也保留为 `legacy-roots-check-ignore-attempt.*`，正式 ignored-root 证据使用 `git status --short --ignored`。T6 `MANIFEST.txt` 仅作历史门禁和初始 `81 passed, 34 skipped` 对照，R6 根目录独立保存 RED/fix/format 原始证据。临时日志未版本化且可能 ephemeral；本附录的计数、命令和关键输出是报告内的持久审计摘要。

### A-12 R6 同工厂跨三元组 RED-first 与最终修复证据

最终总体 review 发现原测试未覆盖 R6 的“一个 no-arg factory 只能属于一个精确三元组”规则。独立修复证据根 `/tmp/nexusdesk-phase1-r6-fix-evidence` 保留了先测试后实现的时序；**F 未重放该历史 RED**。在实现修复前，`r6-red.command/.log/.exit` 的实际结果为 exit 1：

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

三个 RED 均为第二三元组注册未抛 `ConfigurationError`；通过的 control 是两个身份不同但自定义 `__eq__` 判定相等的 factory 不应被误拒。实现随后用 `is` 对既有 factory 做身份比较，拒绝同一 factory 跨 Engine/Protocol/version 三元组复用，不采用 `__eq__` 或 bare `id()`。测试逐参数断言第二注册为 `duplicate_adapter`、factory 注册阶段未执行、第一三元组仍能解析且只构造一个实例、第二三元组按既定优先级不可解析、没有 partial registration；custom-equality control 分别解析 v1/v2。

R6 `r6-new-post-fix.log` 为 `4 passed, 170 deselected in 0.06s`，`r6-registries-post-fix.log` 为 `174 passed in 0.16s`，`r6-four-focused-final.log` 为 `560 passed in 0.45s`。F 又在当前树独立执行同一四节点选择：

```text
4 passed, 170 deselected in 0.05s
457 passed in 0.28s   # contracts + registries
560 passed in 0.42s   # four-file
```

这些是通过子集与合并套件的重复确认，不增加 560 个去重 focused cases。R6 初次 `r6-ruff-format-check-initial.log/.exit` 保留 exit 1 与 `1 file would be reformatted, 1 file already formatted` 的中间事实；格式修正后的 `r6-ruff-format-check.log/.exit` 为 exit 0、`2 files already formatted`。F 最终另行执行全仓 `ruff check src tests`（All checks passed）及 25 个 Phase 1 文件 format check（25 files already formatted），均为 exit 0；中间 format 失败未被最终成功覆盖或删除。
