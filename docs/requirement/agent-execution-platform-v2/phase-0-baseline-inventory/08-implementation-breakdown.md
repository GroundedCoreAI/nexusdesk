# Phase 0 · 基线与盘点 — 实施拆解方案

> 状态：进行中（按目标提交拆解，核查裁定随实施回填）
> 创建：2026-11-07
> 依据：`01`~`05` 全部文档 + 现状代码核查（backend @ `c6c47dec39025ebd4d1176c1e9925bac9c99c4fd`）
> 约束：只新增测试、fixture 与中英文基线文档；不改生产执行链、不新增迁移；本地运行受影响套件，完整套件与干净 CI 证据按 04/05 另行核验

## 1. 任务拆解（按依赖顺序）

依赖主线：**锁定目标与环境 → 现状证据盘点 → 补齐 fixture/回归缺口 → 形成基线与检查清单 → 双跑及报告**。运行时、配置兼容与结果工具核查可并行；任何文档与代码现实冲突先登记 R-n，再修改测试或文档。

| # | 任务 | 文件（新建/修改） | 依赖 | 溯源 |
|---|---|---|---|---|
| T1 | 锁定目标 SHA、核查工作树、准备隔离 PostgreSQL 并迁移至 head；保存现有套件原始结果 | `baseline/regression-baseline.md`（+`.en.md`） | — | FR-1/FR-4/FR-6，AC-1/AC-4，见 R1/R2 |
| T2 | 盘点 Run API/SSE、Composition、Factory、Worker、Repository、Engine、内存注入及测试映射 | `baseline/runtime-dependencies.md`（+`.en.md`） | T1 | FR-1，AC-1 |
| T3 | 固化实际 Run 状态机、取消/超时/失租/终态保护、事件及 SSE 重放语义 | `baseline/run-lifecycle-events.md`（+`.en.md`） | T1 | FR-2，AC-2 |
| T4 | 建立来源可说明、脱敏、版本化的 AgentConfig fixture 与清单 | `backend/tests/fixtures/agent_execution_baseline/` | T1 | FR-3，AC-3，见 R3 |
| T5 | 补充现状 Engine/Worker/结果解析与双跑差异比较的单测缺口，不复制已有覆盖 | `backend/tests/test_runtime_baseline.py`（新）及必要测试辅助模块 | T2/T3 | FR-1/FR-2/FR-4/FR-6，P0-UT-01~04/08~10 |
| T6 | 补充 AgentConfig 加载、非法输入、fixture 清单、草稿→发布→快照及租户隔离测试 | `backend/tests/test_agent_config_execution_compat.py`（新） | T4 | FR-3，P0-UT-05~07、P0-IT-08 |
| T7 | 只针对未覆盖的 PostgreSQL 生命周期、竞态、事件/SSE 场景补测试 | `backend/tests/test_runtime_postgres.py` | T2/T3 | FR-2/FR-4，P0-IT-01~07/09 |
| T8 | 汇总配置兼容矩阵、可复现命令、覆盖率/耗时、缺陷与分阶段回归映射，冻结标识和检查清单 | `baseline/configuration-compatibility.md`、`baseline/regression-baseline.md`、`baseline/refactoring-checklist.md`（均 +`.en.md`） | T2~T7 | FR-3/FR-5/FR-6，AC-3~6 |
| T9 | 逐条执行 04 的 UT/IT/CM，受影响套件双跑并比较节点结果；如实生成测试报告 | `06-test-report.md`（+`.en.md`） | T5~T8 | 04 全文，AC-1~6 |
| T10 | 对照 05 执行可自动验收项；CI、真实样本或人工签字不足项标 `pending_env`，不提前判定通过 | `07-acceptance-report.md`（+`.en.md`） | T9 | 05 全文 |

报告格式沿用需求生命周期技能的 `06-test-report.md` / `07-acceptance-report.md` 模板。测试报告和验收报告只记录实际执行证据，不在开发启动时预写通过结论。

## 2. 文档与现实不一致清单及裁定

### R1 规划核查点与本次执行目标提交不同

文档（03 文首）记录规划核查点为 `fb3f424`，并要求执行时重新记录 SHA。现实：本阶段从最新 `integration` 的 `c6c47dec39025ebd4d1176c1e9925bac9c99c4fd` 建立 `feat/agent-execution-platform-v2-phase0`，初始工作树干净。**裁定**：基线结论绑定 `c6c47de`；新增测试只影响后续工作树，报告分别注明“未修改现状代码的目标提交”和“含基线产物的待测提交”，不得混称同一 SHA。

### R2 测试库连接与 Alembic 连接是不同环境入口

文档（03/04）要求使用专用 PostgreSQL 和 `TEST_DATABASE_URL`，未明确干净库的迁移命令。现实：测试使用 `TEST_DATABASE_URL`，而 `backend/migrations/env.py` 经 `Settings` 读取 `AGENT_DATABASE_URL`；只对空库设置前者会以默认连接失败，未迁移直接运行会出现 `relation "runtime_runs" does not exist`。**裁定**：可复现步骤先对专用空库设置 `AGENT_DATABASE_URL` 并执行 `alembic upgrade head`，再以同一连接设置 `TEST_DATABASE_URL` 执行 pytest；两个值都不得写入仓库。环境校准失败保留原始计数，但不计入正式双跑。

### R3 真实历史样本与仓库内构造样本必须分开标识

文档（02 FR-3、03 §3）优先要求经授权脱敏的历史配置和发布快照。现实：本阶段未获得生产或客户快照，不能将构造 JSON 宣称为真实历史样本；仓库历史可用于核对旧版 `AgentConfig` 字段形状。**裁定**：首版 fixture 只使用无客户内容的合成值，并按仓库历史提交标注“旧字段形状/当前边界/非法构造”来源类别；覆盖报告单列“真实发布快照代表性未验证”的证据边界和后续 owner，不以删除样本或虚构来源达到指标。

### R4 当前迁移头为 0057，固定 0052 验收口径已过期

文档总 README 的 `0052_memory_tasks_tenant_index` 是 2026-11-02 规划核查值，Phase 1 多份文档却把 `0052` 写成未来固定验收值。现实：目标提交 `c6c47de` 的 `alembic heads` 为 `0057_industry_pack_runtime (head)`。**裁定**：Phase 0 不新增迁移，基线记录并验证 `0057`；总 README 明确历史核查时间，Phase 1 改为“相对实施时目标 head 无变化”，其他后续阶段在各自启动时重核，不在本阶段批量改写其规划编号。

### R5 覆盖率与节点级双跑工具尚不存在

文档（03 §4）称“使用项目既有覆盖率工具”。现实：dev 依赖只有 pytest、httpx、ruff、pytest-asyncio、pytest-split，没有 coverage/pytest-cov；CI 也不产出 JUnit 或双跑比较结果。**裁定**：在 `backend/pyproject.toml` 的 dev group 增加 `pytest-cov` 并更新 `uv.lock`，不改生产依赖；新增 `backend/scripts/runtime_baseline.py`，仅用标准库解析 JUnit 计数、skip 原因和节点结果并比较两轮差异。覆盖率缺失不得写成 0%。

### R6 “所有迟到事件均被条件更新拒绝”范围过宽

文档（03 §2）将终态保护和重复事件概括为 Repository 条件更新拒绝。现实：普通 `finish` 在终态/错误 owner/失租时静默 no-op，普通 `append` 抛 `CancelledError`；但 `DurableToolReplayCache.put` 自行增加 `event_seq` 并写 `tool.replay`，不检查 Run 状态、owner、lease 或取消标记。**裁定**：基线分别记录普通执行事件和 replay 内部缓存事件，不为符合理想模型修改生产代码或断言；SSE 对 replay 隐藏 payload 但推进游标的现状另行固定。

### R7 配置“规范化”必须按读取/发布/快照阶段区分

文档（03 §3）要求比较规范化结果和源样本不变，容易被理解为所有读取都会补齐默认值。现实：create/update/publish 会写完整当前默认值；原始 draft/version 读取和 `snapshot()` 返回存储 JSON，不物化校验默认值，且 snapshot 在校验前直接读取 `tool_names`。**裁定**：合法发布集成 fixture 保留核心执行键，断言 raw draft 不变、published version 被规范化、既有 version 后续不被改写；另记录极稀疏 raw version 的当前限制，不把它伪报为可执行。

### R8 本地静态检查需区分目标树与残留环境

现实：`ruff check src tests` 在目标树通过，但全量 `ruff format --check src` 暴露既有 `seed_memory_*` 格式差异；当前工作目录的忽略旧目录/`__pycache__` 会使架构门禁误报，目标提交的干净 worktree 中门禁通过。**裁定**：不删除用户预先存在的忽略文件、不在 Phase 0 格式化无关生产脚本；报告将格式项登记为既有 P3，架构结论以干净 worktree 和 CI 为证据，新增/修改 Python 文件单独执行格式检查。

### R9 LocalTestAdapter 的具体测试标识不能留到实现时隐式决定

文档（03 §5）原写“精确值在 Phase 1 契约评审中登记”，但 02 FR-5 要求命名冲突或语义不清在 Phase 0 解决，AC-5 又要求未决命名均有裁定。现实：架构与 Phase 1 文档只定义 LocalTestAdapter 类名和场景，没有测试 Engine/Protocol 的具体 ID。**裁定**：Phase 0 冻结生产三元组 `(react,native,v1)`，并冻结 LocalTestAdapter 专用三元组 `(local-test,scripted,v1)`；后者不得用于生产 Agent 默认解析，也不得被当成真实进程监管能力。Phase 1 契约测试显式断言两组身份独立。

## 3. 完成与停线条件

- 任一核心现状结论无 `path:line` 或测试节点证据，标记 `unknown` 并指定 owner；不得从目标架构反推现状。
- 发现既有行为失败时先登记缺陷并单独裁定；不得通过放宽断言、改写 fixture 或顺手重构制造全绿。
- 新增测试如出现非确定性、敏感信息或跨租户问题，按 04 的 P0/P1 停线。
- 完整验收必须满足 05；本地开发完成不等于 Phase 1 已放行。
