# Phase 2 · React Provider 与执行编排器 — 验收方案

> 状态：待评审 / 待实施
> 创建：2026-11-02
> 依据：`01-business-goals.md`（G1～G4、成功指标）、`02-requirements.md`（AC-1～AC-9）；执行依据见 `04-test-plan.md`

## 1. 验收目标与组织

确认 React Provider 与编排器**功能等价、Worker 解耦、SSE/终态可靠、开关可灰度回滚且对现有租户无感**，并给出签字结论。本文是待执行计划，不表示新路径已实现、已测量或已上线。

| 角色 | 职责 |
|---|---|
| 产品负责人 | 验收主持；现有租户体验与范围判定；P2 遗留处置签字 |
| QA | 执行 A1～A9、新旧 diff、双 SSE 和回归；缺陷分级与证据归档 |
| 研发负责人 | 提供实现和测试环境；出具性能/错误率测量；修复缺陷 |
| SRE/运维代表 | 灰度、混合 Worker、监控和回滚演练；部署与运行时 UAT 签字 |
| 租户/客服代表 | 对回复、工具结果、流式体验和取消行为做业务 UAT |

## 2. 验收环境与前置条件

| 环境 | 用途 |
|---|---|
| 类生产专用环境（固定 mock/真实模型两组） | A1～A9、功能等价、性能与错误率测量；真实模型不用于逐字确定性 diff |
| 专用 PostgreSQL + 双 Worker 配置组 | 终态竞争、Lease lost、混合新旧路径及滚动回滚 |
| quickstart demo 环境 | 默认 off、显式 on、现有 API/SSE 与零额外部署组件验证 |

**前置条件**：`04-test-plan.md` 全部通过，无 P0/P1 未关闭；Phase 0 基线数据已归档；验收租户/模型脚本/工具 fixture 专用；准备 off/on 配置和回滚 runbook；真实模型测试使用受控低敏数据，不将输出随机性误判为适配差异。

## 3. 功能验收清单（对应 AC-1～AC-9）

| # | 验收步骤 | 通过判据 |
|---|---|---|
| A1 | 对应 AC-1：对无快照与已发布 Agent 各运行同一固定模型脚本，legacy/on 各一次并导出 Run、事件和内部测试 Outcome | output、history/dropped、模型事件/usage、终态和 error_code 全部一致；Agent 快照未改，解析记录为 react/native/v1 |
| A2 | 对应 AC-2：运行工具循环、历史截断、summary/customer_memory、reasoning 和预算脚本，对比消息及 Memory 调用记录 | 工具参数/结果、消息顺序、dropped/memory_context、reasoning 历史与预算错误等价，reasoning 不进入可见输出 |
| A3 | 对应 AC-3：追踪一次 on 路径调用链，再用 LocalTestAdapter 替换 React 跑公共成功/失败/取消 | 生产 Run 经 Registry→Orchestrator→ReactAdapter；Worker 无 Engine 专属调用；替换 Adapter 不改 Worker 核心且仅一次 finish |
| A4 | 对应 AC-4：分别读取新旧内部与开放 SSE，验证 delta、持久事件、终帧、Last-Event-ID、tool.replay 和跨租户访问 | 类型/顺序/payload/seq/回放/心跳符合基线；delta 不落库；无重复终态、内部 metadata、history 或新增敏感字段 |
| A5 | 对应 AC-5：逐项注入缺模型、model timeout、非法/空响应、轮数/工具预算及未知异常 | 两路径 RunView/run.failed 的 error_code 一致，映射无通用化丢失；日志/API 无原始敏感异常 |
| A6 | 对应 AC-6：执行中取消并同时释放成功，重复 cancel，检查 Adapter 任务和 PG 终态/事件 | 清理完成，最终 cancelled 且无 output；无迟到 completed/第二终态，取消语义与旧路径一致，无 pending task |
| A7 | 对应 AC-7：分别触发 run/model timeout、Lease lost，再提交过期 Worker 成功结果 | error_code 分别为 run_timeout、model_timeout、worker_lost；终态均正确，迟到 output 被拒绝，终态事件唯一 |
| A8 | 对应 AC-8：验证默认 off、显式 on、混合 Worker，再制造 on 解析失败；最后 off 并滚动重启 | off/on 路径选择正确，混合执行等价；解析失败不静默兜底；回滚后所有新 Run 为 legacy，无数据库操作 |
| A9 | 对应 AC-9：检查 API/Agent 配置/迁移 diff、日志观测与既有回归 | 公共 schema 无变化、head=`0052`、日志含安全 path/三元组/终态且无敏感内容；回归全绿 |

每个场景执行记录必须包含：执行人、日期、环境、开关状态、前置数据/脚本版本、实际结果、判定、Run ID、CI/日志/SSE 证据链接。新旧 diff 必须附机器可读结果，不只写“人工看起来一致”。

## 4. UAT 判定（租户/客服代表与 SRE）

- 租户/客服代表在未修改 Agent 和客户端的情况下，确认回复、工具结果、流式输出、错误提示和取消体验与旧路径一致。
- SRE 能从安全日志/指标区分 legacy 与 orchestrator、定位 react/native/v1 和终态，且无法从日志读取 input/config/history/凭据。
- SRE 独立完成一次 on→off 滚动回滚，确认新 Run 全走 legacy、在途 Run 按既有规则收敛、无需迁移或客户端操作。

## 5. 业务指标验收

| 指标 | 基线 | 目标 | 测量方法 |
|---|---|---|---|
| 固定 React 回归语料语义一致率 | 待 Phase 0 建立基线 | output/history/dropped/事件/error_code/终态一致率 100% | 至少覆盖无快照、有快照、工具、Memory、失败五组；每组 legacy/on 同脚本对比并保存 diff |
| 新路径注册与编排覆盖率 | 待 Phase 0 盘点 | on 状态验收 Run 100% 经 react/native/v1 和 Orchestrator，Worker Engine 直接调用为 0 | 汇总验收 Run 的安全 path/三元组日志及调用链测试，抽样不得替代全量计数 |
| SSE 兼容率 | 待 Phase 0 录制基线 | 固定场景事件/seq/回放/delta/终帧一致率 100%，新泄露字段为 0 | 内部与开放 API 各至少覆盖成功、工具、取消、失败和重放，保存规范化 SSE diff |
| 取消/超时/迟到结果保护正确率 | 待 Phase 0 盘点 | 规定场景 100% 正确，迟到成功覆盖数为 0 | 执行 A6/A7 和真实 PG 竞争用例，逐个 Run 核对状态、output、error_code 和终态事件数 |
| 新路径性能与稳定性 | 待 Phase 0 测量 | p95 端到端延迟增量 ≤5%，新增错误率为 0 | 同一环境交替执行 legacy/on 各 ≥30 个固定脚本 Run，记录 p50/p95/首 token/错误率及资源；样本不足标 pending_env |
| 回滚恢复能力 | 待 Phase 0 演练 | 回滚后新 Run 100% legacy，无 downgrade/数据修复/客户端变更 | 混合 Worker 执行后 off 滚动重启，检查至少 20 个新 Run 的路径日志和在途 Run 收敛记录 |

## 6. 合规核对

| # | 核对项 | 判定 |
|---|---|---|
| C1 | 日志、错误、Execution metadata、内部与开放 SSE 不含密钥、原始堆栈、input/config/history 或未授权客户数据 | 一票否决 |
| C2 | tenant/business/workspace 隔离和公开字段过滤不变，跨租户 Run/SSE 不可达 | 一票否决 |
| C3 | 开关默认 false，off/on/混合/回滚均验证；回滚无需 Alembic downgrade、数据修复或客户端变更 | 必须通过 |
| C4 | RunRepository 仍是唯一 Run 终态/持久事件提交者，取消、Lease lost 和迟到成功保护未被绕过 | 一票否决 |
| C5 | 公共 API/SSE/Agent 快照和表结构不变，head 保持 `0052`；未夹带 Phase 3～6 功能 | 必须通过 |

## 7. 通过标准与签字

- **通过**：A1～A9 全部通过；语义/SSE/终态/回滚硬指标达成，性能采样满足目标或有经评审的有效环境数据；C1～C5 全过；无 P0/P1 遗留。
- **有条件通过**：仅 P2/P3 遗留且每条有 owner 与期限；不得豁免等价性、敏感信息、终态、开关或迁移硬要求。
- **不通过**：任一否决项、AC 或硬指标未达成；立即保持/恢复 off，修复后重验受影响项及全部新旧路径回归。
- **基线与环境说明**：Phase 0 未测数据不得编造；性能环境或样本不足标 `pending_env`，在获得有效数据前不得宣称性能达标或全面启用。

输出《Phase 2 验收报告》：AC 执行记录、新旧 diff、指标数据、灰度/回滚证据、合规结果、遗留清单、结论与以下签字。

| 角色 | 姓名 | 日期 | 结论 | 签字 |
|---|---|---|---|---|
| 产品负责人 | 待填写 | 待填写 | 待填写 | 待填写 |
| QA | 待填写 | 待填写 | 待填写 | 待填写 |
| 研发负责人 | 待填写 | 待填写 | 待填写 | 待填写 |
| SRE/运维代表 | 待填写 | 待填写 | 待填写 | 待填写 |
| 租户/客服代表 | 待填写 | 待填写 | 待填写 | 待填写 |
