# 01. 背景与目标

## 背景

NexusDesk 早期代码按 `apps`、`modules`、`integrations` 和 `platform` 横向堆叠。随着 Agent Runtime、Tool Gateway、Policy Harness、插件生命周期和业务能力持续增加，目录名称已经不能准确表达职责边界。

主要问题：

1. 平台能力、业务能力和应用组合代码混在相邻目录中。
2. 扩展契约与具体实现的边界不够明显。
3. `modules` 既表示业务模块，又承载 Runtime、模型网关和工具网关等平台能力。
4. 应用入口容易反向承载领域逻辑。
5. 文档中的目标架构与实际目录逐步偏离。

## 重构目标

- 用四个顶层目录表达稳定的架构边界。
- 保持当前模块化单体部署方式和业务行为不变。
- 将 Runtime、Tool Gateway、Policy、Extension Platform 收入 Core Platform。
- 将协议、DTO、事件、策略和 UI 扩展模型集中到 Extension Contracts。
- 将客服、审批、知识、记忆等领域代码收入 Business Capabilities。
- 将 API、Worker、Seed 和组合根收入 Applications。
- 消除旧命名空间和旧目录的运行时依赖。
- 用架构测试、导入扫描和完整回归测试防止目录再次发散。

## 非目标

- 不拆分微服务。
- 不新增插件市场、SDK 生态或新的业务领域。
- 不改变数据库业务模型；数据库变更仍必须通过 Alembic。
- 不通过兼容别名长期保留旧目录。
