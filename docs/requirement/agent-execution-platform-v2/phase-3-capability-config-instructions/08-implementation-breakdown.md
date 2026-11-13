# Phase 3 · 能力、配置与指令 — 实施拆解

> 状态：T1～T5 已完成（T5 验收有条件通过，条件挂 T7 前）；T6、T7、T8 已完成（合并测试线通过，无阻断项，实现与文档仍在工作树未提交）；T9 已完成（有条件通过，条件①待真实栈复跑，已并入 #128）；T10、T11 进行中，阶段测试/验收报告尚未创建；**T12、T13 已于 2026-11-13 移出本阶段**，转独立迭代跟进（issue #127 seed、#128 quickstart，见 R-39）
> 创建：2026-11-12
> 修订：2026-11-13（第三批收口：T7/T8 设计裁定 R-42～R-52 写入 §2 表（含协调者补充的清洗闸闸序与 `declared` 列重复项例外、`settings` 可选入参与四态矩阵比较基准两条），§4 T7/T8 文件清单与接线纪律同步扩列，T7 接线纪律由八条扩为十七条，并回写 03/04/05 双语；状态头与 §3 任务表改为 T6/T7/T8 已完成、T10/T11 进行中；§5 追加 off 态五列 NULL 的 PG 直证缺口与注释裁定编号语义外溢两条登记）
> 修订：2026-11-13（第二批收口：T6 状态改为已完成（测试取证＋加固轮），T6 小节新增加固轮收口条并回写 03 §6/04 P3-UT-17～19 口径，T7 小节新增 prepared 路径接线追加纪律三条（禁传 Summary/Memory 实参与同源 settings、两快照码 `_ERROR_MAP` 登记与指令层 `ConfigurationError` 不被降级的测试口径、R-32 扩参后 Protocol/实现签名一致性测试），本轮新增裁定 R-40（空 `content` 历史行透传作用域）与 R-41（Engine prepared 路径三条一致性不变量）并登记入 §2 表；状态头与 §3 任务表同步，§3 的 T9 行状态改为与状态头一致的"已完成（验收有条件通过，条件①待 T8 真实端点）"）
> 修订：2026-11-13（T6/T9 收口裁定 R-26～R-38：R-10"计算一次"语义、保留窗口表达式、prepare 同步性与 payload JSON 原生、错误码接线归属、provider 常量同源、Engine Protocol 扩参、非 slug tenant_id 阻断、写屏障入口清洗闸；§1 新规 9 禁文档依赖评审工作标签；修 R-21 的 §7.3→§7.2 错引；T6 文件清单补 `instructions/__init__.py`；T7 认领 P3-IT-19；§5 登记范围外缺陷与 skip 归因）
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
9. 评审轮次的工作标签（`D-*`、`F-*`、`M*`/`Minor-*` 等）只存在于当轮工作记录与代码/测试注释，**不进入 01–05/08 文档**；文档必须自包含地复述判据本身，后续任务不得依据这类标签定位要求，也不得新增此类引用。

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
| R-21 | `ExecutionRequest.effective_capabilities` 是裸 `dict[str,bool]`，T4 产出结构化 `EffectiveCapabilities`，03 §7.2 要求三元组，无唯一投影函数，T7/T8 各自实现会造成收窄结果分叉或原因码丢失 | 两个纯函数唯一归属 `contracts/capabilities.py` 并在 `contracts/__init__.py` 导出：`effective_capability_flags(effective)->dict[str,bool]`（恒 11 键、False 不省略、按 `CAPABILITY_ORDER`）、`effective_capability_views(effective)->tuple[EffectiveCapabilityDecision,...]`（即 §7.2 三元组，复用既有 strict DTO，不新建响应模型）。T7/T8 只能调用这两者，禁止内联推导/重排/裁剪；`ExecutionRequest` 契约不变，其 `effective_capabilities` 定义为降级视图（非授权凭据），原因码与 provenance 只存在于 `EffectiveCapabilitiesSnapshot`；消费者读缺键按 False |
| R-22 | Available 值按 workspace_generation 入键但不含 tenant/scope，收窄只在读路径；T5/T7 若直接查 cache 会产生"无受信 Workspace 却 available=true"的矛盾证据 | 键设计不变，改为接线纪律＋类型门禁：03§4.3/§5.3 明文四能力快照与 `ExecutionRequest` 的 available/effective 只取自 `CapabilityResolution`；T5 快照构造函数入参类型固定 `CapabilityResolution`（不接受 `AvailableCapabilities`/`CacheLookup`）；P3-UT-25 负控断言；旁路按 P1 缺陷返工。暂不给 `scripts/check_architecture.py` 加 import 门禁（composition 仍需构造 `CapabilityCache`），实测出现旁路再升级 |
| R-23 | 02 US-1/03 §8 "Engine 选择"字面似要求下拉与候选来源，但 Phase 3 生产 Registry 仅 `react/native/v1` 一个合法三元组，冻结契约无 Engine 目录端点 | Phase 3 的"选择"以实现为只读呈现生效三元组＋"已注册/未注册"状态 Tag（前端候选集＝生产合法集常量）；不新增目录端点、不做自由输入，该形态即 US-1/§8 的合规实现，钉入 03 §8，不可回退。真正的多候选选择归 Phase 4/5（04 P3-CM-10），届时候选必须来自 Registry metadata。不放宽 FR-2：未注册/非 React 三元组仍精确拒绝，Tag 仅是呈现提示 |
| R-24 | 03 §3.2.5 可读作"用户一编辑即须写 canonical"，前端最小写回（不为旧草稿凭空补 engine/react、空 disabled 省略 key）因此被疑违约 | 裁定：前端最小写回与 §3.2.5 一致。该条约束 canonical diff/审计层的语义变化（判据 changes 无默认三元组噪声），不约束客户端 body 键集合；服务端 PUT 恒存规范化 body 叠加 `canonical_config_diff` 抑噪是 T3 冻结行为，维持不动。禁止两端把该条读成"一编辑即补写 engine/react"或"服务端须原样存旧形状"；§3.2.5 补句消歧，04/05 判据已兼容此读法、无需改动，前端无返工 |
| R-25 | 05 M3 要求"编辑入口失效/隐藏符合开关"，但前端无途径读取 `execution_phase3_enabled`；"错误反推"无法表达"未尝试即隐藏"、无法区分 off 与 on+orchestrator-off 错配；同时前端正确判定 off+orchestrator-on 须保持 Phase 2 React 编辑可用 | 新增最小只读 `GET /api/v1/agents/execution-config-flags`（03 §7.4，先例 `memory-config-caps`）：恰两布尔 `execution_phase3_enabled/execution_orchestrator_enabled`，与 preview 同 internal management 面、Reader 权限；只读 settings、零副作用（禁 probe/Adapter/Run/缓存读取/审计）、off 与错配态均正常返回且永不回 `execution_phase3_disabled`；暴露原始值对而非合成视图，UI 按 FR-9 矩阵合成：off 隐藏 preview/收窄入口，错配态显示提示不假成功，flags 读取失败 fail-closed 隐藏；React 模型/轮次编辑与历史查看永不受 flags 门控。落 T8（实现）与 T9（消费）；新增 P3-UT-26/P3-IT-20、04 §6.1 场景与 05 M3 判据扩展；题二确认前端既有判断合规 |
| R-26 | T6 实测 `prepare_instructions()` 内 `effective()` 恰一次，而 Phase 2 的 `RuntimeFactory.for_run` 构造 Runtime 时仍会再算同一纯派生值；若把 R-10 读成"`effective()` 全局只调一次"就必须改动 Phase 2 装配路径 | "计算一次"限定为**业务渲染与有效指令组装每 Run 恰一次且可计数**（prompt 组装、Summary/Memory 渲染、保留窗口取值）；`for_run` 的第二次 `effective()` 无 I/O、无副作用、两次结果逐字段相等且消息 diff 为 0，属合规。禁止 memoize 消除；T7 允许但不要求把 prep 结果传入 Runtime 构造，传入须逐条保 Phase 2 parity；计数断言作用域限于 prepare 步 |
| R-27 | 保留窗口 `history_turns*2` 表达式现有三处（`engine.py` 入参 slice、`engine.py` 写回 slice、`runtime_factory.py` prepare slice），03 §6 禁 Provider 截断而 Engine 写回必须自算 kept/dropped | 不抽共享 helper、不移截断逻辑；一致性由 P3-UT-17（prepare 恰交末 `2*history_turns` 条、Provider 全量透传、baseline/prepared 消息与 kept/dropped 全等）钉住，T7 的 P3-IT-09/10 不得弱化。若将来必须抽，唯一归属为 `core_platform/agent_runtime` 纯函数且不得改 Engine 组装顺序/写回 slice/dropped 语义 |
| R-28 | `InstructionProvider.prepare` 为同步纯格式化，T7 若"为未来预留"改 async 将迫使 Engine/Adapter 消费点改造并移动 start 前屏障时点 | 同步签名（无 I/O、不 await、同输入产相等 payload）在 03 §6/04 P3-UT-18/19/02 AC-8 冻结；async 化属契约变更，须先改 03 §6 与 08 §2 立新裁定并同步 04/05，再改契约，禁止实现期就地改签名 |
| R-29 | `PreparedInstructions.payload: JsonValue` 在契约基类 `strict=True` 下直接拒 `tuple`/`set`（实测 `invalid-json-value`），React 消费侧又要求 `list` | Provider 必须产出 JSON 原生结构（`list`/`dict`/标量），不得依赖序列化层或运行时 coercion；React/test provider 现形已合规，无代码改动 |
| R-30 | 指令层只用 `ConfigurationError(code=INVALID_REQUEST, details.operation∈{instruction_prepare,instruction_resolve,instruction_consume})`，`RuntimeFactory` 准备失败用新 `RuntimeFault` 码 `agent_snapshot_required`/`agent_snapshot_invalid`；`error_mapper._ERROR_MAP` 未登记该两码，未映射码按 `get(code, INTERNAL_ERROR)` 降级 | 契约层不新增 `ExecutionErrorCode`；两新码由 **T7** 登记进 `_ERROR_MAP` 的 INVALID_REQUEST 组，Run 侧不得降级 `internal_error`；到 `execution_configuration_invalid` 的映射只发生在 HTTP 面——save/publish 已由 `agent_config/service.py` 接线（既有），preview 由 **T8** 复用同一映射、不建第二张表；03 §7.3 补一行记载 |
| R-31 | 生产 descriptor 在 `runtime_composition.py:147-148` 写字面量 `"react-native"/"v1"`，contracts 已有 `REACT_INSTRUCTION_PROVIDER_ID/_VERSION`（且该 builder 无 settings 入参，R-20 的 policy_version 同源亦未接线） | **T7** 必须引用常量并加 descriptor↔Provider 注册集合一致性断言（每个 enabled 生产 descriptor 的二元组可被 `resolve_instruction_provider` 命中），与 R-20 同构；`probe_id/policy_provider_id` 等无常量来源的字面量不在本轮，`policy_version` 仍按 R-20 由 settings 注入；standalone 镜像字面量由既有 parity 测试保证值一致、不强改 |
| R-32 | `adapters/react/adapter.py:33-42` 的 `RuntimeEngine` Protocol 仍 5 参，而实现已是 6 参；T7 传 prepared 输入必须扩 Protocol | 属 **T7** 交付项并写入 T7 验收点：`run` 增加带默认 `None` 的 prepared 入参（off 路径逐字不变），Adapter 传入 prepare 结果，Protocol 与实现签名一致性由测试钉住，5 参形态不得保留 |
| R-33 | `EffectiveCapabilitiesSnapshot.tenant_id` 是五类快照唯一无文法约束字符串；实测 `AGENT_TENANT_ID=/acme-corp` 被 Settings 接受后序列化整批 `snapshot_denied_host_path`(path=tenant_id)，该部署每个 Phase 3 Run `start=0`；本仓取值 `local`/slug 形不可达，外部非常规命名可达 | 选 (b)：不改字段类型（收紧只把失败从序列化期挪到构造期，且牵动 `EffectiveCapabilities`/解析请求/ports/cache 键/`Settings.tenant_id` 全链），改为 03 §5.2 明文部署前置与运维后果，04 P3-UT-14 要求"合法形态必过 + 非法形态整批拒"双向负控；Phase 3 不放宽值侧拒绝 |
| R-34 | 08 T7 现句"入参载荷必须由 serialize_execution_snapshots 产出，否则得 ExecutionSnapshotError"高估现实：`repository.py` 的 `_validated_snapshot_bodies` 只做形状+身份校验，形状合法而内容被禁的手工载荷可越过；验收判为 T7 接线前须闭环的 C3 一票否决面 | 登记为 **T7 硬性交付项**：屏障入口在形状闸之上加清洗闸（`assert_snapshot_payload_clean` 或等价 strict 再校验闸），命中即 `ExecutionSnapshotError` 且不访问数据库；判据为 P3-IT-08 的五类形状合法负控（逐列触发、随后该行五列仍 NULL）。`repository.py` 作为 T7 对 T5 文件的唯一例外 |
| R-35 | 03 §7.4 "前端单次编辑器生命周期取一次"与实测不符：React 19 StrictMode 开发态每个 GET 双发（`/me`、catalog 同样翻倍），生产构建一次，且不随 preview/save 增长；前端断言写作"≥1 且 ≤2 且与交互次数无关" | 口径改为"每次 mount 至多一次、不随交互增长"；开发态两次属 StrictMode 双执行、不属违约，超界重复读取才算违约；T9 无返工 |
| R-36 | 前端 spec 使用 `P3-FE-*`（25 个编号含 05b/10b/10c/16b，四 locale 参数化展开 37 个用例），而 04 §6.1 只有散文、证据无法逐项映射 | 编号与 M1–M3/P3-CM-08/P3-CM-05 的对应登记进 04 §6.1（新用例取未占用编号、已登记编号不复用不改义），06 直接引用该表而不另建映射表 |
| R-37 | `-m postgres` 的 28 条 skip 中 24 条文案 `Requires a test PostgreSQL role with CREATEDB` 实为 `MIGRATION_TEST_DATABASE_URL` 未提供的 opt-in skip（协调角色实测 `rolcreatedb=true, rolsuper=true`），文案极易误归因；另 `test_agent_execution_phase3_migration.py` 自带 fixture 读 `TEST_DATABASE_URL` 且不探测角色 | 04 §2 写入五类"按机制归因"口径供 06 直接引用，并登记该不对称（角色真缺 CREATEDB 时该文件 ERROR 而非 skip，不得据 error 反推角色权限） |
| R-38 | `model_not_configured` 的 errorText 句子自 initial commit 即存在于 `frontend/src/i18n/index.ts` 且不是任一 locale 字典的键，en/hi 显示整句中文；Phase 3 未触碰该文件 | 属 Phase 3 范围外既有缺陷，登记在 08 §5 与 04 P3-CM-08，不计入本阶段通过/不通过；前端显式白名单常量钉"不得新增第二个未翻译码"；修复走独立 i18n 提交/issue，不进 Phase 3 文件范围，也不得在 06/07 记作 Phase 3 缺陷或修复 |
| R-39 | 维护者于 2026-11-13 决定优先交付功能本体（T7 编排接线、T8 preview API、T10 测试报告、T11 验收），T12 示例 seed 与 T13 fresh quickstart 接线不在本轮执行 | T12/T13 移出本阶段，转独立低优先级迭代跟进：issue **#127**（T12 低敏幂等示例 seed）、issue **#128**（T13 fresh quickstart 接线与 off/on/回滚验证，依赖 #127）。原裁定 R-15 的先后顺序依然有效——seed 与 quickstart 仍必须在真实 06/07 之后，只是不在本阶段完成；07 必须把这两项如实记为"延后至 #127/#128"，禁止写成已完成，也禁止用"代码已合入"替代证据。本阶段完成定义相应收窄为 T7/T8/T10/T11 + 文档收口 |
| R-40 | 03 §6"空值不创建空消息"若按字面覆盖历史行，则 content 为空串的历史行在 Phase 3 会被拒，而 Phase 2 的 _baseline_messages 原样发送该行 —— 与 AC-7"消息序列 diff 为 0"和 US-1"旧 Agent 无需修改即可继续运行"直接冲突 | 裁定：该规则只约束注入槽（Summary/Memory）与当前用户输入；历史行一律原样透传，含 content 为空串、旧 role 词表与额外键。额外键仅在校验层保留，经 react_native_history_item 投影后不进入 payload/Engine（消费侧 react_native_messages 反而拒绝带外键条目），故 parity 成立。T7 及后续不得以"清洁化"为由重新拒绝空 content 历史行；判据见 04 P3-UT-16/17 |
| R-41 | prepared 路径与 Engine 实参可能各自为政（payload 的 current_user_input 与 run() 的 message 不一致时静默按 payload 执行、持久化却写实参），且准备侧与 Engine 侧若取自不同 settings 对象，保留窗口会静默漂移而 parity 测试恒同源、CI 抓不到 | 裁定：Engine 的 prepared 分支强制三条不变量——payload.current_user_input 等于 message 实参；payload.history 等于 Engine 按自身 settings.history_turns 算出的 kept 切片（经同一投影函数比较）；prepared 路径下 summary_message/customer_memory 实参必须为 None。违规在调用模型前抛 ConfigurationError（details.operation=instruction_consume、field 为被违反字段），不回退 baseline。T7 接线不得在 prepared 路径传 Summary/Memory 实参，且准备侧与 Engine 侧必须共用同一 effective settings 来源 |
| R-42 | Phase 3 没有外部部署可探测，probe_id/probe_version 与 descriptor/缓存键同源，"部署缺失/版本不兼容/probe 超时"在生产实现上结构性不可达；同时 03 §4.2 明文 warmer 不创建 Adapter，probe 若调用 adapter.get_capabilities 会与之直接冲突 | 生产 probe 为声明派生型（只读 registry.metadata().declared，禁调 adapter.get_capabilities），回显 context 身份、observed_at 取注入时钟、deployment_digest 为部署身份与三元组的稳定 SHA-256 且禁用 UNOBSERVED_DIGEST；三个受信端口实现集中在新 capability/production.py，仅由 composition 的 ports= 代码级注入缝替换（settings/env 不得选择端口）；AC-3/P3-IT-03/A3 的取证边界登记为：替身证明 probe 超时/异常/回显不符/workspace 缺失/策略层拒绝，生产实现必须证明 cold→一次有界 warm→available、实例声明偏差（R-43）与 disabled 只收窄；Phase 4/5 由同一 TrustedDeploymentProbe Protocol 替换实现，不预留新抽象 |
| R-43 | 本阶段 probe 为声明派生，Available 与注册声明恒同源，"部署侧声明与 Adapter 实例声明不一致"在生产上唯一可达的形态是 fresh Adapter 实例的 get_capabilities() 与 Registry 注册声明之间的偏差；无闸时分叉的 Run 会按注册声明落快照、按实例声明执行，证据与行为静默不一致 | 声明偏差闸落在 Run 路径：resolve 之后、写快照与 prepare 之前逐项比较 adapter.get_capabilities() 与 registry.metadata() 的注册声明，任一不符即 execution_configuration_invalid 失败关闭且 Adapter.start=0、五列仍 NULL；比较只针对 resolve 产生的实例，probe/warmer 仍不创建 Adapter（与 R-42 不冲突）；因拒绝早于序列化与写屏障，本闸的负控判据是"零副作用"（04 P3-IT-22） |
| R-44 | Phase 3 无版本化租户策略存储，platform ceiling 与 tenant/agent/execution 四层取值无来源；policy_revision 每轮进 key 会毒死整条 Phase 3 Run 路径（每轮 cold→policy_unavailable→必需能力缺失→失败关闭） | ceiling 为代码常量 allow-list{streaming,cancellation,tool_calling,native_events}（默认拒绝，恰等 React 声明真值，本阶段无虚假证据且 Phase 4/5 可产生真实 platform_denied），不复用 policy_harness（tool.invoke×角色轴不同）；tenant 与 execution 层一律 allowed（Effective 为六元 AND 且 _effective_one 顺序短路，结构上不可能放大 ceiling，诚实登记本阶段该两层无真实信源）；agent 层由已发布 disabled 派生；current_revision 返回按作用域常量 0 即为合规（R-17 的"禁止默认 0"只约束读取抛异常时），禁止时钟/DB 派生"每轮都变"的实现，单调不减由测试在作用域内钉住；provider 回显三项 context 值，layer_versions 四项齐全且 revision 0 |
| R-45 | execution_capability_policy_version 由 settings 注入后，standalone 镜像仍写默认 v1，test_react_descriptor_metadata_matches… 的"整体 descriptor 相等"断言在任何部署覆盖该值时必红；同时 _build_execution_orchestrator 需新增 settings 入参，四处调用点（含不在 T7 清单的 test_agent_config_execution_compat.py）必须同步 | parity 断言改为"model_dump(exclude={policy_version}) 逐字段相等 + 两侧派生来源各自钉住（生产==settings 值、standalone==settings 字段默认值）"，其余 14 字段强度不降；standalone 字面量不强改（R-31）；该 compat 测试文件与 capability/production.py 登记入 T7 文件清单，adapter_registry.py 仍不改（不新增枚举 API） |
| R-46 | warmer 的注册集只能是"已注册且 enabled 的三元组"，但 AdapterRegistry 无枚举 API 且 metadata() 对 disabled/未知必抛；AdapterRegistry 属 T3 文件不在 T7 清单 | composition 自持其注册的 AdapterDescriptor 实例并只过滤 enabled 派生 warm targets，不新增枚举 API；targets 的 scope 分量只能到部署级作用域（tenant=settings.tenant_id、agent_id=None、published_version=None、disabled=()、restriction=NO_EXECUTION_RESTRICTIONS），business/workspace 与 worker 共用提到 extension_contracts 的 DEFAULT_BUSINESS_ID/DEFAULT_WORKSPACE_ID 常量；守护测试钉"targets 数==enabled 注册数"且每个 target 可被 metadata() 命中；子系统仅在 execution_phase3_enabled 时构造，warmer.start() 紧随 extensions.start_all，finally 内第一个 aclose（warmer→resolver→contributions→extensions→engine→listener/notifier）；ready 不等 probe（start 只 create_task，/ready 不读缓存也不读两开关） |
| R-47 | PolicyCacheKey 含 tenant/business/workspace/agent/published/disabled，而 composition 启动不可能枚举这些作用域，故真实 Run 的 policy key 本阶段必然 cold；照 03 §4.2"hot path 只读缓存"字面执行会使每个 (tenant,agent,version) 组合的首个 Run 必失败一次 | 只读缓存约束的对象是 CapabilityResolver.resolve()；Run 屏障（Worker 后台路径，非 HTTP 请求）在 cold/error 时对同一 request 显式 await resolver.warm() 恰一次，仍只经同一批受信端口与同样由 settings 定的 probe/policy 超时界定；preview（HTTP 面）与本阶段保持 cold 只读并返回稳定不可用原因，故 P3-UT-22"hot path 不 probe"、AC-3/A3 cold 判据与 C11（采集前提是预热）均不削弱；失租/取消时该 await 可能留下一个后台 in-flight 轮次继续写缓存，属诊断性写入，须钉住 Adapter.start=0 |
| R-48 | 现状 runtime_fingerprint 把 execution_phase3_enabled 与全部 execution_capability_*/execution_snapshot_max_bytes 哈希进 fingerprint（exclude 集只列了 execution_orchestrator_enabled），翻开关或改调参会使已入队 Run 全报 configuration_changed，直接违反 §4.3"切换不要求重建 Runtime" | 把这些字段全部加入排除集；phase3 开关的语义变化仍由五列 provenance 与 R-17 现读兑现；静态测试"只排除编排开关"改名并扩展为"两个开关与 Phase 3 调参族均不进 fingerprint，而 model_* 变更仍使指纹变化" |
| R-49 | CapabilityCache TTL 与 probe/policy 的 observed_at/resolved_at 共用同一注入 clock，而 resolver 用 datetime.fromtimestamp(clock(), UTC)；传 time.monotonic 会给出 1970 前后的时间戳（仍是 aware datetime，能过校验但证据荒谬） | composition 只注入单一 POSIX wall-clock（time.time）可调用对象给子系统全部组件；observed_at/resolved_at 年份合理性由测试钉住；wall-clock 回拨只会使条目提前 stale（fail-closed 方向），不构成授权放大 |
| R-50 | on+orchestrator-off 若按 §9.2 字面"健康检查/启动校验失败关闭"理解成拒绝启动，会使 §7.4/R-25/M3 的"错配态提示"与 flags 端点在该态永不可观察 | 错配态不阻断进程启动：启动校验记录一次稳定告警，失败关闭落 Run 准入与终态码 execution_configuration_invalid，/ready 本阶段不加 503（04/05 无该判据）；off 态遇非 React 发布配置仍 execution_phase3_disabled，且该态只能由直接写入 agent_versions 的测试用例达到（发布/快照读路径已在 registry 精确拒绝）；Run 侧只用四个既有公开码，不新增错误码与前端文案。协调者补充两条：①_build_execution_orchestrator 的 settings 为**可选**参数（缺省取字段默认值即 off 态），生产组装根必须显式传入——因既有 baseline 测试调用点不可改；②Worker 侧四态矩阵的引擎三元组比较基准是**部署注册的 PRODUCTION_ADAPTER_SELECTOR**，不是 orchestrator 注入的 selector（后者只是 Adapter 装配缝）；已发布配置无 engine 快照的行按固定 React 三元组放行（P2-IT-14 形态不变） |
| R-51 | R-34 现句"入参载荷必须出自 serialize_execution_snapshots"只约束编排侧，而 repository._validated_snapshot_bodies 仅做形状+身份校验；若清洗闸只做 assert_snapshot_payload_clean，则 04 P3-IT-08 要求的"缺项/重复项"负控仍可落库 | 清洗闸裁定落在 repository 入口且必须是 strict 再校验形态——推荐逐列复用公开 deserialize_execution_snapshots；只调 clean 扫描结构上无法拒绝缺项与重复项；**闸序固定为：shape 校验 → startup 身份比较（不符=`audit_conflict`，不访问数据库）→ strict 清洗闸 → `engine.begin()`**；若 C11 采样显示代价过高，退路为逐列 model_validate_json+clean（同样拒缺项/重复项，省掉 canonical 往返）；编排侧保留"载荷必须出自序列化器"的构造纪律。**例外登记**：`declared_capabilities_snapshot` 列的"重复项"负控结构性不可表达（该列由定形对象承载、重复 JSON 键在解析时塌缩），故 P3-IT-08 的 5 类×列负控矩阵为 24/25 可表达，并由矩阵完备性测试钉住该例外 |
| R-52 | ExecutionConfigSnapshot 需要 canonical ExecutionConfig，但 core_platform 不得 import business AgentConfig（架构闸），而六键/legacy 别名投影只在 service.py 存在；漏传 serialize_execution_snapshots 的 max_bytes 会静默用 65536 常量（settings 允许 4096-262144）；PreparedInstructions 要传给 Adapter，而 contracts/adapter.py 属 T1 冻结且 registry 的 _validate_adapter_contract 要求 start 恰一个位置参数 | contracts/config.py 新增 execution_config_from_agent_config(mapping) 六键投影（键集合恰为 AgentConfig.normalize_execution 的集合），并以 parity 测试钉住"与 AgentConfig.execution_config() 语义相等"（旧根别名与 react 两种形态各一例）；serialize_execution_snapshots 必须显式传 settings.execution_snapshot_max_bytes，并用"上限低于载荷即拒"的负控钉住；PreparedInstructions 经 ExecutionContext 字段传递（同处增 owner/scope 字段），不改 AgentEngineAdapter.start 契约（R-32），Adapter 消费点不得同时传 summary_message/customer_memory（engine.py 的准备路径明文要求省略并做矛盾检查） |

## 3. 任务顺序总览

| 任务 | 内容 | 依赖 | 状态 |
|---|---|---|---|
| T1 | 双语 01–05/README 校准与 08 设计冻结 | 基线代码核验 | **已完成（仅文档）** |
| T2 | 迁移 `0058`、settings 与 rollout 骨架 | T1 | **已完成（规格/质量评审通过）** |
| T3 | ExecutionConfig、Registry metadata、normalizer、canonical diff | T2 | **已完成（规格/质量评审通过，修复后独立复核 APPROVED）** |
| T4 | 四层能力、可信端口、缓存/warmer、最小权限 | T3 | **已完成（含 R-16～R-22 两轮返工；验收有条件通过，关闭条件①②③已满足；构造器负控与 loader generation 二次读两项挂 T7 跟踪）** |
| T5 | 五快照 DTO、denylist/size、Repository 一次性持久化 | T2、T4 | **已完成（验收有条件通过：屏障入口清洗闸、outcome 映射表测试、tenant_id 部署前置三项挂 T7 前）** |
| T6 | InstructionInput、React/test Provider、RuntimeFactory 准备 | T3 | **已完成（通过测试取证与加固轮收口；实现与加固尚在工作树，未提交）** |
| T7 | Orchestrator/Context/Worker/composition/ReactAdapter 集成与屏障 | T5、T6 | **已完成（合并测试线通过，无阻断项；实现未提交）** |
| T8 | preview API、422 安全审计、scope 与 OpenAPI | T4、T7 | **已完成（合并测试线通过，无阻断项；实现未提交）** |
| T9 | AgentsPage、API 类型、四语言、Playwright | T3、T8 | **已完成（有条件通过，条件①待真实栈复跑，已并入 #128）** |
| T10 | 完整受影响测试、PG/迁移/C11/前端证据，创建 06 | T2–T9 | **进行中** |
| T11 | A1–A11/C1–C11/M1–M3 实际验收，创建 07 | T10 | **进行中** |
| T12 | 独立低敏幂等 Phase 3 示例 seed | T11 | **移出本阶段（R-39）→ issue #127** |
| T13 | fresh quickstart 自动接线、off/on/回滚验证、06/07 附录 | T12 | **移出本阶段（R-39）→ issue #128（依赖 #127）** |

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

- **文件**：`agent_execution/contracts/instructions.py`、`agent_execution/instructions/{__init__,react,test}_provider.py`（`__init__.py` 承载 `PRODUCTION_INSTRUCTION_PROVIDERS` 与 `resolve_instruction_provider`）、`applications/platform_runtime/runtime_factory.py`；`core_platform/agent_runtime/engine.py` 仅做等价输入接线（已实施：拆出 `_baseline_messages`/`_prepared_messages` 两分支，off 路径不动）；`backend/tests/test_agent_execution_phase3_instructions.py`、`test_runtime_engine.py`。
- **依赖/溯源**：T3；FR-7；AC-7、AC-8；P3-UT-16～19、P3-IT-09/10。
- **RED**：`uv run --directory backend pytest tests/test_agent_execution_phase3_instructions.py tests/test_runtime_engine.py tests/test_react_engine_adapter.py`，证明 Provider 缺失/重复渲染与消息兼容用例先失败。
- **GREEN**：上述 pytest + Summary/Memory 受影响测试；逐字比较 System→Summary→Memory→history→user；ruff、scoped format、架构检查。
- **验收点**：system prompt 与 Summary/Memory 各计算一次；测试 Provider 独立格式且不查 Memory；无空消息、无双写回，双 emit/ack/Outcome 不变。口径已冻结并回写 03 §6：R-10 的"一次"限于业务渲染与有效指令组装，`for_run` 的第二次 `effective()` 属同一纯派生值、保持原样（R-26，禁 memoize）；三处 `history_turns*2` 表达式不抽 helper、由 P3-UT-17 parity 钉住（R-27）；`prepare` 同步契约写死（R-28）；payload 必须 JSON 原生结构（R-29）；provider 字面量与注册集合同源属 **T7** 交付（R-31），T6 只出常量与解析函数。
- **规格评审**：Provider 只适配格式，RuntimeFactory 准备发生在 runner 前。**质量评审**：消息快照、budget/dropped/history、Provider 调用计数和错误路径完整。
- **加固轮收口（回写 03 §6、04 P3-UT-17～19；本轮新增 R-40/R-41）**：parity 优先裁定使空 `content` 历史行原样透传——"空值不创建空消息"只约束注入槽与当前用户输入（R-40；AC-7 要求与 Phase 2 基线序列 diff 为 0，`_baseline_messages` 本就原样发送这类行）；Engine prepared 路径落地三条一致性不变量（R-41；`engine.py` 的 `_check_prepared_inputs`/`_prepared_messages`），违规抛 `ConfigurationError(operation="instruction_consume", field=<被违反字段>)` 且不回退装配；两个快照错误码收敛为 `runtime_factory.AGENT_SNAPSHOT_REQUIRED`/`AGENT_SNAPSHOT_INVALID` 常量，raise 站点无字面量、并按触发条件钉住取值；原计数端口式断言（其计数不可能变化、属假覆盖）已改造为结构性保证（`InstructionInput` 九项字段集合钉死、端口传入即拒、payload 递归扫描无活动对象）；parity 比较面含事件 `(kind, data)`，仅排除 Engine 自计的 `duration_ms`；`prepare_instructions` 的 `ValidationError` 包成不回显被拒值、丢弃 `__cause__` 的受控 `ConfigurationError(operation="instruction_prepare")`；注入 system 连续块与"history 开始后不得再出现 system"由消费侧强制，Summary 先于 Memory 由 Provider 自律并以测试钉住输出顺序；React Provider 有意忽略 `engine_context`，测试 Provider 原样携带以证明该口径为 Provider 策略。本小节不记录测试数字（数字归 06）。

### T7 — 执行集成、启动屏障与双开关

- **文件**：`agent_execution/orchestration/{execution_context,orchestrator}.py`、`agent_execution/adapters/react/adapter.py`、`agent_execution/adapters/react/error_mapper.py`（登记 `agent_snapshot_required`/`agent_snapshot_invalid`）、`applications/platform_runtime/runtime_composition.py`、`core_platform/agent_runtime/worker.py`；`core_platform/agent_runtime/repository.py` 仅限写屏障入口清洗闸一处（T7 对 T5 文件的唯一例外，见 R-34）；`backend/tests/test_agent_execution_phase3_orchestration.py`、`test_execution_orchestrator.py`；`agent_execution/capability/production.py`（新增：三个生产受信端口实现）与 `capability/__init__.py`/`capability/resolver.py`（仅 loader 复用轮内 generation 与 revision 作参数，T4 遗留项②）、`contracts/config.py`（新增六键投影函数）、`extension_contracts`（新增 business/workspace 兜底常量）、`backend/tests/test_agent_execution_phase3_wiring.py`、`test_agent_config_execution_compat.py`（parity 断言改写，R-45）；四态矩阵与 Run 侧码的随行落点另登记 `adapters/react/*`（`adapter.py` 的 Protocol 扩参与 prepared 传参、`error_mapper.py` 的两快照码登记）、`applications/platform_runtime/runtime_factory.py`、`core_platform/agent_runtime/engine.py`、`tests/test_agent_execution_phase3_snapshots.py`（P3-IT-08 负控落点）。
- **依赖/溯源**：T5、T6；FR-3～FR-9；AC-3～AC-10；P3-IT-03/06～13/18/**19**、P3-CM-03/06/07/09（P3-IT-19 的 preview 投影半边归 T8）。
- **RED**：加载 PG 环境，`uv run --directory backend pytest tests/test_agent_execution_phase3_orchestration.py tests/test_execution_orchestrator.py tests/test_react_engine_adapter.py tests/test_runtime_postgres.py`，先断言 DB 失败 start=0、公开事件原序和四态矩阵。
- **GREEN**：上述 pytest；增加缓存 Runtime off→on/on→off、已 claim 行固定路径、迟到结果/取消/超时；ruff、scoped format、架构检查。
- **验收点**：Provider prepare+snapshot commit→Adapter.start；Phase 3 flag 不进 fingerprint；off/off、off/on 原样，on/off 失败关闭，on/on 完整；任何 off 非 React=`execution_phase3_disabled`；composition 接线纪律十七条：①参数全取 R-18 settings（零硬编码）、`execution_capability_policy_version`→descriptor→provider 同源（R-20）、revision 由 `current_revision` 现读不传常量/默认 0（R-17）、`execution_restriction_digest` 传 `NO_EXECUTION_RESTRICTIONS`（R-17）、`ExecutionRequest.effective_capabilities` 用 `effective_capability_flags`（R-21）、快照/请求只取 `resolution.*` 不读 cache 原值（R-22）。⑦生产 descriptor 的 `instruction_provider_id/provider_version` 引用 contracts 常量，且每个 enabled descriptor 的该二元组可被 `resolve_instruction_provider` 命中（R-31）；⑧`adapters/react/error_mapper.py` 登记 `agent_snapshot_required`/`agent_snapshot_invalid` 于 INVALID_REQUEST 组，未登记即按 `internal_error` 降级视为缺陷（R-30）。**Engine Protocol（R-32）**：`adapters/react/adapter.py` 的 `RuntimeEngine` Protocol 的 `run` 必须扩为接受 prepared 入参（默认 `None` 保 off 路径逐字不变），Adapter 传入 prepare 结果；Protocol 与 `core_platform/agent_runtime/engine.py` 实现签名的一致性须有测试钉住，5 参形态不得保留。**写屏障结果映射纪律（03 §5.3 冻结）**：`audit_conflict`→失败关闭且 `Adapter.start=0`；`not_claimed`/`lease_lost`→沿用既有失租/取消路径，禁止报成配置错误；`written`/`reused` 才允许进入 `Adapter.start`，且入参载荷必须出自 `serialize_execution_snapshots`；写屏障入口自身另设**清洗闸**——对五份 body 调 `assert_snapshot_payload_clean` 或以等价的 strict 再校验闸替代，使形状合法而内容被禁（被禁键/值、缺项、违反覆盖性）的手工载荷也在**访问数据库之前**抛 `ExecutionSnapshotError`（编程/审计错误，非运行时分类）；"绕过序列化器"因此不可能写入任何载荷（R-34 硬性交付项，负控判据见 04 P3-IT-08）。`written`/`reused` 标签在并发同载荷下可能双方都报 `written`，属诊断标签，落库结果一致。⑨三个受信端口只由 composition 的代码级 `ports=` 参数注入，settings/env 不得选择端口，off 时子系统不构造（R-42/R-46）；⑩probe 只读注册声明且绝不调 `adapter.get_capabilities()`，声明偏差在 resolve 后、prepare 前比较并失败关闭（R-42/R-43）；⑪policy ceiling 为代码常量 allow-list、tenant/execution 层 allowed、agent 层由已发布 disabled 派生、`current_revision` 恒作用域常量且禁止每轮前进（R-44）；⑫warm targets 由 composition 自持 enabled descriptor 派生，不新增 AdapterRegistry 枚举 API，作用域只到部署级并复用 extension_contracts 的 scope 常量（R-46）；⑬`execution_phase3_enabled` 与 `execution_capability_*`/`execution_snapshot_max_bytes` 全部加入 fingerprint 排除集（R-48），子系统时钟只用一个 POSIX wall-clock 可调用对象（R-49），warmer 在 `extensions.start_all` 之后 start、`finally` 内最先 aclose（次序 warmer→resolver→contributions→extensions→engine→listener/notifier），ready 不等 probe（R-46）；⑭Run 屏障 cold 时有界 `await resolver.warm()` 恰一次，preview 保持 cold 只读（R-47）；⑮双开关在每 claim 开始读一次并固定路径（worker 六处 `self.settings.*` 改读局部变量，且读取早于 fingerprint 守卫，否则 `configuration_changed` 早退路径引用未绑定局部变量），published 非 React 三元组 off→`execution_phase3_disabled`、on→`execution_engine_unavailable`，on+orchestrator-off→`execution_configuration_invalid` 且 `runtime.for_run` 调用计数恒 0（R-50/R-11）；⑯清洗闸在 repository 入口且为 strict 再校验形态（逐列复用公开 `deserialize_execution_snapshots`），只做 clean 扫描不足以拒绝缺项/重复项（R-51）；⑰`serialize_execution_snapshots` 必须显式传 `settings.execution_snapshot_max_bytes`，ExecutionConfig 由六键投影得出并与 `AgentConfig.execution_config()` parity 钉住，PreparedInstructions 经 `ExecutionContext` 字段传递而不改 `AgentEngineAdapter.start` 契约（R-52/R-32）。
- **prepared 路径接线追加纪律（03 §6 三条不变量 R-41 的收口登记，与上条 ⑦⑧ 及 R-32 段落同属 T7 验收点）**：①worker/orchestrator 走 prepared 路径时不得再传 `summary_message`/`customer_memory` 实参，且准备侧（`RuntimeFactory.prepare_instructions`）与 Engine 侧必须共用同一 effective settings 来源——违规由 `engine.py` 的 `_check_prepared_inputs` 失败关闭（`ConfigurationError`，`field="summary_message"`/`"customer_memory"`/`"history"`），禁止以"payload 优先"静默吞掉；②错误口径：两个快照码仍须按 ⑧（R-30）登记进 `_ERROR_MAP` 的 INVALID_REQUEST 组，未登记即经 `_ERROR_MAP.get(code, _INTERNAL_ERROR)` 降级 `internal_error`，视为缺陷；指令层的 `ConfigurationError` 则不同，它是 `AdapterExecutionError` 子类，其公开分类由 `map_execution_error` 的既有透传分支承载、不经 `_ERROR_MAP`，因此 T7 须有测试证明它在 Run 路径不被降级为 `internal_error`（被包成非 `AdapterExecutionError` 异常即缺陷）；③`RuntimeEngine` Protocol 按 R-32 扩参后，Adapter 把 prepare 结果传入 `run`，Protocol 与 `core_platform/agent_runtime/engine.py` 实现签名的一致性由测试钉住，同一测试还须覆盖默认 `None` 形态下 off 路径逐字不变。
- **T4 遗留跟踪项（T7 验收前必须关闭）**：①构造器负控测试补齐——`CapabilityCache` 拒绝 `ttl<=0`/`capacity<1`（cache.py:108）、`CapabilityWarmer` 拒绝非正间隔（warmer.py:35）、`CapabilityResolver` 拒绝 `probe_timeout<=0`（resolver.py:182，当前只测了 `policy_timeout`）；T7 是首个用 settings 值构造这些组件的任务，此时补最自然。②loader 内 generation/revision 二次读修正——key 用轮内观测值构造，而 loader 执行时重读传给 probe/policy context（resolver.py:439/:560），与本轮已修的 revision skew 同类；无 echo 校验故不产生假 mismatch，影响仅为 TTL 内轻微语义陈旧，修法为把 generation 与 revision 一并作 loader 参数复用轮内值，T7 须改 `capability/resolver.py`（已按 R-46/本项登记进 T7 文件清单）。③`current_revision` 实现须满足 03 §4.2 的"同一作用域单调不减"并在 T7 测试中钉住。④写屏障入口清洗闸（R-34）与两个 `RuntimeFault` 码登记（R-30）是 T7 验收前的硬性交付项，二者均为 C3/错误口径一票否决面，不得以"形状校验已足够"关闭。owner：开发角色；期限：T7 验收前。
- **规格评审**：逐项核对 R-8～R-11，不改公开 Run/SSE、Memory 或终态语义。**质量评审**：屏障调用顺序、故障注入、ContextVar/取消 gate、并发与缓存 Runtime 回归充分。

### T8 — preview API 与伪造字段安全审计

- **文件**：`applications/customer_service/platform_routes.py`（preview 与 §7.4 flags 端点及响应 DTO）、`applications/security_audit.py`（新增：伪造字段/越权拒绝的唯一审计接线）、`applications/application_factory.py`（按路由/字段路径的最小审计 hook + 全局 422 handler 的 `msg` 首行截断）、`core_platform/platform_services/identity/access.py`（`request.state.principal` 可信主体暴露，五个成功出口）、`RuntimeServices.execution_subsystem` 字段（T8 与 Run 共享同一 resolver 的官方通道，off 时恒 None）、相关 Run/Agent schema 与既有审计服务接线；`backend/tests/test_agent_execution_phase3_preview.py`、`backend/tests/test_agent_execution_phase3_flags.py`。
- **依赖/溯源**：T4、T7；FR-5、FR-8、FR-9；AC-5、AC-9、AC-10；P3-UT-11/12/22/26、P3-IT-04/05/11/17/20、P3-CM-03/04。
- **RED**：加载 PG 环境，`uv run --directory backend pytest tests/test_agent_execution_phase3_preview.py`，覆盖 strict 422、跨域 404、factory/Run=0、probe 失败、OpenAPI 白名单、`execution-config-flags` 契约缺失，以及**审计记录存在**。
- **GREEN**：上述 pytest + Agent/Run 路由回归；ruff、scoped format、架构检查。
- **验收点**：`POST /api/v1/agents/execution-preview` 支持未保存草稿；仅 Engine/安全 schema/Effective reason；可信 scope；审计不记 body/字段值/Authorization/Cookie；preview 不授权 Run；preview `capabilities` 用 `effective_capability_views`，字段与顺序按 03 §7.2，禁止自建响应模型（R-21）；新增 `GET /api/v1/agents/execution-config-flags` 仅返回两布尔、零副作用、off/错配态正常可读、永不返回领域错误（P3-UT-26/P3-IT-20，R-25）。**HTTP 面口径以 03 §7.2/§7.3 为准**：四个稳定领域错误码挂 409 `detail=<code>`（与 save/publish 同形，R-30）；`config_schema` 实际形态为 `{schema_version, fields:[{name,type,required,nullable,minimum,maximum}]}`；preview 不 `await` warm（cold→200＋稳定不可用码＋后台去重刷新，与 Run 屏障的 R-47 一次有界 warm 相对）；审计 action `security.request_rejected`、details 恰为 `{category,request_id,field_paths,error_types}`、触发条件为"审计路由∧存在 body 字段路径"，preview 越权 404 另写 `agent_scope_not_found`；可信主体取 `request.state.principal`。422 `msg` 首行截断属纵深防御，本仓 pydantic v2 已把嵌套错误拍平为单行，故无专项测试钉住其生效。
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
- R-26～R-34 已在 T7/T8 开工前冻结（T6 实施结论回写，无 Phase 2 返工）；R-35～R-38 为口径登记类裁定，不引入代码改动。冲突时同 §5 先改双语 08/03 再实施。
- **Phase 3 范围外既有缺陷（不计入本阶段通过/不通过）**：`model_not_configured` 的中文句子自 initial commit（`7dce7ba`）即以字面量存在于 `frontend/src/i18n/index.ts`，且该句子在 `zh-CN/zh-TW/en/hi` 四个字典里都不是键，en/hi 界面直接显示整句中文；Phase 3 未修改该文件。前端用例以显式白名单常量（`agent-execution-config.spec.ts` 的 `UNTRANSLATED_ERROR_COPY`）钉住"不得新增第二个未翻译码"并标注归属。修复走独立 i18n 提交/issue（把该句子键化并补齐四语言），不进 Phase 3 文件范围，也不得在 06/07 记作 Phase 3 缺陷或 Phase 3 修复（04 P3-CM-08、R-38）。
- **PG skip 归因与 C11 采集口径**：06 引用 04 §2 的"按机制归因"段，禁止把 `Requires a test PostgreSQL role with CREATEDB` 写成角色缺权限；该文案只表示 `MIGRATION_TEST_DATABASE_URL` 未提供（R-37）。C11 采集须在能跑真实 PG 的取值下进行，缺该 opt-in 变量属 `pending_env`。
- R-39：T12/T13 已移出本阶段，转 issue #127/#128 跟进；本阶段完成定义为 T7/T8/T10/T11 完成 + 文档收口，07 须如实记录该延后与其证据缺口，不得因 seed/quickstart 未做而把相关验收项写成通过。
- **off 态五列 NULL 的 PG 直证缺口（第三批登记）**：off/off 与 off/on 下"五列仍为 NULL"目前由**屏障调用计数恒 0** 与既有 PG 链条用例（claim→run→终态后五列保持 NULL）组合证明，属结构性充分，但**没有单条 PG 端到端直读断言**同时覆盖"off 态 + 真实 Run + 逐列读回 NULL"。该项如实登记为 06 的证据边界，不写成已直证；若 T11 验收要求单条直证再补用例，不在本轮补写结论。
- **代码注释中的裁定编号语义外溢（第三批登记）**：评审发现注释里的编号与实际裁定内容不完全对应——R-42/R-44 被用于"端口注入纪律"，R-51 被用于"事件原序/无快照拒绝/写一次 seam"，R-52 被用于"字节 ceiling 传递"。**以本文件 §2 表的定义为准**：注释外溢不改变裁定语义，也不构成新的裁定；T11 前不强制清理注释，06/07 引用裁定时一律回溯 §2 表原文。
