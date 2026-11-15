# Phase 2 · React Provider 与执行编排器 — 业务目标

> 状态：本地 T2～T11 与 R17 live 验证已完成，R18 生产修复及聚焦验证已完成，详见 06/07 及相应附录；R18 最小 live on/off 已完成；总体仍有条件通过
> 创建：2026-11-02
> 修订：2026-11-12（R18 与当前状态统一；设计期内容保留为历史计划）
> 依据：`docs/architecture/agent-execution-platform-v2.md` 第 4～7、12、14～17、19～22 节；Phase 1 已通过 merge `0a6c4b5` 合入 integration，代码合入不等于正式人工验收；`08-implementation-breakdown.md`（R1～R18、T1～T11）

## 要解决的问题

### 问题 1：Worker 与固定 ReAct Runtime 构造和执行方式耦合

`backend/src/agent_platform/core_platform/agent_runtime/worker.py` 当前通过 `RuntimeFactory.for_run()` 取得 Runtime 并直接调用 `run()`；`runtime_factory.py` 固定构造 `RuntimeEngine`。Worker 因而了解具体 Runtime 的输出 `(output, history, dropped)` 和异常形式，后续 Engine 无法复用同一编排路径。

### 问题 2：公共 Execution 生命周期尚无人协调

Phase 1 已合入的契约和注册中心需要由执行编排器连接。当前没有组件统一完成 claimed Run→ExecutionRequest 映射、`react/native/v1` 精确解析、Adapter start/stream/cancel/collect、结果与错误归一化；若直接把这些职责加入 Worker，会继续扩大其引擎专属知识。

### 问题 3：重构必须保持现有 Run、事件与 SSE 可观察行为

现有 `RunRepository` 已提供 queued/running/completed/failed/cancelled、按提交顺序 first-commit-wins、Lease 失效拒绝迟到提交、持久事件序号与回放；内部和开放 API 还区分持久事件与瞬态 `model.delta`。迁移若改变事件名、稳定 payload、游标、终态或错误码，会直接破坏控制台和开放 API 客户端。公共 AsyncIterator 没有下游确认语义，简单出队/yield 也不能证明 Worker 已成功持久化或通知。

### 问题 4：首个主要重构缺少可灰度、可撤销的执行入口

当前只有旧 Runtime 调用路径，没有新旧路径开关。需要默认关闭的新编排路径、可混合运行 Worker 的兼容设计以及无需数据库回滚的恢复手段，避免一次性切换全部执行流量。

## 业务目标

| 目标 | 说明 |
|---|---|
| G1：React 成为首个公共 Provider | 保留 LangGraph ReAct 推理与工具执行，在外层实现完整 React Adapter，经注册中心以固定 `react/native/v1` 解析；复用既有 RuntimeFactory/RuntimeEngine，不写第二套 ReAct |
| G2：Worker 与具体 Engine 解耦 | 编排器管理 Adapter 生命周期、公共 Result 与私有 Outcome；Worker 继续负责队列、Lease/Heartbeat、取消监测、Memory 完成钩子和 Repository 终态提交，不识别 Engine 内部实现 |
| G3：现有用户体验零回归 | 新旧路径在输出、历史、Memory、事件、SSE、错误码、取消与终态上按 03 的确定性/并行规则保持等价，公共 API、数据库与前端不变 |
| G4：可控迁移与快速回滚 | 通过默认关闭、进程启动生效的全局开关受控启用新路径；回滚只切回旧路径并滚动重启，无迁移和数据修复 |

## 成功指标

| 指标 | 基线（现状） | 目标 |
|---|---|---|
| 固定 React 回归语料的新旧路径语义一致率 | Phase 0 已建立现状基线；本阶段另生成可比机器证据 | 串行确定性脚本中 output、history/dropped、error、usage、稳定 payload、顺序、每 Run 连续 seq、终帧位置及严格重放一致率 100%；并行工具按 call_id 对齐集合和局部偏序，按 03 的显式字段路径 canonicalize，不要求跨路径绝对 seq/全局分支顺序相同 |
| React 经注册中心与编排器执行覆盖率 | 当前无新路径 | 开关开启的验收 Run 100% 经 `react/native/v1` 和编排器；无 Worker 直接调用具体 Engine，无客户端选择、latest 或静默回退 |
| 内部及开放 SSE 兼容率 | Phase 0 已固化 Last-Event-ID、delta、tool.replay 等基线 | 固定场景按 03 的对等规则验证内部/Open SSE 的 Last-Event-ID、after、超过 200 条排空、无 ID delta 不重放、隐藏 tool.replay 但推进游标及公共字段过滤；无内部 metadata 新泄露；游标校验保持 R15 基线：内部手工 Last-Event-ID 非法/越界为 400/invalid_last_event_id，内部 after 与 Open after/Last-Event-ID 的 typed 类型/范围错误为 422，合法游标继续 max(after,last_id) 并严格 seq>after |
| 取消、超时与迟到结果保护正确率 | Phase 0 已盘点 Repository/Worker 行为 | 取消竞争、run/model timeout、Lease lost、阻塞生产/消费、aclose、append/emit 失败等规定场景 100% 保持唯一正确终态；迟到成功覆盖数为 0，所有 owned tasks 完成 |
| 新路径执行性能与稳定性 | 需真实环境与人工复核 | 按 05 §4 在相同环境/脚本执行至少 30 matched pairs，5 组 warm-up 不计样本，以 nearest-rank p95 验证新路径端到端延迟增幅 ≤5%，新增错误率为 0；原始延迟独立报告，不被 canonical diff 隐藏；真实外部环境不足仅性能子指标为 `pending_env`，功能出口独立判断且 T9 最多有条件通过 |
| 回滚恢复能力 | Phase 0 已记录现有部署与恢复行为 | 开关关闭并滚动重启后 100% 新 Run 走旧路径；存量 queued/running/terminal 行可读，混合 claim 与在途执行按既有规则收敛；无 Alembic downgrade、数据修复或客户端变更 |
| 验收后示例可复现性 | 当前没有 Phase 2 专属示例种子 | 开发、测试、正式验收完成后新增幂等、低敏、可识别命名空间的 Phase 2 示例种子，并经 quickstart 默认 off、显式 on、内嵌 Worker、双 SSE 和 off 回滚验证；实际结果只追加到 06/07 附录 |

## 范围

**包含**：
- 基于 Phase 1 契约实现 React Adapter、开放业务事件映射、安全错误映射、ack-aware 私有流与 ExecutionOutcome。
- 实现 Execution Orchestrator、同步 ContextVar 捕获/复位边界、固定 `react/native/v1` 选择及独立 LocalTest Registry/selector。
- Worker 末尾可选 `orchestrator=None` 参数、组合根装配和默认关闭的全局功能开关。
- 保持 Repository 终态/持久事件所有权，验证内部与开放 SSE、真实 Memory、错误、取消、超时和 Lease 行为。
- 新旧路径对等回归、独立 PostgreSQL 17、混合 Worker 迁移及回滚演练。
- T10/T11 的**验收后**新增示例种子与 quickstart 复验，并将事实追加到 06/07 附录。

**不包含**（属于后续阶段 / 明确不做）：
- 修改 LangGraph 推理算法、工具协议、Memory 业务规则或模型 Profile 选择逻辑。
- Agent 配置新增 Engine/Protocol 字段、Effective 能力计算和配置/策略快照；nil 兼容哨兵的正式身份模型移除留待 Phase 3。
- Runtime Host、外部进程、Workspace、沙箱、凭据代理、Codex/其他 Engine、Session Resume 或人工审批新能力。
- 新 Task/Execution 表、Lease Epoch/Fencing Token、事务 Outbox、新 SSE 重放协议或自动重试。
- 任何 Alembic 迁移、ORM、公共 HTTP/SSE schema 或前端代码变更；不新增部署服务或 UI。

## 风险与约束

- **身份污染**：`execution_id` 保持 UUID 并直接使用 claimed row ID；Agent UUID 必须严格来自真实快照。仅无快照 React legacy base_runtime 可在内部使用 `UUID(int=0)` 匿名未绑定哨兵，且不得进入查询、授权、DB、HTTP/SSE、日志、指标或 engine_metadata；不得借 Run/conversation UUID 充当 Agent。
- **适配层改变时序**：worker_emit 与私有 runtime_emit 必须隔离；首发 gate 在 stream 同步 claim 或显式 no-stream 选择前关闭。队列有界并区分 yield 与 worker_emit 成功后的私有 ack；React 无流 collector 显式选择私有 no-stream suppression，不再类比 LocalTest；活跃流背压等待，终态仅在生产结束且 queued+in-flight undelivered 为零后发布。
- **错误码与用量回归**：统一 ExecutionError 不能吞掉 Phase 0 全来源及未来未知 RuntimeFault 的原始 code；未知普通异常公共映射 internal_error、legacy execution_error。usage 非 optional 且不得为 None；React v1 无聚合输入时公共 Result 与私有 Outcome 均为 `{}`，不是既有聚合或伪造零 token。
- **取消清理不完整**：cancel、aclose、emit 失败和调用方 CancelledError 必须唤醒首发 gate/等待者、取消并排空 runner、抑制迟到成功；Adapter 显式取消是 first-terminal-wins，Run 持久层是按提交顺序 first-commit-wins，stale finish no-op 而 stale append 抛 CancelledError。只承诺协作式协程在外层超时内有界清理，不承诺强杀不协作协程或撤销工具副作用。
- **开关不一致**：混合 Worker 可分别走新旧路径；开关不得进入 runtime-composition fingerprint，开启时失败必须显式失败而非静默回退。`run_id` 仅进日志/ trace，指标保持低基数。
- **迁移与证据边界**：2026-11-10 本次只读观测 `uv run --directory backend alembic heads` 为 `0057_industry_pack_runtime (head)`；这是基线观测而非常量。测试须动态核对 heads、空库 upgrade 和前后迁移目录零漂移。Phase 1 代码已 merge 不代表人工验收完成；本阶段 06/07 仅在 T8/T9 实际执行后生成。
