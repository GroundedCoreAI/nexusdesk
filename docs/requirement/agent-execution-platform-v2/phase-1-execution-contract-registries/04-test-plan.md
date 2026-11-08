# Phase 1 · 执行契约与注册中心 — 测试方案

> 状态：待评审 / 待实施
> 创建：2026-11-02
> 依据：`02-requirements.md`（FR-1～FR-6、AC-1～AC-8）、`03-technical-design.md`（契约 v1、精确注册解析、LocalTestAdapter、无迁移）

## 1. 测试范围与原则

**范围**：六类执行 DTO、Adapter Protocol 全生命周期、Engine/Protocol/Adapter 注册中心、版本与兼容矩阵、错误/事件/取消语义、LocalTestAdapter 及生产路径零接线验证。

**原则**：

1. **完整契约必测**：三个身份属性和 get_capabilities、start、stream_events、cancel、collect_result 五方法均有独立及组合断言。
2. **失败关闭必测**：未知、冲突、不兼容和禁用配置不得回退到其他实现；错误不得泄漏敏感文本。
3. **取消与迟到结果必测**：取消幂等，取消/终态后的迟到事件和成功不能改变逻辑结果。
4. **时间类用例不等待**：超时、长运行与延迟通过测试时钟/事件闸门构造，不用真实长 sleep。
5. **零接线回归必测**：本阶段没有生产开关，必须证明 Worker/Factory/API 和迁移保持现状。

## 2. 测试环境与数据构造

| 环境 | 用途 |
|---|---|
| 单测（纯内存） | DTO、错误、能力、注册中心、版本解析、工厂隔离与事件规则 |
| 契约集成（LocalTestAdapter） | 完整异步生命周期、取消竞争、错误场景、重复/延迟事件；无需 DB、网络、模型或真实进程 |
| 既有 PG 集成回归 | 运行 `test_runtime_postgres.py` 等确认未接线的现有行为不变；使用专用 `TEST_DATABASE_URL` |

**数据构造约定**：固定 execution/tenant/agent ID 和事件脚本；错误 details 放入 `secret-marker` 验证脱敏；每个异步用例结束检查无 pending task。注册矩阵至少包含一个 Engine、两个 Protocol、两个 Adapter 版本以及未声明组合。

## 3. 单元测试

| 编号 | 用例 | 预期 | 溯源 |
|---|---|---|---|
| P1-UT-01 | 六类模型合法 payload 与缺字段/未知字段/非法状态参数化校验 | 合法值保留版本与 ID；非法值均被 ValidationError 拒绝 | FR-1、AC-1 |
| P1-UT-02 | 两个实例分别修改 config、metadata、artifacts、usage、payload、capabilities 默认集合 | 实例间无可变默认共享，原实例不受影响 | FR-1、AC-1 |
| P1-UT-03 | Request/Handle/Result/Event 的 execution_id 和三元组一致性 | 不匹配身份不能形成有效生命周期对象；公共 Handle 不含公共 API 暴露约定 | FR-1、FR-2 |
| P1-UT-04 | Result 状态与 output/error 组合校验 | completed+error、failed 无 error、cancelled 携带迟到成功 output 均被拒绝或规范化拒绝 | FR-1、FR-2 |
| P1-UT-05 | 十类 ExecutionError 的 category/code/retryable/details 转换 | 分类完整且稳定；secret-marker、堆栈和输入原文不进入安全 message | FR-4、AC-4 |
| P1-UT-06 | EngineCapabilities 默认与显式声明 | 未声明项均 false；声明 tool_calling 不会自动改变其他能力或授权 | FR-2、FR-4、AC-4 |
| P1-UT-07 | AgentEvent 唯一 event_id、单调 sequence、schema_version/source 校验 | 顺序/版本合法；重复 event_id 可被识别，契约层不擅自丢弃 | FR-4 |
| P1-UT-08 | Engine 与 Protocol 独立注册及描述符校验 | 两类记录可独立存在；空 ID、非法版本、冲突重复被拒绝 | FR-3、AC-5 |
| P1-UT-09 | 有效三元组及两个显式版本解析 | 精确返回对应工厂实例，无 latest；连续解析实例状态互不共享 | FR-3、AC-5 |
| P1-UT-10 | 未知 Engine/Protocol/版本、未声明组合和禁用记录解析 | 全部返回稳定 ConfigurationError code，不回退 | FR-3、FR-4、AC-6 |
| P1-UT-11 | Adapter 工厂身份/版本与注册记录不一致 | 实例被拒绝且不泄漏给调用方，错误可诊断但无敏感 config | FR-3、AC-6 |
| P1-UT-12 | 公共契约依赖方向静态检查 | contracts/registry 不 import Worker、Repository、Factory 或具体 Engine | FR-6、G1 |

## 4. 契约与集成测试

| 编号 | 用例 | 预期 | 溯源 |
|---|---|---|---|
| P1-IT-01 | 成功场景依次调用 capabilities→start→stream→collect | 五方法与身份属性正常，事件序号连续，结果 completed，output/usage 与脚本一致 | AC-2、FR-2 |
| P1-IT-02 | 多事件流式场景与空事件场景 | 多事件保持顺序和 payload；空事件可直接得到有效终态，stream 不悬挂 | FR-2、AC-2 |
| P1-IT-03 | start 前非法场景及 start 时 EngineUnavailable | 非法配置/不可用 Engine 在有效 Handle 产生前失败，分类正确 | FR-2、FR-5、AC-4 |
| P1-IT-04 | ConfigurationError、ProtocolError、AuthenticationError、PermissionDenied 参数化场景 | 各场景稳定映射 category/code/retryable；无凭据和原始客户输入泄露 | AC-4、FR-4 |
| P1-IT-05 | ResourceExhausted、WorkspaceError、InternalError 及模拟进程故障 | 各场景得到确定 failed/错误语义；模拟进程故障不被描述为真实 Host 测试 | AC-4、AC-7、FR-5 |
| P1-IT-06 | 测试时钟触发 Timeout | 不实际等待即得到 Timeout；结果不自动重试，不宣称无副作用 | AC-7、FR-4 |
| P1-IT-07 | 长运行启动后 cancel 两次并收集结果 | cancel 幂等，流及时关闭，结果 cancelled，任务全部清理 | AC-3、FR-2 |
| P1-IT-08 | cancel 与成功结果竞争，随后注入迟到成功/事件 | cancelled 终态不被覆盖，取消后无有效新事件，无第二终态 | AC-3、FR-2 |
| P1-IT-09 | 重复 event_id、乱序/延迟 sequence 场景 | 契约层准确保留异常供上层识别，不伪造持久去重能力；测试可确定完成 | AC-7、FR-4 |
| P1-IT-10 | 新增测试专用 Engine/Protocol/Adapter 并复用整套契约用例 | 不修改公共契约和 Worker 即可注册并通过同一套件 | AC-5、G1、G2 |
| P1-IT-11 | 重复运行全部 LocalTestAdapter 场景至少两轮 | 语义、错误和事件脚本结果确定，无跨场景状态或悬挂任务 | AC-7、FR-5 |

## 5. 通用核对项（本阶段适用）

| 编号 | 核对项 | 通过标准 | 溯源 |
|---|---|---|---|
| P1-CM-01 | 数据库迁移不变 | Alembic head 与实施入口记录的目标提交实际值一致，无新增/修改版本文件，无 downgrade 需求 | AC-8、G4 |
| P1-CM-02 | 生产零接线与配置不变 | Worker/Factory/组合根未调用新执行路径，无新运行时开关，旧路径默认且唯一 | AC-8、FR-6 |
| P1-CM-03 | 公共 API/SSE/Run 契约兼容 | RunRequest/RunSnapshot/RunStatus、事件名和路由未改；相关既有测试全绿 | AC-8、FR-6 |
| P1-CM-04 | 敏感信息与日志 | DTO/注册/Adapter 错误输出不含 secret-marker、凭据、连接串、原始堆栈或客户输入 | AC-4、非功能 |
| P1-CM-05 | 多租户与实例边界 | tenant_id 不被注册中心改写；不同 request/解析实例无可观察状态串用 | FR-1、FR-3、非功能 |
| P1-CM-06 | 代码质量与依赖边界 | 受影响后端 ruff/pytest 全绿，contracts/registry 无应用层或具体 Engine 反向依赖 | FR-6、G1 |

## 6. 回归范围

- `backend/tests/test_runtime_engine.py`：ReAct 推理、工具循环、预算、错误与取消原行为不变。
- `backend/tests/test_runtime_postgres.py`：队列、Lease、终态、事件回放、HTTP/SSE 原行为不变。
- `backend/tests/test_open_platform.py`、`test_extension_contracts.py`：公开流与既有 Run/Extension 端口不变。
- Agent 快照、模型 Profile、Memory 相关既有测试至少运行受影响模块；新包未接线时不得出现行为差异。

## 7. 缺陷分级与出口准则

| 级别 | 定义 | 处理 |
|---|---|---|
| P0 阻断 | 破坏现有 Run 主流程；数据丢失；跨租户或凭据泄露 | 修复并全量回归后方可继续 |
| P1 严重 | 生命周期/终态错误；取消失效；解析回退错误；公共契约阻碍独立 Adapter | 修复前不得进入验收 |
| P2 一般 | 非关键诊断、测试确定性或错误分类偏差且不影响生产 | 记录后可带问题验收，需产品签字 |
| P3 轻微 | 文档、命名、非敏感日志问题 | 排期修复 |

**出口准则**：P1-UT/IT/CM 全部通过；AC-1～AC-8 可复现通过；受影响既有回归全绿；无 P0/P1 未关闭；无生产行为 diff、无迁移变化、无悬挂异步任务。
