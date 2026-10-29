# Phase 1 - Conversation Summary Memory: Test Plan

This counterpart records the refactored standalone worker entrypoint used by P1-IT-16:

```text
python -m agent_platform.applications.worker.memory
```

The test scope, acceptance criteria, lease handling, concurrent claiming, and graceful shutdown requirements are unchanged. The worker must leave no running task after cancellation.
