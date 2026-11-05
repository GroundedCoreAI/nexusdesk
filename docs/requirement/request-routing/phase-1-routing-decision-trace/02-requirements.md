# Phase 1 · 路由决策可见 — 需求文档

## 用户故事

**US-1（客服主管）**：作为客服主管，我希望看到每条客户消息被判定成了哪一类、依据是什么，以便在客户投诉没人回复时快速归因，而不是翻应用日志推测。

**US-2（海外运营）**：作为负责海外渠道的运营，我希望客户无论渠道语言，说 "human" 或 "客服" 时也能转人工，以便海外用户不会卡在机器人流程里。

**US-3（产品负责人）**：作为产品负责人，我希望拿到各分支的真实占比，以便决定是否值得投入 `direct` / `lightweight` 档位改造，而不是凭感觉排期。

**US-4（研发）**：作为研发，我希望改造入口判定时有可逐条对照的验证手段，以便不因为重构客服主链路而引入回归。

## 功能需求

### FR-1 路由决策采集

| 项 | 说明 |
|---|---|
| 触发时机 | `CustomerService.send()` 完成判定后、执行动作前 |
| 输入 | 会话行（`mode`、`customer_id`、`agent_id`）、消息文本与长度、有效记忆开关与旗标、人工请求规则命中结果、本次请求的 `request_id` |
| 输出 | `routing_decisions` 一行：`disposition`、`execution_tier`、`action`、`reason_code`、`matched_rule_id`、`decider`、`message_length` |
| 执行方式 | 同步，**在 `send()` 既有事务内、用 SAVEPOINT 隔离**写入；不新开事务、不改变锁序 |
| 失败处理 | 写入失败**不得**影响消息处理：回滚到 SAVEPOINT、记 WARN、在 `CustomerService` 内按 tenant 递增进程内 failure counter（`routing summary` 返回 `routing_write_failures`），继续既有分支；不重试。该计数不跨副本/进程聚合，重启清零；连接断开/事务失效时由既有数据库错误处理决定整体失败，不承诺绝对隔离 |
| 边界 | **本阶段不发布事件**（无消费者，且两条调用路径的真实提交点不同），只写表 |

### FR-2 决策语义等价现状（硬约束）

决策记录按**维度**表达，不使用单一模式枚举：

- `disposition`：业务处置（`reject` / `handoff` / `defer` / `continue`）
- `execution_tier`：执行档位，**仅 `continue` 可能有值**，本阶段唯一取值 `agent`
- `action`：客服能力内部的执行指令，执行器按它分派，**不按 `reason_code` 分派**
- `reason_code`：解释**为什么**
- `matched_rule_id`：命中的具体规则（仅人工请求规则有值）

判定序列必须与现状**动作等价**（除 FR-3、FR-4 两处有意变更）：

| 现状分支（`service.py`） | `disposition` | `execution_tier` | `action` | `reason_code` |
|---|---|---|---|---|
| 第 129 行 `mode == "closed"` | `reject` | `NULL` | `reject` | `conversation_closed` |
| 第 131 行 命中人工请求规则 | `handoff` | `NULL` | `request_handoff` | `user_requested_human` |
| 第 142 行 `mode == "human"` | `defer` | `NULL` | `defer` | `human_mode_active` |
| 第 142 行 `mode == "waiting"` | `defer` | `NULL` | `defer` | `waiting_mode_active` |
| 第 167 行 黑名单旗标命中 | `handoff` | `NULL` | `request_handoff` | `blacklist_flag` |
| 第 196 行 `model_backend == "unconfigured"` 且无 agent | `reject` | `NULL` | `reject` | `model_not_configured` |
| 其余 | `continue` | `agent` | `submit_agent_run` | `default_agent` |

同时写入 `decider = "cs_routing_v1"`（判定规则版本；**不再用 `legacy_branch_v1`**，因为规则已含扩展）。**不建任何预留列**（`task_relation` / `escalate_from` / `decision_type` / `stage_ids` / `confidence` / `profile_ref`），语义定型前不建。

### FR-3 人工请求规则（确定性关键词，非意图识别）

| 项 | 说明 |
|---|---|
| 触发时机 | 与现行第 131 行判定同一位置，替换硬编码集合 |
| 归一化 | 去首尾空白、大小写折叠、全角转半角、剥离句末单个标点 |
| 匹配方式 | 整个消息与规则短语**相等**；**禁止任意子串包含**，否则 `your agent platform is slow` 会被误判 |
| 匹配范围 | **locale-agnostic 并集匹配**：`locale` 仅作规则元数据，不参与筛选；同一消息可命中任一 locale 的规则 |
| 规则结构 | `{"id": "en_human_request_001", "locale": "en", "phrases": [...]}`；**id 必须显式**，不能用"语言+下标"生成，否则调词表顺序会让历史记录指向错误规则 |
| 稳定性与唯一性 | 规则 id 与归一化 phrase 是跨阶段稳定契约；规则 id 全局唯一，归一化后的 phrase 必须全局唯一。调换规则或短语顺序不得改变同一短语的 `matched_rule_id` |
| 输出 | 命中时 `disposition=handoff`、`reason_code=user_requested_human`、`matched_rule_id=<规则 id>` |
| 默认规则 | zh-CN（`转人工`、`人工客服`、`客服`）、zh-TW（`轉人工`）、en（`human`、`real person`、`representative`、`human agent`）、hi（`मानव`、`एजेंट`） |
| 失败处理 | 配置解析或校验失败（含重复 id、归一化后重复 phrase，如 `" HUMAN "` 与 `human`）时回退默认规则并记 WARN，不得因配置错误把正常消息判成转人工 |

**明确边界**：这是**可配置的确定性关键词规则**，不是完整的多语言意图识别。`I want to speak to a human` 这类句内表达**不命中**，属有意取舍；裸 `agent` 有误触风险，**明确不支持**，默认用 `human agent`。

### FR-4 两条 409 改为返回结果（修掉决策丢失与渠道重试）

| 项 | 说明 |
|---|---|
| 现状问题 | `conversation_closed`（第 129 行）与 `model_not_configured`（第 196 行）都 `raise DomainError(409)`：整个事务回滚 → 决策记录丢失；渠道把 409 当可重试错误，按首次 + 最多 4 次重试（默认 `max_attempts=5`，共最多 5 次 attempt）后 failed，客户全程收不到回复 |
| 改动 | `send()` 改为返回 `{"conversation_id", "run": None, "rejected": "<reason_code>"}`，不再抛异常 |
| 调用方映射 | `platform_routes.py` 的 messages 端点把 `rejected` 映射为 409（对外状态码不变） |
| 渠道行为 | **不改代码**：`_accept_envelope` 已按 `result["run"]` 判空，`run=None` 时正常写 `channel_receipts`，更新 `channels.last_activity_at` 并清空 `last_error_code`；`send()` 不抛异常后入站事件自然标记 `processed`，`attempts==1`，不再有第二次 attempt，重试停止 |
| 影响面 | `send()` 异常契约变化；本阶段唯一需要改动调用方的地方。渠道 Reject 从“失败重试”变为“首次处理成功”，并产生上述正常成功副作用 |

### FR-5 决策查询

| 项 | 说明 |
|---|---|
| 列表 | 按会话倒序；`limit` 默认 50、上限 200；`before` 为 `base64("<created_at_iso>|<id>")` 不透明游标，服务端按 `(created_at, id)` 键集分页 |
| 聚合 | 按 `disposition` 与 `reason_code` 两个维度给出条数；响应含当前进程、当前 tenant 的 `routing_write_failures` |
| 时间范围 | `since` / `until` 为 ISO 8601；必须 `since < until`；跨度上限 31 天；未传默认最近 7 天 |
| 权限 | 复用现有租户与作用域隔离；跨租户不可达 |

### FR-6 开关与配置

| 配置项 | 归属 | 默认值 | 说明 |
|---|---|---|---|
| `trace_enabled` | **客服能力配置**（`customer_service/routing/settings.py`） | `false` | 关闭后不写决策记录；迁移与验证完成后在指定 canary 环境显式开启 |
| `handoff_rules` | **客服能力配置** | 四语言默认规则（含显式 id） | 人工请求规则 |

- **业务配置不进 Core Settings**：客服词表是业务规则，放进 `core_platform/.../settings.py` 会把业务词汇带进 Core。
- 注入点：`applications/platform_runtime/platform_services.py` 构造 `CustomerService` 处注入，不做模块级全局。
- 环境变量前缀 `AGENT_CS_ROUTING_`；租户级覆盖受现有机制限制（`CapabilityConfigService` 为平台级），本阶段**不承诺租户覆盖**。
- 灰度是环境/进程级，不是租户级：部署后先保持 `trace_enabled=false`，迁移和验证完成后再在指定 canary 环境设为 `true`，观察 7 天。
- **开关只控制记录**，不回退 FR-3 的规则扩展与 FR-4 的返回契约。

## 非功能需求

- **性能**：单条消息附加一次单行 INSERT（SAVEPOINT 内），P95 附加延迟 ≤ 5ms。
- **兼容**：**除 FR-3、FR-4 外**，其余路径在 HTTP 状态码与持久化副作用上与基线一致；规则扩展是有意的行为变更（`human` 由 `continue` 变为 `handoff`）。
- **多租户**：必含 `tenant_id` / `business_id` / `workspace_id`，读路径一律带作用域谓词。
- **隐私**：**不存原文、不存摘要**，只存 `message_length`（SHA-256 对短文本可字典还原，不构成脱敏）。
- **可观测**：本阶段靠决策表、进程内 `routing_write_failures` 计数和 WARN 日志，不发事件；计数不跨副本/进程聚合、重启清零，跨副本失败率测量依赖 WARN 日志聚合。

## 验收标准

| # | 场景 | 预期 |
|---|---|---|
| AC-1 | 对 `mode=closed` 会话发消息 | 接口返回 409 `conversation_closed`；`send()` 返回 `rejected`；**决策已落库** `reject / conversation_closed`；**未写入 `conversation_messages`**（与现状一致） |
| AC-2 | 发送 `转人工` | 请求人工接管、不建 Run；决策 `handoff / request_handoff / user_requested_human`，`matched_rule_id` 非空 |
| AC-3 | 发送 `human`（英文） | **有意的行为变更**：原先走 `continue`，现在转人工；决策 `handoff / user_requested_human` |
| AC-4 | 对 `mode=human` 会话发消息 | 消息入库、不建 Run；决策 `defer / human_mode_active` |
| AC-5 | 黑名单客户发消息且开关打开 | 请求人工接管、不建 Run；决策 `handoff / blacklist_flag` |
| AC-6 | 普通消息 | 正常提交 Run；决策 `continue / agent / submit_agent_run / default_agent` |
| AC-7 | 无 agent 且 `model_backend=unconfigured` | 接口返回 409 `model_not_configured`；**决策已落库** `reject / model_not_configured` |
| AC-8 | 关闭 `trace_enabled` 后重复 AC-1~AC-7 | 决策表零新增；HTTP 状态码与基线一致；**FR-3 规则扩展与 FR-4 返回契约不随开关回退** |
| AC-9 | 查询某会话决策 / 租户聚合 | 游标分页正确（同时间戳不漏不重）；聚合按 `disposition` 与 `reason_code` 正确；跨租户为空；`since/until` 校验生效 |
| AC-10 | 注入决策写入失败（触发器抛错） | 主流程仍成功（SAVEPOINT 回滚）；仅 WARN；不抛给调用方；当前 tenant 的 `routing_write_failures` 在 summary 中 +1，其他 tenant 不变；计数为进程内且重启清零 |
| AC-11 | 发送 `your agent platform is slow` / 裸 `agent` | 精确匹配且默认规则不含裸 `agent`，不判转人工；决策 `continue/default_agent` |
| AC-12 | 渠道入站收到两条 409 对应消息 | 入站事件标记 `processed`、`attempts==1`，不再有第二次 attempt、无重试；正常写 `channel_receipts`，更新 `channels.last_activity_at` 并清空 `last_error_code`（**验证即可，无代码改动**） |
