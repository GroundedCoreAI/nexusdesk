# Phase 1 · 执行契约与注册中心 — 需求文档

> 状态：待评审 / 待实施
> 创建：2026-11-02
> 依据：`docs/architecture/agent-execution-platform-v2.md` 第 4～6、17 节，Phase 1；`01-business-goals.md`（G1～G4）

## 用户故事

**US-1（Adapter 开发者）**：作为 Adapter 开发者，我希望实现一套稳定且有版本的公共契约，以便接入新 Engine 时无需修改 Worker 或平台公共模型。

**US-2（平台研发）**：作为平台研发，我希望分别注册 Engine、Protocol 和 Adapter，以便按精确三元组解析实现并在执行前发现不兼容配置。

**US-3（QA）**：作为 QA，我希望使用确定性的本地 Adapter 驱动全部生命周期与异常场景，以便在没有外部 Engine 和凭据时重复验证契约。

**US-4（平台运维）**：作为平台运维，我希望本阶段不改变生产 Run 链路和数据库，以便契约建设不会引入线上切换或回滚负担。

## 功能需求

### FR-1 版本化执行数据契约

| 项 | 说明 |
|---|---|
| 触发时机 | Adapter 接收执行、返回句柄/结果，或平台与 Adapter 交换事件和能力时 |
| 输入 | 可信执行上下文、Run 映射数据、Adapter 原生输出；模型包含 ExecutionRequest、ExecutionHandle、ExecutionResult、ExecutionError、AgentEvent、EngineCapabilities |
| 输出 | `extra="forbid"` 校验后的不可歧义 DTO；公共字段有 `contract_version`/事件 `schema_version`，Engine 私有数据只进入明确隔离的 metadata |
| 执行方式 | 同步内存校验；禁止数据库、网络及模型调用；集合字段使用安全默认值，实例间不得共享可变状态 |
| 失败处理 | 缺字段、非法标识、未知字段、非法状态或不一致 ID 立即抛出校验错误；不得自动补全未知 Engine 配置或记录敏感 config 原文 |

### FR-2 完整 Adapter 生命周期契约

| 项 | 说明 |
|---|---|
| 触发时机 | 调用方准备执行一个已解析的 Adapter 时 |
| 输入 | ExecutionRequest；Adapter 暴露 engine_id、protocol_id、adapter_version，并实现 get_capabilities、start、stream_events、cancel、collect_result |
| 输出 | start 返回匹配 execution_id 的 ExecutionHandle；stream_events 异步产出 AgentEvent；collect_result 返回唯一逻辑终态；get_capabilities 显式声明不支持项 |
| 执行方式 | 全程异步非阻塞；事件迭代与结果收集可独立测试；句柄进程字段仅作内部信息，不进入公共 HTTP API |
| 失败处理 | 启动、协议、收集异常统一映射为 ExecutionError；cancel 可重复调用且不将用户取消改写成内部失败；终态后不得再发出有效事件或成功结果 |

### FR-3 Engine、Protocol 与 Adapter 注册中心

| 项 | 说明 |
|---|---|
| 触发时机 | 应用组合或测试注册描述符/Adapter 工厂，以及按三元组解析 Adapter 时 |
| 输入 | EngineDescriptor、ProtocolDescriptor、Adapter 工厂及支持的 `(engine_id, protocol_id)` 组合；解析键含精确 adapter_version |
| 输出 | 独立注册记录或新的 Adapter 实例；有效组合可解析，未注册/禁用/不兼容组合得到稳定的配置错误代码 |
| 执行方式 | 进程内同步注册与解析；工厂每次产生独立实例，不共享单次 Execution 状态；不承担网络发现或真实健康探测 |
| 失败处理 | 未知 ID、版本不匹配、未声明组合、重复冲突注册和工厂返回身份不一致均 fail closed；不得在解析失败时回退到另一 Engine 或版本 |

### FR-4 版本、错误与事件规则

| 项 | 说明 |
|---|---|
| 触发时机 | 注册/解析版本，或 Adapter 产生错误和事件时 |
| 输入 | `contract_version=v1`、显式 `adapter_version`（本阶段示例 `v1`）、事件序号与错误分类 |
| 输出 | ConfigurationError、EngineUnavailable、ProtocolError、AuthenticationError、PermissionDenied、ResourceExhausted、Timeout、Cancelled、WorkspaceError、InternalError；错误含安全 code、分类、retryable 与受限 details |
| 执行方式 | 纯内存转换；AgentEvent 使用 execution 内单调 sequence 和唯一 event_id，允许契约层表达重复/迟到事件但不替平台去重或落库 |
| 失败处理 | 不支持的契约主版本和 Adapter 版本直接拒绝；默认重试仅为建议，不在 Phase 1 自动重试；错误消息不得包含凭据、原始堆栈或客户输入 |

### FR-5 LocalTestAdapter 与公共契约套件

| 项 | 说明 |
|---|---|
| 触发时机 | 本地测试或 CI 选择 LocalTestAdapter 场景时 |
| 输入 | 测试场景脚本：成功、流式、长运行、配置无效、协议错误、认证失败、权限拒绝、资源耗尽、超时、取消、模拟进程故障、重复及延迟事件 |
| 输出 | 确定的句柄、事件序列、能力、结果或 ExecutionError；测试可控制完成/取消闸门，不依赖真实进程和网络 |
| 执行方式 | 异步内存实现；时间与等待用测试时钟或事件闸门控制；同一场景重复执行产生相同语义 |
| 失败处理 | 非法场景定义在 start 前拒绝；测试结束必须清理待等待任务；不得用真实 sleep 模拟长超时，不得把模拟故障描述为真实 Runtime Host 能力 |

### FR-6 隔离接入与兼容约束

| 项 | 说明 |
|---|---|
| 触发时机 | Phase 1 代码合入和 CI 回归时 |
| 输入 | 新包、直接实例化注册中心的测试、现有 Runtime/API 测试 |
| 输出 | 新契约可被 Phase 2 导入；现有 RuntimeFactory、RuntimeWorker、RunPort 和 HTTP/SSE 签名及行为不变 |
| 执行方式 | 不修改生产 Worker 调用路径，不增加运行时配置开关；Phase 1 无启用状态，回滚为不引入/移除未接线的新包 |
| 失败处理 | 任一现有 Runtime 回归失败即阻断合入；禁止为通过新测试而修改既有事件名、Run 状态或表结构 |

## 非功能需求

- **性能**：注册与 DTO 校验只进行进程内操作，不在解析中执行 I/O；Phase 1 不改变生产 Run 延迟，性能基线待 Phase 0 测量。
- **兼容**：现有 Agent 快照、RunRequest/RunSnapshot、RunStatus、Runtime Event 和 API 不变；当前迁移 head `0052` 不变。
- **多租户**：request 中 tenant_id 只能来自可信上下文；注册中心不按不可信输入跨租户查找实现，日志和错误不得输出 config、凭据或原始输入。
- **可维护性**：Engine/Protocol/Adapter 身份与版本清晰，公共契约不 import Factory、Worker、Repository 或任何具体 Engine。
- **可靠性**：取消幂等、实例隔离、事件顺序与错误语义可重复测试；不宣称本阶段已提供持久事件去重或进程清理。

## 验收标准

| # | 场景 | 预期 |
|---|---|---|
| AC-1 | 用合法及非法 payload 分别构造六类契约模型，并验证两个实例修改默认集合 | 合法模型字段和版本正确；非法/未知字段被拒绝；可变默认值互不共享 |
| AC-2 | 对 LocalTestAdapter 依次调用 capabilities、start、stream_events、collect_result | 三元组身份与 execution_id 一致，事件按序到达，结果为 completed 且 output/usage 符合场景脚本 |
| AC-3 | 在长运行场景启动后连续两次 cancel，再收集事件和结果，并尝试提交迟到成功 | 两次取消均安全，流终止且结果为 cancelled；迟到成功不覆盖取消，无取消后的有效新事件 |
| AC-4 | 遍历全部错误分类和不支持能力场景 | 每类错误得到规定 category/code/retryable，敏感文本不泄露；不支持能力显式为 false，不被当成授权 |
| AC-5 | 独立注册一个 Engine、两个 Protocol 和对应版本化 Adapter，再按有效三元组解析 | Engine 与 Protocol 不需绑死注册；有效组合返回独立且身份匹配的 Adapter，不修改公共契约或 Worker |
| AC-6 | 解析未知 Engine/Protocol/版本、未声明组合、禁用项，并执行重复冲突注册和身份不匹配工厂 | 全部以稳定配置错误拒绝，无隐式 latest、跨版本或其他 Engine 回退 |
| AC-7 | 重放 LocalTestAdapter 的重复事件、延迟事件、超时、资源耗尽及模拟进程故障 | 事件异常被准确保留供上层处理；其余场景产生确定终态/错误；测试无真实外部依赖和悬挂任务 |
| AC-8 | 检查迁移 head、生产 Worker/Factory 接线并运行既有 Runtime/API/SSE 回归 | head 仍为 `0052`，新路径未接入生产 Worker，既有 API、事件名、状态及测试行为无变化 |
