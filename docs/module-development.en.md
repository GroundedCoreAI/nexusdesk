# Capability Development and Platform Extension Rules

These rules apply to business capabilities under `backend/src/agent_platform/business_capabilities`, platform services under `backend/src/agent_platform/core_platform`, and their frontend surfaces. See the [Architecture Index](architecture.en.md). These are target rules; they do not claim that every existing dependency has already been fully decoupled.

## 1. Development unit and layers

The independent unit is a business capability or platform service with a clear boundary, replaceable dependencies, and independent acceptance tests. The initial deployment remains a modular monolith.

| Layer | Responsibility |
|---|---|
| API / UI | Input validation, authentication context, protocol conversion, and presentation |
| Domain service | State transitions, invariants, and use-case orchestration |
| Ports and contracts | Protocols, DTOs, errors, and events without exposing another domain's rows |
| Repository / adapter | Concrete PostgreSQL, HTTP, model, or channel implementations |
| Composition root | Dependency injection, configuration, and lifecycle |

Extract `contracts.py`, `ports.py`, `repository.py`, and `adapters/` according to complexity. Do not create empty layers for simple capabilities. The current composition is owned by `applications/customer_service/platform_services.py` and Runtime composition.

## 2. Trusted execution context

`ExecutionContext` contains tenant, actor, roles/scopes, trace/request IDs, optional conversation/run IDs, deadline, and cancellation. Identity and tenant are resolved by the server; the model must not provide them. Resource ownership must be verified.

The context must not contain plaintext secrets, channel tokens, or client-supplied permissions. Workers use restricted service identities. Cancellation and deadlines map separately to in-process requests and durable tasks.

## 3. Ownership and transactions

Each README declares ownership. Commands modify owned data and query ports provide reads; capabilities must not update another capability's tables directly. Observability consumes read-only projections and cannot change business state.

Existing shared-transaction exceptions remain documented until they can be safely wrapped by ports. Do not break atomic application work units merely to create a formal boundary. Database changes require new Alembic migrations and must not edit applied migrations.

## 4. Commands, queries, events, and errors

Commands carry DTOs, resource IDs, version conditions, and required idempotency keys. Queries use trusted resource scope and stable cursors. Public DTOs must not expose database row structures. Events use a versioned envelope and consumers must be idempotent. Errors expose stable categories and codes, not internal stack traces.

## 5. Cross-layer ownership

- `agent_config`: Agent definition, publishing, and versions.
- `agent_runtime`: Run lifecycle and total budget.
- `tool_gateway`: Tool definitions, execution, and operation records.
- `policy_harness`: Authorization, risk, confirmation, and constraints.
- `model_gateway`: Model profiles, calls, and usage.
- `knowledge`: Documents, indexing, retrieval, and citations.
- `conversation` / `channel`: Messages, sessions, receiving, and delivery.
- `customer_service` / `human_handoff`: Tickets, confirmation, transfer, and assignment.
- `observability`: Read-only projections and audit queries.

## 6. Delivery process

1. Define scope, dependencies, invariants, and the smallest DTO/Protocol.
2. Provide fake adapters, error cases, and contract tests.
3. Implement domain rules, persistence, and adapters before API/UI wiring.
4. Validate compatibility in the composition root.
5. Update current-state documentation, configuration, test locations, and runbooks.

## 7. Acceptance

Cover normal, rejection, conflict, cancellation, and failure paths. Use PostgreSQL for transaction, uniqueness, locking, and tenant-isolation checks. Use simulated external services for throttling, disconnects, timeouts, duplicates, and unknown results. UI changes must verify permissions, error presentation, and the complete business flow.
