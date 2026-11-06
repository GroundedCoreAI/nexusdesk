# Phase 2 · React Provider 与执行编排器 — 业务目标

> 状态：待评审 / 待实施
> 创建：2026-11-02
> 依据：`docs/architecture/agent-execution-platform-v2.md` 第 4～7、12、14～17、19～22 节，Phase 2；Phase 1（G1～G4）

## 要解决的问题

### 问题 1：Worker 与固定 ReAct Runtime 构造和执行方式耦合

`backend/src/agent_platform/core_platform/agent_runtime/worker.py` 当前通过 `RuntimeFactory.for_run()` 取得 Runtime 并直接调用 `run()`；`backend/src/agent_platform/applications/platform_runtime/runtime_factory.py` 固定构造 `RuntimeEngine`。这使 Worker 了解具体 Runtime 的输出 `(output, history, dropped)` 和异常形式，后续 Engine 无法复用同一编排路径。

### 问题 2：公共 Execution 生命周期尚无人协调

Phase 1 规划的契约和注册中心需要由执行编排器连接。当前没有组件统一完成 Run→ExecutionRequest 映射、`react/native/v1` 解析、Adapter start/stream/cancel/collect、结果与错误归一化；若直接把这些职责加入 Worker，会继续扩大其引擎专属知识。

### 问题 3：重构必须保持现有 Run、事件与 SSE 可观察行为

现有 `RunRepository` 已提供 queued/running/completed/failed/cancelled、取消优先、Lease 失效拒绝迟到提交、持久事件序号与回放；内部和开放 API 还区分持久事件与瞬态 `model.delta`。迁移若改变事件名、payload、游标、终态或错误码，会直接破坏控制台和开放 API 客户端。

### 问题 4：首个主要重构缺少可灰度、可撤销的执行入口

当前只有旧 Runtime 调用路径，没有新旧路径开关。需要默认关闭的新编排路径、可混合运行 Worker 的兼容设计以及无需数据库回滚的恢复手段，避免一次性切换全部执行流量。

## 业务目标

| 目标 | 说明 |
|---|---|
| G1：React 成为首个公共 Provider | 保留 LangGraph ReAct 推理与工具执行，在外层实现完整 React Adapter，经注册中心以 `react/native/v1` 解析 |
| G2：Worker 与具体 Engine 解耦 | 编排器管理 Adapter 生命周期和公共结果；Worker 继续负责队列、Lease/Heartbeat、取消监测和 Repository 终态提交，不识别 Engine 内部实现 |
| G3：现有用户体验零回归 | 新旧路径在输出、历史、Memory、事件、SSE、错误码、取消与终态上保持等价，公共 API 不变 |
| G4：可控迁移与快速回滚 | 通过默认关闭的全局开关受控启用新路径；回滚只切回旧路径并滚动重启，无迁移和数据修复 |

## 成功指标

| 指标 | 基线（现状） | 目标 |
|---|---|---|
| 固定 React 回归语料的新旧路径语义一致率 | 待 Phase 0 建立输出、history/dropped、事件及错误码基线 | 相同模型脚本下 output、history/dropped、事件类型/顺序/payload、error_code 和终态一致率 100% |
| React 经注册中心与编排器执行覆盖率 | 待 Phase 0 盘点；当前为 0 条新路径 | 开关开启的验收 Run 100% 经 `react/native/v1` 和编排器；无 Worker 直接调用具体 Engine |
| 内部及开放 SSE 兼容率 | 待 Phase 0 录制现有事件序列、payload、Last-Event-ID 与 delta 基线 | 固定场景事件名、持久 seq/回放、瞬态 delta 与终帧一致率 100%，无内部 metadata 新泄露 |
| 取消、超时与迟到结果保护正确率 | 待 Phase 0 盘点现有 Repository/Worker 用例结果 | 取消竞争、run/model timeout、Lease lost 场景 100% 保持规定终态，迟到成功覆盖数为 0 |
| 新路径执行性能与稳定性 | 待 Phase 0 测量 p50/p95、首 token、错误率及资源基线 | 相同样本新路径 p95 端到端延迟增量 ≤5%，新增错误率为 0；采样方法见验收方案 |
| 回滚恢复能力 | 待 Phase 0 演练并记录当前部署恢复基线 | 开关关闭并滚动重启后 100% 新 Run 走旧路径；无 Alembic downgrade、数据修复或客户端变更 |

## 范围

**包含**：
- 基于 Phase 1 契约实现 React Adapter、Runtime Event↔AgentEvent 内部映射及 ExecutionError 映射。
- 实现 Execution Orchestrator，固定本阶段旧配置到 `react/native/v1` 的兼容选择。
- Worker 新旧路径分支、组合根装配和默认关闭的全局功能开关。
- 保持 Repository 终态/事件所有权，验证内部与开放 SSE、Memory、错误、取消、超时和 Lease 行为。
- 新旧路径对等回归、混合 Worker 迁移及回滚演练。

**不包含**（属于后续阶段 / 明确不做）：
- 修改 LangGraph 推理算法、工具协议、Memory 业务规则或模型 Profile 选择逻辑。
- Agent 配置新增 Engine/Protocol 字段、Effective 能力计算和配置/策略快照（Phase 3）。
- Runtime Host、外部进程、Workspace、沙箱、凭据代理（Phase 4）。
- Codex/其他 Engine、Session Resume、人工审批新能力（Phase 5 及以后）。
- 新 Task/Execution 表、Lease Epoch/Fencing Token、事务 Outbox、新 SSE 重放协议（Phase 6 或后续）。
- 任何 Alembic 迁移、公共 HTTP/SSE schema 变更和微服务拆分（本阶段明确不做）。

## 风险与约束

- **适配层改变时序**：队列转发可能重排 delta 与持久事件；必须用同一发射回调和顺序测试保证模型/工具事件语义，run 终态仍仅由 Repository 发出。
- **错误码回归**：统一 ExecutionError 不能把 `model_timeout`、`agent_model_required` 等既有代码吞成通用错误；映射表必须保留公开 error_code，原始异常不得泄露。
- **取消清理不完整**：协程取消需传播到 Adapter 执行并等待清理；取消不承诺撤销工具副作用，迟到结果继续由 Repository 拒绝。
- **开关不一致**：混合 Worker 可能分别走新旧路径；两条路径必须始终等价，开启时注册/解析失败应明确失败而非静默回退。
- **兼容性**：默认 `execution_orchestrator_enabled=false`；现有 Agent 快照无需修改，固定解析 `react/native/v1`。当前迁移 head 为 `0052`，本阶段完成后仍为 `0052`。
