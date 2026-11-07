# Phase 2 · React Provider 与执行编排器 — 测试方案

> 状态：待评审 / 待实施
> 创建：2026-11-02
> 依据：`02-requirements.md`（FR-1～FR-6、AC-1～AC-9）、`03-technical-design.md`（ReactAdapter、Orchestrator、SSE 等价、终态保护、默认关闭开关）

## 1. 测试范围与原则

**范围**：ReactAdapter 完整契约、Execution Orchestrator、Worker 新旧路径、注册解析、事件/SSE 兼容、错误/取消/超时/Lease 终态、全局开关、混合部署和回滚；不包含外部 Engine 或 Runtime Host。

**原则**：

1. **新旧等价必测**：使用同一模型/工具响应脚本分别执行 legacy 与 orchestrator，逐字段比较 output、history/dropped、事件、错误码和终态。
2. **开关兜底必测**：默认及显式关闭均走旧路径，关闭状态与 Phase 0 基线 diff 为零；开启失败不得静默回退。
3. **SSE 双接口必测**：内部和开放 API 分别验证持久事件、瞬态 delta、游标重放、终帧、过滤及脱敏。
4. **终态竞争必测**：取消/Lease lost 与成功同时发生时由真实 Repository 判定，不能只 mock finish。
5. **时间类用例不等待**：model/run timeout 用短配置或可控时钟，Lease 过期直接改库；异步用例结束无 pending task。

## 2. 测试环境与数据构造

| 环境 | 用途 |
|---|---|
| 单测（假 Registry/Adapter/Runtime） | Request/Outcome、React 五方法、映射、Worker 分支、错误和取消清理，无需 DB |
| 集成（PG 17 + 专用 TEST_DATABASE_URL） | claim/heartbeat/finish/cancel/reap、真实事件序号和 Repository 终态保护 |
| mock/demo 模型与 MockTransport | 可编程模型文本、工具调用、超时、非法响应；真实 HTTP 工具路径可重复 |
| ASGI 内部与开放 API | 内部 `/api/v1/runs/{id}/events` 和开放平台 SSE/回放/开放字段脱敏 |
| 双 Worker 配置组 | 同库混合 legacy/orchestrator 执行和滚动回滚演练 |

**数据构造约定**：复用 `test_runtime_postgres.py` 的专用租户、RunRepository 和 BusinessRuntimePersistenceHooks；新旧路径使用独立但相同 fixture/模型脚本。Agent 快照、summary/customer_memory/history 直接构造；Lease/queue 时间直接改库；不得使用生产凭据或客户数据。

## 3. 单元测试

| 编号 | 用例 | 预期 | 溯源 |
|---|---|---|---|
| P2-UT-01 | claimed row→ExecutionRequest 映射 | execution_id=run.id，tenant/conversation/input 正确；旧配置固定 react/native/v1，不接受客户端 Engine/Effective 能力 | FR-2、AC-1 |
| P2-UT-02 | ReactAdapter 身份、能力和 start 成功 | 属性为 react/native/v1，Handle execution_id 匹配，声明能力符合当前 React，未支持 Session/审批不显式开启 | FR-1、AC-3 |
| P2-UT-03 | React start→stream→collect 成功 | RuntimeEngine.run 仅由 Adapter 调用一次；output/usage 和内部 history/dropped 完整，结果 completed | FR-1、AC-1 |
| P2-UT-04 | 空输出、工具循环和 dropped history 结果打包 | 与原 Runtime 返回一致；history/dropped 只在私有 Outcome/metadata，不进入公共 payload | FR-1、AC-2、AC-9 |
| P2-UT-05 | model/tool 事件双向映射及未知/缺字段事件 | 原 kind/data 与顺序无损；model.delta 瞬态标记保留；非法事件受控失败而非改名 | FR-4、AC-4 |
| P2-UT-06 | RuntimeFault 全代码、model/run timeout、CancelledError、未知异常参数化映射 | category 正确且公开 error_code 保留；未知为 execution_error，敏感异常正文不出现 | FR-5、AC-5、AC-7 |
| P2-UT-07 | React cancel 两次及 start 前/失败后清理 | cancel 幂等，执行任务和事件流关闭，无第二结果或 pending task | FR-1、AC-6 |
| P2-UT-08 | Orchestrator 有效解析及未知版本/未注册/禁用组合 | 有效组合创建独立 Adapter；无效组合明确失败，无 latest/旧路径/其他 Engine 回退 | FR-2、AC-3、AC-8 |
| P2-UT-09 | Orchestrator start/stream/collect 各阶段异常 | 每阶段均清理任务/迭代器并产生规范失败；不重复调用 collect/cancel 造成第二终态 | FR-2、FR-5 |
| P2-UT-10 | Worker 开关 false/true 分支与 fingerprint 失败 | false 仅调用 legacy，true 仅调用 Orchestrator；两条路径 configuration_changed 行为一致 | FR-3、FR-6、AC-8 |
| P2-UT-11 | Worker 新路径 Outcome→finish 参数映射 | completed/failed/cancelled、output/history/error_code 正确；Worker 不读取 Engine 私有类型 | FR-3、AC-3 |
| P2-UT-12 | Memory summary/customer_memory/dropped 在新旧路径传递 | 输入渲染及 memory_context 调用参数一致，history/dropped 不丢失 | FR-1、FR-3、AC-2 |
| P2-UT-13 | Settings 默认与环境变量覆盖 | 默认 false；`AGENT_EXECUTION_ORCHESTRATOR_ENABLED=true/false` 正确解析，非法值拒绝 | FR-6、AC-8 |
| P2-UT-14 | 依赖方向与公开序列化静态检查 | Worker/Orchestrator 不 import RuntimeEngine；RunView/SSE 不含 history、process_id、engine_metadata | FR-2、FR-4、AC-3、AC-9 |

## 4. 集成测试

| 编号 | 用例 | 预期 | 溯源 |
|---|---|---|---|
| P2-IT-01 | 无 Agent 快照的固定文本模型，新旧路径各跑一次 | output、history/dropped、模型事件/usage、run.completed 和 error_code 完全一致 | AC-1、FR-1 |
| P2-IT-02 | 已发布 Agent 快照、Gateway Profile、语言与多轮工具调用，新旧路径对比 | 同一 Profile/工具参数/消息顺序/工具结果/预算生效，回复与事件等价，快照未改 | AC-1、AC-2 |
| P2-IT-03 | 历史截断 + summary + customer_memory + reasoning 场景 | 注入消息顺序、dropped、memory_context、reasoning 历史保留和不可见性与 legacy 一致 | AC-2 |
| P2-IT-04 | 新路径完整 Run 并检查 Registry/Factory/Adapter/Orchestrator/Worker 调用记录 | 仅经 react/native/v1 和 Orchestrator 执行；Worker 无 Engine 分支，Repository finish 仅一次 | AC-3 |
| P2-IT-05 | 内部 SSE 新旧路径对比及 Last-Event-ID 重放 | 持久事件名/seq/data/顺序一致；delta 瞬态且无 id/不落库；终帧后关闭，无重复 run 事件 | AC-4 |
| P2-IT-06 | 开放 API SSE、tool.replay 过滤及非法游标 | 与旧路径同样脱敏和过滤；Last-Event-ID/after 行为及 400 不变，无私有 metadata/gateway 内部字段 | AC-4、AC-9 |
| P2-IT-07 | 缺模型、模型非法/空响应、轮数/工具预算、未知 Provider 异常，新旧路径对比 | RunView 和持久 run.failed 的 error_code 一致；日志/API 无敏感原文 | AC-5 |
| P2-IT-08 | 执行中模型等待时取消，随后释放成功；重复 cancel | Adapter/模型任务实际收到取消并清理；最终 cancelled、output 为空，无迟到 run.completed | AC-6 |
| P2-IT-09 | 真实 PG 中 cancel 与 finish 竞争，并在终态后再次 finish | Repository 终态唯一，取消优先；后续完成提交无效，事件序列无第二终态 | AC-6 |
| P2-IT-10 | 分别构造 model_timeout、run_timeout | 分别 failed/model_timeout、failed/run_timeout，与 legacy 相同；超时后任务清理且无自动重试 | AC-7 |
| P2-IT-11 | 直接改库使 Lease 过期并 reap，再让旧 Worker 迟到提交成功 | heartbeat 返回 lost，最终 failed/worker_lost；迟到 output 不写入，终态事件唯一 | AC-7 |
| P2-IT-12 | 默认 off、显式 on、两组混合 Worker 同库消费，再 off 滚动重启 | off 只走 legacy，on 只走 orchestrator；混合结果等价；回滚后新 Run 全 legacy，在途 Run 按现有规则收敛 | AC-8 |
| P2-IT-13 | on 状态删除/禁用注册项后启动或执行 | fail fast 并产生可诊断安全错误；绝不静默 legacy 或选择其他版本 | AC-8 |
| P2-IT-14 | Phase 1 LocalTestAdapter 经同一 Orchestrator 替换 React | 无需修改 Worker 核心即可执行公共成功/失败/取消场景，验证 Worker 与具体 Engine 解耦 | AC-3 |

## 5. 通用核对项（本阶段适用）

| 编号 | 核对项 | 通过标准 | 溯源 |
|---|---|---|---|
| P2-CM-01 | 数据库迁移与既有行兼容 | head 保持 `0052`；无版本文件变更；存量 queued/running/terminal Run 读写和回滚无需数据修复 | AC-9 |
| P2-CM-02 | 配置加载与默认兜底 | 新开关默认 false，环境覆盖正确；off 路径与 Phase 0 基线 diff 为零 | AC-8 |
| P2-CM-03 | 审计、日志与观测 | 可按 run_id 查看 path、react/native/v1、耗时、终态和错误分类；无 input/config/history/密钥/原始堆栈 | AC-9 |
| P2-CM-04 | 多租户与公开数据面 | tenant/business/workspace 过滤不变；跨租户 Run/SSE 不可达；公共响应无 Engine 私有 metadata | AC-4、AC-9 |
| P2-CM-05 | API/SSE/Agent 配置兼容 | RunView/RunStatus/HTTP 状态、内部与开放 SSE、已发布快照结构无变更；现有相关测试全绿 | AC-1、AC-4、AC-9 |
| P2-CM-06 | 异步资源与代码质量 | 成功/失败/取消/回滚后无 pending Adapter/Worker task；受影响 ruff/pytest 全绿，无新反向依赖 | AC-3、AC-6、AC-9 |

## 6. 回归范围

- `backend/tests/test_runtime_engine.py`：RuntimeEngine 本身不改，既有推理/工具/预算/取消测试必须全绿。
- `backend/tests/test_runtime_postgres.py`：旧路径及新路径共同验证 claim、事件、取消、HTTP/SSE、慢模型中断和迟到结果。
- `backend/tests/test_open_platform.py`：开放 API 幂等、权限、事件脱敏、回放和消息账本不变。
- `test_agent_model_required.py`、`test_agent_languages.py`：旧快照、模型 Profile 与语言行为不变。
- Memory 的 `test_memory_injection.py`、`test_memory_summary.py`、`test_memory_customers.py`、`test_memory_config.py`、`test_memory_governance.py`：输入注入与完成写回等价。
- `test_extension_contracts.py`：既有 RunPort/RuntimeBindings/RuntimeFactory 可兼容使用，未把 Engine 塞入 Extension Registry。

## 7. 缺陷分级与出口准则

| 级别 | 定义 | 处理 |
|---|---|---|
| P0 阻断 | 回复/工具主流程破坏；数据丢失；跨租户或凭据泄露；错误终态覆盖 | 立即关闭新路径，修复并完整回归 |
| P1 严重 | 新旧语义不等价；SSE 回归；取消/Lease 失效；开关或回滚失效；Worker 仍耦合 Engine | 修复前不得扩大灰度或进入验收 |
| P2 一般 | 非关键性能退化、诊断缺失、非敏感字段差异且无不兼容影响 | 记录后可带问题验收，需产品签字 |
| P3 轻微 | 文案、命名、非敏感日志问题 | 排期修复 |

**出口准则**：P2-UT/IT/CM 全部通过；AC-1～AC-9 可复现通过；受影响回归全绿；off 基线 diff 为零；取消/超时/迟到结果无终态错误；无 P0/P1 未关闭、无迁移变化和悬挂任务。性能指标未测量不得写“达标”。
