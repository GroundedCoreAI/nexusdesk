# 02. 目标架构

## 顶层结构

```text
agent_platform/
├── core_platform/
│   ├── agent_runtime/
│   ├── tool_gateway/
│   ├── policy_harness/
│   ├── extension_platform/
│   └── platform_services/
│       ├── access_control/
│       ├── identity/
│       ├── integrations/
│       ├── model_gateway/
│       ├── observability/
│       ├── persistence/
│       ├── secrets/
│       └── storage/
│
├── extension_contracts/
├── business_capabilities/
│   ├── customer_service/
│   ├── approval/
│   ├── knowledge/
│   ├── memory/
│   ├── sample_operations/
│   └── other domain capabilities
│
├── applications/
│   ├── customer_service/
│   └── worker/
│
```

## 层职责

### Core Platform

提供所有业务能力共享的运行基础设施：Runtime 生命周期、模型和工具调度、授权与风险控制、插件注册和生命周期、审计、事件、持久化及观测。

### Extension Contracts

只定义稳定协议，不依赖 Application 或具体业务实现，包括 Tool、Capability、Policy、Event、UI Extension 和 Runtime Bindings。

### Business Capabilities

拥有领域规则、领域服务、领域事件和业务数据访问。业务能力通过契约向平台贡献工具、事件和 UI，不直接修改 Runtime 内部状态。外部插件的受控实现归入对应 Business Capability 或应用绑定，不再保留独立顶层 `extensions/` 目录。

### Applications

负责启动、路由、依赖组装、Worker 和初始化脚本。Applications 可以依赖平台和业务能力，但平台和业务能力不能依赖具体 Application 组合根。

## 依赖方向

```text
Applications
    ├── Core Platform
    ├── Extension Contracts
    └── Business Capabilities

Business Capabilities
    ├── Extension Contracts
    └── Core Platform ports/services

Core Platform
    └── Extension Contracts

Extension Contracts
    └── framework-independent types only
```
