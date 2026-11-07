# Phase 3 · 能力、配置与指令 — 技术落地文档

> 状态：待评审（未开始实施；以下模块与迁移均为规划）
> 创建：2026-11-02
> 依据：`01-business-goals.md`（G1–G4）、`02-requirements.md`（FR-1–FR-9、AC-1–AC-11）、架构文档第 3、5、6、11、14–17、21 节
> 现状核查：2026-11-02 对 `integration` 工作树；迁移 head 为 `0052_memory_tasks_tenant_index`

## 1. 现状映射与设计裁定

| 现状证据 | 核查结论 | 本阶段裁定 |
|---|---|---|
| `business_capabilities/agent_config/service.py` | `AgentConfig(extra=forbid)` 使用现有 JSONB 草稿/发布链路，没有 Engine 字段 | 扩展同一模型与 JSONB，不建 Agent 配置表、不改历史快照；增加单一兼容规范化入口 |
| `applications/platform_runtime/runtime_factory.py` | `for_run()` 固定构造 `RuntimeEngine`，`effective()` 拼接系统提示与语言规则 | Phase 2 后改由 Orchestrator/Registry 提供 Adapter；React 有效提示词只计算一次并交给 Instruction Provider |
| `core_platform/agent_runtime/worker.py`、`engine.py` | Worker 取得 Summary/Memory 渲染文本，Engine 固定 SystemMessage 顺序 | 保留 MemoryInjection 业务职责；Provider 只替换格式适配，不移动记忆读取、预算或完成后的写回逻辑 |
| `business_capabilities/memory/injection.py` | 已有 Summary/Memory 开关、渲染、降级和注入日志 | 原样复用其结果，禁止 React/测试 Provider 再实现一套文案或查询 |
| `core_platform/agent_runtime/repository.py`、迁移 `0001/0002` | Run 有 `config` JSONB；Agent 草稿与版本分别为 `agents.draft`、`agent_versions.config` | Run 增加独立决策快照列；AgentConfig 仍在原 JSONB 中，避免混淆输入快照与解析决策 |
| `platform_settings/settings.py` | `AGENT_` 前缀、Pydantic Settings、环境变量覆盖是既有先例 | 新开关沿用该方式；秘密仍只进独立环境/凭据设施，不写入快照或示例配置 |
| Phase 1–2 规划 | Registry、Capabilities、ExecutionRequest、Orchestrator 是前置组件，当前工作树尚不存在 | 本阶段只基于其已验收契约接线；若前置契约变化，先修订本文并评审，不在 Worker 增加 Engine 分支 |

## 2. 改动总览

| 层 | 文件 | 改动 |
|---|---|---|
| 迁移 | `backend/migrations/versions/0053_agent_execution_metadata.py` | 规划新增五个可空 Run 决策快照列；实施前重验 head/down_revision |
| 配置模型 | `backend/src/agent_platform/core_platform/agent_execution/config/execution_config.py` | 定义版本化 ExecutionConfig、EngineSelector、ReactConfig 与严格校验 |
| 兼容层 | `backend/src/agent_platform/core_platform/agent_execution/config/legacy_config.py` | 旧根字段映射、默认值、别名冲突检测；无副作用 |
| 能力 | `backend/src/agent_platform/core_platform/agent_execution/capability/capability_resolver.py` | Declared/Available/Policy/Effective 解析与缓存失效 |
| 策略 | `backend/src/agent_platform/core_platform/agent_execution/capability/capability_policy.py` | 可信 Policy Provider、逐层收窄、来源/原因快照 |
| 指令 | `backend/src/agent_platform/core_platform/agent_execution/instructions/instruction_provider.py` | Provider 契约、InstructionInput/RenderedInstructions 与版本标识 |
| React 指令 | `backend/src/agent_platform/core_platform/agent_execution/instructions/react_instruction_provider.py` | 保持现有 React 消息顺序与文案 |
| 渲染 | `backend/src/agent_platform/core_platform/agent_execution/instructions/instruction_renderer.py` | 公共片段装配与空态规则，不读取 Memory Store |
| 编排 | `backend/src/agent_platform/core_platform/agent_execution/orchestration/orchestrator.py` | 配置→能力→快照→指令→Adapter 启动顺序 |
| 上下文 | `backend/src/agent_platform/core_platform/agent_execution/orchestration/execution_context.py` | 仅服务端构造的 tenant/actor/policy/Execution 上下文 |
| Agent 配置 | `backend/src/agent_platform/business_capabilities/agent_config/service.py` | 接入规范化配置、Registry schema 校验、发布/回滚/预览兼容 |
| Run 持久化 | `backend/src/agent_platform/core_platform/agent_runtime/repository.py` | Adapter 启动前写入五个快照；历史空值与内部读取 |
| 组合 | `backend/src/agent_platform/applications/platform_runtime/runtime_composition.py` | 注册配置/能力/策略/Instruction Provider，沿用组合根注入 |
| 配置 | `backend/src/agent_platform/core_platform/platform_services/platform_settings/settings.py` | 增加 FR-9 的开关、探测与快照限制 |
| 前端 | `frontend/src/shared/api/client.ts`、`frontend/src/features/agents/AgentsPage.tsx` | 类型化 Engine 配置、只读 Effective 预览与错误展示 |
| i18n | `frontend/src/i18n/index.ts` 及实际拆分的语言资源 | 所有新增用户文案中英及现有支持语言资源，不硬编码 |
| 部署示例 | `deploy/production/.env.example` | 仅添加非秘密开关占位与说明，默认关闭 Phase 3 |
| 测试 | `backend/tests/test_agent_execution_config.py`、`test_capability_resolver.py`、`test_instruction_providers.py`、`test_agent_execution_metadata_migrations.py` | 规划新增确定性与迁移测试，具体用例见 04 |

## 3. 数据模型

### 3.1 迁移 `0053_agent_execution_metadata.py`

> 规划编号：以当前 head `0052_memory_tasks_tenant_index` 为直接前驱。实施前若 head 已变化，必须创建新的正确链接并同步修订文档；禁止改历史迁移。

| 表 | 新列 | 类型/空值 | 用途 |
|---|---|---|---|
| `runtime_runs` | `execution_config_snapshot` | JSONB NULL | 规范化配置、Agent 版本、Engine 三元组、Instruction Provider 版本 |
| `runtime_runs` | `declared_capabilities_snapshot` | JSONB NULL | 受信任 Adapter 声明与契约版本 |
| `runtime_runs` | `available_capabilities_snapshot` | JSONB NULL | 环境判定、原因码、探测版本与时间 |
| `runtime_runs` | `effective_capabilities_snapshot` | JSONB NULL | 最终逐能力布尔值与解析摘要 |
| `runtime_runs` | `execution_policy_snapshot` | JSONB NULL | 策略版本、来源及逐层允许/拒绝决定 |

设计要点：

- 只加列、不加默认值、不回填；旧行 NULL 明确表示未经过 Phase 3，迁移期间现有读写不需要知道新列。
- 不增加 `agents`/`agent_versions` 列，不增加独立 Task/Execution、Engine Session、RuntimeHost 或 Workdir 表。
- Engine 三元组保留在执行配置快照内，本阶段不为其增加查询索引；出现真实筛选需求后另评审。
- 配对 downgrade 仅删除这五列，且只在 disposable 数据库演练；生产回滚保留列与历史数据。
- 快照由应用按 Run 写一次，运行中不随配置、策略或探测变化而更新；公开 API 继续返回白名单字段。

### 3.2 AgentConfig JSONB 规范

| 配置区 | 字段 | 规则 |
|---|---|---|
| 公共区 | 现有 system/tool/knowledge/reply_language/summary/memory 字段 | 名称与语义保持，避免无关迁移 |
| 选择区 | `engine.engine_id/protocol_id/adapter_version` | 缺省 `react/native/v1`；必须精确注册，禁止 latest |
| React 区 | `react.model_profile_id/model_profile_version/max_model_rounds` | 严格类型与既有边界；旧根字段同值可读、异值拒绝 |
| Agent 策略区 | `disabled_capabilities` | 仅为已注册能力名的去重列表；只能收窄，不能接受 `effective_capabilities` |

保存或发布会生成规范化后的新草稿/新版本；读取历史对象不触发数据库 UPDATE。旧发布版本回滚时仍先经兼容层校验，不修改目标版本内容。

### 3.3 快照内容与敏感边界

| 快照 | 必需内容 | 明确排除 |
|---|---|---|
| Execution Config | schema_version、agent_id/version、engine、公共与 Engine 专属有效值、instruction_provider id/version | Token、API Key、凭据明文、Summary/Memory 原文、宿主环境 |
| Declared | schema_version、capabilities、adapter contract/version | 客户端提交值、进程/路径信息 |
| Available | 逐能力 available/reason_code、probe_version、probed_at | 原始探测 stderr、网络秘密、内部命令行 |
| Policy | schema_version、policy_version、逐层 source/reason/allowed、来源版本 | 秘密策略内容、其他租户规则、认证材料 |
| Effective | schema_version、最终 capabilities、resolution_digest | 可覆盖最终值的外部输入、原始客户上下文 |

每类快照均执行 JSON 大小限制与递归敏感键检查。摘要只用于关联，不把哈希当作脱敏手段；不允许先写入敏感原文再依赖日志脱敏。

## 4. 核心流程

### 4.1 配置加载与发布（`legacy_config.py`、`service.py`）

```
读取 JSONB → 识别旧/新字段 → 校验别名一致性 → 补 react/native/v1
→ Registry 解析精确三元组 → 按 Adapter schema 校验 → 生成不可变 ExecutionConfig
```

- 加载历史配置只做内存规范化；用户保存/发布才持久化新形态。
- 发布继续执行现有模型 Profile、工具、知识库和 tenant/scope 校验，不因新增 Engine 字段绕过。
- Phase 3 只完整开放 React 与测试 Adapter；生产未注册 Engine 一律拒绝，Codex schema 留待 Phase 5。

### 4.2 能力解析（`capability_resolver.py`）

```
Adapter.get_capabilities → Declared
Declared + 有界部署探测/版本矩阵 → Available
Available + 平台上限 → 租户策略 → 已发布 Agent 禁用项 → 可信 Execution 限制
→ Effective + 全层快照
```

- 逐能力求交而非字典合并；未知能力名默认 false 并产生配置/契约错误。
- 缓存键至少包含 tenant 无关的部署标识、Engine 三元组、探测版本；策略变化清理对应解析缓存。
- 探测超时/异常转换为稳定原因码；不得将原始异常、stderr 或路径写入事件。
- UI 预览和实际 Run 使用相同 resolver；执行时以新快照为准，不能接受 UI 上次预览结果作为授权。

### 4.3 Run 快照与启动屏障（`orchestrator.py`、`repository.py`）

```
Run 已创建 → 解析配置/能力/策略 → 校验并序列化快照
→ 在同一持久化边界写入 → 重新读取关键标识校验 → 构造 ExecutionRequest
→ 渲染指令 → Adapter.start
```

- 任一步失败都不得调用 Adapter.start；Run 由既有 Orchestrator/Repository 终态职责失败关闭。
- 已启动后取消/超时仍保留启动时快照；迟到结果不得修改快照或既有取消终态。
- `execution_phase3_enabled=false` 时仅走 Phase 2 React 兼容路径，五列保持 NULL；非 React 明确失败。

### 4.4 指令渲染（Instruction Provider）

```
现有 RuntimeFactory 有效系统提示（平台 + Agent + 回复语言）
+ MemoryInjection.render_summary / customer_memory 的既有结果
+ kept history + 当前输入
→ InstructionInput（每类仅一份）
→ Engine Instruction Provider → Adapter 原生指令
```

- React 顺序固定为 System → Summary（非空且启用）→ Memory（非空）→ kept history → user。
- Provider 不重新拼接平台/Agent 提示，不读取或写回 Summary/Memory，不改变 history_turns、budget、注入日志或完成后任务分发。
- 测试 Provider 证明可使用不同格式；Phase 3 不实现 Codex 文件发现、Skill 挂载或 Workspace 文件写入。

### 4.5 只读预览与审计

- 预览 API 仅接受 Agent/版本标识和可信 tenant/scope，服务端重新解析；不接受 Effective 或策略版本。
- 响应只含可展示能力、稳定原因码和配置 schema 元数据；不返回五个内部快照、策略秘密或探测原文。
- Agent 发布/回滚审计增加 Engine 三元组与配置 schema 版本；Run 内部审计可关联快照，不记录敏感值。

## 5. 配置

`backend/src/agent_platform/core_platform/platform_services/platform_settings/settings.py` 规划新增：

| 配置项 | 类型 | 默认值 | 约束 |
|---|---|---|---|
| `execution_phase3_enabled` | bool | `false` | 初始部署默认关闭；React 兼容与非 React 拒绝语义见 4.3 |
| `execution_capability_policy_version` | str | `v1` | 非空、受支持版本；仅服务端读取 |
| `execution_capability_probe_timeout_seconds` | float | `2.0` | `(0,10]`，禁止无界探测 |
| `execution_capability_probe_cache_seconds` | int | `30` | `[0,300]`；0 表示不缓存，仍不增加热路径外部调用 |
| `execution_snapshot_max_bytes` | int | `65536` | `[4096,262144]`，逐类检查 |

环境变量沿用 `AGENT_` 前缀。`.env.example` 只放非秘密值；任何 Engine Token 不属于本阶段配置。

## 6. 模型调用路径

React 继续按已发布模型 Profile ID/version 经现有 Model Gateway 选择模型，保持 `RuntimeFactory.bound_model` 的校验与 Run 关联；新规范只改变配置承载位置，不引入第二套模型解析或密钥流。无有效 Profile 仍返回 `agent_model_required`，工具调用能力仍按现有校验。其他 Engine 的模型/凭据路径由各自后续阶段定义，本阶段不得借通用 `config` 绕过 Gateway。

## 7. 测试方案

| 层 | 用例 |
|---|---|
| 单测 | 旧配置映射、别名冲突、严格 schema、四层能力单调性、伪造输入拒绝、快照敏感/大小校验、React/测试 Provider 渲染 |
| 集成 | 草稿→发布→Run→快照全链路，策略变化、探测失败、取消/失败快照、跨租户与开关回滚 |
| 迁移 | 从实际前驱升级、旧行 NULL、新行写入、并发读写、配对 downgrade、历史迁移校验 |
| 回归 | Phase 0 React/Worker/Repository/SSE 基线，Agent 配置与 Summary/Memory 全套适用测试 |

详细用例、故障与恶意路径见 `04-test-plan.md`。

## 8. 上线与回滚

1. **入口**：Phase 0 基线、Phase 1–2 验收完成；重验迁移 head、目标提交和契约版本。
2. **迁移**：五个可空列可在线事务执行，无默认回填和长时间数据重写；先在存量副本验证读写与锁。
3. **灰度**：先部署 `execution_phase3_enabled=false`，确认 React 无 diff；随后仅对测试租户/测试 Adapter 开启，观察解析延迟、拒绝原因与快照大小。
4. **开放**：通过 AC 与安全门槛后再开启；生产未注册 Engine 不因开关打开而自动可用。
5. **开关回滚**：关闭总开关即停止新 Phase 3 路径；非 React 明确失败，绝不静默改用 React。保留快照列和 Agent JSONB。
6. **代码回滚**：可回到 Phase 2 兼容代码，旧代码忽略新增可空列；不得读取不存在的非空默认值，也无需数据库 downgrade。
7. **数据回滚**：仅 disposable 环境验证 downgrade；生产若确需删列须单独变更评审，不与应用回滚绑定。
