# Phase 7 · 高级 Engine 能力与规模化 — 技术落地文档

> 状态：暂缓执行（项目起步阶段；目标设计仅作 backlog 参考，不进入实施）
> 暂缓决定：2026-11-07；FR-1~FR-11 对应 P4 issue 见 `02-requirements.md`「暂缓与需求跟踪」，重新排期前不得据此启动开发或迁移
> 创建：2026-11-02
> 依据：`01-business-goals.md`（G1~G11）、`02-requirements.md`（FR-1~FR-11、AC-1~AC-22）、架构第 4~19 节与第 22 节、当前代码核查
> 基线声明：当前最新迁移 head 核查为 `0052_memory_tasks_tenant_index`；行为/性能基线未测，待 Phase 0。本文 `0058+` 全部是规划号，实施前必须重核 head、重编号并设置真实依赖
> 约束：本文只定义逻辑模型、流程与文件级计划，不包含实现代码或可执行迁移

## 改动总览

### 当前代码事实与设计约束

| 当前位置 | 2026-11-02 核查事实 | Phase 7 约束 |
|---|---|---|
| `backend/src/agent_platform/core_platform/agent_runtime/engine.py` | LangGraph ReAct Runtime，直接构造模型/工具循环 | 保留为 React Provider 内部实现，不把 Engine 专属概念扩散到 Worker |
| `backend/src/agent_platform/core_platform/agent_runtime/worker.py` | Worker 直接调用 `runtime.run`，按配置的 `settings.tenant_id` 领取 Run，负责 Lease、取消与终态协作 | Phase 2 应先切到 Orchestrator；Phase 7 公平调度需扩展多租户领取上下文，不在 Worker 写路由/厂商逻辑 |
| `backend/src/agent_platform/core_platform/agent_runtime/repository.py` | 持久队列、FIFO claim、事件、容量计数与终态条件更新 | 复用队列与事务；公平调度和 waiting 需 additive 扩展，不能削弱 Lease/终态保护 |
| `backend/src/agent_platform/core_platform/agent_runtime/schemas.py` | Run 只有 queued/running/completed/failed/cancelled | waiting 是显式 additive 变更，需同步约束、索引、API、SDK 与 UI |
| `backend/src/agent_platform/applications/platform_runtime/runtime_factory.py` | 按 Agent 快照构造固定 ReAct Runtime 和固定模型 Profile | Phase 1~2 应已由 Registry/Orchestrator 替代核心解析；动态模型只扩展 React 模型绑定 |
| `backend/src/agent_platform/applications/platform_runtime/runtime_composition.py` | 组合根显式构造 Runtime、Repository、Worker 与平台服务 | 新服务只在此及对应应用入口注入，Adapter 不自行获取全局服务或跨模块仓储 |
| `backend/src/agent_platform/business_capabilities/agent_config/service.py` | `AgentConfig(extra="forbid")` 使用固定 `model_profile_id/version` | 新 Engine/动态模型/Skill 引用必须类型化、可默认兼容并进入发布快照 |
| `backend/src/agent_platform/core_platform/platform_services/model_gateway/` | 已有版本化 Profile、模型 fallback、配额、调用/尝试、usage 与估算 cost | 复用模型调用与费用事实表；动态选择和 Engine 用量不得重复实现或重复计费 |
| `backend/src/agent_platform/business_capabilities/approval/service.py` | 已有租户隔离、幂等创建、revision、职责分离、决议与审计 | 通过事务端口关联 Execution，复用审批状态机，不创建平行审批业务 |
| `backend/src/agent_platform/core_platform/platform_services/storage/objects.py` | 只有面向知识归档的 S3 put 封装 | 新建执行 Artifact 端口与独立配置，不把知识库凭据/路径当默认执行存储 |
| `backend/src/agent_platform/core_platform/platform_services/platform_settings/settings.py` | `AGENT_` 前缀；已有全局/租户活动容量等设置 | 九个 Phase 7 开关默认 false；敏感配置只存环境 Secret 引用 |
| `frontend/src/shared/components/ui.tsx`、`frontend/src/features/models/GatewayReports.tsx` | 消费现有 SSE 与模型报表 | 增量支持 waiting、Effective 能力、Engine 用量和 unknown 状态，所有文案走 i18n |
| `backend/migrations/versions/0052_memory_tasks_tenant_index.py` | 当前核查到的最高迁移号 | 禁止把下列规划号写成已存在；每片实施前重核最新 head |

### 目标文件级计划

下列 `agent_execution` 路径基于架构第 16 节，只有 Phase 1~6 已建立相应边界后才可按片新增/修改。

| 层/切片 | 文件（规划） | 改动 |
|---|---|---|
| S7-01 契约 | `backend/src/agent_platform/core_platform/agent_execution/contracts/` | 复用公共 Request/Handle/Result/Event/Error；只增加必要的版本化扩展点，不加入厂商字段 |
| S7-01 Adapter | `backend/src/agent_platform/core_platform/agent_execution/adapters/testing/local_test_adapter.py` | 增强确定性故障、重复/延迟事件、用量和能力矩阵模拟 |
| S7-01 测试 | `backend/tests/agent_execution/contract/` | 建立所有 Adapter 共用的参数化契约套件与依赖边界检查 |
| S7-02 路由 | `backend/src/agent_platform/core_platform/agent_execution/orchestration/route_planner.py`、`fallback_policy.py` | 生成受信 RoutePlan、分类副作用、逐候选重新授权 |
| S7-02 能力 | `backend/src/agent_platform/core_platform/agent_execution/capability/capability_resolver.py` | 输出带原因和策略版本的 Effective 快照；向只读 UI 投影提供 DTO |
| S7-03 Session | `backend/src/agent_platform/core_platform/agent_execution/session/session_manager.py`、`session_repository.py` | 生命周期、绑定校验、过期清理、恢复重新授权与幂等创建 Run |
| S7-04 交互 | `backend/src/agent_platform/core_platform/agent_execution/interaction/interaction_manager.py`、`interaction_repository.py`、`approval_port.py` | 持久 waiting、审批事务端口、Schema 输入、过期/取消与恢复 |
| S7-05 模型 | `backend/src/agent_platform/core_platform/agent_execution/models/model_selection.py` | 有界确定性规则、Profile 资格过滤与选择快照 |
| S7-06 用量 | `backend/src/agent_platform/core_platform/agent_execution/usage/usage_contracts.py`、`usage_repository.py`、`usage_reporting.py` | 归一化、幂等、additive/informational、unknown 与分币种聚合 |
| S7-07 调度 | `backend/src/agent_platform/core_platform/agent_runtime/worker.py`、`admission.py`、`repository.py`；`agent_execution/scheduling/fair_claim.py` | 接入多租户公平 claim 上下文、原子 queued/running 准入、公平候选选择、waiting 恢复重新准入；Worker 不承载 Engine 逻辑 |
| S7-08 Skill | `backend/src/agent_platform/core_platform/agent_execution/skills/skill_store.py`、`skill_adapter.py` | 版本/哈希/来源/权限、共享只读挂载与 Engine 格式转换 |
| S7-08 Artifact | `backend/src/agent_platform/core_platform/agent_execution/artifacts/artifact_store.py`、`object_store.py` | 授权元数据、对象写入/下载、保留、扫描状态与清理 |
| S7-09 Profile | `backend/src/agent_platform/core_platform/agent_execution/host/runtime_profile.py`、`health_monitor.py`、`circuit_breaker.py` | 版本化配置快照、主动/被动健康、分布式状态与半开恢复 |
| 公共编排 | `backend/src/agent_platform/core_platform/agent_execution/orchestration/orchestrator.py` | 接线路由、Session、交互、模型、Workspace、用量和 Profile；不实现 Engine 推理 |
| 公共持久化 | `backend/src/agent_platform/core_platform/agent_runtime/repository.py`、`schemas.py` | 增加 waiting/执行关联与公平 claim；保留旧读取、事件游标和终态条件更新 |
| 配置 | `backend/src/agent_platform/business_capabilities/agent_config/service.py`；`platform_settings/settings.py` | 类型化可选策略、九开关、限制值与 Secret 引用校验 |
| API | `backend/src/agent_platform/applications/platform_runtime/execution_routes.py`、`runtime_composition.py` | 规划 Resume、交互、Effective、用量、Artifact、Profile 管理端点及组合注入 |
| 前端 | `frontend/src/shared/api/client.ts`、`shared/components/ui.tsx`、`features/execution/`、`features/models/GatewayReports.tsx` | Effective/waiting/健康/Artifact/统一报表 UI；不展示未授权操作 |
| 部署 | `deploy/`、`.env.example`（仅实施对应切片时） | 增加非敏感占位与健康/存储参数；Secret 只放未入库环境文件 |

## 数据模型

### 迁移规划总表

| 规划号（均非现有文件） | 切片 | 逻辑变更 | 实施前强制核查 |
|---|---|---|---|
| `0058_phase7_engine_sessions`（按需） | S7-03 | 复用 Phase 5 已建 `agent_engine_sessions`，仅以可空列/索引扩展通用 Session；Phase 5 未建表时才评审新增 | 重核 head、Phase 5 实际 Session/Execution 字段与 `0055` 是否实施、现有索引及真实 `down_revision`，禁止重复建表 |
| `0059_phase7_execution_waits` | S7-04 | 新增 `agent_execution_waits`；Run 状态允许 waiting；同会话活跃索引纳入 waiting | 重核 head、所有 Run 状态消费者、公开 API/SDK/UI 与审批关联约束 |
| `0060_phase7_engine_usage` | S7-06 | 新增 `engine_usage_records` 与幂等/报表索引 | 重核 head、Phase 6 事件 Outbox、网关事实表和报表数据量 |
| `0061_phase7_fair_scheduling` | S7-07 | 新增 `runtime_tenant_fairness` 与必要队列索引 | 重核 head、现有容量语义、EXPLAIN、多 Worker 锁顺序与迁移在线性 |
| `0062_phase7_skills_artifacts` | S7-08 | 新增 Skill/版本与 Artifact 元数据表及范围/保留索引 | 重核 head、Workspace/Object Store 端口、保留与扫描状态机 |
| `0063_phase7_runtime_profiles` | S7-09 | 新增 Profile/版本/健康表与租户绑定、状态索引 | 重核 head、Registry/Host 实际标识、分布式锁与配置版本模式 |

编号不预留独占权，也不要求连号；若其他需求先占用，应使用当时下一个可用号并同步更新 01~05 文档。所有迁移遵循 expand-only：先加表/可空列/新索引，代码兼容旧形态，flag 验证后再启用。回滚只关 flag/撤代码，不删除历史数据。

### 复用与扩展模型 `agent_engine_sessions`（S7-03）

以下是通用 Session 的目标字段视图，不表示再次建表。若 Phase 5 Stage B 已实施 `0055`，S7-03 必须复用现有记录与兼容读取，只迁移通用能力确实缺少的字段；若未实施，才按本视图评审新表。

| 字段组 | 内容 | 不变量 |
|---|---|---|
| 身份与范围 | `id`、`tenant_id`、`business_id`、`workspace_id`、`conversation_id` | 所有读写带可信范围；原生 Session ID 不可作为跨租户授权凭据 |
| 执行绑定 | `engine_id`、`protocol_id`、`adapter_version`、`provider_session_id` | 同一范围/Adapter 下原生 ID 唯一；Resume 不自动更改三元组 |
| 策略快照 | 当前绑定哈希、Agent/Workspace 绑定、Runtime Profile 引用、metadata schema 版本 | 旧快照用于兼容检查与审计，恢复仍加载当前策略并重新授权 |
| 生命周期 | `status=active|expired|closed|failed`、`expires_at`、创建/更新/关闭时间 | 非 active 或已过期不得恢复；清理不删除必要审计 |

`metadata` 只允许 Adapter 版本化的非 Secret 数据。原生 Token、宿主敏感路径与完整进程环境不得入库。

### 规划模型 `agent_execution_waits`（S7-04）

| 字段组 | 内容 | 不变量 |
|---|---|---|
| 身份与范围 | `id`、`tenant_id`、`business_id`、`workspace_id`、`run_id`、`execution_id` | Run/Execution 必须同范围；同会话互斥包含 waiting |
| 交互 | `kind=approval|input`、Adapter request ID、`approval_id`（可空）、有界请求与 JSON Schema | 同一 Execution/Adapter request ID 只有一个有效等待；不保存 Secret 输入 |
| 决议 | `status=pending|resolved|expired|cancelled`、`revision`、决议类型、请求/决议哈希、幂等键 | 条件更新防并发；相同重试返回原结果，不同决议冲突 |
| 时间 | `expires_at`、创建/决议时间 | 过期或 Run 已终态不得恢复；恢复再次准入和授权 |

审批状态仍归 `approval_requests`；本表只保存关联与 Execution 等待状态。审批决议、等待关闭、Run waiting→queued 与 Outbox 必须在同一数据库事务，避免“已批准但未恢复”或重复恢复。

### 规划模型 `engine_usage_records`（S7-06）

| 字段组 | 内容 | 不变量 |
|---|---|---|
| 关联 | `id`、租户范围、Run/Execution/内部尝试、Engine/Protocol/Adapter 标识 | 关联均来自服务端上下文，客户端不能改写租户或 Execution |
| 幂等与来源 | `source`、`adapter_event_id`、`metric_version`、`usage_kind`、`aggregation_mode` | 租户 + Execution + Adapter 身份 + 事件 ID + 指标版本唯一，避免不同 Execution 的局部事件 ID 冲突；重复上报不重复计数 |
| 数值 | 白名单 `quantities`、单位、发生/接收时间 | 只接受非负有限数值；未知单位隔离，不进入总计 |
| 成本 | 可空 `amount`、`currency`、`cost_status=known|unknown|not_applicable`、定价快照 | 缺失成本不是 0；无汇率不跨币种求和；所有金额标为估算 |

模型网关仍以 `gateway_calls/attempts/costs` 为事实来源。统一报表使用来源视图：网关模型调用只取网关事实；Engine 记录中 `informational` 仅展示，`additive` 才加入 Engine 总额。任何 Engine 汇总若包含已由网关计费的模型用量，必须 informational 或拆出非重叠增量。

### 规划模型 `runtime_tenant_fairness`（S7-07）

| 字段 | 内容 | 不变量 |
|---|---|---|
| `tenant_id` | 公平调度主体 | 不将 business/workspace 标识泄露给其他租户 |
| `last_served_at`、`last_run_id` | 最近一次成功 claim 的公平游标 | 仅在选中 queued→running 的同一事务更新 |
| `revision`、`updated_at` | 并发与审计信息 | 多 Worker 下不能依赖进程内游标 |

配额以短事务内的有效 Run 状态为事实，不用最终可能漂移的进程计数。waiting 与 running 分开计数；全局/租户 queued 与 running 各有硬限额。现有 `queue_capacity`/`tenant_capacity` 的兼容映射必须在 S7-07 设计评审冻结，不能静默改变 flag-off 行为。

### 规划模型 Skill 与 Artifact（S7-08）

| 模型 | 关键字段 | 不变量 |
|---|---|---|
| `agent_skills` | ID、`scope_type=tenant|platform`、所有者范围、名称、来源、权限、状态 | 只有受信发布流程能创建 platform 共享项；租户只能读取被授权共享项 |
| `agent_skill_versions` | Skill ID、版本、内容/对象引用、SHA-256、格式版本、创建时间 | 已发布版本不可变；执行快照固定版本与哈希，挂载只读 |
| `execution_artifacts` | ID、租户范围、Run/Execution、内部对象键、MIME、大小、SHA-256、保留截止、扫描状态 | 对象键不对客户端公开；下载重新授权；过期/扫描拒绝按策略阻断 |

对象内容不进入普通事件或关系表大字段。Artifact Store 通过独立端口支持本地受控卷或 S3 兼容对象存储；大文件流式处理、大小限制和清理失败指标是上线门禁。

### 规划模型 Runtime Profile（S7-09）

| 模型 | 关键字段 | 不变量 |
|---|---|---|
| `runtime_profiles` | ID、租户/平台范围、名称、当前发布版本、状态 | 只有允许范围可引用；人工 disabled 优先于健康恢复 |
| `runtime_profile_versions` | Profile ID、版本、Engine/Protocol/Adapter、资源/超时/egress/Secret 引用、探测策略 | 已发布不可变；不接受客户端任意命令、宿主路径或明文 Secret |
| `runtime_profile_health` | Profile ID/版本、Adapter、健康状态、熔断状态、连续计数、最后成功/失败、open 截止、revision | 状态更新带原子 revision/锁；陈旧数据不健康；半开探测数量有界 |

## 核心流程

### 1. Adapter 注册与契约验证（S7-01）

受信组合根注册元数据 → Registry 校验 Engine/Protocol/版本兼容与配置 Schema → 读取 Declared 能力 → 在 LocalTestAdapter 和候选 Adapter 上运行同一参数化契约 → 仅合格版本进入可解析集合。运行期 Orchestrator 只依赖公共 Adapter 端口；Worker 不 import 厂商包。

可选健康检查是独立运维端口，不向公共 ExecutionRequest 塞入厂商字段。未实现可选高级端口的 Adapter 通过基础契约后仍可执行基本任务。

### 2. 路由、Effective 与安全回退（S7-02）

1. 从已发布 Agent 与租户策略生成 RoutePlan；忽略客户端未授权候选。
2. 对每个候选重新读取版本、健康、Workspace/凭据范围，计算 `Effective = Declared ∩ Available ∩ Policy`。
3. 必需能力不满足则记录原因并评估下一候选；所有候选不合格则启动前失败。
4. 启动后由 Phase 6 副作用账本跟踪流式输出、工具/命令、Session、审批、Artifact 与外部写入。
5. 仅当错误分类可重试且副作用计数为 0、无输出、无 Session 修改、结果不未知时允许下一尝试；每次尝试有独立 ID、序号和不可变快照，Run 终态仍由 Repository 单独提交。

基础降级只移除可选体验，不放宽必需能力、沙箱、网络或授权。健康状态只改变 Available，不参与 Policy 放行。

### 3. Session Resume（S7-03）

API 认证与范围校验 → 锁读 Session 和幂等记录 → 校验 active/未过期及会话、Workspace、Engine 三元组绑定 → 加载当前 Agent 发布版、凭据引用、Runtime Profile 与策略 → 重新计算 Effective → 新建带相同原生 Session 关联的新 Run → 提交后由 Orchestrator 调用 Adapter Resume。

同一幂等键同请求返回原 Run；不同请求体冲突。授权不通过、绑定变化或 Session 不支持时不创建排队记录，不自动切换 Engine。过期清理由独立维护任务执行并记录原因。

### 4. 审批/输入等待与恢复（S7-04）

Engine 发出有界请求 → Orchestrator 校验 Effective 与 Schema → 一个事务创建等待、更新 Run 为 waiting、写事件/Outbox → Worker 结束本次执行并释放 Lease/running 配额 → 操作员通过带 revision 的 API 决议 → 审批端口和等待仓储同事务校验 actor/职责分离/过期/幂等 → 重新授权与配额准入 → Run 转 queued → Worker 用持久等待上下文恢复。

Adapter 必须从检查点/协议游标恢复，不能从副作用节点起点盲重放。若 Engine 不支持安全暂停恢复，则不得声明该能力；可选择保持运行等待的切片外方案不纳入本契约。取消与迟到决议由 Run 终态和 waiting revision 双重拒绝。

### 5. 动态模型选择（S7-05）

AgentConfig 增加可选、类型化 `model_selection`：有序规则、允许 Profile 引用和固定版本约束；固定 `model_profile_id/version` 保持原路径。选择器过滤租户可用、启用、操作匹配、工具匹配、输入限制匹配和固定版本的 Profile → 按第一条匹配规则选择 → 将 Profile ID/版本、规则 ID、理由和目录版本写入 Execution 快照 → 现有 `GatewayChatModel` 使用该固定快照。

网关内部 `fallback_model_ids` 仍属于已发布 Profile 的模型路由，不能越过 Profile 的既有租户/密钥约束。动态选择失败不静默回退到旧固定 Profile，除非 Agent 类型化策略明确声明且该固定项也合格。

### 6. 用量与成本（S7-06）

Adapter 用量事件 → 校验公共 envelope 和事件 ID → 归一化白名单数值、单位、来源与 aggregation_mode → 幂等写入 → 由 Phase 6 Outbox/重试机制保证可恢复 → 报表分别读取网关事实和 Engine additive 记录。

写入失败不撤销已经完成的业务输出，但必须留下可重试任务、指标和告警。报表响应至少包含 `coverage`、`unknown_cost_records`、`currency` 和来源过滤；总计不得将 informational、unknown 或不同币种混为一个金额。成本 API 沿用现有“估算”语义，不生成供应商账单。

### 7. 全局配额与公平 claim（S7-07）

提交：短事务获取固定配额协调锁 → 统计有效全局/租户 queued 与 running → 任一格满则 429 → 插入 queued。等待恢复走相同准入，不绕过队列。

claim：先 reap 失效记录 → 短事务协调全局 running → 每租户取最老可运行 queued 候选 → 按“从未服务优先、最早 last_served 优先、候选 created_at/ID 决胜”选择 → 对选中行条件更新并验证全局/租户 running → 同事务更新公平游标与事件。锁顺序固定为配额协调锁、公平行、Run 行，实际 SQL 与 EXPLAIN 在实施评审确认。

finish/cancel/reap 通过状态变化释放容量，不依赖 Worker 本地计数。协调查询失败 fail closed；不得以跳过限制换取可用性。等待数量独立受限并参与存储容量监控。

### 8. Skill 与 Artifact（S7-08）

Skill：受信发布者上传 → 计算哈希、验证来源/权限/大小 → 发布不可变版本 → Agent 以 ID/版本/哈希引用并进入发布快照 → Workspace Provider 创建执行目录 → Engine Skill Adapter 转成该 Engine 的只读布局 → 启动前复核挂载哈希与路径。任何 symlink/路径逃逸或篡改均失败关闭。

Artifact：Engine 通过受控 Workspace 输出 → Artifact Store 流式写入独立对象存储 → 计算大小/哈希并写元数据 → 按策略执行 Secret 扫描和 `artifact.created` → 下载 API 重新校验租户/Workspace/保留/扫描状态后返回受控内容或短期授权 → 到期任务删除对象并保留必要审计。对象删除失败重试并告警，不把元数据标记为已清理。

### 9. Runtime Profile 健康与熔断（S7-09）

发布不可变 Profile → 路由解析版本并固化资源、egress、Adapter 与 Secret 引用 → 主动无副作用探测或被动启动结果更新带时间戳健康 → closed 下达到连续失败阈值转 open 并记录 open_until → open 候选不参与 Available → 冷却后以全局有界 half_open 探测验证 → 达到成功阈值回 closed，失败重新 open。

探测不携带租户输入、不执行业务工具、不写 Workspace Artifact。手动 disabled 不被探测覆盖；健康 stale/unknown 时按不可用处理。若无健康候选，S7-02 可在无副作用前提下选择其他已授权候选，否则返回明确不可用，不以无限 queued 掩盖故障。

## 配置

`backend/src/agent_platform/core_platform/platform_services/platform_settings/settings.py` 规划新增 FR-11 的九个布尔开关，全部默认 `false`，环境变量自动使用 `AGENT_` 前缀。每个切片只可新增自身需要的有界数值配置；以下默认值是待评审契约而非当前设置。

| 配置项 | 默认/启用条件 | 用途 |
|---|---|---|
| `phase7_session_ttl_seconds` | `86400`；S7-03 评审可收紧 | 新 Session 默认过期上限，不延长已过期 Session |
| `phase7_interaction_ttl_seconds` | `3600`；S7-04 评审可收紧 | 审批/输入等待过期时间上限 |
| `phase7_tenant_waiting_limit` | `100`；S7-04/S7-07 联合评审 | 限制单租户持久等待数量 |
| `phase7_artifact_max_bytes` | `104857600`；S7-08 评审按存储能力调整 | 单 Artifact 硬上限，流式校验 |
| `phase7_artifact_retention_days` | `7`；S7-08 评审按合规调整 | 默认保留期，不能覆盖更严格租户策略 |
| `phase7_health_failure_threshold` | `3`；S7-09 评审 | closed→open 连续失败阈值 |
| `phase7_health_open_seconds` | `30`；S7-09 评审 | open 冷却时长 |
| `phase7_health_stale_seconds` | `60`；S7-09 评审 | 健康结果最大有效龄期 |
| `phase7_health_half_open_probes` | `1`；S7-09 评审 | 全局半开并发探测上限 |

配额数值必须在 S7-07 启用前显式冻结全局/租户 queued、running 与 waiting 限额及其对现有 `queue_capacity`、`tenant_capacity`、`worker_concurrency` 的映射；不得仅以默认值评审代替容量评审。对象存储与 Credential Broker 的 Secret 只通过未入库环境文件提供，`.env.example` 只放占位。

## 模型调用路径（涉及 LLM）

旧配置：Agent 发布快照固定 `model_profile_id/version` → React Provider → `GatewayChatModel` → Catalog 解析同版本 → 现有 Profile 内模型路由/fallback → `gateway_calls/attempts/costs` 记录 usage/cost。

S7-05 开启且配置动态策略：执行前先从允许集合选出固定 Profile 快照，再进入完全相同的网关路径；不得绕开 Gateway Governance、凭据、工具能力检查或版本解析。非 React Engine 的原生模型调用只有通过 Adapter 用量契约上报，并标记与网关记录是否重叠。

模型 fallback 与 Engine fallback 不共享“可重试”结论：前者沿用现有网关仅在未流式输出时的模型错误规则，后者还必须满足 Execution 副作用与策略条件。

## 测试方案

| 层 | 用例 |
|---|---|
| 单测 | P7-UT-01~30：注册/兼容、路由/副作用、Effective、Session、等待、模型、usage/cost、配额/公平、Skill/Artifact、健康与开关 |
| 集成 | P7-IT-01~30：公共 Adapter 契约、PostgreSQL 多 Worker、Worker 重启、审批恢复、真实网关快照、对象存储、熔断与全关回归 |
| 通用 | P7-CM-01~12：迁移 head/在线性、配置、i18n、租户、Secret、依赖边界、观测、性能证据与逐片发布门禁 |
| 回归 | 现有 `test_runtime_engine.py`、`test_runtime_postgres.py`、`test_runtime_scope.py`、`test_runtime_availability.py`、模型网关/审批/Workspace/迁移套件及 Phase 0~6 新增回归 |

详细步骤、预期和溯源见 `04-test-plan.md`。只执行当前已评审切片的适用用例，但每个用例必须明确结果；未实施或未运行不能写“通过”。Phase 0 基线缺失时，比较型指标与全关 diff 门禁不得判通过。

## 上线与回滚

- **逐片评审**：S7-01~09 各自提交范围/非目标、依赖证据、文件清单、迁移（如有）、契约/集成测试、安全评审、灰度租户、监控阈值和回滚演练。统一文档不是一次性上线许可。
- **小 PR 顺序**：先 Phase 0~6 依赖，再选片；迁移 expand-only 与代码兼容可先合入但 flag 保持关闭。禁止在一个 PR 中同时引入多个厂商 Adapter、核心调度改写和全部持久化模型。
- **灰度**：仅在专用测试租户/LocalTestAdapter 验证后进入受控租户；真实厂商集成若另行批准，也必须通过同一公共契约，不能替代平台基础验收。
- **回滚**：先关对应 flag 停止新路径；进行中的基本 Run 按 Phase 0~6 终态规则收尾，Session/waiting 不自动恢复，Artifact/用量保留授权读取与清理。回滚代码仍须能读取新表/新状态，禁止为回滚执行破坏性 down migration。
- **再启用**：重新核查当前策略、Session/等待过期、健康新鲜度、配额与积压；不得把停用期间旧授权快照直接当作有效。
- **完成定义**：单片上线只表示该片适用 A/C 通过；Phase 7 整体不得宣称完成，除非所有被批准纳入最终范围的切片均有独立验收报告且架构第 22 节相关项有证据。
