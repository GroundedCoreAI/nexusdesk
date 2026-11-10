# Phase 1 · 执行契约与注册中心 — 测试方案

> 状态：设计决策已冻结（R1～R11）；本地测试与本地自动化验收证据已形成，完整套件与 CI 待执行，正式人工验收及签字未完成
> 创建：2026-11-02；设计冻结：2026-11-08
> 修订：2026-11-09（R11 owned-task 文档澄清，无生命周期行为变更）
> 依据：`02-requirements.md`（FR-1～FR-6、AC-1～AC-8）、`03-technical-design.md`（契约 v1、精确注册解析、LocalTestAdapter、无迁移）、`08-implementation-breakdown.md`（R1～R11、T1～T8）

## 1. 测试范围与原则

**范围**：六类严格执行 DTO、安全错误目录、Adapter Protocol 全生命周期、Engine/Protocol/Adapter 注册中心、版本与兼容矩阵、事件 high-water、LocalTestAdapter、结构独立第二 Adapter 及生产路径零接线验证。

**原则**：

1. **完整契约必测**：三个身份属性和 get_capabilities、start、stream_events、cancel、collect_result 五方法均有独立及组合断言；两个 Adapter 复用同一套件。
2. **严格输入必测**：原始 input 不 trim，ID/版本不做 coercion；非法 Result 组合只拒绝，不清洗；跨对象一致性在 Adapter 边界验证。
3. **失败关闭必测**：按固定顺序拒绝未知、重复、不兼容和禁用配置；错误只暴露静态目录与受限 details。
4. **取消与终态必测**：立即/并发/重复收集共享一个终态；取消竞争、迟到事件/成功不能改变首个终态；终态 Result 可见后无事件可见。
5. **时间类用例不等待**：超时、长运行与延迟通过手动假时钟/事件闸门构造，不用真实 sleep 决定结果。
6. **零接线回归必测**：证明 ContractModel、Worker/Factory/API、迁移、锁文件和保护文件保持现状。

## 2. 测试环境与数据构造

| 环境 | 用途 |
|---|---|
| 单测（纯内存） | DTO、错误目录、能力、注册中心、版本解析、工厂隔离与依赖方向 |
| 契约集成（两个测试 Adapter） | 完整异步生命周期、取消竞争、错误场景、重复/冲突/迟到事件；无需 DB、网络、模型或真实进程 |
| 既有 PG 集成回归 | 运行 `test_runtime_postgres.py` 等确认未接线的现有行为不变；使用专用 `TEST_DATABASE_URL` |

**数据构造约定**：固定 execution/tenant/agent ID；LocalTest 事件 ID 由 execution_id+ordinal 经 UUIDv5 派生，timestamp 为固定 epoch+ordinal。尝试从原始异常、input/config/provider response 及禁止的 details 键注入 `secret-marker`，断言输入被拒绝或安全输出不含标记，不得把任意文本放入合法 details。每个异步用例结束确认所有 owned tasks 已 await/done，且无 Adapter-owned 或 test-created pending task；completed task 引用可保留并以 `all(done)` 检查，不要求最终 task set 为空。执行前 empty-set 断言是另一个独立条件。

注册矩阵至少包含独立 Engine/Protocol、两个显式 Adapter 版本、禁用项及未声明组合；LocalTest 三元组为 `(local-test,scripted,v1)`，第二 Adapter 三元组为 `(contract-probe,contract-scripted,v1)`。

## 3. 单元测试

| 编号 | 用例 | 预期 | 溯源 |
|---|---|---|---|
| P1-UT-01 | 六类模型合法/缺字段/未知字段/非法版本、ID、opaque 字符串、timestamp 与状态参数化校验 | 合法值逐字保留；非法值均 ValidationError；strict 模式拒绝 coercion，input 不 trim | FR-1、AC-1 |
| P1-UT-02 | 两个实例分别修改 config、metadata、artifacts、usage、payload、effective_capabilities 等默认集合 | 实例间无可变默认共享，原实例不受影响 | FR-1、AC-1 |
| P1-UT-03 | Request/Handle/Result/Event 的 ExecutionKey、Adapter 身份及 Event/Handle session 一致性 | 独立 DTO 仅校验自身；不匹配身份在 Adapter 边界/公共套件被拒绝，绝不修补 | FR-1、FR-2 |
| P1-UT-04 | Result 三种终态的 output/error 正反向组合 | completed+error、failed 无 error/带 output/带 cancelled error、cancelled 带 output 或 error 均直接 ValidationError；合法 artifacts/usage/engine_metadata 各终态均允许 | FR-1、FR-2 |
| P1-UT-05 | 十类 category、静态目录每个 code、只读 computed message、retryable、受限 details，以及 ExecutionError 直接和 failed Result nested 的 mapping/JSON round-trip | code 唯一归属；直接 `model_validate(model_dump())`、直接 `model_validate_json(model_dump_json())` 及 nested mapping/JSON 成功往返并保留安全 model_dump；精确目录 message 仅作 no-op token 且重算；任意/不匹配/非 string message 及 code 缺失/非法时的 message 均 ValidationError，绝不覆盖 computed property；异常/input/config/provider 文本和堆栈不泄露 | FR-1、FR-4、AC-4、R9 |
| P1-UT-06 | EngineCapabilities 11 项默认与显式声明 | 未声明项均严格 false；声明 tool_calling 不自动改变其他能力或授权，非 bool 被拒绝 | FR-2、FR-4、AC-4 |
| P1-UT-07 | AgentEvent event_id、sequence、event_type、schema_version/source、UTC timestamp 与 payload | 字段合法；独立 Event 不施加跨事件排序，禁止 wall-clock/random 默认工厂 | FR-4 |
| P1-UT-08 | Engine/Protocol/Adapter 描述符独立注册及重复/引用校验 | Engine/Protocol 可独立存在；完全相同或冲突重复均拒绝；未知引用拒绝；disabled 可注册不可解析 | FR-3、AC-5 |
| P1-UT-09 | 有效三元组及两个显式版本解析；对象仍存活时的连续独立解析、singleton、A→B→A 循环、不可 weakref 候选、死亡引用回收、地址复用与自定义 `__eq__` | 精确返回对应工厂实例，无 latest；每次解析重新调用工厂，两个同时存活结果以 `is not` 区分且状态不共享；同一存活 singleton 第二次及 A→B→A 第三次复用均以 `configuration_error/adapter_contract_mismatch` 拒绝且对象不逃逸；不可 weakref 候选首次返回前同样拒绝；weakref/gc 证明 Registry 不强留 Adapter，死亡引用在解析时清理，后续新对象不受地址复用影响且身份绝不使用 bare `id()`；任意 `__eq__` 不被调用 | FR-3、AC-5、R10 |
| P1-UT-10 | 未知/禁用 Engine、Protocol、未声明 pair、其他版本和禁用 Adapter 解析 | 严格按 unknown_engine→engine_disabled→unknown_protocol→protocol_disabled→incompatible_engine_protocol→unknown_adapter_version→adapter_disabled 返回稳定 code | FR-3、FR-4、AC-6 |
| P1-UT-11 | 工厂抛错、身份/版本不一致、缺少 Protocol 方法、生命周期 bound-signature 错误 arity、Future/Task-returning factory 的 awaitable 拒绝与清理，以及独立 `BaseException` 边界 | 前三类分别映射 adapter_factory_failed、adapter_identity_mismatch、adapter_contract_mismatch；对 bound method 以 `Signature.bind` 占位而不执行，`get_capabilities` 绑定 0 参，其余四方法各绑定 1 参，错误 arity 为 adapter_contract_mismatch；实例在检查前不逃逸；同步 resolve 对 factory 返回的 Future/Task 以 adapter_contract_mismatch 拒绝，并 cancel 返回的 Future/Task 作为 cleanup，断言 `future.cancelled()`，Task fixture 还须 await 完成清理且无 pending task；独立边界用例验证 `CancelledError`/其他 `BaseException` 控制流不被吞掉或改写，与 Future/Task cleanup 分开断言；诊断无敏感 config 或原始异常文本 | FR-3、AC-6、R3/R5/R10 |
| P1-UT-12 | 公共契约、Registry、LocalTestAdapter 与包入口依赖方向静态检查；按 T2 contracts/包入口→T3 Registry→T4 LocalTestAdapter/no-eager-test-import 增量加入，T6 完整重跑 | Contracts 不 import Registry/Worker/Repository/Factory/具体 Engine；Registry 不 import 具体 Adapter；LocalTestAdapter 不 import Registry；包入口不 eager import 测试 Adapter；既有 ContractModel 零 diff；当前任务计划覆盖的模块缺失必须失败，不得 skip 或因 absent 而通过，T4 才完成整项 | FR-6、G1 |

## 4. 契约与集成测试

| 编号 | 用例 | 预期 | 溯源 |
|---|---|---|---|
| P1-IT-01 | 成功场景 capabilities→start→stream→collect；覆盖 start 后立即/并发/重复 collect、第二次 start，以及首个 stream consumer 合法创建后的并发第二次 consumer 和首个迭代器 `aclose()` 后的顺序第二次 consumer | 五方法与身份属性正常，LocalTest 序号连续，所有收集返回相等 completed Result；第二次 start 和两种第二次 consumer 尝试均为 `configuration_error/invalid_adapter_state`，不允许 stream replay/restart | AC-2、FR-2 |
| P1-IT-02 | 多事件流式场景与空事件场景 | 多事件保持顺序和 payload；空事件可直接得到有效终态，stream 不悬挂 | FR-2、AC-2 |
| P1-IT-03 | start 前非法场景、Request 三元组不匹配及启动前 EngineUnavailable/ResourceExhausted | 均在有效 Handle 产生前失败，分类正确；仅明确启动前 EngineUnavailable 与 ResourceExhausted 可 retryable，启动后失败及 timeout 默认 False，Phase 1 不重试 | FR-2、FR-5、AC-4 |
| P1-IT-04 | ConfigurationError、ProtocolError、AuthenticationError、PermissionDenied 参数化场景 | 各场景稳定映射静态 category/code/message/retryable；Registry/Adapter 边界不复制 Pydantic 原值或异常字符串 | AC-4、FR-4 |
| P1-IT-05 | WorkspaceError、InternalError、未知异常及模拟进程故障 | 未知异常仅映射 internal_error/internal_error；模拟故障为 internal_error/simulated_process_failure；process_id 为 None，无真实 Host 断言 | AC-4、AC-7、FR-5 |
| P1-IT-06 | 手动假时钟触发内建 TimeoutError | 不实际等待即唤醒等待者，得到 failed + timeout/execution_timeout；不自动重试，启动后 timeout 默认不可重试 | AC-7、FR-4 |
| P1-IT-07 | 长运行启动后重复/并发 cancel，再并发收集结果和事件 | cancel 幂等，闸门释放且流关闭，所有收集得到相等 cancelled Result（error=None），owned/test 任务全部清理 | AC-3、FR-2 |
| P1-IT-08 | 分别控制取消先完成、成功先完成，随后注入迟到成功/事件 | 首个终态原子获胜；已成功时 cancel 为 no-op，已取消时成功被抑制；终态 Result 可见后无事件可见，无第二终态 | AC-3、FR-2 |
| P1-IT-09 | exact duplicate、同 event_id 不同内容、新 event_id 的低序号、合法 gap 及提前 aclose | 完整重复和迟到事件原样 yield 且不推进/降低水位；内容冲突为 event_identity_conflict；gap 合法；timestamp 不排序；迭代关闭无 pending task | AC-7、FR-4 |
| P1-IT-10 | 注册 `(contract-probe,contract-scripted,v1)` 第二 Adapter 并复用成功、空/多事件、错误、取消、重复/迟到、幂等收集和清理整套公共用例 | 第二 Adapter 结构独立且非 LocalTestAdapter 子类；套件不 import LocalTest 具体类型；不修改公共契约、Registry 接口或 Worker | AC-5、G1、G2 |
| P1-IT-11 | 重复运行全部 LocalTestAdapter 场景至少两轮，并覆盖 stream failure/collector cancellation | 语义、错误和事件脚本确定，无跨场景状态；success/failure/cancel/timeout/iterator close 后所有 owned tasks 已 await/done，无 Adapter-owned 或 test-created pending task；completed task 引用可保留并以 `all(done)` 检查，执行前 empty-set 断言另行保留 | AC-7、FR-5、R11 |

## 5. 通用核对项（本阶段适用）

| 编号 | 核对项 | 通过标准 | 溯源 |
|---|---|---|---|
| P1-CM-01 | 数据库迁移不变 | `alembic heads` 为 `0057_industry_pack_runtime`；相对 `4dfcfb41e9cbb799753986c2d76134514bbd19be` 无版本文件新增/修改，无 downgrade 需求 | AC-8、G4 |
| P1-CM-02 | 生产零接线与配置不变 | Worker/Factory/组合根未调用新执行路径，无新运行时开关、Settings、外部 Engine、凭据、前端或 deploy 变更 | AC-8、FR-6 |
| P1-CM-03 | 公共 API/SSE/Run 契约兼容 | RunRequest/RunSnapshot/RunStatus、事件名和路由未改；相关既有 Runtime/API/SSE 测试全绿 | AC-8、FR-6 |
| P1-CM-04 | 敏感信息与日志 | DTO/注册/Adapter 安全输出不含 secret-marker、凭据、连接串、Pydantic 原值、异常原文、原始堆栈或客户输入 | AC-4、非功能 |
| P1-CM-05 | 多租户与实例边界 | tenant_id 不被注册中心改写；不同 request/解析实例无可观察状态串用；事件 high-water 仅存在每 active execution | FR-1、FR-3、非功能 |
| P1-CM-06 | 代码质量与依赖边界 | 新增测试及 `ruff check src tests`、受影响文件 `ruff format --check`、`test_core_boundaries.py` 全绿；R8 依赖方向满足，`backend/uv.lock` 零 diff | FR-6、G1 |

## 6. 回归范围

- `backend/tests/test_runtime_engine.py`：ReAct 推理、工具循环、预算、错误与取消原行为不变。
- `backend/tests/test_runtime_postgres.py`：队列、Lease、终态、事件回放、HTTP/SSE 原行为不变。
- `backend/tests/test_open_platform.py`、`test_extension_contracts.py`：公开流、ContractModel 与既有 Run/Extension 端口不变。
- `backend/tests/test_runtime_baseline.py`、`test_core_boundaries.py`：Phase 0 基线及架构边界保持有效。
- Agent 快照、模型 Profile、Memory 相关既有测试至少运行受影响模块；新包未接线时不得出现行为差异。

## 7. 缺陷分级与出口准则

| 级别 | 定义 | 处理 |
|---|---|---|
| P0 阻断 | 破坏现有 Run 主流程；数据丢失；跨租户或凭据泄露 | 修复并全量回归后方可继续 |
| P1 严重 | 生命周期/终态错误；取消失效；解析回退错误；公共契约阻碍独立 Adapter；事件身份冲突被修补 | 修复前不得进入验收 |
| P2 一般 | 非关键诊断、测试确定性或错误分类偏差且不影响生产 | 记录后可带问题验收，需产品签字 |
| P3 轻微 | 文档、命名、非敏感日志问题 | 排期修复 |

**出口准则**：P1-UT/IT/CM 全部实际执行并通过；AC-1～AC-8 可复现通过；受影响既有回归全绿；无 P0/P1 未关闭；无生产行为 diff、迁移/锁文件变化或悬挂异步任务。完整套件由 CI 按仓库约定运行，未执行的本地或 CI 项目不得记为通过。
