# Phase 1 · 执行契约与注册中心 — 需求文档

> 状态：设计决策已冻结（R1～R11）；本地测试与本地自动化验收证据已形成，完整套件与 CI 待执行，正式人工验收及签字未完成
> 创建：2026-11-02；设计冻结：2026-11-08
> 修订：2026-11-09（R11 owned-task 文档澄清，无生命周期行为变更）
> 依据：`docs/architecture/agent-execution-platform-v2.md` 第 4～6、17 节，Phase 1；`01-business-goals.md`（G1～G4）；`08-implementation-breakdown.md`（R1～R11、T1～T8）

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
| 输出 | 复用且不修改 ContractModel 的 Phase 1 严格不可变 DTO；`extra="forbid"`、`strict=True`、`str_strip_whitespace=False`，公共字段有 `contract_version`/事件 `schema_version`，原始 input 与 ID 不被 trim；ExecutionError 不新增 schema 即可安全 mapping/JSON round-trip，序列化 message 仅为静态目录完整性标记 |
| 执行方式 | 同步内存校验；禁止数据库、网络及模型调用；集合字段使用安全默认工厂；跨对象身份在 Adapter 边界/公共套件校验，不在模型间隐式修补 |
| 失败处理 | 缺字段、非法标识、未知字段、非法状态或不一致 ID 立即拒绝；Result 非法组合不得通过清字段或改状态修复；ExecutionError 输入中的任意、不匹配或非 string message（包括 code 缺失/非法时）均 ValidationError，只有与所供 code 静态目录完全相等的 string 可作为 no-op token 丢弃重算；不得自动补全未知 Engine 配置或记录敏感 config 原文 |

### FR-2 完整 Adapter 生命周期契约

| 项 | 说明 |
|---|---|
| 触发时机 | 调用方准备执行一个已解析的 Adapter 时 |
| 输入 | ExecutionRequest；Adapter 暴露 engine_id、protocol_id、adapter_version，并实现 get_capabilities、start、stream_events、cancel、collect_result |
| 输出 | start 返回全部 ExecutionKey 匹配的 ExecutionHandle；stream_events 异步产出 AgentEvent；collect_result 返回唯一逻辑终态；get_capabilities 显式声明 11 项严格布尔能力 |
| 执行方式 | 全程异步非阻塞；每实例仅一个 active execution；结果可在 start 后立即及与流并发收集，重复/并发收集返回相等 Result；句柄进程字段仅作内部信息 |
| 失败处理 | 启动、协议、收集异常统一映射为安全 ExecutionError；cancel 可重复/并发调用，首个终态获胜；终态 Result 可见后不得再出现事件；等待方取消和迭代器提前关闭均须清理任务 |

### FR-3 Engine、Protocol 与 Adapter 注册中心

| 项 | 说明 |
|---|---|
| 触发时机 | 应用组合或测试注册描述符/Adapter 工厂，以及按三元组解析 Adapter 时 |
| 输入 | EngineDescriptor、ProtocolDescriptor、AdapterDescriptor，以及与描述符分开保存的同步无参 Adapter 工厂；解析键含精确 adapter_version |
| 输出 | 独立注册记录或新的 Adapter 实例；有效组合可解析，未注册/禁用/不兼容组合得到稳定的配置错误代码；同一注册已返回且仍存活的任何实例都不得再次从后续解析返回 |
| 执行方式 | 进程内同步注册与解析；一个工厂只对应一个精确三元组，每次解析产生独立实例；按精确注册用 weakref 跟踪已返回实例，仅以 `is` 比较存活对象身份并在解析时清理死亡引用，不强引用 Adapter、不调用任意 `__eq__`、不保存可复用 bare `id()`；Adapter 注册要求被引用 Engine/Protocol 已存在；不承担网络发现或健康探测 |
| 失败处理 | 未知 ID、版本不匹配、未声明组合、任何重复注册（包括完全相同）、工厂失败/身份不符/缺少方法均 fail closed；仍存活的 singleton 或 A→B→A 循环复用，以及不可 weakref 的候选，均以 `configuration_error/adapter_contract_mismatch` 在实例逃逸前拒绝；不得回退到另一 Engine 或版本 |

### FR-4 版本、错误与事件规则

| 项 | 说明 |
|---|---|
| 触发时机 | 注册/解析版本，或 Adapter 产生错误和事件时 |
| 输入 | `contract_version=v1`、事件 `schema_version=v1`、显式 `adapter_version`、事件序号与错误分类 |
| 输出 | 十个 lower-snake-case category、唯一归属的静态 code 目录、只读安全 computed message、retryable 与受限 details；message 直接及 nested mapping/JSON 往返保持安全 model_dump 表示；事件保留原生 payload |
| 执行方式 | 纯内存转换；输入 message 只接受与所供 code 静态目录完全相等的 string 作为 integrity token，在 before-validation 丢弃并重算，其他值一律拒绝；每个 active execution 跟踪 high-water mark，exact duplicate 原样产出且不推进水位，新 event_id 的低序号迟到事件原样产出，允许高水位上方 gap；不做持久去重 |
| 失败处理 | 不支持的契约主版本和 Adapter 版本直接拒绝；同 event_id 不同内容为 `protocol_error/event_identity_conflict`；Phase 1 不自动重试；错误不得包含凭据、异常原文、堆栈或客户输入 |

### FR-5 LocalTestAdapter 与公共契约套件

| 项 | 说明 |
|---|---|
| 触发时机 | 本地测试或 CI 选择 LocalTestAdapter 场景时 |
| 输入 | 测试场景脚本：能力、启动错误、有序事件、终态、完成/逐事件闸门、流错误、超时、模拟进程故障、显式重复及延迟事件 |
| 输出 | 固定 `(local-test,scripted,v1)` 身份的确定句柄、事件序列、能力、结果或 ExecutionError；scenario 不得覆盖身份 |
| 执行方式 | 异步内存实现；UUIDv5/固定 epoch 派生事件默认值，假时钟和 `asyncio.Event` 控制时间/等待；每轮 fresh Adapter；公共套件不 import LocalTestAdapter 具体类型 |
| 失败处理 | 非法场景定义在 Handle 产生前拒绝；取消/超时释放等待；终态后注入被抑制；结束必须 await owned tasks 并断言无 Adapter/test pending task；不得把模拟故障描述为真实 Runtime Host 能力 |

### FR-6 隔离接入与兼容约束

| 项 | 说明 |
|---|---|
| 触发时机 | Phase 1 代码合入和 CI 回归时 |
| 输入 | 新包、直接实例化注册中心的测试、现有 Runtime/API 测试 |
| 输出 | 新契约可被 Phase 2 导入；现有 RuntimeFactory、RuntimeWorker、RunPort、ContractModel 和 HTTP/SSE 签名及行为不变 |
| 执行方式 | 不修改生产 Worker 调用路径，不增加运行时配置开关；依赖方向为 `extension_contracts.base <- contracts <- registry/adapters.testing`；回滚为还原未接线的新包 |
| 失败处理 | 任一现有 Runtime 回归失败即阻断合入；禁止为通过新测试而修改既有事件名、Run 状态、表结构、Settings 或锁文件 |

## 非功能需求

- **性能**：注册与 DTO 校验只进行进程内操作，不在解析中执行 I/O；Phase 1 不改变生产 Run 延迟，性能基线待 Phase 0 测量。
- **兼容**：现有 Agent 快照、RunRequest/RunSnapshot、RunStatus、Runtime Event 和 API 不变；迁移 head 与实施入口 `4dfcfb41e9cbb799753986c2d76134514bbd19be` 的 `0057_industry_pack_runtime` 一致，`backend/uv.lock` 零 diff。
- **多租户**：request 中 tenant_id 只能来自可信上下文；注册中心不按不可信输入跨租户查找实现，日志和错误不得输出 config、凭据或原始输入。
- **可维护性**：Contracts 不 import Registry/Worker/Repository/Factory/具体 Engine；Registry 不 import 具体 Adapter；LocalTestAdapter 不 import Registry；包入口不 eager import 测试 Adapter。
- **可靠性**：取消幂等、实例隔离、共享终态、事件 high-water 与错误语义可重复测试；不宣称本阶段已提供持久事件去重或真实进程监管。

## 验收标准

| # | 场景 | 预期 |
|---|---|---|
| AC-1 | 用合法及非法 payload 分别构造六类契约模型，并验证两个实例修改默认集合 | 合法模型字段和版本正确、原始 input 不去空格；非法/未知字段及非法 Result 组合被拒绝；可变默认值互不共享 |
| AC-2 | 对 LocalTestAdapter 依次调用 capabilities、start、stream_events、collect_result | 三元组身份与 ExecutionKey 一致，事件按序到达，结果为 completed 且 output/usage 符合场景脚本 |
| AC-3 | 在长运行场景启动后连续两次 cancel，再收集事件和结果，并尝试提交迟到成功 | 两次取消均安全，流终止且结果为 cancelled；迟到成功不覆盖取消，无取消后的可见新事件 |
| AC-4 | 遍历全部错误分类和不支持能力场景 | 每类错误得到静态目录规定的 category/code/message/retryable，直接及 nested mapping/JSON 往返保留安全 model_dump，任意/不匹配/非 string message 被拒绝；敏感文本不泄露；11 项未声明能力均为 false，不被当成授权 |
| AC-5 | 独立注册 Engine、Protocol 和版本化 Adapter，并以结构独立的第二 Adapter 复用公共套件；在对象仍存活时重复解析，并覆盖 singleton、A→B→A 循环、不可 weakref 候选及死亡对象回收 | 有效组合返回独立且身份匹配的 Adapter；仍存活 singleton/循环复用及不可 weakref 候选在逃逸前以 `adapter_contract_mismatch` 拒绝；weakref/gc 证据表明注册中心不强留 Adapter，死亡引用被清理且地址复用不作为身份；第二 Adapter 非 LocalTestAdapter 子类，不修改公共契约或 Worker |
| AC-6 | 按裁定顺序解析未知/禁用 Engine、Protocol、版本和未声明组合，并执行任何重复注册及工厂异常 | 全部以稳定配置错误拒绝，工厂实例在身份/契约/freshness 检查前不逃逸，无隐式 latest、跨版本或其他 Engine 回退 |
| AC-7 | 重放重复/冲突/迟到事件、超时、资源耗尽及模拟进程故障 | exact duplicate 和迟到事件准确保留，event_id 冲突被拒绝；其余场景产生确定终态/错误；无真实外部依赖和悬挂任务 |
| AC-8 | 检查迁移 head、锁文件、生产 Worker/Factory 接线并运行既有 Runtime/API/SSE 回归 | head 保持 `0057_industry_pack_runtime`，锁文件和保护文件零 diff，新路径未接入生产，既有 API、事件名、状态及测试行为无变化 |
