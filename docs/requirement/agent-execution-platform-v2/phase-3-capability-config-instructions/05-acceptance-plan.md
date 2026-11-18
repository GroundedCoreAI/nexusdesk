# Phase 3 · 能力、配置与指令 — 验收方案

> 状态：待实施（上线前执行；当前无验收结果、未创建 07）
> 创建：2026-11-02
> 修订：2026-11-18（范围限定验收修订：C11 由性能专用门槛改为开关完整性/回滚的显式功能门槛，原"≥100 配对样本/p95 ≤50ms/真实 resolver 性能"口径及结论封顶规则废止，仅保留为历史上下文或另立独立跟进项；CI provenance/最终 PR head CI run/URL、真实或授权历史样本、多样本/大样本量要求不再作为阶段验收门禁或结论上限；A1～A11、C1～C10 的功能正确性、开关完整性（默认 off/显式 on/错配态 fail closed/无静默降级/回滚）、租户隔离、Secret 处理、快照/数据完整性、迁移、终态语义、副作用/清理、无 P0/P1 与单一验收负责人记录仍为门禁；高风险开关启用另附独立审批。历史测试数字与结论不追溯修改；#127/#128 维持延后边界，不写成已完成）
> 修订：2026-11-13（第三批收口：T7/T8 裁定落验收——A3 增加取证边界与生产可观察信号、A4 增加平台 ceiling 与 revision 常量说明、A6/C5 钉"已分类屏障失败终态永不为 `execution_error`"、A10 增加 fingerprint 排除集/错配态仍可启动/`runtime.for_run==0`、C2/C9 增加生产端口形态与 Run 侧码纪律；对应 R-42～R-52）
> 修订：2026-11-13（§6 与环境表登记 T12/T13 移出本阶段、转 issue #127/#128（08 R-39），验收范围相应收窄）
> 修订：2026-11-13（M3 判据锚定 03 §7.4 execution-config-flags 声明式门控，对应 R-25）
> 修订：2026-11-13（T4 返工裁定 R-17～R-22：受信 policy revision 入口、capability settings 落点与 TTL 下界、Effective 唯一投影、Available 收窄不可旁路）
> 修订：2026-11-13（A4 补充必需能力缺失与策略收窄的启动阻断边界，对应 R-16）
> 修订：2026-11-12（开发入口与最终门禁、C11 实测、双开关与验收后 seed）
> 修订：2026-11-17（统一为最小核心团队验收标准：单一验收负责人、阶段验收与高风险能力启用分离；技术判据与硬门槛不变）
> 依据：`01-business-goals.md`（G1–G4、成功指标）、`02-requirements.md`（AC-1–AC-11）、`04-test-plan.md`

## 1. 范围与轻量责任

确认 AC-1～AC-11、C1～C11 与 M1–M3 有实际证据，覆盖兼容、安全、快照、四语言和回滚；性能仅作为历史上下文/另立跟进项，不作为本阶段验收门禁。验收负责人组织并作单一结论，执行人准备环境/补查/整理证据，两者可为同一人；不虚构产品、QA、业务、安全、运维等独立角色，也不要求多角色签字。开发自验不等于真实用户验收或独立审计。阶段验收通过不构成任何高风险能力或后续阶段的启用授权。

## 2. 开发入口、验收前置与最终上线门禁

**开发入口已满足到可规划/可实施程度**：基线 `3969258` 已有 Phase 1/2 代码，focused baseline 为 163 passed / 5 skipped。Phase 0/1 正式验收尚未完成，Phase 2 为有条件通过且生产性能、CI/真实部署、人类 UAT/签字与持久证据仍有缺口；不得写成上游全部正式验收完成。

| 环境 | 用途 |
|---|---|
| 类生产 React + 受控模型/工具 | 功能、真实配置/性能、Summary/Memory 回归 |
| 独立 pgvector PostgreSQL + LocalTestAdapter | 能力、Adapter.start 屏障、失败/取消/超时、跨租户、迁移 |
| quickstart 双容器（demo 模型） | 验收完成后的 seed 自动接线、默认 off、on、回滚验证（**本阶段不执行，延后至 issue #128**，见 §6 与 08 R-39） |
| disposable 存量库副本 | 在线迁移、并发、旧二进制回滚与 downgrade |
| 前端验收构建 + 现有 Playwright | Engine 配置、只读 preview、四语言、M1–M3 等效证据 |

**进入 A/C 验收前置**：T2–T9 完成；实际 `06-test-report.md/.en.md` 已创建且 P3-UT/IT/CM 全通过；无 P0/P1；实施时动态重验迁移链；至少两个专用 tenant/独立 scope；证据完成敏感扫描。CI 全量结果可得性、真实或授权历史样本、C11 性能 ≥100 配对样本/p95 目标自 2026-11-18 起不再作为阶段验收入口门禁，仅为历史上下文或另立独立跟进项。（历史口径保留：目标 SHA 的 CI 全量结果可得、C11 ≥100 配对样本达标且缺环境保持 `pending_env` 不得通过——已废止。）

**最终上线门禁**：A1～A11、C1～C11 全通过（C11 为开关完整性/回滚功能门槛，见 §5），M1–M3 完成或有等效自动化证据；本阶段功能承诺不因未测性能、CI provenance 或真实历史样本缺失而阻断。条件通过不能覆盖任何一票否决项；高风险开关启用须另附独立审批记录，与阶段验收分离。（历史口径保留：上游真实历史样本、CI/真实部署、生产性能与人工验收缺口须关闭或阻断相应上线范围——已废止，不构成本阶段门禁。）

## 3. 功能验收（A1～A11）

| # | 对应 | 验收步骤 | 通过判据 | 溯源 |
|---|---|---|---|---|
| A1 | AC-1 | 导入合法旧样本，读取/执行 React，再正常保存发布 | 默认三元组正确；模型/工具/Summary/Memory diff 为 0；读取无 UPDATE，diff 无默认噪声 | FR-1；G1；US-1 |
| A2 | AC-2 | 保存合法 React，提交未知三元组/latest/类型/额外/别名异值 | 合法精确解析；非法 100% 稳定拒绝；metadata 校验 factory/Adapter 调用为 0 | FR-2；G1；US-2 |
| A3 | AC-3 | 模拟部署缺失、版本不兼容、冷/过期 probe、超时与 Workspace 缺失 | cold/stale 不可用，后台成功才可用；Available 不超出 Declared；必需能力阻断；`policy_revision` 来自受信策略源现读而非调用方传入（R-17），R-18 的六项 settings 在 composition 全部有落点（无硬编码）；**取证边界（R-42/R-43）**：部署缺失/版本不兼容/probe 超时在本阶段生产实现上结构性不可达，只由注入的 probe/policy 替身证明，而生产实现必须可观察 cold→一次有界 warm 成功→available 与实例声明偏差（`resolve` 后、`prepare` 前比较，React start 恒 0） | FR-3；G2；US-2、US-3 |
| A4 | AC-4 | 各层拒绝同一能力并尝试下层允许 | Effective 始终拒绝；快照逐层解释来源、版本、原因；仅策略层收窄的配置仍可启动（必需能力缺失不含策略拒绝，见 R-16）；生产实现的可观察性（R-44）：Phase 3 平台 ceiling 为代码常量 allow-list，被拒的七项在本阶段 declared=false 故被 `not_declared` 短路，因此 `platform_denied` 只有以测试注册的 Engine 才能观察（Phase 4/5 注册声明 terminal_execution 的 Engine 时在生产实现上可达）；tenant/execution 层本阶段无真实信源，如实登记为完备性缺口而非缺陷 | FR-4；G2；US-3 |
| A5 | AC-5 | 原始 HTTP 伪造各层字段并跨 tenant/scope preview | 提权/跨域为 0；422/领域错误外还须查到安全审计，且无 body/字段值/秘密；preview 不建 Run；preview 三元组与同 scope resolver 输出逐字节一致，无原因码丢失（R-21） | FR-5；G2；US-3 |
| A6 | AC-6 | 检查四类终态快照，注入超限、嵌套秘密与 DB 失败 | Adapter.start 前五类一次 commit 且不可变；失败 start=0；公开 `run.started` 顺序不变；历史 NULL/公开白名单正确；已分类的屏障失败终态**永不**为 `execution_error`（序列化/denylist/缺项/超限/`audit_conflict` 给 `execution_configuration_invalid`，失租/未 claim 给既有 `worker_lost`） | FR-6；G4；US-5 |
| A7 | AC-7 | 重放空态、Summary、Memory、组合、开关、截断 | React 顺序、文案、budget、日志、写回 diff 为 0，无重复/空消息 | FR-7；G3；US-4 |
| A8 | AC-8 | 同一 InstructionInput 交 React/测试 Provider | 原生格式独立；业务渲染一次；无 ReAct 化或 Provider 降级 | FR-7；G3；US-4 |
| A9 | AC-9 | 编辑未保存草稿并 preview，变更策略，切换四语言 | Effective 只读/重算，disabled 只收窄；四语言完整；无内部快照/提权，preview 不授权 Run | FR-4、FR-5、FR-8；G1、G2；US-1、US-3 |
| A10 | AC-10 | 遍历双开关、缓存 Runtime off→on/on→off、非 React、历史与应用回滚 | off 保留部署原 Phase 2 路径；on+orchestrator off 失败关闭且 `runtime.for_run` 调用计数恒 0；非 React 明确失败；已 claim 行路径固定；历史可读无需 downgrade；`execution_phase3_enabled` 与 `execution_capability_*`/`execution_snapshot_max_bytes` 均不进 fingerprint（翻开关或改调参不使已入队 Run 报 `configuration_changed`，R-48）；on+orchestrator-off 错配态进程仍启动且 `GET /agents/execution-config-flags` 在该态正常可读（R-50） | FR-8、FR-9；G4；US-6 |
| A11 | AC-11 | 动态核验迁移链，存量副本升级/并发，disposable downgrade | `0058_agent_execution_metadata` 当前前驱 `0057_industry_pack_runtime`；只新增五可空列，旧行 NULL，不改历史迁移 | FR-6；G1、G4；US-5、US-6 |

每项记录执行人、日期、环境、目标 SHA、前置数据、操作、预期/实际、判定及证据链接。优先引用 06 的 UT/IT/CM、CI、PG、Playwright 原始结果，不重复整套手工测试；合入、skip、`pending_env` 均不等于通过。

## 4. 少量关键人工检查

仅补自动化未覆盖的实际界面/回滚操作，记录执行人、SHA、结果与证据，不另设独立 UAT 轮次。

| # | 检查 | 通过判据 |
|---|---|---|
| M1 | 打开旧 Agent 与新 Engine 配置 | 旧 Agent 无强制补字段/默认 dirty/重发布提示；公共、React、只读 Effective 区分清楚 |
| M2 | 提交未知/冲突配置并查看 preview | 错误可定位且四语言完整；不支持、环境不可用、策略拒绝含义明确，声明不等于授权 |
| M3 | 应用回滚并检查界面 | Phase 3 编辑入口失效/隐藏符合开关——UI 依 `GET /agents/execution-config-flags`（03 §7.4）声明式隐藏 preview 入口与 `disabled_capabilities` 收窄勾选，不靠点击报错反推；`phase3=on+orchestrator=off` 显示错配提示且不假成功；React 模型/轮次编辑与历史发布/Run 查看不受两开关门控；历史发布与 Run 仍可查看，无内部快照外泄 |

## 5. 安全、数据与发布硬门槛

| # | 核对项 | 判定 | 溯源 |
|---|---|---|---|
| C1 | 客户端、UI、Adapter 声明不能授予 Effective；伪造矩阵提权为 0 | 一票否决 | AC-3～AC-5；G2；FR-3～FR-5 |
| C2 | 策略可信且版本明确；下层不能恢复拒绝，无跨 Engine 自动回退；revision/version 权威来自 provider 自身，`execution_capability_policy_version` 与注册 descriptor 及 provider 回显一致（R-17/R-20）；平台 ceiling 与 tenant/agent/execution 取值来自代码常量与已发布配置而非调用方（R-44），`current_revision` 恒为作用域常量并在作用域内单调不减，禁止时钟/DB 派生的每轮前进 | 一票否决 | AC-4、AC-10；G2；FR-4、FR-8 |
| C3 | 快照、日志、事件、审计、公开 API 不含 body/Token/Key/原始 Memory/宿主秘密 | 一票否决 | AC-5、AC-6；G4；FR-5、FR-6 |
| C4 | tenant 与 business/workspace scope 覆盖配置、preview、策略、快照、审计 | 一票否决 | AC-5；G2；FR-5 |
| C5 | 五快照在 Adapter.start 前一次 commit 且不可变，公开事件原序，历史 NULL 不回填；已分类的屏障失败终态永不为 `execution_error`（R-50/R-51 的显式分类不被宽 `except Exception` 降级） | 必须通过 | AC-6；G4；FR-6 |
| C6 | React 复用既有 Summary/Memory 渲染与开关，基线无差异 | 必须通过 | AC-7；G3；FR-7 |
| C7 | 旧 JSONB 不批量改写，canonical diff 无默认噪声，非法配置不能发布，未注册 Engine 不开放 | 必须通过 | AC-1、AC-2；G1；FR-1、FR-2 |
| C8 | 四语言完整，Effective 只读，preview 无内部快照/Run 授权 | 必须通过 | AC-9；G1、G2；FR-8 |
| C9 | 双开关和应用回滚成功，无需 downgrade；非 React 不静默降级（on+orchestrator-off 下 `runtime.for_run` 调用计数恒 0）；Run 侧只用四个既有公开码 `execution_phase3_disabled`/`execution_configuration_invalid`/`execution_engine_unavailable`/`execution_policy_unavailable`，不新增未翻译码，失租/非 running 走既有 `worker_lost` 路径，不得降级为 `execution_error` | 一票否决 | AC-10；G4；FR-8、FR-9 |
| C10 | 动态重验迁移，仅五列且不改历史；无 Phase 4/5/6 范围偷跑 | 必须通过 | AC-11；G1、G4；FR-6 |
| C11 | **开关完整性与回滚（2026-11-18 起，功能门槛）**：默认 off 保留原 Phase 2 路径；显式 on 命中 Phase 3 能力/配置/指令入口；`phase3=on+orchestrator=off` 错配态 fail closed 且 `runtime.for_run` 调用计数恒 0；非 React 明确失败不静默降级；已 claim 行路径固定；两开关与调参不进 fingerprint；应用回滚无需 downgrade；三者证据以配置、flags 端点、Run 侧码与迁移可空列为凭 | 必须通过（一票否决同 C9）；无开关/回滚证据或静默降级即不通过 | AC-10；FR-8/9；G4；US-6 |
| C11（旧） | 历史口径（已废止，非门禁）：真实 resolver/admission 配对基线、缓存预热、≥100 有效交错配对样本、p95 增量 ≤50ms、不含外部模型；不足/未测=`not_measured`/`pending_env` | 2026-11-18 起不再作为阶段验收门槛，保留为历史上下文/另立独立跟进项，历史数字与结论不追溯修改 | G1；性能成功指标（历史） |

## 6. 结论与验收后工作

- **通过**：A1～A11、C1～C11 全通过（C11 为开关完整性/回滚功能门槛）；M1–M3 完成或等效；无 P0/P1；回滚证据完整，最终上线门禁无阻断。
- **有条件通过**：仅限不影响安全、兼容、快照、开关/回滚的非硬门禁 P2/P3，每条有 owner/期限并由验收负责人说明；一票否决项不适用。
- **不通过**：任一 AC/硬门槛失败、真实基线缺失致兼容无法判定、提权/跨域/泄密/非 React 静默降级、开关/回滚证据缺失或无静默降级失效。未测性能/CI/真实历史样本不再单列不通过判据（2026-11-18 修订）。
- **性能/CI 不再封顶结论（2026-11-18 修订）**：C11 旧性能口径的 `not_measured`/`pending_env` 不再使"通过"档不命中，也不再把结论封顶为"有条件通过"；历史数字与结论不追溯修改。
- **放行说明**：阶段通过不自动授权高风险能力启用；启用须另附独立审批记录。

实际验收后才创建双语 `07-acceptance-report.md/.en.md`，含 A/C 证据、C11 开关完整性/回滚证据、M 项、迁移/回滚、遗留及以下单一记录。

| 验收负责人 | 执行人 | 日期 | 目标 SHA | 结论 | 证据/遗留 |
|---|---|---|---|---|---|
| JackChow（用户本人确认，2026-11-18） | WorkBuddy 自动化验收执行 | 2026-11-18 | `5170e140f10b117549cf54ba400131f5d7f95f69` | **通过（范围限定 / PASS scope-limited）** | `../11-scope-limited-acceptance-record-20261118.md` §7；证据包 `20261118T125822Z.tar.gz` |

**seed/quickstart 严格在真实 06/07 后（本阶段不执行，见下）**：先新增独立低敏、确定性 ID、create-or-preserve 幂等 Phase 3 示例 seed，不伪造执行快照；再单独接线 fresh quickstart 自动执行，验证默认 off/on/回滚和真实 Run 快照。最后仅向已存在的 06/07 追加该补证；不提前创建报告，不让生产自动插入示例。

**本阶段范围调整（2026-11-13，08 R-39）**：维护者决定优先交付功能本体，上述 seed 与 quickstart 接线**不在本阶段执行**，转独立低优先级迭代跟进——issue **#127**（示例 seed）与 **#128**（fresh quickstart 接线与 off/on/回滚验证，依赖 #127）。因此本阶段验收范围收窄为 A1～A11、C1～C11、M1～M3 中**不依赖 seed/quickstart 证据**的部分；"下次 quickstart 自带 Phase 3 示例数据"这一诉求本阶段不予验收，07 必须把它如实记为**延后（#127/#128）并说明证据缺口**，禁止写成已完成，也禁止用"代码已合入"替代证据。先后顺序不变：#127/#128 仍须在真实 06/07 之后执行。
