# Phase 1 · 技能中心的应用运行时 — 需求文档

> 状态：需求基线已落地，定向实现与验证完成；全量验收待执行
> 创建：2026-11-11
> 依据：[01-business-goals.md](01-business-goals.md)（G1～G6）

## 用户故事

**US-1（应用管理员）**：作为应用管理员，我希望创建服务应用时直接选择一个 Agent 和发布版本，以便不再先理解场景与能力层级。

**US-2（应用管理员）**：作为应用管理员，我希望在应用内配置技能和连接，以便订单查询等同名技能可以为不同应用使用不同 URL 和凭据。

**US-3（应用管理员）**：作为应用管理员，我希望为技能设置人工确认、金额/权限、幂等、超时和失败降级规则，以便高风险写操作不会由模型自由决定。

**US-4（应用管理员）**：作为应用管理员，我希望发布、回滚和查看版本差异，以便确认线上行为稳定且可追溯。

**US-5（渠道管理员）**：作为渠道管理员，我希望把客户渠道绑定到某个已发布应用版本，以便草稿修改不会意外影响线上客户。

**US-6（运营人员）**：作为运营人员，我希望从标准案例复制一个可编辑应用，以便快速开始且不用担心标准案例被弄脏。

**US-7（客服主管）**：作为客服主管，我希望从会话追溯到应用、Agent、技能与连接，以便排查和审计。

**US-8（研发/运维）**：作为研发或运维，我希望删除未上线的旧概念和双轨代码，以便系统只维护一套可理解的应用运行时。

## 功能需求

### FR-1 服务应用结构

| 项 | 说明 |
|---|---|
| 触发时机 | 创建、编辑或打开服务应用 |
| 输入 | 名称、描述、类型、来源、绑定的 Agent、技能、连接、应用级规则和渠道 |
| 输出 | v2 应用草稿和摘要；不再输出场景、能力、Provider 或执行顺序 |
| 执行方式 | 同步 CRUD；配置保存使用 revision 乐观锁 |
| 失败处理 | key 重复、Agent 不存在/未发布、跨作用域引用返回明确 4xx；不产生部分保存 |

应用必须直接绑定恰好一个 Agent。Agent 必须存在、未归档且至少有一个可发布版本。应用来源为 `user` 或 `example`；示例应用 `immutable=true`，只能复制或预览。

### FR-2 技能模型

| 项 | 说明 |
|---|---|
| 触发时机 | 应用管理员新增、编辑、启停或删除技能 |
| 输入 | key、名称、描述、类型、连接、参数 schema、参数映射、结果映射、安全规则、失败策略 |
| 输出 | 应用内唯一技能记录；发布快照中的技能条目 |
| 执行方式 | 同步 CRUD；保存后仅影响草稿 |
| 失败处理 | 非法 schema、缺少连接、重复 key、引用其他应用连接时拒绝保存 |

技能类型限定为 `knowledge`、`query`、`action`、`handoff`。`agent` 不再作为技能类型；Agent 是应用级绑定。`action` 技能必须声明是否写操作；高风险写操作必须启用人工确认或显式安全豁免并记审计。

### FR-3 应用连接

| 项 | 说明 |
|---|---|
| 触发时机 | 管理员配置外部 HTTP 服务、内部动作或人工队列 |
| 输入 | key、名称、执行器类型、endpoint、method、公开 Header、认证方式、超时、响应限制、配置 |
| 输出 | 只属于该应用的连接；API 不返回明文凭据 |
| 执行方式 | 同步 CRUD；连接测试异步或短同步调用 |
| 失败处理 | endpoint 不安全、Header 冲突、凭据缺失、测试失败返回可定位错误；不得回显密钥 |

连接 key 在同一应用内唯一。不同应用即使 endpoint 相同也不共享连接实例、凭据、revision 或修改权限。连接 endpoint 禁止 URL 内嵌用户名/密码、禁止动态 query/fragment。

### FR-4 连接凭据

| 项 | 说明 |
|---|---|
| 触发时机 | 保存或轮换连接凭据 |
| 输入 | bearer token、API key、自定义 Header 密文或引用 |
| 输出 | `service_application_connection_credentials` 中的密文；响应仅返回 `credentials_configured=true` |
| 执行方式 | 与连接保存同事务或独立轮换操作 |
| 失败处理 | 加密失败则整体失败；Vault 不可用时禁止降级为明文；审计只记录配置状态 |

凭据只能由应用连接解析器在本应用运行上下文中解密。发布 JSON、运行快照、trace、审计、日志和错误消息不得出现明文。

### FR-5 业务规则与安全边界

| 项 | 说明 |
|---|---|
| 触发时机 | 技能调用前、调用中、调用后 |
| 输入 | `requires_confirmation`、`max_amount`、`allowed_roles`、`idempotency_key`、`timeout_seconds`、`on_error`、`result_schema`、应用级兜底/handoff 配置 |
| 输出 | 允许执行、要求人工确认、拒绝、超时、降级或二次人工处理 |
| 执行方式 | 运行时确定性检查；模型只能提出调用，不能绕过规则 |
| 失败处理 | 规则求值失败按拒绝处理 `rule_evaluation_failed`；写操作幂等冲突不重复执行 |

### FR-6 发布快照

| 项 | 说明 |
|---|---|
| 触发时机 | 管理员点击发布 |
| 输入 | 当前草稿 revision、绑定 Agent 版本、技能、连接元数据、规则、渠道引用 |
| 输出 | 不可变 `service_application_versions.config` v2；应用 `published_version` 更新 |
| 执行方式 | 单事务；先完成 readiness，再生成快照 |
| 失败处理 | Agent 未发布、连接未配置、凭据缺失、技能非法、revision 冲突均阻止发布，不产生半成品版本 |

快照必须包含 `schema_version="v2"`、Agent id/version、技能数组、连接公开元数据与 `credential_ref`、digest 和渠道配置。发布不可变；修改草稿不改变任何已发布版本。

### FR-7 回滚与版本历史

| 项 | 说明 |
|---|---|
| 触发时机 | 管理员选择历史版本回滚 |
| 输入 | 目标版本、当前应用 revision |
| 输出 | 以目标快照为源生成新的最高版本；`source_version` 指向目标版本 |
| 执行方式 | 同步、单事务 |
| 失败处理 | 目标版本不存在、Agent/连接已不可用、revision 冲突返回 409/422；不破坏原历史 |

回滚采用追加式历史，不直接修改旧版本。新消息使用回滚后发布的新版本；已入站事件保持其入站时固定的版本。

### FR-8 应用级运行时

| 项 | 说明 |
|---|---|
| 触发时机 | 提交 Agent run 前 |
| 输入 | 应用 id、应用版本、绑定 Agent 版本、会话、消息 |
| 输出 | 含应用上下文的 run snapshot：授权技能列表、连接解析引用、规则、trace 元数据 |
| 执行方式 | 在提交 run 的同一事务中解析发布快照和 Agent snapshot |
| 失败处理 | 应用版本不可用、Agent 版本缺失、技能/连接不一致则拒绝运行并写可观测错误 |

运行时只能暴露“Agent 选择的平台内置工具 ∩ 应用授权技能”。自定义 HTTP 技能不得通过全局 `registered_tools` 旁路进入客户应用 runtime。同一 Agent 被多个应用引用时，每个应用看到的技能和连接集合必须不同。

### FR-9 渠道绑定

| 项 | 说明 |
|---|---|
| 触发时机 | 创建渠道、切换渠道版本、入站消息 |
| 输入 | 应用 id、已发布应用版本、渠道提供商配置、凭据 |
| 输出 | 渠道记录应用绑定；每个入站事件保存应用 id/version |
| 执行方式 | 渠道创建同步；入站仍走 outbox + worker |
| 失败处理 | 目标应用未发布或版本无效则拒绝创建/切换；渠道禁用时入站事件标记不可用 |

渠道不得直接绑定 `agent_id`。应用发布不会静默改变已有渠道；切换绑定版本是显式、可审计操作。

### FR-10 会话与运行追溯

| 项 | 说明 |
|---|---|
| 触发时机 | 创建会话、提交 run、记录 trace |
| 输入 | 渠道/应用上下文 |
| 输出 | `runtime_conversations.application_id/application_version`、`runtime_runs` 中的应用快照、应用 trace |
| 执行方式 | 与创建/提交同事务 |
| 失败处理 | 缺少应用上下文的新渠道会话必须失败，不回退到裸 Agent |

`agent_id` 可作为从应用绑定派生的查询冗余字段保留，但不得作为渠道路由的唯一依据。应用 trace 至少记录应用 key/version、Agent id/version、技能 key、连接 key、结果码和耗时。

### FR-11 标准案例

| 项 | 说明 |
|---|---|
| 触发时机 | 启动 seed、浏览案例、复制案例 |
| 输入 | 代码内置应用模板、目标应用 key/name |
| 输出 | 不可变示例应用；用户拥有的复制应用 |
| 执行方式 | seed 幂等；复制单事务 |
| 失败处理 | seed 冲突不覆盖；示例直接编辑/删除返回 403；复制 key 冲突返回 409 |

示例应用带 `origin=example`、`template_key`、`template_version`、`immutable=true`。复制后 `origin=user`、`immutable=false`，保留来源信息用于 lineage；修改副本不影响示例。

### FR-12 应用列表与分页

| 项 | 说明 |
|---|---|
| 触发时机 | 打开应用目录/标准案例列表 |
| 输入 | page、page_size、状态、来源、关键词、归档标记 |
| 输出 | `items/total/page/page_size` |
| 执行方式 | 服务端分页 |
| 失败处理 | page/page_size 越界按 schema 校验拒绝 |

默认 `page_size=10`，最大 100。前端分页器使用 Ant Design 组件并与表格/列表底部对齐。

### FR-13 应用内部信息架构

应用详情固定为六个页签：

1. 应用概览
2. 智能体
3. 技能
4. 业务规则
5. 预览与调试
6. 客户渠道与发布

技能页使用 Ant Design Table，至少展示技能、类型、连接、启用状态、最近测试、发布检查与操作；编辑抽屉包含基本信息、连接、参数映射、结果映射、安全规则和连接测试。

### FR-14 权限与审计

| 操作 | 最低权限 | 审计动作示例 |
|---|---|---|
| 查看应用/技能/连接元数据 | Reader | 不记录读取审计，但鉴权 |
| 编辑应用/技能/规则 | Admin | `service_application.updated` |
| 保存/轮换连接凭据 | Admin | `service_application.connection.credential_configured`（不含值） |
| 发布/回滚/归档 | Admin | `service_application.published/rolled_back` |
| 切换渠道版本 | Admin | `channel.application_version_changed` |
| 复制示例 | Admin | `service_application.copied_from_example` |

所有资源按 tenant/business/workspace/application 隔离。跨作用域 id 必须表现为不存在。

### FR-15 Clean-break 删除

新代码和新 UI 中必须删除：

- `/service-providers` 与 `/service-scenarios` API、路由注册、服务、模型、测试。
- `/industry-packs/installations`、升级预览、升级应用、升级记录 API 和 UI。
- `ScenarioToolBridge`、Scenario handler、应用 `capabilities/scenarios/default_execution_order` v1 配置。
- 前端 `features/service-scenarios`、`IndustryCapabilitiesPage`、Provider/Scenario 类型和 client 函数。
- `/service-apps/industry` 路由，不提供重定向。

历史迁移 `0054`～`0057` 不修改；由新的 `0058` 破坏式迁移清理。

## 配置项

| 配置项 | 层级 | 默认值 | 说明 |
|---|---|---|---|
| `service_app_examples_enabled` | 全局 settings | `true` | 启动时幂等安装标准案例；关闭时仍保留已有案例 |
| `service_app_connection_timeout_seconds` | 全局 settings | `10` | 新连接默认超时；技能可覆盖但受上限约束 |
| `service_app_connection_timeout_max` | 全局 settings | `60` | 连接/技能超时硬上限 |
| `service_app_default_page_size` | 全局 settings | `10` | 应用列表默认分页大小 |
| `service_app_preview_write_enabled` | 全局 settings | `false` | 草稿预览是否允许执行写技能；默认只模拟，不产生外部写 |
| `service_app_credential_key_file` | 全局 settings | 复用既有 Vault 配置 | 连接凭据加密密钥文件；禁止提交 |

以上开关不用于启用旧 Scenario/Provider 兼容路径。clean-break 后不存在双轨开关。

## 非功能需求

- **隔离**：任何查询和运行时解析必须包含 tenant/business/workspace/application 条件；跨应用、跨租户资源表现为不存在。
- **安全**：凭据只存密文；API/日志/审计/发布 JSON/trace 不出现明文；HTTP 连接沿用工具网关的固定 endpoint、Header 校验、出站网络策略、响应大小和超时限制。
- **性能**：50 个技能、20 个连接以内的应用，发布检查与快照生成 P95 < 1 秒（不含外部连接测试）；运行时应用上下文解析 P95 < 100 ms。
- **一致性**：发布、回滚、渠道版本切换和入站事件固定版本必须使用事务；revision 冲突不得覆盖他人修改。
- **可用性**：前端所有用户文案走 i18n；表格和分页支持键盘操作、空态、加载态、错误态；中英文同步。
- **可维护性**：前端主应用页拆分；后端删除旧双轨模块；单文件不继续承载多个生命周期。
- **审计**：发布、回滚、连接凭据状态、渠道版本切换、示例复制必须审计；审计不记录敏感值。
- **部署**：quickstart 空库一次迁移和 seed 成功；生产升级前明确破坏式数据重置窗口，不支持滚动混部。

## 验收标准

| # | 场景 | 预期 |
|---|---|---|
| AC-1 | 新建应用并直接选择 Agent 发布版本 | 应用保存成功；详情显示绑定的 Agent 与版本；无场景/能力字段 |
| AC-2 | 应用 A、B 都配置 `order_lookup`，连接不同 URL/凭据 | 两个应用分别调用正确 endpoint；修改 A 不影响 B；日志不泄露凭据 |
| AC-3 | 同一 Agent 同时被 A、B 引用 | 在 A 的会话只出现 A 授权技能，在 B 只出现 B 授权技能；无法通过全局工具旁路 |
| AC-4 | 应用发布后修改草稿技能/连接 | 线上渠道运行仍使用已发布版本；UI 显示未发布变更；重新发布后使用新版本 |
| AC-5 | 回滚到历史版本 | 产生新的最高版本并指向 source version；新消息使用回滚版本；历史版本不被改写 |
| AC-6 | 渠道绑定应用已发布版本并接收消息 | 入站事件、会话和 run 都记录应用 id/version；会话可追溯到技能/连接 trace |
| AC-7 | 浏览并直接编辑标准案例 | 编辑/删除被拒绝；复制后得到完整可编辑应用；修改副本不影响标准案例 |
| AC-8 | 重启 quickstart，用户已修改复制应用 | seed 不覆盖用户应用；标准案例内容不重复创建 |
| AC-9 | 使用新 UI 完成一次应用配置 | 只出现服务应用、Agent、技能、应用连接和客户渠道主概念；旧中间概念不可见 |
| AC-10 | 访问旧 Provider/Scenario/Industry 升级/`service-apps/industry` 入口 | 路由/API/组件不存在或返回 404；无重定向与兼容层 |
| AC-11 | 空数据库启动并完成迁移/seed | `0058` 一次成功；标准案例生成；可创建、发布应用并接收渠道消息 |
| AC-12 | 对连接、发布、回滚、渠道版本切换执行审计检查 | 审计记录操作者、资源、版本和状态；任何位置无明文凭据 |
