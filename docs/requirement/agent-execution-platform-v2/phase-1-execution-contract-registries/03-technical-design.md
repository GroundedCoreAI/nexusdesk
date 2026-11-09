# Phase 1 · 执行契约与注册中心 — 技术落地文档

> 状态：设计决策已冻结（R1～R11）；本地测试与本地自动化验收证据已形成，完整套件与 CI 待执行，正式人工验收及签字未完成
> 创建：2026-11-02；设计冻结：2026-11-08
> 修订：2026-11-09（R11 owned-task 文档澄清，无生命周期行为变更）
> 依据：`docs/architecture/agent-execution-platform-v2.md` 第 4～6、15～17、19 节，Phase 1；`02-requirements.md`（FR-1～FR-6、AC-1～AC-8）；`08-implementation-breakdown.md`（R1～R11、T1～T8）

## 现状核查与改动总览

实施入口固定为 `4dfcfb41e9cbb799753986c2d76134514bbd19be`：`core_platform/agent_execution` 尚不存在，Alembic head 为 `0057_industry_pack_runtime`。`RuntimeEngine.run()`、`RuntimeWorker`、`RuntimeFactory` 与 `RunRepository` 继续承担现有 ReAct/Run 路径；`extension_contracts/runtime.py` 继续作为 Run/业务端口边界。以下 `agent_execution` 路径均为**拟新增**，本文不代表已经实现或通过测试。

用户已明确要求启动 Phase 1，因此 Phase 0 的干净已提交产物 CI 双跑、经授权真实历史样本和人工签字仍开放被列为**已接受的入口风险**，不构成 Phase 0 正式验收或放行。

| 层 | 文件 | 改动 |
|---|---|---|
| 迁移/依赖 | `backend/migrations/versions/`、`backend/uv.lock` | 不新增或修改；入口与完成时 head 均为 `0057_industry_pack_runtime`，锁文件零 diff |
| 契约 | `backend/src/agent_platform/core_platform/agent_execution/contracts/{base,common,request,handle,result,events,capabilities,errors}.py` | Phase 1 严格基类、ExecutionKey/安全别名、六类版本化 DTO、静态错误目录 |
| Adapter 协议 | `backend/src/agent_platform/core_platform/agent_execution/contracts/adapter.py` | AgentEngineAdapter Protocol 与身份/生命周期约束 |
| 注册中心 | `backend/src/agent_platform/core_platform/agent_execution/registry/{engine_registry,protocol_registry,adapter_registry}.py` | 描述符、独立注册、精确三元组解析；工厂与描述符分开保存 |
| 测试 Adapter | `backend/src/agent_platform/core_platform/agent_execution/adapters/testing/local_test_adapter.py` | 可编程、确定性、无外部依赖的 LocalTestScenario/LocalTestAdapter |
| 可复用套件 | `backend/tests/agent_execution/adapter_contract_suite.py` | 仅依赖公共契约的抽象场景、闸门/假时钟与清理断言；不得 import LocalTestAdapter 具体类型 |
| 第二 Adapter | `backend/tests/agent_execution/contract_probe_adapter.py` | 结构独立、非 LocalTestAdapter 子类，固定三元组 `(contract-probe,contract-scripted,v1)` |
| 测试 | `backend/tests/{test_agent_execution_contracts,test_agent_execution_registries,test_local_test_adapter,test_agent_execution_contract_probe}.py` | DTO/错误、注册解析及两个 Adapter 复用同一契约套件 |
| 包入口 | 上述新包的 `__init__.py` | 只导出公共契约/注册接口；不得 eager import 测试 Adapter |
| 既有入口 | `runtime_factory.py`、`runtime_composition.py`、`worker.py`、`repository.py`、`schemas.py`、`extension_contracts/{base,runtime}.py` | 本阶段零 diff；不修改 ContractModel、生产接线、公共 Run 端口或现有模型 |
| 部署/配置/前端 | `deploy/`、Settings、`.env.example`、`frontend/` | 本阶段零 diff、无新开关或凭据 |

## 数据模型与模块边界

### R1：严格 DTO、身份与精确字段

复用 `extension_contracts.base.ContractModel` 且不修改它。新增 Phase 1 基类 `ExecutionContractModel(ContractModel)`，显式保留 `frozen=True`、`extra="forbid"`、`allow_inf_nan=False`，并设置 `strict=True`、`str_strip_whitespace=False`。原始输入不去空格；严格模式拒绝非字符串到字符串的 coercion。

`ExecutionKey` 只含 `execution_id: UUID`、`engine_id`、`protocol_id`、`adapter_version`，由 Request/Handle/Result/Event 复用：

- Request/Handle/Result/Error/Capabilities 使用 `contract_version: Literal["v1"] = "v1"`；Event 使用 `schema_version: Literal["v1"] = "v1"`。显式传入其他版本必须失败。
- Engine/Protocol ID 匹配 `^[a-z0-9][a-z0-9_-]{0,63}$`；Adapter 版本匹配 `^v[1-9][0-9]*$`。`latest`、`v0`、`v01`、首尾空白及非字符串均拒绝。
- 公共 opaque 字符串非空、最大 200 字符、不含控制字符且无首尾空白，绝不 trim ID。`input` 不属于 opaque ID，允许原始换行等内容并逐字保留。
- `event_type` 最长 100 字符，匹配 `^[a-z0-9]+(?:[._-][a-z0-9]+)*$`；事件序号从 1 开始。

| 模型 | 精确字段与默认值 | 关键不变量 |
|---|---|---|
| ExecutionRequest | ExecutionKey；`tenant_id: str`（1～200）；`agent_id: UUID`；`conversation_id: UUID \| None = None`；`input: str`（1～200000，逐字保留）；`config: dict[str, JsonValue]`、`effective_capabilities: dict[str, bool]` 均 `default_factory`；`engine_session_id/workspace_id/trace_id: str \| None = None`；`execution_workdir: str \| None = None`；`timeout_seconds: int \| None = None` | timeout 严格 `>0`；workdir 仅作 opaque 字符串，不做文件系统校验；本阶段不计算 Effective 能力 |
| ExecutionHandle | ExecutionKey；`provider_session_id: str \| None = None`；`process_id: int \| None = None`（严格 `>0`）；`status: Literal["running"] = "running"`；`metadata: dict[str, JsonValue]` 工厂默认 | 只有 Result 表达终态；process_id/metadata 不自动暴露到 RunView 或 SSE |
| ExecutionResult | ExecutionKey；必需 `status: Literal["completed","failed","cancelled"]`；`output: str \| None = None`；`artifacts: list[dict[str, JsonValue]]` 工厂默认；`usage/engine_metadata: dict[str, JsonValue]` 工厂默认；`error: ExecutionError \| None = None` | 状态组合见 R2；集合默认值不共享 |
| ExecutionError | `contract_version`；必需 `category` 与 `code` 枚举；序列化只读 computed `message`；`retryable: bool = False`；受限 `details` 默认空 | message 只能由静态 code 目录计算，调用方不能提供动态文本；原始异常不序列化 |
| AgentEvent | 必需 `event_id: UUID`；ExecutionKey；`schema_version`；`engine_session_id: str \| None = None`；`sequence: int >= 1`；`event_type`；`source: Literal["platform","engine_native"]`；必需 timezone-aware `timestamp`；`payload: dict[str, JsonValue]` 工厂默认；`trace_id: str \| None = None` | timestamp 规范化到 UTC，但不是排序键；独立 Event 只校验字段；不得使用 wall-clock/random 默认工厂 |
| EngineCapabilities | `contract_version`；`streaming`、`persistent_session`、`session_resume`、`cancellation`、`human_approval`、`interactive_input`、`tool_calling`、`file_operations`、`terminal_execution`、`native_events`、`workspace_required` 共 11 个严格 bool，默认均 False | 无能力蕴含规则；Declared 不等于 Available/Effective，更不等于授权 |

跨对象一致性在 **Adapter 边界及公共契约套件**校验，不在 Pydantic 模型间加入隐式交叉校验：Request 三元组等于 Adapter 身份；Handle 与 Request 的全部 ExecutionKey 字段相等；Result/Event 与 Handle 的全部 ExecutionKey 字段相等；Event 的 `engine_session_id` 与 Handle 的 `provider_session_id` 相等（包括二者均为 None）。任何不匹配都拒绝，绝不修补。

### R2：Result 状态组合

非法组合直接抛出 ValidationError，绝不通过清字段或改状态来修复：

| status | output | error | artifacts / usage / engine_metadata |
|---|---|---|---|
| completed | str 或 None | 必须 None | 均允许 |
| failed | 必须 None | 必需且 category 不得为 cancelled | 均允许 |
| cancelled | 必须 None | 必须 None | 均允许 |

内建 `TimeoutError` 形成 `failed + timeout/execution_timeout`；用户显式取消形成无 error 的 cancelled Result。迟到成功由 Adapter 状态机抑制，不允许先构造成功 DTO 再清洗其 output/error。

### R3：安全错误与静态 code 目录

`ExecutionError` 是数据 DTO；`AdapterExecutionError(Exception)` 只携带一个安全 ExecutionError；`ConfigurationError(AdapterExecutionError)` 覆盖注册及生命周期/配置误用。直接构造畸形 DTO 抛 Pydantic ValidationError；Registry/Adapter 边界转换校验失败时不得复制原始 Pydantic 值或异常字符串。

十类 category 固定为 lower snake case：`configuration_error`、`engine_unavailable`、`protocol_error`、`authentication_error`、`permission_denied`、`resource_exhausted`、`timeout`、`cancelled`、`workspace_error`、`internal_error`。每个 code 只属于一个 category：

| category | codes |
|---|---|
| configuration_error | invalid_request、invalid_handle、invalid_result、invalid_event、invalid_scenario、invalid_adapter_state、duplicate_engine、duplicate_protocol、duplicate_adapter、unknown_engine、engine_disabled、unknown_protocol、protocol_disabled、incompatible_engine_protocol、unknown_adapter_version、adapter_disabled、adapter_factory_failed、adapter_identity_mismatch、adapter_contract_mismatch |
| engine_unavailable | engine_unavailable |
| protocol_error | protocol_error、event_identity_conflict |
| authentication_error | authentication_failed |
| permission_denied | permission_denied |
| resource_exhausted | resource_exhausted |
| timeout | execution_timeout |
| cancelled | execution_cancelled |
| workspace_error | workspace_error |
| internal_error | internal_error、simulated_process_failure |

静态 message 只来自 code 目录，不含动态敏感值。`details` 是默认空、禁止额外键的受限结构，只允许 `engine_id`、`protocol_id`、`adapter_version`、`field`、`operation`；各值是有界严格字符串，并按对应 ID/版本/slug 规则校验，不接受异常文本、config、input、provider response 或自由 reason。

内建 `TimeoutError` 映射为 `timeout/execution_timeout`；未知 Exception 映射为 `internal_error/internal_error`，不得使用 `str(exc)` 或堆栈。调用方任务的 `asyncio.CancelledError` 在清理后继续传播；显式 Adapter cancel 产生 cancelled Result，而非把 cancelled error 附加到 Result。retryable 默认 False，仅明确的启动前 `engine_unavailable` / `resource_exhausted` 可标 True；启动后失败及 timeout 默认 False。Phase 1 永不自动重试。

### R9：ExecutionError.message 安全序列化往返（2026-11-08 T2 quality review）

T2 quality review 在代码变更前确认：`message` 是 serialized computed field，而 `extra="forbid"` 会使 `ExecutionError.model_validate(error.model_dump())`、`model_validate_json(error.model_dump_json())` 以及 failed ExecutionResult 内嵌 Error 的 JSON round-trip 把该序列化字段当作额外字段拒绝。R9 在不引入新 DTO schema、transport persistence 或 API 变更的前提下关闭此缺陷：

1. `message` 仍为只读、序列化的 computed value，只能由所供 code 的静态目录项计算，绝不成为调用方可覆盖文本。
2. before-validation 检查直接构造、mapping/JSON 输入及 failed Result 内嵌 Error：若输入含 `message`，仅当它是 string 且与所供 code 的静态目录 message **完全相等**时才接受，作为无操作 integrity token；随后在 before-validation 中移除/丢弃并由 code 重算，不单独保存调用方文本。直接构造传入精确目录值也仅是同一 no-op token。
3. 任意、不匹配、非 string 或其他动态 `message` 均抛 Pydantic ValidationError；当 code 缺失/非法而输入仍含 `message` 时同样拒绝，不得静默忽略任意 message。
4. 成功的直接 `model_validate(model_dump())`、直接 `model_validate_json(model_dump_json())`、nested failed Result mapping/JSON round-trip 必须保留安全 `model_dump` 表示；computed property 不被输入覆盖。任意调用方文本仍禁止，traceback/异常脱敏规则不变。

### 责任边界与依赖方向

- `contracts` 只表达数据与 Adapter Protocol，不操作 Worker 队列、不决定租户权限、不提交 Run 终态。
- `registry` 只保存描述符与独立工厂，不做动态网络发现、真实健康检查或 RuntimeEngine 构造，也不 import 具体 Adapter。
- `LocalTestAdapter` 只模拟 Adapter 语义，不 import Registry；“进程故障”不表示已有 Process Supervisor。
- 依赖只能为 `extension_contracts.base <- agent_execution.contracts <- registry 和 adapters.testing`；测试再依赖这些模块。Contracts 不得 import Registry/Worker/Repository/Factory/具体 Engine，包 `__init__` 不得 eager import 测试 Adapter。
- 既有 `extension_contracts/base.py` 与 `runtime.py` 保持零 diff，不把 Engine Adapter 塞入 Capability/Extension Registry。

## 核心流程

### R5：Adapter 签名与生命周期

```python
@property engine_id / protocol_id / adapter_version -> str
async get_capabilities() -> EngineCapabilities
async start(request: ExecutionRequest) -> ExecutionHandle
def stream_events(handle: ExecutionHandle) -> AsyncIterator[AgentEvent]  # 通常为 async generator
async cancel(handle: ExecutionHandle) -> None
async collect_result(handle: ExecutionHandle) -> ExecutionResult
```

- 每个 Adapter 实例仅一个 active execution，每次 Registry resolution 都新建实例。第二次 start 以 `configuration_error/invalid_adapter_state` 拒绝。
- 首次 `stream_events(handle)` 合法创建 consumer 后，任何第二次 consumer 尝试均以 `configuration_error/invalid_adapter_state` 拒绝：既包括与首个迭代器并发的尝试，也包括首个迭代器关闭后的顺序尝试。Phase 1 没有 stream replay/restart 语义。
- `collect_result` 可在 start 后立即调用，也可与 stream 消费并发。所有重复/并发调用共享一个 terminal future 并返回相等 Result；一个等待调用方的取消不得取消共享执行。
- 终态 Result 可见后不得再有事件可见。cancel 要求合法 Handle；终态前若取消先完成则原子获胜，返回 cancelled Result 并关闭流。重复/并发 cancel 安全；其他终态后 cancel 为 no-op，已成功结果保持成功。
- async generator 提前 `aclose()`、timeout、stream failure、collector cancellation 均须完成清理，不留下 Adapter-owned pending task。
- 错误 Handle/状态使用安全 configuration error；Adapter 自己产生的畸形 Handle/Event/Result 使用 protocol error。调用方 `invalid_*` 误用与 Adapter 产出协议破坏不得混为一类。

### R4：事件流异常与 high-water mark

独立 AgentEvent 仅做字段校验。LocalTest 正常流使用连续 `1..N`，其他 Adapter 允许单调递增但有 gap 的 sequence。每个 active execution 独立跟踪 high-water mark，不使用全局或持久注册表：

1. `(execution_id,event_id)` 相同且完整 DTO 相等是 exact duplicate：原样 yield，不推进 high-water，不去重丢弃。
2. 相同 event_id 但内容不同：抛 `protocol_error/event_identity_conflict`，不修补事件。
3. 新 event_id 且 `sequence <= high-water`：属于 late/out-of-order，原样 yield，不降低 high-water。
4. 新 event_id 且 sequence 高于 high-water：允许 gap，yield 后推进到该 sequence；timestamp 不参与排序。

上述可观察异常仅在 execution active 时适用。取消或其他终态后，LocalTest 关闭流并抑制后续脚本事件/结果；首个终态不可被覆盖。

### R6：注册与精确解析

描述符固定为 `EngineDescriptor(engine_id, enabled=True)`、`ProtocolDescriptor(protocol_id, enabled=True)`、`AdapterDescriptor(engine_id, protocol_id, adapter_version, enabled=True)`。同步 `Callable[[], AgentEngineAdapter]` factory 与描述符分开存储；一个 factory 只注册一个精确三元组，不得用同一无参 factory 覆盖多个组合。

Engine/Protocol/精确 Adapter 的重复注册即使内容完全相同也一律拒绝。Adapter 注册前其 Engine/Protocol 必须已存在；disabled 可注册但不可 resolve。解析按以下顺序返回首个配置错误：

`unknown_engine → engine_disabled → unknown_protocol → protocol_disabled → incompatible_engine_protocol（该 pair 无任何注册）→ unknown_adapter_version（pair 仅存在于其他版本）→ adapter_disabled`。

工厂抛错、实例身份不符、缺少协议方法分别映射 `adapter_factory_failed`、`adapter_identity_mismatch`、`adapter_contract_mismatch`；身份和契约检查在实例逃逸前完成。每次 resolve 都调用 factory，禁止 latest、fallback、discovery、health probing、singleton 或网络访问。

生命周期 bound-signature 检查对 bound method 使用 `Signature.bind` 的占位参数而不实际执行方法：`get_capabilities` 绑定 0 个参数，`start`、`stream_events`、`cancel`、`collect_result` 各绑定 1 个参数。错误 arity 以 `adapter_contract_mismatch` 拒绝且实例不得逃逸；这只是对 R5 精确签名的 Registry 检查澄清，不新增生命周期方法。

### R10：按存活实例强制 fresh resolution（2026-11-08 T3 quality review）

T3 quality review 确认 singleton factory 可跨 resolution 返回同一个仍存活 Adapter，A→B→A 循环工厂也可复用首个对象，从而破坏每实例单 active execution 和状态隔离。每次成功 resolve 除再次调用 factory 外，还必须满足以下 fresh-instance 约束：

1. 返回值必须与该**精确注册**此前返回且仍存活的每个对象都不同；仍存活 singleton 或 A→B→A 循环复用在后续调用以 `ConfigurationError` + `configuration_error/adapter_contract_mismatch` 拒绝，重复对象不得逃逸。
2. 每个精确注册分别用 weak reference 跟踪已返回对象，身份比较只能使用 `is`；不得调用任意 `__eq__`，不得把可复用的 bare `id()` 当作身份。解析时清理死亡引用；Registry 不得为 freshness 强引用 Adapter 或延长其生命周期。
3. 已死亡的先前对象不阻止后续新对象成功返回，即使 CPython 复用了内存地址。不可 weak-reference 的候选在首次返回前即以 `adapter_contract_mismatch` 拒绝；Adapter 实现必须支持 weakref，普通类天然支持，使用 `__slots__` 的类须包含 `__weakref__`。这是 factory/实现约束，不是公共 Run/API 字段。
4. freshness 检查在既有 awaitable cleanup、身份检查和生命周期契约检查之后、实例逃逸之前执行。普通 weakref/tracking 失败安全映射为 `adapter_contract_mismatch`，不得暴露原始异常文本；`asyncio.CancelledError` 及其他 `BaseException` 控制流不被吞掉或改写。
5. 同步 resolve 遇到 factory 返回 Future/Task 时，不得以 await 方式扩展成异步 factory API；应以 `adapter_contract_mismatch` 拒绝该 awaitable，并 cancel 返回的 Future/Task 作为 cleanup。T3 必须断言 `future.cancelled()`，Task fixture 还须 await 完成清理且无 pending task。调用方 `CancelledError`/其他 `BaseException` 传播是独立边界规则，与 Future/Task cleanup 分属不同测试边界。
6. 不引入全局 singleton registry、强实例 cache、网络或 threading 行为，也不以 health probe/discovery 替代 freshness。

### R7：LocalTestAdapter 场景驱动

`LocalTestScenario` 仅用于测试，包含 capabilities、start_error、ordered events、terminal result、可选 completion_gate、逐事件 wait_for_gate、可选 stream_error，以及 timeout/process_failure 开关。事件脚本可显式覆盖 sequence/event_id/timestamp，并用 `duplicate_of` 声明完整重复；其余值使用确定性默认。

- 固定身份只能是 `(local-test,scripted,v1)`，scenario 不可覆盖；Request 指定其他三元组时在 Handle 产生前失败。第二 Adapter 固定为 `(contract-probe,contract-scripted,v1)`。
- 事件 ID 由 `execution_id + ordinal` 经 UUIDv5 派生；timestamp 使用固定 epoch 加 ordinal 偏移。场景执行禁止 `uuid4()` / `datetime.now()`。
- 手动推进的假时钟控制 timeout，`asyncio.Event` 闸门控制 completion/events；真实 sleep 不得决定预期结果。
- timeout 唤醒等待者并产生 failed Timeout；cancel 释放闸门并关闭流。终态后控制脚本可尝试注入，但 Adapter 抑制并保留首个终态。
- 每轮使用 fresh Adapter。success/failure/cancel/timeout/iterator close 都 await 所有 owned tasks；断言所有 owned tasks 均为 done，且无 Adapter-owned 或 test-created pending task。completed task 引用可保留用于检查，不要求最终 task set 为空；执行前 empty-set 断言是另一个独立条件。
- `process_id` 始终 None；模拟进程故障使用 `internal_error/simulated_process_failure`，不是 Runtime Host 证据。

公共 pytest 套件通过抽象场景构造、闸门/时钟和清理断言复用上述语义，不 import LocalTestAdapter 具体类型；第二 Adapter 不继承 LocalTestAdapter，并复用成功、空/多事件、错误、取消、重复/迟到、幂等收集与清理整套用例。

### R11：Owned-task 完成断言与引用保留（2026-11-09 最终审查文档澄清）

最终审查发现“Adapter-owned task set 最终为空”的部分旧表述与实现/测试保留 completed task 引用的行为不一致。统一口径为：所有 owned tasks 已 await/done，无 Adapter-owned 或 test-created pending task；completed task 引用可保留并以 `all(done)` 检查。执行前 empty-set 断言用于验证 fresh execution 未继承任务，是另一个独立条件。本澄清不修改生命周期代码、任务所有权或清理行为。

## 配置与模型调用路径

本阶段无新 Settings、环境变量、AgentConfig、外部 Engine、凭据或模型调用路径。测试构造可信 request，不读取真实凭据、模型 Profile 或租户配置；Phase 3 才负责从类型化配置生成 config 和 Effective 能力。

## 测试方案

| 层 | 用例 |
|---|---|
| 单测 | 严格/不 trim DTO、精确字段与默认隔离、Result 非法组合、静态错误目录、能力默认值、跨对象边界、注册顺序与工厂检查、依赖方向 |
| 契约/集成 | 两个结构独立 Adapter 复用五方法、立即/并发/幂等收集、事件异常、取消竞争、timeout、全部错误分类和清理套件 |
| 回归 | 新增测试、ruff check/format check、`test_core_boundaries.py`、适用的 Phase 0 Runtime/API/SSE 回归；保护文件零 diff、head/锁文件不变 |

详细步骤和溯源见 `04-test-plan.md`。完整套件仍按仓库约定由 CI 执行，不得把未运行的 CI 写成通过。

## 上线与回滚

- 新包不接入生产组合根，无数据库、部署、运行时开关、API/SSE、前端或凭据变更。
- 回滚只还原未接线的新包及测试，无需 Alembic downgrade、数据修复或 Worker 切换。
- 设计如需偏离 R1～R11，必须先新增裁定并同步 01～05/08，再改实现。Phase 2 接入前还须重新核对 v1 与真实 React 行为。
