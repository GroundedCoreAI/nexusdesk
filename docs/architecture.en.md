# NexusDesk Architecture and Capability Planning Index

NexusDesk is a Python modular monolith with an asynchronous LangGraph Runtime, PostgreSQL, and a React console. The code is organized into four layers: Core Platform, Extension Contracts, Business Capabilities, and Applications. The refactor decisions and acceptance evidence are documented in [Architecture Refactor Requirements](requirement/architecture-refactor/README.md).

## Four-layer architecture

```text
agent_platform/
├── core_platform/
│   ├── agent_runtime/
│   ├── tool_gateway/
│   ├── policy_harness/
│   ├── extension_platform/
│   └── platform_services/
├── extension_contracts/
├── business_capabilities/
│   └── sample_operations/  # sample capability implementation
└── applications/
```

- **Core Platform**: Runtime, Tool Gateway, Policy, plugin lifecycle, and shared platform services.
- **Extension Contracts**: Tool, capability, policy, event, UI Extension, and Runtime Binding contracts.
- **Business Capabilities**: Customer service, approval, knowledge, memory, and other domains.
- **Applications**: API, workers, seeders, and dependency composition roots.

## Capability and platform-service index

See the linked README files in the Chinese source document for the current detailed planning index. The planning documents cover current status, ownership, contracts, boundaries, constraints, UI, implementation stages, and acceptance criteria.

The shared development and extension rules are documented in [Capability Development and Platform Extension Rules](module-development.en.md). Operational documentation is available in [Platform Guide](platform.md), [Runtime](runtime.md), and [Platform Validation](platform-validation.md).

## Architecture rules

The diagram and planning tables describe collaboration responsibilities, not direct imports. Models and tools are injected through composition roots. Applications compose the system but do not own platform or domain implementations. The system remains a modular monolith; no immediate microservice split is required.
