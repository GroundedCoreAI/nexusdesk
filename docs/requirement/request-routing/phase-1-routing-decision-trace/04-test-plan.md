# Phase 1 · 路由决策可见 — 测试方案

> 状态：待实施（本阶段开发完成后执行）
> 创建：2026-10-30
> 依据：`02-requirements.md`（FR-1~FR-6、AC-1~AC-12）、`03-technical-design.md`（判定序列、SAVEPOINT、两条 409 契约、无事件）

## 1. 测试范围与原则

**范围**：`routing_decisions` 表与迁移、`customer_service/routing/` 四个模块、`send()` 改造、两个查询端点、客服能力配置。

**原则**：

1. **等价性限定在 HTTP 边界与持久化副作用**：Phase 1 有 FR-3、FR-4 两处有意变更，**不要求 `send()` 内部返回值与基线相等**。
2. **SELECT 次数与顺序不变必测**：`agent_snapshot` 不得提前查；总 SQL 数预期 `+1`（新增决策 INSERT）。
3. **失败不反噬必测**：SAVEPOINT 注入失败后主流程必须仍然成功。
4. **两条 409 都必测**：`conversation_closed` 与 `model_not_configured` 是同一类缺陷，不能只测一条。
5. **Reject 不得写消息**：现状 closed 分支不写 `conversation_messages`，必须断言改造后也没写。
6. **不等待时间**：本阶段无退避/过期逻辑。

## 2. 测试环境与数据构造

| 环境 | 用途 |
|---|---|
| 单测（无 DB） | 判定序列、规则归一化与精确匹配、开关行为、规则 id 稳定性 |
| 集成（PG + `pytest.mark.postgres`） | 决策落库、事务/回滚、查询与聚合、租户隔离、渠道入站 |
| SQL 计数（`before_cursor_execute`） | SELECT 次数与顺序、锁序 |

**数据构造**：直接写库构造四种 `mode`；黑名单用 `upsert_flag(..., "blacklist", ...)`；`model_not_configured` 通过 `settings.model_backend="unconfigured"` + 无 agent 会话构造；写入失败通过临时触发器注入；基线对照在改造前分支跑同一组用例并记录 HTTP 状态与持久化快照。

集成用例默认在 `trace_enabled=true` 下执行（包括 P1-IT-13 的 SQL 基线 `+1` 断言）；只有 P1-IT-12 显式关闭记录开关，用于验证 AC-8。

## 3. 单元测试

| 编号 | 用例 | 预期 | 溯源 |
|---|---|---|---|
| P1-UT-01 | `mode=closed` 判定 | `reject / action=reject / conversation_closed`、`execution_tier=NULL` | FR-2、AC-1 |
| P1-UT-02 | 中文 `转人工` / `人工客服` / `客服` 命中 | `handoff / request_handoff / user_requested_human`、`matched_rule_id=zh_human_request_001` | FR-2、FR-3、AC-2 |
| P1-UT-03 | 英文 `human` / `real person` / `representative` / `human agent` 命中 | `handoff`、`matched_rule_id=en_human_request_001` | FR-3、AC-3 |
| P1-UT-04 | `mode=human` / `mode=waiting` | `defer / action=defer`、`human_mode_active` / `waiting_mode_active` | FR-2、AC-4 |
| P1-UT-05 | 黑名单且开关打开 | `handoff / blacklist_flag` | FR-2、AC-5 |
| P1-UT-06 | 其余 | `continue / agent / submit_agent_run / default_agent` | FR-2、AC-6 |
| P1-UT-07 | 归一化边界：`" HUMAN "`、`"ＨＵＭＡＮ"`、`"human."` | 命中（含句末标点剥离） | FR-3 |
| P1-UT-08 | 精确匹配反例：`"your agent platform is slow"`、`"human being"`、裸 `"agent"` | **不命中** | FR-3、AC-11 |
| P1-UT-09 | `trace_enabled=false` | 不产生写入调用 | FR-6、AC-8 |
| P1-UT-10 | 规则配置为非法 JSON | 回退默认规则并记 WARN，不抛错 | FR-3 |
| P1-UT-11 | 落库参数 | 只写 `message_length` 与 `request_id`；无 `message_digest` 列、无预留列 | FR-1、FR-2 |
| P1-UT-12 | 规则 id 稳定性 | 调换 `handoff_rules` 顺序后，同一短语仍匹配到同一 `matched_rule_id` | FR-3 |
| P1-UT-13 | 约束不变量 | `reject` 带 `execution_tier` 被拒；`continue` 无档位**允许**；`message_length<0` 被拒；同作用域重复 `request_id` 被拒 | FR-2 |
| P1-UT-14 | zh-TW `轉人工` 命中 | `handoff`、`matched_rule_id=zhtw_human_request_001` | FR-3 |
| P1-UT-15 | 印地语 `मानव` / `एजेंट` 命中 | `handoff`、`matched_rule_id=hi_human_request_001` | FR-3 |
| P1-UT-16 | locale-agnostic 并集匹配 | 匹配器不读取 `locale` / 渠道语言；`客服` 在渠道声称为 `en` 或 `zh-TW` 时仍稳定命中 `zh_human_request_001` | FR-3 |
| P1-UT-17 | 规则 id 与归一化 phrase 全局唯一 | 规则 id 重复，或两条规则分别配置 `" HUMAN "` 与 `human`（归一化后相同）时，设置模型 validator 拒绝该配置 | FR-3 |

## 4. 集成测试

| 编号 | 用例 | 预期 | 溯源 |
|---|---|---|---|
| P1-IT-01 | 对 `closed` 会话发消息 | HTTP 409；`send()` 返回 `rejected`；决策 1 行 `reject/conversation_closed`；**`conversation_messages` 无新增行** | AC-1 |
| P1-IT-02 | 中文转人工 | 返回 `handoff`、`run=None`；决策 1 行 `handoff/request_handoff` | AC-2 |
| P1-IT-03 | 英文 `human` | 与 P1-IT-02 相同（**记录为与基线的有意差异**） | AC-3 |
| P1-IT-04 | `mode=human` 会话 | 消息入库、history 更新、`run=None`；决策 `defer/human_mode_active` | AC-4 |
| P1-IT-05 | 黑名单客户 | 请求人工接管；决策 `handoff/blacklist_flag` | AC-5 |
| P1-IT-06 | 普通消息 | 创建 Run 且持久化副作用与基线一致；决策 `continue/agent` | AC-6 |
| P1-IT-07 | 无 agent 且 `model_backend=unconfigured` | HTTP 409 `model_not_configured`；决策 1 行 `reject/model_not_configured` | AC-7 |
| P1-IT-08 | 注入决策写入失败 | **SAVEPOINT 回滚后主流程仍成功**（消息入库、Run 创建正常）；日志记 WARN 且不抛错；该 tenant 的进程内 Counter 计数 `routing_write_failures` +1，其他 tenant 不变；重启清零 | AC-10 |
| P1-IT-09 | `_submit_run` 抛错致外层回滚 | 决策行不存在（与业务结果同生共死） | FR-1 |
| P1-IT-10 | 租户 B 查租户 A 的会话决策 | 空结果，不泄露 | FR-5、AC-9 |
| P1-IT-11 | 聚合接口 | `disposition` / `reason_code` 计数与写入一致；`since/until` 格式与跨度校验生效 | AC-9 |
| P1-IT-12 | 关闭开关后重跑 AC-1~AC-7 | 决策表零新增；HTTP 状态码与基线一致；**FR-3 规则扩展与 FR-4 契约不随开关回退** | AC-8 |
| P1-IT-13 | SELECT 次数与顺序（记录开启） | 与改造前一致（证明未提前查 `agent_snapshot`）；总 SQL 数为基线 `+1`（新增决策 INSERT） | FR-2、03 关键约束 |
| P1-IT-14 | 锁序断言 | 受理咨询锁先于会话锁；决策写入不引入新锁 | 01 风险、FR-1 |
| P1-IT-15 | 渠道入站收到两条 409 对应消息 | 两条事件逐条断言：首次处理即 `status=processed`、`attempts=1`，不再有第二次 attempt、无 pending/重试；各写 1 行 `channel_receipts`，`channels.last_activity_at` 已更新且 `last_error_code IS NULL`（无代码改动） | AC-12 |
| P1-IT-16 | 游标分页 | 同 `created_at` 的多行不漏不重（按 `id` 二次排序） | AC-9 |

## 5. 通用核对项（本阶段适用）

| 编号 | 核对项 | 通过标准 |
|---|---|---|
| P1-CM-01 | 迁移在线性 | 存量库 `upgrade head` 成功；`downgrade` 仅删新表；不动已有表；`EXPLAIN (ANALYZE)` 确认三个索引被真实查询命中 |
| P1-CM-02 | 配置加载与归属 | `trace_enabled` 默认 `false`；`AGENT_CS_ROUTING_TRACE_ENABLED` / `AGENT_CS_ROUTING_HANDOFF_RULES` 覆盖生效；部署后先保持关闭，再在指定的环境/进程 canary 显式开启并观察 7 天，不是租户级灰度；**配置定义在客服能力内，`core_platform` settings 零新增业务项** |
| P1-CM-03 | 观测面 | 表字段齐全；**不发布任何事件**（断言无新增 event task）；不含消息原文 |
| P1-CM-04 | 租户隔离 | 跨租户不可达（列表与聚合均验证） |
| P1-CM-05 | Core 边界 | `core_platform` 无新增 import 业务模块、无新增业务词汇（含字符串）；架构门禁通过 |

## 6. 回归范围

- 后端全量：`pytest -m "not postgres"` 与 `pytest -m postgres`（CI 两个分片）
- 重点回归：`tests/test_*customer_service*`、`tests/test_runtime_postgres.py`、人工接管相关用例、渠道入站用例
- 断言：新增表为空时既有行为不变；**两条 409 的 HTTP 状态码不变**

## 7. 缺陷分级与出口准则

| 级别 | 定义 | 处理 |
|---|---|---|
| P0 阻断 | 主流程被破坏；消息丢失或不该入库的消息入库；跨租户泄露 | 修复并回归后方可继续 |
| P1 严重 | 分支行为与基线不一致（FR-3/FR-4 除外）；开关失效；决策写入失败影响主流程 | 修复前不得进入验收 |
| P2 一般 | 规则覆盖不足；聚合口径偏差 | 记录后可带问题验收，需产品签字 |
| P3 轻微 | 文案、日志、注释问题 | 排期修复 |

**出口准则**：UT/IT/CM 全部通过；AC-1~AC-12 在集成环境复现通过；回归套件全绿；
**SAVEPOINT 失败注入下主流程仍成功**；**两条 409 的 HTTP 状态码与基线一致**；无 P0/P1 未关闭。
