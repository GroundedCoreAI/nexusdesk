# Phase 1 · 路由决策可见 — 验收方案

> 状态：待实施（本阶段上线前执行）
> 创建：2026-10-30
> 依据：`01-business-goals.md`（G1~G3、成功指标）、`02-requirements.md`（AC-1~AC-12）；测试执行依据见 `04-test-plan.md`

## 1. 验收目标与组织

确认本阶段交付物**功能正确**（AC 逐条复现通过）、**业务有效**（能拿到分流数据）、**安全可上线**
（SAVEPOINT 隔离、两条 409 契约可控、开关可关），并给出签字结论。

| 角色 | 职责 |
|---|---|
| 产品负责人 | 验收主持；FR-3/FR-4 两处有意行为变更的确认；P2 遗留处置签字 |
| QA | AC 场景执行与记录；回归结论；缺陷分级 |
| 研发负责人 | 环境保障；写延迟与失败计数数据出具；缺陷修复 |
| 客服运营代表 | 四语言规则的可接受性判定（UAT） |

## 2. 验收环境与前置条件

| 环境 | 用途 |
|---|---|
| 类生产环境（4 语言、含英文渠道） | 功能验收、指标测量 |
| quickstart 双容器（demo 模型） | 部署承诺验证（不涉及模型调用，验证不回归即可） |

**前置条件**：`04-test-plan.md` 全部用例通过，无 P0/P1 未关闭；验收使用专用租户与专用会话；基线快照（HTTP 状态码 + 持久化副作用）已从改造前版本采集完毕。`trace_enabled` 部署默认 `false`；完成迁移与部署冒烟后，验收方先在专用验收环境/指定 canary 显式设为 `true`，确认决策表可写，再执行 A1~A12；指标测量需在开启后观察 7 天再取数。A8 单独临时关闭记录开关验证，结束后恢复为 `true`。该开关是环境/进程级，不是租户级。

## 3. 功能验收清单（对应 AC-1~AC-12）

> 本阶段只验收 **4 种业务处置**（Reject / Handoff / Defer / Continue）与 **1 个执行档位**（Agent）；只有 `continue` 带 `execution_tier='agent'`，其余三种处置均为 `NULL`。
> Direct / Lightweight / Resume / Escalate 属后续阶段，不验收、不承诺可用。
> **本阶段有两处有意的行为变更**：FR-3 规则扩展（英文/繁体/印地语可转人工）、FR-4 两条 409 改为返回结果。

| # | 验收步骤 | 通过判据 |
|---|---|---|
| A1 | 关闭一个会话后发消息 | HTTP 409；决策 1 行 `reject/conversation_closed`；**`conversation_messages` 无新增**（与现状一致） |
| A2 | 发 `转人工` | 请求人工接管、不建 Run；决策 `handoff/request_handoff`，`matched_rule_id` 非空 |
| A3 | 发 `human`（英文渠道） | 转人工；决策 `handoff/user_requested_human`；**记录为与基线的有意差异** |
| A4 | 对 `mode=human` 会话发消息 | 消息入库、不建 Run；决策 `defer/human_mode_active` |
| A5 | 黑名单客户发消息 | 请求人工接管；决策 `handoff/blacklist_flag` |
| A6 | 发普通咨询 | 正常出 Run 与回复；决策 `continue/agent/submit_agent_run` |
| A7 | 无 agent 且 `model_backend=unconfigured` 时发消息 | HTTP 409 `model_not_configured`；决策 `reject/model_not_configured` |
| A8 | 在 A1~A7 通过后，临时关闭 `trace_enabled` 并重放 A1~A7，随后恢复开启 | 决策表零新增；HTTP 状态码与基线一致；**FR-3/FR-4 不随开关回退**（设计决定，需产品确认理解） |
| A9 | 查询会话决策 / 租户聚合 | 游标分页同时间戳不漏不重；聚合分布正确；换租户为空；`since/until` 校验生效 |
| A10 | 注入决策写入失败 | 主流程仍成功；日志有 WARN；summary 的 `routing_write_failures` 对当前 tenant +1、其他 tenant 不变；来源是 CustomerService 内的进程内 Counter，非跨副本聚合，重启清零 |
| A11 | 发 `your agent platform is slow` / 裸 `agent` | 不判转人工；决策 `continue/default_agent` |
| A12 | 渠道向已关闭会话 / 未配置模型会话发消息 | 两条入站事件逐条为 `status=processed`、`attempts=1`，无第二次 attempt、无重试；各写 1 行 `channel_receipts`，`channels.last_activity_at` 已更新且 `last_error_code IS NULL`（无代码改动） |

每个场景执行记录：执行人、日期、环境、前置数据、实际结果、判定、截图/日志链接。

## 4. UAT 判定（客服运营代表）

- 四语言确定性关键词规则能否覆盖真实客户表达（抽样 20 条真实会话人工判断误判/漏判，阈值由运营确认）。
  句内表达（`I want to speak to a human`）已知不命中，需运营确认可接受。
- 决策记录内容是否足以支撑客诉归因（用 3 条历史客诉复盘验证）。

## 5. 业务指标验收

| 指标 | 基线 | 目标 | 测量方法 |
|---|---|---|---|
| 决策覆盖率 | 0 | **数据库健康时** 100%（含两条 Reject 分支）；写入失败单独计数并告警，不计入覆盖率 | 专用租户连续 100 条消息，决策行数 / 成功返回请求数 |
| 决策写入失败率 | — | < 0.1% 且可观测 | 跨副本用 WARN 日志聚合计算；summary 的 `routing_write_failures` 只代表当前进程/租户，重启清零，不能单独作为全局失败率 |
| 附加写延迟 P95 | — | ≤ 5ms | 决策 INSERT 的 statement 时长，样本 ≥ 100 |
| 人工请求规则命中 | 仅中文 2 词硬编码 | 四语言用例全命中 | 验收用例集逐条执行 |
| 分流数据可得性 | 无 | 可按 `disposition` 与 `reason_code` 聚合 | 跑通 A9 并导出一次分布，供 Phase 2 收益测算 |
| 渠道无效重试次数 | 两条 409 各首次 + 最多 4 次重试（`max_attempts` 默认 5），最终 `failed` | 0 次重试；首次处理即 `processed`，`attempts=1` | 查 `channel_inbound_events.attempts/status`，同时核对 `channel_receipts` 与 `channels.last_activity_at/last_error_code` |

## 6. 合规核对

| # | 核对项 | 判定 |
|---|---|---|
| C1 | 决策记录不含消息原文、摘要或客户敏感信息（仅长度与关联 id） | 一票否决 |
| C2 | 跨租户不可达（列表与聚合均验证） | 必须通过 |
| C3 | 开关可关闭记录；**FR-3/FR-4 的行为变更需回滚代码才能撤销，已明示** | 必须通过 |
| C4 | Core Platform 未被引入业务语义（架构门禁 + 人工核对字符串） | 必须通过 |
| C5 | 业务配置（开关、人工请求规则）定义在客服能力内，`core_platform` settings 零新增业务项 | 必须通过 |

> C4 说明：本项目架构门禁只校验 import 关系，**不校验字符串里的业务词汇**。本阶段 Core 应零改动，人工核对成本极低。
> C5 说明：客服词表放进 Core Settings 会把"转人工/人工客服/representative"这类业务短语带进 Core，属同一类越界，单独列为核对项。

## 7. 通过标准与签字

- **通过**：A1~A12 全部通过；覆盖率（健康条件）与写延迟达标；合规项全过；无 P0/P1 遗留；Phase 2 所需分布数据已产出。
- **有条件通过**：仅 P2/P3 遗留且每条有 owner 与期限，硬指标达标。
- **不通过**：任一否决项触发，或 A1 出现"关闭会话消息被入库"、A10 事务隔离未达标、A8 开关语义与产品理解不一致。

输出《Phase 1 验收报告》：AC 执行记录表、指标测量数据、合规核对结果、遗留清单、结论与签字（产品 / QA / 研发 / 客服运营）。
