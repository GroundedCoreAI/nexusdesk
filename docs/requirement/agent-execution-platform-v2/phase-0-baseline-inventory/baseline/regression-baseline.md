# Phase 0 基线 · 回归环境、结果与复现命令

> 状态：修正后的本地正式双跑已通过 310 节点比较与两轮 XPASS 日志审计；干净 CI、真实样本、最终提交证据与验收仍未预先判通过
> 现状目标提交：`c6c47dec39025ebd4d1176c1e9925bac9c99c4fd`
> 基线产物：正式被测特性分支**未提交工作树**；以 base 元数据与确定性 tree hash 标识，不赋予虚构产物 SHA，最终 committed-artifact 证据保持 `pending_commit`
> 初次记录：2026-11-07；T8 扩充：2026-11-08；T9 正式结果及修正后双跑回填：2026-11-08
> 依据：`02-requirements.md`（FR-1～FR-6、AC-1～AC-6）与 `04-test-plan.md`
> 证据目录：本机 `/tmp/nexusdesk-phase0-*`（不提交秘密、数据库连接串或大型临时日志）

## 1. 环境指纹

| 项 | 已核实值 |
|---|---|
| 分支 | `feat/agent-execution-platform-v2-phase0` |
| Python | 3.11.9 |
| uv | 0.11.3 (`45da18ac3`) |
| 容器镜像 | `pgvector/pgvector:pg17` |
| PostgreSQL | 17.11 (Debian 17.11-1.pgdg12+2) |
| 数据库隔离 | 专用 Phase 0 容器和数据库；正式两轮各用独立空库并迁移至 head |
| 迁移 head | `0057_industry_pack_runtime` |
| 正式库准备与使用 | Run 1、Run 2 各用一个本地独立空库，均已在各自测试前迁移并核实到 `0057_industry_pack_runtime` 后实际用于正式测试 |
| 外部模型 | 不进入确定性必过路径 |
| 连接信息 | 仅存于权限受限的本机环境文件；命令只引用变量名，不记录其值 |

完整依赖锁见 `backend/uv.lock`。`pytest-cov` 仅属于 dev group，不作为生产运行依赖。本地库名属于非秘密标识，但本文无需记录；任何 URL、用户名或密码均不进入文档、日志摘要或命令输出。

## 2. 现有目标提交校准结果

以下发生在新增 Phase 0 测试/工具之前，只用于建立现有行为与环境校准证据。

| 轮次/检查 | 实际命令或范围 | 结果 | 判定 |
|---|---|---|---|
| 空库环境校准 | 现有 `test_runtime_engine.py`、`test_runtime_postgres.py`、`test_runtime_availability.py`、`test_runtime_scope.py` | 21 passed、10 failed、10 errors，7.22s | 未迁移空库导致 `runtime_runs` 不存在；**不计正式双跑**，原始日志保留为 `/tmp/nexusdesk-phase0-existing-run0.log` |
| Alembic 校准 | 仅设置 `TEST_DATABASE_URL` | 连接默认 `127.0.0.1:5432` 失败 | 证实 Alembic 经 Settings 读取 `AGENT_DATABASE_URL`；不记录连接串 |
| 修正迁移环境 | 对专用空库设置 `AGENT_DATABASE_URL` 后 `alembic upgrade head` | 迁移成功 | 测试另设 `TEST_DATABASE_URL` 为同一专用库 |
| 现有 Runtime 基线 | 同一四个现有套件，已迁移数据库 | **31 passed in 4.95s** | `/tmp/nexusdesk-phase0-existing-run1.log` 及对应 JUnit XML |
| Ruff lint | `uv run --directory backend ruff check src tests` | 通过 | 目标现状代码 |
| Ruff format | `uv run --directory backend ruff format --check src` | 既有 `seed_memory_*` 等文件不满足格式检查 | 登记 P3，不在 Phase 0 批量格式化无关生产脚本 |
| 架构门禁 | 目标提交的干净临时 worktree 执行根目录 `scripts/check_architecture.py` | 通过 | 当前工作目录的忽略旧目录/`__pycache__` 会误报，不删除用户文件 |

## 3. 当前产物树的非正式证据

以下均为正式双跑前的聚焦预检、工具验证或范围演练。它们证明相应命令/测试曾产生所述结果，**不构成同一 25 套件、同一树、两个独立空库的正式双跑**，也不构成 CI 或验收证据。

| 检查 | 实际结果 | 产物与边界 |
|---|---|---|
| 早期合并预检（不含 T6） | 23 suites，**261 passed in 84.78s** | 与聚焦运行及其他预检重叠；不能与下列计数相加为唯一节点数 |
| 加入 T6 的合并预检 | 24 suites，**267 passed in 87.32s** | 与聚焦运行及上一轮范围重叠；不是唯一节点增量，也不是正式 25 套件运行 |
| 旧 24 套件清单的全产物演练 | JUnit `tests=267, failures=0, errors=0, skipped=0, time=126.343s`；coverage JSON `9799 / 18534 = 52.87%` | `/tmp/nexusdesk-phase0-preflight.log`、`.xml`、`.summary.json`、`.coverage.json`；旧清单不含新加入的 memory-injection 套件，排除出正式结果 |
| 演练产物自比较 | self-compare JSON 为 `identical=true`，无节点差异 | 同一文件与自身比较只验证比较工具路径，**不是要求的两轮基线** |
| 演练包装器缺陷 | pytest 进程已完成并生成完整上述产物，随后 zsh 包装器以 `read-only variable: status` 失败 | 如实保留缺陷；该包装器不是成功的正式命令。下文正式模板改用 `test_rc` 并保留 pytest 实际退出码 |
| T7 与新增 memory-injection 聚焦运行 | **46 passed in 16.43s**，pytest exit 0 | `/tmp/nexusdesk-phase0-t7-memory.log` 与 `/tmp/nexusdesk-phase0-t7-memory.xml`；合并 28 个 Runtime PostgreSQL 测试和 18 个 memory-injection 测试，只是范围证据，不是正式 25 套件运行 |
| T7 独立评审 | 直接 worker 执行增加独立 5 秒外层超时后，独立 spec 与 quality 评审通过 | 评审结论不是正式运行产物，不替代原始日志、JUnit、双跑或验收 |

早期 873/18534（4.71%）覆盖率仅是一次工具 smoke，不是正式覆盖率基线，本文不以其代表当前产物覆盖率。

## 4. 正式 25 套件有序范围

两轮必须使用下列**完全相同的顺序和测试清单**。不得一轮增删套件、改名或仅补跑差异后宣称等价。

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

范围包含 Runtime 核心与 PostgreSQL/SSE/replay、基线汇总/比较工具、fixture、AgentConfig 兼容、Agent/API/语言/模型约束、memory 配置/客户/PostgreSQL/注入，以及 model/tool gateway、egress、credential 和 workspace 回归。后续阶段仍按变更相关性选取套件，不要求每次无关改动机械执行全部套件；正式 Phase 0 双跑则不得缩减此清单。

## 5. 正式双跑可复现命令模板

**§6 当前 310 节点 Run 1、Run 2 已使用修复后的模板完成，两轮审计与比较门禁均成功；旧 303 节点结果仅作为被取代历史另列。以下模板继续作为后续正式复现必须原样使用的命令。** 在仓库根目录对 Run 1、Run 2 分别启动独立 shell，并将 `run_id` 设为 `run1` 或 `run2`。每轮使用各自的环境文件和独立空库；两个文件均放在仓库外，含各自的 `TEST_DATABASE_URL`，权限仅当前用户可读写。不要复用校准库、预检库或另一轮的库，不要在终端打印环境文件。加载前清除继承变量；文件缺失/不可读、加载失败或缺少 `TEST_DATABASE_URL` 均必须在 Alembic/pytest 前失败，不得使用默认值。

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

两轮原始日志、JUnit、summary、`xpass-audit.json`、coverage、base/tree/metadata 文件均按 `run1`/`run2` 分离并放在仓库外。`base_commit` 只记录 `git rev-parse HEAD` 的基线元数据，**不是未提交工作树 SHA**。实际产物身份由 tree hash 给出：对 `git ls-files -co --exclude-standard -z` 的原始路径字节排序，逐项以 8 字节大端路径长度、原始路径、8 字节大端数据长度和文件字节更新 SHA-256；符号链接哈希其目标字节。输出为 `sha256=... files=...`，忽略文件（包括 ignored env 文件）不读取。

`pytest_start_utc`/`pytest_end_utc` 紧贴 pytest 前后采集，真实退出码首先存入 `test_rc`，summary/audit/identity 失败不得覆盖它。每轮必须比较 tree-before/tree-after；两轮还必须比较 tree-before 和 base-commit。若任一轮内树发生变化、两轮树hash/文件数不同或 base 不同，不得接受节点比较，须裁定并重跑同一产物树。只有以下身份门禁与两轮日志审计全部成功才执行节点比较；比较门禁会重新执行审计并覆盖为同样的确定性 JSON，审计无法运行（exit 2）或发现 XPASS（exit 1）都立即阻断：

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

XPASS 证据分为两层，不能互相替代。JUnit `summary` 负责把 pytest 的 strict XPASS 表示分类为 `xpass`：包括 `<failure message="[XPASS(strict)] …">`，以及兼容 `<skipped message="xfail-marked test passes unexpectedly">`；普通 `<failure>` 仍是 `failed`。但 non-strict XPASS 在 JUnit 中只是没有标记的普通 passed testcase，**仅凭 JUnit 无法证明零 XPASS**。因此每轮必须保留 pytest `-rA` 原始日志并执行 `audit-log`。该命令要求恰有一个 short test summary、至少一条测试状态记录和完整终端汇总，输出确定性的 `summary_entries`、`xpass`、`xpass_count` JSON；exit 0 表示没有 XPASS 行且至少有 `PASSED` 记录证明使用了包含通过项的 `-rA` 全量状态输出，exit 1 表示发现 non-strict XPASS，exit 2 表示日志缺失、非 UTF-8、证据结构不完整或干净结论缺少 `PASSED` 证据。它只审计 short summary 的 `XPASS` 状态行，不声称从 JUnit 或任意文本通用检测 XPASS；strict XPASS 的 pytest 非零 `test_rc` 仍须独立通过。

比较器以每个 JUnit testcase 的精确 **`(classname,name)`** 为节点身份：新增/缺失节点、`passed/failed/error/skipped/xfail/xpass` outcome 变化以及 skip/xfail/xpass 原因变化都属于差异；耗时保留用于观察，但不参与等价判断。`identical=true` 仅表示这些节点字段一致，不抹平失败，也不表示业务验收通过。比较器退出 0 表示无上述差异、1 表示有节点差异、2 表示输入错误；不得把退出码强制改成成功。任何失败、skip 或差异都须保留原因并裁定，不能靠删除节点、改测试名或只比较总数隐藏。实际报告需记录每轮 UTC 起止、base/tree/metadata 文件、真实退出码、summary/audit 退出码和身份比较结果。

## 6. 正式双跑与覆盖率

修正后的本地正式双跑已完成并逐项复核。两轮均实际使用各自迁移到 `0057_industry_pack_runtime` 的独立空库，严格执行 §4 的同一有序 25 套件和 §5 的修正后模板；每轮 pytest、summary、日志审计、树身份和包装器均成功，比较门禁在重新审计两轮日志后才执行节点比较。完整逐用例溯源见 `../06-test-report.md`。

| 项 | Run 1 | Run 2 | 比较/说明 |
|---|---|---|---|
| 产物标识 | base `c6c47dec39025ebd4d1176c1e9925bac9c99c4fd`；tree `sha256=f7d3ae857427b5d0173c080f4e6678755f4562730629d3155c2b7d2c44c0d2b1 files=1018` | 同左 | base 只是元数据，不是未提交树 SHA；`run1_within/run2_within/cross_run_tree/cross_run_base` 全为 `true`，两轮间无仓库文件变化 |
| UTC 起止 | 2026-11-07T21:37:50Z ～ 2026-11-07T21:40:16Z | 2026-11-07T21:41:09Z ～ 2026-11-07T21:43:36Z | 原始日志与 run-specific metadata 已保存 |
| tests/failures/errors/skipped | 310 / 0 / 0 / 0 | 310 / 0 / 0 / 0 | 两轮 JUnit 均含 310 个唯一节点，全部 passed |
| JUnit xfail/xpass | 0 / 0 | 0 / 0 | 全部 310 个节点均为 passed，无 skip/xfail/xpass 原因；non-strict XPASS 另由日志审计判定 |
| `-rA` 日志审计 | exit 0；`summary_entries=310`、`xpass=[]`、`xpass_count=0` | exit 0；`summary_entries=310`、`xpass=[]`、`xpass_count=0` | 每轮正式审计和比较门禁重新审计均成功 |
| 耗时 | 145.281s | 145.353s | 仅作观察，不参与等价判定，数值波动不自动判 flaky |
| 覆盖率 | 9886/18534 = 53.339807920578394%（53.34%） | 9900/18534 = 53.4153447717708%（53.42%） | 各自 coverage JSON 实际总量；不宣称逐行等价 |
| pytest/summary/audit 退出码 | 0 / 0 / 0 | 0 / 0 / 0 | 分别记录，包装器状态未覆盖 pytest 状态 |
| tree-after/轮内 cmp/wrapper 退出码 | 0 / 0 / 0 | 0 / 0 / 0 | 每轮 before/after 身份一致，包装器成功 |
| 节点比较 | — | — | 比较门禁重新审计成功后 compare exit 0；`/tmp/nexusdesk-phase0-compare.json`：`identical=true`；`added=[]`、`missing=[]`、`outcome_changes=[]`、`skip_reason_changes=[]` |

每轮均保存 `.log`、`.xml`、`.summary.json`、`.xpass-audit.json`、`.coverage.json`、`.coverage`、`.base-commit.txt`、`.tree-before.txt`、`.tree-after.txt`、`.metadata.txt`，完整逐文件路径见 `../06-test-report.md` 附录 A。共享身份检查为 `/tmp/nexusdesk-phase0-identity-checks.json`，环境指纹为 `/tmp/nexusdesk-phase0-environment.log`；比较门禁日志为 `/tmp/nexusdesk-phase0-compare-gate.log`。

`/tmp/nexusdesk-phase0-coverage-diff.json` 显示 8 个文件的 executed-line 集合有差异，Run 2 净多 14 条已覆盖行；每文件 run1-only/run2-only 行号均保留。节点 outcome 仍完全一致。这只是覆盖率观察，不是 flaky 测试证明，也不得以两位小数覆盖率或全绿总数隐藏。被测树当时未提交，最终 committed-artifact SHA 保持 `pending_commit`；本地双跑通过不替代 §7 的干净 CI `pending_env`、真实授权样本 `pending_env` 或人工验收。

**被取代的修复前 303 节点历史**完整保存在 `/tmp/nexusdesk-phase0-superseded-20261107-3d4f9b06/`：base 同上，tree 为 `sha256=3d4f9b06cbdd5de89250d888c0ea695d145e6051d4cc995c64107947fc14e729 files=1014`；两轮 UTC 分别为 2026-11-07T18:28:35Z～18:30:58Z、18:31:55Z～18:34:25Z，均为 303 passed、零 failure/error/skip，JUnit time 为 142.851s/148.877s，覆盖率为 9886/18534（53.34%）/9881/18534（53.31%），当时节点比较一致。所选源中没有实际 xfail 标记，但该轮没有 `audit-log` 产物，**不得作为修正后 XPASS 门禁通过的证据，也不得把其 tree hash 或计数冒充当前结果**。

**另保留一次被拒绝的 Run 1 尝试**于 `/tmp/nexusdesk-phase0-rejected-run1-20261107-19548c1d/`：tree 为 `sha256=19548c1df1591a9fb084e4bb178694d782a50c74c870d0ab4c936975e42d11b9 files=1018`，UTC 为 2026-11-07T21:20:28Z～21:22:53Z；pytest exit 0、308 个 JUnit 节点全 passed、time 144.515s、轮内树稳定，但审计因不支持真实终端汇总 `(0:02:24)` 而 exit 2，未生成正式 audit JSON，Run 2/compare 未启动。它不是测试失败，也不是通过的正式轮次。解析器修复后的独立诊断对该日志得到 exit 0、308 条记录、零 XPASS，但未把该尝试提升为正式证据；随后以新 Run 1 空库重新启动上述当前 310 节点双跑。

当前 310 节点 = 被取代的 303 节点 + 5 个 strict/non-strict XPASS 工具回归 + 2 个长耗时终端格式回归。本文及报告的数字回填发生在被测树完成之后，只修改文档；上述 tree hash 不代表包含这些事后文档编辑的新工作树，也不代表最终提交树。

## 7. CI 支持证据与边界

既有 CI run：<https://github.com/GroundedCoreAI/nexusdesk/actions/runs/42227604191>，2026-11-06 全部 job 成功，head 为 `16aed12eb095f29bed5c536b5fcbf68e510136c4`。目标提交 `c6c47de` 是该后端状态之后的文档合并，backend 树与该 CI head 一致；此前汇总计数为 949 passed、17 skipped。

这只是**现状后端单次全量 CI 支持证据**，不包含本阶段新增测试、覆盖率、JUnit artifact 或双跑比较。含 Phase 0 产物的提交尚未推送/运行 CI，因此正式 CI 双跑和链接保持 `pending_env`，不得将上述 run 写成 Phase 0 验收通过证据。

## 8. 缺陷与确定性处置

- 环境校准失败单独保留，不能混入正式失败率，也不能删除记录。
- 新增测试若两轮结果不同，先定位测试隔离、时钟、任务清理或数据库清理问题；不得简单重跑至绿色。
- 发现既有行为与文档不一致时，登记 R 项/缺陷并固定现实；Phase 0 不通过改生产代码或弱化断言制造全绿。
- 任一轮 `audit-log` 缺失、无法解析或发现 XPASS 时不得接受该轮或执行节点比较；不得用 JUnit passed、summary 成功或 compare 相同替代日志审计。
- `tool.replay` 终态后消耗 seq 的 P2 边界已有专门 SSE 测试证据，但未被宣称为安全修复；稀疏手工 raw version 的 `KeyError("tool_names")` 按 P0-I7 单独跟踪。二者均不得借全绿总数消失。
- CI、真实样本、人工签字缺证据时不满足 Phase 1 完整入口，即使本地测试全部通过。P0/P1 最终开放数量只能由后续实际测试/验收报告核定。
