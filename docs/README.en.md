# NexusDesk Documentation

[简体中文](README.md) · **English**

Documentation is grouped by purpose. The code and section 1 of each module README are the sources of current implementation status; actual CI results are the source of test coverage. Architecture designs and plans do not imply that every capability has been delivered. Historical delivery and validation snapshots are kept in the [archive](archive/README.en.md).

## Quick links

- [Project home](../README.md)
- [Onboarding guide](onboarding/README.en.md)
- [Platform guide](guides/platform.en.md)
- [Local development](development/local-development.en.md)

## Architecture and execution

| Document | Contents |
|---|---|
| [Module architecture](architecture/overview.en.md) | Module boundaries, dependencies, and platform responsibilities |
| [Agent execution platform v2](architecture/agent-execution-platform-v2.en.md) | Target architecture for the Agent execution platform |
| [Runtime documentation](architecture/runtime.en.md) | Agent Runtime, tool calls, and the standalone worker |
| [Streaming design](architecture/streaming-design.en.md) | Streaming execution and response protocol design |

## Usage and integration

| Document | Contents |
|---|---|
| [Platform guide](guides/platform.en.md) | Workbench, conversations, tickets, and platform operations |
| [Knowledge workspace](guides/knowledge-workspace.en.md) | Knowledge documents, chunks, publishing, and retrieval |
| [Open platform](guides/open-platform.en.md) | Application integration, channels, and open APIs |
| [Enterprise identity and embedded chat](guides/open-platform-identity.md) (Chinese) | Enterprise identity mapping, OIDC, and embedded chat |
| [Access control](guides/access-control.md) (Chinese) | Members, fixed roles, and the permission model |
| [Model gateway governance](guides/model-gateway-governance.en.md) | Model configuration, access keys, quotas, and cost governance |
| [Industry examples](guides/industry-examples.en.md) | Configuration and usage examples for different industries |

## Development

| Document | Contents |
|---|---|
| [Local development](development/local-development.en.md) | Dependencies, environment configuration, and startup |
| [Capability development and extension rules](development/module-development.en.md) | Module boundaries, shared contracts, and delivery rules |
| [Internationalization](development/internationalization.md) (Chinese) | Frontend localization conventions |
| [UI design system](development/ui-design-system.md) (Chinese) | Theme, layout, and component styling conventions |

## Deployment and operations

| Document | Contents |
|---|---|
| [Middleware guide](operations/middleware.en.md) | PostgreSQL, Milvus, and optional external service dependencies |
| [Database migrations](operations/database-migrations.en.md) | Alembic migrations, upgrades, and rollback boundaries |
| [Local administrator](operations/local-admin.md) (Chinese) | Local administrator accounts and permission operations |

## API reference

| Document | Contents |
|---|---|
| [API reference](reference/api.en.md) | API namespaces and reference entry points |

## Requirements and historical records

- Requirement lifecycle documentation: [Agent Memory](requirement/agent-memory/README.md), [Architecture Refactor](requirement/architecture-refactor/README.en.md), [Agent Execution Platform v2](requirement/agent-execution-platform-v2/README.en.md), [Agent Evaluation](requirement/agent-evaluation/01-p2-roadmap.md), [P0 Production Readiness](requirement/p0-production-readiness/README.md) (some documents are Chinese only)
- [Historical archive](archive/README.en.md): superseded implementation progress, early validation, and environment-specific records; these are not sources of current status
