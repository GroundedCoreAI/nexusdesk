# 01. Background and Goals

## Background

The early NexusDesk layout grouped code under `apps`, `modules`, `integrations`, and `platform`. As Agent Runtime, Tool Gateway, Policy Harness, plugin lifecycle management, and business capabilities grew, these names stopped expressing clear ownership boundaries.

The main problems were:

1. Platform, business, and application-composition code were mixed together.
2. Extension contracts were not visibly separated from implementations.
3. `modules` represented both business domains and platform capabilities.
4. Application entry points could accumulate domain logic.
5. The documented target architecture drifted from the actual directories.

## Goals

- Express stable architecture boundaries through four top-level directories.
- Preserve the modular-monolith deployment model and business behavior.
- Place Runtime, Tool Gateway, Policy, and Extension Platform under Core Platform.
- Place protocols, DTOs, events, policy, and UI extension models under Extension Contracts.
- Place customer service, approval, knowledge, and memory code under Business Capabilities.
- Place API, workers, seeders, and composition roots under Applications.
- Remove runtime dependencies on legacy namespaces and directories.
- Prevent future drift with architecture tests, import scans, and regression tests.

## Non-goals

- No microservice split.
- No plugin marketplace, SDK ecosystem, or new business domain.
- No change to the business database model; database changes still require Alembic migrations.
- No long-term compatibility aliases for the old directories.
