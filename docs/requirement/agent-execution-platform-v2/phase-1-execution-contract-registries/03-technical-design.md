# Phase 1 · 执行契约与注册中心 — 技术落地文档

> 状态：待评审 / 待实施
> 创建：2026-11-02
> 依据：`docs/architecture/agent-execution-platform-v2.md` 第 4～6、15～17、19 节，Phase 1；`02-requirements.md`（FR-1～FR-6、AC-1～AC-8）

## 现状核查与改动总览

现状：`RuntimeEngine.run()` 位于 `core_platform/agent_runtime/engine.py`；`RuntimeWorker` 直接经 `RuntimeFactory.for_run()` 取得并执行 Runtime；`RunRepository` 已处理队列、Lease、事件与终态；`extension_contracts/runtime.py` 是 Run/业务端口边界。以下 `agent_execution` 路径均为**拟新增**，当前不存在，本文不代表已实现。

| 层 | 文件 | 改动 |
|---|---|---|
| 迁移 | `backend/migrations/versions/` | 不新增或修改迁移；当前 head `0052_memory_tasks_tenant_index.py` 保持不变 |
| 新模块 | `backend/src/agent_platform/core_platform/agent_execution/contracts/{request,handle,result,events,capabilities,errors}.py` | 六类版本化 DTO 与错误分类；不依赖 Runtime/应用层 |
| 新模块 | `backend/src/agent_platform/core_platform/agent_execution/contracts/adapter.py` | AgentEngineAdapter Protocol 与身份/生命周期约束 |
| 新模块 | `backend/src/agent_platform/core_platform/agent_execution/registry/{engine_registry,protocol_registry,adapter_registry}.py` | 描述符、独立注册、兼容矩阵和精确三元组解析 |
| 新模块 | `backend/src/agent_platform/core_platform/agent_execution/adapters/testing/local_test_adapter.py` | 可编程、确定性、无外部依赖的契约 Adapter |
| 测试 | `backend/tests/{test_agent_execution_contracts,test_agent_execution_registries,test_local_test_adapter}.py` | 模型、注册/版本及完整 Adapter 契约测试 |
| 既有入口 | `runtime_factory.py`、`runtime_composition.py`、`worker.py`、`repository.py`、`schemas.py`、`extension_contracts/runtime.py` | 本阶段不改生产接线、公共 Run 端口或现有模型 |
| 部署/配置/前端 | `deploy/`、Settings、`.env.example`、`frontend/` | 本阶段无变更、无新开关 |

## 数据模型与模块边界

### 契约字段与不变量

| 模型 | 必需公共字段 | 关键不变量 |
|---|---|---|
| ExecutionRequest | execution/tenant/agent/conversation ID、engine/protocol/adapter 三元组、input、config、effective_capabilities、可选 session/workdir/timeout/trace | ID 非空且 execution_id 贯穿全生命周期；config 由可信调用方提供；本阶段不计算 Effective 能力 |
| ExecutionHandle | execution_id、三元组、provider_session_id、内部 process_id、status、metadata | execution_id 与 request 相同；process_id/metadata 不自动暴露到 RunView 或 SSE |
| ExecutionResult | execution_id、completed/failed/cancelled、output、artifacts、usage、engine_metadata、error | completed 不得带 error；failed 必须带规范化 error；cancelled 不输出迟到成功 output |
| ExecutionError | category、稳定 code、安全 message、retryable、受限 details | category 覆盖 FR-4 十类；原始异常仅作内部 cause，不序列化敏感文本 |
| AgentEvent | event_id、schema_version、execution_id、sequence、event_type、source、timestamp、payload、trace_id | 单 execution 内 sequence 单调；event_id 可识别重复；本阶段不写 runtime_events |
| EngineCapabilities | streaming、persistent_session、session_resume、cancellation、human_approval、interactive_input、tool_calling、file_operations、terminal_execution、native_events、workspace_required | 未声明能力为 false；Declared 不代表 Available/Effective，更不代表授权 |

契约版本采用显式 `contract_version=v1`，AgentEvent 采用 `schema_version=v1`；不兼容主版本必须新增模型/转换层，不在 v1 中静默改义。DTO 禁止未知字段和共享可变默认值。

### 责任边界

- `contracts` 只表达数据与 Adapter Protocol，不操作 Worker 队列、不决定租户权限、不提交 Run 终态。
- `registry` 只保存描述符、兼容关系和工厂；不做动态网络发现、不执行真实健康检查、不构造 RuntimeEngine。
- `LocalTestAdapter` 只模拟 Adapter 语义；“进程故障”是测试场景，不表示已有 Process Supervisor。
- 既有 `extension_contracts/runtime.py` 继续服务业务能力；不得把 Engine Adapter 塞入 Capability/Extension Registry。

## 核心流程

### 1. 注册与精确解析（`registry/`）

```
注册 Engine → 注册 Protocol → 注册 Adapter 工厂及其支持组合
→ 校验描述符身份、版本、组合和重复冲突
→ resolve(engine_id, protocol_id, adapter_version)
→ 精确查找并创建新实例 → 校验实例身份 → 返回或抛 ConfigurationError
```

- Engine/Protocol 可独立注册；Adapter 注册记录声明允许的组合，禁止解析时猜测。
- 完全相同注册是否允许须在实现前固定为“重复注册一律拒绝”或“仅完全相同幂等”；测试按选定规则固化。冲突定义必须拒绝，本文验收默认采用“重复注册一律拒绝”以尽早暴露组合错误。
- 不提供 latest、版本范围或自动降级；禁用记录和未知 ID 均 fail closed。

### 2. Adapter 生命周期（`contracts/adapter.py`）

```
get_capabilities → start(request) → 并发消费 stream_events(handle)
→ collect_result(handle) → completed / failed / cancelled
                      ↘ cancel(handle)（任意运行时刻、可重复）↗
```

- start 失败不得返回半有效 Handle；stream 的协议异常必须能传至调用方并映射为错误。
- collect_result 在流正常结束后返回结果；cancel 后流必须终止，重复 cancel 与重复结果收集不得产生第二终态。
- 取消不撤销已完成副作用；超时也不证明 Engine 未执行工作。retryable 只是元数据，本阶段不自动重试。
- 重复/延迟事件在契约层可观测，持久去重和 SSE 重放仍由后续编排及既有 Repository 负责。

### 3. LocalTestAdapter 场景驱动（`adapters/testing/local_test_adapter.py`）

场景定义包含身份、能力、启动错误、事件脚本、结果、完成/取消闸门及延迟事件；测试时钟推进超时，事件闸门控制长运行与取消。每个场景验证五方法和三个身份属性，失败后清理异步迭代器与任务。

### 4. 错误与事件边界

| 来源 | 规范化结果 | 本阶段不做 |
|---|---|---|
| DTO/注册/版本错误 | ConfigurationError，稳定 code，无自动回退 | 不修改 Agent 配置，不写数据库 |
| Adapter 启动/协议/收集异常 | 对应 ExecutionError；未知异常归 InternalError | 不把原始异常文本暴露给 API |
| Timeout/Cancelled | Timeout 或 Cancelled；保留是否可重试建议 | 不推断副作用已回滚，不自动重试 |
| 原生事件 | AgentEvent(source=engine_native)，保留 payload | 不强行转换为 ReAct Tool Calling 抽象 |

## 配置与模型调用路径

本阶段无新 Settings、环境变量或 AgentConfig，也无模型调用路径。测试构造可信 request，不读取真实凭据、模型 Profile 或租户配置；Phase 3 才负责从类型化配置生成 config 和 Effective 能力。

## 测试方案

| 层 | 用例 |
|---|---|
| 单测 | 六类 DTO 校验、默认值隔离、十类错误、能力默认值、注册/版本/兼容矩阵、工厂实例隔离 |
| 契约/集成 | LocalTestAdapter 全生命周期、五方法、事件顺序、取消幂等、超时、全部错误分类、重复/延迟事件 |
| 回归 | 既有 `test_runtime_engine.py`、`test_runtime_postgres.py` 及 API/SSE 测试；确认未接生产路径、迁移 head 不变 |

详细步骤和溯源见 `04-test-plan.md`。

## 上线与回滚

- 新包不接入生产组合根，无数据库变更、部署变更或运行时开关；合入只增加可被测试直接调用的模块。
- CI 必须证明现有 Runtime/API 回归无 diff；不得借本阶段改变事件结构或 Run 状态。
- 回滚可还原未接线的新包及测试，无需 Alembic downgrade、数据修复或 Worker 切换。
- Phase 2 接入前须重新核对 v1 契约与真实 React 行为；如需不兼容变更，应先修订本阶段文档和版本决策，不得静默修改。
