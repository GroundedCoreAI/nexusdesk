# Phase 0 基线 · AgentConfig 配置兼容矩阵

> 状态：现状兼容证据与修正后本地正式 Run 1/Run 2 的 310 节点全过、两轮 XPASS 审计成功结果已登记（见 `regression-baseline.md` §6）；干净 CI、真实授权样本、最终提交证据与验收签字仍待各自证据
> 创建日期：2026-11-08
> 依据：`02-requirements.md`（FR-3、AC-3）、`04-test-plan.md`（P0-UT-05～07、P0-IT-08）、`manifest.v1.json` 与现状测试
> 现状目标提交：`c6c47dec39025ebd4d1176c1e9925bac9c99c4fd`
> 当前产物树：未提交的特性分支工作树；不赋予虚构产物 SHA，也不与现状目标提交混称

## 1. 范围与证据边界

- fixture 根目录为 `backend/tests/fixtures/agent_execution_baseline/`。目录共 **7 个文件**：`manifest.v1.json` 加 **6 个 payload 文件**；payload 展开为 **5 个合法用例**和 **16 个非法用例**。
- 所有值均为合成值。仓库历史来源只说明**字段形状**，不表示捕获过生产或客户内容；不得把这些 fixture 称为真实历史样本。
- 真实生产发布快照的代表性仍为 `pending_env`，由 Agent 配置 owner 与安全 owner 补充经授权样本或形成正式范围裁定。
- 本文冻结目标提交的现状行为及当前未提交产物树的测试证据，不发明未来 Engine 映射。未知 `engine` 字段因 `AgentConfig` 的 `extra=forbid` 被拒绝，不表示已设计或批准任何 Engine 配置合同。
- 下述聚焦测试和既有非正式预检均不替代 25 套件正式双跑、干净 CI、真实样本评审或验收签字；正式状态见 `regression-baseline.md`。

## 2. 文件清单与来源

| 文件 | payload 类型 | 用例数 | 来源类别与已核实边界 |
|---|---|---:|---|
| `manifest.v1.json` | 清单，不直接校验 | — | 固定 `fixture_version=v1`、目标 SHA、文件集合、合成值政策、预期结果和精确错误位置 |
| `minimal-defaults.v1.json` | 单个 AgentConfig | 1 合法 | 按目标提交当前 AgentConfig 构造的最小合成输入，验证当前默认值 |
| `legacy-core-shape.v1.json` | 单个 AgentConfig | 1 合法 | 字段集由历史提交 `7dce7ba473622b209329ccd058b42b74b5538bdc` 的 `backend/src/agent_platform/modules/agent_config/service.py` 核实；值全为合成值 |
| `legacy-memory-shape.v1.json` | 单个 AgentConfig | 1 合法 | 字段集由历史提交 `7250aa0e83a48b7b43340b8fa0db4666eb83e7b7` 的同一路径核实；值全为合成值 |
| `valid-boundaries.v1.json` | `cases` 集合 | 2 合法 | 按当前约束构造的数值、集合与运行时截断边界合成输入 |
| `unknown-engine-field.v1.json` | 单个 AgentConfig | 1 非法 | 在当前合法合成配置上增加不支持的 `engine` 对象 |
| `invalid-cases.v1.json` | `cases` 集合 | 15 非法 | 按当前枚举、类型、范围和模型绑定约束构造的合成非法输入 |

清单完整性及合法输入由 `test_runtime_baseline_fixtures.py::test_fixture_manifest_covers_exact_files_and_all_valid_configs` 验证；非法输入的精确位置由同文件 `test_invalid_fixtures_declare_exact_pydantic_error_locations` 验证。

## 3. 合法输入兼容矩阵

| 文件 / 用例 ID | 覆盖重点 | 当前预期与断言 |
|---|---|---|
| `minimal-defaults.v1.json` | 仅提供必填 `system_prompt` | 校验成功；下表所有当前默认值与 `AgentConfig.model_dump(mode="json")` 一致 |
| `legacy-core-shape.v1.json` | 初始核心字段形状；新增 memory 字段缺省读取 | 校验成功；发布集成输入保留核心键；不是生产内容样本 |
| `legacy-memory-shape.v1.json` | 早期 memory 开关字段形状；后续字段缺省读取 | 校验成功；发布集成输入保留 `tool_names` 等键；不是生产内容样本 |
| `valid-boundaries.v1.json` / `lower-numeric-boundaries` | 最短 prompt、数值下界、单元素集合 | 校验成功 |
| `valid-boundaries.v1.json` / `upper-numeric-and-collection-boundaries` | `max_model_rounds=30`、30 个工具、30 个 KB、memory 限制值 999 | 校验成功；高于平台运行时 memory 上限的值可由运行时截断，不把模型校验成功等同于实际注入数量 |

`minimal-defaults.v1.json` 冻结的当前默认值：

| 字段 | 默认值 | 字段 | 默认值 |
|---|---|---|---|
| `tool_names` | `[]` | `knowledge_base_ids` | `[]` |
| `max_model_rounds` | `6` | `model_profile_id` | `null` |
| `model_profile_version` | `null` | `reply_language` | `"auto"` |
| `summary_enabled` | `true` | `memory_enabled` | `true` |
| `memory_write` | `true` | `memory_read_enabled` | `true` |
| `memory_types` | `["profile","preference","event"]` | `memory_search_enabled` | `true` |
| `memory_write_mode` | `"auto"` | `memory_inject_max_items` | `null` |
| `memory_search_limit` | `null` | `memory_blacklist_auto_handoff` | `false` |

## 4. 非法输入与精确 Pydantic 位置

下表原样记录 manifest 的 `expected_error_locations`。每个内层数组是一个 Pydantic `loc`；`[]` 明确表示**根模型校验错误**，不是“缺少断言”。集合元素错误保留整数下标，例如 `["memory_types",0]`。测试对规范化后的完整位置集合做相等比较，而非只检查字段名。

| 文件 / 用例 ID | 非法构造 | 精确 `expected_error_locations` |
|---|---|---|
| `unknown-engine-field.v1.json` | 未声明的 `engine` 对象；`extra=forbid` | `[["engine"]]` |
| `invalid-cases.v1.json` / `empty-system-prompt` | 空 prompt | `[["system_prompt"]]` |
| `invalid-cases.v1.json` / `tool-names-wrong-type` | 工具集合传入字符串 | `[["tool_names"]]` |
| `invalid-cases.v1.json` / `model-rounds-wrong-type` | 轮次传入非数值字符串 | `[["max_model_rounds"]]` |
| `invalid-cases.v1.json` / `model-rounds-below-lower-bound` | `max_model_rounds=0` | `[["max_model_rounds"]]` |
| `invalid-cases.v1.json` / `model-rounds-above-upper-bound` | `max_model_rounds=31` | `[["max_model_rounds"]]` |
| `invalid-cases.v1.json` / `model-profile-version-below-lower-bound` | `model_profile_version=0` | `[["model_profile_version"]]` |
| `invalid-cases.v1.json` / `model-profile-binding-is-incomplete` | 只有 profile ID、缺少 version；关联字段为 `model_profile_id` 与 `model_profile_version` | `[[]]` |
| `invalid-cases.v1.json` / `invalid-reply-language-enum` | 不支持的回复语言 | `[["reply_language"]]` |
| `invalid-cases.v1.json` / `invalid-memory-type-enum` | 集合第 0 项为不支持的 memory 类型 | `[["memory_types",0]]` |
| `invalid-cases.v1.json` / `empty-memory-types` | 空 memory 类型集合 | `[["memory_types"]]` |
| `invalid-cases.v1.json` / `invalid-memory-write-mode-enum` | 不支持的写入模式 | `[["memory_write_mode"]]` |
| `invalid-cases.v1.json` / `memory-inject-limit-below-lower-bound` | 注入上限为 0 | `[["memory_inject_max_items"]]` |
| `invalid-cases.v1.json` / `memory-search-limit-below-lower-bound` | 检索上限为 0 | `[["memory_search_limit"]]` |
| `invalid-cases.v1.json` / `invalid-knowledge-base-uuid` | KB 集合第 0 项不是 UUID | `[["knowledge_base_ids",0]]` |
| `invalid-cases.v1.json` / `summary-enabled-wrong-type` | 布尔开关传入数组 | `[["summary_enabled"]]` |

合计为 1 个独立非法文件用例加 15 个集合用例，即 **16 个非法用例**；合法集合 2 例加 3 个独立合法文件，即 **5 个合法用例**。

## 5. 可复现聚焦命令

在仓库根目录执行。静态/fixture 检查不需要 PostgreSQL，也不需要设置 `TEST_DATABASE_URL`：

```bash
uv run --directory backend pytest \
  tests/test_runtime_baseline_fixtures.py \
  tests/test_agent_config_execution_compat.py::test_p0_ut_08_frozen_identities_terminology_and_worker_neutrality \
  -rA --durations=0 \
  --junitxml=/tmp/nexusdesk-phase0-config-static.xml
```

PostgreSQL 聚焦复现使用独立、已迁移的测试库。环境文件仅保存在本机且不得提交；这里只引用变量名，不显示 URL 或凭据。加载前先清除继承的数据库变量；文件缺失/不可读或 `source` 失败时必须退出，不能回落到继承值或默认数据库。迁移失败同样停止后续测试：

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

可用以下只读命令复核两个历史字段形状来源；它们不读取生产数据：

```bash
git show 7dce7ba473622b209329ccd058b42b74b5538bdc:backend/src/agent_platform/modules/agent_config/service.py
git show 7250aa0e83a48b7b43340b8fa0db4666eb83e7b7:backend/src/agent_platform/modules/agent_config/service.py
```

这些是聚焦复现命令，不是正式 25 套件双跑命令；后者及产物命名、覆盖率与节点比较规则见 `regression-baseline.md`。

## 6. 真实 PostgreSQL 发布、快照与执行边界

以下均为 `backend/tests/test_agent_config_execution_compat.py` 对真实 PostgreSQL 的现状断言；模型绑定使用测试内真实 demo profile，不调用真实外部模型。

| 测试节点 | 已固定的现状行为 | 证据边界 |
|---|---|---|
| `test_p0_it_08_legacy_raw_draft_publishes_normalized_v1` | 两个 legacy raw draft fixture 均深拷贝后使用；仅在内存中替换为真实 demo profile 绑定，并清空 tool/KB 列表；绑定 SQL 用 `CAST(:draft AS jsonb)` 模拟 raw JSONB draft。真实发布 API 后 raw draft 与源 fixture 字节不变；存储 v1 与 `AgentConfig.model_validate(legacy).model_dump(mode="json")` 完全一致，含全部当前默认字段；显式 `snapshot(version=1)` 返回存储 v1 | 证明合成字段形状的公开链路，不证明真实生产样本代表性 |
| `test_later_draft_and_v2_do_not_rewrite_v1_or_cross_tenant_boundary` | 后续 draft/v2 不改写存储或显式读取的 v1；不带版本的 latest snapshot 为 v2。跨租户 `versions()` 当前抛 `DomainError(code="not_found", status=404)`，而 `snapshot()` 抛 `DomainError(code="agent_not_found", status=404)` | 两个错误码是当前实际差异，必须分别保留，不在文档中统一 |
| `test_queued_run_keeps_v1_snapshot_after_v2_is_published` | v1 时提交且仍为 queued 的 Run，在 v2 发布后保留完整 Agent v1 快照 | 测试不执行模型，只验证排队 Run 的持久快照 |
| `test_sparse_raw_version_exposes_direct_snapshot_tool_names_limitation` | 手工插入的极稀疏 raw version 虽是合法 `AgentConfig` 输入，直接 `snapshot()` 当前抛 `KeyError("tool_names")` | 这是**存储阶段限制**；不证明公开 publish 会创建此行，也不证明所有合法配置均可直接执行。按 P2/open 单独跟踪，不能与真实历史合法样本失败的 P1 分级混同 |

这些 PostgreSQL 行为已包含在 `regression-baseline.md` §6 记录的当前本地正式 Run 1/Run 2 结果中：两轮各 310 个节点全部 passed，逐轮及比较门禁重新执行的非 strict XPASS 日志审计均 exit 0、`summary_entries=310`、`xpass_count=0`。干净 CI、真实授权样本、最终提交证据与验收签字仍待补齐。稀疏 raw-version 项在 `refactoring-checklist.md` 的 P0-I7 跟踪，须在 Phase 3 配置映射前解决或形成正式裁定并补回归。
