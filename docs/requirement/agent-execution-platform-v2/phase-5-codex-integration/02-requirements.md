# Phase 5 · Codex 集成 — 需求文档

> 状态：待评审（仅规划，未实施）
> 创建：2026-11-02
> 依据：`01-business-goals.md`（G1~G6）；`docs/architecture/agent-execution-platform-v2.md` 第 4、5、8~10、12~13、17（Phase 5）节

## 用户故事

**US-1（平台管理员）**：作为平台管理员，我希望按已验证版本和独立开关启用 Codex CLI/App-Server，以便灰度接入外部 Engine 并可快速回退。

**US-2（可信租户用户）**：作为可信租户用户，我希望 Codex 在授权 Workspace 中完成任务并返回流式进度与最终结果，以便使用其原生编码能力而不改变既有 Run 使用方式。

**US-3（平台研发）**：作为平台研发，我希望两种 Protocol 实现同一 Adapter 契约且共享 Codex Engine 身份，以便无需修改 Worker 即可扩展协议。

**US-4（运维人员）**：作为运维人员，我希望取消、超时、崩溃和断连都能清理真实进程与连接，以便避免孤儿进程、资源泄漏和错误终态。

**US-5（安全负责人）**：作为安全负责人，我希望凭据只按 Execution 和策略受控暴露，且不可信租户默认被拒绝，以便在 Phase 6 完整安全能力落地前不扩大攻击面。

**US-6（会话用户与审计员）**：作为会话用户与审计员，我希望 App-Server Session 可以安全恢复且全程可追溯，以便延续上下文，同时防止跨租户或过期授权被复用。

## 功能需求

### FR-1 分阶段注册与稳定门禁

| 项 | 说明 |
|---|---|
| 触发时机 | 部署注册 Adapter、解析 Agent Engine 配置或申请开启 Stage B 时。 |
| 输入 | `engine_id`、`protocol_id`、`adapter_version`、Codex 版本、Stage A 门禁证据、部署开关。 |
| 输出 | `codex/cli_exec` 与 `codex/app_server` 独立可用性；共享 Engine 身份；拒绝未解锁或不兼容组合。 |
| 执行方式 | 启动时同步注册与校验，执行时异步解析；不阻塞 React 注册。 |
| 失败处理 | 未验证版本、未知 Protocol、Stage A 门禁未满足均 fail closed；记录无 Secret 的原因码与审计。 |

### FR-2 CLI 请求映射与版本兼容

| 项 | 说明 |
|---|---|
| 触发时机 | Stage A Worker 通过编排器启动 Codex Run。 |
| 输入 | 经校验的 ExecutionRequest、Codex 类型化配置、指令/上下文、Workspace 和 Effective 能力快照。 |
| 输出 | 仅含允许参数的 CLI 调用规范和内部 ExecutionHandle；公共响应不包含宿主细节。 |
| 执行方式 | 异步启动，非阻塞 API；实际进程由 RuntimeHost 管理。 |
| 失败处理 | 缺二进制、版本不兼容、参数/配置无效分别映射稳定错误码；不自动改用未验证版本。 |

### FR-3 RuntimeHost 启动、取消与超时

| 项 | 说明 |
|---|---|
| 触发时机 | CLI 进程或 App-Server 子进程/连接启动、用户取消、达到截止时间或 Worker 停止时。 |
| 输入 | 内部句柄、进程组、取消请求、超时与终止宽限期。 |
| 输出 | Running/Terminating/Exited 状态、实际退出证据、稳定 Run 终态及清理结果。 |
| 执行方式 | 异步监管；先请求优雅终止，再按策略强制终止整个进程树。 |
| 失败处理 | 无法确认退出时报告清理失败并告警，不伪报 completed/cancelled；保留有界诊断，不泄露 PID 给客户端。 |

### FR-4 原生事件、最终结果与用量

| 项 | 说明 |
|---|---|
| 触发时机 | 收到 CLI 输出或 App-Server 通知，及执行结束时。 |
| 输入 | stdout/stderr、JSON-RPC notification/response、原生完成与 usage 数据。 |
| 输出 | 带公共外层的平台事件、`source=engine_native` 的有界原生事件、ExecutionResult 与可用 usage。 |
| 执行方式 | 流式异步映射；稳定语义与原生语义并行保留，不转换为 ReAct 内部推理。 |
| 失败处理 | 未知事件可有界保留并标记； malformed 输出产生 ProtocolError 和脱敏诊断；缺失 usage 为 unknown，不填零。 |

### FR-5 Workspace 与文件策略

| 项 | 说明 |
|---|---|
| 触发时机 | 准备 Execution、挂载 Workspace/Skill、收集产物和清理时。 |
| 输入 | 可信租户上下文、Workspace ID、Execution ID、只读/读写挂载与保留策略。 |
| 输出 | 单次 Execution Workdir、授权挂载、受控产物和清理记录。 |
| 执行方式 | 由 Phase 4 Workspace Provider 异步准备；Adapter 不自行选择宿主路径。 |
| 失败处理 | 路径穿越、符号链接逃逸、跨租户访问、未授权写入均拒绝；准备失败不得启动 Codex。 |

### FR-6 凭据策略与可信租户硬门槛

| 项 | 说明 |
|---|---|
| 触发时机 | 解析 Codex 配置、启动进程、恢复 Session 或租户信任属性变化时。 |
| 输入 | 服务端凭据引用、租户/Agent/Execution/Engine 授权、信任登记和策略快照。 |
| 输出 | 仅当前 Execution 可用的受控环境变量或 Secret 挂载、无明文的审计记录。 |
| 执行方式 | 启动前同步授权、按需注入；不继承宿主 Codex 登录目录。 |
| 失败处理 | 无引用、授权不符、信任不足或无法隔离时拒绝启动；禁止复制 `~/.codex/auth.json`，Secret 不进入日志/事件。 |

### FR-7 App-Server JSON-RPC 封装与连接生命周期

| 项 | 说明 |
|---|---|
| 触发时机 | Stage B 已解锁且执行选择 `app_server` 时。 |
| 输入 | 协商后的协议版本、初始化参数、请求 ID、notification、响应与连接状态。 |
| 输出 | Provider 内部类型化调用、响应路由、重连/关闭结果及平台契约事件。 |
| 执行方式 | 异步全双工通信；请求 ID 与 Run/Turn 关联，超时和背压有界。 |
| 失败处理 | 版本协商失败、未知/重复/迟到响应、断连均按协议错误处理；私有 JSON-RPC 不暴露为公共 API。 |

### FR-8 原生 Session 持久化与 Session/Turn/Run 映射

| 项 | 说明 |
|---|---|
| 触发时机 | App-Server 创建、使用、完成、过期或关闭原生 Session 时。 |
| 输入 | Conversation、Run、Engine Session、provider_session_id、Protocol/Adapter、Workspace 和元数据版本。 |
| 输出 | 平台 Session 记录及一个 Session 对多个 Run、一个 Turn 对一次执行尝试的可追踪关联。 |
| 执行方式 | 异步事务持久化；仅在实际需要持久 Session 时启用规划迁移。 |
| 失败处理 | 映射冲突、元数据版本不兼容或持久化失败则停止 Resume；不影响无 Session 的 CLI 路径。 |

### FR-9 流式处理、审批与交互输入

| 项 | 说明 |
|---|---|
| 触发时机 | App-Server 发出流式通知、审批请求或交互输入请求时。 |
| 输入 | Effective 能力、原生请求、审批/输入响应及请求关联 ID。 |
| 输出 | 通用平台事件与经授权的内部响应；公共客户端仅使用 NexusDesk 通用契约。 |
| 执行方式 | 异步流式；等待输入时有超时、取消和背压边界。 |
| 失败处理 | Declared 但非 Effective 的能力必须拒绝；未知请求不自动批准；断连不得留下永久等待。 |

### FR-10 Session Resume 重新鉴权

| 项 | 说明 |
|---|---|
| 触发时机 | 用户或系统请求恢复已持久化的 App-Server Session。 |
| 输入 | 平台 Session ID、当前可信身份、Agent/Conversation/Workspace、当前策略与凭据范围。 |
| 输出 | 重新授权后的 Resume 或明确拒绝；更新审计和最近使用时间。 |
| 执行方式 | 每次 Resume 同步重新鉴权后异步执行，不缓存旧授权结论。 |
| 失败处理 | 跨租户、跨 Conversation/Workspace、过期/吊销、Protocol 或 Adapter 不兼容均拒绝并审计；不得仅凭原生 ID 恢复。 |

### FR-11 错误分类、审计与可观测性

| 项 | 说明 |
|---|---|
| 触发时机 | 启动、解析、执行、取消、恢复和清理的任一失败或关键状态变化。 |
| 输入 | 稳定错误分类、Run/Session/Protocol 关联、版本、耗时、退出与 usage 元数据。 |
| 输出 | 公共错误码、内部脱敏诊断、指标、结构化日志和审计事件。 |
| 执行方式 | 异步记录不阻塞事件主流程；关键安全拒绝必须可靠审计。 |
| 失败处理 | Provider 原始异常不直接返回；诊断有大小/频率上限，完整 parser 诊断与用量幂等治理由 Phase 6 深化。 |

### FR-12 配置开关与兼容发布

| 配置项 | 层级 | 默认值 | 说明 |
|---|---|---|---|
| `codex_cli_enabled` | 全局 settings | `false` | Stage A 总开关；仅允许已验证版本和可信租户。 |
| `codex_app_server_enabled` | 全局 settings | `false` | Stage B 总开关；配置和运行时均检查 Stage A 门禁。 |
| `codex_allowed_versions` | 全局 settings | `[]` | 已验证版本白名单；空列表拒绝 Codex 启动。 |
| `codex_trusted_tenants` | 部署策略 | `[]` | Phase 6 前显式可信租户白名单；不得由客户端设置。 |
| `codex_session_persistence_enabled` | 全局 settings | `false` | 仅在 Stage B 且 Session 迁移就绪后开启。 |
| `codex.timeout_seconds` | AgentConfig | `1800`，受部署上限约束 | 类型化执行截止时间；不得突破平台上限。 |
| `codex.sandbox_mode` / `approval_mode` | AgentConfig | 部署最严格允许值 | 只能收窄，不能放大 Effective 能力。 |

## 非功能需求

- **性能**：事件解析与转发有界且不阻塞 Worker；记录启动、事件与取消 p50/p95，未测基线待 Phase 0，预算在基线评审后冻结。
- **兼容**：默认 Engine 保持 React；既有 Run、事件类型、SSE 游标和历史 Agent 配置不变，Protocol 私有字段不进入公共模型。
- **多租户**：租户身份来自可信认证上下文；Session、Workspace、凭据引用和缓存均带租户绑定，跨租户默认拒绝。
- **安全**：Phase 6 完整 Broker/强沙箱前只开放显式可信租户；Secret、宿主 auth 文件、命令行敏感参数不得进入日志、事件或公共响应。
- **可靠性**：进程退出、连接关闭和 Run 终态可关联；重复/迟到协议消息不得导致重复审批或错误完成，通用事件去重/Fencing 在 Phase 6 完成。
- **可运维性**：CLI 与 App-Server 独立健康状态、版本、错误率、事件滞后和清理指标可观测；开关可即时整体关闭。

## 验收标准

| # | 场景 | 预期 | 溯源 |
|---|---|---|---|
| AC-1 | 可信租户以固定受支持版本发起一次 CLI 编码任务。 | 经公共编排路径完成；RuntimeHost 句柄内部可见，最终输出与 Run 关联，公共 API 无宿主细节。 | FR-2；G1 |
| AC-2 | 分别解析两种 Protocol，并在 Stage A 门禁未满足时尝试开启 App-Server。 | 两者均为 `engine_id=codex`、独立 Protocol；未满足门禁时 Stage B 被拒绝，满足后才可启用。 | FR-1；G2、G5 |
| AC-3 | CLI/App-Server 产生消息、命令、文件变更与 usage（若支持）。 | 平台事件与有界原生事件均保留并关联 Run；usage 原样归一收集，缺失时显式 unknown。 | FR-4；G3 |
| AC-4 | 对长运行 CLI 与 App-Server 分别取消、超时并注入子进程。 | 在宽限期内终止进程树/连接并释放资源，终态正确；不能确认清理时明确失败并告警。 | FR-3；G1、G6 |
| AC-5 | 提交合法 Workspace，并尝试路径穿越、符号链接逃逸和跨租户读写。 | 合法任务仅访问授权目录；所有逃逸均被拒绝且未启动或已安全终止，审计无 Secret。 | FR-5；G4 |
| AC-6 | 使用受控凭据引用启动，随后尝试宿主 auth 文件复制、Secret 输出和不可信租户启动。 | 仅授权 Execution 获得受控凭据；宿主文件不复制，明文不泄露，不可信租户默认拒绝。 | FR-6；G4 |
| AC-7 | Stage B 完成 JSON-RPC 初始化、并发请求、断连和未知/迟到响应。 | 请求关联正确、断连有终态、私有协议不进入公共 API，异常有界且可诊断。 | FR-7；G2 |
| AC-8 | 同一 Conversation 经 App-Server 创建 Session 并执行多个 Turn/Run，随后过期。 | Session/Turn/Run 映射准确，元数据带版本，过期资源释放；CLI 不依赖 Session 表。 | FR-8；G5 |
| AC-9 | 请求流式输出、审批与交互输入，并分别测试 Effective 允许和拒绝。 | 允许时按通用契约工作；拒绝时不执行操作、不自动批准，等待可超时/取消。 | FR-9；G3、G4 |
| AC-10 | 合法恢复 Session 后，再以错误租户、Workspace、过期凭据或不兼容 Adapter 恢复。 | 合法恢复重新鉴权成功；其余全部拒绝并审计，旧授权结论不被复用。 | FR-10；G4、G5 |
| AC-11 | 注入不支持版本、malformed CLI 输出、非法 JSON-RPC 和缺失 usage。 | 返回稳定错误/unknown，不泄露 Provider 原始异常或 Secret；日志指标可按 Run/Protocol 定位。 | FR-11；G1、G3 |
| AC-12 | 关闭两个 Codex 开关并运行既有 React、Run/API/SSE 与历史配置回归。 | Codex 不可启动；与 Phase 0 基线 diff 为零，既有适用测试全绿；回滚无需删表。 | FR-12；G6 |
