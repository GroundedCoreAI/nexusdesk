# 阶段二：集团统一入口与业务注册机制

> 状态：已完成  
> 日期：2026-10-28

## 1. 目标

阶段二不做 Kubernetes、节点池、资源池或 ToC/ToB 部署隔离，只解决一个问题：

> 一个进程内由集团统一入口装配多个业务，多个业务共用同一套 Core Platform Runtime。

## 2. 实现

新增统一入口：

```text
agent_platform.applications.group.main
```

新增应用装配层：

```text
agent_platform/applications/application_factory.py
agent_platform/applications/business_registry.py
agent_platform/applications/group/
```

业务通过 `BusinessApplication` 注册以下信息：

- `business_id`
- 展示名称
- API 路由前缀
- 业务路由注册函数
- 业务自有的可信扩展绑定函数

当前已注册两个业务：

```text
customer-service
└── /api/v1/customer-service/*

itsm
└── /api/v1/itsm/*
```

集团入口提供：

```text
GET /api/v1/businesses
```

用于返回当前进程已注册的业务清单。

ITSM 当前是最小可运行业务应用骨架，用于验证第二个业务可以独立注册路由并复用同一个 Runtime；ITSM 领域功能不在本阶段展开。

## 3. 兼容策略

原入口仍然保留：

```text
agent_platform.applications.customer_service.main
```

该入口继续使用历史路径，例如：

```text
/api/v1/health
/api/v1/agents
```

它和集团入口复用同一个 `application_factory` 和同一个 `platform_runtime`，没有复制 Runtime 生命周期、Worker 启停或异常处理逻辑。

## 4. 后续扩展 ITSM

ITSM 后续只需要在现有 `BusinessApplication` 基础上增加自己的领域路由和能力绑定：

```python
BusinessRegistry(
    (
        customer_service_application("/customer-service"),
        itsm_application("/itsm"),
    )
)
```

本阶段不引入 `business_id` 数据字段，也不改变现有租户、权限和数据库模型。业务上下文与数据范围在阶段三处理。
