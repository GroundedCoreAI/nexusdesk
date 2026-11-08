# Phase 0 基线 · Runtime 执行依赖与接口盘点

> 基线提交：`c6c47dec39025ebd4d1176c1e9925bac9c99c4fd`
> 盘点日期：2026-11-07；复核修订：2026-11-08
> 证据范围：目标提交的静态代码与既有测试；新增回归节点和双跑结果见 `06-test-report.md`
> 迁移边界：目标 head 为 `0057_industry_pack_runtime`，Phase 0 不新增或修改迁移

## 1. 入口与公共契约

| 入口 | 当前路径 | 关键行为 |
|---|---|---|
| 内部 Runtime API | `backend/src/agent_platform/applications/customer_service/runtime_routes.py:40-89` | 挂载于 `/api/v1`，提供 Run 提交、查询、取消和事件 SSE；提交经 `RuntimeAdmission.submit` |
| 开放平台和公开 SSE | `backend/src/agent_platform/business_capabilities/open_platform/routes.py:256-260,408-465`、`backend/src/agent_platform/business_capabilities/open_platform/service.py:377-439` | 挂载于 `/openapi/v1`，增加应用/会话授权和幂等，再进入同一 Run 持久化路径 |
| 客服入口 | `backend/src/agent_platform/business_capabilities/customer_service/service.py:243-276` | 可携带已发布 Agent 快照提交到同一 Repository |
| Worker | `backend/src/agent_platform/applications/application_factory.py:76-132`、`backend/src/agent_platform/applications/worker/__main__.py:7-19` | 内嵌 Worker 由 lifespan 启停，独立 Worker 调用同一 `serve()` |

当前存在三套不能混称的输入/端口表面：

1. **内部 Run API** 直接接收 `backend/src/agent_platform/core_platform/agent_runtime/schemas.py:7-26` 的核心 `RunRequest`。它含外部字符串 `conversation_id`、最长 8,000 字符的 `message` 且 `extra="forbid"`；`RunView` 不暴露 owner、lease、config、history 或 event sequence。
2. **开放平台提交** 接收 `MessageInput`：`message`、`stream`、`wait_seconds`（默认 30，范围 0–30），conversation UUID 位于 URL path，并要求必填、长度 1–128 的 `Idempotency-Key` 请求头（`backend/src/agent_platform/business_capabilities/open_platform/routes.py:256-260,408-428`）。应用/会话解析后，service 才构造内部核心 `RunRequest`（`backend/src/agent_platform/business_capabilities/open_platform/service.py:418-426`）；公开查询/终态视图在适用处复用 `RunView`。
3. `backend/src/agent_platform/extension_contracts/runtime.py:21-55,203-213` 另定义能力中立的 `RunRequest`/`RunSnapshot`/`RunEvent`/`RunPort`，字段包含 tenant、UUID conversation、`input`、config 和 idempotency key，事件字段名为 `sequence`。目标提交中这套端口未接入 HTTP 执行链；不能把它的字段或限制当作现有任一 HTTP 合同。

## 2. 核心内部接口

| 组件 | 接口与证据 | 当前职责 |
|---|---|---|
| Admission | `backend/src/agent_platform/core_platform/agent_runtime/admission.py:17-67` | 解析会话与 Agent 快照，执行容量/单会话限制，提交 queued Run |
| Repository | `backend/src/agent_platform/core_platform/agent_runtime/repository.py:23-65,151-203,203-285,327-391` | `submit/get/events/claim/append/heartbeat/finish/cancel/reap`；拥有状态与持久事件事务 |
| Worker | `backend/src/agent_platform/core_platform/agent_runtime/worker.py:16-54,145-195` | 每 Worker 一个 owner UUID；排他 claim、心跳监视、执行、取消和清理 |
| Factory | `backend/src/agent_platform/applications/platform_runtime/runtime_factory.py:20-127` | `effective(snapshot)` 生成有效设置；`for_run(row, emit)` 按快照构造每次 Run 的 Runtime |
| Engine | `backend/src/agent_platform/core_platform/agent_runtime/engine.py:20-29,147-221` | 两节点 LangGraph ReAct；`run()` 返回 `(output, final_history, dropped)` |
| Bindings | `backend/src/agent_platform/applications/platform_runtime/service_groups.py:121-141` | 聚合 Engine/settings/snapshot、tool/policy/retrieval/customer/memory/gateway/ledger/replay/events 等进程资源 |
| Memory 端口 | `backend/src/agent_platform/extension_contracts/runtime.py:151-200`、`backend/src/agent_platform/core_platform/agent_runtime/hooks.py:18-35` | 当前实际使用的内存注入与持久化 hook 边界 |

目标 Git 树的 `backend/src/agent_platform/modules/` 下没有第二套 Runtime 源码；本地忽略的 `__pycache__` 不属于基线实现，也不能作为架构门禁中的额外模块证据。

## 3. 构造期与每次 Run 的依赖

### 3.1 进程构造期

`runtime_services()` 是组合根：

1. 读取公开工具规格并计算 fingerprint，明确排除凭据及选定 Worker/数据库设置；创建 SQL engine、LISTEN/NOTIFY listener 与 notifier（`backend/src/agent_platform/applications/platform_runtime/runtime_composition.py:94-141`）。
2. 创建共享 tool/model HTTP client、基础 ToolGateway、基础模型与 RuntimeEngine，以及带业务持久化 hooks 的 RunRepository（`backend/src/agent_platform/applications/platform_runtime/runtime_composition.py:152-190`）。
3. 创建共享 memory store/service groups/RuntimeBindings，再构造单一 RuntimeFactory、RuntimeAdmission 和 RuntimeWorker（`backend/src/agent_platform/applications/platform_runtime/runtime_composition.py:235-292,307-332`）。

这些进程级对象可由多个 Run 复用；模型 HTTP client、工具策略、记忆服务及 Repository 不应在后续重构中被隐式改成每请求重复构造。

### 3.2 提交与 claim

- Admission 将已发布 Agent 快照写入 `runtime_runs.config`，包含 agent id/version、raw versioned config、tool snapshot 和 `is_example`（`backend/src/agent_platform/core_platform/agent_runtime/admission.py:34-67`、`backend/src/agent_platform/business_capabilities/agent_config/service.py:396-426`）。
- claim 而非 submit 加载会话 history、rolling summary 和 customer_id（`backend/src/agent_platform/core_platform/agent_runtime/repository.py:203-251`）。
- claim 成功后才设置 owner、started_at、lease_until 并进入 running（`backend/src/agent_platform/core_platform/agent_runtime/repository.py:203-251`）。

### 3.3 每个 claimed Run

1. Worker 绑定 tenant/business/workspace scope，并比较存储 fingerprint 与当前进程 fingerprint；不一致抛 `RuntimeFault("configuration_changed")`（`backend/src/agent_platform/core_platform/agent_runtime/worker.py:38-46,71-80`）。
2. 生产路径每次调用 `RuntimeFactory.for_run(row, emit)`。无 Agent 快照时返回共享基础 Engine；有快照时创建每次 Run 的 ToolGateway、PlatformTools、GatewayChatModel、effective settings 和 Engine（`backend/src/agent_platform/applications/platform_runtime/runtime_factory.py:76-114`）。
3. `effective()` 合并 prompt/language policy，按策略约束 rounds，并组合全局与 Agent summary 开关（`backend/src/agent_platform/applications/platform_runtime/runtime_factory.py:51-74`）。
4. Worker 仍支持无 `for_run` 的直接 Runtime 对象，属于兼容/测试路径（`backend/src/agent_platform/core_platform/agent_runtime/worker.py:76-88`），不能与生产 Factory 路径混为一谈。
5. Worker 渲染 summary、异步读取 customer memory 后调用 Engine。传给 `MemoryInjectionPort` 的 settings 是 Worker 进程 settings，不是 Factory 的 per-Agent effective settings；Agent memory 配置另从 `row.config` 读取（`backend/src/agent_platform/core_platform/agent_runtime/worker.py:81-89,125-138`、`backend/src/agent_platform/business_capabilities/memory/injection.py:48-59`）。

## 4. 数据读写与副作用边界

| 数据 | 当前读写者与证据 | 基线约束 |
|---|---|---|
| `runtime_runs` | Repository 主写（`backend/src/agent_platform/core_platform/agent_runtime/repository.py:55-149,203-391`）；handoff 专用写入（`backend/src/agent_platform/business_capabilities/human_handoff/service.py:125-153`） | Run 状态、owner/lease、cancel flag、event_seq、output/error 与时间戳不得由 Engine 直接修改 |
| `runtime_events` | Repository `_event`（`backend/src/agent_platform/core_platform/agent_runtime/repository.py:30-53`）；DurableToolReplayCache 专用写入（`backend/src/agent_platform/core_platform/tool_gateway/replay.py:80-119`） | 普通事件与状态同事务；`(run_id, seq)` 为主键，seq 是每 Run 游标 |
| `runtime_conversations` | submit/claim/finish hooks（`backend/src/agent_platform/core_platform/agent_runtime/repository.py:55-149,203-325`、`backend/src/agent_platform/applications/platform_runtime/runtime_hooks.py:49-84`） | history、summary、customer 绑定在 claim/finish 间传递 |
| Agent draft/version/snapshot | AgentConfig service 与 Admission/Factory（`backend/src/agent_platform/business_capabilities/agent_config/service.py:396-426`、`backend/src/agent_platform/applications/platform_runtime/runtime_factory.py:51-114`） | 发布后版本不可被后续发布改写；Run 固定提交时快照 |
| 工具/模型调用 | ToolGateway、GatewayChatModel（`backend/src/agent_platform/core_platform/agent_runtime/engine.py:31-145`、`backend/src/agent_platform/core_platform/platform_services/model_gateway/gateway.py:551-604`） | Engine 只通过抽象调用；Provider 原文不得进入普通异常终态或公开 SSE |
| Memory/总结 | Worker、MemoryInjection、completion hooks（`backend/src/agent_platform/core_platform/agent_runtime/worker.py:81-99`、`backend/src/agent_platform/applications/platform_runtime/runtime_hooks.py:49-135`） | 成功完成才执行完成 hooks；失败/取消不得伪装为成功副作用 |

## 5. 既有测试映射与新增基线职责

| 依赖面 | 目标提交既有证据 | Phase 0 补充职责 |
|---|---|---|
| Engine 循环/预算/错误 | `backend/tests/test_runtime_engine.py:50-237` 覆盖正常工具循环、并行工具、参数校验、预算、空输出、模型超时和 HTTP 脱敏 | 补完整事件 payload、Worker 普通异常映射及 transient delta 分流 |
| 队列/租约/取消 | `backend/tests/test_runtime_postgres.py:60-144,279-307` 覆盖排他 claim、租户隔离、取消后迟到 finish、失租、队列超时和执行中取消 | 补完整生命周期、异常终态、迟到 append、reaper 变体与 SSE 游标边界 |
| API/SSE | `backend/tests/test_runtime_postgres.py:171-202`、`backend/tests/test_open_platform.py:109-159,222-257` | 固定严格 after、隐藏 replay payload、公开字段缩减等当前行为 |
| Agent 快照 | `backend/tests/test_platform_postgres.py:277-301`、`backend/tests/test_memory_config.py:38-201` 的现有默认/legacy/边界用例 | 用合成旧字段形状 fixture 固定发布/快照兼容和跨租户隔离；真实生产样本代表性另列未决项 |
| 进程组合 | `backend/tests/test_runtime_postgres.py:147-168,205-272`、`backend/tests/test_platform_postgres.py:277-301` 间接覆盖 | 后续阶段必须重跑 Factory 与直接 Runtime 两条路径，不得只测新抽象 |

## 6. 已知差异与后续约束

- `tool.replay` 的专用写入没有普通 append 的完整 owner/lease/终态保护（`backend/src/agent_platform/core_platform/tool_gateway/replay.py:80-119` 对照 `backend/src/agent_platform/core_platform/agent_runtime/repository.py:253-270`），详见 `run-lifecycle-events.md`；Phase 0 只记录，不顺手修复。
- 开放平台 `message()` 的 stream 注释称不包含 token delta，但实现会输出可见文本 delta（`backend/src/agent_platform/business_capabilities/open_platform/routes.py:408-428,337-361`）。登记为既有 P2 文档/注释偏差。
- 历史真实发布快照未提供，当前 fixture 不能证明生产样本代表性；见 `configuration-compatibility.md`。
- 后续 Engine/Protocol/Adapter 抽象必须保留上述公共 HTTP 合同、每 Run 快照、fingerprint、租户/工作区绑定和完成事务，不得从中立 `RunPort` 反推当前线上行为。
