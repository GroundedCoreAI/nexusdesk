# Phase 3 Final Batch: Resource Data-Plane Scoping

> Status: Implemented (PostgreSQL integration regression is pending environment recovery)  
> Date: 2026-10-28

## 1. Goal

Connect the validated `BusinessScope` to the core resource data plane:

```text
tenant_id
  + business_id
  + workspace_id (when explicitly selected)
```

This batch does not change deployment topology and does not cover Kubernetes node pools or ToC/ToB deployment isolation.

## 2. Resources

Migration `0046_resource_scope_columns` adds ownership columns and composite indexes to:

- `agents`
- `knowledge_bases`
- `knowledge_documents`
- `knowledge_folders`
- `channels`

Legacy-compatible defaults are:

```text
business_id = customer-service
workspace_id = default
```

## 3. Data-access changes

The resource services now use:

- `resource_scope_clause()`
- `resource_scope_values()`

Coverage includes Agent management, knowledge workspace/retrieval/vector access, and channel management plus ingress authorization. Seed and worker calls without an HTTP scope retain their historical tenant-level behavior.

## 4. Compatibility and security rules

1. `tenant_id` remains the primary isolation boundary.
2. `business_id` comes from the trusted route scope, not request bodies or model output.
3. Without `X-Workspace-ID`, queries are scoped to the business and remain compatible with multi-workspace administrators.
4. New resources use the trusted scope; context-free legacy callers use `customer-service/default`.
5. Cross-business or cross-workspace access resolves as unavailable rather than exposing another scope.

## 5. Verification

Passed:

- Ruff
- `compileall`
- Non-PostgreSQL suite: `360 passed, 341 deselected`
- Scope unit tests: `3 passed`
- Alembic head: `0046_resource_scope_columns`

PostgreSQL integration tests were attempted, but the configured local `127.0.0.1:5433` instance was not running (`ConnectionRefusedError`).

## 6. Explicitly out of scope

This batch covers the main Agent, knowledge-base, and channel configuration resources. Three-dimensional filtering for conversations, tickets, Memory, evaluation, and other domain tables remains a later data-plane hardening task.
