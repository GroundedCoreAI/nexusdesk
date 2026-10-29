# Phase 3 - Event Memory and Semantic Search: Implementation Breakdown

The existing production `memory-worker` service gains event-memory task handling; no new service is required. Its current command is:

```text
python -m agent_platform.applications.worker.memory
```

The deployment decision, pgvector requirement, task ordering, and compatibility constraints remain unchanged. This corrects the historical `apps.worker` namespace reference.
