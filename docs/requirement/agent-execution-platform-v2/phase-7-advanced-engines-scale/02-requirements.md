# Phase 7 · 高级 Engine 能力与规模化 — 需求文档

> 状态：暂缓执行（项目起步阶段；FR/AC 仅保留为延期需求契约，不进入实施、测试或验收）
> 暂缓决定：2026-11-07；FR-1~FR-11 均已登记为最低优先级 P4 issue，详见下方「暂缓与需求跟踪」
> 创建：2026-11-02
> 依据：`01-business-goals.md`（G1~G11）、架构第 17 节 Phase 7、第 18 节持续待办、第 19 节质量门禁、第 22 节架构验收；当前代码核查结果见 `03-technical-design.md`
> 基线声明：现状性能与行为基线未测，待 Phase 0；本文目标不是现状测试结论

## 暂缓与需求跟踪

因项目处于起步阶段，Phase 7 全部需求自 2026-11-07 起暂缓执行，统一调整为最低优先级 P4。以下 issue 仅用于保留需求和后续排期；在明确重新激活本阶段前，不开展实施、测试或验收，也不表示任何功能已经交付。

| 需求 | 主题 | 切片 | P4 issue |
|---|---|---|---|
| FR-1 | Adapter 生态与公共契约 | S7-01 | [#110](https://github.com/GroundedCoreAI/nexusdesk/issues/110) |
| FR-2 | 策略路由与安全回退 | S7-02 | [#111](https://github.com/GroundedCoreAI/nexusdesk/issues/111) |
| FR-3 | Effective 能力与基础执行降级 | S7-02 | [#112](https://github.com/GroundedCoreAI/nexusdesk/issues/112) |
| FR-4 | Engine Session Resume 与重新授权 | S7-03 | [#113](https://github.com/GroundedCoreAI/nexusdesk/issues/113) |
| FR-5 | 人工审批、交互输入与持久等待 | S7-04 | [#114](https://github.com/GroundedCoreAI/nexusdesk/issues/114) |
| FR-6 | 动态模型选择 | S7-05 | [#115](https://github.com/GroundedCoreAI/nexusdesk/issues/115) |
| FR-7 | 统一 Engine 用量与成本 | S7-06 | [#116](https://github.com/GroundedCoreAI/nexusdesk/issues/116) |
| FR-8 | 租户公平与全局配额 | S7-07 | [#117](https://github.com/GroundedCoreAI/nexusdesk/issues/117) |
| FR-9 | Skill 与 Artifact | S7-08 | [#118](https://github.com/GroundedCoreAI/nexusdesk/issues/118) |
| FR-10 | Runtime Profile、健康检查与熔断 | S7-09 | [#119](https://github.com/GroundedCoreAI/nexusdesk/issues/119) |
| FR-11 | 配置开关与逐切片发布 | S7-01~S7-09 | [#120](https://github.com/GroundedCoreAI/nexusdesk/issues/120) |

## 用户故事

**US-1（Engine 贡献者）**：作为 Engine 贡献者，我希望用版本化 Adapter 和公共契约测试接入 Engine，以便无需修改 Worker 核心或扭曲公共协议。

**US-2（平台运维员）**：作为平台运维员，我希望路由回退仍遵守租户策略和副作用边界，以便提高可用性而不放大权限或重复执行。

**US-3（业务用户）**：作为业务用户，我希望不具备高级能力的 Engine 仍能完成基本任务，以便不会因缺少 Session、审批或原生事件而完全不可用。

**US-4（会话操作员）**：作为会话操作员，我希望恢复已绑定且仍获授权的 Engine Session，以便继续上下文而不继承已撤销权限。

**US-5（人工审核员）**：作为人工审核员，我希望在执行挂起后审批或提供受校验输入，以便安全恢复长任务且不会重复副作用。

**US-6（Agent 管理员）**：作为 Agent 管理员，我希望系统在允许的模型 Profile 集合中确定性选择并记录理由，以便兼顾任务需求、成本与可审计性。

**US-7（财务与运营人员）**：作为财务与运营人员，我希望按 Run、Engine、模型与租户查看统一用量和估算成本，以便分析支出且不会重复计算或把未知当零。

**US-8（SRE）**：作为 SRE，我希望全局配额和公平调度跨 Worker 生效，以便单个大租户不会耗尽平台容量或使其他租户饥饿。

**US-9（Workspace 管理员）**：作为 Workspace 管理员，我希望共享只读、带版本和哈希的 Skill，并安全保留和下载 Artifact，以便复用能力而不泄露跨租户数据。

**US-10（Runtime 运维员）**：作为 Runtime 运维员，我希望用版本化 Runtime Profile 管理健康检查与熔断，以便隔离故障、受控恢复并保留基本执行路径。

**US-11（发布负责人）**：作为发布负责人，我希望每个能力切片有独立默认关闭的开关和回滚证据，以便逐片评审、灰度和撤回，避免 Big Bang。

## 功能需求

### FR-1 Adapter 生态与公共契约

| 项 | 说明 |
|---|---|
| 触发时机 | 注册、升级或契约验证一个 Engine/Protocol/Adapter 组合时。 |
| 输入 | 受信任的 Adapter 实现、`(engine_id, protocol_id, adapter_version)`、声明能力、协议兼容范围、配置 Schema 与契约测试结果。 |
| 输出 | 可解析的版本化注册项、Declared 能力、兼容矩阵与拒绝原因；测试环境提供确定性 LocalTestAdapter。 |
| 执行方式 | 注册在组合根显式完成；运行期解析同步进行，外部 Engine 调用异步且不阻塞 Worker 调度循环。 |
| 失败处理 | 未知、不兼容、配置无效或契约失败的 Adapter 不得接收业务执行；错误使用稳定代码，不泄露厂商原始敏感错误。 |

契约要求：覆盖启动、流式事件、结果收集、取消、超时、Engine 不可用、配置无效、协议错误、重复/延迟事件与用量收集；Adapter 不操作队列、不决定租户权限、不提交平台 Run 终态、不绕过 Runtime Host。新增 Protocol 不得迫使公共 Engine 契约加入厂商专属字段。具体厂商仅是示例，不是本 FR 的交付清单。

### FR-2 策略路由与安全回退

| 项 | 说明 |
|---|---|
| 触发时机 | 创建 Execution、选择候选或在启动早期发生可分类故障时。 |
| 输入 | 平台生成的有序 RoutePlan、Agent 已发布配置、租户允许列表、候选健康状态、所需能力、Workspace/凭据策略和当前副作用标记。 |
| 输出 | 选定 Adapter、不可变路由/策略快照，以及 `execution.route_selected` / `execution.fallback` 审计事件。 |
| 执行方式 | 编排器逐候选同步决策、异步启动；同一 Run 可记录多个有先后关系的内部尝试，不引入一等 Task 双表。 |
| 失败处理 | 仅 EngineUnavailable、启动前 ProtocolError 或策略明确允许且无可见输出的启动超时进入下一候选；其余错误终止或等待人工处理。 |

每个候选都必须重新计算 Declared ∩ Available ∩ Policy，并重新校验租户、Agent、Workspace、凭据、配额和 Engine/Protocol 权限。客户端不能直接注入任意候选。发生流式输出、工具/命令、审批、Artifact、Session 状态改变或其他外部副作用后禁止自动回退；超时或结果未知默认禁止回退。

### FR-3 Effective 能力与基础执行降级

| 项 | 说明 |
|---|---|
| 触发时机 | 路由选择、Resume、等待恢复、UI 查询任务可用功能时。 |
| 输入 | Adapter Declared、部署/健康 Available、租户与 Agent Policy、切片开关和请求中的必需能力。 |
| 输出 | 服务端计算的 Effective 能力及不可支持原因；持久化到执行快照，UI 只消费该投影。 |
| 执行方式 | 执行前同步解析；能力或策略变化不会扩大已快照 Execution 的权限，恢复时必须重新解析。 |
| 失败处理 | 可选高级能力不可用时置为 false 并保留基本执行；必需能力缺失返回 `capability_unavailable`，启动前拒绝且不产生副作用。 |

基本执行为 start、按支持情况流式输出、collect_result，以及支持时的 cancel。无 streaming 时允许只在终态返回结果；无 Session/审批/交互/原生事件时不得伪造成功。usage 不可用时明确为 unknown，UI 隐藏或禁用相应操作并给出经 i18n 的原因。

### FR-4 Engine Session Resume 与重新授权

| 项 | 说明 |
|---|---|
| 触发时机 | 创建、更新、过期清理 Session，或操作员通过规划 API `POST /engine-sessions/{session_id}/resume` 发起新 Run 时。 |
| 输入 | 平台 Session ID、可信租户/业务/Workspace 上下文、当前会话与 Agent、幂等键、新输入和当前授权上下文。 |
| 输出 | 新 Run/Execution、Session 绑定快照与 `engine.session.resumed` 事件；不返回宿主进程信息或原生凭据。 |
| 执行方式 | 授权与快照同步完成，Engine 恢复异步执行；同一幂等键和相同请求只创建一个 Run。 |
| 失败处理 | Session 不存在、过期、终态、跨租户、会话/Workspace/Engine 绑定变化或策略不兼容时失败关闭；不自动换 Engine 继续原生 Session。 |

恢复必须重新加载当前已发布 Agent、租户策略、有效凭据引用、Runtime Profile 与 Effective 能力；旧策略快照只用于审计，不能恢复已撤销权限。原生 metadata 由 Adapter 按版本解释，平台不任意改写。不支持 Resume 的 Adapter 返回明确不支持，不模拟持久 Session。

### FR-5 人工审批、交互输入与持久等待

| 项 | 说明 |
|---|---|
| 触发时机 | Effective 能力允许且 Engine/编排器请求审批或结构化输入；操作员提交决议、取消或等待过期时。 |
| 输入 | Execution/Run、交互类型、经过大小和 Schema 限制的请求、过期时间、审批人权限、revision 与幂等决议。 |
| 输出 | waiting Run、待处理交互、`approval.required`/`approval.resolved` 或 `input.required`/`input.resolved` 事件，以及一次受控恢复。 |
| 执行方式 | 同事务持久等待和 Run 状态后释放运行 Lease/配额；决议后重新授权并转 queued，由 Worker 异步恢复。 |
| 失败处理 | 自审、越权、revision 冲突、重复不同决议、Schema 不符、取消或过期均不得恢复；重复相同请求返回原结果且不重复副作用。 |

审批复用现有 `ApprovalService` 的租户隔离、职责分离、revision 与审计，通过平台端口关联 Execution，不复制第二套审批状态机。交互输入只接受声明的非 Secret 结构化类型；Secret 必须走凭据引用，不能写入普通事件。waiting 是新增公开状态，现有五态及其 SSE 终态语义保持兼容；同会话互斥必须包含 waiting。

### FR-6 动态模型选择

| 项 | 说明 |
|---|---|
| 触发时机 | 支持动态选择的 React Execution 在启动前解析模型时。 |
| 输入 | Agent 的版本化选择策略、允许的 Profile ID/版本约束、操作类型、工具/输入约束、租户网关权限和可用模型目录。 |
| 输出 | 一个模型 Profile ID、不可变版本、选择规则/理由和实际模型调用关联；没有策略时沿用固定 Profile。 |
| 执行方式 | 启动前确定性规则选择并快照；一次 Execution 内不切换选择策略，网关自身模型路由 fallback 继续按现有契约执行。 |
| 失败处理 | 无合格 Profile、版本不固定、操作/工具不兼容或越权时启动前失败；不得为追求成功率选择允许集合外模型。 |

动态模型选择与 Engine fallback 是不同层级的决策，二者均需独立授权和审计。非 React Engine 只有声明并通过适配契约时才可接入；不得假定所有 Engine 都由平台模型网关驱动。选择依据必须是有界规则，不接受客户端任意 Profile ID 或未经审核的自动学习策略。

### FR-7 统一 Engine 用量与成本

| 项 | 说明 |
|---|---|
| 触发时机 | Adapter 报告增量/汇总用量、模型网关完成调用、Execution 结束或报表查询时。 |
| 输入 | 带 Adapter 事件标识的用量、来源、指标版本、数值单位、Execution/Run 关联、定价快照和币种。 |
| 输出 | 幂等用量记录与按租户/时间/Run/Engine/Protocol/Adapter/模型聚合的报表；每次 Execution 可发出 `usage.updated`。 |
| 执行方式 | 用量落库幂等且与主执行解耦，报表只读聚合；缺少用量不阻断已完成的基本输出。 |
| 失败处理 | 非数值、负数、非有限值或未知单位拒绝/隔离；成本不可计算标 unknown，记录持久化失败并告警但不伪造 0。 |

复用现有 `gateway_calls`、`gateway_attempts`、`gateway_costs`，不重复抄写模型费用。Engine 记录必须声明 `aggregation_mode=additive|informational`；只有 additive 进入总计，与网关重叠的 Engine 汇总只能 informational。不同币种分列，费用均标为估算而非账单，并保留 unknown 记录数。

### FR-8 租户公平与全局配额

| 项 | 说明 |
|---|---|
| 触发时机 | Run 提交、Worker claim/finish/cancel/reap、等待与恢复时。 |
| 输入 | 全局/租户 queued 与 running 限额、当前有效运行记录、租户公平游标和可信租户范围。 |
| 输出 | 原子准入或稳定 429、跨 Worker 一致的领取顺序、配额事件与可观测计数。 |
| 执行方式 | 保留 PostgreSQL 持久队列、`FOR UPDATE SKIP LOCKED`、Lease/Heartbeat；用短事务和数据库协调保证跨进程限额与防饥饿选择。 |
| 失败处理 | 配额满返回 `execution_quota_exceeded` 与有界 Retry-After；数据库协调失败时 fail closed，不通过进程内计数近似放行。 |

waiting 不占 running 配额，也不被当作可立即 claim 的 queued；恢复重新准入。平台应分别限制等待数量，防止持久等待无限占用存储。调度只保证本阶段定义的公平与全局限额，不承诺任务优先级或严格实时 SLA。

### FR-9 Skill 与 Artifact

| 项 | 说明 |
|---|---|
| 触发时机 | 发布/引用 Skill、准备 Execution Workdir、收集 Artifact、下载或保留清理时。 |
| 输入 | 租户/共享作用域、Skill 版本/来源/权限/内容哈希、Engine 适配类型、Artifact 内容/大小/MIME/保留策略和授权上下文。 |
| 输出 | 只读 Skill 挂载与快照、`artifact.created` 事件、Artifact 元数据和经授权下载；不向客户端暴露宿主路径。 |
| 执行方式 | Skill 在启动前校验并固定版本；Artifact 通过 Workspace/Object Store 端口异步写入，元数据与内容哈希可核验。 |
| 失败处理 | 哈希/来源/权限不符、路径或符号链接逃逸、超限、跨租户访问、保留期到期均拒绝；失败不将不受信内容挂载进 Engine。 |

共享 Skill 仅只读，平台格式不绑定某一厂商目录；Engine Skill Adapter 负责确定性转换。Artifact 使用独立执行存储配置和授权下载，不复用知识库密钥作为默认凭据，不提供永久匿名 URL。大型对象、Secret 扫描和清理失败必须可观测。

### FR-10 Runtime Profile、健康检查与熔断

| 项 | 说明 |
|---|---|
| 触发时机 | 发布/解析 Runtime Profile、执行路由、定时健康探测、连续失败/成功或人工禁用时。 |
| 输入 | 版本化 Engine/Protocol/Adapter 绑定、资源/超时/ egress/Secret 引用、租户允许范围、健康探测配置与带时间戳结果。 |
| 输出 | 不可变 Profile 快照、Available 状态、closed/open/half_open 熔断状态、审计事件与告警。 |
| 执行方式 | 无副作用探测异步且有超时；路由读取最新有效状态，半开仅允许有界探测执行。 |
| 失败处理 | 配置无效拒绝发布；健康数据陈旧或未知不视为健康；open 时跳过候选或返回明确不可用，不无限排队。 |

健康状态只参与 Available，不能增加 Policy/Effective 权限。人工 disabled 优先于自动恢复；熔断键至少包含 Runtime Profile ID/版本和 Adapter 标识。多 Worker 需要一致状态或有证据的等效协调，不能以单进程计数冒充全局健康。

### FR-11 配置开关与逐切片发布

| 配置项 | 层级 | 默认值 | 说明 |
|---|---|---|---|
| `phase7_adapter_sdk_enabled` | 全局 settings | `false` | 仅启用 S7-01 适配器 SDK/测试入口，不自动启用任何厂商 Adapter。 |
| `phase7_safe_routing_enabled` | 全局 settings | `false` | 启用 S7-02 路由、回退与 Effective 能力增强。 |
| `phase7_session_resume_enabled` | 全局 settings | `false` | 启用 S7-03 Session Resume；关闭时不得创建恢复执行。 |
| `phase7_human_interaction_enabled` | 全局 settings | `false` | 启用 S7-04 持久等待、审批和输入恢复。 |
| `phase7_dynamic_model_enabled` | 全局 settings | `false` | 启用 S7-05；无 Agent 策略时仍保持固定 Profile。 |
| `phase7_engine_usage_enabled` | 全局 settings | `false` | 启用 S7-06 Engine 用量采集；既有网关记录不回填伪造。 |
| `phase7_fair_scheduling_enabled` | 全局 settings | `false` | 启用 S7-07 公平/全局配额新路径。 |
| `phase7_skill_artifact_enabled` | 全局 settings | `false` | 启用 S7-08 Skill 挂载与执行 Artifact 服务。 |
| `phase7_runtime_profile_enabled` | 全局 settings | `false` | 启用 S7-09 Profile 与健康熔断路由。 |

所有环境变量沿用 `AGENT_` 前缀。开关是独立 blast-radius 控制，不表示可绕过切片依赖；依赖不满足时配置校验应拒绝启用。已持久化的 Session、waiting、用量、Artifact 与健康历史在关闭后仍可按授权读取/清理，但不得经新开关路径继续执行。回滚不得依赖 down migration。

## 非功能需求

- **性能**：Phase 0 先测量现有执行与数据库基线。路由/能力解析在不含外部 I/O 时新增 P95 开销目标 ≤50 ms；报表在约定 30 天数据量下 P95 ≤2 s；配额在约定压测下不超过全局/租户硬限额。未记录环境和样本的数值不得作为验收结论。
- **兼容**：旧 Agent 配置默认 ReAct/固定 Profile；旧 Run 状态、事件游标和终态不变。新字段可空或有兼容默认值，waiting 与新增事件须同步 API、SDK/UI；开关全关相对 Phase 0 的行为 diff 为 0。
- **多租户**：所有 Session、交互、用量、Skill/Artifact、Profile 绑定和调度操作使用可信 tenant/business/workspace scope；跨租户资源标识不可枚举，404/403 策略一致且不泄露存在性。
- **安全**：回退、Resume、恢复与动态选择均重新授权；权限只收窄。不可信代码上线前必须具备已验收沙箱、Workspace、网络、资源与凭据隔离。普通事件、日志、审计、报表不得含 Secret。
- **可靠性**：Run 终态、Lease/Heartbeat、事件游标与幂等约束保持权威；等待/恢复、重复事件、迟到结果、Worker 重启与进程崩溃均有契约测试。任何自动重试不得重复未知副作用。
- **可观测性**：审计包含 actor、tenant scope、run/execution、route/profile/policy 版本与稳定原因码，不包含输入正文或凭据；关键故障、配额拒绝、熔断与 unknown usage/cost 有指标和告警。
- **UI/i18n**：UI 展示服务端 Effective 能力、等待/健康/unknown 状态及原因；所有用户可见文案走 i18n，不以技术 Declared 能力冒充已授权能力。
- **交付**：每片小 PR 只修改必要模块，保留适用 lint/typecheck/契约/迁移/集成/安全门禁；不得以未实现的厂商 Adapter 作为统一契约验收替代品。

## 验收标准

| # | 场景 | 预期 | 溯源 |
|---|---|---|---|
| AC-1 | 用 LocalTestAdapter 注册一个新 Engine/Protocol 组合并运行公共契约 | 启动、流式、结果、取消、超时、错误、重复/延迟事件与用量用例全部通过；Worker 核心无改动，公共契约无厂商字段 | G1/US-1/FR-1 |
| AC-2 | 注册未知组合、不兼容版本、无效配置及能力虚报的 Adapter | 业务执行前被拒绝并给出稳定原因；不得进入路由或接触租户数据 | G1/US-1/FR-1 |
| AC-3 | 首选候选在产生任何输出/副作用前返回可重试 EngineUnavailable，第二候选获授权且兼容 | 仅创建一个有序后续尝试，记录两次策略/能力校验与回退原因，Run 最终语义唯一 | G2/US-2/FR-2 |
| AC-4 | 分别尝试回退到未授权候选，以及在输出、工具、审批、Artifact 或未知超时后回退 | 未授权候选被拒绝；有副作用或结果未知时不自动回退，不重复执行，事件说明原因 | G2/US-2/FR-2 |
| AC-5 | Adapter 不支持 Session、审批、交互和 streaming，但支持基本执行，请求未将这些能力标为必需 | Effective 对应项为 false，基本结果可完成；UI 不显示伪造操作，usage 缺失显示 unknown | G3/US-3/FR-3 |
| AC-6 | 请求明确要求终端、Resume 或其他当前 Effective 不具备的能力 | 启动前返回 `capability_unavailable`，不启动 Engine、不静默关闭安全要求、不落副作用 | G3/US-3/FR-3 |
| AC-7 | 在同一租户/会话/Workspace 和兼容策略下恢复有效 Session，并用相同幂等键重试 | 重新授权后只创建一个新 Run，沿用原生 Session 并固定新执行快照，事件可关联 | G4/US-4/FR-4 |
| AC-8 | 在 Session 过期、撤权、Agent/Workspace/Engine 绑定变化或跨租户情况下恢复 | 全部失败关闭，不创建 Run、不更换 Engine、不沿用旧授权；审计不含原生 Secret | G4/US-4/FR-4 |
| AC-9 | Engine 请求人工审批，另一合格审核员批准；并发重复批准、自审和 Worker 重启同时发生 | Run 进入 waiting 并释放运行资源；仅一次合法批准触发一次重新授权恢复，自审/重复冲突不改变结果或重复副作用 | G5/US-5/FR-5 |
| AC-10 | Engine 请求结构化输入，分别提交合法输入、错误 Schema、越权输入、过期输入和取消 | 仅合法且在有效期内的输入恢复一次；其余不恢复，事件/审计不记录 Secret 或越权内容 | G5/US-5/FR-5 |
| AC-11 | Agent 配置有界动态模型策略，同时保留一个无策略的旧 Agent | 新 Agent 选择允许集合内固定版本并记录理由；旧 Agent 的 Profile/版本和网关行为与 Phase 0 一致 | G6/US-6/FR-6 |
| AC-12 | 最优模型不支持所需工具、未授权或无固定版本，后续存在合格模型 | 只评估授权候选并选择合格项；无合格项则启动前失败，不越权 fallback | G6/US-6/FR-6 |
| AC-13 | 同一 Adapter 事件重复上报，且 Engine 汇总用量与网关模型调用重叠 | 幂等去重；additive 与 informational 正确区分，总和不重复，来源和 Run/Execution 关联完整 | G7/US-7/FR-7 |
| AC-14 | 用量缺少定价、包含两种币种，并尝试跨租户查询报表 | 未知成本保持 unknown 而非 0；币种分列不直接求和；跨租户无数据泄露 | G7/US-7/FR-7 |
| AC-15 | 多 API/Worker 并发提交和 claim，使全局与租户 queued/running 同时接近上限 | 原子准入不超任何硬限额；429 语义稳定，完成/取消/reap 后按契约释放 | G8/US-8/FR-8 |
| AC-16 | 高负载租户持续提交，轻载租户间歇提交，同时存在 waiting Run | 轻载租户每批均能推进且达到约定 P95 目标；waiting 不占 running，恢复重新准入 | G8/US-8/FR-8 |
| AC-17 | 发布共享 Skill，篡改内容或引用跨租户/未授权版本后启动执行 | 合法执行固定版本/哈希并只读挂载；篡改和越权在启动前拒绝，平台格式不被厂商格式替代 | G9/US-9/FR-9 |
| AC-18 | 生成小型与大型 Artifact，尝试路径逃逸、跨租户/过期下载并执行保留清理 | 合法内容哈希和授权下载正确；危险路径、越权和过期访问被拒，清理与 Secret 扫描可审计 | G9/US-9/FR-9 |
| AC-19 | 发布带资源/egress/Secret 引用的 Runtime Profile，注入连续健康失败达到阈值 | 执行固定 Profile 快照；熔断 closed→open，候选被跳过或明确失败，权限不因健康状态扩大 | G10/US-10/FR-10 |
| AC-20 | 冷却后有界半开探测成功/失败、健康数据陈旧、人工禁用后再恢复 | half_open 转换和探测数量符合契约；陈旧数据不健康，人工禁用优先，恢复不绕过路由授权 | G10/US-10/FR-10 |
| AC-21 | 分别独立启用/关闭九个切片，并在全部关闭后重放 Phase 0 回归 | 开关默认值均为 false，依赖校验明确；全关时 API、事件、模型选择和终态行为 diff 为 0 | G11/US-11/FR-11 |
| AC-22 | 对任一切片执行设计评审、迁移 head 核查、灰度、回滚与证据检查 | 仅批准该片范围；回滚无需 down migration，历史授权数据可保留；未满足门禁不进入生产 | G11/US-11/FR-11 |
