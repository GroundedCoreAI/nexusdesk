# Phase 1 · 路由决策可见 — 实施拆解方案

> 状态：已裁定（技术负责人拆解，dev/qa 以此为执行基线）
> 创建：2026-10-30
> 依据：`01`~`05` 全部文档 + 现状代码核查（backend @ `feat/phase-1-routing-decisions`）
> 约束：只做 Phase 1；不过度设计；不发布 `routing.decision_created`；不建 Outbox；不改 Core Platform；不改渠道业务分支。

## 0. 现状核查

本轮核查不执行 git，只读工作区文件和代码。

| 现状 | 结论 |
|---|---|
| `backend/migrations/versions/0053_routing_decisions.py` 已存在 | 表、约束和三个索引已有初稿，需按 T1 做最终核对 |
| `backend/tests/test_routing_decisions_migration.py` 已存在 | 已覆盖迁移 SQL 和 PostgreSQL 可逆性，纳入 T9 回归 |
| `backend/src/agent_platform/business_capabilities/customer_service/service.py` 已有路由接线初稿 | 已出现 `decide_ingress` 调用、`_record_decision()`、Reject 返回和 per-tenant Counter；需按 T4 补齐/核对 |
| `backend/src/agent_platform/applications/customer_service/platform_routes.py` 已有查询端点和 Reject 映射初稿 | 需按 T5 核对行为与响应契约 |
| `backend/src/agent_platform/applications/platform_runtime/platform_services.py` 已有配置注入初稿 | 需按 T5 核对实例注入，不允许退回模块级隐藏全局 |
| `backend/src/agent_platform/business_capabilities/customer_service/routing/` 已包含 `__init__.py`、`decision.py`、`rules.py`、`settings.py`、`repository.py` 实现 | `settings.py` 已按 R5 将 `trace_enabled` 默认值与 `_default_settings()` 回退值设为 `False`；T2/T3 仍需做最终核对 |
| `backend/tests/test_routing_*.py` 已有规则、判定、API、PG、repository 和迁移测试初稿 | 由 T6~T9 按 04 用例编号补齐、整合和回归 |

因此，本文件按“补齐未完成实现 + 核验已落地初稿”组织，不把当前分支当作全新开工。

## 1. 任务拆解（按依赖顺序）

依赖主线：**T1/T2 并行 → T3 → T4 → T5 → T6/T7/T8 → T9**。

并行边界：

- T1 迁移与 T2 纯规则/配置模块互不阻塞，可并行。
- T6 单元测试可在 T2 完成后先写规则与 validator 部分，涉及 `CustomerService` 的用例需等 T4。
- T7 依赖真实 PostgreSQL 和可用的 T1/T3/T4/T5；T8 只做渠道验证，依赖 T4/T5，不等待 T7 全绿。
- T9 是收口任务，必须等待 T1~T8 完成。

| # | 任务 | 文件（新建/修改） | 依赖 | 溯源 |
|---|---|---|---|---|
| T1 | 迁移核对：确认 `routing_decisions` 字段、作用域唯一键、档位/长度约束、会话/处置/原因索引和 `down_revision=0052_memory_tasks_tenant_index`；不增加预留列 | `backend/migrations/versions/0053_routing_decisions.py`（核对；必要时修改） | — | FR-1、FR-2、FR-5；AC-1、AC-6、AC-7、AC-9；04 P1-CM-01 |
| T2 | 补齐 routing 包：显式规则 id 的配置模型、归一化与 locale-agnostic 并集匹配、重复 id/归一化 phrase validator、`decide_ingress()` 判定序列；配置留在客服能力内，并把 `trace_enabled` 默认值修正为 `False` | `backend/src/agent_platform/business_capabilities/customer_service/routing/__init__.py`（新/核对）、`settings.py`（新/修改）、`rules.py`（新/核对）、`decision.py`（新/核对） | — | FR-2、FR-3、FR-6；AC-2、AC-3、AC-8、AC-11；04 P1-UT-02~07、P1-UT-10~17 |
| T3 | 补齐 repository：SAVEPOINT 隔离的单行写入、按 `(created_at,id)` 键集查询、按处置/原因聚合；写入失败返回明确失败结果，不吞掉连接级错误；不发事件 | `backend/src/agent_platform/business_capabilities/customer_service/routing/repository.py`（新/核对） | T1、T2 | FR-1、FR-5；AC-9、AC-10；04 P1-IT-08~11、P1-IT-16 |
| T4 | 补齐 `CustomerService.send()`：先判定、再记录、再按 `action` 执行；Reject 不写消息；两条 409 返回 `rejected`；进程内 per-tenant failure Counter 只在已开启记录且写入失败时加一 | `backend/src/agent_platform/business_capabilities/customer_service/service.py`（修改/核对） | T2、T3 | FR-1~FR-4、FR-6；AC-1~AC-8、AC-10、AC-11；04 P1-UT-01、P1-UT-04~09、P1-IT-01~09、P1-IT-12~14 |
| T5 | 装配与接口：在 `platform_services.py` 构造并注入 routing settings；补齐两个只读端点、Reject→409 映射、游标/时间窗校验，以及 summary 的 `routing_write_failures` 字段 | `backend/src/agent_platform/applications/platform_runtime/platform_services.py`（修改/核对）、`backend/src/agent_platform/applications/customer_service/platform_routes.py`（修改/核对） | T3、T4 | FR-4、FR-5、FR-6；AC-1、AC-7、AC-9、AC-10；04 P1-IT-10、P1-IT-11、P1-IT-16、P1-CM-02 |
| T6 | 单元测试：四语言规则、归一化、精确匹配反例、locale-agnostic 并集、重复 id/归一化 phrase 拒绝、规则 id 稳定性、判定映射、开关关闭、per-tenant failure Counter | `backend/tests/test_routing_decisions_unit.py`（新） | T2、T4 | FR-2、FR-3、FR-6；AC-2、AC-3、AC-8、AC-10、AC-11；04 P1-UT-01~17 |
| T7 | PostgreSQL 集成测试：六类判定落库、两条 409 持久化、Reject 无消息、SAVEPOINT 失败隔离、外层回滚、游标分页、聚合、租户隔离、summary failure 字段 | `backend/tests/test_routing_decisions_postgres.py`（新/扩展） | T1、T3、T4、T5 | FR-1~FR-5；AC-1~AC-11；04 P1-IT-01~14、P1-IT-16 |
| T8 | 渠道端到端验证：**不改 channel 业务分支**；两条 409 对应入站首次处理即 `processed`、`attempts=1`、无第二次 attempt；断言 `channel_receipts`、`channels.last_activity_at`、`channels.last_error_code` | `backend/tests/test_routing_channel_postgres.py`（新/扩展） | T4、T5 | FR-4；AC-12；04 P1-IT-15 |
| T9 | 收口回归：迁移 up/down、真实查询 `EXPLAIN (ANALYZE, BUFFERS)`、相关客服/运行时/渠道套件、架构门禁、配置默认值和中英文档交叉检查 | `backend/tests/test_routing_decisions_migration.py`（修改/核对）、相关既有测试文件；不新增生产代码 | T1~T8 | 04 §5~§7；P1-CM-01~05 |

测试文件路径是执行建议；若仓库既有测试组织更合适，允许在不改变覆盖内容和不触碰生产代码的前提下调整文件归属。

## 2. 文档与现实不一致清单及裁定

### R1 渠道 attempts：首次处理就会从 0 增到 1，重试上限不是“三次”

文档旧口径把两条 409 描述为固定三次重试后失败，并要求修复后 attempts 保持不变。

代码现实：

- `backend/migrations/versions/0032_channel_inbound_outbox.py:28-29`：`attempts` 默认 0，`max_attempts` 默认 5。
- `backend/src/agent_platform/business_capabilities/channel/service.py:758-765`：worker 在调用 `send()` 前执行 `attempts=attempts+1`。
- `backend/src/agent_platform/business_capabilities/channel/service.py:791-796`：本次执行后按 `attempts` 决定 `processed` / `pending` / `failed`。

**裁定**：

- `attempts` 是“总执行次数”，首次处理前从 0 增到 1。
- 默认 `max_attempts=5` 表示首次 + 最多 4 次重试，共 5 次 attempt；原基线不是固定三次。
- 改造后永久性 409 正常返回，首次执行即为 `status=processed`、`attempts=1`，不再产生第二次 attempt。
- 所有文档和测试统一写成：首次处理 `attempts==1`、`status=processed`、`pending` 不新增；禁止再描述为 attempts 保持不变。

回填：`01-business-goals.md` 的成功指标/风险，`02-requirements.md` 的 FR-4/AC-12，`03-technical-design.md` 的渠道流程，`04-test-plan.md` 的 P1-IT-15，`05-acceptance-plan.md` 的 A12 与业务指标。

### R2 人工请求规则：locale-agnostic 并集，规则 id 与归一化 phrase 都是稳定契约

文档旧口径曾写“按渠道语言分组”，并让 `人工客服` 同时出现在 zh-CN 和 zh-TW 两个规则中。

代码现实：

- `backend/src/agent_platform/business_capabilities/customer_service/service.py:125-144`：`send()` 没有 locale 参数。
- `backend/src/agent_platform/business_capabilities/customer_service/service.py:151-159`：`decide_ingress()` 调用未传渠道语言。
- 当前工作区缺少 `customer_service/routing/` 包，规则 validator 尚未落地。

**裁定**：

- Phase 1 对所有规则做 **locale-agnostic 并集匹配**；`locale` 只作元数据，不参与命中过滤。
- 规则 id 显式配置，不能由“locale + 下标”生成。Phase 1 与后续 Phase 2 都以规则 id 和归一化 phrase 为稳定契约；不得复用 id 表达新语义。
- 归一化后的 phrase（trim、case-fold、全角转半角、剥离单个句末标点）必须**全局唯一**。
- 设置模型必须拒绝重复的规则 id 和重复的归一化 phrase；配置解析/校验失败回退默认规则并记 WARN。
- 默认规则精确为：

| 规则 id | locale | phrases |
|---|---|---|
| `zh_human_request_001` | `zh-CN` | `转人工`、`人工客服`、`客服` |
| `zhtw_human_request_001` | `zh-TW` | `轉人工` |
| `en_human_request_001` | `en` | `human`、`real person`、`representative`、`human agent` |
| `hi_human_request_001` | `hi` | `मानव`、`एजेंट` |

- 裸 `agent` 不支持；英文人员表达统一使用 `real person`，不要使用旧的两词变体。
- 调换规则或短语顺序不得改变同一短语的 `matched_rule_id`。

回填：`01-business-goals.md` 的问题/范围/风险，`02-requirements.md` 的 US-2、FR-3、AC-11，`03-technical-design.md` 的配置与规则语义，`04-test-plan.md` 的 P1-UT-02~17，`05-acceptance-plan.md` 的 UAT/验收步骤。

### R3 决策写入失败计数：进程内、按 tenant、通过 summary 暴露

文档旧口径只写“仅 WARN”“失败可计数”，没有说明计数落在哪里。

代码现实：

- `backend/src/agent_platform/business_capabilities/customer_service/service.py:96`：`CustomerService` 持有 `_routing_write_failures: Counter[str]`。
- `backend/src/agent_platform/business_capabilities/customer_service/service.py:173-179`：只有开启记录且 `record()` 返回失败时，才按 `decision.tenant_id` 累加。
- `backend/src/agent_platform/business_capabilities/customer_service/service.py:328-332`：routing summary 返回 `routing_write_failures`。

**裁定**：

- 计数器归 `CustomerService` 实例所有，按 `tenant_id` 维护，属于**进程内诊断状态**。
- 它不是持久化指标，不做跨副本聚合，进程重启后清零；WARN 日志继续保留，用于跨副本告警和日志聚合。
- `GET /routing-decisions/summary` 返回当前进程、当前租户的 `routing_write_failures`，不承诺等于全局失败总数。
- 失败率生产指标以日志/监控聚合为准；summary 字段用于单进程排障和验收复现。
- `trace_enabled=false` 导致的跳过不计为失败。

回填：`01-business-goals.md` 的成功指标/风险，`02-requirements.md` 的 FR-1/AC-10/非功能需求，`03-technical-design.md` 的写入与查询接口，`04-test-plan.md` 的 P1-IT-08/P1-IT-11，`05-acceptance-plan.md` 的 A10/业务指标。

### R4 渠道 Reject 新副作用：正常成功路径会写 receipt 并刷新渠道状态

文档旧口径只说明入站事件会变成 `processed`，没有列出成功返回带来的其他持久化副作用。

代码现实：

- `backend/src/agent_platform/business_capabilities/channel/service.py:661-672`：调用 `customer.send()`，`result["run"]` 为空按正常结果处理。
- `backend/src/agent_platform/business_capabilities/channel/service.py:673-689`：插 `channel_receipts`，并执行 `UPDATE channels SET last_activity_at=now(),last_error_code=NULL`。
- `backend/src/agent_platform/business_capabilities/channel/service.py:791-816`：无异常时入站事件置 `processed`、写 `processed_at`。

**裁定**：

- `conversation_closed` / `model_not_configured` 改为返回 `rejected` 后，渠道路径按正常成功处理：
  - `channel_inbound_events.status='processed'`
  - `channel_inbound_events.attempts=1`
  - `channel_receipts` 新增一行
  - `channels.last_activity_at` 刷新
  - `channels.last_error_code` 清空
- 不产生第二次 attempt，不进入 `pending`，不因永久性 409 重试。
- 这些是 FR-4 的预期副作用，不能被测试误判为回归。

回填：`02-requirements.md` 的 FR-4/AC-12，`03-technical-design.md` 的渠道行为，`04-test-plan.md` 的 P1-IT-15，`05-acceptance-plan.md` 的 A12。

### R5 默认开关与灰度：默认关闭，指定 canary 环境显式开启

文档旧口径同时写记录开关默认开启和“先打开开关观察 7 天”，二者矛盾。

代码现实：

- `backend/src/agent_platform/business_capabilities/customer_service/routing/settings.py:83` 的
  `trace_enabled` 默认值与 `_default_settings()` 回退值均已按本裁定设为 `False`；回归测试需显式开启后
  才能验证写入。
- `docs/requirement/request-routing/phase-1-routing-decision-trace/03-technical-design.md:210` 的旧版本示例曾把 `trace_enabled` 写成默认开启；本轮已回填，当前示例为 `False`。

**裁定**：

- `trace_enabled` 默认值为 **`false`**。
- 部署顺序：迁移 → 部署默认关闭版本 → 冒烟验证 → 在指定 canary 环境设置 `AGENT_CS_ROUTING_TRACE_ENABLED=true` → 观察 7 天 → 再扩大范围。
- 开关是部署/进程级环境配置，不是租户级配置，也不做运行时动态切换。
- 开关只控制决策记录，不回退 FR-3 的规则扩展和 FR-4 的返回契约。
- 扩大范围前必须检查决策写入失败计数、WARN 日志和 summary 分布。

回填：`02-requirements.md` 的 FR-6，`03-technical-design.md` 的配置/上线与回滚，`04-test-plan.md` 的 P1-CM-02，`05-acceptance-plan.md` 的 A8/业务指标。

### R6 示例与测试：统一 canonical 词表，补足 zh-TW、hi 和 validator 用例

文档旧口径混用多套英文人员表达、裸 `agent` 和繁体 `客服`，且四语言覆盖不完整。

代码现实：

- 匹配必须严格相等；当前没有 locale 输入，不能用语言分组解释短语。
- 当前工作区缺少规则模块和对应单测，测试尚未兑现。

**裁定**：

- canonical 示例统一为：`human`、`real person`、`representative`、`human agent`、`转人工`、`人工客服`、`客服`、`轉人工`、`मानव`、`एजेंट`。
- 裸 `agent`、`your agent platform is slow`、`human being` 必须是不命中反例。
- 明确增加 zh-TW `轉人工` → `zhtw_human_request_001`、hi `मानव`/`एजेंट` → `hi_human_request_001` 的测试。
- 明确增加重复规则 id、以及归一化后重复 phrase 被 validator 拒绝的测试。
- 增加 locale-agnostic 用例：同一 `客服` 不依赖渠道 locale，始终命中 `zh_human_request_001`。

回填：`01-business-goals.md` 示例，`02-requirements.md` 的 FR-3/AC-11，`03-technical-design.md` 的规则语义，`04-test-plan.md` 的 P1-UT-02~17，`05-acceptance-plan.md` 的 UAT。

### R7 范围裁定：不发事件、不建 Outbox、渠道不改业务分支、Core 零业务语义

文档旧口径已提出延后事件，但需要在实施基线中再次锁定，避免实现时扩散。

代码现实：

- `backend/src/agent_platform/business_capabilities/customer_service/service.py:151-170`：当前路由链路只有 `decide_ingress()`、记录和执行，没有 `routing.decision_created` 发布。
- 渠道路径可在 `backend/src/agent_platform/business_capabilities/channel/service.py:661-689` 以现有正常结果处理 Reject，不需要新增专用分支。
- Core Platform 不新增业务配置或规则词表。

**裁定**：

- 本阶段不发布 `routing.decision_created`，不创建 Outbox，不新增消息可靠性基础设施。
- `channel/service.py` 不加 Reject 专用分支；仅通过测试验证现有成功路径。
- 不修改 `core_platform`，不把客服词表、开关或判定规则放进 Core Settings。
- 后续若引入事件，必须单独评审真实提交点、决策 id 回填和事件总线 scope 问题。

回填：`03-technical-design.md` 的已知限制/渠道/上线，`04-test-plan.md` 的 P1-IT-15/P1-CM-03/P1-CM-05，`05-acceptance-plan.md` 的合规核对。

## 3. 执行顺序、交接与红线

### 3.1 执行顺序

1. **T1 + T2 并行**：先冻结迁移契约和纯规则/配置契约。T2 必须先让 routing 包可 import。
2. **T3**：实现 SAVEPOINT 写入、查询和聚合；不得引入事件发布。
3. **T4**：接入 `send()`，完成 Reject 返回、per-tenant failure Counter 和原有锁序。
4. **T5**：完成依赖注入、查询端点、Reject→409 和 summary failure 字段。
5. **T6 / T7 / T8**：规则单测、PostgreSQL 集成测试、渠道端到端验证可并行推进；渠道测试不等待查询性能用例。
6. **T9**：跑迁移可逆性、EXPLAIN、相关回归和架构门禁，形成 `06-test-report.md` 的输入。

### 3.2 给 dev 的交接

- 以 `02` 的 FR/AC 和 `03` 的判定序列为唯一行为契约；发现冲突先登记 R 编号，不擅自扩大范围。
- 规则默认开关为 `false`；测试要显式开启后才能验证写入。
- `record()` 失败只能回滚到 SAVEPOINT，不得让决策写入失败反噬消息处理或 Run 创建。
- Reject 分支不写 `conversation_messages`；两条 409 在 HTTP 边界仍返回 409。
- 不新增 `routing.decision_created`、Outbox、Core 配置或渠道专用业务分支。
- 保持“受理咨询锁 → 会话行锁 → 决策写入”的原锁序。
- 查询端点必须带 tenant/business/workspace 谓词；summary 的失败计数必须明确是当前进程和当前租户。

### 3.3 给 QA 的交接

- 按 `04-test-plan.md` 逐条执行 P1-UT-01~17、P1-IT-01~16、P1-CM-01~05。
- 渠道用例必须逐条断言 `status=processed`、`attempts=1`、receipt 新增、`last_activity_at` 刷新、`last_error_code=NULL`。
- 失败计数用例必须验证：主流程成功、WARN 存在、同租户 summary 计数增加、其他租户不增加、重启/新实例计数清零。
- 四语言规则必须覆盖 zh-CN、zh-TW、en、hi；重复归一化 phrase 和裸 `agent` 必须有反例。
- 迁移/查询用例必须执行 `EXPLAIN (ANALYZE, BUFFERS)`，并验证游标在相同时间戳下不漏不重。
- 无事件、无 Outbox、Core 零业务词表作为通用核对项，不能只看功能测试。

### 3.4 红线

- 跨租户读取或写入、决策记录泄露消息原文/摘要：立即阻断。
- Reject 写入 `conversation_messages`，或关闭会话消息被错误持久化：立即阻断。
- 决策写入失败导致消息处理或 Run 创建失败：立即阻断。
- 渠道永久性 409 仍进入重试、`attempts` 大于 1 或 status 不是 `processed`：立即阻断。
- 规则匹配依赖 locale、重复 phrase 被静默接受、裸 `agent` 被误判：阻断对应测试通过。
- 向 Core Platform 引入业务词表/业务配置，或发布未批准事件：阻断合入。

### 3.5 交付边界

本文件只定义 Phase 1 的实施与验证基线；不实现代码、不修改 `01`~`05`、不执行 git、不提交。实现完成后由测试报告和验收报告记录真实结果。
