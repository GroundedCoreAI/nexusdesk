# Phase 5 · Codex 集成 — 测试方案

> 状态：待实施（本阶段开发完成后执行；当前未执行、未通过）
> 创建：2026-11-02
> 依据：`02-requirements.md`（FR-1~FR-12、AC-1~AC-12）、`03-technical-design.md`（Stage A/B、RuntimeHost、Session、规划迁移 0055）

## 1. 测试范围与原则

**范围**：Codex CLI Adapter、App-Server Adapter、JSON-RPC、原生事件/usage、RuntimeHost 集成、Workspace/凭据策略、Session/Resume、配置开关、条件性 Session 迁移和 React 回归。

**原则**：

1. **Stage 顺序必测**：Stage B 的所有启用测试先验证门禁拒绝，再凭 Stage A 完整通过证据解锁；不得用 mock 绕过产品门禁。
2. **开关兜底必测**：CLI/App-Server/Session 独立关闭后，React 与既有行为同 Phase 0 基线逐点一致。
3. **真实进程必测**：进程退出、进程树清理、连接关闭以 OS/Host 证据断言，不能仅断言协程取消。
4. **安全对抗必测**：路径穿越、符号链接、跨租户、宿主 auth 文件、Secret canary 和不可信租户均纳入负向用例。
5. **故障注入必测**：崩溃、hang、断连、malformed/重复/迟到消息和缺失 usage 不得转化为假成功或永久等待。
6. **时间类用例不等待**：Session 过期、超时与宽限期通过可控时钟或直接构造状态；真实进程测试保留有界超时。
7. **基线如实记录**：性能、React 行为和回归基线未测项标“待 Phase 0”，不得将 skip 记为通过。

## 2. 测试环境与数据构造

| 环境 | 用途 |
|---|---|
| 单测（无 DB） | 配置/版本、参数白名单、事件 fixtures、JSON-RPC 状态机、错误映射、Session 策略。 |
| 集成（PG + pytest postgres fixture） | Run/事件持久化、条件性 Session 迁移与 Repository、租户/Conversation 绑定。 |
| 受控 Codex 环境 | 固定已验证版本的 CLI/App-Server；使用专用低权限账号和非生产凭据。 |
| RuntimeHost/沙箱前置环境 | Phase 4 实际 Host、进程组、挂载、资源与清理观测；Phase 6 前不测试不可信租户开放。 |
| React/SSE 回归环境 | 现有 DemoModel、Run API、`after`/`Last-Event-ID`、历史 Agent 配置和事件 fixtures。 |

**数据构造约定**：至少两个租户、两个 Conversation/Workspace；使用 Secret canary、含子进程与文件写入的可控任务、正常/malformed/未知版本协议 fixtures。真实 Codex 测试凭据由部署 Secret 注入，不写入仓库；无法提供受控真实版本时相关 IT 标 `pending_env`，不得用全 mock 代替验收。

## 3. 单元测试

| 编号 | 用例 | 预期 | 溯源 |
|---|---|---|---|
| P5-UT-01 | 同一 Engine 注册两种 Protocol | Engine ID 均为 `codex`，Adapter/Protocol 独立解析，未知组合拒绝。 | FR-1 |
| P5-UT-02 | Stage A 门禁状态机 | 证据缺失时 Stage B 不可启用；证据完整才允许，关闭 Stage A 同时阻止 Stage B 新执行。 | FR-1、FR-12 |
| P5-UT-03 | Codex 版本兼容矩阵 | 支持版本通过，空白名单、未知/高低不兼容版本 fail closed。 | FR-1、FR-2 |
| P5-UT-04 | 类型化配置与能力收窄 | 非法字段/超时上限拒绝；Agent 配置不能扩大部署 Effective 能力。 | FR-2、FR-12 |
| P5-UT-05 | CLI 参数与环境白名单 | 仅生成允许参数；任意客户端参数、宿主敏感环境和 auth 路径不进入调用。 | FR-2、FR-6 |
| P5-UT-06 | CLI 正常/分片/malformed 输出 fixtures | 分片重组正确；平台/原生事件关联 Run，malformed 产生有界 ProtocolError。 | FR-4、FR-11 |
| P5-UT-07 | usage 提取与缺失 | 支持字段正确归一；缺失/部分字段为 unknown，不填零、不编造模型名。 | FR-4 |
| P5-UT-08 | 错误与取消映射 | EngineUnavailable、AuthenticationError、Timeout、Cancelled 等映射稳定，原始异常不外泄。 | FR-3、FR-11 |
| P5-UT-09 | Workspace 路径与链接校验 | 穿越、绝对路径、符号链接和跨租户挂载在启动前拒绝。 | FR-5 |
| P5-UT-10 | 凭据引用与信任边界 | 无引用/跨租户/不可信租户拒绝；日志与异常序列化无 Secret。 | FR-6 |
| P5-UT-11 | JSON-RPC 帧与版本协商 | 分片、并发 ID、错误响应和协商失败均正确处理，方法 schema 不进入公共模型。 | FR-7 |
| P5-UT-12 | JSON-RPC 重复/未知/迟到响应 | 不错误完成 Turn、不自动重放副作用请求，等待者有界退出。 | FR-7、FR-11 |
| P5-UT-13 | 审批/输入能力门控 | 非 Effective 能力拒绝；未知请求不自动批准，响应只能匹配原请求。 | FR-9 |
| P5-UT-14 | Session/Turn/Run 映射与元数据版本 | 多 Turn 关联同一 Session 且各自 Run 独立；不兼容元数据拒绝 Resume。 | FR-8 |
| P5-UT-15 | Session Resume 全量重新鉴权 | 租户、Conversation、Workspace、状态、凭据、Protocol/Adapter 任一变化均拒绝。 | FR-10 |
| P5-UT-16 | Session 过期清理重入 | 重复过期/关闭不重复释放或报错，过期后不可恢复。 | FR-8、FR-10 |
| P5-UT-17 | 日志/事件诊断边界 | 超长 stderr、JSON-RPC payload 和 Secret canary 被截断/脱敏，公共响应无宿主细节。 | FR-11、FR-6 |
| P5-UT-18 | Codex 开关与 React 默认 | 默认解析 React；各 Codex 开关默认 false，关闭时不可构造执行。 | FR-12 |

## 4. 集成测试

| 编号 | 用例 | 预期 | 溯源 |
|---|---|---|---|
| P5-IT-01 | 真实受控 CLI 成功执行 | 经 Orchestrator/Host 完成 AC-1，Workdir、输出、产物、终态和 Run 关联正确。 | AC-1 |
| P5-IT-02 | 两种 Protocol 注册及 Stage 解锁 | 复现 AC-2；未达门禁的 App-Server 配置与运行时均拒绝。 | AC-2 |
| P5-IT-03 | CLI 原生事件和 usage 端到端 | 消息/命令/文件事件保真且有序关联，最终 usage 或 unknown 正确。 | AC-3 |
| P5-IT-04 | App-Server 原生流与 usage 端到端 | notification 与稳定事件并行保留，Turn 结果关联同一 Run。 | AC-3 |
| P5-IT-05 | CLI 用户取消含孙进程 | 取消后进程组实际退出、挂载/临时资源释放，Run 不被迟到成功覆盖。 | AC-4 |
| P5-IT-06 | CLI/App-Server 超时与 hang | 超过截止时间后优雅/强制终止，清理失败有明确错误和告警。 | AC-4 |
| P5-IT-07 | Codex 进程崩溃与 App-Server 断连 | 连接/进程不残留，Run 进入可诊断终态，不永久等待。 | AC-4、AC-7 |
| P5-IT-08 | Workspace 合法读写与逃逸对抗 | 合法任务成功；穿越、symlink、跨租户读写全部被拒并审计。 | AC-5 |
| P5-IT-09 | 凭据最小暴露与 Secret canary | 仅目标 Execution 可用；日志、事件、API 无 canary，宿主 auth 文件不可见。 | AC-6 |
| P5-IT-10 | 不可信租户与信任撤销 | 默认拒绝；执行前撤销信任不得启动，新 Resume 也不得沿用旧信任。 | AC-6、AC-10 |
| P5-IT-11 | JSON-RPC 并发、断连和异常响应 | 复现 AC-7，请求不串线、私有协议无公共路由、异常可诊断。 | AC-7 |
| P5-IT-12 | Session 持久化、多 Turn 与过期 | 条件性迁移升级后复现 AC-8；CLI 在未启用 Session 时不受影响。 | AC-8 |
| P5-IT-13 | 审批/输入允许、拒绝与等待取消 | 复现 AC-9；拒绝无文件/命令副作用，等待可超时/取消。 | AC-9 |
| P5-IT-14 | Session Resume 合法与跨边界对抗 | 复现 AC-10；每次均重新鉴权并生成独立 Run/审计。 | AC-10 |
| P5-IT-15 | 不支持版本、坏输出与缺 usage 故障注入 | 复现 AC-11，稳定错误/unknown、无 Secret、诊断可关联。 | AC-11 |
| P5-IT-16 | 开关关闭 React/API/SSE/历史配置回归 | 复现 AC-12；Phase 0 基线存在时 diff 为零，否则标阻断待补而非通过。 | AC-12 |
| P5-IT-17 | 条件性 Session 迁移升级/降级保护 | 从实施时 head 升级成功；有数据降级要求导出，历史迁移校验和不变。 | FR-8、G6 |
| P5-IT-18 | Stage A 预发布稳定性批次 | 至少 20 个混合场景无 P0/P1，且连续 3 次适用回归通过后才能签出 Stage B 解锁证据。 | FR-1；G5 |

## 5. 通用核对项（本阶段适用）

| 编号 | 核对项 | 通过标准 | 溯源 |
|---|---|---|---|
| P5-CM-01 | 迁移规划号与历史保护 | 实施前重核 head；0055 仅 Stage B 需要时新增，无历史迁移修改。 | FR-8、G6 |
| P5-CM-02 | 配置加载与默认拒绝 | 默认全部关闭，环境覆盖生效；空版本/信任白名单不能启动 Codex。 | FR-12、FR-6 |
| P5-CM-03 | Secret 与敏感参数扫描 | 日志、事件、SSE、错误、审计和测试中无真实 Secret/canary/宿主 auth 内容。 | FR-6、FR-11 |
| P5-CM-04 | 租户与 Session 隔离 | 所有 Repository 查询和 Resume 均带可信租户及 Conversation/Workspace 约束。 | FR-5、FR-10 |
| P5-CM-05 | 原生协议边界 | 公共 OpenAPI/响应无 JSON-RPC 方法、宿主 PID、敏感参数或私有错误。 | FR-2、FR-7 |
| P5-CM-06 | 进程与连接资源 | 无孤儿进程/FD/临时挂载；取消、超时、崩溃均有清理证据。 | FR-3 |
| P5-CM-07 | 观测与审计 | Run/Protocol/Adapter/Session 关联、版本、退出码、usage unknown 和安全拒绝可查询。 | FR-11 |
| P5-CM-08 | 双语与需求溯源 | 文档中英结构/ID/表格行一致，UT/IT/CM、A 与 AC 可追溯。 | G6 |

## 6. 回归范围

- `backend/tests/test_runtime_postgres.py`：认领、取消竞态、Worker 丢失、迟到结果、持久事件和 SSE replay。
- React Runtime、RuntimeFactory、Agent 历史配置、Run API、SSE `after`/`Last-Event-ID` 与现有前端事件消费的适用套件。
- Workspace、工具凭据/网络、模型网关凭据套件，确认 Codex 新路径未改变已有边界。
- 迁移全链路与从实施时实际 head 的升级；不得改写 0001~0052 或其他已合入历史迁移。
- Phase 0 基线缺失时，性能、兼容 diff 和既有行为项标“待 Phase 0”，作为出口阻断而非豁免。

## 7. 缺陷分级与出口准则

| 级别 | 定义 | 处理 |
|---|---|---|
| P0 阻断 | Secret/跨租户泄露；不可信租户误开放；主执行路径破坏；数据丢失；失控进程。 | 立即关闭相关开关，修复并全量回归后方可继续。 |
| P1 严重 | 终态/清理错误；Stage 门禁失效；Session 越权；公共协议泄露；开关失效。 | 修复前不得进入验收或解锁 Stage B。 |
| P2 一般 | 非核心事件/usage 映射偏差、有界诊断或质量偏差。 | 记录后可带问题验收，需产品与安全签字；不得掩盖安全项。 |
| P3 轻微 | 文案、非敏感日志和文档问题。 | 排期修复并保留溯源。 |

**出口准则**：Stage A 的适用 UT/IT/CM 与 AC-1~AC-6、AC-11~AC-12 全通过并完成 P5-IT-18 后才解锁 Stage B；阶段总出口要求全部适用用例和 AC 通过、真实 Codex 环境项无未批准 skip、回归全绿、开关关闭 diff 为零、无 P0/P1 未关闭。Phase 6 前不得将“不可信多租户开放”列为通过范围。
