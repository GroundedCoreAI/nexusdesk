# Phase 3 · 能力、配置与指令 — 测试方案

> 状态：待实施（本阶段开发完成后执行；当前无测试结果）
> 创建：2026-11-02
> 修订：2026-11-11（小团队轻量验收：复用自动化证据，移除多角色签字要求）
> 依据：`02-requirements.md`（FR-1–FR-9、AC-1–AC-11）、`03-technical-design.md`（兼容层、能力解析、快照屏障、Instruction Provider、回滚）

## 1. 测试范围与原则

**范围**：AgentConfig 兼容与类型化配置、Registry 接线、Declared/Available/Policy/Effective、只读预览、Run 快照、Instruction Provider、React Summary/Memory 兼容、迁移 `0053`、开关与回滚。

**原则**：

1. **基线先行**：现有行为基线以 Phase 0 实测为准；未完成前标“待 Phase 0”，不得以本阶段新实现反写预期。
2. **开关兜底必测**：总开关关闭后 React 与 Phase 2 行为逐点一致，非 React 必须拒绝而非换 Engine。
3. **空态回归必测**：历史快照 NULL、无 Engine 字段、无 Summary/Memory 均保持明确语义。
4. **恶意输入必测**：伪造能力/策略、额外字段、跨租户、敏感快照和超限输入不得只靠正面用例覆盖。
5. **故障路径必测**：探测超时、策略未知、持久化失败和 Adapter 启动前失败均失败关闭，不产生半授权执行。
6. **时间类用例不等待**：探测过期、缓存失效和 Run 超时使用 fake clock、直接改库或可控测试替身。
7. **无副作用重放**：快照决策重放只读数据，不重新调用真实模型、工具或外部 Engine。
8. **证据复用**：UT/IT/CM 的自动化结果和 CI/数据库证据直接供 A/C 验收引用，不为验收重复手工执行整套测试；人工只补无法自动化的关键检查。

## 2. 测试环境与数据构造

| 环境 | 用途 |
|---|---|
| 纯单测 | 配置映射、schema、能力求交、策略收窄、快照校验和指令渲染，无需 DB |
| 集成（专用 PostgreSQL + pytest fixture） | 草稿/发布/Run/快照、跨租户、并发读写、取消与失败链路 |
| Phase 1 LocalTestAdapter + Phase 2 测试编排器 | 不依赖外部 Engine 的声明、启动屏障、事件与终态验证 |
| mock/demo 模型与 MemoryInjection 测试替身 | 可编程 React 响应、Summary/Memory 顺序和既有渲染兼容 |
| disposable 迁移库 | 从实际前驱升级、旧行/新行、并发与 downgrade；不连接生产库 |
| 前端 typecheck/i18n/组件测试 | 类型化表单、只读能力视图、错误与语言资源 |

**数据构造约定**：使用 Phase 0 的授权脱敏样本和版本化 fixture；新构造两个 tenant、多个业务/workspace scope。声明、探测、策略与 Provider 均用确定性替身。快照持久化失败在 Adapter mock 前注入；取消/超时通过 Repository 状态与 fake clock 构造。每个测试独立清理 Run、版本和审计，不共享可变策略。

## 3. 单元测试

| 编号 | 用例 | 预期 | 溯源 |
|---|---|---|---|
| P3-UT-01 | 缺少 `engine/react` 的旧配置规范化 | 得到 `react/native/v1`，旧模型/轮次/公共字段等值，输入对象不变 | FR-1；AC-1 |
| P3-UT-02 | 新旧 React 别名同值 | 接受并输出单一规范值，无重复字段来源 | FR-1、FR-2；AC-1、AC-2 |
| P3-UT-03 | 新旧 React 别名异值 | 明确拒绝并指出冲突字段，不静默选择 | FR-2；AC-2 |
| P3-UT-04 | 未知三元组、latest、额外字段与自由配置字典 | 全部拒绝，Registry 未被绕过 | FR-2；AC-2 |
| P3-UT-05 | Profile ID/version 单独出现、轮次越界、disabled 能力未知/重复 | 按严格规则拒绝或规范化去重，边界不放宽 | FR-2、FR-4；AC-2 |
| P3-UT-06 | Declared=true 但部署缺失或版本不兼容 | Available=false 且有稳定原因码，Declared 不被改写 | FR-3；AC-3 |
| P3-UT-07 | 探测超时、异常与缓存命中/失效 | 有界返回不可用；缓存键完整，声明变化后旧值失效，无原始异常泄漏 | FR-3；AC-3 |
| P3-UT-08 | `workspace_required=true` 且 Workspace 不可用 | Available=false，必需能力缺失时阻止启动 | FR-3；AC-3 |
| P3-UT-09 | 平台/租户/Agent/Execution 任一层拒绝后下层允许 | Effective=false，记录全部决定，单调性成立 | FR-4；AC-4 |
| P3-UT-10 | 未知能力名、未知策略版本、缺失策略源 | 不默认授权；按最小权限或配置错误拒绝 | FR-4；AC-4 |
| P3-UT-11 | ExecutionRequest 输入伪造 Declared/Available/Effective | 严格拒绝，服务端对象不含客户端能力值 | FR-5；AC-5 |
| P3-UT-12 | tenant/actor 与认证上下文不一致 | 不信任请求字段，使用可信上下文并记录越权错误 | FR-5；AC-5 |
| P3-UT-13 | 快照缺必需字段、不可序列化或超过大小上限 | 校验失败，启动屏障不通过 | FR-6；AC-6 |
| P3-UT-14 | 快照嵌套 Token、API Key、原始 Memory、宿主路径 | 写入前拒绝；日志与错误不含敏感原文 | FR-6；AC-6 |
| P3-UT-15 | 快照重复序列化与决策重放 | 键/版本/原因稳定，重放只读且不改变快照 | FR-6；AC-6 |
| P3-UT-16 | React 空 Summary/Memory 与开关关闭 | 不生成空消息，保持 Phase 0 基线序列 | FR-7；AC-7 |
| P3-UT-17 | Summary、Memory、组合及历史截断 | System→Summary→Memory→history→user 顺序和文案完全一致 | FR-7；AC-7 |
| P3-UT-18 | 测试 Provider 使用不同格式 | 业务渲染仅调用一次，原生格式不被强制转成 ReAct | FR-7；AC-8 |
| P3-UT-19 | 未知 Provider、重复上下文或渲染契约错误 | 启动前明确失败，不降级为另一 Provider | FR-7；AC-7、AC-8 |
| P3-UT-20 | FR-9 settings 默认值、环境覆盖与非法边界 | 默认关闭、覆盖生效，非法超时/缓存/大小被拒绝 | FR-9；AC-10 |

## 4. 集成测试

| 编号 | 用例 | 预期 | 溯源 |
|---|---|---|---|
| P3-IT-01 | 旧草稿加载→不修改读取→正常编辑发布→React Run | 历史 JSONB 无 UPDATE；新版本规范化；执行与 Phase 0 基线一致 | AC-1；FR-1、FR-2 |
| P3-IT-02 | 合法新配置发布及未知/不可用配置发布 | 合法精确解析；非法在发布或 admission 前拒绝，Adapter 未启动 | AC-2；FR-2 |
| P3-IT-03 | 组合声明、环境探测与多层策略后执行 | 五类数据一致，Effective 只含所有层允许项，UI/Run 使用同一 resolver | AC-3、AC-4；FR-3、FR-4 |
| P3-IT-04 | Run/Agent/预览 API 注入伪造能力、策略与宿主字段 | 4xx/领域错误、提权为 0、安全审计完整且无敏感原文 | AC-5；FR-5 |
| P3-IT-05 | tenant B 读取 tenant A 的配置、预览、Run 快照与审计 | 全部不可达，不以仅隐藏字段代替查询隔离 | AC-5；FR-5 |
| P3-IT-06 | 完成 Run 检查启动前快照 | 五列非空、版本齐全、启动事件晚于快照提交，快照不可变 | AC-6；FR-6 |
| P3-IT-07 | Adapter 失败、用户取消、执行超时后检查快照 | 保留启动时快照与正确既有终态；迟到结果不覆盖取消或改写快照 | AC-6；FR-6 |
| P3-IT-08 | 注入快照序列化/DB 写入失败 | Run 失败关闭，Adapter.start 调用数为 0，无半成品 ExecutionRequest | AC-6；FR-6 |
| P3-IT-09 | 真实 MemoryInjection 测试替身贯通 Summary/Memory/开关/完成后写回 | 注入文案、顺序、budget、日志和写回与 Phase 0 基线 diff 为 0 | AC-7；FR-7 |
| P3-IT-10 | 同一上下文分别经 React 与测试 Engine Provider | 格式独立、渲染只一次、Run 公共事件契约不被原生格式破坏 | AC-8；FR-7 |
| P3-IT-11 | 预览后改变平台/租户策略再执行 | 预览只读；执行重新计算且不能沿用旧授权，原因码更新 | AC-4、AC-9；FR-4、FR-8 |
| P3-IT-12 | 总开关关闭执行旧 React 并比较事件/API/SSE | Phase 2 行为一致，五列 NULL，无 Phase 3 探测或快照副作用 | AC-10；FR-8、FR-9 |
| P3-IT-13 | 总开关关闭执行非 React | 返回 `execution_phase3_disabled`，React Adapter 调用数为 0，历史快照仍可读 | AC-10；FR-8、FR-9 |
| P3-IT-14 | 从实际前驱迁移并对旧/新 Run 并发读写 | 仅五列新增，旧行 NULL，新行可写，现有 Repository 语句不受阻 | AC-11；FR-6 |
| P3-IT-15 | 应用回滚到 Phase 2 二进制但不 downgrade | 新可空列不阻碍旧代码，React 正常，历史数据完整 | AC-10、AC-11；FR-8 |
| P3-IT-16 | 新旧 React 配置经 Model Gateway 与工具校验 | Profile/版本/权限/Run 关联不变，无通用配置绕过或密钥进入快照 | AC-1、AC-2、AC-6；FR-2、FR-6 |

## 5. 通用核对项（本阶段适用）

| 编号 | 核对项 | 通过标准 | 溯源 |
|---|---|---|---|
| P3-CM-01 | 迁移在线性与编号 | 实施前重验 head/down_revision；只加五列、无回填、无历史迁移修改；disposable downgrade 配对 | AC-11；FR-6 |
| P3-CM-02 | 配置加载 | 默认值、环境覆盖、非法边界与缓存失效全部符合 FR-9，秘密不进入示例文件 | AC-10；FR-9 |
| P3-CM-03 | 审计与观测 | Engine/provider/policy 版本和原因码齐全；日志、事件、审计无 Token/Memory 原文/宿主细节 | AC-5、AC-6；FR-5、FR-6 |
| P3-CM-04 | 租户与 scope 隔离 | 配置、预览、快照、策略与审计均按 tenant 和业务/workspace scope 隔离 | AC-5；FR-5 |
| P3-CM-05 | 历史兼容 | Phase 0 合法样本 100% 按裁定通过；原始 JSONB 不批量改写，失败样本有既有缺陷记录 | AC-1；FR-1 |
| P3-CM-06 | 快照不可变与空值语义 | 启动前写入、之后不更新；历史 NULL 不伪造回填，公开 API 不直接暴露 | AC-6；FR-6 |
| P3-CM-07 | 能力授权边界 | Declared/Available/Effective 均非客户端授权源；任一层拒绝不可被下层恢复 | AC-3～AC-5；FR-3～FR-5 |
| P3-CM-08 | 前端 i18n 与只读视图 | 用户文案无硬编码，支持语言检查通过；Effective 无编辑/提交入口 | AC-9；FR-8 |
| P3-CM-09 | 整体回滚 | 开关关闭和应用回滚无需动迁移；非 React 不降级，快照和历史配置不丢失 | AC-10；FR-8、FR-9 |
| P3-CM-10 | 阶段边界 | 未实现真实 Host/Workdir/Sandbox、Codex、通用策略后台或自动跨 Engine fallback | AC-2、AC-10；FR-2、FR-8 |

## 6. 回归范围

- Phase 0 锁定的 RuntimeEngine、Worker、Repository、取消/失租/超时、Run API 与 SSE 基线；若 Phase 0 尚无实测结果，对应兼容结论保持阻断，不填写“通过”。
- 既有 `test_runtime_engine.py`、`test_runtime_postgres.py`、Agent 配置/发布/回滚、Model Gateway、工具与知识访问测试。
- Summary/Memory 配置、注入、降级、注入日志与完成后任务分发测试；逐一比较消息内容、顺序与开关。
- 前端 Agent 编辑/diff/发布、前端 typecheck、`check:i18n` 与 build；后端 ruff 及受影响 pytest，最终全量由 CI 执行。
- 迁移升级后运行旧代码兼容与新代码空值测试；禁止修改历史 fixture 来掩盖既有非法样本。

## 7. 缺陷分级与出口准则

| 级别 | 定义 | 处理 |
|---|---|---|
| P0 阻断 | 客户端/Adapter 可提权；跨租户泄露；秘密进入快照；未授权 Adapter 启动；数据丢失 | 立即停止验收，修复并完整回归安全与兼容套件 |
| P1 严重 | 旧配置不兼容；Effective 计算错误；快照缺失；Summary/Memory 行为回归；开关或非 React 拒绝失效 | 修复前不得进入验收 |
| P2 一般 | 非阻断原因码、预览、性能目标或一般质量偏差 | 仅在无安全/兼容影响且非硬门禁项时记录 owner、期限，由验收负责人在单一验收记录中确认带问题验收 |
| P3 轻微 | 文案、非敏感日志或展示问题 | 排期修复，不得掩盖 i18n 硬编码或泄露问题 |

**出口准则**：P3-UT/IT/CM 全部通过；AC-1～AC-11 可复现；适用回归全绿；无 P0/P1 未关闭；提权与跨租户成功数为 0；快照覆盖率和敏感扫描达标；开关关闭与 Phase 2 基线 diff 为 0。环境不可用项标 `pending_env` 并阻断其覆盖的上线承诺，禁止写成通过。
