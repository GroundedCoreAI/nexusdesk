# Phase 5 · Codex 集成 — 业务目标

> 状态：待评审（仅规划，未实施；当前代码无 Codex 支持）
> 创建：2026-11-02
> 依据：`docs/architecture/agent-execution-platform-v2.md` 第 3.2、4、5、7~10、12~13、17（Phase 5）、19~22 节；现状核查见 `03-technical-design.md`

> 阶段：Phase 5（Stage A：CLI Exec；Stage B：App-Server，严格串行解锁）
> 预估工期：Stage A 约 4 周；Stage B 约 4 周，评审后确认
> 依赖：Phase 0~4 已验收；受支持的 Codex 版本与测试授权已确认；Phase 6 未完成前仅限显式可信租户

## 要解决的问题

### 问题 1：当前没有外部 Codex 执行路径

现状 `RuntimeFactory` 与 `RuntimeWorker` 仍围绕 LangGraph ReAct Runtime，仓库代码和测试中没有 Codex CLI、App-Server、JSON-RPC 或 Codex Session 实现。直接增加引擎分支会形成第二条执行路径，绕过统一契约、Worker 和事件治理。

### 问题 2：外部进程不能以协程生命周期代替真实进程治理

当前 Worker 的取消以取消 asyncio Task 为主；Codex CLI 与 App-Server 还涉及进程树、stdio、连接、超时和孤儿资源。必须经由 Phase 4 RuntimeHost 启停和清理，不能把宿主 PID、参数或私有协议暴露给公共 API。

### 问题 3：协议、Session 与原生语义容易被错误统一

CLI Exec 与 App-Server 是同一 `codex` Engine 的不同 Protocol。若复用 Engine 身份时混淆 Protocol，或把 Codex 事件强行改写为 ReAct Tool Calling，会破坏事件保真、Session/Run 映射和后续协议扩展。

### 问题 4：凭据与 Workspace 是上线硬门槛

当前模型网关 Vault 不等于 Execution 级 Credential Broker；当前逻辑 Workspace 也不等于强沙箱。Phase 5 不得复制宿主 `~/.codex/auth.json`、跨租户共享凭据目录，或在 Phase 6 的完整 Broker/强沙箱落地前向不可信租户开放代码执行。

## 业务目标

| 目标 | 说明 |
|---|---|
| G1：打通受治理的 Codex CLI | 通过公共执行契约和 RuntimeHost 完成 Stage A 的请求、事件、结果、用量、取消与超时闭环。 |
| G2：验证 Engine/Protocol 解耦 | `codex/cli_exec` 与 `codex/app_server` 共享 Engine 身份、独立注册和版本兼容，不污染 Worker 与公共 API。 |
| G3：保留 Codex 原生价值 | 保留有界的原生事件与元数据，同时映射稳定平台事件，收集最终结果和用量，不伪装成 ReAct 推理。 |
| G4：落实执行安全边界 | 使用隔离 Execution Workdir、受控凭据引用和 Effective 能力策略；不可信租户在 Phase 6 前保持关闭。 |
| G5：受控交付 App-Server 与 Session | 仅在 Stage A 稳定门禁通过后实现 JSON-RPC、流式交互、原生 Session 及重新鉴权的 Resume。 |
| G6：保护存量行为与可回退性 | React、既有 Run/API/SSE 与历史配置无回归；CLI、App-Server 可分别灰度和关闭。 |

## 成功指标

| 指标 | 基线（现状） | 目标 |
|---|---|---|
| 已接入 Codex Protocol 数 | 0；代码检索无 Codex Adapter | Stage A 为 1；Stage B 验收后为 2，且共享 `engine_id=codex`。 |
| Codex 契约与端到端场景通过率 | 未测，待 Phase 0 建立外部 Engine 基线 | 本阶段适用 UT/IT/CM 与 AC 通过率 100%，无 P0/P1。 |
| Stage A 稳定性门禁 | 未测，待 Phase 0 | 连续 3 次预发布全量适用回归通过，且一次至少 20 个混合成功/失败/取消场景无 P0/P1 后才允许 Stage B。 |
| 原生事件与用量关联完整率 | 未测，待 Phase 0 | 支持的原生事件、最终结果和可用 usage 均关联同一 Run/Execution；缺失 usage 显式标记而非填零。 |
| 取消/超时实际清理达成率 | 未测，待 Phase 0 | 适用场景中 100% 在配置宽限期内终止进程树并释放 Workdir/连接资源；失败不得伪报成功。 |
| 凭据与跨租户泄露 | 未测，待 Phase 0 安全基线 | 对抗用例中明文 Secret、宿主 auth 文件和跨租户文件泄露均为 0；不可信租户开放数为 0。 |
| React 回归差异 | 未测，待 Phase 0 | 开关关闭时与 Phase 0 行为 diff 为 0，既有回归套件全绿。 |
| 执行开销与启动时延 | 未测，待 Phase 0 | 先记录 CLI/App-Server p50/p95；不得在基线缺失时宣称性能提升，预算在 Phase 0 后评审冻结。 |

## 范围

**包含**：

- Stage A：受支持版本探测与固定兼容矩阵、类型化 Codex 配置、CLI Adapter、RuntimeHost 启动、stdout/stderr 解析、原生事件、结果/usage、取消/超时、Workspace 与受控凭据策略。
- Stage A 稳定门禁、契约测试、故障注入、可信租户灰度与独立开关。
- Stage B：App-Server JSON-RPC 封装、连接生命周期、Session/Turn/Run 映射、流式事件、能力受控的审批/交互输入、Session Resume 重新鉴权。
- Stage B 确需持久 Session 时的 `agent_engine_sessions` 规划迁移与 Repository。
- React 回归、审计、指标、双语实施规划及上线/回滚方案。

**不包含**（属于后续阶段 / 明确不做）：

- 完整 Credential Broker、短期凭据全生命周期、强沙箱、网络出口与跨日志/事件/产物脱敏体系：属于 Phase 6，是开放不可信租户前的阻断项。
- Fencing Token、事务性 Event Outbox、事件去重/通用重放治理与 usage 幂等聚合：属于 Phase 6；Phase 5 只保证采集和关联。
- Claude Code、ACP、OpenClaw、多 Engine 路由/回退及规模化调度：属于 Phase 7 或后续；[Phase 7](../phase-7-advanced-engines-scale/02-requirements.md#暂缓与需求跟踪) 自 2026-11-07 起因项目起步阶段暂缓执行，相关需求仅以最低优先级 P4 issue 跟踪。
- 自研 Codex 推理循环、把 Codex 原生协议暴露为 NexusDesk 公共 API、无版本约束地支持所有 Codex 发布版。
- 本阶段不修改历史迁移，不承诺当前不存在的 Codex 功能已经可用。

## 风险与约束

- **Codex 版本漂移**：stdout/JSON-RPC/usage 字段变化会破坏解析；固定已验证版本、启动时兼容性检查、契约样本测试，未知版本 fail closed。
- **Stage B 提前膨胀**：并行实现会掩盖 CLI 基础问题；Stage A 未满足稳定门禁时 App-Server 开关和实现合入均不得解锁。
- **取消不等于退出**：协程取消可能留下子进程；以 RuntimeHost 的进程组退出与资源释放证据为准。
- **Session 越权恢复**：原生 Session ID 不是授权；Resume 必须重新校验租户、Agent、Workspace、凭据范围、Protocol/Adapter 与 Effective 策略。
- **凭据安全硬门槛**：Phase 6 未完成完整 Broker 与强沙箱前，只允许部署方显式登记的可信租户；默认拒绝，不向不可信多租户代码执行开放。
- **兼容性**：缺省继续使用 React；新增字段和事件保持向后兼容，Codex 开关默认关闭，回滚不依赖删除新增表或改写历史 Run。
