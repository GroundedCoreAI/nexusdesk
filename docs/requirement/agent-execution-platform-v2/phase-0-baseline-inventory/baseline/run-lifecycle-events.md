# Phase 0 基线 · Run 生命周期、事件与 SSE

> 基线提交：`c6c47dec39025ebd4d1176c1e9925bac9c99c4fd`
> 盘点日期：2026-11-07；复核修订：2026-11-08
> 结论来源：目标提交静态路径；可重复动态断言以 `06-test-report.md` 的实际节点为准

## 1. 状态与所有权

持久状态只有 `queued`、`running`、`completed`、`failed`、`cancelled`，由核心 schema 与数据库约束共同限制（`backend/src/agent_platform/core_platform/agent_runtime/schemas.py:7-8`、`backend/migrations/versions/0001_runtime.py:23-44`）。

- `queued`：尚无执行 owner；`queue_expires_at` 决定能否被 claim（`backend/src/agent_platform/core_platform/agent_runtime/repository.py:55-149,203-251`）。
- 成功 claim 创建 `running` 并设置 owner/lease；**持续有效的 owner/lease 是 heartbeat、普通 append/finish 的写入条件，不是存储状态必须时刻满足的不变量**。lease 可已过期而状态仍为 running，直到 Worker/reaper 处理（`backend/src/agent_platform/core_platform/agent_runtime/repository.py:203-281,297-317,368-391`）。
- 终态设置 `finished_at`，普通完成清理 lease；普通迟到 finish 不得覆盖终态（`backend/src/agent_platform/core_platform/agent_runtime/repository.py:283-325`）。
- `cancel_requested` 是标志位，不是第六种状态。running Run 在请求取消后仍可短暂保持 running，直到 Worker/Repository 协同进入 cancelled（`backend/src/agent_platform/core_platform/agent_runtime/repository.py:327-366`）。

## 2. 可达转换

| 起点/触发 | 实际结果与字段 | 证据 |
|---|---|---|
| 新提交 | 原子写入 queued、用户消息和 `run.queued`；设置 queue deadline | `backend/src/agent_platform/core_platform/agent_runtime/repository.py:55-149` |
| queued + 成功 claim | running；设置 owner/started_at/lease_until，写 `run.started`；同租户、未过期、`FOR UPDATE SKIP LOCKED` | `backend/src/agent_platform/core_platform/agent_runtime/repository.py:203-251` |
| running + Engine 正常返回 | completed；写 output/history，error 为 null，清 lease；成功 hooks 与 `run.completed` 同事务 | `backend/src/agent_platform/core_platform/agent_runtime/worker.py:91-99`、`backend/src/agent_platform/core_platform/agent_runtime/repository.py:283-325` |
| running + `RuntimeFault` | failed，`error_code=exc.code` | `backend/src/agent_platform/core_platform/agent_runtime/worker.py:109-110` |
| running + 外层执行超时 | failed/`run_timeout`；单次模型超时另为 `model_timeout` | `backend/src/agent_platform/core_platform/agent_runtime/worker.py:111-112`、`backend/src/agent_platform/core_platform/agent_runtime/engine.py:57-65,183-196` |
| running + 普通异常 | failed/`execution_error`；日志只带 Run ID，不带 Provider 异常原文 | `backend/src/agent_platform/core_platform/agent_runtime/worker.py:113-116` |
| queued + cancel | cancel flag=true，立即 cancelled/finished_at，`run.cancelled` 为 `{}` | `backend/src/agent_platform/core_platform/agent_runtime/repository.py:327-366` |
| running + cancel | 先写 cancel flag 与 `run.cancel_requested`，状态仍 running；后续 finish 强制 cancelled，清 output/error，跳过成功 hooks | `backend/src/agent_platform/core_platform/agent_runtime/repository.py:309-325,352-365` |
| 执行中观察到取消 | heartbeat 返回 cancel，monitor 取消 execution；`CancelledError` 路径尝试 cancelled | `backend/src/agent_platform/core_platform/agent_runtime/repository.py:272-281`、`backend/src/agent_platform/core_platform/agent_runtime/worker.py:56-69,100-108` |
| Worker 停止 | serve 取消执行；若 owner/lease 仍有效，同一 `CancelledError` 路径可写 cancelled，即使无 API cancel flag | `backend/src/agent_platform/core_platform/agent_runtime/worker.py:100-108,186-192` |
| heartbeat 失租/数据库失败 | monitor fail closed，取消 execution 并尝试 failed/`worker_lost`；finish 自身拒绝过期/错误 owner | `backend/src/agent_platform/core_platform/agent_runtime/worker.py:56-69,100-108`、`backend/src/agent_platform/core_platform/agent_runtime/repository.py:297-317` |
| 过期 running lease + reaper | 通常 failed/`worker_lost`；若已请求取消，则 cancelled 且保留 `error_code=worker_lost` | `backend/src/agent_platform/core_platform/agent_runtime/repository.py:368-391` |
| 过期 queued deadline + reaper | 通常 failed/`queue_timeout`；若已有取消标志，则 cancelled 且保留 `error_code=queue_timeout` | `backend/src/agent_platform/core_platform/agent_runtime/repository.py:368-391` |
| 人工接管 | queued 直接 cancelled，reason=`human_handoff`；running 写取消标志和带 reason 的 cancel_requested | `backend/src/agent_platform/business_capabilities/human_handoff/service.py:125-153` |
| 任意终态 + cancel | 不更新、不新增事件，返回当前终态 | `backend/src/agent_platform/core_platform/agent_runtime/repository.py:350-366` |
| 终态/错误 owner/过期 lease + 普通 finish | 静默 no-op；不提交 output/history/hooks/终态事件 | `backend/src/agent_platform/core_platform/agent_runtime/repository.py:283-325` |
| 非 running/错误 owner/已取消/过期 + 普通 append | 写前抛 `asyncio.CancelledError` | `backend/src/agent_platform/core_platform/agent_runtime/repository.py:253-270` |

### 2.1 RuntimeFault 来源不能只看 Engine 字面 raise

Worker、Engine 与 Factory 的当前字面路径包括 `configuration_changed`、`agent_model_required`、`model_round_limit`、`model_timeout`、`invalid_model_response`、`duplicate_tool_call_id`、`tool_call_limit`、`empty_model_response`、`model_output_too_large`、`repeated_tool_call`（`backend/src/agent_platform/core_platform/agent_runtime/worker.py:109-110`、`backend/src/agent_platform/core_platform/agent_runtime/engine.py:31-115`、`backend/src/agent_platform/applications/platform_runtime/runtime_factory.py:103-114`）。

有快照的生产 Run 使用 GatewayChatModel；它把捕获的 DomainError 按 `RuntimeFault(exc.code)` 传播，只有 `model_stream_not_supported` 走回退而非直接抛出（`backend/src/agent_platform/applications/platform_runtime/runtime_factory.py:97-114`、`backend/src/agent_platform/core_platform/platform_services/model_gateway/gateway.py:551-604`）。当前 chat 可达的额外错误来源至少包括：

- 资源/版本：`model_resource_not_found`、`model_resource_disabled`、`model_profile_version_not_found`（`backend/src/agent_platform/core_platform/platform_services/model_gateway/catalog.py:103-115,306-318`）。
- 输入/能力：`model_input_too_large`、`model_tools_not_supported`（`backend/src/agent_platform/core_platform/platform_services/model_gateway/gateway.py:137-147`）。
- Provider/传输：`model_provider_unavailable`、`model_rate_limited`、`model_provider_rejected`、`model_transport_error`（`backend/src/agent_platform/core_platform/platform_services/model_gateway/gateway.py:353-366,480-489`）。
- 内容治理：`content_blocked_input`、`content_blocked_output`（`backend/src/agent_platform/core_platform/platform_services/model_gateway/gateway.py:386-397`）。
- 网关治理：`gateway_concurrency_exceeded`、`gateway_request_quota_exceeded`（`backend/src/agent_platform/core_platform/platform_services/model_gateway/governance.py:369-393`）。
- 凭据解析：引用的环境变量缺值时抛 `model_credential_unavailable`，Gateway 调用时才解析（`backend/src/agent_platform/core_platform/platform_services/model_gateway/catalog.py:83-90`、`backend/src/agent_platform/core_platform/platform_services/model_gateway/gateway.py:425-435`）。
- 响应/流适配器：非流式与流式响应超过上限时抛 `model_response_too_large`，流未收到 `[DONE]` 即结束时抛 `model_stream_interrupted`（`backend/src/agent_platform/core_platform/platform_services/model_gateway/adapters.py:115-123,281-307,350-353`）。

这是一份按当前调用点分类的基线，不是禁止未来 DomainError 的封闭枚举；后续契约必须保留稳定的原始 code 分类与脱敏边界。

## 3. 竞态与清理基线

- **取消与队列超时不是全局无条件的“取消优先”**：queued cancel 先提交则 reaper 不再选中；reaper 先提交 failed 则后续 cancel 是终态 no-op；reaper 读取时已有取消标志则得到 cancelled-with-`queue_timeout` 变体（`backend/src/agent_platform/core_platform/agent_runtime/repository.py:327-391`）。
- **普通 append 与 heartbeat 是执行期防线**；transient `model.delta` 故意绕过二者，可能在取消/终态附近 best-effort 到达，不具有持久顺序保证（`backend/src/agent_platform/core_platform/agent_runtime/worker.py:48-69`、`backend/src/agent_platform/core_platform/agent_runtime/repository.py:253-281`）。
- `_execute.finally` 取消并 gather watcher 与 execution；serve 停止时取消并 gather dispatcher tasks（`backend/src/agent_platform/core_platform/agent_runtime/worker.py:117-123,186-192`）。
- Worker 只 reaper/claim 配置的 tenant，按 `worker_concurrency` 限量，监听 `runtime_queue` NOTIFY，并以 0.5 秒轮询兜底（`backend/src/agent_platform/core_platform/agent_runtime/worker.py:145-185`）。
- 并行工具之间的事件交错取决于调度；同一工具自身的 started 先于 completed，不能把不同 call_id 的全局固定顺序写成合同（`backend/src/agent_platform/core_platform/agent_runtime/engine.py:107-145`）。

## 4. 持久事件与 transient 事件

普通 `_event` 原子递增 `runtime_runs.event_seq`、插入 `(run_id, seq, type, data)` 并发送持久指针 NOTIFY；`run.queued` 还通知 Worker 队列（`backend/src/agent_platform/core_platform/agent_runtime/repository.py:30-53`）。事件主键为 `(run_id, seq)`，序号每 Run 从 1 开始，不是全局游标（`backend/migrations/versions/0001_runtime.py:47-55`）。

| 事件/写入路径 | 持久 data 形状 |
|---|---|
| `run.queued`、`run.started` | `{}`（`backend/src/agent_platform/core_platform/agent_runtime/repository.py:143-145,243-244`） |
| `run.cancel_requested` | Repository 为 `{}`；人工接管为 `{"reason":"human_handoff"}`（`backend/src/agent_platform/core_platform/agent_runtime/repository.py:352-365`、`backend/src/agent_platform/business_capabilities/human_handoff/service.py:145-153`） |
| 普通 finish 的 `run.completed`、`run.failed` | 同时含 `output` 与 `error_code`：`{"output": output_or_null, "error_code": error_or_null}`（`backend/src/agent_platform/core_platform/agent_runtime/repository.py:313-325`） |
| reaper 的 `run.failed`、`run.cancelled` | **只有** `error_code`，不含 `output` 键；错误为 `queue_timeout` 或 `worker_lost`（`backend/src/agent_platform/core_platform/agent_runtime/repository.py:383-391`） |
| 其他 `run.cancelled` | queued cancel 为 `{}`；handoff 为 `{"reason":"human_handoff"}`；Worker finish 为 `{"output":null,"error_code":null}`（`backend/src/agent_platform/core_platform/agent_runtime/repository.py:323-325,357-365`、`backend/src/agent_platform/business_capabilities/human_handoff/service.py:125-145`） |
| `model.started` | `{"round": round_no}`（`backend/src/agent_platform/core_platform/agent_runtime/engine.py:31-38`） |
| `model.completed` | `round`、`tool_calls`、`usage`、`gateway_call_id`、`first_token_ms`、`duration_ms`（`backend/src/agent_platform/core_platform/agent_runtime/engine.py:85-97`） |
| `tool.started` | `name`、模型工具 `call_id`（`backend/src/agent_platform/core_platform/agent_runtime/engine.py:117-120`） |
| `tool.completed` | `name`、`call_id`、`ok`、`error`、`gateway_call_id`、`execution_status`、`tool_version`、`duration_ms`（`backend/src/agent_platform/core_platform/agent_runtime/engine.py:121-133`） |
| `summary.queued` | `{"dropped": count}`（`backend/src/agent_platform/applications/platform_runtime/runtime_hooks.py:74-84`） |
| `memory_extract.queued` | `{"customer_id": string}`（`backend/src/agent_platform/applications/platform_runtime/runtime_hooks.py:85-106`） |
| `memory.injected` | `items`、`flags`、`events`、`item_ids`；明细另存 item id/section/score（`backend/src/agent_platform/business_capabilities/memory/injection.py:90-107`、`backend/src/agent_platform/applications/platform_runtime/runtime_hooks.py:109-134`） |
| `knowledge.retrieved` | `sources`，含 document id/title/version/chunk id（`backend/src/agent_platform/business_capabilities/knowledge/tools.py:61-76`） |
| `memory_search.completed` | `mode`、`hits`、`returned`（`backend/src/agent_platform/business_capabilities/memory/tools.py:99-106`） |
| `tool.replay` | `idempotency_key` 与完整工具 `result`，属于内部持久重放缓存（`backend/src/agent_platform/core_platform/tool_gateway/replay.py:80-119`） |

可信/外部工具贡献也接收 raw `emit`，因此业务扩展事件不是封闭枚举（`backend/src/agent_platform/core_platform/platform_services/integrations/business_tools/platform_tools.py:26-47`）。后续统一信封不得假定当前只有上表名称。

### 4.1 `model.delta`

- Engine data 为 `round` 加可选 `text`/`reasoning`，不含部分工具 JSON（`backend/src/agent_platform/core_platform/agent_runtime/engine.py:43-55`）。
- Worker 转成 notifier payload `{"k":"delta", ...data}` 后立即返回，不调用 Repository append（`backend/src/agent_platform/core_platform/agent_runtime/worker.py:48-54`）。
- delta 没有数据库 seq，不可通过 after 重放；notifier 失败会丢弃 delta/触发重连，不阻断持久事件（`backend/src/agent_platform/core_platform/agent_runtime/notify.py:32-57`）。
- 开放 SSE 另有 transient、无 id 的 `accepted` 和中途授权失败 `error`（`backend/src/agent_platform/business_capabilities/open_platform/routes.py:324-336,366-370`）。

### 4.2 `tool.replay` 特殊边界

`DurableToolReplayCache.put` 自行增加 event_seq 并插入 `tool.replay`，不走 `_event`，不检查 Run 状态、owner、lease 或取消标志，也不发 NOTIFY（`backend/src/agent_platform/core_platform/tool_gateway/replay.py:80-119`）。因此它可在并发/直接调用时于终态后消耗序号；两个 SSE 实现都隐藏其 payload 但推进游标（`backend/src/agent_platform/applications/customer_service/runtime_routes.py:115-121`、`backend/src/agent_platform/business_capabilities/open_platform/routes.py:371-390`）。**这不能被概括为“普通执行事件也允许终态后写入”，也不能用普通 append 的测试替代该专用路径的测试。**

## 5. SSE 重放与字段暴露

### 5.1 内部 SSE

- 查询 `after` 与 `Last-Event-ID` 取 `max(after,last_id)`；非法/越界 header 返回 400（`backend/src/agent_platform/applications/customer_service/runtime_routes.py:83-121`）。
- Repository 严格读取 `seq > after`，按 seq 排序，每页最多 200 条（`backend/src/agent_platform/core_platform/agent_runtime/repository.py:175-201`）。
- 输出 `id: seq`、`event: type` 和完整 JSON data；transient delta 无 id，不推进游标（`backend/src/agent_platform/applications/customer_service/runtime_routes.py:115-145`）。
- 仅在 Run 已终态且游标达到当前 event_seq 时结束；满 200 条页面先继续排空再等待，15 秒无通知发送 heartbeat comment（`backend/src/agent_platform/applications/customer_service/runtime_routes.py:122-148`）。

### 5.2 开放 SSE

- 使用同样的 strict-after/max 与终态排空规则，先输出 accepted，0.5 秒轮询并按固定 tick 发 heartbeat（`backend/src/agent_platform/business_capabilities/open_platform/routes.py:324-399,454-465`）。
- delta 只公开 truthy 可见文本，不公开 reasoning（`backend/src/agent_platform/business_capabilities/open_platform/routes.py:337-361`）。
- 持久 data 缩减为 `run_id`；模型事件只增加 round/tool-call 计数，终态事件合并完整公开 RunView。工具输入、检索来源、usage、gateway id、memory 明细和 replay payload 不公开（`backend/src/agent_platform/business_capabilities/open_platform/routes.py:371-390`）。

## 6. 后续阶段必须保持的断言

1. 五个持久状态、取消标志与终态保护不被新 Engine 状态复制或绕开。
2. `execution_error`、`run_timeout`、Engine/Factory/Model Gateway 的 RuntimeFault code 及 reaper 取消变体不得被理想化成单一错误形状。
3. 普通持久事件序号与状态事务、严格大于游标、终态后排空和 200 条分页保持兼容。
4. transient delta 不进入持久游标；公开 SSE 不暴露 reasoning、工具输入、usage、gateway/memory/replay 明细。
5. 普通 append/finish 与 `tool.replay` 分开测试；任何安全修复必须另起需求和小提交，并显式记录行为变更，不能在 Phase 0 基线测试中暗中改变。
