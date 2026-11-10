# Phase 0 基线 · 标识与分阶段重构检查清单

> 状态：基线检查清单；不代表正式双跑、CI、验收或 Phase 1 已放行
> 现状目标提交：`c6c47dec39025ebd4d1176c1e9925bac9c99c4fd`
> 当前产物树：未提交的特性分支工作树，不赋予虚构 SHA；后续证据须区分目标提交与实际产物
> 冻结日期：2026-11-07；T8 扩充：2026-11-08
> 依据：`configuration-compatibility.md`、`regression-baseline.md`、`04-test-plan.md`
> 用法：后续阶段启动时先比较目标 SHA，再逐项附加新证据；不得覆盖本基线或用目标架构替代现状验证

## 1. 冻结标识与术语

| 项 | 冻结值 | 约束 |
|---|---|---|
| 生产 React Engine | `react` | 当前 LangGraph ReAct 的未来公共 Engine ID，不是 Python 类名 |
| 生产原生 Protocol | `native` | 保留 ReAct 原生模型/工具语义，不强制抹平事件 |
| 初版 Adapter | `v1` | 显式解析；禁止隐式 latest |
| 生产组合 | `(react,native,v1)` | Phase 2 新旧 React 路径和 Phase 3 旧配置默认值必须一致 |
| LocalTestAdapter 组合 | `(local-test,scripted,v1)` | 仅测试使用；不得成为生产 Agent 默认值，不代表真实进程监管 |
| Execution | 一次执行尝试 | 首次迁移 `Run = 一次 Execution 尝试`，`execution_id` 与 Run ID 的映射由 Phase 1 明确 |
| Task | 不建双表 | 不引入 Task/Execution 双表或第二套当前状态机 |
| Worker 选择 | 无 Engine 分支 | Engine/Protocol/Adapter 由契约和 Registry 精确解析，不在 Worker 写供应商 if/else |

任何新增 ID、版本或不兼容组合必须先登记兼容矩阵并增加契约测试；不得复用 `react` 指向不同推理实现，也不得用 `local-test` 通过生产授权。AgentConfig 当前拒绝未知 `engine` 字段是 `extra=forbid` 的现状证据，不是未来 Engine 映射的预先批准。

## 2. 每次重构的通用门禁

- [ ] 记录实施目标 SHA、干净工作树、当时实际 Alembic head；与 Phase 0 基线做增量 diff，并区分现状目标与当前产物提交。
- [ ] 保持五个 Run 状态、取消标志、owner/lease、fingerprint、每 Run Agent 快照和终态事务。
- [ ] 重跑 Runtime 核心与基线工具：`test_runtime_engine.py`、`test_runtime_baseline.py`、`test_runtime_baseline_tooling.py`、`test_runtime_baseline_fixtures.py`，保留 summary/compare 的原始输出。
- [ ] 重跑 `test_agent_config_execution_compat.py` 的 AgentConfig fixture/发布/快照/租户隔离/排队 Run 快照及稀疏 raw-version 限制证据；配置矩阵新增用例须声明精确 Pydantic `loc`。
- [ ] 对 Runtime 持久化、并发、SSE/replay 或 Run API 的改动，按影响重跑 `test_runtime_postgres.py`、`test_runtime_availability.py`、`test_runtime_scope.py`、`test_tool_replay_postgres.py`、`test_platform_postgres.py`、`test_open_platform.py`；Agent 语言/模型约束改动另跑对应 `test_agent_*` 套件。
- [ ] 对 memory 或上下文组装的改动，按影响重跑 `test_memory_config.py`、`test_memory_postgres.py`、`test_memory_customers_postgres.py`、`test_memory_config_postgres.py`，尤其 `test_memory_injection_postgres.py` 的注入明细、上限、开关与隔离断言。
- [ ] 对 model/tool 边界改动，按影响重跑 `test_model_gateway.py`、`test_model_discovery.py`、`test_tool_egress.py`、`test_tool_post.py`、`test_tool_credentials.py`、`test_tool_workspace.py`；无关改动不机械要求整套运行，阶段级正式基线仍按既定清单执行。
- [ ] 普通持久事件与 transient delta 分开断言；严格 after 重放、终态排空、公开字段缩减不退化，并保留 `tool.replay` 专用边界的独立判断。
- [ ] 失败、skip、xfail 和 pending_env 全部保留原因；双跑按 `(classname,name)` 比较节点、outcome 和 skip 原因，不只比较总数，耗时不参与等价。
- [ ] 不输出 config/history/凭据/连接串/Provider 原文；fixture 继续使用合成值，真实生产样本代表性保持 `pending_env` 直至授权补证。
- [ ] 生产缺陷修复与行为变更另起小提交，附前后证据；不得混入“等价重构”。
- [ ] 数据库改动使用实施时实际 head 新迁移，禁止修改已应用历史迁移；无迁移阶段须证明 head 不变。

## 3. Phase 1–7 映射

| 阶段 | 必须保留/验证 | 必跑基线与新增证据 | 回滚/停线条件 |
|---|---|---|---|
| Phase 1 契约与 Registry | 生产零接线；两组冻结三元组独立；显式版本；中立 RunPort 不被误当现有 HTTP 合同 | 全部新增契约/Registry/LocalTestAdapter 测试 + Runtime 单测、基线工具/fixture 与静态标识检查；head 与入口相同 | 仅移除未接线代码；任何生产接线、隐式 latest、Worker 分支或迁移都停线 |
| Phase 2 React Provider/Orchestrator | 新旧路径 output/history/dropped、事件、错误、取消、reaper、memory 完成副作用等价；Worker 只依赖编排 | 全部适用的 Phase 0 Runtime/PostgreSQL/SSE/replay/AgentConfig/memory-injection 基线双跑；新旧同脚本 A/B；Factory 与直接 Runtime 兼容路径 | 开关回到旧路径且无需数据回退；任何终态、事件、配置、memory 副作用或跨租户差异停线 |
| Phase 3 能力/配置/指令 | 旧配置缺省映射 `(react,native,v1)`；raw 历史 JSONB 不改写；Declared/Available/Effective 与授权分离；先处置 P0-I7 存储阶段限制 | 全部 fixture 与发布/快照/按版本执行；新旧默认等值；客户端提权与跨租户对抗测试；稀疏 raw version 的修复或正式裁定及回归 | 可关闭新配置解析；合法旧样本失败、历史版本被改写或客户端提权停线；不得把手工稀疏行限制误报成公开 publish 失败 |
| Phase 4 Runtime Host/Workspace | 现有 Run 治理不被进程状态复制；真实进程树清理、路径/软链隔离、资源限额另证 | Phase 0 生命周期/取消/迟到写入 + 新进程故障/工作区对抗测试；LocalTestAdapter 不得冒充 Host 证据 | 新 Host 默认关闭；宿主越权、泄露、悬挂进程或取消不清理停线 |
| Phase 5 Codex A/B | Provider 内封装 CLI/App-Server 原生协议；统一治理不抹平原生事件；凭据不进入 fixture/日志 | Phase 0 契约/生命周期/SSE + 新 Provider 契约套件与受控集成；付费/外部服务不作为旧基线必过条件 | CLI 未稳定不得启用 App-Server；安全门槛、回退与事件兼容失败即关闭新 Provider |
| Phase 6 安全/可靠性/事件治理 | Fencing、Outbox、去重、取消/重放竞态；普通事件与 replay 专用路径分别评审 | 全部适用的 Phase 0 基线 + 故障注入、对抗、安全和并发测试；以终态 `tool.replay` SSE 测试为现状证据，同时明确处理终态后消耗 seq 的未决边界 | 不可信多租户上线必须全部满足隔离/凭据/网络/资源门槛；不得以 P2 延期或已有测试证据绕过安全 veto |
| Phase 7 高级能力/规模化 | 自 2026-11-07 起暂缓；重新激活后按独立切片评审，路由/回退重算策略 | 当前不执行、不验收；激活后复用全部适用基线并为每切片新增证据 | P4 issue #110–#120 跟踪；未明确激活不得作为交付承诺或削弱前述门槛 |

## 4. 当前差异、未决项与责任

| ID | 级别/状态 | 项 | Owner / 期限 | 对 Phase 1 的影响 |
|---|---|---|---|---|
| P0-I1 | `pending_env` | 同一产物提交的干净 CI 双跑、原始 artifact 与 CI 链接尚未形成 | 研发负责人 + QA；Phase 1 入口评审前 | 本地双跑不能替代 CI AC-4 证据 |
| P0-I2 | `pending_env` | 未提供经授权的真实历史发布快照；当前仅有明确标注来源的合成字段形状 fixture | Agent 配置代表 + 安全代表；Phase 1 配置兼容评审前 | 不得宣称真实样本代表性；需补样本或形成正式范围裁定 |
| P0-I3 | P2 / open | 开放平台 stream 注释称无 token delta，实际会输出可见文本 delta | 开放平台后端 owner；Phase 2 前 | 不改变当前基线，不影响未接线契约 |
| P0-I4 | P2 / open | `tool.replay` 可在专用调用下于终态后消耗 seq；`test_p0_it_07_internal_sse_hides_terminal_tool_replay_and_advances_cursor` 已证明 SSE 隐藏 payload 且推进游标的现状，但安全/行为边界仍未修复或裁定 | Runtime + 安全 owner；最迟 Phase 6 安全门槛前 | Phase 0 已隔离记录；普通终态状态未被覆盖，禁止把测试证据写成安全修复或把该行为扩散到新事件路径 |
| P0-I5 | P3 / open | 既有 `seed_memory_*` 的全量格式检查差异 | 对应脚本 owner；后续相关脚本变更时 | 与 Phase 0 新增文件无关，不通过批量格式化混入本阶段 |
| P0-I6 | 环境说明 | 本地忽略旧目录/`__pycache__` 会干扰架构扫描；干净目标 worktree 门禁通过 | 本地环境 owner；后续本地复现时 | 不属于 Git 目标树；不得删除用户文件制造“干净”结论 |
| P0-I7 | P2 / open | 手工插入的极稀疏 raw version 虽通过 `AgentConfig` 输入校验，直接 `snapshot()` 当前抛 `KeyError("tool_names")`；这是存储阶段限制，不证明公开 publish 会生成该行，也不证明所有合法配置均可直接执行 | AgentConfig + Runtime owner；Phase 3 配置映射前解决或正式裁定并补回归 | 与经授权真实历史合法样本失败的 P1 分级分开；本项不伪造公开 publish 失败证据，也不得因公开链路测试通过而关闭存储边界 |

P0/P1 缺陷的最终开放数量必须由 `06-test-report.md` 与 `07-acceptance-report.md` 根据实际结果复核；本清单不提前宣称验收通过、P0/P1 数量或 Phase 1 已放行。T8 不创建上述报告，也不把聚焦预检、评审或自比较写成正式双跑。

## 5. Phase 1 入口核对

- [ ] AC-1～AC-6 均有当前产物提交的证据，所有 pending_env 有环境和 owner。
- [ ] 干净 CI 双跑节点结果一致，skip/xfail/flaky 均有处置；覆盖率和耗时不是未测量却填 0。
- [ ] 真实历史样本已补证或其代表性边界经 Agent 配置/安全/产品正式裁定。
- [ ] P0/P1 未决项为 0；P2/P3 均有 owner、期限和影响边界。
- [ ] 本清单中的冻结标识和通用门禁已进入 Phase 1 测试设计。
- [ ] 架构、产品、QA、研发和安全完成各自签字；本地开发完成不代替签字。
