# 行业 Pack 运行时 V1

> 状态：已落地开发版本，尚未完成生产验收
> 创建：2026-11-02
> 关联：
> - [多行业场景包](./industry-pack-v1.md)
> - [客服模块实施路线](./implementation-roadmap-v1.md)
> - [人工工作台业务上下文](./handoff-context-v1.md)

## 0. 本切片解决了什么

此前行业 Pack 只能编译为 `ScenarioConfig` 和 `ServiceApplicationConfig`，无法安装到租户，也没有统一的 Provider 注册表、模板升级和成熟度发布门禁。

本轮补齐了从“可编译资产”到“可安装、可配置、可升级、可检查”的运行时闭环：

1. 行业 Pack 可以安装为真实的场景草稿和服务应用草稿。
2. 业务对象、工具和人工队列可以通过统一注册表声明可用性。
3. 后续模板版本可以通过三方合并预览安全升级，不覆盖租户本地修改。
4. `alpha / beta / ga` 成熟度进入后端 readiness 与场景发布门禁。
5. 前端增加服务应用内部的“行业能力”管理页。

本切片仍然不是“生产可用”的完整交付。真实 Provider 调用、工具执行、真实渠道入站联调和生产数据验收仍待完成。

## 1. 目标与边界

### 1.1 目标

- 行业差异通过模板、配置和注册表表达，不在运行时写 `if industry` 或 `if pack_key` 业务分支。
- 安装和升级只修改草稿，不自动发布。
- 安装、升级、Provider 和 readiness 全部按租户、业务和空间作用域隔离。
- 冲突时保留本地配置并阻断升级应用。
- 发布检查由后端强制执行，前端只负责解释和引导。

### 1.2 非目标

- 不把行业 Pack 做成独立的市场、签名分发或外部制品仓库。
- 不在本轮实现真实 Provider 网络调用、凭证托管、健康检查和重试。
- 不自动发布安装后的场景或应用。
- 不提供升级回滚、冲突逐字段解决 UI 或自动迁移脚本。
- 不以模拟器和自动化测试替代真实渠道与生产数据验收。

## 2. 数据模型

迁移 `0057_industry_pack_runtime` 新增三个持久化表，均以
`tenant_id + business_id + workspace_id` 作为作用域：

### 2.1 `service_provider_registry`

统一保存三类接入能力：

- `object`：订单、发票、物流等业务对象数据来源。
- `tool`：查询、办理和外部系统调用能力。
- `human_queue`：人工承接队列。

关键字段包括 `provider_key / kind / name / enabled / config / source /
source_ref / revision`。同一作用域内 `kind + provider_key` 唯一，`kind` 只允许上述三类。

### 2.2 `industry_pack_installations`

保存一次行业 Pack 安装：

- Pack 标识、版本、摘要和成熟度。
- 安装生成的应用 key。
- 场景模板版本与模板摘要。
- 模板 key 到实际场景 key 的映射。
- 安装时的应用和场景基线快照。
- 安装状态与 revision。

同一作用域内 `pack_key + application_key` 唯一。

### 2.3 `industry_pack_upgrades`

保存升级预览和应用记录：

- 来源版本、目标版本与目标摘要。
- 合并计划、冲突路径和待写入的目标配置。
- `preview / clean / conflicted / applied / failed` 状态。
- 创建者和实际应用者、应用时间。

升级记录通过作用域复合外键关联安装记录，安装删除时级联删除升级记录。

## 3. Provider 注册表

### 3.1 API

```text
GET  /api/v1/service-providers
GET  /api/v1/service-providers/{kind}/{key}
POST /api/v1/service-providers
PUT  /api/v1/service-providers/{kind}/{key}
```

读取接口允许只读角色访问，新建和修改要求管理员权限。

### 3.2 行为

- 支持按类型筛选和按名称、标识、说明搜索。
- 新建时同一 `kind + key` 冲突返回 409。
- 更新必须携带当前 `revision`，过期写返回
  `service_provider_missing_or_revision_conflict`。
- `kind` 和 `key` 是稳定身份，不允许通过更新修改。
- 创建和更新分别记录审计事件
  `service_provider.created`、`service_provider.updated`。
- 安装 Pack 时按场景依赖幂等创建未启用的占位 Provider，不覆盖管理员已配置的同身份记录。
- 模板升级引入新的对象、工具或人工队列时，同样幂等创建未启用的 Provider 占位。
- readiness 只读取当前作用域中已启用的 Provider 身份。

注册表当前保存的是“能力声明和连接配置”，不是完整的连接器运行时。真实鉴权、调用、超时、重试和健康检查仍需由后续执行层补齐。

## 4. 行业 Pack 安装

### 4.1 API

```text
GET  /api/v1/industry-packs
GET  /api/v1/industry-packs/{pack_key}
GET  /api/v1/industry-packs/installations
POST /api/v1/industry-packs/{pack_key}/install
POST /api/v1/industry-packs/installations/{id}/upgrade-preview
POST /api/v1/industry-packs/installations/{id}/upgrade
```

安装请求示例：

```json
{
  "pack_version": "1.0.0",
  "application_key": "content-community-service",
  "install_scenarios": true
}
```

`install_scenarios=true` 安装模板中的全部场景；为 `false` 时只安装应用蓝图引用的场景。请求未提供时默认安装全部场景。

### 4.2 安装结果

- 为每个目标场景创建真实的 `service_scenarios` 草稿。
- 创建真实的服务应用草稿，并将蓝图场景引用映射到已安装场景。
- 将 Pack 来源、模板版本、模板摘要和成熟度写入场景元数据。
- 保存安装基线快照，供后续三方合并使用。
- 为场景依赖的对象、工具和人工队列创建未启用 Provider 占位。
- 不自动发布场景或应用。

### 4.3 幂等与冲突

- 同一作用域、同一 Pack、同一应用 key 且摘要一致时，返回已有安装，`created=false`。
- 同一安装身份但摘要不同，返回
  `industry_pack_installation_conflict`。
- 同标识场景已存在且来源元数据匹配时，复用该场景，不覆盖其草稿。
- 同标识场景来源不匹配时，返回
  `industry_pack_scenario_collision`。
- 同标识服务应用已存在时，返回
  `industry_pack_application_conflict`，不会静默覆盖。

## 5. 模板升级与三方合并

### 5.1 三方定义

- `base`：安装时保存的模板基线。
- `local`：租户当前场景或应用草稿。
- `incoming`：目标 Pack 版本编译出的新模板。

### 5.2 合并规则

- 字段路径级比较 `base / local / incoming`。
- `entries / facts / decisions / recommendations / handlers` 以 `key` 作为列表身份。
- `options` 以 `value` 作为身份。
- `fallback_order` 和其他普通列表按稳定 JSON 值合并。
- 不使用数组下标作为业务身份。
- 仅本地修改时保留本地值。
- 仅模板修改时采用新模板值。
- 双方没有冲突的修改可以自动合并。
- 双方修改同一路径时记录冲突并保留 local。
- 合并结果必须重新通过 `ScenarioConfig` 校验；校验失败时回退 local 并标记 `blocked`。
- 应用配置也参与升级预览；无法安全合并时阻断应用级升级。

### 5.3 预览与应用

- `upgrade-preview` 只生成计划并写入 `industry_pack_upgrades`，不修改场景或应用草稿。
- 预览记录状态为 `clean / conflicted / blocked`。
- 只有 `clean` 的预览允许应用升级。
- 应用升级时再次校验场景和应用 `draft_revision`；预览后发生漂移返回
  `industry_pack_upgrade_preview_stale`。
- 应用成功后更新草稿、安装版本、基线快照和升级记录，但不自动发布。
- 冲突预览、阻断预览和过期预览都不能部分写入。

## 6. 成熟度与发布门禁

readiness 新增两项 Pack 场景检查：

- `template-maturity`
- `provider-capability`

### 6.1 模板成熟度

| 成熟度 | 发布判定 |
|---|---|
| `alpha` | 必阻断，只允许验证和模拟 |
| `beta` | 应用存在 `canary` 客户渠道时放行；否则阻断 |
| `ga` | 正常参与发布检查 |

场景级发布接口还会直接检查 Pack 元数据中的成熟度。`alpha` 场景返回：

```text
409 scenario_alpha_publish_forbidden
```

因此不能通过单独发布场景绕过应用 readiness。

`config.industry_pack` 属于安装器维护的保留元数据。普通场景新建接口拒绝注入该字段；
已安装场景的更新接口只允许保持原有元数据不变，不能把 `alpha` 改为 `ga` 绕过门禁。

### 6.2 Provider 能力

对 Pack 场景，readiness 会检查：

- `object.provider` 对应的 `object:{provider}`。
- 已启用 handler 的 `tool` 对应的 `tool:{tool}`。
- 人工 handler 或人工能力队列对应的 `human_queue:{queue}`。

缺失时阻断发布。检查文案只说明缺少多少项业务数据能力，不向操作者或客户泄露 Provider key、工具标识、队列名等内部实现。

普通非 Pack 场景不启用这两项额外门禁，保持原有 readiness 行为。

## 7. 前端

新增路由：

```text
/service-apps/industry
```

入口位于“服务应用”内部，不新增一级导航，也不恢复独立 `/service-scenarios` 页面。

页面包含三部分：

- **行业模板**：查看 Pack、成熟度、对象和场景数量，安装为草稿。
- **接入能力**：按对象、工具、人工队列筛选和编辑 Provider。
- **升级记录**：查看安装，执行升级预览，展示冲突路径并应用无冲突升级。

readiness 面板同步展示 `template-maturity` 和 `provider-capability` 检查，使前后端展示口径一致。

## 8. 人工工作台的关系

人工工作台的真实场景上下文聚合此前已经完成：`GET /api/v1/handoffs/{id}/context`
可以返回场景、对象、事实、决策、运行和路由证据，并在服务端完成权限裁剪和脱敏。

本轮补的是行业 Pack、Provider 和发布门禁，不重复实现工作台上下文。仍需完成的是模拟/平台 API 之外的**真实渠道 handoff 入站联调**。

## 9. 验证覆盖

代码库当前包含以下自动化覆盖：

```text
backend/tests/test_industry_pack_migrations.py
backend/tests/test_industry_pack_merge.py
backend/tests/test_industry_pack_runtime.py
backend/tests/test_industry_pack_release_gate.py
backend/tests/test_service_application_readiness.py
backend/tests/test_handoff_context.py
```

覆盖重点包括：

- 迁移创建、约束、索引与可逆性。
- Provider CRUD、revision 冲突和权限。
- Pack 安装幂等、场景/应用草稿和 Provider 占位。
- 三方合并的自动合并、冲突、删除和校验失败。
- 升级预览、应用与 revision 漂移。
- `alpha / beta / ga` 和 Provider 缺失门禁。
- 人工工作台上下文聚合。

这些测试证明开发切片具备基本回归保护，不等同于生产验收。

## 10. 仍未完成

1. **真实 Provider 与工具执行**：注册表尚未连接真实业务系统，也没有凭证、重试、限流、超时、健康检查和可观测性闭环。
2. **真实渠道入站联调**：人工工作台上下文已可用，但企微/飞书等真实渠道从入站、场景执行到 handoff 的全链路仍需验收。
3. **生产数据验收**：需要真实订单、账号、退款、物流和人工队列数据验证权限、脱敏、幂等、失败和结果未知语义。
4. **升级治理**：尚缺升级回滚、冲突逐字段解决、批量升级和灰度升级策略。
5. **Pack 分发**：当前仅支持内置 Pack 目录，尚未实现外部 Pack 包安装、签名、来源验证和版本市场。
6. **生产发布运营**：需要容量、监控、告警、审计留存、灾备和发布回滚演练。

因此当前结论是：**能力闭环已落地到开发版本，可进入联调和验收；不能据此宣称生产可用。**
