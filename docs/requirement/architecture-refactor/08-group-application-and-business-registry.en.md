# Phase 2: Group Entrypoint and Business Registry

> Status: Complete  
> Date: 2026-10-28

## 1. Goal

Phase 2 does not introduce Kubernetes, node pools, resource pools, or ToC/ToB deployment isolation. It solves one problem:

> A group-level entrypoint can assemble multiple businesses in one process while sharing the same Core Platform Runtime.

## 2. Implementation

New unified entrypoint:

```text
agent_platform.applications.group.main
```

New application-composition layer:

```text
agent_platform/applications/application_factory.py
agent_platform/applications/business_registry.py
agent_platform/applications/group/
```

Each `BusinessApplication` registers:

- `business_id`
- display name
- API route prefix
- business route registration function
- business-owned trusted extension bindings

Two businesses are now registered:

```text
customer-service
└── /api/v1/customer-service/*

itsm
└── /api/v1/itsm/*
```

The group entrypoint exposes:

```text
GET /api/v1/businesses
```

to list businesses registered in the process.

ITSM is currently a minimal runnable business application skeleton. It proves
that a second business can register its own routes and reuse the same Runtime;
ITSM domain features are intentionally out of scope for this phase.

## 3. Compatibility

The original entrypoint remains available:

```text
agent_platform.applications.customer_service.main
```

It keeps the historical paths, for example:

```text
/api/v1/health
/api/v1/agents
```

It reuses the same `application_factory` and `platform_runtime`; Runtime lifecycle, Worker startup/shutdown, and exception handling are not duplicated.

## 4. Extending ITSM

ITSM can add its domain routes and capability bindings on top of the existing `BusinessApplication`:

```python
BusinessRegistry(
    (
        customer_service_application("/customer-service"),
        itsm_application("/itsm"),
    )
)
```

This phase does not add a `business_id` database field or change tenant, permission, or database models. Business context and data scope are handled in Phase 3.
