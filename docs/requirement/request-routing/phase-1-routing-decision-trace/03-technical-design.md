# Phase 1 · 路由决策可见 — 技术落地文档

> 写本文前已核查现状代码（`service.py` 判定分支、`store.py::transaction`、`channel/service.py` 调用路径、`events.py::_ensure_task`、`0041` 观测表惯例、`application.py` 挂载前缀）。
> 修订（2026-10-30）：初版。
> 修订（2026-10-30）：按技术评审重写——SAVEPOINT 隔离写入、Reject 与 model_not_configured 改为返回结果、删除未定型预留列、配置归业务能力。
> 修订（2026-10-30）：第二轮评审后修正——**本阶段不发布事件**、去掉 Reject 分支的 `add_message`、渠道改动降为"验证即可"、兼容性口径改为"仅 HTTP 边界与持久化副作用等价"。
> 修订（2026-10-30）：第三轮评审后修正——统一渠道 `attempts` 与默认 `max_attempts` 口径、规则改为 locale-agnostic 并集并校验 id/phrase 唯一性、补充进程内写入失败计数、明确 Reject 的渠道回执副作用、将开关默认值改为 false 并采用环境级 canary。

## Phase 1 的准确定义

本阶段**不是**"零行为变更的纯观测"。它是三件事的组合：

1. **决策可见**：把 `send()` 里的隐式 `if` 链变成可查询的 `routing_decisions` 记录
2. **人工请求规则扩展**：从硬编码中文两词扩展为可配置的四语言规则
3. **渠道无效重试修复**：`conversation_closed` / `model_not_configured` 两条永久性 409
   不再进入第二次 attempt。按 `channel_inbound_events.max_attempts` 默认 5 计算，基线是首次处理加最多 4 次重试、
   共最多 5 次 attempt 后标记 failed；改造后首次处理即 `processed`。

因此兼容性承诺是：**除 FR-3（规则扩展）与 FR-4（两条 409 改为返回结果）外，其余路径在 HTTP 边界与持久化副作用上与基线一致。**

## 改动总览

| 层 | 文件 | 改动 |
|---|---|---|
| 迁移 | `backend/migrations/versions/0053_routing_decisions.py` | 新建 `routing_decisions` 表、三个索引、三个 CHECK、一个唯一约束 |
| 新模块 | `backend/src/agent_platform/business_capabilities/customer_service/routing/__init__.py` | 包入口 |
| 新模块 | `backend/src/agent_platform/business_capabilities/customer_service/routing/decision.py` | `RoutingDecision` 数据类、常量、`decide_ingress()` 判定序列 |
| 新模块 | `backend/src/agent_platform/business_capabilities/customer_service/routing/rules.py` | 归一化与人工请求规则匹配 |
| 新模块 | `backend/src/agent_platform/business_capabilities/customer_service/routing/repository.py` | 决策写入（SAVEPOINT）与查询 |
| 新模块 | `backend/src/agent_platform/business_capabilities/customer_service/routing/settings.py` | `CustomerServiceRoutingSettings`（业务配置不进 Core） |
| 入口 | `backend/src/agent_platform/business_capabilities/customer_service/service.py` | `send()` 改为「先判定、再记录、再执行」；两条 409 改为返回 `rejected` |
| 接口 | `backend/src/agent_platform/applications/customer_service/platform_routes.py` | 两个只读端点；messages 端点把 `rejected` 映射为 409 |
| 装配 | `backend/src/agent_platform/applications/platform_runtime/platform_services.py` | 在构造 `CustomerService` 处注入路由配置（不做模块级全局） |
| 渠道 | `backend/src/agent_platform/business_capabilities/channel/service.py` | **不改代码**，只需验证：`send()` 返回 `rejected` 后正常写回执，入站事件首次处理即 `processed`、`attempts==1`，不再进入第二次 attempt |
| 事件 | — | **本阶段不发布事件**（无消费者；理由见「已知限制」） |
| 前端 | — | 无改动 |

**Core Platform 零改动**：不新增端口、不新增执行档位、不修改 `agent_runtime`，也不往 Core Settings 加任何业务配置。

## 数据模型

### 迁移 `0053_routing_decisions.py`

```sql
CREATE TABLE routing_decisions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       TEXT        NOT NULL,
    business_id     TEXT        NOT NULL,
    workspace_id    TEXT        NOT NULL,
    conversation_id UUID        NOT NULL,   -- 无外键：对齐 memory_injection_log / audit_records
    request_id      UUID        NOT NULL,   -- 每次 send() 一个，与入站尝试一一对应
    disposition     TEXT        NOT NULL,   -- reject | handoff | defer | continue
    execution_tier  TEXT        NULL,       -- agent（本阶段唯一取值）
    action          TEXT        NOT NULL,   -- 客服内部执行指令
    reason_code     TEXT        NOT NULL,   -- 解释「为什么」，不承担分派职责
    matched_rule_id TEXT        NULL,       -- 命中的规则 id
    decider         TEXT        NOT NULL,   -- cs_routing_v1
    message_length  INTEGER     NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT routing_decisions_request_unique
        UNIQUE (tenant_id, business_id, workspace_id, request_id),
    CONSTRAINT routing_decisions_tier_requires_continue
        CHECK (execution_tier IS NULL OR disposition = 'continue'),
    CONSTRAINT routing_decisions_tier_known
        CHECK (execution_tier IS NULL OR execution_tier = 'agent'),
    CONSTRAINT routing_decisions_length_non_negative
        CHECK (message_length >= 0)
);

CREATE INDEX routing_decisions_conversation
    ON routing_decisions(tenant_id, business_id, workspace_id, conversation_id, created_at DESC, id DESC);

CREATE INDEX routing_decisions_disposition
    ON routing_decisions(tenant_id, business_id, workspace_id, disposition, created_at DESC);

CREATE INDEX routing_decisions_reason
    ON routing_decisions(tenant_id, business_id, workspace_id, reason_code, created_at DESC);
```

`down_revision` 指向 `0052_memory_tasks_tenant_index`。

设计要点：

- **无外键。** 本仓观测/审计表不放外键：`memory_injection_log`（0041）只有裸 `run_id UUID NOT NULL` 并配 `retention_days`，`audit_records` 用 `resource TEXT`。放 `REFERENCES ... ON DELETE CASCADE` 会让删会话连带删审计数据。
- **CHECK 单向。** 只约束「有档位必须 `continue`」，不要求「`continue` 必须有档位」——否则未来`continue + 澄清`这类无档位组合会被封死。
- **刻意不约束 `disposition` / `action` 的取值集合。** 它们是业务层的开放集合，新增一种处置方式不应该需要改数据库约束；这两个约束由代码常量保证。`execution_tier` 例外：本阶段只有 `agent`，用 CHECK 挡住误写。
- **不设 `message_digest`。** SHA-256 不是脱敏：客服消息高度可枚举（「退款」「查订单」「转人工」），字典即可还原。只存 `message_length`。
- **不设预留列。** `task_relation` / `escalate_from` / `decision_type` / `stage_ids` / `confidence` / `profile_ref` 全部不建：语义未定型，提前建列等于用未验证的抽象绑架后续阶段。
- **保留策略**沿用观测表思路（参考 `memory_injection_log_retention_days`），清理任务不在本阶段实现。

## 核心流程

### 1. `send()` 改为「先判定、再记录、再执行」

```python
async with transaction(self.engine, connection) as c:
    await execute(c, "SELECT pg_advisory_xact_lock(71432019)")   # 锁序不变：受理锁在前
    conv = required(await one(c, "SELECT ... FOR UPDATE", ...))  # 会话锁在后
    request_id = uuid4()

    decision = await decide_ingress(c, self, conv, message, request_id)
    await self._record_decision(c, conv, decision)               # SAVEPOINT 隔离
    return await self._apply_decision(c, conv, decision, message)
```

`decide_ingress` 的判定序列：

| 序号 | 判定 | IO |
|---|---|---|
| 1 | `conv["mode"] == "closed"` → `reject/conversation_closed` | 无 |
| 2 | 人工请求规则命中 → `handoff/user_requested_human` | 无 |
| 3 | `mode in {"human","waiting"}` → `defer` | 无 |
| 4 | 黑名单旗标 → `handoff/blacklist_flag` | 取 `agent_snapshot` + `active_flags`（**位置与现状相同**，仍在前三步之后） |
| 5 | 无 agent 且 `model_backend == "unconfigured"` → `reject/model_not_configured` | 复用第 4 步已取的 snapshot，无额外查询 |
| 6 | 其余 → `continue/agent/submit_agent_run/default_agent` | 无 |

**关键约束**：现状中 `agent_snapshot` 只在通过前三个分支后才查（`service.py` 第 164-166 行）。改造后保持这个位置，否则会改变正常消息的查询次数与持锁时间。`model_not_configured` 从"提交 Run 时抛错"前移为判定序列的第 5 步，**不新增查询**。

### 2. `_apply_decision` 按 `action` 分派（不按 `reason_code` 分派）

```python
if decision.action == "reject":
    # 与现状一致：不写消息、不建 Run。当前 closed 分支就是直接抛异常，没有 add_message
    return {"conversation_id": cid, "run": None, "rejected": decision.reason_code}
if decision.action == "request_handoff":
    await add_message(c, cid, "user", message)
    handoff = await self.handoffs.request(...)
    return {"conversation_id": cid, "run": None, "handoff": handoff}
if decision.action == "defer":
    await add_message(...); await execute(... history 更新 ...)
    return {"conversation_id": cid, "run": None}
if decision.action == "submit_agent_run":
    return await self._submit_run(c, conv, decision, message)
raise DomainError("routing_action_unhandled", 500)
```

**Reject 分支的两个要点**：

1. **不写消息。** 现状 `service.py:129` 是直接 `raise DomainError`，不调用 `add_message`；若这里补一条 `add_message`，会让"关闭会话后的消息被入库"成为一个没人批准的新副作用（`add_message` 会插 `conversation_messages`，非 user 角色还会建分发）。
2. **不抛异常。** 抛出会让整个事务回滚，决策记录随之消失。改为返回 `{"rejected": reason_code}`，由调用方映射。

**两条 409 一并改造**（同一类缺陷：永久性拒绝 + 被渠道重试）：

| 原分支 | 改造后 |
|---|---|
| `service.py:129-130` `raise DomainError("conversation_closed", 409)` | 返回 `{"rejected": "conversation_closed"}` |
| `service.py:192-196` `raise DomainError("model_not_configured", 409)` | 判定序列第 5 步 + 返回 `{"rejected": "model_not_configured"}` |

调用方映射：`platform_routes.py` 的 messages 端点收到 `rejected` → `raise DomainError(reason, 409)`，对外状态码不变。

**渠道层不需要改代码**：`channel/service.py` 的 `_accept_envelope` 已按 `result["run"]` 判空，`run=None` 时正常写
`channel_receipts`，并更新 `channels.last_activity_at`、清空 `channels.last_error_code`。渠道 worker 在调用 `send()`
前已把本次 attempt 从 0 递增到 1（`channel/service.py:758-762`）；`send()` 不再抛异常后，入站事件随后会被标记
`processed`，`attempts==1`，不会再进入第二次 attempt。**本阶段只做验证，不引入分支。**

### 3. 决策写入（`routing/repository.py`）

```python
async def record(conn, decision) -> bool:
    try:
        async with conn.begin_nested():          # SAVEPOINT：失败只回滚这一小段
            await conn.execute(text(INSERT_SQL), {...})
        return True
    except Exception:                            # 观测失败不能反噬业务
        logger.warning("routing decision not recorded", exc_info=True)
        return False
```

- **失败计数由业务服务维护**：`CustomerService._record_decision()` 先判断 `trace_enabled`；关闭时直接跳过，
  不计数。开启时调用 `record()`，仅当返回 `False` 时对 `self._routing_write_failures[decision.tenant_id]`
  递增。计数器是
  **当前进程、当前 tenant** 的诊断值，不跨副本聚合，进程重启清零；WARN 日志保留，跨副本失败率由日志平台聚合测量。
- **为什么必须 SAVEPOINT**：PostgreSQL 语句出错后事务进入 aborted 状态，即使 Python 捕获异常，后续 SQL 仍报 `current transaction is aborted`，`_apply_decision` 的消息写入与 Run 创建会全部失败——恰好在要保护的场景里打死主流程。`begin_nested()` 在本仓已有先例（`conversation/service.py:346`）。
- **边界**：SAVEPOINT 只能隔离语句级错误。连接断开或事务已失效时回滚到保存点同样无效，由既有数据库错误处理决定整个请求失败——**不承诺"绝对不影响业务"**。
- **没有事件**：`record()` 只写表，不发布任何事件（见「已知限制」）。

### 4. 查询接口（`applications/customer_service/platform_routes.py`）

客服业务路由实际在 `platform_routes.py`（已定义 `/conversations/{cid}`、`/conversations/{cid}/messages`、`/handoffs`），经 `applications/customer_service/application.py` 以 `prefix=api_prefix`（`/api/v1`）挂载；`routes.py` 只有 `/health`、`/modules`、`/deployment`。

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/v1/conversations/{cid}/routing-decisions` | `limit`（默认 50、上限 200）+ `before` 游标 |
| `GET` | `/api/v1/routing-decisions/summary?since=&until=` | 按 `disposition` / `reason_code` 聚合条数，并返回当前进程/当前 tenant 的 `routing_write_failures` |

- **游标格式**：`before` 是 `base64("<created_at_iso>|<id>")` 的不透明串，服务端解码后按 `(created_at, id) < (before_at, before_id)` 做键集分页。必须用复合游标，否则同时间戳会漏行。
- `summary` 校验：ISO 8601；`since < until`；跨度上限 31 天；未传默认最近 7 天。
- `summary.routing_write_failures` 是进程内计数：只代表处理该请求的副本在本次进程生命周期内累计的
  SAVEPOINT 写入失败数，不跨副本聚合、重启清零；响应必须保留该边界，不能把它当成全局失败总数。
- 两个端点都带完整作用域谓词，权限沿用现有 `Operator` / `Reader` 依赖。

### 5. 索引验证

三个索引按查询形状设计，落地后必须用真实 SQL 跑 `EXPLAIN (ANALYZE, BUFFERS)` 验证，重点看 `summary` 在 `since/until` 范围过滤 + 聚合下是否仍走索引（范围 + 聚合可能需要 `(tenant,business,workspace,created_at,disposition)` 顺序）。按验证结果调整后再定稿迁移。

## 配置

新建 `business_capabilities/customer_service/routing/settings.py`（业务配置不进 Core Settings）：

```python
class RoutingRule(BaseModel):
    id: str                                   # 稳定 id，如 en_human_request_001
    locale: str                               # zh-CN / zh-TW / en / hi
    phrases: list[str]

class CustomerServiceRoutingSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGENT_CS_ROUTING_", extra="ignore")

    trace_enabled: bool = False
    handoff_rules: list[RoutingRule] = [
        RoutingRule(id="zh_human_request_001", locale="zh-CN", phrases=["转人工", "人工客服", "客服"]),
        RoutingRule(id="zhtw_human_request_001", locale="zh-TW", phrases=["轉人工"]),
        RoutingRule(id="en_human_request_001", locale="en", phrases=["human", "real person", "representative", "human agent"]),
        RoutingRule(id="hi_human_request_001", locale="hi", phrases=["मानव", "एजेंट"]),
    ]

    @model_validator(mode="after")
    def validate_rule_identity(self):
        # id 全局唯一；归一化后的 phrase 全局唯一。重复配置必须拒绝。
        ...
        return self
```

- **规则带显式 id**：不能用"语言 + 列表下标"生成 `matched_rule_id`，否则调整词表顺序会让历史记录指向错误规则。
- **规则身份稳定**：`RoutingRule.id` 与归一化后的 phrase 是 Phase 1/2 共同遵守的稳定契约；调换规则或短语顺序
  不得改变同一短语的 `matched_rule_id`。新增语义必须使用新 id 或显式迁移，不得复用旧 id 指向不同规则。
- **全局唯一性校验**：Pydantic model validator（或等价校验）必须拒绝重复 `id`、以及归一化后重复的 phrase。
  例如两条规则同时配置 `" HUMAN "` 与 `"human"` 属于非法配置。
- **locale 不参与匹配**：`locale` 只是规则来源/运营元数据。本阶段对所有规则做 locale-agnostic 并集匹配，
  不按渠道语言筛选，也不把 locale 拼进 `matched_rule_id`。
- **注入点**：在 `applications/platform_runtime/platform_services.py` 构造 `CustomerService` 的位置注入实例，不做模块级全局变量。
- 环境变量：`AGENT_CS_ROUTING_TRACE_ENABLED`、`AGENT_CS_ROUTING_HANDOFF_RULES`（JSON）。
- **失败回退**：配置解析失败或 validator 校验失败时，回退默认规则并记 WARN；不得因配置错误把正常消息判成转人工。
- **默认关闭**：`trace_enabled` 默认 `false`。部署后先在指定 canary 环境显式设为 `true`，观察 7 天；
  这是环境/进程级灰度，不是租户级覆盖。开关只控制记录，不回退 FR-3/FR-4 的行为变更。
- **已知限制**：现有 `CapabilityConfigService` 是平台级（进程共享，无租户覆盖），因此本阶段**不承诺租户级覆盖**，只提供环境变量级配置。

## 规则语义（明确边界，不过度宣称）

本阶段是**可配置的确定性关键词规则**，不是多语言转人工意图识别：

1. **归一化**：去首尾空白、大小写折叠、全角转半角。
2. **匹配方式**：整个消息与规则短语**相等**（精确匹配），**禁止任意子串包含**——否则 `your agent platform is slow` 会被误判。
3. **标点**：剥离句末单个标点后再比较（`human.` 命中 `human`）。
4. **locale-agnostic 并集**：匹配时遍历全部规则，`locale` 不参与筛选；`客服`、`轉人工`、`human`、`मानव`
   在不同渠道语言下都按同一并集匹配。
5. **命中可追溯**：写 `matched_rule_id`，调词表不必翻日志。
6. **规则身份稳定**：显式 id 与归一化 phrase 全局唯一，调换规则或短语顺序不能改变已有短语的 `matched_rule_id`。
7. **已知召回缺口**：`I want to speak to a human` 这类句内表达不命中。**有意取舍**（精确匹配优先不误判），补召回属 Phase 2 规则升级，本阶段不做 NLP 分类器。
8. **裸 `agent` 明确不支持**：默认只用 `human agent`，避免 `your agent platform is slow` 一类误触；
   其他近义表达不在默认词表中，需要人工转接时统一使用 `real person`。

## 已知限制与后续项

| # | 内容 | 处置 |
|---|---|---|
| L1 | **本阶段不发布事件。** `routing.decision_created` 目前无消费者；发它需要回填决策 id、区分两条调用路径的真实提交点（渠道传外部连接时 `transaction()` 不提交），并会放大下面 L2 的问题 | 等有消费者且明确投递语义再加；届时评估 Outbox |
| L2 | **事件总线 scope 取值有既有缺陷**：`events.py::_ensure_task` 从包装 dict 取 `payload.get("business_id")`，而该字段实际在 `event.payload` 内部，因此落到默认 `customer-service/default` | 与本阶段无关的既有问题；登记待修，不阻塞 |
| L3 | **决策覆盖率不是无条件 100%**：SAVEPOINT 失败时请求成功但无记录；判定后执行阶段若还有其他抛错路径也会随事务回滚 | 指标改为"数据库健康时 100%"；WARN 保留，并在 `routing_summary.routing_write_failures` 暴露当前进程/当前 tenant 的失败计数。该计数不跨副本聚合、重启清零，跨副本失败率由日志平台聚合测量 |
| L4 | 保留/清理任务未实现 | 参考 `memory_injection_log_retention_days` 后续补 |

## 模型调用路径

本阶段**不涉及模型**：判定全部为确定性规则，不调用 `model_gateway`，不产生 token 消耗。

## 测试方案

| 层 | 用例 |
|---|---|
| 单测 | 判定序列与现状分支一一映射；归一化与精确匹配边界（句末标点、全角、大小写）；zh-CN / zh-TW / en / hi 默认规则；locale-agnostic 并集；裸 `agent` 与非默认近义表达不命中；规则 id/phrase 稳定；重复 id、重复归一化 phrase 被 validator 拒绝；配置失败回退默认规则；开关关闭不写入 |
| 集成 | 六个分支行为与决策记录一致；**两条 409 均返回 `rejected` 且决策已落库**；SAVEPOINT 失败后主流程仍成功且 summary 失败计数递增；外层回滚时决策一并回滚；查询游标分页与聚合；租户隔离 |
| 渠道 | 两条 409 对应入站首次处理即 `processed`、`attempts==1`、无第二次 attempt；`channel_receipts` 有回执，`channels.last_activity_at` 更新，`last_error_code` 为空（验证即可，渠道代码不改） |
| 回归 | 既有客服与运行时套件全绿；两条 409 的 HTTP 状态码不变；人工接管与渠道入站既有用例不回归 |

## 上线与回滚

- **迁移**：仅新建表与索引，在线执行；存量数据无需回填。
- **默认关闭**：`trace_enabled` 默认 `false`，`AGENT_CS_ROUTING_TRACE_ENABLED=false` 时不写决策。
  **注意**：规则扩展与两条 409 的返回契约**不随开关回退**（它们是有意的行为变更）。
- **回滚**：如需回到完全旧行为，需回滚代码；迁移 `downgrade` 仅 `DROP TABLE routing_decisions`。
- **灰度**：完成迁移与验证后，在指定 canary 环境/进程显式设置 `AGENT_CS_ROUTING_TRACE_ENABLED=true`，
  观察 7 天，用 `summary` 确认 `disposition` / `reason_code` 分布符合预期，再逐步扩大范围并决定 Phase 2 是否启动。
  本阶段没有租户级开关，不能把 canary 描述成按租户灰度。
