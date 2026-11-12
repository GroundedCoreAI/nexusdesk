# Phase 2 · React Provider 与执行编排器 — 实施拆解与设计裁定

> 状态：本地 T2～T11 与 R17 live 验证已完成，R18 生产修复及聚焦验证已完成，详见 06/07 及相应附录；R18 最小 live on/off 已完成；总体仍有条件通过
> 创建：2026-11-10
> 修订：2026-11-12（R18：Worker 终态日志必须晚于正常 finish 成功；当前状态统一）
> 依据：`01-business-goals.md`（G1～G4）、`02-requirements.md`（US-1～US-4、FR-1～FR-6、AC-1～AC-9）、`03-technical-design.md`、`04-test-plan.md`、`05-acceptance-plan.md`（R1～R18）；backend 基线 `0a6c4b5`

## 1. 使用方式与全局门禁

1. 严格按 **T1→T2→T3→T4→T5→T6→T7→T8→T9→T10→T11** 执行；每项完成标准与证据齐备后才进入下一项。除文档评审外，不得把后续任务并行解释为绕过依赖。
2. 设计冻结时，本拆解只授权设计、不授权实现、提交、推送、PR、正式测试或验收；这是历史门禁，当前进度以状态头及 06/07 为准。实施时若发现新冲突，先新增连续 R 编号并同步中英文 01～05/08，再改代码。
3. 全程不新增/修改 Alembic 迁移、ORM、公共 HTTP/SSE schema 或前端；不改 Phase 1 DTO/Registry/LocalTest、RuntimeEngine/Factory 既有职责、Repository/hooks 终态语义，不写第二套 ReAct。
4. 代码合入、自动化测试、人工验收分别记录。T8 实际逐条测试后才新建双语 06，T9 实际逐项验收后才新建双语 07；当前禁止创建或预写通过。
5. 只有 T8 测试与 T9 正式验收完成后才执行 T10 新示例种子和 T11 quickstart 验证。T11 只向既有 06/07 追加附录，失败重开缺陷及受影响验收项。
6. 各任务的“验收证据”是该任务未来完成时必须提交的材料，不表示当前已经取得。本地只声称实际运行的检查；全量套件由 CI 执行，不能把计划或 skip 写成通过。

## 2. 文档与现实不一致清单及冻结裁定（R1～R18）

### R1 — 基线、迁移与阶段状态

- 基线为 merge `0a6c4b5`；Phase 1 代码已合入 integration，但这不等于自动化全量测试或正式人工验收。Phase 2 当前仅设计冻结。
- 2026-11-10 只读执行 `uv run --directory backend alembic heads`，实测 `0057_industry_pack_runtime (head)`；这只是当次观测，不是永久常量。
- Phase 2 不新增/修改迁移、ORM、公共 HTTP/SSE schema、前端。实施和测试动态核验 heads、空库 upgrade/current、前后迁移版本目录清单/哈希零漂移，禁止 downgrade 或修改已应用历史迁移。

### R2 — Execution 与 Agent 身份

- 公共 `ExecutionRequest.execution_id` 保持 Phase 1 UUID 字段且必须为精确 stdlib UUID，值直接等于 claimed `runtime_runs` row ID，不另造 Execution ID；ExecutionContext 私有边界的受控规范化、临时 canonical parse 和原 row 保留严格按 R16，不得把私有 canonical parse 误解为公共字符串化。
- 有快照时严格解析 `config.agent.id` 的真实 UUID；缺失、畸形、nil 安全失败，不 fallback 到 base_runtime，不借 Run/conversation UUID 充当 Agent。
- 仅无快照 React + legacy `base_runtime` 可在 Request 内部使用 `UUID(int=0)` 作为匿名未绑定兼容哨兵；Phase 3 以正式身份模型移除，Phase 1 DTO 不变。
- nil 不得进入 selector、授权、tenant/credential/Agent 查询、DB、HTTP/SSE、日志、指标或 engine_metadata；RuntimeFactory 保持原 no-snapshot 分支，不得用 nil 查询 Agent。

### R3 — Registry 与同步/异步装配

- Registry factory 保持同步、零参、fresh-instance；禁止异步工厂及同步 resolve 中 await。
- Orchestrator 在一个同步无 `await` 区段 set 私有 execution `ContextVar`，间接调用 `registry.resolve`，并在 `finally` reset；应用零参工厂读取、校验并把 `ExecutionContext` 与 RuntimeFactory 捕获到新 ReactAdapter，Adapter 之后不再读 ContextVar。**Context 不含 worker_emit 或 runtime_emit**。
- `worker_emit` 是 Worker→`orchestrator.execute(context, worker_emit)` 的独立参数，是唯一沿用旧 Worker 写 Repository/Notifier 的回调，仅 Worker/Orchestrator 可持有；Factory/PlatformTools/RuntimeEngine 不得触达。
- Adapter runner 创建私有 `runtime_emit`，以同一 claimed row、同一函数对象同时传给 `await RuntimeFactory.for_run(row, runtime_emit)` 和 `runtime.run(..., runtime_emit, ...)`；它只做 `(kind,data)→AgentEvent→React 私有流`，不得直接写 Repository/Notifier。Core 不 import applications/business，由应用组合根注入能力。
- 缺失 Context、错误类型、Context 覆盖、重复 start 和工厂异常安全失败并清理；`agent_model_required` 在 Adapter 生命周期保留 legacy code，不能吞成 `adapter_factory_failed`；开启路径失败不得静默回退 legacy。
- 确定性测试和 spy 覆盖 task 并发隔离、嵌套 reset、resolve/工厂异常清理、Context 缺失/覆盖、for_run/run 同一 runtime_emit、事件只能经公共流后由 Orchestrator 调 worker_emit，以及多 Run 不共享 row/history/双 emit/queue/runner/result。

### R4 — 公共结果、私有 Outcome、错误与 usage

- 公共 `ExecutionResult` 只安全暴露 `ExecutionErrorCode`、静态 message 和 Phase 1 既有字段；私有 `ExecutionOutcome` 显式携带 output、history、dropped、legacy error code、非 optional usage 等，不经 engine_metadata/Context 增传 HTTP/SSE 字段。
- history/dropped 仅成功执行时返回 Worker Memory 完成钩子；失败/取消不返回。usage 不得为 `None`；React v1 当前 Runtime 只返回 output/history/dropped，无聚合输入时公共 Result 与私有 Outcome usage 都为 `{}`，不是既有聚合或伪造零 token；`model.completed` usage 逐字保留，不从事件另造 Result 聚合。
- 错误矩阵按 03 §6.1 覆盖 Phase 0 全来源：除 Engine/Factory 字面错误外，包含 `model_resource_not_found/model_resource_disabled/model_profile_version_not_found/model_input_too_large/model_tools_not_supported`、`model_provider_unavailable/model_rate_limited/model_provider_rejected/model_transport_error`、`content_blocked_input/content_blocked_output`、`gateway_concurrency_exceeded/gateway_request_quota_exceeded`、`model_credential_unavailable/model_response_too_large/model_stream_interrupted`；`model_stream_not_supported` 当前走 fallback。RuntimeFault `model_timeout` 与外层 `run_timeout` 分离，保留/畸形事件和 ack 协议错误为安全 protocol_error。
- 所有 RuntimeFault 即使未来未知，也在私有 legacy_error_code 逐字保留原始 code；公共按已知表或 internal_error 安全 fallback，不复制 Provider/Domain 文本。未知普通异常和普通 stream/worker_emit 失败为公共 `internal_error` + legacy `execution_error`；stale/cancelled/expired append 的 CancelledError 是控制流，不进入普通错误映射。
- 显式 cancel 无 ExecutionError；heartbeat lost 由 Worker 得 failed/worker_lost；调用方 CancelledError 清理后重抛。不得泄露 Provider 原文、stack、input/config/history、秘密或 nil。

### R5 — Adapter 能力、公共契约与 LocalTest 边界

- 身份固定 `react/native/v1`；`streaming/cancellation/tool_calling/native_events=true`，`persistent_session/session_resume/human_approval/interactive_input/file_operations/terminal_execution/workspace_required=false`。
- 每实例 fresh 且仅一个 active execution，完整实现 start、stream_events、cancel、collect_result、get_capabilities 五方法，不改公共签名/DTO。
- 必须按 03 §4.2 对公共 `adapter_contract_suite.py` 的 **25 个函数逐项裁定**：19 个原函数复用，其中列明的流式用例在测试 harness 显式 `anext→await worker_emit→acknowledge`；6 个原函数排除并执行指定私有替代，不得只写“适用公共契约”。私有协议测试直接使用 raw stream，公共五方法不变。
- 公共 AsyncIterator 无下游 ack，不能声称它自行证明更强 delivery 语义；Core 私有 runtime-checkable `AcknowledgingEventStream` 与 React 私有测试另行证明 ack identity/exactly-once/abort。
- LocalTest 无私有协议，保持 claim 前入队、terminal 丢弃和 `yield = delivery`，使用独立 Registry/selector，复用同一 Orchestrator/Worker，不与生产 react Registry 混用。

### R6 — 事件、背压、确认与终态发布

- 所有合法普通业务事件原名、相同 JSON payload 经私有 runtime_emit→React 私有流→公共 stream→Orchestrator worker_emit 透传，包括 `model.delta`、`knowledge.retrieved`、`memory_search.completed` 和扩展事件，无 allowlist；Adapter 原始 `run.*`、`tool.replay` 或畸形事件在 worker_emit 前安全 protocol_error。
- `run.*` 仅 Repository，`tool.replay` 仅 DurableToolReplayCache；`model.delta` 经同一双 emit/ack 边界后仍由 worker_emit 走 Notifier best-effort，无 DB seq/replay。AgentEvent 使用 UUID event_id、UTC timestamp、Adapter-local 单调 sequence、`source=engine_native`，不改变 DB event_seq/SSE ID。
- start 创建 runner 和关闭的首发 gate；`stream_events` 同步 claim 返回前把 never-claimed 原子改为 claimed-active 并放行，runner 此前不得向流发射，start→立即 stream 首事件不丢。正常 Orchestrator 固定 start→claim→放行→drain→collect，不依赖竞态。
- 单独 no-stream collector 在 never-claimed 时显式选择 **React 私有 no-stream suppression** 并放行；事件不入队、不阻塞，之后 stream 为空/按终态结束且无 replay，**不再声称等同 LocalTest**。collect/stream 首次选择在同一状态锁下先到先赢。
- 明确定义 never-claimed、claimed-active、closed、terminal；cancel/aclose 唤醒首发 gate 和 put/get，closed 后不可再次 claim，never-claimed 的 no-stream/cancel terminal 后首次 stream 为空。LocalTest 保持自己的 claim 前入队、terminal 丢弃、yield=delivery。
- 推荐 Condition + bounded deque，统一跟踪上述状态、producer finished、terminal published、queued/in-flight undelivered、已结算 ack identity、pending result、shielded terminal future 和 runner。队列容量至少 1，仅限制 queued buffer，可另有一个 yield 中 in-flight；活跃流满时等待 Condition。
- Core 私有 `AcknowledgingEventStream` 为 `AsyncIterator[AgentEvent]+acknowledge(event)+abort(error)/aclose`，不 import React。pop/yield 不是 React delivery；Orchestrator 成功 await worker_emit 后才按 execution_id/event_id 匹配当前唯一 in-flight ack，exactly-once 扣减；重复已结算 ack 幂等，错误身份/无 in-flight/乱序/跨 execution ack 安全 protocol_error 并 abort，绝不裸 yield 自动 ack。
- runner 正常结束先存 pending result；producer finished 且 queued+in-flight undelivered=0 后发布唯一 Result，空闲未关闭 claimed stream 不阻塞 collect。正常 Orchestrator 先 drain stream 再 collect，Worker 最后 finish，保证 Repository 的 run.* 终帧最后。
- cancel、aclose、普通 stream/worker_emit 失败原子抑制队列和迟到事件、唤醒 gate/put/get、取消并 drain runner、抑制迟到成功。显式 cancel 是 Adapter 内部 first-terminal-wins，得无 output/error cancelled Result，且已完成 Result 不追溯取消；普通失败为 failed 非 cancelled。
- stale/cancelled/expired `worker_emit→Repository.append` 抛 `asyncio.CancelledError`，不 ack、不持久化，Orchestrator/Adapter abort/aclose 后重抛，不改原终态、不归普通 execution_error；stale/terminal/wrong-owner/expired finish 才静默 no-op。
- runner stream/protocol failure 安全抛给 stream consumer，按 delivered 解除等待，再发布 failed Result；Notifier 已吞掉的指定 PG/OS delta 失败正常 ack，其他异常按 worker_emit 失败。
- 单独 no-stream collector 取消停止执行；共享 collectors shield；调用方 CancelledError 清理后重抛。所有 owned tasks 最终 await/done；只承诺协作式协程在外层 timeout 下有界 drain，不承诺强杀非协作协程。
- 使用 Event/gate 和双 emit spy 的确定性测试覆盖首事件、四种流状态、queue size 1、多事件慢 worker_emit、ack identity/重复/乱序、立即/并发/重复 collect、阻塞生产/消费 cancel、aclose、append/Notifier failure、两种持久提交顺序、迟到事件/结果与任务完成；不得靠 sleep 巧合。

### R7 — 新旧对等、SSE 与性能证据

- 串行确定性脚本比较 output、error、usage、成功 history/dropped、稳定 payload、顺序、每 Run 连续 seq、终帧位置和从各游标严格 replay。
- 并行工具按 call_id 对齐 started/completed，要求集合、局部 started→completed 偏序、模型轮边界一致；独立并行分支不要求跨路径全局顺序或绝对 seq 相同，无 call_id 的并行区域业务事件按每模型轮 multiset 比较。
- 仅 canonicalize：DTO event_id/timestamp/Run 实例与计时标识符；`model.completed.gateway_call_id/first_token_ms/duration_ms`；`tool.completed.gateway_call_id/duration_ms`。canonicalize 前验证字段类型、nullable、duration 非负。
- 不规范化 call_id、业务 document/chunk ID、工具参数/结果、output、error_code、usage，不全局删 ID。原始延迟独立作为性能证据，不能被 canonical diff 隐藏。
- 保留内部/Open SSE 的 Last-Event-ID、after、200+ drain、无 ID delta 不重放、隐藏 tool.replay 但推进 cursor、公共字段过滤和终帧位置；游标手工/typed 校验边界、400/422 及合法 max/strict replay 严格按 R15，并保留实际 ASGI/FastAPI 路由证据。

### R8 — Selector 与实现复用

- 生产组合固定可信 `react/native/v1`，不可由请求覆盖；无 latest、fallback、客户端 Engine 选择。
- LocalTest 仅独立 Registry/selector，同一 Orchestrator/Worker；复用现有 RuntimeEngine/RuntimeFactory，不写第二套 ReAct，不在 Worker 增加具体 Engine 分支。

### R9 — Worker、Settings、组合与 rollout

- Worker 仅在构造末尾增加 `orchestrator=None`，off 路径不变；on 调 `orchestrator.execute(context, worker_emit)`，把原事件回调作为独立 worker_emit，不放入 Context/Adapter；Repository 仍是唯一终态写者。
- `Settings.execution_orchestrator_enabled=False`，由 `AGENT_EXECUTION_ORCHESTRATOR_ENABLED` 覆盖；进程启动/滚动重启生效，非请求热切换。`backend/.env.example`、`deploy/production/.env.example` 和必要 compose 仅添加占位/插值，不新增服务或秘密。
- flag 排除在 runtime-composition fingerprint 外，off API/on Worker 与混合 Worker fingerprint 相同。共享组合根注册 EngineDescriptor(react)、ProtocolDescriptor(native)、AdapterDescriptor(react/native/v1)，构造同一 Orchestrator 并可选注入 Worker。
- rollout 记录存量 queued/running/terminal 行、混合 claim、在途取消/Lease 收敛和回滚；异常时全部 off 滚动重启，无需迁移、数据修复或客户端变更，开启失败不静默兜底。

### R10 — 取消、timeout 与 Lease 竞争

- 显式 `adapter.cancel` 是 Adapter 内部 first-terminal-wins，得无 output/error cancelled Result；已完成 Result 不追溯取消。Orchestrator 调用方 CancelledError 清理后重抛；普通执行/worker_emit 错误为 failed。
- Worker 用 `monitor_failure` 区分用户 cancelled 与 failed/worker_lost；失租不得伪装用户取消，model_timeout/run_timeout 不混淆。
- stale/terminal/wrong-owner/expired finish 静默 no-op；stale/cancelled/expired append 抛 `asyncio.CancelledError`，不 ack、不持久化、清理后重抛且不改原终态，不得写成 append no-op 或普通 execution_error。
- Run 持久层按提交顺序 **first-commit-wins**，不是无条件 cancel 优先：finish/reaper 先提交则 cancel no-op，cancel 先提交则 late finish 不改写；保留 reaper cancelled-with-worker_lost/queue_timeout 变体。确定性测试覆盖两种顺序及取消、timeout、完成、失租竞争，只有一个终态，无自动重试、Fencing Token 或副作用回滚新语义。

### R11 — 测试环境、观测与证据

- 真实 PG 使用独立新建 `pgvector/pgvector:pg17` Docker 容器、专用新 DB/卷，不复用旧容器。连接串仅存在仓库外权限受限 env，经 `TEST_DATABASE_URL`/`AGENT_DATABASE_URL` 注入，不打印。
- 覆盖 snapshot/no-snapshot off/on、success/error/timeout/cancel/lease、Memory summary/history/extract/reinforce/injection transactions、内部/Open SSE、跨租户、混合 Worker 和回滚；异步测试用 Event/gate，不用 sleep 决定结果。
- 指标仅低基数 path/tuple/status/error 标签，`run_id` 仅日志/trace；无秘密、nil、input/config/history 或原始异常。
- 06 对 04 每条测试独立记录，07 对 05 每个 A/C 项独立判定；本地、CI、人工证据分开。P2 功能 UT/IT/CM 必须全过，CM08 证据诚信/测量边界可独立通过。
- 性能严格按 05 §4：每个固定场景至少 30 matched pairs，5 组 matched warm-up pairs 不计样本，同环境/脚本/模型/Profile/工具配置并交替或平衡 off/on；nearest-rank p95 取排序后 1-based 第 `ceil(0.95×N)` 个，N=30 为第 29 个，目标 `p95(new)<=p95(old)*1.05`。原始 paired overhead、end-to-end、首 token、错误率分别保存，外部模型/工具时延不从端到端扣除。
- test double 仅功能证据，不得宣称生产性能；真实外部环境不足仅性能子指标为 `pending_env`，不否定功能出口，但 T9 最多有条件通过，不能写完全通过。

### R12 — 正式验收后的示例种子

- 用户明确要求开发、测试、正式验收全部完成后才新增示例种子；T1～T9 不创建 Phase 2 专属 seed，T9 使用受控 fixtures。
- T10 必须新增 Phase 2 专属、幂等、低敏、可识别命名空间的数据，不只是运行现有 seeds；只用现有 schema/API/published snapshots，不加 Engine 字段、迁移、UI，不伪造 Agent ID。具体数据形状可在 T10 实施前根据当前 seed 结构定稿，但不得改变这些门禁。
- 数据支持 published-snapshot 与 no-snapshot legacy base-runtime 的 off/on 场景；二次运行不重复、不覆盖运营修改。
- T11 用 quickstart 验证默认 off、显式 on、内嵌 Worker、内部/Open SSE、路径日志、off 回滚，不新增服务。实际结果作为验收后验证附录追加到既有 06/07，不重写旧证据；失败重开缺陷和受影响验收项。

### R13 — 累计精确 Core 模块与依赖方向测试维护

- 既有 `test_cumulative_t2_t3_t4_modules_and_dependency_direction_are_exact` 是 Core 源码模块清单与依赖方向架构门禁，不是公共 DTO 契约测试。Phase 2 在 T2/T3/T4 按实际新增源码累计更新其 `expected` 集合，始终要求 `actual == expected`，不得改成子集断言、过滤或忽略额外模块，也不得删除任何 Phase 1 条目或弱化既有依赖扫描；该测试专用维护不改变 Phase 1 实现或公共行为。
- T2 仅加入 `orchestration/__init__.py`、`orchestration/execution_context.py`、`orchestration/execution_lifecycle.py`、`adapters/react/error_mapper.py`；T3 届时再加入 `adapters/react/__init__.py`、`adapter.py`、`event_mapper.py`；T4 届时再加入 `orchestration/orchestrator.py`。T4 的应用层 `react_adapter_factory.py` 不在该 Core `rglob` 范围，不得加入此集合。T2 不得预填 T3/T4 模块。

### R14 — 私有 Outcome 收集与无协议 LocalTest 的确定性回退

- T4 的精确文件范围扩展为修改 `core_platform/agent_execution/adapters/react/adapter.py`、`orchestration/execution_lifecycle.py`，新增 `orchestration/orchestrator.py`、`applications/platform_runtime/react_adapter_factory.py`，并扩展 `tests/test_execution_orchestrator.py`、`test_react_engine_adapter.py`；R13 的 Core 精确模块集合仍只累计新增 `orchestration/orchestrator.py`，不得借 R14 新增其他 Core 模块。
- `execution_lifecycle.py` 增加 Core 私有 runtime-checkable `OutcomeCollectingAdapter` Protocol/helper：`async collect_outcome(handle) -> ExecutionOutcome`。helper 必须验证真实异步能力，描述符访问异常 fail closed；不得加入 Phase 1 `AgentEngineAdapter`/contracts/公开序列化，不得 import React。
- ReactAdapter 的 `collect_outcome` 复用 `collect_result` 的同一 terminal/no-stream/collector/cancellation 路径并返回内部已发布 Outcome。Orchestrator 对 React 只调用一次私有收集入口，不先后重复公共/私有 collect；Handle、共享/单独 collector 取消和唯一终态保持不变。成功返回真实 history/dropped，失败保留原 legacy code（包括未来未知 RuntimeFault），取消无 code；Orchestrator 不访问 `_execution`，私有字段不进入 Result/engine_metadata。
- LocalTest 不实现该私有协议。Orchestrator 仅在无协议时调用公共 `collect_result` 后转 Outcome：completed 默认 `history=[]/dropped=[]`，cancelled 无 code；failed 使用固定映射：公共 `execution_timeout→run_timeout`，其余公共 failed（包括 internal/protocol/simulated process 等）一律 `execution_error`。不得读取 message/details/Provider 文本，不得给 `ExecutionOutcome.from_result` 增加隐式错误码猜测；该 lossy fallback 不得用于 React。
- 增加协议检测、React 三类 Outcome、公共 Result 无私有字段、LocalTest 三类 fallback、Handle/collector/取消一致性、Orchestrator 不重复收集及不访问 `_execution` 的测试证据。

### R15 — 内部与 Open SSE 游标校验边界

- 内部 `Last-Event-ID` 继续由 handler 手工解析；无法解析为整数或其他非法值或超出 `[0,2147483647]` 时返回 `400 / invalid_last_event_id`，不得改成 422。
- 内部 `after` 以及 Open `after`、`Last-Event-ID` 继续由 FastAPI typed Query/Header 校验；类型错误或超出 `[0,2147483647]` 时返回 422，不得把 Open 422 改成 400。
- 合法游标继续以 `max(after,last_id)` 计算有效 after，并严格只重放 `seq>after`，不重复边界事件。
- Phase 2 不改变内部/Open SSE 路由、schema、状态码或错误体。R7、T6、T8 的 SSE 证据必须经 ASGI/FastAPI 实际路由分别覆盖内部手工 header 400、内部 typed after 422、Open typed after/header 422 及合法 max/strict replay；helper 单测不能替代路由证据。

### R16 — ExecutionContext 私有 Execution UUID 受控规范化与原 row 保留

- ExecutionContext 私有边界对 Execution UUID 做受控规范化：精确 stdlib `UUID` 原样返回并保持原对象身份；UUID 子类（包括 asyncpg 返回类型）经 `UUID(str(value))` 等受控值转换生成精确 stdlib UUID。规范化结果不得仍是子类。
- `row.id` 与传入 `execution_id` 分别规范化后以 `==` 做值相等检查，不再使用 `is`。公共 `ExecutionRequest.execution_id` 必须为精确 stdlib UUID，且值直接等于 claimed `row.id`；值不匹配安全失败。
- `context.row` 必须保留同一原 claimed Mapping（`context.row is claimed_row`）；原 `row.id` 不复制、不替换、不改写，包括保留其原对象身份、类型和值。`RuntimeFactory.for_run` 继续接收同一原 row，不得改为接收规范化后的副本。
- 字符串、整数、None、伪造非 UUID 全部拒绝为安全静态 `INVALID_REQUEST`。恶意 UUID 子类的 `__str__` 或描述符抛出的普通异常同样转换为安全静态 `INVALID_REQUEST`，不得泄露原异常文本/堆栈；`asyncio.CancelledError` 等控制流异常必须原样重抛，不得归入普通异常映射。
- 私有边界上的临时 canonical parse 不属于被禁止的公共字符串化，不改变 Phase 1 公共 DTO/schema/序列化形状。snapshot Agent 严格 UUID、受限 nil 哨兵和禁止借 Run/conversation UUID 的规则不变。
- T2 建立上述私有规范化与身份测试。R16 的 T6b 对等修复只允许修改既有 `backend/src/agent_platform/core_platform/agent_execution/orchestration/execution_context.py` 及对应测试，不允许修改公共 ExecutionRequest/DTO/contracts、Repository、RuntimeFactory、ORM 或迁移。P2-UT-01 覆盖普通 UUID、子类、伪造类型、恶意异常和控制流；P2-IT-18 必须经真实、未经 fixture 预先规范化的 asyncpg claimed row→Context→Request 链验证精确 stdlib UUID 与原 row 保留，T8 出口必跑，helper 单测或预转换 fixture 不得替代。

### R17 — Quickstart 必须实际输出受控 Worker INFO 路径日志

- T11 live quickstart 实测：显式 on 容器已启用 `execution_orchestrator_enabled=True` 与 embedded Worker，published Run 完成且 `error_code=null`，但没有 `path=orchestrator`；Worker logger level=0、effective/root=30、`propagate=True`，故 `logger.info` 被 uvicorn 默认 root WARNING 行为过滤。路径日志是验收与运行观测契约，不得把该现象解释为仅测试显示差异。
- 仅修改 quickstart 部署日志边界：新增 `deploy/quickstart/uvicorn-logging.yaml`，supervisor API 命令增加 `--log-config /app/deploy/uvicorn-logging.yaml`，Dockerfile quickstart stage 把该文件复制到 `/app/deploy/`。不改 compose 服务、schema、公共 API 或其他部署入口，不在 Worker import 时配置 logging。
- YAML 使用 `disable_existing_loggers: false`，只给 `agent_platform.core_platform.agent_runtime.worker` 配置 INFO、专属 stdout handler 和 `propagate: false`。root 保持 WARNING，uvicorn/access 默认 INFO handler 原样保留；不得全局升 INFO/DEBUG，不得把 Worker info 改成 warning，不得禁用或改变其他 logger 的敏感信息边界。off 路径不新增 orchestrator 日志，on 日志字段仍只允许原受控低基数字段与 `duration_ms`。
- 聚焦测试文件范围仅允许修改既有 `backend/tests/test_deployment.py` 和 `backend/tests/test_runtime_baseline.py`：前者增加配置测试，实际经 uvicorn 加载 YAML，断言 Worker INFO 记录可见、root WARNING、既有 logger 保留，以及 supervisor/Dockerfile 接线；后者仅允许在 `test_worker_off_with_injected_orchestrator_uses_only_legacy` 保留/新增 off 无 `path=orchestrator` 日志断言，不得借此修改其他测试。重跑受影响的 Worker 路径日志测试与 Ruff。T11 必须重建 quickstart，以真实显式 on 的 completed Run 看到路径日志并确认默认/off Run 无 orchestrator 日志；这些自动化结果不是 live 通过证据。

### R18 — 正常 finish 成功前不得发布 Worker 终态日志

- 最终跨阶段评审发现：正常 Outcome 在 `repository.finish` 前先记 completed/failed；finish 普通异常后，既有异常处理器又记 failed 并重试 finish，可能出现 completed+failed 矛盾双日志。正常 Outcome 的受控 INFO 只能在对应 finish 成功返回后记录；finish 抛错时只由既有异常路径记录一次 failed。
- 生产与测试代码范围严格限于 `backend/src/agent_platform/core_platform/agent_runtime/worker.py` 和 `backend/tests/test_runtime_baseline.py` 的 R18 聚焦用例。不得改变 Repository 唯一终态写者、first-commit-wins、stale/no-op、Memory、off legacy、异常/取消控制流或公共 API/compose。
- 新增故障注入：orchestrator completed，completed finish 首次普通异常，failed finish 随后成功；断言 `finish_statuses=['completed','failed']`，受控日志只有一条 failed 且无 completed。另验证正常 finish 成功返回与日志的严格先后顺序。只跑新增用例、相关 Worker path-log/deployment 聚焦测试与 Ruff，不重跑旧全套。
- 同步 06/07 的 R18/总评审追加记录；07 的 T9 汇总统一为 10 个 case-executing pytest 命令、356 例次、354 通过、2 失败，保留首次 A1/A2/A5 的 32 passed+1 failed 和 Gateway 18 passed+1 failed，修正重跑不增加唯一覆盖。T11 用最终代码重建后最小复测一个 on Run 与 off 回滚日志；生产性能、CI、真实部署 canary、人类 UAT/签字和持久归档继续 pending，结论仍有条件通过。

## 3. 任务依赖总览

| 任务 | 名称 | 直接依赖 | 主要溯源 |
|---|---|---|---|
| T1 | 设计/R 冻结 | Phase 1 merge 基线 | 全部 G/US/FR/AC、R1～R18 |
| T2 | Context/Outcome/身份/纯 mapper | T1 | FR-1/2/3/5、AC-1/3/5/9、R2～R4/R10/R13/R16 |
| T3 | ReactAdapter/events/backpressure | T2 | FR-1/4/5、AC-3～7、R3～R6/R10/R13 |
| T4 | Orchestrator/binding/selector | T3 | FR-2、AC-1/3/5/8、R3/R5/R8/R13/R14 |
| T5 | Worker/Settings/composition | T4 | FR-3/6、AC-3/8/9、R9/R10 |
| T6 | parity/PostgreSQL/SSE/cancel-timeout-lease 集成 | T5 | 全部 FR/AC、R1～R11/R15/R16 |
| T7 | rollout/quickstart runbook/mixed Workers/rollback | T6 | FR-6、AC-8/9、R9/R11 |
| T8 | 正式测试与双语 06 | T7 | 04 全部主用例、AC-1～9、R11/R15/R16 |
| T9 | 正式验收与双语 07 | T8 | 05 全部主 A/C、R11/R12/R16 |
| T10 | 新示例 seed | T9 | FR-6、AC-8/9、R12 |
| T11 | seed 后 quickstart 验证与 06/07 附录 | T10 | AC-4/8/9、R11/R12/R17/R18 |

## 4. 任务明细、完成标准与证据

### T1 — 设计与 R1～R18 冻结

- **依赖/输入**：Phase 1 merge `0a6c4b5`；只读核查 DTO、Worker、composition、seed、compose 和动态 Alembic head。
- **精确文件**：修改本主题 `README.md`/`README.en.md`；本阶段 `01-business-goals`、`02-requirements`、`03-technical-design`、`04-test-plan`、`05-acceptance-plan` 的中英文；新增本文件中英文。不得新建 06/07。
- **溯源**：全部 G1～G4、US-1～US-4、FR-1～FR-6、AC-1～AC-9、R1～R18。
- **完成标准**：所有冲突直接在 01～05 修正；中英文实质同步；文件级设计、完整测试/验收矩阵、T1～T11 依赖和证据门禁一致；无实现代码、无预写通过。
- **验收证据**：双语 diff、只读路径/编号/残留冲突检查、`git diff --check` 和设计评审记录；文档冻结不等于开发、测试或人工验收完成。

### T2 — ExecutionContext、ExecutionOutcome、身份与纯错误映射

- **依赖**：T1。
- **精确文件**：新增 `backend/src/agent_platform/core_platform/agent_execution/orchestration/__init__.py`、`execution_context.py`、`execution_lifecycle.py`；新增 `backend/src/agent_platform/core_platform/agent_execution/adapters/react/error_mapper.py`；新建/扩展 `backend/tests/test_execution_orchestrator.py`、`backend/tests/test_react_engine_adapter.py` 的纯函数/身份用例；按 R13 仅更新 `backend/tests/test_local_test_adapter.py` 的 T2 累计精确模块集合。不得在此任务实现 Orchestrator、修改 Phase 1 DTO 或 LocalTest 实现。
- **溯源**：FR-1/2/3/5；AC-1/3/5/9；R2/R3/R4/R10/R13/R16；P2-UT-01/04/06/12/14/15，后续 A1/A3/A5/A7。
- **完成标准**：R16 的 Execution UUID 私有受控规范化可执行：精确 stdlib UUID 保持原对象、UUID 子类受控转换为精确 stdlib、row.id 与 execution_id 分别规范化后以 `==` 检查值相等而非 `is`，公共 Request 使用精确 stdlib UUID；Context 保留同一原 claimed Mapping，原 row.id 不复制/替换/改写，RuntimeFactory 继续收原 row；伪造输入和恶意普通异常安全静态 `INVALID_REQUEST`，控制流异常重抛。真实 Agent/受限 nil 规则可执行；私有 Context 不含任何 emit，Context/Outcome 不进入公共序列化；同步 ContextVar scope 可嵌套、并发隔离、异常复位。`execution_lifecycle.py` 同时定义 Outcome 与 Core 私有 runtime-checkable `AcknowledgingEventStream`/helper（AsyncIterator+acknowledge+abort/aclose），不 import React；完整 Phase 0 全来源及未来未知 RuntimeFault/timeout/未知异常纯映射，未知 code 私有逐字保留、公共安全 fallback；React v1 无聚合输入 usage={}，成功 Memory 值边界明确；Core 无应用反向依赖。
- **验收证据**：上述测试实际节点与结果、身份/usage/03 §6.1 全错误矩阵逐行输出、未来未知 code、Protocol runtime-checkable/依赖方向、公开序列化静态检查；R16 普通 UUID 原对象、UUID 子类、伪造类型/值不匹配、恶意 `__str__`/描述符普通异常、安全静态 `INVALID_REQUEST`、控制流重抛、原 Mapping/row.id 保留和 RuntimeFactory 原 row spy 证据；R13 累计精确模块集合同步且完整 Phase 1 相关组无 deselect 通过，依赖门禁不弱化；未执行项保持 pending。

### T3 — ReactAdapter、开放事件映射与私有 ack-aware 状态机

- **依赖**：T2。
- **精确文件**：新增 `backend/src/agent_platform/core_platform/agent_execution/adapters/react/__init__.py`、`adapter.py`、`event_mapper.py`；扩展 `backend/tests/test_react_engine_adapter.py`；按 R13 在 `backend/tests/test_local_test_adapter.py` 累计加入本任务的三个 Core 模块。复用 Phase 1 公共契约测试但不修改其公共 DTO/Registry/LocalTest 实现。
- **溯源**：FR-1/4/5；AC-3/4/5/6/7；R3/R4/R5/R6/R10/R13；P2-UT-02/03/05/07/15～21，后续 A3～A7。
- **完成标准**：固定身份/能力、五方法、fresh 单 active 实例；Adapter runner 创建私有 runtime_emit 并同时传 for_run/run，普通事件只进 React 私有流、伪造 run.*/tool.replay 在 worker_emit 前拒绝。实现关闭首发 gate、stream 同步 claim 放行、显式 no-stream suppression、never-claimed/claimed-active/closed/terminal、先到 collect/stream、cancel/aclose 唤醒；容量至少 1 queued buffer、唯一 in-flight、ack identity/exactly-once/重复 settled 幂等/错误 ack abort、pending result、shielded future、drain/collect 和唯一终态全部实现。空闲 claimed stream 不阻塞 collect，stale append CancelledError 不 ack、不持久化、清理后重抛，owned tasks 可清理。
- **验收证据**：按 03 §4.2 列出公共 suite 25 函数的 19 复用/6 排除及私有替代，流式公共用例显式 worker_emit/ack；双 emit spy、首事件、no-stream/closed/terminal、容量 1、慢 worker_emit、ack 对抗、collector、aclose、append/Notifier、两种竞态与任务 done 的 Event/gate 输出；R13 累计精确模块集合同步且依赖门禁不弱化；不能以 LocalTest yield=delivery 代替 React 私有协议证据。

### T4 — Orchestrator、应用 binding 与固定 selector

- **依赖**：T3。
- **精确文件**：修改 `backend/src/agent_platform/core_platform/agent_execution/adapters/react/adapter.py`、`orchestration/execution_lifecycle.py`；新增 `backend/src/agent_platform/core_platform/agent_execution/orchestration/orchestrator.py`、`backend/src/agent_platform/applications/platform_runtime/react_adapter_factory.py`；扩展 `backend/tests/test_execution_orchestrator.py`、`backend/tests/test_react_engine_adapter.py`；按 R13 在 `backend/tests/test_local_test_adapter.py` 累计加入 `orchestration/orchestrator.py`，不得加入应用 factory。保持 `backend/src/agent_platform/applications/platform_runtime/runtime_factory.py` 既有 ReAct 构造职责，不加 Engine 分支；组合根接线留给 T5。
- **溯源**：FR-2；AC-1/3/5/8；R3/R5/R8/R13/R14；P2-UT-08/09/14/15/16/21，P2-IT-04/14 的可单测部分，后续 A1/A3/A5/A8。
- **完成标准**：生产 selector 固定 react/native/v1 且无请求覆盖/latest/fallback；`execute(context, worker_emit)` 独立接收原 Worker 回调，同步 set→resolve→finally reset、零参 fresh factory 捕获不含 emit 的 Context；start→同步 claim stream/放行→公共取事件→await worker_emit→检测 React 私有 ack 协议后 ack→drain，Factory/PlatformTools/RuntimeEngine 无 worker_emit 路径。React 经 Core 私有 `collect_outcome` 仅收集一次，复用既有 Handle/collector/取消路径并保留真实 history/dropped 和原 legacy code；LocalTest 无 Outcome 协议时仍 await worker_emit、无额外 ack、yield=delivery，仅经公共 `collect_result→ExecutionOutcome.from_result` 确定性回退。各阶段异常 abort/aclose，append/调用方 CancelledError 清理后重抛；支持 LocalTest 独立 Registry/selector 注入而不改 Worker 核心。
- **验收证据**：有效/未知/禁用组合、Context 并发/嵌套/异常、多 Run 隔离、双 emit spy、ack/Outcome 协议检测及描述符 fail closed、首发 gate、worker_emit 后 ack、abort/aclose、append 控制流与各阶段失败、LocalTest 三类 fallback 与 React 三类 Outcome、未知 RuntimeFault 原 code、公共 Result 无私有字段、React 不重复 collect 且不访问 `_execution`；R13 累计精确模块集合同步且依赖门禁不弱化；调用链证明 for_run 不在同步 factory 内执行，Core/Worker 无 Engine 或应用反向依赖。

### T5 — Worker 可选注入、Settings 与共享组合根

- **依赖**：T4。
- **精确文件**：修改 `backend/src/agent_platform/core_platform/agent_runtime/worker.py`、`backend/src/agent_platform/core_platform/platform_services/platform_settings/settings.py`、`backend/src/agent_platform/applications/platform_runtime/runtime_composition.py`；修改 `backend/.env.example`、`deploy/production/.env.example` 及必要的 `compose.yaml`、`deploy/quickstart/compose.yaml`、`deploy/production/compose.yaml` 插值；扩展 `backend/tests/test_execution_orchestrator.py`、`backend/tests/test_runtime_baseline.py`。
- **溯源**：FR-3/6；AC-3/8/9；R9/R10；P2-UT-10/11/12/13/23/24，后续 P2-IT-12/18、A3/A8/A9。
- **完成标准**：Worker 仅末尾 `orchestrator=None`，off 代码路径保持原行为；on 将原事件回调作为独立 worker_emit 调 `orchestrator.execute(context, worker_emit)`，使用 Outcome 且仅成功传 Memory history/dropped，最后由 Repository finish；monitor_failure/失租不变，stale finish no-op、stale append CancelledError 控制流及 Run first-commit-wins 不改；默认 false、启动生效、flag 不进 fingerprint；组合注册固定三元组并可注入，LocalTest 独立 selector；无新增服务、秘密或公开配置字段。
- **验收证据**：off/on 分支、worker_emit 独立传参和 Outcome→finish 映射、fingerprint 等价、配置解析、Memory/取消/失租、append/finish 与两种提交顺序、组合描述符与低基数观测测试；off 基线 diff 和 compose 配置渲染检查，不能仅凭代码审阅声称运行验证。

### T6 — 对等、真实 PostgreSQL、SSE、Memory 与取消/timeout/Lease 集成

- **依赖**：T5。
- **精确文件**：完成 `backend/tests/test_react_engine_adapter.py`、`test_execution_orchestrator.py`；扩展 `backend/tests/test_runtime_baseline.py`、`test_runtime_postgres.py`、`test_open_platform.py`、`test_agent_config_execution_compat.py`、`test_memory_injection_postgres.py`、`test_memory_customers_postgres.py`、`test_memory_events_postgres.py`、`test_memory_governance_postgres.py`、`test_memory_postgres.py`、`test_memory_summary.py`。必要时只新增测试辅助 canonicalizer，放在 `backend/tests/test_execution_orchestrator.py`，不得进入生产公共 DTO。R16 的 **T6b** 对等修复只允许额外修改既有 `backend/src/agent_platform/core_platform/agent_execution/orchestration/execution_context.py`，并在既有 `backend/tests/test_execution_orchestrator.py`、`backend/tests/test_runtime_postgres.py` 修复/新增对应单测与真实 asyncpg 用例；不得借 T6b 修改 Phase 1 公共 ExecutionRequest/DTO/contracts、Repository、RuntimeFactory、ORM 或迁移，也不得扩大其他生产源码范围。
- **溯源**：全部 FR-1～FR-6、AC-1～AC-9、R1～R11/R15/R16；P2-UT-01/22 及 P2-IT-01～20、P2-CM-01～08；A1～A9 自动化证据。
- **完成标准**：串行/并行对等及精确 canonicalization 原字段校验；独立新 pgvector PG17 DB/卷和受限 env；snapshot/no-snapshot off/on、真实 Memory 五类事务、内部/Open SSE、双 emit spy、首发 gate/no-stream/closed/terminal、容量 1/ack identity/aclose、公共 suite 25 函数逐项裁定、全来源及未来未知错误、append/finish 控制流、Adapter first-terminal-wins 与 Run 两种 first-commit-wins 顺序、双 timeout、失租/reaper/迟到、跨租户、存量行和混合 claim 全覆盖；R15 的内部手工 header 400、内部 typed after 422、Open typed after/header 422 和合法 max/strict replay 必须经实际 ASGI/FastAPI 路由验证，且路由/schema/状态码/错误体不变；R16 的 P2-UT-01 普通/子类/伪造/恶意异常/控制流及 P2-IT-18 真实未经 fixture 规范化的 asyncpg claimed row→Context→Request 链必须通过，证明公共 Request 精确 stdlib UUID、Context/RuntimeFactory 同一原 row 和原 row.id 对象/类型/值未改写；动态 heads/空库 upgrade/目录零漂移；所有 owned tasks done，原始延迟单独保存。
- **验收证据**：每条 P2-IT/CM 的实际 `文件::用例`、环境、结果和原始输出；双 emit/ack/公共 suite 精确清单、PG 容器/DB 非敏感标识、动态迁移输出、事件/replay diff、R15 三类非法游标边界及合法 max/strict replay 的实际路由请求/响应、R16 真实 asyncpg 返回类型、规范化前后对象/类型/值关系、Context/RuntimeFactory 原 row spy、原 row.id 未改写及安全错误/控制流证据、Memory 事务、append/finish 与两种提交顺序、清理和按 05 §4 采集的延迟样本。连接串不得出现在命令输出或报告；环境缺失不得 skip 后声称通过，helper 单测不得替代 R15 路由证据或 R16 真实驱动链，test double 不得宣称生产性能。

### T7 — Rollout/quickstart runbook、混合 Workers 与回滚演练

- **依赖**：T6。
- **精确文件**：新增 `docs/operations/agent-execution-orchestrator-rollout.md` 和 `.en.md`；修改 `docs/getting-started/quickstart.md` 和 `.en.md` 的默认 off/显式 on/回滚操作说明；沿用 T5 的 compose/env 文件，不新增服务。此任务不创建 Phase 2 示例种子。
- **溯源**：FR-6；AC-8/9；R9/R11；P2-IT-12/18、P2-CM-02/03/08；A8/A9、C4。
- **完成标准**：runbook 写明默认 off 合入、显式 on、off API/on Worker、混合 Worker 小组灰度、存量 queued/running/terminal 检查、低基数观测、原始延迟、异常全 off 滚动重启；quickstart 只说明受控开关和内嵌 Worker，不暗示请求热切换或自动 fallback；完成一次受控混合/回滚演练并保留待 T8 引用的原始证据。
- **验收证据**：双语文档、配置渲染、混合 claim/存量行/fingerprint/路径日志/回滚实际记录；确认回滚无 Alembic downgrade、数据修复、客户端变化或新服务。演练不预写为正式测试/人工验收结论。

### T8 — 正式测试与双语 06

- **依赖**：T7。
- **精确文件**：实际执行 04 主用例和受影响回归后，新增 `docs/requirement/agent-execution-platform-v2/phase-2-react-provider-orchestrator/06-test-report.md` 与 `.en.md`；缺陷修复可涉及 T2～T7 对应文件，但须先同步设计并重新回归。此任务不得创建 07 或 Phase 2 示例种子。
- **溯源**：04 的 P2-UT-01～24、P2-IT-01～20、P2-CM-01～08 及回归范围；AC-1～AC-9；R11/R15/R16；05 主验收进入条件。
- **完成标准**：每条用例有独立 `文件::用例`/环境/结果/证据行；所有功能 UT/IT/CM 全过，CM08 证据诚信/测量边界通过；P0/P1 为零，off diff 为零，受影响回归全绿，无迁移/ORM/公共路由/schema/状态码/错误体/前端变化或悬挂任务；P2-IT-05/06 和 CM05 按 R15 经实际 ASGI/FastAPI 路由分别验证内部手工 header 400、内部 typed after 422、Open typed after/header 422 及合法 max/strict replay，helper 单测不能替代；P2-UT-01 的 R16 普通/子类/伪造/恶意普通异常/控制流用例与 P2-IT-18 的真实未经 fixture 规范化 asyncpg claimed row→Context→Request 链必须实际通过，证明公共 Request 精确 stdlib UUID、Context/RuntimeFactory 原 row 和原 row.id 对象/类型/值保留，helper 单测或预转换 fixture 不得替代；CI 与本地分开，真实性能不足仅子指标 pending_env，06 如实记录缺陷、skip、风险和 CI 链接。
- **验收证据**：双语 06、实际命令/CI 链接/原始输出、R15 三类非法游标边界与合法 max/strict replay 的实际路由请求/响应及重放序列、R16 真实 asyncpg 返回类型、规范化前后对象/类型/值关系、Context/RuntimeFactory 原 row spy、原 row.id 未改写、安全静态 `INVALID_REQUEST` 与控制流重抛的实际测试记录、05 §4 性能样本或 pending_env 原因、缺陷修复与回归记录。功能出口全绿且 CM08 证据诚信通过才允许 T9；性能 pending_env 不阻止进入 T9，但 T9 最多有条件通过，不得把本计划中的预期写成结果。

### T9 — 正式验收与双语 07（受控 fixtures，无新 seed）

- **依赖**：T8 主测试出口满足。
- **精确文件**：新增 `docs/requirement/agent-execution-platform-v2/phase-2-react-provider-orchestrator/07-acceptance-report.md` 与 `.en.md`；只使用 T6 受控 fixtures 和 T7 部署证据，不新增/修改 seed 文件。
- **溯源**：05 的 A1～A9 主场景、C1～C5、业务/性能指标和签字表；全部 AC；R11/R12/R16。
- **完成标准**：每个 A/C 独立判定和证据；人工操作、真实环境、本地/CI 证据分开；结论为通过/有条件通过/不通过之一，遗留项有 owner/期限，签字真实。真实性能子指标 pending_env 不否定全绿功能出口，但本任务最多“有条件通过/待补性能证据”，不能写完全通过；明确 T10/T11 尚未执行，不能预写附录通过。
- **验收证据**：双语 07、签字表、原始操作/05 §4 性能或 pending_env/回滚/安全证据。只有 T8 测试和本任务正式验收均完成后才允许 T10；有条件通过的遗留性能证据仍是未完成项，不得当作完全通过。

### T10 — 新增 Phase 2 专属幂等示例 seed

- **依赖**：T8 和 T9 均实际完成；这是硬门禁，不可与 T6～T9 并行提前执行。
- **精确文件**：新增 `backend/src/agent_platform/applications/seed_execution_orchestrator.py` 和 `backend/tests/test_execution_orchestrator_seed.py`。只读参考 `backend/src/agent_platform/applications/seed.py`、`seed_demo_packs.py`；不修改现有 seeds、schema、Engine 字段、迁移、UI 或 compose 服务。具体低敏数据形状在本任务开始前按现有 seed 结构定稿并同步本任务说明。
- **数据形状定稿（2026-11-11）**：批次固定为 `execution-orchestrator-phase2-v1`；Connection/Model/Profile/Agent/Open Application 显示名分别以 `[Phase 2 Orchestrator] Demo Connection`、`[Phase 2 Orchestrator] Demo Chat`、`[Phase 2 Orchestrator] Chat Profile`、`[Phase 2 Orchestrator] Published Agent`、`[Phase 2 Orchestrator] Open Application` 为初始值。Connection 使用现有 `protocol="demo"` 且无凭据，Model 使用 `model_name="demo"`、`operations=["chat"]`、`tool_calling=true`，Profile 为真实发布的 Chat Profile；Agent `is_example=true`，仅绑定该 Profile 的已发布版本，不创建知识库或工具。Open Application 首次 `enabled=true`，`agent_ids` 仅含该 Agent，`agent_versions` 不固定版本，`knowledge_base_ids=[]`，不创建 App Key。
- **稳定身份与真实发布**：现有网关 `Catalog.save`、Agent `create`、Open Platform `save` 的新建路径均只生成随机 UUID，没有可持久化的 Phase 2 业务键；为免于依赖可改显示名，Connection/Model/Profile/Agent/Open Application 使用 `uuid5(NAMESPACE_URL, "agent-platform:{tenant}:execution-orchestrator-phase2-v1:{kind}:{key}")`，其中 `key` 分别为 `demo-connection`、`demo-chat`、`chat-profile`、`published-agent`、`open-application`。这些资源的确定性 INSERT 只建立经过现有 Pydantic 合同校验的元数据/草稿；Profile 与 Agent 必须分别经现有 `Catalog.publish`、`AgentService.publish` 生成真实 `gateway_profile_versions`、`agent_versions`，禁止手写 snapshot。会话仍走 `ConversationService.create`，以租户加 `external_id=phase2-orchestrator-published` / `phase2-orchestrator-legacy` 为稳定业务键；前者绑定真实 Agent UUID，后者 `agent_id=NULL`，不伪造 legacy Agent 或 nil UUID。
- **计数、输出与保留**：`created`/`preserved` 均且仅含 `connections`、`models`、`profiles`、`agents`、`conversations`、`open_applications` 六项；首次全创建时分别为 `1/1/1/1/2/1`，完整二次执行为 `created=0`、对应 `preserved=1/1/1/1/2/1` 且所有 ID 不变。入口仅输出上述两组计数及 `agent_id`、`agent_version`、`published_external_id`、`legacy_external_id`、`open_application_id`。所有已存在资源只保留不更新：不重复发布、不复活归档、不覆盖运营改名或 Agent 草稿、不重新启用或重授权 Open Application、不把已重绑定会话改回；使用租户+批次 advisory lock 串行化同一命名空间。不得创建消息、Run、runtime/open 事件、客户、工单、费用、请求/调用日志，不得写凭据或开关/env 文件，off/on 共用同一份数据。
- **溯源**：FR-6；AC-8/9；R12；P2-CM-09；A8 验收后附录、C5。
- **完成标准**：使用现有 runtime services/API/published snapshots 创建可识别 Phase 2 命名空间的数据，而非只重跑现有 seeds；published-snapshot 使用真实 Agent UUID，no-snapshot 场景不伪造 Agent；幂等且不覆盖运营修改；覆盖 off/on 所需两类示例，无生产凭据/客户数据。
- **验收证据**：首次与二次执行的创建/复用计数、命名空间和真实引用检查、跨租户/敏感信息检查、`test_execution_orchestrator_seed.py` 实际结果；不得把数据生成本身当作 quickstart 或验收通过。

### T11 — 新 seed 的 quickstart 验证与 06/07 验收后附录

- **依赖**：T10。
- **精确文件**：使用 T7 quickstart/runbook、T5 compose 和 T10 seed 模块；扩展 `backend/tests/test_execution_orchestrator_seed.py`；R17 缺陷修复另限新增 `deploy/quickstart/uvicorn-logging.yaml`，修改 `deploy/quickstart/supervisord.conf`、`Dockerfile`、`backend/tests/test_deployment.py`、`backend/tests/test_runtime_baseline.py`（仅限 R17 指定的单一 off 无 `path=orchestrator` 日志断言）与双语 03/08；R18 另仅限 `backend/src/agent_platform/core_platform/agent_runtime/worker.py` 和 `backend/tests/test_runtime_baseline.py` 的 R18 聚焦范围，并同步双语 01～05/08 的必要状态/R18 段；只向既有本阶段 `06-test-report.md`/`.en.md`、`07-acceptance-report.md`/`.en.md` 追加“验收后验证附录”，保留原报告正文和历史证据。
- **溯源**：AC-4/8/9；R11/R12/R17/R18；P2-CM-09/10；A8/C5 验收后附录。
- **完成标准**：在 quickstart 内显式运行新 seed，分别验证默认 off、显式 on、内嵌 Worker、published-snapshot/no-snapshot legacy base-runtime、内部/Open SSE、路径日志和全 off 回滚；无新增服务、迁移或公开字段；所有实际结果和限制逐条记录。
- **验收证据**：二次 seed 幂等结果、各配置的真实路径日志、双 SSE/replay、off 回滚、测试输出和双语 06/07 新增附录。任一失败重开缺陷及 A8/相关 C 项，修复并重跑后才恢复结论；不得删除失败记录或改写先前证据。

## 5. 最终可追溯性核对

- **FR/AC 覆盖**：T2～T6 覆盖 FR-1～FR-5，T5/T7 覆盖 FR-6；T6/T8 提供 AC-1～AC-9 自动化证据，T9 对 A1～A9/C1～C5 人工判定，T11 补 A8/C5 验收后附录。
- **R 覆盖**：R1/R11 由 T6/T8/T9 动态验证；R2～R4 由 T2～T4；R13 由 T2～T4 累计维护精确 Core 模块集合；R14 由 T4 完成私有 Outcome 收集与 LocalTest 确定性回退；R5/R6 由 T3/T6；R7 由 T6/T8/T9，R15 由 T6/T8/T9 提供双 SSE 实际路由证据；R8 由 T4；R9/R10 由 T5～T7/T9；R12 严格由 T9→T10→T11 顺序保证；R16 由 T2 建立私有规范化，T6b 在限定文件范围内修复，T6/T8 提供普通/子类/伪造/异常/控制流与真实 asyncpg 链证据，T9 按 A1/C2 人工验收；R17 由 quickstart 专属日志配置、聚焦测试和 T11 重建后的真实 on/off 路径日志复验闭环；R18 由 finish 故障注入、严格日志顺序聚焦测试及最终代码的最小 T11 on/off live 复测闭环。
- **保护面**：每个开发任务 diff 均检查无迁移、ORM、公共 HTTP/SSE schema、前端和 Phase 1 公共契约变化；任何必要变化都不是“顺手修复”，必须先新增 R 并重新评审。
- **报告时机**：设计期原计划为 06/07 分别在 T8/T9 实际完成后创建、T11 仅追加；当前 06/07 已存在，本地 T2～T11 与 R17 live 已完成，当前进度以 06/07 及其 T11/R18 附录为准，不得为了文档套件完整预写通过。
