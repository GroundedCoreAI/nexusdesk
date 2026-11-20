# NexusDesk Agent 执行平台 v2 · 分阶段规划文档

> 状态：Phase 0/1 正式验收仍未完成，后续各阶段报告保留各自边界。Phase 5 Stage A（`codex/cli_exec/v1`）已于 2026-11-20 完成**范围限定**端到端验收（PASS scope-limited），由单一验收负责人 JackChow 签署，权威记录 `13-scope-limited-acceptance-record-20261120-phase7-stage-a.md`；Stage A 在 quickstart 单租户演示范围的解锁记录见 `phase-5-codex-integration/07-acceptance-report.md` 末章。容器内需 `bwrap` 沙箱的工具调用受 Docker 默认 seccomp 阻断，登记为部署加固边界；Stage B 仍锁定，P5-IT-18 与 Stage B 独立解锁记录仍未满足；生产 Codex 路由、不可信多租户等高风险启用未请求、未授权。Phase 6 01～05 与双语 08 已于 2026-11-16 按代码现实核查并批准直接继续开发；不声称 Phase 6 已实施、测试、验收或获准不可信开放。Phase 7 暂缓。
> 创建：2026-11-02
> 修订：2026-11-20（Phase 5 Stage A 收口：修正本行「Stage A 完整验收未通过」的过期表述，登记 `13` 已签署的范围限定验收记录与 `07` Stage A 解锁记录；明确容器内 bwrap 沙箱边界、Stage B 与高风险启用仍锁定；CD `.env` 版本号回写陷阱由 PR #157 关闭。Phase 0/1 正式验收缺口不因本修订追认完成）
> 修订：2026-11-18（阶段 0–3 验收范围限定：性能/容量/p50/p95/C11 延迟、配对样本与样本数、≤5%/≤50ms、CI provenance/最终 PR head 双跑/CI run URL、真实或授权历史样本、多样本/大数据量均不作为阶段验收门禁，仅作历史记录或范围外说明；保留功能正确性、开关完备性、租户隔离、Secret、数据完整性、迁移、终态/副作用、无 P0/P1 与单一验收记录；高风险能力启用仍为独立审批；阶段 0–3 非破坏性 lane 接受受控共享生产主机）
> 修订：2026-11-16（新增 Phase 6 实施基线；记录当前迁移 head 与上游验收边界）
> 修订：2026-11-13（Phase 3 状态行更新：T1～T9 实施完成、合并测试线通过，T6/T7/T8 无阻断项且实现与文档第三批未提交，T10/T11 进行中故 06/07 尚未创建，T9 条件①并入 #128；08 §2 追加裁定 R-42～R-52，03/04/05 双语同步本批内容）
> 修订：2026-11-13（Phase 3 状态行更新：T1～T6 与 T9 已实施、T5/T9 有条件通过、T6 已通过测试取证与加固轮收口、4 个本地提交未 push 未合入、T7/T8 与 T10/T11 未开始故 06/07 不存在；T12/T13 移出本阶段转 issue #127/#128（08 R-39））
> 修订：2026-11-13（Phase 3 T1～T4 工作树实施状态，任务级评审/验收结论；阶段级 06/07 仍未创建）
> 修订：2026-11-12（同步 Phase 2 实际状态，冻结 Phase 3 设计与实施拆解）
> 依据：`docs/architecture/agent-execution-platform-v2.md` 第 17、19、20、22 节；各阶段 06/07 实际报告
>
> **2026-11-18 验收范围修订（适用于阶段 0–3）**：性能/容量/延迟（p50/p95、C11、配对样本、样本数、≤5%/≤50ms）、CI provenance（最终 PR head 双跑 / CI run URL）、真实或授权历史样本、多样本/大数据量要求不再是阶段验收门禁，仅作历史记录或明确的范围外说明；阶段通过只依据功能正确性（A 场景）、开关完备性（默认关闭、显式开启、off/on/rollback 矩阵、无静默回退、开关不泄漏到公开面/指纹）、租户隔离、Secret、数据完整性、迁移正确性、终态语义、副作用/清理、无开放 P0/P1 与单一验收记录。高风险能力启用仍单独审批；阶段 0–3 非破坏性 lane 可在 run-scoped 隔离的受控共享生产主机上执行，不改变同机服务。

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
- **Phase 3 阶段验收门禁（2026-11-18 范围限定）**：只依据本阶段 A/C 功能、开关矩阵、租户隔离、Secret、数据完整性、迁移、终态/副作用、无 P0/P1 与单一验收记录；上游真实历史样本、CI/真实部署、性能/容量及人工验收缺口按 2026-11-18 修订为历史记录或范围外项，不再阻塞阶段 0–3 验收，也不写为 `pending_env` / 未通过。高风险能力启用仍须独立审批，不能用“代码已合入”替代。
- 2026-11-12 实测迁移 head 为 `0057_industry_pack_runtime`，`0053_routing_decisions` 已占用旧规划号。Phase 3 规划新迁移为 `0058_agent_execution_metadata`，`down_revision="0057_industry_pack_runtime"`；T2 实施前必须动态重验，若目标提交变化则同步修订文档，禁止修改已应用历史迁移。
- **Phase 6 开发入口**：授权在基线 `7772a32` 直接继续开发；从实测单一 head `0067_merge_heads` 规划 0068、0069。该入口不代表 Phase 0 或 Phase 5 完整验收前置已满足；真实 Session/Resume、生产 Codex 路由、强沙箱/故障环境与独立批准仍按 Phase 6 08 R-5～R-9 阻断。
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
- Phase 2：关注有条件通过边界、开关矩阵/隔离/数据/迁移/终态/副作用等保留门禁及附录证据；性能/真实部署缺口为 2026-11-18 范围外历史记录，不重写历史结论。
- Phase 3：重点审查旧根别名与 canonical diff、无 Adapter 实例的草稿校验、最小权限与缓存失效、五快照启动屏障、Provider 单次渲染、双开关矩阵、预览租户隔离及默认关闭/无静默回退/开关不泄漏等保留门禁；C11 的 100 个真实样本为 2026-11-18 范围外历史记录，非门禁。
- Phase 4/5：按实际报告审查进程与 Workspace 隔离、原生协议封装。
- Phase 6：从 [08-implementation-breakdown.md](phase-6-security-reliability-events/08-implementation-breakdown.md) 开始，审查 Fencing 覆盖、直接写入 Outbox 原子性、双 sequence 域、凭据/强沙箱 enforcement、聚焦测试复用及未决上游/真实环境门禁。
- Phase 7：重新激活后按小切片独立评审。
