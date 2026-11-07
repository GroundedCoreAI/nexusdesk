# Phase 3 · 能力、配置与指令 — 业务目标

> 状态：待评审（未开始实施）
> 创建：2026-11-02
> 依据：`docs/architecture/agent-execution-platform-v2.md` 第 5、6、11、14、15、17 节 Phase 3、19、22 节；Phase 0–2 规划文档
> 预估工期：~2 周（Phase 0 基线完成后重估）
> 依赖：Phase 0 兼容基线完成；Phase 1 执行契约与注册中心、Phase 2 React Provider 与编排器已验收

## 要解决的问题

### 问题 1：Agent 配置无法安全表达多 Engine 选择

当前 `backend/src/agent_platform/business_capabilities/agent_config/service.py` 的 `AgentConfig` 只有 ReAct 相关字段，`backend/src/agent_platform/applications/platform_runtime/runtime_factory.py` 固定构造 `RuntimeEngine`。直接增加自由字典会让未知 Engine、错误类型和版本漂移进入已发布快照，也无法保证旧配置无损加载。

### 问题 2：技术能力、环境可用性与授权没有统一判定链

架构要求区分 Declared、Available、Policy 与 Effective，但当前没有该解析链。若直接采用 Adapter 声明或客户端字段，可能把“支持终端”误当成“允许终端”，并使 UI、编排器和审计对同一 Run 得出不同结论。

### 问题 3：指令与 Summary/Memory 注入绑定 ReAct 消息结构

`backend/src/agent_platform/core_platform/agent_runtime/engine.py` 直接组装 SystemMessage；`worker.py` 与 `business_capabilities/memory/injection.py` 已分别负责摘要和客户记忆的获取、渲染及开关。若没有 Instruction Provider 边界，新 Engine 要么复用不适用的 ReAct 结构，要么复制记忆逻辑并产生行为分叉。

### 问题 4：单次执行缺少不可变的决策快照

现有 `runtime_runs.config` 保存 Run 入参快照，但没有独立的解析后执行配置、各层能力和策略快照。发布后配置、部署探测或策略变化后，难以解释历史 Run 为什么允许或拒绝某项能力。

## 业务目标

| 目标 | 说明 |
|---|---|
| G1：兼容且类型化的多 Engine 配置 | 旧配置默认解析为 `(react,native,v1)`；新配置按 Engine/Protocol/Adapter 精确校验，草稿与发布仍复用现有 JSONB 链路 |
| G2：服务端能力治理 | 建立 Declared → Available → Policy → Effective 的单调收窄链路，客户端和 Adapter 均不能越过环境或策略提权 |
| G3：可替换的 Engine 指令渲染 | 通过 Instruction Provider 适配 Engine 格式，同时复用现有 Summary/Memory 开关、渲染文案、顺序和降级行为 |
| G4：可追溯且可回滚的执行决策 | 每次经 Phase 3 路径执行的 Run 持久化解析后配置、能力与策略快照；开关回退不影响历史快照读取 |

## 成功指标

| 指标 | 基线（现状） | 目标 |
|---|---|---|
| 存量 Agent 草稿与发布快照兼容率 | 待 Phase 0 测量真实脱敏样本与边界样本 | 合法样本加载、规范化、再发布和执行通过率 100%；原始历史 JSONB 不被批量改写 |
| 非法或未知执行配置拒绝率 | 待 Phase 0 盘点现有校验覆盖 | 未知三元组、类型错误、额外字段、冲突别名及不可用必需能力拒绝率 100%，错误码稳定 |
| 客户端能力提权成功数 | 待 Phase 0 盘点现有请求信任边界 | 伪造 Declared/Available/Effective、策略或 Engine 内部字段的提权成功数为 0 |
| Phase 3 Run 决策快照完整率 | 待 Phase 0 测量现有 Run 元数据覆盖 | 新路径完成、失败、取消、超时 Run 的快照覆盖率 100%；缺失快照不得进入 Adapter 启动阶段 |
| React 指令兼容回归通过率 | 待 Phase 0 建立 Summary/Memory 消息序列基线 | 空态、开关关闭、摘要、客户记忆及组合场景的既有消息顺序与文案 diff 为 0 |
| 配置与能力解析附加延迟 | 待 Phase 0 测量 Run admission/claim 延迟 | 使用已缓存注册表与策略时，单 Run 服务端解析 p95 增加不超过 50ms；外部可用性探测不进入同步热路径 |

## 范围

**包含**：

- 在现有 AgentConfig JSONB 草稿/发布快照中增加 Engine 选择与 Engine 专属类型化配置，不新增 Agent 配置表。
- 提供旧字段到规范化执行配置的兼容映射，固定缺省三元组 `react/native/v1`。
- 实现能力声明、部署可用性检查、策略解析、Effective 能力计算与只读展示。
- 实现 Instruction Provider、React Provider 及测试 Provider 契约，复用现有 Summary/Memory 渲染结果。
- 规划迁移 `0053_agent_execution_metadata`，只在 `runtime_runs` 增加执行配置、分层能力和策略快照所需的可空字段。
- 配置、API、前端类型/展示、审计、测试、上线与回滚设计。

**不包含**（属于后续阶段 / 明确不做）：

- Runtime Host、真实外部进程、Execution Workdir 或 Sandbox（Phase 4）。
- Codex CLI/App-Server 及其生产指令文件、Skill 挂载（Phase 5）。
- 凭据代理、强沙箱、网络出口、Fencing/Outbox 等完整安全可靠能力（Phase 6）。
- 独立 Task/Execution 表、Agent 配置关系化拆分、自动选择 latest Adapter 或跨 Engine 自动降级。
- 通用租户策略管理后台；本阶段只接入受信任 Policy Provider 与静态/既有策略源。

## 风险与约束

- **双写配置歧义**：旧根字段与新 `react` 字段可能冲突；同值可规范化，不同值必须拒绝，禁止静默选一个。
- **能力探测抖动**：外部进程或网络探测可能阻塞执行；Phase 3 只使用有界、缓存的部署探测，失败按不可用处理并记录原因。
- **策略来源不清**：没有可信来源时不得默认放开；平台默认策略是上限，租户/Agent/Execution 只能继续收窄。
- **快照泄露**：解析配置可能含内部标识或提示词；快照不得包含凭据、原始客户记忆或宿主秘密，公开响应不得直接返回内部快照。
- **指令回归**：Provider 重构可能改变 Summary/Memory 顺序或重复注入；React 必须通过 Phase 0 的逐消息兼容测试。
- **兼容性**：历史 `agents.draft` 与 `agent_versions.config` 原地不改；旧记录只在用户正常保存/发布时生成新版本，不为补默认值而批量迁移。
- **迁移约束**：`0053` 是规划号；实施前必须重验 head 和 `down_revision`，禁止修改已应用的 `0052` 或更早迁移。
