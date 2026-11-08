# Phase 1 · 执行契约与注册中心 — 业务目标

> 状态：待评审 / 待实施
> 创建：2026-11-02
> 依据：`docs/architecture/agent-execution-platform-v2.md` 第 4～6、15～17、19～21 节，Phase 1

## 要解决的问题

### 问题 1：平台与具体 ReAct Runtime 缺少独立执行边界

当前 `backend/src/agent_platform/applications/platform_runtime/runtime_factory.py` 直接构造 `RuntimeEngine`，`backend/src/agent_platform/core_platform/agent_runtime/worker.py` 直接调用其 `run()`；`backend/src/agent_platform/extension_contracts/runtime.py` 只定义 Run、Runtime 业务端口与绑定，没有 Engine Adapter 的启动、事件、取消和结果契约。新增 Engine 时只能继续把引擎专属分支放进 Factory 或 Worker，难以独立测试和演进。

### 问题 2：Engine、Protocol 与 Adapter 无法独立注册和按版本解析

当前没有 `core_platform/agent_execution` 包，也没有 Engine/Protocol/Adapter 注册中心。架构所需的 `(engine_id, protocol_id, adapter_version)` 三元组、兼容组合校验和明确拒绝未知配置的机制均不存在，无法在不修改公共执行代码的情况下验证新 Adapter。

### 问题 3：Adapter 的错误、取消与能力语义缺少可重复验证手段

现有 `RuntimeFault`、Run 状态与 Runtime Event 服务于单一 ReAct 路径，尚不能作为跨 Engine 契约。没有不依赖外部 Engine 的确定性 Adapter，后续编排器无法稳定覆盖流式事件、失败、超时、取消、重复及延迟事件。

## 业务目标

| 目标 | 说明 |
|---|---|
| G1：稳定公共执行契约 | 定义带版本的 Request、Handle、Result、Error、Event、Capabilities 与完整 Adapter Protocol，隔离 Engine 原生细节 |
| G2：建立可扩展解析机制 | Engine、Protocol、Adapter 可独立注册，按精确三元组解析并拒绝未知、重复或不兼容配置 |
| G3：建立契约质量门禁 | 用 LocalTestAdapter 和公共契约测试覆盖成功、流式、错误、超时与取消，不依赖外部 Engine |
| G4：保持现有运行行为 | 本阶段不切换生产执行路径、不改公共 Run API、不新增数据库迁移，为 Phase 2 提供可回退基础 |

## 成功指标

| 指标 | 基线（现状） | 目标 |
|---|---|---|
| 六类公共模型及 Adapter 五方法的契约测试覆盖率 | 待 Phase 0 盘点现有覆盖 | 本阶段定义的契约分支与 Adapter 五方法 100% 有用例，CI 全绿 |
| 注册中心有效/无效组合解析正确率 | 待 Phase 0 盘点；当前无注册中心 | 固定兼容性矩阵中的有效组合解析成功率 100%，无效组合拒绝率 100% |
| LocalTestAdapter 契约场景通过率 | 待 Phase 0 盘点；当前无该 Adapter | 成功、流式、取消、超时及全部规定错误分类场景 100% 通过，连续运行结果确定 |
| 新增 Adapter 对公共契约的修改次数 | 待 Phase 0 测量 | 用一个测试专用新 Adapter 验证：实现及注册时不修改公共契约和 Worker，修改次数为 0 |
| 对现有 Run 执行延迟与错误率的影响 | 待 Phase 0 测量延迟与错误率基线 | 生产路径不接入新代码，行为 diff 为 0，不引入额外执行延迟或错误 |

## 范围

**包含**：
- 新建版本化执行契约模型、Adapter Protocol 与错误分类。
- 新建 Engine Registry、Protocol Registry、Adapter Registry 及精确版本解析。
- 新建确定性 LocalTestAdapter、可复用契约测试及注册中心测试。
- 明确句柄内部字段、事件顺序、重复/延迟事件、取消幂等和不支持能力的表达方式。

**不包含**（属于后续阶段 / 明确不做）：
- React Provider、Worker 改接编排器及生产路径切换（Phase 2）。
- Agent 配置中的 Engine 选择、Effective 能力计算与策略快照（Phase 3）。
- Runtime Host、真实进程监管、Workspace 与沙箱（Phase 4）。
- Codex 或其他外部 Engine 集成（Phase 5 及以后）。
- 独立 Task/Execution 表、任何 Alembic 迁移、微服务拆分及复杂调度器（本阶段明确不做）。

## 风险与约束

- **契约过度设计**：一次纳入所有 Engine 私有概念会失去稳定性；仅固定跨 Engine 必需字段，其余放入有版本的原生元数据。
- **版本解析不确定**：自动选择“最新版”会使同一 Run 不可复现；Phase 1 只接受显式 `adapter_version`，禁止隐式 latest。
- **测试假实现过于宽松**：LocalTestAdapter 可能掩盖真实生命周期错误；公共契约测试必须作为后续每个 Adapter 的强制套件，而不是只验证测试实现自身。
- **取消与副作用混淆**：取消只停止后续执行，不能承诺撤销已发生的工具副作用；错误与结果模型必须保留这一语义。
- **兼容性**：现有 `agent_runtime`、`extension_contracts/runtime.py`、HTTP/SSE 和表结构保持原样；新包本阶段仅在直接实例化的测试中使用。实施开始时记录目标提交的迁移 head，完成本阶段后必须与该入口值一致；不得沿用历史规划编号代替实际核查。
