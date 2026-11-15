# Phase 7 · 高级 Engine 能力与规模化 — 测试方案

> 状态：暂缓执行（项目起步阶段；不执行本测试方案，任何用例均未执行且不得记为通过）
> 暂缓决定：2026-11-07；FR-1~FR-11 对应 P4 issue 见 `02-requirements.md`「暂缓与需求跟踪」，仅在阶段重新激活且对应切片开发完成后执行适用用例
> 创建：2026-11-02
> 修订：2026-11-11（小团队轻量验收：复用自动化证据，移除多角色签字要求；阶段仍暂缓）
> 依据：`02-requirements.md`（FR-1~FR-11、AC-1~AC-22）、`03-technical-design.md`（S7-01~S7-09、规划迁移与核心流程）、架构第 19 节与第 22 节
> 基线声明：现有行为、覆盖率、性能与容量基线未测，待 Phase 0；所有比较型测试必须先引用已签收的 Phase 0 数据

## 1. 测试范围与原则

**范围**：S7-01 Adapter 契约、S7-02 路由/降级、S7-03 Session、S7-04 人机交互、S7-05 动态模型、S7-06 用量成本、S7-07 公平配额、S7-08 Skill/Artifact、S7-09 Runtime Profile 健康，以及各片 API/UI/迁移/开关。真实厂商 Adapter 只有另行评审纳入时才增加其实例测试，不是统一套件的必要替身。

**原则**：

1. **逐片执行**：每个切片至少执行其溯源用例、全部适用 CM 和受影响回归；不得要求未评审切片假装已测，也不得用单一片通过代表 Phase 7 全量通过。
2. **开关兜底必测**：全部开关默认 false；全关及逐片关闭后的 API、事件、模型选择、终态行为与 Phase 0 基线 diff 为零。
3. **权限失败关闭**：路由、Resume、恢复、动态模型、下载与健康恢复均包含撤权、跨租户和绑定变化用例；任何错误不得扩大 Effective 权限。
4. **副作用优先**：超时、断连、Worker 重启、重复/延迟事件与迟到结果必须验证不重复外部副作用，不以“最终成功”掩盖重复执行。
5. **异步与多进程必测**：waiting 释放 Lease/配额；quota/fairness/health 用两个以上 API/Worker 验证，不能用单进程 mock 替代。
6. **时间类用例不等待**：Session、交互、健康、Artifact 保留通过直接构造时间或可控时钟；退避与过期不靠长时间 sleep。
7. **成本口径必测**：重复事件、additive/informational、unknown、不同币种与网关重叠分别断言，禁止把未知成本归为 0。
8. **空态与兼容必测**：无可选策略、无高级能力、无用量、无健康数据、历史 Run/Agent 快照均保持可读和可降级。
9. **证据复用**：UT/IT/CM 的自动化结果及多进程、容量、报表、存储证据直接供 A/C 验收引用，不为验收重复手工执行整套测试；人工只补无法自动化的关键检查。

## 2. 测试环境与数据构造

| 环境 | 用途 |
|---|---|
| 纯单测（可控时钟、假策略/仓储） | 路由分类、Effective、状态机、模型规则、usage/cost、健康与配置校验 |
| PostgreSQL + pytest postgres fixture | 迁移、租户范围、Run/Session/waiting、幂等、事件游标、配额与公平事务 |
| 两个以上 API/Worker 进程 | 并发提交/claim、全局配额、fairness cursor、熔断/半开协调和 Worker 重启 |
| LocalTestAdapter | 确定性成功、失败、流式、长运行、超时、取消、进程故障、重复/延迟事件、资源耗尽和用量 |
| demo/mock 模型与真实模型网关仓储 | 固定 Profile 兼容、动态选择、版本快照、模型 fallback 与调用成本关联 |
| 受控临时卷或 S3 兼容测试服务 | Skill 只读挂载、Artifact 大对象、授权下载、扫描状态和保留清理 |
| quickstart demo 栈 | 默认关闭、部署配置、基础 ReAct 回归与回滚演练；不用于证明生产性能 |
| 类生产专用租户（逐片验收时） | 约定容量、P95、报表数据量与真实依赖验收；不得使用其他租户业务数据 |

**数据构造约定**：至少使用两个租户、两个 business/workspace 范围和两个 Worker owner；每个用例独立创建 Agent 发布快照、Profile 版本、Execution/Run 与策略版本。通过直接写库构造 expired/stale/retention 场景；并发用 barrier 同时释放。副作用使用带唯一操作 ID 的假工具/假命令账本计数。事件重复使用同一 Adapter event ID，不同决议使用不同哈希。所有 Secret 均为可识别的假值并断言不出现在日志、事件、审计、元数据和报表中。

**测试切片映射**：S7-01→UT01~03/IT01~05；S7-02→UT04~09/IT06~09；S7-03→UT10~12/IT10~11；S7-04→UT13~15/IT12~14；S7-05→UT16~17/IT15~17；S7-06→UT18~20/IT18~19；S7-07→UT21~23/IT20~22；S7-08→UT24~26/IT23~26；S7-09→UT27~29/IT27~28；发布治理（对应 FR-11）→UT30/IT29~30。CM 按适用性执行。

## 3. 单元测试

| 编号 | 用例 | 预期 | 溯源 |
|---|---|---|---|
| P7-UT-01 | 版本化 Adapter 注册与解析 | 合法三元组解析到正确实现；注册元数据和 Declared 能力完整，Worker 无厂商依赖 | FR-1/AC-1 |
| P7-UT-02 | 未知组合、不兼容版本与无效配置 | 全部在业务执行前以稳定代码拒绝，不进入路由 | FR-1/AC-2 |
| P7-UT-03 | Declared 能力及契约结果真实性 | 未通过高级契约的能力不得声明可用；基础能力可独立通过 | FR-1/AC-1、AC-2 |
| P7-UT-04 | Declared、Available、Policy 交集 | Effective 只保留三者交集并带原因/策略版本，健康不增加权限 | FR-3/AC-5 |
| P7-UT-05 | 必需能力缺失与可选能力降级 | 可选项 false 保留基本执行；必需项启动前 `capability_unavailable` | FR-3/AC-5、AC-6 |
| P7-UT-06 | RoutePlan 只来自受信策略 | 客户端候选被忽略；顺序稳定且所有候选属于租户/Agent 允许集合 | FR-2/AC-3 |
| P7-UT-07 | 无副作用可重试错误分类 | 仅允许分类、零输出、零副作用时选择下一尝试并记录原因 | FR-2/AC-3 |
| P7-UT-08 | 输出/工具/审批/Artifact/未知超时后的回退 | 每种标记均禁止自动回退，不创建后续尝试 | FR-2/AC-4 |
| P7-UT-09 | 候选重新授权与权限单调收窄 | 未授权候选被拒；回退后 Effective 不包含前一候选额外权限 | FR-2/AC-4 |
| P7-UT-10 | Session 合法绑定和恢复快照 | 同范围、同三元组且 active 时通过，快照使用当前策略而非旧授权 | FR-4/AC-7 |
| P7-UT-11 | Resume 撤权、绑定变化与跨租户 | 全部失败关闭且不创建 Run、不自动换 Engine | FR-4/AC-8 |
| P7-UT-12 | Session 过期与 Resume 幂等 | 过期拒绝；同键同请求返回原 Run，同键不同请求冲突 | FR-4/AC-7、AC-8 |
| P7-UT-13 | Run waiting 状态转换与资源释放 | running→waiting 合法，waiting→queued 需决议/授权；终态和迟到转换被拒 | FR-5/AC-9 |
| P7-UT-14 | 审批职责分离与 revision | 自审、越权、非 pending、revision 冲突拒绝；合法审核员仅成功一次 | FR-5/AC-9 |
| P7-UT-15 | 输入 Schema、过期、取消和决议幂等 | 仅合法未过期输入通过；重复同决议无副作用，不同决议冲突 | FR-5/AC-10 |
| P7-UT-16 | 动态模型确定性规则与旧配置 | 首条匹配规则胜出并固定版本/理由；无策略严格走旧固定 Profile | FR-6/AC-11 |
| P7-UT-17 | 动态 Profile 资格过滤 | 操作、工具、输入限制、启用、版本和租户授权任一不符均排除 | FR-6/AC-12 |
| P7-UT-18 | usage 数值白名单与 cost 状态 | 负数/非有限/未知单位隔离；缺定价为 unknown，不产生 0 金额 | FR-7/AC-14 |
| P7-UT-19 | usage 幂等与 additive/informational | 同事件只记一次；仅 additive 入总计，重叠 Engine 汇总不重复 | FR-7/AC-13 |
| P7-UT-20 | 多币种报表和来源关联 | 币种分列、未知数独立，Run/Execution/Engine/模型关联完整 | FR-7/AC-13、AC-14 |
| P7-UT-21 | queued/running 原子准入边界 | 等于上限拒绝、低于上限允许；全局或租户任一满均 429 | FR-8/AC-15 |
| P7-UT-22 | 公平候选排序与决胜规则 | 从未服务优先，其后按 last_served、created_at、ID；轻租户不会持续排后 | FR-8/AC-16 |
| P7-UT-23 | waiting 与恢复配额语义 | waiting 不算 running/可领取 queued；恢复重新准入，等待数量另受限 | FR-8/AC-16 |
| P7-UT-24 | Skill 版本、来源、权限与哈希 | 已发布不可变；篡改、未授权共享和版本漂移在执行前拒绝 | FR-9/AC-17 |
| P7-UT-25 | Skill 适配路径和只读约束 | 不同 Engine 布局确定；`..`、绝对路径和 symlink 逃逸失败关闭 | FR-9/AC-17 |
| P7-UT-26 | Artifact 元数据、下载授权与保留 | 哈希/大小正确；跨租户、过期、扫描拒绝不下载，清理状态不虚报 | FR-9/AC-18 |
| P7-UT-27 | Runtime Profile 配置校验 | 发布版本不可变；任意命令、明文 Secret、越界资源和无效探测被拒 | FR-10/AC-19 |
| P7-UT-28 | 熔断 closed/open/half_open 状态机 | 阈值、冷却、成功/失败计数及有界探测严格符合配置 | FR-10/AC-19、AC-20 |
| P7-UT-29 | 健康陈旧、unknown 与人工禁用 | stale/unknown 不健康；manual disabled 不被自动恢复覆盖 | FR-10/AC-20 |
| P7-UT-30 | 九开关默认值、环境覆盖和依赖校验 | 全部默认 false；`AGENT_` 覆盖生效；缺依赖时启用被拒绝 | FR-11/AC-21 |

## 4. 集成测试

| 编号 | 用例 | 预期 | 溯源 |
|---|---|---|---|
| P7-IT-01 | Adapter 启动、流式事件、结果与用量完整链路 | 事件有序可重放，结果唯一，usage 与 Run/Execution 关联；Worker 未感知厂商语义 | FR-1/AC-1 |
| P7-IT-02 | Adapter 取消、超时与长运行 | 取消/超时终态和进程清理正确，迟到结果不覆盖终态 | FR-1/AC-1；架构§19.1 |
| P7-IT-03 | Engine 不可用、配置无效与协议错误 | 分类稳定、无原始敏感错误；无效配置不启动，符合回退分类 | FR-1/AC-1、AC-2 |
| P7-IT-04 | 重复/延迟事件与断线重放 | event ID/游标去重，迟到事件不破坏状态，SSE 重连不重复业务副作用 | FR-1/AC-1；架构§19.1 |
| P7-IT-05 | 新 LocalTestAdapter 组合的依赖边界证明 | 公共契约全过；Worker 核心 diff 为 0，新增 Protocol 不要求公共 Engine 厂商字段 | FR-1/AC-1；架构§22 解耦 |
| P7-IT-06 | 启动前 EngineUnavailable 的安全回退 | 第二候选重新授权后只执行一次有效工作，两次快照与回退事件齐全 | FR-2/AC-3 |
| P7-IT-07 | 未授权候选与各类副作用后的回退尝试 | 不越权、不重复工具/命令/Artifact；结果未知时明确失败而非再跑 | FR-2/AC-4 |
| P7-IT-08 | 仅基础能力 Engine 的端到端执行与 UI | 无高级操作可完成结果；Effective/原因由服务端返回，UI 文案有 i18n，usage 缺省为 unknown | FR-3/AC-5 |
| P7-IT-09 | 强制要求不支持能力 | API 启动前拒绝，数据库无 Execution/副作用记录，安全要求不被关闭 | FR-3/AC-6 |
| P7-IT-10 | 有效 Session Resume、同键重试与 Worker 重启 | 重新授权后仅一个新 Run；原生上下文延续，事件/快照完整，重启不重复创建 | FR-4/AC-7 |
| P7-IT-11 | 过期、撤权、绑定变化和跨租户 Resume | 全部无新 Run/新副作用，不泄露 Session 是否存在或原生 metadata | FR-4/AC-8 |
| P7-IT-12 | 人工审批 waiting、资源释放、批准与恢复 | waiting 不持 Lease/running；合法他审同事务转 queued，恢复从正确游标继续 | FR-5/AC-9 |
| P7-IT-13 | 审批并发、自审、重复决议与 Worker 重启 | 只有一个有效决议/恢复；审批、等待、Run、Outbox 状态一致，无重复副作用 | FR-5/AC-9 |
| P7-IT-14 | 交互输入合法/错误/越权/过期/取消 | 只有合法路径恢复一次；其他状态可审计，普通事件无输入 Secret | FR-5/AC-10 |
| P7-IT-15 | 旧固定 Profile 与无策略动态开关兼容 | 开关开启但无策略时 Profile/版本/调用路径与 Phase 0 一致 | FR-6/AC-11 |
| P7-IT-16 | 动态选择及 Profile 内模型 fallback | 快照固定选中 Profile/版本/理由；网关 fallback 仍受原 Profile 权限并正确关联成本 | FR-6/AC-11、AC-12 |
| P7-IT-17 | 动态模型越权或无合格候选 | 不选择允许集外模型，无模型调用，启动前失败且原因稳定 | FR-6/AC-12 |
| P7-IT-18 | 网关与 Engine 用量联合报表及重复上报 | 模型费只取网关事实；additive/informational 正确，重复事件不改变总计 | FR-7/AC-13 |
| P7-IT-19 | unknown 成本、双币种与跨租户报表 | unknown 不归零、币种不混算、unknown 数准确；其他租户记录不可见 | FR-7/AC-14 |
| P7-IT-20 | 多 API/Worker 同时提交与 claim 达上限 | 全局/租户 queued/running 均不超硬限额；429/Retry-After 稳定，无死锁 | FR-8/AC-15 |
| P7-IT-21 | finish/cancel/reap 后容量释放与故障 fail closed | 状态改变后按契约释放；协调 DB 故障不放行，恢复后计数仍准确 | FR-8/AC-15 |
| P7-IT-22 | noisy neighbor、公平推进与 waiting 恢复 | 轻租户每批推进并达到约定 P95；waiting 不占 running，恢复重新排队 | FR-8/AC-16 |
| P7-IT-23 | 共享 Skill 发布、快照与两种测试 Engine 布局 | 版本/哈希一致、挂载只读；平台模型不变，Adapter 转换确定且基本执行成功 | FR-9/AC-17 |
| P7-IT-24 | Skill 篡改、跨租户引用和路径/符号链接逃逸 | 启动前全部拒绝，无不受信内容进入 Workdir，不泄露其他租户路径 | FR-9/AC-17 |
| P7-IT-25 | 小/大 Artifact 写入、哈希、授权下载与事件 | 流式大小限制生效，内容和哈希一致，事件无对象正文/Secret，合法下载成功 | FR-9/AC-18 |
| P7-IT-26 | Artifact 越权/过期下载、扫描拒绝和清理失败重试 | 全部按策略阻断；对象未删成功不报 cleaned，重试和告警可观测 | FR-9/AC-18 |
| P7-IT-27 | Runtime Profile 快照与连续失败熔断 | 资源/egress/Secret 引用按版本执行；closed→open 后跳过候选或明确失败，不扩大 Effective | FR-10/AC-19 |
| P7-IT-28 | 多 Worker 半开恢复、陈旧健康和人工禁用 | half_open 全局探测不超上限；失败重开、成功关闭；stale 不可用且人工禁用优先 | FR-10/AC-20 |
| P7-IT-29 | 九开关全关及逐片关闭的 Phase 0 回归 | 旧 Agent/Run/API/SSE/模型/终态行为 diff 为 0，新路径无新副作用 | FR-11/AC-21 |
| P7-IT-30 | 单片灰度、回滚、历史数据读取与再启用 | 仅该片停止新执行；旧新数据均可读，无 down migration；再启用重新授权/查过期/查健康 | FR-11/AC-22 |

## 5. 通用核对项（本阶段适用）

| 编号 | 核对项 | 通过标准 | 溯源 |
|---|---|---|---|
| P7-CM-01 | Phase 0 基线前置 | 行为、覆盖率、性能、容量和发布回滚基线有环境/样本/证据；缺失时比较型指标不得判过 | G11/AC-21、AC-22；架构§17 Phase 0 |
| P7-CM-02 | 迁移 head 与规划号核查 | 实施前重新列出 head；0058+ 未被当作现有文件，真实编号/down_revision 与文档同步 | FR-11/AC-22 |
| P7-CM-03 | 迁移在线性与兼容 | 从当前 head upgrade 成功；expand-only、无长锁业务表；waiting/索引/新表旧代码兼容，回滚无需 down | FR-4~FR-11/AC-22 |
| P7-CM-04 | 配置加载与依赖 | 默认 false、环境覆盖和有界数值正确；缺 Phase 依赖或配额未冻结时启用失败 | FR-11/AC-21 |
| P7-CM-05 | 公共 Adapter 契约完整性 | 每个上线 Adapter 执行架构§19.1 全部适用项及 LocalTestAdapter 故障矩阵，无厂商豁免未记录 | FR-1/AC-1；架构§19.1~19.2 |
| P7-CM-06 | 租户与资源范围 | Session/wait/usage/Skill/Artifact/Profile/报表/调度均跨租户不可达，scope 过滤无遗漏 | FR-2~FR-10/AC-4、AC-8、AC-14、AC-17~19 |
| P7-CM-07 | Secret、沙箱与路径安全 | 日志/事件/审计/元数据/报表无 Secret；不可信执行具备沙箱、egress、资源和路径隔离，危险用例失败关闭 | FR-2、FR-4、FR-5、FR-8~FR-10/AC-4、AC-8、AC-10、AC-18~20；架构§22 安全 |
| P7-CM-08 | 审计与观测 | route/fallback/resume/decision/quota/usage/artifact/health 含关联 ID、版本和稳定原因；无正文/Secret，告警可触发 | FR-2~FR-10；架构§22 可运维性 |
| P7-CM-09 | Effective UI 与 i18n | UI 仅依据服务端 Effective，waiting/unknown/健康/拒绝原因正确；所有新增用户文案通过 i18n 检查 | FR-3、FR-5、FR-7、FR-10/AC-5、AC-9、AC-14、AC-20 |
| P7-CM-10 | 性能、容量与锁证据 | 在约定负载记录 P95、吞吐、EXPLAIN、锁等待与样本；路由开销、报表、配额、公平达到 01/02 指标 | G2、G7、G8、G10/AC-15、AC-16 |
| P7-CM-11 | 回归与全关 diff | 受影响既有套件全绿；全关相对 Phase 0 diff 为 0；skip 有原因且不算通过 | G3、G11/AC-21 |
| P7-CM-12 | 小 PR、文档现实与厂商边界 | 每片范围独立、文档路径/状态与代码一致；Worker 解耦，无未批准厂商交付被写成完成 | G1、G11/AC-1、AC-22；架构§19.4、§22 |

## 6. 回归范围

- 现有 Runtime：`backend/tests/test_runtime_engine.py`、`test_runtime_postgres.py`、`test_runtime_scope.py`、`test_runtime_availability.py`，重点覆盖五态、取消/超时、租约、同会话互斥、SSE 游标和终态保护。
- 模型与配额：`test_model_gateway.py`、`test_gateway_governance.py`、`test_gateway_credentials.py`、`test_gateway_migrations.py`，确保固定 Profile、模型 fallback、调用/成本与既有 quota 不被新路径绕过。
- 审批与范围：`test_runtime_scope.py` 及现有审批测试；waiting、恢复与审批决议不得扩大 tenant/business/workspace 范围。
- Workspace/存储：现有 `test_tool_workspace.py`、`test_agent_workspace.py`、`test_knowledge_workspace.py` 及对应迁移测试；新执行存储不得改变知识/工具既有边界。
- 全部迁移：从真实当前 head 做升级与旧代码兼容验证；0058+ 仅在对应切片创建后执行，当前不得声称这些迁移测试存在或通过。
- 前端：受影响页面执行 typecheck、i18n、build 和现有 Playwright；验证旧五态、固定模型报表与无高级能力空态。
- Phase 0~6：后续形成的契约、React/Codex、Runtime Host、Workspace、凭据、事件/fencing 回归全部纳入适用片；当前未测基线必须待 Phase 0 补齐。

## 7. 缺陷分级与出口准则

| 级别 | 定义 | 处理 |
|---|---|---|
| P0 阻断 | 跨租户泄露；越权执行/回退/恢复；重复已确认外部副作用；数据丢失；沙箱逃逸 | 立即停止切片灰度，修复并跑完全部安全/回归后方可继续 |
| P1 严重 | 终态/Lease/幂等错误；配额超限；waiting 重复恢复；费用重复；开关失效；熔断导致全局不可用 | 修复前不得进入该片验收或扩大灰度 |
| P2 一般 | 非安全策略偏差、报表展示不完整、非阻断性能目标未达 | 仅非硬门禁项可记录 owner/期限后由验收负责人在单一验收记录中确认带问题验收 |
| P3 轻微 | 文案、非关键日志、文档链接问题 | 排期修复，不得掩盖 i18n 或溯源失败 |

**单片出口准则**：该片适用 UT/IT/CM 全通过且留有逐条证据；适用 AC 在集成环境复现通过；受影响回归全绿；无 P0/P1 未关闭；迁移、灰度、回滚和全关 diff 门禁通过；Phase 0 比较基线已签收。任何 skip 必须说明环境、影响与补测人，不计入通过率。

**Phase 7 整体出口准则**：只有所有被批准纳入最终范围的切片分别满足单片出口，且架构第 22 节相关解耦、安全、扩展与运维项有证据，才可称整体完成。不得用真实厂商数量、单测数量或一次 demo 替代。
