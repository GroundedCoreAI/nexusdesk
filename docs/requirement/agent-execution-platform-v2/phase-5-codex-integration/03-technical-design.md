# Phase 5 · Codex 集成 — 技术落地文档

> 状态：待评审（仅规划，未实施；目标路径须在开发前按 Phase 1~4 实际产物重核）
> 创建：2026-11-02
> 依据：`01-business-goals.md`（G1~G6）、`02-requirements.md`（FR-1~FR-12、AC-1~AC-12）、架构第 4、8~10、12~13、16~17 节

> 写本文前已核查现状代码、测试、迁移、凭据与 SSE 先例；修订时须在对应小节记录日期与原因。

## 现状核查与约束

| 核查面 | 2026-11-02 事实 | 本阶段约束 |
|---|---|---|
| Engine 路径 | `backend/src/agent_platform/core_platform/agent_runtime/worker.py` 直接运行 Runtime；`applications/platform_runtime/runtime_factory.py` 构造 ReAct Runtime。 | 以 Phase 1~2 实际 Orchestrator/Registry 为接线点，不新增 Worker 的 Codex 分支。 |
| Codex | `backend/`、`frontend/src`、`deploy/` 检索无 Codex CLI/App-Server/JSON-RPC/Session 实现。 | 所有 Codex 能力均为新增规划，禁止写成已有支持。 |
| RuntimeHost/Workspace | 当前无 `core_platform/agent_execution/`；逻辑 Workspace/工具目录不等于外部 Engine 沙箱。 | 依赖 Phase 4 实际 RuntimeHost、Process Supervisor 和 Workspace Provider，不重复造进程管理。 |
| 凭据 | `platform_services/secrets/vault.py` 提供安装密钥 Fernet 加解密；`model_gateway/catalog.py` 绑定租户/连接/地址/协议，尚无 Execution Broker。 | Phase 5 仅用受控引用与最小暴露；完整 Broker、短期授权和强沙箱归 Phase 6。 |
| 事件/SSE | `agent_runtime/repository.py` 同事务递增 `runtime_runs.event_seq` 并写 `runtime_events`；`customer_service/runtime_routes.py` 支持 `after` 与 `Last-Event-ID`，NOTIFY 仅作唤醒。 | 复用持久事件与 SSE 外层，不另建 Codex 专用事件通道；Outbox/去重/usage 幂等归 Phase 6。 |
| 终态/Lease | Repository 已校验 owner、lease 和终态，`test_runtime_postgres.py` 覆盖取消竞态、Worker 丢失与迟到结果。 | 保留先例；跨 Worker Epoch/Fencing 不在 Phase 5 冒充完成。 |
| 迁移 | 当前 head 为 `0052_memory_tasks_tenant_index`。 | `0055_agent_engine_sessions` 仅为规划预留号，Stage B 需要时才新增；实施前重核 head 和依赖，不修改历史迁移。 |

## 改动总览

| 层 | 文件 | 改动 | 溯源 |
|---|---|---|---|
| 新模块 | `backend/src/agent_platform/core_platform/agent_execution/adapters/codex/cli_exec.py` | Stage A Adapter；请求映射、启动、事件流、结果与取消，仅经 RuntimeHost。 | FR-1~FR-4 |
| 新模块 | `.../adapters/codex/app_server.py` | Stage B Protocol Adapter；复用公共 Codex 配置/事件模型，不复用 CLI stdio 状态机。 | FR-1、FR-7~FR-10 |
| 新模块 | `.../adapters/codex/jsonrpc.py` | Provider 私有 JSON-RPC 帧、ID 关联、版本协商、超时、背压与断连状态机。 | FR-7、FR-11 |
| 新模块 | `.../adapters/codex/events.py` | CLI/App-Server 原生事件规范化、稳定平台映射、有界 payload 与 usage 提取。 | FR-4、FR-11 |
| 新模块 | `.../adapters/codex/config.py` | 类型化配置、版本/能力交集校验；不信任客户端 Effective 能力。 | FR-1、FR-2、FR-12 |
| 新模块 | `.../agent_execution/session/{models,manager,repository}.py` | Stage B Session 映射、过期、Resume 重新鉴权；CLI 无此依赖。 | FR-8、FR-10 |
| 迁移 | `backend/migrations/versions/0055_agent_engine_sessions.py` | 规划号、条件性新增 `agent_engine_sessions`；实际 `down_revision` 由实施时 head 决定。 | FR-8 |
| 入口 | `backend/src/agent_platform/applications/platform_runtime/runtime_composition.py` | 按 Phase 1~4 实际组合根注册 Codex Protocol、Host、Workspace、Session 与策略依赖。 | FR-1、FR-12 |
| 配置 | `backend/src/agent_platform/core_platform/platform_services/platform_settings/settings.py` | 增加默认关闭、版本白名单、可信租户和 Session 开关；敏感值仅存部署 Secret 环境。 | FR-6、FR-12 |
| API | Phase 3 实际通用能力/审批路由（路径实施前重核） | 仅暴露通用能力与审批/输入契约；不得新增公共 Codex JSON-RPC 路由。 | FR-7、FR-9 |
| 部署 | `backend/.env.example`、`deploy/production/.env.example` 及实际 RuntimeHost 配置 | 仅增加无 Secret 的占位与开关示例；不写入真实 Token，不挂载宿主 Codex auth 目录。 | FR-6、FR-12 |
| 测试 | `backend/tests/test_codex_{contract,cli,app_server,session}.py`、协议 fixtures | 公共契约、真实受控二进制、故障注入、Workspace/凭据对抗与 React 回归。 | AC-1~AC-12 |

> 上表省略号表示同一 `backend/src/agent_platform/core_platform/agent_execution/` 根目录；所有路径均为规划落点，若 Phase 1~4 采用不同结构，先修订本文再实施。

## 数据模型

### 规划迁移 `0055_agent_engine_sessions.py`（仅 Stage B 需要时）

| 字段 | 规划类型/约束 | 用途 |
|---|---|---|
| `id` | UUID PK | 平台 Engine Session ID，Resume 的公共内部标识。 |
| `tenant_id` | TEXT NOT NULL + 索引 | 可信租户边界，所有查询强制带租户。 |
| `conversation_id` | UUID NOT NULL，引用 `runtime_conversations(id)` | 绑定业务 Conversation，禁止跨会话恢复。 |
| `engine_id` / `protocol_id` / `adapter_version` | TEXT NOT NULL | 固定 `codex/app_server` 及兼容 Adapter；CLI 不复用 App-Server Session。 |
| `provider_session_id` | TEXT NOT NULL | Codex 原生 Session 标识，不单独作为授权依据。 |
| `workspace_id` | 类型按 Phase 4 实际模型重核，NOT NULL | 绑定 Workspace，恢复时必须一致。 |
| `status` | TEXT CHECK：`active/suspended/expired/closed/failed` | 显式生命周期与过期清理。 |
| `metadata` / `metadata_schema_version` | JSONB NOT NULL / TEXT NOT NULL | Adapter 所有的有界版本化原生元数据，不存 Secret。 |
| `created_at` / `updated_at` / `last_used_at` | TIMESTAMPTZ | 审计与清理依据。 |
| `expires_at` | TIMESTAMPTZ NULL + 索引 | 过期后禁止 Resume 并释放关联资源。 |

设计要点：

- 规划唯一约束 `(tenant_id, protocol_id, adapter_version, provider_session_id)`，并为 `(tenant_id, conversation_id, status)` 建索引；最终字段、FK 与 Workspace 类型按实施时模型重核。
- 一个 Conversation 可有多个 Engine Session，一个 Session 可关联多个 Run；Run 通过 Phase 1~3 的执行元数据保存 `engine_session_id`，本阶段不新建 Task 表。
- `metadata` 不得保存凭据、完整宿主环境或无界原生日志；原生 ID 仅在 Provider 内部使用。
- Stage A 不创建也不依赖该迁移；Stage B 设计评审若证明无需持久 Session，可取消此规划迁移并记录裁定。
- 在线迁移采用新增表方式，不改历史表；downgrade 前若已有数据必须按仓库惯例要求显式导出，禁止静默丢失。

## 核心流程

### 1. Stage A：CLI 执行（`cli_exec.py` + Phase 4 RuntimeHost）

```text
Run 创建（默认关闭时拒绝 Codex）
→ Worker/Orchestrator 解析 (codex, cli_exec, adapter_version)
→ 校验可信租户、版本、类型化配置与 Effective 能力
→ Workspace Provider 创建 Execution Workdir 和授权挂载
→ 凭据引用按当前 Execution 最小化解析，不读取宿主 ~/.codex/auth.json
→ RuntimeHost 启动进程组并返回内部 Handle
→ CLI Adapter 有界读取 stdout/stderr，映射平台事件并保留原生事件
→ 收集最终 output/artifacts/usage（usage 缺失为 unknown）
→ Orchestrator 提交结果；Host 确认进程退出与资源清理
```

- Adapter 不直接 `subprocess`、不操作队列、不提交 Run 终态；命令参数由白名单构造，敏感参数不进入日志。
- stderr 既可能是诊断也可能含 Secret，不能无条件作为公开错误；原始输出有大小上限并脱敏。
- Stage A 的稳定门禁为 FR-1/AC-2 的强制前置：测试报告、预发布连续回归和混合场景证据齐全后，Stage B 才可合入/启用。

### 2. 取消与超时（RuntimeHost / Process Supervisor）

```text
取消或截止
→ 持久化 cancel_requested/timeout 意图
→ Host 请求 Codex 优雅停止
→ 宽限期内等待进程组与连接退出
→ 未退出则强制终止整个进程树
→ 清理挂载、临时目录、连接与资源
→ 依据真实退出和清理结果提交 cancelled/failed，禁止迟到成功覆盖
```

- 协程取消只是触发器，不是完成证据；无法确认清理时以明确失败和告警收尾。
- 本阶段保留现有 owner/lease/终态保护，不声称具备 Phase 6 的 Lease Epoch/Fencing。

### 3. Stage B：JSON-RPC 与 Turn（`app_server.py`、`jsonrpc.py`）

```text
Stage A 门禁 + app_server 开关 + 版本协商
→ 建立/复用受 Host 监管的连接
→ initialize 并固定本次协议能力
→ 以内部 request_id 关联 Run/Turn，发送类型化请求
→ notification 转事件；response/error 按 ID 路由
→ 审批/输入仅在 Effective 允许时经通用平台契约往返
→ turn 完成收集结果/usage；关闭、断连、超时均退出等待并清理
```

- JSON-RPC 消息 schema、方法名和错误仅存在 Provider 内；公共 API 不出现 `jsonrpc`、方法名或原生 request_id。
- 未知、重复、迟到响应不自动重放有副作用请求；重试分类与副作用治理在 Phase 6 完整落地。

### 4. Session Resume 重新鉴权（`session/manager.py`）

```text
平台 Session ID + 当前认证上下文
→ 按 tenant 查询 Session 并检查 active/expires_at
→ 重新校验 Conversation、Agent、Workspace、Protocol/Adapter、凭据范围与 Effective 策略
→ 校验原生 Session 仍可用，必要时 fail closed
→ Provider 执行 resume，记录审计/last_used_at
→ 新 Turn 仍创建独立 Run/Execution 尝试
```

- 不复用启动时授权缓存；信任撤销、凭据过期或 Workspace 改变均拒绝。
- Session 过期清理与 Workspace 资源解绑可重入；完整 Fencing 和跨 Worker 恢复由 Phase 6 保证。

## 配置

规划在 `platform_settings/settings.py` 增加 `codex_cli_enabled=false`、`codex_app_server_enabled=false`、`codex_allowed_versions=[]`、`codex_trusted_tenants=[]`、`codex_session_persistence_enabled=false`，并设置输出、连接、Session 和取消宽限期的有界参数。

- 敏感配置只保存 `credential_ref`，实际值由部署 Secret 环境/挂载维护，`.env.example` 仅放占位。
- `codex.timeout_seconds` 默认规划 1800 秒，但必须受部署硬上限约束；当前全局 `run_timeout_seconds` 上限及 Phase 3 配置合并规则须实施前重核。
- 所有 Agent 侧 `sandbox_mode`、`approval_mode` 与能力值只能收窄部署策略；Phase 6 前信任白名单为空即拒绝。

## 模型调用路径

Codex 是外部 Engine，模型选择、推理循环和工具执行由 Codex 原生完成，不假定经过 NexusDesk Model Gateway，也不在 ReAct `RuntimeFactory.bound_model()` 中增加分支。平台只注入经授权的 Engine 配置/凭据引用并收集 Codex 返回的 usage；usage 关联 Run 与 Protocol，缺失时为 unknown，重复聚合与计费幂等归 Phase 6。

## 测试方案

| 层 | 用例 |
|---|---|
| 单测 | 版本/配置、CLI 参数白名单、事件与 usage fixtures、JSON-RPC ID/断连状态机、Session 鉴权与过期、错误脱敏。 |
| 集成 | 受控真实 Codex CLI/App-Server、RuntimeHost 进程树、取消/超时/崩溃、Workspace 对抗、凭据与可信租户、Session Resume。 |
| 回归 | React/Run/API/SSE、历史配置、迁移与开关关闭 diff；Phase 0 未测基线不得记为通过。 |

详细用例、对抗/故障注入及出口准则见 `04-test-plan.md`。

## 上线与回滚

1. 前置确认 Phase 0~4 验收和 Phase 0 基线；固定 Codex 版本、测试账号、可信租户与审计保留策略。
2. 仅在 Stage B 需要时执行规划 `0055`；实施前重核迁移 head、在线锁行为与 downgrade 数据保护，绝不改历史迁移。
3. 先部署默认关闭代码，再对单个可信租户开启 CLI；通过 Stage A 门禁后才允许 App-Server 灰度，最后按需开启 Session。
4. 回滚顺序为关闭 Session → 关闭 App-Server → 停止新 CLI Run → 按 Host 策略清理活动进程；保留新增表与历史事件，无需 down migration。
5. 任一 Secret 泄露、跨租户访问、不可信租户误开放或孤儿进程失控均立即停止新执行并关闭开关；不得通过放宽沙箱/凭据策略恢复可用性。
