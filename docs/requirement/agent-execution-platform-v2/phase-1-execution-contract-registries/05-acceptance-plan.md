# Phase 1 · 执行契约与注册中心 — 验收方案

> 状态：设计决策已冻结（R1～R11）；本地测试与本地自动化验收证据已形成，完整套件与 CI 待执行，正式人工验收及签字未完成
> 创建：2026-11-02；设计冻结：2026-11-08
> 修订：2026-11-09（R11 owned-task 文档澄清，无生命周期行为变更）
> 依据：`01-business-goals.md`（G1～G4、成功指标）、`02-requirements.md`（AC-1～AC-8）；执行依据见 `04-test-plan.md`；裁定与任务见 `08-implementation-breakdown.md`（R1～R11、T1～T8）

## 1. 验收目标与组织

确认契约与注册中心**可独立扩展、生命周期语义正确、测试确定、现有生产路径零影响**，并由产品、QA、研发和 Adapter 代表签字。本文是验收计划，不表示功能已实现或已通过。

| 角色 | 职责 |
|---|---|
| 产品负责人 | 验收主持；确认范围未蔓延及后续阶段边界；P2 遗留处置签字 |
| QA | 执行 A1～A8、核对测试证据与确定性；回归结论和缺陷分级 |
| 研发负责人 | 提供实现、依赖方向、无迁移/零接线证据；指标测量和缺陷修复 |
| Adapter 开发代表 | 用结构独立的第二测试 Adapter 做 UAT，确认无需修改公共契约或 Worker |

## 2. 验收环境与前置条件

| 环境 | 用途 |
|---|---|
| CI / 本地纯 Python 环境 | 契约、注册中心、LocalTestAdapter 与第二 Adapter 全部场景；禁止依赖外部 Engine、凭据和网络 |
| 专用 PostgreSQL 回归环境 | 验证既有 Runtime/API/SSE 未回归及迁移 head 不变 |
| 文档与代码评审环境 | 核对路径、版本、依赖边界、错误脱敏和 Phase 2 非目标 |

**前置条件**：`04-test-plan.md` 全部用例实际执行并通过，无 P0/P1 未关闭；提供 CI run、测试日志、文件变更清单、保护文件 diff 与 `alembic heads` 证据；验收数据和测试租户专用，不使用真实客户输入或凭据。

**入口风险边界**：用户要求启动 Phase 1 只表示接受 Phase 0 未关闭项作为入口风险。Phase 0 的干净已提交产物 CI 双跑、经授权真实历史样本和人工签字仍须各自取得证据；本阶段启动、测试或验收不得被引用为 Phase 0 已正式通过。

## 3. 功能验收清单（对应 AC-1～AC-8）

| # | 验收步骤 | 通过判据 |
|---|---|---|
| A1 | 对应 AC-1：现场运行六类 DTO 正反向参数化用例，演示原始 input 保留及修改一个实例的默认集合后读取另一实例 | 所有非法输入和 Result 组合被拒绝，版本/ID 正确且 input 不 trim；另一实例默认值未变化，证据关联 P1-UT-01～04 |
| A2 | 对应 AC-2：选择成功与流式脚本，按 capabilities→start→stream→collect 执行，演示立即/并发/重复收集、第二次 start，以及首个 stream consumer 创建后的并发和迭代器关闭后的顺序第二次 consumer | 五方法及身份属性符合契约，事件有序，所有收集返回相等 completed Result；第二次 start 和两种第二次 consumer 尝试均为 `configuration_error/invalid_adapter_state`，无 stream replay/restart 或悬挂任务 |
| A3 | 对应 AC-3：分别控制取消先完成和成功先完成，重复 cancel 并注入迟到事件/成功 | 首个终态保持不变；取消先完成时仅 cancelled 且无 error/output；成功先完成时 cancel 为 no-op；终态 Result 可见后无事件可见 |
| A4 | 对应 AC-4：遍历十类错误、静态目录全部 code 和 11 项能力，执行 ExecutionError 直接/failed Result nested mapping/JSON round-trip，并尝试注入任意或不匹配 message、原始异常及非法 details `secret-marker` | category/code/message/retryable 符合矩阵；直接及 nested 往返保留安全 model_dump，精确 message 仅作 no-op integrity token；任意/不匹配/非 string message 和非法 details 均被 ValidationError 拒绝；未声明能力为 false；所有面向调用方输出均无敏感标记 |
| A5 | 对应 AC-5：由 Adapter 代表独立添加 `(contract-probe,contract-scripted,v1)`，复用公共套件；持有两次解析结果证明同时存活身份独立，并执行 singleton、A→B→A 循环、不可 weakref 候选和 weakref/gc 回收场景 | 第二 Adapter 非 LocalTestAdapter 子类；无需改公共契约/Registry 接口/Worker；有效组合均通过；两个存活结果为独立且身份匹配的实例；仍存活 singleton/循环复用和不可 weakref 候选均以 `configuration_error/adapter_contract_mismatch` 在逃逸前拒绝；weakref/gc 证明 Registry 不强留 Adapter，死亡引用被清理，后续新对象不受地址复用影响且未调用任意 `__eq__` |
| A6 | 对应 AC-6：按固定顺序执行未知/禁用 ID、未知版本、未声明组合、任何重复注册、工厂异常/身份错误/缺方法、错误 bound-signature arity、Future/Task-returning factory 的 awaitable 拒绝与清理，以及独立 `BaseException` 边界 | 全部 fail closed，错误代码及优先级稳定；`Signature.bind` 占位检查为 capabilities 0 参、其余四方法各 1 参，错误 arity 为 `adapter_contract_mismatch`；实例在检查前不逃逸；同步 resolve 拒绝 Future/Task 并 cancel 作为 cleanup，`future.cancelled()` 为真，Task fixture 已 await 清理且无 pending task；独立边界用例证明 `CancelledError`/其他 `BaseException` 传播不被吞改；不发生 latest、其他版本或其他 Engine 回退 |
| A7 | 对应 AC-7：运行 exact duplicate、event_id 冲突、迟到/gap 事件、超时、资源耗尽、模拟进程故障两轮并检查 asyncio 任务 | 重复/迟到事件原样可见、冲突被拒绝、gap 合法；其余语义可重复且分类正确；无真实外部依赖、Adapter-owned 或 test-created pending task |
| A8 | 对应 AC-8：检查 ContractModel、生产 Worker/Factory、保护文件及锁文件 diff，运行现有 Runtime/API/SSE 回归并查询迁移 head | 新路径未接生产，旧 API/事件/状态及保护文件零 diff；head 为 `0057_industry_pack_runtime`，锁文件不变，回归全绿 |

每个场景执行记录必须包含：执行人、日期、环境、前置数据、实际结果、判定、CI/日志链接；失败项不得标为通过或以“仅测试实现”为由豁免。环境不可用项标 `pending_env`，人工签字未完成项标 `pending`，不得预先批准。

## 4. UAT 判定（Adapter 开发代表）

- 仅阅读公共契约与注册接口即可完成第二测试 Adapter，不需理解或修改 Worker、Repository、RuntimeFactory，也不继承 LocalTestAdapter。
- 成功、错误和取消场景的诊断足以定位配置/协议问题，但不会暴露原始凭据、config、异常文本或客户内容。
- 明确区分 LocalTestAdapter 的模拟进程故障与 Phase 4 的真实进程监管，验收记录不得混称。

## 5. 业务指标验收

| 指标 | 基线 | 目标 | 测量方法 |
|---|---|---|---|
| 契约分支与五方法覆盖率 | 待 Phase 0 盘点 | 定义的契约分支和五方法 100% 有用例且通过 | 导出 P1-UT/IT 溯源矩阵与 CI 结果，逐方法核对，缺失任一项即不达标 |
| 有效/无效组合解析正确率 | 待 Phase 0 盘点 | 固定矩阵有效成功率与无效拒绝率均 100% | 至少覆盖独立 Engine/Protocol、两个版本、禁用及全部无效类别，保留每行结果与错误优先级 |
| LocalTestAdapter 场景确定通过率 | 待 Phase 0 盘点 | 规定场景两轮均 100% 通过，无 pending task | 同一环境连续执行两轮，保存独立日志及 Adapter/test 任务清理断言 |
| 新 Adapter 对公共契约/Worker 修改次数 | 待 Phase 0 测量 | 0 次 | 审查第二 Adapter 的变更文件清单、非继承结构与公共套件复用证据 |
| 对现有 Run 延迟与错误率影响 | 待 Phase 0 测量 | 生产行为 diff 为 0，无新增执行开销 | 以零生产接线/保护文件 diff 和现有回归为验收证据；性能数值不在本阶段虚构，留 Phase 0/2 实测 |

## 6. 合规核对

| # | 核对项 | 判定 |
|---|---|---|
| C1 | DTO、注册、错误和日志不含明文凭据、连接串、Pydantic 原值、异常原文、原始堆栈或客户输入 | 一票否决 |
| C2 | 不改变租户边界、Run/Extension 公共端口、ContractModel、Agent 快照、HTTP/SSE 与表结构；head 保持 `0057_industry_pack_runtime`，锁文件零 diff | 必须通过 |
| C3 | 新路径未接生产组合根，回滚仅需还原未接线代码，无需迁移或数据修复 | 必须通过 |
| C4 | Effective 能力未被伪装成 Declared 能力，注册中心不承担授权、调度或进程监管 | 必须通过 |

## 7. 通过标准与签字

- **通过**：A1～A8 全部通过；前四项工程硬指标达成；C1～C4 全过；无 P0/P1 遗留。
- **有条件通过**：仅 P2/P3 遗留且每条有 owner 与期限；不得豁免 AC、生产兼容或敏感信息问题。
- **不通过**：任一否决项、AC 或硬指标未达成；修复后重验受影响项及相关回归。
- **基线说明**：标为“待 Phase 0 测量/盘点”的数值不得在验收时补写为既有实测值；本阶段用固定测试矩阵判定目标，生产性能基线留待 Phase 0/2。Phase 0 入口风险的接受不是其验收签字。

输出《Phase 1 验收报告》：AC 执行记录、指标矩阵、CI/迁移证据、合规结果、遗留清单和以下签字。报告只能根据实际证据填写。

| 角色 | 姓名 | 日期 | 结论 | 签字 |
|---|---|---|---|---|
| 产品负责人 | 待填写 | 待填写 | 待填写 | 待填写 |
| QA | 待填写 | 待填写 | 待填写 | 待填写 |
| 研发负责人 | 待填写 | 待填写 | 待填写 | 待填写 |
| Adapter 开发代表 | 待填写 | 待填写 | 待填写 | 待填写 |
