# Phase 3 · 能力、配置与指令 — 需求文档

> 状态：设计已校准（未开始实施；保留 G1–G4、US-1～US-6、FR-1～FR-9、AC-1～AC-11）
> 创建：2026-11-02
> 修订：2026-11-13（FR-9 表新增 6 项 capability settings 落点，对应 R-18/R-19）
> 修订：2026-11-12（代码现状、预览契约、启动屏障、双开关与迁移）
> 依据：`01-business-goals.md`（G1–G4）、架构文档第 5、6、11、14、17 节 Phase 3

## 用户故事

**US-1（租户管理员）**：作为租户管理员，我希望旧 Agent 无需修改即可继续运行，并能为新 Agent 选择受支持的 Engine/Protocol，以便平滑演进而非批量迁移。

**US-2（平台研发）**：作为平台研发，我希望每种 Engine 配置都有严格类型和版本化解析，以便新增 Engine 时不把自由字典与条件分支扩散到公共代码。

**US-3（安全管理员）**：作为安全管理员，我希望 Effective 能力只能由服务端根据环境与策略计算，以便 Adapter 声明或客户端请求不能形成授权。

**US-4（执行平台研发）**：作为执行平台研发，我希望指令按 Engine 渲染但复用 Summary/Memory 业务逻辑，以便扩展 Engine 时保持上下文行为一致。

**US-5（QA/审计人员）**：作为 QA 或审计人员，我希望读取一次 Run 的配置、能力和策略快照，以便重放允许/拒绝决策并定位版本差异。

**US-6（运维人员）**：作为运维人员，我希望 Phase 3 能整体关闭且非 React 配置不会静默降级，以便在故障时安全回滚。

## 功能需求

### FR-1 旧配置兼容与规范化

| 项 | 说明 |
|---|---|
| 触发时机 | 加载草稿、已发布版本、执行快照或 diff 时；用户保存/发布时 |
| 输入 | 现有 JSONB 配置，可能缺少 `engine` 与 `react`，仅含旧根字段 |
| 输出 | 缺省 `(react,native,v1)` 的规范化 `ExecutionConfig`；历史原始 JSONB 保持不变 |
| 执行方式 | 同步纯函数映射，草稿校验、发布、预览、执行与 diff 共用；只在内存规范化，不因 GET/正常读取 UPDATE |
| 失败处理 | 非法旧字段按既有规则拒绝并记录稳定错误码；不得删除未知字段或放宽 `extra=forbid` |
| 溯源 | G1；US-1 |

### FR-2 类型化 Engine 选择与专属配置

| 项 | 说明 |
|---|---|
| 触发时机 | Agent 草稿创建/更新、发布、回滚、快照解析、预览及 Run admission |
| 输入 | 显式 `engine` 三元组、Registry 配置 schema、公共字段与 Engine 专属字段 |
| 输出 | 严格、不可变的 `ExecutionConfig`；React 新规范使用 `react.model_profile_id/model_profile_version/max_model_rounds`，旧根字段作为兼容别名 |
| 执行方式 | Pydantic 严格校验；Registry 以精确三元组取 metadata 校验草稿，禁止 latest 和任意字典；执行时才 `resolve` 新 Adapter |
| 失败处理 | 未知/不兼容三元组、缺字段、类型错误及别名异值均拒绝；不可用配置不得发布或启动，不自动换 Engine |
| 溯源 | G1；US-1、US-2 |

### FR-3 Declared 与 Available 能力解析

| 项 | 说明 |
|---|---|
| 触发时机 | 注册元数据定义 Declared；Run 编排与能力预览读取可信部署探测的 Available |
| 输入 | 受信任注册声明、精确版本、部署 probe 与 Workspace 可用代次 |
| 输出 | Declared 快照及逐项 Available 布尔值、稳定原因码、probe 版本/时间；Available 不得超出 Declared |
| 执行方式 | 声明只读；probe 超时、有界缓存与失效由服务端控制，热路径不启动外部 Engine；无 Workspace 时 `workspace_required=true` 不可用 |
| 失败处理 | probe 缺失、失败、超时、过期或版本未知均不可用/明确拒绝，不默认放开；不泄露原始异常或秘密 |
| 溯源 | G2；US-2、US-3 |

### FR-4 Policy 与 Effective 能力解析

| 项 | 说明 |
|---|---|
| 触发时机 | Available 后、ExecutionRequest 构造前；UI 预览与 Run 共用同一 resolver |
| 输入 | Available、平台 ceiling、可信租户策略、已发布 Agent 的 `disabled_capabilities`、可信 Execution 限制 |
| 输出 | 逐项 Policy 决定、来源/版本/原因码及最终 Effective；任一层 false 后不得恢复 true |
| 执行方式 | 服务端单调收窄，默认最小权限；Agent/Execution 只能禁用；客户端 Run 请求无 Policy/Effective 输入 |
| 失败处理 | 未知能力或策略版本失败关闭；缺失/不可信策略按最小权限，必需能力被拒绝则阻止启动，不跨 Engine 回退 |
| 溯源 | G2；US-3、US-6 |

### FR-5 客户端输入与公共能力视图防提权

| 项 | 说明 |
|---|---|
| 触发时机 | Run API、Agent API、`POST /api/v1/agents/execution-preview` 及 ExecutionRequest 构造 |
| 输入 | 可能伪造 `declared/available/effective/effective_capabilities`、policy 版本、宿主字段或越权配置的请求 |
| 输出 | 严格拒绝未知/伪造字段；预览仅返回 Engine 身份、安全 schema metadata 与 `{name,effective,reason_code}`，不返回内部快照、probe/policy 原文或路径 |
| 执行方式 | tenant/actor/business/workspace 来自认证上下文；`agent_id` 可选，提供时按同一 scope 加载，未保存草稿也可预览；ExecutionRequest 完全由服务端构造 |
| 失败处理 | schema 错误沿用 422，scope 内找不到 Agent 沿用 404；提权尝试有稳定领域错误和安全审计；预览不建 Run、不实例化 Adapter、不授权后续执行 |
| 溯源 | G2；US-3 |

### FR-6 执行配置、能力与策略快照

| 项 | 说明 |
|---|---|
| 触发时机 | Phase 3 编排解析完成后、`Adapter.start` 前；历史审计只读 |
| 输入 | 规范化配置、Declared、Available、Effective、Policy 决定及 Agent/Provider 版本 |
| 输出 | `runtime_runs` 五个可空 JSONB 列，分别为 execution config、Declared、Available、Effective、execution policy；Engine 三元组含于配置快照 |
| 执行方式 | 五类 DTO 版本化、逐类大小限制、递归 denylist，同一 DB commit 一次性写入后才开始 Adapter/Runtime/工具/模型副作用；完成/失败/取消/超时均不改写 |
| 失败处理 | 序列化、敏感扫描、大小或 DB commit 失败均使 Run 失败且 `Adapter.start=0`；公开 `run.started` 仍由既有 claim 先发；历史 NULL 表示 Phase 3 前记录，不回填 |
| 溯源 | G4；US-5 |

### FR-7 Instruction Provider 与 React 兼容

| 项 | 说明 |
|---|---|
| 触发时机 | Orchestrator 取得历史与已渲染 Summary/Memory 后、React runner 创建前 |
| 输入 | `InstructionInput`：已计算 system prompt、回复语言结果、会话历史/当前输入、已渲染 Summary/Memory、受控 Engine 占位 |
| 输出 | provider ID/version 与 Engine 原生指令；React 严格保持 System → Summary → Memory → kept history → current user |
| 执行方式 | 系统提示和 Summary/Memory 业务渲染各一次；Provider 仅格式适配，不查 Memory、不重复拼装；ReactAdapter 在准备完成后才创建 runner |
| 失败处理 | 未知 Provider 或渲染错误阻止 Adapter.start；空值/开关关闭沿用既有降级，不生成空消息，不改双 emit/ack/Outcome |
| 溯源 | G3；US-4 |

### FR-8 配置与能力展示、审计和回滚

| 项 | 说明 |
|---|---|
| 触发时机 | 管理员编辑/预览 Agent、审计、开关切换或应用回滚 |
| 输入 | 类型化草稿、只读 Effective、私有快照、双开关与审计事件 |
| 输出 | 在既有 React 19 + antd v6 AgentsPage 中适度拆件；`zh-CN/zh-TW/en/hi` 完整文案；Effective 只读，disabled 只收窄 |
| 执行方式 | OpenAPI 沿用现有约定；回滚不删快照、不批量改 JSONB；Phase 3 off 精确保留部署原 Phase 2 on/off 路径 |
| 失败处理 | probe 失败显示不可用及稳定原因；任何 off 状态非 React 均 `execution_phase3_disabled`；preview 不创建/授权 Run，审计无秘密 |
| 溯源 | G1、G2、G4；US-1、US-3、US-5、US-6 |

### FR-9 配置开关

| 配置项 | 层级 | 默认值 | 说明 |
|---|---|---|---|
| `execution_phase3_enabled` | 全局 settings | `false` | Phase 3 总开关；与 `execution_orchestrator_enabled` 组成四态矩阵 |
| `execution_capability_policy_version` | 全局 settings / 可信 Policy Provider | `v1` | 默认策略版本，客户端不可设置 |
| `execution_capability_probe_timeout_seconds` | 全局 settings | `2.0` | 有界部署 probe 超时 |
| `execution_capability_probe_cache_seconds` | 全局 settings | `30` | probe 结果缓存；身份/声明/probe/Workspace 代次变化失效 |
| `execution_capability_policy_cache_seconds` | 全局 settings | `30` | Policy/Effective 缓存；租户/Agent/版本/策略修订/disabled/restriction 摘要变化失效 |
| `execution_snapshot_max_bytes` | 全局 settings | `65536` | **每一类**快照的 UTF-8 JSON 序列化上限，超限不启动 |
| `execution_capability_policy_timeout_seconds` | 全局 settings | `2.0` | 有界策略源等待（R-18），`gt=0, le=10`，与 probe 同上限 |
| `execution_capability_probe_max_concurrency` | 全局 settings | `4` | 单进程并发 probe 上限（R-18），`ge=1, le=32` |
| `execution_capability_cache_capacity` | 全局 settings | `512` | Available 与 Policy 两把 LRU 的条目上限（同一值，R-18），`ge=16, le=100000` |
| `execution_capability_cache_retry_seconds` | 全局 settings | `5.0` | 缓存错误重试与 warmer 失败退避的同源间隔（R-18），`gt=0, le=60` |
| `execution_capability_warm_refresh_seconds` | 全局 settings | `10.0` | 受控后台 warmer 刷新周期（R-18）；`gt=0, le=300`，Phase 3 on 时必须小于两个 cache TTL |
| `execution_capability_deployment_identity` | 全局 settings | `default` | Available/Policy key 的部署身份标签（R-18），`Slug` 模式，同一逻辑部署各进程必须一致 |
| `engine` | AgentConfig JSONB | `{react,native,v1}` | 缺省由兼容层补齐；新值精确注册 |
| `react` | AgentConfig JSONB | 从旧根字段派生 | 类型化配置；与旧别名异值拒绝 |
| `disabled_capabilities` | 已发布 AgentConfig / 可信 Agent 策略 | `[]` | 只能禁用，不能授权或覆盖 ceiling/tenant policy |

上述 `execution_capability_*` 新增字段均非秘密、默认安全；`*_cache_seconds` 与 `*_retry/refresh_seconds` 下界为严格大于 0（R-19，不提供"缓存 TTL=0/永不过期"形态）；`execution_phase3_enabled=true` 时 settings 层校验 `warm_refresh < min(probe, policy TTL)`，违反即启动失败关闭。

双开关语义：

| `execution_phase3_enabled` | `execution_orchestrator_enabled` | 行为 |
|---|---|---|
| false | false | 精确原 Phase 2 legacy Runtime 路径，无 Phase 3 probe/快照 |
| false | true | 精确原 Phase 2 Orchestrator React 路径，无 Phase 3 probe/快照 |
| true | false | 配置不可用，失败关闭；不得静默走 legacy React |
| true | true | Phase 3 解析、快照、Provider 与 Orchestrator 路径 |

任一 Phase 3-off 状态遇非 React 均明确 `execution_phase3_disabled`，React Adapter 调用为 0。

## 非功能需求

- **性能**：真实 resolver/admission 路径缓存预热后至少 100 个有效配对样本，p95 增量 ≤50ms；probe 不在同步热路径无界阻塞。
- **兼容**：旧草稿/发布快照、模型/工具校验、Summary/Memory、公开 Run/SSE 与 `run.started` 顺序保持；历史 NULL 语义明确。
- **多租户**：Agent、策略、Run、预览均按认证 tenant 和业务/workspace scope 查询，跨域保持既有 not-found。
- **安全**：快照递归拒绝秘密、原始客户记忆和宿主细节；默认最小权限，preview/Adapter 声明均不是授权源。
- **可审计**：私有快照含 schema/provider/policy 版本和原因码；决策重放只读，公开响应白名单。
- **可回滚**：关闭新路径无需 downgrade，不删除/重写历史，不使非 React 换 Engine。

## 验收标准

| # | 场景 | 预期 | 溯源 |
|---|---|---|---|
| AC-1 | 加载 Phase 0 旧草稿、发布快照与缺省/边界样本并执行 React | 合法样本默认 `react/native/v1`，模型/工具/Summary/Memory 不变，历史 JSONB 不改写，canonical diff 无默认噪声 | FR-1；G1；US-1 |
| AC-2 | 保存合法 `react`，再提交类型错误、额外字段、未知三元组及别名异值 | 合法配置通过；非法配置稳定拒绝；metadata 校验不实例化 Adapter | FR-2；G1；US-2 |
| AC-3 | 声明支持但部署缺失/版本不兼容/probe 超时，以及无 Workspace | Available=false 且有原因码；不超出 Declared，必需能力缺失阻止启动 | FR-3；G2；US-2、US-3 |
| AC-4 | 各层禁用后由下层重新启用 | Effective 始终 false；快照记录来源、版本与原因，单调收窄 | FR-4；G2；US-3 |
| AC-5 | Run/Agent/预览伪造各层字段并跨租户预览 | 严格拒绝、提权为 0；跨租户不可达且有安全审计；预览不建 Run | FR-5；G2；US-3 |
| AC-6 | 检查四类终态 Run 快照，构造超限/嵌套秘密及 DB 失败 | Adapter.start 前五快照一次提交且不可变；失败时 start=0；历史 NULL 不回填，公开不泄露 | FR-6；G4；US-5 |
| AC-7 | 比较空态、开关、Summary、Memory、组合与截断 React 消息 | 顺序、文案、budget 与基线 diff 为 0，无重复/空消息，业务渲染一次 | FR-7；G3；US-4 |
| AC-8 | 测试 Provider 渲染不同格式并注入相同输入 | 格式独立、业务渲染一次，不强制 ReAct 化，不另做 Memory 渲染 | FR-7；G3；US-4 |
| AC-9 | 编辑预览后改变策略，并覆盖四语言与 M1–M3 | Effective 只读且服务端重算，disabled 只收窄；四语言完整，无提权/内部快照 | FR-4、FR-5、FR-8；G1、G2；US-1、US-3 |
| AC-10 | 遍历双开关矩阵并运行 React/非 React，检查历史快照 | off 保留部署原 Phase 2 路径；on+orchestrator off 失败关闭；非 React 不静默降级；历史可读 | FR-8、FR-9；G4；US-6 |
| AC-11 | 从规划前驱升级 `0058_agent_execution_metadata`，验证旧/新行、并发及 disposable downgrade | 仅新增五个可空列；实施前动态重验 head/down_revision，当前前驱 `0057_industry_pack_runtime`，不改历史迁移 | FR-6；G1、G4；US-5、US-6 |
