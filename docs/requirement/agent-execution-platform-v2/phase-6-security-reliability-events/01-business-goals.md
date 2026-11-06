# Phase 6 · 安全、可靠性与事件治理 — 业务目标

> 状态：待评审（仅规划，未实施；不可信多租户代码执行前的阻断阶段）
> 创建：2026-11-02
> 依据：`docs/architecture/agent-execution-platform-v2.md` 第 3、7~10、12~13、17（Phase 6）、18.2/18.4/18.6、19~22 节；现状核查见 `03-technical-design.md`

> 阶段：Phase 6（安全、执行可靠性、事件可靠性三条工作流，统一硬门禁验收）
> 预估工期：约 6~8 周，设计评审与故障演练环境确认后冻结
> 依赖：Phase 0~5 已验收；Phase 4 RuntimeHost/Workspace 可用；支持故障注入、沙箱对抗与独立安全审计的类生产环境

## 要解决的问题

### 问题 1：现有加密凭据能力不等于 Execution 级安全边界

当前 `CredentialVault` 主要服务模型网关连接，缺少 Engine Execution 的短期授权、目标/范围绑定、吊销、 Broker 审计和统一脱敏。Codex 等外部 Engine 若直接继承宿主凭据或长期环境变量，会扩大跨租户与事后泄露风险。

### 问题 2：逻辑 Workspace 与工具网络策略不能替代强沙箱

现有 Workspace/工具 egress 有局部保护，但不可信 Agent 命令需要进程、挂载、文件、网络、系统调用与资源联合隔离。路径穿越、符号链接、DNS rebinding、云元数据访问和宿主逃逸必须按攻击面验证，而非只检查配置存在。

### 问题 3：owner/lease 终态保护仍缺跨 Worker Fencing

当前 Repository 能拒绝部分过期 owner 写入，但没有单调递增 Lease Epoch/Fencing Token 覆盖所有事件、结果、用量、Session、Outbox 与资源操作。Worker 丢失、租约续期竞态、迟到结果和重试副作用仍可能产生不一致。

### 问题 4：事件持久化与 SSE 先例尚未形成完整可靠投递体系

当前事件和 Run 可同事务写入，SSE 支持游标重放，NOTIFY 只作唤醒；但缺统一 schema/version/source/event_id、原生事件去重、事务性 Outbox、保留期游标缺口处理和 usage 幂等聚合。parser 失败也缺有界、脱敏、可统计诊断。

## 业务目标

| 目标 | 说明 |
|---|---|
| G1：建立 Execution 凭据安全闭环 | Vault/Broker 提供加密、版本、范围、短期授权、轮换、吊销与审计，凭据只在授权 Execution 内最小暴露。 |
| G2：建立不可信执行强隔离 | 强沙箱、默认拒绝网络、文件/挂载隔离与资源限制共同生效，通过真实逃逸与数据外泄对抗。 |
| G3：保证执行所有权与恢复一致性 | Lease Epoch/Fencing 阻止过期 Worker 的一切有效写入；Worker 丢失、迟到结果、取消和清理保持一致终态。 |
| G4：保证副作用与配额可恢复 | 重试按错误和副作用分类；进程、Workdir、连接、资源预留与配额在成功、失败、取消、超时和崩溃后正确释放。 |
| G5：建立版本化可靠事件体系 | schema、sequence、event_id、dedup、事务性 Outbox 与 SSE replay 共同保证可追踪、可重放、无静默缺口。 |
| G6：保证用量幂等与解析可诊断 | 重复/迟到 usage 不重复聚合或计费；原生解析失败有脱敏、有界、可关联诊断和明确降级策略。 |
| G7：兼容存量并可验证上线 | React/Codex、现有 Run/API/SSE 和历史数据可迁移回退；未测基线待 Phase 0，安全与可靠性硬指标不得以平均值替代。 |

## 成功指标

| 指标 | 基线（现状） | 目标 |
|---|---|---|
| Execution 凭据越权与明文泄露 | 未测，待 Phase 0 安全基线 | 对抗场景越权授权、跨租户/跨 Execution 使用和明文泄露均为 0；吊销后新使用 100% 拒绝。 |
| 沙箱/文件/网络逃逸 | 未测，待 Phase 0 | 规划攻击矩阵中成功逃逸、元数据访问和未授权外联均为 0；任何 P0 即停止开放。 |
| 过期 Worker 有效提交数 | 未测，待 Phase 0 | 故障注入下状态、事件、usage、Session、Outbox 的过期提交均为 0，且有 Fencing 拒绝审计。 |
| Worker 丢失与迟到结果一致性 | 未测，待 Phase 0 | 100% 场景进入定义的可恢复状态或终态；迟到结果覆盖、双终态和重复副作用均为 0。 |
| 取消确认与清理/配额一致率 | 未测，待 Phase 0 | 100% 场景满足真实退出/清理确认；无法确认时不伪报 cancelled；无残留预留或配额泄漏。 |
| 事件持久化/Outbox 原子性 | 未测，待 Phase 0 | 故障点注入下部分状态+缺失终态事件、无事件 Outbox 或重复业务效果均为 0。 |
| SSE 重放完整性 | 当前已有基本游标重放；完整性与规模未测，待 Phase 0 | 保留期内事件无静默缺口；断线重连后按 event_id 去重，终态与最终事件一致。 |
| usage 重复聚合/计费 | 未测，待 Phase 0 | 重复、重放、Worker 重试下同源 usage 重复计数为 0；修正记录可追溯。 |
| parser 诊断覆盖与泄露 | 未测，待 Phase 0 | malformed/未知原生事件均产生有界分类诊断；Secret canary 泄露为 0，诊断不导致事件风暴。 |
| 安全与可靠性开销 | 未测，待 Phase 0 | 记录 p50/p95、Outbox lag 和恢复时间；预算在基线后评审，未测不得宣称无性能影响。 |
| 存量回归差异 | 未测，待 Phase 0 | 兼容模式与回滚场景 diff 为 0，适用既有测试全绿。 |

## 范围

**包含**：

- Execution Credential Vault/Broker、类型化 Secret 引用、短期 grant、目标/范围绑定、轮换/吊销/审计与统一脱敏。
- 强沙箱 Provider、默认拒绝网络 egress、DNS/IP/重定向防护、文件/挂载/产物隔离与资源限制。
- Lease Epoch/Fencing Token、Worker 丢失检测、迟到结果/终态保护、取消确认、超时清理、重试副作用与配额释放。
- 事件 schema/version/source/event_id/sequence、去重、Event Store/事务性 Outbox、SSE 重连/游标重放与保留期缺口处理。
- usage 幂等聚合、parser diagnostics、迁移/回填/协调任务、指标告警、对抗与故障注入演练。
- 规划迁移 `0056_execution_fencing_event_outbox` 与 `0057_execution_credential_security`，以及兼容发布和回滚方案。

**不包含**（属于后续阶段 / 明确不做）：

- 新 Engine、多 Engine 路由/回退、全局公平调度与完整成本报表：属于 Phase 7 或后续。
- 微服务拆分、独立 Task/Execution 双表模型或整体重写调度器：沿用模块化单体和 Run=一次 Execution 尝试。
- 外部 KMS/Secret Manager 的具体厂商集成：本阶段定义可替换 Vault/Broker 接口与安装密钥实现；厂商适配按部署需求后续落地。
- 无限期保存原始事件、未脱敏 payload 或 Secret；不承诺跨保留期的完整 SSE 重放。
- 以“可信租户”豁免本阶段安全验收，或在任一硬门禁未过时开放不可信代码执行。
- 本阶段不修改历史迁移，不把当前局部保护写成已经满足完整目标。

## 风险与约束

- **迁移与回填竞态**：新增 event_id、epoch 和 Outbox 需与旧 Worker 并存；采用 expand/backfill/validate/switch，规划号实施前重核 head，不修改历史迁移。
- **Fencing 覆盖不完整**：只保护 Run 状态仍会泄露事件或 usage；所有接受 Worker 写入的 Repository/资源操作必须校验 `(run_id, owner, lease_epoch)`。
- **超时不代表无副作用**：进程可能已执行外部写入；模糊结果默认不自动重试，需幂等键/副作用凭证或人工恢复。
- **取消确认与可用性冲突**：无法证明进程停止时不能为了 UI 体验伪报 cancelled；进入明确失败/待清理状态并告警，资源保持隔离。
- **脱敏误报与漏报**：仅替换已知 Token 不够；组合注册 Secret、canary、通用模式、结构化字段与产物隔离，原始诊断有界且不进入普通事件。
- **Outbox 不是通知总线**：NOTIFY/SSE 仍是投递加速层，Event Store 是事实源；Outbox 发布失败可重试，不能阻塞安全拒绝或伪造已完成。
- **不可信开放硬门槛**：Vault/Broker、强沙箱、网络/文件隔离、Fencing/恢复、事件一致性和对抗验收任一未完成，均不得向不可信租户开放。
- **兼容性**：新增列/表采用向后兼容扩展，既有 SSE `id` 继续使用 Run 内 sequence；回滚不得要求删除凭据或事件数据。
