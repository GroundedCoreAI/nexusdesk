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

## 4. Current conclusion

The main physical directory migration has been completed. `agent_platform/modules`, `apps`, `integrations`, and `platform` are no longer retained as runtime directories. Final regression testing, legacy documentation cleanup, and architecture-gate confirmation remain.

See `07-acceptance-report.md` for the current status.
