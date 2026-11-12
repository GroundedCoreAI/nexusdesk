# Phase 2 · React Provider 与执行编排器 — 需求文档

> 状态：本地 T2～T11 与 R17 live 验证已完成，R18 生产修复及聚焦验证已完成，详见 06/07 及相应附录；R18 最小 live on/off 已完成；总体仍有条件通过
> 创建：2026-11-02
> 修订：2026-11-12（R18 与当前状态统一；设计期内容保留为历史计划）
> 依据：`docs/architecture/agent-execution-platform-v2.md` 第 4～7、12、14～17 节；Phase 0 `baseline/run-lifecycle-events.md`；Phase 1（FR-1～FR-6，代码经 merge `0a6c4b5` 合入 integration，不是人工验收结论）；`01-business-goals.md`（G1～G4）；`08-implementation-breakdown.md`（R1～R18）

## 用户故事

**US-1（存量租户用户）**：作为现有 Agent 的用户，我希望内部重构不改变 Agent 配置和客户端，使回复、事件、取消和终态行为保持一致。

**US-2（平台开发者）**：作为平台开发者，我希望 React 通过通用 Adapter 与编排器运行，使后续 Engine 不必修改 Worker 核心逻辑。

**US-3（平台运维）**：作为平台运维，我希望新路径默认关闭、可灰度、可回退，使出现问题时能恢复旧执行路径而无需数据库操作。

**US-4（QA/SRE）**：作为 QA/SRE，我希望比较新旧输出、事件、错误和终态，使可复现证据决定是否发生迁移回归。

## 功能需求

### FR-1 React Engine Adapter

| 项目 | 说明 |
|---|---|
| 触发 | 新路径编排器把已 claim Run 解析到固定 `react/native/v1` 身份并启动 Adapter |
| 输入 | Phase 1 不变的 ExecutionRequest，加上私有 ExecutionContext（同一 claimed row、history、summary/customer_memory、trace/timeout 等）；`worker_emit` 是 Worker→Orchestrator 的独立参数，不进入 Context/Adapter/RuntimeFactory；RuntimeEngine 仍由现有 RuntimeFactory 构造 |
| 身份与能力 | ExecutionContext 私有边界按 R16 受控规范化 Execution UUID：精确 stdlib UUID 原样返回并保持对象身份；UUID 子类（如 asyncpg 返回类型）经 `UUID(str(value))` 等受控值转换生成精确 stdlib UUID；`row.id` 与传入 `execution_id` 分别规范化后以 `==` 做值相等检查，不得用 `is`。公共 `ExecutionRequest.execution_id` 必须为精确 stdlib UUID 且值直接等于 claimed row ID；临时 canonical parse 不属于公共字符串化。Context 保留同一原 claimed Mapping，原 `row.id` 不复制、替换或改写，RuntimeFactory 继续接收原 row。字符串、整数、None、伪造非 UUID 和值不匹配均安全拒绝；恶意子类 `__str__`/描述符抛出的普通异常转为安全静态 `INVALID_REQUEST`，控制流异常原样重抛。有快照严格解析 `config.agent.id` 真实 UUID，缺失/畸形/nil 安全失败；仅无快照 React legacy base_runtime 可用 `UUID(int=0)` 作为匿名未绑定内部哨兵，不得借 Run/conversation UUID。Adapter 身份 react/native/v1；streaming/cancellation/tool_calling/native_events=true，其余不支持能力=false |
| 输出 | 完整五方法和安全公共 ExecutionResult；私有 ExecutionOutcome 显式携带 output、history、dropped、legacy error_code、非 optional usage 等私有值，history/dropped 不藏在公共 engine_metadata。ReactAdapter 另实现 Core 私有 `async collect_outcome(handle)`，复用公共 `collect_result` 的同一 terminal/no-stream/collector/cancellation 路径并返回内部已发布 Outcome；该入口不进入 Phase 1 公共协议。usage 不得为 None；React v1 当前 Runtime 只返回 output/history/dropped，无聚合输入时公共 Result 与私有 Outcome usage 都为 `{}`，不是既有聚合或伪造零 token |
| 执行 | Registry factory 保持同步、零参、fresh-instance；应用在同步无 await 段把 ContextVar 捕获到新 ReactAdapter。Adapter 私有 `runtime_emit` 同时传给 `RuntimeFactory.for_run(row, runtime_emit)` 和 `runtime.run(..., runtime_emit, ...)`，只做 `(kind,data)→AgentEvent→React 私有流`，不得直接写 Repository/Notifier。runner 内异步构造 Runtime，每实例一个 active execution，不重写 ReAct |
| 失败处理 | 缺失/错误 Context、重复 start、RuntimeFault、TimeoutError、未知异常按显式安全矩阵处理。`agent_model_required` 在 Adapter 生命周期保留 legacy code，不吞成 `adapter_factory_failed`；开启路径失败不得静默回退 legacy |

### FR-2 Execution Orchestrator

| 项目 | 说明 |
|---|---|
| 触发 | Worker 在开关开启时 claim Run 并校验配置 fingerprint 后 |
| 输入 | Claimed row、可信 tenant/conversation/agent 上下文、独立 `worker_emit`（唯一沿用旧 Worker 写 Repository/Notifier 的回调）和已渲染 Memory；Core 不得 import applications/business |
| 输出 | ExecutionOutcome（status、output、history、dropped、legacy error_code、非 optional usage 等）；每次执行独立 Adapter/Handle，不共享 row、history、worker_emit、runtime_emit、queue 或 runner |
| 执行 | 构造 Request→固定选择 react/native/v1→同步无 await 段 set ContextVar、registry.resolve、finally reset→start→同步 claim stream 并打开首发 gate→runner 才可经私有 runtime_emit 发射→从公共流取事件后 `await worker_emit`，成功再 `acknowledge(event)`→完整 drain→React 仅私有 `collect_outcome` 一次，或无 Outcome 协议的 LocalTest 公共 `collect_result→ExecutionOutcome.from_result` 确定性回退；Worker 最后 finish，使 run.* 终帧最后。正常编排不依赖 collect/stream 竞态 |
| 协议检测 | Core 私有 runtime-checkable `AcknowledgingEventStream` 与 `OutcomeCollectingAdapter`/helper 不 import React，验证真实异步能力且描述符异常 fail closed；React 必须 worker_emit 成功后 ack，LocalTest 无私有协议，明确 Adapter 内部 `yield = delivery`，Orchestrator 仍 await worker_emit 但无额外 ack。React 私有收集不得经 lossy fallback；LocalTest fallback 只读公共 error code：`execution_timeout→run_timeout`，其余 failed 一律 `execution_error`，completed 默认 history/dropped 空列表，cancelled 无 code。任何 Factory/PlatformTools/RuntimeEngine 事件不得直接触达 worker_emit；异常走 abort/aclose 清理 |
| 失败处理 | Registry/version/Context/Adapter 各阶段失败安全归一化并清理，无静默 fallback；调用方及 Repository append 的 CancelledError 清理后重抛。生产 selector 固定三元组，LocalTest 使用独立 Registry/selector、同一 Orchestrator/Worker；无 latest、fallback、客户端 Engine 选择 |

### FR-3 Worker 集成与保留职责

| 项目 | 说明 |
|---|---|
| 触发 | RuntimeWorker._execute 根据进程启动时的全局开关选择路径；队列 claim、heartbeat、finish 沿用现有逻辑 |
| 输入 | Claimed row、legacy RuntimeFactory 或新 Orchestrator、owner、fingerprint、MemoryInjectionPort、原事件回调作为 on 路径 `worker_emit`；只在构造末尾新增 `orchestrator=None`，off 路径不变 |
| 输出 | 与 legacy 等价的 Repository.finish 参数和事件；新路径 Worker 不识别 React/Codex，私有 history/dropped 仅成功时进入 Worker Memory 完成钩子 |
| 执行 | off 走原 legacy 分支；on 调 `orchestrator.execute(context, worker_emit)`。monitor 继续 heartbeat，并在失租/取消时取消 execution task；Orchestrator 先 claim/drain stream 再 collect，Worker 最后 finish |
| 失败处理 | monitor_failure 区分用户 cancelled 与 failed/worker_lost，失租不得伪装用户取消。Repository 仍是唯一终态写者：stale/terminal/wrong-owner/expired finish 静默 no-op；stale/cancelled/expired append 抛 `asyncio.CancelledError`，不得写成 no-op 或普通 execution_error。持久层按提交顺序 first-commit-wins，reaper 行为不变 |

### FR-4 Runtime 事件、AgentEvent、React 私有流与 SSE 兼容

| 项目 | 说明 |
|---|---|
| 输入与透传 | 所有合法普通业务事件经私有 runtime_emit 以原名、相同 JSON payload 转 AgentEvent，再由 Orchestrator 经 worker_emit 还原投递，包括 knowledge.retrieved、memory_search.completed、model.delta 和扩展事件，无 allowlist；缺失/畸形字段安全 protocol_error |
| 禁止伪造 | Adapter 原始 run.*、tool.replay 为安全 protocol_error，不得到达 worker_emit；run.* 仅 Repository，tool.replay 仅 DurableToolReplayCache。model.delta 最终仍由 worker_emit 走 Notifier best-effort，无 DB seq/replay |
| AgentEvent | UUID event_id、UTC timestamp、Adapter-local 单调 sequence、source=engine_native；不改 DB event_seq/SSE ID |
| 私有结构化协议 | Core 定义 runtime-checkable `AcknowledgingEventStream`：`AsyncIterator[AgentEvent] + acknowledge(event) + abort(error)/aclose`。ack 按 execution_id/event_id 匹配当前唯一 in-flight，exactly-once；重复已结算 ack 幂等不重复扣减，错误身份/乱序 ack 安全协议失败并 abort，绝不裸 yield 自动 ack |
| React 首发与无流语义 | 不再声称等同 LocalTest。start 后首发 gate 关闭，stream_events 同步 claim 前 runner 不得向流发射；正常 start→claim stream→放行→drain→collect。单独 no-stream collector 在 never-claimed 时显式选择 React 私有 no-stream suppression 并放行，之后 stream 为空/按终态结束；cancel/aclose 同样唤醒 gate |
| 状态与背压 | 明确定义 never-claimed、claimed-active、closed、terminal；collect/stream 竞争按先到模式线性化。Condition+bounded deque 容量至少 1，仅限制 queued buffer，可另有一个 in-flight。claimed-active 满时等待；pop/yield 不是 React delivery，只有 worker_emit 成功后 ack 才减少 undelivered |
| 终态与关闭 | runner 正常结束先存 pending result，producer finished 且 queued+in-flight undelivered=0 后发布唯一 Result，不以未关闭的空 claimed stream 阻塞 collect。terminal 时活跃流 drain 后结束；closed 后不可再次 claim；never-claimed 的 no-stream/cancel terminal 后首次 stream 为空且无 replay。显式 cancel/aclose/普通 emit 失败抑制迟到事件/结果并清理 |
| SSE | 保留内部/Open Last-Event-ID、after、200+ drain、无 ID delta 不重放、隐藏 tool.replay 但推进 cursor、公共字段过滤；内部 Last-Event-ID 由 handler 手工解析，非法或超出 `[0,2147483647]` 返回 `400 / invalid_last_event_id`；内部 after 及 Open after/Last-Event-ID 由 FastAPI typed Query/Header 校验，类型或范围错误返回 422；合法游标以 `max(after,last_id)` 合并并严格重放 `seq>after`，不得互换 400/422；AgentEvent/Outcome/Context 不增 HTTP/SSE 字段，路由、schema、状态码和错误体均不变 |

### FR-5 错误、取消、超时与终态

| 项目 | 说明 |
|---|---|
| 输入 | RuntimeFault.code、ExecutionError、cancel_requested、heartbeat、ExecutionResult、runtime_emit/worker_emit/stream/append/Notifier 异常 |
| 输出 | 公共错误仅 ExecutionErrorCode 与静态 message，私有 Outcome 保留任意 RuntimeFault 原始 code；既有 agent_model_required、configuration_changed、Gateway/Domain code、model/run timeout、execution_error、worker_lost 等可观测 code 不丢 |
| 完整来源矩阵 | 除 Engine/Factory 字面错误外，覆盖 Phase 0 基线的 model_resource_not_found/disabled、model_profile_version_not_found、model_input_too_large、model_tools_not_supported、model_provider_unavailable/rate_limited/provider_rejected/transport_error、content_blocked_input/output、gateway_concurrency_exceeded/request_quota_exceeded、model_credential_unavailable、model_response_too_large、model_stream_interrupted；model_stream_not_supported 当前走 fallback。完整公共映射见 03 §6.1 |
| 未知 code 与异常 | 所有 RuntimeFault 即使未预知也在私有 legacy_error_code 保留原始 code，公共按已知表或 internal_error 安全 fallback，不复制 Provider/Domain 文本；未知普通异常为公共 internal_error + legacy execution_error。model_timeout/run_timeout 分离 |
| append 控制流 | stale/cancelled/expired `worker_emit→Repository.append` 的 asyncio.CancelledError 不 ack、不持久化事件，Orchestrator/Adapter abort/aclose 清理后重抛，由原终态/monitor 决定结果，不归为普通 execution_error；Notifier 已吞掉的指定 PG/OS delta 失败仍正常 ack |
| 取消 | 显式 adapter.cancel 在 Adapter 内部 first-terminal-wins，得无 output/error cancelled Result；已完成 Result 不被追溯取消。普通 stream/worker_emit 失败为 failed 非 cancelled；单独 no-stream collector 取消停止执行，共享 collectors shield；调用方 CancelledError 清理后重抛 |
| 持久化竞态 | Run 持久层按提交顺序 first-commit-wins，不是无条件 cancel 优先：finish/reaper 先提交则 cancel no-op；cancel 先提交则 late finish 不改写。覆盖 cancelled-with-worker_lost/queue_timeout reaper 变体；无自动重试、Fencing Token 或副作用回滚新语义 |
| 清理 | 所有 owned tasks 完成；仅承诺协作式协程在外层 timeout 下有界 drain，不承诺强杀非协作协程 |

### FR-6 功能开关、组合、观测与回滚

| 配置 | 层级 | 默认值 | 说明 |
|---|---|---|---|
| `execution_orchestrator_enabled`（环境变量 `AGENT_EXECUTION_ORCHESTRATOR_ENABLED`） | Core Settings / 每个 API 或 Worker 进程 | `false` | false 使用既有 Factory/Runtime；true 使用 Orchestrator；进程启动/滚动重启生效，非请求热切换。两个 env 示例和必要 compose 仅做插值 |

| 项目 | 说明 |
|---|---|
| 组合 | 共享组合根注册 EngineDescriptor(react)、ProtocolDescriptor(native)、AdapterDescriptor(react/native/v1)，可选注入 orchestrator。flag 排除在 runtime-composition fingerprint 外，off API/on Worker 与混合 Worker fingerprint 相同 |
| 观测 | 安全结构化日志/trace 可按 run_id 关联 path、tuple、终态、错误类别和耗时；metrics 仅低基数 path/tuple/status/error 标签，run_id 不进指标，不记录 input/config/history/凭据/nil Agent |
| 灰度与回滚 | 记录存量 queued/running/terminal 行、混合 claim、在途执行和回滚；异常时所有进程 false 并滚动重启，开启失败不静默回退，Repository 契约不变，无迁移/数据修复/客户端变更 |

## 非功能需求

- **性能**：新路径只增加进程内 DTO/事件映射。真实等价外部环境按 05 §4 方法至少 30 matched pairs、5 组 warm-up 不计样本，目标 nearest-rank p95 端到端延迟增幅 ≤5%；首 token、原始开销和错误率独立报告。test double 只能用于功能，不得宣称生产性能；无真实环境性能子指标为 `pending_env`，但不阻止全绿功能测试进入最多“有条件通过”的验收。
- **兼容性**：Phase 1 DTO、Registries、LocalTest、RuntimeEngine/Factory、runtime hooks、Repository、API/SSE 行为不变。不新增/修改迁移、ORM、公共 HTTP/SSE schema、前端；测试动态核验 heads、空库 upgrade、迁移目录零漂移。
- **多租户与身份**：tenant/business/workspace 继续来自可信 scope；nil 不进入 selector、授权、tenant/credential/Agent 查询、DB、日志、指标或公共数据，客户端不能选 Engine 或提权。
- **可靠性**：保留 Lease、Adapter first-terminal-wins、Run 持久层 first-commit-wins、迟到保护及 append/finish 不同控制流；首发 gate、ack identity、取消/关闭竞态用确定性测试覆盖，关闭后无 pending owned task。
- **观测与安全**：公共 Result/errors 仅安全枚举和静态文本，model.completed usage 原样保留；私有 history/dropped/Outcome/Context 和 runtime_emit/worker_emit 不进入 HTTP/SSE/public engine_metadata，日志和错误不泄露秘密或原始异常。
- **测试证据**：真实 PostgreSQL 使用独立新建 `pgvector/pgvector:pg17` 容器、新 DB/卷；连接串仅仓库外受限 env，经 TEST_DATABASE_URL/AGENT_DATABASE_URL 注入，不打印。本地、CI、人工证据分开，功能出口与性能子指标分开判定。

## 验收标准

| 编号 | 场景 | 预期 |
|---|---|---|
| AC-1 | 新旧路径运行相同串行无工具脚本，覆盖无 Agent 快照与已发布 Agent 快照 | R16 的精确 stdlib UUID、私有受控规范化、值相等及原 claimed row 保留正确，真实 Agent/受限 nil 正确；output、成功 history/dropped、稳定模型事件、非 optional usage、终态和 error_code 按 03 对等；React v1 无聚合输入 usage={}，旧快照零修改，固定 react/native/v1 |
| AC-2 | 相同工具、并行工具、历史截断、summary/customer_memory、reasoning 与预算脚本对比 | call_id 集合、局部 started→completed、模型轮边界、参数/结果、消息顺序、Memory 完成上下文、reasoning 不可见性和预算错误等价；并行分支不要求绝对 seq/全局顺序相同 |
| AC-3 | 开启后检查完整调用链、双 emit、ContextVar、首发握手和 LocalTest 独立 Registry/selector | RuntimeFactory 与 RuntimeEngine 只收到同一私有 runtime_emit，Orchestrator 独占 worker_emit；start→claim→放行无首事件丢失；Worker 无 Engine 分支、Core 无反向依赖，并发/嵌套/异常安全，多 Run 隔离，LocalTest 无协议且 yield=delivery |
| AC-4 | 对比内部/Open SSE、普通/扩展事件、结构化 ack、背压、无流/closed/terminal 和重放 | 合法业务事件原名同 payload；spy 证明事件不直达 worker_emit；ack identity/exactly-once/abort 正确，伪造 run.* 不到 worker_emit；seq/replay/delta/终帧/200+ drain 按 03，内部手工 Last-Event-ID 非法/越界为 400/invalid_last_event_id，内部 after 与 Open after/Last-Event-ID 的 typed 类型/范围错误为 422，合法游标继续 max(after,last_id) 并严格 seq>after，路由/schema/状态码/错误体不变；无重复终态、私有数据泄漏或悬挂任务 |
| AC-5 | 注入缺配置、全部 Phase 0 Gateway/Domain/Engine 错误、未来未知 RuntimeFault code、stream/worker_emit/append 和未知异常 | 公共错误安全，私有/Run legacy code 全保留，未来 code 安全 fallback；append CancelledError 不 ack、不持久化、清理后重抛且不改原终态，普通 emit 失败非 cancelled，model/run timeout 分离，无敏感原文 |
| AC-6 | 执行中取消并释放成功，覆盖首发 gate、阻塞生产/消费、aclose、no-stream/shared collectors、迟到事件及两种持久提交顺序 | Adapter 显式取消 first-terminal-wins 且无 output/error；Run 持久层 first-commit-wins，finish 先提交 cancel no-op，cancel 先提交 late finish 不改写；调用方取消重抛，无第二终态/pending task |
| AC-7 | 分别触发 run_timeout、model_timeout、Lease lost、过期 Worker 迟到 finish/append 和 reaper 变体 | 保留 failed/run_timeout、failed/model_timeout、failed/worker_lost；finish stale no-op、append CancelledError；reaper cancelled-with-worker_lost/queue_timeout 保持，失租不伪装用户取消，终态唯一 |
| AC-8 | 默认启动、显式开启、off API/on Worker、混合 Worker，再关闭滚动重启；正式验收后才验证新示例种子 | 默认仅 legacy、开启仅 Orchestrator，fingerprint 不变；混合结果等价、回滚仅 legacy，开启失败不兜底。T10/T11 仅在正式验收后执行并通过 quickstart off/on、内嵌 Worker、双 SSE 和 off 回滚 |
| AC-9 | 动态检查 API/Agent 配置/数据库/前端 diff、迁移、观测、功能回归与性能证据边界 | 无迁移/ORM/公共 schema/前端变化，heads/upgrade/目录零漂移；日志/trace 可追踪，指标低基数无敏感/nil；功能用例全部实际通过，性能方法可复现，真实外部环境不足仅性能子指标 pending_env，T9 最多有条件通过 |
