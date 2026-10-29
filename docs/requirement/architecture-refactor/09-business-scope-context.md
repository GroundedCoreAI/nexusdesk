# 阶段三第一批：租户、业务与工作空间上下文

> 状态：已完成（数据面落地见 `10-resource-scope-data-plane.md`）  
> 日期：2026-10-28

## 1. 本批次目标

阶段三先建立统一的上下文边界，不立即把所有业务表改成三维主键。

```text
tenant_id
└── business_id
    └── workspace_id
```

含义：

- `tenant_id`：现有数据与身份的一级隔离边界。
- `business_id`：集团内的业务边界，例如 `customer-service`、`itsm`。
- `workspace_id`：业务内部的工作空间、团队或场景边界。

## 2. 已落地

### 2.1 稳定契约

`extension_contracts.BusinessScope` 已定义统一上下文模型。

平台上下文已支持可选的：

- `business_id`
- `workspace_id`

涉及：

- `ExecutionContext`
- `ToolExecutionContext`
- `PolicyContext`
- `Principal`

### 2.2 请求边界

集团入口根据业务路由前缀解析业务：

```text
/api/v1/customer-service/* → customer-service
```

工作空间通过可信请求头传递：

```text
X-Workspace-ID: default
```

该值只进入受控上下文，不允许由模型或业务请求体注入。

### 2.3 下游传播

业务上下文会进入：

- `Principal.execution_context()`
- Tool Gateway 的 `ToolExecutionContext`
- Policy Harness 的 `PolicyContext`
- `/me` 返回结果

## 3. 第二批：控制面持久化与校验

已新增 Alembic migration：

```text
0045_tenant_business_scopes
```

新增控制面表：

- `tenant_businesses`
- `tenant_workspaces`

应用启动时会把集团入口注册的业务写入当前租户，并创建 `default` 工作空间。请求进入业务路由后，会校验业务和可选工作空间是否属于当前租户且处于启用状态。

## 4. 当前安全边界

业务/工作空间控制面校验已完成，Agent、知识库、渠道等主要配置资源已接入数据面过滤；`workspace_id` 仍不是单独的完整授权结论。

因此：

- 现有数据库查询仍以 `tenant_id` 为准。
- 不能仅凭 `X-Workspace-ID` 绕过现有权限。
- 后续持久化批次必须校验业务和工作空间是否属于当前租户及主体。

## 5. 已完成的下一批

已处理业务资源绑定和数据面过滤：

1. 为 Agent、知识库、渠道等资源增加业务归属策略。
2. 将业务上下文传入资源服务。
3. 在不破坏租户兼容的前提下增加查询过滤。
4. 补充跨业务访问拒绝和迁移回归测试。
