# NexusDesk Agent 执行平台 v2 · 分阶段规划文档

> 状态：Phase 0 与 Phase 1 的正式验收仍未完成；Phase 2 代码已随 merge `3969258` 合入 integration，07 结论为**有条件通过**，生产性能、CI/真实部署、人类 UAT/签字与持久证据仍有未决项；Phase 3 已于 2026-11-12 按已合入代码校准 01～05 并新增 08，T1～T9 已按 08 在特性分支 `feat/agent-execution-platform-v2-phase3` 实施完成并通过合并测试线取证（任务级双评审+验收：T5 与 T9 为**有条件通过**，T9 的条件①待真实栈复跑、已并入 #128；T6/T7/T8 无阻断项）；已有 4 个本地提交（`4318042` backend、`d662a4b` frontend、`90f1630` docs、`e647788` chore），**未 push、未合入 main/integration**，且 T6 的指令层与其加固轮、T7 的执行集成、T8 的 preview API 与本轮文档第三批仍在工作树未提交；T10、T11 进行中，故阶段测试/验收报告 06/07 尚未创建；**T12、T13 已移出本阶段，转独立迭代跟进（issue #127 seed、#128 fresh quickstart，见 08 R-39）**；Phase 4–6 未开始；Phase 7 暂缓
> 创建：2026-11-02
> 修订：2026-11-13（Phase 3 状态行更新：T1～T9 实施完成、合并测试线通过，T6/T7/T8 无阻断项且实现与文档第三批未提交，T10/T11 进行中故 06/07 尚未创建，T9 条件①并入 #128；08 §2 追加裁定 R-42～R-52，03/04/05 双语同步本批内容）
> 修订：2026-11-13（Phase 3 状态行更新：T1～T6 与 T9 已实施、T5/T9 有条件通过、T6 已通过测试取证与加固轮收口、4 个本地提交未 push 未合入、T7/T8 与 T10/T11 未开始故 06/07 不存在；T12/T13 移出本阶段转 issue #127/#128（08 R-39））
> 修订：2026-11-13（Phase 3 T1～T4 工作树实施状态，任务级评审/验收结论；阶段级 06/07 仍未创建）
> 修订：2026-11-12（同步 Phase 2 实际状态，冻结 Phase 3 设计与实施拆解）
> 依据：`docs/architecture/agent-execution-platform-v2.md` 第 17、19、20、22 节；各阶段 06/07 实际报告

## 背景

当前代码同时保留 legacy Runtime 与默认关闭的 Orchestrator 路径。Phase 1 的精确 Registry/Adapter 契约、Phase 2 的 `ExecutionOrchestrator`、`ExecutionContext`、`ReactAdapter` 与组合根已存在，但 AgentConfig 尚无 Engine 类型化配置、能力策略解析、决策快照和 Instruction Provider。直接叠加外部 Engine 仍会把配置、授权与指令格式分支扩散到 Worker 和 Runtime。

本目录是 Agent 执行平台 v2 的唯一规划总目录。代码合入、开发入口、自动化辅助验收与最终上线门禁是不同事实；规划文档不代表功能已经实现，任何阶段的有条件通过也不等于上游全部正式验收完成。

## 总体原则

1. **契约优先、渐进重构**：扩展已存在的 Execution Contract、Registry、Orchestrator 和 ReactAdapter，不新建平行执行栈。
2. **统一治理而非统一引擎内部**：保留各 Engine 的推理循环、工具模型和原生协议。
3. **兼容与可回退**：复用 Run、Worker 队列、Lease/Heartbeat、事件与 Agent 发布快照；新旧路径由明确开关矩阵控制。
4. **能力不等于授权**：Effective 由服务端结合 Declared、部署 Available 与可信 Policy 单调收窄，客户端输入不能提权。
5. **安全与证据是上线门槛**：不可信多租户代码执行前必须完成隔离、凭据、网络和资源治理；`pending_env`、skip、未测量不能改写为通过。
6. **小团队轻量验收**：复用自动化证据，只保留验收负责人和执行人（可同人）、少量人工检查与单一验收记录，不虚构独立角色。
7. **每阶段独立验证**：G/US/FR/AC、测试用例和验收步骤均可溯源；06/07 仅在实际测试/验收后创建。

## 阶段路线图

| 阶段 | 主题 | 核心价值 | 优先级 | 预估* | 目录 |
|---|---|---|---|---|---|
| Phase 0 | 基线与盘点 | 固化现状、兼容样本与回归安全网 | P0 | ~1–1.5 周 | [phase-0-baseline-inventory/](phase-0-baseline-inventory/) |
| Phase 1 | 执行契约与注册中心 | 建立 Engine/Protocol/Adapter 稳定边界 | P0 | ~1.5–2 周 | [phase-1-execution-contract-registries/](phase-1-execution-contract-registries/) |
| Phase 2 | React Provider 与执行编排器 | 解除 Worker 对具体 Runtime 的依赖 | P0 | ~2–3 周 | [phase-2-react-provider-orchestrator/](phase-2-react-provider-orchestrator/) |
| Phase 3 | 能力、配置与指令 | 多 Engine 类型化配置、能力治理与快照 | P0 | ~2 周，实施前重估 | [phase-3-capability-config-instructions/](phase-3-capability-config-instructions/) |
| Phase 4 | Runtime Host、进程监管与 Workspace | 外部 Engine 的受管进程和隔离工作目录 | P1 | ~3–4 周 | [phase-4-runtime-host-workspace/](phase-4-runtime-host-workspace/) |
| Phase 5 | Codex 集成 | 以 CLI、再以 App-Server 验证多协议架构 | P1 | ~8 周（A/B 串行） | [phase-5-codex-integration/](phase-5-codex-integration/) |
| Phase 6 | 安全、可靠性与事件治理 | 达到不可信多租户执行的生产门槛 | P1 | ~4–6 周 | [phase-6-security-reliability-events/](phase-6-security-reliability-events/) |
| Phase 7 | 高级 Engine 能力与规模化 | 按独立能力切片扩展生态、治理与成本 | P4（暂缓） | 重新排期后按切片评审 | [phase-7-advanced-engines-scale/](phase-7-advanced-engines-scale/) |

> **Phase 7 暂缓说明（2026-11-07）**：本阶段不进入实施、测试或验收；FR-1～FR-11 以最低优先级 P4 issue #110～#120 跟踪，明确重新激活前不作为交付承诺。

\* 预估仅用于排期讨论，不是交付承诺；须按实际基线和未决门禁重估。

各阶段统一包含双语 `01`～`05`；大型阶段另含双语 `08`。`06-test-report.md` / `07-acceptance-report.md` 只在实际测试/验收后生成；quickstart 等验收后验证只能向既有报告追加附录，不能预写结果。

## 依赖、开发入口与迁移约定

- 默认阶段顺序为 Phase 0 → 1 → 2 → 3 → 4 → 5A → 5B → 6 → 7；Phase 7 当前暂缓。
- **Phase 3 开发入口**：基线 `3969258` 已提供所需 Phase 1/2 代码，focused baseline 为 163 passed / 5 skipped；该入口允许按 08 开发，不代表全量 CI、上游正式验收或生产发布已批准。
- **Phase 3 最终上线门禁**：除本阶段 A/C 外，上游真实历史样本、CI/真实部署、性能及人工验收缺口必须按其报告继续跟踪；影响本阶段结论的缺口未关闭前保持 `pending_env` / 未通过，不能用“代码已合入”或删除门禁替代。
- 2026-11-12 实测迁移 head 为 `0057_industry_pack_runtime`，`0053_routing_decisions` 已占用旧规划号。Phase 3 规划新迁移为 `0058_agent_execution_metadata`，`down_revision="0057_industry_pack_runtime"`；T2 实施前必须动态重验，若目标提交变化则同步修订文档，禁止修改已应用历史迁移。
- 任一阶段发现设计与代码现实不一致，先登记 R-n 裁定并修订相关双语文件，再修改实现。

## Phase 2 当前交付与 Phase 3 接续点

Phase 2 的 ReactAdapter 在 `start` 创建受 gate 保护的 runner，RuntimeFactory 随后在 runner 内装配模型、工具与有效系统提示；Orchestrator 保持 worker_emit/runtime_emit 双 emit、结构化 ack、Memory Outcome 和公开 Run/SSE 语义。Phase 2 07 及后续附录记录了有条件通过和 quickstart 补证，不能写成完全正式验收。

Phase 3 必须扩展这些组件而不是复制执行链。`Repository.claim` 仍先公开 `run.started`；Phase 3 的“启动屏障”专指 `Adapter.start` 及 Runtime/工具/模型副作用之前，不改变公开事件顺序。总开关关闭时严格保留部署原 Phase 2 on/off 路径；任何 off 状态下的非 React 均明确 `execution_phase3_disabled`，绝不静默改用 React。

## 明确不做的（整体边界）

- **首次迁移不拆微服务**：保持模块化单体。
- **不重写调度器**：保留持久化 Worker 队列、Lease/Heartbeat 与既有终态职责。
- **不引入 Task/Execution 双表**：Run 仍表示一次 Execution 尝试。
- **不强制所有 Engine 支持 Session/审批/交互**：这些是可声明、可解析的可选能力。
- **不抹平原生事件**：统一事件信封，不强制转换为 ReAct Tool Calling。
- **不在无量测依据时改共享存储**：先评估容量、延迟、隔离和成本。
- **不允许不可信任务直接获得宿主权限**：隔离、凭据和网络策略是硬门槛。
- **不引入 Postman 发布、外部预览服务或新前端测试框架**：沿用 OpenAPI、Playwright 和现有部署形态。

## Review 指引

- Phase 0/1：正式验收缺口仍按各自 07 跟踪，不能由后续合入追认完成。
- Phase 2：关注有条件通过边界、性能/真实部署缺口及附录证据，不重写历史结论。
- Phase 3：重点审查旧根别名与 canonical diff、无 Adapter 实例的草稿校验、最小权限与缓存失效、五快照启动屏障、Provider 单次渲染、双开关矩阵、预览租户隔离及 C11 的 100 个真实样本。
- Phase 4/5/6：分别审查进程与 Workspace 隔离、原生协议封装、安全与事件治理；不得向 Phase 3 偷渡范围。
- Phase 7：重新激活后按小切片独立评审。
