# Phase 3 Batch 1: Tenant, Business, and Workspace Context

> Status: Complete (data-plane implementation is documented in `10-resource-scope-data-plane.en.md`)  
> Date: 2026-10-28

## 1. Goal of this batch

Phase 3 first establishes a unified context boundary. It does not immediately change every business table to a three-dimensional key.

```text
tenant_id
└── business_id
    └── workspace_id
```

Meaning:

- `tenant_id`: the existing first-level boundary for data and identity.
- `business_id`: a business boundary inside a group, such as `customer-service` or `itsm`.
- `workspace_id`: a workspace, team, or scenario boundary inside a business.

## 2. Implemented

### 2.1 Stable contracts

`extension_contracts.BusinessScope` defines the shared context model.

The platform context now supports optional:

- `business_id`
- `workspace_id`

The fields are propagated through:

- `ExecutionContext`
- `ToolExecutionContext`
- `PolicyContext`
- `Principal`

### 2.2 Request boundary

The group entrypoint resolves the business from the route prefix:

```text
/api/v1/customer-service/* → customer-service
```

The workspace is carried by a trusted request header:

```text
X-Workspace-ID: default
```

The value enters only the controlled context and cannot be injected by the model or a business request body.

### 2.3 Downstream propagation

The business context reaches:

- `Principal.execution_context()`
- Tool Gateway `ToolExecutionContext`
- Policy Harness `PolicyContext`
- the `/me` response

## 3. Batch 2: Durable control plane and validation

The following Alembic migration was added:

```text
0045_tenant_business_scopes
```

New control-plane tables:

- `tenant_businesses`
- `tenant_workspaces`

At startup, the application registers the businesses declared by the group entrypoint for the current tenant and creates a `default` workspace. Requests entering a business route then validate that the business and optional workspace belong to the current tenant and are enabled.

## 4. Current security boundary

Business and workspace control-plane validation is now in place, and the main Agent, knowledge-base, and channel configuration resources use data-plane filters. `workspace_id` is not treated as a complete authorization decision by itself.

Therefore:

- Existing database queries still use `tenant_id`.
- `X-Workspace-ID` alone cannot bypass existing authorization.
- The persistence batch must verify that a business and workspace belong to the current tenant and principal.

## 5. Completed next batch

The completed batch handled resource binding and data-plane filtering:

1. Define business ownership for agents, knowledge bases, channels, and similar resources.
2. Pass business context into resource services.
3. Add query filters while preserving tenant compatibility.
4. Add cross-business denial and migration regression tests.
