# Phase 1 · 执行契约与注册中心 — 实施拆解方案

> 状态：已裁定（R1～R11 为当前技术设计冻结基线，dev/qa 按 T1～T8 执行）；本地测试与本地自动化验收证据已形成，完整套件与 CI 待执行，正式人工验收及签字未完成
> 创建：2026-11-08
> 修订：2026-11-09（R11 owned-task 文档澄清，无生命周期行为变更）
> 依据：`01`～`05` 全部中英文文档 + 独立设计评审 + 现状核查（backend @ `4dfcfb41e9cbb799753986c2d76134514bbd19be`）
> 约束：文档与代码隔离实施；不修改生产接线、API/SSE、Settings、迁移、前端、deploy、外部 Engine 或凭据；本地只跑受影响检查，完整套件由 CI 按仓库约定执行；未实际运行的检查不得写成通过

## 1. 实施入口与已接受风险

| 项 | 冻结基线 |
|---|---|
| 分支 / 目标提交 | `feat/agent-execution-platform-v2-phase1` / `4dfcfb41e9cbb799753986c2d76134514bbd19be` |
| Alembic | 唯一 head 为 `0057_industry_pack_runtime`；Phase 1 不新增或修改迁移 |
| 新包现状 | `backend/src/agent_platform/core_platform/agent_execution` 尚不存在；所有实现路径均为拟新增 |
| 既有基类 | `extension_contracts.base.ContractModel` 已有 `frozen=True`、`extra="forbid"`、`allow_inf_nan=False`、`str_strip_whitespace=True`；Phase 1 只用子类覆盖严格策略，既有文件零 diff |
| 依赖 | `backend/uv.lock` 不变，不为本阶段新增依赖 |
| Phase 0 状态 | 实现已提交并推送，但干净已提交产物 CI 双跑、经授权真实历史样本和人工签字仍开放，正式验收尚未完成 |

**入口风险裁定**：用户明确要求启动 Phase 1，因此上述 Phase 0 未关闭项作为已接受入口风险继续由产品负责人和 QA 跟踪；这不是 Phase 0 验收、签字或放行。Phase 1 的任何实现、测试或验收证据都不得反向充当 Phase 0 通过结论。

## 2. 设计裁定总表

独立设计评审结论为 **DESIGN NEEDS DECISIONS**；R1～R8 是 controller 批准的初始关闭裁定。2026-11-08 T2 quality review 在代码变更前发现 ExecutionError.message 序列化往返缺陷，controller 以 R9 补充裁定；同日 T3 quality review 又确认 singleton/cycled factory 会复用仍存活 Adapter，controller 以 R10 补充存活实例 freshness 裁定。2026-11-09 最终审查发现部分文字把最终无 pending task 误写为 Adapter-owned task 集合最终为空，与实现/测试保留 completed task 引用并断言全部 done 的实际语义不一致，controller 以 R11 作纯文档澄清。当前 R1～R11 均已同步回填相关 01～05 文档，后续实现不得以“常识”或库默认行为替换这些明确口径。T1 的历史任务记录仍只描述当时的 R1～R8 冻结，不回写为当时已有 R9/R10/R11；T2 的 R9 范围保持原样，不回写为当时已有 R10/R11。

| # | 裁定主题 | 冻结结论 | 回填位置 |
|---|---|---|---|
| R1 | DTO 基类、身份、字段与跨对象一致性 | 严格且不 trim 的 Phase 1 子类；精确 ExecutionKey/DTO 字段；显式版本与有界 opaque 字符串；跨对象一致性只在 Adapter 边界/公共套件校验 | 02 FR-1/FR-4，03 R1，04 UT-01～07 |
| R2 | Result 终态组合 | 非法组合只拒绝不修复；completed/failed/cancelled 的 output/error 规则固定；迟到成功由状态机抑制 | 02 FR-1/FR-2，03 R2，04 UT-04/IT-06～08 |
| R3 | 安全异常与静态错误目录 | DTO/AdapterExecutionError/ConfigurationError 分层；十类 category、唯一 code 归属、静态 message、受限 details；不泄露原异常 | 02 FR-4，03 R3，04 UT-05/IT-03～06 |
| R4 | 事件流异常与 high-water | exact duplicate 原样产出且不推进水位；event_id 冲突拒绝；新 ID 低序号原样产出；gap 合法；终态后抑制 | 02 FR-4，03 R4，04 IT-09 |
| R5 | Adapter 签名、共享终态与清理 | 每实例单 active execution；立即/并发/幂等收集；取消竞争首个终态获胜；终态后无事件；所有退出路径清理任务 | 02 FR-2，03 R5，04 IT-01/07/08/11 |
| R6 | 三个 Registry 与精确解析 | 描述符和工厂分离；所有重复拒绝；固定错误优先级；每次解析新实例；身份/契约检查先于实例逃逸 | 02 FR-3，03 R6，04 UT-08～11 |
| R7 | 确定性 LocalTestAdapter | 固定身份、声明式场景、UUIDv5/固定 epoch、假时钟/闸门、首终态保护、完整任务清理；模拟故障不是 Host 证据 | 02 FR-5，03 R7，04 IT-01～09/11 |
| R8 | 可复用套件、第二 Adapter 与依赖方向 | pytest 抽象套件不依赖 LocalTest 具体类型；第二 Adapter 结构独立；Contracts/Registry/Adapter 依赖单向且包入口不 eager import | 02 FR-6，03 文件总览/R7，04 UT-12/IT-10 |
| R9 | ExecutionError.message 安全序列化往返 | 仅精确静态目录 string 作为 no-op integrity token，before-validation 丢弃重算；任意/不匹配/非 string 或 code 缺失/非法时的 message 拒绝；直接/nested mapping/JSON 保留安全 model_dump | 02 FR-1/FR-4/AC-4，03 R9，04 UT-05，05 A4 |
| R10 | 按存活实例强制 fresh resolution | 每精确注册以 weakref + `is` 跟踪存活对象；singleton/A→B→A 复用及不可 weakref 候选在逃逸前拒绝；死亡引用清理、不强留实例、不用 `__eq__`/bare `id()`，地址复用不影响身份 | 02 FR-3/AC-5，03 R6/R10，04 UT-09/UT-11，05 A5/A6 |
| R11 | owned task 完成断言与引用保留 | 所有 owned tasks 已 await/done，无 Adapter-owned 或 test-created pending task；completed task 引用可保留并以 `all(done)` 检查；执行前 empty-set 断言是独立条件；仅澄清文档，不改生命周期行为 | 03 R7/R11，04 §2/IT-11，08 R7/R11 |

### R1 DTO schemas / identity

1. 复用 `extension_contracts.base.ContractModel` 且不修改它。新增 `ExecutionContractModel(ContractModel)`，显式配置 `strict=True`、`str_strip_whitespace=False`，并保留 `frozen=True`、`extra="forbid"`、`allow_inf_nan=False`。任何原始输入都不得被预先 trim。
2. `ExecutionKey = execution_id: UUID + engine_id + protocol_id + adapter_version`，用于 Request/Handle/Result/Event。Request/Handle/Result/Error/Capabilities 带 `contract_version: Literal["v1"]="v1"`；Event 带 `schema_version: Literal["v1"]="v1"`。显式不支持版本失败。
3. Engine/Protocol ID 正则固定为 `^[a-z0-9][a-z0-9_-]{0,63}$`；版本正则固定为 `^v[1-9][0-9]*$`。`latest`、`v0`、`v01`、空白及非字符串 coercion 全部拒绝。
4. 公共 opaque 字符串非空、最长 200、无控制字符、无首尾空白，不 trim ID。`event_type` 最长 100，匹配 `^[a-z0-9]+(?:[._-][a-z0-9]+)*$`。Request.input 不属于 opaque ID，允许换行且逐字保留。

| DTO | 冻结字段（未写默认值的字段均为必需） |
|---|---|
| ExecutionRequest | ExecutionKey；`tenant_id: str` 1～200；`agent_id: UUID`；`conversation_id: UUID \| None = None`；`input: str` 1～200000 且逐字保留；`config: dict[str, JsonValue] = factory(dict)`；`effective_capabilities: dict[str, bool] = factory(dict)`；`engine_session_id/workspace_id/trace_id: bounded nonempty str \| None = None`；`execution_workdir: str \| None = None`（opaque、无文件系统校验）；`timeout_seconds: int \| None = None` 且严格 >0 |
| ExecutionHandle | ExecutionKey；`provider_session_id: str \| None = None`；`process_id: int \| None = None` 且严格 >0；`status: Literal["running"]="running"`；`metadata: dict[str, JsonValue] = factory(dict)`。只有 Result 可处于终态 |
| ExecutionResult | ExecutionKey；必需 `status: Literal["completed","failed","cancelled"]`；`output: str \| None = None`；`artifacts: list[dict[str, JsonValue]] = factory(list)`；`usage/engine_metadata: dict[str, JsonValue] = factory(dict)`；`error: ExecutionError \| None = None` |
| ExecutionError | `contract_version`；必需 category/code 枚举；只读且序列化的 computed `message`，只能来自静态 code 目录；`retryable: bool = False`；受限 details 默认空 |
| AgentEvent | 必需 `event_id: UUID`；ExecutionKey；`schema_version`；`engine_session_id: str \| None = None`；`sequence: int >= 1`；有界 lowercase dot/slug `event_type`；`source: Literal["platform","engine_native"]`；必需 timezone-aware datetime 并规范化到 UTC；`payload: dict[str, JsonValue] = factory(dict)`；`trace_id: str \| None = None`。确定性 Adapter 执行不得有 wall-clock/random 默认工厂 |
| EngineCapabilities | `contract_version`；既有文档中的 `streaming`、`persistent_session`、`session_resume`、`cancellation`、`human_approval`、`interactive_input`、`tool_calling`、`file_operations`、`terminal_execution`、`native_events`、`workspace_required` 共 11 个严格 bool，默认 False；无蕴含规则 |

跨对象检查不是 Pydantic 跨模型魔法：Request 三元组必须等于 Adapter 身份；Handle 与 Request 的全部 ExecutionKey 字段相等；Result/Event 与 Handle 的全部 ExecutionKey 字段相等；Event.engine_session_id 与 Handle.provider_session_id 相等，包括 None。由 Adapter 边界与公共契约套件拒绝 mismatch，绝不自动修复。

### R2 Result rules

| status | output | error | artifacts / usage / engine_metadata |
|---|---|---|---|
| completed | str 或 None | 必须 None | 均允许 |
| failed | 必须 None | 必需且不能是 cancelled category | 均允许 |
| cancelled | 必须 None | 必须 None | 均允许 |

畸形组合直接 ValidationError，绝不把字段清掉或改状态使其“合法”。内建 TimeoutError 对应 `failed + timeout/execution_timeout`；用户取消对应无 error 的 cancelled Result。迟到成功由 Adapter 状态抑制，不从成功 DTO 清洗而来。

### R3 Errors

- `ExecutionError` 是数据 DTO；`AdapterExecutionError(Exception)` 携带一个安全 ExecutionError；`ConfigurationError(AdapterExecutionError)` 覆盖 Registry 与生命周期/配置误用。
- 直接构造畸形 DTO 抛 Pydantic ValidationError。Registry/Adapter 边界转换校验失败时，不复制原始 Pydantic values 或异常字符串。调用方错误 Handle/状态使用 configuration error；Adapter 产生的畸形 Handle/Event/Result 使用 protocol error。
- 内建 `TimeoutError` 映射 `timeout/execution_timeout`；未知 Exception 映射 `internal_error/internal_error`，不使用 `str(exc)` 或 stack。调用方任务 `asyncio.CancelledError` 清理后传播；显式 Adapter cancel 产生 cancelled Result。
- 十类 category 为 `configuration_error`、`engine_unavailable`、`protocol_error`、`authentication_error`、`permission_denied`、`resource_exhausted`、`timeout`、`cancelled`、`workspace_error`、`internal_error`。每 code 只属于一个 category。
- retryable 默认 False；仅明确启动前 `engine_unavailable` / `resource_exhausted` 可为 True；启动后失败与 timeout 默认 False；Phase 1 永不自动重试。
- details 默认空，只允许经有界严格校验的 `engine_id`、`protocol_id`、`adapter_version`、`field`、`operation`。ID/版本按 R1 正则，field/operation 按有界 slug 校验；禁止任意异常文本、config、input、provider response、reason 或额外键。

**静态 code/message 目录**（message 为实现应使用的完整固定文本，不插值）：

| category | code | 静态 message | retryable 口径 |
|---|---|---|---|
| configuration_error | invalid_request | Execution request is invalid. | False |
| configuration_error | invalid_handle | Execution handle is invalid. | False |
| configuration_error | invalid_result | Execution result is invalid. | False |
| configuration_error | invalid_event | Agent event is invalid. | False |
| configuration_error | invalid_scenario | Local test scenario is invalid. | False |
| configuration_error | invalid_adapter_state | Adapter state does not allow this operation. | False |
| configuration_error | duplicate_engine | Engine is already registered. | False |
| configuration_error | duplicate_protocol | Protocol is already registered. | False |
| configuration_error | duplicate_adapter | Adapter is already registered for this exact tuple. | False |
| configuration_error | unknown_engine | Engine is not registered. | False |
| configuration_error | engine_disabled | Engine is disabled. | False |
| configuration_error | unknown_protocol | Protocol is not registered. | False |
| configuration_error | protocol_disabled | Protocol is disabled. | False |
| configuration_error | incompatible_engine_protocol | Engine and protocol have no registered adapter combination. | False |
| configuration_error | unknown_adapter_version | Adapter version is not registered for this engine and protocol. | False |
| configuration_error | adapter_disabled | Adapter is disabled. | False |
| configuration_error | adapter_factory_failed | Adapter factory failed safely. | False |
| configuration_error | adapter_identity_mismatch | Adapter identity does not match its registration. | False |
| configuration_error | adapter_contract_mismatch | Adapter does not implement the required contract. | False |
| engine_unavailable | engine_unavailable | Engine is unavailable. | 仅明确启动前可为 True，否则 False |
| protocol_error | protocol_error | Adapter protocol failed. | False |
| protocol_error | event_identity_conflict | Event identity conflicts with different content. | False |
| authentication_error | authentication_failed | Engine authentication failed. | False |
| permission_denied | permission_denied | Engine permission was denied. | False |
| resource_exhausted | resource_exhausted | Engine resources are exhausted. | 仅明确启动前可为 True，否则 False |
| timeout | execution_timeout | Execution timed out. | False |
| cancelled | execution_cancelled | Execution was cancelled. | False；不附加到 cancelled Result |
| workspace_error | workspace_error | Engine workspace operation failed. | False |
| internal_error | internal_error | Execution failed internally. | False |
| internal_error | simulated_process_failure | Simulated process failure occurred. | False；不是 Host 证据 |

### R4 Event stream semantics

- 独立 Event 只校验自身字段。正常 LocalTest 流序号连续 `1..N`；其他 Adapter 可单调递增但有 gap。high-water 按 active execution 隔离，不使用全局/持久注册表。
- exact duplicate 定义为 `(execution_id,event_id)` 相同且完整 DTO 相等：原样 yield、不推进 high-water、不去重丢弃。
- 同 event_id 不同内容：抛 `protocol_error/event_identity_conflict`，不修复。新 event_id 且 `sequence <= high-water`：late/out-of-order，原样 yield，不降低水位。新 event_id 且高于水位：允许 gap，yield 后推进水位。timestamp 不是排序键。
- 可观察异常只适用于 active execution。取消或其他终态 Result 后，LocalTest 关闭流并抑制后续脚本事件/结果，保留首个终态。

### R5 Adapter signatures / lifecycle

```python
@property engine_id / protocol_id / adapter_version -> str
async get_capabilities() -> EngineCapabilities
async start(request: ExecutionRequest) -> ExecutionHandle
def stream_events(handle: ExecutionHandle) -> AsyncIterator[AgentEvent]  # normally async generator
async cancel(handle: ExecutionHandle) -> None
async collect_result(handle: ExecutionHandle) -> ExecutionResult
```

1. 每个 Adapter 实例仅一个 active execution，每次 resolution fresh instance；第二次 start 以 `configuration_error/invalid_adapter_state` 拒绝。首次 `stream_events(handle)` 合法创建 consumer 后，任何第二次 consumer 尝试——无论与首个迭代器并发，还是首个迭代器关闭后的顺序调用——均以 `configuration_error/invalid_adapter_state` 拒绝。Phase 1 没有 stream replay/restart 语义。
2. `collect_result` 可在 start 后立即调用，并与 stream consumption 并发。一个共享 terminal future 让重复/并发调用返回相等 Result；shield 共享执行，单个等待调用方取消不得取消它。
3. 终态 Result 可见后不得有事件可见。cancel 要求合法 Handle；终态前若先完成则原子获胜，返回 cancelled Result 并关闭流。重复/并发 cancel 安全；其他终态后 no-op，已成功结果保持成功。
4. 提前 async-generator `aclose()`、timeout、stream failure、collector cancellation 均不得留下 Adapter-owned pending task。等待方取消的隔离与最终清理必须同时满足，不能用 shield 掩盖泄漏。
5. 错误 Handle/状态使用安全 configuration errors；Adapter 产生的畸形 Handle/Event/Result 使用 protocol errors。

### R6 Registries

- 描述符固定为 `EngineDescriptor(engine_id,enabled=True)`、`ProtocolDescriptor(protocol_id,enabled=True)`、`AdapterDescriptor(engine_id,protocol_id,adapter_version,enabled=True)`。同步 `Callable[[],AgentEngineAdapter]` factory 与描述符分开保存；一个注册只对应一个精确三元组，禁止一个 no-arg factory 注册多个组合。
- Engine/Protocol/精确 Adapter 重复注册即使完全相同也拒绝。Adapter 注册要求被引用 Engine/Protocol 已存在；disabled 可注册不可 resolve。
- 解析顺序固定：`unknown_engine → engine_disabled → unknown_protocol → protocol_disabled → incompatible_engine_protocol（pair 无任何注册）→ unknown_adapter_version（pair 仅其他版本）→ adapter_disabled`。
- 工厂失败、错误身份、缺失方法分别为 `adapter_factory_failed`、`adapter_identity_mismatch`、`adapter_contract_mismatch`。实例逃逸前检查身份和契约；每次 resolution 再调用 factory。禁止 latest、fallback、discovery、health probing、singleton、网络。
- 生命周期 bound-signature 检查对 bound method 使用 `Signature.bind` 占位参数而不实际执行：`get_capabilities` 绑定 0 参，`start`/`stream_events`/`cancel`/`collect_result` 各绑定 1 参；错误 arity 为 `adapter_contract_mismatch` 且实例不逃逸。这是 R5 精确签名检查的澄清，不新增生命周期方法。
- 每次成功解析还必须满足 R10 的存活实例 freshness；仅再次调用 factory 不足以证明 fresh instance。

### R7 LocalTestAdapter

- 测试专用声明式 `LocalTestScenario` 包含 capabilities、start_error、ordered events、terminal result、可选 completion_gate、逐事件 wait_for_gate、可选 stream_error、timeout/process_failure 开关。事件允许显式 sequence/event_id/timestamp override 与 `duplicate_of` 完整重复；其他默认确定。
- 固定身份只能 `(local-test,scripted,v1)`，scenario 不可覆盖；Request 指定其他三元组时在 Handle 存在前失败。第二 Adapter 固定 `(contract-probe,contract-scripted,v1)`。
- 事件 ID 由 execution_id+ordinal 经 UUIDv5 派生；timestamp 为固定 epoch+ordinal offset；场景执行禁止 uuid4/datetime.now。手动假时钟控制 timeout，asyncio.Event 闸门控制 completion/events，真实 sleep 不决定结果。
- timeout 唤醒等待者并产生 failed Timeout；cancel 释放闸门并关闭流。终态后控制可尝试注入，但 Adapter 抑制并保留首终态。每轮 fresh Adapter。
- success/failure/cancel/timeout/iterator close 都 await 所有 owned tasks；断言所有 owned tasks 均为 done，且无 Adapter-owned 或 test-created pending task。completed task 引用可保留用于检查，不要求最终 task set 为空；执行前 empty-set 断言是另一个独立条件。process_id 始终 None；模拟故障为 `internal_error/simulated_process_failure`，不是 Host 证据。

### R8 Reusable suite / dependencies

- 仅 pytest 使用的 `backend/tests/agent_execution/adapter_contract_suite.py` 提供抽象场景构造、gate/clock controls 与 cleanup assertions，不得 import LocalTestAdapter 具体类型。
- `backend/tests/agent_execution/contract_probe_adapter.py` 是结构独立第二 Adapter，非 LocalTestAdapter 子类，身份 `(contract-probe,contract-scripted,v1)`；复用成功、空/多事件、错误、取消、重复/迟到、幂等收集与清理同一套件。
- 依赖方向固定为 `extension_contracts.base <- agent_execution.contracts <- registry 和 adapters.testing`，tests 再依赖它们。Contracts 不 import Registry/Worker/Repository/Factory/具体 Engines；Registry 不 import 具体 Adapter；LocalTestAdapter 不 import Registry；包 `__init__` 不 eager import 测试 Adapter。

### R9 ExecutionError.message safe round-trip（2026-11-08 T2 quality review）

**发现原因**：T2 quality review 在代码变更前确认，serialized computed `message` 与 `extra="forbid"` 冲突，导致 `ExecutionError.model_validate(error.model_dump())`、`model_validate_json(error.model_dump_json())` 及 nested failed ExecutionResult JSON 往返拒绝合法安全 DTO。需要关闭往返缺陷，同时不能开放任意错误文本。

**Controller 裁定**：

1. message 保持只读 serialized computed value，只能由所供 code 的静态目录计算。直接构造、mapping 或 JSON 输入若含 message，仅接受与所供 code 静态目录 message 完全相等的 string；它只是 no-op integrity token，在 before-validation 移除/丢弃并由 code 重算，不单独保存，也绝不覆盖 computed property。直接构造精确目录值同样只能按此 token 处理。
2. 任意、不匹配、非 string 或其他动态 message 均 Pydantic ValidationError；code 缺失/非法而输入含 message 时也拒绝，不得静默忽略。规则一致适用于直接构造、model_validate/model_validate_json 和 failed Result 内嵌 ExecutionError。
3. 直接 `model_validate(model_dump())`、直接 `model_validate_json(model_dump_json())`、nested failed Result mapping/JSON 成功往返必须保留安全 model_dump 表示。任意调用方文本仍禁止，traceback 与异常脱敏不削弱。
4. 不引入新 DTO schema、transport persistence 或 API 变更。T2 必须把 R9 的正反向直接/nested 用例纳入 P1-UT-05，完成 spec/quality review 后才可继续。

### R10 Live-instance freshness（2026-11-08 T3 quality review）

**发现原因**：T3 quality review 确认 singleton factory 能跨 resolution 返回同一个仍存活 Adapter，A→B→A cycled factory 也能复用首个对象。仅“每次调用 factory”不能防止共享 active execution/state，必须在实现前冻结 fresh-instance 判定、失败分类和生命周期约束。

**Controller 裁定**：

1. 每次成功 resolve 返回的对象必须与该精确注册此前返回且仍存活的每个对象不同。仍存活 singleton 的第二次返回、A→B→A 的第三次复用均以 `ConfigurationError` + `configuration_error/adapter_contract_mismatch` 拒绝，重复对象不得逃逸。
2. Registry 按精确注册分别保存已返回对象的 weak reference，只以 `is` 比较身份；不得调用任意 `__eq__`，不得使用可复用 bare `id()`。解析时 prune 死亡引用，绝不因 freshness 强引用 Adapter 或延长其生命周期。已死亡对象不阻止后续新对象，即使 CPython 地址复用。
3. 不可 weak-reference 的候选在首次返回前以 `adapter_contract_mismatch` 拒绝。Adapter 实现必须支持 weakref；普通类支持，`__slots__` 类须含 `__weakref__`。这是 factory/实现约束，不新增公共 Run/API 字段。
4. freshness 在既有 awaitable cleanup、身份检查、生命周期契约检查之后且实例逃逸之前执行。普通 weakref/tracking 失败安全映射为 `adapter_contract_mismatch` 且不暴露原始异常文本；`CancelledError` 及其他 `BaseException` 控制流继续传播。
5. T3 必须以 P1-UT-09 覆盖两个同时存活结果的 `is not`、singleton、A→B→A、不可 weakref、自定义 `__eq__` 不调用、weakref/gc 无强留与死亡引用清理，以及地址复用不作为身份。P1-UT-11 以 `Signature.bind` 占位覆盖 0/1 参 arity；同步 resolve 对 factory 返回的 Future/Task 以 `adapter_contract_mismatch` 拒绝并 cancel 作为 cleanup，断言 `future.cancelled()`，Task fixture 还 await 清理且无 pending task；独立边界用例验证 `CancelledError`/其他 `BaseException` 传播，与 Future/Task cleanup 分开断言。这不扩展同步 factory API。
6. 不引入全局 singleton registry、强实例 cache、网络或 threading 行为。T3 必须先同步本裁定及 02～05，再实现 Registry，并完成 spec/quality review 闭环后才可进入 T4。

### R11 Owned-task 完成断言与引用保留（2026-11-09 最终审查文档澄清）

**发现原因**：03/04/08 的部分文字要求 Adapter-owned task 集合最终为空，但实现和测试会保留 completed task 引用，并断言 `all(task.done() for task in owned_tasks)` 及无 pending task。“最终集合为空”与“所有任务已完成、没有悬挂任务”不是同一条件。

**Controller 裁定**：

1. success/failure/cancel/timeout/iterator close 等结束路径必须 await 所有 Adapter-owned tasks，且这些 tasks 均已 done；不得留下 Adapter-owned 或 test-created pending task。
2. Adapter 和测试可保留 completed task 引用用于检查；最终断言为所有保留的 owned tasks 均 done（例如 `all(done)`），不要求最终 task set 为空。
3. 执行前要求 Adapter-owned task set 为空的断言用于证明 fresh execution 没有继承任务，是独立于结束后无 pending task 的另一个条件，不得被本澄清删除或混淆。
4. 本裁定仅统一 03/04/08 的中英文表述，不改变任何生命周期代码、任务所有权或清理行为；06/07 的证据与结论由后续证据任务按实际执行结果更新。

## 3. 任务拆解（按依赖顺序）

依赖主线：**T1 设计冻结 → T2 契约 → T3 注册中心 → T4 公共套件与 LocalTest → T5 独立第二 Adapter → T6 隔离/回归证据 → T7 测试报告 → T8 验收报告与最终独立评审**。T3 与 T4 的 Registry/Adapter 代码保持单向依赖；T5 不得通过修改公共接口来“适配”套件。

| # | 任务 | 文件（新建/修改） | 依赖 | 溯源 | 验证门禁 |
|---|---|---|---|---|---|
| T1 | 冻结 R1～R8，回填 01～05，建立双语拆解和总 README 状态；不写代码 | 本目录 `01-business-goals.md`、`02-requirements.md`、`03-technical-design.md`、`04-test-plan.md`、`05-acceptance-plan.md`、本文件（各含 `.en.md`）；主题 `README.md` / `README.en.md` | — | R1～R8；全部 G/FR/AC | 中英实质对等；R1～R8、T1～T8 完整；只改文档；对已跟踪编辑运行 `git diff --check`，并对全部 14 份文档（含未跟踪的 08 双文件）执行 trailing-whitespace/final-newline 检查；不要求 `git add`，不得改变 index；不得声称 Phase 0 已验收或 Phase 1 测试通过 |
| T2 | 实现严格契约、安全错误目录与 Adapter Protocol | 新建 `backend/src/agent_platform/core_platform/agent_execution/{__init__.py,contracts/{__init__.py,base.py,common.py,request.py,handle.py,result.py,events.py,capabilities.py,errors.py,adapter.py}}`；新建 `backend/tests/test_agent_execution_contracts.py` | T1 | FR-1/FR-2/FR-4，AC-1/AC-4，P1-UT-01～07及P1-UT-12（contracts/包入口部分），R1～R3/R5/R8/R9 | 运行该测试文件、UT-01～07及 UT-12 的 contracts/包入口依赖断言；此时只新增并运行这些已存在主体的断言，不要求 Registry/LocalTestAdapter 主体提前存在，但本任务计划覆盖的模块缺失必须失败，不得 skip 或因 absent 而通过；检查精确字段、静态目录、ValidationError、安全映射及 R9 直接/nested mapping/JSON 往返与任意/不匹配/非 string message 拒绝；spec review → quality review，finding 全部修复并复审后才进入 T3 |
| T3 | 实现三个 Registry、描述符、精确解析和工厂检查 | 新建 `backend/src/agent_platform/core_platform/agent_execution/registry/{__init__.py,engine_registry.py,protocol_registry.py,adapter_registry.py}`；新建 `backend/tests/test_agent_execution_registries.py` | T2 | FR-3，AC-5/AC-6，P1-UT-08～11及P1-UT-12（新增 Registry 部分），P1-IT-03/04 的注册/解析前置部分，R3/R5/R6/R8/R10 | 运行 Registry 测试、UT-08～11及 UT-12 已累计的 contracts/包入口 + 新增 Registry 依赖断言；Registry 模块缺失或断言未实际执行必须失败，不得 skip/absent-pass，此时尚不要求 LocalTestAdapter 部分；逐项验证重复、引用、禁用、错误优先级和三类工厂失败；按 R10 验证两个存活结果 `is not`、live singleton/A→B→A/不可 weakref 候选拒绝且无逃逸、weakref/gc 无强留及死亡引用清理、不用 `__eq__`/bare `id()` 或地址复用作身份；用 `Signature.bind` 占位验证 capabilities 0 参/其余四方法 1 参及错误 arity；同步 resolve 以 `adapter_contract_mismatch` 拒绝 Future/Task 候选并 cancel cleanup，断言 `future.cancelled()`、Task fixture 已 await 清理且无 pending task，独立验证 `BaseException` 传播边界；将 lifecycle-shape/signature、freshness/weakref、singleton/cycle、Future/Task cleanup 与 safe-inspection（无实例提前逃逸、无原始异常文本）回归逐项命名并实际执行；spec review → quality review 闭环后进入 T4 |
| T4 | 实现可复用 pytest 契约套件与确定性 LocalTestAdapter | 新建 `backend/tests/agent_execution/{__init__.py,adapter_contract_suite.py}`；新建 `backend/src/agent_platform/core_platform/agent_execution/adapters/{__init__.py,testing/{__init__.py,local_test_adapter.py}}`；新建 `backend/tests/test_local_test_adapter.py` | T2（套件/Adapter），T3（组合验证） | FR-2/FR-4/FR-5，AC-2/AC-3/AC-4/AC-7，P1-IT-01～09/11，相关 P1-UT-03/05/07、P1-UT-12（本任务完成）与 P1-CM-04/05，R2～R5/R7/R8 | 新增并运行 UT-12 的 LocalTestAdapter 不 import Registry 与包入口不 eager import 测试 Adapter 断言，连同 T2/T3 已累计断言组成并运行完整 P1-UT-12；LocalTestAdapter/包入口缺失或断言未实际执行必须失败，不得 skip/absent-pass；两个以上连续轮次覆盖立即/并发收集、事件异常、取消竞争、假时钟、aclose 和全部错误，并断言 owned/test 任务清理；spec review → quality review 闭环后进入 T5 |
| T5 | 增加结构独立第二 Adapter 并复用同一套件和注册测试 | 新建 `backend/tests/agent_execution/contract_probe_adapter.py`、`backend/tests/test_agent_execution_contract_probe.py`；不得改 T2 公共契约、T3 Registry 接口或 Worker | T3、T4 | AC-5，P1-IT-10，G1/G2，R8 | 固定 `(contract-probe,contract-scripted,v1)`；确认非继承、套件无 LocalTest 具体 import；成功、空/多事件、错误、取消、重复/迟到、幂等收集、清理与注册全复用；公共契约/Worker 零 diff；spec review → quality review 闭环后进入 T6 |
| T6 | 形成隔离、静态检查、架构与适用回归证据 | 无计划代码/文档修改；只读检查 T2～T5 文件、保护文件、`backend/migrations/versions/`、`backend/uv.lock`，原始输出供 T7 引用 | T5 | P1-UT-12 完整重跑，P1-CM-01～06，AC-8，04 §6，FR-6/G4 | 运行下方 T6 全部门禁并完整重跑 P1-UT-12（contracts/包入口、Registry、LocalTestAdapter、no-eager-test-import 均实际执行，缺失不得 skip/absent-pass）；保护文件零 diff、head=0057、锁文件不变；完整套件留 CI，未运行项如实标记；spec review → quality review 闭环后进入 T7 |
| T7 | 逐条执行 04 并只凭实际证据写双语测试报告 | 新建 `06-test-report.md` / `06-test-report.en.md`；仅在 T7 实际执行时创建 | T6 | 04 全部 P1-UT/IT/CM、AC-1～8、T2～T6 | 每个 UT/IT/CM 独立一行，含文件::用例、环境、结果、证据；记录缺陷 D-n、残留风险、skip/pending_env 和 CI 边界；不得预写通过 |
| T8 | 逐条执行 05、写双语验收报告，并完成最终独立整体评审 | 新建 `07-acceptance-report.md` / `07-acceptance-report.en.md`；仅在 T8 实际验收时创建 | T7 | 05 A1～A8、C1～C4、业务指标与签字 | 环境不可用项 `pending_env`、人工签字项 `pending`，不得预批准；最终独立 overall review 的 finding 全部修复并复审后才可报告完成 |

报告格式沿用需求生命周期技能的 `06-test-report.md` / `07-acceptance-report.md` 模板。T1 不创建 06/07；T7/T8 只能记录实际执行证据。

### T6 可复现验证门禁

在 `backend/` 执行受影响测试与静态检查（路径按 T2～T5 实际新增文件保持精确）：

```bash
uv run pytest tests/test_agent_execution_contracts.py tests/test_agent_execution_registries.py tests/test_local_test_adapter.py tests/test_agent_execution_contract_probe.py
uv run ruff check src tests
uv run ruff format --check src/agent_platform/core_platform/agent_execution tests/agent_execution tests/test_agent_execution_contracts.py tests/test_agent_execution_registries.py tests/test_local_test_adapter.py tests/test_agent_execution_contract_probe.py
uv run pytest tests/test_core_boundaries.py
uv run pytest tests/test_runtime_engine.py tests/test_runtime_postgres.py tests/test_open_platform.py tests/test_extension_contracts.py tests/test_runtime_baseline.py
uv run alembic heads
```

- PostgreSQL 回归使用专用 `TEST_DATABASE_URL`；环境不可用时记录 `pending_env`，不能把未执行写成通过。
- 从仓库根目录以入口提交为保护基线执行 `git diff --exit-code 4dfcfb41e9cbb799753986c2d76134514bbd19be -- <保护路径>`。保护路径至少包括：
  - `backend/src/agent_platform/extension_contracts/base.py`、`runtime.py`；
  - `backend/src/agent_platform/applications/platform_runtime/runtime_factory.py`、`runtime_composition.py`；
  - `backend/src/agent_platform/applications/customer_service/runtime_factory.py`、`runtime_composition.py`；
  - `backend/src/agent_platform/core_platform/agent_runtime/worker.py`、`repository.py`、`schemas.py`；
  - `backend/migrations/versions/`、`backend/pyproject.toml`、`backend/uv.lock`；
  - `backend/src/agent_platform/business_capabilities/customer_service/routing/settings.py`、`backend/src/agent_platform/core_platform/platform_services/platform_settings/settings.py`；
  - `backend/.env.example`、`deploy/production/.env.example`、`frontend/.env.example`；
  - `frontend/`、`deploy/` 整个目录零 diff。

除 T2～T5 任务表精确列出的 `backend/src/agent_platform/core_platform/agent_execution/`、`backend/tests/agent_execution/` 和四个新测试文件，以及 T1/T7/T8 任务表列出的文档外，仓库其他所有既有路径均须零 diff；上述保护清单是最低集合，不表示未列出的既有路径可以修改。
- `alembic heads` 必须仍为 `0057_industry_pack_runtime`，`backend/uv.lock` 必须零 diff。全量测试套件不在提交前本地强制执行，由 CI 在 push/PR 时运行；本任务没有自动 commit/push/PR 步骤，也不得声称未运行的 CI 已通过。

## 4. 完成与停线条件

- **设计偏离先停线**：实现与当前 R1～R11 或 01～05 不一致时，先新增 R 条目、说明原因并同步中英文相关文档，再改代码；不得静默变更契约。
- **双重评审串行关门**：T2～T6 每个实现任务完成后先做 spec review，再做 quality review；全部 finding 修复并重新评审通过前，不得开始下一任务。T7/T8 的证据与最终 overall review 同样不得带未解决 finding 结案。
- **范围硬边界**：禁止生产 wiring、公共 API/SSE、Settings/环境变量、Alembic 迁移、前端、deploy、外部 Engine、凭据或真实 Runtime Host 变更；禁止修改既有 ContractModel 和锁文件。
- **证据硬边界**：测试、CI、真实样本、环境和人工签字没有实际证据时必须保留 open/pending/pending_env；Phase 0 入口风险不是验收，Phase 1 实施启动也不是测试通过。
- **安全与确定性停线**：敏感文本泄露、跨租户状态、终态覆盖、事件身份冲突被修复而非拒绝、真实 sleep 决定结果或悬挂任务均按 04 的 P0/P1 规则处理。
- **无自动提交**：本拆解不包含自动 commit、push 或 PR；只有用户后续明确要求时才另行遵循仓库提交流程。
