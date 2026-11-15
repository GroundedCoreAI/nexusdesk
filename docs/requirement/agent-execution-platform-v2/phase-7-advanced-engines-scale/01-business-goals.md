# Phase 7 · 高级 Engine 能力与规模化 — 业务目标

> 状态：暂缓执行（项目起步阶段；保留规划，不进入实施、测试或验收）
> 暂缓决定：2026-11-07；FR-1~FR-11 已登记为最低优先级 P4 GitHub issue（#110~#120），索引见 `02-requirements.md`「暂缓与需求跟踪」
> 创建：2026-11-02
> 依据：`docs/architecture/agent-execution-platform-v2.md` 第 17 节 Phase 7、第 18 节、第 19 节、第 22 节；2026-11-02 对当前代码与 Alembic 迁移的核查
> 阶段：Phase 7（高级能力，P4 最低优先级；依赖 Phase 0~6 的已验收能力）
> 预估工期：按 9 个独立小 PR/切片分别估算，不给出 Big Bang 总工期承诺
> 依赖：Phase 0 基线与回归证据、Phase 1~2 公共执行契约与编排器、Phase 3 能力/指令、Phase 4 Workspace/Runtime Host、Phase 6 安全与事件治理；未满足依赖的切片不得上线

## 要解决的问题

### 问题 1：当前执行路径仍固定于 ReAct，扩展边界尚未形成

当前 `backend/src/agent_platform/core_platform/agent_runtime/worker.py` 直接调用 Runtime，`backend/src/agent_platform/applications/platform_runtime/runtime_factory.py` 构造固定 `RuntimeEngine`，尚无已实现的公共 Engine/Protocol/Adapter 注册中心。直接堆叠厂商集成会把协议差异、进程管理和路由策略重新耦合进 Worker。

### 问题 2：高级能力缺少统一、可降级的治理契约

Session Resume、人工审批、交互输入、动态模型选择等能力不能仅靠 Adapter 声称支持。当前 `RunStatus` 只有 queued/running/completed/failed/cancelled，尚无以执行等待状态、Session 重新授权和副作用安全回退为核心的实现。若各 Engine 自行解释能力，UI、权限与失败语义会不一致。

### 问题 3：模型治理已有基础，但不能代表全 Engine 用量与规模治理

现有模型网关已支持版本化 Profile、模型路由 fallback、调用用量和估算成本；现有 Runtime 也有队列容量与租户容量限制。它们尚未覆盖 Engine 原生用量、跨币种/未知成本、跨 Worker 公平调度，以及 Runtime Profile 健康熔断。重复建设或重复计费都会造成错误治理。

### 问题 4：Skill、Artifact 与健康状态若缺少平台边界，将扩大安全和运维风险

当前知识/工具工作区和 S3 归档能力不是通用执行 Skill/Artifact Store。若直接暴露宿主路径、对象键或厂商目录格式，会产生跨租户访问、路径逃逸、凭据泄露和格式锁定风险；若健康检查只保存在单进程内，也无法支撑多 Worker 的一致路由。

## 业务目标

| 目标 | 说明 |
|---|---|
| G1：可验证的 Adapter 生态 | 新 Engine 以 `(engine_id, protocol_id, adapter_version)` 接入并通过公共契约测试，不修改 Worker 核心或公共 Engine 契约；Claude、ACP、OpenClaw 等仅是适配器示例，不构成交付承诺。 |
| G2：受策略约束的路由与回退 | 只对明确、无副作用且可重试的故障回退；每个候选重新执行租户、Agent、Workspace、凭据与能力授权，权限只能收窄。 |
| G3：基础执行始终可用 | 不支持高级能力的 Engine 仍可按 Effective 能力完成基本执行；必需能力缺失则前置拒绝，禁止静默降级安全要求。 |
| G4：可恢复且重新授权的 Session | Session 与租户、会话、Engine/Protocol/Adapter、Workspace 和策略版本绑定；恢复前重新授权，过期或越权恢复失败关闭。 |
| G5：可恢复的人机协作 | 人工审批与交互输入使用持久等待、幂等决议、职责分离和过期语义；等待释放执行资源，恢复不重复副作用。 |
| G6：可审计的动态模型选择 | 在租户与 Agent 允许集合内确定性选择版本化模型 Profile，快照记录选择理由；旧固定 Profile 行为保持兼容。 |
| G7：统一且不重复计算的用量/成本 | 汇聚模型网关与 Engine 原生用量，区分可加总与仅展示数据、已知与未知成本、不同币种；跨租户不可见。 |
| G8：租户公平与全局配额 | 在保留现有队列/Lease 的前提下实施跨 Worker 原子配额与防饥饿调度，限制 noisy neighbor，waiting 不占用运行配额。 |
| G9：受控的 Skill 与 Artifact | Skill 有版本、来源、权限与内容哈希并以只读方式适配挂载；Artifact 有租户授权、哈希、保留期和安全下载，不暴露宿主路径。 |
| G10：可运维的 Runtime Profile | 版本化 Runtime Profile 统一资源与 Adapter 配置；健康检查、熔断、半开恢复影响 Available 而非授权，状态可审计。 |
| G11：可独立回退的渐进交付 | 每个切片有独立默认关闭的 feature flag、小 PR、契约测试、上线评审与回滚证据，避免一次性上线全部 Phase 7。 |

## 成功指标

> 下列“未测”均不是零，也不是已通过；须由 Phase 0 在指定环境建立基线并记录样本、负载与测量方法。基线缺失时不得以比较型指标宣称改善。

| 指标 | 基线（现状） | 目标 |
|---|---|---|
| Adapter 契约通过率与 Worker 解耦 | 未测，待 Phase 0 记录现有 Adapter/契约覆盖（当前无公共 Adapter 套件） | 每个上线 Adapter 的适用契约用例 100% 通过；新增 Adapter 的 Worker 核心 diff 为 0，公共 Engine 契约无不必要变更。 |
| 回退授权与副作用安全 | 未测，待 Phase 0 记录现有错误/重试行为 | 越权回退、发生副作用后的自动回退、跨租户回退均为 0；每次回退均有原因和策略快照。 |
| 基础能力兼容 | 未测，待 Phase 0 固定 ReAct 请求、事件、终态与 UI 基线 | 高级能力关闭或不可用时，Phase 0 基础执行回归 100% 通过，开关关闭行为 diff 为 0。 |
| Session 恢复安全 | 未测，待 Phase 0 盘点会话与授权行为 | 适用恢复场景重新授权率 100%；过期、撤权、绑定变化与跨租户恢复阻断率 100%。 |
| 人机等待与决议正确性 | 未测，待 Phase 0 记录现有审批与 Run 行为 | 等待不持有运行 Lease/配额；重复决议不产生第二次恢复或副作用；越权/自审/过期决议阻断率 100%。 |
| 动态模型选择可审计性 | 未测，待 Phase 0 记录固定 Profile 选择及模型 fallback | 100% 选择落在允许集合并固化 Profile ID/版本/理由；旧配置选择结果与 Phase 0 一致。 |
| 用量完整性与成本口径 | 未测，待 Phase 0 测量模型网关覆盖、未知成本与延迟 | 100% 记录有来源和幂等键；重复上报不重复汇总；未知成本不显示为 0；跨币种不直接相加。 |
| 配额与公平性 | 未测，待 Phase 0 测量队列吞吐、P95 等待和 noisy-neighbor 场景 | 多 Worker 压测无超限；在约定双租户负载下，轻载租户每批测试均能推进，且其 P95 排队时间不超过同环境空载基线的 2 倍。 |
| Skill/Artifact 安全与可重现 | 未测，待 Phase 0 盘点 Workspace 与对象存储边界 | 执行快照 100% 固定 Skill 版本/哈希；跨租户下载、路径逃逸、篡改挂载和过期下载阻断率 100%。 |
| Runtime 健康治理 | 未测，待 Phase 0 记录 Engine 可用性与故障恢复 | 熔断/半开状态转换符合契约率 100%；陈旧健康数据不被视为健康；健康检查不执行租户业务副作用。 |
| 切片回退能力 | 未测，待 Phase 0 记录发布与回滚流程 | 每个上线切片均能独立关闭；关闭后适用 Phase 0 行为 diff 为 0，回滚不要求删除历史数据或执行 down migration。 |

## 范围

**包含**：以下只是统一规划与候选交付切片；每片都须在设计评审时确认依赖、迁移 head、API/UI、测试证据和实际上线范围。

| 切片 | 能力范围 | 独立开关（默认关闭） | 主要依赖 |
|---|---|---|---|
| S7-01 | Adapter SDK、LocalTestAdapter 增强、公共契约与兼容性测试 | `phase7_adapter_sdk_enabled` | Phase 1 契约/注册中心 |
| S7-02 | 策略路由、安全回退、基础能力降级、Effective 能力投影 | `phase7_safe_routing_enabled` | Phase 1~3；S7-01 测试适配器 |
| S7-03 | Engine Session 生命周期与重新授权 Resume | `phase7_session_resume_enabled` | Phase 2~4、Phase 6 |
| S7-04 | 人工审批、交互输入、持久 waiting 与恢复 | `phase7_human_interaction_enabled` | Phase 2、Phase 6；复用现有审批端口 |
| S7-05 | 动态模型 Profile 选择与快照 | `phase7_dynamic_model_enabled` | Phase 2 React Provider；现有模型网关 |
| S7-06 | Engine 用量归一化、成本汇总与报表 | `phase7_engine_usage_enabled` | Phase 1 事件契约；S7-01 |
| S7-07 | 跨 Worker 全局/租户配额与公平调度 | `phase7_fair_scheduling_enabled` | Phase 2 编排器与现有持久队列 |
| S7-08 | 共享只读 Skill Store、Engine Skill Adapter、Artifact Store | `phase7_skill_artifact_enabled` | Phase 3~4、Phase 6 |
| S7-09 | Runtime Profile、健康检查、熔断与半开恢复 | `phase7_runtime_profile_enabled` | Phase 1 注册中心、Phase 4 Runtime Host |

**不包含**（属于后续阶段 / 明确不做）：
- 不承诺交付或许可任何具体厂商 Engine/Protocol；Claude、ACP、OpenClaw、远程及自定义 Engine 只作为 Adapter 形态示例。
- 不把所有切片合并为一个核心迁移或大型 PR，不以接入 Engine 数量代替架构验收。
- 不拆微服务，不整体替换现有 Worker 队列、Lease、Heartbeat 与终态保护。
- 不在本阶段自动引入一等 Task/Execution 双表、任务优先级或跨 Engine 的有副作用续跑；有证据需要时另立需求。
- 不允许超时、结果未知、已流式输出、已审批、已产生 Artifact 或已发生外部副作用后盲目自动回退。
- 不把成本估算当供应商账单，不在缺少汇率与快照时进行币种换算，不把缺失 usage/cost 当 0。
- 不提供跨租户可写 Skill、匿名 Artifact 链接、任意客户端宿主命令，或在沙箱与网络/凭据隔离未验收时开放不可信代码执行。

## 风险与约束

- **依赖先行**：本文引用的是目标 `agent_execution` 边界，不表示这些模块已经存在；实施必须基于已验收的 Phase 0~6 现实重核。
- **迁移漂移**：当前最新迁移为 `0052_memory_tasks_tenant_index`。本文如出现 `0058+` 均为规划号而非现有文件，实施前必须重核 head、重新编号并设置真实 `down_revision`。
- **权限放大**：fallback、动态模型、Resume 与健康恢复都可能改变执行目标；每次改变目标均须重新计算 Effective 能力并沿用可信租户上下文。
- **副作用未知**：超时和断连不能证明 Engine 未执行工作；默认停止自动回退并给出可审计的未知/失败语义。
- **数据重复**：模型网关已记录模型调用成本；Engine 聚合用量必须声明是否可加总，禁止与模型调用重复求和。
- **兼容性**：新增 waiting、Effective 能力和新事件均为 additive 变更；旧 Run、Agent 发布快照、SSE 游标与固定 Profile 行为必须可读取、可回放。
- **敏感信息**：配置只保存 Secret 引用，日志、事件、Skill 元数据、Artifact 元数据和报表不得包含明文 Token、宿主敏感路径或跨租户标识。
- **上线边界**：文档给出统一可测试契约，不等于批准全部功能上线；具体范围、阈值、真实模型/Engine、容量与生产样本须逐切片在单一验收记录中确认并保留证据。
