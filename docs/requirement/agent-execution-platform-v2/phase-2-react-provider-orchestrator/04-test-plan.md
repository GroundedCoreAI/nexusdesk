# Phase 2 · React Provider 与执行编排器 — 测试方案

> 状态：本地 T2～T11 与 R17 live 验证已完成，R18 生产修复及聚焦验证已完成，详见 06/07 及相应附录；R18 最小 live on/off 已完成；总体仍有条件通过
> 创建：2026-11-02
> 修订：2026-11-12（R18 与当前状态统一；设计期内容保留为历史计划）
> 依据：`02-requirements.md`（FR-1～FR-6、AC-1～AC-9）、`03-technical-design.md`（R1～R12 对应设计）、`08-implementation-breakdown.md`（R13/R14/R15/R16/R17/R18 及 T6/T8/T11）

## 1. 测试范围与原则

**范围**：ReactAdapter 完整契约与私有 ack-aware 流、私有 Outcome 收集及无协议 LocalTest 确定性回退、worker_emit/runtime_emit 双 emit 隔离、首发 gate 与 no-stream 状态机、Execution Orchestrator、Worker 新旧路径、同步 ContextVar/异步 Runtime 装配、开放事件/SSE 兼容、错误/取消/超时/Lease、真实 Memory、全局开关、混合部署和回滚；不包含外部 Engine 或 Runtime Host。

**原则**：

1. **对等规则明确**：串行确定性脚本严格比较 output/error/usage/history/dropped/稳定 payload/顺序/每 Run seq/终帧/重放；并行工具按 call_id 集合、局部偏序和模型轮边界比较，仅 canonicalize 03 §7.3 的路径。
2. **yield 不等于 delivery**：React 测试 harness 对公共流显式执行 `anext→await worker_emit→acknowledge`，并以 Core 私有 `AcknowledgingEventStream` 验证 identity/exactly-once/abort；LocalTest 无私有协议，保留 claim 前入队、terminal 丢弃和 yield=delivery，不与 React no-stream 混称。
3. **双 emit 单向边界**：for_run/run 只收到同一私有 runtime_emit；Factory/PlatformTools/RuntimeEngine 不得触达 worker_emit，Orchestrator 从公共流取出后才调用唯一 worker_emit，spy 逐段记录顺序和次数。
4. **开关与指纹必测**：默认/显式 off 走旧路径；on 失败不兜底；开关不进入 fingerprint，off API/on Worker 与混合 Worker 不因此 configuration_changed。
5. **双 SSE 与真实 PG 必测**：真实 Repository 决定取消/Lease/成功竞争及 first-commit-wins；内部/Open 分别验证持久事件、瞬态 delta、游标重放、200+ 排空、tool.replay 和脱敏。
6. **确定性异步测试**：使用 Event/gate/手动时钟控制；外层 timeout 只防悬挂，真实 sleep 不决定结果。每个结束路径断言所有 owned/test tasks 已 await/done。
7. **私有 Outcome 不丢原 code**：验证 `OutcomeCollectingAdapter` 真异步与描述符 fail-closed 检测；React 只私有收集一次并复用公共 collector 路径，completed/failed/cancelled 保留各自语义；LocalTest 仅公共 collect 后按固定 error code 回退，严禁 React 经 lossy fallback 或 Orchestrator 访问 `_execution`。
8. **证据不预写**：T8 的 06 对每条主测试独立记录；T11 的新增种子用例仅在实际执行后追加，不得把未执行、skip 或环境缺失写成通过。

## 2. 测试环境与数据构造

| 环境 | 用途与硬性要求 |
|---|---|
| 单测（假 Registry/Adapter/Runtime、Event/gate） | Request/Outcome、React 五方法、ContextVar、映射、背压、Worker 分支、错误和清理，无需 DB |
| 独立 Docker PostgreSQL | 新建 `pgvector/pgvector:pg17` 容器、全新专用 DB 和卷，不复用 Phase 0/1 容器；空库 `alembic upgrade head`，验证 claim/heartbeat/finish/cancel/reap、事件序号与 Memory 事务 |
| 凭据注入 | 连接串仅存在仓库外权限受限（0600）env 文件，经 `TEST_DATABASE_URL` 与 `AGENT_DATABASE_URL` 注入；日志、命令输出、报告均不得打印连接串或秘密 |
| mock/demo 模型与 MockTransport | 可编程文本、并行工具、超时、非法响应、usage 与扩展事件；真实 HTTP 工具路径可重复 |
| ASGI 内部与开放 API | 内部 `/api/v1/runs/{id}/events` 和开放平台 SSE/回放/公共字段过滤 |
| 双 Worker 配置组 | 同库混合 legacy/orchestrator、off API/on Worker、存量行和滚动回滚演练 |
| quickstart（仅 T11） | 正式验收后新增示例种子的默认 off、显式 on、内嵌 Worker、双 SSE、路径日志和 off 回滚，不新增服务 |

**数据构造**：复用 `test_runtime_postgres.py` 的专用租户、RunRepository 和 BusinessRuntimePersistenceHooks；新旧路径使用独立但等价 fixture/脚本。Agent 快照、summary/customer_memory/history 直接构造；Lease/queue 时间直接改库；不使用生产凭据或客户数据。迁移 head 在当次环境动态记录；本次设计观测 0057 不是永久断言。

## 3. 单元测试（T2～T6）

| 编号 | 用例 | 预期 | 溯源 |
|---|---|---|---|
| P2-UT-01 | claimed row→ExecutionContext→ExecutionRequest、UUID 规范化与 Agent 身份 | 精确 stdlib UUID 经私有规范化原样返回并保持原对象身份；UUID 子类经 `UUID(str(value))` 等受控值转换生成精确 stdlib UUID；`row.id` 与传入 execution_id 分别规范化后以 `==` 检查值相等而非 `is`，公共 Request.execution_id 为精确 stdlib UUID 且值直接等于 row.id。`context.row is claimed_row`、RuntimeFactory 收到同一原 row，原 row.id 保持同一对象且未复制/替换/改写。字符串、整数、None、伪造非 UUID 和值不匹配均安全静态 `INVALID_REQUEST`；恶意 UUID 子类的 `__str__` 与描述符普通异常转为安全静态 `INVALID_REQUEST` 且不泄露原异常，`asyncio.CancelledError` 等控制流异常原样重抛。有快照严格解析 config.agent.id，缺失/畸形/nil 安全失败；仅无快照 React legacy base_runtime 可用内部 UUID(int=0)，不得借 Run/conversation UUID；固定 react/native/v1 | FR-1/2、AC-1、R2/R8/R16 |
| P2-UT-02 | ReactAdapter 身份、能力和 start 成功 | 属性 react/native/v1；Handle UUID 匹配；streaming/cancellation/tool_calling/native_events=true，其余 false；fresh instance、单 active execution、重复 start 安全失败 | FR-1、AC-3、R5 |
| P2-UT-03 | React 双 emit、首发握手与 start→stream→collect 成功 | spy 证明 for_run/run 在同一 runner 中以同 row、同一私有 runtime_emit 各调用一次，ExecutionContext 不含任何 emit，worker_emit 仅由 Orchestrator 持有；start→同步 claim stream 才放行 runner，首个事件不丢，公共 yield→await worker_emit→ack 顺序正确；output/usage 和私有 history/dropped 完整，completed Result 唯一 | FR-1/2/4、AC-1/3/4、R3/R4/R6 |
| P2-UT-04 | 空输出、工具循环、dropped 与 usage 打包 | 与原 Runtime 返回一致；history/dropped 仅在私有 Outcome 且只成功时给 Memory；usage 非 optional 且不得为 None，React v1 无聚合输入时公共 Result 与私有 Outcome 都为 `{}`，不是既有聚合或零 token；model.completed usage 逐字保留，公共 engine_metadata 不增字段 | FR-1、AC-2/9、R4 |
| P2-UT-05 | 双 emit 事件 spy、普通/扩展映射与伪造事件隔离 | 分别记录 runtime_emit、公共 yield、worker_emit、Repository/Notifier 和 ack；model.delta、knowledge.retrieved、memory_search.completed、扩展事件原名同 JSON payload 且只经公共流后到 worker_emit 一次，delta 最终 Notifier-only；伪造 run.*/tool.replay 和畸形事件在 worker_emit 前安全 protocol_error，Factory/PlatformTools/RuntimeEngine 无直达路径；AgentEvent UUID/UTC/局部 seq/source 正确 | FR-4、AC-4、R6 |
| P2-UT-06 | Phase 0 全来源 RuntimeFault、未来未知 code、timeout 与异常映射 | 逐项覆盖 03 §6.1 的 Engine/Factory/Gateway/Domain 来源：model_resource_not_found/disabled、model_profile_version_not_found、model_input_too_large、model_tools_not_supported、model_provider_unavailable/model_rate_limited/model_provider_rejected/model_transport_error、content_blocked_input/output、gateway_concurrency_exceeded/request_quota_exceeded、model_credential_unavailable、model_response_too_large、model_stream_interrupted 及其余表项；model_stream_not_supported 当前 fallback；公共仅安全 code/静态 message，所有已知/未来未知 RuntimeFault 的私有 legacy_error_code 逐字保留，未来 code 公共 internal_error 安全 fallback；未知普通异常 internal_error/execution_error，model/run timeout 不混淆，无敏感原文 | FR-5、AC-5/7、R4/R10 |
| P2-UT-07 | React cancel、aclose、首发 gate、竞争与清理 | 显式 cancel 是 Adapter 内部 first-terminal-wins，幂等得无 output/error cancelled，已完成 Result 不追溯取消；首发 gate、阻塞 put/get 被唤醒，runner 被取消并 drain，迟到事件/成功抑制；aclose 同等清理且 closed 不可 replay，无 pending task | FR-1/4/5、AC-6、R6/R10 |
| P2-UT-08 | Orchestrator 有效解析及未知版本/未注册/禁用组合 | 有效组合创建独立 Adapter；无效组合明确失败，无 latest/旧路径/其他 Engine 回退；生产 selector 不可被请求覆盖 | FR-2、AC-3/8、R8 |
| P2-UT-09 | Orchestrator ack/Outcome 协议检测及 start/stream/collect/worker_emit 各阶段异常 | React runtime-checkable `AcknowledgingEventStream` 被检测并仅在 worker_emit 成功后 ack；`OutcomeCollectingAdapter` 验证真实 async 且描述符/同步假能力 fail closed。React 仅 `collect_outcome` 一次，覆盖 completed 真实 history/dropped、failed 原 legacy code（含未知 RuntimeFault）、cancelled 无 code、Handle/共享与单独 collector 取消一致，公共 Result 无私有字段且不访问 `_execution`。LocalTest 无私有协议、yield=delivery、无额外 ack，仅公共 collect 后转 Outcome：completed 空 history/dropped，`execution_timeout→run_timeout`，其余 failed→execution_error，cancelled 无 code。每阶段经 abort/aclose 清理任务/迭代器，普通 stream/worker_emit 为 failed 非 cancelled；append CancelledError 不 ack、清理后重抛；drain→collect→Worker finish 顺序唯一，无第二终态 | FR-2/5、AC-3/5、R4/R6/R14 |
| P2-UT-10 | Worker 开关 false/true 与 fingerprint | false 仅 legacy，true 仅 Orchestrator；configuration_changed 行为一致；开关排除在 fingerprint 外，off API/on Worker 不冲突 | FR-3/6、AC-8、R9 |
| P2-UT-11 | Worker Outcome→finish 参数映射 | completed/failed/cancelled、output/error_code 正确；history/dropped 仅成功传给 Memory；Worker 不读取 Engine 私有类型，Repository finish 唯一 | FR-3、AC-3、R4/R10 |
| P2-UT-12 | Memory summary/customer_memory/dropped 新旧传递 | 输入渲染及成功 memory_context 参数一致；失败/取消不错误写回，history/dropped 不丢失或泄露 | FR-1/3、AC-2、R4 |
| P2-UT-13 | Settings 默认与环境变量覆盖 | 默认 false；AGENT_EXECUTION_ORCHESTRATOR_ENABLED true/false 正确解析，非法值拒绝；仅进程启动生效 | FR-6、AC-8、R9 |
| P2-UT-14 | 依赖方向与公开序列化静态检查 | Core 不 import applications/business；Worker/Orchestrator 不 import RuntimeEngine；RunView/SSE 不含 history、process_id、Outcome/Context 或新增 engine_metadata；私有 Outcome Protocol 不进入 Phase 1 公共 Adapter/contracts；T2/T3/T4 累计精确模块集合同步且依赖门禁不弱化 | FR-2/4、AC-3/9、R3/R4/R13/R14 |
| P2-UT-15 | ContextVar 并发、嵌套与异常复位 | task 并发隔离；嵌套 set/reset 恢复外层；resolve/工厂异常 finally reset；缺失/错误/覆盖 Context 安全失败，Adapter 创建后不读 ContextVar | FR-1/2、AC-3、R3 |
| P2-UT-16 | 多 Run fresh 实例与私有状态隔离 | 同时执行不共享 claimed row/history/worker_emit/runtime_emit/queue/runner/result/首发 gate；每次 stream/ack 只能匹配本 execution，agent_model_required 在 Adapter 生命周期保留 code，不吞成 adapter_factory_failed | FR-1/2/4、AC-1/3/4、R3/R4/R6 |
| P2-UT-17 | 容量 1 队列、慢 worker_emit 与结构化 ack 协议 | 多事件 queued 不超容量且至多一个 in-flight；裸 yield 不减少 undelivered，只有成功 await worker_emit 后按 execution_id/event_id 匹配当前 in-flight 的 ack exactly-once 扣减并唤醒 producer；重复已结算 ack 幂等，错误身份、乱序、无 in-flight、跨 execution ack 安全 protocol_error 并 abort，绝不自动 ack | FR-4、AC-4、R6 |
| P2-UT-18 | React never-claimed/claimed-active/closed/terminal、no-stream 与终态发布门 | start 后未同步 claim 或未显式 no-stream 选择时首发被 gate 阻挡；立即 stream 首事件不丢，单独 no-stream collector 显式开启 suppression 并放行、之后 stream 为空且无 replay，closed/terminal 后 stream 按 03 §4.3 安全结束或拒绝；正常 runner 先存 pending result，producer finished 且 queued+in-flight undelivered=0 后唯一发布，空闲未关闭 claimed stream 不阻塞 collect，cancel/aclose 唤醒 gate；不得类比 LocalTest | FR-4、AC-4/6、R6 |
| P2-UT-19 | 先到 collect/stream、并发/重复 collect 与 no-stream collector 取消 | 首次选择在同一状态锁下先到先赢，正常编排不依赖竞态；collectors 得相等唯一 Result；单独 no-stream collector 取消唤醒 gate 并停止执行，共享 collectors shield；调用方 CancelledError 清理后重抛 | FR-1/4/5、AC-6、R5/R6 |
| P2-UT-20 | runner stream/protocol failure、abort/aclose 与 Notifier 异常边界 | runner 错误安全抛给 consumer、视为 delivered 后发布 failed Result；错误 ack 走 abort，普通 emit 失败走 abort/aclose；指定 Notifier 已吞 PG/OS delta 失败正常 ack，其他异常按 emit failure，所有 owned tasks done | FR-4/5、AC-5、R6 |
| P2-UT-21 | 公共 Adapter suite 的 25 函数精确复用/排除与 React harness | 严格按 03 §4.2 清单逐项执行并留证：19 个原函数复用（其中列明的流式用例经 `anext→worker_emit→acknowledge` 包装），6 个原函数排除并使用同名目的私有替代；不得只写“适用用例”或漏测排除项。私有协议测试直接使用 raw stream，公共五方法不变；LocalTest 无私有协议且仍 yield=delivery | FR-1/4、AC-3/4、R5/R6 |
| P2-UT-22 | 串行/并行 parity 与 canonicalizer 纯函数 | 串行严格比较；并行按 call_id/模型轮偏序与 multiset；仅允许显式路径，先验证类型/nullable/非负 duration；call_id、业务 ID、参数/结果、output/error/usage 不被规范化 | FR-1/4、AC-1/2/4、R7 |
| P2-UT-23 | Worker monitor_failure、失租、stale append/finish 与持久提交顺序 | 用户取消为 cancelled，失租为 failed/worker_lost；调用方取消重抛。stale/terminal/wrong-owner/expired finish 静默 no-op；stale/cancelled/expired append 抛 `asyncio.CancelledError`，不 ack、不持久化、清理后重抛且不改原终态，不归普通 execution_error。用 gate 分别验证 finish/reaper 先提交后 cancel no-op、cancel 先提交后 late finish 不改写，并保留 cancelled-with-worker_lost/queue_timeout reaper 变体 | FR-3/5、AC-6/7、R10 |
| P2-UT-24 | 组合描述符与低基数观测 | 注册 react/native/v1 并可选注入；日志/trace 可含 run_id，metrics 无 run_id；path/tuple/status/error 标签低基数，无 nil/秘密/input/history | FR-6、AC-8/9、R9/R11 |

## 4. 集成测试（T6/T8 主测试）

| 编号 | 用例 | 预期 | 溯源 |
|---|---|---|---|
| P2-IT-01 | 无 Agent 快照固定文本模型，off/on 各跑 | 按串行规则比较 output、成功 history/dropped、模型事件及其原始 usage、run.completed 和 error_code；React v1 无聚合输入时公共 Result 与私有 Outcome usage={}，不伪造零 token；nil 只在受限内部 Request，不泄漏或查询 | AC-1、FR-1、R2/R4/R7 |
| P2-IT-02 | 已发布快照、Gateway Profile、语言与多轮工具 | 真实快照 Agent UUID；同 Profile/工具参数/消息顺序/结果/预算，回复与事件按规则等价，快照未改 | AC-1/2、R2/R7 |
| P2-IT-03 | 历史截断 + summary + customer_memory + reasoning | 注入消息顺序、dropped、成功 memory_context、reasoning 历史保留和不可见性与 legacy 一致 | AC-2、R4 |
| P2-IT-04 | 新路径完整 Run 调用链与双 emit 边界 | 仅 react/native/v1 和 Orchestrator；同步 Context 捕获且 Context 无 emit，runner 内异步 for_run/run 收到同一 runtime_emit；spy 证明 Factory/PlatformTools/RuntimeEngine 事件只进私有流，Orchestrator 从公共流取出后才 worker_emit/ack；drain 后 React 私有 collect_outcome 仅一次且无公共重复收集/`_execution` 访问；Worker 无 Engine 分支，Repository finish 仅一次 | AC-3/4、R3/R6/R8/R14 |
| P2-IT-05 | 内部 SSE 经 ASGI/FastAPI 路由验证 Last-Event-ID/after 与 200+ 排空 | 必须调用实际内部路由而非仅测 helper：手工 Last-Event-ID 的无法解析为整数或其他非法值及超出 `[0,2147483647]` 均返回 `400 / invalid_last_event_id`，typed after 的类型/范围错误返回 422；合法 after/header 以 `max(after,last_id)` 合并并严格只重放 `seq>after`。另按 03 §7 比较持久事件名/seq/data/顺序；delta 无 id/不落库/不重放；终帧最后，无重复 run 事件 | AC-4、R6/R7/R15 |
| P2-IT-06 | Open SSE 经 ASGI/FastAPI 路由验证 typed 游标、tool.replay 与脱敏 | 必须调用实际 Open 路由而非仅测 helper：typed after 与 Last-Event-ID 的类型错误或超出 `[0,2147483647]` 均返回 422，不得写成 400；合法 after/header 以 `max(after,last_id)` 合并并严格只重放 `seq>after`。脱敏/过滤、状态码和错误体不变；tool.replay 隐藏 payload 但推进 cursor；无私有 metadata/gateway 内部字段 | AC-4/9、R6/R7/R15 |
| P2-IT-07 | Phase 0 Gateway/Domain/Engine 错误、未来未知 RuntimeFault 与普通异常 | 覆盖 03 §6.1 全来源代表及一个未来未知 code；RunView/持久 run.failed 的原始 legacy code 一致，公共已知映射或 internal_error 安全 fallback，未知普通异常 internal_error/execution_error，日志/API 无敏感原文 | AC-5、R4 |
| P2-IT-08 | 模型等待时取消后释放成功，重复 cancel | Adapter/模型任务实际收到取消并清理；最终 cancelled、output 空，无迟到 run.completed/第二终态 | AC-6、R6/R10 |
| P2-IT-09 | 真实 PG cancel/finish/reaper 两种提交顺序 | Adapter 显式取消仍是内部 first-terminal-wins；Run 持久层按提交顺序 first-commit-wins：finish/reaper 先提交则 cancel no-op，cancel 先提交则 late finish 不改写；覆盖 reaper cancelled-with-worker_lost/queue_timeout，事件序列无第二终态 | AC-6/7、R10 |
| P2-IT-10 | 分别构造 model_timeout、run_timeout | 分别 failed/model_timeout、failed/run_timeout，与 legacy 相同；任务清理且无自动重试 | AC-7、R4/R10 |
| P2-IT-11 | Lease 过期/reap 后旧 Worker 迟到 finish/append | heartbeat lost，最终 failed/worker_lost 或既有 cancelled-with-worker_lost/queue_timeout 变体；失租不伪装用户取消。stale finish 静默 no-op、不写 output；stale/cancelled/expired append 不持久化事件并抛 CancelledError，Orchestrator 不 ack、abort/aclose 后重抛，不改原终态且不归普通 execution_error | AC-5/7、R10 |
| P2-IT-12 | 默认 off、显式 on、混合 Worker、off 滚动重启 | off/on 路径正确且 fingerprint 不变；混合结果等价；回滚后新 Run 全 legacy，在途 Run 按现有规则收敛 | AC-8、R9 |
| P2-IT-13 | on 状态删除/禁用注册项后启动或执行 | fail fast 并产生安全诊断；绝不静默 legacy 或选择其他版本 | AC-8、R8/R9 |
| P2-IT-14 | LocalTest 独立 Registry/selector 经同一 Orchestrator/Worker | 不改 Worker 核心执行公共成功/失败/取消；LocalTest yield=delivery，不与生产 react Registry 混用；无私有 Outcome 协议时公共 collect 后 completed 默认空 history/dropped、timeout 特判 run_timeout、其余 failed 为 execution_error、cancelled 无 code，不读取 message/details | AC-3、R5/R8/R14 |
| P2-IT-15 | 并行工具与扩展业务事件新旧对比 | 按 call_id 对齐 started/completed 集合与局部偏序、模型轮边界；无 call_id 并行事件按轮 multiset；稳定 payload/usage 不变，原始延迟另存 | AC-2/4、R6/R7 |
| P2-IT-16 | 真实 PG 慢 worker_emit、容量 1、aclose、append/emit 失败与迟到结果 | 背压不死锁且仅成功 worker_emit 后 ack；普通 stream/worker_emit 失败安全 failed 非 cancelled，append CancelledError 不 ack、不持久化并控制流重抛；队列/runner 清理，迟到成功不覆盖，所有 tasks done | AC-4/5/6、R6/R10 |
| P2-IT-17 | 真实 Memory 汇总/历史/提取/强化/注入事务 | 新旧路径 summary、history、dropped、extract/reinforce、customer_memory 注入及事务提交/回滚一致；失败/取消不写回，跨租户隔离 | AC-2/9、R4/R11 |
| P2-IT-18 | off/on 下存量行、混合 claim 与真实 asyncpg Execution UUID 链 | 保留老行可读、mixed Workers 不共享/重领 row、running 按 Lease/取消收敛、terminal 不改写和回滚无数据修复场景。另在独立新 PG17 环境通过真实 asyncpg 驱动取得未经 fixture 预先规范化/转换的 claimed row，实际执行 claimed row→ExecutionContext→ExecutionRequest；断言 Request.execution_id 的类型精确为 stdlib UUID 且值等于原 row.id，`context.row is claimed_row`、RuntimeFactory spy 收到同一原 row、原 row.id 保持同一对象，类型和值未变，未发生复制、替换或改写。不得用预先构造的 stdlib UUID fixture 或仅测 normalization helper 替代真实驱动链 | AC-1/8/9、R9/R10/R16 |
| P2-IT-19 | 动态 Alembic 空库 upgrade 与测试前后目录零漂移 | 当次 heads 与基线动态一致，空库 upgrade head 成功，测试后 current 对应；前后版本目录清单/哈希相同，无 downgrade | AC-9、R1/R11 |
| P2-IT-20 | 跨租户 Run/SSE、身份与观测对抗 | tenant/business/workspace 过滤不变；伪造/nil Agent 不进入授权或查询；跨租户不可达，日志/trace 安全，metrics 无 run_id/秘密 | AC-1/4/9、R2/R11 |

## 5. 通用核对项（T6/T8 主测试）

| 编号 | 核对项 | 通过标准 | 溯源 |
|---|---|---|---|
| P2-CM-01 | 数据库迁移与既有行兼容 | 动态 heads/upgrade/current 符合当次基线；版本目录零漂移；存量 queued/running/terminal Run 读写和回滚无需修复 | AC-9、R1 |
| P2-CM-02 | 配置加载与默认兜底 | 默认 false、环境覆盖正确；off 路径与基线 diff 为零；flag 不进 fingerprint；on 失败不兜底 | AC-8、R9 |
| P2-CM-03 | 审计、日志与观测 | 日志/trace 可按 run_id 查 path/react/native/v1/耗时/终态/error；metrics 低基数且无 run_id；无 input/config/history/密钥/原始堆栈/nil | AC-9、R11 |
| P2-CM-04 | 多租户与公开数据面 | tenant/business/workspace 过滤不变；跨租户 Run/SSE 不可达；公共响应无 Engine 私有 metadata、Outcome 或 Context | AC-4/9、R2/R4 |
| P2-CM-05 | API/SSE/Agent 配置/前端兼容 | RunView/RunStatus、内部/Open SSE 路由/schema/HTTP 状态/错误体、已发布快照、公共 DTO 与前端零变化；R15 的内部 header 400、内部 after 422、Open after/header 422 及合法 max/strict replay 经实际 ASGI/FastAPI 路由逐项记录 | AC-1/4/9、R1/R7/R15 |
| P2-CM-06 | 异步资源与代码质量 | 成功/失败/取消/aclose/回滚后所有 owned tasks done；受影响 ruff/pytest 实际执行，无反向依赖；不声称未跑全量 | AC-3/6/9、R3/R6 |
| P2-CM-07 | Phase 1 保护面、双 emit 与事件所有权 | Phase 1 DTO/Registry/LocalTest、RuntimeEngine/Factory、Repository/hooks 语义不变；Context 无 emit，worker_emit 仅 Orchestrator、runtime_emit 仅私有 Runtime 链；run.* 与 tool.replay 来源唯一，伪造事件不到 worker_emit，delta 无持久 seq | AC-3/4/9、R3/R5/R6 |
| P2-CM-08 | 证据诚信、功能出口与性能子指标分离 | 本地、CI、人工证据分别记录；功能 UT/IT/CM 全过与本项证据诚信/测量边界可独立通过。性能严格按 05 §4 至少 30 matched pairs、5 组 warm-up 不计样本、nearest-rank p95；原始 paired overhead、end-to-end、首 token、错误率分别保存，canonical diff 不掩盖性能，外部模型/工具时延不从端到端口径扣除。test double 仅功能证据；真实外部环境不足只将性能子指标标 pending_env，T9 最多有条件通过 | AC-1/9、R7/R11 |

## 6. 回归范围

- `backend/tests/test_runtime_engine.py`：既有推理/工具/预算/取消行为不变。
- `backend/tests/test_runtime_baseline.py`、`test_runtime_postgres.py`：off/on 的 claim、事件、取消、HTTP/SSE、慢模型中断、存量行和迟到结果。
- `backend/tests/test_open_platform.py`：开放 API 幂等、权限、事件脱敏、回放和消息账本不变。
- `backend/tests/test_agent_config_execution_compat.py`、`test_agent_model_required.py`、`test_agent_languages.py`：真实 UUID、旧快照、Profile 与语言行为。
- 真实 Memory：`test_memory_injection_postgres.py`、`test_memory_customers_postgres.py`（extract）、`test_memory_governance_postgres.py`（reinforce）、`test_memory_postgres.py`（history/事务）、`test_memory_summary.py`、`test_memory_events_postgres.py`；逐条列明实际节点，不以文件名推断执行。
- `backend/tests/test_extension_contracts.py`、Phase 1 `test_agent_execution_contracts.py`、`test_agent_execution_registries.py`、`test_local_test_adapter.py`：公共契约、Registry 与 LocalTest 实现/公共行为不变；仅按 R13 同步累计精确模块集合，且依赖门禁不弱化。
- 完整套件按仓库约定由 CI 执行；本地只声称实际运行的受影响测试，未运行项保留 pending。

## 7. 缺陷分级与主测试出口准则

| 级别 | 定义 | 处理 |
|---|---|---|
| P0 阻断 | 回复/工具主流程破坏；数据丢失；跨租户或凭据泄露；错误终态覆盖；nil 进入授权/查询 | 立即关闭新路径，修复并完整回归 |
| P1 严重 | 新旧语义不等价；ack/SSE 回归；取消/Lease 失效；开关/回滚失效；Worker/Core 反向耦合；任务泄漏 | 修复前不得扩大灰度或进入验收 |
| P2 一般 | 非关键性能退化、诊断缺失、非敏感字段差异且无不兼容影响 | 记录后可带问题验收，需产品签字 |
| P3 轻微 | 文案、命名、非敏感日志问题 | 排期修复 |

**T8 主测试出口**：上述 P2-UT-01～24、P2-IT-01～20、P2-CM-01～08 每条有实际结果；所有功能 UT/IT/CM 必须全部通过，CM08 的证据诚信/测量边界也须通过。P2-UT-01 的 R16 普通 UUID/子类/伪造类型/恶意普通异常/控制流用例和 P2-IT-18 的真实、未经 fixture 规范化的 asyncpg claimed row→Context→Request 链为必跑出口，必须同时证明公共 Request 精确 stdlib UUID、Context/RuntimeFactory 原 row 保留和原 row.id 未改写，不得以 helper 单测或预转换 fixture 替代。AC-1～9 主验收证据可复现；受影响回归全绿；off diff 为零；无 P0/P1、迁移/ORM/公共 schema/前端变化或悬挂任务。真实性能子指标未测量为 `pending_env`，不得写达标，但不否定全绿功能出口；此情形可进入 T9，T9 最多“有条件通过”，不能写完全通过。T8 不创建 Phase 2 示例种子，也不预写 T11 结果。

## 8. 验收后种子验证（仅 T11 执行并追加 06）

| 编号 | 用例 | 预期 | 溯源 |
|---|---|---|---|
| P2-CM-09 | Phase 2 专属示例种子幂等与命名空间 | T9 正式验收后，T10 新建可识别命名空间、低敏、幂等种子；二次运行不重复/不覆盖运营修改；只用现有 schema/API/已发布快照，真实 Agent ID，无 Engine 字段/迁移/UI | AC-8/9、R12、T10 |
| P2-CM-10 | 新种子 quickstart off/on、内嵌 Worker、双 SSE 与回滚 | 默认 off 与显式 on 均支持 published-snapshot 和 no-snapshot legacy base-runtime 示例；路径日志正确，内部/Open SSE 兼容，off 回滚成功，无新增服务；结果只追加 06/07 附录 | AC-4/8/9、R12、T11 |

T11 任一失败都重开缺陷及受影响 A/C 项，修复后重跑；不得删除失败日志、改写 T8/T9 先前证据或把附录当作预先通过。
