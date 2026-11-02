# 人工工作台业务上下文（H2 切片）

> 状态：后端、前端与真实数据联调均已落地
> 创建：2026-11-02
> 关联：
> - [人工工作台 V1](./human-workbench-v1.md)
> - [客服模块实施路线](./implementation-roadmap-v1.md)
> - [行业 Pack 运行时](./industry-pack-runtime-v1.md)

## 0. 本次解决了什么

V1 工作台只能显示交接摘要、最近消息、待确认动作和最近运行。坐席看不到“客户选的是哪个订单、系统查到了什么、客户确认了什么”。

本次给出两件事：

1. **场景轨迹可以绑定真实会话**，不再只有模拟器自己产生的孤立记录。
2. **交接上下文聚合接口** `GET /api/v1/handoffs/{id}/context`，服务端一次性返回场景、对象、事实、决策和执行证据，并把权限裁剪与脱敏留在服务端。

## 1. 场景轨迹绑定会话

### 1.1 数据层

`service_scenario_traces` 增加可空列 `conversation_id`：

- 外键 `runtime_conversations(id)`，`ON DELETE SET NULL`。
- 索引 `(tenant_id, business_id, workspace_id, conversation_id, created_at DESC)`。
- 迁移：`backend/migrations/versions/0056_scenario_trace_conversation.py`。

可空是刻意的：模拟器产生的证据不绑定会话，历史数据不需要回填。

### 1.2 写入链路

`SimulationRequest` 增加可选 `conversation_id`：

```json
POST /api/v1/service-scenarios/simulate?scenario_key=query-orders
{
  "message": "我要退货",
  "conversation_id": "2f1c...",
  "object": {"id": "SO-1", "type": "order", "status": "已发货", "facts": {"status": "已发货"}}
}
```

写入前会在同一事务内校验该会话属于当前租户与业务范围，否则返回 `404 conversation_not_found`，不会写出一条跨租户轨迹。

应用级模拟 `POST /api/v1/service-apps/{key}/simulate` 同样透传该字段。

## 2. 聚合接口

```text
GET /api/v1/handoffs/{id}/context
```

### 2.1 返回结构

| 字段 | 来源 | 说明 |
|---|---|---|
| `handoff` | `handoffs` | 状态、处理人、原因、摘要、revision |
| `conversation` | `runtime_conversations` | 模式、来源、外部标识、`has_customer` 布尔 |
| `application` | 最近轨迹的 `trace.application` | 应用级模拟时写入的应用快照 |
| `scenario` | 最近一条绑定的轨迹 | 场景 key、名称、版本、处理能力、结果 |
| `object` | 轨迹 `object_ref` | 仅 `type / id / status` |
| `facts` | 轨迹 `facts` | 已按坐席视角过滤 |
| `decisions` | 轨迹 `decisions` | `selected` 映射为 `已选择`，其余为 `待确认` |
| `actions` | `pending_actions` | 仅投影 `title/description`，带 `valid` |
| `runs` | `runtime_runs` | 最近 10 条状态与失败码 |
| `routing` | `routing_decisions` | 转人工原因、处置与执行层级 |
| `traces` | `service_scenario_traces` | 最近 10 条轨迹摘要 |

### 2.2 权限与脱敏

1. 交接记录先按租户 + 业务范围读取，跨范围一律 `404 handoff_not_found`。
2. 后续所有查询都带同一 scope 谓词，不做前端拼接。
3. 业务事实按 `audiences` 过滤，只保留包含 `human` 或 `agent` 的字段；仅面向客户的字段不进入坐席视图。
4. `source`、Provider 名称、队列名、规则键等实现细节不进入响应。
5. 客户身份在上下文中只暴露 `has_customer`，不回传 `customer_id`。
6. 脱敏由事实投影时的 `masked` 标记决定，响应只带 `masked: true` 和已遮蔽的值。

### 2.3 空状态语义

没有绑定轨迹时：

- `scenario`、`application`、`object` 为 `null`。
- `facts`、`decisions`、`traces` 为空数组。
- `routing` 为空数组（内部 API 创建的会话没有 ingress 决策，不能编造原因）。

前端据此展示“自动服务尚未绑定场景轨迹”，而不是显示伪造的成功数据。

## 3. 前端

`HandoffPage` 新增“自动服务”区块：

- 服务场景、场景版本、业务对象（类型 · 标识）。
- 业务事实（含“已脱敏”标记）。
- 用户决策（已选择 / 待确认）。
- 空状态、加载失败与重试。

新增 8 条文案，四语言同步（`check:i18n` 通过，1866 条）。

## 4. 测试

`backend/tests/test_handoff_context.py`（6 项，全部通过）：

1. 无轨迹时上下文诚实为空，运行记录仍可见。
2. 绑定轨迹后能还原场景、对象、事实、决策，且客户专属事实与 Provider 名称不泄漏。
3. 轨迹绑定在别的会话上时，本会话上下文不受影响。
4. 未知交接返回 `404 handoff_not_found`。
5. 只读角色可读上下文但不可接管。
6. 跨租户会话不允许写入轨迹（`404 conversation_not_found`）。

真实环境联调（本地 8000，`admin / nexusdesk`，场景 `track-logistics`）：

```text
POST /api/v1/conversations                        → 201
POST /api/v1/service-scenarios/simulate           → 200，响应回带 conversation_id
POST /api/v1/conversations/{id}/handoffs          → 200
GET  /api/v1/handoffs/{id}/context                → 200
      scenario: track-logistics v1 / query / succeeded / query_executed
      object:   order · SO-E2E-…
      facts:    5 条，amount 返回 *99.0 且 masked=true
      decisions: select_order / confirm_object / choose_intent 均为 pending
      traces 1 · routing 0 · runs 1 · actions 0
POST /handoffs/{id}/transition claim → close      → 200 / 200
```

`application` 为 `null` 是预期结果：本次走的是场景模拟入口，不是应用级模拟，没有应用快照可还原。

## 5. 仍然缺什么

1. **运行时尚未真正写轨迹**：目前只有模拟入口会写。真实会话里路由到场景后应落一条 `simulation=false` 的轨迹，这是下一步的关键。
2. 场景版本还没有在会话创建时固化，只能从最近一条轨迹反推。
3. 真实渠道入站的 handoff 仍未覆盖：本次联调用的是平台 API 创建的会话，`routing` 为空，需要一条从企微/飞书入站、场景执行到转人工的完整链路。
4. 事实刷新策略（`refresh`）尚未在人工视角落地，当前只返回轨迹快照。

## 6. 与行业 Pack 运行时同步

`alpha / beta / ga` 成熟度和 Provider 能力检查已经进入 readiness：

- `alpha` 场景必须阻断发布。
- `beta` 场景只有应用配置 `canary` 渠道时才可通过。
- `ga` 场景正常参与发布检查。
- Pack 场景依赖的对象、工具和人工队列缺失时阻断。

场景级发布接口也会直接阻止 `alpha`，错误码为
`scenario_alpha_publish_forbidden`。

本切片没有重复实现人工工作台上下文。工作台仍需用真实渠道 handoff 验证轨迹写入、场景版本固化、事实刷新和权限脱敏。
