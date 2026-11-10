# NexusDesk Agent 执行平台 v2 · 分阶段规划文档

> 状态：Phase 0 自 2026-11-07 起实施中；Phase 1–6 需求分析文档待评审、尚未开始实施；Phase 7 自 2026-11-07 起因项目起步阶段暂缓执行，需求以最低优先级 P4 issue 保留
> 创建：2026-11-02
> 依据：`docs/architecture/agent-execution-platform-v2.md` 第 17、19、20、22 节

## 背景

当前 `RuntimeWorker` 直接调用由 `RuntimeFactory` 构造的固定 LangGraph ReAct Runtime，执行治理、引擎选择和具体推理实现之间缺少稳定的 Engine Adapter 边界。直接叠加 Codex 等外部引擎会把协议、进程和凭据分支扩散到 Worker 与 Runtime。

本目录是 Agent 执行平台 v2 的唯一规划总目录。各阶段均先完成 `01`–`05` 评审，再进入拆解、开发、测试和验收；规划文档不代表功能已经实现。

## 总体原则

1. **契约优先、渐进重构**：先稳定 Execution Contract 与 Registry，再迁移 React，最后接入外部 Engine。
2. **统一治理而非统一引擎内部**：保留各 Engine 的推理循环、工具模型和原生协议。
3. **兼容与可回退**：复用现有 Run、Worker 队列、Lease/Heartbeat、事件与 Agent 发布快照；新旧路径用开关受控切换。
4. **能力不等于授权**：Effective 能力必须由平台结合部署环境与租户策略计算，客户端输入不能提权。
5. **安全是上线门槛**：不可信多租户代码执行前必须完成隔离、凭据、网络和资源治理，不能以“后续优化”替代。
6. **每阶段独立验证**：所有 G/US/FR/AC、测试用例和验收步骤均可溯源；测试与验收结果另写报告，不在规划阶段预写结论。

## 阶段路线图

| 阶段 | 主题 | 核心价值 | 优先级 | 预估* | 目录 |
|---|---|---|---|---|---|
| Phase 0 | 基线与盘点 | 固化现状、兼容样本与回归安全网 | P0 | ~1–1.5 周 | [phase-0-baseline-inventory/](phase-0-baseline-inventory/) |
| Phase 1 | 执行契约与注册中心 | 建立 Engine/Protocol/Adapter 稳定边界 | P0 | ~1.5–2 周 | [phase-1-execution-contract-registries/](phase-1-execution-contract-registries/) |
| Phase 2 | React Provider 与执行编排器 | 解除 Worker 对具体 Runtime 的依赖 | P0 | ~2–3 周 | [phase-2-react-provider-orchestrator/](phase-2-react-provider-orchestrator/) |
| Phase 3 | 能力、配置与指令 | 多 Engine 类型化配置、能力治理与快照 | P0 | ~2 周 | [phase-3-capability-config-instructions/](phase-3-capability-config-instructions/) |
| Phase 4 | Runtime Host、进程监管与 Workspace | 外部 Engine 的受管进程和隔离工作目录 | P1 | ~3–4 周 | [phase-4-runtime-host-workspace/](phase-4-runtime-host-workspace/) |
| Phase 5 | Codex 集成 | 以 CLI、再以 App-Server 验证多协议架构 | P1 | ~8 周（A/B 串行） | [phase-5-codex-integration/](phase-5-codex-integration/) |
| Phase 6 | 安全、可靠性与事件治理 | 达到不可信多租户执行的生产门槛 | P1 | ~4–6 周 | [phase-6-security-reliability-events/](phase-6-security-reliability-events/) |
| Phase 7 | 高级 Engine 能力与规模化 | 按独立能力切片扩展生态、治理与成本 | P4（暂缓） | 重新排期后按切片评审 | [phase-7-advanced-engines-scale/](phase-7-advanced-engines-scale/) |

> **Phase 7 暂缓说明（2026-11-07）**：因项目处于起步阶段，本阶段全部需求暂不进入实施、测试或验收，统一以最低优先级 P4 issue 跟踪。FR-1～FR-11 对应 #110～#120，详见[暂缓与需求跟踪](phase-7-advanced-engines-scale/02-requirements.md#暂缓与需求跟踪)；明确重新激活前，相关规划不作为交付承诺。

\* 预估仅用于排期讨论，不是交付承诺；Phase 0 基线完成后应重新估算。

各阶段统一包含：

- `01-business-goals.md` / `.en.md`：问题、业务目标、成功指标、范围与风险；
- `02-requirements.md` / `.en.md`：US、FR、非功能需求与 AC；
- `03-technical-design.md` / `.en.md`：现状映射、文件级改动、数据与流程、上线回滚；
- `04-test-plan.md` / `.en.md`：UT/IT/CM、回归范围、缺陷分级与出口准则；
- `05-acceptance-plan.md` / `.en.md`：AC 逐条验收、业务指标、合规核对与签字；
- `06-test-report.md`、`07-acceptance-report.md`：仅在实际测试/验收后生成；
- `08-implementation-breakdown.md`：大型阶段设计评审后、开发启动前生成。

## 依赖与迁移约定

- 阶段顺序默认为 Phase 0 → 1 → 2 → 3 → 4 → 5A → 5B → 6 → 7；安全子项可提前评审，但不能削弱后续上线门槛。Phase 7 当前暂缓，不纳入现阶段实施顺序。
- 2026-11-02 规划核查时的迁移头为 `0052_memory_tasks_tenant_index`；2026-11-07 Phase 0 实施核查时已前进到 `0057_industry_pack_runtime`。文档中的 `0053+` 均为**规划编号**，各阶段实施时必须基于目标提交重新核查 head、调整 `down_revision`，禁止修改已应用的历史迁移，也不得把历史规划编号当作永久验收值。
- Phase 0 产出的依赖图、生命周期与兼容基线继续放在本总目录对应阶段下，避免形成第二套文档源。
- 任一阶段发现设计与代码现实不一致，先登记裁定并修订相关文档，再修改实现。

## 明确不做的（整体边界）

- **首次迁移不拆微服务**：先建立模块化单体边界。
- **不重写现有调度器**：保留持久化 Worker 队列、Lease/Heartbeat 与现有终态职责。
- **不立即引入 Task/Execution 双表**：首次迁移定义 Run 为一次 Execution 尝试。
- **不强制所有 Engine 支持 Session/审批/交互**：这些是可声明、可解析的可选能力。
- **不抹平原生事件**：统一事件信封，不强制转换为 ReAct Tool Calling。
- **不在无量测依据时改共享存储**：先评估容量、延迟、隔离和成本。
- **不允许不可信任务直接获得宿主权限**：隔离、凭据和网络策略是硬门槛。

## Review 指引

- Phase 0：现状与测试基线是否可复现；历史配置样本是否覆盖真实发布快照；标识是否冻结。
- Phase 1：契约是否足够稳定且不过度泄漏宿主细节；Adapter 版本、取消和错误语义是否明确。
- Phase 2：新旧 React 路径行为是否等价；Worker 是否只依赖 Orchestrator；回滚是否无需数据回退。
- Phase 3：旧配置默认映射是否无损；Effective 能力是否无法被客户端提权；快照能否完整重放决策依据。
- Phase 4：进程树清理、路径/软链隔离和资源限额是否经故障与对抗测试。
- Phase 5：CLI 稳定后再启用 App-Server；原生协议是否封装在 Provider 内；不可信执行是否仍受安全门槛约束。
- Phase 6：Fencing、Outbox、去重和 SSE 重放是否覆盖竞态；Secret 是否跨日志、事件、产物全链路脱敏。
- Phase 7（当前暂缓，重新激活后适用）：是否按小切片交付；路由与回退是否重新执行策略；无高级能力的 Engine 是否仍可基本执行。
