# Phase 2 · React Provider 与执行编排器 — 技术落地文档

> 状态：待评审 / 待实施
> 创建：2026-11-02
> 依据：`docs/architecture/agent-execution-platform-v2.md` 第 4～7、12、14～17、19、21 节，Phase 2；`02-requirements.md`（FR-1～FR-6、AC-1～AC-9）

## 现状核查与改动总览

现状已核查：`engine.py` 的 `RuntimeEngine.run()` 返回 `(output, history, dropped)`；`worker.py` 负责 fingerprint、Memory 渲染、heartbeat/cancel monitor、调用 Runtime 和 `repository.finish()`；`repository.py` 已原子维护事件序号、取消优先、owner/lease 校验和终态保护；`runtime_composition.py` 装配唯一 RuntimeFactory/Worker；`runtime_routes.py` 与开放平台路由直接消费既有事件表和 Notifier。下表除“既有”说明外均为**拟改动/拟新增**，不表示已实现。

| 层 | 文件 | 改动 |
|---|---|---|
| 迁移 | `backend/migrations/versions/` | 不新增或修改迁移；当前 head `0052_memory_tasks_tenant_index.py` 保持不变 |
| 新模块 | `backend/src/agent_platform/core_platform/agent_execution/adapters/react/adapter.py` | ReactAdapter 五方法，包装现有 RuntimeEngine，保存执行私有 history/dropped 结果 |
| 新模块 | `backend/src/agent_platform/core_platform/agent_execution/adapters/react/event_mapper.py` | `(kind,data)`→内部 AgentEvent→同名 `(kind,data)` 的无损映射 |
| 新模块 | `backend/src/agent_platform/core_platform/agent_execution/adapters/react/error_mapper.py` | RuntimeFault/Timeout/Cancelled/未知异常到 ExecutionError 的显式映射 |
| 新模块 | `backend/src/agent_platform/core_platform/agent_execution/orchestration/{execution_context,execution_lifecycle,orchestrator}.py` | 私有执行上下文、Outcome、注册解析和 Adapter 全生命周期 |
| 既有适配 | `backend/src/agent_platform/applications/platform_runtime/runtime_factory.py` | 保留 ReAct Runtime 构造和 legacy 属性；Engine 选择移交 Registry，不在 Factory 增加其他 Engine 分支 |
| 入口 | `backend/src/agent_platform/applications/platform_runtime/runtime_composition.py` | 注册 React Provider、构造 Orchestrator；向 Worker 同时注入 legacy 与新路径依赖 |
| Worker | `backend/src/agent_platform/core_platform/agent_runtime/worker.py` | 增加开关分支并调用 Orchestrator；保留 Memory、heartbeat、cancel monitor 和 finish |
| 配置 | `backend/src/agent_platform/core_platform/platform_services/platform_settings/settings.py` | 新增 `execution_orchestrator_enabled: bool = false` |
| Repository/API | `agent_runtime/{repository,schemas}.py`、`extension_contracts/runtime.py`、`customer_service/runtime_routes.py`、开放 API 路由 | 原则上不改；仅允许为等价性修复先做文档修订，禁止公共 schema/终态语义变化 |
| 测试 | `backend/tests/{test_react_engine_adapter,test_execution_orchestrator,test_runtime_postgres,test_open_platform}.py` | 新增 Adapter/编排测试并扩展新旧路径、SSE、终态和回滚回归 |
| 部署/前端 | `deploy/`、`.env.example`、`frontend/` | 不新增服务或 UI；部署文档可补开关占位，前端不变 |

## 数据模型与责任边界

### 无数据库模型变更

本阶段继续以 `runtime_runs` 的一行表示一次 Execution 尝试，`execution_id = str(run.id)`。不增加 Engine 列、Task 表、Session 表或事件表字段；`react/native/v1` 由本阶段兼容层固定选择，执行三元组只进入内存 Handle/安全日志，待 Phase 3 再设计配置与快照持久化。

### 私有上下文与公共结果

| 对象 | 内容 | 所有者可暴露范围 |
|---|---|---|
| ExecutionContext | claimed row、execution_id、history、summary_message、customer_memory、emit、trace/timeout | 仅 Worker→Orchestrator→React Adapter；不序列化到 HTTP/SSE/普通日志 |
| ExecutionOutcome | status、output、history、dropped、error_code、可选 usage | Orchestrator→Worker；Worker 仅取 finish/Memory 所需字段 |
| React 内部 engine_metadata | history、dropped 及 React 私有执行信息 | 仅进程内使用；绝不进入 RunView、公开 ExecutionResult 或 SSE |
| 公共 ExecutionResult/Error/Event | Phase 1 v1 契约 | Adapter 与 Orchestrator 边界；公共 API 仍使用既有 RunView/RunEvent |

Worker 继续拥有队列、并发、owner、heartbeat、配置 fingerprint 和最终 `finish()`；Orchestrator 不直接写数据库，避免双终态提交者。Adapter 不操作队列、不决定授权、不调用 Repository.finish。

## 核心流程

### 1. 组合与注册（`runtime_composition.py`）

```
构造现有 RuntimeEngine + RuntimeFactory（legacy 保留）
→ 注册 Engine(react)、Protocol(native)、Adapter(v1 + ReactAdapterFactory)
→ 构造 ExecutionOrchestrator(registry)
→ RuntimeWorker(repository, legacy_factory, orchestrator, settings, ...)
```

- ReactAdapterFactory 在执行作用域内使用现有 `RuntimeFactory.for_run(row, adapter_emit)` 构造 RuntimeEngine，再把 runtime/history/Memory 输入绑定到独立 ReactAdapter；具体 Engine 构造不进入 Worker/Orchestrator。
- 开关关闭时保留原构造和调用路径；开关开启时注册/构造不完整应在启动或首次执行明确失败，不得静默改走 legacy。
- RuntimeFactory 仍是 ReAct 装配器而非通用 Registry；本阶段不把 Codex 等分支加入 Factory。

### 2. 新路径执行（`orchestrator.py`）

```
Worker 校验 fingerprint、渲染 Memory
→ Orchestrator 以 row 构造 ExecutionRequest（固定 react/native/v1）
→ Registry 精确解析并按 ExecutionContext 创建 ReactAdapter
→ adapter.start(request) 得 Handle
→ 消费 stream_events，将事件还原为 (kind,data) 并调用 Worker 提供的 emit
→ adapter.collect_result → ExecutionOutcome
→ Worker 计算 memory_context 并调用 Repository.finish
```

- Request 的 tenant/agent/conversation/input 来自已认领行与可信快照；本阶段不接受客户端 Engine 选择或 Effective 能力。
- ReactAdapter 的 start 创建独立执行任务与有界内部事件队列；stream_events 转发，collect_result 等待任务并读取唯一结果；队列满/消费者退出须取消生产任务，不能无限缓冲 delta。
- 旧路径直接调用 `runtime.run()` 的分支保持独立，便于逐字段对照；新旧路径共用 Repository 与 SSE，不共用执行中 Adapter 状态。

### 3. 事件与 SSE 等价（`event_mapper.py` + 既有 Worker emit）

| 当前来源 | 新路径内部处理 | 最终既有去向 |
|---|---|---|
| model.started/model.completed/tool.started/tool.completed | 转 AgentEvent(source=engine_native)，保留 kind/payload，再还原 | Worker emit→Repository.append→持久 seq→内部/开放 SSE |
| model.delta | 同上但标记瞬态语义，不写内部 AgentEvent 到数据库 | Worker emit→Notifier.send→瞬态 SSE，无 id、无持久记录 |
| run.queued/started/cancel_requested/completed/failed/cancelled | Adapter 不产生这些平台终态事件 | Repository.submit/claim/cancel/finish/reap 原路径唯一发出 |
| tool.replay 与开放 API 字段过滤 | 不进入 React 新映射或按原类型透传 | 现有路由继续过滤/脱敏，公开 payload 不变 |

AgentEvent.sequence 只用于 Adapter 内部顺序检查，不能替代 `runtime_runs.event_seq`；最终 SSE `id` 仍取数据库 seq。开放 API 的 model/run 字段裁剪、内部 API 的 delta 格式和 15 秒 heartbeat 均不改。

### 4. 错误映射与终态提交

| 原始情况 | ExecutionError 分类 | 对外既有 error_code / 终态 |
|---|---|---|
| RuntimeFault(code) | Configuration/Protocol/ResourceExhausted/Internal 按显式表映射 | failed / 保留原 code，如 agent_model_required、model_round_limit |
| model timeout 的 RuntimeFault | Timeout | failed / model_timeout |
| RuntimeEngine.run 外层 TimeoutError | Timeout | failed / run_timeout |
| 用户/Worker 取消 | Cancelled | cancelled / 无 error；Lease lost 例外见下行 |
| heartbeat=lost 导致取消 | Internal + worker_lost 上下文 | failed / worker_lost |
| 未知异常 | InternalError，安全日志不含异常正文 | failed / execution_error |

取消时 Worker 取消 execution task；Orchestrator 在清理边界调用幂等 `adapter.cancel(handle)`、停止事件迭代并等待执行任务退出，再把取消语义交回 Worker。清理需有界，不能让取消永久悬挂。Worker 的 monitor_failure 优先将结果提交 failed/worker_lost；Repository.finish 现有 `TERMINAL`、owner、lease、cancel_requested 条件不变，保证迟到 completed 不覆盖取消/失败。

### 5. 配置开关与回滚

`Settings` 拟新增：`execution_orchestrator_enabled: bool = False`，由 `AGENT_EXECUTION_ORCHESTRATOR_ENABLED` 覆盖。默认 false；配置经进程启动读取，切换需滚动重启，不支持请求级或动态热切换。

灰度可让部分 Worker 开启、部分关闭，因为 Repository 契约一致。回滚将所有进程置 false 并滚动重启；在途执行按现有取消/Lease 规则收敛，不能为回滚强行把 running 行改为新状态。

## 模型调用路径

ReactAdapter 不改变现有调用顺序：`RuntimeFactory.for_run()` 读取 Agent 快照；有快照时经 `bound_model()` 使用 GatewayChatModel 和指定 `model_profile_id/version`，缺配置仍抛 `agent_model_required`；无快照沿用 base_runtime。工具、语言、轮数、Memory、stream_model_deltas 和 gateway usage 记录均复用现有实现，不新增模型调用或重试。

## 测试方案

| 层 | 用例 |
|---|---|
| 单测 | React 身份/能力/生命周期、事件与错误映射、Request/Outcome、Worker 开关、取消清理、配置默认值 |
| 集成 | 同一模型脚本新旧路径对等、工具/Memory、Orchestrator 注册解析、内部/开放 SSE、PG 取消/超时/Lease 终态 |
| 回归 | `test_runtime_engine.py`、`test_runtime_postgres.py`、`test_open_platform.py`、Agent 配置/语言/模型及 Memory 受影响套件 |
| 回滚 | 默认 off、显式 on、混合 Worker、解析失败不兜底、off 滚动重启后只走 legacy，无迁移变化 |

详细步骤和溯源见 `04-test-plan.md`。

## 上线与回滚

- 先合入默认关闭的 Adapter/Orchestrator/Worker 分支，在 CI 和专用环境完成新旧对等；再按 Worker 小组开启，观察错误率、延迟、SSE 与终态。
- 开启时注册/解析失败必须可见并可告警，不能自动切 legacy 掩盖配置错误；新旧路径日志仅记录安全标识和指标。
- 任一新路径 P0/P1 或指标越界即关闭开关并滚动重启；无需 Alembic downgrade、数据迁移或客户端变更。
- 不在同一 PR 引入 Phase 3 配置、外部 Engine、Host 或事件可靠性改造；避免无法定位对等性差异。
