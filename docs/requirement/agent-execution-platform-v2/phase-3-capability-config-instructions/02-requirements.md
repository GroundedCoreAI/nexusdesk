# Phase 3 · 能力、配置与指令 — 需求文档

> 状态：待评审（未开始实施）
> 创建：2026-11-02
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
| 输出 | 缺省 `(engine_id=react, protocol_id=native, adapter_version=v1)` 的规范化执行配置；历史原始 JSONB 保持不变 |
| 执行方式 | 同步纯函数映射；执行与配置校验共用同一兼容层，不各写一套默认逻辑 |
| 失败处理 | 非法旧字段按既有规则拒绝并记录稳定错误码；不得为兼容而删除未知字段或放宽 `extra=forbid` |
| 溯源 | G1；US-1 |

### FR-2 类型化 Engine 选择与专属配置

| 项 | 说明 |
|---|---|
| 触发时机 | Agent 草稿创建/更新、发布、回滚、快照解析及 Run admission |
| 输入 | 显式 `engine` 三元组、注册表提供的配置 schema、公共字段与 Engine 专属字段 |
| 输出 | 通过校验的不可变执行配置；React 新规范使用 `react.model_profile_id/model_profile_version/max_model_rounds`，旧根字段作为兼容别名 |
| 执行方式 | Pydantic 严格校验、禁止额外字段；由 Registry 精确解析 Adapter，禁止 latest 和任意配置字典 |
| 失败处理 | 未知/不兼容三元组、缺失必需字段、类型错误及别名异值均拒绝；不可用配置不得发布或启动 |
| 溯源 | G1；US-1、US-2 |

### FR-3 Declared 与 Available 能力解析

| 项 | 说明 |
|---|---|
| 触发时机 | Adapter 注册/健康状态变化时缓存声明；Run 编排与能力预览时解析 Available |
| 输入 | 受信任 Adapter 的 `EngineCapabilities`、Adapter/Protocol 版本、部署探测与环境约束 |
| 输出 | Declared 快照及逐能力 Available 布尔值、原因码、探测版本/时间；Available 不得超出 Declared |
| 执行方式 | 声明只读；部署探测有超时和缓存，热路径不启动外部 Engine；`workspace_required=true` 而无 Workspace 时判不可用 |
| 失败处理 | 探测失败、超时或版本未知均按不可用/明确拒绝处理，不默认放开；记录不含秘密的原因码 |
| 溯源 | G2；US-2、US-3 |

### FR-4 Policy 与 Effective 能力解析

| 项 | 说明 |
|---|---|
| 触发时机 | Available 计算完成后、ExecutionRequest 构造前；UI 能力预览使用同一解析器 |
| 输入 | Available、平台能力上限、可信租户策略、已发布 Agent 的 `disabled_capabilities`、可信 Execution 上下文 |
| 输出 | 逐能力策略决定、来源/版本/原因码和最终 Effective；任何一层为 false 后不得重新变为 true |
| 执行方式 | 服务端单调收窄；Agent/Execution 只能禁用或收紧，客户端 Run 请求不提供策略或 Effective 输入 |
| 失败处理 | 策略缺失按既有最小权限默认值处理，策略版本不明或必需能力被拒绝则阻止启动；不得跨 Engine 自动回退 |
| 溯源 | G2；US-3、US-6 |

### FR-5 客户端输入与公共能力视图防提权

| 项 | 说明 |
|---|---|
| 触发时机 | Run API、Agent API、能力预览/API 序列化及 ExecutionRequest 构造 |
| 输入 | 可能含伪造 `declared/available/effective_capabilities`、策略版本、宿主字段或越权 Engine 配置的请求 |
| 输出 | 严格拒绝未知字段；公共视图仅返回当前主体可见的 Effective 与必要原因，不返回内部探测/策略秘密 |
| 执行方式 | tenant/actor 来自认证上下文；ExecutionRequest 完全由服务端快照构造，禁止客户端对象直接透传 |
| 失败处理 | 提权尝试返回 4xx/稳定领域错误并记录安全审计；不得通过忽略伪造字段后按其值执行 |
| 溯源 | G2；US-3 |

### FR-6 执行配置、能力与策略快照

| 项 | 说明 |
|---|---|
| 触发时机 | Run 创建/编排解析完成后、Adapter `start` 前；历史 Run 查询与审计时读取 |
| 输入 | 规范化执行配置、Declared/Available/Effective、策略决定与版本、Agent 发布版本和 Instruction Provider 标识 |
| 输出 | `runtime_runs` 中不可变 JSONB 快照及可关联的 Run ID；Engine 三元组包含在执行配置快照内 |
| 执行方式 | 同一持久化边界写入后再启动；快照有 schema 版本、大小上限和敏感字段 denylist，公开 API 不直接暴露 |
| 失败处理 | 序列化、大小或必需字段校验失败则 Run 失败且不启动 Adapter；历史空值表示 Phase 3 前记录，不伪造回填 |
| 溯源 | G4；US-5 |

### FR-7 Instruction Provider 与 React 兼容

| 项 | 说明 |
|---|---|
| 触发时机 | Orchestrator 已获取历史、Summary/Memory 渲染结果并准备 Adapter 输入时 |
| 输入 | System Prompt、回复语言规则、Conversation Context、已渲染 Summary/Memory、可选 Skill/Workspace 上下文占位 |
| 输出 | 带 provider ID/版本的 Engine 原生指令；React 保持 System → Summary → Memory → kept history → user 的既有顺序 |
| 执行方式 | Provider 只负责格式适配；MemoryInjection 继续负责读取、开关、预算和文案，Provider 不查询记忆库、不重复注入 |
| 失败处理 | 未知 Provider 或渲染契约错误阻止启动；Summary/Memory 为空或开关关闭时沿用既有降级，不生成空消息 |
| 溯源 | G3；US-4 |

### FR-8 配置与能力展示、审计和回滚

| 项 | 说明 |
|---|---|
| 触发时机 | 管理员编辑/预览 Agent、审计人员查看 Run、运维切换 Phase 3 开关或回滚版本 |
| 输入 | 类型化草稿、只读 Effective 预览、快照、部署开关与审计事件 |
| 输出 | i18n 表单/错误、不可编辑的 Effective 视图、配置/策略版本审计；关闭开关后恢复 Phase 2 React 行为 |
| 执行方式 | 所有用户可见文案走 i18n；回滚不删快照、不批量改 Agent JSONB；非 React 在开关关闭时明确拒绝而非改用 React |
| 失败处理 | 预览探测失败显示不可用而非可用；开关关闭且存在非 React Run 时返回 `execution_phase3_disabled`；审计不得含秘密 |
| 溯源 | G1、G2、G4；US-1、US-3、US-5、US-6 |

### FR-9 配置开关

| 配置项 | 层级 | 默认值 | 说明 |
|---|---|---|---|
| `execution_phase3_enabled` | 全局 settings | `false` | Phase 3 总开关；关闭仅允许 Phase 2 React 路径，禁止非 React 静默降级 |
| `execution_capability_policy_version` | 全局 settings / 可信 Policy Provider | `v1` | 服务端默认策略版本；客户端不可设置 |
| `execution_capability_probe_timeout_seconds` | 全局 settings | `2.0` | 单次有界部署探测超时，超时可按不可用处理 |
| `execution_capability_probe_cache_seconds` | 全局 settings | `30` | 可用性结果缓存时长；声明与策略变更须使相关缓存失效 |
| `execution_snapshot_max_bytes` | 全局 settings | `65536` | 单类快照序列化上限，超限拒绝启动 |
| `engine` | AgentConfig JSONB | `{engine_id:react,protocol_id:native,adapter_version:v1}` | 缺省仅由兼容层补齐；新值必须精确注册 |
| `react` | AgentConfig JSONB | 从旧根字段派生 | React 类型化配置；与旧别名异值时拒绝 |
| `disabled_capabilities` | 已发布 AgentConfig / 可信 Agent 策略 | `[]` | 只能进一步禁用 Available 能力，不能授予或覆盖平台/租户策略 |

## 非功能需求

- **性能**：注册表、schema 与可信策略优先缓存；解析 p95 增量目标不超过 50ms，任何探测均有超时，不在请求热路径调用外部 Engine。
- **兼容**：旧草稿、发布快照、模型/工具校验、Summary/Memory 开关和公开 Run/SSE 行为保持；历史快照为空有明确语义。
- **多租户**：Agent、策略与 Run 均按认证 tenant 和业务/workspace scope 查询；跨租户配置、能力预览、快照与审计不可达。
- **安全**：能力不是授权；快照与日志不得包含 API Key、Token、原始客户记忆、凭据引用明文或内部宿主路径。
- **可审计**：快照含 schema/provider/policy 版本和逐能力原因码；决策可重放但不要求重跑有副作用的 Engine。
- **可回滚**：总开关无需数据库 downgrade 即可回退；关闭新路径不得删除或重写历史数据，不得让非 React 请求换 Engine 执行。

## 验收标准

| # | 场景 | 预期 | 溯源 |
|---|---|---|---|
| AC-1 | 加载 Phase 0 的旧草稿、发布快照与缺省/边界样本并执行 React | 全部合法样本默认 `react/native/v1`，模型/工具/摘要/记忆行为不变，历史 JSONB 未被改写 | FR-1；G1；US-1 |
| AC-2 | 保存合法 `react` 配置，再提交类型错误、额外字段、未知三元组及新旧别名异值 | 合法配置通过并精确解析；非法配置全部稳定拒绝，不进入发布或 Adapter 启动 | FR-2；G1；US-2 |
| AC-3 | 构造 Adapter 声明支持但部署缺失/版本不兼容/探测超时，以及 `workspace_required` 无 Workspace | Available 逐项为 false 且有原因码；Available 永不超出 Declared，必需能力缺失时拒绝启动 | FR-3；G2；US-2、US-3 |
| AC-4 | 分别在平台、租户、Agent、Execution 层禁用一项能力，再尝试由下层重新启用 | Effective 始终为 false；快照记录各层来源、版本与原因，单调收窄无例外 | FR-4；G2；US-3 |
| AC-5 | 在 Run/Agent/API 请求中伪造 Declared、Available、Effective、策略版本和宿主内部字段，并尝试跨租户预览 | 请求被拒绝或按严格 schema 判定无效，提权成功数为 0；跨租户不可达且有安全审计 | FR-5；G2；US-3 |
| AC-6 | 对完成、失败、取消、超时 Run 检查快照，并构造超限/含秘密的待快照对象 | 正常 Run 在 Adapter 启动前快照完整且不可变；非法快照不启动；历史空值不回填，公开响应不泄露内部内容 | FR-6；G4；US-5 |
| AC-7 | 对空态、开关关闭、Summary、Memory、Summary+Memory 及历史截断场景比较 React 消息 | 顺序、文案、开关、budget 与 Phase 0 基线 diff 为 0，不重复注入、不生成空消息 | FR-7；G3；US-4 |
| AC-8 | 用测试 Engine Provider 渲染与 React 不同的指令格式，并注入相同 Summary/Memory 输入 | Engine 格式可独立变化，业务渲染结果只计算一次；不把原生格式强行转换为 ReAct 消息 | FR-7；G3；US-4 |
| AC-9 | 管理员编辑配置并查看能力预览，随后改变平台/租户策略 | 表单和错误全部 i18n；Effective 只读且随服务端重算更新，UI 无提权入口或内部快照泄露 | FR-4、FR-5、FR-8；G1、G2；US-1、US-3 |
| AC-10 | 开启再关闭 `execution_phase3_enabled`，分别运行旧 React 与非 React 配置，并检查历史快照 | 旧 React 回到 Phase 2 行为；非 React 明确失败且不自动降级；历史快照仍可读取，无需迁移回滚 | FR-8、FR-9；G4；US-6 |
| AC-11 | 从 `0052` 基线升级规划迁移，验证旧行/新行、并发读写及配对 downgrade（仅 disposable 库） | 仅新增五个可空快照列；旧行为不受影响；实施时已重验真实 head/down_revision，未修改历史迁移 | FR-6；G1、G4；US-5、US-6 |
