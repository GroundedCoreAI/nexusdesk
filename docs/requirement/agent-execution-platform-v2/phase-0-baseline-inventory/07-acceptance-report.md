# Phase 0 · 基线与盘点 — 验收报告

> 状态：**待验收 / 未批准**（自动化验收证据已登记；不是通过，也不是有条件通过）
> 创建：2026-11-08
> 依据：`05-acceptance-plan.md`（A1～A6、UAT、五项业务指标、C1～C5）、`06-test-report.md`、`baseline/` 全部基线文档
> 执行：T10 自动化验收代理，**非人工验收、非签字替代**；本地执行及修正后产物回填日期 2026-11-08；所引修正后正式双跑执行于 UTC 2026-11-07
> 现状 base：`c6c47dec39025ebd4d1176c1e9925bac9c99c4fd`；修正后正式被测未提交树：`sha256=f7d3ae857427b5d0173c080f4e6678755f4562730629d3155c2b7d2c44c0d2b1 files=1018`
> 最终产物提交：**`pending_commit`**。base 不是被测未提交树的 SHA，上述树哈希也不包含事后新增的本报告

## 1. 验收组织、范围与前置条件

T10 原始轮次只执行 05 中可自动化的核查；本次仅复核并回填修正后正式双跑的实际产物，没有重跑或替换正式双跑，没有创建提交、推送、PR、CI 成功记录或人工签字。自动化执行与事后文档回填均不等于人工批准。

**前置条件核对**：

- 修正后的本地正式两轮均按同一有序 25 套件、两个独立空 PostgreSQL 数据库执行，310 个唯一节点全部通过，JUnit 的 skip/xfail/xpass 均为 0；两轮未暴露新的 P0/P1 实现缺陷。non-strict XPASS 不能由 JUnit 检测，因此每轮 `-rA` 日志均执行 `audit-log`，正式逐轮及比较门禁重新审计均 exit 0、`summary_entries=310`、`xpass_count=0`。
- 完整验收前置条件**尚未全部满足**：同一已提交产物的干净 CI 双跑为 `pending_env`，经授权真实历史样本为 `pending_env`，最终产物 SHA 为 `pending_commit`，架构/产品/QA/研发/安全验收及签字为 `pending_signoff`。
- 因此本报告登记的是支持基线的本地自动化证据，不宣称 AC-1～AC-6 已全部完成最终验收，也不放行 Phase 1。

**显式证据边界**：

1. P0-UT04 只证明进行中模型中断、工具取消和 worker task 的 await 收束，未枚举每个 asyncio watcher/task，不宣称全局无任务泄漏。
2. 普通 append/finish 的条件保护不能推广到专用 `tool.replay`。后者可在专用调用下于终态后消耗 seq；SSE 隐藏 payload 并推进游标已有测试，但安全/行为边界仍 P2/open，未被修复或裁定。
3. 七个 fixture 文件的值全部为合成值；仓库历史只证明字段形状，不证明真实生产/客户样本代表性。
4. 既有 CI run 42227604191 仅是另一 head 的现状后端单次支持证据，不是本次产物的 CI 双跑。
5. 两轮覆盖率行集合有八文件差异、Run 2 净多 14 行；这是观察，不是 flaky 证明，也不是逐行等价证明。
6. 正式树哈希只标识当时被测树，不标识包含 06/07 事后报告回填的当前工作树，也不标识最终提交树。
7. JUnit `summary` 只负责识别 strict XPASS 的 pytest 表示；non-strict XPASS 是普通 JUnit passed，必须由每轮 `-rA` 日志的 `audit-log` 检出。当前两轮及比较门禁重新审计均 exit 0、310 条、零 XPASS；旧 303 节点历史没有该审计产物，不能借当前结果补写旧轮次。
8. 修复前 303 节点双跑已归档为 `/tmp/nexusdesk-phase0-superseded-20261107-3d4f9b06/`，仅作被取代历史。另一次 308 节点 Run 1 因审计器不支持 `(0:02:24)` 而 exit 2，无正式 audit JSON，Run 2/compare 未启动，归档为 `/tmp/nexusdesk-phase0-rejected-run1-20261107-19548c1d/`；它不是测试失败或通过轮次，事后诊断成功也未将其提升为正式证据。两轮独立 spec/quality 评审分别批准 XPASS 与终端解析修复，详见 `06-test-report.md` §7。

## 2. 验收环境与自动化执行记录

| 环境 | 配置 / 前置数据 | 承担场景与边界 |
|---|---|---|
| 当前本机工作树 | macOS；分支 `feat/agent-execution-platform-v2-phase0`；实际 HEAD 与 base 均为 `c6c47dec39025ebd4d1176c1e9925bac9c99c4fd` | A1/A3/A5 静态核查、C1～C5、diff/引用/双语/ lint 检查；未修改生产或迁移 |
| 修正后正式本地 Run 1 / Run 2 | Python 3.11.9、uv 0.11.3、PostgreSQL 17.11；各自独立空库并迁移至 `0057_industry_pack_runtime`；demo/mock，无外部付费模型必过项 | A2/A3/A4/A6；本次只读复核当前 JUnit、audit、coverage、metadata、identity 与 compare，不重跑或覆盖正式测试产物 |
| 干净 CI | 同一**已提交产物 SHA**，同一环境连续两次，保留原始日志、JUnit、coverage 与链接 | A4/P0-I1：`pending_env`；研发负责人 + QA |
| 真实历史样本环境 | 经授权、脱敏的历史草稿和已发布快照及来源清单 | A3/UAT/P0-I2：`pending_env`；Agent 配置代表 + 安全代表 + 产品负责人 |
| 人工评审 | 架构、产品、QA、研发、安全代表及最终产物提交 | A1/A2/A5/A6、UAT、签字：`pending_signoff` |

本轮实际命令与结果（输出均保存在仓库外 `/tmp/nexusdesk-phase0-t10-*`）：

| 核查 | 实际命令 / 方法 | 实际结果 |
|---|---|---|
| 身份与零漂移 | `git rev-parse HEAD`、`git branch --show-current`；`git diff --name-status c6c47dec39025ebd4d1176c1e9925bac9c99c4fd -- backend/src backend/migrations`；同范围 `git ls-files --others --exclude-standard` | HEAD/base/分支符合预期；tracked diff 与 untracked 列表均为空 |
| 仓库内产物边界 | 以 `git ls-files -co --exclude-standard` 检查 `.coverage*`/实际 env 文件，并以 `find` 只列名称、不读内容 | 非忽略匹配为空；`.coverage*` 文件数为 0。预先存在的 ignored `backend/.env` 未读取、未使用，本轮未创建新的 env 产物 |
| 静态 fixture 与标识 | `uv run --frozen --directory backend pytest tests/test_runtime_baseline_fixtures.py tests/test_agent_config_execution_compat.py::test_p0_ut_08_frozen_identities_terminology_and_worker_neutrality -p no:cacheprovider -rA --durations=0 --junitxml=/tmp/nexusdesk-phase0-t10-config-static.xml` | **3 passed in 1.10s**；无需数据库；含 5 合法/16 非法 fixture 清单与精确结果断言、静态标识/Worker 中立断言 |
| Lint 与改动 Python 格式 | `uv run --frozen --directory backend ruff check src tests`；对 `test_runtime_postgres.py`、三个新 baseline 测试、AgentConfig 兼容测试及 `scripts/runtime_baseline.py` 共六文件执行 `ruff format --check` | lint `All checks passed!`；格式 `6 files already formatted` |
| T10 历史 JUnit 复核（被取代 303 节点树） | 当时用 `scripts/runtime_baseline.py summary` 分别写入新的 T10 summary，再执行 compare；产物现归档于 `/tmp/nexusdesk-phase0-superseded-20261107-3d4f9b06/` | 当时两份新 summary 与原 summary 完全相等，比较 JSON 与当时正式 compare 完全相等；`identical=true`，四类差异均为空，未覆盖正式产物。该历史复核不含 non-strict XPASS 日志审计，不作为当前门禁证据 |
| 修正后正式产物只读复核（本次回填） | 直接解析当前两份 summary/audit/coverage/metadata/tree、共享 identity/compare/coverage-diff 与 wrapper/compare-gate 日志；不写正式产物 | 两轮均 310 个唯一 passed 节点，time 145.281s/145.353s；audit 均 310 条、零 XPASS；四项身份检查 true，compare `identical=true` 且四类差异为空；pytest/summary/audit/tree/wrapper/compare 退出码均 0 |
| 引用、节点与双语静态审计 | 解析三份现状基线的 `path:line`，对照 base 文件；把 06 引用函数映射到两轮 `(classname,name)`；检查现有中英文件对 | 原有 135 个引用均存在，1 个范围包含尾部空行的精度提示仍保留；T10 当时 24 个引用通过，本次扩充后的 06 共 60 个不同测试函数引用均在当前两轮 summary 中存在且 passed；无缺节点；既有双语文件对无缺失 |
| 敏感信息定向扫描 | T10 历史扫描覆盖 28 文件；本次以 `/tmp/nexusdesk-phase0-doc-backfill-secret-scan.json` 对 7 个 fixture、当前两轮 log/XML/summary/audit/coverage/base/tree/metadata、七份共享/wrapper/compare-gate 证据及八份回填文档共 40 文件执行八类模式扫描，并人工查看 fixture 合成值 | 当前 `findings=[]`、`missing_files=[]`。定向扫描不是所有秘密形式的数学证明，也不替代安全签字 |

## 3. 功能验收记录（A1～A6）

执行人：T10 自动化验收代理；日期：2026-11-08。下表“本地自动化结果”与“最终验收状态”严格分列。

| # | 步骤与前置条件 | 实际证据 | 本地自动化结果 | 最终验收状态 | Owner 与所需环境 |
|---|---|---|---|---|---|
| A1 / AC-1 | 以 base、现状代码和 `runtime-dependencies.md` 为前置，从 Run API/Composition 追踪 submit、claim、Factory/Engine、事件与终态；抽查 owner、调用关系、数据/事件及测试映射 | 业务目标定义的 8 类核心面——Runtime Engine、Worker、Repository、Factory、Composition、Agent Config、extension contracts、Run API/SSE——均有 `path:line` 或测试证据及当前职责记录，另有 memory 与测试映射；构造期/每 Run 依赖与 Factory/direct-Runtime 路径分开。静态审计 135 个引用无失效，06 的 60 个被引测试函数两轮全过，`unknown=0`，没有未分派关键 unknown。`test_runtime_engine.py:50-237` 的末端包含空行，登记 P0-A3 文档精度项，不影响实质测试映射 | **本地盘点证据通过**；8/8 定义范围已登记，但不把静态核查当成架构批准 | **`pending_signoff`**；最终 owner/边界与 Adapter 改动入口仍须架构评审 | 架构负责人 + 研发负责人 + QA；最终产物提交及人工架构评审环境 |
| A2 / AC-2 | 以生命周期文档和两个独立 PostgreSQL 正式库为前置，核对正常、取消、失败、失租、竞态、迟到写入、SSE 与 hooks | 17 个文档定义转换行均有代码引用。IT01 固定 queued→running→completed；IT02 覆盖 queued/running cancel；IT03 覆盖 `run_timeout`、RuntimeFault、普通异常；IT04 覆盖 heartbeat/reaper 失租及 cancelled-with-error 变体；IT05 覆盖 cancel-first/reap-first 与并发唯一终态；IT06 覆盖重复 finish、迟到 append、错误 owner/失租和排他 claim；IT07 覆盖 strict max(after,Last-Event-ID)、204 条分页/排空、transient delta 与 replay；IT09 覆盖仅 completed 执行完成 hook、真实 graph 和 summary/memory 注入。P0-UT04 与 `tool.replay` 边界按 §1 限定，未宣称通用终态后写入保护 | **本地动态/静态证据通过（有界）**；P0-I4 保持 P2/open，不作安全豁免 | **`pending_signoff`**；实际/目标差异、公开事件开放枚举及 replay 安全/行为边界须架构与安全代表裁定 | Runtime + 安全 owner、架构负责人、QA；最终产物人工评审。P0-I4 修复或正式处置最迟 Phase 6 安全门槛前完成 |
| A3 / AC-3 | 以七文件 manifest+六 payload、现有 AgentConfig 和正式 PostgreSQL 发布链为前置，加载全部合法/非法样本并检查发布、快照、租户隔离和敏感信息 | 本地静态测试再次通过；正式证据为 **5/5 合法合成配置加载、16/16 非法用例按精确 Pydantic loc 拒绝**。两个 legacy raw draft 发布为规范化 v1，源 fixture 字节不变；v2 不改写 v1，queued Run 保留 v1，跨租户 versions/snapshot 分别保持既定 404。手工极稀疏 raw version 直接 snapshot 的 `KeyError("tool_names")` 保持 P0-I7 P2/open。当前 40 文件扫描无发现，人工查看 fixture 仅见合成 prompt、UUID 和工具名 | **本地合成样本与扫描通过**；真实历史代表性未测量，不能把 5/5 外推为生产 100% | **`pending_env`**（真实样本）+ **`pending_signoff`**（产品/安全）；A3 完整历史样本验收未通过 | Agent 配置代表 + 安全代表 + 产品负责人 + QA；经授权脱敏历史草稿/发布快照及来源清单 |
| A4 / AC-4 | 以相同树、相同有序 25 套件、两个独立空库及修正后正式产物为前置，复核节点、skip/xfail、日志审计、计数、覆盖率和 CI | Run 1/Run 2 均 310/310 passed，JUnit failures/errors/skipped/xfail/xpass=0；本地节点复现率 310/310=100%，added/missing/outcome/skip-reason 均无差异，四项树/base 身份检查全 true。两轮及比较门禁重新审计均 exit 0、310 条、零 XPASS。时间 145.281s/145.353s；coverage 9886/18534=53.34% 与 9900/18534=53.42%，八文件行集合差异和 Run 2 净多 14 行保留。既有 CI 不是当前产物证据 | **修正后本地双跑节点与 XPASS 审计门禁通过**；本次只读复核实际产物，没有重跑或覆盖正式双跑 | **`pending_env`**；同一最终已提交产物的干净 CI 双跑未完成，A4 最终未通过 | 研发负责人 + QA；最终提交上的干净 CI、两次原始 artifact/audit 和链接 |
| A5 / AC-5 | 以冻结标识表、Phase 1 双语示例、checklist 和 Worker AST 静态检查为前置 | `test_p0_ut_08_frozen_identities_terminology_and_worker_neutrality` 本轮再次通过，且正式两轮通过：生产 `(react,native,v1)` 与测试 `(local-test,scripted,v1)` 独立；Run=一次 Execution 尝试；无 Task/Execution 双表、无 Worker Engine/provider 分支；LocalTestAdapter 不代表真实 Host | **本地静态冻结证据通过**；不表示 Phase 1 已接线或放行 | **`pending_signoff`**；标识和术语最终由架构评审冻结确认 | 架构负责人 + Phase 1 契约 owner + QA；最终文档/产物人工评审 |
| A6 / AC-6 | 以 06、regression baseline、缺陷清单及 Phase 1–7 checklist 为前置，核对命令、环境、覆盖率、耗时、缺陷、回归映射和入口条件 | 本地资料包含完整有序命令、依赖/数据库环境、树身份、两轮 UTC/退出码、310 节点、两轮零 XPASS 审计、覆盖率/耗时、P0-I1～I7 和 Phase 1–7 映射；lint/format 本轮通过；两轮新发现 P0/P1 实现缺陷为 0。CI、真实样本、最终提交与人工入口评审仍未完成 | **本地入口资料已登记**；未勾选任何 Phase 1 入口项，未发布 Phase 1 | **`pending_env` + `pending_commit` + `pending_signoff`**；A6 最终入口评审未完成 | 架构/产品/QA/研发/安全共同负责；须先补齐 A1～A5 最终证据并召开人工入口评审 |

## 4. UAT 判定（架构与 Agent 配置代表）

| UAT 项 | 当前证据 | 判定 / 下一证据 | Owner |
|---|---|---|---|
| 架构代表确认依赖图可回答“新增 Adapter 需要改哪些入口”，且目标架构未冒充现状 | A1 已提供构造期、每 Run、公共 HTTP、中立 RunPort、Factory/direct-Runtime 和测试映射；A5 已冻结术语 | **`pending_signoff`**；架构代表对最终产物逐条确认，并处理 A2 replay 边界 | 架构负责人 |
| Agent 配置代表抽查典型历史草稿/发布版本，确认无手工 Engine 字段迁移要求 | 合成/当前公开 publish 链没有建立要求手工添加 Engine 字段的需求；legacy 字段形状会由现有发布链补齐当前默认值 | **`pending_signoff` + `pending_env`**；真实历史代表样本尚未确认，不能将合成链结论外推为全部历史配置承诺 | Agent 配置代表 + 产品负责人 + 安全代表 |
| QA 与研发确认基线失败不会自动成为后续“可接受回归” | checklist 要求停线、保留失败和独立裁定；本报告未豁免 P0-I3/I4/I7 | **`pending_signoff`**；在 Phase 1 入口评审形成共同确认 | QA + 研发负责人 |

## 5. 业务指标逐项判定

| 指标 | 分母与测量方法 | 实测结果 | 最终判定 / 边界 |
|---|---|---|---|
| 1. 核心模块盘点覆盖率 | 分母为 §3-A1 明确定义的 8 类核心面；逐项检查代码/测试证据、调用关系、当前职责与测试映射 | **8/8=100%（文档定义范围的本地登记覆盖）**；135 个引用无失效，60 个被引测试函数两轮全过；另有 1 个尾部空行引用精度提示 | **本地范围达标，最终 `pending_signoff`**；不是对任意未列模块的 100% 声明，仍须架构确认 owner/边界 |
| 2. 状态转换与公开事件语义覆盖率 | 转换登记分母为生命周期 §2 的 17 行；逐行核对代码引用，再以 IT01～07/09 对照动态证据。公开业务扩展事件不是封闭枚举，不能伪造全代码分母 | **17/17=100%（文档定义转换行的静态登记）**；列举场景有两轮正式证据。UT04 与 replay 边界未扩大 | **完整指标 `pending_signoff`**；不宣称所有代码可达转换/公开事件已无条件 100% 覆盖，P0-I4 未裁定 |
| 3. 纳入样本的配置加载通过率 | 合法合成 fixture 分母 5；非法构造分母 16；真实历史样本分母只有在授权样本清单形成后才能确定 | **5/5=100% 合法合成加载；16/16=100% 非法拒绝**；七文件完整。真实历史样本未提供，不记为 0%，也不记为通过 | **本地合成指标通过；完整指标 `pending_env`**；P0-I7 与真实代表性不能被样本总数掩盖 |
| 4. 双跑节点可复现率 | 分母为每轮 310 个唯一 `(classname,name)`；逐节点比较 added/missing/outcome/skip-reason，并独立审计两轮 `-rA` 日志 | **修正后本地 310/310=100% 一致**；两轮均全 passed、JUnit 零 skip/xfail/xpass，四类差异为空；两轮及比较门禁重新审计均 exit 0、310 条、零 XPASS | **修正后本地节点与 XPASS 审计指标通过，CI `pending_env`**；同一最终提交的干净 CI 双跑未测量，不能给完整指标通过 |
| 5. P0/P1 基线阻断项 | 实现缺陷测量分母为两轮正式执行的新发现缺陷记录；验收门禁另按 P0-I1/I2、commit 和 signoff 逐项核对，二者不混算 | 两轮新发现 **P0=0、P1=0 实现缺陷**；但 CI、真实样本、最终产物 SHA 和人工签字门禁未关闭 | **最终待验收**；“没有新实现失败”不等于“最终 P0/P1 验收阻断已清零”，不满足完整通过标准 |

## 6. 合规核对（C1～C5）

| # | 本地自动化结果与证据 | 最终边界 / 状态 |
|---|---|---|
| C1 | **本地定向扫描通过**：当前 40 份 fixture/正式证据/回填文档无八类秘密模式发现，见 `/tmp/nexusdesk-phase0-doc-backfill-secret-scan.json`；fixture 人工核查为合成值。06 的失败终态/caplog 断言亦未泄露合成 provider 原文 | 不是全部秘密形式或人工安全审查的替代；真实样本授权/脱敏仍 `pending_env`，安全签字 `pending_signoff` |
| C2 | **本地通过**：`backend/src backend/migrations` tracked 与 untracked 零差异；HEAD/base 未变，无历史改写；正式证据使用两个专用合成空库并迁移至 0057，无生产 Run/配置数据 | 本轮未改生产、迁移或历史；最终由研发/QA 在签字时确认同一最终产物 |
| C3 | **修正后本地环境/节点/审计证据通过**：正式路径使用 demo/mock、受控本地 HTTP 与 PostgreSQL，无外部付费模型必过条件；310 节点的 JUnit 零 skip/xfail/xpass，两轮及比较门禁重新审计均 exit 0、310 条、零 XPASS；本报告如实保留 pending_env/pending_commit/pending_signoff | 后续 CI 不得隐藏 skip/xfail/XPASS 或引入外部付费必过依赖；QA 最终复核 |
| C4 | **本地身份证据通过但非完整通过**：base 与确定性 tree hash 明确，四项身份检查 true；checklist 已指定后续增量复核责任和入口条件 | **`pending_commit`**：最终产物提交 SHA 不存在，不能给 C4 无限制通过，base 不得冒充产物 SHA |
| C5 | **静态可回退范围通过**：变更限于测试、fixture、文档、基线脚本和 dev-group `pytest-cov`/lock；无生产缺陷修复或迁移，可按独立路径 revert | **未执行实际 revert 演练，不宣称已演练**；最终 committed-artifact 的独立回退证据为 `pending_commit` + QA/研发复核 |

## 7. 遗留问题与验收未决项

P2/P3 的 owner/期限不构成对安全、真实样本兼容或双跑确定性的有条件豁免。

| ID | 级别 / 状态 | 问题与影响 | Owner | 期限建议 |
|---|---|---|---|---|
| P0-I1 | `pending_env` | 同一最终产物提交的干净 CI 双跑、原始 artifact 与链接缺失；阻断 A4/A6 完整验收和 Phase 1 入口 | 研发负责人 + QA | Phase 1 入口评审前 |
| P0-I2 | `pending_env` | 未提供授权真实历史发布快照；合成 fixture 不能证明生产代表性，阻断 A3/UAT 完整验收 | Agent 配置代表 + 安全代表 + 产品负责人 | Phase 1 配置兼容评审前补样；范围裁定不能伪作样本实测 |
| P0-I3 | P2 / open | 开放平台 stream 注释称无 token delta，实际输出可见文本 delta；文档/注释现状偏差 | 开放平台后端 owner | Phase 2 前 |
| P0-I4 | P2 / open | 专用 `tool.replay` 可在终态后消耗 seq；测试只证明 SSE 隐藏 payload/推进游标，不是安全修复。A2 架构/安全裁定不得被跳过，且不得扩散到新事件路径 | Runtime + 安全 owner | Phase 0 签字时确认边界；修复或正式处置最迟 Phase 6 安全门槛前 |
| P0-I5 | P3 / open | 既有 `seed_memory_*` 全量格式差异；与本轮六文件格式通过无关 | 对应脚本 owner | 后续相关脚本变更时 |
| P0-I6 | 环境说明 | ignored 旧目录/`__pycache__` 干扰本地架构扫描；不属于 Git 目标树，未删除用户文件制造干净结果 | 本地环境 owner | 后续本地复现时 |
| P0-I7 | P2 / open | 手工极稀疏 raw version 直接 `snapshot()` 抛 `KeyError("tool_names")`；公开 publish 链通过不能关闭该存储边界 | AgentConfig + Runtime owner | Phase 3 配置映射前解决或正式裁定并补回归 |
| P0-A1 | `pending_commit` | 最终产物 SHA 尚未形成；C4 无法完整通过，当前树也包含事后报告，不沿用正式 tree hash 冒充 | 研发负责人 + QA | CI 双跑和 Phase 1 入口评审前 |
| P0-A2 | `pending_signoff` | 架构/产品/QA/研发/安全的 A1～A6、UAT、指标和合规最终评审未完成；自动执行不能代签 | 五类验收角色 | Phase 1 入口评审前 |
| P0-A3 | P3 / open（文档精度） | `runtime-dependencies` 的 `test_runtime_engine.py:50-237` 范围包含尾部空行；最后实质行是 236。没有缺失测试证据或行为影响，但应收敛引用范围 | Phase 0 文档 owner + QA | 最终架构签字前或下一次获准文档修订时 |

## 8. 结论、下一证据与签字

**总体结论：本地可自动化证据支持该基线，但 Phase 0 仍为“待验收 / 未批准”；不给予有条件通过，不放行 Phase 1。**

理由：A1/A2/A5/A6 的最终人工或入口批准未完成，A3 真实历史代表性与 A4 干净 CI 仍为 `pending_env`；修正后的本地两轮 XPASS 日志审计虽已通过，但五项指标未全部达到最终验收状态；C4 为 `pending_commit`，C1～C5 尚需纳入最终人工验收；五类签字均为 `pending_signoff`。该结论表示证据和批准门槛未完成，**不表示实现失败**，也不否定当前两轮 310 节点全过、零 XPASS 审计及本地节点一致性。

| 角色 | 签字 / 日期 | 完成签字前所需的下一证据 |
|---|---|---|
| 架构负责人 | **`pending_signoff`** / — | 最终提交上的 A1/A2/A5 评审；确认实际/目标边界、17 行转换与开放事件边界、冻结术语，并裁定 P0-I4 当前基线边界 |
| 产品负责人（含 Agent 配置代表、P2 处置） | **`pending_signoff`** / — | A3/UAT 真实历史代表样本或明确证据边界；确认合成/当前链未建立手工 Engine 字段迁移要求，不将其外推为全部历史承诺；处置 P2/P3 |
| QA | **`pending_signoff`** / — | 最终提交、干净 CI 双跑原始 artifact/链接、指标分母复核、C5 回退范围复核及 P0-A3 文档精度处置 |
| 研发负责人 | **`pending_signoff`** / — | 提供最终产物 SHA 和干净 CI 环境；保持生产/迁移零漂移；落实 P0-I1～I7 owner/期限与后续增量复核 |
| 安全代表 | **`pending_signoff`** / — | 审核真实样本授权/脱敏与最终报告扫描；确认 `tool.replay` 安全边界未被测试证据或 P2 级别豁免 |

自动化执行者只提供上述证据，不在签字表中代替任何角色。只有 A1～A6、五项指标、C1～C5、P0/P1 门禁及五类人工签字全部完成后，才能重新判定 Phase 0 验收与 Phase 1 入口。
