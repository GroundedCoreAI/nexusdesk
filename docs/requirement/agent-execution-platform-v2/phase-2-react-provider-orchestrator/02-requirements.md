# Phase 2 · React Provider 与执行编排器 — 需求文档

> 状态：待评审 / 待实施
> 创建：2026-11-02
> 依据：`docs/architecture/agent-execution-platform-v2.md` 第 4～7、12、14～17 节，Phase 2；Phase 1（FR-1～FR-6）；`01-business-goals.md`（G1～G4）

## 用户故事

**US-1（现有租户用户）**：作为现有 Agent 的使用者，我希望平台内部重构后无需修改 Agent 配置或客户端，以便继续获得相同回复、事件和取消行为。

**US-2（平台研发）**：作为平台研发，我希望 React 通过公共 Adapter 和编排器运行，以便未来新增 Engine 时不再修改 Worker 核心逻辑。

**US-3（平台运维）**：作为平台运维，我希望新路径默认关闭且可灰度、可回滚，以便出现异常时无需数据库操作即可恢复旧执行路径。

**US-4（QA/SRE）**：作为 QA/SRE，我希望对比新旧路径的输出、事件、错误和终态，以便用可重复证据判定迁移没有回归。

## 功能需求

### FR-1 React Engine Adapter

| 项 | 说明 |
|---|---|
| 触发时机 | 新路径编排器将已认领 Run 解析为 `react/native/v1` 并启动 Adapter 时 |
| 输入 | ExecutionRequest、执行私有上下文（claimed row、history、summary/customer_memory、事件回调）及由现有 RuntimeFactory 构造的 RuntimeEngine |
| 输出 | 完整 Adapter 五方法结果；ExecutionResult 保留 output/usage/error，内部 engine_metadata 向编排器返回 history 与 dropped，身份固定 react/native/v1 |
| 执行方式 | 异步包装现有 `RuntimeEngine.run()`，不重写模型/工具循环；start 启动执行，stream 转发事件，collect 收集唯一结果，cancel 可重复并停止等待中的执行 |
| 失败处理 | RuntimeFault、TimeoutError、CancelledError 和未知异常映射为 ExecutionError/取消结果；保留原 error_code；history/dropped 不进入公共 API、日志或 SSE |

### FR-2 Execution Orchestrator

| 项 | 说明 |
|---|---|
| 触发时机 | Worker 在开关开启时认领一个 Run 并完成配置 fingerprint 校验后 |
| 输入 | claimed row、可信 tenant/conversation/agent 上下文、事件发射回调及 Memory 渲染结果 |
| 输出 | ExecutionOutcome（status、output、history、dropped、规范化 error_code）；每次执行使用独立 Adapter/Handle |
| 执行方式 | 异步执行：构造 Request→固定兼容选择 react/native/v1→注册中心精确解析→start→消费 stream_events→collect_result；不执行推理、不直接调用 RuntimeEngine.run |
| 失败处理 | 注册/版本/Adapter 启动失败返回或抛出可规范化的失败，不静默回退其他版本或旧路径；清理事件迭代器和 Adapter 任务，未知异常对外保持 execution_error |

### FR-3 Worker 接线与职责保留

| 项 | 说明 |
|---|---|
| 触发时机 | RuntimeWorker._execute 根据全局开关选择执行路径；队列 claim、heartbeat 和 finish 仍按现有逻辑运行 |
| 输入 | 已认领 row、旧 RuntimeFactory 或新 Orchestrator、owner、fingerprint、MemoryInjectionPort |
| 输出 | 与旧路径一致的 Repository.finish 参数和事件；新路径 Worker 不识别 React/Codex 或 Adapter 私有结果 |
| 执行方式 | 开关关闭走原封不动的 legacy 分支；开启调用 `orchestrator.execute(...)`；monitor 继续每秒 heartbeat，失去 Lease/取消时取消 execution task |
| 失败处理 | monitor_failure 仍提交 failed/worker_lost；用户取消仍提交 cancelled；完成时仍由 Worker 调 Repository.finish，Repository 条件更新拒绝终态覆盖和过期 owner |

### FR-4 Runtime Event、AgentEvent 与 SSE 兼容

| 项 | 说明 |
|---|---|
| 触发时机 | React Runtime 发出 model/tool 事件，或 Repository 发出 run 生命周期事件时 |
| 输入 | 现有 `(kind, data)`，包括 model.started/delta/completed、tool.started/completed；AgentEvent 仅作新路径内部外层 |
| 输出 | 映射回同名 `(kind, data)` 后交给既有 Worker emit；model.delta 仍只经 Notifier 瞬态发送，其余模型/工具事件经 Repository.append 持久化；run.* 仍仅由 Repository 产生 |
| 执行方式 | 保持单次 Execution 内发射顺序、原 payload、数据库 seq 和 Last-Event-ID 语义；内部 AgentEvent 字段不直接替换现有 SSE data，不新增重复 run 终态事件 |
| 失败处理 | 映射缺字段或未知事件按受控执行失败/诊断处理，不静默改名；SSE 断连重放仍读 runtime_events，tool.replay 过滤及开放 API 脱敏逻辑不变 |

### FR-5 错误、取消、超时与终态

| 项 | 说明 |
|---|---|
| 触发时机 | 模型/工具/配置失败、run/model 超时、用户取消、Worker 失去 Lease 或结果迟到时 |
| 输入 | RuntimeFault.code、ExecutionError、cancel_requested、heartbeat 状态、ExecutionResult |
| 输出 | 既有 RunStatus 和 error_code；特别保留 agent_model_required、configuration_changed、model_round_limit、model_timeout、run_timeout、execution_error、worker_lost 等现有可观察代码 |
| 执行方式 | Adapter 归一化 Engine 错误，Orchestrator 归一化公共结果，Worker/Repository 决定 Run 终态；cancel 传播并等待清理，取消/超时不得被迟到 completed 覆盖 |
| 失败处理 | 未知异常只记安全日志并映射 execution_error；cancel 幂等且不撤销既有副作用；本阶段不新增自动重试、Fencing Token 或恢复语义 |

### FR-6 功能开关、观测与回滚

| 配置项 | 层级 | 默认值 | 说明 |
|---|---|---|---|
| `execution_orchestrator_enabled`（环境变量 `AGENT_EXECUTION_ORCHESTRATOR_ENABLED`） | 全局 Settings / 每个 API 或 Worker 进程 | `false` | false 走现有 Factory/Runtime 路径；true 走 Orchestrator；变更经配置发布和滚动重启生效，不是请求级热切换 |

| 项 | 说明 |
|---|---|
| 触发时机 | 部署、灰度、观测或回滚时 |
| 输入 | 开关值、结构化安全日志/指标（run_id、engine/protocol/adapter、path、终态、错误分类、耗时，不含 input/config/history） |
| 输出 | 可识别新旧路径及解析版本的运维证据；关闭后新 Run 全部走 legacy |
| 执行方式 | 新组件仅在开关开启时要求可解析；混合 Worker 可同时服务队列；开启时初始化/解析失败 fail fast，不静默 legacy fallback |
| 失败处理 | 出现异常将开关置 false 并滚动重启所有相关进程；在途 Run 按取消/Lease 现有规则收敛，回滚无需迁移、数据修复或客户端变更 |

## 非功能需求

- **性能**：新路径仅增加进程内 DTO/事件映射；在 Phase 0 同模型脚本的配对样本中，p95 端到端延迟增量 ≤5%，首 token 和错误率同时记录，不用 demo 数据冒充实测生产基线。
- **兼容**：默认关闭；既有 Agent 快照、RuntimeFactory 模型/工具/Memory 规则、RunView、RunStatus、HTTP 状态码、SSE 事件与回放均不变；迁移 head 保持 `0052`。
- **多租户**：tenant/business/workspace 继续来自已认证和已持久化 scope；注册解析不使用客户端提供的 Engine 或 Effective 能力；内部 history/metadata 不进入公开流。
- **可靠性**：保留现有 Lease、取消优先、终态单次提交和迟到结果保护；每次执行独立任务/队列，关闭与失败不留下 pending task。
- **可观测性**：可按 run_id 关联新旧路径、Adapter 三元组、耗时和终态；日志不包含模型密钥、工具凭据、原始输入、history 或完整异常文本。

## 验收标准

| # | 场景 | 预期 |
|---|---|---|
| AC-1 | 用相同无工具模型脚本分别走 legacy 与新路径，覆盖无 Agent 快照和已发布 Agent 快照 | output、history/dropped、模型事件、用量、终态及 error_code 一致；旧快照无需修改，React 固定为 react/native/v1 |
| AC-2 | 用相同工具调用、历史截断、summary/customer_memory、reasoning 和预算脚本对比两条路径 | 工具参数/结果、消息顺序、Memory 写回上下文、reasoning 不出现在可见输出、预算错误均等价 |
| AC-3 | 开关开启后从提交 Run 到完成检查调用链，并注入另一个注册 Adapter | Run 经注册中心和 Orchestrator 完成；Worker 不调用具体 Engine，新增 Adapter 无需改 Worker 核心分支 |
| AC-4 | 对比新旧路径内部与开放 SSE：持久模型/工具事件、瞬态 delta、run 终态、Last-Event-ID、tool.replay 和敏感字段 | 事件名/顺序/payload/seq/回放/心跳行为等价；delta 不落库；无重复终态、内部 AgentEvent 或 history/engine_metadata 泄露 |
| AC-5 | 注入配置缺失、模型超时、轮数/工具预算、非法模型响应及未知异常 | Run 终态与既有 error_code 一致，新路径不把错误统一吞成 execution_error；日志和 API 不含原始敏感异常 |
| AC-6 | 在执行中取消并同时释放成功结果，重复取消后读取 Run 和事件 | Adapter 取消完成清理；Run 最终 cancelled，无 output/迟到 completed，重复 cancel 安全，取消事件语义与旧路径一致 |
| AC-7 | 分别触发 run_timeout、model_timeout、Lease lost 和过期 Worker 迟到提交 | 分别保持 failed/run_timeout、failed/model_timeout、failed/worker_lost；Repository 拒绝过期/迟到成功，终态事件唯一 |
| AC-8 | 默认启动、显式开启、混合新旧 Worker 执行后关闭并滚动重启 | 默认全走 legacy；开启全走编排器；混合期间结果等价；回滚后新 Run 全走 legacy，开启时解析失败不静默回退 |
| AC-9 | 检查公共 API/Agent 配置/数据库 diff、观测字段与迁移 head，并运行现有回归 | 无公共 schema 和迁移变更，head 为 `0052`；日志可追踪 path/三元组/终态且无敏感数据，现有测试全绿 |
