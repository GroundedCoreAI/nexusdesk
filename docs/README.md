# NexusDesk 文档

**简体中文** · [English](README.en.md)

本目录按文档用途分类。当前实现以代码和各模块 README 的第 1 节为准，测试覆盖以 CI 的实际运行结果为准；架构设计和规划内容不代表对应能力已经全部交付。历史交付与验证快照统一放在[归档目录](archive/README.md)。

## 快速入口

- [项目主页](../README.zh-CN.md)
- [快速开始](getting-started/quickstart.md)
- [平台使用说明](guides/platform.md)
- [本地开发环境](development/local-development.md)

## 架构与执行机制

| 文档 | 内容 |
|---|---|
| [模块架构](architecture/overview.md) | 模块划分、依赖关系与平台边界 |
| [Agent 执行平台 v2](architecture/agent-execution-platform-v2.md) | Agent 执行平台目标架构设计 |
| [Runtime 文档](architecture/runtime.md) | Agent Runtime、工具调用与独立 Worker |
| [流式响应设计](architecture/streaming-design.md) | 流式执行与响应协议设计 |

## 使用与接入

| 文档 | 内容 |
|---|---|
| [平台使用说明](guides/platform.md) | 工作台、会话、工单与平台功能操作 |
| [知识库工作台](guides/knowledge-workspace.md) | 知识文档、分片、发布与检索 |
| [开放平台](guides/open-platform.md) | 应用接入、渠道与开放接口 |
| [企业身份与嵌入聊天](guides/open-platform-identity.md) | 企业身份映射、OIDC 与嵌入聊天 |
| [用户权限](guides/access-control.md) | 成员、固定角色与权限模型 |
| [模型网关治理](guides/model-gateway-governance.md) | 模型配置、访问密钥、配额与费用治理 |
| [行业示例](guides/industry-examples.md) | 不同行业的配置与使用示例 |

## 开发规范

| 文档 | 内容 |
|---|---|
| [本地开发环境](development/local-development.md) | 依赖、环境配置与启动方式 |
| [模块独立开发与扩展规范](development/module-development.md) | 模块边界、统一契约与交付规则 |
| [国际化](development/internationalization.md) | 前端多语言约定 |
| [UI 设计系统](development/ui-design-system.md) | 主题、布局与组件样式约定 |

## 部署与运维

| 文档 | 内容 |
|---|---|
| [中间件说明](operations/middleware.md) | PostgreSQL、Milvus 及可选外部服务依赖 |
| [数据库迁移](operations/database-migrations.md) | Alembic 迁移、升级与回滚边界 |
| [本地管理员](operations/local-admin.md) | 本地管理员账号与权限操作 |

## API 参考

| 文档 | 内容 |
|---|---|
| [API 说明](reference/api.md) | API 命名空间与接口入口 |

## 需求与历史记录

- 需求全流程文档：[Agent Memory](requirement/agent-memory/README.md)、[架构重构](requirement/architecture-refactor/README.md)、[Agent 执行平台 v2](requirement/agent-execution-platform-v2/README.md)、[Agent Evaluation](requirement/agent-evaluation/01-p2-roadmap.md)、[P0 生产就绪](requirement/p0-production-readiness/README.md)、[服务应用平台 v2](requirement/service-application-platform-v2/README.md)
- [历史文档归档](archive/README.md)：已被取代的实施进度、早期验证和特定环境记录，不作为当前状态依据
