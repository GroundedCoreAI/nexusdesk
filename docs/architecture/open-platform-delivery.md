# 开放平台作为统一对外交付层：落地方案

> 状态：阶段 0、阶段 1（后端 + 公开契约 + 前端绑定入口）已实施并验证；阶段 2 起未开始
> 目标：把开放平台从「Agent API 网关」升级为「对外交付控制面」，先接入 Service Application，再逐步收口全部对外访问链路。

---

## 1. 定位与目标态

### 1.1 一句话定位

**对外一切入口都由开放平台的应用对象统一授权、限流、审计；执行单元可以是 Agent，也可以是（并且优先是）Service Application。**

### 1.2 三层结构

| 层 | 承载 | 职责 |
|---|---|---|
| 交付层 | `open_platform`（`open_applications`） | 一套凭证、一组接入通道、一套配额与审计 |
| 执行层 | `service_apps` / `agent_runtime` | Service Application（技能·连接·规则·欢迎语·知识·handoff）或裸 Agent |
| 通道层 | `channels` | 企业消息渠道（企微/飞书/钉钉/Slack/TG…） |

### 1.3 核心关系

```
open_application (1) ──绑定──> (1) 执行主体
                                   ├── service_application（推荐，完整编排）
                                   └── agent（legacy，裸执行单元）
open_application (1) ──启用──> (N) 接入方式
                                   ├── Hosted Web
                                   ├── Embed
                                   ├── API / SDK
                                   ├── 消息渠道
                                   └── Playground
```

**关键约束：一个开放平台应用只绑定一个执行主体，可以启用多种接入方式。** 这是把「应用为中心」落进数据模型的方式。

---

## 2. 现状盘点

### 2.1 已经具备（不需要重写）

| 能力 | 位置 | 说明 |
|---|---|---|
| 应用密钥 | `open_api_keys`（`opk_`） | 哈希存储、前缀展示、过期、轮换含过渡期、上限 10 个 |
| 限流 / 并发 | `open_rate_windows`、`max_concurrency` | 分钟窗口 + 活跃 run 计数 |
| 幂等 | `open_runs.idempotency_key + payload_hash` | 同键同载荷返回原 run，异载荷 409 |
| SSE 流 | `stream_response()` | `accepted / model.delta / tool.* / run.*`，含 `Last-Event-ID` 续传，公开流已过滤检索片段与工具入参 |
| 请求审计 | `open_request_logs` | 路由、状态码、耗时、错误码、run_id、request_id |
| Webhook 回调 | `open_webhooks` / `open_deliveries` | 签名投递、重试、投递记录 |
| 知识库同步 | `open_sync_tasks` / `open_synced_documents` | 外部文档增删改 + 发布任务 |
| 企业身份 | `enterprise_providers` / `enterprise_sessions` | OIDC / 企微 / 飞书 / 钉钉，`chat_` 会话令牌，embed 域名白名单 |
| Embed 配置 | `open_embed_configs` | 域名白名单、标题、主题色、登录提供方 |
| Embed 前端 | `features/open-platform/EmbedChat.tsx` | postMessage 握手、SSO 换令牌、流式渲染 |
| 渠道 | `channels` + `/api/v1/ingress/channels/{id}/*` | 8 类 provider、版本外键钉定、入站去重、回执 |
| 应用会话链路 | `service_apps/sessions.py` | `open_session` / `send_message` **已参数化**（`kind` / `source` / `context_override` / `allow_unpublished`） |

### 2.2 缺口（本方案要补的）

| 缺口 | 影响 |
|---|---|
| `open_applications` 只能授权 Agent | 无法把 Service Application 交付出去；开放平台用不上应用里配的技能/连接/规则/知识 |
| 平台内没有公开会话入口 | Hosted Web 完全不存在 |
| Embed 只支持 Agent | 嵌入窗口跑的是裸 Agent，不是客户配好的客服应用 |
| 渠道在 UI 上是并列页，不在应用维度归口 | 「这个应用对外有哪些入口」看不全 |
| 应用 `status='offline'` 不生效 | 下线后渠道照跑（上一轮已确认） |
| 台账无来源字段 | 无法区分「后台体验发的」与「开放平台客户发的」 |

---

## 3. 数据模型

### 3.1 新增：交付主体绑定

```sql
-- 拟新增
CREATE TABLE open_application_targets (
  app_id       uuid NOT NULL REFERENCES open_applications(id) ON DELETE CASCADE,
  target_kind  text NOT NULL CHECK (target_kind IN ('agent','service_application')),
  target_id    uuid NOT NULL,
  version_pin  integer,          -- NULL = 跟随最新发布
  created_at   timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (app_id, target_kind, target_id)
);

-- 一个应用只能绑一个 Service Application
CREATE UNIQUE INDEX open_targets_single_application
  ON open_application_targets(app_id) WHERE target_kind = 'service_application';
```

**为什么不用改造 `agent_ids`：**

- `agent_ids uuid[] + agent_versions jsonb` 是「一个密钥访问多个 Agent」的旧范式，语义是**授权清单**；
- Service Application 自带完整编排，语义是**交付主体**，天然唯一；
- 新表把两种语义显式分开，将来加 workflow / agent-team 只需扩 `target_kind` 枚举。

**迁移兼容：** 存量 `agent_ids` 非空 → 迁移时写入 `target_kind='agent'` 的行（每 agent 一行），旧路径保留，前端「创建应用」二选一。

### 3.2 放宽约束

```sql
-- 拟改
runtime_conversations_source_check  → 增加 'open_platform'
open_sessions.agent_id              → DROP NOT NULL（应用模式下无 agent）
```

**不做的事：**

- 不给 `service_application_conversations` 加列。来源写进现有 `metadata`（`{"source":"open_platform","open_app_id":"..."}`），
  统计口径继续按 `kind='customer'`，因为开放平台会话就是真实客户会话，应当进工作台。
- 不改 `kind` 枚举（`customer` / `debug` 保持）。

### 3.3 会话命名空间

| 入口 | external_conversation_id | 约束 |
|---|---|---|
| 后台体验 | `app:{key}:{session_digest}` | 平台登录态 |
| 调试 | `debug:{session_key}` | `kind='debug'` |
| 渠道 | 渠道自带 | `channel_id` 非空 |
| **开放平台** | `open:{open_app_id}:{digest(external_user, external_session)}` | `kind='customer'`，`source='open_platform'` |

现有 `open_sessions` 已有 `(app_id, external_user_id, external_session_id)` 唯一语义，直接复用即可，只是把 conversation 创建委派给 `service_apps.sessions.open_session()`。

---

## 4. 执行链路

### 4.1 现状（Agent 模式）

```
POST /openapi/v1/conversations/{cid}/messages
  → open_platform.submit()
  → snapshot = platform.snapshot + agents.snapshot(version_pin)
  → repository.submit(RunRequest)          # 直接投递 runtime
  → INSERT open_runs
```

### 4.2 目标（Service Application 模式）

```
POST /openapi/v1/conversations/{cid}/messages
  → open_platform.submit()
  → 判定 target_kind == 'service_application'
  → service_apps.sessions.send_message(
        tenant, application_key, conversation_id,
        content,
        actor="open_platform",
        idempotency_key=<Idempotency-Key>,
        external_user_id=<X-External-User-ID>,
        kind="customer",
    )
  → 复用：路由决策 → 准入 → 队列 → worker → 台账 → 事件
  → INSERT open_runs（关联 run_id）
```

**这一条是整套方案的关键：技能、连接、业务规则、知识库、handoff、台账、回复事件——全部零重写。**
`open_session` / `send_message` 在上一轮已经为调试链路参数化，这次只是复用同一组开关。

### 4.3 版本钉定

- `version_pin` 为 NULL：每次开新会话取 `published_version`，老会话保持原版本（`resolve()` 已按 turn 记录版本）
- `version_pin` 有值：`allow_unpublished=False`，`resolve(application_id, version_pin)`
- 应用发布新版本时，开放平台**不自动跟随**（对外的行为契约要稳定），在 UI 上提示「有新版本可用」

### 4.4 身份三层（不能混）

| 身份 | 载体 | 用途 |
|---|---|---|
| 访问者 | `X-External-User-ID` 或 `chat_` 会话令牌 | 谁在对话 |
| 接入应用 | `Bearer opk_` | 哪个系统在调用、算谁的配额 |
| 执行身份 | 应用快照里的 `connections` 凭据 | Agent 以什么权限调企业工具 |

长期密钥只出现在服务端；Embed / Hosted Web 一律走 `chat_` 短期令牌，且令牌只能在 `openapi/v1` 的对话类路径上使用（现有 `chat_scope_required` 校验已实现）。

---

## 5. 五种接入方式映射

| # | 接入方式 | 现状 | 缺口 | 方案 | 优先级 |
|---|---|---|---|---|---|
| 1 | **Hosted Web** | 无 | 全部 | 新增公开页 + 公开会话 API（见 5.1） | P0 |
| 2 | **Embed** | `EmbedChat.tsx` + `open_embed_configs` + SSO | 只认 Agent | 配置加 `target`，`/sso/embed/{app}` 返回应用信息，前端隐藏 Agent 选择器 | P1 |
| 3 | **API / SDK** | `/openapi/v1` 全套 | 只认 Agent | `/conversations` 的 `agent_id` 变可选；无则按绑定主体路由 | **P0** |
| 4 | **消息渠道** | `channels` + ingress | 未在应用维度归口 | 开放平台详情加「渠道」tab，复用 `ChannelsPage` 过滤到本应用 | P1 |
| 5 | **Playground** | 应用「客户交互」调试 + 开放平台 debug | 两套入口 | 开放平台 debug tab 对应用模式复用 `preview` 链路 | P1 |

### 5.1 Hosted Web 的最小实现

- 路由：`/a/{public_slug}`（`open_applications` 加 `public_slug`，可选 `public_access` 枚举：`anonymous` / `login` / `disabled`）
- 前端：新页面复用 `EmbedChat` 的流式渲染逻辑，去掉 postMessage 握手，改为直接换令牌：
  - `anonymous` → 服务端签发匿名 `chat_` 令牌（限 TTL、限该 app）
  - `login` → 复用现有 OIDC / 企微 / 飞书登录
- 后端：`GET /api/v1/public/apps/{slug}`（展示配置）+ `POST /api/v1/public/apps/{slug}/token`
- 会话：外部用户 ID 用浏览器持久化 uuid（localStorage），行为与调试会话的 `session_key` 一致

### 5.2 Embed 扩展点

现有 `EmbedChat` 流程是：父页面 postMessage 令牌 → `/openapi/v1/agents` → 用户选 Agent → `/conversations`。
应用模式下应变成：父页面给令牌 → 直接进对话（无 Agent 选择器），欢迎语和标题来自应用快照 + embed 配置。

外观归属建议：**标题/主题色以 `open_embed_configs` 为准，欢迎语/业务规则/技能以 Service Application 快照为准**，两者不重叠。

---

## 6. 分阶段落地

### 阶段 0：地基（数据模型）— 已完成

| 项 | 内容 |
|---|---|
| 迁移 | `0065_open_platform_targets`：`open_application_targets` 建表 + 存量 agent 回填（10 应用全部回填）；`runtime_conversations.source` 加 `open_platform`；`open_sessions.agent_id` 放宽 |
| 服务 | `service.py` 增加 `target()` / `delivery()`（含版本钉定）、`check()` 增加「目标可用性」校验（应用已发布 / 未下线 / 未归档，fail closed） |
| 验收 | 存量 Agent 应用行为不变（`test_open_platform.py` 6 passed）；迁移 `downgrade -1` + `upgrade head` 往返通过 |

### 阶段 1：开放平台接入应用（P0，核心）— 后端已完成

| 项 | 内容 |
|---|---|
| 后端 | `submit()` 分支到 `service_apps.sessions.send_message`；`create_session` 分支到 `open_session`（`release_version` 钉定 + `metadata` 来源标记）；`create_conversation` 的 `agent_id` 变可选 |
| 契约 | `POST /conversations` 省略 `agent_id` 时按绑定主体；`GET /openapi/v1/targets` 返回交付主体与版本；`GET /open-platform/service-applications`、`.../versions` 供管理端选择 |
| 前端 | **已完成**：创建/编辑应用为「可选绑定服务应用 + 版本钉定」，绑定后 Agent 自动关联（授权清单禁用手动编辑）；列表卡与配置页显示交付主体与版本；接入文档示例按主体自适应（应用模式省略 `agent_id`）；在线调试对应用模式隐藏 Agent 选择；集成配置对应用模式隐藏 Agent 版本固定 |
| 验收 | 真实 HTTP 端到端 13/13 通过（`backend/scripts/e2e_open_platform_delivery.py`）：`opk_` 密钥 → `/targets` → 建会话（`agent_id` 为 null）→ 发消息 → SSE `run.completed` → 台账 `kind=customer` 且 `metadata.source=open_platform` → 后台工作台可见 → `open_runs` / `open_request_logs` 有记录 |

### 阶段 2：统一交付详情页（P0）

| 项 | 内容 |
|---|---|
| 前端 | 应用详情顶部加「交付方式」概览卡：Web / Embed / API / 渠道 / Playground，各自启用状态 + 快捷配置 |
| 后端 | 新增 `GET /open-platform/applications/{id}/delivery` 聚合：绑定主体、启用通道、密钥数、近 7 日会话/成功率/平均响应 |
| 验收 | 管理员在一个页面看清「这个应用对外有哪些入口、怎么开」 |

### 阶段 3：Hosted Web + Embed 扩展（P1）

| 项 | 内容 |
|---|---|
| 后端 | `public_slug` / `public_access`；公开配置与令牌签发接口；embed 支持应用模式 |
| 前端 | `/a/{slug}` 公开页；embed 应用模式隐藏 Agent 选择器 |
| 验收 | 匿名打开公开链接能对话；嵌入到白名单域名能对话，非白名单域名 403 |

### 阶段 4：渠道归口（P1）

| 项 | 内容 |
|---|---|
| 前端 | 开放平台详情「渠道」tab，按 `application_id` 过滤 `ChannelsPage` |
| 后端 | 渠道创建/切换版本时校验所属应用是否已绑定为交付主体（提示但不强制） |
| 验收 | 从应用详情能直接建渠道并看到入站记录 |

### 阶段 5：治理收口（P2）

| 项 | 内容 |
|---|---|
| 版本一致性 | 「开放平台钉的版本 ≠ 应用最新发布版本」提示 + 一键升级 |
| 下线联动 | 应用 `offline` 时开放平台应用自动置于 `disabled` 并拒新会话（**先修 `offline` 不生效的问题**） |
| 配额统一 | 渠道入站也计入 `open_rate_windows`（可选，按 provider 单独限流） |
| 审计统一 | 渠道入站、Web、Embed 三类流量统一进 `open_request_logs`（`route` 区分） |

---

## 7. 需要拍板的决策

| # | 决策 | 建议 |
|---|---|---|
| 1 | 一个开放平台应用能否绑多个执行主体？ | **不能**。多主体会让「一套凭证」失去意义，需要多主体就建多个开放平台应用 |
| 2 | 版本默认钉死还是跟随？ | **默认钉死**，UI 提供「跟随最新」开关；对外契约稳定优先 |
| 3 | Hosted Web 默认访问控制？ | **默认 `login`**，匿名需显式开启（避免公开链接被爬） |
| 4 | 存量 Agent 多授权模式是否保留？ | **保留但标记 legacy**，新建应用不再提供多选 |
| 5 | 渠道是否必须经开放平台？ | **不强制**。渠道继续直连应用，开放平台只做视图归口，避免动 ingress 的稳定链路 |
| 6 | 开放平台会话是否进工作台？ | **进**。它是真实客户会话，与后台体验/调试不同 |

---

## 8. 风险与坑

| 风险 | 说明 | 对策 |
|---|---|---|
| 应用下线不生效 | `resolve()` 与渠道入站都不检查 `status`，开放平台接进来后会放大这个问题 | 阶段 5 前置：在 `open_session` 加 `status='offline'` 拒绝，历史会话回放走单独分支 |
| 版本双轨 | 应用发布版本、开放平台 `version_pin`、渠道 `application_version` 三处独立 | 三者语义写进同一份文档；UI 上互相提示不一致 |
| 会话命名空间冲突 | 开放平台 `open:{app_id}:{digest}` 与后台体验 `app:{key}:{digest}` 不同源，同一个客户在两边是两条会话 | 接受（不同入口不同身份），文档明确 |
| 公开流泄露内部信息 | `stream_response` 已过滤检索片段与工具入参，但应用模式的 `tool.*` 事件更多 | 复用同一过滤器，不按模式分叉 |
| 幂等键语义不一致 | `open_runs` 用 `payload_hash`，`send_message` 用 `_turn_by_idempotency_key` | 开放平台层先做一次幂等（同键直接返回原 run），下层幂等只做兜底 |
| 台账来源不可过滤 | 来源写进 `metadata`，SQL 过滤需 `metadata->>'source'` | 若后续统计需要，再补生成列 + 索引 |

---

## 9. 明确不做

- 不新建第五套运行时或独立 API 网关进程
- 不重写渠道适配器（8 类 provider 已可用）
- 不把「Web 发布 / API 发布 / Embed 发布」做成三个独立管理模块
- 不在浏览器或前端 SDK 放置 `opk_` 长期密钥

---

## 10. 落地顺序建议

```
阶段 0（模型） → 阶段 1（API 接入应用）★ 核心价值点
              → 阶段 2（交付详情页：让入口可见）
              → 阶段 3（Hosted Web / Embed）
              → 阶段 4（渠道归口）
              → 阶段 5（治理收口）
```

阶段 1 完成后，产品叙事就成立了：**「创建应用 → 发布 → 在开放平台绑定并签发密钥 → 外部系统即可调用同一套技能与知识」**。
后续每个阶段只是往同一个交付详情页上加一张卡。

---

## 11. 实施记录（阶段 0 / 1）

### 11.1 变更文件

| 层 | 文件 | 说明 |
|---|---|---|
| 迁移 | `backend/migrations/versions/0065_open_platform_targets.py` | 绑定表 + 部分唯一索引 + 回填 + `source` CHECK 放宽 + `open_sessions.agent_id` 可空 |
| 迁移 | `backend/migrations/versions/0064_application_debug_sessions.py` | 调试会话来源（前置） |
| 会话 | `service_apps/sessions.py` | `open_session` 支持 `release_version` / `metadata`；`_application` 支持 `allow_offline`；`send_message` 对存量会话放行离线应用 |
| 运行时 | `conversation/service.py` | 合法 `source` 增加 `open_platform` |
| 服务 | `open_platform/service.py` | 绑定校验、`targets()` / `target()` / `delivery()` / `describe()`、`create_session` / `submit` 双分支、`session()` 按 `application_id` 校验归属 |
| 契约 | `open_platform/routes.py` | 应用详情返回解析后的 `target`（含 name/key/version/pinned）；列表逐卡附带 `target`；新增 `GET /open-platform/service-applications(+ /versions)`；新增 `GET /openapi/v1/targets`；会话 `agent_id` 可选 |
| 前端 | `frontend/src/features/open-platform/*` | 编辑器绑定服务应用（可选）+ Agent 自动关联、配置页/列表卡交付展示、接入文档与在线调试按主体自适应、四语言词条同步 |
| 测试 | `backend/tests/test_open_platform_delivery.py` | 3 用例：绑定规则、真实客户链路、版本钉定与下线门禁 |
| 验证 | `backend/scripts/e2e_open_platform_delivery.py` | 真实 socket HTTP 端到端脚本（独立租户，不影响开发环境） |

### 11.2 关键语义（实现即契约）

- **绑定唯一性**：`target_kind='service_application'` 上有部分唯一索引，一个开放平台应用只绑一个服务应用；绑定后 `agent_ids` 由服务应用包装的 Agent **自动派生**（展示与 `/openapi/v1/agents` 列表用），运行时路由只认交付目标，公开建会话仍拒绝 `agent_id`（`agent_id_not_applicable` 422）。
- **版本钉定**：`version_pin IS NULL` 跟随当前 `published_version`；有值则钉死。`/targets` 的 `pinned` 字段即是否钉定。
- **下线 fail closed**：应用 `archived` / `offline` / 未发布时 `/targets`、`/conversations`、`/sessions` 全部 409，不静默回退 Agent 路径；已存在会话的后续消息放行（`allow_offline`）。
- **来源可追溯**：`runtime_conversations.source='open_platform'`，台账 `service_application_conversations.metadata` 记 `source` / `open_app_id` / `runtime_conversation_id`，`kind` 仍为 `customer`，所以进工作台、进应用对话记录。

### 11.3 复跑方式

```bash
cd backend
export TEST_DATABASE_URL='postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/agent_platform_test'
.venv/Scripts/python.exe -m pytest tests/test_open_platform.py tests/test_open_platform_delivery.py -q
.venv/Scripts/python.exe scripts/e2e_open_platform_delivery.py
```

E2E 脚本用独立租户 `test-e2e-*` 落数据，跑完不清理（测试库）；要复查时按租户查 `runtime_conversations` / `service_application_conversations` / `open_runs` 即可。

### 11.4 已知缺口

1. 交付详情页尚未聚合「Web / Embed / API / 渠道 / Playground」入口概览 —— 阶段 2 的内容。
2. 开放平台应用侧没有「切换交付主体后旧会话怎么办」的运营视图；当前靠 `session_target_conflict` 409 强制换新会话。
3. 演示模型不会真的发起技能调用，E2E 只能验证到「同一链路 + 台账 + 来源」，技能调用需接真实模型或 mock 业务再验一次。
