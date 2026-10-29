# 阶段三最后一批：核心资源数据面过滤

> 状态：已完成（代码落地，PostgreSQL 集成回归待环境恢复后执行）  
> 日期：2026-10-28

## 1. 本批次目标

把已经在请求边界解析并校验的 `BusinessScope` 传入核心业务资源的数据访问层，形成：

```text
tenant_id
  + business_id
  + workspace_id（请求明确指定时）
```

本批次不改变部署形态，也不处理 Kubernetes 节点、资源池或 ToC/ToB 部署隔离。

## 2. 已落地资源

`0046_resource_scope_columns` 为以下配置资源增加归属字段和联合索引：

- `agents`
- `knowledge_bases`
- `knowledge_documents`
- `knowledge_folders`
- `channels`

字段默认值保持历史单业务兼容：

```text
business_id = customer-service
workspace_id = default
```

## 3. 数据访问改造

已接入统一的请求上下文 SQL 辅助函数：

- `resource_scope_clause()`
- `resource_scope_values()`

已覆盖：

- Agent 列表、详情、目录、创建、更新、发布、回滚、归档、删除和版本读取。
- 知识库、文档、文件夹、上传、搜索、检索和向量索引的主要访问路径。
- 渠道列表、创建、配置更新、启停、Token 轮换、投递与入口校验。

没有 HTTP 业务上下文的 seed、worker 和历史服务调用仍按原有 `tenant_id` 行为运行；后台任务使用数据库资源 ID 和租户边界继续处理多业务任务。

## 4. 兼容与安全规则

1. `tenant_id` 仍然是一级隔离边界。
2. 业务路由解析出的 `business_id` 不能由请求体或模型覆盖。
3. 未指定 `X-Workspace-ID` 时只按业务过滤，兼容业务管理员查看多个工作空间。
4. 创建资源始终写入可信上下文；无上下文时使用 `customer-service/default` 兼容默认值。
5. 跨业务或跨工作空间读取、更新、删除会表现为资源不存在或业务错误，不泄露其他范围资源。

## 5. 验证

已通过：

- Ruff
- `compileall`
- 非 PostgreSQL 测试：`360 passed, 341 deselected`
- 作用域单元测试：`3 passed`
- Alembic head：`0046_resource_scope_columns`

本地 PostgreSQL 集成测试已尝试执行，但当前配置的 `127.0.0.1:5433` 实例未启动（`ConnectionRefusedError`），不是代码测试结论。

## 6. 明确未覆盖范围

本批次完成的是 Agent、知识库、渠道等主要配置资源的数据面接入。会话、工单、Memory、评估及其历史领域表的三维过滤仍属于后续数据面完善工作。
