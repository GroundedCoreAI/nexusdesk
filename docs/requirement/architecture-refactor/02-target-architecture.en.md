# 02. Target Architecture

## Top-level layout

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

## Layer responsibilities

### Core Platform

Shared infrastructure for all business capabilities: runtime lifecycle, model and tool dispatch, authorization and risk controls, plugin registration and lifecycle, audit, events, persistence, and observability.

### Extension Contracts

Stable protocols only. It must not depend on applications or concrete business implementations. It contains Tool, Capability, Policy, Event, UI Extension, and Runtime Binding contracts.

### Business Capabilities

Own domain rules, domain services, domain events, and business data access. Capabilities contribute tools, events, and UI through contracts and do not mutate Runtime internals directly. Controlled external-plugin implementations belong to the relevant Business Capability or application binding; there is no separate top-level `extensions/` directory.

### Applications

Own startup, routing, dependency composition, workers, and initialization scripts. Applications may depend on the platform and business capabilities; the platform and business capabilities must not depend on a concrete application composition root.

## Dependency direction

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
