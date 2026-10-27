# 04. Boundary and Contract Rules

## Allowed dependencies

| Source | May depend on |
|---|---|
| `extension_contracts` | Standard-library types, framework-neutral types, and base models |
| `core_platform` | `extension_contracts` and internal platform services |
| `business_capabilities` | `extension_contracts` and ports/platform services exposed by Core Platform |
| `applications` | All three layers for composition and adaptation |

## Forbidden dependencies

- `extension_contracts` must not depend on `applications`, `business_capabilities`, or concrete platform implementations.
- `core_platform` must not depend on a concrete application composition root.
- `business_capabilities` must not depend on application routes or startup modules.
- Business capabilities must not write the Tool Operation Ledger directly; they must use Tool Gateway.
- Business capabilities must not mutate internal plugin-registry state directly.
- Legacy namespaces must not be reintroduced through permanent compatibility packages.

## Extension integration

Business capabilities and external plugins integrate through:

- Capability Manifest
- Tool Definition / Contribution
- Event Envelope / Subscription
- Policy Declaration
- UI Extension Manifest
- Runtime Bindings

Applications bind implementations into the runtime. Extension Platform validates manifests, compatibility, lifecycle, and controlled startup.

## Data and migrations

This directory refactor does not change business-data semantics. Any database schema change requires a new Alembic migration; already-applied migrations must not be edited.
