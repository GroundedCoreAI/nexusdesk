# 04. 边界与契约规则

## 允许依赖

| 来源 | 可依赖 |
|---|---|
| `extension_contracts` | 标准库、框架无关类型和基础数据模型 |
| `core_platform` | `extension_contracts`、平台内部服务 |
| `business_capabilities` | `extension_contracts`、Core Platform 提供的端口和基础服务 |
| `applications` | 上述三层，用于组合和适配 |

## 禁止依赖

- `extension_contracts` 不得依赖 `applications`、`business_capabilities` 或具体平台实现。
- `core_platform` 不得依赖具体 Application 组合根。
- `business_capabilities` 不得依赖 Application 路由或启动模块。
- 业务能力不得直接写 Tool Operation Ledger；必须经过 Tool Gateway。
- 业务能力不得直接操纵插件注册表内部状态。
- 旧命名空间不得通过长期兼容包重新引入。

## 扩展接入

业务能力或外部插件通过以下契约接入：

- Capability Manifest
- Tool Definition / Contribution
- Event Envelope / Subscription
- Policy Declaration
- UI Extension Manifest
- Runtime Bindings

Application 负责把实现绑定到运行时；Extension Platform 负责校验 manifest、兼容性、生命周期和受控启动。

## 数据与迁移

本次目录重构不改变已有业务数据语义。任何新增或调整数据库结构必须新增 Alembic migration，不允许修改已经应用的历史迁移。
