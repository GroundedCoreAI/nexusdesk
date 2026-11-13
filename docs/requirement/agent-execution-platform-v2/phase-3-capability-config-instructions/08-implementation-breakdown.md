# Phase 3 · 能力、配置与指令 — 实施拆解

> 状态：T1、T2、T3、T4 已完成；T5 后端线实施中，T9 前端线并行实施中（仅依赖已冻结契约，端到端预览证据待 T8/T13）；T6–T8 未开始，T10–T13 未开始，阶段测试/验收尚未执行
> 创建：2026-11-12
> 修订：2026-11-13（T5 返工冻结点写入：§5 快照二次校验/语义级重放/双道 identity 闸/受控 outcome 词汇，T7 新增写屏障结果映射纪律，R-9 补注）
> 修订：2026-11-13（T9 前端线契约张力裁定 R-23～R-25：单三元组 Engine 只读呈现、§3.2.5 最小写回澄清、execution-config-flags 只读契约入 T8/T9）
> 修订：2026-11-13（第1节规则2 改为四角色子代理流程：设计方案/开发（后端线+前端线并行）/测试/验收，协调者居中）
> 修订：2026-11-13（T4 返工裁定 R-17～R-22：受信 policy revision 入口、capability settings 落点与 TTL 下界、Effective 唯一投影、Available 收窄不可旁路）
> 修订：2026-11-13（T4规格评审澄清 required capability missing 语义边界，新增 R-16，同步 03 §4.1、04 P3-UT-23、05 A4）
> 依据：`01-business-goals.md`、`02-requirements.md`、`03-technical-design.md`、`04-test-plan.md`、`05-acceptance-plan.md`
> 基线：`3969258`；focused baseline 163 passed / 5 skipped；基线迁移 head `0057_industry_pack_runtime`，T2 新增 `0058_agent_execution_metadata`
> 工作约束：先 RED 后 GREEN；不预写结果；06/07 仅在实际测试/验收后创建；seed 在 06/07 后，quickstart 在 seed 后

## 1. 实施规则

1. 每项先写能因缺失目标行为而失败的测试，再实现；RED 必须确认失败原因正确，不能以收集错误/环境错误冒充。
2. 每项按四个独立子代理角色推进：**设计方案**（仅在有开放设计问题或需修订 02/03/04/05 时出场，产出裁定并写入正式文档）、**开发**（拆为后端线与前端线，可并行；两线文件范围必须互不重叠，跨线契约以本文件与 03/02 已冻结条款为准，发现契约冲突停下交协调者，不得自行改对方一侧）、**测试**（一个角色，独立取证，不修代码不裁定）、**验收**（一个角色，按 FR/AC/测试方案/05 判据出通过/有条件通过/不通过）。检查点要求不变：规格与质量两类结论都要有，且**发现问题先修复再进入下一任务**；评审可由小团队不同次检查完成，不虚构独立组织角色。协调者负责在角色之间转达结论、裁定冲突、处理环境异常（配额/分类器/容器/凭据），子代理之间不直接通信。
3. 后端命令从仓库根执行：`uv run --directory backend ...`；架构命令固定为 `uv run --directory backend python ../scripts/check_architecture.py`。
4. `ruff check src tests` 可全量运行；`ruff format --check` 只列本阶段新增/修改 Python 文件。全树 format 的无关 Memory seed 既有差异不得修改或冒称通过，06 记录边界。
5. PostgreSQL 集成默认使用独立 pgvector 容器。可复用协调环境 `nexusdesk-phase3-pg`，但每个执行者先重验容器、head、SHA。秘密只在权限 600 的 `/tmp/nexusdesk-phase3-pg.env`，不进仓库/报告。
6. Alembic 读取 `AGENT_DATABASE_URL`，pytest 读取 `TEST_DATABASE_URL`。下列 PG 命令的前置统一为：

   ```bash
   set -a; . /tmp/nexusdesk-phase3-pg.env; set +a
   export AGENT_DATABASE_URL="$TEST_DATABASE_URL"
   export AGENT_API_TOKEN="${AGENT_API_TOKEN:?set a temporary test token}"
   ```

7. 全量 pytest 由 CI 在 push/PR 执行；本地跑完整受影响套件。前端不新增组件测试框架，使用 typecheck、`check:i18n`、build、targeted Playwright。
8. 文档任何新增/修改都同步 `.md` 与 `.en.md`；生产计划不回填历史、不修改已应用迁移、不引入 Phase 4/5/6 范围。

## 2. 冲突记录与设计裁定

| 编号 | 冲突/代码现实 | 冻结裁定 |
|---|---|---|
| R-1 | Phase 0/1 正式验收未完成，Phase 2 有条件通过；旧文档写成上游均 accepted | 区分开发入口与最终上线门禁；代码合入不替代 CI、真实样本、生产性能或人工证据 |
| R-2 | Phase 2 已合入且有 06/07、seed/quickstart 附录 | 扩展现有 Registry/Orchestrator/ReactAdapter，不写“尚未开发”，不建平行执行链 |
| R-3 | `0053_routing_decisions` 已占用，head 已是 `0057_industry_pack_runtime` | 规划 `0058_agent_execution_metadata→0057`；T2 动态重验，变化时先同步全部双语文档 |
| R-4 | Registry 只有身份/factory，草稿若 `resolve` 会实例化 Adapter | 新增精确 metadata/schema 查询；草稿、发布、preview factory 调用为 0；仅执行 resolve fresh Adapter |
| R-5 | 旧根 model 字段与新 `react` 并存，默认补值可能写库/污染 diff | 单一 normalizer；同值接受、异值拒绝；历史读取无 UPDATE，canonical diff 仅抑制默认等价噪声 |
| R-6 | Available 若 hot path 同步 probe 会阻塞，若只读缓存又可能永久 cold | composition 建条目，受控后台 warmer 首轮/刷新；cold/stale/error=false，hot path 不远程 probe；测试完整生命周期 |
| R-7 | 客户端、UI 或 Adapter 声明可能被误当授权 | Declared→Available→Policy→Effective 单调收窄，默认最小权限；Workspace 缺失不可用，disabled 只收窄 |
| R-8 | 五快照与公开 `run.started` 的顺序容易混淆 | claim 公开事件保持原序；五 DTO 在 Adapter.start/runner/Runtime 副作用前一次 commit，失败 start=0 |
| R-9 | 并发重试可能覆盖快照，又不能新增第六列 | 复用 `ExecutionContext.execution_id` 作为 DTO 内 startup identity；NULL 条件写入，同身份校验复用（jsonb 语义相等），不同决策失败。**identity 不变量由入口守卫与 SQL 谓词双向强制**：五份载荷体内 `execution_id` 也必须等于本行 run id，不符返回 `audit_conflict` 且不访问数据库 |
| R-10 | ReactAdapter.start 创建 runner，RuntimeFactory 当前在 runner 内装配 | Provider prepare 与快照 commit 前移到 start；system prompt、Summary/Memory 各计算一次；React 消息顺序完全不变 |
| R-11 | 两个执行开关可形成四态，off/on 切换还受 Runtime cache 影响 | off/off 与 off/on 精确保留原 Phase 2；on/off 失败关闭；on/on 走 Phase 3；非 React off 明确拒绝；Phase 3 flag 不进 fingerprint，Worker 每个 claim 开始固定路径 |
| R-12 | preview 若返回内部能力/策略或沿用旧结果会泄露/提权 | `POST /api/v1/agents/execution-preview` strict 请求和白名单 Effective；scope 隔离，不建 Run/Adapter，不授权后续执行 |
| R-13 | 当前全局 RequestValidationError handler 只有 422，无安全审计 | T8 增加复用可信认证上下文/审计服务的接线；不记 body/字段值/秘密；P3-IT-04 直接查审计 |
| R-14 | 前端无组件测试 runner，性能若只测 helper 或无原始样本会假通过 | 用现有 Playwright 与四 locale；C11 真实 resolver/admission、缓存预热、至少 100 有效交错配对样本和 p95 原始证据 |
| R-15 | 用户要求完成后下次 quickstart 有示例数据，但不能预写测试成功 | T10/T11 先真实生成 06/07；T12 独立低敏幂等 seed；T13 fresh quickstart 接线验证并只向既有 06/07 追加 |
| R-16 | T4 曾把"必需能力缺失阻止启动"（02 AC-3/FR-4:65）读作"所有 declared=true 但未生效的能力"，与 AC-4/FR-4 的正常策略层单调收窄（如 agent_disabled，03 §7.2 preview 示例）混淆，T7 接线后会把受支持的禁用配置误判为启动阻断 | 启动阻断仅限基础设施不可用类原因码 probe_unavailable/probe_timeout/probe_stale/workspace_unavailable/policy_unavailable；not_declared 与 platform_denied/tenant_denied/agent_disabled/execution_denied 只收窄不阻断（见 03 §4.1）；02 原文不改、编号保留，以本裁定与 03 §4.1 为准；T7 准入接线、P3-UT-06～10/23 与 A3/A4 均按此判 |
| R-17 | resolver 无"向受信源查询当前 revision"的入口：T7 传固定值则 03§4.3 的 revision 失效只能靠 TTL；provider 回显真实 revision 与传入值不一致则身份校验失败直接 `policy_unavailable`，阻断合法启动 | `policy_revision` 改为受信观测：`TrustedPolicyProvider` 增同步 `current_revision(PolicyRevisionScope)->int`（本地无 I/O，与 `WorkspaceAvailabilityPort.current` 同级），resolver 构 key/context 时现读并要求 `resolve()` 回显同值；`CapabilityResolutionRequest` 删除 `policy_revision`。回显不一致→缓存 error→`policy_unavailable`（R-16 属必需能力缺失）并下轮有界刷新自愈；读取异常→`PolicySourceUnavailableError`→稳定 `execution_policy_unavailable`，禁止默认 0。`execution_restriction_digest` 仍为调用方入参但由 composition 用 `execution_restriction_digest(values)`（同 `disabled_capabilities_digest` canonical 形态）服务端计算，Phase 3 固定 `NO_EXECUTION_RESTRICTIONS`；provider 不回显该摘要 |
| R-18 | resolver/cache/warmer 构造需要 policy 超时、probe 并发上限、容量、重试间隔（及 warm 刷新周期、部署身份），FR-9 无对应 settings，T7 只能硬编码且 C11 口径不定 | 新增 6 个非秘密 settings：`execution_capability_policy_timeout_seconds=2.0(gt=0,le=10)`、`execution_capability_probe_max_concurrency=4(ge=1,le=32)`、`execution_capability_cache_capacity=512(ge=16,le=100000)`（两把缓存共用）、`execution_capability_cache_retry_seconds=5.0(gt=0,le=60)`（cache 重试与 warmer 失败退避同源）、`execution_capability_warm_refresh_seconds=10.0(gt=0,le=300)`、`execution_capability_deployment_identity="default"(Slug)`；六项进 `backend/.env.example`，`deploy/production/.env.example` 不加；T7 只准从 settings 取值；Phase 3 on 时校验 `warm_refresh < min(TTL)` |
| R-19 | settings 两 `*_cache_seconds` 允许 0，`CapabilityCache` 要求 `ttl_seconds>0`，TTL=0 变成构造期崩溃 | 统一禁止 0：settings 改 `gt=0`（int，有效下界 1s）。不实现"0=永不过期/不缓存"——需新增 `expires_at=None` 与 warmer 语义分支，且与 R-6"旧值不得当新鲜授权"冲突；`gt=0` 一处改动即令配置期与构造期边界一致并在 settings 层失败关闭。Phase 3 不提供"关闭能力缓存"形态 |
| R-20 | `execution_capability_policy_version` 无消费点，resolver 实际用 descriptor 的 policy_version，配置将静默失效 | 该值即部署声明的策略契约版本，唯一消费者是 composition：构造 `AdapterDescriptor.policy_version` 与注册同一 provider 时取该值，descriptor→PolicyContext→PolicyCacheKey→provider 回显校验构成闭环；provider 不引入第二个版本来源；类型收敛为 `AdapterVersion`（`^v[1-9][0-9]*$`）；02 FR-9 原文不改 |
| R-21 | `ExecutionRequest.effective_capabilities` 是裸 `dict[str,bool]`，T4 产出结构化 `EffectiveCapabilities`，03§7.3 要求三元组，无唯一投影函数，T7/T8 各自实现会造成收窄结果分叉或原因码丢失 | 两个纯函数唯一归属 `contracts/capabilities.py` 并在 `contracts/__init__.py` 导出：`effective_capability_flags(effective)->dict[str,bool]`（恒 11 键、False 不省略、按 `CAPABILITY_ORDER`）、`effective_capability_views(effective)->tuple[EffectiveCapabilityDecision,...]`（即 §7.2 三元组，复用既有 strict DTO，不新建响应模型）。T7/T8 只能调用这两者，禁止内联推导/重排/裁剪；`ExecutionRequest` 契约不变，其 `effective_capabilities` 定义为降级视图（非授权凭据），原因码与 provenance 只存在于 `EffectiveCapabilitiesSnapshot`；消费者读缺键按 False |
| R-22 | Available 值按 workspace_generation 入键但不含 tenant/scope，收窄只在读路径；T5/T7 若直接查 cache 会产生"无受信 Workspace 却 available=true"的矛盾证据 | 键设计不变，改为接线纪律＋类型门禁：03§4.3/§5.3 明文四能力快照与 `ExecutionRequest` 的 available/effective 只取自 `CapabilityResolution`；T5 快照构造函数入参类型固定 `CapabilityResolution`（不接受 `AvailableCapabilities`/`CacheLookup`）；P3-UT-25 负控断言；旁路按 P1 缺陷返工。暂不给 `scripts/check_architecture.py` 加 import 门禁（composition 仍需构造 `CapabilityCache`），实测出现旁路再升级 |
| R-23 | 02 US-1/03 §8 "Engine 选择"字面似要求下拉与候选来源，但 Phase 3 生产 Registry 仅 `react/native/v1` 一个合法三元组，冻结契约无 Engine 目录端点 | Phase 3 的"选择"以实现为只读呈现生效三元组＋"已注册/未注册"状态 Tag（前端候选集＝生产合法集常量）；不新增目录端点、不做自由输入，该形态即 US-1/§8 的合规实现，钉入 03 §8，不可回退。真正的多候选选择归 Phase 4/5（04 P3-CM-10），届时候选必须来自 Registry metadata。不放宽 FR-2：未注册/非 React 三元组仍精确拒绝，Tag 仅是呈现提示 |
| R-24 | 03 §3.2.5 可读作"用户一编辑即须写 canonical"，前端最小写回（不为旧草稿凭空补 engine/react、空 disabled 省略 key）因此被疑违约 | 裁定：前端最小写回与 §3.2.5 一致。该条约束 canonical diff/审计层的语义变化（判据 changes 无默认三元组噪声），不约束客户端 body 键集合；服务端 PUT 恒存规范化 body 叠加 `canonical_config_diff` 抑噪是 T3 冻结行为，维持不动。禁止两端把该条读成"一编辑即补写 engine/react"或"服务端须原样存旧形状"；§3.2.5 补句消歧，04/05 判据已兼容此读法、无需改动，前端无返工 |
| R-25 | 05 M3 要求"编辑入口失效/隐藏符合开关"，但前端无途径读取 `execution_phase3_enabled`；"错误反推"无法表达"未尝试即隐藏"、无法区分 off 与 on+orchestrator-off 错配；同时前端正确判定 off+orchestrator-on 须保持 Phase 2 React 编辑可用 | 新增最小只读 `GET /api/v1/agents/execution-config-flags`（03 §7.4，先例 `memory-config-caps`）：恰两布尔 `execution_phase3_enabled/execution_orchestrator_enabled`，与 preview 同 internal management 面、Reader 权限；只读 settings、零副作用（禁 probe/Adapter/Run/缓存读取/审计）、off 与错配态均正常返回且永不回 `execution_phase3_disabled`；暴露原始值对而非合成视图，UI 按 FR-9 矩阵合成：off 隐藏 preview/收窄入口，错配态显示提示不假成功，flags 读取失败 fail-closed 隐藏；React 模型/轮次编辑与历史查看永不受 flags 门控。落 T8（实现）与 T9（消费）；新增 P3-UT-26/P3-IT-20、04 §6.1 场景与 05 M3 判据扩展；题二确认前端既有判断合规 |

## 3. 任务顺序总览

| 任务 | 内容 | 依赖 | 状态 |
|---|---|---|---|
| T1 | 双语 01–05/README 校准与 08 设计冻结 | 基线代码核验 | **已完成（仅文档）** |
| T2 | 迁移 `0058`、settings 与 rollout 骨架 | T1 | **已完成（规格/质量评审通过）** |
| T3 | ExecutionConfig、Registry metadata、normalizer、canonical diff | T2 | **已完成（规格/质量评审通过，修复后独立复核 APPROVED）** |
| T4 | 四层能力、可信端口、缓存/warmer、最小权限 | T3 | **已完成（含 R-16～R-22 两轮返工；验收有条件通过，关闭条件①②③已满足；M2/Minor-3 挂 T7 跟踪项）** |
| T5 | 五快照 DTO、denylist/size、Repository 一次性持久化 | T2、T4 | **实施中** |
| T6 | InstructionInput、React/test Provider、RuntimeFactory 准备 | T3 | 未开始 |
| T7 | Orchestrator/Context/Worker/composition/ReactAdapter 集成与屏障 | T5、T6 | 未开始 |
| T8 | preview API、422 安全审计、scope 与 OpenAPI | T4、T7 | 未开始 |
| T9 | AgentsPage、API 类型、四语言、Playwright | T3、T8 | **实施中（前端线，提前开工；T8/T13 前仅契约级证据）** |
| T10 | 完整受影响测试、PG/迁移/C11/前端证据，创建 06 | T2–T9 | 未开始 |
| T11 | A1–A11/C1–C11/M1–M3 实际验收，创建 07 | T10 | 未开始 |
| T12 | 独立低敏幂等 Phase 3 示例 seed | T11 | 未开始 |
| T13 | fresh quickstart 自动接线、off/on/回滚验证、06/07 附录 | T12 | 未开始 |

## 4. 任务详单

### T1 — 设计修订与文档冻结（已完成）

- **文件**：主题 `README.md/.en.md`；本阶段 `01`～`05` 双语；本文件双语。未修改生产代码，未创建 06/07。
- **交付**：R-1～R-15、G/US/FR/AC/P3/A/C 编号保留，T2–T13 顺序和验证门禁。
- **验证**：文档成对/编号/stale token/diff 自检；这些是文档质量检查，不是产品测试或验收。
- **规格评审**：确认代码现状、开发入口与最终门禁、启动屏障、双开关、C11、seed 顺序均已冻结。
- **质量评审**：确认中英文对应、无预写通过、无秘密、无生产文件变更。

### T2 — 迁移、settings 与 rollout 骨架

- **文件**：`backend/migrations/versions/0058_agent_execution_metadata.py`；`core_platform/platform_services/platform_settings/settings.py`；`backend/tests/test_agent_execution_phase3_migration.py`、`test_agent_execution_phase3_settings.py`；必要时私有 ORM 字段映射。
- **依赖/溯源**：T1；FR-6、FR-9；AC-6、AC-10、AC-11；P3-UT-20、P3-IT-14/15、P3-CM-01/02。
- **RED**：先 `uv run --directory backend alembic heads` 重验；再 `uv run --directory backend pytest tests/test_agent_execution_phase3_migration.py tests/test_agent_execution_phase3_settings.py`，确认因五列/安全默认设置缺失而失败。
- **GREEN**：加载第 1 节 PG 环境，运行上述 pytest、`uv run --directory backend alembic upgrade head`、并发/旧行验证及 disposable downgrade；`uv run --directory backend ruff check src tests`；`ruff format --check` 仅本任务文件；架构检查。
- **验收点**：只新增五可空 JSONB 列，无 backfill/第六列/历史迁移修改；off 默认，probe/policy/cache/size 边界严格，无秘密。
- **规格评审**：迁移链与五 DTO/公开事件边界符合 R-3/R-8/R-9。**质量评审**：真实 PG 证据、可逆性、旧二进制兼容、format 边界完整。

### T3 — ExecutionConfig、Registry metadata 与 AgentConfig 兼容

- **文件**：`agent_execution/contracts/config.py`、`registry/adapter_registry.py`、`business_capabilities/agent_config/service.py`；`backend/tests/test_agent_execution_phase3_config.py`、`test_agent_execution_registries.py`、`test_agent_config_execution_compat.py`。
- **依赖/溯源**：T2；FR-1、FR-2；AC-1、AC-2；P3-UT-01～05/21、P3-IT-01/02/16、P3-CM-05。
- **RED**：`uv run --directory backend pytest tests/test_agent_execution_phase3_config.py tests/test_agent_execution_registries.py tests/test_agent_config_execution_compat.py`，覆盖别名、未知三元组、factory=0、读取无 UPDATE、默认 diff 无噪声。
- **GREEN**：上述 pytest + `test_agent_model_required.py` 等模型/工具受影响测试；ruff、 scoped format、架构检查。
- **验收点**：同一 normalizer 服务草稿/发布/preview/执行/diff；严格 DTO、精确 metadata、fresh Adapter 语义不变，历史 JSONB 不改写。
- **规格评审**：逐条核对 AC-1/2 与旧模型/工具权限不绕过。**质量评审**：不可变性、冲突字段路径、调用计数、canonical diff 不掩盖真实变化。

### T4 — 能力分层、可信端口与缓存/warmer

- **文件**：`agent_execution/contracts/capabilities.py`；`agent_execution/capability/{ports,resolver,cache,warmer}.py`；`backend/tests/test_agent_execution_phase3_capabilities.py`。
- **依赖/溯源**：T3；FR-3、FR-4、FR-5；AC-3、AC-4、AC-5；P3-UT-06～12/22/23、P3-IT-03/11、P3-CM-07（R-16 见 03 §4.1）。
- **RED**：`uv run --directory backend pytest tests/test_agent_execution_phase3_capabilities.py`，先覆盖 cold/stale、workspace_required、单调收窄、未知策略、完整 cache key 和 warmer 关闭。
- **GREEN**：上述 pytest；重复运行验证 fake clock 无等待/后台任务泄漏；ruff、scoped format、架构检查。
- **验收点**：composition/受控后台 warmer 负责首轮与刷新，hot path 只读；miss/stale/error 不可用；Available≤Declared，Effective 逐层收窄；未知能力/策略失败关闭。
- **返工范围（R-16～R-22）**：`capability/ports.py` 增 `PolicyRevisionScope` 与 `TrustedPolicyProvider.current_revision`；`capability/resolver.py` 删除请求字段 `policy_revision`、改由 provider 每轮现读一次并把该观测值贯穿 key/loader/echo 校验、**删除回退分支使 `EffectiveCapabilities.policy_revision` 恒等于本轮现读值**、新增 `PolicySourceUnavailableError`；`contracts/capabilities.py` 新增 `execution_restriction_digest`/`NO_EXECUTION_RESTRICTIONS` 与两个投影函数并在 `contracts/__init__.py` 导出；`platform_settings/settings.py` 增 6 字段、两 TTL 改 `gt=0`、`policy_version` 改 `AdapterVersion`、`execution_phase3_enabled` 时的 `warm_refresh < min(TTL)` 校验；`backend/.env.example` 增 6 行；`test_agent_execution_phase3_settings.py` 的 0 值接受断言改为拒绝，`test_agent_execution_phase3_capabilities.py` 的请求字段集合断言同步。测试对应 P3-UT-20/23/24/25。
- **规格评审**：检查 R-6/R-7、缓存身份/租户/版本/revision/digest/generation 与最小权限。**质量评审**：并发 singleflight、超时、生命周期、原因码和脱敏 DTO 可重复验证。

### T5 — 五快照与一次性持久化

- **文件**：`agent_execution/contracts/snapshots.py`、`agent_execution/capability/snapshots.py`、`core_platform/agent_runtime/repository.py`、`core_platform/agent_runtime/schemas.py`；`backend/tests/test_agent_execution_phase3_snapshots.py`。
- **依赖/溯源**：T2、T4；FR-6；AC-6、AC-11；P3-UT-13～15、P3-IT-06～08/18、P3-CM-06。
- **RED**：加载 PG 环境，`uv run --directory backend pytest tests/test_agent_execution_phase3_snapshots.py tests/test_runtime_postgres.py`，确认五 DTO、嵌套 denylist、单类大小、NULL 条件写入尚未满足。
- **GREEN**：上述 pytest；并发/重试和 DB commit failure 实测（注入须让 UPDATE 真正执行后再失败）；ruff、scoped format、架构检查。
- **验收点**：五 DTO strict/versioned；递归敏感扫描不回显原值（值侧路径拒绝作用于所有字符串值，为有意收窄并有合法形态负控）；每类独立 65536 默认上限（决定性断言区分共享总额）；序列化对 canonical 文本二次严格校验，`model_copy` 不得成为落库通道；重放提供语义级保证、接受 `str \| Mapping`、类型误用与缺失错误码可区分；execution_id 在 DTO 内，无第六列，且入口守卫与 SQL 谓词双向绑定本行 run id；写屏障返回受控分类 `written/reused/audit_conflict/not_claimed/lease_lost`（不含载荷内容）；一次 commit 后任何终态不改写（逐字段比较完整存储载荷）；四能力快照构造签名只接受 `CapabilityResolution`，其 available/effective 已含 Workspace 收窄（R-22）。
- **规格评审**：确认公开 `run.started` 仍在 claim，不在本任务提前改 Orchestrator 顺序。**质量评审**：事务原子性、写一次条件、序列化稳定性、公开白名单与日志无秘密。

### T6 — Instruction Provider 与 React 指令准备

- **文件**：`agent_execution/contracts/instructions.py`、`agent_execution/instructions/{react,test}_provider.py`、`applications/platform_runtime/runtime_factory.py`；必要时 `core_platform/agent_runtime/engine.py` 仅做等价输入接线；`backend/tests/test_agent_execution_phase3_instructions.py`、`test_runtime_engine.py`。
- **依赖/溯源**：T3；FR-7；AC-7、AC-8；P3-UT-16～19、P3-IT-09/10。
- **RED**：`uv run --directory backend pytest tests/test_agent_execution_phase3_instructions.py tests/test_runtime_engine.py tests/test_react_engine_adapter.py`，证明 Provider 缺失/重复渲染与消息兼容用例先失败。
- **GREEN**：上述 pytest + Summary/Memory 受影响测试；逐字比较 System→Summary→Memory→history→user；ruff、scoped format、架构检查。
- **验收点**：system prompt 与 Summary/Memory 各计算一次；测试 Provider 独立格式且不查 Memory；无空消息、无双写回，双 emit/ack/Outcome 不变。
- **规格评审**：Provider 只适配格式，RuntimeFactory 准备发生在 runner 前。**质量评审**：消息快照、budget/dropped/history、Provider 调用计数和错误路径完整。

### T7 — 执行集成、启动屏障与双开关

- **文件**：`agent_execution/orchestration/{execution_context,orchestrator}.py`、`agent_execution/adapters/react/adapter.py`、`applications/platform_runtime/runtime_composition.py`、`core_platform/agent_runtime/worker.py`；`backend/tests/test_agent_execution_phase3_orchestration.py`、`test_execution_orchestrator.py`。
- **依赖/溯源**：T5、T6；FR-3～FR-9；AC-3～AC-10；P3-IT-03/06～13/18、P3-CM-03/06/07/09。
- **RED**：加载 PG 环境，`uv run --directory backend pytest tests/test_agent_execution_phase3_orchestration.py tests/test_execution_orchestrator.py tests/test_react_engine_adapter.py tests/test_runtime_postgres.py`，先断言 DB 失败 start=0、公开事件原序和四态矩阵。
- **GREEN**：上述 pytest；增加缓存 Runtime off→on/on→off、已 claim 行固定路径、迟到结果/取消/超时；ruff、scoped format、架构检查。
- **验收点**：Provider prepare+snapshot commit→Adapter.start；Phase 3 flag 不进 fingerprint；off/off、off/on 原样，on/off 失败关闭，on/on 完整；任何 off 非 React=`execution_phase3_disabled`；composition 接线纪律六条：参数全取 R-18 settings（零硬编码）、`execution_capability_policy_version`→descriptor→provider 同源（R-20）、revision 由 `current_revision` 现读不传常量/默认 0（R-17）、`execution_restriction_digest` 传 `NO_EXECUTION_RESTRICTIONS`（R-17）、`ExecutionRequest.effective_capabilities` 用 `effective_capability_flags`（R-21）、快照/请求只取 `resolution.*` 不读 cache 原值（R-22）。**写屏障结果映射纪律（T5 D-3 冻结）**：`audit_conflict`→失败关闭且 `Adapter.start=0`；`not_claimed`/`lease_lost`→沿用既有失租/取消路径，禁止报成配置错误；`written`/`reused` 才允许进入 `Adapter.start`，且入参载荷必须由 `serialize_execution_snapshots` 产出（否则得 `ExecutionSnapshotError`，属编程/审计错误而非运行时分类）。`written`/`reused` 标签在并发同载荷下可能双方都报 `written`，属诊断标签，落库结果一致。
- **T4 遗留跟踪项（T7 验收前必须关闭）**：①构造器负控测试补齐（M2）——`CapabilityCache` 拒绝 `ttl<=0`/`capacity<1`（cache.py:108）、`CapabilityWarmer` 拒绝非正间隔（warmer.py:35）、`CapabilityResolver` 拒绝 `probe_timeout<=0`（resolver.py:182，当前只测了 `policy_timeout`）；T7 是首个用 settings 值构造这些组件的任务，此时补最自然。②loader 内 Workspace generation 二次读修正（Minor-3）——key 用轮内观测的 generation 构造，而 loader 执行时重读 generation 传给 probe/policy context（resolver.py:439/:560），与本轮已修的 revision skew 同类；无 echo 校验故不产生假 mismatch，影响仅为 TTL 内轻微语义陈旧，修法为 loader 复用轮内值作参数。③`current_revision` 实现须满足 03 §4.2 的"同一作用域单调不减"并在 T7 测试中钉住。owner：开发角色；期限：T7 验收前。
- **规格评审**：逐项核对 R-8～R-11，不改公开 Run/SSE、Memory 或终态语义。**质量评审**：屏障调用顺序、故障注入、ContextVar/取消 gate、并发与缓存 Runtime 回归充分。

### T8 — preview API 与伪造字段安全审计

- **文件**：`applications/customer_service/platform_routes.py`、`applications/application_factory.py`（仅最小按路由/字段路径审计 hook）、相关 Run/Agent schema 与现有审计服务接线；§7.4 flags 端点与响应 DTO（归入同一测试文件）；`backend/tests/test_agent_execution_phase3_preview.py`。
- **依赖/溯源**：T4、T7；FR-5、FR-8、FR-9；AC-5、AC-9、AC-10；P3-UT-11/12/22/26、P3-IT-04/05/11/17/20、P3-CM-03/04。
- **RED**：加载 PG 环境，`uv run --directory backend pytest tests/test_agent_execution_phase3_preview.py`，覆盖 strict 422、跨域 404、factory/Run=0、probe 失败、OpenAPI 白名单、`execution-config-flags` 契约缺失，以及**审计记录存在**。
- **GREEN**：上述 pytest + Agent/Run 路由回归；ruff、scoped format、架构检查。
- **验收点**：`POST /api/v1/agents/execution-preview` 支持未保存草稿；仅 Engine/安全 schema/Effective reason；可信 scope；审计不记 body/字段值/Authorization/Cookie；preview 不授权 Run；preview `capabilities` 用 `effective_capability_views`，字段与顺序按 03 §7.2，禁止自建响应模型（R-21）；新增 `GET /api/v1/agents/execution-config-flags` 仅返回两布尔、零副作用、off/错配态正常可读、永不返回领域错误（P3-UT-26/P3-IT-20，R-25）。
- **规格评审**：HTTP 状态、DomainError 稳定映射与 R-12/R-13 一致。**质量评审**：直接查审计而非只看 422，响应递归扫描无快照/probe/policy/path 泄露。

### T9 — AgentsPage、四语言与 Playwright

- **文件**：`frontend/src/shared/api/client.ts`、`features/agents/AgentsPage.tsx`、`agents.css`、必要的 1–2 个同目录组件；`frontend/src/i18n/locales/{zh-CN,zh-TW,en,hi}.json`；`frontend/tests/agent-execution-config.spec.ts`。
- **依赖/溯源**：T3、T8；FR-1、FR-5、FR-8；AC-1、AC-2、AC-5、AC-9；P3-CM-08；M1–M3。
- **RED**：`cd frontend && npx playwright test tests/agent-execution-config.spec.ts`，先验证旧 Agent 无默认 dirty、preview 只读、disabled 只收窄、冲突错误和四语言。
- **GREEN**：`cd frontend && npm run typecheck && npm run check:i18n && npm run build && npx playwright test tests/agent-execution-config.spec.ts tests/agent-memory-config.spec.ts`；保存截图/trace/网络证据。
- **验收点**：复用现有 antd/AgentModelPicker/样式，viewer 只读；preview 不创建 Run；`zh-CN/zh-TW/en/hi` 无硬编码回退；不引入组件测试 runner；M3 声明式门控——消费 03 §7.4 flags：off 隐藏 preview/收窄入口，React 模型/轮次编辑与历史查看不受门控，错配态显示提示不假成功，flags 读取失败 fail-closed 隐藏（R-25）。
- **契约张力裁定（R-23/R-24/R-25）**：Engine 区只读呈现判定合规（R-23，无返工）；`patchReactConfig` 最小写回判定合规（R-24，无返工）；T9 返工范围为消费 §7.4 flags 的声明式隐藏/提示与对应 Playwright mock 及断言（R-25），文件范围仍仅 `frontend/`。
- **规格评审**：M1–M3 或等效证据、canonical dirty/diff 和“预览不授权”完整。**质量评审**：API 类型、可访问名称、四语言、请求断言和既有 Agent 编辑回归。

### T10 — 完整受影响验证与 06

- **文件**：T2–T9 所有测试/实现；`backend/tests/test_agent_execution_phase3_performance.py`；实际执行后新增 `06-test-report.md` 与 `.en.md`。
- **依赖/溯源**：T2–T9；全部 FR/AC、P3-UT/IT/CM；重点 C11。
- **RED/负控**：`uv run --directory backend pytest tests/test_agent_execution_phase3_performance.py` 先用不足 100 样本/缺环境负控验证结果为 `not_measured` 或 `pending_env`，不将其写成产品通过或产品缺陷；检查 06 尚不存在。
- **GREEN**：运行 T2–T9 全部受影响 pytest（含真实 PG/迁移）、ruff、scoped format、架构、前端四项；真实 warmed-cache resolver/admission 同环境交错采集至少 100 有效配对样本并保存原始数据/p95；目标 SHA 全量 CI 后续纳入报告。
- **报告门禁**：仅依据实际命令/输出创建双语 06，逐项列 P3-UT/IT/CM、环境、SHA、skip、pending_env、format 基线和 C11 原始证据；未满足不得进入 T11。
- **规格评审**：独立核对每个 P3 编号均有证据，硬门禁未删。**质量评审**：复核原始数据可复算、样本有效、无秘密、报告不夸大 CI/生产结论。

### T11 — 实际验收与 07

- **文件**：引用既有 06/CI/数据库/Playwright 证据；实际验收后新增 `07-acceptance-report.md` 与 `.en.md`。
- **依赖/溯源**：T10；A1–A11、C1–C11、M1–M3、G1–G4、US-1～US-6。
- **RED/前置**：确认 06 双语存在且出口满足；缺项保持未验收，不创建“通过”07。需要补查的命令只按 04 对受影响项执行，不重复整套手工测试。
- **GREEN/证据**：验收负责人/执行人（可同人）核对 A/C、完成少量 M 项或认可等效 Playwright，复核 C11、迁移/回滚与上游上线缺口，形成单一结论。
- **报告门禁**：实际验收后才写双语 07；任一 veto、C11、跨租户、泄密、非 React 静默降级失败均不得通过；环境缺失如实保留。
- **规格评审**：每个 A 对应正确 AC/FR/G/US，最终上线门禁与开发入口不混淆。**质量评审**：证据链接、实际/预期、遗留 owner/期限和验收记录真实完整。

### T12 — 验收后独立示例 seed

- **文件**：`backend/src/agent_platform/applications/seed_execution_phase3.py`；必要的低敏 fixture；`backend/tests/test_execution_phase3_seed.py`。此时不得改 quickstart 自动接线。
- **依赖/溯源**：T11 且真实 06/07 已存在；支持后续 US-1/US-6 演示，不作为 FR/AC 测试证据替代品。
- **RED**：加载 PG 环境，`uv run --directory backend pytest tests/test_execution_phase3_seed.py`，先验证模块/确定性示例/幂等不存在。
- **GREEN**：上述 pytest；连续执行 seed 两次，验证 create-or-preserve、ID 稳定、无重复、无运行时副作用；ruff、scoped format、架构检查。
- **验收点**：低敏 typed Engine/React/disabled 示例和必要安全 demo Profile 资源；不伪造五快照、不创建 Run、不自动授予能力、不影响生产 opt-in。
- **规格评审**：确认严格后置于验收且示例范围不含 Host/Codex/秘密。**质量评审**：幂等、保留用户修改、敏感扫描和独立运行证据。

### T13 — fresh quickstart 接线、验证与报告附录

- **文件**：`deploy/container/bootstrap.py` 及现有 quickstart 启动链最小改动；T12 seed；验证后向**已存在**的 `06-test-report.md/.en.md`、`07-acceptance-report.md/.en.md` 追加附录。
- **依赖/溯源**：T12；验证 AC-10、P3-CM-02/09 的部署形态；不得重写 T10/T11 原结论。
- **RED**：在未接线 fresh 环境确认 bootstrap 不产生 Phase 3 示例，记录为缺失自动接线，而非伪造产品测试失败；检查待追加的 06/07 均已存在。
- **GREEN**：在专用 fresh 环境运行 `sh nexusdesk quickstart`，确认 seed 自动且幂等；验证默认 off、Orchestrator off/on 原路径、Phase 3 on+Orchestrator on、on+off 失败关闭、非 React off 拒绝、真实 Run 生成快照及应用回滚；再次启动/执行 seed 验证无重复。
- **证据**：保存容器/迁移/seed/off/on/rollback/真实 Run 快照与敏感扫描结果，向既有 06/07 双语追加验收后 quickstart 附录；生产不自动插入示例。
- **规格评审**：顺序确为 seed→fresh quickstart→附录，未提前创建/覆盖 06/07。**质量评审**：fresh 环境、重复启动、双开关、回滚、真实快照和无秘密证据可复现。

## 5. 完成定义与执行协调项

- T2–T9 每项只有在 RED/GREEN、两类评审、溯源和文档同步完成后才可关闭。
- T10/T11 的报告是实际结果，不是本计划的预期；T12/T13 不得被提前并行到验收前。
- **执行协调项（非架构未决）**：T2 重验迁移 head；T10 协调目标 SHA 的 CI、独立 PG、真实性能环境与经授权历史样本；T11 明确同一小团队的验收负责人/执行人及上游缺口对上线范围的影响；T13 使用隔离 fresh quickstart 环境，避免破坏开发者现有栈。
- 若这些环境/证据不可得，对应项保持 `pending_env` / `not_measured`，状态不得写成 DONE 或通过；不得通过降低 C11、删除安全审计、跳过四语言或伪造 quickstart 证据来放行。
- R-17/R-18/R-19/R-20/R-21/R-22 已在 T5、T7、T8 开工前冻结；T7/T8 若与这些裁定冲突，先改 08/03 双语并同步 02/04/05，再实施。
- R-23/R-24/R-25 已在 T8 开工与 T9 返工开工前冻结；T8/T9 若与这些裁定冲突，先改 08/03 双语并同步 04/05，再实施；02 保持不动，除非裁定本身变更需求语义。
