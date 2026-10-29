# NexusDesk Architecture Refactor and Directory Consolidation

> Status: In progress
> Started: 2026-10-27
> Working branch: `refactor/plugin-platform`

## 1. Goal

This directory records the decisions, migration work, and acceptance evidence for consolidating NexusDesk from the historical `apps / modules / integrations / platform` layout into four target layers:

```text
NexusDesk
├── Core Platform
├── Extension Contracts
├── Business Capabilities
└── Applications
```

This is a **large internal refactor of a modular monolith**. It does not change the deployment model, split services, or expand the business scope.

## 2. Documentation boundary

- `docs/`: current architecture, feature, and operational documentation.
- This directory: background, target architecture, migration mapping, boundary rules, and acceptance evidence for this refactor.
- Feature documentation remains in the `docs/` root or its existing requirement directory and is not duplicated here.

## 3. Document set

| File | Content | Status |
|---|---|---|
| `01-background-and-goals.md` | Background, problems, and goals | Created |
| `02-target-architecture.md` | Four-layer target architecture | Created |
| `03-directory-migration-map.md` | Old-to-new directory mapping | Created |
| `04-boundary-and-contracts.md` | Dependency and extension-contract rules | Created |
| `05-migration-plan.md` | Migration order and operating principles | Created |
| `06-acceptance-plan.md` | Code, test, and documentation acceptance criteria | Created |
| `07-acceptance-report.md` | Current acceptance results and open items | Initial record |
| `08-group-application-and-business-registry.md` | Phase 2 group entrypoint and business registry | Complete |
| `09-business-scope-context.md` | Phase 3 tenant, business, and workspace context | Complete |
| `10-resource-scope-data-plane.en.md` | Phase 3 core resource data-plane filtering | Complete |

## 4. Current conclusion

The main physical directory migration has been completed. `agent_platform/modules`, `apps`, `integrations`, and `platform` are no longer retained as runtime directories. Phase 2 is complete, and Phase 3 has completed the context boundary plus data-plane filtering for the main Agent, knowledge-base, and channel configuration resources.

Upgrade note: Python startup modules have moved from `agent_platform.apps.*`
to `agent_platform.applications.*`. Quickstart/API may embed Workers in the API
process; production uses dedicated Worker entrypoints such as
`python -m agent_platform.applications.worker.memory` with
`AGENT_EMBEDDED_WORKER=false`.

See `07-acceptance-report.md` for the current status.
