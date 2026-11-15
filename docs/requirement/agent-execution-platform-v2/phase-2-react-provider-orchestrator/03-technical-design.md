# Phase 2 · React Provider 与执行编排器 — 技术落地文档

> 状态：本地 T2～T11 与 R17 live 验证已完成，R18 生产修复及聚焦验证已完成，详见 06/07 及相应附录；R18 最小 live on/off 已完成；总体仍有条件通过
> 创建：2026-11-02
> 修订：2026-11-12（R18：Worker 终态日志必须晚于正常 finish 成功；当前状态统一）
> 依据：`docs/architecture/agent-execution-platform-v2.md` 第 4～7、12、14～17、19、21 节；Phase 0 `baseline/run-lifecycle-events.md`；Phase 1 `backend/tests/agent_execution/adapter_contract_suite.py`；`02-requirements.md`（FR-1～FR-6、AC-1～AC-9）；`08-implementation-breakdown.md`（R1～R18、T1～T11）；backend 基线 `0a6c4b5`

## 1. 现状核查与改动总览

Phase 1 代码已通过 merge `0a6c4b5` 合入 integration，但正式人工验收仍是独立事项。`RuntimeEngine.run()` 返回 `(output, history, dropped)`；Worker 负责 fingerprint、Memory 渲染、heartbeat/cancel monitor、Runtime 调用与 `repository.finish()`；Repository 原子维护事件序号、owner/lease、按提交顺序的终态保护及 append/finish 的不同控制流；组合根装配唯一 RuntimeFactory/Worker；内部与开放路由消费既有事件表和 Notifier。除“既有”说明外，以下均为**拟改动/拟新增**，不表示已实现。

2026-11-10 只读执行 `uv run --directory backend alembic heads` 观测到 `0057_industry_pack_runtime (head)`。该值只描述本次基线；实施和测试必须重新动态读取，不得作为永久验收常量。

| 层 | 文件 | 改动 |
|---|---|---|
| 迁移/ORM/前端 | `backend/migrations/versions/`、既有 ORM、`frontend/` | 零新增、零修改；测试动态比较 heads、空库 upgrade 与前后目录清单/哈希 |
| 新模块 | `backend/src/agent_platform/core_platform/agent_execution/adapters/react/{__init__.py,adapter.py}` | ReactAdapter 五方法、首发 gate、私有 runtime_emit、ack-aware 流、取消与唯一终态 |
| 新模块 | `.../adapters/react/event_mapper.py` | `(kind,data)`→AgentEvent→原 `(kind,data)` 的开放业务事件映射与保留事件拒绝 |
| 新模块 | `.../adapters/react/error_mapper.py` | 全部 Engine/Gateway/Domain RuntimeFault、未来未知 code、Timeout/未知异常的安全公共映射与私有原始 code 保留 |
| 新模块 | `.../agent_execution/orchestration/{__init__.py,execution_context.py}` | 私有 ExecutionContext 与同步 ContextVar 捕获/reset；不含 worker_emit/runtime_emit |
| 新模块 | `.../orchestration/execution_lifecycle.py` | 私有 ExecutionOutcome、非 optional usage、runtime-checkable AcknowledgingEventStream 与 OutcomeCollectingAdapter/helper、纯转换；不 import React |
| 新模块 | `.../orchestration/orchestrator.py` | 固定选择、独占 worker_emit、start→claim→放行、ack/Outcome 协议检测、worker_emit 后 ack、drain→React 私有单次 collect 或 LocalTest 公共回退、abort/aclose |
| 应用工厂 | `backend/src/agent_platform/applications/platform_runtime/react_adapter_factory.py` | 同步零参工厂读取当前 Context 并捕获到新实例；不 await、不接触 worker_emit、不持久读 ContextVar |
| 既有 Factory | `.../platform_runtime/runtime_factory.py` | 保持既有 ReAct 构造；on 路径由 Adapter 将私有 runtime_emit 同时传给 for_run 和 runtime.run，legacy off 不变 |
| 组合根 | `.../platform_runtime/runtime_composition.py` | 注册 react/native/v1、构造 Orchestrator、可选注入 Worker；fingerprint 排除新开关 |
| Worker | `backend/src/agent_platform/core_platform/agent_runtime/worker.py` | 末尾 `orchestrator=None`；off 原路径，on 将原回调作为 worker_emit 传给编排器；保留 Memory/monitor/finish |
| Settings | `backend/src/agent_platform/core_platform/platform_services/platform_settings/settings.py` | 新增 `execution_orchestrator_enabled: bool = False` |
| 环境/部署 | `backend/.env.example`、`deploy/production/.env.example`、`compose.yaml`、`deploy/quickstart/compose.yaml`、`deploy/production/compose.yaml` | 仅增加必要 AGENT_EXECUTION_ORCHESTRATOR_ENABLED 占位/插值；不新增服务、密钥或 UI |
| quickstart 日志 | `deploy/quickstart/uvicorn-logging.yaml`、`deploy/quickstart/supervisord.conf`、`Dockerfile` | R17：quickstart API 通过 `--log-config` 加载专属配置，仅 Worker logger 以 INFO 输出受控路径日志；root 保持 WARNING，不新增服务或敏感字段 |
| 保护模块 | Phase 1 contracts/registries/LocalTest、`agent_runtime/{engine,repository,schemas}.py`、runtime hooks、API/SSE 路由 | 保持不变；对等修复若需变化必须先新增 R 并同步设计，公共 schema/终态语义不得改变 |
| 测试 | 新 `backend/tests/test_react_engine_adapter.py`、`test_execution_orchestrator.py`；扩展 `test_runtime_baseline.py`、`test_runtime_postgres.py`、`test_open_platform.py`、`test_agent_config_execution_compat.py`、真实 Memory 测试 | 双 emit spy、逐函数公共契约/私有替代、并发/ack/backpressure、PG/SSE/Memory、错误/取消/Lease、混合 Worker/回滚证据 |

## 2. 数据模型与责任边界

### 2.1 无数据库模型变更和身份规则

一条 `runtime_runs` 行仍表示一次 Execution 尝试。`ExecutionRequest.execution_id` 保持 Phase 1 UUID 字段，必须为精确 stdlib UUID，值直接等于 claimed `row.id`，不另造 Execution ID。ExecutionContext 私有边界按 R16 分别规范化 `row.id` 与传入 `execution_id` 后以 `==` 检查值相等，不得用 `is`：精确 stdlib UUID 原样返回并保持原对象身份；UUID 子类（如 asyncpg 返回类型）经 `UUID(str(value))` 等受控值转换生成精确 stdlib UUID。该临时 canonical parse 只在私有边界进行，不属于禁止的公共字符串化，不改变公共 DTO、schema 或序列化形状。字符串、整数、None、伪造非 UUID 和值不匹配安全拒绝为静态 `INVALID_REQUEST`；恶意子类 `__str__`/描述符抛出的普通异常同样转为安全静态 `INVALID_REQUEST`，不泄露原异常，控制流异常原样重抛。不增加 Engine 列、Task 表、Session 表或事件字段；固定三元组只在内存 DTO、安全日志/trace 中出现。

Agent 身份规则：

1. 有快照：严格解析 `config.agent.id` 真实 UUID；缺失、非 UUID、nil 均安全失败，不 fallback，不借 row/conversation UUID。
2. 无快照且确为 React + legacy `base_runtime`：仅 Request 内部可使用 `UUID(int=0)` 表示匿名未绑定 Agent，以兼容 Phase 1 DTO。
3. nil 不得进入 selector、授权、tenant/credential/Agent 查询、数据库、HTTP/SSE、日志、metrics 或 engine_metadata；运行工厂不能用 nil 查 Agent。
4. Phase 3 通过正式身份模型移除该兼容哨兵；Phase 1 DTO 不变。

### 2.2 私有上下文、双 emit 与结果

| 对象 | 内容与方向 | 可见范围/禁止事项 |
|---|---|---|
| ExecutionContext | `context.row` 是同一原 claimed Mapping，规范化后的精确 stdlib UUID execution_id、history、summary_message、customer_memory、trace/timeout 等 | Worker→Orchestrator→同步应用工厂捕获→ReactAdapter；**不含 worker_emit 或 runtime_emit**，不序列化、不跨执行共享；原 `row.id` 不复制、替换或改写，`RuntimeFactory.for_run` 继续接收原 row，公共 Request 使用规范化后的精确 stdlib UUID |
| worker_emit | Worker 原事件回调，Worker→`orchestrator.execute(context, worker_emit)`；唯一沿用旧路径写 Repository.append 或 Notifier 的回调 | 仅 Worker/Orchestrator；不进入 Context、Adapter、RuntimeFactory、PlatformTools 或 RuntimeEngine |
| runtime_emit | ReactAdapter 私有回调；同一函数对象同时传给 `RuntimeFactory.for_run(row, runtime_emit)` 和 `runtime.run(..., runtime_emit, ...)` | 只做 `(kind,data)→AgentEvent→React 私有流`；不得直接触达 worker_emit、Repository 或 Notifier |
| ExecutionOutcome | status、output、history、dropped、legacy error_code、非 optional usage、私有辅助值 | ReactAdapter 私有 `collect_outcome`→Orchestrator→Worker；无协议 LocalTest 只能公共 `collect_result→from_result` 确定性回退；仅成功执行向 Memory 完成钩子提供 history/dropped |
| 公共 ExecutionResult | Phase 1 不变字段；安全 status/output/usage/artifacts/engine_metadata/error | 不经 engine_metadata 增传 history、dropped、Outcome、Context、回调或 HTTP/SSE 字段 |
| AgentEvent | UUID event_id、UTC timestamp、局部单调 sequence、source=engine_native、原 event_type/payload | 进程内信封；不改 DB event_seq/SSE ID |

Worker 继续拥有队列、并发、owner、heartbeat、fingerprint 和最终 finish；Orchestrator 不直接写 DB；Adapter 不操作队列、不决定授权、不调用 Repository.finish。Core 不 import applications/business，应用组合根注入 RuntimeFactory 能力。

## 3. 同步 Registry、异步 Runtime 与双 emit 装配

Registry factory 仍是同步 `Callable[[], AgentEngineAdapter]`，零参且每次 fresh instance。禁止 async factory 或在同步 resolve 中 await `RuntimeFactory.for_run()`。

```text
Worker._execute(on)
  └─ orchestrator.execute(context, worker_emit)

Orchestrator
  └─ 同步、无 await 段：
       token = execution_context_var.set(context)  # context 不含任何 emit
       try: adapter = registry.resolve(react, native, v1)
       finally: execution_context_var.reset(token)

应用零参 ReactAdapterFactory（仅上述同步段被间接调用）
  └─ 读取并校验当前 ExecutionContext
     → 捕获 context 与 RuntimeFactory 引用到新 ReactAdapter
     → 返回；Adapter 此后不再读 ContextVar，也不知道 worker_emit

adapter.start(request)
  └─ 创建 runner 与关闭的首发 gate
     → runner 创建私有 runtime_emit
     → await runtime_factory.for_run(同一 claimed row, runtime_emit)
     → runtime.run(..., 同一 runtime_emit, ...)

Orchestrator 正常路径
  └─ start → 同步 claim stream_events（打开发射 gate）
     → 从公共流取 AgentEvent
     → 还原 (kind,data) → await worker_emit(kind,data)
     → 成功后 await acknowledge(event)
     → drain
     → React：await collect_outcome(handle)  # 私有入口且仅一次
       LocalTest：await collect_result(handle)
                 → ExecutionOutcome.from_result(..., 显式确定性 legacy code)  # 无协议才回退
```

缺失 Context、类型错误、Context 覆盖、重复 start 和工厂异常均安全失败并 finally reset。`agent_model_required` 是 Adapter runner/lifecycle 的 RuntimeFault，保留 legacy code，不能改写成 `adapter_factory_failed`。开启路径失败不得静默 legacy fallback。

spy 必须证明 for_run/run 收到同一 runtime_emit，Factory/PlatformTools/RuntimeEngine 没有任何 worker_emit 路径；model.delta、knowledge.retrieved、memory_search.completed、扩展事件只在公共流取出后经 worker_emit 各一次，伪造 run.*/tool.replay 在 worker_emit 前被拒绝。

## 4. ReactAdapter 生命周期、结构化 ack 与终态状态机

### 4.1 能力与公共契约

固定身份 `react/native/v1`；`streaming/cancellation/tool_calling/native_events=true`，其余七个不支持能力=false。每实例一个 active execution，完整实现现有五方法，不新增公共签名或 DTO 字段。

公共 AsyncIterator 没有下游 ack，因此公共套件不能单独证明 React 的 worker_emit 后 delivery。React harness 对公共流做显式包装：`event=await anext(raw_stream)`→记录并 `await worker_emit(event.event_type, event.payload)`→`await raw_stream.acknowledge(event)`；aclose/异常委托 abort/aclose。私有协议测试直接使用 raw stream。公共五方法不变。

LocalTest 实际在 claim 前入队、terminal 丢弃队列，并在 `__anext__` 的 yield 时结算 delivery；React 不得再声称“无 consumer 抑制等同 LocalTest”。LocalTest 不实现 AcknowledgingEventStream，Orchestrator 检测不到该协议时仍 await worker_emit，但不额外 ack，明确其 Adapter 内部 `yield = delivery`。

### 4.2 公共 adapter_contract_suite.py 逐函数复用/排除清单

React harness 继承 `AdapterContractSuite`，以 scripted RuntimeFactory/Runtime、worker_emit spy、ack 包装和手动 clock/gate 实现控制；所有 streaming 原函数都经上述显式 worker_emit/ack 包装。下表是完整冻结清单，不能用“适用用例”替代。

| 公共测试函数 | React 裁定与 harness/私有替代 |
|---|---|
| `test_capabilities_start_stream_collect_success` | **排除原函数**：硬编码 scenario usage/artifacts/engine_metadata 不符合 React v1 无聚合输入。私有替代保留身份、Request 不变、Handle、重复 start、事件和 completed 断言，但 usage={}、artifacts=[]、engine_metadata={}，并走 worker_emit/ack |
| `test_immediate_concurrent_and_repeated_collectors_share_result` | **原函数复用**：首个 collector 在 never-claimed 显式选择 no-stream suppression 并放行 gate；共享 shielded Result |
| `test_concurrent_second_consumer_and_claim_after_aclose_are_rejected` | **原函数复用**：同步单 claim，closed 后拒绝再次 claim |
| `test_multiple_events_preserve_order_payload_and_empty_stream_terminates` | **原函数复用 + ack 包装**：验证顺序/payload；空流首发握手后正常结束 |
| `test_request_identity_mismatch_fails_before_handle` | **原函数复用**：身份错误在 Handle 前安全失败 |
| `test_prestart_errors_precede_handle_and_preserve_retryability` | **排除原函数**：React v1 无 LocalTest 任意 prestart_error scenario。私有替代覆盖真实 Request/Context/state 前置错误；RuntimeFault 在 runner 按矩阵测试 |
| `test_stream_errors_are_safe_for_stream_and_all_collectors` | **原函数复用**：harness 注入 runner/stream 安全错误并验证所有 collectors |
| `test_pre_chained_safe_stream_error_does_not_retain_raw_exception_chain` | **原函数复用**：保持异常链脱敏 |
| `test_unknown_exception_and_simulated_process_failure_are_distinct_and_safe` | **排除原函数**：外部 process failure 不属于 React v1。私有替代仅保留未知异常安全 internal_error/execution_error；不断言 simulated_process_failure |
| `test_manual_clock_timeout_wakes_collectors_without_real_waiting` | **原函数复用**：harness 注入手动 scheduler/clock，映射 outer execution_timeout/run_timeout，不靠真实等待 |
| `test_repeated_concurrent_cancel_closes_stream_and_collectors` | **原函数复用**：取消唤醒首发 gate、stream 和 collectors |
| `test_cancel_wins_gate_race_and_suppresses_late_events_and_success` | **原函数复用**：Adapter first-terminal-wins，迟到事件/成功抑制 |
| `test_success_wins_gate_race_and_is_never_retroactively_cancelled` | **原函数复用**：completed 后 cancel 不追溯改写 |
| `test_duplicates_late_events_gaps_and_timestamps_follow_sequence_rules` | **排除原函数**：React 由 raw kind/data 生成局部 UUID/UTC/单调 seq，不接收 LocalTest 外部 seq/duplicate_of。私有替代验证重复 raw 事件获得不同 event_id、局部 seq 连续且无乱序输入概念 |
| `test_same_event_id_with_different_content_is_never_repaired` | **排除原函数**：runtime_emit 不接受外部 event_id，不能构造同 ID 异内容。私有替代验证伪造信封字段被拒绝/不解释，重复 raw payload 不合并 ID |
| `test_terminal_visibility_never_precedes_queued_or_active_stream_events` | **原函数复用 + ack 包装**：活跃流全部 ack 后 Result；立即 collect 先到选择 no-stream，终态后 stream 为空 |
| `test_early_aclose_cleans_owned_tasks_and_does_not_permit_replay` | **原函数复用 + ack 包装**：首事件显式 worker_emit/ack，aclose 清理且不可 replay |
| `test_one_cancelled_collector_does_not_cancel_shared_execution` | **原函数复用**：共享 collectors shield |
| `test_lone_collector_cancellation_cleans_owned_work_before_propagation` | **原函数复用**：单独 no-stream collector 取消清理后重抛 |
| `test_deterministic_fresh_runs_have_no_cross_instance_high_water` | **排除原函数**：外部指定 [5,2] seq 不符合 React 局部生成。私有替代验证 fresh Run 从各自 seq 1 开始、event/result 对象和状态不共享 |
| `test_pending_anext_is_woken_by_aclose_without_external_cancel` | **原函数复用**：aclose 唤醒 pending anext 和首发 gate |
| `test_claimed_empty_stream_does_not_block_successful_collection` | **原函数复用**：stream 先到，producer finished 且 undelivered=0 即发布 Result，不要求空调用方先 aclose |
| `test_delivered_only_event_does_not_require_an_extra_poll_before_result` | **原函数复用 + ack 包装**：worker_emit/ack 后无需额外 poll 即可 collect |
| `test_invalid_handles_are_rejected_by_stream_collect_and_cancel` | **原函数复用**：五方法相关 Handle 校验不变 |
| `test_raw_request_and_handle_values_fail_safely` | **原函数复用**：原始错误对象安全失败且不泄露 |

### 4.3 React 私有流状态与首发握手

流状态明确为 `never-claimed → claimed-active → closed`，执行另有 pending/terminal；不得把这些状态与 LocalTest 内部实现混称。

1. **start**：创建 runner 和关闭的首发 gate；在 stream_events 同步 claim 或 no-stream collector 显式选择之前，runner 可装配/等待，但首个 runtime_emit 不得进入 React 流，更不得触达 worker_emit。
2. **stream 先到**：stream_events 在同步返回 iterator 前原子设置 claimed-active 并打开 gate；runner 才能发射，保证 start→立即 stream 的首事件不丢。
3. **collect 先到且 never-claimed**：单独或共享 collector 显式选择 React 私有 **no-stream suppression**，原子保持 never-claimed/no-stream 模式并打开 gate；事件不入队、不阻塞、不到 worker_emit，之后 stream 返回空/按 terminal 结束，不重放。
4. **竞争**：collect 与 stream 的首次选择在同一状态锁下先到先赢；正常 Orchestrator 固定 stream 先 claim、drain 后 collect，不依赖竞态。
5. **closed/terminal**：活跃流在 terminal 前排空已接收且已 ack 事件后结束并 closed；aclose/cancel 唤醒首发 gate、put/get 并清理，closed 后再次 claim 安全失败。never-claimed 的 no-stream/cancel terminal 后首次 stream 为空且无 replay。

LocalTest 保持其 claim 前入队、terminal 丢弃和 yield=delivery 原语义，以上 React 规则只适用于 React 私有实现。

### 4.4 Core 私有 AcknowledgingEventStream 协议

在 `orchestration/execution_lifecycle.py` 定义 runtime-checkable 结构化 Protocol/helper，不 import 具体 React：

```text
AcknowledgingEventStream(AsyncIterator[AgentEvent])
  async acknowledge(event)
  async abort(error)
  async aclose()
```

helper 对公共 `AsyncIterator[AgentEvent]` 做 `isinstance` 协议检测并返回私有能力或 None。规则：

- 每个 execution 同时至多一个 in-flight；ack 必须同时匹配 execution_id 和 event_id，且对应当前 in-flight。
- 成功 ack exactly-once 地扣减 undelivered 并唤醒 producer；对同一已结算 execution/event identity 的重复 ack 幂等，不再次扣减。
- 错误 execution/event identity、无 in-flight、乱序 ack 或跨 execution ack 是安全 protocol_error，调用 abort 清理；不得猜测、自动修复或裸 yield 自动 ack。
- Orchestrator 检测为 React 私有协议时，worker_emit 成功后才 acknowledge；检测不到时仅适用于 LocalTest 的 yield=delivery，不能虚构 ack。
- 普通 worker_emit/stream 异常走 abort/aclose 并发布 failed Outcome；append/caller CancelledError 走 abort/aclose 后重抛，不映射普通 execution_error。

### 4.5 生产、背压与终态发布

推荐 Condition + bounded deque，并在同一状态锁下维护 stream 状态、producer finished、terminal published、queued/in-flight undelivered、settled ack identities、pending result、shielded terminal future 和 runner。

1. 队列容量至少 1，仅限制 queued buffer，可另有一个已 yield 未 ack 的 in-flight；活跃流满时 producer 等待 Condition。
2. pop/yield 不是 React delivery；Orchestrator 从公共流取出后 await worker_emit，成功后的 ack 才扣减 undelivered。测试侧 streaming 公共套件同样显式执行此步骤。
3. runner 正常结束先存 pending result；producer finished 且 queued+in-flight undelivered=0 后发布唯一 Result。已 claim 但空闲未关闭的 stream 不阻塞 collect，terminal 会唤醒 stream；活跃事件不得在 Result 前跳过 ack。
4. 正常 Orchestrator 先完整 drain，再 collect，Worker 最后 finish，保证 Repository 的 run.* 终帧最后。
5. runner stream/protocol failure 安全抛给 consumer，按 delivered 解除等待，再发布 failed Result，不悬挂 collector。
6. cancel/aclose/普通 emit 失败原子抑制 queued/迟到事件、唤醒 put/get 和首发 gate、取消并 drain runner、抑制迟到成功。

### 4.6 取消、append/finish 与清理矩阵

| 触发 | 必须行为 | 结果 |
|---|---|---|
| 显式 adapter.cancel | Adapter 内部 first-terminal-wins；关闭流、唤醒 gate/put/get、取消并 drain runner，重复 cancel 安全 | 若尚无终态则 cancelled Result，output=None/error=None；已完成 Result 不追溯取消 |
| async generator aclose | 同显式取消的执行清理，唤醒首发 gate，无 runner 泄漏 | 按 Adapter 取消语义收敛，closed 不可 replay |
| 普通 stream/worker_emit/Notifier 非吞掉异常 | abort/aclose，抑制后续事件/成功 | 安全 failed Outcome：公共 internal_error、legacy execution_error，非 cancelled |
| stale/cancelled/expired `worker_emit→Repository.append` | Repository 抛 `asyncio.CancelledError`；事件不 ack、不持久化，Orchestrator/Adapter 清理后重抛控制流 | 不归普通 execution_error，不改写原终态，由 monitor/已提交状态决定 Run |
| stale/terminal/wrong-owner/expired Repository.finish | Repository 静默 no-op，不提交 output/history/hooks/终态事件 | 保持先提交终态；不得描述成 append no-op |
| Notifier 已吞掉的指定 PG/OS delta 失败 | 保持 best-effort，正常 ack delta；其他异常按普通 worker_emit 失败 | 不制造持久 delta 或新错误字段 |
| 调用方 CancelledError | 清理 owned iterator/runner/tasks 后重抛 | Worker monitor 决定 cancelled 或 failed/worker_lost，失租不伪装用户取消 |
| 单独 no-stream collector 取消 | 停止执行、唤醒 gate 并清理；共享 collectors shield | 与公共 collector 契约一致 |
| 非协作 runner | 外层 timeout 记录清理失败/悬挂风险并 fail closed | 只承诺协作式协程有界 drain，不宣称强杀 |

所有 owned tasks 最终必须 await/done。持久层不是无条件 cancel 优先：Run 按提交顺序 first-commit-wins；finish/reaper 先提交后 cancel no-op，cancel 先提交则 late finish 不改写。reaper 继续产生 cancelled-with-worker_lost/queue_timeout 变体。测试用 Event/gate 控制两种顺序，不靠 sleep 巧合。

### 4.7 Core 私有 Outcome 收集与 LocalTest 回退

`execution_lifecycle.py` 另定义 Core 私有 runtime-checkable `OutcomeCollectingAdapter`：

```text
OutcomeCollectingAdapter
  async collect_outcome(handle) -> ExecutionOutcome
```

helper 对 Adapter 做结构检测，验证 `collect_outcome` 是真正 async callable；描述符访问异常、同步函数、返回值的 async 假象或错误形状都 fail closed 为无协议，不得调用该能力。Protocol/helper 不 import React，不加入 Phase 1 `AgentEngineAdapter`、公共 contracts 或公开序列化。

ReactAdapter 的私有 `collect_outcome` 与公共 `collect_result` 共用同一个内部 terminal collection 实现：同样处理 Handle、stream-first/no-stream 选择、collector 计数、shielded future、单独/共享 collector 取消和清理；终态后读取 Adapter 内部已经发布的同一 Outcome，不重建、不猜测 legacy code。Orchestrator 对检测到此协议的 React 只调用 `collect_outcome` 一次，不先调用 `collect_result` 再补一次私有收集，也不访问 `_execution`。completed 保留真实 history/dropped，failed 保留原 RuntimeFault legacy code（含未来未知 code），cancelled 无 code；这些私有值不得进入公共 Result 或 engine_metadata。

LocalTest 不实现该私有协议，Orchestrator 仅在检测不到协议时走公共 `collect_result`，随后按下表显式转换。`ExecutionOutcome.from_result` 对 failed 仍要求显式 legacy code，不增加从 message/details/Provider 文本或未知字段猜测的逻辑。

| 无协议 LocalTest 公共 Result | 私有 Outcome |
|---|---|
| completed | `history=[]`、`dropped=[]`，保留安全 output/usage 等公共值 |
| failed 且公共 error code=`execution_timeout` | failed，`legacy_error_code="run_timeout"` |
| failed 且为其余任意公共 error code（包括 internal/protocol/simulated process 等） | failed，`legacy_error_code="execution_error"` |
| cancelled | cancelled，无 error/code |

这是只为无协议 LocalTest 定义的有损兼容回退；React 绝不能经此路径丢失原 code。若 Adapter 暴露私有协议，其收集失败不得静默降级到公共收集。drain→collect 完成后才由 Worker finish，保证唯一终态和 run.* 终帧顺序。

## 5. 事件映射、双 emit spy 与 SSE 所有权

| 来源 | React 内部处理 | 最终去向 |
|---|---|---|
| 所有合法普通业务事件（model/tool、knowledge.retrieved、memory_search.completed、扩展事件） | runtime_emit 原名同 JSON payload 转 AgentEvent；公共流取出后还原，Orchestrator await worker_emit，成功再 ack；无 allowlist | 旧 worker_emit 决定 Repository.append 或 Notifier，每次事件一次 |
| model.delta | 与其他事件走相同双 emit/ack 边界，不在 runtime_emit 直接 Notifier | worker_emit→Notifier best-effort，无 DB seq/replay |
| Adapter 原始 run.* | 安全 protocol_error，在 worker_emit 前失败 | run.* 仅 Repository.submit/claim/cancel/finish/reap |
| Adapter 原始 tool.replay | 安全 protocol_error，在 worker_emit 前失败 | tool.replay 仅 DurableToolReplayCache |
| 内部 AgentEvent/Outcome/Context/emit 回调 | 不进入公开 payload | 内部/Open SSE schema 和字段过滤不变 |

spy 测试分别记录 runtime_emit、公共 yield、worker_emit、Repository/Notifier 和 ack 顺序；覆盖 model.delta、knowledge.retrieved、memory_search.completed、扩展事件、伪造 run.*/tool.replay，断言任何 Factory/PlatformTools/RuntimeEngine 事件都不能绕过公共流直达 worker_emit。

内部/Open SSE 的游标校验按既有路由分别保持以下 R15 矩阵，不得把内部手工 header 的 400 改成 422，也不得把 Open typed 校验的 422 改成 400：

| API 与参数 | 校验机制 | 非法、类型或范围错误 | 既有响应 |
|---|---|---|---|
| 内部 `Last-Event-ID` | handler 手工解析 header | 无法解析为整数或其他非法值，或超出 `[0,2147483647]` | `400 / invalid_last_event_id` |
| 内部 `after` | FastAPI typed Query | 类型错误或超出 `[0,2147483647]` | `422` |
| Open `after` | FastAPI typed Query | 类型错误或超出 `[0,2147483647]` | `422` |
| Open `Last-Event-ID` | FastAPI typed Header | 类型错误或超出 `[0,2147483647]` | `422` |
| 内部/Open 合法游标 | 以 `max(after,last_id)` 计算有效 after | 无；缺失游标按既有默认值处理 | 严格只重放 `seq>after`，不重复边界事件 |

Phase 2 不改变上述路由、schema、状态码或错误体。内部/Open SSE 继续保留超过 200 条持续 drain、无 ID delta 不重放、tool.replay payload 隐藏但 cursor 推进、终帧位置与公共字段过滤。AgentEvent.sequence 只用于 Adapter 局部顺序，不能替代 DB event_seq/SSE id。04 的 P2-IT-05/06 必须经 ASGI/FastAPI 实际路由验证该矩阵，helper 单测不能替代路由证据。

## 6. 错误、用量与终态映射

### 6.1 Phase 0 全来源错误矩阵

以下来自 Phase 0 `baseline/run-lifecycle-events.md:38–52` 的 Engine/Factory/Gateway/Domain 清单。私有 Outcome/Run 的 legacy_error_code 始终保留 RuntimeFault 原始 code，公共只使用安全目录，不复制 Provider/Domain 文本。

| 原始 RuntimeFault/条件 | 公共 category/code | 私有 legacy_error_code / Run |
|---|---|---|
| agent_model_required、configuration_changed | configuration_error / invalid_request | failed / 原 code；agent_model_required 不得成为 adapter_factory_failed |
| model_resource_not_found、model_resource_disabled、model_profile_version_not_found | configuration_error / invalid_request | failed / 各原 code |
| model_input_too_large | resource_exhausted / resource_exhausted | failed / model_input_too_large |
| model_tools_not_supported | configuration_error / invalid_request | failed / model_tools_not_supported |
| invalid_model_response、empty_model_response、duplicate_tool_call_id、repeated_tool_call | protocol_error / protocol_error | failed / 各原 code |
| model_round_limit、tool_call_limit、model_output_too_large | resource_exhausted / resource_exhausted | failed / 各原 code |
| model_provider_unavailable、model_rate_limited、model_provider_rejected、model_transport_error | engine_unavailable / engine_unavailable | failed / 各原 code；不在 Worker 新增自动重试 |
| content_blocked_input、content_blocked_output | permission_denied / permission_denied | failed / 各原 code |
| gateway_concurrency_exceeded、gateway_request_quota_exceeded | resource_exhausted / resource_exhausted | failed / 各原 code |
| model_credential_unavailable | authentication_error / authentication_failed | failed / model_credential_unavailable |
| model_response_too_large | resource_exhausted / resource_exhausted | failed / model_response_too_large |
| model_stream_interrupted | engine_unavailable / engine_unavailable | failed / model_stream_interrupted |
| model_timeout | timeout / execution_timeout | failed / model_timeout |
| RuntimeEngine.run 外层 TimeoutError | timeout / execution_timeout | failed / run_timeout |
| 任意未来/未预知 RuntimeFault(code) | internal_error / internal_error 安全 fallback | failed / **逐字保留原始 code**，不因公共枚举未知而丢弃 |
| 未知普通 Exception、普通 stream/worker_emit 失败 | internal_error / internal_error | failed / execution_error |
| Adapter 保留 run.*/tool.replay、畸形事件、ack identity/乱序错误 | protocol_error / protocol_error | failed / execution_error（已有显式 legacy code 时保留） |
| 显式 Adapter cancel | 无 ExecutionError | cancelled / 无 error/output |
| heartbeat lost | Worker 侧安全 internal/worker_lost 语义 | failed / worker_lost；reaper 可有 cancelled-with-worker_lost |

`model_stream_not_supported` 当前由 GatewayChatModel 走 fallback，而非直接 RuntimeFault；若未来调用点改为抛出，仍按“保留原 code + 安全公共映射/fallback”处理，不能静默丢 code。stale/cancelled/expired append 的 CancelledError 是控制流，不进入上表普通异常映射。

### 6.2 Usage 和私有完成值

- `ExecutionResult.usage` 与 Outcome usage 非 optional、不得为 None。React v1 当前 `RuntimeEngine.run()` 只返回 `(output, history, dropped)`，没有聚合 usage 输入，因此公共 Result 和私有 Outcome usage 都为 `{}`；这不是“沿用既有 Runtime 聚合”，也不是伪造 `prompt_tokens=0` 等零 token。
- `model.completed` 事件 usage 原样保留，包括未知但合法扩展字段；不得从该事件另造 Result usage 聚合口径。
- output/history/dropped 仅私有 Outcome 显式承载；失败/取消不向 Memory 完成钩子返回 history/dropped。
- 不通过 engine_metadata、Outcome、Context 或 emit 回调增传 HTTP/SSE 字段，不记录 secret、原始异常或 nil Agent。

## 7. 新旧路径对等比较规则

### 7.1 串行确定性脚本

相同模型/工具脚本下逐项比较 output、error、usage、history/dropped（成功时）、稳定 payload、事件顺序、每 Run 连续 DB seq、终帧位置及从各游标严格重放。合法业务事件名和 payload 不得因 Adapter 改写。

### 7.2 并行工具与模型轮

- 以 call_id 对齐 tool.started/tool.completed；要求集合相等、同 call_id started→completed 局部偏序及模型轮边界一致。
- 独立并行分支不要求跨路径全局顺序或绝对 seq 相同；每 Run 自身 seq 仍连续且终帧最后。
- 并行区域内无归属 call_id 的业务事件按每模型轮 multiset 比较，不强行全局排序。

### 7.3 仅这些显式路径可 canonicalize

| 范围 | 可 canonicalize 字段 |
|---|---|
| DTO | event_id、timestamp、Run 实例/计时标识符 |
| model.completed payload | gateway_call_id、first_token_ms、duration_ms |
| tool.completed payload | gateway_call_id、duration_ms |

canonicalize 前验证原字段类型、nullable 与 duration 非负。不得规范化 call_id、业务 document/chunk ID、工具参数/结果、output、error_code 或 usage，不得全局删除 ID。原始延迟是独立性能证据，不能因 canonical diff 为零而省略。

## 8. 配置、组合、上线与回滚

`Settings.execution_orchestrator_enabled=False`，由 `AGENT_EXECUTION_ORCHESTRATOR_ENABLED` 覆盖。默认 off；进程启动读取，滚动重启生效，不能请求级热切换。flag 从 runtime-composition fingerprint 排除，off API/on Worker 与混合 Worker 不因开关报 configuration_changed。

共享组合根注册 EngineDescriptor(react)、ProtocolDescriptor(native)、AdapterDescriptor(react/native/v1)，构造同一 Orchestrator 并按开关可选注入 Worker。生产 selector 固定可信三元组，不接受请求覆盖。LocalTest 只使用独立 Registry/selector，共用 Orchestrator/Worker，无私有 ack 协议。

上线顺序：默认 off 合入并完成 CI/专用环境对等证据→按 Worker 小组 on→观察低基数指标、安全日志、SSE、终态与原始延迟→逐步扩大。记录部署前后存量 queued/running/terminal 行可读、混合 claim 不串 row、在途按取消/Lease 收敛、terminal 不被重写。异常时全部 off 滚动重启；无需 Alembic downgrade、数据修复或客户端变更。

> 修订（2026-11-12，R17）：T11 quickstart 实测中显式 on 的 published Run 已完成且无 error_code，但容器没有 `path=orchestrator` 日志；Worker logger 为 INFO 记录，root WARNING 使其被过滤。受控路径日志是验收与运行观测契约，缺失属于部署缺陷，不能仅靠单元测试中的 caplog 通过来关闭。
>
> quickstart 的 supervisor API 命令通过 `--log-config /app/deploy/uvicorn-logging.yaml` 加载专属 YAML；该文件随 quickstart image 复制到 `/app/deploy/`。配置只为 `agent_platform.core_platform.agent_runtime.worker` 设置 INFO、专属 stdout handler 与 `propagate: false`，并设 `disable_existing_loggers: false`；root 保持 WARNING，uvicorn/access 默认 INFO handler 原样保留，其他既有 logger 不被禁用或降敏。Worker 继续使用 `logger.info`，不在 import 时配置 logging，不改成 warning，不增加 secret、异常原文、input/config/history、私有 row 或其他敏感字段；off 路径仍不产生 orchestrator 日志。聚焦测试必须实际加载该 uvicorn 配置并验证 Worker INFO 可见、root WARNING、既有 logger 保留与配置接线；T11 重建 quickstart 后仍须以真实 on/off Run 复验，单测不能替代 live 证据。

> 修订（2026-11-12，R18）：最终跨阶段评审发现正常 Outcome 在 `repository.finish` 前先记录 completed/failed；若 finish 普通失败，既有异常处理器会再记 failed 并重试 finish，形成 completed+failed 矛盾双日志。正常 Outcome 的受控终态 INFO 必须移到对应 `repository.finish` 成功返回之后；finish 抛错时不得先记正常 Outcome，只由既有异常路径记录一次 failed。Repository 仍是唯一终态写者，first-commit-wins、stale/no-op、Memory、off legacy 及异常/取消控制流全部不变。
>
> R18 仅允许修改 `backend/src/agent_platform/core_platform/agent_runtime/worker.py` 与 `backend/tests/test_runtime_baseline.py` 的聚焦范围。故障注入必须覆盖 completed Outcome 的 completed finish 首次普通异常、failed finish 随后成功，断言 `finish_statuses=['completed','failed']` 且只有一条 failed、无 completed；另断言正常 finish 成功返回后才产生日志的顺序。T11 使用最终代码重建后只需最小复测一个 on Run 与 off 回滚日志，验证 on 仅一条与真实终态一致的日志、off 无 orchestrator 日志；本任务不自行重建 quickstart。

## 9. 测试、性能证据、报告与验收后种子

详细用例见 04，验收见 05，任务顺序见 08。T8 实际逐条测试后才创建双语 06，T9 实际逐项验收后才创建双语 07，不得预写通过。

功能出口与性能子指标分离：P2 功能 UT/IT/CM 必须全部通过，P2-CM-08 的证据诚信/测量边界也可独立通过；真实外部模型/工具环境缺失时，仅性能子指标为 `pending_env`，不得用 test double 宣称生产性能。T9 此时最多有条件通过，不能写完全通过。性能方法固定为 05 §4 的同环境同脚本、至少 30 matched pairs、5 组 warm-up 不计样本、nearest-rank p95 和原始开销/外部模型时延边界。

用户明确要求开发、测试、正式验收全部完成后才新增示例种子：T10 新建 Phase 2 专属、幂等、低敏、可识别命名空间的数据，使用现有 schema/API/已发布快照，不加 Engine 字段、迁移或 UI，不伪造 Agent ID；覆盖 published-snapshot 与 no-snapshot legacy base-runtime 的 off/on 场景。T11 在 quickstart 验证默认 off、显式 on、内嵌 Worker、内部/Open SSE、路径日志与 off 回滚，不新增服务。实际结果作为验收后验证附录追加到既有 06/07，绝不重写先前证据；失败重开缺陷及受影响验收项。
