# Phase 3 · 能力、配置与指令 — 业务目标

> 状态：设计已按代码现实校准（未实施、未测试、未验收）
> 创建：2026-11-02
> 修订：2026-11-12（迁移、Phase 1/2 现状、启动屏障、预览与证据门禁）
> 依据：`docs/architecture/agent-execution-platform-v2.md` 第 5、6、11、14、15、17、19、22 节；Phase 0–2 06/07；`02-requirements.md`（FR-1～FR-9）
> 预估工期：~2 周（T2 前按最终范围重估）
> 开发入口：基线 `3969258` 已合入 Phase 1/2 代码，focused baseline 163 passed / 5 skipped；这不是上游正式验收完成或最终上线批准

## 要解决的问题

### 问题 1：Agent 配置无法安全表达多 Engine 选择

`business_capabilities/agent_config/service.py` 的 `AgentConfig(extra=forbid)` 只有既有根字段；Phase 2 `ExecutionOrchestrator` 当前固定 `react/native/v1`，Registry 只有身份/factory，没有配置 schema、声明、probe、policy/provider 元数据。自由字典会绕过精确类型与发布校验，简单补默认值又会让历史读取产生 UPDATE 或 canonical diff 默认噪声。

### 问题 2：技术能力、环境可用性与授权没有统一判定链

`EngineCapabilities` 目前只是 11 项 Declared 布尔声明，`ExecutionRequest.effective_capabilities` 只是内部 DTO 字段，没有 Declared → Available → Policy → Effective 解析器、可信 probe/policy 端口或缓存边界。若直接采用 Adapter 声明或客户端字段，就会把“支持”误当“授权”。Phase 3 必须默认最小权限，并在无 Workspace 时使 `workspace_required=true` 不可用。

### 问题 3：指令与 Summary/Memory 注入绑定 ReAct 消息结构

`RuntimeFactory.effective()` 组合系统提示，`RuntimeEngine.run()` 组装 SystemMessage；Worker 已提供渲染后的 Summary/Memory。ReactAdapter.start 创建 runner 后 RuntimeFactory 才装配 Runtime。若没有可测试的“准备/渲染 → Adapter.start”屏障，新 Engine 会复制提示与 Memory 逻辑，或改变既有消息顺序。

### 问题 4：单次执行缺少不可变的决策快照

`runtime_runs.config` 保存输入快照，但没有解析后配置、Declared/Available/Policy/Effective 五类独立快照。发布后配置、探测或策略变化后，历史 Run 无法解释允许/拒绝依据；公开 API 也不能因此直接暴露内部快照。

## 业务目标

| 目标 | 说明 |
|---|---|
| G1：兼容且类型化的多 Engine 配置 | 旧配置默认解析为 `react/native/v1`；Registry 元数据驱动严格 schema；同值旧根别名接受、异值拒绝；历史读取无 UPDATE，canonical diff 无默认噪声 |
| G2：服务端能力治理 | 建立 Declared → Available → Policy → Effective 单调收窄链，默认最小权限；客户端、预览和 Adapter 均不能越过环境或策略提权 |
| G3：可替换的 Engine 指令渲染 | InstructionInput/Provider 适配 Engine 格式；系统提示和 Summary/Memory 只计算一次，React 消息顺序、文案、预算和写回保持兼容 |
| G4：可追溯且可回滚的执行决策 | Phase 3 Run 在 Adapter.start 前一次性持久化五快照；序列化/DB 失败不启动；开关回退不改公开 `run.started` 顺序或历史快照 |

## 成功指标

| 指标 | 基线（现状） | 目标 |
|---|---|---|
| 存量 Agent 草稿与发布快照兼容率 | Phase 0 合成合法样本 5/5；经授权真实历史样本仍 `pending_env` | 纳入清单的合法样本加载、规范化、再发布与 React 执行 100% 符合；原始 JSONB 不批量改写；真实样本缺失不判完整通过 |
| 非法或未知执行配置拒绝率 | 既有 AgentConfig/RunRequest 已 `extra=forbid`，无 Engine schema | 未知三元组、类型错误、额外字段、别名异值及不可用必需能力 100% 稳定拒绝 |
| 客户端能力提权成功数 | 公开 RunRequest 无能力字段；无 Phase 3 预览 API | 伪造 Declared/Available/Effective、Policy、宿主字段或跨租户预览的提权成功数为 0 |
| Phase 3 Run 决策快照完整率 | 无五快照列 | 经 Adapter.start 的完成、失败、取消、超时 Run 五快照覆盖率 100%；未提交快照时 start 调用为 0 |
| React 指令兼容回归 | Phase 2 已有受控对等证据；真实上游缺口按原报告保留 | 空态、开关、Summary、Memory、组合及截断场景的既有消息顺序/文案 diff 为 0，业务渲染仅一次 |
| 配置与能力解析附加延迟 | 数值基线待测 | 缓存预热后，真实实现同环境交错采集至少 100 个有效配对样本，解析 p95 增量 ≤50ms；外部模型时间排除，未测写 `not_measured`/`pending_env` |

## 范围

**包含**：

- 扩展现有 AgentConfig JSONB 草稿/发布链与 `ExecutionConfig`/legacy normalizer，不新增 Agent 配置表。
- 扩展 Registry 注册元数据：严格 config schema、Declared、probe、policy/provider 标识；草稿和预览不实例化 Adapter。
- Declared/Available/Policy/Effective 类型、可信 probe/policy 端口、缓存与失效、最小权限、只读 Effective 预览。
- 规划迁移 `0058_agent_execution_metadata`，仅在 `runtime_runs` 增加五个可空快照列，实施前动态重验 `down_revision`。
- InstructionInput、React/测试 Provider、Orchestrator/ExecutionContext/ReactAdapter/RuntimeFactory 扩展及启动屏障。
- `POST /api/v1/agents/execution-preview`、现有 AgentsPage 适度拆件、四语言、OpenAPI、审计、测试、上线回滚。
- 开发测试验收完成后的独立低敏幂等示例 seed 与 fresh quickstart 自动接线/验证。

**不包含**：

- Runtime Host、真实外部进程、Execution Workdir 或 Sandbox（Phase 4）。
- Codex CLI/App-Server、生产指令文件或 Skill 挂载（Phase 5）。
- 凭据代理、强沙箱、网络出口、Fencing/Outbox 等完整安全可靠能力（Phase 6）。
- 独立 Task/Execution 表、Agent 配置关系化拆分、latest Adapter、跨 Engine 自动降级或通用策略后台。
- 新组件测试 runner、Postman 发布或外部预览服务；沿用 typecheck/i18n/build 与有针对性的 Playwright。

## 风险与约束

- **双写配置歧义**：旧根字段与 `react` 同值可规范化，异值必须拒绝；不得静默选值。
- **能力探测抖动**：同步热路径只读有界缓存；miss/stale/failure 均不可用，后台 probe 有超时，不启动外部 Engine。
- **策略来源不清**：平台默认 ceiling 最小授权，租户/Agent/Execution 只能收窄；未知能力/策略版本失败关闭。
- **快照泄露与膨胀**：五类 DTO 各自 denylist、schema/version 和大小上限；不保存秘密、Summary/Memory 原文、stderr 或宿主路径；公开仅白名单。
- **启动顺序误读**：`Repository.claim` 的公开 `run.started` 保持原序；快照屏障只约束 Adapter.start/副作用，不能借兼容名义改 Phase 2 公共事件。
- **指令回归**：Provider 不查询 Memory、不重复拼装系统提示，不改变双 emit/ack、history、budget、日志与完成后写回。
- **兼容性**：历史 `agents.draft`/`agent_versions.config` 原地不改；新默认字段只在用户明确采用新形态时持久化，历史读取和默认等价 diff 无噪声。
- **迁移约束**：`0058` 当前直接前驱为 `0057_industry_pack_runtime`；T2 前重验，禁止修改 `0053_routing_decisions` 或其他历史迁移。
