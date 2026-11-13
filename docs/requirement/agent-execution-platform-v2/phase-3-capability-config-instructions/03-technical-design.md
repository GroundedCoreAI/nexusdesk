# Phase 3 · 能力、配置与指令 — 技术设计

> 状态：设计已按基线 `3969258` 校准；T2～T5 已在特性分支工作树实施（未 commit），§7 预览契约与 §9 迁移发布仍待 T8/T7 接线，下文未实施项均为规划
> 创建：2026-11-02
> 修订：2026-11-13（T5 返工冻结点写入 §5.2/§5.3：序列化后二次严格校验、值侧路径拒绝与重放语义级保证两条有意收窄、startup identity 两道闸、写屏障受控分类结果与 jsonb 语义相等；§8 补 flags 读取失败不出"未启用"提示）
> 修订：2026-11-13（T9 前端线契约张力裁定 R-23～R-25：§8 Engine 只读呈现钉死、§3.2.5 语义层判据澄清、新增 §7.4 execution-config-flags 只读契约）
> 修订：2026-11-13（T4 返工裁定 R-17～R-22：受信 policy revision 入口、capability settings 落点与 TTL 下界、Effective 唯一投影、Available 收窄不可旁路）
> 修订：2026-11-13（§4.1 补充必需能力缺失判定范围，对应 R-16）
> 修订：2026-11-12（Registry、执行链、预览 API、缓存/快照与迁移现实）
> 依据：`01-business-goals.md`（G1–G4）、`02-requirements.md`（FR-1–FR-9、AC-1–AC-11）、架构第 3、5、6、11、14–17、21 节
> 当前代码核验：2026-11-12；Alembic head 为 `0057_industry_pack_runtime`，`0053_routing_decisions` 已存在
> 开发入口：focused baseline 163 passed / 5 skipped；上游 Phase 0/1 正式验收、Phase 2 生产/CI/UAT 未决项仍按原报告跟踪

## 1. 当前代码映射与边界

| 领域 | 已存在 | Phase 3 扩展方式 |
|---|---|---|
| Registry | `AdapterDescriptor` 仅精确三元组/enabled；`register` 不调用 factory；`resolve` 返回 fresh Adapter 并防 live 复用 | 描述符增加严格 config schema、Declared、probe/policy/provider 标识与版本；新增 metadata 精确查询，草稿绝不 `resolve` |
| 配置 | `AgentConfig(extra=forbid)` 使用 JSONB 草稿/发布，旧根 model 字段和模型/工具/知识校验 | 同一兼容层规范化；保持已有存储/权限/发布，不新增表、不回写历史 |
| 编排 | Orchestrator 固定 React/native/v1，ExecutionContext 构造请求，Composition 注册 ReactAdapter | 选择已发布 ExecutionConfig，扩展 Context/Orchestrator，保留 worker_emit/runtime_emit、ack、private Outcome |
| React | `ReactAdapter.start` 创建 `_Execution` 与 runner，runner 内 RuntimeFactory 构造模型/工具/Runtime | start 前准备快照与 Provider 输入；准备完成后才创建 runner，RuntimeEngine 消息规则不变 |
| Memory | Worker 已产生 `summary_message/customer_memory`；RuntimeEngine 按 System→Summary→Memory→history→user 组装 | 复用已渲染结果各一次；Provider 仅适配，不重新读取、预算或写回 |
| Run | Repository.claim 标 running 并公开 `run.started`；Worker 保留 legacy/on 两条路径 | 不改变 claim 公共事件顺序；在 Adapter.start 前新增私有五快照提交屏障与明确双开关矩阵 |
| 前端/API | `/api/v1` internal routes、React 19 + antd v6 AgentsPage、四个 JSON locale、Playwright | 增加 internal preview，扩展现有页面与类型；不建外部服务/Postman 发布/组件测试框架 |

明确不实现 Runtime Host、真实进程/Workdir/Sandbox、Codex、凭据代理、强隔离、网络出口、Fencing/Outbox、latest 或自动跨 Engine fallback。

## 2. 文件级改动规划

新增路径是建议落点，T2–T9 可在不改变边界的情况下小幅调整并同步 08；不得复制平行执行链。

| 文件 | 动作 | 内容 |
|---|---|---|
| `backend/migrations/versions/0058_agent_execution_metadata.py` | 新增 | 当前 `down_revision=0057_industry_pack_runtime`；`runtime_runs` 五可空 JSONB 列；T2 动态重验 |
| `backend/src/agent_platform/core_platform/platform_services/platform_settings/settings.py` | 修改 | Phase 3/probe/policy/cache/snapshot/warmer 设置（R-18/R-19），默认安全，无秘密 |
| `.../agent_execution/contracts/config.py` | 新增 | `ExecutionConfig`、Engine triple、ReactConfig、legacy alias 规范化 |
| `.../agent_execution/contracts/capabilities.py` | 修改 | 复用 11 项能力，增加分层原因/决定 DTO，不新增未编号能力语义；新增 Effective→Run/preview 的唯一投影函数（R-21）与 `execution_restriction_digest`/`NO_EXECUTION_RESTRICTIONS`（R-17） |
| `.../agent_execution/contracts/snapshots.py` | 新增 | 五类严格快照 DTO、schema/version、递归 denylist、序列化与大小校验 |
| `.../agent_execution/contracts/instructions.py` | 新增 | `InstructionInput`、PreparedInstructions、Provider Protocol |
| `.../agent_execution/registry/adapter_registry.py` | 修改 | metadata 注册/精确查询；factory 与 fresh Adapter 语义不变 |
| `.../agent_execution/capability/{ports,resolver,cache,warmer}.py` | 新增 | TrustedDeploymentProbe、TrustedPolicyProvider（含 `current_revision`，R-17）、Available/Policy/Effective 解析、缓存与受控后台 warmer |
| `.../agent_execution/instructions/{react,test}_provider.py` | 新增 | React 原生消息格式与独立测试格式；测试 Provider 不进生产注册 |
| `business_capabilities/agent_config/service.py` | 修改 | AgentConfig 新字段、canonical diff、草稿/发布校验、历史只读 |
| `core_platform/agent_runtime/repository.py` | 修改 | 五快照一次写入；既有 claim/终态顺序不改 |
| `core_platform/agent_runtime/schemas.py` | 修改 | 仅私有 DTO 接线；公开 RunRequest 仍 strict，无能力/策略字段 |
| `agent_execution/orchestration/{execution_context,orchestrator}.py` | 修改 | 选择配置、能力/Provider/快照准备、Adapter.start 屏障 |
| `agent_execution/adapters/react/adapter.py` | 修改 | 接收已准备输入；不在 runner 内二次业务渲染；保留 gate/ack/cancel |
| `applications/platform_runtime/{runtime_factory,runtime_composition}.py` | 修改 | system prompt 只计算一次，注入 resolver/Provider；双开关接线 |
| `core_platform/agent_runtime/worker.py` | 修改 | 四态矩阵；off 走原路径，on+orchestrator off 失败关闭 |
| `applications/customer_service/platform_routes.py` | 修改 | `POST /agents/execution-preview` strict 请求/白名单响应与 scope；新增 `GET /agents/execution-config-flags` 只读开关契约（§7.4） |
| `frontend/src/shared/api/client.ts` | 修改 | Engine/React/disabled/preview 类型与 API helper |
| `frontend/src/features/agents/AgentsPage.tsx`、`agents.css` | 修改 | 沿用现有区块；仅适度提取 `ExecutionConfigSection`/`CapabilityPreview` 等 |
| `frontend/src/i18n/locales/{zh-CN,zh-TW,en,hi}.json` | 修改 | 所有表单、原因、错误文案四语言 |
| `frontend/tests/agent-execution-config.spec.ts` | 新增 | 有针对性 Playwright M1–M3/伪造字段/只读/四语言证据 |

## 3. ExecutionConfig、别名与 canonical diff

### 3.1 数据模型

```text
ExecutionConfig (strict, frozen, extra=forbid)
  engine: EngineIdentity { engine_id, protocol_id, adapter_version }
  react: ReactConfig | null
  disabled_capabilities: tuple[CapabilityName, ...] = ()
ReactConfig (strict, frozen)
  model_profile_id: UUID | None
  model_profile_version: int | None
  max_model_rounds: PositiveInt  # 沿用既有边界
```

- 缺少 `engine` 时仅内存补 `(react,native,v1)`；显式非 React 不允许携带 `react` 配置。
- `ExecutionConfig` 只含可发布、可审计配置，不含 Declared/Available/Policy/Effective、probe 结果、tenant/actor 或宿主信息。
- `AdapterDescriptor` 扩展 `config_schema`、`declared`、`declared_schema_version`、`probe_id/probe_version`、`policy_provider_id/policy_version`、`instruction_provider_id/provider_version` 与 `config_schema_version`。新增 `metadata(engine,protocol,version)` 精确查询，disabled/unknown 均明确失败。
- 草稿/发布/预览调用 metadata 的 schema validator；Registry `register` 和 metadata lookup 均不调用 factory。执行路径仍需 `resolve` fresh Adapter，start 前可比较实例声明与注册声明，偏离则失败关闭。

### 3.2 单一 legacy normalizer

1. 先用既有 AgentConfig 严格解析公共字段，再提取旧根 model alias 与新 `react`。
2. 两边都缺失时使用 React 默认；仅一边有值时采用该值；两边都有且语义相等时接受并只保留 canonical 值；不等时以字段路径报冲突。
3. ID/version 配对、轮次、模型 Profile/工具/知识/tenant 权限继续走既有服务校验，兼容层不能绕过。
4. 返回新对象，不修改输入 dict/model；GET、回滚查看、diff、后台正常读取均不持久化。
5. 用户明确保存新形态时写 canonical 配置；普通旧草稿编辑不得仅因缺省三元组产生变化。本条约束的是语义层"变化"（判据为 canonical diff/审计无默认噪声，见 §3.3 与 P3-IT-01），不是客户端 PUT body 的键集合选择：前端可最小写回——只写草稿中已存在的别名位置（有根别名改根别名、有 `react` 则同步 `react`），绝不为旧草稿凭空补 `engine` 或 `react` 键、空 `disabled_capabilities` 省略；服务端存储端照常把 body 规范化落库（T3 已冻结行为），该规范化本身不构成"仅缺省三元组的变化"。两端均不得把本条读作"一编辑即须为草稿补写 engine/react"或"服务端必须原样保存旧形状"，前者制造别名冲突，后者重开 T3（08 R-24 钉死）。

### 3.3 canonical diff

diff 两侧先经同一 normalizer 得到语义视图，再剔除仅由 Phase 3 默认补出的 `engine=react/native/v1`、空 `disabled_capabilities` 和与旧根等价的 `react` 默认字段。用户实际值变化、disabled 新增、显式非 React 均保留差异。禁止通过全局删除默认值掩盖真实修改；已发布原始 JSONB 不变。

## 4. 能力解析、可信端口与缓存

### 4.1 四类类型

| 类型 | 内容与来源 | 约束 |
|---|---|---|
| `DeclaredCapabilities` | Registry 11 项 `EngineCapabilities`、declaration schema/version、三元组 | 注册时代码可信；客户端不可覆盖 |
| `AvailableCapabilities` | 每项 `{available,reason_code}`、probe id/version、observed_at、deployment/declaration digest | `available ⇒ declared`；原始 probe 响应不入快照/API |
| `PolicyDecisionSet` | 每项各层 `{allowed,source,reason_code}`、platform/tenant/agent/execution policy version/revision | 来源必须可信；决定只允许收窄 |
| `EffectiveCapabilities` | 每项 `{effective,reason_code}`、resolved policy/declaration/probe 版本摘要 | `effective = declared ∧ available ∧ platform ∧ tenant ∧ ¬agent_disabled ∧ execution_allowed` |

未知能力名不是可忽略集合项，而是 schema/策略错误。平台 ceiling 默认最小授权；缺 tenant/Agent/Execution 策略不能放大 ceiling。稳定原因至少区分 `not_declared`、`probe_unavailable`、`probe_timeout`、`probe_stale`、`workspace_unavailable`、`platform_denied`、`tenant_denied`、`agent_disabled`、`execution_denied`、`policy_unavailable`；公开只返回安全原因。

"必需能力缺失"（阻止启动）仅指 declared=true 且最终原因属于部署/受信基础设施不可用类：`probe_unavailable`、`probe_timeout`、`probe_stale`、`workspace_unavailable`、`policy_unavailable`（含未预热/过期产生的不可用）；此类使 Run 准入失败关闭（FR-2"不可用配置不得发布或启动"、FR-3 失败处理、FR-4"缺失/不可信策略按最小权限"）。`not_declared` 与策略层收窄 `platform_denied`、`tenant_denied`、`agent_disabled`、`execution_denied` 是 FR-4/AC-4 的正常单调收窄结果，本身不构成必需能力缺失、不阻止启动；对应能力仅 Effective=false，并在快照中记录来源、版本与原因码。受控策略显式定义必需子集前，declared=true 全集视为必需集。

`workspace_required=true` 且可信 Workspace availability 不存在/不可用时，该 Adapter/运行准入不可用；Phase 3 不创建 Workdir 或伪报 Workspace 可用。`disabled_capabilities` 只能将 true 变 false，不能启用 Declared=false 或上层 false。

### 4.2 端口

```text
TrustedDeploymentProbe.probe(ProbeContext) -> ProbeResult
TrustedPolicyProvider.current_revision(PolicyRevisionScope) -> int
TrustedPolicyProvider.resolve(PolicyContext) -> PolicyDecisionSet
WorkspaceAvailabilityPort.current(WorkspaceScope) -> AvailabilityGeneration
```

端口由 composition 注入受信实现；请求 DTO 不能传 probe/policy 实例、URL、策略版本或结果。ProbeContext 只含部署身份、精确三元组、adapter/config/probe 版本、声明 digest、Workspace scope/generation。probe 有 timeout 与并发上限，不得启动外部 Engine 或输出秘密；本阶段不假设已有熔断基础设施，若需退避仅由受控后台调度器实现。

**policy revision 的受信入口（R-17）**：`policy_revision` 是受信策略源的当前观测值，不是调用方入参，`CapabilityResolutionRequest` 不携带该字段。resolver 每次构造 Policy/Effective key 与 PolicyContext 时，通过 `current_revision(scope)` 向注入的同一 `TrustedPolicyProvider` 现读；该读取与 `WorkspaceAvailabilityPort.current` 同级——同步、本地、无远程 I/O，允许出现在同步 hot path。**Availability key 的构造同样经该现读路径（与 Policy key 共用同一轮观测），因此策略源故障时整轮 fail-fast、连 Available 解析一并抛 `PolicySourceUnavailableError`，这是有意设计而非遗漏：目的是保证同一轮内 key、loader、echo 校验与 Effective provenance 使用同一个 revision 值，避免 revision 恰好在轮内前进时把 revN+1 的结果写进 revN 的 key；T7 不得把 `availability_cache_status` 当作"不依赖策略源的诊断入口"。同一作用域内该值必须单调不减，`resolve()` 必须回显本轮读取的同一 revision；回显不一致按 `_PolicyMismatchError` 记为缓存 error 状态，后续 hot read 得 `policy_unavailable`（按 R-16 属必需能力缺失，失败关闭），下一次有界刷新自愈。读取抛异常时 resolver 抛 `PolicySourceUnavailableError`，预览与 Run 准入映射为稳定 `execution_policy_unavailable`，禁止用 `0` 或缺省值继续。本阶段平台默认策略源无版本化租户策略数据，`current_revision` 返回按作用域稳定的值即为合规实现；§4.3 的"policy revision 变化使相关条目失效"由该机制兑现，不再依赖 TTL 兜底。`execution_restriction_digest` 由 composition 服务端用 `contracts/capabilities.py:execution_restriction_digest(values)`（与 `disabled_capabilities_digest` 同一 canonical 形态）计算，Phase 3 无 restriction 源，固定传空集常量 `NO_EXECUTION_RESTRICTIONS = "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"`（即 `execution_restriction_digest(())` 的实际计算值，若 canonical 形态未来变更该常量字面值必须同步变更并被测试钉住）；策略源不回显该摘要，不参与身份校验。

**构造参数来源（R-18/R-19/R-20）**：probe/policy 超时、并发上限、两把缓存容量、失败重试间隔、warmer 刷新周期与部署身份一律取自 FR-9 的 `execution_capability_*` settings，composition 不得自造硬编码常量；`*_cache_seconds`、`*_retry/refresh_seconds` 与 `CapabilityCache`/`CapabilityWarmer` 的 `ttl_seconds > 0`、`retry_interval_seconds > 0`、`capacity >= 1` 同边界，非法值在 settings 层失败关闭；`execution_capability_policy_version` 由 composition 用作 `AdapterDescriptor.policy_version` 与所注册策略 provider 的同一版本值。

**首次填充与生命周期**：composition 启动时为已注册且 enabled 的精确三元组建立 probe/policy cache entry，并由受控后台 warmer 执行首轮 probe；warmer 只调用可信端口、写脱敏 Available DTO，不创建 Adapter/Run。应用 ready 可不等所有外部 probe 完成，但在有效值写入前对应 Available=false。此后 warmer 按 TTL 在过期前刷新，失败保留明确 stale/error 状态而不把旧值当新鲜授权，并按有界间隔重试。Run 和 preview 的同步 hot path 只读缓存；miss/stale 时返回不可用并触发去重后的后台刷新，绝不在请求内同步调用远程 probe。测试 composition 用同一生命周期接口注入确定性 probe/policy 替身和 fake clock，显式控制首次填充、刷新、过期与关闭，覆盖“未预热不可用→后台成功→可用→过期不可用”的完整序列；应用关闭须取消 warmer，测试不得泄漏后台任务。

### 4.3 缓存键与失效

- **Available key**：`deployment_identity + engine triple + adapter_version + config_schema_version + probe_id/probe_version + declaration_digest + workspace_availability_generation`。
- **Policy/Effective key**：上述 identity/declaration/probe 摘要 + `tenant_id + business/workspace scope + agent_id + published_version + policy_provider_id/policy_version/policy_revision + disabled_capabilities_digest + trusted_execution_restriction_digest`（其中 `policy_revision` 由 §4.2 的 `current_revision` 现读，非调用方传入，R-17）。
- 缓存只存脱敏 DTO，有 TTL、容量上限和 per-key singleflight；同步 hot path 不等待无界远程调用。miss/stale/error 的 Available 为 false；未知/不可信 Policy 失败关闭。
- **Available 缓存值不含 Workspace 收窄（R-22）**：Available key 含 `workspace_availability_generation` 但不含 tenant/scope（保持既有裁定），缓存值因此是部署级原始观测，`_narrow_workspace` 只发生在读路径。任何快照、`ExecutionRequest`、审计或预览证据的构造方必须消费 `CapabilityResolution.available/effective`（已收窄），禁止直接读取 `CapabilityCache.lookup(...).value`；构造方签名入参类型固定为 `CapabilityResolution`，类型即门禁。旁路产生"无受信 Workspace 却 available=true"的矛盾证据，按 P1 缺陷返工。
- 注册/声明/probe 版本变化替换 identity key；平台/租户 policy revision 变化使相关 tenant/scope 条目失效（由 §4.2 `current_revision` 现读兑现，非 TTL 兜底，R-17）；Agent 发布/disabled 或 Execution restriction 变化自然换 key；Workspace generation 变化只影响相关 Available/Effective。预览不得把决定写入 Run 授权缓存，执行必须重新求值当前版本。
- **Runtime fingerprint 裁定**：沿用 `execution_orchestrator_enabled` 先例，`execution_phase3_enabled` **不进入 fingerprint**。组合根可长期持有无副作用的 resolver/cache，Worker 在每个已 claim Run 开始时读取一次当前双开关并固定本次路径；off/on 切换不要求重建 Runtime，也不得改变 legacy claim 语义。路径固定后即使运行中开关变化也不重算；已写快照的一致性由 startup identity 保证，不能借缓存复用改写策略。T7 增加缓存 Runtime 下 off→on、on→off、on+orchestrator off 和已 claim 行的回归。

## 5. 五快照与启动屏障

### 5.1 DTO 与列

| 快照 DTO | 规划列 | 最小内容 |
|---|---|---|
| `ExecutionConfigSnapshot` | `execution_config_snapshot` | schema_version、Agent/version、Engine triple、canonical config、provider id/version |
| `DeclaredCapabilitiesSnapshot` | `declared_capabilities_snapshot` | schema_version、Engine triple、declaration version/digest、11 项声明 |
| `AvailableCapabilitiesSnapshot` | `available_capabilities_snapshot` | schema_version、逐项 available/reason、probe id/version、observed_at、digest |
| `EffectiveCapabilitiesSnapshot` | `effective_capabilities_snapshot` | schema_version、逐项 effective/reason、关联 declaration/probe/policy 版本 |
| `ExecutionPolicySnapshot` | `execution_policy_snapshot` | schema_version、各层决定、可信来源标识、policy version/revision、disabled/restriction 摘要 |

五列均可空 JSONB；旧行 NULL 表示未经过 Phase 3。所有 DTO strict/frozen、版本显式、无任意扩展字典。不包含 Summary/Memory 原文、用户输入全文、模型响应、API Key/Token、连接串、stderr、secret reference 明文或内部宿主路径。

### 5.2 递归 denylist 与大小

在嵌套 dict/list/tuple/DTO 全路径扫描键和值；键名归一化后至少拒绝 `password/passwd/secret/token/access_token/refresh_token/api_key/apikey/authorization/cookie/credential/private_key/connection_string`，以及明确业务字段 `customer_memory/summary_message/raw_memory/stderr/host_path/workdir_path`。不能仅靠顶层删键；允许字符串中出现普通单词不应误报，但凭据形态值或已标记敏感路径必须拒绝。错误只给字段路径与稳定码，不回显原值。

五类分别 canonical JSON 序列化并计算 UTF-8 bytes，各自不得超过 `execution_snapshot_max_bytes`（默认 65536），不是五类共享总额。不可序列化、denylist 命中、超限、版本/必需字段缺失均失败关闭。序列化在生成 canonical 文本后**再对该文本执行一次严格 DTO 校验**（`type(snapshot).model_validate_json(canonical)`）：`frozen=True` 只挡属性赋值、不挡 `model_copy(update=...)`，而完成度/覆盖性不变量只在构造期运行，故再校验是必需的第二道闸——`model_copy` 绕过验证器不得成为落库通道。校验发生在 denylist 与 JSON 生成之后，因此不可序列化输入仍按原语义报"不可序列化"，且再校验不改变 canonical 字节（重复序列化逐字节一致）。

两条有意收窄（冻结）：

- 值侧宿主路径拒绝作用于**所有**字符串值，不限键名。这是有意的强收窄：五类快照 DTO 中唯一无格式约束的字符串是 `EffectiveCapabilitiesSnapshot.tenant_id`，其余（Slug/EngineId/AdapterVersion/DigestString）的文法本身不允许以分隔符开头，故"以 `/` 开头的值被拒"不会误杀合法载荷；负控测试覆盖本仓真实 tenant/workspace 标识形态与 URL、相对路径、中文等业务文本。
- 只读决策重放提供的是**语义级**保证（严格再校验 + 载荷身份一致性 + 与 canonical 化后的形态比对），**不提供逐字节防篡改**：PostgreSQL `jsonb` 会重编码键序与空白，逐字节比较会误杀合法读回，因此比较对象是 canonical 化后的形态而非原始存储字节；字节级审计完整性需另行引入校验列/链式摘要，不在 Phase 3 范围。重放入口接受 `str | Mapping` 两种形状（`Repository.get` 返回解码后的 dict），错误码区分"缺失"与"类型不符"，不得把类型误用报成"载荷缺失"。

### 5.3 顺序与一次性

1. 既有 Repository.claim 仍先把 Run 标 running 并公开 `run.started`，保持 Phase 2 对外兼容。
2. Worker/Orchestrator 在 Phase 3 on+orchestrator on 路径读取已发布配置、当前可信 Available/Policy，构造五 DTO 和 PreparedInstructions。四个能力类快照（Declared/Available/Policy/Effective）只能由 `CapabilityResolution` 构造（R-22）；`ExecutionRequest.effective_capabilities` 由 §7.2 的唯一投影函数从同一 resolution 派生，不得从缓存原始值或降级视图反推原因码。
3. 对五 DTO 完成校验、denylist、序列化、大小检查后，在一个短事务写入同一 Run；要求五列仍 NULL，或 `ExecutionConfigSnapshot.execution_id` 与本次 startup identity 相同，避免并发/重试覆盖。startup identity 直接复用 `ExecutionContext.execution_id`，写入配置快照并由其余四快照的同一字段关联，**不新增第六列或单独 token 列**。身份不变量由**两道闸同时强制**：入口守卫要求 `payloads.execution_id == run_id` **且五份载荷体内 `execution_id` 均等于 `str(run_id)`**（防"守卫参数诚实、体内伪造"），不符者直接返回 `audit_conflict` 且**不访问数据库**；SQL 谓词在两个分支上都绑 `execution_config_snapshot->>'execution_id'=:execution_id`，即使调用方跳过入口守卫也无法把某行指向另一个 run。"同身份校验复用"的比较语义是 **PostgreSQL `jsonb` 值相等（语义相等）**，不是逐字节相等。写入结果返回受控分类 `SnapshotWriteResult.outcome ∈ {written, reused, audit_conflict, not_claimed, lease_lost}`（只含标签、不含任何载荷内容），调用方映射见 08 T7 接线纪律。
4. **DB commit 成功是 `Adapter.start` 的硬屏障**。任一失败走既有 failed 终态/错误映射，`Adapter.start`、runner、RuntimeFactory 模型/工具装配均不得发生。
5. start 后完成、失败、取消、失租、超时或迟到结果均不更新五列。应用重试若已有快照只能验证一致并复用（一致判据同上，为 jsonb 语义相等），不能按新策略重写；不一致失败并返回 `audit_conflict`。
6. 公开 Run/详情/SSE/预览均不直接返回五列；仅受权内部审计另用字段白名单，本阶段不新增公共快照端点。

## 6. Instruction Provider 与 React 兼容

```text
InstructionInput (strict, frozen)
  engine: EngineIdentity
  agent_id, agent_version
  system_prompt: str                  # RuntimeFactory 已计算的平台+Agent+回复语言规则
  history: tuple[ConversationMessage, ...]  # 已按既有保留策略生成
  current_user_input: str
  summary_message: str | None         # Worker 已渲染
  customer_memory: str | None         # Worker 已渲染
  engine_context: Mapping[str, Scalar] # 仅受控非敏感占位；Phase 3 不挂 Skill/Workdir
InstructionProvider.prepare(InstructionInput) -> PreparedInstructions
PreparedInstructions { provider_id, provider_version, payload }
```

- RuntimeFactory 在 runner 前完成有效 system prompt 计算一次；Worker 的 Summary/Memory 业务结果直接传入，Provider 不查询 Memory、不改开关/预算/文案。
- React Provider 产出与 `RuntimeEngine.run` 等价的结构化输入，顺序固定 System → 可选 Summary System → 可选 Memory System → kept history → current Human；空值不创建空消息。
- history 截断、Summary 开关、无空消息、完成 history/dropped、日志和完成后 Memory 写回沿用现有代码，不能在 Provider 再执行一次。
- 测试 Provider 返回独立可断言的原生格式，只注册于测试 composition，用来证明同一 InstructionInput 不需第二次业务渲染、也不强制 ReAct 化。
- Orchestrator 完成 Provider prepare 与快照 commit 后调用 `ReactAdapter.start`；Adapter 创建 `_Execution`/asyncio runner 的现有时点之后只做 Engine 格式消费。未知 Provider、重复渲染或 contract 错误在 start 前失败。
- 双 emit、结构化 ack、backpressure、private Outcome、取消 gate、公开 Run/SSE 语义全部保留。

## 7. 预览 HTTP 契约

### 7.1 路由与权限

`POST /api/v1/agents/execution-preview`，挂既有 `applications/customer_service/platform_routes.py` 与 authenticated internal management 依赖；不是 Open Platform，不新增外部服务/Postman 发布。沿用 Reader/Admin 中现有 Agent 读取权限，写权限只控制保存/发布，预览本身永不修改。

请求（所有层 `extra=forbid`）：

```json
{
  "agent_id": "7b8f…可省略或 null",
  "config": {
    "system_prompt": "…",
    "engine": {"engine_id":"react","protocol_id":"native","adapter_version":"v1"},
    "react": {"model_profile_id":null,"model_profile_version":null,"max_model_rounds":6},
    "disabled_capabilities": ["terminal_execution"]
  }
}
```

`config` 使用完整 AgentConfig 草稿契约（示例省略既有公共字段），支持未保存修改；`agent_id=null` 可预览新草稿。提供 ID 时必须以认证 tenant + business/workspace scope 加载并核对草稿归属，跨租户/跨 scope 使用既有 not-found，不能仅隐藏响应字段。

明确禁止请求中的 `declared`、`available`、`effective`、`effective_capabilities`、`policy`、`policy_version`、`probe`、`tenant_id`、`actor`、宿主/Workspace 内部字段及任何未知字段；不得“忽略后继续”。服务端仅从注册 metadata、可信端口与认证上下文计算。

### 7.2 响应

```json
{
  "engine": {"engine_id":"react","protocol_id":"native","adapter_version":"v1"},
  "config_schema": {"schema_version":"v1","fields":[{"name":"max_model_rounds","type":"integer","required":true}]},
  "capabilities": [
    {"name":"streaming","effective":true,"reason_code":"allowed"},
    {"name":"terminal_execution","effective":false,"reason_code":"agent_disabled"}
  ]
}
```

响应模型也是白名单 strict；`config_schema` 只含可公开字段名/类型/必填/安全边界，不含 JSON schema 内部描述中的秘密或路径。11 项均返回 Effective 与稳定原因，不返回 Declared/Available/Policy 原值、五快照、probe 原文、policy 规则、内部 ID 或路径。probe 失败时对应项 `effective=false` + 稳定原因，不能返回成功可用。

preview 的 `capabilities` 数组即 `EffectiveCapabilities.items`，由唯一投影 `effective_capability_views(resolution.effective)` 产出：字段固定 `name/effective/reason_code`（复用既有 strict DTO `EffectiveCapabilityDecision`，不新建响应模型）、11 项齐全、按 `CAPABILITY_ORDER` 排序（R-21）。Run 侧 `ExecutionRequest.effective_capabilities` 由同一模块的 `effective_capability_flags(effective)` 唯一投影，恒含 11 个键、False 不省略；两路投影必须来自同一 `EffectiveCapabilities` 实例，T7/T8 不得内联字典推导、重排或裁剪，也不得从降级视图反推原因码。

### 7.3 错误与副作用

| 情况 | 行为 |
|---|---|
| Phase 3 off | 稳定领域错误 `execution_phase3_disabled`，不 probe、不实例化 Adapter |
| schema/type/extra/forged | 既有 422 风格，字段路径可定位，无敏感回显 |
| scoped Agent 不存在/跨域 | 既有 404 domain 行为，不泄露另一 tenant 是否存在 |
| 未知/禁用三元组 | 稳定 `execution_engine_unavailable`（或现有等价 DomainError，实现时固定映射） |
| Registry schema/Provider/Policy 配置错误 | 稳定 `execution_configuration_invalid` / `execution_policy_unavailable`，不降级授权 |
| 单个 probe 失败/超时 | 200 预览中该项不可用及稳定原因；若配置整体不可解析则对应领域错误 |

预览不调用 factory/`resolve`，不创建 Run、Conversation、snapshot、Memory 任务或 Adapter，不缓存为后续 Run 授权。执行必须重新读取已发布版本和当前可信策略。

**422 不等于安全审计**：当前 `applications/application_factory.py` 的全局 RequestValidationError handler 只返回 422，不写安全审计。T8 必须为 Run/Agent/预览的伪造字段与越权尝试增加可测试的审计接线，优先复用现有审计服务与可信认证上下文，可在该 handler 增加按路由/稳定字段路径触发的最小 hook；只记录时间、可信 tenant/actor/scope、route、request ID、错误类别和脱敏字段路径，**绝不记录请求 body、字段值、Authorization/Cookie 或秘密**。P3-IT-04 必须直接查询审计记录，不能只断言 422。

### 7.4 Phase 3 开关只读契约

`GET /api/v1/agents/execution-config-flags`，与 preview 挂同一 `applications/customer_service/platform_routes.py`、同一 authenticated internal management 面（`Reader` 读取权限；viewer 也需按开关呈现，故不用 Admin），不是 Open Platform。无请求参数与 body；响应为 strict DTO（`extra=forbid`、frozen，字段恰为两个布尔、名称与 settings 逐字一致）：

```json
{
  "execution_phase3_enabled": false,
  "execution_orchestrator_enabled": true
}
```

本端点存在，是为了让前端声明式满足 05 M3（"Phase 3 编辑入口失效/隐藏符合开关"）：错误反推只能表达"尝试且失败"，无法表达"未尝试即隐藏"，也无法区分 off 与 on+orchestrator-off 错配态；设计先例是既有 `GET /agents/memory-config-caps`（同为向 Reader 暴露租户无关部署开关）。纪律：

- 只读 `runtime(request).settings` 两个布尔；禁止读取 capability 缓存、发起 probe、调用任何远程端口、实例化 Adapter/factory、创建 Run/Conversation/快照、触发 warmer 或写审计（读缓存会把端点与 Phase 3 子系统生命周期耦合，冷/关部署下反而不可读）。Phase 3 全 off 时必须正常返回——这正是它存在的场景；本端点永不返回 `execution_phase3_disabled` 或其他 execution_* 领域错误，认证失败沿用既有 401/403。
- 暴露两个原始开关而非合成视图：合成字段会把 FR-9 四态矩阵复刻到服务端并与前端漂移，且丢失"正常回滚 off"与"配置错误态"的区分；运维提示须能引用与 `backend/.env.example` 逐字同名的配置项。矩阵在 UI 的合成规则见 §8，权威判定仍在服务端。
- 安全边界：两布尔为非秘密、租户无关的部署配置，保密级别同 `summary_enabled` 等既有暴露，不含 body/Token/Key/原始 Memory/宿主信息，不违反 C3；对所有认证 tenant 返回一致、无 per-tenant 数据面与跨 scope 查询，不违反 C4。不返回其他 `execution_capability_*` 调参、内部 ID、digest、policy/probe 原文或 schema_version。
- OpenAPI 与其他 internal route 一样自动包含；响应确定，前端单次编辑器生命周期取一次即可。本条由 08 R-25 钉死；T8 实现、T9 消费。

## 8. 前端与可观测性

- 在 AgentsPage 现有配置页增加 Engine 与 React 配置区块，复用 `AgentModelPicker`、antd Form 和 `agents.css`；仅当文件复杂度需要时提取 1–2 个同目录组件，不建新设计系统。
- US-1 的"选择受支持的 Engine/Protocol"在 Phase 3 单合法三元组下以只读呈现兑现：展示草稿生效三元组（缺省 `react/native/v1`）与"已注册/未注册"状态 Tag，前端候选集是等于生产 Registry 合法集的常量，不设 Engine 目录端点、不做自由输入（本形态为 US-1/§8 的合规实现，08 R-23 钉死，不可回退）。真正的多候选选择在 Phase 4/5 非 React Engine 进入生产注册时才是需求（04 P3-CM-10），届时候选必须来自 Registry metadata 而非前端枚举。只读呈现不放宽 FR-2：未注册/非 React 三元组仍由服务端在保存/发布/preview/Run 精确拒绝，前端 Tag 只是呈现提示、不是校验，不得以显示方便引入 `latest` 或跨 Engine 自动换。
- 保存继续使用既有草稿/发布/diff 流程；canonical 默认不制造 dirty。旧 Agent 打开时不强制补字段或重新发布。
- “预览能力”显式触发当前未保存 config 的 POST；结果显示只读 Effective/reason，禁用项只能加入 `disabled_capabilities`，不提供 Declared/Available/Policy 编辑或 Run 按钮授权。
- 前端以 `GET /agents/execution-config-flags`（§7.4）声明式门控，不靠点击报错反推开关：`execution_phase3_enabled=false` 时隐藏 Phase 3 专属编辑入口（"预览能力"按钮与 CapabilityPreview 面板、`disabled_capabilities` 收窄勾选）并显示"Phase 3 未启用"提示；Engine 只读展示不属编辑入口，可保留（整卡隐藏亦合规）。`execution_phase3_enabled=true && execution_orchestrator_enabled=false`（FR-9 配置错误态）时保留只读展示并显示"部署配置错误"提示，绝不展示假成功；flags 读取失败时 fail-closed 隐藏 Phase 3 专属入口，但**不得显示"Phase 3 未启用"提示**——读取失败不等于证实 off，谎报未启用是新的误导；只读消费方式沿用 `memory-config-caps` 先例（interface + 页面 `useResource` 一次），不额外发明读取函数。React 模型/轮次编辑、保存/发布/diff 与历史发布/Run 查看**永不**被这两个开关门控——off+orchestrator-on 必须精确保持原 Phase 2 React 路径（FR-9/AC-10），禁用它们反而是违规。新增提示文案进入四语言。
- viewer 全部只读；后端仍是授权边界。所有标签、reason、错误和帮助文本进入 `zh-CN`、`zh-TW`、`en`、`hi` 四个 JSON，不硬编码。
- 使用现有 Playwright mock `/api/v1/**`，覆盖 M1–M3 或等效证据、伪造请求不进入页面、四 locale；不引入组件测试 runner。
- OpenAPI 自动包含新 internal route；审计记录 agent/version、Engine、provider/policy/probe 版本和结果摘要，不记录 secret、Memory 原文或宿主路径。指标观察 cache hit/miss/stale、probe timeout、resolution latency、snapshot rejection/start barrier failure。

## 9. 迁移、发布与回滚

### 9.1 迁移

规划 `0058_agent_execution_metadata`，当前直接前驱 `0057_industry_pack_runtime`。T2 先执行 `uv run --directory backend alembic heads` 动态重验；若目标提交 head 已变，先更新全部双语文件和 08 再实施。只新增五个 nullable JSONB 列，无默认值回填、无历史行 UPDATE、无既有序列改名；downgrade 仅在 disposable 库验证，生产回滚不依赖 downgrade。

PostgreSQL 集成默认使用独立 pgvector 容器；Alembic 读取 `AGENT_DATABASE_URL`，pytest 读取 `TEST_DATABASE_URL`。容器随机凭据仅存权限 600 的环境文件，不进仓库/文档/报告。测试时先加载环境，再把测试 URL 显式赋给 `AGENT_DATABASE_URL` 并设置临时 `AGENT_API_TOKEN`；连接配置错误是环境问题，不写成产品缺陷或通过。

### 9.2 发布顺序

1. 部署 additive migration；旧二进制可继续读写，因为新列可空且旧代码不引用。
2. 新二进制默认 `execution_phase3_enabled=false`，保持部署当前 `execution_orchestrator_enabled` 对应的原 Phase 2 路径。
3. 在专用 tenant 验证 metadata、probe/policy、快照、preview、React 对等和 C11，再仅开启 `execution_orchestrator_enabled=true` 部署的 Phase 3。
4. `execution_phase3_enabled=true && execution_orchestrator_enabled=false` 是配置错误，健康检查/启动校验与 Run 均失败关闭；不能悄悄启用 legacy。
5. 回退先关 Phase 3；off 时非 React 明确拒绝。旧 React 回部署原 Phase 2 路径；历史五列只读保留。应用回滚无需数据库 downgrade。

### 9.3 完成后的 seed 与 quickstart

严格在真实 `06-test-report*` 与 `07-acceptance-report*` 创建后：新增独立 `seed_execution_phase3.py` 风格低敏、确定性 ID、create-or-preserve 幂等示例，不伪造快照证据；随后单独接线 fresh quickstart 自动执行并验证 off/on/回滚及真实 Run 生成快照。只向已经存在的 06/07 追加证据，生产不自动插入示例。

## 10. 需求追踪

| 设计 | FR | AC | 主要验证 |
|---|---|---|---|
| ExecutionConfig/normalizer/metadata/canonical diff | FR-1、FR-2 | AC-1、AC-2 | P3-UT-01～05、P3-IT-01/02/16、P3-CM-05 |
| 四层能力、可信端口、缓存、最小权限 | FR-3、FR-4、FR-5 | AC-3～AC-5 | P3-UT-06～12、P3-IT-03～05/11、P3-CM-04/07 |
| 五 DTO、denylist、大小、一次性 commit 屏障 | FR-6 | AC-6、AC-11 | P3-UT-13～15、P3-IT-06～08/14/15、P3-CM-01/06 |
| InstructionInput/React/test Provider | FR-7 | AC-7、AC-8 | P3-UT-16～19、P3-IT-09/10 |
| 预览、flags 只读契约、AgentsPage、四语言、审计、双开关 | FR-5、FR-8、FR-9 | AC-5、AC-9、AC-10 | P3-UT-26、P3-IT-04/05/11～13/20、P3-CM-02～04/08/09；M1–M3 |

最终测试与验收不预写结果；所有环境缺口、真实历史样本、CI/生产性能与人工证据保持 `pending_env`/`not_measured`，不得通过删除硬门禁放行。
